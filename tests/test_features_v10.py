"""Unit, hand-calculation, edge-case, and strict temporal leakage tests for ganyan/features_v10.py."""
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest
from scipy.special import ndtr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan.features_v10 import (
    BELL_COLS,
    BELL_FPCT_PRIOR_STD,
    BELL_PRIOR_DF,
    BELL_SF_PRIOR_STD,
    H2H_COLS,
    H2H_PRIOR_N,
    H2H_PRIOR_W,
    JLOY_COLS,
    JLOY_JWR_PRIOR,
    JLOY_T_JWR_PRIOR_N,
    LOAD_COLS,
    LOAD_DECAY_DAYS,
    LOAD_DIST_REF,
    V10_BLOCK_COLS,
    V10_CANDIDATE_BLOCKS,
    attach_BELL,
    attach_H2H,
    attach_JLOY,
    attach_LOAD,
    attach_v10,
    get_v10_cols,
)
from ganyan.model_v9 import V9_CONFIG


def test_v10_column_definitions_and_no_overlap():
    assert len(BELL_COLS) == 6
    assert len(JLOY_COLS) == 6
    assert len(LOAD_COLS) == 5
    assert len(H2H_COLS) == 5
    assert V10_CANDIDATE_BLOCKS == ("BELL", "JLOY", "LOAD", "H2H")
    assert set(V10_BLOCK_COLS) == {"BELL", "JLOY", "LOAD", "H2H"}

    base_v9 = list(V9_CONFIG["feature_cols"])
    assert len(base_v9) == 139
    assert get_v10_cols(()) == base_v9

    v10_only = [c for blk in V10_CANDIDATE_BLOCKS for c in V10_BLOCK_COLS[blk]]
    assert len(v10_only) == 22
    assert len(set(v10_only)) == 22
    assert set(base_v9).isdisjoint(v10_only)

    all_cols = get_v10_cols(V10_CANDIDATE_BLOCKS)
    assert len(all_cols) == 139 + 22
    assert len(set(all_cols)) == 161

    prog_cols = get_v10_cols(("BELL",), with_program=True)
    assert len(prog_cols) == 139 + len(BELL_COLS) + 6  # son6_last/mean/same + kgs/s20/best_sf


