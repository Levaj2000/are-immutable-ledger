#!/bin/bash
# Scenario 05: AuthBridge token exchange → receipt issued
# AuthBridge exchanges a SPIFFE SVID for an audience-scoped OAuth token
# and records the exchange in the ledger.
set -e
source "$(dirname "$0")/_lib.sh"

echo ""
echo -e "${BOLD}Scenario 05: AuthBridge token exchange + receipt${RESET}"
echo -e "${DIM}AuthBridge exchanges SPIFFE SVID for workday-api token → receipt issued${RESET}"
echo ""

SESSION="session-05-$$"
AGENT_SPIFFE="spiffe://rossoctl.io/ns/default/sa/hr-agent"

# AuthBridge performs RFC 8693 token exchange and records it
RECEIPT=$(issue_receipt \
    "authbridge.token.exchanged" \
    "$AGENT_SPIFFE" \
    "{\"tool\":\"get_compensation\",\"audience\":\"workday-api\",\"scopes\":[\"read_compensation\"],\"ttl_seconds\":300,\"grant_type\":\"urn:ietf:params:oauth:grant-type:token-exchange\"}" \
    "authbridge-sidecar" \
    "$SESSION")

HASH=$(echo "$RECEIPT" | python3 -c "import json,sys; print(json.load(sys.stdin)['entry_hash'])")
echo "$RECEIPT" | python3 -m json.tool

if [ -n "$HASH" ]; then
    ok "Token exchange receipt issued: hash=${HASH:0:16}..."
else
    fail "No receipt hash returned"
    exit 1
fi

# Verify the receipt
echo ""
VERIFY=$(verify_receipt "$HASH" "authbridge.token.exchanged")
VALID=$(echo "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin)['valid'])")
AGENT=$(echo "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin)['agent_id'])")

if [ "$VALID" = "True" ]; then
    ok "Receipt verified: valid=true, agent=$AGENT, source=authbridge-sidecar"
else
    fail "Receipt verification failed"
    echo "$VERIFY" | python3 -m json.tool
    exit 1
fi

echo ""
ok "Scenario 05 complete"
