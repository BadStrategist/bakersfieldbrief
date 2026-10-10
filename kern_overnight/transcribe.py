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
import time
import contextlib
from pathlib import Path

from .fetch import _epoch_from_name  # noqa: E402 (block naming helper)
from .streetcheck import fix_text as _fix_text  # noqa: E402 (mis-hearing fold)

ENGINE = os.environ.get("KO_STT_ENGINE", "faster-whisper")
MODEL_SIZE = os.environ.get("KO_WHISPER_MODEL",
                            "Systran/faster-whisper-large-v3")
# 2026-09-30 GPU A/B (6 blocks, 3 nights): full large-v3 at beam 5 cut junk
# lines ~90% vs turbo (4 vs 47; turbo melts static into CJK/Cyrillic noise),
# street MATCH counts tied (16 vs 17), 1.2 vs 0.68 min/block. Turbo was only
# the right call while this ran on CPU. Beam 1 was likewise a CPU-speed choice.
BEAM_SIZE = int(os.environ.get("KO_BEAM", "5"))
# large-v3-turbo (ungated mobiuslabs mirror) beat distil-large-v3 in the
# Aug-2026 A/B on this workload: 48.6% vs 35.7% street MATCH rate
# (streetcheck gazetteer) at 9.9 vs 11.3 min/block. Systran's repo is
# HF-gated, so we pin the mirror.
MIN_CONFIDENCE = float(os.environ.get("KO_MIN_CONF", "0.45"))
MIN_DURATION_S = float(os.environ.get("KO_MIN_SEG_S", "1.0"))
# Parallel transcription workers. 3 made this 16GB rig swap/stall for 20-30 min
# under memory pressure (observed 2026-09-02/03/05): 3 x ~1.4GB models needs
# ~4.2GB free, but Chrome/RuneLite/Discord leave only ~5GB. 2 workers (~2.8GB)
# fits comfortably -> steady, no thrash. Fewer parallel model loads barely cost
# wall-clock on 32 cores (RAM, not CPU, is the bottleneck) and eliminates the
# stalls that actually ran transcription long. Env KO_WORKERS still overrides.
WORKERS = int(os.environ.get("KO_WORKERS", "2"))  # parallel blocks per night


def _cuda_ready() -> bool:
    """True if the NVIDIA GPU + CUDA 12 cuBLAS/cuDNN 9 DLLs are usable.

    The DLLs come from the nvidia-cublas-cu12 / nvidia-cudnn-cu12 pip wheels
    (site-packages/nvidia/*/bin); CTranslate2 won't find them on its own, so
    register them here. Runs at import, i.e. once in every worker process."""
    if os.name != "nt":
        return False  # CI/Linux: no GPU path, keep CPU behaviour
    import ctypes
    import glob
    import site
    try:
        for sp in site.getsitepackages():
            for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            return False
        ctypes.WinDLL("cublas64_12.dll")
        ctypes.WinDLL("cudnn64_9.dll")
        return True
    except Exception:  # noqa: BLE001 — any failure → CPU
        return False


# Whisper device. Until 2026-09-30 this was hard-coded CPU (int8, 8 threads x
# 2 workers = half of all 32 threads + ~3GB RAM for 30-90 min). The RTX 4060
# runs turbo at float16 in ~1.6GB VRAM, far faster, with no CPU/RAM pressure.
# KO_DEVICE=cpu forces the old path; "auto" falls back to CPU if CUDA is absent.
# Measured 2026-09-30 on real blocks: CPU ~9.9 min/block, GPU 1 worker 1.7,
# GPU 2 workers 1.25 with turbo. With large-v3 beam 5, 2 workers hit 7.9 of
# 8.2 GB VRAM and spilled to shared memory: 8.8 min/block vs ~1.2 for one
# worker. So the GPU path runs 1 worker unless KO_WORKERS says otherwise.
_DEV_PREF = os.environ.get("KO_DEVICE", "auto").lower()
DEVICE = "cuda" if _DEV_PREF in ("auto", "cuda") and _cuda_ready() else "cpu"
if DEVICE == "cuda" and "KO_WORKERS" not in os.environ:
    WORKERS = 1

# --- per-process globals for the parallel workers (set by _init_worker)
_W_ENGINE = ENGINE
_W_VOCAB = ""
_W_TZ: dt.tzinfo = dt.timezone(dt.timedelta(hours=-7))
_W_MODEL = None


