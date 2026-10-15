# Claude result for handover-reel-audio-fix.md

- ran: 2026-10-12 17:01 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

The fix is written and tested, and the full report is in `reel-audio-fix.md` at the repo root. Nothing was pushed, published or re-posted.

**One thing to know first:** the cron wrappers run this working copy, so these changes are in force at the 08:45 PT slot on 2026-10-13 whether or not anything is committed. If you want tomorrow on the old code, the repo files must be stashed and the three wrapper edits reverted by hand (that directory is not under git; the edits are listed in the report).

## Root cause
The builder started each cut on a Whisper segment's start time, and Whisper stamps a 30 s chunk that opens on dead air as one segment from 0.00 to 29.98, so on 10-12 both cuts took the 12 s of silence before the call (0.5 s and 0.7 s of sound), were mixed despite `verify_ok: false`, and nothing downstream read the exit code or measured the result.

- **Why 10-12:** commit `8e317bea` (10-09) made the hint exact, so the call now sits at second 25 of the probe and what precedes it is often silence.
- **Not new:** the same dead-air clip sits in the 09-21, 09-22 and 09-23 soundtracks, hidden by good clips beside it. I did not check whether those reels were posted.
- **10-09 brake fire:** the Pembroke call was outside the 70 s probe (clock hints are only good to the minute), and "fire" alone then scored 5 against a threshold of 3 (3 as a drama word, 2 because `fired` fuzzy-matches `fire`). Fixed, not deferred.

## Files changed
- `scripts/brief_reel/make_dispatch_audio.py`
- `scripts/brief_reel/reel_audio_gate.py` (new)
- `scripts/brief_reel/publish_social.py`
- `tests/test_reel_audio.py` (new, 45 tests)
- `tests/test_publish_social.py` (2 existing kept and now stubbing the gate, 18 added)
- `AGENTS.md` (a "Reel audio" section)
- `reel-audio-fix.md` (the report)
- `~/AppData/Local/hermes/scripts/ko_social_publish.py`, outside the repo: exit codes 6 and 7 are not retried, and each gets a label.

I did not touch the five files you listed.

## Test command and result
`.venv\Scripts\python.exe -m pytest -q -o addopts="" --tb=short` gave **753 passed in 267.69s**.

I also replayed six real nights through the new builder into `%TEMP%\reelfix3`:

| Night | As published | New build |
|---|---|---|
| 10-07 | 3 clips | 3 clips, clean |
| 10-08 | 1 clip, failed verification | 3 clips, clean |
| 10-09 | story 1 played a brake fire | 3 clips, story 1 is the 5420 Pembroke Avenue call |
| 10-10 | 3 clips | 3 clips, clean |
| 10-11 | story 3 opened on unrelated traffic | 3 clips, story 3 starts on the truck fire call |
| 10-12 | 2 clips of dead air, -35.6 LUFS | 2 real clips, -16.4 LUFS, story 3 dropped |

Every replayed mix landed at -16.3 or -16.4 LUFS. The 10-12 soundtrack, rendered to `reel.mp4`, passes the publish gate at -16.4 LUFS; the original published reel is held by it.

## What happens tomorrow if a clip fails verification
- **One clip fails, another verifies:** the failed clip is not mixed, the reel is re-paced over the rest and published at -16 LUFS, and the run exits 7 with `PUBLISHED, AUDIO DEGRADED` and the dropped story and reason in the cron output.
- **Every clip fails:** no soundtrack is written, nothing is posted, and the run exits 6 with `REEL HELD` and the reasons. The 09:00 slot repeats the alert without rebuilding, and the existing 10:15 check raises "the reel did NOT post".
- **The reel comes out quiet for any other reason:** held at the publisher's -19 LUFS floor, same exit 6.

The decisions you asked for:
- **Gate location:** both. The builder drops and re-paces; the publisher re-reads the audit and measures the `reel.mp4` it is about to post, because it reuses any soundtrack already on disk without running the builder.
- **Fallback when nothing verifies:** hold the reel. I did not automate card-and-caption, because the only card path (`post_facebook.py`) also posts a bed-only reel and cannot be tested without posting.
- **Levels:** each clip and the finished mix at -16 LUFS, the bed at -36 LUFS, peak at or under -1 dBTP, all measured. A mix needing more than +12 dB is refused as having no voice.

## Could not verify
- **A live publish**, by instruction. The API legs and the new report lines are covered by tests with the API stubbed.
- **The wrapper edit:** it compiles; it was not run.
- **How the new mix sounds.** Loudness matches a normal day, but the final stage is now a measured gain and limiter and nobody has listened to it. `%TEMP%\reelfix3\2026-10-12\soundtrack.mp3` is the one to hear.
- **CI on Linux:** the new ffmpeg tests ran only here on Windows.

Also worth knowing:
- **Exit 7 may fire often.** Three of the last seven published reels were missing a story; on the replay only one of six is. If it becomes noise, it is one line in `publish_social.py`.
- **10-12 story 3 still has no clip.** The probe model (`large-v3-turbo`) cannot hear a transmission the night model did. Using `large-v3` for the probe is a separate change.
- **Today's reel directory was hand-repaired by someone else at 17:09 to 17:20.** I left it alone. Its audit log is still the 09:17 one, so `publish_social.py --date 2026-10-12` now exits 6.
- **Another workstream was in the tree:** it committed `make_brief_json.py` as `18695dae` and has `render_reel.py` modified. Neither is mine, and the soundtrack timeline is unaffected.

--- exit: 0 ---
