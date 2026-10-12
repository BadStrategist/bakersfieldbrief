"""Town pages under /surveillance/, and the copy that follows the ownership data.

Three things these guard:
  * a town is a looked-up fact: a camera is in a town when its point is inside that place's
    Census boundary, and a camera in no place is on no town page;
  * a town page exists only when it is not thin and the ownership join covers it, so the
    pages stay unbuilt (no file, no hub link, no sitemap entry) until the county join lands;
  * the hub never types how many cameras are unjoined: it counts joined, no-record and
    not-looked-up cameras from the data, and says a different thing for each.
"""
import datetime as dt
import html
import json
import re
import sys
import tempfile
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build.common as common  # noqa: E402
from build import places_kern  # noqa: E402
from build.builders import alpr_explorer, alpr_page, alpr_towns, trackers  # noqa: E402

# Real points, checked against the Census boundaries on 2026-10-12.
RIDGECREST = (35.6513, -117.6878)      # a mapped camera on China Lake Boulevard
TEHACHAPI = (35.1382, -118.4682)
STALLION = (35.0944, -118.6239)        # Stallion Springs, in the Tehachapi group
MARICOPA = (35.0583, -119.3933)
GRAPEVINE = (34.9849, -118.9391)       # Interstate 5 at the foot of the Grapevine: no place
NEAR_TEHACHAPI = (35.1097, -118.3985)  # unincorporated, 1.2 km outside the Tehachapi city limits
BAKERSFIELD = (35.3733, -119.0187)


# ------------------------------------------------------------------ the town of a point
def test_places_file_holds_the_eleven_cities():
    cities = {p["name"] for p in places_kern.load() if p["kind"] == "city"}
    assert cities == {"Arvin", "Bakersfield", "California City", "Delano", "Maricopa",
                      "McFarland", "Ridgecrest", "Shafter", "Taft", "Tehachapi", "Wasco"}


@pytest.mark.parametrize("pt,name,kind", [
    (RIDGECREST, "Ridgecrest", "city"), (TEHACHAPI, "Tehachapi", "city"),
    (STALLION, "Stallion Springs", "cdp"), (MARICOPA, "Maricopa", "city"),
    (BAKERSFIELD, "Bakersfield", "city")])
def test_a_point_is_in_the_place_whose_boundary_holds_it(pt, name, kind):
    pl = places_kern.place_of(*pt)
    assert (pl["name"], pl["kind"]) == (name, kind)


def test_a_point_in_no_place_has_no_town():
    assert places_kern.place_of(*GRAPEVINE) is None
    assert places_kern.place_of(None, None) is None
    # and the nearest town is a measurement, never a membership
    assert places_kern.place_of(*NEAR_TEHACHAPI) is None
    pl, km = places_kern.nearest(*NEAR_TEHACHAPI, 5.0)
    assert pl["name"] == "Tehachapi" and 0 < km < 5.0
    assert places_kern.nearest(*GRAPEVINE, 5.0) is None


def test_every_listed_town_names_real_places_and_bakersfield_is_not_one():
    names = {p["name"] for p in places_kern.load()}
    for slug, town in alpr_towns.TOWNS.items():
        assert set(town["places"]) <= names, slug
        assert slug == places_kern.slug(town["name"])
    # /surveillance/ is Bakersfield's page; a second one would compete with it
    assert "bakersfield" not in alpr_towns.TOWNS
    assert all("Bakersfield" not in t["places"] for t in alpr_towns.TOWNS.values())
    assert alpr_towns.FLOOR <= alpr_towns.MIN_CAMERAS


# ------------------------------------------------------------------ fixtures
def _cam(i, pt, manu="Flock Safety", mapped="2025-06-16"):
    # a step of 10 cm: the Stallion Springs camera stands 10 m inside its boundary
    return {"id": 5000 + i, "lat": pt[0] + (i % 10) * 1e-6, "lon": pt[1] + (i % 10) * 1e-6, "manufacturer": manu,
            "operator": "", "direction": "90", "mapped": mapped, "camera_type": "ALPR"}


