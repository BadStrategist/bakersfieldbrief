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
from datetime import datetime, timedelta

from . import common

# ---------------------------------------------------------------- palette
# Website guide-sign design system (matches assets/css/site.css)
SIGN = "#232B30"
SIGN_DEEP = "#1A2126"
SIGN_DARK = "#14191D"
AMBER = "#DC9A1F"
AMBER_SOFT = "#F3C76E"
RED = "#B3472F"
RED_DEEP = "#8F3720"
INK = "#20262C"
INK_SOFT = "#57504A"
PAPER = "#FAF6EC"
PAPER2 = "#F1EADA"
CARD = "#FFFDF7"
LINE = "#E3DBC8"
LINE_STRONG = "#C4BAA2"
SHADOW = "0 1px 2px rgba(32,38,28,.07), 0 8px 24px rgba(32,38,28,.06)"
# Email-safe font stacks (website brand fonts; fall back for clients that
# block web fonts). IBM Plex Mono isn't email-safe -> Courier New fallback.
SERIF = "'Lora', Georgia, 'Times New Roman', serif"
SANS = "'Public Sans', Arial, Helvetica, sans-serif"
DISPLAY = "'Barlow Condensed', 'Arial Narrow', Arial, sans-serif"
MONO = "'Courier New', Courier, monospace"

GREEN = SIGN          # legacy alias (weekend guide)
DEEP = SIGN_DEEP      # legacy alias (weekend guide)
MUTED = INK_SOFT      # legacy alias (weekend guide)

BASE_URL = "https://bakersfieldbrief.com"


def _kicker(text: str) -> str:
    """Uppercase display-font kicker with amber rule (site style)."""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 6px"><tr>'
            f'<td style="width:26px;border-top:2px solid {AMBER};font-size:1px;line-height:1px">&nbsp;</td>'
            f'<td style="padding-left:8px;font-family:{DISPLAY};font-size:14px;font-weight:600;'
            f'letter-spacing:2px;text-transform:uppercase;color:{RED}">{H.escape(text)}</td></tr></table>')


def _card_open(accent: str = SIGN) -> str:
    """Site .card: cream card, left accent border, radius, soft shadow."""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:14px 0;background:{CARD};border:1px solid {LINE};'
            f'border-left:4px solid {accent};border-radius:6px;box-shadow:{SHADOW}"><tr><td style="padding:14px 16px">')


def _card_close() -> str:
    return "</td></tr></table>"


