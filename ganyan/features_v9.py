"""Leak-free v9 pre-race feature blocks (KEY, SHIP, STAB, WORK, BIAS, and diagnostic DAY)."""
import re

import numpy as np
import pandas as pd

from ganyan.features_v5 import _clean_entity_str, _sorted_work_frame, _to_day_int
from ganyan.features_v6 import _to_f64
from ganyan.features_v7 import (
    _active_mask,
    _fpct_array,
    _inv_order,
    _prior_keyed_stats,
)
from ganyan.features_v8 import (
    _JOCKEY_AP_RE,
    _TR_UPPER_MAP,
    _compute_agf_share,
    _race_active_rel,
    get_v8_cols,
)
from ganyan.model_v8 import V8_CONFIG

KEY_COLS = [
    "key_n_ran",
    "key_n_won",
    "key_wr",
    "key_ahead_wr",
    "key_behind_wr",
    "key_wr_m3",
]

SHIP_COLS = [
    "trn_away",
    "trn_city_share_365d",
    "trn_away_resid_730d",
    "h_ship_first",
]

STAB_COLS = [
    "trn_n_28d",
    "trn_resid_14d",
    "trn_resid_28d",
    "trn_fpct_resid_28d",
    "trn_resid_28d_rel",
]

WORK_COLS = [
    "gw_jk_last",
    "gw_jk_n30",
    "gw_hard_days",
    "gw_jk_first_ride",
]

BIAS_COLS = [
    "bias_gate_resid",
    "bias_n",
]

DAY_COLS = [
    "day_bias_n",
    "day_gate_bias",
    "day_gate_bias_x_gf",
]

V9_CANDIDATE_BLOCKS = ("KEY", "SHIP", "STAB", "WORK", "BIAS")

V9_BLOCK_COLS = {
    "KEY": list(KEY_COLS),
    "SHIP": list(SHIP_COLS),
    "STAB": list(STAB_COLS),
    "WORK": list(WORK_COLS),
    "BIAS": list(BIAS_COLS),
    "DAY": list(DAY_COLS),
}

# Fixed Bayesian smoothing & threshold constants (documented in V9 report)
KEY_PRIOR_W = 0.5
KEY_PRIOR_N = 3.0
SHIP_HOME_MIN_STARTS = 10
SHIP_AWAY_PRIOR_N = 20.0
STAB_PRIOR_14 = 10.0
STAB_PRIOR_28 = 15.0
BIAS_WINDOW_DAYS = 1095
BIAS_PRIOR_N = 100.0
DAY_PRIOR_N = 2.0

SMOOTHING_CONSTANTS = {
    "KEY_PRIOR_W": KEY_PRIOR_W,
    "KEY_PRIOR_N": KEY_PRIOR_N,
    "SHIP_HOME_MIN_STARTS": SHIP_HOME_MIN_STARTS,
    "SHIP_AWAY_PRIOR_N": SHIP_AWAY_PRIOR_N,
    "STAB_PRIOR_14": STAB_PRIOR_14,
    "STAB_PRIOR_28": STAB_PRIOR_28,
    "BIAS_WINDOW_DAYS": BIAS_WINDOW_DAYS,
    "BIAS_PRIOR_N": BIAS_PRIOR_N,
    "DAY_PRIOR_N": DAY_PRIOR_N,
}

_POST_TIME_RE = re.compile(r"(\d{1,2})\s*[:.]\s*(\d{2})")
_WS_RE = re.compile(r"\s+")
_DOT_WS_RE = re.compile(r"\s*\.\s*")


def _empty_result(df, cols):
    out = df.copy()
    for c in cols:
        out[c] = pd.Series(dtype="float64")
    return out


def _col_or_empty(work, col, dtype="string"):
    if col in work.columns:
        return work[col]
    fill_val = np.nan if dtype == "float64" else pd.NA
    return pd.Series(fill_val, index=work.index, dtype=dtype)


def _norm_upper_str(series):
    """Normalize string column with Turkish uppercase map and trimmed whitespace."""
    s = _clean_entity_str(series)
    valid = s.notna()
    out = pd.Series(pd.NA, index=s.index, dtype="string")
    if not valid.any():
        return out
    uniq = s[valid].unique()
    umap = {}
    for raw in uniq:
        txt = _WS_RE.sub(" ", str(raw).strip()).translate(_TR_UPPER_MAP).upper()
        umap[raw] = txt if txt else pd.NA
    return s.map(umap).astype("string")


def _day_stride(day_arr):
    """Return `(day_off, stride)` for collision-free `entity_code * stride + day_off` int64 keys."""
    if len(day_arr) == 0:
        return np.zeros(0, dtype=np.int64), 1_000_000, 0
    d_min = int(day_arr.min())
    d_max = int(day_arr.max())
    day_off = (day_arr - d_min).astype(np.int64)
    stride = max(d_max - d_min + 100, 1_000_000)
    return day_off, stride, d_min


def _range_window_agg(
    ev_entity,
    ev_day_off,
    ev_vals,
    q_entity,
    q_day_lo,
    q_day_hi,
    stride,
    chunk_size=250_000,
):
    """Vectorized `[q_day_lo, q_day_hi)` sliding-window sums per entity via int64 key + cumsum."""
    m = len(q_entity)
    k_cols = len(ev_vals)
    out = [np.zeros(m, dtype=np.float64) for _ in range(k_cols)]
    if m == 0 or len(ev_entity) == 0:
        return out

    ev_keys = ev_entity.astype(np.int64) * stride + ev_day_off.astype(np.int64)
    tmp = {"_k": ev_keys}
    v_names = []
    for ci, arr in enumerate(ev_vals):
        vcol = f"_v{ci}"
        tmp[vcol] = np.asarray(arr, dtype=np.float64)
        v_names.append(vcol)
    grp = pd.DataFrame(tmp).groupby("_k", sort=True, as_index=False).sum()

    u_keys = grp["_k"].to_numpy(dtype=np.int64)
    u_ent = u_keys // stride
    grp["_ent"] = u_ent
    in_cs_df = grp.groupby("_ent", sort=False)[v_names].cumsum()
    in_cs_list = [in_cs_df[vcol].to_numpy(dtype=np.float64) for vcol in v_names]

    q_ent_i64 = q_entity.astype(np.int64)
    q_lo_k = q_ent_i64 * stride + np.maximum(q_day_lo, 0).astype(np.int64)
    q_hi_k = q_ent_i64 * stride + np.maximum(q_day_hi, 0).astype(np.int64)
    m_keys = len(u_keys)

    for s in range(0, m, chunk_size):
        e = min(s + chunk_size, m)
        p_lo = np.searchsorted(u_keys, q_lo_k[s:e], side="left")
        p_hi = np.searchsorted(u_keys, q_hi_k[s:e], side="left")
        has = p_hi > p_lo
        if not has.any():
            continue
        pl = p_lo[has]
        ph = p_hi[has] - 1
        same_prev = (pl > 0) & (u_ent[np.maximum(pl - 1, 0)] == u_ent[pl])
        prev_idx = np.maximum(pl - 1, 0)
        for ci, ics in enumerate(in_cs_list):
            sub_val = np.where(same_prev, ics[prev_idx], 0.0)
            out[ci][s:e][has] = ics[ph] - sub_val
    return out


def _lite_work_frame(df, needed_cols):
    """Sort `df` deterministically via `_sorted_work_frame` after slicing only required columns."""
    base_cols = ("date", "city", "race_no", "race_id", "horse_key")
    keep = [c for c in df.columns if c in base_cols or c in needed_cols]
    return _sorted_work_frame(df[keep])


