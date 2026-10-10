#!/usr/bin/env python3
"""Deepgram STT engine — backup for faster-whisper (accuracy-first).

Switched via KO_STT_ENGINE=deepgram. Requires DEEPGRAM_API_KEY in .env.

Why accuracy-first: Deepgram Nova-3 is state-of-the-art on narrowband radio
audio. We send only the VAD-merged speech segments (never the dead air), so
billing (~$0.0059/min) and latency stay proportional to actual speech.

Row shape matches the whisper engine exactly:
  {time_local, duration, text, confidence, source_file, engine}
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import requests

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
MODEL = os.environ.get("KO_DEEPGRAM_MODEL", "nova-3")

VOCAB_BOOST = [
    "Bakersfield", "Kern County", "KCSO", "BPD", "KCFD", "Oildale",
    "Rosedale", "Chester Avenue", "Ming Avenue", "Truxtun", "Highway 99",
    "Highway 58", "code 3", "structure fire", "vegetation fire", "Panama Lane",
]


class DeepgramError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not k:
        raise DeepgramError(
            "KO_STT_ENGINE=deepgram but DEEPGRAM_API_KEY not set "
            "(add it to .env)")
    return k


def _segment_rows(segments: list[dict], block_epoch: int,
                  tz: dt.tzinfo, source_file: str,
                  base_s: float = 0.0) -> list[dict]:
    """Map Deepgram utterance timestamps → the shared row shape.

    `base_s` is the offset of this segment inside the block. Deepgram reports
    timestamps relative to the audio that was POSTed, so without `base_s` every
    row of every segment after the first landed at the wrong time. The row now
    carries `offset_s` into the block and leaves `time_local` to the caller's
    window rule, which stamps it from that offset.
    """
    rows = []
    for s in segments:
        text = (s.get("transcript") or "").strip()
        if not text:
            continue
        conf = float(s.get("confidence", 0.0) or 0.0)
        start = base_s + float(s.get("start", 0.0))
        end = base_s + float(s.get("end", 0.0))
        rows.append({
            "duration": round(max(end - start, 0.1), 2),
            "text": text,
            "confidence": round(conf, 3),
            "source_file": source_file,
            "engine": f"deepgram:{MODEL}",
            "offset_s": round(start, 1),
        })
    return rows


def transcribe_segments(segments_wavs: list[tuple[float, float, bytes]],
                        block_epoch: int, tz: dt.tzinfo,
                        source_file: str) -> list[dict]:
    """Transcribe VAD-isolated segment audio bytes with Deepgram Nova.

    segments_wavs: [(start_s, end_s, wav_bytes), ...] — the caller slices
    speech out of the preprocessed block so billing stays on real audio.
    Returns JSONL-style rows carrying `offset_s` into the block; the
    caller's window rule stamps `time_local` from that offset.
    """
    api_key = _key()
    params = {
        "model": MODEL, "language": "en", "punctuate": "true",
        "smart_format": "true", "utterances": "true",
    }
    for term in VOCAB_BOOST:
        params.setdefault("keywords", []).append(term)
    headers = {"Authorization": f"Token {api_key}",
               "Content-Type": "audio/wav"}
    all_rows: list[dict] = []
    for start_s, _end_s, wav_bytes in segments_wavs:
        r = requests.post(DEEPGRAM_URL, params=params, headers=headers,
                          data=wav_bytes, timeout=300)
        if r.status_code == 402:
            raise DeepgramError("Deepgram billing/quota exceeded (HTTP 402)")
        r.raise_for_status()
        res = r.json()
        utterances = ((res.get("results") or {}).get("utterances") or [])
        all_rows += _segment_rows(utterances, block_epoch, tz, source_file,
                                  base_s=start_s)
    return all_rows
