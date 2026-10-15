# Handover: the reel soundtrack shipped silent on 2026-10-12, and a clip played the wrong audio on 2026-10-09

You are the owner of this fix. Hermes executes and verifies your claims. Repo: `C:\Users\tscac\Projects\BakersfieldBrief.com`.
This file is a brief, not a plan you must follow. Find the real cause, then fix the class of defect. No bandaid.

## What the owner already measured (do not re-derive these, verify them if you doubt them)

1. **2026-10-12 ship is effectively silent.** `ffmpeg -af volumedetect` on `work/social/<date>/reel.mp4`:
   - 10-06: mean -18.1, max -1.3
   - 10-07: mean -17.9, max -1.4
   - 10-08: mean -16.3, max -1.3
   - 10-09: mean -17.9, max -1.3
   - 10-10: mean -17.9, max -1.5
   - 10-11: mean -18.1, max -1.5
   - **10-12: mean -34.6, max -10.7**
   That reel is live on the page (published 09:19 PT).
2. **`work/social/2026-10-12/soundtrack.json`:** both stories carry `cut_ok: true` but `verify_ok: false`,
   `verify_ratio: 0.0`, `verify_score: 0` and `verified_transcript: []` (the re-transcription came back
   empty). `bed: reel_bed_3.mp3`, `bed_db: -18`. The `matched_text` and `beat_text` are good, so the window
   search worked and the CUT is the broken part.
3. **Every other recent day verified fine.** 10-09, 10-10 and 10-11 all show `verify_ok: true` for every
   story with 1 to 2 transcript lines each. 10-08 is mixed (one None, one False, one None) and that day was
   25 s, not 30 s.
4. **The bed files are not the cause.** All three measure the same: `reel_bed_1.mp3` mean -16.9 / max -1.7,
   `reel_bed_2.mp3` mean -17.1 / max -1.7, `reel_bed_3.mp3` mean -17.1 / max -1.7.
5. **Why it went silent for the whole reel:** `make_dispatch_audio.py` mixes the bed with
   `volume={BED_DB}dB` at `BED_DB = -18`. The bed's own mean is about -17 dB, so -18 dB relative lands the
   bed near -35 dB absolute. On a normal day the radio voice dominates the mix and nobody notices. With both
   clips silent the mix is nothing but that bed, so the whole reel is inaudible on a phone.
6. **The failure was swallowed, twice over:**
   - `make_dispatch_audio.py` line 471 warns when `verify_ok` is false, then line 474 appends the piece
     anyway. The exit code only goes non-zero for the `failed` list at line 429 (no keyword-matched beat),
     which did not happen today.
   - `scripts/brief_reel/publish_social.py` calls the builder at line 175. Check what it does with that
     return code, and whether a reel whose audio verification failed can reach the page.
7. **2026-10-09 played the wrong audio:** the "Shots fired on the 5400 block of Pembroke Avenue" card played
   a clip about a brake fire. That is a window-selection defect, a different failure of the same system.

## What the owner wants

The class of defect fixed, not today's symptom. A published reel with no usable voice track is worse than no
reel, and we found it by hand a day late. Specifically:

1. **A clip whose re-transcription comes back empty or degenerate must never be mixed.** Dropping it is
   correct. Mixing it is not.
2. **The failure must be loud and must reach the publisher.** A verified-audio failure has to fail the run
   that publishes, with an alert, so we learn about it the same morning. Decide where the gate belongs
   (builder exit code, a check the publisher runs, or both) and say why.
3. **Define and implement the fallback for the case where no clip verifies at all** (today). Options you may
   consider, pick one and justify it: hold the reel and publish the card and caption only; publish with the
   bed brought up to a real listening level; re-read the copy with TTS on this box. Whatever you choose, it
   must be an explicit, logged outcome, never a silent 30 s of near silence.
4. **Make the mix unable to ship at -35 dB.** The bed at a fixed relative attenuation against a source whose
   own level varies is the wrong shape. Consider measuring the finished mix and normalizing it (for example
   `loudnorm` to a stated LUFS with a true-peak ceiling), with the bed at a stated LUFS under the voice.
   State the numbers you choose and why.
5. **The window-selection defect from 10-09** (right card, wrong audio): find why the pick landed on a brake
   fire and fix that too, or say plainly why it is a separate job and what the fix is.
6. **Add tests** that fail if a degenerate clip is mixed, and if a reel whose audio verification failed can
   be published without a loud outcome.
7. **Do not touch these files**, another workstream owns them and has uncommitted edits:
   `build/builders/alpr_towns.py`, `assets/css/deflock.css`, `build/builders/daily.py`,
   `tests/test_alpr_towns.py`, `build/alpr_town_records.json`.
8. **Do not push, do not publish, do not re-post today's reel.** Write your changes and the tests, run them,
   and report. Hermes ships after review.

## Report back

Write your findings and the change to `reel-audio-fix.md` at the repo root, and end your reply with: the root
cause in one sentence, the files you changed, the exact test command you ran and its result, what happens
tomorrow if a clip fails verification again, and anything you could not verify. Use no em dashes.