def _gate_frac_array(work, active):
    """Return `gate_frac` on `(0, 1]` using existing column or active race field."""
    if "gate_frac" in work.columns:
        gf = _to_f64(work["gate_frac"])
        return np.where(active & np.isfinite(gf) & (gf > 0.0), gf, np.nan)
    gate = _to_f64(_col_or_empty(work, "gate", dtype="float64"))
    work["_v9_act_cnt"] = active.astype(np.float64)
    fld = np.maximum(
        work.groupby("race_id", sort=False)["_v9_act_cnt"].transform("sum").to_numpy(dtype=np.float64),
        1.0,
    )
    return np.where(active & np.isfinite(gate) & (gate > 0.0), gate / fld, np.nan)


def _dist_band_v9(distance_series):
    """Bucket race distance per V9 spec: <=1200->0, 1201-1600->1, 1601-2000->2, >2000->3."""
    d = _to_f64(distance_series)
    out = np.full(len(d), -1, dtype=np.int64)
    ok = np.isfinite(d) & (d > 0.0)
    out[ok & (d <= 1200.0)] = 0
    out[ok & (d > 1200.0) & (d <= 1600.0)] = 1
    out[ok & (d > 1600.0) & (d <= 2000.0)] = 2
    out[ok & (d > 2000.0)] = 3
    return out


# ---------------------------------------------------------------------------
# 1. KEY — Key races (subsequent wins/runs of rivals strictly > d_R and < D)
# ---------------------------------------------------------------------------
def attach_KEY(df):
    """Attach KEY block: subsequent performance of rivals faced in horse's last 1 & 3 races."""
    if len(df) == 0:
        return _empty_result(df, KEY_COLS)

    work = _lite_work_frame(df, ("scratched", "finish"))
    n = len(work)
    active = _active_mask(work)
    fin = _to_f64(_col_or_empty(work, "finish", dtype="float64"))
    settled = active & np.isfinite(fin)

    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)
    valid_hk = hk_codes >= 0
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    day_off, stride, _ = _day_stride(day_arr)

    key_n_ran = np.full(n, np.nan, dtype=np.float64)
    key_n_won = np.full(n, np.nan, dtype=np.float64)
    key_wr = np.full(n, np.nan, dtype=np.float64)
    key_ahead_wr = np.full(n, np.nan, dtype=np.float64)
    key_behind_wr = np.full(n, np.nan, dtype=np.float64)
    wr_sum3 = np.zeros(n, dtype=np.float64)
    wr_cnt3 = np.zeros(n, dtype=np.int32)

    s_mask = settled & valid_hk
    if s_mask.any():
        s_idx = np.flatnonzero(s_mask)
        s_hk = hk_codes[s_idx].astype(np.int64)
        s_day = day_off[s_idx]
        s_fin = fin[s_idx]
        race_codes, _ = pd.factorize(work["_rid_sort"], sort=False)
        s_rc = race_codes[s_idx].astype(np.int64)
        s_rno = work["_race_no_n"].to_numpy(dtype=np.int64)[s_idx]

        # Unique sorted (horse_code, day_off) keys for strictly (d_R, D) lookups
        s_keys_all = s_hk * stride + s_day
        run_keys = np.unique(s_keys_all)
        win_mask_s = s_fin == 1.0
        win_keys = np.unique(s_keys_all[win_mask_s]) if win_mask_s.any() else np.zeros(0, dtype=np.int64)

        # Build contiguous race slices for settled runners so rival expansion is pure NumPy
        r_order = np.argsort(s_rc, kind="mergesort")
        rc_sorted = s_rc[r_order]
        rc_hk = s_hk[r_order]
        rc_fin = s_fin[r_order]

        max_rc = int(rc_sorted.max()) + 1
        rc_start = np.zeros(max_rc, dtype=np.int64)
        rc_len = np.zeros(max_rc, dtype=np.int64)
        r_splits = np.r_[0, np.flatnonzero(rc_sorted[1:] != rc_sorted[:-1]) + 1, len(rc_sorted)]
        u_rc = rc_sorted[r_splits[:-1]]
        rc_start[u_rc] = r_splits[:-1]
        rc_len[u_rc] = np.diff(r_splits)

        # Sort settled history per horse deterministically by (hk, day, race_no, orig_idx)
        h_order = np.lexsort((s_idx, s_rno, s_day, s_hk))
        hs_hk = s_hk[h_order]
        hs_day = s_day[h_order]
        hs_rc = s_rc[h_order]
        hs_fin = s_fin[h_order]
        hs_keys = hs_hk * stride + hs_day

        # Last strictly pre-day settled start index (`< D`) for every target row `0..n-1`
        v_idx = np.flatnonzero(valid_hk)
        q_keys_all = hk_codes[v_idx].astype(np.int64) * stride + day_off[v_idx]
        pos_hi = np.searchsorted(hs_keys, q_keys_all, side="left")
        q_hk_all = hk_codes[v_idx].astype(np.int64)
        q_day_all = day_off[v_idx]

        chunk_sz = 100_000
        for lag_k in (1, 2, 3):
            cand_pos = pos_hi - lag_k
            has_k = (cand_pos >= 0) & (hs_hk[np.maximum(cand_pos, 0)] == q_hk_all)
            if not has_k.any():
                break

            row_sel = v_idx[has_k]
            p_sel = cand_pos[has_k]
            target_d = q_day_all[has_k]
            self_hk = q_hk_all[has_k]
            r_id = hs_rc[p_sel]
            d_r = hs_day[p_sel]
            s_fin_k = hs_fin[p_sel]

            tot_n_ran = np.zeros(len(row_sel), dtype=np.float64)
            tot_n_won = np.zeros(len(row_sel), dtype=np.float64)
            ahead_ran = np.zeros(len(row_sel), dtype=np.float64)
            ahead_won = np.zeros(len(row_sel), dtype=np.float64)
            behind_ran = np.zeros(len(row_sel), dtype=np.float64)
            behind_won = np.zeros(len(row_sel), dtype=np.float64)

            for cs in range(0, len(row_sel), chunk_sz):
                ce = min(cs + chunk_sz, len(row_sel))
                c_rc = r_id[cs:ce]
                c_lens = rc_len[c_rc]
                total_exp = int(c_lens.sum())
                if total_exp == 0:
                    continue

                m_c = ce - cs
                loc_qid = np.repeat(np.arange(m_c, dtype=np.int64), c_lens)
                starts_rep = np.repeat(rc_start[c_rc], c_lens)
                cum_lens = np.cumsum(c_lens)
                grp_offsets = cum_lens - c_lens
                intra = np.arange(total_exp, dtype=np.int64) - np.repeat(grp_offsets, c_lens)
                flat_pos = starts_rep + intra

                riv_hk = rc_hk[flat_pos]
                riv_fin = rc_fin[flat_pos]
                q_self_hk = self_hk[cs:ce][loc_qid]
                keep = riv_hk != q_self_hk
                if not keep.any():
                    continue

                loc_qid = loc_qid[keep]
                riv_hk = riv_hk[keep]
                riv_fin = riv_fin[keep]

                q_dr = d_r[cs:ce][loc_qid]
                q_dt = target_d[cs:ce][loc_qid]
                valid_span = (q_dr + 1) < q_dt
                if not valid_span.any():
                    continue

                loc_qid = loc_qid[valid_span]
                riv_hk = riv_hk[valid_span]
                riv_fin = riv_fin[valid_span]
                lo_k = riv_hk * stride + (q_dr[valid_span] + 1)
                hi_k = riv_hk * stride + q_dt[valid_span]

                ran_b = (
                    np.searchsorted(run_keys, hi_k, side="left")
                    > np.searchsorted(run_keys, lo_k, side="left")
                ).astype(np.float64)
                if len(win_keys) > 0:
                    won_b = (
                        np.searchsorted(win_keys, hi_k, side="left")
                        > np.searchsorted(win_keys, lo_k, side="left")
                    ).astype(np.float64)
                else:
                    won_b = np.zeros(len(loc_qid), dtype=np.float64)

                tot_n_ran[cs:ce] = np.bincount(loc_qid, weights=ran_b, minlength=m_c)
                tot_n_won[cs:ce] = np.bincount(loc_qid, weights=won_b, minlength=m_c)

                if lag_k == 1:
                    q_sf = s_fin_k[cs:ce][loc_qid]
                    is_ah = riv_fin < q_sf
                    is_bh = riv_fin > q_sf
                    ahead_ran[cs:ce] = np.bincount(loc_qid, weights=np.where(is_ah, ran_b, 0.0), minlength=m_c)
                    ahead_won[cs:ce] = np.bincount(loc_qid, weights=np.where(is_ah, won_b, 0.0), minlength=m_c)
                    behind_ran[cs:ce] = np.bincount(loc_qid, weights=np.where(is_bh, ran_b, 0.0), minlength=m_c)
                    behind_won[cs:ce] = np.bincount(loc_qid, weights=np.where(is_bh, won_b, 0.0), minlength=m_c)

            wr_k = np.where(
                tot_n_ran > 0.0,
                (tot_n_won + KEY_PRIOR_W) / (tot_n_ran + KEY_PRIOR_N),
                np.nan,
            )
            ok_wr = np.isfinite(wr_k)
            wr_sum3[row_sel[ok_wr]] += wr_k[ok_wr]
            wr_cnt3[row_sel[ok_wr]] += 1

            if lag_k == 1:
                key_n_ran[row_sel] = tot_n_ran
                key_n_won[row_sel] = tot_n_won
                key_wr[row_sel] = wr_k
                key_ahead_wr[row_sel] = np.where(
                    ahead_ran > 0.0,
                    (ahead_won + KEY_PRIOR_W) / (ahead_ran + KEY_PRIOR_N),
                    np.nan,
                )
                key_behind_wr[row_sel] = np.where(
                    behind_ran > 0.0,
                    (behind_won + KEY_PRIOR_W) / (behind_ran + KEY_PRIOR_N),
                    np.nan,
                )

    key_wr_m3 = np.where(wr_cnt3 > 0, wr_sum3 / np.maximum(wr_cnt3, 1), np.nan)

    inv = _inv_order(work)
    out = df.copy()
    out["key_n_ran"] = key_n_ran[inv]
    out["key_n_won"] = key_n_won[inv]
    out["key_wr"] = key_wr[inv]
    out["key_ahead_wr"] = key_ahead_wr[inv]
    out["key_behind_wr"] = key_behind_wr[inv]
    out["key_wr_m3"] = key_wr_m3[inv]
    return out


