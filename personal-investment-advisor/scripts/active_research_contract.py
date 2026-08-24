"""Shared fail-closed helpers for PIA active-research contracts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESERVED_SOURCE_LOCATORS = ("example.com", "example.test", ".invalid", "localhost")


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def positive_integer(value: Any, *, minimum: int = 1) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def parse_aware_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def valid_source_locator(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().lower()
    if any(token in normalized for token in RESERVED_SOURCE_LOCATORS):
        return False
    return normalized.startswith(("https://", "http://", "sec://", "dataset://"))


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def canonical_sha256(path: str | Path) -> str:
    document = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: str | Path, label: str) -> Any:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label}_read_error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label}_json_error: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def validate_evidence_stamp(
    value: Any,
    prefix: str,
    *,
    as_of: datetime,
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]
    errors: list[str] = []
    observed_at = parse_aware_iso(value.get("observed_at"))
    available_at = parse_aware_iso(value.get("available_at"))
    retrieved_at = parse_aware_iso(value.get("retrieved_at"))
    if observed_at is None:
        errors.append(f"{prefix}.observed_at must be a timezone-aware ISO datetime")
    if available_at is None:
        errors.append(f"{prefix}.available_at must be a timezone-aware ISO datetime")
    if retrieved_at is None:
        errors.append(f"{prefix}.retrieved_at must be a timezone-aware ISO datetime")
    if (
        observed_at is not None
        and available_at is not None
        and utc(observed_at) > utc(available_at)
    ):
        errors.append(f"{prefix} must satisfy observed_at <= available_at")
    for field, parsed in (
        ("observed_at", observed_at),
        ("available_at", available_at),
        ("retrieved_at", retrieved_at),
    ):
        if parsed is not None and utc(parsed) > utc(as_of):
            errors.append(f"{prefix}.{field} cannot be after package as_of")
    if not valid_source_locator(value.get("source_locator")):
        errors.append(f"{prefix}.source_locator must be a non-test public or dataset locator")
    if not valid_sha256(value.get("content_sha256")):
        errors.append(f"{prefix}.content_sha256 must be a lowercase SHA-256")
    return errors


def base_report(schema_version: str, detail_status: str = "not_evaluated") -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": "invalid_input",
        "detail_status": detail_status,
        "decision_scope": "research_only",
        "research_only": True,
        "operation_mode": "read_only_offline",
        "mutation_performed": False,
        "formal_use_allowed": False,
        "errors": [],
        "warnings": [],
        "fail_closed": {"enforced": True, "triggered": True},
    }


def fail_report(
    schema_version: str,
    detail_status: str,
    errors: list[str],
    *,
    status: str = "invalid_input",
) -> dict[str, Any]:
    report = base_report(schema_version, detail_status)
    report["status"] = status
    report["errors"] = errors
    return report
