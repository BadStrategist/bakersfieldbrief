#!/usr/bin/env python3
"""Tehachapi Weather page — /tehachapi-weather/.

Year-round demand (unlike the pass page's winter spike) around 'tehachapi
weather' / 'tehachapi weather forecast'. Same proven live-tracker formula as
/grapevine/ and /tehachapi-pass/: direct quotable answer answering the query,
FAQPage JSON-LD with the live reading in Q1, real timestamps, honesty guards.

All data comes keyless from the existing build/sources/tehachapi_weather.py:
KTSP (Tehachapi Municipal Airport) current observation, NWS HNX/87,20 forecast
periods, and CAZ334 alerts. Every source degrades to 'unavailable this build'
— never a fabricated reading.
"""
from __future__ import annotations

import html
import re

from .. import common
from . import images
from . import page as page_mod
from .tehachapi import _sev_cls  # reuse severity→color map


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    tw = sources.get("tehachapi_weather", {})
    cur = tw.get("current", {})
    forecast = tw.get("forecast", [])
    alerts = tw.get("alerts", [])
    rel = "../"

    # ---- current conditions card
    cond_html = '<div class="errorbox">Current Tehachapi weather is unavailable this build.</div>'
    if cur.get("ok"):
        bits = []
        if cur.get("temperature") is not None:
            bits.append(f'{cur["temperature"]}°F')
        else:
            bits.append("temp unavailable")
        wind = []
        if cur.get("wind_mph") is not None:
            gust = f" (gusts to {cur['gust_mph']} mph)" if cur.get("gust_mph") else ""
            wind.append(f"{cur['wind_mph']} mph{gust} from {cur.get('wind_dir') or '?'}")
        if cur.get("humidity") is not None:
            bits.append(f"humidity {cur['humidity']}%")
        cond = cur.get("condition") or ""
        obs = cur.get("observed", "")
        station = cur.get("station", "?")
        cond_html = (
            '<div class="card"><h3>Right now in Tehachapi</h3>'
            f'<p class="big-word" style="font-size:2rem">{bits[0]}' +
            (" &middot; " + " &middot; ".join(x for x in bits[1:] + wind) if (bits[1:] or wind) else "") +
            (f" &middot; {cond}" if cond else "") + '</p>'
            f'<p class="note">NWS station <strong>{html.escape(station)}</strong> (Tehachapi), '
            f'observed {html.escape(obs)}.</p></div>')

    # ---- forecast
    fc_html = '<p class="note">Forecast unavailable this build.</p>'
    if forecast:
        rows = "".join(
            f'<tr><td>{html.escape(p.get("name", ""))}</td>'
            f'<td>{p.get("temp_f", "—")}°</td>'
            f'<td>{html.escape(p.get("wind_speed", ""))} {html.escape(p.get("wind_dir", ""))}</td>'
            f'<td>{html.escape(p.get("short", ""))}</td></tr>'
            for p in forecast[:6])
        fc_html = (f'<div class="table-wrap"><table class="data">'
                   f'<thead><tr><th>Period</th><th>Temp</th><th>Wind</th><th>Forecast</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div>'
                   f'<p class="note">Source: National Weather Service forecast for '
                   f'HNX/87,20 (Tehachapi).</p>')

    # ---- alerts
    al_html = ('<p>No active NWS advisories for the Tehachapi area (CAZ334).</p>'
               f'<p class="note">Source: National Weather Service. Zone CAZ334 · '
               f'<a href="https://www.weather.gov/hnx/" target="_blank" rel="noopener">weather.gov/hnx</a></p>')
    if alerts:
        items = "".join(
            f'<li><span class="tag {_sev_cls(a.get("severity"))}">{html.escape(a.get("severity", ""))}</span> '
            f'<strong>{html.escape(a.get("event", ""))}</strong> {html.escape(a.get("headline", ""))}</li>'
            for a in alerts)
        al_html = f'<ul class="hl">{items}</ul><p class="note">Source: NWS. Confirm at weather.gov.</p>'

    # ---- direct quotable answer (Q1-targeted, first text after H1)
    if cur.get("ok"):
        direct = (f'<p class="answer"><strong>Right now it is {cur.get("temperature", "—")}°F in '
                  f'Tehachapi</strong>'
                  + (f' with {cur["wind_mph"]} mph wind from {cur.get("wind_dir") or "?"}'
                     if cur.get("wind_mph") is not None else '')
                  + (f', {cond}' if (cond := cur.get("condition")) else '')
                  + f'. Observed by the NWS {html.escape(cur.get("station", "station"))} at '
                  + f'{html.escape(cur.get("observed", "the latest observation"))}.</p>')
    else:
        direct = ('<p class="answer">A current Tehachapi reading is unavailable this build — the NWS '
                  'station did not report. Check back for the live forecast.</p>')

    # ---- FAQ (visible + schema). Q1 carries the live reading.
    now_temp = cur.get("temperature") if cur.get("ok") else None
    q1 = (f"Right now it is {now_temp}°F in Tehachapi, "
          + (f"with {cur['wind_mph']} mph wind"
             + (f" from {cur.get('wind_dir')}" if cur.get("wind_dir") else "")
             + (f" and gusts to {cur['gust_mph']} mph" if cur.get("gust_mph") else "")
             if cur.get("wind_mph") is not None else "wind not currently reported")
          + f", observed at {cur.get('observed') or 'the latest NWS observation'}." if cur.get("ok")
          else "A current Tehachapi reading is unavailable this build.")
    faq_qa = [
        ("What's the weather in Tehachapi right now?",
         q1 if cur.get("ok") else "A current Tehachapi weather reading is unavailable this build."),
        ("What is the Tehachapi weather forecast?",
         ("The National Weather Service predicts: " +
          "; ".join(f"{p.get('name','')} {p.get('temp_f','—')}° with {p.get('wind_speed','')} {p.get('wind_dir','')}"
                    for p in forecast[:4]) + "." if forecast else
          "The NWS forecast is unavailable this build.")),
        ("Does it snow in Tehachapi?",
         "Yes — Tehachapi sits at about 4,000 ft elevation, so it sees snow in winter storms. "
         "Check the winter road conditions on the " +
         '<a href="/tehachapi-pass/">Tehachapi Pass page</a> for chain-control and closure status.'),
        ("How windy is Tehachapi?",
         (f"Right now the NWS reports {cur['wind_mph']} mph"
          + (f" with gusts to {cur['gust_mph']} mph" if cur.get("gust_mph") else "")
          + f" from {cur.get('wind_dir') or 'the prevailing direction'}." if cur.get("wind_mph") is not None
          else "Wind data is unavailable this build.")),
        ("How do I get the official Tehachapi forecast?",
         "The National Weather Service forecast for Tehachapi is at weather.gov — zone CAZ334. "
         "This page refreshes 3 times daily."),
    ]
    faq_html = "".join(
        f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq_qa)
    live_answer = re.sub(r"<[^>]+>", "", faq_qa[0][1])

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Weather · National Weather Service</p>
      <h1>Tehachapi Weather</h1>
      <p class="lede">Live current conditions and forecast for Tehachapi, California (elevation ~4,000 ft)
      — temperature, wind, and alerts from the National Weather Service.</p>
      <div class="meta"><span>NWS observation: {html.escape(cur.get("observed", "unavailable this build")) if cur.get("ok") else "unavailable this build"}</span>
      <span class="dot">&bull;</span><span>refreshes 3× daily</span></div></div>
    </div>

    {direct}

    {images.figure("tehachapi", rel)}

    <div class="grid cols-2">
      {cond_html}
      <div class="card"><h3>Forecast</h3>{fc_html}</div>
    </div>

    <section class="block">
      <div class="sign-head"><span class="tab">Alerts</span><h2>NWS alerts for the area</h2></div>
      <div class="card">{al_html}</div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Related</span><h2>Tehachapi road & travel</h2></div>
      <div class="card"><ul class="hl">
        <li><a href="/tehachapi-pass/">Tehachapi Pass road conditions (SR-58)</a> — is the pass open
        right now?</li>
        <li><a href="/grapevine/">The Grapevine (I-5 / Tejon Pass)</a> — the main LA↔Bakersfield route.</li>
        <li><a href="/fires/">Kern County wildfire tracker</a> — air-quality impacts for the mountains.</li>
      </ul></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Why</span><h2>Tehachapi's weather</h2></div>
      <div class="card"><p>Tehachapi sits at about <strong>4,000 feet</strong> on the western edge of the
      Mojave Desert, where the San Joaquin Valley meets the high desert. That elevation and the pass
      geography give it cool summers, cold winters, and strong winds year-round — some of the most
      consistent wind energy in the state, hence the windmills.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">FAQ</span><h2>Tehachapi weather questions</h2></div>
      <div class="card">{faq_html}</div>
    </section>

    <p class="note">Weather data from the National Weather Service (station KTSP, forecast HNX/87,20,
    zone CAZ334), each shown with its own observed/updated time. This page is an independent summary;
    always confirm severe-weather alerts on weather.gov. Never a fabricated reading — when a source is
    unreachable it says so.</p>"""

    page = page_mod.render(
        title="Tehachapi Weather | Current Conditions & Forecast | Bakersfield Daily Brief",
        desc="Live Tehachapi weather — current temperature, wind, and forecast from the National Weather Service, plus alerts. Updated 3x daily.",
        canonical="/tehachapi-weather/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq(live_answer, faq_qa)])
    common.write(common.SITE / "tehachapi-weather" / "index.html", page)
    built.append("tehachapi-weather/index.html")

    ctx.build_report["tehachapi_weather"] = {
        "temp": cur.get("temperature"),
        "wind_mph": cur.get("wind_mph"),
        "alerts": len(alerts),
    }
    return built


def _faq(live_answer: str | None, faq_qa) -> dict:
    """FAQPage schema. Q1's answer carries the live reading for AI/featured."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer",
                                "text": (live_answer if (i == 0 and live_answer) else a)}}
            for i, (q, a) in enumerate(faq_qa)
        ],
    }