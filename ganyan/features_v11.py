"""Leak-free v11 pre-race going and weather feature blocks (GOING, WX, GPREF)."""
import os
from pathlib import Path
import re
import sqlite3

import numpy as np
import pandas as pd

from ganyan.features_v7 import _active_mask, _fpct_array, _inv_order
from ganyan.features_v9 import (
    _col_or_empty,
    _day_stride,
    _empty_result,
    _lite_work_frame,
    _norm_upper_str,
    _range_window_agg,
)
from ganyan.features_v10 import _attach_cols, _fast_race_active_rel, _to_f64, get_v10_cols
from ganyan.model_v10 import V10_BLOCKS, V10_CONFIG
from ganyan.track import normalize_track_cond

GOING_COLS = [
    "going_ord",
    "going_wet",
    "going_turf_num",
    "going_turf_ord",
    "going_dirt_ord",
]

WX_COLS = [
    "wx_temp_c",
    "wx_rh",
    "wx_rainy",
    "wx_windy",
]

GPREF_COLS = [
    "gpref_wet_n",
    "gpref_wet_wr",
    "gpref_wet_fpct_delta",
    "gpref_wet_sf_delta",
    "gpref_wet_x_fpct_delta",
    "gpref_wet_x_sf_delta",
    "gpref_wet_x_fpct_rel",
]

V11_CANDIDATE_BLOCKS = ("GOING", "WX", "GPREF")

V11_BLOCK_COLS = {
    "GOING": list(GOING_COLS),
    "WX": list(WX_COLS),
    "GPREF": list(GPREF_COLS),
}

_BLOCK_NEEDED_COLS = {
    "GOING": ("scratched", "surface", "track_cond", "track_cond_raw"),
    "WX": ("scratched", "temp_c", "rh", "sky", "windy"),
    "GPREF": ("scratched", "surface", "track_cond", "track_cond_raw", "finish", "fpct", "sf"),
}

GOING_ORD_MAP = {
    "kuru": 0.0,
    "normal": 1.0,
    "nemli": 2.0,
    "islak": 3.0,
    "yumusak": 4.0,
    "agir": 5.0,
}

WET_CONDS = frozenset({"nemli", "islak", "yumusak", "agir"})
DRY_CONDS = frozenset({"kuru", "normal"})
RAINY_SKIES = frozenset({"yagisli", "karli"})

GPREF_WR_PRIOR_W = 0.3
GPREF_WR_PRIOR_N = 3.0
GPREF_FPCT_PRIOR_K = 3.0
GPREF_SF_PRIOR_K = 3.0

SMOOTHING_CONSTANTS = {
    "GPREF_WR_PRIOR_W": GPREF_WR_PRIOR_W,
    "GPREF_WR_PRIOR_N": GPREF_WR_PRIOR_N,
    "GPREF_FPCT_PRIOR_K": GPREF_FPCT_PRIOR_K,
    "GPREF_SF_PRIOR_K": GPREF_SF_PRIOR_K,
}

_TURF_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*$")


def _empty_day_cond_df():
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="string"),
            "city": pd.Series(dtype="string"),
            "cim_raw": pd.Series(dtype="string"),
            "kum_raw": pd.Series(dtype="string"),
            "sentetik_raw": pd.Series(dtype="string"),
            "hava_raw": pd.Series(dtype="string"),
            "temp_c": pd.Series(dtype="float64"),
            "rh": pd.Series(dtype="float64"),
            "sky": pd.Series(dtype="string"),
            "windy": pd.Series(dtype="float64"),
        }
    )


