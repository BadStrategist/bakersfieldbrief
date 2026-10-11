#!/usr/bin/env python3
"""Tests for /traffic-cameras/: the Caltrans CCTV source, the page, the camera blocks on the
road trackers, and the Pages Function that proxies the stills.

Fixtures are the two Caltrans feeds exactly as served on 2026-10-11
(tests/fixtures/cctvStatusD06_2026-10-11.json, cctvStatusD09_2026-10-11.json): 44 Kern County
cameras, 43 in service, and one that is not, `SR-58 : Cameron Road`.

Run:  .venv/Scripts/python.exe -m pytest tests/test_traffic_cameras.py -q
Fully offline. The function tests need node and are skipped without it.
"""
from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import common  # noqa: E402
from build.builders import (fog_delays, grapevine, home, roads, tehachapi,  # noqa: E402
                            traffic_cameras)
from build.sources import cameras  # noqa: E402
from build.sources import roads as roads_src  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FEEDS = {"6": "cctvStatusD06_2026-10-11.json", "9": "cctvStatusD09_2026-10-11.json"}
DEAD = "sr58cameronroad"
LONG_DASHES = ("\u2014", "&mdash;", "&#8212;", "&#x2014;")

# Everything this work wrote. The site stylesheet is checked from its camera section on.
OWN_FILES = ("build/sources/cameras.py", "build/builders/traffic_cameras.py",
             "functions/api/cameras.js", "assets/js/cameras.js", "assets/js/webmcp-cameras.js",
             "tests/test_traffic_cameras.py")


def _feed(district: str) -> dict:
    return json.loads((FIX / FEEDS[district]).read_text(encoding="utf-8"))


def _cams() -> list:
    return cameras.kern(_feed("6")) + cameras.kern(_feed("9"))


def _feed_urls() -> set:
    return {row["cctv"]["imageData"]["static"]["currentImageURL"]
            for d in FEEDS for row in _feed(d)["data"]}


def _route(slug: str, text: str) -> dict:
    """One Caltrans route as roads.py parses it, from a single Central California section."""
    route = next(r for r in roads_src.ROUTES if r["slug"] == slug)
    page = (f"<p>latest reported as of Sunday, October 11th, 2026 at 08:33 AM. </p>"
            f"[IN THE CENTRAL CALIFORNIA AREA] {text}")
    return roads_src._parse(page, route)


QUIET = "No traffic restrictions are reported for this area."


def _roads(i5=QUIET, sr58=QUIET, sr99=QUIET) -> dict:
    return {"ok": True, "asof": "2026-10-11", "log": [],
            "routes": [_route("i5", i5), _route("sr58", sr58), _route("sr99", sr99)]}


def _sources(**over) -> dict:
    src = {"cameras": {"ok": True, "cameras": _cams(), "asof": "2026-10-11", "log": [],
                       "log_started": "2026-10-11"},
           "roads": _roads(), "weather": {"ok": True, "alerts": []}}
    src.update(over)
    return src


def _build(monkeypatch, tmp_path, builder=traffic_cameras, path="traffic-cameras", **over):
    monkeypatch.setattr(common, "SITE", tmp_path)
    ctx = types.SimpleNamespace(today=common.today_pacific(), build_report={}, statusbar="")
    builder.build(ctx, _sources(**over))
    return (tmp_path / path / "index.html").read_text(encoding="utf-8"), ctx


def _main(page: str) -> str:
    return page[page.index("<main>"):page.index("</main>")]


def _card(page: str, cid: str) -> str:
    m = re.search(rf'<li class="cam[^"]*" id="cam-{cid}".*?</li>', page, re.S)
    assert m, f"no card for {cid}"
    return m.group(0)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# ---------------------------------------------------------------- the source
