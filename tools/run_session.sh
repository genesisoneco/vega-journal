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
# HERMES_MODEL, VEGA_ADMIN_TOKEN, BREVO_API_KEY, VEGA_FROM_EMAIL, etc.
[ -f tools/.env ] && set -a && . tools/.env && set +a

PYTHON="${VEGA_PYTHON:-python3}"

# Preflight: warn (do not block) if Pillow is missing - covers need it.
if ! "$PYTHON" -c "import PIL" 2>/dev/null; then
  echo "[vega] WARN: Pillow not installed; entries will publish without a cover thumbnail."
  echo "[vega]       fix: $PYTHON -m pip install -r tools/requirements.txt"
fi

# Optional in-script random delay (minutes). Prefer staggering cron times,
# but this gives the "posts at a random time" feel on a fixed schedule.
if [ -n "${VEGA_MAX_DELAY_MIN:-}" ] && [ "${VEGA_MAX_DELAY_MIN}" -gt 0 ]; then
  DELAY=$(( RANDOM % (VEGA_MAX_DELAY_MIN * 60) ))
  echo "[vega] random delay: ${DELAY}s"
  sleep "$DELAY"
fi

# Cron can race with manual/site commits. Start from the latest origin/main
# immediately before generation so the later push is fast-forwardable.
echo "[vega] syncing repo before ${SESSION} entry..."
git fetch origin
CURRENT_BRANCH="$(git branch --show-current)"
git pull --rebase --autostash origin "${CURRENT_BRANCH:-main}"

echo "[vega] writing ${SESSION} entry..."
"$PYTHON" tools/new_entry.py --session "$SESSION"
RC=$?
echo "[vega] new_entry exit ${RC}"

# Email the new entry to confirmed subscribers if enabled (no-op dry run
# unless BREVO_API_KEY + VEGA_FROM_EMAIL are set).
if [ "$RC" -eq 0 ] && [ "${VEGA_NOTIFY:-0}" = "1" ]; then
  "$PYTHON" tools/notify_subscribers.py || echo "[vega] notify failed (non-fatal)"
fi

exit "$RC"
