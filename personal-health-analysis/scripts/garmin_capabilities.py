#!/usr/bin/env python3
"""Issue short-lived, operation-scoped capabilities for live Garmin actions.

This module prevents accidental authorization propagation: ordinary booleans,
lookalike objects, capabilities for another scope or operation, and expired
capabilities all fail closed. It is not a security boundary against malicious
code already executing in this Python process; such code can introspect module
state or bypass Python-level checks.
"""

from __future__ import annotations

import secrets
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone


DEFAULT_TTL_SECONDS = 300
MAX_TTL_SECONDS = 3600
_ISSUER = object()


class CapabilityError(PermissionError):
    """Raised when a live action does not receive the exact required grant."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _ScopedCapability:
    """Immutable process-local grant. Instances are created by this module only."""

    __slots__ = (
        "_scope",
        "_operation",
        "_issued_at",
        "_expires_at",
        "_nonce",
        "_request_sha256",
        "_consumed",
        "_consume_lock",
        "_issuer",
        "_sealed",
    )

    def __init__(
        self,
        *,
        scope: str,
        operation: str,
        issued_at: datetime,
        expires_at: datetime,
        nonce: str,
        request_sha256: str | None,
        issuer: object,
    ) -> None:
        if issuer is not _ISSUER:
            raise CapabilityError("module_issuance_required")
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_issued_at", issued_at)
        object.__setattr__(self, "_expires_at", expires_at)
        object.__setattr__(self, "_nonce", nonce)
        object.__setattr__(self, "_request_sha256", request_sha256)
        object.__setattr__(self, "_consumed", False)
        object.__setattr__(self, "_consume_lock", threading.Lock())
        object.__setattr__(self, "_issuer", issuer)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("capability_is_immutable")

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def operation(self) -> str:
        return self._operation

    @property
    def issued_at(self) -> datetime:
        return self._issued_at

    @property
    def expires_at(self) -> datetime:
        return self._expires_at

    @property
    def nonce(self) -> str:
        return self._nonce

    def __repr__(self) -> str:
        return (
            "<ScopedCapability "
            f"scope={self._scope!r} operation={self._operation!r} "
            f"expires_at={self._expires_at.isoformat()!r}>"
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_now(value: datetime | None) -> datetime:
    resolved = _utc_now() if value is None else value
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timezone_aware_datetime_required")
    return resolved.astimezone(timezone.utc)


def _validate_label(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_required")
    return value.strip()


def _request_digest(request: dict[str, object] | None) -> str | None:
    """Return a deterministic digest without retaining sensitive request values."""
    if request is None:
        return None
    if not isinstance(request, dict):
        raise ValueError("capability_request_must_be_object")
    try:
        encoded = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("capability_request_not_json_serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def issue_capability(
    *,
    scope: str,
    operation: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
    request: dict[str, object] | None = None,
) -> _ScopedCapability:
    """Issue an immutable, short-lived grant for one operation and request."""
    scope = _validate_label(scope, field="scope")
    operation = _validate_label(operation, field="operation")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ValueError("ttl_seconds_must_be_integer")
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("ttl_seconds_out_of_range")
    issued_at = _normalize_now(now)
    return _ScopedCapability(
        scope=scope,
        operation=operation,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
        nonce=secrets.token_hex(16),
        request_sha256=_request_digest(request),
        issuer=_ISSUER,
    )


def require_capability(
    capability: object,
    *,
    scope: str,
    operation: str,
    now: datetime | None = None,
    request: dict[str, object] | None = None,
) -> None:
    """Fail closed unless *capability* is the exact live grant requested."""
    if type(capability) is not _ScopedCapability or capability._issuer is not _ISSUER:
        raise CapabilityError("capability_object_required")
    if capability.scope != scope:
        raise CapabilityError("capability_scope_mismatch")
    if capability.operation != operation:
        raise CapabilityError("capability_operation_mismatch")
    if capability._consumed:
        raise CapabilityError("capability_consumed")
    if capability._request_sha256 != _request_digest(request):
        raise CapabilityError("capability_request_mismatch")
    if _normalize_now(now) >= capability.expires_at:
        raise CapabilityError("capability_expired")


def consume_capability(
    capability: object,
    *,
    scope: str,
    operation: str,
    now: datetime | None = None,
    request: dict[str, object] | None = None,
) -> None:
    """Validate and consume a grant so the sensitive action cannot reuse it."""
    if type(capability) is not _ScopedCapability or capability._issuer is not _ISSUER:
        raise CapabilityError("capability_object_required")
    with capability._consume_lock:
        require_capability(
            capability,
            scope=scope,
            operation=operation,
            now=now,
            request=request,
        )
        object.__setattr__(capability, "_consumed", True)


__all__ = [
    "CapabilityError",
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "issue_capability",
    "require_capability",
    "consume_capability",
]
