#!/usr/bin/env python3
"""Extract frames from candidate moments so they can be LOOKED AT (visual moments without speech).

Usage: extract_frames.py work/<id> --candidates cands.json [--frames 6]
cands.json: [{"id": 1, "start": "00:08:05", "end": "00:08:40"}, ...]
Writes work/<id>/frames/cand<id>_<n>.jpg (640px wide) and a contact sheet cand<id>.jpg per candidate.
"""
import argparse, json, os, subprocess

def sec(t):
    v = 0.0
    for p in str(t).split(":"):
        v = v * 60 + float(p)
    return v

ap = argparse.ArgumentParser()
ap.add_argument("workdir")
ap.add_argument("--candidates", required=True)
ap.add_argument("--frames", type=int, default=6)
ap.add_argument("--source")
a = ap.parse_args()
src = a.source or os.path.join(a.workdir, "source.mp4")
out = os.path.join(a.workdir, "frames"); os.makedirs(out, exist_ok=True)
for i, c in enumerate(json.load(open(a.candidates, encoding="utf-8")), 1):
    cid = c.get("id", i); s, e = sec(c["start"]), sec(c["end"])
    step = (e - s) / a.frames
    for n in range(a.frames):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s + step * (n + .5):.2f}", "-i", src, "-frames:v", "1",
                        "-vf", "scale=640:-2", os.path.join(out, f"cand{cid}_{n+1}.jpg")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", os.path.join(out, f"cand{cid}_%d.jpg"),
                    "-vf", f"tile=3x{(a.frames + 2) // 3}", "-frames:v", "1", os.path.join(out, f"cand{cid}.jpg")], check=True)
    print(f"candidato {cid}: frames/cand{cid}.jpg")
