#!/usr/bin/env python3
"""Guard: Whisper's 'Weibel'/'Wibel' mis-hearing must land on the gazetteer
spelling 'Wible Road'.

Pins the 2026-10-05 defect: the published overnight report told readers the
pursuit ran on "Weibel Avenue", a street that does not exist. The gazetteer
holds exactly one match, 'Wible Road'. Evidence for the mapping: 'weibel' 25x
and 'wibel' 2x across transcripts/, plus 'Wible Road' in streets.txt line 6103.

'Weibel' is also a local surname ("Megan Weibel", transcripts/2026-08-14.jsonl),
so the fold must only fire in a street context. Both halves are tested: the
street cases fold, the name cases do not.
"""
from kern_overnight import streetcheck as SC


def _gazetteer():
    streets = SC.load_streets()
    return streets, {SC.normalize(s): s for s in streets}


def test_gazetteer_holds_the_real_spelling():
    streets, _ = _gazetteer()
    assert "Wible Road" in streets
    assert [s for s in streets if s.lower().startswith(("weibel", "wibel"))] == []


def test_check_name_folds_mishearings_into_a_match():
    streets, norm = _gazetteer()
    for probe in ("Weibel Avenue", "Weibel", "Wibel Rd"):
        assert SC.check_name(probe, streets, norm) == ("MATCH", "Wible Road"), probe


def test_fix_text_folds_street_mentions():
    # after a locational word
    assert SC.fix_text("approaching Weibel.") == "approaching Wible Road."
    assert SC.fix_text("suspicious person on Weibel, it's closed") == \
        "suspicious person on Wible Road, it's closed"
    # before a type word, including a wrong one ('Avenue' for 'Road')
    assert SC.fix_text("1914 Weibel Road") == "1914 Wible Road"
    assert SC.fix_text("Weibel Avenue from Pacheco") == "Wible Road from Pacheco"
    # intersection
    assert SC.fix_text("Weibel and Bell Terrace") == "Wible Road and Bell Terrace"


def test_fix_text_leaves_the_surname_alone():
    # never rewrite a person into a street
    assert SC.fix_text("Pree Valley 2, Megan Weibel") == "Pree Valley 2, Megan Weibel"
    assert SC.fix_text("Megan Weibel, Information from Control 3") == \
        "Megan Weibel, Information from Control 3"
    # and never touch an unrelated street
    assert SC.fix_text("crash on Mount Vernon Avenue") == "crash on Mount Vernon Avenue"


def test_vocab_primes_the_correct_spelling():
    """Whisper can only hear a street it was primed with."""
    vocab = [v.strip() for v in
             (SC.STREETS_FILE.parent / "vocab.txt").read_text(encoding="utf-8").splitlines()]
    assert "Wible Road" in vocab
    assert [v for v in vocab if v.lower().startswith(("weibel", "wibel"))] == []