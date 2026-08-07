#!/usr/bin/env python3
"""build_all.py — the whole site build.

  python build/build_all.py [--skip-sources] [--no-llm] [--alpr-change]

Pipeline:
  1. run every source module (isolated; failures recorded, never fatal)
  2. build every section from the collected data
  3. copy static assets into site/
  4. write robots.txt, sitemap.xml, CNAME
  5. write data/build_report.json (used by the site footer + the workflow)

--alpr-change: record the ALPR weekly change-log entry (used by the weekly job).
--no-llm:       force the LLM fallback path (local testing without a key).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import common  # noqa: E402
from build.sources import SOURCES  # noqa: E402
from build.builders import (daily, cityhall, openings, trackers, static_pages,
                            places, guide, grapevine, events, feed,
                            numbers, letters, gasprices, weatherpage)  # noqa: E402
from build.builders import page as page_mod  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sources", action="store_true", help="reuse last build report data")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM calls entirely")
    ap.add_argument("--alpr-change", action="store_true", help="record ALPR weekly change log")
    ap.add_argument("--guide", action="store_true", help="run the Thursday Weekend Guide build (scrapes venue whitelist)")
    args = ap.parse_args()

    if args.no_llm:
        import os
        os.environ.pop("LLM_API_KEY", None)

    # ---------------------------------------------------------- clean
    shutil.rmtree(common.SITE, ignore_errors=True)
    common.SITE.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- sources
    ctx = types.SimpleNamespace(today=common.today_pacific(), build_report={},
                                guide=args.guide)
    results = {}
    cache_file = common.DATA / "source_cache.json"
    if args.skip_sources:
        if cache_file.exists():
            results = json.loads(cache_file.read_text(encoding="utf-8"))
            common.log("reusing cached source data (--skip-sources)")
        else:
            common.log("--skip-sources but no cache found; fetching anyway")
    if not results:
        for name, mod in SOURCES.items():
            try:
                res = mod.run(ctx, record_change=args.alpr_change) if name == "alpr" else mod.run(ctx)
            except Exception as e:  # noqa: BLE001 - isolation guarantee
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            results[name] = res
            status = "ok" if res.get("ok") else ("stub" if name == "blocked" else "FAIL")
            common.log(f"source {name}: {status}")
        cache_file.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------- builders
    ctx.statusbar = page_mod.build_statusbar(results.get("weather"), results.get("escribe"))
    builders = [("daily", daily), ("cityhall", cityhall),
                ("openings", openings), ("trackers", trackers),
                ("places", places), ("guide", guide),
                ("grapevine", grapevine), ("events", events),
                ("feed", feed), ("numbers", numbers), ("letters", letters),
                ("gasprices", gasprices), ("weatherpage", weatherpage),
                ("static", static_pages)]
    for bname, bmod in builders:
        try:
            files = bmod.build(ctx, results)
            common.log(f"builder {bname}: {len(files)} files")
        except Exception as e:  # noqa: BLE001
            import traceback
            common.log(f"builder {bname} FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()

    trackers.build_hub(ctx, results)
    common.log("builder trackers-hub done")

    # ---------------------------------------------------------- assets
    for src in ("css", "js", "fonts", "vendor", "img"):
        shutil.copytree(common.ASSETS / src, common.SITE / "assets" / src, dirs_exist_ok=True)
    common.log("assets copied")

    # ---------------------------------------------------------- robots / sitemap / CNAME
    _robots()
    _sitemap()
    (common.SITE / "CNAME").write_text("bakersfieldbrief.com\n", encoding="utf-8")

    # ---------------------------------------------------------- report
    report = {
        "built_at": common.now_pacific().isoformat(timespec="seconds"),
        "sources": {k: {"ok": v.get("ok", False), "error": v.get("error", ""),
                        **({} if v.get("ok") else {})}
                    for k, v in results.items()},
        "section": ctx.build_report,
    }
    (common.DATA / "build_report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8")

    n_pages = len(list(common.SITE.rglob("*.html")))

    # custom domain record for Pages (repo root CNAME → built artifact)
    _cname = common.ROOT / "CNAME"
    if _cname.exists():
        (common.SITE / "CNAME").write_text(_cname.read_text(encoding="utf-8").strip() + "\n", encoding="utf-8")

    common.log(f"DONE — {n_pages} html pages in site/, report at data/build_report.json")
    if not all(v.get("ok", False) for k, v in results.items() if k != "blocked"):
        failed = [k for k, v in results.items() if not v.get("ok", False) and k != "blocked"]
        common.log(f"NOTE — sources with failures (site still builds): {failed}")


def _robots():
    common.write(common.SITE / "robots.txt", """User-agent: *
Allow: /
Sitemap: https://bakersfieldbrief.com/sitemap.xml
""")


def _sitemap():
    urls = []
    for p in common.SITE.rglob("index.html"):
        rel = p.relative_to(common.SITE).as_posix()
        rel = rel[: -len("index.html")]
        urls.append(f"https://bakersfieldbrief.com/{rel}")
    urls += ["https://bakersfieldbrief.com/"]
    urls = sorted(set(urls))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"  <url><loc>{u}</loc></url>")
    xml.append("</urlset>")
    common.write(common.SITE / "sitemap.xml", "\n".join(xml) + "\n")


if __name__ == "__main__":
    main()
