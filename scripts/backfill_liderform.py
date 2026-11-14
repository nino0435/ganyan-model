"""Backfill historical Liderform per-race workouts (2015-10-01 -> newest-to-oldest).

Requires Cloudflare WARP (or non-BTK egress) to reach liderform.com.tr.
Stops immediately on 403/Cloudflare or BTK block/redirect without retry storms.
"""
import argparse
import datetime as dt
import gzip
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan.db import fetched_ok, init_db, log_fetch  # noqa: E402
from ganyan.sources.fetch import fetch  # noqa: E402
from ganyan.sources.liderform import (  # noqa: E402
    city_slug,
    detect_liderform_block,
    galop_url,
    parse_galop_horses,
    parse_galop_page,
    parse_next_data,
)
from ganyan.tjk import DOMESTIC_CITIES, UA  # noqa: E402

FETCH_SOURCE = "liderform_galop"
WORKOUT_SOURCE = "liderform"
MIN_DATE = "2015-10-01"


def _read_gz_or_plain(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        return None
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def resolve_horse_key(conn, race_id, horse_number):
    """Resolve horse_key from runners by (race_id, prog_no = horse_number)."""
    if conn is None or not race_id or horse_number is None:
        return None
    row = conn.execute(
        """
        SELECT horse_key
        FROM runners
        WHERE race_id = ? AND prog_no = ?
        ORDER BY COALESCE(scratched, 0) ASC
        LIMIT 1
        """,
        (str(race_id), int(horse_number)),
    ).fetchone()
    return row[0] if row and row[0] else None


def insert_workouts(conn, rows, commit=True):
    """Insert workout rows into workouts table with INSERT OR IGNORE deduplication."""
    if not rows:
        return 0
    cur = conn.cursor()
    before = conn.total_changes
    for r in rows:
        params = {
            "source": r.get("source") or WORKOUT_SOURCE,
            "horse_key": r.get("horse_key"),
            "horse_name": r["horse_name"],
            "ext_horse_id": (
                str(r["ext_horse_id"]) if r.get("ext_horse_id") is not None else None
            ),
            "date": r["date"],
            "city": r.get("city"),
            "kind": r.get("kind"),
            "jockey": r.get("jockey"),
            "kg": r.get("kg"),
            "d1600": r.get("d1600"),
            "d1400": r.get("d1400"),
            "d1200": r.get("d1200"),
            "d1000": r.get("d1000"),
            "d800": r.get("d800"),
            "d600": r.get("d600"),
            "d400": r.get("d400"),
            "d200": r.get("d200"),
            "effort": r.get("effort"),
            "going": r.get("going"),
            "inner_outer": r.get("inner_outer"),
            "surface": r.get("surface"),
        }
        if params["city"] is None or params["kind"] is None:
            exists = cur.execute(
                """
                SELECT 1 FROM workouts
                WHERE source IS :source
                  AND horse_name IS :horse_name
                  AND date IS :date
                  AND city IS :city
                  AND kind IS :kind
                LIMIT 1
                """,
                params,
            ).fetchone()
            if exists:
                continue
        cur.execute(
            """
            INSERT OR IGNORE INTO workouts (
                source, horse_key, horse_name, ext_horse_id, date, city, kind,
                jockey, kg, d1600, d1400, d1200, d1000, d800, d600, d400, d200,
                effort, going, inner_outer, surface
            ) VALUES (
                :source, :horse_key, :horse_name, :ext_horse_id, :date, :city, :kind,
                :jockey, :kg, :d1600, :d1400, :d1200, :d1000, :d800, :d600, :d400, :d200,
                :effort, :going, :inner_outer, :surface
            )
            """,
            params,
        )
    inserted = conn.total_changes - before
    if commit:
        conn.commit()
    return inserted


def insert_horse_ids(conn, rows, commit=True):
    """Upsert external horse ID mappings into horse_ids, preserving resolved horse_key."""
    if not rows:
        return 0
    cur = conn.cursor()
    before = conn.total_changes
    for r in rows:
        raw_ext = r.get("ext_id") if r.get("ext_id") is not None else r.get("ext_horse_id")
        if raw_ext is None or str(raw_ext).strip() == "":
            continue
        params = {
            "source": r.get("source") or WORKOUT_SOURCE,
            "ext_id": str(raw_ext).strip(),
            "horse_key": r.get("horse_key"),
            "horse_name": r.get("horse_name"),
        }
        cur.execute(
            """
            INSERT INTO horse_ids (source, ext_id, horse_key, horse_name)
            VALUES (:source, :ext_id, :horse_key, :horse_name)
            ON CONFLICT(source, ext_id) DO UPDATE SET
                horse_key = COALESCE(excluded.horse_key, horse_ids.horse_key),
                horse_name = COALESCE(excluded.horse_name, horse_ids.horse_name)
            """,
            params,
        )
    changed = conn.total_changes - before
    if commit:
        conn.commit()
    return changed


def ingest_galop_page(conn, race_id, race_date, html_text, dry_run=False):
    """Parse one Liderform race galop page, map horse_keys, and write in one short tx."""
    next_data = parse_next_data(html_text)
    horses = parse_galop_horses(next_data)
    workouts = parse_galop_page(next_data, race_date)

    seen_horses = {}
    for h in horses:
        key_id = h["horse_number"] if h["horse_number"] is not None else f"ext:{h['ext_horse_id']}"
        seen_horses[key_id] = h
    for w in workouts:
        key_id = w["horse_number"] if w["horse_number"] is not None else f"ext:{w['ext_horse_id']}"
        if key_id not in seen_horses:
            seen_horses[key_id] = {
                "horse_number": w["horse_number"],
                "ext_horse_id": w["ext_horse_id"],
                "horse_name": w["horse_name"],
            }

    key_by_prog = {}
    horse_id_rows = []
    unmatched_count = 0

    for h in seen_horses.values():
        prog_no = h["horse_number"]
        h_key = resolve_horse_key(conn, race_id, prog_no) if prog_no is not None else None
        if prog_no is not None:
            key_by_prog[prog_no] = h_key
        if h_key is None:
            unmatched_count += 1
        if h.get("ext_horse_id"):
            horse_id_rows.append({
                "source": WORKOUT_SOURCE,
                "ext_id": h["ext_horse_id"],
                "horse_key": h_key,
                "horse_name": h.get("horse_name"),
            })

    workout_rows = []
    for w in workouts:
        prog_no = w["horse_number"]
        workout_rows.append({
            **w,
            "source": WORKOUT_SOURCE,
            "horse_key": key_by_prog.get(prog_no),
            "surface": None,
        })

    inserted = 0
    if not dry_run and conn is not None and (horse_id_rows or workout_rows):
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")  # okuyup sonra yazan işlemde eşzamanlı yazıcıyla kilit çakışmasını önler
        try:
            insert_horse_ids(conn, horse_id_rows, commit=False)
            inserted = insert_workouts(conn, workout_rows, commit=False)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    return {
        "horses": len(seen_horses),
        "unmatched_horses": unmatched_count,
        "workouts": len(workout_rows),
        "inserted_workouts": inserted,
    }


def load_target_races(conn, start_date, end_date):
    """Return domestic status='result' races in [max(start, 2015-10-01), end], newest first."""
    if conn is None:
        return []
    d_start = max(dt.date.fromisoformat(str(start_date)).isoformat(), MIN_DATE)
    d_end = dt.date.fromisoformat(str(end_date)).isoformat()
    if d_end < d_start:
        return []
    placeholders = ",".join("?" for _ in DOMESTIC_CITIES)
    rows = conn.execute(
        f"""
        SELECT race_id, date, city, race_no
        FROM races
        WHERE status = 'result'
          AND date >= ?
          AND date <= ?
          AND city IN ({placeholders})
        ORDER BY date DESC, city ASC, race_no ASC
        """,
        (d_start, d_end, *DOMESTIC_CITIES),
    ).fetchall()
    return [(r[0], r[1], r[2], int(r[3])) for r in rows]


def _http_get_once(url, extra_headers=None, timeout=30):
    """Single-attempt HTTP GET returning (status, body_bytes, final_url)."""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.geturl()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read()
        except Exception:
            err_body = b""
        final_url = e.geturl() if hasattr(e, "geturl") else url
        return e.code, err_body, final_url
    except Exception:
        return None, b"", url


def _new_year_stats():
    return {
        "races": 0,
        "horses": 0,
        "workouts": 0,
        "inserted": 0,
        "unmatched_horses": 0,
        "errors": 0,
    }


def _print_year_summary(year, st, out=sys.stdout):
    if year is None or st is None:
        return
    print(
        f"[Yıl {year}] koşu={st['races']} at={st['horses']} "
        f"galop={st['workouts']} (yeni={st['inserted']}) "
        f"eşleşmeyen_at={st['unmatched_horses']} hata={st['errors']}",
        file=out,
        flush=True,
    )


def run_backfill(
    conn,
    raw_dir,
    start_date,
    end_date,
    delay=2.0,
    max_races=None,
    dry_run=False,
    reparse=False,
    getter=None,
    sleep_fn=time.sleep,
    out=sys.stdout,
):
    """Execute Liderform galop backfill over target races. Returns exit code (0 or 2 on block)."""
    if conn is not None:
        conn.execute("PRAGMA busy_timeout=60000")

    targets = load_target_races(conn, start_date, end_date)
    raw_dl = getter or _http_get_once
    net_state = {"block_reason": None, "conn_errors": 0, "downloaded": False}

    def checked_getter(url, extra_headers=None):
        res = raw_dl(url, extra_headers=extra_headers)
        if len(res) == 3:
            status, body, final_url = res
        else:
            status, body = res
            final_url = url
        if isinstance(body, str):
            body = body.encode("utf-8")
        body = body or b""
        text = body.decode("utf-8", errors="replace") if body else ""

        reason = detect_liderform_block(text, http_status=status, final_url=final_url)
        if reason:
            net_state["block_reason"] = reason
            err_code = status if (status is not None and status != 200) else 451
            return err_code, b""

        if status is None:
            net_state["conn_errors"] += 1
            if net_state["conn_errors"] >= 3:
                net_state["block_reason"] = "Ardışık bağlantı hatası"
            return None, b""

        net_state["conn_errors"] = 0
        net_state["downloaded"] = True
        return status, body

    cur_year = None
    year_stats = None
    processed = 0
    exit_code = 0

    try:
        for race_id, date_str, city, race_no in targets:
            if max_races is not None and processed >= max_races:
                break

            slug = city_slug(city)
            target = f"{date_str}_{slug}_{race_no}"
            raw_path = os.path.join(raw_dir, date_str[:4], f"{target}.html.gz")

            if (
                not dry_run
                and not reparse
                and conn is not None
                and fetched_ok(conn, FETCH_SOURCE, target)
                and os.path.exists(raw_path)
                and os.path.getsize(raw_path) > 0
            ):
                continue

            year = int(date_str[:4])
            if year != cur_year:
                _print_year_summary(cur_year, year_stats, out=out)
                cur_year = year
                year_stats = _new_year_stats()

            processed += 1
            net_state["downloaded"] = False
            url = galop_url(date_str, city, race_no)

            if dry_run:
                if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
                    html_text = _read_gz_or_plain(raw_path)
                else:
                    st_code, body = checked_getter(url)
                    html_text = (
                        body.decode("utf-8", errors="replace")
                        if st_code == 200 and body.strip()
                        else None
                    )
            else:
                html_text = fetch(
                    conn,
                    FETCH_SOURCE,
                    target,
                    url,
                    raw_path,
                    headers=None,
                    delay=0.0,
                    getter=checked_getter,
                    sleep_fn=sleep_fn,
                )

            if net_state["block_reason"]:
                print(
                    f"ENGEL ({net_state['block_reason']}): {url} — WARP kapalı olabilir. Durduruluyor.",
                    file=out,
                    flush=True,
                )
                exit_code = 2
                break

            if not html_text:
                year_stats["errors"] += 1
                if net_state["downloaded"] and delay and delay > 0:
                    sleep_fn(delay)
                continue

            try:
                st = ingest_galop_page(conn, race_id, date_str, html_text, dry_run=dry_run)
                year_stats["races"] += 1
                year_stats["horses"] += st["horses"]
                year_stats["workouts"] += st["workouts"]
                year_stats["inserted"] += st["inserted_workouts"]
                year_stats["unmatched_horses"] += st["unmatched_horses"]
            except BaseException:
                if not dry_run and conn is not None and net_state["downloaded"]:
                    log_fetch(conn, FETCH_SOURCE, target, "error")
                raise

            if net_state["downloaded"] and delay and delay > 0:
                sleep_fn(delay)
    finally:
        _print_year_summary(cur_year, year_stats, out=out)

    return exit_code


def main():
    ap = argparse.ArgumentParser(
        description="Liderform geçmiş galop geri doldurma (2015-10-01 -> yeniden eskiye)."
    )
    ap.add_argument("--start", default=MIN_DATE)
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--raw-dir", default="data/raw/liderform")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--max-races", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()

    d_start = dt.date.fromisoformat(args.start)
    d_end = dt.date.fromisoformat(args.end)
    if d_end < d_start:
        ap.error(f"--end ({args.end}) --start ({args.start}) tarihinden küçük olamaz.")

    conn = None
    if args.dry_run:
        if not os.path.exists(args.db):
            print(f"HATA: Veritabanı bulunamadı: {args.db}", file=sys.stderr)
            sys.exit(1)
        db_uri = f"{Path(args.db).resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=60.0)
    else:
        os.makedirs(args.raw_dir, exist_ok=True)
        conn = init_db(args.db)

    try:
        conn.execute("PRAGMA busy_timeout=60000")
        rc = run_backfill(
            conn,
            args.raw_dir,
            args.start,
            args.end,
            delay=args.delay,
            max_races=args.max_races,
            dry_run=args.dry_run,
            reparse=args.reparse,
        )
    except KeyboardInterrupt:
        print("\nKesildi (Ctrl-C); fetch_log korundu, kaldığı yerden devam edilebilir.", flush=True)
        rc = 130
    finally:
        if conn is not None:
            conn.close()

    sys.exit(rc)


if __name__ == "__main__":
    main()
