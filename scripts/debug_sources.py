#!/usr/bin/env python3
"""Debug the 3 mismatched sources (fixed)."""
import json, re, datetime, requests, xml.etree.ElementTree as ET

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})

print("=== 1. ABC form inputs ===")
r = S.get("https://www.abc.ca.gov/licensing/licensing-reports/new-applications/")
m = re.search(r'<form id="daily-license-report-form".*?</form>', r.text, re.S)
if m:
    form = m.group(0)
    for i in re.findall(r"<input[^>]*>|<select[^>]*>|<textarea[^>]*>", form):
        print("  ", i[:170])
else:
    print("  form not found")

print("\n=== 2. CDEC raw shape ===")
end = datetime.date.today().isoformat()
start = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
url = f"https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet?Stations=ISB&SensorNums=15&dur_code=D&Start={start}&End={end}"
r = S.get(url)
print("status", r.status_code, "len", len(r.text))
print("head:", r.text[:500])

print("\n=== 3. CHP XML structure ===")
r = S.get("https://media.chp.ca.gov/sa_xml/sa.xml")
root = ET.fromstring(r.content)
print("root tag:", root.tag)
for i, ch in enumerate(list(root)[:2]):
    print(f"--- child {i}: <{ch.tag}> children={[c.tag for c in list(ch)]}")
    for c in list(ch)[:8]:
        print("    ", c.tag, repr((c.text or "").strip()[:40]), list(c.attrib.items())[:2])
found = [el for el in root.iter() if (el.text or "").strip().upper() == "LAHB"]
print("LAHB elements:", len(found))
if found:
    p = found[0]
    parent = None
    for anc in root.iter():
        if p in list(anc):
            parent = anc; break
    print("parent tag:", parent.tag if parent is not None else None)
    if parent is not None:
        print("parent children:", [(c.tag, (c.text or '').strip()[:30]) for c in list(parent)][:15])
