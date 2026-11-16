"""Live forward predictor and backcheck runner for Model v5 (`v5_sgr_all`) and Model v6 (`v6_e5`)."""
import argparse
import datetime
import gc
import os
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan import model_v6 as _model_v6_mod
from ganyan.agf_check import agf_complete
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5, load_v5_tables
from ganyan.live_odds import minutes_to_post
from ganyan.model import fit_predict_df
from ganyan.model_v5 import get_b1x_cols
from ganyan.model_v6 import V6_LIVE_MODEL_VERSION, fit_predict_v6_live
from scripts.snapshot_agf import snapshot_agf

IST_TZ = ZoneInfo("Europe/Istanbul")
MODEL_VERSION = "v5_sgr_all"
V6_MODEL_VERSION = V6_LIVE_MODEL_VERSION
DEFAULT_MODELS = (MODEL_VERSION, V6_MODEL_VERSION)
SUPPORTED_MODELS = (MODEL_VERSION, V6_MODEL_VERSION)
DEFAULT_OUT_DB = "data/forward_v5.db"
DEFAULT_MODEL_CACHE_DIR = "data/forward_models"
REF_END = "2017-01-01"
DEFAULT_TRAIN_START = "2015-01-01"
DEFAULT_DUE_MAX_MIN = 8.0

_ORIG_V6_CONFIG = _model_v6_mod.V6_CONFIG
V6_CONFIG = _ORIG_V6_CONFIG

PREDICTIONS_V5_SQL = """
CREATE TABLE IF NOT EXISTS predictions_v5 (
    race_id TEXT,
    prog_no INTEGER,
    model_version TEXT,
    created_at TEXT,
    minutes_to_post REAL,
    p_win REAL,
    agf_used REAL,
    s_cov REAL,
    g_cov REAL,
    PRIMARY KEY(race_id, prog_no, model_version)
)
"""


def _log(msg):
    hms = datetime.datetime.now(IST_TZ).strftime("%H:%M:%S")
    print(f"[{hms}] {msg}", flush=True)


def _resolve_live_v6_config():
    if V6_CONFIG is not _ORIG_V6_CONFIG:
        return V6_CONFIG
    return _model_v6_mod.V6_CONFIG


def _parse_models(models=None, model_version=None):
    """Normalize `models` (comma string or sequence) or legacy `model_version` into validated list."""
    if models is not None:
        if isinstance(models, str):
            items = [x.strip() for x in models.split(",") if x.strip()]
        else:
            items = [str(x).strip() for x in models if str(x).strip()]
    elif model_version is not None:
        items = [str(model_version).strip()]
    else:
        items = list(DEFAULT_MODELS)

    items = list(dict.fromkeys(items))
    if not items:
        raise ValueError("En az bir model sürümü belirtilmeli.")
    unknown = [m for m in items if m not in SUPPORTED_MODELS]
    if unknown:
        raise ValueError(f"Desteklenmeyen model(ler): {unknown}. Geçerli: {list(SUPPORTED_MODELS)}")
    return items


def _normalize_now(now=None):
    """Return timezone-aware Istanbul datetime from None, ISO string, or datetime."""
    if now is None:
        return datetime.datetime.now(IST_TZ)
    if isinstance(now, str):
        dt_val = datetime.datetime.fromisoformat(now)
    elif isinstance(now, datetime.datetime):
        dt_val = now
    else:
        raise TypeError(f"Geçersiz now değeri: {now!r}")
    if dt_val.tzinfo is None:
        return dt_val.replace(tzinfo=IST_TZ)
    return dt_val.astimezone(IST_TZ)


def init_out_db(out_db=DEFAULT_OUT_DB):
    """Initialize standalone output SQLite DB with WAL, busy_timeout=30000, and predictions_v5 schema."""
    p = str(out_db)
    if p != ":memory:":
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(PREDICTIONS_V5_SQL)
    conn.commit()
    return conn


def _open_ro_db(db_path):
    """Open main SQLite DB strictly read-only so forward_v5 never writes predictions into main_db."""
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"Ana veritabanı bulunamadı: {db_path}")
    db_uri = f"{p.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return conn


def due_races(races, now, date_str=None, due_max_min=DEFAULT_DUE_MAX_MIN, predicted_ids=()):
    """Pure selector for unpredicted non-finished/non-cancelled races in 0 < mtp <= due_max_min.

    ``races`` items may be dicts (``race_id, city, post_time, status[, date]``) or
    tuples ``(race_id, city, post_time[, status])``.
    Returns ``[{"race_id": ..., "city": ..., "post_time": ..., "mtp": ...}, ...]``.
    """
    now_ist = _normalize_now(now)
    ds = str(date_str)[:10] if date_str is not None else now_ist.date().isoformat()
    max_min = float(due_max_min)
    pred_set = set(predicted_ids or ())

    selected = []
    for item in races or ():
        if isinstance(item, dict):
            r_date = item.get("date")
            if r_date is not None and str(r_date)[:10] != ds:
                continue
            race_id = item.get("race_id")
            city = item.get("city")
            post_time = item.get("post_time")
            status = item.get("status")
        else:
            seq = tuple(item)
            race_id = seq[0] if len(seq) > 0 else None
            city = seq[1] if len(seq) > 1 else None
            post_time = seq[2] if len(seq) > 2 else None
            status = seq[3] if len(seq) > 3 else None

        if not race_id or race_id in pred_set:
            continue

        st_norm = str(status).strip().lower() if status is not None else ""
        if st_norm in ("result", "cancelled"):
            continue

        if post_time is None or not str(post_time).strip():
            continue

        try:
            mtp = float(minutes_to_post(now_ist, ds, post_time))
        except (TypeError, ValueError):
            continue

        if 0.0 < mtp <= max_min:
            selected.append(
                {
                    "race_id": str(race_id),
                    "city": city,
                    "post_time": str(post_time).strip(),
                    "mtp": mtp,
                }
            )

    selected.sort(key=lambda d: (d["mtp"], str(d["city"] or ""), d["race_id"]))
    return selected


