"""Leak-free v10 pre-race feature blocks (BELL, JLOY, LOAD, H2H) with shared-context fast path."""
from collections import deque
import math
import re

import numpy as np
import pandas as pd
from scipy.special import ndtr

from ganyan.features_v7 import (
    _active_mask,
    _fpct_array,
    _inv_order,
    _prior_keyed_stats,
)
from ganyan.features_v8 import _compute_agf_share
from ganyan.features_v9 import (
    _clean_entity_str,
    _col_or_empty,
    _day_stride,
    _empty_result,
    _lite_work_frame,
    _norm_upper_str,
    _range_window_agg,
    get_v9_cols,
)
from ganyan.model_v9 import V9_CONFIG

BELL_COLS = [
    "bell_sf_std",
    "bell_sf_std_rel",
    "bell_sf_p90",
    "bell_upside_gap",
    "bell_prob_beat_fav",
    "bell_fpct_std",
]

JLOY_COLS = [
    "j_abandoned_to_rival",
    "j_chose_over_prev",
    "j_chose_agf_diff",
    "j_chose_over_loyal_trn",
    "j_trn_loyal_share_race",
    "t_jwr_upgrade",
]

LOAD_COLS = [
    "load_dist_60d",
    "load_dist_180d",
    "load_ewma_wear",
    "sf_vel_recent",
    "sf_accel",
]

H2H_COLS = [
    "h2h_rivals_met",
    "h2h_meetings",
    "h2h_beat_rate",
    "h2h_beat_rate_rel",
    "h2h_vs_fav_margin",
]

V10_CANDIDATE_BLOCKS = ("BELL", "JLOY", "LOAD", "H2H")

V10_BLOCK_COLS = {
    "BELL": list(BELL_COLS),
    "JLOY": list(JLOY_COLS),
    "LOAD": list(LOAD_COLS),
    "H2H": list(H2H_COLS),
}

_BLOCK_NEEDED_COLS = {
    "BELL": ("scratched", "finish", "sf", "fpct"),
    "JLOY": ("scratched", "finish", "jockey", "trainer", "agf_close", "agf_share", "j_wr"),
    "LOAD": ("scratched", "finish", "distance", "sf", "fpct"),
    "H2H": ("scratched", "finish", "agf_close", "agf_share"),
}

_JOCKEY_AP_RE = re.compile(r"\s+AP\.?$", re.IGNORECASE)

# Fixed Bayesian smoothing, decay, and window constants (documented in V10 report)
BELL_WINDOW = 8
BELL_PRIOR_DF = 3.0
BELL_SF_PRIOR_STD = 28.0
BELL_FPCT_PRIOR_STD = 0.28
_NORM_P90_Z = 1.2815515655446004

JLOY_WINDOW_DAYS = 365
JLOY_LOYAL_MIN_RIDES = 5
JLOY_T_JWR_PRIOR_N = 15.0
JLOY_JWR_PRIOR = 0.10

LOAD_WIN_60 = 60
LOAD_WIN_180 = 180
LOAD_DECAY_DAYS = 30.0
LOAD_DIST_REF = 1400.0
LOAD_VEL_MIN_DAYS = 7.0

H2H_WINDOW_DAYS = 730
H2H_PRIOR_W = 1.5
H2H_PRIOR_N = 3.0
H2H_MAX_HIST_RACES = 25

SMOOTHING_CONSTANTS = {
    "BELL_WINDOW": BELL_WINDOW,
    "BELL_PRIOR_DF": BELL_PRIOR_DF,
    "BELL_SF_PRIOR_STD": BELL_SF_PRIOR_STD,
    "BELL_FPCT_PRIOR_STD": BELL_FPCT_PRIOR_STD,
    "JLOY_WINDOW_DAYS": JLOY_WINDOW_DAYS,
    "JLOY_LOYAL_MIN_RIDES": JLOY_LOYAL_MIN_RIDES,
    "JLOY_T_JWR_PRIOR_N": JLOY_T_JWR_PRIOR_N,
    "JLOY_JWR_PRIOR": JLOY_JWR_PRIOR,
    "LOAD_WIN_60": LOAD_WIN_60,
    "LOAD_WIN_180": LOAD_WIN_180,
    "LOAD_DECAY_DAYS": LOAD_DECAY_DAYS,
    "LOAD_DIST_REF": LOAD_DIST_REF,
    "LOAD_VEL_MIN_DAYS": LOAD_VEL_MIN_DAYS,
    "H2H_WINDOW_DAYS": H2H_WINDOW_DAYS,
    "H2H_PRIOR_W": H2H_PRIOR_W,
    "H2H_PRIOR_N": H2H_PRIOR_N,
    "H2H_MAX_HIST_RACES": H2H_MAX_HIST_RACES,
}


def _to_f64(series):
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float64, copy=False)


def _fast_normalize_jockey(series):
    """Normalize jockey names via `.unique()` mapping for exact parity with `_normalize_jockey`."""
    s = _clean_entity_str(series)
    valid = s.notna()
    if not valid.any():
        return pd.Series(pd.NA, index=s.index, dtype="string")
    uniq = s[valid].unique()
    umap = {}
    for raw in uniq:
        txt = _JOCKEY_AP_RE.sub("", str(raw).strip()).strip()
        umap[raw] = txt if txt else pd.NA
    return s.map(umap).astype("string")


