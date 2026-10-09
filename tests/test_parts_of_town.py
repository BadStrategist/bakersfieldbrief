#!/usr/bin/env python3
"""Guard: a part of town in the report comes from the street table, never from
the writer's guess.

Pins the live defect of 2026-10-09: the lead item read "Two shot on Pembroke
Avenue in southwest Bakersfield". The 5400 block of Pembroke Avenue is north of
the Kern River, just off Olive Drive (City of Bakersfield Streets layer:
35.4113, -119.0639). The incident data never said "southwest".
"""
import json
from pathlib import Path

import pytest

from kern_overnight import regions as R

REPORT_2026_10_09 = (
    "A shooting in southwest Bakersfield sent two people to the hospital with "
    "gunshot wounds, drawing a large response to a block on Pembroke Avenue "
    "just after 1 a.m. Deputies in the same hour worked a knife attack on "
    "Lincoln Street.\n\n## The big one\n\n**Two shot on Pembroke Avenue in "
    "southwest Bakersfield**: Just after 1:20 a.m., officers were sent to a "
    "residence in the 5400 block of Pembroke Avenue.\n")
INCIDENTS = [{"area": "the 5400 block of Pembroke Avenue"},
             {"area": "the 1500 block of Lincoln Street"}]


@pytest.mark.parametrize("area,phrase", [
    ("the 5400 block of Pembroke Avenue", "north Bakersfield"),
    ("5400 Pembroke Ave", "north Bakersfield"),
    ("the 7500 block of Pembroke Avenue", "northwest Bakersfield"),
    ("the 900 block of Olive Drive", "north Bakersfield"),
    ("the 500 block of Oildale Drive", "north Bakersfield"),
    ("the 9000 block of Rosedale Highway", "northwest Bakersfield"),
    ("Riverlakes Drive", "northwest Bakersfield"),
    ("Haggin Oaks Boulevard", "southwest Bakersfield"),
    ("the 9000 block of Ming Avenue", "southwest Bakersfield"),
    ("the 1000 block of Baker Street", "east Bakersfield"),
    ("the 6400 block of Niles Street", "east Bakersfield"),
    ("the 1500 block of F Street", "central Bakersfield"),
    ("the 2400 block of Truxtun Avenue", "central Bakersfield"),
    ("Cottonwood Road", "southeast Bakersfield"),
    ("the 4400 block of Hughes Lane", "south Bakersfield"),
    ("South Mount Vernon Avenue and Planz Road", "southeast Bakersfield"),
])
def test_known_blocks(area, phrase):
    assert R.region_of(area) == phrase


@pytest.mark.parametrize("area", [
    "Pembroke Avenue",                 # crosses Fruitvale Avenue: two parts
    "Ming Avenue",                     # crosses Hwy 99
    "near a church off Olive Drive",
    "the 2400 block of Chester Avenue",  # Chester or North Chester?
    "the 1600 block of Truxtun Avenue",  # Truxtun or East Truxtun?
    "Main Street in Delano",
    "the 1500 block of Lincoln Street, Delano",
    "the 3000 block of Sierra Highway",
    "the freeway shoulder",
    "Bakersfield",
    "",
])
def test_uncertain_means_no_answer(area):
    assert R.region_of(area) is None


def test_annotate_sets_and_clears():
    incs = [{"area": "the 5400 block of Pembroke Avenue"},
            {"area": "the Pyramid Lake area", "region": "southwest Bakersfield"}]
    assert R.annotate(incs) == 1
    assert incs[0]["region"] == "north Bakersfield"
    assert "region" not in incs[1]


def test_the_2026_10_09_report_is_caught_and_fixed():
    fixed, problems = R.check(REPORT_2026_10_09, INCIDENTS)
    assert len(problems) == 2
    assert "southwest" not in fixed
    assert "A shooting in north Bakersfield sent" in fixed
    assert "**Two shot on Pembroke Avenue in north Bakersfield**" in fixed
    assert R.check(fixed, INCIDENTS) == (fixed, [])


def test_a_correct_report_is_left_alone():
    text = ("Officers were sent to the 1000 block of Baker Street in east "
            "Bakersfield. A crash closed Rosedale Highway in northwest "
            "Bakersfield near the 9000 block. Deputies in Oildale checked the "
            "500 block of Oildale Drive. A fire burned in southwest "
            "Bakersfield; no street was given.")
    assert R.check(text, []) == (text, [])


def test_claim_in_another_sentence_of_a_one_incident_paragraph():
    text = ("**Crash in southwest Bakersfield**: Officers were sent to the "
            "1000 block of Baker Street. One driver was hurt.")
    fixed, problems = R.check(text, [])
    assert len(problems) == 1 and "Crash in east Bakersfield" in fixed


def test_writer_hands_the_model_the_region(monkeypatch):
    import datetime as dt
    from kern_overnight import write as W
    seen = {}

    def fake(prompt, system, **kw):
        seen["prompt"], seen["system"] = prompt, system
        return ("# The Kern Overnight\n\nA quiet night.\n\n## The big one\n\n"
                "**Two shot on Pembroke Avenue in southwest Bakersfield**: "
                "Officers were sent.\n\n## Night notes\n\nQuiet.")

    monkeypatch.setattr(W.llm, "chat_text", fake)
    incs = [{"type": "shooting", "time": "01:22", "notability": 5,
             "area": "the 5400 block of Pembroke Avenue", "summary": "x"}]
    out = W.write_brief(incs, dt.date(2026, 10, 9))
    assert '"region": "north Bakersfield"' in seen["prompt"]
    assert "'region' field" in seen["system"]
    assert "southwest" not in out and "in north Bakersfield" in out
    assert "region" not in incs[0]  # the caller's list is not touched


def test_table_shape():
    table = json.loads(Path(R.TABLE_FILE).read_text(encoding="utf-8"))
    assert len(table) > 8000
    codes = set(R.PHRASE) | {"X"}
    for key, rows in table.items():
        assert key == key.lower() and rows, key
        for lo, hi, code in rows:
            assert code in codes and 0 <= lo <= hi, key
