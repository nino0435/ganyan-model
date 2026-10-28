"""Forward-testing logger (§4): capture AGF snapshot, predict with v1_agf trained through yesterday, and store in predictions."""
import argparse
import datetime
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db
from ganyan.features import build_features, get_feature_cols
from ganyan.model import fit_predict_df
from scripts.snapshot_agf import snapshot_agf

IST_TZ = ZoneInfo("Europe/Istanbul")
MODEL_VERSION = "v1_agf"


def forward_log(date_str, db_path="data/ganyan.db", prog_dir="data/raw/program", do_snapshot=True, created_at=None):
    """Run forward prediction logging for date_str. Does not overwrite existing predictions for the same model_version."""
    if do_snapshot:
        snapshot_agf(date_str, db_path=db_path, prog_dir=prog_dir)

    conn = init_db(db_path)
    if created_at is None:
        created_at = datetime.datetime.now(IST_TZ).strftime("%Y-%m-%dT%H:%M:%S")

    # Load all historical results < date_str and target day races == date_str
    query = """
    SELECT
        r.race_id, r.date, r.city, r.race_no, r.post_time, r.yg_no,
        r.cls, r.breed, r.distance, r.surface, r.status,
        run.prog_no, run.horse_key, run.name, run.name_raw, run.age, run.sex,
        run.sire, run.dam, run.weight, run.jockey, run.owner, run.trainer,
        run.gate, run.hp, run.son6, run.kgs, run.s20, run.best_time_s,
        run.finish, run.time_s, run.ganyan, run.agf_close, run.agf_close_rank, run.scratched
    FROM races r
    JOIN runners run ON r.race_id = run.race_id
    WHERE (r.date < ? AND r.status = 'result') OR (r.date = ? AND r.status != 'cancelled')
    """
    df = pd.read_sql_query(query, conn, params=(date_str, date_str))
    if df.empty or not (df["date"] == date_str).any():
        conn.close()
        return 0

    # Overlay latest agf_snapshots for target date if available
    snaps = pd.read_sql_query(
        """
        SELECT s.race_id, s.prog_no, s.agf_pct, s.agf_rank
        FROM agf_snapshots s
        JOIN races r ON s.race_id = r.race_id
        WHERE r.date = ?
        ORDER BY s.captured_at ASC
        """,
        conn,
        params=(date_str,),
    )
    if not snaps.empty:
        latest = snaps.groupby(["race_id", "prog_no"], as_index=False).last()
        snap_map = dict(zip(zip(latest["race_id"], latest["prog_no"]), latest["agf_pct"]))
        mask_today = df["date"] == date_str
        for idx in df[mask_today].index:
            key = (df.at[idx, "race_id"], df.at[idx, "prog_no"])
            if key in snap_map and snap_map[key] is not None:
                df.at[idx, "agf_close"] = snap_map[key]

    # Mask target day post-race outcomes so feature builder is strictly pre-race
    mask_today = df["date"] == date_str
    df.loc[mask_today, ["finish", "time_s", "ganyan"]] = np.nan

    feat_df = build_features(df, ref_end="2025-07-01")
    _, with_agf_cols = get_feature_cols(feat_df)

    rg = feat_df.groupby("race_id")
    ok_train = (
        (feat_df["date"] >= pd.Timestamp("2025-01-01"))
        & (feat_df["date"] < pd.Timestamp(date_str))
        & rg["agf_close"].transform(lambda s: s.notna().all())
        & rg["ganyan"].transform(lambda s: s.notna().all())
        & (rg["win"].transform("sum") == 1)
        & (feat_df["field"] >= 4)
    )
    train_df = feat_df[ok_train]
    today_df = feat_df[feat_df["date"] == pd.Timestamp(date_str)].copy()

    # AGF henüz yayınlanmadıysa o koşuyu yazma: INSERT OR IGNORE ilk kaydı kalıcı yapar,
    # AGF'siz (neredeyse tekdüze) tahmin ileri testi bozar. Sonraki çalıştırma yazar.
    active = today_df[today_df["scratched"].fillna(0) == 0]
    agf_ready = active.groupby("race_id")["agf_close"].apply(lambda s: bool(s.notna().all()))
    today_df = today_df[today_df["race_id"].map(agf_ready).fillna(False).astype(bool)].copy()

    if train_df.empty or today_df.empty:
        conn.close()
        return 0

    today_df["p_win"] = fit_predict_df(train_df, today_df, with_agf_cols)

    cur = conn.cursor()
    written = 0
    for _, r in today_df.iterrows():
        if pd.isna(r["prog_no"]):
            continue
        cur.execute(
            """
            INSERT OR IGNORE INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                r["race_id"],
                int(r["prog_no"]),
                MODEL_VERSION,
                created_at,
                float(r["p_win"]),
                float(r["agf_close"]) if pd.notna(r["agf_close"]) else None,
            ),
        )
        written += cur.rowcount
    conn.commit()
    conn.close()
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--no-snapshot", action="store_true")
    args = ap.parse_args()
    n = forward_log(args.date, db_path=args.db, do_snapshot=not args.no_snapshot)
    print(f"Logged {n} new forward predictions for {args.date}")


if __name__ == "__main__":
    main()
