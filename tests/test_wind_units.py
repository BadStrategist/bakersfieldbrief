#!/usr/bin/env python3
"""Wind unit conversion — NWS serves km/h, not m/s.

api.weather.gov returns windSpeed/windGust as {"unitCode","value"} and the
unit for every station we poll is wmoUnit:km_h-1. The old code multiplied by
the m/s->mph factor (2.23694) unconditionally, so a 18 mph pass wind rendered
as "66 mph with gusts to 91 mph" on /tehachapi-pass/ and the email weather
card. These tests pin the conversion to the unitCode that ships with the
value, and pin the source module against a realistic NWS payload.

Run:  .venv/Scripts/python.exe -m pytest tests/test_wind_units.py -q
Fully offline — no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build.common as common  # noqa: E402
from build.sources import tehachapi_weather  # noqa: E402


# ---------------------------------------------------------------- converter
def test_kmh_is_not_treated_as_mps():
    """The regression: 29.52 km/h is 18 mph, not 66."""
    assert common.wind_mph({"unitCode": "wmoUnit:km_h-1", "value": 29.52}) == 18


def test_kmh_gust():
    assert common.wind_mph({"unitCode": "wmoUnit:km_h-1", "value": 40.68}) == 25


def test_mps_still_converts_correctly():
    assert common.wind_mph({"unitCode": "wmoUnit:m_s-1", "value": 10}) == 22


def test_mph_passthrough():
    assert common.wind_mph({"unitCode": "wmoUnit:mi_h-1", "value": 18}) == 18


def test_knots():
    assert common.wind_mph({"unitCode": "wmoUnit:kt", "value": 20}) == 23


def test_null_reading_is_none_not_zero():
    """NWS sends value:null with qualityControl 'Z' — must stay absent."""
    assert common.wind_mph({"unitCode": "wmoUnit:km_h-1", "value": None}) is None
    assert common.wind_mph(None) is None
    assert common.wind_mph({}) is None


def test_unknown_unit_falls_back_to_kmh_not_mps():
    """Unknown/missing unitCode must not silently inflate by 3.6x."""
    assert common.wind_mph({"value": 29.52}) == 18


# ---------------------------------------------------------------- source module
def _obs(**over):
    p = {
        "timestamp": "2026-09-11T19:55:00+00:00",
        "temperature": {"unitCode": "wmoUnit:degC", "value": 30},
        "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 29.52},
        "windGust": {"unitCode": "wmoUnit:km_h-1", "value": 40.68},
        "windDirection": {"unitCode": "wmoUnit:degree_(angle)", "value": 320},
        "textDescription": "Clear",
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 22},
    }
    p.update(over)
    return {"properties": p}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def test_ktsp_source_reports_real_wind(monkeypatch):
    monkeypatch.setattr(common, "fetch", lambda *a, **k: _Resp(_obs()))
    cur = tehachapi_weather._current()
    assert cur["station"] == "KTSP"
    assert cur["temperature"] == 86
    assert cur["wind_mph"] == 18          # was 66
    assert cur["gust_mph"] == 25          # was 91
    assert cur["wind_dir"] == "NW"


def test_ktsp_missing_gust_omits_the_key(monkeypatch):
    """No gust reported -> no 'gusts to ...' claim on the page."""
    payload = _obs(windGust={"unitCode": "wmoUnit:km_h-1", "value": None})
    monkeypatch.setattr(common, "fetch", lambda *a, **k: _Resp(payload))
    cur = tehachapi_weather._current()
    assert cur["wind_mph"] == 18
    assert "gust_mph" not in cur
