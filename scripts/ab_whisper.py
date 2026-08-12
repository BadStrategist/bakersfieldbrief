#!/usr/bin/env python3
"""Whisper model A/B benchmark for Kern Overnight scanner audio.

Transcribes the SAME audio blocks with two faster-whisper models using the
EXACT production settings (_preprocess → _vad_speech_segments →
_merge_segments → _transcribe_whisper, beam 1, en, vocab prompt), then
scores both outputs with the Bakersfield street gazetteer (streetcheck).

The streetcheck MATCH rate is the objective accuracy metric: scanner
audio is full of street names, and that is exactly what distillation
degrades. Speed (seconds per block) is the cost side.

Usage:
  python scripts/ab_whisper.py [date] [n_blocks] [model1] [model2]
"""
from __future__ import annotations

import gc
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kern_overnight import transcribe as T  # noqa: E402
from kern_overnight import streetcheck as SC  # noqa: E402
from kern_overnight.fetch import PACIFIC  # noqa: E402

MODELS = ["distil-large-v3", "large-v3-turbo"]


def run_model(model: str, mp3s: list[Path], vocab: str, out_jsonl: Path) -> dict:
    T.MODEL_SIZE = model
    model_obj = T._load_model()
    rows_total, times = 0, []
    with tempfile.TemporaryDirectory(prefix="ko-ab-") as td:
        work = Path(td)
        with open(out_jsonl, "w", encoding="utf-8") as out:
            for mp3 in mp3s:
                t0 = time.time()
                wav = T._preprocess(mp3, work)
                segs = T._merge_segments(T._vad_speech_segments(wav, work))
                block_epoch = int(mp3.stem.split("-")[1])
                rows = T._transcribe_whisper(model_obj, wav, segs, block_epoch,
                                             PACIFIC, mp3.name, vocab)
                n = 0
                for r in rows:
                    if r["confidence"] < T.MIN_CONFIDENCE and r["duration"] < 3.0:
                        continue
                    out.write(json.dumps(r, ensure_ascii=False) + "\n")
                    n += 1
                times.append(time.time() - t0)
                rows_total += n
                print(f"    [{model}] {mp3.name}: {n} rows in "
                      f"{times[-1]/60:.1f} min", flush=True)
    del model_obj
    gc.collect()
    return {"rows": rows_total,
            "sec_per_block": sum(times) / len(times) if times else 0}


def score(out_jsonl: Path) -> dict:
    if not out_jsonl.exists():
        return {"candidates": 0, "match": 0, "fuzzy": 0, "unknown": 0}
    streets = SC.load_streets()
    raw = out_jsonl.read_text(encoding="utf-8")
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    text = "\n".join(f"{r.get('time_local', '')} | {r.get('text', '')}" for r in rows)
    res = SC.scan(text, streets)
    counts = {"match": 0, "fuzzy": 0, "unknown": 0}
    for s, _, _ in res:
        counts[s.lower()] += 1
    counts["candidates"] = len(res)
    return counts


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-08-10"
    n_blocks = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    models = sys.argv[3:5] or MODELS

    audio_dir = ROOT / "audio" / date
    mp3s = sorted(audio_dir.glob("*.mp3"))[:n_blocks]
    if not mp3s:
        print(f"no blocks in {audio_dir}")
        return 1
    print(f"benchmark: {date}, {len(mp3s)} blocks, models={models}")
    print("blocks:", [p.name for p in mp3s])

    vocab = T.load_vocab(ROOT / "kern_overnight" / "vocab.txt")
    outdir = Path(tempfile.gettempdir()) / "ko-ab"
    outdir.mkdir(parents=True, exist_ok=True)

    results = {}
    for model in models:
        out = outdir / f"{date}-{model.replace('/', '_')}.jsonl"
        if out.exists():
            out.unlink()
        print(f"\n=== {model} ===", flush=True)
        t0 = time.time()
        results[model] = run_model(model, mp3s, vocab, out)
        results[model]["wall_min"] = (time.time() - t0) / 60
        results[model]["street"] = score(out)

    print("\n" + "=" * 64)
    if len(models) == 1:
        m = models[0]
        r = results[m]
        s = r["street"]
        rate = (s["match"] / s["candidates"]) if s["candidates"] else 0
        print(f"{'model':<28}{m[:40]:>40}")
        print(f"{'sec/block':<28}{r['sec_per_block']:>40.1f}")
        print(f"{'rows kept':<28}{r['rows']:>40}")
        print(f"{'street MATCH rate':<28}{rate:>40.1%}")
        print("=" * 64)
        return 0
    print(f"{'metric':<28}{models[0]:>16}{models[1]:>16}")
    print("=" * 64)
    for key, label in [("sec_per_block", "sec/block"),
                       ("rows", "rows kept"),
                       ("wall_min", "wall time (min)")]:
        print(f"{label:<28}"
              f"{results[models[0]][key]:>16.1f}{results[models[1]][key]:>16.1f}")
    print("-" * 64)
    for key, label in [("candidates", "street candidates"),
                       ("match", "  exact matches"),
                       ("fuzzy", "  fuzzy (mis-hears)"),
                       ("unknown", "  unknown")]:
        a, b = results[models[0]]["street"][key], results[models[1]]["street"][key]
        print(f"{label:<28}{a:>16}{b:>16}")
    m0 = results[models[0]]["street"]
    m1 = results[models[1]]["street"]
    r0 = (m0["match"] / m0["candidates"]) if m0["candidates"] else 0
    r1 = (m1["match"] / m1["candidates"]) if m1["candidates"] else 0
    print(f"{'street MATCH rate':<28}{r0:>16.1%}{r1:>16.1%}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
