"""Tests for the CPEX-to-Ledger adapter.

Tests field extraction, gap detection, content canonicalization, and the
full processing flow with a mocked LedgerClient.

Run: python -m pytest -q tests/test_cpex_adapter.py
"""

import base64
import hashlib
import json
import sys
import os
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "adapters", "cpex"))

from cpex_to_ledger import (
    GapDetector,
    canonicalize_content,
    detect_record_type,
    extract_agent_id,
    extract_correlation_id,
    extract_idempotency_key,
    extract_signer_key_reference,
    extract_stream_stamps,
    extract_writer_signature,
    process_line,
)


def make_decision_event(**overrides):
    event = {
        "class_uid": 6003,
        "class_name": "AI Operation",
        "stream_id": "dec-boot-001",
        "stream_seq": 1,
        "emission_seq": 1,
        "activity_id": 1,
        "ai_agent": {"uid": "agent-alpha-7"},
        "metadata": {
            "uid": "record-uuid-001",
            "correlation_uid": "trace-abc-123",
            "version": "1.9.0",
        },
        "unmapped": {
            "signature_b64": base64.b64encode(b"test-signature-bytes").decode(),
            "signature_key_id": "spiffe://cpex/signer/key-01",
        },
        "data": {"tool": "get_compensation", "result": "allowed"},
    }
    event.update(overrides)
    return event


def make_effect_event(**overrides):
    event = make_decision_event(
        stream_id="eff-boot-001",
        stream_seq=1,
        emission_seq=2,
        activity_id=2,
        **overrides,
    )
    event["metadata"] = {
        "uid": "record-uuid-002",
        "correlation_uid": "trace-abc-123",
        "version": "1.9.0",
    }
    return event


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.issue_receipt.return_value = SimpleNamespace(
        entry_hash="hash123",
        entry_id="entry-uuid-1",
        chain_position=1,
    )
    client.write.return_value = SimpleNamespace(
        chain_position=1,
        entry_hash="hash123",
        entry_id="entry-uuid-1",
    )
    return client


@pytest.fixture
def gap_detector():
    return GapDetector()


@pytest.fixture
def stats():
    return {
        "written": 0,
        "parse_errors": 0,
        "write_errors": 0,
        "skipped": 0,
        "gaps_detected": 0,
    }


# --- Record type detection ---


class TestRecordTypeDetection:
    def test_decision_from_current_payload_shape(self):
        event = make_decision_event(stream_id="gw-1/boot-7")
        event["unmapped"]["cpex.decision"] = {"verdict": "allow", "steps": []}
        assert detect_record_type(event) == "decision"

    def test_effect_from_current_payload_shape(self):
        event = make_decision_event(stream_id="gw-1/boot-7")
        event["unmapped"]["cpex.effect"] = {"effect": "begin"}
        assert detect_record_type(event) == "effect"

    def test_decision_from_dec_prefix(self):
        event = make_decision_event(stream_id="dec-boot-001")
        assert detect_record_type(event) == "decision"

    def test_effect_from_eff_prefix(self):
        event = make_decision_event(stream_id="eff-boot-001")
        assert detect_record_type(event) == "effect"

    def test_unknown_prefix_returns_none(self):
        event = make_decision_event(stream_id="unknown-prefix")
        assert detect_record_type(event) is None

    def test_empty_stream_id_returns_none(self):
        event = make_decision_event(stream_id="")
        assert detect_record_type(event) is None

    def test_missing_stream_id_returns_none(self):
        event = make_decision_event()
        del event["stream_id"]
        assert detect_record_type(event) is None


# --- Field extraction ---


