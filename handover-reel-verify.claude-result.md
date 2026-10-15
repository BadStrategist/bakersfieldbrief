# Claude result for handover-reel-verify.md

- ran: 2026-10-12 18:41 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com
-The verdict is in `handover-reel-verify.claude-result.md`. The three commits do what they say, and on the scanner path no clip that fails verification can reach the mix, but you are wrong or incomplete in five places.

## Where you are wrong

1. **`tests/test_reel_audio.py` is not in `fe86bead`.** It is still untracked, and it holds all 45 of the builder's tests, including the two that prove a degenerate clip never reaches the mixer. "Full suite green" was true on this box only because the file is on disk; CI ran without it. It passes here and needs committing.
2. **There was no CRLF conversion.** Every blob for the reel files is LF in `fe86bead~1`, `fe86bead` and `HEAD`. What you saw is `core.autocrlf=true` in the working copy. Nothing to undo.
3. **Today's state file was flipped to held at 18:43:32, during this review, and not by me.** `work/social/2026-10-12.json` now says `done: false, held: true` while its `api` block still shows all four legs live. Something ran the publisher for 2026-10-12; the tests don't touch that directory, and I did not find out what did. Holding was right, since the repaired soundtrack sits beside the old 09:17 audit. Clearing `done` on a posted day is a defect in my code: `report_held` writes `done: False` unconditionally.
4. **CrimeRadar clips skip the third check.** `check_clip` applies "the text is the beat that was picked" only to scanner clips. An emulator clip is mixed on speech plus a readable transcript. No manifest has been written since early October, so it is dormant, but AGENTS.md states the rule without this exception.
5. **The no-area test in `18695dae` claims more than it checks.** It asserts only `where == ""`. `story_json` still defaults the city: 63 of 1,214 incidents on disk build "<label> in Bakersfield" with place `BAKERSFIELD`, which breaks the AGENTS.md rule in the title arm and on every story card.

## Your four questions

- **Hook parity:** yes, it is the alternation I intended. The window gives six cold and six title days, strictly alternating, each opener twice on each bed. The first cold reel is Thursday 10-15; 10-14 itself is a title day. Weekdays are not balanced (cold has a Monday and no Tuesday). Keep the window a constant in the file: an env var is state git does not record, and the cron runs the working copy.
- **`lead_card()`:** it holds up, measured over all 1,214 incidents on disk.
  - **Long label:** no label wraps past two lines; the smallest shrinks to 76 px.
  - **No area:** the place line is skipped cleanly.
  - **No label:** the headline fallback can run to four lines, but the rule never lands lower than y=868 against the safe line at y=1248.
  - **Minor:** the shrink floor is 68 px, not 72, and the place line shows a preposition bug ("on near Lynwood and Height streets").
- **Warn-only:** nothing on the scanner path. Besides item 4, the gaps are softer:
  - Clip level is recorded but not enforced at -16 LUFS.
  - The 1.5 s speech floor does not scale with a 20 s cut.
  - A short cut is not padded, so later scenes drift ahead of their audio.
- **Committed as found:** nothing needs reverting.

The file also covers two label issues for your judgement: free-text types like "Shots fired" now go on screen unqualified (`shots fired, unfounded` becomes "Shots fired"), and lower-casing produces "Dui crash".

I did not re-render or re-measure your LUFS and frame figures; they are taken as reported. One of my shell commands misfired into a read-only `find` across C: for about three minutes before I stopped it; it changed nothing.

--- exit: 0 ---
in Bakersfield"). That breaks the AGENTS.md rule and is
   on screen in the title arm and on every story card; only the cold opener's place line is
   clean. I flagged this in `reel-hook-analysis.md` and left it; it is still open, and it also
   means the two arms differ in more than the opener on a no-area lead.

## Your four questions

### `hook_for_date()` parity and the env var

Yes, it is the alternation I intended, and it matches `reel-hook-analysis.md` section 5 date
for date. Run against the real function:

| date | day | opener | bed |
|---|---|---|---|
| 10-14 | Wed | title | 2 |
| 10-15 | Thu | cold | 3 |
| 10-16 | Fri | title | 1 |
| 10-17 | Sat | cold | 2 |
| 10-18 | Sun | title | 3 |
| 10-19 | Mon | cold | 1 |
| 10-20 | Tue | title | 2 |
| 10-21 | Wed | cold | 3 |
| 10-22 | Thu | title | 1 |
| 10-23 | Fri | cold | 2 |
| 10-24 | Sat | title | 3 |
| 10-25 | Sun | cold | 1 |

Six and six, strict alternation, each opener twice on each bed. 10-13 and 10-26 onward are
title. Two things to know when reading the result:

- The first cold reel is Thursday 10-15, not 10-14. "Inert until 2026-10-14" is true, but
  10-14 itself renders the old title card.
- Weekdays are not balanced: cold has a Monday and no Tuesday, title the reverse. Twelve days
  cannot balance both beds and weekdays; I chose beds.
- A held day (exit 6) removes a row from one arm, and a degraded day (exit 7) shortens the
  story count. Note both on the sheet; the 4-of-6 pair rule needs the pair dropped, not scored.

Keep the window a constant in the file. An env var on the box is state that git does not
record, the cron runs the working copy, and the analysis has to be able to say which arm a date
was from history alone. `brief.json` already records `hook` per date as a second witness.

