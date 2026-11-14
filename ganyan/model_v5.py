"""Model v5: program-free base feature sets, fundamental HGB wrapper, Benter combiner, and edge ROI."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ganyan.features import get_feature_cols
from ganyan.features_v5 import BLOCK_COLS as _FEATURES_BLOCK_COLS
from ganyan.model import fit_predict_df

PROGRAM_COLS = ("son6_last", "son6_mean", "son6_same_surf", "kgs", "s20", "best_sf")
_PROGRAM_SET = frozenset(PROGRAM_COLS)

BASE_COLS = [c for c in get_feature_cols()[0] if c not in _PROGRAM_SET]
BLOCK_COLS = {k: list(v) for k, v in _FEATURES_BLOCK_COLS.items()}

EDGE_BUCKET_LABELS = [
    "<0.8",
    "0.8–0.95",
    "0.95–1.05",
    "1.05–1.2",
    "1.2–1.5",
    ">1.5",
]


def get_base_cols(with_program=False):
    """Return base (no-AGF) feature list, optionally retaining program-derived columns."""
    raw_base, _ = get_feature_cols()
    if with_program:
        return list(raw_base)
    return list(BASE_COLS)


def get_b1_cols(with_program=False):
    """Return v1_agf feature list, optionally retaining program-derived columns."""
    _, raw_with_agf = get_feature_cols()
    if with_program:
        return list(raw_with_agf)
    return [c for c in raw_with_agf if c not in _PROGRAM_SET]


def fit_predict_fund(train_df, test_df, cols):
    """Fit fundamental (AGF-free) HGB model on `train_df[cols]` and predict race-normalized probs."""
    return fit_predict_df(train_df, test_df, list(cols))


def to_log_prob(p, clip_min=1e-6):
    """Clip probabilities at `clip_min` (default 1e-6) and return natural log."""
    arr = np.asarray(p, dtype=np.float64)
    return np.log(np.clip(arr, clip_min, None))


def _ensure_log_prob(x, clip_min=1e-6):
    """Accept either log-probabilities (<= 0) or raw probabilities in [0, 1] (`clip(1e-6)` before `log`)."""
    arr = np.asarray(x, dtype=np.float64)
    if arr.size == 0:
        return arr.copy()
    finite = arr[np.isfinite(arr)]
    if finite.size > 0 and np.min(finite) >= 0.0 and np.max(finite) > 0.0 and np.max(finite) <= 1.0 + 1e-6:
        return np.log(np.clip(arr, clip_min, None))
    return np.where(np.isneginf(arr), np.log(clip_min), arr)


def _group_races_contiguous(race_ids):
    """Factorize `race_ids` and return `(order, starts, ends, counts)` for contiguous race segments."""
    r_code, _ = pd.factorize(pd.Series(race_ids).astype("string"), sort=False)
    order = np.argsort(r_code, kind="mergesort")
    r_sorted = r_code[order]
    if len(r_sorted) == 0:
        empty = np.zeros(0, dtype=np.int64)
        return order, empty, empty, empty
    starts = np.r_[0, np.flatnonzero(r_sorted[1:] != r_sorted[:-1]) + 1]
    ends = np.r_[starts[1:], len(r_sorted)]
    counts = ends - starts
    return order, starts, ends, counts


class BenterCombiner:
    """Two-parameter (`a`, `b`) conditional logit combiner: `p_i ∝ exp(a·log p_fund_i + b·log p_agf_i)`."""

    def __init__(self, clip_min=1e-6):
        self.clip_min = float(clip_min)
        self.a = 0.0
        self.b = 1.0
        self.a_ = 0.0
        self.b_ = 1.0
        self.opt_result_ = None

    def fit(self, log_p_fund, log_p_agf, race_ids, winner_mask):
        """Maximize conditional log-likelihood of winners across races via BFGS."""
        x_raw = _ensure_log_prob(log_p_fund, self.clip_min)
        y_raw = _ensure_log_prob(log_p_agf, self.clip_min)
        w_raw = np.asarray(winner_mask, dtype=np.float64)

        if not (len(x_raw) == len(y_raw) == len(w_raw) == len(race_ids)):
            raise ValueError("log_p_fund, log_p_agf, race_ids, and winner_mask must have equal length.")

        order, starts, ends, counts = _group_races_contiguous(race_ids)
        if len(starts) == 0:
            raise ValueError("Cannot fit BenterCombiner on empty race data.")

        xs = x_raw[order]
        ys = y_raw[order]
        ws = np.where(np.isfinite(w_raw[order]) & (w_raw[order] > 0.0), w_raw[order], 0.0)

        finite_row = np.isfinite(xs) & np.isfinite(ys)
        finite_cnt = np.add.reduceat(finite_row.astype(np.int64), starts)
        w_race_sum = np.add.reduceat(ws, starts)

        valid_race = (finite_cnt == counts) & (counts >= 2) & (w_race_sum > 0.0)
        if not np.any(valid_race):
            raise ValueError("No valid multi-runner races with winners to fit BenterCombiner.")

        if not np.all(valid_race):
            keep_row = np.repeat(valid_race, counts)
            xs = xs[keep_row]
            ys = ys[keep_row]
            ws = ws[keep_row]
            counts = counts[valid_race]
            w_race_sum = w_race_sum[valid_race]
            starts = np.r_[0, np.cumsum(counts[:-1])]

        n_races = float(len(counts))
        w_race_per_row = np.repeat(w_race_sum, counts)

        def nll_and_grad(theta):
            a_val, b_val = float(theta[0]), float(theta[1])
            z = a_val * xs + b_val * ys
            m_r = np.maximum.reduceat(z, starts)
            m_row = np.repeat(m_r, counts)
            exp_z = np.exp(z - m_row)
            sum_exp = np.add.reduceat(exp_z, starts)
            log_denom = m_r + np.log(sum_exp)

            ll = np.sum(ws * z) - np.sum(w_race_sum * log_denom)
            nll = -ll / n_races

            p_row = exp_z / np.repeat(sum_exp, counts)
            diff = ws - w_race_per_row * p_row
            grad_a = -np.sum(diff * xs) / n_races
            grad_b = -np.sum(diff * ys) / n_races
            return float(nll), np.array([grad_a, grad_b], dtype=np.float64)

        res = minimize(
            nll_and_grad,
            x0=np.array([0.5, 0.5], dtype=np.float64),
            method="BFGS",
            jac=True,
        )
        self.a = float(res.x[0])
        self.b = float(res.x[1])
        self.a_ = self.a
        self.b_ = self.b
        self.opt_result_ = res
        return self

    def predict(self, log_p_fund, log_p_agf, race_ids):
        """Return race-normalized probabilities `p_i ∝ exp(a·log p_fund_i + b·log p_agf_i)`."""
        x_raw = _ensure_log_prob(log_p_fund, self.clip_min)
        y_raw = _ensure_log_prob(log_p_agf, self.clip_min)
        if not (len(x_raw) == len(y_raw) == len(race_ids)):
            raise ValueError("log_p_fund, log_p_agf, and race_ids must have equal length.")
        if len(x_raw) == 0:
            return np.zeros(0, dtype=np.float64)

        order, starts, _ends, counts = _group_races_contiguous(race_ids)
        xs = x_raw[order]
        ys = y_raw[order]

        z = self.a * xs + self.b * ys
        finite_row = np.isfinite(z)
        finite_cnt = np.add.reduceat(finite_row.astype(np.int64), starts)
        race_ok = finite_cnt == counts

        z_safe = np.where(finite_row, z, 0.0)
        m_r = np.maximum.reduceat(z_safe, starts)
        exp_z = np.exp(z_safe - np.repeat(m_r, counts))
        sum_exp = np.add.reduceat(exp_z, starts)
        p_sorted = exp_z / np.repeat(sum_exp, counts)

        if not np.all(race_ok):
            ok_row = np.repeat(race_ok, counts)
            unif = 1.0 / np.repeat(counts.astype(np.float64), counts)
            p_sorted = np.where(ok_row, p_sorted, unif)

        p_out = np.empty(len(x_raw), dtype=np.float64)
        p_out[order] = p_sorted
        return p_out


def bootstrap_mean_ci(values, n_boot=2000, seed=0):
    """Compute `(mean, ci95_low, ci95_high)` via bootstrap resampling (`default_rng(seed)`)."""
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return np.nan, np.nan, np.nan
    mean_val = float(arr.mean())
    if np.all(arr == arr[0]):
        return mean_val, mean_val, mean_val

    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=np.float64)
    chunk = max(1, min(200, max(1, 2_000_000 // n)))
    pos = 0
    while pos < n_boot:
        m = min(chunk, n_boot - pos)
        idx = rng.integers(0, n, size=(m, n))
        means[pos : pos + m] = arr[idx].mean(axis=1)
        pos += m
    return mean_val, float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _assign_edge_bucket(edge_arr):
    """Map numeric `edge = p_model / p_mkt` values to the 6 spec bucket indices `0..5` (`-1` if NaN)."""
    idx = np.full(len(edge_arr), -1, dtype=np.int32)
    fin = np.isfinite(edge_arr)
    idx[fin & (edge_arr < 0.8)] = 0
    idx[fin & (edge_arr >= 0.8) & (edge_arr < 0.95)] = 1
    idx[fin & (edge_arr >= 0.95) & (edge_arr < 1.05)] = 2
    idx[fin & (edge_arr >= 1.05) & (edge_arr < 1.2)] = 3
    idx[fin & (edge_arr >= 1.2) & (edge_arr <= 1.5)] = 4
    idx[fin & (edge_arr > 1.5)] = 5
    return idx


def compute_edge_buckets(df, p_col, n_boot=2000, seed=0):
    """Compute flat 1 TL ganyan ROI across the 6 `edge = p_model / p_mkt` buckets.

    `p_mkt` is race-normalized `1 / ganyan`.
    Returns a DataFrame with columns `bucket, bets, win_rate, roi, ci95_low, ci95_high`.
    """
    valid = df[df[p_col].notna() & df["ganyan"].notna() & (df["ganyan"] > 0) & df["win"].notna()].copy()
    if valid.empty:
        return pd.DataFrame(
            [
                {
                    "bucket": lbl,
                    "bets": 0,
                    "win_rate": np.nan,
                    "roi": np.nan,
                    "ci95_low": np.nan,
                    "ci95_high": np.nan,
                }
                for lbl in EDGE_BUCKET_LABELS
            ]
        )

    inv_g = 1.0 / valid["ganyan"].to_numpy(dtype=np.float64)
    inv_s = pd.Series(inv_g, index=valid.index)
    p_mkt = (inv_s / inv_s.groupby(valid["race_id"]).transform("sum")).to_numpy(dtype=np.float64)
    p_mod = valid[p_col].to_numpy(dtype=np.float64)
    edge = np.where(p_mkt > 0.0, p_mod / p_mkt, np.nan)

    win_arr = valid["win"].to_numpy(dtype=np.float64)
    ganyan_arr = valid["ganyan"].to_numpy(dtype=np.float64)
    net_ret = win_arr * ganyan_arr - 1.0
    b_idx = _assign_edge_bucket(edge)

    rows = []
    for bi, lbl in enumerate(EDGE_BUCKET_LABELS):
        mask = b_idx == bi
        cnt = int(np.sum(mask))
        if cnt == 0:
            rows.append(
                {
                    "bucket": lbl,
                    "bets": 0,
                    "win_rate": np.nan,
                    "roi": np.nan,
                    "ci95_low": np.nan,
                    "ci95_high": np.nan,
                }
            )
        else:
            roi_mean, ci_lo, ci_hi = bootstrap_mean_ci(net_ret[mask], n_boot=n_boot, seed=seed)
            rows.append(
                {
                    "bucket": lbl,
                    "bets": cnt,
                    "win_rate": float(win_arr[mask].mean()),
                    "roi": roi_mean,
                    "ci95_low": ci_lo,
                    "ci95_high": ci_hi,
                }
            )
    return pd.DataFrame(rows)


def compute_top1_roi(df, score_col, n_boot=2000, seed=0):
    """Compute flat 1 TL ganyan ROI when betting only the top-ranked runner per race by `score_col`."""
    valid = df[df[score_col].notna() & df["ganyan"].notna() & (df["ganyan"] > 0) & df["win"].notna()].copy()
    if valid.empty:
        return {
            "bets": 0,
            "win_rate": np.nan,
            "roi": np.nan,
            "ci95_low": np.nan,
            "ci95_high": np.nan,
        }
    rk = valid.groupby("race_id")[score_col].rank(ascending=False, method="first")
    picks = valid[rk == 1]
    win_arr = picks["win"].to_numpy(dtype=np.float64)
    ret_arr = win_arr * picks["ganyan"].to_numpy(dtype=np.float64) - 1.0
    roi_mean, ci_lo, ci_hi = bootstrap_mean_ci(ret_arr, n_boot=n_boot, seed=seed)
    return {
        "bets": int(len(picks)),
        "win_rate": float(win_arr.mean()),
        "roi": roi_mean,
        "ci95_low": ci_lo,
        "ci95_high": ci_hi,
    }