# ---------------------------------------------------------------------------
# 2. SHIP — Trainer home-city 365d, away indicator & 730d away residual
# ---------------------------------------------------------------------------
def attach_SHIP(df):
    """Attach SHIP block: trainer 365d home city, away indicator/share, 730d away residual, h_ship_first."""
    if len(df) == 0:
        return _empty_result(df, SHIP_COLS)

    work = _lite_work_frame(df, ("scratched", "finish", "trainer", "agf_share", "agf_close", "agf_pct"))
    n = len(work)
    active = _active_mask(work)
    fin = _to_f64(_col_or_empty(work, "finish", dtype="float64"))
    settled = active & np.isfinite(fin)
    win_v = np.where(settled & (fin == 1.0), 1.0, 0.0)
    agf_s = _compute_agf_share(work, active)
    agf_finite = np.isfinite(agf_s)

    city_s = _norm_upper_str(_col_or_empty(work, "city"))
    trn_s = _clean_entity_str(_col_or_empty(work, "trainer"))
    city_codes, city_uniques = pd.factorize(city_s, sort=True)
    trn_codes, _ = pd.factorize(trn_s, sort=False)
    hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)

    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    day_off, stride, _ = _day_stride(day_arr)

    trn_away = np.full(n, np.nan, dtype=np.float64)
    trn_city_share_365d = np.full(n, np.nan, dtype=np.float64)
    trn_away_resid_730d = np.full(n, np.nan, dtype=np.float64)
    h_ship_first = np.full(n, np.nan, dtype=np.float64)

    n_cities = len(city_uniques)
    valid_tc = (trn_codes >= 0) & (city_codes >= 0)
    hist_tc = valid_tc & settled

    if hist_tc.any() and n_cities > 0 and valid_tc.any():
        h_idx = np.flatnonzero(hist_tc)
        td_keys_raw = trn_codes[h_idx].astype(np.int64) * stride + day_off[h_idx]
        c_idx = city_codes[h_idx].astype(np.int64)
        # Group daily city start counts per (trainer, day)
        tdc_df = pd.DataFrame({"_k": td_keys_raw, "_c": c_idx, "_cnt": 1.0})
        tdc_agg = (
            tdc_df.groupby(["_k", "_c"], sort=True, as_index=False)["_cnt"]
            .sum()
        )
        u_td_keys, td_pos = np.unique(tdc_agg["_k"].to_numpy(dtype=np.int64), return_inverse=True)
        mat = np.zeros((len(u_td_keys), n_cities), dtype=np.float64)
        mat[td_pos, tdc_agg["_c"].to_numpy(dtype=np.int64)] = tdc_agg["_cnt"].to_numpy(dtype=np.float64)
        cs_mat = np.zeros((len(u_td_keys) + 1, n_cities), dtype=np.float64)
        np.cumsum(mat, axis=0, out=cs_mat[1:])

        q_mask = valid_tc
        q_idx = np.flatnonzero(q_mask)
        qt = trn_codes[q_idx].astype(np.int64)
        qd = day_off[q_idx]
        q_city = city_codes[q_idx].astype(np.int64)
        q_lo = qt * stride + np.maximum(qd - 365, 0)
        q_hi = qt * stride + qd

        chunk_sz = 200_000
        for cs in range(0, len(q_idx), chunk_sz):
            ce = min(cs + chunk_sz, len(q_idx))
            p_lo = np.searchsorted(u_td_keys, q_lo[cs:ce], side="left")
            p_hi = np.searchsorted(u_td_keys, q_hi[cs:ce], side="left")
            p_lo = np.minimum(p_lo, p_hi)
            win_cnts = cs_mat[p_hi] - cs_mat[p_lo]
            tot_365 = win_cnts.sum(axis=1)
            ok_365 = tot_365 >= float(SHIP_HOME_MIN_STARTS)
            if ok_365.any():
                sub_rows = q_idx[cs:ce][ok_365]
                sub_cnts = win_cnts[ok_365]
                sub_tot = tot_365[ok_365]
                sub_city = q_city[cs:ce][ok_365]
                home_city = np.argmax(sub_cnts, axis=1)
                trn_away[sub_rows] = (sub_city != home_city).astype(np.float64)
                trn_city_share_365d[sub_rows] = sub_cnts[np.arange(len(sub_rows)), sub_city] / sub_tot

    # 730-day away residual strictly `< D` using leak-free historical `trn_away == 1.0` starts
    away_agf = settled & agf_finite & (trn_codes >= 0) & (trn_away == 1.0)
    q_trn = trn_codes >= 0
    if away_agf.any() and q_trn.any():
        qi = np.flatnonzero(q_trn)
        ev_i = np.flatnonzero(away_agf)
        ev_res = win_v[ev_i] - agf_s[ev_i]
        aw_cnt, aw_sum = _range_window_agg(
            trn_codes[ev_i],
            day_off[ev_i],
            [np.ones(len(ev_i), dtype=np.float64), ev_res],
            trn_codes[qi],
            day_off[qi] - 730,
            day_off[qi],
            stride,
        )
        trn_away_resid_730d[qi] = np.where(
            aw_cnt >= 1.0,
            aw_sum / (aw_cnt + SHIP_AWAY_PRIOR_N),
            np.nan,
        )

    # `h_ship_first`: horse has >=1 prior settled start `< D` anywhere AND 0 prior settled starts in today's city
    if (hk_codes >= 0).any() and (city_codes >= 0).any():
        starts_v = settled.astype(np.float64)
        zeros_v = np.zeros(n, dtype=np.float64)
        all_one = np.where(hk_codes >= 0, 0, -1).astype(np.int64)
        h_prior_n, _, _, _, _, _ = _prior_keyed_stats(
            hk_codes, all_one, day_arr, starts_v, zeros_v, zeros_v, zeros_v, zeros_v, need_sf=False
        )
        hc_n, _, _, _, _, _ = _prior_keyed_stats(
            hk_codes, city_codes, day_arr, starts_v, zeros_v, zeros_v, zeros_v, zeros_v, need_sf=False
        )
        valid_hs = (hk_codes >= 0) & (city_codes >= 0) & np.isfinite(h_prior_n) & (h_prior_n >= 1.0)
        h_ship_first[valid_hs] = (hc_n[valid_hs] == 0.0).astype(np.float64)

    inv = _inv_order(work)
    out = df.copy()
    out["trn_away"] = trn_away[inv]
    out["trn_city_share_365d"] = trn_city_share_365d[inv]
    out["trn_away_resid_730d"] = trn_away_resid_730d[inv]
    out["h_ship_first"] = h_ship_first[inv]
    return out


