#!/bin/bash
# Geri doldurma döngüsü (Mac, arka plan). TJK HTML geri doldurması sürdükçe liderform/yenibeygir yeni günleri
# 10 dk'da bir tarar; geçici hatada (ör. veritabanı kilidi) 60 sn sonra yeniden dener (en çok 5 ardışık hata),
# "WARP kapalı olabilir" uyarısında durur. Kaldığı yerden devam: fetch_log.
# Kullanım (log: data/backfill_<ad>.log):
#   nohup caffeinate -i ops/backfill_loop.sh html scripts/backfill_html.py --start 2015-01-01 --end 2024-10-25 > data/backfill_html.log 2>&1 &
cd "$(dirname "$0")/.." || exit 1
name=$1; shift
fails=0
while true; do
  alive=0
  if [ "$name" != "html" ]; then pgrep -f 'scripts/backfill_htm[l]\.py' >/dev/null && alive=1; fi
  venv/bin/python -u "$@"
  rc=$?
  if [ $rc -ne 0 ]; then
    if tail -n 30 "data/backfill_${name}.log" | grep -q "WARP kapalı olabilir"; then
      echo "[$(date '+%F %T')] engel/WARP: döngü durdu"; break
    fi
    fails=$((fails + 1))
    echo "[$(date '+%F %T')] hata rc=$rc ($fails/5); 60 sn sonra yeniden"
    [ "$fails" -ge 5 ] && break
    sleep 60; continue
  fi
  fails=0
  [ "$name" = "html" ] && break
  [ "$alive" = 0 ] && break
  sleep 600
done
echo "[$(date '+%F %T')] döngü bitti ($name)"
