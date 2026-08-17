#!/usr/bin/env python3
"""Assemble the daily Facebook Reel for The Bakersfield Brief.

Turns the deterministic social card (1080x1350 PNG) + the 30s news-reel
audio bed into a 9:16 (1080x1920) MP4 with a slow Ken Burns zoom-in —
the standard news-reel look. Pure ffmpeg, no AI, brand colors intact.

Usage:
  python scripts/make_reel.py --panels p1.png p2.png p3.png p4.png \
      --audio assets/audio/news_reel_bed.wav \
      --out site/assets/img/social/<date>-reel.mp4
  [--seconds 30] [--fps 30] [--no-fade]
  Panels may also be passed as --card (single-image reel, kept for compat).

Exit codes: 0 ok, 1 missing input, 2 ffmpeg/ffprobe failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PAPER_HEX = "0xFAF6EC"  # cream #FAF6EC — matches the card background
ZOOM_END = 1.10          # gentle 10% zoom-in over each panel


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card", type=Path, help="single card PNG (compat mode)")
    ap.add_argument("--panels", nargs="+", type=Path, help="reel panel PNGs (1080x1920)")
    ap.add_argument("--audio", required=True, type=Path, help="WAV bed (30s)")
    ap.add_argument("--out", required=True, type=Path, help="output MP4 path")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-fade", action="store_true", help="skip the tail audio fade")
    return ap.parse_args()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    a = parse_args()
    panels = list(a.panels) if a.panels else ([a.card] if a.card else [])
    if not panels:
        print("SKIP: provide --panels (or --card)")
        return 1
    for p in panels:
        if not p.exists():
            print(f"SKIP: panel not found: {p}")
            return 1
    if not a.audio.exists():
        print(f"SKIP: audio bed not found: {a.audio}")
        return 1

    a.out.parent.mkdir(parents=True, exist_ok=True)
    n = len(panels)
    per = a.seconds / n  # equal split: 30s / 4 panels = 7.5s each
    fade_st = max(0.0, a.seconds - 0.7)

    # Each panel is a looped still with a slow zoom; concat the n segments.
    inputs: list[str] = []
    filters: list[str] = []
    for i, p in enumerate(panels):
        inputs += ["-loop", "1", "-i", str(p)]
        frames = int(per * a.fps)
        zoom_inc = (ZOOM_END - 1.0) / frames
        filters.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color={PAPER_HEX},"
            f"zoompan=z='min(1+{zoom_inc:.7f}*on,{ZOOM_END})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s=1080x1920:fps={a.fps}[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filters.append(f"{concat_in}concat=n={n}:v=1:a=0,format=yuv420p[v]")
    af = f"[{n}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    if not a.no_fade:
        af += f",afade=t=out:st={fade_st:.2f}:d=0.7"
    af += "[a]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-i", str(a.audio),
        "-filter_complex", ";".join(filters + [af]),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{a.seconds:.2f}",
        "-movflags", "+faststart",
        str(a.out),
    ]
    r = run(cmd)
    if r.returncode != 0:
        print(f"ffmpeg failed ({r.returncode}):\n{r.stderr[-800:]}")
        return 2
    if not a.out.exists() or a.out.stat().st_size < 50_000:
        print(f"SKIP: reel suspiciously small/missing: {a.out}")
        return 2

    # verify the output with ffprobe (duration + dimensions)
    p = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(a.out),
    ])
    try:
        info = json.loads(p.stdout)
        dur = float(info["format"]["duration"])
        vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
        w, h = int(vstream["width"]), int(vstream["height"])
    except Exception as exc:  # noqa: BLE001
        print(f"ffprobe verify failed: {exc}")
        return 2
    print(
        f"reel saved: {a.out} "
        f"({w}x{h}, {dur:.1f}s, {a.out.stat().st_size / 1e6:.1f} MB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
