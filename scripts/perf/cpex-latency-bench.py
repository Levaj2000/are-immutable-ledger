#!/usr/bin/env python3
"""CPEX/AuthBridge latency benchmark for the immutable ledger.

Measures IssueReceipt, VerifyProof, and round-trip latency under
CPEX-shaped workloads via the REST API.

Usage:
    python3 scripts/perf/cpex-latency-bench.py [--endpoint http://localhost:18099] [--profile quick|full]
"""

import argparse
import json
import time
import hashlib
import statistics
import concurrent.futures
import urllib.request
import urllib.error
import sys
import uuid

PROFILES = {
    "quick": {"duration": 10, "ramp_rates": [20, 50, 100]},
    "full":  {"duration": 15, "ramp_rates": [20, 50, 100, 200, 300]},
}

CPEX_CONTENT = json.dumps({
    "class_uid": 6003, "activity_id": 99, "action_id": 3,
    "tool": {"name": "get_compensation"},
    "ai_agent": {"uid": "agent-7"},
})

AUTHBRIDGE_CONTENT = json.dumps({
    "tool": "get_compensation", "audience": "workday-api",
    "scopes": ["read_compensation"], "ttl_seconds": 300,
})

ENTRY_TYPES = [
    ("cpex.policy.allow", CPEX_CONTENT, "praxis-gateway"),
    ("cpex.policy.deny", CPEX_CONTENT, "praxis-gateway"),
    ("cpex.guardrail.pii_scan", json.dumps({"scan_result": "clean"}), "praxis-gateway"),
    ("authbridge.token.exchanged", AUTHBRIDGE_CONTENT, "authbridge-sidecar"),
]


def post_json(endpoint, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{endpoint}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def issue_receipt(endpoint, entry_type, content, source_id, correlation_id):
    body = {
        "entry_type": entry_type,
        "agent_id": "perf-agent",
        "content": content,
        "source_id": source_id,
        "correlation_id": correlation_id,
        "input_hash": hashlib.sha256(content.encode()).hexdigest(),
        "idempotency_key": f"perf-{entry_type}-{uuid.uuid4()}",
    }
    start = time.monotonic()
    resp = post_json(endpoint, "/api/receipts", body)
    elapsed_ms = (time.monotonic() - start) * 1000
    return resp, elapsed_ms


def verify_proof(endpoint, entry_hash, entry_type):
    start = time.monotonic()
    req = urllib.request.Request(
        f"{endpoint}/api/receipts/verify?hash={entry_hash}&type={entry_type}",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    elapsed_ms = (time.monotonic() - start) * 1000
    return result, elapsed_ms


def percentile(data, p):
    if not data:
        return 0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def print_stats(label, latencies):
    if not latencies:
        print(f"  {label}: no data")
        return
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    avg = statistics.mean(latencies)
    print(f"  {label}: p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms  avg={avg:.1f}ms  n={len(latencies)}")
    return {"p50": round(p50, 1), "p95": round(p95, 1), "p99": round(p99, 1),
            "avg": round(avg, 1), "n": len(latencies)}


def run_scenario_a(endpoint, rate, duration):
    """Async audit baseline — 4 parallel chains."""
    latencies = []
    errors = 0
    end_time = time.monotonic() + duration
    interval = 1.0 / rate

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(rate, 50)) as pool:
        futures = []
        while time.monotonic() < end_time:
            et, content, src = ENTRY_TYPES[len(futures) % len(ENTRY_TYPES)]
            corr = f"perf-a-{uuid.uuid4().hex[:8]}"
            futures.append(pool.submit(issue_receipt, endpoint, et, content, src, corr))
            time.sleep(interval)

        for f in concurrent.futures.as_completed(futures):
            try:
                _, ms = f.result()
                latencies.append(ms)
            except Exception:
                errors += 1

    return latencies, errors


def run_scenario_b(endpoint, rate, duration):
    """Sync receipt round-trip — IssueReceipt then VerifyProof."""
    receipt_latencies = []
    verify_latencies = []
    roundtrip_latencies = []
    errors = 0
    end_time = time.monotonic() + duration
    interval = 1.0 / rate

    def do_roundtrip():
        et, content, src = ENTRY_TYPES[0]
        corr = f"perf-b-{uuid.uuid4().hex[:8]}"
        rt_start = time.monotonic()
        resp, issue_ms = issue_receipt(endpoint, et, content, src, corr)
        entry_hash = resp.get("entry_hash")
        if entry_hash:
            _, verify_ms = verify_proof(endpoint, entry_hash, et)
        else:
            verify_ms = 0
        rt_ms = (time.monotonic() - rt_start) * 1000
        return issue_ms, verify_ms, rt_ms

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(rate, 50)) as pool:
        futures = []
        while time.monotonic() < end_time:
            futures.append(pool.submit(do_roundtrip))
            time.sleep(interval)

        for f in concurrent.futures.as_completed(futures):
            try:
                issue_ms, verify_ms, rt_ms = f.result()
                receipt_latencies.append(issue_ms)
                verify_latencies.append(verify_ms)
                roundtrip_latencies.append(rt_ms)
            except Exception:
                errors += 1

    return receipt_latencies, verify_latencies, roundtrip_latencies, errors


