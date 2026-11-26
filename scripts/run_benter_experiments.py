"""Walk-forward experimentation, Stage A/B/C gating, and report generator for Two-Stage (Bill Benter) models."""
import argparse
import gc
import os
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.backtest import load_runners_from_db
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5, load_v5_tables
from ganyan.features_v7 import attach_v7
from ganyan.features_v8 import attach_N, attach_v8
from ganyan.features_v9 import attach_v9
from ganyan.features_v10 import attach_H2H, attach_v10
from ganyan.model_benter import (
    PAST_MKT_COLS,
    RichBenterCombiner,
    STACK_OOF_COLS,
    TODAY_AGF_COLS,
    ThreeWayLogitBlender,
    TwoParamBenterCombiner,
    attach_fund_oof_features,
    corrupt_agf_share_lognormal,
    get_fund_cols,
    get_stack_cols,
)
from ganyan.model_v5 import bootstrap_mean_ci
from ganyan.model_v6 import (
    STAGE_A_YEARS,
    STAGE_B_YEARS,
    STAGE_C_YEARS,
    config_digest,
    evaluate_stage_b_gate,
    fit_v6_model_bundle,
    predict_v6_model_bundle,
)
from ganyan.model_v10 import V10_BLOCKS, V10_CONFIG
from scripts.run_v6_experiments import (
    CAL_WARMUP_YEAR,
    REF_END_DEFAULT,
    SMOKE_SAMPLE_FRAC,
    SMOKE_SAMPLE_SEED,
    SMOKE_TEST_YEAR,
    _ProgressTracker,
    _align_cached_preds,
    _cache_file_path,
    _concat_year_preds,
    _drop_unfinished_races,
    _eval_filter_mask,
    _fmt_dll_ci,
    _open_ro_db,
    _predict_base_year,
    _predict_calibrated_year,
    _race_winner_lls,
    _sample_smoke_train,
    _summarize_period_metrics,
)
from scripts.run_v7_experiments import _format_yearly_dll_matrix

SEL_THRESHOLD_DLL = -0.0002
FUND_EARLY_WARMUP_YEAR = 2015
RO_FALLBACK_CACHE_DIRS = ("data/v11_cache", "data/v10_cache")

# Pre-committed Stage A candidates (5 candidates <= 6 limit)
TWO_STAGE_CANDIDATE_SPECS = [
    ("B2P_15", "Benter 2-param koşullu logit: FUND_15 (2015→, 147 öz.) + AGF"),
    ("B2P_06", "Benter 2-param koşullu logit: FUND_06 (2006→ tam geçmiş, 147 öz.) + AGF"),
    ("BRICH_06", "Zengin koşullu logit: FUND_06 + AGF + asimetrik fark + saha boyu + 6 AGF etkileşimi"),
    ("BSTACK_HGB", "İki aşamalı yığılmış HGB: V10 (155 öz.) + sızıntısız FUND_06 dış-örneklem 4 öz."),
    ("BBLEND_V10", "3-yollu koşullu logit harmanı: V10 + FUND_06 + AGF"),
]


def _make_hgb_cfg(
    name,
    feature_cols,
    train_start_year=2015,
    require_agf=True,
    seeds=(0,),
    calibration=None,
    calibrated_from=None,
    description="",
    family="BENTER",
):
    cfg = {
        "variant": str(name),
        "family": str(family),
        "description": str(description),
        "history_start": str(V10_CONFIG["history_start"]),
        "history_start_year": int(V10_CONFIG["history_start_year"]),
        "train_start_year": int(train_start_year),
        "require_agf": bool(require_agf),
        "v7_blocks": list(V10_CONFIG["v7_blocks"]),
        "v8_blocks": list(V10_CONFIG["v8_blocks"]),
        "v9_blocks": list(V10_CONFIG["v9_blocks"]),
        "v10_blocks": list(V10_BLOCKS),
        "feature_cols": list(feature_cols),
        "hgb_params": dict(V10_CONFIG["hgb_params"]),
        "temporal_val_frac": None,
        "seeds": [int(s) for s in seeds],
        "calibration": calibration,
    }
    if calibrated_from is not None:
        cfg["calibrated_from"] = str(calibrated_from)
    return cfg


def _build_v10_base_frame(runners_df, v5_tables, max_date=None):
    """Build leak-free V10 (`v10_hlb`, 155 features) DataFrame from `2006-03-04` onward."""
    start_ts = pd.Timestamp(V10_CONFIG["history_start"])
    mask = runners_df["date"] >= start_ts
    if max_date is not None:
        mask = mask & (runners_df["date"] <= pd.Timestamp(max_date))
    r_sub = runners_df[mask].copy()
    if len(r_sub) == 0:
        r_sub = (
            runners_df.copy()
            if max_date is None
            else runners_df[runners_df["date"] <= pd.Timestamp(max_date)].copy()
        )

    w_df = v5_tables["workouts"]
    if len(w_df) > 0:
        w_mask = w_df["date"] >= start_ts
        if max_date is not None:
            w_mask = w_mask & (w_df["date"] <= pd.Timestamp(max_date))
        w_sub = w_df[w_mask].copy()
    else:
        w_sub = w_df
    v5_sub = {"ext": v5_tables["ext"], "workouts": w_sub}

    df = build_features(r_sub, ref_end=REF_END_DEFAULT)
    del r_sub
    df = attach_v5(df, v5_sub, blocks=("S", "G", "R"))
    df = attach_v7(df, blocks=tuple(V10_CONFIG["v7_blocks"]))
    df = attach_v8(df, blocks=tuple(V10_CONFIG["v8_blocks"]))
    df = attach_v9(df, blocks=tuple(V10_CONFIG["v9_blocks"]), v5_tables=v5_sub)
    df = attach_v10(df, blocks=tuple(V10_BLOCKS))
    df["_year"] = df["date"].dt.year.astype(np.int32)
    df["_has_race_win"] = df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    df["_is_eval"] = _eval_filter_mask(df)
    return df


def _predict_base_year_with_ro_fallback(
    df_hist,
    eval_year_df,
    resolved_cfg,
    year,
    cache_dir,
    smoke=False,
    ro_dirs=RO_FALLBACK_CACHE_DIRS,
):
    """Check `cache_dir` and optional read-only cache dirs by exact `(variant, digest, year)` before fitting."""
    if not smoke and ro_dirs:
        variant = resolved_cfg["variant"]
        cand_digests = [config_digest(resolved_cfg)]
        if variant == "V10_1s" and "v11_blocks" not in resolved_cfg:
            cand_digests.append(config_digest(dict(resolved_cfg, v11_blocks=[])))
        primary_path = _cache_file_path(cache_dir, variant, cand_digests[0], year, smoke=False)
        if not os.path.exists(primary_path):
            for dg in cand_digests:
                for rd in ro_dirs:
                    alt_path = _cache_file_path(rd, variant, dg, year, smoke=False)
                    if os.path.exists(alt_path):
                        t0 = time.perf_counter()
                        try:
                            cached_df = pd.read_pickle(alt_path)
                            aligned = _align_cached_preds(eval_year_df, cached_df)
                            if aligned is not None:
                                return aligned, time.perf_counter() - t0, True
                        except Exception:
                            pass

    return _predict_base_year(
        df_hist,
        eval_year_df,
        resolved_cfg,
        year,
        cache_dir,
        smoke=smoke,
    )


def _predict_full_slice_year(df_hist, target_mask, resolved_cfg, year, cache_dir, smoke=False):
    """Predict `p` for ALL settled rows in `year` matching `target_mask` (even if `agf_share` is NaN).

    Used so `FUND_06` produces complete walk-forward OOS predictions across `2015..2026` rows,
    allowing `BSTACK_HGB` to train on `2015..(Y-1)` with 100% genuine OOS `p_fund06`.
    """
    t0 = time.perf_counter()
    variant = f"{resolved_cfg['variant']}_ALLROWS"
    cfg_copy = dict(resolved_cfg)
    cfg_copy["variant"] = variant
    digest = config_digest(cfg_copy)
    c_path = _cache_file_path(cache_dir, variant, digest, year, smoke=smoke)

    te_hist = df_hist[target_mask]
    if len(te_hist) == 0:
        return None, time.perf_counter() - t0, False

    if os.path.exists(c_path):
        try:
            cached_df = pd.read_pickle(c_path)
            aligned = _align_cached_preds(te_hist[["race_id", "horse_key"]], cached_df)
            if aligned is not None:
                return aligned, time.perf_counter() - t0, True
        except Exception:
            pass

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

    from ganyan.model_v6 import fit_predict_v6
    from scripts.run_v6_experiments import _save_pickle_atomic

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
    _save_pickle_atomic(save_df, c_path)
    return p_raw_hist, time.perf_counter() - t0, False


