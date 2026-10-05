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

import json
from pathlib import Path

from .. import common

# incidents.fire.ca.gov is where the API lives now; www.fire.ca.gov only redirects to it.
URL = "https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false"

SNAPSHOT = Path(__file__).resolve().parent.parent.parent / "data" / "snapshots" / "calfire.json"


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
                "lat": _g(i, "Latitude", "latitude"),
                "lon": _g(i, "Longitude", "longitude"),
                "started": _g(i, "StartedDateOnly", "Started", "StartedDate"),
                "location": _g(i, "Location", "location"),
                "type": _g(i, "Type", "type"),
                "url": _g(i, "url", "Url", "URL")
                       or f"https://www.fire.ca.gov/incidents/{_g(i, 'slug', 'Slug') or ''}",
            })
        kern = [i for i in incidents if "Kern" in i["county"]]
        result = {"ok": True, "incidents": incidents, "kern": kern,
                  "asof": common.iso_today()}
        # Persist a last-known-good snapshot so a later outage can render the
        # last-known state + its asof instead of a fabricated empty/zero.
        try:
            SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT.write_text(json.dumps(result, ensure_ascii=False),
                                encoding="utf-8")
        except Exception:  # noqa: BLE001 — never fail the build on snapshot write
            pass
        return result
    except Exception as e:  # noqa: BLE001
        # On failure, try to fall back to the last-known-good snapshot so the
        # failure branch can show real last-known data + asof, not a fabricated 0.
        last = None
        try:
            if SNAPSHOT.exists():
                last = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            last = None
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "last": last}
