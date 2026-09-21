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
            m = re.match(r"\*\*(.+?)\*\*\.?\s*(.*)", line)
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
        all_reports = ('<div class="ko-reports">'
                       + "".join(_report_html(r) for r in reps) + '</div>')
        n_old = len(reps) - 2
        more_btn = (f'<p class="arch-more" style="margin-top:10px">'
                    f'<a class="btn" href="{rel}overnight/archive/">'
                    f'View previous reports ({n_old})</a></p>'
                    if n_old > 0 else "")
    else:
        recent = ('<p class="note">No reports published yet. The pipeline is being '
                  'stood up — first edition coming soon.</p>')
        all_reports = recent
        more_btn = ""

    explainer = """
    <p class="sec-head">How it works</p>
    <div class="link-grid">
      <div class="tile"><strong>Listen</strong><span>Police, sheriff, fire, and EMS radio overnight, 9 PM &ndash; 5 AM.</span></div>
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
    if top:
        happened_text = (f"On {latest_date}, {top}. Read the full Kern Overnight "
                         "report for the complete rundown of overnight activity.")
    else:
        happened_text = ("The Kern Overnight publishes a morning summary of overnight "
                         "police, fire, and EMS activity across Bakersfield and Kern "
                         "County, updated daily.")
    faq_jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "What happened overnight in Bakersfield?",
                "acceptedAnswer": {"@type": "Answer", "text": happened_text},
            },
            {
                "@type": "Question",
                "name": "Is there a Bakersfield police scanner?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("Yes. The Kern Overnight summarizes overnight police, fire, "
                             "and EMS dispatch activity across Bakersfield and Kern County "
                             "every morning. For live audio, the Kern County feed is "
                             "available on streaming scanner services like Broadcastify."),
                },
            },
        ],
    }

    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">The Kern Overnight &middot; scanner-to-newsletter</p>
    <h1>What Happened Overnight in Bakersfield</h1>
    <p class="lede">We listen to the county&rsquo;s police, fire, and EMS radio all night so you don&rsquo;t have to. Every morning: what happened, what&rsquo;s preliminary, and where.</p></div></div>

    {newsletter}

    <p class="sec-head">Published reports</p>
    {recent}
    {more_btn}

    {explainer}
    <p class="note" style="margin-top:14px">Compiled from preliminary dispatch traffic each morning; details are unconfirmed until an official source reports them, and locations are generalized for privacy.</p>
    <p class="note credit" style="margin-top:10px">Audio provided by
    <a href="https://www.broadcastify.com/listen/feed/14029" rel="noopener nofollow" target="_blank">Broadcastify</a>.
    Feed archives are used under a Creative Commons Attribution 3.0 United States license.</p>"""

    page = page_mod.render(
        title="What Happened Overnight in Bakersfield — Police, Fire & EMS",
        desc="What happened overnight in Bakersfield? The Kern Overnight summarizes overnight police, fire, and EMS activity across Bakersfield and Kern County every morning — published daily.",
        canonical="/overnight/",
        content=body, current="overnight", rel=rel,
        built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(), faq_jsonld]
               + [_newsarticle_jsonld(r) for r in reps[:2]])
    common.write(common.SITE / "overnight" / "index.html", page)
    built.append("overnight/index.html")

    # ---- archive page: every report, newest first (feeds trends/monthlies later)
    archive_rel = "../../"
    archive_body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Archive</p>
    <h1>The Kern Overnight — every report</h1>
    <p class="lede">All published overnight reports, newest first. The full archive stays on file so we can build trends and monthly summaries from it.</p></div></div>

    {newsletter}

    <p class="arch-more"><a href="{archive_rel}overnight/" class="btn">&larr; Back to the latest reports</a></p>
    {all_reports}
    <p class="arch-more"><a href="{archive_rel}overnight/" class="btn">&larr; Back to the latest reports</a></p>
    """

    archive_page = page_mod.render(
        title="The Kern Overnight — Archive | Bakersfield Daily Brief",
        desc="Archive of every Kern Overnight scanner-to-newsletter report for Bakersfield and Kern County.",
        canonical="/overnight/archive/",
        content=archive_body, current="overnight", rel=archive_rel,
        built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld()] + [_newsarticle_jsonld(r) for r in reps])
    common.write(common.SITE / "overnight" / "archive" / "index.html", archive_page)
    built.append("overnight/archive/index.html")

    ctx.build_report["overnight"] = {"published": len(reps)}
    return built
