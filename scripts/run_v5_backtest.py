"""Yearly walk-forward evaluation and ablation report for Model v5 -> reports/V5.md (or V5_LOCKED.md)."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.backtest import load_runners_from_db
from ganyan.features import build_features
from ganyan.features_v5 import BLOCK_COLS, attach_v5, load_v5_tables
from ganyan.model import fit_predict_df
from ganyan.model_v5 import (
    BenterCombiner,
    bootstrap_mean_ci,
    compute_edge_buckets,
    compute_top1_roi,
    fit_predict_fund,
    get_b1_cols,
    get_base_cols,
    to_log_prob,
)

FUND_VARIANTS = {
    "F0": (),
    "F_S": ("S",),
    "F_G": ("G",),
    "F_R": ("R",),
    "F_SGR": ("S", "G", "R"),
}

DEFAULT_VARIANTS = [
    "B0",
    "B1",
    "F0",
    "F0+B",
    "F_S",
    "F_S+B",
    "F_G",
    "F_G+B",
    "F_R",
    "F_R+B",
    "F_SGR",
    "F_SGR+B",
]

LOCKED_VARIANTS = ["B0", "B1", "F_SGR+B"]
ALL_VALID_VARIANTS = frozenset(DEFAULT_VARIANTS)
LOCKED_CUTOFF = pd.Timestamp("2025-12-31")
LOCKED_START = pd.Timestamp("2026-01-01")


def _open_ro_db(db_path):
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {db_path}")
    db_uri = f"{p.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.Error:
        pass
    return conn


def _eval_filter_mask(df):
    """Same evaluation race filter as `ganyan.backtest.walk_forward`."""
    rg = df.groupby("race_id")
    return (
        rg["agf_close"].transform(lambda s: s.notna().all())
        & rg["ganyan"].transform(lambda s: s.notna().all())
        & (rg["win"].transform("sum") == 1)
        & (df["field"] >= 4)
    )


def _parse_variants(variants_arg, locked=False):
    if locked:
        return list(LOCKED_VARIANTS)
    if variants_arg is None:
        return list(DEFAULT_VARIANTS)
    if isinstance(variants_arg, (list, tuple)):
        items = [str(v).strip() for v in variants_arg if str(v).strip()]
    else:
        items = [v.strip() for v in str(variants_arg).split(",") if v.strip()]
    if not items:
        raise ValueError("En az bir varyant belirtilmeli.")
    unknown = [v for v in items if v not in ALL_VALID_VARIANTS]
    if unknown:
        raise ValueError(f"Bilinmeyen varyant(lar): {unknown}. Geçerli: {DEFAULT_VARIANTS}")
    return items


def _cache_file(cache_dir, variant, year):
    return os.path.join(str(cache_dir), f"pred_{variant}_{int(year)}.pkl")


def _align_cached_preds(te_df, cached_df):
    """Align cached `(race_id, horse_key, p)` onto `te_df`; return 1D array or `None` if incomplete."""
    if not isinstance(cached_df, pd.DataFrame) or not {"race_id", "horse_key", "p"}.issubset(cached_df.columns):
        return None
    left = pd.DataFrame(
        {
            "_rid": te_df["race_id"].astype("string").to_numpy(),
            "_hk": te_df["horse_key"].astype("string").to_numpy(),
        }
    )
    right = cached_df[["race_id", "horse_key", "p"]].copy()
    right["_rid"] = right["race_id"].astype("string")
    right["_hk"] = right["horse_key"].astype("string")
    right = right.drop_duplicates(subset=["_rid", "_hk"], keep="last")[["_rid", "_hk", "p"]]
    merged = left.merge(right, on=["_rid", "_hk"], how="left")
    p_arr = pd.to_numeric(merged["p"], errors="coerce").to_numpy(dtype=np.float64)
    if not np.all(np.isfinite(p_arr)):
        return None
    return p_arr


def _winner_table_for_preds(eval_df, variant_cols):
    """Build race-indexed winner table containing `hit_<v>` and `ll_<v>` per variant."""
    work = eval_df[["race_id", "_year", "win"]].copy()
    for v in variant_cols:
        col = f"p_{v}"
        if col not in eval_df.columns:
            continue
        p_s = eval_df[col]
        valid_mask = p_s.notna()
        rk = pd.Series(np.nan, index=eval_df.index, dtype="float64")
        if valid_mask.any():
            rk.loc[valid_mask] = (
                eval_df.loc[valid_mask].groupby("race_id")[col].rank(ascending=False, method="first")
            )
        work[f"p_{v}"] = p_s
        work[f"rk_{v}"] = rk

    winners = work[work["win"] == 1].copy().set_index("race_id")
    for v in variant_cols:
        col = f"p_{v}"
        if col not in winners.columns:
            continue
        p_w = winners[col]
        rk_w = winners[f"rk_{v}"]
        winners[f"hit_{v}"] = np.where(p_w.notna(), (rk_w == 1).astype(np.float64), np.nan)
        winners[f"ll_{v}"] = np.where(p_w.notna(), -np.log(p_w.clip(lower=1e-6)), np.nan)
    return winners


def _summarize_variant_on_winners(w_df, variant):
    """Compute race count, top-1 accuracy, log-loss, and paired bootstrap diffs vs B0 and B1."""
    h_col = f"hit_{variant}"
    l_col = f"ll_{variant}"
    if h_col not in w_df.columns:
        return None
    sub = w_df[w_df[h_col].notna() & w_df[l_col].notna()]
    n = len(sub)
    if n == 0:
        return None

    hit_v = sub[h_col].to_numpy(dtype=np.float64)
    ll_v = sub[l_col].to_numpy(dtype=np.float64)

    res = {
        "variant": variant,
        "races": int(n),
        "acc": float(hit_v.mean()),
        "ll": float(ll_v.mean()),
    }

    for base_lbl in ("B0", "B1"):
        bh_col = f"hit_{base_lbl}"
        bl_col = f"ll_{base_lbl}"
        if variant == base_lbl:
            res[f"acc_diff_{base_lbl}"] = 0.0
            res[f"acc_lo_{base_lbl}"] = 0.0
            res[f"acc_hi_{base_lbl}"] = 0.0
            res[f"ll_diff_{base_lbl}"] = 0.0
            res[f"ll_lo_{base_lbl}"] = 0.0
            res[f"ll_hi_{base_lbl}"] = 0.0
        elif bh_col in sub.columns and sub[bh_col].notna().all():
            d_acc = hit_v - sub[bh_col].to_numpy(dtype=np.float64)
            d_ll = ll_v - sub[bl_col].to_numpy(dtype=np.float64)
            am, alo, ahi = bootstrap_mean_ci(d_acc, n_boot=2000, seed=0)
            lm, llo, lhi = bootstrap_mean_ci(d_ll, n_boot=2000, seed=0)
            res[f"acc_diff_{base_lbl}"] = am
            res[f"acc_lo_{base_lbl}"] = alo
            res[f"acc_hi_{base_lbl}"] = ahi
            res[f"ll_diff_{base_lbl}"] = lm
            res[f"ll_lo_{base_lbl}"] = llo
            res[f"ll_hi_{base_lbl}"] = lhi
        else:
            pair = sub[sub[bh_col].notna() & sub[bl_col].notna()] if bh_col in sub.columns else pd.DataFrame()
            if len(pair) > 0:
                d_acc = pair[h_col].to_numpy(dtype=np.float64) - pair[bh_col].to_numpy(dtype=np.float64)
                d_ll = pair[l_col].to_numpy(dtype=np.float64) - pair[bl_col].to_numpy(dtype=np.float64)
                am, alo, ahi = bootstrap_mean_ci(d_acc, n_boot=2000, seed=0)
                lm, llo, lhi = bootstrap_mean_ci(d_ll, n_boot=2000, seed=0)
                res[f"acc_diff_{base_lbl}"] = am
                res[f"acc_lo_{base_lbl}"] = alo
                res[f"acc_hi_{base_lbl}"] = ahi
                res[f"ll_diff_{base_lbl}"] = lm
                res[f"ll_lo_{base_lbl}"] = llo
                res[f"ll_hi_{base_lbl}"] = lhi
            else:
                for k in ("acc_diff", "acc_lo", "acc_hi", "ll_diff", "ll_lo", "ll_hi"):
                    res[f"{k}_{base_lbl}"] = np.nan

    return res


def _fmt_acc_diff(row, base_lbl):
    if row["variant"] == base_lbl:
        return "—"
    d = row.get(f"acc_diff_{base_lbl}", np.nan)
    lo = row.get(f"acc_lo_{base_lbl}", np.nan)
    hi = row.get(f"acc_hi_{base_lbl}", np.nan)
    if not np.isfinite(d):
        return "—"
    return f"`{d:+.2%}` (`{lo:+.2%}`…`{hi:+.2%}`)"


def _fmt_ll_diff(row, base_lbl):
    if row["variant"] == base_lbl:
        return "—"
    d = row.get(f"ll_diff_{base_lbl}", np.nan)
    lo = row.get(f"ll_lo_{base_lbl}", np.nan)
    hi = row.get(f"ll_hi_{base_lbl}", np.nan)
    if not np.isfinite(d):
        return "—"
    return f"`{d:+.4f}` (`{lo:+.4f}`…`{hi:+.4f}`)"


def format_v5_report(
    *,
    locked,
    meta,
    fill_rows,
    overall_rows,
    yearly_rows,
    benter_rows,
    uncombined_years,
    warnings_list,
    edge_tables,
):
    title = (
        "# Ganyan Model v5 — Kilitli Test Raporu (2026+)"
        if locked
        else "# Ganyan Model v5 — Yeni Özellik Blokları, Benter Birleşimi ve Ablasyon Raporu"
    )
    lines = [
        title,
        "",
        "> **Uyarı:** Tarihsel değerlendirmede kapanış AGF (`agf_close`) kullanılır; canlıda koşudan önce alınan AGF daha az bilgi içerir.",
        "",
        "## 1. Veri Özeti ve Blok Doluluk Oranları",
        "",
        f"- **Veri Aralığı (DB):** `{meta['db_min_date']}` … `{meta['db_max_date']}`",
        f"- **Toplam Koşucu / Koşu (tüm dönem):** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Eğitim Başlangıcı:** `{meta['start_year']}-01-01` | **İlk Test Yılı:** `{meta['first_test_year']}` | **Bitiş Sınırı:** `{meta['end_date_label']}`",
        f"- **Program Sütunları (`son6/kgs/s20/best_sf`):** `{'Açık (--with-program)' if meta['with_program'] else 'Çıkarıldı (varsayılan)'}`",
        f"- **Değerlendirme Kümesi (eval süzgeci sonrası test dönemi):** `{meta['eval_rows']:,}` satır / `{meta['eval_races']:,}` koşu (`{meta['eval_min_date']}` … `{meta['eval_max_date']}`)",
    ]

    comb_years = sorted({int(r["year"]) for r in benter_rows})
    if comb_years:
        lines.append(f"- **Benter Birleşimli (`+B`) Yıllar:** `{', '.join(str(y) for y in comb_years)}`")
    else:
        lines.append("- **Benter Birleşimli (`+B`) Yıllar:** Yok (`Y−2/Y−1` örnek-dışı tahmini bulunan yıl yok)")
    if uncombined_years:
        lines.append(
            f"- **Birleşimsiz Yıllar (`Y−2/Y−1` tahmini olmadığı için `+B` üretilmeyen):** `{', '.join(str(y) for y in sorted(uncombined_years))}`"
        )
    if warnings_list:
        lines.append("- **Uyarılar:** " + "; ".join(warnings_list))

    lines += [
        "",
        "### Blok Doluluk Oranları",
        "",
        "| Blok | Sütun | Tüm Veri Dolu (%) | Test Kümesi Dolu (%) | Test Sıfır-Dışı (%) |",
        "|---|---|---:|---:|---:|",
    ]
    for fr in fill_rows:
        lines.append(
            f"| {fr['block']} | `{fr['col']}` | {fr['all_fill']:.1%} | {fr['eval_fill']:.1%} | {fr['eval_nonzero']:.1%} |"
        )

    lines += [
        "",
        "## 2. Toplam Performans Özeti (Koşu-Eşli Bootstrap %95 GA, 2000 Tekrar)",
        "",
        "| Varyant | Koşu | 1. Tercih İsabeti | Ort. Log-Loss | Δİsabet vs B0 (%95 GA) | ΔLL vs B0 (%95 GA) | Δİsabet vs B1 (%95 GA) | ΔLL vs B1 (%95 GA) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in overall_rows:
        lines.append(
            f"| `{r['variant']}` | {r['races']} | {r['acc']:.2%} | {r['ll']:.4f} | "
            f"{_fmt_acc_diff(r, 'B0')} | {_fmt_ll_diff(r, 'B0')} | "
            f"{_fmt_acc_diff(r, 'B1')} | {_fmt_ll_diff(r, 'B1')} |"
        )

    lines += [
        "",
        "## 3. Yıllık İleri-Yürüyen Performans",
        "",
        "| Yıl | Varyant | Koşu | 1. Tercih İsabeti | Ort. Log-Loss | Δİsabet vs B0 (%95 GA) | ΔLL vs B0 (%95 GA) | Δİsabet vs B1 (%95 GA) | ΔLL vs B1 (%95 GA) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in yearly_rows:
        lines.append(
            f"| {r['year']} | `{r['variant']}` | {r['races']} | {r['acc']:.2%} | {r['ll']:.4f} | "
            f"{_fmt_acc_diff(r, 'B0')} | {_fmt_ll_diff(r, 'B0')} | "
            f"{_fmt_acc_diff(r, 'B1')} | {_fmt_ll_diff(r, 'B1')} |"
        )

    lines += [
        "",
        "## 4. Benter Birleşimi Katsayıları (`p_i ∝ exp(a·log p_fund + b·log p_agf)`)",
        "",
    ]
    if benter_rows:
        lines += [
            "| Varyant | Test Yılı | Uydurma Yılları | Uydurma Koşu | `a` (Temel Model) | `b` (AGF) |",
            "|---|---:|---|---:|---:|---:|",
        ]
        for br in benter_rows:
            lines.append(
                f"| `{br['variant']}` | {br['year']} | {br['fit_years']} | {br['fit_races']} | {br['a']:.4f} | {br['b']:.4f} |"
            )
    else:
        lines.append("Bu koşuda Benter birleşimi için yeterli geçmiş test yılı (`Y−2/Y−1`) bulunmadı.")

    lines += [
        "",
        "## 5. Kenar Kovası (Edge) ROI Tablosu (`edge = p_model / p_mkt`, 1 TL Ganyan)",
        "",
    ]
    for v_name, tbl_info in edge_tables.items():
        lines += [
            f"### `{v_name}` Kenar Kovaları",
            "",
            "| Kenar Kovası (`p_model / p_mkt`) | Bahis Sayısı | Kazanma % | ROI | ROI %95 GA |",
            "|---|---:|---:|---:|---:|",
        ]
        for _, er in tbl_info["buckets"].iterrows():
            if int(er["bets"]) == 0:
                lines.append(f"| `{er['bucket']}` | 0 | — | — | — |")
            else:
                lines.append(
                    f"| `{er['bucket']}` | {int(er['bets'])} | {er['win_rate']:.2%} | "
                    f"`{er['roi']:+.2%}` | `[{er['ci95_low']:+.2%}, {er['ci95_high']:+.2%}]` |"
                )
        lines += [
            "",
            "| Ek Strateji (1 TL Ganyan) | Bahis Sayısı | Kazanma % | ROI | ROI %95 GA |",
            "|---|---:|---:|---:|---:|",
        ]
        for s_label, s_dict in [
            (f"Yalnız `{v_name}` 1. Tercihi", tbl_info["top1_model"]),
            ("Yalnız AGF 1. Tercihi", tbl_info["top1_agf"]),
        ]:
            if int(s_dict["bets"]) == 0:
                lines.append(f"| {s_label} | 0 | — | — | — |")
            else:
                lines.append(
                    f"| {s_label} | {int(s_dict['bets'])} | {s_dict['win_rate']:.2%} | "
                    f"`{s_dict['roi']:+.2%}` | `[{s_dict['ci95_low']:+.2%}, {s_dict['ci95_high']:+.2%}]` |"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_v5_backtest(
    db_path="data/ganyan.db",
    out_path=None,
    start_year=2015,
    first_test_year=2017,
    end_date=None,
    variants=None,
    cache_dir="data/v5_cache",
    with_program=False,
    locked=False,
    force=False,
):
    """Execute Model v5 yearly walk-forward evaluation and write Markdown report."""
    start_year = int(start_year)
    first_test_year = int(first_test_year)

    if not locked:
        eff_end_str = str(end_date) if end_date is not None else "2025-12-31"
        eff_end_ts = pd.Timestamp(eff_end_str)
        if eff_end_ts > LOCKED_CUTOFF:
            raise ValueError(
                f"--locked verilmedikçe --end-date 2025-12-31'i aşamaz (verilen: {eff_end_str})."
            )
    else:
        eff_end_str = str(end_date) if end_date is not None else None
        eff_end_ts = pd.Timestamp(eff_end_str) if eff_end_str is not None else None

    target_out = out_path or ("reports/V5_LOCKED.md" if locked else "reports/V5.md")
    if locked and os.path.exists(target_out) and not force:
        raise FileExistsError(
            f"Kilitli rapor zaten mevcut: {target_out}. Üzerine yazmak için --force kullanın."
        )

    req_variants = _parse_variants(variants, locked=locked)

    conn = _open_ro_db(db_path)
    try:
        runners_df = load_runners_from_db(conn)
        tables = load_v5_tables(conn)
    finally:
        conn.close()

    if len(runners_df) == 0:
        raise ValueError("Veritabanında değerlendirilecek koşucu satırı bulunamadı.")

    runners_df["date"] = pd.to_datetime(runners_df["date"])
    if eff_end_ts is not None:
        runners_df = runners_df[runners_df["date"] <= eff_end_ts].copy()
        if len(tables["workouts"]) > 0:
            w_df = tables["workouts"]
            tables = {
                "ext": tables["ext"],
                "workouts": w_df[w_df["date"] <= eff_end_ts].copy(),
            }

    if len(runners_df) == 0:
        raise ValueError("Tarih süzgeci sonrası koşucu satırı kalmadı.")

    ref_end = f"{first_test_year}-01-01"
    df = build_features(runners_df, ref_end=ref_end)
    df = attach_v5(df, tables, blocks=("S", "G", "R"))
    df["_year"] = df["date"].dt.year.astype(np.int32)

    eval_mask = _eval_filter_mask(df)
    eval_all = df[eval_mask].copy()

    if locked:
        eval_target = eval_all[eval_all["date"] >= LOCKED_START].copy()
    else:
        eval_target = eval_all[eval_all["_year"] >= first_test_year].copy()

    test_years = sorted(int(y) for y in eval_target["_year"].unique())

    base_cols = get_base_cols(with_program=with_program)
    b1_cols = get_b1_cols(with_program=with_program)
    train_start_ts = pd.Timestamp(f"{start_year}-01-01")

    os.makedirs(cache_dir, exist_ok=True)
    warnings_list = []
    warned_keys = set()

    def _warn_once(key, msg):
        if key not in warned_keys:
            warned_keys.add(key)
            warnings_list.append(msg)
            print(f"UYARI: {msg}", flush=True)

    mem_base_preds = {}

    def get_base_year_pred(base_var, year):
        year = int(year)
        key = (base_var, year)
        if key in mem_base_preds:
            return mem_base_preds[key]

        te_y = eval_all[eval_all["_year"] == year]
        if len(te_y) == 0:
            mem_base_preds[key] = None
            return None

        c_path = _cache_file(cache_dir, base_var, year)
        if os.path.exists(c_path):
            cached = pd.read_pickle(c_path)
            aligned = _align_cached_preds(te_y, cached)
            if aligned is not None:
                mem_base_preds[key] = aligned
                return aligned

        if base_var == "B0":
            p_arr = te_y["agf_share"].to_numpy(dtype=np.float64)
        else:
            y_start = pd.Timestamp(f"{year}-01-01")
            tr = df[(df["date"] >= train_start_ts) & (df["date"] < y_start) & df["win"].notna()]
            if base_var == "B1":
                tr = tr[tr["agf_share"].notna()]
                cols = b1_cols
            else:
                blocks_needed = FUND_VARIANTS[base_var]
                cols = list(base_cols)
                for blk in blocks_needed:
                    cols.extend(BLOCK_COLS[blk])

            if len(tr) == 0 or (tr["finish"] == 1).nunique() < 2:
                _warn_once(
                    (base_var, year),
                    f"{year} yılı ({base_var}) için eğitim verisi yok/yetersiz (satır={len(tr)}), yıl atlandı",
                )
                mem_base_preds[key] = None
                return None

            if base_var == "B1":
                p_arr = fit_predict_df(tr, te_y, cols)
            else:
                p_arr = fit_predict_fund(tr, te_y, cols)

        save_df = pd.DataFrame(
            {
                "race_id": te_y["race_id"].to_numpy(),
                "horse_key": te_y["horse_key"].to_numpy(),
                "p": p_arr,
            }
        )
        save_df.to_pickle(c_path)
        mem_base_preds[key] = p_arr
        return p_arr

    # Always include B0 and B1 internally so diff columns vs B0 and B1 are populated
    compute_variants = list(dict.fromkeys(["B0", "B1"] + req_variants))
    for v in compute_variants:
        eval_target[f"p_{v}"] = np.nan

    benter_rows = []
    uncombined_years = set()

    for y in test_years:
        y_mask = (eval_target["_year"] == y).to_numpy()
        te_y = eval_target[y_mask]
        if len(te_y) == 0:
            continue

        for v in compute_variants:
            if not v.endswith("+B"):
                p_y = get_base_year_pred(v, y)
                if p_y is not None:
                    eval_target.loc[y_mask, f"p_{v}"] = p_y
            else:
                fund_v = v[:-2]
                p_fund_y = get_base_year_pred(fund_v, y)
                if p_fund_y is None:
                    continue

                c_path_b = _cache_file(cache_dir, v, y)
                if os.path.exists(c_path_b):
                    cached_b = pd.read_pickle(c_path_b)
                    aligned_b = _align_cached_preds(te_y, cached_b)
                    if aligned_b is not None:
                        eval_target.loc[y_mask, f"p_{v}"] = aligned_b
                        if v in req_variants and {"a", "b", "fit_years", "fit_races"}.issubset(cached_b.columns):
                            benter_rows.append(
                                {
                                    "variant": v,
                                    "year": int(y),
                                    "fit_years": str(cached_b["fit_years"].iloc[0]),
                                    "fit_races": int(cached_b["fit_races"].iloc[0]),
                                    "a": float(cached_b["a"].iloc[0]),
                                    "b": float(cached_b["b"].iloc[0]),
                                }
                            )
                        continue

                prior_frames = []
                used_fit_years = []
                for py in (y - 2, y - 1):
                    if py < first_test_year:
                        continue
                    p_py = get_base_year_pred(fund_v, py)
                    if p_py is None:
                        continue
                    sub_py = eval_all[eval_all["_year"] == py][["race_id", "agf_share", "win"]].copy()
                    sub_py["p_fund"] = p_py
                    prior_frames.append(sub_py)
                    used_fit_years.append(py)

                if not prior_frames:
                    if v in req_variants:
                        uncombined_years.add(int(y))
                    continue

                fit_df = pd.concat(prior_frames, ignore_index=True)
                comb = BenterCombiner(clip_min=1e-6)
                comb.fit(
                    to_log_prob(fit_df["p_fund"].to_numpy(dtype=np.float64), 1e-6),
                    to_log_prob(fit_df["agf_share"].to_numpy(dtype=np.float64), 1e-6),
                    fit_df["race_id"].to_numpy(),
                    (fit_df["win"] == 1).to_numpy(),
                )
                p_comb = comb.predict(
                    to_log_prob(p_fund_y, 1e-6),
                    to_log_prob(te_y["agf_share"].to_numpy(dtype=np.float64), 1e-6),
                    te_y["race_id"].to_numpy(),
                )
                eval_target.loc[y_mask, f"p_{v}"] = p_comb

                fit_years_str = ",".join(str(fy) for fy in used_fit_years)
                fit_races_n = int(fit_df["race_id"].nunique())
                save_b = pd.DataFrame(
                    {
                        "race_id": te_y["race_id"].to_numpy(),
                        "horse_key": te_y["horse_key"].to_numpy(),
                        "p": p_comb,
                        "a": comb.a,
                        "b": comb.b,
                        "fit_years": fit_years_str,
                        "fit_races": fit_races_n,
                    }
                )
                save_b.to_pickle(c_path_b)
                if v in req_variants:
                    benter_rows.append(
                        {
                            "variant": v,
                            "year": int(y),
                            "fit_years": fit_years_str,
                            "fit_races": fit_races_n,
                            "a": comb.a,
                            "b": comb.b,
                        }
                    )

    winners_all = _winner_table_for_preds(eval_target, compute_variants)

    overall_rows = []
    for v in req_variants:
        st = _summarize_variant_on_winners(winners_all, v)
        if st is not None:
            overall_rows.append(st)

    yearly_rows = []
    for y in test_years:
        w_y = winners_all[winners_all["_year"] == y]
        if len(w_y) == 0:
            continue
        for v in req_variants:
            st = _summarize_variant_on_winners(w_y, v)
            if st is not None:
                st["year"] = int(y)
                yearly_rows.append(st)

    # Edge-bucket ROI tables for F_SGR+B and B1
    edge_tables = {}
    for ev in ("F_SGR+B", "B1"):
        p_col = f"p_{ev}"
        if p_col in eval_target.columns and eval_target[p_col].notna().any():
            sub_ev = eval_target[eval_target[p_col].notna()].copy()
            edge_tables[ev] = {
                "buckets": compute_edge_buckets(sub_ev, p_col, n_boot=2000, seed=0),
                "top1_model": compute_top1_roi(sub_ev, p_col, n_boot=2000, seed=0),
                "top1_agf": compute_top1_roi(sub_ev, "agf_share", n_boot=2000, seed=0),
            }

    # Block fill rates
    fill_rows = []
    for blk in ("S", "G", "R"):
        for col in BLOCK_COLS[blk]:
            all_fill = float(df[col].notna().mean()) if len(df) > 0 else 0.0
            eval_fill = float(eval_target[col].notna().mean()) if len(eval_target) > 0 else 0.0
            eval_nz = (
                float((eval_target[col].notna() & (eval_target[col] != 0)).mean())
                if len(eval_target) > 0
                else 0.0
            )
            fill_rows.append(
                {
                    "block": blk,
                    "col": col,
                    "all_fill": all_fill,
                    "eval_fill": eval_fill,
                    "eval_nonzero": eval_nz,
                }
            )

    meta = {
        "db_min_date": df["date"].min().strftime("%Y-%m-%d"),
        "db_max_date": df["date"].max().strftime("%Y-%m-%d"),
        "total_rows": int(len(df)),
        "total_races": int(df["race_id"].nunique()),
        "start_year": start_year,
        "first_test_year": first_test_year,
        "end_date_label": eff_end_str if eff_end_str is not None else "2026+ (kilitli test)",
        "with_program": bool(with_program),
        "eval_rows": int(len(eval_target)),
        "eval_races": int(eval_target["race_id"].nunique()),
        "eval_min_date": (
            eval_target["date"].min().strftime("%Y-%m-%d") if len(eval_target) > 0 else "—"
        ),
        "eval_max_date": (
            eval_target["date"].max().strftime("%Y-%m-%d") if len(eval_target) > 0 else "—"
        ),
    }

    report_md = format_v5_report(
        locked=locked,
        meta=meta,
        fill_rows=fill_rows,
        overall_rows=overall_rows,
        yearly_rows=yearly_rows,
        benter_rows=benter_rows,
        uncombined_years=uncombined_years,
        warnings_list=warnings_list,
        edge_tables=edge_tables,
    )

    out_dir = os.path.dirname(str(target_out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(target_out, "w", encoding="utf-8") as f:
        f.write(report_md)

    return {
        "report_path": str(target_out),
        "report_markdown": report_md,
        "overall_df": pd.DataFrame(overall_rows),
        "yearly_df": pd.DataFrame(yearly_rows),
        "benter_df": pd.DataFrame(benter_rows),
        "edge_tables": edge_tables,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v5 yıllık ileri-yürüyen değerlendirme ve ablasyon raporu."
    )
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--out", default=None)
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--first-test-year", type=int, default=2017)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--variants", default=None, help="Virgülle ayrılmış varyant listesi")
    ap.add_argument("--cache-dir", default="data/v5_cache")
    ap.add_argument("--with-program", action="store_true")
    ap.add_argument("--locked", action="store_true")
    ap.add_argument("--force", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        res = run_v5_backtest(
            db_path=args.db,
            out_path=args.out,
            start_year=args.start_year,
            first_test_year=args.first_test_year,
            end_date=args.end_date,
            variants=args.variants,
            cache_dir=args.cache_dir,
            with_program=args.with_program,
            locked=args.locked,
            force=args.force,
        )
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Rapor yazıldı: {res['report_path']}", flush=True)


if __name__ == "__main__":
    main()
