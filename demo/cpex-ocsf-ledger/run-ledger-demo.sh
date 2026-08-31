#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUNDLE_DIR="${1:-${OUT:-}}"
LEDGER_ENDPOINT="${LEDGER_ENDPOINT:-localhost:19292}"
HEALTH_URL="${LEDGER_HEALTH_URL:-http://localhost:18080/readyz}"

if [[ -z "$BUNDLE_DIR" ]]; then
  echo "usage: $0 <AI-Identity demo output directory>" >&2
  echo "       OUT=/path/to/output $0" >&2
  exit 2
fi

RECORDS="$BUNDLE_DIR/records.ndjson"
PUBLIC_KEY="$BUNDLE_DIR/demo-pub.pem"

[[ -f "$RECORDS" ]] || { echo "missing bundle records: $RECORDS" >&2; exit 2; }
[[ -f "$PUBLIC_KEY" ]] || { echo "missing bundle public key: $PUBLIC_KEY" >&2; exit 2; }

echo ""
echo "Verdict to Proof — ledger handoff"
echo "Bundle: $BUNDLE_DIR"

if ! curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Starting the ledger compose stack..."
  if command -v docker >/dev/null 2>&1; then
    docker compose -f "$REPO_DIR/demo/docker-compose.yml" up -d --build
  elif command -v podman-compose >/dev/null 2>&1; then
    podman-compose -f "$REPO_DIR/demo/docker-compose.yml" up -d --build
  else
    echo "docker compose or podman-compose is required to start the ledger" >&2
    exit 2
  fi

  for _ in $(seq 1 60); do
    curl -sf "$HEALTH_URL" >/dev/null 2>&1 && break
    sleep 1
  done
fi

curl -sf "$HEALTH_URL" >/dev/null || { echo "ledger is not ready at $HEALTH_URL" >&2; exit 1; }

echo "Importing Jeff's six-record NDJSON bundle..."
IMPORT_OUTPUT="$(python3 "$REPO_DIR/adapters/cpex/cpex_to_ledger.py" \
  --endpoint "$LEDGER_ENDPOINT" --file "$RECORDS" 2>&1)"
echo "$IMPORT_OUTPUT"
echo "$IMPORT_OUTPUT" | grep -Eq "Written: 6[[:space:]]+Errors: 0.*Gaps: 0" || {
  echo "expected six writes with zero errors and zero epoch-scoped gaps" >&2
  exit 1
}

echo "Verifying the ledger's durable cpex chains..."
python3 "$REPO_DIR/proof-explorer/proof.py" verify --entry-type cpex

echo "Resolving the signed request join key..."
python3 "$REPO_DIR/proof-explorer/proof.py" query --correlation-id corr-7f3e2a91

echo "PASS: six signed records imported; epoch-aware density and ledger chains verified."
echo "AID-EMIT-1 public key retained at: $PUBLIC_KEY"