def _own_cam(c, oid, *, owner="KERN SUNSET OIL CO", otype="entity", cstat="not_researched",
             place="Ridgecrest", kind="city"):
    return {"id": str(c["id"]), "lat": c["lat"], "lon": c["lon"], "loc": "China Lake Boulevard",
            "trusted": True, "addr": "China Lake Boulevard, Ridgecrest", "owner": owner,
            "otype": otype, "oid": oid, "pid": oid, "apn": f"080-01{oid}-01", "dist": 4.0,
            "match": "camera adjacent to the parcel (within 30 m)",
            "land": "Private titled parcel (owner on tax roll)", "use": "1100 - STORES",
            "val": "265,244", "district": "1 - Phillip Peters", "cstat": cstat,
            "place": place, "place_kind": kind, "incity": False}


def _ownership(cams, *, skip=(), norecord=(), private=()):
    """Ownership data for the given OSM cameras: one company owner, optionally one private."""
    rows, owners, parcels = [], [], []
    owners.append({"oid": 0, "name": "KERN SUNSET OIL CO", "type": "entity", "cams": [], "n": 0,
                   "nparcel": 1, "parcels": ["080-010-01"], "cstat": "not_researched"})
    owners.append({"oid": 1, "name": "PERRIGE JOHN J", "type": "individual", "cams": [], "n": 0,
                   "nparcel": 1, "parcels": ["080-011-01"], "cstat": "not_researched"})
    for o in owners:
        parcels.append({"pid": o["oid"], "apn": o["parcels"][0], "cams": [], "n": 0,
                        "owners": [o["name"]], "use": "1100 - STORES"})
    nr = {str(c["id"]) for c in norecord}
    for c in cams:
        if c["id"] in {s["id"] for s in skip} or str(c["id"]) in nr:
            continue
        oid = 1 if c["id"] in {p["id"] for p in private} else 0
        o = owners[oid]
        rows.append(_own_cam(c, oid, owner=o["name"], otype=o["type"]))
        o["cams"].append(str(c["id"]))
        o["n"] += 1
        parcels[oid]["cams"].append(str(c["id"]))
        parcels[oid]["n"] += 1
    return {"cams": rows, "owners": owners, "parcels": parcels,
            "norecord": [{"id": str(c["id"]), "lat": c["lat"], "lon": c["lon"],
                          "reason": "no_parcel_60m", "nearest_m": 212.0, "loc": "State Route 58",
                          "addr": ""} for c in norecord],
            "meta": {"built": "2026-10-14"}}


@pytest.fixture
def site(monkeypatch):
    """A throwaway site/ and a hook to install ownership data without touching data/."""
    fake = Path(tempfile.mkdtemp()) / "site"
    (fake / "surveillance").mkdir(parents=True)
    monkeypatch.setattr(common, "SITE", fake)

    def install(own):
        monkeypatch.setattr(alpr_explorer, "_cache", alpr_explorer._apply_privacy(json.loads(json.dumps(own))))
    monkeypatch.setattr(alpr_explorer, "_cache", {})
    return types.SimpleNamespace(root=fake, install=install)


def _sources(cams, asof="2026-10-14"):
    return {"alpr": {"ok": True, "stale": False, "cameras": cams, "asof": asof, "change_log": [],
                     "stats": {"total": len(cams), "newest_mapped": "2025-06-16", "new_this_week": 0,
                               "flock": sum(1 for c in cams if "flock" in c["manufacturer"].lower())}}}


def _ctx():
    return types.SimpleNamespace(today=dt.date(2026, 10, 14), statusbar="", build_report={})