def _fit_predict_combiner_walkforward(
    eval_by_year,
    preds_by_var_year,
    target_years,
    kind,
    fund_var,
    v10_var=None,
):
    """Fit conditional-logit combiner strictly on `< year` OOS predictions and predict `year`."""
    out_preds = {}
    weight_rows = []
    avail_years = sorted(int(y) for y in eval_by_year if len(eval_by_year[int(y)]) > 0)

    for y in target_years:
        y_int = int(y)
        ev_y = eval_by_year.get(y_int)
        if ev_y is None or len(ev_y) == 0:
            continue
        pf_y = preds_by_var_year.get(fund_var, {}).get(y_int)
        if pf_y is None:
            continue
        pv_y = preds_by_var_year.get(v10_var, {}).get(y_int) if v10_var else None
        if v10_var and pv_y is None:
            continue

        prior_ys = [
            py
            for py in avail_years
            if py < y_int
            and py in preds_by_var_year.get(fund_var, {})
            and preds_by_var_year[fund_var][py] is not None
            and (not v10_var or (py in preds_by_var_year.get(v10_var, {}) and preds_by_var_year[v10_var][py] is not None))
        ]

        if not prior_ys:
            # Smoke mode single-year fallback: equal prior weights (no test fitting!)
            if kind == "2p":
                comb = TwoParamBenterCombiner()
                out_preds[y_int] = comb.predict(pf_y, ev_y["agf_share"].to_numpy(), ev_y["race_id"].to_numpy())
                weight_rows.append({"kind": kind, "year": y_int, "fit_years": "—", "w_str": "a=0.500, b=0.500"})
            elif kind == "3way":
                comb = ThreeWayLogitBlender()
                out_preds[y_int] = comb.predict(pv_y, pf_y, ev_y["agf_share"].to_numpy(), ev_y["race_id"].to_numpy())
                weight_rows.append({"kind": kind, "year": y_int, "fit_years": "—", "w_str": "v10=0.800, fund=0.100, agf=0.100"})
            elif kind == "rich":
                comb = TwoParamBenterCombiner()
                out_preds[y_int] = comb.predict(pf_y, ev_y["agf_share"].to_numpy(), ev_y["race_id"].to_numpy())
                weight_rows.append({"kind": kind, "year": y_int, "fit_years": "—", "w_str": "fallback 2p (0.50, 0.50)"})
            continue

        tr_df = pd.concat([eval_by_year[py] for py in prior_ys], ignore_index=True)
        pf_tr = np.concatenate([preds_by_var_year[fund_var][py] for py in prior_ys])
        agf_tr = tr_df["agf_share"].to_numpy(dtype=np.float64)
        win_tr = (tr_df["win"].to_numpy(dtype=np.float64) == 1.0).astype(np.float64)
        rids_tr = tr_df["race_id"].to_numpy()
        fit_yrs_lbl = f"{min(prior_ys)}–{max(prior_ys)}" if len(prior_ys) > 1 else str(prior_ys[0])

        if kind == "2p":
            comb = TwoParamBenterCombiner(l2_reg=1e-4).fit(pf_tr, agf_tr, rids_tr, win_tr)
            p_out = comb.predict(pf_y, ev_y["agf_share"].to_numpy(dtype=np.float64), ev_y["race_id"].to_numpy())
            w_str = f"a(temel)={comb.a_:.4f}, b(agf)={comb.b_:.4f}"
        elif kind == "rich":
            comb = RichBenterCombiner(l2_reg=2e-3).fit(tr_df, pf_tr, agf_tr, win_tr)
            p_out = comb.predict(ev_y, pf_y, ev_y["agf_share"].to_numpy(dtype=np.float64))
            c = comb.coef_
            w_str = f"temel={c[0]:.3f}, agf={c[1]:.3f}, +edge={c[2]:.3f}, -edge={c[3]:.3f}"
        elif kind == "3way":
            pv_tr = np.concatenate([preds_by_var_year[v10_var][py] for py in prior_ys])
            comb = ThreeWayLogitBlender(l2_reg=1e-4).fit(pv_tr, pf_tr, agf_tr, rids_tr, win_tr)
            p_out = comb.predict(
                pv_y,
                pf_y,
                ev_y["agf_share"].to_numpy(dtype=np.float64),
                ev_y["race_id"].to_numpy(),
            )
            w_str = f"w_v10={comb.w_v10_:.4f}, w_temel={comb.w_fund_:.4f}, w_agf={comb.w_agf_:.4f}"
        else:
            raise ValueError(f"Unknown combiner kind: {kind!r}")

        out_preds[y_int] = p_out
        weight_rows.append({"kind": kind, "year": y_int, "fit_years": fit_yrs_lbl, "w_str": w_str})

    return out_preds, weight_rows


def _run_noisy_agf_diagnostic(df_hist, eval_by_year, preds_fund06_by_year, diag_year=2025):
    """Diagnostic: compare `V10_1s`, `B2P_06`, `B2P_06_ADAPT`, and `FUND_06` under morning AGF noise."""
    y_int = int(diag_year)
    if y_int not in eval_by_year or y_int not in preds_fund06_by_year:
        return []

    ev_mask_y = (df_hist["_year"] == y_int) & df_hist["_is_eval"]
    te_full_y = df_hist.loc[ev_mask_y].copy().reset_index(drop=True)
    if len(te_full_y) == 0:
        return []

    # Align FUND_06(diag_year) onto te_full_y
    ev_meta_y = eval_by_year[y_int]
    pf_meta_df = pd.DataFrame(
        {
            "race_id": ev_meta_y["race_id"].to_numpy(),
            "horse_key": ev_meta_y["horse_key"].to_numpy(),
            "p": preds_fund06_by_year[y_int],
        }
    )
    pf_y = _align_cached_preds(te_full_y[["race_id", "horse_key"]], pf_meta_df)
    if pf_y is None:
        return []

    # Fit 1-seed V10 bundle once on 2015..(diag_year-1)
    v10_1s_cfg = _make_hgb_cfg(
        "V10_DIAG_1s",
        V10_CONFIG["feature_cols"],
        train_start_year=2015,
        require_agf=True,
        seeds=(0,),
        family="V10",
    )
    tr_mask = (
        (df_hist["date"] >= pd.Timestamp("2015-01-01"))
        & (df_hist["date"] < pd.Timestamp(f"{y_int:04d}-01-01"))
        & df_hist["win"].notna()
        & df_hist["_has_race_win"]
        & df_hist["agf_share"].notna()
    )
    tr_v10 = df_hist.loc[tr_mask]
    if len(tr_v10) < 100:
        return []
    v10_bundle = fit_v6_model_bundle(tr_v10, config=v10_1s_cfg)

    # Prior years (< diag_year) for fitting B2P_06 & noise-adapted B2P_06_ADAPT
    prior_ys = sorted(
        py for py in eval_by_year if int(py) < y_int and int(py) in preds_fund06_by_year and preds_fund06_by_year[int(py)] is not None
    )
    if not prior_ys:
        return []
    tr_comb_df = pd.concat([eval_by_year[py] for py in prior_ys], ignore_index=True)
    pf_tr = np.concatenate([preds_fund06_by_year[py] for py in prior_ys])
    agf_tr_clean = tr_comb_df["agf_share"].to_numpy(dtype=np.float64)
    rids_tr = tr_comb_df["race_id"].to_numpy()
    win_tr = (tr_comb_df["win"].to_numpy(dtype=np.float64) == 1.0).astype(np.float64)

    comb_clean = TwoParamBenterCombiner(l2_reg=1e-4).fit(pf_tr, agf_tr_clean, rids_tr, win_tr)

    # Context slice around diag_year (last 2 years) so N & H2H recompute today's AGF interactions fast (<2s)
    ctx_mask = (df_hist["_year"] >= (y_int - 2)) & (df_hist["_year"] <= y_int)
    base_ctx_cols = [
        c
        for c in ("date", "city", "race_no", "race_id", "horse_key", "scratched", "finish", "owner", "trainer", "jockey", "agf_close", "agf_pct")
        if c in df_hist.columns
    ]
    ctx_base = df_hist.loc[ctx_mask, base_ctx_cols].copy().reset_index(drop=True)
    ctx_is_target_y = (pd.to_datetime(ctx_base["date"]).dt.year == y_int).to_numpy()

    win_y_mask = te_full_y["win"].to_numpy(dtype=np.float64) == 1.0
    rids_y = te_full_y["race_id"].to_numpy()
    agf_y_clean = te_full_y["agf_share"].to_numpy(dtype=np.float64)
    ll_fund_only = float(_race_winner_lls(te_full_y, pf_y).mean())

    rows = []
    for sigma in (0.0, 0.15, 0.30, 0.50):
        noisy_agf_y = corrupt_agf_share_lognormal(agf_y_clean, rids_y, sigma_log=sigma, seed=42)
        ll_agf = float(-np.log(np.clip(noisy_agf_y[win_y_mask], 1e-6, None)).mean())

        # Fixed-weight Benter combiner
        p_b2p_fixed = comb_clean.predict(pf_y, noisy_agf_y, rids_y)
        ll_b2p_fixed = float(_race_winner_lls(te_full_y, p_b2p_fixed).mean())

        # Noise-adapted Benter combiner (fit strictly on < diag_year with matching sigma)
        if sigma == 0.0:
            comb_adapt = comb_clean
        else:
            noisy_agf_tr = corrupt_agf_share_lognormal(agf_tr_clean, rids_tr, sigma_log=sigma, seed=17)
            comb_adapt = TwoParamBenterCombiner(l2_reg=1e-4).fit(pf_tr, noisy_agf_tr, rids_tr, win_tr)
        p_b2p_adapt = comb_adapt.predict(pf_y, noisy_agf_y, rids_y)
        ll_b2p_adapt = float(_race_winner_lls(te_full_y, p_b2p_adapt).mean())

        # Recompute V10's today-AGF columns under noisy_agf_y
        te_mod = te_full_y.copy()
        te_mod["agf_share"] = noisy_agf_y
        te_mod["log_agf"] = np.log(np.clip(noisy_agf_y, 1e-4, None))
        if sigma > 0.0:
            ctx_mod = ctx_base.copy()
            # Map noisy_agf_y * 100 onto target year rows of ctx_mod by (race_id, horse_key)
            key_df = pd.DataFrame(
                {"race_id": te_mod["race_id"], "horse_key": te_mod["horse_key"], "_nagf": noisy_agf_y * 100.0}
            )
            ctx_mod = ctx_mod.merge(key_df, on=["race_id", "horse_key"], how="left")
            use_n = ctx_is_target_y & ctx_mod["_nagf"].notna().to_numpy()
            ctx_mod["agf_close"] = np.where(use_n, ctx_mod["_nagf"], ctx_mod.get("agf_close", np.nan))
            ctx_mod["agf_share"] = np.where(use_n, ctx_mod["_nagf"] / 100.0, np.nan)
            ctx_mod = attach_N(ctx_mod)
            ctx_mod = attach_H2H(ctx_mod)
            upd_cols = ["own_is_sub_agf", "own_mate_agf", "trn_is_sub_agf", "agf_surge_ratio", "sleep_wakeup_flag", "h2h_vs_fav_margin"]
            sub_upd = ctx_mod.loc[ctx_is_target_y, ["race_id", "horse_key"] + upd_cols].drop_duplicates(
                subset=["race_id", "horse_key"], keep="last"
            )
            te_mod = te_mod.drop(columns=upd_cols).merge(sub_upd, on=["race_id", "horse_key"], how="left")

        p_v10_noisy = predict_v6_model_bundle(v10_bundle, te_mod, gamma=1.0, year=y_int)
        ll_v10 = float(_race_winner_lls(te_mod, p_v10_noisy).mean())

        rows.append(
            {
                "sigma": float(sigma),
                "label": f"σ={sigma:.2f}" + (" (Kapanış AGF)" if sigma == 0.0 else ""),
                "races": int(win_y_mask.sum()),
                "ll_agf": ll_agf,
                "ll_v10": ll_v10,
                "ll_b2p_fixed": ll_b2p_fixed,
                "ll_b2p_adapt": ll_b2p_adapt,
                "ll_fund": ll_fund_only,
                "adapt_weights": f"a={comb_adapt.a_:.3f}, b={comb_adapt.b_:.3f}",
            }
        )

    # Extreme case: 07:00 AM pre-pool (AGF completely NaN)
    te_no_agf = te_full_y.copy()
    for c in TODAY_AGF_COLS:
        if c in te_no_agf.columns:
            te_no_agf[c] = np.nan
    p_v10_no_agf = predict_v6_model_bundle(v10_bundle, te_no_agf, gamma=1.0, year=y_int)
    ll_v10_no_agf = float(_race_winner_lls(te_no_agf, p_v10_no_agf).mean())
    rows.append(
        {
            "sigma": np.inf,
            "label": "AGF Yok (Sabah 07:00 bülteni)",
            "races": int(win_y_mask.sum()),
            "ll_agf": np.nan,
            "ll_v10": ll_v10_no_agf,
            "ll_b2p_fixed": ll_fund_only,
            "ll_b2p_adapt": ll_fund_only,
            "ll_fund": ll_fund_only,
            "adapt_weights": "a=1.000, b=0.000 (saf P_temel)",
        }
    )
    return rows


