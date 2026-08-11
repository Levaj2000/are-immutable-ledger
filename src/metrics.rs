//! Prometheus metrics for the immutable ledger service.

use lazy_static::lazy_static;
use prometheus::{
    register_counter, register_counter_vec, register_histogram, Counter, CounterVec, Encoder,
    Histogram, TextEncoder,
};

lazy_static! {
    pub static ref LEDGER_WRITE_TOTAL: CounterVec = register_counter_vec!(
        "are_ledger_write_total",
        "Ledger write attempts by outcome",
        &["result"]
    )
    .expect("register are_ledger_write_total");
    pub static ref LEDGER_CHAIN_VERIFY_FAILURE_TOTAL: Counter = register_counter!(
        "are_ledger_chain_verify_failure_total",
        "Chain verification detected invalid link or hash"
    )
    .expect("register are_ledger_chain_verify_failure_total");
    pub static ref OUTBOX_PUBLISH_FAILURE_TOTAL: Counter = register_counter!(
        "are_outbox_publish_failure_total",
        "Outbox HTTP publish failures (record stays pending)"
    )
    .expect("register are_outbox_publish_failure_total");
    pub static ref WRITE_DURATION: Histogram = register_histogram!(
        "are_ledger_write_duration_seconds",
        "Time to complete a WriteEntry or IssueReceipt",
        vec![0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
    )
    .expect("register are_ledger_write_duration_seconds");
    pub static ref VERIFY_DURATION: Histogram = register_histogram!(
        "are_ledger_verify_duration_seconds",
        "Time to complete a VerifyProof or VerifyEntry",
        vec![0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1]
    )
    .expect("register are_ledger_verify_duration_seconds");
    pub static ref CHAIN_INTEGRITY_RETRIES: Histogram = register_histogram!(
        "are_ledger_chain_integrity_retries",
        "Retry attempts per write due to chain contention",
        vec![0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    )
    .expect("register are_ledger_chain_integrity_retries");
}

pub fn inc_write(result: &'static str) {
    LEDGER_WRITE_TOTAL.with_label_values(&[result]).inc();
}

pub fn encode_prometheus() -> Vec<u8> {
    let enc = TextEncoder::new();
    let mut buf = Vec::new();
    let _ = enc.encode(&prometheus::gather(), &mut buf);
    buf
}
