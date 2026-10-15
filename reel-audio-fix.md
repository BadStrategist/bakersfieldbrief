# Reel audio fix: the silent reel of 2026-10-12 and the wrong clip of 2026-10-09

Written 2026-10-12. Nothing was pushed, published or re-posted. Read "Live on the box already" before anything else.

## Root cause

**2026-10-12 (silent).** The builder placed each cut on a Whisper segment's start time, on the stated assumption that "transmission boundaries ARE the whisper segment starts". That is false when a 30 s chunk opens on dead air. Reproduced on the saved probes:

| probe | segment as Whisper stamped it | where the words really are |
|---|---|---|
| story 1 | `0.00 to 29.98  211 at the Dollar Tree, with Machete, 2682 Mt. Vernon Avenue.` | 24.7 s |
| story 2 | `0.00 to 29.98  I'm going to take a break to Southside I-5, north of the rest area.` | 24.7 s |

The text matched the story (score 8), so the window search "worked", and the cut took 12 s from offset 0 of the probe: the dead air before the call. `silencedetect` on the two cuts finds 0.5 s and 0.7 s of sound in 12 s. Both `chosen_offset` values in the audit log equal the probe start exactly (1609.6 = 1634.6 - 25, 1565.8 = 1590.8 - 25).

It became visible on 10-12 because commit `8e317bea` (2026-10-09) switched the hint to `offset_s`. The hint is now exact, so the call sits at second 25 of the probe every time, and whatever precedes it is often silence. With the old minute-granular hint there was usually other traffic in front.

**Not new, only total for the first time.** The same dead-air clip sits in three earlier soundtracks in `work/social`, next to good clips that hid it: 09-21 story 3 (0.4 s of sound in 12 s), 09-22 story 3 and 09-23 story 2 (digital silence, -70 LUFS). All three logged `verify_ok: false` and were mixed. I did not check whether those three reels were posted.

**Why it shipped.** Three independent holes:
1. `make_dispatch_audio.py` warned on `verify_ok: false` and appended the piece anyway.
2. Its exit code was 0. And when it is 2, `publish_social.py` never read it: line 177 logged the last 300 characters of stdout and went on if `soundtrack.mp3` existed. The builder's stderr (where the warning went) was logged only when stdout was empty, which it never was.
3. Nothing measured the artifact. The bed was mixed at a fixed `volume=-18dB` on a bed that itself measures -18.1 LUFS, so a mix with no voice is the bed at about -36 LUFS. The published reel measures **-35.6 LUFS** (`reel.silent.mp4`).

**2026-10-09 (brake fire under a shooting card).** Two defects stacked:
1. The probe was 70 s around a clock hint that is only good to the minute, and the Pembroke transmission was outside it (it is at 415.9 s; the probe ended at 407 s). The probe transcript does not contain "Pembroke" at all.
2. The scorer then picked the best of what was left, and a drama word needed no tie to the story. "He extinguished a fire" scored 5 for "Shots fired on the 5400 block of Pembroke Avenue": 3 for `fire` as a drama word, 2 because `fuzzy_hit` treats `fired` and `fire` as the same token (0.89). The threshold was 3. The verification then passed it, for the same reason (`verify_score: 5`).

## What changed