def load_v11_tables(conn):
    """Load day_cond from SQLite (path or open Connection) without failing if missing."""
    if conn is None:
        return {"day_cond": _empty_day_cond_df()}

    own_conn = False
    if isinstance(conn, (str, os.PathLike)):
        p = Path(conn)
        if not p.exists():
            return {"day_cond": _empty_day_cond_df()}
        conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True, timeout=60)
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

        if "day_cond" in tables:
            dc_df = pd.read_sql_query(
                """
                SELECT date, city, cim_raw, kum_raw, sentetik_raw, hava_raw, temp_c, rh, sky, windy
                FROM day_cond
                """,
                conn,
            )
            if dc_df.empty:
                dc_df = _empty_day_cond_df()
            else:
                dc_df["temp_c"] = pd.to_numeric(dc_df["temp_c"], errors="coerce")
                dc_df["rh"] = pd.to_numeric(dc_df["rh"], errors="coerce")
                dc_df["windy"] = pd.to_numeric(dc_df["windy"], errors="coerce")
        else:
            dc_df = _empty_day_cond_df()

        return {"day_cond": dc_df}
    finally:
        if own_conn:
            conn.close()


def extract_turf_going_num(track_cond_raw):
    """Extract penetrometer numeric reading from turf raw condition (e.g. 'Çim: Yumuşak 3,7' -> 3.7)."""
    if track_cond_raw is None or (isinstance(track_cond_raw, float) and np.isnan(track_cond_raw)):
        return np.nan
    s = str(track_cond_raw).strip()
    if not s:
        return np.nan
    m = _TURF_NUM_RE.search(s)
    if not m:
        return np.nan
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return np.nan
    # Filter bogus '0' readings seen on occasional rows (e.g. 'Çim: Normal 0')
    if 0.5 < val <= 10.0:
        return val
    return np.nan


def _date_str_array(dt_series):
    return pd.to_datetime(dt_series).dt.strftime("%Y-%m-%d").to_numpy()


def _day_cond_lookup(v5_tables):
    """Build dict keyed by (date_str, upper_city) -> row dict from v5_tables['day_cond']."""
    if not isinstance(v5_tables, dict):
        return {}
    dc = v5_tables.get("day_cond")
    if dc is None or len(dc) == 0:
        return {}
    d_arr = pd.to_datetime(dc["date"], errors="coerce").dt.strftime("%Y-%m-%d").tolist()
    c_arr = _norm_upper_str(dc["city"]).tolist()
    cim_l = dc["cim_raw"].tolist() if "cim_raw" in dc.columns else [None] * len(dc)
    kum_l = dc["kum_raw"].tolist() if "kum_raw" in dc.columns else [None] * len(dc)
    sen_l = dc["sentetik_raw"].tolist() if "sentetik_raw" in dc.columns else [None] * len(dc)
    t_l = pd.to_numeric(dc["temp_c"], errors="coerce").to_numpy(dtype=np.float64).tolist() if "temp_c" in dc.columns else [np.nan] * len(dc)
    rh_l = pd.to_numeric(dc["rh"], errors="coerce").to_numpy(dtype=np.float64).tolist() if "rh" in dc.columns else [np.nan] * len(dc)
    sky_l = dc["sky"].tolist() if "sky" in dc.columns else [None] * len(dc)
    w_l = pd.to_numeric(dc["windy"], errors="coerce").to_numpy(dtype=np.float64).tolist() if "windy" in dc.columns else [np.nan] * len(dc)

    out = {}
    for idx in range(len(dc)):
        d_s = d_arr[idx]
        c_s = c_arr[idx]
        if not d_s or c_s is None or pd.isna(c_s):
            continue
        out[(d_s, str(c_s))] = {
            "Çim": cim_l[idx] if cim_l[idx] is not None and not pd.isna(cim_l[idx]) else None,
            "Kum": kum_l[idx] if kum_l[idx] is not None and not pd.isna(kum_l[idx]) else None,
            "Sentetik": sen_l[idx] if sen_l[idx] is not None and not pd.isna(sen_l[idx]) else None,
            "temp_c": t_l[idx],
            "rh": rh_l[idx],
            "sky": str(sky_l[idx]).strip() if sky_l[idx] is not None and not pd.isna(sky_l[idx]) else None,
            "windy": w_l[idx],
        }
    return out


def _build_v11_ctx(df, needed_cols, v5_tables=None):
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
        "v5_tables": v5_tables,
        "_dc_map": None,
        "_going": None,
    }