def _fast_race_active_rel(race_codes, n_races, vals, active):
    """Vectorized `vals - mean(vals over active runners in race)` via `np.bincount`."""
    n = len(vals)
    if n == 0 or n_races == 0:
        return np.full(n, np.nan, dtype=np.float64)
    rc_ok = race_codes >= 0
    valid = active & rc_ok & np.isfinite(vals)
    if not valid.any():
        return np.full(n, np.nan, dtype=np.float64)
    v_rc = race_codes[valid]
    sum_r = np.bincount(v_rc, weights=vals[valid], minlength=n_races)
    cnt_r = np.bincount(v_rc, minlength=n_races)
    has_mean = cnt_r > 0
    safe_cnt = np.where(has_mean, cnt_r, 1.0)
    mean_by_rc = np.where(has_mean, sum_r / safe_cnt, np.nan)
    race_mean = np.where(rc_ok, mean_by_rc[np.maximum(race_codes, 0)], np.nan)
    return vals - race_mean


def _build_v10_ctx(df, needed_cols):
    """Build shared sorted work state once across all requested V10 blocks."""
    work = _lite_work_frame(df, needed_cols)
    n = len(work)
    active = _active_mask(work)
    fin = _to_f64(_col_or_empty(work, "finish", dtype="float64"))
    settled = active & np.isfinite(fin)
    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)
    race_codes, _ = pd.factorize(work["race_id"], sort=False)
    n_races = int(race_codes.max()) + 1 if (race_codes >= 0).any() else 0
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    day_off, stride, _ = _day_stride(day_arr)
    inv = _inv_order(work)
    return {
        "index": df.index,
        "work": work,
        "n": n,
        "active": active,
        "fin": fin,
        "settled": settled,
        "hk_codes": hk_codes,
        "race_codes": race_codes,
        "n_races": n_races,
        "day_arr": day_arr,
        "day_off": day_off,
        "stride": stride,
        "inv": inv,
    }


def _ctx_race_groups(ctx):
    """Lazily compute contiguous race groups on shared `ctx`."""
    cached = ctx.get("_race_groups")
    if cached is not None:
        return cached
    race_codes = ctx["race_codes"]
    order = np.argsort(race_codes, kind="mergesort")
    rc_o = race_codes[order]
    valid = rc_o >= 0
    if not valid.any():
        splits = np.zeros(1, dtype=np.int64)
    else:
        start = int(np.flatnonzero(valid)[0])
        rc_v = rc_o[start:]
        splits = np.r_[start, start + np.flatnonzero(rc_v[1:] != rc_v[:-1]) + 1, len(rc_o)]
    cached = (order, splits)
    ctx["_race_groups"] = cached
    return cached


def _ctx_fpct(ctx):
    """Lazily obtain `fpct` float64 array on shared `ctx`."""
    cached = ctx.get("_fpct")
    if cached is not None:
        return cached
    work = ctx["work"]
    cached = _to_f64(work["fpct"]) if "fpct" in work.columns else _fpct_array(work)
    ctx["_fpct"] = cached
    return cached


def _ctx_agf_share(ctx):
    """Lazily obtain `agf_share` float64 array on shared `ctx`."""
    cached = ctx.get("_agf_share")
    if cached is not None:
        return cached
    cached = _compute_agf_share(ctx["work"], ctx["active"])
    ctx["_agf_share"] = cached
    return cached


def _attach_cols(df, cols_dict):
    """Attach computed V10 columns to `df` cleanly in a single non-fragmenting concat."""
    new_df = pd.DataFrame(cols_dict, index=df.index)
    overlap = [c for c in cols_dict if c in df.columns]
    base = df.drop(columns=overlap) if overlap else df
    return pd.concat([base, new_df], axis=1)


