#!/usr/bin/env python3
"""Downloads TwitchDownloaderCLI (chat of Twitch VODs) into tools/TwitchDownloaderCLI/.

Usage: install_twitch_cli.py
Needed only for Twitch links. The binary is not stored in git (about 90 MB).
"""
import io
import json
import os
import platform
import urllib.request
import zipfile

REPO = "lay295/TwitchDownloader"
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(SKILL, "tools", "TwitchDownloaderCLI")


def asset_hint():
    s, m = platform.system(), platform.machine().lower()
    arm = "arm" in m or "aarch" in m
    return {"Windows": "Windows-x64", "Darwin": "MacOSArm64" if arm else "MacOS-x64"}.get(
        s, "LinuxArm64" if arm else "Linux-x64")


def main():
    api = urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/releases/latest")
    rel = json.load(api)
    hint = asset_hint()
    asset = next(a for a in rel["assets"] if a["name"].startswith("TwitchDownloaderCLI") and hint + ".zip" in a["name"])
    print("Baixando", asset["name"], "...")
    data = urllib.request.urlopen(asset["browser_download_url"]).read()
    os.makedirs(DEST, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(data)).extractall(DEST)
    print("OK ->", DEST)


if __name__ == "__main__":
    main()
