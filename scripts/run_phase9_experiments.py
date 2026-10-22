"""Run the frozen, reproducible Phase 9 experiments."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase9_experiments import (  # noqa: E402
    ROOT as PROJECT_ROOT,
    freeze_validation_protocol,
    run_confirmation,
    run_development,
    run_energy_sensitivity,
)


def _progress(stage: str, completed: int, total: int, seed: int) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{now}] {stage}: {completed}/{total} seeds; seed={seed}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("development", "confirmation", "energy-sensitivity"))
    parser.add_argument("--freeze-validation", action="store_true")
    parser.add_argument("--summary-only", choices=("development", "confirmation", "energy-sensitivity"))
    args = parser.parse_args()
    if sum((bool(args.phase), args.freeze_validation, bool(args.summary_only))) != 1:
        parser.error("choose exactly one of --phase, --freeze-validation or --summary-only")

    if args.freeze_validation:
        print(f"Frozen Phase 9 protocol: {freeze_validation_protocol()}")
        return 0

    if args.summary_only:
        if args.summary_only == "development":
            from lowalt6g.phase9_experiments import summarize_development, _atomic_write

            raw_path = PROJECT_ROOT / "results/phase9_development_raw.json"
            summary_path = PROJECT_ROOT / "results/phase9_development_summary.json"
            summary = summarize_development(json.loads(raw_path.read_text(encoding="utf-8")))
        elif args.summary_only == "confirmation":
            from lowalt6g.phase9_experiments import summarize_confirmation, _atomic_write, _write_event_timeline, write_phase9_charts

            raw_path = PROJECT_ROOT / "results/phase9_corrected_confirmation_raw.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            summary = summarize_confirmation(raw)
            _write_event_timeline(raw)
            write_phase9_charts(raw, summary)
            summary_path = PROJECT_ROOT / "results/phase9_corrected_confirmation_summary.json"
        else:
            from lowalt6g.phase9_experiments import summarize_energy_sensitivity, _atomic_write, write_energy_sensitivity_chart

            raw_path = PROJECT_ROOT / "results/phase9_corrected_energy_sensitivity_raw.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            summary = summarize_energy_sensitivity(raw)
            write_energy_sensitivity_chart(summary)
            summary_path = PROJECT_ROOT / "results/phase9_corrected_energy_sensitivity_summary.json"
        if not raw_path.is_file():
            parser.error(f"required raw results are missing: {raw_path}")
        _atomic_write(summary_path, summary)
        print(json.dumps({"summary": str(summary_path), "status": summary.get("status")}, ensure_ascii=False, indent=2))
        return 0

    started = time.perf_counter()
    if args.phase == "development":
        result = run_development(progress=_progress)
    elif args.phase == "confirmation":
        result = run_confirmation(progress=_progress)
    else:
        result = run_energy_sensitivity(progress=_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Elapsed wall time: {time.perf_counter() - started:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
