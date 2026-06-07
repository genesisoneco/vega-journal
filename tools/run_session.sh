#!/usr/bin/env bash
# ============================================================================
#  Vega session launcher (Linux / sejcore) - the cron-driven twin of
#  run_session.cmd. Usage:  run_session.sh open | close
#
#  Cron has a bare environment, so this script: cd's to the repo, loads an
#  optional tools/.env (HERMES_BIN / provider / model / tokens), applies an
#  optional random delay, writes the entry, then (if VEGA_NOTIFY=1) emails subs.
# ============================================================================
set -euo pipefail

SESSION="${1:-adhoc}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

# Optional local env (gitignored): export HERMES_BIN, HERMES_PROVIDER,
# HERMES_MODEL, VEGA_ADMIN_TOKEN, RESEND_API_KEY, VEGA_FROM_EMAIL, etc.
[ -f tools/.env ] && set -a && . tools/.env && set +a

PYTHON="${VEGA_PYTHON:-python3}"

# Optional in-script random delay (minutes). Prefer staggering cron times,
# but this gives the "posts at a random time" feel on a fixed schedule.
if [ -n "${VEGA_MAX_DELAY_MIN:-}" ] && [ "${VEGA_MAX_DELAY_MIN}" -gt 0 ]; then
  DELAY=$(( RANDOM % (VEGA_MAX_DELAY_MIN * 60) ))
  echo "[vega] random delay: ${DELAY}s"
  sleep "$DELAY"
fi

echo "[vega] writing ${SESSION} entry..."
"$PYTHON" tools/new_entry.py --session "$SESSION"
RC=$?
echo "[vega] new_entry exit ${RC}"

# Email the new entry to confirmed subscribers if enabled (no-op dry run
# unless RESEND_API_KEY + VEGA_FROM_EMAIL are set).
if [ "$RC" -eq 0 ] && [ "${VEGA_NOTIFY:-0}" = "1" ]; then
  "$PYTHON" tools/notify_subscribers.py || echo "[vega] notify failed (non-fatal)"
fi

exit "$RC"
