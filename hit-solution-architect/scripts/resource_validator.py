"""Read-only validator for a skill resource manifest and declared resources.

The validator never creates, merges, repairs, or rewrites resources. It checks
path containment before reading a declared file, normalizes UTF-8 text to LF
when requested by the manifest, verifies SHA-256 hashes, and rejects empty or
placeholder-only declared resources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "2.0"
EXIT_OK = 0
EXIT_CONTENT_FAILURE = 1
EXIT_RUNTIME_FAILURE = 2
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv"}
PLACEHOLDER_ONLY_RE = re.compile(
    r"^(?:<!--\s*(?:placeholder|todo|tbd)\s*-->|(?:placeholder|todo|tbd))$",
    re.IGNORECASE | re.DOTALL,
)


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def runtime_failure_report(target_file: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "resource_validator",
        "target_file": target_file,
        "status": "fail",
        "automated_checks": "not_run",
        "errors": [{"code": code, "message": message}],
        "warnings": [],
        "review": [],
        "summary": {"error_count": 1, "warning_count": 0, "review_count": 0},
    }


def _safe_path(root: Path, declared_path: Any) -> tuple[Path | None, dict[str, Any] | None]:
    if not isinstance(declared_path, str) or not declared_path.strip():
        return None, {"code": "E_INVALID_RESOURCE_PATH", "message": "资源路径必须是非空字符串。"}
    relative = Path(declared_path)
    if relative.is_absolute():
        return None, {
            "code": "E_PATH_OUTSIDE_SKILL",
            "path": declared_path,
            "message": "资源清单不得声明绝对路径。",
        }
    root_resolved = root.resolve(strict=False)
    resolved = (root / relative).resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, {
            "code": "E_PATH_OUTSIDE_SKILL",
            "path": declared_path,
            "message": "资源路径解析后越出技能目录。",
        }
    return resolved, None


def _hash_bytes(raw: bytes, *, normalize_lf: bool) -> str:
    normalized = raw
    if normalize_lf:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            normalized = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _resource_state(raw: bytes, suffix: str) -> str:
    if not raw:
        return "empty"
    if suffix.lower() not in TEXT_SUFFIXES:
        return "ok"
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return "ok"
    if not text:
        return "empty"
    if PLACEHOLDER_ONLY_RE.fullmatch(text):
        return "placeholder"
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    if not visible:
        return "placeholder"
    return "ok"


def _iter_declared_hashes(manifest: dict[str, Any]) -> list[tuple[str, Any, str]]:
    declared: list[tuple[str, Any, str]] = []
    for collection in ("top_level_file_hashes", "resource_file_hashes"):
        entries = manifest.get(collection, [])
        if not isinstance(entries, list):
            declared.append((collection, None, ""))
            continue
        for entry in entries:
            if isinstance(entry, dict):
                declared.append((collection, entry.get("path"), entry.get("sha256", "")))
            else:
                declared.append((collection, None, ""))
    return declared


def _actual_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    )


def validate_manifest(manifest: dict[str, Any], *, manifest_path: Path, skill_root: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checked_files = 0
    normalize_lf = manifest.get("text_hash_normalization") == "LF"

    if manifest.get("hash_algorithm", "SHA-256").upper() != "SHA-256":
        errors.append(
            {
                "code": "E_UNSUPPORTED_HASH_ALGORITHM",
                "message": "仅支持 SHA-256 资源清单。",
            }
        )
    normalization = manifest.get("text_hash_normalization")
    if normalization not in (None, "LF"):
        errors.append(
            {
                "code": "E_UNSUPPORTED_TEXT_NORMALIZATION",
                "message": "text_hash_normalization 只支持 LF 或不设置。",
            }
        )

    declarations = _iter_declared_hashes(manifest)
    seen_paths: set[str] = set()
    resource_paths: set[str] = set()
    for collection, declared_path, expected_hash in declarations:
        if declared_path is None:
            errors.append(
                {
                    "code": "E_INVALID_MANIFEST_ENTRY",
                    "collection": collection,
                    "message": "哈希条目必须包含 path 和 sha256。",
                }
            )
            continue
        normalized_declared = Path(str(declared_path)).as_posix()
        if normalized_declared in seen_paths:
            errors.append(
                {
                    "code": "E_DUPLICATE_MANIFEST_PATH",
                    "path": normalized_declared,
                    "message": "资源路径在哈希清单中重复。",
                }
            )
            continue
        seen_paths.add(normalized_declared)
        if collection == "resource_file_hashes":
            resource_paths.add(normalized_declared)
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            errors.append(
                {
                    "code": "E_INVALID_EXPECTED_HASH",
                    "path": normalized_declared,
                    "message": "sha256 必须是 64 位十六进制字符串。",
                }
            )
            continue

        path, path_error = _safe_path(skill_root, declared_path)
        if path_error:
            errors.append(path_error)
            continue
        assert path is not None
        if not path.exists() or not path.is_file():
            errors.append(
                {
                    "code": "E_RESOURCE_MISSING",
                    "path": normalized_declared,
                    "message": "清单声明的文件不存在或不是普通文件。",
                }
            )
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(
                {
                    "code": "E_RESOURCE_READ",
                    "path": normalized_declared,
                    "message": str(exc),
                }
            )
            continue
        checked_files += 1
        actual_hash = _hash_bytes(raw, normalize_lf=normalize_lf)
        if actual_hash.lower() != expected_hash.lower():
            errors.append(
                {
                    "code": "E_HASH_MISMATCH",
                    "path": normalized_declared,
                    "expected": expected_hash.lower(),
                    "actual": actual_hash,
                    "message": "资源内容与清单哈希不一致。",
                }
            )
        if collection == "resource_file_hashes":
            state = _resource_state(raw, path.suffix)
            if state == "empty":
                errors.append(
                    {
                        "code": "E_RESOURCE_EMPTY",
                        "path": normalized_declared,
                        "message": "声明资源为空。",
                    }
                )
            elif state == "placeholder":
                errors.append(
                    {
                        "code": "E_RESOURCE_PLACEHOLDER",
                        "path": normalized_declared,
                        "message": "声明资源只有 placeholder/TODO 内容。",
                    }
                )

    top_level_files = manifest.get("top_level_files", [])
    if not isinstance(top_level_files, list):
        errors.append(
            {
                "code": "E_INVALID_TOP_LEVEL_FILES",
                "message": "top_level_files 必须是数组。",
            }
        )
    else:
        top_hash_paths = {
            Path(str(path)).as_posix()
            for collection, path, _ in declarations
            if collection == "top_level_file_hashes" and path is not None
        }
        declared_top_paths = {
            Path(str(path)).as_posix() for path in top_level_files if isinstance(path, str)
        }
        if top_hash_paths != declared_top_paths:
            errors.append(
                {
                    "code": "E_TOP_LEVEL_FILE_SET_MISMATCH",
                    "listed_only": sorted(declared_top_paths - top_hash_paths),
                    "hashed_only": sorted(top_hash_paths - declared_top_paths),
                    "message": "top_level_files 与 top_level_file_hashes 的路径集合不一致。",
                }
            )
    skill_md = manifest.get("skill_md")
    skill_md_hash = manifest.get("skill_md_sha256")
    if skill_md or skill_md_hash:
        matching = [
            expected
            for _, path, expected in declarations
            if path == skill_md and isinstance(expected, str)
        ]
        if not matching or not isinstance(skill_md_hash, str) or matching[0].lower() != skill_md_hash.lower():
            errors.append(
                {
                    "code": "E_SKILL_HASH_INCONSISTENT",
                    "message": "skill_md_sha256 与对应文件哈希条目不一致。",
                }
            )

    top_directories = manifest.get("top_level_directories", [])
    if not isinstance(top_directories, list):
        errors.append(
            {
                "code": "E_INVALID_DIRECTORY_LIST",
                "message": "top_level_directories 必须是数组。",
            }
        )
        top_directories = []
    for declared_directory in top_directories:
        directory, path_error = _safe_path(skill_root, declared_directory)
        if path_error:
            errors.append(path_error)
            continue
        assert directory is not None
        if not directory.exists() or not directory.is_dir():
            errors.append(
                {
                    "code": "E_RESOURCE_DIRECTORY_MISSING",
                    "path": str(declared_directory),
                    "message": "声明的资源目录不存在。",
                }
            )
            continue
        for actual_file in _actual_files(directory):
            relative = actual_file.relative_to(skill_root.resolve(strict=False)).as_posix()
            if relative not in resource_paths:
                errors.append(
                    {
                        "code": "E_UNDECLARED_RESOURCE",
                        "path": relative,
                        "message": "资源目录中存在未纳入哈希清单的文件。",
                    }
                )

    resource_directories = manifest.get("resource_directories", [])
    if not isinstance(resource_directories, list):
        errors.append(
            {
                "code": "E_INVALID_DIRECTORY_COUNTS",
                "message": "resource_directories 必须是数组。",
            }
        )
        resource_directories = []
    for entry in resource_directories:
        if not isinstance(entry, dict):
            errors.append(
                {
                    "code": "E_INVALID_DIRECTORY_COUNT_ENTRY",
                    "message": "目录计数条目必须是对象。",
                }
            )
            continue
        directory, path_error = _safe_path(skill_root, entry.get("name"))
        if path_error:
            errors.append(path_error)
            continue
        assert directory is not None
        if not directory.exists() or not directory.is_dir():
            continue
        expected_count = entry.get("file_count")
        actual_count = len(_actual_files(directory))
        if not isinstance(expected_count, int) or expected_count != actual_count:
            errors.append(
                {
                    "code": "E_DIRECTORY_COUNT_MISMATCH",
                    "path": str(entry.get("name")),
                    "expected": expected_count,
                    "actual": actual_count,
                    "message": "资源目录文件数与清单不一致。",
                }
            )

    dependencies = manifest.get("declared_local_dependencies", [])
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                errors.append(
                    {
                        "code": "E_INVALID_DEPENDENCY_ENTRY",
                        "message": "本地依赖条目必须是对象。",
                    }
                )
                continue
            dependency_path, path_error = _safe_path(skill_root, dependency.get("path"))
            if path_error:
                errors.append(path_error)
                continue
            assert dependency_path is not None
            if not dependency_path.exists() or not dependency_path.is_file():
                errors.append(
                    {
                        "code": "E_DEPENDENCY_MISSING",
                        "path": str(dependency.get("path")),
                        "message": "声明的本地依赖不存在。",
                    }
                )
                continue
            declared_exists = dependency.get("exists")
            if declared_exists is not None and declared_exists is not True:
                errors.append(
                    {
                        "code": "E_DEPENDENCY_STATE_INCONSISTENT",
                        "path": str(dependency.get("path")),
                        "message": "依赖实际存在，但清单的 exists 状态不是 true。",
                    }
                )
            dependency_hash = dependency.get("sha256")
            if dependency_hash is not None:
                if not isinstance(dependency_hash, str) or not SHA256_RE.fullmatch(dependency_hash):
                    errors.append(
                        {
                            "code": "E_INVALID_DEPENDENCY_HASH",
                            "path": str(dependency.get("path")),
                            "message": "依赖 sha256 必须是 64 位十六进制字符串。",
                        }
                    )
                    continue
                try:
                    dependency_raw = dependency_path.read_bytes()
                except OSError as exc:
                    errors.append(
                        {
                            "code": "E_DEPENDENCY_READ",
                            "path": str(dependency.get("path")),
                            "message": str(exc),
                        }
                    )
                    continue
                actual_dependency_hash = _hash_bytes(dependency_raw, normalize_lf=normalize_lf)
                if actual_dependency_hash.lower() != dependency_hash.lower():
                    errors.append(
                        {
                            "code": "E_DEPENDENCY_HASH_MISMATCH",
                            "path": str(dependency.get("path")),
                            "expected": dependency_hash.lower(),
                            "actual": actual_dependency_hash,
                            "message": "本地依赖内容与依赖条目哈希不一致。",
                        }
                    )
    else:
        errors.append(
            {
                "code": "E_INVALID_DEPENDENCY_LIST",
                "message": "declared_local_dependencies 必须是数组。",
            }
        )

    missing_dependencies = manifest.get("missing_declared_dependencies", [])
    if not isinstance(missing_dependencies, list):
        errors.append(
            {
                "code": "E_INVALID_MISSING_DEPENDENCY_LIST",
                "message": "missing_declared_dependencies 必须是数组。",
            }
        )
    elif missing_dependencies:
        errors.append(
            {
                "code": "E_DECLARED_DEPENDENCIES_MISSING",
                "instances": missing_dependencies[:50],
                "total": len(missing_dependencies),
                "message": "manifest 记录了缺失的本地依赖。",
            }
        )

    status = "fail" if errors else "warning" if warnings else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "resource_validator",
        "target_file": str(manifest_path),
        "skill_root": str(skill_root),
        "status": status,
        "automated_checks": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
        "review": [],
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "review_count": 0,
            "checked_file_count": checked_files,
            "declared_hash_count": len(declarations),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    default_manifest = Path(__file__).resolve().parents[1] / "resource-manifest.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=default_manifest)
    parser.add_argument(
        "--skill-root",
        type=Path,
        help="Skill boundary. Defaults to the manifest parent directory.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = args.manifest.resolve(strict=False)
    skill_root = (args.skill_root or manifest_path.parent).resolve(strict=False)
    try:
        manifest_path.relative_to(skill_root)
    except ValueError:
        report = runtime_failure_report(
            str(manifest_path),
            "E_MANIFEST_OUTSIDE_SKILL",
            "manifest 必须位于 --skill-root 边界内。",
        )
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE
    try:
        manifest_size = manifest_path.stat().st_size
        if manifest_size > MAX_MANIFEST_BYTES:
            raise OSError(
                f"资源清单超过 {MAX_MANIFEST_BYTES} 字节上限：{manifest_size}。"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report = runtime_failure_report(str(manifest_path), "E_MANIFEST_READ", str(exc))
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE
    if not isinstance(manifest, dict):
        report = runtime_failure_report(
            str(manifest_path), "E_MANIFEST_SCHEMA", "manifest 根节点必须是 JSON 对象。"
        )
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE

    report = validate_manifest(manifest, manifest_path=manifest_path, skill_root=skill_root)
    print(render_report(report))
    return EXIT_CONTENT_FAILURE if report["errors"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
