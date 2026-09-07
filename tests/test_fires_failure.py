#!/usr/bin/env python3
"""Regression tests for the /fires/ tracker — the failure branch must NEVER
present a fabricated "0 active" / "no fires" when the CAL FIRE source is down.

This mirrors the surveillance-map failure-branch rule: on a source failure,
render an honest "CAL FIRE data source did not load this build" message (with
last-known asof if a snapshot exists), never a false negative.
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
    (fake / "fires").mkdir(parents=True)
    (fake / "assets").mkdir()
    orig_site = common.SITE
    common.SITE = fake
    try:
        ctx = types.SimpleNamespace(today=dt.date.today(), statusbar="", build_report={})
        trackers.build_fires(ctx, sources)
    finally:
        common.SITE = orig_site
    return (fake / "fires" / "index.html").read_text(encoding="utf-8")


def _visible(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))


def _ok_fires():
    return {"ok": True, "asof": "2026-09-07",
            "incidents": [{"name": "Creek Fire", "county": "Fresno", "acres": "1200",
                           "contained": "45", "type": "Wildfire"}],
            "kern": [{"name": "Valley Fire", "county": "Kern", "acres": "300",
                      "contained": "10", "type": "Wildfire"}]}


def _fail_fires():
    return {"ok": False, "error": "Timeout: ..."}


def test_fail_branch_never_says_zero_active(tmp_path, monkeypatch):
    """On a CAL FIRE failure, the page must NOT claim '0 active' / 'no fires'."""
    body = _visible(_render({"calfire": _fail_fires()}, tmp_path, monkeypatch))
    assert "did not load this build" in body
    assert "No active fires in Kern County" not in body
    assert "0 active in Kern" not in body
    assert "reports 0 active fires" not in body


def test_fail_branch_with_last_known_shows_snapshot(tmp_path, monkeypatch):
    """When a last-known snapshot exists, the failure branch surfaces it with
    its asof instead of a bare empty state."""
    last = _ok_fires()
    src = {"ok": False, "error": "Timeout: ...", "last": last}
    body = _visible(_render({"calfire": src}, tmp_path, monkeypatch))
    assert "did not load this build" in body
    # last-known data is surfaced (Valley Fire) under a last-known label
    assert "Valley Fire" in body
    assert "last-known" in body.lower()


def test_fail_branch_faq_is_honest(tmp_path, monkeypatch):
    """The FAQPage schema answer must not assert a live '0 fires' count on
    failure — it must say the feed could not be reached. The fires FAQ is
    JSON-LD schema (not visible text), so assert against the raw HTML."""
    raw = _render({"calfire": _fail_fires()}, tmp_path, monkeypatch)
    assert "could not be reached" in raw
    assert "reports 0 active" not in raw


def test_ok_branch_still_shows_real_counts(tmp_path, monkeypatch):
    """Sanity: the ok branch keeps showing real incident counts."""
    body = _visible(_render({"calfire": _ok_fires()}, tmp_path, monkeypatch))
    assert "1" in body          # 1 active fire in Kern
    assert "Valley Fire" in body
    assert "did not load this build" not in body
