-- Early deployments stored writer_signature as a hexadecimal VARCHAR. The
-- proof-envelope API represents signatures as bytes, so bring those schemas
-- forward without changing databases that already use BYTEA.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'are_ledger'
      AND table_name = 'ledger_entries'
      AND column_name = 'writer_signature'
      AND data_type <> 'bytea'
  ) THEN
    ALTER TABLE are_ledger.ledger_entries
      ALTER COLUMN writer_signature TYPE BYTEA USING (
        CASE
          WHEN writer_signature IS NULL OR writer_signature = '' THEN NULL
          ELSE decode(writer_signature, 'hex')
        END
      );
  END IF;
END $$;
