"""Gözcü: her koşuyu algıla, yarış başlamadan tahminini yaz (launchd 5 dk'da bir çağırır).

Sabit saatli 'tekrar' işinin yerine geçer. Her çalışmada:
  1. Bugünün başlamamış, tahmini olmayan koşularını bulur (yeni/sürpriz seans dahil).
  2. Bu koşuların şehirlerinin program CSV'sini taze çeker (saat değişikliği, yeni AGF, iptal).
     Her 30 dk'da bir şehir keşfi de yapar: günün programına sonradan eklenen şehirleri yakalar.
  3. AGF'si yayınlanmış koşular için tahmin yazar (ilk kayıt kalıcı: INSERT OR IGNORE).
  4. Yarış saati geçtiği halde tahmini olmayan AGF'li koşuları 'KAÇTI' diye bildirir.
Bekleyen koşu yoksa ağa hiç dokunmadan çıkar.
"""
import argparse
import datetime
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db
from ganyan.tjk import domestic_cities
from scripts.forward_log import MODEL_VERSION, forward_log
from scripts.snapshot_agf import snapshot_agf

IST_TZ = ZoneInfo("Europe/Istanbul")
START_HM = "07:30"  # bundan önce çalışma (gece boş yere TJK'yı yoklama)
DISCOVERY_MIN = 30  # şehir keşfi aralığı (dk)
DISCOVERY_SLACK = 6  # çağrı aralığı 5 dk; keşif penceresi bu kadar geniş


def pending_races(conn, date_str, hm):
    """Başlamamış (post_time > hm), iptal/sonuç olmayan ve v1_agf tahmini olmayan koşular: [(race_id, city, post_time)]."""
    return conn.execute(
        """
        SELECT r.race_id, r.city, r.post_time FROM races r
        WHERE r.date = ? AND r.post_time IS NOT NULL AND r.post_time > ?
          AND r.status NOT IN ('result', 'cancelled')
          AND NOT EXISTS (SELECT 1 FROM predictions p WHERE p.race_id = r.race_id AND p.model_version = ?)
        ORDER BY r.post_time, r.city, r.race_no
        """,
        (date_str, hm, MODEL_VERSION),
    ).fetchall()


def agf_ready_ids(conn, race_ids):
    """AGF yayınlanmış (en az bir AGF'li snapshot satırı olan) koşular."""
    ids = list(race_ids)
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT DISTINCT race_id FROM agf_snapshots WHERE agf_pct IS NOT NULL AND race_id IN ({q})", ids
    ).fetchall()
    return [r[0] for r in rows]


def missed_races(conn, date_str, hm):
    """Saati geçmiş, AGF'si yayınlanmış ama tahmini olmayan koşular (AGF'siz koşular kaçmış sayılmaz)."""
    rows = conn.execute(
        """
        SELECT r.race_id, r.city, r.race_no, r.post_time FROM races r
        WHERE r.date = ? AND r.post_time IS NOT NULL AND r.post_time <= ? AND r.status != 'cancelled'
          AND EXISTS (SELECT 1 FROM agf_snapshots s WHERE s.race_id = r.race_id AND s.agf_pct IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM predictions p WHERE p.race_id = r.race_id AND p.model_version = ?)
        ORDER BY r.post_time, r.city, r.race_no
        """,
        (date_str, hm, MODEL_VERSION),
    ).fetchall()
    return [(rid, f"{city} {no}. koşu {pt}") for rid, city, no, pt in rows]


def _notify_missed(date_str, missed, mark_dir):
    """Kaçan koşu sayısı arttıkça (gün başına) macOS bildirimi göster."""
    if sys.platform != "darwin":
        return
    mark = os.path.join(mark_dir, f".gozcu_missed_{date_str}")
    try:
        seen = int(open(mark).read().strip())
    except (OSError, ValueError):
        seen = 0
    if len(missed) <= seen:
        return
    open(mark, "w").write(str(len(missed)))
    msg = f"{len(missed)} koşu tahminsiz kaçtı ({date_str}), son: {missed[-1][1]}"
    subprocess.run(
        ["osascript", "-e", f'display notification "{msg}" with title "Ganyan"'], check=False, capture_output=True
    )


def run(
    date_str,
    now,
    db_path="data/ganyan.db",
    prog_dir="data/raw/program",
    fetch=True,
    notify=True,
    force_discover=False,
):
    hm = now.strftime("%H:%M")
    if hm < START_HM:
        return 0
    conn = init_db(db_path)
    try:
        pend = pending_races(conn, date_str, hm)
        known = {r[0] for r in conn.execute("SELECT DISTINCT city FROM races WHERE date = ?", (date_str,))}
        discover = fetch and (force_discover or not known or now.minute % DISCOVERY_MIN < DISCOVERY_SLACK)
        if not pend and not discover:
            return 0

        cities = {c for _, c, _ in pend}
        if discover:
            cities |= set(domestic_cities(date_str, page_type="GunlukYarisProgrami"))
        if fetch and cities:
            snapshot_agf(date_str, db_path=db_path, prog_dir=prog_dir, cities=sorted(cities))

        # Taze program saat/iptal bilgisini getirmiş olabilir: yeniden oku.
        pend = pending_races(conn, date_str, hm)
        ready = agf_ready_ids(conn, [p[0] for p in pend])
        written = 0
        if ready:
            written = forward_log(date_str, db_path=db_path, prog_dir=prog_dir, do_snapshot=False, race_ids=ready)
        if written:
            left = {p[0] for p in pending_races(conn, date_str, hm)}
            done = [p for p in pend if p[0] in ready and p[0] not in left]
            desc = ", ".join(f"{c} {t}" for _, c, t in done)
            print(f"{date_str} {hm}: {len(done)} koşu için {written} tahmin yazıldı ({desc}); bekleyen {len(left)}")

        missed = missed_races(conn, date_str, hm)
        if missed:
            print(f"{date_str} {hm}: KAÇTI {len(missed)} koşu: " + "; ".join(m[1] for m in missed))
            if notify:
                _notify_missed(date_str, missed, os.path.dirname(os.path.abspath(db_path)))
        return written
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (varsayılan: bugün, İstanbul)")
    ap.add_argument("--now", help="YYYY-MM-DDTHH:MM (test için sahte saat)")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--force-discover", action="store_true")
    args = ap.parse_args()
    now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(IST_TZ)
    run(
        args.date or now.date().isoformat(),
        now,
        db_path=args.db,
        fetch=not args.no_fetch,
        notify=not args.no_notify,
        force_discover=args.force_discover,
    )


if __name__ == "__main__":
    main()
