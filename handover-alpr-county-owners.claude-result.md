# Claude result for handover-alpr-county-owners.md

- ran: 2026-10-12 13:27 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

Phase A is designed and the driver is written and smoke-tested, but the 187-camera run itself has not happened; that is yours to run. Phase B is patched in and stays unbuilt until that data lands. Nothing is committed or pushed, the real workbench has not been run, and the suite is at 658 passing (your 634 plus 24 new).

## Things you should know first

- **Your five proof points are not known answers.** The probe read the first parcel returned, not the nearest, and the Tehachapi point is 769 m from any camera. Run through the real join:

  | Your label | Actually in | Your owner | Nearest-parcel owner |
  |---|---|---|---|
  | Ridgecrest | Ridgecrest | PERRIGE JOHN J | PERRIGE JOHN J (agrees) |
  | Taft | Maricopa | KERN SUNSET OIL CO | AERA ENERGY LLC |
  | Buttonwillow | Stallion Springs | MILANO LAND & CATTLE | DA/PRO RUBBER INC |
  | Mojave side | Tehachapi city | (none given) | LOOP RANCH LLC |

- **Never run `merge_master.py` or `merge_contacts.py` again.** They rebuild the master from scratch and would erase `match_quality`, the district lines and the 81 hand-researched contact records. The new driver appends rows instead.
- **The September join has three defects the new one fixes:**
  - It capped results at 20 parcels, and two of the 268 rows hit the cap.
  - It understated north-south distance by 18 percent.
  - It misread two-part parcels.
- **The ship commit cannot be source only.** It must carry `data/alpr/explorer_data.json` and `explorer_stats.json`, which the box writes inside a CI-owned tree. `data/snapshots/alpr_created.json` is dirty locally and should not go in.

## Phase A run order

From `work/alpr_ownership/`:

1. `python county_join.py all` — fetch, geocode, parcels, owners, city check, streets, then merge. I estimate 15 to 20 minutes. Re-run it after any interrupt.
2. `python county_join.py verify` — the acceptance check.
3. `python county_join.py recheck` — optional, report only: re-reads parcels and the roll for the 268 older rows.
4. `python fix_districts.py` — one older row still names Mike Gleason. Run it after `verify`, or the "older rows untouched" check fails.
5. `python rebuild_all.py` — without `--locations`, which would re-measure the 268 verified rows.

- **New driver, not `add_new_cameras.py`:** that script produced the 25 duplicates and cached failed geocodes as answers. `county_join.py` reuses the parcel layer, both roll readers, the road measurement, the city inventory query and the district table.
- **Resumability:** every stage is keyed by OSM node id and saved after each camera. A failed call is never stored, and `merge` refuses to run while any stage still owes an answer.
- **Touched in the workbench:** `build_explorer.py` only (backup at `build_explorer.py.bak_precounty`), to carry the town, the no-record list and two new counts.
- **Not for CI:** everything under `work/alpr_ownership/`.

Decisions you asked me to make:

- **Publishing before research:** yes, roll facts are enough. An unresearched owner carries `contact_status: not_researched`, and its record says the company and contact routes "have not been looked up yet".
- **Reusing existing research:** a company or agency the metro join already researched inherits it by exact name. A person never does.
- **Owner typing:** a doubtful name types as private, so no person's name is published by mistake.
- **Unjoined copy:** the hub now counts three states from the data — joined, looked up with no roll record, and not looked up — and says a different thing for each.

`verify` checks:

- every camera is joined or explicitly without a record, once;
- the 268 older rows are unchanged apart from the two new town fields;
- every new join is within 60 m and is the nearest parcel returned;
- the roll record is for the parcel asked about, and both reads name the same owner;
- every assessed value is one number.

Three reads are left to you: every new owner with its type, twelve seeded cameras against the assessor page, and Census town against geocoder address. The count on every surface is checked by the test suite after a local build.

## Phase B

Town is the Census boundary the camera's point is inside, or none. Counts today:

| Town | Cameras inside | Page |
|---|---|---|
| Shafter | 32 | yes |
| Ridgecrest | 31 | yes |
| Delano | 30 | yes |
| McFarland | 19 | yes |
| Oildale | 13 | yes |
| Tehachapi (city 7, Golden Hills 2, Bear Valley Springs 2, Stallion Springs 1) | 12 | yes |
| Rosedale | 11 | yes |
| Wasco | 10 | yes |
| Mojave 5, Taft 4, Maricopa 2, Rosamond 2, California City 0 | | no |

- **Threshold:** ten cameras to be listed, eight to keep the page. Below that the URL redirects to the hub.
- **Bakersfield:** no town page; the hub is its page and a second one would compete with it.
- **Layout:** spokes at `/surveillance/<town>/` using the hub's own explorer section, not the `/places/` template.
- **Per page:** title, H1, meta, a lede built from counts and street names, the map on the town's cameras, and an owner table (land owner, use, assessed value, supervisor, mapped date), plus breadcrumb and Dataset JSON-LD.
- **Wiring:** links both ways, sitemap entry automatic, and the Tehachapi places page links its town page.
- **Edge cases:** 43 of 455 cameras stand within 15 m of a boundary. A camera past the line appears under "Just outside the city limits" with its measured distance and is not counted as the town's.
- **Inert until data:** pages build only from ownership data that the county join wrote.

## Not verified

- The full run, including how many cameras come back with no roll record (0 of the 7 smoke cameras), and whether kerndata tolerates about 340 requests.
- `rebuild_all.py` at 455 rows: only `build_explorer.py` was run, on a copy.
- Town pages on real data beyond Shafter, Oildale and Rosedale, which I previewed from the smoke copy at 14, 13 and 11 cameras.
- The record script in a browser; it passes a syntax check only.
- Whether the tax-roll date the page prints is true for the older rows. It will show the run date while 268 rows hold the September read; `recheck` answers this.

One thing is already live and wrong: 15 older rows label agency land "Private titled parcel", so the hub's "privately titled" count includes them. New rows are labelled correctly; I left the old ones alone pending your call.

--- exit: 0 ---
