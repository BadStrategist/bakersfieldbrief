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


def test_the_hook_window_is_inert_before_it_opens():
    for date in ("2026-10-12", "2026-10-13"):
        assert mbj.hook_for_date(date) == "title"
    for date in ("2026-10-26", "2026-11-01"):
        assert mbj.hook_for_date(date) == "title"


def test_the_hook_window_alternates_and_covers_both_arms():
    days = [mbj.hook_for_date(f"2026-10-{d:02d}") for d in range(14, 26)]
    assert set(days) == {"cold", "title"}, days
    # Twelve days is two full cycles of opener x bed (2 x 3), so each opener runs
    # twice on each of the three beds.
    assert days.count("cold") == 6 and days.count("title") == 6, days
    assert all(a != b for a, b in zip(days, days[1:])), days


def test_an_unparseable_date_falls_back_to_the_title_card():
    assert mbj.hook_for_date("not-a-date") == "title"


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
