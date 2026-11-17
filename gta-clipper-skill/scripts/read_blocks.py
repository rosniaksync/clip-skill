#!/usr/bin/env python3
"""Print transcript.txt in blocks of N minutes (default 10) so the whole video is read, not just the peaks.

Usage: read_blocks.py work/<id>                 # lists the blocks and their line counts
       read_blocks.py work/<id> --block 3       # prints block 3 (1-based), chat volume per minute appended
       read_blocks.py work/<id> --minutes 10
"""
import argparse, json, os, re

ap = argparse.ArgumentParser()
ap.add_argument("workdir")
ap.add_argument("--minutes", type=float, default=10)
ap.add_argument("--block", type=int)
a = ap.parse_args()

size = a.minutes * 60
lines = []
for ln in open(os.path.join(a.workdir, "transcript.txt"), encoding="utf-8"):
    m = re.match(r"\[(\d+):(\d+):(\d+)\]", ln)
    if m:
        h, mi, s = map(int, m.groups())
        lines.append((h * 3600 + mi * 60 + s, ln.rstrip()))
blocks = {}
for t, ln in lines:
    blocks.setdefault(int(t // size) + 1, []).append(ln)
if a.block is None:
    for b, ls in sorted(blocks.items()):
        print(f"block {b}: {len(ls)} lines  (starts {int((b-1)*size//60)} min)")
else:
    print("\n".join(blocks.get(a.block, [])))
