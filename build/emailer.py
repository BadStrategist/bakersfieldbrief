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
import re
from datetime import datetime

from . import common

GREEN = "#232B30"    # charcoal (brand ink)
DEEP = "#1A2126"
AMBER = "#DC9A1F"    # brand gold
RED = "#B3472F"      # brand red
INK = "#20262C"
PAPER = "#FAF6EC"    # brand cream
MUTED = "#57504A"
LINE = "#E4DCC8"     # cream-line border

BASE_URL = "https://bakersfieldbrief.com"


def _brief_sections(date) -> dict:
    """Extract the named sections from today's brief body (data/briefs/<date>.json).

    Returns {overnight, weather, top_stories, something_good, coming_up} —
    the markdown body of each '##' section, or '' when missing.
    """
    import json as _json
    from datetime import date as _date
    dstr = date.isoformat() if hasattr(date, "isoformat") else str(date)
    try:
        raw = _json.loads((common.ROOT / "data" / "briefs" / f"{dstr}.json").read_text(encoding="utf-8"))
        body = raw.get("body", "") if isinstance(raw, dict) else str(raw)
    except Exception:  # noqa: BLE001
        return {"overnight": "", "weather": "", "top_stories": "", "something_good": "", "coming_up": ""}
    import re as _re
    sections = {}
    # Split on '## ' headings (markdown)
    parts = re.split(r"\n## ", body)
    for part in parts:
        if not part.strip():
            continue
        first_line = part.splitlines()[0].strip().lower()
        content = "\n".join(part.splitlines()[1:]).strip()
        for key, names in {
            "overnight": ("the kern overnight", "kern overnight", "overnight"),
            "weather": ("today's weather", "today’s weather", "conditions"),
            "top_stories": ("top stories", "the news", "local headlines"),
            "something_good": ("something good", "something to look forward to"),
            "coming_up": ("coming up this week", "coming up", "what's coming up", "what’s coming up"),
        }.items():
            if first_line.startswith(names):
                sections[key] = content
                break
    return sections


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

    # ---- brief sections (full overnight, weather, something good)
    sections = _brief_sections(today)

    # Kern Overnight summary (feeds the title + a top block)
    ko = None
    try:
        from .builders.daily import _overnight_summary
        ko = _overnight_summary()
    except Exception:  # noqa: BLE001
        ko = None

    # Email-safe font stacks (Lora + Public Sans are the site brand fonts;
    # fall back to Georgia/Arial for clients that block web fonts).
    SERIF = "'Lora', Georgia, 'Times New Roman', serif"
    SANS = "'Public Sans', Arial, Helvetica, sans-serif"

    # ---- full overnight narrative (markdown -> paragraphs; no 'the log')
    def _md_para(text: str) -> str:
        """Convert a markdown body to email-safe <p> paragraphs (bold kept)."""
        import re as _re
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        return "".join(f'<p style="margin:6px 0 0;font-family:{SANS};font-size:13px;line-height:1.55;color:{INK}">{H.escape(p)}</p>' for p in paras)

    overnight_full = sections.get("overnight", "")
    # strip the "the log" portion if present (a '## The log' or 'The log:' tail)
    log_idx = overnight_full.lower().find("the log")
    if log_idx >= 0:
        overnight_full = overnight_full[:log_idx].strip()
    overnight_html = _md_para(overnight_full) if overnight_full else ""

    # ---- Today's Weather (bold the leading line, then the rest)
    weather_full = sections.get("weather", "")
    weather_html = ""
    if weather_full:
        wparas = [p.strip() for p in weather_full.split("\n\n") if p.strip()]
        first = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", wparas[0]) if wparas else ""
        rest = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", "\n\n".join(wparas[1:])) if len(wparas) > 1 else ""
        weather_html = (f'<p style="margin:0;font-family:{SERIF};font-size:15px;line-height:1.5;color:{INK}">{H.escape(first)}</p>'
                        + (f'<p style="margin:6px 0 0;font-family:{SANS};font-size:13px;line-height:1.55;color:{INK}">{H.escape(rest)}</p>' if rest else ""))

    # ---- Something Good
    good_full = sections.get("something_good", "")
    good_html = _md_para(good_full) if good_full else ""

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bakersfield Daily Brief — {H.escape(date_label)}{(' — Overnight: ' + H.escape(ko['headline'])) if ko and ko.get('headline') else ''}</title></head>
<body style="margin:0;padding:0;background:{PAPER}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid {LINE};border-radius:12px;overflow:hidden">

<!-- brand top bar -->
<tr><td style="background:{AMBER};height:6px;font-size:0;line-height:0">&nbsp;</td></tr>

<!-- masthead: derrick emblem + name (card style) -->
<tr><td style="background:{PAPER};padding:22px 24px 14px;text-align:center;border-bottom:1px solid {LINE}">
  <img src="{BASE_URL}/assets/img/emblem.png" width="180" alt="The Bakersfield Brief" style="display:block;margin:0 auto 8px;max-width:180px;height:auto;border:0">
  <p style="margin:6px 0 0;font-family:{SANS};font-size:11px;letter-spacing:3px;text-transform:uppercase;color:{RED}">{H.escape(date_label)}</p>
