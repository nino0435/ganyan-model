"""Forward-test comparison report (`v7_tcjp` vs `v8_an` vs `v9_kssb` vs `v10_hlb` vs AGF, with archived `v5_sgr_all` and `v6_e5`) -> `reports/FORWARD_V5.md`."""
import argparse
import datetime
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.model_v5 import bootstrap_mean_ci

IST_TZ = ZoneInfo("Europe/Istanbul")
V5_VERSION = "v5_sgr_all"
V6_VERSION = "v6_e5"
V7_VERSION = "v7_tcjp"
V8_VERSION = "v8_an"
V9_VERSION = "v9_kssb"
V10_VERSION = "v10_hlb"
TARGET_MODELS = (V5_VERSION, V6_VERSION, V7_VERSION, V8_VERSION, V9_VERSION, V10_VERSION)
SQL_CHUNK = 500


def _open_ro_db_if_exists(db_path):
    """Open SQLite DB strictly read-only if it exists on disk; otherwise return None."""
    if db_path is None:
        return None
    p = Path(db_path)
    if not p.exists():
        return None
    db_uri = f"{p.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return conn


def _parse_ist_dt(val):
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST_TZ)
        return dt.astimezone(IST_TZ)
    except ValueError:
        return None


def _query_by_race_chunks(conn, sql_template, race_ids):
    """Execute `sql_template` (with `{placeholders}`) in chunks of <= 500 race_ids."""
    rids = [str(r) for r in race_ids]
    if not rids:
        return pd.DataFrame()
    frames = []
    for i in range(0, len(rids), SQL_CHUNK):
        chunk = rids[i : i + SQL_CHUNK]
        ph = ",".join("?" for _ in chunk)
        df_c = pd.read_sql_query(sql_template.format(placeholders=ph), conn, params=tuple(chunk))
        if not df_c.empty:
            frames.append(df_c)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _assign_fallback_prog_no_active(runners_df):
    """Ensure every active runner row has a deterministic unique integer `prog_no` per race."""
    out = runners_df.copy()
    pno = pd.to_numeric(out["prog_no"], errors="coerce")
    if pno.notna().all() and not out.assign(_p=pno).duplicated(["race_id", "_p"]).any():
        out["prog_no"] = pno.astype(int)
        return out
    out["prog_no"] = pno.astype("float64")
    for _rid, grp in out.groupby("race_id", sort=False):
        gp = pd.to_numeric(grp["prog_no"], errors="coerce")
        if gp.notna().all() and gp.nunique() == len(gp):
            out.loc[grp.index, "prog_no"] = np.asarray(gp, dtype=np.float64)
        elif gp.isna().all():
            ordered_idx = grp.sort_values("horse_key", kind="mergesort").index
            out.loc[ordered_idx, "prog_no"] = np.arange(1, len(ordered_idx) + 1, dtype=np.float64)
        else:
            used = set()
            missing_idx = []
            for idx_row in grp.sort_values("horse_key", kind="mergesort").index:
                v = gp.loc[idx_row]
                if pd.notna(v) and int(v) > 0 and int(v) not in used:
                    iv = int(v)
                    used.add(iv)
                    out.loc[idx_row, "prog_no"] = float(iv)
                else:
                    missing_idx.append(idx_row)
            next_p = (max(used) + 1) if used else 1
            for offset, idx_row in enumerate(missing_idx):
                out.loc[idx_row, "prog_no"] = float(next_p + offset)
    out["prog_no"] = out["prog_no"].astype(int)
    return out


def _race_winner_metrics_from_probs(df_race_active, p_series):
    """Compute `(ll, top1, top2, top3)` on a single settled race's active runners."""
    p_num = np.asarray(pd.to_numeric(p_series, errors="coerce"), dtype=np.float64)
    if len(p_num) == 0 or not np.all(np.isfinite(p_num)):
        return None
    s = float(np.sum(p_num))
    if s > 0.0:
        p_norm = p_num / s
    else:
        p_norm = np.full(len(p_num), 1.0 / float(len(p_num)), dtype=np.float64)

    rk = np.asarray(pd.Series(p_norm).rank(ascending=False, method="first"), dtype=np.float64)
    win_mask = np.asarray(pd.to_numeric(df_race_active["finish"], errors="coerce"), dtype=np.float64) == 1.0
    if not np.any(win_mask):
        return None

    ll = float(np.mean(-np.log(np.clip(p_norm[win_mask], 1e-6, None))))
    top1 = float(np.mean(rk[win_mask] <= 1.0))
    top2 = float(np.mean(rk[win_mask] <= 2.0))
    top3 = float(np.mean(rk[win_mask] <= 3.0))
    return {"ll": ll, "top1": top1, "top2": top2, "top3": top3}


