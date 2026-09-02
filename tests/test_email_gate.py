#!/usr/bin/env python3
"""Regression tests for the email content gate (build/email_gate.py).

Every section the daily email carries must be present and non-degenerate before
it may send: weather, something good, overnight narrative, date, local
headlines, and the Flock/ALPR tracker card. These tests build a structurally
complete brief.html, then degrade ONE section at a time and assert the gate
flags exactly it — so a future section regression can never silently slip past
the send gate or the watchdog again.

Run:  .venv/Scripts/python.exe -m pytest tests/test_email_gate.py -q
Design rules (match test_kern_overnight.py): fully offline, no network.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build.email_gate import content_is_degraded  # noqa: E402

TODAY = datetime.now(ZoneInfo("America/Los_Angeles"))
ISO = TODAY.strftime("%Y-%m-%d")
HUMAN = f"{TODAY.strftime('%B')} {TODAY.day}, {TODAY.year}"

NARRATIVE = (
    "Police closed a two-block stretch of Chester Avenue downtown for three "
    "hours after a utility vault fire, officials said. Crews restored power "
    "before sunrise. A car struck a parked sedan near White Lane and Ashe "
    "Road. No injuries were reported. Authorities responded to two separate "
    "overnight calls along the 99 corridor."
)
NEWS_LINKS = (
    '<tr><td><a href="https://www.bakersfieldcalifornian.com/story-1" '
    'style="color:#232B30">City council to weigh housing plan</a>'
    '<br><span>The Californian</span></td></tr>'
)


def _full_brief() -> str:
    """A structurally complete brief.html that must pass every gate check."""
    return f"""<!DOCTYPE html><html><head><title>brief</title></head><body>

<!-- Kern Overnight card -->
<table><tr><td>
  What happened overnight: A utility vault fire shut down Chester.
  <a href="https://bakersfieldbrief.com/overnight/">Full Report</a>
  <p>{NARRATIVE}</p>
</td></tr></table>

<!-- Today's Weather card -->
<table><tr><td>Today's Weather
  <img src="https://bakersfieldbrief.com/assets/img/weather-card.jpg" width="100%">
  <p>High near 97° · low around 68. Sunny, breezy by afternoon.</p>
</td></tr></table>

<!-- Something Good card -->
<table><tr><td>Something Good
  <p>Free museum admission all weekend for Kern County residents.</p>
</td></tr></table>

<!-- Local Headlines card -->
<table><tr><td>Local Headlines
  {NEWS_LINKS}
  <p>Headlines link to the original reporting.</p>
</td></tr></table>

<!-- One Thing to Watch card -->
<table><tr><td>
  Flock &amp; ALPR Tracker
  <img src="https://bakersfieldbrief.com/assets/img/tracker-map-card.jpg">
  <p><strong>3</strong> new cameras mapped this week.
     <strong>231</strong> of <strong>260</strong> ALPR cameras in Kern County.</p>
  <p>Data as of {ISO} · refreshed from OpenStreetMap each build.</p>
</td></tr></table>

<!-- follow CTA -->
<p>{HUMAN} &middot; {ISO}</p>
</body></html>"""


@pytest.fixture
def brief(tmp_path: Path):
    """Write the full brief and return (path, degraded-html builder)."""
    p = tmp_path / "brief.html"
    p.write_text(_full_brief(), encoding="utf-8")
    return p


def _write(p: Path, html: str) -> Path:
    p.write_text(html, encoding="utf-8")
    return p


def _replace(p: Path, old: str, new: str) -> Path:
    return _write(p, p.read_text(encoding="utf-8").replace(old, new))


def test_full_brief_passes(brief):
    assert content_is_degraded(brief) == []


def test_missing_brief_file_flagged(tmp_path):
    assert content_is_degraded(tmp_path / "nope.html") == ["no rendered brief"]


# ---------------------------------------------------------------- one per section
def test_degraded_weather_flagged(brief):
    _replace(brief, "High near 97° · low around 68.", "Weather data unavailable.")
    assert "weather" in content_is_degraded(brief)


def test_missing_weather_image_flagged(brief):
    # prose present but the baked weather graphic is gone (redraw failed in
    # emailer.py drops it) => must block, never ship a degrader with a live
    # URL pointing nowhere.
    _replace(brief, '  <img src="https://bakersfieldbrief.com/assets/img/weather-card.jpg" width="100%">\n', "")
    missing = content_is_degraded(brief)
    assert "weather image" in missing


def test_degraded_something_good_flagged(brief):
    # remove the kicker so only the template comment remains
    html = brief.read_text(encoding="utf-8").replace("Something Good", "")
    _write(brief, html)
    assert "something good" in content_is_degraded(brief)


def test_degraded_overnight_narrative_flagged(brief):
    # truncate the card to headline + count + Full Report link (the 2026-09-01 bug)
    _replace(brief, f"  <p>{NARRATIVE}</p>\n", "")
    assert "overnight" in content_is_degraded(brief)


def test_degraded_date_flagged(brief):
    _write(brief, brief.read_text(encoding="utf-8").replace(HUMAN, "Jan 1, 1999").replace(ISO, "1999-01-01"))
    assert "date" in content_is_degraded(brief)


def test_degraded_headlines_flagged(brief):
    _replace(brief, NEWS_LINKS, "")
    assert "headlines" in content_is_degraded(brief)


# ---------------------------------------------------------------- the Flock/ALPR ask
def test_missing_flock_card_flagged(brief):
    # fall back to a plain agenda "One Thing to Watch" (no Flock tracker)
    html = brief.read_text(encoding="utf-8")
    html = html.replace("Flock &amp; ALPR Tracker\n  ", "One Thing to Watch\n  ")
    html = html.replace(
        '  <img src="https://bakersfieldbrief.com/assets/img/tracker-map-card.jpg">\n', "")
    html = html.replace(
        "  <p><strong>3</strong> new cameras mapped this week.\n"
        "     <strong>231</strong> of <strong>260</strong> ALPR cameras in Kern County.</p>",
        "  <p>Kern County Board of Supervisors on Tuesday.</p>")
    _write(brief, html)
    assert "flock/alpr" in content_is_degraded(brief)


def test_flock_card_with_zero_cameras_flagged(brief):
    _replace(brief, "<strong>231</strong> of <strong>260</strong>", "<strong>0</strong> of <strong>0</strong>")
    assert "flock/alpr" in content_is_degraded(brief)


def test_flock_card_without_new_camera_line_flagged(brief):
    _replace(brief, "<strong>3</strong> new cameras mapped this week.", "Tracker refreshed from OpenStreetMap.")
    assert "flock/alpr" in content_is_degraded(brief)


def test_stale_flock_card_flagged(brief):
    # present + real counts, but the "Data as of" date is old => must block
    _replace(brief, f"Data as of {ISO}", "Data as of 2026-08-11")
    assert "flock/alpr" in content_is_degraded(brief)


def test_flock_card_without_asof_date_flagged(brief):
    _replace(brief, f"  <p>Data as of {ISO} · refreshed from OpenStreetMap each build.</p>\n", "")
    assert "flock/alpr" in content_is_degraded(brief)
