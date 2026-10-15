# Reel hook analysis, 2026-10-12

Answer to `handover-reel-hook.md`. Nothing here is committed, pushed or posted. The production
scripts are unchanged. The proposed code sits in `work/reel_hook/proto/` (gitignored) and has
been rendered.

## 1. Verdict on the 20 second target

**20 s average watch time per view is not reachable on a 30 s reel. It is not realistically
reachable on a 60 s reel either.** The reason is how the number is built, not the quality of
one reel.

Average per view = (share who pass 3 s) x (their average) + (share who leave) x (their average).

Measured: 17.8 percent pass 3 s, average 3.24 s. The handover's "stayers watch about 15 s"
holds only if the leavers average about 0.7 s. The data does not say what they average. The
honest range for stayers is 4.3 s (leavers at 3.0 s) to 18.2 s (leavers at 0 s). I use 15 s
and 0.7 s below and mark it as an assumption.

| Case | Share past 3 s | Stayer average | Average per view |
|---|---|---|---|
| Today (measured) | 17.8% | about 15 s | 3.24 s |
| Better hook only | 25% | 15 s | 4.3 s |
| Better hook only | 30% | 15 s | 5.0 s |
| Hook and body | 30% | 18 s | 5.9 s |
| Strong | 40% | 20 s | 8.4 s |
| Very strong | 50% | 22 s | 11.4 s |
| 20 s on a 30 s reel, stayers watch all 30 s | 65.9% needed | 30 s | 20 s |
| 20 s on a 30 s reel, stayers leave at the outro (26 s) | 76.3% needed | 26 s | 20 s |
| 20 s on a 60 s reel, stayers watch all 60 s | 32.5% needed | 60 s | 20 s |
| 20 s on a 60 s reel, stayers average 40 s | 49.1% needed | 40 s | 20 s |

Reading it:

- At 30 s, 20 s needs two things at once: the 3 second hold must rise from 17.8 percent to
  about 66 to 76 percent, and nearly every stayer must watch to the end. With stayers at
  today's 15 s the target is impossible even at a 100 percent hold, because 15 is under 20.
- A longer reel does not fix this. "33 percent retention on 60 s" is true as a ratio, but
  the same absolute behaviour on a 60 s reel is still 3.24 s. A longer reel only helps the
  17.8 percent who stay, and only if they stay longer than 15 s. To average 20 s at 60 s you
  need at least a 32.5 percent hold with every stayer watching every second.
- 96.7 percent of views are non-followers, and a view is counted for a reel that autoplays
  past. That is why the leaver share is large. It will stay large.
- "1-minute views 0" is not a signal. No reel is 60 s long.

**What I can reason to:** the lever is the 3 second hold. Each 10 points of hold adds about
1.4 s to the average at today's stayer length. A hold of 30 percent gives about 5 s. Getting
from 3.2 s to 8 s needs a 40 percent hold and 20 s stayers. I will not promise any of these.
I recommend the owner track **3 second hold rate** as the target, and keep 20 s as the goal
for **viewers who pass 3 seconds** (reachable at 30 s: it means stayers reach 20 of 30 s).

**Longer reel:** not now. Length multiplies only the stayers. Fix the hook first. If the hold
passes about 30 percent, test 45 s with four stories. The renderer already takes four, and
the bed already loops. The cost is the padding risk: a fourth story is the fourth most
notable call of the night, and the pager shows "1 / 4" so the viewer sees how much is left.

## 2. Is today's reel live?

Yes. One read of the Graph API (`/posts` and `/video_reels`, token not printed):

- Reel `1473500888216983`, published 2026-10-12 16:19:02 UTC (09:19 PT), length 29 s, status
  published, copyright check clean. Feed post created 16:19:34 UTC.
- The API shows **one** post for today, not two. The two rows at 09:19 in Business Suite are
  most likely the reel and its feed post. Zero views at screenshot time fits a fresh post.
