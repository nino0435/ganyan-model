"""Leak-free pre-race feature builder for Ganyan model."""
import numpy as np
import pandas as pd
from ganyan.parse_program import parse_son6

SURF_LETTER = {"Çim": "Ç", "Kum": "K", "Sentetik": "S"}


def _extract_son6_stats(son6_series, surface_series):
    """Extract (son6_last, son6_mean, son6_same_surf) from raw or parsed son6 values."""
    last_vals = []
    mean_vals = []
    same_vals = []
    for raw, surf in zip(son6_series, surface_series):
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, str):
            items = parse_son6(raw)
        else:
            items = []
        if not items:
            last_vals.append(np.nan)
            mean_vals.append(np.nan)
            same_vals.append(np.nan)
            continue
        # Treat '0' as 10 (outside top 9 / unplaced) for numeric summary
        finishes = [10.0 if f == 0 else float(f) for _, f in items]
        last_vals.append(finishes[-1])
        mean_vals.append(float(np.mean(finishes)))
        target_letter = SURF_LETTER.get(surf, "")
        if target_letter:
            same_vals.append(sum(1 for s, _ in items if s == target_letter) / len(items))
        else:
            same_vals.append(np.nan)
    return last_vals, mean_vals, same_vals


def get_feature_cols(df=None):
    """Return (BASE, WITH_AGF) feature column lists."""
    base = [
        "h_n",
        "h_wr",
        "h_t3r",
        "h_fpct_last",
        "h_fpct_m3",
        "h_sf_last",
        "h_sf_m3",
        "h_sf_best",
        "h_beaten_last",
        "h_beaten_m3",
        "h_logodds_last",
        "h_logodds_m3",
        "h_days",
        "h_dist_chg",
        "h_same_surf",
        "j_n",
        "j_wr",
        "t_n",
        "t_wr",
        "weight",
        "hp",
        "age",
        "sex_d",
        "gate",
        "gate_frac",
        "field",
        "distance",
        "surf",
        "arap",
        "son6_last",
        "son6_mean",
        "son6_same_surf",
        "kgs",
        "s20",
        "best_sf",
    ]
    rel_cols = ["weight", "hp", "h_sf_m3", "h_sf_best", "j_wr", "h_logodds_m3", "h_fpct_m3"]
    for c in rel_cols:
        base.append(f"{c}_rel")
        base.append(f"{c}_rk")
    with_agf = base + ["agf_share", "log_agf"]
    return base, with_agf


