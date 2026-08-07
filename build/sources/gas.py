#!/usr/bin/env python3
"""AAA gas prices for Bakersfield — gasprices.aaa.com/?state=CA, parsed from
the metro accordion block. Free, no key. Any failure -> {"ok": False}."""
from __future__ import annotations

import re

from .. import common

URL = "https://gasprices.aaa.com/?state=CA"


def run(ctx):
    try:
        body = common.fetch(URL, timeout=30).text
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # Bakersfield accordion: <h3 data-cost="..." data-title>Bakersfield</h3>
    idx = body.find("<h3 data-cost=")
    while idx != -1:
        end_h3 = body.find("</h3>", idx)
        if end_h3 != -1 and "Bakersfield" in body[idx:end_h3]:
            block = body[idx:idx + 2600]
            break
        idx = body.find("<h3 data-cost=", idx + 1)
    else:
        return {"ok": False, "error": "Bakersfield block not found on AAA page"}

    m = re.search(r'data-cost="([\d.]+)"', block)
    current = float(m.group(1)) if m else None

    # table rows: <td>Current Avg.</td><td>$5.6616</td>... (Reg/Mid/Prem/Diesel)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S)
    labels = {"Current Avg.": "current", "Yesterday Avg.": "yesterday"}
    out = {}
    for row in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if not cells or cells[0] not in labels:
            continue
        key = labels[cells[0]]
        prices = []
        for c in cells[1:5]:
            pm = re.search(r"\$?([\d.]+)", c)
            prices.append(float(pm.group(1)) if pm else None)
        # Regular, Mid, Premium, Diesel
        out[key] = {"regular": prices[0], "mid": prices[1],
                    "premium": prices[2], "diesel": prices[3]}

    if not out.get("current"):
        return {"ok": False, "error": "could not parse Bakersfield price rows"}
    if current is None:
        current = out["current"].get("regular")

    return {"ok": True, "metro": "Bakersfield", "current": out["current"],
            "yesterday": out.get("yesterday", {}), "asof": common.iso_today()}
