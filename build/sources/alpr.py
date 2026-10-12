#!/usr/bin/env python3
"""ALPR cameras — OpenStreetMap via Overpass API. Free, no key.

Query: node["man_made"="surveillance"]["surveillance:type"="ALPR"] inside the Kern County
boundary (455 nodes on 2026-10-12, 416 of them Flock Safety).

Until 2026-10-12 the query was the box 35.20,-119.25,35.55,-118.80, the Bakersfield metro, under
a heading that said Kern County. Measured that day: 270 in the box, 455 in the county. The 185
the box left out were Delano 31, McFarland 25, Shafter 20, Wasco 10, Ridgecrest 34, Mojave,
Rosamond and California City 17, Tehachapi 15, Taft and Maricopa 13, the Grapevine 10.

The tag filter is right as it is. Every node in the county tagged surveillance:type=ALPR is a
man_made=surveillance node, and no other surveillance node mentions a plate reader in any tag.
Do not add manufacturer~Flock: the 68 Flock nodes it would bring in are all Condor video domes
(surveillance:type=camera, camera:type=dome), which read no plates.

License: © OpenStreetMap contributors, ODbL. See site attribution.

Weekly change log: node IDs diffed against the previous snapshot
(data/snapshots/alpr_nodes.json) — "N newly mapped this week".
"""
from __future__ import annotations

import collections
import datetime as dt

from .. import common

OVERPASS = "https://overpass-api.de/api/interpreter"
# The two servers behind overpass-api.de, asked directly when the front door refuses. Measured
# 2026-10-12 with the budget below (and a plain `out;`), from this box and from a GitHub
# runner: lambert 11 of 12 (the miss was a 429 on the probe's own IP), gall 12 of 12. The third-party mirrors are not
# here because none of them works: tested from a runner on 2026-10-05, overpass.private.coffee
# and overpass.kumi.systems timed out at 60 s, maps.mail.ru answered 504, overpass.osm.jp
# failed TLS. When all three refuse, the last good camera list below is the fallback, and the
# next build (three hours later) tries again.
BACKENDS = ("https://lambert.openstreetmap.de/api/interpreter",
            "https://gall.openstreetmap.de/api/interpreter")
# [timeout:25][maxsize:32 MB] is the fix for the 504s of 2026-10-10 to 2026-10-12. A query that
# declares no budget asks for the defaults (180 s, 512 MB), and a loaded server turns that
# away at the door: "Dispatcher_Client::request_read_and_idx::timeout. The server is probably
# too busy to handle your request." Alternated in the same minutes on 2026-10-12, the
# unbudgeted query got through 4 times in 26 and this one every time it was not rate limited.
# The whole reply is about 225 KB.
# out meta; → each node carries its real OSM timestamp (creation for most
# surveillance nodes, which are mapped once and never edited).
#
# The area is Kern County's own boundary, OSM relation 396494 (Overpass addresses a relation as
# an area at 3600000000 + its id). By id, not by name: a renamed relation still answers. A box
# cannot stand in for it: the box that holds the county (34.78,-120.30,35.85,-117.55) also holds
# 6 cameras in Tulare and Los Angeles counties.
KERN_AREA = 3600396494
QUERY = ('[out:json][timeout:25][maxsize:33554432];'
         'node["man_made"="surveillance"]["surveillance:type"="ALPR"]'
         f"(area:{KERN_AREA});out meta;")
# What the camera list covers. Every change-log row carries it, and a row written under another
# scope makes the next weekly run a re-baseline (see _weekly_row).
SCOPE = "kern-county"
OLD_SCOPE = "bakersfield-metro"   # rows before 2026-10-12 carry no scope: they are this one
# The box the query used to be. It is the "Bakersfield" in the page's own questions ("How many
# Flock cameras are in Bakersfield?"), so the answer can still be about Bakersfield.
METRO_BOX = (35.20, -119.25, 35.55, -118.80)
# A 0.2 degree cell (about 22 km by 18 km) that held this many cameras and now holds none is a
# part of the county missing from the reply, not mappers at work.
CELL_MIN = 5


