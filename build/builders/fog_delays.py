#!/usr/bin/env python3
"""Fog delays page — /fog-delays/ — Kern County school delays and closures.

One plain answer at the top (how many districts and schools have posted a delay
or a closure today), the board itself, the National Weather Service fog
advisory if one is up, and a season record nobody else keeps: every delay and
closure posted since this page started logging.

The board is whatever districts posted to the Kern County Superintendent of
Schools' AlertLine. A school that is missing from it has posted nothing there;
the page never says a school is "on time", because AlertLine does not say that.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import common
from . import page as page_mod

_ALERTLINE = "https://alertline.kern.org/"
_KIND_TAG = {"closure": ("red", "Closed"), "delay": ("amber", "Delayed"), "other": ("", "Alert")}


def _slug(site: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", site.lower()).strip("-")


def _clock(updated_at: str) -> str:
    """'2026-11-17 05:05:16' -> '5:05 AM'. AlertLine stamps are Kern County local time."""
    try:
        t = dt.datetime.strptime(updated_at[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    return t.strftime("%I:%M %p").lstrip("0")


def _long_date(d: dt.date) -> str:
    return d.strftime("%A, %B ") + str(d.day)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _status_text(a: dict) -> str:
    """The district's own wording, with its custom note when it wrote one."""
    desc = a.get("description") or a.get("category") or "Alert"
    if desc.lower() == "custom" and a.get("info"):
        return a["info"]
    return f"{desc}: {a['info']}" if a.get("info") else desc


def _summary(alerts: list) -> tuple[int, int, int]:
    delays = sum(1 for a in alerts if a["kind"] == "delay")
    closures = sum(1 for a in alerts if a["kind"] == "closure")
    return delays, closures, len(alerts) - delays - closures


def _headline(alerts: list) -> tuple[str, str, str]:
    """(big word, css class, spoken sentence fragment) for today's board."""
    delays, closures, other = _summary(alerts)
    if not alerts:
        return "No alerts posted", "big-open", "no delays or closures are posted"
    bits = []
    if delays:
        bits.append(_plural(delays, "delay", "delays"))
    if closures:
        bits.append(_plural(closures, "closure", "closures"))
    if other:
        bits.append(_plural(other, "other alert", "other alerts"))
    cls = "big-closed" if closures else "big-restrict"
    posted = "is posted" if len(alerts) == 1 else "are posted"
    return " · ".join(bits), cls, " and ".join(bits) + " " + posted


def _board(alerts: list) -> str:
    if not alerts:
        return ""
    rows = "".join(f"""
        <tr id="{_slug(a['site'])}"><td><strong>{html.escape(a['site'])}</strong></td>
        <td><span class="tag {_KIND_TAG[a['kind']][0]}">{_KIND_TAG[a['kind']][1]}</span>
        {html.escape(_status_text(a))}</td>
        <td class="num">{html.escape(_clock(a['updated_at']))}</td></tr>"""
                   for a in alerts)
    return f"""<div class="table-wrap"><table class="data">
          <thead><tr><th>District or school</th><th>Status</th><th class="num">Posted</th></tr></thead>
          <tbody>{rows}</tbody></table></div>"""


def _season_start(today: dt.date) -> dt.date:
    """School years run July through June."""
    return dt.date(today.year if today.month >= 7 else today.year - 1, 7, 1)


def _season(log: dict, today: dt.date) -> tuple[list, list]:
    """(days, sites) for the current school year, newest day first, most-affected site first."""
    start = _season_start(today).isoformat()
    days, sites = [], {}
    for day in sorted(log.get("days", {}), reverse=True):
        if day < start:
            continue
        alerts = log["days"][day]
        delays, closures, other = _summary(alerts)
        days.append({"day": day, "delays": delays, "closures": closures, "other": other,
                     "fog": any(a.get("fog") for a in alerts)})
        for a in alerts:
            s = sites.setdefault(a["site"], {"site": a["site"], "delays": 0, "closures": 0,
                                             "other": 0, "last": day})
            s[{"delay": "delays", "closure": "closures"}.get(a["kind"], "other")] += 1
            s["last"] = max(s["last"], day)
    ranked = sorted(sites.values(), key=lambda s: (-(s["delays"] + s["closures"]), s["site"]))
    return days, ranked


def _short_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return d.strftime("%a, %b ") + str(d.day)


