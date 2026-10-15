# Claude result for handover-alpr-town-seo.md

- ran: 2026-10-12 16:37 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

# ALPR town pages: audit for a top-3 goal

The fixes from the 15:48 run are finished and reviewed on disk; nothing is committed or pushed. `pytest -q` is green, and a local `--no-llm` build renders all eight pages with the new blocks. The fixes are not on the live site yet, so every "after" figure below is from the local build, not deployed HTML.

Nobody can promise top 3. My verdict per page:

| Page | Cameras | Top 3 for "<town> flock camera map"? | Main blocker |
|---|---|---|---|
| Tehachapi | 12 | Plausible, not likely soon | MyTownView holds position 1 with an older, linked page |
| Ridgecrest | 31 | Plausible for map and location queries; not for "ridgecrest flock cameras" | That query is a news SERP |
| Delano | 30 | Plausible | Name collision with Delavan, Wisconsin |
| Shafter | 32 | Plausible | Atlas of Surveillance and KGET hold the "license plate readers" query |
| McFarland | 19 | Plausible | Generic national map tools |
| Wasco | 10 | Uncertain | Results are not local at all, which suggests little search demand |
| Oildale | 13 | Likely for its own query | Little demand; no competitor names the town |
| Rosedale | 11 | Unlikely for "rosedale flock cameras" | Google reads it as Bakersfield; news and the Atlas hold it |

The eighth live page is Shafter (32 cameras), which the handover table left out.

## What the on-disk work changes

- **Meta description:** trimmed from 222 to 226 characters to 138 to 153, so it shows whole. This helps click-through; it is not a ranking factor.
- **`FAQPage`:** added to every town page, with four or five questions answered from the build's data. The visible block and the schema node come from one list, so they cannot differ. Google rarely shows FAQ rich results for non-government sites now; the value is the visible text that matches "does <town> have flock cameras" and "how many".
- **Sibling links:** each town page now links the other seven with "<Town> Flock camera map" anchors, plus the hub's `#towns` table. Distinct internal link targets go from 8 to 36 or 37.
- **Heading order:** the explorer title is an `h2` on town pages (it was an `h3` straight after the `h1`). The hub keeps its `h3`.
- **Public records block:** on Tehachapi, Ridgecrest, Delano and Shafter, from `build/alpr_town_records.json`. Each record is a word-for-word quote with a link, and the page prints the mapped count beside the record's number.
- **Brief to town link:** a brief links a town's map when one paragraph names the town and a plate-reader word. The 2026-10-08 brief, which ranks third for "ridgecrest flock cameras", now links `/surveillance/ridgecrest/` first.
- **Existing JSON-LD:** every node the pages had is kept.

## The public records, checked today

| Town | Record | Record's number | Mapped inside | Quote checked against |
|---|---|---|---|---|
| Tehachapi | Police department grant application, BSCC, July 6, 2023 | 16 | 7 in the city | The PDF text, all three quotes exact |
| Tehachapi | Sheriff's Notice of Exemption, CEQAnet 2026040438 | one pole | point is inside Golden Hills | The CEQAnet page; sentence and coordinates match |
| Delano | BSCC funded project summaries | 25 | 30 | The PDF text, exact |
| Ridgecrest | Atlas of Surveillance entry, February 2024 | 24 | 31 | The Atlas page, exact |
| Ridgecrest | KGET headline on the contract change | none | n/a | Not fetched: KGET returns 403 to this box |
| Shafter | Atlas of Surveillance entry, 2024 | 25 | 32 | The Atlas page, exact |

- The KGET headline matches what our own 2026-10-08 brief carries, but I could not read the KGET page itself.
- The Tehachapi record is labelled as an application; the BSCC funded summaries do not name the department, and the page says so.
- The differing counts are handled in one sentence: a record is what an agency asked for or was authorized; the map is what volunteers found, for any operator. Ridgecrest's 31 includes 3 that OpenStreetMap tags to Home Depot and 7 with no operator tag.

## Query set and who holds it now

Searched today through the web search tool, which shows who occupies the results, not exact Google positions.

| Query | Current occupiers | Type |
|---|---|---|
| tehachapi flock camera map | MyTownView, areyouflocked, BSCC PDF, CEQAnet (your search) | Thin map pages and primary records |
| does tehachapi have flock cameras | Tehachapi News (police chief on Flock), train-cam pages | Local news |
| ridgecrest flock cameras | KGET via NewsBreak, ground.news, our 2026-10-08 brief (your search) | News |
| ridgecrest flock camera map | Flock Finder article, a "DeFlock Ridgecrest" change.org petition, an OSM user history | No local map page |
| delano flock cameras locations | Delavan, Wisconsin news; Atlas of Surveillance Delano entry | Wrong town, then a record |
| shafter license plate readers flock cameras | Atlas of Surveillance, KGET (council approves expansion) | Record and news |
| mcfarland ca flock camera map | National map tools, KGET crime story | Generic |
| wasco flock cameras license plate readers | City pages from other states, national explainers | Not local |
| oildale flock camera map | National explainers | Not local |
| rosedale bakersfield flock cameras alpr | Bakersfield news, Atlas of Surveillance (Bakersfield police) | Bakersfield |

I did not run "<town> ALPR" or "<town> surveillance cameras" for every town.

## On-page audit

- **Sound already:** canonical, one `h1`, title length (49 to 54), sitemap entry, crawlable server-rendered tables.
- **Depth:** 1,591 words (Rosedale) to 3,747 (Ridgecrest) after the fixes. The per-camera ownership table is the content no competitor has; MyTownView admits 7 locations for Tehachapi where we list 12 with owners.
- **Doorway risk:** low for the four pages with records, because their data and sources differ. Wasco, Oildale and Rosedale share the same template sentences with only the numbers and streets changed, and have no record block. They are the thinnest of the set.
- **Keyword counts:** "flock" at 41 to 75 per page is not a problem; it is mostly the table's Maker column. No change made.
- **Hub's "What is complete, and what is not" block:** neutral for ranking. It is on the hub, not the town pages, and it is honest scope copy that MyTownView also carries. I left it alone.

## What blocks top 3

1. **Not indexed.** No town page is in Google's index, and the hub is indexed with old copy. Nothing ranks until that changes.
2. **No Search Console.** Connecting it is the single most useful step: it allows an indexing request for the eight URLs and shows real queries. It needs the owner.
3. **No external links.** The pages are new and nothing outside the site links to them. MyTownView has age and its own link network.
4. **News intent.** "ridgecrest flock cameras" and "does tehachapi have flock cameras" return news. A map page will not hold top 3 there; a dated brief can, and now passes the click to the map.
5. **Low demand.** For Wasco, Oildale and Rosedale the results suggest few people search these terms, so a top-3 position may bring almost no visits.

## Still open

- **Shafter expansion:** KGET reports the council approved 10 more plate readers, 10 live cameras and a trailer. I did not add it because I could not read the page from here.
- **Tehachapi News:** an article has the police chief addressing Flock cameras. Same reason, not added.
- **Mobile check:** I did not open the pages at 390 px in a browser. The new CSS wraps long links and uses 44 px link rows, but Hermes should confirm no horizontal overflow on the deployed pages.
- **Local build cleanup:** I restored the eight CI-owned files the local build had dirtied. The working tree now holds only the four source edits and `build/alpr_town_records.json`.

--- exit: 0 ---
