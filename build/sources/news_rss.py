#!/usr/bin/env python3
"""Local news RSS: KGET (kget.com/feed/) + 23ABC (turnto23.com/news/local-news.rss).

Both confirmed working Aug 2026. bakersfield.com rate-limits aggressively —
poll gently or skip; we skip it (not a source) and note the possibility in
the README. Headlines + links ONLY — never republished article text.
"""
from __future__ import annotations

import datetime as dt

import feedparser

from .. import common

FEEDS = [
    ("KGET 17", "https://www.kget.com/feed/"),
    ("23ABC", "https://www.turnto23.com/news/local-news.rss"),
]
MAX_PER_FEED = 25


def run(ctx):
    out, errors = [], []
    for name, url in FEEDS:
        try:
            r = common.fetch(url, timeout=30)
            f = feedparser.parse(r.content)
            for e in f.entries[:MAX_PER_FEED]:
                out.append({
                    "title": (e.get("title") or "").strip(),
                    "url": e.get("link", ""),
                    "source": name,
                    "published": _pub(e),
                })
        except Exception as ex:  # noqa: BLE001
            errors.append(f"{name}: {type(ex).__name__}: {ex}")

    # dedup by title across feeds
    seen, dedup = set(), []
    for h in out:
        k = h["title"].lower()[:60]
        if k not in seen and h["title"]:
            seen.add(k)
            dedup.append(h)

    return {"ok": True, "headlines": dedup, "errors": errors, "asof": common.iso_today()}


def _pub(e) -> str:
    for key in ("published", "updated"):
        v = e.get(key)
        if v:
            return v
    return ""
