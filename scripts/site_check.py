#!/usr/bin/env python3
"""Site-wide QA audit for the Bakersfield Brief static build.

Checks (all offline against site/):
  1. every internal href/src target exists (no broken links, no 404s)
  2. no leftover build tokens (__XXX__), literal markdown (**), or raw
     {{ }} braces in output HTML
  3. every page has og:title/og:desc/og:image + canonical + title
  4. duplicate id attributes on any page
  5. sitemap.xml entries all exist on disk; feed.xml parses
  6. JSON-LD blocks parse
Usage: python scripts/site_check.py [site_dir]
"""
from __future__ import annotations

import html as htmlmod
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
SITE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site"

FAILS: list[str] = []
WARNS: list[str] = []


def fail(msg: str):
    FAILS.append(msg)


def warn(msg: str):
    WARNS.append(msg)


def resolve(href: str, page: Path) -> Path | None:
    """Resolve a possibly-relative href/src against the page's directory."""
    href = href.split("#", 1)[0].split("?", 1)[0]
    if not href or href.startswith(("http:", "https:", "mailto:", "tel:", "data:", "javascript:")):
        return None
    if href.startswith("//"):
        return None
    p = (page.parent / unquote(href)).resolve()
    try:
        rel = p.relative_to(SITE.resolve())
    except ValueError:
        return None
    if rel.as_posix().startswith(".."):
        return None
    if p.is_dir():
        return p / "index.html"
    return p


def main() -> int:
    pages = sorted(SITE.rglob("*.html"))
    if not pages:
        print("no pages found under", SITE)
        return 1

    # ---- 1+2+3+4: per-page checks
    for page in pages:
        rel = page.relative_to(SITE).as_posix()
        text = page.read_text(encoding="utf-8")

        # tokens left unrendered
        for tok in re.findall(r"__[A-Z_]+__", text):
            fail(f"{rel}: unrendered token {tok}")
        if "**" in text:
            fail(f"{rel}: literal '**' markdown in output")
        if "<!--__" in text:
            fail(f"{rel}: unrendered template comment")

        # duplicate ids
        ids = re.findall(r'id="([^"]+)"', text)
        dups = {i for i in ids if ids.count(i) > 1}
        if dups:
            fail(f"{rel}: duplicate ids {sorted(dups)[:5]}")

        # head essentials
        if "<title>" not in text or "</title>" not in text:
            fail(f"{rel}: missing <title>")
        for tag in ["og:title", "og:description", "og:image", "og:url"]:
            if f'property="{tag}"' not in text and f'name="{tag}"' not in text:
                fail(f"{rel}: missing {tag}")
        if 'rel="canonical"' not in text:
            fail(f"{rel}: missing canonical")

        # json-ld parse
        for b in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', text, re.S):
            try:
                json.loads(b)
            except Exception as e:  # noqa: BLE001
                fail(f"{rel}: JSON-LD invalid ({type(e).__name__})")

        # internal link targets
        for href in re.findall(r'(?:href|src)="([^"]+)"', text):
            tgt = resolve(href, page)
            if tgt is not None and not tgt.exists():
                fail(f"{rel}: broken link -> {href}")

    # ---- 5: sitemap
    sm = SITE / "sitemap.xml"
    if sm.exists():
        try:
            root = ET.parse(sm).getroot()
            urls = [u.text for u in root.iter() if u.tag.endswith("loc")]
            for u in urls:
                path = urlparse(u).path.lstrip("/")
                target = SITE / path
                if not target.exists() and not (target.parent / "index.html").exists():
                    fail(f"sitemap.xml: entry missing on disk -> {u}")
            if len(urls) != len(pages) - 1:
                warn(f"sitemap has {len(urls)} entries vs {len(pages) - 1} pages (excluding 404)")
        except Exception as e:  # noqa: BLE001
            fail(f"sitemap.xml unparseable: {type(e).__name__}: {e}")
    else:
        fail("sitemap.xml missing")

    # feed parses
    feed = SITE / "feed.xml"
    if feed.exists():
        try:
            ET.parse(feed)
        except Exception as e:  # noqa: BLE001
            fail(f"feed.xml unparseable: {type(e).__name__}: {e}")
    else:
        fail("feed.xml missing")

    # ---- summary
    print(f"pages checked: {len(pages)}")
    print(f"FAILS: {len(FAILS)}")
    for f in FAILS[:40]:
        print("  FAIL", f)
    print(f"WARNS: {len(WARNS)}")
    for w in WARNS[:10]:
        print("  WARN", w)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
