"""Unit, hand-calculation, edge-case, and strict temporal leakage tests for ganyan/features_v9.py."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan.features_v9 import (
    BIAS_COLS,
    BIAS_PRIOR_N,
    DAY_COLS,
    DAY_PRIOR_N,
    KEY_COLS,
    KEY_PRIOR_N,
    KEY_PRIOR_W,
    SHIP_AWAY_PRIOR_N,
    SHIP_COLS,
    STAB_COLS,
    STAB_PRIOR_14,
    STAB_PRIOR_28,
    V9_BLOCK_COLS,
    V9_CANDIDATE_BLOCKS,
    WORK_COLS,
    attach_BIAS,
    attach_DAY,
    attach_KEY,
    attach_SHIP,
    attach_STAB,
    attach_WORK,
    attach_v9,
    get_v9_cols,
)
from ganyan.model_v8 import V8_CONFIG


def test_v9_column_definitions_and_no_overlap():
    assert len(KEY_COLS) == 6
    assert len(SHIP_COLS) == 4
    assert len(STAB_COLS) == 5
    assert len(WORK_COLS) == 4
    assert len(BIAS_COLS) == 2
    assert len(DAY_COLS) == 3
    assert V9_CANDIDATE_BLOCKS == ("KEY", "SHIP", "STAB", "WORK", "BIAS")
    assert set(V9_BLOCK_COLS) == {"KEY", "SHIP", "STAB", "WORK", "BIAS", "DAY"}

    base_v8 = list(V8_CONFIG["feature_cols"])
    assert len(base_v8) == 122
    assert get_v9_cols(()) == base_v8

    v9_only = [c for blk in V9_BLOCK_COLS for c in V9_BLOCK_COLS[blk]]
    assert len(v9_only) == 24
    assert len(set(v9_only)) == 24
    assert set(base_v8).isdisjoint(v9_only)

    all_cand = get_v9_cols(V9_CANDIDATE_BLOCKS)
    assert len(all_cand) == 122 + 21
    assert len(set(all_cand)) == 143


def test_attach_KEY_hand_calc_ahead_behind_and_exclude_same_day_win():
    # Horse H0 runs in 3 prior races (R1 on 05-01, R2 on 05-15, R3 on 06-01), then target race on D = 2026-06-30.
    # In R3 (2026-06-01):
    #   - R_A (fin=1, AHEAD of H0 which was 2nd): subsequently runs on 06-15 (fin=1, INCLUDED) and 06-30 (ignored)
    #   - H0  (fin=2)
    #   - R_B (fin=3, BEHIND H0): does NOT run again before 06-30, wins ON 2026-06-30 (MUST BE EXCLUDED!)
    #   - R_C (fin=4, BEHIND H0): runs on 06-20 (fin=5, lost -> INCLUDED as ran, not won)
    #   - R_SCR (scratched=1, finish=NaN): MUST BE IGNORED
    # Earlier races for H0 (R1 05-01: R_E won 05-20; R2 05-15: R_D won 06-10) -> check key_wr_m3.
    rows = [
        # R1 (2026-05-01): H0 fin=1 (won! -> ahead on R1 would be NaN), R_E fin=2
        {"race_id": "2026-05-01_A_1", "date": "2026-05-01", "city": "A", "race_no": 1, "horse_key": "H0", "finish": 1, "scratched": 0},
        {"race_id": "2026-05-01_A_1", "date": "2026-05-01", "city": "A", "race_no": 1, "horse_key": "R_E", "finish": 2, "scratched": 0},
        # R_E wins on 2026-05-20
        {"race_id": "2026-05-20_A_1", "date": "2026-05-20", "city": "A", "race_no": 1, "horse_key": "R_E", "finish": 1, "scratched": 0},
        # R2 (2026-05-15): H0 fin=3, R_D fin=1
        {"race_id": "2026-05-15_A_1", "date": "2026-05-15", "city": "A", "race_no": 1, "horse_key": "H0", "finish": 3, "scratched": 0},
        {"race_id": "2026-05-15_A_1", "date": "2026-05-15", "city": "A", "race_no": 1, "horse_key": "R_D", "finish": 1, "scratched": 0},
        # R_D wins on 2026-06-10
        {"race_id": "2026-06-10_A_1", "date": "2026-06-10", "city": "A", "race_no": 1, "horse_key": "R_D", "finish": 1, "scratched": 0},
        # R3 (2026-06-01): H0 fin=2 against R_A(1), R_B(3), R_C(4), plus scratched R_SCR
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "R_A", "finish": 1, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "H0", "finish": 2, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "R_B", "finish": 3, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "R_C", "finish": 4, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "R_SCR", "finish": np.nan, "scratched": 1},
        # Subsequent runs in (06-01, 06-30): R_A wins 06-15, R_C loses 06-20
        {"race_id": "2026-06-15_A_1", "date": "2026-06-15", "city": "A", "race_no": 1, "horse_key": "R_A", "finish": 1, "scratched": 0},
        {"race_id": "2026-06-20_A_1", "date": "2026-06-20", "city": "A", "race_no": 1, "horse_key": "R_C", "finish": 5, "scratched": 0},
        # Target day D = 2026-06-30: R_B WINS earlier on D (must NEVER count for H0 on D!)
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "R_B", "finish": 1, "scratched": 0},
        {"race_id": "2026-06-30_A_2", "date": "2026-06-30", "city": "A", "race_no": 2, "horse_key": "H0", "finish": np.nan, "scratched": 0},
        # On 2026-05-15 H0's lag-1 was R1 where H0 won (finish=1) -> key_ahead_wr must be NaN!
    ]
    out = attach_KEY(pd.DataFrame(rows))
    h0_target = out[(out["race_id"] == "2026-06-30_A_2") & (out["horse_key"] == "H0")].iloc[0]

    # R3: R_A (ran=1, won=1) + R_C (ran=1, won=0); R_B's win on D excluded -> ran=2, won=1
    assert h0_target["key_n_ran"] == pytest.approx(2.0)
    assert h0_target["key_n_won"] == pytest.approx(1.0)
    exp_wr3 = (1.0 + KEY_PRIOR_W) / (2.0 + KEY_PRIOR_N)
    exp_ah3 = (1.0 + KEY_PRIOR_W) / (1.0 + KEY_PRIOR_N)
    exp_bh3 = (0.0 + KEY_PRIOR_W) / (1.0 + KEY_PRIOR_N)
    assert h0_target["key_wr"] == pytest.approx(exp_wr3)
    assert h0_target["key_ahead_wr"] == pytest.approx(exp_ah3)
    assert h0_target["key_behind_wr"] == pytest.approx(exp_bh3)

    # R2: R_D (1 ran, 1 won), R1: R_E (1 ran, 1 won) -> wr2 = wr1 = (1+0.5)/(1+3) = 1.5/4 = 0.375
    exp_wr12 = (1.0 + KEY_PRIOR_W) / (1.0 + KEY_PRIOR_N)
    assert h0_target["key_wr_m3"] == pytest.approx((exp_wr3 + exp_wr12 + exp_wr12) / 3.0)

    # Check H0 on 2026-05-15 (lag-1 was R1 where H0 WON -> key_ahead_wr is NaN, key_n_ran=0 because R_E didn't run before 05-15)
    h0_r2 = out[(out["race_id"] == "2026-05-15_A_1") & (out["horse_key"] == "H0")].iloc[0]
    assert h0_r2["key_n_ran"] == pytest.approx(0.0)
    assert h0_r2["key_n_won"] == pytest.approx(0.0)
    assert np.isnan(h0_r2["key_wr"])
    assert np.isnan(h0_r2["key_ahead_wr"])
    assert np.isnan(h0_r2["key_behind_wr"])


def test_attach_SHIP_home_city_min10_away_resid_and_first_ship():
    # Trainer T1 has 10 prior settled starts in [D-365, D) relative to D = 2026-06-30:
    # - 8 starts in Istanbul, 2 away starts in Ankara (one win w/ agf=0.20, one loss w/ agf=0.30).
    # Trainer T_SMALL has only 9 starts -> trn_away & trn_city_share_365d MUST be NaN.
    # Horse H_OLD ran before in Istanbul, NEVER in Ankara -> on D in Ankara, h_ship_first == 1.0!
    # Horse H_NEW debuts on D -> h_ship_first MUST be NaN!
    rows = []
    # 8 home starts in Istanbul (using lower/mixed case to test normalization)
    for i in range(8):
        d = (pd.Timestamp("2025-10-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({
            "race_id": f"{d}_İstanbul_1",
            "date": d,
            "city": "İstanbul" if i % 2 == 0 else "İSTANBUL",
            "race_no": 1,
            "horse_key": "H_OLD" if i == 0 else f"H_I{i}",
            "trainer": "T1",
            "finish": 4,
            "agf_share": 0.15,
            "scratched": 0,
        })
    # 2 away starts in Ankara for T1
    rows.append({
        "race_id": "2026-02-01_Ankara_1",
        "date": "2026-02-01",
        "city": "Ankara",
        "race_no": 1,
        "horse_key": "H_AW1",
        "trainer": "T1",
        "finish": 1,
        "agf_share": 0.20,
        "scratched": 0,
    })
    rows.append({
        "race_id": "2026-03-01_Ankara_1",
        "date": "2026-03-01",
        "city": "Ankara",
        "race_no": 1,
        "horse_key": "H_AW2",
        "trainer": "T1",
        "finish": 5,
        "agf_share": 0.30,
        "scratched": 0,
    })
    # Wait: notice on 2026-02-01 & 2026-03-01, T1 only had 8 & 9 prior starts (< 10), so those 2 did not have trn_away==1!
    # Put 10 home starts BEFORE away starts so T1 already had home_city=Istanbul when running away on 2026-02-01!
    rows_clean = []
    for i in range(10):
        d = (pd.Timestamp("2025-10-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        rows_clean.append({
            "race_id": f"{d}_İstanbul_1",
            "date": d,
            "city": "İstanbul" if i % 2 == 0 else "İSTANBUL",
            "race_no": 1,
            "horse_key": "H_OLD" if i == 0 else f"H_I{i}",
            "trainer": "T1",
            "finish": 4,
            "agf_share": 0.15,
            "scratched": 0,
        })
    rows_clean.extend([
        {
            "race_id": "2026-02-01_Ankara_1",
            "date": "2026-02-01",
            "city": "Ankara",
            "race_no": 1,
            "horse_key": "H_AW1",
            "trainer": "T1",
            "finish": 1,
            "agf_share": 0.20,
            "scratched": 0,
        },
        {
            "race_id": "2026-03-01_Ankara_1",
            "date": "2026-03-01",
            "city": "Ankara",
            "race_no": 1,
            "horse_key": "H_AW2",
            "trainer": "T1",
            "finish": 5,
            "agf_share": 0.30,
            "scratched": 0,
        },
    ])
    # Small trainer with 9 starts
    for i in range(9):
        d = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        rows_clean.append({
            "race_id": f"{d}_Bursa_1",
            "date": d,
            "city": "Bursa",
            "race_no": 1,
            "horse_key": f"H_S{i}",
            "trainer": "T_SMALL",
            "finish": 2,
            "agf_share": 0.10,
            "scratched": 0,
        })

    # Target day 2026-06-30
    rows_clean.extend([
        {
            "race_id": "2026-06-30_Ankara_1",
            "date": "2026-06-30",
            "city": "Ankara",
            "race_no": 1,
            "horse_key": "H_OLD",
            "trainer": "T1",
            "finish": np.nan,
            "agf_share": 0.25,
            "scratched": 0,
        },
        {
            "race_id": "2026-06-30_İstanbul_2",
            "date": "2026-06-30",
            "city": "İstanbul",
            "race_no": 2,
            "horse_key": "H_OLD",
            "trainer": "T1",
            "finish": np.nan,
            "agf_share": 0.30,
            "scratched": 0,
        },
        {
            "race_id": "2026-06-30_Ankara_3",
            "date": "2026-06-30",
            "city": "Ankara",
            "race_no": 3,
            "horse_key": "H_NEW",
            "trainer": "T_SMALL",
            "finish": np.nan,
            "agf_share": 0.10,
            "scratched": 0,
        },
    ])

    out = attach_SHIP(pd.DataFrame(rows_clean)).set_index("race_id")
    away_row = out.loc["2026-06-30_Ankara_1"]
    home_row = out.loc["2026-06-30_İstanbul_2"]
    small_row = out.loc["2026-06-30_Ankara_3"]

    assert away_row["trn_away"] == pytest.approx(1.0)
    assert away_row["trn_city_share_365d"] == pytest.approx(2.0 / 12.0)
    exp_aw_res = ((1.0 - 0.20) + (0.0 - 0.30)) / (2.0 + SHIP_AWAY_PRIOR_N)
    assert away_row["trn_away_resid_730d"] == pytest.approx(exp_aw_res)
    assert away_row["h_ship_first"] == pytest.approx(1.0)

    assert home_row["trn_away"] == pytest.approx(0.0)
    assert home_row["trn_city_share_365d"] == pytest.approx(10.0 / 12.0)
    assert home_row["h_ship_first"] == pytest.approx(0.0)

    assert np.isnan(small_row["trn_away"])
    assert np.isnan(small_row["trn_city_share_365d"])
    assert np.isnan(small_row["h_ship_first"])


def test_attach_STAB_windows_agf_exclusion_and_relative():
    # D = 2026-06-30
    # - 2026-06-01 (D-29 -> OUTSIDE 28d & 14d)
    # - 2026-06-02 (D-28 -> exact INSIDE 28d, OUTSIDE 14d): T1 horse wins (1st/2) with agf=0.10
    # - 2026-06-16 (D-14 -> exact INSIDE 14d & 28d): T1 horse runs 2nd/2 with agf=0.20 (no-AGF extra race on 06-20 excluded from resid)
    rows = [
        # D-29 outside window
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "H1", "trainer": "T1", "finish": 1, "agf_share": 0.05, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "H2", "trainer": "T2", "finish": 2, "agf_share": 0.95, "scratched": 0},
        # D-28 (exact boundary inside 28d): T1 beats favorite T2 -> fpct=0.0, exp_fpct=1.0
        {"race_id": "2026-06-02_A_1", "date": "2026-06-02", "city": "A", "race_no": 1, "horse_key": "H1", "trainer": "T1", "finish": 1, "agf_share": 0.10, "scratched": 0},
        {"race_id": "2026-06-02_A_1", "date": "2026-06-02", "city": "A", "race_no": 1, "horse_key": "H2", "trainer": "T2", "finish": 2, "agf_share": 0.90, "scratched": 0},
        # D-14 (exact boundary inside 14d): T1 2nd/2 with agf=0.20 -> fpct=1.0, exp_fpct=1.0
        {"race_id": "2026-06-16_A_1", "date": "2026-06-16", "city": "A", "race_no": 1, "horse_key": "H1", "trainer": "T1", "finish": 2, "agf_share": 0.20, "scratched": 0},
        {"race_id": "2026-06-16_A_1", "date": "2026-06-16", "city": "A", "race_no": 1, "horse_key": "H2", "trainer": "T2", "finish": 1, "agf_share": 0.80, "scratched": 0},
        # D-10 without AGF -> increments trn_n_28d (=3) but NOT resid!
        {"race_id": "2026-06-20_A_1", "date": "2026-06-20", "city": "A", "race_no": 1, "horse_key": "H1", "trainer": "T1", "finish": 1, "agf_share": np.nan, "scratched": 0},
        # Target D = 2026-06-30
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H1", "trainer": "T1", "finish": np.nan, "agf_share": 0.40, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H2", "trainer": "T2", "finish": np.nan, "agf_share": 0.60, "scratched": 0},
    ]
    out = attach_STAB(pd.DataFrame(rows))
    rd = out[out["race_id"] == "2026-06-30_A_1"].set_index("trainer")

    t1 = rd.loc["T1"]
    t2 = rd.loc["T2"]
    assert t1["trn_n_28d"] == pytest.approx(3.0)
    assert t2["trn_n_28d"] == pytest.approx(2.0)

    # T1 14d: (0 - 0.20) / (1 + 10); T1 28d: ((1 - 0.10) + (0 - 0.20)) / (2 + 15) = +0.70 / 17
    exp_t1_14 = (-0.20) / (1.0 + STAB_PRIOR_14)
    exp_t1_28 = (0.90 - 0.20) / (2.0 + STAB_PRIOR_28)
    exp_t2_28 = (-0.90 + 0.20) / (2.0 + STAB_PRIOR_28)
    assert t1["trn_resid_14d"] == pytest.approx(exp_t1_14)
    assert t1["trn_resid_28d"] == pytest.approx(exp_t1_28)
    assert t2["trn_resid_28d"] == pytest.approx(exp_t2_28)
    assert t1["trn_resid_28d_rel"] == pytest.approx(exp_t1_28 - 0.5 * (exp_t1_28 + exp_t2_28))
    # T1 fpct_resid_28d: ((0.0 - 1.0) + (1.0 - 1.0)) / (2 + 15) = -1.0 / 17
    assert t1["trn_fpct_resid_28d"] == pytest.approx(-1.0 / (2.0 + STAB_PRIOR_28))


def test_attach_WORK_jockey_normalization_apranti_and_source_priority():
    # D = 2026-06-30
    # - H_LF: Race jockey "R.B.DÜNDAR AP"; workout (liderform, 06-25) "ROBİN BORAN DÜNDAR" (DRIVING) + duplicate yenibeygir on 06-25 "WRONG" (dropped!)
    #   and earlier 06-10 "R.B.DÜNDAR"; NEVER raced together (hj_n=0) -> gw_jk_last=1, gw_jk_n30=2, gw_hard_days=5, gw_jk_first_ride=1
    # - H_APR: Last workout 06-28 has jockey="APRANTİ" -> gw_jk_last=NaN, gw_jk_n30=NaN, gw_jk_first_ride=NaN
    # - H_NOMATCH: Race jockey "MÜS.ÇELİK", workout has "MERTCAN ÇELİK" (same surname, WRONG prefix!) and ALLOUT on 04-20 (>60d -> NaN)
    #   and previously raced together (hj_n=2) -> gw_jk_last=0, gw_jk_n30=0, gw_hard_days=NaN, gw_jk_first_ride=0
    df = pd.DataFrame([
        # Past race on 05-01 for H_NOMATCH with MÜS.ÇELİK (so hj_n=1 < D)
        {"race_id": "2026-05-01_A_1", "date": "2026-05-01", "city": "A", "race_no": 1, "horse_key": "H_NOMATCH", "jockey": "MÜS.ÇELİK", "finish": 3, "scratched": 0},
        # Target day 2026-06-30
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_LF", "jockey": "R.B.DÜNDAR AP", "finish": np.nan, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_APR", "jockey": "N.ŞEN", "finish": np.nan, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "A", "race_no": 1, "horse_key": "H_NOMATCH", "jockey": "MÜS.ÇELİK", "finish": np.nan, "scratched": 0},
    ])
    workouts = pd.DataFrame([
        {"source": "yenibeygir", "horse_key": "H_LF", "date": pd.Timestamp("2026-06-25"), "jockey": "YANLIŞ BİNİCİ", "effort": "CANTER"},
        {"source": "liderform", "horse_key": "H_LF", "date": pd.Timestamp("2026-06-25"), "jockey": "ROBİN BORAN DÜNDAR", "effort": "DRIVING"},
        {"source": "liderform", "horse_key": "H_LF", "date": pd.Timestamp("2026-06-10"), "jockey": "R.B.DÜNDAR", "effort": "CANTER"},
        {"source": "liderform", "horse_key": "H_APR", "date": pd.Timestamp("2026-06-28"), "jockey": "APRANTİ", "effort": "ALLOUT"},
        {"source": "yenibeygir", "horse_key": "H_NOMATCH", "date": pd.Timestamp("2026-06-20"), "jockey": "MERTCAN ÇELİK", "effort": "CANTER"},
        {"source": "liderform", "horse_key": "H_NOMATCH", "date": pd.Timestamp("2026-04-20"), "jockey": "MÜS.ÇELİK", "effort": "ALLOUT"},
    ])
    out = attach_WORK(df, v5_tables={"workouts": workouts})
    rd = out[out["race_id"] == "2026-06-30_A_1"].set_index("horse_key")

    r_lf = rd.loc["H_LF"]
    assert r_lf["gw_jk_last"] == pytest.approx(1.0)
    assert r_lf["gw_jk_n30"] == pytest.approx(2.0)
    assert r_lf["gw_hard_days"] == pytest.approx(5.0)
    assert r_lf["gw_jk_first_ride"] == pytest.approx(1.0)

    r_apr = rd.loc["H_APR"]
    assert np.isnan(r_apr["gw_jk_last"])
    assert np.isnan(r_apr["gw_jk_n30"])
    assert np.isnan(r_apr["gw_jk_first_ride"])
    assert r_apr["gw_hard_days"] == pytest.approx(2.0)

    r_no = rd.loc["H_NOMATCH"]
    assert r_no["gw_jk_last"] == pytest.approx(0.0)
    assert r_no["gw_jk_n30"] == pytest.approx(0.0)
    assert np.isnan(r_no["gw_hard_days"])
    assert r_no["gw_jk_first_ride"] == pytest.approx(0.0)


def test_attach_BIAS_distance_bands_quintiles_and_3y_window():
    # Cell: Ankara + Çim + 1400m (band=1) + q5=0 (gate_frac=0.10)
    # Relative to Target D = 2026-06-30 (note 2024 is a leap year):
    # - 2023-06-30 (D-1096 -> OUTSIDE 1095d [D-1095, D)): winner with agf=0.10 (excluded!)
    # - 2023-07-01 (D-1095 -> exact BOUNDARY INSIDE 1095d): winner with agf=0.20 (+0.80)
    # - 2025-05-01 (D < 1095): loser with agf=0.30 (-0.30)
    # Target D = 2026-06-30
    rows = [
        {"race_id": "2023-06-30_A_1", "date": "2023-06-30", "city": "Ankara", "race_no": 1, "horse_key": "H1", "surface": "Çim", "distance": 1400, "gate": 1, "gate_frac": 0.10, "finish": 1, "agf_share": 0.10, "scratched": 0},
        {"race_id": "2023-07-01_A_1", "date": "2023-07-01", "city": "Ankara", "race_no": 1, "horse_key": "H2", "surface": "Çim", "distance": 1400, "gate": 1, "gate_frac": 0.10, "finish": 1, "agf_share": 0.20, "scratched": 0},
        {"race_id": "2025-05-01_A_1", "date": "2025-05-01", "city": "Ankara", "race_no": 1, "horse_key": "H3", "surface": "Çim", "distance": 1400, "gate": 1, "gate_frac": 0.20, "finish": 4, "agf_share": 0.30, "scratched": 0},
        {"race_id": "2026-06-30_A_1", "date": "2026-06-30", "city": "Ankara", "race_no": 1, "horse_key": "H4", "surface": "Çim", "distance": 1400, "gate": 1, "gate_frac": 0.15, "finish": np.nan, "agf_share": 0.25, "scratched": 0},
        # Different distance band (1200 -> band 0) -> bias_n=0, bias_gate_resid=NaN
        {"race_id": "2026-06-30_A_2", "date": "2026-06-30", "city": "Ankara", "race_no": 2, "horse_key": "H5", "surface": "Çim", "distance": 1200, "gate": 1, "gate_frac": 0.15, "finish": np.nan, "agf_share": 0.25, "scratched": 0},
    ]
    out = attach_BIAS(pd.DataFrame(rows)).set_index("race_id")
    r_hit = out.loc["2026-06-30_A_1"]
    assert r_hit["bias_n"] == pytest.approx(2.0)
    assert r_hit["bias_gate_resid"] == pytest.approx((0.80 - 0.30) / (2.0 + BIAS_PRIOR_N))

    r_miss = out.loc["2026-06-30_A_2"]
    assert r_miss["bias_n"] == pytest.approx(0.0)
    assert np.isnan(r_miss["bias_gate_resid"])


def test_attach_DAY_only_earlier_post_time_and_race_no_tiebreak():
    # Same day 2026-06-30, Ankara, Çim:
    # - Race 1 (13:30, race_no=1): gate_frac=0.20 wins (diff = -0.30)
    # - Race 2 (14:00, race_no=2): gate_frac=0.80 wins (diff = +0.30)
    # - Race 3 (14:00, race_no=3 -> same post_time as R2, tiebreak by race_no!): sees R1 & R2, NOT R3!
    # - Race 4 (14:30, İstanbul -> OTHER city!): MUST NOT see Ankara!
    # - Race 5 (14:30, Ankara, Kum -> OTHER surface!): MUST NOT see Çim!
    rows = [
        {"race_id": "2026-06-30_Ankara_1", "date": "2026-06-30", "city": "Ankara", "surface": "Çim", "post_time": "13:30", "race_no": 1, "horse_key": "A1", "gate_frac": 0.20, "finish": 1, "scratched": 0},
        {"race_id": "2026-06-30_Ankara_1", "date": "2026-06-30", "city": "Ankara", "surface": "Çim", "post_time": "13:30", "race_no": 1, "horse_key": "A2", "gate_frac": 0.90, "finish": 2, "scratched": 0},
        {"race_id": "2026-06-30_Ankara_2", "date": "2026-06-30", "city": "Ankara", "surface": "Çim", "post_time": "14:00", "race_no": 2, "horse_key": "B1", "gate_frac": 0.80, "finish": 1, "scratched": 0},
        {"race_id": "2026-06-30_Ankara_2", "date": "2026-06-30", "city": "Ankara", "surface": "Çim", "post_time": "14:00", "race_no": 2, "horse_key": "B2", "gate_frac": 0.40, "finish": 2, "scratched": 0},
        {"race_id": "2026-06-30_Ankara_3", "date": "2026-06-30", "city": "Ankara", "surface": "Çim", "post_time": "14:00", "race_no": 3, "horse_key": "C1", "gate_frac": 0.60, "finish": 1, "scratched": 0},
        {"race_id": "2026-06-30_İstanbul_1", "date": "2026-06-30", "city": "İstanbul", "surface": "Çim", "post_time": "14:30", "race_no": 1, "horse_key": "D1", "gate_frac": 0.50, "finish": np.nan, "scratched": 0},
        {"race_id": "2026-06-30_Ankara_5", "date": "2026-06-30", "city": "Ankara", "surface": "Kum", "post_time": "14:30", "race_no": 5, "horse_key": "E1", "gate_frac": 0.50, "finish": np.nan, "scratched": 0},
    ]
    out = attach_DAY(pd.DataFrame(rows))
    r1 = out[out["race_id"] == "2026-06-30_Ankara_1"].iloc[0]
    r2 = out[out["race_id"] == "2026-06-30_Ankara_2"].iloc[0]
    r3 = out[out["race_id"] == "2026-06-30_Ankara_3"].iloc[0]
    r_ist = out[out["race_id"] == "2026-06-30_İstanbul_1"].iloc[0]
    r_kum = out[out["race_id"] == "2026-06-30_Ankara_5"].iloc[0]

    assert r1["day_bias_n"] == pytest.approx(0.0)
    assert np.isnan(r1["day_gate_bias"])

    exp_b2 = (0.20 - 0.5) / (1.0 + DAY_PRIOR_N)
    assert r2["day_bias_n"] == pytest.approx(1.0)
    assert r2["day_gate_bias"] == pytest.approx(exp_b2)
    assert r2["day_gate_bias_x_gf"] == pytest.approx(exp_b2 * 0.80)

    exp_b3 = ((0.20 - 0.5) + (0.80 - 0.5)) / (2.0 + DAY_PRIOR_N)
    assert r3["day_bias_n"] == pytest.approx(2.0)
    assert r3["day_gate_bias"] == pytest.approx(exp_b3)
    assert r3["day_gate_bias_x_gf"] == pytest.approx(exp_b3 * 0.60)

    assert r_ist["day_bias_n"] == pytest.approx(0.0)
    assert r_kum["day_bias_n"] == pytest.approx(0.0)


def test_v9_strict_future_invariance_and_same_day_freeze():
    dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01", "2026-06-15", "2026-07-01"]
    rows = []
    for i, d in enumerate(dates):
        for rno in (1, 2):
            rid = f"{d}_Ankara_{rno}"
            pt = "14:00" if rno == 1 else "14:30"
            rows.append({
                "race_id": rid,
                "date": d,
                "city": "Ankara",
                "surface": "Çim",
                "distance": 1400,
                "post_time": pt,
                "race_no": rno,
                "horse_key": "H_A" if rno == 1 else "H_B",
                "trainer": "T_SHARED",
                "jockey": "A.ÇELİK" if i % 2 == 0 else "A.ÇELİK AP",
                "gate": 1 if rno == 1 else 5,
                "gate_frac": 0.2 if rno == 1 else 0.8,
                "finish": 2 if rno == 1 else 1,
                "fpct": 0.5 if rno == 1 else 0.0,
                "agf_share": 0.30 if rno == 1 else 0.40,
                "scratched": 0,
            })
            # Cross-rival H_X to trigger KEY + same-day double entry for H_A on 2026-06-15
            rows.append({
                "race_id": rid,
                "date": d,
                "city": "Ankara",
                "surface": "Çim",
                "distance": 1400,
                "post_time": pt,
                "race_no": rno,
                "horse_key": "H_A" if (d == "2026-06-15" and rno == 2) else f"H_X_{rno}",
                "trainer": "T_SHARED" if (d == "2026-06-15" and rno == 2) else "T_OTH",
                "jockey": ("A.ÇELİK" if i % 2 == 0 else "A.ÇELİK AP") if (d == "2026-06-15" and rno == 2) else "B.SAV",
                "gate": 1 if (d == "2026-06-15" and rno == 2) else 3,
                "gate_frac": 0.2 if (d == "2026-06-15" and rno == 2) else 0.6,
                "finish": 1 if rno == 1 else 3,
                "fpct": 0.0 if rno == 1 else 1.0,
                "agf_share": 0.70 if rno == 1 else 0.60,
                "scratched": 0,
            })

    workouts = pd.DataFrame([
        {"source": "liderform", "horse_key": "H_A", "date": pd.Timestamp("2026-06-10"), "jockey": "AHMET ÇELİK", "effort": "ALLOUT"},
        {"source": "liderform", "horse_key": "H_A", "date": pd.Timestamp("2026-06-15"), "jockey": "B.SAV", "effort": "DRIVING"},
        {"source": "yenibeygir", "horse_key": "H_A", "date": pd.Timestamp("2026-06-25"), "jockey": "B.SAV", "effort": "ALLOUT"},
    ])
    v5_tables = {"workouts": workouts}

    df_orig = pd.DataFrame(rows)
    df_mut = df_orig.copy()
    mask_ge_d = pd.to_datetime(df_mut["date"]) >= pd.Timestamp("2026-06-15")
    mask_gt_d = pd.to_datetime(df_mut["date"]) > pd.Timestamp("2026-06-15")
    df_mut.loc[mask_ge_d, "finish"] = 1
    df_mut.loc[mask_ge_d, "fpct"] = 0.0
    df_mut.loc[mask_gt_d, "agf_share"] = 0.95

    out_orig = attach_v9(df_orig, blocks=tuple(V9_BLOCK_COLS), v5_tables=v5_tables)
    out_mut = attach_v9(df_mut, blocks=tuple(V9_BLOCK_COLS), v5_tables=v5_tables)

    # 5 candidate blocks: strictly future-invariant on <= D even when >= D finishes change!
    le_d = pd.to_datetime(out_orig["date"]) <= pd.Timestamp("2026-06-15")
    cand_cols = [c for blk in V9_CANDIDATE_BLOCKS for c in V9_BLOCK_COLS[blk]]
    for col in cand_cols:
        s1 = out_orig.loc[le_d, col].to_numpy(dtype=np.float64)
        s2 = out_mut.loc[le_d, col].to_numpy(dtype=np.float64)
        assert np.array_equal(s1, s2, equal_nan=True), f"Temporal leakage detected in {col}!"

    # DAY block: strictly invariant on < D (2026-06-15 race 1 uses only before race 1; mutations >= race 1 don't leak into < 06-15 or 06-15 race 1)
    lt_d = pd.to_datetime(out_orig["date"]) < pd.Timestamp("2026-06-15")
    for col in DAY_COLS:
        assert np.array_equal(
            out_orig.loc[lt_d, col].to_numpy(dtype=np.float64),
            out_mut.loc[lt_d, col].to_numpy(dtype=np.float64),
            equal_nan=True,
        ), f"Leakage in DAY col {col}"
        r1_d = out_orig["race_id"] == "2026-06-15_Ankara_1"
        assert np.array_equal(
            out_orig.loc[r1_d, col].to_numpy(dtype=np.float64),
            out_mut.loc[r1_d, col].to_numpy(dtype=np.float64),
            equal_nan=True,
        )

    # Same-day freeze across race 1 and race 2 for H_A on 2026-06-15 for all 21 candidate cols
    ha_d = out_orig[(out_orig["date"] == "2026-06-15") & (out_orig["horse_key"] == "H_A")]
    assert len(ha_d) == 2
    for col in cand_cols:
        if col == "trn_resid_28d_rel":
            # Race-relative difference depends on the other runners in race 1 vs race 2
            continue
        v0, v1 = ha_d[col].iloc[0], ha_d[col].iloc[1]
        assert (np.isnan(v0) and np.isnan(v1)) or np.isclose(v0, v1), f"Same-day freeze broken for {col}"


def test_v9_empty_missing_columns_and_none_tables_resilience():
    empty_df = pd.DataFrame(columns=["race_id", "date", "horse_key"])
    out_empty = attach_v9(empty_df, blocks=tuple(V9_BLOCK_COLS), v5_tables=None)
    assert len(out_empty) == 0
    for blk in V9_BLOCK_COLS:
        for c in V9_BLOCK_COLS[blk]:
            assert c in out_empty.columns

    minimal = pd.DataFrame([{"race_id": "2026-06-15_A_1", "date": "2026-06-15", "horse_key": "H1"}])
    out_min = attach_v9(minimal, blocks=tuple(V9_BLOCK_COLS), v5_tables=None)
    assert len(out_min) == 1
    for blk in V9_BLOCK_COLS:
        for c in V9_BLOCK_COLS[blk]:
            assert c in out_min.columns and np.isnan(out_min.loc[0, c])
