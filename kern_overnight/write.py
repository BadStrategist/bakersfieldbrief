#!/usr/bin/env python3
"""Stage 4 — WRITE: incidents JSON -> Markdown morning brief (LLM pass 2).

Structure: title, opening, '## The big one' (only if a 4+ incident exists),
'## Around the county' (the 3-4 incidents told as paragraphs),
'## The log' (EVERY other incident, one row each, built in code),
'## Night notes' (required — a brief 2-3 sentence summary of the night's
patterns: busiest hours, notable threads, outcomes). Footer lines are appended
in CODE so they can never be omitted: the privacy disclaimer."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import llm, regions

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
    "sharpen it. Name a part of town (southwest Bakersfield, east Bakersfield "
    "and the like) ONLY when the incident carries a 'region' field, and "
    "then use that exact phrase; an incident with no 'region' gets its street "
    "and no part of town. Never work out a part of town from a street name. "
    "No names, ever. Target 600-1000 words through fuller narrative "
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

    The night window runs 19:00 -> 07:00, so a plain ``HH:MM`` sort puts
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


def incident_key(inc: dict) -> tuple[str, str]:
    """Identity of a row: its time and the first 60 chars of what it says.

    A set of times is NOT an identity. On 2026-10-10 two rows share 22:06 (a
    radio stolen vehicle and an emulator vehicle stop), so a time set cannot
    tell that the second one is missing from the page.
    """
    what = _one_line(inc.get("summary") or inc.get("disposition") or "")
    return (str(inc.get("time", "")), what[:60])


def paragraph_incidents(incidents: list[dict]) -> list[dict]:
    """The incidents the writer is asked to tell as PARAGRAPHS (prompt step 4).

    Exactly the picks the prompt hands the model: the single 4+ lead and up to
    eight 3-4 incidents. Everything else belongs in the log, so this one
    function decides which incidents are told twice and which are not told at
    all if it is wrong.
    """
    by_note: dict[int, list[dict]] = {}
    for inc in incidents:
        by_note.setdefault(int(inc.get("notability", 1)), []).append(inc)
    big = (by_note.get(5, []) + by_note.get(4, []))[:1]
    around = (by_note.get(4, []) + by_note.get(3, []))[:8]
    out, seen = [], set()
    for inc in big + around:
        k = incident_key(inc)
        if k not in seen:
            seen.add(k)
            out.append(inc)
    return out


def _log_row(inc: dict) -> str:
    """One log bullet: time first, then type and area, then the summary."""
    typ = " ".join(str(inc.get("type") or "incident").split())
    typ = typ[:1].upper() + typ[1:]
    area = " ".join(str(inc.get("area") or "").split())
    what = _one_line(inc.get("summary") or inc.get("disposition") or "")
    head = f"{typ}, {area}" if area else typ
    line = f"- **{fmt_time_long(inc.get('time', ''))}** — {head}."
    return f"{line} {what}".rstrip()


def log_rows(incidents: list[dict], limit: int = 40,
             skip: list[dict] | None = None) -> list[str]:
    """The log bullets: every incident NOT told as a paragraph, in night order.

    The rule is a partition, not a notability cut. The old rule took notability
    2 only, so a 3 that missed the eight "Around the county" slots appeared
    nowhere on the page at all, and the 2026-10-10 page was whole only because
    the 07:30 agent logged six of them by hand.
    """
    skipped = {incident_key(i) for i in (skip or [])}
    items = [i for i in incidents if incident_key(i) not in skipped]
    items.sort(key=lambda i: night_key(i.get("time", "")))
    if len(items) > limit:
        print(f"[write] log capped at {limit}: {len(items) - limit} row(s) past "
              "the cap are not on the page", flush=True)
    return [_log_row(inc) for inc in items[:limit]]


def render_log_section(incidents: list[dict], limit: int = 40,
                       skip: list[dict] | None = None) -> str:
    """The '## The log' section, built in CODE: time first, chronological.

    The log used to be written by the LLM from a prompt asking for
    ``**HH:MM** — {type}, {area}.`` lines. It never complied: times were
    buried mid-sentence ("Deputies were sent at 12:02 a.m.") and the entries
    came back in notability order (12:02a, 12:01a, 1:02a, 3:55a, 11:06p,
    11:02p, 10:15p …). Building the section here makes both properties
    deterministic, so a reader can always scan the night in the order it
    happened. Returns "" when there is nothing to log.
    """
    rows = log_rows(incidents, limit, skip)
    if not rows:
        return ""
    return "\n".join(["## The log", ""] + rows + [""])


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


ROW_LINE = re.compile(r"^[ \t]*-\s+\*\*(\d{1,2}:\d{2} [ap]\.m\.)\*\*")


def log_lines(body: str) -> list[str]:
    """The bullet lines inside the body's '## The log' section, verbatim."""
    m = _LOG_HEAD.search(body or "")
    if not m:
        return []
    tail = (body or "")[m.end():]
    nxt = re.search(r"^[ \t]*#{1,6}[ \t]*\S", tail, re.M)
    block = tail[:nxt.start()] if nxt else tail
    return [ln.rstrip() for ln in block.splitlines() if ROW_LINE.match(ln)]


