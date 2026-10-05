#!/usr/bin/env python3
"""EPA AirNow — current + forecast AQI for Bakersfield (zip 93301).

Free API key (docs.airnowapi.org → register). Reads AIRNOW_API_KEY from the
environment (repo secret on GitHub; .env locally). Without a key the source
returns needs_key=True and pages show an honest "waiting for key" state —
never a fake number. Keyless-friendly: one current-observation call + one
forecast call per build (~2 calls/day).
"""
from __future__ import annotations

import os

from .. import common

ZIP = "93301"
DISTANCE = 25
# AirNow retired the per-zip and per-lat/long services on 2026-10-01 (they answer 410 with
# "This web service has been retired"). These are the replacement "ziplatlong" services: same
# key, different field names (nowcastAQI / aqiCategoryName; forecasts carry dateValid).
OBS_URL = ("https://www.airnowapi.org/aq/observation/current/ziplatlong/"
           f"?format=application/json&zipCode={ZIP}&distance={DISTANCE}&API_KEY={{key}}")
FC_URL = ("https://www.airnowapi.org/aq/forecast/current/ziplatlong/"
          f"?format=application/json&zipCode={ZIP}&distance={DISTANCE}&API_KEY={{key}}")

# The observation service names the category but no longer numbers it.
CAT_NUM = {"good": 1, "moderate": 2, "unhealthy for sensitive groups": 3,
           "unhealthy": 4, "very unhealthy": 5, "hazardous": 6}

# EPA category number -> css class
CAT_CLASS = {1: "aqi-good", 2: "aqi-mod", 3: "aqi-usg", 4: "aqi-unh", 5: "aqi-vunh", 6: "aqi-haz"}


def run(ctx):
    key = os.environ.get("AIRNOW_API_KEY", "").strip()
    if not key:
        return {"ok": False, "needs_key": True,
                "error": "AIRNOW_API_KEY not set (register free at docs.airnowapi.org)"}

    out = {"ok": True, "aqi": None, "category": None, "category_num": None,
           "parameter": None, "area": None, "observed": None, "asof": common.iso_today()}

    # current observation (per pollutant; EPA reports the max as the AQI)
    try:
        r = common.fetch(OBS_URL.format(key=key), timeout=20)
        rows = r.json() if isinstance(r.json(), list) else []
        rows = [x for x in rows if x.get("nowcastAQI") is not None]
        if rows:
            worst = max(rows, key=lambda x: x["nowcastAQI"])
            name = worst.get("aqiCategoryName")
            out.update({
                "aqi": worst["nowcastAQI"],
                "category": name,
                "category_num": CAT_NUM.get(str(name or "").lower()),
                "parameter": worst.get("parameterName"),
                "area": worst.get("reportingAreaName"),
                "observed": f"{worst.get('dateObserved', '')} {worst.get('hourObserved', '')}".strip(),
            })
    except Exception as e:  # noqa: BLE001
        common.log(f"airnow observation failed: {type(e).__name__}: {e}")

    # today's forecast
    try:
        date = common.iso_today()
        r = common.fetch(FC_URL.format(key=key), timeout=20)
        rows = r.json() if isinstance(r.json(), list) else []
        today_rows = [x for x in rows if x.get("aqi") is not None
                      and str(x.get("dateValid", ""))[:10] == date]
        if today_rows:
            worst = max(today_rows, key=lambda x: x["aqi"])
            out["forecast"] = {
                "aqi": worst["aqi"],
                "category": worst.get("categoryName"),
                "category_num": worst.get("categoryNumber"),
                "parameter": worst.get("parameterName"),
            }
    except Exception as e:  # noqa: BLE001
        common.log(f"airnow forecast failed: {type(e).__name__}: {e}")

    if out["aqi"] is None and "forecast" not in out:
        return {"ok": False, "error": "AirNow returned no data"}
    return out


def css_class(category_num) -> str:
    return CAT_CLASS.get(category_num, "")
