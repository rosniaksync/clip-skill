#!/usr/bin/env python3
"""Transcreve com tempo por palavra (faster-whisper). Idioma detectado automaticamente.

Uso:
  transcribe.py work/<id>/source.mp4                                  # vídeo inteiro (transcribe_fast: tiny)
  transcribe.py work/<id>/source.mp4 --candidates work/<id>/cands.json   # só os candidatos (transcribe_refine: small)
  transcribe.py work/<id>/source.mp4 --range 00:12:00-00:13:10        # só esses trechos (pode repetir)
  transcribe.py work/<id>/source.mp4 --detect-only                    # só detecta o idioma (lang.json)

Idioma: na primeira vez, pega 3 a 5 trechos de ~30 s espalhados pelo meio do vídeo (sem começo e fim),
detecta com o modelo tiny e usa o idioma que mais aparece (config.json -> language_detect). Grava em
work/<id>/lang.json; as transcrições seguintes usam esse idioma. --language força outro.

Com --candidates/--range, só esses trechos são transcritos e trocados dentro do transcript.json existente.
A margem dos candidatos (--pad) é no mínimo max(pad_before, pad_after, pad_folga), para a legenda cobrir um corte com folga.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

from common import load_config, media_duration, read_json, secs, ts, write_json


def merge_ranges(rs):
    out = []
    for s, e in sorted(rs):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def extract_wav(video, wav, start=None, length=None):
    cut = ["-ss", f"{start:.2f}", "-t", f"{length:.2f}"] if start is not None else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", *cut, "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav],
                   check=True)


class Models:
    """Carrega cada modelo uma vez só (CUDA se houver, senão CPU int8)."""
    def __init__(self):
        self.cache = {}
        self.device, self.ctype = "cpu", "int8"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                self.device, self.ctype = "cuda", "float16"
        except Exception:
            pass

    def get(self, name):
        if name not in self.cache:
            from faster_whisper import WhisperModel
            print(f"Carregando o modelo '{name}' ({self.device})…")
            self.cache[name] = WhisperModel(name, device=self.device, compute_type=self.ctype)
        return self.cache[name]


def sample_points(duration, lcfg):
    """Centros dos trechos de amostra, espalhados pelo meio do vídeo (evita começo e fim)."""
    n_max, n_min = int(lcfg.get("samples", 5)), int(lcfg.get("min_samples", 3))
    L, skip = float(lcfg.get("sample_seconds", 30)), float(lcfg.get("skip_edges", 0.15))
    a, b = duration * skip, duration * (1 - skip)
    if b - a < L:                       # vídeo muito curto: usa o vídeo quase todo
        a, b = 0.0, duration
    n = max(n_min, min(n_max, int((b - a) // (2 * L)) or n_min))
    step = (b - a) / n
    starts = [max(0.0, min(duration - L, a + step * (k + 0.5) - L / 2)) for k in range(n)]
    return [round(s, 2) for s in starts], min(L, duration)


def vote(results, min_prob):
    """results = [(lang, prob)]: idioma que mais aparece (empate: maior soma de probabilidade)."""
    ok = [(l, p) for l, p in results if l and p >= min_prob] or [(l, p) for l, p in results if l]
    if not ok:
        return None
    cnt, psum = Counter(l for l, _ in ok), defaultdict(float)
    for l, p in ok:
        psum[l] += p
    return max(cnt, key=lambda l: (cnt[l], psum[l]))


def detect_language(video, cfg, models):
    lcfg = cfg.get("language_detect", {})
    dur = media_duration(video)
    starts, L = sample_points(dur, lcfg)
    model = models.get(lcfg.get("model", "tiny"))
    tmp = tempfile.mkdtemp(prefix="lang_")
    results = []
    try:
        for k, s in enumerate(starts, 1):
            wav = os.path.join(tmp, f"s{k}.wav")
            extract_wav(video, wav, s, L)
            _, info = model.transcribe(wav, beam_size=1, vad_filter=True, without_timestamps=True)
            results.append((info.language, round(float(info.language_probability or 0), 3)))
            print(f"  amostra {k}/{len(starts)} em {ts(s)}: {info.language} ({results[-1][1]:.2f})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lang = vote(results, float(lcfg.get("min_probability", 0.4)))
    if not lang:
        sys.exit("Não deu para detectar o idioma (amostras sem fala). Rode com --language xx.")
    return lang, [{"start": s, "language": l, "prob": p} for s, (l, p) in zip(starts, results)]


def get_language(video, workdir, cfg, models, forced=None):
    lpath = os.path.join(workdir, "lang.json")
    if forced:
        write_json(lpath, {"language": forced, "source": "manual"})
        return forced
    saved = read_json(lpath)
    if saved and saved.get("language"):
        return saved["language"]
    print("Detectando o idioma…")
    lang, samples = detect_language(video, cfg, models)
    write_json(lpath, {"language": lang, "source": "auto", "model": cfg.get("language_detect", {}).get("model", "tiny"),
                       "samples": samples})
    print(f"✓ Idioma detectado: {lang} → lang.json" + ("" if lang == "pt" else
          "  (vídeo gringo: a legenda do short sai traduzida para português)"))
    return lang


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", help="tiny|base|small|medium|large-v3 (padrão: config.json)")
    ap.add_argument("--beam", type=int, help="beam size (1 = mais rápido; padrão: config.json)")
    ap.add_argument("--language", help="força o idioma (ex.: pt, en); sem isso usa lang.json / detecção")
    ap.add_argument("--range", action="append", help="só transcreve S-E (hh:mm:ss); pode repetir")
    ap.add_argument("--candidates", help="JSON [{start,end}] (seg ou hh:mm:ss): só esses trechos (passada small)")
    ap.add_argument("--pad", type=float, help="margem antes/depois de cada candidato (mín. max(pad_before, pad_after, pad_folga))")
    ap.add_argument("--detect-only", action="store_true", help="só detecta o idioma e grava lang.json")
    a = ap.parse_args()

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        sys.exit("faster-whisper não instalado: pip install -r requirements.txt")

    out_dir = os.path.dirname(os.path.abspath(a.video))
    tpath = os.path.join(out_dir, "transcript.json")
    models = Models()
    lang = get_language(a.video, out_dir, cfg, models, a.language)
    if a.detect_only:
        return

    refine = bool(a.candidates or a.range)
    pcfg = cfg.get("transcribe_refine" if refine else "transcribe_fast", {})
    model_name = a.model or pcfg.get("model", "small" if refine else "tiny")
    beam = a.beam or pcfg.get("beam", 5 if refine else 1)
    min_pad = max(float(cfg.get("pad_before", 0)), float(cfg.get("pad_after", 0)), float(cfg.get("pad_folga", 10)))
    pad = max(a.pad if a.pad is not None else float(cfg.get("transcribe_refine", {}).get("pad_seconds", 10)), min_pad)

    total = media_duration(a.video)
    ranges = []
    for r in a.range or []:
        s, e = (secs(x) for x in r.split("-"))
        ranges.append((max(0.0, s), min(total, e) if total else e))
    if a.candidates:
        with open(a.candidates, encoding="utf-8") as f:
            for c in json.load(f):
                ranges.append((max(0.0, secs(c["start"]) - pad), min(total, secs(c["end"]) + pad) if total
                               else secs(c["end"]) + pad))
    ranges = merge_ranges(ranges) if ranges else [[0.0, None]]   # None = vídeo inteiro

    model = models.get(model_name)
    tmp = tempfile.mkdtemp(prefix="clipper_")
    segments, words, duration = [], [], None
    try:
        for k, (rs, re_) in enumerate(ranges, 1):
            wav = os.path.join(tmp, f"a{k}.wav")
            print(f"Extraindo áudio {k}/{len(ranges)}" + (f" ({ts(rs)}–{ts(re_)})" if re_ is not None else "") + "…")
            extract_wav(a.video, wav, rs if re_ is not None else None, (re_ - rs) if re_ is not None else None)
            segs, info = model.transcribe(wav, language=lang, word_timestamps=True, vad_filter=True, beam_size=beam)
            duration = info.duration if re_ is None else duration
            for s in segs:
                words.extend({"w": w.word.strip(), "s": round(w.start + rs, 2), "e": round(w.end + rs, 2)}
                             for w in (s.words or []) if w.word.strip())
                segments.append({"s": round(s.start + rs, 2), "e": round(s.end + rs, 2), "text": s.text.strip()})
                print(f"\r  transcrito até {ts(s.end + rs)}", end="", flush=True)
            print()
            os.remove(wav)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if ranges[0][1] is not None and os.path.exists(tpath):   # troca só os trechos dentro do transcript existente
        with open(tpath, encoding="utf-8") as f:
            old = json.load(f)

        def outside(x):
            return all(x["e"] <= rs or x["s"] >= re_ for rs, re_ in ranges)
        words = [w for w in old["words"] if outside(w)] + words
        segments = [x for x in old["segments"] if outside(x)] + segments
        duration = old.get("duration")
    words.sort(key=lambda w: w["s"])
    segments.sort(key=lambda x: x["s"])
    write_json(tpath, {"language": lang, "duration": duration or total, "segments": segments, "words": words},
               indent=None)
    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[{ts(s['s'])}] {s['text']}\n")
    print(f"✓ {len(segments)} frases, {len(words)} palavras ({model_name}, idioma {lang}) → transcript.json / transcript.txt")


if __name__ == "__main__":
    main()
