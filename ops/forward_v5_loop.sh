#!/usr/bin/env bash
# Model v5 (B1_SGR, tüm geçmiş) günlük güncelleme ve canlı koşu-öncesi tahmin döngüsü.
# Kullanım örneği:
#   nohup caffeinate -i ops/forward_v5_loop.sh &

cd "$(dirname "$0")/.." || exit 1
mkdir -p data

LOG_FILE="data/forward_v5.log"
INTERVAL_SEC=120
last_update_day=""

ist_window_state() {
    venv/bin/python -c '
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

tz = ZoneInfo("Europe/Istanbul")
now = datetime.now(tz)
start_dt = datetime.combine(now.date(), time(9, 40), tzinfo=tz)
end_dt = datetime.combine(now.date(), time(23, 30), tzinfo=tz)
if start_dt <= now <= end_dt:
    print(f"1 {now.date().isoformat()} 0")
else:
    nxt = start_dt if now < start_dt else start_dt + timedelta(days=1)
    print(f"0 {now.date().isoformat()} {int(nxt.timestamp())}")
'
}

while true; do
    state="$(ist_window_state 2>> "$LOG_FILE")"
    if [ -z "$state" ]; then
        sleep 60
        continue
    fi

    read -r in_win ist_day target_ts <<< "$state"

    if [ "$in_win" = "1" ]; then
        if [ "$last_update_day" != "$ist_day" ]; then
            venv/bin/python -u scripts/daily_v5_update.py --date "$ist_day" >> "$LOG_FILE" 2>&1 || true
            last_update_day="$ist_day"
        fi
        venv/bin/python -u scripts/forward_v5.py --date "$ist_day" --once >> "$LOG_FILE" 2>&1 || true
        sleep "$INTERVAL_SEC"
    else
        printf '[%s] pencere dışı (09:40-23:30); İstanbul 09:40 bekleniyor\n' "$(TZ=Europe/Istanbul date '+%H:%M:%S')" >> "$LOG_FILE"
        while true; do
            now_ts="$(date +%s)"
            rem=$(( target_ts - now_ts ))
            if [ "$rem" -le 0 ]; then
                sleep 1
                break
            fi
            if [ "$rem" -gt 300 ]; then
                sleep 300
            else
                sleep "$rem"
            fi
        done
    fi
done
