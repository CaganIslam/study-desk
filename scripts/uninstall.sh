#!/usr/bin/env bash
# Stop study-desk and remove its launchd agent. Your data, config and logs are kept.
set -euo pipefail

LABEL="com.studydesk.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "study-desk stopped and will no longer start at login."
echo "Data root, ~/Library/Application Support/StudyDesk and ~/Library/Logs/StudyDesk were left in place."
