#!/usr/bin/env python3
"""The Daily Brief (homepage, index.html) — Tucson-style editorial layout v2.

  date/location line → TODAY'S BRIEF hero (top story + numbered sidebar)
  → Conditions strip → The News (keyless digest) → One Thing to Watch
  → "Latest across Bakersfield" 4-category grid
  → "The week at a glance" Mon–Fri calendar
  → "Recent daily briefs" archive (each build saves a permanent copy)

All content baked at build time. Headlines link out only — never republished text.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path

from .. import common, llm
from ..sources.airnow import css_class as _aqi_css
from . import images
from . import page as page_mod
SUN_ICON = """<svg class="sun-sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
  <circle cx="12" cy="12" r="6" fill="#DC9A1F"/>
  <g stroke="#DC9A1F" stroke-width="2" stroke-linecap="round">
    <line x1="12" y1="1" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="23"/>
    <line x1="1" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="23" y2="12"/>
    <line x1="4.2" y1="4.2" x2="6.3" y2="6.3"/><line x1="17.7" y1="17.7" x2="19.8" y2="19.8"/>
    <line x1="4.2" y1="19.8" x2="6.3" y2="17.7"/><line x1="17.7" y1="6.3" x2="19.8" y2="4.2"/>
  </g>
</svg>"""


def build(ctx, sources: dict) -> list[str]:
    built = []
    today = ctx.today
    built_iso = common.iso_today()

    news = sources.get("news_rss", {})
    weather = sources.get("weather", {})
    chp = sources.get("chp", {})
    isa = sources.get("isabella", {})
    escribe = sources.get("escribe", {})
    board = sources.get("kern_board", {})
    abc = sources.get("abc", {})
    food = sources.get("food", {})
    alpr = sources.get("alpr", {})
    airnow = sources.get("airnow", {})
    calfire = sources.get("calfire", {})

    headlines = news.get("headlines", [])
    top = headlines[0] if headlines else None
    # The 6am build writes the brief body once and caches it; later builds reuse that body. The
    # headline must be the story that body was written about, not whatever leads the feed three
    # hours later (2026-09-22: a fire headline over a body about oil permits).
    pinned = _cached_brief_top(today)
    if pinned and pinned.get("title"):
        top = next((h for h in headlines if h.get("title") == pinned["title"]), pinned)

    rel = ""
    content = _page_content(ctx, today, built_iso, rel,
                            news, weather, chp, isa, escribe, board,
                            abc, food, alpr, airnow, calfire, headlines, top,
                            sources.get("venues", {}).get("events", []))

    jsonld = [
        page_mod.org_jsonld(),
        page_mod.website_jsonld(),
        {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": _brief_h1(today),
            "datePublished": built_iso,
            "dateModified": built_iso,
            "isAccessibleForFree": True,
            "publisher": {
                "@type": "NewsMediaOrganization",
                "name": "Bakersfield Daily Brief",
                "url": "https://bakersfieldbrief.com/",
                "logo": page_mod.publisher_logo(),
            },
            "mainEntityOfPage": "https://bakersfieldbrief.com/",
        },
    ]

    page = page_mod.render(
        title=_big_title(top, today),
        desc="The daily civic brief for Bakersfield and Kern County: live weather, conditions, local news headlines with links, the week at a glance, and one public-meeting item to watch. Updated every morning at 6 AM PT.",
        canonical="/",
        content=content,
        current="index",
        rel="",
        built=built_iso,
        jsonld=jsonld,
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
    )
    common.write(common.SITE / "index.html", page)
    built.append("index.html")

    # ---- permanent archive copy + archive page ----
    archive_built = _archive(ctx, today, built_iso, top, news, weather, chp, isa,
                             escribe, board, abc, food, alpr, airnow, calfire,
                             headlines, sources.get("venues", {}).get("events", []))
    built.extend(archive_built)

    # ---- email renderings (same data → email-safe HTML + plain text)
    try:
        from ..emailer import render_brief
        built.extend(render_brief(ctx, sources, today))
        ctx.build_report.setdefault("daily", {})["email"] = "rendered"
    except Exception as e:  # noqa: BLE001
        common.log(f"email render failed: {type(e).__name__}: {e}")

    ctx.build_report["daily"] = {
        "news_headlines": len(headlines),
        "news_digest": ctx.build_report.get("_digest_meta", "deterministic"),
        "alerts": weather.get("count", 0),
        "chp_new": len(chp.get("new", [])),
        "top_story": top["title"] if top else None,
        "archive": built_iso,
    }
    return built


# ================================================================ page body
def _page_content(ctx, today, built_iso, rel, news, weather, chp, isa,
                  escribe, board, abc, food, alpr, airnow, calfire, headlines, top,
                  events=None) -> str:
    date_line = f"""
    <div class="date-line"><span>{today.strftime('%B').upper()} {today.day}, {today.year}</span><span>Bakersfield, California</span></div>"""

    hero, sidebar = _hero_row(top, headlines, today, rel, built_iso,
                              weather, airnow, calfire, escribe, events)

    digest_html, digest_meta = _news(news, built_iso)
    ctx.build_report["_digest_meta"] = digest_meta
    conditions = _conditions(weather, chp, isa, airnow, calfire, built_iso, rel)
    watch = _one_thing(escribe, board)

    cats = _category_grid(rel, escribe, board, abc, food, alpr, calfire)
    week = _week_grid(today, rel, weather, escribe, board, top)
    archive_html = _recent_briefs(rel)

    return f"""{date_line}
    <div class="brief-top">
      <div class="hero-col">
        {hero}
        {_overnight_section(rel)}
      </div>
      <aside class="sidebar-col">{sidebar}</aside>
    </div>

    {images.figure("bakersfield", rel)}

    <div class="ad-slot" data-ad-slot="home-hero" aria-hidden="true"></div>

    {_newsletter_block()}

    {conditions}

    <section class="card" style="margin:14px 0" aria-labelledby="h-fair">
      <p class="sec-head" id="h-fair">Kern County Fair 2026 <span class="unit">Sept 23 &ndash; Oct 4 &middot; Bakersfield</span></p>
      <div class="ko-inner">
        <div class="ko-main">
          <h3 class="ko-title"><a href="{rel}fair/">Fair dates, concert lineup &amp; tickets</a></h3>
          <p class="ko-text">The 2026 Kern County Fair runs Sept 23 &ndash; Oct 4 &mdash; twelve nights of headline concerts at the Budweiser Pavilion, PRCA rodeo, monster trucks, carnival, and more.</p>
        </div>
        <div class="ko-cta">
          <a class="btn-red" href="{rel}fair/">See the fair guide</a>
        </div>
      </div>
    </section>

    <section aria-labelledby="h-news" id="the-news">
      <p class="sec-head" id="h-news">The News <span class="unit">headlines + links, synthesized</span></p>
      {digest_html}
    </section>
    {watch}

    <section aria-labelledby="h-cats">
      <p class="sec-head" id="h-cats">Latest across Bakersfield <span class="unit">meetings · records · data</span></p>
      {cats}
    </section>

    <section aria-labelledby="h-week">
      <p class="sec-head" id="h-week">The week at a glance <span class="unit">{_week_label(today)}</span></p>
      {week}
    </section>

    <section aria-labelledby="h-archive">
      <p class="sec-head" id="h-archive">Recent daily briefs <span class="unit">archived every morning</span></p>
      {archive_html}
    </section>

    {_footnote()}"""


# ---------------------------------------------------------------- overnight
def _short_area(area: str) -> str:
    """Compress a generalized area for titles: 'the 2100 block of Niles Street'
    → '2100 block Niles St'; 'Williams Street at Eureka Street, East Bakersfield'
    → 'Williams St at Eureka St'."""
    if not area:
        return "the area"
    a = re.sub(r"\bthe\b|\bof\b", " ", area)
    for long, short in (("Street", "St"), ("Avenue", "Ave"), ("Road", "Rd"),
                        ("Drive", "Dr"), ("Highway", "Hwy"), ("Lane", "Ln"),
                        ("Boulevard", "Blvd")):
        a = a.replace(long, short)
    a = " ".join(a.split())
    a = a.split(",")[0]
    return a[:44]


_INCIDENT_CAT = {
    "dui": "traffic", "hit and run": "traffic", "hit_and_run": "traffic",
    "traffic collision": "traffic", "traffic enforcement": "traffic",
    "traffic_enforcement": "traffic", "vehicle vs pedestrian": "traffic",
    "vehicle_vs_pedestrian": "traffic", "road rage": "police",
    "road_rage": "police", "stolen vehicle": "police", "stolen_vehicle": "police",
    "theft": "police", "welfare check": "police", "welfare_check": "police",
    "welfare call": "police", "burglary": "police",
    "suspicious person report": "police", "suspicious_person_report": "police",
    "assault report": "police", "assault_report": "police",
    "domestic call": "police", "domestic_call": "police", "shooting": "police",
    "fire alarm": "fire", "fire_alarm": "fire", "structure fire": "fire",
    "structure_fire": "fire", "vehicle fire": "fire", "vehicle_fire": "fire",
    "grass fire": "fire", "grass_fire": "fire", "outside fire": "fire",
    "outside_fire": "fire", "electrical fire": "fire", "electrical_fire": "fire",
    "commercial fire alarm": "fire", "medical aid": "medical",
    "medical_aid": "medical", "man down": "medical", "man_down": "medical",
    "mental health crisis": "medical", "mental_health_crisis": "medical",
}


def _incident_cat(typ) -> str:
    """Rich incident-type → category mapping (the brief's ko line was
    collapsing everything to 'other' via the thin map-feed CATEGORY)."""
    from .map import CATEGORY
    t = str(typ or "").lower().strip()
    if t in _INCIDENT_CAT:
        return _INCIDENT_CAT[t]
    if "_" in t:
        t2 = t.replace("_", " ")
        if t2 in _INCIDENT_CAT:
            return _INCIDENT_CAT[t2]
    return CATEGORY.get(t, "other")


# Human-readable labels for raw incident type tokens (underscore -> words,
# abbreviations kept uppercase, common phrasing cleaned). Anything not in
# this map falls back to underscore->space + Title Case in _type_label().
_TYPE_LABEL = {
    "working_fire": "working fire",
    "medical_aid": "medical aid",
    "traffic_collision": "traffic collision",
    "hit_and_run": "hit-and-run",
    "vehicle_vs_pedestrian": "vehicle vs. pedestrian",
    "vehicle_vs_bicyclist": "vehicle vs. bicyclist",
    "vehicle_into_building": "vehicle into a building",
    "vehicle_into_pole": "vehicle into a pole",
    "vehicle_rollover": "vehicle rollover",
    "vehicle_pursuit": "vehicle pursuit",
    "foot_pursuit": "foot pursuit",
    "welfare_check": "welfare check",
    "suspicious_person": "suspicious person",
    "suspicious_person_report": "suspicious person report",
    "suspicious_circumstances": "suspicious circumstances",
    "suspicious_circumstance": "suspicious circumstances",
    "suspicious_vehicle": "suspicious vehicle",
    "domestic_disturbance": "domestic disturbance",
    "domestic_violence": "domestic violence",
    "family_disturbance": "family disturbance",
    "physical_disturbance": "physical disturbance",
    "juvenile_disturbance": "juvenile disturbance",
    "verbal_disturbance": "verbal disturbance",
    "shots_fired": "shots fired",
    "brandishing_firearm": "brandishing a firearm",
    "firearms_incident": "firearms incident",
    "weapons_offense": "weapons offense",
    "armed_robbery": "armed robbery",
    "armed_subject": "armed subject",
    "reckless_driver": "reckless driver",
    "street_racing": "street racing",
    "hazardous_condition": "hazardous condition",
    "roadway_hazard": "roadway hazard",
    "traffic_incident": "traffic incident",
    "traffic_enforcement": "traffic enforcement",
    "assault_with_deadly_weapon": "assault with a deadly weapon",
    "assault_with_a_weapon": "assault with a weapon",
    "stolen_vehicle": "stolen vehicle",
    "stolen_firearms_search": "stolen-firearms search",
    "runaway_juvenile": "runaway juvenile",
    "suicidal_subject": "suicidal subject",
    "mental_health_crisis": "mental health crisis",
    "mental_health": "mental health call",
    "mental_health_hold": "mental health hold",
    "fire_cause_investigation": "fire-cause investigation",
    "commercial_fire_alarm": "commercial fire alarm",
    "commercial_alarm": "commercial alarm",
    "medical_alarm": "medical alarm",
    "juvenile_nuisance": "juvenile nuisance",
    "dui_driver": "DUI driver",
    "dui_report": "DUI report",
    "probation_check": "probation check",
    "warrant_service": "warrant service",
    "felony_warrant": "felony warrant",
    "repo_assist": "repo assist",
    "officer_assist": "officer assist",
    "burglary_in_progress": "burglary in progress",
    "theft_in_progress": "theft in progress",
    "train_vs_pedestrian": "train vs. pedestrian",
    "vehicle_fire_check": "vehicle fire check",
    "fire_response": "fire response",
    "small_fire": "small fire",
    "camp_fire": "camp fire",
    "attempted_arson": "attempted arson",
    "brush_fire": "brush fire",
    "vegetation_fire": "vegetation fire",
    "grass_fire": "grass fire",
    "outside_fire": "outside fire",
    "structure_fire": "structure fire",
    "vehicle_fire": "vehicle fire",
    "electrical_fire": "electrical fire",
}


def _type_label(typ) -> str:
    """Raw incident type token → a clean, human-readable label.

    'working_fire' → 'Working fire'; 'dui' → 'DUI'; anything unseen falls
    back to underscore→space + Title Case. Used by the overnight headline
    so raw tokens like 'working_fire' never leak into the email.
    """
    t = str(typ or "incident").strip().lower()
    if t in _TYPE_LABEL:
        return _TYPE_LABEL[t].strip().capitalize()
    # fallback: dui -> DUI, vehicle_vs_pedestrian -> Vehicle vs pedestrian
    words = t.replace("_", " ").split()
    out = []
    for w in words:
        w = w.strip()
        if w in ("dui", "ems", "chp", "bpd", "kcsd"):
            out.append(w.upper())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _overnight_summary() -> dict | None:
    """Latest Kern Overnight data → {date, title, headline, count, cats, top}.

    Reads the published reports + the append-only incidents dataset; the
    headline feeds the brief title and the section summary."""
    try:
        from .overnight import _published_reports
        reps = _published_reports()
        if not reps:
            return None
        rep = reps[0]
        incs: list[dict] = []
        f = Path("incidents") / f"{rep['date']}.json"
        if f.exists():
            try:
                incs = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                incs = []
        cats = {"fire": 0, "police": 0, "medical": 0, "traffic": 0, "other": 0}
        for i in incs:
            cats[_incident_cat(i.get("type", ""))] += 1
        top = max(incs, key=lambda i: i.get("notability", 0)) if incs else None
        headline = None
        if top:
            # Human label, never the raw token: 'working_fire' would leak
            # straight into the email title/card. Keep the report's own
            # natural phrasing when it already reads like a sentence.
            label = _type_label(top.get("type", "incident"))
            area = _short_area(top.get("area", ""))
            headline = f"{label} at {area}" if area and area != "the area" else label
        return {"date": rep["date"], "title": rep["title"],
                "headline": headline, "count": len(incs), "cats": cats,
                "top": top, "incs": incs}
    except Exception:  # noqa: BLE001
        return None


_HOOD_PREP = {"east side": "on the east side", "west side": "on the west side",
              "downtown": "downtown", "north bakersfield": "in north Bakersfield",
              "south bakersfield": "in south Bakersfield", "oildale": "in Oildale",
              "rosedale": "in Rosedale", "on the highway": "on the highway"}


def _hood(area: str) -> str | None:
    """Neighborhood-level area for rundown lines — never street names."""
    a = (area or "").lower()
    for key, out in (("east", "east side"), ("downtown", "downtown"),
                     ("oildale", "Oildale"), ("rosedale", "Rosedale"),
                     ("north", "north Bakersfield"), ("south", "south Bakersfield"),
                     ("west", "west side"), ("99", "on the highway"),
                     ("highway", "on the highway")):
        if key in a:
            return out
    return None


_TYPE_NORM = {
    "commercial fire": "structure fire", "structure fire report": "structure fire",
    "reported shooting": "shooting", "vehicle collision": "traffic collision",
    "domestic violence with injury": "domestic call", "domestic": "domestic call",
    "attempted burglary": "burglary attempt", "mental health hold": "welfare call",
    "welfare check": "welfare call", "suspicious person": "suspicious person report",
    "assault report involving a child": "assault report",
}
_PLURALS = {"mental health crisis": "mental health crises",
            "assault with a weapon": "assaults with weapons"}


def _plural(typ: str) -> str:
    return _PLURALS.get(typ, typ + "s")


def _overnight_rundown() -> str | None:
    """One professional rundown sentence, neighborhood-level only:
    '3 structure fires on the east side, a shooting downtown, a traffic
    collision, and 8 more — 16 incidents total.'"""
    ko = _overnight_summary()
    if not ko or not ko.get("incs"):
        return None
    from collections import Counter
    type_counts: Counter = Counter()
    hood_for: dict[str, Counter] = {}
    for i in ko["incs"]:
        typ = _TYPE_NORM.get(str(i.get("type", "incident")).lower(),
                             str(i.get("type", "incident")).lower())
        type_counts[typ] += 1
        h = _hood(i.get("area", ""))
        if h:
            hood_for.setdefault(typ, Counter())[h] += 1
    top3 = type_counts.most_common(3)
    parts = []
    for typ, n in top3:
        hc = hood_for.get(typ)
        where = _HOOD_PREP.get(hc.most_common(1)[0][0]) if hc else ""
        if n > 1:
            parts.append(f"{n} {_plural(typ)}{(' ' + where) if where else ''}")
        else:
            parts.append(f"a {typ}{(' ' + where) if where else ''}")
    s = ", ".join(parts)
    rest = ko["count"] - sum(n for _, n in top3)
    if rest > 0:
        s += f", and {rest} more"
    return f"{s} — {ko['count']} incidents total"


