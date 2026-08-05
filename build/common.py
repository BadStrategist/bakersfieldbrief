#!/usr/bin/env python3
"""Shared helpers for the Bakersfield Daily Brief build.

Every module in build/sources and build/builders imports from here.
All paths are derived from this file's location, so the build runs from
any cwd on any OS (Windows dev box, GitHub Actions Ubuntu runner).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent          # repo root
BUILD = ROOT / "build"
DATA = ROOT / "data"                                   # snapshots + diff state (committed)
SNAP = DATA / "snapshots"                              # per-source JSON snapshots
LOGS = DATA / "change_logs"                            # tracker weekly change logs
DRAFTS = ROOT / "drafts"                               # review-only recaps (never deployed)
SITE = ROOT / "site"                                   # built static output (deployed)
ASSETS = ROOT / "assets"                               # static assets copied into site
TEMPLATES = ROOT / "templates"
SCRIPTS = ROOT / "scripts"

PACIFIC = ZoneInfo("America/Los_Angeles")
UA = ("BakersfieldDailyBrief/1.0 (+https://bakersfieldbrief.com; "
      "static news site; contact: editor@bakersfieldbrief.com)")
PLACEHOLDER = "/*__DATA__*/null"                       # JSON inline placeholder

for _d in (DATA, SNAP, LOGS, DRAFTS, SITE):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- .env loader
# Load KEY=VALUE lines from repo-root .env (stdlib only) so local builds see
# the same secrets the GitHub workflow passes via env. Never commit .env.
_ENV_PATH = ROOT / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


# ---------------------------------------------------------------- time
def now_pacific() -> dt.datetime:
    return dt.datetime.now(PACIFIC)


def today_pacific() -> dt.date:
    return now_pacific().date()


def pacific_hour() -> int:
    return now_pacific().hour


def iso_today() -> str:
    return today_pacific().isoformat()


# ---------------------------------------------------------------- http
def fetch(url: str, *, timeout: int = 30, retries: int = 2, method: str = "GET",
          headers: dict | None = None, **kwargs) -> requests.Response:
    """GET/POST with a polite UA, timeout and 2 retries. Raises on failure."""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, timeout=timeout, headers=h, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - any failure → retry
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


# ---------------------------------------------------------------- snapshots
def load_snapshot(name: str, default=None):
    """Load a JSON snapshot from data/snapshots/<name>.json."""
    p = SNAP / f"{name}.json"
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_snapshot(name: str, obj) -> Path:
    p = SNAP / f"{name}.json"
    p.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    return p


def load_change_log(tracker: str) -> list:
    p = LOGS / f"{tracker}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_change_log(tracker: str, entry: dict) -> None:
    log = load_change_log(tracker)
    log.append(entry)
    (LOGS / f"{tracker}.json").write_text(
        json.dumps(log, indent=1, default=str), encoding="utf-8")


# ---------------------------------------------------------------- template render
def inline_placeholder(html: str, data) -> str:
    """Replace the JS-visible placeholder with real JSON.

    The placeholder must appear exactly once; it lives inside a
    <script type="application/json"> block so the browser never executes it
    (XSS-safe: we control all content, but defense in depth).
    """
    dumped = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    n = html.count(PLACEHOLDER)
    if n == 0:
        raise ValueError("placeholder /*__DATA__*/null not found in template")
    if n > 1:
        raise ValueError("placeholder appears more than once in template")
    return html.replace(PLACEHOLDER, dumped)


def read_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- misc
def esc(s) -> str:
    """HTML-escape a value for safe inline rendering."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
                 .replace('"', "&quot;").replace("'", "&#39;")


def rel_path(from_dir: str, to_path: str) -> str:
    """Relative href from a page directory (repo-relative, no leading /) to a file."""
    src = (SITE / from_dir).resolve() if from_dir else SITE.resolve()
    dst = (SITE / to_path).resolve()
    try:
        return os.path.relpath(dst, src).replace("\\", "/")
    except ValueError:  # different drives (shouldn't happen; same tree)
        return to_path


def safe_filename(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen] or "untitled"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def log(msg: str) -> None:
    print(f"[build] {dt.datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)
