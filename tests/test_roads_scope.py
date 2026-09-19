#!/usr/bin/env python3
"""Corridor scoping for the Caltrans pass pages.

Caltrans reports by AREA, which is far too coarse to answer "is the pass open?":
I-5's CENTRAL CALIFORNIA text is a San Joaquin County wind advisory (200 miles
north of Tejon Pass) and SR-58 ships ONE Central section for the whole route, so
a collision in the city of Bakersfield was headlined as "Tehachapi Pass:
CLOSED". These tests pin the corridor scope: a pass may only be reported
closed/restricted when a Caltrans item names a place ON that corridor.

Fixtures are real Caltrans pages saved on 2026-09-19 (tests/fixtures/roads_*.html).
Run:  python -m pytest tests/test_roads_scope.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build.sources import roads as R  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def _parse(slug: str, fname: str) -> dict:
    route = next(r for r in R.ROUTES if r["slug"] == slug)
    return R._parse((FIX / fname).read_text(encoding="utf-8"), route)


# ---------------------------------------------------------------- scope, real data
def test_i5_irvine_closure_is_not_the_pass():
    """The Orange County connector closure must not be reported as Tejon Pass."""
    p = _parse("i5", "roads_i5_2026-09-19.html")
    sc = p["scope"]
    assert p["status"] == "CLOSED"          # route-wide rollup is still CLOSED
    assert sc["on_pass_reported"] is False
    assert sc["on_pass"] == "OPEN"
    assert any("Irvine" in i["place"] for i in sc["elsewhere"])


def test_i5_san_joaquin_wind_advisory_is_elsewhere():
    p = _parse("i5", "roads_i5_2026-09-19.html")
    assert any("San Joaquin" in (i["county"] or "") for i in p["scope"]["elsewhere"])


def test_sr58_bakersfield_collision_is_not_the_pass():
    """The live case that motivated the fix: SR-58 closed at Superior Rd, in town."""
    p = _parse("sr58", "roads_sr58_2026-09-19.html")
    sc = p["scope"]
    assert sc["on_pass_reported"] is False
    assert sc["on_pass"] == "OPEN"
    assert any("Bakersfield" in i["place"] for i in sc["elsewhere"])


def test_sr99_merced_closure_is_not_kern():
    p = _parse("sr99", "roads_sr99_2026-09-19.html")
    sc = p["scope"]
    assert sc["on_pass_reported"] is False
    assert any("Merced" in i["place"] for i in sc["elsewhere"])


# ---------------------------------------------------------------- scope, corridor hit
def test_on_corridor_closure_does_report_the_pass():
    """A real pass closure (place named in the corridor) MUST set the pass status."""
    route = next(r for r in R.ROUTES if r["slug"] == "sr58")
    text = ("[IN THE CENTRAL CALIFORNIA AREA] Is closed at Keene /in Keene/ (Kern Co) "
            "- Due to snow - Motorists are advised to use an alternate route")
    p = R._parse(text, route)
    assert p["scope"]["on_pass_reported"] is True
    assert p["scope"]["on_pass"] == "CLOSED"


def test_corridor_keywords_do_not_match_neighbouring_routes():
    """\"SR-133\" (Irvine) must not read as \"SR-138\" (the pass junction)."""
    assert not any(k in "THE CONNECTOR TO SR-133 /IN IRVINE/" for k in R.CORRIDOR["i5"])


# ---------------------------------------------------------------- builder-level honesty
def _visible(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))


def _render_tehachapi(scope, tmp_path, monkeypatch):
    import datetime as dt
    import tempfile
    import types
    from build.builders import tehachapi
    import build.common as common

    routes = [{
        "number": "58", "slug": "sr58", "name": "State Route 58 - Tehachapi",
        "pass": False, "status": "CLOSED", "pass_status": "OPEN",
        "scope": scope,
        "sections": [{"region": "CENTRAL CALIFORNIA", "status": "CLOSED",
                      "text": "Is closed at Superior Rd /in Bakersfield/ (Kern Co)"}],
        "reported_as_of": "Saturday, September 19th, 2026 at 04:15 PM", "hash": "abc",
    }]
    sources = {"roads": {"ok": True, "routes": routes, "asof": "2026-09-19", "log": []},
               "tehachapi_weather": {"ok": True, "current": {"ok": True, "station": "KTSP",
                                                             "wind_mph": 12, "observed": "Sep 19, 04:00 PM"},
                                     "forecast": [], "alerts": []}}
    fake = Path(tempfile.mkdtemp()) / "site"
    (fake / "tehachapi-pass").mkdir(parents=True)
    (fake / "assets").mkdir()
    orig = common.SITE
    common.SITE = fake
    try:
        tehachapi.build(types.SimpleNamespace(today=dt.date.today(), statusbar="",
                                              build_report={}), sources)
    finally:
        common.SITE = orig
    return _visible((fake / "tehachapi-pass" / "index.html").read_text(encoding="utf-8"))


def test_builder_does_not_call_the_pass_closed_for_a_town_closure(tmp_path, monkeypatch):
    scope = {"on_pass": "OPEN", "on_pass_reported": False, "on_pass_items": [],
             "elsewhere": [{"status": "CLOSED", "place": "Bakersfield", "county": "Kern Co",
                            "where": "Bakersfield (Kern Co)",
                            "text": "Is closed at Superior Rd /in Bakersfield/ (Kern Co)",
                            "region": "CENTRAL CALIFORNIA"}]}
    body = _render_tehachapi(scope, tmp_path, monkeypatch)
    assert "no closures or restrictions on Tehachapi Pass itself" in body
    assert "closure at Bakersfield (Kern Co)" in body
    # the verdict block itself must never claim a pass closure
    verdict = re.search(r"As of .{0,120}?Tehachapi Pass is (.{0,40})", body)
    assert verdict and "closed" not in verdict.group(1).lower()


def test_builder_reports_a_real_pass_closure(tmp_path, monkeypatch):
    scope = {"on_pass": "CLOSED", "on_pass_reported": True,
             "on_pass_items": [{"status": "CLOSED", "place": "Keene", "county": "Kern Co",
                                "where": "Keene (Kern Co)", "text": "Is closed at Keene",
                                "region": "CENTRAL CALIFORNIA"}],
             "elsewhere": []}
    body = _render_tehachapi(scope, tmp_path, monkeypatch)
    assert "Tehachapi Pass is closed" in body


def test_water_faq_carries_the_asked_phrasings():
    """The two questions the cited competitors answer, answered with our live numbers."""
    raw = (ROOT / "build" / "builders" / "trackers.py").read_text(encoding="utf-8")
    assert "How full is Lake Isabella right now?" in raw
    assert "How far below full pool is Lake Isabella?" in raw
    assert "acre-feet over the last" in raw and "7 days" in raw
