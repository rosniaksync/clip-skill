#!/usr/bin/env python3
"""Histórico de cada vídeo/live: o que já foi cortado, para nunca repetir.

Fica em <paths.work_root>/historico/<plataforma>_<id>.json (um arquivo por vídeo; o VOD de uma live no ar
tem sempre o mesmo id, então mandar o link de novo continua de onde parou).

Uso:
  progress.py show <info.json | work/<id>>   # o que já foi feito e de onde continuar
  progress.py check work/<id>                # cortes do clips.json que repetem cortes já feitos
  progress.py done work/<id>                 # no fim de CADA bloco: grava o trecho e os shorts dele
"""
import argparse
import datetime
import os
import sys

from common import (history_path, history_summary, load_config, media_duration, read_json, secs,
                    section_offset, ts, write_json)


def load_info(target):
    p = target if target.endswith(".json") else os.path.join(target, "info.json")
    info = read_json(p)
    if not info or not info.get("id"):
        sys.exit(f"info.json sem id: {p}")
    return info


def load_hist(info, cfg):
    path = history_path(info.get("extractor_key"), info["id"], cfg)
    return path, read_json(path, None) or {
        "video": {k: info.get(k) for k in ("id", "extractor_key", "title", "webpage_url", "channel", "uploader")},
        "blocks": [], "clips": []}


def overlap(a, b):
    """fração do menor trecho que se sobrepõe ao outro"""
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return max(0.0, inter) / max(1e-6, min(a[1] - a[0], b[1] - b[0]))


def show(hist, cfg):
    spans, covered, n = history_summary(hist)
    if not hist["blocks"]:
        print("Vídeo novo: nada cortado ainda. Começa em 00:00:00.")
        return
    print(f"Já cortado: {', '.join(f'{ts(s)}–{ts(e)}' for s, e in spans)}  ({len(hist['blocks'])} blocos, {n} shorts)")
    ov = float(cfg.get("chunk_overlap_minutes", 5)) * 60
    print(f"Continuar de: {ts(max(0.0, covered - ov))} (coberto até {ts(covered)}, menos {ov / 60:g} min de sobreposição)")
    for c in hist["clips"]:
        print(f"  • {ts(c['start'])}–{ts(c['end'])}  {c.get('hook', '')} / {c.get('subhook', '')}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["show", "check", "done"])
    ap.add_argument("target")
    a = ap.parse_args()
    info = load_info(a.target)
    path, hist = load_hist(info, cfg)

    if a.cmd == "show":
        return show(hist, cfg)

    wd = a.target
    off = section_offset(wd)
    clips = read_json(os.path.join(wd, "clips.json"), []) or []

    if a.cmd == "check":
        rep = 0
        for c in clips:
            me = [secs(c["start"]) + off, secs(c["end"]) + off]
            for old in hist["clips"]:
                if overlap(me, [old["start"], old["end"]]) >= 0.5:
                    rep += 1
                    print(f"✗ corte #{c['id']} ({ts(me[0])}–{ts(me[1])}) repete '{old.get('hook')}' "
                          f"({ts(old['start'])}–{ts(old['end'])}, {os.path.basename(old.get('file') or '')}): descarte")
        print("✓ nenhum corte repetido" if not rep else f"{rep} corte(s) repetido(s)")
        return

    # done: grava o trecho do bloco e os shorts renderizados
    dur = media_duration(os.path.join(wd, "source.mp4"))
    block = {"start": round(off, 2), "end": round(off + dur, 2), "workdir": os.path.abspath(wd),
             "done_at": datetime.datetime.now().isoformat(timespec="seconds")}
    renders = read_json(os.path.join(wd, "shorts", "renders.json"), {}) or {}
    new = 0
    for c in clips:
        r = renders.get(str(c["id"]))
        if not r:
            continue
        item = {"start": round(secs(c["start"]) + off, 2), "end": round(secs(c["end"]) + off, 2),
                "hook": c.get("hook"), "subhook": c.get("subhook"), "file": r.get("file"),
                "notion_page_id": c.get("notion_page_id") or r.get("notion_page_id")}
        same = next((o for o in hist["clips"] if o.get("file") == item["file"]), None)
        if same:
            same.update(item)        # renderizado de novo (gancho trocado): atualiza, não duplica
        else:
            hist["clips"].append(item)
            new += 1
    hist["blocks"] = [b for b in hist["blocks"] if b.get("workdir") != block["workdir"]] + [block]
    block["shorts"] = sum(1 for c in clips if str(c["id"]) in renders)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, hist)
    spans, covered, n = history_summary(hist)
    print(f"✓ Histórico atualizado: bloco {ts(block['start'])}–{ts(block['end'])}, +{new} shorts "
          f"(total {n}); coberto até {ts(covered)} → {path}")


if __name__ == "__main__":
    main()
