#!/usr/bin/env python3
"""Isabella Lake water data — CDEC station ISB (Lake Isabella, Kern River).

Pulls the three daily reservoir readings every build:
  * storage   — sensor 15 (STORAGE, acre-feet)  [the long-standing source]
  * elevation — sensor 6  (RES ELEV, feet above MSL)
  * inflow    — sensor 23 (RES INFLOW, cubic feet/sec)

Verified Aug-Sep 2026: the CDEC JSONDataServlet returns a FLAT JSON array (not
{data:[...]}); each record {stationId, SENSOR_NUM, date, obsDate, value, units}.
value=-9999 (or empty) means missing/no data — each sensor's most recent valid
reading is kept, plus a 30-day storage series for the tracker chart.

Full pool elevation is 2605.5 ft (spillway crest). Storage capacity 568,000 AF.
"""
from __future__ import annotations

import datetime as dt

from .. import common

_URL = ("https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet"
        "?Stations=ISB&SensorNums={sn}&dur_code=D&Start={start}&End={end}")
CAPACITY_AF = 568_000          # Lake Isabella full capacity, acre-feet
FULL_POOL_FT = 2605.5          # spillway / full-pool elevation, feet MSL
SENSORS = {"storage_af": 15, "elev_ft": 6, "inflow_cfs": 23}
SERIES_DAYS = 30
_BAD = {"", "-9999", "na", "nan", "m"}


def _num(v) -> float | None:
    """Parse a CDEC value, rejecting missing sentinels."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= -5000 or f == -9999:
        return None
    return f


def _sensor_series(sess_rows) -> list[dict]:
    """Dedupe by day and sort chronologically (CDEC can return duplicated or
    out-of-order daily rows). One reading per date, newest last."""
    import datetime as _dt
    by_day: dict[str, float] = {}
    for row in sess_rows:
        v = _num(row.get("value"))
        if v is None:
            continue
        dstr = row.get("obsDate") or row.get("date") or ""
        # normalize CDEC '2026-9-5 00:00' -> '2026-09-05'
        m = __import__("re").match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(dstr))
        if not m:
            continue
        key = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        # last reading wins for a day
        by_day[key] = v
    return [{"date": k, "value": round(by_day[k], 2)} for k in sorted(by_day)]


def run(ctx):
    end = ctx.today.isoformat()
    start = (ctx.today - dt.timedelta(days=SERIES_DAYS + 7)).isoformat()
    try:
        readings = {}
        for name, sn in SENSORS.items():
            r = common.fetch(_URL.format(sn=sn, start=start, end=end), timeout=40)
            j = r.json()
            rows = j if isinstance(j, list) else j.get("data", [])
            readings[name] = _sensor_series(rows)
        if not readings.get("storage_af"):
            raise ValueError("no valid storage readings")

        last_s = readings["storage_af"][-1]
        last_e = readings["elev_ft"][-1] if readings.get("elev_ft") else None
        last_i = readings["inflow_cfs"][-1] if readings.get("inflow_cfs") else None

        return {
            "ok": True,
            # --- legacy keys (numbers.py, daily.py, emailer.py, sunday_read.py) ---
            "last": {"value": round(last_s["value"]), "date": last_s["date"],
                     "af": round(last_s["value"])},
            "series": readings["storage_af"][-SERIES_DAYS:],
            "pct": round(100 * last_s["value"] / CAPACITY_AF, 1),
            "capacity_af": CAPACITY_AF,
            "trend": (f"{readings['storage_af'][-1]['value'] - readings['storage_af'][0]['value']:+,} AF"
                      if len(readings["storage_af"]) > 1 else ""),
            # --- new keys (water tracker elevation/inflow) ---
            "storage": {"value": round(last_s["value"]), "date": last_s["date"],
                        "af": round(last_s["value"])},
            "elev_ft": {"value": round(last_e["value"], 2),
                        "date": last_e["date"]} if last_e else None,
            "inflow_cfs": {"value": round(last_i["value"]),
                           "date": last_i["date"]} if last_i else None,
            "full_pool_ft": FULL_POOL_FT,
            "storage_series": readings["storage_af"][-SERIES_DAYS:],
            "asof": common.iso_today(),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
