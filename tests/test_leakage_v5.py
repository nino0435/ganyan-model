"""Strict temporal and same-day leakage tests for Model v5 feature blocks (S, G, R)."""
import numpy as np
import pandas as pd
import pytest

from ganyan.features import build_features
from ganyan.features_v5 import BLOCK_COLS, attach_G, attach_R, attach_S, attach_v5


def _make_synthetic_v5_dataset():
    """Create multi-year synthetic races, `ext` ratings, and `workouts` around D = 2026-06-14.

    Ensures >=20 runners per (city, surface, distance, breed) in 2025 and >=15 timed runners
    per (date, city) so `par_t`, `day_var`, `sfa_*`, and `g_last_d400_rel` are all non-trivial.
    """
    dates = [
        "2025-02-10",
        "2025-04-15",
        "2025-06-20",
        "2025-09-10",
        "2026-05-01",
        "2026-05-25",
        "2026-06-14",  # target day D
        "2026-06-20",
        "2026-07-05",
    ]
    horses = [f"SIRE_{i}|DAM_{i}|2021" for i in range(16)]
    jockeys = [f"J_{i % 5}" for i in range(16)]
    trainers = [f"T_{i % 4}" for i in range(16)]

    rng = np.random.default_rng(123)
    race_rows = []
    ext_rows = []
    workout_rows = []

    for d_idx, d in enumerate(dates):
        for r_no in (1, 2):
            race_id = f"{d}_Ankara_{r_no}"
            subset = horses[:8] if r_no == 1 else horses[8:]
            finishes = rng.permutation(np.arange(1, 9))
            for h_pos, (hk, fin) in enumerate(zip(subset, finishes)):
                idx = int(hk.split("_")[1].split("|")[0])
                time_val = (84.0 if r_no == 1 else 98.0) + float(fin) * 0.35 + d_idx * 0.08 + (idx % 3) * 0.05
                race_rows.append(
                    {
                        "race_id": race_id,
                        "date": d,
                        "city": "Ankara",
                        "race_no": r_no,
                        "prog_no": h_pos + 1,
                        "horse_key": hk,
                        "name": f"AT {idx}",
                        "age": 4,
                        "sex": "d" if idx % 2 == 0 else "e",
                        "sire": f"SIRE_{idx}",
                        "dam": f"DAM_{idx}",
                        "weight": 55.0 + (h_pos % 5) * 0.5,
                        "jockey": jockeys[idx],
                        "owner": f"OWN_{idx % 6}",
                        "trainer": trainers[idx],
                        "gate": h_pos + 1,
                        "hp": 45.0 + idx * 1.5,
                        "breed": "Ingiliz" if r_no == 1 else "Arap",
                        "distance": 1400 if r_no == 1 else 1600,
                        "surface": "Çim" if r_no == 1 else "Kum",
                        "son6": "Ç1K2Ç3",
                        "kgs": 15 + (idx % 5),
                        "s20": 16,
                        "best_time_s": 84.5 if r_no == 1 else 98.5,
                        "finish": int(fin),
                        "time_s": time_val,
                        "ganyan": 1.8 + float(fin) * 1.4,
                        "agf_close": 48.0 / float(fin),
                        "agf_close_rank": int(fin),
                        "scratched": 0,
                    }
                )
                ext_rows.append(
                    {
                        "race_id": race_id,
                        "horse_key": hk,
                        "value": float(80 - fin * 4 + (d_idx % 4)),
                    }
                )

    # Workouts before D (within 60d, 30d, 14d), ON D, and AFTER D
    workout_dates = [
        "2026-04-20",  # 55 days before D
        "2026-05-20",  # 25 days before D
        "2026-06-05",  # 9 days before D
        "2026-06-14",  # ON day D (must NOT be used on D)
        "2026-06-18",  # AFTER day D (must NOT leak into D)
        "2026-07-02",  # AFTER day D
    ]
    for wd_i, wd in enumerate(workout_dates):
        for h_i, hk in enumerate(horses[:12]):
            workout_rows.append(
                {
                    "source": "liderform",
                    "horse_key": hk,
                    "horse_name": f"AT {h_i}",
                    "date": pd.Timestamp(wd),
                    "city": "Ankara",
                    "kind": "SPRINT" if (h_i + wd_i) % 2 == 0 else "GALOP",
                    "d800": 50.0 + h_i * 0.2 - wd_i * 0.1,
                    "d600": 37.0 + h_i * 0.15,
                    "d400": 24.2 + h_i * 0.12 - wd_i * 0.05,
                    "effort": "ALLOUT" if (h_i + wd_i) % 3 == 0 else "CANTER",
                }
            )

    runners_df = pd.DataFrame(race_rows)
    ext_df = pd.DataFrame(ext_rows)
    workouts_df = pd.DataFrame(workout_rows)
    return runners_df, ext_df, workouts_df


