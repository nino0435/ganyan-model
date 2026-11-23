"""Walk-forward experimentation, Stage A/B/C gating, and report generator for Model v9."""
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
from ganyan.features_v8 import attach_v8
from ganyan.features_v9 import (
    SMOOTHING_CONSTANTS,
    V9_BLOCK_COLS,
    V9_CANDIDATE_BLOCKS,
    attach_BIAS,
    attach_DAY,
    attach_KEY,
    attach_SHIP,
    attach_STAB,
    attach_WORK,
    attach_v9,
    compute_work_jockey_stats_by_source_year,
    get_v9_cols,
)
from ganyan.model_v6 import (
    STAGE_A_YEARS,
    STAGE_B_YEARS,
    STAGE_C_YEARS,
    evaluate_stage_b_gate,
)
from ganyan.model_v8 import V8_CONFIG
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

BASE_V9_SPECS = [
    ("V8_1s", (), "V8 tabanı (v8_an özellikleri, 122 özellik, 1 tohum)"),
    ("V9_KEY", ("KEY",), "V8 + KEY (anahtar yarış rakiplerinin sonraki başarısı, 6 özellik)"),
    ("V9_SHIP", ("SHIP",), "V8 + SHIP (antrenör ev şehri, deplasman ve at ilk şehir startı, 4 özellik)"),
    ("V9_STAB", ("STAB",), "V8 + STAB (antrenör 14g/28g AGF fazlası ahır dalgası, 5 özellik)"),
    ("V9_WORK", ("WORK",), "V8 + WORK (galop binicisi uyumu ve sert idman tazeliği, 4 özellik)"),
    ("V9_BIAS", ("BIAS",), "V8 + BIAS (3 yıllık şehir+pist+mesafe+kulvar eğilimi, 2 özellik)"),
    ("V9_ALL", list(V9_CANDIDATE_BLOCKS), "V8 + 5 aday paket birlikte (KEY+SHIP+STAB+WORK+BIAS, 21 yeni özellik)"),
    ("V9_DAY", ("DAY",), "TANISAL: V8 + DAY (gün içi önceki koşuların kulvar eğilimi — adaya girmez)"),
]

SEL_THRESHOLD_DLL = -0.0002
LIVE_BASELINE_S = 175.0  # ~2 dk 55 sn aktif 3 canlı model bütçesi
LIVE_BUDGET_EXTRA_S = 30.0


