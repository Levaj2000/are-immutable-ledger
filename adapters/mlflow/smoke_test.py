#!/usr/bin/env python3
"""Smoke test: simulate MLflow webhook events against a running listener + ledger.

Prerequisites:
  1. Ledger running (cd demo && make up)
  2. Webhook listener running (python adapters/mlflow/webhook_listener.py)

Usage:
  python adapters/mlflow/smoke_test.py [--listener http://localhost:18098]
"""

import argparse
import json
import sys
import uuid

import requests

SCENARIOS = [
    {
        "name": "Register model",
        "payload": {
            "entity": "registered_model",
            "action": "created",
            "timestamp": "2026-08-11T13:00:00+00:00",
            "data": {
                "name": "fraud_detector",
                "tags": {"team": "risk-ai"},
                "description": "Real-time fraud scoring model",
            },
        },
    },
    {
        "name": "Create model version v1",
        "payload": {
            "entity": "model_version",
            "action": "created",
            "timestamp": "2026-08-11T13:05:00+00:00",
            "data": {
                "name": "fraud_detector",
                "version": "1",
                "source": "s3://mlflow-artifacts/1/abc123/artifacts/model",
                "run_id": "run-abc-001",
                "tags": {"framework": "xgboost"},
                "description": "Baseline model",
            },
        },
    },
    {
        "name": "Create model version v2",
        "payload": {
            "entity": "model_version",
            "action": "created",
            "timestamp": "2026-08-11T14:00:00+00:00",
            "data": {
                "name": "fraud_detector",
                "version": "2",
                "source": "s3://mlflow-artifacts/1/def456/artifacts/model",
                "run_id": "run-def-002",
                "tags": {"framework": "xgboost"},
                "description": "Tuned hyperparameters",
            },
        },
    },
    {
        "name": "Promote v2 to champion",
        "payload": {
            "entity": "model_version_alias",
            "action": "created",
            "timestamp": "2026-08-11T14:30:00+00:00",
            "data": {
                "name": "fraud_detector",
                "alias": "champion",
                "version": "2",
            },
        },
    },
    {
        "name": "Tag v2 as approved",
        "payload": {
            "entity": "model_version_tag",
            "action": "set",
            "timestamp": "2026-08-11T14:35:00+00:00",
            "data": {
                "name": "fraud_detector",
                "version": "2",
                "key": "approval",
                "value": "approved-by:risk-lead",
            },
        },
    },
]


def run_smoke(listener_url):
    print(f"\n  MLflow → Ledger Smoke Test")
    print(f"  Listener: {listener_url}\n")

    results = []
    for scenario in SCENARIOS:
        delivery_id = str(uuid.uuid4())
        try:
            resp = requests.post(
                f"{listener_url}/webhooks/mlflow",
                json=scenario["payload"],
                headers={
                    "Content-Type": "application/json",
                    "X-MLflow-Delivery-Id": delivery_id,
                    "X-MLflow-Timestamp": "1723384200",
                },
                timeout=5,
            )
            body = resp.json()
            ok = resp.status_code == 201
            results.append(ok)
            status = "OK" if ok else "FAIL"
            entry_type = body.get("entry_type", "?")
            chain_pos = body.get("chain_position", "?")
            print(f"  [{status}] {scenario['name']:<30} → {entry_type} (pos {chain_pos})")
            if not ok:
                print(f"         {resp.status_code}: {body}")
        except Exception as e:
            results.append(False)
            print(f"  [FAIL] {scenario['name']:<30} → {e}")

    passed = sum(results)
    total = len(results)
    print(f"\n  {passed}/{total} passed\n")
    return all(results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listener", default="http://localhost:18098")
    args = parser.parse_args()
    ok = run_smoke(args.listener)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