def test_kern_filter_returns_44_cameras_from_both_districts():
    d6, d9 = cameras.kern(_feed("6")), cameras.kern(_feed("9"))
    assert (len(d6), len(d9)) == (34, 10)
    cams = d6 + d9
    assert len(cams) == 44
    assert len({c["id"] for c in cams}) == 44
    out = [c for c in cams if not c["in_service"]]
    assert [c["caltrans_name"] for c in out] == ["SR-58 : Cameron Road"]
    assert sum(c["in_service"] for c in cams) == 43
    # nothing outside Kern County leaks in from the 151 rows the two feeds carry
    assert len(_feed("6")["data"]) == 128 and len(_feed("9")["data"]) == 23


def test_image_urls_come_only_from_the_parsed_json():
    """Every picture address is one Caltrans published. None is assembled from a name."""
    published = _feed_urls()
    for c in _cams():
        assert c["image_url"] in published
        assert cameras.camera_id(c["image_url"]) == c["id"]
    # No file this work wrote holds the pieces a constructed address would need.
    for rel in OWN_FILES[:5]:
        src = (ROOT / rel).read_text(encoding="utf-8")
        for piece in ("cctv/image", ".jpg\"", ".jpg'", "/previous/"):
            assert piece not in src, f"{rel} holds {piece!r}: is an image address being built?"


def test_an_address_that_is_not_caltrans_is_dropped():
    row = _feed("6")["data"][0]["cctv"]
    row["imageData"]["static"]["currentImageURL"] = "https://example.com/x/evil.jpg"
    cam = cameras.normalize(row)
    assert cam["image_url"] == ""
    assert "example.com" not in traffic_cameras.card(cam)
    assert "Picture unavailable right now" in traffic_cameras.card(cam)


def test_four_cameras_on_one_pole_get_four_different_names():
    pole = [c for c in _cams() if c["route"] == "US-395"]
    assert len(pole) == 4 and len({(c["lat"], c["lon"]) for c in pole}) == 1
    assert len({c["label"] for c in pole}) == 4
    assert all("looking" in c["label"] or "look " in c["label"] for c in pole)


def test_names_expand_caltrans_shorthand_and_keep_the_feed_name():
    by = {c["id"]: c for c in _cams()}
    assert by["ker99atrosedalehwyroute178"]["label"] == "SR-99 at Rosedale Highway (Route 178)"
    assert by["ker5norte119"]["label"] == "I-5 north of Route 119"
    assert by["sr58tehachapisummit"]["label"] == "SR-58 at Tehachapi Summit"
    assert by["ker99sorte46"]["near"] == "McFarland"
    assert by["ker5norte119"]["caltrans_name"] == "KER-5-N/O RTE 119"


class _Reply:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _patch_feeds(monkeypatch, tmp_path, down=()):
    monkeypatch.setattr(common, "SNAP", tmp_path)
    monkeypatch.setattr(common, "LOGS", tmp_path)

    def fetch(url, **kw):
        for district, feed_url in cameras.FEEDS:
            if url == feed_url:
                if district in down:
                    raise OSError("feed down")
                return _Reply(_feed(district))
        raise AssertionError(f"unexpected fetch: {url}")
    monkeypatch.setattr(common, "fetch", fetch)


def test_run_reads_both_feeds_and_logs_nothing_on_the_first_run(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch, tmp_path)
    out = cameras.run(None)
    assert out["ok"] and len(out["cameras"]) == 44 and out["log"] == []
    assert not (tmp_path / "cameras.json").exists()      # no baseline, so no invented change


def test_change_log_records_a_camera_going_out_and_coming_back(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch, tmp_path)
    cameras.run(None)
    snap = json.loads((tmp_path / "cameras_last.json").read_text(encoding="utf-8"))
    for c in snap["cameras"]:
        if c["id"] == DEAD:
            c["in_service"] = True                       # it was in service last time
        if c["id"] == "ker58athst":
            c["in_service"] = False                      # and this one was out
    (tmp_path / "cameras_last.json").write_text(json.dumps(snap), encoding="utf-8")
    out = cameras.run(None)
    changes = {e["id"]: e["change"] for e in out["log"]}
    assert changes == {DEAD: "out of service", "ker58athst": "back in service"}
    assert json.loads((tmp_path / "cameras.json").read_text(encoding="utf-8")) == out["log"]


