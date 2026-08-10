# Retention and archival safety

Ledger rows are links in a cryptographic history. Deleting an old prefix, an
interior row, or one chain while retaining claims of complete verification
changes the meaning of the evidence. A successful verification over the rows
that remain is not proof that the deleted history was intact.

The bundled `scripts/retention-cleanup.sh` is therefore a non-destructive
capacity report. It deliberately refuses the former raw-delete mode.

## Safe operating rule

Do not delete `ledger_entries` or their associated proof material unless the
deployment has an archival protocol that external verifiers understand. Legal
holds, investigation requirements, and the organization's records policy also
take precedence over storage targets.

A future archival implementation should, at minimum:

1. close an exact chain range at a known hash and position;
2. export every entry and its hash version to immutable or WORM storage;
3. produce a signed manifest containing the chain key, range, boundary hashes,
   object digests, export time, signer, and retention policy;
4. verify the export before any database deletion;
5. preserve tombstone/checkpoint metadata in the online service;
6. teach `VerifyEntry`, `VerifyChain`, and independent tooling how to retrieve
   and validate archived ranges; and
7. test restore, legal hold, partial-export failure, and key-rotation behavior.

Until those properties exist, add database capacity, compress payloads, or put
large content in content-addressed storage and record its digest in the ledger.
Those approaches preserve the audit history instead of silently weakening it.