def _season_html(log: dict, today: dt.date) -> str:
    days, sites = _season(log, today)
    started = log.get("started") or today.isoformat()
    since = _long_date(dt.date.fromisoformat(started)) + f", {started[:4]}"
    if not days:
        return (f'<div class="card"><p>Nothing has been posted since this record started on '
                f'{since}. Every delay and closure posted to AlertLine from that day on is '
                f'kept here, by day and by district. Earlier school years are not included '
                f'because AlertLine only publishes the current day.</p></div>')
    day_rows = "".join(f"""
        <tr><td>{_short_date(d['day'])}</td><td class="num">{d['delays']}</td>
        <td class="num">{d['closures']}</td><td class="num">{d['other']}</td></tr>"""
                       for d in days)
    site_rows = "".join(f"""
        <tr><td>{html.escape(s['site'])}</td><td class="num">{s['delays']}</td>
        <td class="num">{s['closures']}</td><td class="num">{_short_date(s['last'])}</td></tr>"""
                        for s in sites)
    fog_days = sum(1 for d in days if d["fog"])
    return f"""<div class="card"><p><strong>{_plural(fog_days, 'fog day', 'fog days')}</strong>
      and {_plural(len(days), 'day', 'days')} with any alert since this record started on
      {since}. Earlier school years are not included because AlertLine only publishes the
      current day.</p></div>
      <h3>By day</h3>
      <div class="table-wrap"><table class="data">
        <thead><tr><th>Day</th><th class="num">Delays</th><th class="num">Closures</th>
        <th class="num">Other</th></tr></thead><tbody>{day_rows}</tbody></table></div>
      <h3>By district or school</h3>
      <div class="table-wrap"><table class="data">
        <thead><tr><th>District or school</th><th class="num">Delays</th>
        <th class="num">Closures</th><th class="num">Most recent</th></tr></thead>
        <tbody>{site_rows}</tbody></table></div>"""


def _fog_advisories(weather: dict) -> list:
    if not (weather or {}).get("ok"):
        return []
    return [a for a in weather.get("alerts", []) if "fog" in (a.get("event") or "").lower()]


def _outlook_html(weather: dict) -> str:
    if not (weather or {}).get("ok"):
        return ('<div class="card"><p>National Weather Service alerts were unavailable this '
                'build. See <a href="https://www.weather.gov/hnx/" target="_blank" '
                'rel="noopener">weather.gov/hnx</a> for the current fog forecast.</p></div>')
    fog = _fog_advisories(weather)
    if not fog:
        return ('<div class="card"><p>No dense fog advisory is in effect for Kern County '
                'right now, according to the National Weather Service.</p></div>')
    items = "".join(
        f'<li><strong>{html.escape(a["event"])}</strong>: '
        f'{html.escape(a.get("headline") or a.get("areas") or "")}</li>' for a in fog)
    return (f'<div class="card"><ul class="hl">{items}</ul><p class="note">An advisory is a '
            'forecast of low visibility. It is not a delay: each district decides for itself '
            'on the morning.</p></div>')


