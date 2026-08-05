#!/usr/bin/env python3
"""Email-safe renderings of the Daily Brief (and the Weekend Guide).

The email is the SAME data payload the homepage is built from, rendered twice:

  - HTML: table-based layout, inline styles only, web-safe fonts, no JS,
    no forms, ~600px. Works in Outlook, Gmail, and friends.
  - TXT:  plain-text fallback of the identical content.

Output: email/<date>/brief.{html,txt} and email/latest/ copies. The daily
workflow auto-commits these so any mailing service can pick them up later.
Delivery wiring is deliberately out of scope until launch.
"""
from __future__ import annotations

import html as H
from datetime import datetime

from . import common

GREEN = "#232B30"
DEEP = "#1A2126"
AMBER = "#DC9A1F"
INK = "#20262C"
PAPER = "#F5F7F6"
MUTED = "#57504A"

BASE_URL = "https://bakersfieldbrief.com"


# ---------------------------------------------------------------- brief
def render_brief(ctx, sources: dict, today, rel: str = "") -> list[str]:
    """Render today's brief as email-safe HTML + plain text. Returns file paths."""
    built = []
    date_label = f"{today.strftime('%B')} {today.day}, {today.year}"

    weather = sources.get("weather", {})
    chp = sources.get("chp", {})
    isa = sources.get("isabella", {})
    airnow = sources.get("airnow", {})
    calfire = sources.get("calfire", {})
    news = sources.get("news_rss", {})
    escribe = sources.get("escribe", {})
    board = sources.get("kern_board", {})
    abc = sources.get("abc", {})
    food = sources.get("food", {})
    headlines = news.get("headlines", [])[:8]

    # ---- conditions
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    weather_v = f"{cur}° / {hi}°" if cur and hi else (f"{hi}°" if hi else "n/a")
    alerts = (weather or {}).get("alerts", [])
    alert_v = f"{alerts[0]['event']} active" if alerts else "No active alerts"
    isa_last = isa.get("last")
    isa_v = f"{isa_last['value']:,} AF ({isa.get('pct')}% cap)" if isa_last else "n/a"
    chp_v = f"{len(chp.get('new', []))} overnight" if chp.get("new") else "None overnight"
    if airnow.get("ok") and airnow.get("aqi") is not None:
        aqi_v = f"AQI {airnow['aqi']} · {airnow.get('category')}"
    elif airnow.get("needs_key"):
        aqi_v = "AQI awaiting key"
    else:
        aqi_v = "AQI unavailable"
    kern_fires = [f for f in calfire.get("incidents", []) if "Kern" in str(f.get("county", ""))]
    fire_v = f"{len(kern_fires)} active in Kern" if kern_fires else "0 active in Kern"

    conds = [
        ("Weather", weather_v), ("Alerts", alert_v), ("Isabella", isa_v),
        ("CHP", chp_v), ("Air", aqi_v), ("Fires", fire_v),
    ]

    # ---- news (headlines + links only, source-credited)
    news_html = ""
    news_txt = ""
    for h in headlines:
        title = H.escape(h.get("title", ""))
        url = H.escape(h.get("url", "#"), quote=True)
        src = H.escape(h.get("source", "news"))
        news_html += (f'<tr><td style="padding:6px 0;border-bottom:1px solid #E3E0DA">'
                      f'<a href="{url}" style="color:{GREEN};font-weight:bold;text-decoration:none">{title}</a>'
                      f'<br><span style="font-size:11px;color:{MUTED}">{src}</span></td></tr>')
        news_txt += f"• {h.get('title', '')} ({h.get('source', '')}) — {h.get('url', '')}\n"

    # ---- one thing to watch
    watch = _one_thing(escribe, board)
    watch_html = f'<p style="font-family:Georgia,serif;font-size:15px;line-height:1.5;color:{INK}">{watch}</p>'
    watch_txt = watch

    # ---- openings count
    n_abc = len(abc.get("items", [])) if abc.get("ok") else 0
    n_food = len(food.get("items", [])) if food.get("ok") else 0

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bakersfield Daily Brief — {H.escape(date_label)}</title></head>
<body style="margin:0;padding:0;background:{PAPER}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #E3E0DA">

<tr><td style="background:{GREEN};padding:18px 24px">
  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;letter-spacing:2px;color:#C9E4D2">{H.escape(date_label)}</p>
  <h1 style="margin:4px 0 0;font-family:Georgia,serif;font-size:24px;color:#ffffff">The Bakersfield Brief</h1>
  <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#C9E4D2">Bakersfield &amp; Kern County — {H.escape(date_label)}</p>
</td></tr>

<tr><td style="padding:16px 24px">
  <h2 style="margin:0 0 8px;font-family:Georgia,serif;font-size:16px;color:{DEEP}">Conditions</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{''.join(
      f'<tr><td style="padding:3px 0;font-family:Arial,sans-serif;font-size:13px;color:{INK}"><span style="font-weight:bold">{H.escape(k)}:</span> {H.escape(v)}</td></tr>'
      for k, v in conds)}</table>
</td></tr>

<tr><td style="padding:0 24px 16px">
  <h2 style="margin:0 0 8px;font-family:Georgia,serif;font-size:16px;color:{DEEP}">The News</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{news_html}</table>
  <p style="font-family:Arial,sans-serif;font-size:11px;color:{MUTED}">Headlines link to the original reporting. We never republish article text.</p>
