#!/usr/bin/env bash
# Install and enable the nightly dividend-etl timer.
#
# Run as root, from the repository root:
#     sudo bash ops/systemd/install.sh
#
# One password entry, then it does everything and prints what it did. Kept as a
# script so the install is one command with no chance of a mistyped unit name or
# a half-typed path, and so `daemon-reload` cannot be forgotten after the copy.
#
# Safe to re-run: it overwrites the units and is idempotent apart from --now on
# the timer, which is what you want after editing a unit.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO/ops/systemd"
UNITS=(dividend-etl.service dividend-etl.timer)
SERVICE=dividend-etl.service
TIMER=dividend-etl.timer

if [[ $EUID -ne 0 ]]; then
  echo "error: must run as root (try: sudo bash $0)" >&2
  exit 1
fi

if [[ ! -d /etc/systemd/system ]]; then
  echo "error: /etc/systemd/system not found -- systemd is not managing this system." >&2
  echo "On WSL2 that usually means systemd is not enabled; see docs/deployment-runbook.md." >&2
  exit 1
fi

# Verify before installing, so a syntax error is caught here rather than at 03:00.
if command -v systemd-analyze >/dev/null 2>&1; then
  echo "==> Verifying unit syntax"
  systemd-analyze verify "$SRC/dividend-etl.service" "$SRC/dividend-etl.timer" \
    2>&1 | grep -i "$SERVICE\|$TIMER" || true
  echo "    (no unit-specific errors above = ok)"
fi

# The service reads the warehouse credentials from EnvironmentFile and runs as the
# invoking user; both paths are absolute, so this only guards against a wrong checkout.
grep -q '^EnvironmentFile=' "$SRC/dividend-etl.service" \
  || { echo "error: service has no EnvironmentFile line" >&2; exit 1; }

echo "==> Installing units to /etc/systemd/system"
for unit in "${UNITS[@]}"; do
  install -m 0644 "$SRC/$unit" "/etc/systemd/system/$unit"
  echo "    installed $unit"
done

echo "==> daemon-reload"
systemctl daemon-reload

echo "==> Enabling and starting $TIMER"
systemctl enable --now "$TIMER"

echo
echo "==> Installed state"
systemctl is-enabled "$TIMER" || true
systemctl is-active "$TIMER" || true
echo
systemctl list-timers "$TIMER" --all --no-pager || true
echo
echo "Next fire is the line above. To run once now, without waiting:"
echo "    sudo systemctl start $SERVICE"
echo "Watch it with:  journalctl -u $SERVICE -f"
