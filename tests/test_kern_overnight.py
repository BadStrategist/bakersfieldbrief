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
def geo_cache(tmp_path_factory):
    """A COPY of the committed Nominatim cache, redirected to a temp file.

    geo._nominatim calls _save_cache on every lookup, so before this fixture the
    suite rewrote the committed data/geo_cache.json as it ran (that file is
    perennially dirty on the build box for exactly this reason) and cached None
    for every invented name such as "Test Street".
    """
    from kern_overnight import geo
    real = geo.CACHE_PATH
    tmp = tmp_path_factory.mktemp("geocache") / "geo_cache.json"
    if real.exists():
        tmp.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
    mp = pytest.MonkeyPatch()
    mp.setattr(geo, "CACHE_PATH", tmp)
    yield geo._load_cache()
    mp.undo()


@pytest.fixture(autouse=True)
def no_live_nominatim(monkeypatch):
    """The suite must not depend on, or hammer, the live Nominatim service.

    A test that needs a response patches geo.requests.get itself, which runs after
    this fixture and wins.
    """
    from kern_overnight import geo
    monkeypatch.setattr(geo.requests, "get",
                        lambda *a, **k: pytest.fail("test called live Nominatim"))


def _fake_nominatim(monkeypatch, lat=35.381, lon=-119.001, empty=False):
    """Answer Nominatim deterministically instead of over the network.

    These tests assert OUR logic (block refinement, cross-street precision, the
    fallback ladder) and used to do it by calling the live service, which also
    wrote the results into the committed cache.
    """
    from kern_overnight import geo

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [] if empty else [{"lat": str(lat), "lon": str(lon)}]

    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: _R())


