#!/usr/bin/env python3
"""Explicit, privacy-preserving Garmin Connect authentication helper."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from collections.abc import Mapping, MutableMapping
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from contextlib import contextmanager
import ipaddress
import socket
import subprocess
from tempfile import TemporaryDirectory
from types import MethodType
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
SUPPORTED_GARMINCONNECT_VERSION = "0.3.17"

# Garmin's edge rejects some proxy exit paths outright (TLS reset or 429 across
# every login strategy), so Garmin hosts are routed around a configured HTTP
# proxy by default. Set GARMIN_EGRESS_ALLOW_PROXY=1 to keep the proxy for them.
GARMIN_DIRECT_EGRESS_HOSTS = ("garmin.com", ".garmin.com")
GARMIN_API_DOMAINS = (
    "sso.garmin.com",
    "diauth.garmin.com",
    "connectapi.garmin.com",
    "connect.garmin.com",
)
ALLOW_PROXY_ENV_VAR = "GARMIN_EGRESS_ALLOW_PROXY"
LOGIN_STRATEGY_ENV_VAR = "GARMIN_LOGIN_STRATEGY"
PROXY_BYPASS_ENV_VARS = ("NO_PROXY", "no_proxy")
_TRUE_VALUES = frozenset({"1", "true", "yes"})


def _detect_physical_ipv4() -> str | None:
    try:
        out = subprocess.check_output(
            ["route", "print", "0.0.0.0"], text=True, errors="ignore", timeout=3
        )
    except Exception:
        return None
    fake_net = ipaddress.ip_network("198.18.0.0/15")
    for line in out.splitlines():
        match = re.match(
            r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+)",
            line,
        )
        if not match:
            continue
        _gw, iface, _metric = match.groups()
        try:
            ip = ipaddress.ip_address(iface)
        except ValueError:
            continue
        if ip not in fake_net and not ip.is_loopback and not ip.is_link_local:
            return iface
    return None


@contextmanager
def _tun_fake_ip_bypass_scope(Garmin: object, request_guard: _LoginRequestGuard | None = None):
    """When TUN Fake-IP (198.18.0.0/15) intercepts DNS, bind to physical NIC + DoH."""
    if not _direct_egress_requested(os.environ) or not getattr(
        Garmin, "__module__", ""
    ).startswith("garminconnect"):
        yield
        return
    try:
        from garminconnect import client as sdk
        from curl_cffi import CurlOpt
        import requests
    except ImportError:
        yield
        return
    orig_cffi_session = getattr(sdk.cffi_requests, "Session", None)
    if not callable(orig_cffi_session) or not getattr(
        orig_cffi_session, "__module__", ""
    ).startswith("curl_cffi"):
        yield
        return
    orig_getaddrinfo = socket.getaddrinfo
    orig_connect = socket.socket.connect
    try:
        addrs = orig_getaddrinfo("sso.garmin.com", 443, type=socket.SOCK_STREAM)
        first_ip = addrs[0][4][0] if addrs else ""
        is_fake_ip = ipaddress.ip_address(first_ip) in ipaddress.ip_network("198.18.0.0/15")
    except Exception:
        is_fake_ip = False
    if not is_fake_ip:
        yield
        return
    phys_ip = _detect_physical_ipv4()
    if not phys_ip:
        yield
        return
    host_ips: dict[str, str] = {}
    try:
        doh = requests.Session()
        doh.trust_env = False
        for host in GARMIN_API_DOMAINS:
            resp = doh.get(
                "https://223.5.5.5/resolve",
                params={"name": host, "type": "A"},
                timeout=4,
            ).json()
            ips = [
                ans["data"]
                for ans in resp.get("Answer", [])
                if isinstance(ans, dict) and ans.get("type") == 1 and isinstance(ans.get("data"), str)
            ]
            if ips:
                host_ips[host] = ips[0]
    except Exception:
        pass
    if not host_ips:
        yield
        return
    target_ips = set(host_ips.values())
    resolve_list = [f"{h}:443:{ip}" for h, ip in host_ips.items()]

    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and host.lower() in host_ips:
            return orig_getaddrinfo(host_ips[host.lower()], port, family, type, proto, flags)
        return orig_getaddrinfo(host, port, family, type, proto, flags)

    def custom_connect(self, address):
        if isinstance(address, tuple) and len(address) == 2 and address[0] in target_ips:
            try:
                self.bind((phys_ip, 0))
            except OSError:
                pass
        return orig_connect(self, address)

    def custom_cffi_session(*args, **kwargs):
        opts = dict(kwargs.get("curl_options") or {})
        opts[CurlOpt.INTERFACE] = phys_ip
        opts[CurlOpt.RESOLVE] = resolve_list
        kwargs["curl_options"] = opts
        kwargs["trust_env"] = False
        sess = orig_cffi_session(*args, **kwargs)
        if request_guard is not None:
            request_guard.session(sess)
        return sess

    socket.getaddrinfo = custom_getaddrinfo
    socket.socket.connect = custom_connect
    sdk.cffi_requests.Session = custom_cffi_session
    try:
        yield
    finally:
        socket.getaddrinfo = orig_getaddrinfo
        socket.socket.connect = orig_connect
        sdk.cffi_requests.Session = orig_cffi_session


def _direct_egress_requested(env: Mapping[str, str]) -> bool:
    return env.get(ALLOW_PROXY_ENV_VAR, "").strip().casefold() not in _TRUE_VALUES


def _force_direct_garmin_egress(env: MutableMapping[str, str]) -> bool:
    """Add Garmin hosts to NO_PROXY while keeping existing bypass entries."""
    if not _direct_egress_requested(env):
        return False
    changed = False
    for key in PROXY_BYPASS_ENV_VARS:
        entries = [item.strip() for item in env.get(key, "").split(",") if item.strip()]
        missing = [host for host in GARMIN_DIRECT_EGRESS_HOSTS if host not in entries]
        if not missing:
            continue
        env[key] = ",".join(entries + missing)
        changed = True
    return changed


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


# Stable, secret-free failure categories. ``base_status`` keeps the legacy label
# so existing callers keep their meaning while the category tells 429, TLS,
# dependency and credential failures apart.
AUTH_FAILURE_STATUSES = (
    "rate_limited",
    "provider_blocked",
    "tls_error",
    "connection_error",
    "mfa_required",
    "token_store_error",
    "dependency_error",
    "authentication_failed",
    "auth_unclassified",
)

_CURL_CODE_STATUSES = {
    "35": "tls_error",
    "51": "tls_error",
    "58": "tls_error",
    "60": "tls_error",
    "77": "tls_error",
    "7": "connection_error",
    "28": "connection_error",
    "52": "connection_error",
    "55": "connection_error",
    "56": "connection_error",
}
_CURL_CODE_PATTERN = re.compile(r"curl:\s*\((\d+)\)")
_RATE_LIMIT_MARKERS = ("429", "too many requests", "ratelimit", "rate limit")
_TLS_MARKERS = ("tls", "ssl", "openssl", "certificate", "handshake")
_TOKEN_STORE_MARKERS = ("token_store", "temporary_token", "token store")
_DEPENDENCY_MARKERS = (
    "garminconnect_not_installed",
    "garminconnect_version_mismatch",
    "no module named",
)
_CONNECTION_MARKERS = (
    "connection",
    "timed out",
    "timeout",
    "name resolution",
    "failed to perform",
    "proxy",
    "network",
)
_AUTH_MARKERS = (
    "authentication",
    "credential",
    "invalid",
    "incorrect",
    "locked",
    "account error",
)
_LAST_FAILURE: dict[str, object] = {}


class SavedSessionError(RuntimeError):
    """A sanitized restoration failure with transport metadata, never token text."""

    def __init__(self, exc: BaseException):
        self.status = _classify_auth_failure(exc)
        self.code = self.status
        self.error_type = type(exc).__name__
        self.http_status = _http_status(exc)
        super().__init__(self.status)


def _http_status(exc: BaseException) -> int | None:
    for _ in range(5):
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
        if value is None:
            value = getattr(exc, "status_code", None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
        cause = exc.__cause__
        if cause is None:
            break
        exc = cause
    return None


class _LoginTransportBlocked(BaseException):
    """Owned hard-stop signal: the SDK's broad Exception handlers must not retry."""

    def __init__(self, status_code: int, category: str):
        self.status_code = status_code
        self.category = category
        super().__init__("authentication_transport_blocked")


