"""Unit and synthetic end-to-end tests for V6 live core (`model_v6`), cache, and `forward_v5_report.py`."""
import copy
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan import model_v6
from ganyan.db import init_db, upsert_program, upsert_results
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5
from ganyan.model_v6 import (
    V6_CONFIG,
    V6_LIVE_MODEL_VERSION,
    V6_YEARLY_GAMMA,
    RaceTemperatureCalibrator,
    build_v6_cache_key,
    fit_predict_v6,
    fit_predict_v6_live,
    fit_v6_model_bundle,
    get_v6_gamma,
)
from scripts import forward_v5, forward_v5_report


def _build_synthetic_live_frames():
    """Build leak-free `(train_df, today_df)` with >800 training rows so `min_samples_leaf=400` splits."""
    rng = np.random.default_rng(20261116)
    horses = [f"SIRE_{i}|DAM_{i}|2020" for i in range(12)]
    hist_dates = pd.date_range("2024-01-01", periods=80, freq="4D")
    target_date = "2026-06-15"

    rows = []
    ext_rows = []
    w_rows = []

    for d_idx, dt_val in enumerate(hist_dates):
        d_str = dt_val.strftime("%Y-%m-%d")
        city = "Ankara" if d_idx % 2 == 0 else "İstanbul"
        if d_idx % 3 == 0:
            w_str = (dt_val - pd.Timedelta(days=6)).strftime("%Y-%m-%d")
            for h_i, hk in enumerate(horses):
                w_rows.append(
                    {
                        "source": "liderform",
                        "horse_key": hk,
                        "date": w_str,
                        "city": city,
                        "kind": "SPRINT" if h_i % 2 == 0 else "GALOP",
                        "d800": 49.5 + 0.15 * h_i,
                        "d600": 37.0 + 0.10 * h_i,
                        "d400": 24.2 + 0.08 * h_i,
                        "effort": "ALLOUT" if h_i % 4 == 0 else "CANTER",
                    }
                )

        for r_no in (1, 2):
            rid = f"{d_str}_{city}_{r_no}"
            sub_h = horses[:6] if r_no == 1 else horses[6:]
            # Give lower-indexed horses genuinely higher win chance + higher AGF so HGB learns signal
            strengths = np.array([6.0, 4.5, 3.2, 2.2, 1.4, 0.9], dtype=float)
            probs = strengths / strengths.sum()
            order_fin = rng.choice(6, size=6, replace=False, p=probs)
            fin_by_pos = np.empty(6, dtype=int)
            for rank_i, pos_i in enumerate(order_fin, start=1):
                fin_by_pos[pos_i] = rank_i

            for pos, hk in enumerate(sub_h):
                h_num = int(hk.split("_")[1].split("|")[0])
                fin = int(fin_by_pos[pos])
                agf_val = float(100.0 * probs[pos])
                rows.append(
                    {
                        "race_id": rid,
                        "date": d_str,
                        "city": city,
                        "race_no": r_no,
                        "prog_no": pos + 1,
                        "horse_key": hk,
                        "name": f"AT {h_num}",
                        "age": 4,
                        "sex": "d" if h_num % 2 == 0 else "e",
                        "sire": f"SIRE_{h_num}",
                        "dam": f"DAM_{h_num}",
                        "weight": 56.0 + 0.5 * pos,
                        "jockey": f"J_{pos % 4}",
                        "owner": f"O_{h_num % 3}",
                        "trainer": f"T_{pos % 3}",
                        "gate": pos + 1,
                        "hp": 70.0 - 2.5 * pos,
                        "breed": "Ingiliz",
                        "distance": 1400 if r_no == 1 else 1600,
                        "surface": "Çim" if r_no == 1 else "Kum",
                        "finish": fin,
                        "time_s": (85.0 if r_no == 1 else 100.0) + 0.30 * fin,
                        "ganyan": max(1.05, 0.80 / probs[pos]),
                        "agf_close": agf_val,
                        "agf_close_rank": pos + 1,
                        "scratched": 0,
                    }
                )
                ext_rows.append({"race_id": rid, "horse_key": hk, "value": float(80.0 - 2.0 * fin)})

    # Two target races on 2026-06-15 (6 horses and 5 horses; outcomes masked as in live)
    for r_no, sub_h, agfs in [
        (1, horses[:6], [36.0, 24.0, 16.0, 11.0, 8.0, 5.0]),
        (2, horses[6:11], [40.0, 25.0, 17.0, 11.0, 7.0]),
    ]:
        rid = f"{target_date}_Ankara_{r_no}"
        for pos, (hk, agf_v) in enumerate(zip(sub_h, agfs)):
            h_num = int(hk.split("_")[1].split("|")[0])
            rows.append(
                {
                    "race_id": rid,
                    "date": target_date,
                    "city": "Ankara",
                    "race_no": r_no,
                    "prog_no": pos + 1,
                    "horse_key": hk,
                    "name": f"AT {h_num}",
                    "age": 4,
                    "sex": "d" if h_num % 2 == 0 else "e",
                    "sire": f"SIRE_{h_num}",
                    "dam": f"DAM_{h_num}",
                    "weight": 56.0 + 0.5 * pos,
                    "jockey": f"J_{pos % 4}",
                    "owner": f"O_{h_num % 3}",
                    "trainer": f"T_{pos % 3}",
                    "gate": pos + 1,
                    "hp": 70.0 - 2.5 * pos,
                    "breed": "Ingiliz",
                    "distance": 1400,
                    "surface": "Çim",
                    "finish": np.nan,
                    "time_s": np.nan,
                    "ganyan": np.nan,
                    "agf_close": agf_v,
                    "agf_close_rank": pos + 1,
                    "scratched": 0,
                }
            )

    raw_df = pd.DataFrame(rows)
    tables = {"ext": pd.DataFrame(ext_rows), "workouts": pd.DataFrame(w_rows)}
    feat_df = attach_v5(build_features(raw_df, ref_end="2025-01-01"), tables, blocks=("S", "G", "R"))

    target_ts = pd.Timestamp(target_date)
    train_df = feat_df[(feat_df["date"] < target_ts) & feat_df["win"].notna() & feat_df["agf_share"].notna()].copy()
    today_df = feat_df[feat_df["date"] == target_ts].copy()
    return train_df, today_df