def _truncate_for_day_d(runners_df, ext_df, workouts_df, target_day, drop_sameday_ext=True):
    """Delete rows > D, mask outcomes on D, and filter ext/workouts to strictly < D."""
    d_ts = pd.Timestamp(target_day)
    r_dt = pd.to_datetime(runners_df["date"])
    trunc_r = runners_df[r_dt <= d_ts].copy()
    mask_d = pd.to_datetime(trunc_r["date"]) == d_ts
    for col in ("finish", "time_s", "ganyan", "agf_close", "agf_close_rank"):
        if col in trunc_r.columns:
            trunc_r.loc[mask_d, col] = np.nan

    # Shuffle rows so tie-breaking cannot accidentally rely on finish-sorted input order
    trunc_r = trunc_r.sample(frac=1.0, random_state=77).reset_index(drop=True)

    if drop_sameday_ext:
        keep_rids = set(runners_df.loc[r_dt < d_ts, "race_id"])
    else:
        keep_rids = set(runners_df.loc[r_dt <= d_ts, "race_id"])
    trunc_ext = ext_df[ext_df["race_id"].isin(keep_rids)].copy().reset_index(drop=True)

    w_dt = pd.to_datetime(workouts_df["date"])
    trunc_w = workouts_df[w_dt < d_ts].copy().reset_index(drop=True)
    return trunc_r, trunc_ext, trunc_w


