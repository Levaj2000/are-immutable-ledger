#!/usr/bin/env bash
set -euo pipefail

# Ledger retention cleanup — deletes entries older than N days.
# Breaks hash chain for deleted entries but keeps recent chain intact.
#
# Usage:
#   ./scripts/retention-cleanup.sh              # default: 7 days
#   ./scripts/retention-cleanup.sh 3            # keep last 3 days
#   DRY_RUN=1 ./scripts/retention-cleanup.sh    # preview without deleting
#
# Run from infra01:
#   oc exec -n immutable-ledger <db-pod> -- bash -c '...'

RETAIN_DAYS="${1:-7}"
DRY_RUN="${DRY_RUN:-0}"
DB_NAME="${POSTGRESQL_DATABASE:-are_ledger}"
DB_USER="${POSTGRESQL_USER:-ledger_writer}"
SCHEMA="are_ledger"

CUTOFF="NOW() - INTERVAL '${RETAIN_DAYS} days'"

echo "Retention cleanup: keep last ${RETAIN_DAYS} days"

# Count what would be deleted
COUNTS=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c "
SET search_path TO ${SCHEMA};
SELECT entry_type, count(*)
FROM ledger_entries
WHERE written_ts < ${CUTOFF}
GROUP BY entry_type
ORDER BY count(*) DESC;
")

echo "Entries older than ${RETAIN_DAYS} days:"
echo "$COUNTS"

TOTAL=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c "
SET search_path TO ${SCHEMA};
SELECT count(*) FROM ledger_entries WHERE written_ts < ${CUTOFF};
" | tr -d ' ')

echo "Total to delete: ${TOTAL}"

if [ "$DRY_RUN" = "1" ]; then
    echo "DRY_RUN=1 — no changes made."
    exit 0
fi

if [ "$TOTAL" = "0" ]; then
    echo "Nothing to delete."
    exit 0
fi

echo "Deleting in batches of 10000..."
DELETED=0
while true; do
    BATCH=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c "
    SET search_path TO ${SCHEMA};
    DELETE FROM ledger_entries
    WHERE entry_id IN (
        SELECT entry_id FROM ledger_entries
        WHERE written_ts < ${CUTOFF}
        LIMIT 10000
    );
    SELECT count(*) FROM ledger_entries WHERE written_ts < ${CUTOFF};
    " | tail -1 | tr -d ' ')

    DELETED=$((DELETED + 10000))
    echo "  deleted batch... ${BATCH} remaining"

    if [ "$BATCH" = "0" ]; then
        break
    fi
done

echo "Cleanup complete. Running VACUUM..."
psql -U "$DB_USER" -d "$DB_NAME" -c "SET search_path TO ${SCHEMA}; VACUUM ANALYZE ledger_entries;"
echo "Done."