def _text(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def _county():
    """12 in Ridgecrest, 9 in the Tehachapi group, 3 in Maricopa, 2 at the Grapevine, 1 just
    outside Tehachapi."""
    cams = [_cam(i, RIDGECREST) for i in range(12)]
    cams += [_cam(20 + i, TEHACHAPI) for i in range(7)] + [_cam(30 + i, STALLION) for i in range(2)]
    cams += [_cam(40 + i, MARICOPA) for i in range(3)] + [_cam(50 + i, GRAPEVINE) for i in range(2)]
    cams += [_cam(60, NEAR_TEHACHAPI, manu="Motorola Solutions")]
    return cams


# ------------------------------------------------------------------ which towns get a page
def test_no_town_page_until_the_join_covers_the_county(site):
    """Today's state: the join holds the metro only. Nothing is built and nothing links."""
    cams = _county()
    site.install(_ownership(cams[:12]))            # Ridgecrest joined, 13 others not looked up
    src = _sources(cams)
    assert alpr_towns.plan(src) == {}
    assert alpr_towns.build(_ctx(), src) == []
    assert not list((site.root / "surveillance").rglob("index.html"))
    assert alpr_towns.hub_links_html(alpr_towns.plan(src), src) == ""


def test_the_september_join_builds_no_town_page_even_when_every_camera_is_joined(site):
    """Measured 2026-10-12: the cached metro-only list (270 cameras) against the September join
    (268) is 99 percent joined, and that built Oildale, Rosedale and Shafter. A join that never
    covered the county carries no "norecord" key, and without the key nothing is built."""
    cams = [_cam(i, RIDGECREST) for i in range(12)]
    own = _ownership(cams)
    del own["norecord"]
    site.install(own)
    assert alpr_towns.plan(_sources(cams)) == {}
    own["norecord"] = []
    site.install(own)
    assert list(alpr_towns.plan(_sources(cams))) == ["ridgecrest"]


def test_no_town_page_without_ownership_data_or_a_camera_list(site):
    assert alpr_towns.plan(_sources(_county())) == {}          # no ownership data at all
    site.install(_ownership(_county()))
    assert alpr_towns.plan({"alpr": {"ok": False, "error": "Timeout"}}) == {}


def test_towns_that_clear_the_bar_get_a_page_and_thin_ones_do_not(site):
    cams = _county()
    site.install(_ownership(cams))
    plans = alpr_towns.plan(_sources(cams))
    assert list(plans) == ["ridgecrest", "tehachapi"]
    assert len(plans["ridgecrest"]["cams"]) == 12
    # the Tehachapi group counts its own places and nothing else
    assert len(plans["tehachapi"]["cams"]) == 9
    assert [c["id"] for c in plans["tehachapi"]["near"]] == ["5060"]
    # Maricopa has 3: a real town, a thin page. The Grapevine cameras are in no town.
    built = alpr_towns.build(_ctx(), _sources(cams))
    assert built == ["surveillance/ridgecrest/index.html", "surveillance/tehachapi/index.html"]
    assert not (site.root / "surveillance" / "maricopa").exists()


def test_a_town_below_the_floor_loses_its_page_and_gets_a_redirect(site):
    cams = [_cam(i, RIDGECREST) for i in range(alpr_towns.FLOOR - 1)]
    site.install(_ownership(cams))
    assert alpr_towns.plan(_sources(cams)) == {}
    lines = alpr_towns.redirect_lines()
    assert "/surveillance/ridgecrest/  /surveillance/  302\n" in lines
    # a built page is never redirected away
    (site.root / "surveillance" / "delano").mkdir()
    (site.root / "surveillance" / "delano" / "index.html").write_text("x", encoding="utf-8")
    assert "/surveillance/delano/" not in alpr_towns.redirect_lines()


def test_a_town_whose_own_cameras_are_not_joined_has_no_page(site):
    """The county can be 90 percent joined while one town is not: that town waits."""
    cams = [_cam(i, RIDGECREST) for i in range(10)] + [_cam(100 + i, BAKERSFIELD) for i in range(190)]
    site.install(_ownership(cams, skip=cams[:5]))
    assert alpr_towns.plan(_sources(cams)) == {}


# ------------------------------------------------------------------ the page
def _town_page(site, slug="tehachapi", **kw):
    cams = _county()
    site.install(_ownership(cams, **kw))
    alpr_towns.build(_ctx(), _sources(cams))
    return (site.root / "surveillance" / slug / "index.html").read_text(encoding="utf-8")


def test_town_page_head_and_links(site):
    raw = _town_page(site)
    assert "<title>Tehachapi Flock Camera Map | 9 License Plate Readers</title>" in raw
    assert '<link rel="canonical" href="https://bakersfieldbrief.com/surveillance/tehachapi/">' in raw
    assert [_text(x) for x in re.findall(r"<h1[^>]*>(.*?)</h1>", raw, re.S)] == ["Tehachapi Flock Camera Map"]
    assert 'name="robots" content="index, follow"' in raw
    # spoke to hub, spoke to spoke, and the breadcrumb says where the page sits
    assert 'href="../../surveillance/"' in raw and 'href="../../surveillance/ridgecrest/"' in raw
    crumbs = _text(re.search(r'<nav class="breadcrumbs".*?</nav>', raw, re.S).group(0))
    assert crumbs == "Daily Brief › Trackers › Flock camera map › Tehachapi"
    blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, re.S)]
    types_ = {b.get("@type") for b in blocks}
    assert {"WebPage", "Dataset", "BreadcrumbList"} <= types_
    ds = next(b for b in blocks if b.get("@type") == "Dataset")
    assert ds["url"].endswith("/surveillance/tehachapi/") and "Tehachapi" in ds["spatialCoverage"]["name"]
    # no long dash anywhere in what the page says
    assert chr(8212) not in _text(raw) and "&mdash;" not in raw


