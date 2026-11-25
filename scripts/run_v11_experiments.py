"""Walk-forward experimentation, Stage A/B/C gating, and report generator for Model v11 (GOING, WX, GPREF)."""
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
from ganyan.features_v10 import attach_v10
from ganyan.features_v11 import (
    SMOOTHING_CONSTANTS,
    V11_BLOCK_COLS,
    V11_CANDIDATE_BLOCKS,
    _BLOCK_COMPUTERS,
    _BLOCK_NEEDED_COLS,
    _build_v11_ctx,
    attach_v11,
    get_v11_cols,
    load_v11_tables,
)
from ganyan.features_v10 import _attach_cols
from ganyan.model_v6 import (
    STAGE_A_YEARS,
    STAGE_B_YEARS,
    STAGE_C_YEARS,
    evaluate_stage_b_gate,
)
from ganyan.model_v10 import V10_BLOCKS, V10_CONFIG
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

BASE_V11_SPECS = [
    ("V10_1s", (), "V10 tabanı (v10_hlb özellikleri, 155 özellik, 1 tohum)"),
    ("V11_GOING", ("GOING",), "V10 + GOING (yüzeye göre pist sırası, ıslaklık ve çim ölçümü, 5 özellik)"),
    ("V11_WX", ("WX",), "V10 + WX (sıcaklık, nem, yağışlı gökyüzü ve rüzgarlı bayrağı, 4 özellik)"),
    ("V11_GPREF", ("GPREF",), "V10 + GPREF (atın geçmiş ıslak/kuru performans tercihi ve gün çarpımı, 7 özellik)"),
    ("V11_ALL", list(V11_CANDIDATE_BLOCKS), "V10 + 3 aday paket birlikte (GOING+WX+GPREF, 16 yeni özellik)"),
]

SEL_THRESHOLD_DLL = -0.0002
LIVE_BASELINE_S = 220.0
LIVE_BUDGET_EXTRA_S = 30.0


