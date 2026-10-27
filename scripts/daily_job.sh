#!/bin/bash
# Günlük ileri test işi (launchd çağırır). Kullanım: scripts/daily_job.sh sabah|aksam [YYYY-MM-DD]
#   sabah: program + canlı AGF → tahmin kaydı (yarışlardan önce)
#   aksam: sonuçlar → FORWARD.md → JSON export (yarışlardan sonra; 06:00'dan önce çalışırsa dünü işler)
set -u -o pipefail

MODE="${1:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/venv/bin/python"
LOG="$HOME/Library/Logs/ganyan-daily.log"
LOCK="$ROOT/data/.lock"
cd "$ROOT" || exit 1

if [ -f "$LOG" ] && [ "$(stat -f %z "$LOG")" -gt 5242880 ]; then mv "$LOG" "$LOG.1"; fi
exec >>"$LOG" 2>&1

log() { echo "$(TZ=Europe/Istanbul date +%Y-%m-%dT%H:%M:%S%z) [$MODE] $*"; }

case "$MODE" in sabah|aksam) ;; *) log "kullanım: $0 sabah|aksam [YYYY-MM-DD]"; exit 2 ;; esac

if [ -n "${2:-}" ]; then
  D="$2"
elif [ "$MODE" = aksam ] && [ "$(TZ=Europe/Istanbul date +%H)" -lt 6 ]; then
  D="$(TZ=Europe/Istanbul date -v-1d +%F)"
else
  D="$(TZ=Europe/Istanbul date +%F)"
fi

# Yarım kalmış işin kilidi 6 saatten eskiyse sil.
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360)" ]; then rmdir "$LOCK"; fi
if ! mkdir "$LOCK" 2>/dev/null; then log "kilit var, çıkılıyor"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

FAIL=0
step() {
  local name="$1"; shift
  log "$name başladı ($D)"
  if "$PY" -I "$@"; then log "$name OK"; else local rc=$?; log "$name HATA($rc)"; FAIL=1; fi
}

if [ "$MODE" = sabah ]; then
  step update_daily scripts/update_daily.py --date "$D"
  step forward_log scripts/forward_log.py --date "$D"
else
  step update_daily scripts/update_daily.py --date "$D"
  step forward_report scripts/forward_report.py
  step export_day scripts/export_day.py --date "$D"
fi

if [ "$FAIL" -ne 0 ]; then
  osascript -e "display notification \"$MODE işi başarısız ($D), log: ~/Library/Logs/ganyan-daily.log\" with title \"Ganyan\"" || true
  exit 1
fi
log "bitti"
