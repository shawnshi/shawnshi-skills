#!/usr/bin/env python3
"""Audit and migrate one legacy discovery-call runtime subject binding.

The migration is deliberately narrower than ordinary workspace initialization:
it only adds the current host-signed ``subject_resolution`` to a legacy runtime
manifest.  It never invents, changes, or aliases a ``customer_id``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = Path("runtime/manifest.json")
MIGRATION_SCHEMA = "discovery-call-subject-binding-migration/v1"
SUBJECT_SCHEMA = "discovery-call-subject-resolution/v1"
IDENTITY_FIELDS = (
    "schema",
    "issuer",
    "customer_id",
    "canonical_customer_name",
    "canonical_entity_key",
    "jurisdiction",
    "canonical_subject_sha256",
    "organization_scope_sha256",
    "id_source",
)


class MigrationError(RuntimeError):
    """A fail-closed, user-actionable migration error."""


def _load_local_module(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"discovery_call_migration_{name}", path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"无法加载迁移依赖：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PREFLIGHT = _load_local_module("preflight_intake")
RUNTIME = _load_local_module("runtime_tx")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalized_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise MigrationError(f"{label}必须是文本。")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).strip()
    if not normalized:
        raise MigrationError(f"{label}不能为空。")
    return normalized


def _stable_subject(value: Mapping[str, object]) -> dict[str, object]:
    return {field: value.get(field) for field in IDENTITY_FIELDS}


def _regular_manifest(workspace: Path) -> Path:
    if (
        not workspace.is_dir()
        or workspace.is_symlink()
        or workspace.resolve() != workspace
    ):
        raise MigrationError("workspace必须是非符号链接目录。")
    manifest = workspace / MANIFEST_REL
    if (
        manifest.is_symlink()
        or not manifest.is_file()
        or manifest.resolve().parent != manifest.parent.resolve()
    ):
        raise MigrationError("runtime/manifest.json必须是工作区内普通文件。")
    return manifest


@contextmanager
def _manifest_lock(manifest: Path) -> Iterator[None]:
    """Lock the existing manifest without creating or modifying a lock file."""
    descriptor = os.open(manifest, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_manifest(workspace: Path, manifest: Path) -> tuple[dict[str, object], bytes]:
    raw = manifest.read_bytes()
    try:
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise MigrationError(f"runtime/manifest.json包含重复JSON键：{key}")
                result[key] = value
            return result

        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"runtime/manifest.json不是有效UTF-8 JSON：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != RUNTIME.RUNTIME_SCHEMA:
        raise MigrationError("runtime/manifest.json schema无效。")
    sequence = payload.get("transaction_sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise MigrationError("runtime/manifest.json transaction_sequence无效。")
    for key in ("customer_id", "customer_display_name", "organization_scope"):
        _normalized_text(payload.get(key), f"manifest.{key}")
    if not isinstance(payload.get("artifacts"), dict) or not isinstance(payload.get("runtime_files"), dict):
        raise MigrationError("legacy manifest缺少可审计的artifacts/runtime_files对象。")
    try:
        RUNTIME.verify_manifest_artifacts(workspace, payload)
    except Exception as exc:
        raise MigrationError(f"迁移前成果或机器文件与manifest不一致：{exc}") from exc
    return payload, raw


def _verified_gate(intake_input: Path) -> dict[str, object]:
    if (
        intake_input.is_symlink()
        or not intake_input.is_file()
        or intake_input.resolve() != intake_input
    ):
        raise MigrationError("--intake-input必须是普通文件。")
    try:
        result = PREFLIGHT.evaluate_intake_file(
            str(intake_input),
            now=datetime.now(timezone.utc).replace(microsecond=0),
            require_request_binding=True,
        )
        return PREFLIGHT.verified_gate_record(result)
    except PREFLIGHT.PreflightError as exc:
        raise MigrationError(f"当前intake未通过宿主签名预检：{exc}") from exc


def _assert_legacy_identity(
    manifest: Mapping[str, object],
    gate: Mapping[str, object],
) -> dict[str, object]:
    subject = gate.get("subject_resolution")
    if not isinstance(subject, dict) or subject.get("schema") != SUBJECT_SCHEMA:
        raise MigrationError("当前intake缺少有效subject_resolution。")

    existing = manifest.get("subject_binding")
    if isinstance(existing, dict):
        if _stable_subject(existing) != _stable_subject(subject):
            raise MigrationError("workspace已有不同的subject_binding；迁移不得重绑定主体。")
        return subject
    if existing is not None:
        raise MigrationError("workspace.subject_binding类型无效。")

    legacy_customer_id = _normalized_text(manifest.get("customer_id"), "manifest.customer_id")
    if subject.get("customer_id") != legacy_customer_id:
        raise MigrationError("当前验签主体customer_id与legacy workspace不一致；迁移不得改号。")
    legacy_name = _normalized_text(manifest.get("customer_display_name"), "manifest.customer_display_name")
    signed_name = _normalized_text(subject.get("canonical_customer_name"), "subject_resolution.canonical_customer_name")
    if legacy_name != signed_name:
        raise MigrationError("当前验签主体名称与legacy workspace不一致。")
    legacy_scope = _normalized_text(manifest.get("organization_scope"), "manifest.organization_scope")
    expected_scope_sha = _sha256(legacy_scope.encode("utf-8"))
    if subject.get("organization_scope_sha256") != expected_scope_sha:
        raise MigrationError("当前验签主体范围与legacy workspace不一致。")

    # A canonical-derived id is cryptographically tied to the complete signed
    # (name, entity key, jurisdiction) tuple.  A host-attested external id is
    # accepted only when it exactly preserves the existing stable account id.
    # Therefore a same-name, different-entity resolution cannot be silently
    # rebound through this migration.
    if subject.get("id_source") == "canonical_derived":
        expected_id = "cust-" + str(subject.get("canonical_subject_sha256", ""))[:12]
        if legacy_customer_id != expected_id:
            raise MigrationError("canonical-derived主体与legacy customer_id不一致。")
    elif subject.get("id_source") != "host_attested_external":
        raise MigrationError("subject_resolution.id_source不受支持。")

    old_gate = manifest.get("intake_preflight")
    if isinstance(old_gate, dict) and isinstance(old_gate.get("subject_resolution"), dict):
        if _stable_subject(old_gate["subject_resolution"]) != _stable_subject(subject):
            raise MigrationError("legacy manifest中已有不同的签名主体谱系；禁止覆盖。")
    return subject


def _backup_dir(workspace: Path, source_sha: str, subject_sha: str) -> Path:
    migration_id = "sbm-" + _sha256(f"{source_sha}|{subject_sha}".encode("utf-8"))[:20]
    return workspace / "runtime" / "migrations" / migration_id


def _assert_safe_parent(path: Path, workspace: Path) -> None:
    root = workspace.resolve()
    if path.resolve(strict=False).parent.parent.parent != root:
        raise MigrationError("迁移备份路径越出workspace。")
    cursor = workspace
    for part in path.relative_to(workspace).parts[:-1]:
        cursor = cursor / part
        if cursor.exists() and (cursor.is_symlink() or not cursor.is_dir()):
            raise MigrationError(f"迁移备份父路径无效：{cursor}")


def _prepare_backup(
    backup_dir: Path,
    *,
    original: bytes,
    receipt: Mapping[str, object],
) -> bool:
    """Create a durable backup. Return True only when created this call."""
    original_sha = _sha256(original)
    receipt_bytes = _json_bytes(receipt)
    expected = {
        "manifest.original.json": original,
        "manifest.original.sha256": (original_sha + "\n").encode("ascii"),
        "migration-receipt.json": receipt_bytes,
    }
    if backup_dir.exists():
        if backup_dir.is_symlink() or not backup_dir.is_dir():
            raise MigrationError("既有迁移备份路径不是普通目录。")
        actual_names = {item.name for item in backup_dir.iterdir()}
        if actual_names != set(expected):
            raise MigrationError("既有迁移备份不完整或含未知文件。")
        for name, data in expected.items():
            target = backup_dir / name
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise MigrationError("既有迁移备份与当前迁移计划不一致。")
        return False

    parent_existed = backup_dir.parent.exists()
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = backup_dir.parent / f".{backup_dir.name}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir(mode=0o700)
    try:
        for name, data in expected.items():
            target = temporary / name
            with target.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        RUNTIME.fsync_directory(temporary)
        os.replace(temporary, backup_dir)
        RUNTIME.fsync_directory(backup_dir.parent)
    except BaseException:
        if backup_dir.exists() and not backup_dir.is_symlink() and backup_dir.is_dir():
            shutil.rmtree(backup_dir)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if not parent_existed and backup_dir.parent.is_dir() and not any(backup_dir.parent.iterdir()):
            backup_dir.parent.rmdir()
    return True


def _write_manifest_atomic(path: Path, data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".manifest.migration.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, path.stat().st_mode & 0o777)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        RUNTIME.fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _after_manifest_replace() -> None:
    """Test seam for proving rollback after the replacement point."""


def _cleanup_created_backup(backup_dir: Path, workspace: Path) -> None:
    shutil.rmtree(backup_dir, ignore_errors=True)
    migrations = backup_dir.parent
    if migrations.is_dir() and not any(migrations.iterdir()):
        migrations.rmdir()
    runtime = migrations.parent
    RUNTIME.fsync_directory(runtime if runtime.is_dir() else workspace)


def migrate_workspace(
    workspace_value: str | Path,
    intake_value: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    supplied_workspace = Path(workspace_value).expanduser()
    if supplied_workspace.is_symlink():
        raise MigrationError("workspace不得是符号链接。")
    workspace = Path(os.path.abspath(supplied_workspace))
    manifest_path = _regular_manifest(workspace)
    supplied_intake = Path(intake_value).expanduser()
    if supplied_intake.is_symlink():
        raise MigrationError("--intake-input不得是符号链接。")
    intake_path = Path(os.path.abspath(supplied_intake))
    gate = _verified_gate(intake_path)

    def plan(current: dict[str, object], original: bytes) -> tuple[dict[str, object], Path, dict[str, object]]:
        subject = _assert_legacy_identity(current, gate)
        current_binding = current.get("subject_binding")
        current_gate = current.get("intake_preflight")
        current_gate_subject = (
            current_gate.get("subject_resolution") if isinstance(current_gate, dict) else None
        )
        if (
            isinstance(current_binding, dict)
            and isinstance(current_gate_subject, dict)
            and current_binding == current_gate_subject
        ):
            return current, Path(), {"status": "already_migrated"}
        source_sha = _sha256(original)
        subject_sha = str(gate.get("subject_resolution_sha256", ""))
        backup_dir = _backup_dir(workspace, source_sha, subject_sha)
        _assert_safe_parent(backup_dir, workspace)
        migrated_at = _utc_now()
        if backup_dir.is_dir():
            receipt_path = backup_dir / "migration-receipt.json"
            try:
                prior = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise MigrationError("既有迁移备份收据不可读。") from exc
            migrated_at = str(prior.get("migrated_at", ""))
        replacement = dict(current)
        replacement["subject_binding"] = dict(subject)
        # Scaffold validation runs before ordinary resume writes.  Persist the
        # same verified gate so that validation can prove this binding came
        # from the current host-signed intake, rather than from local text.
        replacement["intake_preflight"] = dict(gate)
        replacement["transaction_sequence"] = int(current["transaction_sequence"]) + 1
        replacement["updated_at"] = migrated_at
        replacement["subject_binding_migration"] = {
            "schema": MIGRATION_SCHEMA,
            "migration_id": backup_dir.name,
            "migrated_at": migrated_at,
            "source_manifest_sha256": source_sha,
            "backup_path": backup_dir.relative_to(workspace).as_posix(),
            "request_binding_receipt_id": gate["request_binding_receipt_id"],
            "request_binding_receipt_sha256": gate["request_binding_receipt_sha256"],
            "gate_id": gate["gate_id"],
            "subject_resolution_sha256": subject_sha,
        }
        return replacement, backup_dir, {"status": "planned", "migrated_at": migrated_at}

    if dry_run:
        current, original = _read_manifest(workspace, manifest_path)
        replacement, backup_dir, state = plan(current, original)
        if state["status"] == "already_migrated":
            return {
                "schema": MIGRATION_SCHEMA,
                "status": "already_migrated",
                "dry_run": True,
                "workspace": str(workspace),
                "customer_id": current["customer_id"],
            }
        return {
            "schema": MIGRATION_SCHEMA,
            "status": "planned",
            "dry_run": True,
            "workspace": str(workspace),
            "customer_id": current["customer_id"],
            "source_manifest_sha256": _sha256(original),
            "replacement_manifest_sha256": _sha256(_json_bytes(replacement)),
            "backup_path": backup_dir.relative_to(workspace).as_posix(),
        }

    with _manifest_lock(manifest_path):
        current, original = _read_manifest(workspace, manifest_path)
        replacement, backup_dir, state = plan(current, original)
        if state["status"] == "already_migrated":
            return {
                "schema": MIGRATION_SCHEMA,
                "status": "already_migrated",
                "dry_run": False,
                "workspace": str(workspace),
                "customer_id": current["customer_id"],
            }
        replacement_bytes = _json_bytes(replacement)
        source_sha = _sha256(original)
        replacement_sha = _sha256(replacement_bytes)
        receipt = {
            "schema": MIGRATION_SCHEMA,
            "migration_id": backup_dir.name,
            "migrated_at": state["migrated_at"],
            "workspace_context_id": str(current.get("context_id", "")),
            "customer_id": str(current["customer_id"]),
            "source_manifest_sha256": source_sha,
            "replacement_manifest_sha256": replacement_sha,
            "request_binding_receipt_id": gate["request_binding_receipt_id"],
            "request_binding_receipt_sha256": gate["request_binding_receipt_sha256"],
            "gate_id": gate["gate_id"],
            "subject_resolution_sha256": gate["subject_resolution_sha256"],
        }
        created_backup = False
        replacement_attempted = False
        try:
            created_backup = _prepare_backup(
                backup_dir,
                original=original,
                receipt=receipt,
            )
            # Detect a concurrent non-cooperating manifest writer after backup.
            if _sha256(manifest_path.read_bytes()) != source_sha:
                raise MigrationError("manifest在迁移期间发生CAS变化。")
            replacement_attempted = True
            _write_manifest_atomic(manifest_path, replacement_bytes)
            _after_manifest_replace()
            if _sha256(manifest_path.read_bytes()) != replacement_sha:
                raise MigrationError("迁移后的manifest摘要不匹配。")
        except BaseException:
            # Atomic replacement normally leaves the old file intact.  If a
            # later check fails, restore the byte-exact original before exit.
            if replacement_attempted and manifest_path.is_file() and not manifest_path.is_symlink():
                if manifest_path.read_bytes() != original:
                    _write_manifest_atomic(manifest_path, original)
            if created_backup:
                _cleanup_created_backup(backup_dir, workspace)
            raise
        return {
            "schema": MIGRATION_SCHEMA,
            "status": "migrated",
            "dry_run": False,
            "workspace": str(workspace),
            "customer_id": current["customer_id"],
            "source_manifest_sha256": source_sha,
            "replacement_manifest_sha256": replacement_sha,
            "backup_path": backup_dir.relative_to(workspace).as_posix(),
        }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="将legacy discovery-call workspace显式迁移到当前验签subject_binding。"
    )
    command.add_argument("workspace", help="包含runtime/manifest.json的legacy workspace")
    command.add_argument(
        "--intake-input",
        required=True,
        help="当前宿主签名且预检ready的intake v3普通文件（不接受-或stdin）",
    )
    command.add_argument("--dry-run", action="store_true", help="只验证并输出计划，绝不写入workspace")
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        result = migrate_workspace(args.workspace, args.intake_input, dry_run=args.dry_run)
    except (MigrationError, OSError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