class TestFieldExtraction:
    def test_stream_stamps_from_aid_emit_nested_shape(self):
        event = make_decision_event()
        event["unmapped"]["cpex.stream"] = {
            "epoch": 1755000000000000000,
            "stream_id": "gw-1/boot-7",
            "stream_seq": 7,
            "emission_seq": 42,
        }
        assert extract_stream_stamps(event) == (
            1755000000000000000,
            "gw-1/boot-7",
            7,
            42,
        )

    def test_stream_stamps_legacy_fallback(self):
        event = make_decision_event()
        assert extract_stream_stamps(event) == (None, "dec-boot-001", 1, 1)

    def test_agent_id_from_ai_agent_uid(self):
        event = make_decision_event()
        assert extract_agent_id(event) == "agent-alpha-7"

    def test_agent_id_not_from_metadata_uid(self):
        event = make_decision_event()
        result = extract_agent_id(event)
        assert result != "record-uuid-001"

    def test_agent_id_fallback_to_agent_id_field(self):
        event = {"agent_id": "fallback-agent"}
        assert extract_agent_id(event) == "fallback-agent"

    def test_agent_id_fallback_to_unknown(self):
        event = {}
        assert extract_agent_id(event) == "unknown"

    def test_correlation_id_from_request_join_key(self):
        event = make_decision_event()
        event["unmapped"]["cmf.request.request_id"] = "request-draw-42"
        assert extract_correlation_id(event) == "request-draw-42"

    def test_correlation_id_falls_back_to_metadata(self):
        event = make_decision_event()
        assert extract_correlation_id(event) == "trace-abc-123"

    def test_correlation_id_empty_when_missing(self):
        event = {"metadata": {}}
        assert extract_correlation_id(event) == ""

    def test_idempotency_key_from_metadata_uid(self):
        event = make_decision_event()
        assert extract_idempotency_key(event) == "record-uuid-001"

    def test_writer_signature_base64_decoded(self):
        event = make_decision_event()
        sig = extract_writer_signature(event)
        assert sig == b"test-signature-bytes"

    def test_writer_signature_empty_when_missing(self):
        event = {"unmapped": {}}
        assert extract_writer_signature(event) == b""

    def test_writer_signature_invalid_base64_returns_empty(self):
        event = {"unmapped": {"signature_b64": "!!!not-base64!!!"}}
        sig = extract_writer_signature(event)
        assert sig == b""

    def test_signer_key_reference(self):
        event = make_decision_event()
        assert extract_signer_key_reference(event) == "spiffe://cpex/signer/key-01"

    def test_signer_key_reference_empty_when_missing(self):
        event = {"unmapped": {}}
        assert extract_signer_key_reference(event) == ""


# --- Gap detection ---


class TestGapDetection:
    def test_no_gap_sequential(self, gap_detector):
        alerts = gap_detector.check("dec-001", 1, 1)
        assert alerts == []
        alerts = gap_detector.check("dec-001", 2, 2)
        assert alerts == []

    def test_gap_detected(self, gap_detector):
        gap_detector.check("dec-001", 1, 1)
        alerts = gap_detector.check("dec-001", 3, 3)
        assert len(alerts) == 1
        assert "GAP" in alerts[0]
        assert "expected stream_seq 2" in alerts[0]

    def test_multiple_streams_independent(self, gap_detector):
        gap_detector.check("dec-001", 1, 1)
        gap_detector.check("eff-001", 1, 2)
        alerts = gap_detector.check("dec-001", 2, 3)
        assert alerts == []
        alerts = gap_detector.check("eff-001", 2, 4)
        assert alerts == []

    def test_emission_seq_ordering_violation(self, gap_detector):
        gap_detector.check("dec-001", 1, 5)
        alerts = gap_detector.check("dec-001", 2, 3)
        assert any("ORDERING" in a for a in alerts)

    def test_emission_seq_none_no_crash(self, gap_detector):
        alerts = gap_detector.check("dec-001", 1, None)
        assert alerts == []

    def test_emission_seq_equal_triggers_ordering(self, gap_detector):
        gap_detector.check("dec-001", 1, 5)
        alerts = gap_detector.check("dec-001", 2, 5)
        assert any("ORDERING" in a for a in alerts)

    def test_new_epoch_starts_fresh_sequence_scope(self, gap_detector):
        gap_detector.check("gw-1", 7, 42, epoch=100)
        alerts = gap_detector.check("gw-1", 1, 1, epoch=101)
        assert alerts == []

    def test_same_stream_id_is_independent_across_epochs(self, gap_detector):
        gap_detector.check("gw-1", 1, 1, epoch=100)
        gap_detector.check("gw-1", 1, 1, epoch=101)
        assert gap_detector.check("gw-1", 2, 2, epoch=100) == []
        assert gap_detector.check("gw-1", 2, 2, epoch=101) == []


# --- Content canonicalization ---


