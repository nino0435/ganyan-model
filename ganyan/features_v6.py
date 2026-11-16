"""Leak-free v6 pre-race feature blocks and yearly source coverage counters."""
import os
from pathlib import Path
import re
import sqlite3
import numpy as np
import pandas as pd

from ganyan.features_v5 import _clean_entity_str, _sorted_work_frame, _to_day_int

X_GC_COLS = [
    "gc_rate",
    "gc_boy_last",
    "gc_boy_m5",
    "gc_sprint_risk",
]

X_FARK_COLS = [
    "h_margin_last",
    "h_margin_m3",
    "h_close_loss_m3",
    "h_margin_rel",
]

X_S800_COLS = [
    "h_s800_last",
    "h_s800_m3",
    "h_pace_rat_last",
    "h_s800_rel",
]

X_PRIZE_COLS = [
    "h_prize_last",
    "h_prize_m3",
    "h_prize_best5",
    "h_prize_rel",
    "h_prize_rk",
]

X_POOL_COLS = [
    "city_pool_rel_90d",
    "city_ganyan_share_90d",
    "h_origin_pool_m3",
    "h_shipper_delta",
]

X_STEW_COLS = [
    "stew_prior_cnt",
    "stew_prior_rate",
    "stew_days_last",
    "stew_last_race_flag",
]

V6_BLOCK_COLS = {
    "X_GC": list(X_GC_COLS),
    "X_FARK": list(X_FARK_COLS),
    "X_S800": list(X_S800_COLS),
    "X_PRIZE": list(X_PRIZE_COLS),
    "X_POOL": list(X_POOL_COLS),
    "X_STEW": list(X_STEW_COLS),
}

_LEAD_FLOAT_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_METRE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:metre|mt\b|m\b)", re.IGNORECASE)
_MULTI_LEG_GANYAN_RE = re.compile(r"[34567]\s*['’]?\s*l[ıiuü]", re.IGNORECASE)


def _to_f64(x):
    """Convert any Series/ExtensionArray/ndarray (including nullable Float64/string) to float64 ndarray."""
    s = pd.to_numeric(x, errors="coerce")
    if isinstance(s, pd.Series):
        return s.to_numpy(dtype=np.float64, na_value=np.nan)
    if hasattr(s, "to_numpy"):
        try:
            return s.to_numpy(dtype=np.float64, na_value=np.nan)
        except TypeError:
            return s.to_numpy(dtype=np.float64)
    return np.asarray(s, dtype=np.float64)


def _empty_runner_extra_df():
    return pd.DataFrame(
        {
            "race_id": pd.Series(dtype="string"),
            "horse_key": pd.Series(dtype="string"),
            "fark": pd.Series(dtype="string"),
            "gec_cikis": pd.Series(dtype="string"),
        }
    )


def _empty_race_extra_df():
    return pd.DataFrame(
        {
            "race_id": pd.Series(dtype="string"),
            "son800_s": pd.Series(dtype="float64"),
            "prize_1": pd.Series(dtype="float64"),
        }
    )


def _empty_pools_df():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(pd.Series(dtype="object")),
            "city": pd.Series(dtype="string"),
            "bet": pd.Series(dtype="string"),
            "amount": pd.Series(dtype="float64"),
        }
    )


def _empty_steward_df():
    return pd.DataFrame(
        {
            "race_id": pd.Series(dtype="string"),
            "horse_name": pd.Series(dtype="string"),
            "horse_key": pd.Series(dtype="string"),
        }
    )


def load_v6_tables(conn):
    """Load runner_extra, race_extra, pools, and steward_notes read-only from SQLite.

    Accepts an open ``sqlite3.Connection`` or DB file path. Missing or empty tables
    return empty typed DataFrames without raising.
    """
    if conn is None:
        return {
            "runner_extra": _empty_runner_extra_df(),
            "race_extra": _empty_race_extra_df(),
            "pools": _empty_pools_df(),
            "steward_notes": _empty_steward_df(),
        }

    own_conn = False
    if isinstance(conn, (str, os.PathLike)):
        p = Path(conn)
        if not p.exists():
            return load_v6_tables(None)
        db_uri = f"{p.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=60)
        own_conn = True

    try:
        try:
            conn.execute("PRAGMA busy_timeout=60000")
        except sqlite3.Error:
            pass

        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

        if "runner_extra" in tables:
            re_df = pd.read_sql_query(
                """
                SELECT race_id, horse_key, fark, gec_cikis
                FROM runner_extra
                WHERE race_id IS NOT NULL AND horse_key IS NOT NULL AND horse_key != ''
                """,
                conn,
            )
            if re_df.empty:
                re_df = _empty_runner_extra_df()
        else:
            re_df = _empty_runner_extra_df()

        if "race_extra" in tables:
            rce_df = pd.read_sql_query(
                """
                SELECT race_id, son800_s, prize_1
                FROM race_extra
                WHERE race_id IS NOT NULL
                """,
                conn,
            )
            if rce_df.empty:
                rce_df = _empty_race_extra_df()
            else:
                rce_df["son800_s"] = _to_f64(rce_df["son800_s"])
                rce_df["prize_1"] = _to_f64(rce_df["prize_1"])
        else:
            rce_df = _empty_race_extra_df()

        if "pools" in tables:
            pools_df = pd.read_sql_query(
                """
                SELECT date, city, bet, amount
                FROM pools
                WHERE date IS NOT NULL AND amount IS NOT NULL
                """,
                conn,
            )
            if pools_df.empty:
                pools_df = _empty_pools_df()
            else:
                pools_df["date"] = pd.to_datetime(pools_df["date"], errors="coerce")
                pools_df["amount"] = _to_f64(pools_df["amount"])
                pools_df = pools_df[
                    pools_df["date"].notna() & np.isfinite(pools_df["amount"]) & (pools_df["amount"] > 0.0)
                ].reset_index(drop=True)
        else:
            pools_df = _empty_pools_df()

        if "steward_notes" in tables:
            stew_df = pd.read_sql_query(
                """
                SELECT race_id, horse_name, horse_key
                FROM steward_notes
                WHERE race_id IS NOT NULL
                """,
                conn,
            )
            if stew_df.empty:
                stew_df = _empty_steward_df()
        else:
            stew_df = _empty_steward_df()

        return {
            "runner_extra": re_df,
            "race_extra": rce_df,
            "pools": pools_df,
            "steward_notes": stew_df,
        }
    finally:
        if own_conn:
            conn.close()


def parse_fark_to_boy(raw):
    """Parse TJK finish margin text ('1,5 Boy', 'Boyun', 'Baş', 'Burun', 'Yarım Boy', 'Uzak') to lengths."""
    if raw is None or pd.isna(raw):
        return np.nan
    s = str(raw).strip()
    if not s or s in ("-", "--", "---", "—", "–"):
        return np.nan
    low = s.replace("İ", "i").replace("I", "ı").lower()
    if "at baş" in low or "atbaş" in low:
        return 0.0
    if "burun" in low:
        return 0.05
    if "baş" in low or "bas" in low:
        return 0.15
    if "boyun" in low:
        return 0.30
    if "yarım" in low or "yarim" in low:
        return 0.50
    if "uzak" in low:
        return 10.0
    mm = _METRE_RE.search(low)
    if mm:
        val_m = float(mm.group(1).replace(",", "."))
        return float(np.clip(val_m / 3.0, 0.0, 20.0))
    nm = _LEAD_FLOAT_RE.search(low)
    if nm:
        val = float(nm.group(1).replace(",", "."))
        return float(np.clip(val, 0.0, 20.0))
    return np.nan


