#!/usr/bin/env python3
"""Geocoding for The Kern Overnight map — block/cross-street → coordinates.

Privacy: locations are ALWAYS generalized before geocoding (block level or
cross streets). The map dots are approximate on purpose; the feed never
carries exact street numbers.

Strategy (fast → slow, all cached):
  1. Local Bakersfield gazetteer: known streets/neighborhoods → centroid.
  2. Nominatim (OSM) for block/interpolation and intersections, cached in
     data/geo_cache.json (1 req/s polite rate limit).
  3. City centroid fallback (still labelled 'area').
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "geo_cache.json"
CITY = (35.3733, -119.0187)  # Bakersfield center

# ----------------------------------------------------------------- gazetteer
# Representative points for the streets/areas most likely to appear on the
# feed. Block-level refinement comes from Nominatim when available; these
# centroids are the offline fallback.
STREETS: dict[str, tuple[float, float]] = {
    # downtown / core
    "chesterton": (35.376, -119.019), "chester avenue": (35.373, -119.018),
    "truxtun avenue": (35.373, -119.022), "truxtun": (35.373, -119.022),
    "19th street": (35.380, -119.000), "20th street": (35.380, -119.005),
    "24th street": (35.378, -119.010), "union avenue": (35.380, -119.003),
    "f street": (35.373, -119.016), "h street": (35.373, -119.012),
    "k street": (35.373, -119.008), "l street": (35.373, -119.005),
    "m street": (35.373, -119.002), "n street": (35.373, -119.000),
    "o street": (35.373, -118.998),
    # south
    "ming avenue": (35.312, -119.020), "ming": (35.312, -119.020),
    "panama lane": (35.267, -119.015), "white lane": (35.320, -119.020),
    "stockdale highway": (35.355, -119.040), "stockdale": (35.355, -119.040),
    "california avenue": (35.345, -119.015), "brundage lane": (35.331, -119.015),
    "fairfax road": (35.318, -119.030), "auburn street": (35.318, -119.012),
    "columbus street": (35.325, -119.008), "wible road": (35.348, -119.045),
    "old river road": (35.360, -119.060),
    # east
    "niles street": (35.375, -118.985), "mount vernon avenue": (35.380, -118.995),
    "mount vernon": (35.380, -118.995), "east brundage lane": (35.331, -118.990),
    "pioneer drive": (35.368, -118.985), "sumner avenue": (35.356, -118.995),
    "baker street": (35.380, -118.995), "williams street": (35.378, -118.990),
    "eureka street": (35.378, -118.995), "monroe street": (35.378, -118.993),
    "chicago avenue": (35.378, -118.990), "gosford road": (35.375, -119.030),
    "calloway drive": (35.420, -119.050), "allen road": (35.373, -119.052),
    "ashe road": (35.373, -119.065), "coffee road": (35.373, -119.086),
    "real road": (35.400, -119.030),
    # north
    "olive drive": (35.415, -119.020), "oildale": (35.420, -119.030),
    "north chester avenue": (35.420, -119.015), "brown street": (35.420, -119.012),
    "garden street": (35.418, -119.010), "franklin street": (35.418, -119.020),
    "belle terrace": (35.415, -119.035),
    # west
    "rosedale highway": (35.400, -119.060), "rosedale": (35.400, -119.060),
    "7th standard road": (35.440, -119.100), "hageman road": (35.373, -119.075),
    "norris road": (35.373, -119.095), "oak street": (35.400, -119.100),
    "panama lane west": (35.267, -119.080),
    # landmarks
    "lake ming": (35.4376, -118.8688), "hart park": (35.4476, -118.9113),
    # outlying towns (area-level dots)
    "delano": (35.769, -119.247), "wasco": (35.594, -119.341),
    "shafter": (35.500, -119.272), "tehachapi": (35.132, -118.449),
    "ridgecrest": (35.622, -117.671), "mojave": (35.052, -118.174),
    "lamont": (35.260, -118.914), "arvin": (35.209, -118.828),
    "frazier park": (34.822, -118.944), "lake isabella": (35.640, -118.473),
    "kern river": (35.280, -118.800), "buttonwillow": (35.400, -119.469),
    "tupman": (35.300, -119.350),
}

AREA_KEYS = {"oildale", "rosedale", "delano", "wasco", "shafter", "tehachapi",
             "ridgecrest", "mojave", "lamont", "arvin", "frazier park",
             "lake isabella", "buttonwillow", "tupman"}

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_UA = "BakersfieldBrief-KernOvernight/1.0 (editor@bakersfieldbrief.com)"


class GeoError(RuntimeError):
    pass


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def _nominatim(query: str, cache: dict) -> tuple[float, float] | None:
    """One Nominatim lookup, cached, rate-limited to ~1 req/s."""
    if query in cache:
        v = cache[query]
        return (v[0], v[1]) if v else None
    try:
        r = requests.get(_NOMINATIM,
                         params={"q": query, "format": "json", "limit": 1,
                                 "addressdetails": 0},
                         headers={"user-agent": _UA}, timeout=15)
        r.raise_for_status()
        rows = r.json()
        hit = rows[0] if rows else None
        cache[query] = [float(hit["lat"]), float(hit["lon"])] if hit else None
    except Exception as e:  # noqa: BLE001
        # Do NOT cache None on a failed lookup. `cache[query] = None` means
        # "Nominatim answered and has no such place"; a timeout, a DNS blip or an
        # HTTP 429 is not evidence of a missing street. Writing None here pinning a
        # real address as unresolvable forever in a cache that ships in the repo,
        # is how data/geo_cache.json accumulated null entries.
        print(f"    [geo] nominatim failed for {query!r} ({type(e).__name__}); "
              "retrying next run", flush=True)
        return None
    _save_cache(cache)
    time.sleep(1.1)  # polite rate limit
    return (cache[query][0], cache[query][1]) if cache.get(query) else None


def _street_hit(text: str) -> tuple[str, tuple[float, float], bool] | None:
    """Find a known street/area in the text → (name, point, is_area)."""
    t = text.lower()
    for name, pt in sorted(STREETS.items(), key=lambda kv: -len(kv[0])):
        if name in t:
            return name, pt, name in AREA_KEYS
    return None


_BLOCK_RE = re.compile(r"(\d{3,5})(?:00)?\s*(?:block of|block|of)?\s*([a-z]+\s(?:avenue|street|road|lane|drive|highway|way|boulevard|place))", re.I)


def geocode(place: str, cache: dict | None = None) -> dict:
    """Geocode a generalized place string → {lat, lng, precision, label}.

    precision: 'block' (Nominatim interpolation or street point when the
               input carries a block number) | 'street' (gazetteer centroid)
               | 'area' (neighborhood/town) | 'city' (fallback).
    """
    cache = cache if cache is not None else _load_cache()
    label = re.sub(r"\s+", " ", place.strip())
    t = label.lower()

    # 1. block pattern ("2400 block of Chester Ave") — Nominatim refinement,
    #    then plain street query, then gazetteer
    m = _BLOCK_RE.search(t)
    if m:
        num, street = m.group(1), m.group(2)
        for query in (f"{num} block of {street}, Bakersfield, Kern County, CA",
                      f"{street}, Bakersfield, CA"):
            hit = _nominatim(query, cache)
            if hit:
                return {"lat": hit[0], "lng": hit[1], "precision": "block",
                        "label": label}

    # 2. cross streets ("X at Y", "X and Y") — intersection query, else
    #    midpoint of both gazetteer points (grid streets average well)
    cross = re.search(r"([a-z\s]+?)\s+(?:at|and|near)\s+([a-z\s]+?)(?:,|$)", t)
    if cross:
        s1, s2 = cross.group(1).strip(), cross.group(2).strip()
        hit = _nominatim(f"{s1} & {s2}, Bakersfield, CA", cache)
        if hit:
            return {"lat": hit[0], "lng": hit[1], "precision": "block",
                    "label": label}
        g1 = _street_hit(s1)
        g2 = _street_hit(s2)
        if g1 and g2:
            return {"lat": (g1[1][0] + g2[1][0]) / 2,
                    "lng": (g1[1][1] + g2[1][1]) / 2,
                    "precision": "street", "label": label}

    # 3. gazetteer
    hit = _street_hit(t)
    if hit:
        name, pt, is_area = hit
        return {"lat": pt[0], "lng": pt[1],
                "precision": "area" if is_area else "street",
                "label": label}

    # 4. city fallback
    return {"lat": CITY[0], "lng": CITY[1], "precision": "city",
            "label": label}


def build_feed(incidents_dir: Path, out: Path, max_age_h: float = 72.0) -> int:
    """Incidents JSON → compact map feed (data/incidents_geo.json).

    One dot per incident, newest first, within max_age_h. Exact street
    numbers are never included — only the generalized area label."""
    cache = _load_cache()
    feed: list[dict] = []
    now = dt.datetime.now(dt.timezone.utc)
    for f in sorted(incidents_dir.glob("*.json"), reverse=True):
        try:
            incidents = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        day = dt.date.fromisoformat(f.stem)
        for inc in incidents:
            hh, mm = (inc.get("time") or "00:00").split(":")
            ts = dt.datetime(day.year, day.month, day.day, int(hh), int(mm),
                             tzinfo=dt.timezone.utc)
            age_h = (now - ts).total_seconds() / 3600
            if age_h > max_age_h:
                continue
            g = geocode(inc.get("area", ""), cache)
            feed.append({
                "t": ts.strftime("%Y-%m-%d %H:%M"),
                "type": inc.get("type", "incident"),
                "nb": inc.get("notability", 2),
                "area": g["label"],
                "p": g["precision"],
                "lat": g["lat"],
                "lng": g["lng"],
            })
    feed.sort(key=lambda d: d["t"], reverse=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    return len(feed)
