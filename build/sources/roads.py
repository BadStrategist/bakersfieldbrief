#!/usr/bin/env python3
"""Caltrans road conditions — I-5 (Grapevine/Tejon Pass), SR-58, SR-99.

Endpoint: https://roads.dot.ca.gov/roadscell.php?roadnumber=N (verified Aug
2026 — compact HTML, one timestamped condition text per route, sections like
"[IN THE CENTRAL CALIFORNIA AREA] ..."). The page's own timestamp ("latest
reported as of <date/time>") is kept verbatim — it is displayed, never
replaced by our build time.

Status is classified per route from the section text (CLOSED > RESTRICTIONS
> OPEN), with careful negation handling ("no traffic restrictions" must not
trip CLOSED). A change log (data/change_logs/roads.json) records every
status flip plus material text changes, capped at 60 entries.
"""
from __future__ import annotations

import hashlib
import re

from .. import common

ROUTES = [
    {"number": "5", "name": "Interstate 5 — Grapevine (Tejon Pass)", "slug": "i5", "pass": True},
    {"number": "58", "name": "State Route 58 — Tehachapi", "slug": "sr58", "pass": False},
    {"number": "99", "name": "State Route 99 — Central Valley", "slug": "sr99", "pass": False},
]
URL = "https://roads.dot.ca.gov/roadscell.php?roadnumber={n}"

_STATUS = ("OPEN", "RESTRICTIONS", "CLOSED")
_NO_PROBLEM = re.compile(r"no (traffic )?(restrictions|closures?|incidents?|delays?)", re.I)


def run(ctx):
    out = {"ok": True, "routes": [], "asof": common.iso_today()}
    for route in ROUTES:
        try:
            r = common.fetch(URL.format(n=route["number"]), timeout=25)
            parsed = _parse(r.text, route)
            if parsed:
                out["routes"].append(parsed)
        except Exception as e:  # noqa: BLE001
            common.log(f"roads {route['number']} failed: {type(e).__name__}: {e}")
    if not out["routes"]:
        return {"ok": False, "error": "no Caltrans routes parsed"}

    # ---- diff against snapshot + change log
    snap = common.load_snapshot("roads", default={})
    log = common.load_snapshot("roads_log", default=[])
    for rte in out["routes"]:
        prev = snap.get(rte["slug"], {})
        if prev.get("status") != rte["status"] and prev:
            log.insert(0, {
                "ts": common.iso_today(),
                "route": rte["slug"],
                "route_name": rte["name"],
                "from": prev.get("status", "?"),
                "to": rte["status"],
            })
        elif prev.get("hash") != rte["hash"] and prev:
            log.insert(0, {
                "ts": common.iso_today(),
                "route": rte["slug"],
                "route_name": rte["name"],
                "from": "updated",
                "to": rte["status"],
                "note": "condition text changed",
            })
    log = log[:60]
    common.save_snapshot("roads_log", log)
    common.save_snapshot("roads", {x["slug"]: {"status": x["status"], "hash": x["hash"]}
                                   for x in out["routes"]})
    out["log"] = log
    return out


# ---------------------------------------------------------------- parse
_SECTION = re.compile(r"\[IN THE ([A-Z ]+?) AREA\](.*?)(?=\[IN THE |$)", re.S)
_TS = re.compile(r"latest reported as of (.+?)(?=\.\s|\.$)", re.I)


def _parse(html: str, route: dict) -> dict:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    ts = ""
    m = _TS.search(text)
    if m:
        ts = m.group(1).strip()

    sections = []
    for region, body in _SECTION.findall(text):
        body = re.sub(r"\s+", " ", body).strip().strip("&#160;").strip()
        if body and "no traffic restrictions" not in body.lower():
            sections.append({"region": region.strip(), "text": body})
        elif body:
            sections.append({"region": region.strip(), "text": "No traffic restrictions reported."})

    # per-section status so builders can headline the pass (Central CA area)
    for s in sections:
        s["status"] = _section_status(s["text"])

    status = _classify(sections) if sections else "OPEN"
    detail_text = " ".join(f"{s['region']}: {s['text']}" for s in sections)
    pass_status = next((s["status"] for s in sections
                        if "CENTRAL" in s["region"].upper()), status)
    return {
        "number": route["number"],
        "slug": route["slug"],
        "name": route["name"],
        "pass": route.get("pass", False),
        "status": status,
        "pass_status": pass_status if route.get("pass") else status,
        "sections": sections,
        "reported_as_of": ts,
        "hash": hashlib.md5(detail_text.encode()).hexdigest()[:10],
    }


def _section_status(t: str) -> str:
    if _NO_PROBLEM.search(t):
        return "OPEN"
    if re.search(r"\bis\s+closed\b|\bare\s+closed\b|will be closed|is currently closed", t, re.I):
        return "CLOSED"
    if re.search(r"\bclosed\b|\brestrictions?\b|chains|reduced to \d lane|one lane|two lanes closed|"
                 r"\bwind\b|\bfog\b|snow|traffic hazard|collision|disabled vehicle", t, re.I):
        return "RESTRICTIONS"
    return "OPEN"


def _classify(sections: list[dict]) -> str:
    worst = "OPEN"
    for s in sections:
        t = s["text"]
        if _NO_PROBLEM.search(t):
            continue
        if re.search(r"\bis\s+closed\b|\bare\s+closed\b|will be closed|is currently closed", t, re.I):
            return "CLOSED"
        if re.search(r"\bclosed\b|\brestrictions?\b|chains|reduced to \d lane|one lane|two lanes closed|"
                     r"\bwind\b|\bfog\b|snow|traffic hazard|collision|disabled vehicle", t, re.I):
            worst = "RESTRICTIONS"
    return worst