def parse_gec_cikis_to_boy(raw):
    """Parse TJK late-start text ('2 Boy', '100 Metre', 'Startta Kaldı') to lengths lost (>= 0)."""
    if raw is None or pd.isna(raw):
        return 0.0
    s = str(raw).strip()
    if not s or s in ("-", "--", "---", "—", "–"):
        return 0.0
    low = s.replace("İ", "i").replace("I", "ı").lower()
    if "kal" in low or "çıkmad" in low or "cikmad" in low or "derecesiz" in low:
        return 20.0
    if "burun" in low:
        return 0.05
    if "baş" in low or "bas" in low:
        return 0.15
    if "boyun" in low:
        return 0.30
    if "yarım" in low or "yarim" in low:
        return 0.50
    if "uzak" in low:
        return 12.0
    mm = _METRE_RE.search(low)
    if mm:
        val_m = float(mm.group(1).replace(",", "."))
        return float(np.clip(val_m / 3.0, 0.0, 25.0))
    nm = _LEAD_FLOAT_RE.search(low)
    if nm:
        val = float(nm.group(1).replace(",", "."))
        return float(np.clip(val, 0.0, 25.0))
    if any(tok in low for tok in ("boy", "start", "geç", "gec")):
        return 2.0
    return 0.0


def _map_unique_str(series, fn, na_val=np.nan):
    """Apply string parser `fn` only to unique non-null values for O(U) speed on 1M+ rows."""
    s = series.astype("string")
    non_na = s.dropna().unique()
    if len(non_na) == 0:
        return np.full(len(s), na_val, dtype=np.float64)
    mapping = {str(val): float(fn(str(val))) for val in non_na}
    mapped = s.map(mapping)
    out = _to_f64(mapped).copy()
    if not np.isnan(na_val):
        na_mask = s.isna().to_numpy(dtype=bool, na_value=True)
        out[na_mask] = float(na_val)
    return out


def _horse_prior_obs_stats(
    df_hk_clean,
    df_day_int,
    obs_hk_clean,
    obs_day_int,
    obs_val,
    window_k=3,
    compute_best5=False,
    return_days_since=False,
):
    """Compute strictly prior (`obs_day < df_day`) per-horse stats via `numpy.searchsorted(..., side='left')`.

    Observations on the same `(horse_key, day)` are averaged first so `obs_day` is strictly
    increasing per horse, guaranteeing zero same-day or future leakage.
    """
    n = len(df_day_int)
    last_out = np.full(n, np.nan, dtype=np.float64)
    mean_out = np.full(n, np.nan, dtype=np.float64)
    best5_out = np.full(n, np.nan, dtype=np.float64) if compute_best5 else None
    cnt_out = np.zeros(n, dtype=np.float64)
    days_out = np.full(n, np.nan, dtype=np.float64) if return_days_since else None

    if n == 0 or len(obs_day_int) == 0:
        if return_days_since:
            return last_out, mean_out, best5_out, cnt_out, days_out
        return last_out, mean_out, best5_out, cnt_out

    obs_frame = pd.DataFrame(
        {
            "_hk": obs_hk_clean,
            "_day": np.asarray(obs_day_int, dtype=np.int64),
            "_val": np.asarray(obs_val, dtype=np.float64),
        }
    )
    obs_frame = obs_frame[obs_frame["_hk"].notna() & np.isfinite(obs_frame["_val"])]
    if len(obs_frame) == 0:
        if return_days_since:
            return last_out, mean_out, best5_out, cnt_out, days_out
        return last_out, mean_out, best5_out, cnt_out

    daily = (
        obs_frame.groupby(["_hk", "_day"], sort=False)["_val"]
        .mean()
        .reset_index()
        .sort_values(["_hk", "_day"], kind="mergesort")
        .reset_index(drop=True)
    )

    w_hk_code, hk_uniques = pd.factorize(daily["_hk"], sort=False)
    w_bounds = np.r_[0, np.flatnonzero(w_hk_code[1:] != w_hk_code[:-1]) + 1, len(daily)]
    w_day = daily["_day"].to_numpy(dtype=np.int64)
    w_val = daily["_val"].to_numpy(dtype=np.float64)

    df_code = hk_uniques.get_indexer(df_hk_clean)
    matched = np.flatnonzero(df_code >= 0)
    if len(matched) == 0:
        if return_days_since:
            return last_out, mean_out, best5_out, cnt_out, days_out
        return last_out, mean_out, best5_out, cnt_out

    m_codes = df_code[matched]
    m_order = np.argsort(m_codes, kind="mergesort")
    rows_sorted = matched[m_order]
    codes_sorted = m_codes[m_order]

    grp_splits = np.r_[0, np.flatnonzero(codes_sorted[1:] != codes_sorted[:-1]) + 1, len(codes_sorted)]
    for gi in range(len(grp_splits) - 1):
        gs = grp_splits[gi]
        ge = grp_splits[gi + 1]
        c = codes_sorted[gs]
        r_idx = rows_sorted[gs:ge]
        r_days = df_day_int[r_idx]

        ws = w_bounds[c]
        we = w_bounds[c + 1]
        wd = w_day[ws:we]
        wv = w_val[ws:we]

        hi = np.searchsorted(wd, r_days, side="left")
        cnt_out[r_idx] = hi.astype(np.float64)

        has_p = hi > 0
        if has_p.any():
            rp = r_idx[has_p]
            hip = hi[has_p]
            max_hi = int(hip.max())
            # Per-horse local prefix sum starting at 0.0 prevents cross-horse float carry from >= D rows
            cs_local = np.empty(max_hi + 1, dtype=np.float64)
            cs_local[0] = 0.0
            np.cumsum(wv[:max_hi], out=cs_local[1:])

            last_idx = hip - 1
            last_out[rp] = wv[last_idx]
            lo_k = np.maximum(0, hip - int(window_k))
            denom = (hip - lo_k).astype(np.float64)
            mean_out[rp] = (cs_local[hip] - cs_local[lo_k]) / denom

            if compute_best5:
                i2 = np.maximum(0, hip - 2)
                i3 = np.maximum(0, hip - 3)
                i4 = np.maximum(0, hip - 4)
                i5 = np.maximum(0, hip - 5)
                best5_out[rp] = np.maximum.reduce(
                    [wv[last_idx], wv[i2], wv[i3], wv[i4], wv[i5]]
                )

            if return_days_since:
                days_out[rp] = (r_days[has_p] - wd[last_idx]).astype(np.float64)

    if return_days_since:
        return last_out, mean_out, best5_out, cnt_out, days_out
    return last_out, mean_out, best5_out, cnt_out


