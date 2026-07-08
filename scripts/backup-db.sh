#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SumPoint — Database backup script
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/backup-db.sh           — single backup
#   ./scripts/backup-db.sh --cron    — backup + rotate (keep 7 days)
#
# Set BACKUP_DIR to change the output directory (default: ./backups).
# Source your .env before running, or set DATABASE_URL manually.
#
# To automate, add a cron job on the VPS host:
#   0 3 * * * cd /root/vps-new && ./scripts/backup-db.sh --cron
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS=7

# ── Parse DATABASE_URL ───────────────────────────────────────────────────────
# Supports: postgresql+asyncpg://user:pass@host:port/dbname
#           postgresql://user:pass@host:port/dbname
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set. Source your .env first." >&2
    exit 1
fi

# Strip the +asyncpg driver prefix for pg_dump
PG_URL="${DATABASE_URL/+asyncpg/}"
# Extract components: postgresql://user:pass@host:port/dbname
PG_URL="${PG_URL/postgresql:\/\//}"

DB_USER="${PG_URL%%:*}"
PG_URL="${PG_URL#*:}"

DB_PASS="${PG_URL%%@*}"
PG_URL="${PG_URL#*@}"

DB_HOST="${PG_URL%%:*}"
PG_URL="${PG_URL#*:}"

DB_PORT="${PG_URL%%/*}"
DB_NAME="${PG_URL#*/}"

# ── Backup ───────────────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/sumpoint_${TIMESTAMP}.sql.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup → $BACKUP_FILE"

PGPASSWORD="$DB_PASS" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-owner \
    --no-acl \
    | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup complete: $BACKUP_FILE ($BACKUP_SIZE)"

# ── Rotation (only with --cron) ──────────────────────────────────────────────
if [ "${1:-}" = "--cron" ]; then
    DELETED=$(find "$BACKUP_DIR" -name "sumpoint_*.sql.gz" -mtime +$KEEP_DAYS -delete -print | wc -l)
    if [ "$DELETED" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rotated: removed $DELETED old backup(s)"
    fi
fi
