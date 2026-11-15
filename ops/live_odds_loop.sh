#!/usr/bin/env bash
# Canlı ganyan oranı toplayıcı sürekli döngü sarmalayıcısı.
# Kullanım örneği:
#   nohup caffeinate -i ops/live_odds_loop.sh &

cd "$(dirname "$0")/.." || exit 1
mkdir -p data

next_0930_epoch() {
    venv/bin/python -c '
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

tz = ZoneInfo("Europe/Istanbul")
now = datetime.now(tz)
target = datetime.combine(now.date(), time(9, 30), tzinfo=tz)
if now >= target:
    target += timedelta(days=1)
print(int(target.timestamp()))
'
}

while true; do
    if venv/bin/python -u scripts/live_odds_collect.py --db data/live_odds.db >> data/live_odds.log 2>&1; then
        target_ts="$(next_0930_epoch)"
        if [ -z "$target_ts" ]; then
            sleep 300
            continue
        fi
        while true; do
            now_ts="$(date +%s)"
            rem=$(( target_ts - now_ts ))
            if [ "$rem" -le 0 ]; then
                break
            fi
            if [ "$rem" -gt 300 ]; then
                sleep 300
            else
                sleep "$rem"
            fi
        done
    else
        sleep 60
    fi
done
