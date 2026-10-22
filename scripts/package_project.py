from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import zipfile

EXCLUDED_DIRS = {
    ".runtime", ".venv", ".pytest_cache", "node_modules", "dist", "test-results",
    "__pycache__", ".git", ".mypy_cache", ".ruff_cache", "playwright-report", "coverage",
}


def safe_relative(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def files_to_pack(root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.endswith(".egg-info"))
        for filename in sorted(files):
            path = Path(current) / filename
            relative = path.relative_to(root).as_posix()
            yield path, relative


def create_archive(root: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for source, relative in files_to_pack(root):
            arcname = f"6G-RESCUE/{relative}"
            if not safe_relative(arcname):
                raise ValueError(f"Unsafe archive path: {arcname}")
            archive.write(source, arcname)
    with zipfile.ZipFile(destination) as archive:
        bad = archive.testzip()
        if bad:
            raise IOError(f"CRC verification failed: {bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise IOError("Duplicate paths in ZIP")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if roots != {"6G-RESCUE"}:
            raise IOError(f"Unexpected top-level entries: {roots}")
        if any(not safe_relative(name) for name in names):
            raise IOError("Unsafe ZIP path detected")
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    sidecar = destination.with_suffix(destination.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    return digest


def extract_archive(source: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            if not safe_relative(info.filename):
                raise ValueError(f"Unsafe archive path: {info.filename}")
        archive.extractall(destination)
        bad = archive.testzip()
        if bad:
            raise IOError(f"CRC verification failed: {bad}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.destination:
        print(create_archive(root, args.destination.resolve()))
    elif args.archive and args.extract_to:
        extract_archive(args.archive.resolve(), args.extract_to.resolve())
    else:
        parser.error("Choose --destination, or both --archive and --extract-to")


if __name__ == "__main__":
    main()
