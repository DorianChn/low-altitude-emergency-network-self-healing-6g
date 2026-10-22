"""Capture Phase 5-14 artifacts before adding Phase 15 outputs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs/phase15/protected_artifacts_baseline.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"refusing to replace existing baseline: {OUT.relative_to(ROOT)}")
    phase14_audit_path = ROOT / "results/phase14_integrity_audit.json"
    audit = json.loads(phase14_audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS":
        raise SystemExit("Phase 14 integrity audit is not PASS; capture blocked")

    protected: dict[str, str] = {}
    for item in audit.get("historical_frozen_json", {}).get("items", []):
        if item.get("matches") is not True:
            raise SystemExit(f"historical baseline mismatch: {item.get('path')}")
        protected[str(item["path"])] = str(item["actual_sha256"])

    phase14_files: set[Path] = {phase14_audit_path}
    for pattern in (
        "PHASE14_*.md",
        "configs/phase14/**/*",
        "results/phase14_*",
        "plots/phase14/**/*",
    ):
        phase14_files.update(path for path in ROOT.glob(pattern) if path.is_file())
    phase14_files.update(
        ROOT / path
        for path in (
            "src/lowalt6g/radio_link.py",
            "src/lowalt6g/phase14_radio.py",
            "src/lowalt6g/phase14_experiments.py",
            "scripts/run_phase14_experiments.py",
            "scripts/phase14_integrity_audit.py",
            "scripts/plot_phase14_results.py",
            "scripts/verify_phase14_legacy_reproduction.py",
        )
        if (ROOT / path).is_file()
    )
    for path in sorted(phase14_files):
        protected[path.relative_to(ROOT).as_posix()] = sha256(path)

    result = {
        "schema_version": "1.0",
        "phase": "phase15_link_calibration_pipeline",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch_at_capture": git("branch", "--show-current"),
        "phase14_base_commit": git("rev-parse", "phase14-radio-link-model"),
        "phase14_integrity_audit_sha256": sha256(phase14_audit_path),
        "phase14_integrity_audit_status": audit.get("status"),
        "historical_phase5_8_9_10_11_count": len(audit.get("historical_frozen_json", {}).get("items", [])),
        "protected_file_count": len(protected),
        "files": [{"path": path, "sha256": value} for path, value in sorted(protected.items())],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("branch_at_capture", "phase14_base_commit", "historical_phase5_8_9_10_11_count", "protected_file_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
