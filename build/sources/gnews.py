#!/usr/bin/env python3
"""Google News RSS — per-place hyperlocal headlines (free, no key).

One query per place (see GN_QUERIES); Google News aggregates local outlets
(Tehachapi News, KGET, 23ABC, Bakersfield.com, bakersfieldnow, etc.).
Results are filtered against known junk (AQI widgets, national syndication)
and deduped by normalized title. `when:3d` keeps results fresh for the
daily cron. Any query failure returns [] for that place — never fatal.
"""
from __future__ import annotations

import html as htmlmod
import re
import urllib.parse

import feedparser

from .. import common

BASE = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q={q}"

# slug -> query (keep in sync with PLACES in build/builders/places.py)
GN_QUERIES = {
    "tehachapi": "tehachapi when:3d",
    "bakersfield-nw": "northwest bakersfield OR oildale when:3d",
    "bakersfield-sw": "southwest bakersfield when:3d",
    "bakersfield-east": "east bakersfield when:3d",
    "bakersfield-central": "downtown bakersfield when:3d",
}

# junk domains / patterns to drop (widgets, national PR syndication)
_BLOCK = (
    "iqair", "maxpreps", "weather.com", "accuweather", "benzinga", "zacks",
    "insider monkey", "streetinsider", "prnewswire", "globenewswire", "businesswire",
)


def run(ctx):
    out = {"ok": True, "results": {}, "asof": common.iso_today()}
    for slug, query in GN_QUERIES.items():
        out["results"][slug] = _fetch(query)
    return out


def _fetch(query: str, limit: int = 12) -> list[dict]:
    url = BASE.format(q=urllib.parse.quote(query))
    try:
        r = common.fetch(url, timeout=25)
        f = feedparser.parse(r.content)
    except Exception:  # noqa: BLE001
        return []

    items = []
    seen = set()
    for e in f.entries:
        title = htmlmod.unescape(e.get("title") or "").strip()
        src = _source_from_title(title)
        title = re.sub(r"\s+-\s+[^-]+$", "", title).strip()  # drop trailing "- Outlet"
        if not title or len(title) < 15:
            continue
        low = title.lower()
        if any(b in low for b in _BLOCK):
            continue
        key = re.sub(r"[^a-z0-9]+", "", low)[:70]
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title,
            "source": src,
            "url": e.get("link", ""),
            "published": (e.get("published") or "")[:22],
        })
        if len(items) >= limit:
            break
    return items


def _source_from_title(title: str) -> str:
    m = re.search(r"- ([A-Za-z0-9 .&\']+)$", title)
    if m:
        return m.group(1).strip()
    return "Google News"