# ------------------------------------------------- the overnight card (home band)
def _overnight_card(chp: dict) -> tuple[str, str]:
    """The home page's overnight band as an email-safe card, plus its plain-text twin.

    Same rows, same labels, same order as the home band and /overnight/, because all three
    read night_counts.MAP. No published report, or no call file for it, means no card:
    a count is never invented here. The CHP line shows only when its own reading is of the
    same morning as the report.
    """
    try:
        from .builders import night_counts, overnight
    except Exception as e:  # noqa: BLE001
        common.log(f"overnight card skipped: {type(e).__name__}: {e}")
        return "", ""
    reps = overnight._published_reports()
    if not reps:
        common.log("overnight card skipped: no published report")
        return "", ""
    rep = reps[0]
    incs = overnight._incidents(rep["date"])
    if not incs:
        common.log(f"overnight card skipped: no call file for {rep['date']}")
        return "", ""
    rows, inside, _unmapped = night_counts.chips(incs)
    night = datetime.fromisoformat(rep["date"])
    eve = night - timedelta(days=1)
    when = (f"7 PM {eve.strftime('%A')} to 7 AM {night.strftime('%A')}, "
            f"{night.strftime('%b')} {night.day}")
    say = "call while Kern slept" if len(incs) == 1 else "calls while Kern slept"

    chp_line = ""
    if (chp or {}).get("ok") and str(chp.get("asof", ""))[:10] == rep["date"]:
        cn = len(chp.get("overnight", []) or [])
        logged = ("no road incidents" if cn == 0 else
                  "1 road incident" if cn == 1 else f"{cn} road incidents")
        chp_line = (f'<p style="margin:8px 0 0;font-family:{SANS};font-size:11px;line-height:1.5;'
                    f'color:{INK_SOFT}">A separate count from a different source: CHP logged '
                    f'{logged} overnight (Caltrans QuickMap). Some can be the same events as the '
                    f'calls above.</p>')

    trs = "".join(
        f'<tr><td style="padding:7px 0 7px;border-top:1px solid {LINE};width:42px;'
        f'font-family:{SERIF};font-size:16px;font-weight:700;color:{INK};vertical-align:top">{n}</td>'
        f'<td style="padding:7px 0 7px;border-top:1px solid {LINE};font-family:{SANS};font-size:13px;'
        f'line-height:1.4;color:{INK};vertical-align:top">{H.escape(label)}'
        + (f'<br><span style="font-size:11px;color:{INK_SOFT}">{H.escape(inside)}</span>'
           if label == night_counts.OTHER else "")
        + "</td></tr>"
        for label, n in rows)

    html_card = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:12px 0 4px;background:{PAPER2};border:1px solid {LINE};border-radius:6px">'
        f'<tr><td style="padding:12px 14px 2px">'
        f'<p style="margin:0;font-family:{SERIF};font-size:28px;line-height:1.15;color:{INK}">'
        f'<strong>{len(incs)}</strong>'
        f'<span style="font-family:{SANS};font-size:14px;color:{INK_SOFT}"> {say}</span></p>'
        f'<p style="margin:3px 0 0;font-family:{MONO};font-size:11px;color:{INK_SOFT}">'
        f'{H.escape(when)}</p>'
        f'<p style="margin:12px 0 0;font-family:{DISPLAY};font-size:11px;font-weight:600;'
        f'letter-spacing:2px;text-transform:uppercase;color:{RED}">Calls by type, most serious first</p>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:4px 0 0">{trs}</table>'
        f'{chp_line}'
        f'<p style="margin:12px 0 10px"><a href="{BASE_URL}/overnight/" '
        f'style="display:inline-block;background:{RED};color:#ffffff;font-family:{DISPLAY};'
        f'font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;'
        f'text-decoration:none;padding:8px 16px;border-radius:4px">Read the full overnight log</a></p>'
        f'</td></tr></table>')

    txt_rows = "\n".join(f"  {n} {label}" for label, n in rows)
    txt_card = (f"{len(incs)} {say} ({when})\n{txt_rows}"
                + (f"\n  other calls: {inside}" if inside else ""))
    return html_card, txt_card


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


# ----------------------------------------------------------------- keyless prose
def _read_overnight_report(today) -> str:
    """The published Kern Overnight report markdown (real narrative), '' if none."""
    iso = today.isoformat() if hasattr(today, "isoformat") else str(today)
    p = common.DATA / "overnight_reports" / f"{iso}.md"
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:  # noqa: BLE001
        return ""


def _read_incidents(today) -> list:
    """Today's incident list from incidents/<iso>.json (real extracted data).

    The published report markdown can be missing on a day the overnight
    pipeline partially failed (cron/LLM outage), while the incident data that
    WAS extracted still exists on disk. The email must degrade to a real
    narrative built from these incidents, not to a stale stub.
    """
    import json as _json
    iso = today.isoformat() if hasattr(today, "isoformat") else str(today)
    p = common.ROOT / "incidents" / f"{iso}.json"
    try:
        if not p.exists():
            return []
        data = _json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _incidents_narrative(incs: list) -> str:
    """A real multi-sentence overnight narrative built from today's incidents.

    Reuses the incident summaries already extracted from the overnight
    transcript (type, area, notability, summary), so the degraded email is
    genuinely informative — never a stub. Always yields >= 2 sentences carrying
    a real number (incident count), which also satisfies the content gate's
    'real but short' check.
    """
    from collections import Counter
    if not incs:
        return ""
    try:
        from .builders.daily import _type_label
    except Exception:  # noqa: BLE001
        _type_label = lambda t: str(t or "incident").replace("_", " ")
    n = len(incs)
    by_type = Counter(_type_label(i.get("type", "incident")) for i in incs)
    kinds = ", ".join(
        f"{c} {t}" if c > 1 else f"a {t}"
        for t, c in by_type.most_common(3)
    )
    sents = [f"Crews and officers handled {kinds} overnight across Bakersfield "
             f"and Kern County — {n} incidents in all."]
    top = sorted(incs, key=lambda i: i.get("notability", 0), reverse=True)[:3]
    for i in top:
        s = (i.get("summary") or "").strip()
        if s:
            sents.append(s)
    body = " ".join(s for s in sents if s).strip()
    return body.rstrip(".") + "." if body else ""


