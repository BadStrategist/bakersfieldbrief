#!/usr/bin/env python3
"""Stubs for sources blocked from datacenter IPs (GitHub-hosted runners
included) or not yet built. Each returns ok=False with a clear reason so the
build report shows them as "stubbed" without breaking anything.

Blocked (verified Aug 2026): Kern County Granicus portal (403 on datacenter
IPs), kernpublichealth.com, BoardDocs, Bakersfield PD's website, Flock
transparency portals.

Not-yet-built: DBA filings (Kern Clerk), building permits (Kern
Development Services), school-board agendas (KHSD/BCSD), AQI.

Architecture note: these are *isolated* modules — to move a real source to a
self-hosted runner later (Raspberry Pi at home), replace the stub body with a
real fetch; the workflow already supports a SELF_HOSTED_RUNNER opt-in (see
.github/workflows), so no restructuring is needed.
"""
from __future__ import annotations

STUBS = {
    "granicus": "Kern County Granicus portal 403s datacenter IPs — replace with the stable boardagenda.pdf source (build/sources/kern_board.py) or run on a self-hosted runner.",
    "kern_public_health": "kernpublichealth.com blocks datacenter IPs — self-hosted runner needed.",
    "boarddocs": "BoardDocs blocks datacenter IPs — self-hosted runner needed.",
    "bpd": "Bakersfield PD website blocks datacenter IPs — self-hosted runner needed.",
    "flock_portals": "Flock Safety transparency portals block datacenter IPs — self-hosted runner needed.",
    "dba_filings": "Not built yet — Kern County Clerk DBA filings (future 'Openings & Closings' source).",
    "building_permits": "Not built yet — Kern Development Services building permits (future source).",
    "school_boards": "Not built yet — KHSD / BCSD / KHSD agenda feeds (future City Hall section).",
    "aqi": "Placeholder only — EPA AirNow/PurpleAir need an API key; AQI card shows 'not yet available'.",
}


def run(ctx):
    return {"ok": False, "stubs": STUBS, "error": "stubbed sources (blocked or not built) — see data/sources/blocked.py",
            "asof": common_iso()}


def common_iso() -> str:
    from .. import common
    return common.iso_today()