# ---------------------------------------------------------------- geocoding
class TestGeo:
    def test_block_precision_known_street(self, geo_cache, monkeypatch):
        _fake_nominatim(monkeypatch)
        from kern_overnight import geo
        g = geo.geocode("the 2100 block of Niles Street", geo_cache)
        assert g["precision"] == "block"
        assert abs(g["lat"] - 35.38) < 0.02

    def test_area_precision_town(self, geo_cache):
        from kern_overnight import geo
        assert geo.geocode("Oildale", geo_cache)["precision"] == "area"

    def test_cross_street_resolves(self, geo_cache, monkeypatch):
        _fake_nominatim(monkeypatch, 35.372, -119.010)
        from kern_overnight import geo
        g = geo.geocode("Williams Street at Eureka Street, East Bakersfield", geo_cache)
        assert g["precision"] != "city"
        assert abs(g["lat"] - 35.37) < 0.03

    def test_city_fallback_unknown(self, geo_cache, monkeypatch):
        _fake_nominatim(monkeypatch, empty=True)  # “no such place”, not a lookup failure
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

    def test_feed_shape_and_privacy(self, geo_cache, tmp_path, monkeypatch):
        _fake_nominatim(monkeypatch, empty=True)
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
        assert len(blocks) == 24
        first = dt.datetime.fromtimestamp(blocks[0][0], TZ)
        last_end = dt.datetime.fromtimestamp(blocks[-1][1], TZ)
        assert (first.strftime("%H:%M"), last_end.strftime("%H:%M")) == ("19:00", "07:00")

    def test_in_overnight_window(self):
        from kern_overnight import transcribe as T
        def at(h, m=0, day=8):
            return int(dt.datetime(2026, 8, day, h, m, tzinfo=TZ).timestamp())

        # the night that owns Aug 9 runs Aug 8 19:00 to Aug 9 07:00
        for h, m, day in ((19, 0, 8), (19, 16, 8), (23, 30, 8),
                          (5, 30, 9), (6, 45, 9)):
            assert T._in_overnight_window(at(h, m, day), dt.date(2026, 8, 9), TZ), (h, m, day)
        for h, m, day in ((18, 0, 8), (12, 0, 9), (7, 0, 9), (20, 0, 9)):
            assert not T._in_overnight_window(at(h, m, day), dt.date(2026, 8, 9), TZ), (h, m, day)

    def test_transcribe_wav_slice_and_kwargs(self):
        np = pytest.importorskip("numpy")  # heavy PC-only dep; skip in CI
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
        pytest.importorskip("numpy")  # heavy PC-only dep; skip in CI
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
        rows, n_failed = T._transcribe_whisper(FakeModel(), wav, [(0.0, 3.0)], 1786261275,
                                     TZ, "f.mp3", "vocab")
        assert set(rows[0]) == {"time_local", "duration", "text", "confidence",
                                "source_file", "engine", "offset_s"}
        assert rows[0]["engine"].startswith("faster-whisper:")
        assert rows[0]["time_local"]  # anchored to block epoch

    def test_a_straddling_block_keeps_only_the_window_and_records_the_offset(self, tmp_path):
        """A block that starts before 19:00 contributes only after it (5.1, 5.2)."""
        import wave as wave_mod
        from kern_overnight import transcribe as T

        class FakeModel:
            def __init__(self, starts):
                self.starts = list(starts)

            def transcribe(self, audio, **kw):
                s = self.starts.pop(0)
                return ([type("S", (), {"text": "copy", "start": s, "end": s + 2.0,
                                        "avg_logprob": -0.3})()], None)

        wav = tmp_path / "s.wav"
        with wave_mod.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00" * 16000 * 2 * 63)   # 63 s, room for a 60 s offset

        # a block that starts one minute before the window opens: its first
        # minute belongs to the previous report and must not appear
        block = int(dt.datetime(2026, 10, 8, 18, 59, 0, tzinfo=TZ).timestamp())
        rows, failed = T._transcribe_whisper(FakeModel([0.0, 0.0]), wav,
                                             [(0.0, 3.0), (60.0, 63.0)], block,
                                             TZ, "14029-straddle.mp3", "vocab")
        assert failed == 0
        assert len(rows) == 1                       # 18:59:00 dropped, 19:00:00 kept
        assert rows[0]["time_local"] == "19:00"
        assert rows[0]["offset_s"] == 60.0
        assert rows[0]["source_file"] == "14029-straddle.mp3"

        # a block well inside the night keeps its rows, as before
        inside = int(dt.datetime(2026, 10, 8, 23, 0, tzinfo=TZ).timestamp())
        rows2, _ = T._transcribe_whisper(FakeModel([0.5]), wav, [(0.0, 3.0)], inside,
                                         TZ, "14029-inside.mp3", "vocab")
        assert rows2[0]["time_local"] == "23:00"
        assert len(rows2) == 1
        assert rows2[0]["offset_s"] == 0.5

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
        # starts 15 min before 19:00, so it carries the first quarter hour of
        # the night: it belongs to the window. The old containment rule
        # (w_start <= startTs) dropped exactly this block every night.
        straddle_ts = int(dt.datetime(2026, 8, 8, 18, 45, tzinfo=TZ).timestamp())
        early_ts = int(dt.datetime(2026, 8, 8, 18, 0, tzinfo=TZ).timestamp())
        monkeypatch.setattr(fetch, "_archive_entries",
                            lambda d: [{"id": f"14029-{in_ts}", "startTs": in_ts},
                                       {"id": f"14029-{out_ts}", "startTs": out_ts},
                                       {"id": f"14029-{straddle_ts}", "startTs": straddle_ts},
                                       {"id": f"14029-{early_ts}", "startTs": early_ts}])

        def fake_download(archive_id, start_ts, audio_dir):
            p = audio_dir / f"14029-{start_ts}.mp3"
            p.write_bytes(b"\x00" * 60_000)
            return p

        monkeypatch.setattr(fetch, "_download_archive", fake_download)
        got = fetch.fetch(dt.date(2026, 8, 9), tmp_path, TZ)
        assert sorted(p.name for p in got) == sorted([f"14029-{in_ts}.mp3",
                                                     f"14029-{straddle_ts}.mp3"])

    def test_a_block_already_on_disk_costs_no_play_call(self, tmp_path, monkeypatch):
        """Never spend a play.php call (or a login) on a block we hold."""
        from kern_overnight import fetch
        ts = int(dt.datetime(2026, 8, 8, 23, 0, tzinfo=TZ).timestamp())
        p = tmp_path / f"14029-{ts}.mp3"
        p.write_bytes(b"\x00" * 60_000)

        def boom(archive_id):
            raise AssertionError("_audio_url called for a block already on disk")

        monkeypatch.setattr(fetch, "_audio_url", boom)
        assert fetch._download_archive(f"14029-{ts}", ts, tmp_path) == p


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
                # Report window is 7 PM - 7 AM (19:00 -> 06:59); the emulator
                # fills the hours the radio feed does not carry.
                assert 0 <= int(inc["time"][:2]) <= 6 or int(inc["time"][:2]) >= 19
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
            [sys.executable,
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
        # transcript-only pushes must carry [skip ci] so they never trigger
        # a site deploy (private-repo Actions-minute budget protection)
        commits = [c for c in calls if c[:2] == ["git", "commit"]]
        assert commits and "[skip ci]" in " ".join(str(x) for x in commits[0])

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

    def test_brief_lede_never_double_escapes(self, tmp_path, monkeypatch):
        """REGRESSION (2026-08-14 live incident): the brief lede must never
        render literal '&lt;p&gt;' / '&lt;strong&gt;' — the fallback greeting
        is already HTML and must pass through unescaped."""
        import datetime as dt
        from build.builders import daily as D

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        # the per-day LLM brief cache may exist locally — force the
        # deterministic fallback path this test is guarding
        monkeypatch.setattr(D, "_cached_brief_body", lambda today: None)
        class Ctx:
            build_report = {}

        today = dt.date(2026, 8, 14)
        top = {"title": "Analysis: City of Bakersfield has invested over $100M in affordable housing", "url": "https://example.com/1", "source": "KGET 17"}
        weather = {"forecast": {"high": 92, "low": 66}, "alerts": []}
        airnow, calfire = {}, {"summary": "2 in Kern"}
        escribe = {"upcoming": []}
        html_out = D._article_lead(top, [], weather, airnow, calfire,
                                   escribe, [], today, "../../", Ctx())
        assert "&lt;p&gt;" not in html_out, "lede double-escaped a <p> tag"
        assert "&lt;strong&gt;" not in html_out, "lede double-escaped a <strong> tag"
        assert "<strong>Good morning" in html_out, "fallback greeting must render as real HTML"
        assert "**" not in html_out, "stray markdown bold leaked into the lede"

    def test_diversify_caps_single_source(self):
        """The brief's stories must never be one outlet's feed — any single
        source is capped, order is preserved."""
        from build.builders.daily import _diversify
        items = [{"title": f"k{i}", "source": "KGET 17"} for i in range(5)] + \
                [{"title": f"a{i}", "source": "23ABC"} for i in range(5)]
        out = _diversify(items, cap=3)
        kget = sum(1 for i in out if i["source"].startswith("KGET"))
        abc = sum(1 for i in out if i["source"].startswith("23ABC"))
        assert kget == 3 and abc == 3
        assert out[0]["title"] == "k0"  # order preserved

    def test_top_stories_leads_are_bolded(self):
        """Render-side bold: every paragraph under 'Top stories' gets a
        bolded first sentence (skimmable leads), other sections stay plain."""
        from build.builders.daily import _para_html
        prose = ("Good morning.\n\n## Top stories\n\n"
                 "KGET 17 reports that the fair opens Friday. Gates at noon.\n\n"
                 "According to 23ABC, the council met. They voted 4-1.\n\n"
                 "## Something good\n\nA nice note here. Not bolded.")
        html_out = _para_html(prose)
        assert html_out.count("<strong>") == 2
        assert "<strong>KGET 17 reports that the fair opens Friday.</strong>" in html_out
        assert "<strong>According to 23ABC, the council met.</strong>" in html_out
        assert "<strong>A nice note here.</strong>" not in html_out


# ------------------------------------------------- social post publish gate
class TestSocialGate:
    """post_facebook.gate_check must NEVER approve a partial or incomplete
    overnight report — the reel/photo post can only go out once the
    overnight is fully transcribed AND published."""

    def _write(self, tmp_path, name: str, text: str) -> Path:
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return p

    def _run(self, tmp_path, overnight_text: str, brief_text: str = "x" * 300):
        import scripts.post_facebook as pf
        bp = self._write(tmp_path, "2026-08-17.json", json.dumps({"body": brief_text}))
        op = self._write(tmp_path, "2026-08-17.md", overnight_text)
        old_b, old_o = pf.BRIEFS, pf.OVERNIGHTS
        pf.BRIEFS, pf.OVERNIGHTS = tmp_path, tmp_path
        try:
            return pf.gate_check("2026-08-17")
        finally:
            pf.BRIEFS, pf.OVERNIGHTS = old_b, old_o

    def test_complete_report_passes(self, tmp_path):
        full = ("# The Kern Overnight — August 17, 2026\n\n"
                "Opening paragraph with real content describing the night's "
                "calls across Bakersfield and Kern County, including the "
                "most serious incident and the general picture.\n\n"
                "## The big one\n\nSomething notable happened around the "
                "county and crews responded in force.\n\n"
                "## Around the county\n\nA couple of scannable bullets about "
                "the night's other calls and how they were handled.\n\n"
                "## The log\n\n21:39 — Item one. 22:10 — Item two. "
                "00:20 — Item three. 01:48 — Item four.\n\n"
                "## Night notes\n\nTwo sentences of notes summarising how "
                "the night went and what stood out.")
        assert self._run(tmp_path, full) is not None

    def test_partial_coverage_marker_rejected(self, tmp_path):
        partial = ("> ⚠️ PARTIAL COVERAGE: transcription was still running "
                   "when this report was written.\n\n"
                   "# The Kern Overnight — August 17, 2026\n\n"
                   "## Night notes\n\nPartial notes.")
        assert self._run(tmp_path, partial) is None

    def test_missing_required_sections_rejected(self, tmp_path):
        incomplete = ("# The Kern Overnight — August 17, 2026\n\n"
                      "Only an opening paragraph, no Night notes.")
        assert self._run(tmp_path, incomplete) is None

    def test_missing_overnight_rejected(self, tmp_path):
        import scripts.post_facebook as pf
        bp = self._write(tmp_path, "2026-08-17.json", json.dumps({"body": "x" * 300}))
        old_b, old_o = pf.BRIEFS, pf.OVERNIGHTS
        pf.BRIEFS, pf.OVERNIGHTS = tmp_path, tmp_path
        try:
            assert pf.gate_check("2026-08-17") is None
        finally:
            pf.BRIEFS, pf.OVERNIGHTS = old_b, old_o

    def test_wait_for_gate_retry_disabled_skips_fast(self, tmp_path):
        """retry=0 must not hang: a partial overnight returns None at once."""
        import scripts.post_facebook as pf
        partial = ("> ⚠️ PARTIAL COVERAGE: transcription was still running "
                   "when this report was written.\n\n"
                   "# The Kern Overnight — August 17, 2026\n\n"
                   "## Night notes\n\nPartial notes.")
        self._write(tmp_path, "2026-08-17.json", json.dumps({"body": "x" * 300}))
        self._write(tmp_path, "2026-08-17.md", partial)
        old_b, old_o = pf.BRIEFS, pf.OVERNIGHTS
        pf.BRIEFS, pf.OVERNIGHTS = tmp_path, tmp_path
        try:
            assert pf.wait_for_gate("2026-08-17", 0) is None
        finally:
            pf.BRIEFS, pf.OVERNIGHTS = old_b, old_o

    def test_wait_for_gate_complete_passes_immediately(self, tmp_path):
        import scripts.post_facebook as pf
        full = ("# The Kern Overnight — August 17, 2026\n\n"
                "Opening paragraph with real content describing the night's "
                "calls across Bakersfield and Kern County, including the "
                "most serious incident and the general picture.\n\n"
                "## The big one\n\nSomething notable happened around the "
                "county and crews responded in force.\n\n"
                "## Around the county\n\nA couple of scannable bullets about "
                "the night's other calls and how they were handled.\n\n"
                "## The log\n\n21:39 — Item one. 22:10 — Item two. "
                "00:20 — Item three. 01:48 — Item four.\n\n"
                "## Night notes\n\nTwo sentences of notes summarising how "
                "the night went and what stood out.")
        self._write(tmp_path, "2026-08-17.json", json.dumps({"body": "x" * 300}))
        self._write(tmp_path, "2026-08-17.md", full)
        old_b, old_o = pf.BRIEFS, pf.OVERNIGHTS
        pf.BRIEFS, pf.OVERNIGHTS = tmp_path, tmp_path
        try:
            assert pf.wait_for_gate("2026-08-17", 25) is not None
        finally:
            pf.BRIEFS, pf.OVERNIGHTS = old_b, old_o


class TestBriefJson:
    """make_brief_json must build a valid reel config deterministically from
    the committed data — the daily reel renderer's schema is the contract."""

    def test_build_for_committed_date(self):
        import scripts.make_brief_json as mbj
        cfg = mbj.build("2026-08-17")
        for k in ("brand", "date_label", "kicker", "tagline", "url", "stories"):
            assert cfg.get(k), f"missing required key: {k}"
        assert 1 <= len(cfg["stories"]) <= 4
        assert cfg["date_label"] == "MONDAY, AUGUST 17"
        for s in cfg["stories"]:
            assert s.get("headline"), "every story needs a headline"
            assert len(s["headline"].split()) <= 12, "headline too long"
            assert s.get("scene") in mbj.TYPE_SCENE.values()

    def test_lead_is_the_most_serious_incident(self):
        """The brief's own editorial framing ('most serious') must drive which
        incident leads the reel — here the Monterey Street firearm brandishing
        (notability 4) leads, not a lesser call."""
        import scripts.make_brief_json as mbj
        cfg = mbj.build("2026-08-17")
        lead = cfg["stories"][0]
        assert "Monterey" in lead["headline"]
        assert lead["time"] == "11:00 PM"

    def test_stories_never_duplicate(self):
        """A story may never appear twice in the reel — the scene-variety
        fallback once re-picked the 2nd story as the 3rd (suicidal subject
        duplicated on 2026-08-18). Every headline must be unique."""
        import scripts.make_brief_json as mbj
        for date in ("2026-08-17", "2026-08-18"):
            cfg = mbj.build(date)
            heads = [s["headline"] for s in cfg["stories"]]
            assert len(heads) == len(set(heads)), \
                f"duplicate story in reel for {date}: {heads}"

    def test_music_rotates_daily(self):
        """The reel music bed must rotate deterministically: a DIFFERENT bed
        on consecutive days, the SAME bed for the same date (so re-renders
        reproduce the reel), cycling through the full stack."""
        import scripts.make_brief_json as mbj
        assert len(mbj.REEL_BEDS) == 3
        beds = [mbj.music_for_date(d) for d in
                ("2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21")]
        # one full 3-day cycle covers every bed exactly once
        assert len(set(beds[:3])) == 3, f"rotation repeated: {beds}"
        # consecutive days always differ (no same bed twice in a row)
        assert all(beds[i] != beds[i + 1] for i in range(len(beds) - 1))
        # day 1 vs day 4: same bed (3-day cycle)
        assert beds[0] == beds[3]
        # deterministic: same date, same bed
        assert mbj.music_for_date("2026-08-18") == beds[0]
        # all in the stack (no fallback triggered for valid dates)
        assert all(b in mbj.REEL_BEDS for b in beds)

    def test_subhead_never_cuts_decimal_dots(self):
        """273.6 (penal-code decimal) must not be treated as a sentence end."""
        import scripts.make_brief_json as mbj
        s = mbj._first_sentence("Domestic violence in progress (273.6) at a "
                                "residence on Animas Court; units responding.")
        assert s.startswith("Domestic violence in progress (273.6)")
        assert not s.endswith("(273.")


class TestNoGuessingGate:
    """The duplicate guard must only count real daily posts (reel/photo), and
    the gate must verify the overnight is LIVE on the website (a repo file is
    not publication)."""

    def test_link_post_never_satisfies_duplicate_guard(self):
        """A newsletter promo that mentions the brief URL must not block the
        daily reel — that bug previously skipped a whole day."""
        import scripts.post_facebook as pf
        promo = {"permalink_url": "https://www.facebook.com/posts/12345",
                 "message": "In depth today: https://bakersfieldbrief.com/briefs/2026-08-17/",
                 "type": "link"}
        assert not pf._is_daily_post(promo)

    def test_reel_and_photo_satisfy_duplicate_guard(self):
        import scripts.post_facebook as pf
        reel = {"permalink_url": "https://www.facebook.com/reel/860799243635804/",
                "message": "🌅 x\nhttps://bakersfieldbrief.com/briefs/2026-08-17/", "type": "video"}
        photo = {"permalink_url": "https://www.facebook.com/photos/12345",
                 "message": "🌅 x\nhttps://bakersfieldbrief.com/briefs/2026-08-17/", "type": "photo"}
        assert pf._is_daily_post(reel)
        assert pf._is_daily_post(photo)

    def test_overnight_must_be_live_on_site(self, monkeypatch):
        """NO GUESSING: a repo file is not publication — the site must render
        <section id="<date>"> before the post is allowed."""
        import scripts.post_facebook as pf

        class _Resp:
            status_code = 200
            text = '<section class="letter" id="2026-08-17">...'

        monkeypatch.setattr(pf.requests, "get", lambda *a, **k: _Resp())
        assert pf.overnight_live_on_site("2026-08-17") is True
        assert pf.overnight_live_on_site("2026-08-15") is False

    def test_stale_archive_headline_never_leads_post(self):
        """The caption lead must NEVER be the archive headline — it is the
        LLM's title for the daily brief and can be any top story, including
        national wire items that are grounded in the body yet wrong for a
        scanner reel ('Jeff Daniels channeled Reagan in The Brink of War'
        led the 2026-08-18 reel; 'Lanterns' did the same on 08-17). The lead
        must always come from the Kern Overnight scanner content."""
        import scripts.post_facebook as pf
        body = json.loads((pf.ROOT / "data" / "briefs" / "2026-08-18.json")
                          .read_text(encoding="utf-8"))["body"]
        # even a wire headline that IS in the body (as a top story) must not
        # lead — extract_top_story ignores the archive entirely
        top = pf.extract_top_story(body, "2026-08-18")
        assert "Jeff Daniels" not in top and "Brink of War" not in top
        assert len(top) > 30
        # and the lead IS the body's own Kern Overnight first sentence
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        lead_para = next(
            p for p in paras
            if not p.lower().startswith("good morning") and not p.startswith("##"))
        expected = re.split(r"(?<=[.!?])\s+",
                            re.sub(r"[*#_]", "", lead_para))[0].strip()
        assert top == expected

    def test_caption_never_truncates_mid_word(self):
        """compose_post must cut the detail to WHOLE sentences — a hard
        character slice once shipped '...Columbus Street esca' mid-word."""
        import scripts.post_facebook as pf
        body = json.loads((pf.ROOT / "data" / "briefs" / "2026-08-18.json")
                          .read_text(encoding="utf-8"))["body"]
        overnight = (pf.ROOT / "data" / "overnight_reports" / "2026-08-18.md") \
            .read_text(encoding="utf-8")
        msg = pf.compose_post("2026-08-18", body, overnight)
        # the detail block must end on a sentence boundary (period), never
        # mid-word: find the paragraph between the lead and the link
        m = re.search(r"\n\n(.+?)\n\n📰", msg, re.S)
        assert m, "detail block not found"
        detail = m.group(1).strip()
        assert len(detail) <= 900
        assert detail.endswith((".", "!", "?")), \
            f"detail truncated mid-word: ...{detail[-60:]}"
        # a long block is cut at a sentence end, not just anywhere
        long_text = "One. " * 500
        cut = pf._truncate_sentences(long_text, 900)
        assert cut.endswith(".") and not cut.endswith("..")
        assert len(cut) <= 900

    def test_headline_grounding_ratio(self):
        """Grounding is a content-word overlap check, not a substring check:
        a headline sharing >=60% of its significant words with the body passes,
        a nearly-empty headline never does."""
        import scripts.post_facebook as pf
        body = ("Good morning. The night's most serious call involved a group "
                "of juveniles with a firearm on Monterey Street, CHP says.")
        assert pf._headline_grounded_in_body(
            "Juveniles with firearm on Monterey Street", body)
        assert not pf._headline_grounded_in_body(
            "Unrelated headline about a film review", body)
        assert not pf._headline_grounded_in_body("", body)
        assert not pf._headline_grounded_in_body("the and for", body)





# ---------------------------------------------------------------- newsletter
def test_newsletter_idempotency_uses_pacific_date():
    """The send script must look for 'Daily Brief <Pacific-today>' — NOT the
    UTC date (GitHub runners are UTC; between 4pm PT and midnight PT the UTC
    date is tomorrow, which caused 3 emails on 2026-08-28)."""
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    import send_newsletter_ml as sn

    # The check must construct the name from common.today_pacific()
    import inspect
    src = inspect.getsource(sn._today_campaigns)
    # strip the docstring so its prose about the old bug doesn't trip the check
    code = src.split('"""', 2)[2] if '"""' in src else src
    assert "common.today_pacific()" in code, "idempotency check must use Pacific date"
    assert "datetime.now()" not in code, "UTC datetime.now() caused duplicate sends"

    # And the matching must be exact (same name the sender uses)
    assert sn._today_campaigns.__doc__ and "three emails on 2026-08-28" in sn._today_campaigns.__doc__


def test_newsletter_unsent_draft_is_not_already_sent(monkeypatch):
    """A draft left by a failed schedule call must not block the day's send (it used to count
    as "already sent", so CI and the watchdog both skipped the day silently)."""
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    import send_newsletter_ml as sn
    from build import common
    name = sn._campaign_name(common.today_pacific())
    calls = []

    def fake_req(method, path, payload=None, token=""):
        calls.append((method, path))
        if method == "GET":
            return {"data": rows} if "page=1" in path else {"data": []}
        return {}
    monkeypatch.setattr(sn, "_req", fake_req)

    rows = [{"id": "d1", "name": name, "status": "draft"}]
    assert sn._today_campaign_exists("t") is None
    assert ("DELETE", "/campaigns/d1") in calls

    calls.clear()
    rows = [{"id": "d2", "name": name, "status": "draft"}, {"id": "s1", "name": name, "status": "sent"}]
    assert sn._today_campaign_exists("t") == "s1"
    assert not any(m == "DELETE" for m, _ in calls)


def test_newsletter_campaign_name_format():
    """Campaign name must be 'Daily Brief YYYY-MM-DD' in Pacific time."""
    from build import common
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "scripts"))
    import send_newsletter_ml as sn
    d = common.today_pacific()
    name = f"Daily Brief {d.isoformat()}"
    assert name == sn._campaign_name(d), "sender and idempotency check must agree on the name"
