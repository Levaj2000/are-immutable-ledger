# Retention and Archival

Ledger rows are links in a cryptographic history. Deleting an old prefix, an
interior row, or one chain while retaining claims of complete verification
changes the meaning of the evidence. A successful verification over the rows
that remain is not proof that the deleted history was intact.

The bundled `scripts/retention-cleanup.sh` is therefore a non-destructive
capacity report. It deliberately refuses raw deletion.

## Safe operating rule

Do not delete `ledger_entries` or their associated proof material unless the
deployment has an archival protocol that external verifiers understand. Legal
holds, investigation requirements, and the organization's records policy also
take precedence over storage targets.

## Storage reality

"Immutable" means the chain cannot be altered in place. It does not mean every
entry lives in hot PostgreSQL forever. The question is how to move data to
cheaper storage without breaking the evidence property.

A CPEX deployment doing 100 decisions/sec with 2 KB average event size produces
roughly 17 GB/day in the ledger. That is manageable for PostgreSQL in the short
term but untenable over months without a tiered strategy. Regulated industries
often require 5-7 year retention (EU AI Act, SR 11-7, FDA 21 CFR Part 11),
which makes the combination of long retention and bounded storage an
architectural requirement, not an optimization.

## Tiered retention strategy

### Tier 1: Payload externalization (no chain impact)

Move large `content` blobs to content-addressed object storage (S3, MinIO,
WORM-capable). The ledger entry stores the content digest in `input_hash`
and a retrieval URI in `content`. Chain integrity is unchanged because the
entry hash still commits to the content field (which now holds a reference
rather than the full payload).

This is the lowest-effort option and can reduce hot storage by 5-10x for
verbose OCSF/JSON events. It preserves the full audit trail in PostgreSQL
while pushing bulk bytes to cheaper, horizontally scalable storage.

**Implementation sketch:**

1. Adapter or gateway computes `input_hash = SHA-256(payload)`.
2. Payload is written to object store at a content-addressed path
   (e.g., `s3://ledger-archive/{entry_type}/{input_hash}`).
3. Ledger entry is written with `content` set to a compact reference
   (e.g., `{"ref": "s3://...", "size": 2048, "hash": "..."}`)
   and `content_type` set to `application/vnd.ledger-ref+json`.
4. Proof receipt and chain verification work unchanged. Content retrieval
   adds one object-store read.

### Tier 2: Chain checkpointing and cold archive

Close a chain range at a known position, export the entries to immutable
or WORM storage, leave a checkpoint record in PostgreSQL, and prune the
archived range from the hot database.

This is the primary mechanism for bounding PostgreSQL storage while
preserving the evidence property across the full retention window.

**Checkpoint contract (7-point safety requirements):**

1. Close an exact chain range at a known hash and position.
2. Export every entry and its hash version to immutable or WORM storage.
3. Produce a signed manifest containing the chain key, range, boundary
   hashes, object digests, export time, signer, and retention policy.
4. Verify the export (re-walk the archived chain, confirm every entry
   hash and chain link) before any database deletion.
5. Preserve tombstone/checkpoint metadata in the online database so that
   `VerifyChain` knows the archived prefix exists and where to find it.
6. Teach `VerifyEntry`, `VerifyChain`, and independent tooling
   (`proof-explorer/proof.py`) how to retrieve and validate archived
   ranges transparently.
7. Test restore, legal hold, partial-export failure, and key-rotation
   behavior.

**Verification across the boundary:**

`VerifyChain` walks the online range and trusts the checkpoint for the
archived prefix. The checkpoint entry contains the boundary hash, so a
verifier can confirm the online chain is rooted in the archived chain
without fetching every archived entry. Deep verification (walking the
archived range) is available on demand from cold storage.

**Checkpoint entry shape (proposed):**

```
entry_type:      <same chain being checkpointed>
content_type:    application/vnd.ledger-checkpoint+json
content:         {
  "archived_range": [1, 50000],
  "boundary_hash": "<entry_hash of position 50000>",
  "manifest_uri": "s3://ledger-archive/manifests/<chain>/<timestamp>.json",
  "manifest_hash": "<SHA-256 of the signed manifest>",
  "export_verified": true,
  "export_ts": "2027-01-15T00:00:00Z"
}
```

### Tier 3: Per-chain retention policies

Different `entry_type` chains get different retention windows based on
their regulatory and operational requirements:

| Category | Example entry types | Retention | Rationale |
|---|---|---|---|
| Compliance / audit | `cpex.decision`, `authbridge.token.exchanged` | 5-7 years | EU AI Act, SR 11-7, FDA |
| Model provenance | `mlflow.model_version.created` | Life of model + 3 years | Model risk management |
| Operational | `openshell.http_activity`, `kagenti.tool.call` | 90 days | Troubleshooting, capacity |
| Debug / trace | Verbose trace chains | 7-30 days | Ephemeral by nature |

Retention policies are enforced by the checkpoint/archive mechanism (Tier 2),
not by raw deletion. Each chain's policy determines when it is eligible for
archival and when archived data can be moved to deep cold or destroyed
(subject to legal holds).

**Configuration (proposed):**

```yaml
retention:
  default_days: 90
  policies:
    - entry_type_prefix: "cpex."
      retain_days: 2555       # ~7 years
    - entry_type_prefix: "mlflow."
      retain_days: 1095       # 3 years
    - entry_type_prefix: "openshell."
      retain_days: 90
```

## PostgreSQL partitioning

For deployments with high write volume, partition `ledger_entries` by
`written_ts` (monthly or weekly ranges). This makes archival operationally
simpler: checkpoint and export an entire partition, then detach and drop it.
Chain verification across partition boundaries works because `previous_hash`
links are logical (by entry type), not physical (by partition).

Partitioning also improves query performance for time-bounded queries
(`QueryEntries` with `from_ts`/`to_ts`) through partition pruning.

## What to do today

Until the checkpoint mechanism is implemented:

1. **Add database capacity.** PostgreSQL handles hundreds of GB comfortably
   with proper vacuuming and index maintenance.
2. **Externalize large payloads.** Content-addressed object storage for
   event bodies over a configurable threshold (Tier 1).
3. **Monitor growth.** Use `scripts/retention-cleanup.sh` to assess
   per-chain volume and identify candidates for future archival.
4. **Partition early.** Set up range partitioning on `written_ts` before
   the table is large enough to make migration painful.
5. **Document retention requirements.** Work with compliance stakeholders
   to define per-chain retention windows so the policies are ready when
   the mechanism lands.

## Compliance framing

The retention strategy is a feature, not a limitation. Regulated industries
want long retention with provable integrity. The pitch is not "we delete old
data" but "hot/warm/cold tiers with chain-verified archive, so your 7-year
audit trail is provably intact even after it leaves the primary database."

The three-layer proof model (entry hash, writer signature, chain link)
extends across tiers. A proof receipt issued at write time remains
independently verifiable from cold storage. The checkpoint manifest provides
the bridge: it proves the archived chain was intact at export time, and the
online chain is rooted in that checkpoint.