def test_v6_yearly_gamma_table_and_fallback_warning():
    assert V6_LIVE_MODEL_VERSION == "v6_e5"
    expected_gammas = {
        2017: 0.9794,
        2018: 0.9844,
        2019: 0.9915,
        2020: 0.9932,
        2021: 1.0030,
        2022: 1.0139,
        2023: 1.0278,
        2024: 1.0331,
        2025: 1.0336,
        2026: 1.0307,
    }
    assert V6_YEARLY_GAMMA == pytest.approx(expected_gammas)

    warns = []
    g_2026 = get_v6_gamma(2026, warn_fn=warns.append)
    assert g_2026 == pytest.approx(1.0307)
    assert warns == []

    # Future year not in table -> uses latest year (2026: 1.0307) and logs warning
    g_2027 = get_v6_gamma(2027, warn_fn=warns.append)
    assert g_2027 == pytest.approx(1.0307)
    assert len(warns) == 1
    assert "2027" in warns[0]
    assert "2026" in warns[0]


def test_fit_predict_v6_live_sums_to_one_and_matches_fit_predict_v6_at_gamma_one():
    train_df, today_df = _build_synthetic_live_frames()
    assert len(train_df) == 960
    assert len(today_df) == 11

    # Interleave race rows to ensure non-contiguous race_ids still normalize cleanly
    today_shuffled = today_df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    p_live_2026 = fit_predict_v6_live(train_df, today_shuffled)
    assert len(p_live_2026) == len(today_shuffled)
    assert np.all(np.isfinite(p_live_2026))
    assert np.all((p_live_2026 > 0.0) & (p_live_2026 < 1.0))

    sums_2026 = pd.Series(p_live_2026).groupby(today_shuffled["race_id"].to_numpy()).sum()
    assert np.allclose(sums_2026.to_numpy(), 1.0, atol=1e-12)

    # When gamma == 1.0, fit_predict_v6_live must match fit_predict_v6 5-seed average identically
    p_live_g1 = fit_predict_v6_live(train_df, today_shuffled, gamma=1.0)
    p_ref_5s = fit_predict_v6(
        train_df,
        today_shuffled,
        V6_CONFIG["feature_cols"],
        hgb_params=V6_CONFIG["hgb_params"],
        seeds=V6_CONFIG["seeds"],
        temporal_val_frac=V6_CONFIG.get("temporal_val_frac"),
    )
    assert np.allclose(p_live_g1, p_ref_5s, atol=1e-12)

    # And 2026 default gamma (1.0307 != 1.0) equals RaceTemperatureCalibrator(gamma=1.0307) on p_ref_5s
    cal = RaceTemperatureCalibrator(clip_min=1e-6)
    cal.gamma = V6_YEARLY_GAMMA[2026]
    cal.temperature = 1.0 / cal.gamma
    p_expected_2026 = cal.predict(p_ref_5s, today_shuffled["race_id"].to_numpy())
    assert np.allclose(p_live_2026, p_expected_2026, atol=1e-12)
    assert not np.allclose(p_live_2026, p_live_g1, atol=1e-5)


