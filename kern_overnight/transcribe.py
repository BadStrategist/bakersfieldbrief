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
MODEL_SIZE = os.environ.get("KO_WHISPER_MODEL", "distil-large-v3")
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
           "-af", "highpass=f=250,lowpass=f=3400,volume=10dB",
           str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _vad_speech_segments(wav: Path, work: Path) -> list[tuple[float, float]]:
    """Silero VAD → [(start_s, end_s), ...]; raise if torch/silero missing.

    Reads the 16 kHz mono PCM WAV with the stdlib `wave` module (no
    torchaudio/torchcodec — their native DLLs don't load with this machine's
    ffmpeg build) and feeds Silero a plain float32 tensor."""
    try:
        import numpy as np
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps
    except ImportError as e:
        raise TranscribeError(
            f"Silero VAD unavailable ({e}). pip install torch silero-vad "
            "(CPU torch is fine for VAD).") from e
    import wave
    with wave.open(str(wav), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise TranscribeError(f"{wav.name}: expected 16k mono PCM")
        raw = w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    audio = torch.from_numpy(audio)
    model = load_silero_vad()
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
    # Offline by default (cached models only — a HF network check once hung
    # the job for 10+ min). Set HF_HUB_OFFLINE=0 to allow a first-run
    # download of the model.
    local_only = os.environ.get("HF_HUB_OFFLINE", "1") != "0"
    try:
        return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8",
                            cpu_threads=8, local_files_only=local_only)
    except Exception as e:  # noqa: BLE001 — cache miss → allow download
        raise TranscribeError(
            "faster-whisper model not in cache. Run once with "
            "HF_HUB_OFFLINE=0 (or `huggingface-cli download "
            f"Systran/faster-whisper-{MODEL_SIZE}`) to fetch it. ({e})") from e


def _transcribe_wav(model, audio: "np.ndarray", seg: tuple[float, float], vocab: str) -> list[dict]:
    """One VAD segment through faster-whisper; independent, no conditioning.

    `audio` is the full preprocessed float32 array (read once by the caller);
    the segment is sliced out (audio_start/audio_end were removed from
    faster-whisper's API) and timestamps re-anchored."""
    s0, s1 = seg
    chunk = audio[int(s0 * 16000):int(s1 * 16000)]
    if len(chunk) == 0:
        return []
    segs, _info = model.transcribe(
        chunk,
        language="en",
        beam_size=1,
        vad_filter=False,          # we already VAD'd; keep whisper's own off
        initial_prompt=vocab,      # vocabulary priming (editable vocab.txt)
        condition_on_previous_text=False,
    )
    rows = []
    for s in segs:
        text = s.text.strip()
        if not text:
            continue
        conf = float(getattr(s, "avg_logprob", 0.0))
        rows.append({"text": text, "confidence": conf,
                     "start": float(s.start) + s0,
                     "end": float(s.end) + s0})
    return rows


def _merge_segments(segs: list[tuple[float, float]], gap_s: float = 10.0) -> list[tuple[float, float]]:
    """Merge VAD segments separated by < gap_s of silence.

    Whisper's per-call overhead dominates on scanner audio (each call costs
    ~10-18s of fixed decode), so bursts separated by up to 10 s of dead air
    are merged into one call — measured 41 calls vs 161 raw segments, 39%
    faster wall time (758s vs 1241s per block)."""
    if not segs:
        return []
    merged = [list(segs[0])]
    for s0, s1 in segs[1:]:
        if s0 - merged[-1][1] < gap_s:
            merged[-1][1] = max(merged[-1][1], s1)
        else:
            merged.append([s0, s1])
    return [(a, b) for a, b in merged]


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
                segs = _merge_segments(_vad_speech_segments(wav, work))
                if not segs:
                    continue
                if model is None:
                    model = _load_model()
                # read the preprocessed array ONCE per block (the segments
                # are slices of it — no per-segment file I/O)
                import numpy as np
                import wave as wave_mod
                with wave_mod.open(str(wav), "rb") as w:
                    raw = w.readframes(w.getnframes())
                audio_arr = (np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                             / 32768.0)
                for (s0, s1) in segs:
                    duration = s1 - s0
                    if duration < MIN_DURATION_S:
                        continue
                    try:
                        rows = _transcribe_wav(model, audio_arr, (s0, s1), vocab_text)
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
