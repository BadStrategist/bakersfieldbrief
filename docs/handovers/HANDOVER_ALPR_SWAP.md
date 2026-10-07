# Handover: update/rebuild bakersfieldbrief.com/surveillance/ (built, NOT published)

Repo: `C:\Users\tscac\Projects\BakersfieldBrief.com`. Read this whole file before touching anything.

## 0. The goal, stated once

**We are updating and rebuilding the existing `/surveillance/` page. That is the only ALPR page.**
There is no second page, no `/alpr-explorer/`, no separate "Flock camera map" route, now or later.
Every ALPR, Flock and camera-map url on this site is `/surveillance/` and nothing else.

**Start by studying the live page:** `https://bakersfieldbrief.com/surveillance/`. That is the target
and the thing that must not regress. Fetch it, read it top to bottom, and study its structure, copy,
FAQ, schema and internal links before you read or change any source file. Section 3 records what it
holds today, so you can compare.

The staged work adds a land-ownership explorer to that page: the reader can see who owns the land
each camera stands on or beside. Right now the staged build ALSO publishes that explorer as its own
page, which breaks the rule in the paragraph above. Fixing that is item 1 of section 6.

## 1. Repository and deploy facts

- `git log -1`: `a99298b overnight report 2026-09-22`.
- `git status -sb`: `## main...origin/main [behind 1]`. Pull before you push.
- Nothing is staged. The live page still serves the old Leaflet map.
- A push to `main` triggers `.github/workflows/daily.yml`: `python build/build_all.py`, then `pytest`
  as a hard gate, then a Cloudflare Pages deploy of `site/`.
- `site/` and `work/` are gitignored. The repo holds sources plus `data/alpr/`, never built HTML.
- Local build check: `python build/build_all.py --skip-sources`, then serve `site/` on port 8100.

## 2. What the change is

The Leaflet map in the middle of `/surveillance/` is replaced by the land-ownership explorer: 268
cameras joined to 174 owners of record across 212 tax-roll parcels, with tabs for Owners, Cameras,
Parcels and Sources, per-record views at `#owner/<n>`, `#camera/<id>` and `#parcel/<n>`, and the
public source printed for every value. The page keeps its own title, lede, FAQ, headings, schema and
link graph. The explorer lives inside the page. It is not a page of its own.

The explorer's HTML is generated as a standalone document by `work/alpr_ownership/build_explorer.py`
and written to `data/alpr/explorer.html`. How that content reaches `/surveillance/` is the open
decision in section 6, item 1.

## 3. The live page you are protecting

Live `https://bakersfieldbrief.com/surveillance/`, verified today:

| Element | Live value |
|---|---|
| h1 | `Flock Camera Map — Bakersfield` |
| h2 | `Newest cameras` (the only h2) |
| h3 | `Flock & ALPRs · Kern County`, `What this tracker shows` |
| Stats row | 268 ALPR cameras mapped, 239 Flock Safety units, 2026-09-21 newest mapped on OSM, +15 new cameras, last 4 weeks |
| Lede | "See every license plate reader in Bakersfield on a live map — 239 Flock Safety cameras and 268 total ALPR units mapped in the metro, with facing direction, newest-camera highlights, and a weekly change log from OpenStreetMap." |
| FAQ | 4 visible questions, listed in section 4 |
| FAQPage schema | 4 `mainEntity` entries, matching the visible pairs |
| Other JSON-LD | `NewsMediaOrganization`, `WebSite`, `WebPage` |
| Canonical | `https://bakersfieldbrief.com/surveillance/` |
| Internal page links | none (icons and manifest only) |
| Map | `#alpr-map` div plus Leaflet JS |
| Newest list | 66 list items |

`https://bakersfieldbrief.com/alpr-explorer/` returns **404** live. Nothing from this work is deployed.

## 4. What must survive, exactly

Do not lose or reword these. Additive changes only.

1. The h1, the h2 and both h3 strings, verbatim.
2. The four FAQ questions, verbatim, with their answers:
   - How many Flock cameras are in Bakersfield?
   - Where are the Flock cameras in Bakersfield?
   - Are Flock cameras legal in California?
   - How long do Flock cameras keep data?
3. The FAQPage JSON-LD block, with every visible question present in `mainEntity`. A question added
   to the visible FAQ needs its schema twin in the same change.
