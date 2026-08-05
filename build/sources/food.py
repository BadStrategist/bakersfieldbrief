#!/usr/bin/env python3
"""Kern County Environmental Health — closed food facilities table.

https://phweb.kerncounty.com/EH_Framed_Webpages/EH_Enforcement_ClosedFoodFacility.aspx
Rows: facility, address, closure score (verified Aug 2026, 23 table rows).
"""
from __future__ import annotations

import html
import re

from .. import common

URL = "https://phweb.kerncounty.com/EH_Framed_Webpages/EH_Enforcement_ClosedFoodFacility.aspx"


def run(ctx):
    try:
        r = common.fetch(URL, timeout=40)
        rows = []
        body = re.search(r"<tbody.*?</tbody>", r.text, re.S)
        frag = body.group(0) if body else r.text
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", frag, re.S):
            cells = []
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S):
                txt = re.sub(r"<[^>]+>", " ", c)
                txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
                cells.append(txt)
            if len(cells) < 3:
                continue
            # Table layout (verified Aug 2026): date | facility | address | … | status("Closed-74")
            if re.match(r"^\d{1,2}/\d{1,2}/\d{4}", cells[0]):
                closed_date, facility, address = cells[0], cells[1], cells[2]
                score_raw = cells[4] if len(cells) > 4 else (cells[3] if len(cells) > 3 else "")
            else:
                # skip header rows like "INSPECTION DATE | FACILITY | ADDRESS"
                if cells[0].upper().startswith(("INSPECTION", "FACILITY", "DATE", "FACILITY NAME", "CLOSURE")):
                    continue
                closed_date, facility, address, score_raw = "", cells[0], cells[1], (cells[2] if len(cells) > 2 else "")
            m = re.search(r"(\d{1,3})", score_raw)
            rows.append({
                "facility": facility,
                "address": address,
                "closed_date": closed_date,
                "score": m.group(1) if m else score_raw,
                "status": score_raw,
                "raw": " | ".join(cells),
            })
        # dedup against snapshot so "recently closed" is meaningful
        snapshot = common.load_snapshot("food_seen", default=[])
        keys = {r["raw"] for r in rows}
        fresh = [r for r in rows if r["raw"] not in set(snapshot)]
        common.save_snapshot("food_seen", sorted(keys))
        return {"ok": True, "items": rows, "new": fresh, "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
