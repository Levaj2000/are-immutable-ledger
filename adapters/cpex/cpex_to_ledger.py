#!/usr/bin/env python3
"""CPEX-to-Ledger adapter for the CPEX audit seam.

Reads CPEX audit records (OCSF 6003/ai_operation, JSONL) from stdin or
a file and writes them to the immutable ledger. Each record becomes a
ledger entry with:

  entry_type:           "cpex.decision" or "cpex.effect" (from stream_id prefix)
  agent_id:             ai_agent.uid (NOT metadata.uid)
  content:              JCS-canonicalized event bytes (envelope stripped)
  content_type:         "application/ocsf+json"
  source_id:            "cpex-audit-seam"
  correlation_id:       metadata.correlation_uid
  idempotency_key:      metadata.uid (the record ID)
  input_hash:           SHA-256 of canonical content
  writer_signature:     unmapped.signature_b64 (base64-decoded)
  signer_key_reference: unmapped.signature_key_id

Gap detection: validates stream_seq continuity per (epoch, stream_id)
and emission_seq monotonicity. Alerts on gaps but still writes records.
A CPEX restart opens a new epoch and resets stream_seq; that is reported
as an epoch change, not a gap.

Usage:
  python cpex_to_ledger.py --file /var/log/cpex-audit.jsonl
  cat audit-stream.jsonl | python cpex_to_ledger.py
  python cpex_to_ledger.py --endpoint localhost:19292 --strict-gaps
"""

import argparse
import base64
import copy
import hashlib
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdks", "python"))
from ledger_client import LedgerClient

SOURCE_ID = "cpex-audit-seam"
CONTENT_TYPE = "application/ocsf+json"

STREAM_PREFIX_MAP = {
    "dec-": "decision",
    "eff-": "effect",
}

# Record-type discriminators, in the plugin's OCSF records. The decision
# sink inserts unmapped["cpex.decision"] on every finalized verdict;
# unmapped["cpex.effect"] is reserved for AuditHandler::on_effect, which
# has not landed yet.
RECORD_TYPE_KEYS = (
    ("cpex.decision", "decision"),
    ("cpex.effect", "effect"),
)

# The per-request join key a signed draw receipt reconciles against.
REQUEST_ID_KEY = "cmf.request.request_id"

ENVELOPE_KEYS = ("signature_b64", "signature_key_id", "fingerprint", "prev_fingerprint")


STREAM_STAMP_KEY = "cpex.stream"


def extract_stream_stamps(event):
    """Return (epoch, stream_id, stream_seq, emission_seq).

    The plugin's OCSF records carry the seam's completeness/ordering stamps
    under unmapped["cpex.stream"], inside the hashed bytes. Older seam output
    carried them at the top level, so fall back to that.
    """
    stamps = event.get("unmapped", {}).get(STREAM_STAMP_KEY)
    if not isinstance(stamps, dict):
        stamps = event
    return (
        stamps.get("epoch"),
        stamps.get("stream_id", ""),
        stamps.get("stream_seq"),
        stamps.get("emission_seq"),
    )


class GapDetector:
    """Tracks stream_seq continuity per (epoch, stream_id) and emission_seq
    monotonicity."""

    def __init__(self):
        self._last_seq = {}
        self._last_epoch = {}
        self._last_emission_seq = -1
        self._notes = []

    def pop_notes(self):
        """Drain informational notes (epoch changes) recorded since the last call."""
        notes, self._notes = self._notes, []
        return notes

    def check(self, stream_id, stream_seq, emission_seq, epoch=None):
        alerts = []

        previous_epoch = self._last_epoch.get(stream_id, epoch)
        if previous_epoch != epoch:
            self._notes.append(
                f"EPOCH CHANGE in {stream_id}: {previous_epoch} -> {epoch}; "
                f"stream_seq resets to {stream_seq} (expected, not a gap)"
            )
        self._last_epoch[stream_id] = epoch

        key = (epoch, stream_id)
        if key in self._last_seq:
            expected = self._last_seq[key] + 1
            if stream_seq != expected:
                alerts.append(
                    f"GAP in {stream_id}: expected stream_seq {expected}, got {stream_seq}"
                )

        self._last_seq[key] = stream_seq

        if emission_seq is not None and emission_seq <= self._last_emission_seq:
            alerts.append(
                f"ORDERING: emission_seq {emission_seq} <= previous {self._last_emission_seq}"
            )
        if emission_seq is not None:
            self._last_emission_seq = emission_seq

        return alerts


def detect_record_type(event):
    """Classify a record as a decision or an effect, or None to skip it.

    The plugin's OCSF records are keyed on the unmapped object they carry:
    a finalized verdict from the decision sink brings unmapped["cpex.decision"].
    Their stream_id is a gateway/boot id (e.g. "gw-1/boot-7") nested under
    unmapped["cpex.stream"], so the dec-/eff- prefix convention below only
    identifies older seam output that carried a top-level stream_id.
    """
    unmapped = event.get("unmapped")
    if isinstance(unmapped, dict):
        for key, record_type in RECORD_TYPE_KEYS:
            if key in unmapped:
                return record_type

    stream_id = event.get("stream_id", "")
    for prefix, record_type in STREAM_PREFIX_MAP.items():
        if stream_id.startswith(prefix):
            return record_type
    return None


def extract_agent_id(event):
    ai_agent = event.get("ai_agent", {})
    uid = ai_agent.get("uid", "")
    if uid:
        return uid
    return event.get("agent_id", "unknown")


