#!/usr/bin/env python3
"""lead_order.py - the night's incidents, most serious first.

The overnight report's writer chooses its opening paragraph and "The big one"
from this list, so the report leads the same way the reel, the night card and
the reel post do (owner rule 2026-10-20: "always lead with the serious events,
not a stupid fire"). The ranking is build.builders.night_counts.severity:

  0  gunfire, stabbings, homicides, standoffs, hostages
  1  any call with a weapon
  2  assaults, fights, domestic violence
  3  burglary, theft, pursuits, missing people
  4  fires at a home or a vehicle
  5  other fires, crashes, medical
  6  everything else

Inside a tier: higher notability, then the earlier call. A fire leads only on a
night with nothing in tiers 0-3.

Usage:  python kern_overnight/lead_order.py 2026-10-20 [--top 5] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.builders import night_counts  # noqa: E402

TIER_NAMES = ("gunfire / stabbing / standoff", "weapon", "assault / violence",
              "theft / pursuit / missing", "home or vehicle fire",
              "other fire / crash / medical", "other")


def _night_minute(t) -> int:
    try:
        h, m = (int(x) for x in str(t)[:5].split(":"))
    except ValueError:
        return 9999
    return ((h - 19) % 24) * 60 + m


def ranked(incidents: list[dict]) -> list[dict]:
    return sorted(incidents, key=lambda i: (night_counts.severity(i),
                                            -int(i.get("notability") or 0),
                                            _night_minute(i.get("time"))))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--incidents-dir", default=str(ROOT / "incidents"))
    a = ap.parse_args(argv)
    p = Path(a.incidents_dir) / f"{a.date}.json"
    try:
        incs = [i for i in json.loads(p.read_text(encoding="utf-8")) if isinstance(i, dict)]
    except (OSError, ValueError) as exc:
        print(f"lead_order: cannot read {p}: {exc}", file=sys.stderr)
        return 1
    rows = ranked(incs)[: a.top]
    if a.json:
        print(json.dumps([{**i, "severity": night_counts.severity(i)} for i in rows],
                         ensure_ascii=False, indent=1))
        return 0
    print(f"Most serious first ({len(incs)} incidents). Lead with #1; a fire leads only "
          f"when nothing in tiers 0-3 happened.")
    for n, i in enumerate(rows, 1):
        tier = night_counts.severity(i)
        print(f"{n}. [tier {tier}: {TIER_NAMES[tier]}] {i.get('time', '?')} "
              f"{i.get('type', '')}: {str(i.get('summary', ''))[:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
