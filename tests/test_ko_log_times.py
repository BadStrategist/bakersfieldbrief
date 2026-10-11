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


class TestLogIsEveryIncidentNotToldAsAParagraph:
    """The log is a partition of the night, not a notability cut.

    A notability-3 row that misses the eight 'Around the county' slots used to
    appear nowhere on the page: render_log_section took notability 2 only, so the
    2026-10-10 page was whole only because the 07:30 agent logged six of them by
    hand, against its own step 4.
    """

    INCS = [
        {"time": "19:10", "notability": 4, "type": "the big one",
         "area": "Bakersfield", "summary": "The lead incident."},
        {"time": "20:20", "notability": 3, "type": "third", "area": "",
         "summary": "Told as a paragraph."},
        {"time": "21:30", "notability": 3, "type": "fourth", "area": "",
         "summary": "Also a paragraph."},
        {"time": "22:06", "notability": 2, "type": "stolen vehicle",
         "area": "Baker Street", "summary": "A stolen vehicle was reported."},
        {"time": "22:06", "notability": 2, "type": "vehicle stop",
         "area": "", "summary": "A vehicle stop on the app feed."},
        {"time": "23:40", "notability": 1, "type": "extra patrol",
         "area": "", "summary": "An extra patrol was requested."},
    ]

    def test_paragraphs_and_rows_partition_the_night(self):
        from kern_overnight.write import (incident_key, log_rows,
                                          paragraph_incidents, log_lines,
                                          render_log_section)
        told = paragraph_incidents(self.INCS)
        rows = log_rows(self.INCS, skip=told)
        body = "# T\n\nOpening.\n\n## Night notes\n\nNotes.\n"
        out = render_log_section(self.INCS, skip=told)
        assert len(told) + len(rows) == len(self.INCS)
        assert len(log_lines(out)) == len(rows)
        # every non-paragraph incident is a row, in night order
        assert [r.split("**")[1] for r in rows] == \
            ["10:06 p.m.", "10:06 p.m.", "11:40 p.m."]
        # the two 22:06 rows are different incidents and both survive
        assert incident_key(self.INCS[3]) != incident_key(self.INCS[4])
        again = log_rows(self.INCS, skip=paragraph_incidents(self.INCS))
        assert again == rows
        assert body  # keeps the linter honest about the unused local

    def test_insert_log_lines_keeps_the_writers_lines(self):
        from kern_overnight.write import insert_log_lines, log_lines, log_rows, \
            paragraph_incidents
        # the writer's body: one row, in its own shape, plus a 22:06 row
        body = ("# T\n\nOpening.\n\n## The log\n\n"
                "- **10:06 p.m.**: a stolen vehicle was reported.\n\n"
                "## Night notes\n\nNotes.\n")
        rows = log_rows(self.INCS, skip=paragraph_incidents(self.INCS))
        out, added = insert_log_lines(body, rows)
        assert added == 2                      # the second 22:06 row and 11:40
        kept = log_lines(out)
        assert len(kept) == 3
        assert "a stolen vehicle was reported" in kept[0]   # writer's line intact
        assert kept[0].startswith("- **10:06 p.m.**:")
        # night order holds across the insert
        times = [r.split("**")[1] for r in kept]
        assert times == ["10:06 p.m.", "10:06 p.m.", "11:40 p.m."]

    def test_insert_log_lines_is_idempotent(self):
        from kern_overnight.write import insert_log_lines, log_rows, \
            paragraph_incidents, render_log_section
        rows = log_rows(self.INCS, skip=paragraph_incidents(self.INCS))
        body = "# T\n\nOpening.\n\n" + render_log_section(
            self.INCS, skip=paragraph_incidents(self.INCS)) + "## Night notes\n\nN.\n"
        out, added = insert_log_lines(body, rows)
        assert added == 0 and out == body

    def test_insert_log_lines_sorts_and_drops_nothing(self):
        """An inserted row lands in night order and no line is cut to make
        room. There was a 40-row cap here, and before that the cut ran ahead
        of the sort, so an inserted 7 p.m. row was the one dropped."""
        from kern_overnight.write import insert_log_lines, log_lines
        body = ("# T\n\n## The log\n\n"
                "- **5:10 a.m.** — Alarm on Oak Street was checked.\n"
                "- **6:10 a.m.** — Alarm on Elm Street was checked.\n\n"
                "## Night notes\n\nN.\n")
        out, added = insert_log_lines(
            body, ["- **7:15 p.m.** — Fight reported near Jefferson Park."])
        assert added == 1
        assert [r.split("**")[1] for r in log_lines(out)] == \
            ["7:15 p.m.", "5:10 a.m.", "6:10 a.m."]

    def test_a_busy_night_logs_every_row(self):
        """121 app rows came in on 2026-10-10. The log used to stop at 40 and
        say so only on stdout, while the docstring promised every incident."""
        from kern_overnight.write import (insert_log_lines, log_lines, log_rows,
                                          paragraph_incidents, render_log_section)
        night = [{"time": f"{19 + n // 60:02d}:{n % 60:02d}", "notability": 2,
                  "type": "alarm", "area": "",
                  "summary": f"Alarm number {n} was checked at a business."}
                 for n in range(130)]
        told = paragraph_incidents(night)
        rows = log_rows(night, skip=told)
        assert len(told) + len(rows) == len(night) == 130
        assert len(log_lines(render_log_section(night, skip=told))) == 130
        out, added = insert_log_lines("# T\n\n## Night notes\n\nN.\n", rows)
        assert added == 130 and len(log_lines(out)) == 130


