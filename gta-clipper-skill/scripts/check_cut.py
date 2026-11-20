#!/usr/bin/env python3
"""Confere (e acerta) o início e o fim dos cortes ANTES de renderizar (regras "Início e fim perfeitos" em
references/viral-rules.md).

Uso:
  check_cut.py work/<id>                  # todos os cortes do clips.json: sugestões + alertas, uma folha de frames
  check_cut.py work/<id> --apply          # idem e grava no clips.json as correções seguras (backup clips.json.bak)
  check_cut.py work/<id> --clip N         # só o corte N
  check_cut.py work/<id> --clip N --verbose   # + todas as palavras e o volume a cada 0,1 s (jeito antigo)

Para cada corte, calcula pelas regras (tempos do arquivo, palavras da passada small do transcript.json):
  início = começo da 1ª palavra − 0,15 s (nunca no meio de palavra; depois de uma troca de cena logo no começo);
  fim = 0,3 a 0,8 s depois da última palavra, no ponto mais baixo do som (risada/grito: quando cai), antes da
        próxima fala e antes de uma troca de cena.
O que precisa de olho humano vira alerta (⚠): começo sem fala (momento visual?), fala emendada logo depois do
fim, troca de cena colada na palavra, trecho sem passada small, corte curto demais.
Frames: frames/cortes.jpg, uma linha por corte: I−0,5 · I · I+1,0 | F−1,0 · F · F+0,5 (já com o ajuste).
"""
import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fmt_precise, load_config, read_json, secs, utf8_stdout, write_json  # noqa: E402

SR = 16000
STEP = 0.05         # resolução do volume (s)
START_LEAD = 0.15   # início = começo da 1ª palavra - 0,15 s
END_TAIL = (0.3, 0.8)  # fim = 0,3 a 0,8 s depois da última palavra
SPAN = 3.0


def fmt(t):
    return fmt_precise(t)


# ---------------------------------------------------------------- medições

class Audio:
    """Volume (dBFS) em janelas de STEP s. Usa o audio16k.pcm do transcribe.py se existir (instantâneo)."""
    def __init__(self, wd, src):
        self.src, self.arr = src, None
        pcm, meta = os.path.join(wd, "audio16k.pcm"), read_json(os.path.join(wd, "audio16k.json"))
        try:
            st = os.stat(src)
            if os.path.exists(pcm) and meta == {"size": st.st_size, "mtime": int(st.st_mtime)}:
                self.arr = np.memmap(pcm, dtype=np.int16, mode="r")
        except OSError:
            pass

    def db(self, a, b):
        a = max(0.0, a)
        if self.arr is not None:
            x = np.asarray(self.arr[int(a * SR):int(b * SR)], dtype=np.float32) / 32768.0
        else:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                                  "-i", self.src, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                                 stdout=subprocess.PIPE, check=True).stdout
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        n = int(SR * STEP)
        k = len(x) // n
        if not k:
            return []
        rms = np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=1)) + 1e-9
        return [(a + i * STEP, float(20 * np.log10(r))) for i, r in enumerate(rms)]


