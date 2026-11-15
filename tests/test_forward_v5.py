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

from ganyan.db import init_db, upsert_program
from scripts import daily_v5_update, forward_v5

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

    snap_calls = []
    monkeypatch.setattr(
        forward_v5,
        "snapshot_agf",
        lambda ds, db_path=None, prog_dir=None, cities=None: snap_calls.append((ds, list(cities or []))) or 0,
    )

    # 1) At 13:55 (mtp=5.0 for race 1, mtp=35.0 for race 2): only race 1 is predicted
    written_1 = forward_v5.run_once(
        now="2026-04-20T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        due_max_min=8.0,
    )
    assert written_1 == 6
    assert snap_calls == [(target_date, ["Ankara"])]

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
            ORDER BY prog_no
            """
        ).fetchall()
        assert len(rows) == 6
        assert [r[0] for r in rows] == [rid_due] * 6
        assert [r[1] for r in rows] == [1, 2, 3, 4, 5, 6]
        assert {r[2] for r in rows} == {"v5_sgr_all"}
        assert {r[3] for r in rows} == {"2026-04-20T13:55:00+03:00"}
        assert all(r[4] == pytest.approx(5.0) for r in rows)
        p_vals = [r[5] for r in rows]
        assert all(0.0 < p < 1.0 for p in p_vals)
        assert sum(p_vals) == pytest.approx(1.0)
        assert [r[6] for r in rows] == pytest.approx(agf_snap_vals)
        # All 6 horses ran on 2026-04-15 (Yenibeygir hiz) and had 2026-04-05 Liderform workouts
        assert all(r[7] == pytest.approx(1.0) for r in rows)
        assert all(r[8] == pytest.approx(1.0) for r in rows)
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
    )
    assert written_2 == 0
    assert len(snap_calls) == 1

    # 3) At 14:24 (mtp=6.0 for race 2): race 2 enters due window and gets predicted
    written_3 = forward_v5.run_once(
        now="2026-04-20T14:24:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        due_max_min=8.0,
    )
    assert written_3 == 6
    assert len(snap_calls) == 2

    oconn = sqlite3.connect(str(out_db))
    try:
        total_cnt = oconn.execute("SELECT COUNT(*) FROM predictions_v5").fetchone()[0]
        assert total_cnt == 12
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
