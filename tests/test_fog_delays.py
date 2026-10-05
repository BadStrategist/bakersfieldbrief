#!/usr/bin/env python3
"""Tests for /fog-delays/: the AlertLine source, the season log and the page.

The season log is the only record of past fog days (AlertLine publishes today
only), so the merge rules are pinned here. The page must never claim a school
is on time, and the API key must never reach an error string.

Run:  .venv/Scripts/python.exe -m pytest tests/test_fog_delays.py -q
Fully offline: rows are AlertLine's own documented sample.
"""
from __future__ import annotations

import datetime as dt
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import common  # noqa: E402
from build.builders import fog_delays  # noqa: E402
from build.sources import alertline  # noqa: E402

# alertline.kern.org/api/1.0/posted/alerts/test, verbatim
SAMPLE = [
    {"site_name": "Bakersfield City School District", "description": "Fog Closure",
     "additional_info": None, "alert_category": "Fog Closure", "severity": 99,
     "updated_at": "2016-01-13 05:01:16"},
    {"site_name": "Arvin High School - (KHSD)", "description": "2 Hour Fog Delay",
     "additional_info": None, "alert_category": "Fog Delay", "severity": 2,
     "updated_at": "2016-01-13 05:05:16"},
    {"site_name": "Bear Valley/Stallion Springs", "description": "Custom",
     "additional_info": "Major flooding on city streets - schools closed for the day",
     "alert_category": "Custom", "severity": 99, "updated_at": "2016-01-13 06:21:16"},
]


def _alerts():
    return [alertline.normalize(r) for r in SAMPLE]


def test_normalize_kinds():
    closure, delay, custom = _alerts()
    assert (closure["kind"], closure["fog"]) == ("closure", True)
    assert (delay["kind"], delay["fog"], delay["severity"]) == ("delay", True, 2)
    assert (custom["kind"], custom["fog"]) == ("closure", False)
    assert alertline.normalize({"site_name": "  "}) is None


def test_record_keeps_most_severe_and_never_drops():
    log = {"started": "2026-10-04", "days": {}}
    delay = alertline.normalize(SAMPLE[1])
    assert alertline.record(log, "2026-11-17", [delay])
    # the district upgrades the delay to a closure later that morning
    upgraded = dict(delay, severity=99, kind="closure", description="Fog Closure")
    assert alertline.record(log, "2026-11-17", [upgraded])
    assert log["days"]["2026-11-17"][0]["kind"] == "closure"
    # a later run sees an empty board: the morning's alert stays on the record
    assert not alertline.record(log, "2026-11-17", [])
    assert not alertline.record(log, "2026-11-17", [delay])
    assert log["days"]["2026-11-17"][0]["kind"] == "closure"


def test_error_strings_never_carry_the_key():
    key = "6940b08f1b11e20238cd1c6a9712122d"
    msg = f"HTTPError: 403 for url: https://alertline.kern.org/api/1.0/posted/alerts/today/{key}"
    assert key not in alertline._scrub(msg, key)
    assert key not in alertline._scrub(msg, "")


def test_no_key_is_reported_not_raised(monkeypatch):
    monkeypatch.delenv("ALERTLINE_API_KEY", raising=False)
    out = alertline.run(None)
    assert out["ok"] is False and out["needs_key"] is True and "days" in out["log"]


def _build(monkeypatch, tmp_path, source, weather=None, today=dt.date(2026, 11, 17)):
    monkeypatch.setattr(common, "SITE", tmp_path)
    ctx = types.SimpleNamespace(today=today, build_report={}, statusbar="")
    fog_delays.build(ctx, {"alertline": source, "weather": weather or {"ok": True, "alerts": []}})
    return (tmp_path / "fog-delays" / "index.html").read_text(encoding="utf-8"), ctx


def test_page_with_alerts(monkeypatch, tmp_path):
    alerts = _alerts()
    log = {"started": "2026-10-04", "days": {"2026-11-17": alerts}}
    page, ctx = _build(monkeypatch, tmp_path, {"ok": True, "alerts": alerts, "log": log,
                                              "fetched_at": "2026-11-17 05:42"})
    assert "1 delay · 2 closures" in page
    assert "As of 5:42 AM on Tuesday, November 17" in page
    assert 'id="arvin-high-school-khsd"' in page
    assert "Major flooding on city streets" in page
    assert "1 fog day" in page
    assert "on time" not in page.lower()
    assert ctx.build_report["fog_delays"] == {"ok": True, "alerts": 3, "logged_days": 1}


def test_page_quiet_day_and_empty_record(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path, {
        "ok": True, "alerts": [], "fetched_at": "2026-10-05 06:10",
        "log": {"started": "2026-10-04", "days": {}}}, today=dt.date(2026, 10, 5))
    assert "No alerts posted" in page
    assert "no delays or closures are posted" in page
    assert "Nothing has been posted since this record started on Sunday, October 4, 2026" in page
    assert "on time" not in page.lower()


def test_page_when_alertline_is_unreachable(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path, {"ok": False, "error": "boom",
                                             "log": {"started": "2026-10-04", "days": {}}})
    assert "could not be read" in page
    assert "No alerts posted" not in page  # never assert an all-clear we did not see
    assert "boom" not in page


def test_last_school_year_stays_out_of_this_years_record():
    log = {"days": {"2026-02-05": _alerts(), "2026-11-17": _alerts()[:1]}}
    days, sites = fog_delays._season(log, dt.date(2026, 11, 20))
    assert [d["day"] for d in days] == ["2026-11-17"]
    assert len(sites) == 1


def test_fog_advisory_shown_only_when_nws_has_one(monkeypatch, tmp_path):
    wx = {"ok": True, "alerts": [
        {"event": "Dense Fog Advisory", "headline": "Dense Fog Advisory until 11 AM PST", "areas": "Kern"},
        {"event": "Wind Advisory", "headline": "Wind Advisory", "areas": "Kern"}]}
    page, _ = _build(monkeypatch, tmp_path, {"ok": True, "alerts": [], "log": {"days": {}},
                                             "fetched_at": "2026-11-17 05:42"}, weather=wx)
    assert "Dense Fog Advisory until 11 AM PST" in page
    assert "Wind Advisory" not in page
