#!/usr/bin/env python3
"""Regression guards for the 2026-09-11 email defects.

Both bugs shipped to every subscriber silently, so pin them here.

  1. The overnight narrative was cut mid-sentence ("...moving at the time. The
     rest of") because the emailer stripped everything from the first plain
     substring "the log" — meant to remove a trailing "## The log" SECTION, it
     also matched ordinary prose ("The rest of the log leaned on disturbances").
  2. The text email printed a dangling "ONE THING TO WATCH" heading with nothing
     under it whenever the Flock/ALPR card replaced the watch item.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build.emailer import strip_log_section  # noqa: E402


PROSE = (
    "An officer working the Olive Drive overpass also called for a tow after a "
    "bicyclist was involved in a collision there, with eastbound traffic moving "
    "at the time.\n\nThe rest of the log leaned on disturbances and welfare "
    "checks, with a string of domestic-related calls spread across the county."
)


def test_prose_containing_the_log_is_not_truncated():
    """The exact 2026-09-11 shape: 'the log' inside a sentence must survive."""
    out = strip_log_section(PROSE)
    assert out == PROSE
    assert "The rest of the log leaned on" in out
    assert out.rstrip().endswith("across the county."), out[-60:]


def test_the_overnight_log_phrasing_is_not_treated_as_a_section():
    """'the overnight log' has no contiguous 'the log' — must never be cut."""
    t = "The rest of the overnight log was a mix of the usual calls overnight."
    assert strip_log_section(t) == t


def test_real_markdown_log_section_is_still_stripped():
    t = ("Crews handled a quiet night across the county.\n\n"
         "## The log\n\n- 01:12 Traffic stop, Rosedale\n- 01:40 Welfare check")
    out = strip_log_section(t)
    assert out == "Crews handled a quiet night across the county."
    assert "Traffic stop" not in out


def test_line_initial_log_marker_is_stripped():
    t = "A quiet night overall.\nThe log:\n- 02:00 Disturbance, Oildale"
    assert strip_log_section(t) == "A quiet night overall."


def test_bold_log_heading_is_stripped():
    t = "Brisk overnight pace.\n\n**The log**\n\n- 03:10 Fire, East Bakersfield"
    assert strip_log_section(t) == "Brisk overnight pace."


def test_no_marker_is_a_noop():
    t = "Nothing notable happened overnight in the county."
    assert strip_log_section(t) == t


def test_empty_input_is_safe():
    assert strip_log_section("") == ""
    assert strip_log_section(None) == ""


def test_text_email_has_no_empty_watch_section(tmp_path, monkeypatch):
    """The txt renderer must not emit the heading without content.

    Renders nothing here (no live sources); asserts on the template shape so the
    dangling-heading regression cannot come back.
    """
    import re as _re
    src = (ROOT / "build" / "emailer.py").read_text(encoding="utf-8")
    assert "{watch_block}Web: {BASE_URL}/" in src, "txt template lost its watch block"
    assert not _re.search(r"^ONE THING TO WATCH$", src, _re.M), (
        "the text template hardcodes an unconditional ONE THING TO WATCH heading")
