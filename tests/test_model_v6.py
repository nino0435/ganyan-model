"""Unit, strict leakage, and synthetic end-to-end tests for Model v6."""
import ast
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
import pytest

from ganyan.db import (
    init_db,
    upsert_pools,
    upsert_race_extra,
    upsert_results,
    upsert_runner_extra,
)
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5
from ganyan.features_v6 import (
    V6_BLOCK_COLS,
    X_FARK_COLS,
    X_GC_COLS,
    X_POOL_COLS,
    X_PRIZE_COLS,
    X_S800_COLS,
    X_STEW_COLS,
    attach_X_FARK,
    attach_X_STEW,
    attach_v6,
    compute_yearly_source_coverage,
    load_v6_tables,
    parse_fark_to_boy,
    parse_gec_cikis_to_boy,
)
from ganyan.model import fit_predict_df
from ganyan.model_v5 import PROGRAM_COLS, to_log_prob
from ganyan.model_v6 import (
    CANDIDATE_VARIANTS,
    E2_VARIANT_NAMES,
    E4_VARIANT_NAMES,
    VARIANT_SPECS,
    IsotonicRaceCalibrator,
    RaceTemperatureCalibrator,
    compute_ev_bet_stats,
    compute_topk_coverage,
    config_digest,
    evaluate_stage_b_gate,
    fit_predict_v6,
    get_v6_cols,
    pin_v6_config_in_source,
    resolve_variant_config,
)
from scripts.run_v6_experiments import build_arg_parser, main as v6_cli_main, run_v6_experiments


def test_v6_block_and_variant_definitions():
    assert set(V6_BLOCK_COLS.keys()) == {"X_GC", "X_FARK", "X_S800", "X_PRIZE", "X_POOL", "X_STEW"}
    assert len(E2_VARIANT_NAMES) <= 12
    assert len(E4_VARIANT_NAMES) <= 6
    assert VARIANT_SPECS["E3"]["seeds"] == (0, 1, 2, 3, 4)

    all_v6_cols = get_v6_cols(extra_blocks=tuple(V6_BLOCK_COLS), with_program=False)
    assert len(all_v6_cols) == len(set(all_v6_cols))
    for pcol in PROGRAM_COLS:
        assert pcol not in all_v6_cols

    with pytest.raises(ValueError):
        get_v6_cols(extra_blocks=("UNKNOWN_BLOCK",))

    digests = {}
    for v_name in ("E0",) + CANDIDATE_VARIANTS:
        cfg = resolve_variant_config(v_name)
        assert cfg["variant"] == v_name
        digests[v_name] = config_digest(cfg)
    assert digests["E0"] != digests["E1a"]
    assert digests["E1a"] != digests["E1b"]
    assert digests["E4_gc"] != digests["E4_fark"]
    assert compute_yearly_source_coverage(pd.DataFrame()).empty


def test_parsers_fark_and_gec_cikis_hand_calculated():
    assert parse_fark_to_boy("At Başı") == pytest.approx(0.0)
    assert parse_fark_to_boy("Burun") == pytest.approx(0.05)
    assert parse_fark_to_boy("Baş") == pytest.approx(0.15)
    assert parse_fark_to_boy("Boyun") == pytest.approx(0.30)
    assert parse_fark_to_boy("Yarım Boy") == pytest.approx(0.50)
    assert parse_fark_to_boy("1,5 Boy") == pytest.approx(1.5)
    assert parse_fark_to_boy("6 Metre") == pytest.approx(2.0)
    assert parse_fark_to_boy("Uzak") == pytest.approx(10.0)
    assert np.isnan(parse_fark_to_boy(None))
    assert np.isnan(parse_fark_to_boy("-"))

    assert parse_gec_cikis_to_boy(None) == pytest.approx(0.0)
    assert parse_gec_cikis_to_boy("-") == pytest.approx(0.0)
    assert parse_gec_cikis_to_boy("Startta Kaldı") == pytest.approx(20.0)
    assert parse_gec_cikis_to_boy("2,5 Boy") == pytest.approx(2.5)
    assert parse_gec_cikis_to_boy("15 Metre") == pytest.approx(5.0)


