"""Altılı payout estimation model (§3.3): y = a_city + b * x, where x = sum_j log(winner_agf_share_j)."""
import json
import numpy as np
import pandas as pd


class PayoutModel:
    """Fixed-effects OLS model: log(payout) = a_city + b * sum_j log(agf_share_j)."""

    def __init__(self, a_by_city=None, b=-1.0, default_a=8.0, trained_through=None):
        self.a_by_city = dict(a_by_city or {})
        self.b = float(b)
        self.default_a = float(default_a)
        self.trained_through = trained_through

    def fit(self, df):
        """Fit on DataFrame with columns ['city', 'x', 'y'] (or 'payout' instead of 'y')."""
        data = df.copy()
        if "y" not in data.columns:
            data["y"] = np.log(np.clip(data["payout"].astype(float), 1e-2, None))
        data = data[data["x"].notna() & data["y"].notna() & np.isfinite(data["x"]) & np.isfinite(data["y"])]
        if len(data) == 0:
            return self

        cities = sorted(data["city"].unique())
        # Design matrix: one-hot for cities + x column
        n = len(data)
        k = len(cities)
        city_to_idx = {c: i for i, c in enumerate(cities)}
        X = np.zeros((n, k + 1), dtype=float)
        for row_i, c in enumerate(data["city"]):
            X[row_i, city_to_idx[c]] = 1.0
        X[:, k] = data["x"].values
        y = data["y"].values

        params, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        self.a_by_city = {c: float(params[i]) for i, c in enumerate(cities)}
        self.b = float(params[k])
        self.default_a = float(np.mean(params[:k])) if k > 0 else 8.0
        if "date" in data.columns and len(data["date"]) > 0:
            self.trained_through = str(pd.to_datetime(data["date"]).max().date())
        return self

    def predict_log(self, city, x):
        a = self.a_by_city.get(city, self.default_a)
        return a + self.b * np.asarray(x, dtype=float)

    def predict_payout(self, city, agf_shares):
        """Predict payout TL for 6 winning AGF shares (or pre-summed log x if scalar)."""
        if np.ndim(agf_shares) == 0:
            x = float(agf_shares)
        else:
            shares = np.clip(np.asarray(agf_shares, dtype=float), 1e-4, 1.0)
            x = float(np.sum(np.log(shares)))
        a = self.a_by_city.get(city, self.default_a)
        return float(np.exp(a + self.b * x))

    def to_dict(self):
        return {
            "a_by_city": self.a_by_city,
            "b": self.b,
            "trained_through": self.trained_through,
        }


def build_altili_dataset(conn_or_altili_df, runners_df):
    """Build historical altili dataset with ['date', 'city', 'which', 'x', 'y', 'payout'] from DB or DataFrames."""
    if hasattr(conn_or_altili_df, "execute"):
        alt_df = pd.read_sql_query("SELECT * FROM altili", conn_or_altili_df)
    else:
        alt_df = conn_or_altili_df.copy()

    run = runners_df[runners_df["scratched"].fillna(0) == 0].copy()
    if "agf_close" not in run.columns and "agf_pct" in run.columns:
        run["agf_close"] = run["agf_pct"]

    rg_sum = run.groupby("race_id")["agf_close"].transform("sum")
    run["agf_share"] = np.where(rg_sum > 0, run["agf_close"] / rg_sum, np.nan)

    # Map race_id -> winner's agf_share (only single-winner races with valid agf_share)
    win_counts = run[run["finish"] == 1].groupby("race_id").size()
    single_winner_races = set(win_counts[win_counts == 1].index)
    winners = run[(run["finish"] == 1) & (run["race_id"].isin(single_winner_races))]
    race_win_share = dict(zip(winners["race_id"], winners["agf_share"]))

    rows = []
    for _, row in alt_df.iterrows():
        date_str = str(row["date"])[:10]
        city = row["city"]
        end_r = int(row["end_race"])
        start_r = int(row["start_race"])
        rids = [f"{date_str}_{city}_{r}" for r in range(start_r, end_r + 1)]
        if len(rids) != 6:
            continue
        shares = [race_win_share.get(rid) for rid in rids]
        if any(s is None or np.isnan(s) or s <= 0 for s in shares):
            continue
        pay = float(row["payout"])
        if pay <= 0:
            continue
        x = float(sum(np.log(max(s, 1e-4)) for s in shares))
        rows.append({
            "date": date_str,
            "city": city,
            "which": int(row["which"]),
            "start_race": start_r,
            "end_race": end_r,
            "legs": json.loads(row["legs"]) if isinstance(row["legs"], str) else row["legs"],
            "payout": pay,
            "x": x,
            "y": float(np.log(pay)),
        })
    return pd.DataFrame(rows)


def walk_forward_payout(alt_data, months=None, train_start="2025-01-01"):
    """Walk-forward evaluation of PayoutModel across months (§3.3)."""
    from ganyan.backtest import DEFAULT_MONTHS

    if months is None:
        months = DEFAULT_MONTHS
    df = alt_data.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df["ym"] = df["dt"].dt.strftime("%Y-%m")

    preds = []
    models_by_month = {}
    for m in months:
        m_start = pd.Timestamp(f"{m}-01")
        tr = df[(df["dt"] >= pd.Timestamp(train_start)) & (df["dt"] < m_start)]
        te = df[df["ym"] == m].copy()
        if len(tr) < 5 or len(te) == 0:
            continue
        pm = PayoutModel().fit(tr)
        models_by_month[m] = pm
        te["y_pred"] = [pm.predict_log(c, x) for c, x in zip(te["city"], te["x"])]
        te["payout_pred"] = np.exp(te["y_pred"])
        te["b_est"] = pm.b
        preds.append(te)

    res = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()
    if res.empty:
        return res, {}, models_by_month

    ss_res = float(np.sum((res["y"] - res["y_pred"]) ** 2))
    ss_tot = float(np.sum((res["y"] - res["y"].mean()) ** 2))
    r2_log = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    ape = np.abs(res["payout_pred"] - res["payout"]) / res["payout"]
    mdape = float(np.median(ape) * 100.0)
    full_model = PayoutModel().fit(df[df["dt"] >= pd.Timestamp(train_start)])

    metrics = {
        "n_test": len(res),
        "r2_log": r2_log,
        "mdape_pct": mdape,
        "b_final": full_model.b,
        "a_by_city_final": full_model.a_by_city,
    }
    return res, metrics, models_by_month
