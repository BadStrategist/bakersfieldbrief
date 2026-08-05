#!/usr/bin/env python3
"""Places — hyperlocal sections for parts of Bakersfield + Tehachapi.

Each place is a registry entry (add one = 5 lines). Every place page is the
same template, built daily from data we already fetch, filtered by keyword
(headlines) and geolocation (CHP incidents, ALPR cameras):

  /places/                     hub of place cards
  /places/<slug>/              local conditions · incidents · headlines ·
                               ALPR (compact) · openings & closings · watch

Honest design: geo-filters are best-effort on public data. Headline matching
is keyword-based (coverage varies by day); zones share the city forecast;
Tehachapi gets its own NWS gridpoint forecast. Pages say so plainly.
"""
from __future__ import annotations

import datetime as dt
import html
import math

from .. import common
from ..sources.airnow import css_class as _aqi_css
from . import page as page_mod

# ------------------------------------------------------------------ registry
PLACES = {
    "tehachapi": {
        "name": "Tehachapi",
        "blurb": "The mountain town on the Mojave edge of Kern County — its own climate, its own school district, and its own incident footprint on Highway 58.",
        "aliases": ("tehachapi",),
        "center": (35.1322, -118.4490),
        "radius_km": 30,
        "nws_point": (35.1322, -118.4490),
        "city_filter": "TEHACHAPI",
        "citywide": False,
        "school_note": "Tehachapi Unified School District agendas are on the blocked list — a self-hosted runner unlocks them.",
    },
    "bakersfield-nw": {
        "name": "Northwest Bakersfield",
        "blurb": "North of downtown toward Oildale — Highway 99 corridor, the Kern River Parkway, and the airport edge.",
        "aliases": ("northwest bakersfield", "nw bakersfield", "north bakersfield", "oildale"),
        "center": (35.43, -119.05),
        "radius_km": 14,
        "nws_point": None,
        "city_filter": "BAKERSFIELD",
        "citywide": True,
        "school_note": "",
    },
    "bakersfield-sw": {
        "name": "Southwest Bakersfield",
        "blurb": "The fastest-growing part of town — Stockdale Highway, Seven Oaks, and the newest retail corridors.",
        "aliases": ("southwest bakersfield", "sw bakersfield", "south bakersfield", "west bakersfield", "seven oaks", "stockdale"),
        "center": (35.28, -119.10),
        "radius_km": 12,
        "nws_point": None,
        "city_filter": "BAKERSFIELD",
        "citywide": True,
        "school_note": "",
    },
    "bakersfield-east": {
        "name": "East Bakersfield",
        "blurb": "East of the 99 — old Bakersfield neighborhoods, Panorama, and the hills toward the Kern River Canyon.",
        "aliases": ("east bakersfield", "eastside", "east side", "panorama"),
        "center": (35.38, -118.93),
        "radius_km": 11,
        "nws_point": None,
        "city_filter": "BAKERSFIELD",
        "citywide": True,
        "school_note": "",
    },
    "bakersfield-central": {
        "name": "Central Bakersfield",
        "blurb": "Downtown and midtown — City Hall, the courthouses, Truxtun Avenue, and the central neighborhoods.",
        "aliases": ("downtown bakersfield", "central bakersfield", "midtown bakersfield"),
        "center": (35.3733, -119.0187),
        "radius_km": 8,
        "nws_point": None,
        "city_filter": "BAKERSFIELD",
        "citywide": True,
        "school_note": "",
    },
}

_FORECAST_CACHE: dict[tuple, dict] = {}


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    news = sources.get("news_rss", {})
    gnews = sources.get("gnews", {})
    chp = sources.get("chp", {})
    alpr = sources.get("alpr", {})
    escribe = sources.get("escribe", {})
    weather = sources.get("weather", {})
    airnow = sources.get("airnow", {})

    for slug, meta in PLACES.items():
        out = common.SITE / "places" / slug / "index.html"
        common.write(out, _place_page(ctx, slug, meta, built_iso, sources,
                                      news, gnews, chp, alpr, escribe, weather, airnow))
        built.append(f"places/{slug}/index.html")

    hub = _hub(ctx, built_iso, weather)
    common.write(common.SITE / "places" / "index.html", hub)
    built.append("places/index.html")

    ctx.build_report["places"] = {
        "places": list(PLACES.keys()),
        "tehachapi_forecast": _forecast_for(PLACES["tehachapi"]["nws_point"]).get("high") is not None,
        "gnews_per_place": {slug: len(gnews.get("results", {}).get(slug, [])) for slug in PLACES},
    }
    return built


