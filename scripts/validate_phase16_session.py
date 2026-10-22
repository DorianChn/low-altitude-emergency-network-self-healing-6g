"""Validate a saved Phase 16 measurement session plan without starting acquisition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase16_measurement import validate_experiment_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="measurement-session JSON file")
    parser.add_argument("--report", type=Path, help="write a new JSON validation report")
    parser.add_argument("--strict", action="store_true", help="exit with status 2 when the plan is not ready")
    args = parser.parse_args()
    source = args.config.resolve()
    if not source.is_file():
        parser.error(f"session config does not exist: {source}")
    raw = source.read_bytes()
    config = json.loads(raw.decode("utf-8"))
    result = validate_experiment_config(config)
    report = {
        "schema_version": "1.0",
        "phase": "phase16_measurement_session_validation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else source.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        **result,
        "acquisition_started": False,
        "hardware_accessed": False,
    }
    if args.report:
        output = args.report.resolve()
        if output == source or output.exists():
            parser.error("report path must be a new file and must not overwrite the input or existing files")
        report["report_path"] = output.relative_to(ROOT).as_posix() if output.is_relative_to(ROOT) else output.name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 2 if args.strict and not result["ready_for_measurement"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
