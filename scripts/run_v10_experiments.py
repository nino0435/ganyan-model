"""Walk-forward experimentation, Stage A/B/C gating, and report generator for Model v10."""
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
from ganyan.features_v9 import attach_v9
from ganyan.features_v10 import (
    SMOOTHING_CONSTANTS,
    V10_BLOCK_COLS,
    V10_CANDIDATE_BLOCKS,
    _BLOCK_COMPUTERS,
    _BLOCK_NEEDED_COLS,
    _attach_cols,
    _build_v10_ctx,
    attach_BELL,
    attach_H2H,
    attach_JLOY,
    attach_LOAD,
    attach_v10,
    get_v10_cols,
)
from ganyan.model_v6 import (
    STAGE_A_YEARS,
    STAGE_B_YEARS,
    STAGE_C_YEARS,
    evaluate_stage_b_gate,
)
from ganyan.model_v9 import V9_CONFIG
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

BASE_V10_SPECS = [
    ("V9_1s", (), "V9 tabanı (v9_kssb özellikleri, 139 özellik, 1 tohum)"),
    ("V10_BELL", ("BELL",), "V9 + BELL (doğal dağılım / çan eğrisi, iyi gün tavanı, 6 özellik)"),
    ("V10_JLOY", ("JLOY",), "V9 + JLOY (jokey tercihi, terk etme ve ahır sadakati, 6 özellik)"),
    ("V10_LOAD", ("LOAD",), "V9 + LOAD (biriken efor integrali ve hız ivmesi türevi, 5 özellik)"),
    ("V10_H2H", ("H2H",), "V9 + H2H (son 2 yıl birebir rövanş / derbi karnesi, 5 özellik)"),
    ("V10_ALL", list(V10_CANDIDATE_BLOCKS), "V9 + 4 aday paket birlikte (BELL+JLOY+LOAD+H2H, 22 yeni özellik)"),
]

SEL_THRESHOLD_DLL = -0.0002
LIVE_BASELINE_S = 220.0  # ~3.5 dk aktif 4 canlı model (v6+v7+v8+v9)
LIVE_BUDGET_EXTRA_S = 30.0


