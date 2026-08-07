#!/usr/bin/env python3
"""Events page — /events/ — what's happening around town.

Venue listings come from the whitelist scrape (data/venues.json; refreshed
every build, curated weekly), plus public meetings from eSCRIBE and the
County Board. Events are grouped This week / Next / Later / Date TBD; past
events are dropped. Every entry links to the venue's own listing.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import common
from . import images
from . import page as page_mod


# ---------------------------------------------------------------- date parse
def _when_date(e, today) -> dt.date | None:
    """Best-effort date extraction across venue 'when' formats."""
    w = str(e.get("when") or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", w)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s*(\d{4}))?", w)
    if m:
        try:
            mon = dt.datetime.strptime(m.group(1), "%b").month
        except ValueError:
            try:
                mon = dt.datetime.strptime(m.group(1), "%B").month
            except ValueError:
                return None
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return dt.date(year, mon, int(m.group(2)))
        except ValueError:
            return None
    return None


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    today = common.today_pacific()
    rel = "../"

    events = sources.get("venues", {}).get("events", []) or []
    escribe = sources.get("escribe", {})
    board = sources.get("board", {})

    dated = [(e, _when_date(e, today)) for e in events if e.get("name")]
    future = [(e, d) for e, d in dated if d is None or d >= today]

    def sort_key(pair):
        e, d = pair
        return (d is None, d or dt.date.max, str(e.get("venue", "")).lower())

    future.sort(key=sort_key)
    groups = {
        "This week": [p for p in future if p[1] and p[1] <= today + dt.timedelta(days=6)],
        "Next week": [p for p in future if p[1] and today + dt.timedelta(days=7) <= p[1] <= today + dt.timedelta(days=13)],
        "Later": [p for p in future if p[1] and p[1] > today + dt.timedelta(days=13)],
        "Date TBD": [p for p in future if p[1] is None],
    }
    groups = {k: v for k, v in groups.items() if v}

    def ev_row(e, d) -> str:
        when = (d.strftime("%a, %b") + f" {d.day}") if d else (html.escape(str(e.get("when") or "Date TBD")))
        when = html.escape(when)
        url = html.escape(e.get("url") or "#")
        venue = html.escape(e.get("venue") or "")
        name = html.escape(e.get("name") or "Untitled event")
        return f"""
      <li class="ev-row">
        <span class="ev-date">{when}</span>
        <span class="ev-body"><a href="{url}" target="_blank" rel="noopener"><strong>{name}</strong></a>
        <span class="ev-venue">{venue}</span></span>
      </li>"""

    secs = ""
    for gname, items in groups.items():
        rows = "".join(ev_row(e, d) for e, d in items)
        secs += f"""
      <section class="block">
        <div class="sign-head"><span class="tab">{len(items)}</span><h2>{gname}</h2></div>
        <ul class="ev-list">{rows}</ul>
      </section>"""

    # ---- public meetings (next 14 days)
    up = escribe.get("upcoming", []) or []
    meet_rows = ""
    for m in sorted(up, key=lambda x: str(x.get("start_iso", ""))):
        if (m.get("start_iso") or "")[:10] < built_iso:
            continue
        when = (m.get("start_iso") or "")[:16].replace("T", " ")
        meet_rows += f"""
      <li class="ev-row">
        <span class="ev-date">{html.escape(when)}</span>
        <span class="ev-body"><a href="{html.escape(m.get('url', rel + 'city-hall/'))}" rel="noopener"><strong>{html.escape(m.get('name', 'Public meeting'))}</strong></a>
        <span class="ev-venue">Public meeting · agenda-linked</span></span>
      </li>"""
    if meet_rows:
        secs += f"""
      <section class="block">
        <div class="sign-head"><span class="tab">Gov</span><h2>Public meetings</h2></div>
        <ul class="ev-list">{meet_rows}</ul>
      </section>"""

    if not secs:
        secs = '<p class="note">No dated events or meetings found yet — the venue scrape refreshes every build.</p>'

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Around town</p>
      <h1>Events in Bakersfield</h1>
      <p class="lede">What's on at the Fox, Mechanics Bank Arena, The Well and more — plus
      public meetings on the city calendar. Listings come from each venue's own site
      (whitelist in data/venues.json) and refresh every build.</p></div>
    </div>
    {images.figure("fair", rel)}
    {secs}
    <p class="note">Dates are as published by each venue; always confirm on the venue's listing
    before planning around an event. Meeting items come from official agendas and can change.</p>"""

    page = page_mod.render(
        title="Events in Bakersfield — what's on around town | Bakersfield Daily Brief",
        desc="Live events at Bakersfield venues (Fox Theater, Mechanics Bank Arena, The Well) plus public meetings — refreshed every build.",
        canonical="/events/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    common.write(common.SITE / "events" / "index.html", page)
    built.append("events/index.html")

    ctx.build_report["events"] = {"groups": {k: len(v) for k, v in groups.items()},
                                  "meetings": len(up)}
    return built
