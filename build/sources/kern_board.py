#!/usr/bin/env python3
"""Kern County Board of Supervisors agenda — stable PDF at itsapps.kerncounty.com.

NOT the Granicus portal (403s datacenter IPs). Text extracts cleanly with
pdfplumber. We capture: meeting date, top-level agenda sections, and numbered
items for "What to Watch" previews + the Flock/ALPR keyword watch.
"""
from __future__ import annotations

import io
import re

import pdfplumber

from .. import common

PDF_URL = "https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf"
WATCH_WORDS = ("flock", "alpr", "license plate reader", "automated license", "surveillance")


def run(ctx):
    try:
        r = common.fetch(PDF_URL, timeout=60)
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        full = "\n".join(pages)

        date_line = _meeting_date(full)
        items = _numbered_items(full)
        sections = _sections(full)
        watched = [i for i in items if _watch_hit(i)]

        return {"ok": True, "date": date_line, "sections": sections[:12],
                "items": items, "watched": watched,
                "page_count": len(pages), "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _meeting_date(text: str) -> str:
    m = re.search(r"BOARD OF SUPERVISORS[^\n]*\n([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    return m.group(1) if m else ""


def _numbered_items(text: str) -> list[dict]:
    """Items appear as '1) Resolution honoring …' (parenthesis, not dot), with
    optional 'CA' consent markers and action lines. Section headers are
    ALL-CAPS lines. Title = first line (+ up to 2 wrapped lines)."""
    items = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(r"^(\d{1,3})[.)]\s+(.+)$", s)
        if m:
            title = m.group(2).strip()
            for nxt in lines[i + 1:i + 3]:
                n = nxt.strip()
                if not n or re.match(r"^\d{1,3}[.)]", n) or n.isupper():
                    break
                title += " " + n
            items.append({"num": m.group(1), "title": title, "text": title})
    return items


def _sections(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.isupper() and len(s) > 4 and len(s) < 60 and not s.startswith("HTTP"):
            out.append(s.title())
    return out


def _watch_hit(item: dict) -> bool:
    hay = (item.get("title", "") + " " + item.get("text", "")).lower()
    return any(w in hay for w in WATCH_WORDS)
