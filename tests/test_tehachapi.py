#!/usr/bin/env python3
"""Regression tests for the Tehachapi Pass page (/tehachapi-pass/).

The page is the second pass in the site's proven live-tracker formula: direct
quotable answer scoped honestly to "SR-58 reported X (Central California area)"
(SR-58 Caltrans text is area-wide, NOT pass-specific), live wind from the NWS
station, and a last-known stale fallback that never asserts unavailable when we
DO have last-known status — and never overclaims "pass is OPEN" from area text.

Run:  .venv/Scripts/python.exe -m pytest tests/test_tehachapi.py -q
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

from build.builders import tehachapi  # noqa: E402
import build.common as common  # noqa: E402


def _sr58(ok=True, stale=False, status="OPEN", asof="Saturday, September 5th, 2026 at 08:10 PM"):
    routes = [{
        "number": "58", "slug": "sr58", "name": "State Route 58 - Tehachapi",
        "pass": False, "status": status, "pass_status": status,
        "sections": [{"region": "CENTRAL CALIFORNIA",
                      "text": "No traffic restrictions reported." if status == "OPEN" else "restrictions",
                      "status": status}],
        "reported_as_of": asof, "hash": "abc",
    }]
    if ok and not stale:
        return {"ok": True, "routes": routes, "asof": "2026-09-05", "log": []}
    if stale:
        # the stale fallback path: ok MUST be False (else the builder sees a
        # live source and correctly shows no banner)
        return {"ok": False, "last_good": True, "stale": True, "log": [],
                "routes": routes, "asof": "2026-09-02"}
    return {"ok": False, "routes": [], "error": "no routes"}


def _weather(wind=29, ok=True):
    return {"ok": True, "current": {
        "ok": ok, "station": "KTSP", "temperature": 68,
        "wind_mph": wind, "wind_dir": "W", "condition": "Clear",
        "observed": "Sep 05, 07:35 PM",
    }, "forecast": [{
        "name": "Tonight", "is_daytime": False, "temp_f": 55,
        "wind_speed": "0 to 5 mph", "wind_dir": "W", "short": "Mostly Clear",
        "starts": "2026-09-05",
    }], "alerts": [], "asof": "2026-09-05"}


def _render(sources, tmp_path, monkeypatch):
    """Build the page into a real temp SITE dir. Returns raw HTML."""
    import types
    fake = Path(tempfile.mkdtemp()) / "site"
    (fake / "tehachapi-pass").mkdir(parents=True)
    (fake / "assets").mkdir()
    orig_site = common.SITE
    common.SITE = fake
    try:
        ctx = types.SimpleNamespace(today=dt.date.today(), statusbar="", build_report={})
        tehachapi.build(ctx, sources)
    finally:
        common.SITE = orig_site
    return (fake / "tehachapi-pass" / "index.html").read_text(encoding="utf-8")


def _visible(raw: str) -> str:
    """Strip scripts + tags for visible-text assertions."""
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))


# ---------------------------------------------------------------- honesty: area-scoped wording
def test_no_bare_pass_overclaim(tmp_path, monkeypatch):
    """SR-58 text is area-wide; we must NOT claim 'Tehachapi Pass is OPEN' as a bare fact."""
    body = _visible(_render({"roads": _sr58(), "tehachapi_weather": _weather()}, tmp_path, monkeypatch))
    assert "SR-58 is reported Open" in body
    assert "Tehachapi Pass is Open" not in body
    assert "Central California area" in body


def test_direct_answer_carries_live_status(tmp_path, monkeypatch):
    body = _visible(_render({"roads": _sr58(), "tehachapi_weather": _weather()}, tmp_path, monkeypatch))
    assert "SR-58 is reported" in body
    assert "Saturday, September 5th, 2026 at 08:10 PM" in body


# ---------------------------------------------------------------- wind card
def test_wind_card_uses_ktsp(tmp_path, monkeypatch):
    body = _visible(_render({"roads": _sr58(), "tehachapi_weather": _weather(wind=29)}, tmp_path, monkeypatch))
    assert "Current conditions at the pass" in body
    assert "29 mph" in body
    assert "KTSP" in body


def test_no_wind_fabrication_when_ktsp_down(tmp_path, monkeypatch):
    body = _visible(_render({"roads": _sr58(), "tehachapi_weather": _weather(ok=False)}, tmp_path, monkeypatch))
    assert "unavailable this build" in body


# ---------------------------------------------------------------- stale fallback
def test_stale_fallback_shows_banner_and_keeps_status(tmp_path, monkeypatch):
    sources = {"roads": _sr58(ok=False, stale=True, status="RESTRICTIONS",
                              asof="Wednesday, September 2nd, 2026 at 06:34 PM"),
               "tehachapi_weather": _weather()}
    body = _visible(_render(sources, tmp_path, monkeypatch))
    assert "may be out of date" in body       # last-known banner KEPT
    assert "roads.dot.ca.gov" in body         # direct Caltrans link
    assert "Restrictions" in body             # last-known status word KEPT


def test_stale_fallback_does_not_say_unavailable(tmp_path, monkeypatch):
    sources = {"roads": _sr58(ok=False, stale=True), "tehachapi_weather": _weather()}
    body = _visible(_render(sources, tmp_path, monkeypatch))
    assert "unavailable" not in body


# ---------------------------------------------------------------- no-data → no bare claim
def test_no_status_word_when_no_road_data(tmp_path, monkeypatch):
    sources = {"roads": _sr58(ok=False, stale=False), "tehachapi_weather": _weather()}
    body = _visible(_render(sources, tmp_path, monkeypatch))
    assert "SR-58 conditions are unavailable this build" in body
    # must NOT render a bare "is Open"/"is Closed" claim with no data
    assert "SR-58 is reported" not in body


# ---------------------------------------------------------------- crosslink + phone
def test_alt_routes_and_links_present(tmp_path, monkeypatch):
    body = _visible(_render({"roads": _sr58(), "tehachapi_weather": _weather()}, tmp_path, monkeypatch))
    assert "grapevine" in body.lower()          # crosslink to the grapevine alternative
    assert "1-800-427-7623" in body             # Caltrans phone
    assert "roads.dot.ca.gov" in body


def test_know_before_you_go_block_present(tmp_path, monkeypatch):
    body = _visible(_render({"roads": _sr58(), "tehachapi_weather": _weather()}, tmp_path, monkeypatch))
    assert "Know before you go" in body
    assert "4,067" in body                       # elevation
    assert "R2" in body and "R3" in body          # chain controls
    assert "QuickMap" in body                     # live camera link