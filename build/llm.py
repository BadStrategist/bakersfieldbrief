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


SUNDAY_SYSTEM = (
    "You are the Sunday feature writer for Bakersfield Daily Brief, a factual "
    "local news publication for Bakersfield and Kern County, California. You "
    "write one long-form feature each week: a warm, readable, newsletter-"
    "length look at ONE Kern County topic, drawn ONLY from the facts provided. "
    "Plain prose paragraphs with occasional section headings (## for headings, "
    "plain text for body). Never invent names, numbers, dates, or quotes not "
    "in the source material. Attribute facts to their sources where relevant. "
    "No marketing language, no filler, no 'in today's fast-paced world' — "
    "write like a sharp local journalist who knows the valley."
)


def write_sunday_read(topic: str, facts: str, max_words: int = 1100) -> str | None:
    """Long-form weekly feature (900–1200 words) from real week data.

    topic: the chosen theme (e.g. 'wildfire season', 'Lake Isabella levels').
    facts: a plain-text dump of the week's verifiable data (headlines with
    outlets, CHP incidents, reservoir numbers, alerts, meetings). The model
    writes one sourced, human feature using ONLY these facts.
    """
    if not topic or not facts:
        return None
    prompt = (
        f"Write this week's Sunday feature for Bakersfield Daily Brief. "
        f"Theme: {topic}. Target length: {max_words} words. Use ONLY the "
        "facts below — every number, name, and date must come from this list. "
        "Structure: an engaging lede, 3-5 developed sections, and a short "
        "close. If the facts are thin in one area, focus deeper on the areas "
        "where they are rich rather than padding.\n\n"
        f"WEEK'S FACTS:\n{_truncate(facts, limit=MAX_INPUT_CHARS)}"
    )
    return _chat(prompt, max_tokens=1600, system=SUNDAY_SYSTEM)


def _chat(prompt: str, max_tokens: int | None = None,
          system: str | None = None) -> str | None:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        print("    [llm] no LLM_API_KEY set — skipping (graceful fallback)", flush=True)
        return None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; "
                                       "x64) AppleWebKit/537.36"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system or SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens or MAX_OUTPUT_TOKENS,
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
            msg = r.json()["choices"][0]["message"]
            out = (msg.get("content") or "").strip()
            if not out:  # reasoning models can return content in 'reasoning'
                out = (msg.get("reasoning") or "").strip()
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


# ---------------------------------------------------------------- brief full
BRIEF_SYSTEM = (
    "You are the morning writer for the Bakersfield Brief, a factual "
    "local-news digest for Bakersfield and Kern County, California. You "
    "write the daily brief in the site's established voice: warm, "
    "plain-spoken, professional — a sharp local journalist who knows the "
    "valley, never sensational, never folksy, never corporate.\n\n"
    "Your job each morning: write ONE complete, flowing brief of "
    "700–1,000 words that a reader can finish over coffee and feel "
    "genuinely caught up on Kern County. Write in full, developed "
    "sentences — never telegraphic, never thin. Per-section budgets to "
    "hit the total: greeting 50–70 words; Kern Overnight 160–200 words "
    "(a narrative with specifics — times, roads, what units did); weather "
    "70–90 words; each top story 60–90 words (a real paragraph: context, "
    "what happened, why it matters); good note 50–70 words; coming-up "
    "120–160 words (meetings with dates and times, events with venues). "
    "The brief must cover, in order:\n"
    "1. A 2–3 sentence morning greeting that names the day's top story and "
    "the headline conditions (temperature, air quality, any active alerts "
    "or fires).\n"
    "2. The Kern Overnight summary — a compact narrative of the night's "
    "notable incidents, generalized to neighborhoods or block/cross "
    "streets. No exact addresses. Never publish names, license plates, or "
    "callback numbers.\n"
    "3. The weather picture — today's high and low, the current "
    "observation, any alerts, air quality, active fires.\n"
    "4. What the top local stories actually say — a developed paragraph "
    "per story, in your own words, covering the substance: who, what, and "
    "why it matters to Kern County. NOT the headline restated. "
    "MANDATORY: every story paragraph must name its outlet in the first "
    "sentence — 'KGET 17 reports that…', 'According to 23ABC, …' — so "
    "readers always see the source. Cover stories from multiple outlets, "
    "never a single source only. Vary the attribution phrasing — reports, "
    "said, according to, told us, announced — so no two stories read "
    "alike; never attribute the same outlet twice in a row. Wrap the "
    "opening sentence of each story paragraph in **bold** so skimmers can "
    "find the top stories at a glance.\n"
    "5. One or two upbeat community notes worth a smile.\n"
    "6. What's coming up this week — the public meetings and events worth "
    "knowing, in prose.\n\n"
    "Rules:\n"
    "- Facts only from the source material provided. Never invent names, "
    "numbers, dates, quotes, or details. If an article's full text is "
    "missing, summarize from its headline alone and say no more.\n"
    "- Summarize in your own unbiased words — paraphrase, never copy "
    "sentences from articles.\n"
    "- Attribution: when a fact comes from a specific outlet or agency "
    "(KGET, 23ABC, the Sheriff's Office, NWS), name it naturally in the "
    "sentence.\n"
    "- Tone: plain and warm, zero hype, zero editorializing, zero filler "
    "(\"in today's fast-paced world\" is banned). Write like you're telling "
    "a neighbor what happened while they slept.\n"
    "- Output format (CRITICAL for standardization): open with the "
    "greeting — NO heading. Then use EXACTLY these five section headings, "
    "in this exact order, each on its own line starting with ##:\n"
    "## The Kern Overnight\n## Today's weather\n## Top stories\n"
    "## Something good\n## Coming up this week\n"
    "Write 2-5 paragraphs under each heading. No other headings, no "
    "bullet lists, no \\\"here's what you need to know\\\" boilerplate. The "
    "ONLY allowed emphasis is **bold**, used solely for each top-story "
    "paragraph's opening sentence.\\n\\n"
    "Quality bar: if a reader skims only your first paragraph and your "
    "last, they should still know the shape of the day. If they read it "
    "all, they should feel caught up — the news, the night, the weather, "
    "and the week ahead."
)