def _get_dc_map(ctx):
    if ctx["_dc_map"] is None:
        ctx["_dc_map"] = _day_cond_lookup(ctx["v5_tables"])
    return ctx["_dc_map"]


def _resolve_going_state(ctx):
    """Resolve normalized going, ordinal score, wet flag, and turf penetrometer reading once per ctx."""
    if ctx["_going"] is not None:
        return ctx["_going"]

    work = ctx["work"]
    n = ctx["n"]
    active = ctx["active"]

    surf_s = _col_or_empty(work, "surface", dtype="string").tolist()
    tc_raw_s = _col_or_empty(work, "track_cond_raw", dtype="string").tolist()
    tc_norm_s = _col_or_empty(work, "track_cond", dtype="string").tolist()

    dc_map = _get_dc_map(ctx)
    has_dc = bool(dc_map)
    if has_dc:
        d_strs = _date_str_array(work["_dt"]).tolist()
        c_ups = _norm_upper_str(_col_or_empty(work, "city", dtype="string")).tolist()
    else:
        d_strs = None
        c_ups = None

    going_ord = np.full(n, np.nan, dtype=np.float64)
    going_wet = np.full(n, np.nan, dtype=np.float64)
    going_turf_num = np.full(n, np.nan, dtype=np.float64)
    going_turf_ord = np.full(n, np.nan, dtype=np.float64)
    going_dirt_ord = np.full(n, np.nan, dtype=np.float64)

    norm_cache = {}
    turf_num_cache = {}
    act_l = active.tolist()

    for i in range(n):
        if not act_l[i]:
            continue
        sf_val = surf_s[i]
        sf_str = str(sf_val).strip() if sf_val is not None and not pd.isna(sf_val) else ""

        raw_val = tc_raw_s[i]
        raw_str = str(raw_val).strip() if raw_val is not None and not pd.isna(raw_val) else ""

        norm_val = tc_norm_s[i]
        norm_str = str(norm_val).strip().lower() if norm_val is not None and not pd.isna(norm_val) else ""

        # Fallback to day_cond only when track_cond/raw is missing or 'bilinmiyor'
        if has_dc and (not raw_str) and norm_str in ("", "bilinmiyor") and sf_str in ("Çim", "Kum", "Sentetik"):
            c_up = c_ups[i]
            if c_up is not None and not pd.isna(c_up):
                dc_row = dc_map.get((d_strs[i], str(c_up)))
                if dc_row is not None:
                    dc_raw = dc_row.get(sf_str)
                    if dc_raw:
                        raw_str = str(dc_raw).strip()

        if (not norm_str or norm_str == "bilinmiyor") and raw_str and sf_str:
            ckey = (sf_str, raw_str)
            if ckey not in norm_cache:
                try:
                    norm_cache[ckey] = normalize_track_cond(sf_str, raw_str)
                except KeyError:
                    norm_cache[ckey] = "bilinmiyor"
            norm_str = norm_cache[ckey]

        ord_v = GOING_ORD_MAP.get(norm_str)
        if ord_v is not None:
            going_ord[i] = ord_v
            if norm_str in WET_CONDS:
                going_wet[i] = 1.0
            elif norm_str in DRY_CONDS:
                going_wet[i] = 0.0
            if sf_str == "Çim":
                going_turf_ord[i] = ord_v
            elif sf_str == "Kum":
                going_dirt_ord[i] = ord_v

        if sf_str == "Çim" and raw_str:
            if raw_str not in turf_num_cache:
                turf_num_cache[raw_str] = extract_turf_going_num(raw_str)
            going_turf_num[i] = turf_num_cache[raw_str]

    res = {
        "going_ord": going_ord,
        "going_wet": going_wet,
        "going_turf_num": going_turf_num,
        "going_turf_ord": going_turf_ord,
        "going_dirt_ord": going_dirt_ord,
    }
    ctx["_going"] = res
    return res


