#!/usr/bin/env python3
"""LLM summarization for Bakersfield Daily Brief — with hard cost guardrails.

Design (per project constraints):
  * Key comes from the LLM_API_KEY env var (GitHub repo secret; absent locally).
  * Inexpensive model by default: gpt-4o-mini (override via LLM_MODEL).
  * Input capped at MAX_INPUT_CHARS; output capped via max_tokens.
  * Any failure (missing key, HTTP error, timeout, bad JSON) → return None.
    Callers must fall back to a plain headline list — the site builds either way.
  * OpenAI-compatible endpoint; LLM_BASE_URL can point at OpenRouter or any
    compatible gateway without code changes.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MAX_INPUT_CHARS = 6000          # ~1.5k tokens — keeps each call < $0.002
MAX_OUTPUT_TOKENS = 380
TIMEOUT = 45
# Upstream capacity/rate-limit errors: sleep RETRY_SLEEP seconds and retry,
# up to MAX_RETRIES extra attempts, then fall back gracefully.
RETRYABLE_STATUS = {429, 503}
RETRY_SLEEP = int(os.environ.get("LLM_RETRY_SLEEP", "70"))
MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
SYSTEM = (
    "You are the wire editor of Bakersfield Daily Brief, a factual local civic "
    "news digest for Bakersfield and Kern County, California. Write in neutral, "
    "plain, professional English. Never editorialize, never speculate, never "
    "give advice. Prefer short sentences. No markdown, no bullet lists, no "
    "headings — plain prose paragraphs only."
)


def _truncate(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def summarize_news(headlines: list[dict], max_items: int = 14) -> str | None:
    """headlines: [{"title", "source", "url", "published"}] → 3-5 neutral paragraphs."""
    if not headlines:
        return None
    items = headlines[:max_items]
    lines = "\n".join(
        f"- {h['title']} ({h.get('source', 'news')}) {h.get('url', '')}"
        for h in items
    )
    prompt = (
        "Below are today's headlines from local Bakersfield/Kern County news "
        "sources, with source names and URLs. Write a 'The News' digest of 3-5 "
        "short paragraphs that groups related items, states facts only, and "
        "mentions the source outlet by name for each item you include. Do not "
        "invent details not present in the headlines. End with a closing line "
        "naming the outlets covered today.\n\nHEADLINES:\n" + _truncate(lines)
    )
    return _chat(prompt)


def pick_thing_to_watch(candidates: list[dict]) -> str | None:
    """candidates: [{"meeting", "item", "date", "url"}] → 1-2 sentence pick."""
    if not candidates:
        return None
    lines = "\n".join(
        f"- {c['date']} {c['meeting']}: {c['item']} ({c['url']})"
        for c in candidates[:25]
    )
    prompt = (
        "From the upcoming public-meeting agenda items below, pick the single "
        "most notable one for Bakersfield/Kern County residents. Respond with "
        "two sentences: what the item is and when/where the public can "
        "participate. Facts only; do not add opinions.\n\nAGENDA ITEMS:\n"
        + _truncate(lines)
    )
    return _chat(prompt)


def friendly_brief(top_title: str, headlines: list[dict], weather: dict,
                   airnow: dict, calfire: dict, events: list[dict]) -> str | None:
    """→ 2-3 warm, plain paragraphs opening the daily article.

    Ties together the top story, conditions, and a couple of upbeat notes so
    the brief reads like a neighbor's morning summary, not a wire feed.
    Facts only — no invented details, no editorializing.
    """
    if not top_title and not headlines:
        return None
    ev = "; ".join(f"{e.get('name', 'an event')} at {e.get('venue', 'a local venue')}"
                   for e in events[:3])
    cond = []
    fc = (weather or {}).get("forecast", {}) or {}
    if fc.get("high") is not None:
        cond.append(f"a high near {fc['high']}")
    alerts = (weather or {}).get("alerts", [])
    if alerts:
        cond.append(f"{alerts[0].get('event', 'a weather alert')}")
    if airnow and airnow.get("ok") and airnow.get("aqi") is not None:
        cond.append(f"air quality around {airnow['aqi']}")
    cond_txt = (" " + "; ".join(cond) + ".") if cond else ""
    lines = "\n".join(
        f"- {h['title']} ({h.get('source', 'news')})" for h in headlines[:12]
    )
    prompt = (
        "Write the opening of a friendly local news brief for Bakersfield/Kern "
        "County, addressed to readers as 'you'. Two to three short paragraphs. "
        "Paragraph 1: greet readers warmly and name the day's top story "
        f"('{top_title}') in your own words. Paragraph 2: summarize conditions "
        f"('{cond_txt}') and 2-3 other notable headlines from the list. "
        "Paragraph 3: point readers to something pleasant coming up"
        + (f" ({ev})" if ev else "")
        + ". Tone: warm, plain, trustworthy. Facts only; never invent details "
        "not in the input; no markdown, no headings.\n\nHEADLINES:\n"
        + _truncate(lines)
    )
    return _chat(prompt)


def pick_positive(headlines: list[dict]) -> str | None:
    """Choose one genuinely positive local story → 2 sentences, warm tone."""
    if not headlines:
        return None
    lines = "\n".join(
        f"- {h['title']} ({h.get('source', 'news')})" for h in headlines[:14]
    )
    prompt = (
        "From the local headlines below, choose the ONE that is most positive "
        "or uplifting for the community — something like a grand opening, a "
        "scholarship, a volunteer drive, a festival, or a milestone. Respond "
        "with two warm, factual sentences about it. Do not invent details not "
        "in the headline; no markdown.\n\nHEADLINES:\n" + _truncate(lines)
    )
    return _chat(prompt)


def _chat(prompt: str) -> str | None:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        print("    [llm] no LLM_API_KEY set — skipping (graceful fallback)", flush=True)
        return None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "temperature": 0.3,
                },
                timeout=TIMEOUT,
            )
            if r.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                print(f"    [llm] HTTP {r.status_code} (upstream capacity) — "
                      f"sleeping {RETRY_SLEEP}s, retry {attempt + 1}/{MAX_RETRIES}", flush=True)
                time.sleep(RETRY_SLEEP)
                continue
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"].strip()
            return out if out else None
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                print(f"    [llm] HTTP {code} — sleeping {RETRY_SLEEP}s, "
                      f"retry {attempt + 1}/{MAX_RETRIES}", flush=True)
                time.sleep(RETRY_SLEEP)
                continue
            print(f"    [llm] HTTP {code or '?'} after {attempt + 1} attempt(s) — fallback", flush=True)
            return None
        except Exception as e:  # noqa: BLE001 - graceful skip on any failure
            print(f"    [llm] {type(e).__name__}: {e} — fallback", flush=True)
            return None
    print(f"    [llm] giving up after {MAX_RETRIES + 1} attempts — fallback", flush=True)
    return None


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
