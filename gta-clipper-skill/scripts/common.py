#!/usr/bin/env python3
"""Shared helpers: config.json, paths (with environment-variable overrides) and time formats."""
import json
import os
import subprocess

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")

# config.json -> paths.<key> can be overridden by these environment variables
PATH_ENV = {
    "cookies_master": "YT_COOKIES_MASTER",
    "pot_script": "BGUTIL_POT_SCRIPT",
    "twitch_cli": "TWITCH_DOWNLOADER_CLI",
    "work_root": "CORTES_WORK_ROOT",
}


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def cfg_path(key, cfg=None):
    """paths.<key> from config.json (env var wins). '~' is expanded; relative = relative to the skill folder."""
    cfg = cfg or load_config()
    val = os.environ.get(PATH_ENV.get(key, "")) or (cfg.get("paths") or {}).get(key)
    if not val:
        return None
    val = os.path.expandvars(os.path.expanduser(val))
    if not os.path.isabs(val) and not (len(val) > 1 and val[1] == ":"):   # keep "C:\..." as is on any OS
        val = os.path.normpath(os.path.join(SKILL_DIR, val))
    return val


def twitch_cli_path(cfg=None):
    p = cfg_path("twitch_cli", cfg)
    if not p:
        return None
    for cand in (p, p + ".exe"):
        if os.path.isfile(cand):
            return cand
    return None


def secs(t):
    """'01:02:03.5' / '2:03' / 123.4 -> seconds (float)."""
    if isinstance(t, (int, float)):
        return float(t)
    v = 0.0
    for p in str(t).strip().split(":"):
        v = v * 60 + float(p)
    return v


def ts(s):
    """seconds -> HH:MM:SS"""
    s = int(round(max(0.0, s)))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def mmss(s):
    """seconds -> M:SS (short-file times, e.g. 0:10)"""
    s = int(round(max(0.0, s)))
    return f"{s // 60}:{s % 60:02d}"


def section_offset(workdir):
    """Absolute time (s) in the original video where source.mp4 starts (0 without --section)."""
    p = os.path.join(workdir, "section.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return float(json.load(f).get("offset", 0.0))
    return 0.0


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, indent=2):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def media_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- histórico por vídeo (não repetir cortes)

def video_key(extractor, vid):
    import re as _re
    return _re.sub(r"[^A-Za-z0-9_.-]", "_", f"{extractor or 'video'}_{vid}")


def history_path(extractor, vid, cfg=None):
    """<work_root>/historico/<plataforma>_<id>.json — um arquivo por vídeo/live, entre uma vez e outra."""
    root = cfg_path("work_root", cfg) or os.path.join(SKILL_DIR, "work")
    return os.path.join(root, "historico", video_key(extractor, vid) + ".json")


def merge_spans(spans):
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def history_summary(hist):
    """(trechos já cortados juntados, fim do último trecho cortado, nº de shorts).
    A próxima rodada continua depois do último trecho cortado: no modo abertura (ex.: 0:40–1:10) o bate-papo antes
    da abertura fica de fora e a live continua de ~1:05, não do começo."""
    spans = merge_spans([[b["start"], b["end"]] for b in hist.get("blocks", [])])
    covered = spans[-1][1] if spans else 0.0
    return spans, covered, len(hist.get("clips", []))


def continue_from(covered, cfg):
    """Onde a próxima rodada começa: fim do que já foi coberto menos a sobreposição
    (no máximo 1/4 do que foi coberto, para uma live recém-começada não refazer tudo)."""
    ov = min(float(cfg.get("chunk_overlap_minutes", 5)) * 60, covered * 0.25)
    return max(0.0, covered - ov)
