#!/bin/bash
# backup.sh - резервне копіювання баз shop, warehouse, bank з RDS у S3 (префікс backups/).
# Пароль береться зі змінної середовища DB_PASSWORD (не з аргументів: аргументи видно в `ps` та історії).
#
# Використання:
#   export DB_PASSWORD=<пароль БД>
#   ./backup.sh <RDS_ENDPOINT> <DB_USER> <S3_BUCKET>
set -euo pipefail

DB_HOST="${1:-}"
DB_USER="${2:-}"
S3_BUCKET="${3:-}"

if [ -z "$DB_HOST" ] || [ -z "$DB_USER" ] || [ -z "$S3_BUCKET" ] || [ -z "${DB_PASSWORD:-}" ]; then
  echo "Використання: export DB_PASSWORD=<пароль>; ./backup.sh <RDS_ENDPOINT> <DB_USER> <S3_BUCKET>"
  exit 1
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/tmp/backups"
mkdir -p "$BACKUP_DIR"
export MYSQL_PWD="$DB_PASSWORD"   # mysqldump читає пароль зі змінної, а не з командного рядка

echo "=== Початок резервного копіювання: $TIMESTAMP ==="
for DB in shop warehouse bank; do
  FILE="$BACKUP_DIR/${DB}_backup_${TIMESTAMP}.sql.gz"
  echo "Копіювання бази $DB -> $FILE"
  mysqldump -h "$DB_HOST" -u "$DB_USER" --single-transaction "$DB" | gzip > "$FILE"
  aws s3 cp "$FILE" "s3://$S3_BUCKET/backups/${DB}_backup_${TIMESTAMP}.sql.gz"
  rm -f "$FILE"
done

echo "=== Готово. Вміст s3://$S3_BUCKET/backups/ ==="
aws s3 ls "s3://$S3_BUCKET/backups/"
