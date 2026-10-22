"""Render charts from the independent Phase 8 parameter-confirmation records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase8_charts import write_phase8_charts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/phase8_sensitivity_validation_raw.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "plots/phase8_sensitivity_validation")
    args = parser.parse_args()
    paths = write_phase8_charts(args.input, args.output_dir)
    print(json.dumps({"charts": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