def in_metro(c: dict) -> bool:
    lat, lon = c.get("lat"), c.get("lon")
    return (lat is not None and lon is not None
            and METRO_BOX[0] <= lat <= METRO_BOX[2] and METRO_BOX[1] <= lon <= METRO_BOX[3])


def metro_counts(cameras: list) -> tuple[int, int]:
    """(cameras, Flock cameras) inside the Bakersfield metro box, from the same list as the total."""
    metro = [c for c in cameras if in_metro(c)]
    return len(metro), sum(1 for c in metro if "flock" in (c.get("manufacturer") or "").lower())


def _cells(points: list) -> collections.Counter:
    return collections.Counter((round(p["lat"] * 5), round(p["lon"] * 5)) for p in points
                               if p.get("lat") is not None and p.get("lon") is not None)


def _lost_cells(elements: list) -> list[str]:
    """Parts of the last good list that the new reply has no camera in at all."""
    last = (common.load_snapshot("alpr_last", default={}) or {})
    before = _cells(last.get("cameras") or []) if isinstance(last, dict) else {}
    now = _cells(elements)
    return [f"{n} near {la / 5:.1f},{lo / 5:.1f}" for (la, lo), n in sorted(before.items())
            if n >= CELL_MIN and not now.get((la, lo))]


def _weekly_row(cameras: list, new_ids: list, gone_ids: list) -> dict:
    """This week's change-log row.

    "New" is the diff against last Monday's snapshot. That only means "newly mapped" while both
    lists cover the same ground. When the last row was written under another scope, the diff is
    mostly cameras the old query never asked for, so that one week a camera is new only if it was
    first mapped on or after the last row's date. The rest go on the row as "widened": a count
    of cameras the wider map brought in, never as new ones.
    """
    row = {"date": common.iso_today(), "total": len(cameras), "new_ids": new_ids,
           "gone_ids": gone_ids, "new_count": len(new_ids), "scope": SCOPE}
    log = common.load_change_log("alpr")
    if log and (log[-1].get("scope") or OLD_SCOPE) != SCOPE:
        since = str(log[-1].get("date") or "")[:10]
        mapped = {c["id"]: c["mapped"] for c in cameras}
        new = [i for i in new_ids if since and mapped.get(i, "") >= since]
        row.update(new_ids=new, new_count=len(new), widened=len(new_ids) - len(new))
    return row


def _fetch_elements() -> list:
    """The camera nodes from the first Overpass server that gives a whole answer."""
    errors = []
    for i, url in enumerate((OVERPASS, *BACKENDS)):
        try:
            # backoff=20: retries at 20 s and 40 s. The default (1.5 s, 3 s) gave a busy
            # Overpass under five seconds to recover, and its 504 on 2026-10-10 turned a deploy
            # red that a retry a minute later passed. The backends get one try each.
            if i == 0:
                r = common.fetch(url, method="POST", data={"data": QUERY}, timeout=90, backoff=20)
            else:
                r = common.fetch(url, method="POST", data={"data": QUERY}, timeout=60, retries=0)
            j = r.json()
            # Overpass answers a timeout or memory error with HTTP 200, a "remark" and an empty
            # or partial element list. Taken at face value that is "0 cameras", and on the weekly
            # run it would log every camera as gone. Treat it as the failure it is.
            remark = str(j.get("remark") or "")
            if remark and ("error" in remark.lower() or "timed out" in remark.lower()):
                raise RuntimeError(f"Overpass remark: {remark[:160]}")
            if errors:
                common.log(f"alpr: answered by {url.split('/')[2]} after {'; '.join(errors)[:200]}")
            return j.get("elements", [])
        except Exception as e:  # noqa: BLE001 - the next server is the retry
            errors.append(f"{url.split('/')[2]}: {type(e).__name__}: {e}")
    raise RuntimeError("; ".join(errors))


