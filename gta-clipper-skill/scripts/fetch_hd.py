#!/usr/bin/env python3
"""Baixa em alta (1080p ou acima, regra do download.py) só os trechos dos cortes escolhidos.

Fluxo rápido: o bloco é baixado leve (download.py --analysis, 480p) para transcrever, ler, ver frames e escolher
os cortes. Este script baixa cada corte em alta, com `hd_margin_seconds` de sobra dos dois lados, mede onde o
trecho começa e confere pelo áudio (correlação com a cópia leve) para o tempo bater no centésimo. O
make_shorts.py usa o trecho em alta sozinho (work/<id>/hd/hd.json) e, se faltar, chama este script.

Uso:
  fetch_hd.py work/<id> [--only 1,3] [--force] [--jobs 3]

Rápido: vários cortes ao mesmo tempo (download.hd_parallel) e sem perguntar de novo ao site (a info do vídeo fica
em cache desde o --probe). Corte que muda de tempo (passo 7b) e sai da sobra baixada é baixado de novo sozinho.
Saída 3 = YouTube bloqueou (precisa de cookies).
"""
import argparse
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from common import SKILL_DIR, load_config, read_json, secs, section_offset, utf8_stdout, write_json

SR = 8000
_lock = threading.Lock()


class Blocked(Exception):
    pass


