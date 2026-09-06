#!/usr/bin/env python3
"""Post a message to a Discord channel webhook.

Used by the daily CI (blocked/failed email alert) and the email watchdog so
both surface a degraded email to the ops Discord channel the same morning.
Pure stdlib (urllib), so it runs under the repo venv or Hermes's python.

Webhook URL resolution (first non-empty wins):
  1. --webhook <url>
  2. env DISCORD_WEBHOOK_URL
  3. DISCORD_WEBHOOK_URL= in <LOCALAPPDATA>/hermes/.env

Message: --header <line> is prepended bold, then the body comes from
--file <path> (default '-' reads stdin).

Exit 0 on success; 1 on any failure (missing webhook, unreadable file, HTTP
error). CI and the watchdog treat a non-zero exit as a loud signal, never a
silent skip.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def _webhook_from_env_files() -> str:
    env = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--webhook", default="", help="Discord webhook URL")
    ap.add_argument("--header", default="", help="Bold header line")
    ap.add_argument("--file", default="-", help="Message body file (default: stdin)")
    args = ap.parse_args()

    webhook = (args.webhook or os.environ.get("DISCORD_WEBHOOK_URL", "")
               or _webhook_from_env_files())
    if not webhook:
        print("notify_discord: no DISCORD_WEBHOOK_URL (env, --webhook, or hermes .env)",
              file=sys.stderr)
        return 1

    if args.file == "-":
        body = sys.stdin.read()
    else:
        try:
            body = Path(args.file).read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"notify_discord: cannot read {args.file}: {e}", file=sys.stderr)
            return 1

    text = (f"**{args.header}**\n{body}" if args.header else body)
    payload = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "BakersfieldBrief/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except Exception as e:  # noqa: BLE001
        print(f"notify_discord: POST failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
