#!/usr/bin/env python3
"""Regression tests for the 2026-10-04 site audit fixes.

  - the road change log follows the Kern corridor, not the statewide rollup
  - AirNow's replacement web services (the old ones were retired 2026-10-01)
  - evening builds keep the observed temperature instead of printing "n/a"
  - the fair page reads as a record once the fair is over
  - a brand suffix never pushes a title past the search-results cut
  - a noindex page stays out of the sitemap

Run:  .venv/Scripts/python.exe -m pytest tests/test_audit_2026_10.py -q
Fully offline.
"""
from __future__ import annotations

import datetime as dt
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import build_all, common  # noqa: E402
from build.builders import fair, home, page as page_mod  # noqa: E402
from build.sources import airnow, roads  # noqa: E402


# ---------------------------------------------------------------- road change log
def _route(on_pass_items, elsewhere_status="CLOSED"):
    return {"slug": "i5", "status": elsewhere_status, "scope": {
        "on_pass": roads._worst([i["status"] for i in on_pass_items]),
        "on_pass_reported": bool(on_pass_items), "on_pass_items": on_pass_items}}


def test_closure_elsewhere_on_the_route_is_not_a_corridor_change():
    clear = roads.corridor_state(_route([], elsewhere_status="OPEN"))
    orange_county_closure = roads.corridor_state(_route([], elsewhere_status="CLOSED"))
    assert clear == orange_county_closure
    assert clear[0] == "OPEN"


def test_corridor_problem_changes_status_and_hash():
    clear = roads.corridor_state(_route([]))
    wind = roads.corridor_state(_route([{"status": "RESTRICTIONS", "text": "High wind advisory"}]))
    shut = roads.corridor_state(_route([{"status": "CLOSED", "text": "Closed at Grapevine"}]))
    assert (wind[0], shut[0]) == ("RESTRICTIONS", "CLOSED")
    assert len({clear[1], wind[1], shut[1]}) == 3


def test_old_log_entries_are_relabelled_statewide(monkeypatch):
    old = [{"ts": "2026-10-01", "route": "i5", "from": "updated", "to": "CLOSED",
            "route_name": "Interstate 5 — Grapevine (Tejon Pass)"},
           {"ts": "2026-10-05", "time": "6:33 PM", "route": "i5", "from": "OPEN",
            "to": "RESTRICTIONS", "route_name": "I-5 Grapevine (Tejon Pass)", "scope": "corridor"}]
    monkeypatch.setattr(common, "load_snapshot", lambda name, default=None: old)
    log = roads._load_log()
    assert log[0]["route_name"] == "I-5, anywhere in California"
    assert log[1]["route_name"] == "I-5 Grapevine (Tejon Pass)"
    assert roads.log_when(log[0]) == "2026-10-01"
    assert roads.log_when(log[1]) == "2026-10-05 6:33 PM"
    assert "do not mean the pass itself was closed" in roads.log_note(log)
    assert roads.log_note(log[1:]) == ""


# ---------------------------------------------------------------- AirNow
def test_airnow_reads_the_replacement_services(monkeypatch):
    obs = [{"dateObserved": "2026-10-04", "hourObserved": "18:00", "reportingAreaName": "Bakersfield",
            "parameterName": "OZONE", "nowcastAQI": 112,
            "aqiCategoryName": "Unhealthy for Sensitive Groups"},
           {"dateObserved": "2026-10-04", "hourObserved": "18:00", "reportingAreaName": "Bakersfield",
            "parameterName": "PM2.5", "nowcastAQI": 54, "aqiCategoryName": "Moderate"}]
    today = common.iso_today()
    fc = [{"dateValid": today, "parameterName": "OZONE", "aqi": 140, "categoryNumber": 3,
           "categoryName": "Unhealthy for Sensitive Groups"},
          {"dateValid": "2099-01-01", "parameterName": "OZONE", "aqi": 300, "categoryNumber": 5,
           "categoryName": "Very Unhealthy"}]

    def fake_fetch(url, **kw):
        assert "ziplatlong" in url
        return types.SimpleNamespace(json=lambda: obs if "/observation/" in url else fc)

    monkeypatch.setenv("AIRNOW_API_KEY", "k")
    monkeypatch.setattr(common, "fetch", fake_fetch)
    out = airnow.run(None)
    assert out["ok"] and out["aqi"] == 112 and out["category_num"] == 3
    assert out["parameter"] == "OZONE" and out["area"] == "Bakersfield"
    assert out["forecast"]["aqi"] == 140 and out["forecast"]["category_num"] == 3


# ---------------------------------------------------------------- evening weather
def test_evening_build_shows_the_observed_temperature():
    evening = {"ok": True, "alerts": [], "forecast": {"current": 88, "high": None, "low": 61}}
    card = home._weather_tile(evening, "2026-10-04")
    assert "88&deg;" in card and "Low 61&deg; tonight" in card
    assert "Unavailable" not in card


# ---------------------------------------------------------------- fair
def _fair(monkeypatch, tmp_path, today):
    monkeypatch.setattr(common, "SITE", tmp_path)
    fair.build(types.SimpleNamespace(today=today, build_report={}, statusbar=""), {})
    return (tmp_path / "fair" / "index.html").read_text(encoding="utf-8")


def test_fair_page_reads_as_a_record_after_the_last_day(monkeypatch, tmp_path):
    during = _fair(monkeypatch, tmp_path, dt.date(2026, 10, 4))
    after = _fair(monkeypatch, tmp_path, dt.date(2026, 10, 5))
    assert "ended on October 4" not in during and "Fair runs" in during
    assert "ended on October 4" in after and "Fair ran" in after
    assert "Fair runs" not in after


# ---------------------------------------------------------------- titles
def test_brand_suffix_is_dropped_only_when_the_title_runs_long():
    long = "Is the Grapevine Open Right Now? Live I-5 Tejon Pass Status | Bakersfield Daily Brief"
    short = "Contact | Bakersfield Daily Brief"
    render = lambda t: page_mod.render(title=t, desc="d", canonical="/x/", content="")  # noqa: E731
    assert "<title>Is the Grapevine Open Right Now? Live I-5 Tejon Pass Status</title>" in render(long)
    assert "<title>Contact | Bakersfield Daily Brief</title>" in render(short)


# ---------------------------------------------------------------- sitemap
def test_noindex_pages_stay_out_of_the_sitemap(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "SITE", tmp_path)
    for path, robots in (("oversight", "noindex, follow"), ("grapevine", "index, follow")):
        (tmp_path / path).mkdir()
        (tmp_path / path / "index.html").write_text(
            f'<html><head><meta name="robots" content="{robots}"></head></html>', encoding="utf-8")
    build_all._sitemap()
    xml = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert "/grapevine/" in xml and "/oversight/" not in xml
