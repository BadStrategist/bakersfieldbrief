#!/usr/bin/env python3
"""The Daily Brief: the home page (index.html), the dated brief pages and the /briefs/ archive.

The home page body is composed in home.py (v5 design) and rendered through
templates/home.html. This module picks the top story, writes index.html, saves the permanent
copy of the day's brief and renders the email.

All content baked at build time. Headlines link out only, never republished text.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path

from .. import common, llm
from . import images
from . import page as page_mod


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

    from . import home  # home imports this module, so the import waits until build time
    content, glance, jsonld = home.render(
        ctx, today, built_iso, "", top, headlines, weather, chp, isa, escribe, board,
        alpr, airnow, calfire, sources.get("roads", {}))
    ctx.build_report["_digest_meta"] = "deterministic" if headlines else "no-headlines"

    page = page_mod.render(
        title=_big_title(top, today),
        desc=home.DESC,
        canonical="/",
        content=content,
        current="index",
        rel="",
        built=built_iso,
        jsonld=jsonld,
        statusbar=glance,
        template="home.html",
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
        "overnight_band": ctx.build_report.pop("_overnight_band", None),
        "archive": built_iso,
    }
    return built


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


# ---------------------------------------------------------------- the news
_DIGEST_CACHE = {}


def _get_digest(headlines: list[dict]) -> str | None:
    """LLM news digest, computed at most once per build (homepage + article
    both render it; we never pay for the same summarization twice)."""
    key = tuple(h.get("title", "") for h in headlines[:14])
    if key not in _DIGEST_CACHE:
        _DIGEST_CACHE[key] = llm.summarize_news(headlines[:14]) if headlines else None
    return _DIGEST_CACHE[key]


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


# ---------------------------------------------------------------- dates


def _board_date(board: dict) -> str:
    raw = (board or {}).get("date", "")
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


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


def _brief_pager(dstr: str, dates: list, rel: str) -> str:
    """Previous / next day links on a dated brief. Older briefs were reachable only from the
    /briefs/ list, one internal link each; this chains every day to its neighbours."""
    ds = sorted({d for d in dates if re.match(r"^\d{4}-\d{2}-\d{2}$", d or "")})
    if dstr not in ds:
        return ""
    i = ds.index(dstr)

    def lab(d):
        x = dt.date.fromisoformat(d)
        return f"{x:%a}, {x:%b} {x.day}"
    prev_l = (f'<a rel="prev" href="{rel}briefs/{ds[i - 1]}/">&larr; {lab(ds[i - 1])}</a>' if i > 0 else "<span></span>")
    next_l = (f'<a rel="next" href="{rel}briefs/{ds[i + 1]}/">{lab(ds[i + 1])} &rarr;</a>' if i < len(ds) - 1 else "<span></span>")
    return (f'<nav class="brief-pager" aria-label="Other days">{prev_l}'
            f'<a href="{rel}briefs/">All daily briefs</a>{next_l}</nav>')


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
    # 6 AM Pacific with the right offset for that date (-07:00 in summer, -08:00 in winter)
    try:
        stamp = dt.datetime.combine(dt.date.fromisoformat(iso), dt.time(6, 0),
                                    tzinfo=common.PACIFIC).isoformat()
    except ValueError:
        stamp = f"{iso}T06:00:00-07:00"
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": headline,
        "description": desc,
        "image": ["https://bakersfieldbrief.com/assets/img/bakersfield.jpg"],
        "datePublished": stamp,
        "dateModified": stamp,
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


_ALPR_WORDS = _BRIEF_TOPICS[1][0]


def _camera_towns(alpr: dict) -> dict:
    """slug -> name for the town camera maps this build writes. The briefs are built before
    those pages, so this asks the same plan the pages are built from."""
    from . import alpr_towns
    try:
        return {s: p["town"]["name"] for s, p in alpr_towns.plan({"alpr": alpr}).items()}
    except Exception as e:  # noqa: BLE001 - a brief is never lost to a link
        common.log(f"daily: town camera links skipped ({type(e).__name__}: {e})")
        return {}


def _town_camera_links(content_html: str, towns: dict | None) -> list[tuple[str, str]]:
    """The town camera maps a brief should link: a town with a page this build (towns is
    slug -> name) that one paragraph or list item names together with a plate-reader word.
    A town named in one story and a camera in another is no link."""
    picked = []
    for block in re.split(r"</p>|</li>|</h[1-6]>", content_html):
        text = _plain(block).lower()
        if not any(k in text for k in _ALPR_WORDS):
            continue
        for slug, name in (towns or {}).items():
            row = (f"surveillance/{slug}/", f"{name} Flock camera map")
            if re.search(rf"\b{re.escape(name.lower())}\b", text) and row not in picked:
                picked.append(row)
    return picked


def _related_trackers(rel: str, content_html: str, towns: dict | None = None) -> str:
    """Give every brief page a job: a path into the evergreen trackers that
    actually earn clicks. Chosen by what the day's brief mentions, topped up to
    at least three so a quiet news day still links somewhere useful. A brief on a
    town's plate readers also links that town's camera map, first."""
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
    picked = _town_camera_links(content_html, towns) + picked
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
    towns = _camera_towns(alpr)
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
        content=(_h2ify(content) + _related_trackers(rel, content, towns)
                 + _brief_pager(built_iso, [str(e.get("date", "")) for e in _load_archive()] + [built_iso], rel)),
        current="index", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                _brief_newsarticle(headline, dated_desc, built_iso)],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        og_type="article", og_image="https://bakersfieldbrief.com/assets/img/bakersfield.jpg",
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

    hub_body = (f"{_h2ify(hub_content)}\n\n{_related_trackers(index_rel, hub_content, towns)}"
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
            past_body = (_h2ify(stored) + _related_trackers(past_rel, stored, towns)
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
            canonical=f"/briefs/{dstr}/",
            content=past_body + _brief_pager(dstr, [str(x.get("date", "")) for x in entries], past_rel),
            current="index", rel=past_rel,
            built=built_iso, jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                                     _brief_newsarticle(past_headline, past_desc, dstr)],
            statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
            og_type="article", og_image="https://bakersfieldbrief.com/assets/img/bakersfield.jpg"))
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

