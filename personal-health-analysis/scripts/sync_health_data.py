#!/usr/bin/env python3
"""Bounded GarminDB synchronization with explicit network authorization."""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence
from uuid import uuid4

from garmin_capabilities import (
    CapabilityError,
    consume_capability,
    issue_capability,
    require_capability,
)


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTHORIZATION = 3
EXIT_CONFIGURATION = 4
EXIT_SYNC_FAILURE = 5
EXIT_RATE_LIMIT = 6
EXIT_TIMEOUT = 7

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_NAME = "GarminConnectConfig.json"
SYNC_STATS = ("monitoring", "sleep", "rhr", "hrv", "weight")
SYNC_OPERATION = "garmindb_sync"
SYNC_PLAN_VERSION = 2
DEFAULT_PLAN_TTL_SECONDS = 300
MAX_PLAN_TTL_SECONDS = 900
SYNC_PLAN_FIELDS = frozenset(
    {
        "version",
        "operation",
        "window",
        "issued_at",
        "expires_at",
        "nonce",
        "bindings",
        "payload_sha256",
    }
)
SYNC_BINDING_FIELDS = frozenset({"config", "runner"})
CONFIG_BINDING_FIELDS = frozenset({"filename", "sha256"})
RUNNER_BINDING_FIELDS = frozenset({"interpreter", "cli", "environment"})
RUNNER_FILE_BINDING_FIELDS = frozenset(
    {"filename", "sha256", "size_bytes", "path_sha256", "file_identity_sha256"}
)
RUNNER_ENVIRONMENT_FIELDS = frozenset(
    {
        "evidence_method",
        "review_status",
        "pyvenv_cfg_sha256",
        "site_packages_tree_sha256",
        "site_packages_file_count",
        "packages",
    }
)
PACKAGE_EVIDENCE_FIELDS = frozenset({"name", "version", "metadata_sha256"})
PACKAGE_EVIDENCE_NAMES = ("garmindb", "garminconnect")
SUPPORTED_PACKAGE_VERSIONS = {"garmindb": "3.8.0", "garminconnect": "0.3.9"}
MAX_METADATA_BYTES = 1024 * 1024


class WindowError(ValueError):
    pass


class SyncConfigurationError(RuntimeError):
    pass


class SyncPlanError(ValueError):
    pass


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize a bounded Garmin health-data window."
    )
    subparsers = parser.add_subparsers(dest="command")
    sync_parser = subparsers.add_parser("sync", help="Run a bounded synchronization")
    sync_parser.add_argument("--start", help="Inclusive start date in YYYY-MM-DD")
    sync_parser.add_argument("--end", help="Inclusive end date in YYYY-MM-DD")
    sync_parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize network access for this invocation",
    )
    sync_parser.add_argument(
        "--allow-sync",
        action="store_true",
        help="Explicitly authorize GarminDB synchronization for this invocation",
    )
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="Validate the request only"
    )
    sync_parser.add_argument(
        "--plan-output",
        help="During --dry-run, atomically write a short-lived sync plan",
    )
    sync_parser.add_argument(
        "--plan-ttl-seconds",
        type=int,
        default=DEFAULT_PLAN_TTL_SECONDS,
        help="Plan lifetime (1-900 seconds)",
    )
    sync_parser.add_argument(
        "--plan-file",
        help="Required short-lived plan produced by a matching --dry-run",
    )
    sync_parser.add_argument(
        "--config-dir",
        help=(
            "Explicit GarminDB config directory; required when creating or "
            "executing a bound plan"
        ),
    )
    sync_parser.add_argument(
        "--garmindb-python",
        help=(
            "Explicit Python executable from a separately verified GarminDB "
            "environment; no PATH discovery is performed"
        ),
    )
    sync_parser.add_argument(
        "--timeout-seconds", type=int, default=900, help="Maximum runner duration"
    )
    return parser


