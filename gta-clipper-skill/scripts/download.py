#!/usr/bin/env python3
"""Baixa uma live/VOD (até 1080p) e, na Twitch, o chat.

Uso:
  download.py URL --out work/<id> [--section 01:00:00-02:00:00] [--max-height 1080]
                  [--cookies ARQ] [--cookies-from-browser NAV] [--player-client web] [--no-chat]
  download.py URL --probe        # só olha (título, canal, duração, ao vivo, heatmap), não baixa

Gera em --out:
  source.mp4    vídeo (H.264/AAC preferidos, saída MP4)
  info.json     título, canal, duração, link, se está ao vivo
  section.json  com --section (ou live): offset REAL medido do início do arquivo no vídeo original
  heatmap.json  YouTube: mapa de "mais repetidos" (tempos absolutos do vídeo original), quando existir
  chat.json     Twitch: chat do VOD (TwitchDownloaderCLI). YouTube não baixa chat.

Lives ainda no ar:
  * Twitch, link de canal (twitch.tv/nome): se estiver ao vivo, usa o VOD da live atual; sem VOD, para.
  * YouTube ao vivo: baixa só o que já passou até agora (bloco fechado), nunca fica gravando.

YouTube (configuração fixa, ver paths.setup_guide no config.json):
  * Node é sempre o runtime JS; bgutil-ytdlp-pot-provider gera o PO token (paths.pot_script).
  * Cookies só quando o vídeo pede login/idade, e SEMPRE por cópia temporária do arquivo master
    (paths.cookies_master; $YT_COOKIES_MASTER ou --cookies sobrescrevem). O yt-dlp reescreve o arquivo que recebe.
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
import time
from urllib.parse import parse_qs, urlparse

from common import (cfg_path, continue_from, history_path, history_summary, load_config, read_json, secs, ts, twitch_cli_path,
                    write_json)

LOGIN_HINTS = ("sign in", "age-restricted", "confirm your age", "log in",
               "login", "private video", "members-only", "not a bot")
TWITCH_CHANNEL_RE = re.compile(r"^https?://(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)/?(?:\?.*)?$")
TWITCH_RESERVED = {"videos", "directory", "settings", "downloads", "p", "search", "subscriptions", "inventory"}


def is_youtube(url):
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def is_twitch(url):
    return "twitch.tv" in url


def needs_login(err):
    msg = str(err).lower()
    return any(h in msg for h in LOGIN_HINTS)


def base_opts(cfg, cookie_copy=None, player_client=None):
    node = shutil.which("node")
    if not node:
        sys.exit("Node.js não encontrado no PATH (o yt-dlp usa como runtime JS). Rode scripts/check_setup.py.")
    ea = {}
    pot = cfg_path("pot_script", cfg)
    if pot and os.path.exists(pot):
        ea["youtubepot-bgutilscript"] = {"script_path": [pot]}
    else:
        print(f"(aviso: gerador do PO token não encontrado em {pot}; veja scripts/check_setup.py)")
    if player_client:
        ea["youtube"] = {"player_client": [player_client]}
    o = {"quiet": False, "noprogress": False, "noplaylist": True,
         "js_runtimes": {"node": {"path": node}}, "extractor_args": ea}
    if cookie_copy:
        o["cookiefile"] = cookie_copy
    return o


# ---------------------------------------------------------------- Twitch: canal ao vivo -> VOD atual

def resolve_twitch_channel(url, yt_dlp, opts):
    """twitch.tv/nome -> link do VOD da live atual. Para (sys.exit) se offline ou sem VOD."""
    m = TWITCH_CHANNEL_RE.match(url)
    if not m or m.group(1).lower() in TWITCH_RESERVED:
        return url
    name = m.group(1)
    q = {**opts, "skip_download": True, "quiet": True}
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
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                        "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", tmp], check=True)
        os.replace(tmp, path)
    return audio_abs_start - lead, lead


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
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        with open(raw, encoding="utf-8") as f:
            data = json.load(f)
        msgs = [{"t": c["content_offset_seconds"], "text": c.get("message", {}).get("body", "")}
                for c in data.get("comments", [])]
        write_json(os.path.join(out, "chat.json"), {"source": "twitch", "messages": msgs}, indent=None)
        print(f"✓ Chat da Twitch salvo (chat.json, {len(msgs)} mensagens)")
    except Exception as e:  # chat é só sinal de apoio
        print(f"(sem chat: {e.__class__.__name__})")
    finally:
        if os.path.exists(raw):
            os.remove(raw)


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


# ---------------------------------------------------------------- main

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
    ap.add_argument("--probe", action="store_true", help="só mostra as informações, não baixa")
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

    def use_cookies():
        if not master or not os.path.isfile(master):
            sys.exit(f"Este vídeo pede login e o arquivo de cookies não existe: {master}\n"
                     f"Veja {guide} para exportar de novo.")
        dst = os.path.join(tmpdir, "cookies.txt")
        shutil.copyfile(master, dst)
        return dst

    def opts(extra=None):
        o = base_opts(cfg, cookie_copy, a.player_client)
        if a.cookies_from_browser:
            o["cookiesfrombrowser"] = (a.cookies_from_browser,)
        o.update(extra or {})
        return o

    try:
        url = resolve_twitch_channel(a.url, yt_dlp, opts()) if is_twitch(a.url) else a.url

        def get_info(extra=None):
            with yt_dlp.YoutubeDL({**opts(extra), "skip_download": True, "quiet": True}) as y:
                return y.extract_info(url, download=False)

        try:
            info = get_info()
        except yt_dlp.utils.DownloadError as e:
            if not needs_login(e):
                raise
            print(f"→ O vídeo pede login: usando uma CÓPIA de {master}")
            cookie_copy = use_cookies()
            info = get_info()

        is_live = bool(info.get("is_live"))
        heat = info.get("heatmap") or []
        if a.probe:
            print(json.dumps({"url": url, "title": info.get("title"), "uploader": info.get("uploader"),
                              "duration": info.get("duration"), "duration_string": info.get("duration_string"),
                              "is_live": is_live, "live_status": info.get("live_status"),
                              "heatmap_points": len(heat), "extractor": info.get("extractor_key"), "id": info.get("id")},
                             ensure_ascii=False, indent=1))
            chaps = info.get("chapters") or []
            if chaps:   # Twitch VOD: um capítulo por categoria/jogo (mostra quando ele abriu o jogo)
                print("Capítulos (categoria/jogo):")
                for c in chaps:
                    print(f"  {ts(c.get('start_time') or 0)}–{ts(c.get('end_time') or 0)}  {c.get('title')}")
            hist = read_json(history_path(info.get("extractor_key"), info.get("id"), cfg))
            if hist and hist.get("blocks"):
                spans, covered, n = history_summary(hist)
                print(f"Histórico: já cortado {', '.join(f'{ts(s)}–{ts(e)}' for s, e in spans)} ({n} shorts). "
                      f"Continuar de {ts(continue_from(covered, cfg))}.")
            else:
                print("Histórico: vídeo novo, nada cortado ainda.")
            return

        os.makedirs(a.out, exist_ok=True)
        keep = {k: info.get(k) for k in ("id", "title", "uploader", "channel", "channel_url", "uploader_url",
                                          "duration", "webpage_url", "extractor_key", "upload_date",
                                          "live_status", "release_timestamp")}
        keep["is_live"] = is_live
        keep["webpage_url"] = keep["webpage_url"] or url
        write_json(os.path.join(a.out, "info.json"), keep)
        print(f"Título: {keep['title']}  |  Duração: {keep.get('duration')}s")

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
            print(f"✓ Mapa de mais repetidos salvo (heatmap.json, {len(heat)} pontos)")

        # --- vídeo: melhor qualidade até max-height, saída mp4
        h = a.max_height
        yt_live = is_live and is_youtube(url)
        dl = opts({
            "format": f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
            "format_sort": [f"res:{h}", "fps", "vcodec:h264", "acodec:aac"],
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(a.out, "source.%(ext)s"),
            "live_from_start": yt_live,     # só para live do YouTube no ar
            "concurrent_fragment_downloads": dcfg.get("concurrent_fragments", 8),
        })
        live_state = {}
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
                y.download([url])

        src = [p for p in glob.glob(os.path.join(a.out, "source.*"))
               if not p.endswith((".part", ".json", ".ytdl"))]
        if not src:
            sys.exit("Download falhou: nenhum arquivo source.")
        mp4 = os.path.join(a.out, "source.mp4")
        if src[0] != mp4:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src[0], "-c", "copy", mp4], check=True)
            os.remove(src[0])

        # --- offset REAL (o arquivo começa no keyframe anterior ao pedido)
        offset = 0.0
        if rng:
            audio_start = rng[0]
            if yt_live and live_state.get("fd"):
                audio_start = live_state["first_sq"] * live_state["fd"]
            offset, lead = measure_and_fix(mp4, audio_start)
            write_json(os.path.join(a.out, "section.json"),
                       {"offset": round(offset, 3), "requested": [rng[0], rng[1]], "measured": True,
                        "keyframe_lead": round(lead, 3), "live": is_live})
            print(f"✓ Offset real do trecho: {offset:.2f}s (pedido {rng[0]:.2f}s, keyframe {lead:.2f}s antes)")

        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,codec_name", "-of", "csv=p=0", mp4],
                           capture_output=True, text=True)
        print("Resolução baixada (largura,altura,codec):", r.stdout.strip())

        # --- chat: só Twitch (YouTube não baixa chat)
        if not a.no_chat and is_twitch(url) and dcfg.get("chat_twitch", True):
            twitch_chat(url, a.out, rng, offset, cfg)

        print(f"✓ Salvo {mp4}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
