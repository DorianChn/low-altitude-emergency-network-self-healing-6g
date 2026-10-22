"""Phase 6 replay provenance, frozen-result integrity, and HTTP contract tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lowalt6g import phase6_api
from lowalt6g.phase6_demo import SCENARIOS


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _without_wall_clock(value: Any) -> Any:
    if isinstance(value, dict):
        ignored = {
            "decision_time_ms",
            "algorithm_decision_total_ms",
            "algorithm_decision_mean_ms",
            "algorithm_decision_p95_ms",
            "controller_observe_total_ms",
            "diagnosis",
        }
        return {key: _without_wall_clock(item) for key, item in value.items() if key not in ignored}
    if isinstance(value, list):
        return [_without_wall_clock(item) for item in value]
    return value


async def _asgi_get(app, path: str) -> tuple[int, dict[str, str], bytes]:
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

    raw_path = path.encode("ascii")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept", b"application/json")],
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in start.get("headers", [])}
    return start["status"], headers, body


def _request(path: str) -> tuple[int, dict[str, str], bytes]:
    return asyncio.run(_asgi_get(phase6_api.app, path))


def test_frozen_phase5_validation_artifacts_are_complete_and_unchanged() -> None:
    manifest_path = RESULTS / "phase5_frozen_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert _sha256(manifest_path) == "386be3c58f822e326d7283451bcc00c1d2c710c60240c65f5231968c8aa5b6d5"

    # Phase 5's source hashes are historical provenance. Later phases evolved
    # the simulator, so current source is validated by its behavior tests rather
    # than requiring it to remain byte-for-byte equal to the Phase 5 snapshot.
    assert "dynamic_simulation.py" in manifest["source_file_sha256"]

    # Pin the later Phase 9 protocol and use its protected hashes to verify the
    # frozen Phase 5 data files without changing the Phase 5 manifest.
    phase9_protocol_path = ROOT / "configs" / "phase9" / "validation_protocol_corrected.json"
    assert _sha256(phase9_protocol_path) == "1318a422e5e501fff9e083dc6deb46234e119a749464af6a22b5c867e09d0915"
    phase9_protocol = json.loads(phase9_protocol_path.read_text(encoding="utf-8"))
    protected_hashes = phase9_protocol["protected_historical_sha256"]
    phase5_artifacts = (
        "results/phase5_frozen_manifest.json",
        "results/phase5_integrity_audit.json",
        "results/phase5_validation_summary.json",
        "results/phase5_validation_dynamic_failures.json",
        "results/phase5_validation_severe_persistent_faults.json",
        "results/phase5_validation_high_mobility_rescue.json",
        "results/phase5_validation_high_load_backhaul_limit.json",
    )
    for relative_path in phase5_artifacts:
        assert relative_path in protected_hashes
        assert _sha256(ROOT / relative_path) == protected_hashes[relative_path], relative_path

    total_seeds = 0
    total_runs = 0
    for scenario_id, _, _ in SCENARIOS:
        path = RESULTS / f"phase5_validation_{scenario_id}.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        assert source["scenario_id"] == scenario_id
        assert source["experiment_role"] == "held_out_validation_frozen_algorithm"
        assert source["frozen_manifest_sha256"] == _sha256(manifest_path)
        seeds = source["seed_experiments"]
        assert len(seeds) == 20
        for item in seeds:
            assert set(item["strategies"]) == set(source["strategy_order"])
            assert len(item["strategies"]) == 5
            assert all(event.get("time_s") is not None for event in item["environment_events"])
        total_seeds += len(seeds)
        total_runs += sum(len(item["strategies"]) for item in seeds)
    audit = json.loads((RESULTS / "phase5_integrity_audit.json").read_text(encoding="utf-8"))
    assert audit["status"] == "PASS"
    assert total_seeds == audit["held_out_seed_count"] == 80
    assert total_runs == audit["strategy_run_count"] == 400


def test_phase6_replays_use_full_ticks_and_frozen_metrics() -> None:
    manifest = json.loads((RESULTS / "phase6_demo_manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "precomputed_offline_replay"
    assert manifest["live_stream"] is False
    assert manifest["frozen_manifest_sha256"] == _sha256(RESULTS / "phase5_frozen_manifest.json")

    for scenario_id, _, _ in SCENARIOS:
        item = manifest["scenarios"][scenario_id]
        replay = json.loads((RESULTS / item["artifact"]).read_text(encoding="utf-8"))
        source = json.loads((RESULTS / f"phase5_validation_{scenario_id}.json").read_text(encoding="utf-8"))
        original_seed = next(seed for seed in source["seed_experiments"] if seed["seed"] == replay["seed"])
        assert replay["seed"] == min(source["reproducibility"]["seeds"])
        assert replay["world_trace_sha256"] == original_seed["world_trace_sha256"]
        assert replay["validation"]["reconciliation"]["all_five_strategy_metrics_match_excluding_wall_clock_fields"]
        for strategy_id, strategy_run in replay["strategies"].items():
            frozen_run = original_seed["strategies"][strategy_id]
            assert len(strategy_run["state_snapshots"]) == replay["duration_s"] // replay["time_step_s"] + 1
            assert strategy_run["state_snapshots"][0]["time_s"] == 0
            assert strategy_run["state_snapshots"][-1]["time_s"] == replay["duration_s"]
            assert strategy_run["metrics"] == frozen_run["metrics"]
            assert _without_wall_clock(strategy_run["event_log"]) == _without_wall_clock(frozen_run["event_log"])
            assert all(
                frame["time_s"] == index * replay["time_step_s"]
                for index, frame in enumerate(strategy_run["state_snapshots"])
            )


def test_phase6_and_historical_api_contracts() -> None:
    status, _, body = _request("/api/demo/phase6")
    assert status == 200
    index = json.loads(body)
    assert set(index["scenarios"]) == {scenario_id for scenario_id, _, _ in SCENARIOS}

    status, _, body = _request("/api/demo/phase6/severe_persistent_faults")
    assert status == 200
    replay = json.loads(body)
    assert replay["seed"] == 7000
    assert set(replay["strategies"]) == {"A_no_recovery", "B_phase1_static_grid", "Bprime_static_grid_shared_safety", "C_rolling_horizon_mpc", "D_lexicographic_rescue_priority"}

    status, _, _ = _request("/api/demo/phase6/not-a-scenario")
    assert status == 404

    for path in (
        "/api/health",
        "/api/experiments/phase2",
        "/api/experiments/phase5",
        "/api/experiments/phase5/severe_persistent_faults",
        "/api/replay/2026",
    ):
        status, _, _ = _request(path)
        assert status == 200, path


def test_phase6_api_reports_missing_fixture_clearly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(phase6_api, "RESULTS_DIR", tmp_path)
    status, _, body = _request("/api/demo/phase6")
    assert status == 503
    assert "unavailable" in json.loads(body)["detail"].lower()
