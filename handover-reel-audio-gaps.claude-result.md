# Claude result for handover-reel-audio-gaps.md

- ran: 2026-10-12 19:12 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

All three gaps are closed in the builder and the publish gate, but only one of them (clip level) changes anything on the reels you have on disk. Nothing is committed, pushed or published.

**These edits are live at the 08:45 PT slot on 2026-10-13**, because the cron runs the working copy. To keep tomorrow on `0e53dc93`, stash the four source files listed at the end.

Tests: full suite 811 passed. Nine nights with audio on disk (10-04 to 10-12) replayed through the fixed builder: eight clean, 10-12 degraded on story 3 as before.

## The wrapper question

- **File:** `C:\Users\tscac\AppData\Local\hermes\scripts\ko_social_publish.py`, last written 17:23 today.
- **Line:** 254, `if rc not in (0, 3, 6, 7):`. Its comment is lines 251 to 253, the two labels are lines 285 to 289, and the docstring is line 24.
- **Where it lives:** in no commit. That directory has no git, so the file on the box is the only copy.
- **Run since:** no. `2026-10-12-publish.log` holds one attempt, at 09:15, before the edit.
- **Now run against a stub:** I ran the wrapper's own `main()` with the publisher and browser launcher swapped for stubs in a temp directory. Exits 6, 7 and 3 each ran the publisher once, never touched the launcher and printed the right label. Exit 5 retried once, as it should.

## Before and after

Measured over everything on disk: 36 soundtracks with an audit log, 82 mixed clips, 24 `reel.mp4`. The published 09-17 directory has no audit log and no scratch clips, so it is in the reel count only.

| Gap | Before | After |
|---|---|---|
| 1. Clips mixed more than 1 LU from -16 LUFS | 16 of 82 | 0 mixed: 77 trimmed to within 1 LU, 5 refused |
| 2. Clips under the speech floor | 5 of 82 | 5 of 82, none newly refused |
| 3. Clips shorter than their slot | 0 of 82 | 0 of 82 |
| 3. Soundtracks off the scene plan | 0 of 36 | 0 of 36 |
| Reels whose scene count is not their clip count | 3 of 24, unchecked | 3 of 24, held by the gate |

### 1. Clip level: enforced
- **Rule:** a clip must measure within 1 LU of -16 LUFS after its trim, or it is dropped and the reel re-paced like any other failed clip.
- **A quiet clip:** it is lifted by a measured gain of up to +12 dB. A clip the cap still leaves off -16 is dropped.
- **On disk:** the 5 refused are the five dead-air clips, which the speech floor also refuses. So the level check alone refuses nothing here.
- **What it does change:** the 11 real voices that went out between -14.0 and -27.6 LUFS now land between -16.0 and -16.4. Published 10-04 and 10-05 had clips at -19.8, -18.1 and -19.6; the replay puts them at -16.1, -16.0 and -16.3.
- **Tight spot:** the 09-27 clip needed +11.6 dB of the 12 dB cap. A real voice slightly quieter than that would be dropped, and on a one-clip day that holds the reel. I left the cap alone on one data point.

### 2. Speech floor: now a share of the slot
- **Rule:** 1.5 s or a quarter of the slot, whichever is more: 2.1 s in an 8.3 s slot, 3 s in 12 s, 5 s in 20 s. Under 1.5 s reads "no usable audio"; under the share reads "mostly dead air".
- **On disk:** it changes nothing. The five dead-air clips are 6 percent or less, and the lowest real clip is 33 percent (6.65 s of 20 s). Your "2 s in a 20 s cut" case is not on disk; it is covered by tests only.
- **Side effect:** when another clip drops and the slots grow, a clip that filled 8.3 s can fail at 12 s or 20 s. That can hold a day that had one thin clip.

### 3. Short cut: reproduced, then fixed in the mix
- **Not on a published day:** no clip on disk is shorter than its slot, so I could not prove the drift on a real reel.
- **Exposure:** 8 of 2,909 transcript rows start within 8.33 s of the end of their block (19 within 20 s), and 3 of the 46 emulator clips in the manifests are shorter than 8.33 s.
- **Reproduction:** I ran the `0e53dc93` builder on the 10-12 audio with one substituted story, the carbon monoxide alarm at 800 Jeffrey Street, which was dispatched 6.2 s before its block ends. It is a real transmission but was not in that day's brief.
  - The build exited 0 and logged 30.0 s; the soundtrack was 27.82 s.
  - The publisher would have rendered 28 s as three 7.67 s scenes.
  - Clip 2 started 1.51 s before its scene and clip 3 0.84 s before. The old gate passed it.
- **Direction:** the audio runs ahead of the picture, not the picture ahead of the audio.
- **Fix:** each clip is padded (or trimmed) to exactly its slot in the mix, and the written file's length is checked against the plan. A mix off the plan is refused with exit 5. The speech share is judged against the slot, so a short clip that is mostly padding is dropped.
- **Same night after the fix:** 30.00 s, every clip on its scene, 2.18 s of padding recorded in the audit.
- **Publish gate:** `audio_gate` now also holds a reel whose scene count is not its clip count, or whose length is off the plan by more than 0.25 s. It holds the old 27.79 s proof reel and passes the fixed one.
- **The three mismatched reels:** published 09-18 and 09-19 (three scenes over two clips, last scene 4 s off), and my own 10-12 dry render from the earlier session, rendered from an unpruned brief.

## What I could not verify
- Gap 3 on a day that was actually published, and gap 2's refusal on a real clip. Both rest on the reproduction and on tests.
- The wrapper under the real Hermes cron runner. The stub run exercises its code, not the scheduler.
- `publish_social.py` end to end on a real date. It would fetch git and could reach the API, so I called `audio_gate` directly on built artifacts instead.
- How any of it sounds. Nobody has listened to the padded clip or the re-levelled ones.
- The nights before 10-04. Their source audio is gone, so those clips were re-measured from the scratch pieces, not rebuilt.
- Linux CI. The new ffmpeg tests ran only on this box.
- Whether three older reels were posted as they sit on disk: 09-27 measures -31.0 LUFS, 09-21 -19.2 and 09-24 -19.6, all under the -19 publish floor.

A day held because `brief.json` could not be pruned will stay held on the retry slot, since the mis-cut reel is reused; it needs a person.

## Files changed
- `scripts/brief_reel/make_dispatch_audio.py`
- `scripts/brief_reel/reel_audio_gate.py`
- `scripts/brief_reel/publish_social.py`
- `AGENTS.md` (the Reel audio section)
- `tests/test_publish_social.py`
- `tests/test_reel_audio.py` (still untracked; it needs committing with the rest)

`make_brief_json.py` and `render_reel.py` were not touched: no line in either was needed. `hook_for_date` and the cold-open scene plan are as they were. The measurement scripts and all rebuilt audio are in `%TEMP%\reelgaps`.

--- exit: 0 ---
