"""GitHub Actions tek giriş betiği (§2.2, §2.3): tahmin ve aksam modları.

Kullanım:
  python -I scripts/actions_run.py tahmin|aksam [--date YYYY-MM-DD] [--db PATH] [--state-dir PATH] [--dry-run]
"""
import argparse
import csv
import datetime
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db
from scripts import gozcu
from scripts.actions_budget import (
    IST_TZ,
    OVERHEAD_SEC_AKSAM,
    OVERHEAD_SEC_TAHMIN,
    ceil_billed_min,
    format_budget_summary,
    karar,
    load_budget,
    project_month_min,
    record_run,
    save_budget,
)
from scripts.forward_report import forward_report
from scripts.update_daily import update_daily

MIN_RACES_DEFAULT = 1000
CSV_COLUMNS = ("race_id", "prog_no", "model_version", "created_at", "p_win", "agf_used")


class StateValidationError(RuntimeError):
    """Durum (veritabanı) doğrulaması başarısız olduğunda fırlatılır."""


def validate_db(db_path, high_water=0, min_races=MIN_RACES_DEFAULT):
    """Veritabanı bütünlüğünü ve satır sayısı alt sınırlarını doğrula (§2.3).

    Kontroller:
      1. Dosya var ve boyutu > 0
      2. PRAGMA integrity_check = ok
      3. races >= min_races (varsayılan 1000)
      4. predictions >= high_water (budget.json içindeki predictions_high_water)
    """
    if not db_path or not os.path.exists(db_path):
        raise StateValidationError(f"Veritabanı bulunamadı: {db_path}")
    if os.path.getsize(db_path) == 0:
        raise StateValidationError(f"Veritabanı dosyası boş (0 bayt): {db_path}")

    try:
        conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as exc:
        raise StateValidationError(f"Veritabanı açılamadı ({db_path}): {exc}") from exc

    try:
        chk = conn.execute("PRAGMA integrity_check").fetchone()
        if not chk or str(chk[0]).lower() != "ok":
            raise StateValidationError(f"PRAGMA integrity_check başarısız: {chk}")

        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "races" not in tables or "predictions" not in tables:
            raise StateValidationError("Veritabanı şeması eksik (races/predictions tablosu yok)")

        n_races = int(conn.execute("SELECT COUNT(*) FROM races").fetchone()[0])
        if n_races < int(min_races):
            raise StateValidationError(f"races satır sayısı yetersiz: {n_races} < {min_races}")

        n_preds = int(conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0])
        if n_preds < int(high_water):
            raise StateValidationError(
                f"Veri kaybı alarmı: predictions ({n_preds}) < predictions_high_water ({high_water})"
            )

        return {
            "ok": True,
            "races": n_races,
            "predictions": n_preds,
            "high_water": int(high_water),
        }
    except sqlite3.Error as exc:
        raise StateValidationError(f"Veritabanı sorgu hatası ({db_path}): {exc}") from exc
    finally:
        conn.close()


