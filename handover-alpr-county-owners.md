# County cameras, their land owners, then town pages

Two owner instructions, in order:

1. "Should we fill in the cameras for the rest of the county? Maybe we should add the land owner
   info for each of those as well. Have claude help you work on that, but don't push it live until
   it is verified working and accurate."
2. "After its built, we can try to rank for 'tehachapi flock camera map' etc."

So: Phase A is the county camera list plus the land-owner join for every camera. Phase B is the town
pages that rank for those queries. Nothing goes live until it is verified.

## Where we are

Your widening is **verified by me, not taken on trust**: the patched fetch returns **455** elements,
**416** Flock-made, all 455 `surveillance:type=ALPR`, **270** in the metro and **185** outside it,
all 455 dated. The 68 extra Flock-made nodes in the metro are exactly as you said:
`surveillance:type=camera, camera:type=dome, camera:model=Condor`, so the filter stays. Full suite:
**634 pass**. Three of my numbers were wrong and yours are right (455 not 461, 185 not 191, the Flock
gap is domes).

Your changes are sitting uncommitted and unpushed, and that is deliberate: shipping the widening now
would put a page that leads with land ownership in front of readers with **187 of 455 cameras showing
"no owner record yet"**. The owner wants the owners filled in, so the two halves ship together.

## Phase A: the ownership join for all 455 (design it, I run it)

The workbench in `work/alpr_ownership/` already does this for the metro: `join_parcels.py` (nearest
parcel within 60 m from the Kern County assessor parcels layer), `owner_lookup.py` (owner of record
from the county tax roll), `owner_full_lookup.py`, `build_db.py` (`alpr_ownership.db`: cameras 268,
parcels 212, owners 174, entities 380, contacts 191), `build_explorer.py`, `rebuild_all.py` (writes
`data/alpr/explorer_data.json`, `explorer_stats.json`, `explorer.html`). `add_new_cameras.py` did the
same thing for 25 late cameras, so the pattern exists.

I proved the chain reaches the whole county today, one camera per town: Tehachapi 35.1318,-118.4468
(21 parcels within 60 m, owner of record ALMARDENI ISSA & AMAL, gas and mini-mart, assessed 265,244),
Ridgecrest 35.6513,-117.6878 (7 parcels, PERRIGE JOHN J, parking lot), Taft 35.0583,-119.3933
(5 parcels, KERN SUNSET OIL CO), Buttonwillow 35.0944,-118.6239 (5 parcels, MILANO LAND & CATTLE CO
LLC, grazing land 840,000), Mojave side 35.1382,-118.4682 (2 parcels).

What I need from you before I run it:

- **The run order**, script by script, and whether a new driver script is cleaner than editing
  `add_new_cameras.py`. Name what to reuse and what to touch.
- **Resumability.** 185 new cameras means 185 reverse geocodes (Nominatim policy is about one per
  second, so minutes), 185 parcel queries, 185 tax-roll lookups, plus entity work for owner names the
  metro never saw (oil and cattle companies). A run this size has to survive an interrupt and a
  re-run without duplicating rows. Say how.
- **What a page may publish before research finishes.** My view: the roll facts (owner of record, APN,
  assessed value, use code, district) are enough to publish, and the contact layer is optional
  enrichment that they existing weekly reminder can track. If you agree, say what `contact_status`
  carries for an unresearched owner so nothing reads as "we looked and found nothing" when we have
  not looked. Decide it, do not leave it to me.
- **The unjoined copy** you wrote ("the other 187 are mapped with no owner record yet") becomes wrong
  after this run, so it needs to follow the data, not a fixed number.
- **Bounds.** Say which scripts must NOT run in CI (the join is a box job) and what the acceptance
  check is for the run: parcel distance sanity, every new camera either joined or explicitly
  right-of-way, spot-checks against the assessor page, and the count on every surface.

I run it and hand you the output. You verify it, then we ship.

## Phase B: the town pages

The demand is real. "tehachapi flock camera map" is held by MyTownView with a 7-location page, and
behind it are aggregator clusters (areyouflocked.com, deflocktheusa.com, flockscanner.com,
flockcameralocations.com, flocklocations.com). Ridgecrest has live civic demand: the contract
pushback is covered by the local paper, southkernsol.org and citizenportal.

Those pages are lists of dots. Ours would carry, per camera, the owner of record, assessed value, use
code, supervisor district, mapped date, and our own map. That is the differentiator, and it comes out
of Phase A.

Design decisions I want from you:

- **Threshold.** Which towns clear the bar for their own page and which do not. A one-camera page is
  thin and would hurt us. Your own breakdown of the 185 gives the raw material (Ridgecrest 34,
  Delano 31, McFarland 25, Shafter 20, Mojave/Rosamond/California City 17, Tehachapi 15,
  Taft/Maricopa 13, Wasco 10, Grapevine 10, Buttonwillow 2, elsewhere 8), but a town page needs the
  town's own count, including the metro towns, so compute it from the joined data.
- **Where they live.** `/surveillance/<town>/` as spokes off the county hub, with links both ways.
  Check `/places/` and `/ownership/` first: reuse the layout if it fits rather than inventing a third.
- **Per page:** title, H1, meta, the town's camera list with owner rows, the map centered on the town,
  a short factual lede that a local would recognize, internal links, JSON-LD. Real data only, no
  caveat blocks, no keyword stuffing, and no page that a reader would call thin.
- **Sitemap and hub wiring**, plus the tests.

You can write the page patches before the data lands, as long as they stay inert until it exists.

## Constraints

- No push until verified, per the owner's instruction. When we do ship: source only with `[skip ci]`,
  push, then `gh workflow run deploy.yml`. `data/` is CI-owned. The join DB is a box artifact.
- Do not touch `build/emailer.py`, `tests/test_email_overnight_card.py`, or
  `C:\Users\tscac\Projects\wall-dashboard`.
- This box is Windows; project interpreter
  `C:/Users/tscac/Projects/BakersfieldBrief.com/.venv/Scripts/python.exe`; never `python -` with a
  heredoc here (exit 124). My probes: `hermes/cache/scratch/alpr_verify_fetch.py`,
  `alpr_far_parcel_probe.py`, `alpr_far_owner_probe.py`, `alpr_count_probe.py`.

## Deliverable

The Phase A run plan first, with the acceptance check, then the Phase B design and patches. Say
plainly what you could not verify.
