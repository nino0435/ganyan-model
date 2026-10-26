"""Strict leakage test for ganyan.features.build_features (§3.1)."""
import numpy as np
import pandas as pd
from ganyan.features import build_features, get_feature_cols


def _make_synthetic_history():
    """Create a multi-day synthetic dataset spanning before, on, and after D=2026-06-14."""
    dates = ["2025-02-10", "2025-04-15", "2026-05-01", "2026-06-14", "2026-06-20", "2026-07-05"]
    horses = [f"SIRE_{i}|DAM_{i}|2022" for i in range(8)]
    jockeys = [f"J_{i % 3}" for i in range(8)]
    trainers = [f"T_{i % 2}" for i in range(8)]

    rows = []
    rng = np.random.default_rng(42)
    for d_idx, d in enumerate(dates):
        for r_no in (1, 2):
            race_id = f"{d}_Ankara_{r_no}"
            subset = horses[:4] if r_no == 1 else horses[4:]
            finishes = rng.permutation([1, 2, 3, 4])
            for h_i, (hk, fin) in enumerate(zip(subset, finishes)):
                idx = int(hk.split("_")[1].split("|")[0])
                rows.append({
                    "race_id": race_id,
                    "date": d,
                    "city": "Ankara",
                    "race_no": r_no,
                    "prog_no": h_i + 1,
                    "horse_key": hk,
                    "name": f"HORSE {idx}",
                    "age": 4,
                    "sex": "d" if idx % 2 == 0 else "e",
                    "sire": f"SIRE_{idx}",
                    "dam": f"DAM_{idx}",
                    "weight": 57.0 + h_i * 0.5,
                    "jockey": jockeys[idx],
                    "owner": "OWNER",
                    "trainer": trainers[idx],
                    "gate": h_i + 1,
                    "hp": 50.0 + idx * 2,
                    "breed": "Ingiliz" if r_no == 1 else "Arap",
                    "distance": 1400 if r_no == 1 else 1600,
                    "surface": "Çim" if r_no == 1 else "Kum",
                    "son6": "Ç1K2Ç3K4",
                    "kgs": 14 + idx,
                    "s20": 16,
                    "best_time_s": 85.5 if r_no == 1 else 102.0,
                    "finish": int(fin),
                    "time_s": (85.0 if r_no == 1 else 101.0) + fin * 0.4 + d_idx * 0.1,
                    "ganyan": 2.5 * fin,
                    "agf_close": 40.0 / fin,
                    "agf_close_rank": int(fin),
                    "scratched": 0,
                })
    return pd.DataFrame(rows)


def test_no_future_or_sameday_leakage():
    raw = _make_synthetic_history()
    target_day = pd.Timestamp("2026-06-14")
    ref_end = "2025-07-01"

    # (a) Build features with full dataset (including future dates and target_day outcomes)
    full_feat = build_features(raw, ref_end=ref_end)
    day_a = (
        full_feat[full_feat["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    # (b) Delete all rows after D, and set finish, time_s, ganyan, agf_close on D to NaN
    truncated = raw[pd.to_datetime(raw["date"]) <= target_day].copy()
    mask_d = pd.to_datetime(truncated["date"]) == target_day
    for col in ["finish", "time_s", "ganyan", "agf_close", "agf_close_rank"]:
        truncated.loc[mask_d, col] = np.nan

    # Shuffle order on day D to verify sort order isn't leaking finish position
    truncated = truncated.sample(frac=1.0, random_state=99).reset_index(drop=True)

    trunc_feat = build_features(truncated, ref_end=ref_end)
    day_b = (
        trunc_feat[trunc_feat["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    base_cols, _ = get_feature_cols()
    assert len(day_a) == len(day_b) == 8

    for col in base_cols:
        pd.testing.assert_series_equal(
            day_a[col],
            day_b[col],
            check_names=True,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
            obj=f"Feature column '{col}' leaked future or same-day outcome information!",
        )


def test_walk_forward_non_overlapping():
    from ganyan.backtest import walk_forward

    raw = _make_synthetic_history()
    preds, monthly, bs = walk_forward(raw, months=["2026-06", "2026-07"], ref_end="2025-07-01")
    assert not preds.empty
    assert list(monthly["month"]) == ["2026-06", "2026-07"]
    assert "v1_agf" in bs
    # Probabilities in each race sum to 1
    sums = preds.groupby("race_id")["p_v1_agf"].sum()
    assert np.allclose(sums.values, 1.0)

