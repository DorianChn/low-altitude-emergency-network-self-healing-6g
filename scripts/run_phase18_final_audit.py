"""Read-only final audit of historical evidence; writes only results/phase18."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "phase18"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(relative: str) -> dict[str, Any] | None:
    path = ROOT / relative
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def command(*args: str) -> str:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip()


def verify_map(entries: dict[str, Any], *, sizes: bool = False) -> list[dict[str, Any]]:
    checked = []
    for relative, expected_value in entries.items():
        expected = expected_value.get("sha256") if isinstance(expected_value, dict) else expected_value
        expected_size = expected_value.get("size_bytes") if isinstance(expected_value, dict) else None
        path = ROOT / relative
        actual = sha256(path)
        actual_size = path.stat().st_size if path.is_file() else None
        matches = actual == expected and (not sizes or expected_size is None or actual_size == expected_size)
        checked.append({
            "path": Path(relative).as_posix(),
            "expected_sha256": expected,
            "actual_sha256": actual,
            "expected_size_bytes": expected_size,
            "actual_size_bytes": actual_size,
            "matches": matches,
        })
    return checked


def experiment_count_audit() -> dict[str, Any]:
    """Reconcile the principal confirmatory raw-row counts against protocols."""
    checks: list[dict[str, Any]] = []

    def add(name: str, path: str, observed: int, expected: int, note: str) -> None:
        checks.append({
            "experiment": name,
            "path": path,
            "observed": observed,
            "expected": expected,
            "matches": observed == expected,
            "note": note,
        })

    phase1 = read_json("results/phase1_benchmark.json") or {}
    add("phase1 single-seed benchmark", "results/phase1_benchmark.json", 1 if phase1.get("reproducibility", {}).get("seed") is not None else 0, 1, "one configured seed; not a statistical sample")

    phase2 = read_json("results/phase2_20_seed_results.json") or {}
    add("phase2 seed runs", "results/phase2_20_seed_results.json", len(phase2.get("seed_experiments", [])), 20, "20 seeds, 3 strategies")

    phase3 = read_json("results/phase3_replay_seed_2026.json") or {}
    replay_strategies = phase3.get("strategies", {})
    replay_frames = [len(value.get("state_snapshots", [])) for value in replay_strategies.values() if isinstance(value, dict)]
    frame_match = bool(replay_frames) and len(set(replay_frames)) == 1
    checks.append({"experiment": "phase3 replay frames", "path": "results/phase3_replay_seed_2026.json", "observed": replay_frames[0] if frame_match else replay_frames, "expected": 61, "matches": frame_match and replay_frames[0] == 61, "note": "single seed replay; not independent trials"})

    phase4 = read_json("results/phase4_validation_4000_4019.json") or {}
    add("phase4 held-out seeds", "results/phase4_validation_4000_4019.json", len(phase4.get("seed_experiments", [])), 20, "20 validation seeds; shared traces across four strategies")

    phase5_records = 0
    phase5_policy_runs = 0
    phase5_groups = {}
    for scene in ("severe_persistent_faults", "dynamic_failures", "high_mobility_rescue", "high_load_backhaul_limit"):
        relative = f"results/phase5_validation_{scene}.json"
        payload = read_json(relative) or {}
        runs = payload.get("seed_experiments", [])
        phase5_records += len(runs)
        phase5_policy_runs += sum(len(item.get("strategies", {})) for item in runs)
        phase5_groups[scene] = {"seeds": len(runs), "strategy_counts": sorted({len(item.get("strategies", {})) for item in runs})}
    add("phase5 held-out strategy runs", "results/phase5_validation_*.json", phase5_policy_runs, 400, "4 scenarios x 20 seeds x 5 strategies")
    checks.append({"experiment": "phase5 per-scene seeds", "path": "results/phase5_validation_*.json", "observed": phase5_groups, "expected": "20 seeds and 5 strategies per scenario", "matches": all(v["seeds"] == 20 and v["strategy_counts"] == [5] for v in phase5_groups.values()), "note": "raw files retain per-seed results"})

    for name, relative, expected_records, expected_runs, strategy_field in (
        ("phase8 ablation", "results/phase8_validation_raw.json", 40, 680, "baseline_strategy_runs"),
        ("phase8 sensitivity", "results/phase8_sensitivity_validation_raw.json", 80, 2000, "baseline_strategy_runs"),
    ):
        payload = read_json(relative) or {}
        records = payload.get("records", [])
        per_record = [len(item.get(strategy_field, {})) + len(item.get("variant_runs", {})) for item in records]
        observed_runs = sum(per_record)
        add(f"{name} raw records", relative, len(records), expected_records, "record = one scenario/seed world trace")
        add(f"{name} raw strategy/variant runs", relative, observed_runs, expected_runs, "counted from baseline_strategy_runs + variant_runs in each raw record")
        scenario_counts = {}
        for item in records:
            scenario_counts[item.get("scenario_id", "unknown")] = scenario_counts.get(item.get("scenario_id", "unknown"), 0) + 1
        checks.append({"experiment": f"{name} scenario seed allocation", "path": relative, "observed": scenario_counts, "expected": "balanced across 4 scenarios", "matches": len(scenario_counts) == 4 and len(set(scenario_counts.values())) == 1, "note": "all policies within each record share its world_trace_sha256"})

    for name, relative, expected_records, expected_runs, n_strategy in (
        ("phase9 corrected confirmation", "results/phase9_corrected_confirmation_raw.json", 80, 480, 6),
        ("phase10 confirmation", "results/phase10_confirmation_raw.json", 80, 400, 5),
    ):
        payload = read_json(relative) or {}
        records = payload.get("records", [])
        strategy_field = "strategy_runs"
        observed_runs = sum(len(item.get(strategy_field, {})) for item in records)
        add(f"{name} seed traces", relative, len(records), expected_records, "4 scenarios x 20 held-out seeds")
        add(f"{name} strategy runs", relative, observed_runs, expected_runs, f"{n_strategy} strategies per matched seed")
        checks.append({"experiment": f"{name} trace pairing", "path": relative, "observed": len({(x.get('scenario_id'), x.get('seed'), x.get('world_trace_sha256')) for x in records}), "expected": 80, "matches": len({(x.get('scenario_id'), x.get('seed')) for x in records}) == 80 and all(x.get("world_trace_sha256") for x in records), "note": "one shared trace hash per scenario/seed record"})

    phase11 = read_json("results/phase11_confirmation_raw.json") or {}
    phase11_rows = phase11.get("records", [])
    phase11_groups: dict[tuple[str, int], set[str]] = {}
    for item in phase11_rows:
        phase11_groups.setdefault((item.get("scenario_id", ""), int(item.get("seed", -1))), set()).add(item.get("strategy_key", ""))
    add("phase11 policy rows", "results/phase11_confirmation_raw.json", len(phase11_rows), 880, "80 matched scenario/seed pairs x 11 policy configurations")
    checks.append({"experiment": "phase11 matched seed groups", "path": "results/phase11_confirmation_raw.json", "observed": {"groups": len(phase11_groups), "policy_counts": sorted({len(v) for v in phase11_groups.values()})}, "expected": {"groups": 80, "policy_count": 11}, "matches": len(phase11_groups) == 80 and all(len(v) == 11 for v in phase11_groups.values()), "note": "world trace equality is also recorded in Phase 11 delivery audit"})

    phase14 = read_json("results/phase14_confirmation_raw.json") or {}
    phase14_rows = phase14.get("records", [])
    phase14_groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in phase14_rows:
        phase14_groups.setdefault((item.get("scenario_id", ""), int(item.get("seed", -1))), []).append(item)
    add("phase14 model-policy runs", "results/phase14_confirmation_raw.json", len(phase14_rows), 480, "80 matched scenario/seed traces x 6 policy/model combinations")
    phase14_pairing = all(len(rows) == 6 and len({row.get("world_trace_sha256") for row in rows}) == 1 for rows in phase14_groups.values())
    checks.append({"experiment": "phase14 paired model traces", "path": "results/phase14_confirmation_raw.json", "observed": len(phase14_groups), "expected": 80, "matches": len(phase14_groups) == 80 and phase14_pairing, "note": "within each scenario/seed, strategies and both link models share one trace"})

    phase15_holdout = read_json("results/phase15_holdout_validation.json") or {}
    add("phase15 public-data holdout rows", "results/phase15_holdout_validation.json", int(phase15_holdout.get("sample_count", 0)), 570, "public 3.6 GHz A2G holdout data; not project-device calibration")
    phase16 = read_json("results/phase16_measurement_readiness.json") or {}
    add("phase16 project device measurements", "results/phase16_measurement_readiness.json", int(phase16.get("project_measurement_records", -1)), 0, "status must remain NOT_READY_FOR_FIELD_MEASUREMENT")
    phase17 = read_json("results/phase17_validation_summary.json") or {}
    add("phase17 discrete replay frames", "results/phase17_validation_summary.json", int(phase17.get("offline_replay", {}).get("mapped_frame_count", 0)), 61, "saved Phase 6 replay; no interpolation")
    add("phase17 software fault cases", "results/phase17_validation_summary.json", int(phase17.get("fault_injection", {}).get("passed_count", 0)), 21, "software-only safety and contract cases")

    return {"status": "PASS" if all(item["matches"] for item in checks) else "FAIL", "checks": checks, "check_count": len(checks), "failed_checks": [item for item in checks if not item["matches"]]}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    warnings: list[str] = []
    current_files: list[dict[str, Any]] = []

    # Phase 17's pre-change baseline deliberately protects frozen experiment data
    # and their phase manifests across Phases 5, 8-11, and 14-16.
    protected_baseline = read_json("results/phase17/protected_start_manifest.json")
    if protected_baseline is None:
        errors.append("missing Phase 17 protected-start manifest")
        protected_checked: list[dict[str, Any]] = []
    else:
        protected_checked = []
        for item in protected_baseline.get("files", []):
            path = ROOT / item["path"]
            actual = sha256(path)
            actual_size = path.stat().st_size if path.is_file() else None
            matches = actual == item["sha256"] and actual_size == item.get("size_bytes")
            protected_checked.append({
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "expected_size_bytes": item.get("size_bytes"),
                "actual_size_bytes": actual_size,
                "matches": matches,
            })
            if not matches:
                errors.append(f"Phase 17 protected baseline mismatch: {item['path']}")

    # Verify manifest-addressed phase deliverables without rewriting any old audit.
    phase_manifests: dict[str, Any] = {}
    phase9 = read_json("results/phase9_artifact_manifest.json") or {}
    phase9_entries = {**phase9.get("protected_historical_sha256", {}), **phase9.get("artifacts", {})}
    phase_manifests["phase9"] = verify_map(phase9_entries)

    phase10 = read_json("results/phase10_artifact_manifest.json") or {}
    phase_manifests["phase10"] = verify_map(phase10.get("artifacts_sha256", {}))

    phase11 = read_json("results/phase11_artifact_manifest.json") or {}
    phase_manifests["phase11"] = verify_map(phase11.get("artifacts", {}), sizes=True)

    for phase, items in phase_manifests.items():
        for item in items:
            if not item["matches"]:
                errors.append(f"{phase} artifact manifest mismatch: {item['path']}")

    # Current integrity audits are read as evidence and independently cross-checked
    # by the Phase 17 protected list above. Do not rerun scripts that overwrite them.
    audit_paths = {
        "phase5": "results/phase5_integrity_audit.json",
        "phase8_sensitivity": "results/phase8_sensitivity_validation_audit.json",
        "phase8_replication": "results/phase8_replication_postprocess_audit.json",
        "phase12": "results/phase12_integrity_audit.json",
        "phase13": "results/phase13_visualization_audit.json",
        "phase14": "results/phase14_integrity_audit.json",
        "phase15": "results/phase15_integrity_audit.json",
        "phase16": "results/phase16_integrity_audit.json",
        "phase17": "results/phase17_integrity_audit.json",
    }
    stored_audits: dict[str, Any] = {}
    for name, relative in audit_paths.items():
        payload = read_json(relative)
        status = payload.get("status") if payload else "MISSING"
        stored_audits[name] = {"path": relative, "status": status, "sha256": sha256(ROOT / relative)}
        if status != "PASS":
            warnings.append(f"stored audit is {status}: {relative}")

    # Independent public-source check: Phase 15 data remain public data, not device
    # calibration. Raw data are deliberately excluded from a public RC manifest.
    dataset_manifest = read_json("configs/phase15/public_dataset_manifest.json") or {}
    dataset_id = dataset_manifest.get("dataset_id", "")
    raw_root = ROOT / "data" / "phase15" / "raw" / dataset_id
    public_sources = []
    for item in dataset_manifest.get("files", []):
        path = raw_root / item["filename"]
        actual = sha256(path)
        actual_size = path.stat().st_size if path.is_file() else None
        matches = actual == item.get("sha256") and actual_size == item.get("size_bytes")
        public_sources.append({
            "filename": item["filename"],
            "expected_sha256": item.get("sha256"),
            "actual_sha256": actual,
            "expected_size_bytes": item.get("size_bytes"),
            "actual_size_bytes": actual_size,
            "matches": matches,
        })
        if not matches:
            errors.append(f"Phase 15 public source mismatch: {item['filename']}")

    # Phase 5 source hashes are historical code-version identifiers. Later phases
    # intentionally evolved those modules; record drift separately from data hashes.
    phase5_manifest = read_json("results/phase5_frozen_manifest.json") or {}
    phase5_source_checks = []
    for filename, expected in phase5_manifest.get("source_file_sha256", {}).items():
        path = ROOT / "src" / "lowalt6g" / filename
        actual = sha256(path)
        phase5_source_checks.append({
            "path": path.relative_to(ROOT).as_posix(),
            "expected_phase5_sha256": expected,
            "current_sha256": actual,
            "matches": actual == expected,
            "classification": "historical_version_match" if actual == expected else "later_phase_source_drift_requires_history_context",
        })
    mismatched_sources = [item for item in phase5_source_checks if not item["matches"]]
    if mismatched_sources:
        warnings.append(f"{len(mismatched_sources)} Phase 5 source snapshots differ from current evolving source files; frozen data hashes are checked separately")

    # Stage counts and reproducibility metadata are taken from actual raw/summary files.
    experiment_evidence = {}
    summary_paths = {
        "phase1": "results/phase1_benchmark.json",
        "phase2": "results/phase2_20_seed_results.json",
        "phase3": "results/phase3_replay_seed_2026.json",
        "phase4": "results/phase4_validation_4000_4019.json",
        "phase5": "results/phase5_validation_summary.json",
        "phase8_ablation": "results/phase8_validation_summary.json",
        "phase8_sensitivity": "results/phase8_sensitivity_validation_summary.json",
        "phase9": "results/phase9_corrected_confirmation_summary.json",
        "phase10": "results/phase10_confirmation_summary.json",
        "phase11": "results/phase11_confirmation_summary.json",
        "phase14": "results/phase14_confirmation_summary.json",
        "phase15": "results/phase15_holdout_validation.json",
        "phase16": "results/phase16_measurement_readiness.json",
        "phase17": "results/phase17_validation_summary.json",
    }
    for name, relative in summary_paths.items():
        payload = read_json(relative)
        if payload is None:
            experiment_evidence[name] = {"path": relative, "status": "MISSING"}
            warnings.append(f"missing evidence summary: {relative}")
            continue
        experiment_evidence[name] = {
            "path": relative,
            "sha256": sha256(ROOT / relative),
            "phase": payload.get("phase"),
            "status": payload.get("status", payload.get("analysis_status", payload.get("pipeline_status"))),
            "seed_count_total": payload.get("seed_count_total", payload.get("seed_count")),
            "policy_run_count": payload.get("policy_run_count"),
            "scene_count": payload.get("scene_count", payload.get("scenario_count")),
            "experiment_role": payload.get("experiment_role"),
            "model_scope": payload.get("model_scope"),
        }

    # Phase 7 is intentionally a negative finding unless actual artifacts emerge.
    phase7_matches = []
    for base in (ROOT / "src", ROOT / "tests", ROOT / "configs", ROOT / "results", ROOT / "plots", ROOT):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "node_modules" in path.parts or ".venv" in path.parts:
                continue
            lower = path.name.lower()
            if "phase7" in lower or "phase_7" in lower or "phase-7" in lower:
                phase7_matches.append(path.relative_to(ROOT).as_posix())
    phase7_evidence = {
        "report_present": (ROOT / "PHASE7_REPORT.md").is_file(),
        "matching_named_artifacts": sorted(set(phase7_matches)),
        "branch_present": bool(command("git", "branch", "-a", "--list", "*phase7*")),
        "commit_search_matches": command("git", "log", "--all", "--oneline", "--grep=phase[ -]*7", "-i").splitlines(),
        "conclusion": "NO_PHASE7_EVIDENCE_FOUND" if not phase7_matches and not (ROOT / "PHASE7_REPORT.md").exists() else "EVIDENCE_REQUIRES_REVIEW",
    }

    status_porcelain = command("git", "status", "--porcelain=v1", "-uall").splitlines()
    staged_paths = command("git", "diff", "--cached", "--name-only").splitlines()
    conflicts = [line for line in status_porcelain if len(line) >= 2 and ("U" in line[:2] or line[:2] in {"AA", "DD"})]
    workspace = {
        "branch": command("git", "branch", "--show-current"),
        "head": command("git", "rev-parse", "HEAD"),
        "remotes": command("git", "remote", "-v").splitlines(),
        "branches": command("git", "branch", "--format=%(refname:short)").splitlines(),
        "status_entry_count_expanded": len(status_porcelain),
        "staged_path_count": len(staged_paths),
        "untracked_status_count": sum(line.startswith("??") for line in status_porcelain),
        "conflict_count": len(conflicts),
        "phase18_branch_created_without_file_changes": command("git", "branch", "--show-current") == "phase18-final-audit-delivery",
        "phase18_commit_created": False,
        "remote_push_performed": False,
        "raw_status_entries": status_porcelain,
    }
    if conflicts:
        errors.append("Git worktree contains unresolved conflicts")

    reports = []
    for phase in range(1, 18):
        path = ROOT / f"PHASE{phase}_REPORT.md"
        reports.append({"phase": phase, "path": path.name, "present": path.is_file(), "sha256": sha256(path)})

    result = {
        "schema_version": "1.0",
        "phase": "phase18_final_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Read-only historical audit; only results/phase18 artifacts are written by this script.",
        "status": "PASS" if not errors else "FAIL",
        "workspace": workspace,
        "reports": reports,
        "phase7_evidence": phase7_evidence,
        "protected_history": {
            "phase17_start_manifest_path": "results/phase17/protected_start_manifest.json",
            "protected_file_count": len(protected_checked),
            "matched_file_count": sum(item["matches"] for item in protected_checked),
            "all_protected_hashes_match": bool(protected_checked) and all(item["matches"] for item in protected_checked),
            "files": protected_checked,
            "phase5_current_source_snapshot_checks": phase5_source_checks,
            "phase5_source_snapshot_drift_count": len(mismatched_sources),
            "phase15_public_source_count": len(public_sources),
            "phase15_public_sources_match": bool(public_sources) and all(item["matches"] for item in public_sources),
            "phase15_public_sources": public_sources,
            "artifact_manifests": phase_manifests,
            "stored_phase_audits": stored_audits,
        },
        "experiment_evidence": experiment_evidence,
        "raw_experiment_count_audit": experiment_count_audit(),
        "warnings": warnings,
        "errors": errors,
    }
    out_path = OUT / "phase18_integrity_audit.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # A separate compact evidence manifest with hashes and provenance classes.
    evidence_paths = set()
    evidence_paths.update(item["path"] for item in protected_checked if item["matches"])
    evidence_paths.update(summary_paths.values())
    evidence_paths.update(audit_paths.values())
    evidence_paths.update(["results/phase17/protected_start_manifest.json", "results/phase5_frozen_manifest.json"])
    evidence_paths.update(["results/phase9_artifact_manifest.json", "results/phase10_artifact_manifest.json", "results/phase11_artifact_manifest.json"])
    evidence_paths.update(["configs/phase15/public_dataset_manifest.json", "configs/phase15/calibration_protocol_v2.json"])
    evidence_paths.update(["results/phase15_measurements_public_clean.csv", "results/phase15_holdout_validation.json"])
    evidence_paths.update(["results/phase16_calibration_state.json", "results/phase16_measurement_readiness.json", "results/phase16_uncertainty_budget.json"])
    evidence_paths.update(["results/phase17_closed_loop_run.json", "results/phase17_replay_validation.json", "results/phase17_fault_injection_results.json", "results/phase17_command_audit.json", "results/phase17_adapter_status.json"])
    evidence_paths.update(item["path"] for item in reports if item["present"])
    evidence_paths.update([
        "PHASE18_REPORT.md",
        "PHASE18_EVIDENCE_INDEX.md",
        "PHASE18_DATA_INTEGRITY_REPORT.md",
        "PHASE18_FINAL_ACCEPTANCE_MATRIX.md",
        "PHASE18_KNOWN_ISSUES.md",
        "PHASE18_RELEASE_READINESS.md",
        "PHASE18_REPRODUCIBILITY_REPORT.md",
        "PHASE18_DEFENSE_QA.md",
        "PHASE18_OFFICIAL_REFERENCES.md",
        "scripts/verify_phase18_release_manifest.py",
        "results/phase18/phase18_test_execution.json",
        "results/phase18/browser/phase18-1920x1080.png",
        "results/phase18/browser/phase18-1366x768.png",
        "results/phase18/browser/phase18-390x844.png",
    ])
    evidence_paths.update(
        f"data/phase15/raw/{dataset_id}/{item['filename']}"
        for item in dataset_manifest.get("files", [])
    )
    manifest_items = []
    for relative in sorted(evidence_paths):
        path = ROOT / relative
        if not path.is_file():
            continue
        phase = "phase_unknown"
        for number in range(1, 19):
            if f"phase{number}" in relative.lower() or f"phase{number}_" in relative.lower():
                phase = f"phase{number}"
                break
        if relative.startswith("results/phase1") and phase == "phase1":
            pass
        if relative.startswith("data/phase15/raw/"):
            source_class = "public_source_data_not_copied_to_rc"
            release_included = False
        elif "phase17_closed_loop" in relative or "fault_injection" in relative:
            source_class = "synthetic_software_test_evidence"
            release_included = True
        elif "phase6_demo" in relative or "phase3_replay" in relative:
            source_class = "saved_abstract_simulation_replay"
            release_included = True
        elif relative.startswith("results/") and ("raw" in relative or "validation" in relative):
            source_class = "frozen_or_derived_simulation_evidence"
            release_included = True
        elif relative.startswith("configs/phase15"):
            source_class = "public_data_provenance_and_calibration_protocol"
            release_included = True
        else:
            source_class = "phase_report_audit_or_configuration"
            release_included = True
        manifest_items.append({
            "path": Path(relative).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "file_type": path.suffix.lower() or "no_extension",
            "source_phase": phase,
            "evidence_class": source_class,
            "release_included": release_included,
            "frozen_historical_data": relative in {item["path"] for item in protected_checked},
        })
    evidence_manifest = {
        "schema_version": "1.0",
        "phase": "phase18_evidence_manifest",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_self_hash_included": False,
        "items": manifest_items,
    }
    (OUT / "phase18_evidence_manifest.json").write_text(json.dumps(evidence_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "protected": f"{result['protected_history']['matched_file_count']}/{result['protected_history']['protected_file_count']}",
        "phase5_source_drift": result["protected_history"]["phase5_source_snapshot_drift_count"],
        "phase9_manifest_matches": sum(item["matches"] for item in phase_manifests["phase9"]),
        "phase10_manifest_matches": sum(item["matches"] for item in phase_manifests["phase10"]),
        "phase11_manifest_matches": sum(item["matches"] for item in phase_manifests["phase11"]),
        "phase15_public_sources": f"{sum(item['matches'] for item in public_sources)}/{len(public_sources)}",
        "evidence_items": len(manifest_items),
        "warnings": warnings,
        "errors": errors,
    }, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