class _LoginRequestGuard:
    """Per-login latch covering SSO/MFA sessions and DI/IT exchange transports."""

    def __init__(self):
        self.blocked: _LoginTransportBlocked | None = None
        self.active = True
        self.sessions: set[int] = set()

    def check(self):
        if self.blocked is not None:
            raise self.blocked
        if not self.active:
            raise RuntimeError("authentication_scope_closed")

    def reject(self, code: int, category: str):
        self.blocked = _LoginTransportBlocked(code, category)
        raise self.blocked

    def wrap(self, request):
        def guarded(*args, **kwargs):
            self.check()
            try:
                response = request(*args, **kwargs)
            except Exception as exc:
                code = _http_status(exc)
                if code in (403, 429):
                    self.reject(code, "rate_limited" if code == 429 else "provider_blocked")
                raise
            code = getattr(response, "status_code", None)
            if code in (403, 429):
                self.reject(code, "rate_limited" if code == 429 else "provider_blocked")
            headers = getattr(response, "headers", None)
            header = getattr(headers, "get", None)
            if callable(header) and header("cf-mitigated", "") == "challenge":
                self.reject(code if isinstance(code, int) else 200, "provider_blocked")
            # The pinned SDK also retries MFA when 429 is inside a 200 JSON
            # body. Inspect only known error fields; never log response bodies.
            decode = getattr(response, "json", None)
            if callable(decode):
                try:
                    body = decode()
                except ValueError:
                    body = None
                if isinstance(body, dict):
                    error = body.get("error")
                    embedded = error.get("status-code") if isinstance(error, dict) else None
                    if embedded in (403, 429, "403", "429"):
                        self.reject(code if isinstance(code, int) else 200,
                                    "rate_limited" if str(embedded) == "429" else "provider_blocked")
                    status = body.get("responseStatus")
                    if isinstance(status, dict) and status.get("type") == "CAPTCHA_REQUIRED":
                        self.reject(code if isinstance(code, int) else 200, "provider_blocked")
            return response
        return guarded

    def session(self, session):
        if id(session) in self.sessions:
            return
        request = getattr(session, "request", None)
        if not callable(request):
            raise RuntimeError("guarded_login_session_unsupported")
        session.request = self.wrap(request)
        self.sessions.add(id(session))

    def bind(self, native):
        post = getattr(native, "_http_post", None)
        if not callable(post):
            raise RuntimeError("guarded_login_exchange_unsupported")
        native._http_post = self.wrap(post)
        for name in ("cs", "_api_session"):
            self.session(getattr(native, name, None))

    def close(self):
        self.active = False
        if self.blocked is not None:
            self.blocked.__traceback__ = None