### `scripts/brief_reel/make_dispatch_audio.py`
- **Cut placement.** The probe is transcribed with the voice detector on and word timestamps. A clip may start only on a word's own start (first word, a word after a 0.6 s pause, or a word after a full stop), with 0.15 s of pre-roll. Segment stamps are no longer used for placement. Measured on the 10-12 probes: VAD word times put the two calls at 25.55 s and 24.72 s; plain word times without VAD still put story 2 at 6.24 s, which is why VAD goes first and the plain pass is only a fallback.
- **Anchor rule (the 10-09 fix).** A window is eligible only if it carries an anchor to this story: a word of the street name, the house or block number (a "5400 block" matches 5420; "64-65" is read as 6465), or the words of the matched transcript row (most of a short row, four or more of a long one). Drama words still rank eligible windows; they can no longer make one eligible. No anchor in the probe means no clip for that story.
- **Scoring window = cut window.** Windows are scored at the shortest length a clip can end up with, from word times, so the words that pick a window are words the cut holds. It used to score 6 s and cut 8 to 20 s.
- **Clock hints get a 115 s probe** (a minute stamp spans 60 s). Only matters for transcripts older than 2026-10-10.
- **Verification is a gate.** `check_clip` refuses a clip unless: (a) the cut holds at least 1.5 s of audible speech, measured with `silencedetect`, independent of the ASR; (b) its re-transcription reads as speech (not empty, at least 3 words, not a loop); (c) that text is the picked beat (carries the anchor, or shares half its distinct words with the beat). A refused clip is dropped, never mixed. It gets up to three hearings first (raw cut, processed cut, raw cut with Whisper's temperature ladder) because a loop is often the decoder and not the audio; the 10-08 Pacific Street clip, which shipped with `verify_ok: false` on a pure digit loop, now verifies with a readable transcript.
- **Re-pacing.** `pace_and_verify` cuts every clip at the length the current count gives, drops the failures, and repeats until a round drops nothing, so the reel length and `reel_indices` always describe the clips that are actually in the mix.
- **Levels are measured.** See below.
- **Exit codes and audit.** 0 clean; 2 degraded (a story dropped, named on stderr); 4 held (no clip verified); 5 mix refused. On 4 and 5 no `soundtrack.mp3` exists (a stale one is deleted at the start of every build) and `soundtrack.json` is still written with `outcome: "held"` and the reason. Every audit now carries `outcome`, per-story `verify_reason`, `speech_s`, `piece_lufs`, `anchor`, and the mix measurements. A story with no transcript match used to exit 0; it is now degraded like any other missing story.

### `scripts/brief_reel/reel_audio_gate.py` (new)
The numbers and the checks, shared by the builder and the publisher: `loudness` (ffmpeg `ebur128`), `speech_seconds`, `transcript_problem`, `audit_problems`, `dropped_stories`. A measurement that cannot be taken returns `None`, and every caller treats `None` as a fail.

### `scripts/brief_reel/publish_social.py`
- `audio_gate(date, reel)` runs in `main` before any publish path, every run except `--verify-only`. It asks two independent questions and both must pass: does the audit log vouch for every clip in the reel, and does `reel.mp4` itself measure at or above -19 LUFS.
- A held reel is exit **6**: nothing is posted, the state file records `held: true, done: false` with the reasons, and the report prints `audio=HELD` and one `audio_problem=` line per reason. It is never exit 3, which the wrapper labels "SKIP, gate blocked".
- A degraded reel is published, `done: true` is written so no slot posts again, and the run exits **7** with `audio=DEGRADED` and one `audio_dropped=` line per story.
- The builder's exit code and stderr are logged. A build that already held today is not rebuilt by the retry slot (`--force` rebuilds).

### `~/AppData/Local/hermes/scripts/ko_social_publish.py` (outside the repo, not under git)
Three edits: the docstring exit line; `if rc not in (0, 3):` became `if rc not in (0, 3, 6, 7):` so a held or degraded run does not restart the browser and rebuild the same audio; two labels added to the final line, `REEL HELD: no usable dispatch audio, NOTHING was posted ...` for 6 and `PUBLISHED, AUDIO DEGRADED: ...` for 7. Without this edit the gate still holds; the run would only be noisier (a pointless browser restart, label `exit 6`).

### `AGENTS.md`
A "Reel audio" section with the rules above.

### Tests
`tests/test_reel_audio.py` (new, 45 tests) and `tests/test_publish_social.py` (2 existing tests kept, 18 added). The two existing tests now stub `audio_gate`, since `main` asks it.

## The decisions you asked for

**1. A degenerate clip is never mixed.** Dropped in `check_clip`, proven end to end by `test_when_no_clip_verifies_nothing_is_mixed_and_the_build_is_held` and `test_a_degenerate_clip_is_left_out_of_the_mix_and_the_build_says_so`, which run the builder's `main` and assert on what reaches the mixer.

**2. Where the gate lives: both, for different reasons.** The builder is the only place that can drop a clip and re-pace, so it must refuse there. But the builder's exit code cannot be the gate on its own: the publisher skips the builder whenever a `soundtrack.mp3` is already on disk, and the render sits between the soundtrack and what is posted. So the publisher measures the file it is about to post, on the publish path, the same place the 25 s floor lives. Either check alone would have stopped 10-12; the tests prove each one separately (`..._on_the_audit_alone`, `..._on_the_loudness_alone`).

**3. Fallback when no clip verifies: hold the reel.** No reel, no story, exit 6, alert. Why not the others:
- Bed brought up to level: 30 s of music under cards is not "the city talks, we listen", and it is what a viewer would take for a broken post. The mixer now refuses that mix by construction.
- TTS on this box: a new voice, new copy path and new failure modes, unreviewed, introduced as an emergency fallback. Not something to ship in a fix.
- Card and caption only: I did not automate it. The only card path is `post_facebook.py main`, which also renders and posts a bed-only reel as a "bonus", and it cannot be exercised without posting for real. If you want the card on a held day, that is a small separate change (a card-only entry point) and one deliberate live test.
On a held morning three things tell you: the 08:45 run's `REEL HELD` line, the 09:00 retry repeating it within seconds (no rebuild), and the existing 10:15 `bb_publish_status.py --reel-only` alarm "the reel did NOT post", because `done` is false.

**4. Levels.** All measured as EBU R128 integrated loudness, never assumed:
- Each clip: **-16 LUFS**. The chain's single-pass `loudnorm` undershoots on sparse speech (clips shipped at -24.8, -26.8 and -27.6 LUFS beside clips at -16), so each clip is measured after the chain and trimmed by one gain under a limiter, capped at +12 dB so dead air is never turned up.
- Bed: **-36 LUFS**, 20 LU under the voice. This is the balance the good days already had (bed -18.1 LUFS at -18 dB); the gain is now computed from the bed's measured loudness.
- Finished mix: **-16 LUFS**, limiter at -2 dBFS, measured true peak must be at or under -1 dBTP. The six good reels of 10-06 to 10-11 measure -16.4 LUFS, so a normal day sounds the same. -16 is the usual mobile and social target.
- Hard stops: the normaliser may lift the mix by at most +12 dB (a bed-only mix needs about +20 and is refused as "no voice track in it"); the written file is measured again and must be within 2 LU of -16; the publisher's floor on `reel.mp4` is -19 LUFS.
I chose one measured gain plus a limiter over `loudnorm` for the final stage because `loudnorm` in one pass does not hit its target (that is the undershoot above) and in two passes silently falls back to dynamic mode. A gain that is measured, applied and measured again cannot miss quietly.

**5. The 10-09 defect.** Fixed (anchor rule plus the wider clock probe). Replayed on the real audio, the Pembroke card now plays `Medic Squad 63, Medical Aid to Station 61's area, 5420 Pembroke Avenue, enter from the west, two patients`.

## Evidence: six real nights replayed through the new builder

Outputs in `%TEMP%\reelfix3\<date>\` (nothing under `work/social` was written). Whisper on CPU, 178 to 293 s per night.

| night | as published | new build | mix |
|---|---|---|---|
| 10-07 | 3 clips | 3 clips, exit 0 | -16.3 LUFS, peak -2.2 |
| 10-08 | 1 clip, `verify_ok: false`, 25 s | 3 clips, exit 0, 30 s | -16.3, -2.2 |
| 10-09 | 3 clips, story 1 a brake fire | 3 clips, exit 0, story 1 is the Pembroke call | -16.3, -2.2 |
| 10-10 | 3 clips | 3 clips, exit 0 | -16.3, -2.2 |
| 10-11 | 3 clips, story 3 opened on unrelated Lost Hills Road traffic | 3 clips, exit 0, story 3 starts on "We have 97 with a truck fire" | -16.3, -2.3 |
| 10-12 | 2 clips of dead air, **-35.6 LUFS** | 2 real clips (11.1 s and 8.2 s of speech), exit 2 | **-16.4**, -2.2 |

10-12 is exit 2 because story 3 (Panama Lane and Pebble Point) has no clip: the probe ASR does not hear that transmission in either mode. It was missing from the published reel too.

The 10-12 soundtrack was also rendered with `render_reel.py` and the resulting `reel.mp4` measured through the gate's own function: -16.4 LUFS, pass. The gate run against the real artifacts: the original published reel (`work/social/2026-10-12/scratch/reel.silent.mp4`) -35.6 LUFS, held; the 09:17 audit log, held (stories 1 and 2 in the reel without a verified clip).

## Live on the box already

The cron wrappers run this working copy, so these edits are in force at the **08:45 PT slot on 2026-10-13** whether or not anything is committed or pushed. "Hermes ships after review" covers the commit, not the behaviour. If you want tomorrow's run on the old code, the repo files have to be stashed and the three wrapper edits reverted by hand (that directory is not a git repository; the edits are listed above).

## What happens tomorrow if a clip fails verification

- **One clip fails, another verifies:** the failed clip is not mixed, the reel is re-paced over the rest and published at -16 LUFS, and the run exits 7 with `PUBLISHED, AUDIO DEGRADED` and the dropped story and its reason in the cron output. The 09:00 slot stays silent because the reel is live.
- **Every clip fails:** no soundtrack is written, nothing is posted, exit 6 with `REEL HELD` and the reasons. 09:00 repeats the alert without rebuilding. 10:15 raises "the reel did NOT post".
- **The mix or the render comes out quiet for any other reason:** held at the publisher's -19 LUFS floor, same exit 6.

## Things to know

- **Exit 7 will fire often at first.** 3 of the last 7 published reels were missing a story. On the replay only 1 of 6 is, but expect a degraded alert some mornings. That is the requirement as you wrote it; if it turns into noise, make 7 a warning line with exit 0 in one place (`publish_social.py`, the `return EXIT_DEGRADED if degraded else 0` line).
- **Today's reel directory was hand-repaired by someone else while I worked** (17:09 to 17:20: `fix_s1.wav`, `fix_s2.wav`, a new `soundtrack.mp3` and `reel.mp4` at -17.3 LUFS, the originals kept as `soundtrack.broken.mp3` and `scratch/reel.silent.mp4`). I did not touch it. Its `soundtrack.json` is still the 09:17 one, so `publish_social.py --date 2026-10-12` now exits 6 on the audit. That is the gate working as designed on an audit that vouches for nothing; replacing today's post needs its own deliberate path.
- **Another workstream was in this tree at the same time.** `scripts/make_brief_json.py` changed at 17:31 (new headline labels, a hook test) and was committed at 18:04 as `18695dae`; `scripts/brief_reel/render_reel.py` is modified in the working tree now (a "cold" opener). Neither is mine and that commit holds none of my files. My replay ran against the new labels, so headlines read "Robbery on..." where the published reel said "Incident reported on...". The cold opener keeps the 1 s intro, so the soundtrack timeline is unchanged. I did not touch the five files you listed.
- **Sound.** The final stage is now a measured gain and a limiter at -2 dBFS; the old mix peaked at -1.3 dBFS. Loudness is identical on a normal day (-16.3 against -16.4 LUFS) but nobody has listened to the new output. Listen to `%TEMP%\reelfix3\2026-10-12\soundtrack.mp3` before the first live run if you can.

## Not done, and why

- **The probe ASR is weaker than the night ASR.** The probe and the verification use `large-v3-turbo` on CPU; the night transcript uses `large-v3`. When the turbo model cannot hear a transmission the night model did (10-12 story 3), the story has no clip. Cutting straight on `offset_s` without the probe would place the cut correctly but could not be verified by the same weak model. Using `large-v3` for the probe is the fix; it costs minutes per story on this CPU and belongs in its own change.
- **Story to transcript row is still a keyword and time match** (`pick_row`). Incidents carry no pointer to the rows they were extracted from. The anchor rule guarantees the clip names the story's place; it cannot tell two calls at the same address apart. The real fix is the extractor writing its source rows on each incident.
- **Emulator (CrimeRadar) clips** go through the speech and transcript checks but not the anchor check, since their link to the story is the manifest title. No manifest has been produced since 10-09, so this path was not exercised on real data.
- **A render or builder failure other than audio still exits 3** ("gate blocked") from `build_assets`. Same family of swallowed failure, outside this brief; worth its own exit code.

## Could not verify

- A live publish, by instruction. The API legs, the state file under a real run and the Discord delivery of the new lines are covered by tests with the API stubbed, not by a real post.
- The wrapper edit: it compiles, and it was not run.
- How the new mix sounds on a phone.
- CI: the new ffmpeg tests ran here on Windows. `deploy.yml` and `daily.yml` install ffmpeg before pytest, and the tests skip without it, but they have not run on the Linux runner.
