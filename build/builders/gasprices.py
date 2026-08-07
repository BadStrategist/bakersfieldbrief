#!/usr/bin/env python3
"""Gas prices page — /gas-prices/. Bakersfield metro averages from AAA,
refreshed each build. Falls back gracefully when the source is down."""
from __future__ import annotations

import html

from .. import common
from . import images
from . import page as page_mod


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = ""
    gas = sources.get("gas", {})

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Gas prices · AAA</p>
      <h1>Bakersfield gas prices</h1>
      <p class="lede">Current average prices in the Bakersfield metro, as reported by AAA —
      regular, mid-grade, premium, and diesel. Updated with every build.</p>
      <div class="meta"><span>Data as of <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>AAA Daily Fuel Gauge Report</span></div></div>
    </div>
    {images.figure("oil", rel)}
    {_prices(gas)}
    {_context(gas, rel)}
    """

    page = page_mod.render(
        title="Bakersfield gas prices — AAA averages | Bakersfield Daily Brief",
        desc="Current AAA average gas prices in Bakersfield, California: regular, mid-grade, premium, and diesel, with yesterday's averages for comparison.",
        canonical="/gas-prices/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "gas-prices" / "index.html", page)
    built.append("gas-prices/index.html")

    ctx.build_report["gas_prices"] = {
        "ok": gas.get("ok", False),
        "regular": (gas.get("current") or {}).get("regular"),
        "asof": gas.get("asof", built_iso),
    }
    return built


def _prices(gas: dict) -> str:
    if not gas.get("ok"):
        return ('<div class="card"><p class="note">AAA price data is unavailable this build '
                f'({html.escape(str(gas.get("error", "unknown")))}). Check back after the next '
                'build, or see the <a href="https://gasprices.aaa.com/?state=CA" rel="noopener">'
                'AAA California page</a> directly.</p></div>')

    cur = gas.get("current", {})
    yes = gas.get("yesterday", {})

    def row(label, key):
        c, y = cur.get(key), (yes or {}).get(key)
        delta = ""
        if c is not None and y is not None:
            d = round(c - y, 2)
            cls = "down" if d < 0 else ("up" if d > 0 else "flat")
            arrow = "▼" if d < 0 else ("▲" if d > 0 else "—")
            delta = f'<span class="gas-delta {cls}">{arrow} ${abs(d):.2f}</span>'
        today = f"${c:.4f}" if c is not None else "—"
        yest = f"${y:.4f}" if y is not None else "—"
        return (f"<tr><td>{label}</td>"
                f"<td class=\"gas-n\">{today}</td>"
                f"<td class=\"gas-y\">{yest}</td>"
                f"<td>{delta}</td></tr>")

    rows = "".join(row(l, k) for l, k in
                   (("Regular", "regular"), ("Mid-grade", "mid"),
                    ("Premium", "premium"), ("Diesel", "diesel")))

    return f"""
    <div class="card" style="margin-top:14px">
      <table class="gas-table">
        <thead><tr><th>Fuel</th><th>Today</th><th>Yesterday</th><th>Change</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p class="note">Source: <a href="https://gasprices.aaa.com/?state=CA" rel="noopener">AAA Daily Fuel Gauge Report</a> —
      metro average as reported by AAA. Station-level prices vary; this is the Bakersfield metro mean.</p>
    </div>"""


def _context(gas: dict, rel: str) -> str:
    cur = gas.get("current", {}) if gas.get("ok") else {}
    reg = cur.get("regular")
    lede = (f"Regular unleaded averages <strong>${reg:.4f}</strong> in Bakersfield today."
            if reg is not None else "AAA metro pricing is unavailable this build.")
    return f"""
    <section class="block">
      <div class="sign-head"><span class="tab">Why</span><h2>About these numbers</h2></div>
      <div class="card"><p>{lede}</p>
      <p>AAA surveys fuel prices across the metro and publishes the average. The Daily Brief
      re-publishes it as a quick reference — for the cheapest stations near you, AAA and
      GasBuddy list live station-level prices.</p>
      <p>Want to compare with the wider region? The <a href="{rel}grapevine/">Grapevine
      conditions</a> page covers the I-5 corridor, and our <a href="{rel}events/">events</a>
      page has what&rsquo;s on around town.</p></div>
    </section>"""
