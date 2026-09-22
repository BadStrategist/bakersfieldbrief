"""Guards for /surveillance/, the only ALPR page on the site.

The page carries a ranking we do not want to lose: its title, h1, h2, h3s, the four original FAQ
questions and their schema twins, the canonical and the social tags. The land ownership explorer
lives inside it; nothing may publish the explorer as a second url or link to one.

Runs against the built site/ (CI runs pytest after build_all.py). A checkout with no build skips.
"""
import html
import json
import pathlib
import re

import pytest

SITE = pathlib.Path(__file__).resolve().parents[1] / "site"
PAGE = SITE / "surveillance" / "index.html"

pytestmark = pytest.mark.skipif(not PAGE.exists(), reason="site not built in this checkout")


def _page():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s))).strip()


def _jsonld(raw):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, re.S)]


def test_title_headings_and_canonical_kept():
    raw = _page()
    assert "<title>Bakersfield Flock Camera Map | Live ALPR Tracker</title>" in raw
    assert '<link rel="canonical" href="https://bakersfieldbrief.com/surveillance/">' in raw
    h1 = [_text(x) for x in re.findall(r"<h1[^>]*>(.*?)</h1>", raw, re.S)]
    assert h1 == ["Flock Camera Map — Bakersfield"]
    h2 = [_text(x) for x in re.findall(r"<h2[^>]*>(.*?)</h2>", raw, re.S)]
    assert "Newest cameras" in h2
    h3 = [_text(x) for x in re.findall(r"<h3[^>]*>(.*?)</h3>", raw, re.S)]
    assert "Flock & ALPRs · Kern County" in h3
    assert "What this tracker shows" in h3
    for tag in ('property="og:url" content="https://bakersfieldbrief.com/surveillance/"',
                'property="og:title"', 'name="twitter:card"', 'name="robots" content="index, follow"'):
        assert tag in raw, tag


def test_faq_visible_and_schema_agree():
    raw = _page()
    blocks = _jsonld(raw)
    types = {b.get("@type") for b in blocks}
    assert {"NewsMediaOrganization", "WebSite", "WebPage", "FAQPage"} <= types
    faq = next(b for b in blocks if b.get("@type") == "FAQPage")
    schema_q = [q["name"] for q in faq["mainEntity"]]
    visible_q = [_text(x).removeprefix("Q: ") for x in re.findall(r'<p class="pr-q">(.*?)</p>', raw, re.S)]
    assert schema_q == visible_q
    for q in ("How many Flock cameras are in Bakersfield?", "Where are the Flock cameras in Bakersfield?",
              "Are Flock cameras legal in California?", "How long do Flock cameras keep data?"):
        assert q in schema_q, q


def test_no_second_alpr_page():
    assert not (SITE / "alpr-explorer").exists()
    assert "alpr-explorer" not in (SITE / "sitemap.xml").read_text(encoding="utf-8")
    offenders = [p.relative_to(SITE).as_posix() for p in SITE.rglob("*.html")
                 if re.search(r'href="[^"]*alpr-explorer', p.read_text(encoding="utf-8", errors="ignore"))]
    assert not offenders, offenders


def test_explorer_is_on_the_page_and_crawlable():
    raw = _page()
    assert 'id="explorer"' in raw and 'id="alpr-map"' in raw
    assert "<iframe" not in raw
    assert "alpr-explorer.js" in raw and "webmcp-alpr.js" in raw and 'id="tracker-data"' in raw
    payload = json.loads(re.search(r'<script type="application/json" id="tracker-data">(.*?)</script>', raw, re.S).group(1))
    cams = payload["cameras"]
    # every mapped camera is a server-rendered list item, so the records are readable without JS
    items = re.findall(r'<li class="ax-item" data-id="(\d+)"', raw)
    assert sorted(items) == sorted(str(c["id"]) for c in cams)
    # the stat row appears once, not twice
    assert raw.count('<div class="stats">') == 1


def test_ownership_numbers_agree():
    raw = _page()
    stats_p = SITE.parent / "data" / "alpr" / "explorer_stats.json"
    data_p = SITE.parent / "data" / "alpr" / "explorer_data.json"
    if not (stats_p.exists() and data_p.exists()):
        pytest.skip("no ownership data in this checkout")
    st = json.loads(stats_p.read_text(encoding="utf-8"))
    d = json.loads(data_p.read_text(encoding="utf-8"))
    assert st["owners"] == len(d["owners"]) and st["parcels"] == len(d["parcels"]) and st["cameras"] == len(d["cams"])
    own = re.search(r'<section class="card ax-own".*?</section>', raw, re.S).group(0)
    assert f"{st['owners']} owners of record" in _text(own)
    assert f"{st['parcels']} parcels" in _text(own)
    asset = SITE / "assets" / "alpr" / "ownership.json"
    assert asset.exists()
    assert re.search(r'data-src="\.\./assets/alpr/ownership\.json\?v=[0-9a-f]{10}"', raw)


def test_placement_copy_never_overclaims():
    body = _text(_page()).lower()
    for bad in ("the parcel under it", "the land under it", "holds land under", "on their land",
                "the land it stands on"):
        assert bad not in body, bad


def test_private_names_follow_the_switch():
    from build.builders import alpr_explorer
    if alpr_explorer.PUBLISH_PRIVATE_NAMES:
        return
    data_p = SITE.parent / "data" / "alpr" / "explorer_data.json"
    if not data_p.exists():
        pytest.skip("no ownership data in this checkout")
    d = json.loads(data_p.read_text(encoding="utf-8"))
    private = [o["name"] for o in d["owners"] if str(o.get("type", "")).lower() in alpr_explorer.PRIVATE_TYPES]
    raw = _page() + (SITE / "assets" / "alpr" / "ownership.json").read_text(encoding="utf-8")
    leaked = [n for n in private if html.escape(n) in raw or n in raw]
    assert not leaked, leaked[:5]
