#!/usr/bin/env python3
"""Guard: mis-heard street names must land on the OFFICIAL spelling, and the
gazetteer itself must never invent a street.

Pins two live defects:
  2026-10-05: the published report told readers a pursuit ran on "Weibel
  Avenue", a street that does not exist. The gazetteer holds exactly one
  match, 'Wible Road'. Evidence: 'weibel' 25x and 'wibel' 2x across
  transcripts/.
  2026-10-06: the report said "Ledgeview Lane" (correct, and what the audio
  says) and a 'gazetteer wins' pass rewrote it to the bogus 'Ledgewiew Lane'
  because streets.txt held that typo. Kern County Centerline Roads and the
  City of Bakersfield Streets layer each carry exactly one 'LEDGEVIEW LN' and
  zero 'LEDGEWIEW'.

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
    assert "Ledgeview Lane" in vocab
    assert [v for v in vocab if v.lower().startswith(("weibel", "wibel"))] == []


def test_gazetteer_holds_ledgeview_not_ledgewiew():
    """The 2026-10-06 defect: streets.txt held the bogus 'Ledgewiew Lane' and a
    'gazetteer wins' pass rewrote a correct report to it. Both official layers
    (Kern County Centerline Roads, City of Bakersfield Streets) carry exactly
    one 'LEDGEVIEW LN' and zero 'LEDGEWIEW'."""
    streets, _ = _gazetteer()
    assert "Ledgeview Lane" in streets
    assert [s for s in streets if "ledgew" in s.lower()] == []


def test_ledgewiew_folds_to_the_official_spelling():
    streets, norm = _gazetteer()
    assert SC.fix_text("woman locked in a car on Ledgewiew Lane") == \
        "woman locked in a car on Ledgeview Lane"
    assert SC.check_name("Ledgewiew Lane", streets, norm) == ("MATCH", "Ledgeview Lane")