def scene_changes(src, a, b, thr=0.35):
    """Tempos (do arquivo) de troca de cena/transição entre a e b (filtro scene do ffmpeg)."""
    a = max(0.0, a)
    r = subprocess.run(["ffmpeg", "-v", "info", "-nostdin", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src, "-an",
                        "-vf", f"scale=320:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    out = []
    for line in r.stderr.splitlines():
        if "showinfo" in line and "pts_time:" in line:
            out.append(a + float(line.split("pts_time:")[1].split()[0]))
    return out


def grab(src, t, path, width):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", src,
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", path], check=True)
    return path


# ---------------------------------------------------------------- regras

def smooth(db):
    """volume suavizado (média de 3 janelas de STEP)"""
    v = np.array([d for _, d in db]) if db else np.array([])
    if len(v) >= 3:
        v = np.convolve(np.pad(v, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    return [(t, float(x)) for (t, _), x in zip(db, v)]


def plan_start(s, words, scenes):
    """-> (novo_início, nota, alertas). Correção só quando a regra é clara."""
    notes, alerts = [], []
    inside = next((w for w in words if w["s"] < s < w["e"]), None)
    if inside and (s - inside["s"]) <= (inside["e"] - s):
        w0 = inside                                     # cortou o começo da palavra: entra a palavra inteira
        notes.append(f"cortava \"{inside['w']}\" no meio: começa nela")
    else:
        if inside:
            notes.append(f"cortava o fim de \"{inside['w']}\": começa na palavra seguinte")
        w0 = next((w for w in words if w["s"] >= (inside["e"] if inside else s) - 1e-6), None)
    if w0 is None:
        alerts.append("sem palavras depois do início (só imagem?): confira nos frames")
        return s, notes, alerts
    gap = w0["s"] - s
    new = s
    if inside or not (0.05 <= gap <= 0.4):
        if gap > 1.0 and not inside:
            alerts.append(f"{gap:.1f} s sem fala até \"{w0['w']}\": só vale se for momento visual (0,5–1 s antes da "
                          f"ação); senão comece em {fmt(w0['s'] - START_LEAD)}")
            return s, notes, alerts
        new = w0["s"] - START_LEAD
    prev = [w for w in words if w["e"] <= w0["s"] + 1e-6 and w is not w0]
    if prev and prev[-1]["e"] > new:                    # palavra anterior colada: corta no meio do intervalo
        new = (prev[-1]["e"] + w0["s"]) / 2
        notes.append(f"\"{prev[-1]['w']}\" colada antes: início no meio do intervalo")
    for t in scenes:
        if new - 0.05 <= t <= new + 1.0:
            alt = t + 0.1
            if alt <= w0["s"] - 0.03:
                notes.append(f"troca de cena em {fmt(t)}: começa logo depois dela")
                new = alt
            else:
                alerts.append(f"troca de cena em {fmt(t)} ({t - new:+.2f} s), colada na 1ª palavra: confira nos frames")
    return round(new, 2), notes, alerts


def plan_end(e, words, db, scenes):
    notes, alerts = [], []
    inside = next((w for w in words if w["s"] < e < w["e"]), None)
    last = inside or next((w for w in reversed(words) if w["e"] <= e + 1e-6), None)
    if inside:
        notes.append(f"cortava \"{inside['w']}\" no meio: termina depois dela")
    if last is None:
        alerts.append("sem palavras antes do fim: confira nos frames")
        return e, notes, alerts
    nxt = next((w for w in words if w["s"] >= last["e"] - 1e-6 and w is not last), None)
    lo, hi = last["e"] + END_TAIL[0], last["e"] + END_TAIL[1]
    if nxt is not None:
        hi = min(hi, nxt["s"] - 0.1)
    cut_scene = [t for t in scenes if last["e"] - 0.05 <= t <= hi + 0.1]
    if cut_scene:
        hi = min(hi, cut_scene[0] - 0.1)
        notes.append(f"troca de cena em {fmt(cut_scene[0])}: o fim fica antes dela")
    tail = e - last["e"]
    if not inside and tail > END_TAIL[1] + 0.05:
        loud = [d for t, d in db if last["e"] + 0.2 <= t <= e]
        base = [d for t, d in db]
        if loud and base and np.median(loud) > np.percentile(base, 60):
            alerts.append(f"fim {tail:.1f} s depois de \"{last['w']}\" com som alto (risada/reação?): se não for, "
                          f"termine em {fmt(last['e'] + 0.5)}")
            return e, notes, alerts
    if hi < last["e"] + 0.1:
        mid = (last["e"] + nxt["s"]) / 2 if nxt is not None and nxt["s"] > last["e"] else last["e"] + 0.05
        if cut_scene:
            mid = min(mid, cut_scene[0] - 0.05)
        alerts.append(f"fala emendada depois de \"{last['w']}\" (\"{nxt['w'] if nxt else ''}\" logo em seguida): "
                      "o fim fica entre as palavras; confira se a frase acabou")
        return round(mid, 2), notes, alerts
    lo = min(lo, hi)
    win = [(t, d) for t, d in smooth(db) if lo - 1e-6 <= t <= hi + 1e-6]
    if lo - 0.05 <= e <= hi + 0.05 and win:
        cur = min(win, key=lambda x: abs(x[0] - e))[1]
        if cur <= min(d for _, d in win) + 3:
            return e, notes, alerts                     # já está dentro da regra e num ponto baixo do som
    best = min(win, key=lambda x: x[1])[0] if win else (lo + hi) / 2
    if nxt is not None and nxt["s"] - best < 0.3:
        alerts.append(f"fala logo depois do fim (\"{nxt['w']}\" em {fmt(nxt['s'])}): confira se não come a frase")
    return round(best + STEP / 2, 2), notes, alerts


def context(words, cut, before, after):
    """'aaa bbb ▸ccc ddd' com o tempo relativo da palavra mais perto do corte."""
    pre = [w for w in words if w["e"] <= cut + 1e-6][-before:]
    post = [w for w in words if w["e"] > cut + 1e-6][:after]
    txt = " ".join(w["w"] for w in pre) + " ‖ " + " ".join(w["w"] for w in post)
    return txt.strip()


def in_refined(tr, t):
    ref = tr.get("refined")
    if ref is None:          # transcript antigo, sem registro: não dá para saber
        return True
    return any(a <= t <= b for a, b in ref)


# ---------------------------------------------------------------- jeito antigo (--verbose)

def show_verbose(label, cut, words, db):
    print(f"  --- {label} {fmt(cut)}: palavras ---")
    for w in words:
        mark = "  <- corte no meio" if w["s"] < cut < w["e"] else ""
        print(f"    {fmt(w['s'])}–{fmt(w['e'])} ({w['s'] - cut:+.2f}s) {w['w']}{mark}")
    print(f"  --- volume (dBFS a cada {STEP:g} s) ---")
    for t, d in db[::2]:
        bar = "█" * max(0, int((d + 60) / 2))
        print(f"    {fmt(t)} ({t - cut:+.1f}) {d:6.1f} {bar}{'  <- corte' if abs(t - cut) < STEP else ''}")


# ---------------------------------------------------------------- folha de frames

def frames_sheet(src, rows, path, tmpdir, width):
    """rows = [(cid, início, fim)] -> uma linha por corte com 6 quadros."""
    from extract_frames import sheet
    jobs, srows = [], []
    for cid, s, e in rows:
        pts = [(s - 0.5, "I-0,5"), (s, "I"), (s + 1.0, "I+1"), (e - 1.0, "F-1"), (e, "F"), (e + 0.5, "F+0,5")]
        files = [os.path.join(tmpdir, f"c{cid}_{k}.jpg") for k in range(len(pts))]
        jobs += [(t, f) for (t, _), f in zip(pts, files)]
        srows.append((f"#{cid}  {fmt(s)} → {fmt(e)}", [(f, lab) for f, (_, lab) in zip(files, pts)]))
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
        list(ex.map(lambda j: grab(src, j[0], j[1], width), jobs))
    return sheet(srows, path, width)


# ---------------------------------------------------------------- main

def check_clip(clip, tr, audio, src, verbose):
    words = tr.get("words") or []
    s, e = secs(clip["start"]), secs(clip["end"])
    ws = [w for w in words if w["e"] > s - SPAN and w["s"] < s + SPAN]
    we = [w for w in words if w["e"] > e - SPAN and w["s"] < e + SPAN]
    db_e = audio.db(e - SPAN, e + SPAN)
    sc_s, sc_e = scene_changes(src, s - SPAN, s + SPAN), scene_changes(src, e - SPAN, e + SPAN)
    ns, n1, a1 = plan_start(s, ws, sc_s)
    ne, n2, a2 = plan_end(e, we, db_e, sc_e)
    for t, lab in ((s, "início"), (e, "fim")):
        if not in_refined(tr, t):
            a1.append(f"o {lab} está fora da passada small (palavras do tiny, pouco precisas): rode "
                      f"transcribe.py --range em volta dele")
    if verbose:
        show_verbose("INÍCIO", s, ws, audio.db(s - SPAN, s + SPAN))
        show_verbose("FIM", e, we, db_e)
    return {"id": int(clip["id"]), "s": s, "e": e, "ns": ns, "ne": ne, "notes": n1 + n2, "alerts": a1 + a2,
            "ctx_s": context(ws, ns, 2, 4), "ctx_e": context(we, ne, 4, 2), "hook": clip.get("hook", ""),
            "scenes": sorted(set(round(t, 2) for t in sc_s + sc_e))}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--clip", type=int, help="só este corte (padrão: todos)")
    ap.add_argument("--clips", help="clips.json (padrão: work/<id>/clips.json)")
    ap.add_argument("--apply", action="store_true", help="grava as correções no clips.json (backup .bak)")
    ap.add_argument("--no-frames", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="todas as palavras e o volume (jeito antigo)")
    ap.add_argument("--source")
    a = ap.parse_args()

    cfg = load_config()
    wd = a.workdir
    src = a.source or os.path.join(wd, "source.mp4")
    cpath = a.clips or os.path.join(wd, "clips.json")
    clips = read_json(cpath, []) or []
    todo = [c for c in clips if a.clip is None or int(c.get("id", 0)) == a.clip]
    if not todo:
        sys.exit(f"Corte {a.clip} não está no clips.json" if a.clip else "clips.json vazio")
    tr = read_json(os.path.join(wd, "transcript.json"), {}) or {}
    if not tr.get("words"):
        print("⚠ transcript.json sem palavras: rode transcribe.py --candidates antes (passada small).")
    audio = Audio(wd, src)
    with ThreadPoolExecutor(max_workers=1 if a.verbose else min(4, len(todo))) as ex:
        res = list(ex.map(lambda c: check_clip(c, tr, audio, src, a.verbose), todo))

    min_len = float(cfg.get("clip_min_seconds") or 0)   # null = sem mínimo
    changed = 0
    for r in res:
        ds, de = r["ns"] - r["s"], r["ne"] - r["e"]
        dur = r["ne"] - r["ns"]
        print(f"#{r['id']} {fmt(r['ns'])} → {fmt(r['ne'])} ({dur:.1f} s) {r['hook']}")
        print(f"  início {'ok' if abs(ds) < 0.01 else f'{ds:+.2f} s'}: {r['ctx_s']}")
        print(f"  fim {'ok' if abs(de) < 0.01 else f'{de:+.2f} s'}: {r['ctx_e']}")
        for n in r["notes"]:
            print(f"  · {n}")
        if min_len and dur < min_len:
            r["alerts"].append(f"corte com {dur:.1f} s (mínimo {min_len:g} s)")
        for al in r["alerts"]:
            print(f"  ⚠ {al}")
        if abs(ds) >= 0.01 or abs(de) >= 0.01:
            changed += 1

    if a.apply and changed:
        shutil.copyfile(cpath, cpath + ".bak")
        by_id = {r["id"]: r for r in res}
        for c in clips:
            r = by_id.get(int(c.get("id", 0)))
            if r:
                c["start"], c["end"] = fmt(r["ns"]), fmt(r["ne"])
        write_json(cpath, clips)

    if not a.no_frames:
        tmp = os.path.join(wd, "frames", "_cut")
        os.makedirs(tmp, exist_ok=True)
        fw = int(cfg.get("frames", {}).get("cut_width", 256))
        sheet = frames_sheet(src, [(r["id"], r["ns"], r["ne"]) for r in res],
                             os.path.join(wd, "frames", "cortes.jpg" if a.clip is None else f"corte{a.clip}.jpg"),
                             tmp, fw)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"Frames: {os.path.relpath(sheet, wd)}")
    n_al = sum(1 for r in res if r["alerts"])
    print(f"✓ {len(res)} cortes: {changed} com ajuste" + (" (gravado no clips.json)" if a.apply and changed else
          " (rode com --apply para gravar)" if changed else "") + f", {n_al} com alerta para olhar")


if __name__ == "__main__":
    main()
