"""Evaluate v1_agf vs v3_agf_soy (pedigree features) on monthly walk-forward -> reports/SOY.md."""
import argparse
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.backtest import DEFAULT_MONTHS, TRAIN_START, load_runners_from_db
from ganyan.db import init_db
from ganyan.features import SOY_COLS, build_features, get_feature_cols, get_soy_feature_cols
from ganyan.model import fit_predict_df

YOUNG_MAX_STARTS = 3


def run_soy_walk_forward(runners_df, months=None, train_start=TRAIN_START, ref_end="2025-07-01"):
    months = months or DEFAULT_MONTHS
    df = build_features(runners_df, ref_end=ref_end)
    _, v1_cols = get_feature_cols(df)
    v3_cols = get_soy_feature_cols()

    rg = df.groupby("race_id")
    ok = (
        rg["agf_close"].transform(lambda s: s.notna().all())
        & rg["ganyan"].transform(lambda s: s.notna().all())
        & (rg["win"].transform("sum") == 1)
        & (df["field"] >= 4)
    )
    eval_df = df[ok].copy()
    eval_df["ym"] = eval_df["date"].dt.strftime("%Y-%m")
    # share of runners per race that are lightly raced (pedigree should matter most there)
    eval_df["young_share"] = (eval_df["h_n"] <= YOUNG_MAX_STARTS).groupby(eval_df["race_id"]).transform("mean")

    preds = []
    for m in months:
        tr = eval_df[(eval_df["date"] >= pd.Timestamp(train_start)) & (eval_df["date"] < pd.Timestamp(f"{m}-01"))]
        te = eval_df[eval_df["ym"] == m].copy()
        if len(tr) == 0 or len(te) == 0:
            continue
        te["p_v1"] = fit_predict_df(tr, te, v1_cols)
        te["p_v3"] = fit_predict_df(tr, te, v3_cols)
        for c in ("p_v1", "p_v3"):
            te[f"{c}_rk"] = te.groupby("race_id")[c].rank(ascending=False, method="first")
        preds.append(te)

    winners = pd.concat(preds, ignore_index=True).query("win == 1")
    return winners


def paired_stats(w):
    rng = np.random.default_rng(0)
    d_ll = -np.log(w["p_v3"].clip(lower=1e-6)).values + np.log(w["p_v1"].clip(lower=1e-6)).values
    d_acc = (w["p_v3_rk"] == 1).astype(float).values - (w["p_v1_rk"] == 1).astype(float).values
    n = len(w)
    bs_ll = [d_ll[rng.integers(0, n, n)].mean() for _ in range(2000)]
    bs_acc = [d_acc[rng.integers(0, n, n)].mean() for _ in range(2000)]
    return {
        "n": n,
        "ll_v1": float((-np.log(w["p_v1"].clip(lower=1e-6))).mean()),
        "ll_v3": float((-np.log(w["p_v3"].clip(lower=1e-6))).mean()),
        "ll_diff": float(d_ll.mean()),
        "ll_lo": float(np.percentile(bs_ll, 2.5)),
        "ll_hi": float(np.percentile(bs_ll, 97.5)),
        "acc_v1": float((w["p_v1_rk"] == 1).mean()),
        "acc_v3": float((w["p_v3_rk"] == 1).mean()),
        "acc_diff": float(d_acc.mean()),
        "acc_lo": float(np.percentile(bs_acc, 2.5)),
        "acc_hi": float(np.percentile(bs_acc, 97.5)),
    }


def format_report(winners):
    overall = paired_stats(winners)
    young = winners[winners["young_share"] >= 0.3]
    old = winners[winners["young_share"] < 0.3]
    passed = overall["ll_hi"] < 0.0
    lines = [
        "# Ganyan — Soy (Baba/Anne) Özellikleri Walk-Forward Değerlendirmesi",
        "",
        f"**Karar:** **{'GEÇTİ' if passed else 'GEÇMEDİ'}** — `ll(v3_agf_soy) − ll(v1_agf) = {overall['ll_diff']:+.5f}`, "
        f"2000 tekrarlı koşu-eşli bootstrap %95 GA `[{overall['ll_lo']:+.5f}, {overall['ll_hi']:+.5f}]` "
        f"(geçme koşulu: üst sınır < 0, `v2_agf_hava` kapısıyla aynı).",
        "",
        f"Eklenen özellikler: {', '.join('`'+c+'`' for c in SOY_COLS)} (yalnız D gününden önceki yavru sonuçları, büzülmeli).",
        f"Genç-at kümesi: koşudaki atların en az %30'u `h_n <= {YOUNG_MAX_STARTS}` olan koşular.",
        "",
        "| Küme | Koşu | `v1_agf` LL | `v3_agf_soy` LL | LL Fark | LL %95 GA | `v1` 1.Tercih | `v3` 1.Tercih | 1.Tercih Fark (%95 GA) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, w in [("Tüm koşular", winners), ("Genç at ağırlıklı", young), ("Diğer", old)]:
        if len(w) == 0:
            continue
        s = paired_stats(w)
        lines.append(
            f"| {label} | {s['n']} | {s['ll_v1']:.4f} | {s['ll_v3']:.4f} | `{s['ll_diff']:+.5f}` | "
            f"`[{s['ll_lo']:+.5f}, {s['ll_hi']:+.5f}]` | {s['acc_v1']:.2%} | {s['acc_v3']:.2%} | "
            f"`{s['acc_diff']:+.2%}` (`{s['acc_lo']:+.2%}`…`{s['acc_hi']:+.2%}`) |"
        )
    lines += ["", "> Kapanış AGF kullanılır; canlı AGF daha az bilgi içerir. Damsire (anne babası) veride yok, eklenmedi.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--out", default="reports/SOY.md")
    args = ap.parse_args()
    conn = init_db(args.db)
    runners_df = load_runners_from_db(conn)
    print(f"Loaded {len(runners_df)} runner rows.", flush=True)
    winners = run_soy_walk_forward(runners_df)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(format_report(winners))
    print(f"Wrote report to {args.out}")
    conn.close()


if __name__ == "__main__":
    main()
