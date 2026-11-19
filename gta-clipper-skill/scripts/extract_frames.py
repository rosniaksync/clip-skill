#!/usr/bin/env python3
"""Frames dos candidatos para OLHAR (momentos visuais sem fala, bate-papo só com webcam, menu/loading).

Uso: extract_frames.py work/<id> --candidates cands.json [--frames 4] [--width 320] [--per-sheet 5] [--ids 1,3]
     extract_frames.py work/<id> --candidates cands.json --per-candidate   # também cand<id>.jpg (jeito antigo)
cands.json: [{"id": 1, "start": "00:08:05", "end": "00:08:40"}, ...]

Grava work/<id>/frames/cands_1.jpg, cands_2.jpg...: uma folha com vários candidatos (uma linha por candidato,
`--frames` quadros espalhados, com o id e o tempo de cada quadro escritos). Menos imagens = menos tokens.
Extração em paralelo (ffmpeg com seek rápido; use a cópia leve do modo análise, que é muito mais rápida).
Padrões em config.json -> frames.
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont

from common import SKILL_DIR, fmt_hms, load_config, secs, utf8_stdout


def grab(src, t, path, width):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", src,
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", path], check=True)
    return path


def font(size):
    try:
        return ImageFont.truetype(os.path.join(SKILL_DIR, "fonts", "Montserrat-Black.ttf"), size)
    except OSError:
        return ImageFont.load_default()


def sheet(rows, path, width, label_h=22):
    """rows = [(rótulo, [(arquivo, rótulo_do_quadro), ...])] -> uma imagem, uma linha por item."""
    ims = [[(Image.open(f).convert("RGB"), lab) for f, lab in fr] for _, fr in rows]
    h = max((im.height for r in ims for im, _ in r), default=180)
    cols = max(len(r) for r in ims)
    out = Image.new("RGB", (cols * width + (cols - 1) * 4, len(rows) * (h + label_h) + (len(rows) - 1) * 6), (0, 0, 0))
    d = ImageDraw.Draw(out)
    f_row, f_fr = font(16), font(13)
    y = 0
    for (title, _), r in zip(rows, ims):
        d.text((4, y + 2), title, font=f_row, fill=(255, 220, 0))
        for k, (im, lab) in enumerate(r):
            x = k * (width + 4)
            out.paste(im, (x, y + label_h))
            if lab:
                tw = d.textlength(lab, font=f_fr)
                d.rectangle([x + width - tw - 8, y + label_h + 2, x + width - 2, y + label_h + 18], fill=(0, 0, 0))
                d.text((x + width - tw - 5, y + label_h + 3), lab, font=f_fr, fill=(255, 255, 255))
        y += h + label_h + 6
    out.save(path, quality=82)
    return path


def main():
    utf8_stdout()
    fcfg = load_config().get("frames", {})
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--frames", type=int, default=int(fcfg.get("per_candidate", 4)))
    ap.add_argument("--width", type=int, default=int(fcfg.get("width", 320)))
    ap.add_argument("--per-sheet", type=int, default=int(fcfg.get("per_sheet", 5)))
    ap.add_argument("--ids", help="só estes ids (ex.: 1,3,5)")
    ap.add_argument("--per-candidate", action="store_true", help="também grava cand<id>.jpg (uma folha por candidato)")
    ap.add_argument("--source")
    a = ap.parse_args()
    src = a.source or os.path.join(a.workdir, "source.mp4")
    out = os.path.join(a.workdir, "frames")
    os.makedirs(out, exist_ok=True)
    cands = json.load(open(a.candidates, encoding="utf-8"))
    keep = {int(x) for x in a.ids.split(",")} if a.ids else None

    jobs, rows = [], []
    for i, c in enumerate(cands, 1):
        cid = c.get("id", i)
        if keep is not None and int(cid) not in keep:
            continue
        s, e = secs(c["start"]), secs(c["end"])
        step = (e - s) / a.frames
        times = [s + step * (n + .5) for n in range(a.frames)]
        files = [os.path.join(out, f"cand{cid}_{n + 1}.jpg") for n in range(a.frames)]
        jobs += list(zip(times, files))
        rows.append((f"#{cid}  {fmt_hms(s)}–{fmt_hms(e)}", [(f, fmt_hms(t)) for f, t in zip(files, times)]))
    if not rows:
        sys.exit("Nenhum candidato para extrair.")
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
        list(ex.map(lambda j: grab(src, j[0], j[1], a.width), jobs))

    sheets = []
    for k in range(0, len(rows), a.per_sheet):
        sheets.append(sheet(rows[k:k + a.per_sheet], os.path.join(out, f"cands_{k // a.per_sheet + 1}.jpg"), a.width))
    if a.per_candidate:
        for title, fr in rows:
            cid = title.split()[0][1:]
            sheet([(title, fr)], os.path.join(out, f"cand{cid}.jpg"), a.width)
    print("Frames: " + "  ".join(os.path.relpath(p, a.workdir) for p in sheets)
          + f"  ({len(rows)} candidatos, {a.frames} quadros cada)")


if __name__ == "__main__":
    main()