def test_town_page_lists_its_cameras_with_owner_rows_and_only_its_cameras(site):
    raw = _town_page(site)
    payload = json.loads(re.search(r'<script type="application/json" id="tracker-data">(.*?)</script>', raw, re.S).group(1))
    ids = sorted(str(c["id"]) for c in payload["cameras"])
    assert len(ids) == 10                          # 9 in the group and 1 just outside
    assert sorted(re.findall(r'<li class="ax-item" data-id="(\d+)"', raw)) == ids
    table = re.search(r'<section class="card" id="cameras">.*?</section>', raw, re.S).group(0)
    assert len(re.findall(r"<tr><td>", table)) == 9
    t = _text(table)
    for want in ("KERN SUNSET OIL CO", "1100 - STORES", "$265,244", "District 1, Phillip Peters",
                 "Stallion Springs", "Mapped on OSM"):
        assert want in t, want
    near = _text(re.search(r'<section class="card" id="nearby">.*?</section>', raw, re.S).group(0))
    assert "Just outside the Tehachapi city limits" in near and "0.7 mi outside the Tehachapi city limits" in near
    assert alpr_towns._outside(0.0026) == "10 ft" and alpr_towns._outside(0.03) == "100 ft"
    assert "not counted in Tehachapi’s 9" in near
    # Ridgecrest's cameras are not on Tehachapi's page
    assert "5000" not in ids
    assert "9 license plate readers are mapped in Tehachapi and Stallion Springs" in _text(raw)
    assert 'data-src="../../assets/alpr/ownership.json?v=' in raw


def test_private_owner_is_not_named_on_a_town_page(site):
    cams = _county()
    raw = _town_page(site, slug="ridgecrest", private=cams[:3])
    if alpr_explorer.PUBLISH_PRIVATE_NAMES:
        return
    assert "PERRIGE" not in raw
    assert "Private owner (name not published)" in raw
    assert "(name not published) (private owner)" not in _text(raw)


def test_town_page_says_what_was_found_for_a_camera_with_no_roll_record(site):
    cams = _county()
    raw = _town_page(site, slug="ridgecrest", norecord=cams[:1])
    t = _text(raw)
    assert "In a road or right of way: no titled parcel within 60 meters." in t
    assert "11 are joined to the Kern County tax-roll parcel" in t
    assert "1 stands where the tax roll has no parcel to join" in t
    assert "not looked up yet" not in t.lower()


# ------------------------------------------------------------------ what a search needs
def _blocks(raw):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, re.S)]


def test_town_page_headings_skip_no_level(site):
    raw = _town_page(site)
    main = raw[raw.index("<h1"):raw.index('<section class="card" id="more">')]
    levels = [int(n) for n in re.findall(r"<h([1-6])\b", main)]
    assert levels[0] == 1 and levels.count(1) == 1
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels
    # the explorer title is an h2 here and stays an h3 on the hub, whose headings are pinned
    assert '<h2 id="ax-h">' in raw and '<h3 id="ax-h">' not in raw
    assert '<h3 id="ax-h">' in alpr_page.explorer_html([], "2026-10-14", 0, True)[0]


def test_town_meta_description_is_shown_whole():
    for name, n in (("Ridgecrest", 31), ("McFarland", 19), ("Wasco", 10), ("Shafter", 132)):
        d = alpr_towns._desc(n, n, name, False)
        assert len(d) <= 160 and f"{n} license plate readers in {name}" in d, d
    d = alpr_towns._desc(12, 12, "Tehachapi", True)
    assert len(d) <= 160 and "in and around Tehachapi" in d


