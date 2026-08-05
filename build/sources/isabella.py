#!/usr/bin/env python3
"""Isabella Lake storage — CDEC station ISB, sensor 15 (STORAGE, acre-feet).

Verified Aug 2026: returns a FLAT JSON array (not {data:[...]}), each record
{stationId, SENSOR_NUM, date, obsDate, value, units}. value=-9999 means
missing/no data yet today — the module returns the most recent valid reading
plus a 30-day series for the tracker chart.
"""
from __future__ import annotations

import datetime as dt

from .. import common

URL = ("https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet"
       "?Stations=ISB&SensorNums=15&dur_code=D&Start={start}&End={end}")
CAPACITY_AF = 568_000  # Lake Isabella full capacity, acre-feet
SERIES_DAYS = 30


def run(ctx):
    try:
        end = ctx.today.isoformat()
        start = (ctx.today - dt.timedelta(days=SERIES_DAYS + 7)).isoformat()
        r = common.fetch(URL.format(start=start, end=end), timeout=40)
        j = r.json()
        rows = j if isinstance(j, list) else j.get("data", [])

        series = []
        for row in rows:
            try:
                v = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            if v <= 0 or v == -9999:
                continue
            series.append({"date": (row.get("obsDate") or row.get("date") or ""),
                           "value": round(v)})

        series.sort(key=lambda x: x["date"])
        last = series[-1] if series else None
        pct = round(100 * last["value"] / CAPACITY_AF, 1) if last else None

        return {"ok": True, "last": last, "pct": pct, "capacity_af": CAPACITY_AF,
                "series": series[-SERIES_DAYS:], "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
