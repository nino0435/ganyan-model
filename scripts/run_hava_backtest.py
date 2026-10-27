"""Evaluate v1_agf vs v2_agf_hava on non-overlapping monthly walk-forward (2025-07 … 2026-10) -> reports/HAVA_PIST.md (§5)."""
import argparse
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.backtest import DEFAULT_MONTHS, TRAIN_START, load_runners_from_db, load_weather_from_db
from ganyan.db import init_db
from ganyan.features import build_features, get_feature_cols, get_hava_feature_cols
from ganyan.model import fit_predict_df, make_estimator
from ganyan.track import load_html_cond_into_db


def _fit_estimator(train_df, feats):
    m = make_estimator()
    y_train = (train_df["finish"] == 1).astype(int)
    X_train = train_df[feats].copy()
    all_nan = [c for c in feats if X_train[c].isna().all()]
    if all_nan:
        X_train[all_nan] = 0.0
    m.fit(X_train, y_train)
    return m, all_nan


def _predict_race_norm(m, all_nan, test_df, feats):
    X_test = test_df[feats].copy()
    if all_nan:
        X_test[all_nan] = 0.0
    p = m.predict_proba(X_test)[:, 1]
    s = pd.Series(p, index=test_df.index)
    denom = s.groupby(test_df["race_id"]).transform("sum").values
    return np.where(denom > 0, p / denom, 1.0 / test_df.groupby("race_id")["race_id"].transform("size").values)


