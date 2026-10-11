#!/usr/bin/env python3
"""ALPR cameras — OpenStreetMap via Overpass API. Free, no key.

Query: node["man_made"="surveillance"]["surveillance:type"="ALPR"]
bbox 35.20,-119.25,35.55,-118.80  (~246 nodes Aug 2026; mostly Flock Safety).

License: © OpenStreetMap contributors, ODbL. See site attribution.

Weekly change log: node IDs diffed against the previous snapshot
(data/snapshots/alpr_nodes.json) — "N newly mapped this week".
"""
from __future__ import annotations

import datetime as dt

from .. import common

OVERPASS = "https://overpass-api.de/api/interpreter"
# There is no working mirror to fall back to. Tested from a GitHub runner on 2026-10-05 with
# this exact query: overpass.private.coffee and overpass.kumi.systems timed out at 60 s,
# maps.mail.ru answered 504, overpass.osm.jp failed TLS; this server answered in 2.4 s. When
# it cannot be reached, the last good camera list below is the fallback, and the next build
# (three hours later) tries again.
# out meta; → each node carries its real OSM timestamp (creation for most
# surveillance nodes, which are mapped once and never edited).
QUERY = ('[out:json];node["man_made"="surveillance"]["surveillance:type"="ALPR"]'
         "(35.20,-119.25,35.55,-118.80);out meta;")


def run(ctx, *, record_change: bool = False):
    """record_change=True on the weekly job → append a change-log entry."""
    try:
        # backoff=20: retries at 20 s and 40 s. The default (1.5 s, 3 s) gave a busy
        # Overpass under five seconds to recover, and its 504 on 2026-10-10 turned a deploy
        # red that a retry a minute later passed.
        r = common.fetch(OVERPASS, method="POST", data={"data": QUERY}, timeout=90, backoff=20)
        j = r.json()
        elements = j.get("elements", [])
        # Overpass answers a timeout or memory error with HTTP 200, a "remark" and an empty or
        # partial element list. Taken at face value that is "0 cameras", and on the weekly run it
        # would log every camera as gone. Treat it as the failure it is.
        remark = str(j.get("remark") or "")
        if remark and ("error" in remark.lower() or "timed out" in remark.lower()):
            raise RuntimeError(f"Overpass remark: {remark[:160]}")
        prev_n = len(common.load_snapshot("alpr_nodes", default=[]) or [])
        if prev_n >= 50 and len(elements) < prev_n * 0.6:
            raise RuntimeError(f"Overpass returned {len(elements)} nodes, last snapshot had {prev_n}")
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
            recorded = common.append_change_log("alpr", {
                "date": common.iso_today(),
                "total": len(cameras),
                "new_ids": new_ids,
                "gone_ids": gone_ids,
                "new_count": len(new_ids),
            })
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
            common.log(f"alpr: fetch failed ({err[:120]}); serving last good list from {last.get('asof')}")
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
