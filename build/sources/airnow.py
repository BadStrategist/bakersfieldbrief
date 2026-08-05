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
OBS_URL = ("https://www.airnowapi.org/aq/observation/zipCode/current/"
           f"?format=application/json&zipCode={ZIP}&distance={DISTANCE}&API_KEY={{key}}")
FC_URL = ("https://www.airnowapi.org/aq/forecast/zipCode/"
          f"?format=application/json&zipCode={ZIP}&date={{date}}&distance={DISTANCE}&API_KEY={{key}}")

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
        rows = [x for x in rows if x.get("AQI") is not None]
        if rows:
            worst = max(rows, key=lambda x: x["AQI"])
            out.update({
                "aqi": worst["AQI"],
                "category": worst.get("Category", {}).get("Name"),
                "category_num": worst.get("Category", {}).get("Number"),
                "parameter": worst.get("ParameterName"),
                "area": worst.get("ReportingArea"),
                "observed": f"{worst.get('DateObserved', '')} {worst.get('HourObserved', '')}:00",
            })
    except Exception as e:  # noqa: BLE001
        common.log(f"airnow observation failed: {type(e).__name__}: {e}")

    # today's forecast
    try:
        date = common.iso_today()
        r = common.fetch(FC_URL.format(date=date, key=key), timeout=20)
        rows = r.json() if isinstance(r.json(), list) else []
        today_rows = [x for x in rows if x.get("AQI") is not None
                      and str(x.get("DateForecast", ""))[:10] == date]
        if today_rows:
            worst = max(today_rows, key=lambda x: x["AQI"])
            out["forecast"] = {
                "aqi": worst["AQI"],
                "category": worst.get("Category", {}).get("Name"),
                "category_num": worst.get("Category", {}).get("Number"),
                "parameter": worst.get("ParameterName"),
            }
    except Exception as e:  # noqa: BLE001
        common.log(f"airnow forecast failed: {type(e).__name__}: {e}")

    if out["aqi"] is None and "forecast" not in out:
        return {"ok": False, "error": "AirNow returned no data"}
    return out


def css_class(category_num) -> str:
    return CAT_CLASS.get(category_num, "")
