#!/usr/bin/env bash
# BuoyUp v4 · chạy KHÔNG cần Docker (máy dev, hoặc VPS có sẵn Python 3.12).
#   ./run-local.sh            cài môi trường (lần đầu) rồi chạy server ở cổng 8000 (PORT=… để đổi)
#   ./run-local.sh test       chạy toàn bộ test backend + kiểm tra giao diện (cần Node 18+)
#   ./run-local.sh reset-lan  làm mới tài khoản demo chị Lan (APP_ENV dev/demo)
# Dữ liệu (SQLite) nằm ở ./data/buoyup.db; cấu hình ở BackEnd/API_config/.env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/BackEnd/.venv"
SRC="$ROOT/BackEnd/src"
DATA="$ROOT/data"
PY="${PYTHON:-python3}"

[ -f "$ROOT/BackEnd/API_config/.env" ] || {
  echo "Thiếu BackEnd/API_config/.env  →  cp BackEnd/API_config/.env.example BackEnd/API_config/.env rồi điền."; exit 1; }
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
fi
"$VENV/bin/pip" install -q -r "$SRC/requirements-dev.txt"
mkdir -p "$DATA"
export FRONTEND_DIR="$ROOT/Frontend"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$DATA/buoyup.db}"

case "${1:-run}" in
  test)
    (cd "$SRC" && "$VENV/bin/python" -m pytest -q)
    (cd "$ROOT" && "$VENV/bin/python" -B Frontend/tests/v4-api-check.py >/dev/null && echo "v4 API check: PASS")
    (cd "$ROOT/Frontend/tests" && node v4-ui-check.mjs | tail -1 && node c1-check.mjs | tail -1)
    ;;
  reset-lan)
    "$VENV/bin/python" "$SRC/scripts/reset_demo_seller.py"
    ;;
  run)
    cd "$DATA"
    echo "BuoyUp: http://localhost:${PORT:-8000}/   (Ctrl+C để dừng)"
    exec "$VENV/bin/uvicorn" app.main:app --app-dir "$SRC" --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
    ;;
  *) sed -n '2,6p' "$0"; exit 1 ;;
esac