# ---------------------------------------------------------------------------
# 3. STAB — Stable form / hot-cold wave over 14d and 28d (< D)
# ---------------------------------------------------------------------------
def attach_STAB(df):
    """Attach STAB block: trainer 14d/28d win & fpct residuals vs AGF expectations."""
    if len(df) == 0:
        return _empty_result(df, STAB_COLS)

    work = _lite_work_frame(df, ("scratched", "finish", "trainer", "fpct", "field", "agf_share", "agf_close", "agf_pct"))
    n = len(work)
    active = _active_mask(work)
    fin = _to_f64(_col_or_empty(work, "finish", dtype="float64"))
    fpct = _fpct_array(work)
    settled = active & np.isfinite(fin)
    win_v = np.where(settled & (fin == 1.0), 1.0, 0.0)
    agf_s = _compute_agf_share(work, active)
    agf_finite = np.isfinite(agf_s)

    # Active AGF rank descending -> expected finish percentile on `[0, 1]`
    work["_v9_agf_act"] = np.where(active & agf_finite, agf_s, np.nan)
    work["_v9_act_f"] = active.astype(np.float64)
    agf_rk = (
        work.groupby("race_id", sort=False)["_v9_agf_act"]
        .rank(ascending=False, method="average")
        .to_numpy(dtype=np.float64)
    )
    agf_n_act = (
        work.groupby("race_id", sort=False)["_v9_agf_act"]
        .transform("count")
        .to_numpy(dtype=np.float64)
    )
    exp_fpct = np.where(
        active & agf_finite & np.isfinite(agf_rk) & (agf_n_act >= 2.0),
        (agf_rk - 1.0) / np.maximum(agf_n_act - 1.0, 1.0),
        np.nan,
    )

    trn_s = _clean_entity_str(_col_or_empty(work, "trainer"))
    trn_codes, _ = pd.factorize(trn_s, sort=False)
    valid_t = trn_codes >= 0
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    day_off, stride, _ = _day_stride(day_arr)

    trn_n_28d = np.full(n, np.nan, dtype=np.float64)
    trn_resid_14d = np.full(n, np.nan, dtype=np.float64)
    trn_resid_28d = np.full(n, np.nan, dtype=np.float64)
    trn_fpct_resid_28d = np.full(n, np.nan, dtype=np.float64)

    hist_t = settled & valid_t
    if valid_t.any():
        qi = np.flatnonzero(valid_t)
        trn_n_28d[qi] = 0.0
        if hist_t.any():
            ev_i = np.flatnonzero(hist_t)
            has_w_agf = agf_finite[ev_i]
            has_f_agf = agf_finite[ev_i] & np.isfinite(fpct[ev_i]) & np.isfinite(exp_fpct[ev_i])

            ev_n_all = np.ones(len(ev_i), dtype=np.float64)
            ev_n_agf = has_w_agf.astype(np.float64)
            ev_w_res = np.where(has_w_agf, win_v[ev_i] - agf_s[ev_i], 0.0)
            ev_n_f = has_f_agf.astype(np.float64)
            ev_f_res = np.where(has_f_agf, fpct[ev_i] - exp_fpct[ev_i], 0.0)

            qd = day_off[qi]
            qt = trn_codes[qi]

            _, n_agf_14, sum_w_14 = _range_window_agg(
                trn_codes[ev_i],
                day_off[ev_i],
                [ev_n_all, ev_n_agf, ev_w_res],
                qt,
                qd - 14,
                qd,
                stride,
            )
            n_all_28, n_agf_28, sum_w_28, n_f_28, sum_f_28 = _range_window_agg(
                trn_codes[ev_i],
                day_off[ev_i],
                [ev_n_all, ev_n_agf, ev_w_res, ev_n_f, ev_f_res],
                qt,
                qd - 28,
                qd,
                stride,
            )

            trn_n_28d[qi] = n_all_28
            trn_resid_14d[qi] = np.where(
                n_agf_14 >= 1.0,
                sum_w_14 / (n_agf_14 + STAB_PRIOR_14),
                np.nan,
            )
            trn_resid_28d[qi] = np.where(
                n_agf_28 >= 1.0,
                sum_w_28 / (n_agf_28 + STAB_PRIOR_28),
                np.nan,
            )
            trn_fpct_resid_28d[qi] = np.where(
                n_f_28 >= 1.0,
                sum_f_28 / (n_f_28 + STAB_PRIOR_28),
                np.nan,
            )

    trn_resid_28d_rel = _race_active_rel(work, trn_resid_28d, active, tmp_col="_v9_stab_rel")

    inv = _inv_order(work)
    out = df.copy()
    out["trn_n_28d"] = trn_n_28d[inv]
    out["trn_resid_14d"] = trn_resid_14d[inv]
    out["trn_resid_28d"] = trn_resid_28d[inv]
    out["trn_fpct_resid_28d"] = trn_fpct_resid_28d[inv]
    out["trn_resid_28d_rel"] = trn_resid_28d_rel[inv]
    return out


