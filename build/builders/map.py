#!/usr/bin/env python3
"""The Kern Overnight — Live Incident Map (/map/).

Leaflet + OpenStreetMap, no API keys. Dots come from the incident feed
(data/incidents_geo.json) which the nightly pipeline geocodes to block or
cross-street level. Privacy: popups carry only the generalized area label —
never an exact address.
"""
from __future__ import annotations

import json
from pathlib import Path

from build import common
from . import page as page_mod

CATEGORY = {
    "structure fire": "fire", "vegetation fire": "fire", "commercial fire": "fire",
    "attempted arson": "fire", "fire": "fire", "electrical": "fire",
    "vehicle collision": "traffic", "traffic collision": "traffic", "pursuit": "traffic",
    "medical aid": "medical", "mental health hold": "medical",
    "robbery": "police", "burglary": "police", "attempted burglary": "police",
    "pursuit (police)": "police", "shooting": "police", "reported shooting": "police",
    "domestic": "police", "assault": "police", "suspicious": "police",
    "welfare check": "police", "DUI": "traffic", "disturbance": "police",
    "missing person": "police", "unknown": "other",
}
COLORS = {"fire": "#E53935", "police": "#DC9A1F", "medical": "#2E7D32",
          "traffic": "#64748B", "other": "#475569"}
PRECISION_LABEL = {"block": "block / cross-street", "street": "street-level",
                   "area": "neighborhood", "city": "general area"}


def _load_feed() -> list[dict]:
    p = Path(common.DATA_DIR if hasattr(common, "DATA_DIR") else "data") / "incidents_geo.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"
    feed = _load_feed()
    dots = []
    counts = {}
    for d in feed:
        cat = CATEGORY.get(d.get("type", "").lower(), "other")
        counts[cat] = counts.get(cat, 0) + 1
        dots.append({
            "lat": d["lat"], "lng": d["lng"],
            "type": d.get("type", "incident"), "cat": cat,
            "time": d.get("t", ""), "area": d.get("area", ""),
            "prec": PRECISION_LABEL.get(d.get("p", "city"), "general area"),
            "nb": int(d.get("nb", 2)),
        })
    dots_json = json.dumps(dots, ensure_ascii=False)

    legend = "".join(
        f'<span class="lg"><i style="background:{COLORS[c]}"></i>{c.title()} ({counts.get(c, 0)})</span>'
        for c in ("fire", "police", "medical", "traffic", "other"))

    body = f"""
    <style>
      #map {{ height: 540px; border-radius: 10px; border: 1px solid #E5E0D5; }}
      .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin:10px 0 4px; font-size:.85rem; color:#444; }}
      .legend .lg {{ display:inline-flex; align-items:center; gap:6px; }}
      .legend i {{ width:12px; height:12px; border-radius:50%; display:inline-block; }}
      .filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:6px 0 14px; }}
      .filters button {{ font:inherit; font-size:.85rem; padding:5px 14px; border-radius:999px;
        border:1px solid #D8D2C4; background:#fff; cursor:pointer; color:#232B30; }}
      .filters button.on {{ background:#232B30; color:#FBF8F1; border-color:#232B30; }}
      .pop {{ font-size:.9rem; line-height:1.35; }}
      .pop b {{ display:block; margin-bottom:2px; }}
      .pop .tm {{ color:#6B7280; font-size:.8rem; }}
      .pop .nb {{ font-size:.75rem; color:#92400E; }}
    </style>

    <p class="sec-head">Live incident map <span class="unit">rolling, from the overnight feed</span></p>
    <div class="card">
      <div id="map"></div>
      <div class="legend">{legend}</div>
      <div class="filters" id="filters">
        <button class="on" data-f="all">All</button>
        <button data-f="fire">Fire</button>
        <button data-f="police">Police</button>
        <button data-f="medical">Medical</button>
        <button data-f="traffic">Traffic</button>
      </div>
      <p class="note">Dots are placed from overnight police, sheriff, fire, and EMS dispatch traffic. Locations are
      generalized to block or cross-street level &mdash; the map never shows an exact address &mdash; and
      everything is preliminary until confirmed. Archives lag live airwaves by up to ~30 minutes, so the
      map is a rolling picture, not instantaneous.</p>
    </div>

    <p class="sec-head">What the dots mean</p>
    <div class="card"><p>Each dot is one dispatched incident from the overnight scanner feed, colored by
    category and sized by how significant it sounded on the air (larger = more serious). Click a dot for
    the incident type, the time it was dispatched, and the generalized location &mdash; block or cross
    streets, never a house number. Read the full morning write-up on the
    <a href="{rel}overnight/">Kern Overnight</a> page.</p></div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
    <script>
      (function () {{
        var feed = {dots_json};
        var map = L.map('map', {{ scrollWheelZoom: false }}).setView([35.3733, -119.0187], 12);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
          maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
        }}).addTo(map);
        var markers = [];
        var SIZES = {{5: 16, 4: 13, 3: 11, 2: 9, 1: 7}};
        function addDot(d) {{
          var m = L.circleMarker([d.lat, d.lng], {{
            radius: SIZES[d.nb] || 9, color: '#fff', weight: 1.5,
            fillColor: d.cat === 'fire' ? '#E53935' : d.cat === 'police' ? '#DC9A1F'
              : d.cat === 'medical' ? '#2E7D32' : d.cat === 'traffic' ? '#64748B' : '#475569',
            fillOpacity: 0.9
          }}).addTo(map);
          m.bindPopup('<div class="pop"><b>' + d.type + '</b>'
            + '<span class="tm">' + d.time + '</span><br>' + d.area
            + '<br><span class="nb">' + d.prec + (d.nb >= 4 ? ' &middot; significant' : '') + '</span></div>');
          m._ko = d;
          markers.push(m);
        }}
        feed.forEach(addDot);
        if (feed.length === 0) {{
          L.circleMarker([35.3733, -119.0187], {{ radius: 5, color: '#999' }}).addTo(map)
            .bindPopup('<div class="pop"><b>No incidents yet</b><br>New dots appear after the next overnight run.</div>').openPopup();
        }}
        document.getElementById('filters').addEventListener('click', function (e) {{
          var b = e.target.closest('button'); if (!b) return;
          document.querySelectorAll('#filters button').forEach(function (x) {{ x.classList.remove('on'); }});
          b.classList.add('on');
          var f = b.dataset.f;
          markers.forEach(function (m) {{
            map.removeLayer(m);
            if (f === 'all' || m._ko.cat === f) addDot(m._ko);
          }});
        }});
      }})();
    </script>
    """

    page = page_mod.render(
        title="Live Incident Map | Bakersfield Daily Brief",
        desc="A rolling map of overnight police, fire, and EMS incidents across Bakersfield and Kern County, placed to block or cross-street level from scanner dispatch audio.",
        canonical="/map/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "map" / "index.html", page)
    built.append("map/index.html")
    ctx.build_report["map"] = {"dots": len(feed)}
    return built