def _init_worker(engine: str, vocab: str, tz: dt.tzinfo) -> None:
    """One call per worker process at spawn: seed globals, cache nothing yet."""
    global _W_ENGINE, _W_VOCAB, _W_TZ, _W_MODEL
    _W_ENGINE, _W_VOCAB, _W_TZ, _W_MODEL = engine, vocab, tz, None


def _block_worker(mp3: Path) -> tuple[list[dict], int]:
    """Process one block in a worker process → (rows, failed segments).

    The whisper model loads lazily on the first block so each worker holds
    exactly one copy for the whole night. A block never raises out of the pool,
    but its failures are COUNTED and returned so the caller can fail loudly.
    It used to return [] with no signal, so a night that transcribed nothing
    exited 0 and the pipeline called it a success."""
    global _W_MODEL
    try:
        with tempfile.TemporaryDirectory(prefix="ko-w") as td:
            work = Path(td)
            wav = _preprocess(mp3, work)
            segs = _merge_segments(_vad_speech_segments(wav, work))
            if not segs:
                return [], 0
            block_epoch = int(mp3.stem.split("-")[1])
            if _W_ENGINE == "deepgram":
                return _transcribe_deepgram(wav, segs, block_epoch, _W_TZ,
                                            mp3.name), 0
            if _W_MODEL is None:
                _W_MODEL = _load_model()
            return _transcribe_whisper(_W_MODEL, wav, segs, block_epoch,
                                       _W_TZ, mp3.name, _W_VOCAB)
    except Exception as e:  # noqa: BLE001
        print(f"    [ko-stt] block {mp3.name} FAILED: {type(e).__name__}: {e}",
              flush=True)
        return [], 1  # a whole block lost is a failure the caller must see


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
    print(f"    [ko-stt] loading {MODEL_SIZE} on {DEVICE}...", flush=True)
    # Offline by default (cached models only — a HF network check once hung
    # the job for 10+ min). Set HF_HUB_OFFLINE=0 to allow a first-run
    # download of the model.
    local_only = os.environ.get("HF_HUB_OFFLINE", "1") != "0"
    try:
        if DEVICE == "cuda":
            return WhisperModel(MODEL_SIZE, device="cuda", compute_type="float16",
                                local_files_only=local_only)
        return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8",
                            cpu_threads=8, local_files_only=local_only)
    except Exception as e:  # noqa: BLE001 — cache miss → allow download
        raise TranscribeError(
            "faster-whisper model not in cache. Run once with "
            "HF_HUB_OFFLINE=0 (or `huggingface-cli download "
            f"{MODEL_SIZE}`) to fetch it. ({e})") from e


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
        beam_size=BEAM_SIZE,
        vad_filter=False,          # we already VAD'd; keep whisper's own off
        initial_prompt=vocab,      # vocabulary priming (editable vocab.txt)
        condition_on_previous_text=False,
    )
    rows = []
    for s in segs:
        # Fold known mis-hearings (e.g. 'Weibel Avenue' -> 'Wible Road') as the
        # row is written, so every downstream consumer (extract, digest, the
        # LLM, the report) sees the gazetteer spelling, not just the incidents.
        text = _fix_text(s.text.strip())
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
    """True if `epoch` is a block of the 19:00→07:00 night that owns `date`.

    Overlap, not containment: the first evening block starts after 19:00
    (19:16, 18:58), and containment dropped it, so 19:00-21:00 was never
    fetched or transcribed. The rule lives in fetch.in_window so the window
    has exactly one definition.
    """
    from kern_overnight import fetch
    return fetch.in_window(epoch, *fetch.window_bounds(date, tz))


