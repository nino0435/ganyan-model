"""Monthly walk-forward evaluation and coupon backtest engine (§3.2, §3.5)."""
import numpy as np
import pandas as pd
from ganyan.features import build_features, get_feature_cols
from ganyan.model import fit_predict_df

TRAIN_START = pd.Timestamp("2025-01-01")
DEFAULT_MONTHS = [
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08",
    "2026-09",
    "2026-10",
]


def load_runners_from_db(conn):
    """Load joined races and runners from SQLite into a DataFrame."""
    query = """
    SELECT
        r.race_id, r.date, r.city, r.race_no, r.post_time, r.yg_no,
        r.cls, r.breed, r.distance, r.surface, r.status,
        run.prog_no, run.horse_key, run.name, run.name_raw, run.age, run.sex,
        run.sire, run.dam, run.weight, run.jockey, run.owner, run.trainer,
        run.gate, run.hp, run.son6, run.kgs, run.s20, run.best_time_s,
        run.finish, run.time_s, run.ganyan, run.agf_close, run.agf_close_rank, run.scratched
    FROM races r
    JOIN runners run ON r.race_id = run.race_id
    WHERE r.status = 'result'
    """
    return pd.read_sql_query(query, conn)


def walk_forward(runners_df, months=None, train_start=TRAIN_START, ref_end="2025-07-01"):
    """Run non-overlapping monthly walk-forward evaluation across months (§3.2).

    Returns (predictions_df, monthly_summary_df, bootstrap_stats_dict).
    """
    if months is None:
        months = DEFAULT_MONTHS

    df = build_features(runners_df, ref_end=ref_end)
    base_cols, with_agf_cols = get_feature_cols(df)

    rg = df.groupby("race_id")
    ok = (
        rg["agf_close"].transform(lambda s: s.notna().all())
        & rg["ganyan"].transform(lambda s: s.notna().all())
        & (rg["win"].transform("sum") == 1)
        & (df["field"] >= 4)
    )
    eval_df = df[ok].copy()
    eval_df["ym"] = eval_df["date"].dt.strftime("%Y-%m")

    preds = []
    for m in months:
        m_start = pd.Timestamp(f"{m}-01")
        tr = eval_df[(eval_df["date"] >= pd.Timestamp(train_start)) & (eval_df["date"] < m_start)]
        te = eval_df[eval_df["ym"] == m].copy()
        if len(tr) == 0 or len(te) == 0:
            continue
        te["p_v1_noagf"] = fit_predict_df(tr, te, base_cols)
        te["p_v1_agf"] = fit_predict_df(tr, te, with_agf_cols)
        te["p_agf"] = te["agf_share"]
        inv = 1.0 / te["ganyan"]
        te["p_odds"] = inv / inv.groupby(te["race_id"]).transform("sum")

        for col in ["p_v1_noagf", "p_v1_agf", "p_agf", "p_odds"]:
            te[f"{col}_rk"] = te.groupby("race_id")[col].rank(ascending=False, method="first")
        preds.append(te)

    all_preds = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()
    if all_preds.empty:
        return all_preds, pd.DataFrame(), {}

    # Monthly summary table
    winners = all_preds[all_preds["win"] == 1].copy()
    monthly_rows = []
    for m, w_sub in winners.groupby("ym"):
        row = {"month": m, "races": len(w_sub)}
        for label, col in [
            ("agf", "p_agf"),
            ("odds", "p_odds"),
            ("v1_noagf", "p_v1_noagf"),
            ("v1_agf", "p_v1_agf"),
        ]:
            row[f"acc_{label}"] = float((w_sub[f"{col}_rk"] == 1).mean())
            row[f"ll_{label}"] = float(-np.log(w_sub[col].clip(lower=1e-6)).mean())
        monthly_rows.append(row)
    monthly_df = pd.DataFrame(monthly_rows)

    # Race-paired bootstrap (2000 samples) across all months
    rng = np.random.default_rng(0)
    w_idx = winners.set_index("race_id")
    hit_agf = (w_idx["p_agf_rk"] == 1).astype(float).values
    bootstrap = {}
    for label, col in [
        ("v1_noagf", "p_v1_noagf"),
        ("v1_agf", "p_v1_agf"),
        ("odds", "p_odds"),
    ]:
        hit_m = (w_idx[f"{col}_rk"] == 1).astype(float).values
        d = hit_m - hit_agf
        bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
        bootstrap[label] = {
            "acc": float(hit_m.mean()),
            "ll": float(-np.log(w_idx[col].clip(lower=1e-6)).mean()),
            "diff_vs_agf": float(d.mean()),
            "ci95_low": float(np.percentile(bs, 2.5)),
            "ci95_high": float(np.percentile(bs, 97.5)),
        }
    bootstrap["agf"] = {
        "acc": float(hit_agf.mean()),
        "ll": float(-np.log(w_idx["p_agf"].clip(lower=1e-6)).mean()),
        "diff_vs_agf": 0.0,
        "ci95_low": 0.0,
        "ci95_high": 0.0,
    }

    return all_preds, monthly_df, bootstrap