def _read_day_races(conn, date_str):
    return conn.execute(
        """
        SELECT race_id, city, post_time, status
        FROM races
        WHERE date = ?
        ORDER BY post_time, city, race_no
        """,
        (date_str,),
    ).fetchall()


def _read_predicted_ids(out_conn, model_version=MODEL_VERSION):
    rows = out_conn.execute(
        "SELECT DISTINCT race_id FROM predictions_v5 WHERE model_version = ?",
        (model_version,),
    ).fetchall()
    return {r[0] for r in rows}


def _load_runners_with_today(conn, date_str, overlay_snapshots=True):
    """Tek SQL (forward_log ile aynı): date < bugün ve status='result' + bugünün iptal olmayan program satırları;
    ardından (canlı kipte) son AGF bindirmesi ve bugünün sonuç sütunlarının maskelenmesi."""
    race_cols = {r[1] for r in conn.execute("PRAGMA table_info(races)").fetchall()}
    tc_select = (
        "r.track_cond_raw, r.track_cond,"
        if "track_cond" in race_cols
        else "NULL AS track_cond_raw, NULL AS track_cond,"
    )
    query = f"""
    SELECT
        r.race_id, r.date, r.city, r.race_no, r.post_time, r.yg_no,
        r.cls, r.breed, r.distance, r.surface, r.status,
        {tc_select}
        run.prog_no, run.horse_key, run.name, run.name_raw, run.age, run.sex,
        run.sire, run.dam, run.weight, run.jockey, run.owner, run.trainer,
        run.gate, run.hp, run.son6, run.kgs, run.s20, run.best_time_s,
        run.finish, run.time_s, run.ganyan, run.agf_close, run.agf_close_rank, run.scratched
    FROM races r
    JOIN runners run ON r.race_id = run.race_id
    WHERE (r.date < ? AND r.status = 'result')
       OR (r.date = ? AND COALESCE(r.status, '') != 'cancelled')
    """
    df = pd.read_sql_query(query, conn, params=(date_str, date_str))
    if df.empty or not (df["date"] == date_str).any():
        return pd.DataFrame()

    if overlay_snapshots:
        # Overlay latest positive agf_snapshots for target date (matching scripts/forward_log.py)
        snaps = pd.read_sql_query(
            """
            SELECT s.race_id, s.prog_no, s.agf_pct, s.agf_rank
            FROM agf_snapshots s
            JOIN races r ON s.race_id = r.race_id
            WHERE r.date = ? AND s.agf_pct > 0
            ORDER BY s.captured_at ASC, s.rowid ASC
            """,
            conn,
            params=(date_str,),
        )
        if not snaps.empty:
            latest = snaps.groupby(["race_id", "prog_no"], as_index=False).last()
            snap_map = dict(
                zip(
                    zip(latest["race_id"], latest["prog_no"].astype(int)),
                    latest["agf_pct"],
                )
            )
            mask_today = df["date"] == date_str
            for idx in df[mask_today].index:
                prog_val = df.at[idx, "prog_no"]
                if pd.isna(prog_val):
                    continue
                key = (df.at[idx, "race_id"], int(prog_val))
                if key in snap_map and snap_map[key] is not None:
                    df.at[idx, "agf_close"] = float(snap_map[key])

    # Strictly mask target-day post-race columns before feature engineering
    mask_today = df["date"] == date_str
    df.loc[mask_today, ["finish", "time_s", "ganyan"]] = np.nan
    return df


def _agf_ready_map(today_runners_df, candidate_race_ids):
    """Evaluate agf_complete per candidate race (excluding scratched horses from active check)."""
    cand_set = set(candidate_race_ids)
    sub = today_runners_df[today_runners_df["race_id"].isin(cand_set)]
    if sub.empty:
        return {}
    all_agf = sub.groupby("race_id")["agf_close"].apply(list).to_dict()
    active = sub[pd.to_numeric(sub["scratched"], errors="coerce").fillna(0) == 0]
    if active.empty:
        return {}
    ready = {}
    for rid, grp in active.groupby("race_id"):
        ready[rid] = bool(agf_complete(grp["agf_close"].tolist(), all_agf.get(rid)))
    return ready


def _filter_v5_tables_pre_day(tables, df, ds):
    """Restrict external ratings and workouts strictly to races/dates `< ds`."""
    today_ts = pd.Timestamp(ds)
    dt = pd.to_datetime(df["date"], errors="coerce")
    ext_df = tables["ext"]
    if len(ext_df) > 0:
        hist_rids = set(df.loc[dt < today_ts, "race_id"].astype(str))
        ext_df = ext_df[ext_df["race_id"].astype("string").isin(hist_rids)].copy()
    w_df = tables["workouts"]
    if len(w_df) > 0:
        w_dt = pd.to_datetime(w_df["date"], errors="coerce")
        w_df = w_df[w_dt < today_ts].copy()
    return {"ext": ext_df, "workouts": w_df}


