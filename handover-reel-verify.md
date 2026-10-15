# Handover: verify the reel changes now on main (review only, no pushes)

Workdir: `C:/Users/tscac/Projects/BakersfieldBrief.com`

Your audio-fix run stalled at 17:57 with your work complete on disk and no summary
written. I verified it, committed it, and installed the other half of your hook plan.
Read the commits and tell me where I am wrong.

## The three commits

- `18695dae` reel: real headlines for unmapped dispatch types. Mine, from your staged
  `work/reel_hook/proto/make_brief_json.py`.
- `fe86bead` reel audio: a clip that does not verify is dropped, never mixed. Yours,
  committed as found: `reel_audio_gate.py`, `make_dispatch_audio.py`,
  `publish_social.py`, `tests/test_publish_social.py`, `AGENTS.md`.
- `2a6ddf0e` reel: the cold open for the hook test, inert until 2026-10-14. Mine, from
  your staged `work/reel_hook/proto/render_reel.py`.

## What I verified, and how

1. Headlines: replayed `make_brief_json.py` over the 22 shipped reel briefs on the same
   incident data. Old builder 33 of 66 stories generic (50 percent), new builder 0 of 66.
   33 headlines rewritten.
2. Audio, end to end on the day that failed: rebuilt 2026-10-12, cuts landing at 1635.1 s
   and 1590.5 s against the shipped 1609.6 s and 1565.8 s, mix -16.4 LUFS, peak -2.2 dBTP,
   exit 0. Your gate refuses that day's shipped mix (-35.5 LUFS) and passes 2026-10-11
   (-16.6 LUFS). Full suite green, CI deploy green.
3. Cold open: rendered both arms from one brief. The cold arm's frame 0 carries the label
   and the place in the top third; the control arm draws its news line at about y=1300,
   under the caption bar.

## Answer these

- Is `hook_for_date()`'s date parity the alternation you intended for 2026-10-14 to
  2026-10-25, and should the window come from an env var rather than a constant in the
  file?
- Does `lead_card()` hold up for a story with no label, or no area, and for a label long
  enough to wrap past two lines? Nothing caps that today.
- In the audio path, is anything still warn-only on any branch, i.e. can a clip that fails
  verification still reach the mix?
- Anything in your committed audio work that should not have been committed as found, in
  particular the CRLF conversion on `reel_audio_gate.py` and `tests/test_publish_social.py`.

No pushes, no deploys, no edits outside your own notes. Write the verdict to
`handover-reel-verify.claude-result.md`.
