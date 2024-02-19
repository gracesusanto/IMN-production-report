#!/bin/bash

# Assuming these environment variables are passed from docker-compose to the backup service
DB_USER="${POSTGRES_USER}"
DB_PASSWORD="${POSTGRES_PASSWORD}"
DB_NAME="${POSTGRES_DB}"
# The hostname for the database should match the service name of the database in docker-compose
DB_HOST="db"

# Backup storage directory inside the container
# Make sure this directory maps to a volume or bind mount for persistence
BACKUP_DIR="./backup/backups"

# Backup filename format
DATE=$(date +%Y-%m-%d_%H%M%S)
FILE_NAME="db_backup_$DATE.sql"

# Perform the backup
# The -h option is set to $DB_HOST, allowing connection to the PostgreSQL service
PGPASSWORD=$DB_PASSWORD pg_dump -U $DB_USER -h $DB_HOST $DB_NAME > "$BACKUP_DIR/$FILE_NAME"

# Optional: Delete backups older than 30 days
find $BACKUP_DIR -type f -name '*.sql' -mtime +30 -exec rm {} \;

echo "Database backup completed: $FILE_NAME"
