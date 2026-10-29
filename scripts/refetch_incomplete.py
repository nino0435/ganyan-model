"""Re-download results CSVs that have fewer races than the program (TJK may publish them partially).

Usage: scripts/refetch_incomplete.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--dry-run]
Only replaces a file when the fresh download has more races than the local one.
"""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db, upsert_results
from ganyan.parse_results import parse_results_file
from ganyan.tjk import DELAY, get, results_csv_url
from scripts.update_daily import _results_incomplete, _race_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-10-26")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    res_dir = "data/raw/results"
    conn = init_db(args.db)
    todo = []
    for fn in sorted(os.listdir(res_dir)):
        if not fn.endswith(".csv"):
            continue
        ds, city = fn[:-4].split("_", 1)
        if args.start <= ds <= args.end and _results_incomplete(conn, os.path.join(res_dir, fn), ds, city):
            todo.append((ds, city, os.path.join(res_dir, fn)))
    print(f"Incomplete result files: {len(todo)}")

    fixed = 0
    for ds, city, fn in todo:
        if args.dry_run:
            print(f"  {ds} {city}: {_race_count(fn)} races locally")
            continue
        st, data = get(results_csv_url(datetime.date.fromisoformat(ds), city))
        time.sleep(DELAY)
        new_n = data.decode("utf-8-sig", "replace").count("Kosu :") if st == 200 and data else 0
        if new_n > _race_count(fn):
            open(fn, "wb").write(data)
            upsert_results(conn, parse_results_file(fn, date=ds, city=city))
            fixed += 1
            print(f"  {ds} {city}: -> {new_n} races")
        else:
            print(f"  {ds} {city}: unchanged at source ({new_n} races)")
    conn.close()
    print(f"Updated: {fixed}")


if __name__ == "__main__":
    main()