# ---------------------------------------------------------------------------
# 4. WORK — Workout jockey intent (`liderform` > `yenibeygir`, APRANTİ -> NaN)
# ---------------------------------------------------------------------------
def _parse_jockey_identity(raw_val):
    """Parse jockey string -> `(is_full_given, given_tokens, surname)` or `None` for unknown/`APRANTİ`."""
    if raw_val is None or pd.isna(raw_val):
        return None
    s = _WS_RE.sub(" ", str(raw_val).strip())
    if not s:
        return None
    s = _JOCKEY_AP_RE.sub("", s).strip()
    if not s:
        return None
    u = s.translate(_TR_UPPER_MAP).upper()
    if u == "AP" or u == "APRANTI" or u.startswith("APRANTI "):
        return None

    if "." in u:
        u_nodot_sp = _DOT_WS_RE.sub(".", u)
        parts = [p for p in u_nodot_sp.split(".") if p]
        if not parts:
            return None
        last_toks = parts[-1].split()
        if len(parts) == 1:
            if len(last_toks) == 1:
                return (True, (), last_toks[0])
            return (True, tuple(last_toks[:-1]), last_toks[-1])
        surname = last_toks[-1]
        given = tuple(parts[:-1] + last_toks[:-1])
        return (False, given, surname)

    toks = u.split()
    if len(toks) == 1:
        return (True, (), toks[0])
    return (True, tuple(toks[:-1]), toks[-1])


def _parsed_jockeys_match(pw, pr):
    """Return True if parsed workout identity `pw` matches race jockey `pr`."""
    if pw is None or pr is None:
        return False
    is_full_w, gw, sw = pw
    is_full_r, gr, sr = pr
    if sw != sr:
        return False
    if len(gw) == 0 or len(gr) == 0:
        return False
    if is_full_w == is_full_r:
        return gw == gr
    if len(gw) != len(gr):
        return False
    full_g, abbr_g = (gw, gr) if is_full_w else (gr, gw)
    return all(fg.startswith(ag) for fg, ag in zip(full_g, abbr_g))


def _dedup_workouts(v5_tables, dedup=True):
    """Load workouts matching `features_v5.py:370-386` (optionally deduplicating `liderform` > `yenibeygir`)."""
    workouts = v5_tables.get("workouts") if isinstance(v5_tables, dict) else v5_tables
    if workouts is None or len(workouts) == 0:
        return pd.DataFrame()
    w = workouts.copy()
    if "source" in w.columns:
        src_s = w["source"].astype("string").str.strip().str.lower()
        if src_s.isin(["liderform", "yenibeygir"]).any() or src_s.notna().any():
            w = w[src_s.isin(["liderform", "yenibeygir"])].copy()
            w["_src_norm"] = w["source"].astype("string").str.strip().str.lower()
        else:
            w["_src_norm"] = "unknown"
    else:
        w["_src_norm"] = "unknown"

    if "horse_key" not in w.columns or "date" not in w.columns:
        return pd.DataFrame()
    w["_hk_s"] = _clean_entity_str(w["horse_key"])
    w["_dt"] = pd.to_datetime(w["date"], errors="coerce")
    w = w[w["_hk_s"].notna() & w["_dt"].notna()].copy()
    if len(w) == 0:
        return pd.DataFrame()

    if dedup and (w["_src_norm"] == "yenibeygir").any():
        w["_src_prio"] = np.where(w["_src_norm"] == "liderform", 0, 1)
        w = (
            w.sort_values(["_hk_s", "_dt", "_src_prio"], kind="mergesort")
            .drop_duplicates(subset=["_hk_s", "_dt"], keep="first")
            .drop(columns=["_src_prio"])
        )
    return w.reset_index(drop=True)


def _build_jockey_match_index(r_series, w_series):
    """Map unique runner & workout jockey strings to int IDs and sorted matching `(r_id, w_id)` int64 keys."""
    r_uniq = r_series.dropna().astype(str).unique().tolist()
    w_uniq = w_series.dropna().astype(str).unique().tolist()

    r_parsed = {s: _parse_jockey_identity(s) for s in r_uniq}
    w_parsed = {s: _parse_jockey_identity(s) for s in w_uniq}

    # Assign unique integer IDs to valid parsed strings (>= 0)
    r_id_map = {}
    by_surname_r = {}
    for s, p in r_parsed.items():
        if p is None:
            continue
        rid = len(r_id_map)
        r_id_map[s] = rid
        by_surname_r.setdefault(p[2], []).append((rid, p))

    w_id_map = {}
    by_surname_w = {}
    for s, p in w_parsed.items():
        if p is None:
            continue
        wid = len(w_id_map)
        w_id_map[s] = wid
        by_surname_w.setdefault(p[2], []).append((wid, p))

    j_stride = max(len(w_id_map) + 10, 100_000)
    pair_keys = []
    for sur, r_list in by_surname_r.items():
        w_list = by_surname_w.get(sur)
        if not w_list:
            continue
        for rid, rp in r_list:
            for wid, wp in w_list:
                if _parsed_jockeys_match(wp, rp):
                    pair_keys.append(rid * j_stride + wid)

    match_keys = np.sort(np.asarray(pair_keys, dtype=np.int64)) if pair_keys else np.zeros(0, dtype=np.int64)
    r_ids = r_series.map(lambda x: r_id_map.get(str(x), -1) if pd.notna(x) else -1).to_numpy(dtype=np.int64)
    w_ids = w_series.map(lambda x: w_id_map.get(str(x), -1) if pd.notna(x) else -1).to_numpy(dtype=np.int64)
    return r_ids, w_ids, match_keys, j_stride


