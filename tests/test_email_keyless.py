#!/usr/bin/env python3
"""Regression tests for the keyless email fallback (build/emailer.py).

On 2026-09-05 the daily email did NOT send because the LLM brief body
(data/briefs/<date>.json) was never written after a timeout, so the email's
overnight/weather/something-good prose all rendered empty and the content gate
correctly blocked the send. The structural fix (2026-09-05): when those prose
sections are empty, render_brief fills them from deterministic real data (the
published overnight report, the live forecast, real headlines/events) — so an
LLM outage degrades prose QUALITY, never section PRESENCE.

These tests exercise the pure builders and the _fill_keyless_prose merge.

Run:  .venv/Scripts/python.exe -m pytest tests/test_email_keyless.py -q
Fully offline — only committed data + constructed fixtures, no network.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import emailer  # noqa: E402

TODAY = dt.date(2026, 9, 5)  # the incident date (fixed, not "now")


# ---------------------------------------------------------------- weather
def test_keyless_weather_has_temperature_reading():
    weather = {"forecast": {"high": 82, "low": 60, "current": 81}}
    text = emailer._keyless_weather(weather, {"ok": True, "aqi": 62, "category": "Moderate"}, {})
    assert "82" in text and "60" in text
    # must carry a real temp symbol so the email gate's has_temp passes
    assert "°" in text


def test_keyless_weather_handles_empty_forecast():
    text = emailer._keyless_weather({}, {}, {})
    assert text.strip()  # never empty; graceful prose
    assert "No active weather alerts" in text


def test_keyless_weather_mentions_fires_when_present():
    calfire = {"incidents": [{"county": "Kern", "name": "Pozo Creek Fire"}]}
    text = emailer._keyless_weather({}, {}, calfire)
    assert "Pozo Creek" in text and "1 active fire" in text


# ---------------------------------------------------------------- something good
def test_keyless_good_picks_a_positive_headline():
    headlines = [
        {"title": "City council approves budget", "source": "KGET 17"},
        {"title": "Bakersfield library wins national award for literacy program",
         "source": "23ABC"},
    ]
    text = emailer._keyless_good(headlines, [], TODAY)
    assert "award" in text.lower()
    assert text.strip()


def test_keyless_good_picks_family_event_first():
    events = [{"name": "Family Fun Festival", "venue": "Hart Park",
               "when": "2026-09-06"}]
    text = emailer._keyless_good([], events, TODAY)
    assert "Family Fun Festival" in text


def test_keyless_good_empty_when_no_uplift():
    headlines = [{"title": "Semi rollover closes Highway 99", "source": "KGET"}]
    assert emailer._keyless_good(headlines, [], TODAY).strip() == ""


# ---------------------------------------------------------------- overnight
def test_keyless_overnight_reads_published_report():
    # today's real published KO report is in the repo
    text = emailer._keyless_overnight(TODAY, {"headline": "x", "count": 1})
    assert len(text) >= 150
    assert text.count(". ") >= 3
    assert "Airport" in text  # real narrative, not boilerplate


def test_keyless_overnight_falls_back_to_summary_when_no_report(tmp_path, monkeypatch):
    monkeypatch.setattr(emailer, "_read_overnight_report", lambda today: "")
    ko = {"headline": "Pursuit on Airport Dr", "count": 12}
    text = emailer._keyless_overnight(TODAY, ko)
    assert "Pursuit on Airport Dr" in text
    assert "12 incidents" in text


# ---------------------------------------------------------------- merge
def test_fill_keyless_prose_only_fills_empty_keys():
    weather = {"forecast": {"high": 82, "low": 60, "current": 81}}
    sources = {"weather": weather, "airnow": {"ok": True, "aqi": 62},
               "calfire": {}, "news_rss": {"headlines": [
                   {"title": "Library wins award", "source": "23ABC"}]},
               "venues": {"events": []}}
    # LLM overnight present; weather + something-good empty -> only those filled
    sections = {"overnight": "LLM wrote this.", "weather": "", "something_good": ""}
    emailer._fill_keyless_prose(sections, sources, TODAY, {"headline": "x", "count": 1})
    assert sections["overnight"] == "LLM wrote this."  # untouched
    assert "82" in sections["weather"]                 # filled
    assert sections["something_good"].strip()          # filled