def _fmt_dll_ci(diff_arr):
    arr = np.asarray(diff_arr, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return "—", "—"
    m, lo, hi = bootstrap_mean_ci(arr, n_boot=2000, seed=0)
    return f"`{m:+.4f}`", f"`[{lo:+.4f}, {hi:+.4f}]`"


def _format_no_data_report(main_db, forward_db, reason, cov_rows=None):
    lines = [
        "# Ganyan Model v5 / v6 / v7 / v8 / v9 / v10 — İleri Test (Forward) Karşılaştırma Raporu",
        "",
        f"- **Ana Veritabanı:** `{main_db}` (salt-okunur)",
        f"- **İleri-Test Tahmin Veritabanı:** `{forward_db}` (salt-okunur)",
        f"- **Durum:** {reason} — **yeterli veri yok**.",
    ]
    if cov_rows:
        lines += [
            "",
            "## Kayıtlı Tahmin Kapsamı (Henüz Sonuçlanmamış)",
            "",
            "| Model | Kayıtlı Koşu | Kayıtlı Satır | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) |",
            "|---|---:|---:|---|---|",
        ]
        for cr in cov_rows:
            if cr["logged_races"] == 0:
                lines.append(f"| `{cr['model']}` | 0 | 0 | — | — |")
            else:
                lines.append(
                    f"| `{cr['model']}` | {cr['logged_races']} | {cr['logged_rows']} | "
                    f"{cr['s_mean']:.1%} ({cr['s_med']:.1%} / {cr['s_min']:.1%}) | "
                    f"{cr['g_mean']:.1%} ({cr['g_med']:.1%} / {cr['g_min']:.1%}) |"
                )
    return "\n".join(lines).rstrip() + "\n"


def _compute_cov_summary_rows(preds_df, models_order):
    rows = []
    for mv in models_order:
        sub = preds_df[preds_df["model_version"] == mv]
        if sub.empty:
            rows.append(
                {
                    "model": mv,
                    "logged_races": 0,
                    "logged_rows": 0,
                    "min_date": "—",
                    "max_date": "—",
                    "s_mean": np.nan,
                    "s_med": np.nan,
                    "s_min": np.nan,
                    "g_mean": np.nan,
                    "g_med": np.nan,
                    "g_min": np.nan,
                }
            )
            continue
        s_num = pd.to_numeric(sub["s_cov"], errors="coerce")
        g_num = pd.to_numeric(sub["g_cov"], errors="coerce")
        by_race = pd.DataFrame({"race_id": sub["race_id"], "s": s_num, "g": g_num}).groupby(
            "race_id", sort=False
        ).mean()
        s_vals = by_race["s"].dropna().to_numpy(dtype=np.float64)
        g_vals = by_race["g"].dropna().to_numpy(dtype=np.float64)
        s_ids = by_race["s"].dropna().index.to_numpy()
        g_ids = by_race["g"].dropna().index.to_numpy()
        dates = sub["race_id"].astype(str).str[:10]
        rows.append(
            {
                "model": mv,
                "logged_races": int(sub["race_id"].nunique()),
                "logged_rows": int(len(sub)),
                "min_date": str(dates.min()),
                "max_date": str(dates.max()),
                "s_mean": float(np.mean(s_vals)) if len(s_vals) else 0.0,
                "s_med": float(np.median(s_vals)) if len(s_vals) else 0.0,
                "s_min": float(np.min(s_vals)) if len(s_vals) else 0.0,
                "s_min_race": str(s_ids[int(np.argmin(s_vals))]) if len(s_vals) else "—",
                "g_mean": float(np.mean(g_vals)) if len(g_vals) else 0.0,
                "g_med": float(np.median(g_vals)) if len(g_vals) else 0.0,
                "g_min": float(np.min(g_vals)) if len(g_vals) else 0.0,
                "g_min_race": str(g_ids[int(np.argmin(g_vals))]) if len(g_vals) else "—",
            }
        )
    return rows


def _agg_common_metrics(m_dict, rids):
    return {
        "ll": float(np.mean([m_dict[r]["ll"] for r in rids])),
        "top1": float(np.mean([m_dict[r]["top1"] for r in rids])),
        "top2": float(np.mean([m_dict[r]["top2"] for r in rids])),
        "top3": float(np.mean([m_dict[r]["top3"] for r in rids])),
    }


def _append_paired_comparison_tables(
    lines,
    rids,
    methods,
    pairs,
    model_metrics_by_race,
    agf_metrics_by_race,
    ci_subheading=None,
):
    """Append summary table and paired ΔLL + 95% bootstrap CI table for `rids`."""
    n_r = len(rids)
    ll_by_method = {
        "AGF": np.array([agf_metrics_by_race[r]["ll"] for r in rids], dtype=np.float64),
    }
    stats_by_method = {"AGF": _agg_common_metrics(agf_metrics_by_race, rids)}
    for m in methods:
        if m == "AGF":
            continue
        m_dict = model_metrics_by_race[m]
        ll_by_method[m] = np.array([m_dict[r]["ll"] for r in rids], dtype=np.float64)
        stats_by_method[m] = _agg_common_metrics(m_dict, rids)

    lines += [
        "| Yöntem | Koşu | Ort. Log-Loss | 1. Tercih İsabeti | İlk-2 İsabeti | İlk-3 İsabeti |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for m in methods:
        st = stats_by_method[m]
        lines.append(
            f"| `{m}` | {n_r} | {st['ll']:.4f} | {st['top1']:.2%} | {st['top2']:.2%} | {st['top3']:.2%} |"
        )
    lines.append("")
    if ci_subheading:
        lines += [ci_subheading, ""]
    lines += [
        "| Karşılaştırma (Negatif = Sol Model Daha İyi) | Koşu | Eşli Ort. ΔLL | Bootstrap %95 GA |",
        "|---|---:|---:|---|",
    ]
    for lhs, rhs in pairs:
        m_str, ci_str = _fmt_dll_ci(ll_by_method[lhs] - ll_by_method[rhs])
        lines.append(f"| `{lhs} − {rhs}` | {n_r} | {m_str} | {ci_str} |")


def build_forward_v5_report(main_db="data/ganyan.db", forward_db="data/forward_v5.db"):
    """Build Markdown comparison report for active (`v7_tcjp`, `v8_an`, `v9_kssb`, `v10_hlb`) + retired (`v5_sgr_all`, `v6_e5`) vs AGF."""
    f_conn = _open_ro_db_if_exists(forward_db)
    if f_conn is None:
        return _format_no_data_report(main_db, forward_db, "Tahmin veritabanı bulunamadı")

    try:
        f_tables = {
            r[0] for r in f_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "predictions_v5" not in f_tables:
            return _format_no_data_report(main_db, forward_db, "`predictions_v5` tablosu bulunamadı")

        preds_df = pd.read_sql_query(
            """
            SELECT race_id, prog_no, model_version, created_at, minutes_to_post,
                   p_win, agf_used, s_cov, g_cov
            FROM predictions_v5
            """,
            f_conn,
        )
    finally:
        f_conn.close()

    if preds_df.empty:
        return _format_no_data_report(main_db, forward_db, "Kayıtlı ileri-test tahmini bulunmuyor")

    found_models = [str(m) for m in preds_df["model_version"].dropna().unique()]
    models_order = list(TARGET_MODELS) + sorted(m for m in found_models if m not in TARGET_MODELS)
    cov_rows = _compute_cov_summary_rows(preds_df, models_order)

    m_conn = _open_ro_db_if_exists(main_db)
    if m_conn is None:
        return _format_no_data_report(main_db, forward_db, "Ana veritabanı bulunamadı", cov_rows=cov_rows)

    try:
        all_rids = sorted(preds_df["race_id"].dropna().astype(str).unique())
        races_df = _query_by_race_chunks(
            m_conn,
            "SELECT race_id, date, city, race_no, post_time, status FROM races WHERE race_id IN ({placeholders})",
            all_rids,
        )
        runners_df = _query_by_race_chunks(
            m_conn,
            """
            SELECT race_id, prog_no, horse_key, finish, ganyan, agf_close, scratched
            FROM runners
            WHERE race_id IN ({placeholders})
            """,
            all_rids,
        )
        m_tables = {
            r[0] for r in m_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "agf_snapshots" in m_tables:
            snaps_df = _query_by_race_chunks(
                m_conn,
                """
                SELECT race_id, prog_no, captured_at, agf_pct, rowid AS _rid_ord
                FROM agf_snapshots
                WHERE race_id IN ({placeholders}) AND agf_pct > 0
                """,
                all_rids,
            )
        else:
            snaps_df = pd.DataFrame()
    finally:
        m_conn.close()

    if races_df.empty or runners_df.empty:
        return _format_no_data_report(
            main_db, forward_db, "Ana veritabanında eşleşen koşu bulunamadı", cov_rows=cov_rows
        )

    # Filter strictly pre-race predictions (`minutes_to_post >= 0` when present, else `created_at < post_time`)
    race_meta = races_df.drop_duplicates("race_id").set_index("race_id")
    preds_valid = preds_df[preds_df["race_id"].isin(race_meta.index)].copy()
    mtp_num = pd.to_numeric(preds_valid["minutes_to_post"], errors="coerce")
    pt_clean = race_meta["post_time"].replace("", np.nan).fillna("23:59").astype(str)
    post_iso = (
        preds_valid["race_id"].map(race_meta["date"]).astype(str)
        + "T"
        + preds_valid["race_id"].map(pt_clean).astype(str)
    )
    pre_ok = np.where(
        mtp_num.notna(),
        mtp_num >= 0.0,
        preds_valid["created_at"].astype(str).str[:16] < post_iso.str[:16],
    )
    preds_valid = preds_valid[pre_ok].copy()
    if preds_valid.empty:
        return _format_no_data_report(
            main_db, forward_db, "Koşu öncesi geçerli tahmin kaydı bulunamadı", cov_rows=cov_rows
        )

    # Identify settled races (`status == 'result'`, >=2 active runners, >=1 active winner)
    settled_races = set(races_df.loc[races_df["status"].astype(str).str.lower() == "result", "race_id"].astype(str))
    run_settled = runners_df[
        runners_df["race_id"].astype(str).isin(settled_races)
        & (pd.to_numeric(runners_df["scratched"], errors="coerce").fillna(0) == 0)
    ].copy()
    if run_settled.empty:
        return _format_no_data_report(
            main_db, forward_db, "Sonuçlanmış koşu bulunamadı", cov_rows=cov_rows
        )

    run_settled = _assign_fallback_prog_no_active(run_settled)
    run_settled["prog_no"] = pd.to_numeric(run_settled["prog_no"], errors="coerce")
    run_settled["finish"] = pd.to_numeric(run_settled["finish"], errors="coerce")
    run_settled["agf_close"] = pd.to_numeric(run_settled["agf_close"], errors="coerce")

    valid_settled_rids = []
    active_by_race = {}
    for rid, grp in run_settled.groupby("race_id", sort=False):
        if len(grp) < 2 or grp["prog_no"].isna().any():
            continue
        if int((grp["finish"] == 1).sum()) < 1:
            continue
        g_clean = grp.copy()
        g_clean["prog_no"] = g_clean["prog_no"].astype(int)
        active_by_race[str(rid)] = g_clean
        valid_settled_rids.append(str(rid))

    if not valid_settled_rids:
        return _format_no_data_report(
            main_db, forward_db, "Sonuçlanmış geçerli koşu bulunamadı", cov_rows=cov_rows
        )

    # Index snapshots by race_id for fast prediction-time AGF lookup
    snaps_by_race = {}
    if not snaps_df.empty:
        snaps_df = snaps_df.copy()
        snaps_df["prog_no"] = pd.to_numeric(snaps_df["prog_no"], errors="coerce")
        snaps_df["agf_pct"] = pd.to_numeric(snaps_df["agf_pct"], errors="coerce")
        snaps_df = snaps_df[snaps_df["prog_no"].notna() & (snaps_df["agf_pct"] > 0)].copy()
        snaps_df["prog_no"] = snaps_df["prog_no"].astype(int)
        snaps_df["_cap_dt"] = [_parse_ist_dt(x) for x in snaps_df["captured_at"]]
        snaps_df = snaps_df.sort_values(["captured_at", "_rid_ord"], kind="mergesort")
        for rid_s, s_grp in snaps_df.groupby("race_id", sort=False):
            snaps_by_race[str(rid_s)] = s_grp

    # Evaluate per-race metrics for each model and for AGF
    preds_settled = preds_valid[preds_valid["race_id"].astype(str).isin(set(valid_settled_rids))].copy()
    if preds_settled.empty:
        return _format_no_data_report(
            main_db, forward_db, "Sonuçlanmış koşularla eşleşen tahmin bulunamadı", cov_rows=cov_rows
        )

    preds_settled["prog_no"] = pd.to_numeric(preds_settled["prog_no"], errors="coerce")
    preds_settled["agf_used"] = pd.to_numeric(preds_settled["agf_used"], errors="coerce")
    preds_settled = preds_settled[preds_settled["prog_no"].notna()].copy()
    preds_settled["prog_no"] = preds_settled["prog_no"].astype(int)

    # Earliest created_at per race across logged models = prediction cutoff for agf_snapshots
    pred_cutoff_by_race = {}
    post_dt_by_race = {}
    for rid_m in valid_settled_rids:
        if rid_m in race_meta.index:
            d_m = str(race_meta.loc[rid_m, "date"]).strip()
            pt_m = str(pt_clean.loc[rid_m]).strip()
            post_dt_by_race[rid_m] = _parse_ist_dt(f"{d_m}T{pt_m}:00" if len(pt_m) == 5 else f"{d_m}T{pt_m}")
    agf_used_fallback_by_race = {}
    for rid_p, p_grp in preds_settled.groupby("race_id", sort=False):
        dts = [d for d in (_parse_ist_dt(x) for x in p_grp["created_at"]) if d is not None]
        pred_cutoff_by_race[str(rid_p)] = min(dts) if dts else None
        au_sub = p_grp.dropna(subset=["agf_used"])
        if not au_sub.empty:
            agf_used_fallback_by_race[str(rid_p)] = (
                au_sub.groupby("prog_no", sort=False)["agf_used"].first().to_dict()
            )

    agf_metrics_by_race = {}
    agf_source_by_race = {}

    for rid in valid_settled_rids:
        if rid not in pred_cutoff_by_race:
            continue
        act_df = active_by_race[rid]
        pnos = act_df["prog_no"].tolist()

        # 1. Prediction-time AGF from `agf_snapshots` (`captured_at <= prediction_created_at`)
        used_vals = None
        used_src = None
        if rid in snaps_by_race:
            s_grp = snaps_by_race[rid]
            cut_dt = pred_cutoff_by_race.get(rid)
            p_dt = post_dt_by_race.get(rid)
            if s_grp["_cap_dt"].notna().any():
                if p_dt is not None:
                    s_pool = s_grp[s_grp["_cap_dt"].notna() & (s_grp["_cap_dt"] <= p_dt)]
                else:
                    s_pool = s_grp[s_grp["_cap_dt"].notna()]
                if cut_dt is not None and not s_pool.empty:
                    eff_cut = cut_dt + datetime.timedelta(seconds=30)
                    if p_dt is not None and eff_cut > p_dt:
                        eff_cut = p_dt
                    s_pre = s_pool[s_pool["_cap_dt"] <= eff_cut]
                    if s_pre.empty:
                        s_pre = s_pool
                else:
                    s_pre = s_pool
            else:
                s_pre = s_grp
            if not s_pre.empty:
                snap_latest = s_pre.groupby("prog_no", sort=False)["agf_pct"].last().to_dict()
                if all((p in snap_latest and snap_latest[p] > 0) for p in pnos):
                    used_vals = [float(snap_latest[p]) for p in pnos]
                    used_src = "agf_snapshots"

        # 2. Fallback: closing AGF (`runners.agf_close`), or recorded `predictions_v5.agf_used`
        if used_vals is None:
            close_map = dict(zip(act_df["prog_no"], act_df["agf_close"]))
            if all((pd.notna(close_map.get(p)) and float(close_map[p]) > 0) for p in pnos):
                used_vals = [float(close_map[p]) for p in pnos]
                used_src = "agf_close"
            else:
                au_map = agf_used_fallback_by_race.get(rid, {})
                if all((pd.notna(au_map.get(p)) and float(au_map[p]) > 0) for p in pnos):
                    used_vals = [float(au_map[p]) for p in pnos]
                    used_src = "agf_used"

        if used_vals is not None:
            m_agf = _race_winner_metrics_from_probs(act_df, used_vals)
            if m_agf is not None:
                agf_metrics_by_race[rid] = m_agf
                agf_source_by_race[rid] = used_src

    model_metrics_by_race = {mv: {} for mv in models_order}
    for (mv, rid), m_grp in preds_settled.groupby(["model_version", "race_id"], sort=False):
        rid_s = str(rid)
        if mv not in model_metrics_by_race or rid_s not in active_by_race:
            continue
        act_df = active_by_race[rid_s]
        p_map = dict(zip(m_grp["prog_no"], pd.to_numeric(m_grp["p_win"], errors="coerce")))
        pnos = act_df["prog_no"].tolist()
        if not all((p in p_map and pd.notna(p_map[p]) and float(p_map[p]) >= 0.0) for p in pnos):
            continue
        p_vec = [float(p_map[p]) for p in pnos]
        m_res = _race_winner_metrics_from_probs(act_df, p_vec)
        if m_res is not None:
            model_metrics_by_race[mv][rid_s] = m_res

    any_settled_count = sum(len(d) for d in model_metrics_by_race.values())
    if any_settled_count == 0:
        return _format_no_data_report(
            main_db, forward_db, "Modeller için değerlendirilebilir sonuçlanmış koşu yok", cov_rows=cov_rows
        )

    common_active_rids = [
        rid
        for rid in valid_settled_rids
        if rid in model_metrics_by_race.get(V7_VERSION, {})
        and rid in model_metrics_by_race.get(V8_VERSION, {})
        and rid in model_metrics_by_race.get(V9_VERSION, {})
        and rid in model_metrics_by_race.get(V10_VERSION, {})
        and rid in agf_metrics_by_race
    ]
    common_v9_rids = [
        rid
        for rid in valid_settled_rids
        if rid in model_metrics_by_race.get(V6_VERSION, {})
        and rid in model_metrics_by_race.get(V7_VERSION, {})
        and rid in model_metrics_by_race.get(V8_VERSION, {})
        and rid in model_metrics_by_race.get(V9_VERSION, {})
        and rid in agf_metrics_by_race
    ]
    common_v8_rids = [
        rid
        for rid in valid_settled_rids
        if rid in model_metrics_by_race.get(V6_VERSION, {})
        and rid in model_metrics_by_race.get(V7_VERSION, {})
        and rid in model_metrics_by_race.get(V8_VERSION, {})
        and rid in agf_metrics_by_race
    ]
    common_rids = [
        rid
        for rid in valid_settled_rids
        if rid in model_metrics_by_race.get(V5_VERSION, {})
        and rid in model_metrics_by_race.get(V6_VERSION, {})
        and rid in agf_metrics_by_race
    ]
    common_v7_rids = [
        rid
        for rid in valid_settled_rids
        if rid in model_metrics_by_race.get(V5_VERSION, {})
        and rid in model_metrics_by_race.get(V6_VERSION, {})
        and rid in model_metrics_by_race.get(V7_VERSION, {})
        and rid in agf_metrics_by_race
    ]

    # Summarize AGF sources across evaluated settled races (active + V9/V8 transition + legacy union)
    ref_agf_rids = sorted(
        set(common_active_rids) | set(common_v9_rids) | set(common_v8_rids) | set(common_rids)
    ) or sorted(agf_source_by_race)
    n_snap = sum(1 for r in ref_agf_rids if agf_source_by_race.get(r) == "agf_snapshots")
    n_close = sum(1 for r in ref_agf_rids if agf_source_by_race.get(r) == "agf_close")
    n_au = sum(1 for r in ref_agf_rids if agf_source_by_race.get(r) == "agf_used")

    if not ref_agf_rids:
        agf_src_desc = "Eşleşen geçerli AGF kaydı bulunamadı"
    elif n_snap > 0 and n_close == 0 and n_au == 0:
        agf_src_desc = f"`agf_snapshots` (tahmin anındaki AGF — `{n_snap}` / `{len(ref_agf_rids)}` koşunun tamamı)"
    elif n_snap == 0 and n_close > 0 and n_au == 0:
        agf_src_desc = (
            f"Kapanış AGF (`runners.agf_close` — `{n_close}` / `{len(ref_agf_rids)}` koşu; "
            f"`agf_snapshots` tablosunda eşleşen kayıt bulunmadığından yedek kaynak kullanıldı)"
        )
    else:
        agf_src_desc = (
            f"Karma kaynak — tahmin anındaki AGF (`agf_snapshots`): `{n_snap}` koşu, "
            f"kapanış AGF (`runners.agf_close` yedek): `{n_close}` koşu"
            + (f", `predictions_v5.agf_used` yedek: `{n_au}` koşu" if n_au else "")
        )

    lines = [
        "# Ganyan Model v5 / v6 / v7 / v8 / v9 / v10 — İleri Test (Forward) Karşılaştırma Raporu",
        "",
        "> **İstatistiksel Dürüstlük Uyarısı (Küçük Örneklem):** Küçük koşu sayılarında koşu-bazlı bootstrap %95 güven aralıkları (GA) doğal olarak **çok geniştir**; birkaç sürpriz kazanan log-loss farklarını kolayca bir yöne çekebilir. Tarihsel doğrulamada `v6_e5 − v5_sgr_all` farkı yaklaşık `-0.0027` nats, `v7_tcjp − v6_e5` farkı yaklaşık `-0.0019` nats, `v8_an − v7_tcjp` farkı yaklaşık `-0.0027` nats, `v9_kssb − v8_an` farkı yaklaşık `-0.0021` nats, `v10_hlb − v9_kssb` farkı yaklaşık `-0.0009` nats mertebesindedir ve bu ölçekte farkların gürültüden ayrışması binlerce ileri-test koşusu gerektirir (`v5_sgr_all` ve `v6_e5` yeni canlı üretimden emekli edilmiştir; tarihsel kayıtları arşivde korunmaktadır). Aşağıdaki tüm sayılar hiçbir biçimde güzelleştirilmeden ham haliyle verilmiştir.",
        "",
        "## 1. Veri ve AGF Kaynağı Özeti",
        "",
        f"- **Ana Veritabanı:** `{main_db}` (salt-okunur)",
        f"- **İleri-Test Tahmin Veritabanı:** `{forward_db}` (salt-okunur)",
        f"- **Aktif Canlı Eşli Karşılaştırma Koşu Sayısı (`{V7_VERSION}` ∩ `{V8_VERSION}` ∩ `{V9_VERSION}` ∩ `{V10_VERSION}` ∩ `AGF`):** `{len(common_active_rids)}`",
        f"- **V9 Dönemi Eşli Karşılaştırma Koşu Sayısı (`{V6_VERSION}` ∩ `{V7_VERSION}` ∩ `{V8_VERSION}` ∩ `{V9_VERSION}` ∩ `AGF`):** `{len(common_v9_rids)}`",
        f"- **V8 Dönemi Eşli Karşılaştırma Koşu Sayısı (`{V6_VERSION}` ∩ `{V7_VERSION}` ∩ `{V8_VERSION}` ∩ `AGF`):** `{len(common_v8_rids)}`",
        f"- **Üçlü Eşli Karşılaştırma Koşu Sayısı (`{V5_VERSION}` ∩ `{V6_VERSION}` ∩ `AGF`):** `{len(common_rids)}`",
        f"- **Dörtlü Eşli Karşılaştırma Koşu Sayısı (`{V5_VERSION}` ∩ `{V6_VERSION}` ∩ `{V7_VERSION}` ∩ `AGF`):** `{len(common_v7_rids)}`",
        f"- **Kullanılan AGF Kaynağı:** {agf_src_desc}",
        "",
        "## 2. Eşli Performans Karşılaştırması",
        "",
        f"### Aktif Canlı Karşılaştırma (`{V10_VERSION}` vs `{V9_VERSION}` vs `{V8_VERSION}` vs `{V7_VERSION}` vs `AGF`)",
        "",
    ]

    if not common_active_rids:
        lines.append(
            f"Ortak sonuçlanmış aktif canlı koşu sayısı `0` (`{V10_VERSION}` sonuçlanmış: "
            f"`{len(model_metrics_by_race.get(V10_VERSION, {}))}`) — aktif dörtlü eşli karşılaştırma için **yeterli veri yok**."
        )
    else:
        _append_paired_comparison_tables(
            lines,
            common_active_rids,
            methods=["AGF", V7_VERSION, V8_VERSION, V9_VERSION, V10_VERSION],
            pairs=[
                (V10_VERSION, V9_VERSION),
                (V10_VERSION, V8_VERSION),
                (V10_VERSION, V7_VERSION),
                (V10_VERSION, "AGF"),
                (V9_VERSION, V8_VERSION),
                (V9_VERSION, "AGF"),
                (V8_VERSION, V7_VERSION),
                (V8_VERSION, "AGF"),
                (V7_VERSION, "AGF"),
            ],
            model_metrics_by_race=model_metrics_by_race,
            agf_metrics_by_race=agf_metrics_by_race,
            ci_subheading="#### Aktif Canlı Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)",
        )

    lines += [
        "",
        f"### V9 Dönemi Eşli Karşılaştırma (`{V9_VERSION}` vs `{V8_VERSION}` vs `{V7_VERSION}` vs `{V6_VERSION}` vs `AGF`)",
        "",
    ]
    if not common_v9_rids:
        lines.append(
            f"Ortak sonuçlanmış V9 koşu sayısı `0` (`{V9_VERSION}` sonuçlanmış: "
            f"`{len(model_metrics_by_race.get(V9_VERSION, {}))}`) — V9 dönemi eşli karşılaştırma için **yeterli veri yok**."
        )
    else:
        _append_paired_comparison_tables(
            lines,
            common_v9_rids,
            methods=["AGF", V6_VERSION, V7_VERSION, V8_VERSION, V9_VERSION],
            pairs=[
                (V9_VERSION, V8_VERSION),
                (V9_VERSION, V7_VERSION),
                (V9_VERSION, V6_VERSION),
                (V9_VERSION, "AGF"),
                (V8_VERSION, V7_VERSION),
                (V8_VERSION, "AGF"),
                (V7_VERSION, V6_VERSION),
                (V7_VERSION, "AGF"),
                (V6_VERSION, "AGF"),
            ],
            model_metrics_by_race=model_metrics_by_race,
            agf_metrics_by_race=agf_metrics_by_race,
            ci_subheading="#### V9 Dönemi Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)",
        )

    lines += [
        "",
        f"### V8 Dönemi Eşli Karşılaştırma (`{V8_VERSION}` vs `{V7_VERSION}` vs `{V6_VERSION}` vs `AGF`)",
        "",
    ]
    if not common_v8_rids:
        lines.append(
            f"Ortak sonuçlanmış V8 koşu sayısı `0` (`{V8_VERSION}` sonuçlanmış: "
            f"`{len(model_metrics_by_race.get(V8_VERSION, {}))}`) — V8 dönemi eşli karşılaştırma için **yeterli veri yok**."
        )
    else:
        _append_paired_comparison_tables(
            lines,
            common_v8_rids,
            methods=["AGF", V6_VERSION, V7_VERSION, V8_VERSION],
            pairs=[
                (V8_VERSION, V7_VERSION),
                (V8_VERSION, V6_VERSION),
                (V8_VERSION, "AGF"),
                (V7_VERSION, V6_VERSION),
                (V7_VERSION, "AGF"),
                (V6_VERSION, "AGF"),
            ],
            model_metrics_by_race=model_metrics_by_race,
            agf_metrics_by_race=agf_metrics_by_race,
            ci_subheading="#### V8 Dönemi Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)",
        )

    lines += [
        "",
        f"### Tarihsel Arşiv (`{V5_VERSION}` vs `{V6_VERSION}` vs `AGF`)",
        "",
    ]
    if not common_rids:
        lines.append(
            f"Ortak sonuçlanmış koşu sayısı `0` (`{V5_VERSION}` sonuçlanmış: `{len(model_metrics_by_race.get(V5_VERSION, {}))}`, "
            f"`{V6_VERSION}` sonuçlanmış: `{len(model_metrics_by_race.get(V6_VERSION, {}))}`) — "
            "üçlü eşli karşılaştırma için **yeterli veri yok**."
        )
    else:
        _append_paired_comparison_tables(
            lines,
            common_rids,
            methods=["AGF", V5_VERSION, V6_VERSION],
            pairs=[
                (V6_VERSION, V5_VERSION),
                (V6_VERSION, "AGF"),
                (V5_VERSION, "AGF"),
            ],
            model_metrics_by_race=model_metrics_by_race,
            agf_metrics_by_race=agf_metrics_by_race,
            ci_subheading="#### Eşli ΔLL ve Koşu-Bazlı Bootstrap %95 Güven Aralığı (2000 Tekrar, `seed=0`)",
        )

    lines += [
        "",
        f"### V7 Eşli Karşılaştırma (`{V7_VERSION}` vs `{V6_VERSION}` vs `{V5_VERSION}` vs `AGF`)",
        "",
    ]
    if not common_v7_rids:
        lines.append(
            f"Ortak sonuçlanmış V7 koşu sayısı `0` (`{V7_VERSION}` sonuçlanmış: `{len(model_metrics_by_race.get(V7_VERSION, {}))}`) — "
            "dörtlü eşli karşılaştırma için **yeterli veri yok**."
        )
    else:
        _append_paired_comparison_tables(
            lines,
            common_v7_rids,
            methods=["AGF", V5_VERSION, V6_VERSION, V7_VERSION],
            pairs=[
                (V7_VERSION, V6_VERSION),
                (V7_VERSION, V5_VERSION),
                (V7_VERSION, "AGF"),
            ],
            model_metrics_by_race=model_metrics_by_race,
            agf_metrics_by_race=agf_metrics_by_race,
        )

    lines += [
        "",
        "## 3. Model Başına `s_cov` / `g_cov` ve Tekil Performans Özeti",
        "",
        "| Model | Kayıtlı Koşu | Tarih Aralığı | `s_cov` Ort. (Medyan / Min) | `g_cov` Ort. (Medyan / Min) | Sonuçlanmış Koşu | Tekil Ort. LL | 1. Tercih / İlk-2 / İlk-3 | Eşli ΔLL vs AGF (%95 GA) |",
        "|---|---:|---|---|---|---:|---:|---|---|",
    ]
    cov_by_model = {r["model"]: r for r in cov_rows}
    min_cov_notes = []
    for mv in models_order:
        cr = cov_by_model[mv]
        m_map = model_metrics_by_race.get(mv, {})
        paired_agf_rids = [r for r in valid_settled_rids if r in m_map and r in agf_metrics_by_race]
        n_m = len(paired_agf_rids)
        if cr["logged_races"] == 0:
            s_txt = "—"
            g_txt = "—"
            dt_txt = "—"
        else:
            s_txt = f"{cr['s_mean']:.1%} ({cr['s_med']:.1%} / {cr['s_min']:.1%})"
            g_txt = f"{cr['g_mean']:.1%} ({cr['g_med']:.1%} / {cr['g_min']:.1%})"
            dt_txt = f"`{cr['min_date']}`…`{cr['max_date']}`"
            # Min s_cov/g_cov genelde debut/az-koşmuş atların doğal veri azlığıdır
            # (bkz. docs); hangi koşu olduğunu göstermek yanlış "scraper hatası"
            # yorumunu önler.
            if cr["s_min"] < 0.5:
                min_cov_notes.append(f"`{mv}` s_cov min → `{cr['s_min_race']}` ({cr['s_min']:.0%})")
            if cr["g_min"] < 0.5:
                min_cov_notes.append(f"`{mv}` g_cov min → `{cr['g_min_race']}` ({cr['g_min']:.0%})")

        if n_m == 0:
            lines.append(
                f"| `{mv}` | {cr['logged_races']} | {dt_txt} | {s_txt} | {g_txt} | 0 | — | — | — |"
            )
        else:
            m_ll = np.array([m_map[r]["ll"] for r in paired_agf_rids], dtype=np.float64)
            a_ll = np.array([agf_metrics_by_race[r]["ll"] for r in paired_agf_rids], dtype=np.float64)
            t1 = float(np.mean([m_map[r]["top1"] for r in paired_agf_rids]))
            t2 = float(np.mean([m_map[r]["top2"] for r in paired_agf_rids]))
            t3 = float(np.mean([m_map[r]["top3"] for r in paired_agf_rids]))
            d_s, ci_s = _fmt_dll_ci(m_ll - a_ll)
            lines.append(
                f"| `{mv}` | {cr['logged_races']} | {dt_txt} | {s_txt} | {g_txt} | "
                f"{n_m} | {float(m_ll.mean()):.4f} | {t1:.1%} / {t2:.1%} / {t3:.1%} | {d_s} ({ci_s}) |"
            )

    if min_cov_notes:
        lines += [
            "",
            "**Düşük kapsamlı (<%50) koşular** (genelde debut/az-koşmuş at kaynaklı; "
            "scraper arızası değil — bkz. `race_id`):",
            "",
        ]
        lines += [f"- {note}" for note in min_cov_notes]

    return "\n".join(lines).rstrip() + "\n"


def forward_v5_report(
    db_path="data/ganyan.db",
    forward_db_path="data/forward_v5.db",
    out_path="reports/FORWARD_V5.md",
):
    """Generate and write `FORWARD_V5.md`; always succeeds and returns Markdown string."""
    md = build_forward_v5_report(main_db=db_path, forward_db=forward_db_path)
    if out_path:
        parent = os.path.dirname(str(out_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
    return md


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="İleri-test karşılaştırma raporu: v7_tcjp, v8_an, v9_kssb, v10_hlb (+ v5_sgr_all / v6_e5 arşivi) ve AGF -> reports/FORWARD_V5.md"
    )
    ap.add_argument("--db", default="data/ganyan.db", help="Ana SQLite veritabanı yolu (salt-okunur)")
    ap.add_argument(
        "--forward-db",
        "--pred-db",
        "--predictions-db",
        dest="forward_db",
        default="data/forward_v5.db",
        help="İleri-test tahmin SQLite veritabanı yolu (salt-okunur)",
    )
    ap.add_argument("--out", default="reports/FORWARD_V5.md", help="Çıktı Markdown dosyası yolu")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    forward_v5_report(
        db_path=args.db,
        forward_db_path=args.forward_db,
        out_path=args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
