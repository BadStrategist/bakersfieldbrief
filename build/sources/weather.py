#!/usr/bin/env python3
"""NWS weather alerts — api.weather.gov/alerts/active?area=CA, filtered to Kern."""
from __future__ import annotations

import datetime as dt

from .. import common

URL = "https://api.weather.gov/alerts/active?area=CA"


def run(ctx):
    try:
        r = common.fetch(URL, headers={"Accept": "application/geo+json"})
        features = r.json().get("features", [])
        kern = []
        for f in features:
            p = f.get("properties", {})
            area_desc = p.get("areaDesc") or ""
            if "Kern" not in area_desc:
                continue
            kern.append({
                "event": p.get("event", ""),
                "severity": p.get("severity", ""),
                "headline": p.get("headline", ""),
                "description": (p.get("description") or "")[:400],
                "instruction": (p.get("instruction") or "")[:300],
                "starts": p.get("effective", ""),
                "ends": p.get("expires", ""),
                "url": p.get("url", ""),
                "areas": area_desc,
            })
        # sort: active first (by end time), then by severity
        order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
        kern.sort(key=lambda a: (order.get(a["severity"], 4), a["ends"]))
        return {"ok": True, "alerts": kern, "count": len(kern),
                "forecast": _bakersfield_forecast(), "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _bakersfield_forecast() -> dict:
    """Today's high/low from the NWS gridpoint forecast for downtown Bakersfield
    (35.3733, -119.0187 → Hanford/HNX office) + current temp from the KBFL
    airport observation station. All free, no key. Any failure → partial dict."""
    out = {"high": None, "low": None, "current": None}
    try:
        pt = common.fetch("https://api.weather.gov/points/35.3733,-119.0187",
                          headers={"Accept": "application/geo+json"})
        fc_url = pt.json()["properties"]["forecast"]
        periods = common.fetch(fc_url, headers={"Accept": "application/geo+json"}).json()["properties"]["periods"]
        today = dt.date.today().isoformat()
        highs, lows = [], []
        for p in periods:
            if (p.get("startTime") or "")[:10] == today:
                if p.get("isDaytime"):
                    highs.append(p.get("temperature"))
                else:
                    lows.append(p.get("temperature"))
        if highs:
            out["high"] = max(highs)
        if lows:
            out["low"] = min(lows)
    except Exception:  # noqa: BLE001
        pass
    try:
        obs = common.fetch("https://api.weather.gov/stations/KBFL/observations/latest",
                           headers={"Accept": "application/geo+json"}).json()["properties"]
        c = (obs.get("temperature") or {}).get("value")
        if c is not None:
            out["current"] = round(c * 9 / 5 + 32)
    except Exception:  # noqa: BLE001
        pass
    return out
