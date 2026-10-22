"""Phase 13 read-only research-artifact API contract tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lowalt6g import api, phase6_api


ROOT = Path(__file__).resolve().parents[1]


async def _asgi_get(app_instance, path: str) -> tuple[int, bytes]:
    sent: list[dict[str, Any]] = []
    requested = False

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if requested:
            return {"type": "http.disconnect"}
        requested = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept", b"application/json")],
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
    }
    await app_instance(scope, receive, send)
    start = next(item for item in sent if item["type"] == "http.response.start")
    body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return start["status"], body


def _get(path: str) -> tuple[int, dict[str, Any]]:
    status, body = asyncio.run(_asgi_get(phase6_api.app, path))
    return status, json.loads(body)


@pytest.mark.parametrize(
    ("phase_id", "filename"),
    [
        ("phase5", "phase5_validation_summary.json"),
        ("phase8", "phase8_replication_summary.json"),
        ("phase9", "phase9_corrected_confirmation_summary.json"),
        ("phase10", "phase10_confirmation_summary.json"),
        ("phase11", "phase11_confirmation_summary.json"),
    ],
)
def test_research_endpoint_returns_unmodified_artifact_and_sha256(phase_id: str, filename: str) -> None:
    path = ROOT / "results" / filename
    source = json.loads(path.read_text(encoding="utf-8"))
    status, payload = _get(f"/api/research/{phase_id}")

    assert status == 200
    assert payload["dataset_id"] == phase_id
    assert payload["artifact_path"] == f"results/{filename}"
    assert payload["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["artifact"] == source
    assert payload["model_scope"] == "abstract_6g_research_simulation_not_real_network_test"


def test_research_endpoint_rejects_unknown_phase_and_path_input() -> None:
    status, payload = _get("/api/research/phase12")
    assert status == 404
    assert payload["detail"] == "unknown research phase"

    status, _ = _get("/api/research/..%2Fphase5")
    assert status == 404


def test_research_endpoint_reports_missing_artifact_without_substitution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    status, payload = _get("/api/research/phase11")
    assert status == 503
    assert "phase11_confirmation_summary.json" in payload["detail"]


def test_phase14_research_endpoint_includes_hashed_sensitivity_artifact(tmp_path: Path, monkeypatch) -> None:
    comparison = {"phase": "phase14_radio_link_model", "partition": "confirmation", "scenarios": {}}
    sensitivity = {"phase": "phase14_radio_link_model_sensitivity", "partition": "exploratory_development_only"}
    (tmp_path / "phase14_confirmation_summary.json").write_text(json.dumps(comparison), encoding="utf-8")
    (tmp_path / "phase14_model_sensitivity_summary.json").write_text(json.dumps(sensitivity), encoding="utf-8")
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    status, payload = _get("/api/research/phase14")

    assert status == 200
    assert payload["artifact"] == comparison
    assert payload["artifact_sha256"] == hashlib.sha256((tmp_path / "phase14_confirmation_summary.json").read_bytes()).hexdigest()
    linked = payload["supporting_artifacts"]["sensitivity"]
    assert linked["artifact"] == sensitivity
    assert linked["artifact_sha256"] == hashlib.sha256((tmp_path / "phase14_model_sensitivity_summary.json").read_bytes()).hexdigest()


def test_phase14_research_endpoint_explains_missing_sensitivity_data(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "phase14_confirmation_summary.json").write_text(json.dumps({"phase": "phase14"}), encoding="utf-8")
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    status, payload = _get("/api/research/phase14")
    assert status == 503
    assert "phase14_model_sensitivity_summary.json" in payload["detail"]


def test_phase15_research_endpoint_returns_hashed_saved_evidence(tmp_path: Path, monkeypatch) -> None:
    summary = {"phase": "phase15", "model_scope": "public_measurement_path_loss_evaluation_not_project_device_calibration"}
    holdout = {"status": "EVALUATED", "sample_count": 570}
    audit = {"status": "PASS", "row_count": 1370}
    for filename, value in (
        ("phase15_calibration_summary.json", summary),
        ("phase15_holdout_validation.json", holdout),
        ("phase15_dataset_audit.json", audit),
    ):
        (tmp_path / filename).write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)

    status, payload = _get("/api/research/phase15")

    assert status == 200
    assert payload["artifact"] == summary
    assert payload["experiment_role"] == "public_measurement_group_holdout_evaluation"
    assert payload["model_scope"] == summary["model_scope"]
    assert payload["supporting_artifacts"]["holdout_validation"]["artifact"] == holdout
    assert payload["supporting_artifacts"]["dataset_audit"]["artifact"] == audit
    assert payload["artifact_sha256"] == hashlib.sha256((tmp_path / "phase15_calibration_summary.json").read_bytes()).hexdigest()


def test_phase15_plot_endpoint_only_serves_allowlisted_saved_files(tmp_path: Path, monkeypatch) -> None:
    plot_dir = tmp_path / "plots" / "phase15"
    plot_dir.mkdir(parents=True)
    expected = b"saved plot bytes"
    (plot_dir / "phase15_fit_and_holdout.png").write_bytes(expected)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)

    response = api.phase15_plot("phase15_fit_and_holdout.png")
    assert Path(response.path) == plot_dir / "phase15_fit_and_holdout.png"
    assert Path(response.path).read_bytes() == expected

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        api.phase15_plot("../../README.md")
    assert error.value.status_code == 404


def test_phase15_research_endpoint_reports_missing_link_calibration_evidence(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "phase15_calibration_summary.json").write_text(json.dumps({"phase": "phase15"}), encoding="utf-8")
    monkeypatch.setattr(api, "RESULTS_DIR", tmp_path)
    status, payload = _get("/api/research/phase15")
    assert status == 503
    assert "phase15_holdout_validation.json" in payload["detail"]
