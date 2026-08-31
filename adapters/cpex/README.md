# CPEX Adapter

Bridges CPEX audit seam records (OCSF 6003/ai_operation, JSONL) to the immutable ledger. This is the "guinea pig consumer" for testing the audit seam shape from [contextforge-org/cpex#166](https://github.com/contextforge-org/cpex/pull/166) before the native Rust sink lands.

First adapter to use `writer_signature` and `signer_key_reference` fields. First adapter with stream gap detection.

## Usage

```bash
# From stdin (pipe from CPEX audit output)
cat audit-stream.jsonl | python cpex_to_ledger.py

# From file
python cpex_to_ledger.py --file /var/log/cpex-audit.jsonl

# Custom endpoint + strict gap checking (CI mode)
python cpex_to_ledger.py --endpoint localhost:19292 --strict-gaps --file audit.jsonl

# Fire-and-forget mode (WriteEntry, no receipts)
python cpex_to_ledger.py --write-only --file audit.jsonl
```

## Field Mapping

| OCSF 6003 Field | Ledger Field | Notes |
|---|---|---|
| `stream_id` prefix (`dec-*`/`eff-*`) | `entry_type` | `cpex.decision` or `cpex.effect` |
| `ai_agent.uid` | `agent_id` | NOT `metadata.uid` (record ID) |
| `metadata.correlation_uid` | `correlation_id` | |
| `metadata.uid` | `idempotency_key` | Record ID — unique per event |
| JCS-canonicalized event | `content` | Envelope fields stripped |
| SHA-256 of canonical content | `input_hash` | |
| `unmapped.signature_b64` | `writer_signature` | Base64-decoded |
| `unmapped.signature_key_id` | `signer_key_reference` | |

## Gap Detection

The adapter validates two counters from the CPEX audit seam:

- **`stream_seq`** (per `(epoch, stream_id)`) — completeness claim. Dense within an epoch of its stream; a gap means a missing record. The adapter alerts on gaps. A CPEX restart opens a new epoch and legitimately resets the counter — that discontinuity is expected and is not a gap.
- **`emission_seq`** (global) — ordering claim only. Legitimately sparse for single-stream consumers. The adapter alerts on non-monotonic values (ordering violations) but not on gaps.

Gap detection is **alert-and-continue** — records are still written to the ledger. Use `--strict-gaps` to exit with code 1 if any gaps are detected (CI quality gate).

**Known limitation:** `GapDetector` keys continuity on `stream_id` alone, so a stream that
crosses an epoch boundary — a CPEX restart mid-run — is reported as a gap and fails
`--strict-gaps`, even though the reset is expected. Keying on `(epoch, stream_id)` is
pending confirmation of the epoch field's name and location in the seam record (cpex#166).
Until then, do not run `--strict-gaps` across a restart.

## Content Canonicalization

Envelope fields (`unmapped.signature_b64`, `unmapped.signature_key_id`, `unmapped.fingerprint`, `unmapped.prev_fingerprint`) are stripped before canonicalization. The remaining event is JCS-canonicalized (RFC 8785) and SHA-256 hashed. This ensures both the CPEX fingerprint chain and the ledger's V3 entry hash commit to the same canonical bytes.

## Production Path

This Python CLI adapter is for testing and offline replay. The production integration is a native Rust gRPC client inside the CPEX ocsf-audit plugin, calling the ledger directly as a sink.