def test_one_feed_down_keeps_that_districts_last_cameras(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch, tmp_path)
    cameras.run(None)
    _patch_feeds(monkeypatch, tmp_path, down=("9",))
    out = cameras.run(None)
    assert out["ok"] and len(out["cameras"]) == 44 and out["stale_districts"] == ["9"]
    assert out["log"] == []                               # a feed that was not read logs nothing


def test_both_feeds_down_falls_back_to_the_last_good_list(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch, tmp_path)
    cameras.run(None)
    _patch_feeds(monkeypatch, tmp_path, down=("6", "9"))
    out = cameras.run(None)
    assert out["ok"] is False and out["stale"] and out["last_good"]
    assert len(out["cameras"]) == 44


def test_both_feeds_down_with_no_last_list_is_reported_not_raised(monkeypatch, tmp_path):
    _patch_feeds(monkeypatch, tmp_path, down=("6", "9"))
    out = cameras.run(None)
    assert out["ok"] is False and out["cameras"] == []


# ---------------------------------------------------------------- the page
def test_page_states_the_answer_and_the_caltrans_time_in_plain_html(monkeypatch, tmp_path):
    page, ctx = _build(monkeypatch, tmp_path, roads=_roads(
        i5="A high wind advisory is in effect from Lebec to Grapevine /in Lebec/ (Kern Co)."))
    main = _main(page)
    answer = _text(re.search(r'<p class="answer".*?</p>', main, re.S).group(0))
    assert answer.startswith("As of Sunday, October 11th, 2026 at 08:33 AM, Caltrans reports: "
                             "I-5 over Tejon Pass is open with restrictions; ")
    assert "SR-58 over Tehachapi Pass is clear of reported problems" in answer
    assert 'Caltrans road report: <span class="updated">Sunday, October 11th, 2026 at 08:33 AM' in main
    # the answer comes before the first camera, and neither needs a script to appear
    assert main.index('class="answer"') < main.index('class="cam"')
    assert "<h1>Bakersfield traffic cameras and Kern County road status</h1>" in main
    assert ctx.build_report["traffic_cameras"] == {"ok": True, "cameras": 44, "in_service": 43,
                                                   "stale": False}


@pytest.mark.parametrize("text, status", [
    ("Is closed from Grapevine to Lebec /in Lebec/ (Kern Co) - Due to snow.", "CLOSED"),
    ("Chains are required from Lebec to Gorman /in Lebec/ (Kern Co).", "RESTRICTIONS"),
])
def test_status_wording_is_the_grapevine_pages_spoken_form(monkeypatch, tmp_path, text, status):
    spoken = grapevine._STATUS_COPY[status][3]
    page, _ = _build(monkeypatch, tmp_path, roads=_roads(i5=text))
    assert f"I-5 over Tejon Pass is {spoken}" in _text(_main(page))
    # and the Grapevine page, built from the same report, says the same words
    gv, _ = _build(monkeypatch, tmp_path, builder=grapevine, path="grapevine", roads=_roads(i5=text))
    assert f"I-5 over Tejon Pass is <span class=\"{grapevine._STATUS_COPY[status][1]}\">{spoken}</span>" in gv
    # never the badge word used as a verb phrase
    assert "is Restrictions" not in page and "is Closed" not in page


def test_no_problem_and_pre_scope_states_use_the_shared_wording(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path)
    text = _text(_main(page))
    for prose in ("I-5 over Tejon Pass", "SR-58 over Tehachapi Pass", "SR-99 through the Central Valley"):
        assert f"{prose} is {grapevine.NO_PROBLEM_SPOKEN}" in text
    legacy = _roads()
    for r in legacy["routes"]:
        r.pop("scope")                                   # a snapshot from before corridor scoping
    page, _ = _build(monkeypatch, tmp_path, roads=legacy)
    assert f"I-5 over Tejon Pass is {grapevine._STATUS_COPY['OPEN'][3]}." in _text(_main(page))


