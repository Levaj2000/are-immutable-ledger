#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
echo ""
echo "  Immutable Ledger Release Test — v${VERSION}"
echo "  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  Commit: $(git rev-parse --short HEAD)"
echo ""

PASS=0
FAIL=0

run_step() {
    local name="$1"
    shift
    echo -n "  [$((PASS + FAIL + 1))] ${name}..."
    if "$@" > /tmp/release-test-output.log 2>&1; then
        echo " ✓"
        PASS=$((PASS + 1))
    else
        echo " ✗"
        echo "      $(tail -5 /tmp/release-test-output.log | head -3)"
        FAIL=$((FAIL + 1))
        return 1
    fi
}

# Phase 1: Static checks
echo "  ── Static Checks ──"
run_step "cargo fmt" cargo fmt --all --check
run_step "cargo clippy" cargo clippy --all-targets --all-features --locked -- -D warnings
run_step "cargo audit" cargo audit

# Phase 2: Unit & integration tests
echo ""
echo "  ── Tests ──"
run_step "cargo test" cargo test --all --locked
run_step "Python gateway tests" python3 -m pytest -q tests/test_gateway_contract.py
run_step "MLflow webhook tests" python3 -m pytest -q tests/test_mlflow_webhook.py

# Phase 3: Build release binary
echo ""
echo "  ── Build ──"
run_step "cargo build --release" cargo build --release

# Phase 4: Live integration (requires docker/podman)
echo ""
echo "  ── Live Integration ──"

# Detect compose command
if command -v docker-compose &>/dev/null; then
    COMPOSE="docker-compose"
elif docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v podman-compose &>/dev/null; then
    COMPOSE="podman-compose"
elif python3 -m podman_compose --version &>/dev/null 2>&1; then
    COMPOSE="python3 -m podman_compose"
else
    echo "  [SKIP] No compose tool found — skipping live integration"
    echo ""
    echo "  ── Results ──"
    echo "  Passed: ${PASS}  Failed: ${FAIL}  Skipped: live integration"
    echo ""
    exit $FAIL
fi

cleanup() {
    echo -n "  Cleaning up containers..."
    cd demo && $COMPOSE down -v > /dev/null 2>&1 || true
    cd ..
    echo " done"
}
trap cleanup EXIT

# Start services
echo -n "  Starting ledger + postgres..."
cd demo && $COMPOSE up -d --build > /tmp/release-test-output.log 2>&1
cd ..
# Wait for ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:18080/readyz > /dev/null 2>&1; then
        echo " ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo " timeout"
        FAIL=$((FAIL + 1))
        exit 1
    fi
    sleep 2
done

# Health endpoints
run_step "/healthz returns ok" curl -sf http://localhost:18080/healthz
run_step "/readyz returns ready" bash -c 'curl -sf http://localhost:18080/readyz | grep -q ready'
run_step "/verifyz returns JSON" bash -c 'curl -sf http://localhost:18080/verifyz | python3 -m json.tool > /dev/null'
run_step "/metrics returns prometheus" bash -c 'curl -sf http://localhost:18083/metrics | grep -q are_ledger'

# Write and verify via demo smoke
run_step "Demo smoke test" bash -c 'cd demo && python3 01-standalone-writer.py'
run_step "Proof explorer verify" python3 proof-explorer/proof.py verify --all

# Chain integrity metric
run_step "chain_integrity_valid gauge" bash -c 'sleep 3 && curl -sf http://localhost:18083/metrics | grep -q "are_ledger_chain_integrity_valid"'

# Adapter smoke tests
echo ""
echo "  ── Adapter Smoke Tests ──"

# OCSF adapter (OpenShell)
run_step "OCSF adapter (OpenShell)" bash -c \
    'python3 adapters/ocsf/ocsf_to_ledger.py --endpoint localhost:19292 --file adapters/ocsf/sample_events.jsonl'

# OTEL adapter (Kagenti)
run_step "OTEL adapter (Kagenti)" bash -c \
    'python3 adapters/otel/otel_to_ledger.py --endpoint localhost:19292 --file adapters/otel/sample_spans.jsonl'

# MLflow webhook adapter
LEDGER_ENDPOINT=localhost:19292 python3 adapters/mlflow/webhook_listener.py > /tmp/webhook-listener.log 2>&1 &
WEBHOOK_PID=$!
sleep 2

if curl -sf http://localhost:18098/healthz > /dev/null 2>&1; then
    run_step "MLflow webhook smoke" python3 adapters/mlflow/smoke_test.py
    kill $WEBHOOK_PID 2>/dev/null || true
else
    echo "  [SKIP] Webhook listener failed to start"
    kill $WEBHOOK_PID 2>/dev/null || true
fi

# CPEX joint demo scenarios (if compose is running)
if [ -f demo/joint-cpex/scenarios/_lib.sh ]; then
    run_step "Sample data loader" bash -c 'cd demo && python3 sample-data/load-samples.py'
fi

# Final chain verification after all adapter writes
run_step "Final chain verify (all adapters)" python3 proof-explorer/proof.py verify --all

# Evidence matrix (if available)
if [ -f tests/run_evidence.py ]; then
    run_step "Evidence matrix" python3 tests/run_evidence.py
fi

echo ""
echo "  ── Results ──"
echo "  Passed: ${PASS}  Failed: ${FAIL}"
echo "  Version: v${VERSION}"
echo "  Commit: $(git rev-parse --short HEAD)"
echo ""

exit $FAIL
