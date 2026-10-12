#!/usr/bin/env python3
"""Build build/kern_places.json: the boundary of every city and Census place in Kern County.

  .venv\\Scripts\\python.exe scripts/build_kern_places.py

Which town a camera is in is a looked-up fact, the same rule as a part of town
(scripts/build_street_regions.py). /surveillance/<town>/ and the "in Ridgecrest city limits"
line on a camera record both read it from this file (build/places_kern.py), never from a
geocoder's address string and never from a box drawn by hand.

Sources, all Census TIGERweb:
  * Incorporated Places (the 11 cities)          Places_CouSub_ConCity_SubMCD layer 4
  * Census Designated Places (Mojave, Rosamond)  Places_CouSub_ConCity_SubMCD layer 5
  * Kern County itself, to keep only its places  State_County, GEOID 06029

A place is kept when its interior point is inside the county. Place boundaries are simplified
to about 1 m and no further: city limits run down the middle of roads, cameras stand on those
roads, and at 10 m one Tehachapi camera sat half a metre from the simplified line. Run on the
box and commit the output: it is source, and it changes only when a city annexes land.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "kern_places.json"
UA = {"user-agent": "BakersfieldDailyBrief/1.0 (editor@bakersfieldbrief.com)"}

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
PLACES = f"{TIGER}/Places_CouSub_ConCity_SubMCD/MapServer"
LAYERS = ((4, "Incorporated Places", "city"), (5, "Census Designated Places", "cdp"))
COUNTY_SERVICE = f"{TIGER}/State_County/MapServer"
KERN_GEOID = "06029"
# The box that holds the county, with a margin. Only a first cut: the county polygon decides.
ENVELOPE = "-120.35,34.75,-117.50,35.90"


def _get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"{url}: {d['error']}")
    return d


def in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_rings(x: float, y: float, rings: list) -> bool:
    """Even-odd over every ring, so a hole is outside and a second part is inside."""
    return sum(in_ring(x, y, r) for r in rings) % 2 == 1


def county_rings() -> list:
    """Kern County's polygon. The county layer is found by name, not by a number that the
    Census has moved between vintages."""
    layers = _get(COUNTY_SERVICE, {"f": "json"})["layers"]
    lid = next(la["id"] for la in layers if la["name"].strip().lower() == "counties")
    d = _get(f"{COUNTY_SERVICE}/{lid}/query", {
        "where": f"GEOID='{KERN_GEOID}'", "outFields": "GEOID,BASENAME", "outSR": 4326,
        "geometryPrecision": 5, "maxAllowableOffset": 0.0001, "f": "json"})
    feats = d.get("features") or []
    if len(feats) != 1 or feats[0]["attributes"].get("BASENAME") != "Kern":
        raise RuntimeError(f"expected one county named Kern for GEOID {KERN_GEOID}, got "
                           f"{[f['attributes'] for f in feats]}")
    return feats[0]["geometry"]["rings"]


def fetch_places(kern: list) -> list[dict]:
    out = []
    for lid, want, kind in LAYERS:
        name = _get(f"{PLACES}/{lid}", {"f": "json"}).get("name", "")
        if want.lower() not in name.lower():
            raise RuntimeError(f"layer {lid} is {name!r}, expected {want!r}")
        off = 0
        while True:
            d = _get(f"{PLACES}/{lid}/query", {
                "where": "STATE='06'", "geometry": ENVELOPE,
                "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "GEOID,BASENAME,NAME,INTPTLAT,INTPTLON,CENTLAT,CENTLON",
                "orderByFields": "GEOID", "resultOffset": off, "outSR": 4326,
                "geometryPrecision": 6, "maxAllowableOffset": 0.00001, "f": "json"})
            feats = d.get("features") or []
            for f in feats:
                a = f["attributes"]
                lat = a.get("INTPTLAT") or a.get("CENTLAT")
                lon = a.get("INTPTLON") or a.get("CENTLON")
                rings = (f.get("geometry") or {}).get("rings") or []
                if not rings or lat is None or lon is None:
                    raise RuntimeError(f"place {a} has no geometry or interior point")
                if in_rings(float(lon), float(lat), kern):
                    out.append({"name": a["BASENAME"], "kind": kind, "geoid": a["GEOID"],
                                "rings": rings})
            off += len(feats)
            if not feats or not d.get("exceededTransferLimit"):
                break
    out.sort(key=lambda p: (p["kind"], p["name"]))
    return out


def main() -> int:
    kern = county_rings()
    places = fetch_places(kern)
    cities = [p["name"] for p in places if p["kind"] == "city"]
    # The county has 11 incorporated cities. Fewer means a layer answered short.
    must = {"Arvin", "Bakersfield", "California City", "Delano", "Maricopa", "McFarland",
            "Ridgecrest", "Shafter", "Taft", "Tehachapi", "Wasco"}
    if set(cities) != must:
        print(f"cities are {sorted(cities)}, expected {sorted(must)}", file=sys.stderr)
        return 1
    names = [p["name"] for p in places]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        print(f"two places share a name: {twice}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps({
        "built": dt.date.today().isoformat(),
        "source": "U.S. Census TIGERweb: Incorporated Places, Census Designated Places, "
                  "Counties (GEOID 06029)",
        "places": places}, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(cities)} cities, {len(places) - len(cities)} "
          f"Census places, {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
