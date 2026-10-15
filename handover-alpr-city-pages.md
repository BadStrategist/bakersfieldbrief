# Should every city have its own ALPR page?

The owner asks, verbatim: **"Ask claude if each city should have their own ALPR / FLOCK page?"**

This is a design and SEO question, not a build request. Answer it as a decision, with the
tradeoffs, and only then write patches if you think they are needed. Do not push anything.

## What shipped an hour ago (commit 460b7a01, deploy run 38314854751)

The county-wide list is live: 455 cameras, every one joined to parcel and owner of record
(`county_join.py all` + `verify`, then `rebuild_all.py`), 316 owners, 375 parcels, 0 cameras with no
roll record. Plus the eight town pages your design wrote, under the floor rule you set (ten cameras
to be listed, eight to keep, under that the url redirects to the hub):

| page | cameras | near list |
| --- | --- | --- |
| Shafter | 32 | 0 |
| Ridgecrest | 31 | 2 |
| Delano | 30 | 0 |
| McFarland | 19 | 0 |
| Oildale | 13 | 0 |
| Tehachapi (city 7 + Golden Hills 2 + Bear Valley Springs 2 + Stallion Springs 1) | 12 | 3 |
| Rosedale | 11 | 0 |
| Wasco | 10 | 0 |

I fixed two things on the way through, both yours to review:
1. The map panel on a town page said "All 15 mapped cameras" while the headline said 12 (the panel
   carries the near list). The panel now names the split: "12 mapped cameras in Tehachapi, Golden
   Hills, Bear Valley Springs and Stallion Springs, plus 3 just outside the Tehachapi city limits".
   `explorer_html(scope_note=...)`, passed only by the town builder, so the hub copy is untouched.
2. The FAQ breakdown left the public agency lane out of its sentence, so its numbers summed to 413
   of 455. It now reads 256 private, 42 public agency, 124 street or right of way, 33 city interest.

Also: 15 older rows called city, county, school and special-district land "Private titled parcel"
(the rule keys on owner type government, and those rows predate it). Relabelled with that rule in
both master files; the hub's privately titled count went 271 to 256, public 27 to 42. `data/alpr`
is now a box-owned path in `scripts/ci_push.sh` (BOX_PATHS, the leak check and the dirty check),
which matches the paragraph you wrote in AGENTS.md.

## The place counts the join produced

Bakersfield 197, no place 57, Shafter 32, Ridgecrest 31, Delano 30, McFarland 19, Oildale 13,
Rosedale 11, Wasco 10, Tehachapi (city) 7, Potomac Park 6, East Niles 6, Mojave 5, Hillcrest 4,
Taft 4, East Bakersfield 3, La Cresta 2, Maricopa 2, Bear Valley Springs 2, Golden Hills 2,
McKittrick 2, Boron 2, Rosamond 2, Keene 2, Casa Loma 1, Old Stine 1, Stallion Springs 1,
Valley Acres 1.

Kern's incorporated cities are Bakersfield, Delano, Maricopa, Ridgecrest, Shafter, Taft, Tehachapi,
Wasco, Arvin, California City and McFarland. Arvin and California City have no camera in the list
at all. Taft has 4, Maricopa 2.

## The question, as I understand it

Today a page exists only where the cameras justify one. The owner is asking whether that is the
right rule at all: whether **every city** should have a page, including the ones with four cameras
or none, because the query people type is the city name ("taft flock camera map", "does arvin have
flock cameras", "california city license plate readers"). Two of those queries have a real answer
today and a page would be the only local one; the third has the answer "none mapped".

Please decide, and be specific:

1. **Every incorporated city, or only the ones above a floor?** If every city, what floor replaces
   the current one, and what does a city with four cameras or none carry that keeps it from being
   the thin page the owner rejects everywhere else? He has a standing rule that a page must be worth
   reading standalone, and that thin one-pagers are not acceptable.
2. **A city with zero cameras:** is "none mapped in this city" a page worth having, or does it
   dilute the hub and the eight real pages? If yes, what must it carry to earn its place (the
   county number, how the county list is made, the nearest cameras, the roll facts for that city)?
3. **Unincorporated places** (Oildale, Rosedale, Potomac Park, East Niles, Lamont, Mojave, Boron and
   the rest): same question, and do they sit at the same level as cities or under them?
4. **What it costs me to keep:** each page is another url in the sitemap and another file whose
   numbers must stay true every week. Say plainly which set you would build, what the floor is, and
   what you would refuse.

## Constraints

- Nothing goes live until it is verified working and accurate. That is the owner's standing
  instruction for this thread.
- No thin pages, no invented copy, no caveat blocks on the surveillance pages. Real data only,
  counted from the data, never typed.
- The redirect rule (a listed town below the floor redirects to the hub) is what the owner has live
  now; if you change it, say what replaces it.
- Light palette, mobile first, no horizontal overflow, correct heading order, JSON-LD kept.
- Ads stay off the surveillance pages entirely.

## Deliverable

The decision first (which pages exist, why, what the floor is), then the design, then patches if you
want them written. Do not push. When you are done I will run the build, check the rendered pages at
1280 and 390 px, and report the numbers before anything ships.
