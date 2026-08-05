#!/usr/bin/env python3
"""CAL FIRE incidents — active wildfires (verified endpoint, Aug 2026).

incidents.fire.ca.gov is the public site; its structured data endpoint is
https://www.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false
(200, application/json, includes a county field). We keep incidents whose
county text mentions Kern for the Conditions block, and expose the rest for
context. Fail-soft: any error → {"ok": False} and the Conditions chip says
so; the site never breaks.
"""
from __future__ import annotations

from .. import common

URL = "https://www.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false"


def run(ctx):
    try:
        r = common.fetch(URL, timeout=30)
        data = r.json() if isinstance(r.json(), list) else []
        incidents = []
        for i in data:
            county = str(i.get("county") or "")
            incidents.append({
                "name": i.get("name") or "Unnamed incident",
                "county": county,
                "acres": i.get("acresBurned"),
                "contained": i.get("percentContained"),
                "url": i.get("url") or f"https://www.fire.ca.gov/incidents/{i.get('slug') or ''}",
            })
        kern = [i for i in incidents if "Kern" in i["county"]]
        return {"ok": True, "incidents": incidents, "kern": kern,
                "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
