#!/usr/bin/env python3
"""Discovery files — every built page must be listed for AI crawlers.

Why this exists: llms.txt and sitemap_agentic_discovery.xml were hand-written
lists. They do not fail loudly when a builder adds a page, so they fell behind:
on 2026-09-19 llms.txt covered 22 of 90 live pages and the agentic sitemap
covered 7 of 90. The pages earning Search Console impressions (the /places/
neighbourhood set, /briefs/ archive, /trackers/, /city-hall/county-board/) were
exactly the ones AI crawlers could not find.

The fix: both files are generated from the pages the build actually wrote, and
these tests pin that. A page added to site/ without appearing in both files
fails here instead of shipping invisible.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build.build_all as build_all  # noqa: E402
from build import common  # noqa: E402

PAGE = ("<!doctype html><html><head><title>{title} | Bakersfield Daily Brief</title>"
        "</head><body><h1>{title}</h1></body></html>")


def _fake_site(tmp_path, pages):
    """Point the build's SITE at a temp dir holding these pages."""
    for path, title in pages.items():
        f = tmp_path / path.strip("/") / "index.html" if path != "/" else tmp_path / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(PAGE.format(title=title), encoding="utf-8")
    return tmp_path


def test_every_built_page_is_in_llms_and_agentic_sitemap(tmp_path, monkeypatch):
    site = _fake_site(tmp_path, {
        "/": "Home",
        "/water/": "Lake Isabella water level",
        "/places/tehachapi/": "Tehachapi",
        "/briefs/2026-09-19/": "The Daily Brief for September 19, 2026",
    })
    monkeypatch.setattr(common, "SITE", site)

    build_all._llms()
    build_all._agentic_sitemap({})

    llms = (site / "llms.txt").read_text(encoding="utf-8")
    agentic = (site / "sitemap_agentic_discovery.xml").read_text(encoding="utf-8")

    for path in ("/", "/water/", "/places/tehachapi/", "/briefs/2026-09-19/"):
        assert f"https://bakersfieldbrief.com{path}" in llms, f"llms.txt misses {path}"
        if path != "/":
            assert f"<loc>https://bakersfieldbrief.com{path}</loc>" in agentic, \
                f"agentic sitemap misses {path}"


def test_agentic_sitemap_keeps_curated_key_entry_point_descriptions(tmp_path, monkeypatch):
    site = _fake_site(tmp_path, {"/roads/": "Road conditions"})
    monkeypatch.setattr(common, "SITE", site)

    build_all._agentic_sitemap({})
    agentic = (site / "sitemap_agentic_discovery.xml").read_text(encoding="utf-8")

    assert "I-5 Grapevine, SR-58 Tehachapi" in agentic, "curated /roads/ description lost"


def test_page_titles_strip_the_site_name_suffix(tmp_path, monkeypatch):
    site = _fake_site(tmp_path, {"/places/tehachapi/": "Tehachapi"})
    monkeypatch.setattr(common, "SITE", site)

    titles = build_all._page_titles()

    assert titles["/places/tehachapi/"] == "Tehachapi"
    assert "Bakersfield Daily Brief" not in titles["/places/tehachapi/"]


def test_agentic_sitemap_escapes_markup_in_titles(tmp_path, monkeypatch):
    site = _fake_site(tmp_path, {"/letters/": "Letters &amp; tips"})
    monkeypatch.setattr(common, "SITE", site)

    build_all._agentic_sitemap({})
    agentic = (site / "sitemap_agentic_discovery.xml").read_text(encoding="utf-8")

    assert "Letters &amp; tips" in agentic
    assert "Letters & tips" not in agentic.replace("Letters &amp; tips", "")


def test_real_built_site_has_no_unlisted_page():
    """Against the repo's own last build, when one exists."""
    site = common.SITE
    if not site.exists() or not any(site.rglob("index.html")):
        return  # no local build; the two tests above still pin the invariant

    llms = (site / "llms.txt").read_text(encoding="utf-8")
    agentic = (site / "sitemap_agentic_discovery.xml").read_text(encoding="utf-8")
    linked = set(re.findall(r"bakersfieldbrief\.com(/[^)\s]*)", llms))
    locs = set(re.findall(r"<loc>https://bakersfieldbrief\.com(/[^<]*)</loc>", agentic))

    for p in site.rglob("index.html"):
        path = "/" + p.relative_to(site).as_posix()[: -len("index.html")]
        assert path in linked, f"llms.txt misses {path}"
        assert path in locs, f"agentic sitemap misses {path}"
