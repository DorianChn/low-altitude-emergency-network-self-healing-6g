"""Run the auditable Phase 10 development and held-out experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase10_experiments import (  # noqa: E402
    freeze_protocol,
    run_confirmation,
    run_development,
)


def _progress(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("development", "freeze", "confirmation"),
        help="run development, freeze the protocol after review, or run held-out confirmation",
    )
    args = parser.parse_args()
    if args.action == "development":
        result = run_development(progress=_progress)
    elif args.action == "freeze":
        result = freeze_protocol()
    else:
        result = run_confirmation(progress=_progress)
    print(json.dumps({
        "action": args.action,
        "status": result.get("status", "frozen_before_confirmation"),
        "raw_output": result.get("raw_output"),
        "summary_output": result.get("summary_output"),
        "protocol_sha256": result.get("protocol_sha256"),
        "seed_count_total": result.get("seed_count_total"),
        "policy_run_count": result.get("policy_run_count"),
        "elapsed_wall_s": result.get("elapsed_wall_s"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
