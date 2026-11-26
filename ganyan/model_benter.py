"""Two-stage (Bill Benter) fundamental + market conditional-logit models and OOF stack helpers."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ganyan.model_v5 import _ensure_log_prob, _group_races_contiguous, to_log_prob
from ganyan.model_v10 import V10_CONFIG

# Exact 8 columns in V10_CONFIG["feature_cols"] (155) that depend on TODAY'S race AGF.
TODAY_AGF_COLS = (
    "agf_share",
    "log_agf",
    "own_is_sub_agf",
    "own_mate_agf",
    "trn_is_sub_agf",
    "agf_surge_ratio",
    "sleep_wakeup_flag",
    "h2h_vs_fav_margin",
)

# 6 auxiliary race-day AGF interaction columns (excluding raw agf_share & log_agf).
TODAY_AGF_AUX_COLS = (
    "own_is_sub_agf",
    "own_mate_agf",
    "trn_is_sub_agf",
    "agf_surge_ratio",
    "sleep_wakeup_flag",
    "h2h_vs_fav_margin",
)

# Exact 10 columns in V10_CONFIG["feature_cols"] that depend on strictly historical (< D) odds or AGF.
PAST_MKT_COLS = (
    "h_logodds_last",
    "h_logodds_m3",
    "h_logodds_m3_rel",
    "h_logodds_m3_rk",
    "trn_away_resid_730d",
    "trn_resid_14d",
    "trn_resid_28d",
    "trn_fpct_resid_28d",
    "trn_resid_28d_rel",
    "bias_gate_resid",
)

STACK_OOF_COLS = (
    "fund_log_p",
    "fund_rk_pct",
    "fund_vs_agf_log",
    "fund_minus_agf",
)

_TODAY_AGF_SET = frozenset(TODAY_AGF_COLS)
_PAST_MKT_SET = frozenset(PAST_MKT_COLS)


def get_fund_cols(pure_sport=False):
    """Return Stage-1 fundamental feature list stripped of today's AGF (and optionally past market cols).

    - ``pure_sport=False`` (default): 147 features — zero dependence on today's AGF; computable pre-pool
      and across ``2006–2014`` AGF-free history.
    - ``pure_sport=True``: 137 features — additionally removes historical ``< D`` closing odds / AGF residuals.
    """
    v10_cols = list(V10_CONFIG["feature_cols"])
    if pure_sport:
        return [c for c in v10_cols if c not in _TODAY_AGF_SET and c not in _PAST_MKT_SET]
    return [c for c in v10_cols if c not in _TODAY_AGF_SET]


def get_stack_cols():
    """Return 159 Stage-2 stacked HGB features = V10 (155) + 4 walk-forward OOS fundamental features."""
    return list(V10_CONFIG["feature_cols"]) + list(STACK_OOF_COLS)


def attach_fund_oof_features(df, p_fund, clip_min=1e-6):
    """Attach 4 leak-free OOS fundamental features (`STACK_OOF_COLS`) onto a copy/concat of `df`.

    Rows where `p_fund` is NaN (e.g., pre-2015 warmup history) keep NaN across all 4 OOF columns.
    """
    n = len(df)
    if n == 0:
        empty_cols = {c: pd.Series(dtype="float64", index=df.index) for c in STACK_OOF_COLS}
        overlap = [c for c in STACK_OOF_COLS if c in df.columns]
        base = df.drop(columns=overlap) if overlap else df
        return pd.concat([base, pd.DataFrame(empty_cols, index=df.index)], axis=1)

    pf = np.asarray(p_fund, dtype=np.float64)
    if len(pf) != n:
        raise ValueError(f"p_fund length ({len(pf)}) must match len(df) ({n}).")

    pf_ok = np.isfinite(pf) & (pf > 0.0)
    fund_log_p = np.where(pf_ok, np.log(np.clip(np.where(pf_ok, pf, 1.0), clip_min, 1.0)), np.nan)

    fund_rk_pct = np.full(n, np.nan, dtype=np.float64)
    if pf_ok.any():
        tmp_rk = pd.DataFrame(
            {
                "_rid": df["race_id"].to_numpy(),
                "_pf": np.where(pf_ok, pf, np.nan),
            }
        )
        fund_rk_pct = (
            tmp_rk.groupby("_rid", sort=False)["_pf"]
            .rank(ascending=False, pct=True)
            .to_numpy(dtype=np.float64)
        )

    if "agf_share" in df.columns:
        agf_s = pd.to_numeric(df["agf_share"], errors="coerce").to_numpy(dtype=np.float64)
    else:
        agf_s = np.full(n, np.nan, dtype=np.float64)

    both_ok = pf_ok & np.isfinite(agf_s) & (agf_s > 0.0)
    agf_log = np.where(both_ok, np.log(np.clip(np.where(both_ok, agf_s, 1.0), clip_min, 1.0)), np.nan)
    fund_vs_agf_log = np.where(both_ok, fund_log_p - agf_log, np.nan)
    fund_minus_agf = np.where(both_ok, pf - agf_s, np.nan)

    new_df = pd.DataFrame(
        {
            "fund_log_p": fund_log_p,
            "fund_rk_pct": fund_rk_pct,
            "fund_vs_agf_log": fund_vs_agf_log,
            "fund_minus_agf": fund_minus_agf,
        },
        index=df.index,
    )
    overlap = [c for c in STACK_OOF_COLS if c in df.columns]
    base = df.drop(columns=overlap) if overlap else df
    return pd.concat([base, new_df], axis=1)


class RaceConditionalLogit:
    """Vectorized race-grouped multinomial logit: `p_{r,i} ∝ exp(X_{r,i} @ w)` with L2 regularization."""

    def __init__(self, l2_reg=1e-4, prior_w=None, max_iter=300):
        self.l2_reg = float(l2_reg)
        self.prior_w = None if prior_w is None else np.asarray(prior_w, dtype=np.float64).copy()
        self.max_iter = int(max_iter)
        self.coef_ = None
        self.opt_result_ = None

    def fit(self, X, race_ids, winner_mask):
        """Fit conditional logit weights `coef_` maximizing race-level winner log-likelihood."""
        X_arr = np.asarray(X, dtype=np.float64)
        if X_arr.ndim != 2 or X_arr.shape[1] == 0:
            raise ValueError("X must be a non-empty 2D feature array.")
        n_rows, n_feats = X_arr.shape
        w_raw = np.asarray(winner_mask, dtype=np.float64)
        if not (len(w_raw) == len(race_ids) == n_rows):
            raise ValueError("X, race_ids, and winner_mask must have matching row count.")

        w0 = (
            np.zeros(n_feats, dtype=np.float64)
            if self.prior_w is None
            else np.asarray(self.prior_w, dtype=np.float64).copy()
        )
        if len(w0) != n_feats:
            raise ValueError(f"prior_w length ({len(w0)}) must match X.shape[1] ({n_feats}).")

        order, starts, _ends, counts = _group_races_contiguous(race_ids)
        if len(starts) == 0:
            self.coef_ = w0.copy()
            return self

        Xs = X_arr[order]
        ws = np.where(np.isfinite(w_raw[order]) & (w_raw[order] > 0.0), w_raw[order], 0.0)
        finite_row = np.all(np.isfinite(Xs), axis=1)
        finite_cnt = np.add.reduceat(finite_row.astype(np.int64), starts)
        w_race_sum = np.add.reduceat(ws, starts)

        valid_race = (finite_cnt == counts) & (counts >= 2) & (w_race_sum > 0.0)
        if not np.any(valid_race):
            self.coef_ = w0.copy()
            return self

        if not np.all(valid_race):
            keep_row = np.repeat(valid_race, counts)
            Xs = Xs[keep_row]
            ws = ws[keep_row]
            counts = counts[valid_race]
            w_race_sum = w_race_sum[valid_race]
            starts = np.r_[0, np.cumsum(counts[:-1])]

        n_races = float(len(counts))
        w_race_per_row = np.repeat(w_race_sum, counts)
        reg = self.l2_reg

        def nll_and_grad(theta):
            w_vec = np.asarray(theta, dtype=np.float64)
            z = Xs @ w_vec
            m_r = np.maximum.reduceat(z, starts)
            exp_z = np.exp(z - np.repeat(m_r, counts))
            sum_exp = np.add.reduceat(exp_z, starts)
            log_denom = m_r + np.log(sum_exp)

            ll = np.sum(ws * z) - np.sum(w_race_sum * log_denom)
            diff_w = w_vec - w0
            nll = -ll / n_races + 0.5 * reg * float(np.dot(diff_w, diff_w))

            p_row = exp_z / np.repeat(sum_exp, counts)
            resid = ws - w_race_per_row * p_row
            grad = -(Xs.T @ resid) / n_races + reg * diff_w
            return float(nll), np.asarray(grad, dtype=np.float64)

        res = minimize(
            nll_and_grad,
            x0=w0.copy(),
            method="L-BFGS-B",
            jac=True,
            options={"maxiter": self.max_iter},
        )
        self.coef_ = np.asarray(res.x, dtype=np.float64).copy() if np.all(np.isfinite(res.x)) else w0.copy()
        self.opt_result_ = res
        return self

    def predict(self, X, race_ids):
        """Predict race-normalized probabilities `p_{r,i}` summing to 1 within each `race_id`."""
        X_arr = np.asarray(X, dtype=np.float64)
        n_rows = len(X_arr)
        if n_rows != len(race_ids):
            raise ValueError("X and race_ids must have equal length.")
        if n_rows == 0:
            return np.zeros(0, dtype=np.float64)
        if self.coef_ is None:
            raise ValueError("RaceConditionalLogit is not fitted yet.")

        order, starts, _ends, counts = _group_races_contiguous(race_ids)
        Xs = X_arr[order]
        finite_row = np.all(np.isfinite(Xs), axis=1)
        race_ok = np.add.reduceat(finite_row.astype(np.int64), starts) == counts

        Xs_safe = np.where(finite_row[:, None], Xs, 0.0)
        z_safe = Xs_safe @ self.coef_
        m_r = np.maximum.reduceat(z_safe, starts)
        exp_z = np.exp(z_safe - np.repeat(m_r, counts))
        sum_exp = np.add.reduceat(exp_z, starts)
        p_sorted = exp_z / np.repeat(sum_exp, counts)

        if not np.all(race_ok):
            ok_row = np.repeat(race_ok, counts)
            unif = 1.0 / np.repeat(counts.astype(np.float64), counts)
            p_sorted = np.where(ok_row, p_sorted, unif)

        out = np.empty(n_rows, dtype=np.float64)
        out[order] = p_sorted
        return out


class TwoParamBenterCombiner:
    """Bill Benter 2-parameter conditional logit: `p_i ∝ exp(a·log p_fund_i + b·log p_agf_i)`."""

    def __init__(self, clip_min=1e-6, l2_reg=1e-4):
        self.clip_min = float(clip_min)
        self.l2_reg = float(l2_reg)
        self.a_ = 0.5
        self.b_ = 0.5
        self._logit = None

    def _design(self, p_fund, p_agf):
        xf = _ensure_log_prob(p_fund, self.clip_min)
        xa = _ensure_log_prob(p_agf, self.clip_min)
        if len(xf) != len(xa):
            raise ValueError("p_fund and p_agf must have equal length.")
        return np.column_stack([xf, xa])

    def fit(self, p_fund, p_agf, race_ids, winner_mask):
        X = self._design(p_fund, p_agf)
        self._logit = RaceConditionalLogit(l2_reg=self.l2_reg, prior_w=[0.5, 0.5]).fit(
            X, race_ids, winner_mask
        )
        self.a_ = float(self._logit.coef_[0])
        self.b_ = float(self._logit.coef_[1])
        return self

    def predict(self, p_fund, p_agf, race_ids):
        if len(p_fund) == 0:
            return np.zeros(0, dtype=np.float64)
        X = self._design(p_fund, p_agf)
        if self._logit is None:
            tmp = RaceConditionalLogit(l2_reg=self.l2_reg, prior_w=[self.a_, self.b_])
            tmp.coef_ = np.array([self.a_, self.b_], dtype=np.float64)
            return tmp.predict(X, race_ids)
        return self._logit.predict(X, race_ids)


class ThreeWayLogitBlender:
    """3-input conditional logit: `p_i ∝ exp(w_v10·log p_v10 + w_fund·log p_fund + w_agf·log p_agf)`."""

    def __init__(self, clip_min=1e-6, l2_reg=1e-4):
        self.clip_min = float(clip_min)
        self.l2_reg = float(l2_reg)
        self.w_v10_ = 0.8
        self.w_fund_ = 0.1
        self.w_agf_ = 0.1
        self._logit = None

    def _design(self, p_v10, p_fund, p_agf):
        x1 = _ensure_log_prob(p_v10, self.clip_min)
        x2 = _ensure_log_prob(p_fund, self.clip_min)
        x3 = _ensure_log_prob(p_agf, self.clip_min)
        if not (len(x1) == len(x2) == len(x3)):
            raise ValueError("p_v10, p_fund, and p_agf must have equal length.")
        return np.column_stack([x1, x2, x3])

    def fit(self, p_v10, p_fund, p_agf, race_ids, winner_mask):
        X = self._design(p_v10, p_fund, p_agf)
        self._logit = RaceConditionalLogit(l2_reg=self.l2_reg, prior_w=[0.8, 0.1, 0.1]).fit(
            X, race_ids, winner_mask
        )
        self.w_v10_ = float(self._logit.coef_[0])
        self.w_fund_ = float(self._logit.coef_[1])
        self.w_agf_ = float(self._logit.coef_[2])
        return self

    def predict(self, p_v10, p_fund, p_agf, race_ids):
        if len(p_v10) == 0:
            return np.zeros(0, dtype=np.float64)
        X = self._design(p_v10, p_fund, p_agf)
        if self._logit is None:
            tmp = RaceConditionalLogit(l2_reg=self.l2_reg)
            tmp.coef_ = np.array([self.w_v10_, self.w_fund_, self.w_agf_], dtype=np.float64)
            return tmp.predict(X, race_ids)
        return self._logit.predict(X, race_ids)


class RichBenterCombiner:
    """Multi-feature conditional logit over `P_temel`, `AGF`, asymmetric overlays, field size, and AGF-aux."""

    FEATURE_NAMES = (
        "log_p_fund",
        "log_agf",
        "pos_edge",
        "neg_edge",
        "fund_x_lfield",
        "agf_x_lfield",
    ) + TODAY_AGF_AUX_COLS

    def __init__(self, clip_min=1e-6, l2_reg=2e-3, aux_cols=TODAY_AGF_AUX_COLS):
        self.clip_min = float(clip_min)
        self.l2_reg = float(l2_reg)
        self.aux_cols = tuple(aux_cols)
        self.aux_means_ = {}
        self.aux_stds_ = {}
        self._logit = None
        self.coef_ = None

    def _build_base_six(self, df, p_fund, p_agf):
        lp_f = to_log_prob(p_fund, self.clip_min)
        lp_a = to_log_prob(p_agf, self.clip_min)
        both_fin = np.isfinite(lp_f) & np.isfinite(lp_a)
        diff = np.where(both_fin, lp_f - lp_a, 0.0)
        pos_edge = np.maximum(0.0, diff)
        neg_edge = np.minimum(0.0, diff)

        if "field" in df.columns:
            fld = pd.to_numeric(df["field"], errors="coerce").to_numpy(dtype=np.float64)
        else:
            fld = df.groupby("race_id", sort=False)["race_id"].transform("size").to_numpy(dtype=np.float64)
        fld_clean = np.where(np.isfinite(fld) & (fld >= 2.0), np.clip(fld, 2.0, 30.0), 10.0)
        lfield_c = np.log(fld_clean) - np.log(10.0)

        f_x_lf = np.where(np.isfinite(lp_f), lp_f * lfield_c, np.nan)
        a_x_lf = np.where(np.isfinite(lp_a), lp_a * lfield_c, np.nan)
        return [lp_f, lp_a, pos_edge, neg_edge, f_x_lf, a_x_lf], both_fin

    def fit(self, df, p_fund, p_agf, winner_mask):
        cols_list, both_fin = self._build_base_six(df, p_fund, p_agf)
        self.aux_means_ = {}
        self.aux_stds_ = {}

        for col in self.aux_cols:
            if col in df.columns:
                raw = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)
            else:
                raw = np.full(len(df), np.nan, dtype=np.float64)
            ok = np.isfinite(raw) & both_fin
            if np.sum(ok) >= 10:
                mu = float(np.mean(raw[ok]))
                sd = float(np.std(raw[ok]))
                if not np.isfinite(sd) or sd < 1e-6:
                    sd = 1.0
            else:
                mu, sd = 0.0, 1.0
            self.aux_means_[col] = mu
            self.aux_stds_[col] = sd
            z_col = np.where(np.isfinite(raw), np.clip((raw - mu) / sd, -6.0, 6.0), 0.0)
            cols_list.append(z_col)

        X = np.column_stack(cols_list)
        prior_w = np.zeros(X.shape[1], dtype=np.float64)
        prior_w[0] = 0.5
        prior_w[1] = 0.5
        self._logit = RaceConditionalLogit(l2_reg=self.l2_reg, prior_w=prior_w).fit(
            X, df["race_id"].to_numpy(), winner_mask
        )
        self.coef_ = self._logit.coef_.copy()
        return self

    def predict(self, df, p_fund, p_agf):
        if len(df) == 0:
            return np.zeros(0, dtype=np.float64)
        if self._logit is None:
            raise ValueError("RichBenterCombiner is not fitted yet.")
        cols_list, _ = self._build_base_six(df, p_fund, p_agf)
        for col in self.aux_cols:
            if col in df.columns:
                raw = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)
            else:
                raw = np.full(len(df), np.nan, dtype=np.float64)
            mu = self.aux_means_.get(col, 0.0)
            sd = self.aux_stds_.get(col, 1.0)
            z_col = np.where(np.isfinite(raw), np.clip((raw - mu) / sd, -6.0, 6.0), 0.0)
            cols_list.append(z_col)
        X = np.column_stack(cols_list)
        return self._logit.predict(X, df["race_id"].to_numpy())


def corrupt_agf_share_lognormal(agf_share, race_ids, sigma_log, seed=0, clip_min=1e-6):
    """Simulate early-pool noisy `agf_share` via log-normal perturbation + race renormalization."""
    arr = np.asarray(agf_share, dtype=np.float64)
    n = len(arr)
    if n != len(race_ids):
        raise ValueError("agf_share and race_ids must have equal length.")
    if n == 0:
        return np.zeros(0, dtype=np.float64)

    order, starts, _ends, counts = _group_races_contiguous(race_ids)
    base_s = np.where(np.isfinite(arr[order]) & (arr[order] > 0.0), np.clip(arr[order], clip_min, 1.0), 0.0)

    if float(sigma_log) > 0.0:
        rng = np.random.default_rng(int(seed))
        eps = rng.normal(0.0, float(sigma_log), size=n)
        pert_s = np.where(base_s > 0.0, base_s * np.exp(np.clip(eps[order], -8.0, 8.0)), 0.0)
    else:
        pert_s = base_s

    denom_r = np.add.reduceat(pert_s, starts)
    denom_row = np.repeat(denom_r, counts)
    unif_row = 1.0 / np.repeat(counts.astype(np.float64), counts)
    norm_s = np.where(denom_row > 0.0, pert_s / np.where(denom_row > 0.0, denom_row, 1.0), unif_row)

    # Preserve NaN on races where original agf_share had zero positive entries
    orig_sum_r = np.add.reduceat(base_s, starts)
    has_agf_row = np.repeat(orig_sum_r > 0.0, counts)
    norm_s = np.where(has_agf_row, norm_s, np.nan)

    out = np.empty(n, dtype=np.float64)
    out[order] = norm_s
    return out


__all__ = [
    "PAST_MKT_COLS",
    "RichBenterCombiner",
    "RaceConditionalLogit",
    "STACK_OOF_COLS",
    "TODAY_AGF_AUX_COLS",
    "TODAY_AGF_COLS",
    "ThreeWayLogitBlender",
    "TwoParamBenterCombiner",
    "attach_fund_oof_features",
    "corrupt_agf_share_lognormal",
    "get_fund_cols",
    "get_stack_cols",
]