def _make_synthetic_v6_fixture():
    """Build synthetic multi-date racing data + all 4 v6 extra tables spanning < D, == D, and > D."""
    dates = [
        ("2025-02-10", "Ankara"),
        ("2025-05-12", "İstanbul"),
        ("2026-04-20", "Ankara"),
        ("2026-06-14", "Bursa"),     # Target day D
        ("2026-06-28", "İstanbul"),  # Future > D
        ("2026-07-15", "Ankara"),    # Future > D
    ]
    horses = [f"SIRE_{i}|DAM_{i}|2021" for i in range(8)]
    rng = np.random.default_rng(123)

    runner_rows = []
    re_rows = []
    rce_rows = []
    pool_rows = [
        {"date": "2026-03-01", "city": "Ankara", "bet": "GANYAN", "amount": 320_000.0},
        {"date": "2026-03-01", "city": "Ankara", "bet": "1. 6'LI GANYAN", "amount": 1_500_000.0},
        {"date": "2026-05-01", "city": "Bursa", "bet": "GANYAN", "amount": 410_000.0},
        {"date": "2026-05-01", "city": "Bursa", "bet": "1. 6'LI GANYAN", "amount": 1_900_000.0},
    ]
    stew_rows = []

    for d_i, (d_str, city) in enumerate(dates):
        is_on_or_after_d = d_str >= "2026-06-14"
        pool_rows.append(
            {
                "date": d_str,
                "city": city,
                "bet": "GANYAN",
                "amount": 9e9 if is_on_or_after_d else float(250_000 * (d_i + 1)),
            }
        )
        pool_rows.append(
            {
                "date": d_str,
                "city": city,
                "bet": "1. 6'LI GANYAN",
                "amount": 5e10 if is_on_or_after_d else float(1_200_000 * (d_i + 1)),
            }
        )

        for r_no in (1, 2):
            rid = f"{d_str}_{city}_{r_no}"
            sub_h = horses[:4] if r_no == 1 else horses[4:]
            fins = rng.permutation([1, 2, 3, 4])

            rce_rows.append(
                {
                    "race_id": rid,
                    "son800_s": 39.5 if is_on_or_after_d else (48.0 + 0.6 * r_no + 0.2 * d_i),
                    "prize_1": 85_000_000.0 if is_on_or_after_d else float(300_000 * (1 + r_no)),
                }
            )

            for pos, (hk, fin) in enumerate(zip(sub_h, fins)):
                idx = int(hk.split("_")[1].split("|")[0])
                runner_rows.append(
                    {
                        "race_id": rid,
                        "date": d_str,
                        "city": city,
                        "race_no": r_no,
                        "prog_no": pos + 1,
                        "horse_key": hk,
                        "name": f"AT {idx}",
                        "age": 4,
                        "sex": "d" if idx % 2 == 0 else "e",
                        "sire": f"SIRE_{idx}",
                        "dam": f"DAM_{idx}",
                        "weight": 56.0 + pos * 0.5,
                        "jockey": f"J_{idx % 3}",
                        "owner": f"O_{idx % 4}",
                        "trainer": f"T_{idx % 2}",
                        "gate": pos + 1,
                        "hp": 55.0 + idx * 2,
                        "breed": "Ingiliz" if r_no == 1 else "Arap",
                        "distance": 1400 if r_no == 1 else 1600,
                        "surface": "Çim" if r_no == 1 else "Kum",
                        "finish": int(fin),
                        "time_s": (85.0 if r_no == 1 else 101.0) + float(fin) * 0.35,
                        "ganyan": 2.0 + float(fin) * 1.5,
                        "agf_close": 40.0 / float(fin),
                        "agf_close_rank": int(fin),
                        "scratched": 0,
                    }
                )
                # Inject extreme fark & gec_cikis on D and > D to prove zero leakage
                if is_on_or_after_d:
                    fark_txt = "Uzak"
                    gc_txt = "Startta Kaldı"
                else:
                    fark_txt = "1,5 Boy" if fin in (1, 2, 3) else None
                    gc_txt = "2 Boy" if (idx + d_i) % 3 == 0 else None
                re_rows.append(
                    {
                        "race_id": rid,
                        "horse_key": hk,
                        "fark": fark_txt,
                        "gec_cikis": gc_txt,
                    }
                )
                if is_on_or_after_d or (idx % 2 == 0 and d_i == 1):
                    stew_rows.append(
                        {
                            "race_id": rid,
                            "horse_name": f"AT {idx}",
                            "horse_key": hk,
                        }
                    )

    tables = {
        "runner_extra": pd.DataFrame(re_rows),
        "race_extra": pd.DataFrame(rce_rows),
        "pools": pd.DataFrame(pool_rows),
        "steward_notes": pd.DataFrame(stew_rows),
    }
    return pd.DataFrame(runner_rows), tables


