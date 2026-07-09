#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SumPoint — Database restore script
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/restore-db.sh backups/sumpoint_20260709_030000.sql.gz
#
# Source your .env before running, or set DATABASE_URL manually.
# This DROPS AND RECREATES every object in the target database from the dump
# — it does not merge with existing data. Confirms before running.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BACKUP_FILE="${1:?Usage: $0 <path-to-backup.sql.gz>}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set. Source your .env first." >&2
    exit 1
fi

# Strip the +asyncpg driver prefix and parse components, same as backup-db.sh.
PG_URL="${DATABASE_URL/+asyncpg/}"
PG_URL="${PG_URL/postgresql:\/\//}"

DB_USER="${PG_URL%%:*}"
PG_URL="${PG_URL#*:}"

DB_PASS="${PG_URL%%@*}"
PG_URL="${PG_URL#*@}"

DB_HOST="${PG_URL%%:*}"
PG_URL="${PG_URL#*:}"

DB_PORT="${PG_URL%%/*}"
DB_NAME="${PG_URL#*/}"

echo "About to restore '$BACKUP_FILE' into database '$DB_NAME' on $DB_HOST:$DB_PORT."
echo "This will DROP every table/object currently in that database first."
read -r -p "Type the database name to confirm: " CONFIRM
if [ "$CONFIRM" != "$DB_NAME" ]; then
    echo "Confirmation did not match. Aborting." >&2
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restoring $BACKUP_FILE -> $DB_NAME"

gunzip -c "$BACKUP_FILE" | PGPASSWORD="$DB_PASS" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --set ON_ERROR_STOP=on

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restore complete. Run 'alembic upgrade head' if the dump predates the current schema."
