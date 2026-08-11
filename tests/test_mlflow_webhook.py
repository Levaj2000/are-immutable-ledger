"""End-to-end test for the MLflow webhook listener.

Tests the webhook listener in isolation (no ledger needed) by mocking the
LedgerClient, then verifies the full request→parse→record→receipt flow.

Run: python -m pytest -q tests/test_mlflow_webhook.py
"""

import json
import sys
import os
import hashlib
import hmac
import base64
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "adapters", "mlflow"))


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.issue_receipt.return_value = SimpleNamespace(
        entry_hash="abc123hash",
        entry_id="entry-uuid-1",
        chain_position=1,
        entry_type="mlflow.model_version.created",
    )
    return client


@pytest.fixture
def app(mock_client):
    with patch("webhook_listener.get_client", return_value=mock_client):
        import webhook_listener
        webhook_listener._client = mock_client
        webhook_listener.app.testing = True
        yield webhook_listener.app


@pytest.fixture
def client(app):
    return app.test_client()


def model_version_created_payload():
    return {
        "entity": "model_version",
        "action": "created",
        "timestamp": "2026-08-11T14:30:00.123456+00:00",
        "data": {
            "name": "fraud_detector",
            "version": "3",
            "source": "models:/abc123",
            "run_id": "run-xyz-789",
            "tags": {"stage": "staging"},
            "description": "Fine-tuned v3",
        },
    }


def model_alias_created_payload():
    return {
        "entity": "model_version_alias",
        "action": "created",
        "timestamp": "2026-08-11T15:00:00+00:00",
        "data": {
            "name": "fraud_detector",
            "alias": "champion",
            "version": "3",
        },
    }


def registered_model_payload():
    return {
        "entity": "registered_model",
        "action": "created",
        "timestamp": "2026-08-11T13:00:00+00:00",
        "data": {
            "name": "fraud_detector",
            "tags": {},
            "description": "Production fraud model",
        },
    }


class TestWebhookReceiver:
    def test_model_version_created(self, client, mock_client):
        payload = model_version_created_payload()
        resp = client.post(
            "/webhooks/mlflow",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "delivery-1"},
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "recorded"
        assert body["entry_type"] == "mlflow.model_version.created"
        assert body["entry_hash"] == "abc123hash"

        call = mock_client.issue_receipt.call_args
        assert call.kwargs["entry_type"] == "mlflow.model_version.created"
        assert call.kwargs["source_id"] == "mlflow-registry"
        assert call.kwargs["correlation_id"] == "mlflow:fraud_detector:v3"
        assert call.kwargs["idempotency_key"] == "delivery-1"
        assert len(call.kwargs["input_hash"]) == 64

        content = json.loads(call.kwargs["content"])
        assert content["data"]["name"] == "fraud_detector"
        assert content["data"]["version"] == "3"
        assert content["data"]["run_id"] == "run-xyz-789"

    def test_model_alias_created(self, client, mock_client):
        payload = model_alias_created_payload()
        resp = client.post(
            "/webhooks/mlflow",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "delivery-2"},
        )
        assert resp.status_code == 201
        call = mock_client.issue_receipt.call_args
        assert call.kwargs["entry_type"] == "mlflow.model_version_alias.created"
        assert call.kwargs["correlation_id"] == "mlflow:fraud_detector:v3"

    def test_registered_model_created(self, client, mock_client):
        payload = registered_model_payload()
        resp = client.post(
            "/webhooks/mlflow",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "delivery-3"},
        )
        assert resp.status_code == 201
        call = mock_client.issue_receipt.call_args
        assert call.kwargs["entry_type"] == "mlflow.registered_model.created"
        assert call.kwargs["correlation_id"] == "mlflow:fraud_detector"

    def test_idempotency_uses_delivery_id(self, client, mock_client):
        payload = model_version_created_payload()
        for _ in range(2):
            client.post(
                "/webhooks/mlflow",
                data=json.dumps(payload),
                content_type="application/json",
                headers={"X-MLflow-Delivery-Id": "same-delivery"},
            )
        for call in mock_client.issue_receipt.call_args_list:
            assert call.kwargs["idempotency_key"] == "same-delivery"

    def test_input_hash_is_deterministic(self, client, mock_client):
        payload = model_version_created_payload()
        client.post(
            "/webhooks/mlflow",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "d1"},
        )
        hash1 = mock_client.issue_receipt.call_args.kwargs["input_hash"]

        client.post(
            "/webhooks/mlflow",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "d2"},
        )
        hash2 = mock_client.issue_receipt.call_args.kwargs["input_hash"]
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_input_hash_changes_with_data(self, client, mock_client):
        p1 = model_version_created_payload()
        client.post(
            "/webhooks/mlflow",
            data=json.dumps(p1),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "d1"},
        )
        hash1 = mock_client.issue_receipt.call_args.kwargs["input_hash"]

        p2 = model_version_created_payload()
        p2["data"]["version"] = "4"
        client.post(
            "/webhooks/mlflow",
            data=json.dumps(p2),
            content_type="application/json",
            headers={"X-MLflow-Delivery-Id": "d2"},
        )
        hash2 = mock_client.issue_receipt.call_args.kwargs["input_hash"]
        assert hash1 != hash2

    def test_rejects_invalid_json(self, client):
        resp = client.post(
            "/webhooks/mlflow",
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_healthz(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200


class TestHmacVerification:
    def test_rejects_invalid_signature_when_secret_configured(self, mock_client):
        with patch("webhook_listener.get_client", return_value=mock_client):
            import webhook_listener
            original_secret = webhook_listener.WEBHOOK_HMAC_SECRET
            webhook_listener.WEBHOOK_HMAC_SECRET = "test-secret"
            webhook_listener._client = mock_client
            try:
                test_client = webhook_listener.app.test_client()
                payload = model_version_created_payload()
                resp = test_client.post(
                    "/webhooks/mlflow",
                    data=json.dumps(payload),
                    content_type="application/json",
                    headers={
                        "X-MLflow-Delivery-Id": "d1",
                        "X-MLflow-Timestamp": "1723384200",
                        "X-MLflow-Signature": "v1,invalidsignature",
                    },
                )
                assert resp.status_code == 401
            finally:
                webhook_listener.WEBHOOK_HMAC_SECRET = original_secret

    def test_accepts_valid_signature(self, mock_client):
        with patch("webhook_listener.get_client", return_value=mock_client):
            import webhook_listener
            secret = "test-secret-123"
            original_secret = webhook_listener.WEBHOOK_HMAC_SECRET
            webhook_listener.WEBHOOK_HMAC_SECRET = secret
            webhook_listener._client = mock_client
            try:
                test_client = webhook_listener.app.test_client()
                payload = model_version_created_payload()
                payload_json = json.dumps(payload)
                delivery_id = "sig-test-delivery"
                timestamp = "1723384200"
                signing_input = f"{delivery_id}.{timestamp}.{payload_json}"
                sig = hmac.new(
                    secret.encode(), signing_input.encode(), hashlib.sha256
                ).digest()
                sig_b64 = base64.b64encode(sig).decode()

                resp = test_client.post(
                    "/webhooks/mlflow",
                    data=payload_json,
                    content_type="application/json",
                    headers={
                        "X-MLflow-Delivery-Id": delivery_id,
                        "X-MLflow-Timestamp": timestamp,
                        "X-MLflow-Signature": f"v1,{sig_b64}",
                    },
                )
                assert resp.status_code == 201
            finally:
                webhook_listener.WEBHOOK_HMAC_SECRET = original_secret
