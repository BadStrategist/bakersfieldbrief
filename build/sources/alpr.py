#!/usr/bin/env python3
"""ALPR cameras — OpenStreetMap via Overpass API. Free, no key.

Query: node["man_made"="surveillance"]["surveillance:type"="ALPR"]
bbox 35.20,-119.25,35.55,-118.80  (~246 nodes Aug 2026; mostly Flock Safety).

License: © OpenStreetMap contributors, ODbL. See site attribution.

Weekly change log: node IDs diffed against the previous snapshot
(data/snapshots/alpr_nodes.json) — "N newly mapped this week".
"""
from __future__ import annotations

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
        stats = {
            "total": len(cameras),
            "flock": sum(1 for c in cameras if "flock" in (c["manufacturer"] or "").lower()),
            "new_this_week": len(new_ids),
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

        common.save_snapshot("alpr_nodes", sorted(cur_ids))
        return {"ok": True, "cameras": cameras, "stats": stats,
                "change_log": common.load_change_log("alpr"), "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
