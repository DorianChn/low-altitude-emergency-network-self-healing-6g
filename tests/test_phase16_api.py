from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from lowalt6g import api


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_phase16_endpoint_returns_saved_readiness_and_hashed_evidence(tmp_path: Path, monkeypatch) -> None:
    readiness = {
        "phase": "phase16_field_measurement_readiness",
        "status": "NOT_READY_FOR_FIELD_MEASUREMENT",
        "measurement_import_audit_path": "results/phase16/imports/source.audit.json",
    }
    write_json(tmp_path / "phase16_measurement_readiness.json", readiness)
    for filename in api.PHASE16_SUPPORTING_ARTIFACTS.values():
        write_json(tmp_path / filename, {"path": filename})
    import_path = tmp_path / "phase16/imports/source.audit.json"
    write_json(import_path, {"record_count_after_cleaning": 1370, "source_type": "public_measurement"})
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    response = api.research_artifact("phase16")

    assert response["dataset_id"] == "phase16"
    assert response["artifact"] == readiness
    assert response["artifact_sha256"] == hashlib.sha256((tmp_path / "phase16_measurement_readiness.json").read_bytes()).hexdigest()
    assert response["model_scope"] == "measurement_readiness_and_uncertainty_framework_not_field_calibration"
    assert response["supporting_artifacts"]["measurement_import"]["artifact"]["record_count_after_cleaning"] == 1370
    assert response["supporting_artifacts"]["measurement_import"]["artifact_sha256"] == hashlib.sha256(import_path.read_bytes()).hexdigest()


def test_phase16_endpoint_does_not_claim_success_when_saved_import_is_missing(tmp_path: Path, monkeypatch) -> None:
    write_json(tmp_path / "phase16_measurement_readiness.json", {
        "measurement_import_audit_path": "results/phase16/imports/missing.audit.json",
    })
    for filename in api.PHASE16_SUPPORTING_ARTIFACTS.values():
        write_json(tmp_path / filename, {"path": filename})
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    with pytest.raises(HTTPException) as error:
        api.research_artifact("phase16")
    assert error.value.status_code == 503
    assert "unavailable" in error.value.detail or "cannot be read" in error.value.detail


def test_phase16_endpoint_rejects_import_path_traversal(tmp_path: Path, monkeypatch) -> None:
    write_json(tmp_path / "phase16_measurement_readiness.json", {
        "measurement_import_audit_path": "results/phase16/imports/../../secret.audit.json",
    })
    for filename in api.PHASE16_SUPPORTING_ARTIFACTS.values():
        write_json(tmp_path / filename, {"path": filename})
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    with pytest.raises(HTTPException) as error:
        api.research_artifact("phase16")
    assert error.value.status_code == 503
    assert "unavailable" in error.value.detail

