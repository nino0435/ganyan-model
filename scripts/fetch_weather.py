"""Fetch historical hourly weather from Open-Meteo archive API into data/raw/weather/<city>.json and weather_hourly table (§3.2)."""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ganyan.db import init_db
from ganyan.tjk import UA
from ganyan.tracks import TRACK_COORDS

IST_TZ = ZoneInfo("Europe/Istanbul")


def fetch_city_archive(lat, lon, start_date, end_date, tries=3, timeout=30):
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "precipitation,temperature_2m,relative_humidity_2m,wind_speed_10m",
        "timezone": "Europe/Istanbul",
    })
    url = f"https://archive-api.open-meteo.com/v1/archive?{params}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status == 200:
                    return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def upsert_weather_json(conn, city, payload, src="archive"):
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])
    temp = hourly.get("temperature_2m", [])
    rh = hourly.get("relative_humidity_2m", [])
    wind = hourly.get("wind_speed_10m", [])

    rows = []
    for i, ts in enumerate(times):
        rows.append((
            city,
            ts,
            precip[i] if i < len(precip) else None,
            temp[i] if i < len(temp) else None,
            rh[i] if i < len(rh) else None,
            wind[i] if i < len(wind) else None,
            src,
        ))
    conn.executemany(
        """
        INSERT INTO weather_hourly (city, ts, precip_mm, temp_c, rh, wind_kmh, src)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(city, ts) DO UPDATE SET
            precip_mm = excluded.precip_mm,
            temp_c = excluded.temp_c,
            rh = excluded.rh,
            wind_kmh = excluded.wind_kmh,
            src = excluded.src
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="2024-10-01")
    ap.add_argument("--end-date", default=None, help="Defaults to today - 6 days (Europe/Istanbul)")
    ap.add_argument("--db", default="data/ganyan.db")
    ap.add_argument("--out-dir", default="data/raw/weather")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    if args.end_date is None:
        today = datetime.datetime.now(IST_TZ).date()
        args.end_date = (today - datetime.timedelta(days=6)).isoformat()

    os.makedirs(args.out_dir, exist_ok=True)
    conn = init_db(args.db)

    total_hours = 0
    missing_hours = 0
    for idx, (city, (lat, lon)) in enumerate(TRACK_COORDS.items()):
        fn = os.path.join(args.out_dir, f"{city}.json")
        payload = None
        if os.path.exists(fn) and os.path.getsize(fn) > 0 and not args.refresh:
            payload = json.load(open(fn, encoding="utf-8"))
        else:
            if idx > 0:
                time.sleep(2.0)
            payload = fetch_city_archive(lat, lon, args.start_date, args.end_date)
            if payload is not None:
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)

        if payload is not None:
            n = upsert_weather_json(conn, city, payload, src="archive")
            nulls = sum(1 for x in payload.get("hourly", {}).get("precipitation", []) if x is None)
            total_hours += n
            missing_hours += nulls
            print(f"{city:12}: {n} hours loaded (missing precip={nulls})", flush=True)
        else:
            print(f"{city:12}: FAILED to fetch weather", flush=True)

    rate = (missing_hours / total_hours * 100.0) if total_hours else 0.0
    print(f"Weather summary: cities={len(TRACK_COORDS)}, total_hours={total_hours}, missing={missing_hours} ({rate:.2f}%)")
    conn.close()


if __name__ == "__main__":
    main()
