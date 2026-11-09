"""Tahmin birleştirme aracı (§6): A.db'deki tahminleri B.db'ye birleştir.

Aynı (race_id, prog_no, model_version) her ikisinde de varsa created_at EN ERKEN olan kalır;
yalnız A'da varsa B'ye eklenir; yalnız B'de varsa B'deki korunur.
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db


def merge_predictions(from_db, into_db, model_version="v1_agf", dry_run=False):
    """from_db içindeki predictions kayıtlarını into_db'ye birleştir.

    Dönüş:
      {
        "added": int, "updated": int, "same": int,
        "eklenen": int, "degisen": int, "ayni": int,
      }
    """
    conn_a = sqlite3.connect(f"file:{os.path.abspath(from_db)}?mode=ro", uri=True, timeout=30)
    conn_b = (
        sqlite3.connect(f"file:{os.path.abspath(into_db)}?mode=ro", uri=True, timeout=30)
        if dry_run
        else init_db(into_db)
    )
    try:
        where_sql = "WHERE model_version = ?" if model_version else ""
        params = (model_version,) if model_version else ()

        rows_a = conn_a.execute(
            f"SELECT race_id, prog_no, model_version, created_at, p_win, agf_used FROM predictions {where_sql} ORDER BY race_id, prog_no",
            params,
        ).fetchall()
        rows_b = conn_b.execute(
            f"SELECT race_id, prog_no, model_version, created_at, p_win, agf_used FROM predictions {where_sql}",
            params,
        ).fetchall()

        map_b = {
            (r[0], int(r[1]), r[2]): (str(r[3] or ""), r[4], r[5])
            for r in rows_b
        }

        to_insert = []
        to_update = []
        same = 0

        for race_id, prog_no, mv, created_at, p_win, agf_used in rows_a:
            pk = (race_id, int(prog_no), mv)
            a_ts = str(created_at or "")
            if pk not in map_b:
                to_insert.append((race_id, int(prog_no), mv, a_ts, p_win, agf_used))
            else:
                b_ts, _, _ = map_b[pk]
                if a_ts and (not b_ts or a_ts < b_ts):
                    to_update.append((a_ts, p_win, agf_used, race_id, int(prog_no), mv))
                else:
                    same += 1

        added = len(to_insert)
        updated = len(to_update)
        prefix = "[DRY-RUN] " if dry_run else ""
        print(f"{prefix}eklenen: {added}, değişen: {updated}, aynı: {same}")

        if not dry_run and (to_insert or to_update):
            cur = conn_b.cursor()
            if to_insert:
                cur.executemany(
                    """
                    INSERT INTO predictions (race_id, prog_no, model_version, created_at, p_win, agf_used)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    to_insert,
                )
            if to_update:
                cur.executemany(
                    """
                    UPDATE predictions
                    SET created_at = ?, p_win = ?, agf_used = ?
                    WHERE race_id = ? AND prog_no = ? AND model_version = ?
                    """,
                    to_update,
                )
            conn_b.commit()

        return {
            "added": added,
            "updated": updated,
            "same": same,
            "eklenen": added,
            "degisen": updated,
            "ayni": same,
        }
    finally:
        conn_a.close()
        conn_b.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="A.db'deki tahminleri B.db'ye en erken created_at kuralıyla birleştir")
    ap.add_argument("--from", dest="from_db", required=True, help="Kaynak veritabanı (A.db)")
    ap.add_argument("--into", dest="into_db", required=True, help="Hedef veritabanı (B.db)")
    ap.add_argument("--model-version", default="v1_agf", help="Model sürümü (varsayılan: v1_agf)")
    ap.add_argument("--dry-run", action="store_true", help="Hedef veritabanına yazmadan sayıları raporla")
    args = ap.parse_args(argv)

    merge_predictions(
        from_db=args.from_db,
        into_db=args.into_db,
        model_version=args.model_version,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