def _transcription_note() -> str:
    """Small italic note on the brief page: how the scanner report is made."""
    return (
        '<p class="trans-note">How the Kern Overnight report is made: archived '
        'public-safety radio audio is transcribed to text by a speech-to-text '
        'model, and the morning report is written from that dispatch log. '
        'Locations are generalized to block or cross streets, and every detail '
        'is preliminary until confirmed by an official source.</p>')


def _big_title(top, today) -> str:
    """Own-brand title — the site is the entity, never a syndicated
    headline. The hero still shows the top story; the <title>/og:title/
    schema say who we are."""
    return f"Bakersfield News Today, {_fmt_date(today)} | Bakersfield Daily Brief"


def _overnight_section(rel: str) -> str:
    """Significant homepage section for The Kern Overnight (traffic driver)."""
    ko = _overnight_summary()
    if not ko:
        return """
    <section aria-labelledby="h-overnight" class="card" style="margin:14px 0">
      <p class="sec-head" id="h-overnight">The Kern Overnight <span class="unit">listened overnight &middot; written by sunrise</span></p>
      <p>First edition coming soon. <a href="%s">About the scanner-to-newsletter report</a></p>
    </section>""" % rel
    rundown = _overnight_rundown() or f"{ko['count']} incidents tracked overnight"
    cats = " &middot; ".join(f"{n} {c}" for c, n in ko["cats"].items() if n)
    return f"""
    <section class="ko-section" aria-labelledby="h-overnight">
      <p class="sec-head" id="h-overnight">The Kern Overnight <span class="unit">listened overnight &middot; written by sunrise</span></p>
      <div class="ko-inner">
        <div class="ko-main">
          <h3 class="ko-title"><a href="{rel}overnight/">{html.escape(ko['title'])}</a></h3>
          <p class="ko-text">{html.escape(rundown)}.</p>
          <p class="ko-cats">{cats}</p>
          <p class="ko-friend">Slept through the night? Here&rsquo;s what you missed while the city talked.</p>
        </div>
        <div class="ko-cta">
          <a class="btn-red" href="{rel}overnight/">See what happened overnight</a>
          <a class="btn btn-ghost" href="{rel}overnight/archive/">Browse the archive</a>
          <a class="btn btn-ghost" href="{rel}map/">Live map</a>
        </div>
      </div>
    </section>"""


