#!/usr/bin/env python3
"""CHP incidents — media.chp.ca.gov/sa_xml/sa.xml.

Verified Aug 2026: Center/Dispatch IDs are XML *attributes*
(<Center ID="LAHB"><Dispatch ID="BFCC">), and element values are quoted
strings ("Aug  4 2026  1:24PM"). "Overnight" = logs we haven't seen yet in
this snapshot (new since last build). Bakersfield dispatch = BFCC under
center LAHB.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET

from .. import common

URL = "https://media.chp.ca.gov/sa_xml/sa.xml"
CENTER, DISPATCH = "LAHB", "BFCC"


def run(ctx):
    try:
        r = common.fetch(URL, timeout=40)
        root = ET.fromstring(r.content)
        logs = []
        for center in root.findall("Center"):
            if (center.get("ID") or "").upper() != CENTER:
                continue
            for disp in center.findall("Dispatch"):
                if (disp.get("ID") or "").upper() != DISPATCH:
                    continue
                for log in disp.findall("Log"):
                    logs.append(_log_to_dict(log))

        logs.sort(key=lambda x: x.get("time", ""))
        snapshot = common.load_snapshot("chp_seen", default=[])
        seen = set(snapshot)
        fresh = [l for l in logs if l["log_id"] not in seen]
        common.save_snapshot("chp_seen", [l["log_id"] for l in logs][-200:])

        # rolling 7-day archive so place pages show "last 7 days" not just today
        archive = common.load_snapshot("chp_archive", default=[])
        by_id = {a["log_id"]: a for a in archive}
        for l in logs:
            by_id[l["log_id"]] = l
        cutoff = ctx.today - dt.timedelta(days=7)
        pruned = []
        for a in by_id.values():
            t = _parse_log_time(a.get("time", ""))
            if t is None or t.date() >= cutoff:
                pruned.append(a)
        pruned.sort(key=lambda x: x.get("time", ""))
        common.save_snapshot("chp_archive", pruned)

        return {"ok": True, "logs": logs, "new": fresh, "archive": pruned,
                "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_LOG_TIME_FORMATS = ("%b %d %Y %I:%M%p", "%b %d %Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S")


def _parse_log_time(s: str):
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in _LOG_TIME_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _unquote(v: str | None) -> str:
    return (v or "").strip().strip('"')


def _log_to_dict(log) -> dict:
    latlon = _unquote(log.findtext("LATLON"))
    lat, lon = None, None
    m = re.match(r"(\d{7,8}):(\d{7,9})", latlon)
    if m:
        lat = int(m.group(1)) / 1_000_000
        lon = -int(m.group(2)) / 1_000_000  # CHP values are unsigned; CA is west → negative
    return {
        "log_id": _unquote(log.get("ID") or log.findtext("LogId")),
        "time": _unquote(log.findtext("LogTime")),
        "type": _unquote(log.findtext("LogType")),
        "location": _unquote(log.findtext("Location")),
        "area": _unquote(log.findtext("Area")),
        "lat": lat,
        "lon": lon,
        "details": _unquote(log.findtext("IncidentDetail"))[:160],
    }
