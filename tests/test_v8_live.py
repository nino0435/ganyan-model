"""Unit and synthetic end-to-end tests for V8 live core (`model_v8`), `--prewarm-models`, and `forward_v5_report.py`."""
import copy
import importlib.util
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan import model_v6, model_v7, model_v8
from ganyan.db import init_db, upsert_program, upsert_results
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5
from ganyan.features_v7 import attach_v7
from ganyan.features_v8 import attach_v8
from ganyan.model_v6 import RaceTemperatureCalibrator, fit_predict_v6
from ganyan.model_v8 import (
    V8_CONFIG,
    V8_LIVE_MODEL_VERSION,
    V8_YEARLY_GAMMA,
    build_v8_cache_key,
    fit_predict_v8_live,
    fit_v8_model_bundle,
    get_v8_gamma,
)
from scripts import forward_v5, forward_v5_report


def _load_populate_helper():
    mod_path = Path(__file__).with_name("test_model_v5.py")
    spec = importlib.util.spec_from_file_location("_test_model_v5_helper_v8", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._populate_synthetic_v5_sqlite


_populate_synthetic_v5_sqlite = _load_populate_helper()


def _build_synthetic_v8_live_frames():
    """Build leak-free `(train_df, today_df)` with >800 training rows and T+C+J+P+A+N columns."""
    rng = np.random.default_rng(20261124)
    horses = [f"SIRE_{i}|DAM_{i}|2020" for i in range(12)]
    hist_dates = pd.date_range("2024-01-01", periods=80, freq="4D")
    target_date = "2026-06-15"
    equip_choices = ["", "KG", "KG DB", "KG K", "KG DB SK"]
    cls_choices = ["Handikap 15", "ŞARTLI 3", "KV-6", "MAIDEN"]
    owners = ["YILMAZ AHIR", "AHMET YILMAZ", "KAYA EKURISI", "MEHMET KAYA"]

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
            strengths = np.array([6.0, 4.5, 3.2, 2.2, 1.4, 0.9], dtype=float)
            probs = strengths / strengths.sum()
            order_fin = rng.choice(6, size=6, replace=False, p=probs)
            fin_by_pos = np.empty(6, dtype=int)
            for rank_i, pos_i in enumerate(order_fin, start=1):
                fin_by_pos[pos_i] = rank_i

            for pos, hk in enumerate(sub_h):
                h_num = int(hk.split("_")[1].split("|")[0])
                fin = int(fin_by_pos[pos])
                eq = equip_choices[(d_idx + pos) % len(equip_choices)]
                jock = f"J_{pos % 4} AP" if (d_idx + pos) % 3 == 0 else f"J_{pos % 4}"
                rows.append(
                    {
                        "race_id": rid,
                        "date": d_str,
                        "city": city,
                        "race_no": r_no,
                        "prog_no": pos + 1,
                        "horse_key": hk,
                        "name": f"AT {h_num}",
                        "name_raw": f"AT {h_num} {eq}".strip(),
                        "cls": cls_choices[(d_idx + r_no) % len(cls_choices)],
                        "age": 4 + (d_idx // 50),
                        "sex": "d" if h_num % 2 == 0 else "e",
                        "sire": f"SIRE_{h_num}",
                        "dam": f"DAM_{h_num}",
                        "weight": 55.5 + 0.5 * pos + (0.5 if d_idx % 2 else 0.0),
                        "jockey": jock,
                        "owner": owners[h_num % len(owners)],
                        "trainer": f"T_{pos % 3}",
                        "gate": pos + 1,
                        "hp": 70.0 - 2.5 * pos,
                        "breed": "Ingiliz",
                        "distance": 1400 if r_no == 1 else 1600,
                        "surface": "Çim" if r_no == 1 else "Kum",
                        "finish": fin,
                        "time_s": (85.0 if r_no == 1 else 100.0) + 0.30 * fin,
                        "ganyan": max(1.05, 0.80 / probs[pos]),
                        "agf_close": float(100.0 * probs[pos]),
                        "agf_close_rank": pos + 1,
                        "scratched": 0,
                    }
                )
                ext_rows.append({"race_id": rid, "horse_key": hk, "value": float(80.0 - 2.0 * fin)})

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
                    "name_raw": f"AT {h_num} KG DB",
                    "cls": "KV-6",
                    "age": 4,
                    "sex": "d" if h_num % 2 == 0 else "e",
                    "sire": f"SIRE_{h_num}",
                    "dam": f"DAM_{h_num}",
                    "weight": 56.0 + 0.5 * pos,
                    "jockey": f"J_{pos % 4}",
                    "owner": owners[h_num % len(owners)],
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
    feat_df = attach_v7(feat_df, blocks=("T", "C", "J", "P"))
    feat_df = attach_v8(feat_df, blocks=("A", "N"))

    target_ts = pd.Timestamp(target_date)
    train_df = feat_df[(feat_df["date"] < target_ts) & feat_df["win"].notna() & feat_df["agf_share"].notna()].copy()
    today_df = feat_df[feat_df["date"] == target_ts].copy()
    return train_df, today_df


def test_v8_config_and_yearly_gamma_table_and_fallback_warning():
    assert V8_LIVE_MODEL_VERSION == "v8_an"
    assert V8_CONFIG["variant"] == "V8_SEL_CAL"
    assert V8_CONFIG["v7_blocks"] == ["T", "C", "J", "P"]
    assert V8_CONFIG["v8_blocks"] == ["A", "N"]
    assert len(V8_CONFIG["feature_cols"]) == 122

    expected_gammas = {
        2017: 0.9881,
        2018: 0.9873,
        2019: 0.9952,
        2020: 0.9967,
        2021: 1.0053,
        2022: 1.0153,
        2023: 1.0290,
        2024: 1.0338,
        2025: 1.0337,
        2026: 1.0306,
    }
    assert V8_YEARLY_GAMMA == pytest.approx(expected_gammas)

    warns = []
    assert get_v8_gamma(2026, warn_fn=warns.append) == pytest.approx(1.0306)
    assert warns == []

    g_2027 = get_v8_gamma(2027, warn_fn=warns.append)
    assert g_2027 == pytest.approx(1.0306)
    assert len(warns) == 1
    assert "V8" in warns[0]
    assert "2027" in warns[0]
    assert "2026" in warns[0]


def test_fit_predict_v8_live_sums_to_one_and_matches_gamma_calibration():
    train_df, today_df = _build_synthetic_v8_live_frames()
    assert len(train_df) == 960
    assert len(today_df) == 11

    today_shuffled = today_df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    p_live_2026 = fit_predict_v8_live(train_df, today_shuffled)
    assert len(p_live_2026) == len(today_shuffled)
    assert np.all(np.isfinite(p_live_2026))
    assert np.all((p_live_2026 > 0.0) & (p_live_2026 < 1.0))

    sums_2026 = pd.Series(p_live_2026).groupby(today_shuffled["race_id"].to_numpy()).sum()
    assert np.allclose(sums_2026.to_numpy(), 1.0, atol=1e-12)

    p_live_g1 = fit_predict_v8_live(train_df, today_shuffled, gamma=1.0)
    p_ref_5s = fit_predict_v6(
        train_df,
        today_shuffled,
        V8_CONFIG["feature_cols"],
        hgb_params=V8_CONFIG["hgb_params"],
        seeds=V8_CONFIG["seeds"],
        temporal_val_frac=V8_CONFIG.get("temporal_val_frac"),
    )
    assert np.allclose(p_live_g1, p_ref_5s, atol=1e-12)

    cal = RaceTemperatureCalibrator(clip_min=1e-6)
    cal.gamma = V8_YEARLY_GAMMA[2026]
    cal.temperature = 1.0 / cal.gamma
    p_expected_2026 = cal.predict(p_ref_5s, today_shuffled["race_id"].to_numpy())
    assert np.allclose(p_live_2026, p_expected_2026, atol=1e-12)
    assert not np.allclose(p_live_2026, p_live_g1, atol=1e-5)


def test_v8_model_bundle_cache_hit_and_key_invalidation(tmp_path, monkeypatch):
    train_df, today_df = _build_synthetic_v8_live_frames()
    cache_file = tmp_path / "forward_models" / "2026-06-15_v8_an.pkl"

    fit_calls = []
    real_fit_bundle = fit_v8_model_bundle

    def _spy_fit(tr, config=None):
        fit_calls.append(build_v8_cache_key("2026-06-15", "spy", config=config)["config_digest"])
        return real_fit_bundle(tr, config=config)

    monkeypatch.setattr(model_v8, "fit_v8_model_bundle", _spy_fit)

    # 1) Cold cache -> trains once and saves pickle
    p1 = fit_predict_v8_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2015-01-01"},
    )
    assert len(fit_calls) == 1
    assert cache_file.exists()

    # 2) Warm hit -> 0 retraining
    p2 = fit_predict_v8_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2015-01-01"},
    )
    assert len(fit_calls) == 1
    assert np.array_equal(p1, p2)

    # 3) train_start change -> retrains
    _ = fit_predict_v8_live(
        train_df,
        today_df,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 2

    # 4) Config change -> retrains
    alt_cfg = copy.deepcopy(V8_CONFIG)
    alt_cfg["hgb_params"]["max_iter"] = 60
    _ = fit_predict_v8_live(
        train_df,
        today_df,
        config=alt_cfg,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-15", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 3

    # 5) Date change -> retrains
    _ = fit_predict_v8_live(
        train_df,
        today_df,
        config=alt_cfg,
        cache_path=str(cache_file),
        cache_meta={"date": "2026-06-16", "train_start": "2016-01-01"},
    )
    assert len(fit_calls) == 4


def test_prewarm_models_warms_active_triad_without_agf_and_skips_when_warm(tmp_path, monkeypatch):
    main_db = tmp_path / "ganyan_prewarm.db"
    cache_dir = tmp_path / "forward_models"
    out_db = tmp_path / "forward_v5.db"
    target_date = "2026-04-20"
    _populate_synthetic_v5_sqlite(main_db)

    v6_calls = []
    v7_calls = []
    v8_calls = []
    real_v6_fit = model_v6.fit_v6_model_bundle
    real_v7_fit = model_v7.fit_v7_model_bundle
    real_v8_fit = model_v8.fit_v8_model_bundle

    def _spy_v6(tr, config=None):
        v6_calls.append(len(tr))
        return real_v6_fit(tr, config=config)

    def _spy_v7(tr, config=None):
        v7_calls.append(len(tr))
        return real_v7_fit(tr, config=config)

    def _spy_v8(tr, config=None):
        v8_calls.append(len(tr))
        return real_v8_fit(tr, config=config)

    monkeypatch.setattr(model_v6, "fit_v6_model_bundle", _spy_v6)
    monkeypatch.setattr(model_v7, "fit_v7_model_bundle", _spy_v7)
    monkeypatch.setattr(model_v8, "fit_v8_model_bundle", _spy_v8)

    # 1) Cold prewarm even BEFORE today's program/AGF exists -> warms active triad (v6_e5, v7_tcjp, v8_an)
    warmed_1 = forward_v5.prewarm_models(
        date_str=target_date,
        main_db=str(main_db),
        train_start="2015-01-01",
        models="v6_e5,v7_tcjp,v8_an",
        cache_dir=str(cache_dir),
    )
    assert warmed_1 == ["v6_e5", "v7_tcjp", "v8_an"]
    assert (cache_dir / f"{target_date}_v6_e5.pkl").exists()
    assert (cache_dir / f"{target_date}_v7_tcjp.pkl").exists()
    assert (cache_dir / f"{target_date}_v8_an.pkl").exists()
    assert len(v8_calls) == 1
    assert len(v7_calls) == 1
    assert len(v6_calls) == 3

    # 2) Second prewarm call -> warm cache hit, skips without retraining
    warmed_2 = forward_v5.prewarm_models(
        date_str=target_date,
        main_db=str(main_db),
        train_start="2015-01-01",
        models="v6_e5,v7_tcjp,v8_an",
        cache_dir=str(cache_dir),
    )
    assert warmed_2 == []
    assert len(v8_calls) == 1
    assert len(v7_calls) == 1
    assert len(v6_calls) == 3

    # 3) Later live run_once reuses warm caches cleanly with 0 retraining
    conn = init_db(main_db)
    try:
        rid = f"{target_date}_Ankara_1"
        agfs = [30.0, 22.0, 18.0, 14.0, 10.0, 6.0]
        runners = [
            {
                "race_id": rid,
                "prog_no": pos + 1,
                "horse_key": f"SIRE_{pos}|DAM_{pos}|2018",
                "name": f"AT {pos}",
                "name_raw": f"AT {pos} KG DB",
                "age": 4,
                "sex": "d" if pos % 2 == 0 else "e",
                "sire": f"SIRE_{pos}",
                "dam": f"DAM_{pos}",
                "weight": 56.0 + pos * 0.5,
                "jockey": f"J_{pos % 4}",
                "owner": f"O_{pos % 3}",
                "trainer": f"T_{pos % 3}",
                "gate": pos + 1,
                "hp": 50.0 + pos,
                "son6_raw": "Ç1Ç2",
                "kgs": 15,
                "s20": 16,
                "best_time_s": 85.5,
                "agf_pct": agfs[pos],
                "agf_rank": pos + 1,
            }
            for pos in range(6)
        ]
        upsert_program(
            conn,
            {
                "races": [
                    {
                        "race_id": rid,
                        "date": target_date,
                        "city": "Ankara",
                        "race_no": 1,
                        "post_time": "14:00",
                        "yg_no": 1,
                        "cls": "ŞARTLI 3",
                        "breed": "Ingiliz",
                        "distance": 1400,
                        "surface": "Çim",
                        "status": "scheduled",
                    }
                ],
                "runners": runners,
            },
        )
        conn.commit()
    finally:
        conn.close()

    written = forward_v5.run_once(
        now=f"{target_date}T13:55:00+03:00",
        date_str=target_date,
        main_db=str(main_db),
        out_db=str(out_db),
        train_start="2015-01-01",
        due_max_min=8.0,
        do_snapshot=False,
        models="v6_e5,v7_tcjp,v8_an",
        cache_dir=str(cache_dir),
    )
    assert written == 18
    assert len(v8_calls) == 1
    assert len(v7_calls) == 1
    assert len(v6_calls) == 3


def test_forward_v5_report_active_v6_v7_v8_without_v5_and_with_legacy_archive(tmp_path):
    main_db = tmp_path / "main.db"
    fwd_db = tmp_path / "forward_v5.db"

    conn = init_db(main_db)
    try:
        settled_races = []
        settled_runners = []
        # Races 1..2: legacy era (2026-11-15, had v5_sgr_all + v6_e5)
        # Races 3..6: post-v5 retirement active era (2026-11-23, v6_e5 + v7_tcjp + v8_an only, NO v5!)
        for r_i in range(1, 7):
            d_str = "2026-11-15" if r_i <= 2 else "2026-11-23"
            rid = f"{d_str}_Ankara_{r_i}"
            settled_races.append(
                {
                    "race_id": rid,
                    "date": d_str,
                    "city": "Ankara",
                    "race_no": r_i,
                    "post_time": f"1{2 + r_i}:00",
                    "yg_no": r_i,
                    "cls": "ŞARTLI",
                    "breed": "Ingiliz",
                    "distance": 1400,
                    "surface": "Çim",
                    "status": "result",
                }
            )
            agf_close_vals = [42.0, 26.0, 18.0, 14.0]
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
        conn.commit()
    finally:
        conn.close()

    fconn = forward_v5.init_out_db(fwd_db)
    try:
        for r_i in range(1, 7):
            d_str = "2026-11-15" if r_i <= 2 else "2026-11-23"
            rid = f"{d_str}_Ankara_{r_i}"
            c_at = f"{d_str}T1{2 + r_i - 1}:55:00+03:00"
            p_v5 = [0.40, 0.30, 0.20, 0.10] if r_i % 2 == 1 else [0.34, 0.36, 0.18, 0.12]
            p_v6 = [0.44, 0.28, 0.18, 0.10] if r_i % 2 == 1 else [0.30, 0.42, 0.17, 0.11]
            p_v7 = [0.46, 0.27, 0.17, 0.10] if r_i % 2 == 1 else [0.28, 0.44, 0.17, 0.11]
            p_v8 = [0.50, 0.25, 0.15, 0.10] if r_i % 2 == 1 else [0.25, 0.48, 0.16, 0.11]

            if r_i <= 2:
                model_probs = (("v5_sgr_all", p_v5), ("v6_e5", p_v6))
            else:
                model_probs = (("v6_e5", p_v6), ("v7_tcjp", p_v7), ("v8_an", p_v8))

            for pno in range(1, 5):
                for mv, probs in model_probs:
                    fconn.execute(
                        """
                        INSERT INTO predictions_v5 (
                            race_id, prog_no, model_version, created_at, minutes_to_post,
                            p_win, agf_used, s_cov, g_cov
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (rid, pno, mv, c_at, 5.0, probs[pno - 1], 25.0, 1.0, 0.75),
                    )
        fconn.commit()
    finally:
        fconn.close()

    rep_out = tmp_path / "rep_active_triad.md"
    assert (
        forward_v5_report.main(["--db", str(main_db), "--forward-db", str(fwd_db), "--out", str(rep_out)])
        == 0
    )
    md = rep_out.read_text(encoding="utf-8")

    # V8 era has 4 settled races (without v5!), while legacy archive has 2 races and active V10 / V9 quads have 0
    assert (
        "Aktif Canlı Eşli Karşılaştırma Koşu Sayısı "
        "(`v7_tcjp` ∩ `v8_an` ∩ `v9_kssb` ∩ `v10_hlb` ∩ `AGF`):** `0`"
    ) in md
    assert (
        "V9 Dönemi Eşli Karşılaştırma Koşu Sayısı "
        "(`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `v9_kssb` ∩ `AGF`):** `0`"
    ) in md
    assert "V8 Dönemi Eşli Karşılaştırma Koşu Sayısı (`v6_e5` ∩ `v7_tcjp` ∩ `v8_an` ∩ `AGF`):** `4`" in md
    assert "Üçlü Eşli Karşılaştırma Koşu Sayısı (`v5_sgr_all` ∩ `v6_e5` ∩ `AGF`):** `2`" in md
    assert "`v8_an − v7_tcjp`" in md
    assert "`v8_an − v6_e5`" in md
    assert "`v8_an − AGF`" in md
    assert "`v6_e5 − v5_sgr_all`" in md
    assert "| `v8_an` | 4 |" in md
    assert "| `v6_e5` | 6 |" in md
