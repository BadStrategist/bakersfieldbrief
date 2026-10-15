# Is the ALPR number on /surveillance/ correct? Verify it, then decide the fix

Owner's question, verbatim: "So is the number of ALPRs on our tracker correct? Ask claude to verify".

You are the verifier. Do not take my numbers on trust: re-measure them yourself, then give a verdict
and a fix. I am the one who will ship it.

## What the tracker says and where the number comes from

- Page: `/surveillance/`. The explorer's heading is "Flock & ALPRs &middot; Kern County", with
  "270 cameras on this map" (the live build shows 270). The hero and the map agree.
- Query, `build/sources/alpr.py`: `node["man_made"="surveillance"]["surveillance:type"="ALPR"]`
  inside bbox `35.20,-119.25,35.55,-118.80`, `out meta;`.
- Other surfaces that print the same number: the home card (`build/builders/home.py:638`,
  "{total} cameras mapped."), the weekly numbers article (`build/builders/numbers.py:140`),
  and the trackers page (`build/builders/trackers.py:175`, "ALPR cameras mapped").
- The site's own scope line (`build/builders/static_pages.py:30`): it covers "the City of
  Bakersfield, Kern County, and the communities along State Route 99 from Wheeler Ridge to the
  Kern River Canyon".

## What I measured, 2026-10-12, with the fixed query budget

All queries carried `[timeout:25][maxsize:33554432]`. Three of the nine hit a 429 (my own probe
traffic), so the missing cases need a re-run with a pause, not a conclusion.

| Query | Box | Result |
|---|---|---|
| Shipped query, shipped bbox | 35.20,-119.25,35.55,-118.80 | **270** (2.8 s) |
| Shipped query, whole county | 34.78,-120.30,35.85,-117.55 | **461** (1.9 s) |
| `nwr["surveillance:type"="ALPR"]`, whole county | same | **461** (1.8 s) |
| Any `man_made=surveillance` + any `surveillance:type`, county | same | **604** (2.3 s) |
| `nwr["man_made"="surveillance"]["manufacturer"~"Flock",i]`, shipped bbox | shipped | **308** (2.8 s) |
| Any `man_made=surveillance`, shipped bbox | shipped | **467** (22.6 s) |
| `nwr["surveillance:type"="ALPR"]` (no man_made), shipped bbox | shipped | 429, not measured |
| `camera:type~ALPR`, shipped bbox | shipped | 429, not measured |
| `surveillance=ALPR`, shipped bbox | shipped | 429, not measured |

So inside the shipped box the ALPR filter is not over-counting (270 of 467 surveillance nodes). The
gap is the box, not the tag: **191 of the 461 county-wide mapped cameras are outside it.**

Those 191 are not scattered noise. They are towns with their own agencies:

- Taft / Maricopa (about 35.03 to 35.19, -119.45 to -119.36)
- Buttonwillow and the I-5 corridor
- Tehachapi and the Tehachapi Pass (35.11 to 35.15, -118.62 to -118.40)
- Mojave and Rosamond-side, Ridgecrest ("Ridgecrest Police Department", 35.65,-117.69)
- the Delano / north county side, lon to -117.65

And the ALPR filter looks like it misses some in-box cameras: `manufacturer~Flock` finds **308** in
the same box where `surveillance:type=ALPR` finds 270. That is a real 38-camera difference and needs
your judgement, not a blanket OR: Flock also sells non-ALPR hardware (Raven audio detection), so
check what those 38 nodes actually carry before widening the filter.

## Outside corroboration that the county runs cameras outside the metro box

- EFF Atlas of Surveillance, Kern County Sheriff's Department: "As of April 2024, the Kern County
  Sheriff's Office operates 30 Flock Safety automated license plate readers"
  (atlasofsurveillance.org/a/CA0150000ALPR).
- CEQA notice 2026040438, public agency Kern County: "Flock Safety Automated License Plate Reading
  (ALPR) Camera Installation Project" (ceqanet.lci.ca.gov/2026040438).
- KGET: Ridgecrest's police chief is amending the city's Flock contract.
- GovTech: "License plate-reading cameras are springing up across Bakersfield and Kern County."

So the missing 191 are real deployments, not mapper noise.

## The question to answer

1. **Verdict.** Is 270 correct? My reading: the number is honest for the area the query covers, and
   the area is the Bakersfield metro box, not the county the heading claims. Confirm or refute with
   your own measurements, and say plainly if you find I am wrong.
2. **Tag path.** Should the query accept a second path (`manufacturer~Flock`) or is that over-counting?
   Check the 38 nodes' own tags before answering.
3. **Fix, and which one.** Either widen the query to the county (my preference: the page's whole value
   is who watches this county and whose land they stand on, so 41 percent of the county missing is the
   wrong scope), or relabel every surface to the area actually covered. If you widen, you own these
   consequences:
   - The weekly change log must not print a fake "+191 newly mapped this week". Design the baseline
     (advance the snapshot without a change-log row, or emit the row as a coverage expansion), and
     keep "newly mapped" meaning what it says.
   - The land-ownership join is manual on this box; 191 more cameras is 191 more parcels that join
     later, so say how the page should read while a large share is unjoined.
   - The map's own view and zoom, the home card, `/numbers/`, `/trackers/` and the tests all read the
     same source. Name every file.
4. **What CI proves.** The freshness gate proves the list is today's. It proves nothing about
   coverage. If coverage needs its own check, say what it is and where it runs.

## Constraints

- No staleness or coverage disclaimer on the page: the owner has ruled that out as tacky and not
  trust building. Fix the data or fix the label, never add a caveat block.
- Every surface that prints the number must print the same number, from one source.
- Source-only changes ship with `[skip ci]`, then `gh workflow run deploy.yml`. Generated data under
  `data/` is CI-owned; do not hand-edit it.
- Scope: `build/sources/alpr.py`, `build/builders/alpr_page.py`, `home.py`, `numbers.py`,
  `trackers.py`, `static_pages.py`, `scripts/check_alpr_fresh.py`, the workflows and their tests. Do
  not touch `build/emailer.py`, `tests/test_email_overnight_card.py`, or
  `C:\Users\tscac\Projects\wall-dashboard`.
- This box is Windows; the project interpreter is
  `C:/Users/tscac/Projects/BakersfieldBrief.com/.venv/Scripts/python.exe`. Never `python -` with a
  heredoc here (exit 124). My probe was
  `hermes/cache/scratch/alpr_count_probe.py`; re-run it with pauses between queries to dodge the 429s.

## Deliverable

First the verdict with the numbers you measured, then the fix design (files, changes, what proves it),
then patches.