# ---------------------------------------------------------------- page
def _place_page(ctx, slug: str, meta: dict, built_iso: str, sources: dict,
                news, gnews, chp, alpr, escribe, weather, airnow) -> str:
    rel = "../../"
    name = meta["name"]

    # ---- conditions (local forecast + county alerts)
    fc = _forecast_for(meta["nws_point"]) if meta["nws_point"] else (weather or {}).get("forecast", {})
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    if hi is not None and lo is not None:
        weather_v = f"{hi}&deg; / {lo}&deg;"
    elif cur is not None:
        weather_v = f"{cur}&deg;"
    else:
        weather_v = "n/a"
    alerts = (weather or {}).get("alerts", [])
    alert_v = alerts[0]["event"] + " active" if alerts else "No active alerts"

    if airnow.get("ok") and airnow.get("aqi") is not None:
        aqi_v = (f'<span class="{_aqi_css(airnow.get("category_num"))}">{airnow["aqi"]} &middot; '
                 f'{html.escape(airnow.get("category") or "")}</span> <span class="unit">city-wide</span>')
    elif airnow.get("needs_key"):
        aqi_v = 'Waiting for EPA AirNow key'
    else:
        aqi_v = 'Unavailable this build'

    conditions = f"""
    <section aria-labelledby="h-cond">
      <p class="sec-head" id="h-cond">Local conditions <span class="unit">{"Tehachapi mountain forecast" if meta["nws_point"] else "Bakersfield metro forecast"}</span></p>
      <div class="cond-strip">
        <div class="cond-chip"><div class="l">Today</div><div class="v">{weather_v}</div></div>
        <div class="cond-chip"><div class="l">Weather alerts</div><div class="v {'amber' if alerts else ''}">{html.escape(alert_v)}</div></div>
        <div class="cond-chip"><div class="l">Air quality (AQI)</div><div class="v">{aqi_v}</div></div>
      </div>
      <p class="note" style="margin-top:10px">{"Forecast from the NWS Hanford gridpoint for Tehachapi." if meta["nws_point"] else "The four Bakersfield zone pages share the metro forecast — the city sits in one climate zone."}
      Alerts are county-wide (NWS); AQI is the Bakersfield monitoring area (EPA AirNow).</p>
    </section>"""

    # ---- CHP incidents near this place (rolling 7-day archive)
    chp_items = _nearby_chp(chp, meta)
    if chp_items:
        lis = "".join(f"""
        <li><strong>{html.escape(i.get('type', 'Incident')[:38])}</strong>
        <span class="when">{html.escape(i.get('location', ''))} &middot; {html.escape(i.get('time', ''))}</span></li>"""
                      for i in chp_items[:7])
        chp_html = f'<ul class="hl">{lis}</ul>'
    else:
        chp_html = '<p class="note">No CHP incidents logged near this area in the last 7 days. The archive grows with each daily build.</p>'

    # ---- headlines: Google News for this place + metro keyword matches
    hl_items = _place_headlines(gnews, news, slug, meta)
    if hl_items:
        lis = "".join(f"""
        <li><span class="src">{html.escape(h.get('source', 'news'))}</span><br>
        <a href="{html.escape(h.get('url', '#'))}" rel="noopener">{html.escape(h['title'])}</a></li>"""
                      for h in hl_items[:10])
        headlines_html = f'<ul class="hl">{lis}</ul>'
    else:
        headlines_html = ('<p class="note">No headlines for this area in the last 3 days. '
                          'Hyperlocal coverage varies &mdash; check back after the next daily build.</p>')

    # ---- ALPR in this area (compact, less prominent)
    cams = _cameras_near(alpr, meta)
    if cams:
        dated = sorted([c for c in cams if c.get("mapped")], key=lambda c: c["mapped"], reverse=True)
        newest = "".join(f"""<li><span class="n-date">{html.escape(str(c.get('mapped', '')))}</span>
        <span class="n-meta">{html.escape(c.get('manufacturer', ''))} &middot; <a href="https://www.openstreetmap.org/node/{c['id']}" target="_blank" rel="noopener">node {c['id']}</a></span></li>"""
                         for c in dated[:3])
        alpr_html = f"""
        <p><strong>{len(cams)} license plate readers</strong> mapped in this area by OpenStreetMap volunteers.</p>
        <ul class="newest-list">{newest}</ul>
        <p class="note" style="margin-top:8px">Mapping is crowdsourced &mdash; mapped dates are not installation dates.
        <a href="{rel}surveillance/">Full map &rarr;</a></p>"""
    else:
        alpr_html = ('<p class="note">No ALPR cameras mapped in this area. Camera mapping is '
                     'crowdsourced and concentrated in the Bakersfield metro core.</p>')

    # ---- what to watch
    if meta["citywide"]:
        up = escribe.get("upcoming", [])[:2]
        if up:
            m_lis = "".join(f'<li><a href="{html.escape(m.get("url", f"{rel}city-hall/"))}" rel="noopener">{html.escape(m.get("name", "Public meeting"))}</a> <span class="when">{html.escape((m.get("start_iso") or "").replace("T", " · "))}</span></li>' for m in up)
            watch_html = f'<ul class="hl">{m_lis}</ul><p class="note">City of Bakersfield meetings are citywide; neighborhood-specific agendas are rare.</p>'
        else:
            watch_html = '<p class="note">No upcoming city meetings posted.</p>'
    else:
        watch_html = f'<p class="note">{html.escape(meta.get("school_note", ""))} City of Bakersfield meetings do not cover Tehachapi.</p>'

    body = f"""
    <div class="pagehead">
      <nav class="breadcrumbs"><a href="{rel}index.html">Daily Brief</a> &rsaquo;
      <a href="{rel}places/">Places</a> &rsaquo; {html.escape(name)}</nav>
      <div class="hero"><p class="kicker">Places &middot; hyperlocal</p>
      <h1>{html.escape(name)}</h1>
      <p class="lede">{html.escape(meta["blurb"])}</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>auto-generated from public data</span></div></div>
    </div>

    {conditions}

    <div class="brief-grid" style="margin-top:6px">
      <div class="brief-main">
        <section aria-labelledby="h-chp">
          <p class="sec-head" id="h-chp">Incidents near {html.escape(name.split()[0]) if name.startswith("Bakersfield") else html.escape(name)} <span class="unit">CHP, last 7 days</span></p>
          {chp_html}
        </section>
        <section aria-labelledby="h-hl">
          <p class="sec-head" id="h-hl">In the headlines <span class="unit">local outlets, last 3 days</span></p>
          {headlines_html}
          <p class="ng-credit">Aggregated via Google News from local outlets (Tehachapi News, KGET, 23ABC, Bakersfield.com and more) plus KGET/23ABC headline matching.</p>
        </section>
      </div>
      <aside class="sidebar">
        <div class="side-box">
          <h2>Plate readers in this area</h2>
          {alpr_html}
        </div>
        <div class="side-box">
          <h2>What to watch</h2>
          {watch_html}
        </div>
        <div class="ad-slot" data-ad-slot="place-sidebar" aria-hidden="true"></div>
      </aside>
    </div>

    <p class="note">How this page is built: headlines come from Google News aggregation and
    outlet keyword matching; incidents and cameras by geolocation against public records (CHP,
    OpenStreetMap/ODbL). Matching is best-effort &mdash; see the <a href="{rel}about/">About</a>
    page for sourcing policy.</p>"""

    page = page_mod.render(
        title=f"{html.escape(name)} — local conditions, incidents & news | Bakersfield Daily Brief",
        desc=f"Hyperlocal page for {html.escape(name)}: local forecast, CHP incidents, headlines, plate readers, and what to watch — auto-generated daily.",
        canonical=f"/places/{slug}/",
        content=body, current="places", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "")
    return page