def _prepare_v6_inputs(df, tables, ds, v6_cfg, check_only=False):
    """Align V6 feature history (`history_start='2006-03-04'`) and historical unfinished-race filter
    with `scripts/run_v6_experiments.py` (E0 / E5_best_temp).

    Returns `(df_v6, tables_v6, can_share_v5_feat_df)`.
    When `df` contains no rows before `history_start`, no unfinished historical races, and no extra V6
    blocks, returns `(df, tables, True)` so `build_features` + `attach_v5` runs only once.
    """
    hist_start = str(v6_cfg.get("history_start", "2006-03-04"))
    start_ts = pd.Timestamp(hist_start)
    today_ts = pd.Timestamp(ds)
    dt = pd.to_datetime(df["date"], errors="coerce")

    is_hist = dt < today_ts
    is_today = dt == today_ts

    if is_hist.any():
        hist_sub = df.loc[is_hist]
        scr = (
            pd.to_numeric(hist_sub["scratched"], errors="coerce").fillna(0)
            if "scratched" in hist_sub.columns
            else pd.Series(0, index=hist_sub.index)
        )
        fin = pd.to_numeric(hist_sub["finish"], errors="coerce")
        act_fin = (scr == 0) & fin.notna()
        hist_race_ok = act_fin.groupby(hist_sub["race_id"], sort=False).transform("any")
        hist_date_ok = dt.loc[is_hist] >= start_ts
        use_date_cut = bool((hist_race_ok & hist_date_ok).any() or not hist_race_ok.any())
        hist_keep = (hist_race_ok & hist_date_ok) if use_date_cut else hist_race_ok
    else:
        use_date_cut = True
        hist_keep = pd.Series(dtype=bool)

    keep_mask = np.zeros(len(df), dtype=bool)
    keep_mask[np.asarray(is_today, dtype=bool)] = True
    if len(hist_keep) > 0:
        keep_mask[np.asarray(is_hist, dtype=bool)] = np.asarray(hist_keep, dtype=bool)

    w_df = tables["workouts"]
    if len(w_df) > 0 and use_date_cut:
        w_dt = pd.to_datetime(w_df["date"], errors="coerce")
        w_keep = np.asarray(w_dt >= start_ts, dtype=bool)
    else:
        w_keep = np.ones(len(w_df), dtype=bool)

    extra_blocks = tuple(v6_cfg.get("extra_blocks") or ())
    can_share = bool(keep_mask.all() and np.all(w_keep) and not extra_blocks)
    if can_share or check_only:
        return (df if can_share else None), (tables if can_share else None), can_share

    df_v6 = df.loc[keep_mask].copy()
    dt_v6 = pd.to_datetime(df_v6["date"], errors="coerce")
    kept_hist_rids = set(df_v6.loc[dt_v6 < today_ts, "race_id"].astype(str))
    ext_df = tables["ext"]
    ext_v6 = (
        ext_df[ext_df["race_id"].astype("string").isin(kept_hist_rids)].copy()
        if len(ext_df) > 0
        else ext_df
    )
    w_v6 = w_df.loc[w_keep].copy() if len(w_df) > 0 else w_df
    return df_v6, {"ext": ext_v6, "workouts": w_v6}, False


def _fit_predict_v5_from_feat(feat_df, ds, train_start, target_race_ids):
    """Exact `v5_sgr_all` training slice and single-seed HGB prediction on `feat_df`."""
    train_ts = pd.Timestamp(train_start)
    today_ts = pd.Timestamp(ds)
    ok_train = (
        (feat_df["date"] >= train_ts)
        & (feat_df["date"] < today_ts)
        & feat_df["agf_share"].notna()
        & feat_df["win"].notna()
    )
    train_df = feat_df[ok_train]
    if train_df.empty or (train_df["finish"] == 1).nunique() < 2:
        _log(f"UYARI ({MODEL_VERSION}): eğitim verisi yetersiz (satır={len(train_df)})")
        return None

    today_df = feat_df[(feat_df["date"] == today_ts) & feat_df["race_id"].isin(list(target_race_ids))].copy()
    if today_df.empty:
        return None

    cols = get_b1x_cols("B1_SGR")
    today_df["p_win"] = fit_predict_df(train_df, today_df, cols)
    keep_cols = [
        c
        for c in ("race_id", "prog_no", "horse_key", "gate", "agf_close", "yb_hiz_last", "g_days_last", "p_win")
        if c in today_df.columns
    ]
    return today_df[keep_cols].copy()


