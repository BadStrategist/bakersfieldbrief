# Claude result for handover-alpr-count.md

- ran: 2026-10-12 13:05 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

# Verdict: 270 is right for the box, wrong for the heading

The patches are in the working tree, not committed. The full test suite passes, and a live dry run of the patched source returned 455 cameras.

## 1. What I measured (2026-10-12)

| Measure | Result |
|---|---|
| Shipped query, shipped box | **270** (240 Flock) — confirmed |
| Same tag filter, inside the real Kern County boundary (OSM relation 396494) | **455** (416 Flock) |
| Same filter, your county bbox | 461 — confirmed, but 6 of those are not in Kern County |
| `nwr["surveillance:type"="ALPR"]`, county boundary (no `man_made`) | 455, all nodes |
| Every `man_made=surveillance` node in the county | 663: 455 ALPR, 73 gunshot detectors, 70 cameras, 65 untyped |
| Flock-made in the shipped box | 308 — confirmed |

Your reading holds: the number is honest for the box, and the box is the Bakersfield metro, not the county the heading claims. Three of your details are off:

- **The county total is 455, not 461, so 185 are missing, not 191.** Four of the extra six sit on the Tulare side of the county line at Delano (lat 35.7905 to 35.7907). Two are near Gorman in Los Angeles County.
- **The Flock gap is 68, not 38.** 308 minus 270 mixes sets: 30 of the 270 are not Flock. The correct subtraction is 308 Flock minus 240 Flock plate readers.
- **The missing cameras are mostly the 99 corridor north and Ridgecrest:**

| Area | Cameras outside the box |
|---|---|
| Ridgecrest | 34 |
| Delano | 31 |
| McFarland | 25 |
| Shafter | 20 |
| Mojave / Rosamond / California City | 17 |
| Tehachapi | 15 |
| Taft / Maricopa | 13 |
| Wasco | 10 |
| Grapevine | 10 |
| Buttonwillow / I-5 | 2 |
| Elsewhere | 8 |

I did not re-run your three 429'd box queries. Instead I pulled all 663 surveillance nodes in the county and read their tags: no node outside the 455 mentions ALPR, LPR or a plate reader in any tag. Two extra probes for Flock objects with no `man_made` tag never completed, so that case is unmeasured.

No query makes the number "cameras installed". The page already prints that Flock's portal listed 462 for Bakersfield PD alone, against 240 Flock plate readers mapped in the metro.

## 2. Tag path: do not add `manufacturer~Flock`

All 68 extra nodes are `surveillance:type=camera`, `camera:type=dome`, `camera:model=Condor`. They are Flock video domes, not plate readers. The filter stays as it is.

One consequence for you to decide: the page is titled "Flock Camera Map" and says "240 Flock Safety cameras", while 308 Flock devices are mapped in the metro. I tightened the first FAQ answer to "Flock Safety license plate reader cameras". The stat tile ("Flock Safety units"), the lead callout and the meta description still say "Flock Safety cameras" for the plate-reader count. Showing Condors as their own layer is a separate feature I did not build.

## 3. Fix: widen to the county

**Query.** `build/sources/alpr.py` now asks for `(area:3600396494)`, the county's own boundary, by id. A box cannot do it because of the six out-of-county cameras. With the production budget, all three servers returned 455 nodes (225 KB). Two answers took about 26 s and gall took 4.8 s; my shipped-box query also took 23 s, so I read that as queueing on this IP, not query cost.

**Change-log baseline.** Every row now carries `scope`. When the last row has a different scope, that one week counts a camera as new only if it was first mapped on or after the last row's date. The rest go on the row as `widened: N`. The live dry run, on copies of the snapshots and log, produced: total 455, **+2 new**, widened 183, snapshot 270 → 455, zero undated cameras.
- The table prints that row as "Map widened to all of Kern County: 183 cameras already mapped outside the Bakersfield metro added to the total".
- I treated that as a change-log entry, not a caveat. If you read it as one, it is one branch in `_ids_cell` in `trackers.py`.
- The "new this week" and "last 4 weeks" counters use each node's own mapped date, so they never see the baseline as new. "Last 4 weeks" will read 15 county-wide.

**Unjoined cameras.** 268 of 455 are joined. The copy claimed a reason that is now false ("mapped after the county records snapshot"). It now states the fact with no reason and no promise:
- explorer subtitle: "the other 187 are mapped with no owner record yet"
- camera row: "Land owner not looked up yet."
- the ownership card and the JS camera record say the same.

The existing Monday reminder will report 187 unjoined until the join is extended on the box.

**Bakersfield answers.** The first two FAQ answers now give the metro share (270 / 240, computed from the same list by `metro_counts`) and the county total. Questions, title, h1 and h3 are unchanged. The "smaller scope than some commercial maps" line is gone.

**Files changed:**
- `build/sources/alpr.py` — query, scope, `metro_counts`, widening row, lost-town guard
- `build/builders/trackers.py` — copy, FAQ answers, change-log cell, tracker description
- `build/builders/alpr_page.py` — unjoined-camera copy
- `tests/test_alpr_freshness.py`, `tests/test_alpr_last4.py` — nine new tests
- Outside your scope list, because widening would otherwise leave them wrong:
  - `assets/js/alpr-explorer.js` — one sentence on the camera record
  - `build/build_all.py` — the summary text said "within the Bakersfield metro" and "Each camera is joined"
  - `build/tracker_card.py` — the email card picture stays framed on the metro; a county-wide frame turns Bakersfield into one dot
  - `AGENTS.md` — one paragraph in the ALPR section; it already had your uncommitted edits

**Files that need no change:** `home.py`, `numbers.py` and `static_pages.py` read the same total and name no area. The scope line in `static_pages.py` becomes true. The map already fits its view to every camera, so it opens on the whole county with clusters. `places.py` only gains: the Tehachapi page now gets its cameras.

**Not verified:** I did not build the site or look at the page in a browser. The county-wide opening view and the email card are worth a look after deploy.

## 4. What CI proves about coverage

- **Static:** a test pins the query to the county boundary id, with no box and no manufacturer filter.
- **Every build:** if a 0.2° cell that held five or more cameras on the last good list comes back empty, the fetch counts as failed. The page keeps the last good list and the freshness gate turns the run red. This catches a town dropping out, which the 60 percent count guard would miss (Ridgecrest is 34 of 455).
- **Limit:** a real mass deletion in one cell would stay red until someone removes `alpr_last.json`. The existing count guard has the same property.
- **Cannot be proven:** cameras nobody has mapped.

## Shipping

Commit source only with `[skip ci]`, push, then `gh workflow run deploy.yml`. The page shows 455 on that deploy.

The widening row lands on the next weekly run that has no row for its date yet. My checkout's last row is 2026-10-05, and I did not check whether today's run landed on origin. If it has not, a manual `weekly.yml` dispatch after the deploy writes the row today; if it has, the row lands next Monday and the table shows 270 for this week until then.

--- exit: 0 ---
