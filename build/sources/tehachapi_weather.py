#!/usr/bin/env python3
"""Tehachapi Pass weather source — all keyless NWS API.

Tehachapi Pass (SR-58, summit ~4,067 ft) current conditions + forecast + zone
alerts. Uses:
  - KTSP (Tehachapi Municipal Airport) /observations/latest  → current temp/wind/gust
  - NWS gridpoint 35.1322,-118.4490 (HNX/87,20) forecast    → 7-day periods + wind
  - the same gridpoint's hourly forecast                     → next 12 hours
  - NWS zone forecast CAZ334 alerts                          → Kern/pass advisories

Every fetch degrades independently (partial dict, never raises) so the page can
show what it has and honestly label what it lacks.
"""
from __future__ import annotations

import datetime as dt

from .. import common

PASS_POINT = "35.1322,-118.4490"      # Tehachapi → HNX/87,20
ZONE = "CAZ334"
PRIMARY_STATION = "KTSP"              # Tehachapi Municipal Airport
_FALLBACK_STATIONS = ["SE067", "C1020"]  # Cummings Valley (SCE), CWOP

_WIND_DIR = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def run(ctx):
    out = {"ok": True, "current": {}, "forecast": [], "alerts": [],
           "asof": common.iso_today(), "sources": {"point": PASS_POINT, "zone": ZONE}}
    out["current"] = _current()
    fc_url, hourly_url = _point_urls()
    out["forecast"] = _forecast(fc_url)
    out["hourly"] = _hourly(hourly_url)
    out["alerts"] = _alerts()
    return out


# ----------------------------------------------------------------- current conditions
def _current() -> dict:
    """Live observation from KTSP (fallback stations tried in order). Returns a
    partial dict with the fields it got; any failure leaves them absent (the
    builder renders 'unavailable this build' rather than inventing a reading)."""
    out = {}
    stations = [PRIMARY_STATION] + _FALLBACK_STATIONS
    for st in stations:
        try:
            props = common.fetch(
                f"https://api.weather.gov/stations/{st}/observations/latest",
                headers={"Accept": "application/geo+json"}).json().get("properties", {})
            c = (props.get("temperature") or {}).get("value")
            if c is None:
                continue   # empty obs, try next station
            out["station"] = st
            out["temperature"] = round(c * 9 / 5 + 32)  # C -> F
            out["wind_mph"] = common.wind_mph(props.get("windSpeed"))
            out["gust_mph"] = common.wind_mph(props.get("windGust"))
            for k in ("wind_mph", "gust_mph"):      # drop nulls: renderer keys off presence
                if out[k] is None:
                    del out[k]
            wd = (props.get("windDirection") or {}).get("value")
            if wd is not None:
                out["wind_dir_deg"] = int(wd)
                out["wind_dir"] = _WIND_DIR[int(wd / 22.5) % 16]
            out["condition"] = (props.get("textDescription") or "").strip()
            rh = (props.get("relativeHumidity") or {}).get("value")
            if rh is not None:
                out["humidity"] = round(rh)
            ts = props.get("timestamp") or ""
            out["timestamp"] = ts     # the live script only replaces this with a NEWER reading
            if ts:
                try:
                    out["observed"] = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                        common.PACIFIC).strftime("%b %d, %I:%M %p").lstrip("0")
                except Exception:  # noqa: BLE001
                    pass
            out["ok"] = True
            return out
        except Exception:  # noqa: BLE001
            continue
    out["ok"] = False
    return out


# ----------------------------------------------------------------- forecast
def _point_urls() -> tuple[str, str]:
    """The gridpoint's 7-day and hourly forecast URLs ('' when NWS is unreachable)."""
    try:
        props = common.fetch(f"https://api.weather.gov/points/{PASS_POINT}",
                             headers={"Accept": "application/geo+json"}).json()["properties"]
        return props.get("forecast") or "", props.get("forecastHourly") or ""
    except Exception:  # noqa: BLE001
        return "", ""


def _pop(p: dict):
    """Chance of precipitation in %, or None when NWS gave none."""
    return (p.get("probabilityOfPrecipitation") or {}).get("value")


def _forecast(fc_url: str) -> list:
    """All NWS 7-day forecast periods (day + night, ~14) with temp and wind.
    The pass page shows only the first five; the weather page groups them by day."""
    periods = []
    if not fc_url:
        return periods
    try:
        props = common.fetch(fc_url, headers={"Accept": "application/geo+json"}).json()["properties"]
    except Exception:  # noqa: BLE001
        return periods
    for p in props.get("periods", []):
        periods.append({
            "name": p.get("name", ""),
            "is_daytime": p.get("isDaytime", True),
            "temp_f": p.get("temperature"),
            "wind_speed": (p.get("windSpeed") or "").strip(),
            "wind_dir": (p.get("windDirection") or "").strip(),
            "short": (p.get("shortForecast") or ""),
            "pop": _pop(p),
            "starts": (p.get("startTime") or "")[:10],
        })
    return periods


def _hourly(hourly_url: str) -> list:
    """The next 12 hours from the NWS hourly forecast, in Pacific time."""
    hours = []
    if not hourly_url:
        return hours
    try:
        props = common.fetch(hourly_url, headers={"Accept": "application/geo+json"}).json()["properties"]
    except Exception:  # noqa: BLE001
        return hours
    now = dt.datetime.now(dt.timezone.utc)
    for p in props.get("periods", []):
        try:
            start = dt.datetime.fromisoformat(p["startTime"])
            end = dt.datetime.fromisoformat(p["endTime"])
        except Exception:  # noqa: BLE001
            continue
        if end <= now:
            continue   # an hour that has already passed
        hours.append({
            "time": start.astimezone(common.PACIFIC).strftime("%I %p").lstrip("0"),
            "temp_f": p.get("temperature"),
            "wind_speed": (p.get("windSpeed") or "").strip(),
            "wind_dir": (p.get("windDirection") or "").strip(),
            "short": (p.get("shortForecast") or ""),
            "pop": _pop(p),
        })
        if len(hours) == 12:
            break
    return hours


# ----------------------------------------------------------------- alerts
def _alerts() -> list:
    """Active NWS alerts for the Tehachapi zone (CAZ334)."""
    try:
        raw = common.fetch(f"https://api.weather.gov/alerts/active/zone/{ZONE}",
                           headers={"Accept": "application/geo+json"}).json()
        out = []
        for f in raw.get("features", []):
            p = f.get("properties", {})
            out.append({
                "event": p.get("event", ""),
                "severity": p.get("severity", ""),
                "headline": p.get("headline", ""),
                "starts": p.get("effective", ""),
                "ends": p.get("expires", ""),
                "url": p.get("url", ""),
            })
        order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
        out.sort(key=lambda a: order.get(a["severity"], 4))
        return out
    except Exception:  # noqa: BLE001
        return []