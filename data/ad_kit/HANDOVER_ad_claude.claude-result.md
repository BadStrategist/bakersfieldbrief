# Result: static ad, "cream paper foot" angle

## Outputs
- `data/ad_kit/ad_static_claude_1080x1350.png` (feed, 4:5)
- `data/ad_Both ads are rendered. They have the night desk photo across the top two thirds and the site's cream paper at the foot, set in dark ink like a newspaper front page.

- **Files:** `data/ad_kit/ad_static_claude_1080x1350.png` (feed) and `data/ad_kit/ad_static_claude_1080x1920.png` (stories). The script that makes them is `data/ad_kit/make_static_ad_claude.py`. It replaced an older ad script that was already at that path, as the handover asked.
- **Copy:**
  - Headline: "Bakersfield Slept. We Listened."
  - Line under it: "Overnight scanner news, roads, fog and weather. One free email, every morning."
  - A gold "9" with "LIVE TRACKERS ON THE SITE" and the nine tracker names.
  - Sign-off: "BakersfieldBrief.com" and "FREE DAILY EMAIL".

  The script refuses to run if the tracker list isn't exactly nine.
- **Readability:** the dark ink on cream measures 15.09:1 and the grey tracker names 7.34:1. The usual minimum for normal-size text is 4.5:1.
- **Story safe zones:** the headline sits at about 170 px from the top, and the last line of text is at 1649 px, under the 1670 px limit. The script fails if that line ever moves past the limit.
- **Fixes after looking at the renders:**
  - The headline was jammed against the edges, so I made it smaller.
  - The city lights behind it were busy, so I darkened the soft shading behind the headline.
  - The feed's text was crowded toward the top of the cream panel, so I spaced it out.
  - The story had about 420 px of empty cream at the bottom, so I made the photo taller.
  - On the second story render, the web address ran straight into "FREE DAILY EMAIL". I made both smaller, and the script now fails if they come closer than 60 px.
- **Limits:**
  - The desk photo is only 928×546, so it is blown up 1.6× for the feed and 2.1× for the story. It looks soft up close, especially on the story.
  - The story crop cuts off the speaker and most of the tablet so the radio stays whole.
  - The radio's screen shows the photo's garbled made-up text. No place in the photo is labelled.
- **Font choice:** the web address uses the site's own serif title font rather than the sans font the handover suggested for the foot, so it reads like the site's masthead.

The full write-up, with type sizes, is in `data/ad_kit/HANDOVER_ad_claude.claude-result.md`. I didn't touch any other file and didn't run git.

--- exit: 0 ---
s with the bokeh behind it.

## Safe margins (9:16)
- The headline cap top is at about y=170, well clear of the 80 px top zone.
- The last baseline is at y=1649. The limit is 1670 (1920 - 250), and the script asserts it.

## What I changed after looking
1. **Render 1:** the headline was fit edge to edge (112 px) and looked crammed against the frame. I set it at 92% of the fit (103 px) and moved it down 8 px on the feed.
2. **Render 1:** the bokeh behind the headline was busy. I raised the scrim (top wash 150 to 160, band 150 to 175). It is still feathered.
3. **Render 1:** the feed foot was top-heavy. I opened up the rule, ledger and sign-off gaps so the foot's bottom margin matches the side margin.
4. **Render 1:** the 9:16 had about 420 px of dead cream at the bottom. I took the photo from 1040 to 1150 px and enlarged the deck and ledger.
5. **Render 2:** on the 9:16 the masthead ran straight into `FREE DAILY EMAIL` with no gap. I set the masthead to 58 px and the tag to 27 px, and added an assert that keeps them at least 60 px apart.

## What I could not do / notes
- The hero is 928x546, so the feed is upscaled 1.58x and the story 2.1x. It is soft up close, especially the story, and sharpening only partly hides that. A higher-resolution original of the same scene would fix it.
- The 9:16 crop cuts off the speaker on the left and most of the tablet on the right, because the radio has to stay whole at that height.
- The radio's screen shows AI-garbled text ("NONITORINS", "HWY 99 OPEN"). It is part of the hero I was told to keep. No place is labelled anywhere in the photo.
- The bottom 270 px of the 9:16 is plain paper on purpose, because platform UI covers it.
