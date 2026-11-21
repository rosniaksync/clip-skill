#!/usr/bin/env python3
"""Baixa uma live/VOD e, na Twitch, o chat. Saída curta (andamento a cada 25% ou 30 s).

Uso:
  download.py URL --out work/<id> [--section 01:00:00-02:00:00] [--analysis] [--max-height 1080]
                  [--cookies ARQ] [--cookies-from-browser NAV] [--player-client web] [--no-chat] [--fresh]
  download.py URL --probe        # só olha (título, canal, duração, ao vivo, heatmap), não baixa

Gera em --out:
  source.mp4    vídeo (H.264/AAC preferidos, saída MP4)
  info.json     título, canal, duração, link, se está ao vivo, "analysis" (cópia leve)
  section.json  com --section (ou live): offset REAL medido do início do arquivo no vídeo original
  heatmap.json  YouTube: mapa de "mais repetidos" (tempos absolutos do vídeo original), quando existir
  chat.json     Twitch: chat do VOD (TwitchDownloaderCLI). YouTube não baixa chat.

Resolução: 1080p; sem 1080p, a logo ACIMA (1440, 2160), nunca abaixo; só desce se não houver nada >= 1080.
--analysis: cópia leve (download.analysis_height, 480p) só para analisar; o short sai do trecho em alta
(fetch_hd.py / make_shorts.py baixam sozinhos).

Rápido e com menos risco de bloqueio do YouTube ("confirme que não é um robô"):
  * A info do vídeo fica em cache (<work_root>/_cache, download.info_cache_minutes): o --probe extrai uma vez e o
    download, os outros blocos e os trechos em alta reaproveitam, sem pedir de novo ao YouTube (--fresh força).
  * YouTube (vídeo que não está ao vivo) + --analysis: baixa a cópia leve do vídeo INTEIRO pelo downloader nativo
    (~10 MB/s, uma vez por link, em <work_root>/_full) e recorta o bloco localmente (cópia de stream, instantâneo).
    O corte por --section direto do YouTube passa pelo ffmpeg e anda a ~2x o tempo real.
    Se o arquivo inteiro passar de download.analysis_full_max_mb ou o download ficar lento, volta ao --section.
  * Pausa entre pedidos ao YouTube (download.sleep_requests) e limite de velocidade (download.youtube_ratelimit_mb).

Lives ainda no ar:
  * Twitch, link de canal (twitch.tv/nome): se estiver ao vivo, usa o VOD da live atual; sem VOD, para.
  * YouTube ao vivo: baixa só o que já passou até agora (bloco fechado), nunca fica gravando.

Cookies só quando o vídeo pede login/idade/"não sou robô", e SEMPRE por cópia temporária do arquivo master
(paths.cookies_master; $YT_COOKIES_MASTER ou --cookies sobrescrevem). O yt-dlp reescreve o arquivo que recebe.
Saída 3 = YouTube bloqueou (precisa de cookies ou esperar).
"""
import argparse
import copy
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlparse

from common import (cfg_path, continue_from, history_path, history_summary, load_config, media_duration, read_json,
                    secs, ts, twitch_cli_path, utf8_stdout, video_key, work_root, write_json)

LOGIN_HINTS = ("sign in", "age-restricted", "confirm your age", "log in",
               "login", "private video", "members-only", "not a bot")
BOT_HINTS = ("not a bot", "confirm you’re not a bot", "confirm you're not a bot")
EXIT_BOT = 3
TWITCH_CHANNEL_RE = re.compile(r"^https?://(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)/?(?:\?.*)?$")
TWITCH_RESERVED = {"videos", "directory", "settings", "downloads", "p", "search", "subscriptions", "inventory"}
MB = 1024 * 1024


def is_youtube(url):
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def is_twitch(url):
    return "twitch.tv" in url


def needs_login(err):
    msg = str(err).lower()
    return any(h in msg for h in LOGIN_HINTS)


def is_bot_check(err):
    msg = str(err).lower()
    return any(h in msg for h in BOT_HINTS)


class SlowDownload(Exception):
    pass


class QuietLogger:
    """Logger do yt-dlp: some com as mensagens de rotina; avisos importantes saem uma vez, numa linha."""
    NOISE = ("Unable to download JSON metadata", "No title found in player responses", "falling back to",
             "Some formats may be missing", "nsig", "n challenge", "Retrying", "Falling back", "storyboard",
             "is not a valid URL", "Downloading", "[download]")

    def __init__(self, verbose=False):
        self.verbose, self.seen, self.last_error = verbose, set(), ""

    def debug(self, msg):
        if self.verbose:
            print(msg)

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        if self.verbose or (msg not in self.seen and not any(n in msg for n in self.NOISE)):
            print(f"(aviso: {msg.replace('WARNING: ', '')[:220]})")
        self.seen.add(msg)

    def error(self, msg):
        self.last_error = msg
        if self.verbose:
            print(msg)


class Progress:
    """progress_hook: uma linha a cada 25% (ou 30 s sem total) por arquivo; opcionalmente aborta se ficar lento."""
    def __init__(self, guard=None):
        self.state, self.guard, self.t0 = {}, guard, time.time()

    def __call__(self, d):
        fn = os.path.basename(d.get("filename") or d.get("tmpfilename") or "")
        st = self.state.setdefault(fn, {"next": 25, "last": time.time()})
        if d.get("status") == "downloading":
            done = d.get("downloaded_bytes") or 0
            tot = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = 100.0 * done / tot if tot else None
            now = time.time()
            if (pct is not None and pct >= st["next"] and pct < 100) or (pct is None and now - st["last"] >= 30):
                if pct is not None:
                    while st["next"] <= pct:
                        st["next"] += 25
                sp = d.get("speed")
                print(f"  {fn[-38:]}: " + (f"{pct:.0f}% de {tot / MB:.0f} MB" if pct is not None else f"{done / MB:.0f} MB")
                      + (f", {sp / MB:.1f} MB/s" if sp else ""), flush=True)
                st["last"] = now
            el = d.get("elapsed") or 0
            avg = (done - st.setdefault("start_bytes", done)) / el if el else 1e12   # média, não a velocidade do instante
            if self.guard and el > self.guard[0] and avg < self.guard[1]:
                raise SlowDownload(f"{avg / MB:.2f} MB/s em média")
        elif d.get("status") == "finished" and not st.get("done"):
            st["done"] = True
            size = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            el = d.get("elapsed") or (time.time() - self.t0)
            print(f"  ✓ {fn[-38:]}: {size / MB:.0f} MB em {el:.0f} s", flush=True)