def _make_variant_cfg(
    name,
    v9_blocks,
    seeds=(0,),
    calibration=None,
    calibrated_from=None,
    description="",
    extra_meta=None,
):
    cfg = {
        "variant": str(name),
        "family": "V9" if v9_blocks else "V8",
        "description": str(description),
        "history_start": str(V8_CONFIG["history_start"]),
        "history_start_year": int(V8_CONFIG["history_start_year"]),
        "train_start_year": int(V8_CONFIG["train_start_year"]),
        "require_agf": bool(V8_CONFIG["require_agf"]),
        "v7_blocks": list(V8_CONFIG["v7_blocks"]),
        "v8_blocks": list(V8_CONFIG["v8_blocks"]),
        "v9_blocks": list(v9_blocks),
        "feature_cols": get_v9_cols(v9_blocks=v9_blocks, with_program=False),
        "hgb_params": dict(V8_CONFIG["hgb_params"]),
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


def _attach_v9_timed(df_base, v5_tables, blocks=tuple(V9_BLOCK_COLS)):
    """Attach V9 blocks cleanly while timing each block individually."""
    out = df_base.copy()
    block_times = {}
    fn_map = {
        "KEY": attach_KEY,
        "SHIP": attach_SHIP,
        "STAB": attach_STAB,
        "WORK": lambda d: attach_WORK(d, v5_tables=v5_tables),
        "BIAS": attach_BIAS,
        "DAY": attach_DAY,
    }
    for blk in blocks:
        t0 = time.perf_counter()
        out = fn_map[blk](out)
        block_times[blk] = time.perf_counter() - t0
    cand_s = sum(block_times.get(b, 0.0) for b in V9_CANDIDATE_BLOCKS)
    all_s = sum(block_times.values())
    return out, {"blocks": block_times, "candidates_total_s": cand_s, "all_total_s": all_s}


def _build_v9_history_frame(runners_df, v5_tables, max_date=None):
    """Build single leak-free feature DataFrame (`2006-03-04`->) with V5 + V7 + V8 + V9 attached."""
    start_ts = pd.Timestamp(V8_CONFIG["history_start"])
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
    v5_sub = {"ext": v5_tables["ext"], "workouts": w_sub}

    df = build_features(r_sub, ref_end=REF_END_DEFAULT)
    del r_sub
    df = attach_v5(df, v5_sub, blocks=("S", "G", "R"))
    df = attach_v7(df, blocks=tuple(V8_CONFIG["v7_blocks"]))
    df = attach_v8(df, blocks=tuple(V8_CONFIG["v8_blocks"]))
    df, v9_timing = _attach_v9_timed(df, v5_sub, blocks=tuple(V9_BLOCK_COLS))
    df["_year"] = df["date"].dt.year.astype(np.int32)
    df["_has_race_win"] = df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    df["_is_eval"] = _eval_filter_mask(df)
    return df, v9_timing, v5_sub


def _measure_single_day_timing(df_hist, v5_sub, target_date_str):
    """Measure isolated attach_v9 overhead on a single target day's runners and full history slice."""
    target_ts = pd.Timestamp(target_date_str)
    day_only = df_hist[df_hist["date"] == target_ts][
        [c for c in df_hist.columns if not any(c in V9_BLOCK_COLS[b] for b in V9_BLOCK_COLS)]
    ].copy()
    w_df = v5_sub["workouts"]
    w_before = w_df[w_df["date"] < target_ts].copy() if len(w_df) > 0 else w_df
    t0 = time.perf_counter()
    _ = attach_v9(day_only, blocks=V9_CANDIDATE_BLOCKS, v5_tables={"ext": v5_sub["ext"], "workouts": w_before})
    day_only_s = time.perf_counter() - t0
    return {
        "target_date": str(target_date_str),
        "target_races": int(day_only["race_id"].nunique()),
        "target_runners": int(len(day_only)),
        "day_slice_attach_s": float(day_only_s),
    }


def _compute_v9_coverage_tables(df_hist, eval_mask, min_eval_year=2017):
    """Compute per-feature fill rates and yearly (`2015–2026`) packet coverage summaries."""
    eval_target = eval_mask & (df_hist["_year"] >= int(min_eval_year))
    feat_rows = []
    for blk, cols in V9_BLOCK_COLS.items():
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
            "key_fill": float(grp["key_wr"].notna().mean()),
            "ship_away": float((grp["trn_away"].notna() & (grp["trn_away"] > 0)).mean()),
            "stab_fill": float(grp["trn_resid_28d"].notna().mean()),
            "work_match": float((grp["gw_jk_last"].notna() & (grp["gw_jk_last"] > 0)).mean()),
            "work_known": float(grp["gw_jk_last"].notna().mean()),
            "bias_fill": float(grp["bias_gate_resid"].notna().mean()),
            "day_fill": float(grp["day_gate_bias"].notna().mean()),
        })
    return feat_rows, yearly_rows


