"""Tests for ganyan.parse_program."""
import os
import pytest
from ganyan.db import init_db, upsert_program
from ganyan.parse_program import parse_program_file

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "program_2026-10-27_Adana.csv")


def test_parse_program_adana_fixture():
    res = parse_program_file(FIXTURE, date="2026-10-27", city="Adana")
    assert res["yg_no"] == 21
    assert len(res["races"]) == 8

    r1 = res["races"][0]
    assert r1["race_no"] == 1
    assert r1["post_time"] == "14:30"
    assert r1["cls"] == "Handikap 15 /H2"
    assert r1["breed"] == "Ingiliz"
    assert r1["distance"] == 1200
    assert r1["surface"] == "Sentetik"

    r1_runners = [r for r in res["runners"] if r["race_id"] == "2026-10-27_Adana_1"]
    p1 = next(r for r in r1_runners if r["prog_no"] == 1)
    assert p1["name"] == "ETIQUETTE"
    assert p1["weight"] == pytest.approx(58.5)
    assert p1["jockey"] == "Ö.YILDIRIM"
    assert p1["gate"] == 1
    assert p1["hp"] == pytest.approx(56.0)
    assert p1["agf_pct"] is None
    assert p1["son6"] == [("K", 2), ("K", 1), ("Ç", 9), ("K", 6), ("K", 1), ("K", 6)]
    assert p1["kgs"] == 21
    assert p1["s20"] == 19
    assert p1["best_time_s"] is None

    p2 = next(r for r in r1_runners if r["prog_no"] == 2)
    assert p2["name"] == "ROSE WARRIOR"
    assert len(p2["son6"]) == 5
    assert p2["son6"] == [("Ç", 1), ("Ç", 6), ("Ç", 2), ("S", 1), ("K", 4)]

    p3 = next(r for r in r1_runners if r["prog_no"] == 3)
    assert p3["name"] == "KING OF LINGO"
    assert p3["gate"] == 8
    assert p3["hp"] == pytest.approx(53.0)
    assert p3["kgs"] == 34
    assert p3["s20"] == 18

    p4 = next(r for r in r1_runners if r["prog_no"] == 4)
    assert p4["best_time_s"] == pytest.approx(73.06)


def test_upsert_program_db(tmp_path):
    conn = init_db(tmp_path / "prog.db")
    res = parse_program_file(FIXTURE, date="2026-10-27", city="Adana")
    upsert_program(conn, res)
    upsert_program(conn, res)
    assert conn.execute("SELECT COUNT(*) FROM races").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM runners").fetchone()[0] == len(res["runners"])
    conn.close()