def _classify_auth_failure(exc: BaseException) -> str:
    """Map an upstream exception onto one stable failure category.

    Only the category and the exception type name are ever emitted; the
    upstream message is inspected in memory and never echoed.
    """
    if isinstance(exc, _LoginTransportBlocked):
        return exc.category
    name = type(exc).__name__.casefold()
    compact_name = name.replace(" ", "")
    message = str(exc).casefold()
    haystack = f"{name} {message}"
    status_code = _http_status(exc)
    if status_code == 429:
        return "rate_limited"
    if (status_code == 403 or "403" in haystack) and any(
        marker in haystack for marker in ("cloudflare", "bot challenge", "cf-mitigated")
    ):
        return "provider_blocked"
    if status_code in (401, 403):
        return "authentication_failed"
    if status_code == 408 or (status_code is not None and status_code >= 500):
        return "connection_error"
    if isinstance(exc, EOFError) or "mfarequired" in compact_name:
        return "mfa_required"
    curl_code = _CURL_CODE_PATTERN.search(message)
    if curl_code and curl_code.group(1) in _CURL_CODE_STATUSES:
        return _CURL_CODE_STATUSES[curl_code.group(1)]
    if "toomanyrequests" in compact_name or any(
        marker in haystack for marker in _RATE_LIMIT_MARKERS
    ):
        return "rate_limited"
    if any(marker in haystack for marker in _TLS_MARKERS):
        return "tls_error"
    if any(marker in haystack for marker in _TOKEN_STORE_MARKERS):
        return "token_store_error"
    if any(marker in haystack for marker in _DEPENDENCY_MARKERS):
        return "dependency_error"
    if any(marker in haystack for marker in _CONNECTION_MARKERS):
        return "connection_error"
    if any(marker in haystack for marker in _AUTH_MARKERS):
        return "authentication_failed"
    return "auth_unclassified"


