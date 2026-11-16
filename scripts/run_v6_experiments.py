"""Walk-forward experimentation, Stage A/B/C gating, and report generator for Model v6."""
import argparse
import datetime
import gc
import os
from pathlib import Path
import sqlite3
import sys
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.backtest import load_runners_from_db
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5, load_v5_tables
from ganyan.features_v6 import (
    V6_BLOCK_COLS,
    attach_v6,
    compute_yearly_source_coverage,
    load_v6_tables,
)
from ganyan.model_v6 import (
    CANDIDATE_VARIANTS,
    DIAGNOSTIC_SPECS,
    E1_E2_POOL,
    E1_TO_E4_POOL,
    STAGE_A_YEARS,
    STAGE_B_YEARS,
    STAGE_C_YEARS,
    VARIANT_SPECS,
    IsotonicRaceCalibrator,
    RaceTemperatureCalibrator,
    bootstrap_mean_ci,
    compute_edge_buckets,
    compute_ev_bet_stats,
    compute_top1_roi,
    compute_topk_coverage,
    config_digest,
    evaluate_stage_b_gate,
    fit_predict_v6,
    pin_v6_config_in_source,
    resolve_variant_config,
)

REF_END_DEFAULT = "2017-01-01"
CAL_WARMUP_YEAR = 2016
SMOKE_TEST_YEAR = 2021
SMOKE_SAMPLE_FRAC = 0.20
SMOKE_SAMPLE_SEED = 42
SMOKE_CANDIDATE = "E4_gc"


def _open_ro_db(db_path):
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {db_path}")
    db_uri = f"{p.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.Error:
        pass
    return conn


def _drop_unfinished_races(runners_df):
    """Exclude races where no active (non-scratched) runner has a valid `finish` position."""
    if len(runners_df) == 0:
        return runners_df
    scr = pd.to_numeric(runners_df["scratched"], errors="coerce").fillna(0) if "scratched" in runners_df.columns else 0
    fin = pd.to_numeric(runners_df["finish"], errors="coerce")
    act_fin = (scr == 0) & fin.notna()
    race_ok = act_fin.groupby(runners_df["race_id"], sort=False).transform("any")
    return runners_df[race_ok].copy()


def _eval_filter_mask(df):
    """Canonical walk-forward evaluation race filter (vectorized equivalent of `run_v5_backtest._eval_filter_mask`)."""
    rids = df["race_id"]
    agf_all = df["agf_close"].notna().groupby(rids, sort=False).transform("all")
    gny_all = df["ganyan"].notna().groupby(rids, sort=False).transform("all")
    one_win = df["win"].groupby(rids, sort=False).transform("sum") == 1
    return agf_all & gny_all & one_win & (df["field"] >= 4)


def _cache_file_path(cache_dir, variant, digest, year, smoke=False):
    prefix = "smoke_pred" if smoke else "pred"
    return os.path.join(str(cache_dir), f"{prefix}_{variant}_{digest}_{int(year)}.pkl")