### `lead_card()` with no label, no area, a long label

It holds up. Measured by replaying its layout over all 1,214 incidents in `incidents/`
(62 nights, 283 distinct types, 263 distinct labels), not a sample:

- **Long label:** no label wraps past two lines. 251 of 263 labels set at the full 124 px;
  12 shrink, the smallest to 76 px ("Suspicious circumstances at a school"). Widest line
  955 px of the 960 allowed. `label_for` caps a free-text type at six words, which is what
  bounds this. Nothing caps the line count in `lead_card` itself, as you say.
- **No area:** 63 incidents. `where` is empty, the place line is skipped, the card is the
  time and the label. Correct.
- **No label** (an old or hand-written brief): falls back to the headline and suppresses the
  place line. 177 of 1,214 headlines run to three or four lines at the floor size. The lowest
  the rule ever lands is y=738 with a label (868 with a two-line place), against the safe line
  at y=1248, so nothing reaches the caption bar; the subhead is what gives way.
- No story on disk produces an empty wrapped line or an over-wide one.

Small defects, none blocking:
- The shrink loop's floor is 68 px, not the 72 the code reads as (`while size > 72` steps 76 to 68).
- If story 1 has no background, the cold arm falls through to `story_card`, whose text fades
  in from alpha 0: frame 0, the thumbnail, is blank. Not reachable from `make_brief_json`
  (it always writes `"backgrounds": "auto"` and `load_or_make` never returns None); only a
  hand-written `"backgrounds": "none"` brief with `"hook": "cold"` hits it.
- The place line shows a preposition bug that the headline used to bury: "on near Lynwood and
  Height streets", "on 5500 block of Silver Crossing Street".

### Is anything still warn-only in the audio path

On the scanner path, no. I traced every branch of `check_clip`, `pace_and_verify`,
`mix_soundtrack` and `main`: a clip is appended to the mix only when `check_clip` returned a
piece in the final pacing round, every unmeasurable value is a refusal, and exits 4 and 5
leave no `soundtrack.mp3`. The publisher asks `audio_gate` before the API on every run except
`--verify-only`, which posts nothing. The wrapper handles 6 and 7 (line 254 of
`ko_social_publish.py`).

What is left, in order of weight:

- The CrimeRadar exception, item 4 above. The only real hole.
- **Clip level is recorded, not enforced.** `level_to` caps its lift at +12 dB and returns
  whatever results; `piece_lufs` goes into the audit and nothing compares it to -16. AGENTS.md
  says each clip is at -16 LUFS. The finished mix is checked, so a quiet clip cannot ship a
  quiet reel, but one clip can sit well under another.
- **The speech floor is absolute.** 1.5 s passes in any cut, and a single-story reel cuts 20 s.
  A clip that is mostly dead air after its first sentence verifies, and the mix still measures
  -16 LUFS because loudness gating ignores the silence. A floor that scales with the cut
  (say 25 percent) would close it.
- **A short cut is not padded.** A clip cut near the end of a block, or an emulator clip
  shorter than its slot, yields a short piece; `duration` in the audit is computed, not
  measured, and every later scene drifts ahead of its audio. The only message is the builder's
  `WARNING: under the 25 s floor`, and the publisher then returns 3 ("gate blocked") for it.
- `_prune_brief_to_audio` swallows any failure with a WARN and renders the unpruned brief.
  An unreadable audit is then caught by the gate; a failed write of `brief.json` is not, and
  would show a dropped story's card. The gate could compare the brief's story count to
  `reel_indices`.
- The raw cut's return code in `check_clip` is ignored (only the processed cut's is read).
- `find_beat` falls back to a pass without the voice detector. AGENTS.md says a cut starts
  from a probe "transcribed with the voice detector on". The fallback's clip still has to pass
  all three checks, so this is a wording gap, not a hole.
- Cascading drops: a clip that verified at 8.3 s is re-cut at 12 s and then 20 s as others
  fail, and must verify again each time. It fails closed (held), but can hold a day that had
  one good clip.

### Should anything not have been committed as found

Nothing needs reverting. What needs adding or correcting is items 1, 3 and 4 above. Also:

- The new labels put a dispatcher's free-text type on screen at 124 px on frame 0. 221 of the
  283 types are off the table; 25 of them, covering 64 incidents, name a grave event
  ("Shots fired" 15, "Overdose" 10, "Robbery" 6, "Stabbing" 2, "Gunshot wound", "Child
  endangerment"). Only kidnapping and hostage get "Reported". One real case reads badly:
  type `shots fired, unfounded` becomes "Shots fired". Your call whether that list should grow.
- Lower-casing loses acronyms: "Dui crash", "Dui driver", "Possible dui", "Dui arrest".
- Your replay figure (0 of 66 generic) is right for those 22 briefs; the generic label still
  exists for the eleven vague types, so it is a property of that data, not a guarantee.

## What I did not do

- No render, no audio rebuild, no publish. Your LUFS figures and frame checks are taken as
  reported; I did not re-measure them.
- I did not find out what ran the publisher at 18:43:32.
- One of my shell commands misfired into a filesystem `find` across C: for about three
  minutes before I stopped it. It was read-only and changed nothing.
