# OSS boundary and hardening status

This repository is an append-only, tamper-evident evidence ledger. That is a
useful governance primitive, but it is not by itself agent memory, an enterprise
brain, a policy engine, a knowledge graph, or a source of organizational truth.
It records what authenticated or unauthenticated writers assert, depending on
deployment configuration, and detects later changes under the supported hash
contract.

## What the OSS core can establish

- a particular proof envelope was accepted by the ledger;
- the stored envelope still matches its versioned canonical hash;
- entries in an exact `entry_type` chain are linked in order;
- an idempotency key was not reused with different bound request material; and
- independently supplied entries share queryable identifiers or metadata.

It cannot establish that an assertion is true, an action actually occurred, a
model reasoned correctly, a policy was valid, or a writer was authorized. Those
claims require external identity, signature, attestation, policy, and domain
evidence validation.

## Hardened in the current OSS change set

| Area | Current state |
| --- | --- |
| Proof envelope | V3 binds signature, key reference, and attestation bytes; V2 remains explicitly verifiable for historical rows. |
| Compatibility | Every entry and receipt exposes `hash_version`; unknown versions fail closed. |
| Idempotency | Retries compare all bound content, metadata, input hash, and proof material; receipts are built from persisted rows. |
| Verification bounds | Range IDs must belong to the requested chain and cannot be reversed. |
| Retention | The former raw-delete script is now a non-destructive report; safe archival requirements are documented. |
| API/UI | gRPC, generated Python stubs, REST representations, evidence runner, and frontend agree on V3 and pagination. |
| Claims | README, contract, security notes, and UI distinguish integrity from truth, identity, execution, and authorization. |
| Dependency posture | Known Rust/npm/Python advisories are cleared in the tested dependency resolutions; CI and Dependabot cover all three ecosystems. |

## Material gaps before enterprise governance use

1. **Writer authentication and authorization.** The optional service bearer
   token is deployment-wide. There is no first-class workload identity, per-
   tenant authorization, writer-to-namespace policy, or administrative RBAC.
2. **Signature semantics and verification.** V3 binds opaque signature bytes,
   but no canonical signed-payload contract, algorithm policy, key resolution,
   certificate path validation, revocation, or rotation behavior is defined.
3. **Attestation appraisal.** Reports are opaque. Nonce binding, freshness,
   endorsements, acceptable measurements, verifier identity, and appraisal
   policy remain external.
4. **Receipt reuse policy.** Expiry, audience, purpose, policy/check identity
   and version, result schema, nonce, and subject binding are not first-class
   receipt fields. A consumer must enforce them from a versioned payload or
   must re-run the check.
5. **External anchoring and split-view resistance.** A database administrator
   can replace history and recompute a chain. There are no signed checkpoints,
   transparency-log witnesses, gossip, quorum signatures, or external anchors.
6. **Archival and recovery.** Checkpointed export, WORM manifests, online-to-
   archive verification, legal holds, backup/restore evidence, and disaster-
   recovery drills are not implemented.
7. **Privacy lifecycle.** Immutable payloads can conflict with minimization,
   correction, erasure, residency, and legal-hold requirements. Sensitive
   content should remain outside the ledger; record a digest and controlled
   reference only after threat and privacy review.
8. **Availability and scale.** The reference deployment is a single PostgreSQL
   instance. HA topology, partitioning, admission control, quotas, rate limits,
   noisy-neighbor isolation, and long-chain checkpoints need production design.
9. **Independent verification.** Online verification trusts the ledger service.
   A portable verifier, canonical test vectors, signed checkpoint format, and
   offline export verification are still needed.
10. **Governance semantics.** The ledger does not model decision authority,
    proposal/approval/effectivity, supersession, exception, obligation,
    revocation, policy hierarchy, or outcome reconciliation. Those belong in a
    separate, versioned governance domain model.
11. **Memory and knowledge services.** There is no semantic retrieval,
    embedding/vector index, entity resolution, ontology, confidence model,
    contradiction handling, summarization, forgetting policy, or contextual
    access control. Build those as projections over governed source data, using
    this ledger only for provenance and decision evidence.
12. **Release evidence.** CI is stronger but still does not run the full live
    evidence matrix or a PostgreSQL service integration on every pull request.
    Checked-in evidence files remain historical snapshots unless regenerated.

## Recommended enterprise composition

Treat the ledger as the evidence plane beneath separate services:

1. identity and workload authentication;
2. policy decision and authorization;
3. governance workflow and domain schemas;
4. knowledge/memory projections and retrieval;
5. receipt trust-policy evaluation;
6. signed checkpointing, archival, and independent audit; and
7. privacy, records, legal-hold, and operational controls.

That composition preserves the useful invariant—accepted governance evidence
is tamper-evident—without asking the ledger to decide what the enterprise knows
or what an agent is allowed to do.