</td></tr>

<tr><td style="padding:0 24px 16px">
  <h2 style="margin:0 0 8px;font-family:Georgia,serif;font-size:16px;color:{DEEP}">One Thing to Watch</h2>
  {watch_html}
</td></tr>

<tr><td style="padding:0 24px 16px">
  <h2 style="margin:0 0 8px;font-family:Georgia,serif;font-size:16px;color:{DEEP}">Openings &amp; Closings</h2>
  <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;color:{INK}">{n_abc} new license application(s), {n_food} closure(s) on file. <a href="{BASE_URL}/openings/" style="color:{GREEN}">Full list →</a></p>
</td></tr>

<tr><td style="background:{PAPER};padding:14px 24px;border-top:2px solid {AMBER}">
  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;color:{MUTED}">Read it on the web: <a href="{BASE_URL}/" style="color:{GREEN}">{BASE_URL}</a> &nbsp;·&nbsp; Ad-free newsletter, supported by clearly labeled ads on the site.</p>
  <p style="margin:4px 0 0;font-family:Arial,sans-serif;font-size:10px;color:{MUTED}">You're receiving this because you subscribed to the Bakersfield Brief. Manage your subscription anytime — unsubscribe link goes here once delivery is wired.</p>
</td></tr>

</table></td></tr></table>
</body></html>"""

    txt_doc = f"""THE BAKERSFIELD BRIEF — {date_label}
Bakersfield & Kern County

CONDITIONS
{chr(10).join(f"{k}: {v}" for k, v in conds)}

THE NEWS
{news_txt}
Headlines link to the original reporting at the outlets named.

ONE THING TO WATCH
{watch_txt}

OPENINGS & CLOSINGS
{n_abc} new license application(s), {n_food} closure(s) on file — {BASE_URL}/openings/

Web: {BASE_URL}/
"""

    out_dir = common.ROOT / "email" / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = common.ROOT / "email" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for name, content in (("brief.html", html_doc), ("brief.txt", txt_doc)):
        (out_dir / name).write_text(content, encoding="utf-8")
        (latest / name).write_text(content, encoding="utf-8")
        built.append(f"email/{today.isoformat()}/{name}")
    common.log(f"email brief rendered: {len(html_doc)} html chars, {len(txt_doc)} txt chars")
    return built


# ---------------------------------------------------------------- guide
def render_guide(events: list[dict], date_label: str, reviewed: bool = False) -> tuple[str, str]:
    """Weekend Guide as (html, txt). reviewed=False → header says DRAFT."""
    banner = "DRAFT — review before sending" if not reviewed else "Weekend Guide"
    rows = ""
    lines = []
    for i, e in enumerate(events[:5], 1):
        name = H.escape(e.get("name", ""))
        url = H.escape(e.get("url", "#"), quote=True)
        venue = H.escape(e.get("venue", ""))
        when = H.escape(e.get("when", ""))
        rows += (f'<tr><td style="padding:8px 0;border-bottom:1px solid #E3E0DA">'
                 f'<span style="font-family:Georgia,serif;font-size:15px;color:{INK};font-weight:bold">{i}. {name}</span>'
                 f'<br><span style="font-family:Arial,sans-serif;font-size:12px;color:{MUTED}">{venue} · {when} · '
                 f'<a href="{url}" style="color:{GREEN}">details</a></span></td></tr>')
        lines.append(f"{i}. {e.get('name', '')} — {e.get('venue', '')} ({e.get('when', '')}) {e.get('url', '')}")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Weekend Guide</title></head>
<body style="margin:0;padding:0;background:{PAPER}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #E3E0DA">
<tr><td style="background:{DEEP};padding:18px 24px">
  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;letter-spacing:2px;color:{AMBER}">{H.escape(banner)}</p>
  <h1 style="margin:4px 0 0;font-family:Georgia,serif;font-size:24px;color:#ffffff">5 Things to Do This Weekend</h1>
  <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#C9E4D2">{H.escape(date_label)}</p>
</td></tr>
<tr><td style="padding:16px 24px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr>
<tr><td style="background:{PAPER};padding:14px 24px;border-top:2px solid {AMBER}">
  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;color:{MUTED}">Venue listings from each venue's own site; check before you go.</p>
</td></tr>
</table></td></tr></table></body></html>"""

    txt = f"{banner.upper()} — 5 THINGS TO DO THIS WEEKEND ({date_label})\n\n" + "\n".join(lines) + "\n"
    return html, txt


# ---------------------------------------------------------------- helpers
def _one_thing(escribe: dict, board: dict) -> str:
    """Plain-text 'most notable upcoming item' (same logic as the homepage)."""
    watched = escribe.get("watched", [])
    for w in watched:
        item = w.get("items") or []
        for it in item[:3]:
            title = (it.get("title") or "").strip()
            if title:
                return f"{title[:160]} — {w.get('name', 'a public meeting')} ({w.get('start_iso', '')[:10]}). Agenda on the official link."
    up = escribe.get("upcoming", [])
    if up:
        return f"{up[0].get('name', 'A public meeting')} on {up[0].get('start_iso', '')[:10]}. Agenda on the official link."
    if board.get("date"):
        return f"Kern County Board of Supervisors on {board['date']} — agenda at the county clerk's page."
    return "No items on the public calendar today."
