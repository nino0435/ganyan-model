"""Leak-free v5 feature blocks (S: speed, G: workouts, R: day-frozen Elo) for Ganyan."""
import os
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd

S_COLS = [
    "yb_hiz_last",
    "yb_hiz_m3",
    "yb_hiz_best5",
    "yb_hiz_n",
    "sfa_last",
    "sfa_m3",
    "sfa_best5",
]

G_COLS = [
    "g_n14",
    "g_n30",
    "g_days_last",
    "g_last_d400",
    "g_last_d600",
    "g_last_d800",
    "g_best_d400_30",
    "g_best_d800_30",
    "g_allout_30",
    "g_sprint_30",
    "g_last_d400_rel",
]

R_COLS = [
    "elo_h",
    "elo_j",
    "elo_t",
    "elo_h_rel",
    "elo_h_rk",
]

BLOCK_COLS = {
    "S": list(S_COLS),
    "G": list(G_COLS),
    "R": list(R_COLS),
}

_EMPTY_WORKOUT_COLS = [
    "source",
    "horse_key",
    "date",
    "city",
    "kind",
    "d800",
    "d600",
    "d400",
    "effort",
]


def _empty_ext_df():
    return pd.DataFrame(
        {
            "race_id": pd.Series(dtype="string"),
            "horse_key": pd.Series(dtype="string"),
            "value": pd.Series(dtype="float64"),
        }
    )


def _empty_workouts_df():
    cols = {c: pd.Series(dtype="string") for c in _EMPTY_WORKOUT_COLS}
    cols["date"] = pd.to_datetime(pd.Series(dtype="object"))
    for dcol in ("d800", "d600", "d400"):
        cols[dcol] = pd.Series(dtype="float64")
    return pd.DataFrame(cols)


def load_v5_tables(conn):
    """Load external Yenibeygir speed ratings and Liderform workouts from SQLite.

    Accepts an open ``sqlite3.Connection`` or a DB path (opened read-only with ``timeout=60``).
    Returns ``{"ext": DataFrame, "workouts": DataFrame}`` without raising if tables are missing/empty.
    """
    if conn is None:
        return {"ext": _empty_ext_df(), "workouts": _empty_workouts_df()}

    own_conn = False
    if isinstance(conn, (str, os.PathLike)):
        p = Path(conn)
        if not p.exists():
            return {"ext": _empty_ext_df(), "workouts": _empty_workouts_df()}
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

        if "ext_ratings" in tables:
            ext_df = pd.read_sql_query(
                """
                SELECT race_id, horse_key, value
                FROM ext_ratings
                WHERE source = 'yenibeygir'
                  AND name = 'hiz'
                  AND horse_key IS NOT NULL
                  AND horse_key != ''
                """,
                conn,
            )
            if ext_df.empty:
                ext_df = _empty_ext_df()
            else:
                ext_df["value"] = pd.to_numeric(ext_df["value"], errors="coerce")
        else:
            ext_df = _empty_ext_df()

        if "workouts" in tables:
            workouts_df = pd.read_sql_query(
                """
                SELECT *
                FROM workouts
                WHERE source IN ('liderform', 'yenibeygir')
                  AND horse_key IS NOT NULL
                  AND horse_key != ''
                """,
                conn,
            )
            if workouts_df.empty:
                workouts_df = _empty_workouts_df()
            else:
                workouts_df["date"] = pd.to_datetime(workouts_df["date"], errors="coerce")
                workouts_df = workouts_df[workouts_df["date"].notna()].reset_index(drop=True)
        else:
            workouts_df = _empty_workouts_df()

        return {"ext": ext_df, "workouts": workouts_df}
    finally:
        if own_conn:
            conn.close()


def _to_day_int(dt_series):
    """Convert a non-null datetime Series to integer days since 1970-01-01 (unit-agnostic)."""
    return pd.to_datetime(dt_series).to_numpy().astype("datetime64[D]").astype(np.int64)


