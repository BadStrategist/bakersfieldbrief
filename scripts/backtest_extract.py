#!/usr/bin/env python3
"""Backtest the deterministic incident extractor against LLM ground truth.

For each known night: run kern_overnight/extract.py over the transcript
digest, then compare against the LLM-written incidents/<date>.json:

  TP  — extractor incident matching an LLM incident (same type, time ±15m)
  FP  — extractor incident with no LLM match (over-extraction)
  FN  — LLM incident the extractor missed (under-extraction)

Fully offline and deterministic — runs in seconds.

Usage: python scripts/backtest_extract.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kern_overnight import extract as EX  # noqa: E402
from kern_overnight import streetcheck as SC  # noqa: E402

DATES = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"]


def digest_rows(transcript: Path) -> list[dict]:
    """Quality rows in the same shape the digest tool produces."""
    rows = []
    for ln in transcript.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("confidence", 0) > -0.45 and len(r.get("text", "")) > 30:
            rows.append(r)
    return rows


_CATEGORY = {
    "fire": {"fire", "structure fire", "vehicle fire", "grass fire",
             "vegetation fire", "outside fire", "electrical fire",
             "commercial fire alarm", "fire cause investigation"},
    "police": {"shooting", "assault with a weapon", "burglary", "hit and run",
               "domestic call", "reckless driver", "foot pursuit",
               "warrant service", "probation check", "suspicious person report",
               "stolen firearms search", "officer assist", "disturbance",
               "juvenile disturbance", "suspicious circumstances",
               "suspicious person", "burglary attempt"},
    "medical": {"medical aid", "medical alarm", "man down", "mental health crisis",
                "welfare call", "suicidal subject", "assault report",
                "domestic violence with injury"},
    "traffic": {"traffic collision", "vehicle vs pedestrian",
                "vehicle into building"},
}


def category(t: str) -> str:
    key = EX.re.sub(r"[^a-z ]", "", str(t or "").lower().strip())
    for cat, names in _CATEGORY.items():
        for n in names:
            if key == EX.re.sub(r"[^a-z ]", "", n):
                return cat
    return "other"


def match(ext, llm) -> bool:
    """Same incident CATEGORY (fire/police/medical/traffic) AND time ±15m."""
    if category(ext["type"]) != category(llm["type"]):
        return False
    try:
        e = int(ext["time"].split(":")[0]) * 60 + int(ext["time"].split(":")[1])
        l = int(llm["time"].split(":")[0]) * 60 + int(llm["time"].split(":")[1])
    except (ValueError, IndexError):
        return False
    return abs(e - l) <= 15


def main() -> int:
    streets = SC.load_streets()
    print(f"gazetteer: {len(streets)} streets | nights: {len(DATES)}")
    t0 = time.time()
    print(f"\n{'date':<12}{'LLM':>5}{'ext':>5}{'TP':>4}{'FP':>4}{'FN':>4}"
          f"{'prec':>7}{'recall':>7}{'wall':>7}")
    tot = {"llm": 0, "ext": 0, "tp": 0, "fp": 0, "fn": 0}
    for date in DATES:
        t1 = time.time()
        tr = ROOT / "transcripts" / f"{date}.jsonl"
        inc_file = ROOT / "incidents" / f"{date}.json"
        if not tr.exists() or not inc_file.exists():
            print(f"{date:<12}  (missing transcript or incidents)")
            continue
        rows = digest_rows(tr)
        ext_incs = EX.extract(rows, streets)
        llm_incs = json.loads(inc_file.read_text(encoding="utf-8"))

        tp = fp = fn = 0
        matched_llm = set()
        for e in ext_incs:
            hit = next((i for i, l in enumerate(llm_incs)
                        if i not in matched_llm and match(e, l)), None)
            if hit is not None:
                tp += 1
                matched_llm.add(hit)
            else:
                fp += 1
        fn = len(llm_incs) - len(matched_llm)
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        for k, v in [("llm", len(llm_incs)), ("ext", len(ext_incs)),
                     ("tp", tp), ("fp", fp), ("fn", fn)]:
            tot[k] += v
        print(f"{date:<12}{len(llm_incs):>5}{len(ext_incs):>5}{tp:>4}{fp:>4}"
              f"{fn:>4}{prec:>7.0%}{rec:>7.0%}{time.time()-t1:>6.1f}s")
    p = tot["tp"] / (tot["tp"] + tot["fp"]) if tot["tp"] + tot["fp"] else 0
    r = tot["tp"] / (tot["tp"] + tot["fn"]) if tot["tp"] + tot["fn"] else 0
    print("-" * 55)
    print(f"{'TOTAL':<12}{tot['llm']:>5}{tot['ext']:>5}{tot['tp']:>4}{tot['fp']:>4}"
          f"{tot['fn']:>4}{p:>7.0%}{r:>7.0%}{time.time()-t0:>6.1f}s")
    print(f"\nwall time total: {time.time()-t0:.1f}s (offline, deterministic)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
