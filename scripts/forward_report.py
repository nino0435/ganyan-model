"""Generate forward-testing report (reports/FORWARD.md) from logged predictions (§4)."""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.allocator import allocate_coupon_a, allocate_fixed_k
from ganyan.db import init_db


def build_forward_report(conn, model_version="v1_agf", budget_tl=1000.0, unit_tl=1.25):
    """Evaluate strictly pre-race predictions (created_at < post_time) against outcomes."""
    query = """
    SELECT
        p.race_id, p.prog_no, p.model_version, p.created_at, p.p_win, p.agf_used,
        r.date, r.city, r.race_no, r.post_time, r.status,
        run.finish, run.scratched, run.agf_close
    FROM predictions p
    JOIN races r ON p.race_id = r.race_id
    LEFT JOIN runners run ON p.race_id = run.race_id AND p.prog_no = run.prog_no
    WHERE p.model_version = ?
    """
    df = pd.read_sql_query(query, conn, params=(model_version,))

    total_logged_races = df["race_id"].nunique() if not df.empty else 0
    total_logged_rows = len(df)
    min_date = str(df["date"].min()) if not df.empty else "—"
    max_date = str(df["date"].max()) if not df.empty else "—"

    # Filter strictly valid pre-race predictions: created_at < date + 'T' + post_time
    if not df.empty:
        post_iso = df["date"].astype(str) + "T" + df["post_time"].fillna("00:00").astype(str)
        valid_df = df[df["created_at"].astype(str).str[:16] < post_iso.str[:16]].copy()
    else:
        valid_df = df.copy()

    valid_races = valid_df["race_id"].nunique() if not valid_df.empty else 0
    res_df = valid_df[(valid_df["status"] == "result") & (valid_df["scratched"].fillna(0) == 0)].copy()

    lines = [
        "# Ganyan — İleri Test (Forward-Test) Raporu",
        "",
        f"- **Model Sürümü:** `{model_version}`",
        f"- **Kayıt Tarih Aralığı:** `{min_date}` … `{max_date}`",
        f"- **Toplam Kayıtlı Tahmin:** `{total_logged_races}` koşu (`{total_logged_rows}` at)",
        f"- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `{valid_races}` koşu",
    ]

    if res_df.empty:
        lines.append("- **Sonuçlanmış Geçerli Koşu:** `0` (Henüz sonuçlanan ileri test koşusu yok; sonuçlar geldikçe bu rapor otomatik güncellenir.)")
        return "\n".join(lines) + "\n"

    # Renormalize among active runners
    res_df["p_norm"] = res_df["p_win"] / res_df.groupby("race_id")["p_win"].transform("sum")
    agf_used = pd.to_numeric(res_df["agf_used"], errors="coerce")
    agf_close = pd.to_numeric(res_df["agf_close"], errors="coerce")
    agf_col = agf_used.where(agf_used > 0).fillna(agf_close.where(agf_close > 0)).fillna(1.0)
    res_df["p_agf"] = agf_col / agf_col.groupby(res_df["race_id"]).transform("sum")

    res_df["rk_mod"] = res_df.groupby("race_id")["p_norm"].rank(ascending=False, method="first")
    res_df["rk_agf"] = res_df.groupby("race_id")["p_agf"].rank(ascending=False, method="first")

    winners = res_df[res_df["finish"] == 1]
    n_res_races = winners["race_id"].nunique()
    acc_mod = float((winners["rk_mod"] == 1).mean()) if len(winners) else 0.0
    acc_agf = float((winners["rk_agf"] == 1).mean()) if len(winners) else 0.0
    ll_mod = float(-np.log(winners["p_norm"].clip(lower=1e-6)).mean()) if len(winners) else 0.0
    ll_agf = float(-np.log(winners["p_agf"].clip(lower=1e-6)).mean()) if len(winners) else 0.0

    lines.extend([
        f"- **Sonuçlanmış Geçerli Koşu:** `{n_res_races}`",
        "",
        "## 1. Koşu Bazında Performans",
        "",
        "| Yöntem | 1. Tercih Kazandı | Log-Loss |",
        "|---|---:|---:|",
        f"| Anlık AGF Favorisi | {acc_agf:.1%} | {ll_agf:.4f} |",
        f"| Model (`{model_version}`) | {acc_mod:.1%} | {ll_mod:.4f} |",
        f"| **Fark (Model − AGF)** | **{acc_mod - acc_agf:+.1%}** | **{ll_mod - ll_agf:+.4f}** |",
    ])

    # Evaluate altili on logged races
    alt_df = pd.read_sql_query("SELECT * FROM altili", conn)
    by_race = {rid: grp for rid, grp in res_df.groupby("race_id")}
    n_alt = hit_fk = hit_ma = 0
    for _, row in alt_df.iterrows():
        rids = [f"{row['date']}_{row['city']}_{r}" for r in range(int(row["start_race"]), int(row["end_race"]) + 1)]
        if len(rids) != 6 or not all(r in by_race for r in rids):
            continue
        n_alt += 1
        legs_official = [set(int(x) for x in leg) for leg in json.loads(row["legs"])]
        legs_agf = [list(zip(by_race[r]["prog_no"], by_race[r]["p_agf"], by_race[r]["p_agf"])) for r in rids]
        legs_mod = [list(zip(by_race[r]["prog_no"], by_race[r]["p_norm"], by_race[r]["p_agf"])) for r in rids]
        c_fk = allocate_fixed_k(legs_agf, budget_tl, unit_tl=unit_tl)
        c_ma = allocate_coupon_a(legs_mod, budget_tl, unit_tl=unit_tl)
        if all(bool(set(c_fk["selected"][j]) & legs_official[j]) for j in range(6)):
            hit_fk += 1
        if all(bool(set(c_ma["selected"][j]) & legs_official[j]) for j in range(6)):
            hit_ma += 1

    lines.extend([
        "",
        f"## 2. Altılı Karşılaştırması (Bütçe {budget_tl:.0f} TL)",
        "",
        f"- **Değerlendirilen Altılı:** `{n_alt}`",
        f"- **Sabit-k 6/6:** `{hit_fk} / {n_alt}`",
        f"- **Model Amaç A 6/6:** `{hit_ma} / {n_alt}`",
    ])
    return "\n".join(lines) + "\n"


def forward_report(db_path="data/ganyan.db", out_path="reports/FORWARD.md", model_version="v1_agf"):
    """Build and write forward-testing report to out_path (default: reports/FORWARD.md)."""
    conn = init_db(db_path)
    try:
        md = build_forward_report(conn, model_version=model_version)
    finally:
        conn.close()
    parent = os.path.dirname(str(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_pos", nargs="?", help="Çıktı dosyası yolu (varsayılan: reports/FORWARD.md)")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out_path = args.out or args.out_pos or "reports/FORWARD.md"
    forward_report(db_path=args.db, out_path=out_path)
    print(f"Wrote forward report to {out_path}")


if __name__ == "__main__":
    main()
