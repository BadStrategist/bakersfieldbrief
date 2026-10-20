"""kern_overnight/lead_order.py: the writer's lead is the most serious call, the
same ranking as the reel and the night card (owner rule 2026-10-20)."""
import json

from kern_overnight import lead_order


def test_gunfire_leads_and_a_fire_never_outranks_a_weapon(tmp_path, capsys):
    rows = [
        {"type": "vehicle fire", "time": "20:52", "notability": 4, "summary": "Semi burned on I-5."},
        {"type": "weapons", "time": "21:07", "notability": 2, "summary": "Two people with machetes."},
        {"type": "shots fired", "time": "22:10", "notability": 2, "summary": "Two loud bangs."},
        {"type": "medical aid", "time": "19:30", "notability": 3, "summary": "Medical aid."},
    ]
    (tmp_path / "2026-10-20.json").write_text(json.dumps(rows), encoding="utf-8")
    assert lead_order.main(["2026-10-20", "--incidents-dir", str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["time"] for r in out] == ["22:10", "21:07", "20:52", "19:30"]
    assert [r["severity"] for r in out] == [0, 1, 4, 5]


def test_a_fire_leads_a_night_with_no_one_in_danger(tmp_path, capsys):
    rows = [{"type": "medical aid", "time": "19:30", "notability": 3, "summary": "x"},
            {"type": "structure fire", "time": "02:00", "notability": 3, "summary": "House fire."}]
    (tmp_path / "d.json").write_text(json.dumps(rows), encoding="utf-8")
    lead_order.main(["d", "--incidents-dir", str(tmp_path), "--json"])
    assert json.loads(capsys.readouterr().out)[0]["type"] == "structure fire"


def test_a_missing_night_is_an_error_not_an_empty_list(tmp_path):
    assert lead_order.main(["2099-01-01", "--incidents-dir", str(tmp_path)]) == 1
