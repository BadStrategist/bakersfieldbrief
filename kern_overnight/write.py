#!/usr/bin/env python3
"""Stage 4 — WRITE: incidents JSON -> Markdown morning brief (LLM pass 2).

Structure: title, opening, '## The big one' (only if a 4+ incident exists),
'## Around the county' (notability 3-4), '## The log' (notability 2, one
line each), '## Night notes' (optional). Footer lines are appended in CODE
so they can never be omitted: the privacy disclaimer AND the required
Broadcastify attribution."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from . import llm

SYSTEM = (
    "You are the writer of 'The Kern Overnight', a morning brief for Bakersfield "
    "and Kern County, CA, compiled from police/fire/EMS scanner audio. Your voice "
    "is a neighbor who stayed up listening so the reader didn't have to: local, "
    "plainspoken, factual. No sensationalism, no crime-panic framing, no cop-drama "
    "slang. Dry wit is acceptable on quiet nights; never joke about someone's bad "
    "night. Use ONLY the provided incident data — no outside facts, causes, or "
    "context. Attribute everything as preliminary ('crews were sent to', 'a caller "
    "reported', 'units responded to'). Never assert confirmed outcomes beyond the "
    "given disposition. Keep location generalization exactly as provided; never "
    "sharpen it. No names, ever. Target 600-1000 words through fuller narrative "
    "on real incidents, never fabrication or padding; a thin night may run under "
    "600 words — say so plainly if the night was quiet."
)

FOOTER = (
    "\n\n---\n\n*Compiled from initial emergency dispatch reports; details are "
    "preliminary and unconfirmed. Locations are generalized for privacy.*\n\n"
    "Audio Provided by Broadcastify."
)


def _fmt_time(t: str) -> str:
    try:
        hh, mm = t.split(":")[:2]
        h = int(hh)
        return f"{h % 12 or 12}:{mm}{'a' if h < 12 else 'p'}"
    except Exception:  # noqa: BLE001
        return t or "??:??"


def write_brief(incidents: list[dict], date: dt.date) -> str:
    if not incidents:
        raise RuntimeError("no incidents to write (refusing empty brief)")
    by_note = {5: [], 4: [], 3: [], 2: []}
    for inc in incidents:
        n = int(inc.get("notability", 1))
        by_note.setdefault(n, []).append(inc)
    big = (by_note[5] + by_note[4])[:1]
    around = (by_note[4] + by_note[3])[:8]
    log = by_note[2][:25]

    payload = json.dumps(incidents, indent=1, ensure_ascii=False)
    prompt = (
        f"Write 'The Kern Overnight — {date.strftime('%A, %B %-d, %Y')}'. Markdown.\n\n"
        "Structure:\n"
        "1. Title heading (# The Kern Overnight — {date})\n"
        "2. Opening paragraph: the night's pace, dominant theme, which parts of "
        "town were busy.\n"
        "3. '## The big one' — ONLY if an incident rates 4+; otherwise omit the "
        "section entirely.\n"
        "4. '## Around the county' — notability 3-4 incidents, each a 5-6 sentence "
        "paragraph; group related incidents where natural.\n"
        "5. '## The log' — notability-2 items, one line each: **HH:MM** — {type}, "
        "{area}. {one-line summary/disposition}\n"
        "6. '## Night notes' — optional; patterns visible ONLY in the provided data.\n\n"
        "Do not include a footer — the publisher appends it.\n\n"
        f"INCIDENTS:\n{payload}"
    )
    body = llm.chat_text(prompt, SYSTEM, max_tokens=2200)
    return body.rstrip() + FOOTER


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    src = Path("incidents") / f"{d.isoformat()}.json"
    if not src.exists():
        sys.exit(f"no incidents at {src} — run extract first")
    incs = json.loads(src.read_text(encoding="utf-8"))
    brief = write_brief(incs, d)
    out = Path("briefs") / f"{d.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(brief, encoding="utf-8")
    print(f"{len(brief)} chars → {out}")