def run(ctx, *, record_change: bool = False):
    """record_change=True on the weekly job → append a change-log entry."""
    try:
        elements = _fetch_elements()
        prev_n = len(common.load_snapshot("alpr_nodes", default=[]) or [])
        if prev_n >= 50 and len(elements) < prev_n * 0.6:
            raise RuntimeError(f"Overpass returned {len(elements)} nodes, last snapshot had {prev_n}")
        # The count above can hold while a whole town drops out (Ridgecrest is 34 of 455). The
        # page keeps the last good list and the run goes red, the same as any failed fetch.
        lost = _lost_cells(elements)
        if lost:
            raise RuntimeError("Overpass reply has no camera where the last good list had "
                               + "; ".join(lost[:6]))
        first_mapped = _first_mapped(elements)
        cameras = []
        for e in elements:
            t = e.get("tags") or {}
            cameras.append({
                "id": e["id"],
                "lat": e.get("lat"),
                "lon": e.get("lon"),
                "manufacturer": t.get("manufacturer", "Unspecified"),
                "operator": t.get("operator", ""),
                "direction": t.get("direction", ""),      # camera facing, if tagged
                # First-mapped date. `out meta` carries the LAST edit, so a re-tagged old camera
                # used to count as "new" (4 of 15 "new in 4 weeks" on 2026-09-22 were edits).
                "mapped": first_mapped.get(str(e["id"]), ""),
                "edited": (e.get("timestamp") or "")[:10],
                "start_date": t.get("start_date", ""),   # crowdsourced, not authoritative
                "camera_type": t.get("surveillance", ""),
            })
        cameras.sort(key=lambda c: c["id"])

        prev = common.load_snapshot("alpr_nodes", default=[])
        prev_ids = set(prev)
        cur_ids = {c["id"] for c in cameras}
        new_ids = sorted(cur_ids - prev_ids)
        gone_ids = sorted(prev_ids - cur_ids)

        newest = max((c["mapped"] for c in cameras if c["mapped"]), default="")

        # "New this week" = cameras whose live OSM `mapped` date falls inside the
        # rolling 7-day window. This is the ONE number the tracker card badge
        # ("+N NEW THIS WEEK"), the surveillance page and the email sentence all
        # read, so they can never disagree.
        # Do NOT use the snapshot diff (new_ids) here: the snapshot advances on
        # the weekly change-log run, so a diff-based counter reads 0 for every
        # build after it. That shipped as a badge reading "+0" next to the email
        # sentence "5 new cameras mapped this week" (2026-09-14).
        wk_cutoff = ""
        try:
            wk_cutoff = (dt.date.fromisoformat(common.iso_today())
                         - dt.timedelta(days=7)).isoformat()
        except ValueError:  # noqa: BLE001 — never break the build on a bad clock
            wk_cutoff = ""
        new_week = sum(1 for c in cameras
                       if wk_cutoff and (c.get("mapped") or "") >= wk_cutoff)

        stats = {
            "total": len(cameras),
            "flock": sum(1 for c in cameras if "flock" in (c["manufacturer"] or "").lower()),
            "new_this_week": new_week,
            "new_this_week_snapshot_diff": len(new_ids),
            "newest_mapped": newest,
        }

        if record_change:
            # A newly mapped camera with no first-mapped date stops the weekly row. Once the row
            # lands, _first_mapped lets the row's own date stand in for the missing one, and the
            # camera then counts as "new this week" on a date nobody looked up. Raising here
            # takes the fallback path below: no row, the snapshot stays put, the run is red
            # (weekly.yml fails on stale), and a re-run logs these cameras once they can be
            # dated. On a daily build the same gap is a warning from check_alpr_fresh.py.
            fresh = set(new_ids)
            undated = [c["id"] for c in cameras if c["id"] in fresh and not c["mapped"]]
            if undated:
                raise RuntimeError(
                    f"{len(undated)} newly mapped camera(s) could not be dated after the OSM "
                    f"history lookups, so the weekly row was not written: nodes "
                    + ", ".join(str(i) for i in undated[:10]))
            recorded = common.append_change_log("alpr", _weekly_row(cameras, new_ids, gone_ids))
            # Advance the snapshot ONLY when the row actually landed.
            # If every build saved it, CI's 3-hourly builds would silently
            # advance it and the weekly diff would always read 0 new. And if the
            # append was refused (this date is already logged, e.g. a manual
            # dispatch after the Monday cron), advancing anyway swallows the
            # cameras mapped since: the run that would have reported them never
            # happens again.
            if recorded:
                common.save_snapshot("alpr_nodes", sorted(cur_ids))
        # last good payload: the fallback when Overpass can't be reached (see below)
        common.save_snapshot("alpr_last", {"cameras": cameras, "stats": stats,
                                           "asof": common.iso_today()})
        # "stale" is written on BOTH paths. scripts/check_alpr_fresh.py passes a run only on an
        # explicit False, so a payload that lost the flag reads as a failure, never as fresh.
        return {"ok": True, "stale": False, "cameras": cameras, "stats": stats,
                "change_log": common.load_change_log("alpr"), "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        # Overpass unreachable from CI for a few minutes (2026-09-22 evening) rebuilt
        # /surveillance/, the site's top search page, with zero cameras. Serve the last good list
        # instead, stamped with ITS date so "Data as of" stays true, and flagged stale.
        # ok stays True so every surface keeps rendering the cameras; it does NOT mean the run
        # is healthy. The stale flag is for CI only: the build log and the freshness check
        # (scripts/check_alpr_fresh.py) read it, and that check fails the run and alerts a
        # human the same day. No page, card or email reads it, and none may.
        err = f"{type(e).__name__}: {e}"
        last = common.load_snapshot("alpr_last", default={}) or {}
        if last.get("cameras"):
            common.log(f"alpr: run failed ({err[:200]}); serving last good list from {last.get('asof')}")
            return {"ok": True, "stale": True, "error": err, "cameras": last["cameras"],
                    "stats": last.get("stats", {}), "change_log": common.load_change_log("alpr"),
                    "asof": last.get("asof", "")}
        return {"ok": False, "error": err}


OSM_V1 = "https://api.openstreetmap.org/api/0.6/node/{id}/1.json"
MAX_LOOKUPS = 60   # per build; the answers are cached for good, so this only bites once


def _first_mapped(elements: list) -> dict:
    """node id -> date the node was first mapped (its version 1).

    A version-1 node's own timestamp is its creation. An edited node's creation date comes from
    the OSM history API once, then lives in data/snapshots/alpr_created.json. If a lookup fails,
    the week the change log first saw the node stands in; failing that the date stays unknown
    ("") rather than falling back to the edit date, and the lookup is retried next build.
    """
    created = common.load_snapshot("alpr_created", default={}) or {}
    if not isinstance(created, dict):   # a damaged snapshot must not take the whole source down
        created = {}
    seen_week = {}
    for entry in common.load_change_log("alpr"):
        for nid in entry.get("new_ids", []) or []:
            seen_week.setdefault(str(nid), str(entry.get("date", ""))[:10])
    out, changed, lookups = {}, False, 0
    for e in elements:
        key = str(e.get("id"))
        if key in created:
            out[key] = created[key]
            continue
        if int(e.get("version") or 1) <= 1:
            created[key] = out[key] = (e.get("timestamp") or "")[:10]
            changed = True
            continue
        date = ""
        if lookups < MAX_LOOKUPS:
            lookups += 1
            try:
                r = common.fetch(OSM_V1.format(id=key), timeout=15, retries=1)
                el = (r.json().get("elements") or [{}])[0]
                date = (el.get("timestamp") or "")[:10]
            except Exception:  # noqa: BLE001 - retried on the next build
                date = ""
        if date:
            created[key] = date
            changed = True
        out[key] = date or seen_week.get(key, "")
    if changed:
        common.save_snapshot("alpr_created", created)
    return out
