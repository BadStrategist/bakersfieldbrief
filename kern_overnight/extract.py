#!/usr/bin/env python3
"""Stage 3 — EXTRACT: transcript JSONL -> structured incident JSON (LLM pass 1).

Chunks the transcript (~30k chars per call), runs the extraction prompt with
all privacy HARD RULEs, dedupes incidents across chunk boundaries by
time+type+area, and writes incidents/DATE.json (append-only dataset)."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from . import llm

CHUNK_CHARS = 30_000
SYSTEM = (
    "You are the overnight-desk extraction engine for 'The Kern Overnight', a "
    "scanner-based morning brief for Bakersfield / Kern County, CA. You turn raw "
    "police/fire/EMS scanner transcripts into a structured incident list. You are "
    "ruthlessly factual: if a transmission is garbled or unclear, you leave the "
    "incident OUT. Missing an incident is acceptable; inventing one is not."
)


def _chunk_rows(rows: list[dict], limit: int = CHUNK_CHARS) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for r in rows:
        size += len(r.get("text", "")) + 40
        if cur and size > limit:
            chunks.append(cur)
            cur, size = [r], len(r.get("text", "")) + 40
        else:
            cur.append(r)
    if cur:
        chunks.append(cur)
    return chunks


def _extract_chunk(rows: list[dict]) -> list[dict]:
    transcript = "\n".join(
        f"{r.get('time_local', '??:??')} [{r.get('source_file', '')}] {r.get('text', '')}"
        for r in rows)
    prompt = (
        "Below is a transcript of last night's police/fire/EMS scanner traffic "
        "for Bakersfield and Kern County. Extract every distinct incident into a "
        "JSON object with one key 'incidents' holding a list. Each incident:\n"
        "{\"time\": \"HH:MM (24h local)\", \"agency\": \"BPD|KCSO|KCFD|EMS|CHP|Other|Unknown\", "
        "\"type\": \"short incident type\", \"area\": \"generalized location\", "
        "\"summary\": \"1-2 factual sentences\", \"disposition\": \"outcome if heard, else unknown\", "
        "\"notability\": 1-5, \"supporting_quotes\": [\"short transcript fragments\"]}\n\n"
        "HARD RULES — non-negotiable:\n"
        "1. Never include names of any person, license plates, or callback numbers.\n"
        "2. Never include patient details or anything from ambulance-to-hospital traffic.\n"
        "3. Generalize all locations to block level or cross streets. Never an exact "
        "address, apartment/unit number, or a business name that identifies a private "
        "residence or victim.\n"
        "4. Only extract incidents supported by clear, coherent transmissions. Garbled "
        "or low-confidence audio is SKIPPED, never guessed at. A missing incident is "
        "acceptable; an invented one is not.\n"
        "5. Ignore radio checks, statuses with no incident, routine traffic stops with "
        "no notable outcome, and test counts.\n"
        "6. No speculation about guilt, cause, or identity — only what was dispatched "
        "and what units reported.\n"
        "7. Merge all transmissions about one event into a single incident.\n"
        "Notability: 5=major, 4=significant, 3=newsworthy routine, 2=minor, 1=barely a line.\n\n"
        f"TRANSCRIPT:\n{transcript[:CHUNK_CHARS]}"
    )
    data = llm.chat_json(prompt, SYSTEM)
    incidents = data.get("incidents", [])
    if not isinstance(incidents, list):
        return []
    return [i for i in incidents if isinstance(i, dict)]


def _dedupe(incidents: list[dict]) -> list[dict]:
    seen = {}
    out = []
    for inc in incidents:
        key = (str(inc.get("time", "")), str(inc.get("type", "")).lower(),
               str(inc.get("area", "")).lower())
        if key in seen:
            # merge: prefer the richer summary/disposition, union quotes
            prev = seen[key]
            for f in ("summary", "disposition"):
                if len(str(inc.get(f, ""))) > len(str(prev.get(f, ""))):
                    prev[f] = inc[f]
            qs = set(prev.get("supporting_quotes", [])) | set(inc.get("supporting_quotes", []))
            prev["supporting_quotes"] = sorted(qs)
        else:
            seen[key] = inc
            out.append(inc)
    return out


def extract(transcript_path: Path, out_path: Path) -> list[dict]:
    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript missing: {transcript_path}")
    rows = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        raise RuntimeError("empty transcript — nothing to extract (refusing empty brief)")
    all_inc = []
    for chunk in _chunk_rows(rows):
        all_inc += _extract_chunk(chunk)
    deduped = _dedupe(all_inc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # append-only dataset: merge with any existing file
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    merged = _dedupe(existing + deduped)
    out_path.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    return merged


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    t = Path("transcripts") / f"{d.isoformat()}.jsonl"
    o = Path("incidents") / f"{d.isoformat()}.json"
    incs = extract(t, o)
    print(f"{len(incs)} incidents → {o}")
