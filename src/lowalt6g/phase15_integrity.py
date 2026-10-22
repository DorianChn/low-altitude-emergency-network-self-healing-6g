"""Hash helpers and frozen-source definition for Phase 15 calibration runs."""

from __future__ import annotations

import hashlib
from pathlib import Path


PHASE15_SOURCE_FILES = (
    "src/lowalt6g/phase15_data.py",
    "src/lowalt6g/phase15_calibration.py",
    "src/lowalt6g/phase15_integrity.py",
    "scripts/fetch_phase15_public_dataset.py",
    "scripts/prepare_phase15_dataset.py",
    "scripts/freeze_phase15_confirmation.py",
    "scripts/run_phase15_calibration.py",
    "configs/phase15/public_dataset_manifest.json",
    "configs/phase15/calibration_protocol.json",
    "configs/phase15/calibration_protocol_v2.json",
    "configs/phase14/link_budget_v1.toml",
    "src/lowalt6g/radio_link.py",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_bundle(root: Path) -> tuple[str, list[dict[str, str]]]:
    files = []
    digest = hashlib.sha256()
    for relative in PHASE15_SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"frozen Phase 15 source missing: {relative}")
        file_hash = sha256_file(path)
        files.append({"path": relative, "sha256": file_hash})
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), files