def _gather_prior_windows(ev_mask, hk_codes, day_off, stride, ev_arrays, window):
    """Gather up to `window` most recent `< D` valid event tuples per horse via searchsorted."""
    n = len(hk_codes)
    k_arr = len(ev_arrays)
    out_wins = [np.full((n, window), np.nan, dtype=np.float64) for _ in range(k_arr)]

    ev_idx = np.flatnonzero(ev_mask & (hk_codes >= 0))
    if len(ev_idx) == 0:
        return out_wins

    ehk = hk_codes[ev_idx].astype(np.int64, copy=False)
    eday = day_off[ev_idx].astype(np.int64, copy=False)
    order = np.lexsort((ev_idx, eday, ehk))
    s_idx = ev_idx[order]
    s_hk = ehk[order]
    s_day = eday[order]
    ev_keys = s_hk * stride + s_day
    n_ev = len(ev_idx)
    ar_ev = np.arange(n_ev, dtype=np.int64)

    win_ev = []
    for arr in ev_arrays:
        s_val = np.asarray(arr, dtype=np.float64)[s_idx]
        mat = np.full((n_ev, window), np.nan, dtype=np.float64)
        mat[:, 0] = s_val
        for lag in range(1, window):
            if lag >= n_ev:
                break
            same = (ar_ev >= lag) & (s_hk == np.roll(s_hk, lag))
            mat[lag:, lag] = np.where(same[lag:], s_val[:-lag], np.nan)
        win_ev.append(mat)

    q_rows = np.flatnonzero(hk_codes >= 0)
    if len(q_rows) == 0:
        return out_wins

    q_hk = hk_codes[q_rows].astype(np.int64, copy=False)
    q_keys = q_hk * stride + day_off[q_rows].astype(np.int64, copy=False)
    pos = np.searchsorted(ev_keys, q_keys, side="left") - 1
    safe_pos = np.maximum(pos, 0)
    hit = (pos >= 0) & (s_hk[safe_pos] == q_hk)
    if not hit.any():
        return out_wins

    hit_rows = q_rows[hit]
    hit_ev = safe_pos[hit]
    for ci, mat in enumerate(win_ev):
        out_wins[ci][hit_rows] = mat[hit_ev]
    return out_wins


def _posterior_mean_std(win_mat, active, prior_df, prior_std):
    """Compute Bayesian-shrunk posterior mean & std over up to W prior events."""
    n = len(active)
    valid = np.isfinite(win_mat)
    cnt = np.sum(valid, axis=1)
    ok = active & (cnt >= 1)

    mu = np.full(n, np.nan, dtype=np.float64)
    std = np.full(n, np.nan, dtype=np.float64)
    if not ok.any():
        return mu, std

    w_ok = win_mat[ok]
    v_ok = valid[ok]
    c_ok = cnt[ok].astype(np.float64)
    s_ok = np.sum(np.where(v_ok, w_ok, 0.0), axis=1) / c_ok
    diff = np.where(v_ok, w_ok - s_ok[:, None], 0.0)
    ss = np.sum(diff * diff, axis=1)
    var = (ss + float(prior_df) * (float(prior_std) ** 2)) / (np.maximum(c_ok - 1.0, 0.0) + float(prior_df))

    mu[ok] = s_ok
    std[ok] = np.sqrt(var)
    return mu, std


def _active_race_pairs(ctx):
    """Vectorized all ordered `(i, k)` pairs of active runners sharing a `race_id`."""
    order, splits = _ctx_race_groups(ctx)
    if len(splits) <= 1:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty

    act_o = ctx["active"][order]
    by_size = {}
    for g_idx in range(len(splits) - 1):
        s, e = int(splits[g_idx]), int(splits[g_idx + 1])
        r_rows = order[s:e]
        a_rows = r_rows[act_o[s:e]]
        m = len(a_rows)
        if m >= 2:
            by_size.setdefault(m, []).append(a_rows)

    if not by_size:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty

    ii_parts = []
    kk_parts = []
    for m, chunks in by_size.items():
        mat = np.vstack(chunks)
        ii_parts.append(np.repeat(mat, m, axis=1).ravel())
        kk_parts.append(np.tile(mat, (1, m)).ravel())
    return np.concatenate(ii_parts), np.concatenate(kk_parts)


