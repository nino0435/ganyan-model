#!/bin/bash
# launchd işlerini kurar/yeniler (idempotent).
set -euo pipefail
cd "$(dirname "$0")/.."
for n in sabah aksam gozcu uyanik; do
  dst="$HOME/Library/LaunchAgents/com.ganyan.$n.plist"
  launchctl bootout "gui/$(id -u)/com.ganyan.$n" 2>/dev/null || true
  cp "ops/launchd/com.ganyan.$n.plist" "$dst"
  plutil -lint "$dst"
  launchctl bootstrap "gui/$(id -u)" "$dst"
done
# Eski sabit saatli 'tekrar' işi gözcüyle değiştirildi (9 Kas 2026).
launchctl bootout "gui/$(id -u)/com.ganyan.tekrar" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.ganyan.tekrar.plist"