def test_town_questions_are_on_the_page_and_in_the_schema_and_agree(site):
    raw = _town_page(site)
    faq = next(b for b in _blocks(raw) if b.get("@type") == "FAQPage")
    block = re.search(r'<section class="card ax-faq" id="questions">.*?</section>', raw, re.S).group(0)
    seen = [(_text(q), _text(a)) for q, a in re.findall(r"<h3>(.*?)</h3><p>(.*?)</p>", block, re.S)]
    assert seen == [(q["name"], q["acceptedAnswer"]["text"]) for q in faq["mainEntity"]]
    got = dict(seen)
    assert got["Does Tehachapi have Flock cameras?"].startswith(
        "Yes. 9 Flock Safety license plate readers are mapped in Tehachapi and Stallion Springs as of 2026-10-14.")
    assert "1 more stands just outside the Tehachapi city limits and is not in that count." in \
        got["Does Tehachapi have Flock cameras?"]
    how = got["How many license plate readers are in Tehachapi?"]
    assert "9 are mapped as of 2026-10-14: 7 in Tehachapi and 2 in Stallion Springs." in how
    assert ("A record at California Board of State and Community Corrections names 16 for the "
            "Tehachapi Police Department.") in how
    assert "Where are the Flock cameras in Tehachapi?" in got
    assert "9 of the 9 cameras are joined" in got["Who owns the land under the cameras in Tehachapi?"]
    # every node the page had before is still there
    assert {"WebPage", "Dataset", "BreadcrumbList", "NewsMediaOrganization", "WebSite"} <= \
        {b.get("@type") for b in _blocks(raw)}


def test_every_public_record_is_a_quote_with_a_source():
    recs = alpr_towns.load_records()
    assert recs
    names = {p["name"] for p in places_kern.load()}
    for r in recs:
        assert set(r["towns"]) <= set(alpr_towns.TOWNS), r["towns"]
        assert r["url"].startswith("https://") and r["quotes"] and all(q.strip() for q in r["quotes"])
        for k in ("agency", "doc", "when", "source"):
            assert r[k].strip(), k
        assert chr(8212) not in json.dumps(r, ensure_ascii=False)
        if "units" in r:
            # the number the page prints is in the words it quotes, and is for a real place
            assert str(r["units"]) in " ".join(r["quotes"]) and r["scope"] in names
            assert all(r["scope"] in alpr_towns.TOWNS[t]["places"] for t in r["towns"])
        if "point" in r:
            assert places_kern.place_of(*r["point"]) is not None and r["point_label"]


def test_town_page_prints_its_records_and_counts_the_map_beside_them(site):
    raw = _town_page(site)
    block = re.search(r'<section class="card ax-records" id="records">.*?</section>', raw, re.S).group(0)
    t = _text(block)
    assert "Tehachapi Police Department: application to the Organized Retail Theft Prevention Grant Program" in t
    assert "is to install 16 Automatic License Plate Readers (ALPR)" in t
    # 7 is counted from the fixture's cameras inside the city, not typed
    assert "The record names 16. This map holds 7 inside Tehachapi." in t
    assert "This is an application." in t
    # the sheriff's notice is here because its pole is inside Golden Hills, a place of this town
    assert "Its coordinates are inside Golden Hills." in t
    assert 'href="https://www.bscc.ca.gov/wp-content/uploads/102-Tehachapi-Police-Dept.pdf"' in block
    assert 'href="https://ceqanet.lci.ca.gov/2026040438"' in block
    # another town's record is not on this page
    assert "Ridgecrest Police Department" not in raw
    who = dict((q["name"], q["acceptedAnswer"]["text"]) for q in
               next(b for b in _blocks(raw) if b.get("@type") == "FAQPage")["mainEntity"])
    assert who["Who operates the license plate readers in Tehachapi?"] == (
        "OpenStreetMap names no operator for these cameras. The public records on this page name "
        "the Kern County Sheriff's Office and Tehachapi Police Department.")


def test_a_record_with_a_point_outside_the_town_is_not_shown(site, monkeypatch):
    rec = {"towns": ["tehachapi"], "agency": "A", "doc": "d", "when": "2026", "source": "S",
           "url": "https://example.org/", "quotes": ["q"], "point": list(GRAPEVINE), "point_label": "x"}
    monkeypatch.setattr(alpr_towns, "load_records", lambda: [rec])
    assert 'id="records"' not in _town_page(site)
    monkeypatch.setattr(alpr_towns, "load_records", lambda: [dict(rec, point=list(STALLION))])
    assert "Its coordinates are inside Stallion Springs." in _text(_town_page(site))
    # a record with no number for the town and no pole in it names no operator for the town
    monkeypatch.setattr(alpr_towns, "load_records", lambda: [{k: v for k, v in rec.items() if "point" not in k}])
    raw = _town_page(site)
    assert 'id="records"' in raw and "Who operates the license plate readers" not in raw