class TestToldPicks:
    """paragraph_incidents() is what the writer was asked to tell. The log used
    to skip all of it unchecked, so a pick the writer left out was in neither
    the prose nor the log."""
    PICKS = [
        {"time": "01:12", "notability": 4, "type": "structure fire",
         "area": "Niles Street", "summary": "Crews fought a garage fire that "
         "spread to a fence on Niles Street."},
        {"time": "02:40", "notability": 3, "type": "pursuit",
         "area": "Union Avenue", "summary": "A stolen pickup was chased down "
         "Union Avenue until it stopped at a canal."},
        {"time": "03:05", "notability": 3, "type": "missing person",
         "area": "", "summary": "A family reported a teenager missing from a "
         "campground near the river."},
    ]
    BODY = ("# The Kern Overnight — October 10, 2026\n\n"
            "A garage fire and a chase down Union Avenue led a busy night, and "
            "a teenager was reported missing from a campground.\n\n"
            "## The big one\n\n"
            "Crews were sent at 1:12 a.m. to a garage fire on Niles Street. "
            "A caller reported it had spread to a fence.\n\n"
            "## Around the county\n\n"
            "A stolen pickup was chased down Union Avenue and stopped at a "
            "canal, units reported.\n\n"
            "## Night notes\n\nThe teenager missing from the campground near "
            "the river was the night's open thread.\n")

    def test_a_skipped_pick_is_logged(self):
        from kern_overnight.write import (_insert_log, log_lines,
                                          render_log_section, told_incidents)
        told = told_incidents(self.BODY, self.PICKS)
        # the missing teenager is named in the opening and in the notes, and
        # told in neither: only a paragraph under a section is a telling
        assert [i["time"] for i in told] == ["01:12", "02:40"]
        out = _insert_log(self.BODY, render_log_section(self.PICKS, skip=told))
        rows = log_lines(out)
        assert len(rows) == 1 and rows[0].startswith("- **3:05 a.m.**")
        assert "teenager missing" in rows[0]

    def test_a_writer_that_tells_nothing_logs_everything(self):
        from kern_overnight.write import told_incidents
        assert told_incidents("# T\n\nA quiet night.\n\n## Night notes\n\nN.\n",
                              self.PICKS) == []

    def test_write_brief_logs_the_pick_the_writer_dropped(self, monkeypatch, capsys):
        import datetime as dt
        from kern_overnight import write
        monkeypatch.setattr(write.llm, "chat_text", lambda *a, **k: self.BODY)
        out = write.write_brief(self.PICKS, dt.date(2026, 10, 10))
        rows = write.log_lines(out)
        assert [r.split("**")[1] for r in rows] == ["3:05 a.m."]
        assert "pick not told as a paragraph" in capsys.readouterr().out


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