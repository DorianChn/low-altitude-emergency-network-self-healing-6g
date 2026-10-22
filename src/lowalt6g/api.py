"""Read-only FastAPI contract for real benchmark and deterministic replay data."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(os.environ.get("LOWALT6G_RESULTS_DIR", PROJECT_ROOT / "results")).resolve()
BENCHMARK_PATH = RESULTS_DIR / "phase2_20_seed_results.json"
PHASE5_SCENARIO_IDS = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
RESEARCH_ARTIFACTS = {
    "phase5": "phase5_validation_summary.json",
    "phase8": "phase8_replication_summary.json",
    "phase9": "phase9_corrected_confirmation_summary.json",
    "phase10": "phase10_confirmation_summary.json",
    "phase11": "phase11_confirmation_summary.json",
    "phase14": "phase14_confirmation_summary.json",
    "phase15": "phase15_calibration_summary.json",
    "phase16": "phase16_measurement_readiness.json",
    "phase17": "phase17_validation_summary.json",
    "phase18": "phase18/phase18_validation_summary.json",
}
PHASE15_SUPPORTING_ARTIFACTS = {
    "holdout_validation": "phase15_holdout_validation.json",
    "dataset_audit": "phase15_dataset_audit.json",
}
PHASE15_PLOT_FILES = {
    "phase15_fit_and_holdout.png",
    "phase15_fit_and_holdout.svg",
    "phase15_holdout_residuals.png",
    "phase15_holdout_residuals.svg",
    "phase15_parameter_uncertainty.png",
    "phase15_parameter_uncertainty.svg",
}
PHASE16_SUPPORTING_ARTIFACTS = {
    "environment_inventory": "phase16_environment_inventory.json",
    "integrity_audit": "phase16_integrity_audit.json",
    "uncertainty_budget": "phase16_uncertainty_budget.json",
    "calibration_state": "phase16_calibration_state.json",
}
PHASE17_SUPPORTING_ARTIFACTS = {
    "environment_inventory": "phase17_environment_inventory.json",
    "integrity_audit": "phase17_integrity_audit.json",
    "adapter_status": "phase17_adapter_status.json",
    "closed_loop_run": "phase17_closed_loop_run.json",
    "command_audit": "phase17_command_audit.json",
    "fault_injection_results": "phase17_fault_injection_results.json",
    "offline_replay_validation": "phase17_replay_validation.json",
}
PHASE18_SUPPORTING_ARTIFACTS = {
    "integrity_audit": "phase18/phase18_integrity_audit.json",
    "evidence_manifest": "phase18/phase18_evidence_manifest.json",
    "release_manifest": "phase18/phase18_release_manifest.json",
}

app = FastAPI(
    title="Low Altitude Emergency Network Simulation API",
    version="0.1.0",
    description=(
        "Read-only access to actual abstract simulation results and timestamped offline replay. "
        "This API is not a live 6G network interface."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _read_artifact(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Simulation artifact is unavailable: {path.name}",
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"Simulation artifact cannot be read: {path.name}",
        ) from error
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail=f"Simulation artifact has invalid shape: {path.name}")
    return value


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": "precomputed_offline_replay",
        "live_stream": False,
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "phase2_benchmark_available": BENCHMARK_PATH.is_file(),
        "seed_2026_replay_available": (RESULTS_DIR / "phase3_replay_seed_2026.json").is_file(),
        "phase5_validation_available": (RESULTS_DIR / "phase5_validation_summary.json").is_file(),
    }


@app.get("/api/experiments/phase2")
def phase2_benchmark() -> dict[str, Any]:
    """Return the committed 20-seed A/B/C experiment artifact without alteration."""
    return _read_artifact(BENCHMARK_PATH)


@app.get("/api/experiments/phase5")
def phase5_benchmark() -> dict[str, Any]:
    """Return the multi-scenario Phase 5 summary when held-out results exist."""
    return _read_artifact(RESULTS_DIR / "phase5_validation_summary.json")


@app.get("/api/experiments/phase5/{scenario_id}")
def phase5_scenario(scenario_id: str) -> dict[str, Any]:
    """Return one scenario's raw held-out seed results and event logs."""
    if scenario_id not in PHASE5_SCENARIO_IDS:
        raise HTTPException(status_code=404, detail="unknown Phase 5 scenario")
    return _read_artifact(RESULTS_DIR / f"phase5_validation_{scenario_id}.json")