4. The canonical url, the og and twitter tags, and the existing JSON-LD types.
5. The internal link graph. No link may point at a second ALPR page, because there is none.
6. The numbers: 268 cameras, 239 Flock Safety, 174 owners, 212 parcels, 92 contactable owners. Every
   surface that states them must agree; see section 5.

Field-by-field live-versus-staged comparison:
`work/alpr_ownership/audit_opus5/seo_live_vs_staged.json`.

## 5. Copy and data rules already settled

- Counts are single-sourced. The explorer build writes `data/alpr/explorer_stats.json`;
  `_explorer_stats()` in `build/builders/trackers.py` reads it back for the lede, the ownership card
  and the FAQ schema. A missing file falls back to `n/a`, never to a typed number or a dash.
- Owner copy says "at or beside their land", or "the nearest parcel". Never "the parcel under it".
  Reason: 202 of the 268 cameras stand beside the joined parcel, not on it.
  `audit_opus5/verify_swap.py` asserts that claim is absent.
- Coordinates are published, never withheld: Lat and Lon columns in the CSV, city and named-owner
  tables in the Markdown, PDF headers, and the OpenStreetMap node url for each camera.
- The broker filter is `publish_filter.py`: match brokers by whole hostname (`homes.com` versus
  `castlecookehomes.com`), drop a broker url rather than rewriting it, and suppress a whole contact
  route when a people-search source backs it. It applies to the page, CSV, MD, PDF and DB.
- No em dashes in copy you write. Use commas, colons, periods or parentheses.
- Wheel zoom is off on all three Leaflet maps in the explorer. A wheel over the explorer must scroll
  the host page; that is asserted (host `scrollY` 1169 to 1221 desktop, 1406 to 1510 phone).

## 6. What is wrong now, and what to do about it

### 1. The second page must go (blocking, fix before push)

The staged build publishes `/alpr-explorer/` as its own indexable page. Proof:

- `<loc>https://bakersfieldbrief.com/alpr-explorer/</loc>` sits in `site/sitemap.xml`.
- The page has a self-canonical, a Dataset JSON-LD block, and no noindex.
- Four built pages link to it as a page: `index.html` (home), `surveillance/index.html`,
  `trackers/index.html`, and itself.

That contradicts section 0. Pick one way to comply, then remove the sitemap entry and every link
that treats it as a page:

- **Option A, the frame stays, the url stops being a page.** Serve the app from an asset path such as
  `/assets/alpr/explorer.html`, put `<meta name="robots" content="noindex,nofollow">` on it, keep it
  out of the sitemap, add a `robots.txt` Disallow, and reference it only as the frame `src`. Keeps the
  767 KB app off the page's critical path and keeps two stylesheets from fighting in one document.
  Cost: a second url exists, as an asset rather than a page.
- **Option B, inline it into `/surveillance/`.** One document, one url, nothing else to explain.
  Cost: the explorer's CSS and JS must be scoped so they cannot reach the host page's styles, and the
  767 KB payload joins the page's LCP path unless it is deferred.

Whichever you choose, the checks are: `grep -c alpr-explorer site/sitemap.xml` returns 0, no built
page links to it as a page, and `/surveillance/` is the only ALPR url a crawler can reach. Confirm
the crawler's view in Search Console after deploy instead of assuming how a frame is treated.

### 2. Duplicate stats row (pre-existing)

`/surveillance/` renders the four-number stats row twice. The pre-swap backup
(`audit_opus5/pre_surveillance_swap/index.html`) has two as well, so this predates the work. Safe to
collapse to one.

### 3. The frame repeats the numbers

The explorer carries its own header, chips and "Data as of" line, so the counts appear twice on
screen. They agree. Hiding the explorer header when it is embedded is the clean fix.

### 4. One map feature was lost

The old map's "highlight newest (28 days)" toggle went with the map. The newest-camera list survives,
and the stat row still shows `+15 new cameras, last 4 weeks`.

### 5. One pre-existing failing test, unrelated

`tests/test_kern_overnight.py::TestGeo::test_block_precision_known_street` fails on this box: the
committed `data/geo_cache.json` has no entry for that address, so the test makes a live Nominatim
query and gets street precision instead of block. Nothing in this work touches geocoding, and CI is
green (last six runs). Do not edit the cache to silence it.

### 6. Local drift warning

Running the full `pytest` locally rewrites `data/geo_cache.json`. Restore it with
`git checkout -- data/geo_cache.json` before committing anything.

### 7. Deferred to the owner (not for the review pass)

