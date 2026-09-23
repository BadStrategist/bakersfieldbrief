#!/usr/bin/env python3
"""City Hall & County — What to Watch agenda previews (auto-published) and
What They Decided recaps (DRAFTS for review, never auto-published).

Pages:
  /city-hall/                          hub: upcoming meetings (city + county)
  /city-hall/meetings/<slug>/          per-meeting agenda preview
  /city-hall/county-board/             current Kern BOS agenda preview
  drafts/recap-<slug>.md               post-meeting recap skeleton for review
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import common
from ..sources import escribe
from . import images
from . import page as page_mod

RECAP_LOOKBACK_DAYS = 14


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    es = sources.get("escribe", {})
    board = sources.get("kern_board", {})

    rel = "../"

    # ---- county board preview page ----
    county_html = _county_page(board, built_iso, rel="../../", ctx=ctx)
    common.write(common.SITE / "city-hall" / "county-board" / "index.html", county_html)
    built.append("city-hall/county-board/index.html")

    # ---- per-meeting preview pages ----
    meeting_pages = []
    for m in es.get("upcoming", []):
        slug = _slug(m["name"], m.get("start_iso", ""))
        out = common.SITE / "city-hall" / "meetings" / slug / "index.html"
        common.write(out, _meeting_page(m, built_iso, rel="../../../", ctx=ctx))
        meeting_pages.append({"name": m["name"], "start_iso": m.get("start_iso", ""),
                              "slug": slug, "items": len(m.get("items", [])),
                              "watched": bool(m.get("watched"))})
        built.append(f"city-hall/meetings/{slug}/index.html")

    # ---- hub page ----
    hub = _hub(es, board, meeting_pages, built_iso, rel, ctx)
    common.write(common.SITE / "city-hall" / "index.html", hub)
    built.append("city-hall/index.html")

    # ---- recap DRAFTS (meetings that already happened, no draft yet) ----
    drafts = _recap_drafts(es)
    ctx.build_report["cityhall"] = {
        "upcoming_meetings": len(meeting_pages),
        "county_items": len(board.get("items", [])),
        "drafts_generated": len(drafts),
    }
    return built


# ---------------------------------------------------------------- county
def _meeting_date(raw: str):
    """Parse a board date string ('September 1, 2026' or '9/1/2026') to a
    date, or None if unparseable/empty. Raises nothing."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%B %d, %Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _meeting_is_past(raw: str) -> bool:
    """True when the board meeting date is before today (America/Los_Angeles).
    Unparseable/missing dates are treated as NOT past so the page keeps the
    normal 'next meets' copy rather than inventing a gap."""
    d = _meeting_date(raw)
    return bool(d) and d < common.today_pacific()


