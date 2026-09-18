#!/usr/bin/env python3
"""Site icons — the favicon set must be real crawlable files.

Why this exists: the site shipped its only icon as an inline `data:image/svg+xml`
URI in the layout head. Browsers render that fine, but Google's SERP and
link-preview crawlers do not, so a bakersfieldbrief.com listing showed NO icon
next to the link while every other result had one. Nothing detected it because
nothing was watching the head or the site root.

These tests pin the shape of the fix, all offline:
  * layout.html declares real, root-absolute icon files and no data-URI icon
  * every icon the markup or the web manifest references EXISTS in assets/icons/
  * favicon.ico carries the small sizes and favicon.svg is valid SVG
  * the build copies the whole set into the site root (browsers ask for
    /favicon.ico, so the files cannot live under /assets/)

Run:  .venv/Scripts/python.exe -m pytest tests/test_site_icons.py -q
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build.build_all as build_all  # noqa: E402

LAYOUT = ROOT / "templates" / "layout.html"
ICONS = ROOT / "assets" / "icons"

# every root-relative asset the head or the manifest must point at
ICON_LINK_RE = re.compile(
    r'<link\s+rel="(?:icon|apple-touch-icon|manifest)"[^>]*href="(/[^"]+)"',
    re.I)
ICON_HREF_RE = re.compile(r'<link\s+rel="(?:icon|apple-touch-icon)"[^>]*href="(/[^"]+)"', re.I)


def _layout() -> str:
    return LAYOUT.read_text(encoding="utf-8")


def _referenced_root_files() -> set[str]:
    """Root-relative files the layout shell and site.webmanifest point at."""
    refs = {Path(m).name for m in ICON_LINK_RE.findall(_layout())}
    man = json.loads((ICONS / "site.webmanifest").read_text(encoding="utf-8"))
    for icon in man["icons"]:
        refs.add(Path(icon["src"]).name)
    return refs


# ---------------------------------------------------------------- the head
def test_layout_declares_real_icon_files():
    hrefs = [Path(h).name for h in ICON_HREF_RE.findall(_layout())]
    # the browser's blind request for /favicon.ico must be satisfied by the markup
    assert "favicon.ico" in hrefs, "no rel=icon pointing at /favicon.ico"
    assert any(h.endswith(".svg") for h in hrefs), "no SVG icon (modern browsers)"
    assert any(h.endswith(".png") for h in hrefs), "no PNG icon (Google requires a raster)"
    assert "apple-touch-icon.png" in {Path(h).name for h in
                                      re.findall(r'rel="apple-touch-icon"[^>]*href="(/[^"]+)"', _layout())}


def test_layout_has_no_data_uri_icon():
    """The regression: a data-URI favicon is invisible to crawlers."""
    assert "data:image/svg+xml" not in _layout(), \
        "data-URI icon is back in the layout head; Google cannot read it"
    assert 'rel="shortcut icon"' not in _layout()


def test_icon_links_are_root_absolute():
    """Page depth must not break the icon path (briefs/2026-09-01/ etc.)."""
    for href in ICON_LINK_RE.findall(_layout()):
        assert href.startswith("/"), f"icon href not root-absolute: {href}"


# ---------------------------------------------------------------- the files
def test_every_referenced_icon_file_exists():
    missing = sorted(r for r in _referenced_root_files() if not (ICONS / r).is_file())
    assert not missing, f"markup/manifest reference missing artwork: {missing}"


def test_build_copies_the_files_the_markup_needs():
    """A file the build never copies 404s in production, icon or not."""
    copied = set(build_all.ICON_ROOT_FILES)
    needed = _referenced_root_files()
    assert needed <= copied, f"referenced but not copied by _icons(): {sorted(needed - copied)}"
    for name in copied:
        assert (ICONS / name).is_file(), f"ICON_ROOT_FILES lists a file that does not exist: {name}"


def test_favicon_ico_carries_the_small_sizes():
    from PIL import Image
    with Image.open(ICONS / "favicon.ico") as im:
        sizes = set(im.ico.sizes())
    for want in ((16, 16), (32, 32), (48, 48)):
        assert want in sizes, f"favicon.ico lacks {want[0]}x{want[1]} (has {sorted(sizes)})"


def test_google_sized_pngs_are_square_and_real():
    from PIL import Image
    for name, size in (("icon-96.png", 96), ("icon-512.png", 512),
                       ("apple-touch-icon.png", 180)):
        with Image.open(ICONS / name) as im:
            assert im.size == (size, size), f"{name} is {im.size}, not square {size}x{size}"


def test_favicon_svg_is_valid_square_svg():
    root = ET.parse(ICONS / "favicon.svg").getroot()
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == "0 0 100 100"


def test_manifest_json_is_valid_and_points_at_the_pngs():
    man = json.loads((ICONS / "site.webmanifest").read_text(encoding="utf-8"))
    assert man["name"] and man["icons"]
    for icon in man["icons"]:
        assert icon["src"].startswith("/")
        assert (ICONS / Path(icon["src"]).name).is_file()


def test_jsonld_org_logo_is_the_square_site_icon():
    """schema.org logo dims must match the file we serve (emblem.png is 1200x630)."""
    from build.builders import page as page_mod
    logo = page_mod.org_jsonld()["logo"]
    assert logo["width"] == logo["height"], "org logo must be square"
    assert logo["url"].endswith(f"icon-{logo['width']}.png")
    assert (ICONS / f"icon-{logo['width']}.png").is_file()


def test_publisher_logo_dims_match_the_file_on_disk():
    """A publisher logo that claims 100x100 for a 1200x630 file is a false
    claim Google can drop the logo rich result over. Dims come from disk."""
    from PIL import Image
    from build.builders import page as page_mod
    logo = page_mod.publisher_logo()
    path = ROOT / "assets" / "img" / Path(logo["url"]).name
    with Image.open(path) as im:
        assert (logo["width"], logo["height"]) == im.size, \
            f"{path.name} is {im.size}, JSON-LD claims {logo['width']}x{logo['height']}"
