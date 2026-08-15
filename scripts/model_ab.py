#!/usr/bin/env python3
"""Model A/B for the brief writer: deepseek-v4-flash-0731 vs Hermes-4.3-36B.

Same system prompt (BRIEF_SYSTEM), same source facts, same request.
Reports: status, wall time, token usage, and the full output for review.
Key from env NOUS_API_KEY_TEST (never embedded in this file).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

KEY = os.environ.get("NOUS_API_KEY_TEST", "")
BASE = "https://inference-api.nousresearch.com/v1"
SYSTEM = open("build/llm.py", encoding="utf-8").read().split('BRIEF_SYSTEM = (')[1].split(")")[0]
SYSTEM = json.loads('"' + SYSTEM.replace('\n', '\\n').replace('"', '\\"') + '"') if False else SYSTEM
# simpler: import the real constant
sys.path.insert(0, ".")
from build.llm import BRIEF_SYSTEM  # noqa: E402

FACTS = (
    "Write a 200-250 word test edition of the brief. Source material:\n\n"
    "OVERNIGHT REPORT:\nA night that opened with a road-rage pair stalling "
    "traffic on White Lane and closed with a stolen van on Kentucky Street "
    "and a fender dispute between big rigs at the Flying J. Law enforcement "
    "carried most of the load: a 90-plus mph DUI south of the Grapevine, a "
    "reported theft from a mobile home park on Barlow Road, and an "
    "attempt-to-locate after a woman was seen crying for help out the "
    "window of a red pickup at Chester and Belle Terrace. Fire crews were "
    "comparatively quiet: a residential alarm that amounted to nothing. "
    "8 incidents total.\n\n"
    "WEATHER:\nExpect a high near 92 and a low around 66 tonight. It is "
    "currently 82 at Meadows Field (KBFL). No active weather alerts. Air "
    "quality is 49, good.\n\n"
    "STORIES:\n"
    "- Kern County Fair announces Grandstand Arena events (KGET 17)\n"
    "  TEXT: The Kern County Fair unveiled the Grandstand Arena lineup, "
    "headlined by a night of demolition derby and a country concert, with "
    "tickets on sale starting Friday.\n"
    "- Man who faced murder charge in deadly stabbing on Taylor St in "
    "Bakersfield committed to state hospital (KGET 17)\n"
    "  TEXT: A Bakersfield man charged with murder in a 2024 stabbing on "
    "Taylor Street was found incompetent to stand trial and committed to a "
    "state hospital, where treatment can continue indefinitely.\n"
    "- City of Bakersfield to hold low-cost pediatric CPR training "
    "September-November (KGET 17)\n"
    "  TEXT: The city will run low-cost pediatric CPR classes at fire "
    "stations across Bakersfield from September through November, open to "
    "parents, grandparents, and caregivers.\n\n"
    "MEETINGS:\nSpecial Safe and Healthy Neighborhoods Committee - 2026-08-14 "
    "13:00; Keep Bakersfield Beautiful Committee - 2026-08-14 12:00.\n\n"
    "EVENTS:\nPEPPER With CYDEWAYS at Fox Theater on Fri, Aug 14; Gavin "
    "Adcock at Mechanics Bank Arena on Fri, Aug 14.\n\n"
    "GOOD NOTE: Kern County Fair Grandstand events announced."
)


def call(model: str, max_tokens: int = 700) -> dict:
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "temperature": 0.3,
        "messages": [{"role": "system", "content": BRIEF_SYSTEM},
                     {"role": "user", "content": FACTS}],
    }).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36"})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=240)
        d = json.loads(r.read())
        dt = time.time() - t0
        msg = d["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        if not text:
            text = "[reasoning-only] " + (msg.get("reasoning") or "")[:400]
        u = d.get("usage", {})
        return {"ok": True, "secs": round(dt, 1), "usage": u, "text": text}
    except urllib.error.HTTPError as e:
        return {"ok": False, "secs": round(time.time() - t0, 1),
                "error": f"HTTP {e.code}: {e.read()[:200]}"}


def main() -> None:
    models = sys.argv[1:] or ["deepseek/deepseek-v4-flash-0731",
                              "Hermes-4.3-36B"]
    for m in models:
        print("=" * 66)
        print("MODEL:", m)
        res = call(m)
        if not res["ok"]:
            print("FAILED:", res["error"], f"({res['secs']}s)")
            continue
        u = res["usage"]
        words = len(res["text"].split())
        print(f"OK {res['secs']}s | prompt={u.get('prompt_tokens')} "
              f"completion={u.get('completion_tokens')} "
              f"total={u.get('total_tokens')} | ~{words} words")
        print("-" * 66)
        print(res["text"])


if __name__ == "__main__":
    main()
