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


WET_TRACK_CONDS = frozenset({"nemli", "islak", "agir", "yumusak"})
TRACK_COND_CATS = ["normal", "yumusak", "nemli", "islak", "agir", "kuru"]
SURFACES_FOR_COND = ["Çim", "Kum", "Sentetik"]


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


def get_hava_feature_cols(include_track_cond=True):
    """Return v2_agf_hava feature column list = v1_agf + weather/track features (§4)."""
    _, with_agf = get_feature_cols()
    hava_cols = [
        "rain_24h",
        "rain_72h",
        "temp_post",
        "wind_post",
        "wet",
        "horse_wet_delta",
        "horse_n_wet",
        "sire_wet_delta",
        "wet_x_horse_wet_delta",
        "wet_x_sire_wet_delta",
    ]
    if include_track_cond:
        for s_lbl in ("cim", "kum", "sentetik"):
            for c_lbl in TRACK_COND_CATS:
                hava_cols.append(f"{s_lbl}_{c_lbl}")
    return with_agf + hava_cols


SOY_COLS = [
    "sire_n",
    "sire_wr",
    "sire_fpct",
    "sire_surf_fpct",
    "sire_dist_fpct",
    "dam_n",
    "dam_fpct",
]


def get_soy_feature_cols():
    """Return v3_agf_soy feature column list = v1_agf + pedigree (sire/dam) features."""
    _, with_agf = get_feature_cols()
    return with_agf + SOY_COLS


STABLE_COLS = [
    "own_mates",
    "own_mate_agf",
    "own_is_top",
    "trn_mates",
    "trn_mate_agf",
    "trn_is_top",
]


def get_stable_feature_cols():
    """Return v4_agf_ahir feature column list = v1_agf + same-owner / same-trainer entry features."""
    _, with_agf = get_feature_cols()
    return with_agf + STABLE_COLS


def _attach_stable(df):
    """Same-race stablemate features from program columns only (owner/trainer/AGF known pre-race)."""
    for who, p in (("owner", "own"), ("trainer", "trn")):
        key = df[who].astype("string").str.strip().replace("", pd.NA)
        g = df.groupby(["race_id", key])
        share = df["agf_share"].fillna(0.0)
        n = g["race_id"].transform("size").where(key.notna(), 1)
        tot = share.groupby([df["race_id"], key]).transform("sum").where(key.notna(), share)
        df[f"{p}_mates"] = (n - 1).astype(float)
        df[f"{p}_mate_agf"] = tot - share
        top = share.groupby([df["race_id"], key]).transform("max")
        df[f"{p}_is_top"] = ((share >= top) & (n > 1)).astype(float)
    return df


def _prior_sums(df, keys, cols):
    """Per-row sums of `cols` over the same `keys` group on dates strictly before the row's date."""
    day = df.groupby(keys + ["date"])[cols].sum()
    prior = day.groupby(level=list(range(len(keys)))).cumsum() - day
    return df[keys + ["date"]].join(prior, on=keys + ["date"])[cols]


def _attach_pedigree(df):
    """Leak-free sire/dam features: offspring results strictly before day D, shrunk toward the prior."""
    if "sire" not in df.columns:
        df["sire"] = df["horse_key"].str.split("|").str[0]
    if "dam" not in df.columns:
        df["dam"] = df["horse_key"].str.split("|").str[1]
    for c in ("sire", "dam"):
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    df["_dist_b"] = pd.cut(df["distance"], [0, 1399, 1799, 99999], labels=False)

    valid = df["fpct"].notna()
    df["_v"] = valid.astype(float)
    df["_f"] = df["fpct"].where(valid, 0.0)
    df["_w"] = df["win"].fillna(0.0)

    def shrunk(keys, k, prior):
        sub = df.dropna(subset=keys)
        pr = _prior_sums(sub, keys, ["_v", "_f", "_w"])
        return pr["_v"], (pr["_f"] + prior * k) / (pr["_v"] + k), (pr["_w"] + 0.1 * 10) / (pr["_v"] + 10)

    n, fp, wr = shrunk(["sire"], 20.0, 0.5)
    df["sire_n"], df["sire_fpct"], df["sire_wr"] = n, fp, wr
    df["sire_surf_fpct"] = shrunk(["sire", "surface"], 20.0, 0.5)[1]
    df["sire_dist_fpct"] = shrunk(["sire", "_dist_b"], 20.0, 0.5)[1]
    n, fp, _ = shrunk(["dam"], 10.0, 0.5)
    df["dam_n"], df["dam_fpct"] = n, fp
    for c in ("sire_n", "dam_n"):
        df[c] = df[c].fillna(0.0)

    return df.drop(columns=["_dist_b", "_v", "_f", "_w"])


