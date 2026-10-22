"""Command-line interface for running reproducible benchmark scenarios."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .config import load_config
from .dynamic_config import load_dynamic_config
from .dynamic_simulation import build_seed_replay_payload
from .experiment import run_dynamic_benchmark
from .simulation import benchmark


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lowalt6g", description="Run the abstract low-altitude emergency network simulation.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="compare no recovery with rule-based UAV relay")
    run_parser.add_argument("--config", type=Path, default=Path("configs/disaster_scenario.toml"))
    run_parser.add_argument("--seed", type=int, help="override the seed from the scenario file")
    run_parser.add_argument("--output", type=Path, help="write the JSON result to this path")
    dynamic_parser = commands.add_parser(
        "run-dynamic", help="compare no recovery, the Phase 1 static grid, and rolling-horizon MPC"
    )
    dynamic_parser.add_argument("--config", type=Path, default=Path("configs/dynamic_scenario.toml"))
    dynamic_parser.add_argument(
        "--output", type=Path, default=Path("results/phase2_20_seed_results.json")
    )
    dynamic_parser.add_argument("--plots", type=Path, default=Path("plots"))
    dynamic_parser.add_argument("--no-charts", action="store_true", help="skip PNG/SVG chart generation")
    phase4_parser = commands.add_parser(
        "run-phase4",
        help="run separate development and held-out validation experiments for rescue-priority MPC",
    )
    phase4_parser.add_argument("--config", type=Path, default=Path("configs/dynamic_scenario.toml"))
    phase4_parser.add_argument("--development-seeds", default="3000-3004")
    phase4_parser.add_argument("--validation-seeds", default="4000-4019")
    phase4_parser.add_argument(
        "--development-output", type=Path, default=Path("results/phase4_development_3000_3004.json")
    )
    phase4_parser.add_argument(
        "--validation-output", type=Path, default=Path("results/phase4_validation_4000_4019.json")
    )
    phase4_parser.add_argument("--plots", type=Path, default=Path("plots"))
    phase5_parser = commands.add_parser(
        "run-phase5",
        help="run matched development and frozen held-out validation across four multi-hazard scenarios",
    )
    phase5_parser.add_argument("--phase", choices=("development", "validation", "both"), default="both")
    phase5_parser.add_argument("--config-dir", type=Path, default=Path("configs/phase5"))
    phase5_parser.add_argument("--results-dir", type=Path, default=Path("results"))
    phase5_parser.add_argument("--plots", type=Path, default=Path("plots"))
    replay_parser = commands.add_parser(
        "export-replay", help="export per-tick state for a reproducible three-policy offline replay"
    )
    replay_parser.add_argument("--config", type=Path, default=Path("configs/dynamic_scenario.toml"))
    replay_parser.add_argument("--seed", type=int, default=2026)
    replay_parser.add_argument("--output", type=Path, default=Path("results/phase3_replay_seed_2026.json"))
    args = parser.parse_args(argv)

    try:
        if args.command == "export-replay":
            dynamic_config = load_dynamic_config(args.config)
            result = build_seed_replay_payload(dynamic_config, args.seed)
            _write_json(args.output, result)
            strategies = result["strategies"]
            assert isinstance(strategies, dict)
            summary = {
                "seed": args.seed,
                "world_trace_sha256": result["world_trace_sha256"],
                "result_json": str(args.output),
                "mode": result["mode"],
                "strategies": {
                    key: {
                        "state_snapshots": len(value["state_snapshots"]),
                        "metrics": value["metrics"],
                    }
                    for key, value in strategies.items()
                },
            }
            sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            return 0

        if args.command == "run-dynamic":
            dynamic_config = load_dynamic_config(args.config)
            chart_experiments = []
            result = run_dynamic_benchmark(
                dynamic_config,
                progress=lambda index, total, seed: print(
                    f"[{index}/{total}] completed seed {seed}", file=sys.stderr, flush=True
                ),
                on_seed=chart_experiments.append,
            )
            result["artifacts"] = {"charts": []}
            _write_json(args.output, result)
            if not args.no_charts:
                from .charts import write_comparison_charts

                chart_paths = write_comparison_charts(
                    result,
                    chart_experiments,
                    args.plots,
                )
                result["artifacts"] = {"charts": [str(path) for path in chart_paths]}
                _write_json(args.output, result)
            sys.stdout.write(json.dumps(_dynamic_console_summary(result, args.output), ensure_ascii=False, indent=2) + "\n")
            return 0

        if args.command == "run-phase4":
            dynamic_config = load_dynamic_config(args.config)
            development_seeds = _parse_seed_spec(args.development_seeds)
            validation_seeds = _parse_seed_spec(args.validation_seeds)
            if len(development_seeds) < 5:
                raise ValueError("at least five independent development seeds are required")
            if len(validation_seeds) < 20:
                raise ValueError("at least twenty held-out validation seeds are required")
            overlap = set(development_seeds) & set(validation_seeds)
            baseline_seeds = set(range(2026, 2046))
            if overlap or (set(development_seeds) | set(validation_seeds)) & baseline_seeds:
                raise ValueError("development/validation seeds must not overlap each other or Phase 2 seeds 2026-2045")

            development_config = replace(dynamic_config, seeds=development_seeds)
            development = run_dynamic_benchmark(
                development_config,
                minimum_seed_count=5,
                include_d=True,
                progress=lambda index, total, seed: print(
                    f"[development {index}/{total}] completed seed {seed}", file=sys.stderr, flush=True
                ),
            )
            development["experiment_role"] = "development_parameter_selection_not_held_out_validation"
            development["seed_partition"] = {
                "development_seeds": list(development_seeds),
                "validation_seeds": list(validation_seeds),
                "phase2_baseline_overlap": [],
            }
            _write_json(args.development_output, development)

            validation_config = replace(dynamic_config, seeds=validation_seeds)
            validation = run_dynamic_benchmark(
                validation_config,
                minimum_seed_count=20,
                include_d=True,
                progress=lambda index, total, seed: print(
                    f"[validation {index}/{total}] completed seed {seed}", file=sys.stderr, flush=True
                ),
            )
            validation["experiment_role"] = "held_out_validation_frozen_algorithm"
            validation["seed_partition"] = {
                "development_seeds": list(development_seeds),
                "validation_seeds": list(validation_seeds),
                "phase2_baseline_overlap": [],
            }
            _write_json(args.validation_output, validation)

            from .charts import write_phase4_comparison_chart

            chart_paths = write_phase4_comparison_chart(validation, args.plots)
            validation["artifacts"] = {"charts": [str(path) for path in chart_paths]}
            _write_json(args.validation_output, validation)
            sys.stdout.write(
                json.dumps(
                    {
                        "development_output": str(args.development_output),
                        "validation_output": str(args.validation_output),
                        "development_seeds": list(development_seeds),
                        "validation_seeds": list(validation_seeds),
                        "validation_aggregate": validation["aggregate"],
                        "validation_paired_differences": validation["paired_differences"],
                        "charts": [str(path) for path in chart_paths],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            return 0

        if args.command == "run-phase5":
            from .phase5 import run_phase5_suite

            result = run_phase5_suite(
                args.config_dir,
                args.results_dir,
                args.plots,
                phase=args.phase,
                progress=lambda scene, index, total, seed: print(
                    f"[{scene} {index}/{total}] completed seed {seed}",
                    file=sys.stderr,
                    flush=True,
                ),
            )
            sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            return 0

        config = load_config(args.config)
        if args.seed is not None:
            config = replace(config, seed=args.seed)
            config.validate()
        runs = benchmark(config)
        effective_config = config.to_dict()
        canonical_config = json.dumps(effective_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        result = {
            "schema_version": "1.0",
            "project_version": __version__,
            "scenario_name": config.scenario_name,
            "model_scope": "abstract_6g_research_simulation_not_real_network_test",
            "reproducibility": {
                "seed": config.seed,
                "effective_config_sha256": hashlib.sha256(canonical_config).hexdigest(),
                "time_step_s": config.time_step_s,
                "duration_s": config.duration_s,
            },
            "configuration": effective_config,
            "runs": {name: run.to_dict() for name, run in runs.items()},
            "rule_based_minus_no_recovery": _deltas(runs["no_recovery"].metrics, runs["rule_based_uav_relay"].metrics),
        }
        serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        sys.stdout.write(serialized)
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
        return 2


def _dynamic_console_summary(result: dict[str, object], output_path: Path) -> dict[str, object]:
    aggregate = result["aggregate"]
    assert isinstance(aggregate, dict)
    strategies: dict[str, object] = {}
    for key, group in aggregate.items():
        assert isinstance(group, dict)
        metrics = group["metrics"]
        recovery = group["network_recovery"]
        latency = group["latency_conditioned_on_success"]
        strategies[key] = {
            "connection_success_rate": metrics["user_connection_success_rate"]["mean"],
            "rescue_service_success_rate": metrics["rescue_user_service_success_rate"]["mean"],
            "recovery_success_rate": recovery["success_rate"],
            "recovered_only_time_s": recovery["recovered_only_time_s"]["mean"],
            "pooled_average_latency_ms": latency["pooled_average_ms"],
            "pooled_p95_latency_ms": latency["pooled_p95_ms"],
            "mean_energy_wh": metrics["drone_energy_consumed_wh"]["mean"],
            "mean_decision_time_ms": metrics["algorithm_decision_total_ms"]["mean"],
        }
    return {
        "seed_count": result["reproducibility"]["seed_count"],
        "result_json": str(output_path),
        "charts": result.get("artifacts", {}).get("charts", []),
        "strategies": strategies,
    }


def _write_json(path: Path, result: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def _parse_seed_spec(value: str) -> tuple[int, ...]:
    """Parse inclusive ranges (3000-3004) or comma-separated seed IDs."""
    if "-" in value and "," not in value:
        start_text, end_text = value.split("-", maxsplit=1)
        start, end = int(start_text), int(end_text)
        if end < start:
            raise ValueError("seed range end must be greater than or equal to its start")
        return tuple(range(start, end + 1))
    seeds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not seeds or len(set(seeds)) != len(seeds) or min(seeds) < 0:
        raise ValueError("seed list must contain unique non-negative integers")
    return seeds


def _deltas(baseline: dict[str, int | float | None], recovery: dict[str, int | float | None]) -> dict[str, float | None]:
    keys = (
        "network_coverage_rate",
        "user_connection_success_rate",
        "rescue_user_service_success_rate",
        "average_communication_latency_ms",
    )
    result: dict[str, float | None] = {}
    for key in keys:
        before, after = baseline[key], recovery[key]
        result[key] = round(after - before, 6) if before is not None and after is not None else None
    before_recovery = baseline["network_recovery_time_s"]
    after_recovery = recovery["network_recovery_time_s"]
    result["network_recovery_time_s"] = (
        float(after_recovery - before_recovery)
        if isinstance(before_recovery, (int, float)) and isinstance(after_recovery, (int, float))
        else None
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
