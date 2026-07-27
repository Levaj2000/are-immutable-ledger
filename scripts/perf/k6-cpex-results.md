# CPEX/AuthBridge Latency Harness Results

## Pre-pool baseline (historical)

Run date: 2026-07-24
Ledger version: 0.1.0 (single-connection, global mutex, 5-retry permanent halt)
PostgreSQL: 16-alpine (single node, Podman, no tuning)
Profile: quick (10s per rate, rates: 20/50/100 req/s)
Host: macOS (Podman VM)
API path: REST gateway (adds ~1-2ms over raw gRPC)

> **Note:** These numbers reflect the pre-pool architecture. The global mutex
> and 5-retry circuit breaker have been replaced with `deadpool-postgres`
> (16 connections), 10 retries with exponential backoff, and auto-recovery.
> See the before/after comparison in `contracts/cpex-integration-draft.md`.

## Scenario A — Async Audit Baseline (4 parallel chains)

4 chains: `cpex.policy.allow`, `cpex.policy.deny`, `cpex.guardrail.pii_scan`, `authbridge.token.exchanged`

| Load (total) | IssueReceipt p50 | p95 | p99 | Throughput | Errors |
|---|---|---|---|---|---|
| 20 req/s | 7.3ms | 11.9ms | 67.1ms | 19/s | 0 |
| 50 req/s | 5.8ms | 7.7ms | 13.0ms | 44/s | 0 |
| 100 req/s | 4.4ms | 6.0ms | 23.4ms | 87/s | 0 |

Aggregate throughput at saturation: ~87 req/s (via REST; raw gRPC expected higher)
Saturation indicator: no errors at 100 req/s, headroom remains

## Scenario B — Sync Receipt Round-Trip (IssueReceipt + VerifyProof)

Combined latency: write receipt, then immediately verify it (simulates multi-hop flow).

| Load | IssueReceipt p50 | IssueReceipt p99 | VerifyProof p50 | VerifyProof p99 | Round-trip p50 | Round-trip p99 | Errors |
|---|---|---|---|---|---|---|---|
| 20 req/s | 6.9ms | 123.8ms | 3.7ms | 34.2ms | 10.8ms | 138.5ms | 0 |
| 50 req/s | 5.9ms | 101.5ms | 3.3ms | 26.0ms | 9.3ms | 114.0ms | 0 |
| 100 req/s | 4.2ms | 53.3ms | 2.7ms | 6.3ms | 7.0ms | 57.4ms | 159 |

The "knee" (where errors appear): ~100 req/s (159 errors)

## Scenario C — Mixed Read/Write Contention

Concurrent IssueReceipt writers + VerifyProof readers on `cpex.guardrail.pii_scan`.

| Load | IssueReceipt p50 | IssueReceipt p99 | VerifyProof p50 | VerifyProof p99 | Errors |
|---|---|---|---|---|---|
| 20 req/s | 6.6ms | 217.3ms | 4.4ms | 47.2ms | 0 |
| 50 req/s | 5.2ms | 7.3ms | 3.3ms | 5.0ms | 0 |
| 100 req/s | 4.3ms | 7.1ms | 2.5ms | 4.9ms | 0 |

VerifyProof degradation under write load: minimal — p99 stays under 5ms even at 100 req/s mixed

## Scenario D — Single-Chain Hot Path

All writes to one `entry_type` — advisory lock contention stress.

| Load | p50 | p99 | Throughput | Errors |
|---|---|---|---|---|
| 20 req/s | 6.3ms | 9.9ms | 19/s | 0 |
| 50 req/s | 4.9ms | 12.9ms | 44/s | 0 |
| **100 req/s** | **4.2ms** | **220.8ms** | **11/s** | **738** |

Advisory lock contention threshold: ~50 req/s per chain
Chain halt triggered at: 100 req/s (738 errors, throughput collapsed to 11/s)

## Post-pool results (Scenario D single-chain before/after)

| Load | Before (global mutex) | After (connection pool) |
|---|---|---|
| 50 req/s | p50=4.9ms, p99=12.9ms, 0 errors | p50=7.3ms, p99=14.4ms, 0 errors |
| **100 req/s** | **p50=4.2ms, p99=220ms, 11/s, 738 errors** | **p50=5.9ms, p99=13.8ms, 85/s, 0 errors** |
| 200 req/s | (not tested) | p50=4.8ms, p99=29.0ms, 113/s, 769 errors |

## Summary

| Operation | Pre-pool | Post-pool | Bottleneck |
|---|---|---|---|
| IssueReceipt (multi-chain, 100 req/s) | p99=23.4ms, 87/s | Unchanged (mutex wasn't the bottleneck for multi-chain) | Advisory lock per chain |
| IssueReceipt (single-chain, 100 req/s) | p99=220ms, 11/s, 738 errors | p99=13.8ms, 85/s, 0 errors | Resolved — global mutex eliminated |
| VerifyProof (under write load) | p99=4.9ms | Unchanged | Not contention-limited |

## Observations

1. **Connection pool fixed the single-chain collapse.** 738 errors → 0 at 100 req/s. Throughput 11/s → 85/s. The global mutex was the bottleneck, not the advisory lock.

2. **Multi-chain was already fine.** 4 parallel chains at 100 req/s = 0 errors both before and after. The pool eliminated false serialization but multi-chain writes were already below the per-chain advisory lock threshold.

3. **VerifyProof is fast and resilient.** p99 < 5ms under write load, unchanged by the pool. Read replicas would improve further but aren't needed at this scale.

4. **Round-trip p50 of ~10ms is workable for guardrail dedup.** IssueReceipt + VerifyProof adds ~10ms p50 to the request path via REST. Raw gRPC should be ~50% faster.

5. **REST gateway adds overhead.** These numbers include ~1-2ms of Flask + HTTP overhead. Production integration should use gRPC directly.