def test_bell_exact_math_and_maiden_nans():
    rows = []
    # H1 has 4 prior starts with sf = [10, 30, 10, 30], fpct = [0.0, 1.0, 0.0, 1.0]
    for i, (dt, sf_v, fp_v) in enumerate(
        [
            ("2026-01-01", 10.0, 0.0),
            ("2026-02-01", 30.0, 1.0),
            ("2026-03-01", 10.0, 0.0),
            ("2026-04-01", 30.0, 1.0),
        ]
    ):
        rows.append(
            {
                "race_id": f"{dt}_A_1",
                "date": dt,
                "city": "A",
                "race_no": 1,
                "horse_key": "H1",
                "finish": 1 if fp_v == 0.0 else 3,
                "sf": sf_v,
                "fpct": fp_v,
                "scratched": 0,
            }
        )
    # H3 has 1 prior start: sf = [30.0], fpct = [0.2]
    rows.append(
        {
            "race_id": "2026-03-15_A_1",
            "date": "2026-03-15",
            "city": "A",
            "race_no": 1,
            "horse_key": "H3",
            "finish": 2,
            "sf": 30.0,
            "fpct": 0.2,
            "scratched": 0,
        }
    )
    # H4 has 2 prior starts: sf = [40.0, 40.0], fpct = [0.0, 0.0]
    for dt in ("2026-02-15", "2026-04-15"):
        rows.append(
            {
                "race_id": f"{dt}_A_1",
                "date": dt,
                "city": "A",
                "race_no": 1,
                "horse_key": "H4",
                "finish": 1,
                "sf": 40.0,
                "fpct": 0.0,
                "scratched": 0,
            }
        )

    # Target race D = 2026-05-01 with H1, H2 (maiden), H3, H4, plus H5 (scratched)
    for hk, scr in [("H1", 0), ("H2", 0), ("H3", 0), ("H4", 0), ("H5", 1)]:
        rows.append(
            {
                "race_id": "2026-05-01_A_1",
                "date": "2026-05-01",
                "city": "A",
                "race_no": 1,
                "horse_key": hk,
                "finish": np.nan,
                "sf": np.nan,
                "fpct": np.nan,
                "scratched": scr,
            }
        )

    out = attach_BELL(pd.DataFrame(rows))
    tgt = out[out["race_id"] == "2026-05-01_A_1"].set_index("horse_key")

    h1_var = (400.0 + BELL_PRIOR_DF * (BELL_SF_PRIOR_STD ** 2)) / (3.0 + BELL_PRIOR_DF)
    h1_std = math.sqrt(h1_var)
    h1_fp_std = math.sqrt((1.0 + BELL_PRIOR_DF * (BELL_FPCT_PRIOR_STD ** 2)) / (3.0 + BELL_PRIOR_DF))
    h3_std = BELL_SF_PRIOR_STD
    h4_var = (0.0 + BELL_PRIOR_DF * (BELL_SF_PRIOR_STD ** 2)) / (1.0 + BELL_PRIOR_DF)
    h4_std = math.sqrt(h4_var)
    z90 = 1.2815515655446004

    assert tgt.loc["H1", "bell_sf_std"] == pytest.approx(h1_std)
    assert tgt.loc["H1", "bell_fpct_std"] == pytest.approx(h1_fp_std)
    assert tgt.loc["H1", "bell_sf_p90"] == pytest.approx(20.0 + z90 * h1_std)
    assert tgt.loc["H3", "bell_sf_std"] == pytest.approx(h3_std)
    assert tgt.loc["H4", "bell_sf_std"] == pytest.approx(h4_std)

    mean_std = (h1_std + h3_std + h4_std) / 3.0
    assert tgt.loc["H1", "bell_sf_std_rel"] == pytest.approx(h1_std - mean_std)

    # Top rival for H1 is H4 (mu=40, std=h4_std); top rival for H4 is H3 (mu=30, std=h3_std)
    assert tgt.loc["H1", "bell_upside_gap"] == pytest.approx((20.0 + z90 * h1_std) - 40.0)
    assert tgt.loc["H1", "bell_prob_beat_fav"] == pytest.approx(
        float(ndtr((20.0 - 40.0) / math.sqrt(h1_var + h4_var)))
    )
    assert tgt.loc["H4", "bell_upside_gap"] == pytest.approx((40.0 + z90 * h4_std) - 30.0)
    assert tgt.loc["H4", "bell_prob_beat_fav"] == pytest.approx(
        float(ndtr((40.0 - 30.0) / math.sqrt(h4_var + h3_std ** 2)))
    )

    for col in BELL_COLS:
        assert np.isnan(tgt.loc["H2", col])
        assert np.isnan(tgt.loc["H5", col])


