/**
 * CPEX/AuthBridge integration latency harness.
 *
 * Measures the ledger under CPEX-shaped workloads:
 *   A) Async audit — 4 parallel chains, ramp to find saturation
 *   B) Sync receipt round-trip — IssueReceipt then VerifyProof
 *   C) Mixed read/write — concurrent writers + readers
 *   D) Single-chain hot path — advisory lock contention stress
 *
 * Run against demo/joint-cpex infrastructure:
 *   cd demo/joint-cpex && docker compose up -d postgres ledger
 *   docker run --rm \
 *     -v $(pwd)/scripts/perf:/scripts \
 *     -v $(pwd)/proto:/work/proto \
 *     grafana/k6 run /scripts/k6-cpex-latency.js
 *
 * Override target:  K6_TARGET=host.docker.internal:9092
 * Override profile: K6_PROFILE=full|quick  (default: quick)
 */

import grpc from 'k6/net/grpc';
import encoding from 'k6/encoding';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import exec from 'k6/execution';

const client = new grpc.Client();
client.load(['/work/proto'], 'immutable_ledger.proto');
const target = __ENV.K6_TARGET || 'host.docker.internal:9092';
const profile = __ENV.K6_PROFILE || 'quick';
let connected = false;

// Custom metrics for the integration draft
const issueReceiptDuration = new Trend('issue_receipt_duration', true);
const verifyProofDuration = new Trend('verify_proof_duration', true);
const roundTripDuration = new Trend('receipt_roundtrip_duration', true);
const writeErrors = new Counter('write_errors');
const verifyErrors = new Counter('verify_errors');
const chainHalts = new Counter('chain_halt_events');

// Collected hashes for VerifyProof reads (shared across VUs via scenario tags)
const recentHashes = {};

function ensureConnected() {
  if (!connected) {
    client.connect(target, { plaintext: true });
    connected = true;
  }
}

function uniq() {
  return `${exec.vu.idInTest}-${exec.vu.iterationInScenario}-${Date.now()}`;
}

// ─── Helpers ────────────────────────────────────────────────

function writeEntry(entryType, agentId, content, sourceId, correlationId, inputHash) {
  ensureConnected();
  const payload = encoding.b64encode(content || `perf-${Date.now()}`, 'rawstd');
  const req = {
    entryType,
    agentId: agentId || 'perf-agent',
    content: payload,
    contentType: 'application/json',
    sourceId: sourceId || 'perf-harness',
    idempotencyKey: `perf-${entryType}-${uniq()}`,
  };
  if (correlationId) req.correlationId = correlationId;
  if (inputHash) req.inputHash = inputHash;

  const r = client.invoke(
    'are.ledger.v1.ImmutableLedgerService/WriteEntry', req);
  const ok = check(r, { 'write ok': (r) => r && r.status === grpc.StatusOK });
  if (!ok) {
    writeErrors.add(1);
    if (r && r.message && r.message.includes('Unavailable')) {
      chainHalts.add(1);
    }
  }
  return r;
}

function issueReceipt(entryType, agentId, content, sourceId, correlationId, inputHash) {
  ensureConnected();
  const payload = encoding.b64encode(content || `perf-${Date.now()}`, 'rawstd');
  const req = {
    entryType,
    agentId: agentId || 'perf-agent',
    content: payload,
    contentType: 'application/json',
    sourceId: sourceId || 'perf-harness',
    idempotencyKey: `perf-${entryType}-${uniq()}`,
  };
  if (correlationId) req.correlationId = correlationId;
  if (inputHash) req.inputHash = inputHash;

  const start = Date.now();
  const r = client.invoke(
    'are.ledger.v1.ImmutableLedgerService/IssueReceipt', req);
  issueReceiptDuration.add(Date.now() - start);

  const ok = check(r, { 'receipt ok': (r) => r && r.status === grpc.StatusOK });
  if (!ok) {
    writeErrors.add(1);
    if (r && r.message && r.message.includes('Unavailable')) {
      chainHalts.add(1);
    }
  }
  return r;
}

function verifyProof(entryHash, entryType) {
  ensureConnected();
  const start = Date.now();
  const r = client.invoke(
    'are.ledger.v1.ImmutableLedgerService/VerifyProof',
    { entryHash, entryType });
  verifyProofDuration.add(Date.now() - start);

  const ok = check(r, { 'verify ok': (r) => r && r.status === grpc.StatusOK });
  if (!ok) verifyErrors.add(1);
  return r;
}

// ─── Scenario configs ───────────────────────────────────────

const quickDuration = '15s';
const fullDuration = '30s';
const dur = profile === 'full' ? fullDuration : quickDuration;