def _compute_GOING(ctx):
    inv = ctx["inv"]
    gs = _resolve_going_state(ctx)
    return {k: gs[k][inv] for k in GOING_COLS}


def attach_GOING(df, v5_tables=None):
    """Attach GOING block: surface-ordered track condition, wet flag, and turf penetrometer."""
    if len(df) == 0:
        return _empty_result(df, GOING_COLS)
    ctx = _build_v11_ctx(df, _BLOCK_NEEDED_COLS["GOING"], v5_tables=v5_tables)
    return _attach_cols(df, _compute_GOING(ctx))


def _compute_WX(ctx):
    work = ctx["work"]
    n = ctx["n"]
    active = ctx["active"]
    inv = ctx["inv"]

    wx_temp = np.full(n, np.nan, dtype=np.float64)
    wx_rh = np.full(n, np.nan, dtype=np.float64)
    wx_rainy = np.full(n, np.nan, dtype=np.float64)
    wx_windy = np.full(n, np.nan, dtype=np.float64)

    # 1. Direct columns on df if caller provided them (e.g. unit tests)
    if "temp_c" in work.columns:
        wx_temp = _to_f64(work["temp_c"])
    if "rh" in work.columns:
        wx_rh = _to_f64(work["rh"])
    if "windy" in work.columns:
        wx_windy = _to_f64(work["windy"])
    if "sky" in work.columns:
        sky_col = work["sky"].tolist()
        for i, sv in enumerate(sky_col):
            if sv is not None and not pd.isna(sv):
                ss = str(sv).strip().lower()
                if ss:
                    wx_rainy[i] = 1.0 if ss in RAINY_SKIES else 0.0

    # 2. Fill remaining gaps from day_cond lookup
    dc_map = _get_dc_map(ctx)
    if dc_map:
        d_strs = _date_str_array(work["_dt"]).tolist()
        c_ups = _norm_upper_str(_col_or_empty(work, "city", dtype="string")).tolist()
        for i in range(n):
            if not active[i]:
                continue
            c_up = c_ups[i]
            if c_up is None or pd.isna(c_up):
                continue
            dc_row = dc_map.get((d_strs[i], str(c_up)))
            if dc_row is None:
                continue
            if np.isnan(wx_temp[i]) and np.isfinite(dc_row["temp_c"]):
                wx_temp[i] = dc_row["temp_c"]
            if np.isnan(wx_rh[i]) and np.isfinite(dc_row["rh"]):
                wx_rh[i] = dc_row["rh"]
            if np.isnan(wx_rainy[i]) and dc_row["sky"]:
                wx_rainy[i] = 1.0 if dc_row["sky"] in RAINY_SKIES else 0.0
            if np.isnan(wx_windy[i]) and np.isfinite(dc_row["windy"]):
                wx_windy[i] = 1.0 if dc_row["windy"] >= 0.5 else 0.0

    return {
        "wx_temp_c": np.where(active, wx_temp, np.nan)[inv],
        "wx_rh": np.where(active, wx_rh, np.nan)[inv],
        "wx_rainy": np.where(active, wx_rainy, np.nan)[inv],
        "wx_windy": np.where(active, wx_windy, np.nan)[inv],
    }


def attach_WX(df, v5_tables=None):
    """Attach WX block: temperature, humidity, rainy flag, and windy flag."""
    if len(df) == 0:
        return _empty_result(df, WX_COLS)
    ctx = _build_v11_ctx(df, _BLOCK_NEEDED_COLS["WX"], v5_tables=v5_tables)
    return _attach_cols(df, _compute_WX(ctx))


