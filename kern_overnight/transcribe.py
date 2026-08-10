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


def _in_overnight_window(epoch: int, date: dt.date, tz: dt.tzinfo) -> bool:
    """True if `epoch` falls in the 21:00→06:00 overnight window for `date`."""
    w_start = int(dt.datetime.combine(date - dt.timedelta(days=1), dt.time(21, 0), tz).timestamp())
    w_end = int(dt.datetime.combine(date, dt.time(6, 0), tz).timestamp())
    return w_start <= epoch < w_end


def transcribe(audio_dir: Path, out_jsonl: Path, tz: dt.tzinfo,
               vocab_text: str, date: dt.date | None = None) -> int:
    """Transcribe the overnight-window MP3s in audio_dir → out_jsonl.

    When `date` is given, only blocks whose epoch falls in that night's
    21:00→06:00 window are processed — the audio dir may hold extra
    out-of-window archives (the fetch listings return the whole calendar
    days). Returns row count."""
    mp3s = sorted(audio_dir.glob("*.mp3"))
    if date is not None:
        mp3s = [p for p in mp3s
                if _in_overnight_window(_epoch_from_name(p.name) or 0, date, tz)]
    if not mp3s:
        raise TranscribeError(
            f"no overnight-window audio blocks in {audio_dir} — run fetch first")
    print(f"    [ko-stt] {len(mp3s)} blocks in window (of "
          f"{len(list(audio_dir.glob('*.mp3')))} on disk)", flush=True)
    count = 0
    model = None
    engine = ENGINE  # KO_STT_ENGINE: faster-whisper (default) | deepgram
    with tempfile.TemporaryDirectory(prefix="ko-") as td:
        work = Path(td)
        with open(out_jsonl, "w", encoding="utf-8") as out:
            for mp3 in mp3s:
                wav = _preprocess(mp3, work)
                segs = _merge_segments(_vad_speech_segments(wav, work))
                if not segs:
                    continue
                block_epoch = int(mp3.stem.split("-")[1])
                if engine == "deepgram":
                    rows = _transcribe_deepgram(wav, segs, block_epoch, tz, mp3.name)
                else:
                    if model is None:
                        model = _load_model()
                    rows = _transcribe_whisper(model, wav, segs, block_epoch,
                                               tz, mp3.name, vocab_text)
                for r in rows:
                    if r["confidence"] < MIN_CONFIDENCE and r["duration"] < 3.0:
                        continue  # low-confidence + short → drop
                    out.write(json.dumps(r, ensure_ascii=False) + "\n")
                    count += 1


def _transcribe_whisper(model, wav: Path, segs: list[tuple[float, float]],
                        block_epoch: int, tz: dt.tzinfo, source_file: str,
                        vocab_text: str) -> list[dict]:
    """Whisper path: one call per merged segment; rows in JSONL shape."""
    import numpy as np
    import wave as wave_mod
    with wave_mod.open(str(wav), "rb") as w:
        raw = w.readframes(w.getnframes())
    audio_arr = (np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0)
    rows = []
    for (s0, s1) in segs:
        if s1 - s0 < MIN_DURATION_S:
            continue
        try:
            seg_rows = _transcribe_wav(model, audio_arr, (s0, s1), vocab_text)
        except Exception as e:  # noqa: BLE001
            print(f"    [ko-stt] segment {s0:.1f}s failed: {e}", flush=True)
            continue
        for r in seg_rows:
            time_local = (dt.datetime.fromtimestamp(block_epoch, tz) +
                          dt.timedelta(seconds=r["start"])).strftime("%H:%M")
            rows.append({
                "time_local": time_local,
                "duration": round(r["end"] - r["start"], 2),
                "text": r["text"],
                "confidence": round(r["confidence"], 3),
                "source_file": source_file,
                "engine": f"faster-whisper:{MODEL_SIZE}",
            })
    return rows


def _transcribe_deepgram(wav: Path, segs: list[tuple[float, float]],
                         block_epoch: int, tz: dt.tzinfo,
                         source_file: str) -> list[dict]:
    """Deepgram path: slice VAD speech to wav bytes, one API call per
    merged segment; billing tracks real speech seconds only."""
    from . import deepgram
    import wave as wave_mod
    with wave_mod.open(str(wav), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    seg_audio = []
    for (s0, s1) in segs:
        if s1 - s0 < MIN_DURATION_S:
            continue
        chunk = raw[int(s0 * sr) * 2:int(s1 * sr) * 2]  # 16-bit mono
        if not chunk:
            continue
        import io
        buf = io.BytesIO()
        with wave_mod.open(buf, "wb") as wo:
            wo.setnchannels(1)
            wo.setsampwidth(2)
            wo.setframerate(sr)
            wo.writeframes(chunk)
        seg_audio.append((s0, s1, buf.getvalue()))
    return deepgram.transcribe_segments(seg_audio, block_epoch, tz, source_file)


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
    n = transcribe(audio, out, PACIFIC, load_vocab(Path("kern_overnight/vocab.txt")),
                   date=d)
    print(f"{n} transmissions → {out}")
