from __future__ import annotations

import argparse
import json

from lowalt6g.phase11_experiments import (
    freeze_confirmation_protocol,
    run_partition,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 11 matched baseline experiments")
    parser.add_argument("--partition", choices=("development", "confirmation"))
    parser.add_argument("--freeze-confirmation", action="store_true")
    parser.add_argument("--resume", action="store_true", help="resume from the Phase 11 JSONL progress log")
    args = parser.parse_args()
    if args.freeze_confirmation:
        if args.partition or args.resume:
            parser.error("--freeze-confirmation cannot be combined with --partition or --resume")
        print(json.dumps(freeze_confirmation_protocol(), ensure_ascii=False, indent=2))
        return 0
    if not args.partition:
        parser.error("choose --partition development|confirmation or --freeze-confirmation")
    result = run_partition(
        args.partition,
        resume=args.resume,
        progress=lambda message: print(message, flush=True),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "partition": result["partition"],
                "seed_count_total": result["seed_count_total"],
                "policy_run_count": result["policy_run_count"],
                "elapsed_wall_s": result["elapsed_wall_s"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
