#!/usr/bin/env python3
"""Weather page — /weather/. Live NWS 7-day forecast for Bakersfield (HNX
gridpoint) + the live Hanford radar loop image + active Kern alerts."""
from __future__ import annotations

import html

from .. import common
from . import images
from . import page as page_mod


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = ""
    radar = sources.get("radar", {})
    weather = sources.get("weather", {})

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Weather · National Weather Service</p>
      <h1>Bakersfield weather &amp; radar</h1>
      <p class="lede">The 7-day forecast for Bakersfield from the National Weather Service
      (Hanford office), the live Hanford radar loop, and active alerts for Kern County —
      refreshed every build.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>api.weather.gov · no key required</span></div></div>
    </div>
    {_radar(radar)}
    {_alerts(weather, rel)}
    {_forecast(radar)}
    {_context(rel)}
    """

    page = page_mod.render(
        title="Bakersfield weather & radar — 7-day forecast | Bakersfield Daily Brief",
        desc="Bakersfield weather forecast from the National Weather Service: 7-day forecast, live Hanford radar loop, and active Kern County alerts.",
        canonical="/weather/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "weather" / "index.html", page)
    built.append("weather/index.html")

    ctx.build_report["weather_page"] = {
        "ok": radar.get("ok", False), "periods": radar.get("count", 0),
        "alerts": weather.get("count", 0), "asof": radar.get("asof", built_iso),
    }
    return built


def _radar(radar: dict) -> str:
    if not radar.get("ok"):
        return ""
    url = radar.get("radar_url", "")
    if not url:
        return ""
    return f"""
    <figure class="fig">
      <img src="{html.escape(url)}" alt="Live NEXRAD radar loop for the Hanford (KHNX) radar covering Bakersfield and Kern County"
           loading="lazy" style="width:100%;height:auto;background:#0d1b2a">
      <figcaption>Live radar loop &middot; KHNX Hanford NEXRAD &middot; National Weather Service</figcaption>
    </figure>"""


def _alerts(weather: dict, rel: str) -> str:
    alerts = weather.get("alerts", []) if weather.get("ok") else []
    if not alerts:
        return ('<p class="note">No active NWS alerts for Kern County right now. '
                'Alerts and the day&rsquo;s forecast also appear on the '
                f'<a href="{rel}index.html">Daily Brief</a>.</p>')
    items = "".join(
        f'<li><strong>{html.escape(a.get("event", "Alert"))}</strong> — '
        f'{html.escape((a.get("headline") or "")[:120])} '
        f'<span class="cat-tag red">{html.escape(a.get("severity", ""))}</span></li>'
        for a in alerts[:5])
    return f"""
    <section class="block">
      <div class="sign-head"><span class="tab red">Alert</span><h2>Active alerts — Kern County</h2></div>
      <div class="card"><ul style="margin:0 0 0 18px">{items}</ul>
      <p class="note">Source: <a href="https://api.weather.gov/alerts/active?area=CA" rel="noopener">NWS alerts feed</a>.
      Always confirm on the official alert before acting.</p></div>
    </section>"""


def _forecast(radar: dict) -> str:
    if not radar.get("ok"):
        return ('<div class="card"><p class="note">NWS forecast data is unavailable this build '
                f'({html.escape(str(radar.get("error", "unknown")))}). '
                'Check back after the next build.</p></div>')
    periods = radar.get("periods", [])

    # group: daytime cards + a nightly compact strip
    days = [p for p in periods if p.get("is_daytime")]
    nights = [p for p in periods if not p.get("is_daytime")]

    cards = ""
    for d in days[:7]:
        low = next((n.get("temp") for n in nights
                    if n.get("day") == d.get("day")), None)
        low_html = f"Low {low}°" if low is not None else "&nbsp;"
        icon = d.get("icon", "")
        img = f'<img src="{html.escape(icon)}" alt="" loading="lazy" width="60" height="60">' if icon else ""
        cards += f"""
        <div class="wx-day">
          <div class="wx-icon">{img}</div>
          <div class="wx-name">{html.escape(d.get("name", ""))}</div>
          <div class="wx-temp">{d.get("temp")}°{html.escape(d.get("unit", "F"))}</div>
          <div class="wx-low">{low_html}</div>
          <div class="wx-short">{html.escape(d.get("short", ""))}</div>
          <div class="wx-wind">Wind {html.escape(d.get("wind", ""))}</div>
        </div>"""

    return f"""
    <section class="block">
      <div class="sign-head"><span class="tab">7-day</span><h2>Forecast</h2></div>
      <div class="wx-grid">{cards}</div>
      <p class="note">Forecast: National Weather Service, Hanford office (HNX), via api.weather.gov.
      Highs and lows are as published by NWS; conditions can change quickly in summer.</p>
    </section>"""


def _context(rel: str) -> str:
    return f"""
    <section class="block">
      <div class="sign-head"><span class="tab">i</span><h2>About this page</h2></div>
      <div class="card"><p>Radar and forecast data come straight from the National Weather Service
      &mdash; no API key, no third party. The radar loop updates every few minutes; the forecast
      refreshes with each site build.</p>
      <p>Related: <a href="{rel}grapevine/">Grapevine conditions</a> for the I-5 corridor,
      <a href="{rel}water/">Isabella Lake</a> levels, and the day&rsquo;s conditions on the
      <a href="{rel}index.html">Daily Brief</a>.</p></div>
    </section>"""
