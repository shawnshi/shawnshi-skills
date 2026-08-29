#!/usr/bin/env python3
"""POSIX locking, CAS, manifests, and recoverable multi-file commits.

The Markdown artifacts remain the human-readable layer.  The runtime manifest
and write-ahead journal are the machine authority for concurrency and crash
recovery.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


RUNTIME_SCHEMA = "discovery-call-runtime/v1"
JOURNAL_SCHEMA = "discovery-call-transaction/v1"
RUNTIME_DIR = "runtime"
MANIFEST_REL = Path(RUNTIME_DIR) / "manifest.json"
EVIDENCE_MANIFEST_REL = Path(RUNTIME_DIR) / "evidence-manifest.json"
SEARCH_PLAN_REL = Path(RUNTIME_DIR) / "search-plan.json"
SOURCE_CACHE_REL = Path(RUNTIME_DIR) / "source-cache.json"
RUN_METRICS_REL = Path(RUNTIME_DIR) / "run-metrics.json"
GOVERNANCE_CONTEXT_REL = Path(RUNTIME_DIR) / "governance-context.json"
AUDITED_RUNTIME_RELS = {
    EVIDENCE_MANIFEST_REL,
    SEARCH_PLAN_REL,
    SOURCE_CACHE_REL,
    RUN_METRICS_REL,
    GOVERNANCE_CONTEXT_REL,
}
RESEARCH_RUNTIME_RELS = {
    EVIDENCE_MANIFEST_REL,
    SEARCH_PLAN_REL,
    SOURCE_CACHE_REL,
    RUN_METRICS_REL,
}
JOURNAL_NAME = ".discovery-call.txn.json"
OUTPUT_LOCK_NAME = ".discovery-call.output.lock"
WORKSPACE_LOCK_NAME = ".discovery-call.workspace.lock"
TX_DIR_PREFIX = ".discovery-call-txn-"
CONTENT_VERSION_RE = re.compile(r"^[1-9][0-9]*$")
DELIVERY_SUMMARY_UNSET = object()


class TxError(RuntimeError):
    """Base class for deterministic runtime failures."""


class LockTimeout(TxError):
    """A cooperating process held the lock longer than allowed."""


class CASMismatch(TxError):
    """The workspace changed after the caller prepared its candidate."""


class RecoveryRequired(TxError):
    """An unfinished transaction must be recovered before another write."""


@dataclass(frozen=True)
class FileState:
    exists: bool
    sha256: str
    content_version: str
    latest_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "exists": self.exists,
            "sha256": self.sha256,
            "content_version": self.content_version,
            "latest_run_id": self.latest_run_id,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_task_timezone(value: object) -> str | None:
    """Validate an optional persisted IANA timezone without consulting host TZ."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise TxError("运行清单task_timezone必须是非空IANA时区字符串。")
    try:
        return ZoneInfo(value).key
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TxError("运行清单task_timezone不是有效IANA时区。") from exc