def _ko_checkpoint(out_jsonl: Path, blocks_done: int, total: int, push: bool = False) -> None:
    """Commit the transcript JSONL to git so partial-night data reaches the
    cloud even if this PC dies mid-pipeline (Tier-2 resilience).

    Commits ONLY the transcript file (never `git add -A`, so sibling-session
    artifacts are never swept in). A plain `git push` is attempted once at
    the end; failures are tolerated silently — the morning agent's
    stash/rebase push resolves any divergence. Skipped when the output file
    is not inside the repo (e.g. pytest temp dirs).
    """
    try:
        root = Path(__file__).resolve().parent.parent
        try:
            rel = out_jsonl.resolve().relative_to((root / "transcripts").resolve())
        except ValueError:
            return  # not a repo transcript (tests / temp dirs)
        import subprocess
        subprocess.run(["git", "add", "--", str(out_jsonl.resolve())],
                       cwd=root, check=True, capture_output=True, timeout=30)
        # `-- <path>` is a pathspec: without it a bare `git commit` takes the whole
        # index, so anything a sibling session had staged rides along in a commit
        # labelled "transcript checkpoint" (proved: c1d2d725 carried roads.json).
        subprocess.run(
            ["git", "commit", "-q",
             "-m", f"ko: transcript checkpoint ({blocks_done}/{total} blocks) "
                   "[skip ci]",
             "--", str(out_jsonl.resolve())],
            cwd=root, capture_output=True, timeout=30)  # rc 1 = nothing staged, fine
        # [skip ci] keeps transcript-only pushes from triggering a site deploy:
        # the workflow runs only on content-bearing pushes (report/code/data),
        # which saves the private-repo Actions-minute budget while keeping the
        # per-block cloud pushes fully intact (Tier-2 crash safety unchanged).
        if push:
            r = subprocess.run(["git", "push", "-q", "origin", "main"],
                               cwd=root, capture_output=True, timeout=120)
            if r.returncode != 0:
                print("    [ko-stt] checkpoint push deferred (will be pushed "
                      "by the morning agent)", flush=True)
    except Exception as e:  # noqa: BLE001 — never break transcription for git
        print(f"    [ko-stt] checkpoint skipped: {type(e).__name__}", flush=True)


@contextlib.contextmanager
def _transcript_lock(path: Path, wait: float = 900.0):
    """Advisory exclusive lock on <path>.lock, auto-released by the OS when the
    holding process dies (no stale-lock cleanup needed). A second transcriber
    WAITS up to `wait` (phase1/phase2/publish are legitimately sequential and
    must not block each other), then raises if still held by a hung-but-alive
    process. No-op where no advisory-lock API exists (tests / temp dirs).
    Prevents two concurrent transcribers truncating the shared
    transcripts/<date>.jsonl to 0 bytes (the 2026-09-07 corruption)."""
    lock_file = path.with_name(path.name + ".lock")
    fd = None
    msvcrt = fcntl = None
    try:
        import msvcrt  # type: ignore  # Windows advisory file lock
    except ImportError:
        pass
    try:
        import fcntl  # type: ignore  # POSIX advisory file lock
    except ImportError:
        pass
    if msvcrt is None and fcntl is None:
        yield  # no advisory-lock API available — best effort
        return
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        os.write(fd, b"\x00")  # ensure >=1 byte so the lock region is valid
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        pass
    deadline = time.monotonic() + wait
    while True:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"transcript {path.name} still locked after {wait:.0f}s "
                    f"(another transcriber hung?)")
            time.sleep(5)
    try:
        yield
    finally:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