def extract_correlation_id(event):
    """Prefer the per-request join key, falling back to the conversation key.

    A signed draw receipt names the request's correlation id, and the plugin
    carries that at unmapped["cmf.request.request_id"] — deliberately not in
    metadata.correlation_uid, which it reserves for an id that is stable
    across events. The ledger's correlation_id is the field a receipt-in-hand
    is queried against, so the per-request id wins where a record has one.
    """
    unmapped = event.get("unmapped")
    if isinstance(unmapped, dict):
        request_id = unmapped.get(REQUEST_ID_KEY)
        if request_id:
            return request_id

    metadata = event.get("metadata", {})
    return metadata.get("correlation_uid", "")


def extract_idempotency_key(event):
    metadata = event.get("metadata", {})
    return metadata.get("uid", "")


def extract_writer_signature(event):
    unmapped = event.get("unmapped", {})
    sig_b64 = unmapped.get("signature_b64", "")
    if not sig_b64:
        return b""
    try:
        return base64.b64decode(sig_b64)
    except Exception:
        print(f"  WARNING: invalid base64 in signature_b64, skipping signature", file=sys.stderr)
        return b""


def extract_signer_key_reference(event):
    unmapped = event.get("unmapped", {})
    return unmapped.get("signature_key_id", "")


def canonicalize_content(event):
    """Strip envelope fields from unmapped, JCS-canonicalize, return (bytes, sha256_hex)."""
    content = copy.deepcopy(event)

    unmapped = content.get("unmapped", {})
    for key in ENVELOPE_KEYS:
        unmapped.pop(key, None)
    if not unmapped:
        content.pop("unmapped", None)
    elif unmapped != event.get("unmapped", {}):
        content["unmapped"] = unmapped

    try:
        from json_canonicalize import canonicalize
        canonical = canonicalize(content)
    except ImportError:
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    if isinstance(canonical, str):
        canonical_bytes = canonical.encode("utf-8")
    else:
        canonical_bytes = canonical

    content_hash = hashlib.sha256(canonical_bytes).hexdigest()
    return canonical_bytes, content_hash


def process_line(client, line, stats, gap_detector, *, write_only=False):
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        stats["parse_errors"] += 1
        return

    record_type = detect_record_type(event)
    if record_type is None:
        stats["skipped"] += 1
        return

    epoch, stream_id, stream_seq, emission_seq = extract_stream_stamps(event)

    if stream_id and stream_seq is not None:
        gaps = gap_detector.check(stream_id, stream_seq, emission_seq, epoch=epoch)
        for note in gap_detector.pop_notes():
            print(f"  NOTE: {note}", file=sys.stderr)
        for gap_msg in gaps:
            print(f"  WARNING: {gap_msg}", file=sys.stderr)
            stats["gaps_detected"] += 1

    entry_type = f"cpex.{record_type}"
    agent_id = extract_agent_id(event)
    correlation_id = extract_correlation_id(event)
    idempotency_key = extract_idempotency_key(event)
    writer_signature = extract_writer_signature(event)
    signer_key_ref = extract_signer_key_reference(event)

    canonical_bytes, content_hash = canonicalize_content(event)

    write_kwargs = dict(
        entry_type=entry_type,
        agent_id=agent_id,
        content=canonical_bytes,
        content_type=CONTENT_TYPE,
        source_id=SOURCE_ID,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        input_hash=content_hash,
        writer_signature=writer_signature,
        signer_key_reference=signer_key_ref,
    )

    try:
        if write_only:
            resp = client.write(**write_kwargs)
            pos = resp.chain_position
        else:
            resp = client.issue_receipt(**write_kwargs)
            pos = resp.chain_position
        stats["written"] += 1
        seq_info = f"seq={stream_seq}" if stream_seq is not None else ""
        print(f"  [{pos:>3}] {entry_type:<20} agent={agent_id:<20} {seq_info}")
    except Exception as e:
        stats["write_errors"] += 1
        print(f"  ERROR writing {entry_type}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Bridge CPEX audit records to the immutable ledger"
    )
    parser.add_argument("--file", "-f", help="Read from file instead of stdin")
    parser.add_argument(
        "--endpoint", default="localhost:19092", help="Ledger gRPC endpoint"
    )
    parser.add_argument(
        "--write-only",
        action="store_true",
        help="Use WriteEntry instead of IssueReceipt (no receipt data)",
    )
    parser.add_argument(
        "--strict-gaps",
        action="store_true",
        help="Exit with error code if gaps detected",
    )
    args = parser.parse_args()

    client = LedgerClient(args.endpoint)
    stats = {
        "written": 0,
        "parse_errors": 0,
        "write_errors": 0,
        "skipped": 0,
        "gaps_detected": 0,
    }
    gap_detector = GapDetector()

    print(f"\n  CPEX-to-Ledger Adapter")
    print(f"  Ledger: {args.endpoint}")
    print(f"  Source: {'stdin' if not args.file else args.file}")
    print(f"  Mode:   {'WriteEntry' if args.write_only else 'IssueReceipt'}\n")

    try:
        if args.file:
            with open(args.file) as f:
                for line in f:
                    process_line(
                        client, line, stats, gap_detector, write_only=args.write_only
                    )
        else:
            for line in sys.stdin:
                process_line(
                    client, line, stats, gap_detector, write_only=args.write_only
                )
    except KeyboardInterrupt:
        pass

    print(
        f"\n  Written: {stats['written']}  Errors: {stats['write_errors']}  "
        f"Parse errors: {stats['parse_errors']}  Skipped: {stats['skipped']}  "
        f"Gaps: {stats['gaps_detected']}\n"
    )

    client.close()

    if args.strict_gaps and stats["gaps_detected"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
