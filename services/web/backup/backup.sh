#!/bin/bash

# Back up to csv
curl -X POST "http://0.0.0.0:8000/db-backup"

# Assuming these environment variables are passed from docker-compose to the backup service
DB_USER="${POSTGRES_USER}"
DB_PASSWORD="${POSTGRES_PASSWORD}"
DB_NAME="${POSTGRES_DB}"
# The hostname for the database should match the service name of the database in docker-compose
DB_HOST="db"

# Backup storage directory inside the container
# Make sure this directory maps to a volume or bind mount for persistence
BACKUP_DIR="/app/backup/sql"

ensure_folder_exists() {
    if [ ! -d "$1" ]; then
        mkdir -p "$1"
    fi
}
ensure_folder_exists "$BACKUP_DIR"

# Backup filename format
DATE=$(date +%Y-%m-%d)
FILE_NAME="db_backup_$DATE.sql"

# Perform the backup
# The -h option is set to $DB_HOST, allowing connection to the PostgreSQL service
PGPASSWORD=$DB_PASSWORD pg_dump -U $DB_USER -h $DB_HOST $DB_NAME > "$BACKUP_DIR/$FILE_NAME"

# Optional: Delete backups older than 30 days
find $BACKUP_DIR -type f -name '*.sql' -mtime +30 -exec rm {} \;

######## Backup Report ########
# Get the current month and year
current_month=$(date +%-m)
current_year=$(date +%Y)

# Calculate the last month and its year
if [ "$current_month" -eq 1 ]; then
    last_month=12
    last_month_year=$((current_year - 1))
else
    last_month=$(printf "%d" $(($current_month - 1)))
    last_month_year=$current_year
fi

# Send POST request for the current month and year
curl -X 'POST' \
  'http://localhost:8000/report-backup' \
  -H "Content-Type: application/json" \
  -d '{
  "month": '$current_month',
  "year": '$current_year'
}'

# Send POST request for the last month and year
curl -X 'POST' \
  'http://localhost:8000/report-backup' \
  -H "Content-Type: application/json" \
  -d '{
  "month": '$last_month',
  "year": '$last_month_year'
}'

echo "Database backup completed: $FILE_NAME"
