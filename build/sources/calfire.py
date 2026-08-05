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


def _g(item: dict, *names):
    """Case-tolerant key lookup — the API uses 'County', 'Name', …; be safe."""
    for n in names:
        v = item.get(n)
        if v not in (None, ""):
            return v
    return ""


def run(ctx):
    try:
        r = common.fetch(URL, timeout=30)
        data = r.json() if isinstance(r.json(), list) else []
        incidents = []
        for i in data:
            county = str(_g(i, "County", "county") or "")
            incidents.append({
                "name": _g(i, "Name", "name") or "Unnamed incident",
                "county": county,
                "acres": _g(i, "acresBurned", "AcresBurned", "Acres"),
                "contained": _g(i, "percentContained", "PercentContained", "Containment"),
                "url": _g(i, "url", "Url", "URL")
                       or f"https://www.fire.ca.gov/incidents/{_g(i, 'slug', 'Slug') or ''}",
            })
        kern = [i for i in incidents if "Kern" in i["county"]]
        return {"ok": True, "incidents": incidents, "kern": kern,
                "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
