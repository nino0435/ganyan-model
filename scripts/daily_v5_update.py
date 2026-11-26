"""Daily data updater for Model v5 live runner: TJK results/program, Yenibeygir speed, Liderform workouts."""
import argparse
import datetime
import io
import os
import sqlite3
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db
from ganyan.sources.fetch import fetch as fetch_raw_html
from ganyan.sources.yenibeygir import (
    city_slug as yb_city_slug,
    galop_url as yb_galop_url,
    parse_galop_page as parse_yb_galop_page,
)
from ganyan.tjk import DOMESTIC_CITIES
from scripts import backfill_liderform, backfill_yenibeygir
from scripts.update_daily import update_daily

IST_TZ = ZoneInfo("Europe/Istanbul")
GALOP_LOOKBACK_DAYS = 6


def _one_line(text):
    return " ".join(str(text or "").split())


def _log(msg):
    hms = datetime.datetime.now(IST_TZ).strftime("%H:%M:%S")
    print(f"[{hms}] {_one_line(msg)}", flush=True)


def _extract_notice_line(buf_text, prefixes):
    for raw in (buf_text or "").splitlines():
        line = _one_line(raw)
        if any(line.startswith(p) for p in prefixes):
            return line
    lines = [_one_line(x) for x in (buf_text or "").splitlines() if _one_line(x)]
    return lines[-1] if lines else ""


def _load_liderform_targets_incl_program(conn, start_date, end_date):
    """Load domestic non-cancelled races in [max(start, MIN_DATE), end] so today's scheduled card is included."""
    if conn is None:
        return []
    d_start = max(
        datetime.date.fromisoformat(str(start_date)).isoformat(),
        backfill_liderform.MIN_DATE,
    )
    d_end = datetime.date.fromisoformat(str(end_date)).isoformat()
    if d_end < d_start:
        return []
    placeholders = ",".join("?" for _ in DOMESTIC_CITIES)
    rows = conn.execute(
        f"""
        SELECT race_id, date, city, race_no
        FROM races
        WHERE COALESCE(status, '') != 'cancelled'
          AND date >= ?
          AND date <= ?
          AND city IN ({placeholders})
        ORDER BY date DESC, city ASC, race_no ASC
        """,
        (d_start, d_end, *DOMESTIC_CITIES),
    ).fetchall()
    return [(r[0], r[1], r[2], int(r[3])) for r in rows]


def _run_yb_galop_backfill(conn, raw_dir, start_date, end_date, delay=2.0):
    """Fetch and insert pre-race workouts from Yenibeygir `/galoplar` pages (no Cloudflare block)."""
    targets = _load_liderform_targets_incl_program(conn, start_date, end_date)
    races_ok = 0
    horses_n = 0
    total_w = 0
    inserted_w = 0
    unmatched = 0
    errors = 0

    for race_id, r_date, city, race_no in targets:
        slug = yb_city_slug(city)
        target_key = f"{r_date}/{slug}/{race_no}"
        raw_path = os.path.join(str(raw_dir), r_date[:4], f"{r_date}_{slug}_{race_no}.html.gz")
        url = yb_galop_url(r_date, city, race_no)
        html_text = fetch_raw_html(
            conn,
            "yenibeygir_galop",
            target_key,
            url,
            raw_path,
            delay=delay,
        )
        if not html_text:
            errors += 1
            continue

        horses, workouts = parse_yb_galop_page(html_text, r_date)
        races_ok += 1
        horses_n += len(horses)
        hk_by_no = {}
        for h in horses:
            hno = h.get("horse_number")
            if hno is None:
                continue
            hk = backfill_liderform.resolve_horse_key(conn, race_id, hno)
            if hk:
                hk_by_no[hno] = hk
            else:
                unmatched += 1

        rows_to_insert = []
        for w in workouts:
            hk = hk_by_no.get(w.get("horse_number"))
            if not hk:
                continue
            w_copy = dict(w)
            w_copy["horse_key"] = hk
            rows_to_insert.append(w_copy)

        total_w += len(rows_to_insert)
        if rows_to_insert:
            inserted_w += backfill_liderform.insert_workouts(conn, rows_to_insert, commit=True)

    return {
        "races": races_ok,
        "horses": horses_n,
        "workouts": total_w,
        "inserted": inserted_w,
        "unmatched": unmatched,
        "errors": errors,
    }


