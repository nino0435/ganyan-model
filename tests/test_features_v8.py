"""Unit, hand-calculation, and strict temporal leakage tests for ganyan/features_v8.py."""
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan.features_v7 import get_v7_cols
from ganyan.features_v8 import (
    A_COLS,
    K_COLS,
    N_COLS,
    V8_BLOCK_COLS,
    attach_A,
    attach_K,
    attach_N,
    attach_v8,
    get_v8_cols,
)


def test_v8_column_definitions_and_counts():
    assert len(A_COLS) == 10
    assert len(K_COLS) == 7
    assert len(N_COLS) == 12
    assert set(V8_BLOCK_COLS) == {"A", "K", "N"}

    v7_cols = set(get_v7_cols(("T", "C", "J", "P"), with_program=False))
    assert len(v7_cols) == 100
    v8_only = set(A_COLS) | set(K_COLS) | set(N_COLS)
    assert len(v8_only) == 29
    assert v7_cols.isdisjoint(v8_only)

    all_cols = get_v8_cols(("A", "K", "N"), with_program=False)
    assert len(all_cols) == 129
    assert len(set(all_cols)) == 129


def test_attach_A_hand_calculated_values_and_90d_boundaries():
    # Horse H_MAIN trajectory (active settled on past days, scheduled/unsettled on target D='2026-06-30'):
    # D - 91 = 2026-03-31 (outside [D-90, D))
    # D - 90 = 2026-04-01 (exact boundary INSIDE [D-90, D))
    # Target D = 2026-06-30
    df = pd.DataFrame(
        [
            # 1) 2025-10-01: sf=10, fpct=0.0, hp=60 (first career start -> h_layoff_run_no=NaN)
            {
                "race_id": "2025-10-01_Ankara_1",
                "date": "2025-10-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 60.0,
                "age": 4,
                "finish": 1,
                "sf": 10.0,
                "fpct": 0.0,
                "h_n": 0,
                "scratched": 0,
            },
            # Rival in race 1
            {
                "race_id": "2025-10-01_Ankara_1",
                "date": "2025-10-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_OTH",
                "hp": 50.0,
                "age": 6,
                "finish": 2,
                "sf": 5.0,
                "fpct": 1.0,
                "h_n": 4,
                "scratched": 0,
            },
            # 2) 2025-10-20 (gap=19d -> layoff=0.0): sf=20 (NEW PEAK!), hp=70 (NEW PEAK!)
            {
                "race_id": "2025-10-20_Ankara_1",
                "date": "2025-10-20",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 70.0,
                "age": 4,
                "finish": 1,
                "sf": 20.0,
                "fpct": 0.2,
                "h_n": 1,
                "scratched": 0,
            },
            # 3) 2026-03-31 (D-91, gap=162d >= 90 -> layoff=1.0): sf=14, fpct=0.4, hp=65
            {
                "race_id": "2026-03-31_Ankara_1",
                "date": "2026-03-31",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 65.0,
                "age": 5,
                "finish": 2,
                "sf": 14.0,
                "fpct": 0.4,
                "h_n": 2,
                "scratched": 0,
            },
            # 4) 2026-04-01 (D-90, gap=1d -> layoff=2.0 because prev_gap=162 >= 90 and curr=1 < 60): sf=12, fpct=0.6
            {
                "race_id": "2026-04-01_Ankara_1",
                "date": "2026-04-01",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 64.0,
                "age": 5,
                "finish": 3,
                "sf": 12.0,
                "fpct": 0.6,
                "h_n": 3,
                "scratched": 0,
            },
            # 5) 2026-04-21 (gap=20d < 60 -> layoff=3.0 because prev=1<60 and prev2=162>=90): sf=10, fpct=0.8
            {
                "race_id": "2026-04-21_Ankara_1",
                "date": "2026-04-21",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 62.0,
                "age": 5,
                "finish": 4,
                "sf": 10.0,
                "fpct": 0.8,
                "h_n": 4,
                "scratched": 0,
            },
            # 6) 2026-05-11 (gap=20d -> layoff=0.0): sf=8, fpct=1.0
            {
                "race_id": "2026-05-11_Ankara_1",
                "date": "2026-05-11",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 60.0,
                "age": 5,
                "finish": 5,
                "sf": 8.0,
                "fpct": 1.0,
                "h_n": 5,
                "scratched": 0,
            },
            # 7) Target D = 2026-06-30 (gap=50d -> layoff=0.0): hp=56
            {
                "race_id": "2026-06-30_Ankara_1",
                "date": "2026-06-30",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_MAIN",
                "hp": 56.0,
                "age": 5,
                "finish": np.nan,
                "sf": np.nan,
                "fpct": np.nan,
                "h_n": 6,
                "scratched": 0,
            },
            # Rival on target D (age=3, h_n=2)
            {
                "race_id": "2026-06-30_Ankara_1",
                "date": "2026-06-30",
                "city": "Ankara",
                "race_no": 1,
                "horse_key": "H_RIVAL",
                "hp": 50.0,
                "age": 3,
                "finish": np.nan,
                "sf": np.nan,
                "fpct": np.nan,
                "h_n": 2,
                "scratched": 0,
            },
        ]
    )

    out = attach_A(df).set_index("race_id")

    # Race 1 (debut): layoff=NaN, hp_drop=NaN, days_since_peak_sf=NaN, age_rel = 4 - 5 = -1, h_n_rel = 0 - 2 = -2
    r1 = out.loc["2025-10-01_Ankara_1"]
    r1_main = r1[r1["horse_key"] == "H_MAIN"].iloc[0]
    assert np.isnan(r1_main["h_layoff_run_no"])
    assert np.isnan(r1_main["hp_drop_from_peak"])
    assert np.isnan(r1_main["days_since_peak_sf"])
    assert r1_main["h_starts_90d"] == pytest.approx(0.0)
    assert r1_main["age_rel"] == pytest.approx(-1.0)
    assert r1_main["h_n_rel"] == pytest.approx(-2.0)

    # Check layoff progression through races 2..6
    assert out.loc["2025-10-20_Ankara_1", "h_layoff_run_no"] == pytest.approx(0.0)
    assert out.loc["2025-10-20_Ankara_1", "starts_since_peak_sf"] == pytest.approx(0.0)
    assert out.loc["2026-03-31_Ankara_1", "h_layoff_run_no"] == pytest.approx(1.0)
    assert out.loc["2026-04-01_Ankara_1", "h_layoff_run_no"] == pytest.approx(2.0)
    assert out.loc["2026-04-21_Ankara_1", "h_layoff_run_no"] == pytest.approx(3.0)
    assert out.loc["2026-05-11_Ankara_1", "h_layoff_run_no"] == pytest.approx(0.0)

    # Target day 2026-06-30 for H_MAIN:
    r_d = out.loc["2026-06-30_Ankara_1"]
    m_d = r_d[r_d["horse_key"] == "H_MAIN"].iloc[0]
    # Peak hp was 70.0; today 56.0 -> drop = 14.0, ratio = 56/70 = 0.8
    assert m_d["hp_drop_from_peak"] == pytest.approx(14.0)
    assert m_d["hp_peak_ratio"] == pytest.approx(0.8)
    # Peak sf was 20.0 on 2025-10-20 -> (2026-06-30 - 2025-10-20).days = 253
    assert m_d["days_since_peak_sf"] == pytest.approx(253.0)
    # After 2025-10-20 peak, horse ran 4 starts (03-31, 04-01, 04-21, 05-11) -> starts_since_peak_sf = 4.0
    assert m_d["starts_since_peak_sf"] == pytest.approx(4.0)
    # Last 3 sf: mean([12, 10, 8]) = 10.0; prior 3 sf: mean([10, 20, 14]) = 14.6667 -> trend = -14/3
    assert m_d["sf_trend_3v3"] == pytest.approx(10.0 - (44.0 / 3.0))
    # Last 3 fpct: mean([0.6, 0.8, 1.0]) = 0.8; prior 3 fpct: mean([0.0, 0.2, 0.4]) = 0.2 -> trend = +0.6
    assert m_d["fpct_trend_3v3"] == pytest.approx(0.6)
    # [D-90, D) = [2026-04-01, 2026-06-30) -> includes 04-01, 04-21, 05-11 (3 starts), excludes 03-31 (D-91)
    assert m_d["h_starts_90d"] == pytest.approx(3.0)
    assert m_d["age_rel"] == pytest.approx(1.0)
    assert m_d["h_n_rel"] == pytest.approx(2.0)


