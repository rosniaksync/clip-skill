#!/usr/bin/env python3
"""Mostra a transcrição para LER inteira, em linhas compactas (tempo do arquivo, M:SS ou H:MM:SS).

Uso: read_blocks.py work/<id>                 # tudo, em linhas de ~12-20 s (para ler o bloco inteiro de uma vez)
     read_blocks.py work/<id> --block 3       # só o 3º pedaço de --minutes (10) minutos
     read_blocks.py work/<id> --list          # lista os pedaços de 10 min
     read_blocks.py work/<id> --range 8:00-12:30

Linhas montadas pelas palavras do transcript.json (quebra em pausa > 1,2 s, fim de frase depois de 12 s, ou 20 s).
`◆N` no fim da linha = ali está o pico N do find_hype.py (hype.json: áudio, chat da Twitch, heatmap): só apoio.
"""
import argparse
import os
import re

from common import fmt_hms, read_json, secs, utf8_stdout


def compact_lines(tr, max_len=20.0, soft_len=12.0, pause=1.2):
    """[(início, fim, texto)] a partir das palavras (ou das frases, se não houver palavras)."""
    words = tr.get("words") or []
    if not words:
        return [(s["s"], s["e"], s["text"]) for s in tr.get("segments") or []]
    out, cur = [], []
    for w in words:
        if cur:
            dur = cur[-1]["e"] - cur[0]["s"]
            gap = w["s"] - cur[-1]["e"]
            end_sentence = re.search(r"[.!?…]$", cur[-1]["w"])
            if gap > pause or dur >= max_len or (dur >= soft_len and end_sentence):
                out.append((cur[0]["s"], cur[-1]["e"], " ".join(x["w"] for x in cur)))
                cur = []
        cur.append(w)
    if cur:
        out.append((cur[0]["s"], cur[-1]["e"], " ".join(x["w"] for x in cur)))
    return out


def hype_marks(workdir, top=10):
    """{rank: tempo do pico} dos `top` primeiros do hype.json."""
    h = read_json(os.path.join(workdir, "hype.json"), {}) or {}
    out = {}
    for c in (h.get("candidates") or [])[:top]:
        out[c["rank"]] = secs(c.get("peak_ts") or c["start"])
    return out


def render(lines, marks=None, t0=None, t1=None):
    marks = marks or {}
    rows = []
    for k, (s, e, text) in enumerate(lines):
        if t0 is not None and e < t0:
            continue
        if t1 is not None and s > t1:
            break
        nxt = lines[k + 1][0] if k + 1 < len(lines) else e + 1e9
        tag = "".join(f" ◆{r}" for r, p in sorted(marks.items()) if s - 0.5 <= p < max(nxt, e))
        rows.append(f"[{fmt_hms(s)}] {text}{tag}")
    return "\n".join(rows)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--block", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--range")
    ap.add_argument("--no-hype", action="store_true")
    a = ap.parse_args()

    tr = read_json(os.path.join(a.workdir, "transcript.json"))
    if not tr:
        raise SystemExit("transcript.json não existe: rode transcribe.py antes")
    lines = compact_lines(tr)
    marks = {} if a.no_hype else hype_marks(a.workdir)
    size = a.minutes * 60
    if a.list:
        blocks = {}
        for s, _, _ in lines:
            blocks[int(s // size) + 1] = blocks.get(int(s // size) + 1, 0) + 1
        for b, n in sorted(blocks.items()):
            print(f"pedaço {b}: {n} linhas  (começa em {int((b - 1) * size // 60)} min)")
        return
    t0 = t1 = None
    if a.block:
        t0, t1 = (a.block - 1) * size, a.block * size
    elif a.range:
        t0, t1 = (secs(x) for x in a.range.split("-"))
    print(render(lines, marks, t0, t1))


if __name__ == "__main__":
    main()
