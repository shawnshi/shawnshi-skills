"""Small cross-platform helpers for conservative artifact writes."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class SafeWriteError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_issue(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


def _existing_components(path: Path) -> list[Path]:
    absolute = path.absolute()
    parts = absolute.parts
    if not parts:
        return []
    current = Path(parts[0])
    components = [current]
    for part in parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            components.append(current)
        else:
            break
    return components


def reject_symlink_path(path: Path, *, include_leaf: bool = True) -> None:
    check_path = path if include_leaf else path.parent
    for component in _existing_components(check_path):
        if component.is_symlink():
            raise SafeWriteError(
                "E_SYMLINK_PATH",
                "Refusing a path that contains a symbolic link.",
                path=str(path),
                component=str(component),
            )


def paths_alias(first: Path, second: Path) -> bool:
    try:
        if first.resolve(strict=False) == second.resolve(strict=False):
            return True
    except OSError:
        if first.absolute() == second.absolute():
            return True
    if first.exists() and second.exists():
        try:
            return os.path.samefile(first, second)
        except OSError:
            return False
    return False


@contextmanager
def output_lock(target: Path) -> Iterator[None]:
    lock_path = target.with_name(f".{target.name}.lock")
    reject_symlink_path(lock_path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise SafeWriteError("E_OUTPUT_LOCKED", "Another writer holds the output lock.", lock=str(lock_path)) from exc
    except OSError as exc:
        raise SafeWriteError("E_LOCK_CREATE", "Could not create the output lock.", lock=str(lock_path), detail=str(exc)) from exc

    identity = os.fstat(descriptor)
    try:
        os.write(descriptor, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            current = os.stat(lock_path, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                lock_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # A stale lock is safer than deleting an object we can no longer identify.
            pass


def atomic_write_text(target: Path, text: str, *, force: bool = False) -> None:
    target = target.absolute()
    reject_symlink_path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SafeWriteError("E_OUTPUT_DIRECTORY", "Could not create the output directory.", path=str(target.parent), detail=str(exc)) from exc
    reject_symlink_path(target)
    if target.exists() and not force:
        raise SafeWriteError("E_OUTPUT_EXISTS", "Output exists; pass --force to replace it.", path=str(target))

    temporary: Path | None = None
    with output_lock(target):
        reject_symlink_path(target)
        if target.exists() and not force:
            raise SafeWriteError("E_OUTPUT_EXISTS", "Output exists; pass --force to replace it.", path=str(target))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = -1
        for _ in range(20):
            candidate = target.with_name(f".{target.name}.{secrets.token_hex(12)}.tmp")
            try:
                descriptor = os.open(candidate, flags, 0o600)
                temporary = candidate
                break
            except FileExistsError:
                continue
            except OSError as exc:
                raise SafeWriteError("E_TEMP_CREATE", "Could not create an exclusive temporary file.", path=str(candidate), detail=str(exc)) from exc
        if descriptor < 0 or temporary is None:
            raise SafeWriteError("E_TEMP_CREATE", "Could not allocate a unique temporary file.", path=str(target.parent))

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists() and not force:
                raise SafeWriteError("E_OUTPUT_EXISTS", "Output appeared during the write; refusing to replace it.", path=str(target))
            if target.is_symlink():
                raise SafeWriteError("E_SYMLINK_PATH", "Refusing to replace a symbolic link.", path=str(target))
            os.replace(temporary, target)
            temporary = None
            if hasattr(os, "O_DIRECTORY"):
                try:
                    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
