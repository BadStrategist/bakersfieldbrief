#!/usr/bin/env python3
"""LLM calls for The Kern Overnight — larger context than the site's llm.py.

The overnight pipeline is a premium tool with its own key expectations:
- LLM_API_KEY  (required for extraction/writing; fail loudly if missing)
- LLM_MODEL    (default gpt-4o-mini; raise to a stronger model for writing)
- LLM_BASE_URL (OpenAI-compatible endpoint; OpenRouter etc. work)
Supports structured JSON output (extraction) and long markdown (writing)."""
from __future__ import annotations

import json
import os
import re
import sys
import time

import requests

MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
TIMEOUT = 120
MAX_RETRIES = 3
RETRYABLE = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Raised when the LLM stage cannot complete — orchestrator fails loudly."""


def _require_key() -> str:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise LLMError(
            "LLM_API_KEY is not set. The Kern Overnight extraction/writing "
            "stages require an LLM key (add it to .env or the environment). "
            "Refusing to guess — no silent empty brief.")
    return key


def _chat(prompt: str, system: str, max_tokens: int = 2000,
          temperature: float = 0.3, json_mode: bool = False) -> str:
    key = _require_key()
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload, timeout=TIMEOUT)
            if r.status_code in RETRYABLE and attempt < MAX_RETRIES:
                print(f"    [ko-llm] HTTP {r.status_code} — retry {attempt + 1}/{MAX_RETRIES}",
                      flush=True)
                time.sleep(min(30 * (attempt + 1), 90))
                continue
            r.raise_for_status()
            choice = (r.json().get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            out = (msg.get("content") or "").strip()
            if not out:
                # A null content is deterministic for this payload (the model
                # spent its budget on reasoning, or answered in another field),
                # so fail fast instead of sleeping through four retries.
                raise LLMError(
                    "empty completion from model "
                    f"(content={msg.get('content')!r}, "
                    f"finish_reason={choice.get('finish_reason')!r})")
            return out
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(min(20 * (attempt + 1), 60))
    raise LLMError(f"LLM request failed after {MAX_RETRIES + 1} attempts: {last_err}")


def chat_text(prompt: str, system: str, max_tokens: int = 2000) -> str:
    return _chat(prompt, system, max_tokens=max_tokens, temperature=0.4)


def chat_json(prompt: str, system: str, max_tokens: int = 2500) -> dict:
    """Request a JSON object; parse defensively, fail loudly on garbage."""
    raw = _chat(prompt, system, max_tokens=max_tokens, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise LLMError(f"model returned non-JSON: {raw[:200]!r}")
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise LLMError(f"model returned {type(data).__name__}, expected object")
    return data
