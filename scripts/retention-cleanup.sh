#!/usr/bin/env bash
set -euo pipefail

# Non-destructive retention assessment for immutable-ledger operators.
#
# Raw row deletion is intentionally unsupported: removing ledger entries breaks
# the chain history and makes later verification incomplete. See
# docs/retention-and-archival.md for the archival safety requirements.
#
# Usage:
#   ./scripts/retention-cleanup.sh       # report entries older than 7 days
#   ./scripts/retention-cleanup.sh 30    # report entries older than 30 days

RETAIN_DAYS="${1:-7}"
DB_NAME="${POSTGRESQL_DATABASE:-are_ledger}"
DB_USER="${POSTGRESQL_USER:-ledger_writer}"
SCHEMA="are_ledger"

if ! [[ "$RETAIN_DAYS" =~ ^[1-9][0-9]*$ ]]; then
    echo "RETAIN_DAYS must be a positive integer." >&2
    exit 2
fi

if [ "${DELETE_OLD_ENTRIES:-0}" = "1" ]; then
    echo "Refusing raw deletion: it would invalidate retained chain history." >&2
    echo "Use a checkpointed, manifest-backed archival workflow when one is available." >&2
    exit 2
fi

echo "Retention assessment: entries older than ${RETAIN_DAYS} days"

psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -v retain_days="$RETAIN_DAYS" -v schema="$SCHEMA" -c "
SET search_path TO :'schema';
SELECT entry_type, count(*) AS candidate_entries
FROM ledger_entries
WHERE written_ts < NOW() - (:'retain_days' || ' days')::interval
GROUP BY entry_type
ORDER BY candidate_entries DESC, entry_type;
"

psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -v retain_days="$RETAIN_DAYS" -v schema="$SCHEMA" -c "
SET search_path TO :'schema';
SELECT count(*) AS total_candidate_entries,
       COALESCE(sum(octet_length(content)), 0) AS candidate_content_bytes
FROM ledger_entries
WHERE written_ts < NOW() - (:'retain_days' || ' days')::interval;
"

echo "Assessment complete. No rows were deleted."