def _make_variant_cfg(
    name,
    v11_blocks,
    seeds=(0,),
    calibration=None,
    calibrated_from=None,
    description="",
    extra_meta=None,
):
    cfg = {
        "variant": str(name),
        "family": "V11" if v11_blocks else "V10",
        "description": str(description),
        "history_start": str(V10_CONFIG["history_start"]),
        "history_start_year": int(V10_CONFIG["history_start_year"]),
        "train_start_year": int(V10_CONFIG["train_start_year"]),
        "require_agf": bool(V10_CONFIG["require_agf"]),
        "v7_blocks": list(V10_CONFIG["v7_blocks"]),
        "v8_blocks": list(V10_CONFIG["v8_blocks"]),
        "v9_blocks": list(V10_CONFIG["v9_blocks"]),
        "v10_blocks": list(V10_BLOCKS),
        "v11_blocks": list(v11_blocks),
        "feature_cols": get_v11_cols(v11_blocks=v11_blocks, with_program=False),
        "hgb_params": dict(V10_CONFIG["hgb_params"]),
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


def _attach_v11_timed(df_base, blocks=V11_CANDIDATE_BLOCKS, v5_tables=None):
    """Attach V11 blocks via shared context while timing shared prep, each block, and concat."""
    if len(df_base) == 0:
        return attach_v11(df_base, blocks=blocks, v5_tables=v5_tables), {
            "shared_ctx_s": 0.0,
            "concat_s": 0.0,
            "blocks": {},
            "candidates_total_s": 0.0,
        }
    blk_list = tuple(blocks)
    needed = sorted({c for b in blk_list for c in _BLOCK_NEEDED_COLS[b]})

    t0 = time.perf_counter()
    ctx = _build_v11_ctx(df_base, tuple(needed), v5_tables=v5_tables)
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

    cand_s = shared_ctx_s + sum(block_times.get(b, 0.0) for b in V11_CANDIDATE_BLOCKS) + concat_s
    return out, {
        "shared_ctx_s": shared_ctx_s,
        "concat_s": concat_s,
        "blocks": block_times,
        "candidates_total_s": cand_s,
    }


def _slice_v11_tables(v11_tables, max_date=None):
    if not v11_tables:
        return {"day_cond": pd.DataFrame()}
    dc = v11_tables.get("day_cond")
    if max_date is not None and dc is not None and len(dc) > 0:
        max_str = str(max_date)[:10]
        dc = dc[dc["date"].astype(str) <= max_str].copy()
    return {"day_cond": dc}


def _build_v11_history_frame(runners_df, v5_tables, v11_tables, max_date=None):
    """Build single leak-free feature DataFrame (`2006-03-04`->) with V5..V10(HLB) + V11 attached."""
    start_ts = pd.Timestamp(V10_CONFIG["history_start"])
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
    v11_sub = _slice_v11_tables(v11_tables, max_date=max_date)

    df = build_features(r_sub, ref_end=REF_END_DEFAULT)
    del r_sub
    df = attach_v5(df, v5_sub, blocks=("S", "G", "R"))
    df = attach_v7(df, blocks=tuple(V10_CONFIG["v7_blocks"]))
    df = attach_v8(df, blocks=tuple(V10_CONFIG["v8_blocks"]))
    df = attach_v9(df, blocks=tuple(V10_CONFIG["v9_blocks"]), v5_tables=v5_sub)
    df = attach_v10(df, blocks=tuple(V10_BLOCKS))
    df, v11_timing = _attach_v11_timed(df, blocks=V11_CANDIDATE_BLOCKS, v5_tables=v11_sub)
    df["_year"] = df["date"].dt.year.astype(np.int32)
    df["_has_race_win"] = df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    df["_is_eval"] = _eval_filter_mask(df)
    return df, v11_timing


def _select_smoke_year(runners_df, v11_tables):
    """Select SMOKE_TEST_YEAR (2021) when going data exists, else latest complete year with going data."""
    avail_years = sorted(int(y) for y in runners_df["date"].dt.year.unique())
    if not avail_years:
        raise ValueError("Duman testi için yıl bulunamadı.")

    dc = v11_tables.get("day_cond") if isinstance(v11_tables, dict) else None
    dc_years = set()
    if dc is not None and len(dc) > 0:
        dc_years = {int(y) for y in pd.to_datetime(dc["date"], errors="coerce").dt.year.dropna().unique()}

    tc_series = runners_df["track_cond"].astype(str).str.strip().str.lower() if "track_cond" in runners_df.columns else pd.Series("", index=runners_df.index)
    has_tc = tc_series.isin({"kuru", "normal", "nemli", "islak", "yumusak", "agir"})
    tc_years = {int(y) for y in runners_df.loc[has_tc, "date"].dt.year.unique()}
    covered_years = dc_years | tc_years

    if SMOKE_TEST_YEAR in avail_years and SMOKE_TEST_YEAR in covered_years:
        return SMOKE_TEST_YEAR, False

    max_y = avail_years[-1]
    both_covered = [y for y in avail_years if y in (dc_years & tc_years) and y < max_y]
    if both_covered:
        return both_covered[-1], True
    full_covered = [y for y in avail_years if y in covered_years and y < max_y]
    if full_covered:
        return full_covered[-1], True
    if covered_years:
        in_avail = sorted(y for y in covered_years if y in avail_years)
        if in_avail:
            return in_avail[-1], True
    return (SMOKE_TEST_YEAR if SMOKE_TEST_YEAR in avail_years else max_y), False


def _measure_single_day_timing(df_hist, target_date_str, v11_tables):
    """Measure isolated `attach_v11` overhead on a single target day's runners."""
    target_ts = pd.Timestamp(target_date_str)
    drop_cols = {c for b in V11_CANDIDATE_BLOCKS for c in V11_BLOCK_COLS[b]}
    day_only = df_hist[df_hist["date"] == target_ts][[c for c in df_hist.columns if c not in drop_cols]].copy()
    t0 = time.perf_counter()
    _ = attach_v11(day_only, blocks=V11_CANDIDATE_BLOCKS, v5_tables=v11_tables)
    day_only_s = time.perf_counter() - t0
    return {
        "target_date": str(target_date_str),
        "target_races": int(day_only["race_id"].nunique()),
        "target_runners": int(len(day_only)),
        "day_slice_attach_s": float(day_only_s),
    }


def _compute_v11_coverage_tables(df_hist, eval_mask, min_eval_year=2017):
    """Compute per-feature fill rates and yearly (`2015–2026`) GOING/WX/GPREF coverage summaries."""
    eval_target = eval_mask & (df_hist["_year"] >= int(min_eval_year))
    feat_rows = []
    for blk in V11_CANDIDATE_BLOCKS:
        for col in V11_BLOCK_COLS[blk]:
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
                "going_fill": float(grp["going_ord"].notna().mean()),
                "going_wet": float((grp["going_wet"] == 1.0).mean()),
                "turf_num": float(grp["going_turf_num"].notna().mean()),
                "wx_temp": float(grp["wx_temp_c"].notna().mean()),
                "wx_rainy": float((grp["wx_rainy"] == 1.0).mean()),
                "gpref_wet": float((grp["gpref_wet_n"] > 0.0).mean()),
                "gpref_delta": float(grp["gpref_wet_fpct_delta"].notna().mean()),
            }
        )
    return feat_rows, yearly_rows


