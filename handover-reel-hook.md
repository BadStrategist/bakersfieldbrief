# Handover: the reel hook and the whole reel setup, target 20 s watch time

You are the analyst and designer. Hermes executes and verifies. Repo: `C:\Users\tscac\Projects\BakersfieldBrief.com`.
Do not use em dashes anywhere in your output or in any file you write. Plain English, short sentences.

## The owner's request (verbatim)
"Claude is back now so have claude look for a good hook to keep viewer time. Maybe analyze the whole reel
setup. We need minimum 20 second watch time"

## The target, stated honestly
Current average watch time is about **3.2 s per view**. The owner wants **20 s minimum**. On the current
30 s reel that is **67 percent average retention**, which is top-decile for any news format. Say plainly
whether that is reachable at 30 s, and whether the target itself implies a longer reel. If a longer reel is
the answer, say what it costs: a 60 s reel at the same absolute watch behaviour needs only 33 percent
retention for 20 s average, but padding is the risk the owner already asked about. Give the arithmetic for
both cases. Do not promise a number you cannot reason to.

## Evidence measured on this box (use it, do not re-derive it)
Facebook Page Insights, Reels tab, **last 28 days, 2026-09-14 to 2026-10-11**:
- Views **5,755**; 3-second views **1,023**; 1-minute views **0**; watch time **5 h 11 m**.
- Views by content type: Reels 96.9 percent, Photo 2.9 percent, Link 0.2 percent.
- Audience: **96.7 percent non-followers**, 3.3 percent followers.
- Derived: 1,023 / 5,755 = **17.8 percent reach the 3 second mark**. 18,660 s / 5,755 views = **3.24 s
  average per view**. Among the 17.8 percent who pass 3 s, the implied average is about **15 s**.
- So roughly **four of five viewers leave before 3 seconds**, and the ones who stay watch about half the reel.

Per-post views, read from a screenshot of the same panel (approximate, the aggregate above is exact):
2026-10-12 09:19 PT two posts, 0 views each; 2026-10-11 10:53 PT 152; 2026-10-11 09:23 PT 246;
2026-10-10 10:22 PT 291; 2026-10-09 09:22 PT 261; 2026-10-08 07:23 PT 577. The posting slot is about
**09:15 PT** daily, and some days carry two posts. **Check whether today's reel is actually live** (two
posts at 09:19 with 0 views is worth one read of `GET /1298315170026203/posts` with the page token at
`C:\Users\tscac\AppData\Local\hermes\secrets\fb_page_token.txt`; never print the token).

Reel durations, ffprobe on disk: 2026-10-12 **29.0 s**, 10-11 **30.0 s**, 10-10 **30.0 s**, 10-09 **30.0 s**,
10-08 **25.0 s**. Note the 25 s reel is one of the best performers; do not read a trend from one day.

## The real frame plan (read from the code, not from the docs)
`scripts/brief_reel/render_reel.py`, function `frame()`:
- `intro, outro = 1.0, 4.0` seconds. `card_len = (dur - intro - outro) / len(stories)`. With 3 stories and
  dur 30 that is **8.33 s per story**. `MIN_CARD = 6.0` and the renderer refuses a plan below it.
- Inside a story card: headline alpha ramps 0.0 to 0.5 s, subhead at 1.5 s, place box at 2.1 s, gold
  progress bar fills along the top for the whole reel, `1 / N` pager top right.
- The intro is a title flash **complete from frame 0** on purpose: frame 0 is the thumbnail in every
  preview surface, and an earlier fade-in shipped a blank cream frame (the "blank card" bug).
- The bottom 35 percent is deliberately empty (caption bar, audio chip, story reply box cover it).
- No bottom URL band; the URL ships once in the outro and in the caption.
- 3 stories, 1080x1920, 24 fps, music bed rotates daily from three 30 s beds
  (`assets/audio/reel_bed_{1,2,3}.mp3`, chosen by `make_brief_json.music_for_date`).
- Stories come from `scripts/make_brief_json.py`, deterministic, no LLM: lead = the brief's most serious
  incident, stories 2 and 3 = next highest notability, scene mapped from incident type, scene variety only
  as a last-slot tiebreaker.

## What to do
1. **Analyze the actual media, not articles about media.** The reels are on disk:
   `work/social/<date>/reel.mp4` (also the still card PNG beside them). Extract frames with ffmpeg at
   0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0 s from at least the 10-08, 10-09, 10-10, 10-11 and 10-12 reels and
   **look at them**. Judge what a stranger sees in the first second, and whether frame 0 works as a
   thumbnail in a feed. Listen to the audio beds (duration, loudness, whether there is a spoken hook).
2. **Name the hook problem with evidence.** The drop is inside the first 3 seconds, and the first headline
   already lands at 1.0 s, so the old "slow logo intro" theory is wrong. Find the real cause: the title
   flash frame as a thumbnail, text density on a static card, no motion in the first second, no voice,
   lead-story choice, or something else you can point at in the frames.
3. **Design the hook and the whole structure.** Give a specific second-by-second plan for the first 3
   seconds and for the rest, with the exact code changes in `render_reel.py` and, if the story choice is
   part of the problem, `make_brief_json.py`. Keep it deterministic, offline, no LLM, 9:16, and keep the
   music rotation. State the retention arithmetic that gets from 3.2 s to 20 s, and say which single change
   you would ship first and what you expect it to move.
4. **Say what is testable.** Propose the smallest A/B that the owner can run (for example a 7 day hook
   variant against the current one) and the metric that decides it, given that per-post views are only
   readable in Business Suite by hand.
5. **Write your answer to `reel-hook-analysis.md` in the repo root** and print a short summary in your
   final message: the cause, the design, the arithmetic, the first change to ship, and your verdict on
   whether 20 s average is reachable at 30 s.

## Constraints
- No em dashes. No invented numbers. Every claim about our data must trace to a file or a command on this box.
- Do not touch these files, another workstream has uncommitted edits there: `build/builders/alpr_towns.py`,
  `assets/css/deflock.css`, `build/builders/daily.py`, `tests/test_alpr_towns.py`,
  `build/alpr_town_records.json`. The working tree is dirty with that work; leave it alone.
- Another Claude handover (the ALPR town page SEO audit) may run at the same time. Stay off its files.
- Do not push, do not commit, do not publish, do not post. Analysis and code only; Hermes verifies and ships.