def _county_page(board: dict, built_iso: str, rel: str, ctx) -> str:
    items = board.get("items", [])[:80]
    if board.get("ok"):
        if items:
            rows = "".join(f"""
            <tr>
              <td class="num">{html.escape(i.get('num', ''))}</td>
              <td>{html.escape(i.get('title', ''))}</td>
              <td>{'<span class="pill amber">Flock/ALPR watch</span>' if _watch(i) else ''}</td>
            </tr>""" for i in items)
            table = f"""
            <div class="table-wrap"><table class="data">
              <thead><tr><th class="num">No.</th><th>Agenda item</th><th>Watch</th></tr></thead>
              <tbody>{rows}</tbody>
            </table></div>"""
        else:
            table = '<p class="note">No numbered items were extractable from the current board agenda PDF this build.</p>'

        # ---- direct quotable answer (first text after H1, for crawlers/AI)
        raw_date = str(board.get('date', ''))
        date_str = html.escape(raw_date)
        watched = board.get("watched", [])
        top_item = items[0]['title'] if items else ""
        past = _meeting_is_past(raw_date)
        if past:
            ago = (common.today_pacific() - _meeting_date(raw_date)).days
            direct_answer = (f'<p class="answer"><strong>The latest posted agenda is from '
                             f'{date_str or "a past meeting"}; check the board&rsquo;s page for '
                             f'the next meeting.</strong> '
                             f'This agenda carries {len(items)} items'
                             + (f", led by {html.escape(top_item[:60])}" if top_item else "")
                             + (f". {len(watched)} item(s) reference Flock or ALPR surveillance." if watched else ".")
                             + ' Agendas are posted 72 hours ahead under the Brown Act.</p>')
            direct_answer += (f'<p class="note">This agenda was posted for the {date_str} meeting, '
                              f'{ago} day(s) ago. It is the board&rsquo;s most recently published '
                              f'agenda; a new one appears once the next meeting date is set.</p>')
        else:
            direct_answer = (f'<p class="answer"><strong>The Kern County Board of Supervisors '
                             f'next meets on {date_str or "a posted date"} at 9:00 AM at the County '
                             f'Administration Building, 1115 Truxtun Avenue, Bakersfield.</strong> '
                             f'This agenda carries {len(items)} items'
                             + (f", led by {html.escape(top_item[:60])}" if top_item else "")
                             + (f". {len(watched)} item(s) reference Flock or ALPR surveillance." if watched else ".")
                             + ' Agendas are posted 72 hours ahead under the Brown Act.</p>')

        # ---- FAQ (on-page + schema)
        if past:
            q1_answer = (f"The board generally meets on Tuesdays at 9:00 AM at the Kern County "
                         f"Administration Building, 1115 Truxtun Avenue, Bakersfield. The most "
                         f"recent posted agenda is from {date_str or 'a past meeting'}; check the "
                         f"board's page for the next meeting.")
            q3_answer = (f"The most recent posted agenda ({date_str or 'a past meeting'}) includes "
                         f"{len(items)} items."
                         + (f" Led by {html.escape(top_item[:80])}." if top_item else ""))
        else:
            q1_answer = (f"The board generally meets on Tuesdays at 9:00 AM at the Kern County "
                         f"Administration Building, 1115 Truxtun Avenue, Bakersfield. The next "
                         f"posted meeting is {date_str or 'TBD'}.")
            q3_answer = (f"The next posted agenda ({date_str or 'current meeting'}) includes {len(items)} items."
                         + (f" Led by {html.escape(top_item[:80])}." if top_item else ""))
        faq_qa = [
            ("When does the Kern County Board of Supervisors meet?", q1_answer),
            ("How do I see the Kern County Board of Supervisors agenda?",
             "Agendas are posted 72 hours before each meeting per the Brown Act. This page shows the current posted agenda items; the official agenda PDF is linked above."),
            ("What is on the next Kern County Board of Supervisors agenda?", q3_answer),
            ("How does Flock / license-plate-reader surveillance get approved in Kern County?",
             "Flock Safety camera and ALPR (automated license plate reader) proposals come before the Board of Supervisors as agenda items. This page flags those items with an amber 'Flock/ALPR watch' tag."),
            ("Where can I watch or participate in the Kern County Board of Supervisors meeting?",
             "Meetings are at the Kern County Administration Building, 1115 Truxtun Avenue, Bakersfield. Check the official board page for live-stream and public-comment details."),
        ]
        faq_html = "".join(
            f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq_qa)
        import re as _re
        live_answer = _re.sub(r"<[^>]+>", "", faq_qa[0][1])

        body = f"""
        <div class="hero"><p class="kicker">County &middot; Kern Board of Supervisors</p>
        <h1>Kern County Board of Supervisors Agenda</h1>
        <p class="lede">The current Kern County Board of Supervisors agenda, posted for the
        {date_str or 'upcoming'} meeting. The board meets in the County
        Administration Building, 1115 Truxtun Avenue, Bakersfield, generally Tuesdays at 9:00 AM.
        Agendas are posted 72 hours ahead per the Brown Act.</p>
        <div class="meta"><span>Agenda posted: <span class="updated">{date_str}</span></span>
        <span class="dot">&bull;</span><span>Source: official board agenda PDF</span></div></div>
        {direct_answer}
        <p><a class="pill amber" href="https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf">Official agenda PDF ↗</a>
        <a class="pill" href="https://www.kerncounty.com/government/board-of-supervisors">Board page ↗</a></p>
        {table}
        <div class="callout"><strong>Surveillance watch:</strong> items mentioning Flock, ALPR, or license-plate
        readers are flagged amber. The Board&rsquo;s consent calendar is also captured when present.</div>
        <section class="block"><div class="sign-head"><span class="tab">FAQ</span><h2>Board of Supervisors questions</h2></div>
        <div class="card">{faq_html}</div></section>"""
    else:
        asof = html.escape(str(board.get("asof", "")))
        asof_note = (f' Last known data as of <span class="updated">{asof}</span>.' if asof else '')
        body = ('<div class="hero"><h1>Kern County Board of Supervisors Agenda</h1>'
                f'<div class="errorbox">The county agenda data source did not load this build '
                f'({html.escape(str(board.get("error", "unknown")))}).{asof_note}</div>'
                '<p>Check the <a href="https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf">'
                'official board agenda PDF ↗</a> or the <a '
                'href="https://www.kerncounty.com/government/board-of-supervisors">board page ↗</a> '
                'for the latest meeting information.</p></div>')

    if board.get("ok"):
        _date = str(board.get("date", "") or "")
        _top = (items[0]["title"] if items else "").strip().rstrip(", .;-")
        _watched = len(board.get("watched", []) or [])
        if items:
            _title = (f"Kern County Board of Supervisors Agenda {_date} | Bakersfield Daily Brief"
                      if _date else
                      "Kern County Board of Supervisors Agenda | Bakersfield Daily Brief")
            _desc = (f"Kern County Board of Supervisors agenda for {_date or 'the current meeting'}: "
                     f"{len(items)} items"
                     + (f", led by {_top[:70].rstrip(', .;-')}" if _top else "")
                     + (f". {_watched} flagged for Flock/ALPR surveillance" if _watched else "")
                     + ". Item-by-item preview with the official agenda PDF linked.")
        else:
            _title = "Kern County Board of Supervisors Agenda | Bakersfield Daily Brief"
            _desc = ("Kern County Board of Supervisors agenda and meeting details: date, place, "
                     "how agendas are posted under the Brown Act, and the official agenda PDF.")
    else:
        _title = "Kern County Board of Supervisors Agenda | Bakersfield Daily Brief"
        _desc = ("Kern County Board of Supervisors meeting information and the official agenda PDF. "
                 "The county agenda source did not load this build.")

    page = page_mod.render(
        title=_title,
        desc=_desc,
        canonical="/city-hall/county-board/",
        content=body, current="cityhall", rel=rel, built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _county_faq_jsonld(board)])
    return page