def _clean_entity_str(series):
    """Normalize entity identifier column to trimmed StringDtype with blanks mapped to pd.NA."""
    s = series.astype("string").str.strip()
    return s.mask(s == "", pd.NA)


def _sorted_work_frame(df):
    """Return a pre-race deterministically sorted working copy with original position tracking."""
    work = df.copy()
    work["_orig_pos"] = np.arange(len(work), dtype=np.int64)
    work["_dt"] = pd.to_datetime(work["date"])
    work["_day_int"] = _to_day_int(work["_dt"])
    work["_city_s"] = (
        work["city"].astype("string") if "city" in work.columns else pd.Series("", index=work.index, dtype="string")
    )
    work["_race_no_n"] = (
        pd.to_numeric(work["race_no"], errors="coerce").fillna(0)
        if "race_no" in work.columns
        else 0
    )
    work["_rid_sort"] = (
        work["race_id"].astype("string")
        if "race_id" in work.columns
        else pd.Series("", index=work.index, dtype="string")
    )
    work["_hk_s"] = _clean_entity_str(work["horse_key"])
    work = work.sort_values(
        ["_day_int", "_city_s", "_race_no_n", "_rid_sort", "_hk_s", "_orig_pos"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    return work


def _prior_horse_stats(work, val_col):
    """Compute leak-free (last, m3, best5, n_prior) strictly before day D for each horse."""
    n = len(work)
    valid_hk = work["_hk_s"].notna().to_numpy()
    g = work.groupby("_hk_s", sort=False, dropna=False)[val_col]

    s1 = g.shift(1).to_numpy(dtype=np.float64, copy=True)
    s2 = g.shift(2).to_numpy(dtype=np.float64, copy=True)
    s3 = g.shift(3).to_numpy(dtype=np.float64, copy=True)
    s4 = g.shift(4).to_numpy(dtype=np.float64, copy=True)
    s5 = g.shift(5).to_numpy(dtype=np.float64, copy=True)

    last = np.where(valid_hk, s1, np.nan)

    c1 = np.isfinite(s1)
    c2 = np.isfinite(s2)
    c3 = np.isfinite(s3)
    cnt3 = c1.astype(np.int32) + c2.astype(np.int32) + c3.astype(np.int32)
    sum3 = np.where(c1, s1, 0.0) + np.where(c2, s2, 0.0) + np.where(c3, s3, 0.0)
    m3 = np.where(valid_hk & (cnt3 > 0), sum3 / np.maximum(cnt3, 1), np.nan)

    best5_raw = np.fmax.reduce([s1, s2, s3, s4, s5])
    best5 = np.where(valid_hk, best5_raw, np.nan)

    has_val = work[val_col].notna().astype(np.int32)
    cum_val = has_val.groupby(work["_hk_s"], sort=False, dropna=False).cumsum().to_numpy(dtype=np.float64)
    n_prior = np.where(valid_hk, cum_val - has_val.to_numpy(dtype=np.float64), 0.0)

    # Guard against any synthetic same-day multi-entry for the same horse: freeze at first row of (horse, day)
    if n > 1:
        hk_codes, _ = pd.factorize(work["_hk_s"], sort=False)
        day_arr = work["_day_int"].to_numpy()
        order = np.argsort(hk_codes, kind="mergesort")
        hk_o = hk_codes[order]
        day_o = day_arr[order]
        same_hd = (hk_o[1:] >= 0) & (hk_o[1:] == hk_o[:-1]) & (day_o[1:] == day_o[:-1])
        if same_hd.any():
            for idx_pos in np.flatnonzero(same_hd) + 1:
                cur_row = order[idx_pos]
                prev_row = order[idx_pos - 1]
                last[cur_row] = last[prev_row]
                m3[cur_row] = m3[prev_row]
                best5[cur_row] = best5[prev_row]
                n_prior[cur_row] = n_prior[prev_row]

    return last, m3, best5, n_prior


def attach_S(df, ext=None):
    """Attach Block S speed features (`yb_hiz_*` and day-variant adjusted `sfa_*`)."""
    if isinstance(ext, dict):
        ext = ext.get("ext")

    out = df.copy()
    if len(out) == 0:
        for c in S_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)

    # (i) Yenibeygir speed rating history
    if ext is not None and len(ext) > 0:
        ext_sub = ext[["race_id", "horse_key", "value"]].copy()
        ext_sub["_rid_s"] = _clean_entity_str(ext_sub["race_id"])
        ext_sub["_hk_s"] = _clean_entity_str(ext_sub["horse_key"])
        ext_sub["_yb_val"] = pd.to_numeric(ext_sub["value"], errors="coerce")
        ext_sub = (
            ext_sub.dropna(subset=["_rid_s", "_hk_s"])
            .drop_duplicates(subset=["_rid_s", "_hk_s"], keep="last")[["_rid_s", "_hk_s", "_yb_val"]]
        )
        work["_rid_s"] = _clean_entity_str(work["race_id"])
        work = work.merge(ext_sub, on=["_rid_s", "_hk_s"], how="left")
    else:
        work["_yb_val"] = np.nan

    yb_last, yb_m3, yb_best5, yb_n = _prior_horse_stats(work, "_yb_val")

    # (ii) Day-variant adjusted speed figure (sfa)
    work["_year"] = work["_dt"].dt.year.astype(np.int32)
    work["_time_s"] = (
        pd.to_numeric(work["time_s"], errors="coerce")
        if "time_s" in work.columns
        else pd.Series(np.nan, index=work.index, dtype="float64")
    )

    years = np.sort(work["_year"].unique())
    min_year = int(years[0])
    timed = work[work["_time_s"].notna()]

    fine_frames = []
    coarse_frames = []
    for y in years:
        y_int = int(y)
        ref = timed[(timed["_year"] >= y_int - 2) & (timed["_year"] < y_int)]
        if len(ref) == 0 and y_int == min_year:
            ref = timed[timed["_year"] == y_int]
        if len(ref) == 0:
            continue

        f_grp = ref.groupby(["city", "surface", "distance", "breed"])["_time_s"].agg(["median", "count"])
        f_ok = f_grp[f_grp["count"] >= 20][["median"]].rename(columns={"median": "_par_fine"}).reset_index()
        if len(f_ok) > 0:
            f_ok["_year"] = np.int32(y_int)
            fine_frames.append(f_ok)

        c_grp = ref.groupby(["surface", "distance", "breed"])["_time_s"].agg(["median", "count"])
        c_ok = c_grp[c_grp["count"] >= 20][["median"]].rename(columns={"median": "_par_coarse"}).reset_index()
        if len(c_ok) > 0:
            c_ok["_year"] = np.int32(y_int)
            coarse_frames.append(c_ok)

    if fine_frames:
        fine_all = pd.concat(fine_frames, ignore_index=True)
        work = work.merge(fine_all, on=["_year", "city", "surface", "distance", "breed"], how="left")
    else:
        work["_par_fine"] = np.nan

    if coarse_frames:
        coarse_all = pd.concat(coarse_frames, ignore_index=True)
        work = work.merge(coarse_all, on=["_year", "surface", "distance", "breed"], how="left")
    else:
        work["_par_coarse"] = np.nan

    par_fine = work["_par_fine"].to_numpy(dtype=np.float64)
    par_coarse = work["_par_coarse"].to_numpy(dtype=np.float64)
    par_t = np.where(np.isfinite(par_fine), par_fine, par_coarse)
    par_t = np.where(par_t > 0.0, par_t, np.nan)

    time_arr = work["_time_s"].to_numpy(dtype=np.float64)
    sf_raw = (par_t - time_arr) / par_t * 1000.0
    work["_sf_raw"] = sf_raw

    dv_grp = work.groupby(["_day_int", "_city_s"], dropna=False)["_sf_raw"].agg(["median", "count"])
    dv_map = np.where(dv_grp["count"] >= 15, dv_grp["median"], 0.0)
    dv_df = pd.DataFrame({"_day_var": dv_map}, index=dv_grp.index).reset_index()
    work = work.merge(dv_df, on=["_day_int", "_city_s"], how="left")

    day_var = work["_day_var"].fillna(0.0).to_numpy(dtype=np.float64)
    work["_sfa"] = sf_raw - day_var

    sfa_last, sfa_m3, sfa_best5, _ = _prior_horse_stats(work, "_sfa")

    inv = np.empty(len(work), dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(len(work), dtype=np.int64)

    out["yb_hiz_last"] = yb_last[inv]
    out["yb_hiz_m3"] = yb_m3[inv]
    out["yb_hiz_best5"] = yb_best5[inv]
    out["yb_hiz_n"] = yb_n[inv]
    out["sfa_last"] = sfa_last[inv]
    out["sfa_m3"] = sfa_m3[inv]
    out["sfa_best5"] = sfa_best5[inv]
    return out


def attach_G(df, workouts=None):
    """Attach Block G Liderform workout features (`g_*`) using per-horse `numpy.searchsorted`."""
    if isinstance(workouts, dict):
        workouts = workouts.get("workouts")

    out = df.copy()
    n = len(out)
    if n == 0:
        for c in G_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    g_n14 = np.zeros(n, dtype=np.float64)
    g_n30 = np.zeros(n, dtype=np.float64)
    g_days_last = np.full(n, np.nan, dtype=np.float64)
    g_last_d400 = np.full(n, np.nan, dtype=np.float64)
    g_last_d600 = np.full(n, np.nan, dtype=np.float64)
    g_last_d800 = np.full(n, np.nan, dtype=np.float64)
    g_best_d400_30 = np.full(n, np.nan, dtype=np.float64)
    g_best_d800_30 = np.full(n, np.nan, dtype=np.float64)
    g_allout_30 = np.zeros(n, dtype=np.float64)
    g_sprint_30 = np.zeros(n, dtype=np.float64)
    g_last_d400_rel = np.full(n, np.nan, dtype=np.float64)

    if workouts is not None and len(workouts) > 0:
        w = workouts.copy()
        if "source" in w.columns:
            src_s = w["source"].astype("string").str.strip()
            if src_s.isin(["liderform", "yenibeygir"]).any() or src_s.notna().any():
                w = w[src_s.isin(["liderform", "yenibeygir"])].copy()
        w["_hk_s"] = _clean_entity_str(w["horse_key"])
        w["_dt"] = pd.to_datetime(w["date"], errors="coerce")
        w = w[w["_hk_s"].notna() & w["_dt"].notna()].copy()
        if "source" in w.columns and len(w) > 0:
            w_src = w["source"].astype("string").str.strip()
            if (w_src == "yenibeygir").any():
                w["_src_prio"] = np.where(w_src == "liderform", 0, 1)
                w = (
                    w.sort_values("_src_prio", kind="mergesort")
                    .drop_duplicates(subset=["_hk_s", "_dt"], keep="first")
                    .drop(columns=["_src_prio"])
                )
    else:
        w = pd.DataFrame()

    if len(w) > 0:
        w["_w_day"] = _to_day_int(w["_dt"])
        w["_city_s"] = (
            _clean_entity_str(w["city"])
            if "city" in w.columns
            else pd.Series(pd.NA, index=w.index, dtype="string")
        )
        w["_kind_s"] = (
            w["kind"].astype("string").str.strip().str.upper()
            if "kind" in w.columns
            else pd.Series(pd.NA, index=w.index, dtype="string")
        )
        w["_effort_s"] = (
            w["effort"].astype("string").str.strip().str.upper()
            if "effort" in w.columns
            else pd.Series(pd.NA, index=w.index, dtype="string")
        )
        for dcol in ("d400", "d600", "d800"):
            if dcol in w.columns:
                w[f"_{dcol}"] = pd.to_numeric(w[dcol], errors="coerce")
            else:
                w[f"_{dcol}"] = np.nan

        # Precompute (date, city) median d400 across workouts with >=5 valid d400 entries
        valid_dc = w[w["_city_s"].notna() & w["_d400"].notna()]
        if len(valid_dc) > 0:
            dc_grp = valid_dc.groupby(["_w_day", "_city_s"])["_d400"].agg(["median", "count"])
            dc_ok = dc_grp[dc_grp["count"] >= 5][["median"]].rename(columns={"median": "_med_d400"}).reset_index()
            if len(dc_ok) > 0:
                w = w.merge(dc_ok, on=["_w_day", "_city_s"], how="left")
            else:
                w["_med_d400"] = np.nan
        else:
            w["_med_d400"] = np.nan

        w["_d400_rel"] = w["_d400"] - w["_med_d400"]

        # Sort deterministically per horse by date so searchsorted operates on contiguous sorted slices
        w = w.sort_values(
            ["_hk_s", "_w_day", "_city_s", "_kind_s"],
            kind="mergesort",
            na_position="first",
        ).reset_index(drop=True)

        w_hk_code, hk_uniques = pd.factorize(w["_hk_s"], sort=False)
        w_bounds = np.r_[0, np.flatnonzero(w_hk_code[1:] != w_hk_code[:-1]) + 1, len(w)]

        w_day = w["_w_day"].to_numpy(dtype=np.int64)
        w_d400 = w["_d400"].to_numpy(dtype=np.float64)
        w_d600 = w["_d600"].to_numpy(dtype=np.float64)
        w_d800 = w["_d800"].to_numpy(dtype=np.float64)
        w_d400_rel = w["_d400_rel"].to_numpy(dtype=np.float64)
        is_allout = (w["_effort_s"] == "ALLOUT").fillna(False).to_numpy(dtype=np.int32)
        is_sprint = (w["_kind_s"] == "SPRINT").fillna(False).to_numpy(dtype=np.int32)

        cs_allout = np.empty(len(w) + 1, dtype=np.int64)
        cs_allout[0] = 0
        np.cumsum(is_allout, out=cs_allout[1:])

        cs_sprint = np.empty(len(w) + 1, dtype=np.int64)
        cs_sprint[0] = 0
        np.cumsum(is_sprint, out=cs_sprint[1:])

        df_hk = _clean_entity_str(out["horse_key"])
        df_day = _to_day_int(out["date"])
        df_code = hk_uniques.get_indexer(df_hk)

        matched_rows = np.flatnonzero(df_code >= 0)
        if len(matched_rows) > 0:
            m_codes = df_code[matched_rows]
            m_order = np.argsort(m_codes, kind="mergesort")
            rows_sorted = matched_rows[m_order]
            codes_sorted = m_codes[m_order]

            grp_splits = np.r_[0, np.flatnonzero(codes_sorted[1:] != codes_sorted[:-1]) + 1, len(codes_sorted)]
            for gi in range(len(grp_splits) - 1):
                gs = grp_splits[gi]
                ge = grp_splits[gi + 1]
                c = codes_sorted[gs]
                r_idx = rows_sorted[gs:ge]
                r_days = df_day[r_idx]

                ws = w_bounds[c]
                we = w_bounds[c + 1]
                wd = w_day[ws:we]

                hi = np.searchsorted(wd, r_days, side="left")
                lo60 = np.searchsorted(wd, r_days - 60, side="left")
                lo30 = np.searchsorted(wd, r_days - 30, side="left")
                lo14 = np.searchsorted(wd, r_days - 14, side="left")

                lo30_c = np.minimum(lo30, hi)
                lo14_c = np.minimum(lo14, hi)

                g_n14[r_idx] = (hi - lo14_c).astype(np.float64)
                g_n30[r_idx] = (hi - lo30_c).astype(np.float64)
                g_allout_30[r_idx] = (cs_allout[ws + hi] - cs_allout[ws + lo30_c]).astype(np.float64)
                g_sprint_30[r_idx] = (cs_sprint[ws + hi] - cs_sprint[ws + lo30_c]).astype(np.float64)

                has60 = hi > lo60
                if has60.any():
                    r60 = r_idx[has60]
                    last_w = ws + hi[has60] - 1
                    g_days_last[r60] = (r_days[has60] - w_day[last_w]).astype(np.float64)
                    g_last_d400[r60] = w_d400[last_w]
                    g_last_d600[r60] = w_d600[last_w]
                    g_last_d800[r60] = w_d800[last_w]
                    g_last_d400_rel[r60] = w_d400_rel[last_w]

                has30 = hi > lo30
                if has30.any():
                    for k_pos in np.flatnonzero(has30):
                        row_i = r_idx[k_pos]
                        s30 = ws + lo30[k_pos]
                        e30 = ws + hi[k_pos]
                        g_best_d400_30[row_i] = np.fmin.reduce(w_d400[s30:e30])
                        g_best_d800_30[row_i] = np.fmin.reduce(w_d800[s30:e30])

    out["g_n14"] = g_n14
    out["g_n30"] = g_n30
    out["g_days_last"] = g_days_last
    out["g_last_d400"] = g_last_d400
    out["g_last_d600"] = g_last_d600
    out["g_last_d800"] = g_last_d800
    out["g_best_d400_30"] = g_best_d400_30
    out["g_best_d800_30"] = g_best_d800_30
    out["g_allout_30"] = g_allout_30
    out["g_sprint_30"] = g_sprint_30
    out["g_last_d400_rel"] = g_last_d400_rel
    return out


def _race_softmax(scores):
    m = np.max(scores)
    e = np.exp(scores - m)
    return e / np.sum(e)


def attach_R(df, tables=None):
    """Attach Block R day-frozen Elo ratings (`elo_h`, `elo_j`, `elo_t`, `elo_h_rel`, `elo_h_rk`)."""
    del tables
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in R_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    work = _sorted_work_frame(out)

    hk_s = work["_hk_s"]
    jk_s = (
        _clean_entity_str(work["jockey"])
        if "jockey" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )
    tr_s = (
        _clean_entity_str(work["trainer"])
        if "trainer" in work.columns
        else pd.Series(pd.NA, index=work.index, dtype="string")
    )

    h_id, h_uniq = pd.factorize(hk_s, sort=False)
    j_id, j_uniq = pd.factorize(jk_s, sort=False)
    t_id, t_uniq = pd.factorize(tr_s, sort=False)

    r_h = np.zeros(max(len(h_uniq), 1), dtype=np.float64)
    r_j = np.zeros(max(len(j_uniq), 1), dtype=np.float64)
    r_t = np.zeros(max(len(t_uniq), 1), dtype=np.float64)

    elo_h = np.zeros(n, dtype=np.float64)
    elo_j = np.zeros(n, dtype=np.float64)
    elo_t = np.zeros(n, dtype=np.float64)

    if "scratched" in work.columns:
        active_arr = (pd.to_numeric(work["scratched"], errors="coerce").fillna(0) == 0).to_numpy()
    else:
        active_arr = np.ones(n, dtype=bool)

    if "status" in work.columns:
        st_s = work["status"].astype("string").str.strip().str.lower()
        cancelled_arr = (st_s == "cancelled").fillna(False).to_numpy()
    else:
        cancelled_arr = np.zeros(n, dtype=bool)

    if "finish" in work.columns:
        fin_num = pd.to_numeric(work["finish"], errors="coerce")
        win_arr = np.where(fin_num == 1, 1.0, 0.0)
    elif "win" in work.columns:
        win_num = pd.to_numeric(work["win"], errors="coerce")
        win_arr = np.where(win_num == 1, 1.0, 0.0)
    else:
        win_arr = np.zeros(n, dtype=np.float64)

    day_arr = work["_day_int"].to_numpy(dtype=np.int64)
    rid_code, _ = pd.factorize(work["race_id"].astype("string"), sort=False)

    day_bounds = np.r_[0, np.flatnonzero(day_arr[1:] != day_arr[:-1]) + 1, n]
    k_h, k_j, k_t = 0.25, 0.05, 0.04

    for di in range(len(day_bounds) - 1):
        ds = day_bounds[di]
        de = day_bounds[di + 1]

        # Snapshot start-of-day ratings for ALL runners on this day (day-frozen rule)
        hd = h_id[ds:de]
        jd = j_id[ds:de]
        td = t_id[ds:de]
        elo_h[ds:de] = np.where(hd >= 0, r_h[np.maximum(hd, 0)], 0.0)
        elo_j[ds:de] = np.where(jd >= 0, r_j[np.maximum(jd, 0)], 0.0)
        elo_t[ds:de] = np.where(td >= 0, r_t[np.maximum(td, 0)], 0.0)

        # Process each race of this day using the frozen start-of-day ratings stored in elo_*
        sub_rid = rid_code[ds:de]
        r_splits = np.r_[0, np.flatnonzero(sub_rid[1:] != sub_rid[:-1]) + 1, de - ds]
        for ri in range(len(r_splits) - 1):
            rs = ds + r_splits[ri]
            re = ds + r_splits[ri + 1]
            if cancelled_arr[rs]:
                continue
            act_mask = active_arr[rs:re]
            if not act_mask.all():
                idx = np.arange(rs, re)[act_mask]
            else:
                idx = slice(rs, re)

            w_race = win_arr[idx]
            if w_race.size == 0 or np.sum(w_race) <= 0.0:
                continue

            ph = _race_softmax(elo_h[idx])
            pj = _race_softmax(elo_j[idx])
            pt = _race_softmax(elo_t[idx])

            hi_r = h_id[idx]
            valid_h = hi_r >= 0
            if valid_h.any():
                np.add.at(r_h, hi_r[valid_h], k_h * (w_race[valid_h] - ph[valid_h]))

            ji_r = j_id[idx]
            valid_j = ji_r >= 0
            if valid_j.any():
                np.add.at(r_j, ji_r[valid_j], k_j * (w_race[valid_j] - pj[valid_j]))

            ti_r = t_id[idx]
            valid_t = ti_r >= 0
            if valid_t.any():
                np.add.at(r_t, ti_r[valid_t], k_t * (w_race[valid_t] - pt[valid_t]))

    work["_elo_h"] = elo_h
    if active_arr.all():
        rg = work.groupby("race_id", sort=False)
        elo_h_rel = (work["_elo_h"] - rg["_elo_h"].transform("mean")).to_numpy(dtype=np.float64)
        elo_h_rk = rg["_elo_h"].rank(ascending=False, pct=True).to_numpy(dtype=np.float64)
    else:
        elo_h_rel = np.full(n, np.nan, dtype=np.float64)
        elo_h_rk = np.full(n, np.nan, dtype=np.float64)
        act_df = work.loc[active_arr, ["race_id", "_elo_h"]]
        if len(act_df) > 0:
            rg = act_df.groupby("race_id", sort=False)
            elo_h_rel[active_arr] = (act_df["_elo_h"] - rg["_elo_h"].transform("mean")).to_numpy(dtype=np.float64)
            elo_h_rk[active_arr] = rg["_elo_h"].rank(ascending=False, pct=True).to_numpy(dtype=np.float64)

    inv = np.empty(n, dtype=np.int64)
    inv[work["_orig_pos"].to_numpy(dtype=np.int64)] = np.arange(n, dtype=np.int64)

    out["elo_h"] = elo_h[inv]
    out["elo_j"] = elo_j[inv]
    out["elo_t"] = elo_t[inv]
    out["elo_h_rel"] = elo_h_rel[inv]
    out["elo_h_rk"] = elo_h_rk[inv]
    return out


def attach_v5(df, tables=None, blocks=("S", "G", "R")):
    """Attach selected leak-free v5 feature blocks (`S`, `G`, `R`) onto `build_features` output."""
    tables = tables or {}
    out = df.copy()
    for b in blocks:
        if b == "S":
            out = attach_S(out, tables.get("ext"))
        elif b == "G":
            out = attach_G(out, tables.get("workouts"))
        elif b == "R":
            out = attach_R(out)
        else:
            raise ValueError(f"Unknown v5 block: {b!r}. Expected subset of ('S', 'G', 'R').")
    return out
