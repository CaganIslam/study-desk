#!/usr/bin/env bash
# Install study-desk as a launchd agent: the server starts at login and restarts if it stops.
# Re-running is safe. Use --print to show the agent file without installing anything.
set -euo pipefail

LABEL="com.studydesk.server"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/StudyDesk"
PRINT_ONLY="${1:-}"

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }

# launchd starts processes with a minimal PATH; add the folders where claude, ffmpeg,
# mlx_whisper and uv usually live so the server can call them.
path_dirs=("$HOME/.local/bin" "/opt/homebrew/bin" "/usr/local/bin")
for tool in claude ffmpeg mlx_whisper uv; do
  found="$(command -v "$tool" 2>/dev/null || true)"
  [ -n "$found" ] && path_dirs+=("$(dirname "$found")")
done
path_dirs+=("/usr/bin" "/bin" "/usr/sbin" "/sbin")
AGENT_PATH="$(printf '%s\n' "${path_dirs[@]}" | awk '!seen[$0]++' | paste -sd: -)"

plist() {
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/study-desk</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$AGENT_PATH</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.log</string>
</dict>
</plist>
PLIST
}

if [ "$PRINT_ONLY" = "--print" ]; then
  plist
  exit 0
fi

echo "Setting up the Python environment..."
(cd "$REPO" && uv sync --quiet)

mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
plist > "$PLIST"

# Replace a running copy, then start the new one.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

PORT="$(cd "$REPO" && .venv/bin/python -c 'from studydesk.config import load_config; print(load_config().port)')"
for _ in $(seq 1 40); do
  curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
if curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "study-desk is running: http://127.0.0.1:$PORT"
  echo "It starts by itself at login. Logs: $LOG_DIR/server.log"
else
  echo "The agent is installed but the server did not answer yet. See $LOG_DIR/server.log" >&2
  exit 1
fi
