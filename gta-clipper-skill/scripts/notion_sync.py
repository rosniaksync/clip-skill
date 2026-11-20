"""Traz para os cortes o que o usuário mudou no Notion ("Resultados dos Cortes").

Uso (o Claude busca as linhas no Notion e grava num json):
  notion_sync.py linhas.json            # mostra o que mudou (não grava)
  notion_sync.py linhas.json --apply    # grava no clips.json e imprime o que renderizar de novo

linhas.json = [{"page_id": "...", "Gancho": "...", "Título e hashtags": "..."}, ...]
Cada linha é ligada ao corte pelo "notion_page_id" gravado no clips.json (work/<pasta>/clips.json).
- Gancho diferente do "hook"  -> troca o hook (precisa renderizar de novo).
- Título e hashtags diferentes -> troca "title" e "hashtags" (só o kit; não precisa renderizar).
"""
import argparse
import glob
import json
import os
import shutil
import sys

from common import load_config, utf8_stdout, work_root


def norm(t):
    return " ".join((t or "").split())


def split_title(th):
    """'Título 😳 #a #b' -> ('Título 😳', ['#a', '#b']) (hashtags = palavras do fim que começam com #)."""
    words = (th or "").split()
    tags = []
    while words and words[-1].startswith("#"):
        tags.insert(0, words.pop())
    return " ".join(words), tags


def joined(c):
    title, tags = c.get("title") or "", c.get("hashtags") or []
    t_words = title.split()
    while t_words and t_words[-1].startswith("#") and t_words[-1] in tags:
        t_words.pop()
    return " ".join(t_words + list(tags))


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    rows = {r["page_id"].replace("-", ""): r for r in json.load(open(a.rows, encoding="utf-8"))}

    root = work_root(load_config())
    found, rerender = set(), {}
    for cj in sorted(glob.glob(os.path.join(root, "*", "clips.json"))):
        clips = json.load(open(cj, encoding="utf-8"))
        changed = False
        for c in clips:
            pid = (c.get("notion_page_id") or "").replace("-", "")
            r = rows.get(pid)
            if not r:
                continue
            found.add(pid)
            wd = os.path.dirname(cj)
            g = norm(r.get("Gancho"))
            if g and g != norm(c.get("hook")):
                print(f"{os.path.basename(wd)} #{c['id']}: gancho  '{c.get('hook')}'  ->  '{g}'")
                if a.apply:
                    c["hook"] = g
                    c.pop("subhook", None)
                    changed = True
                rerender.setdefault(wd, []).append(c["id"])
            th = norm(r.get("Título e hashtags"))
            if th and th != norm(joined(c)):
                title, tags = split_title(th)
                print(f"{os.path.basename(wd)} #{c['id']}: título/hashtags  ->  '{th}'")
                if a.apply:
                    c["title"], c["hashtags"] = title, tags or c.get("hashtags", [])
                    changed = True
        if changed:
            shutil.copyfile(cj, cj + ".bak_notion")
            with open(cj, "w", encoding="utf-8") as f:
                json.dump(clips, f, ensure_ascii=False, indent=1)
    missing = [p for p in rows if p not in found]
    if missing:
        print(f"(sem corte no PC para {len(missing)} linha(s) do Notion: arquivos já apagados pela limpeza?)")
    if not rerender:
        print("Nada para renderizar de novo.")
    for wd, ids in rerender.items():
        print(f"RENDER {wd} --only {','.join(map(str, ids))}")
    if not a.apply and (rerender or missing is not None):
        print("(só mostrei; rode com --apply para gravar)")


if __name__ == "__main__":
    main()
