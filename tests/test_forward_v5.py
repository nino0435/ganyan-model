"""Offline unit and synthetic end-to-end tests for scripts/forward_v5.py and scripts/daily_v5_update.py."""
import datetime
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan import model_v6, model_v7
from ganyan.db import init_db, upsert_program, upsert_results
from scripts import daily_v5_update, forward_v5, forward_v5_report

IST_TZ = ZoneInfo("Europe/Istanbul")


def _load_populate_helper():
    mod_path = Path(__file__).with_name("test_model_v5.py")
    spec = importlib.util.spec_from_file_location("_test_model_v5_helper", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._populate_synthetic_v5_sqlite


_populate_synthetic_v5_sqlite = _load_populate_helper()


def test_due_races_selection_rules():
    date_str = "2026-11-15"
    now = datetime.datetime(2026, 11, 15, 13, 55, 0, tzinfo=IST_TZ)
    races = [
        # (race_id, city, post_time, status)
        (f"{date_str}_Ankara_1", "Ankara", "14:00", "scheduled"),  # mtp=5.0 -> due
        (f"{date_str}_İzmir_1", "İzmir", "14:03", None),  # mtp=8.0 boundary -> due
        (f"{date_str}_Ankara_2", "Ankara", "14:04", "scheduled"),  # mtp=9.0 -> outside window
        (f"{date_str}_Ankara_3", "Ankara", "13:55", "scheduled"),  # mtp=0.0 -> already at post
        (f"{date_str}_Ankara_4", "Ankara", "13:50", "scheduled"),  # mtp=-5.0 -> past
        (f"{date_str}_Bursa_1", "Bursa", "13:59", "scheduled"),  # mtp=4.0, already predicted -> excluded
        (f"{date_str}_Bursa_2", "Bursa", "13:58", "cancelled"),  # cancelled -> excluded
        (f"{date_str}_Bursa_3", "Bursa", "13:58", "result"),  # result -> excluded
        (f"{date_str}_Bursa_4", "Bursa", None, "scheduled"),  # missing post_time -> excluded
        {
            "race_id": "2026-11-16_Ankara_1",
            "date": "2026-11-16",
            "city": "Ankara",
            "post_time": "14:00",
            "status": "scheduled",
        },  # other date -> excluded
    ]

    due = forward_v5.due_races(
        races,
        now=now,
        date_str=date_str,
        due_max_min=8.0,
        predicted_ids={f"{date_str}_Bursa_1"},
    )
    assert [d["race_id"] for d in due] == [
        f"{date_str}_Ankara_1",
        f"{date_str}_İzmir_1",
    ]
    assert due[0]["mtp"] == pytest.approx(5.0)
    assert due[1]["mtp"] == pytest.approx(8.0)

    # Empty when all due races are already predicted
    assert (
        forward_v5.due_races(
            races,
            now=now,
            date_str=date_str,
            due_max_min=8.0,
            predicted_ids={f"{date_str}_Ankara_1", f"{date_str}_İzmir_1", f"{date_str}_Bursa_1"},
        )
        == []
    )


def test_predictions_v5_schema_and_insert_or_ignore(tmp_path):
    out_file = tmp_path / "sub" / "forward_v5.db"
    conn = forward_v5.init_out_db(out_file)
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert journal.lower() == "wal"
        assert int(busy_ms) == 30000

        info = conn.execute("PRAGMA table_info(predictions_v5)").fetchall()
        cols = [(r[1], r[2].upper(), r[5]) for r in info]
        assert cols == [
            ("race_id", "TEXT", 1),
            ("prog_no", "INTEGER", 2),
            ("model_version", "TEXT", 3),
            ("created_at", "TEXT", 0),
            ("minutes_to_post", "REAL", 0),
            ("p_win", "REAL", 0),
            ("agf_used", "REAL", 0),
            ("s_cov", "REAL", 0),
            ("g_cov", "REAL", 0),
        ]

        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO predictions_v5 (
                race_id, prog_no, model_version, created_at, minutes_to_post,
                p_win, agf_used, s_cov, g_cov
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-11-15_Ankara_1", 1, "v5_sgr_all", "2026-11-15T13:55:00+03:00", 5.0, 0.31, 28.5, 1.0, 0.83),
        )
        assert cur.rowcount == 1

        # Second write for identical (race_id, prog_no, model_version) must be ignored
        cur.execute(
            """
            INSERT OR IGNORE INTO predictions_v5 (
                race_id, prog_no, model_version, created_at, minutes_to_post,
                p_win, agf_used, s_cov, g_cov
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-11-15_Ankara_1", 1, "v5_sgr_all", "2026-11-15T13:57:00+03:00", 3.0, 0.99, 50.0, 0.0, 0.0),
        )
        assert cur.rowcount == 0
        conn.commit()

        rows = conn.execute(
            "SELECT created_at, minutes_to_post, p_win, agf_used, s_cov, g_cov FROM predictions_v5"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "2026-11-15T13:55:00+03:00"
        assert rows[0][1] == pytest.approx(5.0)
        assert rows[0][2] == pytest.approx(0.31)
        assert rows[0][3] == pytest.approx(28.5)
        assert rows[0][4] == pytest.approx(1.0)
        assert rows[0][5] == pytest.approx(0.83)
    finally:
        conn.close()


def _make_prog_runners(race_id, horse_indices, agf_list=None):
    out = []
    for pos, idx in enumerate(horse_indices):
        hk = f"SIRE_{idx}|DAM_{idx}|2018"
        agf_val = agf_list[pos] if agf_list is not None else None
        out.append(
            {
                "race_id": race_id,
                "prog_no": pos + 1,
                "horse_key": hk,
                "name": f"AT {idx}",
                "name_raw": f"AT {idx}",
                "age": 4,
                "sex": "d" if idx % 2 == 0 else "e",
                "sire": f"SIRE_{idx}",
                "dam": f"DAM_{idx}",
                "weight": 56.0 + pos * 0.5,
                "jockey": f"J_{idx % 4}",
                "owner": f"O_{idx % 3}",
                "trainer": f"T_{idx % 3}",
                "gate": pos + 1,
                "hp": 50.0 + idx,
                "son6_raw": "Ç1Ç2Ç3",
                "kgs": 15,
                "s20": 16,
                "best_time_s": 85.5,
                "agf_pct": agf_val,
                "agf_rank": (pos + 1) if agf_val is not None else None,
            }
        )
    return out


def test_run_once_end_to_end_synthetic_db(tmp_path, monkeypatch):
    main_db = tmp_path / "ganyan.db"
    out_db = tmp_path / "forward_v5.db"
    _populate_synthetic_v5_sqlite(main_db)

    target_date = "2026-04-20"
    rid_due = f"{target_date}_Ankara_1"
    rid_later = f"{target_date}_Ankara_2"
    agf_snap_vals = [30.0, 22.0, 18.0, 14.0, 10.0, 6.0]
    agf_prog_vals = [28.0, 24.0, 18.0, 14.0, 10.0, 6.0]

    conn = init_db(main_db)
    try:
        upsert_program(
            conn,
            {
                "races": [
                    {
                        "race_id": rid_due,
                        "date": target_date,
                        "city": "Ankara",
                        "race_no": 1,
                        "post_time": "14:00",
                        "yg_no": 1,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "scheduled",
                    },
                    {
                        "race_id": rid_later,
                        "date": target_date,
                        "city": "Ankara",
                        "race_no": 2,
                        "post_time": "14:30",
                        "yg_no": 2,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "scheduled",
                    },
                ],
                "runners": (
                    _make_prog_runners(rid_due, range(0, 6), agf_list=None)
                    + _make_prog_runners(rid_later, range(6, 12), agf_list=agf_prog_vals)
                ),
            },
        )
        # Overlay fresh AGF snapshots for rid_due (including an earlier 0.0 placeholder that must be ignored)
        for pno in range(1, 7):
            conn.execute(
                "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
                (rid_due, pno, f"{target_date}T09:00:00+03:00", 0.0, pno),
            )
        for pno, pct in enumerate(agf_snap_vals, start=1):
            conn.execute(
                "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
                (rid_due, pno, f"{target_date}T13:54:00+03:00", pct, pno),
            )
        conn.commit()
    finally:
        conn.close()

    cache_dir = tmp_path / "forward_models"
    snap_calls = []
    monkeypatch.setattr(
        forward_v5,
        "snapshot_agf",
        lambda ds, db_path=None, prog_dir=None, cities=None: snap_calls.append((ds, list(cities or []))) or 0,
    )

    # 1) At 13:55 (mtp=5.0 for race 1, mtp=35.0 for race 2): race 1 is predicted for v5_sgr_all, v6_e5, and v7_tcjp
    written_1 = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        due_max_min=8.0,
        cache_dir=str(cache_dir),
    )
    assert written_1 == 18
    assert snap_calls == [(target_date, ["Ankara"])]
    assert (cache_dir / f"{target_date}_v6_e5.pkl").exists()
    assert (cache_dir / f"{target_date}_v7_tcjp.pkl").exists()

    # Main DB predictions table must remain completely untouched
    mconn = sqlite3.connect(str(main_db))
    try:
        main_pred_cnt = mconn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        assert main_pred_cnt == 0
    finally:
        mconn.close()

    oconn = sqlite3.connect(str(out_db))
    try:
        rows = oconn.execute(
            """
            SELECT race_id, prog_no, model_version, created_at, minutes_to_post,
                   p_win, agf_used, s_cov, g_cov
            FROM predictions_v5
            ORDER BY model_version, prog_no
            """
        ).fetchall()
        assert len(rows) == 18
        assert {r[2] for r in rows} == {"v5_sgr_all", "v6_e5", "v7_tcjp"}
        for mv in ("v5_sgr_all", "v6_e5", "v7_tcjp"):
            mv_rows = [r for r in rows if r[2] == mv]
            assert len(mv_rows) == 6
            assert [r[0] for r in mv_rows] == [rid_due] * 6
            assert [r[1] for r in mv_rows] == [1, 2, 3, 4, 5, 6]
            assert {r[3] for r in mv_rows} == {"2026-04-20T13:55:00+03:00"}
            assert all(r[4] == pytest.approx(5.0) for r in mv_rows)
            p_vals = [r[5] for r in mv_rows]
            assert all(0.0 < p < 1.0 for p in p_vals)
            assert sum(p_vals) == pytest.approx(1.0)
            assert [r[6] for r in mv_rows] == pytest.approx(agf_snap_vals)
            # All 6 horses ran on 2026-04-15 (Yenibeygir hiz) and had 2026-04-05 Liderform workouts
            assert all(r[7] == pytest.approx(1.0) for r in mv_rows)
            assert all(r[8] == pytest.approx(1.0) for r in mv_rows)
    finally:
        oconn.close()

    # 2) Re-running 2 minutes later (13:57, mtp=3.0) must skip race 1 without network or duplicate rows
    written_2 = forward_v5.run_once(
        now="2026-04-20T13:57:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        due_max_min=8.0,
        cache_dir=str(cache_dir),
    )
    assert written_2 == 0
    assert len(snap_calls) == 1

    # 3) At 14:24 (mtp=6.0 for race 2): race 2 enters due window and gets predicted for all 3 models
    written_3 = forward_v5.run_once(
        now="2026-04-20T14:24:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        due_max_min=8.0,
        cache_dir=str(cache_dir),
    )
    assert written_3 == 18
    assert len(snap_calls) == 2

    oconn = sqlite3.connect(str(out_db))
    try:
        total_cnt = oconn.execute("SELECT COUNT(*) FROM predictions_v5").fetchone()[0]
        assert total_cnt == 36
    finally:
        oconn.close()


def test_daily_v5_update_fail_soft_and_scheduled_liderform_targets(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "u.db"
    conn = init_db(db_path)
    try:
        races = [
            ("2026-11-14_Ankara_1", "2026-11-14", "Ankara", 1, "result"),
            ("2026-11-15_Ankara_1", "2026-11-15", "Ankara", 1, "scheduled"),
            ("2026-11-15_Ankara_2", "2026-11-15", "Ankara", 2, "cancelled"),
        ]
        for rid, d_s, city, r_no, st in races:
            conn.execute(
                "INSERT INTO races (race_id, date, city, race_no, status) VALUES (?,?,?,?,?)",
                (rid, d_s, city, r_no, st),
            )
        conn.commit()

        targets = daily_v5_update._load_liderform_targets_incl_program(conn, "2026-11-14", "2026-11-15")
        assert [t[0] for t in targets] == ["2026-11-15_Ankara_1", "2026-11-14_Ankara_1"]
    finally:
        conn.close()

    upd_dates = []
    monkeypatch.setattr(
        daily_v5_update,
        "update_daily",
        lambda ds, **kw: upd_dates.append(ds),
    )
    monkeypatch.setattr(
        daily_v5_update.backfill_yenibeygir,
        "run_backfill",
        lambda **kw: (2, {}),
    )

    lf_seen_targets = []

    def _fake_lf_backfill(c, raw_dir, s_d, e_d, delay=2.0, out=None, **kw):
        lf_seen_targets.extend(daily_v5_update.backfill_liderform.load_target_races(c, s_d, e_d))
        return 2

    monkeypatch.setattr(daily_v5_update.backfill_liderform, "run_backfill", _fake_lf_backfill)

    rc = daily_v5_update.main(["--date", "2026-11-15", "--db", str(db_path), "--delay", "0"])
    assert rc == 0
    assert upd_dates == ["2026-11-14", "2026-11-15"]
    assert [t[0] for t in lf_seen_targets] == ["2026-11-15_Ankara_1", "2026-11-14_Ankara_1"]

    out_txt = capsys.readouterr().out
    assert "tjk güncellendi" in out_txt
    assert "UYARI: yenibeygir güncellenemedi" in out_txt
    assert "UYARI: liderform güncellenemedi" in out_txt


def _setup_three_due_races_db(main_db, target_date="2026-04-20"):
    _populate_synthetic_v5_sqlite(main_db)
    agf_vals = [30.0, 22.0, 18.0, 14.0, 10.0, 6.0]
    conn = init_db(main_db)
    try:
        upsert_program(
            conn,
            {
                "races": [
                    {
                        "race_id": f"{target_date}_Ankara_1",
                        "date": target_date,
                        "city": "Ankara",
                        "race_no": 1,
                        "post_time": "14:00",
                        "yg_no": 1,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "scheduled",
                    },
                    {
                        "race_id": f"{target_date}_Ankara_2",
                        "date": target_date,
                        "city": "Ankara",
                        "race_no": 2,
                        "post_time": "14:30",
                        "yg_no": 2,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "scheduled",
                    },
                    {
                        "race_id": f"{target_date}_Ankara_3",
                        "date": target_date,
                        "city": "Ankara",
                        "race_no": 3,
                        "post_time": "15:00",
                        "yg_no": 3,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "scheduled",
                    },
                ],
                "runners": (
                    _make_prog_runners(f"{target_date}_Ankara_1", range(0, 6), agf_list=agf_vals)
                    + _make_prog_runners(f"{target_date}_Ankara_2", range(6, 12), agf_list=agf_vals)
                    + _make_prog_runners(f"{target_date}_Ankara_3", range(0, 6), agf_list=agf_vals)
                ),
            },
        )
        conn.commit()
    finally:
        conn.close()


def test_run_once_partial_recovery_and_error_isolation(tmp_path, monkeypatch, capsys):
    target_date = "2026-04-20"
    main_db = tmp_path / "ganyan_iso.db"
    _setup_three_due_races_db(main_db, target_date=target_date)
    cache_dir = tmp_path / "cache_iso"

    # (a) Partial recovery: if only v5_sgr_all was written earlier, next pass writes ONLY v6_e5 + v7_tcjp
    out_partial = tmp_path / "partial.db"
    w_v5_only = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_partial),
        do_snapshot=False,
        models="v5_sgr_all",
        cache_dir=str(cache_dir),
    )
    assert w_v5_only == 6

    w_backfill_rest = forward_v5.run_once(
        now="2026-04-20T13:56:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_partial),
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w_backfill_rest == 12

    pconn = sqlite3.connect(str(out_partial))
    try:
        counts = dict(
            pconn.execute(
                "SELECT model_version, COUNT(*) FROM predictions_v5 GROUP BY model_version"
            ).fetchall()
        )
        assert counts == {"v5_sgr_all": 6, "v6_e5": 6, "v7_tcjp": 6}
    finally:
        pconn.close()

    # (b) V6 error must not block v5_sgr_all or v7_tcjp
    out_v6_err = tmp_path / "v6_err.db"
    orig_v6_live = forward_v5.fit_predict_v6_live
    monkeypatch.setattr(
        forward_v5,
        "fit_predict_v6_live",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("sentetik v6 hatası")),
    )
    _ = capsys.readouterr()
    w_when_v6_fails = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_v6_err),
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w_when_v6_fails == 12
    assert "HATA (v6_e5)" in capsys.readouterr().out
    monkeypatch.setattr(forward_v5, "fit_predict_v6_live", orig_v6_live)

    # (c) v5 error must not block v6_e5 or v7_tcjp
    out_v5_err = tmp_path / "v5_err.db"
    orig_v5_fit = forward_v5.fit_predict_df
    monkeypatch.setattr(
        forward_v5,
        "fit_predict_df",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("sentetik v5 hatası")),
    )
    _ = capsys.readouterr()
    w_when_v5_fails = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_v5_err),
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w_when_v5_fails == 12
    assert "HATA (v5_sgr_all)" in capsys.readouterr().out
    monkeypatch.setattr(forward_v5, "fit_predict_df", orig_v5_fit)
    econn = sqlite3.connect(str(out_v5_err))
    try:
        mvs = {r[0] for r in econn.execute("SELECT DISTINCT model_version FROM predictions_v5").fetchall()}
        assert mvs == {"v6_e5", "v7_tcjp"}
    finally:
        econn.close()

    # (d) v7 error must not block v5_sgr_all or v6_e5
    out_v7_err = tmp_path / "v7_err.db"
    orig_v7_live = forward_v5.fit_predict_v7_live
    monkeypatch.setattr(
        forward_v5,
        "fit_predict_v7_live",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("sentetik v7 hatası")),
    )
    _ = capsys.readouterr()
    w_when_v7_fails = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_v7_err),
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w_when_v7_fails == 12
    assert "HATA (v7_tcjp)" in capsys.readouterr().out
    monkeypatch.setattr(forward_v5, "fit_predict_v7_live", orig_v7_live)
    econn7 = sqlite3.connect(str(out_v7_err))
    try:
        mvs7 = {r[0] for r in econn7.execute("SELECT DISTINCT model_version FROM predictions_v5").fetchall()}
        assert mvs7 == {"v5_sgr_all", "v6_e5"}
    finally:
        econn7.close()


def test_run_once_v6_daily_cache_reuse_and_key_change_retrain(tmp_path, monkeypatch):
    target_date = "2026-04-20"
    main_db = tmp_path / "ganyan_cache.db"
    out_db = tmp_path / "out_cache.db"
    cache_dir = tmp_path / "models_cache"
    _setup_three_due_races_db(main_db, target_date=target_date)

    fit_calls = []
    v7_fit_calls = []
    real_fit_bundle = model_v6.fit_v6_model_bundle
    real_v7_fit_bundle = model_v7.fit_v7_model_bundle

    def _spy_fit(train_df, config=None):
        fit_calls.append(len(train_df))
        return real_fit_bundle(train_df, config=config)

    def _spy_v7_fit(train_df, config=None):
        v7_fit_calls.append(len(train_df))
        return real_v7_fit_bundle(train_df, config=config)

    monkeypatch.setattr(model_v6, "fit_v6_model_bundle", _spy_fit)
    monkeypatch.setattr(model_v7, "fit_v7_model_bundle", _spy_v7_fit)

    # Race 1 at 13:55 -> trains V6 + V7 once each and writes <date>_v6_e5.pkl & <date>_v7_tcjp.pkl
    w1 = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w1 == 18
    assert len(fit_calls) == 2
    assert len(v7_fit_calls) == 1

    # Race 2 at 14:24 (same day, same train_start & configs) -> loads caches without retraining
    w2 = forward_v5.run_once(
        now="2026-04-20T14:24:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w2 == 18
    assert len(fit_calls) == 2
    assert len(v7_fit_calls) == 1

    # Race 3 at 14:54 with altered train_start -> cache keys change -> retrains both V6 and V7
    w3 = forward_v5.run_once(
        now="2026-04-20T14:54:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2022-01-01",
        do_snapshot=False,
        cache_dir=str(cache_dir),
    )
    assert w3 == 18
    assert len(fit_calls) == 4
    assert len(v7_fit_calls) == 2


def test_v6_history_start_excludes_pre_2006_03_04_rows(tmp_path):
    main_db = tmp_path / "ganyan_2005.db"
    _populate_synthetic_v5_sqlite(main_db)

    # Inject a 2005-06-01 settled race (before V6_CONFIG['history_start'] == '2006-03-04')
    conn = init_db(main_db)
    try:
        rid_old = "2005-06-01_Ankara_1"
        old_runners = [
            {
                "race_id": rid_old,
                "prog_no": i + 1,
                "horse_key": f"SIRE_{i}|DAM_{i}|2018",
                "name": f"AT {i}",
                "name_raw": f"AT {i}",
                "age": 3,
                "sex": "e",
                "sire": f"SIRE_{i}",
                "dam": f"DAM_{i}",
                "weight": 57.0,
                "jockey": "J_0",
                "owner": "O_0",
                "trainer": "T_0",
                "gate": i + 1,
                "hp": 55.0,
                "finish": i + 1,
                "time_s": 86.0 + 0.2 * i,
                "ganyan": 3.0 + i,
                "agf_close": None,
                "agf_close_rank": None,
                "scratched": 0,
            }
            for i in range(4)
        ]
        upsert_results(
            conn,
            {
                "races": [
                    {
                        "race_id": rid_old,
                        "date": "2005-06-01",
                        "city": "Ankara",
                        "race_no": 1,
                        "post_time": "14:00",
                        "yg_no": 1,
                        "cls": "ŞARTLI",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "result",
                    }
                ],
                "runners": old_runners,
                "bets": [],
                "altili": [],
            },
        )
        conn.commit()

        df = forward_v5._load_runners_with_today(conn, "2026-04-15", overlay_snapshots=False)
        tables = forward_v5._filter_v5_tables_pre_day(forward_v5.load_v5_tables(conn), df, "2026-04-15")
    finally:
        conn.close()

    assert (df["date"] == "2005-06-01").any()
    df_v6, _tables_v6, can_share = forward_v5._prepare_v6_inputs(
        df, tables, "2026-04-15", model_v6.V6_CONFIG
    )
    assert can_share is False
    assert not (df_v6["date"] < "2006-03-04").any()


def test_backcheck_cli_and_report_integration(tmp_path, capsys):
    main_db = tmp_path / "ganyan_bc.db"
    _populate_synthetic_v5_sqlite(main_db)

    # Make race 2 on 2026-04-15 a 5-horse race (scratch 6th horse) + add 1 unfinished scheduled race 3
    conn = init_db(main_db)
    try:
        conn.execute(
            "UPDATE runners SET scratched = 1 WHERE race_id = '2026-04-15_Ankara_2' AND prog_no = 6"
        )
        upsert_program(
            conn,
            {
                "races": [
                    {
                        "race_id": "2026-04-15_Ankara_3",
                        "date": "2026-04-15",
                        "city": "Ankara",
                        "race_no": 3,
                        "post_time": "16:30",
                        "yg_no": 3,
                        "cls": "MAIDEN",
                        "breed": "Ingiliz",
                        "distance": 1200,
                        "surface": "Kum",
                        "status": "scheduled",
                    }
                ],
                "runners": _make_prog_runners(
                    "2026-04-15_Ankara_3", range(0, 5), agf_list=[30.0, 25.0, 20.0, 15.0, 10.0]
                ),
            },
        )
        conn.commit()
    finally:
        conn.close()

    # 1) --backcheck without --out must NOT create any output DB and must end with BACKCHECK OK
    _ = capsys.readouterr()
    rc_no_out = forward_v5.main(["--db", str(main_db), "--backcheck", "2026-04-15"])
    assert rc_no_out == 0
    lines_1 = [ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines_1[-1] == "BACKCHECK OK"
    joined_1 = "\n".join(lines_1)
    assert "kosu=2" in joined_1
    assert "atlanan_sonuclanmamis=1" in joined_1
    assert "AGF (kapanış)" in joined_1
    assert "v5_sgr_all" in joined_1
    assert "v6_e5" in joined_1
    assert "v7_tcjp" in joined_1
    assert "spearman(v6_e5, v5_sgr_all)" in joined_1
    assert "spearman(v7_tcjp, v6_e5)" in joined_1

    # 2) --backcheck with --out writes predictions_v5 for all 3 models, consumable by forward_v5_report.py
    bc_out_db = tmp_path / "bc_preds.db"
    rc_with_out = forward_v5.main(
        ["--db", str(main_db), "--backcheck", "2026-04-15", "--out", str(bc_out_db)]
    )
    assert rc_with_out == 0
    lines_2 = [ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines_2[-1] == "BACKCHECK OK"
    assert bc_out_db.exists()

    bconn = sqlite3.connect(str(bc_out_db))
    try:
        cnts = dict(
            bconn.execute(
                "SELECT model_version, COUNT(*) FROM predictions_v5 GROUP BY model_version"
            ).fetchall()
        )
        assert cnts == {"v5_sgr_all": 11, "v6_e5": 11, "v7_tcjp": 11}
    finally:
        bconn.close()

    rep_md = tmp_path / "bc_report.md"
    rc_rep = forward_v5_report.main(
        ["--db", str(main_db), "--forward-db", str(bc_out_db), "--out", str(rep_md)]
    )
    assert rc_rep == 0
    md_txt = rep_md.read_text(encoding="utf-8")
    assert "Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `2`" in md_txt
    assert "Dörtlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `v7_tcjp` ∩ `AGF`):** `2`" in md_txt

