"""Phase 6 read-only replay routes, layered onto the historical API app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .api import RESULTS_DIR, app
from .phase6_demo import SCENARIOS


router = APIRouter(prefix="/api/demo/phase6", tags=["phase6-demo"])
_SCENARIO_IDS = {scenario_id for scenario_id, _, _ in SCENARIOS}
_MODEL_SCOPE = "abstract_6g_research_simulation_not_real_network_test"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=f"Demo artifact is unavailable: {path.name}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=503, detail=f"Demo artifact cannot be read: {path.name}") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail=f"Demo artifact has an invalid shape: {path.name}")
    return payload


@router.get("")
def phase6_demo_index() -> dict[str, Any]:
    """List only generated replay artifacts linked to the frozen Phase 5 set."""
    manifest = _read_json(RESULTS_DIR / "phase6_demo_manifest.json")
    if (
        manifest.get("mode") != "precomputed_offline_replay"
        or manifest.get("live_stream") is not False
        or manifest.get("model_scope") != _MODEL_SCOPE
        or manifest.get("frozen_manifest_sha256") is None
    ):
        raise HTTPException(status_code=503, detail="Phase 6 replay manifest has invalid provenance")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != _SCENARIO_IDS:
        raise HTTPException(status_code=503, detail="Phase 6 replay manifest is missing a required scenario")
    for scenario_id, item in scenarios.items():
        expected_file = f"phase6_demo_{scenario_id}.json"
        if not isinstance(item, dict) or item.get("artifact") != expected_file:
            raise HTTPException(status_code=503, detail="Phase 6 replay manifest contains an invalid artifact path")
        if not (RESULTS_DIR / expected_file).is_file():
            raise HTTPException(status_code=503, detail=f"Demo artifact is unavailable: {expected_file}")
    return manifest


@router.get("/{scenario_id}")
def phase6_demo_scenario(scenario_id: str) -> dict[str, Any]:
    """Return one actual held-out validation seed with discrete saved frames."""
    if scenario_id not in _SCENARIO_IDS:
        raise HTTPException(status_code=404, detail="unknown Phase 6 demo scenario")
    manifest = phase6_demo_index()
    item = manifest["scenarios"][scenario_id]
    artifact = _read_json(RESULTS_DIR / item["artifact"])
    if (
        artifact.get("mode") != "precomputed_offline_replay"
        or artifact.get("live_stream") is not False
        or artifact.get("model_scope") != _MODEL_SCOPE
        or artifact.get("scenario_id") != scenario_id
        or artifact.get("seed") != item.get("seed")
    ):
        raise HTTPException(status_code=503, detail="Demo artifact does not match its replay manifest")
    validation = artifact.get("validation")
    if not isinstance(validation, dict) or validation.get("reconciliation", {}).get(
        "all_strategy_frames_cover_every_configured_tick"
    ) is not True:
        raise HTTPException(status_code=503, detail="Demo artifact is missing full-tick simulator frames")
    return artifact


app.include_router(router)