def base_opts(cfg, url, cookie_copy=None, player_client=None, verbose=False):
    node = shutil.which("node")
    if not node:
        sys.exit("Node.js não encontrado no PATH (o yt-dlp usa como runtime JS). Rode scripts/check_setup.py.")
    ea = {}
    pot = cfg_path("pot_script", cfg)
    if pot and os.path.exists(pot):
        ea["youtubepot-bgutilscript"] = {"script_path": [pot]}
    elif is_youtube(url):
        print(f"(aviso: gerador do PO token não encontrado em {pot}; veja scripts/check_setup.py)")
    if player_client:
        ea["youtube"] = {"player_client": [player_client]}
    o = {"quiet": True, "noprogress": True, "noplaylist": True, "logger": QuietLogger(verbose),
         "js_runtimes": {"node": {"path": node}}, "extractor_args": ea,
         # pedaço que falha não é pulado em silêncio (antes: buraco no áudio sem aviso)
         "skip_unavailable_fragments": False, "fragment_retries": 20}
    if is_youtube(url):
        o["sleep_interval_requests"] = float(cfg.get("download", {}).get("sleep_requests", 1.0))
    if cookie_copy:
        o["cookiefile"] = cookie_copy
    return o


# ---------------------------------------------------------------- cache da info (menos pedidos ao YouTube)

def url_key(url):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})", url)
    if m and is_youtube(url):
        return "youtube_" + m.group(1)
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return "twitch_" + m.group(1)
    return "url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def cache_path(url, cfg):
    return os.path.join(work_root(cfg), "_cache", url_key(url) + ".info.json")


def info_copy(info):
    """cópia da info para o yt-dlp processar; live recém-acabada (post_live) tem gerador e não aceita deepcopy."""
    try:
        return copy.deepcopy(info)
    except TypeError:
        return {**info, "formats": [dict(f) for f in info.get("formats") or []]}


def live_like(info):
    return bool(info.get("is_live")) or info.get("live_status") in ("is_live", "is_upcoming", "post_live")


def url_expire(info):
    """menor 'expire' (epoch) das URLs dos formatos (YouTube); None se não houver."""
    exps = []
    for f in info.get("formats") or []:
        m = re.search(r"[?&/]expire[=/](\d{9,11})", f.get("url") or "")
        if m:
            exps.append(int(m.group(1)))
    return min(exps) if exps else None


def load_cached(url, cfg):
    d = read_json(cache_path(url, cfg))
    if not d or not d.get("info"):
        return None
    info = d["info"]
    max_age = float(cfg.get("download", {}).get("info_cache_minutes", 180)) * 60
    exp = url_expire(info)
    if time.time() - d.get("saved", 0) > max_age or live_like(info) or (exp and exp - time.time() < 1800):
        return None
    return info


def save_cached(urls, info, cfg):
    if live_like(info):
        return
    import yt_dlp
    data = {"saved": time.time(), "info": yt_dlp.YoutubeDL.sanitize_info(copy.deepcopy(info), True)}
    for u in {u for u in urls if u}:
        p = cache_path(u, cfg)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        write_json(p, data, indent=None)


# ---------------------------------------------------------------- Twitch: canal ao vivo -> VOD atual

def resolve_twitch_channel(url, yt_dlp, opts):
    """twitch.tv/nome -> link do VOD da live atual. Para (sys.exit) se offline ou sem VOD."""
    m = TWITCH_CHANNEL_RE.match(url)
    if not m or m.group(1).lower() in TWITCH_RESERVED:
        return url
    name = m.group(1)
    q = {**opts, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(q) as y:
            live = y.extract_info(f"https://www.twitch.tv/{name}", download=False, process=False)
    except yt_dlp.utils.DownloadError as e:
        sys.exit(f"O canal {name} não está ao vivo agora ({str(e).splitlines()[0][:120]}).\n"
                 "Mande o link de um VOD (twitch.tv/videos/...).")
    if not live or not live.get("is_live", True):
        sys.exit(f"O canal {name} não está ao vivo agora. Mande o link de um VOD (twitch.tv/videos/...).")
    with yt_dlp.YoutubeDL({**q, "extract_flat": "in_playlist", "playlistend": 3}) as y:
        lst = y.extract_info(f"https://www.twitch.tv/{name}/videos?filter=archives&sort=time", download=False)
    for ent in (lst or {}).get("entries") or []:
        vurl = ent.get("url") or ent.get("webpage_url")
        if not vurl:
            continue
        if not vurl.startswith("http"):
            vurl = f"https://www.twitch.tv/videos/{str(vurl).lstrip('v')}"
        with yt_dlp.YoutubeDL(q) as y:
            vi = y.extract_info(vurl, download=False, process=False)
        if vi.get("is_live"):
            print(f"→ {name} está ao vivo: usando o VOD da live atual {vurl}")
            return vurl
        break   # o mais recente não é da live atual
    sys.exit(f"O canal {name} está ao vivo, mas a live atual não tem VOD (o canal não salva VODs ou ainda não "
             "apareceu). Nada foi baixado: tente de novo depois que o VOD aparecer, ou mande outro link.")


# ---------------------------------------------------------------- offset real do trecho

def probe_starts(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=start_time:stream=codec_type,start_time",
                          "-of", "json", path], capture_output=True, text=True).stdout
    d = json.loads(out or "{}")
    fmt = float((d.get("format") or {}).get("start_time") or 0.0)
    a = [float(s.get("start_time") or 0.0) for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    v = [float(s.get("start_time") or 0.0) for s in d.get("streams", []) if s.get("codec_type") == "video"]
    return fmt, (a[0] if a else None), (v[0] if v else None)


def measure_and_fix(path, audio_abs_start):
    """O corte por cópia de stream começa o VÍDEO no keyframe anterior; o ÁUDIO começa no ponto pedido.
    Mede quanto o áudio começa depois do início do arquivo (lead) -> offset real = início pedido - lead.
    Se houver lead, recodifica só o áudio com silêncio no começo, para que o tempo 0 do arquivo seja o mesmo
    para vídeo, áudio, transcrição e render. Retorna (offset_real, lead)."""
    fmt, a, v = probe_starts(path)
    if a is None:
        return audio_abs_start, 0.0
    lead = max(0.0, a - fmt)
    if lead > 30:   # não faz sentido: mantém o pedido e avisa
        print(f"(aviso: início do áudio estranho ({lead:.2f}s); mantendo o offset pedido)")
        return audio_abs_start, 0.0
    if lead > 0.05:
        tmp = path + ".fix.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0",
                        "-c:v", "copy", "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", tmp], check=True)
        os.replace(tmp, path)
    return audio_abs_start - lead, lead


