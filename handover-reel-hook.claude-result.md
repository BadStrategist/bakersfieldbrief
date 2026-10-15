# Claude result for handover-reel-hook.md

- ran: 2026-10-12 16:46 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

The analysis is in `reel-hook-analysis.md` at the repo root. No tracked file was edited; the proposed code is in `work/reel_hook/proto/` (gitignored) and has been rendered into frames and one full 30 s reel.

## Verdict
**20 s average per view is not reachable at 30 s, and not realistically at 60 s either.**
- **At 30 s:** it needs about 66 to 76 percent of viewers to pass 3 s (today 17.8 percent) and nearly all of them to watch to the end. With stayers at today's roughly 15 s it is impossible even at a 100 percent hold.
- **At 60 s:** the same absolute behaviour is still 3.24 s. It needs at least a 32.5 percent hold with every stayer watching all 60 s.
- **What moves the number:** the 3 second hold. Each 10 points adds about 1.4 s. A 30 percent hold gives about 5 s; a 40 percent hold with 20 s stayers gives about 8.4 s. I promise none of these.
- **The "15 s" figure is an assumption:** it holds only if leavers average about 0.7 s. The data allows 4.3 to 18.2 s for stayers.
- **Recommendation:** track the 3 second hold as the target, and keep 20 s as the goal for viewers who pass 3 s. Do not lengthen the reel yet.

## Cause
1. **The headline names no event.** 13 of 22 shipped leads and 31 of 52 stories read "Incident reported on...". Today's machete robbery at the Dollar Tree shipped as "Incident reported on the 2600 block of Mount Vernon Avenue". The label table misses 40 percent of incident types (489 of 1,214).
2. **The first second is a brand card.** Its one line of news is drawn at y = 1240, inside the bottom 35 percent that the caption bar covers.
3. **The news lands late.** At 1.0 s the frame is an empty dark background. The headline is full at about 1.9 s, the subhead at 2.5 s, the place box at 3.1 s.
4. **Almost nothing moves**, and the frames are near black.
5. **The first second is silent** (-40 dB) on every reel, and there is no spoken hook.

## Design
- **Ship first: real headlines.** An unmapped type is shown in its own words ("Robbery", "Armed robbery", "Multi-vehicle crash"). On the 22 shipped briefs, generic headlines drop from 31 to 0. I expect the hold to rise but cannot size it.
- **Then test a cold open.** No title card. Story 1 opens at frame 0 with the time, the event in large type and the place, all above the covered zone, and the subhead arrives word by word by about 1.7 s. The soundtrack and later cards do not move.
- **The test:** 12 days alternating by date (10-14 to 10-25), six reels per arm, each music bed twice per arm. The cold open wins if its pooled 3 second hold beats the control by 4 points or more and it leads in 4 of 6 day pairs. The 12 rows are read by hand from Business Suite at 48 hours.

## For Hermes
- **Today's reel is live:** one reel, published 09:19 PT. The API shows one post, not two.
- **Today's reel is nearly silent throughout** (-34.6 dB mean against about -17 dB on the others). Both dispatch clips failed verification and were mixed in anyway. I flagged this but did not patch it.
- **On 10-09 the "Shots fired" card played a clip about a brake fire.**
- **Owner decision:** the new labels are the dispatch call type in plain words. I put "Reported" in front of kidnapping and hostage; say if other types need it.
- **Set the test window** (`HOOK_TEST` in the proposed `make_brief_json.py`) before copying the files in. Dates in the past ship the headline fix alone.
- **Tests:** the `TestBriefJson` assertions hold on the proposed builder. The full suite was not run because the files are not in place.
- **Per-reel insights are not readable by API:** the page token gets a 403.
- **Not my changes:** eight CI-owned files (`data/build_report.json`, `data/briefs_archive.json`, `email/...`, two card images) went dirty at 4:54 PM in one burst. That looks like a local build from the other workstream. I left them alone.

--- exit: 0 ---
