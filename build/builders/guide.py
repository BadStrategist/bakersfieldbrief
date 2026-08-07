#!/usr/bin/env python3
"""Weekend Guide — '5 things to do this weekend' (Thursday build, human-reviewed).

Runs only when build_all.py is invoked with --guide (the Thursday workflow).
Picks up to 5 events from the venue whitelist (data/venues.json → venues
source), preferring dated events in the next 4 days, max 2 per venue.

Outputs:
  drafts/weekend-guide-<date>.html + .txt  — EMAIL DRAFTS for human review
  site/guide/index.html                   — auto-published site version
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re

from .. import common
from ..emailer import render_guide
from . import images
from . import page as page_mod

_VENUE_ORDER = {"fox": 0, "arena": 1, "well": 2, "condors": 3, "visit": 4}


def build(ctx, sources: dict) -> list[str]:
    built = []
    today = common.today_pacific()
    date_label = f"{today.strftime('%B')} {today.day}, {today.year}"

    # Thursday/--guide builds scrape the whitelist fresh and cache the picks;
    # other builds render the cached picks so the footer link never 404s.
    cache_path = common.DATA / "last_guide.json"
    if getattr(ctx, "guide", False):
        events = _pick(sources.get("venues", {}).get("events", []), today)
        cache_path.write_text(json.dumps(events, default=str), encoding="utf-8")
    else:
        try:
            events = _pick(json.loads(cache_path.read_text(encoding="utf-8")), today)
        except Exception:  # noqa: BLE001
            events = []

    # ---- email drafts (human review) — guide builds only
    if getattr(ctx, "guide", False):
        html_doc, txt_doc = render_guide(events, date_label, reviewed=False)
        draft_dir = common.DRAFTS / f"weekend-guide-{today.isoformat()}"
        draft_dir.mkdir(parents=True, exist_ok=True)
        (draft_dir / "guide.html").write_text(html_doc, encoding="utf-8")
        (draft_dir / "guide.txt").write_text(txt_doc, encoding="utf-8")
        built.append(f"drafts/weekend-guide-{today.isoformat()}/guide.html")
        built.append(f"drafts/weekend-guide-{today.isoformat()}/guide.txt")

    # ---- site page (auto-published every build; cached picks off-Thursday)
    if events:
        lis = "".join(f"""
        <li><strong>{html.escape(e.get('name', ''))}</strong>
        <span class="when">{html.escape(e.get('venue', ''))} · {html.escape(e.get('when', '') or 'check listing')}</span>
        <a href="{html.escape(e.get('url', '#'))}" target="_blank" rel="noopener">Details →</a></li>""" for e in events)
        picks = f'<ol class="guide-list">{lis}</ol>'
    else:
        picks = ('<p class="note">No dated events found in the venue whitelist yet — '
                 'the Thursday build scrapes the whitelist; check back after it runs.</p>')
        events = []  # report below

    rel = "../"
    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Weekend Guide</p>
    <h1>5 Things to Do This Weekend</h1>
    <p class="lede">Picked from the venues we watch — Fox Theater, Mechanics Bank Arena,
    The Well Comedy Club, the Condors, and Visit Bakersfield&rsquo;s calendar.</p>
    <div class="meta"><span>Week of {date_label}</span><span class="dot">&bull;</span>
    <span>generated Thursday &middot; email draft is reviewed before sending</span></div></div></div>
    {images.figure("amtrak", rel)}
    {picks}
    <section class="block">
      <div class="sign-head"><span class="tab">How</span><h2>How picks are made</h2></div>
      <div class="card"><p>Events come from each venue&rsquo;s own website (schema.org event data,
      ticketing calendars, or events feeds). We scrape only the venues on our hand-maintained
      whitelist — a whitelist can&rsquo;t recommend a dead venue the way a scraper can.
      Venues with no dated events this weekend are skipped; dates are as the venue published them,
      so check before you go.</p></div>
    </section>"""
    page = page_mod.render(
        title="Weekend Guide — 5 things to do in Bakersfield | Bakersfield Daily Brief",
        desc="Five things to do this weekend in Bakersfield, picked weekly from a hand-maintained venue whitelist (Fox Theater, Mechanics Bank Arena, The Well, Condors, Visit Bakersfield).",
        canonical="/guide/", content=body, current="other", rel=rel,
        built=common.iso_today(), statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    common.write(common.SITE / "guide" / "index.html", page)
    built.append("guide/index.html")

    ctx.build_report["guide"] = {"picked": len(events), "draft": f"drafts/weekend-guide-{today.isoformat()}"}
    return built


def _pick(events: list[dict], today) -> list[dict]:
    """Prefer dated events in the next 4 days; max 2 per venue; 5 total."""
    window = [today + dt.timedelta(days=i) for i in range(5)]
    def score(e):
        when = _parse_when(e.get("when", ""), today)
        if when in window:
            return (0, when.toordinal())
        return (1, 0)
    ranked = sorted(events, key=score)
    out, per_venue = [], {}
    for e in ranked:
        vs = e.get("venue_slug", "?")
        if per_venue.get(vs, 0) >= 2:
            continue
        out.append(e)
        per_venue[vs] = per_venue.get(vs, 0) + 1
        if len(out) >= 5:
            break
    return out


def _parse_when(s: str, today) -> dt.date | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s[:16], fmt).date()
        except ValueError:
            pass
    m = re.match(r"([A-Z][a-z]{2}) (\d{1,2}),? (\d{4})", s)
    if m:
        try:
            return dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
        except ValueError:
            pass
    m2 = re.match(r"([A-Z][a-z]{2}) (\d{1,2})", s)
    if m2:
        try:
            d = dt.datetime.strptime(f"{m2.group(1)} {m2.group(2)} {today.year}", "%b %d %Y").date()
            return d if abs((d - today).days) < 200 else None
        except ValueError:
            return None
    return None