# ---------------------------------------------------------------------------
# 1. BELL — Horse bell-curve volatility, 90th-pct ceiling & upset probability
# ---------------------------------------------------------------------------
def _compute_BELL(ctx):
    work = ctx["work"]
    n = ctx["n"]
    active = ctx["active"]
    settled = ctx["settled"]
    hk_codes = ctx["hk_codes"]
    day_off = ctx["day_off"]
    stride = ctx["stride"]
    inv = ctx["inv"]

    sf_arr = _to_f64(_col_or_empty(work, "sf", dtype="float64"))
    fpct_arr = _ctx_fpct(ctx)

    (sf_win,) = _gather_prior_windows(
        settled & np.isfinite(sf_arr),
        hk_codes,
        day_off,
        stride,
        (sf_arr,),
        BELL_WINDOW,
    )
    (fp_win,) = _gather_prior_windows(
        settled & np.isfinite(fpct_arr),
        hk_codes,
        day_off,
        stride,
        (fpct_arr,),
        BELL_WINDOW,
    )

    mu_sf, bell_sf_std = _posterior_mean_std(sf_win, active, BELL_PRIOR_DF, BELL_SF_PRIOR_STD)
    _, bell_fpct_std = _posterior_mean_std(fp_win, active, BELL_PRIOR_DF, BELL_FPCT_PRIOR_STD)
    bell_sf_std_rel = _fast_race_active_rel(ctx["race_codes"], ctx["n_races"], bell_sf_std, active)
    bell_sf_p90 = mu_sf + _NORM_P90_Z * bell_sf_std

    order, splits = _ctx_race_groups(ctx)
    cand = active & np.isfinite(mu_sf) & np.isfinite(bell_sf_std)
    mu_l = mu_sf.tolist()
    std_l = bell_sf_std.tolist()
    cand_l = cand.tolist()
    order_l = order.tolist()
    rmu_l = [math.nan] * n
    rstd_l = [math.nan] * n

    for g_idx in range(len(splits) - 1):
        s, e = int(splits[g_idx]), int(splits[g_idx + 1])
        top1_m = -math.inf
        top1_s = math.nan
        top1_i = -1
        top2_m = -math.inf
        top2_s = math.nan
        n_cand = 0
        for p in range(s, e):
            idx = order_l[p]
            if not cand_l[idx]:
                continue
            n_cand += 1
            m_val = mu_l[idx]
            s_val = std_l[idx]
            if m_val > top1_m:
                top2_m, top2_s = top1_m, top1_s
                top1_m, top1_s, top1_i = m_val, s_val, idx
            elif m_val > top2_m:
                top2_m, top2_s = m_val, s_val
        if n_cand < 2:
            continue
        for p in range(s, e):
            idx = order_l[p]
            if not cand_l[idx]:
                continue
            if idx == top1_i:
                rmu_l[idx] = top2_m
                rstd_l[idx] = top2_s
            else:
                rmu_l[idx] = top1_m
                rstd_l[idx] = top1_s

    rival_mu = np.array(rmu_l, dtype=np.float64)
    rival_std = np.array(rstd_l, dtype=np.float64)

    bell_upside_gap = bell_sf_p90 - rival_mu
    denom = np.sqrt(bell_sf_std * bell_sf_std + rival_std * rival_std)
    ok_prob = np.isfinite(mu_sf) & np.isfinite(rival_mu) & np.isfinite(denom) & (denom > 0.0)
    bell_prob_beat_fav = np.full(n, np.nan, dtype=np.float64)
    bell_prob_beat_fav[ok_prob] = ndtr((mu_sf[ok_prob] - rival_mu[ok_prob]) / denom[ok_prob])

    return {
        "bell_sf_std": bell_sf_std[inv],
        "bell_sf_std_rel": bell_sf_std_rel[inv],
        "bell_sf_p90": bell_sf_p90[inv],
        "bell_upside_gap": bell_upside_gap[inv],
        "bell_prob_beat_fav": bell_prob_beat_fav[inv],
        "bell_fpct_std": bell_fpct_std[inv],
    }


def attach_BELL(df):
    """Attach BELL block: horse SF & FPCT volatility, P90 ceiling, and prob vs top rival."""
    if len(df) == 0:
        return _empty_result(df, BELL_COLS)
    ctx = _build_v10_ctx(df, _BLOCK_NEEDED_COLS["BELL"])
    return _attach_cols(df, _compute_BELL(ctx))


