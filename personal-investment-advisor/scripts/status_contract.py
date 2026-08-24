"""Stable public status contract for Personal Investment Advisor commands.

The business scripts pre-date this module and intentionally keep their existing
status values.  Public entrypoints use this module to translate those values
into a small, fail-closed vocabulary without changing the underlying result.
"""

from __future__ import annotations

from typing import Any, Iterable


CONTRACT_VERSION = "1.1"

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
STATUS_FAILED = "failed"

CANONICAL_STATUSES = frozenset(
    {
        STATUS_COMPLETE,
        STATUS_INCOMPLETE,
        STATUS_INSUFFICIENT_EVIDENCE,
        STATUS_FAILED,
    }
)

EXIT_CODES = {
    STATUS_COMPLETE: 0,
    STATUS_INCOMPLETE: 1,
    STATUS_INSUFFICIENT_EVIDENCE: 2,
    STATUS_FAILED: 3,
}

_SUCCESS_STATUSES = frozenset(
    {
        "calculated",
        "complete",
        "completed",
        "ok",
        "pass",
        "passed",
        "success",
        "valid",
    }
)
_INCOMPLETE_STATUSES = frozenset(
    {
        "incomplete",
        "partial",
        "pending",
        "not_calculated",
        "not_assessed",
        "not_run",
    }
)
_INSUFFICIENT_STATUSES = frozenset(
    {
        "file_missing",
        "insufficient_data",
        "insufficient_evidence",
        "missing",
        "not_applicable",
        "not_configured",
        "not_found",
        "runtime_quote_missing",
        "stale_data",
        "thresholds_undefined",
    }
)
_FAILED_STATUSES = frozenset(
    {
        "data_error",
        "error",
        "fail",
        "failed",
        "failure",
        "invalid",
        "invalid_input",
    }
)

_STATUS_PRIORITY = {
    STATUS_COMPLETE: 0,
    STATUS_INCOMPLETE: 1,
    STATUS_INSUFFICIENT_EVIDENCE: 2,
    STATUS_FAILED: 3,
}


def normalize_status(value: Any) -> str:
    """Translate a native status into the public vocabulary.

    Unknown, empty, and non-string values are failures.  This is deliberate:
    a new native state must be reviewed before a public caller can rely on it.
    """

    if not isinstance(value, str) or not value.strip():
        return STATUS_FAILED
    normalized = value.strip().lower()
    if normalized in CANONICAL_STATUSES:
        return normalized
    if normalized in _SUCCESS_STATUSES:
        return STATUS_COMPLETE
    if normalized in _INCOMPLETE_STATUSES:
        return STATUS_INCOMPLETE
    if normalized in _INSUFFICIENT_STATUSES:
        return STATUS_INSUFFICIENT_EVIDENCE
    if normalized in _FAILED_STATUSES:
        return STATUS_FAILED
    return STATUS_FAILED


def aggregate_status(statuses: Iterable[Any]) -> str:
    """Return the most conservative canonical status in ``statuses``."""

    normalized = [normalize_status(status) for status in statuses]
    if not normalized:
        return STATUS_FAILED
    return max(normalized, key=_STATUS_PRIORITY.__getitem__)


def status_from_payload(payload: Any, child_exit_code: int) -> str:
    """Derive a canonical status from JSON output and a child exit code."""

    if isinstance(payload, dict):
        candidates = [normalize_status(payload.get("status"))]
        if payload.get("valid") is False:
            candidates.append(STATUS_FAILED)
        errors = payload.get("errors")
        if (
            isinstance(errors, list)
            and errors
            and candidates[0] == STATUS_COMPLETE
        ):
            candidates.append(STATUS_FAILED)
        completeness = payload.get("completeness")
        if (
            isinstance(completeness, dict)
            and completeness.get("complete") is False
        ):
            candidates.append(STATUS_INCOMPLETE)
        stages = payload.get("stages")
        if isinstance(stages, list) and stages:
            stage_statuses = [
                stage.get("status")
                for stage in stages
                if isinstance(stage, dict) and "status" in stage
            ]
            if stage_statuses:
                candidates.extend(stage_statuses)
        status = aggregate_status(candidates)
    elif isinstance(payload, list) and payload:
        native_statuses = [
            item.get("status") if isinstance(item, dict) else None for item in payload
        ]
        status = aggregate_status(native_statuses)
    else:
        return STATUS_FAILED

    # Native children use 0 for success, 1 for an incomplete/business failure,
    # and 2 for invalid input or insufficient evidence.  Crash-style or stable
    # public failure exits (3+) always outrank a softer payload declaration.
    if child_exit_code < 0 or child_exit_code >= exit_code_for(STATUS_FAILED):
        return STATUS_FAILED
    if child_exit_code == 2 and status in {STATUS_COMPLETE, STATUS_INCOMPLETE}:
        return STATUS_FAILED
    if child_exit_code == 1 and status == STATUS_COMPLETE:
        return STATUS_FAILED
    return status


def exit_code_for(status: Any) -> int:
    """Return the stable process exit code, failing closed for unknown values."""

    return EXIT_CODES[normalize_status(status)]


def make_envelope(
    *,
    command: str,
    status: Any,
    detail_status: str,
    result: Any = None,
    errors: Iterable[str] = (),
    limitations: Iterable[str] = (),
    route: dict[str, Any] | None = None,
    completion_scope: str | None = None,
) -> dict[str, Any]:
    """Build the stable JSON envelope returned by ``pia.py``."""

    canonical = normalize_status(status)
    return {
        "contract_version": CONTRACT_VERSION,
        "command": command,
        "status": canonical,
        "detail_status": detail_status,
        "exit_code": EXIT_CODES[canonical],
        "completion_scope": completion_scope,
        "result": result,
        "errors": [str(error) for error in errors if str(error)],
        "limitations": [str(item) for item in limitations if str(item)],
        "route": route or {},
    }
