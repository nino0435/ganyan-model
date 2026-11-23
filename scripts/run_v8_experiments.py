"""Walk-forward experimentation, Stage A/B/C gating, and report generator for Model v8 (Packets A, K, N)."""
import argparse
import gc
import os
import sys
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.backtest import load_runners_from_db
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5, load_v5_tables
from ganyan.features_v7 import attach_v7
from ganyan.features_v8 import V8_BLOCK_COLS, attach_v8, get_v8_cols
from ganyan.model_v6 import (
    STAGE_A_YEARS,
    STAGE_B_YEARS,
    STAGE_C_YEARS,
    evaluate_stage_b_gate,
)
from ganyan.model_v7 import V7_CONFIG
from scripts.run_v6_experiments import (
    CAL_WARMUP_YEAR,
    REF_END_DEFAULT,
    SMOKE_TEST_YEAR,
    _ProgressTracker,
    _concat_year_preds,
    _drop_unfinished_races,
    _eval_filter_mask,
    _fmt_dll_ci,
    _open_ro_db,
    _predict_base_year,
    _predict_calibrated_year,
    _race_winner_lls,
    _summarize_period_metrics,
)
from scripts.run_v7_experiments import _format_yearly_dll_matrix

BASE_V8_SPECS = [
    ("V7_1s", (), "V7 tabanı (100 özellik, 1 tohum)"),
    ("V8_A", ("A",), "V7 + Paket A (at prime/zirve/yıpranma ve form eğimi, 10 özellik)"),
    ("V8_K", ("K",), "V7 + Paket K (jokey prime, kıdem, çoklu pencere form, 7 özellik)"),
    ("V8_N", ("N",), "V7 + Paket N (ahır ağı, aile bağı, ikili uyumu ve uyanış, 12 özellik)"),
    ("V8_AKN", ("A", "K", "N"), "V7 + 3 paket birlikte (A+K+N, 29 yeni özellik)"),
]

SEL_THRESHOLD_DLL = -0.0002


def _make_variant_cfg(
    name,
    v8_blocks,
    seeds=(0,),
    calibration=None,
    calibrated_from=None,
    description="",
    extra_meta=None,
):
    cfg = {
        "variant": str(name),
        "family": "V8" if v8_blocks else "V7",
        "description": str(description),
        "history_start": str(V7_CONFIG["history_start"]),
        "history_start_year": int(V7_CONFIG["history_start_year"]),
        "train_start_year": int(V7_CONFIG["train_start_year"]),
        "require_agf": bool(V7_CONFIG["require_agf"]),
        "v7_blocks": list(V7_CONFIG["v7_blocks"]),
        "v8_blocks": list(v8_blocks),
        "feature_cols": get_v8_cols(v8_blocks=v8_blocks, with_program=False),
        "hgb_params": dict(V7_CONFIG["hgb_params"]),
        "temporal_val_frac": None,
        "seeds": [int(s) for s in seeds],
        "calibration": calibration,
    }
    if calibrated_from is not None:
        cfg["calibrated_from"] = str(calibrated_from)
    if extra_meta:
        for k, v in sorted(extra_meta.items()):
            cfg[str(k)] = v
    return cfg


def _build_v8_history_frame(runners_df, v5_tables, max_date=None):
    """Build single leak-free feature DataFrame (`2006-03-04`->) with V5 + V7 + V8 packets attached."""
    start_ts = pd.Timestamp(V7_CONFIG["history_start"])
    mask = runners_df["date"] >= start_ts
    if max_date is not None:
        mask = mask & (runners_df["date"] <= pd.Timestamp(max_date))
    r_sub = runners_df[mask].copy()
    if len(r_sub) == 0:
        r_sub = (
            runners_df.copy()
            if max_date is None
            else runners_df[runners_df["date"] <= pd.Timestamp(max_date)].copy()
        )

    w_df = v5_tables["workouts"]
    if len(w_df) > 0:
        w_mask = w_df["date"] >= start_ts
        if max_date is not None:
            w_mask = w_mask & (w_df["date"] <= pd.Timestamp(max_date))
        w_sub = w_df[w_mask].copy()
    else:
        w_sub = w_df

    df = build_features(r_sub, ref_end=REF_END_DEFAULT)
    del r_sub
    df = attach_v5(df, {"ext": v5_tables["ext"], "workouts": w_sub}, blocks=("S", "G", "R"))
    df = attach_v7(df, blocks=tuple(V7_CONFIG["v7_blocks"]))
    df = attach_v8(df, blocks=("A", "K", "N"))
    df["_year"] = df["date"].dt.year.astype(np.int32)
    df["_has_race_win"] = df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    df["_is_eval"] = _eval_filter_mask(df)
    return df