# ---------------------------------------------------------------------------
# 2. JLOY — Jockey abandonment/choice, 365d trainer loyalty & JWR upgrade
# ---------------------------------------------------------------------------
def _compute_JLOY(ctx):
    work = ctx["work"]
    n = ctx["n"]
    active = ctx["active"]
    fin = ctx["fin"]
    settled = ctx["settled"]
    hk_codes = ctx["hk_codes"]
    day_arr = ctx["day_arr"]
    day_off = ctx["day_off"]
    stride = ctx["stride"]
    inv = ctx["inv"]

    j_s = _fast_normalize_jockey(_col_or_empty(work, "jockey", dtype="string"))
    j_codes, _ = pd.factorize(j_s, sort=False)
    t_s = _norm_upper_str(_col_or_empty(work, "trainer", dtype="string"))
    t_codes, _ = pd.factorize(t_s, sort=False)

    agf_share = _ctx_agf_share(ctx)
    if "j_wr" in work.columns:
        cur_j_wr = _to_f64(work["j_wr"])
    else:
        zeros = np.zeros(n, dtype=np.int64)
        st_v = settled.astype(np.float64)
        wn_v = (settled & (fin == 1.0)).astype(np.float64)
        z_v = np.zeros(n, dtype=np.float64)
        p_st, p_wn, _, _, _, _ = _prior_keyed_stats(
            zeros,
            j_codes,
            day_arr,
            st_v,
            wn_v,
            z_v,
            z_v,
            z_v,
            need_sf=False,
        )
        cur_j_wr = np.where(
            j_codes >= 0,
            (np.nan_to_num(p_wn, nan=0.0) + 1.0) / (np.nan_to_num(p_st, nan=0.0) + 10.0),
            np.nan,
        )

    j_float = np.where(j_codes >= 0, j_codes.astype(np.float64), np.nan)
    (pj_win,) = _gather_prior_windows(
        settled & (j_codes >= 0),
        hk_codes,
        day_off,
        stride,
        (j_float,),
        1,
    )
    pj_raw = pj_win[:, 0]
    prev_j = np.where(np.isfinite(pj_raw), np.nan_to_num(pj_raw, nan=-1.0).astype(np.int64), -1)

    j_abandoned = np.full(n, np.nan, dtype=np.float64)
    j_chose = np.full(n, np.nan, dtype=np.float64)
    j_chose_agf = np.full(n, np.nan, dtype=np.float64)
    j_chose_loyal = np.full(n, np.nan, dtype=np.float64)
    j_trn_share = np.full(n, np.nan, dtype=np.float64)

    has_pj = active & (prev_j >= 0)
    has_cj = active & (j_codes >= 0)
    j_abandoned[has_pj] = 0.0
    j_chose[has_cj] = 0.0
    j_chose_loyal[has_cj] = 0.0

    ii, kk = _active_race_pairs(ctx)
    if len(ii) > 0:
        neq = ii != kk
        ii_n = ii[neq]
        kk_n = kk[neq]

        ab_mask = (prev_j[ii_n] >= 0) & (prev_j[ii_n] != j_codes[ii_n]) & (j_codes[kk_n] == prev_j[ii_n])
        if ab_mask.any():
            j_abandoned[np.unique(ii_n[ab_mask])] = 1.0

        ch_mask = (j_codes[ii_n] >= 0) & (prev_j[kk_n] == j_codes[ii_n]) & (j_codes[kk_n] != j_codes[ii_n])
        if ch_mask.any():
            ch_i = ii_n[ch_mask]
            ch_k = kk_n[ch_mask]
            j_chose[np.unique(ch_i)] = 1.0

            agf_k = agf_share[ch_k]
            agf_i = agf_share[ch_i]
            both_agf = np.isfinite(agf_k) & np.isfinite(agf_i)
            if both_agf.any():
                max_k_agf = np.full(n, -np.inf, dtype=np.float64)
                np.maximum.at(max_k_agf, ch_i[both_agf], agf_k[both_agf])
                diff_rows = np.isfinite(max_k_agf) & (max_k_agf > -np.inf)
                j_chose_agf[diff_rows] = agf_share[diff_rows] - max_k_agf[diff_rows]

        pair_ev = settled & (j_codes >= 0) & (t_codes >= 0)
        if pair_ev.any():
            max_tc = int(t_codes.max())
            t_stride = max(max_tc + 100, 100_000)
            ev_pkeys = j_codes[pair_ev].astype(np.int64) * t_stride + t_codes[pair_ev].astype(np.int64)
            u_pkeys, ev_pcodes = np.unique(ev_pkeys, return_inverse=True)

            cand_ok = (j_codes[ii] >= 0) & (t_codes[kk] >= 0)
            if cand_ok.any():
                ii_c = ii[cand_ok]
                kk_c = kk[cand_ok]
                cand_keys = j_codes[ii_c].astype(np.int64) * t_stride + t_codes[kk_c].astype(np.int64)
                pos = np.searchsorted(u_pkeys, cand_keys)
                pos_clip = np.minimum(pos, len(u_pkeys) - 1)
                found = (pos < len(u_pkeys)) & (u_pkeys[pos_clip] == cand_keys)
                if found.any():
                    q_pcodes = pos_clip[found].astype(np.int64)
                    q_ii = ii_c[found]
                    q_kk = kk_c[found]
                    q_days = day_off[q_ii]
                    q_lo = day_off[q_ii] - JLOY_WINDOW_DAYS
                    (tj_cnts,) = _range_window_agg(
                        ev_pcodes.astype(np.int64),
                        day_off[pair_ev],
                        [np.ones(int(pair_ev.sum()), dtype=np.float64)],
                        q_pcodes,
                        q_lo,
                        q_days,
                        stride,
                    )

                    self_pair = q_ii == q_kk
                    self_tj = np.zeros(n, dtype=np.float64)
                    if self_pair.any():
                        self_tj[q_ii[self_pair]] = tj_cnts[self_pair]

                    sum_tj = np.bincount(q_ii, weights=tj_cnts, minlength=n).astype(np.float64)
                    share_ok = has_cj & (t_codes >= 0) & (sum_tj > 0.0)
                    j_trn_share[share_ok] = self_tj[share_ok] / sum_tj[share_ok]

                    other_t = (q_ii != q_kk) & (t_codes[q_kk] != t_codes[q_ii])
                    if other_t.any():
                        max_other_tj = np.zeros(n, dtype=np.float64)
                        np.maximum.at(max_other_tj, q_ii[other_t], tj_cnts[other_t])
                        loyal_hit = (
                            has_cj
                            & (max_other_tj >= float(JLOY_LOYAL_MIN_RIDES))
                            & (max_other_tj >= 2.0 * self_tj)
                        )
                        j_chose_loyal[loyal_hit] = 1.0

    t_jwr_upgrade = np.full(n, np.nan, dtype=np.float64)
    q_t_mask = active & (t_codes >= 0) & np.isfinite(cur_j_wr)
    if q_t_mask.any():
        t_ev = settled & (t_codes >= 0) & np.isfinite(cur_j_wr)
        t_typ = np.full(n, JLOY_JWR_PRIOR, dtype=np.float64)
        if t_ev.any():
            q_rows = np.flatnonzero(q_t_mask)
            sum_jwr, cnt_jwr = _range_window_agg(
                t_codes[t_ev],
                day_off[t_ev],
                [cur_j_wr[t_ev], np.ones(int(t_ev.sum()), dtype=np.float64)],
                t_codes[q_rows],
                day_off[q_rows] - JLOY_WINDOW_DAYS,
                day_off[q_rows],
                stride,
            )
            t_typ[q_rows] = (sum_jwr + JLOY_T_JWR_PRIOR_N * JLOY_JWR_PRIOR) / (cnt_jwr + JLOY_T_JWR_PRIOR_N)
        t_jwr_upgrade[q_t_mask] = cur_j_wr[q_t_mask] - t_typ[q_t_mask]

    return {
        "j_abandoned_to_rival": j_abandoned[inv],
        "j_chose_over_prev": j_chose[inv],
        "j_chose_agf_diff": j_chose_agf[inv],
        "j_chose_over_loyal_trn": j_chose_loyal[inv],
        "j_trn_loyal_share_race": j_trn_share[inv],
        "t_jwr_upgrade": t_jwr_upgrade[inv],
    }