def test_v6_model_bundle_cache_hit_and_key_invalidation(tmp_path, monkeypatch):
    train_df, today_df = _build_synthetic_live_frames()
    cache_file = tmp_path / "forward_models" / "2026-06-15_v6_e5.pkl"

    fit_calls = []
    real_fit_bundle = fit_v6_model_bundle

    def _spy_fit(tr, config=None):
        fit_calls.append(build_v6_cache_key("2026-06-15", "spy", config=config)["config_digest"])
        return real_fit_bundle(tr, config=config)

    monkeypatch.setattr(model_v6, "fit_v6_model_bundle", _spy_fit)

    # 1) Cold cache -> trains once and writes pickle
    p1 = fit_predict_v6_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2015-01-01"},
    )
    assert len(fit_calls) == 1
    assert cache_file.exists()

    # 2) Warm cache with identical (date, train_start, config_digest) -> 0 new trainings
    p2 = fit_predict_v6_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2015-01-01"},
    )
    assert len(fit_calls) == 1
    assert np.array_equal(p1, p2)

    # 3) Change train_start -> cache key mismatch -> retrains
    p3 = fit_predict_v6_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 2
    assert np.allclose(p1, p3, atol=1e-12)

    # 4) Repeat with updated train_start -> warm hit again (no retrain)
    _ = fit_predict_v6_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 2

    # 5) Change config (config_digest changes) -> retrains
    alt_cfg = copy.deepcopy(V6_CONFIG)
    alt_cfg["hgb_params"]["max_iter"] = 60
    _ = fit_predict_v6_live(
        train_df,
        today_df,
        config=alt_cfg,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 3

    # 6) Change date -> retrains
    _ = fit_predict_v6_live(
        train_df,
        today_df,
        config=alt_cfg,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-16", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 4


def test_forward_v5_report_synthetic_settled_and_empty_db(tmp_path):
    main_db = tmp_path / "main.db"
    fwd_db = tmp_path / "forward_v5.db"
    empty_out = tmp_path / "empty_FORWARD_V5.md"

    # (1) Missing DBs -> exits 0 and writes "yeterli veri yok"
    rc_missing = forward_v5_report.main(
        ["--db", str(main_db), "--forward-db", str(fwd_db), "--out", str(empty_out)]
    )
    assert rc_missing == 0
    assert "yeterli veri yok" in empty_out.read_text(encoding="utf-8")

    # (2) Build synthetic main_db with 4 settled races + 1 unfinished scheduled race
    conn = init_db(main_db)
    try:
        settled_races = []
        settled_runners = []
        for r_i in range(1, 5):
            rid = f"2026-11-15_Ankara_{r_i}"
            settled_races.append(
                {
                    "race_id": rid,
                    "date": "2026-11-15",
                    "city": "Ankara",
                    "race_no": r_i,
                    "post_time": f"1{3 + r_i}:00",
                    "yg_no": r_i,
                    "cls": "ŞARTLI",
                    "breed": "Ingiliz",
                    "distance": 1400,
                    "surface": "Çim",
                    "status": "result",
                }
            )
            agf_close_vals = [42.0, 26.0, 18.0, 14.0]
            # Winner alternates between horse 1 and horse 2
            fins = [1, 2, 3, 4] if r_i % 2 == 1 else [2, 1, 3, 4]
            for pos in range(4):
                hk = f"S_{pos}|D_{pos}|2021"
                settled_runners.append(
                    {
                        "race_id": rid,
                        "prog_no": pos + 1,
                        "horse_key": hk,
                        "name": f"AT {pos + 1}",
                        "name_raw": f"AT {pos + 1}",
                        "age": 4,
                        "sex": "e",
                        "sire": f"S_{pos}",
                        "dam": f"D_{pos}",
                        "weight": 57.0,
                        "jockey": f"J_{pos}",
                        "owner": f"O_{pos}",
                        "trainer": f"T_{pos}",
                        "gate": pos + 1,
                        "hp": 60.0,
                        "finish": fins[pos],
                        "time_s": 85.0 + 0.3 * fins[pos],
                        "ganyan": 2.2 + fins[pos],
                        "agf_close": agf_close_vals[pos],
                        "agf_close_rank": pos + 1,
                        "scratched": 0,
                    }
                )
        upsert_results(conn, {"races": settled_races, "runners": settled_runners, "bets": [], "altili": []})
        for r_row in settled_runners:
            conn.execute(
                "UPDATE runners SET prog_no = ? WHERE race_id = ? AND horse_key = ?",
                (r_row["prog_no"], r_row["race_id"], r_row["horse_key"]),
            )

        # Unfinished scheduled race 5 (must be excluded from settled metrics)
        unfin_rid = "2026-11-15_Ankara_5"
        upsert_program(
            conn,
            {
                "races": [
                    {
                        "race_id": unfin_rid,
                        "date": "2026-11-15",
                        "city": "Ankara",
                        "race_no": 5,
                        "post_time": "18:00",
                        "yg_no": 5,
                        "cls": "MAIDEN",
                        "breed": "Ingiliz",
                        "distance": 1200,
                        "surface": "Kum",
                        "status": "scheduled",
                    }
                ],
                "runners": [
                    {
                        "race_id": unfin_rid,
                        "prog_no": pos + 1,
                        "horse_key": f"U_{pos}|D_{pos}|2022",
                        "name": f"UAT {pos + 1}",
                        "name_raw": f"UAT {pos + 1}",
                        "age": 3,
                        "sex": "d",
                        "sire": f"U_{pos}",
                        "dam": f"D_{pos}",
                        "weight": 55.0,
                        "jockey": "J_0",
                        "owner": "O_0",
                        "trainer": "T_0",
                        "gate": pos + 1,
                        "hp": 50.0,
                        "son6_raw": "Ç2",
                        "kgs": 14,
                        "s20": 15,
                        "best_time_s": 74.0,
                        "agf_pct": 25.0,
                        "agf_rank": pos + 1,
                    }
                    for pos in range(4)
                ],
            },
        )

        # Insert agf_snapshots ONLY for races 1 and 2 (so races 3 and 4 test fallback to agf_close!)
        for r_i in (1, 2):
            rid = f"2026-11-15_Ankara_{r_i}"
            snap_pcts = [38.0, 30.0, 20.0, 12.0]
            for pno, sp in enumerate(snap_pcts, start=1):
                conn.execute(
                    "INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank) VALUES (?,?,?,?,?)",
                    (rid, pno, f"2026-11-15T1{3 + r_i - 1}:54:00+03:00", sp, pno),
                )
        conn.commit()
    finally:
        conn.close()

    fconn = forward_v5.init_out_db(fwd_db)
    try:
        for r_i in range(1, 6):
            rid = f"2026-11-15_Ankara_{r_i}"
            c_at = f"2026-11-15T1{3 + r_i - 1}:55:00+03:00"
            p_v5 = [0.40, 0.30, 0.20, 0.10] if r_i % 2 == 1 else [0.34, 0.36, 0.18, 0.12]
            p_v6 = [0.44, 0.28, 0.18, 0.10] if r_i % 2 == 1 else [0.30, 0.42, 0.17, 0.11]
            for pno in range(1, 5):
                fconn.execute(
                    """
                    INSERT INTO predictions_v5 (
                        race_id, prog_no, model_version, created_at, minutes_to_post,
                        p_win, agf_used, s_cov, g_cov
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rid, pno, "v5_sgr_all", c_at, 5.0, p_v5[pno - 1], 25.0, 1.0, 0.75),
                )
                fconn.execute(
                    """
                    INSERT INTO predictions_v5 (
                        race_id, prog_no, model_version, created_at, minutes_to_post,
                        p_win, agf_used, s_cov, g_cov
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rid, pno, "v6_e5", c_at, 5.0, p_v6[pno - 1], 25.0, 1.0, 0.75),
                )
        fconn.commit()
    finally:
        fconn.close()

    rep_out = tmp_path / "FORWARD_V5.md"
    rc = forward_v5_report.main(
        ["--db", str(main_db), "--forward-db", str(fwd_db), "--out", str(rep_out)]
    )
    assert rc == 0
    md = rep_out.read_text(encoding="utf-8")

    assert "Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `4`" in md
    assert "`agf_snapshots`" in md
    assert "`runners.agf_close`" in md
    assert "`v6_e5 − v5_sgr_all`" in md
    assert "`v6_e5 − AGF`" in md
    assert "`v5_sgr_all − AGF`" in md
    assert "Bootstrap %95 GA" in md
    assert "`s_cov`" in md and "`g_cov`" in md
    assert "Küçük Örneklem" in md

    # Neither input DB may have been modified with extra tables
    m_chk = sqlite3.connect(str(main_db))
    try:
        assert m_chk.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
    finally:
        m_chk.close()

    # (3) Direct check: _race_winner_metrics_from_probs accepts list, ndarray, and Series identically
    sample_act = pd.DataFrame({"finish": [2, 1, 3, 4]})
    m_list = forward_v5_report._race_winner_metrics_from_probs(sample_act, [30.0, 40.0, 20.0, 10.0])
    m_arr = forward_v5_report._race_winner_metrics_from_probs(
        sample_act, np.array([30.0, 40.0, 20.0, 10.0], dtype=np.float64)
    )
    m_ser = forward_v5_report._race_winner_metrics_from_probs(
        sample_act, pd.Series([30.0, 40.0, 20.0, 10.0])
    )
    assert m_list == pytest.approx(m_arr)
    assert m_list == pytest.approx(m_ser)
    assert m_list["top1"] == 1.0