- The API puts the 10-08 reel at 16:23 UTC, which is 09:23 PT, not 07:23. The slot is steady
  at about 09:20, except 10-10 (10:23) and 10-11 (10:53).
- `/{reel}/video_insights` returned 403 for all eight reels I tried. The page token cannot
  read per-reel insights, so per-reel numbers stay a hand read for now.

## 3. What a stranger sees and hears (from the frames)

Frames at 0.0, 0.5, 1.0, 2.0, 3.0, 5.0 and 10.0 s for 10-08 to 10-12 are in
`work/reel_hook/frames/`, with contact sheets `work/reel_hook/sheet-<date>.png`.

**Cause 1. The headline names no event.** This is the largest defect and it is a bug.

- Today's first words on screen: "Incident reported on the 2600 block of Mount Vernon
  Avenue". The call was a robbery with a machete at the Dollar Tree.
- 10-11: "Incident reported on Union Avenue" (armed robbery by eight to ten people).
  10-10: "Incident reported on northbound Interstate 5" (multi-vehicle crash with fire).
  10-08: "Incident reported on the 1800 block of Pacific Street" (a woman dragged from a home).
- Across the 22 `work/social/2026-*/brief.json` files on disk: **31 of 52 stories and 13 of
  22 leads** open with "Incident reported".
- Why: `make_brief_json.story_json` does `TYPE_LABEL.get(t, "Incident reported")`. The
  incident `type` is free text. Across the 63 `incidents/2026-*.json` files, 489 of 1,214
  incidents (40 percent) carry a type the table does not hold, in 221 distinct spellings
  ("robbery", "armed robbery", "multi-vehicle crash", "assault with a deadly weapon").

**Cause 2. The first second is a brand card, and its one line of news sits under the caption bar.**

- 0.0 to 1.0 s is cream: logo, date, masthead, kicker, then the headline last and smallest.
- That headline is drawn from y = 1240 down. The renderer's own rule says the bottom 35
  percent is covered, and 35 percent starts at y = 1248. So in the feed the only story text
  in the first second is hidden. What is left is a logo and a name a non-follower does not know.
- The same applies to the time and place box on every story card: it is drawn at y 1180 to
  1400, mostly inside the covered zone.

**Cause 3. The news arrives late and small.**

- "The headline lands at 1.0 s" is not what the frames show. At 1.0 s the frame is a dark
  background with only the small brand row (see the third column of every sheet). The
  headline fades in from 1.15 s and its third line is full at 1.86 s.
- The subhead carries the real story and is 42 px grey. It is full at 2.5 s. The place box
  is full at 3.1 s. So the 3 second mark passes before the card is complete.
- At 1.0 s the frame also flips from cream (mean luma 216 of 255) to near black (23). That
  is the only scene change in the first 4 s.

**Cause 4. Almost nothing moves.** After the headline is in, the only motion is a slow drift
on a background with mean luma 28 to 30. The encoder runs `-tune stillimage` and the files
come out at 600 to 830 kbit/s, which is what a slideshow costs.

**Cause 5. The first second is silent, and there is no spoken hook.**

- The soundtrack is not just the bed. `make_dispatch_audio.py` cuts real dispatch radio under
  each story, with the bed at -18 dB. It puts 1.0 s of silence in front.
- Measured: 0 to 1 s is -40 dB mean on every reel. From 1 s it is about -16 dB. So a viewer
  with sound on hears close to nothing for the first second.
- The beds are 30.0 s each, about -17 dB mean, -1.7 dB peak. No voice.
- **Today's reel is close to silent all the way through**: -34.6 dB mean for the whole file,
  against -16.3 to -18.1 dB on the other four. Both dispatch clips failed verification
  (`verify_ok: false`, empty transcript, cut at the very start of the probe window) and were
  mixed in anyway. See `work/social/2026-10-12/soundtrack.json`.
