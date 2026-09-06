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