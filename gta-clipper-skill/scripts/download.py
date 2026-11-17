#!/usr/bin/env python3
"""Download a stream/VOD (+ live chat replay if available).

Usage: download.py URL --out work/<id> [--section 01:00:00-02:00:00]
                   [--max-height 1080] [--cookies PATH] [--player-client web]

YouTube setup (fixed, see C:\\cortes\\COMO-USAR.md):
  * Node is always used as the JS runtime (signature/n-challenge solving).
  * bgutil-ytdlp-pot-provider supplies PO tokens (script mode, no server needed).
  * Cookies are only used when the video asks for login/age verification, and
    ALWAYS from a temporary COPY of the master file (never the original, because
    yt-dlp rewrites the cookie file it is given). Master file defaults to
    C:\\cortes\\cookies-master.txt, override with --cookies or $YT_COOKIES_MASTER.
  * Best quality up to --max-height (default 1080).
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TWITCH_CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools",
                          "TwitchDownloaderCLI", "TwitchDownloaderCLI.exe")
DEFAULT_MASTER = r"C:\cortes\cookies-master.txt"
POT_SCRIPT = os.path.join(os.path.expanduser("~"), "bgutil-ytdlp-pot-provider",
                          "server", "build", "generate_once.js")
LOGIN_HINTS = ("sign in", "age-restricted", "confirm your age", "log in",
               "login", "private video", "members-only", "not a bot")


def to_sec(t):
    parts = [float(p) for p in t.split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def base_opts(cookie_copy=None, player_client=None):
    node = shutil.which("node")
    if not node:
        sys.exit("Node.js not found in PATH (needed as yt-dlp JS runtime).")
    ea = {}
    if os.path.exists(POT_SCRIPT):
        ea["youtubepot-bgutilscript"] = {"script_path": [POT_SCRIPT]}
    else:
        print(f"(aviso: PO-token script nao encontrado em {POT_SCRIPT})")
    if player_client:
        ea["youtube"] = {"player_client": [player_client]}
    o = {
        "quiet": False,
        "noprogress": False,
        "noplaylist": True,
        "js_runtimes": {"node": {"path": node}},
        "extractor_args": ea,
    }
    if cookie_copy:
        o["cookiefile"] = cookie_copy
    return o


def needs_login(err):
    msg = str(err).lower()
    return any(h in msg for h in LOGIN_HINTS)


def twitch_chat(a):
    """Twitch VOD chat via TwitchDownloaderCLI -> chat.json {"source":"twitch","messages":[{"t":sec,"text":...}]}.
    Times are absolute VOD seconds; find_hype.py subtracts the section offset."""
    m = re.search(r"/videos/(\d+)", a.url)
    if not m or not os.path.exists(TWITCH_CLI):
        print("(no chat replay: Twitch VOD id or TwitchDownloaderCLI not found)")
        return
    raw = os.path.join(a.out, "chat_raw.json")
    cmd = [TWITCH_CLI, "chatdownload", "-u", m.group(1), "--bttv", "false", "--ffz", "false",
           "--stv", "false", "--banner", "false", "--log-level", "Error", "-o", raw]
    if a.section:
        s, e = a.section.split("-")
        cmd += ["-b", str(int(to_sec(s))), "-e", str(int(to_sec(e)))]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        data = json.load(open(raw, encoding="utf-8"))
        msgs = [{"t": c["content_offset_seconds"], "text": c.get("message", {}).get("body", "")}
                for c in data.get("comments", [])]
        json.dump({"source": "twitch", "messages": msgs}, open(os.path.join(a.out, "chat.json"), "w",
                  encoding="utf-8"), ensure_ascii=False)
        print(f"✓ Twitch chat saved (chat.json, {len(msgs)} messages)")
    except Exception as e:  # chat is a bonus signal only
        print(f"(no chat replay: {e.__class__.__name__})")
    finally:
        if os.path.exists(raw):
            os.remove(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--section", help="start-end, e.g. 00:30:00-01:45:00")
    ap.add_argument("--cookies", help="master cookies.txt (a copy is used; default "
                                      "$YT_COOKIES_MASTER or " + DEFAULT_MASTER + ")")
    ap.add_argument("--cookies-from-browser")
    ap.add_argument("--player-client", help="optional youtube player_client, e.g. web or tv")
    ap.add_argument("--max-height", type=int, default=1080)
    ap.add_argument("--no-chat", action="store_true")
    a = ap.parse_args()

    try:
        import yt_dlp
    except ImportError:
        sys.exit("yt-dlp missing: pip install -r requirements.txt")

    os.makedirs(a.out, exist_ok=True)
    master = a.cookies or os.environ.get("YT_COOKIES_MASTER") or DEFAULT_MASTER
    tmpdir = tempfile.mkdtemp(prefix="ytck_")
    cookie_copy = None

    def use_cookies():
        """Return a fresh temp COPY of the master cookies (never the original)."""
        if not os.path.isfile(master):
            sys.exit(f"Este video pede login e o arquivo de cookies nao existe: {master}\n"
                     "Veja C:\\cortes\\COMO-USAR.md para exportar de novo.")
        dst = os.path.join(tmpdir, "cookies.txt")
        shutil.copyfile(master, dst)
        return dst

    def opts(extra=None):
        o = base_opts(cookie_copy, a.player_client)
        if a.cookies_from_browser:
            o["cookiesfrombrowser"] = (a.cookies_from_browser,)
        o.update(extra or {})
        return o

    try:
        # 1) metadata — try without cookies first, retry with a cookie COPY if login is needed
        def get_info():
            with yt_dlp.YoutubeDL({**opts(), "skip_download": True, "quiet": True}) as y:
                return y.extract_info(a.url, download=False)

        try:
            info = get_info()
        except yt_dlp.utils.DownloadError as e:
            if not needs_login(e) or cookie_copy:
                raise
            print("→ O video pede login: usando uma COPIA de", master)
            cookie_copy = use_cookies()
            info = get_info()

        if info.get("is_live"):
            print("⚠ Stream is LIVE right now — downloading from the start of the "
                  "available buffer. For best results run again after it ends.")
        keep = {k: info.get(k) for k in ("id", "title", "uploader", "channel", "duration",
                                          "webpage_url", "extractor", "upload_date")}
        json.dump(keep, open(os.path.join(a.out, "info.json"), "w"), indent=2, ensure_ascii=False)
        print(f"Title: {keep['title']}  |  Duration: {keep.get('duration')}s")

        # 2) video — best quality up to max-height (video+audio merged), mp4 out
        h = a.max_height
        dl = opts({
            "format": f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
            "format_sort": [f"res:{h}", "fps", "vcodec:h264", "acodec:aac"],
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(a.out, "source.%(ext)s"),
            "live_from_start": True,
            "concurrent_fragment_downloads": 8,
        })
        if a.section:
            s, e = a.section.split("-")
            from yt_dlp.utils import download_range_func
            dl["download_ranges"] = download_range_func(None, [(to_sec(s), to_sec(e))])
            dl["force_keyframes_at_cuts"] = False  # cut by stream copy, no re-encode (much faster)
            json.dump({"offset": to_sec(s)}, open(os.path.join(a.out, "section.json"), "w"))
        with yt_dlp.YoutubeDL(dl) as y:
            y.download([a.url])

        src = [p for p in glob.glob(os.path.join(a.out, "source.*"))
               if not p.endswith((".part", ".json"))]
        if not src:
            sys.exit("Download failed — no source file.")
        if not src[0].endswith(".mp4"):
            mp4 = os.path.join(a.out, "source.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src[0], "-c", "copy", mp4], check=True)
            os.remove(src[0])

        # report resolution
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height,codec_name",
                                "-of", "csv=p=0", os.path.join(a.out, "source.mp4")],
                               capture_output=True, text=True)
            print("Resolucao baixada (largura,altura,codec):", r.stdout.strip())
        except Exception:
            pass

        # 3) chat replay — optional bonus signal for find_hype.py
        if not a.no_chat:
            if "twitch.tv" in a.url:
                twitch_chat(a)
            else:
                try:
                    with yt_dlp.YoutubeDL({**opts(), "skip_download": True, "quiet": True,
                                           "writesubtitles": True, "subtitleslangs": ["live_chat"],
                                           "outtmpl": os.path.join(a.out, "chat")}) as y:
                        y.download([a.url])
                    found = glob.glob(os.path.join(a.out, "chat*.live_chat.json"))
                    if found:
                        shutil.move(found[0], os.path.join(a.out, "chat.json"))
                        print("✓ Live chat replay saved (chat.json)")
                except Exception as e:  # chat is a bonus signal only
                    print(f"(no chat replay: {e.__class__.__name__})")

        print(f"✓ Saved {os.path.join(a.out, 'source.mp4')}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
