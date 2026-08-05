#!/usr/bin/env python3
"""Calibrate escribe + kern_board + abc parsers."""
import sys, types, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build.sources import escribe, kern_board, abc
from build import common

ctx = types.SimpleNamespace(today=common.today_pacific())

print("=== escribe raw meeting sample ===")
res = escribe.run(ctx)
for m in res["meetings"][:3]:
    print(json.dumps(m, indent=1)[:500])
print("upcoming:", len(res["upcoming"]))
# agenda fetch test on first meeting
m0 = res["meetings"][0]
print("agenda items for", m0["name"], ":", len(escribe._fetch_agenda(m0["id"])), "items")
ag = escribe._fetch_agenda(m0["id"])
if ag: print("  sample:", ag[0])

print("\n=== kern_board raw text sample ===")
import io, pdfplumber, requests
r = common.fetch("https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf", timeout=60)
with pdfplumber.open(io.BytesIO(r.content)) as pdf:
    t = pdf.pages[0].extract_text() or ""
print(t[:800])
# find what numbered items look like
for ln in t.splitlines():
    if ln.strip() and (ln.strip()[0].isdigit() or "ITEM" in ln.upper()):
        print("LINE:", ln[:90])

print("\n=== abc parse check ===")
html_text = abc._get_report_page(ctx.today)
rows = abc._parse_rows(html_text)
print("rows parsed:", len(rows))
print("first rows:", [ (x["license"], x["dba"][:25], x["type"], x["expires"]) for x in rows[:3] ])
