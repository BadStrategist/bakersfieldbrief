"""The Kern Overnight — scanner-to-newsletter pipeline.

Stages: fetch (Broadcastify feed 14029) → transcribe (ffmpeg + Silero VAD +
faster-whisper) → extract (LLM → incidents JSON) → write (LLM → Markdown
brief) → deliver (briefs/DATE.md for human review).

Run:  python -m kern_overnight.run [YYYY-MM-DD]   (default: last night)
"""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from the repo .env (never committed)."""
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
