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
import html as H
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

# Caltrans groups conditions by AREA, which is far too coarse to answer "is the
# pass open?": I-5's CENTRAL CALIFORNIA blob is a San Joaquin County wind
# advisory (200 miles north of Tejon Pass), and SR-58 ships ONE Central section,
# so a Bakersfield city collision was headlined as "Tehachapi Pass: CLOSED".
# Corridor keywords keep a pass answer scoped to places ON the corridor.
CORRIDOR = {
    "i5": ("TEJON", "LEBEC", "GORMAN", "GRAPEVINE", "FORT TEJON", "CASTAIC",
           "PYRAMID LAKE", "SR-138", "SMOKEY BEAR"),
    "sr58": ("TEHACHAPI", "KEENE", "MONOLITH", "BEALVILLE", "CALIENTE",
             "SR-202", "TOWER LINE", "WOODFORD", "TWIN OAKS"),
    "sr99": ("BAKERSFIELD", "DELANO", "WASCO", "MCFARLAND", "SHAFTER",
             "LAMONT", "KERN CO"),
}

# a problem phrase: the anchor we scope to a place
_PROBLEM = re.compile(
    r"is\s+closed|are\s+closed|will be closed|is currently closed|"
    r"closed|restrictions?|chains|reduced to \d lane|one lane|"
    r"two lanes closed|wind advisory|wind|fog|snow|traffic hazard|"
    r"collision|disabled vehicle", re.I)
_PLACE = re.compile(r"/in ([^/]+)/\s*\(([A-Za-z .]+?) Co\)")
_COUNTY = re.compile(r"\(([A-Za-z .]+?) Co\)")
_WINDOW = 210


def run(ctx):
    out = {"ok": True, "routes": [], "asof": common.iso_today()}
    for route in ROUTES:
        try:
            r = common.fetch(URL.format(n=route["number"]), timeout=25)
            parsed = _parse(r.text, route)
            if parsed and not parsed.get("_no_report"):
                out["routes"].append(parsed)
        except Exception as e:  # noqa: BLE001
            common.log(f"roads {route['number']} failed: {type(e).__name__}: {e}")
    if not out["routes"]:
        # graceful stale fallback: reuse the last successful fetch, clearly
        # flagged so the builder can show "may be out of date" + a direct
        # Caltrans link instead of a bare error box.
        last = common.load_snapshot("roads_last", default={})
        if last.get("routes"):
            out["ok"] = False
            out["asof"] = last.get("asof", out["asof"])  # carry the real report date, not today
            out["routes"] = last["routes"]
            out["stale"] = True
            out["stale_note"] = ("Source (Caltrans) unreachable this build; showing the most "
                                 "recent report with its original timestamp.")
            out["last_good"] = True
            out["log"] = common.load_snapshot("roads_log", default=[])
            return out
        return {"ok": False, "error": "no Caltrans routes parsed"}

    # ---- one route failed while others parsed: keep its last good report, flagged stale, so a
    # partial outage neither drops the route from the page nor erases it from the snapshot (which
    # made its next real status change go unlogged).
    fresh_routes = list(out["routes"])
    fresh = {x["slug"] for x in fresh_routes}
    last = common.load_snapshot("roads_last", default={})
    for x in last.get("routes", []) or []:
        if x.get("slug") not in fresh:
            out["routes"].append(dict(x, stale=True))

    # ---- diff against snapshot + change log (fresh routes only)
    snap = common.load_snapshot("roads", default={})
    log = common.load_snapshot("roads_log", default=[])
    for rte in fresh_routes:
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
    snap.update({x["slug"]: {"status": x["status"], "hash": x["hash"]} for x in fresh_routes})
    common.save_snapshot("roads", snap)
    # full last-known payload so a later failed fetch can degrade gracefully
    common.save_snapshot("roads_last", out)
    out["log"] = log
    return out


# ---------------------------------------------------------------- parse
_SECTION = re.compile(r"\[IN THE ([A-Z ]+?) AREA\](.*?)(?=\[IN THE |$)", re.S)
_TS = re.compile(r"latest reported as of (.+?)(?=\.\s|\.$)", re.I)