def run_hava_walk_forward(runners_df, weather_df, months=None, train_start=TRAIN_START, ref_end="2025-07-01"):
    """Run monthly walk-forward comparing v1_agf vs v2_agf_hava and compute permutation importance on test months."""
    if months is None:
        months = DEFAULT_MONTHS

    df = build_features(runners_df, ref_end=ref_end, weather_df=weather_df)
    _, v1_cols = get_feature_cols(df)
    v2_cols = get_hava_feature_cols(include_track_cond=True)
    new_cols = [c for c in v2_cols if c not in v1_cols]

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
    # For permutation importance across all test months: accumulate race-level winner log-loss increase per feature
    perm_ll_deltas = {c: [] for c in v2_cols}
    rng_perm = np.random.default_rng(42)
    n_repeats = 5

    for m in months:
        m_start = pd.Timestamp(f"{m}-01")
        tr = eval_df[(eval_df["date"] >= pd.Timestamp(train_start)) & (eval_df["date"] < m_start)]
        te = eval_df[eval_df["ym"] == m].copy()
        if len(tr) == 0 or len(te) == 0:
            continue

        te["p_v1_agf"] = fit_predict_df(tr, te, v1_cols)
        est_v2, all_nan_v2 = _fit_estimator(tr, v2_cols)
        te["p_v2_agf_hava"] = _predict_race_norm(est_v2, all_nan_v2, te, v2_cols)

        for col in ["p_v1_agf", "p_v2_agf_hava"]:
            te[f"{col}_rk"] = te.groupby("race_id")[col].rank(ascending=False, method="first")

        # Permutation importance on this test month (measuring increase in winner log-loss when feature c is permuted)
        win_mask = (te["win"] == 1).values
        base_ll = float(-np.log(np.clip(te["p_v2_agf_hava"].values[win_mask], 1e-6, 1.0)).mean())
        X_te_base = te[v2_cols].copy()
        if all_nan_v2:
            X_te_base[all_nan_v2] = 0.0
        race_ids_te = te["race_id"].values
        field_sizes_te = te.groupby("race_id")["race_id"].transform("size").values

        for c in v2_cols:
            vals = X_te_base[c].values.copy()
            # Skip constant columns in test month
            if pd.Series(vals).nunique(dropna=False) <= 1:
                perm_ll_deltas[c].append((len(win_mask.nonzero()[0]), 0.0))
                continue
            rep_diffs = []
            for _ in range(n_repeats):
                X_perm = X_te_base.copy()
                X_perm[c] = rng_perm.permutation(vals)
                p_raw = est_v2.predict_proba(X_perm)[:, 1]
                s_p = pd.Series(p_raw, index=te.index)
                denom = s_p.groupby(race_ids_te).transform("sum").values
                p_norm = np.where(denom > 0, p_raw / denom, 1.0 / field_sizes_te)
                perm_ll = float(-np.log(np.clip(p_norm[win_mask], 1e-6, 1.0)).mean())
                rep_diffs.append(perm_ll - base_ll)
            perm_ll_deltas[c].append((int(win_mask.sum()), float(np.mean(rep_diffs))))

        preds.append(te)

    all_preds = pd.concat(preds, ignore_index=True)
    winners = all_preds[all_preds["win"] == 1].copy()

    # Monthly table
    monthly_rows = []
    for m, w_sub in winners.groupby("ym"):
        ll1 = -np.log(w_sub["p_v1_agf"].clip(lower=1e-6))
        ll2 = -np.log(w_sub["p_v2_agf_hava"].clip(lower=1e-6))
        monthly_rows.append({
            "month": m,
            "races": len(w_sub),
            "wet_races": int((w_sub["wet"] == 1).sum()),
            "acc_v1": float((w_sub["p_v1_agf_rk"] == 1).mean()),
            "acc_v2": float((w_sub["p_v2_agf_hava_rk"] == 1).mean()),
            "ll_v1": float(ll1.mean()),
            "ll_v2": float(ll2.mean()),
            "ll_diff": float((ll2 - ll1).mean()),
        })
    monthly_df = pd.DataFrame(monthly_rows)

    # Paired bootstrap (2000 reps) on race level
    def _paired_stats(w_df):
        rng = np.random.default_rng(0)
        ll1 = -np.log(w_df["p_v1_agf"].clip(lower=1e-6)).values
        ll2 = -np.log(w_df["p_v2_agf_hava"].clip(lower=1e-6)).values
        d_ll = ll2 - ll1
        acc1 = (w_df["p_v1_agf_rk"] == 1).astype(float).values
        acc2 = (w_df["p_v2_agf_hava_rk"] == 1).astype(float).values
        d_acc = acc2 - acc1
        n = len(w_df)
        bs_ll = [d_ll[rng.integers(0, n, n)].mean() for _ in range(2000)]
        bs_acc = [d_acc[rng.integers(0, n, n)].mean() for _ in range(2000)]
        return {
            "n_races": n,
            "ll_v1": float(ll1.mean()),
            "ll_v2": float(ll2.mean()),
            "ll_diff": float(d_ll.mean()),
            "ll_ci95_low": float(np.percentile(bs_ll, 2.5)),
            "ll_ci95_high": float(np.percentile(bs_ll, 97.5)),
            "acc_v1": float(acc1.mean()),
            "acc_v2": float(acc2.mean()),
            "acc_diff": float(d_acc.mean()),
            "acc_ci95_low": float(np.percentile(bs_acc, 2.5)),
            "acc_ci95_high": float(np.percentile(bs_acc, 97.5)),
        }

    overall_stats = _paired_stats(winners)
    wet_winners = winners[winners["wet"] == 1]
    dry_winners = winners[winners["wet"] == 0]
    wet_stats = _paired_stats(wet_winners) if len(wet_winners) > 0 else None
    dry_stats = _paired_stats(dry_winners) if len(dry_winners) > 0 else None

    # Weighted average permutation importance across all test races
    perm_rows = []
    for c in v2_cols:
        items = perm_ll_deltas[c]
        tot_w = sum(w for w, _ in items)
        mean_imp = sum(w * val for w, val in items) / tot_w if tot_w > 0 else 0.0
        perm_rows.append({
            "feature": c,
            "is_new": c in new_cols,
            "ll_increase": float(mean_imp),
        })
    perm_df = pd.DataFrame(perm_rows).sort_values("ll_increase", ascending=False).reset_index(drop=True)
    perm_df["rank"] = perm_df.index + 1

    # Also summarize total dataset wet races (all status='result' races in df)
    all_races_meta = df[["race_id", "wet", "track_cond", "surface"]].drop_duplicates("race_id")
    meta_summary = {
        "total_races_db": int(len(all_races_meta)),
        "total_wet_db": int((all_races_meta["wet"] == 1).sum()),
        "total_dry_db": int((all_races_meta["wet"] == 0).sum()),
        "eval_races": int(len(winners)),
        "eval_wet": int(len(wet_winners)),
        "eval_dry": int(len(dry_winners)),
    }

    return monthly_df, overall_stats, wet_stats, dry_stats, perm_df, meta_summary


