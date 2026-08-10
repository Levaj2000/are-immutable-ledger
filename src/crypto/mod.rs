use sha2::{Digest, Sha256};
use uuid::Uuid;

pub const ENTRY_HASH_VERSION_V2: &str = "ARE_LEDGER_ENTRY_HASH_V2";
pub const ENTRY_HASH_VERSION_V3: &str = "ARE_LEDGER_ENTRY_HASH_V3";
pub const ENTRY_HASH_VERSION: &str = ENTRY_HASH_VERSION_V3;

pub struct CanonicalEntryHashInput<'a> {
    pub entry_id: Uuid,
    pub entry_type: &'a str,
    pub agent_id: &'a str,
    pub content: &'a [u8],
    pub content_type: &'a str,
    pub source_id: &'a str,
    pub correlation_id: Option<&'a str>,
    pub idempotency_key: Option<&'a str>,
    pub input_hash: Option<&'a str>,
    pub writer_signature: Option<&'a [u8]>,
    pub signer_key_reference: Option<&'a str>,
    pub attestation_report: Option<&'a [u8]>,
    pub chain_position: i64,
    pub written_ts_ms: i64,
    pub previous_hash: &'a str,
}

pub fn sha256_hex(value: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value);
    hex::encode(hasher.finalize())
}

pub fn advisory_lock_key(entry_type: &str) -> i64 {
    let mut hasher = Sha256::new();
    hasher.update(entry_type.as_bytes());
    let hash = hasher.finalize();
    i64::from_be_bytes(hash[..8].try_into().unwrap())
}

pub fn canonical_entry_hash(input: &CanonicalEntryHashInput<'_>) -> String {
    canonical_entry_hash_for_version(ENTRY_HASH_VERSION, input)
        .expect("current entry hash version must be supported")
}

pub fn canonical_entry_hash_for_version(
    version: &str,
    input: &CanonicalEntryHashInput<'_>,
) -> Option<String> {
    match version {
        ENTRY_HASH_VERSION_V2 => Some(canonical_entry_hash_v2(input)),
        ENTRY_HASH_VERSION_V3 => Some(canonical_entry_hash_v3(input)),
        _ => None,
    }
}

fn canonical_entry_hash_v2(input: &CanonicalEntryHashInput<'_>) -> String {
    let mut bytes = Vec::with_capacity(input.content.len() + 512);
    bytes.extend_from_slice(ENTRY_HASH_VERSION_V2.as_bytes());
    bytes.push(b'\n');

    append_field(
        &mut bytes,
        "entry_id",
        input.entry_id.to_string().as_bytes(),
    );
    append_field(&mut bytes, "entry_type", input.entry_type.as_bytes());
    append_field(&mut bytes, "agent_id", input.agent_id.as_bytes());
    append_field(&mut bytes, "content", input.content);
    append_field(&mut bytes, "content_type", input.content_type.as_bytes());
    append_field(&mut bytes, "source_id", input.source_id.as_bytes());
    append_field(
        &mut bytes,
        "correlation_id",
        input.correlation_id.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "idempotency_key",
        input.idempotency_key.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "input_hash",
        input.input_hash.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "chain_position",
        input.chain_position.to_string().as_bytes(),
    );
    append_field(
        &mut bytes,
        "written_ts_ms",
        input.written_ts_ms.to_string().as_bytes(),
    );
    append_field(&mut bytes, "previous_hash", input.previous_hash.as_bytes());

    sha256_hex(&bytes)
}

fn canonical_entry_hash_v3(input: &CanonicalEntryHashInput<'_>) -> String {
    let proof_material_size = input.writer_signature.map_or(0, <[u8]>::len)
        + input.attestation_report.map_or(0, <[u8]>::len);
    let mut bytes = Vec::with_capacity(input.content.len() + proof_material_size + 768);
    bytes.extend_from_slice(ENTRY_HASH_VERSION_V3.as_bytes());
    bytes.push(b'\n');

    append_field(&mut bytes, "hash_version", ENTRY_HASH_VERSION_V3.as_bytes());
    append_field(
        &mut bytes,
        "entry_id",
        input.entry_id.to_string().as_bytes(),
    );
    append_field(&mut bytes, "entry_type", input.entry_type.as_bytes());
    append_field(&mut bytes, "agent_id", input.agent_id.as_bytes());
    append_field(&mut bytes, "content", input.content);
    append_field(&mut bytes, "content_type", input.content_type.as_bytes());
    append_field(&mut bytes, "source_id", input.source_id.as_bytes());
    append_field(
        &mut bytes,
        "correlation_id",
        input.correlation_id.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "idempotency_key",
        input.idempotency_key.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "input_hash",
        input.input_hash.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "writer_signature",
        input.writer_signature.unwrap_or_default(),
    );
    append_field(
        &mut bytes,
        "signer_key_reference",
        input.signer_key_reference.unwrap_or_default().as_bytes(),
    );
    append_field(
        &mut bytes,
        "attestation_report",
        input.attestation_report.unwrap_or_default(),
    );
    append_field(
        &mut bytes,
        "chain_position",
        input.chain_position.to_string().as_bytes(),
    );
    append_field(
        &mut bytes,
        "written_ts_ms",
        input.written_ts_ms.to_string().as_bytes(),
    );
    append_field(&mut bytes, "previous_hash", input.previous_hash.as_bytes());

    sha256_hex(&bytes)
}

