"""Leak-free v8 pre-race feature blocks (A: horse peak/wear, K: jockey prime, N: stable network & wakeup)."""
from collections import deque
import math
import re

import numpy as np
import pandas as pd

from ganyan.features_v5 import _clean_entity_str, _sorted_work_frame
from ganyan.features_v6 import _to_f64
from ganyan.features_v7 import (
    _active_mask,
    _fpct_array,
    _freeze_same_day_horse,
    _horse_prev_values,
    _inv_order,
    _normalize_jockey,
    _prior_keyed_stats,
)

A_COLS = [
    "hp_drop_from_peak",
    "hp_peak_ratio",
    "days_since_peak_sf",
    "starts_since_peak_sf",
    "sf_trend_3v3",
    "fpct_trend_3v3",
    "h_starts_90d",
    "h_layoff_run_no",
    "age_rel",
    "h_n_rel",
]

K_COLS = [
    "j_career_yrs",
    "j_is_ap",
    "j_wr_180d",
    "j_wr_365d",
    "j_wr_trend_180v_car",
    "j_wr_30v365",
    "j_career_yrs_rel",
]

N_COLS = [
    "own_mates_cnt",
    "own_is_sub_agf",
    "own_mate_agf",
    "trn_mates_cnt",
    "trn_is_sub_agf",
    "fam_hidden_ekuri",
    "tj_n",
    "tj_wr",
    "tj_wr_synergy",
    "oj_wr",
    "agf_surge_ratio",
    "sleep_wakeup_flag",
]

V8_BLOCK_COLS = {
    "A": list(A_COLS),
    "K": list(K_COLS),
    "N": list(N_COLS),
}

_JOCKEY_AP_RE = re.compile(r"\s+AP\.?$", re.IGNORECASE)
_TR_UPPER_MAP = str.maketrans({
    "i": "I",
    "İ": "I",
    "ş": "S",
    "Ş": "S",
    "ğ": "G",
    "Ğ": "G",
    "ü": "U",
    "Ü": "U",
    "ö": "O",
    "Ö": "O",
    "ç": "C",
    "Ç": "C",
})
_CORP_LAST_WORDS = frozenset({
    "AS",
    "LTD",
    "STI",
    "TIC",
    "SAN",
    "VE",
    "HARASI",
    "EKURISI",
    "TARIM",
    "HAYVANCILIK",
    "INSAAT",
    "GIDA",
    "TURIZM",
    "HOLDING",
    "GRUP",
    "GROUP",
    "ORT",
    "KULUBU",
    "KOOP",
})


def _extract_owner_surnames(owner_series):
    """Extract normalized last surname for family-link matching, excluding corporate suffixes."""
    clean = _clean_entity_str(owner_series)
    valid = clean.notna()
    out = pd.Series(pd.NA, index=clean.index, dtype="string")
    if not valid.any():
        return out

    uniq_owners = clean[valid].unique()
    surname_map = {}
    for raw_o in uniq_owners:
        s_o = str(raw_o).strip()
        parts = s_o.split()
        if len(parts) < 2:
            surname_map[raw_o] = pd.NA
            continue
        last_tok = parts[-1].strip(".,;:()[]{}\"'").translate(_TR_UPPER_MAP).upper()
        last_nodot = last_tok.replace(".", "")
        if len(last_nodot) < 3 or last_nodot in _CORP_LAST_WORDS:
            surname_map[raw_o] = pd.NA
        else:
            surname_map[raw_o] = last_nodot
    return clean.map(surname_map).astype("string")


def _race_active_rel(work, vals, active_mask, tmp_col="_rel_tmp"):
    """Compute `vals - mean(vals over active runners in race)` preserving inactive NaNs if needed."""
    work[tmp_col] = np.where(active_mask, vals, np.nan)
    race_mean = work.groupby("race_id", sort=False)[tmp_col].transform("mean").to_numpy(dtype=np.float64)
    return vals - race_mean


