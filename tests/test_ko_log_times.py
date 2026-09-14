#!/usr/bin/env python3
"""'## The log' on the overnight page must show each incident's TIME and read
in the order the night actually happened.

Regression guard: the log used to be written by the LLM, which never kept the
requested ``**HH:MM** — {type}, {area}.`` format. Times came back buried in the
prose ("Deputies were sent at 12:02 a.m.") and the entries were grouped by
notability, so a night ran 12:02a, 12:01a, 1:02a, 3:55a, 11:06p, 10:15p … The
section is now built in code from ``incidents/<date>.json``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "data" / "overnight_reports"
TIME_RE = re.compile(r"^-\s+\*\*(\d{1,2}:\d{2} [ap]\.m\.)\*\*", re.M)


def night_key(display: str) -> int:
    """Display time -> minutes since noon (night order across midnight)."""
    m = re.match(r"(\d{1,2}):(\d{2}) ([ap])\.m\.", display)
    h, mi, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3)
    if ap == "p":
        h += 12
    return ((h - 12) % 24) * 60 + mi


def log_bullets(md_text: str) -> str:
    m = re.search(r"^##[ \t]*The log[ \t]*$(.*?)(?=^##[ \t]|\Z)",
                  md_text, re.S | re.M)
    assert m, "report has no '## The log' section"
    return m.group(1)


class TestRenderLogSection:
    def test_time_first_and_chronological(self):
        from kern_overnight.write import render_log_section
        incs = [
            {"time": "01:44", "notability": 2, "type": "welfare check",
             "area": "Main Street block, Maricopa", "summary": "A deputy checked."},
            {"time": "22:15", "notability": 2, "type": "armed robbery investigation",
             "area": "Bakersfield", "summary": "A caller reported a robbery."},
            {"time": "23:01", "notability": 2, "type": "disturbance",
             "area": "Bakersfield", "summary": "Officers were sent."},
        ]
        out = render_log_section(incs)
        times = TIME_RE.findall(out)
        # 10:15 p.m. -> 11:01 p.m. -> 1:44 a.m. (across midnight, in order)
        assert times == ["10:15 p.m.", "11:01 p.m.", "1:44 a.m."]
        assert out.startswith("## The log")
        assert len(re.findall(r"^-\s", out, re.M)) == 3

    def test_notability_2_only_then_fallback(self):
        from kern_overnight.write import render_log_section
        assert render_log_section([]) == ""
        only_big = [{"time": "02:00", "notability": 4, "type": "fire",
                     "area": "Oildale", "summary": "Crews worked a fire."}]
        assert "2:00 a.m." in render_log_section(only_big)

    def test_bad_time_never_crashes(self):
        from kern_overnight.write import render_log_section, night_key
        assert night_key("bogus") == 24 * 60
        assert night_key("99:99") == 24 * 60
        out = render_log_section([{"time": "bogus", "notability": 2,
                                   "type": "call", "area": "Bakersfield",
                                   "summary": "Something happened."}])
        assert "Time not logged" in out

    def test_long_summary_cuts_at_word_boundary(self):
        from kern_overnight.write import _one_line
        got = _one_line("word " * 200)
        assert got.endswith("…") and not got.endswith("wor…")


class TestInsertLog:
    def test_replaces_llm_written_log(self):
        """An LLM '## The log' (no times) must be swapped, not duplicated."""
        from kern_overnight.write import _insert_log, render_log_section
        body = ("# The Kern Overnight — September 14, 2026\n\n"
                "Opening.\n\n"
                "## The log\n\n- Someone reported a thing at 11:06 p.m.\n\n"
                "## Night notes\n\nQuiet night.\n")
        incs = [{"time": "23:06", "notability": 2, "type": "theft report",
                 "area": "Ming Avenue block", "summary": "A theft was reported."}]
        out = _insert_log(body, render_log_section(incs))
        assert out.count("## The log") == 1
        assert "11:06 p.m." in out
        assert "Someone reported a thing" not in out        # LLM line replaced
        assert out.index("## The log") < out.index("## Night notes")

    def test_inserts_when_llm_omits_section(self):
        from kern_overnight.write import _insert_log
        body = "# T\n\nOpening.\n\n## Night notes\n\nNotes.\n"
        out = _insert_log(body, "## The log\n\n- **1:00 a.m.** — x.\n")
        assert out.count("## The log") == 1
        assert out.index("## The log") < out.index("## Night notes")


class TestPublishedReports:
    """Every shipped report — the archive the site renders — must comply."""

    def test_every_report_is_time_first_and_in_order(self):
        files = sorted(REPORTS.glob("*.md"))
        assert len(files) >= 10, "no published reports found"
        for f in files:
            body = log_bullets(f.read_text(encoding="utf-8"))
            bullets = len(re.findall(r"^-\s", body, re.M))
            times = TIME_RE.findall(body)
            assert times, f"{f.stem}: no log entry starts with a time"
            assert len(times) == bullets, \
                f"{f.stem}: {bullets - len(times)} log entries without a time"
            keys = [night_key(t) for t in times]
            assert keys == sorted(keys), f"{f.stem}: log out of order {times}"