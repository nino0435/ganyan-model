"""Leak-free v7 pre-race feature blocks (T: equipment, C: class/opponents, J: jockey/weight, P: track/distance)."""
import re
import numpy as np
import pandas as pd

from ganyan.features_v5 import _clean_entity_str, _sorted_work_frame, _to_day_int
from ganyan.features_v6 import _to_f64

ALL_EQUIP_TOKENS = frozenset({
    "KG",
    "DB",
    "K",
    "KUL",
    "SK",
    "SKG",
    "GKR",
    "SGKR",
    "YP",
    "BB",
    "OG",
    "ÖG",
    "CG",
    "ÇG",
    "DS",
    "GK",
    "TGK",
})

T_COLS = [
    "eq_has_kg",
    "eq_has_db",
    "eq_has_k",
    "eq_kg_chg",
    "eq_db_chg",
    "eq_k_chg",
    "eq_first_kg_or_db",
    "eq_any_chg",
]

C_COLS = [
    "cls_tier",
    "cls_tier_chg",
    "opp_elo_chg",
    "opp_elo_chg_m3",
    "opp_hp_chg",
    "opp_elo_chg_rel",
]

J_COLS = [
    "j_elo_chg",
    "j_wr_chg",
    "j_same_prev",
    "hj_n",
    "hj_wr",
    "hj_fpct",
    "j_wr_30d",
    "h_weight_chg",
]

P_COLS = [
    "h_surf_n",
    "h_surf_t3r",
    "h_surf_fpct",
    "h_surf_sf_best",
    "h_surf_fpct_delta",
    "h_surf_fpct_rel",
    "h_dist_n",
    "h_dist_fpct",
    "h_dist_sf_best",
    "h_city_fpct",
]

V7_BLOCK_COLS = {
    "T": list(T_COLS),
    "C": list(C_COLS),
    "J": list(J_COLS),
    "P": list(P_COLS),
}

_KOSMAZ_RE = re.compile(r"\s*\(koşmaz\)", re.IGNORECASE)
_JOCKEY_AP_RE = re.compile(r"\s+AP\.?$", re.IGNORECASE)
_GRP_CLS_RE = re.compile(r"\b(?:G|GRUP)\s*[-\s]?[123]\b|\b(?:A|ACIK)\s*[-\s]?[123]\b")
_KV_CLS_RE = re.compile(r"\bKV\b|\bKISA\s*VADE")
_HK_CLS_RE = re.compile(r"\bHANDIKAP\s*(\d+)|\bH\s*[-]?\s*(\d+)")
_SARTLI_CLS_RE = re.compile(r"\bSARTLI\s*(\d+)")
_TR_UPPER_MAP = str.maketrans({"i": "I", "İ": "I", "ş": "S", "Ş": "S", "ğ": "G", "Ğ": "G", "ü": "U", "Ü": "U", "ö": "O", "Ö": "O", "ç": "C", "Ç": "C"})
_SENTINEL_NEG = -1e18


def parse_equip_tokens(name_raw):
    """Extract trailing equipment codes from `runners.name_raw` as an uppercase frozenset."""
    if name_raw is None or pd.isna(name_raw):
        return frozenset()
    s = _KOSMAZ_RE.sub("", str(name_raw)).strip()
    if not s:
        return frozenset()
    tokens = s.split()
    found = []
    while len(tokens) > 1 and tokens[-1].upper() in ALL_EQUIP_TOKENS:
        found.append(tokens.pop().upper())
    return frozenset(found)


def _canonical_equip_sig(toks):
    """Canonicalize equivalent K/KUL tokens for detecting any real equipment change."""
    if not toks:
        return ()
    return tuple(sorted("K" if t == "KUL" else t for t in toks))


def parse_cls_tier(cls_str):
    """Map `races.cls` string to difficulty tier `0.0..5.0` (NaN if missing/unknown)."""
    if cls_str is None or pd.isna(cls_str):
        return np.nan
    s = str(cls_str).strip()
    if not s:
        return np.nan
    u = s.translate(_TR_UPPER_MAP).upper()
    if _GRP_CLS_RE.search(u):
        return 5.0
    if _KV_CLS_RE.search(u):
        return 4.0
    if "MAIDEN" in u or "SATIS" in u:
        return 0.0
    mh = _HK_CLS_RE.search(u)
    if mh:
        val = int(mh.group(1) or mh.group(2))
        if val <= 15:
            return 1.0
        if val <= 17:
            return 2.0
        return 3.0
    ms = _SARTLI_CLS_RE.search(u)
    if ms:
        val = int(ms.group(1))
        if val in (1, 19):
            return 0.0
        if val <= 4:
            return 2.0
        return 3.0
    return np.nan