def format_v11_report(
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
        "# Ganyan Model v11 — Duman Testi Raporu (--smoke)"
        if smoke
        else "# Ganyan Model v11 — Pist Durumu ve Hava (GOING, WX, GPREF) Deneyleri ve Kapı Sonucu"
    )
    cand_s = float(timing_hist.get("candidates_total_s", 0.0))
    day_s = float(timing_day.get("day_slice_attach_s", 0.0))
    over_budget = cand_s > LIVE_BUDGET_EXTRA_S
    budget_note = (
        f"**UYARI:** Tam geçmiş `attach_v11` ({cand_s:.1f} sn), 30 sn ek canlı bütçesini aşıyor."
        if over_budget
        else f"Tam geçmiş `attach_v11` ({cand_s:.1f} sn), 30 sn ek canlı bütçesi **içindedir**."
    )

    lines = [
        title,
        "",
        "> **Sınırlama Notu (Gün Sonu Bloğu):** Tarihsel TJK şehir-gün bloğu gün SONU pist ve hava durumudur; canlıda ise koşu anındaki/öncesindeki ilan görülecektir.",
        "> **Uyarı 1 (Kapanış AGF):** Tarihsel değerlendirmede kapanış AGF (`agf_close`) kullanılır; canlıda koşudan önce alınan AGF daha az bilgi içerir.",
        "> **Uyarı 2 (Seçim Protokolü):** Aday seçimi yalnız Aşama A (`2017–2021`) üzerinde sabit `-0.0002` eşiğiyle yapılmıştır; Aşama B kapısına **en fazla tek** aday taşınmıştır.",
        "",
        "## 1. Veri, Süre, Sabitler ve Kapsam Özeti",
        "",
        f"- **Veritabanı:** `{meta['db_path']}` (salt-okunur)",
        f"- **Veri Aralığı (DB):** `{meta['db_min_date']}` … `{meta['db_max_date']}`",
        f"- **Toplam Sonuçlanmış Koşucu / Koşu:** `{meta['total_rows']:,}` satır / `{meta['total_races']:,}` koşu",
        f"- **Taban Model (`V10_CONFIG`):** `V10_HLB_CAL` (`v10_hlb`, `155` özellik, `min_samples_leaf=400`, `l2=15.0`, `lr=0.03`, `max_iter=420`, `leaf=23`)",
        f"- **Değerlendirme Koşu Sayıları:** Aşama A `{meta['stage_a_races']:,}` | Aşama B `{meta['stage_b_races']:,}` | Aşama C (2026 bilgi) `{meta['stage_c_races']:,}`",
        "",
        "### Süre Ölçümleri ve Canlı Bütçe Değerlendirmesi",
        "",
        f"- **`attach_v11` Geçmiş Süresi (`2006-03-04`→):** 3 aday paket toplamı **`{cand_s:.2f}` sn** "
        f"(ortak hazırlık: `{timing_hist.get('shared_ctx_s', 0.0):.2f}` sn, birleştirme: `{timing_hist.get('concat_s', 0.0):.2f}` sn)",
        "  - Paket kırılımı: "
        + ", ".join(f"`{k}`: {v:.2f} sn" for k, v in timing_hist.get("blocks", {}).items()),
        f"- **Tek Günlük Program İzole Dilim (`{timing_day['target_date']}`, {timing_day['target_races']} koşu / {timing_day['target_runners']} koşucu):** `{day_s:.3f}` sn",
        f"- **Canlı Bütçe Durumu:** {budget_note}",
        "",
        "### Seçilen Yumuşatma Sabitleri",
        "",
        "| Sabit | Değer | Açıklama |",
        "|---|---:|---|",
        f"| `GPREF_WR_PRIOR_W` / `GPREF_WR_PRIOR_N` | `{SMOOTHING_CONSTANTS['GPREF_WR_PRIOR_W']}` / `{SMOOTHING_CONSTANTS['GPREF_WR_PRIOR_N']}` | Islak pist kazanma oranı Bayes büzülmesi |",
        f"| `GPREF_FPCT_PRIOR_K` / `GPREF_SF_PRIOR_K` | `{SMOOTHING_CONSTANTS['GPREF_FPCT_PRIOR_K']}` / `{SMOOTHING_CONSTANTS['GPREF_SF_PRIOR_K']}` | Islak-kuru bitiriş ve hız puanı farkı etkin örneklem büzülmesi |",
        "",
    ]

    if yearly_cov_rows:
        lines += [
            "### Yıllık V11 Paket Doluluk Oranları (`2015–2026`)",
            "",
            "| Yıl | Koşu | Koşucu | `going_ord` Dolu | `going_wet=1` | `turf_num` Dolu | `wx_temp_c` Dolu | `wx_rainy=1` | `gpref_wet>0` | `gpref_delta` Dolu |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for yr in yearly_cov_rows:
            lines.append(
                f"| {yr['year']} | {yr['races']:,} | {yr['runners']:,} | "
                f"{yr['going_fill']:.1%} | {yr['going_wet']:.1%} | {yr['turf_num']:.1%} | "
                f"{yr['wx_temp']:.1%} | {yr['wx_rainy']:.1%} | {yr['gpref_wet']:.1%} | {yr['gpref_delta']:.1%} |"
            )

    if feat_fill_rows:
        lines += [
            "",
            "### V11 Özellik Doluluk Özeti",
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
        f"- **Aşama B'ye Seçilen Tek Aday:** `{stage3_candidate}`" if stage3_candidate else "- **Aşama B'ye Seçilen Tek Aday:** Yok (**V10 korunur**)",
        "",
        "| Varyant | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-2 | İlk-3 |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    for r in stage1_rows:
        v = r["variant"]
        lines.append(
            f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_1s'))} | "
            f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
        )
    lines.extend(_format_yearly_dll_matrix(stage1_rows, stage1_years, "V10_1s", "Aşama A Yıllık ΔLL(varyant − V10_1s)"))

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
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|",
        ]
        for r in stage2_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_1s'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} |"
            )
        lines.extend(_format_yearly_dll_matrix(stage2_rows, stage2_years, "V10_1s", "Aşama 2 Tanısal Yıllık ΔLL(varyant − V10_1s)"))

    lines += [
        "",
        "## 4. Aşama 3 — Resmi Aşama B Doğrulama Kapısı (`2022–2025`, 5-Tohum + Sıcaklık Kalibrasyonu)",
        "",
        "- **Kapı Kuralı (`evaluate_stage_b_gate`):** `ΔLL(aday − V10_BASE)` için koşu-eşli bootstrap %95 GA üst sınırı `< 0` **VE** `4` yılın en az `3`'ünde `ΔLL < 0`.",
        "",
    ]
    if smoke:
        lines.append("Duman testinde Aşama 3 tam kapı koşusu çalıştırılmadı.")
    elif stage3_candidate is None:
        lines.append(
            f"**KAPI SONUCU:** Aşama A (`2017–2021`) taramasında hiçbir V11 adayı `{SEL_THRESHOLD_DLL:+.4f}` eşiğini geçemediğinden Aşama 3 çalıştırılmadı — **V10 korunur**."
        )
    else:
        lines.append(f"- **Sınanan Tek Aday (`Aşama A` kazananı):** `{stage3_candidate}`")
        lines.append("")
        lines += [
            "| Varyant | Koşu | Log-Loss | ΔLL vs `V10_BASE` (%95 GA) | ΔLL vs `AGF` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-2 | İlk-3 | Kapı Kararı |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
        ]
        for r in stage3_b_rows:
            v = r["variant"]
            if v == "B0":
                g_txt = "Referans (Saf AGF)"
            elif v == "V10_BASE":
                g_txt = "Taban (`V10_CONFIG`)"
            else:
                g_txt = "**GEÇTİ**" if stage3_passed else "**KALDI**"
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_BASE'))} | "
                f"{_fmt_dll_ci(r['dll_b0'], r['dll_b0_lo'], r['dll_b0_hi'], is_self=(v == 'B0'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top2']:.2%} | {r['top3']:.2%} | {g_txt} |"
            )

        if stage3_b_yearly_detail:
            lines += [
                "",
                "### Aşama B Yıllık Ayrıntı (5-Tohum + Sıcaklık Kalibrasyonu)",
                "",
                "| Yıl | Varyant | Koşu | Log-Loss | ΔLL vs `V10_BASE` (%95 GA) | 1. Tercih | İlk-2 | İlk-3 |",
                "|---:|---|---:|---:|---|---:|---:|---:|",
            ]
            for yr_row in stage3_b_yearly_detail:
                v = yr_row["variant"]
                lines.append(
                    f"| {yr_row['year']} | `{v}` | {yr_row['races']} | {yr_row['ll']:.4f} | "
                    f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'V10_BASE'))} | "
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
            lines.append(f"**KAPI SONUCU:** `{stage3_candidate}_CAL` Aşama B sabit kapısını geçemedi — **V10 korunur**.")

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
        base_c = "V10_BASE" if any(r["variant"] == "V10_BASE" for r in stage3_c_rows) else "V10_1s"
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