def _keyless_overnight(today, ko) -> str:
    """Deterministic overnight narrative: use REAL data for TODAY.

    Priority:
      1. today's published report prose (strip headings/log);
      2. a real multi-sentence narrative built from today's incidents
         (incidents/<iso>.json) when the report markdown is missing but the
         extracted incident data exists;
      3. '' — genuinely nothing for today, which the content gate MUST block.

    Deliberately does NOT fall back to ko (the latest published report summary):
    when today's report is missing, ko is the PREVIOUS day's data, and shipping
    it as today's "overnight" would silently mislabel yesterday as today.
    """
    md = _read_overnight_report(today)
    if md:
        lines = []
        for ln in md.splitlines():
            s = ln.strip()
            if not s:
                lines.append("")
                continue
            if s.startswith("#"):          # drop #/## headings
                continue
            if s.startswith("- "):         # drop the bullet 'log' lines
                continue
            lines.append(s)
        body = "\n\n".join(l.strip() for l in lines if l.strip())
        if len(body) >= 150 and body.count(". ") >= 3:
            return body
    incs = _read_incidents(today)
    if incs:
        return _incidents_narrative(incs)
    return ""


def _ko_effective(ko, today) -> dict | None:
    """Today-accurate Kern Overnight summary for the email header/count.

    _overnight_summary() reads the PUBLISHED reports; when today's report is
    missing (cron/LLM outage) that resolves to YESTERDAY's data. When today's
    incidents exist, rebuild the headline/count from them so the email's
    header, count line, and narrative are all consistent and current instead of
    a stale prior day. Passes ko through unchanged on a normal day (when
    today's report is present, ko is already today-accurate).
    """
    iso = today.isoformat() if hasattr(today, "isoformat") else str(today)
    if ko and ko.get("date") == iso:
        return ko
    incs = _read_incidents(today)
    if not incs:
        return ko
    try:
        from .builders.daily import _short_area, _type_label
    except Exception:  # noqa: BLE001
        return ko
    top = max(incs, key=lambda i: i.get("notability", 0))
    label = _type_label(top.get("type", "incident"))
    area = _short_area(top.get("area", ""))
    headline = f"{label} at {area}" if area and area != "the area" else label
    return {**(ko or {}), "headline": headline, "count": len(incs),
            "date": iso, "incs": incs, "title": f"The Kern Overnight — {iso}"}


def _keyless_weather(weather, airnow, calfire) -> str:
    """Deterministic weather prose from the live forecast/alerts/AQI/fires."""
    fc = (weather or {}).get("forecast", {}) or {}
    hi, lo, cur = fc.get("high"), fc.get("low"), fc.get("current")
    parts = []
    hi_txt = f"a high near {hi}°" if hi is not None else "a mild day"
    lo_txt = f" and a low around {lo}° tonight" if lo is not None else ""
    parts.append(f"Expect {hi_txt}{lo_txt}.")
    if cur is not None:
        parts.append(f"It is currently {cur}° at Meadows Field (KBFL).")
    alerts = (weather or {}).get("alerts", [])
    if alerts:
        a = alerts[0]
        parts.append(f"**{a.get('event', 'Weather alert')}**: "
                     f"{(a.get('headline') or '')[:180]}")
    elif (weather or {}).get("ok"):
        parts.append("No active weather alerts for Kern County.")
    else:
        parts.append("Weather alerts could not be checked for this edition.")
    if airnow and airnow.get("ok") and airnow.get("aqi") is not None:
        parts.append(f"Air quality is {airnow['aqi']} — "
                     f"{(airnow.get('category') or 'moderate').lower()}.")
    kern = [f for f in (calfire or {}).get("incidents", []) if "Kern" in str(f.get("county", ""))]
    if kern:
        names = ", ".join(f.get("name", "a fire") for f in kern)
        parts.append(f"Fire crews are on {len(kern)} active "
                     f"{'fire' if len(kern) == 1 else 'fires'} in Kern ({names}).")
    return " ".join(parts)


