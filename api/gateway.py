"""REST API — full ledger surface for frontends, CLIs, and external integrations.

Read/audit endpoints:
  GET  /api/entries, /api/summary, /api/chains, /api/verify, /api/timeline, /api/drift

Write endpoints:
  POST /api/entries              — WriteEntry
  POST /api/receipts             — IssueReceipt (write + get proof hash)

Receipt verification:
  GET  /api/receipts/verify      — VerifyProof by hash + type
  GET  /api/entries/by-hash      — GetEntryByHash (full content by hash)
  GET  /api/receipts/chain       — trust chain for a correlation_id
"""

import hmac
import json
import os
import sys

from flask import Flask, jsonify, request
from flask_cors import CORS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdks", "python"))
from ledger_client import LedgerClient

app = Flask(__name__)

ENDPOINT = os.environ.get("LEDGER_ENDPOINT", "localhost:19292")
GATEWAY_API_TOKEN = os.environ.get("GATEWAY_API_TOKEN", "")
DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def cors_origins():
    configured = os.environ.get("GATEWAY_CORS_ORIGINS", "")
    if not configured:
        return DEFAULT_CORS_ORIGINS
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


CORS(app, origins=cors_origins())



# Authentication.
#
# This gateway fronts the append-only ledger: POST /api/entries and
# POST /api/receipts write the evidence the rest of the platform treats as
# authoritative. The previous check skipped authentication entirely when
# GATEWAY_API_TOKEN was unset, so a gateway deployed without the variable
# accepted anonymous writes -- and no manifest set it.
#
# It now fails closed. Running without a token requires the operator to say
# so explicitly with GATEWAY_ALLOW_UNAUTHENTICATED=true, which is intended
# for local development and the demo compose stack only.
#
# /healthz is always reachable so container probes do not need credentials.
ALLOW_UNAUTHENTICATED = os.environ.get(
    "GATEWAY_ALLOW_UNAUTHENTICATED", ""
).strip().lower() in {"1", "true", "yes"}

if not GATEWAY_API_TOKEN and not ALLOW_UNAUTHENTICATED:
    raise SystemExit(
        "GATEWAY_API_TOKEN is not set. The ledger gateway writes evidence and "
        "will not run unauthenticated. Set GATEWAY_API_TOKEN, or set "
        "GATEWAY_ALLOW_UNAUTHENTICATED=true for local development."
    )

UNAUTHENTICATED_PATHS = {"/healthz"}


@app.get("/healthz")
def healthz():
    """Liveness and readiness probe. Never requires credentials."""
    return jsonify({"status": "ok", "service": "are-ledger-gateway"})


@app.before_request
def authorize_gateway_request():
    if request.method == "OPTIONS" or request.path in UNAUTHENTICATED_PATHS:
        return None
    if not GATEWAY_API_TOKEN:
        return None  # only reachable via GATEWAY_ALLOW_UNAUTHENTICATED
    expected = f"Bearer {GATEWAY_API_TOKEN}"
    presented = request.headers.get("Authorization", "")
    if not hmac.compare_digest(presented, expected):
        return jsonify({"error": "unauthorized"}), 401
    return None


_client = None


def get_client():
    """Return a module-level singleton LedgerClient (reused across requests)."""
    global _client
    if _client is None:
        _client = LedgerClient(ENDPOINT)
    return _client


def normalize_content(content):
    """Encode structured JSON content for the byte-oriented ledger contract."""
    if isinstance(content, (dict, list)):
        return json.dumps(content, separators=(",", ":"), sort_keys=True)
    return content


def _query_capped(max_entries=10000, **kwargs):
    """Paginated query that stops after max_entries. Returns (entries, truncated)."""
    c = get_client()
    entries = []
    page_token = ""
    page_size = min(500, max_entries)
    while True:
        page, next_token, _total = c.query_page(
            page_size=page_size, page_token=page_token, **kwargs)
        entries.extend(page)
        if len(entries) >= max_entries:
            return entries[:max_entries], True
        if not next_token:
            break
        page_token = next_token
    return entries, False


