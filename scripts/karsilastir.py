"""Mac ve GitHub Actions tahminlerini gün gün karşılaştırma aracı (§6, salt okunur).

Kullanım:
  python -I scripts/karsilastir.py --mac MAC.db --actions ACTIONS.db [--from YYYY-MM-DD]
"""
import argparse
import datetime
import os
import sqlite3
import sys


def _parse_iso_naive(ts_str):
    if not ts_str:
        return None
    s = str(ts_str).strip()
    try:
        dt = datetime.datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        try:
            return datetime.datetime.fromisoformat(s[:19])
        except ValueError:
            return None


def _load_db_snapshot(db_path, model_version="v1_agf", from_date=None):
    """Salt okunur bağlantıyla yarışları ve geçerli (yarış öncesi) tahminleri yükle."""
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=30)
    try:
        where_date = "AND date >= ?" if from_date else ""
        params_r = (from_date,) if from_date else ()
        race_rows = conn.execute(
            f"""
            SELECT race_id, date, post_time, status
            FROM races
            WHERE (status IS NULL OR status != 'cancelled') {where_date}
            """,
            params_r,
        ).fetchall()
        races = {}
        for rid, d_str, pt, status in race_rows:
            races[rid] = {
                "date": str(d_str or rid[:10]),
                "post_time": str(pt or "00:00"),
                "status": status,
            }

        pred_rows = conn.execute(
            """
            SELECT p.race_id, p.prog_no, p.created_at, p.p_win, r.date, r.post_time
            FROM predictions p
            LEFT JOIN races r ON p.race_id = r.race_id
            WHERE p.model_version = ?
            """,
            (model_version,),
        ).fetchall()

        valid_preds = {}  # race_id -> {prog_no: (created_at, p_win)}
        pred_dates = set()
        for rid, prog_no, created_at, p_win, r_date, r_pt in pred_rows:
            d_str = str(r_date or rid[:10])
            if from_date and d_str < from_date:
                continue
            pred_dates.add(d_str)
            pt_str = str(r_pt or races.get(rid, {}).get("post_time") or "00:00")
            post_iso = f"{d_str}T{pt_str}"
            c_str = str(created_at or "")
            if c_str[:16] < post_iso[:16]:
                valid_preds.setdefault(rid, {})[int(prog_no)] = (c_str, float(p_win))

        return races, valid_preds, pred_dates
    finally:
        conn.close()


def compare_databases(mac_db, actions_db, from_date=None, model_version="v1_agf"):
    """İki veritabanını gün gün karşılaştır ve Markdown tablosu döndür."""
    races_m, preds_m, p_dates_m = _load_db_snapshot(mac_db, model_version=model_version, from_date=from_date)
    races_a, preds_a, p_dates_a = _load_db_snapshot(actions_db, model_version=model_version, from_date=from_date)

    all_races = {**races_a, **races_m}
    if from_date is None:
        all_pred_dates = p_dates_m | p_dates_a
        if all_pred_dates:
            min_pred_date = min(all_pred_dates)
            all_races = {rid: info for rid, info in all_races.items() if info["date"] >= min_pred_date}

    by_date = {}
    for rid, info in all_races.items():
        by_date.setdefault(info["date"], []).append(rid)

    lines = [
        "| Tarih | Koşu Sayısı | Yalnız Mac | Yalnız Actions | İkisi | Hiçbiri | Ort. \\|p_win farkı\\| | Ort. Yazım Saatleri Farkı (dk) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for d_str in sorted(by_date.keys()):
        rids = sorted(by_date[d_str])
        n_races = len(rids)
        only_mac = only_act = both = neither = 0
        p_diffs = []
        ts_diffs_min = []

        for rid in rids:
            m_map = preds_m.get(rid)
            a_map = preds_a.get(rid)
            has_m = bool(m_map)
            has_a = bool(a_map)
            if has_m and has_a:
                both += 1
                common_progs = set(m_map.keys()) & set(a_map.keys())
                for pno in common_progs:
                    m_ts, m_p = m_map[pno]
                    a_ts, a_p = a_map[pno]
                    p_diffs.append(abs(m_p - a_p))
                    dt_m = _parse_iso_naive(m_ts)
                    dt_a = _parse_iso_naive(a_ts)
                    if dt_m and dt_a:
                        ts_diffs_min.append(abs((dt_a - dt_m).total_seconds()) / 60.0)
            elif has_m:
                only_mac += 1
            elif has_a:
                only_act += 1
            else:
                neither += 1

        p_diff_str = f"{sum(p_diffs) / len(p_diffs):.6f}" if p_diffs else "—"
        ts_diff_str = f"{sum(ts_diffs_min) / len(ts_diffs_min):.1f}" if ts_diffs_min else "—"
        lines.append(
            f"| {d_str} | {n_races} | {only_mac} | {only_act} | {both} | {neither} | {p_diff_str} | {ts_diff_str} |"
        )

    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mac ve Actions tahmin veritabanlarını karşılaştır (salt okunur)")
    ap.add_argument("--mac", required=True, help="Mac veritabanı yolu (MAC.db)")
    ap.add_argument("--actions", required=True, help="Actions veritabanı yolu (ACTIONS.db)")
    ap.add_argument("--from", dest="from_date", default=None, help="Başlangıç tarihi YYYY-MM-DD")
    ap.add_argument("--model-version", default="v1_agf", help="Model sürümü (varsayılan: v1_agf)")
    args = ap.parse_args(argv)

    md = compare_databases(
        mac_db=args.mac,
        actions_db=args.actions,
        from_date=args.from_date,
        model_version=args.model_version,
    )
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
