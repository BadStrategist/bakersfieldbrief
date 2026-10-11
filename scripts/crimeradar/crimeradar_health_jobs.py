#!/usr/bin/env python3
"""Print the CrimeRadar chain's own job state, for crimeradar_health.sh.

Separate file on purpose: the Hermes cron runner blocks python -c and heredocs,
so the health wrapper calls this instead. Read-only; never writes a job file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# The chain, in pipeline order. (id, label, what it must have done)
CHAIN = [
    ("f76fbfbb3977", "night monitor", "polls every 15 min, 19:00-06:45"),
    ("ffab0caa36d2", "emit", "stages the window at 07:15"),
    ("54d7c836a9b2", "publish backstop", "merges at 07:40"),
    ("c25ccbac11ee", "publish", "agent path at 07:30"),
    ("2df4a4eb9688", "morning pass", "verify + reel clips at 07:50"),
]


def main() -> int:
    p = Path(os.path.expandvars(r"%LOCALAPPDATA%\hermes\cron\jobs.json"))
    if not p.is_file():
        print("jobs  : cron store not found")
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    by_id = {j.get("id"): j for j in jobs}
    bad = 0
    print("chain jobs")
    for jid, label, expect in CHAIN:
        j = by_id.get(jid)
        if not j:
            print(f"  {label:<18}: job {jid} is GONE")
            bad += 1
            continue
        status = str(j.get("last_status") or "?")
        if status != "ok":
            bad += 1
        ran = str(j.get("last_run_at") or "never")[5:16].replace("T", " ")
        nxt = str(j.get("next_run_at") or "?")[5:16].replace("T", " ")
        flag = "" if status == "ok" else "  <-- FAILING"
        print(f"  {label:<18}: {status:<6} last {ran}  next {nxt}{flag}")
        if status != "ok":
            err = str(j.get("last_error") or "").strip().splitlines()
            if err:
                print(f"    {'':<16} {' '.join(err[:2])[:150]}")
        _ = expect  # kept for the reader; the label above says it
    if bad:
        print(f"chain jobs: {bad} not ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())