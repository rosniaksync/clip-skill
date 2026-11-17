#!/usr/bin/env python3
"""Confere tudo que a skill precisa e diz o comando exato para instalar o que faltar."""
import importlib.metadata as md
import importlib.util
import os
import platform
import shutil
import subprocess
import sys

from common import SKILL_DIR, cfg_path, load_config, twitch_cli_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

cfg = load_config()
sysname = platform.system()
fixes = []


def ok(msg):
    print(f"  ✓ {msg}")


def bad(msg, fix):
    print(f"  ✗ {msg}")
    fixes.append(fix)


print(f"Python {sys.version.split()[0]} em {sysname}")
if sys.version_info < (3, 9):
    bad("Python 3.9+ é necessário", "instale o Python 3.11+ (python.org ou winget install Python.Python.3.12)")

# ffmpeg / ffprobe
ff_fix = {"Windows": "winget install Gyan.FFmpeg   (depois reabra o terminal)",
          "Darwin": "brew install ffmpeg"}.get(sysname, "sudo apt install ffmpeg")
for tool in ("ffmpeg", "ffprobe"):
    ok(tool) if shutil.which(tool) else bad(f"{tool} não encontrado", ff_fix)

# pacotes Python
req = os.path.join(SKILL_DIR, "requirements.txt")
pip = f'python -m pip install -r "{req}"'
for mod, pkg in (("yt_dlp", "yt-dlp"), ("yt_dlp_ejs", "yt-dlp-ejs"), ("faster_whisper", "faster-whisper"),
                 ("av", "av"), ("numpy", "numpy"), ("PIL", "pillow")):
    if importlib.util.find_spec(mod):
        ok(pkg)
    else:
        bad(f"{pkg} não instalado", pip)
try:
    v = md.version("av")
    major = int(v.split(".")[0])
    if not 14 <= major < 17:
        bad(f"av {v} fora da faixa >=14,<17 (o faster-whisper quebra com metadata_errors)",
            'python -m pip install "av>=14,<17"')
except md.PackageNotFoundError:
    pass
try:
    pot_ver = md.version("bgutil-ytdlp-pot-provider")
    ok(f"bgutil-ytdlp-pot-provider {pot_ver}")
except md.PackageNotFoundError:
    pot_ver = None
    bad("bgutil-ytdlp-pot-provider (plugin do PO token) não instalado", pip)

# Node.js (runtime JS do yt-dlp e do gerador do PO token)
node = shutil.which("node")
if node:
    nv = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    ok(f"Node.js {nv}")
else:
    bad("Node.js não encontrado", {"Windows": "winget install OpenJS.NodeJS.LTS   (depois reabra o terminal)",
                                    "Darwin": "brew install node"}.get(sysname, "sudo apt install nodejs npm"))

# gerador do PO token (bgutil, modo script)
pot = cfg_path("pot_script", cfg)
if pot and os.path.isfile(pot):
    ok(f"gerador do PO token ({pot})")
else:
    server = os.path.dirname(os.path.dirname(pot)) if pot else "~/bgutil-ytdlp-pot-provider/server"
    root = os.path.dirname(server)
    tag = f" --branch {pot_ver}" if pot_ver else ""
    bad(f"gerador do PO token não encontrado em {pot} (config.json -> paths.pot_script)",
        f"git clone --single-branch{tag} https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \"{root}\"\n"
        f"      cd \"{server}\"  &&  npm ci  &&  npx tsc")

# TwitchDownloaderCLI (chat dos VODs da Twitch)
cli = twitch_cli_path(cfg)
if cli:
    ok(f"TwitchDownloaderCLI ({cli})")
else:
    bad("TwitchDownloaderCLI não encontrado (config.json -> paths.twitch_cli)",
        f'python "{os.path.join(SKILL_DIR, "scripts", "install_twitch_cli.py")}"')

# cookies (só aviso: só são usados quando o vídeo pede login)
ck = cfg_path("cookies_master", cfg)
if ck and os.path.isfile(ck):
    ok(f"cookies master ({ck})")
else:
    print(f"  ! cookies master não encontrado em {ck} (só faz falta em vídeo com login/idade; "
          f"veja {cfg_path('setup_guide', cfg)})")

if fixes:
    print("\nInstale o que falta:")
    seen = set()
    for f in fixes:
        if f not in seen:
            seen.add(f)
            print(f"  {f}")
    sys.exit(1)
print("\nTudo OK ✓ — pronto para cortar.")
