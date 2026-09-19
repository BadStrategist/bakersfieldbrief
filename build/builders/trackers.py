#!/usr/bin/env python3
"""Trackers — auto-updating evergreen pages.

  /trackers/       hub (registry-driven: add a dict entry to add a tracker)
  /surveillance/   Flock & ALPR tracker (Leaflet map, stats, change log)
  /water/          Isabella Lake / Kern River storage tracker

Pattern for every tracker: source JSON inlined into a static template via the
/*__DATA__*/null placeholder → zero client-side data fetching. Weekly change
logs for the ALPR diff live in data/change_logs/alpr.json.

To ADD a tracker: 1) write a source module in build/sources/,
2) add a "tracker" entry to TRACKERS below with a render fn + template,
3) it appears on /trackers/ and in the weekly workflow automatically.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json

from .. import common
from . import images
from . import page as page_mod


def _js_ver(map_js: str) -> str:
    """Content hash of a tracker JS file — the cache-busting query param.

    Date-based (?v=YYYY-MM-DD) failed us: a same-day JS edit left the query
    unchanged, so returning browsers kept serving the cached old file (e.g.
    the watermarked CARTO map). A hash changes on EVERY content change, so
    browsers always pick up edits while still caching unchanged files.
    """
    try:
        b = (common.ROOT / "assets" / "js" / map_js).read_bytes()
        return hashlib.sha1(b).hexdigest()[:10]
    except OSError:
        return common.iso_today()


def _asset_ver_css() -> str:
    """Content hash of assets/css/deflock.css — the cache-busting query param.

    Same rationale as _js_ver: NEVER date-based (a same-day CSS edit would keep
    the same ?v and returning browsers would serve the stale file). Hash changes
    on every content change."""
    try:
        b = (common.ROOT / "assets" / "css" / "deflock.css").read_bytes()
        return hashlib.sha1(b).hexdigest()[:10]
    except OSError:
        return common.iso_today()


# ------------------------------------------------------------------ registry
TRACKERS = {}  # slug -> dict(name=..., lede=..., build=callable)


def register(slug: str, name: str, lede: str, build_fn):
    TRACKERS[slug] = {"name": name, "lede": lede, "build": build_fn}


def build(ctx, sources: dict) -> list[str]:
    """Entry point used by build_all: render every registered tracker page."""
    for meta in TRACKERS.values():
        meta["build"](ctx, sources)
    return [f"{s}/index.html" for s in TRACKERS]


# ------------------------------------------------------------------ SVG charts
def svg_line_chart(points: list[float], *, width: int = 860, height: int = 200,
                   labels: list[str] | None = None) -> str:
    """Baked inline SVG line chart (no client-side chart lib).

    Includes a left Y-axis (gridlines + rounded labels) so a normal seasonal
    decline reads as a shallow slope, not a steep crash drawn across the full
    height."""
    if len(points) < 2:
        return ""
    mn, mx = min(points), max(points)
    span = (mx - mn) or 1
    pad = 10
    axis_w = 52  # gutter for Y-axis labels
    n = len(points)
    plot_w = width - 2 * pad - axis_w
    xs = [pad + axis_w + i * plot_w / (n - 1) for i in range(n)]
    ys = [height - pad - (v - mn) * (height - 2 * pad) / span for v in points]
    path = " ".join(f"L{x:.1f},{y:.1f}" for x, y in zip(xs[1:], ys[1:]))
    area = f"M{xs[0]:.1f},{height - pad} L{xs[0]:.1f},{ys[0]:.1f} {path} L{xs[-1]:.1f},{height - pad} Z"
    pts = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#1A2126"/>'
                  for x, y in zip(xs, ys))
    last_label = f'<text x="{xs[-1]:.1f}" y="{ys[-1] - 8:.1f}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="12" fill="#4A545C">{points[-1]:,.0f}</text>'
    first_label = f'<text x="{xs[0]:.1f}" y="{ys[0] + 14:.1f}" text-anchor="start" font-family="IBM Plex Mono, monospace" font-size="12" fill="#4A545C">{points[0]:,.0f}</text>'

    # Y-axis: 4 gridlines with rounded labels spanning [mn, mx]
    grid = ""
    for i in range(4):
        v = mn + span * i / 3
        y = height - pad - (v - mn) * (height - 2 * pad) / span
        grid += (f'<line x1="{pad + axis_w:.1f}" y1="{y:.1f}" x2="{width - pad:.1f}" y2="{y:.1f}" '
                 f'stroke="#E4DED2" stroke-width="1"/>'
                 f'<text x="{pad + axis_w - 6:.1f}" y="{y + 4:.1f}" text-anchor="end" '
                 f'font-family="IBM Plex Mono, monospace" font-size="11" fill="#8A9299">{v:,.0f}</text>')

    return f"""<svg viewBox="0 0 {width} {height}" role="img" aria-label="30-day trend chart">
      {grid}
      <path d="{area}" fill="#DC9A1F" opacity="0.18"/>
      <path d="M{xs[0]:.1f},{ys[0]:.1f} {path}" fill="none" stroke="#232B30" stroke-width="2.5" stroke-linejoin="round"/>
      {pts}{first_label}{last_label}
    </svg>"""


def _stat(value_html: str, label: str, cls: str = "") -> str:
    return f'<div class="stat {cls}"><div class="n">{value_html}</div><div class="l">{label}</div></div>'


def _faq_visible(faq_jsonld: dict | None, heading: str) -> str:
    """Render the SAME Q&A that lives in the FAQPage JSON-LD as visible page
    content. Because both are built from one faq_jsonld dict, the on-page text
    and the schema can never drift. Returns '' when there is nothing to render."""
    if not faq_jsonld:
        return ""
    items = faq_jsonld.get("mainEntity", [])
    if not items:
        return ""
    parts = [f'<p class="sec-head">{heading}</p>']
    for q in items:
        name = html.escape(str(q.get("name", "")))
        ans = html.escape(str(q.get("acceptedAnswer", {}).get("text", "")))
        parts.append(f'<p class="pr-q"><strong>Q: {name}</strong></p>')
        parts.append(f"<p>{ans}</p>")
    return "\n".join(parts)


# ------------------------------------------------------------------ ALPR
def build_alpr(ctx, sources: dict):
    data = sources.get("alpr", {})
    stats = data.get("stats", {})
    change_log = data.get("change_log", [])
    cameras = data.get("cameras", [])
    asof = data.get("asof", common.iso_today())

    payload = {"cameras": cameras, "stats": stats,
               "change_log": change_log, "asof": asof}

    # newest mapped cameras (real OSM edit dates)
    dated = [c for c in cameras if c.get("mapped")]
    dated.sort(key=lambda c: c["mapped"], reverse=True)
    newest_top = dated[:6]
    newest_full = dated[:12]

    # Honest "last 4 weeks" count: derive it from each camera's OSM `mapped`
    # edit date, not from the change log. The change log proved unreliable
    # (a pre-Aug-30 bug advanced the snapshot every build, permanently zeroing
    # several weekly `new_count` entries), while `mapped` is a live OSM
    # timestamp recomputed every build — the same 28-day logic the map's
    # "Highlight newest" ring already uses, so stat and map always agree.
    stat_ok = bool(data.get("ok"))
    last4 = 0
    if stat_ok and cameras:
        try:
            asof_d = dt.date.fromisoformat(str(asof)[:10])
            cutoff = (asof_d - dt.timedelta(days=28)).isoformat()
            last4 = sum(1 for c in cameras
                        if c.get("mapped") and c["mapped"] >= cutoff)
        except ValueError:
            last4 = 0

    newest_date = stats.get("newest_mapped", "—")
    # Honest overlay counts: on a data failure show "—" not a false "0".
    ov_total = (str(stats.get("total", 0)) if stat_ok else "—")
    ov_flock = (str(stats.get("flock", 0)) if stat_ok else "—")
    ov_last4 = (f"+{last4}" if stat_ok else "—")

    if data.get("ok"):
        stat_html = (
            _stat(f"{stats.get('total', 0)}", "ALPR cameras mapped", "") +
            _stat(f"{stats.get('flock', 0)}", "Flock Safety units", "amber") +
            _stat(f"{newest_date}", "newest mapped on OSM", "") +
            _stat(f"+{last4}", "new cameras, last 4 weeks", "amber")
        )
    else:
        stat_html = '<div class="errorbox">Overpass/OSM data unavailable this build.</div>'

    # overlay "newest cameras" list — each link carries the camera's coords
    # so the map can fly to it and zoom to street level (see trackers.js)
    if newest_top:
        ov_items = "".join(f"""
        <li>
        <a href="#" class="ov-cam" data-id="{c['id']}" data-lat="{c.get('lat', '')}"
           data-lon="{c.get('lon', '')}" data-dir="{html.escape(str(c.get('direction', '')))}">
        {html.escape(str(c.get('mapped', '')))}</a>
        <span class="ov-meta">{html.escape(c.get('manufacturer', ''))}
        {('· facing ' + html.escape(c['direction'])) if c.get('direction') else ''}</span></li>"""
                           for c in newest_top)
        overlay_list = f'<h4>Newest cameras</h4><ol class="ov-list">{ov_items}</ol>'
    else:
        overlay_list = ""

    map_html = f"""
    <div class="mapwrap deflock">
      <div id="alpr-map" role="application" aria-label="Map of license plate reader camera locations"></div>
      <div class="map-overlay" id="map-overlay">
        <div class="ov-head">
          <h3>Flock &amp; ALPRs <span>&middot; Kern County</span></h3>
          <button type="button" class="ov-min" aria-expanded="true"
                  aria-label="Close panel" title="Close panel">&#8722;</button>
        </div>
        <div class="ov-stats">
          <div><span class="n">{ov_total}</span> cameras mapped</div>
          <div><span class="n">{ov_flock}</span> Flock Safety</div>
          <div><span class="n">{ov_last4}</span> new in 28 days</div>
        </div>
        <button id="toggle-newest" class="ov-btn" aria-pressed="false">Highlight newest (28 days)</button>
        <p class="ov-note" id="newest-note">All cameras shown — ring markers mark the last 28 days of mapping.</p>
        {overlay_list}
        <div class="map-legend" id="map-legend-stats"></div>
        <button type="button" id="ov-toggle" class="ov-toggle" aria-expanded="true"
                aria-label="Close panel" title="Close panel">Close</button>
      </div>
    </div>"""

    # change log table
    if change_log:
        rows = "".join(f"""
        <tr><td>{html.escape(str(e.get('date', '')))}</td>
        <td class="num">{e.get('total', '—')}</td>
        <td class="num {'hot' if e.get('new_count') else ''}">+{e.get('new_count', 0)}</td>
        <td>{html.escape(', '.join(map(str, e.get('new_ids', [])[:4]))) or '—'}{'…' if len(e.get('new_ids', [])) > 4 else ''}</td></tr>"""
                       for e in reversed(change_log[-14:]))
        log_table = f"""
        <div class="table-wrap"><table class="data">
          <thead><tr><th>Week ending</th><th class="num">Total mapped</th><th class="num">New</th><th>Newly mapped node IDs</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>"""
    else:
        log_table = '<p class="note">No weekly snapshots recorded yet.</p>'

    # newest full list (below map)
    if newest_full:
        nl = "".join(f"""
        <li><span class="n-date">{html.escape(str(c.get('mapped', '')))}</span>
        <span class="n-meta">{html.escape(c.get('manufacturer', ''))}{(' · facing ' + html.escape(c['direction'])) if c.get('direction') else ''}
        &middot; <a href="https://www.openstreetmap.org/node/{c['id']}" target="_blank" rel="noopener">node {c['id']}</a></span></li>"""
                     for c in newest_full)
        newest_list = f'<ul class="newest-list">{nl}</ul>'
    else:
        newest_list = '<p class="note">No cameras with OSM mapped dates yet.</p>'

    body = f"""
    {map_html}

    <div class="stats">{stat_html}</div>

    <div class="brief-grid" style="margin-top:6px">
      <div class="brief-main">
        <p class="sec-head">Change log <span class="unit">weekly snapshots, last 14 weeks</span></p>
        {log_table}
        <div class="callout"><strong>What &ldquo;new&rdquo; means:</strong> every weekly run diffs the
        mapped node IDs against the previous snapshot. Newly mapped cameras appear in the week they
        were added to OpenStreetMap &mdash; which is <strong>not</strong> the same as when the hardware
        went up (see caveat below).</div>
      </div>
      <div class="sidebar">
        <div class="side-box">
          <h2>Newest cameras</h2>
          {newest_list}
        </div>
      </div>
    </div>

    <div class="card">
      <span class="tag amber">Flock · ALPR</span>
      <h3>What this tracker shows</h3>
      <p>Bakersfield is one of the most camera-dense cities in California for automated license
      plate readers. This page maps every ALPR camera that volunteers have recorded in
      OpenStreetMap inside the Bakersfield metro, most of which are Flock Safety units. The map
      updates weekly; camera markers show manufacturer, operator, facing direction, and the date
      the node was mapped.</p>
      <p>Understanding where plate readers are mounted is public-record information that helps
      residents know when their vehicle&rsquo;s movements are being recorded. This page offers
      <strong>no guidance on avoiding or interfering with these devices</strong> &mdash; they are
      legal equipment operated by law enforcement and private property owners.</p>
      <p><strong>Important caveat:</strong> OpenStreetMap is crowdsourced. A camera&rsquo;s
      mapping date is <strong>not</strong> its installation date &mdash; a node may have been added
      months or years after the hardware went up, and mapping can lag or be incomplete. Direction
      tags are also volunteer-supplied.</p>
    </div>

    <p class="note">Data: &copy; OpenStreetMap contributors (ODbL), queried via the Overpass API
    with node edit timestamps. Map tiles: &copy; OpenStreetMap contributors / Esri World Street Map.
    Change log backfilled from real OSM node history on site setup.</p>"""

    flock_n = stats.get("flock", 0)
    total_n = stats.get("total", 0)

    faq_jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "How many Flock cameras are in Bakersfield?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (f"Based on volunteer-mapped OpenStreetMap data, {flock_n} Flock Safety "
                             f"cameras are mapped in Bakersfield and Kern County, out of {total_n} "
                             f"total license plate reader (ALPR) cameras, as of {asof}."
                             if data.get("ok") else
                             "A current count is unavailable because the camera data source "
                             "(OpenStreetMap) did not load this build. Use the map and stats once "
                             "data is restored.")
                }
            },
            {
                "@type": "Question",
                "name": "Where are the Flock cameras in Bakersfield?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (f"This page shows a live map of all {total_n} mapped license plate reader "
                             f"cameras in the Bakersfield metro, {flock_n} of which are Flock Safety "
                             f"units. Each camera marker shows its manufacturer, operator, and facing "
                             f"direction."
                             if data.get("ok") else
                             "The camera map cannot be shown right now because the data source "
                             "(OpenStreetMap) did not load this build. Check back once data is restored.")
                }
            },
            {
                "@type": "Question",
                "name": "Are Flock cameras legal in California?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("Automated license-plate reader (ALPR) use by law enforcement is "
                             "generally lawful in California, subject to state and local restrictions. "
                             "Flock and similar systems must comply with California's ALPR statutes, and "
                             "specific rules vary by agency. This page maps publicly visible cameras and "
                             "offers no guidance on avoiding or interfering with them.")
                }
            },
            {
                "@type": "Question",
                "name": "How long do Flock cameras keep data?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("Data retention varies by agency. California law requires agencies that use "
                             "ALPR to publish a retention schedule, so check the specific law-enforcement "
                             "agency's policy rather than assuming a single number. This page does not "
                             "track or report on stored plate data.")
                }
            }
        ]
    }

    # visible declarative answer + honest scope note (resolves the count vs.
    # commercial maps) — same asof as the FAQ schema and the template meta.
    # Only when OSM data actually loaded: on a fetch failure the stats box
    # already says "unavailable", and we must NOT assert "0 cameras".
    if data.get("ok"):
        body = (
            f'<p class="callout"><strong>{flock_n} Flock Safety cameras and {total_n} total '
            f'license-plate readers</strong> are mapped in Bakersfield and Kern County as of '
            f'{asof}. See them on the map below. Count reflects ALPR cameras mapped in '
            f'OpenStreetMap within the Bakersfield metro area as of {asof} — a smaller scope '
            f'than some commercial maps.</p>'
        ) + body

    # on-page lede + meta description — never assert "0 cameras" on a fetch failure
    if data.get("ok"):
        desc = (f"See every license plate reader in Bakersfield on a live map — {flock_n} "
                f"Flock Safety cameras and {total_n} total ALPR units mapped in the metro, "
                f"with facing direction, newest-camera highlights, and a weekly change log "
                f"from OpenStreetMap.")
    else:
        desc = ("Live map of license-plate reader (ALPR) and Flock Safety cameras in "
                f"Bakersfield — data source (OpenStreetMap) was unavailable this build. "
                f"Check back for the latest camera map and change log. Last successful as of "
                f"{asof}.")

    # render the same Q&A visibly so on-page text and schema never drift
    body += _faq_visible(faq_jsonld, "Flock &amp; ALPR questions")

    _write_tracker(ctx, "surveillance", "Flock Camera Map — Bakersfield",
                   desc,
                   stat_html, body, payload, sources, dark=True, img="flock",
                   seo_title="Bakersfield Flock Camera Map | Live ALPR Tracker",
                   faq_jsonld=faq_jsonld)


# ------------------------------------------------------------------ fires
def build_fires(ctx, sources: dict):
    data = sources.get("calfire", {})
    ok = bool(data.get("ok"))
    asof = data.get("asof", common.iso_today())
    incidents = data.get("incidents", [])
    kern = data.get("kern", [])

    # Last-known-good fallback: on a failed fetch, surface the snapshot's real
    # last-known state + its asof instead of a fabricated empty/zero. The page
    # is never presented as "0 fires" when the source is actually down.
    if not ok:
        last = data.get("last") or {}
        last_asof = last.get("asof")
        if last:
            incidents = last.get("incidents", incidents)
            kern = last.get("kern", kern)
            asof = last_asof or asof

    payload = {"incidents": incidents, "kern": kern, "asof": asof, "ok": ok}

    kern_acres = sum(int(float(i.get("acres") or 0)) for i in kern)
    if ok:
        stat_html = (
            _stat(f"{len(kern)}", "active fires in Kern County", "amber") +
            _stat(f"{kern_acres:,}", "acres burning in Kern", "amber") +
            _stat(f"{len(incidents)}", "active fires in California", "") +
            _stat(asof, "data as of", "")
        )
    else:
        last_txt = f" (last confirmed {asof})" if asof else ""
        stat_html = (f'<div class="errorbox">CAL FIRE data source did not load '
                     f'this build{last_txt}. Showing last-known data; check back '
                     f'shortly.</div>')

    # ---- map (fires use their own JS; marker: flame pin)
    # On a failed fetch the overlay must not claim "0 active" — say unavailable.
    if ok:
        kern_count_txt, ca_count_txt, asof_txt = len(kern), len(incidents), asof
    else:
        kern_count_txt = ca_count_txt = "unavailable"
        asof_txt = f"as of {asof}" if asof else "unavailable"
    map_html = """
    <div class="mapwrap deflock">
      <div id="fires-map" role="application" aria-label="Map of active wildfires in California and Kern County"></div>
      <div class="map-overlay" id="map-overlay">
        <h3>Active wildfires <span>&middot; Kern County + California</span></h3>
        <div class="ov-stats">
          <div><span class="n" id="fire-kern-count">{kern}</span> active in Kern</div>
          <div><span class="n" id="fire-ca-count">{all_n}</span> active in CA</div>
          <div><span class="n" id="fire-asof">{asof}</span> data as of</div>
        </div>
        <div class="map-legend" id="map-legend-stats"></div>
      </div>
    </div>""".format(kern=kern_count_txt, all_n=ca_count_txt, asof=asof_txt)

    # ---- incident cards (Kern first, then others)
    def card(i):
        acres = i.get("acres")
        acres_txt = f"{float(acres):,.0f}" if acres not in (None, "") else "n/a"
        cont = i.get("contained")
        cont_txt = f"{float(cont):.0f}%" if cont not in (None, "") else "n/a"
        kern_tag = '<span class="tag amber">Kern County</span>' if "Kern" in str(i.get("county", "")) else ""
        loc = i.get("location") or i.get("county", "")
        return f"""
        <div class="card fire-card">
          <span class="tag">{html.escape(str(i.get('type', 'Wildfire')))}</span>{kern_tag}
          <h3><a href="{html.escape(i.get('url', '#'))}" rel="noopener">{html.escape(str(i.get('name', 'Incident')))}</a></h3>
          <p>{html.escape(str(loc))}{(' &middot; started ' + html.escape(str(i.get('started', '')))) if i.get('started') else ''}</p>
          <div class="stat-row">
            <span><strong>{acres_txt}</strong> acres</span>
            <span><strong>{cont_txt}</strong> contained</span>
          </div>
        </div>"""

    kern_cards = "".join(card(i) for i in kern)
    other_cards = "".join(card(i) for i in incidents if "Kern" not in str(i.get("county", "")))

    if not ok:
        # Honest failure state: never present "0 fires" or "no fires" as if the
        # source is live. Show last-known data (if a snapshot exists) under a
        # clear "source did not load" banner + last-confirmed asof.
        last_txt = f", last confirmed {asof}" if asof else ""
        kern_section = f"""
        <div class="card"><span class="tag amber">Kern County</span>
        <h3>CAL FIRE data source did not load this build{last_txt}</h3>
        <p>The official CAL FIRE feed was unreachable when this page was built.{" Showing the last-known incident data below." if (kern_cards or other_cards) else " No last-known incident data is available yet."}
        Check back shortly — this page refreshes automatically.</p></div>"""
        if kern_cards:
            kern_section += (f'<p class="sec-head">Kern County <span class="unit">last-known</span>'
                             f'</p><div class="grid cols-2">{kern_cards}</div>')
        others_section = ""
        if other_cards:
            others_section = (f'<p class="sec-head" style="margin-top:26px">Active fires in California'
                              f' <span class="unit">last-known</span></p><div class="grid cols-2">{other_cards}</div>')
    elif kern_cards:
        kern_section = f'<p class="sec-head">Kern County <span class="unit">active fires</span></p><div class="grid cols-2">{kern_cards}</div>'
        others_section = f'<p class="sec-head" style="margin-top:26px">Active fires in California <span class="unit">{len(incidents)} statewide</span></p><div class="grid cols-2">{other_cards}</div>' if other_cards else ""
    else:
        kern_section = f"""
        <div class="card"><span class="tag amber">Kern County</span>
        <h3>No active fires in Kern County right now</h3>
        <p>As of {asof}, CAL FIRE lists no active wildfires in Kern County. When one ignites,
        it appears here automatically at the next build &mdash; with acres, containment, and
        location. Active fires elsewhere in California are listed below.</p></div>"""
        others_section = f'<p class="sec-head" style="margin-top:26px">Active fires in California <span class="unit">{len(incidents)} statewide</span></p><div class="grid cols-2">{other_cards}</div>' if other_cards else ""

    body = f"""
    {map_html}

    <div class="stats">{stat_html}</div>

    <div id="fires-list" data-fires-list class="live-fires-list" aria-live="polite"></div>

    {kern_section}
    {others_section}

    <div class="card">
      <span class="tag amber">Fire · CAL FIRE</span>
      <h3>How this tracker works</h3>
      <p>This page pulls the official <strong>CAL FIRE incident feed</strong> (fire.ca.gov) at every
      build and shows every active wildfire, with Kern County called out first. Data comes from
      the state&rsquo;s own public API &mdash; not from us &mdash; so acres, containment, and status
      are exactly what CAL FIRE reports.</p>
      <p><strong>Important:</strong> CAL FIRE covers state and federal wildland fires; it does not
      list every structure fire or medical call (Kern County Fire&rsquo;s dispatch is separate).
      For evacuation orders and preparedness, see <a href="https://kerncountyfire.org/education-safety/ready-kern/" rel="noopener" target="_blank">ReadyKern</a> and
      <a href="https://www.fire.ca.gov/" rel="noopener" target="_blank">fire.ca.gov</a>.</p>
    </div>

    <p class="note">Data: &copy; CAL FIRE / fire.ca.gov public incident feed. Fire perimeters and
    status update continuously; this page rebuilds every few hours.</p>"""

    faq_jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "How many fires are burning in Kern County right now?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (f"As of {asof}, CAL FIRE reports {len(kern)} active "
                             f"{'fire' if len(kern) == 1 else 'fires'} in Kern County"
                             + (f" totaling {kern_acres:,} acres." if kern_acres else ".")
                             + " This page updates automatically from the official CAL FIRE feed."
                             if ok else
                             f"The CAL FIRE feed could not be reached for this build"
                             + (f"; the last confirmed report as of {asof} is shown." if asof else ".")
                             + " Check back shortly — this page refreshes automatically."),
                },
            },
            {
                "@type": "Question",
                "name": "Where are the active fires in Kern County?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (f"This page shows a live map of every active wildfire in Kern County "
                             "and California, with location, acres burned, and containment, drawn "
                             "from the official CAL FIRE incident feed." if ok else
                             "This page normally shows a live map of every active wildfire in Kern "
                             "County and California, but the official CAL FIRE feed was unreachable "
                             "for the latest build."),
                },
            },
            {
                "@type": "Question",
                "name": "Is there a fire near Bakersfield right now?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (f"The map and list above show active CAL FIRE incidents in Kern County "
                             f"and across California as of the latest build. For evacuation orders, "
                             f"check ReadyKern at kerncountyfire.org." if ok else
                             "The official CAL FIRE feed was unreachable for the latest build. For "
                             "current conditions and evacuation orders, check ReadyKern at "
                             "kerncountyfire.org."),
                },
            },
        ],
    }

    if ok:
        seo_lede = (f"Active wildfires in Kern County and California, live from the official "
                    f"CAL FIRE feed — {len(kern)} active in Kern ({kern_acres:,} acres), with a "
                    f"map, containment status, and automatic updates.")
    else:
        seo_lede = (f"Active wildfires in Kern County and California from the official CAL FIRE "
                    f"feed. The latest build could not reach CAL FIRE"
                    + (f"; showing last-known data as of {asof}." if asof else "."))

    _write_tracker(ctx, "fires", "Kern County Fire Tracker",
                   seo_lede,
                   stat_html, body, payload, sources, dark=True, img="",
                   seo_title="Kern County Fire Map — Active Wildfires Live",
                   faq_jsonld=faq_jsonld, map_js="fires.js",
                   current="other",
                   cadence="updates every few hours from CAL FIRE")


# ------------------------------------------------------------------ water
def _fmt_day(dstr: str) -> str:
    """CDEC obsDate '2026-9-5 00:00' -> 'Sep 5'."""
    try:
        import re
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(dstr))
        if not m:
            return str(dstr)
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.strftime("%b %d").replace(" 0", " ")
    except Exception:  # noqa: BLE001
        return str(dstr)


def _chg_clause(chg_txt: str) -> str:
    """Turn the change line into a sentence for the quotable first paragraph."""
    return chg_txt + "."


def _water_level_status(elev_ft, full_pool_ft) -> tuple[str, str]:
    """Honest, objective framing of where the level sits vs full pool.

    Returns (label, note). No fabrication — pure arithmetic on the real
    elevation vs the published full-pool elevation (2605.5 ft).
    """
    if not elev_ft or not full_pool_ft:
        return "", ""
    diff = full_pool_ft - elev_ft
    if diff <= 2:
        return "Near full pool", "The lake is essentially full — most ramps and the main boat launch areas have good access."
    if diff <= 15:
        return "Below full pool", "Water is down a short way from full; main ramps typically remain usable, but check current ramp status."
    if diff <= 40:
        return "Down from full pool", "Lower water exposes some shoreline. Longer ramps still work; smaller or unimproved launches may be marginal. Check ramp status before launching."
    return "Well below full pool", "Water is well down. Ramp access can be limited to the main improved launches, and unmarked hazards near the old shore are more likely. Check current ramp status before launching."


def build_water(ctx, sources: dict):
    data = sources.get("isabella", {})
    payload = {"asof": data.get("asof", common.iso_today())}
    asof = data.get("asof", common.iso_today())
    full_pool = data.get("full_pool_ft", 2605.5)
    cap_af = data.get("capacity_af", 568_000)

    if data.get("ok") and data.get("storage"):
        storage = data["storage"]
        elev = data.get("elev_ft")
        inflow = data.get("inflow_cfs")
        series = data.get("storage_series") or data.get("series", [])
        vals = [float(s["value"]) for s in series]
        pct = data.get("pct", 0)

        # elevation stat + level framing
        delta = (vals[-1] - vals[0]) if len(vals) > 1 else 0

        # ---- change over the last week: the number answer engines actually quote ----
        chg7_af, chg7_days = None, 0
        if len(vals) >= 8:
            chg7_af, chg7_days = vals[-1] - vals[-8], 7
        elif len(vals) >= 2:
            chg7_af, chg7_days = vals[-1] - vals[-2], 1
        chg_txt = ""
        if chg7_af is not None:
            chg_txt = (f"Storage is {'up' if chg7_af >= 0 else 'down'} "
                       f"{abs(chg7_af):,.0f} acre-feet over the last "
                       f"{'7 days' if chg7_days == 7 else '24 hours'}")
        below_pool_txt = ""

        status_label, status_note = _water_level_status(
            elev["value"] if elev else None, full_pool)

        stat_html = (
            _stat(f'{elev["value"]:,}<small> ft</small>' if elev else "n/a",
                  "Water level elevation", "") +
            _stat(f"{storage['value']:,} <small>AF</small>", "Isabella storage", "amber") +
            _stat(f"{pct}%", f"of full pool (568,000 AF)", "") +
            _stat(f"{inflow['value']:,}<small> cfs</small>" if inflow else "n/a",
                  "Kern River inflow", "amber")
        )

        # ---- chart (storage trend) ----
        chart = f'<div class="chart">{svg_line_chart(vals)}<p style="font-family:IBM Plex Mono,monospace;font-size:12px;color:#4A545C;margin:4px 0 0">Lake Isabella storage, acre-feet &mdash; last {len(series)} days</p></div>'

        # ---- 14-day table ----
        rows = "".join(
            f'<tr><td>{_fmt_day(s["date"])}</td><td class="num">{int(float(s["value"])):,} AF</td></tr>'
            for s in reversed(series[-14:]))
        table = f"""
        <div class="table-wrap"><table class="data">
          <thead><tr><th>Date</th><th class="num">Storage (acre-feet)</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>"""

        # ---- objective level reading (no invented 'good/bad') ----
        level_read = ""
        if elev:
            diff = full_pool - elev["value"]
            feet_line = (f"{elev['value']:,} ft, which is {diff:.1f} ft "
                         f"{'below' if diff >= 0 else 'above'} the full-pool elevation "
                         f"of {full_pool:,} ft")
            below_pool_txt = (f"{abs(diff):.1f} ft {'below' if diff >= 0 else 'above'} "
                              f"the full-pool elevation of {full_pool:,} ft")
            level_read = (f"<p><strong>The lake is at {feet_line}.</strong> "
                          f"At this level, {status_note[0].lower()}{status_note[1:]}</p>")

        _chg_sentence = (_chg_clause(chg_txt) if chg_txt else
                         "A week-over-week storage comparison is unavailable this build.")
        body = f"""
        <div class="card"><span class="tag">Lake Isabella</span>
        <h3>Current water level</h3>
        <p><strong>Lake Isabella is at {elev['value']:,} feet elevation</strong>, holding
        {storage['value']:,} acre-feet — {pct}% of its {cap_af:,}-acre-foot full capacity
        (full pool {full_pool:,} ft). That is the live
        reading from California DWR / CDEC, updated with each build.
        {_chg_sentence}</p>
        {level_read}
        <p>Lake Isabella, on the Kern River above Bakersfield, is the valley's biggest reservoir.
        The U.S. Army Corps of Engineers reports storage, elevation and inflow to the California
        Data Exchange Center (CDEC) daily.</p></div>
        {chart}
        {table}

        <div class="card"><span class="tag">Fishing</span>
        <h3>Fishing Lake Isabella</h3>
        <p>Lake Isabella holds <strong>trout, largemouth bass, bluegill, crappie and catfish</strong>.
        It is one of Kern County's most-visited fishing lakes, with bank access around the main
        recreation areas and boat access from the improved ramps.</p>
        <p><strong>Seasonal patterns (general guidance, not a live bite report):</strong></p>
        <ul>
          <li><strong>Trout</strong> — best in spring and fall when the water is cool; the lake is
          regularly planted and trout hold near cooler inlets (Kern River, French Gulch) in summer.</li>
          <li><strong>Largemouth bass</strong> — active spring through fall; target structure,
          points and weedlines. Spawn is typically spring.</li>
          <li><strong>Crappie &amp; bluegill</strong> — strongest spring to early summer around
          brush and docks.</li>
          <li><strong>Catfish</strong> — best on warm summer evenings and nights.</li>
          <li><strong>How the water level matters:</strong> rising water floods new structure that
          fish move onto; a fast drop pulls fish out of newly exposed shallows; very low water
          concentrates fish but can make ramps harder to use and expose hazards.</li>
        </ul>
        <p class="note">Fishing quality depends on weather, water temperature and recent plantings —
        this is general seasonal guidance, not a live bite report. Always check the current
        California Department of Fish &amp; Wildlife regulations and any fish-consumption advisory
        before keeping fish.</p></div>

        <div class="card"><span class="tag">Boating &amp; access</span>
        <h3>Is the lake open? Boat ramp status</h3>
        <p>At {elev['value']:,} ft elevation ({pct}% of capacity), the lake is {status_label.lower()}.
        {status_note}</p>
        <p><strong>Boat access is controlled by the U.S. Army Corps of Engineers and Kern County
        Parks</strong> — ramps and the marina can close for debris, construction or maintenance
        regardless of water level (Lake Isabella ramps closed for two weeks in March 2026 for flood-
        debris removal, then reopened). There is no reliable real-time open/closed feed we can
        automate, so for the current ramp and marina status check the official sources:</p>
        <ul>
          <li>Kern County Parks — <a href="https://www.kerncounty.com/government/parks/facilities/lakes-fishing-boating/lake-isabella" rel="noopener">Lake Isabella boating &amp; permits</a></li>
          <li>U.S. Army Corps of Engineers — <a href="https://www.spk-wc.usace.army.mil/fcgi-bin/hourly.py?report=isb" rel="noopener">Isabella Dam hourly report</a></li>
        </ul>
        <p class="note">Boating on Lake Isabella requires a Kern County boat permit (annual, available
        each November). All boats need a U.S. Coast Guard-approved life jacket per person; operators
        16+ need a California Boater Card. Watch for 60 mph gusts and always slow to no-wake within
        200 ft of shore.</p></div>

        <div class="card"><span class="tag">Know before you go</span>
        <h3>Water-level hazards</h3>
        <p>As the level changes, watch for: submerged fencing near the South Fork, tree snags, rock
        outcroppings and sand spits that appear and disappear with the water, and the 8-ft-deep
        Borel Canal that cuts across the western lake. When the lake is low, these are closer to the
        surface and to where you'd normally launch. Report an emergency to 911; the Kern Valley
        Hospital line is (760) 379-2681.</p></div>"""
    else:
        stat_html = '<div class="errorbox">CDEC data unavailable this build.</div>'
        body = '<p class="note">Reservoir data could not be fetched this build.</p>'

    # ---- FAQ (query-matched for featured snippets) ----
    ev_txt, st_pct = "n/a", "n/a"
    faq_jsonld = None
    if data.get("ok") and data.get("storage"):
        storage = data["storage"]
        elev = data.get("elev_ft")
        inflow = data.get("inflow_cfs")
        st_pct = data.get("pct", 0)
        ev_txt = f"{elev['value']:,} ft" if elev else "n/a"
        cap_txt = f"{storage['value']:,} acre-feet"
        iflow_txt = f"{inflow['value']:,} cubic feet per second" if inflow else "n/a"
        faq_jsonld = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question",
                 "name": "What is the current water level of Lake Isabella?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": (f"Lake Isabella is at {ev_txt} elevation, holding "
                                             f"{cap_txt} ({st_pct}% of its 568,000 acre-foot "
                                             f"capacity). This live reading updates automatically "
                                             f"from California DWR/CDEC.")}},
                {"@type": "Question",
                 "name": "How full is Lake Isabella right now?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": (f"Lake Isabella is {st_pct}% full, holding {cap_txt} of "
                                             f"its 568,000 acre-foot capacity at an elevation of "
                                             f"{ev_txt} (full pool 2,605.5 ft), from the latest "
                                             f"California DWR/CDEC reading.")}},
                {"@type": "Question",
                 "name": "How far below full pool is Lake Isabella?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": ((f"Lake Isabella is {below_pool_txt} (elevation {ev_txt}, "
                                              f"{st_pct}% of capacity).") if below_pool_txt else
                                             (f"Lake Isabella is at {st_pct}% of capacity; the "
                                              f"elevation reading is unavailable this build."))}},
                {"@type": "Question",
                 "name": "Is Lake Isabella full or going up?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": ((f"Lake Isabella is at {st_pct}% of capacity. {chg_txt} "
                                              f"(the 7-day change from the CDEC storage series).")
                                             if chg_txt else
                                             (f"Lake Isabella is at {st_pct}% of capacity as of the "
                                              f"latest reading. The 30-day chart above shows whether "
                                              f"storage is rising, falling or steady."))}},
                {"@type": "Question",
                 "name": "What is the elevation of Lake Isabella?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": (f"The lake elevation is {ev_txt} (full pool is 2605.5 "
                                             f"ft). Elevation is updated from CDEC with each build.")}},
                {"@type": "Question",
                 "name": "How much water is flowing into Lake Isabella?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": (f"Kern River inflow into Lake Isabella is "
                                             f"{iflow_txt} as of the latest reading.")}},
                {"@type": "Question",
                 "name": "What kind of fish are in Lake Isabella?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": "Lake Isabella holds trout, largemouth bass, bluegill, "
                                            "crappie and catfish. Fishing is popular year-round; trout "
                                            "are best in cooler months, bass and panfish in spring to "
                                            "fall, and catfish on warm summer nights."}},
                {"@type": "Question",
                 "name": "Is Lake Isabella open for boating?",
                 "acceptedAnswer": {"@type": "Answer",
                                    "text": (f"At its current level the lake is generally open for "
                                             f"boating from the improved ramps, but ramp and marina "
                                             f"status can change for debris, construction or "
                                             f"maintenance. Check Kern County Parks and the U.S. Army "
                                             f"Corps of Engineers for current status. A Kern County "
                                             f"boat permit is required.")}},
            ],
        }
    else:
        faq_jsonld = None

    # render the same Q&A visibly so on-page text and schema never drift
    body += _faq_visible(faq_jsonld, "Lake Isabella questions")

    _write_tracker(ctx, "water",
                   "Lake Isabella Water Level & Elevation",
                   f"Lake Isabella is at {ev_txt} elevation — {st_pct}% of capacity. Live water level, elevation, Kern River inflow, fishing species, and boat ramp status, updated from California DWR/CDEC.",
                   stat_html, body, payload, sources, img="isabella",
                   seo_title="Lake Isabella Water Level Today | Elevation, Fishing & Ramp Status",
                   faq_jsonld=faq_jsonld,
                   map_js="", current="other",
                   og_image="https://bakersfieldbrief.com/assets/img/isabella.jpg",
                   cadence="updated from DWR/CDEC with each build")


# ------------------------------------------------------------------ writer
def _write_tracker(ctx, slug: str, name: str, lede: str, stat_html: str,
                   body_html: str, payload: dict, sources: dict, dark: bool = False,
                   img: str = "", seo_title: str = "", faq_jsonld: dict | None = None,
                   map_js: str = "trackers.js", cadence: str | None = None,
                   method: str | None = None, current: str = "trackers",
                   og_image: str = "https://bakersfieldbrief.com/assets/img/emblem.png"):
    built_iso = common.iso_today()
    rel = "../"
    tpl = common.read_template("tracker.html")

    # Honest cadence: default is the ALPR/surveillance weekly cadence. Fires and
    # water rebuild every ~3h on CI, not weekly — say so (the audit flagged the
    # self-contradictory "weekly" badge on those pages).
    if cadence is None:
        cadence = "refreshed weekly"
    if method is None:
        method = ("Every run fetches the official public data source, diffs it against the "
                  "previous snapshot, and bakes the result into this static page. No data is "
                  "loaded by your browser.")

    tokens = {
        "__REL__": rel,
        "__TRACKER_NAME__": html.escape(name),
        "__TRACKER_LEDE__": html.escape(lede),
        "__TRACKER_UPDATE__": html.escape(cadence),
        "__TRACKER_KICKER__": html.escape(cadence),
        "__TRACKER_ASOF__": html.escape(str(payload.get("asof", ""))),
        "__TRACKER_IMG__": img,
        "__TRACKER_FIGURE__": images.figure(img, rel),
        "__STATS__": stat_html,
        "__TRACKER_BODY__": body_html,
        "__TRACKER_METHOD__": method,
    }
    for tok, val in tokens.items():
        tpl = tpl.replace(f"<!--{tok}-->", val)
    tpl = common.inline_placeholder(tpl, payload)

    # Map assets only on pages that actually render a Leaflet map. Water (and
    # other non-map trackers) used to ship leaflet.js + markercluster + the ALPR
    # trackers.js for zero functional reason — gate them on map_js being set.
    if map_js:
        map_head = '<link rel="stylesheet" href="../assets/vendor/leaflet.css">'
        map_scripts = ('<script src="../assets/vendor/leaflet.js"></script>\n'
                       '  <script src="../assets/vendor/leaflet.markercluster.js"></script>\n'
                       '  <script src="../assets/js/' + map_js + '?v=' + _js_ver(map_js) + '" defer></script>')
    else:
        map_head = ""
        map_scripts = ""

    extra_scripts = (map_scripts
                     + (('<script src="../assets/js/live-fires.js?v=' + _js_ver("live-fires.js") + '" defer></script>')
                        if slug == "fires" else "")
                     + (('<script src="../assets/js/webmcp-alpr.js?v=' + _js_ver("webmcp-alpr.js") + '" defer></script>')
                        if slug == "surveillance" else ""))

    page = page_mod.render(
        title=seo_title or f"{name} | Bakersfield Daily Brief",
        desc=lede,
        canonical=f"/{slug}/",
        content=tpl, current=current, rel=rel, built=built_iso,
        og_image=og_image,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                page_mod.webpage_jsonld(f"/{slug}/", built_iso,
                                        name=name, desc=lede)]
               + ([faq_jsonld] if faq_jsonld else []),
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        extra_head=map_head
                   + ('<link rel="stylesheet" href="../assets/css/deflock.css?v=' + _asset_ver_css() + '">' if dark else ""),
        extra_scripts=extra_scripts)
    common.write(common.SITE / slug / "index.html", page)

# ------------------------------------------------------------------ hub
def build_hub(ctx, sources: dict) -> list[str]:
    built_iso = common.iso_today()
    rel = "../"
    alpr = sources.get("alpr", {})
    stats = alpr.get("stats", {}) if alpr.get("ok") else {}

    cards = "".join(f"""
        <a class="card" href="{rel}{slug}/">
          <span class="tag">{tag}</span>
          <h3>{html.escape(meta['name'])}</h3>
          <p>{html.escape(meta['lede'])}</p>
          <span class="card-go">Open tracker</span>
        </a>""" for slug, (tag, meta) in {
        "surveillance": ("amber", TRACKERS["surveillance"]),
        "fires": ("amber", TRACKERS["fires"]),
        "water": ("green", TRACKERS["water"]),
    }.items())

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Trackers</p>
      <h1>Live data, updated on a schedule</h1>
      <p class="lede">Evergreen pages that track Kern County&rsquo;s public data over time:
      license plate readers and reservoir levels. Each tracker diffs every run and keeps a
      change log &mdash; so you can see not just the current state, but how it changes.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>ALPR map: weekly &middot; water: daily</span></div></div>
    </div>
    <div class="grid cols-2">{cards}</div>

    <section class="block">
      <div class="sign-head"><span class="tab">How</span><h2>How trackers work</h2></div>
      <div class="card"><p>Every tracker is a small pipeline: fetch the public source
      (Overpass/OSM, CDEC), normalize it, diff it against the stored snapshot, and bake the
      result into a static page at build time. There is no database and no client-side data
      fetching &mdash; the page you see is the page that was built. Adding a tracker is a
      ~30-minute job: see the README.</p>
      <p>ALPR count on the last build: <strong>{stats.get('total', '—')} cameras mapped</strong>
      ({stats.get('flock', 0)} Flock Safety). Map data &copy; OpenStreetMap contributors, ODbL.</p></div>
    </section>"""

    page = page_mod.render(
        title="Trackers — ALPR map, Isabella Lake | Bakersfield Daily Brief",
        desc="Auto-updating data trackers for Kern County: the license plate reader (ALPR) camera map with weekly change log, and Lake Isabella storage levels.",
        canonical="/trackers/",
        content=body, current="trackers", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "")
    common.write(common.SITE / "trackers" / "index.html", page)

    ctx.build_report["trackers"] = {
        "alpr_total": stats.get("total", 0),
        "alpr_new_week": stats.get("new_this_week", 0),
        "pages": ["surveillance", "fires", "water", "trackers"],
    }
    return ["trackers/index.html", "surveillance/index.html", "fires/index.html", "water/index.html"]


# register in dependency order (hub reads TRACKERS)
register("surveillance", "Flock & ALPR Tracker",
         "Every automated license plate reader mapped in the Bakersfield metro — weekly map, facing direction, newest-camera highlights, and a real 13-week change log.", build_alpr)
register("fires", "Kern County Fire Tracker",
         "Active wildfires in Kern County and California, live from the official CAL FIRE feed — map, acres, containment, and automatic updates.", build_fires)
register("water", "Lake Isabella Water Level",
         "Lake Isabella water level and elevation, live from California DWR/CDEC — storage, Kern River inflow, fishing species, and boat ramp status.", build_water)