from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "phase18" / "phase18_release_manifest.json"
VERSION = "6g-rescue-phase18-rc1"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, check=False, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def included_paths() -> set[Path]:
    paths: set[Path] = set()
    explicit = [
        "README.md", "pyproject.toml", "uv.lock",
        "start-demo.cmd", "scripts/start_demo.cmd", "scripts/start_demo.ps1",
        "scripts/run_phase18_final_audit.py", "scripts/build_phase18_validation_summary.py",
        "scripts/build_phase18_release_manifest.py",
        "scripts/verify_phase18_release_manifest.py",
        "frontend/package.json", "frontend/package-lock.json", "frontend/index.html",
        "frontend/vite.config.ts", "frontend/playwright.config.ts", "frontend/vitest.config.ts",
    ]
    for value in explicit:
        path = ROOT / value
        if path.is_file():
            paths.add(path)

    for pattern in ("PHASE*_REPORT.md", "PHASE10_MODEL_DESIGN.md", "PHASE11_ALGORITHM_DESIGN.md", "PHASE12_*.md", "PHASE18_*.md"):
        paths.update(path for path in ROOT.glob(pattern) if path.is_file())

    for directory in ("src/lowalt6g", "tests", "configs", "scripts", "frontend/src", "frontend/e2e", "deliverables/phase18", "plots", "results"):
        base = ROOT / directory
        if base.is_dir():
            paths.update(path for path in base.rglob("*") if path.is_file())

    # The manifest cannot contain its own digest. It includes the generated
    # summary and test/screenshot evidence, but no public raw data is copied in.
    paths.discard(OUT)
    return {
        path for path in paths
        if not any(part in {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "playwright-report", "test-results"} for part in path.parts)
    }


def excluded_public_sources() -> list[str]:
    manifest_path = ROOT / "configs" / "phase15" / "public_dataset_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_id = manifest.get("dataset_id", "")
    return [f"data/phase15/raw/{dataset_id}/{item['filename']}" for item in manifest.get("files", [])]


def main() -> int:
    items = []
    for path in sorted(included_paths(), key=lambda item: item.relative_to(ROOT).as_posix()):
        relative = path.relative_to(ROOT).as_posix()
        items.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": digest(path),
            "file_type": path.suffix.lower() or "no_extension",
            "release_included": True,
            "frozen_historical_data": relative.startswith("results/") and not relative.startswith("results/phase18/"),
        })

    phase18 = ROOT / "results" / "phase18"
    phase18.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "phase": "phase18_local_release_candidate",
        "version": VERSION,
        "release_note": "Local review candidate only; not a Git tag, signed release, public archive, or device-validated product.",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_self_hash_included": False,
        "git_snapshot": {
            "branch": git("branch", "--show-current"),
            "head": git("rev-parse", "HEAD"),
            "working_tree_status_entries": len(git("status", "--porcelain=v1", "-uall").splitlines()),
            "commit_created": False,
            "tag_created": False,
            "remote_push_performed": False,
        },
        "file_count": len(items),
        "total_size_bytes": sum(item["size_bytes"] for item in items),
        "items": items,
        "excluded_files": excluded_public_sources(),
        "exclusion_reason": "Raw public dataset source files are referenced by their official provenance manifest and hash-audited in place; they are not copied into this local candidate manifest.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"version": VERSION, "file_count": payload["file_count"], "size_bytes": payload["total_size_bytes"], "excluded_public_source_count": len(payload["excluded_files"]), "manifest": OUT.relative_to(ROOT).as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
