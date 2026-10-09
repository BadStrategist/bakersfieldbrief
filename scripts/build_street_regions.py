#!/usr/bin/env python3
"""Build kern_overnight/street_regions.json: street + block -> part of town.

Run by hand when the boundaries below change or the city adds streets:

    .venv/Scripts/python.exe scripts/build_street_regions.py [cache_dir]

Sources (all public, fetched with the site's own user agent):
  * City of Bakersfield GIS, Transportation/Streets: every centerline segment
    with its address range, in the city and the county islands around it.
  * City of Bakersfield GIS, Hydrography/Kern River: the river polygon.
  * Census TIGERweb, Census Designated Places: Oildale, Rosedale, Greenacres,
    Casa Loma, Cottonwood, East Niles and the rest, used as anchors and to keep
    separate towns (Lamont, Weedpatch, Edison) out of the six.

The six parts of town are the owner's (2026-10-09). The lines between them are
set HERE and nowhere else:

  NW  Northwest / Rosedale        west of Hwy 99, north of the Kern River
  SW  Southwest                   west of Hwy 99, south of the Kern River
  N   North Bakersfield & Oildale east of Hwy 99 and north of the river, plus
                                  the Olive Drive area: west of 99 as far as
                                  Fruitvale Avenue
  C   Central & Downtown          Hwy 99 to Union Avenue, river to Brundage Lane
  E   East Bakersfield            east of Union Avenue, north of Brundage Lane
  S   Southeast & South           south of Brundage Lane, Hwy 99 to Union Avenue
  SE  Southeast & South           south of Brundage Lane, east of Union Avenue

S and SE are one part of town with two names in copy ("south Bakersfield",
"southeast Bakersfield"). X marks a segment outside all six.
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "kern_overnight" / "street_regions.json"
UA = {"user-agent": "BakersfieldDailyBrief/1.0 (editor@bakersfieldbrief.com)"}

CITY_GIS = "https://gis.bakersfieldcity.us/webmaps/rest/services/General"
STREETS_URL = f"{CITY_GIS}/Transportation/MapServer/4/query"
RIVER_URL = f"{CITY_GIS}/Hydrography/MapServer/1/query"
CDP_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
           "Places_CouSub_ConCity_SubMCD/MapServer/5/query")

# ------------------------------------------------------------- the boundaries
UNION_AVE = -119.0029      # lon
FRUITVALE_AVE = -119.0744  # lon
BRUNDAGE_LN = 35.3541      # lat
# Beyond this box a street is not in any of the six (Shafter, Arvin, the
# canyon, Taft Highway and south).
METRO = (-119.26, 35.25, -118.80, 35.485)  # west, south, east, north

# Census places that settle the question on their own.
CDP_REGION = {
    "Oildale": "N",
    "Rosedale": "NW", "Greenacres": "NW",
    "Olde Stockdale": "SW", "Old Stine": "SW",
    "East Bakersfield": "E", "La Cresta": "E", "Hillcrest": "E",
    "Bakersfield Country Club": "E", "East Niles": "E", "Potomac Park": "E",
    "Casa Loma": "SE", "Cottonwood": "SE", "Rexland Acres": "SE",
    "Greenfield": "S",
}
# Separate communities: never one of the six parts of Bakersfield.
CDP_OUTSIDE = {"Lamont", "Weedpatch", "Edison", "Tarina", "Fuller Acres",
               "El Adobe", "Di Giorgio", "Edmundson Acres", "Stebbins",
               "Mexican Colony", "Cherokee Strip", "Smith Corner",
               "Choctaw Valley"}

TYPES = {
    "ST": "street", "DR": "drive", "AVE": "avenue", "RD": "road", "CT": "court",
    "COURT": "court", "WAY": "way", "LN": "lane", "PL": "place",
    "HWY": "highway", "BLVD": "boulevard", "CIR": "circle", "LOOP": "loop",
    "PKWY": "parkway", "TER": "terrace", "RUN": "run", "PLZ": "plaza",
    "ALY": "alley", "TRL": "trail", "TRAIL": "trail", "PT": "point",
    "GRV": "grove", "PARK": "park", "PATH": "path", "SQ": "square",
    "VW": "view", "GLN": "glen", "ARC": "arc", "EXT": "extension",
}
SKIP_CLASS = {"FREEWAY", "RAMP", "FUTURE"}


# -------------------------------------------------------------------- fetching
def _get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"{url}: {d['error']}")
    return d


def fetch_streets() -> list[dict]:
    rows, off = [], 0
    while True:
        d = _get(STREETS_URL, {
            "where": "1=1", "outSR": 4326, "orderByFields": "OBJECTID",
            "outFields": "LEFTFROM,LEFTTO,RIGHTFROM,RIGHTTO,PREFIX,NAME,TYPE,CLASS",
            "resultOffset": off, "resultRecordCount": 1000,
            "geometryPrecision": 5, "f": "json"})
        feats = d.get("features", [])
        for f in feats:
            pts = [p for path in (f.get("geometry") or {}).get("paths") or []
                   for p in path]
            if pts:
                a = f["attributes"]
                a["a"], a["b"], a["m"] = pts[0], pts[-1], pts[len(pts) // 2]
                rows.append(a)
        off += len(feats)
        if not feats or (len(feats) < 1000 and not d.get("exceededTransferLimit")):
            return rows
        time.sleep(0.5)


def fetch_river() -> list:
    d = _get(RIVER_URL, {"where": "1=1", "outSR": 4326, "geometryPrecision": 5,
                         "maxAllowableOffset": 0.0003, "f": "json"})
    return [f["geometry"]["rings"] for f in d["features"]]


def fetch_cdp() -> list[dict]:
    w, s, e, n = METRO
    d = _get(CDP_URL, {
        "geometry": f"{w - 0.08},{s - 0.05},{e + 0.02},{n + 0.05}",
        "geometryType": "esriGeometryEnvelope", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "BASENAME",
        "outSR": 4326, "geometryPrecision": 5, "f": "json"})
    return [{"name": f["attributes"]["BASENAME"], "rings": f["geometry"]["rings"]}
            for f in d["features"]]


def load(cache: Path | None) -> tuple[list, list, list]:
    out = []
    for name, fn in (("streets_raw.json", fetch_streets),
                     ("river.json", fetch_river), ("cdp.json", fetch_cdp)):
        p = cache / name if cache else None
        if p and p.exists():
            out.append(json.loads(p.read_text(encoding="utf-8")))
            continue
        data = fn()
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data), encoding="utf-8")
        out.append(data)
    return out[0], out[1], out[2]


# -------------------------------------------------------------------- geometry
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
    return sum(in_ring(x, y, r) for r in rings) % 2 == 1


class Lines:
    """Hwy 99 as lon-by-lat and the Kern River as lat-by-lon."""

    def __init__(self, streets: list[dict], river: list):
        pts = sorted({(p[1], p[0]) for s in streets
                      if (s["NAME"] or "").strip() == "99"
                      and (s["CLASS"] or "") == "FREEWAY"
                      for p in (s["a"], s["m"], s["b"])})
        self.h99 = pts
        self.edges = [(r[i], r[i + 1]) for rings in river for r in rings
                      for i in range(len(r) - 1)]

    def lon99(self, lat: float) -> float:
        p = self.h99
        if lat <= p[0][0]:
            return p[0][1]
        if lat >= p[-1][0]:
            return p[-1][1]
        for (la, lo), (lb, lob) in zip(p, p[1:]):
            if la <= lat <= lb:
                return lo if lb == la else lo + (lob - lo) * (lat - la) / (lb - la)
        return p[-1][1]

    def river_lat(self, lon: float) -> float | None:
        ys = [a[1] + (b[1] - a[1]) * (lon - a[0]) / (b[0] - a[0])
              for a, b in self.edges
              if a[0] != b[0] and min(a[0], b[0]) <= lon <= max(a[0], b[0])]
        return (min(ys) + max(ys)) / 2 if ys else None


def classify(lon: float, lat: float, lines: Lines, cdps: list[dict]) -> str:
    for c in cdps:
        if c["name"] in CDP_OUTSIDE and in_rings(lon, lat, c["rings"]):
            return "X"
    for c in cdps:
        if c["name"] in CDP_REGION and in_rings(lon, lat, c["rings"]):
            return CDP_REGION[c["name"]]
    w, s, e, n = METRO
    if not (w <= lon <= e and s <= lat <= n):
        return "X"
    rl = lines.river_lat(lon)
    north = rl is not None and lat > rl
    if lon < lines.lon99(lat):
        if not north:
            return "SW"
        return "N" if lon > FRUITVALE_AVE else "NW"
    if north:
        return "N"
    if lat < BRUNDAGE_LN:
        return "S" if lon < UNION_AVE else "SE"
    return "C" if lon < UNION_AVE else "E"


# ----------------------------------------------------------------------- build
def street_key(seg: dict) -> str | None:
    name = " ".join((seg["NAME"] or "").split()).lower()
    if not name or (seg["CLASS"] or "") in SKIP_CLASS:
        return None
    typ = TYPES.get((seg["TYPE"] or "").strip().upper(), "")
    pre = (seg["PREFIX"] or "").strip().lower()
    return " ".join(x for x in (pre, name, typ) if x)


def build(streets: list[dict], river: list, cdps: list[dict]) -> dict:
    lines = Lines(streets, river)
    by: dict[str, list] = collections.defaultdict(list)
    for s in streets:
        key = street_key(s)
        if not key:
            continue
        nums = [int(s[k]) for k in ("LEFTFROM", "LEFTTO", "RIGHTFROM", "RIGHTTO")
                if s.get(k)]
        reg = classify(s["m"][0], s["m"][1], lines, cdps)
        by[key].append((min(nums) if nums else 0, max(nums) if nums else 0, reg))
    # Every street carries its block ranges, even one that sits in a single
    # part of town: 'Niles Street' and 'W Niles Street' are told apart by number.
    table = {}
    for key, segs in sorted(by.items()):
        merged: list[list] = []
        for lo, hi, reg in sorted(segs):
            if merged and merged[-1][2] == reg and (lo > 0) == (merged[-1][0] > 0):
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi, reg])
        table[key] = merged
    return table


def main() -> int:
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    streets, river, cdps = load(cache)
    table = build(streets, river, cdps)
    OUT.write_text(json.dumps(table, separators=(",", ":"), sort_keys=True),
                   encoding="utf-8")
    counts = collections.Counter(
        v[0][2] if len({r[2] for r in v}) == 1 else "split"
        for v in table.values())
    print(f"{len(table)} streets -> {OUT.relative_to(ROOT)}  {dict(counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