def transcribe(audio_dir: Path, out_jsonl: Path, tz: dt.tzinfo,
               vocab_text: str, date: dt.date | None = None,
               workers: int | None = None, append: bool = False) -> int:
    """Transcribe the overnight-window MP3s in audio_dir → out_jsonl.

    When `date` is given, only blocks whose epoch falls in that night's
    21:00→06:00 window are processed — the audio dir may hold extra
    out-of-window archives (the fetch listings return the whole calendar
    days). `workers` > 1 processes blocks in parallel (one model per
    worker process). `append` keeps existing rows and skips blocks already
    transcribed — the two-phase overnight schedule uses it: phase 1 writes
    the early blocks at ~03:00, phase 2 appends the tail at ~06:30.
    Returns row count."""
    mp3s = sorted(audio_dir.glob("*.mp3"))
    if date is not None:
        mp3s = [p for p in mp3s
                if _in_overnight_window(_epoch_from_name(p.name) or 0, date, tz)]
    if not mp3s:
        raise TranscribeError(
            f"no overnight-window audio blocks in {audio_dir} — run fetch first")
    done: set[str] = set()
    if append and out_jsonl.exists():
        done = {json.loads(ln).get("source_file", "")
                for ln in out_jsonl.read_text(encoding="utf-8").splitlines()
                if ln.strip()}
    mp3s = [p for p in mp3s if p.name not in done]
    if not mp3s:
        print(f"    [ko-stt] all {len(done)} window blocks already transcribed "
              f"({out_jsonl.name}) — nothing to do", flush=True)
        return 0
    print(f"    [ko-stt] {len(mp3s)} blocks in window (of "
          f"{len(list(audio_dir.glob('*.mp3')))} on disk) "
          f"{'· append mode' if append else ''}", flush=True)
    count = 0
    failures = 0
    n_workers = (workers or WORKERS)
    parallel = n_workers > 1 and len(mp3s) > 1
    mode = "a" if append else "w"
    with _transcript_lock(out_jsonl), tempfile.TemporaryDirectory(prefix="ko-") as td:
        if parallel:
            from concurrent.futures import ProcessPoolExecutor
            print(f"    [ko-stt] {n_workers} parallel workers "
                  f"({len(mp3s)} blocks)", flush=True)
            with open(out_jsonl, mode, encoding="utf-8") as out:
                with ProcessPoolExecutor(max_workers=n_workers,
                                         initializer=_init_worker,
                                         initargs=(ENGINE, vocab_text, tz)) as ex:
                    commit_every = max(1, int(os.environ.get("KO_COMMIT_EVERY", "3")))
                    blocks_done = 0
                    for rows, n_failed in ex.map(_block_worker, mp3s):
                        blocks_done += 1
                        failures += n_failed
                        for r in rows:
                            if r["confidence"] < MIN_CONFIDENCE and r["duration"] < 3.0:
                                continue  # low-confidence + short → drop
                            out.write(json.dumps(r, ensure_ascii=False) + "\n")
                            count += 1
                        out.flush()
                        if blocks_done % commit_every == 0:
                            _ko_checkpoint(out_jsonl, blocks_done, len(mp3s))
            _ko_checkpoint(out_jsonl, len(mp3s), len(mp3s), push=True)
            _raise_if_incomplete(failures, out_jsonl)
            return count
        # serial fallback (workers == 1 or a single block)
        work = Path(td)
        with open(out_jsonl, mode, encoding="utf-8") as out:
            commit_every = max(1, int(os.environ.get("KO_COMMIT_EVERY", "3")))
            blocks_done = 0
            for mp3 in mp3s:
                wav = _preprocess(mp3, work)
                segs = _merge_segments(_vad_speech_segments(wav, work))
                if not segs:
                    continue
                block_epoch = int(mp3.stem.split("-")[1])
                if ENGINE == "deepgram":
                    rows = _transcribe_deepgram(wav, segs, block_epoch, tz, mp3.name)
                    block_failed = 0
                else:
                    global _W_MODEL
                    if _W_MODEL is None:  # load once, not once per block
                        _W_MODEL = _load_model()
                    rows, block_failed = _transcribe_whisper(
                        _W_MODEL, wav, segs, block_epoch, tz, mp3.name, vocab_text)
                failures += block_failed
                blocks_done += 1
                for r in rows:
                    if r["confidence"] < MIN_CONFIDENCE and r["duration"] < 3.0:
                        continue  # low-confidence + short → drop
                    out.write(json.dumps(r, ensure_ascii=False) + "\n")
                    count += 1
                out.flush()
                if blocks_done % commit_every == 0:
                    _ko_checkpoint(out_jsonl, blocks_done, len(mp3s))
        _ko_checkpoint(out_jsonl, len(mp3s), len(mp3s), push=True)
    _raise_if_incomplete(failures, out_jsonl)
    return count


def _raise_if_incomplete(failed: int, out_jsonl: Path) -> None:
    """Loud exit for a partial transcript.

    A segment that raises is dropped, and a block that raises is dropped, so a
    night can lose audio silently: the JSONL still looks fine and the run exits
    0. The rows already written are kept and checkpointed; this only stops the
    pipeline from CALLING a partial night a success. The 7:30 publish is a
    separate job, so a re-run signal here never withholds a report.
    """
    if failed:
        raise TranscribeError(
            f"{failed} segment(s)/block(s) failed to transcribe: {out_jsonl.name} "
            "is incomplete. Re-run this phase.")


def _transcribe_whisper(model, wav: Path, segs: list[tuple[float, float]],
                        block_epoch: int, tz: dt.tzinfo, source_file: str,
                        vocab_text: str) -> list[dict]:
    """Whisper path: one call per merged segment → (rows, failed segments)."""
    import numpy as np
    import wave as wave_mod
    with wave_mod.open(str(wav), "rb") as w:
        raw = w.readframes(w.getnframes())
    audio_arr = (np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0)
    rows = []
    failed = 0
    for (s0, s1) in segs:
        if s1 - s0 < MIN_DURATION_S:
            continue
        try:
            seg_rows = _transcribe_wav(model, audio_arr, (s0, s1), vocab_text)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"    [ko-stt] segment {s0:.1f}s FAILED: {type(e).__name__}: {e}",
                  flush=True)
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
    return rows, failed


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