def attach_WORK(df, v5_tables=None):
    """Attach WORK block: workout jockey intent & hard-effort recency strictly `< D`."""
    if len(df) == 0:
        return _empty_result(df, WORK_COLS)

    work = _lite_work_frame(df, ("scratched", "finish", "jockey", "hj_n"))
    n = len(work)
    active = _active_mask(work)
    fin = _to_f64(_col_or_empty(work, "finish", dtype="float64"))
    settled = active & np.isfinite(fin)

    gw_jk_last = np.full(n, np.nan, dtype=np.float64)
    gw_jk_n30 = np.full(n, np.nan, dtype=np.float64)
    gw_hard_days = np.full(n, np.nan, dtype=np.float64)
    gw_jk_first_ride = np.full(n, np.nan, dtype=np.float64)

    w = _dedup_workouts(v5_tables)
    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    min_day = int(day_arr.min())
    max_day = int(day_arr.max())
    if len(w) > 0:
        w["_w_day"] = _to_day_int(w["_dt"])
        min_day = min(min_day, int(w["_w_day"].min()))
        max_day = max(max_day, int(w["_w_day"].max()))

    df_hk = work["_hk_s"]
    w_hk = w["_hk_s"] if len(w) > 0 else pd.Series(dtype="string")
    all_hk = pd.concat([df_hk, w_hk], ignore_index=True)
    all_codes, _ = pd.factorize(all_hk, sort=False)
    df_hk_c = all_codes[:n].astype(np.int64)
    w_hk_c = all_codes[n:].astype(np.int64) if len(w) > 0 else np.zeros(0, dtype=np.int64)

    stride = max(max_day - min_day + 200, 1_000_000)
    df_day_off = (day_arr - min_day).astype(np.int64)

    r_j_col = _col_or_empty(work, "jockey")
    w_j_col = (
        w["jockey"]
        if (len(w) > 0 and "jockey" in w.columns)
        else pd.Series(pd.NA, index=w.index if len(w) > 0 else None, dtype="string")
    )
    r_j_ids, w_j_ids, match_keys, j_stride = _build_jockey_match_index(r_j_col, w_j_col)

    valid_base = (df_hk_c >= 0) & (r_j_ids >= 0)
    gw_jk_n30[valid_base] = 0.0

    # Prior horse × normalized-jockey starts `< D` (use existing `hj_n` if attached, else compute)
    if "hj_n" in work.columns:
        hj_n_arr = _to_f64(work["hj_n"])
    else:
        r_j_norm = _norm_upper_str(_col_or_empty(work, "jockey").str.replace(_JOCKEY_AP_RE, "", regex=True))
        j_norm_c, _ = pd.factorize(r_j_norm, sort=False)
        starts_v = settled.astype(np.float64)
        z_v = np.zeros(n, dtype=np.float64)
        hj_n_arr, _, _, _, _, _ = _prior_keyed_stats(
            df_hk_c, j_norm_c, day_arr, starts_v, z_v, z_v, z_v, z_v, need_sf=False
        )

    if len(w) > 0:
        w_day_off = (w["_w_day"].to_numpy(dtype=np.int64) - min_day).astype(np.int64)
        w_eff = (
            w["effort"].astype("string").str.strip().str.upper()
            if "effort" in w.columns
            else pd.Series(pd.NA, index=w.index, dtype="string")
        )
        w_hard_mask = (w_hk_c >= 0) & w_eff.isin(["ALLOUT", "DRIVING"]).fillna(False).to_numpy(dtype=bool)

        # 1) `gw_hard_days`: last ALLOUT/DRIVING workout strictly `< D`, within 60 days
        if w_hard_mask.any() and (df_hk_c >= 0).any():
            wh_hk = w_hk_c[w_hard_mask]
            wh_d = w_day_off[w_hard_mask]
            wh_keys = wh_hk * stride + wh_d
            h_ord = np.argsort(wh_keys, kind="mergesort")
            wh_keys_s = wh_keys[h_ord]
            wh_hk_s = wh_hk[h_ord]
            wh_d_s = wh_d[h_ord]

            vh = np.flatnonzero(df_hk_c >= 0)
            qh_keys = df_hk_c[vh] * stride + df_day_off[vh]
            pos = np.searchsorted(wh_keys_s, qh_keys, side="left") - 1
            ok_p = (pos >= 0) & (wh_hk_s[np.maximum(pos, 0)] == df_hk_c[vh])
            if ok_p.any():
                r_ok = vh[ok_p]
                gaps = df_day_off[r_ok] - wh_d_s[pos[ok_p]]
                ok_60 = (gaps >= 1) & (gaps <= 60)
                gw_hard_days[r_ok[ok_60]] = gaps[ok_60].astype(np.float64)

        # 2) `gw_jk_last` & `gw_jk_n30`: sorted `(w_hk, w_day_off, orig_w_pos)` on dedup'd workouts
        w_valid = w_hk_c >= 0
        if w_valid.any() and valid_base.any():
            wv_i = np.flatnonzero(w_valid)
            wv_hk = w_hk_c[wv_i]
            wv_d = w_day_off[wv_i]
            wv_j = w_j_ids[wv_i]
            w_keys = wv_hk * stride + wv_d
            w_ord = np.argsort(w_keys, kind="mergesort")
            ws_keys = w_keys[w_ord]
            ws_hk = wv_hk[w_ord]
            ws_d = wv_d[w_ord]
            ws_j = wv_j[w_ord]

            vq = np.flatnonzero(valid_base)
            q_hk = df_hk_c[vq]
            q_d = df_day_off[vq]
            q_rj = r_j_ids[vq]

            hi_w = np.searchsorted(ws_keys, q_hk * stride + q_d, side="left")
            lo_w = np.searchsorted(ws_keys, q_hk * stride + np.maximum(q_d - 30, 0), side="left")
            lo_w = np.minimum(lo_w, hi_w)

            # Most recent workout within `[D-30, D)`
            last_p = hi_w - 1
            has_last30 = (
                (last_p >= lo_w)
                & (last_p >= 0)
                & (ws_hk[np.maximum(last_p, 0)] == q_hk)
                & ((q_d - ws_d[np.maximum(last_p, 0)]) <= 30)
            )
            if has_last30.any():
                l_rows = vq[has_last30]
                lw_j = ws_j[last_p[has_last30]]
                lr_j = q_rj[has_last30]
                known_wj = lw_j >= 0
                if known_wj.any():
                    lk_rows = l_rows[known_wj]
                    pair_k = lr_j[known_wj] * j_stride + lw_j[known_wj]
                    if len(match_keys) > 0:
                        idx_m = np.searchsorted(match_keys, pair_k)
                        hit = (idx_m < len(match_keys)) & (match_keys[np.minimum(idx_m, len(match_keys) - 1)] == pair_k)
                    else:
                        hit = np.zeros(len(lk_rows), dtype=bool)
                    gw_jk_last[lk_rows] = hit.astype(np.float64)

            # Count matching workouts in `[D-30, D)` (all-unknown riders in 30d -> NaN)
            n30_all = hi_w - lo_w
            has_any30 = n30_all > 0
            if has_any30.any():
                a_idx = np.flatnonzero(has_any30)
                n30_known = np.zeros(len(a_idx), dtype=np.int64)
                n30_match = np.zeros(len(a_idx), dtype=np.int64)

                chunk_sz = 100_000
                for cs in range(0, len(a_idx), chunk_sz):
                    ce = min(cs + chunk_sz, len(a_idx))
                    sub_a = a_idx[cs:ce]
                    lens = n30_all[sub_a]
                    tot_e = int(lens.sum())
                    if tot_e == 0:
                        continue
                    loc_q = np.repeat(np.arange(ce - cs, dtype=np.int64), lens)
                    starts = np.repeat(lo_w[sub_a], lens)
                    offs = np.arange(tot_e, dtype=np.int64) - np.repeat(np.cumsum(lens) - lens, lens)
                    w_pos = starts + offs

                    wj_exp = ws_j[w_pos]
                    rj_exp = q_rj[sub_a][loc_q]
                    known_exp = wj_exp >= 0
                    if known_exp.any():
                        n30_known[cs:ce] = np.bincount(loc_q[known_exp], minlength=ce - cs)
                        if len(match_keys) > 0:
                            pk = rj_exp[known_exp] * j_stride + wj_exp[known_exp]
                            im = np.searchsorted(match_keys, pk)
                            mh = (im < len(match_keys)) & (match_keys[np.minimum(im, len(match_keys) - 1)] == pk)
                            n30_match[cs:ce] = np.bincount(
                                loc_q[known_exp], weights=mh.astype(np.int64), minlength=ce - cs
                            )

                q_sub_rows = vq[a_idx]
                gw_jk_n30[q_sub_rows] = np.where(
                    n30_known > 0,
                    n30_match.astype(np.float64),
                    np.nan,
                )

    valid_fr = valid_base & np.isfinite(gw_jk_n30) & np.isfinite(hj_n_arr)
    gw_jk_first_ride[valid_fr] = ((gw_jk_n30[valid_fr] >= 1.0) & (hj_n_arr[valid_fr] == 0.0)).astype(np.float64)

    inv = _inv_order(work)
    out = df.copy()
    out["gw_jk_last"] = gw_jk_last[inv]
    out["gw_jk_n30"] = gw_jk_n30[inv]
    out["gw_hard_days"] = gw_hard_days[inv]
    out["gw_jk_first_ride"] = gw_jk_first_ride[inv]
    return out