def attach_JLOY(df):
    """Attach JLOY block: jockey choice/abandonment, trainer loyalty, and jockey upgrade."""
    if len(df) == 0:
        return _empty_result(df, JLOY_COLS)
    ctx = _build_v10_ctx(df, _BLOCK_NEEDED_COLS["JLOY"])
    return _attach_cols(df, _compute_JLOY(ctx))


# ---------------------------------------------------------------------------
# 3. LOAD — Cumulative exertion integral (distance/EWMA) & SF velocity/accel
# ---------------------------------------------------------------------------
def _compute_LOAD(ctx):
    work = ctx["work"]
    n = ctx["n"]
    active = ctx["active"]
    settled = ctx["settled"]
    hk_codes = ctx["hk_codes"]
    valid_hk = hk_codes >= 0
    day_arr = ctx["day_arr"]
    day_off = ctx["day_off"]
    stride = ctx["stride"]
    inv = ctx["inv"]

    dist_arr = _to_f64(_col_or_empty(work, "distance", dtype="float64"))
    dist_ok = np.where(np.isfinite(dist_arr) & (dist_arr > 0.0), dist_arr, 0.0)
    dist_km = dist_ok / 1000.0
    sf_arr = _to_f64(_col_or_empty(work, "sf", dtype="float64"))
    fpct_arr = _ctx_fpct(ctx)

    load_dist_60d = np.where(active & valid_hk, 0.0, np.nan)
    load_dist_180d = np.where(active & valid_hk, 0.0, np.nan)
    ev_dist = settled & valid_hk & (dist_km > 0.0)
    q_mask = active & valid_hk
    if ev_dist.any() and q_mask.any():
        q_rows = np.flatnonzero(q_mask)
        (d60,) = _range_window_agg(
            hk_codes[ev_dist],
            day_off[ev_dist],
            [dist_km[ev_dist]],
            hk_codes[q_rows],
            day_off[q_rows] - LOAD_WIN_60,
            day_off[q_rows],
            stride,
        )
        (d180,) = _range_window_agg(
            hk_codes[ev_dist],
            day_off[ev_dist],
            [dist_km[ev_dist]],
            hk_codes[q_rows],
            day_off[q_rows] - LOAD_WIN_180,
            day_off[q_rows],
            stride,
        )
        load_dist_60d[q_rows] = d60
        load_dist_180d[q_rows] = d180

    fpct_eff = np.where(np.isfinite(fpct_arr), fpct_arr, 0.5)
    effort_arr = (dist_ok / LOAD_DIST_REF) * (1.0 + 0.5 * (1.0 - fpct_eff))

    order = np.argsort(hk_codes, kind="mergesort")
    hk_o = hk_codes[order].tolist()
    day_o = day_arr[order].tolist()
    act_o = active[order].tolist()
    set_o = settled[order].tolist()
    eff_o = effort_arr[order].tolist()
    order_l = order.tolist()
    wear_l = [math.nan] * n

    exp = math.exp
    pos = 0
    while pos < n:
        hk_c = hk_o[pos]
        end_h = pos + 1
        while end_h < n and hk_o[end_h] == hk_c:
            end_h += 1
        if hk_c < 0:
            pos = end_h
            continue

        wear = 0.0
        last_day = -1
        cur = pos
        while cur < end_h:
            d_cur = day_o[cur]
            d_end = cur + 1
            while d_end < end_h and day_o[d_end] == d_cur:
                d_end += 1

            decayed = wear * exp(-(d_cur - last_day) / LOAD_DECAY_DAYS) if (last_day >= 0 and wear > 0.0) else 0.0
            day_add = 0.0
            has_settled = False
            for p in range(cur, d_end):
                idx = order_l[p]
                if act_o[p]:
                    wear_l[idx] = decayed
                if set_o[p]:
                    day_add += eff_o[p]
                    has_settled = True
            if has_settled:
                wear = decayed + day_add
                last_day = d_cur
            cur = d_end
        pos = end_h

    load_ewma_wear = np.array(wear_l, dtype=np.float64)

    day_f64 = day_arr.astype(np.float64)
    sf_win, d_win = _gather_prior_windows(
        settled & np.isfinite(sf_arr),
        hk_codes,
        day_off,
        stride,
        (sf_arr, day_f64),
        3,
    )
    sf1, sf2, sf3 = sf_win[:, 0], sf_win[:, 1], sf_win[:, 2]
    d1, d2 = d_win[:, 0], d_win[:, 1]

    has_v = active & np.isfinite(sf1) & np.isfinite(sf2) & np.isfinite(d1) & np.isfinite(d2)
    sf_vel_recent = np.full(n, np.nan, dtype=np.float64)
    if has_v.any():
        dt12 = np.maximum(d1[has_v] - d2[has_v], LOAD_VEL_MIN_DAYS)
        sf_vel_recent[has_v] = (sf1[has_v] - sf2[has_v]) / dt12 * 30.0

    has_a = has_v & np.isfinite(sf3)
    sf_accel = np.full(n, np.nan, dtype=np.float64)
    sf_accel[has_a] = (sf1[has_a] - sf2[has_a]) - (sf2[has_a] - sf3[has_a])

    return {
        "load_dist_60d": load_dist_60d[inv],
        "load_dist_180d": load_dist_180d[inv],
        "load_ewma_wear": load_ewma_wear[inv],
        "sf_vel_recent": sf_vel_recent[inv],
        "sf_accel": sf_accel[inv],
    }