# ---------------------------------------------------------------- newsletter
def _newsletter_block() -> str:
    """Newsletter capture with a professional thank-you modal.

    The form posts to the Cloudflare Pages Function (/api/newsletter), which
    adds the email to the MailerLite group server-side (the API token lives
    in Pages env vars — never in the browser). main.js intercepts the submit
    (XHR, no navigation) and shows the in-page thank-you card; the action is
    the no-JS fallback.
    """
    form = ('<form class="nl-form" id="nl-form" '
            'action="/api/newsletter" method="POST">'
            '<input type="email" name="email" placeholder="your@email.com" required '
            'aria-label="Your email"/>'
            '<button type="submit" class="btn">Get the brief</button></form>')
    # The thank-you modal: shown by main.js when the newsletter form submits.
    modal = """
    <div class="nl-modal" id="nl-modal" role="dialog" aria-modal="true" aria-labelledby="nl-modal-title" aria-hidden="true">
      <div class="nl-card">
        <button type="button" class="nl-card-close" data-nl-close aria-label="Close">×</button>
        <div class="nl-card-bar"></div>
        <div class="nl-card-body">
          <div class="nl-card-check" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="#DC9A1F" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </div>
          <h3 id="nl-modal-title">You&rsquo;re on the list</h3>
          <p class="nl-card-sub">Thanks for subscribing to the Bakersfield Daily Brief. Here&rsquo;s what lands in your inbox every morning:</p>
          <ul class="nl-card-list">
            <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" stroke="#DC9A1F" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span><strong>The Overnight</strong> — our morning brief of police scanner activity that occurred overnight while you slept.</span></li>
            <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" stroke="#DC9A1F" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span><strong>Today&rsquo;s weather &amp; conditions</strong> &mdash; high, low, air quality, alerts, fires.</span></li>
            <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" stroke="#DC9A1F" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span><strong>Top stories &amp; what&rsquo;s coming up</strong> &mdash; the news shaping Kern County, plus meetings and events.</span></li>
            <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" stroke="#DC9A1F" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span><strong>Free, always</strong> &mdash; no spam, no paywall. Unsubscribe any time.</span></li>
          </ul>
          <button type="button" class="btn" data-nl-close>Close</button>
          <p class="nl-card-foot">See you tomorrow morning.</p>
        </div>
      </div>
    </div>"""
    return f"""
    <section class="nl-block" aria-label="Newsletter">
      <div class="nl-text"><p class="nl-kicker">The Brief by email</p>
      <p class="nl-pitch">The day&rsquo;s news, conditions, and what&rsquo;s coming up — one clean email, every morning. <em>Free.</em> Also on <a href="https://www.facebook.com/bakersfieldbrief" rel="noopener" target="_blank">Facebook</a> — follow for the daily reel.</p></div>
      {form}
    </section>
    {modal}"""


# ---------------------------------------------------------------- hero row
def _hero_row(top, headlines, today, rel, built_iso,
              weather=None, airnow=None, calfire=None, escribe=None,
              events=None) -> tuple[str, str]:
    if top:
        head = f'<a href="{html.escape(top.get("url", "#"))}" rel="noopener">{html.escape(top["title"])}</a>'
        src = f'<span class="hero-src">via {html.escape(top.get("source", "local news"))}</span>'
    else:
        head = "The Kern County news you\u2019d otherwise miss"
        src = ""

    summary = _quick_summary(top, headlines, weather, airnow, calfire,
                             escribe, events, rel, today)
    hero = f"""
    <p class="today-label">{SUN_ICON} Today&rsquo;s Brief</p>
    <h1 class="today-h1">Bakersfield Daily Brief: {html.escape(_fmt_date(today))}</h1>
    <p class="hero-topstory">Top story: {head} {src}</p>
    <p class="lede">{summary}</p>
    <a class="read-more" href="{rel}briefs/">Read today&rsquo;s full brief</a>"""

    # numbered sidebar (top 4)
    top4 = headlines[:4]
    if top4:
        lis = "".join(f"""
        <li><a href="{html.escape(h.get('url', '#'))}" rel="noopener">{html.escape(h['title'])}</a>
        <span class="n-src">{html.escape(h.get('source', 'news'))}</span></li>""" for h in top4)
        sidebar = f"""<div class="side-box"><h2>This Morning in Kern County</h2>
        <ol class="numlist">{lis}</ol></div>"""
    else:
        sidebar = '<div class="side-box"><h2>This Morning in Kern County</h2><p class="note">No headlines fetched this build.</p></div>'

    return hero, sidebar


def _quick_summary(top, headlines, weather, airnow, calfire,
                   escribe, events, rel, today) -> str:
    """2–3 sentence deterministic day-summary for the hero (keyless)."""
    bits = []
    if top:
        bits.append('The morning read for Kern County')
    others = len(headlines) - 1 if headlines else 0
    if others > 0:
        bits.append(f"{others} more {'story' if others == 1 else 'stories'} across Kern County are below")

    cond = []
    alerts = (weather or {}).get("alerts", [])
    if alerts:
        cond.append(f'a <strong>{html.escape(alerts[0].get("event", "weather alert"))}</strong> is active')
    if airnow and airnow.get("ok") and airnow.get("aqi") is not None:
        cond.append(f'air quality at {airnow["aqi"]} ({html.escape((airnow.get("category") or "").lower())})')
    kern = [f for f in (calfire or {}).get("incidents", []) if "Kern" in str(f.get("county", ""))]
    if kern:
        cond.append(f"{len(kern)} active {'fire' if len(kern) == 1 else 'fires'} in Kern County")
    if cond:
        bits.append("conditions: " + "; ".join(cond))

    nxt = []
    for m in (escribe or {}).get("upcoming", []) or []:
        if (m.get("start_iso") or "")[:10] >= today.isoformat():
            nxt.append(f'<a href="{html.escape(m.get("url", rel + "city-hall/"))}" rel="noopener">{html.escape(m.get("name", "a public meeting"))}</a>')
            break
    for e in events or []:
        from .events import _when_date
        d = _when_date(e, today)
        if d and d >= today:
            nxt.append(f'<a href="{html.escape(e.get("url", "#"))}" rel="noopener">{html.escape(e.get("name", "an event"))}</a>')
            break
    if nxt:
        bits.append("coming up: " + " · ".join(nxt[:2]))

    summary = ". ".join(bits) + "."
    return summary or "The day&rsquo;s news from Bakersfield, Kern County, and beyond."


# ---------------------------------------------------------------- conditions
def _conditions(weather, chp, isa, airnow, calfire, built_iso, rel="") -> str:
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    if cur is not None and hi is not None:
        weather_v = f"{cur}&deg; now &middot; high {hi}&deg;"
    elif hi is not None and lo is not None:
        weather_v = f"high {hi}&deg; &middot; low {lo}&deg;"
    else:
        weather_v = "n/a"
    alerts = (weather or {}).get("alerts", [])
    alert_v = (alerts[0]["event"] + " active" if alerts else
               "No active alerts" if (weather or {}).get("ok") else "Unavailable")
    isa_last = isa.get("last")
    isa_v = f"{isa_last['value']:,} acre-feet" if isa_last else "n/a"
    isa_pct = isa.get("pct")
    chp_night = chp.get("overnight", [])
    chp_v = ("Unavailable" if not chp.get("ok") else
             f"{len(chp_night)} overnight" if chp_night else "None overnight")

    # AQI chip: real value when the key is set; honest states otherwise
    if airnow.get("ok") and airnow.get("aqi") is not None:
        cls = _aqi_css(airnow.get("category_num"))
        aqi_v = (f'<span class="{cls}">{airnow["aqi"]} &middot; {html.escape(airnow.get("category") or "")}'
                 f'</span> <span class="unit">{html.escape(airnow.get("parameter") or "")}</span>')
    elif airnow.get("needs_key"):
        aqi_v = 'Waiting for EPA AirNow key'
    else:
        aqi_v = 'Unavailable this build'

    # Active fires chip (CAL FIRE; Kern-filtered)
    kern_fires = [f for f in calfire.get("incidents", []) if "Kern" in str(f.get("county", ""))]
    if calfire.get("ok"):
        fire_v = f'{len(kern_fires)} in Kern' if kern_fires else '0 in Kern'
    else:
        fire_v = 'Unavailable'

    # every chip links to the live source that updates it (external → new tab)
    def chip(url: str, inner: str, external: bool = True) -> str:
        tgt = ' target="_blank" rel="noopener"' if external else ""
        return f'<a class="cond-chip" href="{url}"{tgt}>{inner}</a>'

    weather_html = chip(
        "https://forecast.weather.gov/MapClick.php?lat=35.3733&lon=-119.0187",
        f'<div class="l">Bakersfield weather</div><div class="v">{weather_v}</div>')
    alert_html = chip(
        "https://www.weather.gov/hnx/",
        f'<div class="l">Weather alerts</div><div class="v {"amber" if alerts else ""}">{html.escape(alert_v)}</div>')
    isa_html = chip(
        f"{rel}water/",
        f'<div class="l">Lake Isabella</div><div class="v">{isa_v} <span style="font-size:13px;color:#57504A">({isa_pct}% full)</span></div>',
        external=False)
    chp_html = chip(
        "https://quickmap.dot.ca.gov/",
        f'<div class="l">CHP overnight</div><div class="v">{chp_v}</div>')
    aqi_html = chip(
        "https://www.airnow.gov/?city=Bakersfield&state=CA&country=USA",
        f'<div class="l">Air quality (AQI)</div><div class="v">{aqi_v}</div>')
    fire_html = chip(
        "https://www.fire.ca.gov/incidents/",
        f'<div class="l">Active fires</div><div class="v">{fire_v}</div>')

    return f"""
    <section aria-labelledby="h-conditions">
      <p class="sec-head" id="h-conditions">Conditions <span class="unit">weather · reservoir · incidents · air · fires</span></p>
      <div class="cond-strip">
        {weather_html}
        {alert_html}
        {isa_html}
        {chp_html}
        {aqi_html}
        {fire_html}
      </div>
      <p class="note" style="margin-top:10px">Each block links to the live source: National Weather Service &middot; CA DWR/CDEC &middot; Caltrans QuickMap (CHP incidents) &middot;
      EPA AirNow &middot; CAL FIRE. Data refreshed each build.</p>
    </section>"""


