-- Widen entry_type from VARCHAR(50) to VARCHAR(255) to support longer
-- dotted-path type names (e.g. "authbridge.scope.evaluated.v2").

ALTER TABLE are_ledger.ledger_entries
  ALTER COLUMN entry_type TYPE VARCHAR(255);

ALTER TABLE are_ledger.ledger_chain_tips
  ALTER COLUMN entry_type TYPE VARCHAR(255);

ALTER TABLE are_ledger.ledger_write_outbox
  ALTER COLUMN entry_type TYPE VARCHAR(255);
