"""Capture live AGF snapshots for a race day into SQLite."""
import argparse
import datetime
import os
import re
import sys
import tempfile
import time
import urllib.parse
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ganyan.db import init_db, upsert_program
from ganyan.parse_program import parse_program_file
from ganyan.parse_results import num
from ganyan.tjk import DELAY, domestic_cities, get, program_csv_url

IST_TZ = ZoneInfo("Europe/Istanbul")


def parse_live_program_html(html_text, date_str, city):
    """Fallback HTML parser for TJK city program page (extracts SiraId, AGFORAN, Gny)."""
    snapshots = []
    # Split by race sections if present
    race_blocks = re.split(r'id="kosu_(\d+)"|(\d+)\.\s*Koşu', html_text)
    # Simpler row-based scan tracking current race_no
    cur_race_no = 0
    for m in re.finditer(
        r'(?:(\d+)\.\s*Koşu\s*:)|(<tr[^>]*>.*?gunluk-GunlukYarisProgrami-SiraId.*?</tr>)',
        html_text,
        re.DOTALL,
    ):
        if m.group(1):
            cur_race_no = int(m.group(1))
            continue
        row_html = m.group(2)
        if not cur_race_no:
            continue
        sira_m = re.search(
            r'gunluk-GunlukYarisProgrami-SiraId[^>]*>\s*(\d+)\s*<', row_html, re.DOTALL
        )
        if not sira_m:
            continue
        prog_no = int(sira_m.group(1))
        agf_m = re.search(
            r'gunluk-GunlukYarisProgrami-AGFORAN[^>]*>[^%]*%\s*([\d.,]+)\s*\(\s*(\d+)\s*\)',
            row_html,
            re.DOTALL,
        )
        gny_m = re.search(
            r'gunluk-GunlukYarisProgrami-Gny[^>]*>\s*([\d.,]+)\s*<', row_html, re.DOTALL
        )
        agf_pct = num(agf_m.group(1)) if agf_m else None
        agf_rank = int(agf_m.group(2)) if agf_m else None
        gny_live = num(gny_m.group(1)) if gny_m else None
        if agf_pct is not None or gny_live is not None:
            snapshots.append({
                "race_id": f"{date_str}_{city}_{cur_race_no}",
                "prog_no": prog_no,
                "agf_pct": agf_pct,
                "agf_rank": agf_rank,
                "ganyan_live": gny_live,
            })
    agf_sums = {}
    for s in snapshots:
        if s["agf_pct"] is not None:
            agf_sums[s["race_id"]] = agf_sums.get(s["race_id"], 0.0) + s["agf_pct"]
    cleaned = []
    for s in snapshots:
        if s["agf_pct"] is not None and agf_sums.get(s["race_id"], 0.0) <= 0.0:
            s["agf_pct"] = None
            s["agf_rank"] = None
        if s["agf_pct"] is not None or s["ganyan_live"] is not None:
            cleaned.append(s)
    return cleaned


def snapshot_agf(date_str, db_path="data/ganyan.db", prog_dir="data/raw/program", cities=None):
    """Fetch cache-busted program CSVs for date_str, upsert program, and record agf_snapshots."""
    os.makedirs(prog_dir, exist_ok=True)
    conn = init_db(db_path)
    now_iso = datetime.datetime.now(IST_TZ).isoformat(timespec="seconds")
    ts = int(time.time())

    if cities is None:
        cities = domestic_cities(date_str, page_type="GunlukYarisProgrami")

    inserted = 0
    for city in cities:
        url = program_csv_url(date_str, city, cache_bust=ts)
        st, data = get(url)
        time.sleep(DELAY)
        if st != 200 or not data:
            continue

        fn = os.path.join(prog_dir, f"{date_str}_{city}.csv")
        open(fn, "wb").write(data)
        parsed = parse_program_file(fn, date=date_str, city=city)
        upsert_program(conn, parsed)

        cur = conn.cursor()
        city_snaps = 0
        for run in parsed["runners"]:
            if run["agf_pct"] is not None:
                cur.execute(
                    """
                    INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank, ganyan_live)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run["race_id"], run["prog_no"], now_iso, run["agf_pct"], run["agf_rank"], None),
                )
                city_snaps += 1
        conn.commit()
        inserted += city_snaps

        # Fallback to HTML if CSV had no AGF values yet
        if city_snaps == 0:
            d = datetime.date.fromisoformat(date_str)
            ds = d.strftime("%d/%m/%Y")
            html_url = (
                "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisProgrami?"
                f"QueryParameter_Tarih={urllib.parse.quote(ds, safe='')}&"
                f"SehirAdi={urllib.parse.quote(city)}&Era=today"
            )
            st_h, body_h = get(
                html_url, tries=1, timeout=10, extra_headers={"X-Requested-With": "XMLHttpRequest"}
            )
            time.sleep(DELAY)
            if st_h == 200 and body_h:
                snaps = parse_live_program_html(body_h.decode("utf-8", "replace"), date_str, city)
                for s in snaps:
                    cur.execute(
                        """
                        INSERT INTO agf_snapshots (race_id, prog_no, captured_at, agf_pct, agf_rank, ganyan_live)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (s["race_id"], s["prog_no"], now_iso, s["agf_pct"], s["agf_rank"], s["ganyan_live"]),
                    )
                    inserted += 1
                conn.commit()

    conn.close()
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--db", default="data/ganyan.db")
    args = ap.parse_args()
    n = snapshot_agf(args.date, db_path=args.db)
    print(f"Captured {n} AGF snapshot rows for {args.date}")


if __name__ == "__main__":
    main()