Two structural changes are decided and queued AFTER the review pass that fixes mistakes and design.
Leave them alone unless you find they block you:

1. Remove the second page entirely, per section 6 item 1.
2. Remove the dead weight. Once the explorer sits on the page, the old Leaflet map code and its
   `webmcp` hook are dead on `/surveillance/` and come out. Confirm page by page that nothing else
   on the site imports them before deleting anything, because other pages may borrow the same code.

## 7. Files

Commit these, they are the change:

| File | Role |
|---|---|
| `build/builders/trackers.py` | builds `/surveillance/`: the explorer slot, `_explorer_stats()`, the added FAQ entries, the ownership card, title and description |
| `assets/css/deflock.css` | the explorer slot's height rule |
| `build/build_all.py` | runs the `alpr_explorer` builder after `map` |
| `build/builders/daily.py` | home card for the ownership data |
| `build/builders/alpr_explorer.py` | the explorer builder (untracked) |
| `data/alpr/explorer.html`, `data/alpr/explorer_stats.json` | the app and its counts sidecar, read by the build (untracked) |
| `tests/test_page_asi.py` | guards a JS statement-truncation bug class (untracked) |

Do not commit unrelated working-tree drift: `email/`, `data/briefs_archive.json`,
`data/build_report.json`, `assets/img/weather-card.jpg`, `scripts/brief_reel/diag_*.py`, `AGENTS.md`,
`proc_check.ps1`, `transcripts/`.

The ALPR pipeline lives in `work/alpr_ownership/` (gitignored): `build_explorer.py` emits the app,
`rebuild_all.py` runs the builders and three gates, `publish_filter.py` scrubs contacts,
`master_rows_contacts.json` is the data the app is built from, and `make_pdf.py`, `build_db.py`,
`export_printout.py` and `build_report.py` produce the downloads.

## 8. Commands

```
# 1. explorer pipeline: builders then three gates (starts its own server on 8099)
cd work/alpr_ownership && python rebuild_all.py      # must end "rebuild_all: clean"

# 2. the site build
cd ../.. && python build/build_all.py --skip-sources # expect "DONE - 90 html pages"

# 3. this work's verifier: 41 checks, 0 failures
python work/alpr_ownership/audit_opus5/verify_swap.py

# 4. served-surface interaction gate (serve site/ on 8100 first)
cd site && python -m http.server 8100 --bind 127.0.0.1 &
cd .. && W=1440 H=900 python work/alpr_ownership/audit_opus5/gate_surface.py http://127.0.0.1:8100/surveillance/ desktop
W=390 H=844 python work/alpr_ownership/audit_opus5/gate_surface.py http://127.0.0.1:8100/surveillance/ phone

# 5. the repo tests
python -m pytest -q -o addopts=""
```

Gate reports: `work/alpr_ownership/audit_opus5/gate_{desktop,phone}.json`. Screenshots:
`audit_opus5/shots_gate/`. `cdp_site.py` in that directory runs any JS probe file against any url.

## 9. Design work you are free to do

The front end can improve. Keep the explorer on the page and keep every rule in section 4. Useful
levers:

- The page's own spacing and rhythm around the explorer slot: `assets/css/deflock.css`.
- The explorer's palette and type: `work/alpr_ownership/build_explorer.py`, one file with inline CSS
  and JS, emitted from `master_rows_contacts.json`. Any change there means rerun `rebuild_all.py`
  (it rewrites `data/alpr/explorer.html` and the stats sidecar), then `build_all.py --skip-sources`,
  then the gates.
- The page's copy blocks live in `build/builders/trackers.py`, in the `build_alpr` section.

House style: light palette only, never a `prefers-color-scheme` flip (the owner runs Windows dark
mode, so a light-only bug reads as a dark-mode pass). Real screenshots, never AI art. No em dashes.

## 10. Ship

```
git pull --rebase
git add build/builders/trackers.py build/builders/alpr_explorer.py build/build_all.py \
        build/builders/daily.py assets/css/deflock.css data/alpr tests/test_page_asi.py
git commit -m "surveillance: land ownership explorer on the page; FAQ and schema kept"
git push
```

Do not push until section 6 item 1 is resolved. Then verify the deployed page, not the source: fetch
`https://bakersfieldbrief.com/surveillance/` once the workflow finishes, re-run the section 3
comparison against it, and confirm no second ALPR url is reachable by a crawler.