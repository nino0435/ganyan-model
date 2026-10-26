"""Tests for ganyan.parse_results and ganyan.db."""
import json
import os
import pytest
from ganyan.db import init_db, upsert_results
from ganyan.parse_results import EQUIP_CODES, clean_horse_name, parse_results_file

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "results_2026-10-24_Ankara.csv")


def test_equip_codes_constant():
    assert EQUIP_CODES == frozenset({"DB", "GKR", "K", "KG", "SK", "SKG"})
    assert clean_horse_name("IMPERIAL GLOIRE DB SKG SK") == "IMPERIAL GLOIRE"
    assert clean_horse_name("ELYSIUM KG K (Koşmaz)") == "ELYSIUM"


def test_parse_results_ankara_fixture():
    res = parse_results_file(FIXTURE, date="2026-10-24", city="Ankara")
    assert res["yg_no"] == 77
    assert len(res["races"]) == 10

    r1 = res["races"][0]
    assert r1["race_no"] == 1
    assert r1["post_time"] == "13:00"
    assert r1["cls"] == "Maiden/Dişi"
    assert r1["breed"] == "Ingiliz"
    assert r1["distance"] == 1400
    assert r1["surface"] == "Çim"
    assert r1["status"] == "result"

    r1_runners = [r for r in res["runners"] if r["race_id"] == "2026-10-24_Ankara_1"]
    assert len(r1_runners) == 10

    w1 = next(r for r in r1_runners if r["name"] == "IMPERIAL GLOIRE")
    assert w1["finish"] == 1
    assert w1["agf_close"] == pytest.approx(2.99)
    assert w1["agf_close_rank"] == 6
    assert w1["ganyan"] == pytest.approx(17.0)
    assert w1["time_s"] == pytest.approx(86.56)
    assert w1["gate"] == 5

    qou = next(r for r in r1_runners if r["name"] == "QUEEN OF UNION")
    assert qou["weight"] == pytest.approx(57.7)
    assert qou["gate"] == 10

    # 4th race named race post_time
    r4 = res["races"][3]
    assert r4["post_time"] == "14:30"

    # 3rd race ELYSIUM scratched=1
    r3_runners = [r for r in res["runners"] if r["race_id"] == "2026-10-24_Ankara_3"]
    elysium = next(r for r in r3_runners if r["name"] == "ELYSIUM")
    assert elysium["scratched"] == 1

    # 2nd race GANYAN = 8 (eküri line)
    r2_ganyan = [b for b in res["bets"] if b["race_id"] == "2026-10-24_Ankara_2" and b["bet"] == "GANYAN"]
    assert len(r2_ganyan) == 1
    assert r2_ganyan[0]["combo"] == "8"
    assert r2_ganyan[0]["payout"] == pytest.approx(2.90)

    # altili checks
    assert len(res["altili"]) == 2
    a1 = next(a for a in res["altili"] if a["which"] == 1)
    assert a1["start_race"] == 1
    assert a1["end_race"] == 6
    assert a1["legs"] == [[5], [8], [6], [2], [10], [7]]
    assert a1["payout"] == pytest.approx(292238.81)

    a2 = next(a for a in res["altili"] if a["which"] == 2)
    assert a2["start_race"] == 5
    assert a2["end_race"] == 10
    assert a2["legs"] == [[10], [7], [4], [5], [1], [5]]
    assert a2["payout"] == pytest.approx(141503.56)


def test_db_idempotent_upsert(tmp_path):
    db_file = tmp_path / "test.db"
    conn = init_db(db_file)
    res = parse_results_file(FIXTURE, date="2026-10-24", city="Ankara")
    upsert_results(conn, res)
    upsert_results(conn, res)  # second time should be idempotent

    races_n = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    runners_n = conn.execute("SELECT COUNT(*) FROM runners").fetchone()[0]
    altili_n = conn.execute("SELECT COUNT(*) FROM altili").fetchone()[0]
    assert races_n == 10
    assert runners_n == len(res["runners"])
    assert altili_n == 2
    conn.close()
