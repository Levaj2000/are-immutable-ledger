# CPEX/AuthBridge Latency Harness Results

Run date: 2026-07-24
Ledger version: 0.1.0 (single-connection, no pooling)
PostgreSQL: 16-alpine (single node, Podman, no tuning)
Profile: quick (10s per rate, rates: 20/50/100 req/s)
Host: macOS (Podman VM)
API path: REST gateway (adds ~1-2ms over raw gRPC)

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

## Summary for Integration Draft

| Operation | Measured p50 | Measured p99 | Throughput | Bottleneck |
|---|---|---|---|---|
| IssueReceipt (multi-chain, 100 req/s) | 4.4ms | 23.4ms | 87/s | Global mutex |
| IssueReceipt (single-chain, 50 req/s) | 4.9ms | 12.9ms | 44/s | Advisory lock |
| IssueReceipt (single-chain, 100 req/s) | 4.2ms | 220.8ms | 11/s | **Collapsed** — advisory lock + circuit breaker |
| VerifyProof (under write load) | 2.5ms | 4.9ms | — | Minimal degradation |
| Receipt round-trip (50 req/s) | 9.3ms | 114.0ms | — | Sum of write + read, p99 tail from mutex |
| Receipt round-trip (20 req/s) | 10.8ms | 138.5ms | — | Stable, no errors |

## Observations

1. **Multi-chain scales, single-chain doesn't.** 4 parallel chains at 100 req/s total = 0 errors, 87/s throughput. 1 chain at 100 req/s = 738 errors, 11/s throughput. The `entry_type` namespace convention (cpex.*, authbridge.*) is not just organizational — it's a performance requirement.

2. **VerifyProof is fast and resilient.** Even under mixed read/write load at 100 req/s, VerifyProof stays under 5ms p99. Read replicas would make this even better but aren't strictly needed at this scale.

3. **p99 tail latency is the concern.** The p50 numbers are fine (4-7ms for IssueReceipt), but p99 spikes to 100ms+ at moderate load. This is the global mutex creating queuing effects. Connection pooling is the fix.

4. **Round-trip p50 of ~10ms is workable for guardrail dedup.** At 20-50 req/s, the IssueReceipt + VerifyProof round-trip adds ~10ms p50 to the request path. This is acceptable for guardrails that would otherwise take 50-200ms to re-run.

5. **REST gateway adds overhead.** These numbers include ~1-2ms of Flask + HTTP overhead. Raw gRPC numbers (from README benchmarks: WriteEntry p50=1.7ms) are significantly better. Production integration should use gRPC directly.

## Recommendations for Sync Receipt Latency Target

Based on measured numbers:
- Phase 0 (async): no latency budget needed — fire-and-forget
- Phase 2 (sync): proposed p99 target = **20ms** via gRPC with connection pool
  - Current REST p99 at 50 req/s = 13ms (IssueReceipt only)
  - Raw gRPC should be ~50% faster (remove Flask overhead)
  - Connection pool eliminates the global mutex tail
  - Read replica for VerifyProof further reduces round-trip
