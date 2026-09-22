"""Dump the live share-step DOM of the reels composer (no clicking, no publish).

Attaches to the existing CDP browser and reports, for every visible radio or
checkbox, the label of its enclosing row, so the platform-selection code can be
written against real selectors.

Run: .venv\\Scripts\\python.exe scripts\\brief_reel\\probe_share_rows2.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import publish_social as ps  # noqa: E402

DUMP = """() => {
  const out = {url: location.href, body: (document.body.innerText || '').slice(0, 3000), rows: []};
  const seen = new Set();
  for (const c of document.querySelectorAll('input, [role=radio], [role=checkbox], [role=switch]')) {
    const r = c.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) continue;
    // nearest ancestor that carries a label worth showing
    let node = c, label = '', depth = 0;
    while (node && depth < 8) {
      const t = (node.innerText || '').trim();
      if (t) { label = t.replace(/\\n+/g, ' | ').slice(0, 160); break; }
      node = node.parentElement; depth++;
    }
    const key = Math.round(r.x) + ':' + Math.round(r.y) + ':' + label;
    if (seen.has(key)) continue;
    seen.add(key);
    out.rows.push({tag: c.tagName, type: c.getAttribute('type'), role: c.getAttribute('role'),
                   aria_checked: c.getAttribute('aria-checked'), checked: !!c.checked,
                   aria_label: c.getAttribute('aria-label'),
                   x: Math.round(r.x), y: Math.round(r.y),
                   up: depth, label});
  }
  out.rows.sort((a, b) => a.y - b.y || a.x - b.x);
  return out;
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(ps.CDP, timeout=60000)
        page = ps.get_page(b)
        d = page.evaluate(DUMP)
        Path(ps.STATE_DIR / "share-rows-probe2.json").write_text(
            json.dumps(d, indent=2), encoding="utf-8")
        print("URL:", d["url"])
        print("---- visible controls ----")
        for r in d["rows"]:
            print(json.dumps(r))
        print("---- body text ----")
        print(d["body"][:2500])
        page.screenshot(path=str(ps.STATE_DIR / "share-rows-probe2.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
