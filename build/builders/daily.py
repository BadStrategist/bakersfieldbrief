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

from .. import common, llm
from ..sources.airnow import css_class as _aqi_css
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

    headlines = news.get("headlines", [])
    top = headlines[0] if headlines else None

    rel = ""
    content = _page_content(ctx, today, built_iso, rel,
                            news, weather, chp, isa, escribe, board,
                            abc, food, alpr, airnow, headlines, top)

    jsonld = [
        page_mod.org_jsonld(),
        page_mod.website_jsonld(),
        {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": (top["title"] if top else f"Bakersfield Daily Brief — {_fmt_date(today)}"),
            "datePublished": built_iso,
            "dateModified": built_iso,
            "isAccessibleForFree": True,
            "publisher": {
                "@type": "NewsMediaOrganization",
                "name": "Bakersfield Daily Brief",
                "url": "https://bakersfieldbrief.com/",
                "logo": {"@type": "ImageObject",
                         "url": "https://bakersfieldbrief.com/assets/img/logo.svg",
                         "width": 100, "height": 100},
            },
            "mainEntityOfPage": "https://bakersfieldbrief.com/",
        },
    ]

    page = page_mod.render(
        title=f"Bakersfield Daily Brief — {_fmt_date(today)} | Kern County civic news",
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
                             escribe, board, abc, food, alpr, airnow, headlines)
    built.extend(archive_built)

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
                  escribe, board, abc, food, alpr, airnow, headlines, top) -> str:
    date_line = f"""
    <div class="date-line"><span>{today.strftime('%B').upper()} {today.day}, {today.year}</span><span>Bakersfield, California</span></div>"""

    hero, sidebar = _hero_row(top, headlines, today, rel)

    digest_html, digest_meta = _news(news, built_iso)
    ctx.build_report["_digest_meta"] = digest_meta
    conditions = _conditions(weather, chp, isa, airnow, built_iso)
    watch = _one_thing(escribe, board)

    cats = _category_grid(rel, escribe, board, abc, food, alpr)
    week = _week_grid(today, rel, weather, escribe, board, top)
    archive_html = _recent_briefs(rel)

    return f"""{date_line}
    <div class="brief-top">
      <div class="hero-col">
        {hero}
      </div>
      <aside class="sidebar-col">{sidebar}</aside>
    </div>

    <div class="ad-slot" data-ad-slot="home-hero" aria-hidden="true"></div>

    {conditions}
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


# ---------------------------------------------------------------- hero row
def _hero_row(top, headlines, today, rel) -> tuple[str, str]:
    if top:
        head = f'<a href="{html.escape(top.get("url", "#"))}" rel="noopener">{html.escape(top["title"])}</a>'
        src = f'<span class="hero-src">via {html.escape(top.get("source", "local news"))}</span>'
    else:
        head = "The Kern County news you\u2019d otherwise miss"
        src = ""

    hero = f"""
    <p class="today-label">{SUN_ICON} Today&rsquo;s Brief</p>
    <h1 class="today-h1">{head}</h1>
    <p class="lede">Plus the rest of the day&rsquo;s news from Bakersfield, Kern County, and beyond. {src}</p>
    <a class="read-more" href="#the-news">Read today&rsquo;s brief</a>"""

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


# ---------------------------------------------------------------- conditions
def _conditions(weather, chp, isa, airnow, built_iso) -> str:
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    if cur is not None and hi is not None:
        weather_v = f"{cur}&deg; / {hi}&deg;"
    elif hi is not None and lo is not None:
        weather_v = f"{hi}&deg; / {lo}&deg;"
    else:
        weather_v = "n/a"
    alerts = (weather or {}).get("alerts", [])
    alert_v = alerts[0]["event"] + " active" if alerts else "No active alerts"
    isa_last = isa.get("last")
    isa_v = f"{isa_last['value']:,} AF" if isa_last else "n/a"
    isa_pct = isa.get("pct")
    chp_new = chp.get("new", [])
    chp_v = f"{len(chp_new)} new" if chp_new else "None overnight"

    # AQI chip: real value when the key is set; honest states otherwise
    if airnow.get("ok") and airnow.get("aqi") is not None:
        cls = _aqi_css(airnow.get("category_num"))
        aqi_v = (f'<span class="{cls}">{airnow["aqi"]} &middot; {html.escape(airnow.get("category") or "")}'
                 f'</span> <span class="unit">{html.escape(airnow.get("parameter") or "")}</span>')
    elif airnow.get("needs_key"):
        aqi_v = 'Waiting for EPA AirNow key'
    else:
        aqi_v = 'Unavailable this build'

    return f"""
    <section aria-labelledby="h-conditions">
      <p class="sec-head" id="h-conditions">Conditions <span class="unit">weather · reservoir · incidents · air</span></p>
      <div class="cond-strip">
        <div class="cond-chip"><div class="l">Bakersfield weather</div><div class="v">{weather_v}</div></div>
        <div class="cond-chip"><div class="l">Weather alerts</div><div class="v {'amber' if alerts else ''}">{html.escape(alert_v)}</div></div>
        <div class="cond-chip"><div class="l">Isabella Lake</div><div class="v">{isa_v} <span style="font-size:13px;color:#57504A">({isa_pct}% cap)</span></div></div>
        <div class="cond-chip"><div class="l">CHP overnight</div><div class="v">{chp_v}</div></div>
        <div class="cond-chip"><div class="l">Air quality (AQI)</div><div class="v">{aqi_v}</div></div>
      </div>
      <p class="note" style="margin-top:10px">Alerts: National Weather Service &middot; Reservoir: CA DWR/CDEC &middot; Incidents: CHP &middot;
      Air: EPA AirNow &middot; Live temps: NWS gridpoint forecast + KBFL airport observation. Data refreshed each build.</p>
    </section>"""


# ---------------------------------------------------------------- the news
def _news(news: dict, built_iso: str) -> tuple[str, str]:
    headlines = news.get("headlines", [])
    digest = llm.summarize_news(headlines[:14]) if headlines else None
    if digest:
        digest_html = f"<div class='card'><p>{digest}</p></div>"
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

    def src_chip(h: dict) -> str:
        return f'<span class="src">{html.escape(h.get("source", "news"))}</span>'

    def card(label: str, group: list) -> str:
        lis = "".join(f"""
        <li><a href="{html.escape(h.get('url', '#'))}" rel="noopener">{html.escape(h['title'])}</a>{src_chip(h)}</li>"""
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
    <p class="ng-credit">Reporting by KGET 17 and 23ABC.</p>"""


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
    candidates = []
    for m in escribe.get("upcoming", []):
        for it in (m.get("items") or [])[:40]:
            candidates.append({"meeting": m.get("name", "City meeting"), "item": it.get("title", ""),
                               "date": m.get("start_iso", ""), "url": m.get("url", ""),
                               "text": it.get("text", "")})
    for it in board.get("items", [])[:60]:
        candidates.append({"meeting": "Kern County Board of Supervisors",
                           "item": it.get("title", ""),
                           "date": board.get("date", ""),
                           "url": "https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf",
                           "text": it.get("text", "")})

    pick = None
    if candidates:
        pick = llm.pick_thing_to_watch(candidates)
    if not pick and candidates:
        top = sorted(candidates, key=_score, reverse=True)[0]
        pick = (f"{top['item']} &mdash; a {html.escape(top['meeting'])} item scheduled for "
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
def _category_grid(rel, escribe, board, abc, food, alpr) -> str:
    # WHAT TO WATCH
    up = escribe.get("upcoming", [])
    if up:
        m = up[0]
        when = (m.get("start_iso") or "").replace("T", " · ")
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
    watch_card = f'<a class="cat-card" href="{html.escape(watch_href)}">{watch_inner}{watch_ext}<span class="card-go">View agenda</span></a>'

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
    decided_card = f'<a class="cat-card" href="{html.escape(decided_href)}">{decided_inner}<span class="card-go">Official agenda</span></a>'

    # AROUND TOWN
    abc_items = abc.get("items", []) if abc.get("ok") else []
    food_items = food.get("items", []) if food.get("ok") else []
    town_lines = []
    if abc_items:
        town_lines.append(f'<span class="cat-tag">New filing</span> {html.escape(abc_items[0].get("dba", "Liquor license application"))}')
    if food_items:
        f0 = food_items[0]
        fdate = f" ({_fmt_short_date(str(f0.get('closed_date', '')))})" if f0.get("closed_date") else ""
        town_lines.append(f'<span class="cat-tag red">Closed</span> {html.escape(f0.get("facility", "Food facility closure"))}{fdate}')
    if not town_lines:
        town_lines.append("No new filings or closures listed today.")
    town_card = f"""<a class="cat-card" href="{rel}openings/">
      <span class="cat-label">Around Town</span>
      <h3>New licenses &amp; closures</h3>
      <p>{'; '.join(town_lines)}</p>
      <span class="card-go">Openings &amp; Closings</span>
    </a>"""

    # IN DEPTH
    alpr_stats = alpr.get("stats", {}) if alpr.get("ok") else {}
    alpr_last4 = sum(e.get("new_count", 0) for e in alpr.get("change_log", [])[-4:])
    depth_line = (f"{alpr_stats.get('total', '—')} ALPR cameras mapped"
                  f" &middot; +{alpr_last4} in 4 weeks") if alpr_stats else "License plate reader tracker"
    depth_card = f"""<a class="cat-card" href="{rel}surveillance/">
      <span class="cat-label">In Depth</span>
      <h3>Flock &amp; ALPR tracker</h3>
      <p>{depth_line} &mdash; map, direction, and a real 13-week change log from OpenStreetMap.</p>
      <span class="card-go">Open the map</span>
    </a>"""

    return f'<div class="cat-grid">{watch_card}{decided_card}{town_card}{depth_card}</div>'


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
      <span class="arch-head"><a href="{rel}briefs/{html.escape(str(e.get('date', '')))}/">{html.escape(e.get('headline', 'Daily brief'))}</a></span>
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


def _archive(ctx, today, built_iso, top, news, weather, chp, isa,
             escribe, board, abc, food, alpr, airnow, headlines) -> list[str]:
    """Save a permanent copy of today's brief + refresh /briefs/ index."""
    built = []
    rel = "../../"  # briefs/<date>/index.html is 2 levels below site root
    content = _page_content(ctx, today, built_iso, rel,
                            news, weather, chp, isa, escribe, board,
                            abc, food, alpr, airnow, headlines, top)

    page = page_mod.render(
        title=f"Bakersfield Daily Brief — {_fmt_date(today)} (archive)",
        desc="Archived copy of today's Bakersfield Daily Brief.",
        canonical=f"/briefs/{built_iso}/",
        content=content, current="index", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
    )
    common.write(common.SITE / "briefs" / built_iso / "index.html", page)
    built.append(f"briefs/{built_iso}/index.html")

    # archive data
    entries = _load_archive()
    entry = {"date": built_iso,
             "headline": top["title"] if top else "No headlines fetched",
             "url": f"/briefs/{built_iso}/"}
    entries = [e for e in entries if e.get("date") != built_iso] + [entry]
    entries.sort(key=lambda e: e.get("date", ""))
    (common.DATA / "briefs_archive.json").write_text(
        json.dumps(entries, indent=1), encoding="utf-8")

    # archive index page (1 level deep → rel="../")
    index_rel = "../"
    rows = "".join(f"""
    <li class="arch-row">
      <span class="arch-date">{html.escape(str(e.get('date', '')))}</span>
      <span class="arch-head"><a href="{index_rel}briefs/{html.escape(str(e.get('date', '')))}/">{html.escape(e.get('headline', 'Daily brief'))}</a></span>
    </li>""" for e in reversed(entries))
    archive_body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Archive</p>
      <h1>All daily briefs</h1>
      <p class="lede">Every morning at 6 AM PT, the brief is saved here as a permanent copy.
      {len(entries)} brief{'' if len(entries) == 1 else 's'} on record.</p></div>
    </div>
    <div class="card"><ul class="arch-list">{rows}</ul></div>"""
    common.write(common.SITE / "briefs" / "index.html", page_mod.render(
        title="All daily briefs — archive | Bakersfield Daily Brief",
        desc="Archive of every Bakersfield Daily Brief, saved automatically each morning.",
        canonical="/briefs/", content=archive_body, current="other", rel=index_rel,
        built=built_iso, jsonld=[page_mod.org_jsonld()],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else ""))
    built.append("briefs/index.html")
    return built


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
