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
    hourly = tw.get("hourly", [])
    days = _days(forecast)
    rel = "../"

    # ---- current conditions card
    # id="tw-now" / "tw-answer" / "tw-observed" are what assets/js/live-tehachapi-weather.js
    # rewrites when the station has reported since this build.
    cond_html = ('<div class="errorbox" id="tw-now">Current Tehachapi weather is unavailable '
                 'this build.</div>')
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
            f'<div class="card" id="tw-now" data-ts="{html.escape(cur.get("timestamp", ""))}">'
            '<h3>Right now in Tehachapi</h3>'
            f'<p class="big-word" style="font-size:2rem">{bits[0]}' +
            (" &middot; " + " &middot; ".join(x for x in bits[1:] + wind) if (bits[1:] or wind) else "") +
            (f" &middot; {cond}" if cond else "") + '</p>'
            f'<p class="note">NWS station <strong>{html.escape(station)}</strong> (Tehachapi), '
            f'observed {html.escape(obs)}.</p></div>')

    # ---- 7-day forecast, one row per day (high from the day period, low from the night)
    fc_html = '<p class="note">Forecast unavailable this build.</p>'
    if days:
        rows = "".join(
            f'<tr><td>{html.escape(d["name"])}</td>'
            f'<td>{_deg(d["high"])}</td><td>{_deg(d["low"])}</td>'
            f'<td>{html.escape(d["wind"])}</td>'
            f'<td>{html.escape(d["short"])}{_pop_txt(d["pop"])}</td></tr>'
            for d in days)
        fc_html = (f'<div class="table-wrap"><table class="data">'
                   f'<thead><tr><th>Day</th><th>High</th><th>Low</th><th>Wind</th><th>Forecast</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div>'
                   f'<p class="note">Source: National Weather Service 7-day forecast for '
                   f'HNX/87,20 (Tehachapi).</p>')

    # ---- next 12 hours
    hr_html = '<p class="note">The hourly forecast is unavailable this build.</p>'
    if hourly:
        rows = "".join(
            f'<tr><td>{html.escape(h["time"])}</td><td>{_deg(h.get("temp_f"))}</td>'
            f'<td>{html.escape(h.get("wind_speed", ""))} {html.escape(h.get("wind_dir", ""))}</td>'
            f'<td>{html.escape(h.get("short", ""))}{_pop_txt(h.get("pop"))}</td></tr>'
            for h in hourly)
        hr_html = (f'<div class="table-wrap"><table class="data">'
                   f'<thead><tr><th>Time</th><th>Temp</th><th>Wind</th><th>Forecast</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div>'
                   f'<p class="note">Source: National Weather Service hourly forecast for HNX/87,20, '
                   f'as of the last page build.</p>')

    # ---- Tehachapi vs Bakersfield (both NWS; build-time readings, each with its time)
    compare = _compare(cur, days, (sources.get("weather") or {}).get("forecast") or {})

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

    # ---- evergreen lead. Google quotes the first text after the H1 in results and
    # keeps it for days; a "right now" reading there showed searchers a temperature
    # three days old. The live reading lives in the card below, which the live
    # script keeps current.
    direct = ('<p class="answer"><strong>Tehachapi weather today:</strong> the live reading from the '
              'Tehachapi Municipal Airport station (KTSP), the National Weather Service 7-day forecast '
              'with daily highs and lows, the next 12 hours, and any wind, snow or winter-storm alerts '
              'for the Tehachapi Mountains.</p>')

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
         ("The National Weather Service forecast for Tehachapi: " +
          "; ".join(_day_txt(d) for d in days[:4]) + "." if days else
          "The NWS forecast is unavailable this build.")),
        ("Is Tehachapi cooler than Bakersfield?", compare["faq"]),
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
         "This page rebuilds several times a day, and the current reading rechecks itself "
         "while the page is open."),
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
      <div class="meta"><span>NWS observation: <span id="tw-observed">{html.escape(cur.get("observed", "unavailable this build")) if cur.get("ok") else "unavailable this build"}</span></span>
      <span class="dot">&bull;</span><span>rechecked while this page is open</span></div></div>
    </div>

    {direct}

    {images.figure("tehachapi", rel)}

    {cond_html}

    <section class="block">
      <div class="sign-head"><span class="tab">7-day</span><h2>Tehachapi 7-day forecast</h2></div>
      <div class="card">{fc_html}</div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Hourly</span><h2>Next 12 hours in Tehachapi</h2></div>
      <div class="card">{hr_html}</div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Compare</span><h2>Tehachapi vs. Bakersfield</h2></div>
      <div class="card">{compare["html"]}</div>
    </section>

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
    zone CAZ334; Bakersfield comparison from station KBFL), each shown with its own observed/updated time. This page is an independent summary;
    always confirm severe-weather alerts on weather.gov. Never a fabricated reading — when a source is
    unreachable it says so.</p>"""

    page = page_mod.render(
        title="Tehachapi Weather | Current Conditions & Forecast | Bakersfield Daily Brief",
        desc="Tehachapi weather: live reading from the Tehachapi airport station, the NWS 7-day forecast with highs and lows, the next 12 hours, and wind and snow alerts.",
        canonical="/tehachapi-weather/", content=body, current="trackers", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq(live_answer, faq_qa)],
        extra_scripts='<script src="{rel}assets/js/live-tehachapi-weather.js" defer></script>'.format(rel=rel))
    common.write(common.SITE / "tehachapi-weather" / "index.html", page)
    built.append("tehachapi-weather/index.html")

    ctx.build_report["tehachapi_weather"] = {
        "temp": cur.get("temperature"),
        "wind_mph": cur.get("wind_mph"),
        "alerts": len(alerts),
    }
    return built


def _deg(v) -> str:
    return f"{v}°" if v is not None else "—"


def _pop_txt(pop) -> str:
    return f" ({pop}% chance of rain)" if pop and pop >= 10 else ""   # 1-9% is noise on every row


def _day_txt(d: dict) -> str:
    temps = ", ".join(x for x in (f"high {d['high']}°" if d["high"] is not None else "",
                                   f"low {d['low']}°" if d["low"] is not None else "") if x)
    return d["name"] + (f" {temps}" if temps else "") + (f", {d['short'].lower()}" if d["short"] else "")


def _days(forecast: list) -> list:
    """Group NWS day/night periods into one row per day: the high from the day
    period, the low from the night after it. A forecast that starts at night gives
    a first row with only a low ('Tonight'); the last day may have no low yet."""
    days = []
    for p in forecast:
        row = {"name": p.get("name", ""), "high": None, "low": None,
               "wind": f'{p.get("wind_speed", "")} {p.get("wind_dir", "")}'.strip(),
               "short": p.get("short", ""), "pop": p.get("pop")}
        if p.get("is_daytime", True):
            row["high"] = p.get("temp_f")
            days.append(row)
        elif days and days[-1]["high"] is not None and days[-1]["low"] is None:
            days[-1]["low"] = p.get("temp_f")
            pops = [x for x in (days[-1]["pop"], p.get("pop")) if x is not None]
            days[-1]["pop"] = max(pops) if pops else None
        else:
            row["low"] = p.get("temp_f")
            days.append(row)
    return days[:7]


def _compare(cur: dict, days: list, bfl: dict) -> dict:
    """Tehachapi vs Bakersfield from NWS data only. Every number shown has a source;
    a side that did not report makes the comparison 'unavailable', never estimated."""
    elev = ("Tehachapi sits at about 4,000 feet and Bakersfield at about 400 feet, "
            "so Tehachapi usually runs cooler and windier.")
    bits = []
    t_now = cur.get("temperature") if cur.get("ok") else None
    b_now = bfl.get("current")
    if t_now is not None and b_now is not None:
        diff = b_now - t_now
        rel = (f"{diff}° cooler" if diff > 0 else f"{-diff}° warmer" if diff < 0 else "the same temperature")
        bits.append(f"At the last page update it was {t_now}°F in Tehachapi "
                    f"(KTSP, {cur.get('observed') or 'latest reading'}) and {b_now}°F in Bakersfield "
                    f"(KBFL, {bfl.get('observed') or 'latest reading'}), so Tehachapi was {rel}.")
    t_hi = days[0]["high"] if days else None
    b_hi = bfl.get("high")
    if t_hi is not None and b_hi is not None and days[0]["name"] in ("Today", "This Afternoon"):
        bits.append(f"Today's NWS forecast high is {t_hi}° in Tehachapi and {b_hi}° in Bakersfield.")
    if not bits:
        bits.append("A side-by-side reading is unavailable this build.")
    text = " ".join(bits)
    return {"faq": f"{text} {elev}",
            "html": (f'<p>{html.escape(text)}</p><p class="note">{elev} '
                     'Bakersfield figures are from the NWS station at Meadows Field (KBFL).</p>')}


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