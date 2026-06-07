#!/usr/bin/env bash
# ============================================================================
#  Weekly subscriber report launcher (Linux / sejcore) - cron-driven.
#  cron has a bare environment, so this cd's to the repo, loads tools/.env
#  (BREVO_API_KEY, VEGA_FROM_EMAIL, DOAIA_API_BASE, DOAIA_ADMIN_TOKEN, ...),
#  then emails the combined subscriber summary. Suggested cron (Fri 8am KST):
#
#    CRON_TZ=Asia/Seoul
#    0 8 * * 5 /home/sejcore/projects/vega-journal/tools/run_report.sh >> ~/vega-weekly.log 2>&1
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

[ -f tools/.env ] && set -a && . tools/.env && set +a

PYTHON="${VEGA_PYTHON:-python3}"
echo "[vega] weekly subscriber report $(date '+%Y-%m-%d %H:%M %Z')"
exec "$PYTHON" tools/weekly_report.py