# ---------------------------------------------------------------- the news
_DIGEST_CACHE = {}


def _get_digest(headlines: list[dict]) -> str | None:
    """LLM news digest, computed at most once per build (homepage + article
    both render it; we never pay for the same summarization twice)."""
    key = tuple(h.get("title", "") for h in headlines[:14])
    if key not in _DIGEST_CACHE:
        _DIGEST_CACHE[key] = llm.summarize_news(headlines[:14]) if headlines else None
    return _DIGEST_CACHE[key]


def _news(news: dict, built_iso: str) -> tuple[str, str]:
    headlines = news.get("headlines", [])
    digest = _get_digest(headlines)
    if digest:
        # model text is text: escape it, and keep its paragraph breaks
        digest_html = "<div class='card'>" + "".join(
            f"<p>{html.escape(p.strip())}</p>" for p in re.split(r"\n\s*\n", digest) if p.strip()) + "</div>"
        meta = "llm"
    else:
        # Always-on path: topic-grouped headline cards — scannable, keyless.
        digest_html = _news_groups(headlines)
        meta = "deterministic" if headlines else "no-headlines"

    return f"""
      {digest_html}""", meta


_TOPIC_BUCKETS = [
    ("Public safety & courts",
     ("police", "deputy", "shooting", "arrest", "crash", "collision", "court", "jury",
      "trial", "suspect", "dui", "drunk", "gun", "fire", "search", "missing", "coroner",
      "sword", "lawsuit", "federal", "jail", "sentence")),
    ("City & county government",
     ("council", "county", "board", "commission", "agenda", "policy", "ordinance",
      "permit", "budget", "supervisor", "planning", "city of", "school district",
      "measure", "department", "compliance")),
    ("Community & events",
     ("fair", "festival", "school", "drive", "health fair", "collector", "marathon",
      "film", "cooling center", "library", "museum", "event", "forum", "foster",
      "care center", "mammogram", "karate", "volunteer", "fundrais")),
    ("Business & economy",
     ("business", "store", "market", "jobs", "company", "solar", "lottery", "powerball",
      "price", "sale", "supermarket", "opening", "economy", "housing")),
    ("Weather & environment",
     ("heat", "cooling", "water", "valley fever", "air", "wildfire", "firefighters",
      "mussel", "temperature", "drought")),
]


def _news_groups(headlines: list[dict], limit: int = 12) -> str:
    """Topic-grouped headline cards — no LLM, no key, scannable, neutral.

    The hero story is already featured above, so grouping starts from the
    second headline; selection is round-robin across outlets so neither
    source dominates. Each headline lands in exactly ONE bucket (first match
    wins) so stories never duplicate across cards. Links out only."""
    pool = _balanced(headlines[1:], limit)
    if not pool:
        return ("<p class='note'>No headlines were fetched this build &mdash; the local "
                "RSS feeds were unreachable. This block returns with tomorrow&rsquo;s build.</p>")

    def card(label: str, group: list) -> str:
        lis = "".join(f"""\n        <li><a href="{html.escape(h.get('url', '#'))}" rel="noopener">{html.escape(h['title'])}</a></li>"""
                      for h in group[:4])
        return f"""
        <div class="card ng">
          <h3>{html.escape(label)}</h3>
          <ul class="ng-list">{lis}</ul>
        </div>"""

    buckets: dict[str, list] = {label: [] for label, _ in _TOPIC_BUCKETS}
    rest = []
    for h in pool:
        for label, keywords in _TOPIC_BUCKETS:
            if _matches(h, keywords):
                buckets[label].append(h)
                break
        else:
            rest.append(h)

    cards = [card(label, buckets[label]) for label, _ in _TOPIC_BUCKETS if buckets[label]]
    overflow = [h for label, _ in _TOPIC_BUCKETS for h in buckets[label][4:]]
    if overflow or rest:
        cards.append(card("More headlines", (overflow + rest)[:4]))

    if not cards:
        return "<p class='note'>No headlines were fetched this build.</p>"

    return f"""
    <div class="news-groups">{"".join(cards)}</div>
    <p class="ng-credit">Reporting by KGET 17, 23ABC and Bakersfield Now.</p>"""


def _matches(h: dict, keywords: tuple) -> bool:
    t = (h.get("title", "") or "").lower()
    return any(k in t for k in keywords)


def _balanced(headlines: list[dict], limit: int) -> list[dict]:
    """Round-robin sample across sources so the digest never favors one outlet."""
    by_src: dict[str, list] = {}
    for h in headlines:
        by_src.setdefault(h.get("source", ""), []).append(h)
    keys = list(by_src)
    out, i = [], 0
    while len(out) < limit and any(by_src.values()):
        k = keys[i % len(keys)]
        if by_src[k]:
            out.append(by_src[k].pop(0))
        i += 1
    return out


# ---------------------------------------------------------------- one thing
_WATCH_PRIORITY = ("budget", "ordinance", "vote", "flock", "alpr", "surveillance",
                   "housing", "tax", "fee", "contract", "resolution", "salary",
                   "zoning", "water", "homeless", "police", "fire")


def _one_thing(escribe: dict, board: dict) -> str:
    """One upcoming agenda item worth watching. Never a meeting that already happened: on
    2026-09-22 this pointed readers to a Sept 15 board item as if it were ahead."""
    from .cityhall import _meeting_is_past
    today_iso = common.iso_today()
    candidates = []
    for m in escribe.get("upcoming", []):
        if str(m.get("start_iso", ""))[:10] and str(m.get("start_iso", ""))[:10] < today_iso:
            continue
        for it in (m.get("items") or [])[:40]:
            candidates.append({"meeting": m.get("name", "City meeting"), "item": it.get("title", ""),
                               "date": m.get("start_iso", ""), "url": m.get("url", ""),
                               "text": it.get("text", "")})
    for it in ([] if _meeting_is_past(board.get("date", "")) else board.get("items", [])[:60]):
        candidates.append({"meeting": "Kern County Board of Supervisors",
                           "item": it.get("title", ""),
                           "date": board.get("date", ""),
                           "url": "https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf",
                           "text": it.get("text", "")})

    pick = None
    if candidates:
        pick = llm.pick_thing_to_watch(candidates)
        pick = html.escape(pick) if pick else None   # model text is text, never markup
    if not pick and candidates:
        top = sorted(candidates, key=_score, reverse=True)[0]
        pick = (f"{html.escape(str(top['item']))} &mdash; a {html.escape(top['meeting'])} item scheduled for "
                f"{top['date']}. Agenda and participation details are on the official agenda link.")

    if pick:
        body = f"""
        <div class="card">
          <span class="tag amber">Watch</span>
          <h3>One thing to watch</h3>
          <p>{pick}</p>
          <p class="note">Agenda items are taken from official public agendas; item text is quoted or
          summarized factually. Agendas can change before a meeting &mdash; confirm on the official
          source before attending.</p>
        </div>"""
    else:
        body = """
        <div class="card">
          <span class="tag">Watch</span>
          <h3>One thing to watch</h3>
          <p>No upcoming agenda items were available in this build. City and county agendas are
          typically posted 72 hours before each meeting &mdash; check back tomorrow.</p>
        </div>"""

    return f"""
    <section aria-labelledby="h-watch">
      <p class="sec-head" id="h-watch">One Thing to Watch <span class="unit">next on the public calendar</span></p>
      {body}
    </section>"""


def _score(c: dict) -> int:
    t = (c.get("item", "") + " " + c.get("text", "")).lower()
    s = sum(1 for w in _WATCH_PRIORITY if w in t)
    if "council" in c.get("meeting", "").lower():
        s += 2
    if "planning" in c.get("meeting", "").lower():
        s += 1
    return s


