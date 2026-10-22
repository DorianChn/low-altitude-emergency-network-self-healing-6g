"""Reconcile Phase 8 replication metadata and regenerate summary/plots.

The replication run itself completed all 80 seeds. Its first aggregation call
revealed that the raw file used `experiment_plan_sha256`, while the shared
summary helper expects the compatible alias `plan_sha256`. This finalizer adds
only that top-level alias, proves the per-seed records hash is unchanged, and
then reruns the frozen analysis.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_phase8_replication as replication  # noqa: E402
from lowalt6g import phase8_experiments as p8  # noqa: E402
from lowalt6g.phase8_charts import write_phase8_charts  # noqa: E402


RAW_PATH = ROOT / "results/phase8_replication_raw.json"
SUMMARY_PATH = ROOT / "results/phase8_replication_summary.json"
AUDIT_PATH = ROOT / "results/phase8_replication_postprocess_audit.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_records_sha256(records: object) -> str:
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(encoded)


def main() -> int:
    protocol = replication._verify_protocol()
    raw_bytes_before = RAW_PATH.read_bytes()
    raw = json.loads(raw_bytes_before)
    if raw.get("status") != "complete" or len(raw.get("records", [])) != 80:
        raise ValueError("replication raw data is not a complete 80-seed cohort")
    if raw.get("actual_policy_run_count") != protocol["policy_runs_expected"]:
        raise ValueError("replication raw policy-run count does not match the frozen protocol")
    if raw.get("protocol_sha256") != replication.sha256_file(replication.PROTOCOL_PATH):
        raise ValueError("replication raw data references a different protocol")
    if raw.get("experiment_plan_sha256") != protocol["experiment_plan_sha256"]:
        raise ValueError("replication raw data references a different experiment plan")
    if raw.get("plan_sha256") not in (None, raw["experiment_plan_sha256"]):
        raise ValueError("unexpected conflicting plan hash alias")

    records_sha_before = _canonical_records_sha256(raw["records"])
    raw["plan_sha256"] = raw["experiment_plan_sha256"]
    replication._atomic_json(RAW_PATH, raw)
    raw_bytes_after = RAW_PATH.read_bytes()
    reloaded = json.loads(raw_bytes_after)
    records_sha_after = _canonical_records_sha256(reloaded["records"])
    if records_sha_before != records_sha_after:
        raise AssertionError("per-seed records changed while adding the metadata alias")

    original_paired_test = p8._paired_test
    try:
        p8._paired_test = replication.vectorized_paired_test
        summary = p8.summarize_raw(reloaded)
    finally:
        p8._paired_test = original_paired_test
    summary["cohort_note"] = "independent 20-seed-per-scenario replication; not pooled with initial 10-seed Phase 8 batch"
    summary["exact_sign_flip_backend"] = "NumPy vectorized exhaustive enumeration of all 2^20 sign assignments"
    summary["protocol_sha256"] = reloaded["protocol_sha256"]
    replication._atomic_json(SUMMARY_PATH, summary)
    chart_paths = write_phase8_charts(RAW_PATH, ROOT / "plots/phase8_replication")

    audit = {
        "schema_version": "1.0",
        "status": "PASS",
        "reason": "the simulation completed; only a summary-required top-level hash alias was absent",
        "field_added": "plan_sha256",
        "value_source": "experiment_plan_sha256 already present in the complete raw file",
        "per_seed_records_modified": False,
        "per_seed_records_canonical_sha256_before": records_sha_before,
        "per_seed_records_canonical_sha256_after": records_sha_after,
        "raw_file_sha256_before_metadata_alias": _sha256(raw_bytes_before),
        "raw_file_sha256_after_metadata_alias": _sha256(raw_bytes_after),
        "summary_file_sha256": replication.sha256_file(SUMMARY_PATH),
        "replication_protocol_sha256": replication.sha256_file(replication.PROTOCOL_PATH),
        "finalizer_code_sha256": replication.sha256_file(Path(__file__).resolve()),
        "policy_runs": reloaded["actual_policy_run_count"],
        "seed_rows": len(reloaded["records"]),
        "charts": [str(path.relative_to(ROOT)) for path in chart_paths],
    }
    replication._atomic_json(AUDIT_PATH, audit)
    print(json.dumps({"summary": str(SUMMARY_PATH), "audit": audit, "charts": [str(path) for path in chart_paths]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
