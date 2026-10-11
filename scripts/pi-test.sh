#!/usr/bin/env bash
# Überträgt das Repo auf den Test-Pi und führt dort pytest aus.
# Aufruf: scripts/pi-test.sh [pytest-Argumente]
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
