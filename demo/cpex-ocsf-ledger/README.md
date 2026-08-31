# CPEX → OCSF → Immutable Ledger demo

Jeff's merged [AI-Identity #499](https://github.com/Levaj2000/AI-Identity/pull/499)
runner owns evidence production and AID-EMIT-1 verification. It writes:

- `records.ndjson` — six signed OCSF records across two producer epochs
- `demo-pub.pem` — the corresponding verification key

After that runner reports `PASS`, hand its output directory to the ledger:

```bash
./demo/cpex-ocsf-ledger/run-ledger-demo.sh /path/to/runner/output
```

The wrapper starts the local ledger stack if needed, imports all six records,
checks that the two epoch-scoped sequences are gap-free, verifies the ledger's
`cpex.*` hash chains, and queries the signed request join key
`corr-7f3e2a91`.

The producer restart deliberately creates a new attestation `chain_uid` while
retaining stream `gw-1/boot-7`. This is valid: CPEX density is scoped to
`(epoch, stream_id)`, emitter attestation continuity is scoped to `chain_uid`,
and ledger durability is independently scoped to `entry_type`.

Open `cpex-ocsf-ledger.html` for the presenter view and six-beat script.