def format_v9_report(
    *,
    smoke,
    meta,
    timing_hist,
    timing_day,
    feat_fill_rows,
    yearly_cov_rows,
    work_src_year_rows,
    work_runner_rows,
    stage1_rows,
    stage1_years,
    selected_blocks,
    sel_note,
    stage3_candidate,
    stage2_rows,
    stage2_years,
    stage3_b_rows,
    stage3_b_yearly_detail,
    stage3_gate_result,
    stage3_passed,
    stage3_c_rows,
    cal_param_rows,
):
    title = (
        "# Ganyan Model v9 — Duman Testi Raporu (--smoke)"
        if smoke
        else "# Ganyan Model v9 — Paket Deneyleri (KEY, SHIP, STAB, WORK, BIAS; Tanı DAY) ve Kapı Sonucu"
    )
    cand_s = float(timing_hist.get("candidates_total_s", 0.0))
    all_s = float(timing_hist.get("all_total_s", 0.0))
    day_s = float(timing_day.get("day_slice_attach_s", 0.0))
    over_budget = cand_s > LIVE_BUDGET_EXTRA_S
    budget_note = (
        f"**UYARI:** Tam geçmiş `attach_v9` ({cand_s:.1f} sn), 30 sn ek canlı bütçesini aşıyor "
        f"(mevcut 3 canlı model toplamı ~{LIVE_BASELINE_S:.0f} sn = 2 dk 55 sn)."
        if over_budget
        else f"Tam geçmiş `attach_v9` ({cand_s:.1f} sn), 30 sn ek canlı bütçesi **içindedir** "
        f"(mevcut 3 canlı model toplamı ~{LIVE_BASELINE_S:.0f} sn = 2 dk 55 sn)."
    )

    lines = [
        title,
        "",
        "> **Uyarı 1 (Kapanış AGF):** Tarihsel değerlendirmede kapanış AGF (`agf_close`) kullanılır; canlıda koşudan önce alınan AGF daha az bilgi içerir.",
        "> **Uyarı 2 (Seçim Protokolü):** Aday seçimi yalnız Aşama A (`2017–2021`) üzerinde sabit `-0.0002` eşiğiyle yapılmıştır; Aşama B kapısına **tek** aday taşınmıştır.",
        "",
        "## 1. Veri, Süre, Sabitler ve Kapsam Özeti",
        "",
        f"- **Veritabanı:** `{meta['db_path']}` (salt-okunur)",
        f"- **Veri Aralığı (DB):** `{meta['db_min_date']}` … `{meta['db_max_date']}`",
        f"- **Toplam Sonuçlanmış Koşucu / Koşu:** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Taban Model (`V8_CONFIG`):** `V8_SEL_CAL` (`122` özellik, `min_samples_leaf=400`, `l2=15.0`, `lr=0.03`, `max_iter=420`, `leaf=23`)",
        f"- **Değerlendirme Koşu Sayıları:** Aşama A `{meta['stage_a_races']:,}` | Aşama B `{meta['stage_b_races']:,}` | Aşama C (2026 bilgi) `{meta['stage_c_races']:,}`",
        "",
        "### Süre Ölçümleri ve Canlı Bütçe Değerlendirmesi",
        "",
        f"- **`attach_v9` Tüm Geçmiş Süresi (`2006-03-04`→):** 5 aday paket toplamı **`{cand_s:.2f}` sn**, `DAY` dahil 6 paket toplamı **`{all_s:.2f}` sn**",
        "  - Paket kırılımı: "
        + ", ".join(f"`{k}`: {v:.2f} sn" for k, v in timing_hist.get("blocks", {}).items()),
        f"- **Tek Günlük Program İzole Dilim (`{timing_day['target_date']}`, {timing_day['target_races']} koşu / {timing_day['target_runners']} koşucu):** `{day_s:.3f}` sn (not: canlı hat geçmiş pencereler için `2006→bugün` matrisi üzerinde çalışır; gerçek canlı ek yük tam geçmiş `attach_v9` süresine yakın olur)",
        f"- **Canlı Bütçe Durumu:** {budget_note}",
        "",
        "### Seçilen Yumuşatma ve Pencere Sabitleri",
        "",
        "| Sabit | Değer | Açıklama |",
        "|---|---:|---|",
        f"| `KEY_PRIOR_W` / `KEY_PRIOR_N` | `{SMOOTHING_CONSTANTS['KEY_PRIOR_W']}` / `{SMOOTHING_CONSTANTS['KEY_PRIOR_N']}` | Anahtar yarış galibiyet oranı Bayes yumuşatması `(won + 0.5) / (ran + 3)` |",
        f"| `SHIP_HOME_MIN_STARTS` | `{SMOOTHING_CONSTANTS['SHIP_HOME_MIN_STARTS']}` | Ev şehri tanımlamak için son 365 gündeki en az start sayısı |",
        f"| `SHIP_AWAY_PRIOR_N` | `{SMOOTHING_CONSTANTS['SHIP_AWAY_PRIOR_N']}` | 730g deplasman AGF fazlası yumuşatma paydası `(n + 20)` |",
        f"| `STAB_PRIOR_14` / `STAB_PRIOR_28` | `{SMOOTHING_CONSTANTS['STAB_PRIOR_14']}` / `{SMOOTHING_CONSTANTS['STAB_PRIOR_28']}` | Ahır 14g `(n + 10)` ve 28g `(n + 15)` AGF fazlası yumuşatması |",
        f"| `BIAS_WINDOW_DAYS` / `BIAS_PRIOR_N` | `{SMOOTHING_CONSTANTS['BIAS_WINDOW_DAYS']}` / `{SMOOTHING_CONSTANTS['BIAS_PRIOR_N']}` | Kulvar eğilimi 3 yıl (1095 gün) penceresi ve `(n + 100)` yumuşatması |",
        f"| `DAY_PRIOR_N` | `{SMOOTHING_CONSTANTS['DAY_PRIOR_N']}` | Gün içi önceki koşular tanısal kulvar eğilimi yumuşatması `(n + 2)` |",
        "",
    ]

    if yearly_cov_rows:
        lines += [
            "### Yıllık V9 Paket Sinyal ve Doluluk Oranları (`2015–2026`)",
            "",
            "| Yıl | Koşu | Koşucu | `key_wr` Dolu | `trn_away>0` | `trn_resid_28d` | `gw_jk_last` Dolu | `gw_jk_last=1` | `bias_gate` Dolu | `day_bias` Dolu |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for yr in yearly_cov_rows:
            lines.append(
                f"| {yr['year']} | {yr['races']:,} | {yr['runners']:,} | "
                f"{yr['key_fill']:.1%} | {yr['ship_away']:.1%} | {yr['stab_fill']:.1%} | "
                f"{yr['work_known']:.1%} | {yr['work_match']:.1%} | {yr['bias_fill']:.1%} | {yr['day_fill']:.1%} |"
            )

    if feat_fill_rows:
        lines += [
            "",
            "### V9 Özellik Doluluk Özeti (`2017+` Değerlendirme Kümesi)",
            "",
            "| Paket | Sütun | Tüm Veri Dolu (%) | Değerlendirme Dolu (%) | Değerlendirme Sıfır-Dışı (%) |",
            "|---|---|---:|---:|---:|",
        ]
        for fr in feat_fill_rows:
            lines.append(
                f"| `{fr['block']}` | `{fr['col']}` | {fr['all_fill']:.1%} | {fr['eval_fill']:.1%} | {fr['eval_nonzero']:.1%} |"
            )

    if work_src_year_rows or work_runner_rows:
        lines += [
            "",
            "### `WORK` Kaynak × Yıl Binici Doluluk ve Eşleşme Oranları (`2017+`)",
            "",
            "> **Veri Notu:** Liderform son verisi **18 Kas 2026** olup canlı hat galopu **Yenibeygir**'den çekmektedir (`--galop-source yenibeygir`). Yenibeygir galop kayıtlarında binici alanı yaklaşık **%18–21 boştur** (`jockey IS NULL`), dolu olduğunda ise tam ad formatıyla geldiği için TJK yarış binicileriyle ad-soyad eşleştirmesi yüksek doğrulukla çalışmaktadır.",
            "",
            "#### Tekil Galop Satırlarında Binici Bilgisi (Kaynak × Yıl)",
            "",
            "| Kaynak | Yıl | Galop Satırı | Bilinen Binici (%) | Genel `APRANTİ` (%) | Boş/Null (%) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for wr in work_src_year_rows:
            lines.append(
                f"| `{wr['source']}` | {wr['year']} | {wr['rows']:,} | "
                f"{wr['known_pct']:.1%} | {wr['apranti_pct']:.1%} | {wr['missing_pct']:.1%} |"
            )
        if work_runner_rows:
            lines += [
                "",
                "#### Koşucu Düzeyinde Son 30g Galop → Yarış Jokeyi Eşleşme Oranı (Kaynak × Yıl)",
                "",
                "| Kaynak | Yıl | Son 30g Galoplu Koşucu | Bilinen Binici (%) | Tüm Koşucuda Eşleşme (%) | Bilinen İçinde Eşleşme (%) |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for rr in work_runner_rows:
                lines.append(
                    f"| `{rr['source']}` | {rr['year']} | {rr['runners_30d']:,} | "
                    f"{rr['known_jockey_pct']:.1%} | {rr['match_all_pct']:.1%} | {rr['match_known_pct']:.1%} |"
                )

    a_lbl = f"{min(stage1_years)}–{max(stage1_years)}" if stage1_years else "—"
    lines += [
        "",
        f"## 2. Aşama A Tarama Sonuçları (`{a_lbl}`, 1-Tohum `seed=0`)",
        "",
        f"- **Otomatik Seçim Kuralı (`SEL_THRESHOLD_DLL = {SEL_THRESHOLD_DLL:+.4f}`):** Eşiği geçen paketler: "
        + (", ".join(f"`{b}`" for b in selected_blocks) if selected_blocks else "**yok**")
        + f" ({sel_note})",
        f"- **Aşama B'ye Seçilen Tek Aday:** `{stage3_candidate}`" if stage3_candidate else "- **Aşama B'ye Seçilen Tek Aday:** Yok (**V8 korunur**)",
        "",
        "| Varyant | Koşu | Log-Loss | ΔLL vs `V8_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    for r in stage1_rows:
        v = r["variant"]
        lines.append(
            f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V8_1s'))} | "
            f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
        )
    lines.extend(_format_yearly_dll_matrix(stage1_rows, stage1_years, "V8_1s", "Aşama A Yıllık ΔLL(varyant − V8_1s)"))

    lines += [
        "",
        "## 3. Aşama 2 — Tanısal Karşılaştırma (`2022–2025`, 1-Tohum `seed=0`, `V9_DAY` Dahil)",
        "",
        "> **Not:** Bu tablo örnek-dışı davranış ve tanısal `V9_DAY` kıyaslaması içindir; aday seçimi Aşama A'da dondurulmuştur.",
        "",
    ]
    if smoke or not stage2_rows:
        lines.append("Duman testinde Aşama 2 tanısal tablosu hesaplanmadı.")
    else:
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V8_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|",
        ]
        for r in stage2_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V8_1s'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )
        lines.extend(_format_yearly_dll_matrix(stage2_rows, stage2_years, "V8_1s", "Aşama 2 Tanısal Yıllık ΔLL(varyant − V8_1s)"))

    lines += [
        "",
        "## 4. Aşama 3 — Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)",
        "",
        "- **Kapı Kuralı (`evaluate_stage_b_gate`):** `ΔLL(aday − V8_BASE)` için koşu-eşli bootstrap %95 GA üst sınırı `< 0` **VE** `4` yılın en az `3`'ünde `ΔLL < 0`.",
        "",
    ]
    if smoke:
        lines.append("Duman testinde Aşama 3 tam kapı koşusu çalıştırılmadı.")
    elif stage3_candidate is None:
        lines.append(
            f"**KAPI SONUCU:** Aşama A (`2017–2021`) taramasında hiçbir tekil V9 paketi `{SEL_THRESHOLD_DLL:+.4f}` eşiğini geçemediğinden Aşama 3 çalıştırılmadı — **V8 korunur**."
        )
    else:
        lines.append(f"- **Sınanan Tek Aday (`Aşama A` kazananı):** `{stage3_candidate}`")
        lines.append("")
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V8_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı Kararı |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for r in stage3_b_rows:
            v = r["variant"]
            if v == "B0":
                g_txt = "Referans (Saf AGF)"
            elif v == "V8_BASE":
                g_txt = "Taban (`V8_CONFIG`)"
            else:
                g_txt = "**GEÇTİ**" if stage3_passed else "**KALDI**"
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V8_BASE'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_txt} |"
            )

        if stage3_b_yearly_detail:
            lines += [
                "",
                "### Aşama B Yıllık Ayrıntı (5-Tohum + Sıcaklık Kalibrasyonu)",
                "",
                "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V8_BASE` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
                "|---:|---|---:|---:|---|---:|---:|---:|",
            ]
            for yr_row in stage3_b_yearly_detail:
                v = yr_row["variant"]
                lines.append(
                    f"| {yr_row['year']} | `{v}` | {yr_row['races']} | {yr_row['ll']:.4f} | "
                    f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'V8_BASE'))} | "
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
        if stage3_passed:
            lines.append(f"**KAPI SONUCU:** `{stage3_candidate}_CAL` Aşama B doğrulama kapısını **GEÇTİ**.")
        else:
            lines.append(f"**KAPI SONUCU:** `{stage3_candidate}_CAL` Aşama B sabit kapısını geçemedi — **V8 korunur**.")

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
        base_c = "V8_BASE" if any(r["variant"] == "V8_BASE" for r in stage3_c_rows) else "V8_1s"
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


