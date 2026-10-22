from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FINAL = ROOT / "submission" / "final"
PACKAGE = Path(os.environ.get("LOWALT6G_PACKAGE_DIR", str(FINAL / "package"))).resolve()
ARCHIVE_NAME = "6g-rescue-phase18-review-candidate-20261021.zip"
ARCHIVE = PACKAGE / ARCHIVE_NAME
OLD_MANIFEST_PATH = ROOT / "results" / "phase18" / "phase18_release_manifest.json"
MANIFEST_NAME = "PACKAGE_MANIFEST.json"
SUMS_NAME = "SHA256SUMS.txt"
PACKAGE_README_NAME = "PACKAGE_README.md"

TEXT_SUFFIXES = {".md", ".txt", ".py", ".ts", ".tsx", ".js", ".cjs", ".json", ".jsonl", ".toml", ".yaml", ".yml", ".html", ".css", ".xml", ".cmd", ".ps1", ".lock"}
SECRET_PATTERNS = [
    ("private_key_pem", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github_token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("openai_secret", re.compile(rb"sk-(?:live|proj)-[A-Za-z0-9_-]{20,}")),
    ("bearer_secret", re.compile(rb"(?i)Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/-]{24,}")),
]
FORBIDDEN_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
FORBIDDEN_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
ALREADY_COMPRESSED = {".png", ".jpg", ".jpeg", ".pdf", ".pptx", ".docx", ".xlsx", ".zip", ".gz", ".mat"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_relative(rel: str) -> Path:
    p = (ROOT / rel).resolve()
    if ROOT.resolve() not in p.parents and p != ROOT.resolve():
        raise ValueError(f"Path escapes project root: {rel}")
    return p


def scan_secret_file(path: Path, rel: str) -> list[dict[str, str]]:
    name = path.name.casefold()
    if name in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        return [{"path": rel, "rule": "credential_or_private_key_filename"}]
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return []
    matches: list[dict[str, str]] = []
    tail = b""
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            chunk = tail + block
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(chunk):
                    matches.append({"path": rel, "rule": label})
            tail = chunk[-512:]
    return matches


def add_tree_files(relative_dir: str, *, only_names: set[str] | None = None) -> list[str]:
    base = ROOT / relative_dir
    if not base.exists():
        return []
    out: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if only_names is not None and path.name not in only_names:
            continue
        if relative_dir == "submission/final" and "submission/final/package" in rel:
            continue
        out.append(rel)
    return out


def package_sources() -> tuple[list[str], list[str]]:
    old = json.loads(OLD_MANIFEST_PATH.read_text(encoding="utf-8"))
    source_paths = [item["path"] for item in old["items"]]
    missing = [rel for rel in source_paths if not safe_relative(rel).is_file()]
    if missing:
        raise FileNotFoundError("Old release allowlist source files missing: " + ", ".join(missing[:12]))

    # Competition artifacts are added explicitly; audit working files and source backups stay out.
    final_root_files = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(FINAL.iterdir())
        if p.is_file() and p.suffix.casefold() in {".md", ".docx", ".pdf", ".pptx", ".mp4"}
    ]
    development_log_paths = [
        path.relative_to(ROOT).as_posix()
        for path in sorted(ROOT.glob("DEVELOPMENT_LOG_PHASE*.md"))
        if path.is_file()
    ]
    # The historical release allowlist predates several frontend build and test
    # configuration files. Include the complete frontend source tree, while
    # excluding generated installs/builds and browser-test output.
    frontend_root = ROOT / "frontend"
    frontend_generated_parts = {
        "node_modules",
        "dist",
        ".vite",
        "coverage",
        "test-results",
        "playwright-report",
        "playwright-output",
        ".cache",
    }
    frontend_paths = []
    for path in sorted(frontend_root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(frontend_root).parts
        if any(part in frontend_generated_parts for part in relative_parts):
            continue
        frontend_paths.append(path.relative_to(ROOT).as_posix())
    runtime_asset_paths = [
        "assets/mumbai-night-city-18219784390.jpg",
    ]
    missing_runtime_assets = [rel for rel in runtime_asset_paths if not safe_relative(rel).is_file()]
    if missing_runtime_assets:
        raise FileNotFoundError("Required runtime assets missing: " + ", ".join(missing_runtime_assets))
    phase18_runtime_support = add_tree_files("results/phase18")
    asset_paths = add_tree_files("submission/final/assets")
    screenshot_paths = add_tree_files("submission/final/audit/screenshots")
    preview_paths = add_tree_files("submission/final/audit/presentation-previews")
    log_names = {
        "pytest-final-rerun.log",
        "vitest-final.log",
        "lint-final.log",
        "build-final.log",
        "playwright-final.log",
        "windows-startup-final.log",
        "npm-audit-final.json",
        "uv-audit-final-clean.json",
        "uv-audit-final-clean.stderr.txt",
        "impeccable-final.json",
        "presentation-render-final.log",
        "package-uv-sync.log",
        "package-python-test-final.log",
        "package-npm-ci.log",
        "package-vitest.log",
        "package-lint-final.log",
        "package-build-final.log",
        "package-playwright-final.log",
        "package-windows-startup-final.log",
        "package-api-smoke-final.log",
        "package-extracted-uv-sync.log",
        "package-extracted-pytest.log",
        "package-extracted-npm-ci.log",
        "package-extracted-vitest.log",
        "package-extracted-lint.log",
        "package-extracted-build.log",
        "package-extracted-playwright.log",
        "package-extracted-windows-startup.log",
        "video-encode-final.log",
        "evidence-pdf-render-final.log",
        "package-build-missing-asset.log",
        "package-python-test-missing-api.log",
        "package-python-test.log",
        "package-build.log",
    }
    log_paths = add_tree_files("submission/final/audit/logs", only_names=log_names)
    audit_paths = []
    for rel in [
        "submission/final/audit/history_integrity.json",
        "submission/final/audit/PACKAGE_VALIDATION_LOG.md",
        "submission/final/audit/video_recording_plan.json",
        "submission/final/audit/generate_video_narration.ps1",
        "submission/final/audit/record_demo_video.mjs",
        "submission/final/audit/generate_evidence_pdf.py",
        "submission/final/audit/evidence_material_render_source.html",
        "submission/final/audit/build_candidate_package.py",
        "submission/final/audit/verify_candidate_package.py",
    ]:
        if (ROOT / rel).is_file():
            audit_paths.append(rel)
    all_paths = sorted(set(source_paths + development_log_paths + frontend_paths + runtime_asset_paths + phase18_runtime_support + final_root_files + asset_paths + screenshot_paths + preview_paths + log_paths + audit_paths))
    if any(rel.startswith("submission/final/package/") for rel in all_paths):
        raise ValueError("Package recursion detected")
    return all_paths, old["excluded_files"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--copy-only", action="store_true", help="assemble and hash a disposable test staging tree without creating a ZIP")
    args = parser.parse_args()
    PACKAGE.mkdir(parents=True, exist_ok=True)
    if any(PACKAGE.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty package directory: {PACKAGE}")
    paths, excluded_raw = package_sources()

    package_readme = """# 6G / RESCUE 本地审阅候选包\n\n状态：本地审阅候选，不是正式发布，也未提交赛事平台。\n\n## 结构与启动\n\n压缩包根目录保留项目相对路径。Windows 11 上解压后，可在项目根目录运行 `scripts\\start_demo.cmd`；也可运行 `scripts\\start_demo.ps1`。服务地址由启动脚本分配并输出，请使用该次启动返回的地址，不要依赖历史报告中的端口。\n\n项目依赖清单为 `uv.lock` 与 `frontend/package-lock.json`。本候选不包含 Python/Node 运行时、虚拟环境、`node_modules` 或第三方安装缓存。完整本地测试/API环境安装命令为 `uv sync --frozen --offline --all-extras --all-groups`，前端依赖为 `npm ci --offline --prefix frontend`。离线机器需预先安装兼容运行时并具备锁定依赖缓存。本机隔离测试使用了此电脑已有的 uv/npm 缓存；这不等同于全新无缓存 Windows 设备。\n\n包内包含预生成离散实验回放、演示 MP4 浏览器录屏和佐证材料 PDF，现场展示不需要重新运行数百次实验。视频播放项目页面与已保存仿真 JSON，不是实时物理网络遥测；Windows SAPI 合成旁白不代表参赛团队的人工陈述。\n\n## 数据与再现范围\n\n压缩包沿用旧 Phase 18 候选的 446 项源文件白名单，并收录本次正式材料、审计截图和最终测试日志。14 个原始 Mendeley 工作簿/MAT 源文件未复制；其 DOI、许可和逐文件哈希保留在项目数据谱系中。若要从原始公开数据重新执行完整 Phase 15 处理，应依官方数据来源另行获取并核验该数据包。清洗数据、校准结果、配置和脚本已包含。\n\n文件大小和 SHA-256 见 `PACKAGE_MANIFEST.json` 与 `SHA256SUMS.txt`。清单不包含自身、校验和文件及压缩包，避免循环哈希；校验和文件包含清单哈希。\n\n## 安全与提交限制\n\n仓库没有根级 LICENSE/COPYING/NOTICE，源码权属和许可选择仍待权利人确认。第三方图片和数据的署名/再分发范围见包内 `submission/final/SECURITY_AUDIT.md`、`DATA_PROVENANCE.md`。公开、提交、补充队伍身份、原创声明及 AI 辅助披露须由队伍人工确认。\n\n正式比赛当前截止信息和视频规格见 `submission/final/OFFICIAL_COMPETITION_REFERENCES.md`；提交前应再次核对赛事系统。此包没有自动填写身份资料、上传作品、提交报名、改许可证、执行射频发射或控制设备。\n\n## 研究边界\n\n这是面向 IMT-2030 研究主题的抽象仿真与软件验证原型，不是真实 6G 网络测试；确定性规则/优化策略不是训练型机器学习。目标设备校准、真实 HIL、外场测量、第二台设备和断网现场验收仍未完成。\n"""
    readme_path = PACKAGE / PACKAGE_README_NAME
    readme_path.write_text(package_readme, encoding="utf-8")

    secret_hits = []
    for rel in paths:
        source = safe_relative(rel)
        secret_hits.extend(scan_secret_file(source, rel))
    if secret_hits:
        raise RuntimeError("Credential scan blocked packaging: " + json.dumps(secret_hits, ensure_ascii=False))

    items = []
    for rel in paths:
        source = safe_relative(rel)
        destination = PACKAGE / Path(rel)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        items.append({"path": rel, "size_bytes": destination.stat().st_size, "sha256": digest(destination)})

    items.append({"path": PACKAGE_README_NAME, "size_bytes": readme_path.stat().st_size, "sha256": digest(readme_path)})

    excluded_paths = set(excluded_raw)
    accidental = sorted(rel for rel in paths if rel in excluded_paths)
    if accidental:
        raise RuntimeError("Excluded raw public dataset copied into package: " + ", ".join(accidental))

    metadata = {
        "schema_version": "1.0",
        "candidate_id": "6g-rescue-phase18-review-candidate-20261021",
        "status": "LOCAL_REVIEW_CANDIDATE_NOT_SUBMITTED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_branch": "phase18-final-audit-delivery",
        "source_head": "7d3eb100ac567aedd7edb462aab7ad1125a3fbb5",
        "source_worktree_changes_included": True,
        "source_worktree_was_clean": False,
        "historical_phase18_manifest": "results/phase18/phase18_release_manifest.json",
        "historical_manifest_modified": False,
        "historical_allowlist_file_count": 446,
        "additional_support_files": sorted(set(paths) - {item["path"] for item in json.loads(OLD_MANIFEST_PATH.read_text(encoding="utf-8"))["items"]}),
        "excluded_raw_public_dataset_files": excluded_raw,
        "excluded_control_files": [MANIFEST_NAME, SUMS_NAME, ARCHIVE_NAME],
        "files": items,
        "file_count": len(items),
        "total_size_bytes": sum(x["size_bytes"] for x in items),
        "secret_scan": {"scanner": "package builder high-confidence credential patterns", "status": "PASS", "files_scanned": len(paths), "findings": 0},
    }
    (PACKAGE / MANIFEST_NAME).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sum_lines = [f"{digest(PACKAGE / MANIFEST_NAME)}  {MANIFEST_NAME}"]
    sum_lines.extend(f"{item['sha256']}  {item['path']}" for item in items)
    (PACKAGE / SUMS_NAME).write_text("\n".join(sum_lines) + "\n", encoding="utf-8")

    if args.copy_only:
        print(json.dumps({
            "package_root": str(PACKAGE),
            "payload_file_count": len(items),
            "total_uncompressed_bytes": metadata["total_size_bytes"],
            "secret_scan": metadata["secret_scan"],
            "archive_created": False,
        }, ensure_ascii=False, indent=2))
        return

    if ARCHIVE.exists():
        raise FileExistsError(f"Refusing to overwrite archive: {ARCHIVE}")
    with zipfile.ZipFile(ARCHIVE, "w", allowZip64=True) as zf:
        files = [p for p in PACKAGE.rglob("*") if p.is_file() and p != ARCHIVE]
        for file in sorted(files):
            rel = file.relative_to(PACKAGE).as_posix()
            method = zipfile.ZIP_STORED if file.suffix.casefold() in ALREADY_COMPRESSED else zipfile.ZIP_DEFLATED
            zf.write(file, rel, compress_type=method, compresslevel=6 if method == zipfile.ZIP_DEFLATED else None)
    with zipfile.ZipFile(ARCHIVE) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"Zip CRC failure at {bad}")
        archive_items = zf.infolist()
    print(json.dumps({
        "package_root": str(PACKAGE),
        "archive": str(ARCHIVE),
        "payload_file_count": len(items),
        "total_uncompressed_bytes": metadata["total_size_bytes"],
        "archive_file_count": len(archive_items),
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_sha256": digest(ARCHIVE),
        "zip_crc": "PASS",
        "excluded_raw_source_count": len(excluded_raw),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
