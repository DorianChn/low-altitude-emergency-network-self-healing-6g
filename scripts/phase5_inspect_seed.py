"""Inspect one raw Phase 5 seed/policy event trace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene")
    parser.add_argument("seed", type=int)
    parser.add_argument("--strategy", default="D_lexicographic_rescue_priority")
    parser.add_argument("--phase", choices=("development", "validation"), default="development")
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--live", action="store_true", help="run this seed now instead of reading a saved artifact")
    parser.add_argument("--config-dir", type=Path, default=Path("configs/phase5"))
    args = parser.parse_args()
    if args.live:
        from lowalt6g.dynamic_config import load_dynamic_config
        from lowalt6g.dynamic_simulation import run_seed_experiment

        config = load_dynamic_config(args.config_dir / f"{args.scene}.toml")
        experiment = run_seed_experiment(
            config,
            args.seed,
            include_d=True,
            include_bprime=True,
        ).to_dict(include_latency_samples=True)
    else:
        path = args.results / f"phase5_{args.phase}_{args.scene}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        experiment = next(item for item in result["seed_experiments"] if item["seed"] == args.seed)
    run = experiment["strategies"][args.strategy]
    print("METRICS")
    print(json.dumps(run["metrics"], ensure_ascii=False, indent=2))
    print("ENVIRONMENT_EVENTS")
    for event in experiment["environment_events"]:
        if event["event_type"] in {
            "station_failure",
            "station_recovery",
            "backhaul_failure",
            "backhaul_recovery",
            "backhaul_capacity_change",
            "traffic_change",
            "user_mobility_change",
        }:
            print(json.dumps(event, ensure_ascii=False, sort_keys=True))
    print("CONTROL_AND_DRONE_EVENTS")
    for event in run["event_log"]:
        if event["event_type"] in {"optimizer_decision", "drone_energy_reserve_shutdown", "network_recovery"}:
            diagnosis = event.get("diagnosis", {})
            record = {
                key: event.get(key)
                for key in (
                    "time_s",
                    "event_type",
                    "trigger",
                    "reason",
                    "deploy",
                    "destination_km",
                    "planning_target_km",
                    "planned_sortie_energy_wh",
                    "planning_battery_wh",
                    "target_switch_count",
                    "infeasible_reasons",
                    "recovery_cause",
                )
                if key in event
            }
            if diagnosis:
                record["failed_station_ids"] = diagnosis.get("failed_station_ids")
                record["disconnected_rescue_count"] = len(diagnosis.get("disconnected_rescue_ids", []))
                record["congested_resource_ids"] = diagnosis.get("congested_resource_ids")
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        elif event["event_type"] == "drone_state_update" and event["time_s"] % 60 == 0:
            print(
                json.dumps(
                    {
                        key: event.get(key)
                        for key in (
                            "time_s",
                            "event_type",
                            "position_km",
                            "moved_km",
                            "energy_consumed_wh",
                            "battery_remaining_wh",
                            "active",
                        )
                    },
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
