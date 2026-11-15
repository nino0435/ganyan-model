"""Live forward predictor for Model v5 (B1_SGR trained on full 2015+ history -> data/forward_v5.db)."""
import argparse
import datetime
import os
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.agf_check import agf_complete
from ganyan.backtest import load_runners_from_db
from ganyan.features import build_features
from ganyan.features_v5 import attach_v5, load_v5_tables
from ganyan.live_odds import minutes_to_post
from ganyan.model import fit_predict_df
from ganyan.model_v5 import get_b1x_cols
from scripts.snapshot_agf import snapshot_agf

IST_TZ = ZoneInfo("Europe/Istanbul")
MODEL_VERSION = "v5_sgr_all"
REF_END = "2017-01-01"
DEFAULT_TRAIN_START = "2015-01-01"
DEFAULT_DUE_MAX_MIN = 8.0

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


def init_out_db(out_db="data/forward_v5.db"):
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


def _load_runners_with_today(conn, date_str):
    """Tek SQL (forward_log ile aynı): date < bugün ve status='result' + bugünün iptal olmayan program satırları;
    ardından son AGF bindirmesi ve bugünün sonuç sütunlarının maskelenmesi."""
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


def run_once(
    now=None,
    date_str=None,
    main_db="data/ganyan.db",
    out_db="data/forward_v5.db",
    train_start=DEFAULT_TRAIN_START,
    due_max_min=DEFAULT_DUE_MAX_MIN,
    prog_dir="data/raw/program",
    do_snapshot=True,
    model_version=MODEL_VERSION,
) -> int:
    """Run a single forward v5 check-and-predict pass; returns number of newly written prediction rows."""
    now_ist = _normalize_now(now)
    ds = str(date_str)[:10] if date_str is not None else now_ist.date().isoformat()
    created_at = now_ist.isoformat(timespec="seconds")

    if not os.path.exists(str(main_db)):
        _log(f"UYARI: ana veritabanı bulunamadı ({main_db})")
        return 0

    out_conn = init_out_db(out_db)
    try:
        predicted_ids = _read_predicted_ids(out_conn, model_version=model_version)

        ro_conn = _open_ro_db(main_db)
        try:
            day_races = _read_day_races(ro_conn, ds)
        finally:
            ro_conn.close()

        due = due_races(
            day_races,
            now=now_ist,
            date_str=ds,
            due_max_min=due_max_min,
            predicted_ids=predicted_ids,
        )
        if not due:
            return 0

        if do_snapshot:
            cities = sorted({d["city"] for d in due if d.get("city")})
            if cities:
                try:
                    snapshot_agf(ds, db_path=main_db, prog_dir=prog_dir, cities=cities)
                except Exception as exc:
                    _log(f"UYARI: snapshot_agf başarısız ({ds}, {cities}): {exc}")

        ro_conn = _open_ro_db(main_db)
        try:
            day_races = _read_day_races(ro_conn, ds)
            due = due_races(
                day_races,
                now=now_ist,
                date_str=ds,
                due_max_min=due_max_min,
                predicted_ids=predicted_ids,
            )
            if not due:
                return 0
            df = _load_runners_with_today(ro_conn, ds)
            if df.empty:
                return 0
            tables = load_v5_tables(ro_conn)
        finally:
            ro_conn.close()

        due_ids = [d["race_id"] for d in due]
        ready_map = _agf_ready_map(df[df["date"] == ds], due_ids)
        ready_due = [d for d in due if ready_map.get(d["race_id"], False)]
        if not ready_due:
            return 0

        ext_df = tables["ext"]
        if len(ext_df) > 0:
            hist_rids = set(df.loc[df["date"] < ds, "race_id"].astype(str))
            ext_df = ext_df[ext_df["race_id"].astype("string").isin(hist_rids)].copy()
        w_df = tables["workouts"]
        if len(w_df) > 0:
            w_df = w_df[w_df["date"] < pd.Timestamp(ds)].copy()
        tables = {"ext": ext_df, "workouts": w_df}

        feat_df = build_features(df, ref_end=REF_END)
        feat_df = attach_v5(feat_df, tables, blocks=("S", "G", "R"))

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
            _log(f"UYARI: eğitim verisi yetersiz (satır={len(train_df)})")
            return 0

        ready_ids = [d["race_id"] for d in ready_due]
        today_df = feat_df[(feat_df["date"] == today_ts) & feat_df["race_id"].isin(ready_ids)].copy()
        if today_df.empty:
            return 0

        cols = get_b1x_cols("B1_SGR")
        today_df["p_win"] = fit_predict_df(train_df, today_df, cols)

        mtp_by_race = {d["race_id"]: float(d["mtp"]) for d in ready_due}
        s_cov_by_race = (
            today_df.groupby("race_id")["yb_hiz_last"].apply(lambda s: float(s.notna().mean())).to_dict()
        )
        g_cov_by_race = (
            today_df.groupby("race_id")["g_days_last"].apply(lambda s: float(s.notna().mean())).to_dict()
        )

        cur = out_conn.cursor()
        written = 0
        for _, r in today_df.iterrows():
            if pd.isna(r["prog_no"]):
                continue
            rid = r["race_id"]
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
                    created_at,
                    mtp_by_race[rid],
                    float(r["p_win"]),
                    float(r["agf_close"]) if pd.notna(r["agf_close"]) else None,
                    s_cov_by_race.get(rid, 0.0),
                    g_cov_by_race.get(rid, 0.0),
                ),
            )
            written += cur.rowcount
        out_conn.commit()

        if written:
            desc = ", ".join(
                f"{d['city']} {d['post_time']} (mtp={d['mtp']:.1f}m, S={s_cov_by_race.get(d['race_id'], 0.0):.0%}, G={g_cov_by_race.get(d['race_id'], 0.0):.0%})"
                for d in ready_due
            )
            _log(f"{model_version}: {len(ready_due)} koşu için {written} tahmin yazıldı [{desc}]")
        return written
    finally:
        out_conn.close()


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v5 (B1_SGR, tüm geçmiş) canlı koşu-öncesi tahmin yazıcı."
    )
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (varsayılan: İstanbul bugün)")
    ap.add_argument("--db", default="data/ganyan.db", help="Ana SQLite veritabanı yolu (salt-okunur okunur)")
    ap.add_argument("--out", default="data/forward_v5.db", help="Tahmin çıktı SQLite yolu")
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

    if args.once or args.now is not None:
        try:
            now_dt = _normalize_now(args.now)
            ds = args.date or now_dt.date().isoformat()
            run_once(
                now=now_dt,
                date_str=ds,
                main_db=args.db,
                out_db=args.out,
                train_start=args.train_start,
                due_max_min=args.due_max_min,
                prog_dir=args.prog_dir,
                do_snapshot=not args.no_snapshot,
            )
        except Exception as exc:
            _log(f"UYARI: forward_v5 çalışması başarısız: {exc}")
        return 0

    while True:
        try:
            now_dt = datetime.datetime.now(IST_TZ)
            ds = args.date or now_dt.date().isoformat()
            run_once(
                now=now_dt,
                date_str=ds,
                main_db=args.db,
                out_db=args.out,
                train_start=args.train_start,
                due_max_min=args.due_max_min,
                prog_dir=args.prog_dir,
                do_snapshot=not args.no_snapshot,
            )
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            _log(f"UYARI: forward_v5 döngü hatası: {exc}")
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
