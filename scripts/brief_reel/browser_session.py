#!/usr/bin/env python3
"""Launch, keep, or stop the signed-in Chrome session used for UI publishing.

Business Suite publishing needs a REAL signed-in Chrome (the agent profile) with
a CDP port, kept alive for the whole job. Playwright closes the browser when the
launcher exits, which kills every script attached over CDP (TargetClosedError),
so the launcher is a long-lived keeper process.

Edge cannot be used at all: Microsoft blocks --remote-debugging-port, so the port
never opens no matter which profile is given.

Usage
-----
  python browser_session.py start [--hold 7200] [--url URL] [--port 9222]
  python browser_session.py stop
  python browser_session.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROFILE = Path.home() / "AppData" / "Local" / "hermes" / "agent-chrome-profile"


def _cdp_up(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def _cdp_healthy(port: int, timeout_ms: int = 25000) -> bool:
    """A live HTTP port is NOT a usable session.

    A wedged page leaves /json/version answering while the WebSocket handshake
    never completes, so every later connect_over_cdp hangs for minutes. Only a
    real connect plus a real page counts as healthy.
    """
    if not _cdp_up(port):
        return False
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=timeout_ms)
            ctx = b.contexts[0] if b.contexts else b.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.evaluate("1")
        return True
    except Exception:
        return False


def _kill_agent_chrome() -> None:
    """Kill ONLY chrome processes owned by the agent profile (never the user's)."""
    import subprocess

    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*agent-chrome-profile*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=90, check=False)
    except Exception:
        pass
    time.sleep(4)


def cmd_status(port: int) -> int:
    up = _cdp_up(port)
    ok = _cdp_healthy(port) if up else False
    print(f"CDP {port}: {'UP' if up else 'DOWN'} / {'healthy' if ok else 'not usable'}")
    return 0 if ok else 1


def cmd_start(port: int, hold: int, url: str) -> int:
    if _cdp_healthy(port):
        print(f"CDP {port} already up and healthy — reusing the running session")
        return 0
    if _cdp_up(port):
        print(f"CDP {port} up but WEDGED — restarting the agent browser")
        _kill_agent_chrome()
    if not PROFILE.exists():
        print(f"FATAL: agent profile missing: {PROFILE}", file=sys.stderr)
        return 1

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",          # Playwright's bundled chromium may be absent
            headless=False,
            viewport={"width": 1500, "height": 950},
            args=[
                f"--remote-debugging-port={port}",
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        print(f"keeper up: {page.url[:80]} hold={hold}s profile={PROFILE}", flush=True)
        try:
            time.sleep(hold)
        except KeyboardInterrupt:
            pass
        print("keeper hold elapsed, closing browser", flush=True)
        try:
            ctx.close()
        except Exception:
            # The browser is often already gone by now (CDP flap, or something closed
            # it). A dead target is not a keeper failure. Exiting with a traceback
            # and code 1 just makes a normal expiry look like a crash.
            pass
    return 0


def cmd_stop(port: int) -> int:
    if not _cdp_up(port):
        print("CDP already down")
        return 0
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
            ws = json.load(r)["webSocketDebuggerUrl"]
    except Exception as e:  # noqa: BLE001
        print(f"cannot read browser ws url: {e}", file=sys.stderr)
        return 1
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            b = pw.chromium.connect_over_cdp(ws, timeout=30000)
            b.close()
        time.sleep(5)
        if not _cdp_up(port):
            print("browser closed")
            return 0
        print("CDP still up after close — killing the agent-profile browser")
    except Exception as e:  # noqa: BLE001
        print(f"close failed: {e} — killing the agent-profile browser", file=sys.stderr)
    # browser.close() over CDP is not reliable against a Playwright-owned
    # persistent context (the keeper keeps the profile open). Kill ONLY the
    # Chrome processes whose command line names the agent profile.
    _kill_agent_chrome()
    time.sleep(3)
    return 0 if not _cdp_up(port) else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["start", "stop", "status"])
    ap.add_argument("--hold", type=int, default=7200)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--url", default="about:blank")
    a = ap.parse_args(argv[1:])
    if a.action == "start":
        return cmd_start(a.port, a.hold, a.url)
    if a.action == "stop":
        return cmd_stop(a.port)
    return cmd_status(a.port)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