def keyframe_at_or_before(path, t):
    """Tempo do keyframe de vídeo <= t (arquivo local), ou None."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                          "-show_entries", "frame=pts_time", "-of", "csv=p=0",
                          "-read_intervals", f"{max(0.0, t - 20):.3f}%{t + 0.05:.3f}", path],
                         capture_output=True, text=True).stdout
    kfs = []
    for x in out.split():
        try:
            kfs.append(float(x.strip(",")))
        except ValueError:
            pass
    ok = [k for k in kfs if k <= t + 1e-3]
    return max(ok) if ok else None


def cut_local(full, out_mp4, start, end):
    """Recorta [start, end] (tempo do arquivo inteiro) por cópia de stream, começando no keyframe <= start.
    Retorna (offset_real, lead): o tempo 0 do recorte = offset_real no vídeo original."""
    k = keyframe_at_or_before(full, start) if start > 0 else 0.0
    s0 = k if k is not None else start
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
    if s0 > 0:
        cmd += ["-ss", f"{s0 + 0.001:.3f}"]
    cmd += ["-i", full]
    if end:
        cmd += ["-t", f"{end - s0:.3f}"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True)
    return measure_and_fix(out_mp4, s0)


# ---------------------------------------------------------------- chat da Twitch

def twitch_chat(url, out, rng, offset, cfg):
    """Chat do VOD -> chat.json {"source":"twitch","messages":[{"t":seg_absoluto,"text":...}]}.
    Os tempos ficam absolutos no VOD; find_hype.py subtrai o offset real do section.json."""
    m = re.search(r"/videos/(\d+)", url)
    cli = twitch_cli_path(cfg)
    if not m or not cli:
        print("(sem chat: id do VOD ou TwitchDownloaderCLI não encontrado; instale com scripts/install_twitch_cli.py)")
        return
    raw = os.path.join(out, "chat_raw.json")
    cmd = [cli, "chatdownload", "-u", m.group(1), "--bttv", "false", "--ffz", "false",
           "--stv", "false", "--banner", "false", "--log-level", "Error", "-o", raw]
    if rng:
        margin = float(cfg.get("download", {}).get("chat_margin_seconds", 30))
        b = max(0, int(min(rng[0], offset) - margin))
        cmd += ["-b", str(b), "-e", str(int(rng[1] + margin))]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(raw, encoding="utf-8") as f:
            data = json.load(f)
        msgs = [{"t": c["content_offset_seconds"], "text": c.get("message", {}).get("body", "")}
                for c in data.get("comments", [])]
        write_json(os.path.join(out, "chat.json"), {"source": "twitch", "messages": msgs}, indent=None)
        print(f"✓ Chat da Twitch: {len(msgs)} mensagens (chat.json)")
    except Exception as e:  # chat é só sinal de apoio
        print(f"(sem chat: {e.__class__.__name__})")
    finally:
        if os.path.exists(raw):
            os.remove(raw)


# ---------------------------------------------------------------- YouTube ao vivo: pedaços em paralelo

def _live_pick(formats, h):
    """Formatos 'do começo' da live (fragments gerado): vídeo na altura h (prefere H.264) e áudio m4a."""
    fr = [f for f in formats if callable(f.get("fragments"))]
    vids = [f for f in fr if f.get("vcodec") not in (None, "none") and f.get("height")]
    auds = [f for f in fr if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")]
    if not vids or not auds:
        return None, None
    hs = sorted({int(f["height"]) for f in vids})
    hh = min([x for x in hs if x >= h] or [hs[-1]]) if h else hs[-1]
    vv = [f for f in vids if int(f["height"]) == hh]
    vv.sort(key=lambda f: (str(f.get("vcodec", "")).startswith("avc1"), f.get("tbr") or 0), reverse=True)
    auds.sort(key=lambda f: (f.get("ext") == "m4a", f.get("abr") or 0), reverse=True)
    return vv[0], auds[0]


def live_fast(y, url, rng, h, out, mp4, cfg):
    """Live do YouTube no ar: em vez do 'live_from_start' do yt-dlp (1 pedaço por vez, ~1 s por pedido), pede
    os pedaços (sq) direto, `download.live_threads` (16) ao mesmo tempo, áudio e vídeo. Pedaço vazio/falho é
    pedido de novo; se continuar faltando, para com erro (nunca deixa buraco). -> (offset, lead)."""
    from concurrent.futures import ThreadPoolExecutor
    from yt_dlp.utils import update_url_query
    dcfg = cfg.get("download", {})
    threads = int(dcfg.get("live_threads", 16))
    tries = int(dcfg.get("live_fragment_retries", 6))
    def first_url(f):
        for frag in f["fragments"]({}):
            return frag
        return None

    linfo = vf = af = None
    bases = {}
    # cache curto (15 min) da lista de pedaços: vários cortes da mesma live seguidos (fetch_hd) não perguntam de novo
    cpath = os.path.join(work_root(cfg), "_cache", "live_" + re.sub(r"[^A-Za-z0-9_-]", "_", url)[-60:] + f"_{h}.json")
    cached = read_json(cpath)
    if cached and time.time() - cached.get("saved", 0) < 900:
        linfo, vf, af, bases = cached["linfo"], cached["vf"], cached["af"], cached["bases"]
    for attempt in range(0 if bases else 4):        # o gerador do YouTube às vezes volta vazio: pergunta de novo
        linfo = y.extract_info(url, download=False)
        vf, af = _live_pick(linfo.get("formats") or [], h)
        if not vf:
            raise RuntimeError("live sem formatos 'do começo' (fragments): não dá para baixar o que já passou")
        fa, fv = first_url(af), first_url(vf)
        if fa and fv:
            bases = {"a": fa, "v": fv}
            break
        print(f"  (YouTube não mandou a lista de pedaços; tentando de novo {attempt + 1}/3)", flush=True)
        time.sleep(3 * (attempt + 1))
    if not bases:
        raise RuntimeError("o YouTube não mandou a lista de pedaços da live (tente de novo em alguns minutos)")
    if not cached or cached.get("bases") != bases:
        keep = ("format_id", "height", "ext", "target_duration")
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        write_json(cpath, {"saved": time.time(), "linfo": {"release_timestamp": linfo.get("release_timestamp")},
                           "vf": {k: vf.get(k) for k in keep}, "af": {k: af.get(k) for k in keep},
                           "bases": {k: {"url": v.get("url"), "fragment_count": v.get("fragment_count")}
                                     for k, v in bases.items()}}, indent=None)
    fd = float(vf.get("target_duration") or af.get("target_duration") or 0)
    if not fd:
        cnt = bases["v"].get("fragment_count") or 0
        el = time.time() - float(linfo.get("release_timestamp") or time.time())
        fd = (el / cnt) if cnt and el > 0 else 5.0
    s_sq, e_sq = int(rng[0] // fd), int(math.ceil(rng[1] / fd))
    sqs = list(range(s_sq, e_sq))
    print(f"Live: {len(sqs)} pedaços de {fd:g} s ({ts(rng[0])}–{ts(rng[1])}), {threads} ao mesmo tempo, "
          f"vídeo {vf.get('format_id')} {vf.get('height')}p + áudio {af.get('format_id')}", flush=True)

    def get(base, sq):
        u = update_url_query(base, {"sq": str(sq)})
        last = None
        for k in range(tries):
            try:
                b = y.urlopen(u).read()
                if b:
                    return b
                last = "vazio"
            except Exception as e:      # 403/429/rede: espera um pouco e tenta de novo
                last = e.__class__.__name__ + ": " + str(e)[:80]
            time.sleep(0.5 * (k + 1) ** 2)
        raise RuntimeError(f"pedaço sq={sq} falhou {tries}x ({last})")

    t0 = time.time()
    parts = []
    for kind, f in (("áudio", af), ("vídeo", vf)):
        k1 = "v" if kind == "vídeo" else "a"
        base = bases[k1]["url"]
        path = os.path.join(out, f"live_{k1}.{f.get('ext') or 'mp4'}")
        n, step = 0, max(1, len(sqs) // 10)
        with open(path, "wb") as fh, ThreadPoolExecutor(threads) as ex:
            for b in ex.map(lambda q: get(base, q), sqs):
                fh.write(b)
                n += 1
                if n % step == 0:
                    print(f"  {kind}: {100 * n // len(sqs)}% ({ts(time.time() - t0)})", flush=True)
        parts.append(path)
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", parts[1], "-i", parts[0], "-map", "0:v:0",
                    "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", mp4], check=True)
    for p in parts:
        os.remove(p)
    print(f"✓ live baixada em {ts(time.time() - t0)}", flush=True)
    return measure_and_fix(mp4, s_sq * fd)


# ---------------------------------------------------------------- YouTube encerrado: trecho em pedaços paralelos

def _start_time(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def vod_fast(rinfo, rng, out, mp4, dcfg):
    """Vídeo do YouTube já encerrado + --section: o YouTube limita cada conexão (~1 MB/s), então o trecho é
    dividido em `vod_pieces` pedaços baixados ao mesmo tempo (vídeo e áudio separados, ffmpeg com -ss/-to na
    entrada). Cada pedaço de vídeo começa num keyframe k_i <= pedido; o pedaço anterior é aparado até k_i
    (sem sobra nem buraco) e o áudio é aparado no mesmo ponto. Retorna (offset_real, lead)."""
    from concurrent.futures import ThreadPoolExecutor
    fmts = rinfo.get("requested_formats") or []
    if len(fmts) != 2 or not all(f.get("url") for f in fmts):
        raise RuntimeError("formato sem vídeo e áudio separados")
    vf, af = (fmts[0], fmts[1]) if fmts[0].get("vcodec") not in (None, "none") else (fmts[1], fmts[0])
    s, e = rng
    n = max(1, int(dcfg.get("vod_pieces", 8)))
    cuts = [s + (e - s) * i / n for i in range(n)] + [e]
    tmp = os.path.join(out, "_vod")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    t0 = time.time()

    def hdr(f):
        return "".join(f"{k}: {v}\r\n" for k, v in (f.get("http_headers") or {}).items())

    def fetch(f, a0, a1, path):
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-headers", hdr(f)]
        if a0 > 0:
            cmd += ["-ss", f"{a0:.3f}"]
        cmd += ["-to", f"{a1:.3f}", "-copyts", "-i", f["url"], "-map", "0:0", "-c", "copy", path]
        for tent in range(3):
            if subprocess.run(cmd).returncode == 0 and os.path.exists(path):
                return path
            time.sleep(2 + tent * 3)
        raise RuntimeError(f"pedaço {os.path.basename(path)} falhou")

    def piece(job):
        kind, i = job
        f = vf if kind == "v" else af
        a0 = cuts[i] - (0 if kind == "v" else 10)          # áudio começa antes: é aparado no keyframe do vídeo
        a1 = cuts[i + 1] + (8 if i < n - 1 else 0) + (0 if kind == "v" else 5)
        return fetch(f, max(0.0, a0), a1, os.path.join(tmp, f"{kind}{i:02d}.mkv"))

    jobs = [(k, i) for i in range(n) for k in ("v", "a")]
    with ThreadPoolExecutor(int(dcfg.get("vod_threads", 2 * n))) as ex:
        list(ex.map(piece, jobs))
    print(f"  {n} pedaços baixados em {ts(time.time() - t0)}", flush=True)

    vpaths = [os.path.join(tmp, f"v{i:02d}.mkv") for i in range(n)]
    with ThreadPoolExecutor(n) as ex:
        ks = list(ex.map(_start_time, vpaths)) + [None]

    def trim(i):
        dst = os.path.join(tmp, f"v{i:02d}_c.mkv")
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", vpaths[i]]
        if ks[i + 1] is not None:
            cmd += ["-t", f"{ks[i + 1] - ks[i]:.3f}"]
        subprocess.run(cmd + ["-c", "copy", dst], check=True)
        return dst

    with ThreadPoolExecutor(n) as ex:
        vfiles = list(ex.map(trim, range(n)))
    lst = os.path.join(tmp, "v.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        fh.write("".join(f"file '{p.replace(os.sep, '/')}'\n" for p in vfiles))
    v_all = os.path.join(tmp, "v_all.mkv")
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", v_all], check=True)
    vdur = media_duration(v_all)
    ends = ks[1:n] + [ks[0] + vdur]

    def first_pts(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts_time",
                              "-read_intervals", "%+#1", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout.split()
        return float(out[0].strip(","))

    def atrim(i):
        # áudio decodificado e cortado na amostra exata [ks[i], ends[i]] (tempo absoluto do primeiro pacote)
        src = os.path.join(tmp, f"a{i:02d}.mkv")
        dst = os.path.join(tmp, f"a{i:02d}.wav")
        st = ks[i] - first_pts(src)
        if st < -0.05:
            raise RuntimeError(f"áudio a{i} começa depois do vídeo ({st:.2f}s)")
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", src, "-af",
                        f"atrim=start={max(0.0, st):.4f}:duration={ends[i] - ks[i]:.4f},asetpts=N/SR/TB",
                        "-c:a", "pcm_s16le", dst], check=True)
        return dst

    with ThreadPoolExecutor(n) as ex:
        afiles = list(ex.map(atrim, range(n)))
    alst = os.path.join(tmp, "a.txt")
    with open(alst, "w", encoding="utf-8") as fh:
        fh.write("".join(f"file '{p.replace(os.sep, '/')}'\n" for p in afiles))
    a_all = os.path.join(tmp, "a_all.m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", alst,
                    "-c:a", "aac", "-b:a", "160k", a_all], check=True)
    adur = media_duration(a_all)
    if abs(adur - vdur) > 1.5 or abs(vdur - (e - ks[0])) > 3:
        raise RuntimeError(f"duração não bate (vídeo {vdur:.1f}s, áudio {adur:.1f}s, pedido {e - ks[0]:.1f}s)")
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", v_all, "-i", a_all, "-map", "0:v:0",
                    "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", mp4], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"✓ trecho baixado em {ts(time.time() - t0)} ({n} pedaços em paralelo)", flush=True)
    return measure_and_fix(mp4, ks[0])


# ---------------------------------------------------------------- YouTube ao vivo: só o que já passou

def limit_live_fragments(info, start, end, elapsed, state):
    """Formatos 'live from start' do YouTube são gerados fragmento a fragmento (sq 0 = início da live).
    Embrulha o gerador para baixar só sq em [start, end] e parar: nunca fica gravando."""
    def wrap(gen_fn):
        def gen(ctx):
            first = last = None
            for frag in gen_fn(ctx):
                sq = int(parse_qs(urlparse(frag["url"]).query).get("sq", ["0"])[0])
                if first is None:
                    count = frag.get("fragment_count") or 0
                    fd = float(state.get("fd") or (elapsed / count if count else 0) or 5.0)
                    state["fd"] = fd
                    first, last = int(start // fd), int(math.ceil(end / fd))
                    state.setdefault("first_sq", first)
                if sq < first:
                    continue
                if sq >= last:
                    return
                yield frag
        return gen
    for f in info.get("formats") or []:
        if callable(f.get("fragments")):
            f["fragments"] = wrap(f["fragments"])


def heights(info):
    return sorted({int(f["height"]) for f in info.get("formats") or []
                   if f.get("height") and f.get("vcodec") not in (None, "none")})


def pick_analysis_height(info, target):
    """Cópia só para analisar (ler, ver frames, escolher cortes): a maior altura <= target (480);
    se não houver, a menor que existir. O short final sai do trecho em alta (fetch_hd.py)."""
    hs = heights(info)
    if not hs:
        return target
    low = [x for x in hs if x <= target]
    return low[-1] if low else hs[0]


def pick_height(info, target):
    """Altura a baixar: `target` (1080) se existir; senão a menor ACIMA dele; só se não houver nada
    >= target, a maior disponível. Nunca troca 1080 indisponível por 720 quando há 1440/2160."""
    hs = heights(info)
    if not hs:
        return target
    best = int(load_config().get("download", {}).get("best_height", 0) or 0)
    if best and any(target <= x <= best for x in hs):   # qualidade melhor: a MAIOR entre 1080 e best_height
        pick = max(x for x in hs if target <= x <= best)
        if pick != target:
            print(f"Resoluções: {', '.join(f'{x}p' for x in hs)} → {pick}p (a melhor disponível)")
        return pick
    if target in hs:
        pick = target
    else:
        above = [x for x in hs if x > target]
        pick = above[0] if above else hs[-1]
    if pick != target:
        print(f"Resoluções: {', '.join(f'{x}p' for x in hs)} → {pick}p (sem {target}p)"
              + ("  ⚠ FONTE MENOR QUE 1080p" if pick < target else ""))
    return pick


def selected_size(yt_dlp, opts, info):
    """Tamanho (bytes) dos formatos que o seletor escolheria; None se não souber."""
    try:
        with yt_dlp.YoutubeDL({**opts, "skip_download": True}) as y:
            r = y.process_ie_result(info_copy(info), download=False)
        fs = r.get("requested_formats") or [r]
        sizes = [f.get("filesize") or f.get("filesize_approx") for f in fs]
        return sum(sizes) if all(sizes) else None
    except Exception:
        return None


# ---------------------------------------------------------------- main

def main():
    utf8_stdout()
    cfg = load_config()
    dcfg = cfg.get("download", {})
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out")
    ap.add_argument("--section", help="início-fim, ex.: 00:30:00-01:45:00 (tempo do vídeo original)")
    ap.add_argument("--cookies", help="arquivo master de cookies (sempre usado por cópia)")
    ap.add_argument("--cookies-from-browser", help="lê os cookies direto do navegador (ex.: firefox)")
    ap.add_argument("--player-client", help="player_client do YouTube (opcional), ex.: web ou tv")
    ap.add_argument("--max-height", type=int, default=dcfg.get("max_height", 1080))
    ap.add_argument("--no-chat", action="store_true")
    ap.add_argument("--analysis", action="store_true",
                    help="cópia leve (download.analysis_height, 480p) só para analisar; depois fetch_hd.py baixa os cortes em alta")
    ap.add_argument("--full-file", action="store_true", help="(teste) força o modo arquivo inteiro + recorte local")
    ap.add_argument("--no-full-file", action="store_true", help="nunca baixa o arquivo inteiro (usa --section direto)")
    ap.add_argument("--fresh", action="store_true", help="ignora a info em cache e pergunta de novo ao site")
    ap.add_argument("--probe", action="store_true", help="só mostra as informações, não baixa")
    ap.add_argument("--verbose", action="store_true", help="mostra tudo do yt-dlp")
    a = ap.parse_args()
    if not a.probe and not a.out:
        ap.error("--out é obrigatório (exceto com --probe)")

    try:
        import yt_dlp
    except ImportError:
        sys.exit("yt-dlp não instalado: pip install -r requirements.txt")

    master = a.cookies or cfg_path("cookies_master", cfg)
    guide = cfg_path("setup_guide", cfg) or "COMO-USAR.md"
    tmpdir = tempfile.mkdtemp(prefix="ytck_")
    cookie_copy = None

    def blocked(e):
        print("✗ O YouTube bloqueou os downloads deste PC por enquanto (pede \"confirme que você não é um robô\").")
        if master and os.path.isfile(master):
            print(f"  Os cookies de {master} não bastaram (expiraram?): exporte de novo (passo a passo em {guide}).")
        else:
            print(f"  Para continuar agora: exporte os cookies do YouTube (passo a passo em {guide}) para {master}.")
        print("  Sem cookies, o bloqueio costuma sair sozinho depois de algumas horas. Twitch não é afetada.")
        sys.exit(EXIT_BOT)

    def use_cookies(e):
        if not master or not os.path.isfile(master):
            if is_bot_check(e):
                blocked(e)
            sys.exit(f"Este vídeo pede login e o arquivo de cookies não existe: {master}\n"
                     f"Veja {guide} para exportar de novo.")
        print(f"→ O vídeo pede login: usando uma CÓPIA de {master}")
        dst = os.path.join(tmpdir, "cookies.txt")
        shutil.copyfile(master, dst)
        return dst

    def opts(extra=None):
        o = base_opts(cfg, a.url, cookie_copy, a.player_client, a.verbose)
        if a.cookies_from_browser:
            o["cookiesfrombrowser"] = (a.cookies_from_browser,)
        o.update(extra or {})
        return o

    def run_with_login(fn):
        """roda fn(); se o site pedir login/robô, tenta de novo com a cópia dos cookies."""
        nonlocal cookie_copy
        try:
            return fn()
        except yt_dlp.utils.DownloadError as e:
            if not needs_login(e) or cookie_copy:
                if is_bot_check(e):
                    blocked(e)
                raise
            cookie_copy = use_cookies(e)
            try:
                return fn()
            except yt_dlp.utils.DownloadError as e2:
                if is_bot_check(e2):
                    blocked(e2)
                raise

    try:
        url = resolve_twitch_channel(a.url, yt_dlp, opts()) if is_twitch(a.url) else a.url

        def fresh_info():
            with yt_dlp.YoutubeDL({**opts(), "skip_download": True}) as y:
                return y.extract_info(url, download=False)

        info = None if (a.fresh or a.probe) else load_cached(url, cfg)
        from_cache = info is not None
        if info is None:
            info = run_with_login(fresh_info)
            save_cached([url, info.get("webpage_url")], info, cfg)
            info = yt_dlp.YoutubeDL.sanitize_info(copy.deepcopy(info), True) if not live_like(info) else info

        is_live = bool(info.get("is_live"))
        heat = info.get("heatmap") or []
        if a.probe:
            print(json.dumps({"url": url, "title": info.get("title"), "uploader": info.get("uploader"),
                              "duration": info.get("duration"), "duration_string": info.get("duration_string"),
                              "is_live": is_live, "live_status": info.get("live_status"),
                              "no_ar_ha": ts(time.time() - float(info["release_timestamp"])) if is_live and info.get("release_timestamp") else None,
                              "heatmap_points": len(heat), "extractor": info.get("extractor_key"), "id": info.get("id"),
                              "max_height": (heights(info) or [None])[-1]},
                             ensure_ascii=False))
            chaps = info.get("chapters") or []
            if chaps:   # Twitch VOD: um capítulo por categoria/jogo (mostra quando ele abriu o jogo)
                print("Capítulos: " + " | ".join(f"{ts(c.get('start_time') or 0)}–{ts(c.get('end_time') or 0)} "
                                                 f"{c.get('title')}" for c in chaps))
            hist = read_json(history_path(info.get("extractor_key"), info.get("id"), cfg))
            if hist and hist.get("blocks"):
                spans, covered, n = history_summary(hist)
                print(f"Histórico: já cortado {', '.join(f'{ts(s)}–{ts(e)}' for s, e in spans)} ({n} shorts). "
                      f"Continuar de {ts(continue_from(covered, cfg))}.")
            else:
                print("Histórico: vídeo novo, nada cortado ainda.")
            return

        os.makedirs(a.out, exist_ok=True)
        for old in glob.glob(os.path.join(a.out, "source.*")):     # pasta reaproveitada: nada de arquivo velho
            if not old.endswith(".part"):
                os.remove(old)
        keep = {k: info.get(k) for k in ("id", "title", "uploader", "channel", "channel_url", "uploader_url",
                                          "duration", "webpage_url", "extractor_key", "upload_date",
                                          "live_status", "release_timestamp")}
        keep["is_live"] = is_live
        keep["webpage_url"] = keep["webpage_url"] or url
        keep["analysis"] = bool(a.analysis)
        write_json(os.path.join(a.out, "info.json"), keep)
        print(f"{keep['title']}  |  {ts(keep.get('duration') or 0)}" + ("  (info do cache)" if from_cache else ""))

        # --- trecho: pedido pelo usuário e, se a live ainda está no ar, fechado no que já passou
        rng = None
        if a.section:
            s_, e_ = a.section.split("-")
            rng = [secs(s_), secs(e_)]
        elapsed = None
        if is_live:
            if info.get("release_timestamp"):
                elapsed = time.time() - float(info["release_timestamp"])
            elif info.get("duration"):
                elapsed = float(info["duration"])
            if not elapsed:
                sys.exit("A live ainda está no ar e não deu para saber quanto já passou. Rode de novo com "
                         "--section início-fim (um trecho que já aconteceu).")
            elapsed -= 30   # margem: os últimos segundos ainda podem não estar disponíveis
            rng = [rng[0] if rng else 0.0, min(rng[1], elapsed) if rng else elapsed]
            if rng[1] <= rng[0]:
                sys.exit(f"A live está no ar há {ts(elapsed)}; o trecho pedido ainda não aconteceu.")
            print(f"⚠ A live ainda está rolando (no ar há ~{ts(elapsed)}). Baixando só o que já passou: "
                  f"{ts(rng[0])}–{ts(rng[1])}. Para o resto, rode de novo depois.")
        if rng:
            write_json(os.path.join(a.out, "section.json"),
                       {"offset": rng[0], "requested": [rng[0], rng[1]], "measured": False})

        # --- heatmap do YouTube (tempos absolutos do vídeo original)
        if heat:
            write_json(os.path.join(a.out, "heatmap.json"),
                       {"source": "youtube", "video_id": info.get("id"),
                        "points": [{"start": p.get("start_time"), "end": p.get("end_time"), "value": p.get("value")}
                                   for p in heat]}, indent=None)

        # --- formato
        if a.analysis:
            h = pick_analysis_height(info, int(dcfg.get("analysis_height", 480)))
            fmt = f"bv*[height={h}]+ba/b[height={h}]/bv*[height<={h}]+ba/b[height<={h}]/wv*+ba/w"
        else:
            h = pick_height(info, a.max_height)
            fmt = f"bv*[height={h}]+ba/b[height={h}]/bv*[height>={h}]+ba/b[height>={h}]/bv*+ba/b"
        yt_live = is_live and is_youtube(url)
        fmt_opts = {"format": fmt, "format_sort": [f"res:{h}", "fps", "vcodec:h264", "acodec:aac"],
                    "merge_output_format": "mp4"}
        mp4 = os.path.join(a.out, "source.mp4")
        offset, lead, done = (rng[0] if rng else 0.0), 0.0, False

        # --- YouTube (não ao vivo) em modo análise: arquivo inteiro leve pelo downloader nativo + recorte local
        want_full = (a.full_file or (a.analysis and is_youtube(url) and dcfg.get("analysis_full_file", True))) \
            and not is_live and not a.no_full_file          # post_live entra: o recorte por trecho só pega 5 s
        if want_full:
            full = os.path.join(work_root(cfg), "_full", f"{video_key(info.get('extractor_key'), info.get('id'))}_{h}p.mp4")
            need_end = min(rng[1], float(info.get("duration") or rng[1])) if rng else float(info.get("duration") or 0)
            have = media_duration(full) if os.path.exists(full) else 0.0
            if have and have >= need_end - 2:
                print(f"→ Cópia leve inteira já baixada ({os.path.basename(full)}): só recortando")
            else:
                size = selected_size(yt_dlp, opts(fmt_opts), info)
                max_mb = float(dcfg.get("analysis_full_max_mb", 8000))
                if size and size / MB > max_mb:
                    print(f"(arquivo inteiro teria {size / MB:.0f} MB > {max_mb:.0f} MB: baixando só o trecho)")
                    want_full = False
                else:
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    rl = float(dcfg.get("youtube_ratelimit_mb", 10) or 0)
                    guard = (float(dcfg.get("full_guard_seconds", 45)), float(dcfg.get("full_min_speed_mb", 1.5)) * MB)
                    print(f"Baixando a cópia leve inteira ({h}p" + (f", ~{size / MB:.0f} MB" if size else "")
                          + ") pelo downloader nativo; depois recorto o bloco")
                    def go_full():
                        dl = opts({**fmt_opts, "outtmpl": full[:-4] + ".%(ext)s", "progress_hooks": [Progress(guard)],
                                   "ratelimit": rl * MB if rl and is_youtube(url) else None,
                                   "concurrent_fragment_downloads": dcfg.get("concurrent_fragments", 8)})
                        with yt_dlp.YoutubeDL(dl) as y:
                            y.process_ie_result(info_copy(info), download=True)
                    try:
                        run_with_login(go_full)
                    except SlowDownload as e:
                        print(f"(download do arquivo inteiro lento ({e}): baixando só o trecho)")
                        want_full = False
                    got = [p for p in glob.glob(full[:-4] + ".*") if not p.endswith((".part", ".ytdl", ".json"))]
                    if want_full and got and got[0] != full:
                        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", got[0], "-c", "copy", full],
                                       check=True)
                        os.remove(got[0])
                    if want_full and not os.path.exists(full):
                        print("(arquivo inteiro não apareceu: baixando só o trecho)")
                        want_full = False
            if want_full:
                if rng:
                    offset, lead = cut_local(full, mp4, rng[0], rng[1])
                else:
                    try:
                        os.link(full, mp4)
                    except OSError:
                        shutil.copyfile(full, mp4)
                done = True

        # --- live do YouTube no ar: pedaços pedidos direto, em paralelo (live_fast)
        if yt_live and rng and not done and dcfg.get("live_fast", True):
            def go_fast():
                with yt_dlp.YoutubeDL(opts({"live_from_start": True})) as y:
                    return live_fast(y, url, rng, h, a.out, mp4, cfg)
            try:
                offset, lead = run_with_login(go_fast)
                done = True
            except Exception as e:      # plano B: o download normal do yt-dlp (mais lento, mas baixa)
                print(f"  Download rápido falhou ({e}); usando o download normal (mais lento).", flush=True)
                for f in os.listdir(a.out):
                    if f.startswith(("live_a", "live_v")) or f == os.path.basename(mp4):
                        try:
                            os.remove(os.path.join(a.out, f))
                        except OSError:
                            pass

        # --- YouTube já encerrado + trecho: pedaços em paralelo (vod_fast)
        if rng and not done and not is_live and is_youtube(url) and dcfg.get("vod_fast", True):
            def go_vod():
                with yt_dlp.YoutubeDL(opts(fmt_opts)) as y:
                    rinfo = y.process_ie_result(info_copy(info), download=False)
                return vod_fast(rinfo, rng, a.out, mp4, dcfg)
            try:
                offset, lead = run_with_login(go_vod)
                done = True
            except Exception as e:      # plano B: download normal do yt-dlp (uma conexão, mais lento)
                print(f"  Download em pedaços falhou ({e}); usando o download normal (mais lento).", flush=True)
                shutil.rmtree(os.path.join(a.out, "_vod"), ignore_errors=True)
                if os.path.exists(mp4):
                    os.remove(mp4)

        # --- download normal (trecho por --section, vídeo inteiro, ou live do YouTube)
        if not done:
            live_state = {}

            def go():
                dl = opts({**fmt_opts, "outtmpl": os.path.join(a.out, "source.%(ext)s"), "progress_hooks": [Progress()],
                           "live_from_start": yt_live,     # só para live do YouTube no ar
                           "concurrent_fragment_downloads": dcfg.get("concurrent_fragments", 8)})
                if rng and not yt_live:
                    from yt_dlp.utils import download_range_func
                    dl["download_ranges"] = download_range_func(None, [(rng[0], rng[1])])
                    dl["force_keyframes_at_cuts"] = False   # corte por cópia de stream (rápido); offset medido depois
                with yt_dlp.YoutubeDL(dl) as y:
                    if yt_live:
                        linfo = y.extract_info(url, download=False)
                        limit_live_fragments(linfo, rng[0], rng[1], elapsed + 30, live_state)
                        y.process_ie_result(linfo, download=True)
                    else:
                        y.process_ie_result(info_copy(info), download=True)
            try:
                run_with_login(go)
            except yt_dlp.utils.DownloadError:
                if not from_cache:
                    raise
                print("(info do cache não serviu: perguntando de novo ao site)")
                fi = run_with_login(fresh_info)
                save_cached([url, fi.get("webpage_url")], fi, cfg)
                info = yt_dlp.YoutubeDL.sanitize_info(copy.deepcopy(fi), True)
                run_with_login(go)

            src = [p for p in glob.glob(os.path.join(a.out, "source.*"))
                   if not p.endswith((".part", ".json", ".ytdl"))]
            if not src:
                sys.exit("Download falhou: nenhum arquivo source.")
            if src[0] != mp4:
                subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", src[0], "-c", "copy", mp4], check=True)
                os.remove(src[0])
            # --- offset REAL (o arquivo começa no keyframe anterior ao pedido)
            if rng:
                audio_start = rng[0]
                if yt_live and live_state.get("fd"):
                    audio_start = live_state["first_sq"] * live_state["fd"]
                offset, lead = measure_and_fix(mp4, audio_start)

        if rng:
            write_json(os.path.join(a.out, "section.json"),
                       {"offset": round(offset, 3), "requested": [rng[0], rng[1]], "measured": True,
                        "keyframe_lead": round(lead, 3), "live": is_live})
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,codec_name", "-of", "csv=p=0", mp4],
                           capture_output=True, text=True)
        dur = media_duration(mp4)
        print(f"✓ {mp4}  ({r.stdout.strip().replace(',', ' ')}, {ts(dur)}"
              + (f", começa em {ts(offset)} do original" if rng else "") + ")")

        # --- chat: só Twitch (YouTube não baixa chat)
        if not a.no_chat and is_twitch(url) and dcfg.get("chat_twitch", True):
            twitch_chat(url, a.out, rng, offset, cfg)
        if heat:
            print(f"✓ Heatmap do YouTube: {len(heat)} pontos (heatmap.json)")
    except yt_dlp.utils.DownloadError as e:
        if is_bot_check(e):
            blocked(e)
        sys.exit(f"✗ Download falhou: {str(e).splitlines()[0][:300]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