def attach_LOAD(df):
    """Attach LOAD block: 60d/180d distance sum, EWMA wear integral, SF velocity & accel."""
    if len(df) == 0:
        return _empty_result(df, LOAD_COLS)
    ctx = _build_v10_ctx(df, _BLOCK_NEEDED_COLS["LOAD"])
    return _attach_cols(df, _compute_LOAD(ctx))


# ---------------------------------------------------------------------------
# 4. H2H — Direct head-to-head rivalry history over last 730 days
# ---------------------------------------------------------------------------
def _compute_H2H(ctx):
    n = ctx["n"]
    active = ctx["active"]
    fin = ctx["fin"]
    settled = ctx["settled"]
    hk_codes = ctx["hk_codes"]
    race_codes = ctx["race_codes"]
    day_arr = ctx["day_arr"]
    inv = ctx["inv"]

    agf_share = _ctx_agf_share(ctx)
    n_horses = int(hk_codes.max()) + 1 if (hk_codes >= 0).any() else 0

    rivals_met = np.where(active, 0.0, np.nan)
    meetings = np.where(active, 0.0, np.nan)
    beat_rate = np.full(n, np.nan, dtype=np.float64)
    vs_fav_margin = np.full(n, np.nan, dtype=np.float64)

    if n_horses > 0:
        day_l = day_arr.tolist()
        hk_l = hk_codes.tolist()
        rc_l = race_codes.tolist()
        act_l = active.tolist()
        set_l = settled.tolist()
        fin_l = fin.tolist()
        agf_l = agf_share.tolist()

        rivals_l = [0.0 if a else math.nan for a in act_l]
        meet_l = [0.0 if a else math.nan for a in act_l]
        rate_l = [math.nan] * n
        fav_l = [math.nan] * n

        hist_races = [deque(maxlen=H2H_MAX_HIST_RACES) for _ in range(n_horses)]
        isfinite = math.isfinite

        d_start = 0
        while d_start < n:
            d_cur = day_l[d_start]
            d_end = d_start + 1
            while d_end < n and day_l[d_end] == d_cur:
                d_end += 1
            cutoff = d_cur - H2H_WINDOW_DAYS

            # Pass 1 on day D: read-only queries against `< D` race histories (same-day frozen)
            day_races = {}
            for p in range(d_start, d_end):
                rc_cur = rc_l[p]
                if rc_cur >= 0:
                    day_races.setdefault(rc_cur, []).append(p)

            for r_rows in day_races.values():
                a_idxs = []
                top1_agf = -math.inf
                top1_loc = -1
                top2_agf = -math.inf
                top2_loc = -1
                for p in r_rows:
                    if not act_l[p]:
                        continue
                    loc = len(a_idxs)
                    a_idxs.append(p)
                    av = agf_l[p]
                    if isfinite(av):
                        if av > top1_agf:
                            top2_agf, top2_loc = top1_agf, top1_loc
                            top1_agf, top1_loc = av, loc
                        elif av > top2_agf:
                            top2_agf, top2_loc = av, loc

                m = len(a_idxs)
                if m >= 2:
                    fav_loc = [top2_loc if loc == top1_loc else top1_loc for loc in range(m)]

                    race_to_runners = {}
                    for loc in range(m):
                        hk = hk_l[a_idxs[loc]]
                        if hk < 0:
                            continue
                        dq = hist_races[hk]
                        while dq and dq[0][1] < cutoff:
                            dq.popleft()
                        for r_p, _, f_p in dq:
                            race_to_runners.setdefault(r_p, []).append((loc, f_p))

                    rivals_sets = [set() for _ in range(m)]
                    loc_meet = [0] * m
                    loc_beats = [0.0] * m
                    fav_meet = [0] * m
                    fav_net = [0.0] * m

                    for lst in race_to_runners.values():
                        k_len = len(lst)
                        if k_len < 2:
                            continue
                        for a_pos in range(k_len):
                            li, fi = lst[a_pos]
                            f_target = fav_loc[li]
                            for b_pos in range(k_len):
                                if a_pos == b_pos:
                                    continue
                                lj, fj = lst[b_pos]
                                if li == lj:
                                    continue
                                rivals_sets[li].add(lj)
                                loc_meet[li] += 1
                                if fi < fj:
                                    loc_beats[li] += 1.0
                                elif fi == fj:
                                    loc_beats[li] += 0.5
                                if lj == f_target:
                                    fav_meet[li] += 1
                                    if fi < fj:
                                        fav_net[li] += 1.0
                                    elif fi > fj:
                                        fav_net[li] -= 1.0

                    for loc in range(m):
                        row_i = a_idxs[loc]
                        mt = loc_meet[loc]
                        rivals_l[row_i] = float(len(rivals_sets[loc]))
                        meet_l[row_i] = float(mt)
                        if mt > 0:
                            rate_l[row_i] = (loc_beats[loc] + H2H_PRIOR_W) / (mt + H2H_PRIOR_N)
                        fm = fav_meet[loc]
                        if fm > 0:
                            fav_l[row_i] = fav_net[loc] / float(fm)

            # Pass 2 on day D: commit settled runners strictly after all day-D queries
            for p in range(d_start, d_end):
                if set_l[p]:
                    hk = hk_l[p]
                    if hk >= 0:
                        hist_races[hk].append((rc_l[p], d_cur, fin_l[p]))

            d_start = d_end

        rivals_met = np.array(rivals_l, dtype=np.float64)
        meetings = np.array(meet_l, dtype=np.float64)
        beat_rate = np.array(rate_l, dtype=np.float64)
        vs_fav_margin = np.array(fav_l, dtype=np.float64)

    beat_rate_rel = _fast_race_active_rel(race_codes, ctx["n_races"], beat_rate, active)

    return {
        "h2h_rivals_met": rivals_met[inv],
        "h2h_meetings": meetings[inv],
        "h2h_beat_rate": beat_rate[inv],
        "h2h_beat_rate_rel": beat_rate_rel[inv],
        "h2h_vs_fav_margin": vs_fav_margin[inv],
    }