def _make_variant_cfg(
    name,
    v10_blocks,
    seeds=(0,),
    calibration=None,
    calibrated_from=None,
    description="",
    extra_meta=None,
):
    cfg = {
        "variant": str(name),
        "family": "V10" if v10_blocks else "V9",
        "description": str(description),
        "history_start": str(V9_CONFIG["history_start"]),
        "history_start_year": int(V9_CONFIG["history_start_year"]),
        "train_start_year": int(V9_CONFIG["train_start_year"]),
        "require_agf": bool(V9_CONFIG["require_agf"]),
        "v7_blocks": list(V9_CONFIG["v7_blocks"]),
        "v8_blocks": list(V9_CONFIG["v8_blocks"]),
        "v9_blocks": list(V9_CONFIG["v9_blocks"]),
        "v10_blocks": list(v10_blocks),
        "feature_cols": get_v10_cols(v10_blocks=v10_blocks, with_program=False),
        "hgb_params": dict(V9_CONFIG["hgb_params"]),
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


def _attach_v10_timed(df_base, blocks=V10_CANDIDATE_BLOCKS):
    """Attach V10 blocks via shared context while timing shared prep, each block, and concat."""
    if len(df_base) == 0:
        return attach_v10(df_base, blocks=blocks), {
            "shared_ctx_s": 0.0,
            "concat_s": 0.0,
            "blocks": {},
            "candidates_total_s": 0.0,
        }
    blk_list = tuple(blocks)
    needed = sorted({c for b in blk_list for c in _BLOCK_NEEDED_COLS[b]})

    t0 = time.perf_counter()
    ctx = _build_v10_ctx(df_base, tuple(needed))
    shared_ctx_s = time.perf_counter() - t0

    block_times = {}
    all_cols = {}
    for blk in blk_list:
        tb0 = time.perf_counter()
        all_cols.update(_BLOCK_COMPUTERS[blk](ctx))
        block_times[blk] = time.perf_counter() - tb0

    tc0 = time.perf_counter()
    out = _attach_cols(df_base, all_cols)
    concat_s = time.perf_counter() - tc0

    cand_s = shared_ctx_s + sum(block_times.get(b, 0.0) for b in V10_CANDIDATE_BLOCKS) + concat_s
    return out, {
        "shared_ctx_s": shared_ctx_s,
        "concat_s": concat_s,
        "blocks": block_times,
        "candidates_total_s": cand_s,
    }


def _build_v10_history_frame(runners_df, v5_tables, max_date=None):
    """Build single leak-free feature DataFrame (`2006-03-04`->) with V5 + V7 + V8 + V9(SEL) + V10 attached."""
    start_ts = pd.Timestamp(V9_CONFIG["history_start"])
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
    df = attach_v7(df, blocks=tuple(V9_CONFIG["v7_blocks"]))
    df = attach_v8(df, blocks=tuple(V9_CONFIG["v8_blocks"]))
    df = attach_v9(df, blocks=tuple(V9_CONFIG["v9_blocks"]), v5_tables=v5_sub)
    df, v10_timing = _attach_v10_timed(df, blocks=V10_CANDIDATE_BLOCKS)
    df["_year"] = df["date"].dt.year.astype(np.int32)
    df["_has_race_win"] = df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    df["_is_eval"] = _eval_filter_mask(df)
    return df, v10_timing


def _measure_single_day_timing(df_hist, target_date_str):
    """Measure isolated `attach_v10` overhead on a single target day's runners."""
    target_ts = pd.Timestamp(target_date_str)
    day_only = df_hist[df_hist["date"] == target_ts][
        [c for c in df_hist.columns if not any(c in V10_BLOCK_COLS[b] for b in V10_CANDIDATE_BLOCKS)]
    ].copy()
    t0 = time.perf_counter()
    _ = attach_v10(day_only, blocks=V10_CANDIDATE_BLOCKS)
    day_only_s = time.perf_counter() - t0
    return {
        "target_date": str(target_date_str),
        "target_races": int(day_only["race_id"].nunique()),
        "target_runners": int(len(day_only)),
        "day_slice_attach_s": float(day_only_s),
    }


def _compute_v10_coverage_tables(df_hist, eval_mask, min_eval_year=2017):
    """Compute per-feature fill rates and yearly (`2015–2026`) packet coverage summaries."""
    eval_target = eval_mask & (df_hist["_year"] >= int(min_eval_year))
    feat_rows = []
    for blk in V10_CANDIDATE_BLOCKS:
        for col in V10_BLOCK_COLS[blk]:
            s_all = df_hist[col]
            s_ev = df_hist.loc[eval_target, col]
            feat_rows.append(
                {
                    "block": blk,
                    "col": col,
                    "all_fill": float(s_all.notna().mean()) if len(s_all) else 0.0,
                    "eval_fill": float(s_ev.notna().mean()) if len(s_ev) else 0.0,
                    "eval_nonzero": float((s_ev.notna() & (s_ev != 0)).mean()) if len(s_ev) else 0.0,
                }
            )

    sub15 = df_hist[df_hist["_year"] >= 2015]
    yearly_rows = []
    for yr, grp in sub15.groupby("_year", sort=True):
        yearly_rows.append(
            {
                "year": int(yr),
                "races": int(grp["race_id"].nunique()),
                "runners": int(len(grp)),
                "bell_fill": float(grp["bell_prob_beat_fav"].notna().mean()),
                "jloy_chose": float((grp["j_chose_over_prev"].notna() & (grp["j_chose_over_prev"] > 0)).mean()),
                "jloy_loyal": float((grp["j_chose_over_loyal_trn"].notna() & (grp["j_chose_over_loyal_trn"] > 0)).mean()),
                "load_vel": float(grp["sf_vel_recent"].notna().mean()),
                "load_acc": float(grp["sf_accel"].notna().mean()),
                "h2h_met": float((grp["h2h_meetings"].notna() & (grp["h2h_meetings"] > 0)).mean()),
                "h2h_fav": float(grp["h2h_vs_fav_margin"].notna().mean()),
            }
        )
    return feat_rows, yearly_rows


def format_v10_report(
    *,
    smoke,
    meta,
    timing_hist,
    timing_day,
    feat_fill_rows,
    yearly_cov_rows,
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
        "# Ganyan Model v10 — Duman Testi Raporu (--smoke)"
        if smoke
        else "# Ganyan Model v10 — Paket Deneyleri (BELL, JLOY, LOAD, H2H) ve Kapı Sonucu"
    )
    cand_s = float(timing_hist.get("candidates_total_s", 0.0))
    day_s = float(timing_day.get("day_slice_attach_s", 0.0))
    over_budget = cand_s > LIVE_BUDGET_EXTRA_S
    budget_note = (
        f"**UYARI:** Tam geçmiş `attach_v10` ({cand_s:.1f} sn), 30 sn ek canlı bütçesini aşıyor "
        f"(mevcut 4 canlı model toplamı ~{LIVE_BASELINE_S:.0f} sn)."
        if over_budget
        else f"Tam geçmiş `attach_v10` ({cand_s:.1f} sn), 30 sn ek canlı bütçesi **içindedir** "
        f"(mevcut 4 canlı model toplamı ~{LIVE_BASELINE_S:.0f} sn)."
    )

    lines = [
        title,
        "",
        "> **Uyarı 1 (Kapanış AGF):** Tarihsel değerlendirmede kapanış AGF (`agf_close`) kullanılır; canlıda koşudan önce alınan AGF daha az bilgi içerir.",
        "> **Uyarı 2 (Seçim Protokolü):** Aday seçimi yalnız Aşama A (`2017–2021`) üzerinde sabit `-0.0002` eşiğiyle yapılmıştır; Aşama B kapısına **en fazla tek** aday taşınmıştır.",
        "",
        "## 1. Veri, Süre, Sabitler ve Kapsam Özeti",
        "",
        f"- **Veritabanı:** `{meta['db_path']}` (salt-okunur)",
        f"- **Veri Aralığı (DB):** `{meta['db_min_date']}` … `{meta['db_max_date']}`",
        f"- **Toplam Sonuçlanmış Koşucu / Koşu:** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Taban Model (`V9_CONFIG`):** `V9_SEL_CAL` (`v9_kssb`, `139` özellik, `min_samples_leaf=400`, `l2=15.0`, `lr=0.03`, `max_iter=420`, `leaf=23`)",
        f"- **Değerlendirme Koşu Sayıları:** Aşama A `{meta['stage_a_races']:,}` | Aşama B `{meta['stage_b_races']:,}` | Aşama C (2026 bilgi) `{meta['stage_c_races']:,}`",
        "",
        "### Süre Ölçümleri ve Canlı Bütçe Değerlendirmesi",
        "",
        f"- **`attach_v10` Tüm Geçmiş Süresi (`2006-03-04`→):** 4 aday paket toplamı **`{cand_s:.2f}` sn** "
        f"(ortak hazırlık: `{timing_hist.get('shared_ctx_s', 0.0):.2f}` sn, birleştirme: `{timing_hist.get('concat_s', 0.0):.2f}` sn)",
        "  - Paket kırılımı: "
        + ", ".join(f"`{k}`: {v:.2f} sn" for k, v in timing_hist.get("blocks", {}).items()),
        f"- **Tek Günlük Program İzole Dilim (`{timing_day['target_date']}`, {timing_day['target_races']} koşu / {timing_day['target_runners']} koşucu):** `{day_s:.3f}` sn (not: canlı hat geçmiş pencereler için `2006→bugün` matrisi üzerinde çalışır; gerçek canlı ek yük tam geçmiş `attach_v10` süresine yakın olur)",
        f"- **Canlı Bütçe Durumu:** {budget_note}",
        "",
        "### Seçilen Yumuşatma ve Pencere Sabitleri",
        "",
        "| Sabit | Değer | Açıklama |",
        "|---|---:|---|",
        f"| `BELL_WINDOW` / `BELL_PRIOR_DF` | `{SMOOTHING_CONSTANTS['BELL_WINDOW']}` / `{SMOOTHING_CONSTANTS['BELL_PRIOR_DF']}` | Çan eğrisi son 8 yarış ve df=3 oynaklık büzülmesi (`sf_prior={SMOOTHING_CONSTANTS['BELL_SF_PRIOR_STD']}`, `fpct_prior={SMOOTHING_CONSTANTS['BELL_FPCT_PRIOR_STD']}`) |",
        f"| `JLOY_WINDOW_DAYS` / `JLOY_LOYAL_MIN_RIDES` | `{SMOOTHING_CONSTANTS['JLOY_WINDOW_DAYS']}` / `{SMOOTHING_CONSTANTS['JLOY_LOYAL_MIN_RIDES']}` | Antrenör-jokey 365g sadakat penceresi ve en az 5 ortak biniş eşiği |",
        f"| `JLOY_T_JWR_PRIOR_N` / `JLOY_JWR_PRIOR` | `{SMOOTHING_CONSTANTS['JLOY_T_JWR_PRIOR_N']}` / `{SMOOTHING_CONSTANTS['JLOY_JWR_PRIOR']}` | Antrenör ortalama jokey kazanma oranı yumuşatması |",
        f"| `LOAD_WIN_60` / `LOAD_WIN_180` / `LOAD_DECAY_DAYS` | `{SMOOTHING_CONSTANTS['LOAD_WIN_60']}` / `{SMOOTHING_CONSTANTS['LOAD_WIN_180']}` / `{SMOOTHING_CONSTANTS['LOAD_DECAY_DAYS']}` | 60g/180g toplam mesafe ve 30g üstel sönümlü efor integrali |",
        f"| `H2H_WINDOW_DAYS` / `H2H_PRIOR_W` / `H2H_PRIOR_N` | `{SMOOTHING_CONSTANTS['H2H_WINDOW_DAYS']}` / `{SMOOTHING_CONSTANTS['H2H_PRIOR_W']}` / `{SMOOTHING_CONSTANTS['H2H_PRIOR_N']}` | 730g ikili rövanş penceresi, Bayes yumuşatma `(beats+1.5)/(meetings+3)` ve son 25 koşu tavanı |",
        "",
    ]

    if yearly_cov_rows:
        lines += [
            "### Yıllık V10 Paket Sinyal ve Doluluk Oranları (`2015–2026`)",
            "",
            "| Yıl | Koşu | Koşucu | `bell_prob` Dolu | `j_chose=1` | `j_loyal=1` | `sf_vel` Dolu | `sf_accel` Dolu | `h2h_meet>0` | `h2h_vs_fav` Dolu |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for yr in yearly_cov_rows:
            lines.append(
                f"| {yr['year']} | {yr['races']:,} | {yr['runners']:,} | "
                f"{yr['bell_fill']:.1%} | {yr['jloy_chose']:.1%} | {yr['jloy_loyal']:.1%} | "
                f"{yr['load_vel']:.1%} | {yr['load_acc']:.1%} | {yr['h2h_met']:.1%} | {yr['h2h_fav']:.1%} |"
            )

    if feat_fill_rows:
        lines += [
            "",
            "### V10 Özellik Doluluk Özeti (`2017+` Değerlendirme Kümesi)",
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
        f"- **Otomatik Seçim Kuralı (`SEL_THRESHOLD_DLL = {SEL_THRESHOLD_DLL:+.4f}`):** Eşiği geçen paketler: "
        + (", ".join(f"`{b}`" for b in selected_blocks) if selected_blocks else "**yok**")
        + f" ({sel_note})",
        f"- **Aşama B'ye Seçilen Tek Aday:** `{stage3_candidate}`" if stage3_candidate else "- **Aşama B'ye Seçilen Tek Aday:** Yok (**V9 korunur**)",
        "",
        "| Varyant | Koşu | Log-Loss | ΔLL vs `V9_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    for r in stage1_rows:
        v = r["variant"]
        lines.append(
            f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V9_1s'))} | "
            f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
        )
    lines.extend(_format_yearly_dll_matrix(stage1_rows, stage1_years, "V9_1s", "Aşama A Yıllık ΔLL(varyant − V9_1s)"))

    lines += [
        "",
        "## 3. Aşama 2 — Tanısal Karşılaştırma (`2022–2025`, 1-Tohum `seed=0`)",
        "",
        "> **Not:** Bu tablo örnek-dışı davranış içindir; aday seçimi Aşama A'da dondurulmuştur.",
        "",
    ]
    if smoke or not stage2_rows:
        lines.append("Duman testinde Aşama 2 tanısal tablosu hesaplanmadı.")
    else:
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V9_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|",
        ]
        for r in stage2_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V9_1s'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )
        lines.extend(_format_yearly_dll_matrix(stage2_rows, stage2_years, "V9_1s", "Aşama 2 Tanısal Yıllık ΔLL(varyant − V9_1s)"))

    lines += [
        "",
        "## 4. Aşama 3 — Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)",
        "",
        "- **Kapı Kuralı (`evaluate_stage_b_gate`):** `ΔLL(aday − V9_BASE)` için koşu-eşli bootstrap %95 GA üst sınırı `< 0` **VE** `4` yılın en az `3`'ünde `ΔLL < 0`.",
        "",
    ]
    if smoke:
        lines.append("Duman testinde Aşama 3 tam kapı koşusu çalıştırılmadı.")
    elif stage3_candidate is None:
        lines.append(
            f"**KAPI SONUCU:** Aşama A (`2017–2021`) taramasında hiçbir tekil V10 paketi `{SEL_THRESHOLD_DLL:+.4f}` eşiğini geçemediğinden Aşama 3 çalıştırılmadı — **V9 korunur**."
        )
    else:
        lines.append(f"- **Sınanan Tek Aday (`Aşama A` kazananı):** `{stage3_candidate}`")
        lines.append("")
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı Kararı |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for r in stage3_b_rows:
            v = r["variant"]
            if v == "B0":
                g_txt = "Referans (Saf AGF)"
            elif v == "V9_BASE":
                g_txt = "Taban (`V9_CONFIG`)"
            else:
                g_txt = "**GEÇTİ**" if stage3_passed else "**KALDI**"
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V9_BASE'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_txt} |"
            )

        if stage3_b_yearly_detail:
            lines += [
                "",
                "### Aşama B Yıllık Ayrıntı (5-Tohum + Sıcaklık Kalibrasyonu)",
                "",
                "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
                "|---:|---|---:|---:|---|---:|---:|---:|",
            ]
            for yr_row in stage3_b_yearly_detail:
                v = yr_row["variant"]
                lines.append(
                    f"| {yr_row['year']} | `{v}` | {yr_row['races']} | {yr_row['ll']:.4f} | "
                    f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'V9_BASE'))} | "
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
            lines.append(f"**KAPI SONUCU:** `{stage3_candidate}_CAL` Aşama B sabit kapısını geçemedi — **V9 korunur**.")

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
        base_c = "V9_BASE" if any(r["variant"] == "V9_BASE" for r in stage3_c_rows) else "V9_1s"
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