def fetch_article_texts(items: list[dict], n: int = 6,
                        max_chars: int = 1600) -> list[dict]:
    """Deterministic article fetch: trafilatura clean text for the first n
    story URLs. Returns the items with 'text' added (or empty string on
    any failure). Blocking but bounded (TIMEOUT per fetch)."""
    try:
        import trafilatura
    except Exception:  # noqa: BLE001
        return [dict(i, text="") for i in items]
    from . import common
    out = []
    for it in items[:n]:
        url = (it or {}).get("url", "")
        text = ""
        if url:
            try:
                html = common.fetch(url, timeout=TIMEOUT).text
                txt = trafilatura.extract(
                    html, include_comments=False, include_tables=False,
                    favor_recall=False) or ""
                text = normalize_whitespace(txt)[:max_chars]
            except Exception:  # noqa: BLE001 - a failed article never blocks
                text = ""
        out.append(dict(it, text=text))
    return out


def brief_full(overnight_md: str, weather_prose: str, airnow: dict,
               calfire: dict, story_items: list[dict], events: list[dict],
               meetings_prose: str, good_prose: str,
               today_label: str, max_words: int = 1400) -> str | None:
    """The complete 1,000-1,500 word brief body in one LLM pass.

    story_items: headline dicts with 'text' (full article text via
    fetch_article_texts). Returns None (graceful) without a key."""
    if not story_items and not overnight_md:
        return None
    head = "\n".join(
        f"- {it.get('title', '?')} ({it.get('source', 'news')})"
        + (f"\n  TEXT: {it['text']}" if it.get("text") else "")
        for it in story_items if it.get("title"))
    ev = "; ".join(
        f"{e.get('name', 'an event')} at {e.get('venue', 'a local venue')}"
        f" on {e.get('when', 'a date')}"
        for e in (events or [])[:6])
    prompt = (
        f"Write today's Bakersfield Brief ({today_label}). Target length: "
        "at least 1,200 words, up to 1,500. Start with a 2-3 sentence warm " 
        "morning greeting that "
        "names the day's top story and the headline conditions. Then cover "
        "in flowing prose: (1) The Kern Overnight summary, (2) today's "
        "weather and conditions, (3) what the top local stories actually "
        "say — 2-3 sentences each, paraphrased, (4) one or two upbeat "
        "community notes, (5) what's coming up this week — meetings and "
        "events. Use ONLY the material below.\n\n"
        f"OVERNIGHT REPORT:\n{overnight_md[:3000]}\n\n"
        f"WEATHER:\n{weather_prose[:1200]}\n\n"
        f"AIR: AQI {airnow.get('aqi', 'n/a')} ({airnow.get('level', 'n/a')})"
        f"; FIRES: {calfire.get('summary', 'n/a')}\n\n"
        f"STORIES:\n{_truncate(head, limit=18000)}\n\n"
        f"EVENTS: {ev[:1200]}\n\n"
        f"MEETINGS: {meetings_prose[:1200]}\n\n"
        f"GOOD NOTE: {good_prose[:800]}"
    )
    return _chat(prompt, max_tokens=3600, system=BRIEF_SYSTEM)