def test_jloy_abandonment_choice_loyalty_and_upgrade():
    rows = []
    # Build 6 prior rides in last 365d for J1 with loyal trainer T_LOYAL (and AP suffix on one ride)
    for k in range(6):
        dt = f"2026-01-{10 + k:02d}"
        rows.append(
            {
                "race_id": f"{dt}_A_1",
                "date": dt,
                "city": "A",
                "race_no": 1,
                "horse_key": f"OLD_{k}",
                "jockey": "ALI VELI AP." if k == 5 else "ALI VELI",
                "trainer": "T_LOYAL",
                "finish": 1 if k < 3 else 4,
                "agf_close": 25.0,
                "scratched": 0,
            }
        )
    # T_NEW normally hires weak jockeys (1 start by J_WEAK, 0 wins)
    rows.append(
        {
            "race_id": "2026-02-01_A_1",
            "date": "2026-02-01",
            "city": "A",
            "race_no": 1,
            "horse_key": "OTHER_NEW",
            "jockey": "MEHMET KAYA",
            "trainer": "T_NEW",
            "finish": 5,
            "agf_close": 10.0,
            "scratched": 0,
        }
    )
    # Give MEHMET KAYA 9 prior losses (total 10 starts, 0 wins -> j_wr = 1/20 = 0.05)
    for k in range(9):
        dt = f"2026-02-{2 + k:02d}"
        rows.append(
            {
                "race_id": f"{dt}_A_1",
                "date": dt,
                "city": "A",
                "race_no": 1,
                "horse_key": f"KAYA_H_{k}",
                "jockey": "MEHMET KAYA",
                "trainer": "T_OTHER",
                "finish": 6,
                "agf_close": 5.0,
                "scratched": 0,
            }
        )

    # Previous race for target horses (2026-03-01): J1 (ALI VELI) rode HORSE_PREV for T_LOYAL
    rows.append(
        {
            "race_id": "2026-03-01_A_1",
            "date": "2026-03-01",
            "city": "A",
            "race_no": 1,
            "horse_key": "HORSE_PREV",
            "jockey": "ALI VELI",
            "trainer": "T_LOYAL",
            "finish": 2,
            "agf_close": 30.0,
            "scratched": 0,
        }
    )
    rows.append(
        {
            "race_id": "2026-03-01_A_2",
            "date": "2026-03-01",
            "city": "A",
            "race_no": 2,
            "horse_key": "HORSE_TARGET",
            "jockey": "MEHMET KAYA",
            "trainer": "T_NEW",
            "finish": 4,
            "agf_close": 12.0,
            "scratched": 0,
        }
    )

    # Target race (2026-04-01): ALI VELI abandons HORSE_PREV (T_LOYAL, 40%) to ride HORSE_TARGET (T_NEW, 10%)!
    # MEHMET KAYA rides HORSE_PREV.
    rows.extend(
        [
            {
                "race_id": "2026-04-01_A_1",
                "date": "2026-04-01",
                "city": "A",
                "race_no": 1,
                "horse_key": "HORSE_TARGET",
                "jockey": "ALI VELI",
                "trainer": "T_NEW",
                "finish": np.nan,
                "agf_close": 10.0,
                "scratched": 0,
            },
            {
                "race_id": "2026-04-01_A_1",
                "date": "2026-04-01",
                "city": "A",
                "race_no": 1,
                "horse_key": "HORSE_PREV",
                "jockey": "MEHMET KAYA",
                "trainer": "T_LOYAL",
                "finish": np.nan,
                "agf_close": 40.0,
                "scratched": 0,
            },
            {
                "race_id": "2026-04-01_A_1",
                "date": "2026-04-01",
                "city": "A",
                "race_no": 1,
                "horse_key": "HORSE_THIRD",
                "jockey": "CAN DEMIR",
                "trainer": "T_THIRD",
                "finish": np.nan,
                "agf_close": 50.0,
                "scratched": 0,
            },
        ]
    )

    out = attach_JLOY(pd.DataFrame(rows))
    tgt = out[out["race_id"] == "2026-04-01_A_1"].set_index("horse_key")

    # HORSE_TARGET gained ALI VELI who abandoned HORSE_PREV (and loyal trainer T_LOYAL)
    assert tgt.loc["HORSE_TARGET", "j_chose_over_prev"] == pytest.approx(1.0)
    assert tgt.loc["HORSE_TARGET", "j_abandoned_to_rival"] == pytest.approx(1.0)  # MEHMET KAYA rode HORSE_TARGET prev and now rides HORSE_PREV
    assert tgt.loc["HORSE_TARGET", "j_chose_agf_diff"] == pytest.approx(0.10 - 0.40)
    assert tgt.loc["HORSE_TARGET", "j_chose_over_loyal_trn"] == pytest.approx(1.0)  # 7 prior rides w/ T_LOYAL vs 0 w/ T_NEW
    assert tgt.loc["HORSE_TARGET", "j_trn_loyal_share_race"] == pytest.approx(0.0)

    # HORSE_PREV was abandoned by ALI VELI (and also gained MEHMET KAYA)
    assert tgt.loc["HORSE_PREV", "j_abandoned_to_rival"] == pytest.approx(1.0)
    assert tgt.loc["HORSE_PREV", "j_chose_over_prev"] == pytest.approx(1.0)
    assert tgt.loc["HORSE_PREV", "j_chose_agf_diff"] == pytest.approx(0.40 - 0.10)
    assert tgt.loc["HORSE_PREV", "j_chose_over_loyal_trn"] == pytest.approx(0.0)

    # HORSE_TARGET upgrade: ALI VELI j_wr (< 2026-04-01): 7 starts, 3 wins -> (3+1)/(7+10) = 4/17
    ali_jwr = 4.0 / 17.0
    # T_NEW had 2 prior rides in 365d:
    # 2026-02-01 MEHMET KAYA (j_wr at that time: 0 starts, 0 wins -> 1/10 = 0.10)
    # 2026-03-01 MEHMET KAYA (j_wr at that time: 10 starts, 0 wins -> 1/20 = 0.05)
    tnew_typ = (0.10 + 0.05 + JLOY_T_JWR_PRIOR_N * JLOY_JWR_PRIOR) / (2.0 + JLOY_T_JWR_PRIOR_N)
    assert tgt.loc["HORSE_TARGET", "t_jwr_upgrade"] == pytest.approx(ali_jwr - tnew_typ)