def _normalize_jockey(series):
    """Normalize jockey name by stripping whitespace and trailing ` AP` apprentice tag."""
    s = series.astype("string").str.strip()
    s = s.str.replace(_JOCKEY_AP_RE, "", regex=True).str.strip()
    return s.mask(s == "", pd.NA)


def _dist_band(distance_series):
    """Bucket race distance into 4 ordinal bands (0..3, -1 when invalid/missing)."""
    d = _to_f64(distance_series)
    out = np.full(len(d), -1, dtype=np.int64)
    ok = np.isfinite(d) & (d > 0.0)
    out[ok & (d <= 1350.0)] = 0
    out[ok & (d > 1350.0) & (d <= 1650.0)] = 1
    out[ok & (d > 1650.0) & (d <= 1950.0)] = 2
    out[ok & (d > 1950.0)] = 3
    return out


def _active_mask(df):
    if "scratched" in df.columns:
        return (pd.to_numeric(df["scratched"], errors="coerce").fillna(0) == 0).to_numpy()
    return np.ones(len(df), dtype=bool)


def _fpct_array(df):
    if "fpct" in df.columns:
        return _to_f64(df["fpct"])
    fin = _to_f64(df["finish"]) if "finish" in df.columns else np.full(len(df), np.nan)
    if "field" in df.columns:
        fld = np.maximum(_to_f64(df["field"]), 1.0)
    else:
        fld = np.maximum(df.groupby("race_id", sort=False)["horse_key"].transform("size").to_numpy(dtype=np.float64), 1.0)
    return (fin - 1.0) / np.maximum(fld - 1.0, 1.0)


def _freeze_same_day_horse(work, arrays):
    """Freeze per-horse lagged/cumulative arrays across any same-day multi-entries."""
    n = len(work)
    if n <= 1 or not arrays:
        return arrays
    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    order = np.argsort(hk_codes, kind="mergesort")
    hk_o = hk_codes[order]
    day_o = day_arr[order]
    same_hd = (hk_o[1:] >= 0) & (hk_o[1:] == hk_o[:-1]) & (day_o[1:] == day_o[:-1])
    if not same_hd.any():
        return arrays
    positions = np.flatnonzero(same_hd) + 1
    for arr in arrays:
        for idx_pos in positions:
            arr[order[idx_pos]] = arr[order[idx_pos - 1]]
    return arrays


def _horse_prev_values(work, val_cols, with_m3_cols=()):
    """Compute strictly `< D` lag-1 (and optional 3-race rolling mean) per horse on `work`."""
    n = len(work)
    valid_hk = work["_hk_s"].notna().to_numpy()
    g = work.groupby("_hk_s", sort=False, dropna=False)
    prev_map = {}
    m3_map = {}
    all_arrays = []

    for col in val_cols:
        s1 = np.where(valid_hk, g[col].shift(1).to_numpy(dtype=np.float64, copy=True), np.nan)
        prev_map[col] = s1
        all_arrays.append(s1)
        if col in with_m3_cols:
            s2 = g[col].shift(2).to_numpy(dtype=np.float64, copy=True)
            s3 = g[col].shift(3).to_numpy(dtype=np.float64, copy=True)
            c1 = np.isfinite(s1)
            c2 = np.isfinite(s2)
            c3 = np.isfinite(s3)
            cnt = c1.astype(np.int32) + c2.astype(np.int32) + c3.astype(np.int32)
            tot = np.where(c1, s1, 0.0) + np.where(c2, s2, 0.0) + np.where(c3, s3, 0.0)
            m3 = np.where(valid_hk & (cnt > 0), tot / np.maximum(cnt, 1), np.nan)
            m3_map[col] = m3
            all_arrays.append(m3)

    _freeze_same_day_horse(work, all_arrays)
    return prev_map, m3_map