export const options = {
  scenarios: {
    // ── A: Async audit baseline (4 parallel chains) ──
    async_cpex_allow: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: 50, duration: dur },
        { target: 200, duration: dur },
        { target: 500, duration: dur },
      ],
      exec: 'asyncCpexAllow',
    },
    async_cpex_deny: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: 50, duration: dur },
        { target: 200, duration: dur },
        { target: 500, duration: dur },
      ],
      exec: 'asyncCpexDeny',
    },
    async_cpex_pii_scan: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: 50, duration: dur },
        { target: 200, duration: dur },
        { target: 500, duration: dur },
      ],
      exec: 'asyncCpexPiiScan',
    },
    async_authbridge_token: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: 50, duration: dur },
        { target: 200, duration: dur },
        { target: 500, duration: dur },
      ],
      exec: 'asyncAuthbridgeToken',
    },

    // ── B: Sync receipt round-trip ──
    sync_receipt_roundtrip: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 80,
      stages: [
        { target: 50, duration: dur },
        { target: 150, duration: dur },
        { target: 300, duration: dur },
      ],
      exec: 'syncReceiptRoundtrip',
    },

    // ── C: Mixed read/write contention ──
    mixed_writers: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 80,
      stages: [
        { target: 100, duration: dur },
        { target: 300, duration: dur },
      ],
      exec: 'mixedWriter',
    },
    mixed_readers: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 80,
      stages: [
        { target: 100, duration: dur },
        { target: 300, duration: dur },
      ],
      exec: 'mixedReader',
      startTime: '3s',
    },

    // ── D: Single-chain hot path ──
    single_chain_hot: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 120,
      stages: [
        { target: 50, duration: dur },
        { target: 200, duration: dur },
        { target: 500, duration: dur },
      ],
      exec: 'singleChainHot',
    },
  },
  thresholds: {
    'issue_receipt_duration': ['p(50)<20', 'p(95)<50', 'p(99)<100'],
    'verify_proof_duration': ['p(50)<5', 'p(95)<15', 'p(99)<30'],
    'receipt_roundtrip_duration': ['p(50)<25', 'p(95)<60', 'p(99)<150'],
    'grpc_req_duration{method:WriteEntry}': ['p(99)<150'],
    'grpc_req_duration{method:IssueReceipt}': ['p(99)<150'],
    'grpc_req_duration{method:VerifyProof}': ['p(99)<50'],
    'chain_halt_events': ['count<1'],
  },
};

// ─── Scenario A: Async audit baseline ───────────────────────

const CPEX_CONTENT = JSON.stringify({
  class_uid: 6003, activity_id: 99, action_id: 3,
  tool: { name: 'get_compensation' },
  ai_agent: { uid: 'agent-7' },
});

const AUTHBRIDGE_CONTENT = JSON.stringify({
  tool: 'get_compensation', audience: 'workday-api',
  scopes: ['read_compensation'], ttl_seconds: 300,
});

export function asyncCpexAllow() {
  writeEntry('cpex.policy.allow', 'perf-agent', CPEX_CONTENT,
    'praxis-gateway', `session-${exec.vu.idInTest}`);
}

export function asyncCpexDeny() {
  writeEntry('cpex.policy.deny', 'perf-agent', CPEX_CONTENT,
    'praxis-gateway', `session-${exec.vu.idInTest}`);
}

export function asyncCpexPiiScan() {
  writeEntry('cpex.guardrail.pii_scan', 'perf-agent',
    JSON.stringify({ scan_result: 'clean', scanner: 'pii-scanner-v1' }),
    'praxis-gateway', `session-${exec.vu.idInTest}`);
}

export function asyncAuthbridgeToken() {
  writeEntry('authbridge.token.exchanged', 'spiffe://rossoctl.io/ns/default/sa/hr-agent',
    AUTHBRIDGE_CONTENT, 'authbridge-sidecar', `session-${exec.vu.idInTest}`);
}

// ─── Scenario B: Sync receipt round-trip ────────────────────

export function syncReceiptRoundtrip() {
  const corr = `roundtrip-${exec.vu.idInTest}-${exec.vu.iterationInScenario}`;
  const body = JSON.stringify({ employee_id: 'EMP-001234' });
  const inputHash = 'perf-sha256-placeholder';

  const start = Date.now();

  // Step 1: IssueReceipt (the write that returns a receipt)
  const receipt = issueReceipt(
    'cpex.policy.allow', 'perf-agent', CPEX_CONTENT,
    'praxis-gateway', corr, inputHash);

  if (receipt && receipt.status === grpc.StatusOK && receipt.message) {
    const entryHash = receipt.message.entryHash;
    const entryType = receipt.message.entryType;

    if (entryHash && entryType) {
      // Step 2: VerifyProof (the read at the next hop)
      verifyProof(entryHash, entryType);
    }
  }

  roundTripDuration.add(Date.now() - start);
}

// ─── Scenario C: Mixed read/write contention ────────────────

const MIXED_TYPE = 'cpex.guardrail.pii_scan';

export function mixedWriter() {
  const r = issueReceipt(MIXED_TYPE, 'perf-agent',
    JSON.stringify({ scan_result: 'clean' }), 'praxis-gateway');

  if (r && r.status === grpc.StatusOK && r.message && r.message.entryHash) {
    recentHashes[MIXED_TYPE] = r.message.entryHash;
  }
}

export function mixedReader() {
  const hash = recentHashes[MIXED_TYPE];
  if (!hash) {
    sleep(0.1);
    return;
  }
  verifyProof(hash, MIXED_TYPE);
}

// ─── Scenario D: Single-chain hot path ──────────────────────

export function singleChainHot() {
  writeEntry('cpex.policy.allow.hot', 'perf-agent', CPEX_CONTENT,
    'praxis-gateway', `hot-${exec.vu.idInTest}`);
}

// ─── Teardown ───────────────────────────────────────────────

export function teardown() {
  if (connected) {
    client.close();
  }
}
