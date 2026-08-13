-- Widen input_hash from VARCHAR(64) to VARCHAR(128) for prefixed hash schemes.
-- Widen agent_id and source_id from VARCHAR(100) to VARCHAR(255) for SPIFFE IDs.

ALTER TABLE are_ledger.ledger_entries
  ALTER COLUMN input_hash TYPE VARCHAR(128);

ALTER TABLE are_ledger.ledger_entries
  ALTER COLUMN agent_id TYPE VARCHAR(255);

ALTER TABLE are_ledger.ledger_entries
  ALTER COLUMN source_id TYPE VARCHAR(255);