@app.get("/api/research/{phase_id}")
def research_artifact(phase_id: str) -> dict[str, Any]:
    """Return one allowlisted, unchanged summary artifact with its file provenance."""
    filename = RESEARCH_ARTIFACTS.get(phase_id)
    if filename is None:
        raise HTTPException(status_code=404, detail="unknown research phase")
    path = RESULTS_DIR / filename
    artifact = _read_artifact(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    response = {
        "schema_version": "1.0",
        "dataset_id": phase_id,
        "artifact_path": f"results/{filename}",
        "artifact_sha256": digest,
        "experiment_role": (
            "phase14_independent_confirmation"
            if phase_id == "phase14" and artifact.get("partition") == "confirmation"
            else artifact.get("experiment_role", "frozen_validation_summary")
        ),
        "model_scope": artifact.get(
            "model_scope", "abstract_6g_research_simulation_not_real_network_test"
        ),
        "artifact": artifact,
    }
    if phase_id == "phase14":
        sensitivity_path = RESULTS_DIR / "phase14_model_sensitivity_summary.json"
        sensitivity = _read_artifact(sensitivity_path)
        response["supporting_artifacts"] = {
            "sensitivity": {
                "artifact_path": "results/phase14_model_sensitivity_summary.json",
                "artifact_sha256": hashlib.sha256(sensitivity_path.read_bytes()).hexdigest(),
                "artifact": sensitivity,
            }
        }
    if phase_id == "phase15":
        response["model_scope"] = artifact.get(
            "model_scope",
            "public_3p6_ghz_measurement_path_loss_evaluation_not_project_device_calibration",
        )
        response["experiment_role"] = "public_measurement_group_holdout_evaluation"
        supporting = {}
        for key, support_filename in PHASE15_SUPPORTING_ARTIFACTS.items():
            support_path = RESULTS_DIR / support_filename
            support_artifact = _read_artifact(support_path)
            supporting[key] = {
                "artifact_path": f"results/{support_filename}",
                "artifact_sha256": hashlib.sha256(support_path.read_bytes()).hexdigest(),
                "artifact": support_artifact,
            }
        response["supporting_artifacts"] = supporting
    if phase_id == "phase16":
        response["model_scope"] = "measurement_readiness_and_uncertainty_framework_not_field_calibration"
        response["experiment_role"] = "current_measurement_readiness_snapshot"
        supporting = {}
        for key, support_filename in PHASE16_SUPPORTING_ARTIFACTS.items():
            support_path = RESULTS_DIR / support_filename
            support_artifact = _read_artifact(support_path)
            supporting[key] = {
                "artifact_path": f"results/{support_filename}",
                "artifact_sha256": hashlib.sha256(support_path.read_bytes()).hexdigest(),
                "artifact": support_artifact,
            }
        import_relative = artifact.get("measurement_import_audit_path")
        if (
            not isinstance(import_relative, str)
            or not import_relative.startswith("results/phase16/imports/")
            or ".." in Path(import_relative).parts
            or not import_relative.endswith(".audit.json")
        ):
            raise HTTPException(status_code=503, detail="Phase 16 saved measurement import audit is unavailable")
        import_path = (RESULTS_DIR / import_relative.removeprefix("results/")).resolve()
        try:
            import_path.relative_to(RESULTS_DIR.resolve())
        except ValueError as error:
            raise HTTPException(status_code=503, detail="Phase 16 import audit path is outside the results directory") from error
        import_artifact = _read_artifact(import_path)
        supporting["measurement_import"] = {
            "artifact_path": import_relative,
            "artifact_sha256": hashlib.sha256(import_path.read_bytes()).hexdigest(),
            "artifact": import_artifact,
        }
        response["supporting_artifacts"] = supporting
    if phase_id == "phase17":
        response["model_scope"] = "software_closed_loop_and_saved_replay_validation_not_real_hil"
        response["experiment_role"] = "phase17_software_acceptance_and_interface_validation"
        supporting = {}
        for key, support_filename in PHASE17_SUPPORTING_ARTIFACTS.items():
            support_path = RESULTS_DIR / support_filename
            support_artifact = _read_artifact(support_path)
            supporting[key] = {
                "artifact_path": f"results/{support_filename}",
                "artifact_sha256": hashlib.sha256(support_path.read_bytes()).hexdigest(),
                "artifact": support_artifact,
            }
        response["supporting_artifacts"] = supporting
    if phase_id == "phase18":
        response["model_scope"] = "final_research_evidence_and_local_release_candidate_audit_not_real_network_validation"
        response["experiment_role"] = "phase18_final_audit_snapshot"
        supporting = {}
        for key, support_filename in PHASE18_SUPPORTING_ARTIFACTS.items():
            support_path = RESULTS_DIR / support_filename
            support_artifact = _read_artifact(support_path)
            supporting[key] = {
                "artifact_path": f"results/{support_filename}",
                "artifact_sha256": hashlib.sha256(support_path.read_bytes()).hexdigest(),
                "artifact": support_artifact,
            }
        response["supporting_artifacts"] = supporting
    return response


@app.get("/api/research/phase15/plots/{filename}")
def phase15_plot(filename: str) -> FileResponse:
    """Serve only the pre-rendered, saved Phase 15 evidence plots."""
    if filename not in PHASE15_PLOT_FILES:
        raise HTTPException(status_code=404, detail="unknown Phase 15 evidence plot")
    path = PROJECT_ROOT / "plots" / "phase15" / filename
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Phase 15 evidence plot is unavailable: {filename}")
    media_type = "image/svg+xml" if filename.endswith(".svg") else "image/png"
    return FileResponse(path, media_type=media_type)


@app.get("/api/replay/{seed}")
def seed_replay(seed: int) -> dict[str, Any]:
    """Return one captured deterministic replay generated by the simulation engine."""
    if seed < 0:
        raise HTTPException(status_code=422, detail="seed must be a non-negative integer")
    artifact = _read_artifact(RESULTS_DIR / f"phase3_replay_seed_{seed}.json")
    if artifact.get("seed") != seed:
        raise HTTPException(status_code=503, detail="Replay artifact seed does not match the request")
    if artifact.get("mode") != "precomputed_offline_replay" or artifact.get("live_stream") is not False:
        raise HTTPException(status_code=503, detail="Replay artifact is missing offline provenance")
    return artifact
