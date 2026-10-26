"""Backfill historical results & program CSVs into data/ganyan.db and run cross-check."""
import argparse
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db, upsert_program, upsert_results
from ganyan.parse_program import parse_program_file
from ganyan.parse_results import parse_results_file
from ganyan.tjk import DELAY, get, program_csv_url, results_csv_url


def cross_check(conn):
    """Cross-check winner's prog_no from program CSV against GANYAN(n) from results CSV."""
    rows = conn.execute(
        """
        SELECT r.race_id, run.prog_no, b.combo
        FROM races r
        JOIN runners run ON r.race_id = run.race_id AND run.finish = 1 AND run.scratched = 0
        JOIN bets b ON r.race_id = b.race_id AND b.bet = 'GANYAN'
        WHERE r.status = 'result'
        """
    ).fetchall()

    # Wait: in eküri races, a horse whose prog_no != GANYAN(n) can finish 1st, while GANYAN pays on the eküri number!
    # Still, let's count exact match vs mismatch across all races where prog_no is not null.
    total = 0
    mismatches = 0
    missing_prog = 0
    by_race = {}
    for race_id, prog_no, combo in rows:
        by_race.setdefault(race_id, []).append((prog_no, combo))

    for race_id, items in by_race.items():
        if len(items) != 1:
            # Dead heat (ölü yarış)
            continue
        prog_no, combo = items[0]
        if prog_no is None:
            missing_prog += 1
            continue
        total += 1
        if str(prog_no) != str(combo).strip():
            mismatches += 1

    rate = (mismatches / total * 100) if total else 0.0
    print(
        f"Cross-check: compared={total} races, mismatches={mismatches} ({rate:.2f}%), missing_prog={missing_prog}"
    )
    return total, mismatches, rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-10-26")
    ap.add_argument("--end", default="2026-10-25")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()

    res_dir = "data/raw/results"
    prog_dir = "data/raw/program"
    os.makedirs(res_dir, exist_ok=True)
    os.makedirs(prog_dir, exist_ok=True)

    # 1. Move hist/*.csv to data/raw/results/ if hist/ exists
    if os.path.isdir("hist"):
        moved = 0
        evicted = 0
        for fn in sorted(os.listdir("hist")):
            if not fn.endswith(".csv"):
                continue
            src = os.path.join("hist", fn)
            dst = os.path.join(res_dir, fn)
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                continue
            st_info = os.stat(src)
            # UF_DATALESS = 0x40000000 on macOS when iCloud evicted the file
            if getattr(st_info, "st_flags", 0) & 0x40000000:
                m = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)\.csv$", fn)
                if m and (args.start <= m.group(1) <= args.end) and not args.skip_download:
                    st_http, data = get(results_csv_url(m.group(1), m.group(2)))
                    time.sleep(DELAY)
                    if st_http == 200 and data:
                        open(dst, "wb").write(data)
                        evicted += 1
            else:
                try:
                    shutil.copyfile(src, dst)
                    os.remove(src)
                    moved += 1
                except OSError:
                    pass
        if moved or evicted:
            print(f"Moved {moved} local CSVs and restored {evicted} iCloud-evicted CSVs to {res_dir}/")

    # Collect target (date, city) pairs from results CSVs in range
    targets = []
    for fn in sorted(os.listdir(res_dir)):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)\.csv$", fn)
        if m:
            d, c = m.group(1), m.group(2)
            if args.start <= d <= args.end:
                targets.append((d, c, fn))

    # 2. Download corresponding program CSVs if not already present
    if not args.skip_download:
        downloaded = 0
        failed = 0
        for i, (d, c, fn) in enumerate(targets, 1):
            p_fn = os.path.join(prog_dir, fn)
            if os.path.exists(p_fn) and os.path.getsize(p_fn) > 0:
                continue
            url = program_csv_url(d, c)
            st, data = get(url)
            time.sleep(DELAY)
            if st == 200 and data:
                open(p_fn, "wb").write(data)
                downloaded += 1
            else:
                failed += 1
            if (downloaded + failed) % 50 == 0:
                print(
                    f"Program download progress: {i}/{len(targets)} checked, {downloaded} downloaded, {failed} failed",
                    flush=True,
                )
        print(f"Program CSV download finished: {downloaded} new, {failed} failed/missing.")

    # 3. Load all results and programs into SQLite
    conn = init_db(args.db)
    print("Loading results CSVs into SQLite...", flush=True)
    for d, c, fn in targets:
        r_path = os.path.join(res_dir, fn)
        parsed_r = parse_results_file(r_path, date=d, city=c)
        upsert_results(conn, parsed_r)

    print("Loading program CSVs into SQLite...", flush=True)
    for d, c, fn in targets:
        p_path = os.path.join(prog_dir, fn)
        if os.path.exists(p_path) and os.path.getsize(p_path) > 0:
            parsed_p = parse_program_file(p_path, date=d, city=c)
            upsert_program(conn, parsed_p)

    races_total = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    races_res = conn.execute("SELECT COUNT(*) FROM races WHERE status='result'").fetchone()[0]
    races_canc = conn.execute("SELECT COUNT(*) FROM races WHERE status='cancelled'").fetchone()[0]
    runners_total = conn.execute("SELECT COUNT(*) FROM runners").fetchone()[0]
    runners_active = conn.execute("SELECT COUNT(*) FROM runners WHERE scratched=0").fetchone()[0]
    print(
        f"DB Summary: races={races_total} (result={races_res}, cancelled={races_canc}), "
        f"runners={runners_total} (active={runners_active})"
    )
    cross_check(conn)
    conn.close()


if __name__ == "__main__":
    main()