def _inv_order(work):
    inv = np.empty(len(work), dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(len(work), dtype=np.int64)
    return inv


def _race_leave_one_out_mean(race_codes, vals, active_mask):
    """Compute leak-free leave-one-out mean of `vals` within each `race_id`."""
    n = len(vals)
    out = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return out
    valid = active_mask & np.isfinite(vals)
    n_races = int(race_codes.max()) + 1 if (race_codes >= 0).any() else 0
    if n_races == 0:
        return out
    r_ok = race_codes >= 0
    v_idx = valid & r_ok
    sum_r = np.bincount(race_codes[v_idx], weights=vals[v_idx], minlength=n_races)
    cnt_r = np.bincount(race_codes[v_idx], minlength=n_races).astype(np.float64)

    r_sum = np.where(r_ok, sum_r[np.maximum(race_codes, 0)], 0.0)
    r_cnt = np.where(r_ok, cnt_r[np.maximum(race_codes, 0)], 0.0)

    has_self = valid & (r_cnt > 1.0)
    no_self = (~valid) & r_ok & (r_cnt >= 1.0)
    out[has_self] = (r_sum[has_self] - vals[has_self]) / (r_cnt[has_self] - 1.0)
    out[no_self] = r_sum[no_self] / r_cnt[no_self]
    return out


def _prior_keyed_stats(
    hk_codes,
    grp_codes,
    day_arr,
    starts_v,
    wins_v,
    top3_v,
    fpct_cnt_v,
    fpct_sum_v,
    sf_v=None,
    need_sf=False,
):
    """Compute strictly `< D` cumulative `(starts, wins, top3, fpct_cnt, fpct_sum, sf_best)` per `(horse, key)`."""
    n = len(day_arr)
    valid_pair = (hk_codes >= 0) & (grp_codes >= 0)
    p_starts = np.full(n, np.nan, dtype=np.float64)
    p_wins = np.full(n, np.nan, dtype=np.float64)
    p_top3 = np.full(n, np.nan, dtype=np.float64)
    p_fcnt = np.full(n, np.nan, dtype=np.float64)
    p_fsum = np.full(n, np.nan, dtype=np.float64)
    p_sf_best = np.full(n, np.nan, dtype=np.float64) if need_sf else None

    if not valid_pair.any():
        return p_starts, p_wins, p_top3, p_fcnt, p_fsum, p_sf_best

    idx_v = np.flatnonzero(valid_pair)
    d_dict = {
        "_hk": hk_codes[idx_v],
        "_gk": grp_codes[idx_v],
        "_day": day_arr[idx_v],
        "_st": starts_v[idx_v],
        "_wn": wins_v[idx_v],
        "_t3": top3_v[idx_v],
        "_fc": fpct_cnt_v[idx_v],
        "_fs": fpct_sum_v[idx_v],
    }
    if need_sf and sf_v is not None:
        sf_sub = sf_v[idx_v]
        d_dict["_sf"] = np.where(np.isfinite(sf_sub), sf_sub, _SENTINEL_NEG)

    tmp = pd.DataFrame(d_dict)
    agg_spec = {
        "_st": ("_st", "sum"),
        "_wn": ("_wn", "sum"),
        "_t3": ("_t3", "sum"),
        "_fc": ("_fc", "sum"),
        "_fs": ("_fs", "sum"),
    }
    if need_sf and sf_v is not None:
        agg_spec["_sf"] = ("_sf", "max")

    daily = (
        tmp.groupby(["_hk", "_gk", "_day"], sort=True, as_index=False)
        .agg(**agg_spec)
        .sort_values(["_hk", "_gk", "_day"], kind="mergesort")
        .reset_index(drop=True)
    )
    gd = daily.groupby(["_hk", "_gk"], sort=False)
    daily["_ps"] = gd["_st"].cumsum() - daily["_st"]
    daily["_pw"] = gd["_wn"].cumsum() - daily["_wn"]
    daily["_pt3"] = gd["_t3"].cumsum() - daily["_t3"]
    daily["_pfc"] = gd["_fc"].cumsum() - daily["_fc"]
    daily["_pfs"] = gd["_fs"].cumsum() - daily["_fs"]
    if need_sf and sf_v is not None:
        cmax = gd["_sf"].cummax()
        prev_max = cmax.groupby([daily["_hk"], daily["_gk"]], sort=False).shift(1).to_numpy(dtype=np.float64)
        daily["_psf"] = np.where(np.isfinite(prev_max) & (prev_max > _SENTINEL_NEG * 0.5), prev_max, np.nan)

    d_idx = pd.MultiIndex.from_arrays([daily["_hk"], daily["_gk"], daily["_day"]])
    q_idx = pd.MultiIndex.from_arrays([hk_codes[idx_v], grp_codes[idx_v], day_arr[idx_v]])
    pos = d_idx.get_indexer(q_idx)

    p_starts[idx_v] = daily["_ps"].to_numpy(dtype=np.float64)[pos]
    p_wins[idx_v] = daily["_pw"].to_numpy(dtype=np.float64)[pos]
    p_top3[idx_v] = daily["_pt3"].to_numpy(dtype=np.float64)[pos]
    p_fcnt[idx_v] = daily["_pfc"].to_numpy(dtype=np.float64)[pos]
    p_fsum[idx_v] = daily["_pfs"].to_numpy(dtype=np.float64)[pos]
    if need_sf and sf_v is not None:
        p_sf_best[idx_v] = daily["_psf"].to_numpy(dtype=np.float64)[pos]

    return p_starts, p_wins, p_top3, p_fcnt, p_fsum, p_sf_best


def attach_T(df):
    """Attach Block T equipment flags and pre-race changes vs prior start."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in T_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    has_raw = "name_raw" in work.columns
    if has_raw:
        raw_s = work["name_raw"].astype("string").str.strip()
        valid_raw = raw_s.notna() & (raw_s != "")
        uniq_raw = raw_s[valid_raw].unique()
        parsed_map = {}
        sig_id_map = {}
        for val in uniq_raw:
            s_val = str(val)
            toks = parse_equip_tokens(s_val)
            sig = _canonical_equip_sig(toks)
            sig_id = sig_id_map.setdefault(sig, float(len(sig_id_map) + 1))
            parsed_map[s_val] = (
                1.0 if "KG" in toks else 0.0,
                1.0 if "DB" in toks else 0.0,
                1.0 if ("K" in toks or "KUL" in toks) else 0.0,
                sig_id,
            )

        kg_arr = np.full(n, np.nan, dtype=np.float64)
        db_arr = np.full(n, np.nan, dtype=np.float64)
        k_arr = np.full(n, np.nan, dtype=np.float64)
        sig_arr = np.full(n, np.nan, dtype=np.float64)
        valid_mask = valid_raw.to_numpy(dtype=bool, na_value=False)
        if valid_mask.any():
            raw_vals = raw_s[valid_mask].tolist()
            kg_arr[valid_mask] = [parsed_map[v][0] for v in raw_vals]
            db_arr[valid_mask] = [parsed_map[v][1] for v in raw_vals]
            k_arr[valid_mask] = [parsed_map[v][2] for v in raw_vals]
            sig_arr[valid_mask] = [parsed_map[v][3] for v in raw_vals]
    else:
        valid_mask = np.zeros(n, dtype=bool)
        kg_arr = np.full(n, np.nan, dtype=np.float64)
        db_arr = np.full(n, np.nan, dtype=np.float64)
        k_arr = np.full(n, np.nan, dtype=np.float64)
        sig_arr = np.full(n, np.nan, dtype=np.float64)

    work["_eq_v"] = valid_mask.astype(np.float64)
    work["_eq_kg"] = kg_arr
    work["_eq_db"] = db_arr
    work["_eq_k"] = k_arr
    work["_eq_sig"] = sig_arr
    work["_eq_kg_z"] = np.where(valid_mask, kg_arr, 0.0)
    work["_eq_db_z"] = np.where(valid_mask, db_arr, 0.0)

    valid_hk = work["_hk_s"].notna().to_numpy()
    prev_map, _ = _horse_prev_values(work, ("_eq_kg", "_eq_db", "_eq_k", "_eq_sig"))

    g = work.groupby("_hk_s", sort=False, dropna=False)
    prior_eq_cnt = np.where(
        valid_hk,
        g["_eq_v"].cumsum().to_numpy(dtype=np.float64) - work["_eq_v"].to_numpy(dtype=np.float64),
        0.0,
    )
    prior_kg_cnt = np.where(
        valid_hk,
        g["_eq_kg_z"].cumsum().to_numpy(dtype=np.float64) - work["_eq_kg_z"].to_numpy(dtype=np.float64),
        0.0,
    )
    prior_db_cnt = np.where(
        valid_hk,
        g["_eq_db_z"].cumsum().to_numpy(dtype=np.float64) - work["_eq_db_z"].to_numpy(dtype=np.float64),
        0.0,
    )
    _freeze_same_day_horse(work, [prior_eq_cnt, prior_kg_cnt, prior_db_cnt])

    has_prior_eq = (
        valid_hk
        & valid_mask
        & (prior_eq_cnt > 0.0)
        & np.isfinite(prev_map["_eq_kg"])
        & np.isfinite(prev_map["_eq_db"])
        & np.isfinite(prev_map["_eq_k"])
    )
    eq_kg_chg = np.where(has_prior_eq, kg_arr - prev_map["_eq_kg"], np.nan)
    eq_db_chg = np.where(has_prior_eq, db_arr - prev_map["_eq_db"], np.nan)
    eq_k_chg = np.where(has_prior_eq, k_arr - prev_map["_eq_k"], np.nan)

    first_kg = (kg_arr == 1.0) & (prior_kg_cnt == 0.0)
    first_db = (db_arr == 1.0) & (prior_db_cnt == 0.0)
    eq_first_kg_or_db = np.where(has_prior_eq, np.where(first_kg | first_db, 1.0, 0.0), np.nan)
    eq_any_chg = np.where(
        has_prior_eq & np.isfinite(prev_map["_eq_sig"]),
        np.where(sig_arr != prev_map["_eq_sig"], 1.0, 0.0),
        np.nan,
    )

    inv = _inv_order(work)
    out["eq_has_kg"] = kg_arr[inv]
    out["eq_has_db"] = db_arr[inv]
    out["eq_has_k"] = k_arr[inv]
    out["eq_kg_chg"] = eq_kg_chg[inv]
    out["eq_db_chg"] = eq_db_chg[inv]
    out["eq_k_chg"] = eq_k_chg[inv]
    out["eq_first_kg_or_db"] = eq_first_kg_or_db[inv]
    out["eq_any_chg"] = eq_any_chg[inv]
    return out


def attach_C(df):
    """Attach Block C class tier and leave-one-out opponent strength change features."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in C_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    active = _active_mask(work)
    race_codes, _ = pd.factorize(work["race_id"].astype("string"), sort=False)

    if "cls" in work.columns:
        cls_s = work["cls"].astype("string")
        uniq_cls = cls_s.dropna().unique()
        cls_map = {str(v): parse_cls_tier(str(v)) for v in uniq_cls}
        cls_tier = _to_f64(cls_s.map(cls_map))
    else:
        cls_tier = np.full(n, np.nan, dtype=np.float64)

    elo_h = _to_f64(work["elo_h"]) if "elo_h" in work.columns else np.full(n, np.nan, dtype=np.float64)
    hp_raw = _to_f64(work["hp"]) if "hp" in work.columns else np.full(n, np.nan, dtype=np.float64)
    hp_clean = np.where(np.isfinite(hp_raw) & (hp_raw > 0.0), hp_raw, np.nan)

    opp_elo_mean = _race_leave_one_out_mean(race_codes, elo_h, active)
    opp_hp_mean = _race_leave_one_out_mean(race_codes, hp_clean, active)

    work["_cls_tier"] = cls_tier
    work["_opp_elo"] = opp_elo_mean
    work["_opp_hp"] = opp_hp_mean

    prev_map, m3_map = _horse_prev_values(
        work, ("_cls_tier", "_opp_elo", "_opp_hp"), with_m3_cols=("_opp_elo",)
    )

    cls_tier_chg = cls_tier - prev_map["_cls_tier"]
    opp_elo_chg = opp_elo_mean - prev_map["_opp_elo"]
    opp_elo_chg_m3 = opp_elo_mean - m3_map["_opp_elo"]
    opp_hp_chg = opp_hp_mean - prev_map["_opp_hp"]

    work["_opp_elo_chg"] = np.where(active, opp_elo_chg, np.nan)
    race_chg_mean = work.groupby("race_id", sort=False)["_opp_elo_chg"].transform("mean").to_numpy(dtype=np.float64)
    opp_elo_chg_rel = opp_elo_chg - race_chg_mean

    inv = _inv_order(work)
    out["cls_tier"] = cls_tier[inv]
    out["cls_tier_chg"] = cls_tier_chg[inv]
    out["opp_elo_chg"] = opp_elo_chg[inv]
    out["opp_elo_chg_m3"] = opp_elo_chg_m3[inv]
    out["opp_hp_chg"] = opp_hp_chg[inv]
    out["opp_elo_chg_rel"] = opp_elo_chg_rel[inv]
    return out


def attach_J(df):
    """Attach Block J jockey upgrade, horse-jockey synergy, 30-day form, and weight change."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in J_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    active = _active_mask(work)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)

    j_s = (
        _normalize_jockey(work["jockey"])
        if "jockey" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )
    j_codes, j_uniques = pd.factorize(j_s, sort=False)

    work["_elo_j"] = _to_f64(work["elo_j"]) if "elo_j" in work.columns else np.full(n, np.nan, dtype=np.float64)
    work["_j_wr"] = _to_f64(work["j_wr"]) if "j_wr" in work.columns else np.full(n, np.nan, dtype=np.float64)
    work["_wt"] = _to_f64(work["weight"]) if "weight" in work.columns else np.full(n, np.nan, dtype=np.float64)
    work["_j_code"] = np.where(j_codes >= 0, j_codes.astype(np.float64), np.nan)

    prev_map, _ = _horse_prev_values(work, ("_elo_j", "_j_wr", "_wt", "_j_code"))

    j_elo_chg = work["_elo_j"].to_numpy(dtype=np.float64) - prev_map["_elo_j"]
    j_wr_chg = work["_j_wr"].to_numpy(dtype=np.float64) - prev_map["_j_wr"]
    h_weight_chg = work["_wt"].to_numpy(dtype=np.float64) - prev_map["_wt"]

    cur_jc = work["_j_code"].to_numpy(dtype=np.float64)
    prev_jc = prev_map["_j_code"]
    j_same_prev = np.where(
        np.isfinite(cur_jc) & np.isfinite(prev_jc),
        np.where(cur_jc == prev_jc, 1.0, 0.0),
        np.nan,
    )

    fin = _to_f64(work["finish"]) if "finish" in work.columns else np.full(n, np.nan, dtype=np.float64)
    fpct = _fpct_array(work)
    finished_act = active & np.isfinite(fin)
    starts_v = finished_act.astype(np.float64)
    wins_v = (finished_act & (fin == 1.0)).astype(np.float64)
    top3_v = (finished_act & (fin <= 3.0)).astype(np.float64)
    fpct_cnt_v = (finished_act & np.isfinite(fpct)).astype(np.float64)
    fpct_sum_v = np.where(fpct_cnt_v > 0.0, fpct, 0.0)

    hj_starts, hj_wins, _, hj_fcnt, hj_fsum, _ = _prior_keyed_stats(
        hk_codes,
        j_codes,
        day_arr,
        starts_v,
        wins_v,
        top3_v,
        fpct_cnt_v,
        fpct_sum_v,
        need_sf=False,
    )
    hj_n = hj_starts
    hj_wr = np.where(np.isfinite(hj_n), (hj_wins + 0.3) / (hj_n + 3.0), np.nan)
    hj_fpct = np.where(np.isfinite(hj_fcnt), (hj_fsum + 1.5) / (hj_fcnt + 3.0), np.nan)

    # Jockey 30-day rolling win rate strictly in [D - 30, D)
    j_wr_30d = np.full(n, np.nan, dtype=np.float64)
    valid_j = j_codes >= 0
    if valid_j.any():
        j_wr_30d[valid_j] = 0.10
        fin_j = valid_j & finished_act
        if fin_j.any():
            jd_df = (
                pd.DataFrame({"_jc": j_codes[fin_j], "_day": day_arr[fin_j], "_st": starts_v[fin_j], "_wn": wins_v[fin_j]})
                .groupby(["_jc", "_day"], sort=True, as_index=False)
                .sum()
                .sort_values(["_jc", "_day"], kind="mergesort")
                .reset_index(drop=True)
            )
            jc_arr = jd_df["_jc"].to_numpy(dtype=np.int64)
            jd_arr = jd_df["_day"].to_numpy(dtype=np.int64)
            jst_arr = jd_df["_st"].to_numpy(dtype=np.float64)
            jwn_arr = jd_df["_wn"].to_numpy(dtype=np.float64)

            cs_st = np.r_[0.0, np.cumsum(jst_arr)]
            cs_wn = np.r_[0.0, np.cumsum(jwn_arr)]
            j_splits = np.r_[0, np.flatnonzero(jc_arr[1:] != jc_arr[:-1]) + 1, len(jc_arr)]
            bounds_by_jc = {int(jc_arr[j_splits[i]]): (int(j_splits[i]), int(j_splits[i + 1])) for i in range(len(j_splits) - 1)}

            q_idx = np.flatnonzero(valid_j)
            q_jc = j_codes[q_idx]
            q_order = np.argsort(q_jc, kind="mergesort")
            q_rows = q_idx[q_order]
            q_sorted_jc = q_jc[q_order]
            q_splits = np.r_[0, np.flatnonzero(q_sorted_jc[1:] != q_sorted_jc[:-1]) + 1, len(q_sorted_jc)]

            for qi in range(len(q_splits) - 1):
                qs, qe = int(q_splits[qi]), int(q_splits[qi + 1])
                jc_val = int(q_sorted_jc[qs])
                b = bounds_by_jc.get(jc_val)
                if b is None:
                    continue
                ws, we = b
                wd = jd_arr[ws:we]
                r_idx = q_rows[qs:qe]
                r_days = day_arr[r_idx]
                hi = np.searchsorted(wd, r_days, side="left")
                lo = np.minimum(np.searchsorted(wd, r_days - 30, side="left"), hi)
                n30 = cs_st[ws + hi] - cs_st[ws + lo]
                w30 = cs_wn[ws + hi] - cs_wn[ws + lo]
                j_wr_30d[r_idx] = (w30 + 1.0) / (n30 + 10.0)

    inv = _inv_order(work)
    out["j_elo_chg"] = j_elo_chg[inv]
    out["j_wr_chg"] = j_wr_chg[inv]
    out["j_same_prev"] = j_same_prev[inv]
    out["hj_n"] = hj_n[inv]
    out["hj_wr"] = hj_wr[inv]
    out["hj_fpct"] = hj_fpct[inv]
    out["j_wr_30d"] = j_wr_30d[inv]
    out["h_weight_chg"] = h_weight_chg[inv]
    return out


def attach_P(df):
    """Attach Block P horse track-surface, distance-band, and city-specific priors."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in P_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    active = _active_mask(work)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)

    fin = _to_f64(work["finish"]) if "finish" in work.columns else np.full(n, np.nan, dtype=np.float64)
    fpct = _fpct_array(work)
    sf_arr = _to_f64(work["sf"]) if "sf" in work.columns else np.full(n, np.nan, dtype=np.float64)
    sf_act = np.where(active, sf_arr, np.nan)

    finished_act = active & np.isfinite(fin)
    starts_v = finished_act.astype(np.float64)
    wins_v = (finished_act & (fin == 1.0)).astype(np.float64)
    top3_v = (finished_act & (fin <= 3.0)).astype(np.float64)
    fpct_cnt_v = (finished_act & np.isfinite(fpct)).astype(np.float64)
    fpct_sum_v = np.where(fpct_cnt_v > 0.0, fpct, 0.0)

    # Overall prior fpct per horse (strictly < D) for surface delta
    all_grp = np.where(hk_codes >= 0, 0, -1)
    _, _, _, all_fcnt, all_fsum, _ = _prior_keyed_stats(
        hk_codes, all_grp, day_arr, starts_v, wins_v, top3_v, fpct_cnt_v, fpct_sum_v, need_sf=False
    )
    h_all_fpct = np.where(all_fcnt > 0.0, (all_fsum + 1.5) / (all_fcnt + 3.0), np.nan)

    # Surface priors
    surf_s = (
        _clean_entity_str(work["surface"])
        if "surface" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )
    surf_codes, _ = pd.factorize(surf_s, sort=False)
    s_n, _, s_t3, s_fcnt, s_fsum, s_sf_best = _prior_keyed_stats(
        hk_codes, surf_codes, day_arr, starts_v, wins_v, top3_v, fpct_cnt_v, fpct_sum_v, sf_v=sf_act, need_sf=True
    )
    h_surf_n = s_n
    h_surf_t3r = np.where(np.isfinite(s_n), (s_t3 + 0.9) / (s_n + 3.0), np.nan)
    h_surf_fpct = np.where(np.isfinite(s_fcnt), (s_fsum + 1.5) / (s_fcnt + 3.0), np.nan)
    h_surf_fpct_delta = np.where((s_fcnt > 0.0) & np.isfinite(h_all_fpct), h_surf_fpct - h_all_fpct, np.nan)

    work["_surf_fpct_act"] = np.where(active, h_surf_fpct, np.nan)
    surf_fpct_mean = work.groupby("race_id", sort=False)["_surf_fpct_act"].transform("mean").to_numpy(dtype=np.float64)
    h_surf_fpct_rel = h_surf_fpct - surf_fpct_mean

    # Distance band priors
    dist_codes = _dist_band(work["distance"]) if "distance" in work.columns else np.full(n, -1, dtype=np.int64)
    d_n, _, _, d_fcnt, d_fsum, d_sf_best = _prior_keyed_stats(
        hk_codes, dist_codes, day_arr, starts_v, wins_v, top3_v, fpct_cnt_v, fpct_sum_v, sf_v=sf_act, need_sf=True
    )
    h_dist_n = d_n
    h_dist_fpct = np.where(np.isfinite(d_fcnt), (d_fsum + 1.5) / (d_fcnt + 3.0), np.nan)

    # City priors
    city_s = _clean_entity_str(work["_city_s"])
    city_codes, _ = pd.factorize(city_s, sort=False)
    _, _, _, c_fcnt, c_fsum, _ = _prior_keyed_stats(
        hk_codes, city_codes, day_arr, starts_v, wins_v, top3_v, fpct_cnt_v, fpct_sum_v, need_sf=False
    )
    h_city_fpct = np.where(np.isfinite(c_fcnt), (c_fsum + 1.5) / (c_fcnt + 3.0), np.nan)

    inv = _inv_order(work)
    out["h_surf_n"] = h_surf_n[inv]
    out["h_surf_t3r"] = h_surf_t3r[inv]
    out["h_surf_fpct"] = h_surf_fpct[inv]
    out["h_surf_sf_best"] = s_sf_best[inv]
    out["h_surf_fpct_delta"] = h_surf_fpct_delta[inv]
    out["h_surf_fpct_rel"] = h_surf_fpct_rel[inv]
    out["h_dist_n"] = h_dist_n[inv]
    out["h_dist_fpct"] = h_dist_fpct[inv]
    out["h_dist_sf_best"] = d_sf_best[inv]
    out["h_city_fpct"] = h_city_fpct[inv]
    return out


def attach_v7(df, blocks=("T", "C", "J", "P")):
    """Attach selected leak-free v7 feature blocks (`T`, `C`, `J`, `P`) onto v5/v6 DataFrame."""
    out = df.copy()
    for blk in blocks or ():
        if blk == "T":
            out = attach_T(out)
        elif blk == "C":
            out = attach_C(out)
        elif blk == "J":
            out = attach_J(out)
        elif blk == "P":
            out = attach_P(out)
        else:
            raise ValueError(f"Unknown v7 block: {blk!r}. Expected subset of {tuple(V7_BLOCK_COLS)}.")
    return out


def get_v7_cols(v7_blocks=(), with_program=False):
    """Return V6 base feature columns (`B1_SGR`) extended with requested `V7_BLOCK_COLS`."""
    from ganyan.model_v6 import get_v6_cols

    cols = list(get_v6_cols(extra_blocks=(), with_program=with_program))
    for blk in v7_blocks or ():
        if blk not in V7_BLOCK_COLS:
            raise ValueError(f"Unknown v7 block: {blk!r}. Expected one of {list(V7_BLOCK_COLS)}.")
        cols.extend(V7_BLOCK_COLS[blk])
    return list(dict.fromkeys(cols))


__all__ = [
    "ALL_EQUIP_TOKENS",
    "C_COLS",
    "J_COLS",
    "P_COLS",
    "T_COLS",
    "V7_BLOCK_COLS",
    "attach_C",
    "attach_J",
    "attach_P",
    "attach_T",
    "attach_v7",
    "get_v7_cols",
    "parse_cls_tier",
    "parse_equip_tokens",
]
