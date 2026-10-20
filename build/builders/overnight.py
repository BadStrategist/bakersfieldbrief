#!/usr/bin/env python3
"""The Kern Overnight page + archive (/overnight/, /overnight/archive/).

Renders PUBLISHED reports dropped into data/overnight_reports/. The main page
shows the two newest reports in full, with the how-it-works / privacy
explainers at the BOTTOM; every report ever published is on the archive page
so trends and monthly summaries can be built from it.
"""
from __future__ import annotations

import html
import re
from datetime import date as _date
from pathlib import Path

from .. import common
from . import night_counts
from . import page as page_mod

REPORTS_DIR = Path(common.DATA) / "overnight_reports"

# Deterministic English day/month names (no locale or platform strftime surprises).
_DOW = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTH = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


# ---------------------------------------------------------------- markdown-lite
def _md(text: str) -> str:
    """Minimal markdown → HTML for the briefs (headings, bold, italics, lists, paras)."""
    out = []
    in_list = False

    def _inline(s: str) -> str:
        esc = html.escape(s)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc)
        return esc

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if line.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            # Report title → h2, NOT h1: the page keeps exactly one real H1
            # ("What Happened Overnight in Bakersfield") for the target query.
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_inline(line[2:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            # Incident lead → real <h3> heading so Google sees each incident
            # headline as crawlable heading content (matches long-tail
            # searches like "tractor trailer fire bakersfield"). The lead is
            # "**Headline.** rest of paragraph…". The chronological log
            # entries start with "**HH:MM** —" — keep those as body text, not
            # headings, or the log would produce a dozen headings.
            # the lead can end "**Headline.**" or "**Headline**:"; drop either separator
            m = re.match(r"\*\*(.+?)\*\*[.:]?\s*(.*)", line)
            if m and not re.match(r"^\d{1,2}:\d{2}", m.group(1)):
                lead, rest = m.group(1), m.group(2)
                out.append(f"<h3>{_inline(lead)}</h3>")
                if rest:
                    out.append(f"<p>{_inline(rest)}</p>")
            else:
                out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _published_reports() -> list[dict]:
    if not REPORTS_DIR.exists():
        return []
    out = []
    for p in sorted(REPORTS_DIR.glob("*.md"), reverse=True):
        text = p.read_text(encoding="utf-8")
        m = re.match(r"#\s+(.+)", text)
        out.append({"date": p.stem, "title": m.group(1).strip() if m else p.stem,
                    "path": p, "body": _md(text)})
    return out


def latest_teaser() -> str | None:
    """One-line teaser for the homepage section, or None when nothing is published."""
    reps = _published_reports()
    if not reps:
        return None
    r = reps[0]
    return (f'<a href="../overnight/#{r["date"]}">{html.escape(r["title"])}</a> '
            f'<span class="note">({r["date"]})</span>')


def _day_banner(date_iso: str, tag: str | None = None, prev: bool = False) -> str:
    """Prominent day header for one report: weekday, full date, optional age tag.

    tag ("Today"/"Yesterday") is only passed on the two newest reports; the
    archive passes nothing so it never claims a stale report is current.
    """
    try:
        d = _date.fromisoformat(date_iso)
    except ValueError:
        return ""
    tag_html = ""
    if tag:
        cls = "ko-day-tag is-prev" if prev else "ko-day-tag"
        tag_html = f'<span class="{cls}">{html.escape(tag)}</span>'
    return (f'<div class="ko-day"><div>'
            f'<p class="ko-day-dow">{_DOW[d.weekday()]}</p>'
            f'<p class="ko-day-date">{_MONTH[d.month - 1]} {d.day}, {d.year}</p>'
            f'</div>{tag_html}</div>')


def _age_tag(date_iso: str, built_iso: str) -> str | None:
    """"Today" / "Yesterday" against the build date, else None (never guess)."""
    try:
        delta = (_date.fromisoformat(built_iso) - _date.fromisoformat(date_iso)).days
    except ValueError:
        return None
    return "Today" if delta == 0 else ("Yesterday" if delta == 1 else None)


def _report_html(r: dict, tag: str | None = None, prev: bool = False) -> str:
    return (f'<section class="letter ko-report" id="{html.escape(r["date"])}">'
            f'{_day_banner(r["date"], tag, prev)}'
            f'<div class="ko-body">{r["body"]}</div></section>')


def _newsarticle_jsonld(r: dict) -> dict:
    """NewsArticle JSON-LD for one report — headline, publish date, and
    publisher. Gives Google a per-day fresh-article signal (news-style rich
    results) instead of just a generic page."""
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": r["title"],
        "datePublished": f'{r["date"]}T06:00:00-07:00',
        "dateModified": f'{r["date"]}T06:00:00-07:00',
        "author": {
            "@type": "Organization",
            "name": "Bakersfield Daily Brief",
            "url": "https://bakersfieldbrief.com/",
        },
        "publisher": {
            "@type": "Organization",
            "name": "Bakersfield Daily Brief",
            "url": "https://bakersfieldbrief.com/",
            "logo": page_mod.publisher_logo(),
        },
        "mainEntityOfPage": f"https://bakersfieldbrief.com/overnight/#{r['date']}",
        "inLanguage": "en",
        "isAccessibleForFree": True,
    }


def _top_incident(reps: list) -> str | None:
    """Return the 'big one' incident headline from the newest report (for the
    FAQ answer) — the first bolded line under '## The big one'."""
    if not reps:
        return None
    text = reps[0]["path"].read_text(encoding="utf-8")
    m = re.search(r"##\s+The big one\s*\n\s*\*\*(.+?)\*\*", text, re.S)
    if not m:
        return None
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s or None


INCIDENTS_DIR = common.ROOT / "incidents"
_MON_ABBR = ("Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.",
             "Sept.", "Oct.", "Nov.", "Dec.")

# This page used to carry its own keyword buckets, so one night's file was counted twice
# and printed twice: "1 Shootings & weapons" here against "2 Weapons and assaults" on the
# home band (2026-10-12), and the keyword "fire" also matched "firearms incident". The
# rows now come from night_counts.MAP, the one table the home band and the wall read.


def _long_date(date_iso: str, abbr: bool = False) -> str:
    try:
        d = _date.fromisoformat(date_iso)
    except ValueError:
        return date_iso
    mon = _MON_ABBR[d.month - 1] if abbr else _MONTH[d.month - 1]
    return f"{mon} {d.day}, {d.year}"


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"


def _leads(text: str, n: int = 2) -> list[str]:
    """The night's own incident headlines (bolded leads), in report order.
    Log entries ("**HH:MM** — …") are not headlines."""
    out = []
    for m in re.finditer(r"^\*\*(.+?)\*\*", text, re.M):
        s = re.sub(r"\s+", " ", m.group(1)).strip(" .:")
        if s and not re.match(r"\d{1,2}:\d{2}", s) and s not in out:
            out.append(s)
        if len(out) >= n:
            break
    return out


def _opening(text: str) -> str:
    """The report's opening paragraph (first prose line under the title)."""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line != "---":
            return re.sub(r"\*+", "", line)
    return ""


def _incidents(date_iso: str) -> list[dict]:
    import json
    p = INCIDENTS_DIR / f"{date_iso}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


def _is_shooting(inc: dict) -> bool:
    t = str(inc.get("type", "")).lower().replace("_", " ")
    return "shoot" in t or "shots" in t


# The card's tile colours, one per night_counts row. A row the map does not name (a type
# promoted out of Other) takes the Other colour.
_CHIP_CLASS = {
    "Weapons and assaults": "weap", "Fires": "fire", "Crashes and traffic": "crash",
    "Medical and overdose": "med", "Missing persons": "miss",
    "Disturbances and welfare": "welf", "Burglary and theft": "theft",
    "Suspicious activity": "susp", "Alarms": "alarm",
}
# Shorter tile labels for phones. The rows and counts are night_counts'; only the words change.
_CHIP_SHORT = {
    "Weapons and assaults": "Weapons &amp; assaults", "Crashes and traffic": "Crashes",
    "Medical and overdose": "Medical", "Disturbances and welfare": "Disturbance &amp; welfare",
    "Burglary and theft": "Burglary &amp; theft", "Suspicious activity": "Suspicious",
}
_HOUR_LABELS = ("7 PM", "8 PM", "9 PM", "10 PM", "11 PM", "12 AM",
                "1 AM", "2 AM", "3 AM", "4 AM", "5 AM", "6 AM")
_BARE_SUMMARY = re.compile(r"^[^.]*\(\d{1,2}:\d{2}\)\s*$")


def _night_minute(t) -> int | None:
    """'HH:MM' -> minutes after 7 PM, so 19:00 is 0 and 05:20 is 620. None if unreadable."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(t or ""))
    if not m:
        return None
    return ((int(m.group(1)) - 19) % 24) * 60 + int(m.group(2))


def _clock(t) -> str:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(t or ""))
    if not m:
        return ""
    h, mm = int(m.group(1)), m.group(2)
    return f"{(h % 12) or 12}:{mm} {'AM' if h < 12 else 'PM'}"


def _top_calls(incs: list[dict], n: int = 4) -> list[dict]:
    """Up to n top calls, printed in the order they happened.

    Picked by night_counts.severity, the one ranking the reel and the post caption
    also use: danger to a person first, a fire only when it hit a home or a
    vehicle, and nothing below that (2026-10-20: four minor weapons calls crowded
    out nothing, but the old rank let a fire-heavy night's semi fire lead the
    social post). Within a tier: higher notability, then a call the log
    describes over one that is only a type and a time, then the earlier call.
    Calls that put a person in danger (tiers 0-2) are never capped; below that,
    at most two from any one category, so a run of fires cannot fill the list.
    """
    ranked = []
    for k, inc in enumerate(incs):
        tier = night_counts.severity(inc)
        if tier > 4:
            continue
        bare = _BARE_SUMMARY.match(str(inc.get("summary", ""))) is not None
        ranked.append((tier, -int(inc.get("notability") or 0), bare,
                       _night_minute(inc.get("time")) or 0, k))
    picked, per_chip = [], {}
    for row in sorted(ranked):
        inc = incs[row[-1]]
        chip = night_counts.CHIP_OF.get(night_counts.normalize(inc.get("type")), night_counts.OTHER)
        if row[0] >= 3 and per_chip.get(chip, 0) >= 2:
            continue
        per_chip[chip] = per_chip.get(chip, 0) + 1
        picked.append(inc)
        if len(picked) >= n:
            break
    return sorted(picked, key=lambda i: _night_minute(i.get("time")) or 0)


def _top_call_html(inc: dict) -> str:
    typ = night_counts.normalize(inc.get("type"))
    chip = night_counts.CHIP_OF.get(typ, night_counts.OTHER)
    tag = "Shooting" if _is_shooting(inc) else typ[:1].upper() + typ[1:]
    summary = re.sub(r"\s+", " ", str(inc.get("summary", ""))).strip()
    if not summary or _BARE_SUMMARY.match(summary):
        # The log has only the type and the time; the tag already says what it was.
        summary = "Reported to dispatch; no further detail in the log."
    return (f'<li><time>{_clock(inc.get("time"))}</time><p>'
            f'<span class="nc-tag nc-{_CHIP_CLASS.get(chip, "other")}">{html.escape(tag)}</span>'
            f'{html.escape(summary)}</p></li>')


def _night_stats_html(date_iso: str) -> str:
    """The night card: the total, calls per hour, the rows by kind and the top calls,
    straight from incidents/<date>.json. Nothing is shown when the file is missing,
    never an invented number.

    The rows, their order and their labels come from night_counts, the same table the
    home band and the wall read, so one night cannot show two sets of numbers.
    """
    incs = _incidents(date_iso)
    if not incs:
        return ""
    rows, inside, _unmapped = night_counts.chips(incs)
    total = len(incs)

    hours = [0] * 12
    times = []
    for inc in incs:
        m = _night_minute(inc.get("time"))
        if m is None:
            continue
        times.append((m, inc.get("time")))
        if m < 720:
            hours[m // 60] += 1
    peak = max(hours)
    bars = []
    for k, c in enumerate(hours):
        cls = ' class="peak"' if peak and c == peak else ""
        pct = round(100 * c / peak) if peak else 0
        bars.append(f'<i{cls} style="height:{pct}%" title="{_HOUR_LABELS[k]}: {c}"></i>')
    facts = []
    if peak:
        k = hours.index(peak)
        start = _HOUR_LABELS[k]
        end = _HOUR_LABELS[k + 1] if k < 11 else "7 AM"
        if start[-2:] == end[-2:]:
            start = start.split()[0]
        facts.append(("Busiest hour", f"<strong>{start}&ndash;{end}</strong> &middot; "
                                      f"{peak} call{'s' if peak != 1 else ''}"))
    facts.append(("Shooting calls", f"<strong>{sum(_is_shooting(i) for i in incs)}</strong>"))
    if times:
        facts.append(("First call", f"<strong>{_clock(min(times)[1])}</strong>"))
        facts.append(("Last call", f"<strong>{_clock(max(times)[1])}</strong>"))
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    mix = "".join(f'<span class="nc-{_CHIP_CLASS.get(label, "other")}" style="flex:{n}"></span>'
                  for label, n in rows)
    tiles = "".join(
        f'<li class="nc-{_CHIP_CLASS.get(label, "other")}"><b>{n}</b>'
        f'<small>{_CHIP_SHORT.get(label, html.escape(label))}</small></li>'
        for label, n in rows)
    top = _top_calls(incs)
    top_html = (f'<section class="nc-top"><h2>Last night&rsquo;s top calls</h2>'
                '<ol>' + "".join(_top_call_html(i) for i in top) + '</ol></section>' if top else "")

    note = ('Counts are the calls our overnight log captured '
            '(7 PM &ndash; 7 AM: the countywide radio feed, plus app-based dispatch '
            'reports for the hours the feed does not carry). It is not a complete '
            'record of every call.')
    if inside:
        note += f' The {night_counts.OTHER} row is {inside}.'
    try:
        d = _date.fromisoformat(date_iso)
        when = f"{_DOW[d.weekday()][:3]} &middot; {_MONTH[d.month - 1][:3]} {d.day}"
    except ValueError:
        when = html.escape(date_iso)
    plural = "s" if total != 1 else ""
    bars_html = "".join(bars)

    return f"""
    <article class="night-card" aria-label="Overnight summary for {html.escape(_long_date(date_iso))}">
      <div class="nc-side">
        <div class="nc-when"><span>{when}</span><span>7 PM &ndash; 7 AM</span></div>
        <div class="nc-total"><b>{total}</b><span>notable call{plural}<br>overnight</span></div>
        <div class="nc-chart"><div class="nc-hours" role="img" aria-label="Calls per hour, 7 PM to 7 AM">{bars_html}</div>
          <div class="nc-axis"><span>7p</span><span>11p</span><span>3a</span><span>7a</span></div></div>
        <dl class="nc-facts">{facts_html}</dl>
      </div>
      <div class="nc-main">
        <div class="nc-mix" aria-hidden="true">{mix}</div>
        <ul class="nc-cats">{tiles}</ul>
        {top_html}
        <div class="nc-cta">
          <p><strong>Get this in your inbox every morning.</strong> Free, one email, no spam.</p>
          <form class="nl-form nc-form" action="/api/newsletter" method="POST"><input type="email" name="email" placeholder="you@email.com" required aria-label="Your email"/><button type="submit">Sign up</button></form>
          <details class="nc-fine"><summary>About these numbers</summary><p>{note}</p></details>
        </div>
      </div>
    </article>"""


def _night_title(r: dict) -> str:
    leads = _leads(r["path"].read_text(encoding="utf-8"), 1)
    day = _long_date(r["date"], abbr=True)
    if leads:
        return f"{_clip(leads[0], 58)} — Bakersfield Overnight, {day}"
    return f"Bakersfield Overnight Police & Fire Log — {day}"


def _night_line(r: dict, href: str) -> str:
    """One archive row: date + that night's top two incident headlines."""
    leads = _leads(r["path"].read_text(encoding="utf-8"), 2)
    what = "; ".join(leads) if leads else "Overnight police, fire and EMS log"
    return (f'<li><a href="{href}"><strong>{html.escape(_long_date(r["date"], abbr=True))}</strong>'
            f'</a> &mdash; {html.escape(what)}</li>')


def _build_night_pages(reps: list, ctx, built_iso: str, newsletter: str) -> list[str]:
    """One permanent page per night at /overnight/<date>/ so every report has its
    own URL, title and NewsArticle block (the hub only ever shows the newest two)."""
    built = []
    rel = "../../"
    for i, r in enumerate(reps):
        text = r["path"].read_text(encoding="utf-8")
        newer = reps[i - 1] if i > 0 else None
        older = reps[i + 1] if i + 1 < len(reps) else None
        nav = ['<p class="arch-more">']
        if older:
            nav.append(f'<a class="btn btn-ghost" href="{rel}overnight/{older["date"]}/">'
                       f'&larr; {html.escape(_long_date(older["date"], abbr=True))}</a> ')
        nav.append(f'<a class="btn" href="{rel}overnight/">Latest night</a> ')
        if newer:
            nav.append(f'<a class="btn btn-ghost" href="{rel}overnight/{newer["date"]}/">'
                       f'{html.escape(_long_date(newer["date"], abbr=True))} &rarr;</a>')
        nav.append("</p>")
        nav_html = "".join(nav)
        try:
            dow = _DOW[_date.fromisoformat(r["date"]).weekday()] + ", "
        except ValueError:
            dow = ""
        long_day = _long_date(r["date"])
        title = _night_title(r)
        desc = _clip(_opening(text), 155) or (
            f"Overnight police, fire and EMS calls in Bakersfield and Kern County for {long_day}.")
        article = _newsarticle_jsonld(r)
        article["headline"] = _clip(title, 108)
        article["description"] = desc
        article["mainEntityOfPage"] = f"https://bakersfieldbrief.com/overnight/{r['date']}/"
        body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">The Kern Overnight &middot; {html.escape(long_day)}</p>
    <h1>What happened in Bakersfield overnight: {html.escape(dow + long_day)}</h1>
    <p class="lede">Police, fire and EMS calls logged across Kern County overnight, 7 PM &ndash; 7 AM. Preliminary dispatch information; locations are generalized.</p></div></div>

    {nav_html}
    {_night_stats_html(r["date"])}
    <div class="ko-reports">{_report_html(r)}</div>
    {nav_html}
    {newsletter}
    <p class="note" style="margin-top:14px">Compiled from preliminary dispatch traffic; details are unconfirmed until an official source reports them, and locations are generalized for privacy. See <a href="{rel}overnight/archive/">every night on file</a>.</p>
    <p class="note credit" style="margin-top:10px">Audio provided by
    <a href="https://www.broadcastify.com/listen/feed/14029" rel="noopener nofollow" target="_blank">Broadcastify</a>.
    Feed archives are used under a Creative Commons Attribution 3.0 United States license.</p>"""
        page = page_mod.render(
            title=title, desc=desc, canonical=f"/overnight/{r['date']}/",
            content=body, current="overnight", rel=rel, built=built_iso,
            statusbar=ctx.statusbar, og_type="article",
            jsonld=[page_mod.org_jsonld(), article])
        common.write(common.SITE / "overnight" / r["date"] / "index.html", page)
        built.append(f"overnight/{r['date']}/index.html")
    return built


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"
    reps = _published_reports()

    if reps:
        parts = [_report_html(r, _age_tag(r["date"], built_iso), prev=i > 0)
                 for i, r in enumerate(reps[:2])]
        # a dashed rule between the two day cards makes the break unmistakable
        recent = ('<div class="ko-reports">'
                  + '<div class="ko-sep"></div>'.join(parts) + '</div>')
        n_old = len(reps) - 2
        more_btn = (f'<p class="arch-more" style="margin-top:10px">'
                    f'<a class="btn" href="{rel}overnight/archive/">'
                    f'View previous reports ({n_old})</a></p>'
                    if n_old > 0 else "")
        recent_nights = ('<p class="sec-head">Recent nights</p><div class="letter"><ul>'
                         + "".join(_night_line(r, f'{rel}overnight/{r["date"]}/') for r in reps[:14])
                         + '</ul></div>')
        stats = _night_stats_html(reps[0]["date"])
    else:
        recent = ('<p class="note">No reports published yet. The pipeline is being '
                  'stood up — first edition coming soon.</p>')
        more_btn = ""
        recent_nights = ""
        stats = ""

    explainer = """
    <p class="sec-head">How it works</p>
    <div class="link-grid">
      <div class="tile"><strong>Listen</strong><span>Police, sheriff, fire, and EMS calls logged overnight, 7 PM &ndash; 7 AM.</span></div>
      <div class="tile"><strong>Transcribe</strong><span>Radio audio is cleaned and turned into text with local vocabulary tuned for scanner jargon.</span></div>
      <div class="tile"><strong>Extract</strong><span>Incidents are pulled from the transcript under strict privacy rules.</span></div>
      <div class="tile"><strong>Write</strong><span>Each morning&rsquo;s report is drafted from the transcript and published automatically.</span></div>
    </div>

    <p class="sec-head">What we never publish</p>
    <div class="card"><p>No names. No license plates. No callback numbers. No patient details. No exact addresses &mdash; locations are generalized to block or cross-street level. Nothing from ambulance-to-hospital traffic. Everything is reported as preliminary dispatch information.</p></div>
    """

    from .daily import _newsletter_block
    newsletter = _newsletter_block()

    top = _top_incident(reps)
    latest_date = reps[0]["date"] if reps else ""
    latest_long = _long_date(latest_date) if latest_date else ""
    if top:
        happened_text = (f"On the night ending {latest_long}, the biggest call was: {top}. "
                         "The full overnight log on this page lists the other police, fire "
                         "and EMS calls, with times and general locations.")
    else:
        happened_text = ("The Kern Overnight publishes a morning summary of overnight "
                         "police, fire, and EMS activity across Bakersfield and Kern "
                         "County, updated daily.")
    faq = [("What happened in Bakersfield last night?", happened_text)]
    incs = _incidents(latest_date) if latest_date else []
    if incs:
        shots = [i for i in incs if _is_shooting(i)]
        if shots:
            first = _clip(str(shots[0].get("summary", "")), 220)
            shoot_text = (f"Our overnight scanner log for {latest_long} includes {len(shots)} "
                          f"shooting or shots-fired call{'s' if len(shots) != 1 else ''}. {first} "
                          "These are preliminary dispatch reports, not confirmed by police.")
        else:
            shoot_text = (f"No shooting or shots-fired call appears in our overnight log "
                          f"for {latest_long}. The log runs 7 PM to 7 AM from a countywide "
                          "radio feed plus app-based dispatch reports, so it is not a "
                          "complete record.")
        faq.append(("Was there a shooting in Bakersfield last night?", shoot_text))
    faq += [
        ("Where can I see Bakersfield police activity from today or last night?",
         "This page lists the police, sheriff, fire and EMS calls logged across Kern "
         "County between 7 PM and 7 AM, published every morning. Each night also has its own "
         "permanent page in the archive."),
        ("Is there a Bakersfield police scanner?",
         "Yes. The Kern Overnight summarizes overnight police, fire, and EMS dispatch activity "
         "across Bakersfield and Kern County every morning. For live audio, the Kern County "
         "feed is available on streaming scanner services like Broadcastify."),
        ("How accurate is this?",
         "Everything here is preliminary dispatch information taken from radio traffic. Details "
         "are unconfirmed until an official source reports them, and locations are generalized "
         "for privacy."),
    ]
    faq_jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq],
    }
    faq_html = ('<p class="sec-head">Questions people ask</p><div class="letter">'
                + "".join(f"<h3>{html.escape(q)}</h3><p>{html.escape(a)}</p>" for q, a in faq)
                + "</div>")

    updated = f" Updated {html.escape(latest_long)}." if latest_long else ""
    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">The Kern Overnight &middot; scanner-to-newsletter</p>
    <h1>What Happened in Bakersfield Last Night</h1>
    <p class="lede">We listen to the county&rsquo;s police, fire, and EMS radio all night so you don&rsquo;t have to. Every morning: what happened overnight, what&rsquo;s preliminary, and where.{updated}</p></div></div>

    {stats}

    <p class="sec-head">Published reports</p>
    {recent}
    {more_btn}

    {recent_nights}

    {newsletter}

    {faq_html}

    {explainer}
    <p class="note" style="margin-top:14px">Compiled from preliminary dispatch traffic each morning; details are unconfirmed until an official source reports them, and locations are generalized for privacy.</p>
    <p class="note credit" style="margin-top:10px">Audio provided by
    <a href="https://www.broadcastify.com/listen/feed/14029" rel="noopener nofollow" target="_blank">Broadcastify</a>.
    Feed archives are used under a Creative Commons Attribution 3.0 United States license.</p>"""

    title = "What Happened in Bakersfield Last Night? Police, Fire & EMS Log"
    desc = ("What happened in Bakersfield last night? Overnight police activity, shootings, "
            "fires and crashes heard on Kern County scanner radio, with times and general "
            "locations. Updated every morning.")
    page = page_mod.render(
        title=title, desc=desc,
        canonical="/overnight/",
        content=body, current="overnight", rel=rel,
        built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(),
                page_mod.webpage_jsonld("/overnight/", latest_date or built_iso, title, desc),
                faq_jsonld])
    common.write(common.SITE / "overnight" / "index.html", page)
    built.append("overnight/index.html")

    # ---- one permanent page per night
    built += _build_night_pages(reps, ctx, built_iso, newsletter)

    # ---- archive page: an index of every night, newest first, linking to its own page
    archive_rel = "../../"
    if reps:
        all_nights = ('<div class="letter"><ul>'
                      + "".join(_night_line(r, f'{archive_rel}overnight/{r["date"]}/') for r in reps)
                      + '</ul></div>')
    else:
        all_nights = recent
    archive_body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Archive</p>
    <h1>The Kern Overnight — every night on file</h1>
    <p class="lede">Every published overnight police, fire and EMS report for Bakersfield and Kern County, newest first. Each night has its own page.</p></div></div>

    <p class="arch-more"><a href="{archive_rel}overnight/" class="btn">&larr; Back to the latest reports</a></p>
    {all_nights}
    <p class="arch-more"><a href="{archive_rel}overnight/" class="btn">&larr; Back to the latest reports</a></p>
    {newsletter}
    """

    archive_page = page_mod.render(
        title="Bakersfield Overnight Police & Fire Log Archive — Every Night | Bakersfield Daily Brief",
        desc="Archive of every Kern Overnight report: nightly police, fire and EMS scanner activity for Bakersfield and Kern County, one page per night.",
        canonical="/overnight/archive/",
        content=archive_body, current="overnight", rel=archive_rel,
        built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "overnight" / "archive" / "index.html", archive_page)
    built.append("overnight/archive/index.html")

    ctx.build_report["overnight"] = {"published": len(reps)}
    return built