def format_v11_bulgular_doc(
    *,
    meta,
    timing_hist,
    stage1_rows,
    stage2_rows,
    stage3_candidate,
    stage3_b_rows,
    stage3_b_yearly_detail,
    stage3_passed,
    stage3_c_rows,
    out_report_path,
):
    """Build concise Turkish summary doc (docs/V11_BULGULAR.md)."""
    cand_s = float(timing_hist.get("candidates_total_s", 0.0))
    lines = [
        f"# Model v11 — Pist Durumu ve Hava Bulguları ({pd.Timestamp.now().strftime('%d.%m.%Y')})",
        "",
        f"Ham rapor: `{out_report_path}`. Özellik modülü: `ganyan/features_v11.py`. Deney betiği: `scripts/run_v11_experiments.py`.",
        "",
        "## Sade Özet",
        "",
        "- **Ne sınandı?** `V10_HLB` (`v10_hlb`, 155 özellik) tabanının üstüne **pist durumu** (`GOING`: 5 özellik), **hava** (`WX`: 4 özellik) ve **atın ıslak/kuru pist tercihi** (`GPREF`: 7 özellik) olmak üzere toplam **16 yeni özellik** sınandı.",
        f"- **Süre:** `attach_v11` tam geçmişi (`2006-03-04`→`{meta['db_max_date']}`) **`{cand_s:.2f}` sn** içinde işledi.",
        "- **Sınırlama:** TJK şehir-gün bloğu gün SONU pist ve hava durumudur; canlıda ise koşu anındaki/öncesindeki ilan görülecektir.",
    ]

    if stage3_candidate is None:
        lines.append("- **Sonuç:** Aşama A (`2017–2021`) taramasında hiçbir aday sabit `-0.0002` eşiğinin altına inmedi — **canlıda `V10_HLB` (`v10_hlb`) korunur**.")
    else:
        status_txt = "**GEÇTİ**" if stage3_passed else "**KALDI — `V10_HLB` korunur**"
        lines.append(f"- **Aşama B Kapı Sonucu (`{stage3_candidate}_CAL` vs `V10_BASE`):** {status_txt}")

    lines.extend(["", "## Tablolar", "", "### Aşama A (2017–2021, 1-Tohum)"])
    lines.append("")
    lines.append("| Varyant | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-3 |")
    lines.append("|---|---:|---:|---|---:|---:|---:|")
    for r in stage1_rows:
        v = r["variant"]
        lines.append(
            f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
            f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_1s'))} | "
            f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top3']:.2%} |"
        )

    if stage2_rows:
        lines.extend(["", "### Aşama 2 Tanı (2022–2025, 1-Tohum)", ""])
        lines.append("| Varyant | Koşu | Log-Loss | ΔLL vs `V10_1s` (%95 GA) | Neg. Yıl | 1. Tercih | İlk-3 |")
        lines.append("|---|---:|---:|---|---:|---:|---:|")
        for r in stage2_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_1s'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top3']:.2%} |"
            )

    if stage3_b_rows:
        lines.extend(["", "### Aşama 3 Resmi Kapı (2022–2025, 5-Tohum + Sıcaklık Kalibrasyonu)", ""])
        lines.append("| Varyant | Koşu | Log-Loss | ΔLL vs `V10_BASE` (%95 GA) | Neg. Yıl (/4) | 1. Tercih | İlk-3 |")
        lines.append("|---|---:|---:|---|---:|---:|---:|")
        for r in stage3_b_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == 'V10_BASE'))} | "
                f"{r['neg_years']}/{r['total_years']} | {r['top1']:.2%} | {r['top3']:.2%} |"
            )

    if stage3_b_yearly_detail:
        lines.extend(["", "### Aşama B Yıllık ΔLL", ""])
        lines.append("| Yıl | Varyant | ΔLL vs `V10_BASE` (%95 GA) | 1. Tercih | İlk-3 |")
        lines.append("|---:|---|---|---:|---:|")
        for yr_row in stage3_b_yearly_detail:
            v = yr_row["variant"]
            if v == "B0":
                continue
            lines.append(
                f"| {yr_row['year']} | `{v}` | "
                f"{_fmt_dll_ci(yr_row['dll_e0'], yr_row['dll_e0_lo'], yr_row['dll_e0_hi'], is_self=(v == 'V10_BASE'))} | "
                f"{yr_row['top1']:.2%} | {yr_row['top3']:.2%} |"
            )

    if stage3_c_rows:
        base_c = "V10_BASE" if any(r["variant"] == "V10_BASE" for r in stage3_c_rows) else "V10_1s"
        lines.extend(["", "### 2026 Bilgi Kümesi *(kilit v5'te tüketildi)*", ""])
        lines.append(f"| Varyant | Koşu | Log-Loss | ΔLL vs `{base_c}` (%95 GA) | 1. Tercih | İlk-3 |")
        lines.append("|---|---:|---:|---|---:|---:|")
        for r in stage3_c_rows:
            v = r["variant"]
            lines.append(
                f"| `{v}` | {r['races']} | {r['ll']:.4f} | "
                f"{_fmt_dll_ci(r['dll_e0'], r['dll_e0_lo'], r['dll_e0_hi'], is_self=(v == base_c))} | "
                f"{r['top1']:.2%} | {r['top3']:.2%} |"
            )

    return "\n".join(lines).rstrip() + "\n"


