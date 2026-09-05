#!/usr/bin/env python3
"""Regression tests for LLM resilience (build/llm.py).

On 2026-09-05 the daily email died because a ReadTimeout skipped straight to
fallback — the retry loop only covered HTTP 429/503, not transient network
errors. These tests lock in that timeouts/connection errors are now retried
(with backoff) and only give up gracefully after exhausting MAX_RETRIES.

Run:  .venv/Scripts/python.exe -m pytest tests/test_llm_resilience.py -q
Fully offline — requests.post is monkeypatched, never hits the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build.llm as llm  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Keep the test instant: no real sleeps, bounded attempts."""
    monkeypatch.setattr(llm, "RETRY_SLEEP", 0)
    monkeypatch.setattr(llm, "MAX_RETRIES", 3)
    monkeypatch.setenv("LLM_API_KEY", "test-key")


class _Resp:
    def __init__(self, code=200):
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


def _post_flaky(fail_attempts: int, exc: Exception, monkeypatch):
    """requests.post that raises exc the first `fail_attempts` calls, then 200."""
    state = {"n": 0}

    def _post(*a, **k):
        state["n"] += 1
        if state["n"] <= fail_attempts:
            raise exc
        return _Resp()

    monkeypatch.setattr(llm.requests, "post", _post)
    return state


def test_read_timeout_is_retried_and_succeeds(monkeypatch):
    """A ReadTimeout now retries instead of skipping to fallback."""
    state = _post_flaky(2, llm.requests.exceptions.ReadTimeout("sim"), monkeypatch)
    out = llm._chat("hi")
    assert out == "ok"
    assert state["n"] == 3  # 2 failures + 1 success


def test_connect_timeout_is_retried_and_succeeds(monkeypatch):
    state = _post_flaky(1, llm.requests.exceptions.ConnectTimeout("sim"), monkeypatch)
    out = llm._chat("hi")
    assert out == "ok"
    assert state["n"] == 2


def test_connection_error_retried_then_succeeds(monkeypatch):
    state = _post_flaky(3, llm.requests.exceptions.ConnectionError("reset"), monkeypatch)
    # 3 failures within MAX_RETRIES=3 -> the 4th call succeeds
    assert llm._chat("hi") == "ok"
    assert state["n"] == 4  # 1 + 3 retries


def test_connection_error_exhausted_falls_back(monkeypatch):
    state = _post_flaky(5, llm.requests.exceptions.ConnectionError("reset"), monkeypatch)
    # more failures than (1 + MAX_RETRIES) -> graceful None, never raises
    assert llm._chat("hi") is None
    assert state["n"] == 4  # 1 + MAX_RETRIES, then fallback


def test_persistent_timeout_falls_back_gracefully(monkeypatch):
    """All retries exhausted => returns None (callers degrade, never crash)."""
    _post_flaky(99, llm.requests.exceptions.ReadTimeout("boom"), monkeypatch)
    assert llm._chat("hi") is None


def test_http_5xx_is_retried(monkeypatch):
    """500s are upstream-capacity signals and stay retryable."""
    state = {"n": 0}

    def _post(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise llm.requests.exceptions.HTTPError("500", response=_Resp(500))
        return _Resp()

    monkeypatch.setattr(llm.requests, "post", _post)
    assert llm._chat("hi") == "ok"
    assert state["n"] == 2


def test_no_key_skips_cleanly(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert llm._chat("hi") is None


def test_long_generation_uses_long_timeout():
    """brief_full (max_tokens=3600) and the Sunday feature must pass the
    long-generation timeout budget, not the 45s short-call default."""
    from inspect import signature
    assert llm.LONG_TIMEOUT > llm.TIMEOUT
    assert llm.LONG_TIMEOUT >= 120
