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
    # SR-126 (Castaic) to the Los Angeles/Kern county line is the south side of the Grapevine:
    # a wind advisory worded that way was read as "not on the pass" while the live check flagged it.
    "i5": ("TEJON", "LEBEC", "GORMAN", "GRAPEVINE", "FORT TEJON", "CASTAIC",
           "PYRAMID LAKE", "SR-138", "SMOKEY BEAR", "SR-126", "SR 126", "KERN CO LINE"),
    "sr58": ("TEHACHAPI", "KEENE", "MONOLITH", "BEALVILLE", "CALIENTE",
             "SR-202", "TOWER LINE", "WOODFORD", "TWIN OAKS"),
    "sr99": ("BAKERSFIELD", "DELANO", "WASCO", "MCFARLAND", "SHAFTER",
             "LAMONT", "KERN CO"),
}

# Counties each corridor runs through. An item that names another county is never "on the
# pass", even when its text window runs into a corridor keyword from the next item (an Irvine,
# Orange Co closure sat right before a "SR-126 to the Kern Co line" wind advisory).
CORRIDOR_COUNTIES = {
    "i5": ("KERN", "LOS ANGELES"),
    "sr58": ("KERN",),
    "sr99": ("KERN", "TULARE"),
}

# a problem phrase: the anchor we scope to a place
_PROBLEM = re.compile(
    r"\bis\s+closed\b|\bare\s+closed\b|will be closed|is currently closed|"
    r"\bclosed\b|\brestrictions?\b|chains|reduced to \d lane|one lane|"
    r"two lanes closed|wind advisory|\bwind\b|\bfog\b|snow|traffic hazard|"
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
            out["log"] = _load_log()
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
    # The log follows the Kern corridor, not the whole route. It used to follow the statewide
    # rollup while naming the row "Grapevine (Tejon Pass)", so a closure in Orange County was
    # logged as the Grapevine closing.
    snap = common.load_snapshot("roads", default={})
    log = _load_log()
    now = common.now_pacific()
    for rte in fresh_routes:
        prev = snap.get(rte["slug"], {})
        status, chash = corridor_state(rte)
        entry = {
            "ts": now.date().isoformat(),
            "time": now.strftime("%I:%M %p").lstrip("0"),
            "route": rte["slug"],
            "route_name": CORRIDOR_NAME.get(rte["slug"], rte["name"]),
            "scope": "corridor",
            "to": status,
        }
        # A snapshot from before corridor scoping has no baseline to compare with: record the
        # baseline now and log from the next change on, rather than invent a change.
        if "corridor" not in prev:
            continue
        if prev["corridor"] != status:
            log.insert(0, dict(entry, **{"from": prev["corridor"]}))
        elif prev.get("corridor_hash") != chash:
            log.insert(0, dict(entry, **{"from": "updated", "note": "condition text changed"}))
    log = log[:60]
    common.save_snapshot("roads_log", log)
    for x in fresh_routes:
        status, chash = corridor_state(x)
        snap[x["slug"]] = {"status": x["status"], "hash": x["hash"],
                           "corridor": status, "corridor_hash": chash}
    common.save_snapshot("roads", snap)
    # full last-known payload so a later failed fetch can degrade gracefully
    common.save_snapshot("roads_last", out)
    out["log"] = log
    return out


# ---------------------------------------------------------------- change log
CORRIDOR_NAME = {
    "i5": "I-5 Grapevine (Tejon Pass)",
    "sr58": "SR-58 Tehachapi Pass",
    "sr99": "SR-99 in Kern County",
}
# What the entries written before corridor scoping actually measured.
STATEWIDE_NAME = {
    "i5": "I-5, anywhere in California",
    "sr58": "SR-58, whole route",
    "sr99": "SR-99, whole route",
}


def corridor_state(rte: dict) -> tuple[str, str]:
    """(status, text hash) of the Caltrans items that sit on the Kern corridor.

    No item naming the corridor is Caltrans' way of saying nothing is wrong there, so that
    reads OPEN and hashes the empty string: advisories elsewhere on the route change neither.
    """
    scope = rte.get("scope") or {}
    items = scope.get("on_pass_items") or []
    status = scope.get("on_pass", "OPEN") if scope.get("on_pass_reported") else "OPEN"
    text = " | ".join(i.get("text", "") for i in items)
    return status, hashlib.md5(text.encode()).hexdigest()[:10]


def _load_log() -> list:
    """The change log, with pre-scoping entries relabelled as the statewide readings they were."""
    log = common.load_snapshot("roads_log", default=[])
    for e in log:
        if "scope" not in e:
            e["scope"] = "statewide"
            e["route_name"] = STATEWIDE_NAME.get(e.get("route"), e.get("route_name", ""))
    return log


def log_when(e: dict) -> str:
    """'2026-10-05 6:33 PM' (entries from before 2026-10-05 carry a date only)."""
    return f"{e.get('ts', '')} {e.get('time', '')}".strip()


def log_note(log: list) -> str:
    """One line under a change-log table while it still shows statewide entries."""
    if not any(e.get("scope") == "statewide" for e in log[:12]):
        return ""
    return ('<p class="note">Rows marked &ldquo;anywhere in California&rdquo; or &ldquo;whole '
            'route&rdquo; were logged before October 5, 2026, when this log covered the entire '
            'highway. They do not mean the pass itself was closed.</p>')


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
        # Judge each Caltrans item on its own text. A fixed character window around a problem
        # word ran into the neighbouring item: an Irvine closure borrowed the next item's SR-126,
        # and the SR-126 wind advisory borrowed the Irvine item's "(Orange Co)".
        for win in _items(s["text"]):
            if not _PROBLEM.search(win) or _section_status(win) == "OPEN":
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
            other_county = bool(county) and not any(
                c in county.upper() for c in CORRIDOR_COUNTIES.get(slug, ()))
            if any(k in win.upper() for k in keywords) and not other_county:
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


_ITEM_START = re.compile(
    r"(?<=[a-z0-9)])\s+(?=(?:The|A|An|Northbound|Southbound|Eastbound|Westbound|Both|All|"
    r"Traffic|Chain|Chains|There|One|Two)\b)")


def _items(text: str) -> list[str]:
    """Split one area's text into separate Caltrans items. Caltrans runs items together with no
    separator; a new item starts with a capitalised word right after the previous one ends.
    Clauses inside an item follow " - " and are never split."""
    return [t.strip() for t in _ITEM_START.split(text or "") if t.strip()]


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
