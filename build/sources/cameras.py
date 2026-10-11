#!/usr/bin/env python3
"""Caltrans traffic cameras in Kern County, from the District 6 and District 9 CCTV feeds.

Endpoints (verified 2026-10-11, keyless, public domain):
  https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.json   128 rows, 34 in Kern
  https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.json    23 rows, 10 in Kern
Each row is {"cctv": {...}} and every value is a string, booleans and numbers included.

Three things the feed does that this module is built around:
 - The picture address is whatever `currentImageURL` says. It is never put together from a
   camera name: the two districts name their files differently and guessed addresses fail.
 - `recordTimestamp` is when Caltrans last edited the row (years ago on most rows), not when
   the picture was taken, so it is never shown as a picture time. The picture's own time is
   the Last-Modified header on the JPEG, which the page reads in the browser.
 - `inService` is the string "true" or "false". A camera that is "false" stays on the list:
   the page says it is out of service instead of dropping it.

A district that cannot be read keeps its rows from the last good list. A change log
(data/change_logs/cameras.json) records cameras going out of service, coming back, and being
added to or dropped from the feed, capped at 60 entries.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

from .. import common

FEEDS = (
    ("6", "https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.json"),
    ("9", "https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.json"),
)
COUNTY = "Kern"
IMAGE_HOST = "cwwp2.dot.ca.gov"
LOG_NAME = "cameras"
LOG_CAP = 60

# Caltrans shorthand in District 6 location names. JNO and JEO are "just north of" and
# "just east of" in Caltrans' lane closure notices.
_WORDS = {
    "N/O": "north of", "S/O": "south of", "E/O": "east of", "W/O": "west of",
    "JNO": "just north of", "JSO": "just south of", "JEO": "just east of", "JWO": "just west of",
    "AT": "at", "RTE": "Route", "UC": "undercrossing", "OC": "overcrossing", "HWY": "Highway",
    "AVE": "Avenue", "DR": "Drive", "RD": "Road", "ST": "Street", "LN": "Lane", "MT": "Mt",
}
_PLACE_FIXES = {"Mc Farland": "McFarland"}
_POSITION = re.compile(r"^(just )?(north|south|east|west) of ", re.I)


def _rows(payload) -> list[dict]:
    """The camera rows of one feed, unwrapped from {"data": [{"cctv": {...}}]}."""
    out = []
    for item in (payload or {}).get("data") or []:
        row = item.get("cctv", item) if isinstance(item, dict) else None
        if isinstance(row, dict):
            out.append(row)
    return out


def _d6_name(location_name: str) -> str:
    """'KER-99-AT ROSEDALE HWY (ROUTE 178)' -> 'at Rosedale Highway (Route 178)'."""
    s = re.sub(r"^[A-Z]{2,3}-\d+-", "", location_name).replace("(", " (")
    words = []
    for w in s.split():
        head = "(" if w.startswith("(") else ""
        tail = ")" if w.endswith(")") else ""
        core = w[len(head):len(w) - len(tail)]
        rep = _WORDS.get(core) or (core.lower() if core[:1].isdigit() else core[:1] + core[1:].lower())
        words.append(head + rep + tail)
    return " ".join(words)


def _d9_name(location_name: str, description: str) -> str:
    """'US-395 : North of SR-14 2' + 'Looking South Zoom' -> 'north of SR-14, looking south zoom'.

    District 9 lists four cameras on one pole north of SR-14, told apart only by a trailing
    digit; Caltrans' own description of each view is what names them here.
    """
    name = location_name.split(" : ", 1)[-1].strip()
    if description:
        name = re.sub(r"\s\d+$", "", name) + ", " + description.strip().lower()
    if _POSITION.match(name):
        return name[:1].lower() + name[1:]
    return "at " + name


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def camera_id(image_url: str) -> str:
    """The file name Caltrans gave the picture, read out of its address: the stable key."""
    return PurePosixPath(urlparse(image_url or "").path).stem


def normalize(row: dict) -> dict | None:
    """One feed row -> the fields the pages use. None when the row cannot be identified."""
    loc = row.get("location") or {}
    image = row.get("imageData") or {}
    static = image.get("static") or {}
    raw_name = " ".join(str(loc.get("locationName") or "").split())
    url = str(static.get("currentImageURL") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != IMAGE_HOST:
        url = ""          # never hand the proxy an address that is not Caltrans' own
    cid = camera_id(url) or common.safe_filename(raw_name)
    if not raw_name or not cid:
        return None
    district = str(loc.get("district") or "").strip()
    description = " ".join(str(image.get("imageDescription") or "").split())
    where = _d9_name(raw_name, description) if " : " in raw_name else _d6_name(raw_name)
    route = str(loc.get("route") or "").strip()
    near = " ".join(str(loc.get("nearbyPlace") or "").split())
    every = _num(static.get("currentImageUpdateFrequency"))
    name = where[3:] if where.startswith("at ") else where
    return {
        "id": cid,
        "district": district,
        "caltrans_name": raw_name,
        "name": name[:1].upper() + name[1:],
        "label": f"{route} {where}".strip(),
        "route": route,
        "direction": str(loc.get("direction") or "").strip(),
        "near": _PLACE_FIXES.get(near, near),
        "lat": _num(loc.get("latitude")),
        "lon": _num(loc.get("longitude")),
        "elevation_ft": _num(loc.get("elevation")),
        "postmile": _num(loc.get("postmile")),
        "in_service": str(row.get("inService")).strip().lower() == "true",
        "image_url": url,
        "update_min": int(every) if every and every > 0 else None,
    }


def kern(payload) -> list[dict]:
    """Every camera a feed lists in Kern County, normalized."""
    out = []
    for row in _rows(payload):
        if str((row.get("location") or {}).get("county") or "").strip() != COUNTY:
            continue
        cam = normalize(row)
        if cam:
            out.append(cam)
    return out


# ---------------------------------------------------------------- change log
def _load_log() -> list:
    p = common.LOGS / f"{LOG_NAME}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no log yet, or unreadable: start again
        return []


def _save_log(log: list) -> None:
    (common.LOGS / f"{LOG_NAME}.json").write_text(
        json.dumps(log[:LOG_CAP], indent=1, default=str), encoding="utf-8")


def diff(previous: list, current: list, fresh_districts: set) -> list[dict]:
    """What changed between two lists, for the districts that were actually read this run."""
    now = common.now_pacific()
    stamp = {"date": now.date().isoformat(), "time": now.strftime("%I:%M %p").lstrip("0")}
    before = {c["id"]: c for c in previous if c.get("district") in fresh_districts}
    after = {c["id"]: c for c in current if c.get("district") in fresh_districts}
    out = []
    for cid, cam in after.items():
        old = before.get(cid)
        if old is None:
            change = "added to the Caltrans list"
        elif old.get("in_service") and not cam["in_service"]:
            change = "out of service"
        elif not old.get("in_service") and cam["in_service"]:
            change = "back in service"
        else:
            continue
        out.append(dict(stamp, id=cid, label=cam["label"], change=change))
    for cid, old in before.items():
        if cid not in after:
            out.append(dict(stamp, id=cid, label=old.get("label", cid),
                            change="dropped from the Caltrans list"))
    return out


# ---------------------------------------------------------------- run
def run(ctx):
    last = common.load_snapshot("cameras_last", default={}) or {}
    last_cams = last.get("cameras") or []
    cams, fresh, failed = [], set(), []
    for district, url in FEEDS:
        try:
            rows = kern(common.fetch(url, timeout=25).json())
            if not rows:
                raise ValueError("no Kern County rows in the feed")
            cams.extend(rows)
            fresh.add(district)
        except Exception as e:  # noqa: BLE001
            common.log(f"cameras district {district} failed: {type(e).__name__}: {e}")
            failed.append(district)
            cams.extend(c for c in last_cams if c.get("district") == district)

    now = common.now_pacific()
    if not fresh:
        # graceful stale fallback, same shape as roads.py: the last good list, flagged, so the
        # page keeps every camera's name and place and says the list could not be re-read.
        if last_cams:
            return {"ok": False, "last_good": True, "stale": True, "cameras": last_cams,
                    "asof": last.get("asof", ""), "fetched_at": last.get("fetched_at", ""),
                    "log": _load_log(), "log_started": last.get("log_started", ""),
                    "error": "both Caltrans camera feeds unreachable"}
        return {"ok": False, "error": "both Caltrans camera feeds unreachable", "cameras": [],
                "log": _load_log()}

    log = _load_log()
    started = last.get("log_started") or now.date().isoformat()
    if last_cams:
        # No previous list means no baseline: record it now and log from the next change on.
        log = diff(last_cams, cams, fresh) + log
        _save_log(log)
    out = {"ok": True, "cameras": cams, "asof": now.date().isoformat(),
           "fetched_at": now.strftime("%Y-%m-%d %H:%M"), "log_started": started}
    if failed:
        out["stale_districts"] = failed
    common.save_snapshot("cameras_last", out)
    out["log"] = log[:LOG_CAP]
    return out
