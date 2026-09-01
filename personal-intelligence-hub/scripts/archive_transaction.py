from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from briefing_gate import validate_briefing_data


JsonGate = Callable[[dict[str, Any]], tuple[list[str], list[str]]]
MarkdownRenderer = Callable[[dict[str, Any]], str]
ReplaceFunction = Callable[[Path, Path], None]
PrecommitValidator = Callable[[], dict[str, str | None] | None]
PostcommitAction = Callable[["ArchiveCommitResult"], None]


class ArchiveTransactionError(RuntimeError):
    """Raised when a briefing pair cannot be committed or restored safely."""


class ArchivePostcommitError(ArchiveTransactionError):
    """Raised after the formal set commits but a derived postcommit action fails."""

    def __init__(self, message: str, result: "ArchiveCommitResult") -> None:
        super().__init__(message)
        self.result = result


JOURNAL_NAME = "transaction.json"
WINDOWS_STAGING_CREATE_ATTEMPTS = 32


@dataclass(frozen=True)
class ArchiveCommitResult:
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    json_sha256: str
    markdown_sha256: str
    gate_warnings: tuple[str, ...]


@dataclass(frozen=True)
class _TargetPaths:
    json: Path
    markdown: Path
    manifest: Path

    def ordered(self) -> tuple[Path, Path, Path]:
        return self.json, self.markdown, self.manifest


