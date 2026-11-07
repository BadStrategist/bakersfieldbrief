"""A transcriber that waited for the lock must not redo blocks finished while it waited.

2026-10-08 and 10-09 each have 19 duplicated transcript rows. transcribe() read the
list of blocks already in the JSONL, THEN took the lock; a phase 2 that queued
behind a still-running phase 1 transcribed every block phase 1 finished in the
meantime a second time. The list is read under the lock now.

Run: .venv/Scripts/python.exe -m pytest tests/test_transcribe_lock_order.py -q
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json

from kern_overnight import transcribe as T


def _row(block: str, text: str) -> dict:
    return {"text": text, "confidence": 0.9, "duration": 5.0, "source_file": block,
            "offset_s": 1.0, "time_local": "01:00"}


def test_blocks_finished_while_waiting_for_the_lock_are_not_redone(tmp_path, monkeypatch):
    audio = tmp_path / "audio"
    audio.mkdir()
    a, b = "14029-1794019045.mp3", "14029-1794020845.mp3"
    for n in (a, b):
        (audio / n).write_bytes(b"x")
    out = tmp_path / "t.jsonl"
    out.write_text("", encoding="utf-8")

    @contextlib.contextmanager
    def lock_released_by_the_other_run(path, wait=900.0):
        # While we "waited", the other run finished block A and let go of the lock.
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_row(a, "from the other run")) + "\n")
        yield

    done = []
    monkeypatch.setattr(T, "_transcript_lock", lock_released_by_the_other_run)
    monkeypatch.setattr(T, "ENGINE", "faster-whisper")
    monkeypatch.setattr(T, "_W_MODEL", object())
    monkeypatch.setattr(T, "_preprocess", lambda mp3, work: mp3)
    monkeypatch.setattr(T, "_vad_speech_segments", lambda wav, work: [(0.0, 5.0)])
    monkeypatch.setattr(T, "_merge_segments", lambda segs: segs)
    monkeypatch.setattr(T, "_ko_checkpoint", lambda *a, **k: None)

    def whisper(model, wav, segs, epoch, tz, name, vocab):
        done.append(name)
        return [_row(name, "ours")], 0
    monkeypatch.setattr(T, "_transcribe_whisper", whisper)

    n = T.transcribe(audio, out, dt.timezone.utc, "", workers=1, append=True)

    assert done == [b]            # A was already there by the time we held the lock
    assert n == 1
    blocks = [json.loads(ln)["source_file"] for ln in out.read_text().splitlines() if ln]
    assert sorted(blocks) == sorted([a, b])
