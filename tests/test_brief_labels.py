"""The reel headline label and the hook-test window.

Measured baseline this change fixes: over the 22 shipped reel briefs of Sep 17 to Oct 12 2026,
33 of 66 stories led with "Incident reported on <place>", which names no event. A replay of the
same 22 dates through the previous builder gives 33 generic headlines; through this one, 0.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.make_brief_json as mbj  # noqa: E402


@pytest.mark.parametrize("raw, expected", [
    # A type the table does not hold shows its own words.
    ("Robbery", "Robbery"),
    ("robbery", "Robbery"),
    ("Arson", "Arson"),
    ("Vehicle vs. pedestrian", "Vehicle vs. pedestrian"),
    ("Shots fired", "Shots fired"),
    ("Weapons call", "Weapons call"),
    ("Multi-vehicle crash", "Multi-vehicle crash"),
    # A compound type keeps its first part.
    ("kidnapping / assault with a firearm", "Kidnapping"),
    ("structure fire, second alarm", "Structure fire"),
    # Only a type that says nothing on its own keeps the generic label.
    ("", "Incident reported"),
    ("incident", "Incident reported"),
    ("vehicle", "Incident reported"),
    ("other", "Incident reported"),
    ("Traffic incident", "Incident reported"),
    # Too long to be a headline is not a headline.
    ("a very long type name that runs well past the six word cap and keeps going",
     "Incident reported"),
])
def test_label_for_names_the_event(raw, expected):
    assert mbj.label_for(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Kidnapping", "Reported kidnapping"),
    ("kidnapping", "Reported kidnapping"),
    ("hostage", "Reported hostage situation"),
])
def test_a_callers_grave_crime_is_labelled_as_reported(raw, expected):
    assert mbj.label_for(raw) == expected


def test_no_type_in_the_table_ever_reaches_the_generic_label():
    """Every type the table knows must still resolve to the table's own label."""
    for t, label in mbj.TYPE_LABEL.items():
        assert mbj.label_for(t) == label


def test_the_reel_always_opens_cold_on_the_lead_story():
    """The cold/title A/B test ended 2026-10-20: the owner judged the cream title
    flash unprofessional, so every reel opens on story 1 from frame 0."""
    for date in ("2026-10-13", "2026-10-14", "2026-10-15", "2026-10-26", "not-a-date"):
        assert mbj.hook_for_date(date) == "cold"


def test_stories_carry_the_label_and_place_the_cold_opener_needs():
    """The cold opener draws the event and the place as two lines; a story with no
    area must carry an empty place, never a defaulted city."""
    with_area = mbj.story_json(
        {"type": "Robbery", "area": "Mount Vernon Avenue", "summary": "x", "time": "01:20"})
    assert with_area["label"] == "Robbery"
    assert with_area["where"].endswith("Mount Vernon Avenue")
    without = mbj.story_json({"type": "Robbery", "area": "", "summary": "x",
                              "time": "01:20"})
    assert without["where"] == ""


@pytest.mark.parametrize("raw, expected", [
    # A hedge the caller wrote stays. "Shots fired, unfounded" read as "Shots
    # fired" claims more than the call did (review, 2026-10-12).
    ("Shots fired, unfounded", "Shots fired, unfounded"),
    ("Assault, possible domestic", "Assault, possible domestic"),
    ("reported shooting", "Reported shooting"),
    ("Possible burglary", "Possible burglary"),
    # A compound type with no hedge still keeps only its first part.
    ("structure fire, second alarm", "Structure fire"),
    ("kidnapping / assault with a firearm", "Kidnapping"),
])
def test_a_hedge_is_never_dropped_while_naming_an_event(raw, expected):
    assert mbj.label_for(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("possible DUI", "Possible DUI"),
    ("possible_dui", "Possible DUI"),
    ("dui_report", "DUI report"),
    ("Reckless driver", "Reckless driver"),
])
def test_a_lower_cased_acronym_stays_an_acronym(raw, expected):
    assert mbj.label_for(raw) == expected


@pytest.mark.parametrize("area, expected", [
    # A place that carries its own locator is never given a second one.
    ("near Lynwood and Height streets", "near Lynwood and Height streets"),
    ("south of Kelso Creek", "south of Kelso Creek"),
    ("off King Street, east Kern", "off King Street, east Kern"),
    # Everything else keeps the preposition it always had.
    ("Mount Vernon Avenue", "on Mount Vernon Avenue"),
    ("Union Avenue", "on Union Avenue"),
    ("Delano", "in Delano"),
    ("", ""),
])
def test_a_place_never_gets_two_locators(area, expected):
    assert mbj._place_phrase(area) == expected


def test_no_type_on_disk_loses_a_hedge_or_lower_cases_an_acronym():
    """Re-measured over every type in incidents/, never a sample: 346 distinct
    types over 1,214 rows. A generic label claims nothing, so it is exempt."""
    import glob
    import json
    import re
    hedge = re.compile(r"\b(unfounded|unconfirmed|possible|reported|alleged|"
                       r"suspicious|unknown|attempted)\b", re.I)
    acro = re.compile(r"\b(dui|dwi|k9|atv|suv|chp|kcso|bpd|fbi|swat|emt)\b")
    files = glob.glob(str(ROOT / "incidents" / "*.json"))
    if not files:
        pytest.skip("no incidents/ data on this checkout")
    types = set()
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else (
            data.get("incidents") or data.get("stories") or [])
        for row in rows:
            if isinstance(row, dict) and row.get("type"):
                types.add(str(row["type"]).strip())
    assert len(types) > 100, len(types)
    for t in sorted(types):
        label = mbj.label_for(t)
        if label == "Incident reported":
            continue
        assert not (hedge.search(t) and not hedge.search(label)), (t, label)
        assert not acro.search(label), (t, label)