def test_attach_K_hand_calculated_jockey_prime_and_windows():
    # Jockey J_A runs on:
    # - 2024-06-30: 1st appearance (win=1), jockey name="J_A AP"
    # - 2025-12-01: win=0 (< 180d cutoff from 2026-06-30? 2026-06-30 - 180d = 2026-01-01; within 365d!)
    # - 2026-01-01: win=1 (exact 180d boundary INCLUDED in [D-180, D))
    # - 2026-06-15: win=1 (inside 30d window [2026-05-31, 2026-06-30))
    # - Target 2026-06-30: jockey="J_A" (graduated, no AP), against J_NEW debuting on 2026-06-30
    df = pd.DataFrame(
        [
            {"race_id": "2024-06-30_A_1", "date": "2024-06-30", "city": "A", "race_no": 1, "horse_key": "H1", "jockey": "J_A AP", "finish": 1, "scratched": 0},
            {"race_id": "2025-12-01_A_1", "date": "2025-12-01", "city": "A", "race_no": 1, "horse_key": "H2", "jockey": "J_A AP", "finish": 2, "scratched": 0},
            {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "H3", "jockey": "J_A", "finish": 1, "scratched": 0},
            {"race_id": "2026-06-15_A_1", "date": "2026-06-15", "city": "A", "race_no": 1, "horse_key": "H4", "jockey": "J_A", "finish": 1, "scratched": 0},
            {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H5", "jockey": "J_A", "finish": np.nan, "scratched": 0},
            {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H6", "jockey": "J_NEW AP", "finish": np.nan, "scratched": 0},
        ]
    )

    out = attach_K(df)
    r_d = out[out["race_id"] == "2026-06-30_A_1"].set_index("horse_key")

    ja = r_d.loc["H5"]
    jnew = r_d.loc["H6"]

    exp_cy = (pd.Timestamp("2026-06-30") - pd.Timestamp("2024-06-30")).days / 365.25
    assert ja["j_career_yrs"] == pytest.approx(exp_cy)
    assert jnew["j_career_yrs"] == pytest.approx(0.0)
    assert ja["j_is_ap"] == pytest.approx(0.0)
    assert jnew["j_is_ap"] == pytest.approx(1.0)
    assert ja["j_career_yrs_rel"] == pytest.approx(0.5 * exp_cy)
    assert jnew["j_career_yrs_rel"] == pytest.approx(-0.5 * exp_cy)

    # 30d window: 2026-06-15 -> n=1, w=1 -> (1+1)/(1+10) = 2/11
    # 180d window: 2026-01-01 (exact D-180) + 2026-06-15 -> n=2, w=2 -> (2+1)/(2+10) = 3/12 = 0.25
    # 365d window: 2025-12-01 + 2026-01-01 + 2026-06-15 -> n=3, w=2 -> (2+2)/(3+20) = 4/23
    # Career prior < D: 4 starts, 3 wins -> (3+2)/(4+20) = 5/24
    wr30 = 2.0 / 11.0
    wr180 = 3.0 / 12.0
    wr365 = 4.0 / 23.0
    wrcar = 5.0 / 24.0
    assert ja["j_wr_180d"] == pytest.approx(wr180)
    assert ja["j_wr_365d"] == pytest.approx(wr365)
    assert ja["j_wr_trend_180v_car"] == pytest.approx(wr180 - wrcar)
    assert ja["j_wr_30v365"] == pytest.approx(wr30 - wr365)


def test_attach_N_network_corporate_filter_and_sleeping_wakeup():
    # History + Target race testing:
    # - Official ekuri: OWNER_A runs H1 (agf=0.40) and H2 (agf=0.10)
    # - Hidden family ekuri: AHMET YILMAZ (agf=0.20) & MEHMET YILMAZ (agf=0.05) with SAME trainer TRN_FAM
    # - Corporate surname exclusion: ALPHA LTD. & BETA LTD. with SAME trainer TRN_CORP -> fam_hidden_ekuri = 0.0!
    # - Sleeping wake-up: H_SLEEP finished 8th & 9th with agf 0.03 & 0.05, today agf=0.15
    rows = [
        # Past race 1 (t-2): H_SLEEP finishes 8th with agf=0.03; TRN_FAM+J1 win
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "H_SLEEP", "owner": "O_SL", "trainer": "TRN_FAM", "jockey": "J1", "finish": 8, "agf_share": 0.03, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "H_WIN1", "owner": "O_A", "trainer": "TRN_FAM", "jockey": "J1 AP", "finish": 1, "agf_share": 0.40, "scratched": 0},
        # Past race 2 (t-1): H_SLEEP finishes 9th with agf=0.05; J1 loses with OTHER trainer
        {"race_id": "2026-06-15_A_1", "date": "2026-06-15", "city": "A", "race_no": 1, "horse_key": "H_SLEEP", "owner": "O_SL", "trainer": "TRN_FAM", "jockey": "J1", "finish": 9, "agf_share": 0.05, "scratched": 0},
        {"race_id": "2026-06-15_A_1", "date": "2026-06-15", "city": "A", "race_no": 1, "horse_key": "H_OTH", "owner": "O_B", "trainer": "TRN_OTHER", "jockey": "J1", "finish": 4, "agf_share": 0.25, "scratched": 0},
        # Target race 2026-06-30
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H1", "owner": "OWNER A", "trainer": "TRN_OWN", "jockey": "J2", "finish": np.nan, "agf_share": 0.35, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H2", "owner": "OWNER A", "trainer": "TRN_OWN", "jockey": "J3", "finish": np.nan, "agf_share": 0.10, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_FAM1", "owner": "AHMET YILMAZ", "trainer": "TRN_FAM", "jockey": "J1", "finish": np.nan, "agf_share": 0.20, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_SLEEP", "owner": "MEHMET YILMAZ", "trainer": "TRN_FAM", "jockey": "J1", "finish": np.nan, "agf_share": 0.15, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_CORP1", "owner": "ALPHA LTD.", "trainer": "TRN_CORP", "jockey": "J4", "finish": np.nan, "agf_share": 0.12, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_CORP2", "owner": "BETA A.Ş.", "trainer": "TRN_CORP", "jockey": "J5", "finish": np.nan, "agf_share": 0.08, "scratched": 0},
    ]
    out = attach_N(pd.DataFrame(rows))
    rd = out[out["race_id"] == "2026-06-30_A_1"].set_index("horse_key")

    # Official ekuri
    assert rd.loc["H1", "own_mates_cnt"] == pytest.approx(1.0)
    assert rd.loc["H1", "own_is_sub_agf"] == pytest.approx(0.0)
    assert rd.loc["H1", "own_mate_agf"] == pytest.approx(0.10)
    assert rd.loc["H2", "own_mates_cnt"] == pytest.approx(1.0)
    assert rd.loc["H2", "own_is_sub_agf"] == pytest.approx(1.0)
    assert rd.loc["H2", "own_mate_agf"] == pytest.approx(0.35)

    # Hidden family ekuri (YILMAZ + TRN_FAM) vs Corporate non-match
    assert rd.loc["H_FAM1", "fam_hidden_ekuri"] == pytest.approx(1.0)
    assert rd.loc["H_FAM1", "trn_mates_cnt"] == pytest.approx(1.0)
    assert rd.loc["H_FAM1", "trn_is_sub_agf"] == pytest.approx(0.0)
    assert rd.loc["H_SLEEP", "fam_hidden_ekuri"] == pytest.approx(1.0)
    assert rd.loc["H_SLEEP", "trn_is_sub_agf"] == pytest.approx(1.0)
    assert rd.loc["H_CORP1", "fam_hidden_ekuri"] == pytest.approx(0.0)
    assert rd.loc["H_CORP2", "fam_hidden_ekuri"] == pytest.approx(0.0)
    assert rd.loc["H_CORP1", "trn_mates_cnt"] == pytest.approx(1.0)

    # Prior Trainer-Jockey synergy: (TRN_FAM, J1) ran 3 prior starts < D (H_SLEEP 8th, H_WIN1 1st, H_SLEEP 9th) -> 1 win / 3 starts
    # J1 overall prior < D: 4 starts (1 win) -> j_wr_prior = (1+2)/(4+20) = 3/24 = 0.125
    exp_tj_wr = (1.0 + 1.0) / (3.0 + 10.0)
    assert rd.loc["H_FAM1", "tj_n"] == pytest.approx(3.0)
    assert rd.loc["H_FAM1", "tj_wr"] == pytest.approx(exp_tj_wr)
    assert rd.loc["H_FAM1", "tj_wr_synergy"] == pytest.approx(exp_tj_wr - 0.125)

    # Sleeping horse wake-up
    prev2_m = 0.5 * (0.03 + 0.05)  # 0.04
    exp_surge = math.log((0.15 + 0.005) / (prev2_m + 0.005))
    assert rd.loc["H_SLEEP", "agf_surge_ratio"] == pytest.approx(exp_surge)
    assert rd.loc["H_SLEEP", "sleep_wakeup_flag"] == pytest.approx(1.0)
    assert np.isnan(rd.loc["H1", "agf_surge_ratio"])
    assert np.isnan(rd.loc["H1", "sleep_wakeup_flag"])