@pytest.mark.parametrize("block", ["S", "G", "R"])
def test_each_block_no_future_or_sameday_leakage(block):
    runners_df, ext_df, workouts_df = _make_synthetic_v5_dataset()
    target_day = pd.Timestamp("2026-06-14")
    ref_end = "2026-01-01"

    # (1) Full dataset (including future races, day-D outcomes, and >= D ext/workouts)
    full_base = build_features(runners_df, ref_end=ref_end)
    full_v5 = attach_v5(full_base, {"ext": ext_df, "workouts": workouts_df}, blocks=(block,))
    day_full = (
        full_v5[full_v5["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    # (2) Truncated dataset: delete > D rows, mask D outcomes, delete >= D ext/workouts
    trunc_r, trunc_ext, trunc_w = _truncate_for_day_d(
        runners_df, ext_df, workouts_df, target_day, drop_sameday_ext=True
    )
    trunc_base = build_features(trunc_r, ref_end=ref_end)
    trunc_v5 = attach_v5(trunc_base, {"ext": trunc_ext, "workouts": trunc_w}, blocks=(block,))
    day_trunc = (
        trunc_v5[trunc_v5["date"] == target_day]
        .sort_values(["race_id", "horse_key"])
        .reset_index(drop=True)
    )

    assert len(day_full) == len(day_trunc) == 16
    for col in BLOCK_COLS[block]:
        pd.testing.assert_series_equal(
            day_full[col],
            day_trunc[col],
            check_names=True,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
            obj=f"Block {block} column '{col}' leaked future or same-day information!",
        )

    # Ensure key columns actually carry non-trivial finite values on day D
    if block == "S":
        assert day_full["yb_hiz_last"].notna().all()
        assert day_full["sfa_last"].notna().all()
    elif block == "G":
        assert day_full["g_last_d400"].notna().any()
        assert day_full["g_last_d400_rel"].notna().any()
        assert day_full["g_last_d400"].isna().any()  # horses 12..15 have no workouts
    elif block == "R":
        assert (day_full["elo_h"] != 0.0).any()
        assert (day_full["elo_j"] != 0.0).any()
        assert (day_full["elo_t"] != 0.0).any()


def test_all_blocks_combined_and_sameday_ext_ignored():
    runners_df, ext_df, workouts_df = _make_synthetic_v5_dataset()
    target_day = pd.Timestamp("2026-06-14")
    ref_end = "2026-01-01"

    full_v5 = attach_v5(
        build_features(runners_df, ref_end=ref_end),
        {"ext": ext_df, "workouts": workouts_df},
        blocks=("S", "G", "R"),
    )
    day_full = full_v5[full_v5["date"] == target_day].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    # Keep day-D ext rows (delete only > D ext rows) to verify day-D ext ratings are also ignored on D
    trunc_r, trunc_ext_with_d, trunc_w = _truncate_for_day_d(
        runners_df, ext_df, workouts_df, target_day, drop_sameday_ext=False
    )
    trunc_v5 = attach_v5(
        build_features(trunc_r, ref_end=ref_end),
        {"ext": trunc_ext_with_d, "workouts": trunc_w},
        blocks=("S", "G", "R"),
    )
    day_trunc = trunc_v5[trunc_v5["date"] == target_day].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    for blk in ("S", "G", "R"):
        for col in BLOCK_COLS[blk]:
            pd.testing.assert_series_equal(
                day_full[col],
                day_trunc[col],
                check_exact=False,
                rtol=1e-12,
                atol=1e-12,
            )


def test_workout_on_day_d_does_not_change_G_columns():
    runners_df, _ext_df, workouts_df = _make_synthetic_v5_dataset()
    target_day = pd.Timestamp("2026-06-14")
    base = build_features(runners_df, ref_end="2026-01-01")

    w_without_d = workouts_df[pd.to_datetime(workouts_df["date"]) != target_day].copy()
    w_with_extreme_d = w_without_d.copy()
    extra_d = []
    for i in range(16):
        extra_d.append(
            {
                "source": "liderform",
                "horse_key": f"SIRE_{i}|DAM_{i}|2021",
                "horse_name": f"AT {i}",
                "date": target_day,
                "city": "Ankara",
                "kind": "SPRINT",
                "d800": 44.0,
                "d600": 32.0,
                "d400": 20.5,
                "effort": "ALLOUT",
            }
        )
    w_with_extreme_d = pd.concat([w_without_d, pd.DataFrame(extra_d)], ignore_index=True)

    g_a = attach_G(base, w_without_d)
    g_b = attach_G(base, w_with_extreme_d)

    day_a = g_a[g_a["date"] == target_day].sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    day_b = g_b[g_b["date"] == target_day].sort_values(["race_id", "horse_key"]).reset_index(drop=True)

    for col in BLOCK_COLS["G"]:
        pd.testing.assert_series_equal(
            day_a[col],
            day_b[col],
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
            obj=f"Day-D workout leaked into '{col}'!",
        )


def test_elo_day_frozen_race2_independent_of_sameday_race1():
    """Second race on day D must not depend on first race's result on day D (even for shared jockey/trainer)."""
    runners_df, _ext_df, _w_df = _make_synthetic_v5_dataset()
    target_day = "2026-06-14"

    # Force shared jockeys & trainers across race 1 and race 2 on day D
    mask_d = runners_df["date"] == target_day
    runners_df = runners_df.copy()
    runners_df.loc[mask_d, "jockey"] = np.where(runners_df.loc[mask_d, "prog_no"] <= 4, "J_0", "J_1")
    runners_df.loc[mask_d, "trainer"] = np.where(runners_df.loc[mask_d, "prog_no"] <= 4, "T_0", "T_1")

    # Scenario A: original race 1 results on day D
    df_a = attach_R(build_features(runners_df, ref_end="2026-01-01"))

    # Scenario B: invert race 1 results on day D completely (and also test cancelling/NaN-ing race 1)
    mod_b = runners_df.copy()
    mask_d_r1 = (mod_b["date"] == target_day) & (mod_b["race_no"] == 1)
    mod_b.loc[mask_d_r1, "finish"] = 9 - mod_b.loc[mask_d_r1, "finish"]
    df_b = attach_R(build_features(mod_b, ref_end="2026-01-01"))

    # Scenario C: race 1 on day D has no winner (all finish = NaN)
    mod_c = runners_df.copy()
    mod_c.loc[mask_d_r1, "finish"] = np.nan
    df_c = attach_R(build_features(mod_c, ref_end="2026-01-01"))

    r2_a = (
        df_a[(df_a["date"] == pd.Timestamp(target_day)) & (df_a["race_no"] == 2)]
        .sort_values("horse_key")
        .reset_index(drop=True)
    )
    r2_b = (
        df_b[(df_b["date"] == pd.Timestamp(target_day)) & (df_b["race_no"] == 2)]
        .sort_values("horse_key")
        .reset_index(drop=True)
    )
    r2_c = (
        df_c[(df_c["date"] == pd.Timestamp(target_day)) & (df_c["race_no"] == 2)]
        .sort_values("horse_key")
        .reset_index(drop=True)
    )

    for col in BLOCK_COLS["R"]:
        pd.testing.assert_series_equal(r2_a[col], r2_b[col], check_exact=False, rtol=1e-12, atol=1e-12)
        pd.testing.assert_series_equal(r2_a[col], r2_c[col], check_exact=False, rtol=1e-12, atol=1e-12)

    # Confirm day-D race 1 outcome DOES update Elo on a subsequent day (> D)
    next_a = df_a[df_a["date"] == pd.Timestamp("2026-06-20")].sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    next_b = df_b[df_b["date"] == pd.Timestamp("2026-06-20")].sort_values(["race_id", "horse_key"]).reset_index(drop=True)
    assert not np.allclose(next_a["elo_h"].to_numpy(), next_b["elo_h"].to_numpy())