def run_v11_experiments(
    db_path="data/ganyan.db",
    cache_dir="data/v11_cache",
    out_report="reports/V11.md",
    out_docs="docs/V11_BULGULAR.md",
    smoke=False,
    allow_sparse=False,
):
    """Run staged Model v11 experiments (GOING, WX, GPREF) over V10_HLB baseline."""
    smoke = bool(smoke)
    os.makedirs(cache_dir, exist_ok=True)

    conn = _open_ro_db(db_path)
    try:
        runners_df = load_runners_from_db(conn)
        v5_tables = load_v5_tables(conn)
        v11_tables = load_v11_tables(conn)
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
        target_y, shifted = _select_smoke_year(runners_df, v11_tables)
        if shifted:
            print(
                f"[smoke] {SMOKE_TEST_YEAR} yılında pist/hava verisi henüz yüklenmediğinden "
                f"dolu tam yıl seçildi: {target_y}",
                flush=True,
            )
        t_feat0 = time.perf_counter()
        df_sm, v11_timing_sm = _build_v11_history_frame(
            runners_df, v5_tables, v11_tables, max_date=f"{target_y}-12-31"
        )
        print(
            f"[smoke] Özellik inşası tamamlandı (toplam={time.perf_counter() - t_feat0:.1f}sn, "
            f"attach_v11_aday={v11_timing_sm['candidates_total_s']:.2f}sn)",
            flush=True,
        )
        sm_max_day = df_sm["date"].max().strftime("%Y-%m-%d")
        timing_day_sm = _measure_single_day_timing(df_sm, sm_max_day, _slice_v11_tables(v11_tables, max_date=sm_max_day))

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

        feat_fill_rows, yearly_cov_rows = _compute_v11_coverage_tables(df_sm, eval_mask_sm, min_eval_year=target_y)
        dc_sm = v11_tables.get("day_cond") if isinstance(v11_tables, dict) else None
        dc_has_target_y = bool(
            dc_sm is not None
            and len(dc_sm) > 0
            and (pd.to_datetime(dc_sm["date"], errors="coerce").dt.year == int(target_y)).any()
        )
        for blk in V11_CANDIDATE_BLOCKS:
            blk_nz = sum(fr["eval_nonzero"] for fr in feat_fill_rows if fr["block"] == blk)
            if blk == "WX" and not dc_has_target_y:
                wx_fill = max((fr["eval_fill"] for fr in feat_fill_rows if fr["block"] == "WX"), default=0.0)
                if wx_fill > 0.0:
                    raise RuntimeError(f"Smoke testinde day_cond boşken WX kapsamı 0 olmalıydı, gözlenen={wx_fill:.4f}")
                print(
                    "[smoke] Not: day_cond tablosu boş olduğu için WX kapsamı %0.0 "
                    "(yalnız TJK day_cond; --apply sonrası dolacak).",
                    flush=True,
                )
                continue
            if blk_nz <= 0.0:
                raise RuntimeError(f"Smoke testinde Paket {blk} sıfır-dışı kapsamı 0!")

        smoke_extra = {"mode": "smoke_pct20"}
        tracker = _ProgressTracker(total_planned_steps=len(BASE_V11_SPECS))
        preds_sm = {}
        ll_base = None
        for v_name, blks, desc in BASE_V11_SPECS:
            cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc, extra_meta=smoke_extra)
            p_y, dt_s, from_c = _predict_base_year(df_sm, eval_y, cfg, target_y, cache_dir, smoke=True)
            if p_y is None or not np.all(np.isfinite(p_y)):
                raise RuntimeError(f"Smoke {v_name} tahmini geçersiz!")
            preds_sm[v_name] = p_y
            ll_y = _race_winner_lls(eval_y, p_y)
            if v_name == "V10_1s":
                ll_base = ll_y
                dll_val = 0.0
            else:
                dll_val = float((ll_y - ll_base).mean())
            tracker.log_step(v_name, target_y, dt_s, dll_val, from_cache=from_c)

        del df_sm
        gc.collect()

        stage1_rows, _ = _summarize_period_metrics(
            eval_y, preds_sm, [v[0] for v in BASE_V11_SPECS], base_key="V10_1s"
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
        report_md = format_v11_report(
            smoke=True,
            meta=meta,
            timing_hist=v11_timing_sm,
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
            "smoke_year": target_y,
            "report_path": str(out_report),
            "timing": v11_timing_sm,
            "feat_fill_rows": feat_fill_rows,
            "stage1_rows": stage1_rows,
        }

    t_f0 = time.perf_counter()
    print("[v11] Özellik matrisi kuruluyor (2006-03-04→)...", flush=True)
    df_hist, v11_timing_hist = _build_v11_history_frame(runners_df, v5_tables, v11_tables)
    del runners_df, v5_tables
    gc.collect()
    timing_day = _measure_single_day_timing(df_hist, db_max_date, v11_tables)
    print(
        f"[v11] Özellik matrisi hazır ({len(df_hist):,} satır, {len(df_hist.columns)} sütun, "
        f"toplam={time.perf_counter() - t_f0:.1f}sn, attach_v11_aday={v11_timing_hist['candidates_total_s']:.2f}sn, "
        f"kırılım={ {k: round(v, 2) for k, v in v11_timing_hist['blocks'].items()} })",
        flush=True,
    )

    eval_mask = df_hist["_is_eval"]
    if not allow_sparse:
        stage_a_mask = eval_mask & df_hist["_year"].isin(STAGE_A_YEARS)
        if stage_a_mask.any():
            a_going_fill = float(df_hist.loc[stage_a_mask, "going_ord"].notna().mean())
            if a_going_fill < 0.50:
                raise RuntimeError(
                    f"Aşama A (2017–2021) going_ord doluluğu çok düşük ({a_going_fill:.1%} < 50%); "
                    "tarama bitince tools/load_cond.py --apply çalıştırın."
                )

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
    feat_fill_rows, yearly_cov_rows = _compute_v11_coverage_tables(df_hist, eval_mask, min_eval_year=min(stage_a_years))

    est_steps = len(BASE_V11_SPECS) * (len(stage_a_years) + len(stage_b_years)) + 2 * (
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
            if var_name in ("V10_1s", "V10_BASE_5s"):
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
    for v_name, blks, desc in BASE_V11_SPECS:
        cfg = _make_variant_cfg(v_name, blks, seeds=(0,), description=desc)
        stage1_cfgs[v_name] = cfg
        stage1_order.append(v_name)
        _run_years(v_name, cfg, stage_a_years, base_1s_ll_by_year)

    eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
    raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V10_1s")
    by_var_a = {r["variant"]: r for r in raw_a_rows}

    selected_blocks = [
        blk
        for blk in V11_CANDIDATE_BLOCKS
        if f"V11_{blk}" in by_var_a and by_var_a[f"V11_{blk}"]["dll_e0"] < SEL_THRESHOLD_DLL
    ]

    stage3_candidate = None
    sel_run_distinct = False
    if not selected_blocks:
        sel_note = "`V11_SEL` oluşturulmadı — hiçbir tekil paket eşiği geçemedi"
        if by_var_a["V11_ALL"]["dll_e0"] < SEL_THRESHOLD_DLL:
            stage3_candidate = "V11_ALL"
            sel_note += " ama birleşik `V11_ALL` eşiği geçti"
        else:
            sel_note += " (**V10 korunur**)"
    elif len(selected_blocks) == 1:
        only_name = f"V11_{selected_blocks[0]}"
        sel_note = f"`V11_SEL`, tek geçen `{only_name}` ile özdeştir"
        ll_sel = by_var_a[only_name]["ll"]
        ll_all = by_var_a["V11_ALL"]["ll"]
        stage3_candidate = only_name if ll_sel <= ll_all else "V11_ALL"
    elif tuple(selected_blocks) == V11_CANDIDATE_BLOCKS:
        sel_note = "`V11_SEL`, 3 paketin tümünü içeren `V11_ALL` ile özdeştir"
        stage3_candidate = "V11_ALL"
    else:
        sel_run_distinct = True
        sel_desc = f"V10 + seçili paketler ({'+'.join(selected_blocks)})"
        cfg_sel = _make_variant_cfg("V11_SEL", tuple(selected_blocks), seeds=(0,), description=sel_desc)
        stage1_cfgs["V11_SEL"] = cfg_sel
        stage1_order.append("V11_SEL")
        tracker.add_steps(len(stage_a_years) + len(stage_b_years))
        _run_years("V11_SEL", cfg_sel, stage_a_years, base_1s_ll_by_year)
        eval_a_df, preds_a_map = _concat_year_preds(eval_by_year, preds_by_var_year, stage_a_years, stage1_order)
        raw_a_rows, _ = _summarize_period_metrics(eval_a_df, preds_a_map, stage1_order, base_key="V10_1s")
        by_var_a = {r["variant"]: r for r in raw_a_rows}
        ll_sel = by_var_a["V11_SEL"]["ll"]
        ll_all = by_var_a["V11_ALL"]["ll"]
        stage3_candidate = "V11_SEL" if ll_sel <= ll_all else "V11_ALL"
        sel_note = f"`V11_SEL` ({'+'.join(selected_blocks)}) Aşama A'da çalıştırıldı"

    def _order_diag_rows(by_var_map, order_list):
        rows_out = [by_var_map[k] for k in ("B0", "V10_1s") if k in by_var_map]
        rest = [by_var_map[v] for v in order_list if v != "V10_1s" and v in by_var_map]
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
        raw_b_1s, _ = _summarize_period_metrics(eval_b_1s, preds_b_1s, stage1_order, base_key="V10_1s")
        stage2_rows = _order_diag_rows({r["variant"]: r for r in raw_b_1s}, stage1_order)

    # Stage 3 (Aşama 3): Strictly ONE candidate from Stage A vs V10_BASE (5-seed + temperature calibration)
    all_cal_years = sorted(set(warmup_years + stage_a_years + stage_b_years + stage_c_years))
    cal_eval_years = sorted(set(stage_a_years + stage_b_years + stage_c_years))
    stage3_b_rows = []
    stage3_b_yearly_detail = []
    stage3_gate_result = None
    stage3_passed = False
    stage3_c_rows = []
    cal_param_rows = []

    if stage3_candidate is not None:
        seeds_5 = tuple(int(s) for s in V10_CONFIG["seeds"])
        cand_blks = tuple(stage1_cfgs[stage3_candidate]["v11_blocks"])
        stage3_specs = [
            ("V10_BASE", (), "Resmi V10 tabanı (v10_hlb, 5 tohum + sıcaklık)"),
            (stage3_candidate, cand_blks, f"{stage3_candidate} (5 tohum + sıcaklık)"),
        ]

        cal_names = []
        for s3_name, blks, desc in stage3_specs:
            raw_5s_name = f"{s3_name}_5s"
            cal_name = "V10_BASE" if s3_name == "V10_BASE" else f"{s3_name}_CAL"
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
                if cal_name == "V10_BASE":
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
                eval_b_5s, preds_b_5s, cal_names, base_key="V10_BASE"
            )
            for y_b in stage_b_years:
                ev_yb, pr_yb = _concat_year_preds(eval_by_year, preds_by_var_year, [y_b], cal_names)
                yr_rows_b, _ = _summarize_period_metrics(ev_yb, pr_yb, cal_names, base_key="V10_BASE")
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
            stage3_c_rows, _ = _summarize_period_metrics(eval_c_5s, preds_c_5s, cal_names, base_key="V10_BASE")
    elif stage_c_years:
        for v_name in stage1_order:
            _run_years(v_name, stage1_cfgs[v_name], stage_c_years, base_1s_ll_by_year)
        eval_c_1s, preds_c_1s = _concat_year_preds(eval_by_year, preds_by_var_year, stage_c_years, stage1_order)
        raw_c_rows, _ = _summarize_period_metrics(eval_c_1s, preds_c_1s, stage1_order, base_key="V10_1s")
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

    report_md = format_v11_report(
        smoke=False,
        meta=meta,
        timing_hist=v11_timing_hist,
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
    print(f"[v11] Rapor yazıldı: {out_report}", flush=True)

    if out_docs:
        doc_md = format_v11_bulgular_doc(
            meta=meta,
            timing_hist=v11_timing_hist,
            stage1_rows=stage1_rows,
            stage2_rows=stage2_rows,
            stage3_candidate=stage3_candidate,
            stage3_b_rows=stage3_b_rows,
            stage3_b_yearly_detail=stage3_b_yearly_detail,
            stage3_passed=stage3_passed,
            stage3_c_rows=stage3_c_rows,
            out_report_path=out_report,
        )
        doc_dir = os.path.dirname(str(out_docs))
        if doc_dir:
            os.makedirs(doc_dir, exist_ok=True)
        with open(out_docs, "w", encoding="utf-8") as f:
            f.write(doc_md)
        print(f"[v11] Bulgular özeti yazıldı: {out_docs}", flush=True)

    return {
        "smoke": False,
        "report_path": str(out_report),
        "docs_path": str(out_docs) if out_docs else None,
        "stage1_rows": stage1_rows,
        "stage2_rows": stage2_rows,
        "stage3_candidate": stage3_candidate,
        "stage3_passed": stage3_passed,
        "stage3_gate_result": stage3_gate_result,
        "sel_run_distinct": sel_run_distinct,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v11 ileri-yürüyen deney serisi (GOING, WX, GPREF)."
    )
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--cache-dir", default="data/v11_cache")
    ap.add_argument("--out-report", default="reports/V11.md")
    ap.add_argument("--out-docs", default="docs/V11_BULGULAR.md")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--allow-sparse", action="store_true")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    try:
        run_v11_experiments(
            db_path=args.db,
            cache_dir=args.cache_dir,
            out_report=args.out_report,
            out_docs=args.out_docs,
            smoke=args.smoke,
            allow_sparse=args.allow_sparse,
        )
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
