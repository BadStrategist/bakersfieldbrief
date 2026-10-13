#!/usr/bin/env python
"""reel_audio_gate.py: the numbers and the checks that decide whether a reel's
soundtrack is fit to publish. One module, two callers:

  make_dispatch_audio.py  builds the soundtrack and refuses to mix a clip that
                          fails a check here;
  publish_social.py       re-reads the builder's audit log and measures the
                          finished reel.mp4 before anything is posted.

Why both: on 2026-10-12 the builder warned that both clips re-transcribed to
nothing, mixed them anyway and exited 0, and the publisher never looked. The
reel went out at -35.6 LUFS (bed only). The builder's exit code alone is not a
gate, because the publisher reuses a soundtrack that is already on disk without
running the builder at all. The artifact that is about to be posted is measured
where it is posted.

Levels (EBU R128, measured with ffmpeg's ebur128, never assumed):
  VOICE_LUFS  -16   each dispatch clip, and the finished mix. The six good reels
                    of 2026-10-06..11 measured -16.4 LUFS, so a normal day sounds
                    the same; -16 is also the usual mobile/social target.
  BED_LUFS    -36   the music bed, 20 LU under the voice. The beds measure -18.1
                    LUFS and were mixed at a fixed -18 dB, which is this same
                    balance; the difference is that the gain is now computed from
                    the bed's measured level instead of assumed.
  PEAK        -1.5  dBTP target for the mix (limiter at -2 dBFS; the MP3 and the
                    reel's AAC encode each add a few tenths).
"""
from __future__ import annotations

import re
import subprocess

VOICE_LUFS = -16.0
BED_LUFS = -36.0
MIX_LUFS = -16.0
MIX_TOLERANCE = 2.0          # the finished mix must land within this of MIX_LUFS
MIN_MIX_LUFS = -19.0         # publish floor for the finished reel
LIMIT_DB = -2.0              # limiter ceiling (sample peak)
MAX_PEAK_DB = -1.0           # measured true peak may not exceed this
# The normaliser may not lift a mix by more than this. A mix with a real voice
# track needs a decibel or two; a mix that needs twenty is the bed on its own,
# and turning that up would publish 30 s of loud music with no dispatch audio.
MAX_MIX_GAIN = 12.0
MAX_VOICE_GAIN = 12.0        # same idea per clip: never amplify dead air
# A levelled clip must MEASURE within this of VOICE_LUFS or it is not mixed. The
# level used to be written to the audit log and compared with nothing. Measured
# on all 82 mixed clips on disk (2026-09-17..10-12 and the replays): the 36 the
# measured trim levelled sit between -15.9 and -16.2; of the 46 the old
# single-pass loudnorm left alone, 16 are more than 1 LU out (-14.0 to -27.6,
# and the five clips of dead air at -31.5 and under).
CLIP_TOLERANCE = 1.0
# A clip must hold this much audible speech. Measured on every clip in
# work/social (2026-09-18..10-12): the 39 good clips held 2.6 s or more, the six
# clips of dead air held 0.7 s or less.
MIN_SPEECH_S = 1.5
# ...and that floor grows with the cut: 1.5 s is a sentence in a 6 s slot and
# dead air with a cough in it in a 20 s one. The speech must be this share of
# the SLOT the scene plan gives the clip (not of the audio that was found, so a
# cut that ran out of block early is judged with its padding). On the same 82
# clips the five of dead air are 6 percent or less and every real one is 33
# percent or more, so nothing that verified on disk is under this line.
MIN_SPEECH_SHARE = 0.25
SPEECH_NOISE = "-35dB"
# The soundtrack is LEAD_S of bed, one slot per clip, TAIL_S of bed, and the
# picture is cut to the same plan (render_reel.frame: 1 s intro, 4 s outro, the
# rest split evenly). The finished audio and the finished reel may be this far
# off that plan and no further; an MP3 or AAC encode adds about 0.05 s.
LEAD_S, TAIL_S = 1.0, 4.0
PLAN_TOLERANCE = 0.25
MIN_WORDS = 3                # a re-transcription shorter than this proves nothing
MIN_DISTINCT = 0.25          # distinct/total words; a loop ("5-5-5-5") is near 0

OUTCOMES_PUBLISHABLE = ("ok", "degraded")


def _ffmpeg_null(path, af, timeout=120):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                        "-vn", "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stderr or ""


def loudness(path) -> dict | None:
    """{'lufs': integrated loudness, 'peak': true peak in dBFS}, or None when it
    cannot be measured. None is never a pass: every caller treats it as a fail.
    Digital silence reads as lufs -70.0."""
    try:
        rc, err = _ffmpeg_null(path, "ebur128=peak=true")
    except Exception:  # noqa: BLE001
        return None
    if rc != 0 or "Summary:" not in err:
        return None
    tail = err[err.rfind("Summary:"):]
    i = re.search(r"\bI:\s+(-?[\d.]+|-inf)\s+LUFS", tail)
    p = re.search(r"\bPeak:\s+(-?[\d.]+|-inf)\s+dBFS", tail)
    if not i:
        return None

    def num(m):
        return -70.0 if (m is None or m.group(1) == "-inf") else float(m.group(1))
    return {"lufs": max(-70.0, num(i)), "peak": num(p)}


