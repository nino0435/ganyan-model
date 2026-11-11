#!/bin/bash
# Google Cloud Scheduler üzerinden GitHub Actions workflow_dispatch tetikleyicileri.
# Kullanım:
#   ops/setup_cloud_scheduler.sh           # .env.cron içindeki GITHUB_DISPATCH_PAT ile kurar/yeniler
#   ops/setup_cloud_scheduler.sh --delete  # 3 Cloud Scheduler işini siler
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-ganyan-zamanlayici-2563}"  # ganyan'a ayrılmış GCP projesi (derspilot'tan bağımsız)
LOCATION="${GCP_LOCATION:-europe-west1}"
REPO="nino0435/ganyan-model"

if [ "${1:-}" = "--delete" ]; then
  for name in ganyan-tahmin-saatlik ganyan-tahmin-bucuk ganyan-aksam; do
    gcloud scheduler jobs delete "$name" --quiet --project="$PROJECT" --location="$LOCATION" || true
  done
  exit 0
fi

[ -f .env.cron ] && { set -a; . ./.env.cron; set +a; }
: "${GITHUB_DISPATCH_PAT:?GITHUB_DISPATCH_PAT gerekli (.env.cron)}"

HDRS="Accept=application/vnd.github+json,Authorization=Bearer ${GITHUB_DISPATCH_PAT},Content-Type=application/json,X-GitHub-Api-Version=2022-11-28"
TAHMIN_URI="https://api.github.com/repos/${REPO}/actions/workflows/ganyan-tahmin.yml/dispatches"
AKSAM_URI="https://api.github.com/repos/${REPO}/actions/workflows/ganyan-aksam.yml/dispatches"

upsert_job() {
  local name="$1" sched="$2" uri="$3" body="$4" desc="$5"
  gcloud scheduler jobs delete "$name" --quiet --project="$PROJECT" --location="$LOCATION" >/dev/null 2>&1 || true
  gcloud scheduler jobs create http "$name" \
    --quiet --project="$PROJECT" --location="$LOCATION" \
    --schedule="$sched" --time-zone="Europe/Istanbul" \
    --uri="$uri" --http-method=POST --headers="$HDRS" \
    --message-body="$body" --description="$desc" \
    --max-retry-attempts=2 --min-backoff=30s
}

upsert_job "ganyan-tahmin-saatlik" "0 9,10,11,12,13 * * *" "$TAHMIN_URI" '{"ref":"main","inputs":{"mode":"tahmin"}}' "Ganyan tahmin (TR 09:00-13:00)"
upsert_job "ganyan-tahmin-bucuk"   "30 14,16,18,20 * * *"  "$TAHMIN_URI" '{"ref":"main","inputs":{"mode":"tahmin"}}' "Ganyan tahmin (TR 14:30-20:30)"
upsert_job "ganyan-aksam"          "45 0 * * *"            "$AKSAM_URI"  '{"ref":"main"}'                            "Ganyan aksam (TR 00:45)"
