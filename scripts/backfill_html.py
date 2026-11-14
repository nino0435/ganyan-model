"""Backfill historical TJK HTML daily results (2005 -> 2024-10-25, newest-to-oldest)."""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import sqlite3
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan.db import (  # noqa: E402
    fetched_ok,
    init_db,
    upsert_pools,
    upsert_race_extra,
    upsert_results,
    upsert_runner_extra,
)
from ganyan.sources.fetch import fetch  # noqa: E402
from ganyan.sources.tjk_html import (  # noqa: E402
    XHR_HEADERS,
    city_results_url,
    day_results_url,
    parse_day_cities,
    parse_results_html,
)
from ganyan.tjk import get as tjk_get  # noqa: E402

SOURCE = "tjk_html"

_TR_ASCII = str.maketrans({
    "ç": "c", "Ç": "C",
    "ğ": "g", "Ğ": "G",
    "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O",
    "ş": "s", "Ş": "S",
    "ü": "u", "Ü": "U",
})


class _NoCommitConn:
    """sqlite3.Connection proxy that defers commit() to an outer BEGIN ... COMMIT block."""

    def __init__(self, conn):
        self._conn = conn

    def commit(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _city_slug(city):
    s = (city or "").translate(_TR_ASCII)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s or "city"


def _read_gz_or_plain(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def has_csv_results(conn, date_str, city):
    """Return True if DB already has non-HTML (CSV-sourced) status='result' races for (date, city)."""
    if conn is None:
        return False
    if not _table_exists(conn, "race_extra"):
        row = conn.execute(
            "SELECT 1 FROM races WHERE date = ? AND city = ? AND status = 'result' LIMIT 1",
            (date_str, city),
        ).fetchone()
        return row is not None
    row = conn.execute(
        """
        SELECT 1
        FROM races r
        LEFT JOIN race_extra re ON re.race_id = r.race_id
        WHERE r.date = ? AND r.city = ? AND r.status = 'result'
          AND COALESCE(re.source, '') != ?
        LIMIT 1
        """,
        (date_str, city, SOURCE),
    ).fetchone()
    return row is not None


def has_html_results(conn, date_str, city):
    """Return True if DB already has tjk_html-sourced rows for (date, city)."""
    if conn is None or not _table_exists(conn, "race_extra"):
        return False
    row = conn.execute(
        """
        SELECT 1
        FROM races r
        JOIN race_extra re ON re.race_id = r.race_id
        WHERE r.date = ? AND r.city = ? AND re.source = ?
        LIMIT 1
        """,
        (date_str, city, SOURCE),
    ).fetchone()
    return row is not None


def write_city_results(conn, parsed):
    """Atomically write races, runners (+prog_no), bets, altili, extras, and pools."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        upsert_results(_NoCommitConn(conn), parsed)
        prog_rows = [
            (r["prog_no"], r["race_id"], r["horse_key"])
            for r in parsed.get("runners", [])
            if r.get("prog_no") is not None
        ]
        if prog_rows:
            conn.executemany(
                """
                UPDATE runners
                SET prog_no = COALESCE(prog_no, ?)
                WHERE race_id = ? AND horse_key = ?
                """,
                prog_rows,
            )
        upsert_race_extra(conn, parsed.get("race_extra", []), commit=False)
        upsert_runner_extra(conn, parsed.get("runner_extra", []), commit=False)
        upsert_pools(conn, parsed.get("pools", []), commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _dry_get_html(url, raw_path, headers=None, delay=1.0):
    """Read local raw_path if cached, else download in-memory without writing to disk or DB."""
    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
        try:
            return _read_gz_or_plain(raw_path)
        except OSError:
            pass
    st, body = tjk_get(url, extra_headers=headers)
    if delay and delay > 0:
        time.sleep(delay)
    if st == 200 and body and body.strip():
        return body.decode("utf-8", errors="replace")
    return None


def _vals_equal(a, b, tol=1e-6):
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= tol
    return a == b


def _load_validate_html(date_str, city, raw_dir, delay):
    """Load city HTML for --validate without touching DB: raw_dir -> fixtures -> live TJK."""
    slug = _city_slug(city)
    candidates = [
        os.path.join(raw_dir, "cities", f"{date_str}_{slug}.html.gz"),
        os.path.join(raw_dir, "cities", f"{date_str}_{slug.lower()}.html.gz"),
        os.path.join(REPO_ROOT, "tests", "fixtures", f"results_html_{date_str}_{slug}.html.gz"),
        os.path.join(REPO_ROOT, "tests", "fixtures", f"results_html_{date_str}_{city}.html.gz"),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return _read_gz_or_plain(p)

    day_raw = os.path.join(raw_dir, "days", f"{date_str}.html.gz")
    day_html = _dry_get_html(day_results_url(date_str), day_raw, headers=None, delay=delay)
    if not day_html:
        return None
    sehir_id = None
    for c_name, c_id in parse_day_cities(day_html):
        if c_name == city or _city_slug(c_name).lower() == slug.lower():
            sehir_id = c_id
            city = c_name
            break
    if not sehir_id:
        return None
    city_raw = os.path.join(raw_dir, "cities", f"{date_str}_{slug}.html.gz")
    return _dry_get_html(
        city_results_url(date_str, city, sehir_id),
        city_raw,
        headers=XHR_HEADERS,
        delay=delay,
    )


def run_validate(db_path, date_str, city, raw_dir, delay):
    """Parse HTML without writing to DB and compare field-by-field against CSV rows in DB."""
    if not os.path.exists(db_path):
        print(f"Validate HATA: DB bulunamadı: {db_path}")
        return 1

    html_text = _load_validate_html(date_str, city, raw_dir, delay)
    if not html_text:
        print(f"Validate HATA: ({date_str}, {city}) için HTML alınamadı.")
        return 1

    parsed = parse_results_html(html_text, date_str, city)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        db_races = {
            r["race_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM races WHERE date = ? AND city = ? ORDER BY race_no",
                (date_str, city),
            ).fetchall()
        }
        if not db_races:
            print(f"Validate HATA: DB'de ({date_str}, {city}) için kayıtlı koşu yok.")
            return 1

        race_ids = tuple(db_races.keys())
        q_marks = ",".join("?" for _ in race_ids)
        db_runners = {
            (r["race_id"], r["horse_key"]): dict(r)
            for r in conn.execute(
                f"SELECT * FROM runners WHERE race_id IN ({q_marks})",
                race_ids,
            ).fetchall()
        }
        db_bets = {
            (r["race_id"], r["bet"], r["combo"]): float(r["payout"])
            for r in conn.execute(
                f"SELECT race_id, bet, combo, payout FROM bets WHERE race_id IN ({q_marks})",
                race_ids,
            ).fetchall()
        }
        db_altili = {
            int(r["which"]): dict(r)
            for r in conn.execute(
                "SELECT * FROM altili WHERE date = ? AND city = ? ORDER BY which",
                (date_str, city),
            ).fetchall()
        }
    finally:
        conn.close()

    total_checks = 0
    diffs = []

    def check(label, html_val, db_val):
        nonlocal total_checks
        total_checks += 1
        if not _vals_equal(html_val, db_val):
            diffs.append(f"{label}: html={html_val!r} != db={db_val!r}")

    html_races = {r["race_id"]: r for r in parsed["races"]}
    check("races.count", len(html_races), len(db_races))
    race_fields = ("race_no", "post_time", "cls", "breed", "distance", "surface", "status")
    for rid in sorted(set(db_races) | set(html_races)):
        if rid not in html_races:
            total_checks += 1
            diffs.append(f"race[{rid}]: HTML'de eksik")
            continue
        if rid not in db_races:
            total_checks += 1
            diffs.append(f"race[{rid}]: DB'de eksik")
            continue
        hr, dr = html_races[rid], db_races[rid]
        for f in race_fields:
            check(f"race[{rid}].{f}", hr.get(f), dr.get(f))

    html_runners = {(r["race_id"], r["horse_key"]): r for r in parsed["runners"]}
    check("runners.count", len(html_runners), len(db_runners))
    runner_fields = (
        "name",
        "name_raw",
        "age",
        "sex",
        "sire",
        "dam",
        "weight",
        "jockey",
        "owner",
        "trainer",
        "gate",
        "hp",
        "finish",
        "time_s",
        "ganyan",
        "agf_close",
        "agf_close_rank",
        "scratched",
    )
    for key in sorted(set(db_runners) | set(html_runners)):
        if key not in html_runners:
            total_checks += 1
            diffs.append(f"runner[{key[0]} | {key[1]}]: HTML'de eksik")
            continue
        if key not in db_runners:
            total_checks += 1
            diffs.append(f"runner[{key[0]} | {key[1]}]: DB'de eksik")
            continue
        hrun, drun = html_runners[key], db_runners[key]
        if drun.get("prog_no") is not None:
            check(f"runner[{key[0]} | {hrun['name']}].prog_no", hrun.get("prog_no"), drun.get("prog_no"))
        for f in runner_fields:
            check(f"runner[{key[0]} | {hrun['name']}].{f}", hrun.get(f), drun.get(f))

    html_bets = {(b["race_id"], b["bet"], b["combo"]): b["payout"] for b in parsed["bets"]}
    check("bets.count", len(html_bets), len(db_bets))
    for bkey in sorted(set(db_bets) | set(html_bets)):
        if bkey not in html_bets:
            total_checks += 1
            diffs.append(f"bet{bkey}: HTML'de eksik")
            continue
        if bkey not in db_bets:
            total_checks += 1
            diffs.append(f"bet{bkey}: DB'de eksik")
            continue
        check(f"bet{bkey}.payout", html_bets[bkey], db_bets[bkey])

    html_altili = {int(a["which"]): a for a in parsed["altili"]}
    check("altili.count", len(html_altili), len(db_altili))
    for w in sorted(set(db_altili) | set(html_altili)):
        if w not in html_altili:
            total_checks += 1
            diffs.append(f"altili[{w}]: HTML'de eksik")
            continue
        if w not in db_altili:
            total_checks += 1
            diffs.append(f"altili[{w}]: DB'de eksik")
            continue
        ha, da = html_altili[w], db_altili[w]
        db_legs = json.loads(da["legs"]) if isinstance(da["legs"], str) else da["legs"]
        check(f"altili[{w}].start_race", ha["start_race"], da["start_race"])
        check(f"altili[{w}].end_race", ha["end_race"], da["end_race"])
        check(f"altili[{w}].legs", ha["legs"], db_legs)
        check(f"altili[{w}].payout", ha["payout"], da["payout"])

    mismatch_count = len(diffs)
    rate = (mismatch_count / total_checks * 100.0) if total_checks else 0.0
    sample_db_yg = next(iter(db_races.values())).get("yg_no")
    print(
        f"Validate ({date_str}, {city}): alan_kontrol={total_checks}, "
        f"uyusmazlik={mismatch_count} ({rate:.4f}%) "
        f"[Not: sehir XHR HTML'de yg_no={parsed['yg_no']!r}, DB CSV yg_no={sample_db_yg!r}]"
    )
    for line in diffs[:20]:
        print(f"  FARK: {line}")
    return 0


def _print_year_summary(year, st):
    if year is None:
        return
    print(
        f"[Yıl {year}] gün={st['days']} şehir={st['cities']} "
        f"koşu={st['races']} at={st['runners']} hata={st['errors']}",
        flush=True,
    )


def main():
    ap = argparse.ArgumentParser(description="TJK HTML günlük sonuç geri doldurma (2005 -> 2024-10-25).")
    ap.add_argument("--start", default="2005-01-01")
    ap.add_argument("--end", default="2024-10-25")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--raw-dir", default="data/raw/tjk_html")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--max-days", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--date", default="2026-10-24")
    ap.add_argument("--city", default="Ankara")
    args = ap.parse_args()

    if args.validate:
        sys.exit(run_validate(args.db, args.date, args.city, args.raw_dir, args.delay))

    d_start = dt.date.fromisoformat(args.start)
    d_end = dt.date.fromisoformat(args.end)
    if d_end < d_start:
        ap.error(f"--end ({args.end}) --start ({args.start}) tarihinden küçük olamaz.")

    conn = None
    if args.dry_run:
        if os.path.exists(args.db):
            conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    else:
        os.makedirs(args.raw_dir, exist_ok=True)
        conn = init_db(args.db)

    cur_year = None
    year_stats = None
    processed_days = 0

    def _new_stats():
        return {"days": 0, "cities": 0, "races": 0, "runners": 0, "errors": 0}

    cur_d = d_end
    try:
        while cur_d >= d_start:
            if args.max_days is not None and processed_days >= args.max_days:
                break
            if cur_d.year != cur_year:
                _print_year_summary(cur_year, year_stats)
                cur_year = cur_d.year
                year_stats = _new_stats()

            d_str = cur_d.isoformat()
            processed_days += 1
            year_stats["days"] += 1

            day_raw = os.path.join(args.raw_dir, "days", f"{d_str}.html.gz")
            day_url = day_results_url(d_str)
            if args.dry_run:
                day_html = _dry_get_html(day_url, day_raw, headers=None, delay=args.delay)
            else:
                day_html = fetch(
                    conn,
                    SOURCE,
                    f"day:{d_str}",
                    day_url,
                    day_raw,
                    headers=None,
                    delay=args.delay,
                )

            if not day_html:
                year_stats["errors"] += 1
                cur_d -= dt.timedelta(days=1)
                continue

            cities = parse_day_cities(day_html)
            for city_name, sehir_id in cities:
                if has_csv_results(conn, d_str, city_name):
                    continue

                city_target = f"city:{d_str}:{city_name}"
                city_raw = os.path.join(args.raw_dir, "cities", f"{d_str}_{_city_slug(city_name)}.html.gz")

                if (
                    not args.dry_run
                    and fetched_ok(conn, SOURCE, city_target)
                    and os.path.exists(city_raw)
                    and has_html_results(conn, d_str, city_name)
                ):
                    continue

                city_url = city_results_url(d_str, city_name, sehir_id)
                if args.dry_run:
                    city_html = _dry_get_html(city_url, city_raw, headers=XHR_HEADERS, delay=args.delay)
                else:
                    city_html = fetch(
                        conn,
                        SOURCE,
                        city_target,
                        city_url,
                        city_raw,
                        headers=XHR_HEADERS,
                        delay=args.delay,
                    )

                if not city_html:
                    year_stats["errors"] += 1
                    continue

                try:
                    parsed = parse_results_html(city_html, d_str, city_name)
                    if not parsed["races"]:
                        year_stats["errors"] += 1
                        continue
                    if not args.dry_run:
                        write_city_results(conn, parsed)
                    year_stats["cities"] += 1
                    year_stats["races"] += len(parsed["races"])
                    year_stats["runners"] += len(parsed["runners"])
                except Exception as exc:
                    year_stats["errors"] += 1
                    print(f"HATA ({d_str} {city_name}): {exc}", file=sys.stderr, flush=True)

            cur_d -= dt.timedelta(days=1)
    except KeyboardInterrupt:
        print("\nKesildi (Ctrl-C); fetch_log korundu, kaldığı yerden devam edilebilir.", flush=True)
    finally:
        _print_year_summary(cur_year, year_stats)
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