def attach_H2H(df):
    """Attach H2H block: prior head-to-head meetings, Bayesian beat rate, and vs-fav margin."""
    if len(df) == 0:
        return _empty_result(df, H2H_COLS)
    ctx = _build_v10_ctx(df, _BLOCK_NEEDED_COLS["H2H"])
    return _attach_cols(df, _compute_H2H(ctx))


# ---------------------------------------------------------------------------
# Entrypoints & feature-list builder
# ---------------------------------------------------------------------------
_BLOCK_COMPUTERS = {
    "BELL": _compute_BELL,
    "JLOY": _compute_JLOY,
    "LOAD": _compute_LOAD,
    "H2H": _compute_H2H,
}


def attach_v10(df, blocks=V10_CANDIDATE_BLOCKS):
    """Attach selected v10 pre-race feature blocks (`BELL`, `JLOY`, `LOAD`, `H2H`) in one shared pass."""
    blk_list = tuple(blocks) if not isinstance(blocks, str) else (blocks,)
    for blk in blk_list:
        if blk not in V10_BLOCK_COLS:
            raise ValueError(f"Geçersiz V10 bloğu: {blk!r}. Geçerliler: {tuple(V10_BLOCK_COLS)}")
    if not blk_list:
        return df.copy()
    if len(df) == 0:
        cols = [c for b in blk_list for c in V10_BLOCK_COLS[b]]
        return _empty_result(df, cols)

    needed = set()
    for blk in blk_list:
        needed.update(_BLOCK_NEEDED_COLS[blk])
    ctx = _build_v10_ctx(df, tuple(sorted(needed)))
    all_cols = {}
    for blk in blk_list:
        all_cols.update(_BLOCK_COMPUTERS[blk](ctx))
    return _attach_cols(df, all_cols)


def get_v10_cols(v10_blocks=V10_CANDIDATE_BLOCKS, with_program=False):
    """Return ordered feature column list = V9_CONFIG (`v9_kssb`) + selected v10 blocks."""
    blk_list = tuple(v10_blocks) if not isinstance(v10_blocks, str) else (v10_blocks,)
    for blk in blk_list:
        if blk not in V10_BLOCK_COLS:
            raise ValueError(f"Geçersiz V10 bloğu: {blk!r}. Geçerliler: {tuple(V10_BLOCK_COLS)}")
    if with_program:
        cols = get_v9_cols(v9_blocks=V9_CONFIG["v9_blocks"], with_program=True)
    else:
        cols = list(V9_CONFIG["feature_cols"])
    for blk in blk_list:
        cols.extend(V10_BLOCK_COLS[blk])
    return cols


__all__ = [
    "BELL_COLS",
    "H2H_COLS",
    "JLOY_COLS",
    "LOAD_COLS",
    "SMOOTHING_CONSTANTS",
    "V10_BLOCK_COLS",
    "V10_CANDIDATE_BLOCKS",
    "attach_BELL",
    "attach_H2H",
    "attach_JLOY",
    "attach_LOAD",
    "attach_v10",
    "get_v10_cols",
]