def _prior_group_window_mean(target_grp, target_day, src_grp, src_day, src_val, window_days=365):
    """Compute trailing `[target_day - window_days, target_day)` mean of `src_val` per group (`< target_day`)."""
    n = len(target_day)
    mean_out = np.full(n, np.nan, dtype=np.float64)
    cnt_out = np.zeros(n, dtype=np.float64)
    if n == 0 or len(src_day) == 0:
        return mean_out, cnt_out

    s_df = pd.DataFrame(
        {
            "_g": src_grp,
            "_d": np.asarray(src_day, dtype=np.int64),
            "_v": np.asarray(src_val, dtype=np.float64),
        }
    )
    s_df = s_df[s_df["_g"].notna() & np.isfinite(s_df["_v"])]
    if len(s_df) == 0:
        return mean_out, cnt_out

    daily = (
        s_df.groupby(["_g", "_d"], sort=False)["_v"]
        .agg(["sum", "count"])
        .reset_index()
        .sort_values(["_g", "_d"], kind="mergesort")
        .reset_index(drop=True)
    )

    g_code, g_uniques = pd.factorize(daily["_g"], sort=False)
    bounds = np.r_[0, np.flatnonzero(g_code[1:] != g_code[:-1]) + 1, len(daily)]
    d_arr = daily["_d"].to_numpy(dtype=np.int64)
    s_arr = daily["sum"].to_numpy(dtype=np.float64)
    c_arr = daily["count"].to_numpy(dtype=np.float64)

    t_code = g_uniques.get_indexer(target_grp)
    matched = np.flatnonzero(t_code >= 0)
    if len(matched) == 0:
        return mean_out, cnt_out

    m_codes = t_code[matched]
    m_order = np.argsort(m_codes, kind="mergesort")
    rows_sorted = matched[m_order]
    codes_sorted = m_codes[m_order]

    grp_splits = np.r_[0, np.flatnonzero(codes_sorted[1:] != codes_sorted[:-1]) + 1, len(codes_sorted)]
    for gi in range(len(grp_splits) - 1):
        gs = grp_splits[gi]
        ge = grp_splits[gi + 1]
        c = codes_sorted[gs]
        r_idx = rows_sorted[gs:ge]
        r_days = target_day[r_idx]

        ws = bounds[c]
        we = bounds[c + 1]
        wd = d_arr[ws:we]

        hi = np.searchsorted(wd, r_days, side="left")
        if window_days is not None:
            lo = np.minimum(np.searchsorted(wd, r_days - int(window_days), side="left"), hi)
        else:
            lo = np.zeros_like(hi)

        max_hi = int(hi.max()) if len(hi) > 0 else 0
        if max_hi == 0:
            continue

        # Per-group local prefix sums starting at 0.0 prevent cross-group float carry from >= D rows
        cs_s_local = np.empty(max_hi + 1, dtype=np.float64)
        cs_s_local[0] = 0.0
        np.cumsum(s_arr[ws : ws + max_hi], out=cs_s_local[1:])

        cs_c_local = np.empty(max_hi + 1, dtype=np.float64)
        cs_c_local[0] = 0.0
        np.cumsum(c_arr[ws : ws + max_hi], out=cs_c_local[1:])

        tot_c = cs_c_local[hi] - cs_c_local[lo]
        tot_s = cs_s_local[hi] - cs_s_local[lo]
        cnt_out[r_idx] = tot_c
        ok = tot_c > 0
        if ok.any():
            mean_out[r_idx[ok]] = tot_s[ok] / tot_c[ok]

    return mean_out, cnt_out


def _active_mask_from_frame(df):
    if "scratched" not in df.columns:
        return np.ones(len(df), dtype=bool)
    scr = _to_f64(df["scratched"])
    return np.isnan(scr) | (scr == 0.0)


def _race_rel_and_rank(work, vals_arr, compute_rk=False, ascending=False):
    """Compute order-invariant within-race `val - race_mean` (and optional pct rank) over active runners."""
    n = len(work)
    rel_out = np.full(n, np.nan, dtype=np.float64)
    rk_out = np.full(n, np.nan, dtype=np.float64) if compute_rk else None
    if n == 0:
        return rel_out, rk_out

    act = _active_mask_from_frame(work)
    act_idx = np.flatnonzero(act)
    if len(act_idx) == 0:
        return rel_out, rk_out

    s_val = pd.Series(vals_arr[act_idx], index=act_idx, dtype="float64")
    r_key = work["race_id"].iloc[act_idx].astype("string")
    rm = s_val.groupby(r_key, sort=False).transform("mean").to_numpy(dtype=np.float64, na_value=np.nan)
    rel_out[act_idx] = vals_arr[act_idx] - rm

    if compute_rk:
        s_rk = s_val.round(12)
        rk = (
            s_rk.groupby(r_key, sort=False)
            .rank(ascending=ascending, pct=True)
            .to_numpy(dtype=np.float64, na_value=np.nan)
        )
        rk_out[act_idx] = rk

    return rel_out, rk_out


def attach_X_GC(df, runner_extra=None):
    """Attach Block X_GC: leak-free prior late-break (`runner_extra.gec_cikis`) features (`< D`)."""
    if isinstance(runner_extra, dict):
        runner_extra = runner_extra.get("runner_extra")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in X_GC_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    w_hk = work["_hk_s"]
    w_day = work["_day_int"].to_numpy(dtype=np.int64)
    w_rid = _clean_entity_str(work["race_id"])
    dist_arr = _to_f64(work["distance"]) if "distance" in work.columns else np.full(n, 1400.0, dtype=np.float64)

    gc_rate = np.full(n, np.nan, dtype=np.float64)
    gc_last = np.full(n, np.nan, dtype=np.float64)
    gc_m5 = np.full(n, np.nan, dtype=np.float64)

    if runner_extra is not None and len(runner_extra) > 0 and "gec_cikis" in runner_extra.columns:
        re_sub = runner_extra[["race_id", "horse_key", "gec_cikis"]].copy()
        re_sub["_rid"] = _clean_entity_str(re_sub["race_id"])
        re_sub["_hk"] = _clean_entity_str(re_sub["horse_key"])
        re_sub = re_sub.dropna(subset=["_rid", "_hk"]).drop_duplicates(subset=["_rid", "_hk"], keep="last")

        if len(re_sub) > 0:
            rid_days = pd.DataFrame({"_rid": w_rid, "_day": w_day}).dropna(subset=["_rid"]).drop_duplicates("_rid")
            re_joined = (
                re_sub.merge(rid_days, on="_rid", how="inner")
                .sort_values(["_hk", "_day", "_rid"], kind="mergesort")
                .reset_index(drop=True)
            )
            if len(re_joined) > 0:
                gc_boy_vals = _map_unique_str(re_joined["gec_cikis"], parse_gec_cikis_to_boy, na_val=0.0)
                gc_flag_vals = (gc_boy_vals > 0.0).astype(np.float64)

                gc_last, gc_m5, _, n_re_prior = _horse_prior_obs_stats(
                    w_hk,
                    w_day,
                    re_joined["_hk"],
                    re_joined["_day"].to_numpy(dtype=np.int64),
                    gc_boy_vals,
                    window_k=5,
                )
                _, flag_mean_all, _, _ = _horse_prior_obs_stats(
                    w_hk,
                    w_day,
                    re_joined["_hk"],
                    re_joined["_day"].to_numpy(dtype=np.int64),
                    gc_flag_vals,
                    window_k=100000,
                )
                has_re = n_re_prior > 0
                prior_gc_cnt = np.where(has_re, flag_mean_all * n_re_prior, 0.0)
                gc_rate = np.where(has_re, (prior_gc_cnt + 0.15 * 3.0) / (n_re_prior + 3.0), np.nan)

    dist_safe = np.where(np.isfinite(dist_arr) & (dist_arr > 0.0), dist_arr, 1400.0)
    gc_sprint_risk = gc_m5 * (1400.0 / dist_safe)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["gc_rate"] = gc_rate[inv]
    out["gc_boy_last"] = gc_last[inv]
    out["gc_boy_m5"] = gc_m5[inv]
    out["gc_sprint_risk"] = gc_sprint_risk[inv]
    return out


