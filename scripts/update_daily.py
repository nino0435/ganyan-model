"""Daily update script: fetch tomorrow's program and today/yesterday's results into SQLite."""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db, upsert_program, upsert_results
from ganyan.parse_program import parse_program_file
from ganyan.parse_results import parse_results_file
from ganyan.tjk import DELAY, domestic_cities, get, program_csv_url, results_csv_url


def update_daily(date_str, db_path="data/ganyan.db", res_dir="data/raw/results", prog_dir="data/raw/program", fetch=True):
    os.makedirs(res_dir, exist_ok=True)
    os.makedirs(prog_dir, exist_ok=True)
    conn = init_db(db_path)

    d = datetime.date.fromisoformat(date_str)
    d_prev = d - datetime.timedelta(days=1)
    d_next = d + datetime.timedelta(days=1)

    # 1. Program CSVs for d and d+1
    for prog_d in (d, d_next):
        ds = prog_d.isoformat()
        cities = domestic_cities(prog_d, page_type="GunlukYarisProgrami") if fetch else []
        for city in cities:
            fn = os.path.join(prog_dir, f"{ds}_{city}.csv")
            if fetch and not os.path.exists(fn):
                st, data = get(program_csv_url(prog_d, city))
                time.sleep(DELAY)
                if st == 200 and data:
                    open(fn, "wb").write(data)
            if os.path.exists(fn) and os.path.getsize(fn) > 0:
                parsed = parse_program_file(fn, date=ds, city=city)
                upsert_program(conn, parsed)

    # 2. Results CSVs for d-1 and d
    for res_d in (d_prev, d):
        ds = res_d.isoformat()
        cities = domestic_cities(res_d, page_type="GunlukYarisSonuclari") if fetch else []
        for city in cities:
            fn = os.path.join(res_dir, f"{ds}_{city}.csv")
            if fetch and not os.path.exists(fn):
                st, data = get(results_csv_url(res_d, city))
                time.sleep(DELAY)
                if st == 200 and data:
                    open(fn, "wb").write(data)
            if os.path.exists(fn) and os.path.getsize(fn) > 0:
                parsed = parse_results_file(fn, date=ds, city=city)
                upsert_results(conn, parsed)

    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()
    update_daily(args.date, db_path=args.db, fetch=not args.no_fetch)


if __name__ == "__main__":
    main()