def _attach_race_weather(df, weather_df):
    """Compute leak-free race-level weather features strictly before post_time (§4.1, §6.4)."""
    if weather_df is None or len(weather_df) == 0:
        df["rain_24h"] = np.nan
        df["rain_72h"] = np.nan
        df["temp_post"] = np.nan
        df["wind_post"] = np.nan
        return df

    # Build distinct (race_id, city, date, post_time) table
    races = df[["race_id", "city", "date", "post_time"]].drop_duplicates("race_id").copy()
    w = weather_df.copy()
    w["ts_dt"] = pd.to_datetime(w["ts"])
    w = w.sort_values(["city", "ts_dt"]).reset_index(drop=True)

    by_city = {}
    for city, grp in w.groupby("city", sort=False):
        # Index by exact hourly timestamp for O(1)/fast slice lookup
        s_idx = grp.set_index("ts_dt")
        by_city[city] = s_idx

    r24_list, r72_list, temp_list, wind_list = [], [], [], []
    for _, r in races.iterrows():
        city = r["city"]
        pt = r["post_time"]
        d_str = pd.Timestamp(r["date"]).strftime("%Y-%m-%d")
        if city not in by_city or not isinstance(pt, str) or ":" not in pt:
            r24_list.append(np.nan)
            r72_list.append(np.nan)
            temp_list.append(np.nan)
            wind_list.append(np.nan)
            continue

        hh_str, mm_str = pt.strip().split(":", 1)
        hh = int(hh_str)
        mm = int(mm_str)
        race_dt = pd.Timestamp(f"{d_str} {hh:02d}:{mm:02d}:00")
        # Last full hour strictly before post_time (post_time hour itself is NOT included per §4.1)
        last_hour = pd.Timestamp(f"{d_str} {hh:02d}:00:00") - pd.Timedelta(hours=1)
        start_24 = last_hour - pd.Timedelta(hours=23)
        start_72 = last_hour - pd.Timedelta(hours=71)

        c_df = by_city[city]
        sub_72 = c_df.loc[start_72:last_hour]
        if len(sub_72) == 0:
            r24_list.append(np.nan)
            r72_list.append(np.nan)
            temp_list.append(np.nan)
            wind_list.append(np.nan)
            continue

        sub_24 = sub_72.loc[start_24:last_hour]
        r24_list.append(float(sub_24["precip_mm"].sum()) if len(sub_24) > 0 and sub_24["precip_mm"].notna().any() else np.nan)
        r72_list.append(float(sub_72["precip_mm"].sum()) if sub_72["precip_mm"].notna().any() else np.nan)

        if last_hour in sub_72.index:
            last_row = sub_72.loc[last_hour]
            if isinstance(last_row, pd.DataFrame):
                last_row = last_row.iloc[-1]
            temp_list.append(float(last_row["temp_c"]) if pd.notna(last_row["temp_c"]) else np.nan)
            wind_list.append(float(last_row["wind_kmh"]) if pd.notna(last_row["wind_kmh"]) else np.nan)
        else:
            temp_list.append(np.nan)
            wind_list.append(np.nan)

    races["rain_24h"] = r24_list
    races["rain_72h"] = r72_list
    races["temp_post"] = temp_list
    races["wind_post"] = wind_list

    return df.merge(
        races[["race_id", "rain_24h", "rain_72h", "temp_post", "wind_post"]],
        on="race_id",
        how="left",
    )


