#!/usr/bin/env python3
"""Regression tests for the Grapevine liveliness guarantees.

"Live" here means honestly live: (a) the page shows how old the Caltrans
report is (so nobody mistakes a stale reading for current), and (b) when the
Caltrans source is unreachable the builder renders a last-known-status fallback
clearly marked "may be out of date" instead of asserting "unavailable" or
outright lying. These guarantee the flagship /grapevine/ page never shows a
wrong status as if it were current.

Run:  .venv/Scripts/python.exe -m pytest tests/test_grapevine_liveliness.py -q
Fully offline — pure functions + a constructed stale source fixture, no network.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build.builders import grapevine  # noqa: E402


# ---------------------------------------------------------------- report age
def test_age_hint_recent():
    ago = dt.timedelta(hours=1)
    ts = _fmt(_now() - ago)
    hint = grapevine._report_age_hint(ts)
    assert "1 hr ago" in hint


def test_age_hint_just_now():
    hint = grapevine._report_age_hint(_fmt(_now()))
    assert "just now" in hint


def test_age_hint_old():
    ts = _fmt(_now() - dt.timedelta(days=2, hours=3))
    assert "2 days ago" in grapevine._report_age_hint(ts)


def test_age_hint_unparseable_is_safe():
    assert grapevine._report_age_hint("") == ""
    assert grapevine._report_age_hint("not a timestamp") == ""


def _now():
    import zoneinfo as zi
    return dt.datetime.now(zi.ZoneInfo("America/Los_Angeles"))


def _fmt(t: dt.datetime) -> str:
    # Caltrans format with ordinal day: "Saturday, September 5th, 2026 at 07:40 PM"
    o = {"1": "st", "2": "nd", "3": "rd"}.get(str(t.day)[-1], "th")
    return t.strftime("%A, %B ") + str(t.day) + o + t.strftime(", %Y at %I:%M %p")


# ---------------------------------------------------------------- stale fallback
def _stale_source(asof: str = "Wednesday, September 2nd, 2026 at 06:34 PM"):
    return {"roads": {
        "ok": False, "last_good": True, "stale": True, "log": [],
        "routes": [{
            "number": "5", "slug": "i5", "name": "Interstate 5 - Grapevine (Tejon Pass)",
            "pass": True, "status": "RESTRICTIONS", "pass_status": "RESTRICTIONS",
            "sections": [{"region": "CENTRAL CALIFORNIA",
                          "text": "The highway is open with restrictions.", "status": "RESTRICTIONS"}],
            "reported_as_of": asof, "hash": "abc",
        }],
    }}


def _render_stale(tmp_path, monkeypatch):
    """Render the grapevine page against a stale source; return the visible body."""
    import types, re
    import build.common as common
    # writes site/grapevine/index.html under the repo — use a throwaway SITE
    from pathlib import Path as P
    fake = tmp_path / "site"
    (fake / "grapevine").mkdir(parents=True)
    (fake / "assets").mkdir()
    monkeypatch.setattr(common, "SITE", fake)
    monkeypatch.setattr(common, "write", lambda p, c: P(p).write_text(c, encoding="utf-8"))
    ctx = types.SimpleNamespace(today=dt.date.today(), statusbar="", build_report={})
    grapevine.build(ctx, _stale_source())
    body = (fake / "grapevine" / "index.html").read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def test_stale_fallback_shows_warning_banner(tmp_path, monkeypatch):
    body = _render_stale(tmp_path, monkeypatch)
    assert "may be out of date" in body
    assert "roads.dot.ca.gov" in body          # direct Caltrans link
    assert "RESTRICTIONS" in body or "Restrictions" in body  # last-known status kept


def test_stale_fallback_never_says_unavailable(tmp_path, monkeypatch):
    body = _render_stale(tmp_path, monkeypatch)
    # when we HAVE last-known status, we must NOT assert it's unavailable
    assert "unavailable" not in body