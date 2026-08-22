#!/usr/bin/env python3
"""MailerLite API helpers for the Bakersfield Brief newsletter.

Adds a subscriber to the configured MailerLite group via the REST API
(Bearer token). Used by the site's subscribe form handler (via build) and
the daily send script.

Env:
  MAILERLITE_API_TOKEN  (required to add subscribers)
  MAILERLITE_GROUP_ID   (optional; default group used when omitted)

Endpoint: https://connect.mailerlite.com/api/subscribers
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

API = "https://connect.mailerlite.com/api/subscribers"


def get_token() -> str:
    tok = os.environ.get("MAILERLITE_API_TOKEN", "").strip()
    if not tok:
        raise SystemExit("MAILERLITE_API_TOKEN not set")
    return tok


def add_subscriber(email: str, group_id: str = "") -> dict:
    """Add a subscriber. Returns the created/updated subscriber dict.
    Raises on API error (HTTPError propagates with the response body)."""
    tok = get_token()
    body = {"email": email}
    gid = group_id or os.environ.get("MAILERLITE_GROUP_ID", "").strip()
    if gid:
        body["groups"] = [gid]
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    sub = data.get("data") or {}
    if not sub.get("id"):
        raise RuntimeError(f"MailerLite returned no subscriber id: {data}")
    return sub
