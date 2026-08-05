#!/usr/bin/env python3
"""Inspect: escribe agenda HTML, kern board PDF later pages, ABC row HTML."""
import sys, types, re, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build.sources import escribe
from build import common
import pdfplumber, requests

print("=== escribe agenda HTML structure ===")
m0 = escribe.run(types.SimpleNamespace(today=common.today_pacific()))["meetings"][0]
r = common.fetch(m0["url"], timeout=25)
html = r.text
print("len:", len(html))
# find agenda item markers
for pat in ["AgendaItem", "agenda-item", "ItemNumber", "itemNum", "agenda_item", "class=\"item", "agendaNumber"]:
    print(f"  '{pat}': {html.count(pat)}")
# strip tags and show first text content
txt = re.sub(r"<script.*?</script>", "", html, flags=re.S)
txt = re.sub(r"<[^>]+>", "|", txt)
txt = re.sub(r"\|+", "|", txt)
print("text-ish head:", txt[:1200])

print("\n=== kern board PDF pages 2-4 ===")
r = common.fetch("https://itsapps.kerncounty.com/clerk/minutes/boardagenda.pdf", timeout=60)
with pdfplumber.open(io.BytesIO(r.content)) as pdf:
    for i in [1, 2]:
        t = pdf.pages[i].extract_text() or ""
        print(f"--- page {i+1} ---")
        print(t[:900])

print("\n=== ABC row raw HTML ===")
from build.sources import abc
html_text = abc._get_report_page(common.today_pacific())
body = re.search(r"<tbody.*?</tbody>", html_text, re.S).group(0)
trs = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
for tr in trs[:1]:
    print(tr[:1500])