def _keyless_good(headlines, events, today) -> str:
    """Deterministic 'something good': a real dated family event or a positive
    headline, else the quiet-honest fallback. Mirror of the site's pick logic."""
    # 1) a real dated family-friendly event in the next 7 days
    try:
        from .builders.daily import _family_event
        fam = _family_event(events or [], today)
        if fam:
            d, e = fam
            name = e.get("name", "A local event")
            venue = e.get("venue") or "a local venue"
            when = d.strftime("%a, %b %d") if hasattr(d, "strftime") else ""
            return (f"A bright spot this week: **{name}** "
                    f"at {venue}" + (f" on {when}." if when else "."))
    except Exception:  # noqa: BLE001
        pass
    # 2) a positive headline (real uplift)
    for h in (headlines or []):
        t = (h.get("title") or "").lower()
        if any(k in t for k in ("grand opening", "scholarship", "fundraiser",
                                "donation", "volunteer", "festival", "celebrat",
                                "anniversary", "museum", "award", "family")):
            return (f"**{h.get('title', '')}** — "
                    f"from {h.get('source', 'local news')}. Good news worth a smile.")
    return ""


def _fill_keyless_prose(sections, sources, today, ko) -> None:
    """Fill empty prose sections in-place from deterministic real data.

    Called only when the LLM brief body is absent/partial (see render_brief).
    Only overwrites keys that are empty — never downgrades LLM prose that exists.
    """
    if not (sections.get("overnight") or "").strip():
        sections["overnight"] = _keyless_overnight(today, ko)
    if not (sections.get("weather") or "").strip():
        weather = sources.get("weather", {})
        airnow = sources.get("airnow", {})
        calfire = sources.get("calfire", {})
        sections["weather"] = _keyless_weather(weather, airnow, calfire)
    if not (sections.get("something_good") or "").strip():
        headlines = (sources.get("news_rss") or {}).get("headlines", [])
        events = (sources.get("venues") or {}).get("events", [])
        sections["something_good"] = _keyless_good(headlines, events, today)


# ---------------------------------------------------------------- brief
_LOG_HEAD_RE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*|\*\*[ \t]*)?the log\b", re.I | re.M)