# ---------------------------------------------------------------------------
# 5. BIAS — Persistent 3-year track/distance-band/gate-quintile bias (< D)
# ---------------------------------------------------------------------------
def attach_BIAS(df):
    """Attach BIAS block: 3-year rolling gate-quintile win residual vs AGF for (city, surface, dist_band)."""
    if len(df) == 0:
        return _empty_result(df, BIAS_COLS)

    work = _lite_work_frame(
        df,
        ("scratched", "finish", "surface", "distance", "gate", "gate_frac", "field", "agf_share", "agf_close", "agf_pct"),
    )
    n = len(work)
    active = _active_mask(work)
    fin = _to_f64(_col_or_empty(work, "finish", dtype="float64"))
    settled = active & np.isfinite(fin)
    win_v = np.where(settled & (fin == 1.0), 1.0, 0.0)
    agf_s = _compute_agf_share(work, active)
    agf_finite = np.isfinite(agf_s)

    city_c, _ = pd.factorize(_norm_upper_str(_col_or_empty(work, "city")), sort=True)
    surf_c, _ = pd.factorize(_norm_upper_str(_col_or_empty(work, "surface")), sort=True)
    dband = _dist_band_v9(_col_or_empty(work, "distance", dtype="float64"))
    gf = _gate_frac_array(work, active)
    q5 = np.where(np.isfinite(gf), np.clip(np.ceil(gf * 5.0) - 1.0, 0.0, 4.0), -1.0).astype(np.int64)

    cell_valid = (city_c >= 0) & (surf_c >= 0) & (dband >= 0) & (q5 >= 0)
    cell_code = np.where(
        cell_valid,
        ((city_c.astype(np.int64) * 16 + surf_c.astype(np.int64)) * 4 + dband) * 5 + q5,
        -1,
    )

    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    day_off, stride, _ = _day_stride(day_arr)

    bias_n = np.full(n, np.nan, dtype=np.float64)
    bias_gate_resid = np.full(n, np.nan, dtype=np.float64)

    hist_b = cell_valid & settled & agf_finite
    if cell_valid.any():
        qi = np.flatnonzero(cell_valid)
        bias_n[qi] = 0.0
        if hist_b.any():
            ei = np.flatnonzero(hist_b)
            n_c, sum_res = _range_window_agg(
                cell_code[ei],
                day_off[ei],
                [np.ones(len(ei), dtype=np.float64), win_v[ei] - agf_s[ei]],
                cell_code[qi],
                day_off[qi] - BIAS_WINDOW_DAYS,
                day_off[qi],
                stride,
            )
            bias_n[qi] = n_c
            bias_gate_resid[qi] = np.where(n_c >= 1.0, sum_res / (n_c + BIAS_PRIOR_N), np.nan)

    inv = _inv_order(work)
    out = df.copy()
    out["bias_gate_resid"] = bias_gate_resid[inv]
    out["bias_n"] = bias_n[inv]
    return out


# ---------------------------------------------------------------------------
# 6. DAY — Same-day earlier post_time gate bias (DIAGNOSTIC ONLY; never live)
# ---------------------------------------------------------------------------
def _parse_post_min(series):
    out = np.full(len(series), 9999, dtype=np.int64)
    vals = series.tolist()
    for i, v in enumerate(vals):
        if v is None or pd.isna(v):
            continue
        m = _POST_TIME_RE.search(str(v))
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                out[i] = hh * 60 + mm
    return out


def attach_DAY(df):
    """Attach DIAGNOSTIC-ONLY DAY block: same-day earlier post_time winners' gate bias."""
    if len(df) == 0:
        return _empty_result(df, DAY_COLS)

    day_needed = ("race_id", "date", "city", "surface", "race_no", "post_time", "scratched", "finish", "gate", "gate_frac", "field")
    out = df[[c for c in day_needed if c in df.columns]].copy()
    n = len(out)
    active = _active_mask(out)
    fin = _to_f64(_col_or_empty(out, "finish", dtype="float64"))
    gf = _gate_frac_array(out, active)

    out["_v9_day"] = _to_day_int(pd.to_datetime(out["date"]))
    out["_v9_city"] = _norm_upper_str(_col_or_empty(out, "city"))
    out["_v9_surf"] = _norm_upper_str(_col_or_empty(out, "surface"))
    out["_v9_rno"] = pd.to_numeric(_col_or_empty(out, "race_no", dtype="float64"), errors="coerce").fillna(0).astype(np.int64)
    out["_v9_pmin"] = _parse_post_min(_col_or_empty(out, "post_time"))
    out["_v9_rid"] = out["race_id"].astype("string")
    out["_v9_win_gf"] = np.where(active & (fin == 1.0) & np.isfinite(gf), gf, np.nan)

    # Collapse strictly to one row per race_id, ordered deterministically by `(day, city, surf, post_min, race_no, race_id)`
    r_df = (
        out.groupby("_v9_rid", sort=False, as_index=False)
        .agg(
            _day=("_v9_day", "first"),
            _city=("_v9_city", "first"),
            _surf=("_v9_surf", "first"),
            _pmin=("_v9_pmin", "first"),
            _rno=("_v9_rno", "first"),
            _win_gf=("_v9_win_gf", "mean"),
        )
        .sort_values(["_day", "_city", "_surf", "_pmin", "_rno", "_v9_rid"], kind="mergesort", na_position="last")
        .reset_index(drop=True)
    )

    valid_group = r_df["_city"].notna() & r_df["_surf"].notna()
    has_win = valid_group.to_numpy(dtype=bool) & np.isfinite(r_df["_win_gf"].to_numpy(dtype=np.float64))
    r_df["_hw"] = has_win.astype(np.float64)
    r_df["_wdiff"] = np.where(has_win, r_df["_win_gf"].to_numpy(dtype=np.float64) - 0.5, 0.0)

    g = r_df.groupby(["_day", "_city", "_surf"], sort=False, dropna=False)
    cum_n = g["_hw"].cumsum().to_numpy(dtype=np.float64) - r_df["_hw"].to_numpy(dtype=np.float64)
    cum_diff = g["_wdiff"].cumsum().to_numpy(dtype=np.float64) - r_df["_wdiff"].to_numpy(dtype=np.float64)

    vg = valid_group.to_numpy(dtype=bool)
    r_df["_day_bias_n"] = np.where(vg, cum_n, np.nan)
    r_df["_day_gate_bias"] = np.where(
        vg & (cum_n >= 1.0),
        cum_diff / (cum_n + DAY_PRIOR_N),
        np.nan,
    )

    n_map = dict(zip(r_df["_v9_rid"], r_df["_day_bias_n"]))
    b_map = dict(zip(r_df["_v9_rid"], r_df["_day_gate_bias"]))

    day_bias_n = out["_v9_rid"].map(n_map).to_numpy(dtype=np.float64)
    day_gate_bias = out["_v9_rid"].map(b_map).to_numpy(dtype=np.float64)
    day_gate_bias_x_gf = np.where(
        np.isfinite(day_gate_bias) & np.isfinite(gf),
        day_gate_bias * gf,
        np.nan,
    )

    res = df.copy()
    res["day_bias_n"] = day_bias_n
    res["day_gate_bias"] = day_gate_bias
    res["day_gate_bias_x_gf"] = day_gate_bias_x_gf
    return res


