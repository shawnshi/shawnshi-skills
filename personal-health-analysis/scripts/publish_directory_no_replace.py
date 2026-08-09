#!/usr/bin/env python3
"""Atomically publish one directory without replacing an existing target."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
import sys
from pathlib import Path


class PublishError(RuntimeError):
    """Stable fail-closed publication error."""


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _raise_errno(operation: str) -> None:
    error_number = ctypes.get_errno()
    if error_number in (errno.EEXIST, errno.ENOTEMPTY):
        raise PublishError("target_exists")
    raise PublishError(f"{operation}_failed_errno_{error_number}")


def _publish_linux(staging: Path, target: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    if renameat2 is None:
        raise PublishError("atomic_no_replace_not_supported")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    if (
        renameat2(
            at_fdcwd,
            os.fsencode(staging),
            at_fdcwd,
            os.fsencode(target),
            rename_noreplace,
        )
        != 0
    ):
        _raise_errno("renameat2")


def _publish_macos(staging: Path, target: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    renamex_np = getattr(library, "renamex_np", None)
    if renamex_np is None:
        raise PublishError("atomic_no_replace_not_supported")
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    rename_excl = 0x00000004
    if renamex_np(os.fsencode(staging), os.fsencode(target), rename_excl) != 0:
        _raise_errno("renamex_np")


def publish_directory_no_replace(staging: Path, target: Path) -> Path:
    staging = _absolute(Path(staging))
    target = _absolute(Path(target))
    if staging.parent != target.parent:
        raise PublishError("staging_and_target_must_share_parent")
    if staging.is_symlink() or not staging.is_dir():
        raise PublishError("staging_directory_invalid")
    attributes = getattr(staging.lstat(), "st_file_attributes", 0)
    if attributes & 0x400:
        raise PublishError("staging_reparse_forbidden")

    try:
        if os.name == "nt":
            os.rename(staging, target)
        elif sys.platform.startswith("linux"):
            _publish_linux(staging, target)
        elif sys.platform == "darwin":
            _publish_macos(staging, target)
        else:
            raise PublishError("atomic_no_replace_not_supported")
    except FileExistsError as exc:
        raise PublishError("target_exists") from exc
    except OSError as exc:
        if exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
            raise PublishError("target_exists") from exc
        raise PublishError("atomic_publish_failed") from exc
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    try:
        published = publish_directory_no_replace(
            Path(args.staging), Path(args.target)
        )
    except PublishError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(str(published))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
