#!/usr/bin/env python3
"""Regression guards for the Kern Overnight stage-3/4 breaks fixed 2026-09-10.

Each test here pins a defect that made the DOCUMENTED pipeline fail outright, so
it cannot silently come back:

  * run.py stage 3 passed two Path objects to extract(), which takes digest ROWS
    -> "TypeError: 'WindowsPath' object is not iterable" on every full run.
  * write.py formatted its prompt date with the glibc-only '%-d' directive
    -> "ValueError: Invalid format string" on Windows, killing stage 4.
  * extract.py had no __main__ although the README documents
    `python -m kern_overnight.extract <date>` as stage 3.
  * the mandatory "Audio Provided by Broadcastify." credit documented as
    un-omittable was not actually emitted.

Offline only — no network, no LLM calls.
"""
from __future__ import annotations

import datetime as dt
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kern_overnight import extract as ko_extract  # noqa: E402
from kern_overnight import write as ko_write      # noqa: E402


def test_long_date_is_portable_and_correct():
    """No '%-d': that directive raises ValueError on Windows (the pipeline host)."""
    s = ko_write._fmt_date_long(dt.date(2026, 9, 10))
    assert s == "Thursday, September 10, 2026", s


def test_long_date_has_no_padded_day():
    """A single-digit day must render as '1', never '01'."""
    assert ko_write._fmt_date_long(dt.date(2026, 8, 1)) == "Saturday, August 1, 2026"


def test_no_percent_dash_directive_in_pipeline_sources():
    """Guard the whole package, not just the one call site that was wrong.
    Only real strftime() CALLS count — a comment explaining the pitfall is fine."""
    offenders = []
    for py in (ROOT / "kern_overnight").rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "strftime(" in line and ("%-d" in line or "%-m" in line):
                offenders.append(f"{py.name}:{i}: {line.strip()}")
    assert not offenders, f"glibc-only strftime directive found: {offenders}"


def test_write_brief_prompt_builds_without_crashing(monkeypatch):
    """write_brief() must get past its date formatting on this platform.
    llm.chat_text(prompt, system, ...) — prompt is the FIRST positional arg."""
    captured = {}

    def fake_chat_text(prompt, system, **kw):
        captured["prompt"] = prompt
        return "# The Kern Overnight — stub\n\nbody"

    monkeypatch.setattr(ko_write.llm, "chat_text", fake_chat_text, raising=False)
    out = ko_write.write_brief(
        [{"type": "Traffic Collision", "area": "Bakersfield", "notability": 4,
          "summary": "Crews were sent to a two-car collision."}],
        dt.date(2026, 9, 10))
    assert "The Kern Overnight" in out
    assert "September 10, 2026" in captured["prompt"]
    # the publisher appends the footer, so the LLM is told not to write one
    assert "Do not include a footer" in captured["prompt"]
    assert out.rstrip().endswith("Audio Provided by Broadcastify.")


def test_footer_carries_mandatory_attribution():
    assert "Audio Provided by Broadcastify." in ko_write.FOOTER
    assert "preliminary" in ko_write.FOOTER


def test_extract_takes_rows_not_paths():
    """The signature run.py must match: a row list, and streets as the 2nd arg."""
    sig = inspect.signature(ko_extract.extract)
    params = list(sig.parameters.values())
    assert params[0].name == "rows"
    assert "list" in str(params[0].annotation)


def test_extract_rejects_path_arguments():
    """The exact crash: Paths are not iterable, so this must raise TypeError."""
    import pytest
    with pytest.raises(TypeError):
        ko_extract.extract(Path("transcripts/x.jsonl"), Path("incidents/x.json"))


def test_run_stage3_call_site_passes_rows(monkeypatch):
    """run.main() stage 3 must feed extract() rows, never Paths."""
    from kern_overnight import run as ko_run

    seen = {}

    def fake_extract(rows, *a, **kw):
        seen["arg"] = rows
        return []

    monkeypatch.setattr(ko_run.ko_extract, "extract", fake_extract)
    monkeypatch.setattr(ko_run, "_usable_rows", lambda p: [{"text": "x" * 40}])
    src = (ROOT / "kern_overnight" / "run.py").read_text(encoding="utf-8")
    assert re.search(r"ko_extract\.extract\(\s*_usable_rows\(", src), \
        "run.py stage 3 must call ko_extract.extract(_usable_rows(transcript))"


def test_extract_module_has_main_block():
    """README documents `python -m kern_overnight.extract <date>`."""
    src = (ROOT / "kern_overnight" / "extract.py").read_text(encoding="utf-8")
    assert '__name__ == "__main__"' in src
