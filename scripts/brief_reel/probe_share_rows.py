"""Reach the reels composer Share step WITHOUT publishing, then dump the
"Share to"/"Post to" rows so the platform selection code can be written against
the real DOM. Publish is never clicked here.

Run: .venv\\Scripts\\python.exe scripts\\brief_reel\\probe_share_rows.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import publish_social as ps  # noqa: E402

PROBE = """() => {
  // Every visible text node region that mentions a platform label inside a
  // section whose header reads "Share to" / "Post to" / "Also share".
  const out = {sections: [], rows: [], toggles: []};
  const all = [...document.querySelectorAll('div')];
  for (const d of all) {
    const own = [...d.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join(' ').trim();
    if (!own) continue;
    if (/^(Post to|Share to|Also share|Share on|Publish to)/i.test(own)) {
      out.sections.push({label: own.slice(0, 60), text: (d.innerText || '').slice(0, 400)});
    }
    if (/^(Facebook|Instagram)$/.test(own)) {
      // walk up until an ancestor carries a control
      let node = d, ctrl = null, depth = 0;
      while (node && depth < 6) {
        const c = node.querySelector('input[type=checkbox],input[type=radio],[role=checkbox],[role=switch],[aria-checked],input');
        if (c) { ctrl = c; break; }
        node = node.parentElement; depth++;
      }
      out.rows.push({
        label: own,
        depth,
        row_text: (d.parentElement ? d.parentElement.innerText : '').slice(0, 200),
        ctrl: ctrl ? {
          tag: ctrl.tagName, type: ctrl.getAttribute('type'),
          role: ctrl.getAttribute('role'),
          aria_checked: ctrl.getAttribute('aria-checked'),
          checked: !!ctrl.checked,
          aria_label: ctrl.getAttribute('aria-label'),
        } : null,
      });
    }
  }
  for (const c of document.querySelectorAll('input, [role=checkbox], [role=switch], [aria-checked]')) {
    const r = c.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      out.toggles.push({tag: c.tagName, role: c.getAttribute('role'),
                        aria_checked: c.getAttribute('aria-checked'),
                        checked: !!c.checked, aria_label: c.getAttribute('aria-label'),
                        y: Math.round(r.y), x: Math.round(r.x)});
    }
  }
  return out;
}
"""


def main() -> int:
    date = ps.today_la()
    assets = ps.build_assets(date)
    if assets is None:
        print("no assets for", date)
        return 3
    reel, brief_json, caption = assets
    print("reel:", reel, "| caption head:", " ".join(caption.split())[:60])
    s = ps.ensure_session()
    print("browser session:", s)
    if s == "unavailable":
        return 4
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(ps.CDP, timeout=90000)
        page = ps.get_page(b)
        res = ps.publish_reel(page, reel, caption, dry_run=True)
        print("reel publish (dry run):", json.dumps(res)[:300])
        if not res.get("ok"):
            return 1
        data = page.evaluate(PROBE)
        Path(ps.STATE_DIR / "share-rows-probe.json").write_text(
            json.dumps(data, indent=2)[:20000], encoding="utf-8")
        page.screenshot(path=str(ps.STATE_DIR / "share-rows-probe.png"), full_page=False)
        print(json.dumps(data, indent=2)[:4000])
        print("saved:", ps.STATE_DIR / "share-rows-probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