def _compute_agf_share(work, active_mask):
    """Return `agf_share` from existing column or race-normalize `agf_close` / `agf_pct`."""
    n = len(work)
    if "agf_share" in work.columns:
        return _to_f64(work["agf_share"])
    agf_col = (
        "agf_close"
        if "agf_close" in work.columns
        else ("agf_pct" if "agf_pct" in work.columns else None)
    )
    if agf_col is None:
        return np.full(n, np.nan, dtype=np.float64)
    agf_raw = _to_f64(work[agf_col])
    agf_pos = np.where(active_mask & np.isfinite(agf_raw) & (agf_raw > 0.0), agf_raw, 0.0)
    work["_v8_agf_tmp"] = agf_pos
    agf_sum = work.groupby("race_id", sort=False)["_v8_agf_tmp"].transform("sum").to_numpy(dtype=np.float64)
    return np.where(
        active_mask & (agf_sum > 0.0) & np.isfinite(agf_raw) & (agf_raw > 0.0),
        agf_raw / np.where(agf_sum > 0.0, agf_sum, 1.0),
        np.nan,
    )


def _compute_jockey_rolling(valid_j, j_codes, day_arr, active_settled, wins_v):
    """Compute strictly `< D` rolling jockey win rates (`30d`, `180d`, `365d`, career)."""
    n = len(day_arr)
    wr_30d = np.full(n, np.nan, dtype=np.float64)
    wr_180d = np.full(n, np.nan, dtype=np.float64)
    wr_365d = np.full(n, np.nan, dtype=np.float64)
    wr_prior = np.full(n, np.nan, dtype=np.float64)

    if not valid_j.any():
        return wr_30d, wr_180d, wr_365d, wr_prior

    wr_30d[valid_j] = 1.0 / 10.0
    wr_180d[valid_j] = 1.0 / 10.0
    wr_365d[valid_j] = 2.0 / 20.0
    wr_prior[valid_j] = 2.0 / 20.0

    fin_j = valid_j & active_settled
    if not fin_j.any():
        return wr_30d, wr_180d, wr_365d, wr_prior

    starts_j = np.ones(int(fin_j.sum()), dtype=np.float64)
    jd_df = (
        pd.DataFrame({
            "_jc": j_codes[fin_j],
            "_day": day_arr[fin_j],
            "_st": starts_j,
            "_wn": wins_v[fin_j],
        })
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
    bounds_by_jc = {
        int(jc_arr[j_splits[i]]): (int(j_splits[i]), int(j_splits[i + 1]))
        for i in range(len(j_splits) - 1)
    }

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
        lo30 = np.minimum(np.searchsorted(wd, r_days - 30, side="left"), hi)
        lo180 = np.minimum(np.searchsorted(wd, r_days - 180, side="left"), hi)
        lo365 = np.minimum(np.searchsorted(wd, r_days - 365, side="left"), hi)

        n30 = cs_st[ws + hi] - cs_st[ws + lo30]
        w30 = cs_wn[ws + hi] - cs_wn[ws + lo30]
        n180 = cs_st[ws + hi] - cs_st[ws + lo180]
        w180 = cs_wn[ws + hi] - cs_wn[ws + lo180]
        n365 = cs_st[ws + hi] - cs_st[ws + lo365]
        w365 = cs_wn[ws + hi] - cs_wn[ws + lo365]
        n_car = cs_st[ws + hi] - cs_st[ws]
        w_car = cs_wn[ws + hi] - cs_wn[ws]

        wr_30d[r_idx] = (w30 + 1.0) / (n30 + 10.0)
        wr_180d[r_idx] = (w180 + 1.0) / (n180 + 10.0)
        wr_365d[r_idx] = (w365 + 2.0) / (n365 + 20.0)
        wr_prior[r_idx] = (w_car + 2.0) / (n_car + 20.0)

    return wr_30d, wr_180d, wr_365d, wr_prior


def _mean_3v3_trend(dq):
    """Given deque (len <= 6) ordered oldest..newest, compute mean(last 3) - mean(older up to 3)."""
    n_q = len(dq)
    if n_q < 4:
        return math.nan
    arr = list(dq)
    older = arr[:-3]
    recent = arr[-3:]
    o_vals = [v for v in older if v == v]
    r_vals = [v for v in recent if v == v]
    if not o_vals or not r_vals:
        return math.nan
    return (sum(r_vals) / len(r_vals)) - (sum(o_vals) / len(o_vals))


def attach_A(df):
    """Attach Block A horse prime, peak decay, layoff recovery, and relative age/experience."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in A_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    active = _active_mask(work)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)

    hp_raw = _to_f64(work["hp"]) if "hp" in work.columns else np.full(n, np.nan, dtype=np.float64)
    hp_pos = np.where(np.isfinite(hp_raw) & (hp_raw > 0.0), hp_raw, np.nan)
    fin = _to_f64(work["finish"]) if "finish" in work.columns else np.full(n, np.nan, dtype=np.float64)
    sf_arr = _to_f64(work["sf"]) if "sf" in work.columns else np.full(n, np.nan, dtype=np.float64)
    fpct_arr = _fpct_array(work)
    age_arr = _to_f64(work["age"]) if "age" in work.columns else np.full(n, np.nan, dtype=np.float64)
    has_hn_col = "h_n" in work.columns
    hn_existing = _to_f64(work["h_n"]) if has_hn_col else None

    hp_drop = np.full(n, np.nan, dtype=np.float64)
    hp_ratio = np.full(n, np.nan, dtype=np.float64)
    days_peak = np.full(n, np.nan, dtype=np.float64)
    starts_peak = np.full(n, np.nan, dtype=np.float64)
    sf_trend = np.full(n, np.nan, dtype=np.float64)
    fpct_trend = np.full(n, np.nan, dtype=np.float64)
    starts_90d = np.full(n, np.nan, dtype=np.float64)
    layoff_no = np.full(n, np.nan, dtype=np.float64)
    prior_cnt_arr = np.full(n, np.nan, dtype=np.float64)

    # Sort work indices by horse keeping chronological order (`mergesort` preserves `_day_int` order)
    order = np.argsort(hk_codes, kind="mergesort")
    hk_o = hk_codes[order].tolist()
    day_o = day_arr[order].tolist()
    act_o = active[order].tolist()
    hp_o = hp_pos[order].tolist()
    fin_o = fin[order].tolist()
    sf_o = sf_arr[order].tolist()
    fpct_o = fpct_arr[order].tolist()
    order_list = order.tolist()

    # Convert outputs to Python lists for fast per-horse linear state transitions (<1s on 1M rows)
    hp_drop_l = [math.nan] * n
    hp_ratio_l = [math.nan] * n
    days_peak_l = [math.nan] * n
    starts_peak_l = [math.nan] * n
    sf_trend_l = [math.nan] * n
    fpct_trend_l = [math.nan] * n
    starts_90d_l = [math.nan] * n
    layoff_no_l = [math.nan] * n
    prior_cnt_l = [math.nan] * n

    pos = 0
    while pos < n:
        hk_c = hk_o[pos]
        end_h = pos + 1
        while end_h < n and hk_o[end_h] == hk_c:
            end_h += 1
        if hk_c < 0:
            pos = end_h
            continue

        hp_prev_max = -1.0
        best_sf = -math.inf
        best_sf_day = -1
        st_since_peak = 0
        sf_dq = deque(maxlen=6)
        fp_dq = deque(maxlen=6)
        days_90_dq = deque()
        prev_start_day = -1
        prev_gap = -1
        prev2_gap = -1
        total_prior_starts = 0

        cur = pos
        while cur < end_h:
            d_cur = day_o[cur]
            d_end = cur + 1
            while d_end < end_h and day_o[d_end] == d_cur:
                d_end += 1

            # Evict starts strictly older than [d_cur - 90, d_cur)
            cutoff_90 = d_cur - 90
            while days_90_dq and days_90_dq[0] < cutoff_90:
                days_90_dq.popleft()

            n_90_val = float(len(days_90_dq))
            sf_tr_val = _mean_3v3_trend(sf_dq)
            fp_tr_val = _mean_3v3_trend(fp_dq)
            d_peak_val = float(d_cur - best_sf_day) if best_sf_day >= 0 else math.nan
            s_peak_val = float(st_since_peak) if best_sf_day >= 0 else math.nan
            if prev_start_day < 0:
                lo_val = math.nan
            else:
                curr_gap = d_cur - prev_start_day
                if curr_gap >= 90:
                    lo_val = 1.0
                elif curr_gap < 60 and prev_gap >= 90:
                    lo_val = 2.0
                elif curr_gap < 60 and 0 <= prev_gap < 60 and prev2_gap >= 90:
                    lo_val = 3.0
                else:
                    lo_val = 0.0

            # 1) Read state `< d_cur` for all rows on day `d_cur` (day-frozen guarantee)
            for k in range(cur, d_end):
                orig_idx = order_list[k]
                hp_c = hp_o[k]
                if hp_prev_max > 0.0 and hp_c == hp_c:
                    hp_drop_l[orig_idx] = hp_prev_max - hp_c
                    hp_ratio_l[orig_idx] = hp_c / hp_prev_max
                days_peak_l[orig_idx] = d_peak_val
                starts_peak_l[orig_idx] = s_peak_val
                sf_trend_l[orig_idx] = sf_tr_val
                fpct_trend_l[orig_idx] = fp_tr_val
                starts_90d_l[orig_idx] = n_90_val
                layoff_no_l[orig_idx] = lo_val
                prior_cnt_l[orig_idx] = float(total_prior_starts)

            # 2) Update state AFTER finishing day `d_cur` (strictly active settled outcomes for `< D+1`)
            for k in range(cur, d_end):
                if not act_o[k]:
                    continue
                hp_c = hp_o[k]
                fin_c = fin_o[k]
                if fin_c == fin_c:
                    if hp_c == hp_c and hp_c > hp_prev_max:
                        hp_prev_max = hp_c
                    sf_c = sf_o[k]
                    fp_c = fpct_o[k]
                    if sf_c == sf_c:
                        if sf_c >= best_sf:
                            best_sf = sf_c
                            best_sf_day = d_cur
                            st_since_peak = 0
                        elif best_sf_day >= 0:
                            st_since_peak += 1
                    elif best_sf_day >= 0:
                        st_since_peak += 1

                    sf_dq.append(sf_c)
                    fp_dq.append(fp_c)
                    days_90_dq.append(d_cur)
                    total_prior_starts += 1
                    if prev_start_day >= 0 and d_cur > prev_start_day:
                        new_gap = d_cur - prev_start_day
                        prev2_gap = prev_gap
                        prev_gap = new_gap
                        prev_start_day = d_cur
                    elif prev_start_day < 0:
                        prev_start_day = d_cur

            cur = d_end
        pos = end_h

    hp_drop[:] = hp_drop_l
    hp_ratio[:] = hp_ratio_l
    days_peak[:] = days_peak_l
    starts_peak[:] = starts_peak_l
    sf_trend[:] = sf_trend_l
    fpct_trend[:] = fpct_trend_l
    starts_90d[:] = starts_90d_l
    layoff_no[:] = layoff_no_l
    prior_cnt_arr[:] = prior_cnt_l

    age_rel = _race_active_rel(work, age_arr, active, tmp_col="_v8_age_tmp")
    hn_base = hn_existing if has_hn_col else prior_cnt_arr
    hn_rel = _race_active_rel(work, hn_base, active, tmp_col="_v8_hn_tmp")

    inv = _inv_order(work)
    out["hp_drop_from_peak"] = hp_drop[inv]
    out["hp_peak_ratio"] = hp_ratio[inv]
    out["days_since_peak_sf"] = days_peak[inv]
    out["starts_since_peak_sf"] = starts_peak[inv]
    out["sf_trend_3v3"] = sf_trend[inv]
    out["fpct_trend_3v3"] = fpct_trend[inv]
    out["h_starts_90d"] = starts_90d[inv]
    out["h_layoff_run_no"] = layoff_no[inv]
    out["age_rel"] = age_rel[inv]
    out["h_n_rel"] = hn_rel[inv]
    return out


def attach_K(df):
    """Attach Block K jockey prime period, apprentice tag, multi-window form, and career age."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in K_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    active = _active_mask(work)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    fin = _to_f64(work["finish"]) if "finish" in work.columns else np.full(n, np.nan, dtype=np.float64)
    active_settled = active & np.isfinite(fin)
    wins_v = (active_settled & (fin == 1.0)).astype(np.float64)

    has_j = "jockey" in work.columns
    if has_j:
        raw_j = work["jockey"].astype("string").str.strip()
        non_empty_j = raw_j.notna() & (raw_j != "")
        j_is_ap = np.where(
            non_empty_j.to_numpy(dtype=bool, na_value=False),
            raw_j.str.contains(_JOCKEY_AP_RE, na=False).to_numpy(dtype=bool, na_value=False).astype(np.float64),
            np.nan,
        )
        j_s = _normalize_jockey(work["jockey"])
    else:
        j_is_ap = np.full(n, np.nan, dtype=np.float64)
        j_s = pd.Series(pd.NA, index=work.index, dtype="string")

    j_codes, _ = pd.factorize(j_s, sort=False)
    valid_j = j_codes >= 0

    j_career_yrs = np.full(n, np.nan, dtype=np.float64)
    if valid_j.any():
        act_j = valid_j & active
        src_days = day_arr[act_j] if act_j.any() else day_arr[valid_j]
        src_codes = j_codes[act_j] if act_j.any() else j_codes[valid_j]
        first_day_by_jc = pd.Series(src_days).groupby(src_codes, sort=False).min().to_dict()
        j_first = np.array(
            [first_day_by_jc.get(int(c), int(d)) if c >= 0 else 0 for c, d in zip(j_codes, day_arr)],
            dtype=np.float64,
        )
        j_career_yrs[valid_j] = np.maximum(
            (day_arr[valid_j].astype(np.float64) - j_first[valid_j]) / 365.25,
            0.0,
        )

    wr_30d, wr_180d, wr_365d, wr_prior = _compute_jockey_rolling(
        valid_j, j_codes, day_arr, active_settled, wins_v
    )
    j_wr_trend_180v_car = wr_180d - wr_prior
    j_wr_30v365 = wr_30d - wr_365d
    j_career_yrs_rel = _race_active_rel(work, j_career_yrs, active, tmp_col="_v8_jcy_tmp")

    inv = _inv_order(work)
    out["j_career_yrs"] = j_career_yrs[inv]
    out["j_is_ap"] = j_is_ap[inv]
    out["j_wr_180d"] = wr_180d[inv]
    out["j_wr_365d"] = wr_365d[inv]
    out["j_wr_trend_180v_car"] = j_wr_trend_180v_car[inv]
    out["j_wr_30v365"] = j_wr_30v365[inv]
    out["j_career_yrs_rel"] = j_career_yrs_rel[inv]
    return out


def attach_N(df):
    """Attach Block N stable network relationships, partnerships, and sleeping-horse wakeup signals."""
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in N_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    active = _active_mask(work)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    fin = _to_f64(work["finish"]) if "finish" in work.columns else np.full(n, np.nan, dtype=np.float64)
    active_settled = active & np.isfinite(fin)
    wins_v = (active_settled & (fin == 1.0)).astype(np.float64)
    starts_v = active_settled.astype(np.float64)
    zero_v = np.zeros(n, dtype=np.float64)

    own_s = (
        _clean_entity_str(work["owner"])
        if "owner" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )
    trn_s = (
        _clean_entity_str(work["trainer"])
        if "trainer" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )
    j_s = (
        _normalize_jockey(work["jockey"])
        if "jockey" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )

    agf_s = _compute_agf_share(work, active)
    agf_finite = np.isfinite(agf_s)

    # 1. Same-race Owner & Trainer multi-entries
    rid_s = work["race_id"].astype("string")
    own_valid_act = active & own_s.notna().to_numpy(dtype=bool, na_value=False)
    trn_valid_act = active & trn_s.notna().to_numpy(dtype=bool, na_value=False)

    work["_v8_rid"] = rid_s
    work["_v8_own"] = own_s.where(pd.Series(own_valid_act, index=work.index), pd.NA)
    work["_v8_trn"] = trn_s.where(pd.Series(trn_valid_act, index=work.index), pd.NA)
    work["_v8_agf"] = np.where(active & agf_finite, agf_s, np.nan)
    work["_v8_agf_z"] = np.where(active & agf_finite, agf_s, 0.0)

    own_grp_cnt = work.groupby(["_v8_rid", "_v8_own"], sort=False)["_v8_rid"].transform("size").to_numpy(dtype=np.float64)
    own_mates_cnt = np.where(own_valid_act, own_grp_cnt - 1.0, 0.0)

    own_max_agf = work.groupby(["_v8_rid", "_v8_own"], sort=False)["_v8_agf"].transform("max").to_numpy(dtype=np.float64)
    own_sum_agf = work.groupby(["_v8_rid", "_v8_own"], sort=False)["_v8_agf_z"].transform("sum").to_numpy(dtype=np.float64)
    own_is_sub_agf = np.where(
        agf_finite,
        np.where((own_mates_cnt >= 1.0) & np.isfinite(own_max_agf) & (agf_s < own_max_agf - 1e-12), 1.0, 0.0),
        np.nan,
    )
    own_mate_agf = np.where(
        agf_finite,
        np.where(own_mates_cnt >= 1.0, np.maximum(own_sum_agf - agf_s, 0.0), 0.0),
        np.nan,
    )

    trn_grp_cnt = work.groupby(["_v8_rid", "_v8_trn"], sort=False)["_v8_rid"].transform("size").to_numpy(dtype=np.float64)
    trn_mates_cnt = np.where(trn_valid_act, trn_grp_cnt - 1.0, 0.0)
    trn_max_agf = work.groupby(["_v8_rid", "_v8_trn"], sort=False)["_v8_agf"].transform("max").to_numpy(dtype=np.float64)
    trn_is_sub_agf = np.where(
        agf_finite,
        np.where((trn_mates_cnt >= 1.0) & np.isfinite(trn_max_agf) & (agf_s < trn_max_agf - 1e-12), 1.0, 0.0),
        np.nan,
    )

    # 2. Hidden family ekuri: same race_id + same trainer + different owner + same surname
    sur_s = _extract_owner_surnames(own_s)
    fam_valid = trn_valid_act & own_valid_act & sur_s.notna().to_numpy(dtype=bool, na_value=False)
    fam_hidden_ekuri = np.zeros(n, dtype=np.float64)
    if fam_valid.any():
        work["_v8_sur"] = sur_s.where(pd.Series(fam_valid, index=work.index), pd.NA)
        sub_f = work.loc[fam_valid, ["_v8_rid", "_v8_trn", "_v8_sur", "_v8_own"]].copy()
        cnt_ts = sub_f.groupby(["_v8_rid", "_v8_trn", "_v8_sur"], sort=False)["_v8_own"].transform("size").to_numpy()
        cnt_tso = sub_f.groupby(["_v8_rid", "_v8_trn", "_v8_sur", "_v8_own"], sort=False)["_v8_own"].transform("size").to_numpy()
        fam_hidden_ekuri[fam_valid] = np.where(cnt_ts > cnt_tso, 1.0, 0.0)

    # 3. Prior Trainer-Jockey and Owner-Jockey partnerships (< D)
    j_codes, _ = pd.factorize(j_s, sort=False)
    trn_codes, _ = pd.factorize(trn_s, sort=False)
    own_codes, _ = pd.factorize(own_s, sort=False)
    valid_j = j_codes >= 0

    _, _, _, wr_prior = _compute_jockey_rolling(valid_j, j_codes, day_arr, active_settled, wins_v)

    tj_starts, tj_wins, _, _, _, _ = _prior_keyed_stats(
        trn_codes, j_codes, day_arr, starts_v, wins_v, zero_v, zero_v, zero_v, need_sf=False
    )
    tj_n = tj_starts
    tj_wr = np.where(np.isfinite(tj_n), (tj_wins + 1.0) / (tj_n + 10.0), np.nan)
    tj_wr_synergy = np.where(np.isfinite(tj_wr) & np.isfinite(wr_prior), tj_wr - wr_prior, np.nan)

    oj_starts, oj_wins, _, _, _, _ = _prior_keyed_stats(
        own_codes, j_codes, day_arr, starts_v, wins_v, zero_v, zero_v, zero_v, need_sf=False
    )
    oj_wr = np.where(np.isfinite(oj_starts), (oj_wins + 0.5) / (oj_starts + 5.0), np.nan)

    # 4. AGF surge ratio & sleeping horse wake-up (< D last 2 starts, day-frozen)
    work["_v8_agf_lag"] = agf_s
    work["_v8_fin_lag"] = fin
    g_h = work.groupby("_hk_s", sort=False, dropna=False)
    valid_hk = work["_hk_s"].notna().to_numpy()

    a1 = np.where(valid_hk, g_h["_v8_agf_lag"].shift(1).to_numpy(dtype=np.float64, copy=True), np.nan)
    a2 = np.where(valid_hk, g_h["_v8_agf_lag"].shift(2).to_numpy(dtype=np.float64, copy=True), np.nan)
    f1 = np.where(valid_hk, g_h["_v8_fin_lag"].shift(1).to_numpy(dtype=np.float64, copy=True), np.nan)
    f2 = np.where(valid_hk, g_h["_v8_fin_lag"].shift(2).to_numpy(dtype=np.float64, copy=True), np.nan)
    _freeze_same_day_horse(work, [a1, a2, f1, f2])

    prev2_agf_ok = np.isfinite(a1) & np.isfinite(a2)
    prev2_agf_mean = np.where(prev2_agf_ok, 0.5 * (a1 + a2), np.nan)
    surge_ok = prev2_agf_ok & agf_finite
    agf_surge_ratio = np.where(
        surge_ok,
        np.log((np.where(surge_ok, agf_s, 0.0) + 0.005) / (np.where(surge_ok, prev2_agf_mean, 0.0) + 0.005)),
        np.nan,
    )

    wake_ok = surge_ok & np.isfinite(f1) & np.isfinite(f2)
    sleep_wakeup_flag = np.where(
        wake_ok,
        np.where((f1 >= 7.0) & (f2 >= 7.0) & (prev2_agf_mean < 0.08) & (agf_s >= 0.08), 1.0, 0.0),
        np.nan,
    )

    inv = _inv_order(work)
    out["own_mates_cnt"] = own_mates_cnt[inv]
    out["own_is_sub_agf"] = own_is_sub_agf[inv]
    out["own_mate_agf"] = own_mate_agf[inv]
    out["trn_mates_cnt"] = trn_mates_cnt[inv]
    out["trn_is_sub_agf"] = trn_is_sub_agf[inv]
    out["fam_hidden_ekuri"] = fam_hidden_ekuri[inv]
    out["tj_n"] = tj_n[inv]
    out["tj_wr"] = tj_wr[inv]
    out["tj_wr_synergy"] = tj_wr_synergy[inv]
    out["oj_wr"] = oj_wr[inv]
    out["agf_surge_ratio"] = agf_surge_ratio[inv]
    out["sleep_wakeup_flag"] = sleep_wakeup_flag[inv]
    return out


def attach_v8(df, blocks=("A", "K", "N")):
    """Attach selected leak-free v8 feature blocks (`A`, `K`, `N`) onto v7 DataFrame."""
    out = df.copy()
    for blk in blocks or ():
        if blk == "A":
            out = attach_A(out)
        elif blk == "K":
            out = attach_K(out)
        elif blk == "N":
            out = attach_N(out)
        else:
            raise ValueError(f"Unknown v8 block: {blk!r}. Expected subset of {tuple(V8_BLOCK_COLS)}.")
    return out


def get_v8_cols(v8_blocks=(), with_program=False):
    """Return V7 base feature columns (T+C+J+P) extended with requested `V8_BLOCK_COLS`."""
    from ganyan.features_v7 import V7_BLOCK_COLS, get_v7_cols

    cols = list(get_v7_cols(v7_blocks=tuple(V7_BLOCK_COLS), with_program=with_program))
    for blk in v8_blocks or ():
        if blk not in V8_BLOCK_COLS:
            raise ValueError(f"Unknown v8 block: {blk!r}. Expected one of {list(V8_BLOCK_COLS)}.")
        cols.extend(V8_BLOCK_COLS[blk])
    return list(dict.fromkeys(cols))


__all__ = [
    "A_COLS",
    "K_COLS",
    "N_COLS",
    "V8_BLOCK_COLS",
    "attach_A",
    "attach_K",
    "attach_N",
    "attach_v8",
    "get_v8_cols",
]
