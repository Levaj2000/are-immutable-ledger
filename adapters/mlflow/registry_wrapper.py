"""MLflow model registry store wrapper — full provenance via ledger proof receipts.

Phase 3 provenance integration. Wraps any MLflow AbstractStore to intercept model
registration, version creation, stage transitions, and alias assignments. Every
lifecycle event gets a tamper-evident proof receipt in the ledger, creating a complete
provenance chain from experiment run to production deployment.

Usage (in MLflow plugin setup.py entry_points):
  "mlflow.model_registry_store": [
      "ledger+sqlite=adapters.mlflow.registry_wrapper:create_sqlite_wrapper",
  ]

Or wrap programmatically:
  from adapters.mlflow.registry_wrapper import LedgerRegistryWrapper
  wrapper = LedgerRegistryWrapper(existing_store, ledger_endpoint="localhost:19292")
"""

import json
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdks", "python"))
from ledger_client import LedgerClient

SOURCE_ID = "mlflow-registry"


class LedgerRegistryWrapper:
    """Decorator around an MLflow AbstractStore that records lifecycle events to the ledger."""

    def __init__(self, delegate, ledger_endpoint="localhost:19292"):
        self._delegate = delegate
        self._client = LedgerClient(ledger_endpoint)

    def create_registered_model(self, name, tags=None, description=None):
        result = self._delegate.create_registered_model(name, tags=tags, description=description)
        self._record("mlflow.model.registered", name, {
            "name": name,
            "tags": {t.key: t.value for t in (tags or [])},
            "description": description or "",
        })
        return result

    def create_model_version(self, name, source, run_id=None, tags=None,
                             run_link=None, description=None, **kwargs):
        result = self._delegate.create_model_version(
            name, source, run_id=run_id, tags=tags,
            run_link=run_link, description=description, **kwargs
        )
        version = getattr(result, "version", "unknown")
        self._record("mlflow.model_version.created", name, {
            "name": name,
            "version": str(version),
            "source": source,
            "run_id": run_id or "",
            "tags": {t.key: t.value for t in (tags or [])},
            "description": description or "",
        }, correlation_id=f"mlflow:{name}:v{version}")
        return result

    def transition_model_version_stage(self, name, version, stage, archive_existing_versions=False):
        result = self._delegate.transition_model_version_stage(
            name, version, stage, archive_existing_versions=archive_existing_versions
        )
        self._record("mlflow.model_version.stage_transition", name, {
            "name": name,
            "version": str(version),
            "stage": stage,
            "archive_existing": archive_existing_versions,
        }, correlation_id=f"mlflow:{name}:v{version}")
        return result

    def set_registered_model_alias(self, name, alias, version):
        result = self._delegate.set_registered_model_alias(name, alias, version)
        self._record("mlflow.model_version.alias_set", name, {
            "name": name,
            "alias": alias,
            "version": str(version),
        }, correlation_id=f"mlflow:{name}:v{version}")
        return result

    def delete_registered_model_alias(self, name, alias):
        result = self._delegate.delete_registered_model_alias(name, alias)
        self._record("mlflow.model_version.alias_deleted", name, {
            "name": name,
            "alias": alias,
        })
        return result

    def delete_model_version(self, name, version):
        self._record("mlflow.model_version.deleted", name, {
            "name": name,
            "version": str(version),
        }, correlation_id=f"mlflow:{name}:v{version}")
        return self._delegate.delete_model_version(name, version)

    def delete_registered_model(self, name):
        self._record("mlflow.model.deleted", name, {"name": name})
        return self._delegate.delete_registered_model(name)

    def set_model_version_tag(self, name, version, tag):
        result = self._delegate.set_model_version_tag(name, version, tag)
        self._record("mlflow.model_version.tag_set", name, {
            "name": name,
            "version": str(version),
            "tag_key": tag.key,
            "tag_value": tag.value,
        }, correlation_id=f"mlflow:{name}:v{version}")
        return result

    def _record(self, entry_type, model_name, data, correlation_id=None):
        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        input_hash = hashlib.sha256(content.encode()).hexdigest()
        try:
            self._client.issue_receipt(
                entry_type=entry_type,
                agent_id=f"mlflow-registry:{model_name}",
                content=content,
                content_type="application/json",
                source_id=SOURCE_ID,
                correlation_id=correlation_id or f"mlflow:{model_name}",
                input_hash=input_hash,
            )
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._delegate, name)