def format_hava_report(monthly_df, overall, wet_stats, dry_stats, perm_df, meta):
    passed = overall["ll_ci95_high"] < 0.0
    decision_word = "GEÇTİ" if passed else "GEÇMEDİ"
    if passed:
        reason = (
            f"Kazanan log-loss farkı `ll(v2_agf_hava) − ll(v1_agf) = {overall['ll_diff']:+.5f}` olup "
            f"2000 tekrarlı koşu-eşli bootstrap %95 güven aralığı üst sınırı (`{overall['ll_ci95_high']:+.5f}`) 0'ın altındadır."
        )
    else:
        reason = (
            f"Kazanan log-loss farkı `ll(v2_agf_hava) − ll(v1_agf) = {overall['ll_diff']:+.5f}` olup "
            f"2000 tekrarlı koşu-eşli bootstrap %95 güven aralığı (`{overall['ll_ci95_low']:+.5f}` … `{overall['ll_ci95_high']:+.5f}`) 0'ı kapsadığı / üst sınırı < 0 olmadığı için istatistiksel olarak anlamlı bir iyileşme sağlamamıştır."
        )

    lines = []
    lines.append("# Ganyan — Hava ve Pist Durumu Özellikleri İleri-Yürüyen (Walk-Forward) Değerlendirme Raporu")
    lines.append("")
    lines.append(f"**Karar (§0):** **{decision_word}** — {reason}")
    lines.append("")
    lines.append("> **Metodoloji Notları (§4.1, §8):**")
    lines.append("> - **Pist durumu ön-ilan varsayımı (§4.1):** TJK geçmiş günlerin program ve sonuç HTML sayfalarında `<div class=\"conditions-race\">` içinde pist durumu yer almaktadır; ancak yarış sabahı erken saatte (`06:40`) çekilen canlı gelecek program sayfasında pist durumu henüz boş olduğundan, pist durumunun bahis anından önce ilan edildiği **varsayım** olarak işaretlenmiştir.")
    lines.append("> - **Open-Meteo lisans ve canlı kullanım (§3.3, §8):** Open-Meteo ücretsiz API'si ticari olmayan (araştırma) kullanım içindir; uygulamada ticari kullanım veya `v2_agf_hava`'nın günlük ileri teste (`forward_log.py`) paralel eklenmesi **kullanıcı kararıdır**. Bu çalışmada kâr (ROI) iddiası yoktur ve bütçeli kupon backtest'i çalıştırılmamıştır.")
    lines.append("")
    lines.append("## 1. Aylık İleri-Yürüyen Karşılaştırma (`v1_agf` vs `v2_agf_hava`, 2025-07 … 2026-10)")
    lines.append("")
    lines.append("| Ay | Koşu | Islak Koşu | `v1_agf` 1.Tercih | `v2_agf_hava` 1.Tercih | `v1_agf` Log-Loss | `v2_agf_hava` Log-Loss | Fark (`v2 − v1` LL) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in monthly_df.iterrows():
        lines.append(
            f"| {r['month']} | {int(r['races'])} | {int(r['wet_races'])} | "
            f"{r['acc_v1']:.2%} | {r['acc_v2']:.2%} | "
            f"{r['ll_v1']:.4f} | {r['ll_v2']:.4f} | {r['ll_diff']:+.4f} |"
        )
    lines.append("")
    lines.append("## 2. Toplam ve Alt Küme (Islak / Kuru) Sonuçları — Eşleştirilmiş Bootstrap (2000 Tekrar)")
    lines.append("")
    lines.append(
        f"- **Islak Koşu Tanımı (§4.2):** `wet = (track_cond in {{nemli, islak, agir, yumusak}})` (bilinmiyorsa `rain_72h >= 5.0 mm`). "
        f"Veritabanındaki toplam `{meta['total_races_db']}` sonuçlanmış koşunun **`{meta['total_wet_db']}`** tanesi ıslak (`{meta['total_dry_db']}` kuru); "
        f"16 aylık değerlendirme dönemindeki `{meta['eval_races']}` koşunun **`{meta['eval_wet']}`** tanesi ıslak (`{meta['eval_dry']}` kuru) sayılmıştır."
    )
    lines.append("")
    lines.append("| Küme | Koşu Sayısı | `v1_agf` Log-Loss | `v2_agf_hava` Log-Loss | LL Fark (`v2 − v1`) | LL %95 GA (Bootstrap) | `v1_agf` 1.Tercih | `v2_agf_hava` 1.Tercih | 1.Tercih Fark (%95 GA) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, st in [
        ("**Tüm Koşular (Birincil Ölçüt)**", overall),
        ("Islak Koşular (`wet == 1`)", wet_stats),
        ("Kuru Koşular (`wet == 0`)", dry_stats),
    ]:
        if st is None:
            continue
        lines.append(
            f"| {label} | {st['n_races']} | {st['ll_v1']:.4f} | {st['ll_v2']:.4f} | "
            f"`{st['ll_diff']:+.5f}` | `[{st['ll_ci95_low']:+.5f}, {st['ll_ci95_high']:+.5f}]` | "
            f"{st['acc_v1']:.2%} | {st['acc_v2']:.2%} | "
            f"`{st['acc_diff']:+.2%}` (`{st['acc_ci95_low']:+.2%}`…`{st['acc_ci95_high']:+.2%}`) |"
        )
    lines.append("")
    lines.append("## 3. Özellik Önemi — Permutation Importance (Test Ayları Üzerinde)")
    lines.append("")
    lines.append("Test aylarında her özelliğin koşular arasında rastgele karıştırılmasıyla (5 tekrar) kazananın log-loss değerinde oluşan ortalama artış (`Δ Log-Loss`, büyük pozitif = daha önemli) aşağıda sıralanmıştır (`79` toplam özellik içinde yeni hava/pist özelliklerinin genel sırası):")
    lines.append("")
    lines.append("### 3.1 İlk 15 Genel Özellik")
    lines.append("")
    lines.append("| Genel Sıra | Özellik | Yeni (Hava/Pist)? | Ortalama Δ Log-Loss |")
    lines.append("|---:|---|---:|---:|")
    for _, r in perm_df.head(15).iterrows():
        is_n = "Evet" if r["is_new"] else "Hayır"
        lines.append(f"| {int(r['rank'])} | `{r['feature']}` | {is_n} | `{r['ll_increase']:+.5f}` |")
    lines.append("")
    lines.append("### 3.2 Yeni Eklenen Hava ve Pist Özelliklerinin Sıralaması")
    lines.append("")
    lines.append("| Genel Sıra (`/ 79`) | Yeni Özellik | Ortalama Δ Log-Loss |")
    lines.append("|---:|---|---:|")
    new_perm = perm_df[perm_df["is_new"]]
    for _, r in new_perm.iterrows():
        lines.append(f"| {int(r['rank'])} | `{r['feature']}` | `{r['ll_increase']:+.5f}` |")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--html-dir", default="data/raw/html_cond")
    ap.add_argument("--out", default="reports/HAVA_PIST.md")
    args = ap.parse_args()

    conn = init_db(args.db)
    if os.path.exists(args.html_dir):
        n_upd = load_html_cond_into_db(conn, args.html_dir)
        print(f"Updated track_cond on {n_upd} races from {args.html_dir}", flush=True)

    runners_df = load_runners_from_db(conn)
    weather_df = load_weather_from_db(conn)
    print(f"Loaded {len(runners_df)} runner rows and {len(weather_df)} weather rows.", flush=True)

    monthly_df, overall_stats, wet_stats, dry_stats, perm_df, meta_summary = run_hava_walk_forward(
        runners_df, weather_df
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    md = format_hava_report(monthly_df, overall_stats, wet_stats, dry_stats, perm_df, meta_summary)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote report to {args.out}")
    conn.close()


if __name__ == "__main__":
    main()