def _county_faq_jsonld(board: dict) -> dict:
    """FAQPage schema for the county board page — Q1 carries the live meeting
    date/count so an AI/featured snippet quotes the real current agenda."""
    raw_date = str(board.get("date", ""))
    date_str = raw_date or "TBD"
    items = board.get("items", [])
    watched = board.get("watched", [])
    top = items[0]["title"] if items else ""
    past = _meeting_is_past(raw_date)
    if past:
        q1 = (f"The most recent posted Kern County Board of Supervisors agenda is from "
              f"{date_str or 'a past meeting'}; check the board's page for the next meeting. "
              f"This agenda carries {len(items)} items"
              + (f", led by {top[:80]}" if top else "")
              + (f". {len(watched)} item(s) reference Flock or ALPR surveillance." if watched else "."))
        q3 = (f"The most recent posted agenda ({date_str or 'a past meeting'}) includes "
              f"{len(items)} items."
              + (f" Led by {top[:80]}." if top else ""))
    else:
        q1 = (f"The Kern County Board of Supervisors next meets on {date_str or 'a posted date'} at 9:00 AM "
              f"at the County Administration Building, 1115 Truxtun Avenue, Bakersfield. "
              f"This agenda carries {len(items)} items"
              + (f", led by {top[:80]}" if top else "")
              + (f". {len(watched)} item(s) reference Flock or ALPR surveillance." if watched else "."))
        q3 = (f"The next posted agenda ({date_str}) includes {len(items)} items."
              + (f" Led by {top[:80]}." if top else ""))
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": "When does the Kern County Board of Supervisors meet?",
             "acceptedAnswer": {"@type": "Answer", "text": q1}},
            {"@type": "Question", "name": "How do I see the Kern County Board of Supervisors agenda?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "Agendas are posted 72 hours before each meeting per the Brown Act. This page shows the current posted agenda items; the official agenda PDF is linked above."}},
            {"@type": "Question", "name": "What is on the next Kern County Board of Supervisors agenda?",
             "acceptedAnswer": {"@type": "Answer", "text": q3}},
            {"@type": "Question", "name": "How does Flock / license-plate-reader surveillance get approved in Kern County?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "Flock Safety camera and ALPR proposals come before the Board of Supervisors as agenda items. This page flags those items with an amber 'Flock/ALPR watch' tag."}},
            {"@type": "Question", "name": "Where can I watch or participate in the Kern County Board of Supervisors meeting?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "Meetings are at the Kern County Administration Building, 1115 Truxtun Avenue, Bakersfield. Check the official board page for live-stream and public-comment details."}},
        ],
    }


# ---------------------------------------------------------------- meetings
def _meeting_page(m: dict, built_iso: str, rel: str, ctx) -> str:
    name = m.get("name", "City meeting")
    start_iso = m.get("start_iso", "")
    items = m.get("items", [])
    watched = [i for i in items if _watch(i)]

    # Past meetings: the page used to keep saying "upcoming" forever, and it
    # stays in the sitemap as a permanent agenda record. Say what actually
    # happened instead of implying the meeting is still ahead.
    date_iso = (start_iso or "")[:10]
    is_past = bool(date_iso) and date_iso < built_iso
    if is_past:
        kicker = "City of Bakersfield &middot; meeting held"
        lede = (f"This meeting was held on {date_iso}. The items below are quoted from the "
                f"official agenda as posted; items can be continued, amended, or withdrawn "
                f"at the meeting.")
        page_title = f"{html.escape(name)} — agenda ({date_iso}, meeting held) | Bakersfield Daily Brief"
        page_desc = (f"Agenda for the {html.escape(name)} meeting of the City of Bakersfield on "
                     f"{date_iso}: every posted item, with Flock/ALPR surveillance items flagged.")
        tail_note = (f'<p class="note">This meeting took place on {date_iso}. See the '
                     f'<a href="{rel}city-hall/">meeting calendar</a> for what&rsquo;s next, or '
                     f'<a href="{rel}briefs/">today&rsquo;s brief</a> for coverage.</p>')
        when_label = "Held"
    else:
        kicker = "City of Bakersfield &middot; agenda preview"
        lede = ("Preview of the posted agenda for this upcoming City of Bakersfield public "
                "meeting. Item titles are quoted from the official agenda; agendas can change "
                "before the meeting.")
        page_title = f"{html.escape(name)} — agenda preview | Bakersfield Daily Brief"
        page_desc = (f"Agenda preview for the upcoming {html.escape(name)} meeting of the City of "
                     f"Bakersfield: every posted item, with Flock/ALPR surveillance items flagged.")
        tail_note = ('<p class="note">Meeting location, staff reports, and attachments are on the '
                     'official agenda page. Public comment instructions are published there as '
                     'well.</p>')
        when_label = "Scheduled"

    if items:
        rows = "".join(f"""
        <tr>
          <td class="num">{html.escape(i.get('num', ''))}</td>
          <td>{html.escape(i.get('title', ''))}</td>
          <td>{'<span class="pill amber">Flock/ALPR</span>' if _watch(i) else ''}</td>
        </tr>""" for i in items)
        table = f"""
        <div class="table-wrap"><table class="data">
          <thead><tr><th class="num">No.</th><th>Agenda item</th><th>Watch</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>"""
    else:
        table = '<p class="note">No numbered agenda items were extractable from the agenda page this build.</p>'

    watched_html = ""
    if watched:
        wl = "".join(f"<li>{html.escape(w.get('title', ''))}</li>" for w in watched[:6])
        watched_html = f"""
        <div class="callout"><strong>Surveillance watch:</strong> this agenda includes item(s)
        referencing Flock, ALPR, or license-plate readers:
        <ul style="margin:8px 0 0 18px">{wl}</ul></div>"""

    body = f"""
    <div class="pagehead">
      <nav class="breadcrumbs"><a href="/">Daily Brief</a> &rsaquo;
      <a href="{rel}city-hall/">City Hall &amp; County</a> &rsaquo; {html.escape(name)}</nav>
      <div class="hero"><p class="kicker">{kicker}</p>
      <h1>{html.escape(name)}</h1>
      <p class="lede">{lede}</p>
      <div class="meta"><span>{when_label}: <span class="updated">{html.escape(common.fmt_when(start_iso))}</span></span>
      <span class="dot">&bull;</span><span>{len(items)} agenda items extracted</span></div></div>
    </div>
    <p><a class="pill amber" href="{html.escape(m.get('url', '#'))}">Official agenda ↗</a></p>
    {watched_html}
    {table}
    {tail_note}"""

    page = page_mod.render(
        title=page_title,
        desc=page_desc,
        canonical=f"/city-hall/meetings/{_slug(name, start_iso)}/",
        content=body, current="cityhall", rel=rel, built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    return page


# ---------------------------------------------------------------- hub
def _hub(es: dict, board: dict, meeting_pages: list[dict], built_iso: str, rel: str, ctx) -> str:
    city_cards = ""
    if meeting_pages:
        cards = []
        for m in meeting_pages[:8]:
            href = f"{rel}city-hall/meetings/{m['slug']}/"
            cards.append(f"""
        <a class="card" href="{href}">
          <span class="tag {'amber' if m['watched'] else ('green' if m['items'] else 'grey')}">{'Flock/ALPR flagged' if m['watched'] else ('agenda posted' if m['items'] else 'agenda pending')}</span>
          <h3>{html.escape(m['name'])}</h3>
          <p>{html.escape(common.fmt_when(m.get('start_iso') or ''))} &mdash; {f"{m['items']} agenda items" if m['items'] else 'Agenda not yet posted'}</p>
          <span class="card-go">View agenda preview</span>
        </a>""")
        city_cards = '<div class="grid cols-2">' + "".join(cards) + "</div>"
    else:
        city_cards = ('<p class="note">No upcoming City of Bakersfield meetings with posted '
                      'agendas were found in the next 7 days (or the calendar API is unreachable '
                      'this build).</p>')

    board_items = len(board.get("items", []))
    _bdate = html.escape(str(board.get('date', '')))
    board_line = (f"Most recent posted agenda: {_bdate}, {board_items} items. The next agenda is not "
                  f"posted yet." if _meeting_is_past(board.get('date', '')) else
                  f"Next regular meeting: agenda for {_bdate or 'the upcoming meeting'}, {board_items} items.")
    board_card = f"""
        <a class="card" href="{rel}city-hall/county-board/">
          <span class="tag {'amber' if board.get('watched') else 'green'}">{'Flock/ALPR flagged' if board.get('watched') else 'agenda posted'}</span>
          <h3>Kern County Board of Supervisors</h3>
          <p>{board_line}</p>
          <span class="card-go">View agenda preview</span>
        </a>"""

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">City Hall &amp; County</p>
      <h1>Bakersfield City Council &amp; Kern County Meetings</h1>
      <p class="lede">Upcoming public meetings in Bakersfield and Kern County, with each posted
      agenda previewed item by item. Items about surveillance cameras (Flock license plate
      readers) are flagged.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>Source: the city&rsquo;s online agenda system and the county&rsquo;s posted PDF agendas</span></div></div>
    </div>

    {images.figure("cityhall", rel)}

    <section class="block">
      <div class="sign-head"><span class="tab">City</span><h2>City of Bakersfield</h2></div>
      {city_cards}
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">County</span><h2>Kern County</h2></div>
      <div class="grid cols-2">{board_card}
      <div class="card"><span class="tag">Coming soon</span><h3>School boards</h3>
      <p>Kern High School District and Bakersfield City School District board agendas are not
      covered yet. Until they are, check each district&rsquo;s own website.</p><span class="card-go">Coming soon</span></div>
      </div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">After</span><h2>What They Decided</h2></div>
      <div class="card"><p>Recaps of what each meeting decided are written after the meeting and
      checked by a person before they appear here. None are published yet; until then, each
      meeting&rsquo;s official agenda and minutes are linked above.</p></div>
    </section>"""

    page = page_mod.render(
        title="Bakersfield City Council & Kern County Meeting Agendas | Bakersfield Daily Brief",
        desc="Upcoming Bakersfield City Council, planning commission, and Kern County Board of Supervisors meetings with item-by-item agenda previews and surveillance-item flags.",
        canonical="/city-hall/",
        content=body, current="cityhall", rel=rel, built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    return page


# ---------------------------------------------------------------- drafts
def _recap_drafts(es: dict) -> list[str]:
    """For meetings in the past RECAP_LOOKBACK_DAYS days that have no draft yet,
    write a skeleton recap markdown to drafts/. Returns created filenames."""
    today = common.today_pacific()
    made = []
    try:
        past = escribe.fetch_meetings(today - dt.timedelta(days=RECAP_LOOKBACK_DAYS), today)
    except Exception:  # noqa: BLE001
        return made
    for m in past:
        try:
            s = escribe._parse_start(m["start"])
        except Exception:  # noqa: BLE001
            continue
        slug = _slug(m["name"], m["start"])
        draft_path = common.DRAFTS / f"recap-{slug}.md"
        if draft_path.exists():
            continue
        items = escribe._fetch_agenda(m["id"])
        if items:
            item_lines = "\n".join(
                f"- {i.get('num', '')} {i.get('title', '')}" for i in items[:30])
        else:
            item_lines = (
                "No agenda items are posted on eSCRIBE for this meeting. "
                "Commission agendas are usually published as PDFs at the City's "
                "Agenda Center (https://www.bakersfieldcity.us/AgendaCenter) — "
                "open the meeting's PDF and summarize the items there.")
        content = f"""---
title: "What They Decided — {m['name']}"
meeting: "{m['name']}"
date: "{s.strftime('%Y-%m-%d')}"
meeting_url: "{m['url']}"
status: draft
---

# What They Decided — {m['name']}

**Meeting:** {s.strftime('%A, %B')} {s.day}, {s.year} at {s.strftime('%I:%M %p').lstrip('0')}
**Official agenda:** {m['url']}

> DRAFT — generated automatically from the posted agenda. Verify outcomes
> against the meeting minutes before publishing, then:
> `python scripts/promote_draft.py drafts/recap-{slug}.md`

## Items on the posted agenda

{item_lines}

## What happened

<!-- Fill in per item: approved / denied / continued / direction given, with
     vote counts if available from the minutes. Keep it factual. -->

## Why it matters

<!-- One or two sentences of neutral context. -->

---
_Generated by Bakersfield Daily Brief on {common.iso_today()}. Verify before publishing._
"""
        common.write(draft_path, content)
        made.append(draft_path.name)
    return made


def _watch(item: dict) -> bool:
    hay = (item.get("title", "") + " " + item.get("text", "")).lower()
    return any(w in hay for w in ("flock", "alpr", "license plate reader", "automated license", "surveillance"))


def _slug(name: str, when: str) -> str:
    datepart = re.sub(r"\D", "", (when or ""))[:8]
    base = common.safe_filename(name, 40)
    return f"{base}-{datepart}" if datepart else base
