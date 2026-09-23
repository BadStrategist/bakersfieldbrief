#!/usr/bin/env python3
"""The Numbers — a weekly data article from the site's live trackers.

Original, keyless prose assembled from real series the site already collects:
Isabella reservoir, ALPR camera growth, CHP incidents, fires, air quality.
Regenerated every build; the numbers move, the write-up follows them."""
from __future__ import annotations

import datetime as dt
import html
import json
import re

from .. import common
from . import images
from . import page as page_mod

WEEK_DAYS = 7


def _iso_week_start(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=today.weekday())


def _pct_str(part, whole) -> str:
    try:
        return f"{100.0 * float(part) / float(whole):.1f}%"
    except Exception:  # noqa: BLE001
        return "n/a"


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    today = ctx.today
    rel = "../"
    week_start = _iso_week_start(today)
    week_end = week_start + dt.timedelta(days=6)

    # ---------------------------------------------------------- data pulls
    isa = sources.get("isabella", {}) or {}
    isa_last = isa.get("last", {}) or {}
    isa_af = isa_last.get("value")
    isa_cap = isa.get("capacity_af")
    isa_pct = isa.get("pct")
    # 7-day trend from the CDEC series (dates are non-zero-padded: '2026-8-6 00:00')
    def _cdec_date(s) -> dt.date | None:
        parts = str(s).split(" ")[0].split("-")
        if len(parts) == 3:
            try:
                return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                return None
        return None

    # the same weekly change /water/ prints (isabella.week_change), not a second definition
    from build.sources.isabella import week_change
    _wk = week_change(isa.get("storage_series") or isa.get("series", []))
    isa_delta = _wk["change"] if _wk else None

    alpr_log = []
    try:
        alpr_log = json.loads((common.DATA / "change_logs" / "alpr.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    # The last four WEEKS by date, not the last four entries: the log holds backfilled entries on
    # adjacent days (08-30 and 08-31), so four entries could span barely two weeks.
    alpr_weeks = []
    if isinstance(alpr_log, list) and alpr_log:
        try:
            _last = dt.date.fromisoformat(str(alpr_log[-1].get("date", ""))[:10])
            _from = (_last - dt.timedelta(days=28)).isoformat()
            alpr_weeks = [e for e in alpr_log if str(e.get("date", "")) > _from]
        except ValueError:
            alpr_weeks = []
    alpr_total = alpr_weeks[-1].get("total", 0) if alpr_weeks else 0
    alpr_added = sum(int(e.get("new_count", 0)) for e in alpr_weeks)
    alpr_span_end = alpr_weeks[-1].get("date", "") if alpr_weeks else ""
    # Prefer the live count /surveillance/ and the home card show (cameras first mapped in the
    # 28 days to the data date), so the three pages print one number.
    _alpr = sources.get("alpr", {}) or {}
    if _alpr.get("ok") and _alpr.get("cameras"):
        try:
            _to = dt.date.fromisoformat(str(_alpr.get("asof", ""))[:10])
            _cut = (_to - dt.timedelta(days=28)).isoformat()
            alpr_total = len(_alpr["cameras"])
            alpr_added = sum(1 for c in _alpr["cameras"] if (c.get("mapped") or "") >= _cut)
            alpr_span_end = _to.isoformat()
            alpr_weeks = alpr_weeks or [{"date": alpr_span_end}]
        except ValueError:
            pass

    chp_archive = []
    try:
        chp_archive = json.loads(
            (common.DATA / "snapshots" / "chp_archive.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    chp_week = []
    if isinstance(chp_archive, list):
        for e in chp_archive:
            m = re.search(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})", str(e.get("time", "")))
            if m:
                try:
                    d = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                             "%b %d %Y").date()
                except ValueError:
                    d = None
                if d and week_start <= d <= week_end:
                    chp_week.append(e)

    kern = [f for f in (sources.get("calfire", {}) or {}).get("incidents", [])
            if "Kern" in str(f.get("county", ""))]
    aq = sources.get("airnow", {}) or {}

    # ---------------------------------------------------------- prose
    paras = []

    if isa_af and isa_cap:
        trend = ""
        if isa_delta is not None:
            direction = "down" if isa_delta < 0 else "up"
            trend = (f" That is <strong>{direction} {abs(isa_delta):,} acre-feet "
                     f"({100.0 * abs(isa_delta) / int(isa_cap):.2f}% of capacity) "
                     f"in the last week.</strong>")
            if _wk:
                _f, _t = dt.date.fromisoformat(_wk["from"]), dt.date.fromisoformat(_wk["to"])
                trend = trend.replace("in the last week.</strong>",
                                      f"in the week of readings from {_f:%b} {_f.day} to {_t:%b} {_t.day}.</strong>")
        paras.append(
            f"<p><strong>Isabella Lake holds {int(isa_af):,} acre-feet — "
            f"{isa_pct}% of capacity.</strong>{trend} Storage in Kern County's largest reservoir "
            f"drives downstream allocations for the Kern River corridor and agriculture. "
            f'Follow the day-to-day on the <a href="{rel}water/">Isabella tracker</a>.</p>')

    if alpr_weeks:
        span = f"the four weeks to {alpr_span_end}"
        paras.append(
            f"<p><strong>Flock cameras keep multiplying: {alpr_total} mapped and counting.</strong> "
            f"In {span}, OpenStreetMap volunteers mapped "
            f"{alpr_added} new cameras. Every camera is a node on the map — location, direction, "
            f"and a 13-week change log live on the "
            f'<a href="{rel}surveillance/">Flock &amp; ALPR tracker</a>.</p>')

    if kern:
        names = ", ".join(html.escape(f.get("name", "fire")) for f in kern)
        paras.append(
            f"<p><strong>{len(kern)} active {'fire' if len(kern) == 1 else 'fires'} are burning "
            f"in Kern County:</strong> {names}. Fire activity is a constant of Kern summers — "
            f"CAL FIRE's incident list is checked every build, and the live count sits in the "
            f'<a href="{rel}">daily brief conditions</a>.</p>')

    if aq and aq.get("ok") and aq.get("aqi") is not None:
        cat = (aq.get("category") or "n/a").lower()
        paras.append(
            f"<p><strong>Air quality measured {aq['aqi']} — {html.escape(cat)}.</strong> "
            f"That is the EPA AirNow reading for Bakersfield, refreshed with each build. "
            f"Smoke from regional fires can move this number fast; the "
            f'<a href="{rel}">brief&rsquo;s air-quality chip</a> links to the live source.</p>')

    if chp_week:
        kinds = {}
        for e in chp_week:
            t = str(e.get("type", "Other"))
            kinds[t] = kinds.get(t, 0) + 1
        top_kind = max(kinds.items(), key=lambda kv: kv[1]) if kinds else (None, 0)
        paras.append(
            f"<p><strong>CHP logged {len(chp_week)} incidents around Kern this week.</strong> "
            f"The most common category was {html.escape(top_kind[0])} ({top_kind[1]} calls). "
            f"Incidents are archived from CHP's public feed so patterns — where crashes cluster, "
            f"what time of day — become visible over time.</p>")

    if len(paras) < 3:
        paras.append(
            "<p>The trackers are still accumulating history. As snapshots stack up, this page "
            "will read the trends — for now, the raw pages are linked above.</p>")

    paras.append(
        '<p class="note">The Numbers is generated automatically from the same public sources as '
        'the daily brief — CDEC (DWR), OpenStreetMap, CAL FIRE, EPA AirNow, and CHP. '
        'Report an error via the <a href="' + rel + 'corrections/">corrections page</a>.</p>')

    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Weekly data article</p>
    <h1>The Numbers</h1>
    <p class="lede">Kern County, measured — one article drawn from the site&rsquo;s live trackers.</p>
    <p class="date-line" style="margin-top:4px">{week_start.strftime('%B %d').replace(' 0', ' ')}&ndash;{week_end.strftime('%B %d, %Y').replace(' 0', ' ')}</p></div></div>
    {images.figure("oil", rel)}
    <article class="article-lead">
      {''.join(paras)}
    </article>
    <p class="sec-head">The trackers behind this article</p>
    <div class="link-grid">
      <a class="tile" href="{rel}water/"><strong>Isabella Lake</strong><span>live CDEC storage</span></a>
      <a class="tile" href="{rel}surveillance/"><strong>Flock &amp; ALPRs</strong><span>camera map + change log</span></a>
      <a class="tile" href="{rel}grapevine/"><strong>Grapevine conditions</strong><span>Caltrans, 3&times; daily</span></a>
      <a class="tile" href="{rel}tehachapi-pass/"><strong>Tehachapi Pass</strong><span>SR-58 + wind, 3&times; daily</span></a>
      <a class="tile" href="{rel}events/"><strong>Events</strong><span>what&rsquo;s on around town</span></a>
    </div>"""

    page = page_mod.render(
        title=f"The Numbers — week of {week_start.strftime('%B %d')} | Bakersfield Daily Brief".replace(' 0', ' '),
        desc="A weekly data article on Kern County: Isabella reservoir, Flock cameras, fires, air quality, and CHP incidents — from the site's live trackers.",
        canonical="/numbers/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "numbers" / "index.html", page)
    built.append("numbers/index.html")

    ctx.build_report["numbers"] = {
        "isabella_af": isa_af, "alpr_total": alpr_total,
        "kern_fires": len(kern), "aqi": aq.get("aqi"),
        "chp_week": len(chp_week)}
    return built
