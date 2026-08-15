#!/usr/bin/env python3
"""Local news RSS: KGET (kget.com/feed/) + 23ABC (turnto23.com/news/local-news.rss).

Both confirmed working Aug 2026. bakersfield.com rate-limits aggressively —
poll gently or skip; we skip it (not a source) and note the possibility in
the README. Headlines + links ONLY — never republished article text.
"""
from __future__ import annotations

import datetime as dt

import re
import feedparser

from .. import common

FEEDS = [
    ("KGET 17", "https://www.kget.com/feed/"),
    ("23ABC", "https://www.turnto23.com/news/local-news.rss"),
    # Bakersfield Now (KBAK 29, Sinclair) has no public RSS — its site is
    # JS-rendered — so we pull it through Google News' site-filtered feed.
    ("Bakersfield Now",
     "https://news.google.com/rss/search?q=site:bakersfieldnow.com&hl=en-US&gl=US&ceid=US:en"),
]
MAX_PER_FEED = 25


def run(ctx):
    out, errors = [], []
    for name, url in FEEDS:
        try:
            r = common.fetch(url, timeout=30)
            f = feedparser.parse(r.content)
            for e in f.entries[:MAX_PER_FEED]:
                title = (e.get("title") or "").strip()
                # Google News titles carry an outlet suffix ("... - KBAK 29")
                title = re.sub(
                    r"\s+-\s+(?:KBAK 29|KBAK|Bakersfield Now|29 News|Bakersfield Now News)$",
                    "", title, flags=re.I)
                out.append({
                    "title": title,
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

    # newest first — the top story must be today's news, not whichever feed
    # listed first. Undated items sort last (epoch 0) but stay in the list.
    for h in dedup:
        h["_epoch"] = _epoch(h.get("published", ""))
    dedup.sort(key=lambda h: h["_epoch"], reverse=True)
    for h in dedup:
        h.pop("_epoch", None)

    return {"ok": True, "headlines": dedup, "errors": errors, "asof": common.iso_today()}


def _epoch(published: str) -> float:
    """RFC-2822 publish string → epoch seconds; 0 if unparsable."""
    if not published:
        return 0.0
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(published).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _pub(e) -> str:
    for key in ("published", "updated"):
        v = e.get(key)
        if v:
            return v
    return ""