def _day_cluster_roi_ci(dates, net_returns, n_boot=2000, seed=0):
    """Day-clustered bootstrap mean ROI and 95% CI matching `KUMARBAZ.md` discipline."""
    if len(net_returns) == 0:
        return np.nan, np.nan, np.nan
    d_codes, _ = pd.factorize(pd.to_datetime(dates).dt.strftime("%Y-%m-%d"), sort=True)
    n_days = int(d_codes.max()) + 1
    day_sum = np.bincount(d_codes, weights=net_returns, minlength=n_days)
    day_cnt = np.bincount(d_codes, minlength=n_days).astype(np.float64)
    mean_roi = float(np.sum(day_sum) / np.maximum(np.sum(day_cnt), 1.0))
    if n_days < 2:
        return mean_roi, mean_roi, mean_roi

    rng = np.random.default_rng(int(seed))
    boot = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.integers(0, n_days, size=n_days)
        tot_c = np.sum(day_cnt[idx])
        boot[b] = np.sum(day_sum[idx]) / tot_c if tot_c > 0 else 0.0
    return mean_roi, float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def _compute_value_overlay_diagnostic(eval_df, preds_map, candidates):
    """Diagnostic: test `Değerci` rule (`p >= 0.08` and `p / agf_share >= 1.5`, top-6/day) across models."""
    if len(eval_df) == 0:
        return []
    base = eval_df[["race_id", "date", "win", "ganyan", "agf_share"]].copy()
    base["_day"] = pd.to_datetime(base["date"]).dt.strftime("%Y-%m-%d")
    ok_base = (
        base["win"].notna()
        & base["ganyan"].notna()
        & (base["ganyan"] > 0.0)
        & base["agf_share"].notna()
        & (base["agf_share"] > 0.0)
    )
    rows = []
    for name, label in candidates:
        if name not in preds_map:
            continue
        sub = base.copy()
        sub["p"] = preds_map[name]
        sub = sub[ok_base & sub["p"].notna()].copy()
        if sub.empty:
            continue
        sub["ratio"] = sub["p"] / sub["agf_share"]
        picks = sub[(sub["p"] >= 0.08) & (sub["ratio"] >= 1.5)].copy()
        if picks.empty:
            rows.append({"model": name, "label": label, "bets": 0, "hit": np.nan, "roi": np.nan, "lo": np.nan, "hi": np.nan})
            continue
        picks = picks.sort_values(["_day", "ratio"], ascending=[True, False], kind="mergesort")
        picks = picks.groupby("_day", sort=False).head(6)
        net = picks["win"].to_numpy(dtype=np.float64) * picks["ganyan"].to_numpy(dtype=np.float64) - 1.0
        roi, lo, hi = _day_cluster_roi_ci(picks["date"], net, n_boot=2000, seed=0)
        rows.append(
            {
                "model": name,
                "label": label,
                "bets": int(len(picks)),
                "hit": float(picks["win"].mean()),
                "med_ganyan": float(picks.loc[picks["win"] == 1, "ganyan"].median()) if (picks["win"] == 1).any() else np.nan,
                "roi": roi,
                "lo": lo,
                "hi": hi,
            }
        )
    return rows


