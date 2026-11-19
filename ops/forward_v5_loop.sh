#!/usr/bin/env bash
# Model v5 (B1_SGR, tüm geçmiş) günlük güncelleme ve canlı koşu-öncesi tahmin döngüsü.
# Kullanım örneği:
#   nohup caffeinate -i ops/forward_v5_loop.sh &

cd "$(dirname "$0")/.." || exit 1
mkdir -p data

LOG_FILE="data/forward_v5.log"
INTERVAL_SEC=120
last_update_day="${LAST_UPDATE_DAY:-}"
WARP_CLI="$(command -v warp-cli 2>/dev/null || echo /usr/local/bin/warp-cli)"
warp_opened_by_us=0

cleanup_warp() {
    if [ "$warp_opened_by_us" = "1" ] && [ -x "$WARP_CLI" ]; then
        "$WARP_CLI" disconnect >/dev/null 2>&1 || true
        warp_opened_by_us=0
        printf '[%s] warp kapatıldı\n' "$(TZ=Europe/Istanbul date '+%H:%M:%S')" >> "$LOG_FILE"
    fi
}
trap cleanup_warp EXIT INT TERM

run_daily_with_warp() {
    local day="$1"
    if [ -x "$WARP_CLI" ] && ! "$WARP_CLI" status 2>/dev/null | grep -q "Status update: Connected"; then
        printf '[%s] warp açılıyor (günlük güncelleme)\n' "$(TZ=Europe/Istanbul date '+%H:%M:%S')" >> "$LOG_FILE"
        "$WARP_CLI" connect >/dev/null 2>&1 || true
        warp_opened_by_us=1
        local i
        for i in $(seq 1 20); do
            if "$WARP_CLI" status 2>/dev/null | grep -q "Status update: Connected"; then
                sleep 2
                break
            fi
            sleep 1
        done
    fi
    venv/bin/python -u scripts/daily_v5_update.py --date "$day" >> "$LOG_FILE" 2>&1 || true
    cleanup_warp
}

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
            run_daily_with_warp "$ist_day"
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