class TestCanonicalization:
    def test_envelope_fields_stripped(self):
        event = make_decision_event()
        canonical_bytes, _ = canonicalize_content(event)
        content = json.loads(canonical_bytes)
        unmapped = content.get("unmapped", {})
        assert "signature_b64" not in unmapped
        assert "signature_key_id" not in unmapped

    def test_non_envelope_unmapped_preserved(self):
        event = make_decision_event()
        event["unmapped"]["custom_field"] = "keep-me"
        canonical_bytes, _ = canonicalize_content(event)
        content = json.loads(canonical_bytes)
        assert content["unmapped"]["custom_field"] == "keep-me"

    def test_aid_emit_attestation_derivations_stripped(self):
        event = make_decision_event()
        event["attestation_list"] = [
            {
                "uid": "att-1",
                "chain_uid": "chain-1",
                "authority_uid": "authority-1",
                "prev_event": {"uid": "record-0"},
                "fingerprint": {"value": "derived"},
                "signatures": [{"algorithm": "ECDSA"}],
            }
        ]
        canonical_bytes, _ = canonicalize_content(event)
        attestation = json.loads(canonical_bytes)["attestation_list"][0]
        assert "fingerprint" not in attestation
        assert "signatures" not in attestation
        assert attestation["uid"] == "att-1"
        assert attestation["chain_uid"] == "chain-1"
        assert attestation["authority_uid"] == "authority-1"
        assert attestation["prev_event"] == {"uid": "record-0"}

    @pytest.mark.parametrize("line_number", [0, 1])
    def test_aid_emit_1_post_489_conformance_vectors(self, line_number):
        fixture = os.path.join(
            os.path.dirname(__file__), "fixtures", "aid_emit_1_post_489.jsonl"
        )
        with open(fixture, encoding="utf-8") as records:
            event = json.loads(records.readlines()[line_number])

        expected = event["attestation_list"][0]["fingerprint"]["value"]
        _, actual = canonicalize_content(event)
        assert actual == expected

    def test_empty_unmapped_removed(self):
        event = make_decision_event()
        event["unmapped"] = {"signature_b64": "abc", "signature_key_id": "xyz"}
        canonical_bytes, _ = canonicalize_content(event)
        content = json.loads(canonical_bytes)
        assert "unmapped" not in content

    def test_deterministic_output(self):
        event = make_decision_event()
        b1, h1 = canonicalize_content(event)
        b2, h2 = canonicalize_content(event)
        assert b1 == b2
        assert h1 == h2

    def test_hash_is_sha256_of_canonical(self):
        event = make_decision_event()
        canonical_bytes, content_hash = canonicalize_content(event)
        expected = hashlib.sha256(canonical_bytes).hexdigest()
        assert content_hash == expected
        assert len(content_hash) == 64

    def test_hash_changes_with_data(self):
        e1 = make_decision_event()
        e2 = make_decision_event()
        e2["data"]["result"] = "denied"
        _, h1 = canonicalize_content(e1)
        _, h2 = canonicalize_content(e2)
        assert h1 != h2

    def test_original_event_not_mutated(self):
        event = make_decision_event()
        original_unmapped = dict(event["unmapped"])
        canonicalize_content(event)
        assert event["unmapped"] == original_unmapped


# --- End-to-end processing ---


