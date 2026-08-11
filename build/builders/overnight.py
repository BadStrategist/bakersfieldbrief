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
from pathlib import Path

from .. import common
from . import page as page_mod

REPORTS_DIR = Path(common.DATA) / "overnight_reports"


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
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
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


def _report_html(r: dict) -> str:
    return (f'<section class="letter" id="{html.escape(r["date"])}">'
            f'<p class="letter-meta">{html.escape(r["date"])}</p>{r["body"]}</section>')


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"
    reps = _published_reports()

    if reps:
        recent = "".join(_report_html(r) for r in reps[:2])
        all_reports = "".join(_report_html(r) for r in reps)
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
      <div class="tile"><strong>Listen</strong><span>Broadcastify feed 14029 archives the overnight airwaves, 9 PM &ndash; 6 AM.</span></div>
      <div class="tile"><strong>Transcribe</strong><span>Radio audio is cleaned and turned into text with local vocabulary tuned for scanner jargon.</span></div>
      <div class="tile"><strong>Extract</strong><span>Incidents are pulled from the transcript under strict privacy rules.</span></div>
      <div class="tile"><strong>Write</strong><span>Each morning&rsquo;s report is drafted from the transcript and published automatically.</span></div>
    </div>

    <p class="sec-head">What we never publish</p>
    <div class="card"><p>No names. No license plates. No callback numbers. No patient details. No exact addresses &mdash; locations are generalized to block or cross-street level. Nothing from ambulance-to-hospital traffic. Everything is reported as preliminary dispatch information.</p></div>
    """

    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Scanner-to-newsletter</p>
    <h1>The Kern Overnight</h1>
    <p class="lede">We listen to the county&rsquo;s police, fire, and EMS radio all night so you don&rsquo;t have to. Every morning: what happened, what&rsquo;s preliminary, and where.</p></div></div>

    <p class="sec-head">Published reports</p>
    {recent}
    {more_btn}

    {explainer}
    <p class="note" style="margin-top:14px">Compiled from preliminary dispatch traffic each morning; details are unconfirmed until an official source reports them, and locations are generalized for privacy.</p>"""

    page = page_mod.render(
        title="The Kern Overnight | Bakersfield Daily Brief",
        desc="The Kern Overnight: a scanner-to-newsletter morning brief of overnight police, fire, and EMS activity across Bakersfield and Kern County.",
        canonical="/overnight/",
        content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "overnight" / "index.html", page)
    built.append("overnight/index.html")

    # ---- archive page: every report, newest first (feeds trends/monthlies later)
    archive_rel = "../../"
    archive_body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Archive</p>
    <h1>The Kern Overnight — every report</h1>
    <p class="lede">All published overnight reports, newest first. The full archive stays on file so we can build trends and monthly summaries from it.</p></div></div>

    <p class="arch-more"><a href="{archive_rel}overnight/" class="btn">&larr; Back to the latest reports</a></p>
    {all_reports}
    <p class="arch-more"><a href="{archive_rel}overnight/" class="btn">&larr; Back to the latest reports</a></p>
    """

    archive_page = page_mod.render(
        title="The Kern Overnight — Archive | Bakersfield Daily Brief",
        desc="Archive of every Kern Overnight scanner-to-newsletter report for Bakersfield and Kern County.",
        canonical="/overnight/archive/",
        content=archive_body, current="other", rel=archive_rel,
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "overnight" / "archive" / "index.html", archive_page)
    built.append("overnight/archive/index.html")

    ctx.build_report["overnight"] = {"published": len(reps)}
    return built
