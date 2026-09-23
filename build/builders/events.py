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
    # Condors games carry the date in the name ("9/25 vs SJ") and no "when": they showed "Date TBD"
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d|/)", str(e.get("name") or ""))
    if m:
        try:
            d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
            return d.replace(year=today.year + 1) if (d - today).days < -180 else d
        except ValueError:
            return None
    return None


# AHL Pacific Division opponents, by the codes the Condors schedule feed uses
_AHL = {"ABB": "Abbotsford Canucks", "CGY": "Calgary Wranglers", "COL": "Colorado Eagles",
        "CV": "Coachella Valley Firebirds", "HSK": "Henderson Silver Knights",
        "ONT": "Ontario Reign", "SD": "San Diego Gulls", "SJ": "San Jose Barracuda",
        "TUC": "Tucson Roadrunners", "TEX": "Texas Stars"}


def _display_name(e: dict) -> str:
    """Condors listings read "9/25 vs SJ"; say "Condors vs. San Jose Barracuda" instead."""
    name = str(e.get("name") or "")
    if e.get("venue_slug") != "condors":
        return name
    m = re.search(r"(vs|at|@)\s+([A-Z]{2,4})\b", name)
    if not m:
        return f"Bakersfield Condors: {name}"
    team = _AHL.get(m.group(2), m.group(2))
    return f"Bakersfield Condors vs. {team}" if m.group(1) == "vs" else f"Bakersfield Condors at {team} (away)"


def _event_jsonld(future: list, today: dt.date, limit: int = 60) -> list[dict]:
    """schema.org Event for each dated upcoming listing in Bakersfield (event rich results).

    Location is the venue name with the city: no street address is stored for these venues and
    none is guessed. Away games ("9/26 at SJ") happen elsewhere and are left out."""
    out = []
    for e, d in future:
        if d is None or d < today:
            continue
        name = str(e.get("name") or "").strip()
        if not name or re.search(r"(\bat|@) [A-Z]{2,4}\b", name):
            continue
        venue = str(e.get("venue") or "Bakersfield venue")
        ev = {
            "@context": "https://schema.org", "@type": "Event",
            "name": _display_name(e),
            "startDate": d.isoformat(),
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {"@type": "Place", "name": venue,
                         "address": {"@type": "PostalAddress", "addressLocality": "Bakersfield",
                                     "addressRegion": "CA", "addressCountry": "US"}},
        }
        if e.get("url"):
            ev["url"] = e["url"]
        out.append(ev)
        if len(out) >= limit:
            break
    return out


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
    # A run of the same show (Bakersfield Community Theatre lists every performance) becomes one
    # entry at its next date, with the count of later dates.
    seen, collapsed = {}, []
    for e, d in future:
        key = (e.get("venue_slug"), str(e.get("name", "")).strip().lower())
        if key in seen and d is not None:
            seen[key]["_more"] = seen[key].get("_more", 0) + 1
            continue
        e = dict(e)
        seen[key] = e
        collapsed.append((e, d))
    future = collapsed
    groups = {
        # rolling windows from today, labelled as such: "Next week" put Oct 5 under "next week" on Sep 22
        "In the next 7 days": [p for p in future if p[1] and p[1] <= today + dt.timedelta(days=6)],
        "In 1 to 2 weeks": [p for p in future if p[1] and today + dt.timedelta(days=7) <= p[1] <= today + dt.timedelta(days=13)],
        "Later": [p for p in future if p[1] and p[1] > today + dt.timedelta(days=13)],
        "Date not posted yet": [p for p in future if p[1] is None],
    }
    groups = {k: v for k, v in groups.items() if v}

    def ev_row(e, d) -> str:
        when = (d.strftime("%a, %b") + f" {d.day}") if d else str(e.get("when") or "Date not posted")
        when = html.escape(when)
        url = html.escape(e.get("url") or "#")
        venue = html.escape(e.get("venue") or "")
        name = html.escape(_display_name(e) or "Untitled event")
        if e.get("_more"):
            name += f' <span class="ev-more">+{e["_more"]} more date{"s" if e["_more"] != 1 else ""}</span>'
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
        <div class="sign-head"><span class="tab">{len(items)} event{"s" if len(items) != 1 else ""}</span><h2>{gname}</h2></div>
        <ul class="ev-list">{rows}</ul>
      </section>"""

    # ---- public meetings (next 14 days)
    up = escribe.get("upcoming", []) or []
    meet_rows = ""
    for m in sorted(up, key=lambda x: str(x.get("start_iso", ""))):
        if (m.get("start_iso") or "")[:10] < built_iso:
            continue
        when = common.fmt_when(m.get("start_iso") or "")
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
        secs = '<p class="note">No dated events or meetings are posted right now. Listings update several times a day.</p>'

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Around town</p>
      <h1>Events in Bakersfield</h1>
      <p class="lede">Concerts, shows, plays, the symphony, Condors hockey, CSUB and Bakersfield
      College home games, and more, plus public meetings on the city calendar. Listings come from each venue&rsquo;s own website and
      update several times a day. Dates are as each venue posted them, so confirm before you go.</p></div>
    </div>
    {images.figure("fair", rel)}
    <div class="card" style="margin:14px 0"><span class="tag amber">Feature</span>
      <h3><a href="{rel}fair/">Kern County Fair 2026 — dates, concerts &amp; tickets</a></h3>
      <p>The county&rsquo;s biggest event runs <strong>Sept 23 &ndash; Oct 4</strong> at the
      Kern County Fairgrounds: twelve nights of concerts at the Budweiser Pavilion, PRCA rodeo,
      monster trucks, and the full carnival.</p></div>
    {secs}
    <p class="note">Dates are as published by each venue; always confirm on the venue's listing
    before planning around an event. Meeting items come from official agendas and can change.</p>"""

    page = page_mod.render(
        title="Events in Bakersfield — what's on around town | Bakersfield Daily Brief",
        desc="Things to do in Bakersfield: concerts at the Fox, Temblor Brewing shows, Bakersfield Community Theatre plays, the symphony, Condors, CSUB and Bakersfield College home games, and public meetings.",
        canonical="/events/", content=body, current="events", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()] + _event_jsonld(future, today))
    common.write(common.SITE / "events" / "index.html", page)
    built.append("events/index.html")

    ctx.build_report["events"] = {"groups": {k: len(v) for k, v in groups.items()},
                                  "meetings": len(up)}
    return built