def _compute_v8_coverage_tables(df_hist, eval_mask, min_eval_year=2017):
    """Compute per-feature fill rates and yearly (`2015–2026`) packet coverage summaries."""
    eval_target = eval_mask & (df_hist["_year"] >= int(min_eval_year))
    feat_rows = []
    for blk, cols in V8_BLOCK_COLS.items():
        for col in cols:
            s_all = df_hist[col]
            s_ev = df_hist.loc[eval_target, col]
            feat_rows.append({
                "block": blk,
                "col": col,
                "all_fill": float(s_all.notna().mean()) if len(s_all) else 0.0,
                "eval_fill": float(s_ev.notna().mean()) if len(s_ev) else 0.0,
                "eval_nonzero": float((s_ev.notna() & (s_ev != 0)).mean()) if len(s_ev) else 0.0,
            })

    sub15 = df_hist[df_hist["_year"] >= 2015]
    yearly_rows = []
    for yr, grp in sub15.groupby("_year", sort=True):
        yearly_rows.append({
            "year": int(yr),
            "races": int(grp["race_id"].nunique()),
            "runners": int(len(grp)),
            "a_hp_drop": float(grp["hp_drop_from_peak"].notna().mean()),
            "a_layoff": float((grp["h_layoff_run_no"].notna() & (grp["h_layoff_run_no"] > 0)).mean()),
            "k_cy": float(grp["j_career_yrs"].notna().mean()),
            "k_ap": float((grp["j_is_ap"].notna() & (grp["j_is_ap"] > 0)).mean()),
            "n_own": float((grp["own_mates_cnt"] > 0).mean()),
            "n_trn": float((grp["trn_mates_cnt"] > 0).mean()),
            "n_fam": float((grp["fam_hidden_ekuri"] > 0).mean()),
            "n_wake": float((grp["sleep_wakeup_flag"].notna() & (grp["sleep_wakeup_flag"] > 0)).mean()),
        })
    return feat_rows, yearly_rows