def strip_log_section(text: str) -> str:
    """Drop a trailing 'log' SECTION from a narrative — never prose.

    The marker MUST sit at a line start (optionally behind markdown heading
    markers). A plain substring search for "the log" also matches ordinary
    prose such as "...at the time.\\n\\nThe rest of the log leaned on
    disturbances..." — which silently truncated the overnight narrative
    mid-sentence in the 2026-09-11 email ("...moving at the time. The rest of")
    and shipped it to every subscriber.
    """
    text = text or ""
    m = _LOG_HEAD_RE.search(text)
    return text[:m.start()].strip() if m else text


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
    # labelled: "88° / 88°" read as high / low when it was current / high
    weather_v = (f"{cur}° now, high {hi}°" if cur is not None and hi is not None
                 else (f"high {hi}°" if hi is not None else "n/a"))
    alerts = (weather or {}).get("alerts", [])
    alert_v = (f"{alerts[0]['event']} active" if alerts else
               "No active alerts" if (weather or {}).get("ok") else "Unavailable")
    isa_last = isa.get("last")
    isa_v = f"{isa_last['value']:,} acre-feet ({isa.get('pct')}% full)" if isa_last else "n/a"
    chp_night = chp.get("overnight", [])
    chp_v = ("Unavailable" if not chp.get("ok") else
             f"{len(chp_night)} overnight" if chp_night else "None overnight")
    if airnow.get("ok") and airnow.get("aqi") is not None:
        aqi_v = f"AQI {airnow['aqi']} · {airnow.get('category')}"
    elif airnow.get("needs_key"):
        aqi_v = "AQI awaiting key"
    else:
        aqi_v = "AQI unavailable"
    kern_fires = [f for f in calfire.get("incidents", []) if "Kern" in str(f.get("county", ""))]
    fire_v = (f"{len(kern_fires)} active in Kern" if kern_fires else
              "0 active in Kern" if calfire.get("ok") else "Unavailable")

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
        news_html += (f'<tr><td style="padding:7px 0;border-bottom:1px solid {LINE}">'
                      f'<a href="{url}" style="color:{SIGN};font-weight:600;text-decoration:none">{title}</a>'
                      f'<br><span style="font-size:11px;color:{INK_SOFT}">{src}</span></td></tr>')
        news_txt += f"• {h.get('title', '')} ({h.get('source', '')}) — {h.get('url', '')}\n"

    # ---- One Thing to Watch (Flock camera tracker update when available)
    alpr = sources.get("alpr") or {}
    flock_html = _flock_update_html(alpr)
    if flock_html and alpr.get("ok"):
        # Regenerate the tracker card image from today's live camera data so
        # the embedded image (a live URL) is always fresh — never a stale
        # committed JPEG. Fail-closed: if the redraw throws, drop the card so
        # the send gate blocks rather than ship an outdated image.
        try:
            from .tracker_card import render_tracker_card
            render_tracker_card(alpr, None)
        except Exception as e:  # noqa: BLE001
            common.log(f"tracker card redraw failed — dropping flock card: {e}")
            flock_html = ""
    if flock_html:
        watch_html = flock_html
        # The txt email prints its own heading. When the Flock card replaces the
        # watch item, watch_txt is "" — the old template still emitted
        # "ONE THING TO WATCH" with nothing under it (an empty section in every
        # text part). Emit the block only when it actually has content.
        watch_txt = ""
        watch_block = ""
    else:
        watch = _one_thing(escribe, board)
        watch_html = f'<p style="font-family:Georgia,serif;font-size:15px;line-height:1.5;color:{INK}">{watch}</p>'
        watch_txt = watch
        watch_block = f"ONE THING TO WATCH\n{watch}\n\n"

    # ---- brief sections (full overnight, weather, something good)
    sections = _brief_sections(today)

    # Kern Overnight summary (feeds the title + a top block). On a day the
    # report is missing, _overnight_summary() returns the LATEST published
    # report (yesterday) — rebuild a today-accurate ko from today's incidents
    # so header/count/narrative stay consistent and current.
    ko = None
    try:
        from .builders.daily import _overnight_summary
        ko = _overnight_summary()
    except Exception:  # noqa: BLE001
        ko = None
    ko = _ko_effective(ko, today)

    # ---- resilience: an LLM outage must degrade prose QUALITY, never section
    # PRESENCE. The brief body (data/briefs/<today>.json) is written by a single
    # LLM call; when that call fails (timeout, 5xx, no key) the file is never
    # written and _brief_sections returns empty prose for overnight/weather/
    # something-good — which used to blank the email and trip the send gate
    # (2026-09-05). Fill each empty prose section from real deterministic data
    # (the published overnight report, the live forecast, real headlines/events)
    # so the email always ships with genuine content. Deterministic < LLM prose,
    # but a factual no-LLM email beats no email. The card-style sections (weather
    # graphic, Flock tracker, headline links) already survive LLM death.
    if not (sections.get("overnight") or "").strip() or \
       not (sections.get("weather") or "").strip() or \
       not (sections.get("something_good") or "").strip():
        _fill_keyless_prose(sections, sources, today, ko)

    # ---- full overnight narrative (markdown -> paragraphs; no 'the log')
    def _md_para(text: str) -> str:
        """Convert a markdown body to email-safe <p> paragraphs (bold kept).

        Order matters: HTML-escape FIRST, then convert **bold** markers to
        <strong> — otherwise the injected <strong> tags get escaped too.
        """
        text = H.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        return "".join(f'<p style="margin:6px 0 0;font-family:{SANS};font-size:13px;line-height:1.55;color:{INK}">{p}</p>' for p in paras)

    def _chunk_paragraphs(text: str, sentences_per_para: int = 3) -> str:
        """Split a long narrative into readable paragraphs at sentence ends."""
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])", text)
        sentences = [p.strip() for p in parts if p.strip()]
        paras = []
        for i in range(0, len(sentences), sentences_per_para):
            paras.append(" ".join(sentences[i:i + sentences_per_para]))
        return "\n\n".join(paras)

    overnight_full = strip_log_section(sections.get("overnight", ""))
    overnight_html = _md_para(_chunk_paragraphs(overnight_full)) if overnight_full else ""

    # ---- the home page's overnight card: the counts by type, same rows as the home
    # band and /overnight/. It sits above the narrative so the numbers land first.
    overnight_card, overnight_txt = _overnight_card(chp)

    # ---- Today's Weather (bold the leading line, then the rest)
    weather_full = sections.get("weather", "")
    weather_html = ""
    if weather_full:
        wparas = [p.strip() for p in weather_full.split("\n\n") if p.strip()]
        def _bold(text: str) -> str:
            text = H.escape(text)
            return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        first = _bold(wparas[0]) if wparas else ""
        rest = _bold("\n\n".join(wparas[1:])) if len(wparas) > 1 else ""
        weather_html = (f'<p style="margin:0;font-family:{SERIF};font-size:15px;line-height:1.5;color:{INK}">{first}</p>'
                        + (f'<p style="margin:6px 0 0;font-family:{SANS};font-size:13px;line-height:1.55;color:{INK}">{rest}</p>' if rest else ""))

    # ---- Today's Weather graphic card (baked PNG, refreshed every build).
    # Regenerate from live NWS + AirNow data so the embedded image (a live URL)
    # is never stale. Fail-closed: if the redraw throws OR there is no real
    # temperature reading, drop the image so the send gate blocks rather than
    # ship a degraded/placeholder card.
    weather_img = ""
    _fc = (weather or {}).get("forecast", {}) or {}
    _air = (weather.get("airnow") or {}) or (airnow or {})
    if _fc.get("current") is not None or _fc.get("high") is not None:
        try:
            from .weather_card import render_weather_card
            _alerts = [(a.get("event") or "") for a in (weather.get("alerts") or []) if a.get("event")]
            render_weather_card({
                "current": _fc.get("current"), "high": _fc.get("high"),
                "low": _fc.get("low"), "condition": _fc.get("condition"),
                "wind_mph": _fc.get("wind_mph"), "wind_dir": _fc.get("wind_dir"),
                "humidity": _fc.get("humidity"),
                "aqi": _air.get("aqi"), "aqi_category": _air.get("category"),
                "alerts": _alerts, "observed": _fc.get("observed"),
                "day_label": date_label,
            }, None)
            weather_img = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                           f'style="margin:8px 0 12px;border:1px solid {LINE};border-radius:6px;overflow:hidden">'
                           f'<tr><td>'
                           f'<img src="{BASE_URL}/assets/img/weather-card.jpg" width="100%" '
                           f'alt="Today\'s weather for Bakersfield &amp; Kern County" '
                           f'style="display:block;width:100%;height:auto;border:0">'
                           f'</td></tr></table>')
        except Exception as e:  # noqa: BLE001
            common.log(f"weather card redraw failed — dropping weather graphic: {e}")
            weather_img = ""

    # ---- Something Good
    good_full = sections.get("something_good", "")
    good_html = _md_para(good_full) if good_full else ""

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bakersfield Daily Brief — {H.escape(date_label)}{(' — Overnight: ' + H.escape(ko['headline'])) if ko and ko.get('headline') else ''}</title></head>
<body style="margin:0;padding:0;background:{PAPER}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:{PAPER}">

