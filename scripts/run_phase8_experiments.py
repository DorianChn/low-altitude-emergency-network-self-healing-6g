"""Run or freeze the reproducible Phase 8 ablation and sensitivity protocol."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase8_experiments import (  # noqa: E402
    ROOT as PROJECT_ROOT,
    freeze_validation_protocol,
    run_stage,
)


def _progress(phase: str, completed: int, total: int, scenario: str, seed: int) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{now}] {phase}: {completed}/{total} seeds; {scenario} seed={seed}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("development", "validation"), help="experiment partition to run")
    parser.add_argument("--freeze-validation", action="store_true", help="freeze the confirmatory plan after development completes")
    parser.add_argument("--charts-only", action="store_true", help="regenerate validation figures from existing raw JSON")
    args = parser.parse_args()
    if sum((bool(args.phase), args.freeze_validation, args.charts_only)) != 1:
        parser.error("choose exactly one of --phase, --freeze-validation, or --charts-only")

    if args.freeze_validation:
        print(f"Frozen validation protocol: {freeze_validation_protocol()}")
        return 0

    if args.charts_only:
        raw_path = PROJECT_ROOT / "results/phase8_validation_raw.json"
        if not raw_path.is_file():
            parser.error(f"validation raw JSON is missing: {raw_path}")
        from lowalt6g.phase8_charts import write_phase8_charts

        paths = write_phase8_charts(raw_path, PROJECT_ROOT / "plots")
        print(json.dumps({"charts": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
        return 0

    started = time.perf_counter()
    result = run_stage(args.phase, progress=_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.phase == "validation":
        from lowalt6g.phase8_charts import write_phase8_charts

        paths = write_phase8_charts(Path(result["raw"]), PROJECT_ROOT / "plots")
        print(json.dumps({"charts": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    print(f"Elapsed wall time: {time.perf_counter() - started:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
