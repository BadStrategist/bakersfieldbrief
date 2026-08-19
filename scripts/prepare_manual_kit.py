#!/usr/bin/env python3
"""Prepare the daily MANUAL posting kit for The Kern Overnight.

Runs after phase 2 + watchdog (~08:00 PT): verifies the publish gate,
renders (or reuses) the 30s reel MP4 + still card PNG deterministically,
composes the Facebook/IG caption, and prints everything a cron job needs
to deliver into the #manual-posting-station Discord thread.

Exit codes:
  0 = kit ready  (prints DATE=, REEL=, CARD=, CAPTION_START...CAPTION_END)
  3 = gate blocked or render failed (prints SKIP <reason>)

Usage:
  .venv\\Scripts\\python.exe scripts/prepare_manual_kit.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import post_facebook as PF  # noqa: E402


def today_la() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def main() -> int:
    date = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else today_la()

    # 1. Publish gate: complete report, no PARTIAL marker, required sections.
    gate = PF.gate_check(date)
    if gate is None:
        print(f"SKIP {date}: publish gate blocked — report not complete/ready")
        return 3
    brief, overnight = gate

    # 2. brief.json — deterministic config the renderer reads (same as CI).
    social = ROOT / "site" / "assets" / "img" / "social"
    brief_json = social / f"{date}-brief.json"
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_brief_json.py"),
         "--date", date, "--out", str(brief_json)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if rc.returncode != 0 or not brief_json.exists():
        print(f"SKIP {date}: brief.json generation failed: {rc.stderr.strip()[:200]}")
        return 3
    if brief_json.stat().st_size < 500:
        print(f"SKIP {date}: brief.json suspiciously small ({brief_json.stat().st_size} B)")
        return 3

    # 3. Music bed — same resolution as post_facebook.main (absolute path).
    music_rel = json.loads(brief_json.read_text(encoding="utf-8")).get(
        "music", "assets/audio/news_reel_bed.wav")
    music_abs = music_rel if Path(music_rel).is_absolute() else str(ROOT / music_rel)

    # 4. Render (or reuse) the reel + card.
    stem = social / f"{date}-reel"
    reel, card = stem.with_suffix(".mp4"), stem.with_suffix(".png")
    if reel.exists() and reel.stat().st_size > 100_000:
        print(f"reel exists, reusing: {reel}")
    else:
        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "brief_reel" / "render_reel.py"),
             str(brief_json), "--out", str(stem), "--music", music_abs],
            cwd=ROOT, capture_output=True, text=True,
        )
        if rc.returncode != 0 or not reel.exists() or reel.stat().st_size <= 100_000:
            print(f"SKIP {date}: reel render failed: {rc.stderr.strip()[:200]}")
            return 3
        print(f"reel rendered: {reel}")

    # 5. Caption — identical to what CI posts.
    message = PF.compose_post(date, brief, overnight)

    print(f"DATE={date}")
    print(f"REEL={reel}")
    print(f"CARD={card}")
    print("CAPTION_START")
    print(message)
    print("CAPTION_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