<!-- brand top bar (guide-sign amber) -->
<tr><td style="background:{AMBER};height:6px;font-size:0;line-height:0">&nbsp;</td></tr>

<!-- masthead: derrick emblem + name (card style) -->
<tr><td style="background:{PAPER};padding:24px 24px 10px;text-align:center">
  <img src="{BASE_URL}/assets/img/emblem.png" width="190" alt="Bakersfield Daily Brief" style="display:block;margin:0 auto 10px;max-width:190px;height:auto;border:0">
  <p style="margin:6px 0 0;font-family:{DISPLAY};font-size:13px;letter-spacing:3px;text-transform:uppercase;color:{RED}">{H.escape(date_label)}</p>
</td></tr>

<!-- Kern Overnight card -->
<tr><td style="padding:6px 20px 2px">
  {_card_open(SIGN)}
    {_kicker("The Kern Overnight")}
    <p style="margin:0 0 4px;font-family:{MONO};font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{INK_SOFT}">Logged 7pm to 7am by the countywide radio feed</p>
    {('' if not (ko and ko.get('headline')) else f'<p style="margin:8px 0 2px;font-family:{SERIF};font-size:18px;color:{INK}"><a href="{BASE_URL}/overnight/" style="color:{INK};text-decoration:none">What happened overnight: {H.escape(ko["headline"])}</a></p>')}
    {('' if not ko else f'<p style="margin:2px 0 10px;font-family:{SANS};font-size:12px;color:{INK_SOFT}">{ko["count"]} incidents tracked overnight · locations generalized &nbsp;'
     f'<a href="{BASE_URL}/overnight/" style="display:inline-block;background:{RED};color:#ffffff;'
     f'font-family:{DISPLAY};font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;'
     f'text-decoration:none;padding:6px 14px;border-radius:4px">Full Report</a></p>')}
    {overnight_card}
    {overnight_html}
  {_card_close()}
</td></tr>

<!-- Today's Weather card -->
<tr><td style="padding:2px 20px">
  {_card_open(AMBER)}
    {_kicker("Today's Weather")}
    {weather_img}
    {weather_html or '<p style="font-family:' + SANS + ';font-size:13px;color:' + INK_SOFT + '">Weather data unavailable.</p>'}
  {_card_close()}