def test_a_town_with_no_record_has_no_records_block_and_names_the_osm_operators(site, monkeypatch):
    monkeypatch.setattr(alpr_towns, "load_records", lambda: [])
    cams = _county()
    for c in cams[:5]:
        c["operator"] = "Ridgecrest Police Department"
    site.install(_ownership(cams))
    alpr_towns.build(_ctx(), _sources(cams))
    raw = (site.root / "surveillance" / "ridgecrest" / "index.html").read_text(encoding="utf-8")
    assert 'id="records"' not in raw
    assert ("OpenStreetMap names an operator for 5 of the 12 mapped cameras: Ridgecrest Police "
            "Department, 5.") in _text(raw)
    teh = (site.root / "surveillance" / "tehachapi" / "index.html").read_text(encoding="utf-8")
    assert "Who operates the license plate readers" not in teh


def test_a_brief_links_a_town_map_only_when_one_paragraph_names_the_town_and_a_camera():
    from build.builders import daily
    towns = {"ridgecrest": "Ridgecrest", "delano": "Delano"}
    story = "<p>Ridgecrest's police chief says the city is amending its Flock camera contract.</p>"
    other = "<p>Delano opens a new park on Saturday.</p>"
    assert daily._town_camera_links(story + other, towns) == [
        ("surveillance/ridgecrest/", "Ridgecrest Flock camera map")]
    assert daily._town_camera_links(other + "<p>Flock cameras are on the agenda.</p>", towns) == []
    assert daily._town_camera_links(story, {}) == [] and daily._town_camera_links(story, None) == []
    out = daily._related_trackers("../../", story + other, towns)
    assert out.index('href="../../surveillance/ridgecrest/"') < out.index('href="../../surveillance/"')
    assert "delano" not in out


# ------------------------------------------------------------------ the hub follows the data
def _hub(site, cams, own):
    site.install(own)
    trackers.build_alpr(_ctx(), _sources(cams))
    return (site.root / "surveillance" / "index.html").read_text(encoding="utf-8")


def test_hub_counts_joined_norecord_and_pending_from_the_data(site):
    cams = _county()
    raw = _hub(site, cams, _ownership(cams, skip=cams[20:22], norecord=cams[22:25]))
    sub = _text(re.search(r'<p class="ax-sub">(.*?)</p>', raw, re.S).group(1))
    assert sub.startswith("27 cameras on the map. 22 are joined to the owner of record")
    assert sub.endswith("3 stand where the tax roll has no parcel to join and 2 have not been looked up yet.")
    own = _text(re.search(r'<section class="card ax-own".*?</section>', raw, re.S).group(0))
    assert "22 of the 27 mapped cameras" in own
    assert "Of the rest, 3 stand where the tax roll has no parcel to join and 2 have not been looked up yet." in own
    # the three kinds of row say three different things
    assert raw.count("In a road or right of way: no titled parcel within 60 meters.") == 3
    assert raw.count("Land owner not looked up yet.") == 2


def test_hub_says_all_joined_when_all_are_and_types_no_number(site):
    cams = _county()
    raw = _hub(site, cams, _ownership(cams))
    sub = _text(re.search(r'<p class="ax-sub">(.*?)</p>', raw, re.S).group(1))
    assert sub.startswith("All 27 mapped cameras, each joined to the owner of record")
    assert "Of the rest" not in raw and "not looked up" not in raw.lower()
    for stale in ("the other 187", "187 are", "mapped with no owner record yet"):
        assert stale not in raw


def test_hub_links_the_town_pages_it_built_and_no_others(site):
    cams = _county()
    raw = _hub(site, cams, _ownership(cams))
    block = re.search(r'<section class="card ax-towns" id="towns">.*?</section>', raw, re.S).group(0)
    # Ridgecrest, Tehachapi, then Stallion Springs, which is on the Tehachapi page
    assert re.findall(r'href="([^"]+)"', block) == ["ridgecrest/", "tehachapi/", "tehachapi/"]
    # before the county join there is no block at all
    raw = _hub(site, cams, _ownership(cams[:12]))
    assert 'id="towns"' not in raw


