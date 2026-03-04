#!/bin/bash
# Run all migration scripts from the migrations directory in order.
# This fires AFTER 01_audit_schema.sql because init scripts are processed
# in alphabetical order (99_ sorts last).
set -e

MIGRATIONS_DIR="/docker-entrypoint-migrations"

if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo "No migrations directory found at $MIGRATIONS_DIR — skipping."
    exit 0
fi

for f in "$MIGRATIONS_DIR"/*.sql; do
    [ -f "$f" ] || continue
    echo "Applying migration: $(basename "$f")"
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$f"
done

echo "All migrations applied."