def run_v10_experiments(
    db_path="data/ganyan.db",
    cache_dir="data/v10_cache",
    out_report="reports/V10.md",
    smoke=False,
):
    """Run staged Model v10 experiments (BELL, JLOY, LOAD, H2H)."""
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
        df_sm, v10_timing_sm = _build_v10_history_frame(
            runners_df, v5_tables, max_date=f"{target_y}-12-31"
        )
        print(
            f"[smoke] Özellik inşası tamamlandı (toplam={time.perf_counter() - t_feat0:.1f}sn, "
            f"attach_v10_aday={v10_timing_sm['candidates_total_s']:.2f}sn)",
            flush=True,
        )
        sm_max_day = df_sm["date"].max().strftime("%Y-%m-%d")
        timing_day_sm = _measure_single_day_timing(df_sm, sm_max_day)

        eval_mask_sm = df_sm["_is_eval"]
        eval_y = (
            df_sm[eval_mask_sm & (df_sm["_year"] == target_y)][
                ["race_id", "horse_key", "date", "_year", "win", "finish", "ganyan", "agf_close", "agf_share", "field"]
            ]
            .copy()
            .reset_index(drop=True)
        )
        if len(eval_y) == 0:
            raise ValueError(f"Duman testi yılı ({target_y}) için değerlendirilebilir koşu bulunamadı.")

        feat_fill_rows, yearly_cov_rows = _compute_v10_coverage_tables(df_sm, eval_mask_sm, min_eval_year=target_y)
        for blk in V10_CANDIDATE_BLOCKS:
            blk_nz = sum(fr["eval_nonzero"] for fr in feat_fill_rows if fr["block"] == blk)
            if blk_nz <= 0.0:
                raise RuntimeError(f"Smoke testinde Paket {blk} sıfır-dışı kapsamı 0!")

        smoke_extra = {"mode": "smoke_pct20"}
        tracker = _ProgressTracker(total_planned_steps=len(BASE_V10_SPECS))
        preds_sm = {}
        ll_base = None
        for v_name, blks, desc in BASE_V10_SPECS:
            cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc, extra_meta=smoke_extra)
            p_y, dt_s, from_c = _predict_base_year(df_sm, eval_y, cfg, target_y, cache_dir, smoke=True)
            if p_y is None or not np.all(np.isfinite(p_y)):
                raise RuntimeError(f"Smoke {v_name} tahmini geçersiz!")
            preds_sm[v_name] = p_y
            ll_y = _race_winner_lls(eval_y, p_y)
            if v_name == "V9_1s":
                ll_base = ll_y
                dll_val = 0.0
            else:
                dll_val = float((ll_y - ll_base).mean())
            tracker.log_step(v_name, target_y, dt_s, dll_val, from_cache=from_c)

        del df_sm
        gc.collect()

        stage1_rows, _ = _summarize_period_metrics(
            eval_y, preds_sm, [v[0] for v in BASE_V10_SPECS], base_key="V9_1s"
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
        report_md = format_v10_report(
            smoke=True,
            meta=meta,
            timing_hist=v10_timing_sm,
            timing_day=timing_day_sm,
            feat_fill_rows=feat_fill_rows,
            yearly_cov_rows=yearly_cov_rows,
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
        return {
            "smoke": True,
            "report_path": str(out_report),
            "timing": v10_timing_sm,
            "stage1_rows": stage1_rows,
        }

    t_f0 = time.perf_counter()
    print("[v10] Özellik matrisi kuruluyor (2006-03-04→)...", flush=True)
    df_hist, v10_timing_hist = _build_v10_history_frame(runners_df, v5_tables)
    del runners_df, v5_tables
    gc.collect()
    timing_day = _measure_single_day_timing(df_hist, db_max_date)
    print(
        f"[v10] Özellik matrisi hazır ({len(df_hist):,} satır, {len(df_hist.columns)} sütun, "
        f"toplam={time.perf_counter() - t_f0:.1f}sn, attach_v10_aday={v10_timing_hist['candidates_total_s']:.2f}sn, "
        f"kırılım={ {k: round(v, 2) for k, v in v10_timing_hist['blocks'].items()} })",
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
    feat_fill_rows, yearly_cov_rows = _compute_v10_coverage_tables(df_hist, eval_mask, min_eval_year=min(stage_a_years))

    est_steps = len(BASE_V10_SPECS) * (len(stage_a_years) + len(stage_b_years)) + 2 * (
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
            if var_name in ("V9_1s", "V9_BASE_5s"):
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
    for v_name, blks, desc in BASE_V10_SPECS:
        cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc)
        stage1_cfgs[v_name] = cfg
        stage1_order.append(v_name)
        _run_years(v_name, cfg, stage_a_years, base_1s_ll_by_year)

    eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
    raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V9_1s")
    by_var_a = {r["variant"]: r for r in raw_a_rows}

    selected_blocks = [
        blk
        for blk in V10_CANDIDATE_BLOCKS
        if f"V10_{blk}" in by_var_a and by_var_a[f"V10_{blk}"]["dll_e0"] < SEL_THRESHOLD_DLL
    ]

    # Build/alias V10_SEL & pick AT MOST ONE candidate between V10_SEL and V10_ALL for Stage B
    stage3_candidate = None
    sel_run_distinct = False
    if not selected_blocks:
        sel_note = "`V10_SEL` oluşturulmadı — hiçbir tekil paket eşiği geçemedi"
        if by_var_a["V10_ALL"]["dll_e0"] < SEL_THRESHOLD_DLL:
            stage3_candidate = "V10_ALL"
            sel_note += " ama birleşik `V10_ALL` eşiği geçti"
        else:
            sel_note += " (**V9 korunur**)"
    elif len(selected_blocks) == 1:
        only_name = f"V10_{selected_blocks[0]}"
        sel_note = f"`V10_SEL`, tek geçen `{only_name}` ile özdeştir"
        ll_sel = by_var_a[only_name]["ll"]
        ll_all = by_var_a["V10_ALL"]["ll"]
        stage3_candidate = only_name if ll_sel <= ll_all else "V10_ALL"
    elif tuple(selected_blocks) == V10_CANDIDATE_BLOCKS:
        sel_note = "`V10_SEL`, 4 paketin tümünü içeren `V10_ALL` ile özdeştir"
        stage3_candidate = "V10_ALL"
    else:
        sel_run_distinct = True
        sel_desc = f"V9 + seçili paketler ({'+'.join(selected_blocks)})"
        cfg_sel = _make_variant_cfg("V10_SEL", tuple(selected_blocks), seeds=(0,), description=sel_desc)
        stage1_cfgs["V10_SEL"] = cfg_sel
        stage1_order.append("V10_SEL")
        tracker.add_steps(len(stage_a_years) + len(stage_b_years))
        _run_years("V10_SEL", cfg_sel, stage_a_years, base_1s_ll_by_year)
        eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
        raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V9_1s")
        by_var_a = {r["variant"]: r for r in raw_a_rows}
        ll_sel = by_var_a["V10_SEL"]["ll"]
        ll_all = by_var_a["V10_ALL"]["ll"]
        stage3_candidate = "V10_SEL" if ll_sel <= ll_all else "V10_ALL"
        sel_note = f"`V10_SEL` ({'+'.join(selected_blocks)}) Aşama A'da çalıştırıldı"

    def _order_diag_rows(by_var_map, order_list):
        rows_out = [by_var_map[k] for k in ("B0", "V9_1s") if k in by_var_map]
        rest = [by_var_map[v] for v in order_list if v != "V9_1s" and v in by_var_map]
        rest.sort(key=lambda r: (r["dll_e0"], order_list.index(r["variant"])))
        rows_out.extend(rest)
        return rows_out

    stage1_rows = _order_diag_rows(by_var_a, stage1_order)

    # Stage 2 (Aşama 2): Diagnostic 1-seed check on 2022–2025
    stage2_rows = []
    if stage_b_years:
        for v_name in stage1_order:
            _run_years(v_name, stage1_cfgs[v_name], stage_b_years, base_1s_ll_by_year)
        eval_b_1s, preds_b_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, stage1_order)
        raw_b_1s, _ = _summarize_period_metrics(eval_b_1s, preds_b_1s, stage1_order, base_key="V9_1s")
        stage2_rows = _order_diag_rows({r["variant"]: r for r in raw_b_1s}, stage1_order)

    # Stage 3 (Aşama 3): Strictly ONE candidate from Stage A vs V9_BASE (5-seed + temperature calibration)
    all_cal_years = sorted(set(warmup_years + stage_a_years + stage_b_years + stage_c_years))
    cal_eval_years = sorted(set(stage_a_years + stage_b_years + stage_c_years))
    stage3_b_rows = []
    stage3_b_yearly_detail = []
    stage3_gate_result = None
    stage3_passed = False
    stage3_c_rows = []
    cal_param_rows = []

    if stage3_candidate is not None:
        seeds_5 = tuple(int(s) for s in V9_CONFIG["seeds"])
        cand_blks = tuple(stage1_cfgs[stage3_candidate]["v10_blocks"])
        stage3_specs = [
            ("V9_BASE", (), "Resmi V9 tabanı (5 tohum + sıcaklık)"),
            (stage3_candidate, cand_blks, f"{stage3_candidate} (5 tohum + sıcaklık)"),
        ]

        cal_names = []
        for s3_name, blks, desc in stage3_specs:
            raw_5s_name = f"{s3_name}_5s"
            cal_name = "V9_BASE" if s3_name == "V9_BASE" else f"{s3_name}_CAL"
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
                if cal_name == "V9_BASE":
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
                eval_b_5s, preds_b_5s, cal_names, base_key="V9_BASE"
            )
            for y_b in stage_b_years:
                ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], cal_names)
                yr_rows_b, _ = _summarize_period_metrics(ev_yb, pr_yb, cal_names, base_key="V9_BASE")
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
            stage3_c_rows, _ = _summarize_period_metrics(eval_c_5s, preds_c_5s, cal_names, base_key="V9_BASE")
    elif stage_c_years:
        for v_name in stage1_order:
            _run_years(v_name, stage1_cfgs[v_name], stage_c_years, base_1s_ll_by_year)
        eval_c_1s, preds_c_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, stage1_order)
        raw_c_rows, _ = _summarize_period_metrics(eval_c_1s, preds_c_1s, stage1_order, base_key="V9_1s")
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

    report_md = format_v10_report(
        smoke=False,
        meta=meta,
        timing_hist=v10_timing_hist,
        timing_day=timing_day,
        feat_fill_rows=feat_fill_rows,
        yearly_cov_rows=yearly_cov_rows,
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

    print(f"[v10] Rapor yazıldı: {out_report}", flush=True)
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


HLB_BLOCKS = ("BELL", "LOAD", "H2H")


def _upsert_markdown_section(report_path, header_prefix, section_md):
    """Append or replace a markdown section starting with `header_prefix` idempotently."""
    existing = ""
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            existing = f.read()
    idx = existing.find(f"\n{header_prefix}")
    if idx < 0 and existing.startswith(header_prefix):
        idx = 0
    if idx >= 0:
        base_txt = existing[:idx].rstrip()
    else:
        base_txt = existing.rstrip()
    out_txt = f"{base_txt}\n\n{section_md.strip()}\n" if base_txt else f"{section_md.strip()}\n"
    out_dir = os.path.dirname(str(report_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(out_txt)


def format_hlb_ablation_section(
    *,
    timing_hist,
    hlb_total_s,
    stage_a_rows,
    stage_b_rows,
    stage_b_yearly,
    hlb_passed,
    stage_c_rows,
    cal_param_rows,
):
    """Format Section 6 for `JLOY`-free `V10_HLB` (`BELL + LOAD + H2H`) ablation."""
    lines = [
        "## 6. Ek Ablasyon — `JLOY` Hariç `V10_HLB` (`BELL + LOAD + H2H`, `155` Özellik)",
        "",
        "> **Ek Ablasyon / Tanısal Notu:** Bu bölüm, resmi Aşama B kapısı sonrasında Aşama 2 (`2022–2025`) bulguları görülerek eksi yazan `JLOY` paketi çıkarılıp yalnızca `BELL + LOAD + H2H` (`155` özellik) ile yapılan tekil ek ablasyon denemesidir; Aşama A ön seçim kuralının dışındadır.",
        "",
        f"- **Tahmini `HLB` Özellik Süresi (`2006-03-04`→):** **`{hlb_total_s:.2f}` sn** "
        f"(ortak hazırlık: `{timing_hist.get('shared_ctx_s', 0.0):.2f}` sn, "
        + ", ".join(f"`{b}`: {timing_hist['blocks'].get(b, 0.0):.2f} sn" for b in HLB_BLOCKS)
        + f", birleştirme: `{timing_hist.get('concat_s', 0.0):.2f}` sn — `30` sn bütçe **içinde**)",
        "",
        "### Ek Ablasyon — `2022–2025` Karşılaştırması (5-Tohum + İleri-Yürüyen Sıcaklık Kalibrasyonu)",
        "",
        "| Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Ek Kapı Kararı |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for r in stage_b_rows:
        v = r["variant"]
        if v == "B0":
            g_txt = "Referans (Saf AGF)"
        elif v == "V9_BASE":
            g_txt = "Taban (`V9_CONFIG`)"
        elif v == "V10_ALL_CAL":
            g_txt = "KALDI (resmi)"
        else:
            g_txt = "**GEÇTİ (ek ablasyon)**" if hlb_passed else "**KALDI**"
        lines.append(
            f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V9_BASE'))} | "
            f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_txt} |"
        )

    if stage_b_yearly:
        lines += [
            "",
            "### Ek Ablasyon — `2022–2025` Yıllık Ayrıntı (`V9_BASE` vs `V10_ALL_CAL` vs `V10_HLB_CAL`)",
            "",
            "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---:|---|---:|---:|---|---:|---:|---:|",
        ]
        for yr_row in stage_b_yearly:
            v = yr_row["variant"]
            lines.append(
                f"| {yr_row['year']} | `{v}` | {yr_row['races']} | {yr_row['ll']:.4f} | "
                f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'V9_BASE'))} | "
                f"{yr_row['top1']:.2%} | {yr_row['top2']:.2%} | {yr_row['top3']:.2%} |"
            )

    if stage_a_rows:
        lines += [
            "",
            "### Ek Ablasyon — `2017–2021` (5-Tohum + Sıcaklık Kalibrasyonu, Bilgi)",
            "",
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/5) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|",
        ]
        for r in stage_a_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V9_BASE'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )

    if stage_c_rows:
        lines += [
            "",
            "### Ek Ablasyon — `2026` Bilgi Kümesi (`5.483` Koşu, 5-Tohum + Sıcaklık)",
            "",
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V9_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---|---|---|",
        ]
        for r in stage_c_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V9_BASE'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )

    if cal_param_rows:
        lines += [
            "",
            "### `V10_HLB_CAL` İleri-Yürüyen Sıcaklık Kalibrasyonu Katsayıları (`gamma = 1/T`)",
            "",
            "| Varyant | Test Yılı | Uydurma Yılları (`< Y`) | Uydurma Koşu | `gamma` (`T=1/gamma`) |",
            "|---|---:|---|---:|---:|",
        ]
        for cr in cal_param_rows:
            p_txt = f"{cr['param']:.4f} (T={1.0 / cr['param']:.4f})" if np.isfinite(cr["param"]) else "—"
            lines.append(
                f"| `{cr['variant']}` | {cr['year']} | {cr['fit_years']} | {cr['fit_races']} | {p_txt} |"
            )

    return "\n".join(lines).rstrip() + "\n"


