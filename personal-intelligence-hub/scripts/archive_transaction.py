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


def _write_journal(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_json_bytes(payload))
    os.replace(temporary, path)


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


def _recover_staging(news_dir: Path) -> None:
    root = news_dir.resolve()
    for staging_root in sorted(news_dir.glob(".pih-stage-*")):
        if not staging_root.is_dir():
            continue
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
        if journal.get("phase") == "committed":
            shutil.rmtree(staging_root, ignore_errors=True)
            continue
        failures: list[str] = []
        for record in reversed(journal.get("snapshots", [])):
            try:
                target = Path(str(record["target"])).resolve()
                target.relative_to(root)
                backup_value = record.get("backup")
                if backup_value:
                    backup = Path(str(backup_value)).resolve()
                    backup.relative_to(staging_root.resolve())
                    if not backup.is_file():
                        raise FileNotFoundError(backup)
                    shutil.copy2(backup, target)
                else:
                    target.unlink(missing_ok=True)
            except (KeyError, OSError, ValueError) as exc:
                failures.append(str(exc))
        if failures:
            raise ArchiveTransactionError(
                "stale transaction recovery was incomplete: " + "; ".join(failures)
            )
        shutil.rmtree(staging_root, ignore_errors=True)


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
    staged.json.write_bytes(_json_bytes(payload))
    staged.markdown.write_text(markdown, encoding="utf-8", newline="\n")
    staged.manifest.write_bytes(_json_bytes(sidecar))
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
    targets: _TargetPaths, backup_root: Path
) -> dict[Path, Path | None]:
    backup_root.mkdir(parents=True, exist_ok=False)
    snapshots: dict[Path, Path | None] = {}
    for index, target in enumerate(targets.ordered()):
        if not target.exists():
            snapshots[target] = None
            continue
        backup = backup_root / f"{index}-{target.name}.previous"
        shutil.copy2(target, backup)
        snapshots[target] = backup
    return snapshots


def _rollback(snapshots: dict[Path, Path | None]) -> list[str]:
    failures: list[str] = []
    for target, backup in reversed(tuple(snapshots.items())):
        try:
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backup, target)
        except OSError as exc:
            failures.append(f"{target}: {exc}")
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
        staging_root = Path(tempfile.mkdtemp(prefix=".pih-stage-", dir=root))
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
            staged.manifest.write_bytes(_json_bytes(sidecar))
            try:
                if json.loads(staged.manifest.read_text(encoding="utf-8")) != sidecar:
                    raise ArchiveTransactionError(
                        "staged sidecar does not match the commit contract"
                    )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ArchiveTransactionError(
                    f"could not reread staged sidecar: {exc}"
                ) from exc

            snapshots = _snapshot_existing(targets, staging_root / "backup")
            journal_path = staging_root / JOURNAL_NAME
            journal = {
                "contract_version": "1.0",
                "run_id": run_id,
                "phase": "promoting",
                "promoted_count": 0,
                "snapshots": [
                    {
                        "target": str(target.resolve()),
                        "backup": str(backup.resolve()) if backup is not None else None,
                    }
                    for target, backup in snapshots.items()
                ],
            }
            _write_journal(journal_path, journal)
            try:
                for index, (source, destination) in enumerate(
                    zip(staged.ordered(), targets.ordered()), start=1
                ):
                    promote(source, destination)
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
                    try:
                        postcommit_action(result)
                    except Exception as exc:
                        raise ArchivePostcommitError(
                            "formal archive committed, but the postcommit action failed: "
                            + str(exc),
                            result,
                        ) from exc
                return result
            except ArchivePostcommitError:
                raise
            except Exception as exc:
                rollback_failures = _rollback(snapshots)
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
