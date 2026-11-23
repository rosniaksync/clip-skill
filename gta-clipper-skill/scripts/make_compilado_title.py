"""Gera o title.png da vinheta dos compilados de melhores momentos.

Uso: python make_compilado_title.py "CORINGA" 1 saida.png
Cores do padrão dos shorts (templates/cam.json): branco + magenta #E400EE, contorno preto.
Tamanho: 15% menor que a primeira versão (pedido 23/11/2026).
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent.parent / "fonts" / "Montserrat-Black.ttf"
W, H = 1080, 1920
MAGENTA = (228, 0, 238, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
SCALE = 0.85            # 15% menor que a versão original
BASE_SIZE = 80          # tamanho da versão original
BASE_STROKE = 7
BASE_GAP = 96           # distância entre linhas na versão original
CENTER_Y = 845          # centro do bloco (igual à versão original, acima da legenda)


def main(streamer: str, part: int, out: str) -> None:
    size = round(BASE_SIZE * SCALE)
    stroke = max(3, round(BASE_STROKE * SCALE))
    gap = round(BASE_GAP * SCALE)
    font = ImageFont.truetype(str(FONT), size)
    small = ImageFont.truetype(str(FONT), round(size * 0.5))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    lines = [("MELHORES MOMENTOS", MAGENTA), (f"{streamer.upper()} JOGANDO", WHITE), ("GTA VI", WHITE)]
    suffix = f"/ PT {part}"
    top = CENTER_Y - (gap * (len(lines) - 1) + size) // 2
    for i, (text, color) in enumerate(lines):
        y = top + i * gap
        tw = d.textlength(text, font=font)
        extra = d.textlength(" " + suffix, font=small) if i == len(lines) - 1 else 0
        x = (W - tw - extra) / 2
        d.text((x, y), text, font=font, fill=color, stroke_width=stroke, stroke_fill=BLACK)
        if extra:
            base = y + font.getbbox("G")[3]
            sy = base - small.getbbox("P")[3]
            d.text((x + tw + d.textlength(" ", font=small), sy), suffix, font=small,
                   fill=MAGENTA, stroke_width=max(2, stroke // 2), stroke_fill=BLACK)
    img.save(out)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
