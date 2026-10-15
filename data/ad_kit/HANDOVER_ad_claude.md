# Handover: static ad for BakersfieldBrief.com, the "cream paper foot" angle

You are one of two designers. The owner (Kulture) will judge the two renders side by side. The other
designer is building a dark plate with a flat ink ledger at the foot. **Your angle is deliberately
different: a light editorial foot, the site's own paper look, with the photograph holding the top.**

## The problem you are solving

The owner sent a draft ad (file below) whose **bottom panel is glitchy and hard to read**: five rounded
translucent pills with icons, serif text on a noisy photograph, small type, one pill holding a full
sentence ("Flock / ALPR Map with Land Ownership Contact info"). The pills are mud. Beat it.

Also wrong in the draft: it says "12+ Live Tracking Charts". The site runs **nine** trackers. Nine is the
number the copy may carry. Never ten, never twelve.

## Your angle, specifically

Bottom third becomes a **cream paper panel** (`#FAF6EC`, the site's own ground), squared off, full bleed
to both side edges, sitting flush to the foot of the frame. Type on it is **ink** (`#1A2126`), not gold,
not white. Amber (`#DC9A1F`) appears only as small marks: a hairline rule, a numeral, a dot. Editorial
rule lines, generous margin, three tiers at most. It should read like the top of a serious newspaper's
front page, not like a software landing page.

The photograph occupies the top two thirds, full bleed, with the headline over its dark upper area and a
**feathered** ink band behind the type (never a hard-edged rectangle).

## Non-negotiable rules the owner has already settled

- No pill cards with icons. No gradient buttons. No stacked CTAs. No fine print. No fake UI, no fake
  product screenshots, no emoji, no mascots, no invented statistics.
- One palette. No neon, no lime green. Never set headline or body type in the accent colour: the research
  found no serious news brand does it (BBC keeps red for LIVE chips, NYT for alerts only).
- A real place needs a real photograph. `uniden_desk_night.jpg` is generated hardware and its window
  skyline is NOT Bakersfield, so do not label any place in it. Do not use the draft's skyline as evidence.
- Honest claims only. The product is a free daily email of overnight scanner news, roads, fog, weather and
  a live camera map. Never promise completeness.
- No em dashes anywhere in the copy. No AI tells (unleash, elevate, in a world where, seamlessly).
- Deliver **both** ratios as separate compositions: 1080x1350 (feed) and 1080x1920 (stories). On the 9:16
  keep about 80 px clear at the top and 250 px clear at the bottom (platform UI covers it).

## Facts

Workdir: `C:\Users\tscac\Projects\BakersfieldBrief.com`. Python: `.venv\Scripts\python.exe` (Pillow and
fontTools installed). Write your script to `data/ad_kit/make_static_ad_claude.py` and render both PNGs to
`data/ad_kit/ad_static_claude_1080x1350.png` and `data/ad_kit/ad_static_claude_1080x1920.png`.
Do not touch any other file. Do not run git. Do not commit.

Fonts (absolute paths):
- Site sans, use this for labels and the foot: `data/ad_kit/fonts/barlow-condensed-600.ttf`, `-700.ttf`
- Site serif for the headline: `C:\Users\tscac\Projects\BakersfieldBrief.com\scripts\brief_reel\fonts\Lora-Variable.ttf`
  (variable: `f.set_variation_by_name("Bold")` or `set_variation_by_axes([700])`)
- Also staged and available if you argue for them: `data/ad_kit/fonts/inter.ttf`, `source-serif-4.ttf`,
  `ibm-plex-sans.ttf`, `archivo.ttf`, `manrope.ttf`, `space-grotesk.ttf`, `newsreader.ttf` (all variable).

Palette, verified from the site's own stylesheet (this is the real brand, not the ad kit's invention):
cream `#FAF6EC`, ivory `#FFFDF7`, ink `#1A2126` / `#232B30` / `#20262C`, amber `#DC9A1F`, deep amber
`#8A5D0A`, brick `#9C3A1D`, sage `#8FA099`, pale cream `#FBEED2`, light grey ground `#F4F6F8`.

Copy you should keep: the headline is **"Bakersfield Slept. We Listened."** The URL is
`BakersfieldBrief.com`. The count is nine. The nine trackers: the Grapevine, Tehachapi Pass (SR-58), Kern
County roads, Bakersfield traffic cameras, school fog delays, the Kern County Fire Tracker, Lake Isabella
water level, the Flock and ALPR tracker, Tehachapi weather. You may shorten these for the foot, but if you
name a number it is nine.

Images you may use:
- `data/ad_kit/uniden_desk_night.jpg` (928x546) the desk-at-night hero, already cropped below the draft's
  burned-in headline. This is the hero the draft used, keep using it.
- The draft to beat: `C:\Users\tscac\AppData\Local\hermes\cache\images\img_427b6f554368.jpeg`
- Plates `data/ad_kit/shot1_heli.png` to `shot5_brand.png` (1152x2048, AI generated), and
  `downtown_bakersfield_fox.jpg` (real, CC0) if you want a different hero.

## What you must do before reporting

1. Render both PNGs.
2. **Look at your own render** (open the image and inspect it, do not trust the code): read every line,
   check the foot's contrast against the cream panel, check both safe margins, check that the panel edge
   and the headline scrim are clean.
3. Iterate at least once on the specific defects you found.
4. Write `<this file>.claude-result.md` next to this handover with: the two output paths, the exact copy
   you set, the type sizes in pixels, the contrast ratio of the ink on cream (state it as a number you
   computed), what you changed after looking at the first render, and anything you could not do.
