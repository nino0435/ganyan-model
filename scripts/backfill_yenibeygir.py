"""Backfill Yenibeygir speed ratings ('hiz' and numeric 'blt') from 2010 onwards."""
import argparse
import datetime as dt
import gzip
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ganyan.db import fetched_ok, init_db  # noqa: E402
from ganyan.sources.fetch import fetch  # noqa: E402
from ganyan.sources.yenibeygir import (  # noqa: E402
    FETCH_SOURCE,
    SOURCE,
    city_slug,
    match_and_save_ratings,
    parse_results_page,
    results_url,
)
from ganyan.tjk import DOMESTIC_CITIES, UA  # noqa: E402

MIN_DATE = "2010-01-01"


def _read_gz_or_plain(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        return None
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def is_guvenliinternet(url_or_none, body_or_text):
    """Return True if response URL or HTML indicates Türk Telekom 'guvenliinternet' block."""
    if url_or_none and "guvenliinternet" in str(url_or_none).lower():
        return True
    if not body_or_text:
        return False
    if isinstance(body_or_text, bytes):
        sample = body_or_text[:32768].decode("utf-8", errors="replace")
    else:
        sample = str(body_or_text)[:32768]
    return "guvenliinternet" in sample.lower()


def make_yenibeygir_getter(
    block_state,
    urlopen_fn=urllib.request.urlopen,
    tries=2,
    timeout=20,
    retry_sleep=1.0,
    sleep_fn=time.sleep,
):
    """Build an HTTP getter compatible with ``fetch(..., getter=...)``.

    On ``guvenliinternet`` redirect/body or network/connection error, sets
    ``block_state['reason']`` and returns ``(None, b'')`` so ``fetch()`` will not
    cache a poisoned block page as ``status='ok'``.
    """

    def _getter(url, extra_headers=None):
        headers = {"User-Agent": UA}
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(max(1, tries)):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urlopen_fn(req, timeout=timeout) as resp:
                    status = getattr(resp, "status", None) or resp.getcode()
                    final_url = resp.geturl() if hasattr(resp, "geturl") else url
                    body = resp.read()
                if is_guvenliinternet(final_url, body):
                    block_state["reason"] = f"guvenliinternet yönlendirmesi algılandı ({final_url})"
                    return None, b""
                return status, body
            except urllib.error.HTTPError as e:
                err_url = e.geturl() if hasattr(e, "geturl") else url
                err_body = b""
                try:
                    err_body = e.read()
                except Exception:
                    pass
                if is_guvenliinternet(err_url, err_body):
                    block_state["reason"] = f"guvenliinternet yönlendirmesi algılandı (HTTP {e.code})"
                    return None, b""
                if e.code == 404:
                    return 404, b""
                if attempt + 1 < tries:
                    sleep_fn(retry_sleep * (attempt + 1))
                else:
                    return e.code, b""
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if is_guvenliinternet(str(e), ""):
                    block_state["reason"] = f"guvenliinternet engeli ({e})"
                    return None, b""
                if attempt + 1 < tries:
                    sleep_fn(retry_sleep * (attempt + 1))
                else:
                    block_state["reason"] = f"bağlantı hatası ({e})"
                    return None, b""
        return None, b""

    return _getter


def list_target_city_days(conn, start_date=MIN_DATE, end_date=None):
    """Return ``[(date, city), ...]`` domestic pairs in DB (>= 2010-01-01), newest-to-oldest."""
    eff_start = max(str(start_date), MIN_DATE)
    placeholders = ",".join("?" for _ in DOMESTIC_CITIES)
    params = [eff_start, end_date, end_date, *DOMESTIC_CITIES]
    rows = conn.execute(
        f"""
        SELECT DISTINCT date, city
        FROM races
        WHERE date >= ?
          AND (? IS NULL OR date <= ?)
          AND city IN ({placeholders})
          AND COALESCE(status, 'result') = 'result'
        ORDER BY date DESC, city ASC
        """,
        params,
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def has_city_ratings(conn, date_str, city):
    """Return True if ``ext_ratings`` already has Yenibeygir rows for ``(date_str, city)``."""
    row = conn.execute(
        """
        SELECT 1
        FROM ext_ratings er
        JOIN races r ON r.race_id = er.race_id
        WHERE er.source = ? AND r.date = ? AND r.city = ?
        LIMIT 1
        """,
        (SOURCE, date_str, city),
    ).fetchone()
    return row is not None


def write_city_day_ratings(conn, parsed, date_str):
    """Write a single ``(date, city)`` page's ratings inside its own short transaction."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")  # okuyup sonra yazan işlemde eşzamanlı yazıcıyla kilit çakışmasını önler
    try:
        stats = match_and_save_ratings(conn, parsed, date_str, commit=False, write=True)
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise


def _dry_get_html(url, raw_path, getter, delay, sleep_fn, block_state):
    """Read local raw .html.gz if cached, else download in-memory without writing to disk/DB."""
    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
        try:
            cached = _read_gz_or_plain(raw_path)
            if cached:
                return cached
        except OSError:
            pass

    st, body = getter(url, extra_headers=None)
    if block_state.get("reason"):
        return None
    if delay and delay > 0:
        sleep_fn(delay)
    if st == 200 and body and body.strip():
        if isinstance(body, str):
            return body
        return body.decode("utf-8", errors="replace")
    return None


def _new_year_stats():
    return {
        "dates": set(),
        "races": 0,
        "runners": 0,
        "hiz_filled": 0,
        "unmatched": 0,
    }


def _print_year_summary(year, st, out=sys.stdout):
    if year is None or st is None:
        return
    print(
        f"[Yıl {year}] gün={len(st['dates'])}, koşu={st['races']}, "
        f"at={st['runners']}, hız dolu={st['hiz_filled']}, eşleşmeyen={st['unmatched']}",
        file=out,
        flush=True,
    )


def run_backfill(
    db_path,
    raw_dir="data/raw/yenibeygir",
    start=MIN_DATE,
    end=None,
    delay=2.0,
    max_days=None,
    dry_run=False,
    urlopen_fn=urllib.request.urlopen,
    sleep_fn=time.sleep,
    out=sys.stdout,
):
    """Execute Yenibeygir backfill; returns ``(exit_code, year_summaries_dict)``."""
    d_start = dt.date.fromisoformat(start)
    if end is not None:
        d_end = dt.date.fromisoformat(end)
        if d_end < d_start:
            raise ValueError(f"--end ({end}) --start ({start}) tarihinden küçük olamaz.")

    if not os.path.exists(str(db_path)):
        if dry_run:
            print(f"HATA: DB bulunamadı: {db_path}", file=out, flush=True)
            return 1, {}
        conn = init_db(db_path)
    elif dry_run:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    else:
        os.makedirs(str(raw_dir), exist_ok=True)
        conn = init_db(db_path)

    conn.execute("PRAGMA busy_timeout=60000")

    block_state = {"reason": None}
    getter = make_yenibeygir_getter(
        block_state,
        urlopen_fn=urlopen_fn,
        sleep_fn=sleep_fn,
    )

    def _guarded_sleep(sec):
        if not block_state.get("reason") and sec and sec > 0:
            sleep_fn(sec)

    cur_year = None
    year_stats = None
    all_summaries = {}
    seen_days = set()
    exit_code = 0

    try:
        targets = list_target_city_days(conn, start_date=start, end_date=end)
        for date_str, city in targets:
            slug = city_slug(city)
            target_key = f"{date_str}:{city}"
            raw_path = os.path.join(str(raw_dir), date_str[:4], f"{date_str}_{slug}.html.gz")

            if (
                not dry_run
                and fetched_ok(conn, FETCH_SOURCE, target_key)
                and os.path.exists(raw_path)
                and has_city_ratings(conn, date_str, city)
            ):
                continue

            if max_days is not None and date_str not in seen_days and len(seen_days) >= max_days:
                break

            yr = int(date_str[:4])
            if yr != cur_year:
                if cur_year is not None:
                    _print_year_summary(cur_year, year_stats, out=out)
                cur_year = yr
                year_stats = _new_year_stats()
                all_summaries[cur_year] = year_stats

            seen_days.add(date_str)

            url = results_url(date_str, city)
            if dry_run:
                html_text = _dry_get_html(url, raw_path, getter, delay, _guarded_sleep, block_state)
            else:
                html_text = fetch(
                    conn,
                    FETCH_SOURCE,
                    target_key,
                    url,
                    raw_path,
                    headers=None,
                    delay=delay,
                    getter=getter,
                    sleep_fn=_guarded_sleep,
                )

            if block_state.get("reason"):
                print(
                    f"DURDURULDU ({date_str} {city}): {block_state['reason']} — WARP kapalı olabilir.",
                    file=out,
                    flush=True,
                )
                exit_code = 2
                break

            if html_text and is_guvenliinternet(url, html_text):
                print(
                    f"DURDURULDU ({date_str} {city}): guvenliinternet içeriği algılandı — WARP kapalı olabilir.",
                    file=out,
                    flush=True,
                )
                exit_code = 2
                break

            if not html_text:
                continue

            parsed = parse_results_page(html_text, date_str)
            if not parsed.get("races"):
                continue

            # If Yenibeygir fell back to a different city because requested city had no card, skip
            if parsed.get("city") and city_slug(parsed["city"]) != slug:
                continue

            if dry_run:
                stats = match_and_save_ratings(conn, parsed, date_str, commit=False, write=False)
            else:
                stats = write_city_day_ratings(conn, parsed, date_str)

            year_stats["dates"].add(date_str)
            year_stats["races"] += stats["races"]
            year_stats["runners"] += stats["runners"]
            year_stats["hiz_filled"] += stats["hiz_filled"]
            year_stats["unmatched"] += stats["unmatched"]
    except KeyboardInterrupt:
        print("\nKesildi (Ctrl-C); fetch_log korundu, kaldığı yerden devam edilebilir.", file=out, flush=True)
        exit_code = 130
    finally:
        _print_year_summary(cur_year, year_stats, out=out)
        conn.close()

    return exit_code, all_summaries


def main():
    ap = argparse.ArgumentParser(description="Yenibeygir hız puanı geri doldurma (2010 ->).")
    ap.add_argument("--start", default=MIN_DATE)
    ap.add_argument("--end", default=None)
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--raw-dir", default="data/raw/yenibeygir")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--max-days", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        code, _ = run_backfill(
            db_path=args.db,
            raw_dir=args.raw_dir,
            start=args.start,
            end=args.end,
            delay=args.delay,
            max_days=args.max_days,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        ap.error(str(exc))
        return

    sys.exit(code)


if __name__ == "__main__":
    main()
