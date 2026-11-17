#!/usr/bin/env python3
"""Render clips.json into finished 1080x1920 shorts using one of two styles.

Styles (each one is a JSON template in ../templates/<style>.json):
  cam    video WITH webcam: facecam on top, gameplay below, title card on the split
  nocam  video WITHOUT webcam: blurred background, gameplay in the middle, title on top

Every colour, font, size, position and the channel name live in the templates.
Each clip in clips.json carries "style", "hook" and "subhook".

Usage:
  make_shorts.py work/<id> --snapshot                   # frames to detect webcam / burned-in subs
  make_shorts.py work/<id> --cam 0.72,0.68,0.27,0.30    # save webcam box (x,y,w,h fractions) and render
  make_shorts.py work/<id> --burned-subs                # source already has subtitles -> no captions
  make_shorts.py work/<id> [--only 1,4] [--style cam|nocam] [--template-dir DIR]
  make_shorts.py work/<id> --preview                    # contact sheet of rendered shorts

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

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLES = ("cam", "nocam")
FPS = 30

# ---------------------------------------------------------------- helpers

def secs(t):
    if isinstance(t, (int, float)):
        return float(t)
    v = 0.0
    for p in str(t).split(":"):
        v = v * 60 + float(p)
    return v


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
    return float(ffprobe(path, "format=duration") or 0)


def load_template(tdir, style):
    path = os.path.join(tdir, f"{style}.json")
    if not os.path.exists(path):
        sys.exit(f"Template not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- fonts

def resolve_font(spec, tdir=None):
    """spec = {"file": "fonts/X.ttf"}: direct path, absolute or relative to the skill folder. No searching."""
    path = spec["file"]
    if not os.path.isabs(path):
        path = os.path.join(SKILL_DIR, path)
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        sys.exit(f"Font file not found: {path}")
    return path


def pil_font(path, size):
    return ImageFont.truetype(path, size)


def fit_font(text, spec, size, min_size, max_width, tdir, stroke=0):
    path = resolve_font(spec, tdir)
    while True:
        f = pil_font(path, size)
        w = f.getlength(text) + 2 * stroke
        if w <= max_width or size <= min_size:
            return f
        size -= 2


# ---------------------------------------------------------------- title images (Pillow)

def lines_of(clip):
    return [clip.get("hook", ""), clip.get("subhook", "")]


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
    specs = [c["line1"], c["line2"]]
    items = []
    for t, sp in zip(texts, specs):
        if t:
            items.append((t, fit_font(t, sp["font"], sp["size"], sp["min_size"], inner_max, tdir), sp["color"]))
    if not items:
        return None

    metrics = []
    for t, f, col in items:
        l, tp, r, b = f.getbbox(t)
        metrics.append((r - l, b - tp, tp, l))
    text_w = max(m[0] for m in metrics)
    text_h = sum(m[1] for m in metrics) + box["line_gap"] * (len(items) - 1)
    box_w = text_w + 2 * (box["padding_x"] + bw) + logo_w
    box_h = max(text_h + 2 * (box["padding_y"] + bw), (logo_size + 2 * (bw + 12)) if logo_spec else 0)

    ch = clean_text(tpl.get("channel_name", ""), tag.get("uppercase", True))
    tag_img = None
    if ch:
        tf = pil_font(resolve_font(tag["font"], tdir), tag["size"])
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
    cx = bx + bw + box["padding_x"] + logo_w + text_w / 2
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
    specs = [t["line1"], t["line2"]]
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


def render_title(tpl, clip, tdir):
    """nocam style: white caps, thick font, black outline, 2 lines."""
    t = tpl["title"]
    up = t.get("uppercase", True)
    st = t["outline"]
    texts = [clean_text(x, up) for x in lines_of(clip)]
    specs = [t["line1"], t["line2"]]
    items = []
    for x, sp in zip(texts, specs):
        if x:
            items.append((x, fit_font(x, sp["font"], sp["size"], sp["min_size"], t["max_width"], tdir, st), sp["color"]))
    if not items:
        return None
    metrics = [f.getbbox(x, stroke_width=st) for x, f, _ in items]
    w = max(m[2] - m[0] for m in metrics) + 4
    h = sum(m[3] - m[1] for m in metrics) + t["line_gap"] * (len(items) - 1) + 4
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 2
    for (x, f, col), m in zip(items, metrics):
        lw = m[2] - m[0]
        px = {"left": 2, "right": w - lw - 2}.get(t.get("align", "center"), (w - lw) // 2)
        d.text((px - m[0], y - m[1]), x, font=f, fill=hex_rgb(col),
               stroke_width=st, stroke_fill=hex_rgb(t["outline_color"]))
        y += m[3] - m[1] + t["line_gap"]
    return img


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


def build_ass(path, words, clip_len, cap, family, canvas, pos_xy, an):
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
    for g in group_words(words, cap["max_words"], cap["max_chars"], cap["max_gap"]):
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


def filter_cam(tpl, cam, src_w, src_h, card_xy, ass_name, fontsdir, with_card):
    W = tpl["canvas"]["w"]
    L = tpl["layout"]
    ch, gh, fx = L["cam_height"], L["game_height"], L["game_focus_x"]
    bw, bh, px, py = cam_box_px(cam, src_w, src_h, W / ch)
    flags = L.get("scale_flags", "bicubic")                  # e.g. "lanczos" for a sharper upscale of the webcam
    sharp = f",{L['cam_sharpen']}" if L.get("cam_sharpen") else ""   # e.g. "unsharp=5:5:0.7:3:3:0.0"
    f = (f"[0:v]split[c][g];"
         f"[c]crop={bw}:{bh}:{px}:{py},scale={W}:{ch}:force_original_aspect_ratio=increase:flags={flags},"
         f"crop={W}:{ch}{sharp}[cam];"
         f"[g]scale={W}:{gh}:force_original_aspect_ratio=increase:flags={flags},"
         f"crop={W}:{gh}:(iw-{W})*{fx}:0[game];"
         f"[cam][game]vstack[base]")
    last = "base"
    if with_card:
        f += f";[{last}][1:v]overlay={card_xy[0]}:{card_xy[1]}[withcard]"
        last = "withcard"
    return f, last


def filter_nocam(tpl, title_xy, ass_name, fontsdir, with_title):
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

def render(workdir, clip, words, args, setup, src_w, src_h, tdir, out_dir):
    style = args.style or clip.get("style")
    if style not in STYLES:
        print(f"  skip #{clip['id']}: style must be one of {STYLES} (got {style!r})")
        return None
    tpl = load_template(tdir, style)
    W, H = tpl["canvas"]["w"], tpl["canvas"]["h"]

    s, e = secs(clip["start"]), secs(clip["end"])
    if e <= s:
        print(f"  skip #{clip['id']}: end before start"); return None
    s = max(0, s - 0.05)
    length = e - s
    name = f"short_{int(clip['id']):02d}"
    tmp = tempfile.mkdtemp(prefix=name + "_", dir=out_dir)
    try:
        # --- title overlay (PNG) for the whole clip
        overlay_png, overlay_xy, img, card_margin = None, (0, 0), None, 0
        if style == "nocam" and "stack" in tpl:
            img, gm = render_stack(tpl, clip, tdir, W)
            overlay_xy = (0, tpl["stack"]["y_top"] - gm)
        elif style == "cam" or "card" in tpl:   # nocam can also use the card (logo + channel tag) instead of the white title
            r = render_card(tpl, clip, tdir, W)
            if r:
                img, box_cy, card_margin = r
                overlay_xy = ((W - img.width) // 2, tpl["card"]["anchor_y"] - box_cy)
        else:
            img = render_title(tpl, clip, tdir)
            if img:
                overlay_xy = ((W - img.width) // 2, tpl["title"]["y_top"])
        if img:
            overlay_png = os.path.join(tmp, "overlay.png")
            img.save(overlay_png)

        # --- word-by-word captions, only if the picture has no burned-in subtitles
        want_caps = not args.no_captions and not setup.get("burned_subs") and clip.get("captions", True)
        cw = [{"w": w["w"], "s": round(w["s"] - s, 3), "e": round(w["e"] - s, 3)}
              for w in words if w["s"] >= s - 0.01 and w["e"] <= e + 0.3] if want_caps else []
        has_caps = bool(cw)
        fontsdir = ""
        ass_path = os.path.join(tmp, "cap.ass")
        if has_caps:
            cap = tpl["captions"]
            font_path = resolve_font(cap["font"], tdir)
            fontsdir = os.path.dirname(font_path)
            family = " ".join(pil_font(font_path, 20).getname()).replace(" Regular", "")
            if cap.get("anchor") == "above_card" and overlay_png:   # bottom of text = gap px above the card tag
                pos_xy, an = (cap["x"], overlay_xy[1] + card_margin - cap.get("gap", 5)), 2
            else:
                pos_xy, an = (cap["x"], cap["y"]), cap.get("an", 5)
            build_ass(ass_path, cw, length, cap, family, tpl["canvas"], pos_xy, an)

        # --- ffmpeg graph
        if style == "cam":
            cam = clip.get("cam") or setup.get("cam")
            if not cam:
                sys.exit("cam style needs the webcam box: run --snapshot, estimate it and pass --cam x,y,w,h")
            graph, last = filter_cam(tpl, cam, src_w, src_h, overlay_xy, "cap.ass", "fonts", bool(overlay_png))
        else:
            graph, last = filter_nocam(tpl, overlay_xy, "cap.ass", "fonts", bool(overlay_png))
        if has_caps:
            fd = fontsdir.replace("\\", "/").replace(":", "\\:")
            graph += f";[{last}]ass=cap.ass:fontsdir='{fd}'[cap]"
            last = "cap"
        graph += f";[{last}]format=yuv420p[v]"

        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{s:.3f}", "-i", os.path.abspath(args.source)]
        if overlay_png:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-i", "overlay.png"]
        out_name = f"{name}.mp4"
        cmd += ["-t", f"{length:.3f}", "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-crf", "20", "-r", str(FPS),
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", os.path.abspath(os.path.join(out_dir, out_name))]
        subprocess.run(cmd, check=True, cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    out = os.path.join(out_dir, out_name)
    verify(out)
    return out


def verify(path):
    def probe(stream):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
                              "stream=codec_name,pix_fmt", "-of", "default=nw=1", path],
                             capture_output=True, text=True).stdout
        return dict(l.split("=", 1) for l in out.split() if "=" in l)
    v, a = probe("v:0"), probe("a:0")
    if v.get("codec_name") != "h264" or v.get("pix_fmt") != "yuv420p" or (a and a.get("codec_name") != "aac"):
        sys.exit(f"Encoding check failed for {path}: video={v} audio={a} (need h264/yuv420p/aac)")


# ---------------------------------------------------------------- snapshot / preview

def snapshot(workdir, source, cam):
    d = duration(source)
    fracs = (0.08, 0.22, 0.38, 0.54, 0.70, 0.86)
    paths = []
    for i, fr in enumerate(fracs, 1):
        p = os.path.join(workdir, f"snapshot_{i}.jpg")
        vf = "scale=1280:-2"
        if cam:
            x, y, w, h = cam
            vf += f",drawbox=x=iw*{x}:y=ih*{y}:w=iw*{w}:h=ih*{h}:color=red@0.9:t=4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{d * fr:.1f}", "-i", source,
                        "-frames:v", "1", "-vf", vf, p], check=True)
        paths.append(p)
    sheet = os.path.join(workdir, "snapshot.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(workdir, "snapshot_%d.jpg"),
                    "-vf", "scale=640:-2,tile=3x2:padding=4:color=black", "-frames:v", "1", sheet], check=True)
    print(f"✓ {sheet}  (+ snapshot_1..6.jpg full size{', webcam box in red' if cam else ''})")
    print("  Look for: (1) a webcam overlay, (2) subtitles burned into the picture.")


def preview(workdir, out_dir):
    shorts = sorted(glob.glob(os.path.join(out_dir, "short_*.mp4")))
    if not shorts:
        sys.exit("No shorts rendered yet.")
    tmp = tempfile.mkdtemp()
    k = 0
    for p in shorts:
        d = duration(p)
        for frac in (0.08, 0.45, 0.85):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{d * frac:.2f}", "-i", p,
                            "-frames:v", "1", "-vf", "scale=360:640",
                            os.path.join(tmp, f"{k:04d}.jpg")], check=True)
            k += 1
    cols = 3 * 2 if k > 3 else 3
    rows = math.ceil(k / cols)
    out = os.path.join(out_dir, "preview.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(tmp, "%04d.jpg"),
                    "-vf", f"tile={min(cols, k)}x{rows}:padding=6:color=black", "-frames:v", "1", out], check=True)
    shutil.rmtree(tmp)
    print(f"✓ Preview → {out}  (3 frames per short)")


# ---------------------------------------------------------------- main

def main():
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
    args = ap.parse_args()
    wd = args.workdir
    args.source = args.source or os.path.join(wd, "source.mp4")
    out_dir = args.out_dir or os.path.join(wd, "shorts")

    setup_path = os.path.join(wd, "setup.json")
    setup = json.load(open(setup_path, encoding="utf-8")) if os.path.exists(setup_path) else {}
    if args.cam:
        setup["cam"] = [float(v) for v in args.cam.split(",")]
        if len(setup["cam"]) != 4:
            sys.exit("--cam needs 4 numbers: x,y,w,h")
    if args.burned_subs:
        setup["burned_subs"] = True
    if args.cam or args.burned_subs:
        json.dump(setup, open(setup_path, "w", encoding="utf-8"), indent=2)

    if args.preview:
        return preview(wd, out_dir)
    if args.snapshot:
        return snapshot(wd, args.source, setup.get("cam"))

    clips = json.load(open(args.clips or os.path.join(wd, "clips.json"), encoding="utf-8"))
    if args.only:
        keep = {int(i) for i in args.only.split(",")}
        clips = [c for c in clips if int(c["id"]) in keep]
    tr_path = os.path.join(wd, "transcript.json")
    words = json.load(open(tr_path, encoding="utf-8"))["words"] if os.path.exists(tr_path) else []

    sw, sh = ffprobe(args.source, "stream=width,height", "v:0").split()[0].split(",")[:2]
    src_w, src_h = int(sw), int(sh)
    os.makedirs(out_dir, exist_ok=True)

    done = []
    for n, c in enumerate(clips, 1):
        print(f"● Renderizando ({n}/{len(clips)}) — #{c['id']} [{args.style or c.get('style')}] {c.get('hook', '')}")
        p = render(wd, c, words, args, setup, src_w, src_h, args.template_dir, out_dir)
        if p:
            done.append(p)
    print(f"✓ {len(done)} shorts → {out_dir}")


if __name__ == "__main__":
    main()
