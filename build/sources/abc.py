#!/usr/bin/env python3
"""CA Dept. of Alcoholic Beverage Control — new license applications.

Per the endpoint notes (tested Aug 2026): POST to admin-post.php with
action=abclqs_daily_report, a nonce scraped from the new-applications page,
and abclqs-date=MM/DD/YYYY.

Verified behavior (Aug 2026): the nonce field is named `abclqs_daily_report`
(not `abclqs_nonce`), and the public page renders the same statewide table
regardless of RPTDATE — the plugin's date filter is not applied server-side
for anonymous visitors. So we POST per the documented flow (which 302s back to
the page) and fall back to parsing the page directly; output is identical.
Filter rows where the premises city = BAKERSFIELD. Dedup by license number
against the previous snapshot so the feed shows new filings.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import common

PAGE = "https://www.abc.ca.gov/licensing/licensing-reports/new-applications/"
POST = "https://www.abc.ca.gov/wp-admin/admin-post.php"
CITY = "BAKERSFIELD"


def run(ctx):
    try:
        html_text = _get_report_page(ctx.today)
        rows = _parse_rows(html_text)
        bakersfield = [r for r in rows if _is_bakersfield(r)]

        # dedup vs snapshot (license# = district|num)
        seen = set(common.load_snapshot("abc_licenses", default=[]))
        fresh = [r for r in bakersfield if r["key"] not in seen]
        seen.update(r["key"] for r in bakersfield)
        common.save_snapshot("abc_licenses", sorted(seen))

        return {"ok": True, "items": bakersfield, "new": fresh,
                "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _get_report_page(today: dt.date) -> str:
    """POST per documented flow; on any failure fall back to the plain GET."""
    try:
        page = common.fetch(PAGE).text
        m = re.search(r'name=["\']abclqs_daily_report["\'][^>]*value=["\']([^"\']+)["\']', page)
        if not m:
            m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']abclqs_daily_report["\']', page)
        if not m:
            return page
        nonce = m.group(1)
        date = today.strftime("%m/%d/%Y")
        r = common.fetch(POST, method="POST", data={
            "action": "abclqs_daily_report",
            "url": "/licensing/licensing-reports/new-applications/",
            "rpttype": "2",
            "abclqs_daily_report": nonce,
            "_wp_http_referer": "/licensing/licensing-reports/new-applications/",
            "abclqs-date": date,
        })
        return r.text
    except Exception:  # noqa: BLE001
        return common.fetch(PAGE).text


def _parse_rows(html_text: str) -> list[dict]:
    body = re.search(r"<tbody.*?</tbody>", html_text, re.S)
    frag = body.group(0) if body else html_text
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", frag, re.S):
        # cells may be <th> (license) or <td>; keep raw inner HTML for <br/> splits
        cells = [c for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if not cells:
            continue
        text = _cell(" ".join(cells))
        if "DBA:" not in text and "BAKERSFIELD" not in text.upper():
            continue  # header or junk row
        rows.append(_row_from_cells(cells))
    return rows


def _cell(inner: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", inner)
    return html.unescape(re.sub(r"\s+", " ", txt)).strip()


def _cell_lines(inner: str) -> list[str]:
    """Cell text split on <br/> with each line trimmed."""
    txt = re.sub(r"<[^>]+>", "\n", inner)
    return [html.unescape(l.strip()) for l in txt.splitlines() if l.strip()]


def _row_from_cells(cells: list[str]) -> dict:
    lic_num = ""
    lic_link = ""
    m = re.search(r'href="([^"]*single-license[^"]*)"[^>]*>\s*(\d+)', cells[0])
    if m:
        lic_link, lic_num = m.group(1), m.group(2)
    dba = ""
    premise_lines: list[str] = []
    for c in cells[1:]:
        lines = _cell_lines(c)
        for j, ln in enumerate(lines):
            if ln.upper().startswith("DBA:"):
                dba = ln[4:].strip()
                # following lines: legal name, then premises street, then city,state zip
                for extra in lines[j + 1:]:
                    if extra and not extra.upper().startswith("MAIL"):
                        premise_lines.append(extra)
                break
        if dba:
            break
    type_m = re.search(r"\b(?:PER|PON|PER/PRM|PRM|OFF-SALE|ON-SALE)\b", _cell(" ".join(cells[3:])))
    exp = re.search(r"(\d{2}/\d{2}/\d{4})", _cell(cells[3]) if len(cells) > 3 else "")
    all_text = _cell(" ".join(cells))
    return {
        "key": lic_num or all_text[:24],
        "license": lic_num,
        "url": "https://www.abc.ca.gov" + lic_link if lic_link else "",
        "dba": dba,
        "type": type_m.group(0) if type_m else "",
        "expires": exp.group(1) if exp else "",
        "address": " ".join(premise_lines)[:140],
        "status": "Pending",
        "raw": all_text[:300],
    }


def _is_bakersfield(row: dict) -> bool:
    return "BAKERSFIELD" in (row.get("raw") or "").upper()
