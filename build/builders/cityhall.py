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
        body = f"""
        <div class="hero"><p class="kicker">County &middot; Kern Board of Supervisors</p>
        <h1>What to Watch</h1>
        <p class="lede">The current Kern County Board of Supervisors agenda, posted for the
        {html.escape(str(board.get('date', '')))} meeting. The board meets in the County
        Administration Building, 1115 Truxtun Avenue, Bakersfield, generally Tuesdays at 9:00 AM.
        Agendas are posted 72 hours ahead per the Brown Act.</p>
        <div class="meta"><span>Agenda posted: <span class="updated">{html.escape(str(board.get('date', '')))}</span></span>
        <span class="dot">&bull;</span><span>Source: official board agenda PDF</span></div></div>
        <p><a class="pill amber" href="https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf">Official agenda PDF ↗</a>
        <a class="pill" href="https://www.kerncounty.com/government/board-of-supervisors">Board page ↗</a></p>
        {table}
        <div class="callout"><strong>Surveillance watch:</strong> items mentioning Flock, ALPR, or license-plate
        readers are flagged amber. The Board&rsquo;s consent calendar is also captured when present.</div>"""
    else:
        body = ('<div class="hero"><h1>County Board agenda</h1>'
                f'<div class="errorbox">The county agenda PDF could not be fetched this build ({html.escape(board.get("error", "unknown"))}).</div></div>')

    page = page_mod.render(
        title="Kern County Board of Supervisors — What to Watch | Bakersfield Daily Brief",
        desc="Current Kern County Board of Supervisors agenda with item-by-item previews: resolutions, departmental requests, consent items, and Flock/ALPR surveillance items flagged.",
        canonical="/city-hall/county-board/",
        content=body, current="cityhall", rel=rel, built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    return page


# ---------------------------------------------------------------- meetings
def _meeting_page(m: dict, built_iso: str, rel: str, ctx) -> str:
    name = m.get("name", "City meeting")
    start_iso = m.get("start_iso", "")
    items = m.get("items", [])
    watched = [i for i in items if _watch(i)]

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
      <nav class="breadcrumbs"><a href="{rel}index.html">Daily Brief</a> &rsaquo;
      <a href="{rel}city-hall/">City Hall &amp; County</a> &rsaquo; {html.escape(name)}</nav>
      <div class="hero"><p class="kicker">City of Bakersfield &middot; agenda preview</p>
      <h1>{html.escape(name)}</h1>
      <p class="lede">Preview of the posted agenda for this upcoming City of Bakersfield public
      meeting. Item titles are quoted from the official agenda; agendas can change before
      the meeting.</p>
      <div class="meta"><span>Scheduled: <span class="updated">{html.escape(start_iso.replace('T', ' · '))}</span></span>
      <span class="dot">&bull;</span><span>{len(items)} agenda items extracted</span></div></div>
    </div>
    <p><a class="pill amber" href="{html.escape(m.get('url', '#'))}">Official agenda ↗</a></p>
    {watched_html}
    {table}
    <p class="note">Meeting location, staff reports, and attachments are on the official agenda page.
    Public comment instructions are published there as well.</p>"""

    page = page_mod.render(
        title=f"{html.escape(name)} — agenda preview | Bakersfield Daily Brief",
        desc=f"Agenda preview for the upcoming {html.escape(name)} meeting of the City of Bakersfield: every posted item, with Flock/ALPR surveillance items flagged.",
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
          <span class="tag {'amber' if m['watched'] else 'green'}">{'Flock/ALPR flagged' if m['watched'] else 'agenda posted'}</span>
          <h3>{html.escape(m['name'])}</h3>
          <p>{html.escape((m.get('start_iso') or '').replace('T', ' · '))} &mdash; {m['items']} agenda items</p>
          <span class="card-go">View agenda preview</span>
        </a>""")
        city_cards = '<div class="grid cols-2">' + "".join(cards) + "</div>"
    else:
        city_cards = ('<p class="note">No upcoming City of Bakersfield meetings with posted '
                      'agendas were found in the next 7 days (or the calendar API is unreachable '
                      'this build).</p>')

    board_items = len(board.get("items", []))
    board_card = f"""
        <a class="card" href="{rel}city-hall/county-board/">
          <span class="tag {'amber' if board.get('watched') else 'green'}">{'Flock/ALPR flagged' if board.get('watched') else 'agenda posted'}</span>
          <h3>Kern County Board of Supervisors</h3>
          <p>Next regular meeting &mdash; agenda for {html.escape(str(board.get('date', 'the upcoming meeting')))}: {board_items} items extracted.</p>
          <span class="card-go">View agenda preview</span>
        </a>"""

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">City Hall &amp; County</p>
      <h1>What to Watch</h1>
      <p class="lede">Upcoming public meetings in Bakersfield and Kern County, with posted agendas
      previewed item by item. We flag items that touch surveillance systems (Flock / ALPR) and
      publish post-meeting recaps as review drafts.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>City agendas via eSCRIBE &middot; county via official PDF</span></div></div>
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
      <p>KHSD and BCSD agenda feeds are stubbed &mdash; their portals block automated access from
      datacenter IPs; a home-runner migration is planned.</p><span class="card-go">On the roadmap</span></div>
      </div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">After</span><h2>What They Decided</h2></div>
      <div class="card"><p>Post-meeting recaps are generated as <strong>review drafts</strong> in the
      repo (<code>drafts/</code>) &mdash; they are never auto-published. A recap appears there after a
      meeting date passes; we review, edit, and promote it to the site with
      <code>python scripts/promote_draft.py drafts/recap-&lt;slug&gt;.md</code>.</p></div>
    </section>"""

    page = page_mod.render(
        title="City Hall & County — What to Watch | Bakersfield Daily Brief",
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
        item_lines = "\n".join(f"- {i.get('num', '')} {i.get('title', '')}" for i in items[:30])
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
