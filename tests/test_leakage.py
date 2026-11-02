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


def _make_synthetic_weather(dates):
    rows = []
    for d in dates:
        base_dt = pd.Timestamp(d) - pd.Timedelta(days=4)
        for h in range(24 * 6):
            ts = (base_dt + pd.Timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
            rows.append({
                "city": "Ankara",
                "ts": ts,
                "precip_mm": 0.2,
                "temp_c": 18.0,
                "rh": 60.0,
                "wind_kmh": 10.0,
                "src": "archive",
            })
    df = pd.DataFrame(rows).drop_duplicates(subset=["city", "ts"]).reset_index(drop=True)
    return df


def test_weather_future_hour_rain_does_not_leak():
    """§4.4 Test 1: Adding 50mm rain at or after post_time hour must not change rain_24h or rain_72h."""
    raw = _make_synthetic_history()
    raw["post_time"] = np.where(raw["race_no"] == 1, "14:30", "23:30")
    w1 = _make_synthetic_weather(raw["date"].unique())

    feat1 = build_features(raw, ref_end="2025-07-01", weather_df=w1)
    day1 = feat1[feat1["date"] == pd.Timestamp("2026-06-14")].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    # Inject 50mm rain at 14:00, 15:00, and 23:00 on 2026-06-14 (post_time for race 1 is 14:30; last full hour before 14:30 is 13:00)
    w2 = w1.copy()
    w2.loc[w2["ts"].isin(["2026-06-14T14:00", "2026-06-14T15:00", "2026-06-14T23:00"]), "precip_mm"] = 50.0
    feat2 = build_features(raw, ref_end="2025-07-01", weather_df=w2)
    day2 = feat2[feat2["date"] == pd.Timestamp("2026-06-14")].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    r1_a = day1[day1["race_no"] == 1]
    r1_b = day2[day2["race_no"] == 1]
    pd.testing.assert_series_equal(r1_a["rain_24h"], r1_b["rain_24h"])
    pd.testing.assert_series_equal(r1_a["rain_72h"], r1_b["rain_72h"])

    # Also verify night race (23:30) does NOT include 23:00 hour (since last full hour strictly before 23:30 is 22:00)
    r2_a = day1[day1["race_no"] == 2]
    r2_b = day2[day2["race_no"] == 2]
    attr_23 = w1.copy()
    attr_23.loc[attr_23["ts"] == "2026-06-14T23:00", "precip_mm"] = 50.0
    feat_23 = build_features(raw, ref_end="2025-07-01", weather_df=attr_23)
    day_23 = feat_23[(feat_23["date"] == pd.Timestamp("2026-06-14")) & (feat_23["race_no"] == 2)].sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    pd.testing.assert_series_equal(r2_a["rain_24h"].reset_index(drop=True), day_23["rain_24h"])


def test_future_wet_race_does_not_change_horse_or_sire_wet_delta():
    """§4.4 Test 2: A future wet race must not change horse_wet_delta or sire_wet_delta on an earlier date."""
    raw = _make_synthetic_history()
    raw["post_time"] = "14:00"
    # Mark 2025-04-15 and 2026-07-05 as wet ('yumusak'), others as dry ('normal')
    raw["track_cond"] = np.where(raw["date"].isin(["2025-04-15", "2026-07-05"]), "yumusak", "normal")
    w = _make_synthetic_weather(raw["date"].unique())

    full_feat = build_features(raw, ref_end="2025-07-01", weather_df=w)
    target = pd.Timestamp("2026-06-14")
    day_full = full_feat[full_feat["date"] == target].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    # Remove all future races (> 2026-06-14) and mask same-day outcomes
    trunc = raw[pd.to_datetime(raw["date"]) <= target].copy()
    trunc.loc[pd.to_datetime(trunc["date"]) == target, ["finish", "time_s", "ganyan"]] = np.nan
    trunc_feat = build_features(trunc, ref_end="2025-07-01", weather_df=w)
    day_trunc = trunc_feat[trunc_feat["date"] == target].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    for col in ["horse_wet_delta", "horse_n_wet", "sire_wet_delta", "wet_x_horse_wet_delta", "wet_x_sire_wet_delta"]:
        pd.testing.assert_series_equal(day_full[col], day_trunc[col], check_exact=False, rtol=1e-12, atol=1e-12)


def test_missing_weather_produces_nan_without_error():
    """§4.4 Test 3: Missing city/hour weather produces NaN features gracefully and model fits without error."""
    from ganyan.features import get_hava_feature_cols
    from ganyan.model import fit_predict_df

    raw = _make_synthetic_history()
    raw["post_time"] = "15:00"
    # Pass empty weather DataFrame
    feat = build_features(raw, ref_end="2025-07-01", weather_df=pd.DataFrame())
    assert feat["rain_24h"].isna().all()
    assert feat["rain_72h"].isna().all()
    assert feat["temp_post"].isna().all()
    assert feat["wind_post"].isna().all()

    cols = get_hava_feature_cols()
    tr = feat[feat["date"] < pd.Timestamp("2026-06-14")]
    te = feat[feat["date"] >= pd.Timestamp("2026-06-14")]
    p = fit_predict_df(tr, te, cols)
    assert len(p) == len(te)
    assert np.all(np.isfinite(p))




def test_pedigree_features_ignore_sameday_and_future_results():
    from ganyan.features import SOY_COLS

    raw = _make_synthetic_history()
    target_day = pd.Timestamp("2026-06-14")
    base = build_features(raw, ref_end="2025-07-01")
    base = base[base["date"] == target_day].set_index(["race_id", "horse_key"])[SOY_COLS]

    mod = raw.copy()
    later = pd.to_datetime(mod["date"]) >= target_day
    mod.loc[later, "finish"] = 5 - mod.loc[later, "finish"]  # flip results on D and after
    mod.loc[later, "time_s"] = mod.loc[later, "time_s"] + 3.0
    flipped = build_features(mod, ref_end="2025-07-01")
    flipped = flipped[flipped["date"] == target_day].set_index(["race_id", "horse_key"])[SOY_COLS]

    pd.testing.assert_frame_equal(base.sort_index(), flipped.sort_index())


def test_pedigree_features_use_prior_offspring_only():
    raw = _make_synthetic_history()
    out = build_features(raw, ref_end="2025-07-01")
    first = out[out["date"] == pd.Timestamp("2025-02-10")]
    assert (first["sire_n"] == 0).all() and (first["dam_n"] == 0).all()
    assert np.allclose(first["sire_fpct"], 0.5)
    later = out[out["date"] == pd.Timestamp("2026-07-05")]
    assert (later["sire_n"] > 0).all()


def test_stablemate_features_count_mates_and_ignore_results():
    from ganyan.features import STABLE_COLS

    pair_keys = ["SIRE_0|DAM_0|2022", "SIRE_1|DAM_1|2022"]
    raw = _make_synthetic_history()
    raw["owner"] = np.where(raw["horse_key"].isin(pair_keys), "A", "SOLO_" + raw["horse_key"])
    out = build_features(raw, ref_end="2025-07-01")
    pair = out[out["horse_key"].isin(pair_keys)]
    assert (pair["own_mates"] == 1).all()
    assert pair.groupby("race_id")["own_is_top"].sum().eq(1).all()
    solo = out[~out["horse_key"].isin(pair_keys)]
    assert (solo["own_mates"] == 0).all() and (solo["own_is_top"] == 0).all()

    mod = raw.copy()
    mod["finish"] = 5 - mod["finish"]
    mod["time_s"] = mod["time_s"] + 3.0
    flipped = build_features(mod, ref_end="2025-07-01")
    a = out.set_index(["race_id", "horse_key"])[STABLE_COLS].sort_index()
    b = flipped.set_index(["race_id", "horse_key"])[STABLE_COLS].sort_index()
    pd.testing.assert_frame_equal(a, b)
