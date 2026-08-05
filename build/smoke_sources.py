#!/usr/bin/env python3
"""Run every source module once and summarize. python build/smoke_sources.py"""
import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build.sources import SOURCES
from build import common

ctx = types.SimpleNamespace(today=common.today_pacific())

for name, mod in SOURCES.items():
    try:
        res = mod.run(ctx)
        if res.get("ok"):
            keys = [k for k in res if k not in ("ok", "asof", "error")]
            brief = ", ".join(f"{k}={len(res[k]) if isinstance(res[k], (list, dict)) else res[k]}" for k in keys[:4])
            print(f"[OK  ] {name}: {brief}")
        else:
            print(f"[STUB/FAIL] {name}: {res.get('error', '?')[:110]}")
    except Exception as e:
        print(f"[CRASH] {name}: {type(e).__name__}: {e}")