# ---------------------------------------------------------------- category grid
def _category_grid(rel, escribe, board, abc, food, alpr, calfire) -> str:
    # WHAT TO WATCH
    up = escribe.get("upcoming", [])
    if up:
        m = up[0]
        when = common.fmt_when(m.get("start_iso") or "")
        watch_inner = (f'<span class="cat-label">What to Watch</span>'
                       f'<h3>{html.escape(m.get("name", "City meeting"))}</h3>'
                       f'<p>{html.escape(when)}</p>'
                       f'<span class="cat-tag">{_day_tag(m.get("start_iso", ""))}</span>')
        watch_href = m.get("url", f"{rel}city-hall/")
        watch_ext = ""
    else:
        watch_inner = ('<span class="cat-label">What to Watch</span><h3>City &amp; county agendas</h3>'
                       '<p>Upcoming meetings with posted agendas.</p>')
        watch_href = f"{rel}city-hall/"
        watch_ext = ""
    watch_card = f'<a class="cat-card" href="{html.escape(watch_href)}">{images.thumb("cityhall", rel)}{watch_inner}{watch_ext}<span class="card-go">View agenda</span></a>'

    # WHAT THEY DECIDED (most recent past city meeting)
    rec = escribe.get("recent", [])
    if rec:
        m = rec[0]
        decided_date = (m.get("start_iso") or "")[:10]
        decided_inner = (f'<span class="cat-label">What They Decided</span>'
                         f'<h3>{html.escape(m.get("name", "Recent meeting"))}</h3>'
                         f'<p>Meeting held {html.escape(_fmt_d(decided_date))}. Post-meeting recaps are drafted for review.</p>'
                         f'<span class="cat-tag">{html.escape(_fmt_d(decided_date))}</span>')
        decided_href = m.get("url", f"{rel}city-hall/")
    else:
        decided_inner = ('<span class="cat-label">What They Decided</span><h3>No recent meetings posted</h3>'
                         '<p>Recaps appear after each meeting date passes.</p>')
        decided_href = f"{rel}city-hall/"
    decided_card = f'<a class="cat-card" href="{html.escape(decided_href)}">{images.thumb("cityhall", rel)}{decided_inner}<span class="card-go">Official agenda</span></a>'

    # IN DEPTH
    alpr_stats = alpr.get("stats", {}) if alpr.get("ok") else {}
    # Same count /surveillance/ shows: cameras first mapped in the 28 days to the data date.
    # Summing the last 4 change-log entries disagreed with it (duplicate and backfill entries).
    try:
        _cut = (dt.date.fromisoformat(str(alpr.get("asof", ""))[:10]) - dt.timedelta(days=28)).isoformat()
    except ValueError:
        _cut = ""
    alpr_last4 = sum(1 for c in alpr.get("cameras", []) if _cut and (c.get("mapped") or "") >= _cut)
    depth_line = (f"{alpr_stats.get('total', '—')} ALPR cameras mapped"
                  f" &middot; +{alpr_last4} in 4 weeks") if alpr_stats else "License plate reader tracker"
    depth_card = f"""<a class="cat-card" href="{rel}surveillance/">
      {images.thumb("chp", rel)}
      <span class="cat-label">In Depth</span>
      <h3>Flock &amp; ALPR tracker</h3>
      <p>{depth_line} &mdash; map, direction, who owns the land at or beside each camera, and a real 13-week change log.</p>
      <span class="card-go">Open the map</span>
    </a>"""

    # FIRE TRACKER — live count from CAL FIRE
    kern_fires = (calfire or {}).get("kern", []) if (calfire or {}).get("ok") else []
    kern_acres = sum(int(float(i.get("acres") or 0)) for i in kern_fires)
    if kern_fires:
        fire_line = (f"{len(kern_fires)} active {'fire' if len(kern_fires) == 1 else 'fires'} in Kern"
                     f" &middot; {kern_acres:,} acres")
        fire_h3 = "Wildfire tracker"
    elif (calfire or {}).get("ok"):
        fire_line = "No active fires in Kern right now"
        fire_h3 = "Wildfire tracker"
    else:
        fire_line = "CAL FIRE data unavailable right now"
        fire_h3 = "Wildfire tracker"
    fire_card = f"""<a class="cat-card" href="{rel}fires/">
      {images.thumb("bakersfield", rel)}
      <span class="cat-label">Live Data</span>
      <h3>{fire_h3}</h3>
      <p>{fire_line} &mdash; live map of CAL FIRE incidents across Kern County and California.</p>
      <span class="card-go">See the map</span>
    </a>"""

    return f'<div class="cat-grid">{watch_card}{decided_card}{depth_card}{fire_card}</div>'


# ---------------------------------------------------------------- week grid
def _week_label(today) -> str:
    monday = today - dt.timedelta(days=today.weekday())
    friday = monday + dt.timedelta(days=4)
    return f"{monday.strftime('%b').upper()} {monday.day} &ndash; {friday.strftime('%b').upper()} {friday.day}"


def _week_grid(today, rel, weather, escribe, board, top) -> str:
    monday = today - dt.timedelta(days=today.weekday())
    days = [monday + dt.timedelta(days=i) for i in range(5)]
    alerts = (weather or {}).get("alerts", [])
    upcoming = escribe.get("upcoming", [])
    # past days get their brief headline so the week never looks empty
    archive = {str(e.get("date", "")): e for e in _load_archive()}

    cols = []
    for d in days:
        iso = d.isoformat()
        items = []

        # weather alerts covering this day
        for a in alerts:
            if _alert_covers(a, iso):
                items.append(f'<li class="day-alert"><span class="tag amber">Alert</span> '
                             f'<a href="{html.escape(a.get("url", "https://www.weather.gov/"))}" rel="noopener">{html.escape(a.get("event", "Weather alert"))}</a></li>')
        # today's lead story
        if d == today and top:
            items.append(f'<li><span class="tag green">Today</span> '
                         f'<a href="{html.escape(top.get("url", "#"))}" rel="noopener">{html.escape(top["title"])}</a></li>')
        # meetings
        for m in upcoming:
            if (m.get("start_iso") or "")[:10] == iso:
                items.append(f'<li><span class="tag">Meeting</span> '
                             f'<a href="{html.escape(m.get("url", f"{rel}city-hall/"))}" rel="noopener">{html.escape(m.get("name", "Public meeting"))}</a></li>')
        # county board
        if _board_date(board) == iso:
            items.append(f'<li><span class="tag">County</span> '
                         f'<a href="{rel}city-hall/county-board/">Board of Supervisors</a></li>')

        # past day's brief headline (from the archive) — the week never shows
        # "No items posted" for a day we actually published
        if d < today:
            arch = archive.get(iso)
            if arch and arch.get("headline"):
                items.append(f'<li><span class="tag">Brief</span> '
                             f'<a href="{rel}briefs/{iso}/">{html.escape(_entry_label(arch))}</a></li>')

        if not items:
            items.append('<li class="day-empty">No items posted</li>')

        today_cls = ' class="today"' if d == today else ""
        head = f"{d.strftime('%a').upper()} {d.day}"
        if d == today:
            head += " &middot; TODAY"
        cols.append(f"""
        <div class="day-col{today_cls}">
          <h3>{head}</h3>
          <ul>{''.join(items)}</ul>
        </div>""")

    return f'<div class="week-grid">{"".join(cols)}</div>'


def _alert_covers(a: dict, day_iso: str) -> bool:
    starts = (a.get("starts") or "")[:10]
    ends = (a.get("ends") or "")[:10]
    return bool(starts and starts <= day_iso and (not ends or day_iso <= ends))


def _board_date(board: dict) -> str:
    raw = (board or {}).get("date", "")
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _day_tag(iso: str) -> str:
    try:
        d = dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return ""
    today = common.today_pacific()
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if 0 < delta <= 7:
        return d.strftime("%A")
    return d.strftime("%b %d")


def _fmt_d(iso: str) -> str:
    if not iso:
        return ""
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _fmt_short_date(raw: str) -> str:
    """'6/29/2026 12:17:00 PM' → 'Jun 29' (portable, no %-d)."""
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            d = dt.datetime.strptime(raw.strip(), fmt)
            return f"{d.strftime('%b')} {d.day}"
        except ValueError:
            continue
    return raw.strip()[:10]


# ---------------------------------------------------------------- archive
def _recent_briefs(rel) -> str:
    entries = _load_archive()
    if not entries:
        return ('<div class="card"><p>The archive starts with today&rsquo;s brief and grows '
                'one entry per day. Check back tomorrow.</p></div>')
    rows = "".join(f"""
    <li class="arch-row">
      <span class="arch-date">{html.escape(str(e.get('date', '')))}</span>
      <span class="arch-head"><a href="{rel}briefs/{html.escape(str(e.get('date', '')))}/">{html.escape(_entry_label(e))}</a></span>
    </li>""" for e in entries[-6:])
    return f"""<div class="card"><ul class="arch-list">{rows}</ul>
    <p class="arch-more"><a href="{rel}briefs/">See all daily briefs &rarr;</a></p></div>"""


def _load_archive() -> list:
    p = common.DATA / "briefs_archive.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------- brief page surface (SEO + job)
def _h2ify(block_html: str) -> str:
    """Section labels on brief pages ship as <p class="sec-head">. A 2,000-word
    article with no h2 gives search engines no heading outline. Convert at
    render time only (.sec-head carries its own type, margin and flex layout,
    so the swap is visually identical)."""
    return re.sub(r'<p class="sec-head"(?P<rest>[^>]*)>(?P<body>.*?)</p>',
                  r'<h2 class="sec-head"\g<rest>>\g<body></h2>',
                  block_html, flags=re.S)


def _plain(block_html: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", block_html)).split())


def _brief_lede(content_html: str, limit: int = 155) -> str:
    """First real paragraph of the brief, for the meta description. Skips the
    greeting so every day's description is not the same sentence."""
    for m in re.finditer(r"<p(?![^>]*sec-head)[^>]*>(.*?)</p>", content_html, re.S):
        txt = _plain(m.group(1))
        if len(txt) < 60 or txt.lower().startswith("good morning"):
            continue
        if len(txt) <= limit:
            return txt
        return txt[:limit].rsplit(" ", 1)[0].rstrip(",;:.-")
    return ""


_TITLE_STOPWORDS = {"for", "and", "the", "with", "in", "of", "to", "at", "on",
                    "a", "an", "as", "but", "or", "its", "after", "over", "from"}


def _brief_title(headline: str, d) -> str:
    """Our own title for a dated brief. Never another outlet's headline: the lead story is
    credited and linked in the body, not used as our page title (owner's rule, 2026-09-22)."""
    return f"Bakersfield News for {d:%A}, {d:%b} {d.day}, {d.year} | Bakersfield Daily Brief"


def _brief_h1(d) -> str:
    return f"Bakersfield Daily Brief: {_fmt_date(d)}"


def _lede_summary(content_html: str, limit: int = 110) -> str:
    """One line from the brief's own written summary (the lede), without the greeting."""
    m = re.search(r'<div class="lede">(.*?)</div>', content_html or "", re.S)
    txt = _plain(m.group(1)) if m else ""
    txt = re.sub(r"^(Good morning|Morning)[^.!]*[.!]\s*", "", txt, flags=re.I).strip()
    if len(txt) <= limit:
        return txt
    return txt[:limit].rsplit(" ", 1)[0].rstrip(",;:.-") + "…"


def _entry_label(e: dict) -> str:
    """Archive link text in our own words: the brief's own opening summary, else the date."""
    s = _lede_summary(str(e.get("content") or "")) or str(e.get("summary") or "").strip()
    if s:
        return s
    try:
        return f"Daily brief for {_fmt_date(dt.date.fromisoformat(str(e.get('date', ''))))}"
    except ValueError:
        return "Daily brief"


def _own_h1(stored_html: str, d) -> str:
    """Stored archive bodies carry the old lead-headline h1 (or none); show our own."""
    h1 = f"<h1>{html.escape(_brief_h1(d))}</h1>"
    stored_html = stored_html.replace("The Bakersfield Brief", "the Bakersfield Daily Brief")
    if re.search(r"<h1[^>]*>", stored_html):
        return re.sub(r"<h1[^>]*>.*?</h1>", h1, stored_html, count=1, flags=re.S)
    return f'<div class="pagehead"><div class="hero"><p class="kicker">The Daily Brief</p>{h1}</div></div>' + stored_html


def _brief_newsarticle(headline: str, desc: str, iso: str) -> dict:
    """NewsArticle JSON-LD for a dated brief page (news-style fresh signal,
    same pattern overnight.py uses per report)."""
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": headline,
        "description": desc,
        "datePublished": f"{iso}T06:00:00-07:00",
        "dateModified": f"{iso}T06:00:00-07:00",
        "author": {"@type": "Organization", "name": "Bakersfield Daily Brief",
                   "url": "https://bakersfieldbrief.com/"},
        "publisher": {"@type": "Organization", "name": "Bakersfield Daily Brief",
                      "url": "https://bakersfieldbrief.com/",
                      "logo": page_mod.publisher_logo()},
        "mainEntityOfPage": f"https://bakersfieldbrief.com/briefs/{iso}/",
        "articleSection": "Daily Brief",
        "inLanguage": "en",
        "isAccessibleForFree": True,
    }


