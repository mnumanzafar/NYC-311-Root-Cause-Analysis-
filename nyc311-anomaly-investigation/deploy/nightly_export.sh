#!/usr/bin/env bash
# Nightly refresh + cohort-comparison export.
# Cron-safe: absolute paths, explicit env, non-zero exit on failure.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT_DIR"

# Load credentials (PG*, SMTP_*, EXPORT_EMAIL_*, SLACK_*) without leaking them to the log.
if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi

PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="$(command -v python3)"

LOG_DIR="${LOG_DIR:-$PROJECT_DIR/reports/exports/nightly/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nightly_$(date -u +%Y%m%d).log"

echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') starting nightly export ===" >>"$LOG_FILE"
"$PYTHON_BIN" -m src.orchestration.nightly_export \
  --out "${OUT_DIR:-$PROJECT_DIR/reports/exports/nightly}" \
  --format "${EXPORT_FORMAT:-all}" \
  "$@" >>"$LOG_FILE" 2>&1
status=$?
echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') finished with status $status ===" >>"$LOG_FILE"
exit $status
