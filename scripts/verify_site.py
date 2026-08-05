#!/usr/bin/env python3
"""Site verification — run after every build (also invoked by CI before deploy).

Checks: every page has one non-empty title, meta description, canonical,
viewport; internal hrefs/srcs resolve on disk; every JSON-LD block parses;
sitemap URLs map to real files; the tracker placeholder was replaced;
no leftover template tokens. One process = one exit code.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

errors = []
warnings = []


def err(msg):
    errors.append(msg)
    print("  FAIL:", msg)


def warn(msg):
    warnings.append(msg)
    print("  warn:", msg)


def main():
    pages = sorted(SITE.rglob("*.html"))
    print(f"checking {len(pages)} html pages")

    for p in pages:
        rel = p.relative_to(SITE).as_posix()
        html = p.read_text(encoding="utf-8")
        # 1. template tokens all replaced?
        leftover = re.findall(r"<!--__[A-Z_]+__-->", html)
        if leftover:
            err(f"{rel}: leftover tokens {set(leftover)}")
        # 2. title
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        if not m or not m.group(1).strip():
            err(f"{rel}: missing/empty title")
        elif html.count("<title>") != 1:
            err(f"{rel}: {html.count('<title>')} title tags")
        # 3. meta description
        m = re.search(r'<meta name="description" content="([^"]*)"', html)
        if not m or not m.group(1).strip():
            err(f"{rel}: missing/empty meta description")
        # 4. canonical
        if 'rel="canonical"' not in html:
            err(f"{rel}: missing canonical")
        # 5. viewport
        if 'name="viewport"' not in html:
            err(f"{rel}: missing viewport")
        # 6. JSON-LD parses
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            try:
                json.loads(block)
            except Exception as e:
                err(f"{rel}: JSON-LD parse error: {e}")
        # 7. internal links resolve on disk (directory links → index.html)
        for href in re.findall(r'href="([^"#]+)"', html):
            if href.startswith(("http", "mailto:", "tel:", "data:")) or href.startswith("//"):
                continue
            target = (p.parent / href).resolve()
            if href.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                err(f"{rel}: broken link {href!r}")
        for src in re.findall(r'src="([^"]+)"', html):
            if src.startswith(("http", "data:")):
                continue
            target = (p.parent / src).resolve()
            if not target.exists():
                err(f"{rel}: broken src {src!r}")
        # 8. placeholder replaced on tracker pages
        if "tracker-data" in html and "/*__DATA__*/null" in html:
            err(f"{rel}: tracker JSON placeholder NOT replaced")

    # sitemap ↔ files
    sm = SITE / "sitemap.xml"
    if sm.exists():
        text = sm.read_text(encoding="utf-8")
        locs = re.findall(r"<loc>(.*?)</loc>", text)
        for loc in locs:
            rel = loc.replace("https://bakersfieldbrief.com/", "")
            if not (SITE / rel).exists():
                err(f"sitemap: {rel} has no file")
        print(f"sitemap: {len(locs)} urls")
    else:
        err("sitemap.xml missing")

    # robots
    if not (SITE / "robots.txt").exists():
        err("robots.txt missing")
    if not (SITE / "CNAME").exists():
        warn("CNAME missing in site/ (needed for the custom domain artifact)")

    print(f"\n{len(pages)} pages · {len(errors)} errors · {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
