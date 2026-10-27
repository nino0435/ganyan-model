"""CLI script to export daily JSON contract for the mobile app (§5)."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db
from ganyan.export import export_day


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--out", default="data/export")
    args = ap.parse_args()
    conn = init_db(args.db)
    out_dir = export_day(conn, args.date, out_root=args.out)
    conn.close()
    print(f"Exported daily JSON files to {out_dir}")


if __name__ == "__main__":
    main()
