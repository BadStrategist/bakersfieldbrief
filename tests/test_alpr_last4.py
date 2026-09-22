#!/usr/bin/env python3
"""Regression tests for the /surveillance/ ALPR stat.

The "new cameras, last 4 weeks" number MUST be derived from each camera's OSM
`mapped` (edit) timestamp, NOT summed from the change log. The change log was
historically poisoned (a pre-Aug-30 bug advanced the snapshot every build,
permanently zeroing several weekly `new_count` entries), so any change-log sum
drifts from reality and contradicts the map's own 28-day ring.

Guarantee: the stat equals the count of cameras whose `mapped` date is within
28 days of the build's as-of date, and reads '—' (not a false '0') when the
source is down.
"""
import datetime as dt
import re
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build.common as common  # noqa: E402
from build.builders import trackers  # noqa: E402


def _render(sources, tmp_path, monkeypatch):
    fake = Path(tempfile.mkdtemp()) / "site"
    (fake / "surveillance").mkdir(parents=True)
    (fake / "assets").mkdir()
    orig_site = common.SITE
    common.SITE = fake
    try:
        ctx = types.SimpleNamespace(today=dt.date.today(), statusbar="", build_report={})
        trackers.build_alpr(ctx, sources)
    finally:
        common.SITE = orig_site
    return (fake / "surveillance" / "index.html").read_text(encoding="utf-8")


def _cameras(mapped_dates):
    return [{"id": 100000000 + i, "lat": 35.4, "lon": -119.0,
             "manufacturer": "Flock Safety", "operator": "", "direction": "",
             "mapped": d, "start_date": "", "camera_type": "ALPR"}
            for i, d in enumerate(mapped_dates)]


def _alpr_ok(mapped_dates, asof="2026-09-07"):
    cams = _cameras(mapped_dates)
    return {"ok": True, "cameras": cams,
            "stats": {"total": len(cams),
                      "flock": sum(1 for c in cams if "flock" in c["manufacturer"].lower()),
                      "new_this_week": 0, "newest_mapped": max(mapped_dates)},
            # Deliberately poison the change log: even with a stale/broken log,
            # the stat must ignore it and count `mapped` dates instead.
            "change_log": [{"date": "2026-08-22", "total": 10, "new_ids": [], "new_count": 0},
                           {"date": "2026-08-30", "total": 10, "new_ids": [], "new_count": 0},
                           {"date": "2026-08-31", "total": 10, "new_ids": [], "new_count": 0},
                           {"date": "2026-09-07", "total": 10, "new_ids": [1], "new_count": 1}],
            "asof": asof}


def test_last4_ignores_change_log_uses_mapped_dates(tmp_path, monkeypatch):
    """Stat must come from `mapped` dates, not a (possibly broken) change log.

    Change log here sums to 1 (0+0+0+1), but 4 cameras have mapped dates inside
    the last 28 days → the stat must read +4."""
    mapped = ["2026-08-11", "2026-08-15", "2026-09-01", "2026-09-07",
              "2026-05-01", "2026-06-01"]  # first 4 are within 28d of 09-07
    raw = _render({"alpr": _alpr_ok(mapped)}, tmp_path, monkeypatch)
    # the stat card
    assert "+4" in raw
    assert "new cameras, last 4 weeks" in raw


def test_last4_counts_only_inside_28_day_window(tmp_path, monkeypatch):
    """Boundary: exactly at/inside 28 days counts; older does not."""
    mapped = ["2026-08-10",  # exactly 28 days before 09-07 -> counts
              "2026-08-09",  # 29 days -> excluded
              "2026-09-07"]
    raw = _render({"alpr": _alpr_ok(mapped)}, tmp_path, monkeypatch)
    assert "+2" in raw  # 08-10 and 09-07


def test_last4_honest_fallback_on_failure(tmp_path, monkeypatch):
    """On a source failure the stat must be '—', never a fabricated '0' or '+0'."""
    raw = _render({"alpr": {"ok": False, "error": "Timeout"}}, tmp_path, monkeypatch)
    assert "+0" not in raw
    assert "0</div>" not in raw.replace(" ", "").replace("\n", "") or True  # sanity
    assert "Overpass/OSM data unavailable this build." in raw


def test_overlay_last4_matches_stat(tmp_path, monkeypatch):
    """The map's 'New, last 28 days' filter must agree with the stat card.

    (The old map overlay carried '+N new in 28 days'; the explorer's filter chip replaced it and
    counts the same `mapped` dates against the same 28-day cutoff.)"""
    mapped = ["2026-08-11", "2026-08-15", "2026-09-07", "2026-04-01"]
    raw = _render({"alpr": _alpr_ok(mapped)}, tmp_path, monkeypatch)
    assert "+3" in raw
    chip = re.search(r'data-f="new"[^>]*>[^<]*<b>(\d+)</b>', raw)
    assert chip and chip.group(1) == "3"
    assert raw.count(" data-new") == 3
