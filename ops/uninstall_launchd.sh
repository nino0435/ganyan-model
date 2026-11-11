#!/bin/bash
# launchd işlerini kaldırır.
set -u
for n in sabah aksam gozcu uyanik tekrar; do
  launchctl bootout "gui/$(id -u)/com.ganyan.$n" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/com.ganyan.$n.plist"
done