def _emit_safe_failure(status: str, exc: BaseException) -> None:
    category = _classify_auth_failure(exc)
    _LAST_FAILURE.clear()
    _LAST_FAILURE.update(
        {
            "status": category,
            "base_status": status,
            "error_type": type(exc).__name__,
        }
    )
    http_status = _http_status(exc)
    if http_status is not None:
        _LAST_FAILURE["http_status"] = http_status
    _emit({"ok": False, **_LAST_FAILURE}, stream=sys.stderr)


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


def _read_saved_token_bytes(token_file: Path) -> bytes | None:
    """Read one bounded, stable token snapshot without persisting credentials."""
    _reject_unsafe_token_path(token_file)
    if not token_file.is_file():
        return None
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
    return token_bytes


def _new_live_client(Garmin, *args, **kwargs):
    # The caller owns retries; neither SDK nor HTTP transport may replay a read.
    client = Garmin(*args, retry_attempts=0, **kwargs)
    transport = client.client
    configure = getattr(transport, "configure", None)
    if callable(configure):
        configure(retries=0)
    else:
        # Native garminconnect 0.3.17 uses requests sessions rather than
        # garth.Client.configure. Keep both SSO and API transports no-retry.
        from requests import Session
        from urllib3.util.retry import Retry

        sessions = [getattr(transport, name, None) for name in ("cs", "_api_session")]
        if not all(isinstance(session, Session) for session in sessions):
            raise RuntimeError("garmin_transport_contract_mismatch")
        for session in sessions:
            assert session is not None  # narrowed after the all-Session contract check
            for adapter in session.adapters.values():
                adapter.max_retries = Retry(
                    total=0, connect=0, read=0, redirect=0, status=0
                )
    return client


def _is_valid_di_token_bytes(raw: bytes) -> bool:
    if not raw or len(raw) > 1_048_576:
        return False
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(parsed, dict):
        return False
    return all(
        isinstance(parsed.get(key), str) and bool(parsed[key].strip())
        for key in ("di_token", "di_refresh_token", "di_client_id")
    )


def _write_token_bytes_atomic(target: Path, payload: bytes) -> None:
    _reject_unsafe_token_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent, prefix=f".{target.name}.") as tmp_dir:
        tmp_file = Path(tmp_dir) / target.name
        with tmp_file.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            tmp_file.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp_file, target)


def _persist_rotated_di_token_bytes(
    source_file: Path,
    original_bytes: bytes,
    new_bytes: bytes,
) -> None:
    if new_bytes == original_bytes or not _is_valid_di_token_bytes(new_bytes):
        return
    try:
        current_bytes = _read_saved_token_bytes(source_file)
        if current_bytes == original_bytes:
            _write_token_bytes_atomic(source_file, new_bytes)
        garmindb_tokens = Path.home() / ".GarminDb" / "garmin_tokens.json"
        if (
            garmindb_tokens.resolve(strict=False) != source_file.resolve(strict=False)
            and garmindb_tokens.is_file()
        ):
            gdb_bytes = _read_saved_token_bytes(garmindb_tokens)
            if gdb_bytes == original_bytes:
                _write_token_bytes_atomic(garmindb_tokens, new_bytes)
    except Exception:
        pass