def test_v8_strict_temporal_leakage_and_same_day_isolation():
    dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01", "2026-05-20", "2026-06-15", "2026-07-01"]
    rows_a = []
    for i, d in enumerate(dates):
        for rno in (1, 2):
            rid = f"{d}_Ankara_{rno}"
            rows_a.append(
                {
                    "race_id": rid,
                    "date": d,
                    "city": "Ankara",
                    "race_no": rno,
                    "horse_key": "H_A" if rno == 1 else "H_B",
                    "owner": "ALİ DEMİR" if rno == 1 else "VELİ DEMİR",
                    "trainer": "T_SHARED",
                    "jockey": "J_A AP" if i % 2 == 0 else "J_A",
                    "age": 4 if rno == 1 else 6,
                    "hp": 60.0 + i,
                    "h_n": i,
                    "finish": 8 if rno == 1 else 2,
                    "sf": 10.0 + i,
                    "fpct": 0.9 if rno == 1 else 0.2,
                    "agf_share": 0.04 if i < 6 else 0.25,
                    "scratched": 0,
                }
            )
            # Same horse H_A also enters race 2 ONLY on 2026-06-15 to test same-day isolation!
            if d == "2026-06-15" and rno == 2:
                rows_a.append(
                    {
                        "race_id": rid,
                        "date": d,
                        "city": "Ankara",
                        "race_no": rno,
                        "horse_key": "H_A",
                        "owner": "ALİ DEMİR",
                        "trainer": "T_SHARED",
                        "jockey": "J_A",
                        "age": 4,
                        "hp": 66.0,
                        "h_n": i,
                        "finish": 1,
                        "sf": 25.0,
                        "fpct": 0.0,
                        "agf_share": 0.25,
                        "scratched": 0,
                    }
                )

    df_orig = pd.DataFrame(rows_a)
    df_mut = df_orig.copy()
    # Mutate all outcomes on >= D (2026-06-15) and hp/agf strictly > D (2026-07-01)
    mask_ge_d = pd.to_datetime(df_mut["date"]) >= pd.Timestamp("2026-06-15")
    mask_gt_d = pd.to_datetime(df_mut["date"]) > pd.Timestamp("2026-06-15")
    df_mut.loc[mask_ge_d, "finish"] = 1
    df_mut.loc[mask_ge_d, "sf"] = -99.0
    df_mut.loc[mask_ge_d, "fpct"] = 0.0
    df_mut.loc[mask_gt_d, "hp"] = 999.0
    df_mut.loc[mask_gt_d, "agf_share"] = 0.95

    out_orig = attach_v8(df_orig, blocks=("A", "K", "N"))
    out_mut = attach_v8(df_mut, blocks=("A", "K", "N"))

    all_v8_cols = A_COLS + K_COLS + N_COLS
    le_d = pd.to_datetime(out_orig["date"]) <= pd.Timestamp("2026-06-15")
    for col in all_v8_cols:
        s1 = out_orig.loc[le_d, col].to_numpy(dtype=np.float64)
        s2 = out_mut.loc[le_d, col].to_numpy(dtype=np.float64)
        assert np.array_equal(s1, s2, equal_nan=True), f"Temporal leakage detected in {col}!"

    # Same-day isolation check on 2026-06-15 for H_A across race 1 & race 2
    ha_d = out_orig[(out_orig["date"] == "2026-06-15") & (out_orig["horse_key"] == "H_A")]
    assert len(ha_d) == 2
    for col in [
        "hp_drop_from_peak",
        "days_since_peak_sf",
        "starts_since_peak_sf",
        "sf_trend_3v3",
        "h_starts_90d",
        "h_layoff_run_no",
        "j_career_yrs",
        "j_wr_180d",
        "tj_n",
        "tj_wr",
        "agf_surge_ratio",
        "sleep_wakeup_flag",
    ]:
        v0, v1 = ha_d[col].iloc[0], ha_d[col].iloc[1]
        assert (np.isnan(v0) and np.isnan(v1)) or np.isclose(v0, v1), f"Same-day mismatch in {col}"