def test_hub_counts_every_camera_once_by_place_and_lists_every_city(site):
    """Every city has its answer on the hub, the ones with no page and the ones with no camera
    too, and the column sums to the camera list."""
    cams = _county()
    own = _ownership(cams)
    site.install(own)
    rows = alpr_towns.place_rows(_sources(cams))
    assert sum(r["n"] for r in rows) == len(cams) == 27
    got = {r["name"]: (r["n"], r["near"]) for r in rows}
    assert {n for n, r in zip(got, rows) if r["kind"] == "city"} == {
        "Arvin", "Bakersfield", "California City", "Delano", "Maricopa", "McFarland",
        "Ridgecrest", "Shafter", "Taft", "Tehachapi", "Wasco"}
    assert got["Ridgecrest"] == (12, 0) and got["Tehachapi"] == (7, 1)
    assert got["Maricopa"] == (3, 0) and got["Arvin"] == (0, 0)
    # a community is listed only when it holds a camera, and has no "just outside" count
    assert got["Stallion Springs"] == (2, None) and "Golden Hills" not in got
    # the Grapevine pair and the one outside Tehachapi are in no place, and are the last row
    assert rows[-1] == {"name": None, "kind": None, "n": 3, "near": None}
    block = _text(re.search(r'<section class="card ax-towns" id="towns">.*?</section>',
                            _hub(site, cams, own), re.S).group(0))
    assert "All 11 incorporated cities in Kern County are listed" in block
    assert "Maricopa city 3 0" in block and "Arvin city 0 0" in block
    assert "Stallion Springs unincorporated, on the Tehachapi map 2" in block
    assert "In no city or Census place 3" in block and "Kern County 27" in block


def test_unresearched_owner_count_is_stated_once_from_the_data(site):
    cams = _county()
    raw = _hub(site, cams, _ownership(cams))
    src = _text(re.search(r'<section class="card ax-sources".*?</section>', raw, re.S).group(0))
    assert ("For 2 of the 2 owners, the company record and the contact routes have not been "
            "researched yet.") in src


# ------------------------------------------------------------------ the record script
def test_record_script_never_says_looked_and_found_nothing_for_an_unresearched_owner():
    js = (Path(__file__).resolve().parents[1] / "assets" / "js" / "alpr-explorer.js").read_text(encoding="utf-8")
    assert js.count('"not_researched"') >= 2
    # the unresearched branch comes before the "No registry page matched" and "not public" copy
    assert js.index("has not been looked up yet") < js.index("No registry page matched this name")
    assert js.index("have not been researched yet") < js.index("That means the record is not")
    # a camera in Ridgecrest is not "outside city limits", and no owner's cameras are "in Bakersfield"
    assert "in Bakersfield" not in js
    assert "placeChip(o)" in js and "NOREC[id]" in js
    assert alpr_page.norecord_line({"reason": "no_parcel_60m"}) in js


# ------------------------------------------------------------------ the built site
SITE = Path(__file__).resolve().parents[1] / "site"


@pytest.mark.skipif(not (SITE / "surveillance" / "index.html").exists(), reason="site not built")
def test_built_town_pages_are_in_the_sitemap_and_linked_both_ways():
    hub = (SITE / "surveillance" / "index.html").read_text(encoding="utf-8")
    sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    redirects = (SITE / "_redirects").read_text(encoding="utf-8")
    pages = sorted(p.parent.name for p in (SITE / "surveillance").glob("*/index.html"))
    assert set(pages) <= set(alpr_towns.TOWNS)
    for slug in alpr_towns.TOWNS:
        url = f"https://bakersfieldbrief.com/surveillance/{slug}/"
        if slug in pages:
            raw = (SITE / "surveillance" / slug / "index.html").read_text(encoding="utf-8")
            assert f"<loc>{url}</loc>" in sitemap
            assert f'href="{slug}/"' in hub
            assert 'href="../../surveillance/"' in raw
            assert f'<link rel="canonical" href="{url}">' in raw
            assert f"/surveillance/{slug}/ " not in redirects
        else:
            assert url not in sitemap and f'href="{slug}/"' not in hub
            assert f"/surveillance/{slug}/  /surveillance/  302" in redirects
