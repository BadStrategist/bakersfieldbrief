"""Home page (v5): the overnight band's counts must come from one night's file, map through
the explicit type table, and add up on the rendered band."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build.builders import home, night_counts  # noqa: E402

# incidents/2026-10-07.json by raw type, as verified in the v5 changelog (25 calls).
OCT7 = {"collision": 4, "medical aid": 3, "welfare check": 2, "domestic disturbance": 2,
        "fire": 2, "overdose": 2, "weapons call": 2, "alarm": 1, "vehicle fire": 1,
        "animal bite": 1, "disturbance": 1, "911 disconnect": 1, "vandalism": 1, "DUI": 1,
        "outside fire": 1}


def _rows(counts):
    return [{"type": t} for t, n in counts.items() for _ in range(n)]


def test_oct7_night_reproduces_the_verified_chips():
    chips, unmapped = night_counts.chips(_rows(OCT7))
    assert [n for _, n in chips] == [5, 5, 4, 3, 2, 2, 4]
    assert [label for label, _ in chips][:6] == [
        "Crashes and traffic", "Disturbances and welfare", "Fires", "Medical aid",
        "Overdose", "Weapons"]
    assert chips[-1][0].startswith("Other: ") and "alarm" in chips[-1][0]
    assert sum(n for _, n in chips) == 25 and unmapped == []


def test_case_and_underscore_variants_are_one_label():
    for a, b in (("Traffic collision", "traffic_collision"), ("Welfare check", "welfare check"),
                 ("DUI", "dui"), ("Shots fired, unfounded", "shots fired, unfounded")):
        assert night_counts.CHIP_OF[night_counts.normalize(a)] == night_counts.CHIP_OF[night_counts.normalize(b)]


def test_no_substring_matching():
    # the live /overnight/ buckets count an alarm as a burglary and would count this as a fire
    assert night_counts.CHIP_OF["alarm"] == night_counts.OTHER
    assert night_counts.CHIP_OF["burglary alarm"] == night_counts.OTHER
    assert night_counts.CHIP_OF["shots fired, unfounded"] == "Weapons"
    assert night_counts.CHIP_OF["vehicle theft"] == "Burglary and theft"


def test_unmapped_label_is_named_and_counted_or_stops_the_build(monkeypatch):
    rows = _rows({"collision": 9, "llama on the loose": 1})
    monkeypatch.delenv("KO_STRICT_TYPES", raising=False)
    chips, unmapped = night_counts.chips(rows)
    assert unmapped == ["llama on the loose"]
    assert chips[-1] == ("Other: llama on the loose", 1) and sum(n for _, n in chips) == 10
    monkeypatch.setenv("KO_STRICT_TYPES", "1")
    with pytest.raises(night_counts.NightCountError):
        night_counts.chips(rows)


def test_other_over_a_fifth_gives_its_largest_type_a_chip():
    chips, _ = night_counts.chips(_rows({"collision": 6, "alarm": 3, "vandalism": 1}))
    assert ("Alarm", 3) in chips and chips[-1] == ("Other: vandalism", 1)
    assert sum(n for _, n in chips) == 10


def test_rendered_band_must_add_up():
    ok = '<span class="num">3</span><ul class="chips"><li><b>2</b><span>Fires</span></li><li><b>1</b><span>Other: alarm</span></li></ul>'
    home._check_band(ok)
    with pytest.raises(night_counts.NightCountError):
        home._check_band(ok.replace('<span class="num">3', '<span class="num">4'))


def test_feed_text_prints_no_long_dashes():
    assert home._e("Heat stays put \u2014 high of 99") == "Heat stays put, high of 99"
    assert "\u2013" not in home._e("Sept 23\u2013Oct 4")
