#!/usr/bin/env python3
"""Score every moment of the stream for 'hype' using objective signals.

Signals (each z-scored, then combined):
  - audio: loudness spikes vs. the stream's own baseline (screams, laughs, explosions)
  - chat: volume, reaction spam and 'clipa' calls (only if chat.json exists); 'clipa' weighs most
  - speech: rate + excited words = weak reinforcement (the model may spell or cut swear words)
  Text is normalised first (lowercase, no accents, repeated letters collapsed).
  Word lists and weights live in config.json -> hype.

Usage: find_hype.py work/<id> [--window 30] [--top 25]
       find_hype.py work/<id> --words 00:08:05-00:08:35   # most frequent words in a window
Writes hype.json and prints the top candidate windows with transcript snippets.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata

import numpy as np

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_hype_cfg():
    with open(os.path.join(SKILL_DIR, "config.json"), encoding="utf-8") as f:
        return json.load(f)["hype"]


def norm(text):
    """lowercase, no accents, repeated letters collapsed ("caraaaalho" -> "caralho", "kkkkkkk" -> "kk")."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    out = []
    for m in re.finditer(r"(.)\1*", t):
        ch, run = m.group(1), len(m.group(0))
        out.append(ch * (min(run, 2) if ch == "k" else 1) if ch.isalpha() else m.group(0))
    return "".join(out)


def word_regex(words):
    """whole-word match on normalised text (multi-word phrases allowed)."""
    ws = sorted({norm(w) for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in ws) + r")(?![a-z0-9])")


def tokens(text):
    return re.findall(r"[a-z0-9]+", norm(text))


def ts(s):
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def audio_db_per_sec(video):
    sr = 8000
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], stdout=subprocess.PIPE)
    out = []
    while True:
        buf = p.stdout.read(sr * 2)
        if not buf:
            break
        x = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
        # use the loudest 100ms inside each second — catches short screams
        n = len(x) // 800 * 800
        if n == 0:
            out.append(-90.0); continue
        rms = np.sqrt(np.mean(x[:n].reshape(-1, 800) ** 2, axis=1) + 1e-10)
        out.append(float(20 * np.log10(rms.max())))
    p.wait()
    return np.array(out)


def chat_per_sec(path, n, offset, cfg):
    """per-second chat volume, reaction count and 'clipa' calls (texts normalised first)."""
    msgs = np.zeros(n); hype = np.zeros(n); clips = np.zeros(n)
    if not os.path.exists(path):
        return None, None, None
    react, clip = word_regex(cfg["chat_reaction_words"]), word_regex(cfg["clip_call_words"])

    def add(t, text):
        i = int(t - offset)
        if 0 <= i < n:
            msgs[i] += 1
            nt = norm(text)
            if react.search(nt):
                hype[i] += 1
            if clip.search(nt):
                clips[i] += 1

    with open(path, encoding="utf-8") as f:
        head = f.read(200)
        f.seek(0)
        if '"source": "twitch"' in head:  # normalised Twitch chat from download.py
            for m in json.load(f)["messages"]:
                add(m["t"], m.get("text") or "")
            return msgs, hype, clips
        for line in f:  # YouTube live_chat replay (one JSON per line)
            try:
                d = json.loads(line)
                act = d.get("replayChatItemAction", {})
                t = int(act.get("videoOffsetTimeMsec", 0)) / 1000.0
                text = ""
                for a_ in act.get("actions", []):
                    item = a_.get("addChatItemAction", {}).get("item", {})
                    r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
                    if r:
                        text = "".join(run.get("text", run.get("emoji", {}).get("shortcuts", [""])[0])
                                       for run in r.get("message", {}).get("runs", []))
            except Exception:
                continue
            add(t, text)
    return msgs, hype, clips


def motion_per_sec(video, n):
    """Mean frame-to-frame change per second (keyframes only = fast). Near 0 = static screen (menu, loading)."""
    w, h = 64, 36
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-skip_frame", "nokey", "-i", video, "-an",
                          "-vf", f"fps=1,scale={w}:{h},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         stdout=subprocess.PIPE)
    out, prev = np.zeros(n), None
    for i in range(n):
        buf = p.stdout.read(w * h)
        if len(buf) < w * h:
            break
        cur = np.frombuffer(buf, dtype=np.uint8).astype(np.float32)
        if prev is not None:
            out[i] = float(np.abs(cur - prev).mean())
        prev = cur
    p.stdout.close(); p.wait()
    return out


def z(x, cap=8.0):
    x = np.asarray(x, dtype=float)
    sd = x.std()
    return np.clip((x - x.mean()) / sd, -cap, cap) if sd > 0 else np.zeros_like(x)


def window_sum(x, w):
    c = np.concatenate([[0], np.cumsum(x)])
    return c[w:] - c[:-w]