def test_chain_control_is_named_only_when_caltrans_names_it_on_a_corridor(monkeypatch, tmp_path):
    quiet, _ = _build(monkeypatch, tmp_path)
    assert "Chain control: none is named on these three corridors" in _text(_main(quiet))
    chains, _ = _build(monkeypatch, tmp_path, roads=_roads(
        i5="Chains are required from Lebec to Gorman /in Lebec/ (Kern Co)."))
    assert "Chain control: Caltrans names chains on I-5 over Tejon Pass" in _text(_main(chains))


def test_road_report_unreadable_claims_no_status_and_keeps_the_cameras(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path, roads={"ok": False, "error": "boom"})
    main = _main(page)
    assert "could not be read when this page was built" in main
    assert "is open" not in main and "clear of reported problems" not in main
    assert "boom" not in page
    assert main.count('<li class="cam') == 44


def test_every_camera_has_a_card_and_only_in_service_ones_have_a_picture(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path)
    main = _main(page)
    assert main.count('<li class="cam') == 44
    assert main.count("<img ") == 43
    assert "44 Caltrans cameras in Kern County: 43 in service, 1 out of service" in main
    for c in _cams():
        card = _card(main, c["id"])
        assert c["name"] in html.unescape(card) and c["route"] in card
        if c["in_service"]:
            assert f'src="/api/cameras?img={c["id"]}"' in card
            assert "New picture about every" in card      # the frame's schedule, before any script
    # the picture never points at Caltrans directly, and never at a made-up file name
    assert "cwwp2.dot.ca.gov" not in main


def test_out_of_service_camera_says_so_and_never_prints_a_zero(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path)
    card = _card(_main(page), DEAD)
    assert 'class="cam is-out"' in card
    assert 'data-caltrans-name="SR-58 : Cameron Road"' in card
    assert "<img" not in card and "/api/cameras" not in card      # nothing to break
    text = _text(card)
    assert text == ("Out of service Cameron Road SR-58 East · near Mojave "
                    "Caltrans lists this camera as out of service.")
    assert not re.search(r"(?<![\w-])0(?![\w.])", text) and "--" not in text


def test_failing_image_renders_the_unavailable_state_not_a_blank_frame(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path)
    main = _main(page)
    live = [c for c in _cams() if c["in_service"]]
    for c in live:
        card = _card(main, c["id"])
        # the failure path is on the image itself, so it works before any script file loads
        assert "onerror=\"this.closest('.cam').classList.add('is-error')\"" in card
        assert '<span class="cam-flag">Picture unavailable right now</span>' in card
        # and the card still names the camera, its route and its place
        assert c["name"] in html.unescape(card) and c["near"] in card
    css = (ROOT / "assets/css/site.css").read_text(encoding="utf-8")
    assert ".cam.is-out .cam-flag, .cam.is-error .cam-flag { display: block; }" in css
    assert ".cam.is-error .cam-pic img { display: none; }" in css
    assert re.search(r"\.cam-flag \{\s*display: none;", css)          # hidden until a picture fails
    js = (ROOT / "assets/js/cameras.js").read_text(encoding="utf-8")
    assert 'card.classList.add("is-error")' in js and "Picture time not available" in js


def test_camera_list_unreadable_prints_no_count_and_no_cards(monkeypatch, tmp_path):
    page, ctx = _build(monkeypatch, tmp_path, cameras={"ok": False, "cameras": [], "error": "boom"})
    main = _main(page)
    assert "camera list could not be read when this page was built" in main
    assert '<li class="cam' not in main and "boom" not in page
    assert not re.search(r"\b0 (Caltrans )?cameras?\b", main)
    assert '"@type": "ItemList"' not in page
    assert ctx.build_report["traffic_cameras"]["ok"] is False


def test_stale_camera_list_keeps_every_name_and_says_which_list_it_is(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path, cameras={
        "ok": False, "last_good": True, "stale": True, "cameras": _cams(), "asof": "2026-10-09",
        "log": []})
    main = _main(page)
    assert main.count('<li class="cam') == 44
    assert "from the last list this page read, on 2026-10-09" in main