def attach_X_FARK(df, runner_extra=None):
    """Attach Block X_FARK: leak-free prior finish-margin dominance & narrow-loss features (`< D`)."""
    if isinstance(runner_extra, dict):
        runner_extra = runner_extra.get("runner_extra")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in X_FARK_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    w_hk = work["_hk_s"]
    w_day = work["_day_int"].to_numpy(dtype=np.int64)
    w_rid = _clean_entity_str(work["race_id"])

    h_margin_last = np.full(n, np.nan, dtype=np.float64)
    h_margin_m3 = np.full(n, np.nan, dtype=np.float64)
    h_close_loss_m3 = np.full(n, np.nan, dtype=np.float64)
    h_margin_rel = np.full(n, np.nan, dtype=np.float64)

    if runner_extra is not None and len(runner_extra) > 0 and "fark" in runner_extra.columns:
        re_f = runner_extra[["race_id", "horse_key", "fark"]].copy()
        re_f["_rid"] = _clean_entity_str(re_f["race_id"])
        re_f["_hk"] = _clean_entity_str(re_f["horse_key"])
        re_f = re_f.dropna(subset=["_rid", "_hk"]).drop_duplicates(subset=["_rid", "_hk"], keep="last")

        if len(re_f) > 0:
            re_f["_f_boy"] = _map_unique_str(re_f["fark"], parse_fark_to_boy, na_val=np.nan)
            fin_arr = _to_f64(work["finish"]) if "finish" in work.columns else np.full(n, np.nan, dtype=np.float64)
            w_f = (
                pd.DataFrame(
                    {
                        "_rid": w_rid,
                        "_hk": w_hk,
                        "_day": w_day,
                        "_fin": fin_arr,
                    }
                )
                .merge(re_f[["_rid", "_hk", "_f_boy"]], on=["_rid", "_hk"], how="inner")
                .sort_values(["_day", "_rid", "_hk"], kind="mergesort")
                .reset_index(drop=True)
            )

            if len(w_f) > 0:
                top5 = w_f[w_f["_fin"].isin([1.0, 2.0, 3.0, 4.0, 5.0]) & np.isfinite(w_f["_f_boy"])].copy()
                if len(top5) > 0:
                    top5["_fin_i"] = top5["_fin"].astype(np.int32)
                    piv = (
                        top5.drop_duplicates(subset=["_rid", "_fin_i"])
                        .pivot(index="_rid", columns="_fin_i", values="_f_boy")
                    )
                    for col_i in (1, 2, 3, 4, 5):
                        if col_i not in piv.columns:
                            piv[col_i] = np.nan
                    piv = piv[[1, 2, 3, 4, 5]].rename(
                        columns={1: "_f1", 2: "_f2", 3: "_f3", 4: "_f4", 5: "_f5"}
                    ).reset_index()
                    w_f = w_f.merge(piv, on="_rid", how="left")

                    fin_v = w_f["_fin"].to_numpy(dtype=np.float64)
                    f1 = w_f["_f1"].to_numpy(dtype=np.float64)
                    f2 = w_f["_f2"].to_numpy(dtype=np.float64)
                    f3 = w_f["_f3"].to_numpy(dtype=np.float64)
                    f4 = w_f["_f4"].to_numpy(dtype=np.float64)
                    f5 = w_f["_f5"].to_numpy(dtype=np.float64)

                    # Support both TJK HTML table layouts: gap on ahead horse (1..4) or beaten horse (2..5)
                    ahead_mode = np.isfinite(f1)
                    g12 = np.where(ahead_mode, f1, f2)
                    g23 = np.where(ahead_mode, f2, f3)
                    g34 = np.where(ahead_mode, f3, f4)
                    g45 = np.where(ahead_mode, f4, f5)

                    margin = np.full(len(w_f), np.nan, dtype=np.float64)
                    m1 = (fin_v == 1.0) & np.isfinite(g12)
                    m2 = (fin_v == 2.0) & np.isfinite(g12)
                    m3 = (fin_v == 3.0) & np.isfinite(g12) & np.isfinite(g23)
                    m4 = (fin_v == 4.0) & np.isfinite(g12) & np.isfinite(g23) & np.isfinite(g34)
                    m5 = (fin_v == 5.0) & np.isfinite(g12) & np.isfinite(g23) & np.isfinite(g34) & np.isfinite(g45)

                    # Signed margin: negative = winning dominance (better), positive = lengths beaten
                    margin[m1] = -g12[m1]
                    margin[m2] = g12[m2]
                    margin[m3] = g12[m3] + g23[m3]
                    margin[m4] = g12[m4] + g23[m4] + g34[m4]
                    margin[m5] = g12[m5] + g23[m5] + g34[m5] + g45[m5]

                    valid_fin = np.isfinite(fin_v) & (fin_v >= 1.0) & np.isfinite(g12)
                    close_loss = np.where(
                        valid_fin,
                        ((fin_v >= 2.0) & (fin_v <= 4.0) & np.isfinite(margin) & (margin <= 1.0)).astype(np.float64),
                        np.nan,
                    )

                    h_margin_last, h_margin_m3, _, _ = _horse_prior_obs_stats(
                        w_hk,
                        w_day,
                        w_f["_hk"],
                        w_f["_day"].to_numpy(dtype=np.int64),
                        margin,
                        window_k=3,
                    )
                    _, h_close_loss_m3, _, _ = _horse_prior_obs_stats(
                        w_hk,
                        w_day,
                        w_f["_hk"],
                        w_f["_day"].to_numpy(dtype=np.int64),
                        close_loss,
                        window_k=3,
                    )
                    h_margin_rel, _ = _race_rel_and_rank(work, h_margin_m3, compute_rk=False)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["h_margin_last"] = h_margin_last[inv]
    out["h_margin_m3"] = h_margin_m3[inv]
    out["h_close_loss_m3"] = h_close_loss_m3[inv]
    out["h_margin_rel"] = h_margin_rel[inv]
    return out