def audio(path, start, dur):
    """mono 8 kHz float32 de [start, start+dur] do arquivo."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, start):.3f}", "-i", path,
                          "-t", f"{dur:.3f}", "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def refine_shift(low, hd, shift, at, win=20.0, search=1.5):
    """shift = (tempo no arquivo do bloco) - (tempo no arquivo hd). Ajusta pelo áudio em volta de `at`
    (tempo do bloco). Retorna (shift_ajustado, confiança 0..1)."""
    a = audio(low, at - search, win + 2 * search)          # bloco: janela maior
    b = audio(hd, at - shift, win)                          # hd: janela que deveria cair no meio de `a`
    if len(a) < SR * 2 or len(b) < SR * 2:
        return shift, 0.0
    a = a - a.mean(); b = b - b.mean()
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)[: len(a) - len(b) + 1]
    k = int(np.argmax(corr))
    seg = a[k:k + len(b)]
    conf = float(np.dot(seg, b) / (np.linalg.norm(seg) * np.linalg.norm(b) + 1e-9))
    lag = k / SR - search                                  # quanto o hd está adiantado em relação ao palpite
    return shift + lag, conf


def need_range(c, cfg):
    """o que o short usa do bloco (igual ao clip_window do make_shorts): corte + pad_before/pad_after,
    ou pad_folga dos dois lados no corte com "folga"."""
    s, e = secs(c["start"]), secs(c["end"])
    if c.get("folga"):
        pb = pa = float(cfg.get("pad_folga", 10))
    else:
        pb, pa = float(cfg.get("pad_before", 0)), float(cfg.get("pad_after", 0))
    return max(0.0, s - pb), e + pa


def have(wd, c, cfg):
    """registro do trecho em alta que já cobre o corte, ou None."""
    reg = read_json(os.path.join(wd, "hd", "hd.json"), {}) or {}
    r = reg.get(str(int(c["id"])))
    need_s, need_e = need_range(c, cfg)
    if r and os.path.exists(r["file"]) and r["covers"][0] <= need_s and r["covers"][1] >= need_e:
        return r
    return None


def fetch_one(wd, c, cfg, force=False):
    """Baixa o corte c em alta. Retorna (registro, texto_curto). Levanta Blocked se o YouTube bloquear."""
    cid = str(int(c["id"]))
    r = None if force else have(wd, c, cfg)
    if r:
        return r, f"#{cid}: já tinha em alta ({r['height']}p)"
    info = read_json(os.path.join(wd, "info.json"), {})
    url = info.get("webpage_url")
    if not url:
        raise RuntimeError("info.json sem webpage_url")
    margin = float(cfg.get("download", {}).get("hd_margin_seconds", 5))
    off = section_offset(wd)
    low = os.path.join(wd, "source.mp4")
    out = os.path.join(wd, "hd", f"c{cid}")
    os.makedirs(out, exist_ok=True)
    for f in ("source.mp4", "section.json"):
        p = os.path.join(out, f)
        if os.path.exists(p):
            os.remove(p)
    need_s, need_e = need_range(c, cfg)
    orig_s = max(0.0, off + need_s - margin)
    orig_e = off + need_e + margin
    cmd = [sys.executable, os.path.join(SKILL_DIR, "scripts", "download.py"), url, "--out", out,
           "--section", f"{orig_s:.2f}-{orig_e:.2f}", "--no-chat"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if p.returncode == 3:
        raise Blocked((p.stdout or "") + (p.stderr or ""))
    hd = os.path.join(out, "source.mp4")
    if p.returncode != 0 or not os.path.exists(hd):
        tail = "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-6:])
        raise RuntimeError(f"#{cid}: download em alta falhou\n{tail}")
    hd_off = section_offset(out)
    shift = hd_off - off                                 # tempo do bloco = tempo do hd + shift
    shift2, conf = refine_shift(low, hd, shift, secs(c["start"]) + 5, search=15.0)   # Twitch: início pode errar alguns segundos
    if conf >= 0.5 and abs(shift2 - shift) < 15:
        note = f"áudio conferido ({shift2 - shift:+.3f} s, conf {conf:.2f})"
        shift = shift2
    else:
        note = f"⚠ conferência pelo áudio fraca (conf {conf:.2f}); usando o início medido"
    hgt = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
                          "-of", "csv=p=0", hd], capture_output=True, text=True).stdout.strip()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", hd],
                               capture_output=True, text=True).stdout.strip() or 0)
    r = {"file": os.path.abspath(hd), "shift": round(shift, 3), "height": int(hgt or 0),
         "covers": [round(shift, 3), round(shift + dur, 3)], "audio_conf": round(conf, 2)}
    with _lock:
        reg_path = os.path.join(wd, "hd", "hd.json")
        reg = read_json(reg_path, {}) or {}
        reg[cid] = r
        write_json(reg_path, reg)
    low_h = "" if r["height"] >= 1080 else "  ⚠ abaixo de 1080p (o vídeo não tem mais)"
    return r, f"#{cid}: {r['height']}p em alta, {note}{low_h}"


def fetch_iter(wd, clips, cfg, jobs=None, force=False):
    """Baixa os cortes em paralelo e devolve (corte, registro_ou_None, texto) conforme cada um termina."""
    jobs = jobs or int(cfg.get("download", {}).get("hd_parallel", 3))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {ex.submit(fetch_one, wd, c, cfg, force): c for c in clips}
        for f in as_completed(futs):
            c = futs[f]
            try:
                r, msg = f.result()
                yield c, r, msg
            except Blocked:
                for g in futs:
                    g.cancel()
                raise
            except Exception as e:      # um corte que falha não derruba os outros
                yield c, None, str(e)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir")
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true", help="baixa de novo mesmo se já tiver")
    ap.add_argument("--jobs", type=int, help="quantos cortes ao mesmo tempo (padrão download.hd_parallel)")
    a = ap.parse_args()
    cfg = load_config()
    clips = read_json(os.path.join(a.workdir, "clips.json"), [])
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        clips = [c for c in clips if int(c["id"]) in keep]
    bad = 0
    try:
        for c, r, msg in fetch_iter(a.workdir, clips, cfg, a.jobs, a.force):
            print(msg)
            bad += r is None
    except Blocked as e:
        print("\n".join(l for l in str(e).splitlines() if l.startswith(("✗", "  "))))
        sys.exit(3)
    print(f"✓ {len(clips) - bad}/{len(clips)} cortes em alta → {os.path.join(a.workdir, 'hd', 'hd.json')}")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