# topic → the evergreen tracker that owns it (all paths verified in the sitemap)
_BRIEF_TOPICS = (
    (("grapevine", "tejon", "i-5", "interstate 5", "tehachapi pass", "hwy 58",
      "highway 58", "chain control", "road closure"), "grapevine/",
     "Is the Grapevine open right now?"),
    (("alpr", "flock", "license plate", "surveillance camera"), "surveillance/",
     "Surveillance cameras in Kern County"),
    (("dispatch", "scanner", "police", "deputies", "chp", "crash", "shooting"), "overnight/",
     "The Kern Overnight: what happened overnight"),
    (("supervisors", "city council", "board of supervisors", "agenda",
      "public meeting", "planning commission"), "city-hall/",
     "City and county meetings this week"),
    (("reservoir", "lake isabella", "aqueduct", "water level", "drought"), "water/",
     "Kern County water levels"),
    (("wildfire", "brush fire", "evacuation", "calfire", "cal fire"), "fires/",
     "Fires and smoke in Kern County"),
)


def _related_trackers(rel: str, content_html: str) -> str:
    """Give every brief page a job: a path into the evergreen trackers that
    actually earn clicks. Chosen by what the day's brief mentions, topped up to
    at least three so a quiet news day still links somewhere useful."""
    text = _plain(content_html).lower()
    scored = []
    for kws, href, label in _BRIEF_TOPICS:
        hits = sum(text.count(k) for k in kws)
        if hits:
            scored.append((hits, href, label))
    scored.sort(key=lambda x: -x[0])
    picked = [(href, label) for _, href, label in scored[:4]]
    for _, href, label in _BRIEF_TOPICS:
        if len(picked) >= 3:
            break
        if (href, label) not in picked:
            picked.append((href, label))
    rows = "".join(f"""
    <li class="arch-row"><span class="arch-date">tracker</span>
    <span class="arch-head"><a href="{rel}{href}">{html.escape(label)}</a></span></li>"""
                   for href, label in picked)
    return f"""
    <section class="block brief-seg" style="margin-top:34px">
      <p class="sec-head">Keep reading <span class="unit">live trackers, updated all day</span></p>
      <div class="card"><ul class="arch-list">{rows}</ul></div>
    </section>"""


def _archive(ctx, today, built_iso, top, news, weather, chp, isa,
             escribe, board, abc, food, alpr, airnow, calfire, headlines,
             events=None) -> list[str]:
    """Save a permanent copy of today's brief + refresh /briefs/ index.

    The brief page is the friendly all-in-one article (greeting, weather, top
    stories, something good, upcoming events) plus a meetings-only block —
    NOT a duplicate of the homepage. Past-day pages render the stored article
    body so every day of the week has real content.
    """
    built = []
    rel = "../../"  # briefs/<date>/index.html is 2 levels below site root
    content = _article_lead(top, headlines, weather, airnow, calfire,
                            escribe, events or [], today, rel, ctx)
    content += _upcoming_meetings(rel, escribe, board, today)

    headline = _brief_title("", today).split(" | ")[0]
    dated_desc = _brief_lede(content) or (
        f"Today's Bakersfield and Kern County brief for {_fmt_date(today)}: local news, "
        "weather, conditions, and public meetings, published every morning at 6 AM PT.")
    page = page_mod.render(
        title=_brief_title(headline, today),
        desc=dated_desc,
        canonical=f"/briefs/{built_iso}/",
        content=_h2ify(content) + _related_trackers(rel, content),
        current="index", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                _brief_newsarticle(headline, dated_desc, built_iso)],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
    )
    common.write(common.SITE / "briefs" / built_iso / "index.html", page)
    built.append(f"briefs/{built_iso}/index.html")

    # archive data — keep the full article body so past-day pages render real
    # content instead of a headline stub (feed.py reads headline/date only)
    entries = _load_archive()
    entry = {"date": built_iso,
             "headline": top["title"] if top else "No headlines fetched",   # the lead story, kept as data
             "summary": _lede_summary(content),
             "url": f"/briefs/{built_iso}/",
             "content": content}
    entries = [e for e in entries if e.get("date") != built_iso] + [entry]
    entries.sort(key=lambda e: e.get("date", ""))
    (common.DATA / "briefs_archive.json").write_text(
        json.dumps(entries, indent=1), encoding="utf-8")

    # /briefs/ hub — the stable URL that renders today's full brief as real
    # content (the same pattern that makes /grapevine/ and /surveillance/
    # rank). Homepage + all internal links point here so link equity
    # accumulates at ONE URL instead of fragmenting across dated URLs.
    # (The dated /briefs/<date>/ pages remain the permanent archive below.)
    index_rel = "../"
    hub_content = _article_lead(top, headlines, weather, airnow, calfire,
                                escribe, events or [], today, index_rel, ctx)
    hub_content += _upcoming_meetings(index_rel, escribe, board, today)

    rows = "".join(f"""
    <li class="arch-row">
      <span class="arch-date">{html.escape(str(e.get('date', '')))}</span>
      <span class="arch-head"><a href="{index_rel}briefs/{html.escape(str(e.get('date', '')))}/">{html.escape(_entry_label(e))}</a></span>
    </li>""" for e in reversed(entries))
    archive_section = f"""
    <p class="sec-head" style="margin-top:26px">All previous briefs <span class="unit">permanent archive, {len(entries)} on record</span></p>
    <div class="card"><ul class="arch-list">{rows}</ul></div>"""

    today_txt = _fmt_date(today)
    top_title = (top or {}).get("title", "")
    brief_faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "What is happening in Bakersfield today?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (f"Today's Bakersfield Daily Brief for {today_txt} covers "
                             + (f"the top story, {top_title}, " if top_title else "")
                             + "plus Kern County news, weather, air quality, and public meetings. "
                             "A new brief is published every morning at 6 AM PT."),
                },
            },
            {
                "@type": "Question",
                "name": "What is the Bakersfield Daily Brief?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("The Bakersfield Daily Brief is a free, automated morning summary "
                             "of Kern County news, weather, conditions, and public meetings. "
                             "It is compiled every day at 6 AM PT and published at "
                             "bakersfieldbrief.com."),
                },
            },
        ],
    }

    hub_body = (f"{_h2ify(hub_content)}\n\n{_related_trackers(index_rel, hub_content)}"
                f"\n\n{archive_section}")
    common.write(common.SITE / "briefs" / "index.html", page_mod.render(
        title="Bakersfield News Today — Daily Brief for Kern County",
        desc=f"Today's Bakersfield news: the {today_txt} Daily Brief with Kern County headlines, weather, air quality, and public meetings. Every morning.",
        canonical="/briefs/", content=hub_body, current="other", rel=index_rel,
        built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), brief_faq],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else ""))
    built.append("briefs/index.html")

    # past-day archive pages: site/ is wiped each build, so re-render from the
    # committed archive metadata — full article body when retained, else the
    # headline stub. Past pages are 2 levels deep → rel="../../" like today's.
    past_rel = "../../"
    for e in entries:
        dstr = str(e.get("date", ""))
        if dstr == built_iso:
            continue
        try:
            d = dt.date.fromisoformat(dstr)
        except ValueError:
            continue
        stored = e.get("content") or ""
        past_headline = _brief_title("", d).split(" | ")[0]
        stored = _own_h1(stored, d) if stored else stored
        if stored:
            past_desc = _brief_lede(stored) or (
                f"The {_fmt_date(d)} Bakersfield Daily Brief: Kern County news, "
                "weather, conditions, and public meetings.")
            past_body = (_h2ify(stored) + _related_trackers(past_rel, stored)
                         + _upcoming_meetings(past_rel, escribe, board, d))
        else:
            past_desc = (f"The Bakersfield Daily Brief for {_fmt_date(d)}: Kern County news, "
                         "weather, conditions, and public meetings.")
            past_body = f"""
        <div class="pagehead"><div class="hero"><p class="kicker">Archive</p>
        <h1>Brief for {_fmt_date(d)}</h1>
        <p class="lede">The Bakersfield Daily Brief for this morning.</p></div></div>
        <div class="card"><p class="note" style="margin-top:8px">The full article for this date was not retained; see
        <a href="/">today&rsquo;s brief</a> or the
        <a href="{past_rel}briefs/">archive index</a>.</p></div>""" + _related_trackers(past_rel, "")
        common.write(common.SITE / "briefs" / dstr / "index.html", page_mod.render(
            title=_brief_title(past_headline, d),
            desc=past_desc,
            canonical=f"/briefs/{dstr}/", content=past_body, current="index", rel=past_rel,
            built=built_iso, jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                                     _brief_newsarticle(past_headline, past_desc, dstr)],
            statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else ""))
        built.append(f"briefs/{dstr}/index.html")
    return built