# ---------------------------------------------------------------- hub
def _hub(ctx, built_iso: str, weather) -> str:
    rel = "../"
    cards = "".join(f"""
        <a class="card" href="{rel}places/{slug}/">
          <span class="tag green">Hyperlocal</span>
          <h3>{html.escape(meta['name'])}</h3>
          <p>{html.escape(meta['blurb'])}</p>
          <span class="card-go">Open {html.escape(meta['name'])}</span>
        </a>""" for slug, meta in PLACES.items())

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Places</p>
      <h1>Your part of Kern County</h1>
      <p class="lede">Hyperlocal pages for parts of town in Bakersfield and for Tehachapi —
      local conditions, CHP incidents, headlines from local outlets, plate readers, and
      what to watch. Built daily from public data.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>Google News aggregation + keyword &amp; geolocation matching</span></div></div>
    </div>
    <div class="grid cols-3">{cards}</div>

    <section class="block">
      <div class="sign-head"><span class="tab">How</span><h2>How place pages are filled</h2></div>
      <div class="card"><p>Headlines are aggregated from Google News (which indexes Tehachapi
      News, KGET, 23ABC, Bakersfield.com and other local outlets) filtered to each area, plus
      keyword matching against KGET/23ABC feeds. Incidents and cameras are matched by
      coordinates against CHP and OpenStreetMap records, with a rolling 7-day incident archive.
      Everything refreshes on the daily build &mdash; coverage varies by what outlets publish,
      and every page states its own limits rather than padding.</p>
      <p>Zones in Bakersfield share the metro forecast; Tehachapi gets its own mountain
      forecast from the NWS Hanford gridpoint.</p></div>
    </section>"""

    page = page_mod.render(
        title="Places — Bakersfield neighborhoods & Tehachapi | Bakersfield Daily Brief",
        desc="Hyperlocal sections for Bakersfield neighborhoods and Tehachapi: local conditions, incidents, headlines, plate readers, and meeting watch — auto-generated daily.",
        canonical="/places/",
        content=body, current="places", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "")
    return page


# ---------------------------------------------------------------- filters
def _matching_headlines(news: dict, meta: dict) -> list:
    out = []
    for h in news.get("headlines", []):
        t = (h.get("title") or "").lower()
        if any(a in t for a in meta["aliases"]):
            out.append(h)
    return out


def _place_headlines(gnews: dict, news: dict, slug: str, meta: dict, limit: int = 10) -> list:
    """Google News results for the place first, then outlet keyword matches,
    deduped by normalized title so the same story never appears twice."""
    out: list[dict] = []
    seen: set[str] = set()

    def norm(t: str) -> str:
        import re as _re
        return _re.sub(r"[^a-z0-9]+", "", (t or "").lower())[:70]

    for h in gnews.get("results", {}).get(slug, []):
        k = norm(h.get("title", ""))
        if k and k not in seen:
            seen.add(k)
            out.append(h)
    for h in _matching_headlines(news, meta):
        k = norm(h.get("title", ""))
        if k and k not in seen:
            seen.add(k)
            out.append(h)
    return out[:limit]


def _nearby_chp(chp: dict, meta: dict) -> list:
    cx, cy = meta["center"]
    r = meta["radius_km"]
    logs = chp.get("archive") or chp.get("logs", [])
    out = []
    for i in logs:
        if i.get("lat") is not None and i.get("lon") is not None:
            if _haversine(cx, cy, i["lat"], i["lon"]) <= r:
                out.append(i)
        else:
            hay = f"{i.get('location', '')} {i.get('area', '')}".lower()
            if any(a in hay for a in meta["aliases"]):
                out.append(i)
    return out


def _cameras_near(alpr: dict, meta: dict) -> list:
    cx, cy = meta["center"]
    r = meta["radius_km"]
    return [c for c in alpr.get("cameras", [])
            if c.get("lat") is not None and c.get("lon") is not None
            and _haversine(cx, cy, c["lat"], c["lon"]) <= r]


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _forecast_for(point: tuple | None) -> dict:
    """Today's high/low for a NWS gridpoint (cached per build)."""
    if point is None:
        return {}
    if point in _FORECAST_CACHE:
        return _FORECAST_CACHE[point]
    out = {"high": None, "low": None}
    try:
        pt = common.fetch(f"https://api.weather.gov/points/{point[0]:.4f},{point[1]:.4f}",
                          headers={"Accept": "application/geo+json"})
        fc_url = pt.json()["properties"]["forecast"]
        periods = common.fetch(fc_url, headers={"Accept": "application/geo+json"}).json()["properties"]["periods"]
        today = common.today_pacific().isoformat()
        highs, lows = [], []
        for p in periods:
            if (p.get("startTime") or "")[:10] == today:
                if p.get("isDaytime"):
                    highs.append(p.get("temperature"))
                else:
                    lows.append(p.get("temperature"))
        if highs:
            out["high"] = max(highs)
        if lows:
            out["low"] = min(lows)
    except Exception:  # noqa: BLE001
        pass
    _FORECAST_CACHE[point] = out
    return out
