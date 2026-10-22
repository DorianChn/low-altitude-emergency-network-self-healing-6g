from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(os.environ.get("LOWALT6G_PACKAGE_DIR", str(ROOT / "submission" / "final" / "package"))).resolve()
ARCHIVE = PACKAGE / "6g-rescue-phase18-review-candidate-20261021.zip"
MANIFEST = PACKAGE / "PACKAGE_MANIFEST.json"
OUT = ROOT / "submission" / "final" / "audit" / "package_validation.json"


def digest_stream(chunks) -> str:
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in manifest["files"]}
    expected_controls = {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
    expected_names = set(expected) | expected_controls
    discrepancies = []
    archive_hash = hashlib.sha256()
    with ARCHIVE.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            archive_hash.update(chunk)

    with zipfile.ZipFile(ARCHIVE) as zf:
        bad = zf.testzip()
        if bad:
            discrepancies.append({"kind": "zip_crc", "path": bad})
        names = [info.filename for info in zf.infolist()]
        if len(names) != len(set(names)):
            discrepancies.append({"kind": "duplicate_archive_paths"})
        if set(names) != expected_names:
            discrepancies.append({"kind": "archive_inventory", "missing": sorted(expected_names-set(names))[:40], "unexpected": sorted(set(names)-expected_names)[:40]})
        for name in names:
            parts = PurePosixPath(name).parts
            if PurePosixPath(name).is_absolute() or ".." in parts or "" in parts:
                discrepancies.append({"kind": "unsafe_archive_path", "path": name})
        for rel, item in expected.items():
            try:
                with zf.open(rel) as f:
                    hasher = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hasher.update(chunk)
                        size += len(chunk)
                actual = hasher.hexdigest()
                if actual != item["sha256"] or size != item["size_bytes"]:
                    discrepancies.append({"kind": "payload_hash", "path": rel, "expected_sha256": item["sha256"], "actual_sha256": actual, "expected_size": item["size_bytes"], "actual_size": size})
            except KeyError:
                discrepancies.append({"kind": "payload_missing", "path": rel})
        # Verify the detached SHA256SUMS entries, without trying to hash the sums file into itself.
        sums = zf.read("SHA256SUMS.txt").decode("utf-8").splitlines()
        sum_entries = {}
        for line in sums:
            parts = line.split("  ", 1)
            if len(parts) == 2:
                sum_entries[parts[1]] = parts[0]
        if sum_entries.get("PACKAGE_MANIFEST.json") != hashlib.sha256(zf.read("PACKAGE_MANIFEST.json")).hexdigest():
            discrepancies.append({"kind": "manifest_detached_sum"})
        if set(sum_entries) != set(expected) | {"PACKAGE_MANIFEST.json"}:
            discrepancies.append({"kind": "detached_sum_inventory", "missing": sorted((set(expected)|{"PACKAGE_MANIFEST.json"})-set(sum_entries)), "unexpected": sorted(set(sum_entries)-(set(expected)|{"PACKAGE_MANIFEST.json"}))})
        for rel, item in expected.items():
            if sum_entries.get(rel) != item["sha256"]:
                discrepancies.append({"kind": "detached_sum_payload", "path": rel})

        # Full extraction to a fresh temp folder verifies paths and files are independently present.
        extract_root = Path(tempfile.mkdtemp(prefix="6g-rescue-phase18-review-extract-"))
        for name in names:
            target = (extract_root / Path(*PurePosixPath(name).parts)).resolve()
            if extract_root.resolve() not in target.parents:
                discrepancies.append({"kind": "extraction_path_escape", "path": name})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as source, target.open("wb") as dest:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    dest.write(chunk)
        key_paths = [
            "pyproject.toml",
            "uv.lock",
            "frontend/package.json",
            "frontend/package-lock.json",
            "scripts/start_demo.cmd",
            "scripts/start_demo.ps1",
            "submission/final/AI+6G场景设计方案.docx",
            "submission/final/答辩演示.pptx",
            "results/phase6_demo_severe_persistent_faults.json",
            "PHASE18_REPORT.md",
        ]
        missing_keys = [rel for rel in key_paths if not (extract_root / rel).is_file()]
        if missing_keys:
            discrepancies.append({"kind": "key_files_missing_after_extract", "paths": missing_keys})

    result = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive": str(ARCHIVE),
        "archive_sha256": archive_hash.hexdigest(),
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_member_count": len(names),
        "payload_file_count": len(expected),
        "payload_uncompressed_bytes": manifest["total_size_bytes"],
        "manifest_file_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "zip_crc": "PASS" if not bad else "FAIL",
        "extraction_root": str(extract_root),
        "key_files_present_after_extract": not missing_keys,
        "discrepancies": discrepancies,
        "status": "PASS" if not discrepancies else "FAIL",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if discrepancies:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
