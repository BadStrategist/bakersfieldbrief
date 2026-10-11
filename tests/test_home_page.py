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
    chips, inside, unmapped = night_counts.chips(_rows(OCT7))
    assert [n for _, n in chips] == [2, 4, 5, 5, 5, 1, 3]
    assert [label for label, _ in chips][:6] == [
        "Weapons and assaults", "Fires", "Crashes and traffic", "Medical and overdose",
        "Disturbances and welfare", "Alarms"]
    assert chips[-1][0] == "Other calls" and "alarm" not in inside
    assert inside == "1 animal bite, 1 911 disconnect, 1 vandalism"
    assert sum(n for _, n in chips) == 25 and unmapped == []


# incidents/2026-10-10.json by raw type (38 calls), the night the band went to one column.
# Equal counts inside Other keep file order, and the public service call came before "Vehicle".
OCT10 = {"Assault": 1, "Disturbance": 1, "Fight": 2, "Fire": 2, "Incident": 5, "Overdose": 1,
         "Traffic collision": 2, "Weapons": 1, "assault with a deadly weapon": 1,
         "assault": 1, "disturbance": 1, "domestic disturbance": 1, "fire alarm": 2,
         "forced entry threat": 1, "grass fire": 2, "juvenile disturbance": 1, "medical aid": 1,
         "multi-vehicle crash": 2, "public service": 1, "Vehicle": 1, "stolen vehicle": 1,
         "suspicious vehicle": 1, "theft": 1, "traffic hazard": 1, "vehicle fire": 3,
         "weapons call": 1}


def test_oct10_night_is_nine_rows_most_serious_first():
    chips, inside, unmapped = night_counts.chips(_rows(OCT10))
    assert chips == [
        ("Weapons and assaults", 7), ("Fires", 7), ("Crashes and traffic", 5),
        ("Medical and overdose", 2), ("Disturbances and welfare", 4),
        ("Burglary and theft", 3), ("Suspicious activity", 1), ("Alarms", 2),
        ("Other calls", 7)]
    assert inside == "5 incident, 1 public service, 1 vehicle"
    assert sum(n for _, n in chips) == 38 and unmapped == []
    assert chips[-1][1] * 5 < 38


def test_row_order_is_the_map_order():
    assert list(night_counts.MAP) == [
        "Weapons and assaults", "Fires", "Crashes and traffic", "Medical and overdose",
        "Missing persons", "Disturbances and welfare", "Burglary and theft",
        "Suspicious activity", "Alarms", "Other calls"]


def test_case_and_underscore_variants_are_one_label():
    for a, b in (("Traffic collision", "traffic_collision"), ("Welfare check", "welfare check"),
                 ("DUI", "dui"), ("Shots fired, unfounded", "shots fired, unfounded")):
        assert night_counts.CHIP_OF[night_counts.normalize(a)] == night_counts.CHIP_OF[night_counts.normalize(b)]


def test_no_substring_matching():
    # the live /overnight/ buckets count an alarm as a burglary and would count this as a fire
    assert night_counts.CHIP_OF["alarm"] == "Alarms"
    assert night_counts.CHIP_OF["burglary alarm"] == "Alarms"
    assert night_counts.CHIP_OF["fire alarm"] == "Alarms"
    assert night_counts.CHIP_OF["shots fired, unfounded"] == "Weapons and assaults"
    assert night_counts.CHIP_OF["vehicle theft"] == "Burglary and theft"
    assert night_counts.CHIP_OF["forced entry threat"] == "Burglary and theft"


def test_unmapped_label_is_named_and_counted_or_stops_the_build(monkeypatch):
    rows = _rows({"collision": 9, "llama on the loose": 1})
    monkeypatch.delenv("KO_STRICT_TYPES", raising=False)
    chips, inside, unmapped = night_counts.chips(rows)
    assert unmapped == ["llama on the loose"]
    assert chips[-1] == ("Other calls", 1) and inside == "1 llama on the loose"
    assert sum(n for _, n in chips) == 10
    monkeypatch.setenv("KO_STRICT_TYPES", "1")
    with pytest.raises(night_counts.NightCountError):
        night_counts.chips(rows)


def test_other_over_a_fifth_gives_its_largest_type_a_chip():
    chips, inside, _ = night_counts.chips(_rows({"collision": 6, "incident": 3, "vandalism": 1}))
    assert ("Incident", 3) in chips and chips[-1] == ("Other calls", 1)
    assert inside == "1 vandalism"
    assert sum(n for _, n in chips) == 10


def test_rendered_band_must_add_up():
    ok = '<span class="num">3</span><ul class="types"><li><b>2</b><span>Fires</span></li><li><b>1</b><span>Other calls</span><small>1 vandalism</small></li></ul>'
    home._check_band(ok)
    with pytest.raises(night_counts.NightCountError):
        home._check_band(ok.replace('<span class="num">3', '<span class="num">4'))


def test_feed_text_prints_no_long_dashes():
    assert home._e("Heat stays put \u2014 high of 99") == "Heat stays put, high of 99"
    assert "\u2013" not in home._e("Sept 23\u2013Oct 4")
