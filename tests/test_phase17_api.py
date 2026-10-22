from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from lowalt6g import api
from lowalt6g.api import app


ROOT = Path(__file__).resolve().parents[1]


async def _asgi_get(path: str) -> tuple[int, bytes]:
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

    await app({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
        "raw_path": path.encode("ascii"), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept", b"application/json")],
        "client": ("testclient", 12345), "server": ("testserver", 80),
    }, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return start["status"], body


def _get(path: str) -> tuple[int, bytes]:
    return asyncio.run(_asgi_get(path))


def test_phase17_research_api_returns_allowlisted_sources_and_hashes():
    status, body = _get("/api/research/phase17")
    assert status == 200
    payload = json.loads(body)
    assert payload["dataset_id"] == "phase17"
    assert payload["model_scope"] == "software_closed_loop_and_saved_replay_validation_not_real_hil"
    assert payload["artifact"]["hardware_output_enabled"] is False
    assert payload["artifact"]["real_hardware_in_loop_status"] == "NOT_RUN_NO_VERIFIED_HARDWARE_OR_DRIVER"
    assert payload["artifact_sha256"] == hashlib.sha256((ROOT / "results/phase17_validation_summary.json").read_bytes()).hexdigest()
    expected = {
        "environment_inventory", "integrity_audit", "adapter_status", "closed_loop_run",
        "command_audit", "fault_injection_results", "offline_replay_validation",
    }
    assert set(payload["supporting_artifacts"]) == expected
    for item in payload["supporting_artifacts"].values():
        path = ROOT / item["artifact_path"]
        assert item["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase17_replay_api_evidence_contains_only_saved_discrete_frames():
    status, body = _get("/api/research/phase17")
    assert status == 200
    replay = json.loads(body)["supporting_artifacts"]["offline_replay_validation"]["artifact"]
    frames = replay["mapped_frames"]
    assert len(frames) == replay["frame_count"] == replay["walked_discrete_frames"] == 61
    assert replay["interpolated_frames"] == 0
    assert all(frame["source"]["interpolated"] is False for frame in frames)
    assert all(frame["source"]["live_device"] is False for frame in frames)


def test_phase17_does_not_change_existing_read_only_api_contract():
    assert _get("/api/health")[0] == 200
    assert _get("/api/research/phase999")[0] == 404


def test_phase17_api_reports_a_missing_support_artifact_without_fabricating_data(monkeypatch):
    with TemporaryDirectory() as directory:
        result_dir = Path(directory)
        (result_dir / "phase17_validation_summary.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(api, "RESULTS_DIR", result_dir)
        status, body = _get("/api/research/phase17")
    assert status == 503
    assert "phase17_environment_inventory.json" in json.loads(body)["detail"]


def test_phase17_machine_readable_contract_schemas_match_saved_command_records():
    config_dir = ROOT / "configs" / "phase17"
    telemetry = json.loads((config_dir / "telemetry_v1.schema.json").read_text(encoding="utf-8"))
    command = json.loads((config_dir / "command_v1.schema.json").read_text(encoding="utf-8"))
    receipt = json.loads((config_dir / "command_receipt_v1.schema.json").read_text(encoding="utf-8"))
    assert telemetry["$schema"] == command["$schema"] == receipt["$schema"]
    assert telemetry["properties"]["schema_version"]["const"] == "1.0"
    assert command["properties"]["schema_version"]["const"] == "1.0"
    assert receipt["properties"]["schema_version"]["const"] == "1.0"
    audit = json.loads((ROOT / "results" / "phase17_command_audit.json").read_text(encoding="utf-8"))
    assert audit["commands"]
    for entry in audit["commands"]:
        assert set(command["required"]).issubset(entry["command"])
        assert entry["command"]["schema_version"] == "1.0"
        assert set(receipt["required"]).issubset(entry["receipt"])
        assert entry["receipt"]["schema_version"] == "1.0"
