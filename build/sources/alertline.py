#!/usr/bin/env python3
"""Kern County school delays and closures — KCSOS AlertLine.

Endpoint: https://alertline.kern.org/api/1.0/posted/alerts/today/{key}
(documented at alertline.kern.org/documentation, free developer key, 1,000
requests a day). One row per district or school that posted an alert today:
site_name, description ("2 Hour Fog Delay"), alert_category, severity (delay
hours, or 99 for a closure), additional_info, updated_at.

Reads ALERTLINE_API_KEY from the environment. The key rides in the URL path,
so it is scrubbed from every error string before anything is returned or logged.

The API only ever answers for today, so this module is also the season logger:
each successful run merges today's alerts into data/fog_delays/log.json. That
file is the only record of past fog days — never rewrite or backfill it.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from .. import common

URL = "https://alertline.kern.org/api/1.0/posted/alerts/today/{key}"
LOG_PATH = common.DATA / "fog_delays" / "log.json"
CLOSURE = 99

# alertline.kern.org serves its leaf certificate without the intermediate that
# signed it, so a strict client (requests on a CI runner) cannot build the chain.
# We ship DigiCert's public intermediate and verify against certifi + that file.
# Verification stays on; never switch this to verify=False.
_INTERMEDIATE = Path(__file__).resolve().parent / "certs" / "geotrust_tls_rsa_ca_g1.pem"
_BUNDLE = None


def _ca_bundle() -> str:
    global _BUNDLE
    if _BUNDLE is None:
        import certifi
        roots = Path(certifi.where()).read_text(encoding="utf-8")
        tmp = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False, encoding="utf-8")
        tmp.write(roots + "\n" + _INTERMEDIATE.read_text(encoding="utf-8"))
        tmp.close()
        _BUNDLE = tmp.name
    return _BUNDLE


def normalize(row: dict) -> dict | None:
    """One AlertLine row -> the shape the page and the log use. None if unusable."""
    site = " ".join(str(row.get("site_name") or "").split())
    if not site:
        return None
    try:
        severity = int(row.get("severity") or 0)
    except (TypeError, ValueError):
        severity = 0
    category = " ".join(str(row.get("alert_category") or "").split())
    description = " ".join(str(row.get("description") or "").split())
    info = " ".join(str(row.get("additional_info") or "").split())
    text = f"{category} {description} {info}".lower()
    if severity == CLOSURE or "closure" in f"{category} {description}".lower():
        kind = "closure"
    elif 0 < severity < CLOSURE or "delay" in f"{category} {description}".lower():
        kind = "delay"
    else:
        kind = "other"
    return {
        "site": site,
        "description": description,
        "info": info,
        "category": category,
        "severity": severity,
        "kind": kind,
        "fog": "fog" in text,
        "updated_at": str(row.get("updated_at") or ""),
    }


def load_log() -> dict:
    try:
        log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        if isinstance(log, dict) and isinstance(log.get("days"), dict):
            return log
    except (OSError, ValueError):
        pass
    return {"started": common.today_pacific().isoformat(), "days": {}}


def record(log: dict, day: str, alerts: list) -> bool:
    """Merge today's alerts into the log. Returns True if the log changed.

    A site keeps its most severe alert of the day: districts lift or edit alerts
    later in the morning, and a delay that was posted still happened.
    """
    if not alerts:
        return False
    by_site = {a["site"]: a for a in log["days"].get(day, [])}
    changed = False
    for a in alerts:
        old = by_site.get(a["site"])
        if old is None or a["severity"] > old.get("severity", 0):
            by_site[a["site"]] = a
            changed = True
    if changed:
        log["days"][day] = sorted(by_site.values(), key=lambda a: a["site"])
    return changed


def save_log(log: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def run(ctx):
    log = load_log()
    key = os.environ.get("ALERTLINE_API_KEY", "").strip()
    if not key:
        return {"ok": False, "needs_key": True, "log": log,
                "error": "ALERTLINE_API_KEY not set (free key at alertline.kern.org/thirdparty)"}
    try:
        r = common.fetch(URL.format(key=key), timeout=20, verify=_ca_bundle())
        try:
            rows = r.json()
        except ValueError:
            # The daily request limit answers 200 with a plain-text notice.
            return {"ok": False, "log": log,
                    "error": "AlertLine answered without JSON: " + _scrub(r.text[:120], key)}
        if not isinstance(rows, list):
            return {"ok": False, "log": log, "error": "AlertLine payload is not a list"}
        alerts = [a for a in (normalize(x) for x in rows if isinstance(x, dict)) if a]
        alerts.sort(key=lambda a: (-a["severity"], a["site"]))
        now = common.now_pacific()
        if record(log, now.date().isoformat(), alerts):
            save_log(log)
        return {"ok": True, "alerts": alerts, "count": len(alerts), "log": log,
                "fetched_at": now.strftime("%Y-%m-%d %H:%M"), "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "log": log, "error": _scrub(f"{type(e).__name__}: {e}", key)}


def _scrub(text: str, key: str) -> str:
    text = text.replace(key, "***") if key else text
    return re.sub(r"(alerts/today/)[^\s'\"/)]+", r"\1***", text)