def _try_download_release_archive(tag, archive_path="ganyan-state.tar.zst", extract_dir="."):
    """Önbellek boşsa GitHub Release varlığından (state-backup / state-seed) durumu indir ve aç."""
    if not shutil.which("gh"):
        return False
    res = subprocess.run(
        ["gh", "release", "download", tag, "-p", os.path.basename(archive_path), "-D", os.path.dirname(os.path.abspath(archive_path)) or ".", "--clobber"],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0 or not os.path.exists(archive_path):
        return False
    ext = subprocess.run(
        ["tar", "--zstd", "-xf", archive_path, "-C", extract_dir],
        check=False,
        capture_output=True,
        text=True,
    )
    return ext.returncode == 0


def ensure_state(
    db_path="data/ganyan.db",
    state_dir="state",
    min_races=MIN_RACES_DEFAULT,
    allow_release_fallback=False,
    fallback_loader=None,
):
    """Durum sağlama (§2.3): (a) önbellek/mevcut DB -> (b) state-backup -> (b) state-seed.

    Başarısızsa StateValidationError fırlatır.
    """
    budget_path = os.path.join(str(state_dir), "budget.json") if state_dir else None
    high_water = 0
    if budget_path and os.path.exists(budget_path):
        st = load_budget(budget_path)
        high_water = int(st.get("predictions_high_water", 0))

    last_err = None
    try:
        info = validate_db(db_path, high_water=high_water, min_races=min_races)
        info["source"] = "cache_or_local"
        return info
    except StateValidationError as err:
        last_err = err

    if allow_release_fallback or fallback_loader is not None:
        loader = fallback_loader or _try_download_release_archive
        for tag in ("state-backup", "state-seed"):
            try:
                if loader(tag):
                    info = validate_db(db_path, high_water=high_water, min_races=min_races)
                    info["source"] = tag
                    return info
            except StateValidationError as err:
                last_err = err

    raise last_err


def db_fingerprint(db_path):
    """Veritabanı değişimini algılamak için tablo satır sayıları ve dosya SHA256 özeti."""
    if not db_path or not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return None
    h = hashlib.sha256()
    with open(db_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    counts = {}
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=30)
    try:
        for tbl in ("races", "runners", "altili", "bets", "agf_snapshots", "predictions"):
            try:
                counts[tbl] = int(conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
            except sqlite3.Error:
                counts[tbl] = -1
    finally:
        conn.close()
    return {"sha256": h.hexdigest(), "counts": counts}


def append_predictions_csv(conn, date_str, csv_path, since_iso=None):
    """Yeni yazılan tahminleri state/predictions/D.csv'ye ekle (aynı PK iki kez yazılmaz).

    Dönüş: (eklenen_satir_sayisi, eklenen_kosu_sayisi)
    """
    existing_pks = set()
    file_exists = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
    if file_exists:
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = (row.get("race_id") or "").strip()
                pno = (row.get("prog_no") or "").strip()
                mv = (row.get("model_version") or "").strip()
                if rid and pno and mv:
                    existing_pks.add((rid, int(pno), mv))

    params = [date_str, f"{date_str}_%"]
    where_since = ""
    if since_iso:
        where_since = " AND p.created_at >= ?"
        params.append(since_iso)

    rows = conn.execute(
        f"""
        SELECT p.race_id, p.prog_no, p.model_version, p.created_at, p.p_win, p.agf_used
        FROM predictions p
        LEFT JOIN races r ON p.race_id = r.race_id
        WHERE (r.date = ? OR p.race_id LIKE ?){where_since}
        ORDER BY p.race_id, p.prog_no, p.model_version
        """,
        tuple(params),
    ).fetchall()

    new_rows = []
    new_races = set()
    for race_id, prog_no, model_version, created_at, p_win, agf_used in rows:
        pk = (race_id, int(prog_no), model_version)
        if pk in existing_pks:
            continue
        existing_pks.add(pk)
        new_races.add(race_id)
        new_rows.append({
            "race_id": race_id,
            "prog_no": int(prog_no),
            "model_version": model_version,
            "created_at": created_at,
            "p_win": p_win,
            "agf_used": "" if agf_used is None else agf_used,
        })

    if not new_rows:
        return 0, 0

    parent = os.path.dirname(str(csv_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)

    return len(new_rows), len(new_races)


def pack_state_archive(db_path="data/ganyan.db", raw_dir="data/raw", out_archive="ganyan-state.tar.zst"):
    """SQLite veritabanını ve data/raw klasörünü tar.zst olarak paketle."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Veritabanı bulunamadı: {db_path}")
    items = [db_path]
    if raw_dir and os.path.exists(raw_dir):
        items.append(raw_dir)
    res = subprocess.run(
        ["tar", "--zstd", "-cf", out_archive, *items],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"tar.zst paketleme hatası: {res.stderr.strip()}")
    return out_archive


def _write_step_summary(summary_line):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(summary_line + "\n")
    except OSError:
        pass


def _write_github_outputs(outputs):
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            for k, v in outputs.items():
                f.write(f"{k}={v}\n")
    except OSError:
        pass


def _elapsed_seconds(start_monotonic):
    env_epoch = os.environ.get("GANYAN_JOB_START_EPOCH")
    if env_epoch:
        try:
            return max(1.0, time.time() - float(env_epoch))
        except ValueError:
            pass
    return max(1.0, time.monotonic() - start_monotonic)


def run_tahmin(
    date_str=None,
    now=None,
    db_path="data/ganyan.db",
    state_dir="state",
    prog_dir="data/raw/program",
    dry_run=False,
    min_races=MIN_RACES_DEFAULT,
):
    start_m = time.monotonic()
    now = now or datetime.datetime.now(IST_TZ)
    d_str = date_str or now.date().isoformat()
    hm = now.strftime("%H:%M")
    budget_path = os.path.join(str(state_dir), "budget.json")

    allow_fallback = (not dry_run) and (os.environ.get("GITHUB_ACTIONS") == "true")
    state_info = ensure_state(
        db_path=db_path,
        state_dir=state_dir,
        min_races=min_races,
        allow_release_fallback=allow_fallback,
    )

    budget = load_budget(budget_path, month_str=now.strftime("%Y-%m"))
    decision = karar(now, "tahmin", budget)
    if decision["error"]:
        print(f"::error::{decision['reason']}")

    if decision["karar"] == "atla":
        elapsed = _elapsed_seconds(start_m)
        if not dry_run:
            budget = record_run(
                budget,
                now,
                "tahmin",
                elapsed_sec=elapsed,
                overhead_sec=OVERHEAD_SEC_TAHMIN,
                predictions_count=state_info["predictions"],
            )
            save_budget(budget_path, budget)
        summary = f"[tahmin {d_str} {hm}] ATLANDI ({decision['reason']}) | {format_budget_summary(budget, now=now)}"
        print(summary)
        _write_step_summary(summary)
        _write_github_outputs({
            "db_changed": "false",
            "state_changed": "false" if dry_run else "true",
            "new_predictions": "0",
            "new_races": "0",
            "skipped_budget": "true",
            "commit_msg": f"tahmin {d_str} {hm}: bekleyen yok",
        })
        return 0

    if dry_run:
        conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=30)
        try:
            pend = gozcu.pending_races(conn, d_str, hm)
            ready = gozcu.agf_ready_ids(conn, [p[0] for p in pend])
            missed = gozcu.missed_races(conn, d_str, hm)
        finally:
            conn.close()
        elapsed = _elapsed_seconds(start_m)
        summary = (
            f"[DRY-RUN tahmin {d_str} {hm}] yazılan=0 (hazır_agf={len(ready)}), "
            f"bekleyen={len(pend)}, kaçan={len(missed)}, süre={elapsed:.1f}s | "
            f"{format_budget_summary(budget, now=now)}"
        )
        print(summary)
        _write_step_summary(summary)
        _write_github_outputs({
            "db_changed": "false",
            "state_changed": "false",
            "new_predictions": "0",
            "new_races": "0",
            "commit_msg": f"tahmin {d_str} {hm}: bekleyen yok",
        })
        return 0

    before_fp = db_fingerprint(db_path)
    wall_iso = datetime.datetime.now(IST_TZ).strftime("%Y-%m-%dT%H:%M:%S")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    run_start_iso = min(wall_iso, now_iso)

    written = gozcu.run(
        d_str,
        now,
        db_path=db_path,
        prog_dir=prog_dir,
        fetch=True,
        notify=False,
        force_discover=True,
    )

    conn = init_db(db_path)
    try:
        csv_path = os.path.join(str(state_dir), "predictions", f"{d_str}.csv")
        csv_rows, csv_races = append_predictions_csv(conn, d_str, csv_path, since_iso=run_start_iso)
        pend_after = gozcu.pending_races(conn, d_str, hm)
        missed = gozcu.missed_races(conn, d_str, hm)
        total_preds = int(conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0])
    finally:
        conn.close()

    if missed:
        missed_desc = "; ".join(m[1] for m in missed)
        print(f"::warning::KAÇTI ({d_str} {hm}, {len(missed)} koşu): {missed_desc}")

    after_fp = db_fingerprint(db_path)
    db_changed = before_fp != after_fp
    elapsed = _elapsed_seconds(start_m)
    total_sec = elapsed + OVERHEAD_SEC_TAHMIN

    budget = record_run(
        budget,
        now,
        "tahmin",
        elapsed_sec=elapsed,
        overhead_sec=OVERHEAD_SEC_TAHMIN,
        predictions_count=max(state_info["predictions"], total_preds),
    )
    save_budget(budget_path, budget)

    summary = (
        f"[tahmin {d_str} {hm}] yazılan={written} ({csv_races} koşu), "
        f"bekleyen={len(pend_after)}, kaçan={len(missed)}, "
        f"süre={elapsed:.1f}s+{OVERHEAD_SEC_TAHMIN}s ({ceil_billed_min(total_sec)} dk) | "
        f"{format_budget_summary(budget, now=now)}"
    )
    print(summary)
    _write_step_summary(summary)
    commit_msg = (
        f"tahmin {d_str} {hm}: {csv_races} koşu"
        if csv_races > 0
        else f"tahmin {d_str} {hm}: bekleyen yok"
    )
    _write_github_outputs({
        "db_changed": "true" if db_changed else "false",
        "state_changed": "false" if dry_run else "true",
        "new_predictions": str(csv_rows),
        "new_races": str(csv_races),
        "commit_msg": commit_msg,
    })
    return 0


def run_aksam(
    date_str=None,
    now=None,
    db_path="data/ganyan.db",
    state_dir="state",
    res_dir="data/raw/results",
    prog_dir="data/raw/program",
    dry_run=False,
    min_races=MIN_RACES_DEFAULT,
    pack_archive=None,
):
    start_m = time.monotonic()
    now = now or datetime.datetime.now(IST_TZ)
    y_date = (
        datetime.date.fromisoformat(date_str)
        if date_str
        else (now.date() - datetime.timedelta(days=1))
    )
    y_str = y_date.isoformat()
    y_prev_str = (y_date - datetime.timedelta(days=1)).isoformat()
    budget_path = os.path.join(str(state_dir), "budget.json")

    allow_fallback = (not dry_run) and (os.environ.get("GITHUB_ACTIONS") == "true")
    state_info = ensure_state(
        db_path=db_path,
        state_dir=state_dir,
        min_races=min_races,
        allow_release_fallback=allow_fallback,
    )

    budget = load_budget(budget_path, month_str=now.strftime("%Y-%m"))
    _ = karar(now, "aksam", budget)  # aksam ASLA bütçe yüzünden atlanmaz

    if dry_run:
        elapsed = _elapsed_seconds(start_m)
        summary = (
            f"[DRY-RUN aksam {y_str}] telafi={y_prev_str}, "
            f"races={state_info['races']}, predictions={state_info['predictions']}, "
            f"süre={elapsed:.1f}s | {format_budget_summary(budget, now=now)}"
        )
        print(summary)
        _write_step_summary(summary)
        _write_github_outputs({
            "db_changed": "false",
            "state_changed": "false",
            "target_date": y_str,
        })
        return 0

    before_fp = db_fingerprint(db_path)

    update_daily(y_str, db_path=db_path, res_dir=res_dir, prog_dir=prog_dir, fetch=True)
    update_daily(y_prev_str, db_path=db_path, res_dir=res_dir, prog_dir=prog_dir, fetch=True)

    report_out = os.path.join(str(state_dir), "FORWARD.md")
    forward_report(db_path=db_path, out_path=report_out)

    after_fp = db_fingerprint(db_path)
    db_changed = before_fp != after_fp
    total_preds = after_fp["counts"].get("predictions", state_info["predictions"]) if after_fp else state_info["predictions"]
    elapsed = _elapsed_seconds(start_m)
    total_sec = elapsed + OVERHEAD_SEC_AKSAM

    budget = record_run(
        budget,
        now,
        "aksam",
        elapsed_sec=elapsed,
        overhead_sec=OVERHEAD_SEC_AKSAM,
        predictions_count=max(state_info["predictions"], total_preds),
    )
    save_budget(budget_path, budget)

    if pack_archive:
        raw_root = os.path.dirname(os.path.abspath(prog_dir))
        pack_state_archive(db_path=db_path, raw_dir=raw_root, out_archive=pack_archive)

    summary = (
        f"[aksam {y_str}] telafi={y_prev_str}, rapor={report_out}, "
        f"db_changed={db_changed}, süre={elapsed:.1f}s+{OVERHEAD_SEC_AKSAM}s ({ceil_billed_min(total_sec)} dk) | "
        f"{format_budget_summary(budget, now=now)}"
    )
    print(summary)
    _write_step_summary(summary)
    _write_github_outputs({
        "db_changed": "true" if db_changed else "false",
        "state_changed": "true",
        "target_date": y_str,
        "commit_msg": f"aksam {y_str}: rapor ve bütçe güncellendi",
    })
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="GitHub Actions Ganyan giriş betiği")
    ap.add_argument("mode", choices=["tahmin", "aksam"], help="Çalışma modu: tahmin | aksam")
    ap.add_argument("--date", default=None, help="Hedef tarih YYYY-MM-DD")
    ap.add_argument("--now", default=None, help="Test için sahte zaman YYYY-MM-DDTHH:MM(:SS)")
    ap.add_argument("--db", default="data/ganyan.db", help="SQLite veritabanı yolu")
    ap.add_argument("--state-dir", default="state", help="Durum klasörü (varsayılan: state)")
    ap.add_argument("--prog-dir", default="data/raw/program", help="Program CSV klasörü")
    ap.add_argument("--res-dir", default="data/raw/results", help="Sonuç CSV klasörü")
    ap.add_argument("--pack-archive", default=None, help="Aksam modunda durum paketi oluştur (ör. ganyan-state.tar.zst)")
    ap.add_argument("--dry-run", action="store_true", help="Ağ ve veritabanı yazımı yapmadan doğrula")
    args = ap.parse_args(argv)

    now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(IST_TZ)

    try:
        if args.mode == "tahmin":
            return run_tahmin(
                date_str=args.date,
                now=now,
                db_path=args.db,
                state_dir=args.state_dir,
                prog_dir=args.prog_dir,
                dry_run=args.dry_run,
            )
        return run_aksam(
            date_str=args.date,
            now=now,
            db_path=args.db,
            state_dir=args.state_dir,
            res_dir=args.res_dir,
            prog_dir=args.prog_dir,
            dry_run=args.dry_run,
            pack_archive=args.pack_archive,
        )
    except StateValidationError as err:
        print(f"::error::Durum doğrulaması başarısız: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
