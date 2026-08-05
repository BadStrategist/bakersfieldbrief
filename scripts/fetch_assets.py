#!/usr/bin/env python3
"""Download self-hosted fonts (Google Fonts woff2) + Leaflet into assets/.

Run once at repo setup; commit the results. Keeps CWV good (no render-blocking
CDN), works offline, and the site is fully static.

  python scripts/fetch_assets.py
"""
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
VENDOR = ROOT / "assets" / "vendor"
FONTS.mkdir(parents=True, exist_ok=True)
VENDOR.mkdir(parents=True, exist_ok=True)

UA_WOFF2 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

FAMILIES = [
    ("Barlow Condensed", "500;600;700", "barlow-condensed"),
    ("Public Sans", "400;500;700", "public-sans"),
    ("IBM Plex Mono", "400;500;600", "plex-mono"),
    ("Lora", "500;600;700", "lora"),
]

CSS_RULES = []
for family, weights, slug in FAMILIES:
    url = ("https://fonts.googleapis.com/css2?family="
           + family.replace(" ", "+") + ":wght@" + weights
           + "&display=swap")
    r = requests.get(url, headers={"User-Agent": UA_WOFF2}, timeout=60)
    r.raise_for_status()
    # group by unicode-range: each @font-face block → one file
    for block in re.findall(r"/\*\s*([a-z-]+)\s*\*/\s*@font-face\s*{([^}]+)}", r.text, re.S):
        subset, body = block
        m = re.search(r"font-family:\s*'([^']+)'", body)
        mw = re.search(r"font-weight:\s*(\d+)", body)
        mu = re.search(r"url\((https://[^)]+\.woff2)\)", body)
        if not (m and mw and mu):
            continue
        fname = f"{slug}-{mw.group(1)}-{subset}.woff2"
        data = requests.get(mu.group(1), headers={"User-Agent": UA_WOFF2}, timeout=90).content
        (FONTS / fname).write_bytes(data)
        CSS_RULES.append(
            f"@font-face{{font-family:'{m.group(1)}';font-style:normal;font-weight:{mw.group(1)};"
            f"font-display:swap;src:url('../fonts/{fname}') format('woff2');}}"
        )
        print(f"  {fname} ({len(data)//1024} KB)")

(FONTS / "fonts.css").write_text("\n".join(CSS_RULES), encoding="utf-8")
print(f"fonts.css: {len(CSS_RULES)} @font-face rules")

# ---- Leaflet (map engine) ----
leaflet_js = requests.get("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", timeout=90).text
leaflet_css = requests.get("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", timeout=90).text
(VENDOR / "leaflet.js").write_text(leaflet_js, encoding="utf-8")
(VENDOR / "leaflet.css").write_text(leaflet_css, encoding="utf-8")
print(f"leaflet: {len(leaflet_js)//1024} KB js, {len(leaflet_css)//1024} KB css")