def run_daily_v5_update(
    date_str=None,
    db_path="data/ganyan.db",
    delay=2.0,
    res_dir="data/raw/results",
    prog_dir="data/raw/program",
    yb_raw_dir="data/raw/yenibeygir",
    lf_raw_dir="data/raw/liderform",
    galop_source="liderform",
) -> int:
    """Execute fail-soft daily TJK + Yenibeygir + Galop update; always returns 0."""
    d_today = (
        datetime.date.fromisoformat(str(date_str)[:10])
        if date_str is not None
        else datetime.datetime.now(IST_TZ).date()
    )
    today_s = d_today.isoformat()
    yest_s = (d_today - datetime.timedelta(days=1)).isoformat()
    yest2_s = (d_today - datetime.timedelta(days=2)).isoformat()

    # (i) TJK: yesterday's results + today's program (call update_daily for yesterday and today)
    try:
        update_daily(yest_s, db_path=db_path, res_dir=res_dir, prog_dir=prog_dir)
        update_daily(today_s, db_path=db_path, res_dir=res_dir, prog_dir=prog_dir)
        chk = sqlite3.connect(str(db_path), timeout=30)
        try:
            n_res = chk.execute(
                "SELECT COUNT(*) FROM races WHERE date = ? AND status = 'result'",
                (yest_s,),
            ).fetchone()[0]
            n_prog = chk.execute(
                "SELECT COUNT(*) FROM races WHERE date = ? AND COALESCE(status, '') != 'cancelled'",
                (today_s,),
            ).fetchone()[0]
        finally:
            chk.close()
        if n_res == 0 and n_prog == 0:
            _log(f"UYARI: tjk güncellenemedi ({yest_s} sonuç=0, {today_s} program=0)")
        else:
            _log(f"tjk güncellendi ({yest_s} sonuç={n_res}, {today_s} koşu={n_prog})")
    except Exception as exc:
        _log(f"UYARI: tjk güncellenemedi ({exc})")

    # (ii) Yenibeygir: [yesterday - 1, yesterday], delay=2.0
    try:
        buf_yb = io.StringIO()
        yb_code, yb_summaries = backfill_yenibeygir.run_backfill(
            db_path=db_path,
            raw_dir=yb_raw_dir,
            start=yest2_s,
            end=yest_s,
            delay=delay,
            out=buf_yb,
        )
        if yb_code != 0:
            detail = _extract_notice_line(buf_yb.getvalue(), ("DURDURULDU", "HATA"))
            suffix = f", {detail}" if detail else ""
            _log(f"UYARI: yenibeygir güncellenemedi (kod={yb_code}{suffix})")
        else:
            yb_races = sum(int(st.get("races", 0)) for st in (yb_summaries or {}).values())
            yb_hiz = sum(int(st.get("hiz_filled", 0)) for st in (yb_summaries or {}).values())
            _log(f"yenibeygir güncellendi ({yest2_s}..{yest_s}: yeni_koşu={yb_races}, hız_dolu={yb_hiz})")
    except Exception as exc:
        _log(f"UYARI: yenibeygir güncellenemedi ({exc})")

    # (iii) Galop: [today - GALOP_LOOKBACK_DAYS, today] (pre-race galop pages), delay=2.0
    # Geniş pencere: yenibeygir_galop günde bir kez çalıştığından, [dün, bugün] tek
    # başına bazı şehirlerin koşu günlerini kaçırabiliyordu (örn. 2 günlük pencereye
    # denk gelmeyen şehirler). fetch_log zaten 'ok' olan hedefleri atladığından
    # (ganyan/sources/fetch.py: fetched_ok), pencereyi genişletmek ek maliyet
    # yaratmadan kaçırılanları yakalar.
    if galop_source == "yenibeygir":
        try:
            yb_galop_dir = f"{yb_raw_dir}_galop"
            os.makedirs(yb_galop_dir, exist_ok=True)
            galop_start_s = (d_today - datetime.timedelta(days=GALOP_LOOKBACK_DAYS)).isoformat()
            conn = init_db(db_path)
            try:
                conn.execute("PRAGMA busy_timeout=60000")
                st = _run_yb_galop_backfill(conn, yb_galop_dir, galop_start_s, today_s, delay=delay)
            finally:
                conn.close()
            if st["races"] == 0 and st["errors"] > 0:
                _log(f"UYARI: yenibeygir galop güncellenemedi (hata={st['errors']})")
            else:
                _log(
                    f"yenibeygir galop güncellendi ({galop_start_s}..{today_s}: "
                    f"koşu={st['races']} at={st['horses']} galop={st['workouts']} "
                    f"(yeni={st['inserted']}) eşleşmeyen_at={st['unmatched']} hata={st['errors']})"
                )
        except Exception as exc:
            _log(f"UYARI: yenibeygir galop güncellenemedi ({exc})")
        return 0

    try:
        os.makedirs(str(lf_raw_dir), exist_ok=True)
        conn = init_db(db_path)
        try:
            conn.execute("PRAGMA busy_timeout=60000")
            buf_lf = io.StringIO()
            with patch.object(
                backfill_liderform,
                "load_target_races",
                _load_liderform_targets_incl_program,
            ):
                lf_code = backfill_liderform.run_backfill(
                    conn,
                    lf_raw_dir,
                    yest_s,
                    today_s,
                    delay=delay,
                    out=buf_lf,
                )
        finally:
            conn.close()

        if lf_code != 0:
            detail = _extract_notice_line(buf_lf.getvalue(), ("ENGEL", "HATA"))
            suffix = f", {detail}" if detail else ""
            _log(f"UYARI: liderform güncellenemedi (kod={lf_code}{suffix})")
        else:
            yr_lines = [
                _one_line(ln)
                for ln in buf_lf.getvalue().splitlines()
                if _one_line(ln).startswith("[Yıl ")
            ]
            summary_txt = "; ".join(yr_lines) if yr_lines else "yeni sayfa yok"
            _log(f"liderform güncellendi ({yest_s}..{today_s}: {summary_txt})")
    except Exception as exc:
        _log(f"UYARI: liderform güncellenemedi ({exc})")

    return 0


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Model v5 canlı akışı için günlük TJK + Yenibeygir + Liderform/Yenibeygir galop güncellemesi."
    )
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (varsayılan: İstanbul bugün)")
    ap.add_argument("--db", default="data/ganyan.db", help="Ana SQLite veritabanı yolu")
    ap.add_argument("--delay", type=float, default=2.0, help="İstekler arası bekleme süresi (sn)")
    ap.add_argument("--yb-raw-dir", default="data/raw/yenibeygir", help="Yenibeygir ham HTML dizini")
    ap.add_argument("--lf-raw-dir", default="data/raw/liderform", help="Liderform ham HTML dizini")
    ap.add_argument(
        "--galop-source",
        choices=("liderform", "yenibeygir"),
        default="liderform",
        help="Galop kaynağı (yerelde liderform, Actions bulutunda yenibeygir)",
    )
    return ap


def main(argv=None):
    ap = build_arg_parser()
    try:
        args = ap.parse_args(argv)
        run_daily_v5_update(
            date_str=args.date,
            db_path=args.db,
            delay=args.delay,
            yb_raw_dir=args.yb_raw_dir,
            lf_raw_dir=args.lf_raw_dir,
            galop_source=args.galop_source,
        )
    except Exception as exc:
        _log(f"UYARI: daily_v5_update genel hata ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
