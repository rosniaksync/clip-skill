#!/usr/bin/env python3
"""Organiza os shorts prontos numa pasta numerada por link.

    <shorts_root>/
        1/                      <- primeiro link que o usuário mandou (todos os blocos juntos)
            01_GANCHO DO SHORT.mp4
            02_OUTRO GANCHO.mp4
            lista-de-postagem.md
        2/                      <- segundo link
        _registro.json          <- qual link é qual número (não mexer)

Uso:
    python scripts/organize_shorts.py work/<id>-b1 [work/<id>-b2 ...] [--move] [--dry-run]

- O número é do LINK (vídeo/live), não do bloco: mandar o mesmo link de novo continua na mesma pasta.
- Copia por padrão (a limpeza do dia apaga `work/`); `--move` move em vez de copiar.
- Rodar de novo no mesmo bloco não duplica nada (o registro lembra o que já foi).
- `paths.shorts_root` no config.json (padrão: C:\\cortes\\shorts).
"""
import argparse
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import cfg_path, load_config, read_json, video_key, write_json   # noqa: E402

DEFAULT_ROOT = r"C:\cortes\shorts"


def safe_name(text, limit=60):
    t = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE)     # tira emoji, :, /, ? etc.
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:limit].strip() or "short")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdirs", nargs="+", help="pastas work/<id>[-bN] com shorts/renders.json")
    ap.add_argument("--move", action="store_true", help="move em vez de copiar")
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que faria")
    a = ap.parse_args()

    cfg = load_config()
    root = cfg_path("shorts_root", cfg) or DEFAULT_ROOT
    reg_path = os.path.join(root, "_registro.json")
    reg = read_json(reg_path, {}) or {}
    reg.setdefault("proximo", 1)
    reg.setdefault("links", {})
    reg.setdefault("arquivos", {})
    counters = {}

    for wd in a.workdirs:
        info = read_json(os.path.join(wd, "info.json"), {}) or {}
        renders = read_json(os.path.join(wd, "shorts", "renders.json"), None)
        if not info or not renders:
            print(f"✗ {wd}: sem info.json ou shorts/renders.json, pulando")
            continue
        key = video_key(info.get("extractor_key"), info.get("id"))
        if key not in reg["links"]:
            reg["links"][key] = reg["proximo"]
            reg["proximo"] += 1
        n = reg["links"][key]
        dest_dir = os.path.join(root, str(n))
        print(f"Link #{n}: {info.get('uploader') or ''} — {info.get('title', '')[:60]}  ({key})")

        if n not in counters:
            existing = [f for f in (os.listdir(dest_dir) if os.path.isdir(dest_dir) else []) if f.lower().endswith(".mp4")]
            counters[n] = len(existing)
        seq = counters[n]
        lista = []
        for cid in sorted(renders, key=lambda x: int(x)):
            r = renders[cid]
            src = r.get("file")
            if not src or not os.path.isfile(src):
                print(f"  - corte {cid}: arquivo não existe mais, pulando")
                continue
            src_abs = os.path.abspath(src)
            if src_abs in reg["arquivos"]:
                print(f"  = {os.path.basename(src)}: já organizado como {reg['arquivos'][src_abs]}")
                continue
            seq += 1
            hook = r.get("hook_text") or " ".join(x for x in (r.get("hook", ""), r.get("subhook", "")) if x)
            name = f"{seq:02d}_{safe_name(hook)}.mp4"
            dst = os.path.join(dest_dir, name)
            print(f"  + {os.path.basename(src)} -> {n}\\{name}")
            if not a.dry_run:
                os.makedirs(dest_dir, exist_ok=True)
                (shutil.move if a.move else shutil.copy2)(src, dst)
                reg["arquivos"][src_abs] = f"{n}\\{name}"
                r["final_file"] = dst
            lista.append((name, r))
        counters[n] = seq

        if lista and not a.dry_run:
            kit = os.path.join(dest_dir, "lista-de-postagem.md")
            with open(kit, "a", encoding="utf-8") as f:
                if f.tell() == 0:
                    f.write(f"# Link {n}: {info.get('uploader') or ''} — {info.get('title', '')}\n\n")
                    f.write(f"{info.get('webpage_url', '')}\n")
                for name, r in lista:
                    f.write(f"\n## {name}\n")
                    f.write(f"- Título: {r.get('title', '')}\n")
                    f.write(f"- Descrição: {r.get('description', '')}\n")
                    f.write(f"- Hashtags: {' '.join(r.get('hashtags') or [])}\n")
                    f.write(f"- No original: {r.get('original_time', '')}\n")
            write_json(os.path.join(wd, "shorts", "renders.json"), renders)

    if not a.dry_run:
        os.makedirs(root, exist_ok=True)
        write_json(reg_path, reg)
        print(f"✓ Pasta: {root}")
    else:
        print("(dry-run: nada foi copiado nem gravado)")


if __name__ == "__main__":
    main()
