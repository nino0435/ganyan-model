"""Monthly walk-forward evaluation and coupon backtest engine (§3.2, §3.5)."""
import numpy as np
import pandas as pd
from ganyan.allocator import allocate_coupon_a, allocate_coupon_b, allocate_fixed_k
from ganyan.features import build_features, get_feature_cols
from ganyan.model import fit_predict_df
from ganyan.payout import PayoutModel

TRAIN_START = pd.Timestamp("2025-01-01")
UNIT_TL_TABLE = {"2026-01-01": 1.25}
BUDGETS_TL = [250, 500, 1000, 2500, 5000]
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


def get_unit_tl(date_str):
    """Look up altili unit price from UNIT_TL_TABLE (K8). Returns None before 2026-01-01."""
    ds = str(date_str)[:10]
    applicable = [price for start_d, price in sorted(UNIT_TL_TABLE.items()) if ds >= start_d]
    return applicable[-1] if applicable else None


def evaluate_coupons(preds_df, altili_df, models_by_month=None, budgets=None, unit_tl_default=1.25):
    """Evaluate 4 coupon allocation methods across budgets on walk-forward predictions (§3.5, §3.6).

    Methods:
      (i)   fixed_k: uniform k^6 fitting budget (ordered by AGF share)
      (ii)  agf_a:   Objective A using AGF share
      (iii) model_a: Objective A using v1_agf probability
      (iv)  model_b: Objective B using v1_agf probability and walk-forward PayoutModel
    """
    if budgets is None:
        budgets = BUDGETS_TL
    if models_by_month is None:
        models_by_month = {}

    by_race = {rid: grp for rid, grp in preds_df.groupby("race_id")}

    # Filter altili_df to valid 6-leg altilis where all 6 races exist in preds_df and have prog_no
    valid_altilis = []
    for _, row in altili_df.iterrows():
        date_str = str(row["date"])[:10]
        city = row["city"]
        start_r = int(row["start_race"])
        end_r = int(row["end_race"])
        rids = [f"{date_str}_{city}_{r}" for r in range(start_r, end_r + 1)]
        if len(rids) != 6 or not all(r in by_race for r in rids):
            continue
        # Ensure prog_no is available for runners in all 6 legs
        if any(by_race[r]["prog_no"].isna().any() for r in rids):
            continue
        legs_official = row["legs"]
        if isinstance(legs_official, str):
            import json
            legs_official = json.loads(legs_official)
        valid_altilis.append({
            "date": date_str,
            "ym": date_str[:7],
            "city": city,
            "which": int(row["which"]),
            "rids": rids,
            "legs_official": [set(int(x) for x in leg) for leg in legs_official],
            "payout": float(row["payout"]),
            "unit_tl": get_unit_tl(date_str),
        })

    methods = ["fixed_k", "agf_a", "model_a", "model_b"]
    summary_rows = []
    go_count = 0
    rng = np.random.default_rng(0)

    for B in budgets:
        # Per-altili records for each method
        rec = {m: [] for m in methods}

        for alt in valid_altilis:
            rids = alt["rids"]
            ym = alt["ym"]
            city = alt["city"]
            # For unit_tl: in pre-2026, use unit_tl_default (1.25) purely to size combinations for hit rate,
            # but exclude pre-2026 from money/ROI calculations per K8 & §3.5.
            u_tl = alt["unit_tl"] if alt["unit_tl"] is not None else unit_tl_default
            is_2026 = alt["unit_tl"] is not None

            legs_agf = []
            legs_mod = []
            for rid in rids:
                grp = by_race[rid]
                legs_agf.append(
                    list(zip(grp["prog_no"].astype(int), grp["p_agf"].astype(float), grp["agf_share"].astype(float)))
                )
                legs_mod.append(
                    list(zip(grp["prog_no"].astype(int), grp["p_v1_agf"].astype(float), grp["agf_share"].astype(float)))
                )

            pm = models_by_month.get(ym, PayoutModel())
            a_city = pm.a_by_city.get(city, pm.default_a)
            b_slope = pm.b

            c_fk = allocate_fixed_k(legs_agf, B, unit_tl=u_tl)
            c_aa = allocate_coupon_a(legs_agf, B, unit_tl=u_tl)
            c_ma = allocate_coupon_a(legs_mod, B, unit_tl=u_tl)
            c_mb = allocate_coupon_b(legs_mod, B, unit_tl=u_tl, a=a_city, b=b_slope)

            for m_name, c_res in [
                ("fixed_k", c_fk),
                ("agf_a", c_aa),
                ("model_a", c_ma),
                ("model_b", c_mb),
            ]:
                sel = c_res["selected"]
                legs_hit = sum(
                    1 for j in range(6) if bool(set(sel[j]) & alt["legs_official"][j])
                )
                hit6 = int(legs_hit == 6)
                rec[m_name].append({
                    "ym": ym,
                    "is_2026": is_2026,
                    "hit6": hit6,
                    "legs_hit": legs_hit,
                    "cost": c_res["cost"] if is_2026 else 0.0,
                    "ret": (alt["payout"] if hit6 else 0.0) if is_2026 else 0.0,
                })

        # Bootstrap vs fixed_k AND vs agf_a across all valid altilis
        fk_hits = np.array([x["hit6"] for x in rec["fixed_k"]], dtype=float)
        aa_hits = np.array([x["hit6"] for x in rec["agf_a"]], dtype=float)
        n_alt = len(fk_hits)
        n_2026 = sum(1 for x in rec["fixed_k"] if x["is_2026"])

        for m_name in methods:
            m_hits = np.array([x["hit6"] for x in rec[m_name]], dtype=float)
            m_legs = np.array([x["legs_hit"] for x in rec[m_name]], dtype=float)
            tot_cost = float(sum(x["cost"] for x in rec[m_name]))
            tot_ret = float(sum(x["ret"] for x in rec[m_name]))
            roi = (tot_ret / tot_cost - 1.0) if tot_cost > 0 else np.nan

            # Monthly ROI std on 2026 months
            df_m = pd.DataFrame([x for x in rec[m_name] if x["is_2026"]])
            if not df_m.empty and df_m["cost"].sum() > 0:
                m_grp = df_m.groupby("ym").agg({"cost": "sum", "ret": "sum"})
                m_grp = m_grp[m_grp["cost"] > 0]
                m_rois = m_grp["ret"] / m_grp["cost"] - 1.0
                roi_std = float(m_rois.std(ddof=1)) if len(m_rois) > 1 else 0.0
            else:
                roi_std = np.nan

            if m_name == "fixed_k" or n_alt == 0:
                diff = 0.0
                ci_low = 0.0
                ci_high = 0.0
            else:
                d = m_hits - fk_hits
                diff = float(d.mean())
                bs = [d[rng.integers(0, n_alt, n_alt)].mean() for _ in range(2000)]
                ci_low = float(np.percentile(bs, 2.5))
                ci_high = float(np.percentile(bs, 97.5))

            if m_name == "agf_a" or n_alt == 0:
                diff_aa = 0.0
                ci_aa_low = 0.0
                ci_aa_high = 0.0
            else:
                d_aa = m_hits - aa_hits
                diff_aa = float(d_aa.mean())
                bs_aa = [d_aa[rng.integers(0, n_alt, n_alt)].mean() for _ in range(2000)]
                ci_aa_low = float(np.percentile(bs_aa, 2.5))
                ci_aa_high = float(np.percentile(bs_aa, 97.5))

            if m_name == "model_a" and diff > 0 and ci_low > 0:
                go_count += 1

            summary_rows.append({
                "budget": B,
                "method": m_name,
                "n_altili": n_alt,
                "n_2026": n_2026,
                "hit6_count": int(m_hits.sum()) if n_alt else 0,
                "hit6_rate": float(m_hits.mean()) if n_alt else 0.0,
                "avg_legs": float(m_legs.mean()) if n_alt else 0.0,
                "cost_2026": tot_cost,
                "return_2026": tot_ret,
                "roi_2026": roi,
                "monthly_roi_std": roi_std,
                "diff_vs_fixed_k": diff,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "diff_vs_agf_a": diff_aa,
                "ci95_aa_low": ci_aa_low,
                "ci95_aa_high": ci_aa_high,
            })

    summary_df = pd.DataFrame(summary_rows)
    go_decision = {
        "passed_budgets": go_count,
        "total_budgets": len(budgets),
        "smart_coupon_claim": bool(go_count >= 3),
    }
    return summary_df, go_decision

