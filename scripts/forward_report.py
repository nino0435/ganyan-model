"""Generate forward-testing report (reports/FORWARD.md) from logged predictions (§4)."""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.agf_check import agf_complete
from ganyan.allocator import allocate_coupon_a, allocate_fixed_k
from ganyan.backtest import get_unit_tl
from ganyan.db import init_db

EARLY_MODEL_VERSION = "v1_agf"
LATE_MODEL_VERSION = "v1_agf_late"
ROI_NOTE = (
    "ROI kapanış öncesi oranlarla değil, kesinleşmiş ödemelerle hesaplanır; "
    "küçük örneklemde tek büyük ikramiye sonucu belirler."
)


def paired_bootstrap_ci(diff_values, n_boot=2000, seed=0):
    """Race-paired bootstrap 95% CI (2000 resamples, default_rng(0)) for mean(diff_values)."""
    d = np.asarray(diff_values, dtype=float)
    n = len(d)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean_val = float(d.mean())
    if n == 1:
        return mean_val, mean_val, mean_val
    rng = np.random.default_rng(seed)
    bs = d[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
    return mean_val, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def _parse_combo_ints(combo):
    if combo is None or (isinstance(combo, float) and np.isnan(combo)):
        return set()
    out = set()
    for part in str(combo).split(","):
        s = part.strip()
        if s:
            try:
                out.add(int(s))
            except ValueError:
                continue
    return out


def _list_model_versions(conn):
    rows = conn.execute(
        "SELECT DISTINCT model_version FROM predictions WHERE model_version IS NOT NULL"
    ).fetchall()
    found = {str(r[0]) for r in rows if str(r[0])}
    if not found:
        return ["v1_agf"]
    ordered = ["v1_agf"] if "v1_agf" in found else []
    ordered.extend(sorted(v for v in found if v != "v1_agf"))
    return ordered


def _build_version_lines(conn, model_version, budget_tl=1000.0, unit_tl=1.25, sec_prefix="##"):
    query = """
    SELECT
        p.race_id, p.prog_no, p.model_version, p.created_at, p.p_win, p.agf_used,
        r.date, r.city, r.race_no, r.post_time, r.status,
        run.finish, run.scratched, run.agf_close
    FROM predictions p
    JOIN races r ON p.race_id = r.race_id
    LEFT JOIN runners run ON p.race_id = run.race_id AND p.prog_no = run.prog_no
    WHERE p.model_version = ?
    ORDER BY r.date, r.city, r.race_no, p.prog_no
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

    # AGF bütünlüğü: bir ata bile '%0'/boş AGF'yle yazılmış ya da toplamı ~%100 olmayan koşu geçersizdir
    # (TJK açılışta geçici placeholder basabiliyor); kayıt DB'de kalır, değerlendirmeye girmez.
    n_bad_agf = 0
    if not valid_df.empty:
        agf_by_race = pd.to_numeric(valid_df["agf_used"], errors="coerce").groupby(valid_df["race_id"]).apply(list)
        bad_ids = {rid for rid, vals in agf_by_race.items() if not agf_complete(vals)}
        n_bad_agf = len(bad_ids)
        valid_df = valid_df[~valid_df["race_id"].isin(bad_ids)].copy()

    valid_races = valid_df["race_id"].nunique() if not valid_df.empty else 0
    res_df = valid_df[(valid_df["status"] == "result") & (valid_df["scratched"].fillna(0) == 0)].copy()

    lines = [
        f"- **Model Sürümü:** `{model_version}`",
        f"- **Kayıt Tarih Aralığı:** `{min_date}` … `{max_date}`",
        f"- **Toplam Kayıtlı Tahmin:** `{total_logged_races}` koşu (`{total_logged_rows}` at)",
        f"- **Koşu Öncesi Geçerli Tahmin (`created_at < post_time`):** `{valid_races}` koşu",
    ]
    if n_bad_agf:
        lines.append(f"- **AGF'si eksik/sıfır olduğu için dışlanan koşu:** `{n_bad_agf}`")

    if res_df.empty:
        lines.append("- **Sonuçlanmış Geçerli Koşu:** `0` (Henüz sonuçlanan ileri test koşusu yok; sonuçlar geldikçe bu rapor otomatik güncellenir.)")
        return lines, False

    # Renormalize among active runners
    p_win_col = pd.to_numeric(res_df["p_win"], errors="coerce").fillna(0.0)
    p_sum = p_win_col.groupby(res_df["race_id"]).transform("sum")
    p_cnt = res_df.groupby("race_id")["p_win"].transform("count")
    res_df["p_norm"] = (p_win_col / p_sum.where(p_sum > 0)).fillna(1.0 / p_cnt)
    agf_used = pd.to_numeric(res_df["agf_used"], errors="coerce")
    agf_close = pd.to_numeric(res_df["agf_close"], errors="coerce")
    agf_col = agf_used.where(agf_used > 0).fillna(agf_close.where(agf_close > 0)).fillna(1.0)
    res_df["p_agf"] = agf_col / agf_col.groupby(res_df["race_id"]).transform("sum")

    res_df["rk_mod"] = res_df.groupby("race_id")["p_norm"].rank(ascending=False, method="first", na_option="bottom")
    res_df["rk_agf"] = res_df.groupby("race_id")["p_agf"].rank(ascending=False, method="first", na_option="bottom")

    winners = res_df[res_df["finish"] == 1]
    n_res_races = winners["race_id"].nunique()
    acc_mod = float((winners["rk_mod"] == 1).mean()) if len(winners) else 0.0
    acc_agf = float((winners["rk_agf"] == 1).mean()) if len(winners) else 0.0
    ll_mod = float(-np.log(winners["p_norm"].clip(lower=1e-6)).mean()) if len(winners) else 0.0
    ll_agf = float(-np.log(winners["p_agf"].clip(lower=1e-6)).mean()) if len(winners) else 0.0

    if len(winners):
        w_pair = pd.DataFrame({
            "race_id": winners["race_id"].values,
            "d_acc": (winners["rk_mod"] == 1).astype(float).values - (winners["rk_agf"] == 1).astype(float).values,
            "d_ll": (-np.log(winners["p_norm"].clip(lower=1e-6)) + np.log(winners["p_agf"].clip(lower=1e-6))).values,
        }).groupby("race_id", sort=False).mean()
        _, acc_ci_lo, acc_ci_hi = paired_bootstrap_ci(w_pair["d_acc"].values)
        _, ll_ci_lo, ll_ci_hi = paired_bootstrap_ci(w_pair["d_ll"].values)
        bs_perf_str = f"1. tercih `[{acc_ci_lo:+.1%}, {acc_ci_hi:+.1%}]`, log-loss `[{ll_ci_lo:+.4f}, {ll_ci_hi:+.4f}]`"
    else:
        bs_perf_str = "—"

    mod_favs = res_df[res_df["rk_mod"] == 1].set_index("race_id")
    agf_favs = res_df[res_df["rk_agf"] == 1].set_index("race_id").reindex(mod_favs.index)
    diff_mask = mod_favs["prog_no"].astype(int) != agf_favs["prog_no"].astype(int)
    n_disagree = int(diff_mask.sum())
    agf_won_disagree = int((agf_favs.loc[diff_mask, "finish"] == 1).sum())
    mod_won_disagree = int((mod_favs.loc[diff_mask, "finish"] == 1).sum())

    lines.extend([
        f"- **Sonuçlanmış Geçerli Koşu:** `{n_res_races}`",
        "",
        f"{sec_prefix} 1. Koşu Bazında Performans",
        "",
        "| Yöntem | 1. Tercih Kazandı | Log-Loss |",
        "|---|---:|---:|",
        f"| Anlık AGF Favorisi | {acc_agf:.1%} | {ll_agf:.4f} |",
        f"| Model (`{model_version}`) | {acc_mod:.1%} | {ll_mod:.4f} |",
        f"| **Fark (Model − AGF)** | **{acc_mod - acc_agf:+.1%}** | **{ll_mod - ll_agf:+.4f}** |",
        "",
        f"- **Koşu-Eşli Bootstrap %95 GA (Model − AGF, 2000 tekrar):** {bs_perf_str}",
        f"- **Model ≠ AGF Favorisi:** `{n_disagree}` koşu (AGF favorisi kazandı: `{agf_won_disagree}`, Model favorisi kazandı: `{mod_won_disagree}`)",
    ])

    # Evaluate altili on logged races
    alt_df = pd.read_sql_query("SELECT * FROM altili ORDER BY date, city, which", conn)
    by_race = {rid: grp for rid, grp in res_df.groupby("race_id")}
    n_alt = n_alt_priced = 0
    alt_stats = {
        "fixed_k": {"hit": 0, "cost": 0.0, "ret": 0.0},
        "agf_a": {"hit": 0, "cost": 0.0, "ret": 0.0},
        "model_a": {"hit": 0, "cost": 0.0, "ret": 0.0},
    }
    for _, row in alt_df.iterrows():
        rids = [f"{row['date']}_{row['city']}_{r}" for r in range(int(row["start_race"]), int(row["end_race"]) + 1)]
        if len(rids) != 6 or not all(r in by_race for r in rids):
            continue
        n_alt += 1
        known_u = get_unit_tl(row["date"])
        u_tl = known_u if known_u is not None else unit_tl
        if known_u is not None:
            n_alt_priced += 1
        payout_val = float(row["payout"]) if row["payout"] is not None and not pd.isna(row["payout"]) else 0.0

        legs_official = [set(int(x) for x in leg) for leg in json.loads(row["legs"])]
        legs_agf = [list(zip(by_race[r]["prog_no"], by_race[r]["p_agf"], by_race[r]["p_agf"])) for r in rids]
        legs_mod = [list(zip(by_race[r]["prog_no"], by_race[r]["p_norm"], by_race[r]["p_agf"])) for r in rids]
        coupons = {
            "fixed_k": allocate_fixed_k(legs_agf, budget_tl, unit_tl=u_tl),
            "agf_a": allocate_coupon_a(legs_agf, budget_tl, unit_tl=u_tl),
            "model_a": allocate_coupon_a(legs_mod, budget_tl, unit_tl=u_tl),
        }
        for key, c_res in coupons.items():
            hit = all(bool(set(c_res["selected"][j]) & legs_official[j]) for j in range(6))
            if hit:
                alt_stats[key]["hit"] += 1
            if known_u is not None:
                alt_stats[key]["cost"] += float(c_res["cost"])
                if hit:
                    alt_stats[key]["ret"] += payout_val

    hit_fk = alt_stats["fixed_k"]["hit"]
    hit_aa = alt_stats["agf_a"]["hit"]
    hit_ma = alt_stats["model_a"]["hit"]

    lines.extend([
        "",
        f"{sec_prefix} 2. Altılı Karşılaştırması (Bütçe {budget_tl:.0f} TL)",
        "",
        f"- **Değerlendirilen Altılı:** `{n_alt}`",
        f"- **Sabit-k 6/6:** `{hit_fk} / {n_alt}`",
        f"- **AGF — Amaç A 6/6:** `{hit_aa} / {n_alt}`",
        f"- **Model Amaç A 6/6:** `{hit_ma} / {n_alt}`",
    ])
    if 0 < n_alt_priced < n_alt:
        lines.append(f"- **Birim Fiyatı Bilinen Altılı:** `{n_alt_priced} / {n_alt}`")
    lines.extend([
        "",
        "| Yöntem | 6/6 | Maliyet (TL) | Dönüş (TL) | ROI |",
        "|---|---:|---:|---:|---:|",
    ])
    for key, label in [
        ("fixed_k", "Sabit-k (AGF)"),
        ("agf_a", "AGF — Amaç A"),
        ("model_a", f"Model (`{model_version}`) — Amaç A"),
    ]:
        st = alt_stats[key]
        if n_alt_priced > 0 and st["cost"] > 0:
            cost_s = f"{st['cost']:,.2f}"
            ret_s = f"{st['ret']:,.2f}"
            roi_s = f"{st['ret'] / st['cost'] - 1.0:+.1%}"
        else:
            cost_s = ret_s = roi_s = "—"
        lines.append(f"| {label} | {st['hit']} / {n_alt} | {cost_s} | {ret_s} | {roi_s} |")

    # Evaluate 1 TL flat ganyan bet on favorite per race
    bets_df = pd.read_sql_query("SELECT race_id, combo, payout FROM bets WHERE bet = 'GANYAN'", conn)
    ganyan_map = {}
    for _, brow in bets_df.iterrows():
        pay = brow["payout"]
        if pay is None or pd.isna(pay):
            continue
        c_ints = _parse_combo_ints(brow["combo"])
        if not c_ints:
            continue
        race_dict = ganyan_map.setdefault(brow["race_id"], {})
        for pno in c_ints:
            race_dict[pno] = float(pay)

    ret_agf_list = []
    ret_mod_list = []
    n_no_ganyan = 0
    for rid in mod_favs.index:
        if rid not in ganyan_map:
            n_no_ganyan += 1
            continue
        p_agf_no = int(agf_favs.loc[rid, "prog_no"])
        p_mod_no = int(mod_favs.loc[rid, "prog_no"])
        ret_agf_list.append(ganyan_map[rid].get(p_agf_no, 0.0))
        ret_mod_list.append(ganyan_map[rid].get(p_mod_no, 0.0))

    n_ganyan = len(ret_agf_list)
    ret_agf_arr = np.array(ret_agf_list, dtype=float)
    ret_mod_arr = np.array(ret_mod_list, dtype=float)
    stake_tl = float(n_ganyan)
    tot_ret_agf = float(ret_agf_arr.sum()) if n_ganyan else 0.0
    tot_ret_mod = float(ret_mod_arr.sum()) if n_ganyan else 0.0

    if n_ganyan > 0:
        roi_agf = tot_ret_agf / stake_tl - 1.0
        roi_mod = tot_ret_mod / stake_tl - 1.0
        roi_agf_s = f"{roi_agf:+.1%}"
        roi_mod_s = f"{roi_mod:+.1%}"
        diff_ret_s = f"**{tot_ret_mod - tot_ret_agf:+.2f}**"
        diff_roi_s = f"**{roi_mod - roi_agf:+.1%}**"
        _, roi_ci_lo, roi_ci_hi = paired_bootstrap_ci(ret_mod_arr - ret_agf_arr)
        bs_roi_s = f"`[{roi_ci_lo:+.1%}, {roi_ci_hi:+.1%}]`"
    else:
        roi_agf_s = roi_mod_s = diff_ret_s = diff_roi_s = bs_roi_s = "—"

    lines.extend([
        "",
        f"{sec_prefix} 3. Para (1 TL ganyan)",
        "",
        f"- **GANYAN satırı olmayan (hesaptan çıkarılan) koşu:** `{n_no_ganyan}`",
        "",
        "| Yöntem | Oynanan Koşu | Yatırılan (TL) | Dönüş (TL) | ROI |",
        "|---|---:|---:|---:|---:|",
        f"| Anlık AGF Favorisi | {n_ganyan} | {stake_tl:,.2f} | {tot_ret_agf:,.2f} | {roi_agf_s} |",
        f"| Model (`{model_version}`) | {n_ganyan} | {stake_tl:,.2f} | {tot_ret_mod:,.2f} | {roi_mod_s} |",
        f"| **Fark (Model − AGF)** | — | — | {diff_ret_s} | {diff_roi_s} |",
        "",
        f"- **Ganyan ROI Farkı Bootstrap %95 GA (Model − AGF, 2000 tekrar):** {bs_roi_s}",
    ])
    return lines, True


def _settled_valid_winners(conn, model_version):
    """Return per-race settled winner metrics for strictly pre-race, AGF-complete predictions of model_version."""
    query = """
    SELECT
        p.race_id, p.prog_no, p.created_at, p.p_win, p.agf_used,
        r.date, r.city, r.race_no, r.post_time, r.status,
        run.finish, run.scratched
    FROM predictions p
    JOIN races r ON p.race_id = r.race_id
    LEFT JOIN runners run ON p.race_id = run.race_id AND p.prog_no = run.prog_no
    WHERE p.model_version = ?
    ORDER BY r.date, r.city, r.race_no, p.prog_no
    """
    df = pd.read_sql_query(query, conn, params=(model_version,))
    cols = ["race_id", "acc_agf", "acc_mod", "ll_agf", "ll_mod"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    post_iso = df["date"].astype(str) + "T" + df["post_time"].fillna("00:00").astype(str)
    valid_df = df[df["created_at"].astype(str).str[:16] < post_iso.str[:16]].copy()
    if valid_df.empty:
        return pd.DataFrame(columns=cols)

    agf_by_race = pd.to_numeric(valid_df["agf_used"], errors="coerce").groupby(valid_df["race_id"]).apply(list)
    bad_ids = {rid for rid, vals in agf_by_race.items() if not agf_complete(vals)}
    valid_df = valid_df[~valid_df["race_id"].isin(bad_ids)].copy()

    res_df = valid_df[(valid_df["status"] == "result") & (valid_df["scratched"].fillna(0) == 0)].copy()
    if res_df.empty:
        return pd.DataFrame(columns=cols)

    p_win_col = pd.to_numeric(res_df["p_win"], errors="coerce").fillna(0.0)
    p_sum = p_win_col.groupby(res_df["race_id"]).transform("sum")
    p_cnt = res_df.groupby("race_id")["p_win"].transform("count")
    res_df["p_norm"] = (p_win_col / p_sum.where(p_sum > 0)).fillna(1.0 / p_cnt)

    agf_used = pd.to_numeric(res_df["agf_used"], errors="coerce")
    agf_col = agf_used.where(agf_used > 0).fillna(1.0)
    res_df["p_agf"] = agf_col / agf_col.groupby(res_df["race_id"]).transform("sum")

    res_df["rk_mod"] = res_df.groupby("race_id")["p_norm"].rank(ascending=False, method="first", na_option="bottom")
    res_df["rk_agf"] = res_df.groupby("race_id")["p_agf"].rank(ascending=False, method="first", na_option="bottom")

    winners = res_df[res_df["finish"] == 1]
    if winners.empty:
        return pd.DataFrame(columns=cols)

    return (
        pd.DataFrame({
            "race_id": winners["race_id"].values,
            "acc_agf": (winners["rk_agf"] == 1).astype(float).values,
            "acc_mod": (winners["rk_mod"] == 1).astype(float).values,
            "ll_agf": (-np.log(winners["p_agf"].clip(lower=1e-6))).values,
            "ll_mod": (-np.log(winners["p_norm"].clip(lower=1e-6))).values,
        })
        .groupby("race_id", sort=False, as_index=False)
        .mean()
    )


def _build_early_late_lines(conn):
    early = _settled_valid_winners(conn, EARLY_MODEL_VERSION)
    late = _settled_valid_winners(conn, LATE_MODEL_VERSION)
    common_set = set(early["race_id"]) & set(late["race_id"])
    lines = ["## Erken ve Geç Tahmin (aynı koşular)", ""]
    if not common_set:
        lines.append(
            "- **Ortak Sonuçlanmış Geçerli Koşu:** `0` "
            "(Henüz iki sürümde de sonuçlanan ortak geçerli koşu yok.)"
        )
        return lines

    early_c = early[early["race_id"].isin(common_set)].reset_index(drop=True)
    late_c = late.set_index("race_id").loc[early_c["race_id"]].reset_index()
    n_common = len(early_c)

    acc_agf_e = float(early_c["acc_agf"].mean())
    acc_mod_e = float(early_c["acc_mod"].mean())
    ll_agf_e = float(early_c["ll_agf"].mean())
    ll_mod_e = float(early_c["ll_mod"].mean())

    acc_agf_l = float(late_c["acc_agf"].mean())
    acc_mod_l = float(late_c["acc_mod"].mean())
    ll_agf_l = float(late_c["ll_agf"].mean())
    ll_mod_l = float(late_c["ll_mod"].mean())

    d_acc_late = (late_c["acc_mod"] - late_c["acc_agf"]).values
    d_ll_late = (late_c["ll_mod"] - late_c["ll_agf"]).values
    _, acc_ci_lo, acc_ci_hi = paired_bootstrap_ci(d_acc_late)
    _, ll_ci_lo, ll_ci_hi = paired_bootstrap_ci(d_ll_late)
    bs_str = f"1. tercih `[{acc_ci_lo:+.1%}, {acc_ci_hi:+.1%}]`, log-loss `[{ll_ci_lo:+.4f}, {ll_ci_hi:+.4f}]`"

    lines.extend([
        f"- **Ortak Sonuçlanmış Geçerli Koşu:** `{n_common}`",
        "",
        "| Yöntem | Koşu | 1. Tercih Kazandı | Log-Loss |",
        "|---|---:|---:|---:|",
        f"| AGF (erken, `{EARLY_MODEL_VERSION}`) | {n_common} | {acc_agf_e:.1%} | {ll_agf_e:.4f} |",
        f"| Model (erken, `{EARLY_MODEL_VERSION}`) | {n_common} | {acc_mod_e:.1%} | {ll_mod_e:.4f} |",
        f"| AGF (geç, `{LATE_MODEL_VERSION}`) | {n_common} | {acc_agf_l:.1%} | {ll_agf_l:.4f} |",
        f"| Model (geç, `{LATE_MODEL_VERSION}`) | {n_common} | {acc_mod_l:.1%} | {ll_mod_l:.4f} |",
        f"| **Fark (Model_geç − AGF_geç)** | {n_common} | **{acc_mod_l - acc_agf_l:+.1%}** | **{ll_mod_l - ll_agf_l:+.4f}** |",
        "",
        f"- **Koşu-Eşli Bootstrap %95 GA (Model_geç − AGF_geç, 2000 tekrar):** {bs_str}",
    ])
    return lines


def build_forward_report(conn, model_version=None, budget_tl=1000.0, unit_tl=1.25):
    """Evaluate strictly pre-race predictions (created_at < post_time) against outcomes."""
    versions = [model_version] if model_version is not None else _list_model_versions(conn)
    if len(versions) == 1:
        sec_lines, has_settled = _build_version_lines(
            conn, versions[0], budget_tl=budget_tl, unit_tl=unit_tl, sec_prefix="##"
        )
        lines = ["# Ganyan — İleri Test (Forward-Test) Raporu", ""] + sec_lines
        if has_settled:
            lines.extend(["", f"> {ROI_NOTE}"])
        return "\n".join(lines) + "\n"

    lines = ["# Ganyan — İleri Test (Forward-Test) Raporu"]
    any_settled = False
    for mv in versions:
        sec_lines, has_settled = _build_version_lines(
            conn, mv, budget_tl=budget_tl, unit_tl=unit_tl, sec_prefix="###"
        )
        any_settled = any_settled or has_settled
        lines.extend(["", f"## Model Sürümü: `{mv}`", ""] + sec_lines)
    if EARLY_MODEL_VERSION in versions and LATE_MODEL_VERSION in versions:
        lines.extend(["", *_build_early_late_lines(conn)])
    if any_settled:
        lines.extend(["", f"> {ROI_NOTE}"])
    return "\n".join(lines) + "\n"


def forward_report(db_path="data/ganyan.db", out_path="reports/FORWARD.md", model_version=None):
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
    ap.add_argument("--model-version", default=None)
    args = ap.parse_args()
    out_path = args.out or args.out_pos or "reports/FORWARD.md"
    forward_report(db_path=args.db, out_path=out_path, model_version=args.model_version)
    print(f"Wrote forward report to {out_path}")


if __name__ == "__main__":
    main()
