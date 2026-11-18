#!/usr/bin/env python3
"""Confere o início e o fim de um corte ANTES de renderizar (regras "Início e fim perfeitos" em
references/viral-rules.md).

Uso:
  check_cut.py work/<id> --clip N            # corte N do clips.json
  check_cut.py work/<id> --clip N --span 3   # janela em volta do início e do fim (padrão 3 s)

Mostra, para o início e para o fim do corte (tempos do arquivo):
  1. as palavras com tempo de `span` s antes a `span` s depois (transcript.json, passada small);
  2. o volume do áudio a cada 0,1 s nesses trechos (dBFS + barra), com a marca do corte;
  3. uma folha de frames: frames/cut<N>_inicio.jpg e frames/cut<N>_fim.jpg (mesmo jeito do extract_frames.py);
  4. alertas: corte no meio de uma palavra, folga do início/fim fora da regra, fala logo depois do fim.
"""
import argparse, json, os, subprocess, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import secs, read_json  # noqa: E402

SR = 16000
STEP = 0.1          # resolução do volume (s)
START_LEAD = 0.15   # início = começo da 1ª palavra - 0,15 s
END_TAIL = (0.3, 0.8)  # fim = 0,3 a 0,8 s depois da última palavra


def fmt(t):
    t = max(0.0, t)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def audio_db(src, a, b):
    """dBFS a cada STEP s entre a e b (tempo do arquivo)."""
    a = max(0.0, a)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src,
                          "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(SR * STEP)
    out = []
    for i in range(0, len(x) // n):
        rms = float(np.sqrt(np.mean(x[i * n:(i + 1) * n] ** 2)) + 1e-9)
        out.append((a + i * STEP, 20 * np.log10(rms)))
    return out


def scene_changes(src, a, b, thr=0.35):
    """Tempos (do arquivo) de troca de cena/transição entre a e b (filtro scene do ffmpeg)."""
    a = max(0.0, a)
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src, "-an",
                        "-vf", f"scale=320:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    out = []
    for line in r.stderr.splitlines():
        if "showinfo" in line and "pts_time:" in line:
            out.append(a + float(line.split("pts_time:")[1].split()[0]))
    return out


def frame_sheet(src, times, path, tmpdir, tag):
    """Mesmo jeito do extract_frames.py: frames 640px + tile 3xN."""
    for n, t in enumerate(times, 1):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", src, "-frames:v", "1",
                        "-vf", "scale=640:-2", os.path.join(tmpdir, f"{tag}_{n}.jpg")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", os.path.join(tmpdir, f"{tag}_%d.jpg"),
                    "-vf", f"tile=3x{(len(times) + 2) // 3}", "-frames:v", "1", path], check=True)