def top_words(workdir, rng, cfg, n=15):
    from collections import Counter

    def sec(t):
        v = 0.0
        for p in t.split(":"):
            v = v * 60 + float(p)
        return v
    s0, e0 = (sec(x) for x in rng.split("-"))
    stop = {norm(w) for w in cfg["stopwords"]}
    sec_path = os.path.join(workdir, "section.json")
    off = json.load(open(sec_path))["offset"] if os.path.exists(sec_path) else 0.0
    sp, ch = Counter(), Counter()
    tr = json.load(open(os.path.join(workdir, "transcript.json"), encoding="utf-8"))
    for w in tr["words"]:
        if s0 <= w["s"] + off < e0:
            sp.update(t for t in tokens(w["w"]) if t not in stop)
    cp = os.path.join(workdir, "chat.json")
    if os.path.exists(cp):
        for m in json.load(open(cp, encoding="utf-8")).get("messages", []):
            if s0 <= m["t"] < e0 and not (m.get("text") or "").startswith("!"):
                ch.update(t for t in tokens(m["text"]) if t not in stop)
    fmt = lambda c: ", ".join(f"{w} ({k})" for w, k in c.most_common(n))
    print(f"Janela {rng} (texto normalizado: minusculo, sem acento, letras repetidas reduzidas)")
    print("  Fala :", fmt(sp))
    print("  Chat :", fmt(ch))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--words", help="most frequent words (chat + speech) in S-E, e.g. 00:08:05-00:08:35")
    a = ap.parse_args()
    cfg = load_hype_cfg()

    if a.words:
        return top_words(a.workdir, a.words, cfg)

    video = os.path.join(a.workdir, "source.mp4")
    tpath = os.path.join(a.workdir, "transcript.json")
    tr = json.load(open(tpath, encoding="utf-8")) if os.path.exists(tpath) else {"words": [], "segments": []}
    has_tr = bool(tr["words"])
    sec_path = os.path.join(a.workdir, "section.json")
    offset = json.load(open(sec_path))["offset"] if os.path.exists(sec_path) else 0.0

    print("Measuring audio loudness…")
    db = audio_db_per_sec(video)
    n = len(db)
    if n < a.window:
        a.window = max(5, n // 2)

    # audio: how far above the local (2-min rolling median) baseline each second is
    k = 120
    pad = np.pad(db, (k // 2, k - k // 2 - 1), mode="edge")
    base = np.convolve(pad, np.ones(k) / k, mode="valid")[:n]
    audio = np.clip(db - base, 0, None)

    wps = np.zeros(n); exc = np.zeros(n)
    sw = word_regex(cfg["speech_words"])
    for w in tr["words"]:
        i = int(w["s"])
        if 0 <= i < n:
            wps[i] += 1
            if sw.search(norm(w["w"])):
                exc[i] += 1

    msgs, chype, clips = chat_per_sec(os.path.join(a.workdir, "chat.json"), n, offset, cfg)

    W = a.window
    wt, cap = cfg["weights"], cfg.get("z_cap", 8)
    # main signals: audio loudness and chat. Words are only weak reinforcement.
    score = (wt["audio"] * z(window_sum(audio, W), cap) + wt["speech_rate"] * z(window_sum(wps, W), cap)
             + wt["speech_words"] * z(window_sum(exc, W), cap))
    signals = ["audio"] + (["speech-rate", "speech-words"] if has_tr else [])
    if msgs is not None and msgs.sum() > 20:
        lag = int(cfg.get("chat_lag_seconds", 8))   # chat reacts late: shift it back
        sh = lambda x: np.concatenate([x[lag:], np.zeros(lag)])
        score += (wt["chat_volume"] * z(window_sum(sh(msgs), W), cap)
                  + wt["chat_reactions"] * z(window_sum(sh(chype), W), cap))
        signals += ["chat-volume", "chat-reactions"]
        n_clip = int(clips.sum())
        if n_clip:  # the audience pointing at the moment: heaviest signal
            # grows with the number of "clipa" messages in the window: 1 lone message must not dominate
            cnt = window_sum(sh(clips), W)
            full = float(cfg.get("clip_calls_full_at", 5))
            score += wt["clip_calls"] * float(cfg.get("clip_calls_max_boost", 6)) * np.minimum(cnt, full) / full
            signals.append(f"clip-calls({n_clip})")

    # gameplay gate: drop windows with a (nearly) static picture (menus, loading, idle screens)
    gate_p = cfg.get("motion_gate_percentile", 0)
    if gate_p:
        print("Measuring picture motion…")
        mot = motion_per_sec(video, n)
        wm = window_sum(mot, W) / W
        thr = np.percentile(wm, gate_p)
        dead = wm < thr
        score = np.where(dead, -1e9, score)
        signals.append(f"motion-gate(>{gate_p}%)")

    # pick non-overlapping top windows
    order = np.argsort(-score)
    picked = []
    for i in order:
        if all(abs(i - j) >= W for j, _ in picked):
            picked.append((int(i), float(score[i])))
        if len(picked) >= a.top:
            break

    segs = tr["segments"]
    results = []
    for rank, (i, sc) in enumerate(picked, 1):
        s, e = i, i + W
        text = " ".join(x["text"] for x in segs if x["e"] > s and x["s"] < e)
        peak = s + int(np.argmax(audio[s:e])) if e <= n else s
        results.append({"rank": rank, "start": s, "end": e, "start_ts": ts(s), "end_ts": ts(e),
                        "peak_ts": ts(peak), "score": round(sc, 2), "text": text[:400]})

    json.dump({"signals": signals, "window": W, "candidates": results},
              open(os.path.join(a.workdir, "hype.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"Signals used: {', '.join(signals)}\n")
    for r in results:
        print(f"#{r['rank']:>2}  {r['start_ts']}–{r['end_ts']}  peak {r['peak_ts']}  score {r['score']}")
        if r["text"]:
            print(f"     {r['text'][:180]}")
    if has_tr:
        print(f"\n✓ {len(results)} candidates → hype.json  (now read transcript.txt and choose clips)")
    else:
        print(f"\n✓ {len(results)} candidates → hype.json  (no transcript yet: transcribe only these windows with\n"
              f"  transcribe.py {a.workdir}/source.mp4 --windows {a.workdir}/hype.json --top 8 --language pt)")


if __name__ == "__main__":
    main()
