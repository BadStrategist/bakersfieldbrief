#!/usr/bin/env python3
"""Compact digest of a Kern Overnight transcript JSONL.

Rows with confidence > -0.45 and text length > 30, sorted by night-time.
Usage: python kern_overnight/digest.py transcripts/2026-08-13.jsonl [--min-conf 0.0]
"""
import json
import re
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    path = Path(args[0]) if args else Path("transcripts") / "latest.jsonl"
    min_conf = -0.45
    if "--min-conf" in args:
        min_conf = float(args[args.index("--min-conf") + 1])
    if not path.exists():
        print(f"missing: {path}")
        return 1
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        conf = r.get("confidence", 0.0)
        text = (r.get("text") or "").strip()
        if conf <= min_conf or len(text) <= 30:
            continue
        rows.append(r)
    rows.sort(key=lambda r: r.get("time_local", ""))
    print(f"# {len(rows)} usable rows (conf>{min_conf}, len>30) from {path.name}")
    print("=" * 100)
    for r in rows:
        t = r.get("time_local", "??:??")
        src = Path(r.get("source_file", "")).name
        conf = r.get("confidence", 0.0)
        text = re.sub(r"\s+", " ", r.get("text", "")).strip()
        print(f"[{t}] ({conf:.2f}) {src}")
        print(f"    {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
