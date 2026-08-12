#!/usr/bin/env python3
"""Disk hygiene for Kern Overnight audio.

Deletes audio/<YYYY-MM-DD>/ block directories older than `--keep` days.
Audio is the one heavy local artifact (~60MB/night) and is never needed
again once transcribed — transcripts/ are the committed, durable copy.

Safety:
  - only touches directories matching audio/YYYY-MM-DD
  - never deletes the current day or anything else under audio/
  - --dry-run prints what would be removed without deleting
  - silence is success: cron watchdog delivers output only when
    something was actually cleaned

Usage:
  python scripts/cleanup_audio.py            # real cleanup (keep 7 days)
  python scripts/cleanup_audio.py --dry-run  # preview
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", type=int, default=7,
                    help="days of audio to keep (default 7)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be deleted, delete nothing")
    args = ap.parse_args()

    if not AUDIO.is_dir():
        return 0  # nothing to do — silence is success

    cutoff = dt.date.today() - dt.timedelta(days=args.keep)
    freed = 0
    removed = []
    for d in sorted(AUDIO.iterdir()):
        if not d.is_dir():
            continue
        try:
            day = dt.date.fromisoformat(d.name)
        except ValueError:
            continue  # not a date dir — leave it alone
        if day >= cutoff:
            continue
        size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        removed.append((d.name, size))
        if not args.dry_run:
            shutil.rmtree(d, ignore_errors=True)
        freed += size

    if not removed:
        return 0  # nothing old — silence is success

    for name, size in removed:
        print(f"removed audio/{name} ({size / 1_048_576:.1f} MB)"
              + (" [dry-run]" if args.dry_run else ""))
    print(f"total: {len(removed)} day(s), {freed / 1_048_576:.1f} MB"
          + (" [dry-run — nothing deleted]" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
