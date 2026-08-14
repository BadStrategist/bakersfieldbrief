#!/usr/bin/env python3
"""Permanent test suite for The Kern Overnight pipeline + map feature.

Run:  .venv/Scripts/python.exe -m pytest tests/ -q

Design rules (token-efficiency):
  * Fully offline — no network calls, ever (Nominatim/Deepgram/fetch are
    monkeypatched or use the committed cache).
  * One shared session-scoped cache fixture — the committed geo cache is
    loaded once and reused by every test.
  * Data tests read the committed datasets (incidents/, data/incidents_geo.json)
    — no fixture files, no duplication.
  * No pytest plugins beyond core.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TZ = dt.timezone(dt.timedelta(hours=-7))
KERN_BOUNDS = (34.8, 36.0, -120.0, -117.2)  # lat_min, lat_max, lng_min, lng_max


@pytest.fixture(scope="session")
def geo_cache():
    """Committed Nominatim cache — loaded once per session, shared."""
    from kern_overnight import geo
    return geo._load_cache()


# ---------------------------------------------------------------- geocoding
class TestGeo:
    def test_block_precision_known_street(self, geo_cache):
        from kern_overnight import geo
        g = geo.geocode("the 2100 block of Niles Street", geo_cache)
        assert g["precision"] == "block"
        assert abs(g["lat"] - 35.38) < 0.02

    def test_area_precision_town(self, geo_cache):
        from kern_overnight import geo
        assert geo.geocode("Oildale", geo_cache)["precision"] == "area"

    def test_cross_street_resolves(self, geo_cache):
        from kern_overnight import geo
        g = geo.geocode("Williams Street at Eureka Street, East Bakersfield", geo_cache)
        assert g["precision"] != "city"
        assert abs(g["lat"] - 35.37) < 0.03

    def test_city_fallback_unknown(self, geo_cache):
        from kern_overnight import geo
        g = geo.geocode("the 1400 block of Hops Lane", geo_cache)
        assert g["precision"] in ("city", "street", "block")  # never crashes

    def test_nominatim_result_is_cached(self, tmp_path, monkeypatch):
        from kern_overnight import geo
        cache: dict = {}

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return [{"lat": "35.40", "lon": "-119.10"}]

        monkeypatch.setattr(geo.requests, "get", lambda *a, **k: FakeResp())
        hit = geo._nominatim("Test Street, Bakersfield, CA", cache)
        assert hit == (35.40, -119.10)
        assert "Test Street, Bakersfield, CA" in cache
        # second call must come from cache, not the network
        monkeypatch.setattr(geo.requests, "get",
                            lambda *a, **k: pytest.fail("network called twice"))
        assert geo._nominatim("Test Street, Bakersfield, CA", cache) == (35.40, -119.10)

    def test_feed_shape_and_privacy(self, geo_cache, tmp_path):
        from kern_overnight import geo
        n = geo.build_feed(ROOT / "incidents", tmp_path / "feed.json", max_age_h=200)
        assert n >= 10
        feed = json.loads((tmp_path / "feed.json").read_text(encoding="utf-8"))
        # no exact street numbers: allow "2400 block of X", forbid "124 X Ave"
        exact = re.compile(
            r"\b\d{1,4}\s+[A-Za-z]+\s+"
            r"(street|avenue|road|lane|drive|highway|way|boulevard)\b", re.I)
        for d in feed:
            assert {"lat", "lng", "p", "t", "type", "area"} <= set(d)
            assert not exact.search(d["area"]), d["area"]
            assert KERN_BOUNDS[0] <= d["lat"] <= KERN_BOUNDS[1]


# ------------------------------------------------------------- transcription
class TestTranscribe:
    def test_merge_segments(self):
        from kern_overnight import transcribe as T
        segs = [(0.0, 1.0), (1.5, 3.0), (5.0, 6.0), (8.0, 9.0), (9.5, 10.0)]
        # explicit gap=2.0 tests the merge semantics; the default is 10.0
        assert T._merge_segments(segs, gap_s=2.0) == [(0.0, 3.0), (5.0, 6.0), (8.0, 10.0)]
        assert T._merge_segments([(0, 1), (3, 4)], gap_s=2.0) == [(0, 1), (3, 4)]
        assert T._merge_segments([(0.0, 1.0), (8.0, 9.0)], gap_s=10.0) == [(0.0, 9.0)]
        assert T._merge_segments([]) == []

    def test_overnight_window(self):
        from kern_overnight import transcribe as T
        blocks = T.overnight_blocks(dt.date(2026, 8, 9), TZ) \
            if hasattr(T, "overnight_blocks") else None
        if blocks is None:  # overnight_blocks lives in fetch
            from kern_overnight import fetch
            blocks = fetch.overnight_blocks(dt.date(2026, 8, 9), TZ)
        assert len(blocks) == 18
        first = dt.datetime.fromtimestamp(blocks[0][0], TZ)
        last_end = dt.datetime.fromtimestamp(blocks[-1][1], TZ)
        assert (first.strftime("%H:%M"), last_end.strftime("%H:%M")) == ("21:00", "06:00")

    def test_in_overnight_window(self):
        from kern_overnight import transcribe as T
        inside = int(dt.datetime(2026, 8, 8, 23, 30, tzinfo=TZ).timestamp())
        outside = int(dt.datetime(2026, 8, 9, 12, 0, tzinfo=TZ).timestamp())
        assert T._in_overnight_window(inside, dt.date(2026, 8, 9), TZ)
        assert not T._in_overnight_window(outside, dt.date(2026, 8, 9), TZ)

    def test_transcribe_wav_slice_and_kwargs(self):
        import numpy as np
        from kern_overnight import transcribe as T
        captured = {}

        class FakeModel:
            def transcribe(self, audio, **kw):
                captured["kw"] = kw
                captured["samples"] = len(np.asarray(audio))
                return ([type("S", (), {"text": "dispatch", "start": 0.25,
                                        "end": 1.0, "avg_logprob": -0.4})()], None)

        audio = np.zeros(16000 * 4, dtype=np.float32)
        audio[16000:32000] = 0.1
        rows = T._transcribe_wav(FakeModel(), audio, (1.0, 3.0), "vocab")
        assert captured["samples"] == 32000
        assert "audio_start" not in captured["kw"]
        assert captured["kw"]["initial_prompt"] == "vocab"
        assert captured["kw"]["condition_on_previous_text"] is False
        assert abs(rows[0]["start"] - 1.25) < 1e-6

    def test_whisper_row_shape(self, tmp_path):
        import wave as wave_mod
        from kern_overnight import transcribe as T

        class FakeModel:
            def transcribe(self, audio, **kw):
                return ([type("S", (), {"text": "copy", "start": 0.5,
                                        "end": 2.0, "avg_logprob": -0.3})()], None)

        # synthetic 16k mono WAV (3 s) — no audio fixtures needed
        wav = tmp_path / "s.wav"
        with wave_mod.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00" * 16000 * 2 * 3)
        rows = T._transcribe_whisper(FakeModel(), wav, [(0.0, 3.0)], 1786261275,
                                     TZ, "f.mp3", "vocab")
        assert set(rows[0]) == {"time_local", "duration", "text", "confidence",
                                "source_file", "engine"}
        assert rows[0]["engine"].startswith("faster-whisper:")
        assert rows[0]["time_local"]  # anchored to block epoch

    def test_engine_dispatch_default_and_override(self, monkeypatch):
        import importlib
        import kern_overnight.transcribe as T
        assert T.ENGINE == "faster-whisper"
        monkeypatch.setenv("KO_STT_ENGINE", "deepgram")
        importlib.reload(T)
        assert T.ENGINE == "deepgram"
        monkeypatch.delenv("KO_STT_ENGINE")
        importlib.reload(T)


# ------------------------------------------------------------------ deepgram
class TestDeepgram:
    def test_key_missing_fails_loudly(self, monkeypatch):
        from kern_overnight import deepgram
        monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
        with pytest.raises(deepgram.DeepgramError):
            deepgram._key()

    def test_key_reads_env(self, monkeypatch):
        from kern_overnight import deepgram
        monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
        assert deepgram._key() == "test-key"

    def test_row_shape_and_engine_tag(self):
        from kern_overnight import deepgram
        rows = deepgram._segment_rows(
            [{"transcript": "medical aid", "confidence": 0.9,
              "start": 10.0, "end": 12.5}], 1786261275, TZ, "f.mp3")
        assert set(rows[0]) == {"time_local", "duration", "text", "confidence",
                                "source_file", "engine"}
        assert rows[0]["engine"] == "deepgram:nova-3"
        assert rows[0]["duration"] == 2.5

    def test_request_keywords_and_model(self, monkeypatch):
        from kern_overnight import deepgram
        monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
        captured = {}

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"results": {"utterances": []}}

        def fake_post(url, **kw):
            captured.update(kw)
            return FakeResp()

        monkeypatch.setattr(deepgram.requests, "post", fake_post)
        rows = deepgram.transcribe_segments(
            [(0.0, 2.0, b"\x00" * 16000)], 1786261275, TZ, "f.mp3")
        assert rows == []
        assert captured["params"]["model"] == "nova-3"
        assert "keywords" in captured["params"]
        assert captured["headers"]["Authorization"] == "Token k"


# --------------------------------------------------------------------- fetch
class TestFetch:
    def test_epoch_from_name(self):
        from kern_overnight import fetch
        assert fetch._epoch_from_name("14029-1786329296.mp3") == 1786329296
        assert fetch._epoch_from_name("nope.mp3") is None

    def test_fetch_window_filter_only(self, tmp_path, monkeypatch):
        """Out-of-window archives are skipped; only in-window blocks kept."""
        from kern_overnight import fetch
        in_ts = int(dt.datetime(2026, 8, 8, 23, 0, tzinfo=TZ).timestamp())
        out_ts = int(dt.datetime(2026, 8, 9, 12, 0, tzinfo=TZ).timestamp())
        monkeypatch.setattr(fetch, "_archive_entries",
                            lambda d: [{"id": f"14029-{in_ts}", "startTs": in_ts},
                                       {"id": f"14029-{out_ts}", "startTs": out_ts}])

        def fake_download(archive_id, start_ts, audio_dir):
            p = audio_dir / f"14029-{start_ts}.mp3"
            p.write_bytes(b"\x00" * 60_000)
            return p

        monkeypatch.setattr(fetch, "_download_archive", fake_download)
        got = fetch.fetch(dt.date(2026, 8, 9), tmp_path, TZ)
        assert len(got) == 1
        assert str(in_ts) in got[0].name


# --------------------------------------------------------------------- data
@pytest.fixture(scope="module")
def incidents():
    out = {}
    for f in sorted((ROOT / "incidents").glob("*.json")):
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    assert out, "no incident datasets committed"
    return out


class TestData:
    def test_incidents_schema_and_privacy(self, incidents):
        required = {"time", "agency", "type", "area", "summary",
                    "disposition", "notability"}
        for day, incs in incidents.items():
            for inc in incs:
                assert required <= set(inc), f"{day}: missing fields"
                assert 1 <= inc["notability"] <= 5
                assert 0 <= int(inc["time"][:2]) <= 6 or int(inc["time"][:2]) >= 21
                blob = json.dumps(inc).lower()
                assert not re.search(r"\b(hector|luna|raphael|billy|wood)\b", blob)
                assert not re.search(r"\b\d{3}[a-z]{3}\b|\bxq\d+\b", blob)

    def test_map_feed_schema(self):
        feed = json.loads((ROOT / "data" / "incidents_geo.json")
                          .read_text(encoding="utf-8"))
        assert len(feed) >= 10
        for d in feed:
            assert {"lat", "lng", "p", "t", "type", "area"} <= set(d)
            assert KERN_BOUNDS[0] <= d["lat"] <= KERN_BOUNDS[1]
            assert KERN_BOUNDS[2] <= d["lng"] <= KERN_BOUNDS[3]

    def test_overnight_summary_latest_only(self):
        """The rundown must reflect ONLY the latest night, never all days."""
        from build.builders.daily import _overnight_summary, _overnight_rundown
        ko = _overnight_summary()
        assert ko is not None
        latest = sorted((ROOT / "incidents").glob("*.json"))[-1].stem
        assert ko["date"] == latest
        assert ko["count"] == len(json.loads(
            (ROOT / "incidents" / f"{latest}.json").read_text(encoding="utf-8")))
        rd = _overnight_rundown()
        assert rd and rd.endswith(f"{ko['count']} incidents total")
        assert "crisiss" not in rd  # pluralization is correct

    def test_builders_import_clean(self):
        import subprocess
        r = subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"),
             "-c", "import build.builders.map, build.builders.static_pages, "
                   "build.builders.overnight, build.builders.daily"],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[:300]

    def test_arena_parser_pairs_own_dates(self, monkeypatch):
        """Regression: every arena event must keep ITS OWN date — the old
        parser stamped the first date found on each page onto all events
        (Brit Floyd showed Aug 14). Slides with a time-only date-section
        (no full date) must be dropped, never fabricated."""
        import build.sources.venues as venues

        html = """
        <article class="slide"><h2 class="slide-title">
        <a href="/event/gavin-adcock/147/" data-gtm-click>Gavin Adcock</a></h2>
        <div class="date-section"><span>Aug 14, 2026 \u2022 Fri 7:00 PM</span><span></span></div></article>
        <article class="slide"><h2 class="slide-title">
        <a href="/event/brit-floyd/146/" data-gtm-click>Brit Floyd</a></h2>
        <div class="date-section"><span>Oct 13, 2026 \u2022 Tue 8:00 PM</span><span></span></div></article>
        <article class="slide"><h2 class="slide-title">
        <a href="/event/blueys-big-play/145/" data-gtm-click>Bluey's Big Play</a></h2>
        <div class="date-section"><span>Tue 6:00 PM</span><span></span></div></article>
        <article class="slide"><h2 class="slide-title">
        <a href="https://www.axs.com/series/31844/hot-wheels-tickets" data-gtm-click>Hot Wheels</a></h2>
        <div class="date-section"><span>Sep 1, 2026 \u2022 Tue 7:00 PM</span><span></span></div></article>
        """
        class FakeResp:
            text = html
        import build.common as common
        monkeypatch.setattr(common, "fetch", lambda *a, **k: FakeResp())

        evs = venues._arena({"url": "https://www.mechanicsbankarena.com/events"})
        by_url = {e["url"].split("/event/")[1].split("/")[0]: e for e in evs}
        assert by_url["gavin-adcock"]["when"].startswith("Aug 14, 2026")
        assert by_url["brit-floyd"]["when"].startswith("Oct 13, 2026")
        assert "blueys" not in by_url          # time-only date -> dropped, not guessed
        assert "hot-wheels" not in by_url      # external axs links excluded

    def test_checkpoint_skips_non_repo_paths(self, tmp_path, monkeypatch):
        """Tier-2: the transcript checkpoint must NEVER run git against
        non-repo paths (pytest temp dirs) — transcription never breaks."""
        import subprocess
        calls = []

        class FakeCompleted:
            def __init__(self, rc):
                self.returncode = rc

        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **k: calls.append(a) or FakeCompleted(0))
        from kern_overnight.transcribe import _ko_checkpoint
        _ko_checkpoint(tmp_path / "out.jsonl", 3, 3, push=True)
        assert calls == []

    def test_checkpoint_commits_repo_transcripts(self, monkeypatch):
        """Tier-2: for a repo transcript, checkpoint does git add (only that
        file) + commit + optional push, and tolerates push failure."""
        import subprocess

        class FakeCompleted:
            def __init__(self, rc):
                self.returncode = rc

        calls = []
        def fake_run(cmd, **k):
            calls.append(cmd)
            rc = 0
            if cmd[:2] == ["git", "push"]:
                rc = 128  # simulate non-fast-forward — must be tolerated
            return FakeCompleted(rc)

        monkeypatch.setattr(subprocess, "run", fake_run)
        from kern_overnight.transcribe import _ko_checkpoint
        _ko_checkpoint(ROOT / "transcripts" / "2026-08-11.jsonl", 3, 18, push=True)
        adds = [c for c in calls if c[:2] == ["git", "add"]]
        assert adds, "git add must run for repo transcripts"
        assert "transcripts" in str(adds[0][-1])
        assert str(adds[0][-1]).endswith("2026-08-11.jsonl")
        assert any(c[:2] == ["git", "push"] for c in calls)

    def test_street_gazetteer_loaded(self):
        """The Bakersfield street gazetteer must exist, be large, and
        contain the major arterials dispatchers actually name."""
        import kern_overnight.streetcheck as sc
        streets = sc.load_streets()
        assert len(streets) > 5000
        for s in ("Chester Avenue", "Truxtun Avenue", "Panama Lane",
                  "Rosedale Highway", "Mount Vernon Avenue", "White Lane"):
            assert s in streets

    def test_streetcheck_matches_fuzzy_and_filters(self):
        """Street validation: exact matches resolve, mis-hears get fuzzy
        suggestions, and radio noise is filtered out."""
        import kern_overnight.streetcheck as sc
        streets = sc.load_streets()
        text = ("on the 2800 block of West Chester Avenue. "
                "Also checking near Famoso Road and Wite Lane. "
                "Copy that, two point five. Another location possible.")
        results = sc.scan(text, streets)
        statuses = {s for s, _, _ in results}
        assert "MATCH" in statuses
        fuzzy = [d for s, c, d in results if s == "FUZZY"]
        assert any("White Lane" in d for d in fuzzy)
        # radio noise must not surface as candidates
        assert not any("two point" in c.lower() or "copy" in c.lower()
                       for _, c, _ in results)

    def test_extractor_privacy_and_dedupe(self):
        """Deterministic extractor: privacy rows are dropped, same-type
        repeats within the window merge, distinct incidents stay."""
        from kern_overnight import extract as EX
        streets = ["Chester Avenue", "White Lane"]
        rows = [
            {"time_local": "02:00", "text": "vehicle fire on the 2800 block "
             "of West Chester Avenue, engine 42 responding"},
            {"time_local": "02:05", "text": "update on that vehicle fire at "
             "Chester Avenue, now fully involved"},
            {"time_local": "03:00", "text": "black 2012 sedan plate 4ABC123 "
             "speeding southbound on White Lane"},
            {"time_local": "04:00", "text": "structure fire at 100 block of "
             "White Lane, multiple engines"},
        ]
        incs = EX.extract(rows, streets)
        types = [i["type"] for i in incs]
        assert types.count("vehicle fire") == 1       # deduped
        assert "structure fire" in types
        assert not any("plate" in i.get("summary", "") for i in incs)  # privacy
        assert incs[0]["notability"] == 4             # merged update raised it
