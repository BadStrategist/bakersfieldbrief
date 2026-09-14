#!/usr/bin/env python3
"""Stage 4 — WRITE: incidents JSON -> Markdown morning brief (LLM pass 2).

Structure: title, opening, '## The big one' (only if a 4+ incident exists),
'## Around the county' (notability 3-4), '## The log' (notability 2, one
'## Night notes' (required — a brief 2-3 sentence summary of the night's
patterns: busiest hours, notable threads, outcomes). Footer lines are appended
in CODE so they can never be omitted: the privacy disclaimer."""
from __future__ import annotations

import datetime as dt
import json
import re
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
    "> Audio Provided by Broadcastify.\n\n"
)


def _fmt_date_long(date: dt.date) -> str:
    """'Thursday, September 10, 2026'.

    Build with ``%A, %B`` + ``date.day`` — NEVER ``%A, %B %-d, %Y``. The ``%-d``
    no-pad modifier is glibc-only: on Windows (this pipeline's platform) it
    raises ``ValueError: Invalid format string`` and killed stage 4 outright.
    The rest of the repo already does it this way (build/builders/fair.py:71).
    """
    return f"{date.strftime('%A, %B')} {date.day}, {date.year}"


def _fmt_time(t: str) -> str:
    try:
        hh, mm = t.split(":")[:2]
        h = int(hh)
        return f"{h % 12 or 12}:{mm}{'a' if h < 12 else 'p'}"
    except Exception:  # noqa: BLE001
        return t or "??:??"


def night_key(t: str) -> int:
    """Sort key for an overnight clock time — minutes since NOON.

    The night window runs 21:00 -> 06:00, so a plain ``HH:MM`` sort puts
    11pm AFTER 1am. Shifting by 12h orders a whole night across midnight
    (23:00 -> 660, 01:00 -> 780). Unparseable times sort last.
    """
    try:
        hh, mm = str(t).split(":")[:2]
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(t)
        return ((h - 12) % 24) * 60 + m
    except Exception:  # noqa: BLE001
        return 24 * 60


def fmt_time_long(t: str) -> str:
    """'22:37' -> '10:37 p.m.'  Unparseable -> 'Time not logged'."""
    try:
        hh, mm = str(t).split(":")[:2]
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(t)
        return f"{h % 12 or 12}:{m:02d} {'a.m.' if h < 12 else 'p.m.'}"
    except Exception:  # noqa: BLE001
        return "Time not logged"


def _one_line(text: str, limit: int = 240) -> str:
    """Collapse whitespace and cut at a WORD boundary, never mid-word."""
    s = " ".join((text or "").split())
    if not s:
        return ""
    first = re.split(r"(?<=[.!?])\s+", s)[0].strip()
    if len(first) > limit:
        cut = first[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        return cut
    return first


def render_log_section(incidents: list[dict], limit: int = 25) -> str:
    """The '## The log' section, built in CODE: time first, chronological.

    The log used to be written by the LLM from a prompt asking for
    ``**HH:MM** — {type}, {area}.`` lines. It never complied: times were
    buried mid-sentence ("Deputies were sent at 12:02 a.m.") and the entries
    came back in notability order (12:02a, 12:01a, 1:02a, 3:55a, 11:06p,
    11:02p, 10:15p …). Building the section here makes both properties
    deterministic — a reader can always scan the night in the order it
    happened. Returns "" when there is nothing to log.
    """
    items = [i for i in incidents if int(i.get("notability", 1)) == 2]
    if not items:
        items = [i for i in incidents if int(i.get("notability", 1)) <= 2]
    if not items:
        items = list(incidents)
    items = sorted(items, key=lambda i: night_key(i.get("time", "")))[:limit]
    if not items:
        return ""
    out = ["## The log", ""]
    for inc in items:
        typ = " ".join(str(inc.get("type") or "incident").split())
        typ = typ[:1].upper() + typ[1:]
        area = " ".join(str(inc.get("area") or "").split())
        what = _one_line(inc.get("summary") or inc.get("disposition") or "")
        head = f"{typ}, {area}" if area else typ
        line = f"- **{fmt_time_long(inc.get('time', ''))}** — {head}."
        out.append(f"{line} {what}".rstrip())
    out.append("")
    return "\n".join(out)


_LOG_HEAD = re.compile(r"^[ \t]*#{1,6}[ \t]*the log\b.*$", re.I | re.M)


def _insert_log(body: str, section: str) -> str:
    """Drop any LLM-written '## The log' and splice in the code-built one."""
    if not section:
        return body
    m = _LOG_HEAD.search(body)
    if m:
        tail = body[m.end():]
        nxt = re.search(r"^[ \t]*#{1,6}[ \t]*\S", tail, re.M)
        body = (body[:m.start()] + (tail[nxt.start():] if nxt else "")).rstrip()
    n = re.search(r"^[ \t]*#{1,6}[ \t]*night notes\b.*$", body, re.I | re.M)
    if n:
        return body[:n.start()] + section + "\n" + body[n.start():]
    return body.rstrip() + "\n\n" + section


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
        f"Write 'The Kern Overnight — {_fmt_date_long(date)}'. Markdown.\n\n"
        "Structure:\n"
        "1. Title heading (# The Kern Overnight — {date})\n"
        "2. Opening paragraph: the night's pace, dominant theme, which parts of "
        "town were busy.\n"
        "3. '## The big one' — ONLY if an incident rates 4+; otherwise omit the "
        "section entirely.\n"
        "4. '## Around the county' — notability 3-4 incidents, each a 5-6 sentence "
        "paragraph; group related incidents where natural.\n"
        "5. Do NOT write a '## The log' section. It is generated from the "
        "incident data and inserted after you, so that every entry carries its "
        "time and the night reads in order.\n"
        "6. '## Night notes' — REQUIRED: a brief 2-3 sentence summary of the night's "
        "patterns (busiest hours, notable threads, outcomes).\n\n"
        "Do not include a footer — the publisher appends it.\n\n"
        f"INCIDENTS:\n{payload}"
    )
    body = llm.chat_text(prompt, SYSTEM, max_tokens=2200)
    body = _insert_log(body.rstrip(), render_log_section(incidents))
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