def attach_v9(df, blocks=V9_CANDIDATE_BLOCKS, v5_tables=None):
    """Attach requested leak-free v9 feature blocks onto v8 DataFrame."""
    out = df.copy()
    for blk in blocks or ():
        if blk == "KEY":
            out = attach_KEY(out)
        elif blk == "SHIP":
            out = attach_SHIP(out)
        elif blk == "STAB":
            out = attach_STAB(out)
        elif blk == "WORK":
            out = attach_WORK(out, v5_tables=v5_tables)
        elif blk == "BIAS":
            out = attach_BIAS(out)
        elif blk == "DAY":
            out = attach_DAY(out)
        else:
            raise ValueError(f"Unknown v9 block: {blk!r}. Expected subset of {tuple(V9_BLOCK_COLS)}.")
    return out


def get_v9_cols(v9_blocks=(), with_program=False):
    """Return V8 base feature columns (122) extended with requested `V9_BLOCK_COLS`."""
    cols = list(get_v8_cols(v8_blocks=tuple(V8_CONFIG["v8_blocks"]), with_program=with_program))
    for blk in v9_blocks or ():
        if blk not in V9_BLOCK_COLS:
            raise ValueError(f"Unknown v9 block: {blk!r}. Expected one of {list(V9_BLOCK_COLS)}.")
        cols.extend(V9_BLOCK_COLS[blk])
    return list(dict.fromkeys(cols))


def compute_work_jockey_stats_by_source_year(df_hist, v5_tables):
    """Compute workout source × year jockey missing/match rates independently per source over 2017+ eval rows."""
    w = _dedup_workouts(v5_tables, dedup=False)
    if len(df_hist) == 0 or len(w) == 0:
        return [], []

    w["_yr"] = pd.to_datetime(w["_dt"]).dt.year.astype(np.int32)
    w_j_col = w["jockey"] if "jockey" in w.columns else pd.Series(pd.NA, index=w.index, dtype="string")
    w_parsed = w_j_col.map(_parse_jockey_identity)
    w["_j_known"] = w_parsed.notna()
    w["_j_aprant"] = (
        w_j_col.astype("string").str.strip().str.translate(_TR_UPPER_MAP).str.upper().str.startswith("APRANTI").fillna(False)
    )

    src_year_rows = []
    for (src, yr), grp in w[w["_yr"] >= 2017].groupby(["_src_norm", "_yr"], sort=True):
        n_tot = len(grp)
        n_null = int(w_j_col.loc[grp.index].isna().sum() + (w_j_col.loc[grp.index].astype("string").str.strip() == "").sum())
        n_apr = int(grp["_j_aprant"].sum())
        n_known = int(grp["_j_known"].sum())
        src_year_rows.append({
            "source": str(src),
            "year": int(yr),
            "rows": int(n_tot),
            "missing_pct": float(n_null / n_tot) if n_tot else 0.0,
            "apranti_pct": float(n_apr / n_tot) if n_tot else 0.0,
            "known_pct": float(n_known / n_tot) if n_tot else 0.0,
        })

    eval_mask = df_hist["_is_eval"].to_numpy(dtype=bool) if "_is_eval" in df_hist.columns else np.ones(len(df_hist), dtype=bool)
    sub = df_hist.loc[eval_mask, ["date", "horse_key", "jockey"]].copy()
    sub = sub[pd.to_datetime(sub["date"]).dt.year >= 2017].reset_index(drop=True)
    if len(sub) == 0:
        return src_year_rows, []

    w["_w_day"] = _to_day_int(w["_dt"])
    sub_day = _to_day_int(pd.to_datetime(sub["date"]))
    sub_yr = pd.to_datetime(sub["date"]).dt.year.to_numpy(dtype=np.int32)
    df_hk = _clean_entity_str(sub["horse_key"])
    r_j_ids, w_j_ids, match_keys, j_stride = _build_jockey_match_index(_col_or_empty(sub, "jockey"), w_j_col)

    runner_rows = []
    for src_name, w_src_grp in w.groupby("_src_norm", sort=True):
        w_idx_s = w_src_grp.index.to_numpy(dtype=np.int64)
        w_days_s = w_src_grp["_w_day"].to_numpy(dtype=np.int64)
        all_hk = pd.concat([df_hk, w_src_grp["_hk_s"]], ignore_index=True)
        codes, _ = pd.factorize(all_hk, sort=False)
        df_hk_c = codes[: len(sub)].astype(np.int64)
        w_hk_c = codes[len(sub) :].astype(np.int64)

        min_d = min(int(sub_day.min()), int(w_days_s.min()))
        max_d = max(int(sub_day.max()), int(w_days_s.max()))
        stride = max(max_d - min_d + 200, 1_000_000)

        w_d_off = (w_days_s - min_d).astype(np.int64)
        w_keys = w_hk_c * stride + w_d_off
        w_ord = np.argsort(w_keys, kind="mergesort")
        ws_keys = w_keys[w_ord]
        ws_hk = w_hk_c[w_ord]
        ws_d = w_d_off[w_ord]
        ws_j = w_j_ids[w_idx_s][w_ord]

        vr_idx = np.flatnonzero(df_hk_c >= 0)
        qd = (sub_day[vr_idx] - min_d).astype(np.int64)
        pos = np.searchsorted(ws_keys, df_hk_c[vr_idx] * stride + qd, side="left") - 1
        has30 = (pos >= 0) & (ws_hk[np.maximum(pos, 0)] == df_hk_c[vr_idx]) & ((qd - ws_d[np.maximum(pos, 0)]) <= 30)
        if not has30.any():
            continue

        r_sel = vr_idx[has30]
        p_sel = pos[has30]
        yr_sel = sub_yr[r_sel]
        rj_sel = r_j_ids[r_sel]
        wj_sel = ws_j[p_sel]
        known_both = (rj_sel >= 0) & (wj_sel >= 0)
        matched = np.zeros(len(r_sel), dtype=bool)
        if known_both.any() and len(match_keys) > 0:
            pk = rj_sel[known_both] * j_stride + wj_sel[known_both]
            im = np.searchsorted(match_keys, pk)
            matched[known_both] = (im < len(match_keys)) & (match_keys[np.minimum(im, len(match_keys) - 1)] == pk)

        df_m = pd.DataFrame({"year": yr_sel, "known": known_both.astype(float), "matched": matched.astype(float)})
        for yr, grp in df_m.groupby("year", sort=True):
            n_g = len(grp)
            n_k = int(grp["known"].sum())
            runner_rows.append({
                "source": str(src_name),
                "year": int(yr),
                "runners_30d": int(n_g),
                "known_jockey_pct": float(n_k / n_g) if n_g else 0.0,
                "match_all_pct": float(grp["matched"].mean()) if n_g else 0.0,
                "match_known_pct": float(grp["matched"].sum() / n_k) if n_k else 0.0,
            })

    runner_rows.sort(key=lambda r: (r["source"], r["year"]))
    return src_year_rows, runner_rows


__all__ = [
    "BIAS_COLS",
    "DAY_COLS",
    "KEY_COLS",
    "SHIP_COLS",
    "SMOOTHING_CONSTANTS",
    "STAB_COLS",
    "V9_BLOCK_COLS",
    "V9_CANDIDATE_BLOCKS",
    "WORK_COLS",
    "attach_BIAS",
    "attach_DAY",
    "attach_KEY",
    "attach_SHIP",
    "attach_STAB",
    "attach_WORK",
    "attach_v9",
    "compute_work_jockey_stats_by_source_year",
    "get_v9_cols",
]
