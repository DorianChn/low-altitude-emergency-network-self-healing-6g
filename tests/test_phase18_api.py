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


async def _get_asgi(path: str) -> tuple[int, bytes]:
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
    return asyncio.run(_get_asgi(path))


def test_phase18_api_returns_saved_summary_and_allowlisted_hashes():
    status, body = _get("/api/research/phase18")
    assert status == 200
    payload = json.loads(body)
    assert payload["dataset_id"] == "phase18"
    assert payload["experiment_role"] == "phase18_final_audit_snapshot"
    assert payload["model_scope"] == "final_research_evidence_and_local_release_candidate_audit_not_real_network_validation"
    assert payload["artifact_sha256"] == hashlib.sha256(
        (ROOT / "results/phase18/phase18_validation_summary.json").read_bytes()
    ).hexdigest()
    assert set(payload["supporting_artifacts"]) == {"integrity_audit", "evidence_manifest", "release_manifest"}
    for item in payload["supporting_artifacts"].values():
        path = ROOT / item["artifact_path"]
        assert item["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase18_api_reports_missing_supporting_evidence_without_fabrication(monkeypatch):
    with TemporaryDirectory() as directory:
        results_dir = Path(directory)
        (results_dir / "phase18").mkdir()
        (results_dir / "phase18" / "phase18_validation_summary.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(api, "RESULTS_DIR", results_dir)
        status, body = _get("/api/research/phase18")
    assert status == 503
    assert "phase18_integrity_audit.json" in json.loads(body)["detail"]


def test_phase18_does_not_change_historical_read_only_routes():
    assert _get("/api/health")[0] == 200
    assert _get("/api/research/phase17")[0] == 200
    assert _get("/api/research/phase999")[0] == 404
