#!/usr/bin/env python3
"""Explicit, privacy-preserving Garmin Connect authentication helper."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from garmin_capabilities import (
    CapabilityError,
    consume_capability,
    issue_capability,
    require_capability,
)


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTHORIZATION = 3
EXIT_DEPENDENCY = 4
EXIT_AUTH_FAILURE = 5

TOKEN_DIR = Path(
    os.environ.get("GARMIN_TOKEN_DIR", Path.home() / ".config" / "garmin-connect")
).expanduser()


class NetworkAuthorizationError(PermissionError):
    """Raised before any live authentication side effect is attempted."""


AUTH_OPERATION = "garmin_auth"
TOKEN_WRITE_OPERATION = "garmin_token_store_write"
SUPPORTED_GARMINCONNECT_VERSION = "0.3.9"


def _require_network_authorization(
    *,
    network_capability: object,
    operation: str = AUTH_OPERATION,
    request: dict[str, object] | None = None,
) -> None:
    """Require a module-issued network grant for the exact live operation."""
    try:
        require_capability(
            network_capability,
            scope="network",
            operation=operation,
            request=request,
        )
    except CapabilityError as exc:
        raise NetworkAuthorizationError("network_authorization_required") from exc


def _emit(payload: dict, *, stream=None) -> None:
    """Emit one machine-readable object without identity or filesystem details."""
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        file=sys.stdout if stream is None else stream,
    )


def _emit_safe_failure(status: str, exc: BaseException) -> None:
    _emit(
        {
            "ok": False,
            "status": status,
            "error_type": type(exc).__name__,
        },
        stream=sys.stderr,
    )


def _load_garmin_api():
    """Load the optional network dependency only for an authorized live action."""
    try:
        installed_version = package_version("garminconnect")
    except PackageNotFoundError as exc:
        raise RuntimeError("garminconnect_not_installed") from exc
    if installed_version != SUPPORTED_GARMINCONNECT_VERSION:
        raise RuntimeError("garminconnect_version_mismatch")
    try:
        from garminconnect import Garmin
    except ImportError as exc:
        raise RuntimeError("garminconnect_not_installed") from exc
    return Garmin


def _prepare_token_dir() -> None:
    token_directory = TOKEN_DIR.parent if TOKEN_DIR.suffix.casefold() == ".json" else TOKEN_DIR
    token_directory.mkdir(parents=True, exist_ok=True)
    try:
        token_directory.chmod(0o700)
    except OSError as exc:
        raise RuntimeError("token_store_security_setup_failed") from exc


def _token_file_path() -> Path:
    return TOKEN_DIR if TOKEN_DIR.suffix.casefold() == ".json" else TOKEN_DIR / "garmin_tokens.json"


def _reject_unsafe_token_path(path: Path) -> None:
    """Reject redirectable token-store paths before reading credential material."""
    for candidate in (path.parent, path):
        if candidate.is_symlink():
            raise RuntimeError("token_store_link_forbidden")
        try:
            attributes = candidate.lstat().st_file_attributes
        except (AttributeError, FileNotFoundError):
            continue
        if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise RuntimeError("token_store_reparse_point_forbidden")


def _restore_client_without_persistent_token_write(Garmin):
    """Restore from an ephemeral copy so refresh cannot mutate the saved tokens."""
    token_file = _token_file_path()
    if not token_file.is_file():
        return None
    _reject_unsafe_token_path(token_file)
    try:
        with token_file.open("rb") as source:
            before = os.fstat(source.fileno())
            token_bytes = source.read(1_048_577)
            after = os.fstat(source.fileno())
        current = token_file.lstat()
    except OSError as exc:
        raise RuntimeError("token_store_read_failed") from exc
    if len(token_bytes) > 1_048_576:
        raise RuntimeError("token_store_too_large")
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    identity_current = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if identity_before != identity_after or identity_after != identity_current:
        raise RuntimeError("token_store_changed_during_read")
    with TemporaryDirectory(prefix="garmin-token-read-") as temporary_dir:
        temporary_file = Path(temporary_dir) / "garmin_tokens.json"
        with temporary_file.open("xb") as handle:
            handle.write(token_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary_file.chmod(0o600)
        except OSError as exc:
            raise RuntimeError("temporary_token_security_setup_failed") from exc
        client = Garmin()
        client.login(tokenstore=temporary_dir)
        return client


def login(
    email: str,
    password: str,
    *,
    network_capability: object = None,
    token_write_capability: object = None,
    request: dict[str, object] | None = None,
) -> bool:
    """Perform an explicitly requested login without echoing account details."""
    _require_network_authorization(
        network_capability=network_capability,
        request=request,
    )
    try:
        consume_capability(
            token_write_capability,
            scope="token_store",
            operation=TOKEN_WRITE_OPERATION,
            request=request,
        )
        Garmin = _load_garmin_api()
        _prepare_token_dir()

        def get_mfa() -> str:
            return input("Garmin MFA code: ")

        client = Garmin(email, password, prompt_mfa=get_mfa)
        client.login(tokenstore=str(TOKEN_DIR))
        return True
    except Exception as exc:
        _emit_safe_failure("authentication_failed", exc)
        return False


def get_client(
    *,
    network_capability: object = None,
    operation: str = AUTH_OPERATION,
    request: dict[str, object] | None = None,
):
    """Restore a saved session without persisting token refresh side effects."""
    _require_network_authorization(
        network_capability=network_capability,
        operation=operation,
        request=request,
    )
    if not TOKEN_DIR.exists():
        return None
    try:
        Garmin = _load_garmin_api()
        return _restore_client_without_persistent_token_write(Garmin)
    except Exception as exc:
        _emit_safe_failure("saved_session_invalid", exc)
        return None


def check_status(
    *,
    network_capability: object = None,
    request: dict[str, object] | None = None,
) -> bool:
    """Validate the saved session without revealing account identity or token paths."""
    _require_network_authorization(
        network_capability=network_capability,
        request=request,
    )
    return get_client(
        network_capability=network_capability,
        request=request,
    ) is not None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Garmin authentication with explicit network authorization."
    )
    subparsers = parser.add_subparsers(dest="command")

    login_parser = subparsers.add_parser("login", help="Create or refresh a session")
    login_parser.add_argument(
        "--email", help="Garmin account email; alternatively set GARMIN_EMAIL"
    )
    login_parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize this command to contact Garmin",
    )
    login_parser.add_argument(
        "--allow-token-write",
        action="store_true",
        help="Explicitly authorize creating or refreshing the persistent token store",
    )
    login_parser.add_argument(
        "--dry-run", action="store_true", help="Validate intent without side effects"
    )

    status_parser = subparsers.add_parser("status", help="Validate a saved session")
    status_parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize this command to contact Garmin",
    )
    status_parser.add_argument(
        "--dry-run", action="store_true", help="Validate intent without side effects"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        _emit(
            {
                "ok": False,
                "status": "usage_error",
                "error": "command_required",
            }
        )
        return EXIT_USAGE

    if args.dry_run:
        _emit(
            {
                "ok": True,
                "status": "dry_run",
                "operation": args.command,
                "network_accessed": False,
                "token_store_written": False,
            }
        )
        return EXIT_OK

    if not args.allow_network:
        _emit(
            {
                "ok": False,
                "status": "network_authorization_required",
                "operation": args.command,
            }
        )
        return EXIT_AUTHORIZATION

    if args.command == "login":
        if not args.allow_token_write:
            _emit(
                {
                    "ok": False,
                    "status": "token_write_authorization_required",
                    "operation": args.command,
                }
            )
            return EXIT_AUTHORIZATION
        email = args.email or os.environ.get("GARMIN_EMAIL")
        if not email:
            _emit(
                {
                    "ok": False,
                    "status": "usage_error",
                    "error": "email_required",
                }
            )
            return EXIT_USAGE
        password = os.environ.get("GARMIN_PASSWORD")
        if not password:
            password = getpass.getpass("Garmin password: ")
        request = {"command": "login"}
        network_capability = issue_capability(
            scope="network",
            operation=AUTH_OPERATION,
            request=request,
        )
        token_write_capability = issue_capability(
            scope="token_store",
            operation=TOKEN_WRITE_OPERATION,
            request=request,
        )
        success = login(
            email,
            password,
            network_capability=network_capability,
            token_write_capability=token_write_capability,
            request=request,
        )
        password = ""
        _emit(
            {
                "ok": success,
                "status": "authenticated" if success else "authentication_failed",
            }
        )
        return EXIT_OK if success else EXIT_AUTH_FAILURE

    request = {"command": "status"}
    network_capability = issue_capability(
        scope="network",
        operation=AUTH_OPERATION,
        request=request,
    )
    success = check_status(
        network_capability=network_capability,
        request=request,
    )
    _emit(
        {
            "ok": success,
            "status": "session_valid" if success else "session_invalid",
        }
    )
    return EXIT_OK if success else EXIT_AUTH_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
