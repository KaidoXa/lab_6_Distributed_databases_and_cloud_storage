#!/bin/bash
# backup.sh - Скрипт резервного копіювання баз даних у S3
# Вимога розділу 10 методички: "скріншот бакета S3 з чеками замовлень і резервною копією баз даних (backup.sh)"

set -e

DB_HOST="$1"
DB_USER="$2"
DB_PASSWORD="$3"
S3_BUCKET="$4"

if [ -z "$DB_HOST" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ] || [ -z "$S3_BUCKET" ]; then
  echo "Використання: ./backup.sh <DB_HOST> <DB_USER> <DB_PASSWORD> <S3_BUCKET>"
  echo "Приклад: ./backup.sh lab6-mysql-db.xxxx.us-east-1.rds.amazonaws.com admin Lab6Password123! lab6-receipts-1234abcd"
  exit 1
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/tmp/backups"
mkdir -p "$BACKUP_DIR"

echo "=== Початок резервного копіювання: $TIMESTAMP ==="

DATABASES=("shop" "warehouse" "bank")

for DB in "${DATABASES[@]}"; do
  BACKUP_FILE="$BACKUP_DIR/${DB}_backup_${TIMESTAMP}.sql.gz"
  echo "Копіювання бази: $DB -> $BACKUP_FILE..."
  
  mysqldump -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB" | gzip > "$BACKUP_FILE"
  
  echo "Завантаження $BACKUP_FILE в s3://$S3_BUCKET/backups/..."
  aws s3 cp "$BACKUP_FILE" "s3://$S3_BUCKET/backups/${DB}_backup_${TIMESTAMP}.sql.gz"
  
  rm -f "$BACKUP_FILE"
done

echo "=== Резервне копіювання успішно завершено! Вміст у S3: ==="
aws s3 ls "s3://$S3_BUCKET/backups/"
