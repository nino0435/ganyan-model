"""Kayıp kurtarma: state/predictions/*.csv dosyalarından predictions tablosunu yeniden kur (§2.3)."""
import argparse
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db


def _parse_float(val):
    if val is None or str(val).strip() == "":
        return None
    return float(val)


def restore_predictions(db_path="data/ganyan.db", predictions_dir="state/predictions", dry_run=False):
    """state/predictions/*.csv içindeki satırları INSERT OR IGNORE ile veritabanına yükle.

    Dönüş: {"csv_files": int, "csv_rows": int, "inserted": int}
    """
    if os.path.isdir(os.path.join(str(predictions_dir), "predictions")):
        predictions_dir = os.path.join(str(predictions_dir), "predictions")

    csv_files = sorted(glob.glob(os.path.join(str(predictions_dir), "*.csv")))
    rows_to_insert = []
    seen_pks = set()
    total_csv_rows = 0

    for fn in csv_files:
        with open(fn, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_csv_rows += 1
                race_id = (row.get("race_id") or "").strip()
                prog_no_str = (row.get("prog_no") or "").strip()
                model_version = (row.get("model_version") or "v1_agf").strip()
                created_at = (row.get("created_at") or "").strip()
                p_win = _parse_float(row.get("p_win"))
                agf_used = _parse_float(row.get("agf_used"))
                if not race_id or not prog_no_str or p_win is None:
                    continue
                prog_no = int(prog_no_str)
                pk = (race_id, prog_no, model_version)
                if pk in seen_pks:
                    continue
                seen_pks.add(pk)
                rows_to_insert.append((race_id, prog_no, model_version, created_at, p_win, agf_used))

    conn = init_db(db_path)
    try:
        if dry_run:
            existing = {
                (r[0], int(r[1]), r[2])
                for r in conn.execute("SELECT race_id, prog_no, model_version FROM predictions").fetchall()
            }
            would_insert = sum(1 for r in rows_to_insert if (r[0], r[1], r[2]) not in existing)
            return {"csv_files": len(csv_files), "csv_rows": total_csv_rows, "inserted": would_insert}

        cur = conn.cursor()
        inserted = 0
        for row_tuple in rows_to_insert:
            cur.execute(
                """
                INSERT OR IGNORE INTO predictions
                    (race_id, prog_no, model_version, created_at, p_win, agf_used)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                row_tuple,
            )
            inserted += cur.rowcount
        conn.commit()
        return {"csv_files": len(csv_files), "csv_rows": total_csv_rows, "inserted": inserted}
    finally:
        conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="state/predictions/*.csv dosyalarından predictions tablosunu geri yükle")
    ap.add_argument("--db", default="data/ganyan.db", help="Hedef SQLite veritabanı")
    ap.add_argument("--predictions-dir", default="state/predictions", help="CSV klasörü (varsayılan: state/predictions)")
    ap.add_argument("--dry-run", action="store_true", help="Veritabanına yazmadan sayıları göster")
    args = ap.parse_args(argv)

    res = restore_predictions(db_path=args.db, predictions_dir=args.predictions_dir, dry_run=args.dry_run)
    prefix = "[DRY-RUN] " if args.dry_run else ""
    print(
        f"{prefix}{res['csv_files']} CSV dosyasından {res['csv_rows']} satır okundu; "
        f"eklenen: {res['inserted']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
