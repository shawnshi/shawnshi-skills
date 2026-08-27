"""Durable, process-safe state store for healthcare strategy work.

The command line intentionally keeps the original ``init``, ``update``,
``status``, ``validate`` and ``ready`` commands. Schema v2 makes the decision,
evidence, financial model, roadmap, compliance context and portfolio explicit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import tempfile
import sys
from typing import Any, Iterator


BLACKBOARD_RELATIVE = Path("tmp") / "strategy_blackboard.json"
SCHEMA_VERSION = 2
MODES = ("brief", "board-memo", "deep-dive", "investment-case")
MATURITY_LEVELS = (
    "working_draft",
    "review_ready",
    "decision_ready",
    "approved_for_execution",
    "blocked",
)

TOP_LEVEL_SECTIONS = (
    "metadata",
    "alignment",
    "evidence",
    "logic_mesh",
    "decisions",
    "quantitative_model",
    "roadmap",
    "compliance_context",
    "portfolio",
    "deliverables",
)

CANONICAL_RECORD_STATUSES = {
    "client_provided",
    "externally_verified",
    "calculated",
    "scenario_assumption",
    "analyst_judgment",
    "needs_input",
    "not_applicable",
}
# Read old records, but flag the alias so the next edit can normalize it.
LEGACY_RECORD_STATUSES = {"sourced", "verified"}
RECORD_STATUSES = CANONICAL_RECORD_STATUSES | LEGACY_RECORD_STATUSES
EVIDENCE_RECORD_TYPES = {"verified_fact", "source_claim"}
EVIDENCE_SOURCE_TYPES = {"primary", "secondary", "user_material"}
EVIDENCE_STRENGTHS = {"high", "medium", "low"}
EVIDENCE_STATUSES = {"active", "disputed", "superseded"}
EVIDENCE_ID_RE = re.compile(r"^EV-[A-Z]{3}-\d{3}$")
EVIDENCE_FIELDS = {
    "evidence_id",
    "record_type",
    "claim",
    "source_title",
    "publisher",
    "source_type",
    "published_at",
    "event_or_data_period",
    "accessed_at",
    "region_and_population",
    "locator",
    "method_and_denominator",
    "limitations",
    "independence_group",
    "strength",
    "status",
    "supersedes",
}

ASSUMPTION_FIELDS = {
    "name",
    "value",
    "unit",
    "source",
    "as_of",
    "region",
    "status",
}

PROTECTED_METADATA_FIELDS = {
    "schema_version",
    "revision",
    "created_at",
    "updated_at",
}


class BlackboardError(Exception):
    """Expected operational error that is safe to return as JSON."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code

    def payload(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return {"status": "error", "error": error}


class JSONArgumentParser(argparse.ArgumentParser):
    """Keep --help readable while returning malformed CLI input as JSON."""

    def error(self, message: str) -> None:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {"code": "INVALID_ARGUMENT", "message": message},
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def blackboard_path(workspace_root: Path) -> Path:
    return workspace_root / BLACKBOARD_RELATIVE


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


@contextmanager
def _file_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Hold an advisory cross-process lock for one complete read/write unit."""

    lock_path = _lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK
            msvcrt.locking(handle.fileno(), mode, 1)
        else:
            import fcntl

            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(handle.fileno(), mode)
        yield
    finally:
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def default_state(topic: str, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise BlackboardError(
            "INVALID_MODE",
            f"mode must be one of: {', '.join(MODES)}",
            details={"mode": mode},
        )
    timestamp = _now()
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "revision": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
            "maturity": "working_draft",
            "approval": {
                "authority": "",
                "authority_role": "",
                "decision": "",
                "as_of": "",
                "source": "",
            },
            "topic": topic,
            "mode": mode,
        },
        "alignment": {
            "decision": "",
            "questions_to_decide": [],
            "audience": [],
            "organization": {"name": "", "type": "", "region": ""},
            "time_horizon": {"start": "", "end": "", "description": ""},
            "decision_deadline": "",
            "budget": {
                "amount": None,
                "currency": "",
                "period": "",
                "source": "",
                "status": "needs_input",
            },
            "success_metrics": [],
            "constraints": [],
            "unacceptable_risks": [],
        },
        "evidence": {"records": [], "gaps": [], "conflicts": []},
        "logic_mesh": {
            "alternatives": [],
            "conflicts": [],
            "core_judgment": "",
            "counter_evidence": [],
        },
        "decisions": {
            "recommendation": "",
            "action_levers": [],
            "management_decisions": [],
            "residual_risks": [],
        },
        "quantitative_model": {
            "applicable": None,
            "not_applicable_reason": "",
            "model_type": "",
            "currency": "",
            "horizon_years": None,
            "discount_rate_assumption_id": "",
            "validation_tolerance": {
                "amount_absolute": 0.01,
                "ratio_absolute": 0.000001,
                "percentage_point_absolute": 0.05,
                "relative": 0.000001,
            },
            "baseline": {},
            "counterfactual": {},
            "assumptions": [],
            "cost_items": [],
            "benefit_items": [],
            "cash_flows": [],
            "formulas": [],
            "scenarios": [],
            "sensitivity": [],
            "outputs": [],
        },
        "roadmap": {
            "phases": [],
            "dependencies": [],
            "governance": {
                "executive_sponsor": "",
                "accountable_owner": "",
                "decision_forum": "",
                "review_cadence": "",
            },
        },
        "compliance_context": {
            "applicability": "undetermined",
            "rationale": "",
            "jurisdiction": "",
            "as_of": "",
            "intended_use": "",
            "data_types": [],
            "affected_users": [],
            "review_required": None,
            "escalations": [],
            "status": "not_reviewed",
        },
        "portfolio": {
            "applicable": None,
            "not_applicable_reason": "",
            "candidates": [],
            "scoring_criteria": [],
            "prioritization": [],
            "gate_results": [],
            "capacity_constraints": [],
            "dependencies": [],
        },
        "deliverables": {
            "project_path": "",
            "implementation_plan": "",
            "outline": "",
            "final_report": "",
        },
    }


def _read_json_unlocked(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except json.JSONDecodeError as exc:
        raise BlackboardError(
            "INVALID_JSON",
            "blackboard contains invalid JSON",
            details={
                "path": str(path),
                "line": exc.lineno,
                "column": exc.colno,
                "reason": exc.msg,
            },
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise BlackboardError(
            "READ_FAILED",
            "blackboard could not be read",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if not isinstance(state, dict):
        raise BlackboardError(
            "INVALID_ROOT",
            "blackboard root must be a JSON object",
            details={"path": str(path)},
        )
    return state


def _atomic_write_unlocked(path: Path, state: dict[str, Any]) -> None:
    """Durably replace a state file without exposing a partial JSON document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        temp_name = None
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise BlackboardError(
            "WRITE_FAILED",
            "blackboard could not be written atomically",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _string_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _legacy_evidence_records(evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence, dict):
        return []
    if isinstance(evidence.get("records"), list):
        records: list[dict[str, Any]] = []
        for index, value in enumerate(evidence["records"], start=1):
            if not isinstance(value, dict):
                records.append(value)
                continue
            record = deepcopy(value)
            if "evidence_id" not in record and "id" in record:
                record["evidence_id"] = record.pop("id")
            legacy_provenance = record.get("status")
            record.setdefault("record_type", "source_claim")
            record.setdefault(
                "source_type",
                "user_material"
                if legacy_provenance == "client_provided"
                else "primary",
            )
            source = record.pop("source", None)
            if isinstance(source, dict):
                record.setdefault("source_title", source.get("title"))
                record.setdefault("publisher", source.get("publisher"))
                record.setdefault(
                    "locator",
                    source.get("locator") or source.get("url") or source.get("path"),
                )
            elif source:
                record.setdefault("locator", source)
            record.setdefault("source_title", None)
            record.setdefault("publisher", None)
            record.setdefault("published_at", None)
            record.setdefault("event_or_data_period", record.pop("as_of", None))
            record.setdefault("accessed_at", None)
            record.setdefault("region_and_population", record.pop("region", None))
            record.setdefault("locator", None)
            record.setdefault("method_and_denominator", None)
            record.setdefault("limitations", None)
            record.setdefault("independence_group", None)
            record.setdefault("strength", "low")
            record["status"] = (
                legacy_provenance
                if legacy_provenance in EVIDENCE_STATUSES
                else "active"
            )
            record.setdefault("supersedes", None)
            records.append(record)
        return records
    records: list[dict[str, Any]] = []
    category_map = {
        "facts": "fact",
        "policy": "policy",
        "market": "market",
        "vendor": "vendor",
        "clinical": "clinical",
    }
    for legacy_key, category in category_map.items():
        values = evidence.get(legacy_key, [])
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values, start=1):
            if isinstance(value, dict):
                record = deepcopy(value)
                claim = record.pop("claim", record.pop("text", record.pop("content", "")))
                source = record.pop("source", None)
                if isinstance(source, dict):
                    source_title = source.get("title")
                    publisher = source.get("publisher")
                    locator = source.get("locator") or source.get("url") or source.get("path")
                else:
                    source_title = None
                    publisher = None
                    locator = source
                record = {
                    "evidence_id": f"EV-{_legacy_domain(category)}-{index:03d}",
                    "record_type": "source_claim",
                    "claim": claim,
                    "source_title": source_title,
                    "publisher": publisher,
                    "source_type": "user_material",
                    "published_at": None,
                    "event_or_data_period": record.get("as_of"),
                    "accessed_at": None,
                    "region_and_population": record.get("region"),
                    "locator": locator,
                    "method_and_denominator": None,
                    "limitations": "Migrated from schema v1; provenance needs review.",
                    "independence_group": None,
                    "strength": "low",
                    "status": "active",
                    "supersedes": None,
                }
            else:
                record = {
                    "evidence_id": f"EV-{_legacy_domain(category)}-{index:03d}",
                    "record_type": "source_claim",
                    "claim": str(value),
                    "source_title": None,
                    "publisher": None,
                    "source_type": "user_material",
                    "published_at": None,
                    "event_or_data_period": None,
                    "accessed_at": None,
                    "region_and_population": None,
                    "locator": None,
                    "method_and_denominator": None,
                    "limitations": "Migrated from schema v1; provenance needs review.",
                    "independence_group": None,
                    "strength": "low",
                    "status": "active",
                    "supersedes": None,
                }
            records.append(record)
    return records


def _legacy_domain(category: str) -> str:
    return {
        "fact": "OPS",
        "policy": "POL",
        "market": "MKT",
        "vendor": "VEN",
        "clinical": "CLN",
    }.get(category, "OPS")


def _legacy_metric(metric: Any, index: int) -> dict[str, Any]:
    if isinstance(metric, dict):
        result = deepcopy(metric)
        result.setdefault("id", f"metric-{index}")
        result.setdefault("name", str(result.get("metric", "")))
        return result
    return {
        "id": f"metric-{index}",
        "name": str(metric),
        "baseline": None,
        "target": None,
        "unit": "",
        "timeframe": "",
        "source": "",
        "status": "needs_input",
    }


def _legacy_phase(phase: Any, index: int) -> dict[str, Any]:
    if isinstance(phase, dict):
        result = deepcopy(phase)
        result.setdefault("id", f"phase-{index}")
        return result
    return {
        "id": f"phase-{index}",
        "name": str(phase),
        "timeframe": "",
        "owner": "",
        "outcomes": [],
        "exit_criteria": [],
        "dependencies": [],
        "status": "proposed",
    }


def migrate_v1(state: dict[str, Any]) -> dict[str, Any]:
    """Convert the former nested layout to the sole supported v2 layout."""

    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    mode = metadata.get("mode") or (
        state.get("alignment", {}).get("mode")
        if isinstance(state.get("alignment"), dict)
        else None
    )
    if mode not in MODES:
        mode = "deep-dive"
    migrated = default_state(str(metadata.get("topic") or "Untitled"), mode)
    migrated["metadata"].update(
        {
            "revision": metadata.get("revision", 0)
            if isinstance(metadata.get("revision", 0), int)
            else 0,
            "created_at": metadata.get("created_at") or migrated["metadata"]["created_at"],
            "updated_at": metadata.get("updated_at") or migrated["metadata"]["updated_at"],
            "maturity": {
                "ready": "decision_ready",
                "complete": "decision_ready",
                "blocked": "blocked",
            }.get(metadata.get("status"), "working_draft"),
            "migrated_from_schema_version": metadata.get("schema_version", 1),
        }
    )
    if isinstance(metadata.get("approval"), dict):
        migrated["metadata"]["approval"].update(deepcopy(metadata["approval"]))

    alignment = state.get("alignment") if isinstance(state.get("alignment"), dict) else {}
    migrated_alignment = migrated["alignment"]
    migrated_alignment["decision"] = alignment.get("decision", "")
    migrated_alignment["questions_to_decide"] = _string_list(
        alignment.get("questions_to_decide", [])
    )
    migrated_alignment["audience"] = _string_list(alignment.get("audience", []))
    organization = alignment.get("organization")
    if isinstance(organization, dict):
        migrated_alignment["organization"].update(organization)
    time_horizon = alignment.get("time_horizon")
    if isinstance(time_horizon, dict):
        migrated_alignment["time_horizon"].update(time_horizon)
    elif time_horizon:
        migrated_alignment["time_horizon"]["description"] = str(time_horizon)
    budget = alignment.get("budget")
    if isinstance(budget, dict):
        migrated_alignment["budget"].update(budget)
    elif budget:
        migrated_alignment["budget"]["source"] = str(budget)
    metrics = alignment.get("success_metrics", [])
    if isinstance(metrics, list):
        migrated_alignment["success_metrics"] = [
            _legacy_metric(metric, index)
            for index, metric in enumerate(metrics, start=1)
        ]
    for key in ("constraints", "unacceptable_risks"):
        migrated_alignment[key] = _string_list(alignment.get(key, []))
    migrated_alignment["decision_deadline"] = alignment.get("decision_deadline", "")

    evidence = state.get("evidence") if isinstance(state.get("evidence"), dict) else {}
    migrated["evidence"]["records"] = _legacy_evidence_records(evidence)
    migrated["evidence"]["gaps"] = _string_list(evidence.get("gaps", []))
    migrated["evidence"]["conflicts"] = _string_list(evidence.get("conflicts", []))

    logic_mesh = state.get("logic_mesh")
    if isinstance(logic_mesh, dict):
        migrated["logic_mesh"].update(deepcopy(logic_mesh))

    decisions = state.get("decisions") if isinstance(state.get("decisions"), dict) else {}
    for key in ("recommendation", "action_levers", "management_decisions", "residual_risks"):
        if key in decisions:
            migrated["decisions"][key] = deepcopy(decisions[key])
    legacy_quant = decisions.get("quantitative_model")
    if isinstance(legacy_quant, dict):
        migrated["quantitative_model"].update(deepcopy(legacy_quant))
        migrated["quantitative_model"]["applicable"] = bool(
            legacy_quant.get("assumptions") or legacy_quant.get("scenarios")
        )
    legacy_roadmap = decisions.get("roadmap", state.get("roadmap"))
    if isinstance(legacy_roadmap, dict):
        migrated["roadmap"].update(deepcopy(legacy_roadmap))
    elif isinstance(legacy_roadmap, list):
        migrated["roadmap"]["phases"] = [
            _legacy_phase(phase, index)
            for index, phase in enumerate(legacy_roadmap, start=1)
        ]

    compliance = state.get("compliance_context", state.get("compliance"))
    if isinstance(compliance, dict):
        migrated_compliance = deepcopy(compliance)
        migrated["compliance_context"].update(migrated_compliance)
        if "affected_groups" in compliance and "affected_users" not in compliance:
            migrated["compliance_context"]["affected_users"] = deepcopy(
                compliance["affected_groups"]
            )
    portfolio = state.get("portfolio")
    if isinstance(portfolio, dict):
        migrated["portfolio"].update(deepcopy(portfolio))
    deliverables = state.get("deliverables")
    if isinstance(deliverables, dict):
        migrated["deliverables"].update(deepcopy(deliverables))
    return migrated


def _normalize_loaded_state(state: dict[str, Any]) -> dict[str, Any]:
    metadata = state.get("metadata")
    version = metadata.get("schema_version") if isinstance(metadata, dict) else None
    if version == 1:
        return migrate_v1(state)
    return state


def load_state(workspace_root: Path) -> tuple[Path, dict[str, Any]]:
    """Load an initialized blackboard; never manufacture missing state."""

    path = blackboard_path(workspace_root)
    if not path.exists():
        raise BlackboardError(
            "NOT_INITIALIZED",
            "blackboard is not initialized; run the init command first",
            details={"path": str(path)},
        )
    with _file_lock(path, exclusive=False):
        if not path.exists():
            raise BlackboardError(
                "NOT_INITIALIZED",
                "blackboard disappeared while it was being opened",
                details={"path": str(path)},
            )
        return path, _normalize_loaded_state(_read_json_unlocked(path))


def save_state(
    path: Path,
    state: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> None:
    """Compatibility API for safe writes by companion scripts."""

    if not path.exists():
        raise BlackboardError(
            "NOT_INITIALIZED",
            "refusing to create state outside the init command",
            details={"path": str(path)},
        )
    with _file_lock(path, exclusive=True):
        current = _normalize_loaded_state(_read_json_unlocked(path))
        current_revision = current.get("metadata", {}).get("revision")
        if expected_revision is None:
            supplied_revision = state.get("metadata", {}).get("revision")
            if isinstance(supplied_revision, int) and not isinstance(
                supplied_revision, bool
            ):
                expected_revision = supplied_revision
        if expected_revision is not None and current_revision != expected_revision:
            raise BlackboardError(
                "REVISION_CONFLICT",
                "blackboard changed after it was read",
                details={
                    "path": str(path),
                    "expected_revision": expected_revision,
                    "actual_revision": current_revision,
                },
            )
        candidate = deepcopy(state)
        metadata = candidate.setdefault("metadata", {})
        metadata["schema_version"] = SCHEMA_VERSION
        metadata["revision"] = (current_revision if isinstance(current_revision, int) else 0) + 1
        metadata.setdefault("created_at", current.get("metadata", {}).get("created_at", _now()))
        metadata["updated_at"] = _now()
        report = validate_state(candidate)
        if report["errors"]:
            raise BlackboardError(
                "INVALID_STATE",
                "refusing to persist a state that violates schema v2",
                details={"errors": report["errors"]},
            )
        _atomic_write_unlocked(path, candidate)


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped[0] in "{[\"" or stripped[0].isdigit() or stripped[0] == "-":
        return True
    return stripped.startswith(("true", "false", "null"))


def _decode_external_value(
    text: str,
    *,
    source: str,
    require_json: bool,
) -> Any:
    if not text.strip():
        raise BlackboardError(
            "VALUE_JSON_INVALID",
            "external value input is empty",
            details={"source": source},
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if not require_json and not _looks_like_json(text):
            return text.rstrip("\r\n")
        raise BlackboardError(
            "VALUE_JSON_INVALID",
            "external value contains invalid JSON",
            details={
                "source": source,
                "line": exc.lineno,
                "column": exc.colno,
                "reason": exc.msg,
            },
        ) from exc


def parse_update_value(raw: str) -> Any:
    """Read inline, @file, or stdin update values without changing inline semantics."""

    if raw == "-":
        try:
            text = sys.stdin.read()
        except (OSError, UnicodeError) as exc:
            raise BlackboardError(
                "VALUE_STDIN_READ_FAILED",
                "could not read update value from stdin",
                details={"reason": str(exc)},
            ) from exc
        return _decode_external_value(text, source="stdin", require_json=False)
    if raw.startswith("@"):
        if len(raw) == 1:
            raise BlackboardError(
                "VALUE_READ_FAILED",
                "@file value source requires a file path",
            )
        value_path = Path(raw[1:])
        try:
            text = value_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BlackboardError(
                "VALUE_READ_FAILED",
                "could not read update value file",
                details={"path": str(value_path), "reason": str(exc)},
            ) from exc
        return _decode_external_value(
            text,
            source=str(value_path),
            require_json=value_path.suffix.lower() == ".json",
        )
    return parse_value(raw)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _meaningful_horizon(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, dict):
        return False
    return any(_present(value.get(key)) for key in ("start", "end", "description"))


def _source_present(source: Any) -> bool:
    if isinstance(source, str):
        return bool(source.strip())
    if isinstance(source, dict):
        return any(
            _present(source.get(key))
            for key in ("title", "publisher", "url", "path", "locator", "reference")
        )
    return False


SUPPORTED_FORMULA_TYPES = {
    "sum",
    "difference",
    "product",
    "ratio",
    "roi",
    "tco",
    "total_benefit",
    "net_benefit",
    "sum_costs",
    "sum_benefits",
    "sum_net",
    "npv",
    "custom",
}

OUTPUT_METRIC_ALIASES = {
    "tco": "total_tco",
    "total_cost": "total_tco",
    "total_costs": "total_tco",
    "total_tco": "total_tco",
    "nominal_tco": "total_tco",
    "total_benefit": "total_benefit",
    "total_benefits": "total_benefit",
    "benefit": "total_benefit",
    "nominal_benefit": "total_benefit",
    "roi": "roi",
    "roi_nominal_base": "roi",
    "net_benefit": "net_benefit",
    "net_benefits": "net_benefit",
    "npv": "npv",
    "npv_base": "npv",
}


def _decimal_number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _quantitative_tolerances(
    quantitative: dict[str, Any],
    error,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    defaults = (
        Decimal("0.01"),
        Decimal("0.000001"),
        Decimal("0.05"),
        Decimal("0.000001"),
    )
    tolerance = quantitative.get("validation_tolerance")
    if not isinstance(tolerance, dict):
        error(
            "TYPE",
            "quantitative_model.validation_tolerance",
            "must be a JSON object",
        )
        return defaults
    values: list[Decimal] = []
    for field, default in zip(
        (
            "amount_absolute",
            "ratio_absolute",
            "percentage_point_absolute",
            "relative",
        ),
        defaults,
    ):
        parsed = _decimal_number(tolerance.get(field))
        if parsed is None or parsed < 0:
            error(
                "INVALID_TOLERANCE",
                f"quantitative_model.validation_tolerance.{field}",
                "must be a finite non-negative number",
            )
            parsed = default
        values.append(parsed)
    return values[0], values[1], values[2], values[3]


def _numbers_match(
    actual: Decimal,
    expected: Decimal,
    *,
    absolute: Decimal,
    relative: Decimal,
) -> bool:
    allowed = max(absolute, abs(expected) * relative)
    return abs(actual - expected) <= allowed


def _validate_investment_consistency(
    state: dict[str, Any],
    error,
    warn,
) -> None:
    """Validate references and recompute only explicitly supported arithmetic."""

    quantitative = state["quantitative_model"]
    machine_readable_started = any(
        _present(quantitative.get(collection))
        for collection in ("cash_flows", "formulas", "scenarios", "outputs")
    )
    # A newly initialized investment case is an editable draft. Completeness is
    # already represented by readiness warnings; arithmetic becomes a hard gate
    # only after the author opts in or supplies machine-verifiable records.
    if quantitative.get("applicable") is not True and not machine_readable_started:
        return
    evidence_records = state["evidence"].get("records", [])
    (
        amount_tolerance,
        ratio_tolerance,
        percentage_tolerance,
        relative_tolerance,
    ) = _quantitative_tolerances(quantitative, error)
    horizon = _decimal_number(quantitative.get("horizon_years"))
    if (
        horizon is None
        or horizon != horizon.to_integral_value()
        or horizon <= 0
    ):
        error(
            "INVALID_NUMBER",
            "quantitative_model.horizon_years",
            "must be a positive integer for investment-case mode",
        )

    collection_names = (
        "assumptions",
        "cost_items",
        "benefit_items",
        "cash_flows",
        "formulas",
        "scenarios",
        "outputs",
    )
    items_by_collection: dict[str, list[Any]] = {}
    id_maps: dict[str, dict[str, dict[str, Any]]] = {}
    all_ids: dict[str, str] = {}
    for collection in collection_names:
        items = quantitative.get(collection, [])
        if not isinstance(items, list):
            items = []
        items_by_collection[collection] = items
        indexed: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(items):
            path = f"quantitative_model.{collection}[{index}]"
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if collection == "assumptions" and not _present(item_id):
                item_id = item.get("assumption_id")
                if _present(item_id):
                    warn(
                        "LEGACY_FIELD",
                        f"{path}.assumption_id",
                        "use id as the canonical stable quantitative identifier",
                    )
            if not _present(item_id):
                error(
                    "REQUIRED",
                    f"{path}.id",
                    "a stable case-sensitive ID is required for investment-case mode",
                )
                continue
            item_id = str(item_id)
            if item_id in all_ids:
                error(
                    "DUPLICATE_ID",
                    f"{path}.id",
                    f"ID {item_id} is already used by {all_ids[item_id]}",
                )
                continue
            all_ids[item_id] = path
            indexed[item_id] = item
        id_maps[collection] = indexed

    assumption_ids = set(id_maps["assumptions"])
    cost_ids = set(id_maps["cost_items"])
    benefit_ids = set(id_maps["benefit_items"])
    cash_flow_ids = set(id_maps["cash_flows"])
    formula_ids = set(id_maps["formulas"])
    scenario_ids = set(id_maps["scenarios"])
    output_ids = set(id_maps["outputs"])
    formula_input_ids = assumption_ids | cost_ids | benefit_ids | cash_flow_ids | formula_ids
    evidence_ids = {
        str(record.get("evidence_id") or record.get("id"))
        for record in evidence_records
        if isinstance(record, dict)
        and _present(record.get("evidence_id") or record.get("id"))
    }
    scenario_types: set[str] = set()
    for scenario_id, scenario in id_maps["scenarios"].items():
        index = items_by_collection["scenarios"].index(scenario)
        scenario_type = scenario.get("scenario_type")
        if scenario_type not in {"base", "downside", "upside", "custom"}:
            warn(
                "SCENARIO_COVERAGE",
                f"quantitative_model.scenarios[{index}].scenario_type",
                "use base, downside, upside, or custom to make scenario coverage auditable",
            )
        else:
            scenario_types.add(scenario_type)
    for required_type in ("base", "downside"):
        if required_type not in scenario_types:
            warn(
                "SCENARIO_COVERAGE",
                "quantitative_model.scenarios",
                f"investment-case mode should include a typed {required_type} scenario",
            )

    def exact_reference(
        reference: Any,
        allowed: set[str],
        path: str,
        target: str,
    ) -> None:
        if not _present(reference):
            return
        if not isinstance(reference, str) or reference not in allowed:
            error(
                "UNKNOWN_REFERENCE",
                path,
                f"must exactly match an existing {target} ID (case-sensitive)",
            )

    exact_reference(
        quantitative.get("discount_rate_assumption_id"),
        assumption_ids,
        "quantitative_model.discount_rate_assumption_id",
        "assumption",
    )

    for item_id, item in id_maps["cost_items"].items():
        index = items_by_collection["cost_items"].index(item)
        path = f"quantitative_model.cost_items[{index}]"
        exact_reference(item.get("evidence_id"), evidence_ids, f"{path}.evidence_id", "evidence")
        exact_reference(
            item.get("assumption_id"),
            assumption_ids,
            f"{path}.assumption_id",
            "assumption",
        )
        formula_reference = item.get("formula")
        if _present(formula_reference):
            exact_reference(formula_reference, formula_ids, f"{path}.formula", "formula")

    for item_id, item in id_maps["benefit_items"].items():
        index = items_by_collection["benefit_items"].index(item)
        path = f"quantitative_model.benefit_items[{index}]"
        exact_reference(item.get("formula"), formula_ids, f"{path}.formula", "formula")

    for item_id, formula in id_maps["formulas"].items():
        index = items_by_collection["formulas"].index(formula)
        path = f"quantitative_model.formulas[{index}]"
        formula_type = formula.get("formula_type") or formula.get("type")
        if "formula_type" not in formula and _present(formula.get("type")):
            warn(
                "LEGACY_FIELD",
                f"{path}.type",
                "use formula_type as the canonical explicit calculation type",
            )
        if not _present(formula_type):
            error(
                "REQUIRED",
                f"{path}.formula_type",
                "an explicit safe formula type is required",
            )
        elif not isinstance(formula_type, str):
            error(
                "TYPE",
                f"{path}.formula_type",
                "must be a string",
            )
        elif formula_type not in SUPPORTED_FORMULA_TYPES:
            warn(
                "UNVERIFIABLE_FORMULA",
                f"{path}.formula_type",
                "unsupported custom formula type was documented but not executed",
            )
        input_ids = formula.get("input_ids")
        if isinstance(input_ids, list):
            seen_inputs: set[str] = set()
            for input_index, input_id in enumerate(input_ids):
                exact_reference(
                    input_id,
                    formula_input_ids,
                    f"{path}.input_ids[{input_index}]",
                    "quantitative input",
                )
                if isinstance(input_id, str):
                    if input_id in seen_inputs:
                        error(
                            "DUPLICATE_REFERENCE",
                            f"{path}.input_ids[{input_index}]",
                            "formula input IDs must not be repeated",
                        )
                    seen_inputs.add(input_id)
        rate_id = formula.get("discount_rate_assumption_id")
        if formula_type == "npv":
            rate_id = rate_id or quantitative.get("discount_rate_assumption_id")
            if not _present(rate_id):
                warn(
                    "UNVERIFIABLE_FORMULA",
                    f"{path}.discount_rate_assumption_id",
                    "NPV requires an explicit discount-rate assumption ID",
                )
            else:
                exact_reference(
                    rate_id,
                    assumption_ids,
                    f"{path}.discount_rate_assumption_id",
                    "assumption",
                )
        exact_reference(
            formula.get("scenario_id"),
            scenario_ids,
            f"{path}.scenario_id",
            "scenario",
        )
        if isinstance(formula.get("scenario_id"), str) and isinstance(
            input_ids, list
        ):
            for input_index, input_id in enumerate(input_ids):
                if isinstance(input_id, str) and input_id in id_maps["cash_flows"]:
                    row_scenario = id_maps["cash_flows"][input_id].get("scenario_id")
                    if _present(row_scenario) and row_scenario != formula.get(
                        "scenario_id"
                    ):
                        error(
                            "REFERENCE_MISMATCH",
                            f"{path}.input_ids[{input_index}]",
                            "formula cash-flow input belongs to a different scenario",
                        )
        exact_reference(
            formula.get("output_id"),
            output_ids,
            f"{path}.output_id",
            "output",
        )

    for item_id, scenario in id_maps["scenarios"].items():
        index = items_by_collection["scenarios"].index(scenario)
        path = f"quantitative_model.scenarios[{index}]"
        assumption_references = scenario.get("assumption_ids")
        if isinstance(assumption_references, list):
            seen_assumptions: set[str] = set()
            for ref_index, reference in enumerate(assumption_references):
                exact_reference(
                    reference,
                    assumption_ids,
                    f"{path}.assumption_ids[{ref_index}]",
                    "assumption",
                )
                if isinstance(reference, str):
                    if reference in seen_assumptions:
                        error(
                            "DUPLICATE_REFERENCE",
                            f"{path}.assumption_ids[{ref_index}]",
                            "scenario assumption IDs must not be repeated",
                        )
                    seen_assumptions.add(reference)
        cash_references = scenario.get("cash_flow_ids")
        if cash_references is not None and not isinstance(cash_references, list):
            error("TYPE", f"{path}.cash_flow_ids", "must be a list of cash-flow IDs")
        elif isinstance(cash_references, list):
            seen_cash_flows: set[str] = set()
            for ref_index, reference in enumerate(cash_references):
                exact_reference(
                    reference,
                    cash_flow_ids,
                    f"{path}.cash_flow_ids[{ref_index}]",
                    "cash-flow",
                )
                if isinstance(reference, str):
                    if reference in seen_cash_flows:
                        error(
                            "DUPLICATE_REFERENCE",
                            f"{path}.cash_flow_ids[{ref_index}]",
                            "scenario cash-flow IDs must not be repeated",
                        )
                    seen_cash_flows.add(reference)
                    if reference in id_maps["cash_flows"]:
                        row_scenario = id_maps["cash_flows"][reference].get(
                            "scenario_id"
                        )
                        if _present(row_scenario) and row_scenario != item_id:
                            error(
                                "REFERENCE_MISMATCH",
                                f"{path}.cash_flow_ids[{ref_index}]",
                                "cash-flow row belongs to a different scenario",
                            )
        rate_id = scenario.get("discount_rate_assumption_id")
        if _present(rate_id):
            exact_reference(
                rate_id,
                assumption_ids,
                f"{path}.discount_rate_assumption_id",
                "assumption",
            )
            if (
                isinstance(rate_id, str)
                and isinstance(assumption_references, list)
                and rate_id not in assumption_references
            ):
                error(
                    "REFERENCE_MISMATCH",
                    f"{path}.discount_rate_assumption_id",
                    "discount-rate assumption must also appear in scenario.assumption_ids",
                )
        output_references = scenario.get("output")
        if isinstance(output_references, list):
            for ref_index, reference in enumerate(output_references):
                exact_reference(
                    reference,
                    output_ids,
                    f"{path}.output[{ref_index}]",
                    "output",
                )

    for item_id, output in id_maps["outputs"].items():
        index = items_by_collection["outputs"].index(output)
        exact_reference(
            output.get("scenario_id"),
            scenario_ids,
            f"quantitative_model.outputs[{index}].scenario_id",
            "scenario",
        )
        exact_reference(
            output.get("formula_id"),
            formula_ids,
            f"quantitative_model.outputs[{index}].formula_id",
            "formula",
        )

    for item_id, row in id_maps["cash_flows"].items():
        if _present(row.get("scenario_id")):
            index = items_by_collection["cash_flows"].index(row)
            exact_reference(
                row.get("scenario_id"),
                scenario_ids,
                f"quantitative_model.cash_flows[{index}].scenario_id",
                "scenario",
            )

    for formula_id, formula in id_maps["formulas"].items():
        output_id = formula.get("output_id")
        if isinstance(output_id, str) and output_id in id_maps["outputs"]:
            output = id_maps["outputs"][output_id]
            if output.get("formula_id") != formula_id:
                error(
                    "REFERENCE_MISMATCH",
                    f"{all_ids[formula_id]}.output_id",
                    "formula.output_id and output.formula_id must point to each other",
                )
            formula_type = formula.get("formula_type") or formula.get("type")
            formula_metric = {
                "tco": "total_tco",
                "sum_costs": "total_tco",
                "total_benefit": "total_benefit",
                "sum_benefits": "total_benefit",
                "net_benefit": "net_benefit",
                "sum_net": "net_benefit",
                "roi": "roi",
                "npv": "npv",
            }.get(formula_type) if isinstance(formula_type, str) else None
            output_metric = OUTPUT_METRIC_ALIASES.get(
                str(output.get("metric", "")).strip().lower()
            )
            if (
                formula_metric is not None
                and output_metric is not None
                and formula_metric != output_metric
            ):
                error(
                    "REFERENCE_MISMATCH",
                    f"{all_ids[formula_id]}.output_id",
                    "formula type and output metric do not match",
                )
            if _present(formula.get("scenario_id")) and output.get(
                "scenario_id"
            ) != formula.get("scenario_id"):
                error(
                    "REFERENCE_MISMATCH",
                    f"{all_ids[formula_id]}.scenario_id",
                    "formula and output must reference the same scenario",
                )
    for scenario_id, scenario in id_maps["scenarios"].items():
        output_references = scenario.get("output")
        if isinstance(output_references, list):
            for ref_index, output_id in enumerate(output_references):
                if isinstance(output_id, str) and output_id in id_maps["outputs"]:
                    if id_maps["outputs"][output_id].get("scenario_id") != scenario_id:
                        error(
                            "REFERENCE_MISMATCH",
                            f"{all_ids[scenario_id]}.output[{ref_index}]",
                            "scenario output must reference an output for the same scenario",
                        )

    def cash_flow_values(
        rows: list[dict[str, Any]],
        path_prefix: str,
    ) -> tuple[list[tuple[dict[str, Any], Decimal, Decimal, Decimal]], bool]:
        validated: list[tuple[dict[str, Any], Decimal, Decimal, Decimal]] = []
        complete = True
        for index, row in enumerate(rows):
            path = f"{path_prefix}[{index}]"
            cost = _decimal_number(row.get("cost"))
            benefit = _decimal_number(row.get("benefit"))
            net = _decimal_number(row.get("net"))
            if cost is None or benefit is None or net is None:
                warn(
                    "UNVERIFIABLE_CALCULATION",
                    path,
                    "cost, benefit, and net must be finite numbers for arithmetic verification",
                )
                complete = False
                continue
            if cost < 0 or benefit < 0:
                error(
                    "INVALID_NUMBER",
                    path,
                    "cost and benefit must be non-negative finite values",
                )
            expected_net = benefit - cost
            if not _numbers_match(
                net,
                expected_net,
                absolute=amount_tolerance,
                relative=relative_tolerance,
            ):
                error(
                    "ARITHMETIC_MISMATCH",
                    f"{path}.net",
                    "declared net "
                    f"{_decimal_text(net)} does not equal benefit-cost "
                    f"{_decimal_text(expected_net)} within amount tolerance "
                    f"{_decimal_text(amount_tolerance)} and relative tolerance "
                    f"{_decimal_text(relative_tolerance)}",
                )
            validated.append((row, cost, benefit, net))
        return validated, complete and len(validated) == len(rows)

    global_cash_rows = [
        row
        for row in items_by_collection["cash_flows"]
        if isinstance(row, dict)
    ]
    seen_periods: set[tuple[str, str]] = set()
    for index, row in enumerate(global_cash_rows):
        scenario_key = str(row.get("scenario_id") or "__base__")
        period_key = json.dumps(row.get("period"), ensure_ascii=False, sort_keys=True)
        key = (scenario_key, period_key)
        if key in seen_periods:
            error(
                "DUPLICATE_PERIOD",
                f"quantitative_model.cash_flows[{index}].period",
                "cash-flow period is duplicated within the same scenario",
            )
        seen_periods.add(key)
    validated_global, global_complete = cash_flow_values(
        global_cash_rows, "quantitative_model.cash_flows"
    )

    assumption_numbers: dict[str, Decimal] = {}
    for item_id, assumption in id_maps["assumptions"].items():
        value = _decimal_number(assumption.get("value"))
        if value is not None:
            assumption_numbers[item_id] = value

    numeric_values: dict[str, Decimal] = dict(assumption_numbers)
    for item_id, item in id_maps["cost_items"].items():
        value = _decimal_number(item.get("amount"))
        if value is not None:
            numeric_values[item_id] = value
    for item_id, item in id_maps["benefit_items"].items():
        value = _decimal_number(item.get("value"))
        if value is None:
            value = _decimal_number(item.get("amount"))
        if value is not None:
            numeric_values[item_id] = value
    for item_id, item in id_maps["cash_flows"].items():
        value = _decimal_number(item.get("net"))
        if value is not None:
            numeric_values[item_id] = value

    formula_cache: dict[str, Decimal | None] = {}
    evaluating: set[str] = set()
    formula_warning_keys: set[tuple[str, str]] = set()

    def formula_warning(code: str, path: str, message: str) -> None:
        key = (code, path)
        if key not in formula_warning_keys:
            formula_warning_keys.add(key)
            warn(code, path, message)

    def discount_rate(rate_id: Any, path: str) -> Decimal | None:
        if not isinstance(rate_id, str) or rate_id not in assumption_numbers:
            formula_warning(
                "UNVERIFIABLE_FORMULA",
                path,
                "discount rate is missing or is not a finite numeric assumption",
            )
            return None
        rate = assumption_numbers[rate_id]
        unit = str(id_maps["assumptions"][rate_id].get("unit", "")).strip().lower()
        if unit in {"%", "percent", "percentage", "pct", "百分比"}:
            rate /= Decimal("100")
        elif unit not in {"ratio", "decimal", "fraction", "比率"}:
            formula_warning(
                "UNVERIFIABLE_FORMULA",
                path,
                "discount-rate unit must be ratio or percent",
            )
            return None
        if rate < 0 or rate >= 1:
            error("INVALID_DISCOUNT_RATE", path, "discount rate must satisfy 0 <= rate < 1")
            return None
        return rate

    def period_index(row: dict[str, Any], path: str) -> int | None:
        raw = row.get("period_index")
        source_field = "period_index"
        if raw is None:
            raw = row.get("period")
            source_field = "period"
        value = _decimal_number(raw)
        if value is None or value != value.to_integral_value() or value < 0:
            formula_warning(
                "UNVERIFIABLE_FORMULA",
                f"{path}.{source_field}",
                "NPV requires period_index or period as a non-negative integer",
            )
            return None
        horizon = _decimal_number(quantitative.get("horizon_years"))
        if (
            horizon is not None
            and horizon == horizon.to_integral_value()
            and int(value) > int(horizon)
        ):
            error(
                "INVALID_PERIOD",
                f"{path}.{source_field}",
                "cash-flow period exceeds quantitative_model.horizon_years",
            )
            return None
        return int(value)

    def npv_from_rows(
        rows: list[dict[str, Any]],
        rate_id: Any,
        path: str,
    ) -> Decimal | None:
        rate = discount_rate(rate_id, f"{path}.discount_rate_assumption_id")
        if rate is None:
            return None
        total = Decimal("0")
        for index, row in enumerate(rows):
            net = _decimal_number(row.get("net"))
            exponent = period_index(row, f"{path}.cash_flows[{index}]")
            if net is None or exponent is None:
                return None
            total += net / ((Decimal("1") + rate) ** exponent)
        return total

    def resolve_numeric(reference: str, formula_path: str) -> Decimal | None:
        if reference in numeric_values:
            return numeric_values[reference]
        if reference in id_maps["formulas"]:
            return evaluate_formula(reference)
        formula_warning(
            "UNVERIFIABLE_FORMULA",
            formula_path,
            f"input {reference} exists but has no finite numeric value",
        )
        return None

    def evaluate_formula(formula_id: str) -> Decimal | None:
        if formula_id in formula_cache:
            return formula_cache[formula_id]
        formula = id_maps["formulas"].get(formula_id)
        if formula is None:
            return None
        formula_index = items_by_collection["formulas"].index(formula)
        path = f"quantitative_model.formulas[{formula_index}]"
        if formula_id in evaluating:
            error("CIRCULAR_REFERENCE", f"{path}.input_ids", "formula dependency cycle detected")
            formula_cache[formula_id] = None
            return None
        evaluating.add(formula_id)
        formula_type = formula.get("formula_type") or formula.get("type")
        input_ids = formula.get("input_ids")
        result: Decimal | None = None
        if not isinstance(formula_type, str):
            formula_warning(
                "UNVERIFIABLE_FORMULA",
                f"{path}.formula_type",
                "formula type is not a string and was not executed",
            )
        elif formula_type == "custom" or formula_type not in SUPPORTED_FORMULA_TYPES:
            formula_warning(
                "UNVERIFIABLE_FORMULA",
                path,
                "custom formula is documented but was not executed",
            )
        elif not isinstance(input_ids, list):
            formula_warning(
                "UNVERIFIABLE_FORMULA",
                f"{path}.input_ids",
                "formula inputs are not a list",
            )
        elif formula_type == "npv":
            rows = [
                id_maps["cash_flows"][reference]
                for reference in input_ids
                if isinstance(reference, str) and reference in id_maps["cash_flows"]
            ]
            if len(rows) != len(input_ids):
                formula_warning(
                    "UNVERIFIABLE_FORMULA",
                    f"{path}.input_ids",
                    "NPV inputs must all reference cash-flow rows",
                )
            else:
                rate_id = formula.get("discount_rate_assumption_id") or quantitative.get(
                    "discount_rate_assumption_id"
                )
                result = npv_from_rows(rows, rate_id, path)
        elif formula_type == "roi" and input_ids and all(
            isinstance(reference, str) and reference in id_maps["cash_flows"]
            for reference in input_ids
        ):
            rows = [id_maps["cash_flows"][reference] for reference in input_ids]
            costs = [_decimal_number(row.get("cost")) for row in rows]
            benefits = [_decimal_number(row.get("benefit")) for row in rows]
            if any(value is None for value in costs + benefits):
                formula_warning(
                    "UNVERIFIABLE_FORMULA",
                    f"{path}.input_ids",
                    "ROI cash-flow inputs must contain finite cost and benefit values",
                )
            else:
                total_cost = sum((value for value in costs if value is not None), Decimal("0"))
                total_benefit = sum(
                    (value for value in benefits if value is not None), Decimal("0")
                )
                if total_cost == 0:
                    formula_warning(
                        "ZERO_DENOMINATOR",
                        path,
                        "ROI is undefined because total cost is zero",
                    )
                else:
                    result = (total_benefit - total_cost) / total_cost
        elif formula_type in {
            "tco",
            "total_benefit",
            "net_benefit",
            "sum_costs",
            "sum_benefits",
            "sum_net",
        }:
            values: list[Decimal] = []
            field = {
                "tco": "cost",
                "total_benefit": "benefit",
                "net_benefit": "net",
                "sum_costs": "cost",
                "sum_benefits": "benefit",
                "sum_net": "net",
            }[formula_type]
            for reference in input_ids:
                value: Decimal | None = None
                if isinstance(reference, str) and reference in id_maps["cash_flows"]:
                    value = _decimal_number(id_maps["cash_flows"][reference].get(field))
                elif (
                    formula_type in {"tco", "sum_costs"}
                    and isinstance(reference, str)
                    and reference in id_maps["cost_items"]
                ):
                    value = _decimal_number(id_maps["cost_items"][reference].get("amount"))
                elif (
                    formula_type in {"total_benefit", "sum_benefits"}
                    and isinstance(reference, str)
                    and reference in id_maps["benefit_items"]
                ):
                    value = _decimal_number(
                        id_maps["benefit_items"][reference].get("value")
                    )
                    if value is None:
                        value = _decimal_number(
                            id_maps["benefit_items"][reference].get("amount")
                        )
                if value is None:
                    formula_warning(
                        "UNVERIFIABLE_FORMULA",
                        f"{path}.input_ids",
                        f"input {reference} has no numeric {field}",
                    )
                    values = []
                    break
                values.append(value)
            if len(values) == len(input_ids):
                result = sum(values, Decimal("0"))
        else:
            values = []
            for reference in input_ids:
                if not isinstance(reference, str):
                    values = []
                    break
                value = resolve_numeric(reference, f"{path}.input_ids")
                if value is None:
                    values = []
                    break
                values.append(value)
            if len(values) == len(input_ids):
                if formula_type == "sum":
                    result = sum(values, Decimal("0"))
                elif formula_type == "difference" and values:
                    result = values[0] - sum(values[1:], Decimal("0"))
                elif formula_type == "product":
                    result = Decimal("1")
                    for value in values:
                        result *= value
                elif formula_type in {"ratio", "roi"} and len(values) == 2:
                    denominator = values[1]
                    if denominator == 0:
                        formula_warning(
                            "UNVERIFIABLE_FORMULA",
                            path,
                            "division by zero prevents formula verification",
                        )
                        result = None
                    elif formula_type == "ratio":
                        result = values[0] / denominator
                    else:
                        result = (values[0] - denominator) / denominator
                else:
                    formula_warning(
                        "UNVERIFIABLE_FORMULA",
                        path,
                        "formula type and input count do not form a supported calculation",
                    )
        evaluating.discard(formula_id)
        formula_cache[formula_id] = result
        if result is not None:
            numeric_values[formula_id] = result
            declared = _decimal_number(formula.get("result"))
            if declared is None:
                declared = _decimal_number(formula.get("value"))
            if declared is not None:
                absolute = ratio_tolerance if formula_type in {"ratio", "roi"} else amount_tolerance
                if not _numbers_match(
                    declared,
                    result,
                    absolute=absolute,
                    relative=relative_tolerance,
                ):
                    error(
                        "ARITHMETIC_MISMATCH",
                        f"{path}.result",
                        f"declared value {_decimal_text(declared)} does not match recomputed "
                        f"{_decimal_text(result)}",
                    )
        return result

    for formula_id in formula_ids:
        evaluate_formula(formula_id)

    def direct_metrics(rows: list[dict[str, Any]], path: str) -> dict[str, Decimal]:
        validated, complete = cash_flow_values(rows, path)
        if not complete or not rows:
            return {}
        total_cost = sum((cost for _, cost, _, _ in validated), Decimal("0"))
        total_benefit = sum(
            (benefit for _, _, benefit, _ in validated), Decimal("0")
        )
        metrics = {
            "total_tco": total_cost,
            "total_benefit": total_benefit,
            "net_benefit": total_benefit - total_cost,
        }
        if total_cost != 0:
            metrics["roi"] = (total_benefit - total_cost) / total_cost
        return metrics

    base_rows = [row for row in global_cash_rows if not _present(row.get("scenario_id"))]
    base_metrics = direct_metrics(base_rows, "quantitative_model.base_cash_flows")
    rate_id = quantitative.get("discount_rate_assumption_id")
    if base_rows and _present(rate_id):
        base_npv = npv_from_rows(base_rows, rate_id, "quantitative_model")
        if base_npv is not None:
            base_metrics["npv"] = base_npv

    def select_scenario_rows(scenario_id: str, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        embedded = scenario.get("cash_flows")
        if isinstance(embedded, list) and all(isinstance(row, dict) for row in embedded):
            return embedded
        references = scenario.get("cash_flow_ids")
        if isinstance(references, list):
            return [
                id_maps["cash_flows"][reference]
                for reference in references
                if isinstance(reference, str) and reference in id_maps["cash_flows"]
            ]
        return [
            row for row in global_cash_rows if row.get("scenario_id") == scenario_id
        ]

    def scenario_metrics_for(
        scenario_id: str,
        scenario: dict[str, Any],
        path: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Decimal]]:
        rows = select_scenario_rows(scenario_id, scenario)
        metrics = direct_metrics(rows, f"{path}.cash_flows")
        scenario_rate_id = scenario.get("discount_rate_assumption_id") or rate_id
        if rows and _present(scenario_rate_id):
            scenario_npv = npv_from_rows(rows, scenario_rate_id, path)
            if scenario_npv is not None:
                metrics["npv"] = scenario_npv
        return rows, metrics

    def validate_claim(
        claim: dict[str, Any],
        path: str,
        metrics: dict[str, Decimal],
    ) -> None:
        metric_raw = str(claim.get("metric", "")).strip().lower()
        metric = OUTPUT_METRIC_ALIASES.get(metric_raw)
        unit = str(claim.get("unit", "")).strip()
        currency = str(quantitative.get("currency", "")).strip()
        if metric in {"total_tco", "total_benefit", "net_benefit", "npv"}:
            if not unit:
                warn("UNIT", f"{path}.unit", "monetary output should declare its currency")
            elif currency and unit.lower() != currency.lower():
                error(
                    "UNIT",
                    f"{path}.unit",
                    "monetary output unit must match quantitative_model.currency",
                )
        elif metric == "roi" and unit.lower() not in {
            "ratio",
            "decimal",
            "fraction",
            "%",
            "percent",
            "percentage",
            "pct",
            "百分比",
        }:
            warn("UNIT", f"{path}.unit", "ROI should declare ratio or percent units")
        declared = _decimal_number(claim.get("value"))
        if declared is None:
            error("INVALID_NUMBER", f"{path}.value", "must be a finite number")
            return
        expected: Decimal | None = None
        formula_id = claim.get("formula_id")
        if isinstance(formula_id, str) and formula_id in formula_ids:
            expected = evaluate_formula(formula_id)
        direct = metrics.get(metric) if metric else None
        if expected is not None and direct is not None and not _numbers_match(
            expected,
            direct,
            absolute=ratio_tolerance if metric == "roi" else amount_tolerance,
            relative=relative_tolerance,
        ):
            error(
                "ARITHMETIC_MISMATCH",
                f"{path}.formula_id",
                "formula result does not match the independently recomputed cash-flow metric",
            )
        if direct is not None:
            expected = direct
        if expected is None:
            warn(
                "UNVERIFIABLE_CALCULATION",
                path,
                "claim has no safely computable supported formula or cash-flow metric",
            )
            return
        is_percentage = metric == "roi" and unit.lower() in {
            "%",
            "percent",
            "percentage",
            "pct",
            "百分比",
        }
        if is_percentage:
            expected *= Decimal("100")
        absolute = (
            percentage_tolerance
            if is_percentage
            else ratio_tolerance
            if metric == "roi"
            else amount_tolerance
        )
        if not _numbers_match(
            declared,
            expected,
            absolute=absolute,
            relative=relative_tolerance,
        ):
            error(
                "ARITHMETIC_MISMATCH",
                f"{path}.value",
                f"declared {_decimal_text(declared)} does not match recomputed "
                f"{_decimal_text(expected)} within absolute tolerance "
                f"{_decimal_text(absolute)} and relative tolerance "
                f"{_decimal_text(relative_tolerance)}",
            )

    for output_id, output in id_maps["outputs"].items():
        index = items_by_collection["outputs"].index(output)
        output_path = f"quantitative_model.outputs[{index}]"
        metrics = base_metrics
        scenario_id = output.get("scenario_id")
        if isinstance(scenario_id, str) and scenario_id in id_maps["scenarios"]:
            _, metrics = scenario_metrics_for(
                scenario_id,
                id_maps["scenarios"][scenario_id],
                output_path,
            )
        validate_claim(output, output_path, metrics)

    for scenario_id, scenario in id_maps["scenarios"].items():
        index = items_by_collection["scenarios"].index(scenario)
        path = f"quantitative_model.scenarios[{index}]"
        embedded = scenario.get("cash_flows")
        if embedded is not None:
            if not isinstance(embedded, list) or not all(
                isinstance(row, dict) for row in embedded
            ):
                error("TYPE", f"{path}.cash_flows", "must be a list of JSON objects")
        scenario_rows, scenario_metrics = scenario_metrics_for(
            scenario_id, scenario, path
        )
        output = scenario.get("output")
        if isinstance(output, list):
            for ref_index, output_id in enumerate(output):
                if isinstance(output_id, str) and output_id in id_maps["outputs"]:
                    validate_claim(
                        id_maps["outputs"][output_id],
                        f"{path}.output[{ref_index}]",
                        scenario_metrics,
                    )
            continue
        if not isinstance(output, dict):
            warn(
                "UNVERIFIABLE_SCENARIO_OUTPUT",
                f"{path}.output",
                "scenario output must be a metric dictionary for arithmetic verification",
            )
            continue
        if "metric" in output or "value" in output:
            exact_reference(
                output.get("formula_id"),
                formula_ids,
                f"{path}.output.formula_id",
                "formula",
            )
            validate_claim(output, f"{path}.output", scenario_metrics)
            continue
        recognized = False
        for raw_metric, raw_claim in output.items():
            metric = OUTPUT_METRIC_ALIASES.get(str(raw_metric).lower())
            if metric is None:
                continue
            recognized = True
            claim = (
                deepcopy(raw_claim)
                if isinstance(raw_claim, dict)
                else {"value": raw_claim}
            )
            claim.setdefault("metric", metric)
            claim.setdefault(
                "unit",
                "ratio" if metric == "roi" else quantitative.get("currency", ""),
            )
            exact_reference(
                claim.get("formula_id"),
                formula_ids,
                f"{path}.output.{raw_metric}.formula_id",
                "formula",
            )
            validate_claim(claim, f"{path}.output.{raw_metric}", scenario_metrics)
        if not recognized:
            warn(
                "UNVERIFIABLE_SCENARIO_OUTPUT",
                f"{path}.output",
                "scenario output contains no supported total_tco, total_benefit, roi, or npv claim",
            )


def validate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Validate schema and mode-specific decision readiness.

    Schema violations are errors. Missing decision inputs are warnings so a
    draft remains editable, but any warning makes ``ready`` false.
    """

    issues: list[dict[str, str]] = []

    def add(severity: str, code: str, path: str, message: str) -> None:
        issues.append(
            {"severity": severity, "code": code, "path": path, "message": message}
        )

    def error(code: str, path: str, message: str) -> None:
        add("error", code, path, message)

    def warn(code: str, path: str, message: str) -> None:
        add("warning", code, path, message)

    if not isinstance(state, dict):
        error("TYPE", "$", "blackboard root must be a JSON object")
        return _validation_report(issues, None)

    sections: dict[str, dict[str, Any]] = {}
    for section in TOP_LEVEL_SECTIONS:
        value = state.get(section)
        if not isinstance(value, dict):
            error("SECTION_TYPE", section, "must be a JSON object")
        else:
            sections[section] = value
    if len(sections) != len(TOP_LEVEL_SECTIONS):
        return _validation_report(issues, None)
    for section in sorted(set(state) - set(TOP_LEVEL_SECTIONS)):
        warn(
            "UNKNOWN_TOP_LEVEL",
            section,
            "is not part of the canonical schema-v2 blackboard",
        )

    metadata = sections["metadata"]
    alignment = sections["alignment"]
    evidence = sections["evidence"]
    logic_mesh = sections["logic_mesh"]
    decisions = sections["decisions"]
    quantitative = sections["quantitative_model"]
    roadmap = sections["roadmap"]
    compliance = sections["compliance_context"]
    portfolio = sections["portfolio"]
    for legacy_field in ("quantitative_model", "roadmap"):
        if legacy_field in decisions:
            warn(
                "DUPLICATE_LEGACY_FIELD",
                f"decisions.{legacy_field}",
                f"use the top-level {legacy_field} section only",
            )
    if "mode" in alignment:
        warn(
            "DUPLICATE_LEGACY_FIELD",
            "alignment.mode",
            "metadata.mode is the sole canonical mode field",
        )

    if metadata.get("schema_version") != SCHEMA_VERSION:
        error("SCHEMA_VERSION", "metadata.schema_version", f"must equal {SCHEMA_VERSION}")
    revision = metadata.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        error("REVISION", "metadata.revision", "must be a non-negative integer")
    mode = metadata.get("mode")
    if mode not in MODES:
        error("MODE", "metadata.mode", f"must be one of: {', '.join(MODES)}")
        mode = None
    if not _present(metadata.get("topic")):
        warn("MISSING_INPUT", "metadata.topic", "topic is not filled")
    maturity = metadata.get("maturity")
    if maturity not in MATURITY_LEVELS:
        error(
            "MATURITY",
            "metadata.maturity",
            "must be one of: " + ", ".join(MATURITY_LEVELS),
        )
    approval = metadata.get("approval")
    if not isinstance(approval, dict):
        error("TYPE", "metadata.approval", "must be a JSON object")
        approval = {}
    if maturity == "approved_for_execution":
        for field in ("authority", "authority_role", "decision", "as_of", "source"):
            if not _present(approval.get(field)):
                error(
                    "EXTERNAL_APPROVAL_REQUIRED",
                    f"metadata.approval.{field}",
                    "is required to record an external authorized approval",
                )

    for key in ("questions_to_decide", "audience", "success_metrics", "constraints", "unacceptable_risks"):
        if not isinstance(alignment.get(key), list):
            error("TYPE", f"alignment.{key}", "must be a list")
    for key in ("organization", "time_horizon", "budget"):
        if not isinstance(alignment.get(key), dict):
            error("TYPE", f"alignment.{key}", "must be a JSON object")

    records = evidence.get("records")
    if not isinstance(records, list):
        error("TYPE", "evidence.records", "must be a list")
        records = []
    for key in ("gaps", "conflicts"):
        if not isinstance(evidence.get(key), list):
            error("TYPE", f"evidence.{key}", "must be a list")
    record_ids: set[str] = set()
    for index, record in enumerate(records):
        path = f"evidence.records[{index}]"
        if not isinstance(record, dict):
            error("TYPE", path, "must be a JSON object")
            continue
        legacy_id = record.get("id") if "evidence_id" not in record else None
        record_id = str(record.get("evidence_id") or legacy_id or "").strip()
        if not record_id:
            error("REQUIRED", f"{path}.evidence_id", "is required")
        elif record_id in record_ids:
            error(
                "DUPLICATE_ID",
                f"{path}.evidence_id",
                f"duplicate evidence id: {record_id}",
            )
        else:
            record_ids.add(record_id)
        if legacy_id is not None:
            warn(
                "LEGACY_FIELD",
                f"{path}.id",
                "migrate id to the canonical evidence_id field",
            )
        elif record_id and not EVIDENCE_ID_RE.fullmatch(record_id):
            error(
                "EVIDENCE_ID",
                f"{path}.evidence_id",
                "must match EV-<three-letter-domain>-<three-digit-sequence>",
            )
        missing_evidence_fields = sorted(EVIDENCE_FIELDS - set(record))
        if legacy_id is not None:
            missing_evidence_fields = [
                field for field in missing_evidence_fields if field != "evidence_id"
            ]
        if missing_evidence_fields:
            error(
                "REQUIRED",
                path,
                "missing canonical fields: " + ", ".join(missing_evidence_fields),
            )
        if not _present(record.get("claim")):
            error("REQUIRED", f"{path}.claim", "is required")
        record_type = record.get("record_type")
        if record_type not in EVIDENCE_RECORD_TYPES:
            error(
                "RECORD_TYPE",
                f"{path}.record_type",
                "must be verified_fact or source_claim",
            )
        source_type = record.get("source_type")
        if source_type not in EVIDENCE_SOURCE_TYPES:
            error(
                "SOURCE_TYPE",
                f"{path}.source_type",
                "must be primary, secondary, or user_material",
            )
        if not _present(record.get("locator")):
            error(
                "PROVENANCE",
                f"{path}.locator",
                "must identify an original URL or file plus page, table, sheet, or field",
            )
        if source_type in {"primary", "secondary"}:
            for field in ("source_title", "publisher", "accessed_at"):
                if not _present(record.get(field)):
                    error(
                        "PROVENANCE",
                        f"{path}.{field}",
                        "is required for an external source",
                    )
        strength = record.get("strength")
        if strength not in EVIDENCE_STRENGTHS:
            error(
                "STRENGTH",
                f"{path}.strength",
                "must be high, medium, or low",
            )
        status = record.get("status")
        if status not in EVIDENCE_STATUSES:
            error(
                "STATUS",
                f"{path}.status",
                "must be active, disputed, or superseded",
            )
        elif status == "superseded" and not _present(record.get("supersedes")):
            error(
                "SUPERSESSION",
                f"{path}.supersedes",
                "must identify the prior evidence record",
            )
        elif status == "disputed" and not _present(record.get("limitations")):
            error(
                "DISPUTE_CONTEXT",
                f"{path}.limitations",
                "must explain why the evidence is disputed",
            )

    for key in ("alternatives", "conflicts", "counter_evidence"):
        if not isinstance(logic_mesh.get(key), list):
            error("TYPE", f"logic_mesh.{key}", "must be a list")
    for key in ("action_levers", "management_decisions", "residual_risks"):
        if not isinstance(decisions.get(key), list):
            error("TYPE", f"decisions.{key}", "must be a list")

    applicable = quantitative.get("applicable")
    if applicable not in (True, False, None):
        error("TYPE", "quantitative_model.applicable", "must be true, false, or null")
    for key in (
        "assumptions",
        "cost_items",
        "benefit_items",
        "cash_flows",
        "formulas",
        "scenarios",
        "sensitivity",
        "outputs",
    ):
        if not isinstance(quantitative.get(key), list):
            error("TYPE", f"quantitative_model.{key}", "must be a list")
    for key in ("baseline", "counterfactual"):
        if not isinstance(quantitative.get(key), dict):
            error("TYPE", f"quantitative_model.{key}", "must be a JSON object")

    assumptions = quantitative.get("assumptions")
    if isinstance(assumptions, list):
        for index, assumption in enumerate(assumptions):
            path = f"quantitative_model.assumptions[{index}]"
            if not isinstance(assumption, dict):
                error("TYPE", path, "must be a JSON object")
                continue
            missing = sorted(ASSUMPTION_FIELDS - set(assumption))
            if missing:
                error("REQUIRED", path, "missing fields: " + ", ".join(missing))
                continue
            status = assumption.get("status")
            if status not in RECORD_STATUSES:
                error(
                    "STATUS",
                    f"{path}.status",
                    "must be one of: " + ", ".join(sorted(RECORD_STATUSES)),
                )
                continue
            if status in LEGACY_RECORD_STATUSES:
                warn(
                    "LEGACY_STATUS",
                    f"{path}.status",
                    "use externally_verified instead of the legacy status",
                )
            if status == "needs_input":
                if assumption.get("value") not in (None, ""):
                    error("VALUE", f"{path}.value", "must be null when status=needs_input")
                continue
            if status == "not_applicable":
                continue
            if assumption.get("value") in (None, ""):
                error("VALUE", f"{path}.value", "is required for this status")
            if not _present(assumption.get("unit")):
                error("UNIT", f"{path}.unit", "is required for this status")
            if status in {"externally_verified", "sourced", "verified"}:
                if not _source_present(assumption.get("source")):
                    error("PROVENANCE", f"{path}.source", "is required")
                for field in ("as_of", "region"):
                    if not _present(assumption.get(field)):
                        error("PROVENANCE", f"{path}.{field}", "is required")
            elif status == "client_provided" and not _source_present(
                assumption.get("source")
            ):
                error("PROVENANCE", f"{path}.source", "must identify the client material")
            elif status == "calculated" and not _present(assumption.get("formula")):
                error("FORMULA", f"{path}.formula", "is required when status=calculated")
            elif status in {"scenario_assumption", "analyst_judgment"} and not _present(
                assumption.get("rationale")
            ):
                error("RATIONALE", f"{path}.rationale", "is required for this status")

    phases = roadmap.get("phases")
    if not isinstance(phases, list):
        error("TYPE", "roadmap.phases", "must be a list")
        phases = []
    if not isinstance(roadmap.get("dependencies"), list):
        error("TYPE", "roadmap.dependencies", "must be a list")
    if not isinstance(roadmap.get("governance"), dict):
        error("TYPE", "roadmap.governance", "must be a JSON object")
    for index, phase in enumerate(phases):
        path = f"roadmap.phases[{index}]"
        if not isinstance(phase, dict):
            error("TYPE", path, "must be a JSON object")
            continue
        for field in ("id", "name", "timeframe", "owner"):
            if not _present(phase.get(field)):
                error("REQUIRED", f"{path}.{field}", "is required")
        for field in ("outcomes", "exit_criteria", "dependencies"):
            if not isinstance(phase.get(field), list):
                error("TYPE", f"{path}.{field}", "must be a list")

    compliance_applicability = compliance.get("applicability")
    if compliance_applicability not in {"undetermined", "required", "not_applicable"}:
        error(
            "STATUS",
            "compliance_context.applicability",
            "must be undetermined, required, or not_applicable",
        )
    for key in ("data_types", "affected_users", "escalations"):
        if not isinstance(compliance.get(key), list):
            error("TYPE", f"compliance_context.{key}", "must be a list")
    review_required = compliance.get("review_required")
    if review_required not in (True, False, None) and not isinstance(
        review_required, list
    ):
        error(
            "TYPE",
            "compliance_context.review_required",
            "must be true, false, null, or a list of required review records",
        )
    if compliance.get("status") not in {
        "not_reviewed",
        "review_required",
        "under_review",
        "reviewed",
        "professionally_reviewed",
        "blocked",
    }:
        error(
            "STATUS",
            "compliance_context.status",
            "must be not_reviewed, review_required, under_review, reviewed, professionally_reviewed, or blocked",
        )

    portfolio_applicable = portfolio.get("applicable")
    if portfolio_applicable not in (True, False, None):
        error("TYPE", "portfolio.applicable", "must be true, false, or null")
    for key in (
        "candidates",
        "scoring_criteria",
        "prioritization",
        "gate_results",
        "capacity_constraints",
        "dependencies",
    ):
        if not isinstance(portfolio.get(key), list):
            error("TYPE", f"portfolio.{key}", "must be a list")

    # Readiness shared by every mode.
    if not _present(alignment.get("decision")):
        warn("MISSING_INPUT", "alignment.decision", "decision to be made is not filled")
    if not _present(alignment.get("audience")):
        warn("MISSING_INPUT", "alignment.audience", "decision audience is not filled")
    if not _meaningful_horizon(alignment.get("time_horizon")):
        warn("MISSING_INPUT", "alignment.time_horizon", "time horizon is not filled")
    if not _present(alignment.get("success_metrics")):
        warn("MISSING_INPUT", "alignment.success_metrics", "success metrics are not filled")

    usable_records = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("status") == "active"
    ]
    if not usable_records:
        warn("MISSING_EVIDENCE", "evidence.records", "no usable evidence record is present")
    if not _present(logic_mesh.get("core_judgment")):
        warn("MISSING_JUDGMENT", "logic_mesh.core_judgment", "core judgment is not filled")
    if not _present(decisions.get("recommendation")):
        warn("MISSING_DECISION", "decisions.recommendation", "recommendation is not filled")
    if not _present(decisions.get("residual_risks")):
        warn("MISSING_RISK", "decisions.residual_risks", "residual risks are not filled")

    if compliance_applicability == "undetermined":
        warn(
            "COMPLIANCE_UNDECIDED",
            "compliance_context.applicability",
            "determine whether compliance review is required",
        )
    elif compliance_applicability == "not_applicable":
        if not _present(compliance.get("rationale")):
            warn(
                "MISSING_RATIONALE",
                "compliance_context.rationale",
                "explain why compliance review is not applicable",
            )
    elif compliance_applicability == "required":
        for field in ("jurisdiction", "as_of", "intended_use"):
            if not _present(compliance.get(field)):
                warn(
                    "MISSING_COMPLIANCE_CONTEXT",
                    f"compliance_context.{field}",
                    "is required when compliance review is required",
                )
        for field in ("data_types", "affected_users"):
            if not _present(compliance.get(field)):
                warn(
                    "MISSING_COMPLIANCE_CONTEXT",
                    f"compliance_context.{field}",
                    "must identify the affected scope",
                )
        if review_required is None:
            warn(
                "COMPLIANCE_REVIEW_UNDECIDED",
                "compliance_context.review_required",
                "determine whether an authorized compliance review is required",
            )
        elif review_required is True and not _present(compliance.get("escalations")):
            warn(
                "MISSING_ESCALATION",
                "compliance_context.escalations",
                "identify the required legal, privacy, security, clinical, or ethics review",
            )
        if review_required is True or (
            isinstance(review_required, list) and bool(review_required)
        ):
            if compliance.get("status") in {
                "not_reviewed",
                "review_required",
                "under_review",
            }:
                warn(
                    "COMPLIANCE_REVIEW_OPEN",
                    "compliance_context.status",
                    "required compliance review is not complete",
                )

    review_records: list[Any] = []
    if isinstance(review_required, list):
        review_records.extend(review_required)
    if isinstance(compliance.get("escalations"), list):
        review_records.extend(compliance["escalations"])
    for index, review in enumerate(review_records):
        path = f"compliance_context.review_records[{index}]"
        if not isinstance(review, dict):
            error("TYPE", path, "must be a JSON object")
            continue
        if not (_present(review.get("role")) or _present(review.get("reviewer"))):
            error(
                "REVIEWER",
                path,
                "must name a reviewer or authorized review role",
            )
        if not _present(review.get("as_of")):
            error("REVIEW_DATE", f"{path}.as_of", "is required")
        if review.get("status") not in {
            "required",
            "pending",
            "in_progress",
            "completed",
            "accepted",
            "rejected",
        }:
            error(
                "REVIEW_STATUS",
                f"{path}.status",
                "must be required, pending, in_progress, completed, accepted, or rejected",
            )

    if maturity in {"decision_ready", "approved_for_execution"} and (
        compliance_applicability == "required"
    ):
        required_records = review_records if review_required is not False else []
        if review_required is True and not required_records:
            warn(
                "MISSING_PROFESSIONAL_REVIEW",
                "compliance_context.escalations",
                "decision-ready work must record every required professional review",
            )
        for index, review in enumerate(required_records):
            if isinstance(review, dict) and review.get("status") not in {
                "completed",
                "accepted",
            }:
                warn(
                    "INCOMPLETE_PROFESSIONAL_REVIEW",
                    f"compliance_context.review_records[{index}].status",
                    "decision-ready work requires completed or accepted review status",
                )
        if review_required is not False and compliance.get("status") not in {
            "reviewed",
            "professionally_reviewed",
        }:
            warn(
                "COMPLIANCE_NOT_REVIEWED",
                "compliance_context.status",
                "decision-ready work requires a recorded professional review outcome",
            )

    # The skill may record an authorized approval, but never infers or promotes
    # maturity automatically. The ready command represents decision readiness.
    if maturity in {"working_draft", "review_ready"}:
        warn(
            "MATURITY_NOT_READY",
            "metadata.maturity",
            "set decision_ready only after an explicit human review of the completed evidence",
        )
    elif maturity == "blocked":
        warn(
            "MATURITY_BLOCKED",
            "metadata.maturity",
            "the recorded outcome is blocked",
        )

    if applicable is False and not _present(quantitative.get("not_applicable_reason")):
        warn(
            "MISSING_RATIONALE",
            "quantitative_model.not_applicable_reason",
            "explain why a quantitative model is not applicable",
        )
    if applicable is True:
        if not _present(quantitative.get("assumptions")):
            warn(
                "MISSING_MODEL_INPUT",
                "quantitative_model.assumptions",
                "at least one explicit assumption is required",
            )
        if not _present(quantitative.get("formulas")):
            warn(
                "MISSING_MODEL_LOGIC",
                "quantitative_model.formulas",
                "calculation formulas are not documented",
            )

    if portfolio_applicable is False and not _present(portfolio.get("not_applicable_reason")):
        warn(
            "MISSING_RATIONALE",
            "portfolio.not_applicable_reason",
            "explain why portfolio prioritization is not applicable",
        )
    if portfolio_applicable is True:
        for field in ("candidates", "scoring_criteria", "prioritization"):
            if not _present(portfolio.get(field)):
                warn(
                    "MISSING_PORTFOLIO_INPUT",
                    f"portfolio.{field}",
                    "is required for portfolio prioritization",
                )

    # Mode-specific readiness gates.
    if mode in {"board-memo", "deep-dive", "investment-case"}:
        organization = alignment.get("organization", {})
        if isinstance(organization, dict):
            for field in ("name", "type", "region"):
                if not _present(organization.get(field)):
                    warn(
                        "MISSING_ALIGNMENT",
                        f"alignment.organization.{field}",
                        "is required for this mode",
                    )
        if not _present(alignment.get("questions_to_decide")):
            warn(
                "MISSING_ALIGNMENT",
                "alignment.questions_to_decide",
                "management questions are not filled",
            )
        if not _present(alignment.get("constraints")):
            warn("MISSING_ALIGNMENT", "alignment.constraints", "constraints are not filled")
        if not _present(decisions.get("action_levers")):
            warn("MISSING_ACTION", "decisions.action_levers", "action levers are not filled")
        if not _present(decisions.get("management_decisions")):
            warn(
                "MISSING_DECISION",
                "decisions.management_decisions",
                "items requiring management approval are not filled",
            )
        if not phases:
            warn("MISSING_ROADMAP", "roadmap.phases", "at least one roadmap phase is required")
        if applicable is None:
            warn(
                "MODEL_UNDECIDED",
                "quantitative_model.applicable",
                "decide whether quantitative analysis is applicable",
            )

    if mode in {"deep-dive", "investment-case"}:
        if len(logic_mesh.get("alternatives", [])) < 2:
            warn(
                "MISSING_ALTERNATIVES",
                "logic_mesh.alternatives",
                "at least two options are required for comparison",
            )
        if not _present(logic_mesh.get("counter_evidence")):
            warn(
                "MISSING_RED_TEAM",
                "logic_mesh.counter_evidence",
                "counter-evidence or falsification result is not filled",
            )
        if not any(
            isinstance(record, dict)
            and record.get("status") == "active"
            and record.get("source_type") in EVIDENCE_SOURCE_TYPES
            and _present(record.get("locator"))
            for record in records
        ):
            warn(
                "MISSING_PROVENANCE",
                "evidence.records",
                "deep analysis needs at least one traceable source record",
            )
        governance = roadmap.get("governance", {})
        if isinstance(governance, dict):
            for field in ("executive_sponsor", "accountable_owner", "decision_forum"):
                if not _present(governance.get(field)):
                    warn(
                        "MISSING_GOVERNANCE",
                        f"roadmap.governance.{field}",
                        "is required for this mode",
                    )
        for index, phase in enumerate(phases):
            if isinstance(phase, dict) and not _present(phase.get("exit_criteria")):
                warn(
                    "MISSING_EXIT_GATE",
                    f"roadmap.phases[{index}].exit_criteria",
                    "at least one measurable exit criterion is required",
                )
        if applicable is True:
            for field in ("scenarios", "sensitivity", "outputs"):
                if not _present(quantitative.get(field)):
                    warn(
                        "MISSING_MODEL_OUTPUT",
                        f"quantitative_model.{field}",
                        "is required for a deep quantitative analysis",
                    )

    if mode == "investment-case":
        budget = alignment.get("budget", {})
        if not isinstance(budget, dict) or budget.get("status") == "needs_input":
            warn(
                "MISSING_BUDGET",
                "alignment.budget",
                "an investment case requires a sourced or explicitly assumed budget boundary",
            )
        elif budget.get("status") not in RECORD_STATUSES:
            error(
                "STATUS",
                "alignment.budget.status",
                "must use a supported evidence status",
            )
        if applicable is not True:
            warn(
                "MODEL_REQUIRED",
                "quantitative_model.applicable",
                "investment-case mode requires a quantitative model",
            )
        else:
            for field in (
                "model_type",
                "currency",
                "horizon_years",
                "baseline",
                "counterfactual",
                "cost_items",
                "benefit_items",
                "cash_flows",
            ):
                if not _present(quantitative.get(field)):
                    warn(
                        "MISSING_INVESTMENT_MODEL",
                        f"quantitative_model.{field}",
                        "is required for investment-case mode",
                    )
            scenarios = quantitative.get("scenarios", [])
            if isinstance(scenarios, list) and len(scenarios) < 2:
                warn(
                    "MISSING_SCENARIOS",
                    "quantitative_model.scenarios",
                    "at least base and downside scenarios are required",
                )
            investment_shapes: tuple[
                tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...
            ] = (
                (
                    "cost_items",
                    ("id", "name", "category", "timing"),
                    (("amount", "formula"), ("source", "evidence_id", "assumption_id")),
                ),
                (
                    "benefit_items",
                    (
                        "id",
                        "name",
                        "type",
                        "baseline",
                        "formula",
                        "attribution",
                        "owner",
                        "status",
                    ),
                    (),
                ),
                (
                    "cash_flows",
                    ("period", "cost", "benefit", "net"),
                    (),
                ),
                (
                    "formulas",
                    ("name", "expression", "input_ids"),
                    (),
                ),
                (
                    "scenarios",
                    ("name", "assumption_ids", "output"),
                    (),
                ),
                (
                    "outputs",
                    ("metric", "value"),
                    (),
                ),
            )
            for collection, required_fields, any_of_groups in investment_shapes:
                items = quantitative.get(collection, [])
                if not isinstance(items, list):
                    continue
                for index, item in enumerate(items):
                    item_path = f"quantitative_model.{collection}[{index}]"
                    if not isinstance(item, dict):
                        error("TYPE", item_path, "must be a JSON object")
                        continue
                    for field in required_fields:
                        if field not in item or not _present(item.get(field)):
                            error(
                                "REQUIRED",
                                f"{item_path}.{field}",
                                "is required for investment-case mode",
                            )
                    for group in any_of_groups:
                        if not any(_present(item.get(field)) for field in group):
                            error(
                                "REQUIRED_ONE_OF",
                                item_path,
                                "requires one of: " + ", ".join(group),
                            )
                    if collection in {"formulas", "scenarios"}:
                        list_field = "input_ids" if collection == "formulas" else "assumption_ids"
                        if list_field in item and not isinstance(item.get(list_field), list):
                            error(
                                "TYPE",
                                f"{item_path}.{list_field}",
                                "must be a list of stable IDs",
                            )
        if portfolio_applicable is not True:
            warn(
                "PORTFOLIO_REQUIRED",
                "portfolio.applicable",
                "investment-case mode requires explicit candidate prioritization and gate results",
            )
        else:
            candidates = portfolio.get("candidates", [])
            if isinstance(candidates, list) and len(candidates) < 2:
                warn(
                    "MISSING_CANDIDATES",
                    "portfolio.candidates",
                    "at least two candidates are required for prioritization",
                )
            candidate_ids: set[str] = set()
            if isinstance(candidates, list):
                for index, candidate in enumerate(candidates):
                    item_path = f"portfolio.candidates[{index}]"
                    if not isinstance(candidate, dict):
                        error("TYPE", item_path, "must be a JSON object")
                        continue
                    for field in ("id", "name", "category", "owner", "status"):
                        if not _present(candidate.get(field)):
                            error("REQUIRED", f"{item_path}.{field}", "is required")
                    if _present(candidate.get("id")):
                        candidate_id = str(candidate["id"])
                        if candidate_id in candidate_ids:
                            error(
                                "DUPLICATE_ID",
                                f"{item_path}.id",
                                f"duplicate candidate id: {candidate_id}",
                            )
                        candidate_ids.add(candidate_id)
            gate_results = portfolio.get("gate_results", [])
            if not _present(gate_results):
                warn(
                    "MISSING_GATE_RESULTS",
                    "portfolio.gate_results",
                    "at least one explicit gate result is required per candidate",
                )
            covered_candidates: set[str] = set()
            if isinstance(gate_results, list):
                for index, result in enumerate(gate_results):
                    item_path = f"portfolio.gate_results[{index}]"
                    if not isinstance(result, dict):
                        error("TYPE", item_path, "must be a JSON object")
                        continue
                    for field in ("candidate_id", "gate", "result", "rationale", "owner"):
                        if not _present(result.get(field)):
                            error("REQUIRED", f"{item_path}.{field}", "is required")
                    if _present(result.get("candidate_id")):
                        candidate_id = str(result["candidate_id"])
                        covered_candidates.add(candidate_id)
                        if candidate_ids and candidate_id not in candidate_ids:
                            error(
                                "UNKNOWN_REFERENCE",
                                f"{item_path}.candidate_id",
                                "does not reference a portfolio candidate",
                            )
                    if _present(result.get("result")) and result.get("result") not in {
                        "pass",
                        "conditional",
                        "fail",
                        "deferred",
                    }:
                        error(
                            "GATE_RESULT",
                            f"{item_path}.result",
                            "must be pass, conditional, fail, or deferred",
                        )
            uncovered = sorted(candidate_ids - covered_candidates)
            if uncovered:
                warn(
                    "UNCOVERED_CANDIDATE",
                    "portfolio.gate_results",
                    "missing gate result for: " + ", ".join(uncovered),
                )

        _validate_investment_consistency(state, error, warn)

    return _validation_report(issues, mode)


def _validation_report(
    issues: list[dict[str, str]], mode: str | None
) -> dict[str, Any]:
    deduplicated: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for issue in issues:
        key = (
            issue["severity"],
            issue["code"],
            issue["path"],
            issue["message"],
        )
        if key not in seen:
            seen.add(key)
            deduplicated.append(issue)
    issues = deduplicated
    errors = [
        f"{issue['path']}: {issue['message']}"
        for issue in issues
        if issue["severity"] == "error"
    ]
    warnings = [
        f"{issue['path']}: {issue['message']}"
        for issue in issues
        if issue["severity"] == "warning"
    ]
    ready = not errors and not warnings
    return {
        "status": "ready" if ready else ("invalid" if errors else "draft"),
        "ready": ready,
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }


def update_section(
    state: dict[str, Any],
    section: str,
    key: str | None,
    value: Any,
    action: str,
) -> dict[str, Any]:
    if section not in TOP_LEVEL_SECTIONS:
        raise BlackboardError(
            "UNKNOWN_SECTION",
            f"unknown section: {section}",
            details={"allowed": list(TOP_LEVEL_SECTIONS)},
        )
    if section not in state or not isinstance(state[section], dict):
        raise BlackboardError(
            "INVALID_SECTION",
            f"{section} is not a JSON object",
        )
    if section == "metadata":
        protected = (
            {key} & PROTECTED_METADATA_FIELDS
            if key
            else set(value) & PROTECTED_METADATA_FIELDS
            if isinstance(value, dict)
            else set()
        )
        if protected:
            raise BlackboardError(
                "PROTECTED_FIELD",
                "revision and schema metadata are managed by the blackboard",
                details={"fields": sorted(protected)},
            )
    target = state[section]
    if key:
        if action == "append":
            if key not in target:
                raise BlackboardError(
                    "UNKNOWN_FIELD",
                    f"{section}.{key} does not exist in schema v2",
                )
            if not isinstance(target[key], list):
                raise BlackboardError(
                    "NOT_A_LIST",
                    f"{section}.{key} is not a list",
                )
            target[key].append(value)
        else:
            if key not in target:
                raise BlackboardError(
                    "UNKNOWN_FIELD",
                    f"{section}.{key} does not exist in schema v2",
                )
            target[key] = value
    else:
        if action == "append":
            raise BlackboardError(
                "INVALID_ACTION",
                "section-level append is not supported; provide --key",
            )
        if not isinstance(value, dict):
            raise BlackboardError(
                "INVALID_VALUE",
                "section-level updates require a JSON object",
            )
        unknown = sorted(set(value) - set(target))
        if unknown:
            raise BlackboardError(
                "UNKNOWN_FIELD",
                f"unknown fields in {section}",
                details={"fields": unknown},
            )
        target.update(value)
    return state


def _assert_evidence_immutable(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    """Require corrections to supersede frozen evidence instead of rewriting it."""

    def index_records(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        records = state.get("evidence", {}).get("records", [])
        if not isinstance(records, list):
            return indexed
        for record in records:
            if not isinstance(record, dict):
                continue
            evidence_id = record.get("evidence_id") or record.get("id")
            if _present(evidence_id):
                indexed[str(evidence_id)] = record
        return indexed

    existing = index_records(before)
    candidate = index_records(after)
    for evidence_id, frozen_record in existing.items():
        if evidence_id not in candidate:
            raise BlackboardError(
                "IMMUTABLE_EVIDENCE",
                "evidence records cannot be deleted; add a superseding record instead",
                details={"evidence_id": evidence_id},
            )
        if candidate[evidence_id] != frozen_record:
            raise BlackboardError(
                "IMMUTABLE_EVIDENCE",
                "evidence records cannot be edited; add a new ID and supersedes link",
                details={"evidence_id": evidence_id},
            )


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_init(args: argparse.Namespace) -> int:
    path = blackboard_path(args.workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path, exclusive=True):
        if path.exists() and not args.force:
            raise BlackboardError(
                "ALREADY_INITIALIZED",
                "blackboard already exists; use --force to replace it explicitly",
                details={"path": str(path)},
            )
        previous_revision = 0
        if path.exists():
            try:
                previous = _normalize_loaded_state(_read_json_unlocked(path))
            except BlackboardError as exc:
                if exc.code not in {"INVALID_JSON", "INVALID_ROOT"}:
                    raise
            else:
                revision = previous.get("metadata", {}).get("revision")
                if isinstance(revision, int):
                    previous_revision = revision + 1
        state = default_state(args.topic, args.mode)
        state["metadata"]["revision"] = previous_revision
        _atomic_write_unlocked(path, state)
    _print(
        {
            "status": "initialized",
            "path": str(path),
            "schema_version": SCHEMA_VERSION,
            "revision": state["metadata"]["revision"],
            "mode": args.mode,
            "topic": args.topic,
        }
    )
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    path = blackboard_path(args.workspace_root)
    if not path.exists():
        raise BlackboardError(
            "NOT_INITIALIZED",
            "blackboard is not initialized; run the init command first",
            details={"path": str(path)},
        )
    with _file_lock(path, exclusive=True):
        if not path.exists():
            raise BlackboardError(
                "NOT_INITIALIZED",
                "blackboard disappeared while waiting for the lock",
                details={"path": str(path)},
            )
        state = _normalize_loaded_state(_read_json_unlocked(path))
        metadata = state.get("metadata", {})
        actual_revision = metadata.get("revision")
        if args.expect_revision is not None and actual_revision != args.expect_revision:
            raise BlackboardError(
                "REVISION_CONFLICT",
                "blackboard changed after it was read",
                details={
                    "path": str(path),
                    "expected_revision": args.expect_revision,
                    "actual_revision": actual_revision,
                },
            )
        old_mode = metadata.get("mode")
        candidate = deepcopy(state)
        update_section(
            candidate,
            args.section,
            args.key,
            parse_update_value(args.value),
            args.action,
        )
        if args.section == "evidence":
            _assert_evidence_immutable(state, candidate)
        new_mode = candidate.get("metadata", {}).get("mode")
        if new_mode not in MODES:
            raise BlackboardError(
                "INVALID_MODE",
                f"mode must be one of: {', '.join(MODES)}",
                details={"mode": new_mode},
            )
        candidate["metadata"]["schema_version"] = SCHEMA_VERSION
        candidate["metadata"]["revision"] = (
            actual_revision if isinstance(actual_revision, int) else 0
        ) + 1
        candidate["metadata"]["updated_at"] = _now()
        candidate["metadata"].setdefault("created_at", _now())
        report = validate_state(candidate)
        if report["errors"]:
            raise BlackboardError(
                "INVALID_UPDATE",
                "update would violate schema v2",
                details={"errors": report["errors"]},
            )
        _atomic_write_unlocked(path, candidate)
    _print(
        {
            "status": "updated",
            "path": str(path),
            "schema_version": SCHEMA_VERSION,
            "revision": candidate["metadata"]["revision"],
            "previous_mode": old_mode,
            "mode": new_mode,
            "section": args.section,
            "key": args.key,
            "action": args.action,
        }
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    _print(
        {
            "status": "ok",
            "path": str(path),
            "schema_version": state.get("metadata", {}).get("schema_version"),
            "revision": state.get("metadata", {}).get("revision"),
            "state": state,
            "validation": report,
        }
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    report["path"] = str(path)
    report["schema_version"] = state.get("metadata", {}).get("schema_version")
    report["revision"] = state.get("metadata", {}).get("revision")
    _print(report)
    if report["errors"]:
        return 1
    if args.strict and report["warnings"]:
        return 1
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    report["path"] = str(path)
    report["schema_version"] = state.get("metadata", {}).get("schema_version")
    report["revision"] = state.get("metadata", {}).get("revision")
    _print(report)
    # Readiness is an unconditional gate; --strict is retained only for CLI
    # compatibility and does not weaken this behavior.
    return 0 if report["ready"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = JSONArgumentParser(description="Strategy Blackboard schema v2")
    parser.add_argument("--workspace-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a new schema-v2 blackboard")
    p_init.add_argument("--topic", required=True)
    p_init.add_argument("--mode", default="deep-dive", choices=MODES)
    p_init.add_argument(
        "--force",
        action="store_true",
        help="explicitly replace an existing blackboard",
    )
    p_init.set_defaults(func=cmd_init)

    p_update = sub.add_parser("update", help="atomically update one v2 section")
    p_update.add_argument("--section", required=True, choices=TOP_LEVEL_SECTIONS)
    p_update.add_argument("--key")
    p_update.add_argument(
        "--value",
        required=True,
        help="inline JSON/text, @path for UTF-8 file input, or - for stdin",
    )
    p_update.add_argument("--action", choices=("set", "append"), default="set")
    p_update.add_argument(
        "--expect-revision",
        type=int,
        help="fail instead of overwriting if the revision has changed",
    )
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status", help="show state and validation result")
    p_status.set_defaults(func=cmd_status)

    p_validate = sub.add_parser("validate", help="validate schema and readiness")
    p_validate.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero for warnings as well as errors",
    )
    p_validate.set_defaults(func=cmd_validate)

    p_ready = sub.add_parser("ready", help="return non-zero unless decision-ready")
    p_ready.add_argument(
        "--strict",
        action="store_true",
        help="compatibility flag; readiness always blocks on warnings",
    )
    p_ready.set_defaults(func=cmd_ready)
    return parser


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        return int(args.func(args) or 0)
    except BlackboardError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False, indent=2), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {"code": "INTERRUPTED", "message": "operation interrupted"},
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 130
    except Exception as exc:  # pragma: no cover - final CLI safety boundary
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "unexpected blackboard failure",
                        "details": {"type": type(exc).__name__, "reason": str(exc)},
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
