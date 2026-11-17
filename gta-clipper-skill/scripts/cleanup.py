#!/usr/bin/env python3
"""Limpeza do dia: apaga tudo da pasta de trabalho, menos o histórico de onde parou.

Roda sozinha quando o note liga (instale uma vez com scripts/install_cleanup.py).
Apaga em paths.work_root tudo o que não foi mexido nas últimas cleanup.idle_hours horas:
vídeos baixados, transcrições, frames, temporários e os shorts prontos. Mantém só cleanup.keep
(a pasta historico/, com até onde cada vídeo/live foi cortado). Nunca mexe no Notion.

Uso:
  cleanup.py              # limpa (respeitando as horas sem mexer)
  cleanup.py --dry-run    # só mostra o que apagaria
  cleanup.py --now        # apaga já, mesmo o que foi mexido agora (cuidado: trabalho em andamento)
"""
import argparse
import datetime
import glob
import os
import shutil
import sys
import tempfile
import time

from common import SKILL_DIR, cfg_path, load_config

TMP_PREFIXES = ("ytck_", "clipper_", "lang_")   # pastas temporárias criadas pelos scripts


def last_touch(path):
    """Momento da última mudança em qualquer coisa dentro de path."""
    t = os.path.getmtime(path)
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for n in dirs + files:
                try:
                    t = max(t, os.path.getmtime(os.path.join(root, n)))
                except OSError:
                    pass
    return t


def size_of(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for n in files:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return total


def safe_root(root):
    """Não deixa apagar a raiz do disco, a pasta do usuário ou a própria skill por engano."""
    r = os.path.normcase(os.path.abspath(root))
    bad = {os.path.normcase(os.path.abspath(p)) for p in
           (os.path.expanduser("~"), SKILL_DIR, os.path.dirname(SKILL_DIR), os.path.abspath(os.sep))}
    drive_root = len(r.rstrip("\\/")) <= 2   # "C:" ou "/"
    return r not in bad and not drive_root


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    cc = cfg.get("cleanup", {})
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", action="store_true")
    a = ap.parse_args()

    root = cfg_path("work_root", cfg)
    if not root or not os.path.isdir(root):
        return print(f"Nada para limpar: a pasta de trabalho não existe ({root}).")
    if not safe_root(root):
        sys.exit(f"Recusei limpar {root}: parece a raiz do disco, a pasta do usuário ou a skill. "
                 "Ajuste paths.work_root no config.json.")
    keep = set(cc.get("keep", ["historico"]))
    limit = 0 if a.now else float(cc.get("idle_hours", 3)) * 3600
    now = time.time()

    targets = [os.path.join(root, n) for n in os.listdir(root) if n not in keep]
    tmp = tempfile.gettempdir()
    targets += [p for p in glob.glob(os.path.join(tmp, "*")) if os.path.basename(p).startswith(TMP_PREFIXES)]

    removed, skipped, freed = [], [], 0
    for p in sorted(targets):
        try:
            if now - last_touch(p) < limit:
                skipped.append(p)
                continue
            sz = size_of(p)
            if not a.dry_run:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            removed.append(p)
            freed += sz
        except OSError as e:
            print(f"(não deu para apagar {p}: {e.__class__.__name__})")

    verb = "Apagaria" if a.dry_run else "Apagado"
    for p in removed:
        print(f"  {verb}: {p}")
    for p in skipped:
        print(f"  Mantido (mexido nas últimas {limit / 3600:g} h): {p}")
    msg = (f"{'[teste] ' if a.dry_run else ''}{len(removed)} item(ns), {freed / 1e9:.2f} GB liberados; "
           f"histórico mantido em {os.path.join(root, 'historico')}")
    print(("✓ " if removed else "Nada para apagar. ") + msg)
    if not a.dry_run:
        os.makedirs(os.path.join(root, "historico"), exist_ok=True)
        with open(os.path.join(root, "historico", "limpeza.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}  {msg}\n")


if __name__ == "__main__":
    main()