def test_update_schedule_is_read_from_the_feed(monkeypatch, tmp_path):
    # District 6 lists 1 minute, District 9 lists 5 and 20: the page must not call them all one.
    assert traffic_cameras.frequency_sentence(_cams()) == (
        "Caltrans replaces these pictures on its own schedule: 34 about every minute, "
        "5 about every 5 minutes and 4 about every 20 minutes.")
    page, _ = _build(monkeypatch, tmp_path)
    assert 'data-every="20"' in _card(page, "us395northofsr141")
    assert "New picture about every 20 minutes" in _card(page, "us395northofsr141")


def _blocks(page: str) -> list:
    return [json.loads(b) for b in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]


def test_jsonld_has_breadcrumb_faq_and_the_ordered_camera_list(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path)
    by_type = {b["@type"]: b for b in _blocks(page)}
    assert {"NewsMediaOrganization", "WebSite", "WebPage", "FAQPage", "ItemList",
            "BreadcrumbList"} <= set(by_type)
    crumbs = [i["name"] for i in by_type["BreadcrumbList"]["itemListElement"]]
    assert crumbs == ["Daily Brief", "Trackers", "Traffic cameras"]
    items = by_type["ItemList"]["itemListElement"]
    assert by_type["ItemList"]["numberOfItems"] == len(items) == 44
    assert [i["position"] for i in items] == list(range(1, 45))
    visible = _text(_main(page))
    main = _main(page)
    for i in items:
        cid = i["url"].rsplit("#cam-", 1)[1]
        assert f'id="cam-{cid}"' in main                  # every listed camera is on the page
        assert f'data-label="{html.escape(i["name"])}"' in main
    # the cards appear in the order the list gives them
    order = re.findall(r'<li class="cam[^"]*" id="cam-([^"]+)"', main)
    assert order == [i["url"].rsplit("#cam-", 1)[1] for i in items]
    for q in by_type["FAQPage"]["mainEntity"]:
        assert q["name"] in visible
        assert q["acceptedAnswer"]["text"] in visible     # only facts that are on the page


def test_no_em_dash_in_the_page_the_blocks_or_the_templates(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path, roads=_roads(
        i5="A high wind advisory is in effect from Lebec to Grapevine /in Lebec/ (Kern Co) "
           "\u2014 use caution."),
        weather={"ok": True, "alerts": [{"event": "Dense Fog Advisory",
                                         "headline": "Dense Fog Advisory \u2014 until 10 AM"}]})
    for dash in LONG_DASHES:
        assert dash not in page, f"long dash {dash!r} in /traffic-cameras/"
    assert "Dense Fog Advisory, until 10 AM" in page      # source text is rewritten, not dropped
    for kind in ("grapevine", "tehachapi", "roads"):
        block = traffic_cameras.block(_sources(), "../", kind)
        assert block and not any(d in block for d in LONG_DASHES)
    for tpl in sorted((ROOT / "templates").glob("*.html")):
        src = tpl.read_text(encoding="utf-8")
        for dash in LONG_DASHES:
            assert dash not in src, f"long dash {dash!r} in templates/{tpl.name}"
    for rel in OWN_FILES:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "\u2014" not in src, f"long dash in {rel}"
    css = (ROOT / "assets/css/site.css").read_text(encoding="utf-8")
    assert "\u2014" not in css[css.index("Caltrans camera cards"):]


def test_page_never_borrows_from_the_surveillance_page(monkeypatch, tmp_path):
    page, _ = _build(monkeypatch, tmp_path)
    main = _main(page).lower()
    for word in ("flock", "alpr", "deflock", "openstreetmap", "tracker-data"):
        assert word not in main
    assert 'href="../surveillance/"' not in main
    assert "color-scheme" in page and "prefers-color-scheme" not in page


# ---------------------------------------------------------------- blocks and links
def test_tracker_blocks_show_the_right_cameras(monkeypatch, tmp_path):
    src = _sources()
    ids = lambda kind: re.findall(r'id="cam-([^"]+)"', traffic_cameras.block(src, "../", kind))  # noqa: E731
    assert ids("grapevine") == ["ker5attruckescaperampshoulder", "ker5attruckescaperampmedian",
                                "ker5atgrapevineuc", "ker5atrte99"]
    assert ids("tehachapi") == ["ker58attowerlinerd", "sr58broomeroad", "sr58tehachapisummit",
                                DEAD, "sr58cachecreek"]
    assert ids("roads") == ["ker5attruckescaperampshoulder", "sr58tehachapisummit",
                            "ker99atcaliforniaave"]
    assert "Out of service" in traffic_cameras.block(src, "../", "tehachapi")
    assert traffic_cameras.block({}, "../", "grapevine") == ""        # no list, no block