</td></tr>

<!-- Kern Overnight -->
<tr><td style="padding:18px 24px 6px">
  <p style="margin:0;font-family:{SANS};font-size:11px;letter-spacing:2px;text-transform:uppercase;color:{AMBER}">The Kern Overnight</p>
  <p style="margin:2px 0 0;font-family:{SANS};font-size:11px;color:{MUTED}">Scanner brief from 9pm to 6am</p>
  {('' if not (ko and ko.get('headline')) else f'<p style="margin:8px 0 2px;font-family:{SERIF};font-size:18px;color:{INK}"><a href="{BASE_URL}/overnight/" style="color:{INK};text-decoration:none">Overnight: {H.escape(ko["headline"])}</a></p>')}
  {('' if not ko else f'<p style="margin:2px 0 0;font-family:{SANS};font-size:12px;color:{MUTED}">{ko["count"]} incidents tracked overnight — <a href="{BASE_URL}/overnight/" style="color:{GREEN};font-weight:600;text-decoration:none">full report</a> · locations generalized</p>')}
  {overnight_html}
</td></tr>

<!-- Today's Weather -->
<tr><td style="padding:10px 24px 4px">
  <h2 style="margin:0 0 8px;font-family:{SERIF};font-size:17px;color:{GREEN}">Today&rsquo;s Weather</h2>
  {weather_html or '<p style="font-family:' + SANS + ';font-size:13px;color:' + MUTED + '">Weather data unavailable.</p>'}
</td></tr>

<!-- Something Good -->
{('' if not good_html else f'''
<tr><td style="padding:10px 24px 4px">
  <h2 style="margin:0 0 8px;font-family:{SERIF};font-size:17px;color:{GREEN}">Something Good</h2>
  {good_html}
</td></tr>''')}

<!-- Local Headlines -->
<tr><td style="padding:12px 24px 8px">
  <h2 style="margin:0 0 8px;font-family:{SERIF};font-size:17px;color:{GREEN}">Local Headlines</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{news_html}</table>
  <p style="font-family:{SANS};font-size:11px;color:{MUTED}">Headlines link to the original reporting. We never republish article text.</p>
</td></tr>

<!-- One Thing to Watch -->
<tr><td style="padding:4px 24px 12px">
  <h2 style="margin:0 0 8px;font-family:{SERIF};font-size:17px;color:{GREEN}">One Thing to Watch</h2>
  {watch_html}
</td></tr>

<!-- follow CTA -->
<tr><td style="padding:6px 24px 18px;text-align:center;border-top:1px solid {LINE}">
  <p style="margin:14px 0 10px;font-family:{SANS};font-size:12px;letter-spacing:1px;text-transform:uppercase;color:{MUTED}">Follow the Brief</p>
  <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto"><tr>
    <td style="padding:0 6px"><a href="https://www.facebook.com/bakersfieldbrief" style="display:inline-block;background:{GREEN};color:#ffffff;font-family:{SANS};font-size:13px;font-weight:600;text-decoration:none;padding:11px 22px;border-radius:6px">Follow on Facebook</a></td>
    <td style="padding:0 6px"><a href="https://www.instagram.com/bakersfieldbrief" style="display:inline-block;background:{RED};color:#ffffff;font-family:{SANS};font-size:13px;font-weight:600;text-decoration:none;padding:11px 22px;border-radius:6px">Follow on Instagram</a></td>
  </tr></table>
</td></tr>

<!-- footer: brand + unsubscribe (required elements so MailerLite appends nothing) -->
<tr><td style="background:{PAPER};padding:14px 24px;border-top:2px solid {AMBER}">
  <p style="margin:0;font-family:{SANS};font-size:11px;color:{MUTED}">The Bakersfield Brief &middot; Bakersfield, California &middot; <a href="{BASE_URL}/" style="color:{GREEN}">bakersfieldbrief.com</a></p>
  <p style="margin:4px 0 0;font-family:{SANS};font-size:10px;color:{MUTED}">You&rsquo;re receiving this because you subscribed to the Bakersfield Brief. <a href="{{$unsubscribe}}" style="color:{GREEN};text-decoration:underline">Unsubscribe</a> any time.</p>
</td></tr>

</table></td></tr></table>
</body></html>"""

    txt_doc = f"""THE BAKERSFIELD BRIEF — {date_label}
Bakersfield & Kern County

THE KERN OVERNIGHT
{('Overnight: ' + ko['headline'] + ' — ') if (ko and ko.get('headline')) else ''}{(str(ko['count']) + ' incidents tracked overnight — ') if ko else ''}full report: {BASE_URL}/overnight/ (locations generalized)

CONDITIONS
{chr(10).join(f"{k}: {v}" for k, v in conds)}

THE NEWS
{news_txt}
Headlines link to the original reporting at the outlets named.

ONE THING TO WATCH
{watch_txt}

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
