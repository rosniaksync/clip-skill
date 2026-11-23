#!/usr/bin/env python3
"""Transcreve com tempo por palavra (faster-whisper). Idioma detectado automaticamente.

Uso:
  transcribe.py work/<id>/source.mp4                                  # vídeo inteiro (transcribe_fast: small)
  transcribe.py work/<id>/source.mp4 --candidates work/<id>/cands.json   # só os candidatos (transcribe_refine: small)
  transcribe.py work/<id>/source.mp4 --range 00:12:00-00:13:10        # só esses trechos (pode repetir)
  transcribe.py work/<id>/source.mp4 --detect-only                    # só detecta o idioma (lang.json)

Rápido em CPU: o áudio (16 kHz mono) é extraído uma vez e guardado em work/<id>/audio16k.pcm (as passadas
seguintes reaproveitam), o modelo usa todos os núcleos (transcribe.cpu_threads, 0 = todos) e a passada roda no
modo em lote do faster-whisper (transcribe.batch_size; --no-batch volta ao modo antigo, frase por frase).
O lote não tem o "fallback" de temperatura do modo antigo: os pedaços que saem em laço (frase repetida) são
refeitos sozinhos no modo antigo. Saída curta: uma linha no fim.

Idioma: na primeira vez, pega 3 a 5 trechos de ~30 s espalhados pelo meio do vídeo (sem começo e fim),
detecta com o modelo tiny e usa o idioma que mais aparece (config.json -> language_detect). Para cedo se os 3
primeiros concordarem com folga. Grava em work/<id>/lang.json; as transcrições seguintes usam esse idioma.

Com --candidates/--range, só esses trechos são transcritos e trocados dentro do transcript.json existente
(o transcript guarda em "refined" os trechos que já passaram pelo small).
A margem dos candidatos (--pad) é no mínimo max(pad_before, pad_after, pad_folga), para a legenda cobrir um corte com folga.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict

import numpy as np

from common import load_config, no_power_throttling, read_json, secs, ts, utf8_stdout, write_json

SR = 16000


def merge_ranges(rs):
    out = []
    for s, e in sorted(rs):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def load_audio(video, workdir):
    """Áudio 16 kHz mono float32 do vídeo inteiro. Cache em audio16k.pcm (int16), refeito se o vídeo mudar."""
    pcm, meta = os.path.join(workdir, "audio16k.pcm"), os.path.join(workdir, "audio16k.json")
    st = os.stat(video)
    key = {"size": st.st_size, "mtime": int(st.st_mtime)}
    if os.path.exists(pcm) and read_json(meta) == key:
        return np.fromfile(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", video, "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    with open(pcm, "wb") as f:
        f.write(raw)
    write_json(meta, key)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


class Models:
    """Carrega cada modelo uma vez só (CUDA se houver, senão CPU int8 com todos os núcleos)."""
    def __init__(self, cfg):
        self.cache = {}
        self.device, self.ctype = "cpu", "int8"
        tcfg = cfg.get("transcribe", {})
        self.threads = int(tcfg.get("cpu_threads", 0)) or (os.cpu_count() or 4)
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                self.device, self.ctype = "cuda", "float16"
        except Exception:
            pass

    def get(self, name):
        if name not in self.cache:
            from faster_whisper import WhisperModel
            kw = dict(device=self.device, compute_type=self.ctype, cpu_threads=self.threads if self.device == "cpu" else 0)
            try:                      # modelo já baixado: não consulta a internet (~1,5 s por modelo)
                self.cache[name] = WhisperModel(name, local_files_only=True, **kw)
            except Exception:
                self.cache[name] = WhisperModel(name, **kw)
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


def detect_language(audio, cfg, models):
    lcfg = cfg.get("language_detect", {})
    dur = len(audio) / SR
    starts, L = sample_points(dur, lcfg)
    model = models.get(lcfg.get("model", "tiny"))
    n_min = int(lcfg.get("min_samples", 3))
    results = []
    for s in starts:
        chunk = audio[int(s * SR):int((s + L) * SR)]
        try:
            lang, prob, _ = model.detect_language(audio=chunk, vad_filter=True)
        except Exception:            # trecho sem fala nenhuma
            lang, prob = None, 0.0
        results.append((lang, round(float(prob or 0), 3)))
        langs = {l for l, p in results}
        if len(results) >= n_min and len(langs) == 1 and min(p for _, p in results) >= 0.8:
            break                    # os primeiros concordam com folga: não precisa das outras amostras
    lang = vote(results, float(lcfg.get("min_probability", 0.4)))
    if not lang:
        sys.exit("Não deu para detectar o idioma (amostras sem fala). Rode com --language xx.")
    return lang, [{"start": s, "language": l, "prob": p} for s, (l, p) in zip(starts, results)]


def get_language(audio, workdir, cfg, models, forced=None):
    lpath = os.path.join(workdir, "lang.json")
    if forced:
        write_json(lpath, {"language": forced, "source": "manual"})
        return forced, False
    saved = read_json(lpath)
    if saved and saved.get("language"):
        return saved["language"], False
    # bloco seguinte da mesma live (work/<id>-b2, -b3...): reaproveita o idioma do bloco anterior
    import glob, re as _re
    base = _re.sub(r"-b\d+$", "", os.path.basename(os.path.normpath(workdir)))
    for sib in sorted(glob.glob(os.path.join(os.path.dirname(os.path.normpath(workdir)), base + "-b*", "lang.json"))):
        prev = read_json(sib)
        if prev and prev.get("language") and os.path.normpath(os.path.dirname(sib)) != os.path.normpath(workdir):
            write_json(lpath, {**prev, "source": "bloco anterior"})
            return prev["language"], False
    lang, samples = detect_language(audio, cfg, models)
    write_json(lpath, {"language": lang, "source": "auto", "model": cfg.get("language_detect", {}).get("model", "tiny"),
                       "samples": samples})
    return lang, True


def repeats(tokens, times=4, max_n=6):
    """True se algum trecho de 1..max_n palavras se repete `times` vezes seguidas (laço do whisper)."""
    t = [x.lower().strip(".,!?…") for x in tokens]
    for n in range(1, max_n + 1):
        for i in range(0, len(t) - times * n + 1):
            g = t[i:i + n]
            if all(t[i + k * n:i + (k + 1) * n] == g for k in range(1, times)):
                return True
    return False


def collapse_repeats(words, max_n=6):
    """Tira repetição em sequência (laço do whisper): trecho de 2+ palavras fica no máximo 2 vezes seguidas
    ('de um de um de um de um' -> 'de um de um'); palavra sozinha, no máximo 4 ('não não não não')."""
    out = list(words)
    changed = True
    while changed:
        changed = False
        t = [w["w"].lower().strip(".,!?…") for w in out]
        for n in range(1, max_n + 1):
            keep = 4 if n == 1 else 2
            i = 0
            while i + (keep + 1) * n <= len(t):
                g = t[i:i + n]
                k = 1
                while t[i + k * n:i + (k + 1) * n] == g:
                    k += 1
                if k > keep:
                    del out[i + keep * n:i + k * n]
                    del t[i + keep * n:i + k * n]
                    changed = True
                i += 1
    return out


def to_rows(segs, offset):
    segments, words = [], []
    for s in segs:
        ws = [{"w": w.word.strip(), "s": round(w.start + offset, 2), "e": round(w.end + offset, 2)}
              for w in (s.words or []) if w.word.strip()]
        words += ws
        segments.append({"s": round(s.start + offset, 2), "e": round(s.end + offset, 2), "text": s.text.strip(),
                         "_w": ws})
    return segments, words


def progress(msg, t0):
    """Linha de progresso com o tempo decorrido; flush para aparecer no log na hora."""
    el = time.time() - t0
    print(f"… {msg} ({int(el // 60)} min {int(el % 60):02d} s)", flush=True)


def run_pass(model, audio, lang, beam, batched, batch_size, offset, collapse, ngram=0, redo_loops=True, cr_max=2.4):
    """Transcreve um trecho (array 16 kHz) -> (segments, words, n_refeitos) em tempo do arquivo.
    Lote = rápido, mas sem o 'fallback' de temperatura do modo antigo. Contra laço (frase repetida):
      ngram > 0 (passada de leitura, tiny): o modelo não pode repetir sequências de `ngram` tokens no pedaço;
      redo_loops (passada small): os pedaços que saem em laço (compressão > cr_max ou frase repetida 4x) são
      refeitos no modo antigo, só eles; collapse: tira repetição em sequência que ainda sobrar (só leitura)."""
    if batched:
        from faster_whisper import BatchedInferencePipeline
        segs, _ = BatchedInferencePipeline(model=model).transcribe(
            audio, language=lang, beam_size=beam, word_timestamps=True, vad_filter=True, batch_size=batch_size,
            no_repeat_ngram_size=ngram)
    else:
        segs, _ = model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True, beam_size=beam)
    t0, total_min, step, segs_l = time.time(), len(audio) / SR / 60, 5.0, []
    next_mark = step
    for s in segs:                        # progresso a cada 5 min de áudio (o log fica vivo)
        segs_l.append(s)
        if s.end / 60 >= next_mark:
            progress(f"transcrição {s.end / 60:.0f}/{total_min:.0f} min", t0)
            next_mark = (s.end / 60 // step + 1) * step
    segs = segs_l
    progress(f"transcrição {total_min:.0f}/{total_min:.0f} min (passada principal pronta)", t0)
    redo = 0
    if batched and redo_loops:
        bad = [s for s in segs if (s.compression_ratio or 0) > cr_max or repeats(s.text.split())]
        regions = merge_ranges([[max(0.0, s.start - 0.2), s.end + 0.2] for s in bad])
        good = [s for s in segs if s not in bad]
        segments, words = to_rows(good, offset)
        if regions:
            progress(f"refazendo {len(regions)} trecho(s) em laço", t0)
        for i, (ra, rb) in enumerate(regions, 1):
            if i % 10 == 0:
                progress(f"  laço {i}/{len(regions)}", t0)
            sub, _ = model.transcribe(audio[int(ra * SR):int(rb * SR)], language=lang, word_timestamps=True,
                                      vad_filter=True, beam_size=beam)
            s2, w2 = to_rows(list(sub), offset + ra)
            lo, hi = offset + ra + 0.2, offset + rb - 0.2      # sem duplicar as palavras da margem
            segments += [x for x in s2 if lo - 0.1 <= (x["s"] + x["e"]) / 2 <= hi + 0.1]
            words += [w for w in w2 if lo <= (w["s"] + w["e"]) / 2 <= hi]
            redo += 1
        segments.sort(key=lambda x: x["s"])
        words.sort(key=lambda w: w["s"])
    else:
        segments, words = to_rows(segs, offset)
    if batched and collapse:
        # o lote às vezes devolve vazio um pedaço com fala (buraco > 12 s): preenche no modo antigo, sem fallback
        dur = len(audio) / SR
        edges = [offset] + [x for w in words for x in (w["s"], w["e"])] + [offset + dur]
        holes = [(edges[i], edges[i + 1]) for i in range(0, len(edges) - 1, 2) if edges[i + 1] - edges[i] > 12]
        if holes:
            progress(f"preenchendo {len(holes)} buraco(s) sem fala (> 12 s)", t0)
        for i, (ha, hb) in enumerate(holes, 1):
            if i % 10 == 0:
                progress(f"  buraco {i}/{len(holes)}", t0)
            ra, rb = max(0.0, ha - offset), min(dur, hb - offset)
            sub, _ = model.transcribe(audio[int(ra * SR):int(rb * SR)], language=lang, word_timestamps=True,
                                      vad_filter=True, beam_size=beam, temperature=0.0,
                                      condition_on_previous_text=False, no_repeat_ngram_size=ngram)
            s2, w2 = to_rows(list(sub), offset + ra)
            if w2:
                segments += s2
                words += w2
                redo += 1
        segments.sort(key=lambda x: x["s"])
        words.sort(key=lambda w: w["s"])
    if collapse:
        words = collapse_repeats(words)
    kept = {id(w) for w in words}
    for x in segments:                     # texto da frase sem a repetição que saiu das palavras
        ws = x.pop("_w")
        if ws and any(id(w) not in kept for w in ws):
            x["text"] = " ".join(w["w"] for w in ws if id(w) in kept)
    return [x for x in segments if x["text"]], words, redo


def main():
    utf8_stdout()
    no_power_throttling()
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", help="tiny|base|small|medium|large-v3 (padrão: config.json)")
    ap.add_argument("--beam", type=int, help="beam size (1 = mais rápido; padrão: config.json)")
    ap.add_argument("--language", help="força o idioma (ex.: pt, en); sem isso usa lang.json / detecção")
    ap.add_argument("--range", action="append", help="só transcreve S-E (hh:mm:ss); pode repetir")
    ap.add_argument("--candidates", help="JSON [{start,end}] (seg ou hh:mm:ss): só esses trechos (passada small)")
    ap.add_argument("--ids", help="com --candidates: só estes ids (ex.: 1,3,5)")
    ap.add_argument("--pad", type=float, help="margem antes/depois de cada candidato (mín. max(pad_before, pad_after, pad_folga))")
    ap.add_argument("--detect-only", action="store_true", help="só detecta o idioma e grava lang.json")
    ap.add_argument("--no-batch", action="store_true", help="modo antigo (frase por frase), mais lento")
    a = ap.parse_args()

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        sys.exit("faster-whisper não instalado: pip install -r requirements.txt")

    t0 = time.time()
    out_dir = os.path.dirname(os.path.abspath(a.video))
    tpath = os.path.join(out_dir, "transcript.json")
    models = Models(cfg)
    audio = load_audio(a.video, out_dir)
    total = len(audio) / SR
    lang, detected = get_language(audio, out_dir, cfg, models, a.language)
    if detected:
        print(f"✓ Idioma detectado: {lang}" + ("" if lang == "pt" else
              "  (vídeo gringo: a legenda do short sai traduzida para português)"))
    if a.detect_only:
        return

    refine = bool(a.candidates or a.range)
    pcfg = cfg.get("transcribe_refine" if refine else "transcribe_fast", {})
    tcfg = cfg.get("transcribe", {})
    model_name = a.model or pcfg.get("model", "small" if refine else "tiny")
    beam = a.beam or pcfg.get("beam", 5 if refine else 1)
    batched = not a.no_batch and bool(tcfg.get("batched", True))
    batch_size = int(tcfg.get("batch_size", 8))
    min_pad = max(float(cfg.get("pad_before", 0)), float(cfg.get("pad_after", 0)), float(cfg.get("pad_folga", 10)))
    pad = max(a.pad if a.pad is not None else float(cfg.get("transcribe_refine", {}).get("pad_seconds", 10)), min_pad)

    ranges = []
    for r in a.range or []:
        s, e = (secs(x) for x in r.split("-"))
        ranges.append((max(0.0, s), min(total, e)))
    if a.candidates:
        keep = {int(x) for x in a.ids.split(",")} if a.ids else None
        with open(a.candidates, encoding="utf-8") as f:
            for i, c in enumerate(json.load(f), 1):
                if keep is None or int(c.get("id", i)) in keep:
                    ranges.append((max(0.0, secs(c["start"]) - pad), min(total, secs(c["end"]) + pad)))
    ranges = merge_ranges(ranges) if ranges else [[0.0, total]]

    model = models.get(model_name)
    segments, words, redo = [], [], 0
    for rs, re_ in ranges:
        seg, wds, n = run_pass(model, audio[int(rs * SR):int(re_ * SR)], lang, beam, batched, batch_size, rs,
                               collapse=not refine, ngram=int(pcfg.get("no_repeat_ngram", 0 if refine else 3)),
                               redo_loops=refine)
        segments += seg
        words += wds
        redo += n

    old = read_json(tpath) if refine else None
    refined = []
    if old:                                   # troca só os trechos dentro do transcript existente
        def outside(x):
            return all(x["e"] <= rs or x["s"] >= re_ for rs, re_ in ranges)
        words = [w for w in old["words"] if outside(w)] + words
        segments = [x for x in old["segments"] if outside(x)] + segments
        refined = old.get("refined") or []
    if not refine and model_name != "tiny":   # passada inteira já é small: tudo conta como refinado (check_cut)
        refined = [[0.0, round(total, 2)]]
    if refine:
        refined = merge_ranges([list(r) for r in refined] + [[round(rs, 2), round(re_, 2)] for rs, re_ in ranges])
    words.sort(key=lambda w: w["s"])
    segments.sort(key=lambda x: x["s"])
    write_json(tpath, {"language": lang, "duration": (old or {}).get("duration") or total, "segments": segments,
                       "words": words, "refined": refined}, indent=None)
    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[{ts(s['s'])}] {s['text']}\n")
    dt = time.time() - t0
    span = sum(re_ - rs for rs, re_ in ranges)
    print(f"✓ {model_name}: {span / 60:.1f} min de áudio em {dt:.0f} s — {len(words)} palavras, idioma {lang}"
          + (f", {redo} trecho(s) refeito(s) sem laço" if redo else "") + " → transcript.json")


if __name__ == "__main__":
    main()