def test_load_distance_ewma_velocity_and_accel():
    rows = [
        {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "H1", "distance": 1200, "finish": 1, "fpct": 0.0, "sf": 10.0, "scratched": 0},
        {"race_id": "2026-01-31_A_1", "date": "2026-01-31", "city": "A", "race_no": 1, "horse_key": "H1", "distance": 1400, "finish": 2, "fpct": 0.5, "sf": 25.0, "scratched": 0},
        {"race_id": "2026-04-01_A_1", "date": "2026-04-01", "city": "A", "race_no": 1, "horse_key": "H1", "distance": 2000, "finish": 3, "fpct": 1.0, "sf": 31.0, "scratched": 0},
        {"race_id": "2026-04-11_A_1", "date": "2026-04-11", "city": "A", "race_no": 1, "horse_key": "H1", "distance": 1600, "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 0},
        {"race_id": "2026-04-11_A_1", "date": "2026-04-11", "city": "A", "race_no": 1, "horse_key": "H_FRESH", "distance": 1600, "finish": np.nan, "fpct": np.nan, "sf": np.nan, "scratched": 0},
    ]
    out = attach_LOAD(pd.DataFrame(rows)).set_index(["race_id", "horse_key"])

    e0 = (1200.0 / LOAD_DIST_REF) * (1.0 + 0.5 * (1.0 - 0.0))
    w30_pre = e0 * math.exp(-30.0 / LOAD_DECAY_DAYS)
    e1 = (1400.0 / LOAD_DIST_REF) * (1.0 + 0.5 * (1.0 - 0.5))
    w30_post = w30_pre + e1
    w90_pre = w30_post * math.exp(-60.0 / LOAD_DECAY_DAYS)
    e2 = (2000.0 / LOAD_DIST_REF) * (1.0 + 0.5 * (1.0 - 1.0))
    w90_post = w90_pre + e2
    w100_pre = w90_post * math.exp(-10.0 / LOAD_DECAY_DAYS)

    r3 = out.loc[("2026-04-01_A_1", "H1")]
    assert r3["load_dist_60d"] == pytest.approx(1.4)  # 01-31 is 60 days before 04-01; 01-01 is 90d before (excluded)
    assert r3["load_dist_180d"] == pytest.approx(2.6)
    assert r3["load_ewma_wear"] == pytest.approx(w90_pre)
    assert r3["sf_vel_recent"] == pytest.approx((25.0 - 10.0) / 30.0 * 30.0)
    assert np.isnan(r3["sf_accel"])

    r4 = out.loc[("2026-04-11_A_1", "H1")]
    assert r4["load_dist_60d"] == pytest.approx(2.0)  # only 04-01 (10d ago); 01-31 is 70d ago
    assert r4["load_dist_180d"] == pytest.approx(4.6)
    assert r4["load_ewma_wear"] == pytest.approx(w100_pre)
    assert r4["sf_vel_recent"] == pytest.approx((31.0 - 25.0) / 60.0 * 30.0)
    assert r4["sf_accel"] == pytest.approx((31.0 - 25.0) - (25.0 - 10.0))

    rf = out.loc[("2026-04-11_A_1", "H_FRESH")]
    assert rf["load_dist_60d"] == pytest.approx(0.0)
    assert rf["load_dist_180d"] == pytest.approx(0.0)
    assert rf["load_ewma_wear"] == pytest.approx(0.0)
    assert np.isnan(rf["sf_vel_recent"])
    assert np.isnan(rf["sf_accel"])


def test_h2h_meetings_dead_heat_window_and_vs_fav():
    rows = [
        # Very old meeting (>730 days before target 2026-06-01 -> must fall outside window!)
        {"race_id": "2024-05-01_A_1", "date": "2024-05-01", "city": "A", "race_no": 1, "horse_key": "A", "finish": 4, "agf_close": 20, "scratched": 0},
        {"race_id": "2024-05-01_A_1", "date": "2024-05-01", "city": "A", "race_no": 1, "horse_key": "B", "finish": 1, "agf_close": 40, "scratched": 0},
        # Meeting 1 inside 730d (2026-01-01): A(1) beats B(2) and C(3)
        {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "A", "finish": 1, "agf_close": 30, "scratched": 0},
        {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "B", "finish": 2, "agf_close": 40, "scratched": 0},
        {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "C", "finish": 3, "agf_close": 30, "scratched": 0},
        # Meeting 2 inside 730d (2026-03-01): A and B dead-heat at 1st!
        {"race_id": "2026-03-01_A_1", "date": "2026-03-01", "city": "A", "race_no": 1, "horse_key": "A", "finish": 1, "agf_close": 50, "scratched": 0},
        {"race_id": "2026-03-01_A_1", "date": "2026-03-01", "city": "A", "race_no": 1, "horse_key": "B", "finish": 1, "agf_close": 50, "scratched": 0},
        # Target race (2026-06-01): A(30%), B(50% = favorite!), C(15%), D(5%, never met)
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "A", "finish": np.nan, "agf_close": 30, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "B", "finish": np.nan, "agf_close": 50, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "C", "finish": np.nan, "agf_close": 15, "scratched": 0},
        {"race_id": "2026-06-01_A_1", "date": "2026-06-01", "city": "A", "race_no": 1, "horse_key": "D", "finish": np.nan, "agf_close": 5, "scratched": 0},
    ]
    out = attach_H2H(pd.DataFrame(rows))
    tgt = out[out["race_id"] == "2026-06-01_A_1"].set_index("horse_key")

    # A met B twice (win=1 + dead-heat=0.5) and C once (win=1) -> 3 meetings, 2.5 beats, 2 unique rivals
    exp_a = (2.5 + H2H_PRIOR_W) / (3.0 + H2H_PRIOR_N)
    # B met A twice (loss=0 + dh=0.5) and C once (win=1) -> 3 meetings, 1.5 beats; B's top rival by AGF is A (+0 win -1 loss + 0 dh = -1 / 2 = -0.5)
    exp_b = (1.5 + H2H_PRIOR_W) / (3.0 + H2H_PRIOR_N)
    # C met A once (loss) and B once (loss) -> 2 meetings, 0 beats; C's fav rival is B (-1 / 1 = -1.0)
    exp_c = (0.0 + H2H_PRIOR_W) / (2.0 + H2H_PRIOR_N)

    assert tgt.loc["A", "h2h_rivals_met"] == pytest.approx(2.0)
    assert tgt.loc["A", "h2h_meetings"] == pytest.approx(3.0)
    assert tgt.loc["A", "h2h_beat_rate"] == pytest.approx(exp_a)
    assert tgt.loc["A", "h2h_vs_fav_margin"] == pytest.approx(0.5)  # vs B: +1 beat, 1 dead-heat -> net +1 / 2

    assert tgt.loc["B", "h2h_rivals_met"] == pytest.approx(2.0)
    assert tgt.loc["B", "h2h_meetings"] == pytest.approx(3.0)
    assert tgt.loc["B", "h2h_beat_rate"] == pytest.approx(exp_b)
    assert tgt.loc["B", "h2h_vs_fav_margin"] == pytest.approx(-0.5)

    assert tgt.loc["C", "h2h_beat_rate"] == pytest.approx(exp_c)
    assert tgt.loc["C", "h2h_vs_fav_margin"] == pytest.approx(-1.0)

    mean_br = (exp_a + exp_b + exp_c) / 3.0
    assert tgt.loc["A", "h2h_beat_rate_rel"] == pytest.approx(exp_a - mean_br)

    assert tgt.loc["D", "h2h_rivals_met"] == pytest.approx(0.0)
    assert tgt.loc["D", "h2h_meetings"] == pytest.approx(0.0)
    assert np.isnan(tgt.loc["D", "h2h_beat_rate"])
    assert np.isnan(tgt.loc["D", "h2h_vs_fav_margin"])