def run_scenario_c(endpoint, rate, duration):
    """Mixed read/write — concurrent writers + readers."""
    write_latencies = []
    read_latencies = []
    errors = 0
    last_hash = {"h": None, "t": None}
    end_time = time.monotonic() + duration
    interval = 1.0 / rate

    def do_write():
        et, content, src = ENTRY_TYPES[2]
        corr = f"perf-c-{uuid.uuid4().hex[:8]}"
        resp, ms = issue_receipt(endpoint, et, content, src, corr)
        last_hash["h"] = resp.get("entry_hash")
        last_hash["t"] = et
        return "w", ms

    def do_read():
        h, t = last_hash["h"], last_hash["t"]
        if not h:
            return "r", 0
        _, ms = verify_proof(endpoint, h, t)
        return "r", ms

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(rate, 50)) as pool:
        futures = []
        i = 0
        while time.monotonic() < end_time:
            if i % 2 == 0:
                futures.append(pool.submit(do_write))
            else:
                futures.append(pool.submit(do_read))
            i += 1
            time.sleep(interval)

        for f in concurrent.futures.as_completed(futures):
            try:
                kind, ms = f.result()
                if kind == "w":
                    write_latencies.append(ms)
                elif ms > 0:
                    read_latencies.append(ms)
            except Exception:
                errors += 1

    return write_latencies, read_latencies, errors


def run_scenario_d(endpoint, rate, duration):
    """Single-chain hot path — all writes to one entry_type."""
    latencies = []
    errors = 0
    end_time = time.monotonic() + duration
    interval = 1.0 / rate
    et = "cpex.policy.allow.hot"

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(rate, 50)) as pool:
        futures = []
        while time.monotonic() < end_time:
            corr = f"perf-d-{uuid.uuid4().hex[:8]}"
            futures.append(pool.submit(issue_receipt, endpoint, et, CPEX_CONTENT, "praxis-gateway", corr))
            time.sleep(interval)

        for f in concurrent.futures.as_completed(futures):
            try:
                _, ms = f.result()
                latencies.append(ms)
            except Exception:
                errors += 1

    return latencies, errors


def main():
    parser = argparse.ArgumentParser(description="CPEX latency benchmark")
    parser.add_argument("--endpoint", default="http://localhost:18099")
    parser.add_argument("--profile", default="quick", choices=["quick", "full"])
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    results = {}

    print(f"\n{'='*60}")
    print(f"  CPEX/AuthBridge Latency Benchmark")
    print(f"  Endpoint: {args.endpoint}")
    print(f"  Profile: {args.profile} (duration={profile['duration']}s per rate)")
    print(f"  Rates: {profile['ramp_rates']} req/s")
    print(f"{'='*60}\n")

    # Scenario A: Async audit baseline
    print("Scenario A: Async Audit Baseline (4 parallel chains)")
    print("-" * 50)
    results["A"] = {}
    for rate in profile["ramp_rates"]:
        print(f"  Rate: {rate} req/s ... ", end="", flush=True)
        latencies, errors = run_scenario_a(args.endpoint, rate, profile["duration"])
        throughput = len(latencies) / profile["duration"]
        results["A"][rate] = print_stats(f"{rate} req/s", latencies)
        if results["A"][rate]:
            results["A"][rate]["errors"] = errors
            results["A"][rate]["throughput"] = round(throughput, 1)
        print(f"    throughput={throughput:.0f}/s  errors={errors}")

    # Scenario B: Sync receipt round-trip
    print(f"\nScenario B: Sync Receipt Round-Trip (IssueReceipt + VerifyProof)")
    print("-" * 50)
    results["B"] = {}
    for rate in profile["ramp_rates"]:
        print(f"  Rate: {rate} req/s ... ", end="", flush=True)
        r_lat, v_lat, rt_lat, errors = run_scenario_b(args.endpoint, rate, profile["duration"])
        results["B"][rate] = {
            "receipt": print_stats("IssueReceipt", r_lat),
            "verify": print_stats("VerifyProof", v_lat),
            "roundtrip": print_stats("Round-trip", rt_lat),
            "errors": errors,
        }
        print(f"    errors={errors}")

    # Scenario C: Mixed read/write
    print(f"\nScenario C: Mixed Read/Write Contention")
    print("-" * 50)
    results["C"] = {}
    for rate in profile["ramp_rates"]:
        print(f"  Rate: {rate} req/s (50/50 read/write) ... ", end="", flush=True)
        w_lat, r_lat, errors = run_scenario_c(args.endpoint, rate, profile["duration"])
        results["C"][rate] = {
            "write": print_stats("IssueReceipt", w_lat),
            "read": print_stats("VerifyProof", r_lat),
            "errors": errors,
        }
        print(f"    errors={errors}")

    # Scenario D: Single-chain hot path
    print(f"\nScenario D: Single-Chain Hot Path (advisory lock contention)")
    print("-" * 50)
    results["D"] = {}
    for rate in profile["ramp_rates"]:
        print(f"  Rate: {rate} req/s ... ", end="", flush=True)
        latencies, errors = run_scenario_d(args.endpoint, rate, profile["duration"])
        throughput = len(latencies) / profile["duration"]
        results["D"][rate] = print_stats(f"{rate} req/s", latencies)
        if results["D"][rate]:
            results["D"][rate]["errors"] = errors
            results["D"][rate]["throughput"] = round(throughput, 1)
        print(f"    throughput={throughput:.0f}/s  errors={errors}")

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")

    with open("scripts/perf/cpex-latency-results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Raw results saved to scripts/perf/cpex-latency-results.json")
    print()


if __name__ == "__main__":
    main()
