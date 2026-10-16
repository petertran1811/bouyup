#!/usr/bin/env bash
# BuoyUp Testbench runner. Runs every adversarial case against the in-process
# backend (FastAPI TestClient, isolated SQLite per test) and builds the sheet.
#
#   ./run_testbench.sh                 # all categories
#   ./run_testbench.sh 01_auth_session # one category folder
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
VENV="$ROOT/BackEnd/.venv"
PY="$VENV/bin/python"
[ -x "$PY" ] || PY="python3"

# no arg -> all cases; arg -> that category folder under cases/
if [ -n "${1:-}" ]; then TARGET="cases/$1"; else TARGET="cases"; fi
mkdir -p "$HERE/results"

echo ">> pytest on Testbench/$TARGET"
set +e
( cd "$HERE" && "$PY" -m pytest -q "$TARGET" \
    --junit-xml="$HERE/results/junit.xml" -o cache_dir="$HERE/results/.pytest_cache" )
STATUS=$?
set -e

echo ">> building sheet"
"$PY" "$HERE/aggregate.py" || true
echo ">> done (pytest exit=$STATUS). Open Testbench/results/testbench_sheet.md"
exit 0
