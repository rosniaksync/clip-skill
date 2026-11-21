#!/usr/bin/env python3
"""Render clips.json into finished 1080x1920 shorts using one of two styles.

Styles (each one is a JSON template in ../templates/<style>.json):
  cam    video WITH webcam: facecam on top, gameplay below, title card on the split
  nocam  video WITHOUT webcam: blurred background, round logo + hook on top, gameplay in the middle

Every colour, font, size, position and the channel name live in the templates.
Each clip in clips.json carries "style", "hook" and "subhook".

Each short is rendered from start - pad_before to end + pad_after (config.json, clamped to the video).
With pad_before = pad_after = 0 (default) the file is exactly the chosen cut, ready to post. A clip with
"folga": true gets pad_folga seconds before and after ("esse com folga"). The cut inside the file is printed,
saved in shorts/renders.json and written to shorts/posting-kit.md.

Foreign-language video (lang.json != pt): captions come from the clip's "captions_pt"
([{"s","e","text"}] in file time, written by Claude). Export the original phrases to translate with
--export-captions N (writes work/<id>/captions_<N>.json).

Usage:
  make_shorts.py work/<id> --snapshot                   # frames to detect webcam / burned-in subs
  make_shorts.py work/<id> --cam 0.72,0.68,0.27,0.30    # save webcam box (x,y,w,h fractions) and render
  make_shorts.py work/<id> --burned-subs                # source already has subtitles -> no captions
  make_shorts.py work/<id> [--only 1,4] [--style cam|nocam] [--template-dir DIR]
  make_shorts.py work/<id> --export-captions 2          # original caption phrases of clip 2 (to translate)
  make_shorts.py work/<id> --preview                    # contact sheet of rendered shorts
  make_shorts.py work/<id> --kit                        # rewrite posting-kit.md only

Per-video choices are saved in work/<id>/setup.json (cam box, burned_subs).
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

from common import SKILL_DIR, load_config, mmss, read_json, section_offset, write_json
from common import ts as hms
STYLES = ("cam", "nocam", "faixa")
FPS = 30

# ---------------------------------------------------------------- helpers

from common import no_power_throttling, secs  # noqa: E402


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def clean_ass(w):
    return w.replace("{", "(").replace("}", ")").replace("\\", "")


EMOJI_RE = re.compile("[\U0001F000-\U0001FFFF←-⇿☀-➿⬀-⯿️‍]")


def clean_text(s, upper):
    s = EMOJI_RE.sub("", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper() if upper else s


def hex_rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def ass_color(c):  # "#RRGGBB" -> &H00BBGGRR
    r, g, b = hex_rgb(c)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def ffprobe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "csv=p=0", path]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def duration(path):
    from common import probe_av
    return float(probe_av(path)["duration"] or 0)


def load_template(tdir, style):
    path = os.path.join(tdir, f"{style}.json")
    if not os.path.exists(path):
        sys.exit(f"Template não encontrado: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- fonts

def resolve_font(spec):
    """spec = {"file": "fonts/X.ttf"}: direct path, absolute or relative to the skill folder. No searching."""
    path = spec["file"]
    if not os.path.isabs(path):
        path = os.path.join(SKILL_DIR, path)
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        sys.exit(f"Fonte não encontrada: {path}")
    return path


def pil_font(path, size):
    return ImageFont.truetype(path, size)


def fit_font(text, spec, size, min_size, max_width, tdir, stroke=0):
    path = resolve_font(spec)
    while True:
        f = pil_font(path, size)
        w = f.getlength(text) + 2 * stroke
        if w <= max_width or size <= min_size:
            return f
        size -= 2


# ---------------------------------------------------------------- title images (Pillow)

ONE_LINE_MAX_CHARS = 18      # frase até isso cabe numa linha só; maior que isso quebra em 2 linhas


def lines_of(clip):
    """O card mostra UMA frase só (o `hook`), quebrada em até 2 linhas balanceadas, mesmo estilo nas duas.
    `subhook` (clips.json antigos) é emendado ao hook como continuação da mesma frase."""
    phrase = " ".join(x.strip() for x in (clip.get("hook", ""), clip.get("subhook", "")) if x and x.strip())
    words = phrase.split()
    if len(phrase) <= ONE_LINE_MAX_CHARS or len(words) < 2:
        return [phrase, ""]
    best = min(range(1, len(words)),
               key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return [" ".join(words[:best]), " ".join(words[best:])]


def _stops(colors):
    return [hex_rgb(c) for c in (colors if isinstance(colors, list) else [colors, colors])]


def grad_img(w, h, colors, horizontal=True):
    """RGBA gradient through 2+ colours ("#RRGGBB"), left->right (or top->bottom)."""
    import numpy as np
    st = np.array(_stops(colors), dtype=float)
    n = w if horizontal else h
    t = np.linspace(0, len(st) - 1, n)
    row = np.stack([np.interp(t, np.arange(len(st)), st[:, k]) for k in range(3)], axis=1).astype("uint8")
    arr = np.tile(row[None, :, :], (h, 1, 1)) if horizontal else np.tile(row[:, None, :], (1, w, 1))
    return Image.fromarray(arr, "RGB").convert("RGBA")


def fill_img(w, h, solid=None, gradient=None, horizontal=True):
    return grad_img(w, h, gradient, horizontal) if gradient else Image.new("RGBA", (w, h), hex_rgb(solid) + (255,))


def skill_path(rel):
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(SKILL_DIR, rel))


def load_logo(spec, size):
    im = Image.open(skill_path(spec["file"])).convert("RGBA")
    if spec.get("crop"):
        im = im.crop(tuple(spec["crop"]))
    if spec.get("pad"):   # fit a square logo inside the circle: black margin so the corners are not cut
        side = int(im.width * (1 + spec["pad"]))
        bgc = Image.new("RGBA", (side, side), im.getpixel((2, 2)))
        bgc.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
        im = bgc
    if spec.get("circle"):
        m = Image.new("L", im.size, 0)
        ImageDraw.Draw(m).ellipse([0, 0, im.width - 1, im.height - 1], fill=255)
        im.putalpha(m)
    elif spec.get("rounded"):   # rounded square: corner radius as a fraction of the side
        m = Image.new("L", im.size, 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1],
                                            int(min(im.size) * spec["rounded"]), fill=255)
        im.putalpha(m)
    return im.resize((size, size), Image.LANCZOS)


def rr_mask(w, h, rad, inset=0):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([inset, inset, w - 1 - inset, h - 1 - inset], max(rad - inset, 0), fill=255)
    return m


def render_label(tpl, clip, W):
    """Etiqueta (pedido 21/11/2026): linha branca de lado a lado na divisa + retângulo branco pequeno
    com o gancho numa linha só, texto preto e 'GTA 6' (ou *palavra*) na cor de destaque.
    Retorna (imagem da largura do vídeo, centro_y, topo_da_etiqueta)."""
    import re
    c = tpl["card"]
    lb = c["label"]
    text = clean_text(" ".join(x.strip() for x in (clip.get("hook", ""), clip.get("subhook", "")) if x and x.strip()),
                      c.get("uppercase", True))
    if not text:
        return None
    pat = re.compile(lb.get("highlight_regex", r"GTA ?(6|VI)"), re.I)
    parts, pos = [], 0
    for mt in re.finditer(r"\*([^*]+)\*|" + pat.pattern, text, re.I):
        if mt.start() > pos:
            parts.append((text[pos:mt.start()], lb["color"]))
        parts.append((mt.group(1) or mt.group(0), lb["highlight_color"]))
        pos = mt.end()
    if pos < len(text):
        parts.append((text[pos:], lb["color"]))
    parts = [(t.replace("*", ""), col) for t, col in parts if t]
    # palavras com a cor de cada uma (para poder quebrar em 2 linhas sem perder o destaque)
    words = []
    for t, col in parts:
        for i, w in enumerate(re.split(r"(\s+)", t)):
            if not w:
                continue
            if w.isspace():
                words.append((" ", col))
            else:
                words.append((w, col))
    fpath = resolve_font(lb["font"])
    maxw = c.get("max_width", 1000) - 2 * lb["padding_x"]
    max_lines = lb.get("max_lines", 1)

    def width(seq, f):
        return sum(f.getlength(t) for t, _ in seq)

    def strip(seq):
        while seq and seq[0][0] == " ":
            seq = seq[1:]
        while seq and seq[-1][0] == " ":
            seq = seq[:-1]
        return seq

    def best_split(f):
        idx = [i for i, (t, _) in enumerate(words) if t == " "]
        best = None
        for i in idx:
            a, b2 = strip(words[:i]), strip(words[i + 1:])
            m = max(width(a, f), width(b2, f))
            if best is None or m < best[0]:
                best = (m, [a, b2])
        return best

    size = lb["size"]
    f = pil_font(fpath, size)
    lines = [strip(words)]
    if width(lines[0], f) > lb.get("one_line_max", maxw) and max_lines >= 2 and best_split(f):
        lines = best_split(f)[1]          # 2 linhas equilibradas (estilo de referência, 21/11/2026)
    while size > lb.get("min_size", 30) and max(width(ln, f) for ln in lines) > maxw:
        size -= 2
        f = pil_font(fpath, size)
        if len(lines) == 2:
            lines = best_split(f)[1]
    l, tp, r, b = f.getbbox("ÁGJQ")
    th = b - tp
    gap = lb.get("line_gap", 6)
    tw = int(max(width(ln, f) for ln in lines))
    text_h = th * len(lines) + gap * (len(lines) - 1)
    bw_, bh_ = tw + 2 * lb["padding_x"], text_h + 2 * lb["padding_y"]
    line_h = c.get("divider", {}).get("height", 0)
    H = max(bh_, line_h) + 4
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cy = H // 2
    if line_h:
        d.rectangle([0, cy - line_h // 2, W, cy - line_h // 2 + line_h - 1], fill=hex_rgb(c["divider"]["color"]))
    bx, by = (W - bw_) // 2, cy - bh_ // 2
    rad = lb.get("radius", 0)
    if rad:
        d.rounded_rectangle([bx, by, bx + bw_ - 1, by + bh_ - 1], rad, fill=hex_rgb(lb["bg"]))
    else:
        d.rectangle([bx, by, bx + bw_ - 1, by + bh_ - 1], fill=hex_rgb(lb["bg"]))
    y = by + lb["padding_y"] - tp
    for ln in lines:
        x = (W - width(ln, f)) / 2
        for t, col in ln:
            d.text((x, y), t, font=f, fill=hex_rgb(col))
            x += f.getlength(t)
        y += th + gap
    return img, cy, by


def render_card(tpl, clip, tdir, W):
    """cam style: channel tag + box with two coloured lines. Returns (image, box_centre_y, margin).
    Optional template keys (all off when absent): box.bg_gradient, box.bg_image, box.border_gradient,
    box.glow, card.logo, card.text_glow, tag.bg_gradient, tag.border_gradient."""
    from PIL import ImageChops, ImageFilter
    c = tpl["card"]
    up = c.get("uppercase", True)
    box, tag = c["box"], c["tag"]
    bw = box["border_width"]
    logo_spec = c.get("logo")
    logo_size = logo_spec["size"] if logo_spec else 0
    logo_gap = logo_spec.get("gap", 24) if logo_spec else 0
    logo_w = (logo_size + logo_gap) if logo_spec else 0
    inner_max = c["max_width"] - 2 * (bw + box["padding_x"]) - logo_w
    texts = [clean_text(t, up) for t in lines_of(clip)]
    specs = [c["line1"], c["line1"]]          # uma frase só: as duas linhas têm o mesmo estilo
    items = []
    for t, sp in zip(texts, specs):
        if t:
            items.append((t, fit_font(t, sp["font"], sp["size"], sp["min_size"], inner_max, tdir), sp["color"]))
    if not items:
        return None
    # mesmo tamanho nas duas linhas: as duas usam o menor tamanho que coube
    size = min(f.size for _, f, _ in items)
    items = [(t, pil_font(resolve_font(c["line1"]["font"]), size), col) for t, _, col in items]

    metrics = []
    for t, f, col in items:
        l, tp, r, b = f.getbbox(t)
        metrics.append((r - l, b - tp, tp, l))
    text_w = max(m[0] for m in metrics)
    text_h = sum(m[1] for m in metrics) + box["line_gap"] * (len(items) - 1)
    box_w = text_w + 2 * (box["padding_x"] + bw) + logo_w
    box_h = max(text_h + 2 * (box["padding_y"] + bw), (logo_size + 2 * (bw + 12)) if logo_spec else 0)
    # card sempre do mesmo tamanho (pedido em 19/11/2026): box.fixed_w / box.fixed_h; o texto fica centrado
    text_area = text_w
    if box.get("fixed_w"):
        box_w = max(box_w, box["fixed_w"])
        text_area = box_w - 2 * (box["padding_x"] + bw) - logo_w
    if box.get("fixed_h"):
        box_h = max(box_h, box["fixed_h"])

    ch = clean_text(tpl.get("channel_name", ""), tag.get("uppercase", True))
    tag_img = None
    if ch:
        tf = pil_font(resolve_font(tag["font"]), tag["size"])
        l, tp, r, b = tf.getbbox(ch)
        tb0 = tag.get("border_width", 0)
        tw, th = r - l + 2 * (tag["padding_x"] + tb0), b - tp + 2 * (tag["padding_y"] + tb0)
        tag_img = (tf, ch, tw, th, l, tp)

    glow = box.get("glow")
    m = int(glow["radius"] * 2) if glow else 0      # transparent margin so the glow is not clipped
    card_w = max(box_w, tag_img[2] if tag_img else 0)
    tag_h = tag_img[3] if tag_img else 0
    overlap = tag.get("overlap", 0) if tag_img else 0
    below = tag.get("position", "top") == "bottom"
    extra = max(tag_h - overlap, 0)
    top = (0 if below else extra) + m
    img = Image.new("RGBA", (card_w + 2 * m, extra + box_h + 2 * m), (0, 0, 0, 0))
    bx = m + (card_w - box_w) // 2
    rad = box.get("radius", 0)

    # --- box: background (solid / gradient / darkened image), border (solid / gradient), glow
    bg = fill_img(box_w, box_h, box.get("bg"), box.get("bg_gradient"), horizontal=box.get("bg_horizontal", False))
    if box.get("bg_image"):
        bi = box["bg_image"]
        pic = Image.open(skill_path(bi["file"])).convert("RGB")
        s = max(box_w / pic.width, box_h / pic.height)
        pic = pic.resize((int(pic.width * s) + 1, int(pic.height * s) + 1), Image.LANCZOS)
        pic = pic.crop(((pic.width - box_w) // 2, (pic.height - box_h) // 2,
                        (pic.width - box_w) // 2 + box_w, (pic.height - box_h) // 2 + box_h))
        if bi.get("blur"):
            pic = pic.filter(ImageFilter.GaussianBlur(bi["blur"]))
        bg = Image.blend(bg.convert("RGB"), pic, bi.get("opacity", 0.2)).convert("RGBA")
    inner = rr_mask(box_w, box_h, rad, bw)
    bg.putalpha(inner)
    border = fill_img(box_w, box_h, box.get("border_color"), box.get("border_gradient"), horizontal=True)
    border.putalpha(ImageChops.subtract(rr_mask(box_w, box_h, rad, 0), inner))
    if glow:
        g = border.filter(ImageFilter.GaussianBlur(glow["radius"]))
        g.putalpha(g.getchannel("A").point(lambda v: int(min(255, v * glow.get("opacity", 1.0) * 1.1))))
        img.alpha_composite(g, (bx, top))
    img.alpha_composite(bg, (bx, top))
    img.alpha_composite(border, (bx, top))

    # --- logo (left, vertically centred in the box)
    if logo_spec:
        lg = load_logo(logo_spec, logo_size)
        img.alpha_composite(lg, (bx + bw + box["padding_x"] // 2 + 6, top + (box_h - logo_size) // 2))

    # --- text (optional neon glow behind it)
    tl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(tl)
    cx = bx + bw + box["padding_x"] + logo_w + text_area / 2
    y = top + (box_h - text_h) // 2
    for (t, f, col), (mw, mh, mtp, ml) in zip(items, metrics):
        d.text((int(cx - mw / 2) - ml, y - mtp), t, font=f, fill=hex_rgb(col))
        y += mh + box["line_gap"]
    tg = c.get("text_glow")
    if tg:
        gl = tl.filter(ImageFilter.GaussianBlur(tg["radius"]))
        gl.putalpha(gl.getchannel("A").point(lambda v: int(min(255, v * tg.get("opacity", 0.8) * 1.5))))
        img.alpha_composite(gl)
    img.alpha_composite(tl)

    # --- channel tag
    if tag_img:
        tf, ch, tw, th, l, tp = tag_img
        align = tag.get("align", "center")
        tx = {"left": bx, "right": bx + box_w - tw}.get(align, m + (card_w - tw) // 2) + tag.get("offset_x", 0)
        ty = (top + box_h - overlap) if below else (top - (tag_h - overlap) if tag_h > overlap else m)
        tb = tag.get("border_width", 0)
        if tb:
            img.alpha_composite(fill_img(tw, th, tag.get("border_color"), tag.get("border_gradient")), (tx, ty))
        img.alpha_composite(fill_img(tw - 2 * tb, th - 2 * tb, tag.get("bg"), tag.get("bg_gradient")), (tx + tb, ty + tb))
        ImageDraw.Draw(img).text((tx + tb + tag["padding_x"] - l, ty + tb + tag["padding_y"] - tp), ch,
                                 font=tf, fill=hex_rgb(tag["color"]))
    if c.get("anchor_on", "box") == "card":     # centre the WHOLE card (box + tag) on anchor_y
        return img, m + (extra + box_h) // 2, m
    return img, top + box_h // 2, m


def render_stack(tpl, clip, tdir, W):
    """nocam 'stack' layout: round logo (with ring) centred, hook text under it with a gradient fill
    (GTA sunset), black outline and glow. No box. Returns the overlay image."""
    from PIL import ImageChops, ImageFilter
    st = tpl["stack"]
    lg_spec, t = st["logo"], st["text"]
    up = t.get("uppercase", True)
    texts = [clean_text(x, up) for x in lines_of(clip)]
    specs = [t["line1"], t["line1"]]          # uma frase só: as duas linhas têm o mesmo estilo
    outline = t["outline"]
    items = [(x, fit_font(x, sp["font"], sp["size"], sp["min_size"], t["max_width"], tdir, outline))
             for x, sp in zip(texts, specs) if x]
    ring = lg_spec.get("ring_width", 0)
    size = lg_spec["size"]
    boxes = [f.getbbox(x, stroke_width=outline) for x, f in items]
    th = sum(b[3] - b[1] for b in boxes) + t["line_gap"] * max(len(items) - 1, 0)
    glow_m = 30
    H = size + 2 * ring + (st["gap"] + th if items else 0) + 2 * glow_m
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # logo + ring
    full = size + 2 * ring
    cx0 = (W - full) // 2
    if ring:
        rg = grad_img(full, full, lg_spec.get("ring_gradient", ["#FF4FD8", "#FF9A3C"]), False).convert("RGBA")
        mk = Image.new("L", (full * 4, full * 4), 0)
        ImageDraw.Draw(mk).ellipse([0, 0, full * 4 - 1, full * 4 - 1], fill=255)
        rg.putalpha(mk.resize((full, full), Image.LANCZOS))
        gl = rg.filter(ImageFilter.GaussianBlur(10))
        img.alpha_composite(gl, (cx0, glow_m)); img.alpha_composite(rg, (cx0, glow_m))
    lg = load_logo(lg_spec, size)
    img.alpha_composite(lg, (cx0 + ring, glow_m + ring))
    # text
    y = glow_m + full + st["gap"]
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    ol = Image.new("L", (W, H), 0)
    od = ImageDraw.Draw(ol)
    for (x, f), b in zip(items, boxes):
        lw = b[2] - b[0]
        px = (W - lw) // 2 - b[0]
        md.text((px, y - b[1]), x, font=f, fill=255)
        od.text((px, y - b[1]), x, font=f, fill=255, stroke_width=outline)
        y += b[3] - b[1] + t["line_gap"]
    if items:
        top = glow_m + full + st["gap"]
        grad = grad_img(W, th + 4, t["gradient"], False).convert("RGBA")
        gimg = Image.new("RGBA", (W, H), (0, 0, 0, 0)); gimg.paste(grad, (0, top - 2))
        glow = Image.new("RGBA", (W, H), hex_rgb(t.get("glow_color", "#FF3DCB")) + (255,))
        ga = ol.filter(ImageFilter.GaussianBlur(t.get("glow_radius", 14)))
        glow.putalpha(ga.point(lambda v: int(v * t.get("glow_opacity", 0.8))))
        img.alpha_composite(glow)
        black = Image.new("RGBA", (W, H), hex_rgb(t["outline_color"]) + (255,)); black.putalpha(ol)
        img.alpha_composite(black)
        gimg.putalpha(ImageChops.multiply(gimg.getchannel("A"), mask))
        img.alpha_composite(gimg)
    return img, glow_m


def key_black(im):
    """Logo on a black square -> black becomes transparent (alpha from brightness), cropped to the art."""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(float)
    mx = a.max(axis=2)
    alpha = np.clip((mx - 12) * 4, 0, 255)
    rgb = np.clip(a * 255 / np.maximum(alpha[..., None], 1), 0, 255)   # un-premultiply so edges keep colour
    out = Image.fromarray(np.dstack([rgb, alpha]).astype("uint8"), "RGBA")
    box = out.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    return out.crop(box) if box else out


def shear(img, k):
    """Fake italic: lean the image right by k (pixels per pixel of height)."""
    if not k:
        return img
    extra = int(img.height * k) + 2
    return img.transform((img.width + extra, img.height), Image.AFFINE,
                         (1, k, -k * img.height, 0, 1, 0), Image.BICUBIC)


def rich_line(parts, font):
    """[(text, '#rrggbb'), ...] on one line -> tight RGBA image."""
    asc, desc = font.getmetrics()
    w = int(sum(font.getlength(t) for t, _ in parts)) + 4
    img = Image.new("RGBA", (w, asc + desc + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 2
    for t, col in parts:
        d.text((x, 2), t, font=font, fill=hex_rgb(col) + (255,))
        x += font.getlength(t)
    return img


def hook_parts(text, base, hi):
    """Words starting with @ or wrapped in *asterisks* get the highlight colour."""
    out = []
    for i, w in enumerate(text.split()):
        col = hi if (w.startswith("@") or (w.startswith("*") and w.endswith("*") and len(w) > 2)) else base
        out.append(((" " if i else "") + w.strip("*"), col))
    return out


def render_faixa(tpl, clip):
    """faixa style: the whole static frame (background + header + hook) as one 1080x1920 image.
    The gameplay goes on top of it in ffmpeg (layout.game)."""
    from PIL import ImageFilter
    W, H = tpl["canvas"]["w"], tpl["canvas"]["h"]
    bgs = tpl["layout"]["background"]
    img = Image.open(skill_path(bgs["file"])).convert("RGBA")
    if img.size != (W, H):
        img = img.resize((W, H), Image.LANCZOS)

    # --- header: line  logo  / RSK CORTES  line
    hd = tpl["header"]
    lg_spec = hd["logo"]
    logo = Image.open(skill_path(lg_spec["file"])).convert("RGBA")
    if lg_spec.get("key_black"):
        logo = key_black(logo)
    s = lg_spec["size"] / max(logo.size)
    logo = logo.resize((int(logo.width * s), int(logo.height * s)), Image.LANCZOS)
    name = shear(rich_line([tuple(p) for p in hd["parts"]], pil_font(resolve_font(hd["font"]), hd["size"])),
                 hd.get("italic", 0))
    nb = name.getbbox() or (0, 0, name.width, name.height)
    name = name.crop(nb)
    ln = hd.get("lines") or {}
    L, G = ln.get("length", 0), ln.get("gap", 0)
    total = 2 * (L + G) + logo.width + hd["gap"] + name.width
    x = (W - total) // 2
    cy = hd["y_center"]
    d = ImageDraw.Draw(img)
    if L:
        d.rectangle([x, cy - ln["width"] // 2, x + L, cy + ln["width"] // 2], fill=hex_rgb(ln["color"]))
    x += L + G
    img.alpha_composite(logo, (x, cy - logo.height // 2))
    x += logo.width + hd["gap"]
    img.alpha_composite(name, (x, cy - name.height // 2))
    x += name.width + G
    if L:
        d.rectangle([x, cy - ln["width"] // 2, x + L, cy + ln["width"] // 2], fill=hex_rgb(ln["color"]))

    # --- hook: white italic, @canal in pink, up to 2 balanced lines
    hk = tpl["hook"]
    up = hk.get("uppercase", True)
    texts = [clean_text(t, up) for t in lines_of(clip) if t]
    rows = []
    if texts:
        size = hk["size"]
        path = resolve_font(hk["font"])
        while True:   # one size for both lines: shrink until the widest fits
            f = pil_font(path, size)
            rows = [shear(rich_line(hook_parts(t, hk["color"], hk["highlight_color"]), f), hk.get("italic", 0))
                    for t in texts]
            if max(r.width for r in rows) <= hk["max_width"] or size <= hk["min_size"]:
                break
            size -= 2
        rows = [r.crop(r.getbbox() or (0, 0, r.width, r.height)) for r in rows]
        th = sum(r.height for r in rows) + hk["line_gap"] * (len(rows) - 1)
        y = hk["y_center"] - th // 2
        sh = hk.get("shadow")
        for r in rows:
            px = (W - r.width) // 2
            if sh:
                layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                sc = Image.new("RGBA", r.size, hex_rgb(sh["color"]) + (255,))
                sc.putalpha(r.getchannel("A").point(lambda v: int(v * sh.get("opacity", 0.8))))
                layer.alpha_composite(sc, (px + sh["offset"], y + sh["offset"]))
                img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(sh.get("blur", 0))))
            img.alpha_composite(r, (px, y))
            y += r.height + hk["line_gap"]
    return img.convert("RGB")


def filter_faixa(tpl):
    W = tpl["canvas"]["w"]
    g = tpl["layout"]["game"]
    gh, fx = g["height"], g.get("focus_x", 0.5)
    flags = tpl["layout"].get("scale_flags", "bicubic")
    f = (f"[0:v]scale={W}:{gh}:force_original_aspect_ratio=increase:flags={flags},"
         f"crop={W}:{gh}:(iw-{W})*{fx}:(ih-{gh})/2[game];"
         f"[1:v][game]overlay=0:{g['y']}[base]")
    return f, "base"


# ---------------------------------------------------------------- captions (ASS)

def group_words(words, max_words, max_chars, max_gap):
    groups, cur = [], []
    for w in words:
        n_chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
        if cur and (len(cur) >= max_words or n_chars > max_chars or w["s"] - cur[-1]["e"] > max_gap
                    or re.search(r"[.!?,]$", cur[-1]["w"])):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def split_phrase(text, s, e, max_words, max_chars):
    """Translated phrase -> caption groups of words with times. The group keeps the original phrase time;
    long phrases are split in chunks (template max_words/max_chars) and every word gets a share of the time
    proportional to its length (word-by-word highlight)."""
    toks = text.split()
    if not toks or e <= s:
        return []
    chunks, cur = [], []
    for t in toks:
        n_chars = sum(len(x) + 1 for x in cur) + len(t)
        if cur and (len(cur) >= max_words or n_chars > max_chars):
            chunks.append(cur); cur = []
        cur.append(t)
    if cur:
        chunks.append(cur)
    total = sum(len(t) + 1 for t in toks)
    groups, t0 = [], s
    for ch in chunks:
        g = []
        for t in ch:
            d = (e - s) * (len(t) + 1) / total
            g.append({"w": t, "s": round(t0, 3), "e": round(t0 + d, 3)})
            t0 += d
        groups.append(g)
    return groups


def caption_groups(words, cap, translated=None):
    """Original words (grouped by the template rules) or translated phrases (captions_pt)."""
    if translated is not None:
        out = []
        for ph in translated:
            out += split_phrase(ph.get("text", ""), ph["s"], ph["e"], cap["max_words"], cap["max_chars"])
        return out
    return group_words(words, cap["max_words"], cap["max_chars"], cap["max_gap"])


def build_ass(path, groups, clip_len, cap, family, canvas, pos_xy, an):
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {canvas['w']}", f"PlayResY: {canvas['h']}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{family},{cap['size']},{ass_color(cap['color'])},{ass_color(cap['color'])},"
        f"{ass_color(cap['outline_color'])},&H80000000,{-1 if cap.get('bold') else 0},0,0,0,100,100,1,0,1,"
        f"{cap['outline']},{cap['shadow']},5,40,40,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    BS = chr(92)  # ASS override tags use a backslash; built explicitly to avoid string-escape traps
    pos = "{" + BS + "an" + str(an) + BS + "pos(" + str(pos_xy[0]) + "," + str(pos_xy[1]) + ")}"
    hi, base, sc = ass_color(cap["highlight_color"]), ass_color(cap["color"]), cap.get("highlight_scale", 112)
    up = cap.get("uppercase", True)
    events = []
    for g in groups:
        g_end = g[-1]["e"]
        for i, w in enumerate(g):
            s = w["s"]
            e = g[i + 1]["s"] if i + 1 < len(g) else g_end + 0.15
            parts = []
            for j, x in enumerate(g):
                txt = clean_text(clean_ass(x["w"]), up)
                if j == i:
                    parts.append("{" + BS + "c" + hi + BS + "fscx" + str(sc) + BS + "fscy" + str(sc) + "}" + txt
                                 + "{" + BS + "c" + base + BS + "fscx100" + BS + "fscy100}")
                else:
                    parts.append(txt)
            events.append([s, e, " ".join(parts)])
    events.sort(key=lambda ev: ev[0])
    for k in range(len(events) - 1):  # never show two captions at once: each ends when the next starts
        events[k][1] = min(events[k][1], events[k + 1][0])
    for s, e, txt in events:
        if e - s >= 0.02:
            lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(min(e, clip_len))},Cap,,0,0,0,,{pos}{txt}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- filter graphs

def cam_box_px(cam, src_w, src_h, target_aspect):
    """Fractions x,y,w,h -> pixel crop. The box is only ever SHRUNK (around its centre) to the
    target aspect, so the crop never leaves the webcam (no border/background strips)."""
    x, y, w, h = cam
    cx, cy = (x + w / 2) * src_w, (y + h / 2) * src_h
    bw, bh = w * src_w, h * src_h
    if bw / bh > target_aspect:
        bw = bh * target_aspect
    else:
        bh = bw / target_aspect
    bw, bh = int(bw) // 2 * 2, int(bh) // 2 * 2
    px = int(min(max(cx - bw / 2, 0), src_w - bw))
    py = int(min(max(cy - bh / 2, 0), src_h - bh))
    return bw, bh, px, py


def filter_cam(tpl, cam, src_w, src_h, card_xy, with_card, zooms=None):
    W = tpl["canvas"]["w"]
    L = tpl["layout"]
    ch, gh, fx = L["cam_height"], L["game_height"], L["game_focus_x"]
    flags = L.get("scale_flags", "bicubic")                  # e.g. "lanczos" for a sharper upscale of the webcam
    sharp = f",{L['cam_sharpen']}" if L.get("cam_sharpen") else ""   # e.g. "unsharp=5:5:0.7:3:3:0.0"
    fr = L.get("cam_frame")
    if fr:
        # Moldura: a webcam inteira (sem cortar) menor, no centro da área de cima, com ela mesma
        # desfocada atrás. Amplia menos que encher 1080 de largura, então o rosto fica mais nítido.
        x, y, w, h = cam
        bw, bh = int(w * src_w) // 2 * 2, int(h * src_h) // 2 * 2
        px = int(min(max(x * src_w, 0), src_w - bw))
        py = int(min(max(y * src_h, 0), src_h - bh))
        fh = int(fr.get("height", 540))
        maxw = W - 2 * int(fr.get("margin_x", 40))
        iw = bw * fh / bh
        if iw > maxw:
            iw, fh = maxw, maxw * bh / bw
        iw, fh = int(iw) // 2 * 2, int(fh) // 2 * 2
        blur = fr.get("blur", 20)
        dark = fr.get("darken", -0.15)
        f = (f"[0:v]split[c][g];"
             f"[c]crop={bw}:{bh}:{px}:{py},split[cb][cf];"
             f"[cb]scale={W}:{ch}:force_original_aspect_ratio=increase,crop={W}:{ch},"
             f"boxblur={blur},eq=brightness={dark}[cbg];"
             f"[cf]scale={iw}:{fh}:flags={flags}{sharp}[cfg];"
             f"[cbg][cfg]overlay=({W}-{iw})/2:({ch}-{fh})/2[cam];")
    else:
        bw, bh, px, py = cam_box_px(cam, src_w, src_h, W / ch)
        f = (f"[0:v]split[c][g];"
             f"[c]crop={bw}:{bh}:{px}:{py},scale={W}:{ch}:force_original_aspect_ratio=increase:flags={flags},"
             f"crop={W}:{ch}{sharp}[cam];")
    f += (
         f"[g]scale={W}:{gh}:force_original_aspect_ratio=increase:flags={flags},"
         f"crop={W}:{gh}:(iw-{W})*{fx}:0[game];"
         f"[cam][game]vstack[base]")
    last = "base"
    if with_card:
        f += f";[{last}][1:v]overlay={card_xy[0]}:{card_xy[1]}[withcard]"
        last = "withcard"
    if zooms:
        # Zoom no rosto (estilo @oluittv, 21/11/2026): nos trechos de reação a webcam ocupa a tela inteira
        # (recorte 9:16 do centro da caixa da webcam), sem card; a legenda continua por cima.
        H = tpl["canvas"]["h"]
        x, y, w, h = cam
        zh = int(h * src_h) // 2 * 2
        zw = int(zh * W / H) // 2 * 2
        zx = int(min(max((x + w / 2) * src_w - zw / 2, 0), src_w - zw))
        zy = int(min(max(y * src_h, 0), src_h - zh))
        f = f.replace("[0:v]split[c][g];", "[0:v]split=3[c][g][z];", 1)
        en = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in zooms)
        f += (f";[z]crop={zw}:{zh}:{zx}:{zy},scale={W}:{H}:flags={flags}{sharp}[zm]"
              f";[{last}][zm]overlay=0:0:enable='{en}'[zoomed]")
        last = "zoomed"
    return f, last


def filter_nocam(tpl, title_xy, with_title):
    W, H = tpl["canvas"]["w"], tpl["canvas"]["h"]
    bg, g = tpl["layout"]["background"], tpl["layout"]["game"]
    gw = int(round(W * g["zoom"] / 2)) * 2
    f = (f"[0:v]split[a][b];"
         f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
         f"boxblur={bg['blur_radius']}:{bg['blur_passes']},eq=brightness={bg['brightness']}[bg];"
         f"[b]scale={gw}:-2,crop={W}:ih:(iw-{W})*{g['focus_x']}:0[fg];"
         f"[bg][fg]overlay=0:{g['y_center']}-h/2[base]")
    last = "base"
    if with_title:
        f += f";[{last}][1:v]overlay={title_xy[0]}:{title_xy[1]}[withtitle]"
        last = "withtitle"
    return f, last


# ---------------------------------------------------------------- render

def clip_window(clip, cfg, src_dur):
    """(render_start, render_end, cut_start, cut_end) in source-file seconds: the short is the cut
    plus pad_before / pad_after (0 = exact cut), or pad_folga on each side when the clip has "folga": true,
    clamped to the video."""
    s, e = secs(clip["start"]), secs(clip["end"])
    if clip.get("folga"):
        pb = pa = float(cfg.get("pad_folga", 10))
    else:
        pb, pa = float(cfg.get("pad_before", 0)), float(cfg.get("pad_after", 0))
    rs = max(0.0, s - pb)
    re_ = e + pa
    if src_dur:
        re_ = min(re_, src_dur)
    return rs, re_, s, e


def hd_source(workdir, clip, s, e):
    """Trecho em alta do corte (fetch_hd.py) que cobre [s, e] (tempo do bloco): (arquivo, shift) ou None.
    Tempo no arquivo hd = tempo do bloco - shift."""
    reg = read_json(os.path.join(workdir, "hd", "hd.json"), {}) or {}
    r = reg.get(str(int(clip["id"])))
    if r and os.path.exists(r["file"]) and r["covers"][0] <= s + 0.01 and r["covers"][1] >= e - 0.05:
        return r["file"], float(r["shift"])
    return None


def render(workdir, clip, words, args, setup, src_w, src_h, tdir, out_dir, cfg, src_dur, lang):
    style = args.style or clip.get("style")
    if style not in STYLES:
        print(f"  pulando #{clip['id']}: style tem que ser um de {STYLES} (veio {style!r})")
        return None
    tpl = load_template(tdir, style)
    W, H = tpl["canvas"]["w"], tpl["canvas"]["h"]
    if style == "cam":
        # per-video (setup.json) or per-clip overrides:
        #   "split": "half"  -> streamer and gameplay the same size (webcam overlay also shows in the gameplay)
        #   "game_focus_x"   -> where the gameplay crop sits (0 = left, 1 = right), to dodge a webcam overlay
        lay, card = dict(tpl["layout"]), dict(tpl["card"])
        if clip.get("split", setup.get("split")) == "half":
            lay["cam_height"] = lay["game_height"] = H // 2
            card["anchor_y"] = H // 2
        fx = clip.get("game_focus_x", setup.get("game_focus_x"))
        if fx is not None:
            lay["game_focus_x"] = float(fx)
        tpl = {**tpl, "layout": lay, "card": card}

    s, e, cut_s, cut_e = clip_window(clip, cfg, src_dur)
    if cut_e <= cut_s or e <= s:
        print(f"  pulando #{clip['id']}: fim antes do início"); return None
    length = e - s
    # --- fonte: trecho em alta do corte (fluxo rápido) ou o arquivo do bloco
    src_path, ss = os.path.abspath(args.source), s
    hd = hd_source(workdir, clip, s, e)
    if hd:
        src_path, ss = hd[0], s - hd[1]
        from common import probe_av
        pi = probe_av(src_path)
        src_w, src_h = int(pi["width"]), int(pi["height"])
    elif (read_json(os.path.join(workdir, "info.json"), {}) or {}).get("analysis"):
        sys.exit(f"Corte #{clip['id']}: o bloco foi baixado leve (modo análise) e o corte ainda não tem o trecho "
                 f"em alta. Rode: python scripts/fetch_hd.py {workdir} --only {clip['id']}")
    name = f"short_{int(clip['id']):02d}"
    tmp = tempfile.mkdtemp(prefix=name + "_", dir=out_dir)
    try:
        # --- title overlay (PNG) for the whole clip
        overlay_png, overlay_xy, img, card_margin = None, (0, 0), None, 0
        if style == "faixa":
            img = render_faixa(tpl, clip)
        elif style == "nocam" and "stack" in tpl:
            img, gm = render_stack(tpl, clip, tdir, W)
            overlay_xy = (0, tpl["stack"]["y_top"] - gm)
        elif style == "cam" and "label" in tpl.get("card", {}):   # etiqueta branca na divisa (21/11/2026)
            r = render_label(tpl, clip, W)
            if r:
                img, box_cy, card_margin = r
                overlay_xy = (0, tpl["card"]["anchor_y"] - box_cy)
        elif style == "cam" or "card" in tpl:   # nocam can also use the card (logo + channel tag) instead of the white title
            r = render_card(tpl, clip, tdir, W)
            if r:
                img, box_cy, card_margin = r
                overlay_xy = ((W - img.width) // 2, tpl["card"]["anchor_y"] - box_cy)
        else:
            sys.exit(f"Template {style} sem 'stack' nem 'card': nada para desenhar o gancho.")
        if clip.get("card") is False:      # pedido 20/11/2026: 1 a cada 3 shorts sai sem card nenhum
            img = None
        if img:
            overlay_png = os.path.join(tmp, "overlay.png")
            img.save(overlay_png)

        # --- word-by-word captions, only if the picture has no burned-in subtitles
        want_caps = not args.no_captions and not setup.get("burned_subs") and clip.get("captions", True)
        groups = []
        if want_caps:
            cap = tpl["captions"]
            if clip.get("captions_pt") is not None:      # translated (foreign video), times in file seconds
                tr = [{"s": max(0.0, secs(p["s"]) - s), "e": min(length, secs(p["e"]) - s), "text": p.get("text", "")}
                      for p in clip["captions_pt"] if secs(p["e"]) > s and secs(p["s"]) < e]
                groups = caption_groups(None, cap, tr)
            elif lang and lang != "pt":
                sys.exit(f"Corte #{clip['id']}: o vídeo está em '{lang}' e a legenda tem que sair em português. "
                         f"Rode --export-captions {clip['id']}, traduza e grave em captions_pt no clips.json.")
            else:
                cw = [{"w": w["w"], "s": round(w["s"] - s, 3), "e": round(w["e"] - s, 3)}
                      for w in words if w["s"] >= s - 0.01 and w["e"] <= e + 0.3
                      and not any(secs(a) - 0.05 <= w["s"] < secs(b) for a, b in clip.get("caption_mute", []))]
                # caption_mute: trechos (tempo do arquivo) que são fala do JOGO (NPC, cutscene, rádio): sem legenda
                for x in clip.get("captions_add", []):   # grito/risada que a transcrição não pega (tempo do arquivo)
                    xs, xe = secs(x["s"]), secs(x["e"])
                    if xe > s and xs < e:
                        cw.append({"w": x["w"], "s": round(max(0.0, xs - s), 3), "e": round(min(length, xe - s), 3)})
                cw.sort(key=lambda w: w["s"])
                groups = caption_groups(cw, cap)
        has_caps = bool(groups)
        fontsdir = ""
        ass_path = os.path.join(tmp, "cap.ass")
        if has_caps:
            cap = tpl["captions"]
            font_path = resolve_font(cap["font"])
            fontsdir = os.path.dirname(font_path)
            family = " ".join(pil_font(font_path, 20).getname()).replace(" Regular", "")
            if style == "cam" and not overlay_png:   # sem card (pedido 20/11/2026): legenda centrada na divisa streamer/gameplay
                pos_xy, an = (cap["x"], tpl["card"]["anchor_y"]), 5
            elif cap.get("anchor") == "above_card" and (overlay_png or card_margin):   # bottom of text = gap px above the card tag (sem card: mesmo lugar)
                pos_xy, an = (cap["x"], overlay_xy[1] + card_margin - cap.get("gap", 5)), 2
            else:
                pos_xy, an = (cap["x"], cap["y"]), cap.get("an", 5)
            build_ass(ass_path, groups, length, cap, family, tpl["canvas"], pos_xy, an)

        # --- ffmpeg graph
        if style == "cam":
            cam = clip.get("cam") or setup.get("cam")
            if not cam:
                sys.exit("O estilo cam precisa da caixa da webcam: rode --snapshot, estime e passe --cam x,y,w,h")
            zooms = [(max(0.0, secs(a) - s), min(length, secs(b) - s)) for a, b in clip.get("zoom", [])]
            zooms = [(a, b) for a, b in zooms if b > a]
            graph, last = filter_cam(tpl, cam, src_w, src_h, overlay_xy, bool(overlay_png), zooms)
        elif style == "faixa":
            graph, last = filter_faixa(tpl)
        else:
            graph, last = filter_nocam(tpl, overlay_xy, bool(overlay_png))
        if has_caps:
            fd = fontsdir.replace("\\", "/").replace(":", "\\:")
            graph += f";[{last}]ass=cap.ass:fontsdir='{fd}'[cap]"
            last = "cap"
        graph += f";[{last}]format=yuv420p[v]"
        if overlay_png:   # a imagem fixa é decodificada uma vez e repetida (antes: -loop 1 decodificava a cada quadro)
            graph = "[1:v]loop=loop=-1:size=1:start=0[ovl];" + graph.replace("[1:v]", "[ovl]")

        ENC = load_config().get("encode", {})
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{ss:.3f}", "-i", src_path]
        if overlay_png:
            cmd += ["-framerate", str(FPS), "-i", "overlay.png"]
        out_name = f"{name}.mp4"
        cmd += ["-t", f"{length:.3f}", "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", str(ENC.get("preset", "veryfast")),
                "-crf", str(ENC.get("crf", 20)), "-r", str(FPS),
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", os.path.abspath(os.path.join(out_dir, out_name))]
        subprocess.run(cmd, check=True, cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    out = os.path.join(out_dir, out_name)
    verify(out)
    return {"file": os.path.abspath(out), "style": style, "render": [s, e], "cut": [cut_s, cut_e], "height": src_h}


def verify(path):
    from common import probe_av
    pi = probe_av(path)
    v = {"codec_name": pi["vcodec"], "pix_fmt": pi["pix_fmt"]}
    a = {"codec_name": pi["acodec"]} if pi["acodec"] else {}
    if v.get("codec_name") != "h264" or v.get("pix_fmt") != "yuv420p" or (a and a.get("codec_name") != "aac"):
        sys.exit(f"Conferência da saída falhou em {path}: vídeo={v} áudio={a} (precisa h264/yuv420p/aac)")


# ---------------------------------------------------------------- snapshot / preview

def snapshot(workdir, source, cam):
    d = duration(source)
    fracs = (0.08, 0.22, 0.38, 0.54, 0.70, 0.86)
    vf = "scale=1280:-2"
    if cam:
        x, y, w, h = cam
        vf += f",drawbox=x=iw*{x}:y=ih*{y}:w=iw*{w}:h=ih*{h}:color=red@0.9:t=4"
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y"]       # um processo só para os 6 quadros
    for fr in fracs:
        cmd += ["-ss", f"{d * fr:.1f}", "-i", source]
    for i in range(len(fracs)):
        cmd += ["-map", f"{i}:v:0", "-frames:v", "1", "-vf", vf, os.path.join(workdir, f"snapshot_{i + 1}.jpg")]
    subprocess.run(cmd, check=True)
    sheet = os.path.join(workdir, "snapshot.jpg")
    from PIL import Image as _I
    ims = [_I.open(os.path.join(workdir, f"snapshot_{i + 1}.jpg")).convert("RGB") for i in range(len(fracs))]
    tw = 640
    ims = [im.resize((tw, int(im.height * tw / im.width))) for im in ims]
    th = max(im.height for im in ims)
    canvas = _I.new("RGB", (3 * tw + 8, 2 * th + 4), "black")
    for k, im in enumerate(ims):
        canvas.paste(im, ((k % 3) * (tw + 4), (k // 3) * (th + 4)))
    canvas.save(sheet, quality=90)
    print(f"✓ {sheet}  (+ snapshot_1..6.jpg em tamanho cheio{', caixa da webcam em vermelho' if cam else ''})")
    print("  Procure: (1) webcam sobre o jogo, (2) legenda gravada na imagem.")


def preview(workdir, out_dir):
    shorts = sorted(glob.glob(os.path.join(out_dir, "short_*.mp4")))
    if not shorts:
        sys.exit("Nenhum short renderizado ainda.")
    from concurrent.futures import ThreadPoolExecutor
    tmp = tempfile.mkdtemp()
    jobs = []
    for p in shorts:
        d = duration(p)
        for frac in (0.08, 0.45, 0.85):
            jobs.append((p, d * frac, os.path.join(tmp, f"{len(jobs):04d}.jpg")))
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
        list(ex.map(lambda j: subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{j[1]:.2f}", "-i", j[0],
                                              "-frames:v", "1", "-vf", "scale=360:640", j[2]], check=True), jobs))
    k = len(jobs)
    cols = 3 * 2 if k > 3 else 3
    rows = math.ceil(k / cols)
    out = os.path.join(out_dir, "preview.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(tmp, "%04d.jpg"),
                    "-vf", f"tile={min(cols, k)}x{rows}:padding=6:color=black", "-frames:v", "1", out], check=True)
    shutil.rmtree(tmp)
    print(f"✓ Preview → {out}  (3 quadros por short)")


# ---------------------------------------------------------------- captions export / renders / posting kit

def video_language(wd):
    lj = read_json(os.path.join(wd, "lang.json")) or {}
    if lj.get("language"):
        return lj["language"]
    return (read_json(os.path.join(wd, "transcript.json")) or {}).get("language")


def export_captions(wd, clip, words, cfg, src_dur, tdir):
    """Original caption phrases (whole short, with the pads) for Claude to translate into captions_pt."""
    tpl = load_template(tdir, clip.get("style") or "cam")
    s, e, _, _ = clip_window(clip, cfg, src_dur)
    cw = [w for w in words if w["s"] >= s - 0.01 and w["e"] <= e + 0.3]
    cap = tpl["captions"]
    phrases, cur = [], []
    for w in cw:   # phrase = words until a pause or sentence end (bigger than one caption: better translation)
        if cur and (w["s"] - cur[-1]["e"] > cap["max_gap"] or re.search(r"[.!?]$", cur[-1]["w"])
                    or len(cur) >= 12):
            phrases.append(cur); cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    out = [{"s": round(g[0]["s"], 2), "e": round(g[-1]["e"], 2), "text": " ".join(x["w"] for x in g)} for g in phrases]
    path = os.path.join(wd, f"captions_{int(clip['id'])}.json")
    write_json(path, out)
    print(f"✓ {len(out)} frases de {hms(s)} a {hms(e)} → {path}")
    print("  Traduza cada frase para português do Brasil (mesmo s/e), revise pensando na cena e grave a lista")
    print(f"  como \"captions_pt\" do corte #{clip['id']} no clips.json.")
    for p in out:
        print(f"  [{p['s']:.2f}-{p['e']:.2f}] {p['text']}")


def hook_text(r):
    """gancho em texto único (linha 1 + linha 2 do card, sem barra)"""
    return r.get("hook_text") or " ".join(x for x in (r.get("hook", ""), r.get("subhook", "")) if x).strip()


def update_renders(wd, out_dir, clip, res, lang):
    """shorts/renders.json: one entry per clip id with everything the posting kit and Notion need."""
    path = os.path.join(out_dir, "renders.json")
    data = read_json(path, {}) or {}
    off = section_offset(wd)
    info = read_json(os.path.join(wd, "info.json"), {}) or {}
    rs, re_ = res["render"]
    cs, ce = res["cut"]
    old = data.get(str(clip["id"]), {})
    data[str(clip["id"])] = {
        "id": clip["id"], "file": res["file"], "style": res["style"],
        "hook": clip.get("hook", ""), "subhook": clip.get("subhook", ""),
        "hook_text": " ".join(x for x in (clip.get("hook", ""), clip.get("subhook", "")) if x).strip(),
        "suggested_cut_in_file": f"{mmss(cs - rs)} a {mmss(ce - rs)}",
        "original_time": f"{hms(cs + off)} a {hms(ce + off)}",
        "file_range_in_source": [round(rs, 2), round(re_, 2)],
        "language": lang or "pt", "origin_language": "PT" if (lang or "pt") == "pt" else "Gringo",
        "title": clip.get("title", ""), "description": clip.get("description", ""),
        "hashtags": clip["hashtags"] if isinstance(clip.get("hashtags"), str) else " ".join(clip.get("hashtags") or []),
        "moment_type": clip.get("type"), "video_url": info.get("webpage_url"),
        "channel": info.get("channel") or info.get("uploader"), "platform": info.get("extractor_key"),
        "notion_page_id": clip.get("notion_page_id") or old.get("notion_page_id"),
    }
    write_json(path, data)
    return data[str(clip["id"])]


def write_posting_kit(wd, out_dir, clips, cfg):
    renders = read_json(os.path.join(out_dir, "renders.json"), {}) or {}
    info = read_json(os.path.join(wd, "info.json"), {}) or {}
    rows = [c for c in clips if str(c["id"]) in renders]
    if not rows:
        return None
    rows.sort(key=lambda c: -float(c.get("score") or 0))
    L = [f"# Kit de postagem — {info.get('title') or os.path.basename(os.path.abspath(wd))}", ""]
    if info.get("webpage_url"):
        L += [f"Vídeo original: {info['webpage_url']}", ""]
    L += ["Ordem sugerida para postar: " + ", ".join(f"#{c['id']}" for c in rows), "",
          (f"Cada arquivo tem {cfg.get('pad_before', 0):g} s extras antes e {cfg.get('pad_after', 0):g} s depois "
           "do corte (quando o vídeo permite)." if float(cfg.get('pad_before', 0)) or float(cfg.get('pad_after', 0))
           else "Cada arquivo é o corte exato, pronto para postar sem editar (o corte sugerido é o arquivo inteiro). "
                f"Cortes marcados \"com folga\" têm {cfg.get('pad_folga', 10):g} s extras antes e depois."), ""]
    for c in rows:
        r = renders[str(c["id"])]
        L += [f"## {os.path.basename(r['file'])} — {hook_text(r)}", "",
              f"- Corte sugerido no arquivo: {r['suggested_cut_in_file']}"
              + (" (com folga)" if c.get("folga") else " (arquivo inteiro)" if r['suggested_cut_in_file'].startswith("0:00 a") else ""),
              f"- Horário no original: {r['original_time']}",
              f"- Título: {c.get('title', '')}"]
        if c.get("description"):
            L.append(f"- Descrição: {c['description']}")
        if c.get("hashtags"):
            tags = c["hashtags"] if isinstance(c["hashtags"], str) else " ".join(c["hashtags"])
            L.append(f"- Hashtags: {tags}")
        if c.get("aviso"):
            L.append(f"- ⚠ Aviso: {c['aviso']}")
        if c.get("reason"):
            L.append(f"- Por quê: {c['reason']}")
        L.append("")
    path = os.path.join(out_dir, "posting-kit.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


# ---------------------------------------------------------------- main

def main():
    from common import utf8_stdout
    utf8_stdout()
    no_power_throttling()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--source", help="default: <workdir>/source.mp4")
    ap.add_argument("--clips", help="default: <workdir>/clips.json")
    ap.add_argument("--out-dir", help="default: <workdir>/shorts")
    ap.add_argument("--template-dir", default=os.path.join(SKILL_DIR, "templates"))
    ap.add_argument("--style", choices=STYLES, help="force one style for every clip (default: clip's own 'style')")
    ap.add_argument("--cam", help="webcam box x,y,w,h as fractions of the frame (saved in setup.json)")
    ap.add_argument("--burned-subs", action="store_true", help="source has subtitles in the picture: no captions (saved)")
    ap.add_argument("--no-captions", action="store_true", help="no captions for this run only")
    ap.add_argument("--only", help="comma-separated clip ids")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--export-captions", type=int, metavar="N", help="original phrases of clip N, to translate")
    ap.add_argument("--kit", action="store_true", help="only rewrite shorts/posting-kit.md")
    ap.add_argument("--no-fetch", action="store_true",
                    help="bloco leve: não baixa sozinho o trecho em alta dos cortes que faltam (fetch_hd.py)")
    args = ap.parse_args()
    cfg = load_config()
    wd = args.workdir
    args.source = args.source or os.path.join(wd, "source.mp4")
    out_dir = args.out_dir or os.path.join(wd, "shorts")

    setup_path = os.path.join(wd, "setup.json")
    setup = json.load(open(setup_path, encoding="utf-8")) if os.path.exists(setup_path) else {}
    if not setup:      # bloco seguinte da mesma live (work/<id>-b2...): mesma caixa da webcam do bloco anterior
        import re as _re
        base = _re.sub(r"-b\d+$", "", os.path.basename(os.path.normpath(wd)))
        for sib in sorted(glob.glob(os.path.join(os.path.dirname(os.path.normpath(wd)), base + "-b*", "setup.json"))):
            if os.path.normpath(os.path.dirname(sib)) != os.path.normpath(wd):
                setup = json.load(open(sib, encoding="utf-8"))
                json.dump(setup, open(setup_path, "w", encoding="utf-8"), indent=2)
                print(f"  webcam do bloco anterior: {setup.get('cam')}")
                break
    if args.cam:
        setup["cam"] = [float(v) for v in args.cam.split(",")]
        if len(setup["cam"]) != 4:
            sys.exit("--cam precisa de 4 números: x,y,w,h")
    if args.burned_subs:
        setup["burned_subs"] = True
    if args.cam or args.burned_subs:
        json.dump(setup, open(setup_path, "w", encoding="utf-8"), indent=2)

    if args.preview:
        return preview(wd, out_dir)
    if args.snapshot:
        return snapshot(wd, args.source, setup.get("cam"))

    all_clips = json.load(open(args.clips or os.path.join(wd, "clips.json"), encoding="utf-8"))
    if args.kit:
        p = write_posting_kit(wd, out_dir, all_clips, cfg)
        return print(f"✓ {p}" if p else "Nenhum short renderizado ainda.")
    clips = all_clips
    if args.only:
        keep = {int(i) for i in args.only.split(",")}
        clips = [c for c in clips if int(c["id"]) in keep]
    tr_path = os.path.join(wd, "transcript.json")
    words = json.load(open(tr_path, encoding="utf-8"))["words"] if os.path.exists(tr_path) else []

    src_dur = duration(args.source)
    lang = video_language(wd)
    if args.export_captions is not None:
        c = next((c for c in all_clips if int(c["id"]) == args.export_captions), None)
        if not c:
            sys.exit(f"Corte #{args.export_captions} não está no clips.json")
        return export_captions(wd, c, words, cfg, src_dur, args.template_dir)

    from common import probe_av
    _pi = probe_av(args.source)
    sw, sh = _pi["width"], _pi["height"]
    src_w, src_h = int(sw), int(sh)
    os.makedirs(out_dir, exist_ok=True)

    # bloco baixado leve (fluxo rápido): o trecho em alta de cada corte que falta é baixado em paralelo
    # (fetch_hd.py) e cada short renderiza assim que o seu trecho chega, enquanto os outros ainda baixam.
    info = read_json(os.path.join(wd, "info.json"), {}) or {}
    need = []
    if info.get("analysis") and not args.no_fetch:
        need = [c for c in clips if not hd_source(wd, c, *clip_window(c, cfg, src_dur)[:2])]
    done, heights = [], {}

    def one(c):
        print(f"● ({len(done) + 1}/{len(clips)}) #{c['id']} [{args.style or c.get('style')}] {c.get('hook', '')}",
              flush=True)
        res = render(wd, c, words, args, setup, src_w, src_h, args.template_dir, out_dir, cfg, src_dur, lang)
        if res:
            done.append(update_renders(wd, out_dir, c, res, lang))
            heights[res["file"]] = res.get("height")

    for c in clips:
        if c not in need:
            one(c)
    if need:
        from fetch_hd import Blocked, fetch_iter
        print(f"↓ baixando {len(need)} corte(s) em alta em paralelo (cada um renderiza assim que chega)", flush=True)
        try:
            for c, r, msg in fetch_iter(wd, need, cfg):
                print("  " + msg, flush=True)
                if r:
                    one(c)
        except Blocked as e:
            print(chr(10).join(l for l in str(e).splitlines() if l.startswith(("✗", "  "))))
            write_posting_kit(wd, out_dir, all_clips, cfg)
            sys.exit(3)
    kit = write_posting_kit(wd, out_dir, all_clips, cfg)
    print(f"✓ {len(done)} shorts → {out_dir}" + (f"  (kit: {kit})" if kit else ""))
    for r in sorted(done, key=lambda r: r["file"]):
        h = heights.get(r["file"])
        print(f"  {os.path.basename(r['file'])}{f' {h}p' if h else ''} | {hook_text(r)} | corte no arquivo: "
              f"{r['suggested_cut_in_file']} | no original: {r['original_time']}")
    if len(done) < len(clips):
        sys.exit(1)


if __name__ == "__main__":
    main()
