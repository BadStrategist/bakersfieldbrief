# Claude result for handover-alpr-city-pages.md

- ran: 2026-10-12 15:09 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

## Decision

**No: every city should get an answer, but not every city should get a page.** Keep the eight pages and the floor as they are (ten to be listed, eight to keep, redirect below that). Give every incorporated city, including the ones with four cameras or none, a row in a by-town table on the hub.

I wrote that table as a patch. It is not committed, not pushed, and I have not run the site build. The full test suite passes.

### 1. Every incorporated city, or a floor?
A floor. Here is what a page would carry for the cities below it, counted from the join:

| city | inside | owners | just outside the limits |
| --- | --- | --- | --- |
| Taft | 4 | 4 | 4 |
| Maricopa | 2 | 1 | 3 |
| Arvin | 0 | 0 | 0 (nearest camera 7.8 mi away) |
| California City | 0 | 0 | 0 (nearest 3.9 mi, in Mojave) |

A Taft page is a four-row table inside copy identical to eight other pages. That is the thin one-pager the owner rejects elsewhere, and the templated pattern search engines treat as doorway pages.

### 2. A city with zero cameras
Refuse it. The page's only claim would be "none", and the list is volunteer-mapped: it can say none are mapped, not that the city has none. That gap needs a caveat, and caveat blocks are banned on these pages. Padding it with the county number, the method and the nearest cameras is hub content under a city name.

### 3. Unincorporated places
Same rule, same level, flat urls. Oildale and Rosedale clear the floor and keep their pages. The rest stay off:
- **Bakersfield county islands** (Potomac Park 6, East Niles 6, Hillcrest 4, East Bakersfield 3, La Cresta 2, Casa Loma 1, Old Stine 1): these belong to the hub, which is Bakersfield's page.
- **Mojave 5, Rosamond 2, Boron 2, Keene 2, McKittrick 2**: below the floor.
- **Lamont**: no camera, so it is not listed at all. Only cities get a zero row.

### 4. What it costs, and what I would build
- **Build:** the eight pages you have, plus one table on the hub. No new urls, no sitemap change, no redirect change.
- **Promotion:** Taft and Mojave are next. The build log already names any unlisted place that reaches ten, so adding one stays a decision.
- **Refuse:** zero-camera pages, pages under the floor, a second Bakersfield page, and per-city FAQ entries on the hub.

I could not check search volume for the city queries: the Ahrefs plan returned "Insufficient plan". The decision rests on the page content, not on demand numbers.

## Design: the hub's by-town block

The link list becomes a three-column table: city or community, cameras inside, just outside the city limits.

- **Rows:** all eleven cities (Arvin and California City show 0), every community holding a camera, then "In no city or Census place" (57). The footer total is 455, and a test asserts the column sums to the camera list.
- **Links:** a town with a page is linked as "Shafter Flock camera map". Golden Hills, Bear Valley Springs and Stallion Springs read "on the Tehachapi map". The Tehachapi row shows 7, the city alone, while its page headline says 12 for the group.
- **Just outside:** filled for cities only, using the same measurement the town pages print (cameras within 3 miles of the limits). Communities get a blank cell, so Oildale's row matches its page.
- **Gating:** unchanged. The block appears only when town pages are built.

City rows from today's data: Bakersfield 197 (6 outside), Shafter 32 (2), Ridgecrest 31 (2), Delano 30 (1), McFarland 19 (6), Wasco 10 (0), Tehachapi 7 (3), Taft 4 (4), Maricopa 2 (3), Arvin 0, California City 0.

## One correction to the handover

The near-list column in your table is wrong for three towns. The pages on disk are right: Delano has 1 just outside, Shafter 2, McFarland 6 (five of them within 80 m of the city line). Your table says 0 for all three. Ridgecrest 2, Tehachapi 3 and Wasco 0 match.

## What changed

- `build/builders/alpr_towns.py`: new `place_rows(sources)`, `hub_links_html(plans, sources)` now renders the table, and the near-list lookup is shared with `plan()`.
- `build/builders/trackers.py`: passes `sources` to the hub block.
- `tests/test_alpr_towns.py`: one assertion updated, one new test for the table.
- `AGENTS.md`: one sentence in the Towns paragraph stating the rule.

When you build, check the table at 390 px. It uses the existing `table.data` in `.table-wrap`, and the linked names are the longest cells.

--- exit: 0 ---
