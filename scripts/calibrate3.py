#!/usr/bin/env python3
"""Inspect escribe AgendaItem blocks + kern board items + ABC row."""
import sys, types, re, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build.sources import escribe
from build import common
import pdfplumber

print("=== escribe AgendaItem context ===")
m0 = escribe.run(types.SimpleNamespace(today=common.today_pacific()))["meetings"][0]
html = common.fetch(m0["url"], timeout=25).text
i = html.find("AgendaItem")
print(html[max(0, i-300):i+1200].replace("\n", " ")[:1500])
print("\n=== kern board pages 2-3 ===")
r = common.fetch("https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf", timeout=60)
with pdfplumber.open(io.BytesIO(r.content)) as pdf:
    for i in [1, 2]:
        t = pdf.pages[i].extract_text() or ""
        print(f"--- page {i+1} ---")
        print(t[:700])
        print()

print("=== ABC row raw HTML ===")
from build.sources import abc
html_text = abc._get_report_page(common.today_pacific())
body = re.search(r"<tbody.*?</tbody>", html_text, re.S).group(0)
trs = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
print(trs[0][:1400])
