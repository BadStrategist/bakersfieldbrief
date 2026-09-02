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
    """Baked inline SVG line chart (no client-side chart lib)."""
    if len(points) < 2:
        return ""
    mn, mx = min(points), max(points)
    span = (mx - mn) or 1
    pad = 10
    n = len(points)
    xs = [pad + i * (width - 2 * pad) / (n - 1) for i in range(n)]
    ys = [height - pad - (v - mn) * (height - 2 * pad) / span for v in points]
    path = " ".join(f"L{x:.1f},{y:.1f}" for x, y in zip(xs[1:], ys[1:]))
    area = f"M{xs[0]:.1f},{height - pad} L{xs[0]:.1f},{ys[0]:.1f} {path} L{xs[-1]:.1f},{height - pad} Z"
    pts = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#1A2126"/>'
                  for x, y in zip(xs, ys))
    last_label = f'<text x="{xs[-1]:.1f}" y="{ys[-1] - 8:.1f}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="12" fill="#4A545C">{points[-1]:,.0f}</text>'
    first_label = f'<text x="{xs[0]:.1f}" y="{ys[0] + 14:.1f}" text-anchor="start" font-family="IBM Plex Mono, monospace" font-size="12" fill="#4A545C">{points[0]:,.0f}</text>'
    return f"""<svg viewBox="0 0 {width} {height}" role="img" aria-label="30-day trend chart">
      <path d="{area}" fill="#DC9A1F" opacity="0.18"/>
      <path d="M{xs[0]:.1f},{ys[0]:.1f} {path}" fill="none" stroke="#232B30" stroke-width="2.5" stroke-linejoin="round"/>
      {pts}{first_label}{last_label}
    </svg>"""


def _stat(value_html: str, label: str, cls: str = "") -> str:
    return f'<div class="stat {cls}"><div class="n">{value_html}</div><div class="l">{label}</div></div>'


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

    last4 = sum(e.get("new_count", 0) for e in change_log[-4:])
    newest_date = stats.get("newest_mapped", "—")

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
          <div><span class="n">{stats.get('total', 0)}</span> cameras mapped</div>
          <div><span class="n">{stats.get('flock', 0)}</span> Flock Safety</div>
          <div><span class="n">+{last4}</span> new in 28 days</div>
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
                             f"total license plate reader (ALPR) cameras, as of {asof}.")
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
                             f"direction.")
                }
            }
        ]
    }

    _write_tracker(ctx, "surveillance", "Flock Camera Map — Bakersfield",
                   f"See every license plate reader in Bakersfield on a live map — {flock_n} Flock Safety cameras and {total_n} total ALPR units mapped in the metro, with facing direction, newest-camera highlights, and a weekly change log from OpenStreetMap.",
                   stat_html, body, payload, sources, dark=True, img="flock",
                   seo_title="Bakersfield Flock Camera Map | Live ALPR Tracker",
                   faq_jsonld=faq_jsonld)