def build(ctx, sources: dict) -> list[str]:
    built_iso = common.iso_today()
    today = ctx.today
    rel = "../"
    data = sources.get("alertline") or {}
    ok = bool(data.get("ok"))
    alerts = data.get("alerts", []) if ok else []
    log = data.get("log") or {"days": {}}
    weather = sources.get("weather") or {}

    fetched = data.get("fetched_at", "")
    asof = f"{_clock(fetched)} on {_long_date(today)}" if fetched else _long_date(today)
    word, cls, spoken = _headline(alerts)

    if ok:
        # .updated and .fog-spoken are what assets/js/fog-delays.js rewrites when it rechecks.
        live = (f'As of <span class="updated">{asof}</span>, '
                f'<span class="fog-spoken">{spoken}</span> on AlertLine')
        answer_tail = (f'{live}, '
                       f'the Kern County Superintendent of Schools\' notice board.')
        big = f"""
      <div class="big-status {cls}" id="fog-big">
        <p class="big-label">Kern County schools · today</p>
        <p class="big-word">{word}</p>
        <p class="big-note">Checked <span class="updated" id="fog-checked">{asof}</span>.
        A school that is not listed has posted nothing to AlertLine.</p>
      </div>"""
        faq_live = f'{live}, where Kern County school districts post delays and closures.'
    else:
        answer_tail = (f'AlertLine could not be read when this page was built on '
                       f'{_long_date(today)}. Check <a href="{_ALERTLINE}">alertline.kern.org</a> '
                       f'or your school directly.')
        big = f"""
      <div class="errorbox" id="fog-big">AlertLine could not be read when this page was built.
      Check <a href="{_ALERTLINE}" target="_blank" rel="noopener">alertline.kern.org</a> or
      your school directly.</div>"""
        faq_live = ("AlertLine could not be read when this page was last built. Check "
                    "alertline.kern.org or your school directly.")

    direct_answer = (f'<p class="answer"><strong>Is there a fog delay today in Kern County?'
                     f'</strong> {answer_tail}</p>')

    faq_qa = [
        ("Is there a fog delay today in Kern County?", faq_live),
        ("Where are Kern County school fog delays announced?",
         "Districts post them to AlertLine (alertline.kern.org), run by the Kern County "
         "Superintendent of Schools, and send their own calls, texts and app notices to "
         "families. This page reads AlertLine. A school that has posted nothing there does "
         "not appear here, so your school's own message is the final word."),
        ("What does a two-hour fog delay mean?",
         "School starts two hours later than its normal bell time and buses run two hours "
         "later than their normal pickup. Dismissal time usually stays the same; your "
         "school's notice says for certain."),
        ("Can a fog delay turn into a closure?",
         "Yes. A district can change a delay to a closure if the fog does not lift, so check "
         "again before you leave. The time next to each entry is when the district last "
         "updated it."),
        ("Why does Kern County get fog delays?",
         "Tule fog. On clear, calm winter nights the ground on the San Joaquin Valley floor "
         "cools and the damp air above it condenses into dense fog that can cut visibility "
         "to a few feet. It is most common from November through February and is thickest "
         "around sunrise, when school buses are on rural roads."),
    ]
    faq_html = "".join(
        f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq_qa)

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Schools · Kern County AlertLine</p>
      <h1>Kern County school fog delays today</h1>
      <p class="lede">Every delay and closure Kern County districts have posted today, on one
      page, with the time each was posted. Rechecked while this page is open.</p>
      <div class="meta"><span>AlertLine checked: <span class="updated">{asof}</span></span></div></div>
    </div>

    {direct_answer}

    {big}

    <section class="block">
      <div class="sign-head"><span class="tab">Today</span><h2>Delays and closures posted today</h2></div>
      <p><input type="search" id="fog-filter" placeholder="Find your district or school"
      aria-label="Find your district or school" hidden></p>
      <div id="fog-board">{_board(alerts) if alerts else
        '<p class="note">Nothing is posted on AlertLine right now.</p>' if ok else
        '<p class="note">The board is unavailable until AlertLine can be read.</p>'}</div>
      <p class="note">Source: <a href="{_ALERTLINE}" target="_blank" rel="noopener">Kern County
      Superintendent of Schools AlertLine</a>. Wording is each district's own.</p>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Outlook</span><h2>Fog advisories</h2></div>
      {_outlook_html(weather)}
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Record</span><h2>Fog delays this school year</h2></div>
      {_season_html(log, today)}
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">FAQ</span><h2>Fog delay questions</h2></div>
      <div class="card">{faq_html}</div>
    </section>

    <p class="note">Driving in fog? See <a href="../roads/">Kern County road conditions</a> for
    I-5, Highway 58 and Highway 99. This page reports what districts post and is not a
    substitute for your school's own notice.</p>"""

    page = page_mod.render(
        title="Kern County School Fog Delays Today: Live List by District | Bakersfield Daily Brief",
        desc="Is there a fog delay today? Every Kern County school delay and closure posted to "
             "the Superintendent of Schools' AlertLine, with the time posted, the fog advisory, "
             "and a running count of fog days this school year.",
        canonical="/fog-delays/", content=body, current="trackers", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq_jsonld(faq_qa)],
        extra_scripts='<script src="{rel}assets/js/fog-delays.js" defer></script>'.format(rel=rel))
    common.write(common.SITE / "fog-delays" / "index.html", page)

    ctx.build_report["fog_delays"] = {
        "ok": ok, "alerts": len(alerts),
        "logged_days": len(log.get("days", {})),
    }
    return ["fog-delays/index.html"]


def _faq_jsonld(faq_qa: list) -> dict:
    """FAQPage schema from the same list the page prints, so they cannot drift."""
    def _plain(s: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()

    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": _plain(a)}}
            for q, a in faq_qa
        ],
    }