def _restore_client_without_persistent_token_write(
    Garmin, *, token_file: Path | None = None, in_memory: bool = False
):
    """Keep profile-free insight restoration separate from profile-based APIs."""
    resolved_token_file = token_file or _token_file_path()
    token_bytes = _read_saved_token_bytes(resolved_token_file)
    if token_bytes is None:
        return None
    if in_memory:
        client = _new_live_client(Garmin)
        client.client._tokenstore_path = None
        client.client.loads(token_bytes.decode("utf-8"))
        if client.client._tokenstore_path is not None:
            raise RuntimeError("token_store_persistence_forbidden")
        return client
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
        client = _new_live_client(Garmin)
        with _tun_fake_ip_bypass_scope(Garmin):
            client.login(tokenstore=temporary_dir)
        try:
            if temporary_file.is_file():
                _persist_rotated_di_token_bytes(
                    resolved_token_file, token_bytes, temporary_file.read_bytes()
                )
        except OSError:
            pass
        return client


def _single_mobile_login_cffi(native, email: str, password: str) -> None:
    """Use the pinned SDK's first existing profile once; never rotate on errors."""
    from garminconnect import client as sdk

    profiles = sdk.MOBILE_IMPERSONATIONS
    if (
        not sdk.HAS_CFFI
        or not profiles
        or not callable(getattr(native, "_do_mobile_login", None))
    ):
        raise RuntimeError("single_login_transport_contract_mismatch")
    # Match SDK session ownership: MFA may retain this session until the
    # enclosing native.login resolves its challenge. Do not close it early.
    session = sdk.cffi_requests.Session(impersonate=profiles[0])
    guard = getattr(native, "_bounded_login_guard", None)
    if not isinstance(guard, _LoginRequestGuard):
        raise RuntimeError("guarded_login_scope_required")
    guard.session(session)
    native._do_mobile_login(session, email, password)


def _strict_verify_token(native) -> bool:
    """An inconclusive provider response is a failure, never token acceptance."""
    profile = native.connectapi("/userprofile-service/socialProfile")
    if not isinstance(profile, dict) or not isinstance(profile.get("displayName"), str) or not profile["displayName"]:
        raise RuntimeError("token_verification_identity_missing")
    return True


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
    native = None
    request_guard = None
    try:
        consume_capability(
            token_write_capability,
            scope="token_store",
            operation=TOKEN_WRITE_OPERATION,
            request=request,
        )
        Garmin = _load_garmin_api()
        _prepare_token_dir()
        _force_direct_garmin_egress(os.environ)

        def get_mfa() -> str:
            return input("Garmin MFA code: ")

        client = _new_live_client(Garmin, email, password, prompt_mfa=get_mfa)
        native = getattr(client, "client", None)
        disabled = getattr(native, "skip_strategies", None)
        if (
            native is None
            or not isinstance(disabled, set)
            or not callable(getattr(native, "login", None))
            or not callable(getattr(native, "dump", None))
            or getattr(native, "_tokenstore_path", None) is not None
        ):
            raise RuntimeError("single_strategy_login_contract_mismatch")
        # Explicit password login starts fresh: never first retry a rejected
        # saved session. Keep only the SDK's existing first strategy, with no
        # transport/fingerprint rotation after a 429 or provider challenge.
        strategy = os.environ.get(LOGIN_STRATEGY_ENV_VAR, "mobile").strip().casefold()
        if strategy == "widget" and getattr(Garmin, "__module__", "").startswith("garminconnect"):
            disabled.update({"mobile+cffi", "mobile+requests", "portal+cffi", "portal+requests"})
        else:
            disabled.update({"mobile+requests", "widget+cffi", "portal+cffi", "portal+requests"})
        # The remaining upstream strategy also rotates fingerprints internally,
        # and its verifier accepts inconclusive failures. Override only this
        # fresh instance; installed SDK modules and read-only clients stay intact.
        request_guard = _LoginRequestGuard()
        request_guard.bind(native)
        native._bounded_login_guard = request_guard
        native._mobile_login_cffi = MethodType(_single_mobile_login_cffi, native)
        native._verify_token = MethodType(_strict_verify_token, native)
        with _tun_fake_ip_bypass_scope(Garmin, request_guard=request_guard):
            native.login(email, password, prompt_mfa=get_mfa)
        request_guard.check()
        # This is the existing explicitly authorized manual token-write path;
        # SDK dump is atomic. Failed authentication never replaces old tokens.
        native.dump(str(TOKEN_DIR))
        try:
            default_token_dir = (Path.home() / ".config" / "garmin-connect").resolve(strict=False)
            garmindb_dir = (Path.home() / ".GarminDb").resolve(strict=False)
            dumped_file = _token_file_path()
            resolved_dir = TOKEN_DIR.resolve(strict=False)
            if dumped_file.is_file() and (garmindb_dir / "GarminConnectConfig.json").is_file():
                dumped_bytes = _read_saved_token_bytes(dumped_file)
                if dumped_bytes and _is_valid_di_token_bytes(dumped_bytes):
                    if resolved_dir == default_token_dir:
                        _write_token_bytes_atomic(garmindb_dir / "garmin_tokens.json", dumped_bytes)
                    elif resolved_dir == garmindb_dir:
                        _write_token_bytes_atomic(default_token_dir / "garmin_tokens.json", dumped_bytes)
        except Exception:
            pass
        return True
    except _LoginTransportBlocked as exc:
        if native is not None:
            clear = getattr(native, "_clear_auth_state", None)
            if callable(clear):
                clear(keep_tokenstore_path=True)
        _emit_safe_failure("authentication_failed", exc)
        return False
    except Exception as exc:
        _emit_safe_failure("authentication_failed", exc)
        return False
    finally:
        if request_guard is not None:
            request_guard.close()


