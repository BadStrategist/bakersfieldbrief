#!/usr/bin/env python3
"""TypeSafe Jev wiring for the social publish pipeline. ADVISORY ONLY.

Rules taken from the typesafe-jev-decision-api skill: Jev screens, ranks, flags and
routes; code decides. Shadow mode first. Never in a critical path with no fallback.
Every call is logged to work/social/jev-shadow.jsonl so its answers can be compared
against what actually happened before anything is allowed to act on them.

Hard guarantees in this module:
  * ask() never raises and never returns anything but a dict.
  * No return value here can authorise, block, or delay a publish. Callers only log.
  * If the key, the network, or the model is unavailable, callers behave exactly as
    they did before Jev existed.

State hygiene: no tokens, no secrets. Only public caption text and the booleans the
browser already measured.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MODEL = "jev-1.13.0"          # pinned: the jev-latest alias moves, thresholds move with it
URL = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_S = 8                  # advisory only, so a slow answer is simply abandoned
SHADOW_LOG = Path(__file__).resolve().parents[2] / "work" / "social" / "jev-shadow.jsonl"


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
def _key() -> str | None:
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                v = line.split("=", 1)[1].strip()
                return v or None
    except OSError:
        return None
    return None


def ask(questions: dict, state, tag: str = "", log_path: Path | None = None) -> dict:
    """One Jev call. Returns {'ok': bool, 'answers': {...}, 'ms': int} and never raises."""
    import urllib.request

    key = _key()
    if not key:
        return {"ok": False, "why": "TYPESAFE_API_KEY not set", "ms": 0, "answers": {}}
    try:
        body = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return {"ok": False, "why": f"state not serialisable: {exc}", "ms": 0, "answers": {}}

    req = urllib.request.Request(
        URL, data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            out = json.load(r)
        res = {"ok": True, "answers": out.get("answers") or {},
               "model": out.get("model"), "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001  (advisory: any failure is non-fatal)
        res = {"ok": False, "why": f"{type(exc).__name__}: {exc}"[:200],
               "ms": int((time.time() - t0) * 1000), "answers": {}}

    log = {"ts": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds"),
           "tag": tag, "state": state, "result": res}
    target = log_path or SHADOW_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return res


# --------------------------------------------------------------------------- #
# the two judgments we ask for
# --------------------------------------------------------------------------- #
READMEY = {
    "verdict": {
        "type": "choice",
        "instructions": (
            "You are screening one automated Facebook and Instagram reel publish "
            "immediately before it runs. The evidence is what the browser measured on "
            "the composer's final Share step. Decide whether the evidence shows a clean "
            "run that should proceed. Judge only what the evidence states; do not "
            "assume anything absent from it."
        ),
        "criteria": {
            "proceed": (
                "a clean Share step: the video is attached, the caption text is present, "
                "auto captions are reported OFF, both the Facebook page and the Instagram "
                "account are targeted, and no copyright warning is reported"
            ),
            "hold": (
                "unsafe to publish: any required flag is reported false, auto captions are "
                "reported ON, a copyright warning is present, or only one of the two "
                "targets is present"
            ),
            "investigate": (
                "the evidence is incomplete or contradicts itself, so a human should look "
                "before anything is published"
            ),
        },
    }
}

TRIAGE = {
    "category": {
        "type": "choice",
        "instructions": (
            "Categorise why one automated social publish run did not complete. Use only "
            "the evidence given. Pick the single best category."
        ),
        "criteria": {
            "gate_blocked": "the publish gate refused the day's report before any browser work",
            "composer_hung": "the browser composer stalled, or the CDP session wedged mid-flow",
            "captions_on": "auto captions could not be turned off, so the run refused to publish",
            "wrong_target": "the composer was not on the intended page or account",
            "verification_failed": "a publish was attempted but the content lists do not show it",
            "other": "none of the above fits the evidence",
        },
    }
}


def screen_publish_evidence(evidence: dict, tag: str = "pre_publish_screen") -> dict:
    """Shadow screen of the Share step. Advisory: the caller logs it and still decides."""
    return ask(READMEY, evidence, tag=tag)


def triage_failure(evidence: dict, tag: str = "failure_triage") -> dict:
    """Classify a failed run for the report and the retry policy. Advisory."""
    return ask(TRIAGE, evidence, tag=tag)


def _selftest() -> int:
    ev = {
        "step_reached": "share",
        "video_attached": True,
        "caption_chars": 328,
        "auto_captions_on": True,
        "targets": ["Facebook page", "Instagram"],
        "copyright_warning": True,
    }
    r = screen_publish_evidence(ev, tag="selftest_screen")
    print("screen  ->", json.dumps(r, indent=2)[:600])
    t = triage_failure({"exit_code": 1, "last_reason": "auto captions still ON - refusing to publish",
                        "captions_attempted_off": True, "composer_reached_share": True},
                       tag="selftest_triage")
    print("triage  ->", json.dumps(t, indent=2)[:600])
    return 0 if (r.get("ok") or t.get("ok")) else 1


if __name__ == "__main__":
    import sys

    sys.exit(_selftest())