def attach_X_S800(df, race_extra=None):
    """Attach Block X_S800: leak-free prior race closing-800m speed & pace-ratio features (`< D`)."""
    if isinstance(race_extra, dict):
        race_extra = race_extra.get("race_extra")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in X_S800_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    w_hk = work["_hk_s"]
    w_day = work["_day_int"].to_numpy(dtype=np.int64)
    w_rid = _clean_entity_str(work["race_id"])

    h_s800_last = np.full(n, np.nan, dtype=np.float64)
    h_s800_m3 = np.full(n, np.nan, dtype=np.float64)
    h_pace_rat_last = np.full(n, np.nan, dtype=np.float64)
    h_s800_rel = np.full(n, np.nan, dtype=np.float64)

    if race_extra is not None and len(race_extra) > 0 and "son800_s" in race_extra.columns:
        rce = race_extra[["race_id", "son800_s"]].copy()
        rce["_rid"] = _clean_entity_str(rce["race_id"])
        rce["_s800"] = _to_f64(rce["son800_s"])
        rce = rce[rce["_rid"].notna() & np.isfinite(rce["_s800"]) & (rce["_s800"] > 35.0) & (rce["_s800"] < 80.0)]
        rce = rce.drop_duplicates(subset=["_rid"], keep="last")

        if len(rce) > 0:
            surf_s = (
                work["surface"].astype("string")
                if "surface" in work.columns
                else pd.Series("U", index=work.index, dtype="string")
            )
            breed_s = (
                work["breed"].astype("string")
                if "breed" in work.columns
                else pd.Series("U", index=work.index, dtype="string")
            )
            dist_num = pd.Series(_to_f64(work["distance"]) if "distance" in work.columns else np.nan, index=work.index)
            fin_num = pd.Series(_to_f64(work["finish"]) if "finish" in work.columns else np.nan, index=work.index)
            time_num = pd.Series(_to_f64(work["time_s"]) if "time_s" in work.columns else np.nan, index=work.index)

            win_times = (
                pd.DataFrame({"_rid": w_rid, "_t": time_num.where(fin_num == 1.0)})
                .dropna(subset=["_rid", "_t"])
                .groupby("_rid", sort=False)["_t"]
                .min()
            )
            race_meta = (
                pd.DataFrame(
                    {
                        "_rid": w_rid,
                        "_day": w_day,
                        "_sb": (surf_s.fillna("U") + "|" + breed_s.fillna("U")).astype("string"),
                        "_dist": dist_num,
                    }
                )
                .dropna(subset=["_rid"])
                .drop_duplicates("_rid")
            )
            race_meta["_win_t"] = _to_f64(race_meta["_rid"].map(win_times))
            r_joined = (
                race_meta.merge(rce[["_rid", "_s800"]], on="_rid", how="inner")
                .sort_values(["_day", "_rid"], kind="mergesort")
                .reset_index(drop=True)
            )

            if len(r_joined) > 0:
                par_mean, par_cnt = _prior_group_window_mean(
                    r_joined["_sb"],
                    r_joined["_day"].to_numpy(dtype=np.int64),
                    r_joined["_sb"],
                    r_joined["_day"].to_numpy(dtype=np.int64),
                    r_joined["_s800"].to_numpy(dtype=np.float64),
                    window_days=730,
                )
                par_shrunk = np.where(
                    par_cnt > 0,
                    (par_mean * par_cnt + 51.0 * 10.0) / (par_cnt + 10.0),
                    51.0,
                )
                s800_arr = r_joined["_s800"].to_numpy(dtype=np.float64)
                r_joined["_s800_fig"] = (par_shrunk - s800_arr) / par_shrunk * 1000.0

                d_r = r_joined["_dist"].to_numpy(dtype=np.float64)
                wt_r = r_joined["_win_t"].to_numpy(dtype=np.float64)
                early_d = d_r - 800.0
                early_t = wt_r - s800_arr
                valid_pace = np.isfinite(d_r) & np.isfinite(wt_r) & (early_d >= 200.0) & (early_t > 8.0)
                pace_rat = np.where(
                    valid_pace,
                    (s800_arr / 800.0) / np.where(valid_pace, early_t / np.maximum(early_d, 1.0), 1.0),
                    np.nan,
                )
                r_joined["_pace_rat"] = np.clip(pace_rat, 0.6, 1.6)

                w_with_pace = (
                    pd.DataFrame({"_rid": w_rid, "_hk": w_hk, "_day": w_day})
                    .merge(r_joined[["_rid", "_s800_fig", "_pace_rat"]], on="_rid", how="inner")
                    .sort_values(["_hk", "_day", "_rid"], kind="mergesort")
                    .reset_index(drop=True)
                )
                h_s800_last, h_s800_m3, _, _ = _horse_prior_obs_stats(
                    w_hk,
                    w_day,
                    w_with_pace["_hk"],
                    w_with_pace["_day"].to_numpy(dtype=np.int64),
                    w_with_pace["_s800_fig"].to_numpy(dtype=np.float64),
                    window_k=3,
                )
                h_pace_rat_last, _, _, _ = _horse_prior_obs_stats(
                    w_hk,
                    w_day,
                    w_with_pace["_hk"],
                    w_with_pace["_day"].to_numpy(dtype=np.int64),
                    w_with_pace["_pace_rat"].to_numpy(dtype=np.float64),
                    window_k=3,
                )
                h_s800_rel, _ = _race_rel_and_rank(work, h_s800_m3, compute_rk=False)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["h_s800_last"] = h_s800_last[inv]
    out["h_s800_m3"] = h_s800_m3[inv]
    out["h_pace_rat_last"] = h_pace_rat_last[inv]
    out["h_s800_rel"] = h_s800_rel[inv]
    return out


def attach_X_PRIZE(df, race_extra=None):
    """Attach Block X_PRIZE: inflation-normalized prior purse class (`race_extra.prize_1`, `< D`)."""
    if isinstance(race_extra, dict):
        race_extra = race_extra.get("race_extra")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in X_PRIZE_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    w_hk = work["_hk_s"]
    w_day = work["_day_int"].to_numpy(dtype=np.int64)
    w_rid = _clean_entity_str(work["race_id"])

    h_prize_last = np.full(n, np.nan, dtype=np.float64)
    h_prize_m3 = np.full(n, np.nan, dtype=np.float64)
    h_prize_best5 = np.full(n, np.nan, dtype=np.float64)
    h_prize_rel = np.full(n, np.nan, dtype=np.float64)
    h_prize_rk = np.full(n, np.nan, dtype=np.float64)

    if race_extra is not None and len(race_extra) > 0 and "prize_1" in race_extra.columns:
        rce = race_extra[["race_id", "prize_1"]].copy()
        rce["_rid"] = _clean_entity_str(rce["race_id"])
        rce["_pr"] = _to_f64(rce["prize_1"])
        rce = rce[rce["_rid"].notna() & np.isfinite(rce["_pr"]) & (rce["_pr"] > 0.0)]
        rce = rce.drop_duplicates(subset=["_rid"], keep="last")

        if len(rce) > 0:
            breed_s = (
                work["breed"].astype("string").fillna("ALL")
                if "breed" in work.columns
                else pd.Series("ALL", index=work.index, dtype="string")
            )
            race_meta = (
                pd.DataFrame({"_rid": w_rid, "_day": w_day, "_breed": breed_s})
                .dropna(subset=["_rid"])
                .drop_duplicates("_rid")
            )
            rj = (
                race_meta.merge(rce[["_rid", "_pr"]], on="_rid", how="inner")
                .sort_values(["_day", "_rid"], kind="mergesort")
                .reset_index(drop=True)
            )
            if len(rj) > 0:
                log_pr = np.log(rj["_pr"].to_numpy(dtype=np.float64))
                rj_days = rj["_day"].to_numpy(dtype=np.int64)
                all_grp = pd.Series("ALL", index=rj.index, dtype="string")

                br_mean, br_cnt = _prior_group_window_mean(
                    rj["_breed"], rj_days, rj["_breed"], rj_days, log_pr, window_days=365
                )
                all_mean, all_cnt = _prior_group_window_mean(
                    all_grp, rj_days, all_grp, rj_days, log_pr, window_days=365
                )
                ref_log_pr = np.where(br_cnt >= 20, br_mean, np.where(all_cnt > 0, all_mean, log_pr))
                rj["_rel_log_pr"] = log_pr - ref_log_pr

                obs_pr = (
                    pd.DataFrame({"_rid": w_rid, "_hk": w_hk, "_day": w_day})
                    .merge(rj[["_rid", "_rel_log_pr"]], on="_rid", how="inner")
                    .sort_values(["_hk", "_day", "_rid"], kind="mergesort")
                    .reset_index(drop=True)
                )
                h_prize_last, h_prize_m3, h_prize_best5, _ = _horse_prior_obs_stats(
                    w_hk,
                    w_day,
                    obs_pr["_hk"],
                    obs_pr["_day"].to_numpy(dtype=np.int64),
                    obs_pr["_rel_log_pr"].to_numpy(dtype=np.float64),
                    window_k=3,
                    compute_best5=True,
                )
                h_prize_rel, h_prize_rk = _race_rel_and_rank(work, h_prize_m3, compute_rk=True, ascending=False)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["h_prize_last"] = h_prize_last[inv]
    out["h_prize_m3"] = h_prize_m3[inv]
    out["h_prize_best5"] = h_prize_best5[inv]
    out["h_prize_rel"] = h_prize_rel[inv]
    out["h_prize_rk"] = h_prize_rk[inv]
    return out