def test_no_sameday_or_future_leakage_all_v6_features():
    """Every column in all 6 V6 blocks on day D must ignore >= D outcomes, >= D extra rows, and row order."""
    raw, tables_full = _make_synthetic_v6_fixture()
    target_day = pd.Timestamp("2026-06-14")
    ref_end = "2025-12-31"

    # (a) Full dataset including >= D outcomes and extreme >= D extra-table values
    feat_full = build_features(raw, ref_end=ref_end)
    feat_full = attach_v6(feat_full, tables_full, blocks=tuple(V6_BLOCK_COLS))
    day_a = (
        feat_full[feat_full["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    # (b1) Keep extra tables un-truncated (still holding extreme D and >D rows!), mask D outcomes & shuffle
    trunc_raw = raw[pd.to_datetime(raw["date"]) <= target_day].copy()
    mask_d = pd.to_datetime(trunc_raw["date"]) == target_day
    for col in ["finish", "time_s", "ganyan", "agf_close", "agf_close_rank"]:
        trunc_raw.loc[mask_d, col] = np.nan
    trunc_raw = trunc_raw.sample(frac=1.0, random_state=77).reset_index(drop=True)

    feat_b1 = attach_v6(build_features(trunc_raw, ref_end=ref_end), tables_full, blocks=tuple(V6_BLOCK_COLS))
    day_b1 = (
        feat_b1[feat_b1["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    # (b2) Also delete all >= D rows from all 4 extra tables
    prior_rids = set(raw.loc[pd.to_datetime(raw["date"]) < target_day, "race_id"])
    tables_prior = {
        "runner_extra": tables_full["runner_extra"][tables_full["runner_extra"]["race_id"].isin(prior_rids)].copy(),
        "race_extra": tables_full["race_extra"][tables_full["race_extra"]["race_id"].isin(prior_rids)].copy(),
        "pools": tables_full["pools"][pd.to_datetime(tables_full["pools"]["date"]) < target_day].copy(),
        "steward_notes": tables_full["steward_notes"][tables_full["steward_notes"]["race_id"].isin(prior_rids)].copy(),
    }
    feat_b2 = attach_v6(build_features(trunc_raw, ref_end=ref_end), tables_prior, blocks=tuple(V6_BLOCK_COLS))
    day_b2 = (
        feat_b2[feat_b2["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    all_new_cols = (
        X_GC_COLS + X_FARK_COLS + X_S800_COLS + X_PRIZE_COLS + X_POOL_COLS + X_STEW_COLS
    )
    assert len(all_new_cols) == 25
    assert len(day_a) == len(day_b1) == len(day_b2) == 8

    for col in all_new_cols:
        assert day_a[col].notna().any(), f"V6 feature '{col}' was all-NaN on synthetic target day!"
        pd.testing.assert_series_equal(
            day_a[col],
            day_b1[col],
            check_names=True,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
            obj=f"V6 feature '{col}' leaked same-day/future runner outcomes or row ordering!",
        )
        pd.testing.assert_series_equal(
            day_a[col],
            day_b2[col],
            check_names=True,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
            obj=f"V6 feature '{col}' leaked same-day/future extra-table rows!",
        )


def test_attach_X_FARK_both_tjk_conventions_and_X_STEW_hand_calculated():
    df = pd.DataFrame(
        [
            # Race 1 (2026-01-01): ahead-horse Fark convention (f1='2 Boy', f2='Boyun'=0.3)
            {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "horse_key": "H1", "name": "AT BIR", "finish": 1, "scratched": 0},
            {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "horse_key": "H2", "name": "AT IKI", "finish": 2, "scratched": 0},
            {"race_id": "2026-01-01_Ankara_1", "date": "2026-01-01", "city": "Ankara", "race_no": 1, "horse_key": "H3", "name": "AT UC", "finish": 3, "scratched": 0},
            # Race 2 (2026-01-10): beaten-horse Fark convention (f1=None, f2='Yarım Boy'=0.5, f3='Baş'=0.15)
            {"race_id": "2026-01-10_Ankara_1", "date": "2026-01-10", "city": "Ankara", "race_no": 1, "horse_key": "H1", "name": "AT BIR", "finish": 2, "scratched": 0},
            {"race_id": "2026-01-10_Ankara_1", "date": "2026-01-10", "city": "Ankara", "race_no": 1, "horse_key": "H2", "name": "AT IKI", "finish": 1, "scratched": 0},
            {"race_id": "2026-01-10_Ankara_1", "date": "2026-01-10", "city": "Ankara", "race_no": 1, "horse_key": "H3", "name": "AT UC", "finish": 3, "scratched": 0},
            # Race 3 (2026-01-25): target evaluation race
            {"race_id": "2026-01-25_Ankara_1", "date": "2026-01-25", "city": "Ankara", "race_no": 1, "horse_key": "H1", "name": "AT BIR", "finish": np.nan, "scratched": 0},
            {"race_id": "2026-01-25_Ankara_1", "date": "2026-01-25", "city": "Ankara", "race_no": 1, "horse_key": "H2", "name": "AT IKI", "finish": np.nan, "scratched": 0},
            {"race_id": "2026-01-25_Ankara_1", "date": "2026-01-25", "city": "Ankara", "race_no": 1, "horse_key": "H3", "name": "AT UC", "finish": np.nan, "scratched": 0},
        ]
    )
    re_df = pd.DataFrame(
        [
            {"race_id": "2026-01-01_Ankara_1", "horse_key": "H1", "fark": "2 Boy", "gec_cikis": None},
            {"race_id": "2026-01-01_Ankara_1", "horse_key": "H2", "fark": "Boyun", "gec_cikis": None},
            {"race_id": "2026-01-01_Ankara_1", "horse_key": "H3", "fark": None, "gec_cikis": None},
            {"race_id": "2026-01-10_Ankara_1", "horse_key": "H2", "fark": None, "gec_cikis": None},
            {"race_id": "2026-01-10_Ankara_1", "horse_key": "H1", "fark": "Yarım Boy", "gec_cikis": None},
            {"race_id": "2026-01-10_Ankara_1", "horse_key": "H3", "fark": "Baş", "gec_cikis": None},
        ]
    )
    out_f = attach_X_FARK(df, re_df)
    r3 = out_f[out_f["race_id"] == "2026-01-25_Ankara_1"].set_index("horse_key")
    # H1: R1 margin = -2.0 (won by 2L), R2 margin = +0.5 (2nd by 0.5L, close loss=1)
    assert r3.loc["H1", "h_margin_last"] == pytest.approx(0.5)
    assert r3.loc["H1", "h_margin_m3"] == pytest.approx((-2.0 + 0.5) / 2.0)
    assert r3.loc["H1", "h_close_loss_m3"] == pytest.approx(0.5)
    # H2: R1 margin = +2.0 (close loss=0), R2 margin = -0.5 (won by 0.5L)
    assert r3.loc["H2", "h_margin_last"] == pytest.approx(-0.5)
    assert r3.loc["H2", "h_margin_m3"] == pytest.approx((2.0 - 0.5) / 2.0)
    # H3: R1 margin = 2.3 (close loss=0), R2 margin = 0.5 + 0.15 = 0.65 (3rd within 1L -> close loss=1)
    assert r3.loc["H3", "h_margin_last"] == pytest.approx(0.65)
    assert r3.loc["H3", "h_close_loss_m3"] == pytest.approx(0.5)

    # Steward notes with horse_key missing (name fallback) on 2026-01-10 for AT BIR (H1)
    stew_df = pd.DataFrame(
        [
            {"race_id": "2026-01-10_Ankara_1", "horse_name": "AT BIR", "horse_key": pd.NA},
        ]
    )
    out_s = attach_X_STEW(df, stew_df)
    r3_s = out_s[out_s["race_id"] == "2026-01-25_Ankara_1"].set_index("horse_key")
    assert r3_s.loc["H1", "stew_prior_cnt"] == pytest.approx(1.0)
    assert r3_s.loc["H1", "stew_days_last"] == pytest.approx(15.0)
    assert r3_s.loc["H1", "stew_last_race_flag"] == pytest.approx(1.0)
    assert r3_s.loc["H2", "stew_prior_cnt"] == pytest.approx(0.0)
    assert np.isnan(r3_s.loc["H2", "stew_days_last"])
    assert r3_s.loc["H2", "stew_last_race_flag"] == pytest.approx(0.0)


def test_temperature_and_isotonic_calibrators_and_monotone_tail_guard():
    rng = np.random.default_rng(2026)
    n_races, field = 2500, 6
    logits = rng.normal(0.0, 1.0, size=(n_races, field))
    e0 = np.exp(logits - logits.max(axis=1, keepdims=True))
    p_base = e0 / e0.sum(axis=1, keepdims=True)

    true_gamma = 1.6
    z_true = true_gamma * to_log_prob(p_base, 1e-6)
    ez = np.exp(z_true - z_true.max(axis=1, keepdims=True))
    p_true = ez / ez.sum(axis=1, keepdims=True)

    cdf = np.cumsum(p_true, axis=1)
    cdf[:, -1] = 1.0
    win_col = (rng.random((n_races, 1)) > cdf).sum(axis=1)
    winners = np.zeros((n_races, field), dtype=float)
    winners[np.arange(n_races), win_col] = 1.0
    race_ids = np.repeat([f"R_{i}" for i in range(n_races)], field)

    tcal = RaceTemperatureCalibrator(clip_min=1e-6).fit(p_base.ravel(), race_ids, winners.ravel())
    assert abs(tcal.gamma - true_gamma) <= 0.15
    p_t = tcal.predict(p_base.ravel(), race_ids)
    assert np.allclose(p_t.reshape(n_races, field).sum(axis=1), 1.0)

    # Isotonic tail-guard check: inject extreme longshots (p=0.002) with 0 wins in training.
    # Because winners come from true_gamma=1.6, iso(0.499) is ~0.676, so unnormalized sum on
    # [0.002, 0.499, 0.499] is ~1.352: without tail guard p[0] collapses to ~7.4e-7, whereas
    # with 0.2x floor (q[0]=0.0004) p[0] = 0.0004 / 1.352 ~= 2.96e-4 >= 2e-4.
    p_train_iso = np.r_[np.full(200, 0.002), p_base.ravel()]
    w_train_iso = np.r_[np.zeros(200), winners.ravel()]
    ical_no_guard = IsotonicRaceCalibrator(clip_min=1e-6, tail_floor_ratio=0.0).fit(p_train_iso, w_train_iso)
    ical = IsotonicRaceCalibrator(clip_min=1e-6, tail_floor_ratio=0.2).fit(p_train_iso, w_train_iso)

    test_race = np.array([0.002, 0.499, 0.499], dtype=np.float64)
    test_rids = np.array(["T1", "T1", "T1"])
    p_iso_raw = ical_no_guard.predict(test_race, test_rids)
    p_iso = ical.predict(test_race, test_rids)
    assert np.isclose(p_iso.sum(), 1.0)
    assert p_iso_raw[0] < 5e-6
    assert p_iso[0] >= 2e-4
    assert p_iso[0] > 50.0 * p_iso_raw[0]

    grid = np.linspace(0.001, 0.90, 50)
    p_grid = ical.predict(grid, np.repeat("G1", len(grid)))
    assert np.isclose(p_grid.sum(), 1.0)
    assert np.all(np.diff(p_grid) >= -1e-15)


def test_stage_b_gate_and_ev_bet_stats_ex_top10_hand_calculated():
    rng = np.random.default_rng(11)
    neg_diffs = rng.normal(-0.015, 0.02, size=500)

    g_pass = evaluate_stage_b_gate({2022: -0.01, 2023: -0.02, 2024: -0.01, 2025: 0.002}, neg_diffs)
    assert g_pass["passed"] is True
    assert g_pass["neg_years"] == 3

    # Fails if only 2 of 4 years have dLL < 0 even when overall CI < 0
    g_fail_yr = evaluate_stage_b_gate({2022: -0.04, 2023: -0.04, 2024: 0.001, 2025: 0.002}, neg_diffs)
    assert g_fail_yr["passed"] is False

    # Fails if CI upper bound >= 0 even when 4/4 years are tiny negative
    noisy_diffs = np.array([-0.001, -0.001, 0.05, -0.05] * 25, dtype=float)
    g_fail_ci = evaluate_stage_b_gate({2022: -0.001, 2023: -0.001, 2024: -0.001, 2025: -0.001}, noisy_diffs)
    assert g_fail_ci["passed"] is False

    # EV bet stats + top-N winning payout exclusion check (exclude top 1 win on small fixture)
    ev_df = pd.DataFrame(
        [
            {"race_id": "R1", "date": "2025-01-01", "p_m": 0.30, "ganyan": 5.0, "win": 1.0},   # EV=1.50, pay=5
            {"race_id": "R1", "date": "2025-01-01", "p_m": 0.70, "ganyan": 1.2, "win": 0.0},   # EV=0.84 (skip)
            {"race_id": "R2", "date": "2025-01-02", "p_m": 0.10, "ganyan": 20.0, "win": 1.0},  # EV=2.00, pay=20 (largest win!)
            {"race_id": "R2", "date": "2025-01-02", "p_m": 0.90, "ganyan": 1.1, "win": 0.0},   # EV=0.99
            {"race_id": "R3", "date": "2025-01-03", "p_m": 0.40, "ganyan": 3.2, "win": 0.0},   # EV=1.28, pay=0
            {"race_id": "R3", "date": "2025-01-03", "p_m": 0.60, "ganyan": 1.5, "win": 1.0},   # EV=0.90
        ]
    )
    st = compute_ev_bet_stats(ev_df, "p_m", thresholds=(1.2, 1.5), top_n_exclude=1, n_boot=200, seed=0).set_index("ev_min")
    # At EV >= 1.2: 3 bets (pay = 5, 20, 0) -> net = +4, +19, -1 -> mean ROI = 22/3
    assert st.loc[1.2, "bets"] == 3
    assert st.loc[1.2, "roi"] == pytest.approx(22.0 / 3.0)
    # Excluding largest 1 win (pay=20) leaves 2 bets (pay = 5, 0) -> net = +4, -1 -> ROI = 3/2 = 1.5
    assert st.loc[1.2, "bets_ex_top10"] == 2
    assert st.loc[1.2, "roi_ex_top10"] == pytest.approx(1.5)

    cov = compute_topk_coverage(ev_df, "p_m", ks=(1, 2, 3))
    assert cov["races"] == 3
    assert cov["top1"] == pytest.approx(1.0 / 3.0)
    assert cov["top2"] == pytest.approx(1.0)


def test_fit_predict_v6_single_multiseed_and_temporal_val():
    raw, tables = _make_synthetic_v6_fixture()
    feat = attach_v6(attach_v5(build_features(raw, ref_end="2025-12-31"), {}), tables)
    cols = get_v6_cols(extra_blocks=("X_GC",))
    tr = feat[feat["date"] < pd.Timestamp("2026-06-14")]
    te = feat[feat["date"] >= pd.Timestamp("2026-06-14")]

    p_v1 = fit_predict_df(tr, te, cols)
    p_v6_s0 = fit_predict_v6(tr, te, cols, seeds=(0,))
    assert np.allclose(p_v1, p_v6_s0, atol=1e-12)

    p_v6_5s = fit_predict_v6(tr, te, cols, seeds=(0, 1, 2, 3, 4))
    sums = pd.Series(p_v6_5s).groupby(te["race_id"].to_numpy()).sum()
    assert np.allclose(sums.to_numpy(), 1.0)

    p_v6_tv = fit_predict_v6(tr, te, cols, seeds=(0,), temporal_val_frac=0.2)
    sums_tv = pd.Series(p_v6_tv).groupby(te["race_id"].to_numpy()).sum()
    assert np.allclose(sums_tv.to_numpy(), 1.0)


def test_pin_v6_config_in_source_isolated_tmp_copy(tmp_path):
    orig_path = Path(__file__).resolve().parents[1] / "ganyan" / "model_v6.py"
    copy_path = tmp_path / "model_v6_copy.py"
    shutil.copyfile(orig_path, copy_path)

    sample_cfg = resolve_variant_config("E4_gc")
    pin_v6_config_in_source(sample_cfg, module_path=copy_path)
    tree = ast.parse(copy_path.read_text(encoding="utf-8"))
    ns = {}
    exec(compile(tree, str(copy_path), "exec"), ns)  # noqa: S102
    assert ns["V6_CONFIG"] == sample_cfg

    pin_v6_config_in_source(None, module_path=copy_path)
    tree2 = ast.parse(copy_path.read_text(encoding="utf-8"))
    ns2 = {}
    exec(compile(tree2, str(copy_path), "exec"), ns2)  # noqa: S102
    assert ns2["V6_CONFIG"] is None


def _populate_synthetic_v6_sqlite(db_path):
    """Populate compact synthetic SQLite spanning 2005..2026 (+ unfinished today race) for fast E2E tests."""
    conn = init_db(db_path)
    rng = np.random.default_rng(20261116)
    horses = [f"SIRE_{i}|DAM_{i}|2002" for i in range(10)]
    years = [2005, 2012, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]

    races, runners, rce_rows, re_rows, pool_rows, ext_rows, w_rows, stew_rows = [], [], [], [], [], [], [], []
    for yr in years:
        has_agf = yr >= 2015
        for m_str in ("04-10", "09-15"):
            d_str = f"{yr}-{m_str}"
            city = "Ankara" if m_str == "04-10" else "İstanbul"
            pool_rows.append({"date": d_str, "city": city, "bet": "GANYAN", "amount": 350_000.0})
            if yr >= 2016:
                w_dt = (pd.Timestamp(d_str) - pd.Timedelta(days=9)).strftime("%Y-%m-%d")
                for h_i, hk in enumerate(horses[:5]):
                    w_rows.append(("liderform", hk, f"AT {h_i}", w_dt, city, "GALOP", 51.0, 38.0, 25.0, "CANTER"))

            rid = f"{d_str}_{city}_1"
            races.append(
                {
                    "race_id": rid,
                    "date": d_str,
                    "city": city,
                    "race_no": 1,
                    "post_time": "14:00",
                    "yg_no": 1,
                    "cls": "ŞARTLI",
                    "breed": "Ingiliz",
                    "distance": 1400,
                    "surface": "Çim",
                    "status": "result",
                }
            )
            rce_rows.append({"race_id": rid, "son800_raw": "0.49.20", "son800_s": 49.2, "prize_1": 400_000.0, "source": "tjk_html"})

            fins = rng.permutation(np.arange(1, 6))
            for pos, (hk, fin) in enumerate(zip(horses[:5], fins)):
                idx = pos
                runners.append(
                    {
                        "race_id": rid,
                        "prog_no": pos + 1,
                        "horse_key": hk,
                        "name": f"AT {idx}",
                        "name_raw": f"AT {idx}",
                        "age": 4,
                        "sex": "d" if idx % 2 == 0 else "e",
                        "sire": f"SIRE_{idx}",
                        "dam": f"DAM_{idx}",
                        "weight": 57.0,
                        "jockey": f"J_{idx % 3}",
                        "owner": f"O_{idx % 2}",
                        "trainer": f"T_{idx % 2}",
                        "gate": pos + 1,
                        "hp": 60.0 + idx,
                        "finish": int(fin),
                        "time_s": 85.0 + float(fin) * 0.25,
                        "ganyan": 1.8 + float(fin) * 1.4,
                        "agf_close": (45.0 / float(fin)) if has_agf else None,
                        "agf_close_rank": int(fin) if has_agf else None,
                        "scratched": 0,
                    }
                )
                re_rows.append(
                    {
                        "race_id": rid,
                        "horse_key": hk,
                        "fark": "1 Boy" if fin <= 3 else None,
                        "gec_cikis": "2 Boy" if pos == 4 else None,
                        "hp_result": 60.0 + idx,
                        "tjk_at_id": 1000 + idx,
                        "source": "tjk_html",
                    }
                )
                if yr >= 2012:
                    ext_rows.append(("yenibeygir", rid, hk, "hiz", float(78 - fin * 2)))
                if pos == 0:
                    stew_rows.append((rid, f"AT {idx}", hk, "engel", "faul"))

    # Also insert an unfinished race (finish=None) on 2026-11-16 to verify unfinished races are excluded
    unfin_rid = "2026-11-16_Ankara_1"
    races.append(
        {
            "race_id": unfin_rid,
            "date": "2026-11-16",
            "city": "Ankara",
            "race_no": 1,
            "post_time": "15:00",
            "yg_no": 1,
            "cls": "MAIDEN",
            "breed": "Ingiliz",
            "distance": 1200,
            "surface": "Kum",
            "status": "result",
        }
    )
    for pos, hk in enumerate(horses[:4]):
        runners.append(
            {
                "race_id": unfin_rid,
                "prog_no": pos + 1,
                "horse_key": hk,
                "name": f"AT {pos}",
                "name_raw": f"AT {pos}",
                "age": 3,
                "sex": "e",
                "sire": f"SIRE_{pos}",
                "dam": f"DAM_{pos}",
                "weight": 57.0,
                "jockey": "J_0",
                "owner": "O_0",
                "trainer": "T_0",
                "gate": pos + 1,
                "hp": 50.0,
                "finish": None,
                "time_s": None,
                "ganyan": None,
                "agf_close": 25.0,
                "agf_close_rank": pos + 1,
                "scratched": 0,
            }
        )

    upsert_results(conn, {"races": races, "runners": runners, "bets": [], "altili": []})
    upsert_race_extra(conn, rce_rows)
    upsert_runner_extra(conn, re_rows)
    upsert_pools(conn, pool_rows)
    conn.executemany(
        "INSERT OR REPLACE INTO ext_ratings (source, race_id, horse_key, name, value) VALUES (?, ?, ?, ?, ?)",
        ext_rows,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO workouts (source, horse_key, horse_name, date, city, kind, d800, d600, d400, effort) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        w_rows,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO steward_notes (race_id, horse_name, horse_key, text, tags) VALUES (?, ?, ?, ?, ?)",
        stew_rows,
    )
    conn.commit()
    loaded_v6 = load_v6_tables(conn)
    assert len(loaded_v6["runner_extra"]) > 0
    assert len(loaded_v6["race_extra"]) > 0
    assert len(loaded_v6["pools"]) > 0
    assert len(loaded_v6["steward_notes"]) > 0
    conn.close()


def test_run_v6_experiments_smoke_and_full_synthetic_db(tmp_path, capsys):
    db_path = tmp_path / "syn_v6.db"
    _populate_synthetic_v6_sqlite(db_path)

    # 1. CLI guard: no invented flags accepted
    ap = build_arg_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(["--unknown-flag"])

    # 2. --smoke mode via CLI main(): writes ONLY to --out and --cache-dir, prints SMOKE OK
    smoke_out = tmp_path / "V6_smoke.md"
    smoke_cache = tmp_path / "smoke_cache"
    rc = v6_cli_main(["--db", str(db_path), "--out", str(smoke_out), "--cache-dir", str(smoke_cache), "--smoke"])
    assert rc == 0
    out_captured = capsys.readouterr().out
    assert "SMOKE OK" in out_captured
    assert "varyant=E0 yil=2021" in out_captured
    assert smoke_out.exists()
    assert len(list(smoke_cache.glob("smoke_pred_*.pkl"))) == 2

    # 3. Full staged walk-forward run (A -> B -> C) + cache resume idempotence
    orig_model_v6 = Path(__file__).resolve().parents[1] / "ganyan" / "model_v6.py"
    tmp_model_v6 = tmp_path / "model_v6_isolated.py"
    shutil.copyfile(orig_model_v6, tmp_model_v6)

    full_out = tmp_path / "V6_full.md"
    full_cache = tmp_path / "full_cache"
    res1 = run_v6_experiments(
        db_path=str(db_path),
        out_path=str(full_out),
        cache_dir=str(full_cache),
        smoke=False,
        pin_config=True,
        model_v6_path=str(tmp_model_v6),
    )
    assert full_out.exists()
    md = res1["report_markdown"]
    assert "## 1. Veri Özeti ve Yıllık Kaynak Doluluk Oranları" in md
    assert "## 3. Aşama A — Seçim Kümesi Sonuçları" in md
    assert "## 4. Aşama B — Doğrulama Kümesi" in md
    assert "kilit v5'te tüketildi, temiz test DEĞİL" in md
    assert len(res1["selected_top2"]) == 2
    assert 2005 in set(res1["coverage_df"]["year"])
    # Unfinished 2026-11-16 race must not inflate 2026 race count beyond the 2 finished races
    yr_2026_row = res1["coverage_df"][res1["coverage_df"]["year"] == 2026].iloc[0]
    assert int(yr_2026_row["races"]) == 2
    # Stage B only evaluates B0, E0, and the 2 selected finalists (4 rows total)
    assert len(res1["stage_b_df"]) == 4

    # Warm-cache second run must hit cache and produce identical Stage A & Stage B summaries
    _ = capsys.readouterr()
    res2 = run_v6_experiments(
        db_path=str(db_path),
        out_path=str(tmp_path / "V6_full_warm.md"),
        cache_dir=str(full_cache),
        smoke=False,
        pin_config=False,
    )
    warm_stdout = capsys.readouterr().out
    assert "[onbellek]" in warm_stdout
    pd.testing.assert_frame_equal(res1["stage_a_df"], res2["stage_a_df"])
    pd.testing.assert_frame_equal(res1["stage_b_df"], res2["stage_b_df"])