def show(label, cut, words, db, kind, scenes=()):
    print(f"\n=== {label}: {fmt(cut)} ===")
    print("Palavras (tempo do arquivo):")
    marked = False
    for w in words:
        inside = w["s"] < cut < w["e"]
        if not marked and (w["s"] >= cut or inside):
            print(f"  ── corte {fmt(cut)} ──")
            marked = True
        mark = "  <- corte no meio desta palavra" if inside else ""
        print(f"    {fmt(w['s'])}–{fmt(w['e'])} ({w['s'] - cut:+.2f}s) {w['w'].strip()}{mark}")
    if not marked:
        print(f"  ── corte {fmt(cut)} ──")
    print("Volume (dBFS a cada 0,1 s):")
    for t, d in db:
        bar = "█" * max(0, int((d + 60) / 2))
        here = "  <- corte" if abs(t - cut) < STEP / 2 + 1e-6 else ""
        print(f"  {fmt(t)} ({t - cut:+.1f}) {d:6.1f} {bar}{here}")

    # alertas pelas regras
    alerts = []
    inside = [w for w in words if w["s"] < cut < w["e"]]
    if inside:
        w0 = inside[0]
        fix = (f"início = {fmt(w0['s'] - START_LEAD)} (palavra - {START_LEAD} s)" if kind == "inicio"
               else f"fim entre {fmt(w0['e'] + END_TAIL[0])} e {fmt(w0['e'] + END_TAIL[1])}, onde o volume cair")
        alerts.append(f"o corte cai no meio da palavra \"{w0['w'].strip()}\": {fix}")
    if kind == "inicio":
        nxt = [w for w in words if w["s"] >= cut - 1e-6]
        if nxt and not inside:
            gap = nxt[0]["s"] - cut
            if gap > 1.0:
                alerts.append(f"{gap:.2f} s até a primeira palavra (\"{nxt[0]['w'].strip()}\"): sem fala no começo; "
                              "só vale se for um momento visual (0,5 a 1 s antes da ação)")
            elif gap < 0.05 or gap > 0.4:
                alerts.append(f"primeira palavra começa {gap:+.2f} s depois do corte; regra: "
                              f"início = {fmt(nxt[0]['s'] - START_LEAD)} (palavra - {START_LEAD} s)")
    else:
        prev = [w for w in words if w["e"] <= cut + 1e-6]
        after = [w for w in words if w["s"] >= cut]
        if prev and not inside:
            tail = cut - prev[-1]["e"]
            if not (END_TAIL[0] - 0.05 <= tail <= END_TAIL[1] + 0.05):
                alerts.append(f"o fim fica {tail:.2f} s depois da última palavra (\"{prev[-1]['w'].strip()}\"); "
                              f"regra: {fmt(prev[-1]['e'] + END_TAIL[0])} a {fmt(prev[-1]['e'] + END_TAIL[1])}")
        if after and after[0]["s"] - cut < 0.3:
            alerts.append(f"tem fala logo depois do fim (\"{after[0]['w'].strip()}\" em {fmt(after[0]['s'])}): "
                          "confira se o corte não come a frase")
        near = [d for t, d in db if cut - 0.15 <= t <= cut + 0.05]   # o som bem no ponto do corte
        peak = max((d for _, d in db), default=-99)
        if near and max(near) > peak - 3:
            alerts.append("o fim está no pico do som (risada/grito): corte quando o volume começa a cair")
    for t in scenes:
        # o short não pode começar com uma transição nem terminar mostrando a cena seguinte
        if kind == "inicio" and -0.05 <= t - cut <= 1.0:
            alerts.append(f"troca de cena/transição em {fmt(t)} ({t - cut:+.2f} s): não comece num corte de câmera; "
                          f"comece depois dele, em {fmt(t + 0.1)} ou mais")
        if kind == "fim" and -1.0 <= t - cut <= 0.05:
            alerts.append(f"troca de cena/transição em {fmt(t)} ({t - cut:+.2f} s): o fim tem que ficar antes dela "
                          f"(até {fmt(t - 0.1)}), mesmo que a folga depois da palavra fique menor")
        if kind == "fim" and 0.05 < t - cut <= 1.0:
            print(f"  (ok: a troca de cena em {fmt(t)} fica depois do fim, o fim não pode passar dela)")
    if scenes:
        print("Trocas de cena na janela: " + ", ".join(f"{fmt(t)} ({t - cut:+.2f}s)" for t in scenes))
    print("Alertas:" if alerts else "Alertas: nenhum (confira os frames mesmo assim)")
    for a in alerts:
        print(f"  ⚠ {a}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--clip", type=int, required=True)
    ap.add_argument("--clips", help="clips.json (padrão: work/<id>/clips.json)")
    ap.add_argument("--span", type=float, default=3.0)
    ap.add_argument("--source")
    a = ap.parse_args()

    wd = a.workdir
    src = a.source or os.path.join(wd, "source.mp4")
    clips = read_json(a.clips or os.path.join(wd, "clips.json"), []) or []
    clip = next((c for c in clips if int(c.get("id", 0)) == a.clip), None)
    if not clip:
        sys.exit(f"Corte {a.clip} não está no clips.json")
    tr = read_json(os.path.join(wd, "transcript.json"), {}) or {}
    words = tr.get("words") or []
    if not words:
        print("⚠ transcript.json sem palavras: rode transcribe.py --candidates antes (passada small).")
    s, e = secs(clip["start"]), secs(clip["end"])
    sp = a.span
    print(f"Corte {a.clip}: {fmt(s)} → {fmt(e)}  ({e - s:.1f} s)  gancho: {clip.get('hook', '')}")

    out = os.path.join(wd, "frames")
    tmp = os.path.join(out, f"_cut{a.clip}")
    os.makedirs(tmp, exist_ok=True)
    for cut, label, kind in ((s, "INÍCIO", "inicio"), (e, "FIM", "fim")):
        win = [w for w in words if w["e"] > cut - sp and w["s"] < cut + sp]
        show(label, cut, win, audio_db(src, cut - sp, cut + sp), kind, scene_changes(src, cut - sp, cut + sp))
        times = [cut - 1.0, cut - 0.5, cut, cut + 0.5, cut + 1.0, cut + 1.5] if kind == "inicio" \
            else [cut - 1.5, cut - 1.0, cut - 0.5, cut, cut + 0.5, cut + 1.0]
        sheet = os.path.join(out, f"cut{a.clip}_{kind}.jpg")
        frame_sheet(src, times, sheet, tmp, kind)
        print(f"Frames: {os.path.relpath(sheet, wd)}  (em ordem: "
              + ", ".join(f"{t - cut:+.1f}s" for t in times) + ")")
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)


if __name__ == "__main__":
    main()
