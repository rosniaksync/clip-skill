#!/usr/bin/env python3
"""Monta o fundo do estilo `faixa` (1080x1920) a partir da arte de referência do usuário
(print/thumbnail no formato do short: topo, gameplay entre duas linhas rosa, palmeiras e prédios embaixo).

- Parte de baixo: a arte original (palmeiras, prédios, helicóptero), tirada logo abaixo da 2ª linha rosa.
- Parte de cima: o degradê escuro da própria arte (tirado da borda esquerda, onde não tem texto),
  sem logo/gancho/linhas (o make_shorts.py desenha o topo e o gancho por cima).
Salva em assets/fundo_faixa.png (templates/faixa.json aponta para ele).

Uso: make_faixa_bg.py <arte_referencia.png> [saida.png]
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SKILL_DIR  # noqa: E402

W, H = 1080, 1920


def pink_lines(a):
    """Linhas rosa horizontais (as bordas da faixa da gameplay): linhas em que quase a largura toda é rosa."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    pink = (r > 170) & (b > 170) & (g < 90)
    rows = np.where(pink.mean(axis=1) > 0.8)[0]
    groups = []
    for y in rows:
        if groups and y - groups[-1][-1] <= 2:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [(gr[0], gr[-1]) for gr in groups]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SKILL_DIR, "assets", "fundo_faixa.png")
    im = Image.open(src).convert("RGB").resize((W, H), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    lines = pink_lines(a)
    if len(lines) < 2:
        sys.exit(f"Não achei as duas linhas rosa da faixa na arte ({lines}).")
    art_top = lines[1][1] + 6                       # logo abaixo da linha de baixo (sem o brilho dela)

    # degradê escuro: média das colunas da borda esquerda e direita, linha por linha, suavizado
    edge = np.concatenate([a[:, 2:40], a[:, -40:-2]], axis=1).mean(axis=1)    # (H, 3)
    # as linhas rosa e a gameplay entre elas não são fundo: interpola por cima delas
    bad = np.zeros(H, bool)
    bad[max(lines[0][0] - 6, 0):art_top] = True
    ys = np.arange(H)
    for c in range(3):
        edge[bad, c] = np.interp(ys[bad], ys[~bad], edge[~bad, c])
    k = 61
    pad = np.pad(edge, ((k // 2, k // 2), (0, 0)), mode="edge")
    smooth = np.stack([np.convolve(pad[:, c], np.ones(k) / k, mode="valid") for c in range(3)], axis=1)
    base = np.repeat(smooth[:, None, :], W, axis=1)

    outa = base.copy()
    outa[art_top:] = a[art_top:]
    blend = 40                                       # emenda suave entre o degradê e a arte
    for i in range(blend):
        y = art_top + i
        t = i / blend
        outa[y] = base[y] * (1 - t) + a[y] * t
    os.makedirs(os.path.dirname(out), exist_ok=True)
    Image.fromarray(np.clip(outa, 0, 255).astype("uint8"), "RGB").save(out)
    print(f"OK {out}  (arte de baixo a partir de y={art_top})")


if __name__ == "__main__":
    main()