# ------------------------------------------------------------------ fires
def build_fires(ctx, sources: dict):
    data = sources.get("calfire", {})
    asof = data.get("asof", common.iso_today())
    incidents = data.get("incidents", [])
    kern = data.get("kern", [])

    payload = {"incidents": incidents, "kern": kern, "asof": asof}

    kern_acres = sum(int(float(i.get("acres") or 0)) for i in kern)
    if data.get("ok"):
        stat_html = (
            _stat(f"{len(kern)}", "active fires in Kern County", "amber") +
            _stat(f"{kern_acres:,}", "acres burning in Kern", "amber") +
            _stat(f"{len(incidents)}", "active fires in California", "") +
            _stat(asof, "data as of", "")
        )
    else:
        stat_html = '<div class="errorbox">CAL FIRE data unavailable this build.</div>'

    # ---- map (fires use their own JS; marker: flame pin)
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
    </div>""".format(kern=len(kern), all_n=len(incidents), asof=asof)

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

    if kern_cards:
        kern_section = f'<p class="sec-head">Kern County <span class="unit">active fires</span></p><div class="grid cols-2">{kern_cards}</div>'
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
                             + " This page updates automatically from the official CAL FIRE feed."),
                },
            },
            {
                "@type": "Question",
                "name": "Where are the active fires in Kern County?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("This page shows a live map of every active wildfire in Kern County "
                             "and California, with location, acres burned, and containment, drawn "
                             "from the official CAL FIRE incident feed."),
                },
            },
            {
                "@type": "Question",
                "name": "Is there a fire near Bakersfield right now?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("The map and list above show active CAL FIRE incidents in Kern County "
                             "and across California as of the latest build. For evacuation orders, "
                             "check ReadyKern at kerncountyfire.org."),
                },
            },
        ],
    }

    _write_tracker(ctx, "fires", "Kern County Fire Tracker",
                   f"Active wildfires in Kern County and California, live from the official CAL FIRE feed — {len(kern)} active in Kern ({kern_acres:,} acres), with a map, containment status, and automatic updates.",
                   stat_html, body, payload, sources, dark=True, img="",
                   seo_title="Kern County Fire Map — Active Wildfires Live",
                   faq_jsonld=faq_jsonld, map_js="fires.js")


# ------------------------------------------------------------------ water
def build_water(ctx, sources: dict):
    data = sources.get("isabella", {})
    payload = {"asof": data.get("asof", common.iso_today())}

    if data.get("ok") and data.get("last"):
        last = data["last"]
        series = data.get("series", [])
        vals = [s["value"] for s in series]
        delta = (vals[-1] - vals[0]) if len(vals) > 1 else 0
        pct = data.get("pct", 0)
        stat_html = (
            _stat(f"{last['value']:,} <small>AF</small>", "Isabella storage", "") +
            _stat(f"{pct}%", "of capacity (568,000 AF)", "amber") +
            _stat(f"{delta:+,} <small>AF</small>", "30-day change", "") +
            _stat(f"{len(series)}", "daily readings kept", "")
        )
        chart = f'<div class="chart">{svg_line_chart(vals)}<p style="font-family:IBM Plex Mono,monospace;font-size:12px;color:#4A545C;margin:4px 0 0">Lake Isabella storage, acre-feet &mdash; last {len(series)} days</p></div>'
        rows = "".join(f'<tr><td>{html.escape(str(s["date"]))}</td><td class="num">{s["value"]:,} AF</td></tr>'
                       for s in reversed(series[-14:]))
        table = f"""
        <div class="table-wrap"><table class="data">
          <thead><tr><th>Date</th><th class="num">Storage (acre-feet)</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>"""
        body = f"""
        <div class="card"><span class="tag">Water</span><h3>Isabella Lake storage</h3>
        <p>Lake Isabella, on the Kern River above Bakersfield, is the valley&rsquo;s biggest
        reservoir. The U.S. Army Corps of Engineers reports storage to the California Data
        Exchange Center (CDEC) daily; we track the 30-day trend. Kern River flows and snowpack
        trackers follow the same pattern.</p></div>
        {chart}
        {table}"""
    else:
        stat_html = '<div class="errorbox">CDEC data unavailable this build.</div>'
        body = '<p class="note">Reservoir data could not be fetched this build.</p>'

    _write_tracker(ctx, "water", "Isabella Lake & Kern River Tracker",
                   "Lake Isabella storage levels, percent of capacity, and the 30-day trend — updated daily from California DWR/CDEC data.",
                   stat_html, body, payload, sources, img="isabella")


# ------------------------------------------------------------------ writer
def _write_tracker(ctx, slug: str, name: str, lede: str, stat_html: str,
                   body_html: str, payload: dict, sources: dict, dark: bool = False,
                   img: str = "", seo_title: str = "", faq_jsonld: dict | None = None,
                   map_js: str = "trackers.js"):
    built_iso = common.iso_today()
    rel = "../"
    tpl = common.read_template("tracker.html")

    tokens = {
        "__REL__": rel,
        "__TRACKER_NAME__": html.escape(name),
        "__TRACKER_LEDE__": html.escape(lede),
        "__TRACKER_UPDATE__": "Auto-updated by the weekly tracker build",
        "__TRACKER_IMG__": img,
        "__TRACKER_FIGURE__": images.figure(img, rel),
        "__STATS__": stat_html,
        "__TRACKER_BODY__": body_html,
        "__TRACKER_METHOD__": "Every run fetches the official public data source, diffs it against the "
                              "previous snapshot, and bakes the result into this static page. No data is "
                              "loaded by your browser.",
    }
    for tok, val in tokens.items():
        tpl = tpl.replace(f"<!--{tok}-->", val)
    tpl = common.inline_placeholder(tpl, payload)

    page = page_mod.render(
        title=seo_title or f"{name} | Bakersfield Daily Brief",
        desc=lede,
        canonical=f"/{slug}/",
        content=tpl, current="trackers", rel=rel, built=built_iso,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()]
               + ([faq_jsonld] if faq_jsonld else []),
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        extra_head='<link rel="stylesheet" href="../assets/vendor/leaflet.css">'
                   + ('<link rel="stylesheet" href="../assets/css/deflock.css?v=' + built_iso + '">' if dark else ""),
        extra_scripts='<script src="../assets/vendor/leaflet.js"></script>\n  <script src="../assets/vendor/leaflet.markercluster.js"></script>\n  <script src="../assets/js/' + map_js + '?v=' + _js_ver(map_js) + '" defer></script>'
                   + (('<script src="../assets/js/webmcp-alpr.js?v=' + _js_ver("webmcp-alpr.js") + '" defer></script>')
                      if slug == "surveillance" else ""))
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
register("water", "Isabella Lake & Kern River Tracker",
         "Lake Isabella storage, percent of capacity, and the 30-day trend from California DWR/CDEC.", build_water)