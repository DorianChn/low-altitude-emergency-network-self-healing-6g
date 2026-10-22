"""Read-only Phase 12 project, provenance, and architecture audit.

This script writes only results/phase12_integrity_audit.json. It does not run
or rewrite historical experiments, manifests, or frozen result files.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_entries(entries: dict[str, Any], label: str) -> dict[str, Any]:
    missing: list[str] = []
    mismatches: list[str] = []
    for relative, expected_value in entries.items():
        expected = expected_value.get("sha256") if isinstance(expected_value, dict) else expected_value
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
        elif sha256_file(path) != expected:
            mismatches.append(relative)
    return {
        "label": label,
        "expected_count": len(entries),
        "verified_count": len(entries) - len(missing) - len(mismatches),
        "missing": missing,
        "mismatches": mismatches,
        "status": "PASS" if not missing and not mismatches else "FAIL",
    }


def _load_phase5_auditor():
    path = ROOT / "scripts/phase5_audit.py"
    spec = importlib.util.spec_from_file_location("phase12_phase5_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Phase 5 auditor: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit_phase5


def _command(*args: str) -> str | None:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _check_module_inventory() -> dict[str, Any]:
    inventory_path = ROOT / "docs/phase12/module_inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    checked = 0
    for module in inventory["modules"]:
        for relative in module["code_paths"] + module.get("evidence_paths", []):
            checked += 1
            if not (ROOT / relative).is_file():
                missing.append(relative)
    diagram_paths: set[str] = set()
    for diagram in (ROOT / "docs/phase12").glob("*.mmd"):
        content = diagram.read_text(encoding="utf-8")
        diagram_paths.update(re.findall(r"(?:src|frontend|configs|results)/[A-Za-z0-9_./-]+", content))
    generated_outputs = {"results/phase12_integrity_audit.json"}
    missing_diagram_paths = sorted(
        path for path in diagram_paths if path not in generated_outputs and not (ROOT / path).exists()
    )
    return {
        "module_count": len(inventory["modules"]),
        "module_path_references_checked": checked,
        "missing_module_or_evidence_paths": sorted(set(missing)),
        "diagram_path_references_checked": len(diagram_paths),
        "missing_diagram_paths": missing_diagram_paths,
        "status": "PASS" if not missing and not missing_diagram_paths else "FAIL",
    }


def _check_diagram_exports() -> dict[str, Any]:
    diagrams = ("system_architecture", "research_dataflow")
    issues: list[str] = []
    checked = 0
    for name in diagrams:
        mmd_path = ROOT / f"docs/phase12/{name}.mmd"
        svg_path = ROOT / f"docs/phase12/{name}.svg"
        png_path = ROOT / f"docs/phase12/{name}.png"
        if not all(path.is_file() for path in (mmd_path, svg_path, png_path)):
            issues.append(f"{name}: missing mmd/svg/png export")
            continue
        checked += 1
        if not mmd_path.read_text(encoding="utf-8").startswith("flowchart "):
            issues.append(f"{name}: Mermaid source has no flowchart declaration")
        try:
            root = ET.parse(svg_path).getroot()
            if not root.tag.endswith("svg") or not root.attrib.get("viewBox"):
                issues.append(f"{name}: SVG root/viewBox invalid")
        except (ET.ParseError, OSError) as error:
            issues.append(f"{name}: invalid SVG: {error}")
        try:
            from PIL import Image

            with Image.open(png_path) as image:
                if image.width < 1200 or image.height < 700:
                    issues.append(f"{name}: PNG export is smaller than report-ready minimum")
        except (OSError, ImportError) as error:
            issues.append(f"{name}: PNG cannot be inspected: {error}")
    return {
        "diagram_count": len(diagrams),
        "complete_export_count": checked,
        "issues": issues,
        "status": "PASS" if not issues and checked == len(diagrams) else "FAIL",
    }


def _phase12_artifacts() -> dict[str, Any]:
    paths = [
        "PHASE12_REPORT.md",
        "PHASE12_ARCHITECTURE.md",
        "PHASE12_STANDARDS_MAPPING.md",
        "PHASE12_REQUIREMENT_TRACEABILITY.md",
        "PHASE12_OFFICIAL_REFERENCES.md",
        "docs/phase12/module_inventory.json",
        "docs/phase12/system_architecture.mmd",
        "docs/phase12/system_architecture.svg",
        "docs/phase12/system_architecture.png",
        "docs/phase12/research_dataflow.mmd",
        "docs/phase12/research_dataflow.svg",
        "docs/phase12/research_dataflow.png",
        "scripts/phase12_audit.py",
        "scripts/render_phase12_architecture.py",
    ]
    missing = [relative for relative in paths if not (ROOT / relative).is_file()]
    artifacts = {
        relative: {
            "sha256": sha256_file(ROOT / relative),
            "bytes": (ROOT / relative).stat().st_size,
        }
        for relative in paths
        if (ROOT / relative).is_file()
    }
    return {
        "expected_count": len(paths),
        "verified_count": len(artifacts),
        "missing": missing,
        "artifacts": artifacts,
        "status": "PASS" if not missing else "FAIL",
    }


def run_audit() -> dict[str, Any]:
    from lowalt6g.phase11_experiments import (
        verify_confirmation_protocol,
        verify_phase10_baseline,
    )

    phase5, _failure_index = _load_phase5_auditor()(ROOT)
    phase5_result = {
        "status": phase5.get("status"),
        "issues": phase5.get("issues", []),
        "scenario_count": phase5.get("scenario_count"),
        "seed_count": phase5.get("held_out_seed_count"),
        "policy_run_count": phase5.get("strategy_run_count"),
        "failed_or_not_sustained_count": phase5.get("failure_or_not_sustained_case_count"),
        "frozen_manifest_sha256": sha256_file(ROOT / "results/phase5_frozen_manifest.json"),
    }

    phase8_sensitivity = json.loads(
        (ROOT / "results/phase8_sensitivity_validation_audit.json").read_text(encoding="utf-8")
    )
    phase8_replication = json.loads(
        (ROOT / "results/phase8_replication_postprocess_audit.json").read_text(encoding="utf-8")
    )

    phase9_manifest = json.loads((ROOT / "results/phase9_artifact_manifest.json").read_text(encoding="utf-8"))
    phase9_artifacts = _verify_entries(phase9_manifest["artifacts"], "Phase 9 artifact manifest")
    phase9_protected = _verify_entries(
        phase9_manifest["protected_historical_sha256"], "Phase 5/8 protected references in Phase 9"
    )

    phase10_baseline = verify_phase10_baseline()
    phase11_protocol = verify_confirmation_protocol()
    phase11_manifest = json.loads((ROOT / "results/phase11_artifact_manifest.json").read_text(encoding="utf-8"))
    phase11_artifacts = _verify_entries(phase11_manifest["artifacts"], "Phase 11 artifact manifest")
    phase11_delivery = json.loads((ROOT / "results/phase11_delivery_audit.json").read_text(encoding="utf-8"))

    reports_expected = [f"PHASE{phase}_REPORT.md" for phase in range(1, 12)]
    reports_present = [name for name in reports_expected if (ROOT / name).is_file()]
    reports_missing = [name for name in reports_expected if not (ROOT / name).is_file()]

    module_inventory = _check_module_inventory()
    diagram_exports = _check_diagram_exports()
    phase12_artifacts = _phase12_artifacts()
    from lowalt6g.phase6_api import app as api_app

    api_paths = api_app.openapi().get("paths", {})
    expected_routes = (
        "/api/health",
        "/api/experiments/phase2",
        "/api/experiments/phase5",
        "/api/experiments/phase5/{scenario_id}",
        "/api/replay/{seed}",
        "/api/demo/phase6",
        "/api/demo/phase6/{scenario_id}",
    )
    api_route_presence = {
        route: "get" in api_paths.get(route, {})
        for route in expected_routes
    }
    frontend_source = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    frontend_routes = {
        route: f'path="{route}"' in frontend_source
        for route in ("/", "/command", "/decision", "/lab", "/demo")
    }

    all_pass = all(
        (
            phase5_result["status"] == "PASS",
            not phase5_result["issues"],
            phase8_sensitivity.get("status") == "PASS",
            phase8_sensitivity.get("policy_run_count") == phase8_sensitivity.get("expected_policy_run_count"),
            phase8_replication.get("status") == "PASS",
            phase9_artifacts["status"] == "PASS",
            phase9_protected["status"] == "PASS",
            phase10_baseline.get("phase10_artifact_hash_mismatches") == 0,
            phase10_baseline.get("phase10_matched_trace_mismatches") == 0,
            phase11_protocol.get("status") == "frozen_before_confirmation",
            phase11_artifacts["status"] == "PASS",
            phase11_delivery.get("confirmation_status") == "complete",
            phase11_delivery.get("confirmation_seed_count") == 80,
            phase11_delivery.get("confirmation_policy_run_count") == 880,
            not phase11_delivery.get("matched_trace_mismatches"),
            all(value == 0 for value in phase11_delivery.get("runtime_violation_totals", {}).values()),
            module_inventory["status"] == "PASS",
            diagram_exports["status"] == "PASS",
            phase12_artifacts["status"] == "PASS",
            all(api_route_presence.values()),
            all(frontend_routes.values()),
        )
    )
    return {
        "schema_version": "1.0",
        "phase": "phase12_6g_architecture_mapping",
        "audit_scope": "read-only audit of historical artifacts and current source mappings; no historical experiment rerun",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "git": {
            "branch": _command("git", "branch", "--show-current"),
            "head": _command("git", "rev-parse", "HEAD"),
            "staged_paths": _command("git", "diff", "--cached", "--name-only"),
            "worktree_changes_preserved": True,
        },
        "historical_reports": {
            "expected": reports_expected,
            "present": reports_present,
            "missing": reports_missing,
        },
        "phase5": phase5_result,
        "phase8": {
            "sensitivity_validation": {
                "status": phase8_sensitivity.get("status"),
                "seed_count": phase8_sensitivity.get("seed_count"),
                "policy_run_count": phase8_sensitivity.get("policy_run_count"),
                "battery_reserve_violations": phase8_sensitivity.get("battery_reserve_violations"),
                "latency_sample_count_mismatches": phase8_sensitivity.get("latency_sample_count_mismatches"),
                "issues": phase8_sensitivity.get("issues", []),
            },
            "replication_postprocess": {
                "status": phase8_replication.get("status"),
                "seed_rows": phase8_replication.get("seed_rows"),
                "policy_runs": phase8_replication.get("policy_runs"),
                "per_seed_records_modified": phase8_replication.get("per_seed_records_modified"),
            },
        },
        "phase9": {"artifact_manifest": phase9_artifacts, "protected_historical": phase9_protected},
        "phase10": phase10_baseline,
        "phase11": {
            "protocol_status": phase11_protocol.get("status"),
            "artifact_manifest": phase11_artifacts,
            "confirmation_seed_count": phase11_delivery.get("confirmation_seed_count"),
            "confirmation_policy_run_count": phase11_delivery.get("confirmation_policy_run_count"),
            "matched_trace_mismatches": phase11_delivery.get("matched_trace_mismatches"),
            "runtime_violation_totals": phase11_delivery.get("runtime_violation_totals"),
            "decision_timeout_count": phase11_delivery.get("decision_timeout_count"),
            "historical_validation_record": phase11_delivery.get("primary_tests"),
        },
        "current_architecture_checks": {
            "module_inventory": module_inventory,
            "diagram_exports": diagram_exports,
            "api_route_presence": api_route_presence,
            "frontend_route_presence": frontend_routes,
        },
        "phase12_artifacts": phase12_artifacts,
        "status": "PASS" if all_pass else "FAIL",
    }


def main() -> int:
    payload = run_audit()
    output = ROOT / "results/phase12_integrity_audit.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
