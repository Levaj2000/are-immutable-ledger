#!/bin/bash
# Fetch the AID-EMIT-1 conformance validator at its pinned commit, verify its
# hash, and print its local path. Standard library only, so it runs with
# `python3 -I` and no installs.
#
# Pinned to the 1.2.0-draft commit praxis-proxy/policy cites (abc7bd8). Move
# both pins together when AID-EMIT-1 1.2.0 is cut.
set -euo pipefail
COMMIT=abc7bd887c0af23081d83f083319208b5f50987e
SHA256=f75f90a4c390588591f82cabb264fcf92a3e53f6f140f1d01da8ab37cfb8370b
DEST="$(cd "$(dirname "$0")/.." && pwd)/out/aid_emit1_validator.py"
mkdir -p "$(dirname "$DEST")"
if ! echo "$SHA256  $DEST" | sha256sum -c --status 2>/dev/null; then
    curl -sSfL -o "$DEST" \
        "https://raw.githubusercontent.com/Levaj2000/AI-Identity/$COMMIT/scripts/aid_emit1_validator.py"
    echo "$SHA256  $DEST" | sha256sum -c --status || { echo "validator hash mismatch" >&2; exit 1; }
fi
echo "$DEST"
