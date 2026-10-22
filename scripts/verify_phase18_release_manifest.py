from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "results" / "phase18" / "phase18_release_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    errors: list[str] = []
    seen: set[str] = set()
    total_bytes = 0
    checked_files = 0
    for item in items:
        relative = item.get("path", "")
        path = Path(relative)
        if not relative or path.is_absolute() or ".." in path.parts or relative in seen:
            errors.append(f"invalid or duplicate relative path: {relative}")
            continue
        seen.add(relative)
        absolute = ROOT / path
        if not absolute.is_file():
            errors.append(f"missing file: {relative}")
            continue
        size = absolute.stat().st_size
        digest = sha256(absolute)
        total_bytes += size
        checked_files += 1
        if size != item.get("size_bytes") or digest != item.get("sha256"):
            errors.append(f"content mismatch: {relative}")
        if relative.startswith("data/phase15/raw/"):
            errors.append(f"public raw source must remain outside the local candidate: {relative}")

    if payload.get("manifest_self_hash_included") is not False:
        errors.append("manifest self hash must be excluded")
    if payload.get("file_count") != len(items):
        errors.append("file_count does not match item list")
    if payload.get("total_size_bytes") != total_bytes:
        errors.append("total_size_bytes does not match the checked item list")
    if MANIFEST_PATH.relative_to(ROOT).as_posix() in seen:
        errors.append("manifest contains its own path")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "version": payload.get("version"),
        "file_count": len(items),
        "total_size_bytes": total_bytes,
        "checked_file_count": checked_files,
        "excluded_public_source_count": len(payload.get("excluded_files", [])),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