class TestProcessLine:
    def test_restart_uses_new_epoch_and_attestation_chain_without_false_gap(
        self, mock_client, stats, gap_detector
    ):
        first = make_decision_event(stream_id="gw-1/boot-7")
        first["metadata"]["uid"] = "producer-a-000005"
        first["attestation_list"] = [{"chain_uid": "producer-a"}]
        first["unmapped"].update(
            {
                "cpex.decision": {"verdict": "allow", "steps": []},
                "cpex.stream": {
                    "epoch": 1755648000000000000,
                    "stream_id": "gw-1/boot-7",
                    "stream_seq": 45,
                    "emission_seq": 45,
                },
            }
        )
        restarted = make_decision_event(stream_id="gw-1/boot-7")
        restarted["metadata"]["uid"] = "producer-b-000001"
        restarted["attestation_list"] = [{"chain_uid": "producer-b"}]
        restarted["unmapped"].update(
            {
                "cpex.decision": {"verdict": "deny", "steps": []},
                "cpex.stream": {
                    "epoch": 1755649000000000000,
                    "stream_id": "gw-1/boot-7",
                    "stream_seq": 1,
                    "emission_seq": 1,
                },
            }
        )

        process_line(mock_client, json.dumps(first), stats, gap_detector)
        process_line(mock_client, json.dumps(restarted), stats, gap_detector)

        assert stats["written"] == 2
        assert stats["gaps_detected"] == 0
        calls = mock_client.issue_receipt.call_args_list
        assert calls[0].kwargs["entry_type"] == calls[1].kwargs["entry_type"] == "cpex.decision"
        assert calls[0].kwargs["idempotency_key"] == "producer-a-000005"
        assert calls[1].kwargs["idempotency_key"] == "producer-b-000001"

    def test_current_decision_shape_is_written_and_stamps_are_checked(
        self, mock_client, stats, gap_detector
    ):
        event = make_decision_event(stream_id="gw-1/boot-7")
        event["unmapped"].update(
            {
                "cpex.decision": {"verdict": "allow", "steps": []},
                "cpex.stream": {
                    "epoch": 1755000000000000000,
                    "stream_id": "gw-1/boot-7",
                    "stream_seq": 7,
                    "emission_seq": 42,
                },
            }
        )

        process_line(mock_client, json.dumps(event), stats, gap_detector)

        assert stats["written"] == 1
        assert stats["skipped"] == 0
        call = mock_client.issue_receipt.call_args
        assert call.kwargs["entry_type"] == "cpex.decision"

        event["unmapped"]["cpex.stream"]["stream_seq"] = 9
        event["unmapped"]["cpex.stream"]["emission_seq"] = 44
        process_line(mock_client, json.dumps(event), stats, gap_detector)
        assert stats["gaps_detected"] == 1

    def test_decision_calls_issue_receipt(self, mock_client, stats, gap_detector):
        event = make_decision_event()
        line = json.dumps(event)
        process_line(mock_client, line, stats, gap_detector)

        assert stats["written"] == 1
        call = mock_client.issue_receipt.call_args
        assert call.kwargs["entry_type"] == "cpex.decision"
        assert call.kwargs["agent_id"] == "agent-alpha-7"
        assert call.kwargs["source_id"] == "cpex-audit-seam"
        assert call.kwargs["content_type"] == "application/ocsf+json"
        assert call.kwargs["correlation_id"] == "trace-abc-123"
        assert call.kwargs["idempotency_key"] == "record-uuid-001"
        assert call.kwargs["writer_signature"] == b"test-signature-bytes"
        assert call.kwargs["signer_key_reference"] == "spiffe://cpex/signer/key-01"
        assert len(call.kwargs["input_hash"]) == 64

    def test_effect_calls_issue_receipt(self, mock_client, stats, gap_detector):
        event = make_effect_event()
        line = json.dumps(event)
        process_line(mock_client, line, stats, gap_detector)

        call = mock_client.issue_receipt.call_args
        assert call.kwargs["entry_type"] == "cpex.effect"

    def test_write_only_uses_write(self, mock_client, stats, gap_detector):
        event = make_decision_event()
        line = json.dumps(event)
        process_line(mock_client, line, stats, gap_detector, write_only=True)

        assert mock_client.write.called
        assert not mock_client.issue_receipt.called

    def test_unknown_stream_id_skipped(self, mock_client, stats, gap_detector):
        event = make_decision_event(stream_id="unknown-prefix")
        line = json.dumps(event)
        process_line(mock_client, line, stats, gap_detector)

        assert stats["skipped"] == 1
        assert not mock_client.issue_receipt.called

    def test_parse_error(self, mock_client, stats, gap_detector):
        process_line(mock_client, "not json", stats, gap_detector)
        assert stats["parse_errors"] == 1

    def test_empty_line_ignored(self, mock_client, stats, gap_detector):
        process_line(mock_client, "", stats, gap_detector)
        process_line(mock_client, "  \n", stats, gap_detector)
        assert stats == {
            "written": 0,
            "parse_errors": 0,
            "write_errors": 0,
            "skipped": 0,
            "gaps_detected": 0,
        }

    def test_write_error_continues(self, mock_client, stats, gap_detector):
        mock_client.issue_receipt.side_effect = Exception("connection refused")
        event = make_decision_event()
        process_line(mock_client, json.dumps(event), stats, gap_detector)
        assert stats["write_errors"] == 1
        assert stats["written"] == 0

    def test_gap_increments_stats(self, mock_client, stats, gap_detector):
        e1 = make_decision_event(stream_seq=1, emission_seq=1)
        e2 = make_decision_event(stream_seq=3, emission_seq=3)
        e2["metadata"]["uid"] = "record-uuid-003"
        process_line(mock_client, json.dumps(e1), stats, gap_detector)
        process_line(mock_client, json.dumps(e2), stats, gap_detector)
        assert stats["gaps_detected"] == 1
        assert stats["written"] == 2

    def test_content_is_canonical_bytes(self, mock_client, stats, gap_detector):
        event = make_decision_event()
        process_line(mock_client, json.dumps(event), stats, gap_detector)

        call = mock_client.issue_receipt.call_args
        content_bytes = call.kwargs["content"]
        content = json.loads(content_bytes)
        assert "signature_b64" not in content.get("unmapped", {})

    def test_input_hash_matches_content(self, mock_client, stats, gap_detector):
        event = make_decision_event()
        process_line(mock_client, json.dumps(event), stats, gap_detector)

        call = mock_client.issue_receipt.call_args
        content_bytes = call.kwargs["content"]
        input_hash = call.kwargs["input_hash"]
        expected = hashlib.sha256(content_bytes).hexdigest()
        assert input_hash == expected
