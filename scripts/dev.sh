#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -e ".[dev]"

running() {
  python -c 'from agentshelf.config import load_settings; from agentshelf.server import running_session; import sys; sys.exit(0 if running_session(load_settings()) else 1)'
}

STARTED=0
if ! running; then
  agentshelf serve >"$ROOT/.agentshelf-dev.log" 2>&1 &
  echo $! >"$ROOT/.agentshelf-dev.pid"
  STARTED=1
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 30; do
    if running; then
      break
    fi
    sleep 0.2
  done
fi

cleanup() {
  if [[ "$STARTED" -eq 1 ]]; then
    agentshelf stop >/dev/null 2>&1 || true
    rm -f "$ROOT/.agentshelf-dev.pid"
  fi
}
trap cleanup EXIT

cd "$ROOT/apps/desktop"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run dev
