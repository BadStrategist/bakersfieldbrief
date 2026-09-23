#!/usr/bin/env python3
"""The Sunday Read — /sunday-read/. A weekly long-form feature.

One Kern County topic, written fresh each Sunday from the week's real data
(headlines, CHP incidents, fires, reservoir, alerts, meetings) using the LLM
long-form writer in CI (LLM_API_KEY). Off-Sundays and keyless builds render
the last published feature from data/last_sunday_read.json so the page never
goes empty. Deterministic fallback assembles a long-form piece from the week's
facts with no LLM.
"""
from __future__ import annotations

import datetime as dt
import html
import json

from .. import common, llm
from ..chp_text import plain_location, plain_type
from . import images
from . import page as page_mod

CACHE = common.DATA / "last_sunday_read.json"
TOPIC_SLUGS = [
    ("Public safety", ("police", "shooting", "arrest", "crash", "court", "trial",
                       "dui", "fire", "incident", "fatal")),
    ("Wildfire season", ("fire", "wildfire", "evacuation", "burn", "containment",
                         "flame", "acre")),
    ("Water & the valley", ("reservoir", "lake", "isabella", "water", "drought",
                            "river", "groundwater")),
    ("Health", ("health", "hospital", "measles", "west nile", "virus", "clinic",
                "vaccin", "air quality")),
    ("The local economy", ("business", "jobs", "store", "market", "economy",
                           "vineyard", "wine", "agriculture", "crop")),
]


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"

    feature = _load_cache()
    if getattr(ctx, "sunday", False):
        feature = _write_feature(sources, built_iso)
        if feature:
            CACHE.write_text(json.dumps(feature, ensure_ascii=False), encoding="utf-8")
        else:
            feature = _load_cache()  # keep last good feature on write failure

    if not feature:
        feature = _fallback_offline(sources, built_iso)

    body = _render(feature, rel)
    page = page_mod.render(
        title="The Sunday Read — a long look at Kern County | Bakersfield Daily Brief",
        desc="The Sunday Read: a weekly, newsletter-length feature on one Kern County story, written from public records and linked reporting.",
        canonical="/sunday-read/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    common.write(common.SITE / "sunday-read" / "index.html", page)
    built.append("sunday-read/index.html")

    ctx.build_report["sunday_read"] = {
        "topic": feature.get("topic", ""),
        "source": feature.get("source", ""),
        "words": feature.get("words", 0),
        "asof": feature.get("date", built_iso),
    }
    return built


# ---------------------------------------------------------------- data
def _week_facts(sources: dict) -> str:
    """Plain-text dump of the week's verifiable facts for the LLM."""
    lines = ["WEEK OF", common.today_pacific().strftime("%B %d, %Y"), ""]

    news = sources.get("news_rss", {})
    heads = news.get("headlines", [])[:20]
    if heads:
        lines.append("LOCAL HEADLINES (source: title)")
        for h in heads:
            lines.append(f"- {h.get('source', 'news')}: {h.get('title', '')}")
        lines.append("")

    chp = sources.get("chp", {})
    # the 7-day archive, newest first: "new" is only what the previous build had not seen
    inc = list(reversed(chp.get("archive") or [])) or chp.get("new", [])
    if inc:
        lines.append("CHP INCIDENTS THIS WEEK")
        for i in inc[:12]:
            lines.append(f"- {i.get('time', '')}: {plain_type(i.get('type', ''))} at {plain_location(i.get('location', ''))}")
        lines.append("")

    cal = sources.get("calfire", {})
    fires = [f for f in cal.get("incidents", []) if "Kern" in str(f.get("county", ""))]
    if fires:
        lines.append("ACTIVE KERN FIRES (CAL FIRE)")
        for f in fires:
            lines.append(f"- {f.get('name', '')}: {f.get('acres', '')} acres, "
                         f"{f.get('percentContained', '')}% contained")
        lines.append("")

    isa = sources.get("isabella", {})
    if isa.get("ok") and isa.get("last"):
        last = isa["last"]
        _pct = isa.get("pct", last.get("pct"))
        lines.append(f"ISABELLA LAKE: {last.get('value', '')} acre-feet "
                     + (f"({_pct}% of capacity)" if _pct not in (None, "") else "")
                     + (f", 30-day trend: {isa.get('trend')}" if isa.get("trend") else ""))
        lines.append("")

    wx = sources.get("weather", {})
    if wx.get("ok"):
        for a in wx.get("alerts", [])[:3]:
            lines.append(f"WEATHER ALERT: {a.get('event', '')} — "
                         f"{a.get('headline', '')[:120]}")
        lines.append("")

    escribe = sources.get("escribe", {})
    meets = escribe.get("upcoming", [])[:5]
    if meets:
        lines.append("UPCOMING PUBLIC MEETINGS")
        for m in meets:
            lines.append(f"- {m.get('start_iso', '')}: {m.get('name', '')}")
        lines.append("")

    return "\n".join(lines)


def _pick_topic(facts: str) -> str:
    """Deterministic topic pick from the week's headlines (no LLM needed)."""
    news = facts.lower()
    for slug, kws in TOPIC_SLUGS:
        hits = sum(1 for k in kws if k in news)
        if hits >= 2:
            return slug
    return "Life in Kern County"


# ---------------------------------------------------------------- writing
def _write_feature(sources: dict, built_iso: str) -> dict | None:
    facts = _week_facts(sources)
    if not facts.strip():
        return None
    topic = _pick_topic(facts)
    # let the LLM refine the topic if it has a key; fallback to deterministic
    prose = llm.write_sunday_read(topic, facts)
    if prose:
        words = len(prose.split())
        return {"date": built_iso, "topic": topic, "source": "llm",
                "words": words, "body": prose}
    return _fallback_deterministic(topic, sources, built_iso)


def _fallback_deterministic(topic: str, sources: dict, built_iso: str) -> dict:
    """Keyless long-form: a structured, factual feature from real week data."""
    news = sources.get("news_rss", {}).get("headlines", [])[:12]
    cal = sources.get("calfire", {})
    fires = [f for f in cal.get("incidents", []) if "Kern" in str(f.get("county", ""))]
    isa = sources.get("isabella", {})
    chp = sources.get("chp", {})
    inc = (list(reversed(chp.get("archive") or [])) or chp.get("new", []))[:8]
    wx = sources.get("weather", {})
    alerts = wx.get("alerts", [])[:3] if wx.get("ok") else []
    escribe = sources.get("escribe", {})
    meets = escribe.get("upcoming", [])[:5]

    paras = [
        "<p>It has been a full week in Kern County"
        + (" — a week of fire, water, and the everyday business of the valley. " if fires
           else " — a week of the everyday business of the valley. ")
        + "This is the long-form look "
        "at what happened, assembled from public records and linked "
        "reporting.</p>",
    ]

    # 1. the news
    if news:
        lis = "".join(
            f'<li><a href="{html.escape(h.get("url", "#"))}" rel="noopener">'
            f'{html.escape(h["title"])}</a> <span class="src">'
            f'{html.escape(h.get("source", "news"))}</span></li>'
            for h in news[:8])
        paras.append(
            "<p><strong>The week in headlines.</strong> The stories Kern "
            "County followed this week:</p>"
            f'<ul class="story-list">{lis}</ul>'
            "<p>Each headline links to the original outlet. Together they "
            "sketch the week: the big incidents, the slow-burn issues, and "
            "the community moments in between.</p>")

    # 2. fires
    if fires:
        names = ", ".join(html.escape(f.get("name", "a fire")) for f in fires)
        details = "; ".join(
            f"{html.escape(f.get('name', ''))} at about {f.get('acres') or 'unknown':,}"
            f" acres ({f.get('percentContained') or 0}% contained)"
            for f in fires if f.get("acres"))
        paras.append(
            "<p><strong>Fire season is real this week.</strong> CAL FIRE lists "
            f"{len(fires)} active fire{'s' if len(fires) != 1 else ''} in Kern "
            f"County: {names}. {details}. For residents, these fires are more "
            "than a headline — they mean evacuation warnings, smoke, and "
            "roads closed at short notice. The county&rsquo;s fire history "
            "makes every dry stretch a watched one.</p>")

    # 3. water
    if isa.get("ok") and isa.get("last"):
        last = isa["last"]
        # the same weekly change /water/ and /numbers/ print; pct lives on the payload, not on
        # "last" (reading it from "last" printed "roughly —% of capacity")
        from build.sources.isabella import week_change
        wk = week_change(isa.get("storage_series") or isa.get("series", []))
        trend = (f" That is {'up' if wk['change'] >= 0 else 'down'} {abs(wk['change']):,} acre-feet "
                 f"over the past week." if wk and wk["change"] else "")
        pct = isa.get("pct", last.get("pct"))
        try:
            af = f"{int(round(float(last.get('value')))):,}"
        except (TypeError, ValueError):
            af = str(last.get("value", ""))
        paras.append(
            "<p><strong>The water that runs the valley.</strong> Lake Isabella "
            f"holds {af} acre-feet"
            + (f", about {pct}% of capacity." if pct not in (None, "") else ".")
            + f"{trend} The number matters "
            "beyond the reservoir itself: it shapes irrigation allotments, "
            "recreation, and the color of the hills into fall. California "
            "watches these figures through every season, and Kern County "
            "watches them closest of all.</p>")

    # 4. weather
    if alerts:
        ev = html.escape(alerts[0].get("event", "a weather alert"))
        head = html.escape((alerts[0].get("headline") or "")[:140])
        paras.append(
            "<p><strong>The weather on top of it.</strong> "
            f"{ev} — {head}. When heat and fire arrive together, the "
            "practical advice is simple and the stakes are not: check on "
            "neighbors, keep water close, and watch official alerts.</p>")

    # 5. roads
    if inc:
        il = "; ".join(html.escape(f"{plain_type(i.get('type')).lower() if i.get('type') else 'an incident'} at {plain_location(i.get('location')) or 'an unlisted location'}")
                       for i in inc[:5])
        paras.append(
            "<p><strong>On the roads.</strong> CHP logged its share of "
            f"incidents across the county this week, including {il}. "
            "None of it made for a quiet commute, and all of it is a "
            "reminder of how much of Kern&rsquo;s daily life moves on "
            "two-lane highways and long straight miles.</p>")

    # 6. the week ahead
    if meets:
        ml = "; ".join(html.escape(m.get("name", "a public meeting"))
                       for m in meets[:4])
        paras.append(
            "<p><strong>The week ahead.</strong> The public calendar carries "
            f"its usual weight: {ml}. Meetings are where the valley&rsquo;s "
            "decisions get made — from planning to public safety — and "
            "they are open to anyone who shows up.</p>")

    # 7. close
    paras.append(
        "<p><strong>The through-line.</strong> Fire, water, weather, roads, "
        "and a calendar of decisions — this is what a week in Kern County "
        "looks like when you pull it together. The Daily Brief tracks it "
        "day by day; the Sunday Read is the weekly pull-back that shows how "
        "the pieces fit.</p>")

    body = "".join(paras)
    return {"date": built_iso, "topic": topic, "source": "deterministic",
            "words": sum(len(p.split()) for p in paras), "body": body}


def _fallback_offline(sources: dict, built_iso: str) -> dict:
    return _fallback_deterministic("Life in Kern County", sources, built_iso)


def _load_cache() -> dict | None:
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        return d if d.get("body") else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- render
def _render(f: dict, rel: str) -> str:
    topic = html.escape(f.get("topic", "Kern County"))
    date_txt = html.escape(str(f.get("date", "")))
    body = f.get("body", "")
    src = f.get("source", "")

    if src == "llm":
        # LLM prose may contain ## section headings — convert to styled ones
        import re
        body = html.escape(body, quote=False)   # LLM text is text, never markup
        body = re.sub(r"^##\s+(.+)$", r'<h3 class="sunday-h">\1</h3>',
                      body, flags=re.M)
        body = "".join(f"<p>{p.strip()}</p>" for p in body.split("\n\n") if p.strip())
        meta = "Written by the Sunday Read desk from this week's public records."
    else:
        meta = "Compiled automatically from this week's public records and linked reporting."

    return f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">The Sunday Read</p>
      <h1>The Sunday Read: {topic}</h1>
      <p class="lede">A weekly, newsletter-length look at one Kern County story —
      assembled from public records and linked reporting.</p>
      <div class="meta"><span>Week of {date_txt}</span><span class="dot">&bull;</span>
      <span>published Sundays</span></div></div>
    </div>
    {images.figure("oil", rel)}
    <article class="article-lead sunday-body">
      {body}
    </article>
    <p class="note" style="margin-top:14px">{meta} Every fact links to its source;
    the <a href="/">Daily Brief</a> covers the week in full.</p>
    """