fn append_field(bytes: &mut Vec<u8>, name: &str, value: &[u8]) {
    bytes.extend_from_slice(name.as_bytes());
    bytes.push(b':');
    bytes.extend_from_slice(value.len().to_string().as_bytes());
    bytes.push(b':');
    bytes.extend_from_slice(value);
    bytes.push(b'\n');
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input<'a>(
        entry_id: Uuid,
        previous_hash: &'a str,
        written_ts_ms: i64,
    ) -> CanonicalEntryHashInput<'a> {
        CanonicalEntryHashInput {
            entry_id,
            entry_type: "LEDGER_ENTRY_TYPE_ACTION_RECEIPT",
            agent_id: "agent-1",
            content: b"{\"ok\":true}",
            content_type: "application/json",
            source_id: "ARE-FOUNDATION-PROOF",
            correlation_id: Some("trace-1"),
            idempotency_key: Some("idem-1"),
            input_hash: Some("payload-sha256"),
            writer_signature: Some(b"writer-signature"),
            signer_key_reference: Some("spiffe://example.test/writer"),
            attestation_report: Some(b"attestation-report"),
            chain_position: 7,
            written_ts_ms,
            previous_hash,
        }
    }

    #[test]
    fn canonical_hash_is_deterministic_for_identical_input() {
        let entry_id = Uuid::new_v4();
        let first = canonical_entry_hash(&input(entry_id, "prev-hash", 1_700_000_000_000));
        for _ in 0..9 {
            let next = canonical_entry_hash(&input(entry_id, "prev-hash", 1_700_000_000_000));
            assert_eq!(first, next);
        }
    }

    #[test]
    fn canonical_hash_changes_when_timestamp_or_previous_hash_changes() {
        let entry_id = Uuid::new_v4();
        let baseline = canonical_entry_hash(&input(entry_id, "prev-hash", 1_700_000_000_000));
        let changed_ts = canonical_entry_hash(&input(entry_id, "prev-hash", 1_700_000_000_001));
        let changed_prev = canonical_entry_hash(&input(entry_id, "prev-hash-2", 1_700_000_000_000));
        assert_ne!(baseline, changed_ts);
        assert_ne!(baseline, changed_prev);
    }

    #[test]
    fn canonical_hash_commits_to_identity_position_and_correlation() {
        let entry_id = Uuid::new_v4();
        let baseline = canonical_entry_hash(&input(entry_id, "prev-hash", 1_700_000_000_000));

        let mut changed_correlation = input(entry_id, "prev-hash", 1_700_000_000_000);
        changed_correlation.correlation_id = Some("trace-2");

        let mut changed_position = input(entry_id, "prev-hash", 1_700_000_000_000);
        changed_position.chain_position += 1;

        let changed_entry_id =
            canonical_entry_hash(&input(Uuid::new_v4(), "prev-hash", 1_700_000_000_000));

        assert_ne!(baseline, canonical_entry_hash(&changed_correlation));
        assert_ne!(baseline, canonical_entry_hash(&changed_position));
        assert_ne!(baseline, changed_entry_id);
    }

    #[test]
    fn v3_hash_commits_to_signature_key_reference_and_attestation() {
        let entry_id = Uuid::new_v4();
        let baseline = canonical_entry_hash(&input(entry_id, "prev-hash", 1_700_000_000_000));

        let mut changed_signature = input(entry_id, "prev-hash", 1_700_000_000_000);
        changed_signature.writer_signature = Some(b"different-signature");

        let mut changed_key = input(entry_id, "prev-hash", 1_700_000_000_000);
        changed_key.signer_key_reference = Some("did:web:example.test:new-key");

        let mut changed_attestation = input(entry_id, "prev-hash", 1_700_000_000_000);
        changed_attestation.attestation_report = Some(b"different-attestation");

        assert_ne!(baseline, canonical_entry_hash(&changed_signature));
        assert_ne!(baseline, canonical_entry_hash(&changed_key));
        assert_ne!(baseline, canonical_entry_hash(&changed_attestation));
    }

    #[test]
    fn v2_hash_remains_available_for_existing_entries() {
        let entry_id = Uuid::new_v4();
        let baseline_input = input(entry_id, "prev-hash", 1_700_000_000_000);
        let v2 = canonical_entry_hash_for_version(ENTRY_HASH_VERSION_V2, &baseline_input)
            .expect("v2 must remain supported");

        let mut changed_proof = input(entry_id, "prev-hash", 1_700_000_000_000);
        changed_proof.writer_signature = Some(b"legacy-v2-did-not-bind-this-field");
        let compatible_v2 = canonical_entry_hash_for_version(ENTRY_HASH_VERSION_V2, &changed_proof)
            .expect("v2 must remain supported");

        assert_eq!(v2, compatible_v2);
        assert_ne!(v2, canonical_entry_hash(&baseline_input));
        assert!(canonical_entry_hash_for_version("unsupported", &baseline_input).is_none());
    }

    #[test]
    fn advisory_lock_key_is_deterministic() {
        let key1 = advisory_lock_key("cpex.policy.allow");
        let key2 = advisory_lock_key("cpex.policy.allow");
        assert_eq!(key1, key2);
    }

    #[test]
    fn advisory_lock_key_differs_for_different_types() {
        let keys: Vec<i64> = vec![
            advisory_lock_key("cpex.policy.allow"),
            advisory_lock_key("cpex.policy.deny"),
            advisory_lock_key("authbridge.token.exchanged"),
            advisory_lock_key("authbridge.tool.denied"),
            advisory_lock_key("openshell.http_activity"),
            advisory_lock_key("kagenti.tool.call"),
        ];
        for i in 0..keys.len() {
            for j in (i + 1)..keys.len() {
                assert_ne!(keys[i], keys[j], "collision between index {i} and {j}");
            }
        }
    }
}
