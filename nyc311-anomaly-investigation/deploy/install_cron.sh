#!/usr/bin/env bash
# Install the nightly export in the current user's crontab (idempotent).
#   bash deploy/install_cron.sh            # 05:30 local time every day
#   CRON_SCHEDULE="0 6 * * *" bash deploy/install_cron.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEDULE="${CRON_SCHEDULE:-30 5 * * *}"
MARKER="# nyc311-anomaly-investigation nightly export"
LINE="$SCHEDULE $PROJECT_DIR/deploy/nightly_export.sh $MARKER"

chmod +x "$PROJECT_DIR/deploy/nightly_export.sh"
current="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$current" | grep -v -F "$MARKER" || true)"
printf '%s\n%s\n' "$filtered" "$LINE" | sed '/^$/d' | crontab -

echo "Installed: $LINE"
crontab -l | grep -F "$MARKER"