def _is_win_ganyan_bet_series(bet_series):
    """Identify win-pool ('GANYAN') rows while excluding multi-leg ('6'LI GANYAN', '5'Lİ GANYAN', etc.)."""
    s = bet_series.astype("string").str.strip()
    has_gny = s.str.contains("ganyan", case=False, na=False)
    is_multi = s.str.contains(_MULTI_LEG_GANYAN_RE, na=False)
    return (has_gny & (~is_multi)).to_numpy(dtype=bool, na_value=False)


def attach_X_POOL(df, pools=None):
    """Attach Block X_POOL: leak-free trailing hipodrom pool liquidity & shipper delta (`< D`)."""
    if isinstance(pools, dict):
        pools = pools.get("pools")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in X_POOL_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    w_hk = work["_hk_s"]
    w_day = work["_day_int"].to_numpy(dtype=np.int64)
    w_city = (
        _clean_entity_str(work["city"])
        if "city" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )

    city_pool_rel_90d = np.full(n, np.nan, dtype=np.float64)
    city_ganyan_share_90d = np.full(n, np.nan, dtype=np.float64)
    h_origin_pool_m3 = np.full(n, np.nan, dtype=np.float64)
    h_shipper_delta = np.full(n, np.nan, dtype=np.float64)

    if pools is not None and len(pools) > 0 and {"date", "city", "amount"}.issubset(pools.columns):
        cols_p = ["date", "city", "amount"] + (["bet"] if "bet" in pools.columns else [])
        p_df = pools[cols_p].copy()
        p_df["_dt"] = pd.to_datetime(p_df["date"], errors="coerce")
        p_df["_city"] = _clean_entity_str(p_df["city"])
        p_df["_amt"] = _to_f64(p_df["amount"])
        p_df = p_df[p_df["_dt"].notna() & p_df["_city"].notna() & np.isfinite(p_df["_amt"]) & (p_df["_amt"] > 0.0)]

        if len(p_df) > 0:
            p_df["_day"] = _to_day_int(p_df["_dt"])
            if "bet" in p_df.columns:
                is_gny = _is_win_ganyan_bet_series(p_df["bet"])
                p_df["_gny_amt"] = np.where(is_gny, p_df["_amt"].to_numpy(dtype=np.float64), 0.0)
            else:
                p_df["_gny_amt"] = 0.0

            city_day = (
                p_df.groupby(["_city", "_day"], sort=False)[["_amt", "_gny_amt"]]
                .sum()
                .reset_index()
                .sort_values(["_city", "_day"], kind="mergesort")
                .reset_index(drop=True)
            )
            tot_arr = city_day["_amt"].to_numpy(dtype=np.float64)
            gny_arr = city_day["_gny_amt"].to_numpy(dtype=np.float64)
            city_day["_log_tot"] = np.log(tot_arr)
            city_day["_gny_sh"] = np.where(gny_arr > 0.0, gny_arr / tot_arr, np.nan)

            nat_src_grp = pd.Series("NAT", index=city_day.index, dtype="string")
            nat_tgt_grp = pd.Series("NAT", index=work.index, dtype="string")
            c_days_src = city_day["_day"].to_numpy(dtype=np.int64)
            c_log_src = city_day["_log_tot"].to_numpy(dtype=np.float64)
            c_gny_src = city_day["_gny_sh"].to_numpy(dtype=np.float64)

            city_m90, city_c90 = _prior_group_window_mean(
                w_city, w_day, city_day["_city"], c_days_src, c_log_src, window_days=90
            )
            nat_m365, nat_c365 = _prior_group_window_mean(
                nat_tgt_grp, w_day, nat_src_grp, c_days_src, c_log_src, window_days=365
            )
            raw_diff = city_m90 - nat_m365
            shrink = city_c90 / (city_c90 + 5.0)
            city_pool_rel_90d = np.where(
                (nat_c365 > 0) & (city_c90 > 0) & np.isfinite(raw_diff),
                raw_diff * shrink,
                np.nan,
            )

            gny_m90, gny_c90 = _prior_group_window_mean(
                w_city, w_day, city_day["_city"], c_days_src, c_gny_src, window_days=90
            )
            city_ganyan_share_90d = np.where(gny_c90 > 0, gny_m90, np.nan)

            # Horse's trailing origin-circuit pool level over last 3 active starts strictly < D
            act_p = _active_mask_from_frame(work)
            _, h_origin_pool_m3, _, _ = _horse_prior_obs_stats(
                w_hk,
                w_day,
                w_hk[act_p].reset_index(drop=True),
                w_day[act_p],
                city_pool_rel_90d[act_p],
                window_k=3,
            )
            both_ok = np.isfinite(h_origin_pool_m3) & np.isfinite(city_pool_rel_90d)
            h_shipper_delta = np.where(both_ok, h_origin_pool_m3 - city_pool_rel_90d, np.nan)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["city_pool_rel_90d"] = city_pool_rel_90d[inv]
    out["city_ganyan_share_90d"] = city_ganyan_share_90d[inv]
    out["h_origin_pool_m3"] = h_origin_pool_m3[inv]
    out["h_shipper_delta"] = h_shipper_delta[inv]
    return out