def _parse(html: str, route: dict) -> dict:
    text = re.sub(r"<!--|-->", "", html)          # comment markers (keep inner text)
    text = re.sub(r"<[^>]+>", " ", text)           # tags → space
    text = H.unescape(text)                        # &#160; → \xa0, &amp; → &, …
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)               # collapse all whitespace

    ts = ""
    m = _TS.search(text)
    if m:
        ts = m.group(1).strip()

    sections = []
    for region, body in _SECTION.findall(text):
        body = re.sub(r"\s+", " ", body).strip(" .")
        if not body:
            continue
        if "no traffic restrictions" in body.lower():
            body = "No traffic restrictions reported."
        sections.append({"region": region.strip(), "text": _clean(body)})

    # per-section status so builders can headline the pass (Central CA area)
    for s in sections:
        s["status"] = _section_status(s["text"])

    # A Caltrans report always carries an "[IN THE ... AREA]" section or a "reported as of"
    # stamp. A page with neither (an outage or error page served with HTTP 200) is not a report,
    # and must not be read as "OPEN": the caller falls back to the last good report instead.
    if not sections and not ts:
        return {"_no_report": True}
    status = _classify(sections) if sections else "OPEN"
    detail_text = " ".join(f"{s['region']}: {s['text']}" for s in sections)
    scope = _scope(sections, route["slug"])
    pass_status = scope["on_pass"] if route.get("pass") else (
        scope["on_pass"] if scope["on_pass_reported"] else status)
    return {
        "number": route["number"],
        "slug": route["slug"],
        "name": route["name"],
        "pass": route.get("pass", False),
        "status": status,
        "pass_status": pass_status if route.get("pass") else status,
        "sections": sections,
        "scope": scope,
        "reported_as_of": ts,
        "hash": hashlib.md5(detail_text.encode()).hexdigest()[:10],
    }


def _worst(statuses) -> str:
    if "CLOSED" in statuses:
        return "CLOSED"
    if "RESTRICTIONS" in statuses:
        return "RESTRICTIONS"
    return "OPEN"


def _scope(sections: list[dict], slug: str) -> dict:
    """Split Caltrans' area text into ON-CORRIDOR problems and everything else.

    Returns {"on_pass": status, "on_pass_reported": bool, "elsewhere": [...]}.
    `on_pass_reported` is False when no problem phrase names the corridor, which
    is Caltrans' way of saying nothing is wrong there; the page must then say
    "no problems reported on the pass" rather than claim a bare OPEN or CLOSED.
    """
    keywords = CORRIDOR.get(slug, ())
    on_corridor, elsewhere = [], []
    for s in sections:
        text = s["text"]
        for m in _PROBLEM.finditer(text):
            lo, hi = max(0, m.start() - _WINDOW), min(len(text), m.end() + _WINDOW)
            win = text[lo:hi]
            if _section_status(win) == "OPEN":
                continue
            place = _PLACE.search(win)
            county_m = _COUNTY.search(win)
            place_name = place.group(1).strip() if place else ""
            county = (place.group(2).strip() + " Co") if place else (
                county_m.group(1).strip() + " Co" if county_m else "")
            item = {
                "status": _section_status(win),
                "place": place_name,
                "county": county,
                "where": (f"{place_name} ({county})" if place_name and county else
                          place_name or county or f"the {s['region'].title()} area"),
                "text": _sentence(win),
                "region": s["region"],
            }
            if any(k in win.upper() for k in keywords):
                on_corridor.append(item)
            elif not any(x["text"] == item["text"] for x in elsewhere):
                elsewhere.append(item)
    # dedupe corridor items the same way
    seen, uniq = set(), []
    for it in on_corridor:
        if it["text"] not in seen:
            seen.add(it["text"])
            uniq.append(it)
    return {
        "on_pass": _worst([i["status"] for i in uniq]),
        "on_pass_reported": bool(uniq),
        "on_pass_items": uniq,
        "elsewhere": elsewhere[:4],
    }


def _sentence(win: str, limit: int = 220) -> str:
    """The status clause from a window, trimmed to readable words."""
    t = " ".join(win.split())
    m = _PLACE.search(t)
    if m:
        t = t[max(0, m.start() - 90):]
    t = t.strip(" -.·")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "..."
    return t


# light typo/spacing cleanup of Caltrans' text (facts unchanged)
_TYPO_FIXES = [
    (r"\beastbund\b", "eastbound"),
    (r"\bI\s+(\d+)\b", r"I-\1"),
    (r"\bSR\s+(\d+)\b", r"SR-\1"),
    (r"\bUS\s+(\d+)\b", r"US-\1"),
    (r"\bCA\s+(\d+)\b", r"CA-\1"),
    (r"\s+", " "),
]


def _clean(t: str) -> str:
    for pat, rep in _TYPO_FIXES:
        t = re.sub(pat, rep, t, flags=re.I)
    return t.strip()


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
