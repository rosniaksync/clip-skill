#!/usr/bin/env python3
"""Histórico de cada vídeo/live: o que já foi cortado, para nunca repetir.

Fica em <paths.work_root>/historico/<plataforma>_<id>.json (um arquivo por vídeo; o VOD de uma live no ar
tem sempre o mesmo id, então mandar o link de novo continua de onde parou).

Uso:
  progress.py show <info.json | work/<id>>   # o que já foi feito e de onde continuar
  progress.py check work/<id>                # cortes do clips.json que repetem cortes já feitos
  progress.py done work/<id> [--block-minutes 30|60]   # no fim de CADA bloco: grava o trecho e os shorts dele
  progress.py notion work/<id>               # campos da linha em "Progresso dos Vídeos" (Notion)
  progress.py set-notion work/<id> <page_id> # guarda o id da linha do Notion (para atualizar a mesma)
"""
import argparse
import datetime
import json
import os
import sys

from common import (continue_from, history_path, history_summary, load_config, media_duration, read_json, secs,
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


PLATFORM = {"youtube": "YouTube", "youtubetab": "YouTube", "twitchvod": "Twitch", "twitchstream": "Twitch",
            "kick": "Kick", "kickvod": "Kick"}


def notion_fields(info, hist, cfg):
    """Linha de 'Progresso dos Vídeos': até onde cortou, de onde continuar e se a live continua."""
    spans, covered, n = history_summary(hist)
    nxt = ts(continue_from(covered, cfg))
    dur = float(hist.get("duration") or info.get("duration") or 0)
    if info.get("is_live"):
        status = "Live continua"
        aviso = f"A live continua. Me mande o link de novo depois que eu continuo de {nxt}, sem repetir."
    elif dur and covered >= dur - 5:
        status, aviso = "Concluído", "Vídeo inteiro cortado. Nada para continuar."
    else:
        status = "Em andamento"
        aviso = f"Parou em {ts(covered)}. Me mande o link de novo que eu continuo de {nxt}, sem repetir."
    bm = hist.get("block_minutes")
    return {
        "Vídeo": info.get("title") or info["id"],
        "Status": status,
        "Aviso": aviso,
        "Continuar de": "" if status == "Concluído" else nxt,
        "Cortado até": ts(covered),
        "Trechos cortados": ", ".join(f"{ts(a)}–{ts(b)}" for a, b in spans),
        "Shorts feitos": n,
        "Blocos feitos": len(hist.get("blocks", [])),
        "Tamanho do bloco": f"{int(bm)} min" if bm else None,
        "Plataforma": PLATFORM.get((info.get("extractor_key") or "").lower(), "Outro"),
        "Link do vídeo": info.get("webpage_url"),
        "ID do vídeo": history_path(info.get("extractor_key"), info["id"], cfg).rsplit(os.sep, 1)[-1][:-5],
        "date:Última atualização:start": datetime.date.today().isoformat(),
        "notion_page_id": hist.get("notion_page_id"),
    }


def show(hist, cfg):
    spans, covered, n = history_summary(hist)
    if not hist["blocks"]:
        print("Vídeo novo: nada cortado ainda. Começa em 00:00:00.")
        return
    print(f"Já cortado: {', '.join(f'{ts(s)}–{ts(e)}' for s, e in spans)}  ({len(hist['blocks'])} blocos, {n} shorts)")
    print(f"Continuar de: {ts(continue_from(covered, cfg))} (coberto até {ts(covered)}, menos a sobreposição)")
    for c in hist["clips"]:
        print(f"  • {ts(c['start'])}–{ts(c['end'])}  {c.get('hook', '')} / {c.get('subhook', '')}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["show", "check", "done", "notion", "set-notion"])
    ap.add_argument("target")
    ap.add_argument("page_id", nargs="?", help="com set-notion: id da linha em Progresso dos Vídeos")
    ap.add_argument("--block-minutes", type=float, help="com done: tamanho de bloco escolhido (30 ou 60)")
    a = ap.parse_args()
    info = load_info(a.target)
    path, hist = load_hist(info, cfg)

    if a.cmd == "show":
        return show(hist, cfg)
    if a.cmd == "notion":
        return print(json.dumps(notion_fields(info, hist, cfg), ensure_ascii=False, indent=1))
    if a.cmd == "set-notion":
        if not a.page_id:
            sys.exit("set-notion precisa do id da página")
        hist["notion_page_id"] = a.page_id
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, hist)
        return print(f"✓ Linha do Notion guardada no histórico: {a.page_id}")

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
    if a.block_minutes:
        hist["block_minutes"] = a.block_minutes
    if info.get("duration"):
        hist["duration"] = info["duration"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, hist)
    spans, covered, n = history_summary(hist)
    print(f"✓ Histórico atualizado: bloco {ts(block['start'])}–{ts(block['end'])}, +{new} shorts "
          f"(total {n}); coberto até {ts(covered)} → {path}")
    f = notion_fields(info, hist, cfg)
    print(f"  {f['Status']}: {f['Aviso']}")
    print("  Atualize 'Progresso dos Vídeos' no Notion com: progress.py notion " + wd)


if __name__ == "__main__":
    main()
