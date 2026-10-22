from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath

EXCLUDED_DIRS = {".runtime", ".venv", ".pytest_cache", "node_modules", "dist", "test-results", "__pycache__", ".git", ".mypy_cache", ".ruff_cache", "playwright-report", "coverage"}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def package_files(root: Path):
    for current, dirs, filenames in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS and not name.endswith(".egg-info"))
        for filename in filenames:
            path = Path(current) / filename
            relative = path.relative_to(root).as_posix()
            if relative not in {"delivery/FINAL_MANIFEST.json", "delivery/SHA256SUMS.txt"}:
                yield relative, path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "delivery" / "FINAL_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    expected = {entry["path"]: entry for entry in manifest["files"]}
    actual = dict(package_files(root))
    problems = []
    for relative in sorted(expected.keys() - actual.keys()):
        problems.append(f"missing: {relative}")
    for relative in sorted(actual.keys() - expected.keys()):
        problems.append(f"unexpected: {relative}")
    for relative in sorted(expected.keys() & actual.keys()):
        item = expected[relative]
        path = actual[relative]
        if path.stat().st_size != item["size_bytes"]:
            problems.append(f"size mismatch: {relative}")
        elif digest(path) != item["sha256"]:
            problems.append(f"SHA-256 mismatch: {relative}")
    sums = {}
    for line in (root / "delivery" / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        value, relative = line.split("  ", 1)
        sums[relative] = value.lower()
    for relative, expected_hash in sums.items():
        if relative == "delivery/FINAL_MANIFEST.json":
            path = manifest_path
        else:
            path = root / Path(*PurePosixPath(relative).parts)
        if not path.is_file() or digest(path) != expected_hash:
            problems.append(f"checksum list mismatch: {relative}")
    if problems:
        print("\n".join(problems))
        return 1
    print(f"PASS: {len(expected)} project files matched size and SHA-256; {len(sums)} checksum rows verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
