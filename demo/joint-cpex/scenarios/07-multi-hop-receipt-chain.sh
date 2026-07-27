#!/bin/bash
# Scenario 07: Multi-hop receipt chain (AuthBridge → CPEX)
#
# The full guardrail dedup flow:
#   1. AuthBridge runs PII scan → IssueReceipt with input_hash
#   2. CPEX verifies AuthBridge's receipt → skips PII re-scan
#   3. CPEX issues its own policy receipt
#   4. Query by correlation_id shows both receipts
#   5. Both chains verify independently
set -e
source "$(dirname "$0")/_lib.sh"

echo ""
echo -e "${BOLD}Scenario 07: Multi-hop receipt chain${RESET}"
echo -e "${DIM}AuthBridge PII scan → receipt → CPEX verifies → skips re-scan → own receipt${RESET}"
echo ""

CORRELATION="multi-hop-$$"
AGENT_SPIFFE="spiffe://rossoctl.io/ns/default/sa/hr-agent"
REQUEST_BODY='{"employee_id":"EMP-001234","include_ssn":true}'
INPUT_HASH=$(sha256 "$REQUEST_BODY")

# ── Hop 1: AuthBridge runs PII scan ──────────────────────────
echo -e "${CYAN}Hop 1: AuthBridge PII scan${RESET}"

AB_RECEIPT=$(issue_receipt \
    "authbridge.guardrail.pii_scan" \
    "$AGENT_SPIFFE" \
    "{\"scan_result\":\"clean\",\"scanner\":\"pii-scanner-v1\",\"fields_checked\":[\"employee_id\",\"include_ssn\"]}" \
    "authbridge-sidecar" \
    "$CORRELATION" \
    "$INPUT_HASH")

AB_HASH=$(echo "$AB_RECEIPT" | python3 -c "import json,sys; print(json.load(sys.stdin)['entry_hash'])")
AB_INPUT=$(echo "$AB_RECEIPT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('input_hash',''))")

if [ -n "$AB_HASH" ]; then
    ok "AuthBridge PII scan receipt: hash=${AB_HASH:0:16}..."
    info "input_hash=${AB_INPUT:0:16}... (covers the original request body)"
else
    fail "AuthBridge receipt not issued"
    exit 1
fi

# ── Hop 2: CPEX receives request + AuthBridge receipt ────────
echo ""
echo -e "${CYAN}Hop 2: CPEX verifies AuthBridge receipt${RESET}"

# Simulate: CPEX receives X-Proof-Receipt header from AuthBridge
# and calls VerifyProof before deciding whether to re-run PII scan
VERIFY=$(verify_receipt "$AB_HASH" "authbridge.guardrail.pii_scan")
VALID=$(echo "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin)['valid'])")
VERIFY_INPUT=$(echo "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('input_hash',''))")

if [ "$VALID" = "True" ]; then
    ok "AuthBridge receipt verified: valid=true"

    # Check input_hash matches the current request body
    if [ "$VERIFY_INPUT" = "$INPUT_HASH" ]; then
        ok "input_hash matches current request body → skip PII re-scan"
    else
        info "input_hash mismatch → payload was transformed → would re-scan"
    fi
else
    fail "AuthBridge receipt invalid → would re-run PII scan"
fi

# ── Hop 3: CPEX issues its own policy receipt ────────────────
echo ""
echo -e "${CYAN}Hop 3: CPEX policy evaluation${RESET}"

CPEX_RECEIPT=$(issue_receipt \
    "cpex.policy.allow" \
    "bob" \
    "{\"tool\":\"get_compensation\",\"decision\":\"allow\",\"policy_steps\":[\"require(role.hr)\",\"delegate(workday-oauth)\"],\"pii_scan\":\"skipped_via_receipt\",\"upstream_receipt\":\"${AB_HASH:0:16}...\"}" \
    "praxis-gateway" \
    "$CORRELATION" \
    "$INPUT_HASH")

CPEX_HASH=$(echo "$CPEX_RECEIPT" | python3 -c "import json,sys; print(json.load(sys.stdin)['entry_hash'])")

if [ -n "$CPEX_HASH" ]; then
    ok "CPEX policy receipt: hash=${CPEX_HASH:0:16}..."
else
    fail "CPEX receipt not issued"
    exit 1
fi

# ── Cross-system correlation ─────────────────────────────────
echo ""
echo -e "${CYAN}Cross-system correlation${RESET}"

# Query all entries with this correlation_id
ENTRIES=$(curl -sS "$LEDGER_API/api/entries?correlation_id=$CORRELATION")
COUNT=$(echo "$ENTRIES" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")

if [ "$COUNT" = "2" ]; then
    ok "correlation_id=$CORRELATION joins $COUNT entries across both systems"
    echo "$ENTRIES" | python3 -c "
import json, sys
for e in json.load(sys.stdin):
    print(f\"  [{e['chain_position']:>3}] {e['entry_type']:<35} agent={e['agent_id']:<20} source={e['source_id']}\")
"
else
    fail "Expected 2 correlated entries, got $COUNT"
fi

# ── Chain verification ───────────────────────────────────────
echo ""
echo -e "${CYAN}Chain verification${RESET}"

for chain_type in "authbridge.guardrail.pii_scan" "cpex.policy.allow"; do
    CHAIN_VERIFY=$(curl -sS "$LEDGER_API/api/verify/$chain_type")
    CHAIN_VALID=$(echo "$CHAIN_VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('chain_valid', False))")
    CHECKED=$(echo "$CHAIN_VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('entries_checked', 0))")

    if [ "$CHAIN_VALID" = "True" ]; then
        ok "$chain_type chain valid ($CHECKED entries)"
    else
        fail "$chain_type chain verification failed"
    fi
done

echo ""
ok "Scenario 07 complete — multi-hop receipt chain verified"
echo -e "${DIM}AuthBridge PII scan → CPEX verified receipt → skipped re-scan → issued own receipt${RESET}"
echo -e "${DIM}Both entries correlated by $CORRELATION, both chains independently verified${RESET}"
