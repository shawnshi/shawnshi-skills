#!/usr/bin/env python3
"""Create/verify a wheel-only manifest and render hash-locked pip input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn, Sequence


SCHEMA_VERSION = 1
HASH_ALGORITHM = "sha256"
MANIFEST_NAME = "wheelhouse-manifest.json"
WHEEL_SUFFIX = ".whl"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LOCK_LINE_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)=="
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)
WHEEL_FIELD_PATTERN = re.compile(r"^[A-Za-z0-9_.+!]+$")
WHEEL_BUILD_PATTERN = re.compile(r"^[0-9][A-Za-z0-9_.]*$")
MANIFEST_KEYS = {
    "schema_version",
    "hash_algorithm",
    "python_version",
    "platform",
    "machine",
    "requirements_lock",
    "artifacts",
}
LOCK_KEYS = {"filename", "sha256"}
ARTIFACT_KEYS = {"filename", "sha256", "size"}


class ManifestError(RuntimeError):
    """A safe, machine-readable wheelhouse integrity failure."""

    def __init__(self, code: str, detail: str, *, exit_code: int = 3) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ManifestError("invalid_arguments", message, exit_code=2)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _verify_stable_file(
    path: Path,
    before: os.stat_result,
    after: os.stat_result,
    *,
    code: str,
) -> None:
    try:
        final = path.lstat()
    except OSError as exc:
        raise ManifestError(code, path.name) from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or not stat.S_ISREG(final.st_mode)
        or _stat_signature(before) != _stat_signature(after)
        or _stat_signature(after) != _stat_signature(final)
    ):
        raise ManifestError(code, path.name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(source.fileno())
    except OSError as exc:
        raise ManifestError("file_read_failed", path.name) from exc
    _verify_stable_file(path, before, after, code="file_changed_during_hash")
    return digest.hexdigest()


def _read_bytes_stable(path: Path, *, maximum_size: int) -> bytes:
    try:
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            if before.st_size > maximum_size:
                raise ManifestError("requirements_lock_too_large", path.name)
            payload = source.read(maximum_size + 1)
            after = os.fstat(source.fileno())
    except ManifestError:
        raise
    except OSError as exc:
        raise ManifestError("requirements_lock_read_failed", path.name) from exc
    if len(payload) > maximum_size:
        raise ManifestError("requirements_lock_too_large", path.name)
    _verify_stable_file(path, before, after, code="requirements_lock_changed_during_read")
    return payload


def _runtime_identity() -> dict[str, str]:
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform.lower(),
        "machine": (platform.machine() or "unknown").lower(),
    }


def _require_regular_file(path: Path, code: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ManifestError(code, path.name)


def _valid_filename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and Path(value).name == value
    )


def _is_artifact_name(name: str) -> bool:
    return name.lower().endswith(WHEEL_SUFFIX)


def _canonical_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _wheel_version(version: str) -> str:
    return re.sub(r"[^A-Za-z0-9.!+]+", "_", version).lower()


def _read_lock(requirements_lock: Path) -> tuple[bytes, list[tuple[str, str]]]:
    _require_regular_file(requirements_lock, "requirements_lock_missing_or_unsafe")
    payload = _read_bytes_stable(requirements_lock, maximum_size=1024 * 1024)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError("requirements_lock_invalid_utf8", requirements_lock.name) from exc

    requirements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line or raw_line.startswith("#"):
            continue
        if raw_line != raw_line.strip():
            raise ManifestError("requirements_lock_line_invalid", f"line={line_number}")
        match = LOCK_LINE_PATTERN.fullmatch(raw_line)
        if match is None:
            raise ManifestError("requirements_lock_line_invalid", f"line={line_number}")
        name = match.group("name")
        version = match.group("version")
        canonical = _canonical_distribution(name)
        if canonical in seen:
            raise ManifestError("requirements_lock_duplicate_distribution", canonical)
        seen.add(canonical)
        requirements.append((name, version))
    if not requirements:
        raise ManifestError("requirements_lock_empty", requirements_lock.name)
    return payload, requirements


def _parse_wheel_filename(filename: str) -> tuple[str, str]:
    if not _valid_filename(filename) or not filename.lower().endswith(WHEEL_SUFFIX):
        raise ManifestError("wheel_filename_invalid", filename)
    fields = filename[: -len(WHEEL_SUFFIX)].split("-")
    if len(fields) not in {5, 6}:
        raise ManifestError("wheel_filename_invalid", filename)
    distribution, version = fields[0], fields[1]
    if not distribution or WHEEL_FIELD_PATTERN.fullmatch(distribution) is None:
        raise ManifestError("wheel_filename_invalid", filename)
    if not version or WHEEL_FIELD_PATTERN.fullmatch(version) is None:
        raise ManifestError("wheel_filename_invalid", filename)
    if len(fields) == 6:
        build, python_tag, abi_tag, platform_tag = fields[2:]
        if WHEEL_BUILD_PATTERN.fullmatch(build) is None:
            raise ManifestError("wheel_filename_invalid", filename)
    else:
        python_tag, abi_tag, platform_tag = fields[2:]
    for tag in (python_tag, abi_tag, platform_tag):
        if WHEEL_FIELD_PATTERN.fullmatch(tag) is None:
            raise ManifestError("wheel_filename_invalid", filename)
    return _canonical_distribution(distribution), version.lower()


def _map_requirements_to_wheels(
    requirements: list[tuple[str, str]],
    artifacts: list[dict[str, Any]],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    locked = {
        _canonical_distribution(name): (name, version)
        for name, version in requirements
    }
    mapped: dict[str, list[dict[str, Any]]] = {name: [] for name in locked}
    for artifact in artifacts:
        filename = artifact["filename"]
        distribution, wheel_version = _parse_wheel_filename(filename)
        locked_value = locked.get(distribution)
        if locked_value is None or wheel_version != _wheel_version(locked_value[1]):
            raise ManifestError("wheel_not_mapped_to_lock", filename)
        mapped[distribution].append(artifact)

    result: list[tuple[str, str, list[dict[str, Any]]]] = []
    for name, version in requirements:
        canonical = _canonical_distribution(name)
        wheels = mapped[canonical]
        if not wheels:
            raise ManifestError("locked_distribution_missing_wheel", f"{name}=={version}")
        result.append((name, version, sorted(wheels, key=lambda item: item["filename"].casefold())))
    return result


def _wheelhouse_artifacts(wheelhouse: Path, manifest: Path) -> list[Path]:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise ManifestError("wheelhouse_not_directory", wheelhouse.name)

    try:
        manifest_resolved = manifest.resolve(strict=False)
        entries = sorted(wheelhouse.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise ManifestError("wheelhouse_read_failed", wheelhouse.name) from exc

    artifacts: list[Path] = []
    folded_names: set[str] = set()
    for entry in entries:
        if entry.resolve(strict=False) == manifest_resolved:
            continue
        if entry.is_symlink() or not entry.is_file() or not _is_artifact_name(entry.name):
            raise ManifestError("unexpected_wheelhouse_entry", entry.name)
        folded = entry.name.casefold()
        if folded in folded_names:
            raise ManifestError("duplicate_artifact_filename", entry.name)
        folded_names.add(folded)
        artifacts.append(entry)
    if not artifacts:
        raise ManifestError("wheelhouse_empty", wheelhouse.name)
    return artifacts


def _load_manifest(path: Path) -> dict[str, Any]:
    _require_regular_file(path, "manifest_missing_or_unsafe")
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ManifestError("manifest_too_large", path.name)
        value = json.loads(path.read_text(encoding="utf-8"))
    except ManifestError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest_invalid_json", path.name) from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest_invalid_shape", path.name)
    return value


def _validate_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ManifestError(code, "expected_lowercase_sha256")
    return value


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if set(manifest) != MANIFEST_KEYS:
        raise ManifestError("manifest_keys_invalid", "top_level")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestError("manifest_schema_version_mismatch", str(manifest["schema_version"]))
    if manifest["hash_algorithm"] != HASH_ALGORITHM:
        raise ManifestError("manifest_hash_algorithm_mismatch", str(manifest["hash_algorithm"]))

    for key in ("python_version", "platform", "machine"):
        if not isinstance(manifest[key], str) or not manifest[key]:
            raise ManifestError("manifest_runtime_identity_invalid", key)

    lock = manifest["requirements_lock"]
    if not isinstance(lock, dict) or set(lock) != LOCK_KEYS:
        raise ManifestError("manifest_lock_invalid", "shape")
    if not _valid_filename(lock["filename"]):
        raise ManifestError("manifest_lock_invalid", "filename")
    _validate_sha256(lock["sha256"], "manifest_lock_hash_invalid")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestError("manifest_artifacts_invalid", "empty_or_not_list")
    folded_names: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_KEYS:
            raise ManifestError("manifest_artifact_invalid", "shape")
        filename = artifact["filename"]
        if not _valid_filename(filename) or not _is_artifact_name(filename):
            raise ManifestError("manifest_artifact_invalid", "filename")
        folded = filename.casefold()
        if folded in folded_names:
            raise ManifestError("manifest_artifact_duplicate", filename)
        folded_names.add(folded)
        _validate_sha256(artifact["sha256"], "manifest_artifact_hash_invalid")
        if type(artifact["size"]) is not int or artifact["size"] < 0:
            raise ManifestError("manifest_artifact_size_invalid", filename)


def create_manifest(
    wheelhouse: Path,
    manifest_path: Path,
    requirements_lock: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    lock_payload, requirements = _read_lock(requirements_lock)
    if manifest_path.exists() and not overwrite:
        raise ManifestError("manifest_exists", manifest_path.name)
    if manifest_path.is_symlink():
        raise ManifestError("manifest_path_unsafe", manifest_path.name)
    if not manifest_path.parent.is_dir():
        raise ManifestError("manifest_parent_missing", manifest_path.parent.name)

    artifacts = _wheelhouse_artifacts(wheelhouse, manifest_path)
    artifact_records = [
        {
            "filename": artifact.name,
            "sha256": _sha256(artifact),
            "size": artifact.stat().st_size,
        }
        for artifact in artifacts
    ]
    _map_requirements_to_wheels(requirements, artifact_records)
    runtime = _runtime_identity()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        **runtime,
        "requirements_lock": {
            "filename": requirements_lock.name,
            "sha256": hashlib.sha256(lock_payload).hexdigest(),
        },
        "artifacts": artifact_records,
    }

    encoded = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            dir=manifest_path.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temporary, manifest_path)
        else:
            try:
                os.link(temporary, manifest_path)
            except FileExistsError as exc:
                raise ManifestError("manifest_exists", manifest_path.name) from exc
            temporary.unlink()
        temporary = None
    except ManifestError:
        raise
    except OSError as exc:
        raise ManifestError("manifest_write_failed", manifest_path.name) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return payload


def verify_manifest(
    wheelhouse: Path,
    manifest_path: Path,
    requirements_lock: Path,
) -> dict[str, Any]:
    lock_payload, requirements = _read_lock(requirements_lock)
    manifest = _load_manifest(manifest_path)
    _validate_manifest_shape(manifest)

    runtime = _runtime_identity()
    for key, expected in runtime.items():
        if manifest[key] != expected:
            raise ManifestError(f"manifest_{key}_mismatch", str(manifest[key]))

    lock = manifest["requirements_lock"]
    if lock["filename"] != requirements_lock.name:
        raise ManifestError("requirements_lock_filename_mismatch", str(lock["filename"]))
    if lock["sha256"] != hashlib.sha256(lock_payload).hexdigest():
        raise ManifestError("requirements_lock_hash_mismatch", requirements_lock.name)

    artifacts = _wheelhouse_artifacts(wheelhouse, manifest_path)
    actual = {artifact.name: artifact for artifact in artifacts}
    declared = {artifact["filename"]: artifact for artifact in manifest["artifacts"]}
    if set(actual) != set(declared):
        missing = sorted(set(declared) - set(actual))
        extra = sorted(set(actual) - set(declared))
        detail = f"missing={','.join(missing)};extra={','.join(extra)}"
        raise ManifestError("wheelhouse_artifact_set_mismatch", detail)

    for filename in sorted(actual, key=str.casefold):
        path = actual[filename]
        expected = declared[filename]
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ManifestError("artifact_read_failed", filename) from exc
        if size != expected["size"]:
            raise ManifestError("artifact_size_mismatch", filename)
        if _sha256(path) != expected["sha256"]:
            raise ManifestError("artifact_hash_mismatch", filename)
    _map_requirements_to_wheels(requirements, manifest["artifacts"])
    return manifest


def _write_new_atomic(path: Path, payload: bytes) -> None:
    if path.exists():
        raise ManifestError("output_exists", path.name)
    if path.is_symlink():
        raise ManifestError("output_path_unsafe", path.name)
    if not path.parent.is_dir():
        raise ManifestError("output_parent_missing", path.parent.name)

    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ManifestError("output_exists", path.name) from exc
        temporary.unlink()
        temporary = None
    except ManifestError:
        raise
    except OSError as exc:
        raise ManifestError("output_write_failed", path.name) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def generate_hash_requirements(
    wheelhouse: Path,
    manifest_path: Path,
    requirements_lock: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest = verify_manifest(wheelhouse, manifest_path, requirements_lock)
    lock_payload, requirements = _read_lock(requirements_lock)
    if manifest["requirements_lock"]["sha256"] != hashlib.sha256(lock_payload).hexdigest():
        raise ManifestError("requirements_lock_hash_mismatch", requirements_lock.name)
    mapped = _map_requirements_to_wheels(requirements, manifest["artifacts"])
    lines = []
    for name, version, wheels in mapped:
        hashes = " ".join(f"--hash=sha256:{wheel['sha256']}" for wheel in wheels)
        lines.append(f"{name}=={version} {hashes}")
    encoded = ("\n".join(lines) + "\n").encode("utf-8")
    _write_new_atomic(output_path, encoded)
    return {
        "schema_version": manifest["schema_version"],
        "artifacts": manifest["artifacts"],
        "requirements": len(mapped),
        "output": output_path.name,
    }


def _build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("create", "verify", "generate-hash-requirements"):
        subparser = subparsers.add_parser(operation)
        subparser.add_argument("--wheelhouse", required=True, type=Path)
        subparser.add_argument("--manifest", type=Path)
        subparser.add_argument("--requirements-lock", required=True, type=Path)
        if operation == "create":
            subparser.add_argument("--overwrite", action="store_true")
        elif operation == "generate-hash-requirements":
            subparser.add_argument("--output", required=True, type=Path)
    return parser


def _emit(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _build_parser().parse_args(argv)
        manifest_path = arguments.manifest or arguments.wheelhouse / MANIFEST_NAME
        if arguments.operation == "create":
            result = create_manifest(
                arguments.wheelhouse,
                manifest_path,
                arguments.requirements_lock,
                overwrite=arguments.overwrite,
            )
        elif arguments.operation == "verify":
            result = verify_manifest(
                arguments.wheelhouse,
                manifest_path,
                arguments.requirements_lock,
            )
        else:
            result = generate_hash_requirements(
                arguments.wheelhouse,
                manifest_path,
                arguments.requirements_lock,
                arguments.output,
            )
        _emit(
            {
                "ok": True,
                "operation": arguments.operation,
                "artifacts": len(result["artifacts"]),
                "schema_version": result["schema_version"],
                **(
                    {"requirements": result["requirements"]}
                    if arguments.operation == "generate-hash-requirements"
                    else {}
                ),
            }
        )
        return 0
    except ManifestError as exc:
        _emit(
            {"ok": False, "code": exc.code, "detail": exc.detail},
            stream=sys.stderr,
        )
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
