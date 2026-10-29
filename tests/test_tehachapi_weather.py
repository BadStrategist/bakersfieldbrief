#!/usr/bin/env python3
"""Regression tests for the Tehachapi Weather page (/tehachapi-weather/).

Year-round host for 'tehachapi weather' queries. Same formula as the pass +
grapevine pages: direct answer with the live reading, FAQPage JSON-LD with the
current conditions in Q1, honest timestamps, and no fabricated data when the
NWS source is unavailable (each weather block degrades to 'unavailable this
build' rather than inventing a temperature).

Run:  .venv/Scripts/python.exe -m pytest tests/test_tehachapi_weather.py -q
Fully offline — pure functions + constructed fixtures, no network.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build.builders import tehachapi_weather  # noqa: E402
import build.common as common  # noqa: E402


def _weather(temp=61, wind=21, ok=True):
    return {"ok": True, "current": {
        "ok": ok, "station": "KTSP", "temperature": temp,
        "wind_mph": wind, "wind_dir": "W", "condition": "Clear",
        "humidity": 30, "observed": "Sep 05, 10:35 PM",
    }, "forecast": [{
        "name": "Tonight", "is_daytime": False, "temp_f": 50,
        "wind_speed": "0 to 5 mph", "wind_dir": "W", "short": "Mostly Clear",
        "starts": "2026-09-05",
    }], "alerts": [], "asof": "2026-09-05"}


def _render(sources, tmp_path, monkeypatch):
    import types
    fake = Path(tempfile.mkdtemp()) / "site"
    (fake / "tehachapi-weather").mkdir(parents=True)
    (fake / "assets").mkdir()
    orig = common.SITE
    common.SITE = fake
    try:
        ctx = types.SimpleNamespace(today=dt.date.today(), statusbar="", build_report={})
        tehachapi_weather.build(ctx, sources)
    finally:
        common.SITE = orig
    return (fake / "tehachapi-weather" / "index.html").read_text(encoding="utf-8")


def _visible(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))


def test_direct_answer_has_live_temp(tmp_path, monkeypatch):
    body = _visible(_render({"tehachapi_weather": _weather(61)}, tmp_path, monkeypatch))
    assert "Right now it is 61" in body
    assert "21 mph" in body
    assert "KTSP" in body


def test_current_card_live(tmp_path, monkeypatch):
    body = _visible(_render({"tehachapi_weather": _weather(temp=72, wind=15)}, tmp_path, monkeypatch))
    assert "Right now in Tehachapi" in body
    assert "72" in body


def test_no_fabrication_when_nws_unavailable(tmp_path, monkeypatch):
    body = _visible(_render({"tehachapi_weather": _weather(ok=False)}, tmp_path, monkeypatch))
    assert "unavailable this build" in body
    assert "Right now it is" not in body  # no invented reading


def test_forecast_and_alerts_blocks(tmp_path, monkeypatch):
    body = _visible(_render({"tehachapi_weather": _weather()}, tmp_path, monkeypatch))
    assert "Forecast" in body
    assert "NWS alerts for the area" in body
    assert "No active NWS advisories" in body


def test_crosslinks_to_pass_page(tmp_path, monkeypatch):
    raw = _render({"tehachapi_weather": _weather()}, tmp_path, monkeypatch)
    assert "tehachapi-pass" in raw  # 2-way internal linking


def test_faq_jsonld_live_q1(tmp_path, monkeypatch):
    import json
    raw = _render({"tehachapi_weather": _weather(66)}, tmp_path, monkeypatch)
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, re.S)
    faqs = []
    for blob in blocks:
        try:
            d = json.loads(blob)
            if d.get("@type") == "FAQPage":
                faqs.append(d)
        except Exception:
            continue
    assert faqs, "no valid FAQPage JSON-LD found"
    q = faqs[0]["mainEntity"]
    assert len(q) > 0
    assert "Right now" in q[0]["acceptedAnswer"]["text"]

# ---- 7-day, hourly, Bakersfield comparison, evergreen lead (2026-10-29) ----------

def _full(bfl=None):
    w = _weather(63)
    w["forecast"] = [
        {"name": "This Afternoon", "is_daytime": True, "temp_f": 65, "wind_speed": "5 mph",
         "wind_dir": "NW", "short": "Mostly Sunny", "pop": 2},
        {"name": "Tonight", "is_daytime": False, "temp_f": 44, "wind_speed": "0 mph",
         "wind_dir": "W", "short": "Cloudy", "pop": None},
        {"name": "Saturday", "is_daytime": True, "temp_f": 57, "wind_speed": "5 mph",
         "wind_dir": "SSW", "short": "Light Rain", "pop": 84},
    ]
    w["hourly"] = [{"time": "4 PM", "temp_f": 63, "wind_speed": "5 mph", "wind_dir": "NW",
                    "short": "Mostly Sunny", "pop": 1}]
    src = {"tehachapi_weather": w}
    if bfl is not None:
        src["weather"] = {"forecast": bfl}
    return src


def test_lead_is_evergreen_not_a_reading(tmp_path, monkeypatch):
    # Google quotes the first text after the H1 for days; it must not be a temperature.
    raw = _render(_full(), tmp_path, monkeypatch)
    lead = re.search(r'<p class="answer">(.*?)</p>', raw, re.S).group(1)
    assert "Tehachapi weather today" in lead
    assert not re.search(r"\d+\s*°", lead)


def test_days_group_high_and_low():
    days = tehachapi_weather._days(_full()["tehachapi_weather"]["forecast"])
    assert days[0]["high"] == 65 and days[0]["low"] == 44
    assert days[1]["name"] == "Saturday" and days[1]["low"] is None


def test_days_starting_at_night():
    days = tehachapi_weather._days([
        {"name": "Tonight", "is_daytime": False, "temp_f": 40},
        {"name": "Friday", "is_daytime": True, "temp_f": 60},
        {"name": "Friday Night", "is_daytime": False, "temp_f": 42}])
    assert days[0] == {**days[0], "name": "Tonight", "high": None, "low": 40}
    assert days[1]["high"] == 60 and days[1]["low"] == 42


def test_seven_day_and_hourly_render(tmp_path, monkeypatch):
    body = _visible(_render(_full(), tmp_path, monkeypatch))
    assert "Tehachapi 7-day forecast" in body
    assert "Next 12 hours in Tehachapi" in body
    assert "84% chance of rain" in body
    assert "1% chance of rain" not in body and "2% chance of rain" not in body


def test_compare_with_bakersfield(tmp_path, monkeypatch):
    body = _visible(_render(_full({"current": 72, "high": 72, "observed": "3:45 PM"}),
                            tmp_path, monkeypatch))
    assert "63°F in Tehachapi" in body and "72°F in Bakersfield" in body
    assert "9° cooler" in body
    assert "Is Tehachapi cooler than Bakersfield?" in body


def test_compare_never_invents_bakersfield(tmp_path, monkeypatch):
    body = _visible(_render(_full(), tmp_path, monkeypatch))   # no Bakersfield data at all
    assert "side-by-side reading is unavailable" in body
    assert "in Bakersfield (KBFL" not in body
