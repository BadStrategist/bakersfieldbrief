#!/usr/bin/env python3
"""Inspect ABC page JS to find how the daily report is really submitted."""
import re, requests

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})
r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")
html = r.text

# find the form and its onsubmit
m = re.search(r'<form id="daily-license-report-form".*?</form>', html, re.S)
form = m.group(0)
print("=== form tail (hidden + datepicker) ===")
print(form[-900:])

# find validateForm and any ajax references
for name in ["validateForm", "abclqs", "admin-post", "daily-report", "datepicker"]:
    idxs = [mm.start() for mm in re.finditer(name, html)]
    print(f"\n=== occurrences of '{name}': {len(idxs)} ===")
    for i in idxs[:4]:
        print(html[max(0, i-120):i+220].replace("\n", " ")[:340])
        print("---")
