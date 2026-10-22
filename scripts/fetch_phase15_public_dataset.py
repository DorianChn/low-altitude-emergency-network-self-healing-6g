"""Fetch a small, CC BY 4.0 A2G measurement subset and verify publisher hashes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "configs/phase15/public_dataset_manifest.json"
DATA_DIR = ROOT / "data/phase15/raw/mendeley_8p6r8ft4fz_v2"
AUDIT_PATH = ROOT / "results/phase15_dataset_download_audit.json"
MAX_BYTES = 5_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path, expected_size: int, expected_sha256: str) -> dict[str, object]:
    if target.exists():
        actual_sha = sha256_file(target)
        actual_size = target.stat().st_size
        if actual_size != expected_size or actual_sha != expected_sha256:
            raise ValueError(f"existing file differs from the verified manifest; left untouched: {target}")
        return {"status": "already_verified", "size_bytes": actual_size, "sha256": actual_sha}

    temporary = target.with_name(target.name + ".phase15-download")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "lowalt6g-phase15-research/1.0"})
            digest = hashlib.sha256()
            size = 0
            with urlopen(request, timeout=45) as response, temporary.open("wb") as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_BYTES:
                        raise ValueError(f"file exceeds Phase 15 download cap ({MAX_BYTES} bytes): {target.name}")
                    digest.update(block)
                    output.write(block)
            actual_sha = digest.hexdigest()
            if size != expected_size or actual_sha != expected_sha256:
                raise ValueError(
                    f"publisher checksum mismatch for {target.name}: size={size}, sha256={actual_sha}"
                )
            temporary.replace(target)
            return {"status": "downloaded_and_verified", "size_bytes": size, "sha256": actual_sha}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"could not fetch {target.name}: {last_error}")


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_results = []
    for item in manifest["files"]:
        filename = str(item["filename"])
        if Path(filename).name != filename:
            raise ValueError(f"unsafe filename in manifest: {filename}")
        url = (
            "https://data.mendeley.com/public-files/datasets/8p6r8ft4fz/files/"
            f"{item['file_id']}/file_downloaded"
        )
        outcome = download(url, DATA_DIR / filename, int(item["size_bytes"]), str(item["sha256"]))
        file_results.append({"filename": filename, "file_id": item["file_id"], "role": item["role"], "url": url, **outcome})

    result = {
        "schema_version": "1.0",
        "phase": "phase15_public_measurement_dataset_fetch",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_id": manifest["dataset_id"],
        "dataset_doi": manifest["doi"],
        "license": manifest["license"],
        "storage_path": DATA_DIR.relative_to(ROOT).as_posix(),
        "files": file_results,
        "status": "PASS" if len(file_results) == len(manifest["files"]) else "FAIL",
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "file_count": len(file_results), "bytes": sum(int(row["size_bytes"]) for row in file_results)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Phase 15 dataset fetch failed: {error}", file=sys.stderr)
        raise SystemExit(2)