@dataclass(frozen=True)
class _RollbackRecord:
    backup: Path | None
    before_sha256: str | None
    promoted_sha256: str


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _validate_report_date(report_date: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ArchiveTransactionError("report_date must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(report_date)
    except ValueError as exc:
        raise ArchiveTransactionError("report_date must be a valid calendar date") from exc
    if parsed.isoformat() != report_date:
        raise ArchiveTransactionError("report_date must use canonical YYYY-MM-DD")
    return parsed


def _validate_identity(payload: dict[str, Any], report_date: str, run_id: str) -> None:
    if not isinstance(payload, dict):
        raise ArchiveTransactionError("payload must be a JSON object")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ArchiveTransactionError("run_id cannot be empty")
    _validate_report_date(report_date)
    payload_report_date = payload.get("report_date")
    if payload_report_date is not None and payload_report_date != report_date:
        raise ArchiveTransactionError("report_date does not match payload.report_date")
    payload_run_id = payload.get("run_id")
    if payload_run_id is not None and payload_run_id != run_id:
        raise ArchiveTransactionError("run_id does not match payload.run_id")


def _validate_with_gate(
    payload: dict[str, Any], gate: JsonGate
) -> tuple[str, ...]:
    try:
        errors, warnings = gate(payload)
    except Exception as exc:
        raise ArchiveTransactionError(f"briefing gate raised an exception: {exc}") from exc
    if errors:
        raise ArchiveTransactionError(
            "briefing gate failed: " + "; ".join(str(error) for error in errors)
        )
    return tuple(str(warning) for warning in warnings)


def _prepare_markdown(
    payload: dict[str, Any],
    *,
    markdown: str | None,
    render_markdown: MarkdownRenderer | None,
) -> str:
    if (markdown is None) == (render_markdown is None):
        raise ArchiveTransactionError(
            "provide exactly one of markdown or render_markdown"
        )
    payload_before = _json_bytes(payload)
    try:
        rendered = render_markdown(payload) if render_markdown is not None else markdown
    except Exception as exc:
        raise ArchiveTransactionError(f"Markdown rendering failed: {exc}") from exc
    if _json_bytes(payload) != payload_before:
        raise ArchiveTransactionError("Markdown renderer must not mutate the payload")
    if not isinstance(rendered, str) or not rendered.strip():
        raise ArchiveTransactionError("Markdown content must be a non-empty string")
    if "\x00" in rendered:
        raise ArchiveTransactionError("Markdown content cannot contain NUL bytes")
    try:
        rendered.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ArchiveTransactionError("Markdown content must be valid UTF-8") from exc
    return rendered


def _target_paths(news_dir: Path, report_date: str) -> _TargetPaths:
    compact_date = report_date.replace("-", "")
    stem = f"intelligence_{compact_date}_briefing"
    return _TargetPaths(
        json=news_dir / f"{stem}.json",
        markdown=news_dir / f"{stem}.md",
        manifest=news_dir / f"{stem}.manifest.json",
    )


def _current_target_state(targets: _TargetPaths) -> dict[str, str | None]:
    return {
        target.name: _sha256_bytes(target.read_bytes()) if target.is_file() else None
        for target in targets.ordered()
    }


def _fsync_directory(path: Path) -> bool:
    """Best-effort directory metadata flush.

    POSIX exposes directory descriptors that can be fsynced after create,
    replace, and unlink operations. Python does not expose an equivalent
    portable Windows primitive, so file contents are flushed there while the
    final directory-entry durability remains an operating-system boundary.
    """

    if os.name == "nt":
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        os.fsync(descriptor)
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return True


def _write_bytes_fsync(path: Path, content: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _copy2_fsync(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    _fsync_file(destination)
    _fsync_directory(destination.parent)


def _create_windows_staging_root(root: Path) -> Path:
    """Create a same-directory staging root that inherits the parent DACL.

    Python 3.13 gives ``tempfile.mkdtemp`` a private Windows DACL via mode
    ``0o700``. A same-volume rename preserves that descriptor, so files created
    below such a directory can retain staging-only permissions after promotion.
    Windows ignores modes other than ``0o700`` and applies the parent's normal
    inheritance rules, while exclusive directory creation keeps allocation
    race-free.
    """

    for _ in range(WINDOWS_STAGING_CREATE_ATTEMPTS):
        candidate = root / f".pih-stage-{uuid.uuid4().hex}"
        try:
            candidate.mkdir(mode=0o777, parents=False, exist_ok=False)
        except FileExistsError:
            continue
        except OSError as exc:
            raise ArchiveTransactionError(
                f"could not create Windows archive staging under {root}: {exc}"
            ) from exc
        return candidate
    raise ArchiveTransactionError(
        "could not allocate a unique Windows archive staging directory"
    )


def _create_staging_root(root: Path) -> Path:
    if os.name == "nt":
        return _create_windows_staging_root(root)
    return Path(tempfile.mkdtemp(prefix=".pih-stage-", dir=root))


def _write_journal(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    _write_bytes_fsync(temporary, _json_bytes(payload))
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_mutex_name(news_dir: Path) -> str:
    """Return one machine-wide mutex name for a canonical archive directory."""

    digest = hashlib.sha256(
        str(news_dir.resolve()).casefold().encode("utf-8")
    ).hexdigest()
    return "Global\\PIHArchive-" + digest


@contextmanager
def _archive_process_guard(news_dir: Path) -> Iterator[None]:
    """Serialize lock recovery and archive ownership at the operating-system level."""

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        wait_object_0 = 0x00000000
        wait_abandoned = 0x00000080
        wait_timeout = 0x00000102
        mutex_name = _windows_mutex_name(news_dir)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            raise ArchiveTransactionError(
                f"could not create archive process guard: {ctypes.get_last_error()}"
            )
        acquired = False
        try:
            state = int(kernel32.WaitForSingleObject(handle, 0))
            if state == wait_timeout:
                raise ArchiveTransactionError(
                    f"another archive transaction owns {news_dir}"
                )
            if state not in {wait_object_0, wait_abandoned}:
                raise ArchiveTransactionError(
                    f"could not acquire archive process guard: state={state}"
                )
            acquired = True
            yield
        finally:
            if acquired:
                kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)
        return

    guard_path = news_dir / ".pih-archive.guard"
    descriptor = os.open(guard_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArchiveTransactionError(
                f"another archive transaction owns {news_dir}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _verify_committed_recovery(
    targets: _TargetPaths,
    *,
    run_id: str,
    report_date: str,
    gate: JsonGate = validate_briefing_data,
) -> None:
    try:
        json_bytes = targets.json.read_bytes()
        markdown_bytes = targets.markdown.read_bytes()
        manifest_bytes = targets.manifest.read_bytes()
        payload = json.loads(json_bytes.decode("utf-8"))
        markdown = markdown_bytes.decode("utf-8")
        sidecar = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveTransactionError(
            f"committed target set is missing or unreadable: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ArchiveTransactionError("committed JSON must be an object")
    if not isinstance(sidecar, dict):
        raise ArchiveTransactionError("committed sidecar must be an object")
    if not markdown.strip() or "\x00" in markdown:
        raise ArchiveTransactionError("committed Markdown is empty or contains NUL")

    _validate_identity(payload, report_date, run_id)
    expected_identity = {
        "contract_version": "1.0",
        "run_id": run_id,
        "report_date": report_date,
        "json_file": targets.json.name,
        "markdown_file": targets.markdown.name,
    }
    for name, expected in expected_identity.items():
        if sidecar.get(name) != expected:
            raise ArchiveTransactionError(
                f"committed sidecar {name} does not match the recovery journal"
            )
    if sidecar.get("schema_version") != payload.get("schema_version"):
        raise ArchiveTransactionError(
            "committed sidecar schema_version does not match the JSON"
        )
    item_count = sidecar.get("item_count")
    items = payload.get("top_10")
    if (
        isinstance(item_count, bool)
        or not isinstance(item_count, int)
        or not isinstance(items, list)
        or item_count != len(items)
    ):
        raise ArchiveTransactionError(
            "committed sidecar item_count does not match the JSON"
        )

    json_hash = _sha256_bytes(json_bytes)
    markdown_hash = _sha256_bytes(markdown_bytes)
    if sidecar.get("json_sha256") != json_hash:
        raise ArchiveTransactionError(
            "committed JSON hash does not match the sidecar"
        )
    if sidecar.get("markdown_sha256") != markdown_hash:
        raise ArchiveTransactionError(
            "committed Markdown hash does not match the sidecar"
        )
    warnings = _validate_with_gate(payload, gate)
    if sidecar.get("gate_warnings") != list(warnings):
        raise ArchiveTransactionError(
            "committed sidecar gate_warnings do not match the briefing gate"
        )


def _remove_recovered_staging(staging_root: Path) -> None:
    try:
        shutil.rmtree(staging_root)
    except OSError as exc:
        raise ArchiveTransactionError(
            f"could not remove verified recovery staging {staging_root}: {exc}"
        ) from exc
    _fsync_directory(staging_root.parent)


def _rollback_state_failures(
    snapshots: dict[Path, _RollbackRecord],
) -> list[str]:
    failures: list[str] = []
    for target, snapshot in snapshots.items():
        try:
            current_sha256 = (
                _sha256_bytes(target.read_bytes()) if target.is_file() else None
            )
            if current_sha256 != snapshot.before_sha256:
                failures.append(
                    f"{target}: restored hash does not match before_sha256"
                )
        except OSError as exc:
            failures.append(f"{target}: could not verify restored state: {exc}")
    return failures


def _recover_staging(news_dir: Path) -> None:
    root = news_dir.resolve()
    for staging_root in sorted(news_dir.glob(".pih-stage-*")):
        if not staging_root.is_dir():
            continue
        try:
            staging_resolved = staging_root.resolve()
            staging_resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ArchiveTransactionError(
                f"invalid recovery journal staging root: {staging_root}"
            ) from exc
        journal_path = staging_root / JOURNAL_NAME
        if not journal_path.is_file():
            shutil.rmtree(staging_root, ignore_errors=True)
            continue
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArchiveTransactionError(
                f"cannot recover unreadable transaction journal: {journal_path}"
            ) from exc

        def invalid(reason: str) -> ArchiveTransactionError:
            return ArchiveTransactionError(
                f"invalid recovery journal {journal_path}: {reason}"
            )

        if not isinstance(journal, dict):
            raise invalid("root must be a JSON object")
        if journal.get("contract_version") != "1.0":
            raise invalid("contract_version must be 1.0")
        run_id = journal.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise invalid("run_id must be a non-empty string")
        report_date = journal.get("report_date")
        if not isinstance(report_date, str):
            raise invalid("report_date must be present")
        try:
            _validate_report_date(report_date)
        except ArchiveTransactionError as exc:
            raise invalid(str(exc)) from exc
        phase = journal.get("phase")
        if phase not in {"promoting", "committed"}:
            raise invalid("phase must be promoting or committed")
        promoted_count = journal.get("promoted_count")
        if (
            isinstance(promoted_count, bool)
            or not isinstance(promoted_count, int)
            or promoted_count < 0
            or promoted_count > 3
        ):
            raise invalid("promoted_count must be an integer from 0 to 3")
        if phase == "committed" and promoted_count != 3:
            raise invalid("a committed journal must record all three promotions")

        records = journal.get("snapshots")
        if not isinstance(records, list) or len(records) != 3:
            raise invalid("snapshots must contain the exact three-file set")
        targets = _target_paths(root, report_date)
        expected_targets = tuple(target.resolve() for target in targets.ordered())
        backup_root = (staging_resolved / "backup").resolve()
        validated_records: list[tuple[Path, _RollbackRecord]] = []
        for index, (record, expected_target) in enumerate(
            zip(records, expected_targets)
        ):
            if not isinstance(record, dict):
                raise invalid(f"snapshot {index} must be an object")
            target_value = record.get("target")
            if not isinstance(target_value, str) or not target_value:
                raise invalid(f"snapshot {index} target must be a path")
            try:
                target = Path(target_value).resolve()
                target.relative_to(root)
            except (OSError, ValueError) as exc:
                raise invalid(f"snapshot {index} target is outside the news root") from exc
            if target != expected_target:
                raise invalid(
                    f"snapshot {index} target does not match {expected_target.name}"
                )

            backup_value = record.get("backup")
            backup_hash = record.get("backup_sha256")
            if backup_hash is not None and (
                not isinstance(backup_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", backup_hash) is None
            ):
                raise invalid(f"snapshot {index} backup_sha256 is invalid")
            backup: Path | None = None
            if backup_value is not None:
                if not isinstance(backup_value, str) or not backup_value:
                    raise invalid(f"snapshot {index} backup must be a path or null")
                try:
                    backup = Path(backup_value).resolve()
                    backup.relative_to(backup_root)
                except (OSError, ValueError) as exc:
                    raise invalid(
                        f"snapshot {index} backup is outside the transaction backup root"
                    ) from exc
                expected_backup = (
                    backup_root / f"{index}-{expected_target.name}.previous"
                ).resolve()
                if backup != expected_backup:
                    raise invalid(
                        f"snapshot {index} backup does not match the expected file"
                    )
            elif backup_hash is not None:
                raise invalid(f"snapshot {index} has a hash without a backup")

            before_hash = record.get("before_sha256")
            promoted_hash = record.get("promoted_sha256")
            if before_hash is not None and (
                not isinstance(before_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", before_hash) is None
            ):
                raise invalid(f"snapshot {index} before_sha256 is invalid")
            if (
                not isinstance(promoted_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", promoted_hash) is None
            ):
                raise invalid(f"snapshot {index} promoted_sha256 is required")
            if backup is None and before_hash is not None:
                raise invalid(
                    f"snapshot {index} has before_sha256 without a backup"
                )
            if backup is not None and (
                before_hash is None or backup_hash != before_hash
            ):
                raise invalid(
                    f"snapshot {index} backup/before hashes do not match"
                )
            validated_records.append(
                (
                    target,
                    _RollbackRecord(
                        backup=backup,
                        before_sha256=before_hash,
                        promoted_sha256=promoted_hash,
                    ),
                )
            )

        def prevalidated_snapshots() -> dict[Path, _RollbackRecord]:
            snapshots: dict[Path, _RollbackRecord] = {}
            for index, (target, snapshot) in enumerate(validated_records):
                if snapshot.backup is not None:
                    if not snapshot.backup.is_file():
                        raise invalid(f"snapshot {index} backup is missing")
                    try:
                        backup_bytes = snapshot.backup.read_bytes()
                    except OSError as exc:
                        raise invalid(
                            f"snapshot {index} backup is unreadable: {exc}"
                        ) from exc
                    if (
                        _sha256_bytes(backup_bytes) != snapshot.before_sha256
                    ):
                        raise invalid(
                            f"snapshot {index} backup does not match before_sha256"
                        )
                snapshots[target] = snapshot
            return snapshots

        recovery = journal.get("recovery")
        if recovery is not None:
            if not isinstance(recovery, dict) or recovery.get("status") not in {
                "rolled_back_after_invalid_commit",
                "rollback_incomplete",
            }:
                raise invalid("recovery diagnostic is invalid")
            snapshots = prevalidated_snapshots()
            failures = _rollback_state_failures(snapshots)
            if failures:
                failures = _rollback(snapshots) + _rollback_state_failures(snapshots)
            if failures:
                raise ArchiveTransactionError(
                    "previous committed recovery rollback is still incomplete; "
                    f"staging and backups remain at {staging_root}: "
                    + "; ".join(failures)
                )
            raise ArchiveTransactionError(
                "previous committed recovery remains quarantined after rollback; "
                f"staging and backups remain at {staging_root}: "
                + str(recovery.get("validation_error") or "unknown validation error")
            )

        if phase == "committed":
            try:
                _verify_committed_recovery(
                    targets,
                    run_id=run_id,
                    report_date=report_date,
                )
            except ArchiveTransactionError as validation_exc:
                try:
                    snapshots = prevalidated_snapshots()
                except ArchiveTransactionError as backup_exc:
                    raise ArchiveTransactionError(
                        "committed archive recovery validation failed and rollback is "
                        f"impossible; staging remains at {staging_root}: "
                        f"{validation_exc}; {backup_exc}"
                    ) from backup_exc
                failures = _rollback(snapshots) + _rollback_state_failures(snapshots)
                journal["recovery"] = {
                    "status": (
                        "rollback_incomplete"
                        if failures
                        else "rolled_back_after_invalid_commit"
                    ),
                    "validation_error": str(validation_exc),
                    "recovered_at": datetime.now().astimezone().isoformat(),
                    "rollback_failures": failures,
                }
                diagnostic_failure: str | None = None
                try:
                    _write_journal(journal_path, journal)
                except OSError as exc:
                    diagnostic_failure = str(exc)
                if failures:
                    message = (
                        "committed archive recovery validation failed and rollback was "
                        f"incomplete; staging and backups remain at {staging_root}: "
                        + "; ".join(failures)
                    )
                else:
                    message = (
                        "committed archive recovery validation failed; prior targets were "
                        f"restored and staging/backups remain quarantined at {staging_root}: "
                        f"{validation_exc}"
                    )
                if diagnostic_failure is not None:
                    message += f"; could not persist recovery diagnostic: {diagnostic_failure}"
                raise ArchiveTransactionError(message) from validation_exc
            _remove_recovered_staging(staging_root)
            continue

        staged_sidecar = staging_resolved / expected_targets[2].name
        identity_sidecar = (
            staged_sidecar if staged_sidecar.is_file() else expected_targets[2]
        )
        try:
            sidecar = json.loads(identity_sidecar.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise invalid("transaction sidecar is missing or unreadable") from exc
        if not isinstance(sidecar, dict):
            raise invalid("transaction sidecar must be a JSON object")
        expected_sidecar_identity = {
            "run_id": run_id,
            "report_date": report_date,
            "json_file": expected_targets[0].name,
            "markdown_file": expected_targets[1].name,
        }
        for name, expected_value in expected_sidecar_identity.items():
            if sidecar.get(name) != expected_value:
                raise invalid(
                    f"transaction sidecar {name} does not match the journal"
                )

        snapshots = prevalidated_snapshots()
        failures = _rollback(snapshots) + _rollback_state_failures(snapshots)
        if failures:
            raise ArchiveTransactionError(
                "stale transaction recovery was incomplete: " + "; ".join(failures)
            )
        _remove_recovered_staging(staging_root)


def _reclaim_stale_lock(lock_path: Path, news_dir: Path) -> bool:
    try:
        observed = lock_path.read_bytes()
        payload = json.loads(observed.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    pid = payload.get("pid")
    owner_host = str(payload.get("hostname") or "")
    if owner_host != socket.gethostname() or not isinstance(pid, int):
        return False
    if _pid_is_running(pid):
        return False
    _recover_staging(news_dir)
    try:
        if lock_path.read_bytes() != observed:
            return False
        lock_path.unlink()
    except FileNotFoundError:
        return False
    return True


def _release_owned_metadata_lock(lock_path: Path, owner_token: str) -> None:
    """Remove only the metadata lock created by the current owner."""

    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if payload.get("owner_token") != owner_token:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def _archive_metadata_lock(news_dir: Path, run_id: str) -> Iterator[None]:
    lock_path = news_dir / ".pih-archive.lock"
    if lock_path.exists():
        if not _reclaim_stale_lock(lock_path, news_dir):
            raise ArchiveTransactionError(
                f"another archive transaction owns {lock_path}"
            )
    else:
        _recover_staging(news_dir)
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as exc:
        raise ArchiveTransactionError(
            f"another archive transaction owns {lock_path}"
        ) from exc
    owner_token = uuid.uuid4().hex
    metadata_written = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    {
                        "run_id": run_id,
                        "owner_token": owner_token,
                        "pid": os.getpid(),
                        "hostname": socket.gethostname(),
                        "acquired_at": datetime.now().astimezone().isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
            handle.flush()
            os.fsync(handle.fileno())
        metadata_written = True
        yield
    finally:
        if metadata_written:
            _release_owned_metadata_lock(lock_path, owner_token)
        else:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


@contextmanager
def _archive_lock(news_dir: Path, run_id: str) -> Iterator[None]:
    with _archive_process_guard(news_dir):
        with _archive_metadata_lock(news_dir, run_id):
            yield


def _write_staged_files(
    staging_root: Path,
    targets: _TargetPaths,
    payload: dict[str, Any],
    markdown: str,
    sidecar: dict[str, Any],
) -> _TargetPaths:
    staged = _TargetPaths(
        json=staging_root / targets.json.name,
        markdown=staging_root / targets.markdown.name,
        manifest=staging_root / targets.manifest.name,
    )
    _write_bytes_fsync(staged.json, _json_bytes(payload))
    _write_bytes_fsync(staged.markdown, markdown.encode("utf-8"))
    _write_bytes_fsync(staged.manifest, _json_bytes(sidecar))
    return staged


def _verify_staged_files(
    staged: _TargetPaths,
    payload: dict[str, Any],
    expected_markdown: str,
    gate: JsonGate,
    render_markdown: MarkdownRenderer | None,
) -> tuple[str, str, tuple[str, ...]]:
    try:
        loaded_payload = json.loads(staged.json.read_text(encoding="utf-8"))
        loaded_markdown = staged.markdown.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveTransactionError(f"could not reread staged files: {exc}") from exc
    if loaded_payload != payload:
        raise ArchiveTransactionError("staged JSON does not match the input payload")
    warnings = _validate_with_gate(loaded_payload, gate)
    if loaded_markdown != expected_markdown:
        raise ArchiveTransactionError("staged Markdown does not match the strict input")
    if render_markdown is not None:
        try:
            rerendered = render_markdown(loaded_payload)
        except Exception as exc:
            raise ArchiveTransactionError(
                f"Markdown rerender verification failed: {exc}"
            ) from exc
        if rerendered != loaded_markdown:
            raise ArchiveTransactionError(
                "Markdown renderer is not deterministic for the staged payload"
            )
    return (
        _sha256_bytes(staged.json.read_bytes()),
        _sha256_bytes(staged.markdown.read_bytes()),
        warnings,
    )


def _snapshot_existing(
    targets: _TargetPaths, staged: _TargetPaths, backup_root: Path
) -> dict[Path, _RollbackRecord]:
    backup_root.mkdir(parents=True, exist_ok=False)
    _fsync_directory(backup_root.parent)
    snapshots: dict[Path, _RollbackRecord] = {}
    for index, (target, promoted) in enumerate(
        zip(targets.ordered(), staged.ordered())
    ):
        promoted_sha256 = _sha256_bytes(promoted.read_bytes())
        if not target.exists():
            snapshots[target] = _RollbackRecord(
                backup=None,
                before_sha256=None,
                promoted_sha256=promoted_sha256,
            )
            continue
        backup = backup_root / f"{index}-{target.name}.previous"
        _copy2_fsync(target, backup)
        before_sha256 = _sha256_bytes(backup.read_bytes())
        snapshots[target] = _RollbackRecord(
            backup=backup,
            before_sha256=before_sha256,
            promoted_sha256=promoted_sha256,
        )
    _fsync_directory(backup_root)
    return snapshots


def _rollback(
    snapshots: dict[Path, _RollbackRecord],
    *,
    allowed_current_sha256: dict[str, str | None] | None = None,
) -> list[str]:
    failures: list[str] = []
    for target, snapshot in snapshots.items():
        try:
            current_sha256 = (
                _sha256_bytes(target.read_bytes()) if target.is_file() else None
            )
        except OSError as exc:
            failures.append(f"{target}: could not read rollback target: {exc}")
            continue
        allowed_hashes: set[str | None] = {
            snapshot.before_sha256,
            snapshot.promoted_sha256,
        }
        if allowed_current_sha256 is not None:
            allowed_hashes.add(allowed_current_sha256.get(target.name))
        if current_sha256 not in allowed_hashes:
            failures.append(
                f"{target}: rollback CAS mismatch; current hash is neither "
                "before_sha256 nor promoted_sha256"
            )
    if failures:
        return failures

    for target, snapshot in reversed(tuple(snapshots.items())):
        try:
            current_sha256 = (
                _sha256_bytes(target.read_bytes()) if target.is_file() else None
            )
            if current_sha256 == snapshot.before_sha256:
                continue
            allowed_hashes: set[str | None] = {snapshot.promoted_sha256}
            if allowed_current_sha256 is not None:
                allowed_hashes.add(allowed_current_sha256.get(target.name))
            if current_sha256 not in allowed_hashes:
                failures.append(
                    f"{target}: rollback CAS changed during recovery"
                )
                break
            if snapshot.backup is None:
                target.unlink(missing_ok=True)
                _fsync_directory(target.parent)
            else:
                _copy2_fsync(snapshot.backup, target)
        except OSError as exc:
            failures.append(f"{target}: {exc}")
            break
    return failures


def _verify_committed_files(
    targets: _TargetPaths,
    payload: dict[str, Any],
    expected_markdown: str,
    expected_sidecar: dict[str, Any],
    gate: JsonGate,
) -> ArchiveCommitResult:
    try:
        json_bytes = targets.json.read_bytes()
        markdown_bytes = targets.markdown.read_bytes()
        manifest_bytes = targets.manifest.read_bytes()
        loaded_payload = json.loads(json_bytes.decode("utf-8"))
        loaded_markdown = markdown_bytes.decode("utf-8")
        loaded_sidecar = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveTransactionError(f"could not reread committed files: {exc}") from exc

    if loaded_payload != payload:
        raise ArchiveTransactionError("committed JSON differs from the staged payload")
    warnings = _validate_with_gate(loaded_payload, gate)
    if loaded_markdown != expected_markdown:
        raise ArchiveTransactionError("committed Markdown differs from the staged content")
    if loaded_sidecar != expected_sidecar:
        raise ArchiveTransactionError("committed sidecar differs from the staged sidecar")

    json_hash = _sha256_bytes(json_bytes)
    markdown_hash = _sha256_bytes(markdown_bytes)
    if loaded_sidecar.get("json_sha256") != json_hash:
        raise ArchiveTransactionError("committed JSON hash does not match the sidecar")
    if loaded_sidecar.get("markdown_sha256") != markdown_hash:
        raise ArchiveTransactionError("committed Markdown hash does not match the sidecar")
    return ArchiveCommitResult(
        json_path=targets.json,
        markdown_path=targets.markdown,
        manifest_path=targets.manifest,
        json_sha256=json_hash,
        markdown_sha256=markdown_hash,
        gate_warnings=warnings,
    )


def commit_briefing_pair(
    payload: dict[str, Any],
    *,
    news_dir: Path | str,
    report_date: str,
    run_id: str,
    markdown: str | None = None,
    render_markdown: MarkdownRenderer | None = None,
    gate: JsonGate = validate_briefing_data,
    replace_fn: ReplaceFunction | None = None,
    expected_target_state: dict[str, str | None] | None = None,
    precommit_validator: PrecommitValidator | None = None,
    postcommit_action: PostcommitAction | None = None,
) -> ArchiveCommitResult:
    """Commit a validated briefing JSON/Markdown pair with rollback recovery.

    The function owns only the formal JSON, Markdown, and commit sidecar. History
    or other indexes must be updated by the caller after this function returns.
    """

    _validate_identity(payload, report_date, run_id)
    gate_warnings = _validate_with_gate(payload, gate)
    markdown_text = _prepare_markdown(
        payload,
        markdown=markdown,
        render_markdown=render_markdown,
    )
    root = Path(news_dir)
    root.mkdir(parents=True, exist_ok=True)
    targets = _target_paths(root, report_date)
    promote = replace_fn or os.replace

    with _archive_lock(root, run_id):
        effective_target_state = expected_target_state
        if precommit_validator is not None:
            validated_target_state = precommit_validator()
            if validated_target_state is not None:
                normalized_target_state = {
                    str(name): str(value) if value is not None else None
                    for name, value in validated_target_state.items()
                }
                if (
                    effective_target_state is not None
                    and normalized_target_state != effective_target_state
                ):
                    raise ArchiveTransactionError(
                        "precommit validator target state conflicts with the caller"
                    )
                effective_target_state = normalized_target_state
        if (
            effective_target_state is not None
            and _current_target_state(targets) != effective_target_state
        ):
            raise ArchiveTransactionError(
                "archive targets changed after the run snapshot; restart the run"
            )
        staging_root = _create_staging_root(root)
        preserve_staging = False
        try:
            preliminary_sidecar = {
                "contract_version": "1.0",
                "run_id": run_id,
                "report_date": report_date,
                "schema_version": payload.get("schema_version"),
                "json_file": targets.json.name,
                "markdown_file": targets.markdown.name,
                "json_sha256": "pending",
                "markdown_sha256": "pending",
                "item_count": len(payload.get("top_10", [])),
                "committed_at": datetime.now().astimezone().isoformat(),
                "gate_warnings": list(gate_warnings),
            }
            staged = _write_staged_files(
                staging_root,
                targets,
                payload,
                markdown_text,
                preliminary_sidecar,
            )
            json_hash, markdown_hash, staged_warnings = _verify_staged_files(
                staged,
                payload,
                markdown_text,
                gate,
                render_markdown,
            )
            sidecar = {
                **preliminary_sidecar,
                "json_sha256": json_hash,
                "markdown_sha256": markdown_hash,
                "gate_warnings": list(staged_warnings),
            }
            _write_bytes_fsync(staged.manifest, _json_bytes(sidecar))
            try:
                if json.loads(staged.manifest.read_text(encoding="utf-8")) != sidecar:
                    raise ArchiveTransactionError(
                        "staged sidecar does not match the commit contract"
                    )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ArchiveTransactionError(
                    f"could not reread staged sidecar: {exc}"
                ) from exc

            snapshots = _snapshot_existing(
                targets, staged, staging_root / "backup"
            )
            journal_path = staging_root / JOURNAL_NAME
            journal = {
                "contract_version": "1.0",
                "run_id": run_id,
                "report_date": report_date,
                "phase": "promoting",
                "promoted_count": 0,
                "snapshots": [
                    {
                        "target": str(target.resolve()),
                        "backup": (
                            str(snapshot.backup.resolve())
                            if snapshot.backup is not None
                            else None
                        ),
                        "backup_sha256": snapshot.before_sha256,
                        "before_sha256": snapshot.before_sha256,
                        "promoted_sha256": snapshot.promoted_sha256,
                    }
                    for target, snapshot in snapshots.items()
                ],
            }
            _write_journal(journal_path, journal)
            try:
                for index, (source, destination) in enumerate(
                    zip(staged.ordered(), targets.ordered()), start=1
                ):
                    promote(source, destination)
                    _fsync_file(destination)
                    _fsync_directory(destination.parent)
                    journal["promoted_count"] = index
                    _write_journal(journal_path, journal)
            except Exception as exc:
                rollback_failures = _rollback(snapshots)
                if rollback_failures:
                    preserve_staging = True
                    raise ArchiveTransactionError(
                        "promotion failed and rollback was incomplete; recovery files remain "
                        f"at {staging_root}: {'; '.join(rollback_failures)}"
                    ) from exc
                raise ArchiveTransactionError(f"promotion failed: {exc}") from exc

            postcommit_ran = False
            try:
                result = _verify_committed_files(
                    targets,
                    payload,
                    markdown_text,
                    sidecar,
                    gate,
                )
                journal["phase"] = "committed"
                _write_journal(journal_path, journal)
                if postcommit_action is not None:
                    postcommit_ran = True
                    try:
                        postcommit_action(result)
                    except Exception as exc:
                        try:
                            _verify_committed_files(
                                targets,
                                payload,
                                markdown_text,
                                sidecar,
                                gate,
                            )
                        except Exception as verification_exc:
                            raise ArchiveTransactionError(
                                "postcommit action changed committed archive bytes"
                            ) from verification_exc
                        raise ArchivePostcommitError(
                            "formal archive committed, but the postcommit action failed: "
                            + str(exc),
                            result,
                        ) from exc
                    result = _verify_committed_files(
                        targets,
                        payload,
                        markdown_text,
                        sidecar,
                        gate,
                    )
                return result
            except ArchivePostcommitError:
                raise
            except Exception as exc:
                rollback_failures = _rollback(
                    snapshots,
                    allowed_current_sha256=(
                        _current_target_state(targets) if postcommit_ran else None
                    ),
                )
                if rollback_failures:
                    preserve_staging = True
                    raise ArchiveTransactionError(
                        "final verification failed and rollback was incomplete; recovery files "
                        f"remain at {staging_root}: {'; '.join(rollback_failures)}"
                    ) from exc
                raise ArchiveTransactionError(
                    f"final verification failed: {exc}"
                ) from exc
        except (KeyboardInterrupt, SystemExit):
            preserve_staging = True
            raise
        finally:
            if not preserve_staging:
                shutil.rmtree(staging_root, ignore_errors=True)
