# Handover: close the audio path's warn-only gaps

Review only for anything you cannot prove. Fix the code where you can prove it.

## Where things stand

Your audio gate is committed as found (`fe86bead`), the cold open is installed from your
proto and inert until 2026-10-14 (`2a6ddf0e`), and your review of the headline work landed.
Two of the three defects you found in the copy are fixed and pushed (`0e53dc93`):

- a hedge is no longer dropped ("Shots fired, unfounded" no longer reads as "Shots fired")
- a lower-cased acronym is no longer lower-cased ("Possible dui" is now "Possible DUI")
- a place that carries its own locator no longer gets a second one ("on near Lynwood and
  Height streets" is now "near Lynwood and Height streets")

Re-measured over all of `incidents/`: 346 distinct types over 1,214 rows, 0 hedges dropped,
0 lower-cased acronyms; 1,033 areas, 21 phrases corrected, 0 double locators left. A guard
test in `tests/test_brief_labels.py` re-runs both checks over the data.

`make_brief_json.py` and `render_reel.py` are now closed to you unless a task below needs a
line in one of them. Say exactly which line and why.

## The gaps you flagged, to close or to refuse with a reason

1. **Clip level is recorded but not enforced at -16 LUFS.** A clip can sit at -24 LUFS and
   still be picked. Enforce it, or say what should happen instead when the best clip on the
   day is quiet.
2. **The 1.5 s speech floor does not scale with a 20 s cut.** A 20 s cut carrying 2 s of
   speech passes today. The floor should be a proportion of the cut, with a floor below
   which the story is dropped as having no usable audio.
3. **A short cut is not padded, so later scenes drift ahead of their audio.** Prove the
   drift on a real day first, then fix it in the mix (pad the cut, or re-time the scene
   plan to the audio that exists). Picture ahead of its own audio is a correctness defect,
   not a polish item.

## One question I owe you

You wrote that "the wrapper edit" compiles but was never run. Name the file and the line.
If it is not in the commit, say where it lives.

## Rules

- No live publish, and nothing that reaches the API. A dry run only.
- No band-aids: if a fix needs the builder's timeline layout changed, change it.
- Re-measure against every reel you have on disk, never a sample, and print the before and
  after counts.
- Keep `hook_for_date` and the cold-open scene plan as they are: the A/B window opens
  2026-10-14 and the first cold reel is Thursday 2026-10-15.
- Report what you could not verify, in your own words, at the end.