def task_date_at(instant: datetime, task_timezone: str) -> date:
    """Return the task civil date for one aware instant and persisted timezone."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise TxError("任务日期计算要求带时区时间。")
    normalized = normalize_task_timezone(task_timezone)
    if normalized is None:  # Defensive: the public contract requires a timezone here.
        raise TxError("任务日期计算缺少task_timezone。")
    return instant.astimezone(ZoneInfo(normalized)).date()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}
    data: dict[str, str] = {}
    for line in lines[1:end]:
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not match:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        data[key] = value
    return data


def parse_frontmatter(text: str) -> dict[str, str]:
    """Public, intentionally flat frontmatter reader used by runtime CLIs."""
    return _frontmatter(text)


def file_state(path: Path) -> FileState:
    if not path.exists():
        return FileState(False, "", "", "")
    if not path.is_file() or path.is_symlink():
        raise TxError(f"CAS目标不是普通文件：{path}")
    raw = path.read_bytes()
    metadata = _frontmatter(raw.decode("utf-8")) if path.suffix.casefold() == ".md" else {}
    return FileState(
        True,
        sha256_bytes(raw),
        metadata.get("content_version", ""),
        metadata.get("latest_run_id", ""),
    )


def _same_state(actual: FileState, expected: Mapping[str, object]) -> bool:
    for key in ("exists", "sha256", "content_version", "latest_run_id"):
        if key in expected and getattr(actual, key) != expected[key]:
            return False
    return True


def assert_file_cas(path: Path, expected: Mapping[str, object]) -> None:
    actual = file_state(path)
    if not _same_state(actual, expected):
        raise CASMismatch(
            f"CAS冲突：{path.name} 已被其他运行修改；expected={dict(expected)!r}, actual={actual.as_dict()!r}"
        )


class PosixFileLock:
    def __init__(self, path: Path, *, timeout: float = 60.0) -> None:
        self.path = path
        self.timeout = timeout
        self._handle = None

    def __enter__(self) -> "PosixFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as exc:
            raise TxError(f"运行锁无法安全打开：{self.path}: {exc}") from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise TxError(f"运行锁不是普通文件：{self.path}")
        self._handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise LockTimeout(f"等待运行锁超时：{self.path}")
                time.sleep(0.05)
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(f"pid={os.getpid()} acquired_at={utc_now()}\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def output_root_lock(root: Path, *, timeout: float = 60.0) -> PosixFileLock:
    root.mkdir(parents=True, exist_ok=True)
    return PosixFileLock(root / OUTPUT_LOCK_NAME, timeout=timeout)


def workspace_lock(workspace: Path, *, timeout: float = 60.0) -> PosixFileLock:
    if not workspace.is_dir() or workspace.is_symlink():
        raise TxError(f"工作目录不存在或为符号链接：{workspace}")
    return PosixFileLock(workspace / WORKSPACE_LOCK_NAME, timeout=timeout)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    missing: list[Path] = []
    cursor = path.parent
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise TxError(f"写入父路径无效：{cursor}")
    for directory in reversed(missing):
        directory.mkdir()
        fsync_directory(directory.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if mode is not None:
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    atomic_write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def load_manifest(workspace: Path, *, required: bool = True) -> dict[str, object] | None:
    path = workspace / MANIFEST_REL
    if not path.exists():
        if required:
            raise TxError(f"缺少机器权威状态：{path}")
        return None
    if path.is_symlink() or not path.is_file() or path.resolve().parent != path.parent.resolve():
        raise TxError(f"运行清单不是工作目录内普通文件：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TxError(f"运行清单无法读取：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != RUNTIME_SCHEMA:
        raise TxError("运行清单schema无效。")
    if not isinstance(payload.get("transaction_sequence"), int) or payload["transaction_sequence"] < 1:
        raise TxError("运行清单transaction_sequence无效。")
    if "task_timezone" in payload:
        normalize_task_timezone(payload["task_timezone"])
    return payload


def manifest_state(workspace: Path) -> tuple[int, str]:
    manifest = load_manifest(workspace)
    assert manifest is not None
    return int(manifest["transaction_sequence"]), sha256_file(workspace / MANIFEST_REL)


def assert_manifest_cas(workspace: Path, expected_revision: int, expected_sha256: str) -> dict[str, object]:
    manifest = load_manifest(workspace)
    assert manifest is not None
    actual_hash = sha256_file(workspace / MANIFEST_REL)
    actual_revision = int(manifest["transaction_sequence"])
    if actual_revision != expected_revision or actual_hash != expected_sha256:
        raise CASMismatch(
            "运行清单CAS冲突："
            f"expected revision/hash={expected_revision}/{expected_sha256}, "
            f"actual={actual_revision}/{actual_hash}"
        )
    return manifest


def verify_manifest_artifacts(workspace: Path, manifest: Mapping[str, object]) -> None:
    """Reject silent out-of-band artifact edits before a machine-authoritative write."""
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TxError("运行清单artifacts无效。")
    for artifact_type, record in artifacts.items():
        if not isinstance(record, dict):
            raise TxError(f"运行清单成果记录无效：{artifact_type}")
        relative = record.get("path")
        expected_hash = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise TxError(f"运行清单成果路径/哈希无效：{artifact_type}")
        target = workspace / relative
        if _relative_target(workspace, target) != relative or not target.is_file() or target.is_symlink():
            raise CASMismatch(f"清单成果缺失或路径无效：{relative}")
        if sha256_file(target) != expected_hash:
            raise CASMismatch(f"清单成果被绕过事务修改：{relative}")
    runtime_files = manifest.get("runtime_files", {})
    if not isinstance(runtime_files, dict):
        raise TxError("运行清单runtime_files无效。")
    for name, record in runtime_files.items():
        if not isinstance(record, dict):
            raise TxError(f"运行清单机器文件记录无效：{name}")
        relative = record.get("path")
        expected_hash = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise TxError(f"运行清单机器文件路径/哈希无效：{name}")
        target = workspace / relative
        if Path(relative) not in AUDITED_RUNTIME_RELS:
            raise TxError(f"运行清单包含未受控机器文件：{relative}")
        if _relative_target(workspace, target) != relative or not target.is_file() or target.is_symlink():
            raise CASMismatch(f"清单机器文件缺失或路径无效：{relative}")
        if sha256_file(target) != expected_hash:
            raise CASMismatch(f"清单机器文件被绕过事务修改：{relative}")


def build_manifest(
    workspace: Path,
    *,
    identity: Mapping[str, str],
    business_mode: str,
    route: str,
    depth: str,
    task_timezone: str | None,
    latest_run_id: str,
    content_version: str,
    stage: str,
    ready_for_use: bool,
    selected_modules: list[str],
    authorization: Mapping[str, object],
    transaction_sequence: int,
    intake_preflight: Mapping[str, object] | None = None,
    candidate_attestation: Mapping[str, object] | None = None,
    delivery_summary: Mapping[str, object] | None | object = DELIVERY_SUMMARY_UNSET,
    overlay: Mapping[Path, bytes] | None = None,
    deletes: tuple[Path, ...] | list[Path] = (),
) -> dict[str, object]:
    overlay = {path.resolve(): data for path, data in (overlay or {}).items()}
    deleted = {path.resolve(strict=False) for path in deletes}
    artifacts: dict[str, dict[str, object]] = {}
    paths = {path.resolve(): path for path in workspace.glob("*.md") if path.is_file() and not path.is_symlink()}
    for path in overlay:
        if path.parent == workspace.resolve() and path.suffix.casefold() == ".md":
            paths[path] = path
    for resolved, path in sorted(paths.items(), key=lambda pair: pair[1].name):
        if resolved in deleted:
            continue
        raw = overlay.get(resolved, path.read_bytes() if path.exists() else b"")
        try:
            metadata = _frontmatter(raw.decode("utf-8"))
        except UnicodeError as exc:
            raise TxError(f"候选成果不是UTF-8：{path}") from exc
        artifact_type = metadata.get("artifact_type")
        if not artifact_type:
            continue
        record: dict[str, object] = {
            "path": path.name,
            "sha256": sha256_bytes(raw),
            "state": {
                "module_status": metadata.get("module_status", ""),
                "review_status": metadata.get("review_status", ""),
                "connector_status": metadata.get("connector_status", ""),
                "freshness_status": metadata.get("freshness_status", ""),
            },
            "content_version": metadata.get("content_version", ""),
            "latest_run_id": metadata.get("latest_run_id", ""),
        }
        if artifact_type == "visit_strategy":
            record["strategy_variant"] = metadata.get("strategy_variant", "")
        artifacts[artifact_type] = record
    runtime_files: dict[str, dict[str, object]] = {}
    for relative in sorted(AUDITED_RUNTIME_RELS, key=lambda item: item.as_posix()):
        path = workspace / relative
        resolved = path.resolve(strict=False)
        if resolved in deleted:
            continue
        raw = overlay.get(resolved)
        if raw is None:
            if not path.exists():
                continue
            if path.is_symlink() or not path.is_file():
                raise TxError(f"机器审计文件不是普通文件：{relative.as_posix()}")
            raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise TxError(f"机器审计文件不是有效UTF-8 JSON：{relative.as_posix()}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("schema"), str):
            raise TxError(f"机器审计文件缺少schema：{relative.as_posix()}")
        runtime_files[relative.name] = {
            "path": relative.as_posix(),
            "sha256": sha256_bytes(raw),
            "schema": payload.get("schema", ""),
            "context_id": payload.get("context_id", ""),
            "run_id": payload.get("run_id", ""),
        }
    research_names = {relative.name for relative in RESEARCH_RUNTIME_RELS}
    present_research_names = research_names & set(runtime_files)
    evidence_run_id: str | None = None
    if present_research_names:
        if present_research_names != research_names:
            missing = sorted(research_names - present_research_names)
            raise TxError("研究机器文件必须四件套同事务绑定，缺少：" + ", ".join(missing))
        research_run_ids = {
            str(runtime_files[name].get("run_id", "")) for name in research_names
        }
        if len(research_run_ids) != 1 or not next(iter(research_run_ids)):
            raise TxError("研究机器四件套run_id必须非空且完全一致。")
        evidence_run_id = next(iter(research_run_ids))
    manifest: dict[str, object] = {
        "schema": RUNTIME_SCHEMA,
        "context_id": identity.get("context_id", ""),
        "customer_id": identity.get("customer_id", ""),
        "customer_display_name": identity.get("customer_display_name", ""),
        "organization_scope": identity.get("organization_scope", ""),
        "business_mode": business_mode,
        "route": route,
        "depth": depth,
        "latest_run_id": latest_run_id,
        "content_version": content_version,
        "stage": stage,
        "ready_for_use": bool(ready_for_use),
        "selected_modules": selected_modules,
        "authorization": dict(authorization),
        "artifacts": artifacts,
        "runtime_files": runtime_files,
        "transaction_sequence": transaction_sequence,
        "updated_at": utc_now(),
    }
    if candidate_attestation is None:
        existing_manifest_path = workspace / MANIFEST_REL
        if existing_manifest_path.is_file() and not existing_manifest_path.is_symlink():
            try:
                existing_payload = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                existing_payload = None
            if isinstance(existing_payload, dict) and isinstance(existing_payload.get("candidate_attestation"), dict):
                candidate_attestation = existing_payload["candidate_attestation"]
    if candidate_attestation is not None:
        manifest["candidate_attestation"] = dict(candidate_attestation)
    if delivery_summary is DELIVERY_SUMMARY_UNSET:
        inherited_delivery_summary: Mapping[str, object] | None = None
        existing_manifest_path = workspace / MANIFEST_REL
        if existing_manifest_path.is_file() and not existing_manifest_path.is_symlink():
            try:
                existing_payload = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                existing_payload = None
            if isinstance(existing_payload, dict) and isinstance(existing_payload.get("delivery_summary"), dict):
                inherited_delivery_summary = existing_payload["delivery_summary"]
        delivery_summary = inherited_delivery_summary
    if delivery_summary is not None:
        required_summary = {
            "schema",
            "source_artifact_type",
            "recommendation",
            "investment_intensity",
            "primary_action",
            "owner",
            "due_date",
        }
        if set(delivery_summary) != required_summary:
            raise TxError("delivery_summary字段不符合受控决策五元组契约。")
        manifest["delivery_summary"] = dict(delivery_summary)
    if evidence_run_id is not None:
        # Governance mutations advance ``latest_run_id`` without rewriting the
        # research snapshot.  Keep the four-file research lineage explicit so
        # validators can bind evidence to its originating run instead of the
        # latest governance event.
        manifest["evidence_run_id"] = evidence_run_id
    if intake_preflight is None:
        current = load_manifest(workspace, required=False)
        inherited = current.get("intake_preflight") if isinstance(current, dict) else None
        if isinstance(inherited, dict):
            intake_preflight = inherited
    if intake_preflight is not None:
        required_gate_fields = {
            "gate_id",
            "input_sha256",
            "business_mode",
            "evaluated_at",
            "expires_at",
            "request_binding_receipt_id",
            "request_binding_receipt_sha256",
            "request_bundle_id",
            "request_revision",
            "raw_request_sha256",
            "mention_ledger_sha256",
            "subject_resolution",
            "subject_resolution_sha256",
            "safety_authorizations_sha256",
            "safety_directives_sha256",
            "safety_authorization_codes",
        }
        if not required_gate_fields <= set(intake_preflight):
            raise TxError("运行清单intake_preflight缺少可信ready收据字段。")
        manifest["intake_preflight"] = dict(intake_preflight)
        subject_resolution = intake_preflight.get("subject_resolution")
        if not isinstance(subject_resolution, Mapping):
            raise TxError("运行清单intake_preflight.subject_resolution无效。")
        manifest["subject_binding"] = dict(subject_resolution)
    normalized_timezone = normalize_task_timezone(task_timezone)
    if normalized_timezone is not None:
        manifest["task_timezone"] = normalized_timezone
    return manifest


def _relative_target(workspace: Path, path: Path) -> str:
    resolved_workspace = workspace.resolve()
    lexical = Path(os.path.abspath(path))
    try:
        lexical_relative = lexical.relative_to(resolved_workspace)
    except ValueError as exc:
        raise TxError(f"事务目标越出工作目录：{path}") from exc
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(resolved_workspace)
    except ValueError as exc:
        raise TxError(f"事务目标越出工作目录：{path}") from exc
    if lexical_relative != relative:
        raise TxError(f"事务目标路径包含符号链接或重定向：{path}")
    root_artifact = len(relative.parts) == 1 and relative.suffix.casefold() == ".md" and not relative.name.startswith(".")
    archive_letter = len(relative.parts) >= 3 and relative.parts[:2] == ("archive", "letters")
    if not root_artifact and relative not in ({MANIFEST_REL} | AUDITED_RUNTIME_RELS) and not archive_letter:
        raise TxError(
            f"事务只允许根目录成果、runtime清单或archive/letters/普通文件：{path}"
        )
    cursor = workspace
    for component in relative.parts[:-1]:
        cursor = cursor / component
        if cursor.is_symlink():
            raise TxError(f"事务目标父目录不得为符号链接：{cursor}")
    if path.is_symlink():
        raise TxError(f"事务目标不得为符号链接：{path}")
    if path.exists() and not path.is_file():
        raise TxError(f"事务目标必须为普通文件：{path}")
    return relative.as_posix()


def relative_target(workspace: Path, path: Path) -> str:
    """Public target-policy check returning a normalized workspace-relative path."""
    return _relative_target(workspace, path)


def journal_path(workspace: Path) -> Path:
    return workspace / JOURNAL_NAME


def unfinished_transaction(workspace: Path) -> bool:
    return journal_path(workspace).exists()


def _load_journal(workspace: Path) -> dict[str, object]:
    path = journal_path(workspace)
    if path.is_symlink() or not path.is_file():
        raise TxError(f"事务日志无效：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TxError(f"事务日志损坏，禁止自动覆盖：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != JOURNAL_SCHEMA:
        raise TxError("事务日志schema无效。")
    return payload


def _write_journal(workspace: Path, payload: dict[str, object]) -> None:
    payload["updated_at"] = utc_now()
    atomic_write_json(journal_path(workspace), payload)


def _cleanup_transaction(workspace: Path, journal: Mapping[str, object]) -> None:
    path = journal_path(workspace)
    path.unlink(missing_ok=True)
    fsync_directory(workspace)
    relative = str(journal.get("tx_dir", ""))
    tx_dir = (workspace / relative).resolve()
    if tx_dir.parent == workspace.resolve() and tx_dir.name.startswith(TX_DIR_PREFIX):
        shutil.rmtree(tx_dir, ignore_errors=True)
        fsync_directory(workspace)


def _copy_fsync(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    atomic_write_bytes(destination, data)


def _transaction_member(tx_dir: Path, relative: object, bucket: str) -> Path:
    if not isinstance(relative, str):
        raise TxError("事务暂存成员路径无效。")
    rel = Path(relative)
    if (
        len(rel.parts) != 2
        or rel.parts[0] != bucket
        or not re.fullmatch(r"\d{4}\.bin", rel.parts[1])
    ):
        raise TxError(f"事务暂存成员路径无效：{relative}")
    member = tx_dir / rel
    bucket_dir = tx_dir / bucket
    if (
        bucket_dir.is_symlink()
        or member.is_symlink()
        or member.resolve(strict=False).parent != bucket_dir.resolve()
    ):
        raise TxError(f"事务暂存成员包含符号链接或越界：{member}")
    return member


def _kill_failpoint(applied_count: int) -> None:
    configured = os.environ.get("DISCOVERY_CALL_TX_SIGKILL_AFTER", "").strip()
    if configured and configured.isdigit() and int(configured) == applied_count:
        os.kill(os.getpid(), signal.SIGKILL)


def transactional_commit(
    workspace: Path,
    planned: Mapping[Path, bytes | str],
    *,
    deletes: tuple[Path, ...] | list[Path] = (),
    expected: Mapping[Path, Mapping[str, object]] | None = None,
    operation: str,
    postflight: Callable[[Path], None] | None = None,
) -> str:
    """Commit files with CAS and a recoverable write-ahead journal.

    The caller must already hold the workspace lock.  Candidate bytes are
    preserved in the transaction directory so recovery can safely roll forward.
    """
    if unfinished_transaction(workspace):
        raise RecoveryRequired("检测到未完成事务；请先运行recover_workspace.py或init --recover。")
    normalized: dict[Path, bytes | None] = {}
    for path, value in planned.items():
        relative = _relative_target(workspace, path)
        target = workspace / relative
        normalized[target] = value.encode("utf-8") if isinstance(value, str) else value
    for path in deletes:
        relative = _relative_target(workspace, path)
        target = workspace / relative
        if target in normalized:
            raise TxError(f"同一事务不能同时写入和删除：{relative}")
        normalized[target] = None
    if not normalized:
        raise TxError("事务没有候选文件。")
    for path, state in (expected or {}).items():
        assert_file_cas(path, state)

    tx_id = uuid.uuid4().hex
    tx_dir = workspace / f"{TX_DIR_PREFIX}{tx_id}"
    (tx_dir / "new").mkdir(parents=True, exist_ok=False)
    (tx_dir / "old").mkdir()
    entries: list[dict[str, object]] = []
    ordered = sorted(
        normalized.items(),
        key=lambda pair: (pair[0].relative_to(workspace) == MANIFEST_REL, str(pair[0])),
    )
    for index, (target, data) in enumerate(ordered):
        before = file_state(target)
        new_rel = Path("new") / f"{index:04d}.bin"
        old_rel = Path("old") / f"{index:04d}.bin"
        if data is not None:
            atomic_write_bytes(tx_dir / new_rel, data)
        if before.exists:
            _copy_fsync(target, tx_dir / old_rel)
        entries.append(
            {
                "target": target.relative_to(workspace).as_posix(),
                "before": before.as_dict(),
                "after_exists": data is not None,
                "after_sha256": sha256_bytes(data) if data is not None else "",
                "new": new_rel.as_posix() if data is not None else "",
                "old": old_rel.as_posix() if before.exists else "",
            }
        )
    fsync_directory(tx_dir / "new")
    fsync_directory(tx_dir / "old")
    fsync_directory(tx_dir)
    journal: dict[str, object] = {
        "schema": JOURNAL_SCHEMA,
        "tx_id": tx_id,
        "operation": operation,
        "workspace": str(workspace.resolve()),
        "state": "prepared",
        "created_at": utc_now(),
        "tx_dir": tx_dir.name,
        "entries": entries,
        "applied": [],
    }
    _write_journal(workspace, journal)
    journal["state"] = "committing"
    _write_journal(workspace, journal)

    try:
        applied: list[str] = []
        for entry in entries:
            target = workspace / str(entry["target"])
            staged = tx_dir / str(entry["new"])
            before = entry["before"]
            if not isinstance(before, dict):
                raise TxError("事务日志before状态无效。")
            assert_file_cas(target, before)
            if bool(entry.get("after_exists", True)):
                mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
                atomic_write_bytes(target, staged.read_bytes(), mode=mode)
            elif target.exists():
                if target.is_symlink() or not target.is_file():
                    raise TxError(f"拒绝删除非普通事务目标：{target}")
                target.unlink()
                fsync_directory(target.parent)
            applied.append(str(entry["target"]))
            journal["applied"] = list(applied)
            _write_journal(workspace, journal)
            _kill_failpoint(len(applied))
        if postflight is not None:
            postflight(workspace)
        journal["state"] = "committed"
        _write_journal(workspace, journal)
    except BaseException:
        # SystemExit/KeyboardInterrupt can still be repaired while this process
        # is alive. SIGKILL/host loss is handled by recover_transaction().
        try:
            recover_transaction(workspace, strategy="rollback", postflight=None)
        except Exception as rollback_error:
            raise TxError(f"事务失败且自动回滚未完成：{rollback_error}")
        raise
    _cleanup_transaction(workspace, journal)
    return tx_id


def recover_transaction(
    workspace: Path,
    *,
    strategy: str = "auto",
    postflight: Callable[[Path], None] | None = None,
) -> str:
    """Recover the sole journal in a locked workspace.

    auto rolls forward only when every target already equals the candidate;
    otherwise it rolls back. Unexpected third-party hashes stop recovery.
    """
    if strategy not in {"auto", "rollback", "roll-forward"}:
        raise TxError("恢复策略只允许auto、rollback、roll-forward。")
    if not unfinished_transaction(workspace):
        return "no_transaction"
    journal = _load_journal(workspace)
    if journal.get("workspace") != str(workspace.resolve()):
        raise TxError("事务日志workspace与当前目录不一致。")
    tx_relative = str(journal.get("tx_dir", ""))
    tx_reference = workspace / tx_relative
    tx_dir = tx_reference.resolve()
    if (
        Path(tx_relative).name != tx_relative
        or tx_reference.is_symlink()
        or tx_dir.parent != workspace.resolve()
        or not tx_dir.name.startswith(TX_DIR_PREFIX)
        or not tx_dir.is_dir()
    ):
        raise TxError("事务暂存目录缺失或越界，禁止猜测恢复。")
    entries = journal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise TxError("事务日志entries无效。")

    all_after = True
    for entry in entries:
        if not isinstance(entry, dict):
            raise TxError("事务日志entry无效。")
        target = workspace / str(entry.get("target", ""))
        _relative_target(workspace, target)
        actual = file_state(target)
        before = entry.get("before")
        after_hash = entry.get("after_sha256")
        if not isinstance(before, dict) or not isinstance(after_hash, str):
            raise TxError("事务日志哈希状态无效。")
        is_before = _same_state(actual, before)
        after_exists = bool(entry.get("after_exists", True))
        is_after = actual.exists == after_exists and (
            (not after_exists) or actual.sha256 == after_hash
        )
        if not is_before and not is_after:
            raise CASMismatch(f"恢复目标存在第三方修改，停止自动恢复：{target}")
        all_after = all_after and is_after

    selected = strategy
    if strategy == "auto":
        selected = "roll-forward" if all_after else "rollback"
    # A caller that cannot supply a postflight has no trustworthy way to
    # establish that a possibly old candidate authorization still matches the
    # complete recovered state. In that case recovery is deliberately
    # loss-safe: restore the before image even when every target already holds
    # the staged bytes. Candidate-aware callers may request roll-forward only
    # with a fail-closed postflight.
    if selected == "roll-forward" and postflight is None:
        selected = "rollback"

    def restore_before_images() -> None:
        for restore_entry in reversed(entries):
            target = workspace / str(restore_entry["target"])
            before = restore_entry["before"]
            if not isinstance(before, dict):
                raise TxError("事务日志before状态无效。")
            if bool(before.get("exists")):
                backup = _transaction_member(tx_dir, restore_entry.get("old", ""), "old")
                if not backup.is_file() or sha256_file(backup) != before.get("sha256"):
                    raise TxError(f"回滚备份缺失或哈希不符：{backup}")
                mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
                atomic_write_bytes(target, backup.read_bytes(), mode=mode)
            elif target.exists():
                if target.is_symlink() or not target.is_file():
                    raise TxError(f"拒绝删除非普通事务新文件：{target}")
                target.unlink()
                fsync_directory(target.parent)

    if selected == "roll-forward":
        try:
            for entry in entries:
                target = workspace / str(entry["target"])
                after_exists = bool(entry.get("after_exists", True))
                staged = _transaction_member(tx_dir, entry.get("new", ""), "new") if after_exists else None
                if after_exists and (staged is None or not staged.is_file()):
                    raise TxError(f"缺少前滚候选：{staged}")
                if after_exists and not (target.exists() and sha256_file(target) == entry["after_sha256"]):
                    assert staged is not None
                    mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
                    atomic_write_bytes(target, staged.read_bytes(), mode=mode)
                elif not after_exists and target.exists():
                    if target.is_symlink() or not target.is_file():
                        raise TxError(f"拒绝删除非普通事务目标：{target}")
                    target.unlink()
                    fsync_directory(target.parent)
            assert postflight is not None
            postflight(workspace)
            journal["state"] = "committed"
            _write_journal(workspace, journal)
            result = "rolled_forward"
        except BaseException:
            # A failed recovered postflight is still an untrusted after image.
            # Restore every before image before surfacing the error so callers
            # never observe an invalid candidate as the recovered workspace.
            restore_before_images()
            _cleanup_transaction(workspace, journal)
            raise
    else:
        restore_before_images()
        result = "rolled_back"
    _cleanup_transaction(workspace, journal)
    return result


@contextlib.contextmanager
def locked_workspace_from_root(
    output_root: Path,
    resolver: Callable[[], Path],
    *,
    timeout: float = 60.0,
) -> Iterator[Path]:
    """Acquire locks in a single global order: output root, then workspace."""
    with output_root_lock(output_root, timeout=timeout):
        workspace = resolver()
        with workspace_lock(workspace, timeout=timeout):
            yield workspace


def recover_workspace(
    workspace: Path,
    *,
    strategy: str = "auto",
    timeout: float = 60.0,
    postflight: Callable[[Path], None] | None = None,
) -> str:
    """Public recovery API; owns output-root then workspace locks."""
    supplied = workspace.expanduser()
    workspace = supplied.resolve()
    if Path(os.path.abspath(supplied)) != workspace:
        raise TxError(f"工作区路径不得包含符号链接或重定向：{supplied}")
    with output_root_lock(workspace.parent, timeout=timeout):
        with workspace_lock(workspace, timeout=timeout):
            return recover_transaction(workspace, strategy=strategy, postflight=postflight)


def transactional_write(
    workspace: Path,
    planned: Mapping[Path, bytes | str],
    *,
    deletes: tuple[Path, ...] | list[Path] = (),
    expected_manifest_revision: int | None = None,
    expected_manifest_hash: str | None = None,
    expected_files: Mapping[Path, Mapping[str, object]] | None = None,
    operation: str = "runtime_write",
    timeout: float = 60.0,
    postflight: Callable[[Path], None] | None = None,
    result_path: Path | None = None,
) -> dict[str, object]:
    """Public atomic write API; owns both locks, checks manifest CAS, journals writes/deletes."""
    supplied = workspace.expanduser()
    workspace = supplied.resolve()
    if Path(os.path.abspath(supplied)) != workspace:
        raise TxError(f"工作区路径不得包含符号链接或重定向：{supplied}")
    with output_root_lock(workspace.parent, timeout=timeout):
        with workspace_lock(workspace, timeout=timeout):
            if unfinished_transaction(workspace):
                raise RecoveryRequired("检测到未完成事务；必须先恢复。")
            manifest_path = workspace / MANIFEST_REL
            if manifest_path.exists():
                if expected_manifest_revision is None or not expected_manifest_hash:
                    raise CASMismatch("已有运行清单时必须提供expected manifest revision/hash。")
                manifest = assert_manifest_cas(
                    workspace, expected_manifest_revision, expected_manifest_hash
                )
                verify_manifest_artifacts(workspace, manifest)
            elif expected_manifest_revision is not None or expected_manifest_hash:
                raise CASMismatch("调用方期望运行清单，但工作区尚无清单。")
            targets = list(planned) + list(deletes)
            if expected_files is not None:
                missing = [str(path) for path in targets if path not in expected_files]
                if missing:
                    raise CASMismatch("expected_files未覆盖全部事务目标：" + ", ".join(missing))
                expected = dict(expected_files)
            else:
                expected = {path: file_state(path).as_dict() for path in targets}
            tx_id = transactional_commit(
                workspace,
                planned,
                deletes=deletes,
                expected=expected,
                operation=operation,
                postflight=postflight,
            )
            result: dict[str, object] = {"transaction_id": tx_id}
            if manifest_path.exists():
                revision, digest = manifest_state(workspace)
                result.update({"manifest_revision": revision, "manifest_sha256": digest})
            if result_path is not None:
                resolved_result = result_path.resolve(strict=False)
                _relative_target(workspace, resolved_result)
                result["result_path"] = str(resolved_result)
            return result