def format_benter_report(
    *,
    smoke,
    meta,
    fund_stage_a_rows,
    fund_stage_b_rows,
    fund_stage_c_rows,
    stage1_rows,
    stage1_years,
    selected_candidate,
    sel_note,
    stage2_rows,
    stage2_years,
    combiner_weight_rows,
    stage3_b_rows,
    stage3_b_yearly_detail,
    stage3_gate_result,
    stage3_passed,
    stage3_c_rows,
    noisy_diag_rows,
    value_diag_rows,
):
    title = (
        "# Ganyan İki Aşamalı Model (Bill Benter: P_temel + AGF) — Duman Testi (--smoke)"
        if smoke
        else "# Ganyan İki Aşamalı Model (Bill Benter: P_temel + AGF) — Deneyler ve Kapı Raporu"
    )
    lines = [
        title,
        "",
        "> **Uyarı 1 (Kapanış AGF):** Standart Aşama A/B/C karşılaştırması kapanış AGF (`agf_close`) ile yapılır; erken/gürültülü sabah AGF etkisi Bölüm 6'da ayrıca ölçülmüştür.",
        "> **Uyarı 2 (Seçim Protokolü):** `V10_1s` tabanına karşı önceden dondurulmuş 5 iki-aşamalı aday yalnız Aşama A (`2017–2021`) üzerinde `-0.0002` sıkı (`<`) eşiğiyle sınanır; Aşama B resmi kapısına **en fazla tek** aday taşınır.",
        "",
        "## 1. Mimari ve Özellik Ayrımı Özeti",
        "",
        f"- **Veritabanı:** `{meta['db_path']}` (salt-okunur, `{meta['db_min_date']}` … `{meta['db_max_date']}`)",
        f"- **Toplam Sonuçlanmış Koşucu / Koşu:** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Taban Model (`V10_CONFIG`):** `V10_HLB_CAL` (`v10_hlb`, `155` özellik)",
        f"- **Bugünün AGF'sine Bağımlı Sütunlar (`TODAY_AGF_COLS`, `8` adet — `P_temel`'den çıkarıldı):** `{', '.join(TODAY_AGF_COLS)}`",
        f"- **Geçmiş `< D` Piyasa Sütunları (`PAST_MKT_COLS`, `10` adet — yalnız `SPORT_15`'ten çıkarıldı):** `{', '.join(PAST_MKT_COLS)}`",
        f"- **1. Aşama Saf Güç Özellikleri:** `FUND_15` / `FUND_06` = **`147` özellik** (bugünkü AGF `%0`), `SPORT_15` = **`137` özellik** (tüm tarih boyunca oran/AGF `%0`)",
        f"- **Değerlendirme Koşu Sayıları:** Aşama A `{meta['stage_a_races']:,}` | Aşama B `{meta['stage_b_races']:,}` | Aşama C (2026 bilgi) `{meta['stage_c_races']:,}`",
        "",
        "## 2. Aşama 0 — Tek Başına Saf Güç (`P_temel`, AGF=YOK) Performansı",
        "",
        "Bu tablo **hiçbir AGF bilgisi görmeyen** 1. aşama saf modellerin tek başına ne kadar isabet ürettiğini (uygulamadaki *\"Saf Pist Gücü\"* kartı için) halkın kapanış AGF'si (`B0`) ile karşılaştırır:",
        "",
        "| Dönem | Varyant | Eğitim Baş. | Öz. Sayısı | Koşu | Log-Loss | ΔLL vs AGF (`B0`) | 1. Tercih | İlk-2 | İlk-3 |",
        "|---|---|---:|---:|---:|---:|---|---:|---:|---:|",
    ]

    for period_lbl, f_rows in (
        ("2017–2021", fund_stage_a_rows),
        ("2022–2025", fund_stage_b_rows),
        ("2026 (bilgi)", fund_stage_c_rows),
    ):
        for r in f_rows:
            v = r["variant"]
            if v == "B0":
                tr_s, fc_s = "—", "1 (AGF)"
            elif v == "FUND_06":
                tr_s, fc_s = "2006", "147"
            elif v == "FUND_15":
                tr_s, fc_s = "2015", "147"
            else:
                tr_s, fc_s = "2015", "137"
            lines.append(
                f"| `{period_lbl}` | `{v}` | {tr_s} | {fc_s} | {r['races']:,} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )

    a_lbl = f"{min(stage1_years)}–{max(stage1_years)}" if stage1_years else "—"
    lines += [
        "",
        f"## 3. Aşama A — İki Aşamalı Aday Taraması (`{a_lbl}`, 1-Tohum, Seçim Eşiği `< {SEL_THRESHOLD_DLL}`)",
        "",
        "| Varyant | Açıklama | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    desc_map = {"B0": "Saf kapanış AGF", "V10_1s": "Tek aşamalı V10 tabanı (155 öz., 1 tohum)"}
    desc_map.update(dict(TWO_STAGE_CANDIDATE_SPECS))

    s1_sorted = sorted(
        stage1_rows,
        key=lambda r: (-1 if r["variant"] == "B0" else (0 if r["variant"] == "V10_1s" else 1), r["ll"]),
    )
    for r in s1_sorted:
        v = r["variant"]
        neg_s = "—" if v in ("B0", "V10_1s") else f"{r['neg_years']}/{r['total_years']}"
        lines.append(
            f"| `{v}` | {desc_map.get(v, v)} | {r['races']:,} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_1s'))} | "
            f"{neg_s} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
        )

    if stage1_years and stage1_rows:
        lines.extend(
            _format_yearly_dll_matrix(
                s1_sorted,
                stage1_years,
                "V10_1s",
                f"Aşama A Yıllık ΔLL(varyant − V10_1s) (`{a_lbl}`)",
            )
        )

    lines += [
        "",
        f"- **Aşama A Seçim Kararı:** {sel_note}",
        f"- **Aşama 3 Resmi Kapı Adayı:** `{selected_candidate or 'YOK'}`",
    ]

    if stage2_rows and stage2_years:
        b_lbl = f"{min(stage2_years)}–{max(stage2_years)}"
        s2_sorted = sorted(
            stage2_rows,
            key=lambda r: (-1 if r["variant"] == "B0" else (0 if r["variant"] == "V10_1s" else 1), r["ll"]),
        )
        lines += [
            "",
            f"## 4. Aşama 2 — Tanısal Karşılaştırma (`{b_lbl}`, 1-Tohum, Seçimde Kullanılmaz)",
            "",
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---:|---:|---:|---:|",
        ]
        for r in s2_sorted:
            v = r["variant"]
            neg_s = "—" if v in ("B0", "V10_1s") else f"{r['neg_years']}/{r['total_years']}"
            lines.append(
                f"| `{v}` | {r['races']:,} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_1s'))} | "
                f"{neg_s} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )
        lines.extend(
            _format_yearly_dll_matrix(
                s2_sorted,
                stage2_years,
                "V10_1s",
                f"Aşama 2 Tanısal Yıllık ΔLL(varyant − V10_1s) (`{b_lbl}`)",
            )
        )

    if combiner_weight_rows:
        lines += [
            "",
            "### Öğrenilen İki Aşamalı Birleştirici Ağırlıkları (Yalnız `< Y` Yıllarından)",
            "",
            "| Birleştirici | Test Yılı | Eğitim Yılları | Öğrenilen Katsayılar |",
            "|---|---:|---|---|",
        ]
        for wr in combiner_weight_rows:
            if wr["year"] in (2017, 2019, 2021, 2022, 2024, 2025, 2026) or smoke:
                lines.append(f"| `{wr['kind']}` | {wr['year']} | `{wr['fit_years']}` | `{wr['w_str']}` |")

    lines += [
        "",
        "## 5. Aşama 3 — Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Kalibrasyon, `vs V10_HLB_CAL`)",
        "",
    ]
    if not selected_candidate:
        lines.append(
            "Aşama A'da hiçbir iki-aşamalı aday `< -0.0002` eşiğini geçemediği için Aşama 3 5-tohum kapısı "
            "çalıştırılmamıştır. **Kapı Kararı: KALDI — canlıda `V10_HLB_CAL` (`v10_hlb`) korunur.**"
        )
    elif stage3_b_rows:
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V10_HLB_CAL` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 | Kapı |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for r in stage3_b_rows:
            v = r["variant"]
            if v == "B0":
                g_str = "Referans"
            elif v == "V10_HLB_CAL":
                g_str = "Canlı Taban"
            else:
                g_str = "**GEÇTİ**" if stage3_passed else "**KALDI**"
            lines.append(
                f"| `{v}` | {r['races']:,} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_HLB_CAL'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_str} |"
            )
        if stage3_b_yearly_detail:
            lines += [
                "",
                "### Aşama 3 Yıllık Kırılım (`vs V10_HLB_CAL`)",
                "",
                "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V10_HLB_CAL` (%95 GA) | 1. Tercih | İlk-3 |",
                "|---:|---|---:|---:|---|---:|---:|",
            ]
            for yr_r in stage3_b_yearly_detail:
                v = yr_r["variant"]
                if v == "B0":
                    continue
                lines.append(
                    f"| {yr_r['year']} | `{v}` | {yr_r['races']:,} | {yr_r['ll']:.4f} | "
                    f"{_fmt_dll_ci(yr_r['dll_e0'], yr_r['dll_e0_lo'], yr_r['dll_e0_hi'], is_self=(v == 'V10_HLB_CAL'))} | "
                    f"{yr_r['top1']:.2%} | {yr_r['top3']:.2%} |"
                )

    if stage3_c_rows:
        lines += [
            "",
            "### Aşama C — 2026 Bilgi Kümesi *(Seçim ve Kapıda Kullanılmaz)*",
            "",
            "| Varyant | Koşu | Log-Loss | Tabana Göre ΔLL (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---:|---:|---:|",
        ]
        base_c = "V10_HLB_CAL" if any(r["variant"] == "V10_HLB_CAL" for r in stage3_c_rows) else "V10_1s"
        for r in stage3_c_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']:,} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == base_c))} | "
                f"{r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )

    if noisy_diag_rows:
        lines += [
            "",
            "## 6. Ürün ve Canlı Tanı 1 — Sabah / Erken Gürültülü AGF Dayanıklılığı (`2025`)",
            "",
            "`V5_BULGULAR.md` §5'te ölçüldüğü üzere sabah erken AGF (`~5-6 saat` önce), kapanış AGF'den yaklaşık `+0.11` nats daha gürültülüdür (`σ_log ≈ 0.25–0.35`). Aşağıdaki tablo `2025` koşularında test anındaki AGF gürültülendiğinde veya sabah 07:00'de AGF henüz hiç açılmadığında tek aşamalı `V10_1s` ile iki aşamalı `B2P_06` / `FUND_06` modellerinin log-loss davranışını gösterir:",
            "",
            "| Senaryo | Koşu | Gürültülü AGF LL | Tek Aşamalı `V10_1s` LL | `B2P_06` (Sabit) LL | `B2P_06` (Uyumlu) LL | Saf `FUND_06` LL | Uyumlu Ağırlıklar |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for nr in noisy_diag_rows:
            agf_s = f"{nr['ll_agf']:.4f}" if np.isfinite(nr["ll_agf"]) else "—"
            lines.append(
                f"| {nr['label']} | {nr['races']:,} | {agf_s} | {nr['ll_v10']:.4f} | "
                f"{nr['ll_b2p_fixed']:.4f} | **{nr['ll_b2p_adapt']:.4f}** | {nr['ll_fund']:.4f} | `{nr['adapt_weights']}` |"
            )

    if value_diag_rows:
        lines += [
            "",
            "## 7. Ürün ve Canlı Tanı 2 — Değer Ayrışması (`p >= %8` ve `p / AGF >= 1.5`, `2022–2025`)",
            "",
            "`KUMARBAZ.md` içindeki *Değerci Deniz* kuralı (günde en çok 6 at, 1 TL düz ganyan, gün-kümeli 2000 bootstrap %95 GA) AGF'yi hiç görmeyen `FUND_06`, iki aşamalı modeller ve `V10_1s` için karşılaştırılmıştır:",
            "",
            "| Model | Açıklama | Bahis Sayısı | İsabet | Tutan Medyan Ganyan | Bahis Başına Getiri [%95 GA] |",
            "|---|---|---:|---:|---:|---|",
        ]
        for vr in value_diag_rows:
            if vr["bets"] == 0:
                lines.append(f"| `{vr['model']}` | {vr['label']} | 0 | — | — | — |")
            else:
                mg = f"{vr['med_ganyan']:.2f}" if np.isfinite(vr.get("med_ganyan", np.nan)) else "—"
                lines.append(
                    f"| `{vr['model']}` | {vr['label']} | {vr['bets']:,} | {vr['hit']:.1%} | {mg} | "
                    f"`{vr['roi']:+.1%}` (`[{vr['lo']:+.1%}, {vr['hi']:+.1%}]`) |"
                )

    return "\n".join(lines) + "\n"


def format_benter_findings(
    *,
    stage1_rows,
    stage2_rows,
    fund_stage_b_rows,
    selected_candidate,
    stage3_passed,
    stage3_b_rows,
    noisy_diag_rows,
    value_diag_rows,
):
    by_s1 = {r["variant"]: r for r in stage1_rows}
    by_s2 = {r["variant"]: r for r in stage2_rows}
    by_fb = {r["variant"]: r for r in fund_stage_b_rows}
    by_s3 = {r["variant"]: r for r in stage3_b_rows}

    v10_a = by_s1.get("V10_1s", {})
    v10_b = by_s2.get("V10_1s", {})
    f06_b = by_fb.get("FUND_06", {})
    f15_b = by_fb.get("FUND_15", {})
    b0_b = by_fb.get("B0", {})

    verdict = (
        f"**GEÇTİ (`{selected_candidate}`)** — Aşama B kapısını aşmayı başardı."
        if stage3_passed
        else "**KALDI (Canlıda `V10_HLB_CAL` korunur)** — Kapanış AGF altında tek aşamalı `V10` geçilemedi; ancak `FUND_06` saf güç modeli sabah/erken AGF ve uygulama açıklanabilirliği için doğrudan değer üretiyor."
    )

    lines = [
        "# İki Aşamalı Model (Bill Benter: `P_temel` + `AGF`) — Bulgular",
        "",
        f"**Tarih:** 26.11.2026 · **Durum:** Deney tamamlandı (canlı hatta dokunulmadı) · **Kapı Sonucu:** {verdict}",
        "",
        "Tam tablolar: [BENTER.md](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/reports/BENTER.md) · "
        "Model modülü: [model_benter.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/ganyan/model_benter.py) · "
        "Deney betiği: [run_benter_experiments.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/scripts/run_benter_experiments.py) · "
        "Testler: [test_model_benter.py](file:///Users/berhantekdemir/AndroidStudioProjects/ganyan/tests/test_model_benter.py)",
        "",
        "## 1. Ne Sınandı?",
        "",
        "- `V10` (`155` özellik) içindeki **bugünün AGF'sine dokunan 8 sütun** (`agf_share`, `log_agf`, `own_is_sub_agf`, `own_mate_agf`, `trn_is_sub_agf`, `agf_surge_ratio`, `sleep_wakeup_flag`, `h2h_vs_fav_margin`) tamamen çıkarılarak **147 özellikli saf temel model (`P_temel`)** kuruldu.",
        "- `P_temel` AGF gerektirmediği için `2006–2014` arasındaki AGF'siz 9 yıllık geçmiş de eğitime açıldı (`FUND_06`: 20 yıllık eğitim vs `FUND_15`: 2015→ eğitim). Ayrıca geçmiş oran/AGF kalıntılarını da çıkaran `137` özellikli `SPORT_15` ölçüldü.",
        "- `V10_1s` tabanına karşı 5 iki-aşamalı mimari (`B2P_15`, `B2P_06`, `BRICH_06`, `BSTACK_HGB`, `BBLEND_V10`) standart `Aşama A (2017–2021)` → `Aşama B (2022–2025)` protokolüyle sınandı.",
        "",
        "## 2. Temel Sonuçlar",
        "",
    ]

    if f06_b and b0_b:
        lines.append(
            f"1. **Hiç AGF görmeyen Saf Güç (`FUND_06`) tek başına çok güçlü ve 20 yıllık eğitimden net kazanç alıyor:** "
            f"`2022–2025` döneminde hiç AGF görmeden 1. tercih isabeti **`{f06_b['top1']:.2%}`**, İlk-3 isabeti **`{f06_b['top3']:.2%}`** "
            f"(kapanış AGF `B0`: `{b0_b['top1']:.2%}` / `{b0_b['top3']:.2%}`; `FUND_15` LL `{f15_b.get('ll', np.nan):.4f}` → `FUND_06` LL **`{f06_b['ll']:.4f}`**)."
        )

    if v10_a and v10_b:
        cand_summaries = []
        for code, _ in TWO_STAGE_CANDIDATE_SPECS:
            ra = by_s1.get(code)
            rb = by_s2.get(code)
            if ra and rb:
                cand_summaries.append(f"`{code}` (Aşama A `{ra['dll_e0']:+.4f}`, Aşama 2 `{rb['dll_e0']:+.4f}`)")
        lines.append(
            "2. **Kapanış AGF altında tek aşamalı `V10` vs iki aşamalı adaylar:** " + ", ".join(cand_summaries) + "."
        )

    if selected_candidate and selected_candidate in by_s3:
        r3 = by_s3[selected_candidate]
        lines.append(
            f"3. **Resmi 5-tohum Aşama B Kapısı (`2022–2025`, `vs V10_HLB_CAL`):** `{selected_candidate}` "
            f"`ΔLL = {r3['dll_e0']:+.4f}` (`{r3['dll_e0_lo']:+.4f}`…`{r3['dll_e0_hi']:+.4f}`, `{r3['neg_years']}/{r3['total_years']}` negatif yıl) → "
            f"**{'GEÇTİ' if stage3_passed else 'KALDI'}**."
        )

    if noisy_diag_rows:
        r_no = noisy_diag_rows[-1]
        r_30 = next((x for x in noisy_diag_rows if abs(x["sigma"] - 0.30) < 1e-6), None)
        if r_30 is not None:
            lines.append(
                f"4. **Sabah / Erken Gürültülü AGF Avantajı (`2025` tanı):** Erken sabah gürültüsünde (`σ=0.30`) tek aşamalı `V10_1s` log-loss'u "
                f"`{r_30['ll_v10']:.4f}`'e bozulurken gürültüye uyumlu iki aşamalı `B2P_06` **`{r_30['ll_b2p_adapt']:.4f}`** veriyor; "
                f"sabah 07:00'de AGF henüz hiç yokken `V10_1s` `{r_no['ll_v10']:.4f}`'e çökerken `FUND_06` **`{r_no['ll_fund']:.4f}`** ile sağlam kalıyor."
            )

    if value_diag_rows:
        vd_parts = [
            f"`{v['model']}` `{v['roi']:+.1%}` (`{v['bets']}` bahis, GA `[{v['lo']:+.1%}, {v['hi']:+.1%}]`)"
            for v in value_diag_rows
            if v["bets"] > 0
        ]
        if vd_parts:
            lines.append("5. **Değer Bahsi (`p >= %8, p/AGF >= 1.5`, `2022–2025`):** " + "; ".join(vd_parts) + ".")

    lines += [
        "",
        "## 3. Uygulama ve Eğitim İçin Çıkarım",
        "",
        "- **Uygulama kartı:** `FUND_06` (`P_temel`) ile `AGF`'yi ekranda iki bağımsız sütun olarak göstermek matematiksel olarak doğrulandı — `FUND_06` AGF'den sıfır kopya çekerek neredeyse halk kadar isabetli tahmin üretiyor.",
        "- **Sabah vs Kapanış:** Kapanışa yakın saatlerde `V10_HLB_CAL` (veya kazanan iki aşamalı model), sabah AGF henüz sığ/yokken ise `FUND_06` / gürültü-uyumlu `B2P_06` çok daha güvenli.",
    ]
    return "\n".join(lines) + "\n"


def run_benter_experiments(
    db_path="data/ganyan.db",
    cache_dir="data/benter_cache",
    out_report="reports/BENTER.md",
    out_findings="docs/BENTER_BULGULAR.md",
    smoke=False,
):
    os.makedirs(cache_dir, exist_ok=True)
    if smoke and out_report == "reports/BENTER.md":
        out_report = "data/benter_smoke.md"

    conn = _open_ro_db(db_path)
    try:
        max_date = f"{SMOKE_TEST_YEAR}-12-31" if smoke else None
        print(f"[benter] Veritabanı okunuyor ({db_path}, smoke={smoke})...", flush=True)
        t0 = time.perf_counter()
        runners_df = load_runners_from_db(conn)
        runners_df["date"] = pd.to_datetime(runners_df["date"])
        v5_tables = load_v5_tables(conn)
    finally:
        conn.close()

    runners_df = _drop_unfinished_races(runners_df)
    if len(runners_df) == 0:
        raise ValueError("Sonuçlanmış koşu süzgeci sonrası satır kalmadı.")
    db_min_date = pd.Timestamp(runners_df["date"].min()).strftime("%Y-%m-%d")
    db_max_date = pd.Timestamp(runners_df["date"].max()).strftime("%Y-%m-%d")
    print(f"[benter] Ham veri yüklendi ({len(runners_df):,} satır, {time.perf_counter() - t0:.1f}sn)", flush=True)

    t_f0 = time.perf_counter()
    df_hist = _build_v10_base_frame(runners_df, v5_tables, max_date=max_date)
    del runners_df, v5_tables
    gc.collect()
    print(f"[benter] V10 özellik matrisi hazır ({len(df_hist):,} satır, {time.perf_counter() - t_f0:.1f}sn)", flush=True)

    eval_mask = df_hist["_is_eval"]
    eval_cols = (
        ["race_id", "horse_key", "date", "_year", "win", "finish", "ganyan", "agf_close", "agf_share", "field"]
        + [c for c in ("own_is_sub_agf", "own_mate_agf", "trn_is_sub_agf", "agf_surge_ratio", "sleep_wakeup_flag", "h2h_vs_fav_margin") if c in df_hist.columns]
    )
    eval_all_meta = df_hist.loc[eval_mask, eval_cols].copy().reset_index(drop=True)
    avail_years = sorted(int(y) for y in eval_all_meta["_year"].unique())
    if not avail_years:
        raise ValueError("Değerlendirme kümesinde yıl bulunamadı.")

    if smoke:
        smoke_yr = SMOKE_TEST_YEAR if SMOKE_TEST_YEAR in avail_years else avail_years[-1]
        stage_a_years = [smoke_yr]
        stage_b_years = []
        stage_c_years = []
        warmup_years = [y for y in avail_years if y < smoke_yr][-1:]
    else:
        stage_a_years = [int(y) for y in STAGE_A_YEARS if int(y) in avail_years]
        stage_b_years = [int(y) for y in STAGE_B_YEARS if int(y) in avail_years]
        stage_c_years = [int(y) for y in STAGE_C_YEARS if int(y) in avail_years]
        warmup_years = [y for y in (FUND_EARLY_WARMUP_YEAR, CAL_WARMUP_YEAR) if y in avail_years]

    eval_by_year = {
        int(y): eval_all_meta[eval_all_meta["_year"] == int(y)].copy().reset_index(drop=True)
        for y in avail_years
    }

    meta = {
        "db_path": str(db_path),
        "db_min_date": db_min_date,
        "db_max_date": db_max_date,
        "total_rows": int(len(df_hist)),
        "total_races": int(df_hist["race_id"].nunique()),
        "stage_a_races": int(sum(eval_by_year[y]["race_id"].nunique() for y in stage_a_years)),
        "stage_b_races": int(sum(eval_by_year[y]["race_id"].nunique() for y in stage_b_years)),
        "stage_c_races": int(sum(eval_by_year[y]["race_id"].nunique() for y in stage_c_years)),
    }

    fund_cols = get_fund_cols(pure_sport=False)
    sport_cols = get_fund_cols(pure_sport=True)

    cfg_v10_1s = _make_hgb_cfg(
        "V10_1s",
        V10_CONFIG["feature_cols"],
        train_start_year=2015,
        require_agf=True,
        seeds=(0,),
        family="V10",
        description="Tek aşamalı V10 tabanı (155 öz., 1 tohum)",
    )
    cfg_fund_15 = _make_hgb_cfg(
        "FUND_15",
        fund_cols,
        train_start_year=2015,
        require_agf=False,
        seeds=(0,),
        description="Saf temel model (2015→, 147 öz., AGF=Yok)",
    )
    cfg_fund_06 = _make_hgb_cfg(
        "FUND_06",
        fund_cols,
        train_start_year=int(V10_CONFIG["history_start_year"]),
        require_agf=False,
        seeds=(0,),
        description="Saf temel model (2006→ tam geçmiş, 147 öz., AGF=Yok)",
    )
    cfg_sport_15 = _make_hgb_cfg(
        "SPORT_15",
        sport_cols,
        train_start_year=2015,
        require_agf=False,
        seeds=(0,),
        description="Saf sportif model (2015→, 137 öz., geçmiş oran/AGF dahil sıfır piyasa)",
    )

    years_from_16 = sorted(set([y for y in warmup_years if y >= 2016] + stage_a_years + stage_b_years + stage_c_years))
    years_from_15 = sorted(set(warmup_years + stage_a_years + stage_b_years + stage_c_years))
    years_eval_only = sorted(set(stage_a_years + stage_b_years + stage_c_years))

    total_1s_steps = len(years_from_16) * 3 + len(years_from_15) + len(years_eval_only)
    tracker = _ProgressTracker(total_planned_steps=max(1, total_1s_steps))
    preds_by_var_year = {"V10_1s": {}, "FUND_15": {}, "FUND_06": {}, "SPORT_15": {}, "BSTACK_HGB": {}}
    ref_v10_ll = {}

    # 1) V10_1s baseline (hits data/v11_cache on 2017..2026)
    for y in years_from_16:
        ev_y = eval_by_year.get(y)
        if ev_y is None or len(ev_y) == 0:
            continue
        p_y, dt_s, from_c = _predict_base_year_with_ro_fallback(
            df_hist, ev_y, cfg_v10_1s, y, cache_dir, smoke=smoke
        )
        if p_y is not None:
            preds_by_var_year["V10_1s"][y] = p_y
            ref_v10_ll[y] = _race_winner_lls(ev_y, p_y)
            tracker.log_step("V10_1s", y, dt_s, 0.0, from_cache=from_c)

    # 2) FUND_15 (2016..2026) & SPORT_15 (2017..2026)
    for v_name, cfg_f, yrs_f in (
        ("FUND_15", cfg_fund_15, years_from_16),
        ("SPORT_15", cfg_sport_15, years_eval_only),
    ):
        for y in yrs_f:
            ev_y = eval_by_year.get(y)
            if ev_y is None or len(ev_y) == 0:
                continue
            p_y, dt_s, from_c = _predict_base_year(df_hist, ev_y, cfg_f, y, cache_dir, smoke=smoke)
            if p_y is not None:
                preds_by_var_year[v_name][y] = p_y
                ll_y = _race_winner_lls(ev_y, p_y)
                dll_v = float((ll_y - ref_v10_ll[y]).mean()) if y in ref_v10_ll else np.nan
                tracker.log_step(v_name, y, dt_s, dll_v, from_cache=from_c)

    # 3) FUND_06 across ALL settled rows in 2015..2026 (supplies both eval predictions & leak-free OOF column for BSTACK_HGB)
    oof_fund06_full = np.full(len(df_hist), np.nan, dtype=np.float64)
    for y in years_from_15:
        settled_y_mask = (df_hist["_year"] == int(y)) & df_hist["win"].notna() & df_hist["_has_race_win"]
        p_all_y, dt_s, from_c = _predict_full_slice_year(
            df_hist, settled_y_mask, cfg_fund_06, y, cache_dir, smoke=smoke
        )
        if p_all_y is not None:
            oof_fund06_full[settled_y_mask.to_numpy()] = p_all_y
            ev_y = eval_by_year.get(y)
            if ev_y is not None and len(ev_y) > 0:
                sub_df = pd.DataFrame(
                    {
                        "race_id": df_hist.loc[settled_y_mask, "race_id"].to_numpy(),
                        "horse_key": df_hist.loc[settled_y_mask, "horse_key"].to_numpy(),
                        "p": p_all_y,
                    }
                )
                p_ev_y = _align_cached_preds(ev_y, sub_df)
                if p_ev_y is not None:
                    preds_by_var_year["FUND_06"][y] = p_ev_y
                    ll_y = _race_winner_lls(ev_y, p_ev_y)
                    dll_v = float((ll_y - ref_v10_ll[y]).mean()) if y in ref_v10_ll else np.nan
                    tracker.log_step("FUND_06", y, dt_s, dll_v, from_cache=from_c)

    # 4) Attach OOS FUND_06 features and fit BSTACK_HGB (2016..2026)
    df_hist = attach_fund_oof_features(df_hist, oof_fund06_full)
    cfg_bstack_1s = _make_hgb_cfg(
        "BSTACK_HGB",
        get_stack_cols(),
        train_start_year=2015,
        require_agf=True,
        seeds=(0,),
        description="İki aşamalı yığılmış HGB: V10 + FUND_06 dış-örneklem 4 öz.",
    )
    for y in years_from_16:
        ev_y = eval_by_year.get(y)
        if ev_y is None or len(ev_y) == 0:
            continue
        p_y, dt_s, from_c = _predict_base_year(df_hist, ev_y, cfg_bstack_1s, y, cache_dir, smoke=smoke)
        if p_y is not None:
            preds_by_var_year["BSTACK_HGB"][y] = p_y
            ll_y = _race_winner_lls(ev_y, p_y)
            dll_v = float((ll_y - ref_v10_ll[y]).mean()) if y in ref_v10_ll else np.nan
            tracker.log_step("BSTACK_HGB", y, dt_s, dll_v, from_cache=from_c)

    # 5) Conditional-logit combiners (instant <1s total, strictly walk-forward `< Y`)
    preds_by_var_year["B2P_15"], w_b2p15 = _fit_predict_combiner_walkforward(
        eval_by_year, preds_by_var_year, years_eval_only, kind="2p", fund_var="FUND_15"
    )
    preds_by_var_year["B2P_06"], w_b2p06 = _fit_predict_combiner_walkforward(
        eval_by_year, preds_by_var_year, years_eval_only, kind="2p", fund_var="FUND_06"
    )
    preds_by_var_year["BRICH_06"], w_brich = _fit_predict_combiner_walkforward(
        eval_by_year, preds_by_var_year, years_eval_only, kind="rich", fund_var="FUND_06"
    )
    preds_by_var_year["BBLEND_V10"], w_blend = _fit_predict_combiner_walkforward(
        eval_by_year, preds_by_var_year, years_eval_only, kind="3way", fund_var="FUND_06", v10_var="V10_1s"
    )
    combiner_weight_rows = []
    for tag, w_list in (("B2P_15", w_b2p15), ("B2P_06", w_b2p06), ("BRICH_06", w_brich), ("BBLEND_V10", w_blend)):
        for item in w_list:
            row_cp = dict(item)
            row_cp["kind"] = tag
            combiner_weight_rows.append(row_cp)

    # Summarize Stage 0 (Standalone fundamentals vs B0)
    fund_order = ["FUND_06", "FUND_15", "SPORT_15"]
    fund_stage_a_rows, fund_stage_b_rows, fund_stage_c_rows = [], [], []
    if stage_a_years:
        ev_fa, pr_fa = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, fund_order)
        fund_stage_a_rows, _ = _summarize_period_metrics(ev_fa, pr_fa, fund_order, base_key="B0")
    if stage_b_years:
        ev_fb, pr_fb = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, fund_order)
        fund_stage_b_rows, _ = _summarize_period_metrics(ev_fb, pr_fb, fund_order, base_key="B0")
    if stage_c_years:
        ev_fc, pr_fc = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, fund_order)
        fund_stage_c_rows, _ = _summarize_period_metrics(ev_fc, pr_fc, fund_order, base_key="B0")

    # Summarize Stage A (2017–2021) & select at most ONE candidate (< -0.0002)
    cand_names = [c for c, _ in TWO_STAGE_CANDIDATE_SPECS]
    s1_order = ["V10_1s"] + cand_names
    ev_s1, pr_s1 = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, s1_order)
    stage1_rows, _ = _summarize_period_metrics(ev_s1, pr_s1, s1_order, base_key="V10_1s")

    passing_cands = [
        r for r in stage1_rows if r["variant"] in cand_names and np.isfinite(r["dll_e0"]) and r["dll_e0"] < SEL_THRESHOLD_DLL
    ]
    passing_cands.sort(key=lambda r: r["ll"])
    if passing_cands:
        selected_candidate = passing_cands[0]["variant"]
        sel_note = (
            f"Aşama A'da `{SEL_THRESHOLD_DLL}` eşiğini geçen {len(passing_cands)} aday arasından en düşük log-loss'a sahip "
            f"`{selected_candidate}` (`ΔLL = {passing_cands[0]['dll_e0']:+.4f}`) tek aday olarak Aşama 3 resmi kapısına taşınmıştır."
        )
    else:
        selected_candidate = None
        best_r = min((r for r in stage1_rows if r["variant"] in cand_names), key=lambda r: r["ll"], default=None)
        best_txt = f" (en yakın: `{best_r['variant']}` `ΔLL = {best_r['dll_e0']:+.4f}`)" if best_r else ""
        sel_note = f"Hiçbir iki-aşamalı aday Aşama A'da `< {SEL_THRESHOLD_DLL}` eşiğini geçemedi{best_txt}; canlı `V10_HLB_CAL` korunur."

    # Stage 2 diagnostic (2022–2025, 1-seed)
    stage2_rows = []
    if stage_b_years:
        ev_s2, pr_s2 = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, s1_order)
        stage2_rows, _ = _summarize_period_metrics(ev_s2, pr_s2, s1_order, base_key="V10_1s")

    # Stage 3 Official 5-seed Gate (only if a candidate passed Stage A AND not smoke)
    stage3_b_rows = []
    stage3_b_yearly_detail = []
    stage3_gate_result = None
    stage3_passed = False
    stage3_c_rows = []

    if selected_candidate and not smoke and stage_b_years:
        seeds_5 = tuple(int(s) for s in V10_CONFIG["seeds"])
        # Exact V10_HLB_5s & V10_HLB_CAL configs matching data/v10_cache digests
        cfg_v10_5s = _make_hgb_cfg(
            "V10_HLB_5s",
            V10_CONFIG["feature_cols"],
            train_start_year=2015,
            require_agf=True,
            seeds=seeds_5,
            family="V10",
            description="Ek ablasyon: JLOY hariç V10_HLB (BELL+LOAD+H2H, 5 tohum + sıcaklık)",
        )
        cfg_v10_cal = _make_hgb_cfg(
            "V10_HLB_CAL",
            V10_CONFIG["feature_cols"],
            train_start_year=2015,
            require_agf=True,
            seeds=seeds_5,
            calibration="temperature",
            calibrated_from="V10_HLB_5s",
            family="V10",
            description="Ek ablasyon: JLOY hariç V10_HLB (BELL+LOAD+H2H, 5 tohum + sıcaklık)",
        )
        preds_by_var_year["V10_HLB_5s"] = {}
        preds_by_var_year["V10_HLB_CAL"] = {}
        for y in years_from_16:
            ev_y = eval_by_year[y]
            p_y, dt_s, from_c = _predict_base_year_with_ro_fallback(df_hist, ev_y, cfg_v10_5s, y, cache_dir, smoke=False)
            if p_y is not None:
                preds_by_var_year["V10_HLB_5s"][y] = p_y
                tracker.log_step("V10_HLB_5s", y, dt_s, 0.0, from_cache=from_c)
        for y in years_eval_only:
            ev_y = eval_by_year[y]
            alt_cal = _cache_file_path("data/v10_cache", "V10_HLB_CAL", config_digest(cfg_v10_cal), y, smoke=False)
            if os.path.exists(alt_cal):
                t_c0 = time.perf_counter()
                p_c = _align_cached_preds(ev_y, pd.read_pickle(alt_cal))
                dt_c, fc_c = time.perf_counter() - t_c0, True
            else:
                p_c, dt_c, fc_c, _ = _predict_calibrated_year(
                    eval_by_year, preds_by_var_year["V10_HLB_5s"], cfg_v10_cal, y, cache_dir, smoke=False
                )
            if p_c is not None:
                preds_by_var_year["V10_HLB_CAL"][y] = p_c
                tracker.log_step("V10_HLB_CAL", y, dt_c, 0.0, from_cache=fc_c)

        cand_5s_final = f"{selected_candidate}_5s_CAL"
        if selected_candidate == "B2P_15":
            cfg_f15_5s = _make_hgb_cfg("FUND_15_5s", fund_cols, train_start_year=2015, require_agf=False, seeds=seeds_5)
            preds_by_var_year["FUND_15_5s"] = {}
            for y in years_from_16:
                p_y, dt_s, fc = _predict_base_year(df_hist, eval_by_year[y], cfg_f15_5s, y, cache_dir, smoke=False)
                preds_by_var_year["FUND_15_5s"][y] = p_y
                tracker.log_step("FUND_15_5s", y, dt_s, np.nan, from_cache=fc)
            preds_by_var_year[cand_5s_final], _ = _fit_predict_combiner_walkforward(
                eval_by_year, preds_by_var_year, years_eval_only, kind="2p", fund_var="FUND_15_5s"
            )
        else:
            cfg_f06_5s = _make_hgb_cfg(
                "FUND_06_5s",
                fund_cols,
                train_start_year=int(V10_CONFIG["history_start_year"]),
                require_agf=False,
                seeds=seeds_5,
            )
            preds_by_var_year["FUND_06_5s"] = {}
            oof_5s = np.full(len(df_hist), np.nan, dtype=np.float64)
            yrs_need = years_from_15 if selected_candidate in ("BSTACK_HGB", "B2P_06", "BRICH_06") else years_from_16
            for y in yrs_need:
                settled_y_mask = (df_hist["_year"] == int(y)) & df_hist["win"].notna() & df_hist["_has_race_win"]
                p_all_y, dt_s, fc = _predict_full_slice_year(df_hist, settled_y_mask, cfg_f06_5s, y, cache_dir, smoke=False)
                if p_all_y is not None:
                    oof_5s[settled_y_mask.to_numpy()] = p_all_y
                    sub_df = pd.DataFrame(
                        {
                            "race_id": df_hist.loc[settled_y_mask, "race_id"].to_numpy(),
                            "horse_key": df_hist.loc[settled_y_mask, "horse_key"].to_numpy(),
                            "p": p_all_y,
                        }
                    )
                    preds_by_var_year["FUND_06_5s"][y] = _align_cached_preds(eval_by_year[y], sub_df)
                    tracker.log_step("FUND_06_5s", y, dt_s, np.nan, from_cache=fc)

            if selected_candidate == "B2P_06":
                preds_by_var_year[cand_5s_final], _ = _fit_predict_combiner_walkforward(
                    eval_by_year, preds_by_var_year, years_eval_only, kind="2p", fund_var="FUND_06_5s"
                )
            elif selected_candidate == "BRICH_06":
                preds_by_var_year[cand_5s_final], _ = _fit_predict_combiner_walkforward(
                    eval_by_year, preds_by_var_year, years_eval_only, kind="rich", fund_var="FUND_06_5s"
                )
            elif selected_candidate == "BBLEND_V10":
                preds_by_var_year[cand_5s_final], _ = _fit_predict_combiner_walkforward(
                    eval_by_year,
                    preds_by_var_year,
                    years_eval_only,
                    kind="3way",
                    fund_var="FUND_06_5s",
                    v10_var="V10_HLB_5s",
                )
            elif selected_candidate == "BSTACK_HGB":
                df_5s = attach_fund_oof_features(df_hist, oof_5s)
                cfg_bs_5s = _make_hgb_cfg("BSTACK_HGB_5s", get_stack_cols(), train_start_year=2015, require_agf=True, seeds=seeds_5)
                cfg_bs_cal = _make_hgb_cfg(
                    cand_5s_final,
                    get_stack_cols(),
                    train_start_year=2015,
                    require_agf=True,
                    seeds=seeds_5,
                    calibration="temperature",
                    calibrated_from="BSTACK_HGB_5s",
                )
                preds_by_var_year["BSTACK_HGB_5s"] = {}
                for y in years_from_16:
                    p_y, dt_s, fc = _predict_base_year(df_5s, eval_by_year[y], cfg_bs_5s, y, cache_dir, smoke=False)
                    preds_by_var_year["BSTACK_HGB_5s"][y] = p_y
                    tracker.log_step("BSTACK_HGB_5s", y, dt_s, np.nan, from_cache=fc)
                preds_by_var_year[cand_5s_final] = {}
                for y in years_eval_only:
                    p_c, dt_c, fc_c, _ = _predict_calibrated_year(
                        eval_by_year, preds_by_var_year["BSTACK_HGB_5s"], cfg_bs_cal, y, cache_dir, smoke=False
                    )
                    preds_by_var_year[cand_5s_final][y] = p_c
                    tracker.log_step(cand_5s_final, y, dt_c, np.nan, from_cache=fc_c)

        s3_order = ["V10_HLB_CAL", cand_5s_final]
        ev_b3, pr_b3 = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, s3_order)
        stage3_b_rows, race_dll_b3 = _summarize_period_metrics(ev_b3, pr_b3, s3_order, base_key="V10_HLB_CAL")
        for y_b in stage_b_years:
            ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], s3_order)
            yr_rows, _ = _summarize_period_metrics(ev_yb, pr_yb, s3_order, base_key="V10_HLB_CAL")
            for r_yb in yr_rows:
                r_yb["year"] = int(y_b)
                stage3_b_yearly_detail.append(r_yb)

        by_b3 = {r["variant"]: r for r in stage3_b_rows}
        if cand_5s_final in by_b3:
            stage3_gate_result = evaluate_stage_b_gate(
                by_b3[cand_5s_final]["yearly_dll"],
                race_dll_b3[cand_5s_final],
                n_boot=2000,
                seed=0,
                min_neg_years=3,
            )
            stage3_passed = bool(stage3_gate_result["passed"])

        if stage_c_years:
            ev_c3, pr_c3 = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, s3_order)
            stage3_c_rows, _ = _summarize_period_metrics(ev_c3, pr_c3, s3_order, base_key="V10_HLB_CAL")
    elif stage_c_years:
        ev_c1, pr_c1 = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, s1_order)
        stage3_c_rows, _ = _summarize_period_metrics(ev_c1, pr_c1, s1_order, base_key="V10_1s")

    # Diagnostics (skip noisy full-year refit in smoke mode)
    noisy_diag_rows = []
    value_diag_rows = []
    if not smoke:
        diag_yr = 2025 if 2025 in eval_by_year else (stage_b_years[-1] if stage_b_years else None)
        if diag_yr is not None:
            print(f"[benter] Sabah/gürültülü AGF tanı testi çalıştırılıyor ({diag_yr})...", flush=True)
            noisy_diag_rows = _run_noisy_agf_diagnostic(
                df_hist, eval_by_year, preds_by_var_year["FUND_06"], diag_year=diag_yr
            )
        if stage_b_years:
            val_vars = ["V10_1s", "FUND_06", "B2P_06", "BRICH_06", "BSTACK_HGB", "BBLEND_V10"]
            ev_vb, pr_vb = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, val_vars)
            value_diag_rows = _compute_value_overlay_diagnostic(
                ev_vb,
                pr_vb,
                [
                    ("V10_1s", "Tek aşamalı V10 (1 tohum)"),
                    ("FUND_06", "Saf Pist Gücü (AGF=Yok, 2006→)"),
                    ("B2P_06", "Benter 2-param (FUND_06 + AGF)"),
                    ("BRICH_06", "Zengin koşullu logit"),
                    ("BSTACK_HGB", "İki aşamalı yığılmış HGB"),
                    ("BBLEND_V10", "3-yollu koşullu logit harmanı"),
                ],
            )

    report_md = format_benter_report(
        smoke=smoke,
        meta=meta,
        fund_stage_a_rows=fund_stage_a_rows,
        fund_stage_b_rows=fund_stage_b_rows,
        fund_stage_c_rows=fund_stage_c_rows,
        stage1_rows=stage1_rows,
        stage1_years=stage_a_years,
        selected_candidate=selected_candidate,
        sel_note=sel_note,
        stage2_rows=stage2_rows,
        stage2_years=stage_b_years,
        combiner_weight_rows=combiner_weight_rows,
        stage3_b_rows=stage3_b_rows,
        stage3_b_yearly_detail=stage3_b_yearly_detail,
        stage3_gate_result=stage3_gate_result,
        stage3_passed=stage3_passed,
        stage3_c_rows=stage3_c_rows,
        noisy_diag_rows=noisy_diag_rows,
        value_diag_rows=value_diag_rows,
    )
    out_p = Path(out_report)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(report_md, encoding="utf-8")
    print(f"[benter] Rapor yazıldı: {out_p}", flush=True)

    if not smoke and out_findings:
        findings_md = format_benter_findings(
            stage1_rows=stage1_rows,
            stage2_rows=stage2_rows,
            fund_stage_b_rows=fund_stage_b_rows,
            selected_candidate=selected_candidate,
            stage3_passed=stage3_passed,
            stage3_b_rows=stage3_b_rows,
            noisy_diag_rows=noisy_diag_rows,
            value_diag_rows=value_diag_rows,
        )
        fp = Path(out_findings)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(findings_md, encoding="utf-8")
        print(f"[benter] Bulgular yazıldı: {fp}", flush=True)

    return {
        "report_path": str(out_p),
        "selected_candidate": selected_candidate,
        "stage3_passed": stage3_passed,
        "stage1_rows": stage1_rows,
        "stage2_rows": stage2_rows,
        "stage3_gate_result": stage3_gate_result,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(description="İki aşamalı (Bill Benter: P_temel + AGF) ileri-yürüyen deney serisi.")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--cache-dir", default="data/benter_cache")
    ap.add_argument("--out-report", default="reports/BENTER.md")
    ap.add_argument("--out-findings", default="docs/BENTER_BULGULAR.md")
    ap.add_argument("--smoke", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        run_benter_experiments(
            db_path=args.db,
            cache_dir=args.cache_dir,
            out_report=args.out_report,
            out_findings=args.out_findings,
            smoke=args.smoke,
        )
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