def _fit_predict_v6_from_feat(feat_df, ds, train_start, target_race_ids, v6_cfg, cache_path=None):
    """Exact `v6_e5` training slice (`_has_race_win` + `require_agf`) and 5-seed + gamma prediction."""
    train_ts = pd.Timestamp(train_start)
    today_ts = pd.Timestamp(ds)
    has_race_win = feat_df.groupby("race_id", sort=False)["win"].transform("sum") >= 1
    ok_train = (
        (feat_df["date"] >= train_ts)
        & (feat_df["date"] < today_ts)
        & feat_df["win"].notna()
        & has_race_win
    )
    if v6_cfg.get("require_agf", True):
        ok_train = ok_train & feat_df["agf_share"].notna()

    train_df = feat_df[ok_train]
    if train_df.empty or (train_df["finish"] == 1).nunique() < 2:
        _log(f"UYARI ({V6_MODEL_VERSION}): eğitim verisi yetersiz (satır={len(train_df)})")
        return None

    today_df = feat_df[(feat_df["date"] == today_ts) & feat_df["race_id"].isin(list(target_race_ids))].copy()
    if today_df.empty:
        return None

    today_df["p_win"] = fit_predict_v6_live(
        train_df,
        today_df,
        config=v6_cfg,
        year=int(today_ts.year),
        cache_path=cache_path,
        cache_meta={"date": ds, "train_start": str(train_start)},
        warn_fn=_log,
    )
    keep_cols = [
        c
        for c in ("race_id", "prog_no", "horse_key", "gate", "agf_close", "yb_hiz_last", "g_days_last", "p_win")
        if c in today_df.columns
    ]
    return today_df[keep_cols].copy()


def _predict_models_core(df, tables, ds, train_start, race_ids_by_model, cache_dir=None, main_db=None):
    """Shared feature-building and model-prediction pipeline for both `run_once` and `run_backcheck`.

    Isolates errors per model so a failure in one model never blocks the other.
    Shares `feat_df` when `df` already matches V6's `history_start` window; otherwise frees `feat_v5`
    before building V6's `2006-03-04+` feature frame so peak memory stays <= ~5 GB (<< 12 GB).
    """
    preds_by_model = {}
    errors_by_model = {}

    need_v5 = bool(race_ids_by_model.get(MODEL_VERSION))
    need_v6 = bool(race_ids_by_model.get(V6_MODEL_VERSION))
    shared_feat = None

    if need_v5:
        feat_v5 = None
        try:
            feat_v5 = build_features(df, ref_end=REF_END)
            feat_v5 = attach_v5(feat_v5, tables, blocks=("S", "G", "R"))
            if need_v6:
                try:
                    v6_peek = _resolve_live_v6_config()
                    if v6_peek is not None:
                        _, _, can_share = _prepare_v6_inputs(df, tables, ds, v6_peek, check_only=True)
                        if can_share:
                            shared_feat = feat_v5
                except Exception:
                    pass
            pred_v5 = _fit_predict_v5_from_feat(
                feat_v5,
                ds=ds,
                train_start=train_start,
                target_race_ids=race_ids_by_model[MODEL_VERSION],
            )
            if pred_v5 is not None and not pred_v5.empty:
                preds_by_model[MODEL_VERSION] = pred_v5
        except Exception as exc:
            errors_by_model[MODEL_VERSION] = exc
            _log(f"HATA ({MODEL_VERSION}): {exc}")
        finally:
            if shared_feat is None and feat_v5 is not None:
                del feat_v5
                gc.collect()

    if need_v6:
        feat_v6 = None
        try:
            v6_cfg = _resolve_live_v6_config()
            if v6_cfg is None:
                raise ValueError("V6_CONFIG tanımlı değil (None).")
            if shared_feat is not None:
                feat_v6 = shared_feat
                shared_feat = None
            else:
                df_v6, tables_v6, _ = _prepare_v6_inputs(df, tables, ds, v6_cfg)
                feat_v6 = build_features(df_v6, ref_end=REF_END)
                del df_v6
                feat_v6 = attach_v5(feat_v6, tables_v6, blocks=("S", "G", "R"))
                del tables_v6
                extra_blocks = tuple(v6_cfg.get("extra_blocks") or ())
                if extra_blocks:
                    from ganyan.features_v6 import attach_v6, load_v6_tables

                    feat_v6 = attach_v6(feat_v6, load_v6_tables(main_db), blocks=extra_blocks)

            c_path = (
                os.path.join(str(cache_dir), f"{ds}_{V6_MODEL_VERSION}.pkl")
                if cache_dir
                else None
            )
            pred_v6 = _fit_predict_v6_from_feat(
                feat_v6,
                ds=ds,
                train_start=train_start,
                target_race_ids=race_ids_by_model[V6_MODEL_VERSION],
                v6_cfg=v6_cfg,
                cache_path=c_path,
            )
            if pred_v6 is not None and not pred_v6.empty:
                preds_by_model[V6_MODEL_VERSION] = pred_v6
        except Exception as exc:
            errors_by_model[V6_MODEL_VERSION] = exc
            _log(f"HATA ({V6_MODEL_VERSION}): {exc}")
        finally:
            shared_feat = None
            if feat_v6 is not None:
                del feat_v6
            gc.collect()

    return preds_by_model, errors_by_model