def run_v9_experiments(
    db_path="data/ganyan.db",
    cache_dir="data/v9_cache",
    out_report="reports/V9.md",
    smoke=False,
):
    """Run staged Model v9 experiments (KEY, SHIP, STAB, WORK, BIAS + diagnostic DAY)."""
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
        df_sm, v9_timing_sm, v5_sub_sm = _build_v9_history_frame(
            runners_df, v5_tables, max_date=f"{target_y}-12-31"
        )
        print(
            f"[smoke] Özellik inşası tamamlandı (toplam={time.perf_counter() - t_feat0:.1f}sn, "
            f"attach_v9_aday={v9_timing_sm['candidates_total_s']:.2f}sn)",
            flush=True,
        )
        sm_max_day = df_sm["date"].max().strftime("%Y-%m-%d")
        timing_day_sm = _measure_single_day_timing(df_sm, v5_sub_sm, sm_max_day)

        eval_mask_sm = df_sm["_is_eval"]
        eval_y = df_sm[eval_mask_sm & (df_sm["_year"] == target_y)][
            ["race_id", "horse_key", "date", "_year", "win", "finish", "ganyan", "agf_close", "agf_share", "field"]
        ].copy().reset_index(drop=True)
        if len(eval_y) == 0:
            raise ValueError(f"Duman testi yılı ({target_y}) için değerlendirilebilir koşu bulunamadı.")

        feat_fill_rows, yearly_cov_rows = _compute_v9_coverage_tables(df_sm, eval_mask_sm, min_eval_year=target_y)
        work_src_rows, work_run_rows = compute_work_jockey_stats_by_source_year(df_sm, v5_sub_sm)
        for blk in V9_BLOCK_COLS:
            blk_nz = sum(fr["eval_nonzero"] for fr in feat_fill_rows if fr["block"] == blk)
            if blk_nz <= 0.0:
                raise RuntimeError(f"Smoke testinde Paket {blk} sıfır-dışı kapsamı 0!")

        smoke_extra = {"mode": "smoke_pct20"}
        tracker = _ProgressTracker(total_planned_steps=len(BASE_V9_SPECS))
        preds_sm = {}
        ll_base = None
        for v_name, blks, desc in BASE_V9_SPECS:
            cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc, extra_meta=smoke_extra)
            p_y, dt_s, from_c = _predict_base_year(df_sm, eval_y, cfg, target_y, cache_dir, smoke=True)
            if p_y is None or not np.all(np.isfinite(p_y)):
                raise RuntimeError(f"Smoke {v_name} tahmini geçersiz!")
            preds_sm[v_name] = p_y
            ll_y = _race_winner_lls(eval_y, p_y)
            if v_name == "V8_1s":
                ll_base = ll_y
                dll_val = 0.0
            else:
                dll_val = float((ll_y - ll_base).mean())
            tracker.log_step(v_name, target_y, dt_s, dll_val, from_cache=from_c)

        del df_sm
        gc.collect()

        stage1_rows, _ = _summarize_period_metrics(
            eval_y, preds_sm, [v[0] for v in BASE_V9_SPECS], base_key="V8_1s"
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
        report_md = format_v9_report(
            smoke=True,
            meta=meta,
            timing_hist=v9_timing_sm,
            timing_day=timing_day_sm,
            feat_fill_rows=feat_fill_rows,
            yearly_cov_rows=yearly_cov_rows,
            work_src_year_rows=work_src_rows,
            work_runner_rows=work_run_rows,
            stage1_rows=stage1_rows,
            stage1_years=[target_y],
            selected_blocks=[],
            sel_note="duman testi — tam seçim çalıştırılmadı",
            stage3_candidate=None,
            stage2_rows=[],
            stage2_years=[],
            stage3_b_rows=[],
            stage3_b_yearly_detail=[],
            stage3_gate_result=None,
            stage3_passed=False,
            stage3_c_rows=[],
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
    print("[v9] Özellik matrisi kuruluyor (2006-03-04→)...", flush=True)
    df_hist, v9_timing_hist, v5_sub = _build_v9_history_frame(runners_df, v5_tables)
    del runners_df, v5_tables
    gc.collect()
    timing_day = _measure_single_day_timing(df_hist, v5_sub, db_max_date)
    work_src_rows, work_run_rows = compute_work_jockey_stats_by_source_year(df_hist, v5_sub)
    del v5_sub
    gc.collect()
    print(
        f"[v9] Özellik matrisi hazır ({len(df_hist):,} satır, {len(df_hist.columns)} sütun, "
        f"toplam={time.perf_counter() - t_f0:.1f}sn, attach_v9_aday={v9_timing_hist['candidates_total_s']:.2f}sn)",
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
    feat_fill_rows, yearly_cov_rows = _compute_v9_coverage_tables(df_hist, eval_mask, min_eval_year=min(stage_a_years))

    est_steps = len(BASE_V9_SPECS) * (len(stage_a_years) + len(stage_b_years)) + 2 * (
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
            if var_name in ("V8_1s", "V8_BASE_5s"):
                ref_ll_map[int(y)] = ll_y
                dll_val = 0.0
            elif int(y) in ref_ll_map:
                dll_val = float((ll_y - ref_ll_map[int(y)]).mean())
            else:
                dll_val = np.nan
            tracker.log_step(var_name, y, dt_s, dll_val, from_cache=from_c)

    # Stage 1 (Aşama A): Fast 1-seed screening on 2017–2021
    stage1_cfgs = {}
    stage1_order = []
    for v_name, blks, desc in BASE_V9_SPECS:
        cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc)
        stage1_cfgs[v_name] = cfg
        stage1_order.append(v_name)
        _run_years(v_name, cfg, stage_a_years, base_1s_ll_by_year)

    eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
    raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V8_1s")
    by_var_a = {r["variant"]: r for r in raw_a_rows}

    selected_blocks = [
        blk
        for blk in V9_CANDIDATE_BLOCKS
        if f"V9_{blk}" in by_var_a and by_var_a[f"V9_{blk}"]["dll_e0"] < SEL_THRESHOLD_DLL
    ]

    # Build/alias V9_SEL & pick AT MOST ONE candidate between V9_SEL and V9_ALL for Stage B
    stage3_candidate = None
    sel_run_distinct = False
    if not selected_blocks:
        sel_note = "`V9_SEL` oluşturulmadı — hiçbir tekil paket eşiği geçemedi (**V8 korunur**)"
    elif len(selected_blocks) == 1:
        only_name = f"V9_{selected_blocks[0]}"
        sel_note = f"`V9_SEL`, tek geçen `{only_name}` ile özdeştir"
        ll_sel = by_var_a[only_name]["ll"]
        ll_all = by_var_a["V9_ALL"]["ll"]
        stage3_candidate = only_name if ll_sel <= ll_all else "V9_ALL"
    elif tuple(selected_blocks) == V9_CANDIDATE_BLOCKS:
        sel_note = "`V9_SEL`, 5 paketin tümünü içeren `V9_ALL` ile özdeştir"
        stage3_candidate = "V9_ALL"
    else:
        sel_run_distinct = True
        sel_desc = f"V8 + seçili paketler ({'+'.join(selected_blocks)})"
        cfg_sel = _make_variant_cfg("V9_SEL", tuple(selected_blocks), seeds=(0,), description=sel_desc)
        stage1_cfgs["V9_SEL"] = cfg_sel
        stage1_order.append("V9_SEL")
        tracker.add_steps(len(stage_a_years) + len(stage_b_years))
        _run_years("V9_SEL", cfg_sel, stage_a_years, base_1s_ll_by_year)
        eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
        raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V8_1s")
        by_var_a = {r["variant"]: r for r in raw_a_rows}
        ll_sel = by_var_a["V9_SEL"]["ll"]
        ll_all = by_var_a["V9_ALL"]["ll"]
        stage3_candidate = "V9_SEL" if ll_sel <= ll_all else "V9_ALL"
        sel_note = f"`V9_SEL` ({'+'.join(selected_blocks)}) Aşama A'da çalıştırıldı"

    def _order_diag_rows(by_var_map, order_list):
        rows_out = [by_var_map[k] for k in ("B0", "V8_1s") if k in by_var_map]
        rest = [by_var_map[v] for v in order_list if v != "V8_1s" and v in by_var_map]
        rest.sort(key=lambda r: (r["dll_e0"], order_list.index(r["variant"])))
        rows_out.extend(rest)
        return rows_out

    stage1_rows = _order_diag_rows(by_var_a, stage1_order)

    # Stage 2 (Aşama 2): Diagnostic 1-seed check on 2022–2025 (including V9_DAY)
    stage2_rows = []
    if stage_b_years:
        for v_name in stage1_order:
            _run_years(v_name, stage1_cfgs[v_name], stage_b_years, base_1s_ll_by_year)
        eval_b_1s, preds_b_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, stage1_order)
        raw_b_1s, _ = _summarize_period_metrics(eval_b_1s, preds_b_1s, stage1_order, base_key="V8_1s")
        stage2_rows = _order_diag_rows({r["variant"]: r for r in raw_b_1s}, stage1_order)

    # Stage 3 (Aşama 3): Strictly ONE candidate from Stage A vs V8_BASE (5-seed + temperature calibration)
    all_cal_years = sorted(set(warmup_years + stage_a_years + stage_b_years + stage_c_years))
    cal_eval_years = sorted(set(stage_a_years + stage_b_years + stage_c_years))
    stage3_b_rows = []
    stage3_b_yearly_detail = []
    stage3_gate_result = None
    stage3_passed = False
    stage3_c_rows = []
    cal_param_rows = []

    if stage3_candidate is not None:
        seeds_5 = tuple(int(s) for s in V8_CONFIG["seeds"])
        cand_blks = tuple(stage1_cfgs[stage3_candidate]["v9_blocks"])
        stage3_specs = [
            ("V8_BASE", (), "Resmi V8 tabanı (5 tohum + sıcaklık)"),
            (stage3_candidate, cand_blks, f"{stage3_candidate} (5 tohum + sıcaklık)"),
        ]

        cal_names = []
        for s3_name, blks, desc in stage3_specs:
            raw_5s_name = f"{s3_name}_5s"
            cal_name = "V8_BASE" if s3_name == "V8_BASE" else f"{s3_name}_CAL"
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
                if cal_name == "V8_BASE":
                    base_5s_ll_by_year[f"cal_{y}"] = ll_y
                    dll_val = 0.0
                elif f"cal_{y}" in base_5s_ll_by_year:
                    dll_val = float((ll_y - base_5s_ll_by_year[f"cal_{y}"]).mean())
                else:
                    dll_val = np.nan
                tracker.log_step(cal_name, y, dt_s, dll_val, from_cache=from_c)

        cand_cal = f"{stage3_candidate}_CAL"
        if stage_b_years:
            eval_b_5s, preds_b_5s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, cal_names)
            stage3_b_rows, race_dll_b = _summarize_period_metrics(
                eval_b_5s, preds_b_5s, cal_names, base_key="V8_BASE"
            )
            for y_b in stage_b_years:
                ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], cal_names)
                yr_rows_b, _ = _summarize_period_metrics(ev_yb, pr_yb, cal_names, base_key="V8_BASE")
                for r_yb in yr_rows_b:
                    r_yb["year"] = int(y_b)
                    stage3_b_yearly_detail.append(r_yb)

            by_var_b3 = {r["variant"]: r for r in stage3_b_rows}
            if cand_cal in by_var_b3:
                r_b = by_var_b3[cand_cal]
                stage3_gate_result = evaluate_stage_b_gate(
                    r_b["yearly_dll"],
                    race_dll_b[cand_cal],
                    n_boot=2000,
                    seed=0,
                    min_neg_years=3,
                )
                stage3_passed = bool(stage3_gate_result["passed"])

        if stage_c_years:
            eval_c_5s, preds_c_5s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, cal_names)
            stage3_c_rows, _ = _summarize_period_metrics(eval_c_5s, preds_c_5s, cal_names, base_key="V8_BASE")
    elif stage_c_years:
        for v_name in stage1_order:
            _run_years(v_name, stage1_cfgs[v_name], stage_c_years, base_1s_ll_by_year)
        eval_c_1s, preds_c_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, stage1_order)
        raw_c_rows, _ = _summarize_period_metrics(eval_c_1s, preds_c_1s, stage1_order, base_key="V8_1s")
        stage3_c_rows = _order_diag_rows({r["variant"]: r for r in raw_c_rows}, stage1_order)

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

    report_md = format_v9_report(
        smoke=False,
        meta=meta,
        timing_hist=v9_timing_hist,
        timing_day=timing_day,
        feat_fill_rows=feat_fill_rows,
        yearly_cov_rows=yearly_cov_rows,
        work_src_year_rows=work_src_rows,
        work_runner_rows=work_run_rows,
        stage1_rows=stage1_rows,
        stage1_years=stage_a_years,
        selected_blocks=selected_blocks,
        sel_note=sel_note,
        stage3_candidate=stage3_candidate,
        stage2_rows=stage2_rows,
        stage2_years=stage_b_years,
        stage3_b_rows=stage3_b_rows,
        stage3_b_yearly_detail=stage3_b_yearly_detail,
        stage3_gate_result=stage3_gate_result,
        stage3_passed=stage3_passed,
        stage3_c_rows=stage3_c_rows,
        cal_param_rows=cal_param_rows,
    )

    out_dir = os.path.dirname(str(out_report))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_report, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"[v9] Rapor yazıldı: {out_report}", flush=True)
    return {
        "smoke": False,
        "report_path": str(out_report),
        "stage1_rows": stage1_rows,
        "stage2_rows": stage2_rows,
        "stage3_candidate": stage3_candidate,
        "stage3_passed": stage3_passed,
        "stage3_gate_result": stage3_gate_result,
        "sel_run_distinct": sel_run_distinct,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v9 ileri-yürüyen deney serisi (KEY, SHIP, STAB, WORK, BIAS + tanısal DAY)."
    )
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--cache-dir", default="data/v9_cache")
    ap.add_argument("--out-report", default="reports/V9.md")
    ap.add_argument("--smoke", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        run_v9_experiments(
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