def parse_window(start_raw: str | None, end_raw: str | None) -> tuple[date, date]:
    if not start_raw or not end_raw:
        raise WindowError("explicit_start_and_end_required")
    try:
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
    except ValueError as exc:
        raise WindowError("invalid_iso_date") from exc
    if start > end:
        raise WindowError("start_after_end")
    return start, end


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_now(value: datetime | None) -> datetime:
    resolved = _utc_now() if value is None else value
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise SyncPlanError("timezone_aware_datetime_required")
    return resolved.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise SyncPlanError(f"plan_{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyncPlanError(f"plan_{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SyncPlanError(f"plan_{field}_invalid")
    return parsed.astimezone(timezone.utc)


def _plan_payload(plan: dict) -> dict:
    return {
        "version": plan.get("version"),
        "operation": plan.get("operation"),
        "window": plan.get("window"),
        "issued_at": plan.get("issued_at"),
        "expires_at": plan.get("expires_at"),
        "nonce": plan.get("nonce"),
        "bindings": plan.get("bindings"),
    }


def _payload_sha256(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bounded_file(path: Path, *, maximum_bytes: int | None = None) -> bytes:
    try:
        if maximum_bytes is not None and path.stat().st_size > maximum_bytes:
            raise SyncConfigurationError("runner_metadata_too_large")
        return path.read_bytes()
    except SyncConfigurationError:
        raise
    except OSError as exc:
        raise SyncConfigurationError("bound_file_read_failed") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SyncConfigurationError("bound_file_read_failed") from exc
    return digest.hexdigest()


def _normalized_path_sha256(path: Path) -> str:
    normalized = os.path.normcase(os.path.abspath(os.fspath(path)))
    return _sha256_bytes(normalized.encode("utf-8", errors="surrogatepass"))


def _file_identity_sha256(path: Path) -> str:
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise SyncConfigurationError("bound_file_stat_failed") from exc
    identity = f"{stat_result.st_dev}:{stat_result.st_ino}".encode("ascii")
    return _sha256_bytes(identity)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise SyncConfigurationError("bound_file_stat_failed") from exc
    return path.is_symlink() or bool(attributes & 0x400)


def _stable_file_evidence(path: Path) -> tuple[str, os.stat_result]:
    """Hash one open descriptor and fail if its path identity changes mid-read."""
    if _is_link_or_reparse(path):
        raise SyncConfigurationError("bound_runner_link_forbidden")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError as exc:
        raise SyncConfigurationError("bound_file_read_failed") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    identity_current = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if identity_before != identity_after or identity_after != identity_current:
        raise SyncConfigurationError("bound_file_changed_during_read")
    return digest.hexdigest(), after


def _runner_file_binding(path: Path) -> dict:
    if not path.is_file():
        raise SyncConfigurationError("bound_runner_file_invalid")
    digest, stat_result = _stable_file_evidence(path)
    return {
        "filename": path.name,
        "sha256": digest,
        "size_bytes": stat_result.st_size,
        "path_sha256": _normalized_path_sha256(path),
        "file_identity_sha256": _sha256_bytes(
            f"{stat_result.st_dev}:{stat_result.st_ino}".encode("ascii")
        ),
    }


def _venv_root_for_interpreter(interpreter: Path) -> Path:
    root = interpreter.parent.parent
    pyvenv_config = root / "pyvenv.cfg"
    if not pyvenv_config.is_file():
        raise SyncConfigurationError("isolated_runner_venv_required")
    if _is_link_or_reparse(root) or _is_link_or_reparse(pyvenv_config):
        raise SyncConfigurationError("isolated_runner_link_forbidden")
    return root


def _locate_site_packages(venv_root: Path) -> Path:
    candidates: list[Path] = []
    windows_candidate = venv_root / "Lib" / "site-packages"
    if windows_candidate.is_dir():
        candidates.append(windows_candidate)
    unix_lib = venv_root / "lib"
    if unix_lib.is_dir():
        candidates.extend(
            candidate
            for candidate in sorted(unix_lib.glob("python*/site-packages"))
            if candidate.is_dir()
        )
    unique = {os.path.normcase(os.path.abspath(os.fspath(path))): path for path in candidates}
    if len(unique) != 1:
        raise SyncConfigurationError("runner_site_packages_not_unique")
    site_packages = next(iter(unique.values()))
    if _is_link_or_reparse(site_packages):
        raise SyncConfigurationError("runner_site_packages_link_forbidden")
    return site_packages


def _site_packages_tree_evidence(site_packages: Path) -> tuple[str, int]:
    """Hash stable package files without executing the runner interpreter."""
    def scan() -> list[Path]:
        files: list[Path] = []
        try:
            for candidate in site_packages.rglob("*"):
                if _is_link_or_reparse(candidate):
                    raise SyncConfigurationError("runner_site_packages_link_forbidden")
                if candidate.is_file():
                    files.append(candidate)
        except OSError as exc:
            raise SyncConfigurationError("runner_site_packages_scan_failed") from exc
        return sorted(
            files,
            key=lambda item: item.relative_to(site_packages).as_posix(),
        )

    files = scan()
    initial_names = [item.relative_to(site_packages).as_posix() for item in files]
    digest = hashlib.sha256()
    for candidate in files:
        relative = candidate.relative_to(site_packages).as_posix().encode("utf-8")
        try:
            size = candidate.stat().st_size
        except OSError as exc:
            raise SyncConfigurationError("runner_site_packages_scan_failed") from exc
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(_file_sha256(candidate).encode("ascii"))
        digest.update(b"\n")
    final_names = [
        item.relative_to(site_packages).as_posix()
        for item in scan()
    ]
    if final_names != initial_names:
        raise SyncConfigurationError("runner_site_packages_changed_during_scan")
    return digest.hexdigest(), len(files)


def _normalize_distribution_name(value: str) -> str:
    return value.strip().casefold().replace("_", "-").replace(".", "-")


def _read_package_evidence(site_packages: Path) -> list[dict]:
    found: dict[str, list[dict]] = {name: [] for name in PACKAGE_EVIDENCE_NAMES}
    try:
        metadata_files = sorted(site_packages.glob("*.dist-info/METADATA"))
    except OSError:
        return []
    for metadata_file in metadata_files:
        try:
            raw = _read_bounded_file(metadata_file, maximum_bytes=MAX_METADATA_BYTES)
        except SyncConfigurationError:
            continue
        name = None
        version = None
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line:
                break
            if line.startswith("Name: "):
                name = _normalize_distribution_name(line[6:])
            elif line.startswith("Version: "):
                version = line[9:].strip()
        if (
            name in found
            and version
            and len(version) <= 100
            and all(character.isprintable() for character in version)
        ):
            found[name].append(
                {
                    "name": name,
                    "version": version,
                    "metadata_sha256": _sha256_bytes(raw),
                }
            )
    return [found[name][0] for name in PACKAGE_EVIDENCE_NAMES if len(found[name]) == 1]


def build_runner_binding(interpreter: Path, cli_path: Path) -> dict:
    venv_root = _venv_root_for_interpreter(interpreter)
    site_packages = _locate_site_packages(venv_root)
    tree_sha256, file_count = _site_packages_tree_evidence(site_packages)
    packages = _read_package_evidence(site_packages)
    versions = {package["name"]: package["version"] for package in packages}
    if set(versions) != set(PACKAGE_EVIDENCE_NAMES):
        raise SyncConfigurationError("runner_package_evidence_incomplete")
    if versions != SUPPORTED_PACKAGE_VERSIONS:
        raise SyncConfigurationError("runner_package_version_unsupported")
    return {
        "interpreter": _runner_file_binding(interpreter),
        "cli": _runner_file_binding(cli_path),
        "environment": {
            "evidence_method": "isolated_venv_filesystem_read_only",
            "review_status": "filesystem_evidence_bound_external_security_review_required",
            "pyvenv_cfg_sha256": _file_sha256(venv_root / "pyvenv.cfg"),
            "site_packages_tree_sha256": tree_sha256,
            "site_packages_file_count": file_count,
            "packages": packages,
        },
    }


def _read_config_source(source_dir: Path) -> tuple[bytes, dict]:
    source_dir = Path(source_dir).expanduser()
    if _is_within(source_dir, SKILL_ROOT):
        raise SyncConfigurationError("skill_directory_config_forbidden")
    source_file = source_dir / CONFIG_NAME
    if not source_file.is_file():
        raise SyncConfigurationError("garmin_config_not_found")
    try:
        raw = source_file.read_bytes()
        original = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncConfigurationError("garmin_config_invalid") from exc
    if not isinstance(original, dict):
        raise SyncConfigurationError("garmin_config_invalid")
    return raw, original


def build_config_binding(source_dir: Path) -> dict:
    raw, _ = _read_config_source(source_dir)
    return {"filename": CONFIG_NAME, "sha256": _sha256_bytes(raw)}


def build_sync_bindings(config_dir: Path, garmindb_python: Path) -> dict:
    interpreter, cli_path = locate_garmindb_cli(garmindb_python)
    return {
        "config": build_config_binding(config_dir),
        "runner": build_runner_binding(interpreter, cli_path),
    }


def validate_sync_bindings(bindings: object) -> None:
    if not isinstance(bindings, dict) or set(bindings) != SYNC_BINDING_FIELDS:
        raise SyncPlanError("plan_bindings_required")
    config = bindings.get("config")
    if not isinstance(config, dict) or set(config) != CONFIG_BINDING_FIELDS:
        raise SyncPlanError("plan_config_binding_invalid")
    if config.get("filename") != CONFIG_NAME or not _is_sha256(config.get("sha256")):
        raise SyncPlanError("plan_config_binding_invalid")
    runner = bindings.get("runner")
    if not isinstance(runner, dict) or set(runner) != RUNNER_BINDING_FIELDS:
        raise SyncPlanError("plan_runner_binding_invalid")
    for field in ("interpreter", "cli"):
        identity = runner.get(field)
        if not isinstance(identity, dict) or set(identity) != RUNNER_FILE_BINDING_FIELDS:
            raise SyncPlanError("plan_runner_binding_invalid")
        if not isinstance(identity.get("filename"), str) or not identity["filename"]:
            raise SyncPlanError("plan_runner_binding_invalid")
        if any(
            not _is_sha256(identity.get(hash_field))
            for hash_field in ("sha256", "path_sha256", "file_identity_sha256")
        ):
            raise SyncPlanError("plan_runner_binding_invalid")
        size = identity.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SyncPlanError("plan_runner_binding_invalid")
    environment = runner.get("environment")
    if not isinstance(environment, dict) or set(environment) != RUNNER_ENVIRONMENT_FIELDS:
        raise SyncPlanError("plan_runner_environment_invalid")
    if environment.get("evidence_method") != "isolated_venv_filesystem_read_only":
        raise SyncPlanError("plan_runner_environment_invalid")
    if (
        environment.get("review_status")
        != "filesystem_evidence_bound_external_security_review_required"
    ):
        raise SyncPlanError("plan_runner_environment_invalid")
    if any(
        not _is_sha256(environment.get(hash_field))
        for hash_field in ("pyvenv_cfg_sha256", "site_packages_tree_sha256")
    ):
        raise SyncPlanError("plan_runner_environment_invalid")
    file_count = environment.get("site_packages_file_count")
    if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count < 0:
        raise SyncPlanError("plan_runner_environment_invalid")
    packages = environment.get("packages")
    if not isinstance(packages, list) or len(packages) > len(PACKAGE_EVIDENCE_NAMES):
        raise SyncPlanError("plan_runner_environment_invalid")
    seen = set()
    for package in packages:
        if not isinstance(package, dict) or set(package) != PACKAGE_EVIDENCE_FIELDS:
            raise SyncPlanError("plan_runner_environment_invalid")
        name = package.get("name")
        if name not in PACKAGE_EVIDENCE_NAMES or name in seen:
            raise SyncPlanError("plan_runner_environment_invalid")
        if not isinstance(package.get("version"), str) or not package["version"]:
            raise SyncPlanError("plan_runner_environment_invalid")
        if not _is_sha256(package.get("metadata_sha256")):
            raise SyncPlanError("plan_runner_environment_invalid")
        seen.add(name)
    versions = {package["name"]: package["version"] for package in packages}
    if versions != SUPPORTED_PACKAGE_VERSIONS:
        raise SyncPlanError("plan_runner_environment_invalid")


def build_sync_plan(
    start: date,
    end: date,
    *,
    ttl_seconds: int = DEFAULT_PLAN_TTL_SECONDS,
    now: datetime | None = None,
    bindings: dict | None = None,
) -> dict:
    """Build a checksum-bound, short-lived plan without performing I/O."""
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise SyncPlanError("plan_ttl_must_be_integer")
    if not 1 <= ttl_seconds <= MAX_PLAN_TTL_SECONDS:
        raise SyncPlanError("plan_ttl_out_of_range")
    validate_sync_bindings(bindings)
    issued_at = _normalize_now(now)
    payload = {
        "version": SYNC_PLAN_VERSION,
        "operation": SYNC_OPERATION,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "issued_at": _format_timestamp(issued_at),
        "expires_at": _format_timestamp(issued_at + timedelta(seconds=ttl_seconds)),
        "nonce": uuid4().hex,
        "bindings": copy.deepcopy(bindings),
    }
    return {**payload, "payload_sha256": _payload_sha256(payload)}


def write_sync_plan_atomic(path: Path, plan: dict) -> Path:
    """Install a complete plan atomically and refuse to overwrite by default."""
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise SyncPlanError("plan_output_exists")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            json.dump(plan, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, output_path)
        temporary_path.unlink()
    except FileExistsError as exc:
        raise SyncPlanError("plan_output_exists") from exc
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return output_path


def load_and_validate_sync_plan(
    path: Path,
    *,
    expected_start: date,
    expected_end: date,
    now: datetime | None = None,
    expected_bindings: dict | None = None,
) -> dict:
    """Load a plan and verify schema, digest, operation, window, and expiry."""
    plan_path = Path(path).expanduser()
    if not plan_path.is_file():
        raise SyncPlanError("sync_plan_not_found")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncPlanError("sync_plan_invalid") from exc
    if not isinstance(plan, dict) or set(plan) != SYNC_PLAN_FIELDS:
        raise SyncPlanError("sync_plan_schema_invalid")
    payload = _plan_payload(plan)
    supplied_digest = plan.get("payload_sha256")
    if not isinstance(supplied_digest, str) or not hmac.compare_digest(
        supplied_digest, _payload_sha256(payload)
    ):
        raise SyncPlanError("plan_digest_mismatch")
    if plan.get("version") != SYNC_PLAN_VERSION:
        raise SyncPlanError("plan_version_unsupported")
    if plan.get("operation") != SYNC_OPERATION:
        raise SyncPlanError("plan_operation_mismatch")
    validate_sync_bindings(plan.get("bindings"))
    if expected_bindings is not None:
        validate_sync_bindings(expected_bindings)
        if plan.get("bindings") != expected_bindings:
            raise SyncPlanError("plan_bindings_mismatch")
    window = plan.get("window")
    expected_window = {
        "start": expected_start.isoformat(),
        "end": expected_end.isoformat(),
    }
    if window != expected_window:
        raise SyncPlanError("plan_window_mismatch")
    nonce = plan.get("nonce")
    if (
        not isinstance(nonce, str)
        or len(nonce) != 32
        or any(character not in "0123456789abcdef" for character in nonce)
    ):
        raise SyncPlanError("plan_nonce_invalid")
    issued_at = _parse_timestamp(plan.get("issued_at"), field="issued_at")
    expires_at = _parse_timestamp(plan.get("expires_at"), field="expires_at")
    if expires_at <= issued_at:
        raise SyncPlanError("plan_expiry_invalid")
    checked_at = _normalize_now(now)
    if checked_at >= expires_at:
        raise SyncPlanError("plan_expired")
    if issued_at > checked_at + timedelta(seconds=5):
        raise SyncPlanError("plan_issued_in_future")
    return plan


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


@contextmanager
def prepare_windowed_config(
    source_dir: Path,
    start: date,
    end: date,
    *,
    expected_sha256: str,
) -> Iterator[Path]:
    """Create a private temporary GarminDB config scoped to the requested dates."""
    raw, original = _read_config_source(source_dir)
    if not hmac.compare_digest(_sha256_bytes(raw), expected_sha256):
        raise SyncConfigurationError("bound_config_changed")

    windowed = copy.deepcopy(original)
    data = windowed.setdefault("data", {})
    if not isinstance(data, dict):
        raise SyncConfigurationError("garmin_config_data_invalid")
    start_value = start.strftime("%m/%d/%Y")
    end_value = end.strftime("%m/%d/%Y")
    data["start_date"] = start_value
    data["end_date"] = end_value
    for stat in SYNC_STATS:
        data[f"{stat}_start_date"] = start_value
        data[f"{stat}_end_date"] = end_value

    with tempfile.TemporaryDirectory(prefix="personal-health-sync-") as temp_name:
        temp_dir = Path(temp_name)
        config_file = temp_dir / CONFIG_NAME
        config_file.write_text(
            json.dumps(windowed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            config_file.chmod(0o600)
            temp_dir.chmod(0o700)
        except OSError as exc:
            raise SyncConfigurationError("temporary_config_security_failed") from exc
        yield temp_dir


def locate_garmindb_cli(
    python_executable: Path | None,
) -> tuple[Path, Path]:
    """Resolve a CLI only beside an explicitly trusted Python executable."""
    if python_executable is None:
        raise SyncConfigurationError("trusted_garmindb_python_required")
    try:
        supplied = Path(python_executable).expanduser()
        interpreter = Path(os.path.abspath(os.fspath(supplied)))
        interpreter.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SyncConfigurationError("trusted_garmindb_python_invalid") from exc
    if not interpreter.is_file():
        raise SyncConfigurationError("trusted_garmindb_python_invalid")
    if _is_link_or_reparse(interpreter):
        raise SyncConfigurationError("trusted_garmindb_python_link_forbidden")
    _venv_root_for_interpreter(interpreter)

    candidates = (
        interpreter.parent / "garmindb_cli.py",
        interpreter.parent / "garmindb_cli",
    )
    for candidate in candidates:
        if candidate.is_file():
            if _is_link_or_reparse(candidate):
                raise SyncConfigurationError("trusted_garmindb_cli_link_forbidden")
            return interpreter, Path(os.path.abspath(os.fspath(candidate)))
    raise SyncConfigurationError("trusted_garmindb_cli_not_found")


def build_garmindb_command(
    python_executable: Path, cli_path: Path, config_dir: Path
) -> list[str]:
    return [
        str(python_executable),
        "-I",
        "-B",
        str(cli_path),
        "--config",
        str(config_dir),
        "--download",
        "--import",
        "--analyze",
        "--monitoring",
        "--sleep",
        "--rhr",
        "--hrv",
        "--weight",
    ]


def _sanitized_runner_environment() -> dict[str, str]:
    """Build a small inherited environment without Python or pip injection hooks."""
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def classify_process_result(returncode: int, output: str) -> tuple[int, dict]:
    normalized = (output or "").casefold()
    if "429" in normalized or "too many requests" in normalized:
        return EXIT_RATE_LIMIT, {"ok": False, "status": "rate_limited"}
    if "failed to login" in normalized or "authentication failed" in normalized:
        return EXIT_SYNC_FAILURE, {"ok": False, "status": "authentication_failed"}
    if returncode != 0:
        return EXIT_SYNC_FAILURE, {
            "ok": False,
            "status": "sync_failed",
            "runner_exit_code": returncode,
        }
    return EXIT_OK, {"ok": True, "status": "sync_completed"}


def execute_sync(
    start: date,
    end: date,
    *,
    network_capability: object = None,
    sync_capability: object = None,
    plan_file: Path | None = None,
    config_dir: Path | None = None,
    garmindb_python: Path | None = None,
    timeout_seconds: int = 900,
    runner=None,
) -> tuple[int, dict]:
    requested_window = {"start": start.isoformat(), "end": end.isoformat()}
    capability_request = {"window": requested_window}
    try:
        require_capability(
            network_capability,
            scope="network",
            operation=SYNC_OPERATION,
            request=capability_request,
        )
    except CapabilityError:
        return EXIT_AUTHORIZATION, {
            "ok": False,
            "status": "network_authorization_required",
            "requested_window": requested_window,
        }
    try:
        require_capability(
            sync_capability,
            scope="sync",
            operation=SYNC_OPERATION,
            request=capability_request,
        )
    except CapabilityError:
        return EXIT_AUTHORIZATION, {
            "ok": False,
            "status": "sync_authorization_required",
            "requested_window": requested_window,
        }
    if plan_file is None:
        return EXIT_AUTHORIZATION, {
            "ok": False,
            "status": "sync_plan_required",
            "requested_window": requested_window,
        }
    try:
        plan = load_and_validate_sync_plan(
            plan_file,
            expected_start=start,
            expected_end=end,
        )
    except SyncPlanError as exc:
        return EXIT_AUTHORIZATION, {
            "ok": False,
            "status": "sync_plan_invalid",
            "error": str(exc),
            "requested_window": requested_window,
        }
    if timeout_seconds <= 0:
        return EXIT_USAGE, {
            "ok": False,
            "status": "usage_error",
            "error": "timeout_must_be_positive",
            "requested_window": requested_window,
        }
    if config_dir is None:
        return EXIT_CONFIGURATION, {
            "ok": False,
            "status": "configuration_error",
            "error": "explicit_config_dir_required_for_bound_plan",
            "requested_window": requested_window,
        }
    if garmindb_python is None:
        return EXIT_CONFIGURATION, {
            "ok": False,
            "status": "configuration_error",
            "error": "trusted_garmindb_python_required",
            "requested_window": requested_window,
        }
    try:
        python_executable, cli_path = locate_garmindb_cli(garmindb_python)
        current_bindings = {
            "config": build_config_binding(Path(config_dir)),
            "runner": build_runner_binding(python_executable, cli_path),
        }
        validate_sync_bindings(current_bindings)
        if plan["bindings"] != current_bindings:
            raise SyncPlanError("plan_bindings_mismatch")
    except SyncPlanError as exc:
        return EXIT_AUTHORIZATION, {
            "ok": False,
            "status": "sync_plan_invalid",
            "error": str(exc),
            "requested_window": requested_window,
        }
    except SyncConfigurationError as exc:
        return EXIT_CONFIGURATION, {
            "ok": False,
            "status": "configuration_error",
            "error": str(exc),
            "requested_window": requested_window,
        }

    runner = subprocess.run if runner is None else runner
    try:
        with prepare_windowed_config(
            Path(config_dir),
            start,
            end,
            expected_sha256=plan["bindings"]["config"]["sha256"],
        ) as temp_config_dir:
            temporary_config = temp_config_dir / CONFIG_NAME
            temporary_config_sha256 = _file_sha256(temporary_config)
            # Re-read the runner bytes and isolated environment immediately before
            # invocation so a post-plan path or file replacement fails closed.
            current_runner = build_runner_binding(python_executable, cli_path)
            if plan["bindings"]["runner"] != current_runner:
                raise SyncConfigurationError("bound_runner_changed")
            current_bindings = {
                "config": build_config_binding(Path(config_dir)),
                "runner": current_runner,
            }
            plan = load_and_validate_sync_plan(
                Path(plan_file),
                expected_start=start,
                expected_end=end,
                expected_bindings=current_bindings,
            )
            if _file_sha256(temporary_config) != temporary_config_sha256:
                raise SyncConfigurationError("temporary_config_changed")
            command = build_garmindb_command(
                python_executable, cli_path, temp_config_dir
            )
            consume_capability(
                network_capability,
                scope="network",
                operation=SYNC_OPERATION,
                request=capability_request,
            )
            consume_capability(
                sync_capability,
                scope="sync",
                operation=SYNC_OPERATION,
                request=capability_request,
            )
            completed = runner(
                command,
                cwd=temp_config_dir,
                env=_sanitized_runner_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        exit_code, payload = classify_process_result(
            completed.returncode, completed.stdout or ""
        )
    except subprocess.TimeoutExpired:
        exit_code, payload = EXIT_TIMEOUT, {"ok": False, "status": "sync_timeout"}
    except (CapabilityError, SyncPlanError) as exc:
        exit_code, payload = EXIT_AUTHORIZATION, {
            "ok": False,
            "status": "authorization_expired_or_plan_changed",
            "error_type": type(exc).__name__,
        }
    except SyncConfigurationError as exc:
        exit_code, payload = EXIT_CONFIGURATION, {
            "ok": False,
            "status": "configuration_error",
            "error": str(exc),
        }
    except Exception as exc:
        exit_code, payload = EXIT_SYNC_FAILURE, {
            "ok": False,
            "status": "sync_failed",
            "error_type": type(exc).__name__,
        }
    payload["requested_window"] = requested_window
    return exit_code, payload


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        emit({"ok": False, "status": "usage_error", "error": "command_required"})
        return EXIT_USAGE

    try:
        start, end = parse_window(args.start, args.end)
    except WindowError as exc:
        emit({"ok": False, "status": "usage_error", "error": str(exc)})
        return EXIT_USAGE

    requested_window = {"start": start.isoformat(), "end": end.isoformat()}
    if args.dry_run:
        if args.plan_file:
            emit(
                {
                    "ok": False,
                    "status": "usage_error",
                    "error": "plan_file_not_allowed_for_dry_run",
                    "requested_window": requested_window,
                }
            )
            return EXIT_USAGE
        plan_written = False
        plan_path = None
        if args.plan_output:
            if not args.config_dir or not args.garmindb_python:
                emit(
                    {
                        "ok": False,
                        "status": "usage_error",
                        "error": "plan_output_requires_explicit_config_and_runner",
                        "requested_window": requested_window,
                    }
                )
                return EXIT_USAGE
            try:
                bindings = build_sync_bindings(
                    Path(args.config_dir).expanduser(),
                    Path(args.garmindb_python).expanduser(),
                )
                plan = build_sync_plan(
                    start,
                    end,
                    ttl_seconds=args.plan_ttl_seconds,
                    bindings=bindings,
                )
                plan_path = write_sync_plan_atomic(Path(args.plan_output), plan)
                plan_written = True
            except (OSError, SyncConfigurationError, SyncPlanError) as exc:
                emit(
                    {
                        "ok": False,
                        "status": "plan_write_failed",
                        "error": str(exc),
                        "requested_window": requested_window,
                    }
                )
                return EXIT_CONFIGURATION
        emit(
            {
                "ok": True,
                "status": "dry_run",
                "network_accessed": False,
                "requested_window": requested_window,
                "plan_written": plan_written,
                **({"plan_file": str(plan_path)} if plan_path else {}),
            }
        )
        return EXIT_OK

    if args.plan_output:
        emit(
            {
                "ok": False,
                "status": "usage_error",
                "error": "plan_output_requires_dry_run",
                "requested_window": requested_window,
            }
        )
        return EXIT_USAGE

    if not args.allow_network:
        emit(
            {
                "ok": False,
                "status": "network_authorization_required",
                "requested_window": requested_window,
            }
        )
        return EXIT_AUTHORIZATION

    if not args.allow_sync:
        emit(
            {
                "ok": False,
                "status": "sync_authorization_required",
                "requested_window": requested_window,
            }
        )
        return EXIT_AUTHORIZATION

    if not args.plan_file:
        emit(
            {
                "ok": False,
                "status": "sync_plan_required",
                "requested_window": requested_window,
            }
        )
        return EXIT_AUTHORIZATION

    network_capability = issue_capability(
        scope="network",
        operation=SYNC_OPERATION,
        request={"window": requested_window},
    )
    sync_capability = issue_capability(
        scope="sync",
        operation=SYNC_OPERATION,
        request={"window": requested_window},
    )
    exit_code, payload = execute_sync(
        start,
        end,
        network_capability=network_capability,
        sync_capability=sync_capability,
        plan_file=Path(args.plan_file).expanduser(),
        config_dir=Path(args.config_dir).expanduser() if args.config_dir else None,
        garmindb_python=(
            Path(args.garmindb_python).expanduser()
            if args.garmindb_python
            else None
        ),
        timeout_seconds=args.timeout_seconds,
    )
    emit(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
