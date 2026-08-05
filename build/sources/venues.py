#!/usr/bin/env python3
"""Venue event scraping for the Weekend Guide (weekly, Thursday build).

Parses the whitelist in data/venues.json. Each parser is isolated — a dead
venue never breaks the others. Runs only when the build is invoked with
--guide (or Thursday); otherwise returns {"ok": True, "skipped": True} so
the daily run makes zero venue requests.

Verified shapes (Aug 2026):
  fox:    https://thebakersfieldfox.com/events/ — schema.org ld+json Events
  arena:  https://www.mechanicsbankarena.com/events — /event/<slug>/<id>/ links
  well:   thewellcomedyclub.com — SeatEngine ticketing calendar
  condors: /schedule/feed/ — WordPress events feed (quiet out of season)
  visit:  visitbakersfield.com/events/ — loads; structured data varies
"""
from __future__ import annotations

import json
import re

from .. import common

HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}


def run(ctx):
    if not getattr(ctx, "guide", False):
        return {"ok": True, "skipped": True}
    out = {"ok": True, "events": []}
    try:
        whitelist = json.loads((common.DATA / "venues.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "venues.json unreadable"}
    for v in whitelist.get("venues", []):
        try:
            parser = _PARSERS.get(v.get("parse"))
            if parser:
                evs = parser(v)
                for e in evs:
                    e["venue"] = v["name"]
                    e["venue_slug"] = v["slug"]
                out["events"].extend(evs)
        except Exception as e:  # noqa: BLE001
            common.log(f"venue {v.get('slug')} failed: {type(e).__name__}: {e}")
    return out


# ---------------------------------------------------------------- parsers
def _fox(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=25)
    blocks = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', r.text, re.S)
    events = []
    for b in blocks:
        try:
            d = json.loads(b)
        except Exception:  # noqa: BLE001
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if it.get("@type") in ("Event", ["Event"]) or "Event" in (it.get("@type") or []):
                events.append({
                    "name": it.get("name", ""),
                    "when": (it.get("startDate") or "")[:16].replace("T", " "),
                    "url": it.get("url") or v["url"],
                })
    return events


def _arena(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=25)
    slugs = re.findall(r'href="([^"]*/event/[^"]+/[0-9]+/)"', r.text)
    origin = "https://www.mechanicsbankarena.com"
    seen, events = set(), []
    for s in slugs:
        if s in seen:
            continue
        seen.add(s)
        name = s.rstrip("/").split("/")[-2].replace("-", " ").title()
        url = s if s.startswith("http") else origin + s
        events.append({"name": name, "when": "", "url": url})
        if len(events) >= 12:
            break
    # dates come from detail pages — fetch the first 5
    for e in events[:5]:
        try:
            dr = common.fetch(e["url"], headers=HEADERS, timeout=20)
            m = re.search(r'"startDate"\s*:\s*"([^"]+)"', dr.text)
            if m:
                e["when"] = m.group(1)[:16].replace("T", " ")
            else:
                m2 = re.search(r"(\w+ \d{1,2}, \d{4})", dr.text)
                if m2:
                    e["when"] = m2.group(1)
        except Exception:  # noqa: BLE001
            pass
    return events


def _well(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=25)
    # SeatEngine calendar link from the ticket buttons
    m = re.search(r'href="([^"]*seatengine[^"]*)"', r.text, re.I)
    cal_url = m.group(1) if m else ""
    events = []
    if not cal_url:
        # fallback: any shows with dates on the homepage
        for name, when in re.findall(r'([A-Z][^<>]{4,40})\s*[-–]\s*(\w+ \d{1,2})', r.text)[:6]:
            events.append({"name": name.strip(), "when": when, "url": v["url"]})
        return events
    try:
        cr = common.fetch(cal_url, headers=HEADERS, timeout=25)
        for name, when in re.findall(r'([A-Z][^<>"]{4,50})\s*(\w{3,9} \d{1,2}(?:st|nd|rd|th)?,? \d{4})', cr.text)[:10]:
            events.append({"name": name.strip(), "when": when, "url": cal_url})
    except Exception:  # noqa: BLE001
        pass
    return events


def _condors(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=25)
    events = []
    for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
        seg = m.group(1)
        title = re.search(r"<title>(.*?)</title>", seg, re.S)
        if not title:
            continue
        # WordPress event feeds carry the date in the title ("Oct 4, 2026 — vs ...")
        t = re.sub(r"<[^>]+>", "", title.group(1)).strip()
        when = ""
        dm = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", t)
        if dm:
            when = dm.group(1)
        events.append({"name": t, "when": when, "url": v["url"]})
    return events


def _visit(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=25)
    events = []
    blocks = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', r.text, re.S)
    for b in blocks:
        try:
            d = json.loads(b)
        except Exception:  # noqa: BLE001
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if "Event" in (it.get("@type") or []) or it.get("@type") == "Event":
                events.append({
                    "name": it.get("name", ""),
                    "when": (it.get("startDate") or "")[:16].replace("T", " "),
                    "url": it.get("url") or v["url"],
                })
    return events


_PARSERS = {"ldjson": _fox, "arena_links": _arena, "well_seatengine": _well,
            "condors_feed": _condors, "visit": _visit}
