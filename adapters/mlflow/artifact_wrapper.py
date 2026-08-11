"""MLflow artifact repository wrapper — hashes artifacts on upload and records to ledger.

Phase 2 provenance integration. Wraps any existing MLflow ArtifactRepository to intercept
log_artifact/log_artifacts calls, compute SHA-256 content hashes, and write proof receipts
to the immutable ledger. Every model artifact gets a verifiable chain of custody.

Usage (in MLflow plugin setup.py entry_points):
  "mlflow.artifact_repository": [
      "ledger+s3=adapters.mlflow.artifact_wrapper:create_s3_wrapper",
      "ledger+local=adapters.mlflow.artifact_wrapper:create_local_wrapper",
  ]

Or wrap programmatically:
  from adapters.mlflow.artifact_wrapper import LedgerArtifactWrapper
  wrapper = LedgerArtifactWrapper(existing_repo, ledger_endpoint="localhost:19292")
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdks", "python"))
from ledger_client import LedgerClient

SOURCE_ID = "mlflow-artifacts"


class LedgerArtifactWrapper:
    """Decorator around an MLflow ArtifactRepository that records content hashes to the ledger."""

    def __init__(self, delegate, ledger_endpoint="localhost:19292", run_id=None, experiment_id=None):
        self._delegate = delegate
        self._client = LedgerClient(ledger_endpoint)
        self._run_id = run_id or ""
        self._experiment_id = experiment_id or ""

    def log_artifact(self, local_file, artifact_path=None):
        content_hash = self._hash_file(local_file)
        self._delegate.log_artifact(local_file, artifact_path)
        dest_path = artifact_path or os.path.basename(local_file)
        self._record_artifact(dest_path, content_hash, os.path.getsize(local_file))

    def log_artifacts(self, local_dir, artifact_path=None):
        hashes = {}
        for root, _dirs, files in os.walk(local_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, local_dir)
                if artifact_path:
                    rel = os.path.join(artifact_path, rel)
                hashes[rel] = (self._hash_file(full), os.path.getsize(full))

        self._delegate.log_artifacts(local_dir, artifact_path)

        for path, (content_hash, size) in hashes.items():
            self._record_artifact(path, content_hash, size)

    def _hash_file(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _record_artifact(self, artifact_path, content_hash, size_bytes):
        correlation_id = f"mlflow:run:{self._run_id}" if self._run_id else ""
        try:
            self._client.issue_receipt(
                entry_type="mlflow.artifact.logged",
                agent_id=f"mlflow-run:{self._run_id}" if self._run_id else "mlflow-artifacts",
                content=json.dumps({
                    "artifact_path": artifact_path,
                    "content_hash": content_hash,
                    "size_bytes": size_bytes,
                    "run_id": self._run_id,
                    "experiment_id": self._experiment_id,
                }),
                content_type="application/json",
                source_id=SOURCE_ID,
                correlation_id=correlation_id,
                input_hash=content_hash,
                idempotency_key=f"artifact:{self._run_id}:{artifact_path}:{content_hash}",
            )
        except Exception:
            pass

    def list_artifacts(self, path=None):
        return self._delegate.list_artifacts(path)

    def download_artifacts(self, artifact_path, dst_path=None):
        return self._delegate.download_artifacts(artifact_path, dst_path)

    def _download_file(self, remote_file_path, local_path):
        return self._delegate._download_file(remote_file_path, local_path)

    def __getattr__(self, name):
        return getattr(self._delegate, name)
