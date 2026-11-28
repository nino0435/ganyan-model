"""Sanal bayi (canlı kumarbaz defteri): günü kurma, yerleştirme, sonuçlandırma, rapor (sentetik DB)."""
import json
import sqlite3

import pytest

from ganyan import kumarbaz_personas as kp
from scripts import run_virtual_bayi as vb


def _main_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE races (race_id TEXT PRIMARY KEY, date TEXT, city TEXT, race_no INT,
                             post_time TEXT, status TEXT);
        CREATE TABLE runners (race_id TEXT, prog_no INT, horse_key TEXT, finish INT, ganyan REAL,
                               scratched INT DEFAULT 0);
        CREATE TABLE agf_snapshots (race_id TEXT, prog_no INT, captured_at TEXT, agf_pct REAL, ganyan_live REAL);
        CREATE TABLE bets (race_id TEXT, bet TEXT, combo TEXT, payout REAL);
        """
    )
    return conn


def _add_race(conn, rid, date, city, no, post_time, status, runners):
    """runners: [(prog_no, horse_key, finish, ganyan, scratched)]."""
    conn.execute("INSERT INTO races VALUES (?,?,?,?,?,?)", (rid, date, city, no, post_time, status))
    for pno, hk, finish, ganyan, scr in runners:
        conn.execute("INSERT INTO runners VALUES (?,?,?,?,?,?)", (rid, pno, hk, finish, ganyan, scr))
    conn.commit()


def _add_snap(conn, rid, pno, captured_at, agf_pct, ganyan_live):
    conn.execute("INSERT INTO agf_snapshots VALUES (?,?,?,?,?)", (rid, pno, captured_at, agf_pct, ganyan_live))
    conn.commit()


def _pred_db(rows):
    """rows: [(race_id, prog_no, model_version, p_win)]."""
    conn = sqlite3.connect(":memory:")
    from scripts.forward_v5 import PREDICTIONS_V5_SQL
    conn.execute(PREDICTIONS_V5_SQL)
    for r in rows:
        conn.execute(
            "INSERT INTO predictions_v5 (race_id, prog_no, model_version, created_at, minutes_to_post, "
            "p_win, agf_used, s_cov, g_cov) VALUES (?,?,?,?,?,?,?,?,?)",
            (r[0], r[1], r[2], "2026-01-01T10:00:00", 5.0, r[3], None, 1.0, 1.0),
        )
    conn.commit()
    return conn


def test_build_day_hasp_requires_full_prediction_coverage():
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 3.0, 0), (2, "h2", 2, 5.0, 0), (3, "h3", 3, 9.0, 0)])
    _add_snap(main, "2026-01-01_Adana_1", 1, "t1", 50.0, 2.8)
    _add_snap(main, "2026-01-01_Adana_1", 2, "t1", 30.0, 4.5)
    _add_snap(main, "2026-01-01_Adana_1", 3, "t1", 20.0, 8.0)
    pred = _pred_db([("2026-01-01_Adana_1", 1, "v10_hlb", 0.5), ("2026-01-01_Adana_1", 2, "v10_hlb", 0.3)])
    day = vb.build_day(main, pred, "2026-01-01", "v10_hlb", snap_which="max")
    assert len(day) == 1
    assert day[0].hasp is False   # horse 3'ün tahmini yok -> koşunun tamamı hasp=False


def test_degerci_picks_value_horse_and_temkinli_picks_favorite():
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 3.0, 0), (2, "h2", 2, 5.0, 0), (3, "h3", 3, 9.0, 0)])
    for pno, agf, gl in ((1, 60.0, 3.0), (2, 25.0, 5.0), (3, 15.0, 9.0)):
        _add_snap(main, "2026-01-01_Adana_1", pno, "t1", agf, gl)
    # at 3'ün modeli AGF payından çok daha iyimser (p=0.40 vs agf payı 0.15): Değerci kriterini sağlar
    pred = _pred_db([
        ("2026-01-01_Adana_1", 1, "v10_hlb", 0.45),
        ("2026-01-01_Adana_1", 2, "v10_hlb", 0.15),
        ("2026-01-01_Adana_1", 3, "v10_hlb", 0.40),
    ])
    day = vb.build_day(main, pred, "2026-01-01", "v10_hlb", snap_which="max")
    assert day[0].hasp is True

    temkinli = kp.p_temkinli(day)
    assert [p.combo for p in temkinli] == [(1,)]   # en düşük canlı oran (3.0) -> at 1

    degerci = kp.p_degerci(day)
    assert [p.combo for p in degerci] == [(3,)]   # p=0.40 >= 1.5 * agfp(0.15)=0.225 ve p>=0.08


def test_small_field_does_not_crash_ikili_sirali_uclu_selectors():
    """2 atlık bir koşuda üçlü/ikili/sıralı seçiciler çökmemeli (m=2,3 ama n=2)."""
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 3.0, 0), (2, "h2", 2, 5.0, 0)])
    _add_snap(main, "2026-01-01_Adana_1", 1, "t1", 60.0, 3.0)
    _add_snap(main, "2026-01-01_Adana_1", 2, "t1", 40.0, 5.0)
    pred = _pred_db([("2026-01-01_Adana_1", 1, "v10_hlb", 0.6), ("2026-01-01_Adana_1", 2, "v10_hlb", 0.4)])
    day = vb.build_day(main, pred, "2026-01-01", "v10_hlb", snap_which="max")
    assert kp.p_uclu(day) == []          # 3 at gerekir, saha 2 -> boş (çökmeden)
    assert len(kp.p_ikili(day)) == 1      # 2 at yeterli
    assert len(kp.p_sirali(day)) == 1


def test_place_is_idempotent_insert_or_ignore():
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 3.0, 0), (2, "h2", 2, 5.0, 0)])
    _add_snap(main, "2026-01-01_Adana_1", 1, "t1", 60.0, 3.0)
    _add_snap(main, "2026-01-01_Adana_1", 2, "t1", 40.0, 5.0)
    pred = _pred_db([("2026-01-01_Adana_1", 1, "v10_hlb", 0.6), ("2026-01-01_Adana_1", 2, "v10_hlb", 0.4)])
    day = vb.build_day(main, pred, "2026-01-01", "v10_hlb", snap_which="max")

    state = sqlite3.connect(":memory:")
    vb.ensure_schema(state)
    picks = kp.p_temkinli(day)
    n1 = vb._insert_picks(state, "A_kapanis_v10", picks, "2026-01-01T09:00:00", replace=False)
    n2 = vb._insert_picks(state, "A_kapanis_v10", picks, "2026-01-01T10:00:00", replace=False)
    assert n1 == 1
    assert n2 == 0   # ikinci çağrı aynı (track, persona, race, bet_type) üzerine yazmaz
    rows = state.execute("SELECT COUNT(*) FROM vb_bets").fetchone()[0]
    assert rows == 1


def test_settle_ganyan_win_loss_and_scratched_void():
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 4.0, 0), (2, "h2", 2, 6.0, 0), (3, "h3", None, None, 1)])
    state = sqlite3.connect(":memory:")
    vb.ensure_schema(state)
    for pno in (1, 2, 3):
        state.execute(
            "INSERT INTO vb_bets (track, persona, race_id, bet_type, combo, stake_tl, placed_at) "
            "VALUES ('A_kapanis_v10', ?, '2026-01-01_Adana_1', 'ganyan', ?, 50.0, 't0')",
            (f"persona{pno}", json.dumps([pno])),
        )
    state.commit()
    rows = state.execute("SELECT id, bet_type, race_id, combo, stake_tl FROM vb_bets WHERE settled = 0").fetchall()
    for bet_id, bet_type, race_id, combo_json, stake in rows:
        combo = json.loads(combo_json)
        res = vb._settle_one(main, bet_type, race_id, combo)
        if res == "void":
            state.execute("UPDATE vb_bets SET settled=1, win=NULL, payout_tl=NULL WHERE id=?", (bet_id,))
        else:
            win, odds_ret = res
            payout = stake * odds_ret if win else 0.0
            state.execute("UPDATE vb_bets SET settled=1, win=?, payout_tl=? WHERE id=?", (int(win), payout, bet_id))
    state.commit()

    got = {r[0]: (r[1], r[2]) for r in state.execute("SELECT persona, win, payout_tl FROM vb_bets")}
    assert got["persona1"] == (1, pytest.approx(200.0))   # kazandı: 50 * 4.0
    assert got["persona2"] == (0, pytest.approx(0.0))     # kaybetti
    assert got["persona3"] == (None, None)                # çekildi -> boş


def test_settle_plase_not_offered_is_void_and_offered_pays():
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 4.0, 0), (2, "h2", 2, 6.0, 0)])
    _add_race(main, "2026-01-01_Adana_2", "2026-01-01", "Adana", 2, "12:30", "result",
               [(1, "h3", 1, 4.0, 0), (2, "h4", 2, 6.0, 0)])
    main.execute("INSERT INTO bets VALUES ('2026-01-01_Adana_2', 'PLASE', '1', 1.8)")
    main.commit()

    assert vb._settle_one(main, "plase", "2026-01-01_Adana_1", [1]) == "void"
    win, odds_ret = vb._settle_one(main, "plase", "2026-01-01_Adana_2", [1])
    assert win is True
    assert odds_ret == pytest.approx(1.8)


def test_settle_cifte_matches_adjacent_leg():
    main = _main_db()
    _add_race(main, "2026-01-01_Adana_1", "2026-01-01", "Adana", 1, "12:00", "result",
               [(1, "h1", 1, 4.0, 0), (2, "h2", 2, 6.0, 0)])
    _add_race(main, "2026-01-01_Adana_2", "2026-01-01", "Adana", 2, "12:30", "result",
               [(1, "h3", 1, 4.0, 0), (2, "h4", 2, 6.0, 0)])
    main.execute("INSERT INTO bets VALUES ('2026-01-01_Adana_2', '1. ÇİFTE', '1/1', 15.0)")
    main.commit()

    win, odds_ret = vb._settle_one(main, "cifte", "2026-01-01_Adana_1|2026-01-01_Adana_2", [1, 1])
    assert win is True
    assert odds_ret == pytest.approx(15.0)

    win2, odds2 = vb._settle_one(main, "cifte", "2026-01-01_Adana_1|2026-01-01_Adana_2", [2, 1])
    assert win2 is False
    assert odds2 == 0.0


def test_report_computes_bankroll_from_settled_bets(tmp_path):
    state = sqlite3.connect(":memory:")
    vb.ensure_schema(state)
    state.executescript(
        """
        INSERT INTO vb_bets (track, persona, race_id, bet_type, combo, stake_tl, placed_at, settled, win, payout_tl)
        VALUES ('A_kapanis_v10', 'Değerci Deniz', 'r1', 'ganyan', '[1]', 50.0, 't0', 1, 1, 300.0);
        INSERT INTO vb_bets (track, persona, race_id, bet_type, combo, stake_tl, placed_at, settled, win, payout_tl)
        VALUES ('A_kapanis_v10', 'Değerci Deniz', 'r2', 'ganyan', '[1]', 50.0, 't1', 1, 0, 0.0);
        INSERT INTO vb_bets (track, persona, race_id, bet_type, combo, stake_tl, placed_at, settled)
        VALUES ('A_kapanis_v10', 'Değerci Deniz', 'r3', 'ganyan', '[1]', 50.0, 't2', 0);
        """
    )
    state.commit()
    led = vb._ledger(state, "A_kapanis_v10", "Değerci Deniz")
    assert led["bank"] == pytest.approx(kp.BANK0 + (300.0 - 50.0) + (0.0 - 50.0))
    assert led["n_settled"] == 2
    assert led["n_hit"] == 1
    assert led["n_pending"] == 1