def run_v10_hlb_ablation(
    db_path="data/ganyan.db",
    cache_dir="data/v10_cache",
    out_report="reports/V10.md",
):
    """Run targeted 5-seed + temperature ablation for `V10_HLB` (`BELL + LOAD + H2H`) reusing cache."""
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

    print("[v10-hlb] Özellik matrisi kuruluyor (2006-03-04→)...", flush=True)
    t_f0 = time.perf_counter()
    df_hist, v10_timing_hist = _build_v10_history_frame(runners_df, v5_tables)
    del runners_df, v5_tables
    gc.collect()
    hlb_total_s = (
        float(v10_timing_hist.get("shared_ctx_s", 0.0))
        + sum(float(v10_timing_hist["blocks"].get(b, 0.0)) for b in HLB_BLOCKS)
        + float(v10_timing_hist.get("concat_s", 0.0))
    )
    print(
        f"[v10-hlb] Özellik matrisi hazır ({len(df_hist):,} satır, toplam={time.perf_counter() - t_f0:.1f}sn, "
        f"hlb_süre={hlb_total_s:.2f}sn)",
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
    eval_by_year = {
        int(y): eval_all_meta[eval_all_meta["_year"] == int(y)].copy().reset_index(drop=True)
        for y in sorted(eval_years_set)
    }

    all_cal_years = sorted(set(warmup_years + stage_a_years + stage_b_years + stage_c_years))
    cal_eval_years = sorted(set(stage_a_years + stage_b_years + stage_c_years))
    seeds_5 = tuple(int(s) for s in V9_CONFIG["seeds"])

    specs = [
        ("V9_BASE", (), "Resmi V9 tabanı (5 tohum + sıcaklık)"),
        ("V10_ALL", tuple(V10_CANDIDATE_BLOCKS), "V10_ALL (5 tohum + sıcaklık)"),
        ("V10_HLB", HLB_BLOCKS, "Ek ablasyon: JLOY hariç V10_HLB (BELL+LOAD+H2H, 5 tohum + sıcaklık)"),
    ]
    tracker = _ProgressTracker(total_planned_steps=len(specs) * (len(all_cal_years) + len(cal_eval_years)))
    preds_by_var_year = {}
    ref_5s_ll = {}
    ref_cal_ll = {}
    hlb_cal_params = []
    cal_names = []

    for s3_name, blks, desc in specs:
        raw_5s_name = f"{s3_name}_5s"
        cal_name = "V9_BASE" if s3_name == "V9_BASE" else f"{s3_name}_CAL"
        cal_names.append(cal_name)

        cfg_5s = _make_variant_cfg(raw_5s_name, blks, seeds=seeds_5, description=desc)
        preds_by_var_year[raw_5s_name] = {}
        for y in all_cal_years:
            ev_y = eval_by_year.get(int(y))
            if ev_y is None or len(ev_y) == 0:
                continue
            p_y, dt_s, from_c = _predict_base_year(df_hist, ev_y, cfg_5s, y, cache_dir, smoke=False)
            if p_y is None:
                continue
            preds_by_var_year[raw_5s_name][int(y)] = p_y
            ll_y = _race_winner_lls(ev_y, p_y)
            if s3_name == "V9_BASE":
                ref_5s_ll[int(y)] = ll_y
                dll_val = 0.0
            else:
                dll_val = float((ll_y - ref_5s_ll[int(y)]).mean()) if int(y) in ref_5s_ll else np.nan
            tracker.log_step(raw_5s_name, y, dt_s, dll_val, from_cache=from_c)

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
            if cal_name == "V10_HLB_CAL" and c_meta is not None:
                hlb_cal_params.append(c_meta)
            ll_y = _race_winner_lls(ev_y, p_c)
            if cal_name == "V9_BASE":
                ref_cal_ll[int(y)] = ll_y
                dll_val = 0.0
            else:
                dll_val = float((ll_y - ref_cal_ll[int(y)]).mean()) if int(y) in ref_cal_ll else np.nan
            tracker.log_step(cal_name, y, dt_s, dll_val, from_cache=from_c)

    stage_a_rows = []
    if stage_a_years:
        eval_a, preds_a = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, cal_names)
        stage_a_rows, _ = _summarize_period_metrics(eval_a, preds_a, cal_names, base_key="V9_BASE")

    stage_b_rows = []
    stage_b_yearly = []
    hlb_passed = False
    hlb_gate_result = None
    if stage_b_years:
        eval_b, preds_b = _concat_year_preds(eval_by_year, preds_by_var_year, stage_b_years, cal_names)
        stage_b_rows, race_dll_b = _summarize_period_metrics(eval_b, preds_b, cal_names, base_key="V9_BASE")
        for y_b in stage_b_years:
            ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], cal_names)
            yr_rows_b, _ = _summarize_period_metrics(ev_yb, pr_yb, cal_names, base_key="V9_BASE")
            for r_yb in yr_rows_b:
                r_yb["year"] = int(y_b)
                stage_b_yearly.append(r_yb)

        by_var_b = {r["variant"]: r for r in stage_b_rows}
        if "V10_HLB_CAL" in by_var_b:
            r_h = by_var_b["V10_HLB_CAL"]
            hlb_gate_result = evaluate_stage_b_gate(
                r_h["yearly_dll"],
                race_dll_b["V10_HLB_CAL"],
                n_boot=2000,
                seed=0,
                min_neg_years=3,
            )
            hlb_passed = bool(hlb_gate_result["passed"])

    stage_c_rows = []
    if stage_c_years:
        eval_c, preds_c = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, cal_names)
        stage_c_rows, _ = _summarize_period_metrics(eval_c, preds_c, cal_names, base_key="V9_BASE")

    section_md = format_hlb_ablation_section(
        timing_hist=v10_timing_hist,
        hlb_total_s=hlb_total_s,
        stage_a_rows=stage_a_rows,
        stage_b_rows=stage_b_rows,
        stage_b_yearly=stage_b_yearly,
        hlb_passed=hlb_passed,
        stage_c_rows=stage_c_rows,
        cal_param_rows=hlb_cal_params,
    )
    _upsert_markdown_section(out_report, "## 6. Ek Ablasyon", section_md)
    print(f"[v10-hlb] Ek ablasyon bölümü yazıldı: {out_report} (passed={hlb_passed})", flush=True)
    return {
        "report_path": str(out_report),
        "hlb_passed": hlb_passed,
        "hlb_gate_result": hlb_gate_result,
        "stage_b_rows": stage_b_rows,
        "stage_c_rows": stage_c_rows,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v10 ileri-yürüyen deney serisi (BELL, JLOY, LOAD, H2H)."
    )
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--cache-dir", default="data/v10_cache")
    ap.add_argument("--out-report", default="reports/V10.md")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--ablation-hlb", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        if args.ablation_hlb and args.smoke:
            raise ValueError("--ablation-hlb ve --smoke birlikte kullanılamaz.")
        if args.ablation_hlb:
            run_v10_hlb_ablation(
                db_path=args.db,
                cache_dir=args.cache_dir,
                out_report=args.out_report,
            )
        else:
            run_v10_experiments(
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
