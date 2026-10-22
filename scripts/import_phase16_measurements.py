"""Read-only audit and derived clean copy for CSV/JSON measurement records."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase16_measurement import audit_measurement_file, write_clean_measurements  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw CSV/JSON path; it is read only")
    parser.add_argument("--source-type", choices=("unknown", "target_device_measurement", "public_measurement", "literature_reference", "SYNTHETIC_TEST_ONLY"), default="unknown")
    parser.add_argument("--metadata-file", type=Path, help="JSON metadata; do not include private coordinates or secrets")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/phase16/imports")
    args = parser.parse_args()
    source = args.input.resolve()
    if not source.is_file():
        parser.error(f"input file does not exist: {source}")
    metadata = json.loads(args.metadata_file.read_text(encoding="utf-8")) if args.metadata_file else {}
    audit, cleaned_rows = audit_measurement_file(source, device_metadata=metadata, source_type=args.source_type)
    source_digest = audit["source_sha256"]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = ".clean.csv" if source.suffix.lower() == ".csv" else ".clean.json"
    clean_path = output_dir / f"{source.stem}-{source_digest[:12]}{extension}"
    audit_path = output_dir / f"{source.stem}-{source_digest[:12]}.audit.json"
    if clean_path.exists() or audit_path.exists():
        raise FileExistsError("Phase 16 import outputs already exist; choose a new output directory to preserve them")
    clean_sha256 = write_clean_measurements(clean_path, cleaned_rows)
    audit.update({
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "software_version": "phase16-import-v1",
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None,
        "cleaned_output_path": clean_path.relative_to(ROOT).as_posix() if clean_path.is_relative_to(ROOT) else clean_path.name,
        "cleaned_output_sha256": clean_sha256,
        "cleaned_rows_are_derived_not_raw": True,
    })
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": audit["import_status"],
        "source_sha256": source_digest,
        "raw_records": audit["record_count_before_cleaning"],
        "clean_records": audit["record_count_after_cleaning"],
        "rejected_records": audit["rejected_record_count"],
        "duplicate_records": audit["duplicate_record_count"],
        "source_hash_unchanged_after_read": audit["source_hash_unchanged_after_read"],
        "cleaned_output": audit["cleaned_output_path"],
        "audit_output": audit_path.relative_to(ROOT).as_posix() if audit_path.is_relative_to(ROOT) else audit_path.name,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

