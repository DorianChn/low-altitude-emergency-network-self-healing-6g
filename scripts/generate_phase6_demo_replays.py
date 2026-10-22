"""Generate Phase 6 scene replay fixtures from the frozen Phase 5 validation set."""

from lowalt6g.phase6_demo import generate_phase6_demo_replays


if __name__ == "__main__":
    result = generate_phase6_demo_replays()
    print("Generated deterministic Phase 6 demo replays:")
    for scenario_id, item in result["scenarios"].items():
        print(
            f"- {scenario_id}: seed={item['seed']} "
            f"({item['validation_seed_count']} validation seeds × 5 strategies)"
        )
    print(f"Phase 5 frozen manifest: {result['frozen_manifest_sha256']}")
