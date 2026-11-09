#!/bin/bash
# Günlük ileri test işi (launchd çağırır). Kullanım: scripts/daily_job.sh sabah|aksam [YYYY-MM-DD]
#   sabah: program + canlı AGF → tahmin kaydı (yarışlardan önce)
#   gozcu: 5 dk'da bir; bugünün koşularını algılar, AGF çıkan koşuya yarıştan önce tahmin yazar (sessiz çalışır)
#   tekrar: (eski) gün içi yeniden deneme; yalnız forward_log (AGF sonradan yayınlanan koşuları ekler, kayıtlılara dokunmaz)
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

case "$MODE" in sabah|aksam|tekrar|gozcu) ;; *) log "kullanım: $0 sabah|aksam|tekrar|gozcu [YYYY-MM-DD]"; exit 2 ;; esac

if [ -n "${2:-}" ]; then
  D="$2"
elif [ "$MODE" = aksam ] && [ "$(TZ=Europe/Istanbul date +%H)" -lt 6 ]; then
  D="$(TZ=Europe/Istanbul date -v-1d +%F)"
else
  D="$(TZ=Europe/Istanbul date +%F)"
fi

# Yarım kalmış işin kilidi 6 saatten eskiyse sil.
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360)" ]; then rmdir "$LOCK"; fi
if ! mkdir "$LOCK" 2>/dev/null; then [ "$MODE" = gozcu ] || log "kilit var, çıkılıyor"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

FAIL=0
step() {
  local name="$1"; shift
  log "$name başladı ($D)"
  if "$PY" -I "$@"; then log "$name OK"; else local rc=$?; log "$name HATA($rc)"; FAIL=1; fi
}

# Gündüz Mac okul ağındayken TJK açılmayabiliyor; forward_log bunu sessizce "0 tahmin" diye geçer.
# Erişim yoksa log'a yaz, günde bir kez bildirim göster (işi yine de çalıştırır).
if [ "$MODE" != aksam ]; then
  PROBE="$(curl -sL --max-time 10 "${TJK_PROBE_URL:-https://www.tjk.org/}" || true)"
  case "$PROBE" in *[Tt][Jj][Kk]*) ;; *)
    [ "$MODE" = gozcu ] || log "UYARI: TJK'ya ulaşılamıyor, tahmin yazılamayabilir"
    MARK="$ROOT/data/.tjk_unreach_$D"
    if [ ! -e "$MARK" ]; then
      touch "$MARK"
      [ "$MODE" != gozcu ] || log "UYARI: TJK'ya ulaşılamıyor, tahmin yazılamayabilir"
      osascript -e "display notification \"TJK'ya ulaşılamıyor ($D) — Mac'i hotspot'a bağla\" with title \"Ganyan\"" || true
    fi ;;
  esac
fi

if [ "$MODE" = gozcu ]; then
  # Her 5 dk çağrılır: yalnız iş yaptığında log'a yazar.
  OUT="$("$PY" -I scripts/gozcu.py --date "$D" 2>&1)"; RC=$?
  [ -z "$OUT" ] || log "$OUT"
  if [ "$RC" -ne 0 ]; then log "gozcu HATA($RC)"; FAIL=1; fi
elif [ "$MODE" = tekrar ]; then
  step forward_log scripts/forward_log.py --date "$D"
elif [ "$MODE" = sabah ]; then
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
[ "$MODE" = gozcu ] || log "bitti"
