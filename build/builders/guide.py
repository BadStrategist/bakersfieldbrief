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
from .events import _display_name

_VENUE_ORDER = {"fox": 0, "arena": 1, "well": 2, "condors": 3, "visit": 4}


def build(ctx, sources: dict) -> list[str]:
    built = []
    today = common.today_pacific()
    date_label = f"{today.strftime('%B')} {today.day}, {today.year}"

    # Thursday/--guide builds scrape the whitelist fresh and cache the picks;
    # other builds render the cached picks so the footer link never 404s.
    # Venue listings are fetched on EVERY build, so pick from them every build: the Thursday cache
    # alone showed Sept 18 and 21 events on the 22nd. The cache is only the fallback when the
    # venue fetch came back empty.
    cache_path = common.DATA / "last_guide.json"
    fresh = sources.get("venues", {}).get("events", []) or []
    if fresh:
        events = _pick(fresh, today)
        if getattr(ctx, "guide", False):
            cache_path.write_text(json.dumps(events, default=str), encoding="utf-8")
    else:
        try:
            events = _pick(json.loads(cache_path.read_text(encoding="utf-8")), today)
        except Exception:  # noqa: BLE001
            events = []
    wk_start, wk_end = _weekend(today)
    weekend_label = (f"{wk_start:%b} {wk_start.day}" + (f" to {wk_end:%b} {wk_end.day}" if wk_end.month != wk_start.month
                     else f" to {wk_end.day}"))

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
        <li><strong>{html.escape(_display_name(e))}</strong>
        <span class="when">{html.escape(e.get('venue', ''))} · {html.escape(_fmt_when_txt(e, today))}</span>
        <a href="{html.escape(e.get('url', '#'))}" target="_blank" rel="noopener">Details →</a></li>""" for e in events)
        picks = f'<ol class="guide-list">{lis}</ol>'
    else:
        picks = ('<p class="note">No dated events are posted by our local venues yet. '
                 'The guide refreshes every Thursday; see <a href="../events/">all events</a> meanwhile.</p>')
        events = []  # report below

    rel = "../"
    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Weekend Guide</p>
    <h1>5 Things to Do This Weekend</h1>
    <p class="lede">Picked from the calendars of local venues: the Fox, Mechanics Bank Arena,
    Temblor Brewing, Bakersfield Community Theatre, the Bakersfield Symphony, the Condors,
    and CSUB and Bakersfield College home games.</p>
    <div class="meta"><span>Weekend of {weekend_label}</span><span class="dot">&bull;</span>
    <span>Updated {date_label}</span></div></div></div>
    {images.figure("fox", rel)}
    {picks}
    <section class="block">
      <div class="sign-head"><span class="tab">How</span><h2>How picks are made</h2></div>
      <div class="card"><p>Events come from each venue&rsquo;s own website (schema.org event data,
      ticketing calendars, or events feeds). We only read a fixed list of established local
      venues, so a closed venue or a spam listing can&rsquo;t slip in.
      This weekend&rsquo;s events come first, then the next ones coming up; past events are
      never listed. Dates are as each venue published them, so check before you go.</p></div>
    </section>"""
    page = page_mod.render(
        title="Weekend Guide — 5 things to do in Bakersfield | Bakersfield Daily Brief",
        desc="Five things to do this weekend in Bakersfield, picked weekly from the listings of established local venues (Fox Theater, Mechanics Bank Arena, The Well, Condors, Visit Bakersfield).",
        canonical="/guide/", content=body, current="other", rel=rel,
        built=common.iso_today(), statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    common.write(common.SITE / "guide" / "index.html", page)
    built.append("guide/index.html")

    ctx.build_report["guide"] = {"picked": len(events), "draft": f"drafts/weekend-guide-{today.isoformat()}"}
    return built


def _weekend(today) -> tuple:
    """The coming Friday-to-Sunday (the current one from Friday through Sunday)."""
    wd = today.weekday()   # Mon=0 .. Sun=6
    if wd >= 4:
        start = today - dt.timedelta(days=wd - 4)
    else:
        start = today + dt.timedelta(days=4 - wd)
    return start, start + dt.timedelta(days=2)


def _pick(events: list[dict], today) -> list[dict]:
    """This weekend's dated events first, then the soonest upcoming; never a past event.
    Max 1 per venue, 5 total. Undated listings only fill leftover slots."""
    start, end = _weekend(today)

    def score(e):
        when = _event_date(e, today)
        if when is None:
            return (2, 0)
        if start <= when <= end:
            return (0, when.toordinal())
        return (1, when.toordinal())
    minor = re.compile(r"swim|dive|cross country|golf|tennis|track|alumni|select-a-seat", re.I)
    ranked = [e for e in sorted(events, key=score)
              if (_event_date(e, today) or today) >= today and not minor.search(str(e.get("name", "")))]
    # Weekend picks go round the days (Fri, Sat, Sun) so one busy Friday can't take all five;
    # then the next upcoming events fill any slots left. One pick per venue keeps it varied.
    def _runs_over_weekend(e):
        # a theatrical run (Gaslight) that is playing across this weekend
        try:
            return (e.get("start") and e.get("end") and
                    dt.date.fromisoformat(e["start"]) <= end and dt.date.fromisoformat(e["end"]) >= start)
        except ValueError:
            return False
    weekend = [e for e in ranked
               if ((d := _event_date(e, today)) and start <= d <= end) or _runs_over_weekend(e)]
    by_day = {}
    for e in weekend:
        d = _event_date(e, today)
        bucket = by_day.setdefault(d if d and start <= d <= end else start, [])
        # a running production has no single date; put it first on its day so a busy Friday
        # of one-night events can't crowd it out of the five
        bucket.insert(0, e) if _runs_over_weekend(e) else bucket.append(e)
    order = []
    while any(by_day.values()):
        for day in sorted(by_day):
            if by_day[day]:
                order.append(by_day[day].pop(0))
    order += [e for e in ranked if e not in weekend]
    out, per_venue = [], set()
    for e in order:
        vs = e.get("venue_slug", "?")
        if vs in per_venue:
            continue
        out.append(e)
        per_venue.add(vs)
        if len(out) >= 5:
            break
    return sorted(out, key=score)


def _fmt_when_txt(e: dict, today) -> str:
    """Readable date for a pick: ISO stamps become 'Fri, Sep 25 at 7:30 p.m.'."""
    if e.get("label"):
        return str(e["label"])
    w = str(e.get("when") or "").strip()
    if w[:4].isdigit() and w[4:5] == "-":
        return common.fmt_when(w.replace(" ", "T"))
    return w or _fmt_day(_event_date(e, today))


def _fmt_day(d) -> str:
    return f"{d:%a}, {d:%b} {d.day}" if d else "see listing for date"


def _event_date(e: dict, today) -> dt.date | None:
    """The listing's date, or a "9/25" date written into the name (Condors games list that way)."""
    d = _parse_when(e.get("when", ""), today)
    if d is None:
        m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d|/)", str(e.get("name", "")))
        if m:
            try:
                d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
                if (d - today).days < -180:   # a January game listed in December
                    d = d.replace(year=today.year + 1)
            except ValueError:
                d = None
    return d


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
