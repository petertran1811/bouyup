#!/usr/bin/env bash
# Sao lưu cơ sở dữ liệu BuoyUp đang chạy trong Docker (an toàn khi server đang ghi: dùng API backup của SQLite).
#   ./deploy/backup.sh                → backups/buoyup-YYYYmmdd-HHMMSS.db
# Khôi phục: xem HANDOVER.md mục "Sao lưu và khôi phục".
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T buoyup python -c "
import sqlite3
src = sqlite3.connect('/data/buoyup.db'); dst = sqlite3.connect('/data/backup.db')
src.backup(dst); dst.close(); src.close()"
docker compose cp buoyup:/data/backup.db "backups/buoyup-$STAMP.db"
docker compose exec -T buoyup rm -f /data/backup.db
echo "Đã lưu backups/buoyup-$STAMP.db"