def build_features(runners_df, ref_end="2025-07-01"):
    """Build leak-free features from runners dataframe.

    Every pre-race feature on day D depends strictly on days < D and pre-race program columns.
    Speed-figure reference medians are computed strictly on dates < ref_end.
    """
    df = runners_df.copy()
    if "scratched" in df.columns:
        df = df[df["scratched"].fillna(0) == 0].copy()

    # Standardize column aliases between SQLite and legacy runs.pkl
    if "horse_key" not in df.columns and "horse" in df.columns:
        df["horse_key"] = df["horse"]
    if "time_s" not in df.columns and "time" in df.columns:
        df["time_s"] = df["time"]
    if "agf_close" not in df.columns and "agf_pct" in df.columns:
        df["agf_close"] = df["agf_pct"]

    df["date"] = pd.to_datetime(df["date"])
    ref_ts = pd.Timestamp(ref_end)

    # IMPORTANT: Sort deterministically by pre-race keys (never by finish!) so tie-breaking is leak-free
    sort_cols = ["date", "city", "race_no", "horse_key"]
    df = df.sort_values(sort_cols).reset_index(drop=True)

    df["win"] = (df["finish"] == 1).astype(float).where(df["finish"].notna(), np.nan)
    df["top3"] = (df["finish"] <= 3).astype(float).where(df["finish"].notna(), np.nan)
    df["field"] = df.groupby("race_id")["horse_key"].transform("size")
    df["fpct"] = (df["finish"] - 1) / (df["field"] - 1).clip(lower=1)

    # --- Speed figure: time_s vs reference median for same track/surface/distance/breed (strictly < ref_ts)
    ref = df[(df["date"] < ref_ts) & df["time_s"].notna()]
    med_fine = ref.groupby(["city", "surface", "distance", "breed"])["time_s"].agg(["median", "size"])
    med_coarse = ref.groupby(["surface", "distance", "breed"])["time_s"].median().rename("med_c")
    df = df.join(med_fine, on=["city", "surface", "distance", "breed"]).join(
        med_coarse, on=["surface", "distance", "breed"]
    )
    df["ref_t"] = np.where(df["size"] >= 20, df["median"], df["med_c"])
    df["sf"] = (df["ref_t"] - df["time_s"]) / df["ref_t"] * 1000.0

    win_t = df[df["finish"] == 1].groupby("race_id")["time_s"].min()
    df["beaten"] = (df["time_s"] - df["race_id"].map(win_t)) / df["distance"] * 1000.0
    df["logodds"] = np.log(df["ganyan"].clip(lower=1.01))

    # --- Horse history (a horse runs at most once per day, so shift(1) is strictly earlier days)
    g = df.groupby("horse_key", sort=False)
    df["h_n"] = g.cumcount()
    win_zero = df["win"].fillna(0.0)
    top3_zero = df["top3"].fillna(0.0)
    df["h_w"] = win_zero.groupby(df["horse_key"]).cumsum() - win_zero
    df["h_top3"] = top3_zero.groupby(df["horse_key"]).cumsum() - top3_zero
    df["h_wr"] = (df["h_w"] + 0.3) / (df["h_n"] + 3.0)
    df["h_t3r"] = (df["h_top3"] + 0.9) / (df["h_n"] + 3.0)

    for col in ["fpct", "sf", "beaten", "logodds"]:
        sh = g[col].shift(1)
        df[f"h_{col}_last"] = sh
        df[f"h_{col}_m3"] = sh.groupby(df["horse_key"]).transform(
            lambda s: s.rolling(3, min_periods=1).mean()
        )
    df["h_sf_best"] = g["sf"].shift(1).groupby(df["horse_key"]).cummax()
    prev_date = g["date"].shift(1)
    df["h_days"] = (df["date"] - prev_date).dt.days
    df["h_dist_chg"] = df["distance"] - g["distance"].shift(1)
    df["h_same_surf"] = (g["surface"].shift(1) == df["surface"]).astype(float).where(prev_date.notna())

    # --- Jockey / trainer prior win rates (counts strictly up to previous day)
    df["_win_z"] = win_zero
    for who, p in [("jockey", "j"), ("trainer", "t")]:
        day = df.groupby([who, "date"])["_win_z"].agg(["size", "sum"]).groupby(level=0).cumsum()
        day_now = df.groupby([who, "date"])["_win_z"].agg(["size", "sum"])
        prior = (day - day_now).rename(columns={"size": f"{p}_n", "sum": f"{p}_w"})
        df = df.join(prior, on=[who, "date"])
        df[f"{p}_wr"] = (df[f"{p}_w"] + 1.0) / (df[f"{p}_n"] + 10.0)
    df = df.drop(columns=["_win_z"])

    # --- Program-derived features (known before race)
    for prog_col in ["son6", "kgs", "s20", "best_time_s"]:
        if prog_col not in df.columns:
            df[prog_col] = np.nan

    s6_last, s6_mean, s6_same = _extract_son6_stats(df["son6"], df["surface"])
    df["son6_last"] = s6_last
    df["son6_mean"] = s6_mean
    df["son6_same_surf"] = s6_same
    df["kgs"] = pd.to_numeric(df["kgs"], errors="coerce")
    df["s20"] = pd.to_numeric(df["s20"], errors="coerce")
    df["best_time_s"] = pd.to_numeric(df["best_time_s"], errors="coerce")
    df["best_sf"] = (df["ref_t"] - df["best_time_s"]) / df["ref_t"] * 1000.0

    # --- Race-relative features (known before the race)
    rg = df.groupby("race_id")
    for col in ["weight", "hp", "h_sf_m3", "h_sf_best", "j_wr", "h_logodds_m3", "h_fpct_m3"]:
        df[f"{col}_rel"] = df[col] - rg[col].transform("mean")
        df[f"{col}_rk"] = rg[col].rank(ascending=col in ("h_logodds_m3", "h_fpct_m3"), pct=True)

    df["gate_frac"] = df["gate"] / df["field"]
    df["arap"] = (df["breed"] == "Arap").astype(int)
    df["surf"] = df["surface"].map({"Çim": 0, "Kum": 1, "Sentetik": 2})
    df["sex_d"] = (df["sex"] == "d").astype(int)

    agf_sum = rg["agf_close"].transform("sum")
    df["agf_share"] = np.where(agf_sum > 0, df["agf_close"] / agf_sum, np.nan)
    df["log_agf"] = np.log(df["agf_share"].clip(lower=1e-4))

    return df