</td></tr>

<!-- Something Good card -->
{('' if not good_html else f'''
<tr><td style="padding:2px 20px">
  {_card_open(RED)}
    {_kicker("Something Good")}
    {good_html}
  {_card_close()}
</td></tr>''')}

<!-- Local Headlines card -->
<tr><td style="padding:2px 20px">
  {_card_open(SIGN)}
    {_kicker("Local Headlines")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{news_html}</table>
    <p style="font-family:{SANS};font-size:11px;color:{INK_SOFT}">Headlines link to the original reporting. We never republish article text.</p>
  {_card_close()}
</td></tr>

<!-- One Thing to Watch card -->
<tr><td style="padding:2px 20px">
  {_card_open(SIGN_DARK)}
    {_kicker("Flock & ALPR Tracker" if flock_html else "One Thing to Watch")}
    {watch_html}
  {_card_close()}
</td></tr>

<!-- follow CTA -->
<tr><td style="padding:14px 20px 18px;text-align:center">
  <p style="margin:0 0 12px;font-family:{DISPLAY};font-size:14px;letter-spacing:2px;text-transform:uppercase;color:{INK_SOFT}">Follow the Brief</p>
  <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto"><tr>
    <td style="padding:0 6px"><a href="https://www.facebook.com/bakersfieldbrief" style="display:inline-block;background:{SIGN};color:#ffffff;font-family:{DISPLAY};font-size:14px;font-weight:600;letter-spacing:1px;text-transform:uppercase;text-decoration:none;padding:12px 24px;border-radius:6px;box-shadow:{SHADOW}">Follow on Facebook</a></td>
    <td style="padding:0 6px"><a href="https://www.instagram.com/bakersfieldbrief" style="display:inline-block;background:{RED};color:#ffffff;font-family:{DISPLAY};font-size:14px;font-weight:600;letter-spacing:1px;text-transform:uppercase;text-decoration:none;padding:12px 24px;border-radius:6px;box-shadow:{SHADOW}">Follow on Instagram</a></td>
  </tr></table>
</td></tr>

<!-- footer: brand + unsubscribe (required elements so MailerLite appends nothing) -->
<tr><td style="background:{PAPER2};padding:14px 24px;border-top:2px solid {AMBER}">
  <p style="margin:0;font-family:{SANS};font-size:11px;color:{INK_SOFT}">Bakersfield Daily Brief &middot; Bakersfield, California &middot; <a href="{BASE_URL}/" style="color:{SIGN}">bakersfieldbrief.com</a></p>
  <p style="margin:4px 0 0;font-family:{SANS};font-size:10px;color:{INK_SOFT}">You&rsquo;re receiving this because you subscribed to the Bakersfield Brief. <a href="{{$unsubscribe}}" style="color:{SIGN};text-decoration:underline">Unsubscribe</a> any time.</p>
</td></tr>

</table></td></tr></table>
</body></html>"""

    txt_doc = f"""THE BAKERSFIELD BRIEF — {date_label}
Bakersfield & Kern County

THE KERN OVERNIGHT
{('What happened overnight: ' + ko['headline'] + ' — ') if (ko and ko.get('headline')) else ''}{(str(ko['count']) + ' incidents tracked overnight — ') if ko else ''}full report: {BASE_URL}/overnight/ (locations generalized)
{overnight_txt}

CONDITIONS
{chr(10).join(f"{k}: {v}" for k, v in conds)}

THE NEWS
{news_txt}
Headlines link to the original reporting at the outlets named.

{watch_block}Web: {BASE_URL}/
"""

    out_dir = common.ROOT / "email" / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = common.ROOT / "email" / "latest"
    latest.mkdir(parents=True, exist_ok=True)

    # Subject line: lead with the day's top story so the inbox preview says
    # what the email is about at a glance. Falls back to the plain date.
    ko_head = (ko or {}).get("headline") or ""
    if ko_head:
        subject = f"Bakersfield Daily Brief — {ko_head} — {date_label}"
    else:
        subject = f"Bakersfield Daily Brief — {date_label}"
    for name, content in (("brief.html", html_doc), ("brief.txt", txt_doc),
                          ("subject.txt", subject + "\n")):
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


def _flock_update_html(alpr: dict) -> str:
    """Flock/ALPR tracker update card for the email.

    Uses the same source_cache 'alpr' payload the surveillance page uses.
    New-camera counts are DYNAMIC: computed from each camera's OSM 'mapped'
    date against today, so the email's number changes day to day instead of
    repeating '5 new this week' — if nothing was mapped today it reports the
    7-day window, and if that's also empty it says so and points to the map.
    """
    from datetime import date as _date
    if not (alpr and alpr.get("ok")):
        return ""
    stats = alpr.get("stats") or {}
    cameras = alpr.get("cameras") or []
    dated = [c for c in cameras if c.get("mapped")]
    dated.sort(key=lambda c: c["mapped"], reverse=True)
    newest = dated[0] if dated else None
    if not newest:
        return ""
    total = stats.get("total", len(cameras))
    flock = stats.get("flock", 0)
    nmap = newest.get("mapped", "")
    ndir = newest.get("direction", "")
    # human-facing direction (compass bearing -> cardinal)
    try:
        deg = int(float(ndir)) % 360
        cardinal = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]
    except (TypeError, ValueError):
        cardinal = ndir or ""
    dir_txt = f", facing {cardinal}" if cardinal else ""

    # ---- dynamic new-camera counts (changes day to day) ----
    # One clock for the whole pipeline: common.iso_today() (Pacific), the same
    # clock alpr.py counts 'mapped' dates against. _date.today() is the RUNNER's
    # local date (UTC in CI), which rolls over ~7 hours before Pacific, so after
    # 5pm PT the two clocks disagree and this sentence dropped the "today" part.
    today = common.iso_today()
    from datetime import timedelta as _td
    week_ago = (_date.fromisoformat(today) - _td(days=7)).isoformat()
    new_today = sum(1 for c in cameras if c.get("mapped") == today)
    # The 7-day total comes from the source payload (stats['new_this_week']) so
    # this sentence and the tracker card's "+N NEW THIS WEEK" badge are the same
    # number by construction. They used to diverge: the badge read the weekly
    # snapshot diff, which reads 0 for every build after the Monday snapshot
    # advance (badge "+0" next to "5 new cameras mapped this week", 2026-09-14).
    week_total = stats.get("new_this_week")
    if week_total is None:            # older cached payload
        week_total = new_today + sum(1 for c in cameras
                                     if week_ago <= (c.get("mapped") or "") < today)
    new_week = max(0, int(week_total) - new_today)
    new_total = new_today + new_week
    if new_today:
        added_txt = (f"<strong>{new_today} new camera{'s' if new_today != 1 else ''} mapped today</strong>"
                     + (f" — {new_week} more this week" if new_week else ""))
    elif new_week:
        added_txt = f"<strong>{new_week} new camera{'s' if new_week != 1 else ''} mapped this week</strong>"
    else:
        added_txt = ("No new cameras mapped in the last 7 days — "
                     "the tracker refreshes from OpenStreetMap every Monday.")

    tracker = f"{BASE_URL}/surveillance/"
    asof = alpr.get("asof", "")
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="margin:8px 0 4px;border:1px solid {LINE};border-radius:6px;overflow:hidden">
  <tr><td>
    <a href="{tracker}" style="display:block;text-decoration:none">
      <img src="{BASE_URL}/assets/img/tracker-map-card.jpg" width="100%" alt="Live Flock &amp; ALPR camera map for Kern County"
           style="display:block;width:100%;height:auto;border:0">
    </a>
  </td></tr>
  <tr><td style="padding:12px 14px">
    <p style="margin:0 0 6px;font-family:{SANS};font-size:13px;line-height:1.55;color:{INK}">
      {added_txt}. <strong>{flock}</strong> of <strong>{total}</strong> ALPR cameras in Kern County are Flock Safety units;
      the newest was mapped <strong>{H.escape(nmap)}</strong>{H.escape(dir_txt)}.</p>
    <p style="margin:0 0 8px;font-family:{MONO};font-size:11px;color:{INK_SOFT}">
      Data as of {H.escape(asof)} · refreshed from OpenStreetMap each build.</p>
    <p style="margin:0;font-family:{SANS};font-size:12px;color:{INK_SOFT}">
      <a href="{tracker}" style="display:inline-block;background:{SIGN};color:#ffffff;font-family:{DISPLAY};font-size:12px;
      font-weight:600;letter-spacing:1px;text-transform:uppercase;text-decoration:none;padding:6px 14px;border-radius:4px">
      View the Live Camera Tracker</a></p>
  </td></tr>
</table>"""