def attach_X_STEW(df, steward_notes=None):
    """Attach Block X_STEW: leak-free prior steward-report (`steward_notes`) history (`< D`)."""
    if isinstance(steward_notes, dict):
        steward_notes = steward_notes.get("steward_notes")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in X_STEW_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)
    w_hk = work["_hk_s"]
    w_day = work["_day_int"].to_numpy(dtype=np.int64)
    w_rid = _clean_entity_str(work["race_id"])
    act_s = _active_mask_from_frame(work)

    if "h_n" in work.columns:
        h_n_prior = np.nan_to_num(_to_f64(work["h_n"]), nan=0.0)
    else:
        _, _, _, h_n_prior = _horse_prior_obs_stats(
            w_hk,
            w_day,
            w_hk[act_s].reset_index(drop=True),
            w_day[act_s],
            np.ones(int(act_s.sum()), dtype=np.float64),
        )

    stew_prior_cnt = np.zeros(n, dtype=np.float64)
    stew_days_last = np.full(n, np.nan, dtype=np.float64)
    stew_last_race_flag = np.full(n, np.nan, dtype=np.float64)

    st_matched_pairs = None
    if steward_notes is not None and len(steward_notes) > 0:
        st_sub = steward_notes.copy()
        st_sub["_rid"] = (
            _clean_entity_str(st_sub["race_id"])
            if "race_id" in st_sub.columns
            else pd.Series(pd.NA, index=st_sub.index, dtype="string")
        )
        st_sub["_hk"] = (
            _clean_entity_str(st_sub["horse_key"])
            if "horse_key" in st_sub.columns
            else pd.Series(pd.NA, index=st_sub.index, dtype="string")
        )
        if st_sub["_hk"].isna().any() and "horse_name" in st_sub.columns and "name" in work.columns:
            st_sub["_hname"] = _clean_entity_str(st_sub["horse_name"])
            name_map = (
                pd.DataFrame({"_rid": w_rid, "_hname": _clean_entity_str(work["name"]), "_hk_map": w_hk})
                .dropna(subset=["_rid", "_hname", "_hk_map"])
                .drop_duplicates(subset=["_rid", "_hname"])
            )
            st_sub = st_sub.merge(name_map, on=["_rid", "_hname"], how="left")
            st_sub["_hk"] = st_sub["_hk"].fillna(st_sub["_hk_map"])

        rid_date_map = (
            pd.DataFrame({"_rid": w_rid, "_dt_df": work["_dt"]})
            .dropna(subset=["_rid"])
            .drop_duplicates("_rid")
        )
        st_sub = st_sub.merge(rid_date_map, on="_rid", how="left")
        parsed_dt = pd.to_datetime(st_sub["_rid"].astype("string").str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
        st_sub["_dt"] = st_sub["_dt_df"].fillna(parsed_dt)
        st_sub = (
            st_sub[st_sub["_hk"].notna() & st_sub["_dt"].notna()]
            .drop_duplicates(subset=["_rid", "_hk"])
            .sort_values(["_hk", "_rid"], kind="mergesort")
            .reset_index(drop=True)
        )

        if len(st_sub) > 0:
            st_days = _to_day_int(st_sub["_dt"])
            st_daily = (
                pd.DataFrame({"_hk": st_sub["_hk"].astype("string"), "_day": st_days})
                .groupby(["_hk", "_day"], sort=False)
                .size()
                .reset_index(name="_cnt")
                .sort_values(["_hk", "_day"], kind="mergesort")
                .reset_index(drop=True)
            )
            _, st_mean_all, _, st_days_cnt, stew_days_last = _horse_prior_obs_stats(
                w_hk,
                w_day,
                st_daily["_hk"].astype("string"),
                st_daily["_day"].to_numpy(dtype=np.int64),
                st_daily["_cnt"].to_numpy(dtype=np.float64),
                window_k=100000,
                return_days_since=True,
            )
            stew_prior_cnt = np.where(st_days_cnt > 0, st_mean_all * st_days_cnt, 0.0)
            st_matched_pairs = st_sub[["_rid", "_hk"]].assign(_has_stew=1.0)

    # Indicator for whether the horse's immediately preceding active start (< D) had a steward note
    starts_df = pd.DataFrame(
        {
            "_rid": w_rid[act_s].reset_index(drop=True),
            "_hk": w_hk[act_s].reset_index(drop=True),
            "_day": w_day[act_s],
        }
    )
    if st_matched_pairs is not None and len(st_matched_pairs) > 0:
        starts_df = starts_df.merge(st_matched_pairs, on=["_rid", "_hk"], how="left")
        has_stew_arr = np.nan_to_num(_to_f64(starts_df["_has_stew"]), nan=0.0)
    else:
        has_stew_arr = np.zeros(len(starts_df), dtype=np.float64)

    stew_last_race_flag, _, _, _ = _horse_prior_obs_stats(
        w_hk,
        w_day,
        starts_df["_hk"],
        starts_df["_day"].to_numpy(dtype=np.int64),
        has_stew_arr,
        window_k=1,
    )

    stew_prior_rate = stew_prior_cnt / np.maximum(h_n_prior + 3.0, 3.0)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["stew_prior_cnt"] = stew_prior_cnt[inv]
    out["stew_prior_rate"] = stew_prior_rate[inv]
    out["stew_days_last"] = stew_days_last[inv]
    out["stew_last_race_flag"] = stew_last_race_flag[inv]
    return out


def attach_v6(df, tables=None, blocks=tuple(V6_BLOCK_COLS)):
    """Attach selected leak-free v6 feature blocks onto a `build_features` (+ `attach_v5`) DataFrame."""
    tables = tables or {}
    out = df.copy()
    for blk in blocks:
        if blk == "X_GC":
            out = attach_X_GC(out, tables.get("runner_extra"))
        elif blk == "X_FARK":
            out = attach_X_FARK(out, tables.get("runner_extra"))
        elif blk == "X_S800":
            out = attach_X_S800(out, tables.get("race_extra"))
        elif blk == "X_PRIZE":
            out = attach_X_PRIZE(out, tables.get("race_extra"))
        elif blk == "X_POOL":
            out = attach_X_POOL(out, tables.get("pools"))
        elif blk == "X_STEW":
            out = attach_X_STEW(out, tables.get("steward_notes"))
        else:
            raise ValueError(f"Unknown v6 block: {blk!r}. Expected subset of {tuple(V6_BLOCK_COLS)}.")
    return out


def compute_yearly_source_coverage(runners_df, v5_tables=None, v6_tables=None, feat_df=None):
    """Count per-year source and feature availability across 2005..max_year directly from DB tables."""
    v5_tables = v5_tables or {}
    v6_tables = v6_tables or {}

    if runners_df is None or len(runners_df) == 0:
        return pd.DataFrame()

    keep_cols = [
        c for c in ("race_id", "horse_key", "date", "scratched", "agf_close", "time_s") if c in runners_df.columns
    ]
    base = runners_df[keep_cols].copy()
    if "scratched" in base.columns:
        scr = _to_f64(base["scratched"])
        base = base[np.isnan(scr) | (scr == 0.0)].copy()
    if len(base) == 0:
        return pd.DataFrame()

    base["_dt"] = pd.to_datetime(base["date"], errors="coerce")
    base = base[base["_dt"].notna()].copy()
    base["_year"] = base["_dt"].dt.year.astype(np.int32)
    base["_rid"] = _clean_entity_str(base["race_id"])
    base["_hk"] = _clean_entity_str(base["horse_key"])

    # External speed source match (yenibeygir)
    ext_df = v5_tables.get("ext")
    if ext_df is not None and len(ext_df) > 0:
        ext_ok = ext_df.copy()
        ext_ok["_rid"] = _clean_entity_str(ext_ok["race_id"])
        ext_ok["_hk"] = _clean_entity_str(ext_ok["horse_key"])
        ext_ok["_v"] = _to_f64(ext_ok["value"])
        ext_keys = (
            ext_ok[ext_ok["_rid"].notna() & ext_ok["_hk"].notna() & np.isfinite(ext_ok["_v"])][["_rid", "_hk"]]
            .drop_duplicates()
            .assign(_has_yb=1.0)
        )
        base = base.merge(ext_keys, on=["_rid", "_hk"], how="left")
    else:
        base["_has_yb"] = np.nan

    # runner_extra source match
    re_df = v6_tables.get("runner_extra")
    if re_df is not None and len(re_df) > 0:
        re_ok = re_df.copy()
        re_ok["_rid"] = _clean_entity_str(re_ok["race_id"])
        re_ok["_hk"] = _clean_entity_str(re_ok["horse_key"])
        f_clean = _clean_entity_str(re_ok["fark"])
        g_clean = _clean_entity_str(re_ok["gec_cikis"])
        dashes = ("-", "--", "---", "—", "–")
        re_ok["_has_fark"] = (f_clean.notna() & (~f_clean.isin(dashes))).to_numpy(dtype=np.float64, na_value=0.0)
        re_ok["_has_gc"] = (g_clean.notna() & (~g_clean.isin(dashes))).to_numpy(dtype=np.float64, na_value=0.0)
        re_ok = re_ok.dropna(subset=["_rid", "_hk"]).drop_duplicates(subset=["_rid", "_hk"], keep="last")
        base = base.merge(re_ok[["_rid", "_hk", "_has_fark", "_has_gc"]], on=["_rid", "_hk"], how="left")
    else:
        base["_has_fark"] = np.nan
        base["_has_gc"] = np.nan

    # race_extra source match
    races_u = base[["_year", "_rid"]].dropna(subset=["_rid"]).drop_duplicates("_rid")
    rce_df = v6_tables.get("race_extra")
    if rce_df is not None and len(rce_df) > 0:
        rce_ok = rce_df.copy()
        rce_ok["_rid"] = _clean_entity_str(rce_ok["race_id"])
        rce_ok["_s800_ok"] = np.isfinite(_to_f64(rce_ok["son800_s"])).astype(np.float64)
        rce_ok["_pr_ok"] = (np.isfinite(_to_f64(rce_ok["prize_1"])) & (_to_f64(rce_ok["prize_1"]) > 0.0)).astype(
            np.float64
        )
        rce_ok = rce_ok.dropna(subset=["_rid"]).drop_duplicates("_rid", keep="last")
        races_u = races_u.merge(rce_ok[["_rid", "_s800_ok", "_pr_ok"]], on="_rid", how="left")
    else:
        races_u["_s800_ok"] = 0.0
        races_u["_pr_ok"] = 0.0

    # workouts by year
    w_df = v5_tables.get("workouts")
    w_by_year = {}
    if w_df is not None and len(w_df) > 0 and "date" in w_df.columns:
        w_dt = pd.to_datetime(w_df["date"], errors="coerce").dropna()
        if len(w_dt) > 0:
            w_by_year = w_dt.dt.year.value_counts().to_dict()

    # pools distinct days by year
    p_df = v6_tables.get("pools")
    pool_days_by_year = {}
    if p_df is not None and len(p_df) > 0 and "date" in p_df.columns:
        p_dt = pd.to_datetime(p_df["date"], errors="coerce").dropna()
        if len(p_dt) > 0:
            tmp_p = pd.DataFrame({"_y": p_dt.dt.year, "_d": p_dt.dt.normalize()})
            pool_days_by_year = tmp_p.groupby("_y")["_d"].nunique().to_dict()

    # steward_notes rows by year
    st_df = v6_tables.get("steward_notes")
    stew_by_year = {}
    if st_df is not None and len(st_df) > 0 and "race_id" in st_df.columns:
        st_y = pd.to_numeric(st_df["race_id"].astype("string").str.slice(0, 4), errors="coerce").dropna()
        if len(st_y) > 0:
            stew_by_year = st_y.astype(int).value_counts().to_dict()

    # Optional derived feature coverage by year (sfa_last, yb_hiz_last, g_days_last, elo_h)
    feat_by_year = {}
    if feat_df is not None and len(feat_df) > 0 and "date" in feat_df.columns:
        f_yr = pd.to_datetime(feat_df["date"]).dt.year.to_numpy(dtype=np.int32)
        for y_val in np.unique(f_yr):
            m = f_yr == y_val
            d_f = {}
            for col_n in ("sfa_last", "yb_hiz_last", "g_days_last"):
                if col_n in feat_df.columns:
                    arr_c = _to_f64(feat_df[col_n])[m]
                    d_f[col_n] = float(np.isfinite(arr_c).mean()) if len(arr_c) > 0 else 0.0
            if "elo_h" in feat_df.columns:
                arr_e = _to_f64(feat_df["elo_h"])[m]
                d_f["elo_nz"] = float((np.isfinite(arr_e) & (arr_e != 0.0)).mean()) if len(arr_e) > 0 else 0.0
            feat_by_year[int(y_val)] = d_f

    agf_ok_all = np.isfinite(_to_f64(base["agf_close"])) if "agf_close" in base.columns else np.zeros(len(base), bool)
    time_ok_all = np.isfinite(_to_f64(base["time_s"])) if "time_s" in base.columns else np.zeros(len(base), bool)
    yb_ok_all = _to_f64(base["_has_yb"]) == 1.0
    fark_ok_all = _to_f64(base["_has_fark"]) == 1.0
    gc_ok_all = _to_f64(base["_has_gc"]) == 1.0
    yr_arr = base["_year"].to_numpy(dtype=np.int32)

    r_yr_arr = races_u["_year"].to_numpy(dtype=np.int32)
    r_s800_ok = _to_f64(races_u["_s800_ok"]) == 1.0
    r_pr_ok = _to_f64(races_u["_pr_ok"]) == 1.0

    rows = []
    for y in sorted(int(v) for v in np.unique(yr_arr)):
        ym = yr_arr == y
        rm = r_yr_arr == y
        n_run = int(np.sum(ym))
        n_rac = int(np.sum(rm))
        f_info = feat_by_year.get(y, {})
        rows.append(
            {
                "year": y,
                "races": n_rac,
                "runners": n_run,
                "agf_pct": float(agf_ok_all[ym].mean()) if n_run > 0 else 0.0,
                "time_pct": float(time_ok_all[ym].mean()) if n_run > 0 else 0.0,
                "sfa_feat_pct": f_info.get("sfa_last", np.nan),
                "yb_src_pct": float(yb_ok_all[ym].mean()) if n_run > 0 else 0.0,
                "yb_feat_pct": f_info.get("yb_hiz_last", np.nan),
                "workout_rows": int(w_by_year.get(y, 0)),
                "galop_feat_pct": f_info.get("g_days_last", np.nan),
                "elo_nz_pct": f_info.get("elo_nz", np.nan),
                "re_fark_pct": float(fark_ok_all[ym].mean()) if n_run > 0 else 0.0,
                "re_gec_pct": float(gc_ok_all[ym].mean()) if n_run > 0 else 0.0,
                "rce_s800_pct": float(r_s800_ok[rm].mean()) if n_rac > 0 else 0.0,
                "rce_prize_pct": float(r_pr_ok[rm].mean()) if n_rac > 0 else 0.0,
                "pool_days": int(pool_days_by_year.get(y, 0)),
                "steward_rows": int(stew_by_year.get(y, 0)),
            }
        )
    return pd.DataFrame(rows)
