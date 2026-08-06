#!/usr/bin/env python3
"""Atom feed — /feed.xml — daily briefs + trackers (syndication, SEO)."""
from __future__ import annotations

import json
import xml.sax.saxutils as sx

from .. import common
from . import page as page_mod

BASE = "https://bakersfieldbrief.com"


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()

    entries = []
    try:
        arch = json.loads((common.DATA / "briefs_archive.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        arch = []
    for e in reversed(arch[-30:]):
        d = str(e.get("date", ""))
        title = str(e.get("headline", "Daily brief"))
        entries.append(f"""  <entry>
    <title>{sx.escape(title)}</title>
    <link href="{BASE}/briefs/{d}/"/>
    <id>{BASE}/briefs/{d}/</id>
    <updated>{d}T12:00:00-07:00</updated>
    <summary>Bakersfield Daily Brief for {d} — the day's news, conditions, and what's coming up in Kern County.</summary>
  </entry>""")

    feed = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Bakersfield Daily Brief</title>
  <subtitle>The Kern County news you'd otherwise miss — gathered from public records.</subtitle>
  <link href="{BASE}/feed.xml" rel="self"/>
  <link href="{BASE}/" rel="alternate"/>
  <id>{BASE}/feed.xml</id>
  <updated>{built_iso}T12:00:00-07:00</updated>
  <author><name>Bakersfield Daily Brief</name></author>
{''.join(entries)}
</feed>"""
    common.write(common.SITE / "feed.xml", feed)
    built.append("feed.xml")

    ctx.build_report["feed"] = {"entries": len(arch[-30:])}
    return built