- On 10-09 the "Shots fired" card played a clip about a brake fire ("flames that are coming
  from the front brakes"), marked `verify_ok: true`. That is an accuracy problem, not only a
  retention one.

**Not the cause:** the pager, the progress bar and the story order are fine. The 10-08 reel
(one story, 25 s, the most views) had the most gripping subhead of the week. One day is not a
trend, but it points the same way: the event is what holds people.

## 4. The design

### First change to ship: real headlines (both test arms, no layout risk)

`make_brief_json.py`: a type the table does not hold is shown in its own words. Only truly
empty types ("incident", "vehicle", "traffic") keep "Incident reported". A caller's word for
a grave crime is labelled as a report.

Measured on the 22 shipped briefs: generic headlines go from 31 to 0, generic leads from 13
to 0. Examples: "Robbery on the 2600 block of Mount Vernon Avenue", "Armed robbery on Union
Avenue", "Multi-vehicle crash on northbound Interstate 5", "Shots fired near Fairgrounds
carnival", "Reported kidnapping on the 1800 block of Pacific Street".

What I expect: it changes frame 0, the thumbnail and every card on about 60 percent of
stories. I expect the hold to rise. I cannot put a number on it.

**Owner decision needed:** the label is now the dispatch call type in plain words. That is
more direct than "Incident reported". I added "Reported" in front of kidnapping and hostage.
Say if other types need the same.

### Second change, the A/B variant: the cold open

`"hook": "cold"` in brief.json. No title card. Story 1 opens the reel on its own background
and keeps the intro second. Every later card and the whole soundtrack stay where they were,
so the two arms differ only in what is on screen from 0.0 to about 3 s.

Second by second (cold arm):

| Time | Screen |
|---|---|
| 0.0 s (thumbnail) | Dark scene. Brand row and kicker. Gold time with a red live dot. Event in 124 px bold ("Shots fired"). Place in gold under it. All complete, all above the covered zone. |
| 0.0 to 0.5 s | Gold rule wipes out under the place. Dot pulses about once a second. |
| 0.25 to about 1.7 s | Subhead arrives one word every 1/14 s, 50 px, light cream. |
| 1.7 to 9.3 s | Story 1 holds (it has 9.33 s instead of 8.33). Background drifts. |
| 9.3 to 26 s | Stories 2 and 3, unchanged cards. |
| 26 to 30 s | Outro, unchanged. |

Rendered proof: `work/reel_hook/proto-sheet-2026-10-09.png`, `-10-11.png`, `-10-12.png`, and
a full encoded reel `work/reel_hook/cold-2026-10-09.mp4` (30.0 s, 3.3 MB, real soundtrack).
Compare with `work/reel_hook/sheet-2026-10-09.png`.

One honest doubt: the cold frame 0 is dark (luma 26) and the title card is bright (216). A
bright card may stand out more in a feed. I do not know which wins. That is what the test is for.

### The exact code

Both files are ready as drop-in replacements, made from the current HEAD versions:

```
Copy-Item work\reel_hook\proto\make_brief_json.py scripts\make_brief_json.py
Copy-Item work\reel_hook\proto\render_reel.py     scripts\brief_reel\render_reel.py
```

Diffs for review: `work/reel_hook/make_brief_json.patch` (86 lines) and
`work/reel_hook/render_reel.patch` (121 lines). Summary of what they do:

`scripts/make_brief_json.py`
- New `VAGUE_TYPES`, `REPORTED_TYPES`, `label_for(raw_type)`. `story_json` calls
  `label_for(inc.get("type", ""))` in place of `TYPE_LABEL.get(t, "Incident reported")`.
- `story_json` also writes `label` and `where` (the place with its preposition, empty when
  the incident has no area).
- New `HOOK_TEST = ("2026-10-14", "2026-10-25")` and `hook_for_date(date)`. `build` writes
  `"hook"`. Outside the window it is always `"title"`. **Set the window before shipping.**
  To ship the headline fix alone, set the window to dates in the past.

`scripts/brief_reel/render_reel.py`
- New `lead_card(...)`: the cold opener described above.
- `frame()`: `cold = cfg.get("hook") == "cold"`, and a small `start(n)` helper for card
  start times. The title card runs only when not cold. With `"hook"` absent or `"title"`
  the output is the same as today: card times and the background drift reduce to the old
  formulas.
- `make_dispatch_audio.py` and `publish_social.py` are not touched. `_prune_brief_to_audio`
  rewrites only `stories`, so `hook` survives it.

Checked: the proposed builder passes the assertions in `tests/test_kern_overnight.py`
`TestBriefJson` for 2026-08-17 and 2026-08-18 (run against the prototype, not through
pytest). I did not run the full test suite, because the files are not in place. Hermes
should run it after the copy.

### Later changes, in order, each its own test

1. **Do not ship silent clips.** In `make_dispatch_audio.py`, a piece that fails
   verification with an empty transcript should be dropped like a story with no beat, or the
   build should stop. Today's reel is the case. I have not written this patch.
2. **Voice from frame 0.** On cold days the 1.0 s of lead silence has no reason to exist.
   Needs `LEAD` in `make_dispatch_audio.py` and `intro` in `render_reel.py` to move together.
3. **Shorter outro.** 4 s of logo is 13 percent of the reel with nothing to watch. Its text
   is complete at 2.4 s. Try 2.5 s and give the time to the stories.
4. **Move the time and place box up** on cards 2 and 3, out of the covered zone (it is at
   y 1180 to 1400 today).
5. **Scene picker stems.** `backgrounds.KEYWORDS` wraps stems in `\b...\b`, so "robber" does
   not match "robbery" and "burglar" does not match "burglary". Today's machete robbery fell
   through to the default city scene.
6. **Default city.** `story_json` falls back to `area = "Bakersfield"` when the incident has
   no area ("Backyard fire in Bakersfield", 09-20). AGENTS.md says an empty area names no
   place. I left the headline behaviour alone and kept the new `where` field empty in that case.

## 5. The test

**Design:** 12 days, opener alternating by date, built into `hook_for_date`. Twelve days is
two full cycles of opener by music bed, so each arm gets six reels and each bed twice:

- Cold: 10-15, 10-17, 10-19, 10-21, 10-23, 10-25.
- Title (control, with the fixed headlines): 10-14, 10-16, 10-18, 10-20, 10-22, 10-24.

Alternating days beats week against week, because the night's news moves views more than
any layout does.

**Reading it by hand:** for each reel, 48 hours after it posts, write down from Business
Suite: views, 3-second views, and watch time or average watch time. Twelve rows.

**Metric that decides:** pooled 3 second hold per arm = sum of 3-second views / sum of views.
Baseline is 17.8 percent. If the per-reel panel does not show 3-second views, use pooled
average watch time = sum of watch time / sum of views, baseline 3.24 s.

**Rule:** the cold open wins if its pooled hold is at least 4 points above the control, and
it is ahead in at least 4 of the 6 adjacent-day pairs. At about 1,500 views per arm the
sampling error on the difference is about 1.4 points, and views inside one reel are not
independent, so a gap under 4 points is noise. If it does not win, keep the title card and
the fixed headlines, and test voice from frame 0 next.

**To automate later:** the page token got a 403 on `/{reel}/video_insights`. If the owner
adds insights read access to the token, the twelve rows could be logged by script. I have
not verified which permission Meta wants.

## 6. Files

- `reel-hook-analysis.md` (this file, repo root, untracked).
- `work/reel_hook/` (gitignored): `frames/`, `sheet-*.png` (current reels), `proto/` (the
  two proposed files), `*.patch`, `proto-sheet-*.png`, `cold-2026-10-09.mp4`, and the
  scripts that produced them (`run_proto.py`, `check_proto.py`, `render_cold.py`, `types.py`).
- No tracked file was edited. The ALPR workstream files were not touched.
