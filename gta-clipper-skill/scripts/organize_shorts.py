#!/usr/bin/env python3
"""Organiza os shorts prontos numa pasta por STREAMER (o mesmo nome da opção "Streamer" no Notion).

    <shorts_root>/                  (C:\\cortes\\shorts)
        coringa/
            01_GANCHO DO SHORT.mp4  <- 01 = ID do short (o mesmo número vai no campo "ID" do Notion)
            02_OUTRO GANCHO.mp4
        alanzoka/
            ...

Uso:
    python scripts/organize_shorts.py work/<pasta> [work/<pasta2> ...] --streamer coringa [--dry-run]

- `--streamer`: nome EXATO da opção no Notion. Sem ele, usa o que já foi gravado para esse canal antes.
- O número (ID) é por streamer e só cresce, mesmo depois da limpeza do dia apagar as pastas: o registro fica em
  <work_root>/historico/shorts_registro.json (a limpeza não apaga o histórico).
- Short refeito (gancho ou tempo trocado): mantém o MESMO número; o arquivo antigo vai para a Lixeira do Windows.
- Copia de work/<pasta>/shorts/ (a limpeza do dia apaga work/). Imprime "ID <streamer> <n> <arquivo>" por short.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import cfg_path, load_config, read_json, video_key, work_root, write_json   # noqa: E402

DEFAULT_ROOT = r"C:\cortes\shorts"


def safe_name(text, limit=60):
    t = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE)     # tira emoji, :, /, ? etc.
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:limit].strip() or "short")


def to_trash(path):
    """Manda para a Lixeira do Windows (dá para recuperar). Fora do Windows: apaga."""
    if not os.path.exists(path):
        return
    if os.name == "nt":
        fn = "DeleteDirectory" if os.path.isdir(path) else "DeleteFile"
        ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; "
              f"[Microsoft.VisualBasic.FileIO.FileSystem]::{fn}($env:TRASH_PATH, 'OnlyErrorDialogs', 'SendToRecycleBin')")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                       env=dict(os.environ, TRASH_PATH=os.path.abspath(path)))
    elif os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def write_list(dest_dir, streamer, items):
    """Reescreve a lista-de-postagem.md da pasta do streamer com os shorts que ainda estão nela."""
    lines = [f"# {streamer}\n"]
    for num in sorted(items, key=int):
        it = items[num]
        if not os.path.isfile(os.path.join(dest_dir, it["name"])):
            continue
        lines += [f"\n## {it['name']}",
                  f"- ID: {num}",
                  f"- Título: {it.get('title', '')}",
                  f"- Descrição: {it.get('description', '')}",
                  f"- Hashtags: {it.get('hashtags', '')}",
                  f"- Live: {it.get('live', '')}",
                  f"- No original: {it.get('original_time', '')}"]
    with open(os.path.join(dest_dir, "lista-de-postagem.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    from common import utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("workdirs", nargs="+", help="pastas work/<pasta> com shorts/renders.json")
    ap.add_argument("--streamer", help="nome da opção Streamer no Notion (ex.: coringa)")
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que faria")
    a = ap.parse_args()

    cfg = load_config()
    root = cfg_path("shorts_root", cfg) or DEFAULT_ROOT
    reg_path = os.path.join(work_root(cfg), "historico", "shorts_registro.json")
    reg = read_json(reg_path, {}) or {}
    reg.setdefault("canais", {})       # canal (uploader) -> streamer
    reg.setdefault("ultimo", {})       # streamer -> maior ID já usado
    reg.setdefault("cortes", {})       # "<pasta de trabalho>#<id do corte>" -> {"streamer", "num", "name"}
    reg.setdefault("itens", {})        # streamer -> {num: dados da lista de postagem}

    for wd in a.workdirs:
        info = read_json(os.path.join(wd, "info.json"), {}) or {}
        renders = read_json(os.path.join(wd, "shorts", "renders.json"), None)
        if not info or not renders:
            print(f"✗ {wd}: sem info.json ou shorts/renders.json, pulando")
            continue
        canal = info.get("channel") or info.get("uploader") or video_key(info.get("extractor_key"), info.get("id"))
        streamer = a.streamer or reg["canais"].get(canal)
        if not streamer:
            sys.exit(f"✗ {wd}: diga o streamer (--streamer <nome igual ao do Notion>) para o canal '{canal}'")
        reg["canais"][canal] = streamer
        dest_dir = os.path.join(root, streamer)
        items = reg["itens"].setdefault(streamer, {})
        print(f"{streamer}: {canal} — {info.get('title', '')[:60]}")

        for cid in sorted(renders, key=lambda x: int(x)):
            r = renders[cid]
            src = r.get("file")
            if not src or not os.path.isfile(src):
                print(f"  - corte {cid}: arquivo não existe mais, pulando")
                continue
            key = f"{os.path.abspath(wd)}#{cid}"
            hook = r.get("hook_text") or " ".join(x for x in (r.get("hook", ""), r.get("subhook", "")) if x)
            prev = reg["cortes"].get(key)
            if prev and prev["streamer"] == streamer:
                num = prev["num"]
                old = os.path.join(dest_dir, prev["name"])
                if os.path.isfile(old) and os.path.getsize(old) == os.path.getsize(src):
                    print(f"  = corte {cid}: já está como {streamer}\\{prev['name']}")
                    r["final_file"], r["numero"] = old, num
                    print(f"ID {streamer} {num} {old}")
                    continue
            else:
                num = int(reg["ultimo"].get(streamer, 0)) + 1
                if os.path.isdir(dest_dir):     # se o usuário pôs arquivos à mão, não repete número
                    used = [int(f.split("_", 1)[0]) for f in os.listdir(dest_dir) if f.split("_", 1)[0].isdigit()]
                    num = max([num] + [u + 1 for u in used])
                reg["ultimo"][streamer] = num
            name = f"{num:02d}_{safe_name(hook)}.mp4"
            dst = os.path.join(dest_dir, name)
            print(f"  + corte {cid} -> {streamer}\\{name}" + ("  (o antigo vai para a Lixeira)" if prev else ""))
            if not a.dry_run:
                os.makedirs(dest_dir, exist_ok=True)
                if prev:
                    to_trash(os.path.join(root, prev["streamer"], prev["name"]))
                shutil.copy2(src, dst)
                reg["cortes"][key] = {"streamer": streamer, "num": num, "name": name}
                tags = r.get("hashtags") or []
                items[str(num)] = {"name": name, "title": r.get("title", ""), "description": r.get("description", ""),
                                   "hashtags": tags if isinstance(tags, str) else " ".join(tags),
                                   "live": info.get("webpage_url", ""), "original_time": r.get("original_time", "")}
                r["final_file"], r["numero"] = dst, num
            print(f"ID {streamer} {num} {dst}")

        if not a.dry_run:
            write_json(os.path.join(wd, "shorts", "renders.json"), renders)

    if not a.dry_run:
        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        write_json(reg_path, reg)
        print(f"✓ Pasta: {root}")
    else:
        print("(dry-run: nada foi copiado nem gravado)")


if __name__ == "__main__":
    main()