def _compute_GPREF(ctx):
    work = ctx["work"]
    n = ctx["n"]
    active = ctx["active"]
    fin = ctx["fin"]
    settled = ctx["settled"]
    hk_codes = ctx["hk_codes"]
    day_off = ctx["day_off"]
    stride = ctx["stride"]
    inv = ctx["inv"]

    gs = _resolve_going_state(ctx)
    going_wet = gs["going_wet"]

    fpct_arr = _to_f64(work["fpct"]) if "fpct" in work.columns else _fpct_array(work)
    sf_arr = _to_f64(_col_or_empty(work, "sf", dtype="float64"))

    valid_hk = hk_codes >= 0
    gpref_wet_n = np.where(active & valid_hk, 0.0, np.nan)
    gpref_wet_wr = np.full(n, np.nan, dtype=np.float64)
    gpref_wet_fpct_delta = np.full(n, np.nan, dtype=np.float64)
    gpref_wet_sf_delta = np.full(n, np.nan, dtype=np.float64)

    # Strictly known wet (1) or dry (0) settled prior starts; 'bilinmiyor' (NaN) excluded from both!
    ev_mask = settled & valid_hk & np.isfinite(going_wet)
    q_mask = active & valid_hk
    if ev_mask.any() and q_mask.any():
        ev_rows = np.flatnonzero(ev_mask)
        q_rows = np.flatnonzero(q_mask)

        gw_ev = going_wet[ev_rows]
        fin_ev = fin[ev_rows]
        fp_ev = fpct_arr[ev_rows]
        sf_ev = sf_arr[ev_rows]

        is_w = gw_ev == 1.0
        is_d = gw_ev == 0.0
        ok_fp = np.isfinite(fp_ev)
        ok_sf = np.isfinite(sf_ev)

        ev_arrays = [
            is_w.astype(np.float64),
            (is_w & (fin_ev == 1.0)).astype(np.float64),
            (is_w & ok_fp).astype(np.float64),
            np.where(is_w & ok_fp, fp_ev, 0.0),
            (is_d & ok_fp).astype(np.float64),
            np.where(is_d & ok_fp, fp_ev, 0.0),
            (is_w & ok_sf).astype(np.float64),
            np.where(is_w & ok_sf, sf_ev, 0.0),
            (is_d & ok_sf).astype(np.float64),
            np.where(is_d & ok_sf, sf_ev, 0.0),
        ]

        # [0, day_off) strictly excludes same-day and future events (< D)
        (
            w_st,
            w_win,
            w_fcnt,
            w_fsum,
            d_fcnt,
            d_fsum,
            w_scnt,
            w_ssum,
            d_scnt,
            d_ssum,
        ) = _range_window_agg(
            hk_codes[ev_rows],
            day_off[ev_rows],
            ev_arrays,
            hk_codes[q_rows],
            np.zeros(len(q_rows), dtype=np.int64),
            day_off[q_rows],
            stride,
        )

        gpref_wet_n[q_rows] = w_st

        has_w = w_st >= 1.0
        if has_w.any():
            gpref_wet_wr[q_rows[has_w]] = (w_win[has_w] + GPREF_WR_PRIOR_W) / (w_st[has_w] + GPREF_WR_PRIOR_N)

        has_fp = (w_fcnt >= 1.0) & (d_fcnt >= 1.0)
        if has_fp.any():
            nw = w_fcnt[has_fp]
            nd = d_fcnt[has_fp]
            neff = (nw * nd) / (nw + nd)
            mw = w_fsum[has_fp] / nw
            md = d_fsum[has_fp] / nd
            # Positive = better (lower) finish pct on wet track vs dry track
            gpref_wet_fpct_delta[q_rows[has_fp]] = (md - mw) * (neff / (neff + GPREF_FPCT_PRIOR_K))

        has_sf = (w_scnt >= 1.0) & (d_scnt >= 1.0)
        if has_sf.any():
            nws = w_scnt[has_sf]
            nds = d_scnt[has_sf]
            neff_s = (nws * nds) / (nws + nds)
            mws = w_ssum[has_sf] / nws
            mds = d_ssum[has_sf] / nds
            # Positive = higher speed figure on wet track vs dry track
            gpref_wet_sf_delta[q_rows[has_sf]] = (mws - mds) * (neff_s / (neff_s + GPREF_SF_PRIOR_K))

    gpref_wet_x_fpct_delta = np.where(
        active & np.isfinite(going_wet) & np.isfinite(gpref_wet_fpct_delta),
        going_wet * gpref_wet_fpct_delta,
        np.nan,
    )
    gpref_wet_x_sf_delta = np.where(
        active & np.isfinite(going_wet) & np.isfinite(gpref_wet_sf_delta),
        going_wet * gpref_wet_sf_delta,
        np.nan,
    )
    gpref_wet_x_fpct_rel = _fast_race_active_rel(
        ctx["race_codes"],
        ctx["n_races"],
        gpref_wet_x_fpct_delta,
        active,
    )

    return {
        "gpref_wet_n": gpref_wet_n[inv],
        "gpref_wet_wr": gpref_wet_wr[inv],
        "gpref_wet_fpct_delta": gpref_wet_fpct_delta[inv],
        "gpref_wet_sf_delta": gpref_wet_sf_delta[inv],
        "gpref_wet_x_fpct_delta": gpref_wet_x_fpct_delta[inv],
        "gpref_wet_x_sf_delta": gpref_wet_x_sf_delta[inv],
        "gpref_wet_x_fpct_rel": gpref_wet_x_fpct_rel[inv],
    }