def entry_to_dict(e):
    try:
        content_parsed = json.loads(e.content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        content_parsed = None
    return {
        "entry_id": e.entry_id,
        "entry_type": e.entry_type,
        "agent_id": e.agent_id,
        "content_raw": e.content.decode("utf-8", errors="replace"),
        "content": content_parsed,
        "content_type": e.content_type,
        "source_id": e.source_id,
        "correlation_id": e.correlation_id,
        "entry_hash": e.entry_hash,
        "previous_hash": e.previous_hash,
        "chain_position": e.chain_position,
        "written_ts": e.written_ts,
        "input_hash": e.input_hash,
        "writer_signature": e.writer_signature.hex() if e.writer_signature else "",
        "signer_key_reference": e.signer_key_reference if hasattr(e, 'signer_key_reference') else "",
        "attestation_report": e.attestation_report.hex() if e.attestation_report else "",
        "hash_version": e.hash_version,
    }


@app.route("/api/entries", methods=["POST"])
def write_entry():
    c = get_client()
    body = request.get_json()
    resp = c.write(
        entry_type=body.get("entry_type", ""),
        agent_id=body.get("agent_id", ""),
        content=normalize_content(body.get("content", "")),
        content_type=body.get("content_type", "application/json"),
        source_id=body.get("source_id", ""),
        correlation_id=body.get("correlation_id", ""),
        idempotency_key=body.get("idempotency_key", ""),
        input_hash=body.get("input_hash", ""),
        writer_signature=bytes.fromhex(body["writer_signature"]) if body.get("writer_signature") else b"",
        signer_key_reference=body.get("signer_key_reference", ""),
        attestation_report=bytes.fromhex(body["attestation_report"]) if body.get("attestation_report") else b"",
    )
    return jsonify({
        "entry_id": resp.entry_id,
        "entry_hash": resp.entry_hash,
        "chain_position": resp.chain_position,
        "written_ts": resp.written_ts,
        "hash_version": resp.hash_version,
    }), 201


@app.route("/api/receipts", methods=["POST"])
def issue_receipt():
    c = get_client()
    body = request.get_json()
    receipt = c.issue_receipt(
        entry_type=body.get("entry_type", ""),
        agent_id=body.get("agent_id", ""),
        content=normalize_content(body.get("content", "")),
        content_type=body.get("content_type", "application/json"),
        source_id=body.get("source_id", ""),
        correlation_id=body.get("correlation_id", ""),
        idempotency_key=body.get("idempotency_key", ""),
        input_hash=body.get("input_hash", ""),
        writer_signature=bytes.fromhex(body["writer_signature"]) if body.get("writer_signature") else b"",
        signer_key_reference=body.get("signer_key_reference", ""),
        attestation_report=bytes.fromhex(body["attestation_report"]) if body.get("attestation_report") else b"",
    )
    return jsonify({
        "entry_hash": receipt.entry_hash,
        "entry_type": receipt.entry_type,
        "chain_position": receipt.chain_position,
        "written_ts": receipt.written_ts,
        "entry_id": receipt.entry_id,
        "input_hash": receipt.input_hash,
        "writer_signature": receipt.writer_signature.hex() if receipt.writer_signature else "",
        "signer_key_reference": receipt.signer_key_reference,
        "attestation_report": receipt.attestation_report.hex() if receipt.attestation_report else "",
        "hash_version": receipt.hash_version,
    }), 201


@app.route("/api/receipts/verify")
def verify_proof():
    c = get_client()
    entry_hash = request.args.get("hash", "")
    entry_type = request.args.get("type", "")
    if not entry_hash or not entry_type:
        return jsonify({"error": "hash and type query params required"}), 400
    v = c.verify_proof(entry_hash, entry_type)
    return jsonify({
        "valid": v.valid,
        "entry_type": v.entry_type,
        "agent_id": v.agent_id,
        "source_id": v.source_id,
        "correlation_id": v.correlation_id,
        "content_type": v.content_type,
        "input_hash": v.input_hash,
        "written_ts": v.written_ts,
        "chain_position": v.chain_position,
        "failure_reason": v.failure_reason or "",
        "writer_signature": v.writer_signature.hex() if v.writer_signature else "",
        "signer_key_reference": v.signer_key_reference,
        "attestation_report": v.attestation_report.hex() if v.attestation_report else "",
        "hash_version": v.hash_version,
    })


@app.route("/api/entries/by-hash")
def get_entry_by_hash():
    c = get_client()
    entry_hash = request.args.get("hash", "")
    entry_type = request.args.get("type", "")
    if not entry_hash or not entry_type:
        return jsonify({"error": "hash and type query params required"}), 400
    entry = c.get_entry_by_hash(entry_hash, entry_type)
    return jsonify(entry_to_dict(entry))


@app.route("/api/receipts/chain")
def receipt_chain():
    c = get_client()
    corr = request.args.get("correlation_id", "")
    if not corr:
        return jsonify({"error": "correlation_id query param required"}), 400
    entries = c.query(correlation_id=corr)
    sorted_entries = sorted(entries, key=lambda e: e.written_ts)
    return jsonify({
        "correlation_id": corr,
        "hops": len(sorted_entries),
        "sources": list(set(e.source_id for e in sorted_entries)),
        "entries": [entry_to_dict(e) for e in sorted_entries],
    })


@app.route("/api/entries", methods=["GET"])
def get_entries():
    c = get_client()
    kwargs = {}
    for key in ("agent_id", "entry_type", "source_id", "correlation_id"):
        val = request.args.get(key, "")
        if val:
            kwargs[key] = val
    for key in ("from_ts", "to_ts"):
        val = request.args.get(key, "")
        if val:
            try:
                kwargs[key] = int(val)
            except ValueError:
                return jsonify({"error": f"{key} must be Unix milliseconds"}), 400
    page_size = request.args.get("page_size", "100")
    try:
        page_size = int(page_size)
    except ValueError:
        page_size = 100
    page_token = request.args.get("page_token", "")
    entries, next_token, total_count = c.query_page(
        page_size=page_size, page_token=page_token, **kwargs)
    return jsonify({
        "entries": [entry_to_dict(e) for e in entries],
        "next_page_token": next_token,
        "total_count": total_count,
    })


@app.route("/api/summary")
def get_summary():
    kwargs = {}
    for key in ("entry_type", "source_id", "agent_id"):
        val = request.args.get(key, "")
        if val:
            kwargs[key] = val
    for key in ("from_ts", "to_ts"):
        val = request.args.get(key, "")
        if val:
            try:
                kwargs[key] = int(val)
            except ValueError:
                return jsonify({"error": f"{key} must be Unix milliseconds"}), 400
    page_size = int(request.args.get("page_size", "10000"))
    entries, truncated = _query_capped(max_entries=page_size, **kwargs)
    by_source = {}
    by_type = {}
    for e in entries:
        by_source.setdefault(e.source_id, []).append(e)
        by_type.setdefault(e.entry_type, []).append(e)
    corr_ids = set(e.correlation_id for e in entries if e.correlation_id)
    cross_system = 0
    for cid in corr_ids:
        sources = set(e.source_id for e in entries if e.correlation_id == cid)
        if len(sources) > 1:
            cross_system += 1
    result = {
        "total_entries": len(entries),
        "sources": {s: len(es) for s, es in by_source.items()},
        "chain_types": len(by_type),
        "correlation_ids": len(corr_ids),
        "cross_system_correlations": cross_system,
    }
    if truncated:
        result["truncated"] = True
        result["truncated_note"] = f"Results capped at {page_size} entries; apply filters for accuracy"
    return jsonify(result)


@app.route("/api/chains")
def get_chains():
    kwargs = {}
    entry_type_filter = request.args.get("entry_type", "")
    if entry_type_filter:
        kwargs["entry_type"] = entry_type_filter
    page_size = int(request.args.get("page_size", "10000"))
    entries, truncated = _query_capped(max_entries=page_size, **kwargs)
    by_type = {}
    for e in entries:
        by_type.setdefault(e.entry_type, []).append(e)
    chains = []
    for et, es in sorted(by_type.items()):
        source = "unknown"
        if "openshell" in et:
            source = "openshell"
        elif "kagenti" in et:
            source = "kagenti"
        elif "gov." in et:
            source = "governance"
        elif "standalone" in et:
            source = "standalone"
        chains.append({
            "entry_type": et,
            "count": len(es),
            "source": source,
            "entries": [entry_to_dict(e) for e in sorted(es, key=lambda x: x.chain_position)],
        })
    result = {"chains": chains}
    if truncated:
        result["truncated"] = True
    return jsonify(result)


@app.route("/api/verify")
def verify_all():
    c = get_client()
    entry_type_filter = request.args.get("entry_type", "")
    if entry_type_filter:
        types = [entry_type_filter]
    else:
        # Discover all chain types (this is an audit operation so full scan is acceptable)
        entries = c.query()
        types = sorted(set(e.entry_type for e in entries))
    results = []
    for t in types:
        v = c.verify_chain(t)
        results.append({
            "entry_type": t,
            "chain_valid": v.chain_valid,
            "entries_checked": v.entries_checked,
            "failure_reason": v.failure_reason or "",
            "first_invalid_entry_id": v.first_invalid_entry_id or "",
        })
    all_valid = all(r["chain_valid"] for r in results)
    return jsonify({"all_valid": all_valid, "chains": results})


@app.route("/api/verify/<path:entry_type>")
def verify_chain(entry_type):
    c = get_client()
    v = c.verify_chain(entry_type)
    return jsonify({
        "entry_type": entry_type,
        "chain_valid": v.chain_valid,
        "entries_checked": v.entries_checked,
        "failure_reason": v.failure_reason or "",
    })


@app.route("/api/timeline")
def get_timeline():
    kwargs = {}
    for key in ("correlation_id",):
        val = request.args.get(key, "")
        if val:
            kwargs[key] = val
    for key in ("from_ts", "to_ts"):
        val = request.args.get(key, "")
        if val:
            try:
                kwargs[key] = int(val)
            except ValueError:
                return jsonify({"error": f"{key} must be Unix milliseconds"}), 400
    page_size = int(request.args.get("page_size", "10000"))
    entries, truncated = _query_capped(max_entries=page_size, **kwargs)
    sorted_entries = sorted(entries, key=lambda e: e.written_ts)
    corr_map = {}
    for e in sorted_entries:
        if e.correlation_id:
            corr_map.setdefault(e.correlation_id, []).append(e.entry_id)
    # Cross-system links: correlations that span multiple sources
    entry_source = {e.entry_id: e.source_id for e in sorted_entries}
    cross_links = {}
    for cid, ids in corr_map.items():
        sources = set(entry_source.get(eid, "") for eid in ids)
        if len(sources) > 1:
            cross_links[cid] = ids
    result = {
        "entries": [entry_to_dict(e) for e in sorted_entries],
        "correlations": {cid: ids for cid, ids in corr_map.items() if len(ids) > 1},
        "cross_links": cross_links,
    }
    if truncated:
        result["truncated"] = True
    return jsonify(result)


@app.route("/api/drift")
def get_drift():
    kwargs = {}
    for key in ("from_ts", "to_ts"):
        val = request.args.get(key, "")
        if val:
            try:
                kwargs[key] = int(val)
            except ValueError:
                return jsonify({"error": f"{key} must be Unix milliseconds"}), 400
    page_size = int(request.args.get("page_size", "10000"))
    entries, truncated = _query_capped(max_entries=page_size, **kwargs)
    denials = [e for e in entries if
               b"Denied" in e.content or b"Blocked" in e.content or
               "deny" in e.entry_type]
    scope_evals = [e for e in entries if "scope" in e.entry_type and "evaluated" in e.entry_type]
    gaps = []
    for d in denials:
        if not d.correlation_id:
            continue
        matching = [s for s in scope_evals if s.correlation_id == d.correlation_id]
        if not matching:
            try:
                content = json.loads(d.content.decode("utf-8"))
                detail = content.get("message", content.get("dst", "denied request"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = "denied request"
            gaps.append({
                "entry_id": d.entry_id,
                "correlation_id": d.correlation_id,
                "agent_id": d.agent_id,
                "source_id": d.source_id,
                "entry_type": d.entry_type,
                "detail": str(detail),
            })
    result = {
        "gaps": gaps,
        "total_denials": len(denials),
        "total_scope_evals": len(scope_evals),
    }
    if truncated:
        result["truncated"] = True
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", "18099"))
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    debug = os.environ.get("GATEWAY_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug, threaded=True)