def _synthetic_history_df():
    return pd.DataFrame(
        [
            {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "H1", "jockey": "J1", "trainer": "T1", "distance": 1200, "finish": 1, "sf": 20.0, "fpct": 0.0, "agf_close": 45.0, "scratched": 0},
            {"race_id": "2026-01-01_A_1", "date": "2026-01-01", "city": "A", "race_no": 1, "horse_key": "H2", "jockey": "J2", "trainer": "T2", "distance": 1200, "finish": 2, "sf": 15.0, "fpct": 1.0, "agf_close": 55.0, "scratched": 0},
            {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H1", "jockey": "J1 AP.", "trainer": "T1", "distance": 1400, "finish": 2, "sf": 24.0, "fpct": 0.5, "agf_close": 35.0, "scratched": 0},
            {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H2", "jockey": "J2", "trainer": "T2", "distance": 1400, "finish": 1, "sf": 30.0, "fpct": 0.0, "agf_close": 50.0, "scratched": 0},
            {"race_id": "2026-02-01_A_1", "date": "2026-02-01", "city": "A", "race_no": 1, "horse_key": "H3", "jockey": "J3", "trainer": "T3", "distance": 1400, "finish": 3, "sf": 10.0, "fpct": 1.0, "agf_close": 15.0, "scratched": 0},
            {"race_id": "2026-03-01_A_1", "date": "2026-03-01", "city": "A", "race_no": 1, "horse_key": "H1", "jockey": "J2", "trainer": "T1", "distance": 1600, "finish": 1, "sf": 35.0, "fpct": 0.0, "agf_close": 40.0, "scratched": 0},
            {"race_id": "2026-03-01_A_1", "date": "2026-03-01", "city": "A", "race_no": 1, "horse_key": "H2", "jockey": "J1", "trainer": "T2", "distance": 1600, "finish": 2, "sf": 28.0, "fpct": 0.5, "agf_close": 45.0, "scratched": 0},
            {"race_id": "2026-03-01_A_1", "date": "2026-03-01", "city": "A", "race_no": 1, "horse_key": "H3", "jockey": "J3", "trainer": "T3", "distance": 1600, "finish": 3, "sf": 18.0, "fpct": 1.0, "agf_close": 15.0, "scratched": 0},
            {"race_id": "2026-04-01_A_1", "date": "2026-04-01", "city": "A", "race_no": 1, "horse_key": "H1", "jockey": "J1", "trainer": "T2", "distance": 1500, "finish": np.nan, "sf": np.nan, "fpct": np.nan, "agf_close": 38.0, "scratched": 0},
            {"race_id": "2026-04-01_A_1", "date": "2026-04-01", "city": "A", "race_no": 1, "horse_key": "H2", "jockey": "J2", "trainer": "T1", "distance": 1500, "finish": np.nan, "sf": np.nan, "fpct": np.nan, "agf_close": 47.0, "scratched": 0},
            {"race_id": "2026-04-01_A_1", "date": "2026-04-01", "city": "A", "race_no": 1, "horse_key": "H3", "jockey": "J3", "trainer": "T3", "distance": 1500, "finish": np.nan, "sf": np.nan, "fpct": np.nan, "agf_close": 15.0, "scratched": 0},
        ]
    )


def test_v10_strict_future_invariance():
    base = _synthetic_history_df()
    # Mutate finish/sf on target day 2026-04-01 AND append brand-new future days
    future_mod = base.copy()
    mask_0401 = future_mod["date"] == "2026-04-01"
    future_mod.loc[mask_0401, "finish"] = [3.0, 1.0, 2.0]
    future_mod.loc[mask_0401, "sf"] = [5.0, 45.0, 25.0]
    future_mod.loc[mask_0401, "fpct"] = [1.0, 0.0, 0.5]
    extra_future = pd.DataFrame(
        [
            {"race_id": "2026-05-01_A_1", "date": "2026-05-01", "city": "A", "race_no": 1, "horse_key": "H1", "jockey": "J2", "trainer": "T1", "distance": 2000, "finish": 1, "sf": 60.0, "fpct": 0.0, "agf_close": 60.0, "scratched": 0},
            {"race_id": "2026-05-01_A_1", "date": "2026-05-01", "city": "A", "race_no": 1, "horse_key": "H2", "jockey": "J1", "trainer": "T2", "distance": 2000, "finish": 2, "sf": 50.0, "fpct": 1.0, "agf_close": 40.0, "scratched": 0},
        ]
    )
    future_mod = pd.concat([future_mod, extra_future], ignore_index=True)

    out_base = attach_v10(base, blocks=V10_CANDIDATE_BLOCKS)
    out_fut = attach_v10(future_mod, blocks=V10_CANDIDATE_BLOCKS).iloc[: len(base)].reset_index(drop=True)

    v10_cols = [c for b in V10_CANDIDATE_BLOCKS for c in V10_BLOCK_COLS[b]]
    for col in v10_cols:
        a = out_base[col].to_numpy(dtype=np.float64)
        b = out_fut[col].to_numpy(dtype=np.float64)
        assert np.array_equal(a, b, equal_nan=True), f"Gelecek sızıntısı: {col}"


def test_v10_same_day_freeze():
    base = _synthetic_history_df()
    # Add an earlier race ON 2026-04-01 featuring H1/H2/J1/T1 whose outcome MUST NOT leak into 2026-04-01 race 2
    earlier_same_day = pd.DataFrame(
        [
            {"race_id": "2026-04-01_A_0", "date": "2026-04-01", "city": "A", "race_no": 0, "horse_key": "H1", "jockey": "J1", "trainer": "T1", "distance": 2400, "finish": 1, "sf": 99.0, "fpct": 0.0, "agf_close": 90.0, "scratched": 0},
            {"race_id": "2026-04-01_A_0", "date": "2026-04-01", "city": "A", "race_no": 0, "horse_key": "H2", "jockey": "J2", "trainer": "T2", "distance": 2400, "finish": 2, "sf": 5.0, "fpct": 1.0, "agf_close": 10.0, "scratched": 0},
        ]
    )
    with_same_day = pd.concat([base, earlier_same_day], ignore_index=True)

    out_base = attach_v10(base, blocks=V10_CANDIDATE_BLOCKS)
    out_same = attach_v10(with_same_day, blocks=V10_CANDIDATE_BLOCKS)

    b_rows = out_base[out_base["race_id"] == "2026-04-01_A_1"].sort_values("horse_key").reset_index(drop=True)
    s_rows = out_same[out_same["race_id"] == "2026-04-01_A_1"].sort_values("horse_key").reset_index(drop=True)
    for col in [c for b in V10_CANDIDATE_BLOCKS for c in V10_BLOCK_COLS[b]]:
        assert np.array_equal(
            b_rows[col].to_numpy(dtype=np.float64),
            s_rows[col].to_numpy(dtype=np.float64),
            equal_nan=True,
        ), f"Aynı gün sızıntısı: {col}"


def test_v10_row_order_invariance_and_scratched():
    base = _synthetic_history_df()
    # Add a scratched runner on 2026-03-01 and 2026-04-01
    scr = pd.DataFrame(
        [
            {"race_id": "2026-03-01_A_1", "date": "2026-03-01", "city": "A", "race_no": 1, "horse_key": "H_SCR", "jockey": "J1", "trainer": "T1", "distance": 1600, "finish": np.nan, "sf": np.nan, "fpct": np.nan, "agf_close": 25.0, "scratched": 1},
            {"race_id": "2026-04-01_A_1", "date": "2026-04-01", "city": "A", "race_no": 1, "horse_key": "H_SCR", "jockey": "J1", "trainer": "T1", "distance": 1500, "finish": np.nan, "sf": np.nan, "fpct": np.nan, "agf_close": 25.0, "scratched": 1},
        ]
    )
    df_with_scr = pd.concat([base, scr], ignore_index=True)
    out_orig = attach_v10(df_with_scr, blocks=V10_CANDIDATE_BLOCKS)

    # Scratched runners must have NaN across all 22 features
    scr_out = out_orig[out_orig["scratched"] == 1]
    for col in [c for b in V10_CANDIDATE_BLOCKS for c in V10_BLOCK_COLS[b]]:
        assert scr_out[col].isna().all(), f"Koşmaz at için NaN değil: {col}"

    # Shuffle row order completely and verify bit-identical output once keyed back
    shuffled = df_with_scr.sample(frac=1.0, random_state=42).reset_index(drop=True)
    out_shuf = attach_v10(shuffled, blocks=V10_CANDIDATE_BLOCKS)

    o_sorted = out_orig.sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    s_sorted = out_shuf.sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    for col in [c for b in V10_CANDIDATE_BLOCKS for c in V10_BLOCK_COLS[b]]:
        assert np.array_equal(
            o_sorted[col].to_numpy(dtype=np.float64),
            s_sorted[col].to_numpy(dtype=np.float64),
            equal_nan=True,
        ), f"Satır sırası duyarlılığı: {col}"


def test_v10_empty_and_invalid_block():
    empty = pd.DataFrame(columns=["race_id", "date", "city", "race_no", "horse_key", "finish", "scratched"])
    for fn in (attach_BELL, attach_JLOY, attach_LOAD, attach_H2H):
        res = fn(empty)
        assert len(res) == 0

    res_all = attach_v10(empty, blocks=V10_CANDIDATE_BLOCKS)
    assert len(res_all) == 0
    for b in V10_CANDIDATE_BLOCKS:
        for col in V10_BLOCK_COLS[b]:
            assert col in res_all.columns

    with pytest.raises(ValueError):
        attach_v10(empty, blocks=("BELL", "BAD_BLOCK"))
    with pytest.raises(ValueError):
        get_v10_cols(v10_blocks=("BAD_BLOCK",))
