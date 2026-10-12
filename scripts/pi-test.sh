#!/usr/bin/env bash
# Copies the repo to the test Pi and runs pytest there.
# Usage: scripts/pi-test.sh [pytest arguments]
set -euo pipefail
HOST="${DOORSTATION_TEST_HOST:-doorstation-test}"
cd "$(dirname "$0")/.."
rsync -a --delete --exclude .git --exclude .venv --exclude .superpowers ./ "$HOST:doorstation-dev/"
args=""
for a in "$@"; do args+=" $(printf '%q' "$a")"; done
ssh "$HOST" "bash -s" <<REMOTE
set -euo pipefail
cd ~/doorstation-dev
if [ ! -x .venv/bin/python ]; then
  python3 -m venv --system-site-packages .venv
fi
pkgs=()
for d in common services/*/; do
  [ -f "\$d/pyproject.toml" ] && pkgs+=(-e "\$d")
done
.venv/bin/pip install -q --disable-pip-version-check pytest "\${pkgs[@]}"
exec .venv/bin/python -m pytest -q$args
REMOTE