def build_features(runners_df, ref_end="2025-07-01", weather_df=None):
    """Build leak-free features from runners dataframe (and optional weather_df).

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

    # Defragment before adding weather/track features
    df = df.copy()

    # --- Weather and Track Condition Features (§4.1, §4.2, §4.3)
    if "post_time" not in df.columns:
        df["post_time"] = None
    df = _attach_race_weather(df, weather_df)

    has_tc = "track_cond" in df.columns and df["track_cond"].notna().any()
    if not has_tc:
        df["track_cond"] = "bilinmiyor"
    else:
        df["track_cond"] = df["track_cond"].fillna("bilinmiyor")

    # One-hot surface x track_cond interaction columns (§4.1)
    surf_map_lbl = {"Çim": "cim", "Kum": "kum", "Sentetik": "sentetik"}
    s_lbl_series = df["surface"].map(surf_map_lbl).fillna("diger")
    cond_cols_dict = {}
    for s_lbl in ("cim", "kum", "sentetik"):
        for c_lbl in TRACK_COND_CATS:
            cond_cols_dict[f"{s_lbl}_{c_lbl}"] = (
                (s_lbl_series == s_lbl) & (df["track_cond"] == c_lbl)
            ).astype(int)

    # Wet definition (§4.2): track_cond in {nemli, islak, agir, yumusak} when known; fallback to rain_72h >= 5.0
    tc_known = df["track_cond"] != "bilinmiyor"
    tc_wet = df["track_cond"].isin(WET_TRACK_CONDS)
    rain_wet = df["rain_72h"].fillna(0.0) >= 5.0
    cond_cols_dict["wet"] = np.where(tc_known, tc_wet, rain_wet).astype(int)
    df = pd.concat([df, pd.DataFrame(cond_cols_dict, index=df.index)], axis=1)

    # Horse wet vs dry prior normalized finish (fpct) delta (§4.3)
    # Only prior completed starts with valid fpct count; a horse runs at most once per day so cumsum()-current is strictly < D
    valid_fpct = df["fpct"].notna()
    is_wet_valid = (df["wet"] == 1) & valid_fpct
    is_dry_valid = (df["wet"] == 0) & valid_fpct

    df["_w_cnt"] = is_wet_valid.astype(int)
    df["_w_sum"] = np.where(is_wet_valid, df["fpct"], 0.0)
    df["_d_cnt"] = is_dry_valid.astype(int)
    df["_d_sum"] = np.where(is_dry_valid, df["fpct"], 0.0)

    hg = df.groupby("horse_key", sort=False)
    h_n_wet = hg["_w_cnt"].cumsum() - df["_w_cnt"]
    h_s_wet = hg["_w_sum"].cumsum() - df["_w_sum"]
    h_n_dry = hg["_d_cnt"].cumsum() - df["_d_cnt"]
    h_s_dry = hg["_d_sum"].cumsum() - df["_d_sum"]

    h_mean_wet = np.where(h_n_wet > 0, h_s_wet / np.maximum(h_n_wet, 1), np.nan)
    h_mean_dry = np.where(h_n_dry > 0, h_s_dry / np.maximum(h_n_dry, 1), np.nan)
    h_raw_delta = np.where((h_n_wet > 0) & (h_n_dry > 0), h_mean_wet - h_mean_dry, 0.0)
    df["horse_n_wet"] = h_n_wet.astype(float)
    df["horse_wet_delta"] = h_raw_delta * (h_n_wet / (h_n_wet + 5.0))

    # Sire wet vs dry prior normalized finish delta across all offspring strictly before current day (< D) (§4.3)
    if "sire" not in df.columns:
        df["sire"] = df["horse_key"].str.split("|").str[0]
    s_day = df.groupby(["sire", "date"])[["_w_cnt", "_w_sum", "_d_cnt", "_d_sum"]].sum()
    s_cum = s_day.groupby(level=0).cumsum()
    s_prior = (s_cum - s_day).rename(
        columns={
            "_w_cnt": "_sw_cnt",
            "_w_sum": "_sw_sum",
            "_d_cnt": "_sd_cnt",
            "_d_sum": "_sd_sum",
        }
    )
    df = df.join(s_prior, on=["sire", "date"])
    sw_cnt = df["_sw_cnt"].fillna(0.0)
    sd_cnt = df["_sd_cnt"].fillna(0.0)
    s_mean_wet = np.where(sw_cnt > 0, df["_sw_sum"] / np.maximum(sw_cnt, 1.0), np.nan)
    s_mean_dry = np.where(sd_cnt > 0, df["_sd_sum"] / np.maximum(sd_cnt, 1.0), np.nan)
    s_raw_delta = np.where((sw_cnt > 0) & (sd_cnt > 0), s_mean_wet - s_mean_dry, 0.0)
    df["sire_wet_delta"] = s_raw_delta * (sw_cnt / (sw_cnt + 20.0))

    df["wet_x_horse_wet_delta"] = df["wet"] * df["horse_wet_delta"]
    df["wet_x_sire_wet_delta"] = df["wet"] * df["sire_wet_delta"]

    df = df.drop(
        columns=["_w_cnt", "_w_sum", "_d_cnt", "_d_sum", "_sw_cnt", "_sw_sum", "_sd_cnt", "_sd_sum"]
    )

    return _attach_stable(_attach_pedigree(df))