def _save_pickle_atomic(df_obj, target_path):
    parent = os.path.dirname(str(target_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{target_path}.tmp.{os.getpid()}"
    df_obj.to_pickle(tmp_path)
    os.replace(tmp_path, target_path)


def _align_cached_preds(te_df, cached_df):
    """Align cached `(race_id, horse_key, p)` onto `te_df`; return 1D float64 array or `None`."""
    if not isinstance(cached_df, pd.DataFrame) or not {"race_id", "horse_key", "p"}.issubset(cached_df.columns):
        return None
    if len(te_df) == 0:
        return np.zeros(0, dtype=np.float64)
    left = pd.DataFrame(
        {
            "_rid": te_df["race_id"].astype("string").to_numpy(),
            "_hk": te_df["horse_key"].astype("string").to_numpy(),
        }
    )
    right = cached_df[["race_id", "horse_key", "p"]].copy()
    right["_rid"] = right["race_id"].astype("string")
    right["_hk"] = right["horse_key"].astype("string")
    right = right.drop_duplicates(subset=["_rid", "_hk"], keep="last")[["_rid", "_hk", "p"]]
    merged = left.merge(right, on=["_rid", "_hk"], how="left")
    p_arr = pd.to_numeric(merged["p"], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
    if len(p_arr) != len(te_df) or not np.all(np.isfinite(p_arr)):
        return None
    return p_arr


def _sample_smoke_train(tr_df, frac=SMOKE_SAMPLE_FRAC, seed=SMOKE_SAMPLE_SEED):
    """Deterministically sample `frac` of training rows while guaranteeing both classes remain."""
    n = len(tr_df)
    if n <= 10:
        return tr_df
    k = max(10, int(round(n * float(frac))))
    k = min(k, n)
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(n, size=k, replace=False))
    sub = tr_df.iloc[idx]
    if (sub["finish"] == 1).nunique() < 2 and (tr_df["finish"] == 1).nunique() >= 2:
        win_pos = np.flatnonzero((tr_df["finish"] == 1).to_numpy())
        lose_pos = np.flatnonzero((tr_df["finish"] != 1).to_numpy())
        extra = np.unique(np.r_[idx[:-2], win_pos[0], lose_pos[0]])
        sub = tr_df.iloc[np.sort(extra)]
    return sub


def _build_history_frame(
    runners_df,
    v5_tables,
    v6_tables,
    history_start,
    ref_end=REF_END_DEFAULT,
    v6_blocks=(),
    max_date=None,
):
    """Build single leak-free feature DataFrame starting at `history_start` (low-memory sequential helper)."""
    start_ts = pd.Timestamp(history_start)
    mask = runners_df["date"] >= start_ts
    if max_date is not None:
        mask = mask & (runners_df["date"] <= pd.Timestamp(max_date))
    r_sub = runners_df[mask].copy()
    if len(r_sub) == 0:
        # Fallback if synthetic fixture only has dates after/before boundary
        r_sub = runners_df.copy() if max_date is None else runners_df[runners_df["date"] <= pd.Timestamp(max_date)].copy()

    ext_df = v5_tables["ext"]
    w_df = v5_tables["workouts"]
    if len(w_df) > 0:
        w_mask = w_df["date"] >= start_ts
        if max_date is not None:
            w_mask = w_mask & (w_df["date"] <= pd.Timestamp(max_date))
        w_sub = w_df[w_mask].copy()
    else:
        w_sub = w_df
    v5_sub = {"ext": ext_df, "workouts": w_sub}

    df = build_features(r_sub, ref_end=ref_end)
    del r_sub
    df = attach_v5(df, v5_sub, blocks=("S", "G", "R"))
    if v6_blocks:
        df = attach_v6(df, v6_tables, blocks=tuple(v6_blocks))

    df["_year"] = df["date"].dt.year.astype(np.int32)
    df["_has_race_win"] = df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    df["_is_eval"] = _eval_filter_mask(df)
    return df


def _race_winner_lls(te_df, p_arr):
    """Return 1D array of winner `-log(clip(p, 1e-6))` ordered by race appearance in `te_df`."""
    win_mask = (te_df["win"].to_numpy(dtype=np.float64) == 1.0)
    p_w = np.clip(np.asarray(p_arr, dtype=np.float64)[win_mask], 1e-6, None)
    return -np.log(p_w)


class _ProgressTracker:
    """Single-line stdout progress logger with wall-clock time, duration, ΔLL, and ETA."""

    def __init__(self, total_planned_steps):
        self.total_steps = max(1, int(total_planned_steps))
        self.done_steps = 0
        self.fit_durations = []

    def add_steps(self, extra_steps):
        self.total_steps = max(self.done_steps + 1, self.total_steps + int(extra_steps))

    def log_step(self, variant, year, elapsed_s, dll_val, from_cache=False):
        self.done_steps += 1
        if not from_cache and elapsed_s > 0.05:
            self.fit_durations.append(float(elapsed_s))
        rem = max(0, self.total_steps - self.done_steps)
        avg_s = float(np.mean(self.fit_durations)) if self.fit_durations else float(elapsed_s)
        eta_s = rem * avg_s
        hms = datetime.datetime.now().strftime("%H:%M:%S")
        dll_str = f"{dll_val:+.4f}" if np.isfinite(dll_val) else "n/a"
        cache_tag = " [onbellek]" if from_cache else ""
        print(
            f"[{hms}] varyant={variant} yil={int(year)} sure={elapsed_s:.1f}sn "
            f"dLL={dll_str} kalan={eta_s:.0f}sn{cache_tag}",
            flush=True,
        )


def _predict_base_year(
    df_hist,
    eval_year_df,
    resolved_cfg,
    year,
    cache_dir,
    smoke=False,
):
    """Fit or load cached `(variant, digest, year)` HGB prediction for `year`; returns `(p_arr, elapsed_s, from_cache)`."""
    t0 = time.perf_counter()
    variant = resolved_cfg["variant"]
    digest = config_digest(resolved_cfg)
    c_path = _cache_file_path(cache_dir, variant, digest, year, smoke=smoke)

    if os.path.exists(c_path):
        try:
            cached_df = pd.read_pickle(c_path)
            aligned = _align_cached_preds(eval_year_df, cached_df)
            if aligned is not None:
                return aligned, time.perf_counter() - t0, True
        except Exception:
            pass

    eval_col = df_hist["_is_eval"] if "_is_eval" in df_hist.columns else _eval_filter_mask(df_hist)
    te_hist = df_hist[(df_hist["_year"] == int(year)) & eval_col]
    if len(te_hist) == 0:
        return None, time.perf_counter() - t0, False

    train_start_ts = pd.Timestamp(f"{int(resolved_cfg['train_start_year']):04d}-01-01")
    y_start_ts = pd.Timestamp(f"{int(year):04d}-01-01")
    tr_mask = (
        (df_hist["date"] >= train_start_ts)
        & (df_hist["date"] < y_start_ts)
        & df_hist["win"].notna()
        & df_hist["_has_race_win"]
    )
    if resolved_cfg["require_agf"]:
        tr_mask = tr_mask & df_hist["agf_share"].notna()

    tr_df = df_hist[tr_mask]
    if smoke:
        tr_df = _sample_smoke_train(tr_df, frac=SMOKE_SAMPLE_FRAC, seed=SMOKE_SAMPLE_SEED)

    if len(tr_df) == 0 or (tr_df["finish"] == 1).nunique() < 2:
        return None, time.perf_counter() - t0, False

    p_raw_hist = fit_predict_v6(
        tr_df,
        te_hist,
        resolved_cfg["feature_cols"],
        hgb_params=resolved_cfg["hgb_params"],
        seeds=resolved_cfg["seeds"],
        temporal_val_frac=resolved_cfg.get("temporal_val_frac"),
    )

    save_df = pd.DataFrame(
        {
            "race_id": te_hist["race_id"].to_numpy(),
            "horse_key": te_hist["horse_key"].to_numpy(),
            "p": p_raw_hist,
        }
    )
    aligned = _align_cached_preds(eval_year_df, save_df)
    if aligned is None:
        return None, time.perf_counter() - t0, False

    canonical_save = pd.DataFrame(
        {
            "race_id": eval_year_df["race_id"].to_numpy(),
            "horse_key": eval_year_df["horse_key"].to_numpy(),
            "p": aligned,
        }
    )
    _save_pickle_atomic(canonical_save, c_path)
    return aligned, time.perf_counter() - t0, False


def _predict_calibrated_year(
    eval_by_year,
    base_preds_by_year,
    resolved_cfg,
    year,
    cache_dir,
    smoke=False,
):
    """Fit walk-forward calibrator strictly on years `< year` and predict `year`."""
    t0 = time.perf_counter()
    variant = resolved_cfg["variant"]
    digest = config_digest(resolved_cfg)
    c_path = _cache_file_path(cache_dir, variant, digest, year, smoke=smoke)
    te_y = eval_by_year.get(int(year))
    if te_y is None or len(te_y) == 0:
        return None, 0.0, False, None

    p_base_y = base_preds_by_year.get(int(year))
    if p_base_y is None:
        return None, 0.0, False, None

    if os.path.exists(c_path):
        try:
            cached_df = pd.read_pickle(c_path)
            aligned = _align_cached_preds(te_y, cached_df)
            if aligned is not None:
                cal_meta = None
                if {"cal_param", "fit_years", "fit_races"}.issubset(cached_df.columns) and len(cached_df) > 0:
                    cal_meta = {
                        "variant": variant,
                        "base_variant": resolved_cfg.get("calibrated_from", ""),
                        "method": resolved_cfg["calibration"],
                        "year": int(year),
                        "fit_years": str(cached_df["fit_years"].iloc[0]),
                        "fit_races": int(cached_df["fit_races"].iloc[0]),
                        "param": float(cached_df["cal_param"].iloc[0]),
                    }
                return aligned, time.perf_counter() - t0, True, cal_meta
        except Exception:
            pass

    prior_years = sorted(py for py in base_preds_by_year if int(py) < int(year) and base_preds_by_year[py] is not None)
    prior_p = []
    prior_rids = []
    prior_win = []
    fit_races = 0
    used_years = []
    for py in prior_years:
        ev_py = eval_by_year.get(int(py))
        if ev_py is None or len(ev_py) == 0:
            continue
        prior_p.append(base_preds_by_year[py])
        prior_rids.append(ev_py["race_id"].to_numpy())
        prior_win.append((ev_py["win"].to_numpy(dtype=np.float64) == 1.0).astype(np.float64))
        fit_races += int(ev_py["race_id"].nunique())
        used_years.append(int(py))

    method = resolved_cfg["calibration"]
    if prior_p:
        all_p = np.concatenate(prior_p)
        all_rids = np.concatenate(prior_rids)
        all_win = np.concatenate(prior_win)
        if method == "temperature":
            cal = RaceTemperatureCalibrator(clip_min=1e-6).fit(all_p, all_rids, all_win)
            p_cal = cal.predict(p_base_y, te_y["race_id"].to_numpy())
            param_val = float(cal.gamma)
        elif method == "isotonic":
            cal = IsotonicRaceCalibrator(clip_min=1e-6).fit(all_p, all_win)
            p_cal = cal.predict(p_base_y, te_y["race_id"].to_numpy())
            param_val = 1.0 if cal.iso_ is not None else np.nan
        else:
            raise ValueError(f"Unknown calibration method: {method!r}")
    else:
        p_cal = np.asarray(p_base_y, dtype=np.float64).copy()
        param_val = 1.0

    fit_years_str = ",".join(str(u) for u in used_years) if used_years else "—"
    save_df = pd.DataFrame(
        {
            "race_id": te_y["race_id"].to_numpy(),
            "horse_key": te_y["horse_key"].to_numpy(),
            "p": p_cal,
            "cal_param": param_val,
            "fit_years": fit_years_str,
            "fit_races": int(fit_races),
        }
    )
    _save_pickle_atomic(save_df, c_path)
    cal_meta = {
        "variant": variant,
        "base_variant": resolved_cfg.get("calibrated_from", ""),
        "method": method,
        "year": int(year),
        "fit_years": fit_years_str,
        "fit_races": int(fit_races),
        "param": float(param_val) if np.isfinite(param_val) else np.nan,
    }
    return p_cal, time.perf_counter() - t0, False, cal_meta


def _summarize_period_metrics(eval_df_period, preds_map_period, variants_order, base_key="E0"):
    """Compute LL, ΔLL vs `base_key` (with 2000-sample paired bootstrap CI), top1/top2/top3, and yearly ΔLL."""
    if len(eval_df_period) == 0:
        return [], {}

    work = eval_df_period[["race_id", "_year", "win", "agf_share"]].copy()
    all_keys = ["B0"] + [v for v in variants_order if v in preds_map_period]
    work["p_B0"] = work["agf_share"].to_numpy(dtype=np.float64)
    for v in variants_order:
        if v in preds_map_period:
            work[f"p_{v}"] = preds_map_period[v]

    for k in all_keys:
        col = f"p_{k}"
        valid = work[col].notna()
        rk = pd.Series(np.nan, index=work.index, dtype="float64")
        if valid.any():
            rk.loc[valid] = work.loc[valid].groupby("race_id", sort=False)[col].rank(ascending=False, method="first")
        work[f"rk_{k}"] = rk

    winners = work[work["win"] == 1].copy().reset_index(drop=True)
    for k in all_keys:
        p_w = winners[f"p_{k}"].to_numpy(dtype=np.float64)
        rk_w = winners[f"rk_{k}"].to_numpy(dtype=np.float64)
        ok = np.isfinite(p_w)
        winners[f"ll_{k}"] = np.where(ok, -np.log(np.clip(p_w, 1e-6, None)), np.nan)
        winners[f"top1_{k}"] = np.where(ok, (rk_w <= 1.0).astype(np.float64), np.nan)
        winners[f"top2_{k}"] = np.where(ok, (rk_w <= 2.0).astype(np.float64), np.nan)
        winners[f"top3_{k}"] = np.where(ok, (rk_w <= 3.0).astype(np.float64), np.nan)

    rows = []
    race_dll_by_var = {}
    years_present = sorted(int(y) for y in winners["_year"].unique())

    for k in all_keys:
        ll_col = f"ll_{k}"
        if ll_col not in winners.columns:
            continue
        ok_m = winners[ll_col].notna()
        if f"ll_{base_key}" in winners.columns:
            ok_m = ok_m & winners[f"ll_{base_key}"].notna()
        sub = winners[ok_m]
        if len(sub) == 0:
            continue

        ll_v = sub[ll_col].to_numpy(dtype=np.float64)
        t1 = float(sub[f"top1_{k}"].mean())
        t2 = float(sub[f"top2_{k}"].mean())
        t3 = float(sub[f"top3_{k}"].mean())

        if k == base_key or f"ll_{base_key}" not in sub.columns:
            d_e0, lo_e0, hi_e0 = 0.0, 0.0, 0.0
            d_arr = np.zeros(len(sub), dtype=np.float64)
        else:
            d_arr = ll_v - sub[f"ll_{base_key}"].to_numpy(dtype=np.float64)
            d_e0, lo_e0, hi_e0 = bootstrap_mean_ci(d_arr, n_boot=2000, seed=0)
        race_dll_by_var[k] = d_arr

        if k == "B0" or "ll_B0" not in sub.columns:
            d_b0, lo_b0, hi_b0 = 0.0, 0.0, 0.0
        else:
            d_b0_arr = ll_v - sub["ll_B0"].to_numpy(dtype=np.float64)
            d_b0, lo_b0, hi_b0 = bootstrap_mean_ci(d_b0_arr, n_boot=2000, seed=0)

        yearly_dll = {}
        yearly_ll = {}
        sub_yr = sub["_year"].to_numpy(dtype=np.int32)
        base_ll_all = sub[f"ll_{base_key}"].to_numpy(dtype=np.float64) if f"ll_{base_key}" in sub.columns else ll_v
        for y in years_present:
            ym = sub_yr == y
            if np.any(ym):
                yearly_ll[y] = float(ll_v[ym].mean())
                yearly_dll[y] = 0.0 if k == base_key else float((ll_v[ym] - base_ll_all[ym]).mean())

        neg_years = sum(1 for v_d in yearly_dll.values() if v_d < 0.0)
        rows.append(
            {
                "variant": k,
                "races": int(len(sub)),
                "ll": float(ll_v.mean()),
                "top1": t1,
                "top2": t2,
                "top3": t3,
                "dll_e0": float(d_e0),
                "dll_e0_lo": float(lo_e0),
                "dll_e0_hi": float(hi_e0),
                "dll_b0": float(d_b0),
                "dll_b0_lo": float(lo_b0),
                "dll_b0_hi": float(hi_b0),
                "neg_years": int(neg_years),
                "total_years": int(len(yearly_dll)),
                "yearly_ll": yearly_ll,
                "yearly_dll": yearly_dll,
            }
        )
    return rows, race_dll_by_var


def _concat_year_preds(eval_by_year, preds_by_var_year, years_seq, variants_seq):
    """Concatenate `eval_by_year[y]` and aligned `preds_by_var_year[v][y]` over `years_seq`."""
    present_years = [int(y) for y in years_seq if int(y) in eval_by_year and len(eval_by_year[int(y)]) > 0]
    if not present_years:
        return pd.DataFrame(), {}
    eval_cat = pd.concat([eval_by_year[y] for y in present_years], ignore_index=True)
    preds_cat = {}
    for v in variants_seq:
        v_map = preds_by_var_year.get(v, {})
        if all((y in v_map and v_map[y] is not None) for y in present_years):
            preds_cat[v] = np.concatenate([v_map[y] for y in present_years])
    return eval_cat, preds_cat


def _fmt_dll_ci(d, lo, hi, is_self=False):
    if is_self or not np.isfinite(d):
        return "—"
    return f"`{d:+.4f}` (`{lo:+.4f}`…`{hi:+.4f}`)"


def _fmt_pct_opt(val):
    if val is None or not np.isfinite(val):
        return "—"
    return f"{val:.1%}"


def format_v6_report(
    *,
    smoke,
    meta,
    coverage_df,
    v6_fill_rows,
    resolved_configs,
    candidate_count,
    stage_a_rows,
    stage_a_years,
    diag_a_row,
    selected_top2,
    stage_b_rows,
    stage_b_years,
    stage_b_yearly_detail,
    gate_results,
    winner_variant,
    stage_c_rows,
    stage_c_years,
    cal_param_rows,
    winner_yearly_rows,
    winner_ev_tables,
    winner_edge_tables,
):
    title = (
        "# Ganyan Model v6 — Duman Testi Raporu (--smoke)"
        if smoke
        else "# Ganyan Model v6 — Deneyler, Seçim/Doğrulama Kapısı ve Değer Bahsi Raporu"
    )
    lines = [
        title,
        "",
        "> **Uyarı 1 (Kapanış AGF):** Tarihsel değerlendirmede kapanış AGF (`agf_close`) kullanılır; canlıda koşudan önce alınan AGF daha az bilgi içerir.",
        f"> **Uyarı 2 (Çoklu Karşılaştırma):** Bu deney serisinde `E0` (`B1_SGR`) tabanına karşı toplam **{candidate_count} V6 aday yapılandırması** (+ 1 geçmiş kesme kontrolü) denenmiştir. Seçim yalnız Aşama A (`2017–2021`) üzerinde yapılmış, Aşama B (`2022–2025`) sabit kapısına yalnız en iyi 2 aday sokulmuştur.",
        "",
        "## 1. Veri Özeti ve Yıllık Kaynak Doluluk Oranları",
        "",
        f"- **Veritabanı:** `{meta['db_path']}` (salt-okunur)",
        f"- **Veri Aralığı (DB):** `{meta['db_min_date']}` … `{meta['db_max_date']}`",
        f"- **Toplam Sonuçlanmış Koşucu / Koşu:** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Denenen V6 Aday Varyant Sayısı:** `{candidate_count}` (`E0` taban hariç)",
        f"- **Kip:** `{'Duman testi (--smoke: yalnız 2021, %20 eğitim örneği)' if smoke else 'Tam ileri-yürüyen koşu (Aşama A 2017–2021 → Aşama B 2022–2025 → Aşama C 2026 bilgi)'}`",
        f"- **Değerlendirme Kümesi Koşu Sayıları:** Aşama A `{meta['stage_a_races']:,}` koşu | Aşama B `{meta['stage_b_races']:,}` koşu | Aşama C (2026 bilgi) `{meta['stage_c_races']:,}` koşu",
        "- **AGF'siz Yıllar Notu (`2005–2014`):** `agf_close` yalnız `2015→` döneminde doludur; `2005–2014` satırları eğitime eklendiğinde (`E1b`) B1 tipi AGF özellikleri (`agf_share`, `log_agf`) `NaN` kalır ve `HistGradientBoostingClassifier` bunları doğal `NaN` dallanmasıyla işler. Ayrıca `liderform` galop verisi `2015-10→` başladığından `2005–2014`'te galop sayacı sütunları (`g_n14`, `g_n30`) sıfır, süre sütunları (`g_days_last`, `g_last_d400`) `NaN` olur.",
        "- **v5 Geçmiş Penceresi Notu:** `scripts/run_v5_backtest.py` ve `scripts/forward_v5.py`, `--start-year 2015` süzgecini yalnız eğitim satırlarına (`tr`) uygulamış, özellik inşasına (`build_features` + `attach_v5`) tüm veritabanını zaten beslemiştir (`V5.md`'de `2006-03-04→`). Bu nedenle `E0` v5'in gerçek `2006-03-04→` geçmiş penceresini korur, `E1a` bugün tamamlanan `2005-01-01→` tam geçmişi sınar, `Ref_2015_Gecmis` kontrol satırı ise `2005–2014` özellik geçmişi tamamen kesildiğinde oluşan kaybı ölçer.",
        "",
        "### Yıllık Kaynak ve Tablo Doluluğu (`2005→` DB Sayımı)",
        "",
        "| Yıl | Koşu | Koşucu | AGF % | Süre (`time_s`) % | Kendi Hız (`sfa`) % | YB Hız Kaynak % | YB Hız Öz. % | Galop Kayıt | Galop Öz. % | Elo≠0 % | `fark` % | `gec_cikis` % | `son800` % | `prize_1` % | `pools` Gün | `steward` Satır |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if len(coverage_df) > 0:
        for _, cr in coverage_df.iterrows():
            lines.append(
                f"| {int(cr['year'])} | {int(cr['races'])} | {int(cr['runners'])} | "
                f"{cr['agf_pct']:.1%} | {cr['time_pct']:.1%} | {_fmt_pct_opt(cr['sfa_feat_pct'])} | "
                f"{cr['yb_src_pct']:.1%} | {_fmt_pct_opt(cr['yb_feat_pct'])} | "
                f"{int(cr['workout_rows'])} | {_fmt_pct_opt(cr['galop_feat_pct'])} | "
                f"{_fmt_pct_opt(cr['elo_nz_pct'])} | {cr['re_fark_pct']:.1%} | {cr['re_gec_pct']:.1%} | "
                f"{cr['rce_s800_pct']:.1%} | {cr['rce_prize_pct']:.1%} | "
                f"{int(cr['pool_days'])} | {int(cr['steward_rows'])} |"
            )

    if v6_fill_rows:
        lines += [
            "",
            "### Yeni E4 Özellik Grupları Doluluk Oranları",
            "",
            "| Grup | Sütun | Tüm Veri Dolu (%) | Değerlendirme Kümesi Dolu (%) | Değerlendirme Sıfır-Dışı (%) |",
            "|---|---|---:|---:|---:|",
        ]
        for fr in v6_fill_rows:
            lines.append(
                f"| `{fr['block']}` | `{fr['col']}` | {fr['all_fill']:.1%} | {fr['eval_fill']:.1%} | {fr['eval_nonzero']:.1%} |"
            )

    lines += [
        "",
        "## 2. Denenen Varyantların Yapılandırma Özeti",
        "",
        "| Varyant | Aile | Öz. Geçmişi | Eğitim Baş. | Ek Blok | HGB (`iter/lr/leaf/min/l2/es`) | Tohum | Kalibrasyon | Özet |",
        "|---|---|---|---:|---|---|---|---|---|",
    ]
    for v_name, cfg in resolved_configs.items():
        hp = cfg["hgb_params"]
        es_lbl = f"tv={cfg['temporal_val_frac']}" if cfg.get("temporal_val_frac") else str(hp.get("early_stopping"))
        hp_str = (
            f"`{hp['max_iter']}/{hp['learning_rate']}/{hp['max_leaf_nodes']}/"
            f"{hp['min_samples_leaf']}/{hp['l2_regularization']}/{es_lbl}`"
        )
        blk_str = ",".join(cfg["extra_blocks"]) if cfg["extra_blocks"] else "—"
        seed_str = ",".join(str(s) for s in cfg["seeds"])
        cal_str = cfg["calibration"] or "—"
        if cfg.get("calibrated_from"):
            cal_str = f"{cal_str}←`{cfg['calibrated_from']}`"
        elif cfg.get("ensemble_from"):
            seed_str = f"{seed_str} (←`{cfg['ensemble_from']}`)"
        lines.append(
            f"| `{v_name}` | {cfg['family']} | `{cfg['history_start']}` | {cfg['train_start_year']} | "
            f"`{blk_str}` | {hp_str} | `{seed_str}` | {cal_str} | {cfg['description']} |"
        )

    # Stage A
    a_yrs_lbl = f"{min(stage_a_years)}–{max(stage_a_years)}" if stage_a_years else "—"
    lines += [
        "",
        f"## 3. Aşama A — Seçim Kümesi Sonuçları (`{a_yrs_lbl}`)",
        "",
        "| Sıra | Varyant | Aile | Koşu | Log-Loss | ΔLL vs E0 (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 | Seçim Durumu |",
        "|---:|---|---|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    rank_counter = 0
    for r in stage_a_rows:
        v = r["variant"]
        if v == "B0":
            fam = "Piyasa"
            rk_str = "—"
            st_str = "Saf AGF referans"
        elif v == "E0":
            fam = "E0"
            rk_str = "0"
            st_str = "Taban (B1_SGR)"
        else:
            rank_counter += 1
            fam = resolved_configs.get(v, {}).get("family", "—")
            rk_str = str(rank_counter)
            st_str = "**Aşama B'ye Geçti**" if v in selected_top2 else "Elendi"
        lines.append(
            f"| {rk_str} | `{v}` | {fam} | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'E0'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {st_str} |"
        )

    if diag_a_row is not None:
        lines.append(
            f"| — | `{diag_a_row['variant']}` | Kontrol | {diag_a_row['races']} | {diag_a_row['ll']:.4f} | "
            f"{_fmt_dll_ci(diag_a_row['dll_e0'], diag_a_row['dll_e0_lo'], diag_a_row['dll_e0_hi'])} | "
            f"{diag_a_row['neg_years']}/{diag_a_row['total_years']} | "
            f"{diag_a_row['top1']:.2%} | {diag_a_row['top2']:.2%} | {diag_a_row['top3']:.2%} | Bilgi (2015→ geçmiş kontrolü) |"
        )

    if stage_a_years and stage_a_rows:
        yr_hdr = " | ".join(str(y) for y in stage_a_years)
        yr_sep = " | ".join("---:" for _ in stage_a_years)
        lines += [
            "",
            "### Aşama A Yıllık ΔLL(varyant − E0) Matrisi",
            "",
            f"| Varyant | {yr_hdr} | Ort. ΔLL vs E0 |",
            f"|---| {yr_sep} |---:|",
        ]
        all_mat_rows = list(stage_a_rows) + ([diag_a_row] if diag_a_row is not None else [])
        for r in all_mat_rows:
            v = r["variant"]
            if v == "E0":
                cells = [f"{r['yearly_ll'].get(y, np.nan):.4f} (LL)" for y in stage_a_years]
                avg_c = f"{r['ll']:.4f} (LL)"
            else:
                cells = [
                    f"`{r['yearly_dll'][y]:+.4f}`" if y in r["yearly_dll"] else "—"
                    for y in stage_a_years
                ]
                avg_c = f"`{r['dll_e0']:+.4f}`"
            lines.append(f"| `{v}` | " + " | ".join(cells) + f" | {avg_c} |")

    if cal_param_rows:
        lines += [
            "",
            "### İleri-Yürüyen Kalibrasyon Katsayıları (E5)",
            "",
            "| Varyant | Taban | Yöntem | Test Yılı | Uydurma Yılları (`< Y`) | Uydurma Koşu | Parametre (`gamma=1/T` veya izotonik) |",
            "|---|---|---|---:|---|---:|---:|",
        ]
        for cr in cal_param_rows:
            p_txt = f"{cr['param']:.4f} (T={1.0 / cr['param']:.4f})" if cr["method"] == "temperature" and np.isfinite(cr["param"]) else "monoton eğri"
            lines.append(
                f"| `{cr['variant']}` | `{cr['base_variant']}` | {cr['method']} | {cr['year']} | "
                f"{cr['fit_years']} | {cr['fit_races']} | {p_txt} |"
            )

    # Stage B
    lines += [
        "",
        "## 4. Aşama B — Doğrulama Kümesi (`2022–2025`) ve Sabit Kapı Kararı",
        "",
        "- **Sabit Kapı Kuralı:** `ΔLL(aday − E0)` için koşu-eşli bootstrap (2000 tekrar, sabit tohum 0) **%95 GA üst sınırı < 0** VE **4 yılın en az 3'ünde yıllık `ΔLL < 0`**.",
        "",
    ]
    if smoke or not stage_b_rows:
        lines.append("Duman testinde (`--smoke`) yalnız 2021 yılı koşulduğundan Aşama B değerlendirilmedi.")
    else:
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs E0 (%95 GA) | ΔLL vs AGF (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı Kararı |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for r in stage_b_rows:
            v = r["variant"]
            if v == "B0":
                g_txt = "Referans (Saf AGF)"
            elif v == "E0":
                g_txt = "Taban (B1_SGR)"
            else:
                gr = gate_results.get(v, {})
                g_txt = "**GEÇTİ**" if gr.get("passed") else "KALDI"
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'E0'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | "
                f"{r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_txt} |"
            )

        if stage_b_yearly_detail:
            lines += [
                "",
                "### Aşama B Yıllık Ayrıntı (`2022–2025`)",
                "",
                "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs E0 (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
                "|---:|---|---:|---:|---|---:|---:|---:|",
            ]
            for yr_row in stage_b_yearly_detail:
                v = yr_row["variant"]
                lines.append(
                    f"| {yr_row['year']} | `{v}` | {yr_row['races']} | {yr_row['ll']:.4f} | "
                    f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'E0'))} | "
                    f"{yr_row['top1']:.2%} | {yr_row['top2']:.2%} | {yr_row['top3']:.2%} |"
                )

        lines.append("")
        if winner_variant is not None:
            lines.append(
                f"**KAPI SONUCU:** `{winner_variant}` Aşama B sabit kapısını **GEÇTİ** (`V6_CONFIG` olarak sabitlendi)."
            )
        else:
            lines.append("**KAPI SONUCU:** Hiçbir aday sabit kapıyı geçemedi → **V6 yok, B1_SGR kalır** (`V6_CONFIG = None`).")

    # Stage C (2026 info)
    lines += [
        "",
        "## 5. Aşama C — 2026 Bilgi Kümesi *(kilit v5'te tüketildi, temiz test DEĞİL)*",
        "",
        "> **Etiket:** 2026 kilitli testi Model v5'te tek seferlik tüketilmiştir (`docs/V5_KILITLI_SONUC.md`). Bu bölüm yalnız `E0` ve (varsa) kapıyı geçen aday için bilgi amaçlıdır; model seçiminde kullanılmaz.",
        "",
    ]
    if smoke or not stage_c_rows:
        lines.append("Bu koşuda 2026 bilgi kümesi hesaplanmadı.")
    else:
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs E0 (%95 GA) | ΔLL vs AGF (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---:|---:|---:|",
        ]
        for r in stage_c_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'E0'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )

    # Section 6: Selected V6 Configuration & Value-Bet Analysis
    lines += [
        "",
        "## 6. Seçilen Yapılandırma Tanımı ve Değer Bahsi Analizi",
        "",
    ]
    if winner_variant is None:
        lines.append(
            "Aşama B doğrulama kapısını geçen V6 adayı bulunmadığından **V6 yok, B1_SGR kalır** (`ganyan/model_v6.py` içinde `V6_CONFIG = None`). Şartname gereği kapıyı geçmeyen adaylar için değer bahsi iddiası üretilmemiştir."
        )
    else:
        w_cfg = resolved_configs[winner_variant]
        lines += [
            f"### Seçilen Aday (`{winner_variant}`) Tam Tanımı",
            "",
            f"- **Varyant / Aile:** `{winner_variant}` (`{w_cfg['family']}`)",
            f"- **Açıklama:** {w_cfg['description']}",
            f"- **Özellik Geçmişi Başlangıcı:** `{w_cfg['history_start']}` | **Eğitim Başlangıcı:** `{w_cfg['train_start_year']}-01-01` | **AGF Zorunlu:** `{w_cfg['require_agf']}`",
            f"- **Ek Özellik Blokları:** `{w_cfg['extra_blocks']}`",
            f"- **Hiperparametreler:** `{w_cfg['hgb_params']}` | **Zamansal Doğrulama:** `{w_cfg['temporal_val_frac']}`",
            f"- **Tohumlar:** `{w_cfg['seeds']}` | **Kalibrasyon:** `{w_cfg['calibration']}`",
            f"- **Özellik Sayısı (`len(feature_cols)`):** `{len(w_cfg['feature_cols'])}`",
            f"- **Özellik Listesi:** `{', '.join(w_cfg['feature_cols'])}`",
            "",
        ]
        if winner_yearly_rows:
            lines += [
                f"### Yıllık Performans ve İlk-k Kapsama Karşılaştırması (`Saf AGF` vs `E0` vs `{winner_variant}`)",
                "",
                f"| Yıl | Dönem | Koşu | Saf AGF LL (Top1/2/3) | E0 LL (Top1/2/3) | `{winner_variant}` LL (Top1/2/3) | ΔLL (`{winner_variant}` − E0, %95 GA) |",
                "|---:|---|---:|---|---|---|---|",
            ]
            for wyr in winner_yearly_rows:
                lines.append(
                    f"| {wyr['year']} | {wyr['stage']} | {wyr['races']} | "
                    f"{wyr['b0_ll']:.4f} ({wyr['b0_t1']:.1%}/{wyr['b0_t2']:.1%}/{wyr['b0_t3']:.1%}) | "
                    f"{wyr['e0_ll']:.4f} ({wyr['e0_t1']:.1%}/{wyr['e0_t2']:.1%}/{wyr['e0_t3']:.1%}) | "
                    f"{wyr['w_ll']:.4f} ({wyr['w_t1']:.1%}/{wyr['w_t2']:.1%}/{wyr['w_t3']:.1%}) | "
                    f"{_fmt_dll_ci(wyr['dll_e0'], wyr['dll_lo'], wyr['dll_hi'])} |"
                )
            lines.append("")

        if winner_ev_tables:
            lines += [
                "### Değer Bahsi Tablosu (`EV = p_model × nihai ganyan`, 1 TL Sabit Bahis, Gün-Kümeli Bootstrap %95 GA)",
                "",
                "| Dönem | Model | Eşik | Bahis | Kazanma % | ROI | ROI %95 GA | En Büyük 10 Kazanç Hariç Bahis | En Büyük 10 Kazanç Hariç ROI (%95 GA) |",
                "|---|---|---:|---:|---:|---:|---|---:|---|",
            ]
            for period_lbl, model_map in winner_ev_tables.items():
                for m_lbl, ev_df in model_map.items():
                    for _, er in ev_df.iterrows():
                        if int(er["bets"]) == 0:
                            lines.append(f"| {period_lbl} | `{m_lbl}` | `≥{er['ev_min']:.2f}` | 0 | — | — | — | 0 | — |")
                        else:
                            ex_str = (
                                f"`{er['roi_ex_top10']:+.2%}` (`[{er['ci95_ex_low']:+.2%}, {er['ci95_ex_high']:+.2%}]`)"
                                if np.isfinite(er["roi_ex_top10"])
                                else "—"
                            )
                            lines.append(
                                f"| {period_lbl} | `{m_lbl}` | `≥{er['ev_min']:.2f}` | {int(er['bets'])} | "
                                f"{er['win_rate']:.2%} | `{er['roi']:+.2%}` | "
                                f"`[{er['ci95_low']:+.2%}, {er['ci95_high']:+.2%}]` | "
                                f"{int(er['bets_ex_top10'])} | {ex_str} |"
                            )
            lines.append("")

        if winner_edge_tables:
            lines += [
                "### Kenar Kovası (`edge = p_model / p_mkt`) ROI Karşılaştırması (Aşama B `2022–2025`)",
                "",
            ]
            for m_lbl, einfo in winner_edge_tables.items():
                lines += [
                    f"#### `{m_lbl}` Kenar Kovaları",
                    "",
                    "| Kenar Kovası (`p_model / p_mkt`) | Bahis Sayısı | Kazanma % | ROI | ROI %95 GA |",
                    "|---|---:|---:|---:|---:|",
                ]
                for _, br in einfo["buckets"].iterrows():
                    if int(br["bets"]) == 0:
                        lines.append(f"| `{br['bucket']}` | 0 | — | — | — |")
                    else:
                        lines.append(
                            f"| `{br['bucket']}` | {int(br['bets'])} | {br['win_rate']:.2%} | "
                            f"`{br['roi']:+.2%}` | `[{br['ci95_low']:+.2%}, {br['ci95_high']:+.2%}]` |"
                        )
                t1_d = einfo["top1"]
                if int(t1_d["bets"]) > 0:
                    lines.append(
                        f"\n- **Yalnız `{m_lbl}` 1. Tercihi (1 TL):** {int(t1_d['bets'])} bahis, "
                        f"kazanma {t1_d['win_rate']:.2%}, ROI `{t1_d['roi']:+.2%}` "
                        f"(`[{t1_d['ci95_low']:+.2%}, {t1_d['ci95_high']:+.2%}]`)"
                    )
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_v6_experiments(
    db_path="data/ganyan.db",
    out_path="reports/V6.md",
    cache_dir="data/v6_cache",
    smoke=False,
    pin_config=None,
    model_v6_path=None,
):
    """Execute Model v6 staged experiments (or `--smoke`) and write `out_path` Markdown report."""
    smoke = bool(smoke)
    if pin_config is None:
        pin_config = not smoke

    os.makedirs(cache_dir, exist_ok=True)

    conn = _open_ro_db(db_path)
    try:
        runners_df = load_runners_from_db(conn)
        v5_tables = load_v5_tables(conn)
        v6_tables = load_v6_tables(conn)
    finally:
        conn.close()

    if len(runners_df) == 0:
        raise ValueError("Veritabanında değerlendirilecek sonuçlanmış koşucu satırı bulunamadı.")

    runners_df["date"] = pd.to_datetime(runners_df["date"], errors="coerce")
    runners_df = runners_df[runners_df["date"].notna()].copy()
    runners_df = _drop_unfinished_races(runners_df)
    if len(runners_df) == 0:
        raise ValueError("Sonuçlanmış koşu süzgeci sonrası satır kalmadı.")

    db_min_date = runners_df["date"].min().strftime("%Y-%m-%d")
    db_max_date = runners_df["date"].max().strftime("%Y-%m-%d")
    raw_total_rows = int(len(runners_df))
    raw_total_races = int(runners_df["race_id"].nunique())

    # ------------------------------------------------------------------
    # SMOKE MODE: fast <=15 min check on single year (2021), E0 + 1 V6 exp, 20% train sample
    # ------------------------------------------------------------------
    if smoke:
        coverage_df = compute_yearly_source_coverage(runners_df, v5_tables, v6_tables, feat_df=None)
        smoke_extra = {"mode": "smoke_pct20"}
        cfg_e0 = resolve_variant_config("E0", extra_meta=smoke_extra)
        cfg_cand = resolve_variant_config(SMOKE_CANDIDATE, extra_meta=smoke_extra)
        resolved_configs = {"E0": cfg_e0, SMOKE_CANDIDATE: cfg_cand}

        avail_years = sorted(int(y) for y in runners_df["date"].dt.year.unique())
        target_y = SMOKE_TEST_YEAR if SMOKE_TEST_YEAR in avail_years else avail_years[-1]
        max_dt_smoke = f"{target_y}-12-31"

        df_sm = _build_history_frame(
            runners_df,
            v5_tables,
            v6_tables,
            history_start=cfg_e0["history_start"],
            ref_end=REF_END_DEFAULT,
            v6_blocks=tuple(cfg_cand["extra_blocks"]),
            max_date=max_dt_smoke,
        )
        eval_mask_sm = _eval_filter_mask(df_sm)
        eval_y = df_sm[eval_mask_sm & (df_sm["_year"] == target_y)][
            ["race_id", "horse_key", "date", "_year", "win", "finish", "ganyan", "agf_close", "agf_share", "field"]
        ].copy()
        if len(eval_y) == 0:
            raise ValueError(f"Duman testi yılı ({target_y}) için değerlendirilebilir koşu bulunamadı.")

        v6_fill_rows = []
        for blk in cfg_cand["extra_blocks"]:
            for col in V6_BLOCK_COLS[blk]:
                v6_fill_rows.append(
                    {
                        "block": blk,
                        "col": col,
                        "all_fill": float(df_sm[col].notna().mean()),
                        "eval_fill": float(df_sm.loc[eval_mask_sm, col].notna().mean()),
                        "eval_nonzero": float(
                            (df_sm.loc[eval_mask_sm, col].notna() & (df_sm.loc[eval_mask_sm, col] != 0)).mean()
                        ),
                    }
                )

        tracker = _ProgressTracker(total_planned_steps=2)
        preds_sm = {}
        p_e0, dt_e0, fc_e0 = _predict_base_year(df_sm, eval_y, cfg_e0, target_y, cache_dir, smoke=True)
        if p_e0 is None:
            raise RuntimeError(f"Smoke E0 tahmini üretilemedi (yıl={target_y}).")
        preds_sm["E0"] = p_e0
        ll_e0 = _race_winner_lls(eval_y, p_e0)
        tracker.log_step("E0", target_y, dt_e0, 0.0, from_cache=fc_e0)

        p_c, dt_c, fc_c = _predict_base_year(df_sm, eval_y, cfg_cand, target_y, cache_dir, smoke=True)
        if p_c is None:
            raise RuntimeError(f"Smoke {SMOKE_CANDIDATE} tahmini üretilemedi (yıl={target_y}).")
        preds_sm[SMOKE_CANDIDATE] = p_c
        ll_c = _race_winner_lls(eval_y, p_c)
        tracker.log_step(SMOKE_CANDIDATE, target_y, dt_c, float((ll_c - ll_e0).mean()), from_cache=fc_c)

        del df_sm
        gc.collect()

        a_rows, _ = _summarize_period_metrics(eval_y, preds_sm, ["E0", SMOKE_CANDIDATE], base_key="E0")
        meta = {
            "db_path": str(db_path),
            "db_min_date": db_min_date,
            "db_max_date": db_max_date,
            "total_rows": raw_total_rows,
            "total_races": raw_total_races,
            "stage_a_races": int(eval_y["race_id"].nunique()),
            "stage_b_races": 0,
            "stage_c_races": 0,
        }
        report_md = format_v6_report(
            smoke=True,
            meta=meta,
            coverage_df=coverage_df,
            v6_fill_rows=v6_fill_rows,
            resolved_configs=resolved_configs,
            candidate_count=1,
            stage_a_rows=a_rows,
            stage_a_years=[target_y],
            diag_a_row=None,
            selected_top2=[SMOKE_CANDIDATE],
            stage_b_rows=[],
            stage_b_years=[],
            stage_b_yearly_detail=[],
            gate_results={},
            winner_variant=None,
            stage_c_rows=[],
            stage_c_years=[],
            cal_param_rows=[],
            winner_yearly_rows=[],
            winner_ev_tables={},
            winner_edge_tables={},
        )
        out_dir = os.path.dirname(str(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        print("SMOKE OK", flush=True)
        return {
            "smoke": True,
            "report_path": str(out_path),
            "report_markdown": report_md,
            "winner_variant": None,
            "selected_top2": [SMOKE_CANDIDATE],
        }

    # ------------------------------------------------------------------
    # FULL WALK-FORWARD MODE (Stage A -> Stage B -> Stage C)
    # Sequential single-frame phases keep peak RAM <= ~7 GB (<< 12 GB limit).
    # ------------------------------------------------------------------
    resolved_configs = {}
    for v_init in ("E0", "E1a", "E1b") + tuple(k for k in VARIANT_SPECS if k.startswith("E2_") or k.startswith("E4_")):
        resolved_configs[v_init] = resolve_variant_config(v_init)
    diag_cfg = resolve_variant_config("Ref_2015_Gecmis")

    # Phase 1: Main V5-history frame ("2006-03-04"->) for canonical eval metadata, E4 fill rates,
    # E0 (all stages so ΔLL is immediately available on every stdout line), plus E2_* and E4_* on Stage A.
    df_v5hist = _build_history_frame(
        runners_df,
        v5_tables,
        v6_tables,
        history_start=resolved_configs["E0"]["history_start"],
        ref_end=REF_END_DEFAULT,
        v6_blocks=tuple(V6_BLOCK_COLS),
    )

    eval_mask_v5 = _eval_filter_mask(df_v5hist)
    eval_cols_keep = [
        "race_id",
        "horse_key",
        "date",
        "_year",
        "win",
        "finish",
        "ganyan",
        "agf_close",
        "agf_share",
        "field",
    ]
    eval_all_meta = df_v5hist.loc[eval_mask_v5, eval_cols_keep].copy().reset_index(drop=True)
    eval_years_set = {int(y) for y in eval_all_meta["_year"].unique()}

    stage_a_years = [int(y) for y in STAGE_A_YEARS if int(y) in eval_years_set]
    stage_b_years = [int(y) for y in STAGE_B_YEARS if int(y) in eval_years_set]
    stage_c_years = [int(y) for y in STAGE_C_YEARS if int(y) in eval_years_set]
    warmup_years = [CAL_WARMUP_YEAR] if CAL_WARMUP_YEAR in eval_years_set else []

    if not stage_a_years:
        raise ValueError("Aşama A (2017–2021) için değerlendirilebilir koşu bulunamadı.")

    eval_by_year = {
        int(y): eval_all_meta[eval_all_meta["_year"] == int(y)].copy().reset_index(drop=True)
        for y in sorted(eval_years_set)
    }

    v6_fill_rows = []
    eval_target_mask_v5 = eval_mask_v5 & (df_v5hist["_year"] >= min(stage_a_years))
    for blk, cols_b in V6_BLOCK_COLS.items():
        for col in cols_b:
            s_all = df_v5hist[col]
            s_ev = df_v5hist.loc[eval_target_mask_v5, col]
            v6_fill_rows.append(
                {
                    "block": blk,
                    "col": col,
                    "all_fill": float(s_all.notna().mean()) if len(s_all) > 0 else 0.0,
                    "eval_fill": float(s_ev.notna().mean()) if len(s_ev) > 0 else 0.0,
                    "eval_nonzero": float((s_ev.notna() & (s_ev != 0)).mean()) if len(s_ev) > 0 else 0.0,
                }
            )

    n_a = len(stage_a_years)
    n_w = len(warmup_years)
    est_steps = (
        (n_w + n_a + len(stage_b_years) + len(stage_c_years))  # E0 across all stages
        + 2 * n_a  # E1a, E1b
        + n_a  # Ref_2015_Gecmis
        + 10 * n_a  # E2_01..E2_10
        + 6 * n_a  # E4_*
        + n_a  # E3
        + 4 * n_a  # E5_*
        + 2 * len(stage_b_years)  # Stage B top2 finalists
    )
    tracker = _ProgressTracker(total_planned_steps=est_steps)

    preds_by_var_year = {v: {} for v in list(VARIANT_SPECS) + list(DIAGNOSTIC_SPECS)}
    e0_winner_ll_by_year = {}

    def _run_hgb_variant_years(df_frame, var_name, cfg_obj, years_list):
        for y in years_list:
            ev_y = eval_by_year.get(int(y))
            if ev_y is None or len(ev_y) == 0:
                continue
            p_y, dt_s, from_c = _predict_base_year(df_frame, ev_y, cfg_obj, y, cache_dir, smoke=False)
            if p_y is None:
                continue
            preds_by_var_year[var_name][int(y)] = p_y
            ll_y = _race_winner_lls(ev_y, p_y)
            if var_name == "E0":
                e0_winner_ll_by_year[int(y)] = ll_y
                dll_val = 0.0
            elif int(y) in e0_winner_ll_by_year:
                dll_val = float((ll_y - e0_winner_ll_by_year[int(y)]).mean())
            else:
                dll_val = np.nan
            tracker.log_step(var_name, y, dt_s, dll_val, from_cache=from_c)

    # 1a. E0 baseline across warmup + Stage A + Stage B + Stage C
    e0_all_years = warmup_years + stage_a_years + stage_b_years + stage_c_years
    _run_hgb_variant_years(df_v5hist, "E0", resolved_configs["E0"], e0_all_years)

    # 1b. E2 (10 HGB configs) and E4 (6 feature blocks) on Stage A ONLY (2017–2021)
    for v_e2 in [k for k in VARIANT_SPECS if k.startswith("E2_")]:
        _run_hgb_variant_years(df_v5hist, v_e2, resolved_configs[v_e2], stage_a_years)

    for v_e4 in [k for k in VARIANT_SPECS if k.startswith("E4_")]:
        _run_hgb_variant_years(df_v5hist, v_e4, resolved_configs[v_e4], stage_a_years)

    del df_v5hist
    gc.collect()

    # Phase 2: Full 2005-> frame once for yearly source coverage (2005..max_year) + E1a & E1b on Stage A
    df_2005 = _build_history_frame(
        runners_df,
        v5_tables,
        v6_tables,
        history_start=resolved_configs["E1a"]["history_start"],
        ref_end=REF_END_DEFAULT,
        v6_blocks=(),
    )
    coverage_df = compute_yearly_source_coverage(runners_df, v5_tables, v6_tables, feat_df=df_2005)
    _run_hgb_variant_years(df_2005, "E1a", resolved_configs["E1a"], stage_a_years)
    _run_hgb_variant_years(df_2005, "E1b", resolved_configs["E1b"], stage_a_years)
    del df_2005
    gc.collect()

    # Phase 4: Diagnostic 2015-> history control on Stage A (2017–2021)
    df_2015 = _build_history_frame(
        runners_df,
        v5_tables,
        v6_tables,
        history_start=diag_cfg["history_start"],
        ref_end=REF_END_DEFAULT,
        v6_blocks=(),
    )
    _run_hgb_variant_years(df_2015, "Ref_2015_Gecmis", diag_cfg, stage_a_years)
    del df_2015
    gc.collect()

    # Phase 5: Select best of E1/E2 strictly on Stage A (2017–2021) and run E3 (5-seed average) on Stage A
    eval_a_df, preds_e12_a = _concat_year_preds(
        eval_by_year, preds_by_var_year, stage_a_years, ("E0",) + E1_E2_POOL
    )
    e12_rows, _ = _summarize_period_metrics(eval_a_df, preds_e12_a, ("E0",) + E1_E2_POOL, base_key="E0")
    e12_cand_rows = [r for r in e12_rows if r["variant"] in E1_E2_POOL]
    e12_cand_rows.sort(key=lambda r: (r["dll_e0"], E1_E2_POOL.index(r["variant"])))
    best_e12_var = e12_cand_rows[0]["variant"]
    resolved_configs["E3"] = resolve_variant_config("E3", base_config=resolved_configs[best_e12_var])

    df_e3 = _build_history_frame(
        runners_df,
        v5_tables,
        v6_tables,
        history_start=resolved_configs["E3"]["history_start"],
        ref_end=REF_END_DEFAULT,
        v6_blocks=tuple(resolved_configs["E3"]["extra_blocks"]),
    )
    _run_hgb_variant_years(df_e3, "E3", resolved_configs["E3"], stage_a_years)

    # Phase 6: Select best of E1..E4 strictly on Stage A for E5_best_temp / E5_best_iso,
    # ensure warmup year (2016) exists for that base, and run all 4 E5 variants on Stage A!
    eval_a_df, preds_e14_a = _concat_year_preds(
        eval_by_year, preds_by_var_year, stage_a_years, ("E0",) + E1_TO_E4_POOL
    )
    e14_rows, _ = _summarize_period_metrics(eval_a_df, preds_e14_a, ("E0",) + E1_TO_E4_POOL, base_key="E0")
    e14_cand_rows = [r for r in e14_rows if r["variant"] in E1_TO_E4_POOL]
    e14_cand_rows.sort(key=lambda r: (r["dll_e0"], E1_TO_E4_POOL.index(r["variant"])))
    best_e14_var = e14_cand_rows[0]["variant"]

    resolved_configs["E5_temp"] = resolve_variant_config("E5_temp", base_config=resolved_configs["E0"])
    resolved_configs["E5_iso"] = resolve_variant_config("E5_iso", base_config=resolved_configs["E0"])
    resolved_configs["E5_best_temp"] = resolve_variant_config(
        "E5_best_temp", base_config=resolved_configs[best_e14_var]
    )
    resolved_configs["E5_best_iso"] = resolve_variant_config(
        "E5_best_iso", base_config=resolved_configs[best_e14_var]
    )

    # Ensure best_e14_var has warmup_years (2016) predictions so E5_best_* is genuinely calibrated in 2017 too
    missing_warmup = [y for y in warmup_years if y not in preds_by_var_year[best_e14_var]]
    if missing_warmup:
        tracker.add_steps(len(missing_warmup))
        best_cfg = resolved_configs[best_e14_var]
        if (
            best_cfg["history_start"] == resolved_configs["E3"]["history_start"]
            and set(best_cfg["extra_blocks"]).issubset(set(resolved_configs["E3"]["extra_blocks"]))
        ):
            _run_hgb_variant_years(df_e3, best_e14_var, best_cfg, missing_warmup)
        else:
            del df_e3
            gc.collect()
            df_e3 = _build_history_frame(
                runners_df,
                v5_tables,
                v6_tables,
                history_start=best_cfg["history_start"],
                ref_end=REF_END_DEFAULT,
                v6_blocks=tuple(best_cfg["extra_blocks"]),
            )
            _run_hgb_variant_years(df_e3, best_e14_var, best_cfg, missing_warmup)

    del df_e3
    gc.collect()

    cal_param_rows = []

    def _run_cal_variant_years(cal_var, years_list):
        cfg_c = resolved_configs[cal_var]
        base_v = cfg_c["calibrated_from"]
        for y in years_list:
            ev_y = eval_by_year.get(int(y))
            if ev_y is None or len(ev_y) == 0:
                continue
            p_c, dt_s, from_c, c_meta = _predict_calibrated_year(
                eval_by_year,
                preds_by_var_year[base_v],
                cfg_c,
                y,
                cache_dir,
                smoke=False,
            )
            if p_c is None:
                continue
            preds_by_var_year[cal_var][int(y)] = p_c
            if c_meta is not None:
                cal_param_rows.append(c_meta)
            ll_y = _race_winner_lls(ev_y, p_c)
            dll_val = (
                float((ll_y - e0_winner_ll_by_year[int(y)]).mean())
                if int(y) in e0_winner_ll_by_year
                else np.nan
            )
            tracker.log_step(cal_var, y, dt_s, dll_val, from_cache=from_c)

    for v_e5 in ("E5_temp", "E5_iso", "E5_best_temp", "E5_best_iso"):
        _run_cal_variant_years(v_e5, stage_a_years)

    # ------------------------------------------------------------------
    # Stage A Ranking & Top-2 Selection (2017–2021)
    # ------------------------------------------------------------------
    all_stage_a_keys = ("E0",) + CANDIDATE_VARIANTS + ("Ref_2015_Gecmis",)
    eval_a_full, preds_a_full = _concat_year_preds(
        eval_by_year, preds_by_var_year, stage_a_years, all_stage_a_keys
    )
    raw_a_rows, _ = _summarize_period_metrics(eval_a_full, preds_a_full, all_stage_a_keys, base_key="E0")
    by_var_a = {r["variant"]: r for r in raw_a_rows}

    cand_a_rows = [by_var_a[v] for v in CANDIDATE_VARIANTS if v in by_var_a]
    cand_a_rows.sort(key=lambda r: (r["dll_e0"], CANDIDATE_VARIANTS.index(r["variant"])))
    selected_top2 = [r["variant"] for r in cand_a_rows[:2]]

    stage_a_rows = []
    if "B0" in by_var_a:
        stage_a_rows.append(by_var_a["B0"])
    if "E0" in by_var_a:
        stage_a_rows.append(by_var_a["E0"])
    stage_a_rows.extend(cand_a_rows)
    diag_a_row = by_var_a.get("Ref_2015_Gecmis")

    # ------------------------------------------------------------------
    # Stage B Validation (2022–2025): ONLY E0 + selected_top2
    # ------------------------------------------------------------------
    def _ensure_variant_years(target_vars, years_list):
        if not years_list or not target_vars:
            return
        # Determine any underlying HGB base variants needed (either directly or as base of E5)
        hgb_jobs = {}  # base_var -> set(years)
        cal_jobs = []
        for tv in target_vars:
            cfg_t = resolved_configs[tv]
            if cfg_t["calibration"] is None:
                miss = [y for y in years_list if y not in preds_by_var_year[tv]]
                if miss:
                    hgb_jobs.setdefault(tv, set()).update(miss)
            else:
                base_v = cfg_t["calibrated_from"]
                # Calibrator for year y needs base_v on all prior years (< max(years_list)) AND on years_list
                max_y = max(years_list)
                needed_base_years = [
                    y_all
                    for y_all in sorted(eval_years_set)
                    if CAL_WARMUP_YEAR <= y_all <= max_y and y_all not in preds_by_var_year[base_v]
                ]
                if needed_base_years:
                    hgb_jobs.setdefault(base_v, set()).update(needed_base_years)
                cal_jobs.append((tv, years_list))

        # Group HGB jobs by history_start so each frame is built at most once
        by_hist = {}
        for bv, y_set in hgb_jobs.items():
            hs = resolved_configs[bv]["history_start"]
            by_hist.setdefault(hs, []).append((bv, sorted(y_set)))

        for hs, bv_list in by_hist.items():
            req_blocks = []
            for bv, _ in bv_list:
                for blk in resolved_configs[bv]["extra_blocks"]:
                    if blk not in req_blocks:
                        req_blocks.append(blk)
            df_tmp = _build_history_frame(
                runners_df,
                v5_tables,
                v6_tables,
                history_start=hs,
                ref_end=REF_END_DEFAULT,
                v6_blocks=tuple(req_blocks),
            )
            for bv, y_sorted in bv_list:
                _run_hgb_variant_years(df_tmp, bv, resolved_configs[bv], y_sorted)
            del df_tmp
            gc.collect()

        for cv, y_c_list in cal_jobs:
            _run_cal_variant_years(cv, y_c_list)

    stage_b_rows = []
    stage_b_yearly_detail = []
    gate_results = {}
    passed_candidates = []
    winner_variant = None

    if stage_b_years:
        _ensure_variant_years(selected_top2, stage_b_years)
        b_keys = ["E0"] + selected_top2
        eval_b_df, preds_b_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, b_keys)
        stage_b_rows, race_dll_b = _summarize_period_metrics(eval_b_df, preds_b_map, b_keys, base_key="E0")

        for y_b in stage_b_years:
            ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], b_keys)
            yr_rows_b, _ = _summarize_period_metrics(ev_yb, pr_yb, b_keys, base_key="E0")
            for r_yb in yr_rows_b:
                r_yb["year"] = int(y_b)
                stage_b_yearly_detail.append(r_yb)

        by_var_b = {r["variant"]: r for r in stage_b_rows}
        for cand_v in selected_top2:
            if cand_v not in by_var_b:
                continue
            r_b = by_var_b[cand_v]
            g_res = evaluate_stage_b_gate(
                r_b["yearly_dll"],
                race_dll_b[cand_v],
                n_boot=2000,
                seed=0,
                min_neg_years=3,
            )
            gate_results[cand_v] = g_res
            if g_res["passed"]:
                passed_candidates.append(cand_v)

        if passed_candidates:
            passed_candidates.sort(key=lambda v: by_var_b[v]["dll_e0"])
            winner_variant = passed_candidates[0]

    # ------------------------------------------------------------------
    # Stage C Info (2026): ONLY E0 + gate-passing candidate(s)
    # ------------------------------------------------------------------
    stage_c_rows = []
    if stage_c_years:
        c_cands = list(passed_candidates)
        if c_cands:
            tracker.add_steps(len(c_cands) * len(stage_c_years))
            _ensure_variant_years(c_cands, stage_c_years)
        c_keys = ["E0"] + c_cands
        eval_c_df, preds_c_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, c_keys)
        stage_c_rows, _ = _summarize_period_metrics(eval_c_df, preds_c_map, c_keys, base_key="E0")

    # ------------------------------------------------------------------
    # Value-bet & Edge tables (if and only if a candidate passed Stage B gate)
    # ------------------------------------------------------------------
    winner_yearly_rows = []
    winner_ev_tables = {}
    winner_edge_tables = {}
    if winner_variant is not None:
        for st_lbl, st_yrs in [
            ("Aşama A", stage_a_years),
            ("Aşama B", stage_b_years),
            ("2026 Bilgi", stage_c_years),
        ]:
            for y_w in st_yrs:
                ev_yw, pr_yw = _concat_year_preds(
                    eval_by_year, preds_by_var_year, [y_w], ["E0", winner_variant]
                )
                if len(ev_yw) == 0 or winner_variant not in pr_yw:
                    continue
                yr_s, _ = _summarize_period_metrics(ev_yw, pr_yw, ["E0", winner_variant], base_key="E0")
                ymap = {r["variant"]: r for r in yr_s}
                if {"B0", "E0", winner_variant}.issubset(ymap):
                    b0_r, e0_r, w_r = ymap["B0"], ymap["E0"], ymap[winner_variant]
                    winner_yearly_rows.append(
                        {
                            "year": int(y_w),
                            "stage": st_lbl,
                            "races": int(w_r["races"]),
                            "b0_ll": b0_r["ll"],
                            "b0_t1": b0_r["top1"],
                            "b0_t2": b0_r["top2"],
                            "b0_t3": b0_r["top3"],
                            "e0_ll": e0_r["ll"],
                            "e0_t1": e0_r["top1"],
                            "e0_t2": e0_r["top2"],
                            "e0_t3": e0_r["top3"],
                            "w_ll": w_r["ll"],
                            "w_t1": w_r["top1"],
                            "w_t2": w_r["top2"],
                            "w_t3": w_r["top3"],
                            "dll_e0": w_r["dll_e0"],
                            "dll_lo": w_r["dll_e0_lo"],
                            "dll_hi": w_r["dll_e0_hi"],
                        }
                    )

        periods_for_ev = [
            ("Aşama B (2022–2025)", stage_b_years),
            ("Dev Tümü (2017–2025)", stage_a_years + stage_b_years),
        ]
        if stage_c_years:
            periods_for_ev.append(("2026 (Bilgi)", stage_c_years))

        for p_lbl, p_yrs in periods_for_ev:
            ev_p_df, pr_p_map = _concat_year_preds(
                eval_by_year, preds_by_var_year, p_yrs, ["E0", winner_variant]
            )
            if len(ev_p_df) == 0 or winner_variant not in pr_p_map:
                continue
            ev_p_df = ev_p_df.copy()
            ev_p_df["p_B0"] = ev_p_df["agf_share"].to_numpy(dtype=np.float64)
            ev_p_df["p_E0"] = pr_p_map["E0"]
            ev_p_df[f"p_{winner_variant}"] = pr_p_map[winner_variant]
            winner_ev_tables[p_lbl] = {
                "Saf AGF (B0)": compute_ev_bet_stats(ev_p_df, "p_B0", thresholds=(1.2, 1.35, 1.5), n_boot=1000, seed=0),
                "E0 (B1_SGR)": compute_ev_bet_stats(ev_p_df, "p_E0", thresholds=(1.2, 1.35, 1.5), n_boot=1000, seed=0),
                winner_variant: compute_ev_bet_stats(
                    ev_p_df, f"p_{winner_variant}", thresholds=(1.2, 1.35, 1.5), n_boot=1000, seed=0
                ),
            }

        ev_b_only, pr_b_only = _concat_year_preds(
            eval_by_year, preds_by_var_year, stage_b_years, ["E0", winner_variant]
        )
        if len(ev_b_only) > 0 and winner_variant in pr_b_only:
            ev_b_only = ev_b_only.copy()
            ev_b_only["p_B0"] = ev_b_only["agf_share"].to_numpy(dtype=np.float64)
            ev_b_only["p_E0"] = pr_b_only["E0"]
            ev_b_only[f"p_{winner_variant}"] = pr_b_only[winner_variant]
            for lbl_m, col_m in [
                ("Saf AGF (B0)", "p_B0"),
                ("E0 (B1_SGR)", "p_E0"),
                (winner_variant, f"p_{winner_variant}"),
            ]:
                winner_edge_tables[lbl_m] = {
                    "buckets": compute_edge_buckets(ev_b_only, col_m, n_boot=2000, seed=0),
                    "top1": compute_top1_roi(ev_b_only, col_m, n_boot=2000, seed=0),
                    "topk": compute_topk_coverage(ev_b_only, col_m, ks=(1, 2, 3)),
                }

    # Pin V6_CONFIG in ganyan/model_v6.py when requested (full run)
    if pin_config:
        pinned_payload = resolved_configs[winner_variant] if winner_variant is not None else None
        pin_v6_config_in_source(pinned_payload, module_path=model_v6_path)

    ordered_cfg_display = {}
    for k_ord in ("E0",) + CANDIDATE_VARIANTS:
        if k_ord in resolved_configs:
            ordered_cfg_display[k_ord] = resolved_configs[k_ord]
    ordered_cfg_display["Ref_2015_Gecmis"] = diag_cfg

    meta = {
        "db_path": str(db_path),
        "db_min_date": db_min_date,
        "db_max_date": db_max_date,
        "total_rows": raw_total_rows,
        "total_races": raw_total_races,
        "stage_a_races": sum(int(eval_by_year[y]["race_id"].nunique()) for y in stage_a_years),
        "stage_b_races": sum(int(eval_by_year[y]["race_id"].nunique()) for y in stage_b_years),
        "stage_c_races": sum(int(eval_by_year[y]["race_id"].nunique()) for y in stage_c_years),
    }

    report_md = format_v6_report(
        smoke=False,
        meta=meta,
        coverage_df=coverage_df,
        v6_fill_rows=v6_fill_rows,
        resolved_configs=ordered_cfg_display,
        candidate_count=len(CANDIDATE_VARIANTS),
        stage_a_rows=stage_a_rows,
        stage_a_years=stage_a_years,
        diag_a_row=diag_a_row,
        selected_top2=selected_top2,
        stage_b_rows=stage_b_rows,
        stage_b_years=stage_b_years,
        stage_b_yearly_detail=stage_b_yearly_detail,
        gate_results=gate_results,
        winner_variant=winner_variant,
        stage_c_rows=stage_c_rows,
        stage_c_years=stage_c_years,
        cal_param_rows=cal_param_rows,
        winner_yearly_rows=winner_yearly_rows,
        winner_ev_tables=winner_ev_tables,
        winner_edge_tables=winner_edge_tables,
    )

    out_dir = os.path.dirname(str(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return {
        "smoke": False,
        "report_path": str(out_path),
        "report_markdown": report_md,
        "candidate_count": len(CANDIDATE_VARIANTS),
        "selected_top2": selected_top2,
        "gate_results": gate_results,
        "winner_variant": winner_variant,
        "stage_a_df": pd.DataFrame(stage_a_rows),
        "stage_b_df": pd.DataFrame(stage_b_rows),
        "stage_c_df": pd.DataFrame(stage_c_rows),
        "coverage_df": coverage_df,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v6 ileri-yürüyen deney serisi (Aşama A seçim, Aşama B kapı, Aşama C 2026 bilgi)."
    )
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--out", default="reports/V6.md")
    ap.add_argument("--cache-dir", default="data/v6_cache")
    ap.add_argument("--smoke", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        run_v6_experiments(
            db_path=args.db,
            out_path=args.out,
            cache_dir=args.cache_dir,
            smoke=args.smoke,
        )
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