def get_client(
    *,
    network_capability: object = None,
    operation: str = AUTH_OPERATION,
    request: dict[str, object] | None = None,
    token_file: Path | None = None,
    in_memory: bool = False,
    raise_on_error: bool = False,
):
    """Restore a saved session without persisting token refresh side effects."""
    _require_network_authorization(
        network_capability=network_capability,
        operation=operation,
        request=request,
    )
    _LAST_FAILURE.clear()
    try:
        Garmin = _load_garmin_api()
        _force_direct_garmin_egress(os.environ)
        client = _restore_client_without_persistent_token_write(
            Garmin, token_file=token_file, in_memory=in_memory
        )
        if client is None and raise_on_error:
            raise FileNotFoundError("token_store_missing")
        return client
    except Exception as exc:
        if raise_on_error:
            raise SavedSessionError(exc) from exc
        _emit_safe_failure("saved_session_restore_failed", exc)
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
        "--strategy",
        choices=("mobile", "widget"),
        default=None,
        help="Single bounded login strategy (default: widget on CLI, mobile in SDK)",
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
    request: dict[str, object]
    args = build_parser().parse_args(argv)
    _LAST_FAILURE.clear()
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
        prev_strategy = os.environ.get(LOGIN_STRATEGY_ENV_VAR)
        try:
            if args.strategy:
                os.environ[LOGIN_STRATEGY_ENV_VAR] = args.strategy
            elif prev_strategy is None:
                os.environ[LOGIN_STRATEGY_ENV_VAR] = "widget"
            success = login(
                email,
                password,
                network_capability=network_capability,
                token_write_capability=token_write_capability,
                request=request,
            )
        finally:
            if prev_strategy is None:
                os.environ.pop(LOGIN_STRATEGY_ENV_VAR, None)
            else:
                os.environ[LOGIN_STRATEGY_ENV_VAR] = prev_strategy
        password = ""
        failure = dict(_LAST_FAILURE)
        payload = {
            "ok": success,
            "status": (
                "authenticated"
                if success
                else failure.get("status", "authentication_failed")
            ),
        }
        if not success:
            payload["base_status"] = failure.get("base_status", "authentication_failed")
            payload["error_type"] = failure.get("error_type", "unknown")
        _emit(payload)
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
    failure = dict(_LAST_FAILURE)
    payload = {
        "ok": success,
        "status": (
            "session_valid" if success else failure.get("status", "session_invalid")
        ),
    }
    if not success:
        payload["base_status"] = failure.get("base_status", "saved_session_invalid")
        payload["error_type"] = failure.get("error_type", "unknown")
    _emit(payload)
    return EXIT_OK if success else EXIT_AUTH_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
