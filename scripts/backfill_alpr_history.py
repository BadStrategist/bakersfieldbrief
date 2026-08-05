#!/usr/bin/env python3
"""Backfill the ALPR change log with the last 13 weeks of REAL OSM mapping
activity, derived from node timestamps (Overpass `out meta`). Run once after
setup; the weekly workflow appends genuine diffs going forward.

  python scripts/backfill_alpr_history.py

Output: data/change_logs/alpr.json (13 weekly entries, oldest → newest) and
refreshes data/snapshots/alpr_nodes.json. Prints the weekly trend so you can
see whether cameras are actually being added to the map.
"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import common  # noqa: E402
from build.sources import alpr  # noqa: E402

WEEKS = 13


def main():
    r = common.fetch(alpr.OVERPASS, method="POST", data={"data": alpr.QUERY}, timeout=120)
    elements = r.json().get("elements", [])
    by_id = {}
    for e in elements:
        t = e.get("tags") or {}
        by_id[e["id"]] = {
            "id": e["id"],
            "lat": e.get("lat"), "lon": e.get("lon"),
            "manufacturer": t.get("manufacturer", "Unspecified"),
            "direction": t.get("direction", ""),
            "mapped": (e.get("timestamp") or "")[:10],
        }

    today = date.today()
    # weeks end on Sundays; start from the Monday 13 weeks ago
    monday = today - timedelta(days=today.weekday())
    entries = []
    for i in range(WEEKS):
        week_end = monday - timedelta(days=7 * (WEEKS - 1 - i) - 6)  # Sunday of week i
        week_start = week_end - timedelta(days=6)                    # Monday of week i
        if week_end > today:
            week_end = today
        cum = [c for c in by_id.values() if c["mapped"] and c["mapped"] <= week_end.isoformat()]
        new = [c["id"] for c in by_id.values()
               if c["mapped"] and week_start.isoformat() <= c["mapped"] <= week_end.isoformat()]
        entries.append({
            "date": week_end.isoformat(),
            "total": len(cum),
            "new_ids": sorted(new),
            "gone_ids": [],
            "new_count": len(new),
        })

    common.append_change_log("alpr", entries[0])
    # replace the whole log (idempotent backfill): write entries directly
    log = common.load_change_log("alpr")
    # keep only backfilled entries (drop any test entries from earlier runs)
    log = [e for e in log if e.get("date") >= entries[0]["date"]]
    known = {e["date"] for e in log}
    for e in entries:
        if e["date"] not in known:
            log.append(e)
    log.sort(key=lambda e: e["date"])
    (common.LOGS / "alpr.json").write_text(
        __import__("json").dumps(log, indent=1, default=str), encoding="utf-8")

    common.save_snapshot("alpr_nodes", sorted(by_id.keys()))

    print(f"backfilled {len(entries)} weekly entries (total mapped now: {len(by_id)})")
    print(f"{'week ending':<12}{'total':>7}{'new that week':>15}")
    for e in entries:
        print(f"{e['date']:<12}{e['total']:>7}{e['new_count']:>15}")
    recent = sum(e["new_count"] for e in entries[-4:])
    print(f"\nnew cameras in the last 4 weeks: {recent} "
          + ("— cameras ARE being added to the map" if recent >= 5
             else "— mapping has been stagnant (few/no new cameras)"))
    print("direction-tagged cameras:", sum(1 for c in by_id.values() if c["direction"]))


if __name__ == "__main__":
    main()
