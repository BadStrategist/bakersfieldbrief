#!/usr/bin/env python3
"""Stage 2 — TRANSCRIBE: scanner audio → JSONL of transmissions.

Preprocess: ffmpeg mono 16 kHz, band-pass ~250–3400 Hz, loudness normalize.
VAD: Silero VAD isolates speech, discards dead air (scanner feeds are
~85–90% silence) before transcription.
Engine: faster-whisper large-v3 locally; swap by setting KO_STT_ENGINE
(only "faster-whisper" is implemented — the interface is the swap point for
Deepgram Nova etc.).

Anti-hallucination guards:
  * segments are transcribed independently — no previous-text conditioning
  * segments with low confidence AND short duration are dropped
  * a no-speech night yields an empty JSONL, not hallucinated text

Output rows (JSONL): {time_local, duration, text, confidence, source_file, engine}
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = os.environ.get("KO_STT_ENGINE", "faster-whisper")
MODEL_SIZE = os.environ.get("KO_WHISPER_MODEL", "large-v3")
MIN_CONFIDENCE = float(os.environ.get("KO_MIN_CONF", "0.45"))
MIN_DURATION_S = float(os.environ.get("KO_MIN_SEG_S", "1.0"))


class TranscribeError(RuntimeError):
    pass


def _preprocess(mp3: Path, work: Path) -> Path:
    """Mono 16 kHz, band-pass 250–3400 Hz, loudness-normalized WAV."""
    if not shutil.which("ffmpeg"):
        raise TranscribeError("ffmpeg not found — install it (winget install ffmpeg / apt ffmpeg)")
    out = work / f"{mp3.stem}.wav"
    cmd = ["ffmpeg", "-y", "-i", str(mp3),
           "-ac", "1", "-ar", "16000",
           "-af", "highpass=f=250,lowpass=f=3400,loudnorm=I=-16:TP=-1.5:LRA=11",
           str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _vad_speech_segments(wav: Path, work: Path) -> list[tuple[float, float]]:
    """Silero VAD → [(start_s, end_s), ...]; raise if torch/silero missing."""
    try:
        import torch  # noqa: F401
        from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
    except ImportError as e:
        raise TranscribeError(
            f"Silero VAD unavailable ({e}). pip install torch silero-vad "
            "(CPU torch is fine for VAD).") from e
    model = load_silero_vad()
    audio = read_audio(str(wav), sampling_rate=16000)
    stamps = get_speech_timestamps(audio, model,
                                   sampling_rate=16000,
                                   min_speech_duration_ms=300,
                                   min_silence_duration_ms=500)
    return [(float(s["start"]) / 16000.0, float(s["end"]) / 16000.0)
            for s in stamps]


def _load_model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise TranscribeError(
            f"faster-whisper unavailable ({e}). pip install faster-whisper "
            "(pulls CTranslate2; large-v3 runs on CPU at int8).") from e
    print(f"    [ko-stt] loading {MODEL_SIZE} (this takes a minute)...", flush=True)
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def _transcribe_wav(model, wav: Path, seg: tuple[float, float], vocab: str) -> dict:
    """One VAD segment through faster-whisper; independent, no conditioning."""
    segs, _info = model.transcribe(
        str(wav),
        language="en",
        beam_size=1,
        vad_filter=False,          # we already VAD'd; keep whisper's own off
        initial_prompt=vocab,      # vocabulary priming (editable vocab.txt)
        audio_start=seg[0],
        audio_end=seg[1],
        condition_on_previous_text=False,
    )
    rows = []
    for s in segs:
        text = s.text.strip()
        if not text:
            continue
        conf = float(getattr(s, "avg_logprob", 0.0))
        rows.append({"text": text, "confidence": conf,
                     "start": float(s.start) + seg[0],
                     "end": float(s.end) + seg[0]})
    return rows


def transcribe(audio_dir: Path, out_jsonl: Path, tz: dt.tzinfo,
               vocab_text: str) -> int:
    """Transcribe every MP3 in audio_dir → out_jsonl. Returns row count."""
    mp3s = sorted(audio_dir.glob("*.mp3"))
    if not mp3s:
        raise TranscribeError(f"no audio blocks in {audio_dir} — run fetch first")
    count = 0
    model = None
    with tempfile.TemporaryDirectory(prefix="ko-") as td:
        work = Path(td)
        with open(out_jsonl, "w", encoding="utf-8") as out:
            for mp3 in mp3s:
                wav = _preprocess(mp3, work)
                segs = _vad_speech_segments(wav, work)
                if not segs:
                    continue
                if model is None:
                    model = _load_model()
                for (s0, s1) in segs:
                    duration = s1 - s0
                    if duration < MIN_DURATION_S:
                        continue
                    try:
                        rows = _transcribe_wav(model, wav, (s0, s1), vocab_text)
                    except Exception as e:  # noqa: BLE001
                        print(f"    [ko-stt] segment {s0:.1f}s failed: {e}", flush=True)
                        continue
                    for r in rows:
                        if r["confidence"] < MIN_CONFIDENCE and duration < 3.0:
                            continue  # low-confidence + short → drop
                        time_local = (dt.datetime.fromtimestamp(
                            int(mp3.stem.split("-")[1]), tz) +
                            dt.timedelta(seconds=r["start"])).strftime("%H:%M")
                        out.write(json.dumps({
                            "time_local": time_local,
                            "duration": round(duration, 2),
                            "text": r["text"],
                            "confidence": round(r["confidence"], 3),
                            "source_file": mp3.name,
                            "engine": f"faster-whisper:{MODEL_SIZE}",
                        }, ensure_ascii=False) + "\n")
                        count += 1
    return count


def load_vocab(path: Path) -> str:
    if not path.exists():
        return ""
    terms = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    return ", ".join(terms[:120])


if __name__ == "__main__":
    from .fetch import PACIFIC
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    audio = Path("audio") / d.isoformat()
    out = Path("transcripts") / f"{d.isoformat()}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = transcribe(audio, out, PACIFIC, load_vocab(Path("kern_overnight/vocab.txt")))
    print(f"{n} transmissions → {out}")