def attach_GPREF(df, v5_tables=None):
    """Attach GPREF block: horse prior wet vs dry track preference and race interaction."""
    if len(df) == 0:
        return _empty_result(df, GPREF_COLS)
    ctx = _build_v11_ctx(df, _BLOCK_NEEDED_COLS["GPREF"], v5_tables=v5_tables)
    return _attach_cols(df, _compute_GPREF(ctx))


_BLOCK_COMPUTERS = {
    "GOING": _compute_GOING,
    "WX": _compute_WX,
    "GPREF": _compute_GPREF,
}


def attach_v11(df, blocks=V11_CANDIDATE_BLOCKS, v5_tables=None):
    """Attach selected v11 pre-race feature blocks (`GOING`, `WX`, `GPREF`) in one shared pass."""
    blk_list = tuple(blocks) if not isinstance(blocks, str) else (blocks,)
    for blk in blk_list:
        if blk not in V11_BLOCK_COLS:
            raise ValueError(f"Geçersiz V11 bloğu: {blk!r}. Geçerliler: {tuple(V11_BLOCK_COLS)}")
    if not blk_list:
        return df.copy()
    if len(df) == 0:
        cols = [c for b in blk_list for c in V11_BLOCK_COLS[b]]
        return _empty_result(df, cols)

    needed = set()
    for blk in blk_list:
        needed.update(_BLOCK_NEEDED_COLS[blk])
    ctx = _build_v11_ctx(df, tuple(sorted(needed)), v5_tables=v5_tables)
    all_cols = {}
    for blk in blk_list:
        all_cols.update(_BLOCK_COMPUTERS[blk](ctx))
    return _attach_cols(df, all_cols)


def get_v11_cols(v11_blocks=V11_CANDIDATE_BLOCKS, with_program=False):
    """Return ordered feature column list = V10_CONFIG (`v10_hlb`) + selected v11 blocks."""
    blk_list = tuple(v11_blocks) if not isinstance(v11_blocks, str) else (v11_blocks,)
    for blk in blk_list:
        if blk not in V11_BLOCK_COLS:
            raise ValueError(f"Geçersiz V11 bloğu: {blk!r}. Geçerliler: {tuple(V11_BLOCK_COLS)}")
    if with_program:
        cols = get_v10_cols(v10_blocks=V10_BLOCKS, with_program=True)
    else:
        cols = list(V10_CONFIG["feature_cols"])
    for blk in blk_list:
        cols.extend(V11_BLOCK_COLS[blk])
    return cols


__all__ = [
    "GOING_COLS",
    "GPREF_COLS",
    "SMOOTHING_CONSTANTS",
    "V11_BLOCK_COLS",
    "V11_CANDIDATE_BLOCKS",
    "WX_COLS",
    "attach_GOING",
    "attach_GPREF",
    "attach_WX",
    "attach_v11",
    "extract_turf_going_num",
    "get_v11_cols",
    "load_v11_tables",
]