def test_v8_empty_and_missing_columns_resilience():
    empty_df = pd.DataFrame(columns=["race_id", "date", "horse_key"])
    out_empty = attach_v8(empty_df, blocks=("A", "K", "N"))
    assert len(out_empty) == 0
    for c in A_COLS + K_COLS + N_COLS:
        assert c in out_empty.columns

    minimal = pd.DataFrame([{"race_id": "2026-06-15_A_1", "date": "2026-06-15", "horse_key": "H1"}])
    out_min = attach_v8(minimal, blocks=("A", "K", "N"))
    assert len(out_min) == 1
    nan_when_h1 = [c for c in A_COLS if c not in ("h_starts_90d", "h_n_rel")] + K_COLS + [
        "own_is_sub_agf",
        "own_mate_agf",
        "trn_is_sub_agf",
        "tj_n",
        "tj_wr",
        "tj_wr_synergy",
        "oj_wr",
        "agf_surge_ratio",
        "sleep_wakeup_flag",
    ]
    for c in nan_when_h1:
        assert np.isnan(out_min.loc[0, c]), f"{c} should be NaN"
    assert out_min.loc[0, "h_starts_90d"] == pytest.approx(0.0)
    assert out_min.loc[0, "h_n_rel"] == pytest.approx(0.0)
    for c in ("own_mates_cnt", "trn_mates_cnt", "fam_hidden_ekuri"):
        assert out_min.loc[0, c] == pytest.approx(0.0)

    # Missing horse_key -> h_starts_90d and h_n_rel also become NaN
    no_hk = pd.DataFrame([{"race_id": "2026-06-15_A_1", "date": "2026-06-15", "horse_key": None}])
    out_no_hk = attach_v8(no_hk, blocks=("A", "K", "N"))
    assert np.isnan(out_no_hk.loc[0, "h_starts_90d"])
    assert np.isnan(out_no_hk.loc[0, "h_n_rel"])
