"""Audit Phase 13 page/data wiring and verify frozen experiment artifacts read-only."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUMMARY_SOURCES = {
    "phase5": "results/phase5_validation_summary.json",
    "phase8": "results/phase8_replication_summary.json",
    "phase9": "results/phase9_corrected_confirmation_summary.json",
    "phase10": "results/phase10_confirmation_summary.json",
    "phase11": "results/phase11_confirmation_summary.json",
}
REPLAY_SCENARIOS = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
REQUIRED_FRONTEND_ROUTES = {"/", "/command", "/decision", "/lab", "/demo", "/research"}
REQUIRED_API_ROUTES = {
    "/api/health",
    "/api/experiments/phase2",
    "/api/experiments/phase5",
    "/api/experiments/phase5/{scenario_id}",
    "/api/replay/{seed}",
    "/api/demo/phase6",
    "/api/demo/phase6/{scenario_id}",
    "/api/research/{phase_id}",
}
PHASE13_SOURCES = (
    "src/lowalt6g/api.py",
    "tests/test_phase13_api.py",
    "frontend/src/App.tsx",
    "frontend/src/components.tsx",
    "frontend/src/ResearchPage.tsx",
    "frontend/src/research-model.ts",
    "frontend/src/research.css",
    "frontend/src/Phase6DemoPage.tsx",
)
SCREENSHOT_EXPECTATIONS = {
    "artifacts/phase13/browser/demo-1920x1080.png": 1920,
    "artifacts/phase13/browser/demo-1366x768.png": 1366,
    "artifacts/phase13/browser/research-1920x1080.png": 1920,
    "artifacts/phase13/browser/research-1366x768.png": 1366,
    "artifacts/phase13/browser/research-390x844.png": 390,
    "artifacts/phase13/browser/research-phase9-1920x1080.png": 1920,
}


def load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_frozen_result_hashes() -> dict[str, str]:
    expected: dict[str, str] = {}
    manifests = (
        "results/phase9_artifact_manifest.json",
        "results/phase10_artifact_manifest.json",
        "results/phase11_artifact_manifest.json",
    )
    for manifest_path in manifests:
        manifest = load_json(manifest_path)
        entries: list[tuple[str, Any]] = []
        protected = manifest.get("protected_historical_sha256", {})
        if isinstance(protected, dict):
            entries.extend(protected.items())
        artifacts = manifest.get("artifacts", {})
        if isinstance(artifacts, dict):
            for path, metadata in artifacts.items():
                digest = metadata.get("sha256") if isinstance(metadata, dict) else metadata
                entries.append((path, digest))
        for relative_path, digest in entries:
            if not isinstance(relative_path, str) or not relative_path.startswith("results/"):
                continue
            if Path(relative_path).suffix.lower() not in {".json", ".jsonl"}:
                continue
            if not isinstance(digest, str):
                continue
            previous = expected.get(relative_path)
            if previous is not None and previous != digest:
                raise ValueError(f"Conflicting frozen hashes for {relative_path}")
            expected[relative_path] = digest
    return expected


def audit_frozen_results() -> dict[str, Any]:
    expected = expected_frozen_result_hashes()
    verified: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    for relative_path, expected_hash in sorted(expected.items()):
        path = ROOT / relative_path
        if not path.is_file():
            missing.append(relative_path)
            continue
        actual_hash = sha256(path)
        verified[relative_path] = {"expected_sha256": expected_hash, "actual_sha256": actual_hash}
        if actual_hash != expected_hash:
            mismatches.append({"path": relative_path, "expected_sha256": expected_hash, "actual_sha256": actual_hash})
    return {
        "expected_count": len(expected),
        "verified_count": len(verified) - len(mismatches),
        "missing": missing,
        "mismatches": mismatches,
        "status": "PASS" if not missing and not mismatches else "FAIL",
    }


def audit_replays() -> dict[str, Any]:
    manifest_path = "results/phase6_demo_manifest.json"
    manifest = load_json(manifest_path)
    scenarios: dict[str, Any] = {}
    for scenario_id in REPLAY_SCENARIOS:
        item = manifest.get("scenarios", {}).get(scenario_id, {})
        artifact_name = item.get("artifact")
        artifact_path = f"results/{artifact_name}" if isinstance(artifact_name, str) else ""
        artifact_file = ROOT / artifact_path if artifact_path else None
        valid = bool(
            artifact_file
            and artifact_file.is_file()
            and manifest.get("mode") == "precomputed_offline_replay"
            and manifest.get("live_stream") is False
        )
        details: dict[str, Any] = {"artifact": artifact_path or None, "seed": item.get("seed"), "valid": valid}
        if valid and artifact_file:
            artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
            runs = artifact.get("strategies", {})
            frame_counts = {policy: len(run.get("state_snapshots", [])) for policy, run in runs.items()}
            details.update(
                {
                    "sha256": sha256(artifact_file),
                    "scenario_id_matches": artifact.get("scenario_id") == scenario_id,
                    "seed_matches": artifact.get("seed") == item.get("seed"),
                    "model_scope": artifact.get("model_scope"),
                    "policy_frame_counts": frame_counts,
                    "status": "PASS" if artifact.get("scenario_id") == scenario_id
                    and artifact.get("seed") == item.get("seed")
                    and bool(frame_counts)
                    and all(count > 0 for count in frame_counts.values())
                    else "FAIL",
                }
            )
        else:
            details["status"] = "FAIL"
        scenarios[scenario_id] = details
    return {
        "manifest": manifest_path,
        "manifest_sha256": sha256(ROOT / manifest_path),
        "mode": manifest.get("mode"),
        "live_stream": manifest.get("live_stream"),
        "multi_uav_frame_replay_available": False,
        "scenarios": scenarios,
        "status": "PASS" if all(item["status"] == "PASS" for item in scenarios.values()) else "FAIL",
    }


def audit_routes() -> dict[str, Any]:
    from lowalt6g.phase6_api import app as api_app

    # FastAPI now keeps included routers lazy on `app.routes`; OpenAPI expands
    # them and reflects the routes actually exposed by the application.
    api_routes = set(api_app.openapi()["paths"])
    app_source = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    frontend_routes = set(re.findall(r'<Route\s+path="([^"]+)"', app_source))
    return {
        "api_routes": {path: path in api_routes for path in sorted(REQUIRED_API_ROUTES)},
        "frontend_routes": {path: path in frontend_routes for path in sorted(REQUIRED_FRONTEND_ROUTES)},
        "status": "PASS" if REQUIRED_API_ROUTES <= api_routes and REQUIRED_FRONTEND_ROUTES <= frontend_routes else "FAIL",
    }


def audit_sources() -> dict[str, Any]:
    return {
        relative_path: {"exists": (ROOT / relative_path).is_file(), "sha256": sha256(ROOT / relative_path) if (ROOT / relative_path).is_file() else None}
        for relative_path in PHASE13_SOURCES
    }


def audit_screenshots() -> dict[str, Any]:
    items: dict[str, Any] = {}
    for relative_path, expected_width in SCREENSHOT_EXPECTATIONS.items():
        path = ROOT / relative_path
        exists = path.is_file()
        width = height = None
        if exists:
            with path.open("rb") as stream:
                header = stream.read(24)
            if len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
                width, height = struct.unpack(">II", header[16:24])
        items[relative_path] = {
            "exists": exists,
            "width": width,
            "height": height,
            "expected_viewport_width": expected_width,
            "size_bytes": path.stat().st_size if exists else None,
            "status": "PASS" if width == expected_width and height else "FAIL",
        }
    return {"screenshots": items, "status": "PASS" if all(item["status"] == "PASS" for item in items.values()) else "FAIL"}


def main() -> int:
    data_sources = {
        phase: {
            "path": relative_path,
            "exists": (ROOT / relative_path).is_file(),
            "sha256": sha256(ROOT / relative_path) if (ROOT / relative_path).is_file() else None,
            "size_bytes": (ROOT / relative_path).stat().st_size if (ROOT / relative_path).is_file() else None,
        }
        for phase, relative_path in SUMMARY_SOURCES.items()
    }
    frozen = audit_frozen_results()
    replays = audit_replays()
    routes = audit_routes()
    source_hashes = audit_sources()
    screenshots = audit_screenshots()
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        branch = "unknown"
    status = "PASS" if frozen["status"] == "PASS" and replays["status"] == "PASS" and routes["status"] == "PASS" and screenshots["status"] == "PASS" and all(item["exists"] for item in data_sources.values()) and all(item["exists"] for item in source_hashes.values()) else "FAIL"
    report = {
        "schema_version": "1.0",
        "phase": "phase13_scientific_visualization",
        "audit_scope": "read-only hashes of frozen experiment outputs, source datasets, offline replay frames, and current application route registration",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_branch": branch,
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "data_sources": data_sources,
        "historical_frozen_result_integrity": frozen,
        "phase6_replay_integrity": replays,
        "route_inventory": routes,
        "browser_screenshot_evidence": screenshots,
        "phase13_source_hashes": source_hashes,
        "status": status,
    }
    output_path = ROOT / "results/phase13_visualization_audit.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "frozen_results": frozen["status"], "verified_frozen_result_count": frozen["verified_count"], "replays": replays["status"], "routes": routes["status"], "screenshots": screenshots["status"], "output": str(output_path)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
