#!/usr/bin/env python3
"""MLflow webhook listener — records model registry events as ledger proof receipts.

Receives MLflow webhook POST payloads (model_version.created, model_version_alias.created,
registered_model.created, etc.) and writes them to the immutable ledger with tamper-evident
proof receipts. Each event gets an entry_type of "mlflow.<entity>.<action>" and carries
the full webhook payload as content.

Usage:
  # Start listener (point MLflow webhooks at http://<host>:18098/webhooks/mlflow)
  python webhook_listener.py

  # Or configure via env:
  LEDGER_ENDPOINT=localhost:19292 WEBHOOK_PORT=18098 python webhook_listener.py

Integration with MLflow:
  import mlflow
  mlflow.create_webhook(
      events=["model_version.created", "model_version_alias.created"],
      http_url="http://localhost:18098/webhooks/mlflow",
      description="Immutable ledger attestation",
  )
"""

import hashlib
import hmac
import json
import os
import sys

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdks", "python"))
from ledger_client import LedgerClient

app = Flask(__name__)

LEDGER_ENDPOINT = os.environ.get("LEDGER_ENDPOINT", "localhost:19292")
WEBHOOK_HMAC_SECRET = os.environ.get("MLFLOW_WEBHOOK_HMAC_SECRET", "")
SOURCE_ID = "mlflow-registry"

_client = None


def get_client():
    global _client
    if _client is None:
        _client = LedgerClient(LEDGER_ENDPOINT)
    return _client


def verify_signature(payload_bytes, headers):
    """Verify MLflow HMAC-SHA256 signature if a shared secret is configured."""
    if not WEBHOOK_HMAC_SECRET:
        return True
    sig_header = headers.get("X-MLflow-Signature", "")
    if not sig_header.startswith("v1,"):
        return False
    delivery_id = headers.get("X-MLflow-Delivery-Id", "")
    timestamp = headers.get("X-MLflow-Timestamp", "")
    signing_input = f"{delivery_id}.{timestamp}.{payload_bytes.decode('utf-8')}"
    expected = hmac.new(
        WEBHOOK_HMAC_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    import base64
    expected_b64 = base64.b64encode(expected).decode()
    actual_b64 = sig_header[3:]
    return hmac.compare_digest(expected_b64, actual_b64)


def build_entry_type(entity, action):
    return f"mlflow.{entity}.{action}"


def build_correlation_id(entity, data):
    """Build a stable correlation ID from the model/prompt identity."""
    name = data.get("name", "")
    version = data.get("version", "")
    if version:
        return f"mlflow:{name}:v{version}"
    return f"mlflow:{name}"


def build_idempotency_key(headers, entity, action):
    delivery_id = headers.get("X-MLflow-Delivery-Id", "")
    if delivery_id:
        return delivery_id
    return f"{entity}.{action}.{hash(json.dumps(request.get_json(), sort_keys=True))}"


def compute_input_hash(data):
    """SHA-256 of the webhook data payload for content-addressing."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@app.route("/webhooks/mlflow", methods=["POST"])
def receive_webhook():
    payload_bytes = request.get_data()
    if not verify_signature(payload_bytes, request.headers):
        return jsonify({"error": "invalid signature"}), 401

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "invalid JSON"}), 400

    entity = body.get("entity", "unknown")
    action = body.get("action", "unknown")
    data = body.get("data", {})
    timestamp = body.get("timestamp", "")

    entry_type = build_entry_type(entity, action)
    correlation_id = build_correlation_id(entity, data)
    idempotency_key = build_idempotency_key(request.headers, entity, action)
    input_hash = compute_input_hash(data)

    agent_id = f"mlflow-registry:{data.get('name', 'unknown')}"

    client = get_client()
    try:
        receipt = client.issue_receipt(
            entry_type=entry_type,
            agent_id=agent_id,
            content=json.dumps({
                "entity": entity,
                "action": action,
                "timestamp": timestamp,
                "data": data,
            }),
            content_type="application/mlflow-webhook+json",
            source_id=SOURCE_ID,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            input_hash=input_hash,
        )
        return jsonify({
            "status": "recorded",
            "entry_type": entry_type,
            "entry_hash": receipt.entry_hash,
            "entry_id": receipt.entry_id,
            "chain_position": receipt.chain_position,
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("WEBHOOK_PORT", "18098"))
    host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
    print(f"\n  MLflow Webhook Listener")
    print(f"  Ledger:   {LEDGER_ENDPOINT}")
    print(f"  Listen:   {host}:{port}")
    print(f"  Endpoint: POST /webhooks/mlflow\n")
    app.run(host=host, port=port)