def _assign_fallback_prog_no(df_sub):
    """Ensure every row has a deterministic unique integer `prog_no` per race."""
    out = df_sub.copy()
    pno_num = pd.to_numeric(out["prog_no"], errors="coerce")
    if pno_num.notna().all() and not out.assign(_p=pno_num).duplicated(["race_id", "_p"]).any():
        out["prog_no"] = pno_num.astype(int)
        return out
    out["prog_no"] = pno_num.astype("float64")
    for _rid, grp in out.groupby("race_id", sort=False):
        g_pno = pd.to_numeric(grp["prog_no"], errors="coerce")
        if g_pno.notna().all() and g_pno.nunique() == len(g_pno):
            out.loc[grp.index, "prog_no"] = np.asarray(g_pno, dtype=np.float64)
        elif g_pno.isna().all():
            ordered_idx = grp.sort_values("horse_key", kind="mergesort").index
            out.loc[ordered_idx, "prog_no"] = np.arange(1, len(ordered_idx) + 1, dtype=np.float64)
        else:
            used = set()
            missing_idx = []
            for idx_row in grp.sort_values("horse_key", kind="mergesort").index:
                v = g_pno.loc[idx_row]
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


def _write_model_predictions(
    out_conn,
    pred_df,
    model_version,
    created_at_by_race,
    mtp_by_race,
    allow_fallback_prog_no=False,
):
    """Write a single model's predictions into `predictions_v5`; returns newly inserted row count."""
    work = _assign_fallback_prog_no(pred_df) if allow_fallback_prog_no else pred_df
    s_cov_by_race = (
        work.groupby("race_id")["yb_hiz_last"].apply(lambda s: float(s.notna().mean())).to_dict()
    )
    g_cov_by_race = (
        work.groupby("race_id")["g_days_last"].apply(lambda s: float(s.notna().mean())).to_dict()
    )

    cur = out_conn.cursor()
    written = 0
    for _, r in work.iterrows():
        if pd.isna(r["prog_no"]):
            continue
        rid = r["race_id"]
        c_at = created_at_by_race[rid] if isinstance(created_at_by_race, dict) else str(created_at_by_race)
        cur.execute(
            """
            INSERT OR IGNORE INTO predictions_v5 (
                race_id, prog_no, model_version, created_at, minutes_to_post,
                p_win, agf_used, s_cov, g_cov
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                int(r["prog_no"]),
                model_version,
                c_at,
                float(mtp_by_race[rid]),
                float(r["p_win"]),
                float(r["agf_close"]) if pd.notna(r["agf_close"]) else None,
                s_cov_by_race.get(rid, 0.0),
                g_cov_by_race.get(rid, 0.0),
            ),
        )
        written += cur.rowcount
    out_conn.commit()
    return written, s_cov_by_race, g_cov_by_race


def run_once(
    now=None,
    date_str=None,
    main_db="data/ganyan.db",
    out_db=DEFAULT_OUT_DB,
    train_start=DEFAULT_TRAIN_START,
    due_max_min=DEFAULT_DUE_MAX_MIN,
    prog_dir="data/raw/program",
    do_snapshot=True,
    model_version=None,
    models=None,
    cache_dir=DEFAULT_MODEL_CACHE_DIR,
) -> int:
    """Run a single forward check-and-predict pass for active models; returns newly written row count."""
    active_models = _parse_models(models=models, model_version=model_version)
    now_ist = _normalize_now(now)
    ds = str(date_str)[:10] if date_str is not None else now_ist.date().isoformat()
    created_at = now_ist.isoformat(timespec="seconds")

    if not os.path.exists(str(main_db)):
        _log(f"UYARI: ana veritabanı bulunamadı ({main_db})")
        return 0

    out_conn = init_out_db(out_db)
    try:
        pred_ids_by_model = {
            mv: _read_predicted_ids(out_conn, model_version=mv) for mv in active_models
        }

        ro_conn = _open_ro_db(main_db)
        try:
            day_races = _read_day_races(ro_conn, ds)
        finally:
            ro_conn.close()

        due_by_model = {
            mv: due_races(
                day_races,
                now=now_ist,
                date_str=ds,
                due_max_min=due_max_min,
                predicted_ids=pred_ids_by_model[mv],
            )
            for mv in active_models
        }
        if not any(due_by_model.values()):
            return 0

        if do_snapshot:
            cities = sorted(
                {d["city"] for mv in active_models for d in due_by_model[mv] if d.get("city")}
            )
            if cities:
                try:
                    snapshot_agf(ds, db_path=main_db, prog_dir=prog_dir, cities=cities)
                except Exception as exc:
                    _log(f"UYARI: snapshot_agf başarısız ({ds}, {cities}): {exc}")
            if now is None:
                created_at = datetime.datetime.now(IST_TZ).isoformat(timespec="seconds")

        ro_conn = _open_ro_db(main_db)
        try:
            day_races = _read_day_races(ro_conn, ds)
            due_by_model = {
                mv: due_races(
                    day_races,
                    now=now_ist,
                    date_str=ds,
                    due_max_min=due_max_min,
                    predicted_ids=pred_ids_by_model[mv],
                )
                for mv in active_models
            }
            if not any(due_by_model.values()):
                return 0
            df = _load_runners_with_today(ro_conn, ds, overlay_snapshots=True)
            if df.empty:
                return 0
            raw_tables = load_v5_tables(ro_conn)
        finally:
            ro_conn.close()

        union_due_ids = list(
            dict.fromkeys(d["race_id"] for mv in active_models for d in due_by_model[mv])
        )
        ready_map = _agf_ready_map(df[df["date"] == ds], union_due_ids)
        ready_due_by_model = {
            mv: [d for d in due_by_model[mv] if ready_map.get(d["race_id"], False)]
            for mv in active_models
        }
        if not any(ready_due_by_model.values()):
            return 0

        tables = _filter_v5_tables_pre_day(raw_tables, df, ds)
        del raw_tables

        race_ids_by_model = {
            mv: [d["race_id"] for d in ready_due_by_model[mv]]
            for mv in active_models
            if ready_due_by_model[mv]
        }
        preds_by_model, _ = _predict_models_core(
            df,
            tables,
            ds=ds,
            train_start=train_start,
            race_ids_by_model=race_ids_by_model,
            cache_dir=cache_dir,
            main_db=main_db,
        )

        total_written = 0
        for mv in active_models:
            pred_df = preds_by_model.get(mv)
            ready_due = ready_due_by_model.get(mv) or []
            if pred_df is None or pred_df.empty or not ready_due:
                continue
            try:
                mtp_by_race = {d["race_id"]: float(d["mtp"]) for d in ready_due}
                written_mv, s_cov_by_race, g_cov_by_race = _write_model_predictions(
                    out_conn,
                    pred_df,
                    model_version=mv,
                    created_at_by_race=created_at,
                    mtp_by_race=mtp_by_race,
                    allow_fallback_prog_no=False,
                )
                total_written += written_mv
                if written_mv:
                    desc = ", ".join(
                        f"{d['city']} {d['post_time']} (mtp={d['mtp']:.1f}m, S={s_cov_by_race.get(d['race_id'], 0.0):.0%}, G={g_cov_by_race.get(d['race_id'], 0.0):.0%})"
                        for d in ready_due
                    )
                    _log(f"{mv}: {len(ready_due)} koşu için {written_mv} tahmin yazıldı [{desc}]")
            except Exception as exc:
                _log(f"HATA ({mv} DB yazımı): {exc}")

        return total_written
    finally:
        out_conn.close()


def _prepost_iso_for_race(ds, post_time, minutes_before=5):
    """Build deterministic pre-race ISO timestamp on `ds` (`post_time - minutes_before`)."""
    if post_time and ":" in str(post_time):
        try:
            hh_s, mm_s = str(post_time).strip().split(":", 1)
            base_dt = datetime.datetime.fromisoformat(f"{ds}T{int(hh_s):02d}:{int(mm_s):02d}:00").replace(
                tzinfo=IST_TZ
            )
            return (base_dt - datetime.timedelta(minutes=int(minutes_before))).isoformat(timespec="seconds")
        except ValueError:
            pass
    return f"{ds}T00:00:00+03:00"


def _compute_settled_metrics(eval_df, p_col):
    """Compute per-race mean log-loss and top-1 hit rate across settled races (`finish == 1`)."""
    work = eval_df[["race_id", "finish", p_col]].copy()
    work["rk"] = work.groupby("race_id", sort=False)[p_col].rank(ascending=False, method="first")
    winners = work[work["finish"] == 1].copy()
    winners["ll"] = -np.log(np.clip(winners[p_col].to_numpy(dtype=np.float64), 1e-6, None))
    winners["top1"] = (winners["rk"].to_numpy(dtype=np.float64) <= 1.0).astype(np.float64)
    by_race = winners.groupby("race_id", sort=False)[["ll", "top1"]].mean()
    return float(by_race["ll"].mean()), float(by_race["top1"].mean())


def run_backcheck(
    date_str,
    main_db="data/ganyan.db",
    out_db=None,
    train_start=DEFAULT_TRAIN_START,
    models=None,
    cache_dir=None,
):
    """Retrospective real-data audit for settled races on `date_str` ('as if trained yesterday evening').

    Uses the exact same `_load_runners_with_today`, `_filter_v5_tables_pre_day`, and
    `_predict_models_core` functions as live `run_once` (zero duplicated feature/model logic).
    Performs zero network calls and writes to `out_db` if and only if `out_db` is provided.
    """
    ds = datetime.date.fromisoformat(str(date_str)[:10]).isoformat()
    active_models = _parse_models(models=models)

    ro_conn = _open_ro_db(main_db)
    try:
        gt_df = pd.read_sql_query(
            """
            SELECT
                r.race_id, r.date, r.city, r.race_no, r.post_time, r.status,
                run.prog_no, run.horse_key, run.finish, run.agf_close, run.scratched
            FROM races r
            JOIN runners run ON r.race_id = run.race_id
            WHERE r.date = ?
            ORDER BY r.city, r.race_no, run.horse_key
            """,
            ro_conn,
            params=(ds,),
        )
        if gt_df.empty:
            raise ValueError(f"{ds} tarihinde veritabanında koşu bulunamadı.")
        df = _load_runners_with_today(ro_conn, ds, overlay_snapshots=False)
        if df.empty:
            raise ValueError(f"{ds} tarihi için koşucu verisi yüklenemedi.")
        raw_tables = load_v5_tables(ro_conn)
    finally:
        ro_conn.close()

    eval_rids = []
    post_time_by_race = {}
    skipped_unfinished = 0
    skipped_no_agf = 0

    for rid, grp in gt_df.groupby("race_id", sort=False):
        st_norm = str(grp["status"].iloc[0] or "").strip().lower()
        if st_norm != "result":
            skipped_unfinished += 1
            continue
        act = grp[pd.to_numeric(grp["scratched"], errors="coerce").fillna(0) == 0]
        fin = pd.to_numeric(act["finish"], errors="coerce")
        if len(act) < 2 or int((fin == 1).sum()) < 1:
            skipped_unfinished += 1
            continue
        agf_c = pd.to_numeric(act["agf_close"], errors="coerce")
        if not (agf_c.notna().all() and bool((agf_c > 0).all())):
            skipped_no_agf += 1
            continue
        eval_rids.append(str(rid))
        post_time_by_race[str(rid)] = grp["post_time"].iloc[0]

    if not eval_rids:
        raise ValueError(
            f"{ds} tarihinde değerlendirilebilir sonuçlanmış koşu bulunamadı "
            f"(atlanan_sonuclanmamis={skipped_unfinished}, atlanan_agfsiz={skipped_no_agf})."
        )

    tables = _filter_v5_tables_pre_day(raw_tables, df, ds)
    del raw_tables

    race_ids_by_model = {mv: list(eval_rids) for mv in active_models}
    preds_by_model, errors_by_model = _predict_models_core(
        df,
        tables,
        ds=ds,
        train_start=train_start,
        race_ids_by_model=race_ids_by_model,
        cache_dir=cache_dir,
        main_db=main_db,
    )
    del df, tables
    gc.collect()

    if errors_by_model:
        err_desc = "; ".join(f"{k}: {v}" for k, v in errors_by_model.items())
        raise RuntimeError(f"Model hatası oluştu: {err_desc}")

    gt_act = gt_df[
        gt_df["race_id"].isin(set(eval_rids))
        & (pd.to_numeric(gt_df["scratched"], errors="coerce").fillna(0) == 0)
    ].copy()
    gt_act["finish"] = pd.to_numeric(gt_act["finish"], errors="coerce")
    gt_act["agf_close"] = pd.to_numeric(gt_act["agf_close"], errors="coerce")
    agf_sum = gt_act.groupby("race_id", sort=False)["agf_close"].transform("sum")
    gt_act["p_agf"] = gt_act["agf_close"] / agf_sum

    if not np.all(np.isfinite(gt_act["p_agf"].to_numpy(dtype=np.float64))):
        raise RuntimeError("AGF olasılıklarında NaN/inf saptandı.")
    agf_race_sums = gt_act.groupby("race_id", sort=False)["p_agf"].sum().to_numpy(dtype=np.float64)
    if not np.all(np.abs(agf_race_sums - 1.0) <= 1e-6):
        raise RuntimeError(f"AGF koşu içi olasılık toplamı 1±1e-6 dışında: {agf_race_sums}")

    for mv in active_models:
        pred_df = preds_by_model.get(mv)
        if pred_df is None or pred_df.empty:
            raise RuntimeError(f"{mv} için tahmin üretilemedi.")
        sub_p = pred_df[["race_id", "horse_key", "p_win"]].rename(columns={"p_win": f"p_{mv}"})
        gt_act = gt_act.merge(sub_p, on=["race_id", "horse_key"], how="left")
        p_arr = gt_act[f"p_{mv}"].to_numpy(dtype=np.float64)
        if not np.all(np.isfinite(p_arr)):
            raise RuntimeError(f"{mv} tahminlerinde NaN veya sonsuz değer saptandı.")
        race_sums = gt_act.groupby("race_id", sort=False)[f"p_{mv}"].sum().to_numpy(dtype=np.float64)
        max_dev = float(np.max(np.abs(race_sums - 1.0)))
        if max_dev > 1e-6:
            raise RuntimeError(f"{mv} koşu içi olasılık toplamı 1±1e-6 dışında (max_sapma={max_dev:.3e}).")

    written_out = 0
    if out_db is not None:
        created_by_race = {
            rid: _prepost_iso_for_race(ds, post_time_by_race.get(rid), minutes_before=5)
            for rid in eval_rids
        }
        mtp_by_race = {rid: 5.0 for rid in eval_rids}
        out_conn = init_out_db(out_db)
        try:
            for mv in active_models:
                w_mv, _, _ = _write_model_predictions(
                    out_conn,
                    preds_by_model[mv],
                    model_version=mv,
                    created_at_by_race=created_by_race,
                    mtp_by_race=mtp_by_race,
                    allow_fallback_prog_no=True,
                )
                written_out += w_mv
        finally:
            out_conn.close()

    n_races = len(eval_rids)
    agf_ll, agf_top1 = _compute_settled_metrics(gt_act, "p_agf")
    if not (np.isfinite(agf_ll) and np.isfinite(agf_top1)):
        raise RuntimeError("AGF log-loss sonlu değil.")

    model_metrics = {}
    for mv in active_models:
        m_ll, m_top1 = _compute_settled_metrics(gt_act, f"p_{mv}")
        if not (np.isfinite(m_ll) and np.isfinite(m_top1)):
            raise RuntimeError(f"{mv} log-loss sonlu değil ({m_ll}).")
        model_metrics[mv] = {"log_loss": m_ll, "top1": m_top1}

    spearman_rho = None
    spearman_const = False
    if MODEL_VERSION in active_models and V6_MODEL_VERSION in active_models:
        p5 = gt_act[f"p_{MODEL_VERSION}"].to_numpy(dtype=np.float64)
        p6 = gt_act[f"p_{V6_MODEL_VERSION}"].to_numpy(dtype=np.float64)
        if len(p5) >= 2 and np.ptp(p5) > 0.0 and np.ptp(p6) > 0.0:
            spearman_rho = float(spearmanr(p6, p5).statistic)
            if not np.isfinite(spearman_rho):
                raise RuntimeError("v6↔v5 Spearman korelasyonu sonlu değil.")
        else:
            spearman_rho = 0.0
            spearman_const = True

    _log(
        f"backcheck tarih={ds} kosu={n_races} kosucu={len(gt_act)} "
        f"atlanan_sonuclanmamis={skipped_unfinished} atlanan_agfsiz={skipped_no_agf}"
        + (f" yazilan_satir={written_out}" if out_db is not None else "")
    )
    print(f"  AGF (kapanış) : kosu={n_races}  log_loss={agf_ll:.4f}  top1={agf_top1:.2%}", flush=True)
    for mv in active_models:
        mm = model_metrics[mv]
        print(
            f"  {mv:<13} : kosu={n_races}  log_loss={mm['log_loss']:.4f}  top1={mm['top1']:.2%}",
            flush=True,
        )
    if spearman_rho is not None:
        const_note = " (sabit dizi)" if spearman_const else ""
        print(
            f"  spearman({V6_MODEL_VERSION}, {MODEL_VERSION}) = {spearman_rho:.4f} (n={len(gt_act)}){const_note}",
            flush=True,
        )
    print("BACKCHECK OK", flush=True)

    return {
        "date": ds,
        "races": n_races,
        "runners": int(len(gt_act)),
        "skipped_unfinished": skipped_unfinished,
        "skipped_no_agf": skipped_no_agf,
        "agf_log_loss": agf_ll,
        "agf_top1": agf_top1,
        "models": model_metrics,
        "spearman_v6_v5": spearman_rho,
        "written_rows": written_out,
    }


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v5 (v5_sgr_all) ve Model v6 (v6_e5) canlı koşu-öncesi tahmin yazıcı ve geriye dönük denetim."
    )
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (varsayılan: İstanbul bugün)")
    ap.add_argument("--db", default="data/ganyan.db", help="Ana SQLite veritabanı yolu (salt-okunur okunur)")
    ap.add_argument(
        "--out",
        default=None,
        help="Tahmin çıktı SQLite yolu (canlıda varsayılan: data/forward_v5.db; --backcheck'te verilmezse yazılmaz)",
    )
    ap.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Virgüllü model sürümleri (varsayılan: v5_sgr_all,v6_e5)",
    )
    ap.add_argument(
        "--model-cache-dir",
        default=DEFAULT_MODEL_CACHE_DIR,
        help="Günlük eğitilmiş V6 model önbellek dizini (varsayılan: data/forward_models)",
    )
    ap.add_argument(
        "--backcheck",
        default=None,
        metavar="YYYY-MM-DD",
        help="Sonuçlanmış bir gün için geriye dönük gerçek-veri denetimi çalıştır",
    )
    ap.add_argument("--train-start", default=DEFAULT_TRAIN_START, help="Eğitim başlangıç tarihi YYYY-MM-DD")
    ap.add_argument("--due-max-min", type=float, default=DEFAULT_DUE_MAX_MIN, help="Koşuya kalan azami dakika")
    ap.add_argument("--once", action="store_true", help="Tek geçiş çalıştır ve çık")
    ap.add_argument("--now", default=None, help="Test için sahte saat (YYYY-MM-DDTHH:MM[:SS])")
    ap.add_argument("--interval", type=int, default=120, help="Döngü kipinde bekleme süresi (sn)")
    ap.add_argument("--prog-dir", default="data/raw/program", help="Ham program CSV dizini")
    ap.add_argument("--no-snapshot", action="store_true", help="Taze AGF snapshot çekmeyi atla")
    return ap


def main(argv=None):
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if args.backcheck is not None:
        try:
            run_backcheck(
                date_str=args.backcheck,
                main_db=args.db,
                out_db=args.out,
                train_start=args.train_start,
                models=args.models,
                cache_dir=None,
            )
        except Exception as exc:
            print(f"BACKCHECK HATA: {exc}", file=sys.stderr, flush=True)
            return 1
        return 0

    live_out_db = args.out if args.out is not None else DEFAULT_OUT_DB

    if args.once or args.now is not None:
        try:
            now_dt = _normalize_now(args.now)
            ds = args.date or now_dt.date().isoformat()
            run_once(
                now=args.now,
                date_str=ds,
                main_db=args.db,
                out_db=live_out_db,
                train_start=args.train_start,
                due_max_min=args.due_max_min,
                prog_dir=args.prog_dir,
                do_snapshot=not args.no_snapshot,
                models=args.models,
                cache_dir=args.model_cache_dir,
            )
        except Exception as exc:
            _log(f"UYARI: forward_v5 çalışması başarısız: {exc}")
        return 0

    while True:
        try:
            now_dt = datetime.datetime.now(IST_TZ)
            ds = args.date or now_dt.date().isoformat()
            run_once(
                now=None,
                date_str=ds,
                main_db=args.db,
                out_db=live_out_db,
                train_start=args.train_start,
                due_max_min=args.due_max_min,
                prog_dir=args.prog_dir,
                do_snapshot=not args.no_snapshot,
                models=args.models,
                cache_dir=args.model_cache_dir,
            )
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            _log(f"UYARI: forward_v5 döngü hatası: {exc}")
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
