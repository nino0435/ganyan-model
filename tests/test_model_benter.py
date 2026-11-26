"""Unit and zero-leakage tests for Two-Stage (Bill Benter) fundamental + market models."""
import sqlite3

import numpy as np
import pandas as pd
import pytest

from ganyan.db import SCHEMA_SQL
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5
from ganyan.features_v7 import attach_v7
from ganyan.features_v8 import attach_v8
from ganyan.features_v9 import attach_v9
from ganyan.features_v10 import attach_v10
from ganyan.model_benter import (
    PAST_MKT_COLS,
    RichBenterCombiner,
    STACK_OOF_COLS,
    TODAY_AGF_COLS,
    ThreeWayLogitBlender,
    TwoParamBenterCombiner,
    attach_fund_oof_features,
    corrupt_agf_share_lognormal,
    get_fund_cols,
    get_stack_cols,
)
from ganyan.model_v10 import V10_BLOCKS, V10_CONFIG
from scripts.run_benter_experiments import run_benter_experiments


def _make_synthetic_runners(n_days=10, races_per_day=2, field_size=6, start_date="2019-06-01", seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    base_dt = pd.Timestamp(start_date)
    horses = [f"AT_{i}|BABA_{i % 5}|ANNE_{i}" for i in range(24)]
    jockeys = [f"JOKEY {i}" for i in range(8)]
    trainers = [f"ANTR {i}" for i in range(6)]
    owners = [f"SAHIP {i} KAYA" for i in range(6)]

    for d_idx in range(n_days):
        dt_str = (base_dt + pd.Timedelta(days=d_idx * 15)).strftime("%Y-%m-%d")
        city = "İstanbul" if d_idx % 2 == 0 else "Ankara"
        for r_no in range(1, races_per_day + 1):
            rid = f"{dt_str}_{city}_{r_no}"
            chosen_h = rng.choice(horses, size=field_size, replace=False)
            strengths = rng.uniform(0.5, 2.5, size=field_size)
            order = np.argsort(-strengths + rng.normal(0, 0.3, size=field_size))
            finishes = np.empty(field_size, dtype=int)
            finishes[order] = np.arange(1, field_size + 1)

            agf_raw = strengths / strengths.sum() * 100.0
            for k in range(field_size):
                hk = chosen_h[k]
                fin = int(finishes[k])
                rows.append(
                    {
                        "race_id": rid,
                        "date": dt_str,
                        "city": city,
                        "race_no": r_no,
                        "post_time": f"{13 + r_no}:00",
                        "distance": 1400 if r_no == 1 else 1600,
                        "surface": "Çim" if r_no == 1 else "Kum",
                        "breed": "İngiliz",
                        "cls": "Handikap 15",
                        "prog_no": k + 1,
                        "horse_key": hk,
                        "name_raw": f"AT_{k} KG DB",
                        "age": 4,
                        "sex": "e" if k % 2 == 0 else "d",
                        "weight": 55.0 + float(k),
                        "jockey": jockeys[(k + d_idx) % len(jockeys)],
                        "trainer": trainers[k % len(trainers)],
                        "owner": owners[k % len(owners)],
                        "gate": k + 1,
                        "hp": 60.0 + 5.0 * strengths[k],
                        "finish": fin,
                        "time_s": 85.0 + 0.4 * fin,
                        "ganyan": round(float(max(1.10, 100.0 / max(agf_raw[k], 2.0))), 2),
                        "agf_pct": round(float(agf_raw[k]), 2),
                        "scratched": 0,
                    }
                )
    return pd.DataFrame(rows)


def _build_full_v10_df(runners_df):
    df = build_features(runners_df, ref_end="2025-07-01")
    df = attach_v5(df, {"ext": pd.DataFrame(), "workouts": pd.DataFrame()}, blocks=("S", "G", "R"))
    df = attach_v7(df, blocks=tuple(V10_CONFIG["v7_blocks"]))
    df = attach_v8(df, blocks=tuple(V10_CONFIG["v8_blocks"]))
    df = attach_v9(df, blocks=tuple(V10_CONFIG["v9_blocks"]), v5_tables={"ext": pd.DataFrame(), "workouts": pd.DataFrame()})
    df = attach_v10(df, blocks=tuple(V10_BLOCKS))
    return df


def test_feature_sets_partition_v10_cleanly():
    v10_cols = list(V10_CONFIG["feature_cols"])
    fund_cols = get_fund_cols(pure_sport=False)
    sport_cols = get_fund_cols(pure_sport=True)
    stack_cols = get_stack_cols()

    assert len(v10_cols) == 155
    assert len(TODAY_AGF_COLS) == 8
    assert len(PAST_MKT_COLS) == 10
    assert set(TODAY_AGF_COLS).issubset(v10_cols)
    assert set(PAST_MKT_COLS).issubset(v10_cols)
    assert set(TODAY_AGF_COLS).isdisjoint(PAST_MKT_COLS)
    assert len(fund_cols) == 147
    assert len(sport_cols) == 137
    assert len(stack_cols) == 159
    assert set(fund_cols).isdisjoint(TODAY_AGF_COLS)
    assert set(sport_cols).isdisjoint(PAST_MKT_COLS)


def test_fund_cols_strictly_invariant_to_today_agf():
    """Mutating or erasing AGF on race day D must change ZERO values in all 147 `FUND_COLS` on day D."""
    base_runners = _make_synthetic_runners(n_days=12, races_per_day=2, field_size=6)
    last_day = base_runners["date"].max()

    alt_runners = base_runners.copy()
    mask_d = alt_runners["date"] == last_day
    # Reverse and scramble today's AGF completely (and set one race's AGF to NaN)
    first_rid = alt_runners.loc[mask_d, "race_id"].iloc[0]
    alt_runners.loc[mask_d, "agf_pct"] = 105.0 - alt_runners.loc[mask_d, "agf_pct"]
    alt_runners.loc[alt_runners["race_id"] == first_rid, "agf_pct"] = np.nan

    df_a = _build_full_v10_df(base_runners)
    df_b = _build_full_v10_df(alt_runners)

    sub_a = df_a[df_a["date"] == pd.Timestamp(last_day)].reset_index(drop=True)
    sub_b = df_b[df_b["date"] == pd.Timestamp(last_day)].reset_index(drop=True)

    for col in get_fund_cols(pure_sport=False):
        np.testing.assert_allclose(
            sub_a[col].to_numpy(dtype=np.float64),
            sub_b[col].to_numpy(dtype=np.float64),
            rtol=0.0,
            atol=1e-12,
            equal_nan=True,
            err_msg=f"Sızıntı yakalandı: `{col}` bugünün AGF değişiminden etkilendi!",
        )

    assert not np.allclose(
        sub_a["agf_share"].to_numpy(dtype=np.float64),
        sub_b["agf_share"].to_numpy(dtype=np.float64),
        equal_nan=True,
    )


def test_pure_sport_cols_invariant_to_all_historical_agf_and_odds():
    """Scrambling BOTH `agf_pct` and `ganyan` across ALL dates must change ZERO values in `PURE_SPORT_COLS`."""
    base_runners = _make_synthetic_runners(n_days=12, races_per_day=2, field_size=6)
    alt_runners = base_runners.copy()
    rng = np.random.default_rng(99)
    alt_runners["agf_pct"] = rng.uniform(1.0, 60.0, size=len(alt_runners))
    alt_runners["ganyan"] = rng.uniform(1.05, 80.0, size=len(alt_runners))

    df_a = _build_full_v10_df(base_runners)
    df_b = _build_full_v10_df(alt_runners)

    for col in get_fund_cols(pure_sport=True):
        np.testing.assert_allclose(
            df_a[col].to_numpy(dtype=np.float64),
            df_b[col].to_numpy(dtype=np.float64),
            rtol=0.0,
            atol=1e-12,
            equal_nan=True,
            err_msg=f"Piyasa sızıntısı: `{col}` geçmiş oran/AGF değişiminden etkilendi!",
        )


def test_attach_fund_oof_features_handles_nan_and_normalizes():
    df = pd.DataFrame(
        {
            "race_id": ["R1", "R1", "R1", "R2", "R2"],
            "agf_share": [0.50, 0.30, 0.20, 0.60, 0.40],
        }
    )
    p_fund = np.array([0.25, 0.55, 0.20, np.nan, np.nan])
    out = attach_fund_oof_features(df, p_fund)

    assert set(STACK_OOF_COLS).issubset(out.columns)
    assert "fund_log_p" not in df.columns
    assert out.loc[0:2, "fund_log_p"].notna().all()
    assert out.loc[3:4, "fund_log_p"].isna().all()
    assert out.loc[3:4, "fund_rk_pct"].isna().all()
    # Runner index 1 has highest p_fund in R1 -> best rank pct (1/3)
    assert out.loc[1, "fund_rk_pct"] < out.loc[0, "fund_rk_pct"] < out.loc[2, "fund_rk_pct"]
    assert np.isclose(out.loc[1, "fund_minus_agf"], 0.55 - 0.30)


def test_two_param_and_three_way_combiners_recover_weights_and_normalize():
    rng = np.random.default_rng(12)
    n_races, k = 150, 5
    rids = np.repeat([f"R_{i}" for i in range(n_races)], k)

    true_logits = rng.normal(0.0, 1.2, size=(n_races, k))
    exp_t = np.exp(true_logits - true_logits.max(axis=1, keepdims=True))
    p_true = exp_t / exp_t.sum(axis=1, keepdims=True)

    wins = np.zeros((n_races, k), dtype=float)
    for i in range(n_races):
        w_idx = rng.choice(k, p=p_true[i])
        wins[i, w_idx] = 1.0

    # p_fund tracks p_true closely; p_agf is noisy uniform-ish
    p_fund = p_true.ravel()
    noisy_logits = rng.normal(0.0, 0.8, size=(n_races, k))
    p_agf = (np.exp(noisy_logits) / np.exp(noisy_logits).sum(axis=1, keepdims=True)).ravel()

    comb2 = TwoParamBenterCombiner().fit(p_fund, p_agf, rids, wins.ravel())
    assert comb2.a_ > comb2.b_
    pred2 = comb2.predict(p_fund, p_agf, rids)
    sums2 = pd.Series(pred2).groupby(rids).sum()
    np.testing.assert_allclose(sums2.to_numpy(), 1.0, atol=1e-9)

    comb3 = ThreeWayLogitBlender().fit(p_fund, p_fund, p_agf, rids, wins.ravel())
    pred3 = comb3.predict(p_fund, p_fund, p_agf, rids)
    sums3 = pd.Series(pred3).groupby(rids).sum()
    np.testing.assert_allclose(sums3.to_numpy(), 1.0, atol=1e-9)


def test_rich_benter_combiner_train_only_standardization_no_test_leakage():
    rng = np.random.default_rng(21)
    n_races, k = 60, 4
    rids = np.repeat([f"TR_{i}" for i in range(n_races)], k)
    p_fund = np.tile([0.45, 0.25, 0.20, 0.10], n_races)
    p_agf = np.tile([0.40, 0.30, 0.20, 0.10], n_races)
    wins = np.zeros(n_races * k)
    for i in range(n_races):
        wins[i * k + rng.choice(k, p=[0.45, 0.25, 0.20, 0.10])] = 1.0

    tr_df = pd.DataFrame(
        {
            "race_id": rids,
            "field": 4,
            "own_is_sub_agf": rng.integers(0, 2, size=n_races * k).astype(float),
            "agf_surge_ratio": rng.normal(0.0, 0.5, size=n_races * k),
        }
    )
    comb = RichBenterCombiner().fit(tr_df, p_fund, p_agf, wins)

    te_single = pd.DataFrame(
        {
            "race_id": ["TE_1"] * 4,
            "field": [4] * 4,
            "own_is_sub_agf": [0.0, 1.0, np.nan, 0.0],
            "agf_surge_ratio": [0.4, -0.2, 0.1, np.nan],
        }
    )
    te_extra = pd.DataFrame(
        {
            "race_id": ["TE_2"] * 4,
            "field": [4] * 4,
            "own_is_sub_agf": [1.0, 1.0, 1.0, 1.0],
            "agf_surge_ratio": [50.0, -50.0, 25.0, -25.0],
        }
    )
    te_both = pd.concat([te_single, te_extra], ignore_index=True)

    p_single = comb.predict(te_single, np.array([0.4, 0.3, 0.2, 0.1]), np.array([0.35, 0.35, 0.2, 0.1]))
    p_both = comb.predict(
        te_both,
        np.array([0.4, 0.3, 0.2, 0.1, 0.25, 0.25, 0.25, 0.25]),
        np.array([0.35, 0.35, 0.2, 0.1, 0.25, 0.25, 0.25, 0.25]),
    )
    np.testing.assert_allclose(p_single, p_both[:4], rtol=0.0, atol=1e-12)
    assert np.isclose(p_single.sum(), 1.0)


def test_corrupt_agf_share_lognormal_properties():
    rids = np.array(["R1", "R1", "R1", "R2", "R2"])
    agf = np.array([0.60, 0.25, 0.15, 0.70, 0.30])
    clean = corrupt_agf_share_lognormal(agf, rids, sigma_log=0.0, seed=1)
    np.testing.assert_allclose(clean, agf, atol=1e-12)

    noisy = corrupt_agf_share_lognormal(agf, rids, sigma_log=0.35, seed=1)
    assert np.isclose(noisy[:3].sum(), 1.0)
    assert np.isclose(noisy[3:].sum(), 1.0)
    assert not np.allclose(noisy, agf)


def test_smoke_pipeline_synthetic_db(tmp_path):
    db_file = tmp_path / "synth.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)

    frames = []
    for yr in (2015, 2016, 2017, 2021):
        frames.append(_make_synthetic_runners(n_days=10, races_per_day=3, field_size=6, start_date=f"{yr}-03-01", seed=yr))
    all_df = pd.concat(frames, ignore_index=True)

    races_rows = (
        all_df[["race_id", "date", "city", "race_no", "post_time", "distance", "surface", "breed", "cls"]]
        .drop_duplicates("race_id")
        .itertuples(index=False)
    )
    conn.executemany(
        """
        INSERT INTO races (race_id, date, city, race_no, post_time, distance, surface, breed, cls, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'result')
        """,
        list(races_rows),
    )
    runner_rows = all_df[
        [
            "race_id",
            "prog_no",
            "horse_key",
            "name_raw",
            "age",
            "sex",
            "weight",
            "jockey",
            "trainer",
            "owner",
            "gate",
            "hp",
            "finish",
            "time_s",
            "ganyan",
            "agf_pct",
            "scratched",
        ]
    ].itertuples(index=False)
    conn.executemany(
        """
        INSERT INTO runners (
            race_id, prog_no, horse_key, name_raw, age, sex, weight, jockey, trainer, owner,
            gate, hp, finish, time_s, ganyan, agf_close, scratched
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        list(runner_rows),
    )
    conn.commit()
    conn.close()

    out_rep = tmp_path / "smoke_rep.md"
    cache_d = tmp_path / "cache"
    res = run_benter_experiments(
        db_path=str(db_file),
        cache_dir=str(cache_d),
        out_report=str(out_rep),
        out_findings="",
        smoke=True,
    )
    assert out_rep.exists()
    txt = out_rep.read_text(encoding="utf-8")
    assert "B2P_06" in txt and "BSTACK_HGB" in txt
    assert len(res["stage1_rows"]) >= 6