@pytest.mark.parametrize("builder, path", [(grapevine, "grapevine"), (roads, "roads"),
                                           (tehachapi, "tehachapi-pass"),
                                           (fog_delays, "fog-delays")])
def test_tracker_pages_link_to_the_camera_page(monkeypatch, tmp_path, builder, path):
    page, _ = _build(monkeypatch, tmp_path, builder=builder, path=path,
                     alertline={"ok": True, "alerts": [], "log": {"days": {}}, "fetched_at": ""},
                     tehachapi_weather={"ok": False})
    assert 'href="../traffic-cameras/"' in _main(page)
    if builder is not fog_delays:
        assert "assets/js/cameras.js" in page and 'class="block cam-block"' in page


def test_home_band_footers_and_discovery_files_link_to_the_camera_page(monkeypatch, tmp_path):
    band, _ = home._night("", {}, "2026-10-11")
    assert '<a href="traffic-cameras/">Traffic cameras</a>' in band
    for tpl in ("layout.html", "home.html"):
        assert 'traffic-cameras/">Kern traffic cameras</a>' in (ROOT / "templates" / tpl).read_text(encoding="utf-8")
    import build.build_all as build_all
    page, _ = _build(monkeypatch, tmp_path)
    build_all._sitemap()
    build_all._llms()
    build_all._agentic_sitemap({})
    assert "<loc>https://bakersfieldbrief.com/traffic-cameras/</loc>" in (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://bakersfieldbrief.com/traffic-cameras/" in (tmp_path / "llms.txt").read_text(encoding="utf-8")
    assert "<loc>https://bakersfieldbrief.com/traffic-cameras/</loc>" in (
        tmp_path / "sitemap_agentic_discovery.xml").read_text(encoding="utf-8")


def test_no_video_anywhere():
    """Stills only. No player, no playlist address, not even behind a flag."""
    for rel in OWN_FILES[:5]:
        src = (ROOT / rel).read_text(encoding="utf-8").lower()
        for word in ("streamingvideourl", "m3u8", "wzmedia", "hls", "<video"):
            assert word not in src, f"{rel} mentions {word}"
    assert "streamingVideoURL" not in json.dumps(_cams())


# ---------------------------------------------------------------- the Pages Function
HARNESS = r"""
import { readFileSync } from "node:fs";
const [fnPath, d6Path, d9Path, scenario] = process.argv.slice(2);
const feeds = {
  "https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.json": readFileSync(d6Path, "utf8"),
  "https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.json": readFileSync(d9Path, "utf8"),
};
const asked = [];
const store = new Map();
globalThis.caches = { default: {
  match: async (req) => { const hit = store.get(req.url); return hit ? hit.clone() : undefined; },
  put: async (req, resp) => { store.set(req.url, resp.clone()); },
} };
globalThis.fetch = async (url) => {
  url = String(url);
  asked.push(url);
  if (feeds[url]) {
    if (scenario === "feeds_down") throw new Error("down");
    return new Response(feeds[url], { status: 200, headers: { "Content-Type": "application/json" } });
  }
  if (scenario === "image_404") return new Response("nope", { status: 404 });
  if (scenario === "image_html") return new Response("<html>", { status: 200, headers: { "Content-Type": "text/html" } });
  return new Response(new Uint8Array([255, 216, 255]), { status: 200,
    headers: { "Content-Type": "image/jpeg", "Last-Modified": "Sun, 11 Oct 2026 22:56:32 GMT" } });
};
const src = readFileSync(fnPath, "utf8");
const mod = await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"));
const pending = [];
const call = async (query) => {
  const resp = await mod.onRequestGet({
    request: new Request("https://bakersfieldbrief.com/api/cameras" + query), env: {},
    waitUntil: (p) => pending.push(p) });
  await Promise.all(pending.splice(0));
  const type = resp.headers.get("Content-Type") || "";
  return { status: resp.status, type, cache: resp.headers.get("Cache-Control"),
           modified: resp.headers.get("Last-Modified"), state: resp.headers.get("X-Camera-State"),
           body: type.includes("json") ? await resp.json() : null };
};
const out = {};
out.list = await call("");
out.good = await call("?img=ker5attruckescaperampshoulder");
out.good_asked = asked.filter((u) => !feeds[u]).slice();
out.again = await call("?img=ker5attruckescaperampshoulder");
out.image_requests_after_second_call = asked.filter((u) => !feeds[u]).length;
out.dead = await call("?img=sr58cameronroad");
out.unknown = await call("?img=notacamera");
out.bad = await call("?img=../../etc/passwd");
out.feed_requests = asked.filter((u) => feeds[u]).length;
console.log(JSON.stringify(out));
"""


def _run_function(tmp_path, scenario: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    res = subprocess.run(
        [node, str(harness), str(ROOT / "functions/api/cameras.js"),
         str(FIX / FEEDS["6"]), str(FIX / FEEDS["9"]), scenario],
        capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_function_lists_the_same_44_cameras_with_the_same_ids(tmp_path):
    out = _run_function(tmp_path, "ok")
    body = out["list"]["body"]
    assert out["list"]["status"] == 200 and body["ok"] and body["count"] == 44
    assert body["in_service"] == 43
    assert sorted(c["id"] for c in body["cameras"]) == sorted(c["id"] for c in _cams())
    assert "image_url" not in json.dumps(body)            # the list hands out no Caltrans address


def test_function_fetches_exactly_the_address_caltrans_published(tmp_path):
    out = _run_function(tmp_path, "ok")
    want = next(c["image_url"] for c in _cams() if c["id"] == "ker5attruckescaperampshoulder")
    assert out["good_asked"] == [want]
    assert (out["good"]["status"], out["good"]["type"]) == (200, "image/jpeg")
    assert out["good"]["cache"] == "public, max-age=60"
    assert out["good"]["modified"] == "Sun, 11 Oct 2026 22:56:32 GMT"   # Caltrans' own frame time
    # the second request inside the minute is served from the edge, not from Caltrans
    assert out["again"]["status"] == 200 and out["image_requests_after_second_call"] == 1
    assert out["feed_requests"] == 2                      # both feeds read once, then held


def test_function_gives_no_picture_for_a_dead_unknown_or_malformed_camera(tmp_path):
    out = _run_function(tmp_path, "ok")
    assert (out["dead"]["status"], out["dead"]["state"]) == (404, "out_of_service")
    assert (out["unknown"]["status"], out["unknown"]["state"]) == (404, "unknown_camera")
    assert (out["bad"]["status"], out["bad"]["state"]) == (400, "bad_id")


@pytest.mark.parametrize("scenario, state", [("image_404", "http_404"),
                                             ("image_html", "not_an_image"),
                                             ("feeds_down", "list_unreachable")])
def test_function_turns_a_failed_picture_into_an_error_the_page_can_show(tmp_path, scenario, state):
    out = _run_function(tmp_path, scenario)
    # an error status is what fires the <img> onerror and the card's unavailable state
    assert (out["good"]["status"], out["good"]["state"]) == (502, state)
    assert out["good"]["type"].startswith("application/json")
    if scenario != "feeds_down":
        # the failure is remembered, so the retry does not go back to Caltrans
        assert out["again"]["status"] == 502 and out["image_requests_after_second_call"] == 1
    else:
        assert out["list"]["body"] == {"ok": False, "status": "list_unreachable"}


def test_harness_source_is_valid_base64_input():
    # guards the data: URL import above against a non-ASCII byte creeping into the function
    src = (ROOT / "functions/api/cameras.js").read_bytes()
    assert base64.b64decode(base64.b64encode(src)) == src and src.isascii()