def format_v8_report(
    *,
    smoke,
    meta,
    feat_fill_rows,
    yearly_cov_rows,
    stage1_rows,
    stage1_years,
    selected_blocks,
    sel_ran,
    stage2_rows,
    stage2_years,
    stage3_selected,
    stage3_b_rows,
    stage3_b_yearly_detail,
    stage3_gate_results,
    stage3_winner,
    stage3_c_rows,
    stage3_c_years,
    cal_param_rows,
):
    title = (
        "# Ganyan Model v8 — Duman Testi Raporu (--smoke)"
        if smoke
        else "# Ganyan Model v8 — Prime Dönem ve Ahır Ağı Paket Deneyleri (A, K, N) ve Doğrulama Kapısı"
    )
    lines = [
        title,
        "",
        "> **Uyarı 1 (Kapanış AGF):** Tarihsel değerlendirmede kapanış AGF (`agf_close`) kullanılır; canlıda koşudan önce alınan AGF daha az bilgi içerir.",
        "> **Uyarı 2 (Seçim Protokolü):** Aday seçimi ve blok birleşimi (`V8_SEL`) yalnız Aşama A (`2017–2021`) üzerinde yapılmış, Aşama B (`2022–2025`) sabit kapısına taşınmıştır.",
        "",
        "## 1. Veri Özeti ve V8 Paket Doluluk Oranları (`2015–2026`)",
        "",
        f"- **Veritabanı:** `{meta['db_path']}` (salt-okunur)",
        f"- **Veri Aralığı (DB):** `{meta['db_min_date']}` … `{meta['db_max_date']}`",
        f"- **Toplam Sonuçlanmış Koşucu / Koşu:** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Taban Model (`V7_CONFIG`):** `V7_TCJP_CAL` (`100` özellik, `min_samples_leaf=400`, `l2=15.0`, `lr=0.03`, `max_iter=420`, `leaf=23`, `es=False`)",
        f"- **Değerlendirme Koşu Sayıları:** Aşama A `{meta['stage_a_races']:,}` | Aşama B `{meta['stage_b_races']:,}` | Aşama C (2026 bilgi) `{meta['stage_c_races']:,}`",
        "",
    ]

    if yearly_cov_rows:
        lines += [
            "### Yıllık V8 Paket Doluluk ve Sinyal Oranları (`2015–2026`)",
            "",
            "| Yıl | Koşu | Koşucu | `hp_drop` Dolu | `layoff>0` | `j_career_yrs` | `j_is_ap` | `own_mates>0` | `trn_mates>0` | `fam_ekuri` | `sleep_wake` |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for yr in yearly_cov_rows:
            lines.append(
                f"| {yr['year']} | {yr['races']:,} | {yr['runners']:,} | "
                f"{yr['a_hp_drop']:.1%} | {yr['a_layoff']:.1%} | {yr['k_cy']:.1%} | {yr['k_ap']:.1%} | "
                f"{yr['n_own']:.1%} | {yr['n_trn']:.1%} | {yr['n_fam']:.1%} | {yr['n_wake']:.2%} |"
            )

    if feat_fill_rows:
        lines += [
            "",
            "### V8 Özellik Doluluk Özeti (`2017+` Değerlendirme Kümesi)",
            "",
            "| Paket | Sütun | Tüm Veri Dolu (%) | Değerlendirme Dolu (%) | Değerlendirme Sıfır-Dışı (%) |",
            "|---|---|---:|---:|---:|",
        ]
        for fr in feat_fill_rows:
            lines.append(
                f"| `{fr['block']}` | `{fr['col']}` | {fr['all_fill']:.1%} | {fr['eval_fill']:.1%} | {fr['eval_nonzero']:.1%} |"
            )

    a_lbl = f"{min(stage1_years)}–{max(stage1_years)}" if stage1_years else "—"
    lines += [
        "",
        f"## 2. Aşama A Tarama Sonuçları (`{a_lbl}`, 1-Tohum `seed=0`)",
        "",
        f"- **Otomatik Seçim Kuralı (`V8_SEL`):** Aşama A'da `ΔLL(paket − V7_1s) < {SEL_THRESHOLD_DLL:+.4f}` sağlayan paketler: "
        + (", ".join(f"`{b}`" for b in selected_blocks) if selected_blocks else "yok")
        + (" (`V8_SEL` çalıştırıldı)" if sel_ran else " (`V8_SEL` çalıştırılmadı — tek/sıfır/tüm paket ile örtüşüyor)"),
        "",
        "| Varyant | Koşu | Log-Loss | ΔLL vs `V7_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    for r in stage1_rows:
        v = r["variant"]
        lines.append(
            f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V7_1s'))} | "
            f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
        )
    lines.extend(_format_yearly_dll_matrix(stage1_rows, stage1_years, "V7_1s", "Aşama A Yıllık ΔLL(varyant − V7_1s)"))

    lines += [
        "",
        "## 3. Aşama B Tanısal Karşılaştırma (`2022–2025`, 1-Tohum `seed=0`)",
        "",
        "> **Not:** Bu tablo tüm tekil paketlerin ve birleşimlerin örnek-dışı davranışını şeffafça görmek için **tanısaldır**; model seçimi yukarıdaki Aşama A'da dondurulmuştur.",
        "",
    ]
    if smoke or not stage2_rows:
        lines.append("Duman testinde Aşama B tanısal tablosu hesaplanmadı.")
    else:
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V7_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|",
        ]
        for r in stage2_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V7_1s'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )
        lines.extend(_format_yearly_dll_matrix(stage2_rows, stage2_years, "V7_1s", "Aşama B Tanısal Yıllık ΔLL(varyant − V7_1s)"))

    lines += [
        "",
        "## 4. Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)",
        "",
        "- **Kapı Kuralı (`evaluate_stage_b_gate`):** `ΔLL(aday − V7_BASE)` için koşu-eşli bootstrap %95 GA üst sınırı `< 0` **VE** `4` yılın en az `3`'ünde `ΔLL < 0`.",
        "",
    ]
    if smoke:
        lines.append("Duman testinde Aşama 3 tam kapı koşusu çalıştırılmadı.")
    elif not stage3_selected:
        lines.append(
            "**SONUÇ:** Aşama A (`2017–2021`) taramasında hiçbir V8 adayı `V7_1s` tabanını (`ΔLL < 0`) geçemediğinden Aşama 3 (5-tohum + kalibrasyon) atlandı; **V7 korunur**."
        )
    else:
        lines.append(f"- **Aşama A'dan Seçilen Finalistler:** {', '.join(f'`{x}`' for x in stage3_selected)}")
        lines.append("")
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V7_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı Kararı |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for r in stage3_b_rows:
            v = r["variant"]
            if v == "B0":
                g_txt = "Referans (Saf AGF)"
            elif v == "V7_BASE":
                g_txt = "Taban (`V7_CONFIG`)"
            else:
                gr = stage3_gate_results.get(v, {})
                g_txt = "**GEÇTİ**" if gr.get("passed") else "KALDI"
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V7_BASE'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_txt} |"
            )

        if stage3_b_yearly_detail:
            lines += [
                "",
                "### Aşama B Yıllık Ayrıntı (5-Tohum + Sıcaklık Kalibrasyonu)",
                "",
                "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V7_BASE` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
                "|---:|---|---:|---:|---|---:|---:|---:|",
            ]
            for yr_row in stage3_b_yearly_detail:
                v = yr_row["variant"]
                lines.append(
                    f"| {yr_row['year']} | `{v}` | {yr_row['races']} | {yr_row['ll']:.4f} | "
                    f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'V7_BASE'))} | "
                    f"{yr_row['top1']:.2%} | {yr_row['top2']:.2%} | {yr_row['top3']:.2%} |"
                )

        if cal_param_rows:
            lines += [
                "",
                "### İleri-Yürüyen Sıcaklık Kalibrasyonu Katsayıları (`gamma = 1/T`, `< Y` Üzerinden)",
                "",
                "| Varyant | Test Yılı | Uydurma Yılları (`< Y`) | Uydurma Koşu | `gamma` (`T=1/gamma`) |",
                "|---|---:|---|---:|---:|",
            ]
            for cr in cal_param_rows:
                p_txt = f"{cr['param']:.4f} (T={1.0 / cr['param']:.4f})" if np.isfinite(cr["param"]) else "—"
                lines.append(
                    f"| `{cr['variant']}` | {cr['year']} | {cr['fit_years']} | {cr['fit_races']} | {p_txt} |"
                )

        lines.append("")
        if stage3_winner is not None:
            lines.append(f"**KAPI SONUCU:** `{stage3_winner}` Aşama B doğrulama kapısını **GEÇTİ**.")
        else:
            lines.append("**KAPI SONUCU:** Hiçbir V8 adayı Aşama B sabit kapısını geçemedi — **V7 korunur**.")

    lines += [
        "",
        "## 5. Aşama C — 2026 Bilgi Kümesi *(kilit v5'te tüketildi, temiz test DEĞİL)*",
        "",
        "> **Uyarı:** 2026 yılı v5'te tek seferlik kilit testi olarak tüketilmiştir; aşağıdaki değerler yalnız bilgi amaçlıdır ve seçimde kullanılmamıştır.",
        "",
    ]
    if smoke or not stage3_c_rows:
        lines.append("Bu koşuda 2026 bilgi kümesi hesaplanmadı.")
    else:
        base_c = "V7_BASE" if any(r["variant"] == "V7_BASE" for r in stage3_c_rows) else "V7_1s"
        lines += [
            f"| Varyant | Koşu | Log-Loss | ΔLL vs `{base_c}` (%95 GA) | ΔLL vs `AGF` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---|---|---|",
        ]
        for r in stage3_c_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == base_c))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )

    return "\n".join(lines).rstrip() + "\n"


