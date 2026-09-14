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
# out meta; → each node carries its real OSM timestamp (creation for most
# surveillance nodes, which are mapped once and never edited).
QUERY = ('[out:json];node["man_made"="surveillance"]["surveillance:type"="ALPR"]'
         "(35.20,-119.25,35.55,-118.80);out meta;")


def run(ctx, *, record_change: bool = False):
    """record_change=True on the weekly job → append a change-log entry."""
    try:
        r = common.fetch(OVERPASS, method="POST", data={"data": QUERY}, timeout=90)
        elements = r.json().get("elements", [])
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
                "mapped": (e.get("timestamp") or "")[:10],  # OSM edit date (≈ creation)
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
            common.append_change_log("alpr", {
                "date": common.iso_today(),
                "total": len(cameras),
                "new_ids": new_ids,
                "gone_ids": gone_ids,
                "new_count": len(new_ids),
            })
            # ONLY advance the snapshot when recording the weekly change log.
            # If every build saved it, CI's 3-hourly builds would silently
            # advance it and the weekly diff would always read 0 new.
            common.save_snapshot("alpr_nodes", sorted(cur_ids))
        return {"ok": True, "cameras": cameras, "stats": stats,
                "change_log": common.load_change_log("alpr"), "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