def insert_log_lines(body: str, rows: list[str], limit: int = 40) -> tuple[str, int]:
    """Add the rows the body's log is missing, keeping the night in order.

    This is how the RELEASE path closes the second-source gap. A body written
    before the emulator rows landed cannot be repaired by re-writing it (the
    writer's prose is worth more than the code-built template, and both render
    the same notability-2 log), so the missing rows are inserted instead. The
    writer's own lines stay verbatim.

    A row is missing when its TIME has no unused occurrence left in the log: a
    multiset, not a set. Two rows share 22:06 on 2026-10-10 (radio stolen
    vehicle, emulator vehicle stop), and a set would hide the second one.
    """
    if not rows:
        return body, 0
    existing = log_lines(body)
    left: dict[str, int] = {}
    for line in existing:
        t = ROW_LINE.match(line).group(1)
        left[t] = left.get(t, 0) + 1
    merged, added = list(existing), 0
    for row in rows:
        t = ROW_LINE.match(row).group(1)
        if left.get(t):
            left[t] -= 1
            continue
        merged.append(row)
        added += 1
    if not added:
        return body, 0
    if len(merged) > limit:
        print(f"[write] log would hold {len(merged)} rows, over the {limit} cap: "
              f"keeping the earliest {limit}", flush=True)
        merged = merged[:limit]
    merged.sort(key=lambda ln: night_key(_line_clock(ln)))
    section = "\n".join(["## The log", ""] + merged + [""])
    return _insert_log(body, section), added


def _line_clock(line: str) -> str:
    """'p.m.' display time back to 24h, so one night sorts as one night."""
    m = ROW_LINE.match(line or "")
    if not m:
        return ""
    return _clock_from_display(m.group(1))


def _clock_from_display(display: str) -> str:
    try:
        mm = re.match(r"(\d{1,2}):(\d{2}) ([ap])\.m\.", display)
        h, mi, ap = int(mm.group(1)) % 12, int(mm.group(2)), mm.group(3)
        if ap == "p":
            h += 12
        return f"{h:02d}:{mi:02d}"
    except Exception:  # noqa: BLE001
        return ""


def write_brief(incidents: list[dict], date: dt.date) -> str:
    if not incidents:
        raise RuntimeError("no incidents to write (refusing empty brief)")
    told = paragraph_incidents(incidents)

    # The part of town is looked up, never written from memory: the 2026-10-09
    # report put Pembroke Avenue in "southwest Bakersfield" (it is north).
    incidents = [dict(i) for i in incidents]
    regions.annotate(incidents)
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
        "paragraph; group related incidents where natural. Cover no incident "
        "below notability 3 as a paragraph: every incident you do not cover "
        "appears in the log as a one-line row, and covering one twice would "
        "print it twice.\n"
        "5. Do NOT write a '## The log' section. It is generated from the "
        "incident data and inserted after you, so that every entry carries its "
        "time and the night reads in order.\n"
        "6. '## Night notes' — REQUIRED: a brief 2-3 sentence summary of the night's "
        "patterns (busiest hours, notable threads, outcomes).\n\n"
        "Do not include a footer — the publisher appends it.\n\n"
        f"INCIDENTS:\n{payload}"
    )
    body = llm.chat_text(prompt, SYSTEM, max_tokens=2200)
    body, wrong = regions.check(body, incidents)
    for w in wrong:
        print(f"[write] part of town corrected: {w}", flush=True)
    body = _insert_log(body.rstrip(),
                       render_log_section(incidents, skip=told))
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