def run_v8_experiments(
    db_path="data/ganyan.db",
    cache_dir="data/v8_cache",
    out_report="reports/V8.md",
    smoke=False,
):
    """Run staged Model v8 experiments (Packets A, K, N) and write `out_report`."""
    smoke = bool(smoke)
    os.makedirs(cache_dir, exist_ok=True)

    conn = _open_ro_db(db_path)
    try:
        runners_df = load_runners_from_db(conn)
        v5_tables = load_v5_tables(conn)
    finally:
        conn.close()

    if len(runners_df) == 0:
        raise ValueError("Veritabanında değerlendirilecek sonuçlanmış koşucu satırı bulunamadı.")

    runners_df["date"] = pd.to_datetime(runners_df["date"], errors="coerce")
    runners_df = runners_df[runners_df["date"].notna()].copy()
    runners_df = _drop_unfinished_races(runners_df)
    if len(runners_df) == 0:
        raise ValueError("Sonuçlanmış koşu süzgeci sonrası satır kalmadı.")

    db_min_date = runners_df["date"].min().strftime("%Y-%m-%d")
    db_max_date = runners_df["date"].max().strftime("%Y-%m-%d")
    raw_total_rows = int(len(runners_df))
    raw_total_races = int(runners_df["race_id"].nunique())

    if smoke:
        avail_years = sorted(int(y) for y in runners_df["date"].dt.year.unique())
        target_y = SMOKE_TEST_YEAR if SMOKE_TEST_YEAR in avail_years else avail_years[-1]
        t_feat0 = time.perf_counter()
        df_sm = _build_v8_history_frame(runners_df, v5_tables, max_date=f"{target_y}-12-31")
        print(f"[smoke] Özellik inşası tamamlandı ({time.perf_counter() - t_feat0:.1f}sn)", flush=True)

        eval_mask_sm = df_sm["_is_eval"]
        eval_y = df_sm[eval_mask_sm & (df_sm["_year"] == target_y)][
            ["race_id", "horse_key", "date", "_year", "win", "finish", "ganyan", "agf_close", "agf_share", "field"]
        ].copy().reset_index(drop=True)
        if len(eval_y) == 0:
            raise ValueError(f"Duman testi yılı ({target_y}) için değerlendirilebilir koşu bulunamadı.")

        feat_fill_rows, yearly_cov_rows = _compute_v8_coverage_tables(df_sm, eval_mask_sm, min_eval_year=target_y)
        for blk in ("A", "K", "N"):
            blk_nz = sum(fr["eval_nonzero"] for fr in feat_fill_rows if fr["block"] == blk)
            if blk_nz <= 0.0:
                raise RuntimeError(f"Smoke testinde Paket {blk} sıfır-dışı kapsamı 0!")

        smoke_extra = {"mode": "smoke_pct20"}
        tracker = _ProgressTracker(total_planned_steps=len(BASE_V8_SPECS))
        preds_sm = {}
        ll_base = None
        for v_name, blks, desc in BASE_V8_SPECS:
            cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc, extra_meta=smoke_extra)
            p_y, dt_s, from_c = _predict_base_year(df_sm, eval_y, cfg, target_y, cache_dir, smoke=True)
            if p_y is None or not np.all(np.isfinite(p_y)):
                raise RuntimeError(f"Smoke {v_name} tahmini geçersiz!")
            preds_sm[v_name] = p_y
            ll_y = _race_winner_lls(eval_y, p_y)
            if v_name == "V7_1s":
                ll_base = ll_y
                dll_val = 0.0
            else:
                dll_val = float((ll_y - ll_base).mean())
            tracker.log_step(v_name, target_y, dt_s, dll_val, from_cache=from_c)

        del df_sm
        gc.collect()

        stage1_rows, _ = _summarize_period_metrics(
            eval_y, preds_sm, [v[0] for v in BASE_V8_SPECS], base_key="V7_1s"
        )
        meta = {
            "db_path": str(db_path),
            "db_min_date": db_min_date,
            "db_max_date": db_max_date,
            "total_rows": raw_total_rows,
            "total_races": raw_total_races,
            "stage_a_races": int(eval_y["race_id"].nunique()),
            "stage_b_races": 0,
            "stage_c_races": 0,
        }
        report_md = format_v8_report(
            smoke=True,
            meta=meta,
            feat_fill_rows=feat_fill_rows,
            yearly_cov_rows=yearly_cov_rows,
            stage1_rows=stage1_rows,
            stage1_years=[target_y],
            selected_blocks=[],
            sel_ran=False,
            stage2_rows=[],
            stage2_years=[],
            stage3_selected=[],
            stage3_b_rows=[],
            stage3_b_yearly_detail=[],
            stage3_gate_results={},
            stage3_winner=None,
            stage3_c_rows=[],
            stage3_c_years=[],
            cal_param_rows=[],
        )
        out_dir = os.path.dirname(str(out_report))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_report, "w", encoding="utf-8") as f:
            f.write(report_md)
        print("SMOKE OK", flush=True)
        return {"smoke": True, "report_path": str(out_report), "stage1_rows": stage1_rows}

    t_f0 = time.perf_counter()
    print("[v8] Özellik matrisi kuruluyor (2006-03-04→)...", flush=True)
    df_hist = _build_v8_history_frame(runners_df, v5_tables)
    del runners_df, v5_tables
    gc.collect()
    print(
        f"[v8] Özellik matrisi hazır ({len(df_hist):,} satır, {len(df_hist.columns)} sütun, {time.perf_counter() - t_f0:.1f}sn)",
        flush=True,
    )

    eval_mask = df_hist["_is_eval"]
    eval_cols = ["race_id", "horse_key", "date", "_year", "win", "finish", "ganyan", "agf_close", "agf_share", "field"]
    eval_all_meta = df_hist.loc[eval_mask, eval_cols].copy().reset_index(drop=True)
    eval_years_set = {int(y) for y in eval_all_meta["_year"].unique()}

    stage_a_years = [int(y) for y in STAGE_A_YEARS if int(y) in eval_years_set]
    stage_b_years = [int(y) for y in STAGE_B_YEARS if int(y) in eval_years_set]
    stage_c_years = [int(y) for y in STAGE_C_YEARS if int(y) in eval_years_set]
    warmup_years = [CAL_WARMUP_YEAR] if CAL_WARMUP_YEAR in eval_years_set else []

    if not stage_a_years:
        raise ValueError("Aşama A (2017–2021) için değerlendirilebilir koşu bulunamadı.")

    eval_by_year = {
        int(y): eval_all_meta[eval_all_meta["_year"] == int(y)].copy().reset_index(drop=True)
        for y in sorted(eval_years_set)
    }
    feat_fill_rows, yearly_cov_rows = _compute_v8_coverage_tables(df_hist, eval_mask, min_eval_year=min(stage_a_years))

    est_steps = len(BASE_V8_SPECS) * (len(stage_a_years) + len(stage_b_years)) + 3 * (
        len(warmup_years) + len(stage_a_years) + len(stage_b_years) + len(stage_c_years)
    )
    tracker = _ProgressTracker(total_planned_steps=est_steps)

    preds_by_var_year = {}
    base_1s_ll_by_year = {}
    base_5s_ll_by_year = {}

    def _run_years(var_name, cfg_obj, years_list, ref_ll_map):
        preds_by_var_year.setdefault(var_name, {})
        for y in years_list:
            ev_y = eval_by_year.get(int(y))
            if ev_y is None or len(ev_y) == 0:
                continue
            p_y, dt_s, from_c = _predict_base_year(df_hist, ev_y, cfg_obj, y, cache_dir, smoke=False)
            if p_y is None:
                continue
            preds_by_var_year[var_name][int(y)] = p_y
            ll_y = _race_winner_lls(ev_y, p_y)
            if var_name in ("V7_1s", "V7_BASE_5s"):
                ref_ll_map[int(y)] = ll_y
                dll_val = 0.0
            elif int(y) in ref_ll_map:
                dll_val = float((ll_y - ref_ll_map[int(y)]).mean())
            else:
                dll_val = np.nan
            tracker.log_step(var_name, y, dt_s, dll_val, from_cache=from_c)

    # Stage 1: Fast 1-seed screening on Stage A (2017–2021)
    stage1_cfgs = {}
    stage1_order = []
    for v_name, blks, desc in BASE_V8_SPECS:
        cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc)
        stage1_cfgs[v_name] = cfg
        stage1_order.append(v_name)
        _run_years(v_name, cfg, stage_a_years, base_1s_ll_by_year)

    eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
    raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V7_1s")
    by_var_a = {r["variant"]: r for r in raw_a_rows}

    selected_blocks = []
    for blk in ("A", "K", "N"):
        v_blk = f"V8_{blk}"
        if v_blk in by_var_a and by_var_a[v_blk]["dll_e0"] < SEL_THRESHOLD_DLL:
            selected_blocks.append(blk)

    sel_ran = len(selected_blocks) == 2
    if sel_ran:
        sel_desc = f"V7 + seçili paketler ({'+'.join(selected_blocks)})"
        cfg_sel = _make_variant_cfg("V8_SEL", tuple(selected_blocks), seeds=(0,), description=sel_desc)
        stage1_cfgs["V8_SEL"] = cfg_sel
        stage1_order.append("V8_SEL")
        _run_years("V8_SEL", cfg_sel, stage_a_years, base_1s_ll_by_year)
        eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
        raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V7_1s")
        by_var_a = {r["variant"]: r for r in raw_a_rows}

    stage1_rows = []
    for fixed_k in ("B0", "V7_1s"):
        if fixed_k in by_var_a:
            stage1_rows.append(by_var_a[fixed_k])
    cand_a_rows = [by_var_a[v] for v in stage1_order if v != "V7_1s" and v in by_var_a]
    cand_a_rows.sort(key=lambda r: (r["dll_e0"], stage1_order.index(r["variant"])))
    stage1_rows.extend(cand_a_rows)

    # Stage 2: Diagnostic 1-seed check on Stage B (2022–2025)
    stage2_rows = []
    if stage_b_years:
        for v_name in stage1_order:
            _run_years(v_name, stage1_cfgs[v_name], stage_b_years, base_1s_ll_by_year)
        eval_b_1s, preds_b_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, stage1_order)
        raw_b_1s, _ = _summarize_period_metrics(eval_b_1s, preds_b_1s, stage1_order, base_key="V7_1s")
        by_var_b1s = {r["variant"]: r for r in raw_b_1s}
        for fixed_k in ("B0", "V7_1s"):
            if fixed_k in by_var_b1s:
                stage2_rows.append(by_var_b1s[fixed_k])
        cand_b1s = [by_var_b1s[v] for v in stage1_order if v != "V7_1s" and v in by_var_b1s]
        cand_b1s.sort(key=lambda r: (r["dll_e0"], stage1_order.index(r["variant"])))
        stage2_rows.extend(cand_b1s)

    # Stage 3: Strict selection from Stage A -> 5-seed + temperature calibration -> Official Stage B Gate
    eligible_stage_a = [r for r in cand_a_rows if r["dll_e0"] < 0.0]
    stage3_selected = []
    if eligible_stage_a:
        stage3_selected.append(eligible_stage_a[0]["variant"])
        for extra_v in ("V8_AKN", "V8_SEL"):
            if len(stage3_selected) >= 3:
                break
            if any(r["variant"] == extra_v for r in eligible_stage_a) and extra_v not in stage3_selected:
                stage3_selected.append(extra_v)

    all_cal_years = sorted(set(warmup_years + stage_a_years + stage_b_years + stage_c_years))
    cal_eval_years = sorted(set(stage_a_years + stage_b_years + stage_c_years))
    stage3_b_rows = []
    stage3_b_yearly_detail = []
    stage3_gate_results = {}
    stage3_winner = None
    stage3_c_rows = []
    cal_param_rows = []

    if stage3_selected:
        seeds_5 = tuple(int(s) for s in V7_CONFIG["seeds"])
        stage3_specs = [("V7_BASE", (), "Resmi V7 tabanı (5 tohum + sıcaklık)")]
        for cand_name in stage3_selected:
            blks = tuple(stage1_cfgs[cand_name]["v8_blocks"])
            stage3_specs.append((cand_name, blks, f"{cand_name} (5 tohum + sıcaklık)"))

        cal_names = []
        for s3_name, blks, desc in stage3_specs:
            raw_5s_name = f"{s3_name}_5s"
            cal_name = "V7_BASE" if s3_name == "V7_BASE" else f"{s3_name}_CAL"
            cal_names.append(cal_name)

            cfg_5s = _make_variant_cfg(raw_5s_name, blks, seeds=seeds_5, description=desc)
            _run_years(raw_5s_name, cfg_5s, all_cal_years, base_5s_ll_by_year)

            cfg_cal = _make_variant_cfg(
                cal_name,
                blks,
                seeds=seeds_5,
                calibration="temperature",
                calibrated_from=raw_5s_name,
                description=desc,
            )
            preds_by_var_year[cal_name] = {}
            for y in cal_eval_years:
                ev_y = eval_by_year.get(int(y))
                if ev_y is None or len(ev_y) == 0:
                    continue
                p_c, dt_s, from_c, c_meta = _predict_calibrated_year(
                    eval_by_year,
                    preds_by_var_year[raw_5s_name],
                    cfg_cal,
                    y,
                    cache_dir,
                    smoke=False,
                )
                if p_c is None:
                    continue
                preds_by_var_year[cal_name][int(y)] = p_c
                if c_meta is not None:
                    cal_param_rows.append(c_meta)
                ll_y = _race_winner_lls(ev_y, p_c)
                if cal_name == "V7_BASE":
                    base_5s_ll_by_year[f"cal_{y}"] = ll_y
                    dll_val = 0.0
                elif f"cal_{y}" in base_5s_ll_by_year:
                    dll_val = float((ll_y - base_5s_ll_by_year[f"cal_{y}"]).mean())
                else:
                    dll_val = np.nan
                tracker.log_step(cal_name, y, dt_s, dll_val, from_cache=from_c)

        if stage_b_years:
            eval_b_5s, preds_b_5s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, cal_names)
            stage3_b_rows, race_dll_b = _summarize_period_metrics(eval_b_5s, preds_b_5s, cal_names, base_key="V7_BASE")

            for y_b in stage_b_years:
                ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], cal_names)
                yr_rows_b, _ = _summarize_period_metrics(ev_yb, pr_yb, cal_names, base_key="V7_BASE")
                for r_yb in yr_rows_b:
                    r_yb["year"] = int(y_b)
                    stage3_b_yearly_detail.append(r_yb)

            by_var_b3 = {r["variant"]: r for r in stage3_b_rows}
            passed = []
            for cn in cal_names:
                if cn == "V7_BASE" or cn not in by_var_b3:
                    continue
                r_b = by_var_b3[cn]
                g_res = evaluate_stage_b_gate(
                    r_b["yearly_dll"],
                    race_dll_b[cn],
                    n_boot=2000,
                    seed=0,
                    min_neg_years=3,
                )
                stage3_gate_results[cn] = g_res
                if g_res["passed"]:
                    passed.append(cn)
            if passed:
                passed.sort(key=lambda v: by_var_b3[v]["dll_e0"])
                stage3_winner = passed[0]

        if stage_c_years:
            eval_c_5s, preds_c_5s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, cal_names)
            stage3_c_rows, _ = _summarize_period_metrics(eval_c_5s, preds_c_5s, cal_names, base_key="V7_BASE")
    else:
        if stage_c_years:
            for v_name in stage1_order:
                _run_years(v_name, stage1_cfgs[v_name], stage_c_years, base_1s_ll_by_year)
            eval_c_1s, preds_c_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, stage1_order)
            stage3_c_rows, _ = _summarize_period_metrics(eval_c_1s, preds_c_1s, stage1_order, base_key="V7_1s")

    meta = {
        "db_path": str(db_path),
        "db_min_date": db_min_date,
        "db_max_date": db_max_date,
        "total_rows": raw_total_rows,
        "total_races": raw_total_races,
        "stage_a_races": sum(int(eval_by_year[y]["race_id"].nunique()) for y in stage_a_years),
        "stage_b_races": sum(int(eval_by_year[y]["race_id"].nunique()) for y in stage_b_years),
        "stage_c_races": sum(int(eval_by_year[y]["race_id"].nunique()) for y in stage_c_years),
    }

    report_md = format_v8_report(
        smoke=False,
        meta=meta,
        feat_fill_rows=feat_fill_rows,
        yearly_cov_rows=yearly_cov_rows,
        stage1_rows=stage1_rows,
        stage1_years=stage_a_years,
        selected_blocks=selected_blocks,
        sel_ran=sel_ran,
        stage2_rows=stage2_rows,
        stage2_years=stage_b_years,
        stage3_selected=stage3_selected,
        stage3_b_rows=stage3_b_rows,
        stage3_b_yearly_detail=stage3_b_yearly_detail,
        stage3_gate_results=stage3_gate_results,
        stage3_winner=stage3_winner,
        stage3_c_rows=stage3_c_rows,
        stage3_c_years=stage_c_years,
        cal_param_rows=cal_param_rows,
    )

    out_dir = os.path.dirname(str(out_report))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_report, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"[v8] Rapor yazıldı: {out_report}", flush=True)
    return {
        "smoke": False,
        "report_path": str(out_report),
        "stage1_rows": stage1_rows,
        "stage2_rows": stage2_rows,
        "stage3_selected": stage3_selected,
        "stage3_winner": stage3_winner,
        "stage3_gate_results": stage3_gate_results,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v8 ileri-yürüyen deney serisi (Paket A, K, N -> Aşama A/B/C)."
    )
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--cache-dir", default="data/v8_cache")
    ap.add_argument("--out-report", default="reports/V8.md")
    ap.add_argument("--smoke", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        run_v8_experiments(
            db_path=args.db,
            cache_dir=args.cache_dir,
            out_report=args.out_report,
            smoke=args.smoke,
        )
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
