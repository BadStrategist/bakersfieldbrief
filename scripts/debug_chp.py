#!/usr/bin/env python3
"""Probe CHP sa.xml structure precisely."""
import requests, re
import xml.etree.ElementTree as ET

S = requests.Session()
S.headers.update({"User-Agent": "BakersfieldDailyBriefBot/1.0 (local news site; editor@bakersfieldbrief.com)"})
r = S.get("https://media.chp.ca.gov/sa_xml/sa.xml")
raw = r.text
print("len:", len(raw))
print("LAHB in raw:", raw.count("LAHB"), "| BFCC in raw:", raw.count("BFCC"))
print("UKCC:", raw.count("UKCC"), "| LA:", raw.count("LA"))
# show first 600 chars raw
print("--- raw head ---")
print(raw[:600])
print("--- raw tail ---")
print(raw[-600:])
root = ET.fromstring(raw)
# unique center-level identifiers: look at Center tags and their children attrs
centers = list(root)
print("n centers:", len(centers))
for c in centers[:6]:
    attrs = {k: v for k, v in c.attrib.items()}
    kids = [(k.tag, k.attrib) for k in list(c)[:3]]
    print("Center attrs:", attrs, "| first kids:", kids)
# all distinct Dispatch IDs
ids = set()
for c in centers:
    for d in c:
        if "ID" in d.attrib:
            ids.add(d.attrib["ID"])
print("all dispatch IDs:", sorted(ids))
