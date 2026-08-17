#!/usr/bin/env python3
"""Assemble the daily Facebook Reel for The Bakersfield Brief.

Turns the deterministic social card (1080x1350 PNG) + the 30s news-reel
audio bed into a 9:16 (1080x1920) MP4 with a slow Ken Burns zoom-in —
the standard news-reel look. Pure ffmpeg, no AI, brand colors intact.

Usage:
  python scripts/make_reel.py --card site/assets/img/social/<date>.png \
      --audio assets/audio/news_reel_bed.wav \
      --out site/assets/img/social/<date>-reel.mp4
  [--seconds 30] [--width 1080] [--height 1920] [--fps 30] [--no-fade]

Exit codes: 0 ok, 1 missing input, 2 ffmpeg/ffprobe failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PAPER_HEX = "0xFAF6EC"  # cream #FAF6EC — matches the card background
ZOOM_END = 1.10          # gentle 10% zoom-in over the clip


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card", required=True, type=Path, help="card PNG (1080x1350)")
    ap.add_argument("--audio", required=True, type=Path, help="WAV bed (30s)")
    ap.add_argument("--out", required=True, type=Path, help="output MP4 path")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-fade", action="store_true", help="skip the tail audio fade")
    return ap.parse_args()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    a = parse_args()
    if not a.card.exists():
        print(f"SKIP: card not found: {a.card}")
        return 1
    if not a.audio.exists():
        print(f"SKIP: audio bed not found: {a.audio}")
        return 1

    a.out.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(a.seconds * a.fps))
    zoom_inc = (ZOOM_END - 1.0) / frames  # per-frame zoom step
    fade_st = max(0.0, a.seconds - 0.7)

    # Ken Burns: zoompan on the card (padded to canvas with cream), audio
    # bed with a gentle tail fade so the cut never clicks.
    vf = (
        f"[0:v]scale={a.width}:{a.height}:force_original_aspect_ratio=decrease,"
        f"pad={a.width}:{a.height}:(ow-iw)/2:(oh-ih)/2:color={PAPER_HEX},"
        f"zoompan=z='min(1+{zoom_inc:.7f}*on,{ZOOM_END})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={a.width}x{a.height}:fps={a.fps},format=yuv420p[v]"
    )
    af = "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    if not a.no_fade:
        af += f",afade=t=out:st={fade_st:.2f}:d=0.7"
    af += "[a]"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(a.card),
        "-i", str(a.audio),
        "-filter_complex", f"{vf};{af}",
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
