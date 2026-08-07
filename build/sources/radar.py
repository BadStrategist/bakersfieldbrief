#!/usr/bin/env python3
"""Bakersfield weather page data — NWS 7-day forecast (HNX gridpoint) plus the
live Hanford (KHNX) radar loop image URL. Free, no key."""
from __future__ import annotations

import datetime as dt

from .. import common

# Bakersfield gridpoint -> Hanford (HNX) forecast office. Radar loop is the
# standard KHNX product; NWS serves it keyless and hotlink-friendly.
POINTS_URL = "https://api.weather.gov/points/35.3733,-119.0187"
RADAR_URL = "https://radar.weather.gov/ridge/standard/KHNX_loop.gif"


def run(ctx):
    try:
        pt = common.fetch(POINTS_URL, headers={"Accept": "application/geo+json"})
        fc_url = pt.json()["properties"]["forecast"]
        periods = common.fetch(fc_url, headers={"Accept": "application/geo+json"}) \
            .json()["properties"]["periods"]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    days = []
    for p in periods:
        start = (p.get("startTime") or "")[:10]
        if not start:
            continue
        days.append({
            "name": p.get("name", ""),
            "day": start,
            "is_daytime": bool(p.get("isDaytime")),
            "short": p.get("shortForecast", ""),
            "temp": p.get("temperature"),
            "unit": p.get("temperatureUnit", "F"),
            "wind": p.get("windSpeed", ""),
            "humidity": (p.get("relativeHumidity") or {}).get("value"),
            "icon": p.get("icon", ""),
            "detailed": p.get("detailedForecast", ""),
        })

    return {"ok": True, "radar_url": RADAR_URL, "periods": days,
            "count": len(days), "asof": common.iso_today(),
            "generated": common.now_pacific().isoformat(timespec="minutes")}