# ---------------------------------------------------------------- upcoming
def _upcoming_meetings(rel, escribe, board, today) -> str:
    """Meetings-only block for the daily article page (events already have
    their own segment in the article, so no duplication here)."""
    rows = []
    for m in escribe.get("upcoming", []) or []:
        iso = str(m.get("start_iso", ""))
        if iso[:10] < today.isoformat() or iso[:10] > (today + dt.timedelta(days=7)).isoformat():
            continue
        when = iso[:16].replace("T", " ")
        rows.append(f"""
        <li class="ev-row"><span class="ev-date">{html.escape(when)}</span>
        <span class="ev-body"><a href="{html.escape(m.get('url', rel + 'city-hall/'))}" rel="noopener"><strong>{html.escape(m.get('name', 'Public meeting'))}</strong></a>
        <span class="ev-venue">Public meeting</span></span></li>""")

    if _board_date(board):
        bd = _board_date(board)
        if today.isoformat() <= bd <= (today + dt.timedelta(days=7)).isoformat():
            rows.append(f"""
            <li class="ev-row"><span class="ev-date">{html.escape(bd[:10])}</span>
            <span class="ev-body"><a href="{rel}city-hall/county-board/"><strong>Board of Supervisors</strong></a>
            <span class="ev-venue">Kern County</span></span></li>""")

    if not rows:
        return ""
    return f"""
    <section class="block brief-seg" style="margin-top:34px">
      <p class="sec-head">Public meetings <span class="unit">next 7 days &middot; official agendas</span></p>
      <ul class="ev-list">{''.join(rows)}</ul>
      <p class="note" style="margin-top:10px">Meetings from official agendas. See
      <a href="{rel}city-hall/">all city &amp; county meetings</a>.</p>
    </section>"""


# ---------------------------------------------------------------- article lead
def _meetings_prose(escribe) -> str:
    """Compact plain-text meeting list for the LLM brief body."""
    bits = []
    for m in escribe.get("upcoming", []) or []:
        iso = str(m.get("start_iso", ""))
        bits.append(f"{m.get('name', 'Public meeting')} — {iso[:16].replace('T', ' ')}")
    return "; ".join(bits[:8])