def duration(path) -> float | None:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def speech_seconds(path, noise: str = SPEECH_NOISE) -> float | None:
    """Seconds of the file that are not silence. Independent of the ASR on
    purpose: whisper returning text is not proof that the cut holds a voice."""
    dur = duration(path)
    if dur is None:
        return None
    try:
        rc, err = _ffmpeg_null(path, f"silencedetect=noise={noise}:d=0.4")
    except Exception:  # noqa: BLE001
        return None
    if rc != 0:
        return None
    silent = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err))
    return max(0.0, dur - silent)


def speech_floor(slot_s: float) -> float:
    """Seconds of audible speech a clip needs to fill a slot of this length."""
    return max(MIN_SPEECH_S, MIN_SPEECH_SHARE * slot_s)


def plan_seconds(clips: int, slot_s: float) -> float:
    """How long a soundtrack of `clips` slots is, and so how long the reel is."""
    return LEAD_S + slot_s * clips + TAIL_S


def timeline_problems(audit, scenes, reel_s) -> list[str]:
    """Reasons the picture is not in step with the soundtrack.

    The render gives each of `scenes` stories (reel_s - LEAD_S - TAIL_S) / scenes
    seconds; the soundtrack gives each clip `story_len`. They are the same number
    only when the reel is as long as the clip plan says and the picture has one
    scene per clip. Anything else puts every scene after the first off its own
    audio. `scenes` is the story count of the brief.json that was rendered,
    `reel_s` the measured length of reel.mp4; None for either is a problem."""
    idx = audit.get("reel_indices") if isinstance(audit, dict) else None
    slot = audit.get("story_len") if isinstance(audit, dict) else None
    if not isinstance(idx, list) or not idx or not isinstance(slot, (int, float)) or slot <= 0:
        return ["the audit log carries no clip plan (story_len, reel_indices)"]
    out = []
    if scenes is None:
        out.append("the story count of brief.json could not be read")
    elif scenes != len(idx):
        out.append(f"the picture has {scenes} scenes and the soundtrack {len(idx)} "
                   f"clips: every scene after the first is off its audio")
    plan = plan_seconds(len(idx), slot)
    if reel_s is None:
        out.append("the length of the reel could not be measured")
    elif abs(reel_s - plan) > PLAN_TOLERANCE:
        out.append(f"the reel runs {reel_s:.2f} s and the clip plan is {plan:.2f} s "
                   f"({len(idx)} x {slot:.2f} s): the scenes are not on their clips")
    return out


def collapse_loops(toks: list[str], max_n: int = 6) -> list[str]:
    """The tokens with every immediate repeat of a 1..max_n word phrase removed.

    Whisper on a standalone cut of narrowband radio can read the first sentence
    correctly and then loop ("...north Chester, 2-4-5-0-1-2-4-5-0-1-2-4-5-0-1").
    The loop is the decoder, not the audio, so it is taken out before the text
    is judged; what is left still has to be enough words and the right ones."""
    out = list(toks)
    changed = True
    while changed:
        changed = False
        for n in range(1, max_n + 1):
            i, kept = 0, []
            while i < len(out):
                if len(kept) >= n and out[i:i + n] == kept[-n:]:
                    i += n
                    changed = True
                else:
                    kept.append(out[i])
                    i += 1
            out = kept
    return out


def transcript_problem(lines) -> str | None:
    """Why a re-transcription is unusable, or None when it reads as speech."""
    text = " ".join(lines or [])
    toks = re.findall(r"[a-z0-9]+", text.lower())
    if not toks:
        return "re-transcription came back empty"
    said = collapse_loops(toks)
    if len(said) < MIN_WORDS:
        if len(toks) >= 2 * MIN_WORDS:
            return (f"re-transcription is a loop ({len(toks)} tokens, "
                    f"{len(said)} once the repeats are removed)")
        return f"re-transcription is {len(said)} word(s)"
    ratio = len(set(said)) / len(said)
    if ratio <= MIN_DISTINCT:
        return f"re-transcription is a loop (distinct ratio {ratio:.2f})"
    return None


def audit_problems(audit) -> list[str]:
    """Reasons the builder's audit log does not vouch for the soundtrack.

    An audit with no `outcome` was written before this gate existed (or by
    something else), so it vouches for nothing."""
    if not isinstance(audit, dict):
        return ["audit log is not readable"]
    out = []
    outcome = audit.get("outcome")
    if outcome not in OUTCOMES_PUBLISHABLE:
        out.append(f"audit outcome is {outcome!r}"
                   + (f" ({audit.get('held_reason')})" if audit.get("held_reason") else ""))
    idx = audit.get("reel_indices")
    stories = audit.get("stories") or []
    if not isinstance(idx, list) or not idx:
        out.append("no story carries a verified clip")
        return out
    by_pos = {s.get("index", 0) - 1: s for s in stories if isinstance(s, dict)}
    for i in idx:
        s = by_pos.get(i)
        if s is None:
            out.append(f"story {i + 1} is in the reel but not in the audit log")
        elif s.get("verify_ok") is not True or s.get("dropped"):
            out.append(f"story {i + 1} is in the reel without a verified clip "
                       f"({s.get('verify_reason') or s.get('error') or 'verify_ok is not true'})")
    return out


def dropped_stories(audit) -> list[str]:
    """One line per brief story that did not make the reel."""
    idx = set(audit.get("reel_indices") or [])
    out = []
    for s in audit.get("stories") or []:
        if s.get("index", 0) - 1 in idx:
            continue
        why = s.get("verify_reason") or s.get("error") or "no clip"
        out.append(f"story {s.get('index')} ({s.get('headline')}): {why}")
    return out
