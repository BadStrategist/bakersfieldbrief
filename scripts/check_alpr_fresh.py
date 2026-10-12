#!/usr/bin/env python3
"""Fail a CI run when the ALPR camera data on /surveillance/ is not today's.

  python scripts/check_alpr_fresh.py [--alert-file /tmp/bb_alpr.txt]
  python scripts/check_alpr_fresh.py --ownership [--alert-file /tmp/bb_own.txt]

Why this exists: build/sources/alpr.py answers a failed Overpass fetch with its last good
camera list and ok=True, which is right for the page (2026-09-22: a short outage rebuilt the
site's top search page with zero cameras) and wrong as a health signal. The build stayed green,
nobody was told, and the only symptom was an older "Data as of" date until the Monday verify
step in weekly.yml. daily.yml runs this after every build, so an outage is a red run and an
ops Discord alert the same day.

Default mode reads the alpr payload the build just wrote (data/source_cache.json) and exits 1
unless ALL of these hold:
  - the payload exists and is ok
  - "stale" is explicitly False (a missing flag is a failure, not a pass)
  - it carries cameras
  - "asof" is the Pacific date of the run
A camera on a fresh list with no first-mapped date is a ::warning annotation and still exit 0.

--ownership reports on the land ownership join instead. That join is researched by hand on the
local box (the Flock transparency portals block datacenter IPs), so CI cannot refresh it and
must not fail over it. It always exits 0 on a readable verdict and writes
--alert-file only when a refresh is due, which weekly.yml turns into a Monday reminder.

Pure stdlib, like scripts/notify_discord.py. Exit 0 fresh, 1 not fresh, 2 bad invocation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PACIFIC = ZoneInfo("America/Los_Angeles")

# A run that builds at 23:58 PT and reaches this step at 00:03 holds data dated "yesterday" that
# is minutes old. The build's own date counts as the run's date while the build is this recent;
# the step sits after the deploy, a few minutes behind the build. Past the window only today's
# date passes, so an old report left in the checkout cannot vouch for old data.
BUILD_WINDOW = dt.timedelta(minutes=90)

# Ownership refresh is due when a mapped camera has waited this long for its owner record, or
# when the copy of the tax roll is this old even with every camera joined.
OWN_GAP_GRACE_DAYS = 14
OWN_MAX_AGE_DAYS = 90


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing or damaged file is a finding, reported by the caller
        return None


def run_dates(now: dt.datetime, built_at: str | None) -> list[str]:
    """Pacific dates that count as "the date of this run": today, plus the build's date when the
    build finished inside BUILD_WINDOW (the midnight straddle above)."""
    now = now.astimezone(PACIFIC)
    dates = [now.date().isoformat()]
    try:
        built = dt.datetime.fromisoformat(str(built_at))
        if built.tzinfo is None:
            built = built.replace(tzinfo=PACIFIC)
        if dt.timedelta(0) <= now - built <= BUILD_WINDOW:
            d = built.astimezone(PACIFIC).date().isoformat()
            if d not in dates:
                dates.append(d)
    except (TypeError, ValueError):
        pass
    return dates


def problems(alpr, dates: list[str]) -> list[str]:
    """Every reason the payload is not a fresh fetch. Empty list = fresh."""
    if not isinstance(alpr, dict) or not alpr:
        return ["the build wrote no alpr payload (data/source_cache.json has no \"alpr\" entry)"]
    err = str(alpr.get("error") or "no error text")[:300]
    asof = str(alpr.get("asof") or "")[:10]
    if alpr.get("ok") is not True:
        return [f"the Overpass fetch failed and there was no last good list to serve, so "
                f"/surveillance/ shows no cameras: {err}"]
    out = []
    stale = alpr.get("stale")
    if stale is True:
        out.append(f"the Overpass fetch failed; /surveillance/ is serving the last good list "
                   f"from {asof or 'an unknown date'}: {err}")
    elif stale is not False:
        out.append(f"the payload has no explicit stale flag (stale={stale!r}); a fetch that "
                   "cannot be shown to have succeeded is not counted as fresh")
    if not alpr.get("cameras"):
        out.append("the payload is ok but carries zero cameras")
    if asof not in dates:
        out.append(f"asof is {asof or 'missing'}, not the Pacific date of this run "
                   f"({' or '.join(dates)})")
    return out


def undated(alpr) -> list[str]:
    """Ids of cameras on the list with no first-mapped date: an edited node whose OSM history
    lookup failed. A warning, never a failure here: the list is the day's, the camera is on the
    page, and it is only missing from "new this week" until a later build dates it. The weekly
    run is the strict one (build/sources/alpr.py refuses the change-log row)."""
    cams = alpr.get("cameras") if isinstance(alpr, dict) else None
    return [str(c.get("id")) for c in cams or [] if isinstance(c, dict) and not c.get("mapped")]


def ownership_status(alpr, own, today: str) -> dict:
    """How far the land ownership join is behind the camera list.

    due=True when a refresh should be on a human's list; reasons says why in plain words.
    """
    cams = (alpr or {}).get("cameras") if isinstance(alpr, dict) else None
    if not isinstance(own, dict) or not own.get("cams"):
        return {"due": True, "built": "", "age_days": None, "unjoined": None,
                "reasons": ["data/alpr/explorer_data.json is missing or unreadable, so "
                            "/surveillance/ shows no land ownership at all"]}
    built = str((own.get("meta") or {}).get("built") or "")[:10]
    try:
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(built)).days
    except ValueError:
        age = None
    joined_ids = {str(c.get("id")) for c in own["cams"]}
    unjoined = (None if not cams else
                sorted(str(c.get("id")) for c in cams if str(c.get("id")) not in joined_ids))
    reasons = []
    if age is None:
        reasons.append("the ownership data carries no readable build date")
    else:
        if unjoined and age > OWN_GAP_GRACE_DAYS:
            n = len(unjoined)
            reasons.append(f"{n} mapped camera{'s have' if n != 1 else ' has'} no owner record and "
                           f"the join is {age} days old (grace is {OWN_GAP_GRACE_DAYS})")
        if age > OWN_MAX_AGE_DAYS:
            reasons.append(f"the tax-roll copy is {age} days old (limit is {OWN_MAX_AGE_DAYS})")
    return {"due": bool(reasons), "built": built, "age_days": age,
            "unjoined": unjoined, "reasons": reasons}


def _write_alert(path: str, text: str) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", default=str(ROOT / "data" / "source_cache.json"))
    ap.add_argument("--report", default=str(ROOT / "data" / "build_report.json"))
    ap.add_argument("--own", default=str(ROOT / "data" / "alpr" / "explorer_data.json"))
    ap.add_argument("--alert-file", default="",
                    help="written ONLY when there is something to tell a human")
    ap.add_argument("--ownership", action="store_true",
                    help="report on the land ownership join instead (never fails the run)")
    args = ap.parse_args(argv)

    now = now or dt.datetime.now(PACIFIC)
    today = now.astimezone(PACIFIC).date().isoformat()
    alpr = (_load(Path(args.cache)) or {}).get("alpr")

    if args.ownership:
        st = ownership_status(alpr, _load(Path(args.own)), today)
        n = "unknown" if st["unjoined"] is None else len(st["unjoined"])
        print(f"alpr ownership: built={st['built'] or 'unknown'} age_days={st['age_days']} "
              f"unjoined={n} due={st['due']}")
        if st["due"]:
            lines = ["The land ownership join on /surveillance/ is due for a refresh:"]
            lines += [f"- {r}" for r in st["reasons"]]
            if st["unjoined"]:
                lines.append("unjoined OSM nodes: " + ", ".join(st["unjoined"][:20])
                             + (" ..." if len(st["unjoined"]) > 20 else ""))
            lines.append("It is a manual job on the local box: work/alpr_ownership/rebuild_all.py, "
                         "then commit data/alpr/explorer_data.json and explorer_stats.json.")
            text = "\n".join(lines) + "\n"
            print(text, end="")
            _write_alert(args.alert_file, text)
        return 0

    built_at = (_load(Path(args.report)) or {}).get("built_at")
    dates = run_dates(now, built_at)
    found = problems(alpr, dates)
    a = alpr if isinstance(alpr, dict) else {}
    print(f"alpr freshness: ok={a.get('ok')} stale={a.get('stale')} asof={a.get('asof')} "
          f"cameras={len(a.get('cameras') or [])} run_date(PT)={'|'.join(dates)} built_at={built_at}")
    blank = undated(alpr)
    if blank:
        print(f"::warning title=ALPR camera with no first-mapped date::{len(blank)} camera(s) on "
              "the list could not be dated from the OSM history and are left out of the new this "
              f"week count until a later build dates them: nodes {', '.join(blank[:20])}"
              + (" ..." if len(blank) > 20 else ""))
    if not found:
        print("alpr freshness: OK, the camera list was fetched from OpenStreetMap on this run")
        return 0
    for f in found:
        # one line per annotation: GitHub cuts an ::error at the first newline
        print(f"::error title=ALPR tracker is not fresh::{' '.join(f.split())}")
    text = ("The camera data on /surveillance/ is NOT today's.\n"
            + "".join(f"- {f}\n" for f in found)
            + "The page is unchanged: it keeps the last good list and its true \"Data as of\" "
              "date, so this alert is the only signal. Every build tries Overpass again. If the "
              "next run is red too, Overpass is down or blocking the runner: see OVERPASS in "
              "build/sources/alpr.py.\n")
    _write_alert(args.alert_file, text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