def _para_html(prose: str) -> str:
    """LLM prose → escaped HTML. '## Heading' lines become the site's
    standard sec-head style; blank-line paragraphs become <p>s. Inside the
    'Top stories' section the first sentence of each paragraph is bolded
    (render-side, so skimmers always find the leads — no model reliance).
    """
    out, section = [], None
    for chunk in re.split(r"\n\s*\n", prose or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("## "):
            section = chunk[3:].strip().lower()
            out.append(f'<p class="sec-head">{html.escape(chunk[3:].strip())}</p>')
        else:
            p = html.escape(chunk).replace("**", "")
            if section == "top stories":
                p = _bold_first_sentence(p)
            out.append(f"<p>{p}</p>")
    return "".join(out)


def _bold_first_sentence(p: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", p, re.S)
    if m:
        return f"<strong>{m.group(1)}</strong>{m.group(2)}{p[m.end():]}"
    return p


def _diversify(items: list, cap: int = 3) -> list:
    """Keep order but cap how many stories any single source contributes —
    the brief must never be one outlet's feed. 'KGET 17' → 'KGET'."""
    counts, out = {}, []
    for it in items or []:
        src = str(it.get("source") or "Other").split()[0]
        if counts.get(src, 0) >= cap:
            continue
        counts[src] = counts.get(src, 0) + 1
        out.append(it)
    return out


def _brief_full_body(top, headlines, weather, airnow, calfire,
                     events, escribe, today) -> str | None:
    """The complete 1,000-1,500 word brief body (LLM, CI-only). None →
    callers fall back to the short greeting + structured blocks."""
    import os
    if not os.environ.get("LLM_API_KEY"):
        return None  # skip the article fetches entirely without a key
    ko = _overnight_summary()
    overnight_md = ""
    if ko:
        f = Path("data") / "overnight_reports" / f"{ko['date']}.md"
        if f.exists():
            try:
                overnight_md = f.read_text(encoding="utf-8")[:3000]
            except Exception:  # noqa: BLE001
                overnight_md = ""
    items = []
    if top:
        items.append(top)
    # source-diverse selection: the brief must never read like one
    # outlet's feed — cap any single source in the supporting stories
    for h in _diversify(headlines or [], cap=3)[:7]:
        items.append(h)
    items = llm.fetch_article_texts(items, n=8)
    wx = _weather_prose(weather, airnow, calfire)
    good = re.sub(r"<[^>]+>", " ", _positive_block(headlines, events, today, ""))
    return llm.brief_full(
        overnight_md, wx, airnow or {}, calfire or {}, items,
        events or [], _meetings_prose(escribe), good,
        f"{today:%A, %B} {today.day}, {today.year}" if hasattr(today, "day") else str(today))


def _cached_brief_body(today) -> str | None:
    """The LLM brief body saved by the 6am build — 3-hourly LLM-free runs
    reuse it so the brief is never downgraded to the fallback mid-day."""
    p = common.DATA / "briefs" / f"{today:%Y-%m-%d}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["body"]
    except Exception:
        return None


def _cached_brief_top(today) -> dict | None:
    """The top headline the cached brief body was written about, if it was saved with it."""
    p = common.DATA / "briefs" / f"{today:%Y-%m-%d}.json"
    try:
        top = json.loads(p.read_text(encoding="utf-8")).get("top")
        return top if isinstance(top, dict) else None
    except Exception:
        return None


def _save_brief_body(today, body: str, top: dict | None = None) -> None:
    try:
        p = common.DATA / "briefs" / f"{today:%Y-%m-%d}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        keep = {k: top.get(k) for k in ("title", "url", "source", "published")} if top else None
        p.write_text(json.dumps({"body": body, "top": keep}), encoding="utf-8")
    except Exception:
        pass


def _article_lead(top, headlines, weather, airnow, calfire,
                  escribe, events, today, rel, ctx) -> str:
    """Friendly, all-in-one 'Today's Brief' opening the daily article.

    Structure: warm greeting → weather block (figure) → top stories with
    short original summaries → 'something good' positive pick → upcoming
    events (concerts/comedians included). LLM upgrades prose when the key is
    present (CI); everything degrades gracefully to a deterministic, keyless
    version so the page always builds.
    """
    from .events import _when_date

    def esc(s):
        return html.escape(str(s or ""))

    # ---- full brief body (LLM, CI) → else short greeting (LLM/deterministic)
    # Cache-first: the 6am build generates and saves; every later render
    # (3-hourly runs, and the /briefs/ hub page in the same build) reuses the
    # saved body instead of firing the LLM again.
    full = _cached_brief_body(today)
    if full is None and os.environ.get("LLM_API_KEY"):
        full = _brief_full_body(top, headlines, weather, airnow, calfire,
                                events, escribe, today)
        if full:
            _save_brief_body(today, full, top)
    ai_note = ""
    if full:
        greeting_html = _para_html(full)  # LLM plain text → escaped <p>s
        ai_note = ('<p class="ai-note">This summary is written by AI at 6 AM from that morning&rsquo;s '
                   'headlines, weather and meetings. The sections below come straight from the '
                   'sources and update through the day; if a number differs, trust the section.</p>')
        ctx_brief_words = len(re.findall(r"[A-Za-z0-9'’-]+", full))
    else:
        greeting = llm.friendly_brief(
            (top or {}).get("title", ""), headlines, weather, airnow, calfire, events)
        if greeting:
            greeting_html = _para_html(greeting)  # LLM plain text → escaped
            ai_note = ('<p class="ai-note">This greeting is written by AI from the morning&rsquo;s '
                       'data; the sections below come straight from the sources.</p>')
            ctx_brief_words = len(re.findall(r"[A-Za-z0-9'’-]+", greeting))
        else:
            greeting_html = _greeting_fallback(top, weather, airnow)  # already HTML
            ctx_brief_words = len(re.findall(
                r"[A-Za-z0-9'’-]+", re.sub(r"<[^>]+>", " ", greeting_html)))
    try:
        ctx.build_report["brief_words"] = ctx_brief_words
    except Exception:  # noqa: BLE001
        pass

    # ---- weather block
    wx = _weather_prose(weather, airnow, calfire)

    # ---- top stories (LLM digest when available, else original one-liners)
    stories = _stories(top, headlines, rel)

    # ---- something good (LLM pick, else real family event, else headline)
    good = _positive_block(headlines, events, today, rel)

    # ---- upcoming events (concerts/comedians included)
    events_html = _events_block(events, escribe, today, rel)

    return f"""
    <div class="pagehead"><div class="hero">
      <p class="kicker">The Daily Brief</p>
      <h1>{esc(_brief_h1(today))}</h1>
      <div class="lede">{greeting_html}</div>
      {ai_note}
    </div></div>

    {_newsletter_block()}

    {_overnight_section(rel)}
    {_transcription_note()}

    <section class="brief-seg" aria-labelledby="seg-weather">
      <p class="sec-head">Today's weather <span class="unit">forecast &middot; alerts &middot; air &middot; fires</span></p>
      {images.figure("bakersfield", rel)}
      <div class="card">{wx}</div>
    </section>

    <section class="brief-seg" aria-labelledby="seg-news">
      <p class="sec-head">Top stories <span class="unit">headlines + links, synthesized</span></p>
      <p class="seg-intro">Here&rsquo;s what&rsquo;s making news around Kern County this morning — the overnight cases, the policy fights, and the community events worth knowing about.</p>
      {stories}
    </section>

    <section class="brief-seg" aria-labelledby="seg-good">
      <p class="sec-head">Something good <span class="unit">one pick to brighten your day</span></p>
      <p class="seg-intro">Not everything in the news is heavy. Here&rsquo;s something to look forward to.</p>
      {good}
    </section>

    <section class="brief-seg" aria-labelledby="seg-events">
      <p class="sec-head">Out this week <span class="unit">concerts &middot; comedy &middot; more</span></p>
      <p class="seg-intro">If you&rsquo;re planning a night out, these are the shows and events on the calendar.</p>
      {images.figure("fox", rel)}
      {events_html}
    </section>

    <p class="note" style="margin-top:8px">That&rsquo;s the morning read — see you back here tomorrow for the next one. This brief is compiled automatically
    from public records and linked sources — a factual digest, not opinion.
    <a href="{rel}letters/">Write a letter</a> about anything here · report an
    error: <a href="mailto:corrections@bakersfieldbrief.com?subject=Correction&body=Page: {rel}briefs/">corrections@bakersfieldbrief.com</a>.</p>
    """


def _greeting_fallback(top, weather, airnow) -> str:
    """Friendly greeting without an LLM — keyless, factual, warm."""
    fc = (weather or {}).get("forecast", {}) or {}
    bits = []
    if fc.get("high") is not None:
        bits.append(f"today&rsquo;s high should land near {fc['high']}&deg;")
    alerts = (weather or {}).get("alerts", [])
    if alerts:
        bits.append(f"a {html.escape(alerts[0].get('event', 'weather alert'))} is in effect")
    if airnow and airnow.get("ok") and airnow.get("aqi") is not None:
        bits.append(f"air quality sits at {airnow['aqi']}")
    cond_txt = (" — " + ", ".join(bits) + ".") if bits else "."
    if top:
        body = (f" <strong>{html.escape(top['title'])}</strong> is the big story "
                f"we&rsquo;re watching today. The full rundown is below — the overnight "
                f"incident summary, the weather picture, the headlines around town, "
                f"and what&rsquo;s coming up this week.")
    else:
        body = (" Here&rsquo;s everything happening in Bakersfield and Kern County "
                "today — the overnight incident summary, the weather picture, "
                "the headlines around town, and what&rsquo;s on the calendar.")
    return f"<p><strong>Good morning, Kern County.</strong>{cond_txt}{body}</p>"


def _weather_prose(weather, airnow, calfire) -> str:
    """Weather block: forecast + alerts + AQI + fires as clean readable prose."""
    fc = (weather or {}).get("forecast", {}) or {}
    bits = []
    if fc.get("high") is not None or fc.get("low") is not None:
        hi = fc.get("high")
        lo = fc.get("low")
        hi_txt = f"a high near {hi}°" if hi is not None else "a mild day"
        lo_txt = f" and a low around {lo}° tonight" if lo is not None else ""
        bits.append(f"Expect {hi_txt}{lo_txt}.")
    if fc.get("current") is not None:
        bits.append(f"It's currently {fc['current']}° at Meadows Field (KBFL).")
    alerts = (weather or {}).get("alerts", [])
    if alerts:
        a = alerts[0]
        bits.append(f"<strong>{html.escape(a.get('event', 'Weather alert'))}</strong>: "
                    f"{html.escape((a.get('headline') or '')[:160])}")
    elif (weather or {}).get("ok"):
        bits.append("No active weather alerts for Kern County.")
    else:
        bits.append("Weather alerts could not be checked for this edition.")
    if airnow and airnow.get("ok") and airnow.get("aqi") is not None:
        bits.append(f"Air quality is {airnow['aqi']} — "
                    f"{html.escape((airnow.get('category') or 'moderate').lower())}.")
    kern = [f for f in (calfire or {}).get("incidents", []) if "Kern" in str(f.get("county", ""))]
    if kern:
        names = ", ".join(html.escape(f.get("name", "fire")) for f in kern)
        bits.append(f"Fire crews are on {len(kern)} active {'fire' if len(kern) == 1 else 'fires'} in Kern ({names}).")
    return "<p>" + "</p><p>".join(bits) + "</p>"


def _stories(top, headlines, rel) -> str:
    """Top stories: LLM digest when available, else original one-liners."""
    if not headlines:
        return '<p class="note">No headlines were fetched this build — the local RSS feeds were unreachable. This block returns with tomorrow&rsquo;s build.</p>'
    digest = _get_digest(headlines)
    if digest:
        return f'<div class="card"><p>{digest}</p></div>'
    # deterministic fallback: hero + 3 more, each summarized in our own words
    items = []
    if top:
        items.append(('<strong>Top story:</strong> ' + html.escape(top["title"])
                      + f' — <em>via {html.escape(top.get("source", "local news"))}.</em>',
                      top.get("url", "#")))
    for h in (headlines or [])[1:4]:
        items.append((html.escape(h["title"]), h.get("url", "#")))
    lis = "".join(
        f'<li><a href="{html.escape(url)}" rel="noopener">{txt}</a></li>'
        for txt, url in items)
    return f'<div class="card"><ul class="story-list">{lis}</ul>' \
           f'<p class="note" style="margin-top:8px">Summaries are written from the headline and link to the original outlet for details.</p></div>'


_POSITIVE_KW = (
    ("Grand opening", ("grand opening", "now open", "ribbon cutting", "opens its doors", "new store")),
    ("For students", ("scholarship", "back to school", "school supply", "student")),
    ("Community", ("volunteer", "fundraiser", "donation", "food drive", "toy drive",
                   "community", "collector", "health fair")),
    ("Celebration", ("festival", "celebrat", "anniversary", "milestone", "award",
                     "honor", "parade")),
    ("Family fun", ("kids", "children", "family", "museum", "library", "art walk", "pet")),
)


def _pos_category(title: str) -> str | None:
    t = (title or "").lower()
    for label, kws in _POSITIVE_KW:
        if any(k in t for k in kws):
            return label
    return None


def _family_event(events, today):
    """A real family-friendly event in the next 7 days — name, venue, date."""
    from .events import _when_date
    best = None
    for e in events or []:
        d = _when_date(e, today)
        if not d or not (today <= d <= today + dt.timedelta(days=7)):
            continue
        name = (e.get("name") or "").lower()
        if any(k in name for k in ("kids", "children", "family", "disney", "bluey",
                                   "musical", "jr", "jr.", "paw patrol", "magic",
                                   "circus", "princess", "sesame", "peppa")):
            return (d, e)
        if best is None:
            best = (d, e)
    return best  # any dated event if no family pick found


def _positive_block(headlines, events, today, rel) -> str:
    """'Something good' — a compact news card with real content.

    Priority: LLM pick (2 warm sentences) → a real dated event with venue and
    date → a keyword-matched positive headline with a category chip. No filler
    copy, no full-width figure, small thumbnail only.
    """
    # 1) LLM pick — real prose
    pick = llm.pick_positive(headlines)
    if pick:
        return f"""
        <div class="card pos-card">
          {images.thumb("fair", rel)}
          <div class="pos-body">
            <span class="cat-tag">Community</span>
            <p>{html.escape(pick)}</p>
          </div>
        </div>"""

    # 2) real event with venue + date
    ev = _family_event(events, today)
    if ev:
        d, e = ev
        name = e.get("name", "A local event")
        venue = e.get("venue") or "local venue"
        when = d.strftime("%a, %b %d")
        cat = _pos_category(name) or "Family fun"
        return f"""
        <div class="card pos-card">
          {images.thumb("fair", rel)}
          <div class="pos-body">
            <span class="cat-tag">{html.escape(cat)}</span>
            <h3><a href="{html.escape(e.get('url') or '#')}" target="_blank" rel="noopener">{html.escape(name)}</a></h3>
            <p>{html.escape(venue)} &middot; {html.escape(when)} — a good one to put on the calendar.</p>
          </div>
        </div>"""

    # 3) positive headline with category chip
    for h in headlines:
        cat = _pos_category(h.get("title", ""))
        if cat:
            return f"""
            <div class="card pos-card">
              {images.thumb("fair", rel)}
              <div class="pos-body">
                <span class="cat-tag">{html.escape(cat)}</span>
                <h3><a href="{html.escape(h.get('url', '#'))}" rel="noopener">{html.escape(h['title'])}</a></h3>
                <p>From {html.escape(h.get('source', 'local news'))} &middot; <a href="{rel}events/">more good things around town</a></p>
              </div>
            </div>"""

    # 4) nothing positive today — a quiet, honest fallback
    return ""


def _events_block(events, escribe, today, rel) -> str:
    """Next-7-days events with date badges; meetings mixed in when thin."""
    from .events import _when_date

    dated = []
    for e in events or []:
        d = _when_date(e, today)
        if d and today <= d <= today + dt.timedelta(days=7):
            dated.append((d, e))
    dated.sort(key=lambda t: t[0])

    rows = []
    for d, e in dated:
        venue = esc = None
        v = e.get("venue") or ""
        rows.append(f"""
        <li class="ev-row"><span class="ev-date">{html.escape(d.strftime('%a') + ' ' + str(d.day))}</span>
        <span class="ev-body"><a href="{html.escape(e.get('url') or '#')}" target="_blank" rel="noopener"><strong>{html.escape(e.get('name', 'Untitled event'))}</strong></a>
        <span class="ev-venue">{html.escape(v)}</span></span></li>""")

    if not rows:
        rows.append('<li class="ev-row"><span class="ev-body">Nothing dated in the next '
                    '7 days from the venues we watch — check the '
                    f'<a href="{rel}events/">events page</a> for the full calendar.</span></li>')

    return f"""
    <div class="card"><ul class="ev-list">{"".join(rows)}</ul>
    <p class="note" style="margin-top:10px">From venue listings we watch: Fox Theater,
    Mechanics Bank Arena, The Well Comedy Club, the Condors, and more. Dates are as
    the venue published them. See <a href="{rel}events/">all events</a>.</p></div>"""


# ---------------------------------------------------------------- misc
def _fmt_date(d: dt.date) -> str:
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def _footnote() -> str:
    return """
    <section class="block" style="margin-top:40px">
      <div class="sign-head"><span class="tab">i</span><h2>About this brief</h2></div>
      <div class="card">
        <p>The Daily Brief is generated automatically every morning from public data sources.
        Each block is independent &mdash; if one source is unavailable, the rest of the brief
        still publishes. Sources: National Weather Service (alerts, forecast, KBFL observation),
        CHP (incidents), California DWR/CDEC (reservoir), City of Bakersfield eSCRIBE and Kern
        County Board of Supervisors (agendas), KGET and 23ABC (headlines), California ABC
        (licenses), Kern County Environmental Health (closures), and OpenStreetMap
        (camera locations, &copy; OSM contributors, ODbL).</p>
        <p>This is a factual digest: we summarize, link, and attribute &mdash; we do not
        editorialize or republish copyrighted article text.</p>
      </div>
    </section>"""
