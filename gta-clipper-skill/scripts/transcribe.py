#!/usr/bin/env python3
"""Transcribe a video with word-level timestamps (faster-whisper).

Usage:
  transcribe.py work/<id>/source.mp4 [--model small] [--language pt] [--beam 5]       # whole video
  transcribe.py work/<id>/source.mp4 --range 00:12:00-00:13:10 [--range ...]          # only these ranges
  transcribe.py work/<id>/source.mp4 --windows work/<id>/hype.json --top 8 --pad 20   # only the hype windows

Writes transcript.json and transcript.txt next to the video. With --range/--windows, only those
parts are transcribed (the model is loaded once) and merged into the existing transcript.json,
replacing what was inside each range. This is the fast path on slow PCs: find the moments with
find_hype.py (audio + chat + motion, no transcript needed), then transcribe just those windows.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile


def ts(s):
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def sec(t):
    v = 0.0
    for p in str(t).split(":"):
        v = v * 60 + float(p)
    return v


def merge_ranges(rs):
    out = []
    for s, e in sorted(rs):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", default="small", help="tiny|base|small|medium|large-v3")
    ap.add_argument("--language", default=None, help="e.g. pt, en (auto if omitted)")
    ap.add_argument("--beam", type=int, default=5, help="beam size (1 = fastest)")
    ap.add_argument("--range", action="append", help="only transcribe S-E (hh:mm:ss); can be repeated")
    ap.add_argument("--windows", help="hype.json from find_hype.py: transcribe its top candidates")
    ap.add_argument("--top", type=int, default=8, help="with --windows: how many candidates")
    ap.add_argument("--pad", type=float, default=20, help="with --windows: seconds added before/after each")
    a = ap.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper missing: pip install -r requirements.txt")

    out_dir = os.path.dirname(os.path.abspath(a.video))
    tpath = os.path.join(out_dir, "transcript.json")
    sec_path = os.path.join(out_dir, "section.json")

    ranges = []
    for r in a.range or []:
        s, e = (sec(x) for x in r.split("-"))
        ranges.append((s, e))
    if a.windows:
        cands = json.load(open(a.windows, encoding="utf-8"))["candidates"][:a.top]
        total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                      "csv=p=0", a.video], capture_output=True, text=True).stdout.strip() or 0)
        ranges += [(max(0, c["start"] - a.pad), min(total, c["end"] + a.pad)) for c in cands]
    ranges = merge_ranges(ranges) if ranges else [[0.0, None]]   # None = whole video

    device, ctype = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device, ctype = "cuda", "float16"
    except Exception:
        pass
    print(f"Loading whisper '{a.model}' on {device}…")
    model = WhisperModel(a.model, device=device, compute_type=ctype)

    tmp = tempfile.mkdtemp(prefix="clipper_")
    segments, words, lang, duration = [], [], None, None
    for k, (rs, re_) in enumerate(ranges, 1):
        wav = os.path.join(tmp, f"a{k}.wav")
        cut = ["-ss", f"{rs:.2f}", "-t", f"{re_ - rs:.2f}"] if re_ is not None else []
        print(f"Extracting audio {k}/{len(ranges)}" + (f" ({ts(rs)}–{ts(re_)})" if re_ is not None else "") + "…")
        subprocess.run(["ffmpeg", "-v", "error", "-y", *cut, "-i", a.video, "-vn", "-ac", "1",
                        "-ar", "16000", wav], check=True)
        segs, info = model.transcribe(wav, language=a.language, word_timestamps=True,
                                      vad_filter=True, beam_size=a.beam)
        lang = lang or info.language
        duration = info.duration if re_ is None else duration
        for s in segs:
            words.extend({"w": w.word.strip(), "s": round(w.start + rs, 2), "e": round(w.end + rs, 2)}
                         for w in (s.words or []) if w.word.strip())
            segments.append({"s": round(s.start + rs, 2), "e": round(s.end + rs, 2), "text": s.text.strip()})
            print(f"\r  transcribed {ts(s.end + rs)}", end="", flush=True)
        print()
        os.remove(wav)
    shutil.rmtree(tmp, ignore_errors=True)

    if ranges[0][1] is not None and os.path.exists(tpath):   # merge into the existing transcript
        old = json.load(open(tpath, encoding="utf-8"))

        def outside(x):
            return all(x["e"] <= rs or x["s"] >= re_ for rs, re_ in ranges)
        words = [w for w in old["words"] if outside(w)] + words
        segments = [x for x in old["segments"] if outside(x)] + segments
        duration = old.get("duration")
    words.sort(key=lambda w: w["s"]); segments.sort(key=lambda x: x["s"])
    json.dump({"language": lang, "duration": duration, "segments": segments, "words": words},
              open(tpath, "w", encoding="utf-8"), ensure_ascii=False)
    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[{ts(s['s'])}] {s['text']}\n")
    print(f"✓ {len(segments)} segments, {len(words)} words → transcript.json / transcript.txt")


if __name__ == "__main__":
    main()
