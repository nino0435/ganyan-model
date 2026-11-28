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
    assert res["altili"] == [
        {"date": "2026-10-27", "city": "Adana", "which": 1, "start_race": 1, "end_race": 6},
        {"date": "2026-10-27", "city": "Adana", "which": 2, "start_race": 3, "end_race": 8},
    ]

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


def test_program_altili_schedule_then_results_fill_legs(tmp_path):
    """Program kazıması altılı grubunu (start/end) önceden yazar; sonuç geldiğinde legs/payout dolar, start/end korunur."""
    conn = init_db(tmp_path / "prog2.db")
    res = parse_program_file(FIXTURE, date="2026-10-27", city="Adana")
    upsert_program(conn, res)

    rows = conn.execute(
        "SELECT which, start_race, end_race, legs, payout FROM altili WHERE date='2026-10-27' AND city='Adana' ORDER BY which"
    ).fetchall()
    assert rows == [(1, 1, 6, None, None), (2, 3, 8, None, None)]

    from ganyan.db import upsert_results
    upsert_results(conn, {
        "altili": [
            {"date": "2026-10-27", "city": "Adana", "which": 1, "start_race": 1, "end_race": 6,
             "legs": [1, 2, 3, 4, 5, 6], "payout": 150000.0},
        ],
        "races": [], "runners": [], "bets": [],
    })
    rows2 = conn.execute(
        "SELECT which, start_race, end_race, legs, payout FROM altili WHERE date='2026-10-27' AND city='Adana' ORDER BY which"
    ).fetchall()
    assert rows2[0][3] == "[1, 2, 3, 4, 5, 6]"
    assert rows2[0][4] == pytest.approx(150000.0)
    assert rows2[1] == (2, 3, 8, None, None)   # ikinci altılı hâlâ sonuçlanmamış

    # Program yeniden kazınırsa (aynı gün) dolmuş legs/payout bozulmamalı
    upsert_program(conn, res)
    rows3 = conn.execute(
        "SELECT which, legs, payout FROM altili WHERE date='2026-10-27' AND city='Adana' ORDER BY which"
    ).fetchall()
    assert rows3[0][1] == "[1, 2, 3, 4, 5, 6]"
    assert rows3[0][2] == pytest.approx(150000.0)
    conn.close()


def test_update_daily_idempotent(tmp_path):
    import shutil
    from scripts.update_daily import update_daily

    db_path = tmp_path / "daily.db"
    res_dir = tmp_path / "results"
    prog_dir = tmp_path / "program"
    res_dir.mkdir()
    prog_dir.mkdir()

    res_fix = os.path.join(os.path.dirname(__file__), "fixtures", "results_2026-10-24_Ankara.csv")
    shutil.copy(res_fix, res_dir / "2026-10-24_Ankara.csv")
    shutil.copy(FIXTURE, prog_dir / "2026-10-25_Adana.csv")

    # Populate via upsert through update_daily helper logic (offline)
    conn = init_db(db_path)
    from ganyan.db import upsert_results
    from ganyan.parse_results import parse_results_file

    upsert_results(conn, parse_results_file(res_dir / "2026-10-24_Ankara.csv", date="2026-10-24", city="Ankara"))
    upsert_program(conn, parse_program_file(prog_dir / "2026-10-25_Adana.csv", date="2026-10-25", city="Adana"))
    snap1 = (
        conn.execute("SELECT * FROM races ORDER BY race_id").fetchall(),
        conn.execute("SELECT * FROM runners ORDER BY race_id, horse_key").fetchall(),
        conn.execute("SELECT * FROM bets ORDER BY race_id, bet, combo").fetchall(),
        conn.execute("SELECT * FROM altili ORDER BY date, city, which").fetchall(),
    )
    # Run second time
    upsert_results(conn, parse_results_file(res_dir / "2026-10-24_Ankara.csv", date="2026-10-24", city="Ankara"))
    upsert_program(conn, parse_program_file(prog_dir / "2026-10-25_Adana.csv", date="2026-10-25", city="Adana"))
    snap2 = (
        conn.execute("SELECT * FROM races ORDER BY race_id").fetchall(),
        conn.execute("SELECT * FROM runners ORDER BY race_id, horse_key").fetchall(),
        conn.execute("SELECT * FROM bets ORDER BY race_id, bet, combo").fetchall(),
        conn.execute("SELECT * FROM altili ORDER BY date, city, which").fetchall(),
    )
    assert snap1 == snap2
    conn.close()


def test_parse_live_program_html():
    from scripts.snapshot_agf import parse_live_program_html

    sample_html = """
    <div>1. Koşu : 14.30</div>
    <table>
      <tr>
        <td class="gunluk-GunlukYarisProgrami-SiraId">1</td>
        <td class="gunluk-GunlukYarisProgrami-AtAdi">ARES GOLD (8)</td>
        <td class="gunluk-GunlukYarisProgrami-AGFORAN">%15(3)</td>
        <td class="gunluk-GunlukYarisProgrami-Gny">31,90</td>
      </tr>
    </table>
    """
    snaps = parse_live_program_html(sample_html, "2026-10-27", "Adana")
    assert len(snaps) == 1
    assert snaps[0]["race_id"] == "2026-10-27_Adana_1"
    assert snaps[0]["prog_no"] == 1
    assert snaps[0]["agf_pct"] == 15.0
    assert snaps[0]["agf_rank"] == 3
    assert snaps[0]["ganyan_live"] == pytest.approx(31.90)


def test_parse_program_and_html_ignore_all_zero_placeholder_agf(tmp_path):
    """TJK açılışta tüm atlara '%0(1)..%0(N)' bastığında AGF henüz yok (None) sayılmalı."""
    from scripts.snapshot_agf import parse_live_program_html

    csv_file = tmp_path / "prog.csv"
    csv_file.write_text(
        "İstanbul;(91. Yarış Günü);11/11/2026\n"
        "1. Kosu : 14.00;Handikap 14; 3 Yaşlı Araplar; kg; 1500m; Sentetik\n"
        "1;ALAZVUR;3y k e;BABA1;ANNE1;58;M.KAYA;SAH1;ANT1;1;%0(1);49;K1;10;17;\n"
        "2;GÜMÜŞ;3y k e;BABA2;ANNE2;58;A.ASLAN;SAH2;ANT2;2;%0(2);47;K2;14;17;\n",
        encoding="utf-8",
    )
    parsed = parse_program_file(csv_file, date="2026-11-11", city="İstanbul")
    assert len(parsed["runners"]) == 2
    assert all(r["agf_pct"] is None and r["agf_rank"] is None for r in parsed["runners"])

    zero_html = """
    <div>1. Koşu : 14.00</div>
    <table>
      <tr>
        <td class="gunluk-GunlukYarisProgrami-SiraId">1</td>
        <td class="gunluk-GunlukYarisProgrami-AGFORAN">%0(1)</td>
      </tr>
      <tr>
        <td class="gunluk-GunlukYarisProgrami-SiraId">2</td>
        <td class="gunluk-GunlukYarisProgrami-AGFORAN">%0(2)</td>
      </tr>
    </table>
    """
    assert parse_live_program_html(zero_html, "2026-11-11", "İstanbul") == []



