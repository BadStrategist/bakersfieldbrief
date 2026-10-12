#!/usr/bin/env python3
"""Which Kern County city or Census place a point is in.

A town on a camera's record, and a camera's place on /surveillance/<town>/, is a looked-up
fact: the point is inside that place's Census boundary or it has no town. Never a geocoder's
address string, never the nearest town, never a box. A camera on Interstate 5 at the Grapevine
is in no place, and says so by having none.

The boundaries are build/kern_places.json (scripts/build_kern_places.py, Census TIGERweb).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent / "kern_places.json"

_places: list | None = None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def load() -> list:
    """Every place with its bounding box, cities first so a city wins a shared edge."""
    global _places
    if _places is None:
        try:
            raw = json.loads(SRC.read_text(encoding="utf-8")).get("places") or []
        except (OSError, ValueError):
            raw = []
        out = []
        for p in raw:
            xs = [pt[0] for r in p["rings"] for pt in r]
            ys = [pt[1] for r in p["rings"] for pt in r]
            out.append({**p, "slug": slug(p["name"]),
                        "bbox": (min(xs), min(ys), max(xs), max(ys))})
        out.sort(key=lambda p: (p["kind"] != "city", p["name"]))
        _places = out
    return _places


def place_of(lat, lon) -> dict | None:
    """The place holding this point: {"name", "kind" ("city" or "cdp"), "slug"}, or None."""
    if lat is None or lon is None:
        return None
    x, y = float(lon), float(lat)
    for p in load():
        w, s, e, n = p["bbox"]
        if not (w <= x <= e and s <= y <= n):
            continue
        # even-odd over every ring: a hole is outside, a second part is inside
        if sum(_in_ring(x, y, r) for r in p["rings"]) % 2 == 1:
            return {"name": p["name"], "kind": p["kind"], "slug": p["slug"]}
    return None


def _km_to(p: dict, lat: float, lon: float) -> float:
    """Kilometres from a point outside a place to that place's boundary."""
    kx, ky = 111.320 * math.cos(math.radians(lat)), 110.574
    best = float("inf")
    for ring in p["rings"]:
        pts = [((x - lon) * kx, (y - lat) * ky) for x, y in ring]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            t = 0.0 if not (dx or dy) else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def nearest(lat, lon, max_km: float) -> tuple[dict, float] | None:
    """For a point in no place: the closest place boundary within max_km, and the distance.

    A measurement, printed as one ("1.2 miles outside the Tehachapi city limits"). It never
    puts the point in the town."""
    if lat is None or lon is None:
        return None
    x, y = float(lon), float(lat)
    pad_y, pad_x = max_km / 110.574, max_km / (111.320 * math.cos(math.radians(y)))
    best = None
    for p in load():
        w, s, e, n = p["bbox"]
        if not (w - pad_x <= x <= e + pad_x and s - pad_y <= y <= n + pad_y):
            continue
        km = _km_to(p, y, x)
        if km <= max_km and (best is None or km < best[1]):
            best = (p, km)
    if not best:
        return None
    p, km = best
    return {"name": p["name"], "kind": p["kind"], "slug": p["slug"]}, km


def by_slug(s: str) -> dict | None:
    return next((p for p in load() if p["slug"] == s), None)


def center(p: dict) -> tuple[float, float]:
    """(lat, lon) of the middle of the place's bounding box, for a map's first frame."""
    w, s, e, n = p["bbox"]
    return ((s + n) / 2, (w + e) / 2)
