from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time as monotonic_time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from history_manager import (
    generate_event_id,
    load_recent_history,
    match_history,
    normalize_url,
)
from hub_utils import HUB_DIR, RUNTIME_DIR, atomic_dump_json, load_json


CONTRACT_VERSION = "1.0"
STRICT_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
CURRENT_SCHEMA_PATH = HUB_DIR / "references" / "briefing_schema.json"
SUBAGENT_PROMPTS_PATH = HUB_DIR / "references" / "subagent_prompts.json"
SEMANTIC_AGENT_PATH = HUB_DIR / "scripts" / "semantic_agent.py"
STAGE_ORDER = ("baseline", "supplemental", "semantic_review", "red_team", "archive")
STAGE_TERMINAL = {
    "completed",
    "degraded",
    "degraded_timeout",
    "skipped",
    "not_required",
}
STAGE_FINAL = STAGE_TERMINAL | {"failed"}
SUPPLEMENT_FAILURE_KIND_ALIASES = {
    "infrastructure": "infrastructure",
    "source_access": "source_access",
    "source_access_blocked": "source_access",
    "bound_source_access_blocked": "source_access",
    "published_at_conflict": "published_at_conflict",
    "publication_date_conflict": "published_at_conflict",
    "date_conflict": "published_at_conflict",
}
SUPPLEMENT_FAILURE_KIND_STATUS = {
    "infrastructure": "failed",
    "source_access": "degraded",
    "published_at_conflict": "degraded",
}
IMMUTABLE_FIELDS = (
    "run_id",
    "skill_sha256",
    "skill_bundle_sha256",
    "skill_path",
    "resource_manifest_sha256",
    "resource_manifest_path",
    "report_date",
    "timezone",
    "window",
    "mix_request",
)


class RunContractError(ValueError):
    pass


def normalize_supplement_failure_kind(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = SUPPLEMENT_FAILURE_KIND_ALIASES.get(str(value).strip().lower())
    if normalized is None:
        raise RunContractError("supplement failure_kind is invalid")
    return normalized


def validate_supplement_failure_kind(value: Any, status: str) -> str | None:
    normalized = normalize_supplement_failure_kind(value)
    if status in {"degraded", "failed"} and normalized is None:
        raise RunContractError(
            "degraded or failed supplement result requires failure_kind"
        )
    if normalized is not None and SUPPLEMENT_FAILURE_KIND_STATUS[normalized] != status:
        raise RunContractError("supplement failure_kind does not match status")
    return normalized


@contextmanager
def locked_manifest(
    manifest_path: str | Path,
    *,
    timeout_seconds: float = 10.0,
) -> Iterator[tuple[dict[str, Any], str]]:
    """Lock and load the authoritative manifest for one cross-process RMW."""
    path = Path(manifest_path)
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    acquired = False
    deadline = monotonic_time.monotonic() + timeout_seconds
    try:
        while not acquired:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if monotonic_time.monotonic() >= deadline:
                    raise RunContractError(
                        f"timed out acquiring run manifest lock: {path}"
                    ) from exc
                monotonic_time.sleep(0.01)
        manifest = load_manifest(path)
        yield manifest, file_sha256(path)
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def commit_manifest(
    manifest_path: str | Path,
    manifest: dict[str, Any],
    expected_sha256: str,
) -> None:
    """CAS guard for a manifest already protected by ``locked_manifest``."""
    path = Path(manifest_path)
    if file_sha256(path) != expected_sha256:
        raise RunContractError("stale manifest writer rejected")
    atomic_dump_json(path, manifest)


def _aware_now(timezone_name: str, supplied: datetime | None = None) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RunContractError(f"unknown timezone: {timezone_name}") from exc
    if supplied is None:
        return datetime.now(zone)
    if supplied.tzinfo is None or supplied.utcoffset() is None:
        raise RunContractError("now must be timezone-aware")
    return supplied.astimezone(zone)


def _normalized_ratio(ratio: dict[str, float]) -> dict[str, float]:
    domains = ("technology", "healthcare_digital")
    values = {domain: float(ratio.get(domain, 0.0)) for domain in domains}
    total = sum(values.values())
    if total <= 0:
        raise RunContractError("requested ratio must have a positive sum")
    return {domain: values[domain] / total for domain in domains}


def _current_schema_default_ratio() -> dict[str, float]:
    schema = load_json(CURRENT_SCHEMA_PATH, {})
    ratio = (schema.get("domain_mix") or {}).get("default_ratio")
    domains = ("technology", "healthcare_digital")
    if not isinstance(ratio, dict) or any(
        not isinstance(ratio.get(domain), (int, float)) for domain in domains
    ):
        raise RunContractError("briefing schema default ratio is missing or invalid")
    if any(float(ratio[domain]) < 0 for domain in domains):
        raise RunContractError("briefing schema default ratio cannot be negative")
    return _normalized_ratio(ratio)


def calendar_window(report_date: str | date, days: int, timezone_name: str) -> dict[str, Any]:
    if days <= 0:
        raise RunContractError("window days must be positive")
    try:
        report_day = report_date if isinstance(report_date, date) else date.fromisoformat(report_date)
        ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise RunContractError("invalid report date or timezone") from exc
    start = report_day - timedelta(days=days - 1)
    return {
        "mode": "calendar_days",
        "days": days,
        "start": start.isoformat(),
        "end": report_day.isoformat(),
        "timezone": timezone_name,
    }


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunContractError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise RunContractError(f"{field} must be at least {minimum}")
    return value


def item_hash(item: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(item)).hexdigest()


def review_scope(
    refined: dict[str, Any],
    semantic_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = refined.get("top_10", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise RunContractError("refined core top_10 must be a list of objects")
    l4_hashes = sorted(
        item_hash(item) for item in items if item.get("intelligence_level") == "L4"
    )
    major_signal_hashes = sorted(
        item_hash(item) for item in items if item.get("major_signal") is True
    )
    conflict_item_hashes = sorted(
        item_hash(item)
        for item in items
        if item.get("evidence_conflict") is True or bool(item.get("conflicts"))
    )
    semantic_conflict = bool(
        semantic_receipt
        and (
            semantic_receipt.get("status") != "passed"
            or bool(semantic_receipt.get("conflicts"))
        )
    )
    targeted = bool(major_signal_hashes or conflict_item_hashes or semantic_conflict)
    return {
        "review_mode": (
            "l4_full_review"
            if l4_hashes
            else "targeted_review"
            if targeted
            else "no_l4_fast_path"
        ),
        "l4_item_hashes": l4_hashes,
        "major_signal_item_hashes": major_signal_hashes,
        "conflict_item_hashes": conflict_item_hashes,
        "semantic_conflict": semantic_conflict,
    }


def _deterministic_red_team_fast_path(
    refined: dict[str, Any],
    semantic_receipt: dict[str, Any],
) -> bool:
    scope = review_scope(refined, semantic_receipt)
    return scope["review_mode"] == "no_l4_fast_path"


def candidate_ref(url: str) -> str:
    normalized = normalize_url(str(url))
    if not normalized:
        raise RunContractError("candidate URL is required")
    return "cand-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def candidate_object_hash(candidate: dict[str, Any]) -> str:
    bound = deepcopy(candidate)
    bound.pop("candidate_object_sha256", None)
    return hashlib.sha256(canonical_json_bytes(bound)).hexdigest()


def registered_candidate_lineage(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    records = (
        (
            "candidate pool",
            manifest.get("artifacts", {}).get("candidate_pool", {}),
            "items",
        ),
        (
            "supplement aggregate",
            manifest.get("stages", {}).get("supplemental", {}),
            "results",
        ),
    )
    registered: dict[str, dict[str, Any]] = {}
    for label, record, collection in records:
        if not isinstance(record, dict):
            raise RunContractError(f"registered {label} record is missing")
        artifact_path = Path(str(record.get("artifact_path") or ""))
        if (
            not artifact_path.is_file()
            or record.get("artifact_sha256") != file_sha256(artifact_path)
        ):
            raise RunContractError(f"registered {label} bytes changed")
        payload = load_json(artifact_path, {})
        if collection == "items":
            candidates = payload.get("items", [])
        else:
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise RunContractError("supplement aggregate results are invalid")
            candidates = [
                candidate
                for result in results
                if isinstance(result, dict)
                for candidate in result.get("candidates", [])
            ]
        if not isinstance(candidates, list) or any(
            not isinstance(candidate, dict) for candidate in candidates
        ):
            raise RunContractError(f"registered {label} candidates are invalid")
        for candidate in candidates:
            reference = str(candidate.get("candidate_id") or "")
            claimed_hash = str(candidate.get("candidate_object_sha256") or "")
            actual_hash = candidate_object_hash(candidate)
            if not reference or claimed_hash != actual_hash:
                raise RunContractError(f"registered {label} candidate hash is invalid")
            entry = registered.setdefault(
                reference,
                {"object_hashes": set(), "urls": set(), "objects": {}},
            )
            entry["object_hashes"].add(claimed_hash)
            entry["objects"][claimed_hash] = deepcopy(candidate)
            for raw_url in (
                candidate.get("url"),
                (candidate.get("access_check") or {}).get("final_url"),
            ):
                normalized = normalize_url(str(raw_url or ""))
                if normalized:
                    entry["urls"].add(normalized)
    return registered


def registered_candidate_hashes(manifest: dict[str, Any]) -> dict[str, set[str]]:
    return {
        reference: set(entry["object_hashes"])
        for reference, entry in registered_candidate_lineage(manifest).items()
    }


def validate_semantic_history(refined: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Apply forge-equivalent history dedupe before semantic publication."""
    history_record = manifest.get("artifacts", {}).get("history_snapshot", {})
    history_path = Path(str(history_record.get("artifact_path") or ""))
    if (
        not history_path.is_file()
        or history_record.get("artifact_sha256") != file_sha256(history_path)
    ):
        raise RunContractError("registered history snapshot bytes changed")
    report_clock = datetime.combine(
        date.fromisoformat(str(manifest["report_date"])),
        time.max,
        tzinfo=ZoneInfo(str(manifest["timezone"])),
    )
    recent_history = load_recent_history(
        days=int(history_record.get("metadata", {}).get("dedupe_days", 7)),
        now=report_clock,
        path=history_path,
    )
    for index, item in enumerate(refined.get("top_10", [])):
        if not isinstance(item, dict):
            raise RunContractError(f"semantic draft top_10[{index}] must be an object")
        match = match_history(item, entries=recent_history, now=report_clock)
        if match.get("redundant"):
            raise RunContractError(
                f"semantic draft top_10[{index}] duplicates the bound history snapshot"
            )


def validate_registered_pipeline_summary(
    refined: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Fail closed when a semantic draft omits registered coverage inputs."""
    baseline_stage = manifest.get("stages", {}).get("baseline", {})
    baseline_coverage = baseline_stage.get("metadata", {}).get("coverage")
    if not isinstance(baseline_coverage, dict):
        raise RunContractError("baseline coverage receipt is missing")

    supplement_record = manifest.get("stages", {}).get("supplemental", {})
    supplement_path = Path(str(supplement_record.get("artifact_path") or ""))
    if (
        not supplement_path.is_file()
        or supplement_record.get("artifact_sha256") != file_sha256(supplement_path)
    ):
        raise RunContractError("registered supplement aggregate bytes changed")
    supplement = load_json(supplement_path, {})
    supplement_coverage = supplement.get("coverage") or {}
    try:
        expected_counts = {
            "source_attempted": _integer(
                baseline_coverage["source_attempted"],
                "baseline coverage.source_attempted",
                minimum=0,
            )
            + _integer(
                supplement_coverage.get("attempted", 0),
                "supplement coverage.attempted",
                minimum=0,
            ),
            "source_succeeded": _integer(
                baseline_coverage["source_succeeded"],
                "baseline coverage.source_succeeded",
                minimum=0,
            )
            + _integer(
                supplement_coverage.get("succeeded", 0),
                "supplement coverage.succeeded",
                minimum=0,
            ),
            "source_failed": _integer(
                baseline_coverage["source_failed"],
                "baseline coverage.source_failed",
                minimum=0,
            )
            + _integer(
                supplement_coverage.get("failed", 0),
                "supplement coverage.failed",
                minimum=0,
            ),
        }
        baseline_raw = _integer(
            baseline_coverage["raw_candidates"],
            "baseline coverage.raw_candidates",
            minimum=0,
        )
        baseline_dated = _integer(
            baseline_coverage["dated_candidates"],
            "baseline coverage.dated_candidates",
            minimum=0,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunContractError("baseline coverage receipt counts are invalid") from exc

    coverage = refined.get("coverage")
    if not isinstance(coverage, dict):
        raise RunContractError("semantic draft coverage is missing")
    for field, expected in expected_counts.items():
        if coverage.get(field) != expected:
            raise RunContractError(
                f"semantic draft coverage.{field} does not match registered artifacts"
            )
    attempted = expected_counts["source_attempted"]
    expected_rate = expected_counts["source_succeeded"] / attempted if attempted else 0.0
    if not isinstance(coverage.get("source_success_rate"), (int, float)) or not math.isclose(
        float(coverage["source_success_rate"]), expected_rate, abs_tol=1e-6
    ):
        raise RunContractError(
            "semantic draft coverage.source_success_rate does not match registered artifacts"
        )
    expected_baseline_status = (
        "completed" if baseline_stage.get("status") == "completed" else baseline_stage.get("status")
    )
    if coverage.get("baseline_status") != expected_baseline_status:
        raise RunContractError(
            "semantic draft coverage.baseline_status does not match run manifest"
        )

    raw_results = supplement.get("results")
    results: list[Any] = raw_results if isinstance(raw_results, list) else []
    lane_failure_set: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        result_coverage = result.get("coverage")
        failed_count = (
            int(result_coverage.get("failed", 0))
            if isinstance(result_coverage, dict)
            else 0
        )
        if result.get("status") in {"degraded", "failed"} or failed_count > 0:
            lane_failure_set.add(str(result.get("lane")))
    lane_failures = sorted(lane_failure_set)
    if sorted(str(value) for value in coverage.get("required_lane_failures", [])) != lane_failures:
        raise RunContractError(
            "semantic draft coverage.required_lane_failures does not match supplement results"
        )
    expected_run_status = (
        "degraded"
        if baseline_stage.get("status") == "degraded"
        or supplement_record.get("status") == "degraded"
        else "complete"
    )
    if coverage.get("run_status") != expected_run_status:
        raise RunContractError(
            "semantic draft coverage.run_status does not match registered stage status"
        )
    expected_confidence = "high" if expected_run_status == "complete" else "medium"
    if coverage.get("coverage_confidence") != expected_confidence:
        raise RunContractError(
            "semantic draft coverage.coverage_confidence does not match registered stage status"
        )
    expected_reasons = sorted(
        str(value) for value in baseline_coverage.get("reasons", []) if str(value)
    ) + [f"supplement lane degraded: {lane}" for lane in lane_failures]
    if sorted(str(value) for value in coverage.get("reasons", [])) != sorted(expected_reasons):
        raise RunContractError(
            "semantic draft coverage.reasons do not match registered artifacts"
        )

    supplemental_candidates = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        result_candidates = result.get("candidates")
        if isinstance(result_candidates, list):
            supplemental_candidates += len(result_candidates)
    dated_denominator = baseline_raw + supplemental_candidates
    expected_dated_rate = (
        (baseline_dated + supplemental_candidates) / dated_denominator
        if dated_denominator
        else 0.0
    )
    if not isinstance(coverage.get("dated_candidate_rate"), (int, float)) or not math.isclose(
        float(coverage["dated_candidate_rate"]), expected_dated_rate, abs_tol=1e-6
    ):
        raise RunContractError(
            "semantic draft coverage.dated_candidate_rate does not match registered artifacts"
        )

    candidate_record = manifest.get("artifacts", {}).get("candidate_pool", {})
    candidate_path = Path(str(candidate_record.get("artifact_path") or ""))
    if (
        not candidate_path.is_file()
        or candidate_record.get("artifact_sha256") != file_sha256(candidate_path)
    ):
        raise RunContractError("registered candidate pool bytes changed")
    candidate_pool = load_json(candidate_path, {})
    baseline_observed = candidate_pool.get("candidate_funnel", {}).get("observed")
    if not isinstance(baseline_observed, int):
        raise RunContractError("candidate pool observed count is missing")
    expected_observed = baseline_observed + supplemental_candidates
    if refined.get("candidate_funnel", {}).get("observed") != expected_observed:
        raise RunContractError(
            "semantic draft candidate_funnel.observed does not match registered artifacts"
        )
    validate_registered_candidate_funnel(
        refined,
        candidate_pool,
        supplemental_candidates=supplemental_candidates,
    )


def validate_registered_candidate_funnel(
    refined: dict[str, Any],
    candidate_pool: dict[str, Any],
    *,
    supplemental_candidates: int,
) -> None:
    """Bind every final funnel disposition to the registered candidate supply."""
    baseline_funnel = candidate_pool.get("candidate_funnel")
    final_funnel = refined.get("candidate_funnel")
    if not isinstance(baseline_funnel, dict) or not isinstance(final_funnel, dict):
        raise RunContractError("candidate funnel receipts are missing")
    baseline_terminal = baseline_funnel.get("terminal_dispositions")
    final_terminal = final_funnel.get("terminal_dispositions")
    if not isinstance(baseline_terminal, dict) or not isinstance(final_terminal, dict):
        raise RunContractError("candidate funnel terminal dispositions are missing")

    def validated_counts(values: dict[str, Any], label: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for key, value in values.items():
            if not isinstance(key, str) or not key:
                raise RunContractError(f"{label} has an invalid disposition name")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RunContractError(f"{label}.{key} must be a non-negative integer")
            counts[key] = value
        return counts

    baseline_counts = validated_counts(
        baseline_terminal, "candidate pool terminal_dispositions"
    )
    final_counts = validated_counts(
        final_terminal, "semantic draft terminal_dispositions"
    )
    observed = baseline_funnel.get("observed")
    retained_for_review = baseline_funnel.get("retained_for_review")
    if (
        not isinstance(observed, int)
        or isinstance(observed, bool)
        or observed < 0
        or not isinstance(retained_for_review, int)
        or isinstance(retained_for_review, bool)
        or retained_for_review < 0
    ):
        raise RunContractError("candidate pool funnel counts are invalid")
    if sum(baseline_counts.values()) != observed:
        raise RunContractError("candidate pool terminal dispositions do not conserve observed")
    if baseline_counts.get("retained_for_review") != retained_for_review:
        raise RunContractError("candidate pool retained_for_review is inconsistent")
    items = candidate_pool.get("items")
    if not isinstance(items, list) or len(items) != retained_for_review:
        raise RunContractError("candidate pool retained_for_review does not match items")

    fixed_dispositions = {
        key: value
        for key, value in baseline_counts.items()
        if key != "retained_for_review"
    }
    for key, expected in fixed_dispositions.items():
        if final_counts.get(key, 0) != expected:
            raise RunContractError(
                f"semantic draft terminal_dispositions.{key} does not match candidate pool"
            )
    downstream_keys = {
        "semantic_duplicate",
        "below_quality_gate",
        "semantic_capacity",
        "red_team_rejected",
        "retained",
    }
    downstream_total = sum(final_counts.get(key, 0) for key in downstream_keys)
    expected_downstream = retained_for_review + supplemental_candidates
    if downstream_total != expected_downstream:
        raise RunContractError(
            "semantic draft downstream terminal dispositions do not conserve review candidates"
        )


def skill_bundle_sha256(skill_path: str | Path) -> str:
    root = Path(skill_path).resolve().parent
    files: list[Path] = []
    for name in ("SKILL.md", "requirements.txt", "resource-manifest.json"):
        path = root / name
        if path.is_file():
            files.append(path)
    for directory_name in ("agents", "references", "scripts"):
        directory = root / directory_name
        if directory.is_dir():
            files.extend(
                path
                for path in directory.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and not {".ruff_cache", ".pytest_cache", ".mypy_cache"}.intersection(
                    path.parts
                )
                and path.suffix.lower() not in {".pyc", ".pyo"}
            )
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in sorted(set(files), key=lambda value: value.relative_to(root).as_posix())
    ]
    return hashlib.sha256(canonical_json_bytes(records)).hexdigest()


def _canonical_content_sha256(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {
        ".md", ".txt", ".py", ".ps1", ".sh", ".csx", ".cs", ".svg",
        ".xml", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv",
        ".html", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    } or path.name.lower() in {".gitignore", ".gitattributes", ".editorconfig"}:
        text = data.decode("utf-8")
        data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def validate_resource_manifest(manifest_path: str | Path, skill_path: str | Path) -> None:
    path = Path(manifest_path)
    root = Path(skill_path).resolve().parent
    payload = load_json(path, {})
    schema_version = payload.get("schema_version") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or schema_version not in {2, 3}
        or payload.get("skill") != root.name
    ):
        raise RunContractError("skill resource manifest identity is invalid")
    if schema_version == 3 and (
        payload.get("hash_algorithm") != "SHA-256"
        or payload.get("text_hash_normalization") != "LF"
    ):
        raise RunContractError("skill resource manifest hash contract is invalid")
    if payload.get("missing_declared_dependencies"):
        raise RunContractError("skill resource manifest has missing dependencies")
    declared: list[tuple[str, str]] = []
    skill_name = str(payload.get("skill_md") or "SKILL.md")
    declared.append((skill_name, str(payload.get("skill_md_sha256") or "")))

    def append_hash_records(field: str, *, required: bool = False) -> None:
        records = payload.get(field)
        if not isinstance(records, list) or (required and not records):
            raise RunContractError(f"skill resource manifest {field} is invalid")
        for record in records:
            if not isinstance(record, dict):
                raise RunContractError(f"skill resource manifest {field} is invalid")
            relative = str(record.get("path") or "")
            expected = str(record.get("sha256") or "").lower()
            if (
                not relative
                or len(expected) != 64
                or any(character not in "0123456789abcdef" for character in expected)
            ):
                raise RunContractError(f"skill resource manifest {field} is invalid")
            declared.append((relative, expected))

    append_hash_records("top_level_file_hashes")
    if schema_version == 3:
        append_hash_records("resource_file_hashes", required=True)
    for record in payload.get("declared_local_dependencies", []):
        if isinstance(record, dict) and record.get("exists") is True:
            declared.append((str(record.get("path") or ""), str(record.get("sha256") or "")))
    seen: dict[str, str] = {}
    for relative, expected in declared:
        normalized = relative.replace("\\", "/")
        if not normalized:
            continue
        prior = seen.get(normalized)
        if prior is not None:
            if prior != expected:
                raise RunContractError(
                    f"skill resource manifest has conflicting hashes: {normalized}"
                )
            continue
        seen[normalized] = expected
        dependency = (root / Path(normalized)).resolve()
        try:
            dependency.relative_to(root)
        except ValueError as exc:
            raise RunContractError("resource manifest dependency escapes skill root") from exc
        if not dependency.is_file() or _canonical_content_sha256(dependency) != expected:
            raise RunContractError(
                f"skill resource manifest hash mismatch: {normalized}"
            )


def review_input_bundle_sha256(manifest: dict[str, Any]) -> str:
    artifacts = manifest.get("artifacts", {})
    candidate = artifacts.get("candidate_pool", {})
    history = artifacts.get("history_snapshot", {})
    history_review = artifacts.get("history_review_slice", {})
    focus = artifacts.get("focus_config", {})
    supplement = manifest.get("stages", {}).get("supplemental", {})
    bound_records = {
        "baseline": manifest.get("stages", {}).get("baseline", {}),
        "candidate_pool": candidate,
        "history_snapshot": history,
        "history_review_slice": history_review,
        "focus_config": focus,
        "supplemental": supplement,
    }
    for label, record in bound_records.items():
        if not record:
            continue
        artifact_path = Path(str(record.get("artifact_path") or ""))
        expected_sha = str(record.get("artifact_sha256") or "")
        if (
            not artifact_path.is_file()
            or len(expected_sha) != 64
            or file_sha256(artifact_path) != expected_sha
        ):
            raise RunContractError(f"review input bundle {label} bytes changed")
    values = {
        "run_id": manifest.get("run_id"),
        "baseline_sha256": manifest.get("stages", {}).get("baseline", {}).get("artifact_sha256"),
        "candidate_pool_sha256": candidate.get("artifact_sha256"),
        "history_snapshot_sha256": history.get("artifact_sha256"),
        "supplement_sha256": supplement.get("artifact_sha256"),
        "window": manifest.get("window"),
        "mix_request": manifest.get("mix_request"),
    }
    if history_review:
        values["history_review_slice_sha256"] = history_review.get("artifact_sha256")
    if focus:
        values["focus_config_sha256"] = focus.get("artifact_sha256")
    if any(values[field] in {None, ""} for field in (
        "run_id",
        "baseline_sha256",
        "candidate_pool_sha256",
        "history_snapshot_sha256",
        "supplement_sha256",
    )):
        raise RunContractError("review input bundle is incomplete")
    if not history_review or values["history_review_slice_sha256"] in {None, ""}:
        raise RunContractError("review input bundle history slice is incomplete")
    if focus and values["focus_config_sha256"] in {None, ""}:
        raise RunContractError("review input bundle focus config is incomplete")
    if (
        history_review
        and history_review.get("input_sha256") != history.get("artifact_sha256")
    ):
        raise RunContractError("review input bundle history slice lineage mismatch")
    return hashlib.sha256(canonical_json_bytes(values)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_skill_bundle(
    skill_path: Path,
    resource_manifest_path: Path,
    run_dir: Path,
) -> tuple[Path, Path]:
    resource = load_json(resource_manifest_path, {})
    records = []
    for field in ("top_level_file_hashes", "resource_file_hashes"):
        values = resource.get(field, [])
        if not isinstance(values, list):
            raise RunContractError(f"resource manifest {field} is invalid")
        records.extend(values)
    skill_relative = str(resource.get("skill_md") or "SKILL.md")
    if not any(
        isinstance(record, dict) and record.get("path") == skill_relative
        for record in records
    ):
        records.append(
            {
                "path": skill_relative,
                "sha256": str(resource.get("skill_md_sha256") or ""),
            }
        )
    snapshot_name = str(resource.get("skill") or "").strip()
    if not snapshot_name or snapshot_name in {".", ".."} or any(
        character in snapshot_name for character in "\\/:"
    ):
        raise RunContractError("resource manifest skill name is unsafe")
    snapshot_root = run_dir / snapshot_name
    snapshot_root.mkdir(parents=True, exist_ok=False)
    copied: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RunContractError("resource manifest file record is invalid")
        relative = Path(str(record.get("path") or ""))
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() in copied
        ):
            raise RunContractError("resource manifest snapshot path is unsafe")
        source = skill_path.parent / relative
        expected_sha256 = str(record.get("sha256") or "")
        if not source.is_file() or _canonical_content_sha256(source) != expected_sha256:
            raise RunContractError("resource changed before bundle snapshot")
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if _canonical_content_sha256(destination) != expected_sha256:
            raise RunContractError("bundle snapshot copy verification failed")
        copied.add(relative.as_posix())
    snapshot_manifest = snapshot_root / "resource-manifest.json"
    shutil.copy2(resource_manifest_path, snapshot_manifest)
    snapshot_skill = snapshot_root / "SKILL.md"
    validate_resource_manifest(snapshot_manifest, snapshot_skill)
    return snapshot_skill, snapshot_manifest


def create_run(
    *,
    report_date: str | None = None,
    timezone_name: str = "Asia/Shanghai",
    window_days: int = 7,
    topic: str = "技术与医疗数字化",
    region: str = "中国、美国与全球",
    requested_ratio: dict[str, float] | None = None,
    ratio_source: str = "schema_default",
    ratio_reason: str = "none",
    runtime_dir: Path = RUNTIME_DIR,
    skill_path: Path = HUB_DIR / "SKILL.md",
    resource_manifest_path: Path | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    current = _aware_now(timezone_name, now)
    report_day = report_date or current.date().isoformat()
    window = calendar_window(report_day, window_days, timezone_name)
    schema_default = _current_schema_default_ratio()
    requested = _normalized_ratio(requested_ratio or schema_default)
    if ratio_source not in {"schema_default", "focus_config", "user"}:
        raise RunContractError("invalid ratio_source")
    if ratio_source != "schema_default" and str(ratio_reason).strip().lower() in {"", "none"}:
        raise RunContractError("non-default requested ratio requires ratio_reason")
    identifier = run_id or uuid.uuid4().hex
    if (
        not identifier
        or identifier in {".", ".."}
        or any(character in identifier for character in "\\/:")
    ):
        raise RunContractError("run_id contains invalid path characters")
    run_dir = runtime_dir / "runs" / identifier
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        raise RunContractError(f"run already exists: {identifier}")
    if not skill_path.exists():
        raise RunContractError(f"skill contract not found: {skill_path}")
    bundle_manifest = resource_manifest_path or skill_path.parent / "resource-manifest.json"
    if not bundle_manifest.is_file():
        raise RunContractError(f"skill resource manifest not found: {bundle_manifest}")
    validate_resource_manifest(bundle_manifest, skill_path)
    source_skill_sha256 = file_sha256(skill_path)
    source_resource_manifest_sha256 = file_sha256(bundle_manifest)
    source_bundle_sha256 = skill_bundle_sha256(skill_path)
    resource_payload = load_json(bundle_manifest, {})
    snapshot_record: dict[str, Any] | None = None
    effective_skill = skill_path.resolve()
    effective_manifest = bundle_manifest.resolve()
    effective_bundle_sha256 = source_bundle_sha256
    if resource_payload.get("schema_version") == 3:
        run_dir.mkdir(parents=True, exist_ok=False)
        try:
            effective_skill, effective_manifest = _snapshot_skill_bundle(
                skill_path.resolve(), bundle_manifest.resolve(), run_dir
            )
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        effective_bundle_sha256 = skill_bundle_sha256(effective_skill)
        if effective_bundle_sha256 != source_bundle_sha256:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise RunContractError("bundle snapshot does not match source bundle")
        execution_cli_path = effective_skill.parent / "scripts" / "run_daily.py"
        if not execution_cli_path.is_file():
            shutil.rmtree(run_dir, ignore_errors=True)
            raise RunContractError("bundle snapshot execution CLI is missing")
        snapshot_record = {
            "contract_version": "pih-bundle-snapshot/1.0",
            "source_skill_path": str(skill_path.resolve()),
            "source_skill_sha256": source_skill_sha256,
            "source_resource_manifest_path": str(bundle_manifest.resolve()),
            "source_resource_manifest_sha256": source_resource_manifest_sha256,
            "snapshot_root": str(effective_skill.parent.resolve()),
            "execution_cli_path": str(execution_cli_path.resolve()),
            "created_at": current.isoformat(),
        }
    manifest: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "run_id": identifier,
        "skill_sha256": file_sha256(effective_skill),
        "skill_bundle_sha256": effective_bundle_sha256,
        "skill_path": str(effective_skill.resolve()),
        "resource_manifest_sha256": file_sha256(effective_manifest),
        "resource_manifest_path": str(effective_manifest.resolve()),
        "created_at": current.isoformat(),
        "report_date": report_day,
        "timezone": timezone_name,
        "window": window,
        "topic": topic,
        "region": region,
        "mix_request": {
            "schema_default_ratio": schema_default,
            "requested_ratio": requested,
            "ratio_source": ratio_source,
            "ratio_reason": ratio_reason,
            "max_ratio_shift": 0.2,
        },
        "run_dir": str(run_dir.resolve()),
        "artifacts": {},
        "stages": {stage: {"status": "pending"} for stage in STAGE_ORDER},
        "events": [
            {
                "stage": "created",
                "status": "completed",
                "recorded_at": current.isoformat(),
            }
        ],
    }
    if snapshot_record is not None:
        manifest["bundle_snapshot"] = snapshot_record
    atomic_dump_json(manifest_path, manifest)
    atomic_dump_json(
        runtime_dir / "active_run.json",
        {"run_id": identifier, "manifest_path": str(manifest_path.resolve())},
    )
    return manifest_path, manifest


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = load_json(manifest_path, {})
    if not isinstance(manifest, dict) or manifest.get("contract_version") != CONTRACT_VERSION:
        raise RunContractError(f"invalid run manifest: {manifest_path}")
    skill_path = Path(str(manifest.get("skill_path") or ""))
    resource_path = Path(str(manifest.get("resource_manifest_path") or ""))
    if not skill_path.is_file() or file_sha256(skill_path) != manifest.get("skill_sha256"):
        raise RunContractError("skill contract bytes changed after run creation")
    if (
        not resource_path.is_file()
        or file_sha256(resource_path) != manifest.get("resource_manifest_sha256")
    ):
        raise RunContractError("resource manifest bytes changed after run creation")
    if skill_bundle_sha256(skill_path) != manifest.get("skill_bundle_sha256"):
        raise RunContractError("skill bundle bytes changed after run creation")
    snapshot = manifest.get("bundle_snapshot")
    if isinstance(snapshot, dict):
        execution_cli = Path(str(snapshot.get("execution_cli_path") or ""))
        if not execution_cli.is_file():
            raise RunContractError("run-scoped execution CLI is missing")
        source_skill = Path(str(snapshot.get("source_skill_path") or ""))
        installed_skill = HUB_DIR / "SKILL.md"
        if source_skill.resolve() == installed_skill.resolve():
            active_skill = Path(__file__).resolve().parent.parent / "SKILL.md"
            if (
                not active_skill.is_file()
                or skill_bundle_sha256(active_skill)
                != manifest.get("skill_bundle_sha256")
            ):
                raise RunContractError(
                    "installed skill changed; continue with the run-scoped CLI: "
                    f"{execution_cli}"
                )
    return manifest


def _validate_predecessors(manifest: dict[str, Any], stage: str) -> None:
    if stage not in STAGE_ORDER:
        raise RunContractError(f"unknown stage: {stage}")
    stage_index = STAGE_ORDER.index(stage)
    for predecessor in STAGE_ORDER[:stage_index]:
        status = manifest.get("stages", {}).get(predecessor, {}).get("status")
        if status not in STAGE_TERMINAL:
            raise RunContractError(
                f"stage {stage} requires terminal predecessor {predecessor}"
            )


def _record_artifact_in_manifest(
    manifest: dict[str, Any],
    name: str,
    artifact: Path,
    *,
    input_sha256: str | None,
    metadata: dict[str, Any] | None,
    current: datetime,
) -> bool:
    digest = file_sha256(artifact)
    existing = manifest.setdefault("artifacts", {}).get(name)
    if existing:
        same_path = (
            Path(str(existing.get("artifact_path") or "")).resolve()
            == artifact.resolve()
        )
        if (
            existing.get("artifact_sha256") != digest
            or not same_path
            or existing.get("input_sha256") != input_sha256
        ):
            raise RunContractError(f"run artifact {name} is immutable once recorded")
        return False
    manifest["artifacts"][name] = {
        "artifact_path": str(artifact.resolve()),
        "artifact_sha256": digest,
        "input_sha256": input_sha256,
        "recorded_at": current.isoformat(),
        "metadata": deepcopy(metadata or {}),
    }
    manifest["events"].append(
        {
            "stage": f"artifact:{name}",
            "status": "completed",
            "recorded_at": current.isoformat(),
        }
    )
    return True


def record_run_artifact(
    manifest_path: str | Path,
    name: str,
    artifact_path: str | Path,
    *,
    input_sha256: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if name not in {
        "focus_config",
        "history_snapshot",
        "history_review_slice",
        "candidate_pool",
        "supplement_request",
        "semantic_review_request",
        "red_team_request",
    }:
        raise RunContractError(f"unsupported run artifact: {name}")
    path = Path(manifest_path)
    artifact = Path(artifact_path)
    if not artifact.is_file():
        raise RunContractError(f"run artifact not found: {artifact}")
    with locked_manifest(path) as (manifest, expected_sha256):
        before = {field: deepcopy(manifest[field]) for field in IMMUTABLE_FIELDS}
        current = _aware_now(manifest["timezone"], now)
        changed = _record_artifact_in_manifest(
            manifest,
            name,
            artifact,
            input_sha256=input_sha256,
            metadata=metadata,
            current=current,
        )
        for field, expected in before.items():
            if manifest[field] != expected:
                raise RunContractError(f"immutable run field changed: {field}")
        if changed:
            commit_manifest(path, manifest, expected_sha256)
        return manifest


def _record_stage_in_manifest(
    manifest: dict[str, Any],
    stage: str,
    status: str,
    *,
    artifact_path: str | Path | None,
    input_sha256: str | None,
    metadata: dict[str, Any] | None,
    current: datetime,
) -> None:
    existing_stage = manifest.get("stages", {}).get(stage, {})
    if existing_stage.get("status") in STAGE_FINAL:
        raise RunContractError(f"stage {stage} is immutable once terminal/final")
    _validate_predecessors(manifest, stage)
    allowed_statuses = STAGE_FINAL | {"running"}
    if status not in allowed_statuses:
        raise RunContractError(f"invalid stage status: {status}")
    stage_data: dict[str, Any] = {
        "status": status,
        "recorded_at": current.isoformat(),
    }
    if artifact_path is not None:
        artifact = Path(artifact_path)
        if not artifact.is_file():
            raise RunContractError(f"stage artifact not found: {artifact}")
        stage_data["artifact_path"] = str(artifact.resolve())
        stage_data["artifact_sha256"] = file_sha256(artifact)
    elif status in {"completed", "degraded"}:
        raise RunContractError(f"stage {stage} requires an artifact")
    if input_sha256:
        stage_data["input_sha256"] = input_sha256
    if metadata:
        stage_data["metadata"] = deepcopy(metadata)
    manifest["stages"][stage] = stage_data
    event: dict[str, Any] = {
        "stage": stage,
        "status": status,
        "recorded_at": current.isoformat(),
    }
    if metadata:
        event["metadata"] = deepcopy(metadata)
    manifest["events"].append(event)


def record_stage(
    manifest_path: str | Path,
    stage: str,
    status: str,
    *,
    artifact_path: str | Path | None = None,
    input_sha256: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    path = Path(manifest_path)
    with locked_manifest(path) as (manifest, expected_sha256):
        before = {field: deepcopy(manifest[field]) for field in IMMUTABLE_FIELDS}
        current = _aware_now(manifest["timezone"], now)
        _record_stage_in_manifest(
            manifest,
            stage,
            status,
            artifact_path=artifact_path,
            input_sha256=input_sha256,
            metadata=metadata,
            current=current,
        )
        for field, expected in before.items():
            if manifest[field] != expected:
                raise RunContractError(f"immutable run field changed: {field}")
        commit_manifest(path, manifest, expected_sha256)
        return manifest


def _usage_budget_tokens(usage: dict[str, Any]) -> int:
    total = _integer(
        usage.get("total_tokens"),
        "execution telemetry total_tokens",
        minimum=0,
    )
    cache_read = _integer(
        usage.get("cache_read_tokens", 0),
        "execution telemetry cache_read_tokens",
        minimum=0,
    )
    cache_write = _integer(
        usage.get("cache_write_tokens", 0),
        "execution telemetry cache_write_tokens",
        minimum=0,
    )
    derived = total - cache_read - cache_write
    if derived < 0:
        raise RunContractError("execution telemetry token counters are inconsistent")
    declared = usage.get("budget_tokens")
    if declared is not None and (
        not isinstance(declared, int)
        or isinstance(declared, bool)
        or declared != derived
    ):
        raise RunContractError("execution telemetry budget_tokens mismatch")
    return derived


def _refresh_telemetry_summary(manifest: dict[str, Any]) -> None:
    telemetry = manifest.setdefault("telemetry", {})
    executions = telemetry.setdefault("executions", {})
    state = _execution_budget_state(manifest)
    summed_duration_seconds = round(
        sum(float(item["duration_seconds"]) for item in executions.values()),
        3,
    )
    failed_invocations = sum(
        1
        for item in executions.values()
        if item["status"] in {"degraded_timeout", "failed", "cancelled"}
    )
    exceeded_dimensions: list[str] = []
    if int(state["accounted_tokens"]) > 250000:
        exceeded_dimensions.append("tokens")
    if float(state["accounted_cost_usd"]) > 3.0:
        exceeded_dimensions.append("cost_usd")
    telemetry["summary"] = {
        "total_tokens": int(state["raw_total_tokens"]),
        "budget_tokens": int(state["actual_tokens"]),
        "token_meter": "total_minus_cache_read_minus_cache_write",
        "total_cost_usd": float(state["actual_cost_usd"]),
        "reserved_tokens": int(state["reserved_tokens"]),
        "reserved_cost_usd": float(state["reserved_cost_usd"]),
        "accounted_total_tokens": int(state["accounted_tokens"]),
        "accounted_total_cost_usd": float(state["accounted_cost_usd"]),
        "summed_duration_seconds": summed_duration_seconds,
        "invocation_count": len(executions),
        "active_reservation_count": sum(
            1
            for record in telemetry.get("reservations", {}).values()
            if record.get("status") == "reserved"
        ),
        "failed_invocations": failed_invocations,
        "normal_run_token_ceiling": 250000,
        "normal_run_cost_usd_ceiling": 3.0,
        "budget_status": "exceeded" if exceeded_dimensions else "within_budget",
        "exceeded_dimensions": exceeded_dimensions,
    }


def record_execution_telemetry(
    manifest_path: str | Path,
    telemetry_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    path = Path(manifest_path)
    artifact = Path(telemetry_path).resolve()
    payload = load_json(artifact, {})
    if payload.get("contract_version") != "pih-execution-telemetry/1.0":
        raise RunContractError("invalid execution telemetry contract_version")
    stage = str(payload.get("stage") or "")
    invocation_id = str(payload.get("invocation_id") or "")
    status = str(payload.get("status") or "")
    if stage not in STAGE_ORDER:
        raise RunContractError("execution telemetry stage is invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", invocation_id):
        raise RunContractError("execution telemetry invocation_id is invalid")
    if status not in {
        "completed",
        "degraded",
        "degraded_timeout",
        "failed",
        "cancelled",
    }:
        raise RunContractError("execution telemetry status is invalid")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise RunContractError("execution telemetry usage is required")
    for field in (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
        "assistant_messages",
        "tool_results",
        "tool_errors",
    ):
        value = usage.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RunContractError(f"execution telemetry {field} is invalid")
    budget_tokens = _usage_budget_tokens(usage)
    usage["budget_tokens"] = budget_tokens
    cost = usage.get("cost_usd")
    duration = payload.get("duration_seconds")
    if (
        not isinstance(cost, (int, float))
        or isinstance(cost, bool)
        or not math.isfinite(float(cost))
        or float(cost) < 0
    ):
        raise RunContractError("execution telemetry cost_usd is invalid")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(float(duration))
        or float(duration) < 0
    ):
        raise RunContractError("execution telemetry duration_seconds is invalid")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RunContractError("execution telemetry sources are required")
    source_sha256s: list[str] = []
    for source in sources:
        if not isinstance(source, dict) or not re.fullmatch(
            r"[0-9a-f]{64}", str(source.get("sha256") or "")
        ):
            raise RunContractError("execution telemetry source hash is invalid")
        source_sha256s.append(str(source["sha256"]))
    if len(source_sha256s) != len(set(source_sha256s)):
        raise RunContractError("execution telemetry contains duplicate sources")
    with locked_manifest(path) as (manifest, expected_sha256):
        if payload.get("run_id") != manifest.get("run_id"):
            raise RunContractError("execution telemetry run_id mismatch")
        if artifact.parent != Path(manifest["run_dir"]).resolve():
            raise RunContractError("execution telemetry must be inside the run directory")
        key = f"{stage}:{invocation_id}"
        telemetry = manifest.setdefault("telemetry", {})
        executions = telemetry.setdefault("executions", {})
        record = {
            "artifact_path": str(artifact),
            "artifact_sha256": file_sha256(artifact),
            "stage": stage,
            "invocation_id": invocation_id,
            "status": status,
            "usage": deepcopy(usage),
            "duration_seconds": round(float(duration), 3),
            "source_sha256s": sorted(source_sha256s),
        }
        existing = executions.get(key)
        if existing is not None:
            if existing == record:
                return manifest
            raise RunContractError("execution telemetry invocation is immutable")
        reservations = telemetry.setdefault("reservations", {})
        reservation = reservations.get(key)
        if not isinstance(reservation, dict):
            raise RunContractError(
                "execution telemetry requires a matching budget reservation"
            )
        if reservation.get("status") != "reserved":
            raise RunContractError("execution budget reservation is already settled")
        prior_source_hashes = {
            str(source_hash)
            for execution in executions.values()
            if isinstance(execution, dict)
            for source_hash in execution.get("source_sha256s", [])
        }
        if prior_source_hashes.intersection(source_sha256s):
            raise RunContractError(
                "execution telemetry source is already bound to another invocation"
            )
        executions[key] = record
        reservation.update(
            {
                "status": "settled",
                "settled_at": _aware_now(manifest["timezone"], now).isoformat(),
                "telemetry_artifact_sha256": record["artifact_sha256"],
                "actual_tokens": budget_tokens,
                "raw_total_tokens": usage["total_tokens"],
                "actual_cost_usd": round(float(cost), 6),
            }
        )
        _refresh_telemetry_summary(manifest)
        current = _aware_now(manifest["timezone"], now)
        manifest["events"].append(
            {
                "stage": stage,
                "status": "telemetry_registered",
                "recorded_at": current.isoformat(),
                "metadata": {
                    "invocation_id": invocation_id,
                    "execution_status": status,
                    "total_tokens": usage["total_tokens"],
                    "budget_tokens": budget_tokens,
                    "cost_usd": float(cost),
                    "duration_seconds": round(float(duration), 3),
                    "run_budget_status": telemetry["summary"]["budget_status"],
                    "active_reservation_count": telemetry["summary"][
                        "active_reservation_count"
                    ],
                },
            }
        )
        commit_manifest(path, manifest, expected_sha256)
        return manifest


def expire_execution_reservation(
    manifest_path: str | Path,
    stage: str,
    invocation_id: str,
    *,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if stage not in STAGE_ORDER or not str(reason).strip():
        raise RunContractError("reservation expiry stage or reason is invalid")
    path = Path(manifest_path)
    with locked_manifest(path) as (manifest, expected_sha256):
        key = f"{stage}:{invocation_id}"
        reservation = (
            manifest.setdefault("telemetry", {})
            .setdefault("reservations", {})
            .get(key)
        )
        if not isinstance(reservation, dict):
            raise RunContractError("execution budget reservation is missing")
        if reservation.get("status") == "expired":
            return manifest
        if reservation.get("status") != "reserved":
            raise RunContractError("only an active reservation can expire")
        current = _aware_now(manifest["timezone"], now)
        reservation.update(
            {
                "status": "expired",
                "expired_at": current.isoformat(),
                "expiry_reason": str(reason).strip(),
            }
        )
        _refresh_telemetry_summary(manifest)
        manifest["events"].append(
            {
                "stage": stage,
                "status": "reservation_expired",
                "recorded_at": current.isoformat(),
                "metadata": {
                    "invocation_id": invocation_id,
                    "reason": str(reason).strip(),
                },
            }
        )
        commit_manifest(path, manifest, expected_sha256)
        return manifest


def require_stage(
    manifest_path: str | Path,
    stage: str,
    statuses: set[str] | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    allowed = statuses or STAGE_TERMINAL
    actual = manifest.get("stages", {}).get(stage, {}).get("status")
    if actual not in allowed:
        raise RunContractError(f"stage {stage} is not terminal: {actual}")
    return manifest


def _execution_budget_state(manifest: dict[str, Any]) -> dict[str, float | int]:
    telemetry = manifest.get("telemetry", {})
    if not isinstance(telemetry, dict):
        raise RunContractError("execution telemetry registry is invalid")
    executions = telemetry.get("executions", {})
    reservations = telemetry.get("reservations", {})
    if not isinstance(executions, dict) or not isinstance(reservations, dict):
        raise RunContractError("execution telemetry registry is invalid")
    actual_tokens = 0
    raw_total_tokens = 0
    actual_cost_usd = 0.0
    for record in executions.values():
        if not isinstance(record, dict) or not isinstance(record.get("usage"), dict):
            raise RunContractError("execution telemetry record is invalid")
        usage = record["usage"]
        raw_total_tokens += _integer(
            usage.get("total_tokens"),
            "execution telemetry total_tokens",
            minimum=0,
        )
        actual_tokens += _usage_budget_tokens(usage)
        cost = usage.get("cost_usd")
        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise RunContractError("execution telemetry cost_usd is invalid")
        actual_cost_usd += float(cost)
    reserved_tokens = 0
    reserved_cost_usd = 0.0
    for record in reservations.values():
        if not isinstance(record, dict):
            raise RunContractError("execution budget reservation is invalid")
        if record.get("status") in {"settled", "expired"}:
            continue
        if record.get("status") != "reserved":
            raise RunContractError("execution budget reservation status is invalid")
        reserved_tokens += _integer(
            record.get("tokens"),
            "execution budget reserved tokens",
            minimum=1,
        )
        cost = record.get("cost_usd")
        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or not math.isfinite(float(cost))
            or float(cost) <= 0
        ):
            raise RunContractError("execution budget reserved cost_usd is invalid")
        reserved_cost_usd += float(cost)
    return {
        "actual_tokens": actual_tokens,
        "raw_total_tokens": raw_total_tokens,
        "actual_cost_usd": round(actual_cost_usd, 6),
        "reserved_tokens": reserved_tokens,
        "reserved_cost_usd": round(reserved_cost_usd, 6),
        "accounted_tokens": actual_tokens + reserved_tokens,
        "accounted_cost_usd": round(actual_cost_usd + reserved_cost_usd, 6),
    }


def _assert_execution_budget_allows_launch(
    manifest: dict[str, Any],
    *,
    reserved_tokens: int,
    reserved_cost_usd: float,
) -> dict[str, float | int]:
    if (
        not isinstance(reserved_tokens, int)
        or isinstance(reserved_tokens, bool)
        or reserved_tokens <= 0
    ):
        raise RunContractError("execution budget token reservation must be positive")
    if (
        not isinstance(reserved_cost_usd, (int, float))
        or isinstance(reserved_cost_usd, bool)
        or not math.isfinite(float(reserved_cost_usd))
        or float(reserved_cost_usd) <= 0
    ):
        raise RunContractError("execution budget cost reservation must be positive")
    state = _execution_budget_state(manifest)
    accounted_tokens = int(state["accounted_tokens"])
    accounted_cost_usd = float(state["accounted_cost_usd"])
    if (
        accounted_tokens >= 250000
        or accounted_cost_usd >= 3.0
        or accounted_tokens + reserved_tokens > 250000
        or accounted_cost_usd + float(reserved_cost_usd) > 3.0
    ):
        raise RunContractError(
            "execution budget exceeded or reservation unavailable; new agent launch is forbidden"
        )
    return {
        **state,
        "requested_tokens": reserved_tokens,
        "requested_cost_usd": round(float(reserved_cost_usd), 6),
        "remaining_cost_usd": round(3.0 - accounted_cost_usd, 6),
    }


def _reserve_execution_budget(
    manifest: dict[str, Any],
    reservations: list[dict[str, Any]],
    *,
    request_sha256: str,
    current: datetime,
) -> None:
    if not reservations:
        return
    total_tokens = sum(int(record["tokens"]) for record in reservations)
    total_cost_usd = sum(float(record["cost_usd"]) for record in reservations)
    _assert_execution_budget_allows_launch(
        manifest,
        reserved_tokens=total_tokens,
        reserved_cost_usd=total_cost_usd,
    )
    registry = manifest.setdefault("telemetry", {}).setdefault(
        "reservations", {}
    )
    for record in reservations:
        stage = str(record.get("stage") or "")
        invocation_id = str(record.get("invocation_id") or "")
        if stage not in STAGE_ORDER or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", invocation_id
        ):
            raise RunContractError("execution budget reservation identity is invalid")
        key = f"{stage}:{invocation_id}"
        reservation = {
            "stage": stage,
            "invocation_id": invocation_id,
            "request_sha256": request_sha256,
            "tokens": int(record["tokens"]),
            "cost_usd": round(float(record["cost_usd"]), 6),
            "status": "reserved",
            "reserved_at": current.isoformat(),
        }
        existing = registry.get(key)
        if existing is not None and existing != reservation:
            raise RunContractError("execution budget reservation is immutable")
        registry[key] = reservation


def _normalized_supplement_budget(gap: dict[str, Any]) -> dict[str, int]:
    budget = {
        "max_queries": _integer(
            gap.get("max_queries", 3),
            "supplement gap max_queries",
            minimum=1,
        ),
        "max_urls": _integer(
            gap.get("max_urls", 6),
            "supplement gap max_urls",
            minimum=1,
        ),
        "max_duration_seconds": _integer(
            gap.get("max_duration_seconds", 180),
            "supplement gap max_duration_seconds",
            minimum=1,
        ),
    }
    if budget["max_queries"] > 10:
        raise RunContractError("supplement gap max_queries cannot exceed 10")
    if budget["max_urls"] > 20:
        raise RunContractError("supplement gap max_urls cannot exceed 20")
    if not 30 <= budget["max_duration_seconds"] <= 900:
        raise RunContractError(
            "supplement gap max_duration_seconds must be between 30 and 900"
        )
    return budget


def _candidate_lane_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "candidate_ref": candidate_ref(str(candidate.get("url") or "")),
        "source_object_sha256": hashlib.sha256(
            canonical_json_bytes(candidate)
        ).hexdigest(),
    }
    for field in (
        "title",
        "url",
        "published_at",
        "published_at_source",
        "source",
        "source_type",
        "provisional_domain",
        "primary_domain",
        "access_check",
    ):
        if field in candidate:
            summary[field] = deepcopy(candidate[field])
    text = str(candidate.get("summary") or candidate.get("description") or "").strip()
    if text:
        summary["summary_excerpt"] = text[:500]
    return summary


def _lane_slice_candidates(
    candidate_pool: dict[str, Any],
    lane: str,
    focus: dict[str, Any],
) -> list[dict[str, Any]]:
    items = candidate_pool.get("items")
    if not isinstance(items, list):
        raise RunContractError("candidate pool items must be a list")
    domain_by_lane = {
        "TechRadar": "technology",
        "HealthcareRadar": "healthcare_digital",
    }
    required_domain = domain_by_lane.get(lane)
    configured_lane = (
        focus.get("coverage_policy", {}).get("lanes", {}).get(lane, {})
        if isinstance(focus, dict)
        else {}
    )
    keywords = [
        str(value).casefold()
        for value in configured_lane.get("keywords", [])
        if str(value).strip()
    ] if isinstance(configured_lane, dict) else []
    selected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        domain = str(
            item.get("provisional_domain") or item.get("primary_domain") or ""
        )
        explicit_lane = str(item.get("lane") or "")
        text = " ".join(
            str(item.get(field) or "")
            for field in ("title", "summary", "description", "fact")
        ).casefold()
        matches = (
            explicit_lane == lane
            or (required_domain is not None and domain == required_domain)
            or (required_domain is None and any(keyword in text for keyword in keywords))
        )
        if matches:
            selected.append(_candidate_lane_summary(item))
    return selected


def _build_supplement_launch_plan(
    execution_packets: list[dict[str, Any]],
    *,
    max_workers: int,
) -> list[dict[str, Any]]:
    if not 1 <= max_workers <= 8:
        raise RunContractError("max_supplement_workers must be between 1 and 8")
    plan: list[dict[str, Any]] = []
    wave_ranges = (
        [(0, 1)]
        + [
            (start, min(start + max_workers, len(execution_packets)))
            for start in range(1, len(execution_packets), max_workers)
        ]
        if execution_packets
        else []
    )
    for start, end in wave_ranges:
        workers = []
        for packet_index, packet in enumerate(
            execution_packets[start:end],
            start=start,
        ):
            gap_id = str(packet["assigned_gap_ids"][0])
            workers.append(
                {
                    "packet_index": packet_index,
                    "gap_id": gap_id,
                    "lane": str(packet["assigned_lanes"][0]),
                    "task_message": str(packet["task_message"]),
                    "timeout_ms": (
                        int(packet["execution_budget"]["max_duration_seconds"])
                        + int(packet["finalization"]["grace_seconds"])
                    )
                    * 1000,
                    "tool_budget": deepcopy(packet["tool_budget"]),
                    "token_budget": int(packet["usage_budget"]["tokens"]),
                    "cost_budget_usd": float(
                        packet["usage_budget"]["cost_usd"]
                    ),
                }
            )
        wave_number = len(plan) + 1
        plan.append(
            {
                "wave": wave_number,
                "mode": "canary" if wave_number == 1 else "fanout",
                "stop_on_infrastructure_failure": wave_number == 1,
                "workers": workers,
            }
        )
    return plan


def build_supplement_request(
    manifest_path: str | Path,
    gaps: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    manifest = require_stage(manifest_path, "baseline", {"completed", "degraded"})
    baseline_sha = manifest["stages"]["baseline"].get("artifact_sha256")
    if not baseline_sha:
        raise RunContractError("baseline artifact hash is missing")
    candidate_record = manifest.get("artifacts", {}).get("candidate_pool")
    if not isinstance(candidate_record, dict):
        raise RunContractError("candidate_pool artifact must be recorded before supplements")
    candidate_path = Path(str(candidate_record.get("artifact_path") or ""))
    if (
        not candidate_path.is_file()
        or candidate_record.get("artifact_sha256") != file_sha256(candidate_path)
    ):
        raise RunContractError("candidate_pool artifact bytes changed")
    if manifest.get("artifacts", {}).get("supplement_request") is not None:
        raise RunContractError("supplement request is immutable once registered")
    normalized_gaps = []
    seen: set[str] = set()
    for gap in gaps:
        gap_id = str(gap.get("gap_id") or "").strip()
        lane = str(gap.get("lane") or "").strip()
        query_scope = str(gap.get("query_scope") or "").strip()
        if not gap_id or not lane or not query_scope or gap_id in seen:
            raise RunContractError("each supplement gap requires a unique gap_id, lane and query_scope")
        seen.add(gap_id)
        max_turns = _integer(
            gap.get("max_turns", 3),
            "supplement gap max_turns",
            minimum=1,
        )
        halt_condition = str(
            gap.get("halt_condition") or "直接来源核验完成或无增量"
        ).strip()
        if not 1 <= max_turns <= 10 or not halt_condition:
            raise RunContractError("supplement gap max_turns or halt_condition is invalid")
        budget = _normalized_supplement_budget(gap)
        verify_bound_candidates = gap.get("verify_bound_candidates", False)
        if not isinstance(verify_bound_candidates, bool):
            raise RunContractError("supplement gap verify_bound_candidates must be boolean")
        normalized_gaps.append(
            {
                "gap_id": gap_id,
                "lane": lane,
                "query_scope": query_scope,
                "max_turns": max_turns,
                "halt_condition": halt_condition,
                "verify_bound_candidates": verify_bound_candidates,
                **budget,
            }
        )
    if not normalized_gaps:
        raise RunContractError("supplement request requires at least one gap")
    current = _aware_now(manifest["timezone"], now)
    run_dir = Path(manifest["run_dir"]).resolve()
    bundle_root = (
        Path(manifest["skill_path"]).resolve().parent
        if isinstance(manifest.get("bundle_snapshot"), dict)
        else HUB_DIR
    )
    prompt_config_path = bundle_root / "references" / "subagent_prompts.json"
    request_path = run_dir / "supplement_request.json"
    prompt_config = load_json(prompt_config_path, {})
    required_packet_fields = (
        prompt_config.get("execution_policy", {})
        .get("context_transfer", {})
        .get("required_fields")
        if isinstance(prompt_config, dict)
        else None
    )
    if not isinstance(required_packet_fields, list) or not required_packet_fields:
        raise RunContractError("supplement execution packet contract is missing")
    observability = (
        prompt_config.get("execution_policy", {}).get("observability", {})
    )
    supplement_token_budget = _integer(
        observability.get("supplement_token_budget_per_gap", 30000),
        "supplement token budget",
        minimum=1,
    )
    finalization_grace_seconds = _integer(
        observability.get("supplement_finalization_grace_seconds", 60),
        "supplement finalization grace seconds",
        minimum=1,
    )
    supplement_tool_budget_soft = _integer(
        observability.get("supplement_tool_budget_soft", 8),
        "supplement tool budget soft",
        minimum=1,
    )
    supplement_tool_budget_hard = _integer(
        observability.get("supplement_tool_budget_hard", 12),
        "supplement tool budget hard",
        minimum=supplement_tool_budget_soft,
    )
    downstream_headroom_tokens = _integer(
        observability.get("downstream_headroom_tokens", 70000),
        "downstream headroom tokens",
        minimum=1,
    )
    downstream_headroom_cost_usd = float(
        observability.get("downstream_headroom_cost_usd", 1.0)
    )
    if (
        not math.isfinite(downstream_headroom_cost_usd)
        or downstream_headroom_cost_usd <= 0
    ):
        raise RunContractError("downstream headroom cost is invalid")
    helper_path = bundle_root / "scripts" / "supplement_agent.py"
    if not helper_path.is_file():
        raise RunContractError("supplement agent helper is missing")
    current_budget = _execution_budget_state(manifest)
    available_cost_usd = round(
        3.0 - float(current_budget["accounted_cost_usd"]),
        6,
    )
    if available_cost_usd <= 0:
        raise RunContractError(
            "execution budget exceeded or reservation unavailable; new agent launch is forbidden"
        )
    supplement_cost_pool = round(
        available_cost_usd - downstream_headroom_cost_usd,
        6,
    )
    if supplement_cost_pool <= 0:
        raise RunContractError(
            "execution budget cannot preserve downstream review cost headroom"
        )
    _assert_execution_budget_allows_launch(
        manifest,
        reserved_tokens=(
            supplement_token_budget * len(normalized_gaps)
            + downstream_headroom_tokens
        ),
        reserved_cost_usd=available_cost_usd,
    )
    cost_units = int(round(supplement_cost_pool * 1_000_000))
    base_cost_units, extra_cost_units = divmod(cost_units, len(normalized_gaps))
    per_gap_cost_budgets = [
        (base_cost_units + int(index < extra_cost_units)) / 1_000_000
        for index in range(len(normalized_gaps))
    ]
    candidate_pool = load_json(candidate_path, {})
    focus_record = manifest.get("artifacts", {}).get("focus_config")
    focus = (
        load_json(Path(str(focus_record.get("artifact_path"))), {})
        if isinstance(focus_record, dict) and focus_record.get("artifact_path")
        else {}
    )
    history_record = manifest.get("artifacts", {}).get("history_snapshot")
    history_snapshot_sha256 = (
        str(history_record.get("artifact_sha256") or "")
        if isinstance(history_record, dict)
        else ""
    )
    execution_packets = []
    for gap_index, gap in enumerate(normalized_gaps):
        safe_gap_id = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", gap["gap_id"])
        if safe_gap_id is None:
            raise RunContractError("supplement gap_id is not safe for an output path")
        final_path = run_dir / f"supplement_{gap['gap_id']}.json"
        draft_path = run_dir / f"supplement_{gap['gap_id']}.draft.json"
        progress_state_path = run_dir / f"supplement_{gap['gap_id']}_progress_state.json"
        lane_slice_path = run_dir / f"supplement_{gap['gap_id']}_lane_slice.json"
        lane_candidates = _lane_slice_candidates(candidate_pool, gap["lane"], focus)
        required_bound_candidate_ids = (
            [
                str(candidate.get("candidate_ref") or "")
                for candidate in lane_candidates[: int(gap["max_urls"])]
                if str(candidate.get("candidate_ref") or "")
            ]
            if gap["verify_bound_candidates"]
            else []
        )
        lane_slice = {
            "contract_version": "supplement-lane-slice/1.0",
            "run_id": manifest["run_id"],
            "gap": deepcopy(gap),
            "window": deepcopy(manifest["window"]),
            "baseline_sha256": str(baseline_sha),
            "candidate_pool_sha256": str(candidate_record["artifact_sha256"]),
            "history_snapshot_sha256": history_snapshot_sha256,
            "source_candidate_count": len(candidate_pool.get("items", [])),
            "candidates": lane_candidates,
            "required_bound_candidate_ids": required_bound_candidate_ids,
        }
        atomic_dump_json(lane_slice_path, lane_slice)
        lane_slice_binding = {
            "path": str(lane_slice_path.resolve()),
            "sha256": file_sha256(lane_slice_path),
        }
        packet = {
            "contract_version": "supplement-execution-packet/1.1",
            "self_contained": True,
            "skill_path": str(Path(manifest["skill_path"]).resolve()),
            "prompt_config_path": str(prompt_config_path.resolve()),
            "prompt_config_sha256": file_sha256(prompt_config_path),
            "run_manifest_path": str(Path(manifest_path).resolve()),
            "registered_request_path": str(request_path.resolve()),
            "bound_input_paths": {"lane_slice": deepcopy(lane_slice_binding)},
            "lane_slice": deepcopy(lane_slice_binding),
            "assigned_gap_ids": [gap["gap_id"]],
            "assigned_lanes": [gap["lane"]],
            "output_paths": {
                "result": str(final_path.resolve()),
                "draft": str(draft_path.resolve()),
            },
            "output_path_by_gap": {gap["gap_id"]: str(final_path.resolve())},
            "write_authorization": {
                "mode": "draft_only_parent_finalizer",
                "final_paths": [str(final_path.resolve())],
                "draft_paths": [str(draft_path.resolve())],
                "agent_allowed_paths": [str(draft_path.resolve())],
                "forbid_other_writes": True,
            },
            "per_gap_max_turns": {gap["gap_id"]: gap["max_turns"]},
            "per_gap_halt_condition": {gap["gap_id"]: gap["halt_condition"]},
            "execution_budget": {
                "max_queries": gap["max_queries"],
                "max_urls": gap["max_urls"],
                "max_duration_seconds": gap["max_duration_seconds"],
            },
            "finalization": {
                "grace_seconds": finalization_grace_seconds,
                "result_completed_at_semantics": "source_check_completed",
            },
            "tool_budget": {
                "soft": supplement_tool_budget_soft,
                "hard": supplement_tool_budget_hard,
                "block": "*",
            },
            "agent_helper": {
                "path": str(helper_path),
                "sha256": file_sha256(helper_path),
                "context_command": (
                    "python -X utf8 scripts/supplement_agent.py context "
                    "--request <supplement_request.json> --gap-id <gap_id>"
                ),
                "verify_bound_command": (
                    "python -X utf8 scripts/supplement_agent.py verify-bound "
                    "--request <supplement_request.json> --gap-id <gap_id> --write-draft"
                ),
                "finalize_command": (
                    "python -X utf8 scripts/supplement_agent.py finalize "
                    "--request <supplement_request.json> --gap-id <gap_id>"
                ),
            },
            "task_message": (
                f"Execute only PIH supplement gap {gap['gap_id']} for lane {gap['lane']}. "
                f"Work in {Path(manifest['skill_path']).resolve().parent}. "
                f"First run: python -X utf8 scripts/supplement_agent.py context "
                f"--request \"{request_path.resolve()}\" --gap-id \"{gap['gap_id']}\". "
                "Use only its compact context; do not read the full request, prompt config, "
                "candidate pool, history snapshot, other lane files, or script source. "
                "Send supplement_progress seq=1 phase=input_validated through the existing "
                "contact_supervisor channel after context succeeds; it is a message, not a tool name. "
                "Check only the assigned sources/query scope within the query, URL, turn, and "
                "source-duration budgets. When context lists required_bound_candidate_urls, attempt "
                "each one before open search and preserve every outcome in access_log. Re-register "
                "each bound candidate that passes access, date, domain, and source-quality gates in "
                "candidates with the same candidate_id and URL; the deterministic finalizer supplies "
                "event_id. Fast helper: you may run python -X utf8 scripts/supplement_agent.py verify-bound "
                f"--request \"{request_path.resolve()}\" --gap-id \"{gap['gap_id']}\" --write-draft "
                "to quickly verify bound candidates and write the initial draft. "
                "Use actual clock values, never rounded or future timestamps. Record "
                "completed_at when source checking ends, then "
                "send supplement_progress seq=2 phase=source_checked through contact_supervisor "
                "and stop all research. "
                "Write only the dynamic fields listed by the helper to its draft_path. Then run "
                f"python -X utf8 scripts/supplement_agent.py finalize --request "
                f"\"{request_path.resolve()}\" --gap-id \"{gap['gap_id']}\". "
                "On success return only draft_ready path=<absolute path> sha256=<sha256>."
            ),
            "progress": {
                "review_kind": "supplement",
                "progress_id": gap["gap_id"],
                "state_path": str(progress_state_path.resolve()),
                "milestone_limit": 2,
            },
            "usage_budget": {
                "tokens": supplement_token_budget,
                "cost_usd": per_gap_cost_budgets[gap_index],
            },
            "publication": {
                "mode": "validated_parent_atomic_replace",
                "artifact_ready_message": "draft_ready path=<draft_path> sha256=<sha256>",
                "finalizer_command": (
                    "python -X utf8 scripts/run_daily.py finalize-supplement "
                    "--manifest <run_manifest.json> --request <supplement_request.json> "
                    "--draft <draft-1.json> [--draft <draft-2.json>]"
                ),
            },
        }
        missing_fields = sorted(set(required_packet_fields) - set(packet))
        if missing_fields:
            raise RunContractError(
                f"supplement execution packet missing declared fields: {missing_fields}"
            )
        execution_packets.append(packet)
    max_workers = _integer(
        prompt_config.get("execution_policy", {})
        .get("parallelism", {})
        .get("max_supplement_workers", 3),
        "max_supplement_workers",
        minimum=1,
    )
    request = {
        "contract_version": "supplement-request/1.1",
        "run_id": manifest["run_id"],
        "baseline_sha256": baseline_sha,
        "candidate_pool_sha256": candidate_record["artifact_sha256"],
        "gap_ledger_sha256": hashlib.sha256(canonical_json_bytes(normalized_gaps)).hexdigest(),
        "created_at": current.isoformat(),
        "gaps": normalized_gaps,
        "execution_packets": execution_packets,
        "downstream_headroom": {
            "tokens": downstream_headroom_tokens,
            "cost_usd": downstream_headroom_cost_usd,
        },
        "launch_plan": _build_supplement_launch_plan(
            execution_packets,
            max_workers=max_workers,
        ),
    }
    atomic_dump_json(request_path, request)
    request_sha256 = file_sha256(request_path)
    manifest_file = Path(manifest_path)
    with locked_manifest(manifest_file) as (locked, expected_manifest_sha256):
        if locked.get("artifacts", {}).get("supplement_request") is not None:
            raise RunContractError("supplement request is immutable once registered")
        before = {field: deepcopy(locked[field]) for field in IMMUTABLE_FIELDS}
        _record_artifact_in_manifest(
            locked,
            "supplement_request",
            request_path,
            input_sha256=candidate_record["artifact_sha256"],
            metadata={"gap_count": len(normalized_gaps)},
            current=current,
        )
        _reserve_execution_budget(
            locked,
            [
                {
                    "stage": "supplemental",
                    "invocation_id": str(packet["assigned_gap_ids"][0]),
                    "tokens": int(packet["usage_budget"]["tokens"]),
                    "cost_usd": float(packet["usage_budget"]["cost_usd"]),
                }
                for packet in execution_packets
            ],
            request_sha256=str(request_sha256),
            current=current,
        )
        _refresh_telemetry_summary(locked)
        for field, expected in before.items():
            if locked[field] != expected:
                raise RunContractError(f"immutable run field changed: {field}")
        commit_manifest(manifest_file, locked, expected_manifest_sha256)
    return request_path, request


def _parse_aware_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RunContractError(f"{field} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RunContractError(f"{field} must be timezone-aware")
    return parsed


def normalize_published_at(value: Any, field: str = "published_at") -> str:
    """Return a canonical source-local YYYY-MM-DD publication date."""
    raw = str(value or "").strip()
    if STRICT_ISO_DATE_PATTERN.fullmatch(raw):
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError as exc:
            raise RunContractError(f"{field} must be a valid ISO date") from exc
    published_at = _parse_aware_datetime(raw, field)
    return published_at.date().isoformat()


def _validate_bound_candidate_source_type(
    item: dict[str, Any], matching_candidates: list[dict[str, Any]]
) -> None:
    """Validate source classification retained from exact-match evidence."""
    registered_types = {
        str(candidate.get("source_type"))
        for candidate in matching_candidates
        if candidate.get("source_type") in {"primary", "secondary"}
    }
    if registered_types and item.get("source_type") not in registered_types:
        raise RunContractError(
            "semantic receipt output source_type does not match an exact bound candidate"
        )


def _validated_semantic_candidate_event_id(
    candidate: dict[str, Any],
    index: int,
    *,
    path_prefix: str,
) -> str:
    required_identity_fields = {
        "key_version",
        "primary_domain",
        "actor",
        "action",
        "object",
        "event_date",
    }
    identity = candidate.get("event_identity")
    if (
        candidate.get("identity_quality") != "semantic"
        or not isinstance(identity, dict)
    ):
        raise RunContractError(
            f"{path_prefix} {index} requires semantic event identity"
        )
    if set(identity) != required_identity_fields or any(
        not str(identity.get(field) or "").strip()
        for field in required_identity_fields
    ):
        raise RunContractError(
            f"{path_prefix} {index} event_identity must contain exactly the semantic identity fields"
        )
    if str(candidate.get("primary_domain") or "") != str(
        identity["primary_domain"]
    ):
        raise RunContractError(
            f"{path_prefix} {index} primary_domain does not match event_identity"
        )
    try:
        derived_event_id = generate_event_id(identity)
    except ValueError as exc:
        raise RunContractError(
            f"{path_prefix} {index} event_identity is invalid"
        ) from exc
    if str(candidate.get("event_id") or "") != derived_event_id:
        raise RunContractError(
            f"{path_prefix} {index} event_id does not match event_identity"
        )
    return derived_event_id


def _validate_multi_independent_lineage(
    item: dict[str, Any],
    resolved_candidates: list[dict[str, Any]],
    validated_access: list[tuple[str, str, str, str, str, int | None]],
) -> None:
    """Validate evidence independence for a multi-source final item."""
    final_event_id = str(item.get("event_id") or "")
    source_names: set[str] = set()
    candidate_urls: set[str] = set()
    candidate_hosts: set[str] = set()
    for index, candidate in enumerate(resolved_candidates):
        derived_event_id = _validated_semantic_candidate_event_id(
            candidate,
            index,
            path_prefix="multi_independent candidate",
        )
        if derived_event_id != final_event_id:
            raise RunContractError(
                f"multi_independent candidate {index} event_id does not match final item.event_id"
            )

        source_name = re.sub(
            r"\s+", " ", str(candidate.get("source") or "").strip().casefold()
        )
        if source_name:
            source_names.add(source_name)
        normalized_url = normalize_url(str(candidate.get("url") or ""))
        host = (urlparse(normalized_url).hostname or "").casefold()
        if normalized_url:
            candidate_urls.add(normalized_url)
        if host:
            candidate_hosts.add(host)

    if len(source_names) < 2:
        raise RunContractError(
            "multi_independent corroboration requires two distinct normalized sources"
        )
    if len(candidate_urls) < 2 or len(candidate_hosts) < 2:
        raise RunContractError(
            "multi_independent corroboration requires two distinct hosts and URLs"
        )
    verified_urls = {
        evidence[3]
        for evidence in validated_access
        if evidence[0] == "verified"
    }
    if not candidate_urls.issubset(verified_urls):
        raise RunContractError(
            "multi_independent corroboration requires verified receipt access for every candidate URL"
        )


def _utc_iso_datetime(value: Any, field: str) -> str:
    return _parse_aware_datetime(value, field).astimezone(timezone.utc).isoformat()


def _validate_request_evidence_time(
    value: Any,
    field: str,
    request_started_at: datetime,
    result_completed_at: datetime,
) -> str:
    instant = _parse_aware_datetime(value, field).astimezone(timezone.utc)
    started = request_started_at.astimezone(timezone.utc)
    completed = result_completed_at.astimezone(timezone.utc)
    if not started <= instant <= completed:
        raise RunContractError(f"{field} is outside the request-to-result window")
    return instant.isoformat()


def _validate_supplement_candidate(
    candidate: Any,
    index: int,
    window: dict[str, Any],
    request_started_at: datetime,
    result_completed_at: datetime,
) -> tuple[str, str, str, str, str, int | None]:
    if not isinstance(candidate, dict):
        raise RunContractError(f"supplement candidate {index} must be an object")
    for field in (
        "title",
        "url",
        "source",
        "published_at",
        "published_at_source",
        "retrieved_at",
        "primary_domain",
        "source_type",
        "summary",
    ):
        if not str(candidate.get(field) or "").strip():
            raise RunContractError(f"supplement candidate {index} missing {field}")
    if not str(candidate["url"]).startswith(("http://", "https://")):
        raise RunContractError(f"supplement candidate {index} has invalid url")
    if candidate["source_type"] not in {"primary", "secondary"}:
        raise RunContractError(f"supplement candidate {index} has invalid source_type")
    if candidate["primary_domain"] not in {"technology", "healthcare_digital"}:
        raise RunContractError(f"supplement candidate {index} has invalid primary_domain")
    try:
        published_day = date.fromisoformat(
            normalize_published_at(
                candidate["published_at"],
                f"supplement candidate {index}.published_at",
            )
        )
        start = date.fromisoformat(str(window["start"]))
        end = date.fromisoformat(str(window["end"]))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise RunContractError(
            f"supplement candidate {index}.published_at is invalid"
        ) from exc
    if not start <= published_day <= end:
        raise RunContractError(f"supplement candidate {index}.published_at is outside window")
    access = candidate.get("access_check")
    if not isinstance(access, dict) or access.get("status") != "verified":
        raise RunContractError(
            f"supplement candidate {index} requires a verified access_check"
        )
    for field in ("checked_at", "method", "requested_url", "final_url", "http_status"):
        if field not in access:
            raise RunContractError(
                f"supplement candidate {index}.access_check missing {field}"
            )
    checked_at = _validate_request_evidence_time(
        access.get("checked_at"),
        f"supplement candidate {index}.access_check.checked_at",
        request_started_at,
        result_completed_at,
    )
    if access.get("method") not in {"http_get", "browser", "api", "document"}:
        raise RunContractError(f"supplement candidate {index} has invalid access method")
    requested_url = str(access.get("requested_url") or "")
    if not requested_url.startswith(("http://", "https://")):
        raise RunContractError(f"supplement candidate {index} has invalid access requested_url")
    if normalize_url(requested_url) != normalize_url(str(candidate["url"])):
        raise RunContractError(
            f"supplement candidate {index} access requested_url does not match candidate url"
        )
    if not str(access.get("final_url") or "").startswith(("http://", "https://")):
        raise RunContractError(f"supplement candidate {index} has invalid access final_url")
    if access.get("status") == "verified" and access.get("method") in {"http_get", "api"}:
        http_status = access.get("http_status")
        if not isinstance(http_status, int) or not 200 <= http_status < 400:
            raise RunContractError(
                f"supplement candidate {index} access status is not successful"
            )
    _validated_semantic_candidate_event_id(
        candidate,
        index,
        path_prefix="supplement candidate",
    )
    _validate_request_evidence_time(
        candidate["retrieved_at"],
        f"supplement candidate {index}.retrieved_at",
        request_started_at,
        result_completed_at,
    )
    return (
        "verified",
        checked_at,
        str(access["method"]),
        normalize_url(str(access["requested_url"])),
        normalize_url(str(access["final_url"])),
        access.get("http_status"),
    )


def _validate_access_log_entry(
    access: Any,
    index: int,
    *,
    path_prefix: str = "supplement result access_log",
    require_machine_classification: bool = False,
) -> tuple[str, str, str, str, str, int | None]:
    path = f"{path_prefix}[{index}]"
    if not isinstance(access, dict):
        raise RunContractError(f"{path} must be an object")
    status = access.get("status")
    if status not in {"verified", "blocked"}:
        raise RunContractError(f"{path}.status is invalid")
    checked_at = _utc_iso_datetime(access.get("checked_at"), f"{path}.checked_at")
    method = str(access.get("method") or "")
    if method not in {"http_get", "browser", "api", "document"}:
        raise RunContractError(f"{path}.method is invalid")
    requested_url = str(access.get("requested_url") or "")
    if not requested_url.startswith(("http://", "https://")):
        raise RunContractError(f"{path}.requested_url is invalid")
    final_url = str(access.get("final_url") or "")
    if not final_url.startswith(("http://", "https://")):
        raise RunContractError(f"{path}.final_url is invalid")
    http_status = access.get("http_status")
    if http_status is not None and (
        not isinstance(http_status, int) or isinstance(http_status, bool)
    ):
        raise RunContractError(f"{path}.http_status is invalid")
    if status == "verified" and method in {"http_get", "api"} and (
        not isinstance(http_status, int) or not 200 <= http_status < 400
    ):
        raise RunContractError(f"{path}.http_status does not prove successful access")
    failure_class = access.get("failure_class")
    if failure_class is not None and failure_class not in {
        "none",
        "transient",
        "permanent",
    }:
        raise RunContractError(f"{path}.failure_class is invalid")
    error_code = access.get("error_code")
    if status == "verified" and failure_class not in {None, "none"}:
        raise RunContractError(f"{path}.failure_class conflicts with verified access")
    if status == "verified" and str(error_code or "").strip():
        raise RunContractError(f"{path}.error_code conflicts with verified access")
    if require_machine_classification and status == "verified" and failure_class != "none":
        raise RunContractError(f"{path}.failure_class must be none for verified access")
    if status == "blocked" and (
        failure_class not in {"transient", "permanent"}
        or not str(error_code or "").strip()
    ):
        raise RunContractError(
            f"{path} blocked access requires failure_class and error_code"
        )
    known_permanent_http = (
        isinstance(http_status, int)
        and not isinstance(http_status, bool)
        and 400 <= http_status < 500
        and http_status not in {408, 425, 429}
    )
    known_transient_http = (
        isinstance(http_status, int)
        and not isinstance(http_status, bool)
        and (http_status in {408, 425, 429} or 500 <= http_status < 600)
    )
    if status == "blocked" and known_permanent_http and failure_class != "permanent":
        raise RunContractError(f"{path}.failure_class must be permanent for HTTP {http_status}")
    if status == "blocked" and known_transient_http and failure_class != "transient":
        raise RunContractError(f"{path}.failure_class must be transient for HTTP {http_status}")
    return (
        status,
        checked_at,
        method,
        normalize_url(requested_url),
        normalize_url(final_url),
        http_status,
    )


def _validate_access_retry_policy(
    access_log: list[dict[str, Any]],
    *,
    seen_permanent_requests: set[str] | None = None,
) -> None:
    permanent_requests = (
        seen_permanent_requests if seen_permanent_requests is not None else set()
    )
    consecutive_host = ""
    consecutive_count = 0
    for index, access in enumerate(access_log):
        requested_url = normalize_url(str(access.get("requested_url") or ""))
        if requested_url in permanent_requests:
            raise RunContractError(
                f"supplement result access_log[{index}] retries a permanent failure"
            )
        http_status = access.get("http_status")
        declared_class = access.get("failure_class")
        is_permanent = access.get("status") == "blocked" and (
            declared_class == "permanent"
            or (
                isinstance(http_status, int)
                and 400 <= http_status < 500
                and http_status not in {408, 425, 429}
            )
        )
        if not is_permanent:
            consecutive_host = ""
            consecutive_count = 0
            continue
        permanent_requests.add(requested_url)
        host = urlparse(requested_url).hostname or ""
        if host == consecutive_host:
            consecutive_count += 1
        else:
            consecutive_host = host
            consecutive_count = 1
        if consecutive_count > 2:
            raise RunContractError(
                f"supplement result access_log[{index}] exceeds permanent failure host limit"
            )


_PATH_LOCAL_PERMANENT_ERROR_MARKERS = (
    "TLS",
    "SSL",
    "CERTIFICATE",
    "PROTOCOL",
    "CURL_EXIT",
)


def _is_path_local_permanent_failure(access: dict[str, Any]) -> bool:
    """Return whether a permanent failure is local to one access path.

    HTTP responses remain URL-global. Only transport failures without an HTTP
    response may be recovered once by another lane through a different method.
    """
    if (
        access.get("status") != "blocked"
        or access.get("failure_class") != "permanent"
        or access.get("http_status") is not None
    ):
        return False
    error_code = str(access.get("error_code") or "").upper()
    return any(marker in error_code for marker in _PATH_LOCAL_PERMANENT_ERROR_MARKERS)


def _validate_cross_lane_access_retry_policy(
    ordered_access: list[tuple[str, str, int, dict[str, Any]]],
    gap_lanes: dict[str, str],
) -> list[dict[str, Any]]:
    """Validate global retry policy with one bounded path-local recovery.

    A different lane may recover a local TLS/transport failure through a
    different access method. The original failure remains in coverage and the
    recovery is recorded in the aggregate. Authoritative HTTP failures,
    same-lane retries, same-method retries and repeated recovery attempts stay
    fail-closed.
    """
    permanent_requests: dict[str, tuple[str, dict[str, Any]]] = {}
    recovered_requests: set[str] = set()
    recoveries: list[dict[str, Any]] = []
    consecutive_host = ""
    consecutive_count = 0
    for index, (_checked_at, gap_id, _log_index, access) in enumerate(ordered_access):
        requested_url = normalize_url(str(access.get("requested_url") or ""))
        previous = permanent_requests.get(requested_url)
        if previous is not None:
            previous_gap, previous_access = previous
            is_bounded_recovery = (
                requested_url not in recovered_requests
                and gap_id != previous_gap
                and gap_lanes.get(gap_id) != gap_lanes.get(previous_gap)
                and access.get("status") == "verified"
                and access.get("method") != previous_access.get("method")
                and _is_path_local_permanent_failure(previous_access)
            )
            if not is_bounded_recovery:
                raise RunContractError(
                    f"supplement result access_log[{index}] retries a permanent failure"
                )
            recoveries.append(
                {
                    "requested_url": requested_url,
                    "failed_gap_id": previous_gap,
                    "failed_method": previous_access.get("method"),
                    "failure_code": previous_access.get("error_code"),
                    "recovery_gap_id": gap_id,
                    "recovery_method": access.get("method"),
                }
            )
            recovered_requests.add(requested_url)
            permanent_requests.pop(requested_url, None)
            consecutive_host = ""
            consecutive_count = 0
            continue
        if requested_url in recovered_requests:
            raise RunContractError(
                f"supplement result access_log[{index}] repeats a coordinated recovery"
            )
        http_status = access.get("http_status")
        declared_class = access.get("failure_class")
        is_permanent = access.get("status") == "blocked" and (
            declared_class == "permanent"
            or (
                isinstance(http_status, int)
                and not isinstance(http_status, bool)
                and 400 <= http_status < 500
                and http_status not in {408, 425, 429}
            )
        )
        if not is_permanent:
            consecutive_host = ""
            consecutive_count = 0
            continue
        permanent_requests[requested_url] = (gap_id, deepcopy(access))
        host = urlparse(requested_url).hostname or ""
        if host == consecutive_host:
            consecutive_count += 1
        else:
            consecutive_host = host
            consecutive_count = 1
        if consecutive_count > 2:
            raise RunContractError(
                f"supplement result access_log[{index}] exceeds permanent failure host limit"
            )
    return recoveries


def register_supplement_results(
    manifest_path: str | Path,
    request_path: str | Path,
    result_paths: Sequence[str | Path],
    *,
    publish_drafts: bool = False,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    manifest = require_stage(manifest_path, "baseline", {"completed", "degraded"})
    request_file = Path(request_path)
    request = load_json(request_file, {})
    request_version = request.get("contract_version")
    if request_version not in {"supplement-request/1.0", "supplement-request/1.1"}:
        raise RunContractError("invalid supplement request")
    bounded_request = request_version == "supplement-request/1.1"
    if request.get("run_id") != manifest["run_id"]:
        raise RunContractError("supplement request run_id mismatch")
    baseline_sha = manifest["stages"]["baseline"].get("artifact_sha256")
    if request.get("baseline_sha256") != baseline_sha:
        raise RunContractError("supplement request baseline_sha256 mismatch")
    request_record = manifest.get("artifacts", {}).get("supplement_request")
    if not isinstance(request_record, dict):
        raise RunContractError("supplement request is not registered in the run manifest")
    if (
        Path(str(request_record.get("artifact_path") or "")).resolve() != request_file.resolve()
        or request_record.get("artifact_sha256") != file_sha256(request_file)
    ):
        raise RunContractError("supplement request does not match the registered artifact")
    candidate_record = manifest.get("artifacts", {}).get("candidate_pool", {})
    candidate_sha = candidate_record.get("artifact_sha256")
    if request.get("candidate_pool_sha256") != candidate_sha:
        raise RunContractError("supplement request candidate_pool_sha256 mismatch")
    candidate_path = Path(str(candidate_record.get("artifact_path") or ""))
    if (
        not candidate_path.is_file()
        or candidate_sha != file_sha256(candidate_path)
    ):
        raise RunContractError("candidate_pool artifact bytes changed")
    candidate_pool = load_json(candidate_path, {})
    candidate_items = candidate_pool.get("items")
    if not isinstance(candidate_items, list):
        raise RunContractError("candidate pool items must be a list")
    candidate_object_hashes = {
        hashlib.sha256(canonical_json_bytes(item)).hexdigest()
        for item in candidate_items
        if isinstance(item, dict)
    }
    expected_gap_ledger = hashlib.sha256(
        canonical_json_bytes(request.get("gaps", []))
    ).hexdigest()
    if request.get("gap_ledger_sha256") != expected_gap_ledger:
        raise RunContractError("supplement request gap ledger hash mismatch")
    request_sha = file_sha256(request_file)
    gaps = {str(gap["gap_id"]): gap for gap in request.get("gaps", [])}
    if not gaps:
        raise RunContractError("supplement request has no gaps")
    current = _aware_now(manifest["timezone"], now)
    request_started_at = _parse_aware_datetime(
        request.get("created_at"), "supplement request created_at"
    )
    if current < request_started_at:
        raise RunContractError("supplement registration cannot precede request creation")
    packet_paths: dict[str, Path] = {}
    packet_draft_paths: dict[str, Path] = {}
    packet_lane_slices: dict[str, Path] = {}
    execution_packets = request.get("execution_packets")
    if not isinstance(execution_packets, list):
        raise RunContractError("supplement request execution packets are missing")
    for packet in execution_packets:
        if not isinstance(packet, dict) or not isinstance(
            packet.get("assigned_gap_ids"), list
        ):
            raise RunContractError("supplement execution packet is invalid")
        assigned_gap_ids = packet["assigned_gap_ids"]
        if len(assigned_gap_ids) != 1 or str(assigned_gap_ids[0]) not in gaps:
            raise RunContractError("supplement execution packet gap assignment is invalid")
        gap_id = str(assigned_gap_ids[0])
        output_paths = packet.get("output_paths")
        output_by_gap = packet.get("output_path_by_gap")
        if (
            gap_id in packet_paths
            or not isinstance(output_paths, dict)
            or not isinstance(output_by_gap, dict)
            or not str(output_paths.get("result") or "")
        ):
            raise RunContractError("supplement execution packet output path is invalid")
        expected_path = Path(str(output_paths["result"])).resolve()
        expected_draft_path = Path(str(output_paths.get("draft") or "")).resolve()
        authorization = packet.get("write_authorization") or {}
        authorized_paths = authorization.get("final_paths")
        authorized_drafts = authorization.get("draft_paths")
        if (
            Path(str(output_by_gap.get(gap_id) or "")).resolve() != expected_path
            or not isinstance(authorized_paths, list)
            or [Path(str(value)).resolve() for value in authorized_paths]
            != [expected_path]
            or not isinstance(authorized_drafts, list)
            or [Path(str(value)).resolve() for value in authorized_drafts]
            != [expected_draft_path]
        ):
            raise RunContractError("supplement execution packet output path mismatch")
        if bounded_request:
            lane_slice_binding = packet.get("lane_slice")
            bound_lane_slice = (packet.get("bound_input_paths") or {}).get("lane_slice")
            if (
                not isinstance(lane_slice_binding, dict)
                or lane_slice_binding != bound_lane_slice
                or not str(lane_slice_binding.get("path") or "")
                or not str(lane_slice_binding.get("sha256") or "")
            ):
                raise RunContractError("supplement execution packet lane slice is invalid")
            lane_slice_path = Path(str(lane_slice_binding["path"])).resolve()
            if (
                lane_slice_path.parent != Path(manifest["run_dir"]).resolve()
                or lane_slice_path in packet_lane_slices.values()
                or not lane_slice_path.is_file()
                or lane_slice_binding["sha256"] != file_sha256(lane_slice_path)
            ):
                raise RunContractError("supplement lane slice path or hash mismatch")
            lane_slice = load_json(lane_slice_path, {})
            if (
                lane_slice.get("contract_version") != "supplement-lane-slice/1.0"
                or lane_slice.get("run_id") != manifest["run_id"]
                or lane_slice.get("gap") != gaps[gap_id]
                or lane_slice.get("candidate_pool_sha256") != candidate_sha
            ):
                raise RunContractError("supplement lane slice binding mismatch")
            slice_candidates = lane_slice.get("candidates")
            if not isinstance(slice_candidates, list) or any(
                not isinstance(candidate, dict)
                or candidate.get("source_object_sha256") not in candidate_object_hashes
                for candidate in slice_candidates
            ):
                raise RunContractError("supplement lane slice candidate lineage mismatch")
            execution_budget = packet.get("execution_budget")
            expected_budget = {
                "max_queries": gaps[gap_id].get("max_queries"),
                "max_urls": gaps[gap_id].get("max_urls"),
                "max_duration_seconds": gaps[gap_id].get("max_duration_seconds"),
            }
            if execution_budget != expected_budget:
                raise RunContractError("supplement execution budget mismatch")
            finalization = packet.get("finalization")
            if (
                not isinstance(finalization, dict)
                or not isinstance(finalization.get("grace_seconds"), int)
                or isinstance(finalization.get("grace_seconds"), bool)
                or not 1 <= finalization["grace_seconds"] <= 300
                or finalization.get("result_completed_at_semantics")
                != "source_check_completed"
            ):
                raise RunContractError("supplement finalization contract is invalid")
            tool_budget = packet.get("tool_budget")
            if (
                not isinstance(tool_budget, dict)
                or not isinstance(tool_budget.get("soft"), int)
                or not isinstance(tool_budget.get("hard"), int)
                or not 1 <= tool_budget["soft"] <= tool_budget["hard"] <= 100
                or tool_budget.get("block") != "*"
            ):
                raise RunContractError("supplement tool budget is invalid")
            helper = packet.get("agent_helper")
            helper_path = Path(str((helper or {}).get("path") or "")).resolve()
            if (
                not isinstance(helper, dict)
                or helper_path
                != (
                    Path(manifest["skill_path"]).resolve().parent
                    if isinstance(manifest.get("bundle_snapshot"), dict)
                    else HUB_DIR
                )
                / "scripts"
                / "supplement_agent.py"
                or not helper_path.is_file()
                or helper.get("sha256") != file_sha256(helper_path)
            ):
                raise RunContractError("supplement agent helper binding mismatch")
            packet_lane_slices[gap_id] = lane_slice_path
        packet_paths[gap_id] = expected_path
        packet_draft_paths[gap_id] = expected_draft_path
    if set(packet_paths) != set(gaps):
        raise RunContractError("supplement execution packets do not cover every gap")

    results: list[dict[str, Any]] = []
    result_completed_at: list[datetime] = []
    seen: set[str] = set()
    global_access_evidence: list[tuple[str, str, int, dict[str, Any]]] = []
    result_source_paths: dict[str, Path] = {}
    degraded = False
    for raw_path in result_paths:
        result_file = Path(raw_path)
        result = load_json(result_file, {})
        if result.get("contract_version") != "supplement-result/1.0":
            raise RunContractError("invalid supplement result contract_version")
        if result.get("run_id") != manifest["run_id"]:
            raise RunContractError("supplement result run_id mismatch")
        if result.get("request_sha256") != request_sha:
            raise RunContractError("supplement result request_sha256 mismatch")
        if result.get("baseline_sha256") != baseline_sha:
            raise RunContractError("supplement result baseline_sha256 mismatch")
        if result.get("candidate_pool_sha256") != candidate_sha:
            raise RunContractError("supplement result candidate_pool_sha256 mismatch")
        gap_id = str(result.get("gap_id") or "")
        if gap_id not in gaps or gap_id in seen:
            raise RunContractError("supplement result has unknown or duplicate gap_id")
        resolved_result_path = result_file.resolve()
        allowed_result_paths = {packet_paths[gap_id]}
        if publish_drafts:
            allowed_result_paths.add(packet_draft_paths[gap_id])
        if resolved_result_path not in allowed_result_paths:
            raise RunContractError(
                "supplement result path does not match execution packet output path"
            )
        result_source_paths[gap_id] = resolved_result_path
        seen.add(gap_id)
        gap = gaps[gap_id]
        if result.get("lane") != gap.get("lane"):
            raise RunContractError("supplement result lane mismatch")
        status = result.get("status")
        if status not in {"completed", "no_increment", "degraded", "failed"}:
            raise RunContractError("supplement result has invalid status")
        failure_kind = validate_supplement_failure_kind(
            result.get("failure_kind"), str(status)
        )
        if failure_kind is not None:
            result["failure_kind"] = failure_kind
            if not str(result.get("failure_reason") or "").strip():
                raise RunContractError(
                    "supplement failure_kind requires failure_reason"
                )
        infrastructure_failure = failure_kind == "infrastructure"
        completed_at = _parse_aware_datetime(
            result.get("completed_at"), "supplement result completed_at"
        )
        if completed_at < request_started_at:
            raise RunContractError(
                "supplement result completed_at cannot precede request creation"
            )
        if completed_at > current:
            raise RunContractError(
                "supplement result completed_at cannot follow registration"
            )
        if bounded_request:
            started_at = _parse_aware_datetime(
                result.get("started_at"), "supplement result started_at"
            )
            if started_at < request_started_at or started_at > completed_at:
                raise RunContractError("supplement result started_at is outside execution window")
            duration_seconds = (completed_at - started_at).total_seconds()
            if duration_seconds > int(gap["max_duration_seconds"]):
                raise RunContractError("supplement result exceeds max_duration_seconds")
        queries = result.get("executed_queries")
        if (
            not isinstance(queries, list)
            or (not queries and not infrastructure_failure)
            or any(not str(query).strip() for query in queries)
        ):
            raise RunContractError(
                "supplement result executed_queries must be a non-empty string list"
            )
        if bounded_request and len(queries) > int(gap["max_queries"]):
            raise RunContractError("supplement result exceeds max_queries")
        access_log = result.get("access_log")
        if not isinstance(access_log, list) or (
            not access_log and not infrastructure_failure
        ):
            raise RunContractError("supplement result access_log must be a non-empty list")
        if bounded_request and len(access_log) > int(gap["max_urls"]):
            raise RunContractError("supplement result exceeds max_urls")
        validated_access = [
            _validate_access_log_entry(
                access,
                index,
                require_machine_classification=True,
            )
            for index, access in enumerate(access_log)
        ]
        for index, evidence in enumerate(validated_access):
            _validate_request_evidence_time(
                evidence[1],
                f"supplement result access_log[{index}].checked_at",
                request_started_at,
                completed_at,
            )
            global_access_evidence.append(
                (evidence[1], gap_id, index, deepcopy(access_log[index]))
            )
        if result.get("confidence") not in {"high", "medium", "low"}:
            raise RunContractError("supplement result confidence is invalid")
        provenance = result.get("data_provenance")
        if not isinstance(provenance, dict):
            raise RunContractError("supplement result data_provenance is required")
        expected_provenance = {
            "request_sha256": request_sha,
            "candidate_pool_sha256": candidate_sha,
            "access_log_sha256": hashlib.sha256(
                canonical_json_bytes(access_log)
            ).hexdigest(),
        }
        if any(provenance.get(field) != value for field, value in expected_provenance.items()):
            raise RunContractError("supplement result data_provenance mismatch")
        candidates = result.get("candidates")
        if not isinstance(candidates, list):
            raise RunContractError("supplement result candidates must be a list")
        for index, candidate in enumerate(candidates):
            candidate_evidence = _validate_supplement_candidate(
                candidate,
                index,
                manifest["window"],
                request_started_at,
                completed_at,
            )
            candidate["candidate_id"] = candidate_ref(str(candidate["url"]))
            candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
            if candidate_evidence not in validated_access:
                raise RunContractError(
                    f"supplement candidate {index} access_check is absent from access_log"
                )
        coverage = result.get("coverage")
        if not isinstance(coverage, dict):
            raise RunContractError("supplement result coverage is required")
        try:
            attempted = _integer(
                coverage["attempted"], "supplement coverage.attempted", minimum=0
            )
            succeeded = _integer(
                coverage["succeeded"], "supplement coverage.succeeded", minimum=0
            )
            failed = _integer(
                coverage["failed"], "supplement coverage.failed", minimum=0
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RunContractError("supplement result coverage counts are invalid") from exc
        if min(attempted, succeeded, failed) < 0 or attempted != succeeded + failed:
            raise RunContractError("supplement result coverage counts do not conserve")
        observed_succeeded = sum(1 for status_value, *_ in validated_access if status_value == "verified")
        observed_failed = sum(1 for status_value, *_ in validated_access if status_value == "blocked")
        if (attempted, succeeded, failed) != (
            len(validated_access),
            observed_succeeded,
            observed_failed,
        ):
            raise RunContractError(
                "supplement result coverage does not match access_log"
            )
        if status in {"completed", "no_increment"} and failed:
            raise RunContractError(
                "successful supplement status cannot contain failed coverage"
            )
        turns_used = result.get("turns_used")
        if infrastructure_failure:
            if turns_used != 0 or attempted != 0 or candidates or access_log or queries:
                raise RunContractError(
                    "infrastructure supplement failure must record zero attempts and turns"
                )
        elif (
            not isinstance(turns_used, int)
            or isinstance(turns_used, bool)
            or not 1 <= turns_used <= gap["max_turns"]
        ):
            raise RunContractError("supplement result exceeds max_turns")
        halt_met = result.get("halt_condition_met")
        if not isinstance(halt_met, bool):
            raise RunContractError("supplement result halt_condition_met must be boolean")
        if infrastructure_failure and halt_met:
            raise RunContractError(
                "infrastructure supplement failure cannot meet the halt condition"
            )
        if status in {"completed", "no_increment"} and not halt_met:
            raise RunContractError("terminal supplement result did not meet halt condition")
        if status == "completed" and not candidates:
            raise RunContractError("completed supplement result requires candidates")
        if status in {"no_increment", "failed"} and candidates:
            raise RunContractError(f"{status} supplement result cannot contain candidates")
        result_completed_at.append(completed_at)
        degraded = degraded or status in {"degraded", "failed"} or failed > 0
        results.append(deepcopy(result))

    ordered_access = sorted(
        global_access_evidence,
        key=lambda entry: (entry[0], entry[1], entry[2]),
    )
    equal_time_urls: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for checked_at, _gap_id, _index, access in ordered_access:
        key = (
            checked_at,
            normalize_url(str(access.get("requested_url") or "")),
        )
        equal_time_urls.setdefault(key, []).append(access)
    for attempts in equal_time_urls.values():
        if len(attempts) < 2:
            continue
        if any(
            access.get("status") == "blocked"
            and (
                access.get("failure_class") == "permanent"
                or (
                    isinstance(access.get("http_status"), int)
                    and not isinstance(access.get("http_status"), bool)
                    and 400 <= access["http_status"] < 500
                    and access["http_status"] not in {408, 425, 429}
                )
            )
            for access in attempts
        ):
            raise RunContractError(
                "supplement access chronology is ambiguous at an equal timestamp"
            )
    cross_lane_recoveries = _validate_cross_lane_access_retry_policy(
        ordered_access,
        {gap_id: str(gap.get("lane") or "") for gap_id, gap in gaps.items()},
    )

    if seen != set(gaps):
        missing = sorted(set(gaps) - seen)
        raise RunContractError(f"supplement results missing gaps: {missing}")
    latest_result_at = max(result_completed_at)
    earliest_result_at = min(result_completed_at)
    if earliest_result_at < request_started_at:
        raise RunContractError(
            "supplement result completed_at cannot precede request creation"
        )
    if latest_result_at > current:
        raise RunContractError(
            "supplement result completed_at cannot follow registration"
        )
    existing_stage = manifest.get("stages", {}).get("supplemental", {})
    if existing_stage.get("status") in STAGE_FINAL:
        if existing_stage.get("status") == "failed":
            raise RunContractError("supplemental stage is failed and cannot be resumed")
        existing_path = Path(str(existing_stage.get("artifact_path") or ""))
        if (
            not existing_path.is_file()
            or existing_stage.get("artifact_sha256") != file_sha256(existing_path)
        ):
            raise RunContractError("registered supplemental artifact bytes changed")
        existing = load_json(existing_path, {})
        if existing.get("results") == sorted(results, key=lambda result: str(result["gap_id"])):
            return existing_path, existing
        raise RunContractError("supplemental stage is terminal with different results")
    if publish_drafts:
        publications: list[tuple[Path, Path]] = []
        for gap_id, source_path in result_source_paths.items():
            final_path = packet_paths[gap_id]
            if source_path == final_path:
                continue
            if final_path.exists() and file_sha256(final_path) != file_sha256(source_path):
                raise RunContractError(
                    "supplement final path already contains different bytes"
                )
            publications.append((source_path, final_path))
        for source_path, final_path in publications:
            if not final_path.exists():
                os.replace(source_path, final_path)

    timing = {
        "request_to_registration_seconds": round(
            (current - request_started_at).total_seconds(), 3
        ),
        "latest_result_to_registration_seconds": round(
            (current - latest_result_at).total_seconds(), 3
        ),
        "result_completion_skew_seconds": round(
            (latest_result_at - earliest_result_at).total_seconds(), 3
        ),
    }
    coverage_total = {
        key: sum(int(result["coverage"][key]) for result in results)
        for key in ("attempted", "succeeded", "failed")
    }
    aggregate_status = (
        "degraded"
        if degraded
        else "no_increment"
        if results and all(result.get("status") == "no_increment" for result in results)
        else "completed"
    )
    aggregate = {
        "contract_version": "supplement-aggregate/1.0",
        "run_id": manifest["run_id"],
        "request_sha256": request_sha,
        "baseline_sha256": baseline_sha,
        "status": aggregate_status,
        "completed_at": current.isoformat(),
        "coverage": coverage_total,
        "cross_lane_recoveries": cross_lane_recoveries,
        "timing": timing,
        "results": sorted(results, key=lambda result: str(result["gap_id"])),
    }
    aggregate_path = Path(manifest["run_dir"]) / "supplement_results.json"
    atomic_dump_json(aggregate_path, aggregate)
    record_stage(
        manifest_path,
        "supplemental",
        "degraded" if aggregate_status == "degraded" else "completed",
        artifact_path=aggregate_path,
        input_sha256=request_sha,
        metadata={
            "gap_count": len(results),
            "coverage": coverage_total,
            "cross_lane_recovery_count": len(cross_lane_recoveries),
            "result_status": aggregate_status,
            **timing,
        },
        now=current,
    )
    return aggregate_path, aggregate


def reconcile_supplement_progress(
    manifest_path: str | Path,
    request_path: str | Path,
    result_paths: Sequence[str | Path],
    progress_state_paths: Sequence[str | Path],
    *,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Turn durable per-gap terminal states into a registered aggregate."""
    manifest = require_stage(manifest_path, "baseline", {"completed", "degraded"})
    request_file = Path(request_path).resolve()
    request = load_json(request_file, {})
    if request.get("contract_version") != "supplement-request/1.1":
        raise RunContractError("supplement progress reconciliation requires request 1.1")
    request_record = manifest.get("artifacts", {}).get("supplement_request")
    if (
        not isinstance(request_record, dict)
        or Path(str(request_record.get("artifact_path") or "")).resolve()
        != request_file
        or request_record.get("artifact_sha256") != file_sha256(request_file)
    ):
        raise RunContractError("supplement request does not match the registered artifact")
    gaps = {
        str(gap.get("gap_id") or ""): gap
        for gap in request.get("gaps", [])
        if isinstance(gap, dict)
    }
    expected_state_paths: dict[Path, str] = {}
    draft_paths: dict[str, Path] = {}
    for packet in request.get("execution_packets", []):
        if not isinstance(packet, dict):
            raise RunContractError("supplement execution packet is invalid")
        assigned = packet.get("assigned_gap_ids")
        progress = packet.get("progress")
        outputs = packet.get("output_paths")
        if (
            not isinstance(assigned, list)
            or len(assigned) != 1
            or not isinstance(progress, dict)
            or not isinstance(outputs, dict)
        ):
            raise RunContractError("supplement execution packet is invalid")
        gap_id = str(assigned[0])
        state_path = Path(str(progress.get("state_path") or "")).resolve()
        draft_path = Path(str(outputs.get("draft") or "")).resolve()
        if gap_id not in gaps:
            raise RunContractError("supplement progress binding is invalid")
        expected_state_paths[state_path] = gap_id
        draft_paths[gap_id] = draft_path
    explicitly_supplied_states: set[Path] = set()
    for raw_state_path in progress_state_paths:
        state_path = Path(raw_state_path).resolve()
        if state_path not in expected_state_paths:
            raise RunContractError("supplement progress state path is not authorized")
        if state_path in explicitly_supplied_states:
            raise RunContractError("duplicate supplement progress state")
        explicitly_supplied_states.add(state_path)
    supplied_states: dict[str, tuple[Path, dict[str, Any]]] = {}
    for state_path, gap_id in expected_state_paths.items():
        if not state_path.is_file():
            if state_path in explicitly_supplied_states:
                raise RunContractError("supplement progress state is missing")
            continue
        state = load_json(state_path, {})
        if state.get("progress_id") != gap_id:
            raise RunContractError("supplement progress identity mismatch")
        supplied_states[gap_id] = (state_path, state)
    supplied_results: dict[str, Path] = {}
    for raw_result_path in result_paths:
        result_path = Path(raw_result_path).resolve()
        result = load_json(result_path, {})
        gap_id = str(result.get("gap_id") or "")
        if gap_id not in gaps or gap_id in supplied_results:
            raise RunContractError("supplement result has unknown or duplicate gap_id")
        supplied_results[gap_id] = result_path
    current = _aware_now(manifest["timezone"], now)
    request_sha = file_sha256(request_file)
    baseline_sha = str(manifest["stages"]["baseline"]["artifact_sha256"])
    candidate_sha = str(
        manifest.get("artifacts", {}).get("candidate_pool", {}).get(
            "artifact_sha256", ""
        )
    )
    reconciled_paths: list[Path] = []
    for gap_id, gap in gaps.items():
        state_record = supplied_states.get(gap_id)
        terminal_status = (
            state_record[1].get("terminal_status") if state_record else None
        )
        if terminal_status not in {"degraded_timeout", "declare_lost"}:
            if gap_id in supplied_results:
                reconciled_paths.append(supplied_results[gap_id])
                continue
            if state_record is None:
                raise RunContractError(
                    f"supplement gap {gap_id} has neither result nor terminal progress state"
                )
            raise RunContractError(
                f"supplement gap {gap_id} progress state is not terminal"
            )
        assert state_record is not None
        state_path, _ = state_record
        access_log: list[dict[str, Any]] = []
        result = {
            "contract_version": "supplement-result/1.0",
            "run_id": manifest["run_id"],
            "request_sha256": request_sha,
            "baseline_sha256": baseline_sha,
            "candidate_pool_sha256": candidate_sha,
            "gap_id": gap_id,
            "lane": gap["lane"],
            "status": "failed",
            "failure_kind": "infrastructure",
            "failure_reason": (
                f"{terminal_status}; progress_state_sha256={file_sha256(state_path)}"
            ),
            "executed_queries": [],
            "access_log": access_log,
            "candidates": [],
            "coverage": {"attempted": 0, "succeeded": 0, "failed": 0},
            "confidence": "low",
            "data_provenance": {
                "request_sha256": request_sha,
                "candidate_pool_sha256": candidate_sha,
                "access_log_sha256": hashlib.sha256(
                    canonical_json_bytes(access_log)
                ).hexdigest(),
            },
            "turns_used": 0,
            "halt_condition_met": False,
            "started_at": current.isoformat(),
            "completed_at": current.isoformat(),
        }
        terminal_result_path = supplied_results.get(gap_id, draft_paths[gap_id])
        atomic_dump_json(terminal_result_path, result)
        reconciled_paths.append(terminal_result_path)
    return register_supplement_results(
        manifest_path,
        request_file,
        reconciled_paths,
        publish_drafts=True,
        now=current,
    )


def _review_request_retry_matches(
    existing: dict[str, Any],
    expected: dict[str, Any],
    run_dir: Path,
) -> bool:
    """Accept only the exact orphan request left by a failed manifest commit."""
    invocation_id = str(existing.get("invocation_id") or "")
    challenge = str(existing.get("challenge") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", invocation_id) or not re.fullmatch(
        r"[0-9a-f]{64}", challenge
    ):
        return False
    try:
        _parse_aware_datetime(existing.get("created_at"), "review request created_at")
    except RunContractError:
        return False

    expected_copy = deepcopy(expected)
    existing_copy = deepcopy(existing)
    for value in (expected_copy, existing_copy):
        value.pop("invocation_id", None)
        value.pop("challenge", None)
        value.pop("created_at", None)
        packet = value.get("execution_packet")
        if isinstance(packet, dict):
            packet.pop("draft_paths", None)
            packet.pop("write_scope", None)
            packet.pop("finalizer_owned_paths", None)
            packet.pop("validation_command", None)
    if existing_copy != expected_copy:
        return False

    packet = existing.get("execution_packet")
    if not isinstance(packet, dict):
        return False
    output_paths = packet.get("output_paths")
    draft_paths = packet.get("draft_paths")
    if not isinstance(output_paths, dict) or not isinstance(draft_paths, dict):
        return False
    if existing.get("review_kind") == "semantic":
        expected_drafts = {
            "dynamic": str(
                (run_dir / f"semantic_dynamic.{invocation_id}.draft.json").resolve()
            ),
            "refined_core": str(
                (run_dir / f"refined_core.{invocation_id}.draft.json").resolve()
            ),
            "decision": str(
                (run_dir / f"semantic_decision.{invocation_id}.draft.json").resolve()
            ),
            "review_receipt": str(
                (run_dir / f"semantic_receipt.{invocation_id}.draft.json").resolve()
            ),
        }
    else:
        expected_drafts = {
            "review_receipt": str(
                (run_dir / f"red_team_receipt.{invocation_id}.draft.json").resolve()
            )
        }
    if draft_paths != expected_drafts:
        return False
    if existing.get("review_kind") == "semantic":
        helper = packet.get("agent_helper")
        expected_validation = (
            helper.get("finalize_command") if isinstance(helper, dict) else None
        )
        if packet.get("validation_command") != expected_validation:
            return False
        return packet.get("write_scope") == [expected_drafts["dynamic"]]
    return sorted(packet.get("write_scope") or []) == sorted(
        [*output_paths.values(), *expected_drafts.values()]
    )


def build_review_request(
    manifest_path: str | Path,
    refined_path: str | Path | None,
    review_kind: str,
    *,
    semantic_receipt_path: str | Path | None = None,
    max_turns: int = 2,
    halt_condition: str | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    manifest = require_stage(
        manifest_path,
        "supplemental",
        {"completed", "degraded", "skipped", "not_required"},
    )
    configuration = {
        "semantic": ("semantic_review_request", "semantic_model", "SemanticEvaluator"),
        "red_team": ("red_team_request", "logic_adversary", "RedTeam"),
    }.get(review_kind)
    if configuration is None:
        raise RunContractError("review request kind must be semantic or red_team")
    artifact_name, reviewer_kind, reviewer_id = configuration
    if (
        not isinstance(max_turns, int)
        or isinstance(max_turns, bool)
        or not 1 <= max_turns <= 2
    ):
        raise RunContractError("review request max_turns must be between 1 and 2")
    if manifest.get("artifacts", {}).get(artifact_name) is not None:
        raise RunContractError(f"{review_kind} review request is immutable once registered")
    refined_file = Path(refined_path) if refined_path is not None else None
    if review_kind == "red_team" and (
        refined_file is None or not refined_file.is_file()
    ):
        raise RunContractError("refined core is required before red-team invocation")
    scope: dict[str, Any] | None = None
    deterministic_fast_path = False
    if review_kind == "red_team":
        if semantic_receipt_path is None:
            raise RunContractError(
                "validated semantic receipt is required before red-team invocation"
            )
        assert refined_file is not None
        validate_semantic_draft(
            manifest_path,
            refined_file,
            semantic_receipt_path,
        )
        semantic_stage = load_manifest(manifest_path).get("stages", {}).get(
            "semantic_review", {}
        )
        if semantic_stage.get("status") not in STAGE_TERMINAL:
            register_review_receipt(
                manifest_path,
                refined_file,
                semantic_receipt_path,
                "semantic_review",
                now=now,
            )
        manifest = load_manifest(manifest_path)
        refined_payload = load_json(refined_file, {})
        semantic_receipt = load_json(Path(semantic_receipt_path), {})
        scope = review_scope(refined_payload, semantic_receipt)
        deterministic_fast_path = _deterministic_red_team_fast_path(
            refined_payload,
            semantic_receipt,
        )
        if scope["review_mode"] in {"no_l4_fast_path", "targeted_review"}:
            max_turns = 1
        if deterministic_fast_path:
            reviewer_kind = "deterministic_gate"
            reviewer_id = "NoL4Gate"
    bundle_root = (
        Path(manifest["skill_path"]).resolve().parent
        if isinstance(manifest.get("bundle_snapshot"), dict)
        else HUB_DIR
    )
    prompt_config_path = bundle_root / "references" / "subagent_prompts.json"
    semantic_agent_path = bundle_root / "scripts" / "semantic_agent.py"
    run_cli_path = bundle_root / "scripts" / "run_daily.py"
    prompt_config = load_json(prompt_config_path, {})
    review_token_budget = (
        0
        if deterministic_fast_path
        else _integer(
            prompt_config.get("execution_policy", {})
            .get("observability", {})
            .get(
                "semantic_token_budget"
                if review_kind == "semantic"
                else "red_team_token_budget",
                80000 if review_kind == "semantic" else 50000,
            ),
            "review token budget",
            minimum=1,
        )
    )
    budget_state: dict[str, float | int] | None = None
    if not deterministic_fast_path:
        observability = prompt_config.get("execution_policy", {}).get(
            "observability", {}
        )
        review_cost_budget_usd = float(
            observability.get(
                "semantic_cost_budget_usd"
                if review_kind == "semantic"
                else "red_team_cost_budget_usd",
                0.5,
            )
        )
        if (
            not math.isfinite(review_cost_budget_usd)
            or review_cost_budget_usd <= 0
        ):
            raise RunContractError("review cost budget is invalid")
        budget_state = _assert_execution_budget_allows_launch(
            manifest,
            reserved_tokens=review_token_budget,
            reserved_cost_usd=review_cost_budget_usd,
        )
    if review_kind == "semantic":
        default_halt = "所有最终条目批量完成语义评估并生成完整血缘映射，或发现阻断问题"
    elif scope and scope["review_mode"] in {"no_l4_fast_path", "targeted_review"}:
        default_halt = "确认绑定 core 无 L4 并完成重大资讯资格、日期、来源独立性与行动时序检查，或发现阻断问题"
    else:
        default_halt = "全部 L4 与重大资讯资格完成反证检查，或发现阻断问题"
    halt = str(halt_condition or default_halt).strip()
    if not halt:
        raise RunContractError("review request halt_condition is required")
    current = _aware_now(manifest["timezone"], now)
    agent_contract = (
        prompt_config.get("review_agents", {}).get(reviewer_id)
        if isinstance(prompt_config, dict)
        else None
    )
    if deterministic_fast_path:
        agent_contract = {
            "role": "确定性无 L4 门禁",
            "model_required": False,
            "network_policy": "forbidden",
        }
    if not isinstance(agent_contract, dict):
        raise RunContractError(f"review prompt contract is missing for {reviewer_id}")
    prompt_sha256 = file_sha256(prompt_config_path)
    if prompt_sha256 is None:
        raise RunContractError("review prompt configuration is missing")
    run_dir = Path(manifest["run_dir"]).resolve()
    request_path = run_dir / f"{review_kind}_review_request.json"
    invocation_id = uuid.uuid4().hex
    if review_kind == "semantic":
        output_paths = {
            "refined_core": str(run_dir / "refined_core.json"),
            "review_receipt": str(run_dir / "semantic_receipt.json"),
        }
        draft_paths = {
            "dynamic": str(
                run_dir / f"semantic_dynamic.{invocation_id}.draft.json"
            ),
            "refined_core": str(run_dir / f"refined_core.{invocation_id}.draft.json"),
            "decision": str(
                run_dir / f"semantic_decision.{invocation_id}.draft.json"
            ),
            "review_receipt": str(
                run_dir / f"semantic_receipt.{invocation_id}.draft.json"
            ),
        }
        progress_messages = [
            "review_progress seq=1 phase=input_validated",
            "review_progress seq=2 phase=lineage_ready",
        ]
    else:
        output_paths = {"review_receipt": str(run_dir / "red_team_receipt.json")}
        draft_paths = {
            "review_receipt": str(
                run_dir / f"red_team_receipt.{invocation_id}.draft.json"
            )
        }
        progress_messages = ["review_progress seq=1 phase=input_validated"]
    request: dict[str, Any] = {
        "contract_version": "review-request/1.1",
        "run_id": manifest["run_id"],
        "review_kind": review_kind,
        "reviewer_kind": reviewer_kind,
        "reviewer_id": reviewer_id,
        "invocation_id": invocation_id,
        "challenge": uuid.uuid4().hex + uuid.uuid4().hex,
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "max_turns": max_turns,
        "halt_condition": halt,
        "created_at": current.isoformat(),
        "execution_packet": {
            "contract_version": "review-execution-packet/1.0",
            "self_contained": True,
            "run_manifest_path": str(Path(manifest_path).resolve()),
            "skill_root": str(bundle_root.resolve()),
            "prompt_config": {
                "path": str(prompt_config_path.resolve()),
                "sha256": prompt_sha256,
            },
            "contract_bundle": {
                "common_contract": deepcopy(
                    prompt_config.get("common_contract", {})
                ),
                "review_common_contract": deepcopy(
                    prompt_config.get("review_common_contract", {})
                ),
                "execution_policy": deepcopy(
                    prompt_config.get("execution_policy", {})
                ),
            },
            "agent_contract": deepcopy(agent_contract),
            "output_paths": output_paths,
            "draft_paths": draft_paths,
            "write_scope": (
                [draft_paths["dynamic"]]
                if review_kind == "semantic"
                else sorted([*output_paths.values(), *draft_paths.values()])
            ),
            "progress_messages": progress_messages,
            "timeout_ms": (
                0
                if deterministic_fast_path
                else _integer(
                    prompt_config.get("execution_policy", {})
                    .get("observability", {})
                    .get(
                        "semantic_timeout_ms"
                        if review_kind == "semantic"
                        else "red_team_timeout_ms",
                        240000 if review_kind == "semantic" else 120000,
                    ),
                    "review timeout_ms",
                    minimum=1,
                )
            ),
            "usage_budget": {
                "tokens": review_token_budget,
                "cost_usd": (
                    0.0
                    if deterministic_fast_path
                    else float((budget_state or {})["requested_cost_usd"])
                ),
            },
            "artifact_ready_message": (
                "decision_ready refined_core_draft_path=<path> refined_core_sha256=<sha256> "
                "decision_path=<path> decision_sha256=<sha256>"
                if review_kind == "semantic"
                else "artifact_ready path=<path> sha256=<sha256>"
            ),
        },
    }
    if review_kind == "semantic":
        helper_sha256 = file_sha256(semantic_agent_path)
        if helper_sha256 is None:
            raise RunContractError("semantic agent helper is missing")
        request["input_bundle_sha256"] = review_input_bundle_sha256(manifest)
        request["review_mode"] = "registered_evidence_batch"
        request["network_policy"] = "registered_evidence_first"
        artifacts = manifest.get("artifacts", {})
        baseline = manifest.get("stages", {}).get("baseline", {})
        supplement = manifest.get("stages", {}).get("supplemental", {})

        def bound_artifact(record: dict[str, Any]) -> dict[str, str]:
            return {
                "path": str(Path(record["artifact_path"]).resolve()),
                "sha256": str(record["artifact_sha256"]),
            }

        request["bound_artifacts"] = {
            "baseline": bound_artifact(baseline),
            "candidate_pool": bound_artifact(artifacts["candidate_pool"]),
            "history_snapshot": bound_artifact(artifacts["history_snapshot"]),
            "supplement": bound_artifact(supplement),
        }
        if artifacts.get("history_review_slice"):
            request["bound_artifacts"]["history_review_slice"] = bound_artifact(
                artifacts["history_review_slice"]
            )
        if artifacts.get("focus_config"):
            request["bound_artifacts"]["focus_config"] = bound_artifact(
                artifacts["focus_config"]
            )
        semantic_observability = (
            prompt_config.get("execution_policy", {}).get("observability", {})
        )
        request["execution_packet"]["tool_budget"] = {
            "soft": _integer(
                semantic_observability.get("semantic_tool_budget_soft", 6),
                "semantic tool budget soft",
                minimum=1,
            ),
            "hard": _integer(
                semantic_observability.get("semantic_tool_budget_hard", 10),
                "semantic tool budget hard",
                minimum=1,
            ),
            "block": "*",
        }
        request["execution_packet"]["agent_helper"] = {
            "path": str(semantic_agent_path.resolve()),
            "sha256": helper_sha256,
            "context_command": [
                "python",
                "-X",
                "utf8",
                str(semantic_agent_path.resolve()),
                "context",
                "--request",
                str(request_path),
            ],
            "finalize_command": [
                "python",
                "-X",
                "utf8",
                str(semantic_agent_path.resolve()),
                "finalize",
                "--request",
                str(request_path),
            ],
        }
        request["execution_packet"]["task_message"] = (
            "Run agent_helper.context_command first. Use only its compact eligible_candidates; "
            "do not read the full request, baseline, history, candidate pool, supplement, schema, "
            "old runs, prompt config, or script source. Send progress via contact_supervisor. "
            "Write only the semantic dynamic draft, then run agent_helper.finalize_command."
        )
        request["execution_packet"]["finalizer_owned_paths"] = sorted(
            [
                *output_paths.values(),
                draft_paths["refined_core"],
                draft_paths["decision"],
                draft_paths["review_receipt"],
            ]
        )
        request["execution_packet"]["validation_command"] = deepcopy(
            request["execution_packet"]["agent_helper"]["finalize_command"]
        )
    else:
        if refined_file is None or semantic_receipt_path is None:
            raise RunContractError("red-team bound inputs are missing")
        request["refined_sha256"] = file_sha256(refined_file)
        request["execution_packet"]["bound_refined_path"] = str(
            refined_file.resolve()
        )
        request["execution_packet"]["bound_semantic_receipt_path"] = str(
            Path(semantic_receipt_path).resolve()
        )
        request["execution_packet"]["validation_command"] = [
            "python",
            "-X",
            "utf8",
            str(run_cli_path.resolve()),
            "validate-red-team-draft",
            "--manifest",
            str(Path(manifest_path).resolve()),
            "--refined",
            str(refined_file.resolve()),
            "--semantic-receipt",
            str(Path(semantic_receipt_path).resolve()),
            "--red-team-receipt",
            draft_paths["review_receipt"],
        ]
        request.update(scope or {})
        request["deterministic_fast_path"] = deterministic_fast_path
        request["network_policy"] = (
            "forbidden" if deterministic_fast_path else "registered_evidence_first"
        )
    stage_name = "semantic_review" if review_kind == "semantic" else "red_team"
    manifest_file = Path(manifest_path)
    with locked_manifest(manifest_file) as (locked, expected_manifest_sha256):
        if locked.get("stages", {}).get("supplemental", {}).get("status") not in {
            "completed",
            "degraded",
            "skipped",
            "not_required",
        }:
            raise RunContractError("review request requires successful supplemental stage")
        if locked.get("artifacts", {}).get(artifact_name) is not None:
            raise RunContractError(
                f"{review_kind} review request is immutable once registered"
            )
        if locked.get("stages", {}).get(stage_name, {}).get("status") in STAGE_FINAL:
            raise RunContractError(f"stage {stage_name} is immutable once terminal/final")
        if request_path.exists():
            orphan = load_json(request_path, {})
            if not _review_request_retry_matches(orphan, request, run_dir):
                raise RunContractError(
                    f"unregistered {review_kind} review request conflicts with this invocation"
                )
            request = orphan
            invocation_id = str(request["invocation_id"])
        else:
            atomic_dump_json(request_path, request)
        request_sha256 = file_sha256(request_path)
        before = {field: deepcopy(locked[field]) for field in IMMUTABLE_FIELDS}
        _record_artifact_in_manifest(
            locked,
            artifact_name,
            request_path,
            input_sha256=request.get("input_bundle_sha256")
            or request.get("refined_sha256"),
            metadata={
                "review_kind": review_kind,
                "reviewer_kind": reviewer_kind,
                "reviewer_id": reviewer_id,
                "review_mode": request["review_mode"],
                "max_turns": request["max_turns"],
                "l4_item_count": len(request.get("l4_item_hashes", [])),
            },
            current=current,
        )
        if not deterministic_fast_path:
            request_budget = request["execution_packet"]["usage_budget"]
            _reserve_execution_budget(
                locked,
                [
                    {
                        "stage": stage_name,
                        "invocation_id": invocation_id,
                        "tokens": int(request_budget["tokens"]),
                        "cost_usd": float(request_budget["cost_usd"]),
                    }
                ],
                request_sha256=str(request_sha256),
                current=current,
            )
            _refresh_telemetry_summary(locked)
        _record_stage_in_manifest(
            locked,
            stage_name,
            "running",
            artifact_path=None,
            input_sha256=None,
            metadata={
                "review_kind": review_kind,
                "reviewer_kind": reviewer_kind,
                "reviewer_id": reviewer_id,
                "invocation_id": invocation_id,
                "request_sha256": request_sha256,
                "max_turns": request["max_turns"],
            },
            current=current,
        )
        for field, expected in before.items():
            if locked[field] != expected:
                raise RunContractError(f"immutable run field changed: {field}")
        commit_manifest(manifest_file, locked, expected_manifest_sha256)
    if review_kind == "red_team" and deterministic_fast_path:
        if refined_file is None:
            raise RunContractError("red-team refined core is missing")
        finalize_red_team_fast_path(
            manifest_path,
            refined_file,
            now=current,
        )
    return request_path, request


def finalize_red_team_fast_path(
    manifest_path: str | Path,
    refined_path: str | Path,
    *,
    now: datetime | None = None,
) -> Path:
    manifest = load_manifest(manifest_path)
    request, request_sha = _registered_review_request(manifest, "red_team")
    if (
        request.get("reviewer_kind") != "deterministic_gate"
        or request.get("reviewer_id") != "NoL4Gate"
        or request.get("deterministic_fast_path") is not True
        or request.get("network_policy") != "forbidden"
    ):
        raise RunContractError("red-team request is not eligible for deterministic fast path")
    refined_file = Path(refined_path).resolve()
    packet = request.get("execution_packet") or {}
    if refined_file != Path(str(packet.get("bound_refined_path") or "")).resolve():
        raise RunContractError("deterministic red-team refined path mismatch")
    semantic_receipt_path = Path(
        str(packet.get("bound_semantic_receipt_path") or "")
    ).resolve()
    refined = load_json(refined_file, {})
    semantic_receipt = load_json(semantic_receipt_path, {})
    if not _deterministic_red_team_fast_path(refined, semantic_receipt):
        raise RunContractError("red-team deterministic fast-path conditions changed")
    current = _aware_now(manifest["timezone"], now)
    receipt = {
        "contract_version": "review-receipt/1.0",
        "run_id": manifest["run_id"],
        "review_kind": "red_team",
        "status": "not_required",
        "reviewer_kind": "deterministic_gate",
        "reviewer_id": request["reviewer_id"],
        "invocation_id": request["invocation_id"],
        "challenge": request["challenge"],
        "request_sha256": request_sha,
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "output_sha256": file_sha256(refined_file),
        "reviewed_item_hashes": [],
        "turns_used": 0,
        "halt_condition_met": True,
        "completed_at": current.isoformat(),
    }
    receipt_path = Path(
        str((packet.get("output_paths") or {}).get("review_receipt") or "")
    ).resolve()
    if receipt_path.exists():
        existing = load_json(receipt_path, {})
        if existing != receipt:
            raise RunContractError("deterministic red-team receipt already differs")
    else:
        atomic_dump_json(receipt_path, receipt)
    register_review_receipt(
        manifest_path,
        refined_file,
        receipt_path,
        "red_team",
        now=current,
    )
    return receipt_path


def finalize_semantic_decision(
    manifest_path: str | Path,
    refined_draft_path: str | Path,
    decision_path: str | Path,
    *,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    manifest = load_manifest(manifest_path)
    request, request_sha = _registered_review_request(manifest, "semantic")
    packet = request.get("execution_packet") or {}
    draft_paths = packet.get("draft_paths") or {}
    output_paths = packet.get("output_paths") or {}
    refined_draft = Path(refined_draft_path).resolve()
    decision_file = Path(decision_path).resolve()
    expected_refined_draft = Path(str(draft_paths.get("refined_core") or "")).resolve()
    expected_decision = Path(str(draft_paths.get("decision") or "")).resolve()
    refined_final = Path(str(output_paths.get("refined_core") or "")).resolve()
    receipt_final = Path(str(output_paths.get("review_receipt") or "")).resolve()
    if refined_draft != expected_refined_draft or decision_file != expected_decision:
        raise RunContractError("semantic finalizer input path is not authorized")
    current = _aware_now(manifest["timezone"], now)
    request_created_at = _parse_aware_datetime(
        request.get("created_at"), "semantic review request created_at"
    )
    timeout_ms = _integer(
        packet.get("timeout_ms"), "semantic review timeout_ms", minimum=1
    )
    deadline = request_created_at + timedelta(milliseconds=timeout_ms)
    if current.astimezone(timezone.utc) > deadline.astimezone(timezone.utc):
        expire_execution_reservation(
            manifest_path,
            "semantic_review",
            str(request["invocation_id"]),
            reason="semantic finalizer exceeded registered timeout",
            now=current,
        )
        record_stage(
            manifest_path,
            "semantic_review",
            "degraded_timeout",
            metadata={
                "invocation_id": request["invocation_id"],
                "deadline": deadline.isoformat(),
                "completed_after_deadline": True,
            },
            now=current,
        )
        raise RunContractError("semantic review completed after registered timeout")
    decision = load_json(decision_file, {})
    if decision.get("contract_version") != "semantic-decision/1.0":
        raise RunContractError("invalid semantic decision contract_version")
    if decision.get("status") != "passed":
        raise RunContractError("semantic decision did not pass")
    turns_used = decision.get("turns_used")
    if (
        not isinstance(turns_used, int)
        or isinstance(turns_used, bool)
        or not 1 <= turns_used <= int(request.get("max_turns", 0))
    ):
        raise RunContractError("semantic decision turns_used exceeds request")
    if decision.get("halt_condition_met") is not True:
        raise RunContractError("semantic decision halt_condition_met must be true")
    if refined_final.is_file() and receipt_final.is_file():
        validate_semantic_draft(manifest_path, refined_final, receipt_final)
        register_review_receipt(
            manifest_path,
            refined_final,
            receipt_final,
            "semantic_review",
            now=current,
        )
        decision_file.unlink(missing_ok=True)
        return refined_final, receipt_final
    refined_source = refined_draft if refined_draft.is_file() else refined_final
    if not refined_source.is_file():
        raise RunContractError("semantic refined draft and recoverable final are missing")
    refined = load_json(refined_source, {})
    lineage = registered_candidate_lineage(manifest)
    reviewed_item_hashes: list[str] = []
    lineage_bindings: list[dict[str, Any]] = []
    access_log: list[dict[str, Any]] = []
    for index, item in enumerate(refined.get("top_10", [])):
        if not isinstance(item, dict):
            raise RunContractError(f"refined item {index} must be an object")
        output_hash = item_hash(item)
        reviewed_item_hashes.append(output_hash)
        refs = item.get("candidate_refs")
        if not isinstance(refs, list) or not refs:
            raise RunContractError(f"refined item {index} candidate_refs are required")
        try:
            output_evidence = (
                normalize_url(str(item.get("url") or "")),
                str(item.get("title") or ""),
                str(item.get("source") or ""),
                normalize_published_at(str(item.get("published_at") or "")),
                str(item.get("published_at_source") or ""),
            )
        except RunContractError as exc:
            raise RunContractError(
                f"refined item {index} evidence is invalid"
            ) from exc
        inputs: list[dict[str, str]] = []
        selected_candidates: list[dict[str, Any]] = []
        exact_output_match = False
        multi_independent = item.get("corroboration_status") == "multi_independent"
        final_event_id = str(item.get("event_id") or "")
        for reference in refs:
            ref = str(reference)
            entry = lineage.get(ref)
            if not isinstance(entry, dict):
                raise RunContractError(
                    f"refined item {index} references an unregistered candidate"
                )
            exact_matches: list[tuple[str, dict[str, Any]]] = []
            event_matches: list[tuple[str, dict[str, Any]]] = []
            for object_hash, candidate in sorted(
                (entry.get("objects") or {}).items()
            ):
                if not isinstance(candidate, dict):
                    continue
                try:
                    candidate_evidence = (
                        normalize_url(str(candidate.get("url") or "")),
                        str(candidate.get("title") or ""),
                        str(candidate.get("source") or ""),
                        normalize_published_at(
                            str(candidate.get("published_at") or "")
                        ),
                        str(candidate.get("published_at_source") or ""),
                    )
                except RunContractError:
                    continue
                if candidate_evidence == output_evidence:
                    exact_matches.append((str(object_hash), candidate))
                    continue
                if multi_independent:
                    try:
                        candidate_event_id = _validated_semantic_candidate_event_id(
                            candidate,
                            0,
                            path_prefix=f"refined item {index} candidate lineage",
                        )
                    except RunContractError:
                        continue
                    if candidate_event_id == final_event_id:
                        event_matches.append((str(object_hash), candidate))
            matches = exact_matches or event_matches
            if not matches:
                raise RunContractError(
                    f"refined item {index} does not match candidate lineage"
                )
            object_hash, selected_candidate = matches[0]
            exact_output_match = exact_output_match or bool(exact_matches)
            selected_candidates.append(selected_candidate)
            inputs.append(
                {
                    "candidate_ref": ref,
                    "candidate_object_sha256": object_hash,
                }
            )
        if not exact_output_match:
            raise RunContractError(
                f"refined item {index} has no candidate matching output evidence"
            )
        lineage_bindings.append(
            {"output_item_sha256": output_hash, "inputs": inputs}
        )
        access = item.get("access_check")
        if not isinstance(access, dict):
            raise RunContractError(f"refined item {index} access_check is required")
        access_candidates = [access]
        if multi_independent:
            access_candidates.extend(
                candidate["access_check"]
                for candidate in selected_candidates
                if isinstance(candidate.get("access_check"), dict)
            )
        known_access = {
            hashlib.sha256(canonical_json_bytes(value)).hexdigest()
            for value in access_log
        }
        for access_value in access_candidates:
            access_sha = hashlib.sha256(
                canonical_json_bytes(access_value)
            ).hexdigest()
            if access_sha not in known_access:
                access_log.append(deepcopy(access_value))
                known_access.add(access_sha)
    receipt = {
        "contract_version": "review-receipt/1.0",
        "run_id": manifest["run_id"],
        "review_kind": "semantic",
        "status": "passed",
        "reviewer_kind": request["reviewer_kind"],
        "reviewer_id": request["reviewer_id"],
        "invocation_id": request["invocation_id"],
        "challenge": request["challenge"],
        "request_sha256": request_sha,
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "input_bundle_sha256": review_input_bundle_sha256(manifest),
        "output_sha256": file_sha256(refined_source),
        "reviewed_item_hashes": reviewed_item_hashes,
        "lineage_bindings": lineage_bindings,
        "access_log": access_log,
        "data_provenance": {
            "input_bundle_sha256": review_input_bundle_sha256(manifest),
            "access_log_sha256": hashlib.sha256(
                canonical_json_bytes(access_log)
            ).hexdigest(),
        },
        "turns_used": turns_used,
        "halt_condition_met": True,
        "completed_at": current.isoformat(),
    }
    receipt_draft = Path(str(draft_paths.get("review_receipt") or "")).resolve()
    atomic_dump_json(receipt_draft, receipt)
    validate_semantic_draft(manifest_path, refined_source, receipt_draft)
    promotion_pairs = (
        (refined_source, refined_final),
        (receipt_draft, receipt_final),
    )
    for source, final in promotion_pairs:
        if final.exists() and file_sha256(final) != file_sha256(source):
            raise RunContractError("semantic final path already contains different bytes")
    for source, final in promotion_pairs:
        if not final.exists():
            os.replace(source, final)
    register_review_receipt(
        manifest_path,
        refined_final,
        receipt_final,
        "semantic_review",
        now=current,
    )
    decision_file.unlink(missing_ok=True)
    return refined_final, receipt_final


def _registered_review_request(
    manifest: dict[str, Any], review_kind: str
) -> tuple[dict[str, Any], str]:
    artifact_name = {
        "semantic": "semantic_review_request",
        "red_team": "red_team_request",
    }.get(review_kind)
    if artifact_name is None:
        raise RunContractError("review receipt has invalid review_kind")
    record = manifest.get("artifacts", {}).get(artifact_name)
    if not isinstance(record, dict):
        raise RunContractError(f"registered {review_kind} review request is missing")
    path = Path(str(record.get("artifact_path") or ""))
    if not path.is_file() or record.get("artifact_sha256") != file_sha256(path):
        raise RunContractError(f"registered {review_kind} review request bytes changed")
    request = load_json(path, {})
    if (
        request.get("contract_version") != "review-request/1.1"
        or request.get("run_id") != manifest.get("run_id")
        or request.get("review_kind") != review_kind
    ):
        raise RunContractError(f"registered {review_kind} review request is invalid")
    return request, str(record["artifact_sha256"])


def _validate_review_execution_paths(
    manifest: dict[str, Any],
    review_kind: str,
    refined_path: str | Path,
    receipt_path: str | Path,
    *,
    allow_draft_paths: bool,
) -> None:
    request, _ = _registered_review_request(manifest, review_kind)
    packet = request.get("execution_packet")
    if not isinstance(packet, dict):
        raise RunContractError("review request execution_packet is missing")
    refined = Path(refined_path).resolve()
    receipt = Path(receipt_path).resolve()
    output_paths = packet.get("output_paths")
    if not isinstance(output_paths, dict):
        raise RunContractError("review request output_paths are missing")
    accepted: list[tuple[Path, Path]] = []
    if review_kind == "semantic":
        accepted.append(
            (
                Path(str(output_paths.get("refined_core") or "")).resolve(),
                Path(str(output_paths.get("review_receipt") or "")).resolve(),
            )
        )
        if allow_draft_paths:
            draft_paths = packet.get("draft_paths")
            if not isinstance(draft_paths, dict):
                raise RunContractError("review request draft_paths are missing")
            accepted.append(
                (
                    Path(str(draft_paths.get("refined_core") or "")).resolve(),
                    Path(str(draft_paths.get("review_receipt") or "")).resolve(),
                )
            )
    else:
        bound_refined = Path(str(packet.get("bound_refined_path") or "")).resolve()
        accepted.append(
            (
                bound_refined,
                Path(str(output_paths.get("review_receipt") or "")).resolve(),
            )
        )
        if allow_draft_paths:
            draft_paths = packet.get("draft_paths")
            if not isinstance(draft_paths, dict):
                raise RunContractError("review request draft_paths are missing")
            accepted.append(
                (
                    bound_refined,
                    Path(str(draft_paths.get("review_receipt") or "")).resolve(),
                )
            )
    if (refined, receipt) not in accepted:
        mode = "draft/output" if allow_draft_paths else "final output"
        raise RunContractError(
            f"{review_kind} review paths do not match execution_packet {mode} paths"
        )


def load_review_progress_state(
    manifest_path: str | Path,
    review_kind: str,
    invocation_id: str,
    request_sha256: str,
) -> dict[str, Any] | None:
    manifest = load_manifest(manifest_path)
    stage = "semantic_review" if review_kind == "semantic" else "red_team"
    if review_kind not in {"semantic", "red_team"}:
        raise RunContractError("review progress kind must be semantic or red_team")
    request, registered_sha256 = _registered_review_request(manifest, review_kind)
    stage_data = manifest.get("stages", {}).get(stage, {})
    metadata = stage_data.get("metadata") or {}
    if stage_data.get("status") in STAGE_FINAL:
        raise RunContractError(f"stage {stage} is final; progress writer rejected")
    if (
        invocation_id != request.get("invocation_id")
        or invocation_id != metadata.get("invocation_id")
        or request_sha256 != registered_sha256
        or request_sha256 != metadata.get("request_sha256")
    ):
        raise RunContractError("stale progress writer rejected")
    state = metadata.get("progress_state")
    return deepcopy(state) if isinstance(state, dict) else None


def update_review_progress(
    manifest_path: str | Path,
    review_kind: str,
    invocation_id: str,
    request_sha256: str,
    state_path: str | Path,
    fingerprint: dict[str, Any],
    agent_status: str,
    evaluator: Callable[..., tuple[dict[str, Any], str]],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    """Evaluate and commit progress from the authoritative manifest under one lock."""
    if review_kind not in {"semantic", "red_team"}:
        raise RunContractError("review progress kind must be semantic or red_team")
    stage = "semantic_review" if review_kind == "semantic" else "red_team"
    path = Path(manifest_path)
    with locked_manifest(path) as (manifest, expected_manifest_sha256):
        request, registered_sha256 = _registered_review_request(manifest, review_kind)
        existing = manifest.get("stages", {}).get(stage, {})
        if existing.get("status") in STAGE_FINAL:
            raise RunContractError(f"stage {stage} is final; progress writer rejected")
        if existing.get("status") != "running":
            raise RunContractError(f"stage {stage} is not running")
        metadata = dict(existing.get("metadata") or {})
        if (
            invocation_id != request.get("invocation_id")
            or invocation_id != metadata.get("invocation_id")
            or request_sha256 != registered_sha256
            or request_sha256 != metadata.get("request_sha256")
        ):
            raise RunContractError("stale progress writer rejected")
        previous_state = metadata.get("progress_state")
        next_state, decision = evaluator(
            previous_state if isinstance(previous_state, dict) else None,
            fingerprint,
            agent_status,
            review_kind=review_kind,
        )
        metadata.update(
            {
                "progress_decision": decision,
                "progress_state_path": str(Path(state_path).resolve()),
                "progress_state": deepcopy(next_state),
                "progress_fingerprint": deepcopy(
                    next_state.get("previous_fingerprint")
                ),
                "reminder_sent": bool(next_state.get("reminder_sent", False)),
            }
        )
        current = _aware_now(manifest["timezone"], now)
        stage_status = {
            "declare_lost": "failed",
            "degraded_timeout": "degraded_timeout",
        }.get(decision, "running")
        _record_stage_in_manifest(
            manifest,
            stage,
            stage_status,
            artifact_path=None,
            input_sha256=None,
            metadata=metadata,
            current=current,
        )
        commit_manifest(path, manifest, expected_manifest_sha256)
    return deepcopy(next_state), decision


def validate_review_receipt(
    receipt: dict[str, Any],
    manifest_path: str | Path,
    refined_path: str | Path,
    *,
    expected_kind: str | None = None,
) -> None:
    manifest = load_manifest(manifest_path)
    refined_file = Path(refined_path)
    refined = load_json(refined_file, {})
    if receipt.get("contract_version") not in {"1.0", "review-receipt/1.0"}:
        raise RunContractError("invalid review receipt contract_version")
    if receipt.get("run_id") != manifest.get("run_id"):
        raise RunContractError("review receipt run_id mismatch")
    review_kind = receipt.get("review_kind")
    if expected_kind is not None and review_kind != expected_kind:
        raise RunContractError("review receipt review_kind mismatch")
    allowed_statuses = {"passed"} if review_kind != "red_team" else {"passed", "not_required"}
    if receipt.get("status") not in allowed_statuses:
        raise RunContractError("review receipt status is not acceptable")
    if receipt.get("reviewer_kind") == "heuristic":
        raise RunContractError("heuristic reviewer cannot authorize a formal briefing")
    request, request_sha = _registered_review_request(manifest, str(review_kind))
    allowed_reviewer = {
        "semantic": {"semantic_model"},
        "red_team": {"logic_adversary", "deterministic_gate"},
    }.get(str(review_kind), set())
    if receipt.get("reviewer_kind") not in allowed_reviewer:
        raise RunContractError("review receipt reviewer_kind is not authorized")
    if receipt.get("reviewer_kind") == "deterministic_gate" and (
        review_kind != "red_team"
        or request.get("deterministic_fast_path") is not True
        or request.get("review_mode") != "no_l4_fast_path"
    ):
        raise RunContractError("deterministic reviewer is not authorized for this request")
    if review_kind == "semantic":
        if request.get("review_mode") != "registered_evidence_batch":
            raise RunContractError("semantic review request mode is invalid")
    else:
        semantic_receipt_path = Path(
            str(
                (request.get("execution_packet") or {}).get(
                    "bound_semantic_receipt_path"
                )
                or ""
            )
        )
        semantic_receipt = load_json(semantic_receipt_path, {})
        expected_scope = review_scope(refined, semantic_receipt)
        for field, expected in expected_scope.items():
            if request.get(field) != expected:
                raise RunContractError(f"red-team review request {field} mismatch")
        if (
            expected_scope["review_mode"] == "no_l4_fast_path"
            and receipt.get("status") != "not_required"
        ):
            raise RunContractError(
                "deterministic no-L4 red-team receipt must be not_required"
            )
        if (
            expected_scope["review_mode"] in {"targeted_review", "l4_full_review"}
            and receipt.get("status") != "passed"
        ):
            raise RunContractError(
                "logic-adversary red-team receipt must be passed"
            )
        if (
            expected_scope["review_mode"] in {"no_l4_fast_path", "targeted_review"}
            and request.get("max_turns") != 1
        ):
            raise RunContractError("no-L4 red-team request must use one turn")
        if (
            receipt.get("reviewer_kind") == "deterministic_gate"
            and not _deterministic_red_team_fast_path(refined, semantic_receipt)
        ):
            raise RunContractError(
                "deterministic red-team fast-path conditions are not met"
            )
    if receipt.get("request_sha256") != request_sha:
        raise RunContractError("review receipt request_sha256 mismatch")
    for field in ("reviewer_id", "invocation_id", "challenge"):
        if not str(receipt.get(field) or "").strip():
            raise RunContractError(f"review receipt {field} is required")
        if receipt.get(field) != request.get(field):
            raise RunContractError(f"review receipt {field} mismatch")
    if receipt.get("reviewer_kind") != request.get("reviewer_kind"):
        raise RunContractError("review receipt reviewer_kind mismatch")
    turns_used = receipt.get("turns_used")
    deterministic_receipt = receipt.get("reviewer_kind") == "deterministic_gate"
    valid_turns = (
        turns_used == 0
        if deterministic_receipt
        else isinstance(turns_used, int)
        and not isinstance(turns_used, bool)
        and 1 <= turns_used <= int(request.get("max_turns", 0))
    )
    if not valid_turns:
        raise RunContractError("review receipt turns_used exceeds request")
    if receipt.get("halt_condition_met") is not True:
        raise RunContractError("review receipt halt_condition_met must be true")
    baseline_sha = manifest.get("stages", {}).get("baseline", {}).get("artifact_sha256")
    if receipt.get("baseline_sha256") != baseline_sha:
        raise RunContractError("review receipt baseline_sha256 mismatch")
    if review_kind == "semantic" and receipt.get("input_bundle_sha256") != review_input_bundle_sha256(manifest):
        raise RunContractError("semantic receipt input_bundle_sha256 mismatch")
    if review_kind == "red_team" and request.get("refined_sha256") != file_sha256(refined_file):
        raise RunContractError("review request refined_sha256 mismatch")
    if receipt.get("output_sha256") != file_sha256(refined_file):
        raise RunContractError("review receipt output_sha256 mismatch")
    candidate_lineage: dict[str, dict[str, Any]] = {}
    candidate_hashes: dict[str, set[str]] = {}
    validated_access: list[tuple[str, str, str, str, str, int | None]] = []
    if review_kind == "semantic":
        candidate_lineage = registered_candidate_lineage(manifest)
        candidate_hashes = {
            reference: set(entry["object_hashes"])
            for reference, entry in candidate_lineage.items()
        }
        access_log = receipt.get("access_log")
        if not isinstance(access_log, list) or (refined.get("top_10") and not access_log):
            raise RunContractError("semantic receipt access_log is required for retained items")
        validated_access = [
            _validate_access_log_entry(
                access,
                index,
                path_prefix="semantic receipt access_log",
            )
            for index, access in enumerate(access_log)
        ]
        mapped_requested_urls: list[str] = []
        for index, item in enumerate(refined.get("top_10", [])):
            access = item.get("access_check")
            if not isinstance(access, dict):
                raise RunContractError(f"refined item {index} access_check is missing")
            evidence = _validate_access_log_entry(
                access,
                index,
                path_prefix="refined item access_check",
            )
            if evidence[0] != "verified":
                raise RunContractError(f"refined item {index} access_check is not verified")
            item_url = normalize_url(str(item.get("url") or ""))
            if evidence[3] != item_url:
                raise RunContractError(
                    f"refined item {index} access requested_url does not match item url"
                )
            if evidence not in validated_access:
                raise RunContractError(
                    f"refined item {index} access_check is absent from semantic access_log"
                )
            mapped_requested_urls.append(evidence[3])
        if len(mapped_requested_urls) != len(set(mapped_requested_urls)):
            raise RunContractError(
                "semantic receipt access mappings must be unique per retained item"
            )
        provenance = receipt.get("data_provenance")
        expected_provenance = {
            "input_bundle_sha256": review_input_bundle_sha256(manifest),
            "access_log_sha256": hashlib.sha256(
                canonical_json_bytes(access_log)
            ).hexdigest(),
        }
        if not isinstance(provenance, dict) or any(
            provenance.get(field) != value
            for field, value in expected_provenance.items()
        ):
            raise RunContractError("semantic receipt data_provenance mismatch")
    expected_hashes = sorted(item_hash(item) for item in refined.get("top_10", []))
    actual_hashes = sorted(str(value) for value in receipt.get("reviewed_item_hashes", []))
    if review_kind == "semantic" and actual_hashes != expected_hashes:
        raise RunContractError("review receipt item hashes do not match refined items")
    if review_kind == "semantic":
        bindings = receipt.get("lineage_bindings")
        if not isinstance(bindings, list):
            raise RunContractError("semantic receipt lineage_bindings is required")
        by_output: dict[str, dict[str, Any]] = {}
        bound_candidates_by_output: dict[str, list[dict[str, Any]]] = {}
        for binding in bindings:
            if not isinstance(binding, dict):
                raise RunContractError("semantic receipt lineage binding must be an object")
            output_hash = str(binding.get("output_item_sha256") or "")
            if output_hash in by_output:
                raise RunContractError("semantic receipt has duplicate lineage binding")
            inputs = binding.get("inputs")
            if not isinstance(inputs, list) or not inputs:
                raise RunContractError("semantic receipt lineage binding inputs are required")
            resolved_candidates: list[dict[str, Any]] = []
            for value in inputs:
                if not isinstance(value, dict):
                    raise RunContractError("semantic receipt lineage input is invalid")
                reference = str(value.get("candidate_ref") or "")
                object_hash = str(value.get("candidate_object_sha256") or "")
                if (
                    not reference.startswith("cand-")
                    or len(object_hash) != 64
                ):
                    raise RunContractError("semantic receipt lineage input is invalid")
                if object_hash not in candidate_hashes.get(reference, set()):
                    raise RunContractError(
                        "semantic receipt lineage candidate hash does not match registered candidate"
                    )
                resolved_candidates.append(
                    candidate_lineage[reference]["objects"][object_hash]
                )
            by_output[output_hash] = binding
            bound_candidates_by_output[output_hash] = resolved_candidates
        if set(by_output) != set(expected_hashes):
            raise RunContractError("semantic receipt lineage outputs do not match final items")
        for item in refined.get("top_10", []):
            output_hash = item_hash(item)
            binding = by_output[output_hash]
            bound_refs = sorted(
                str(value.get("candidate_ref")) for value in binding["inputs"]
            )
            item_refs = sorted(str(value) for value in item.get("candidate_refs", []))
            if not item_refs or bound_refs != item_refs:
                raise RunContractError(
                    "semantic receipt lineage inputs do not match item candidate_refs"
                )
            try:
                item_evidence = (
                    normalize_url(str(item.get("url") or "")),
                    str(item.get("title") or ""),
                    str(item.get("source") or ""),
                    normalize_published_at(str(item.get("published_at") or "")),
                    str(item.get("published_at_source") or ""),
                )
            except RunContractError as exc:
                raise RunContractError(
                    "semantic receipt output evidence is invalid"
                ) from exc
            resolved_candidates = bound_candidates_by_output[output_hash]
            matching_candidates: list[dict[str, Any]] = []
            for candidate in resolved_candidates:
                try:
                    candidate_evidence = (
                        normalize_url(str(candidate.get("url") or "")),
                        str(candidate.get("title") or ""),
                        str(candidate.get("source") or ""),
                        normalize_published_at(
                            str(candidate.get("published_at") or "")
                        ),
                        str(candidate.get("published_at_source") or ""),
                    )
                except RunContractError:
                    continue
                if candidate_evidence == item_evidence:
                    matching_candidates.append(candidate)
            if not matching_candidates:
                raise RunContractError(
                    "semantic receipt output evidence does not match a bound candidate"
                )
            _validate_bound_candidate_source_type(item, matching_candidates)
            registered_access_evidence = []
            for candidate_index, candidate in enumerate(matching_candidates):
                if not isinstance(candidate.get("access_check"), dict):
                    continue
                try:
                    registered_access_evidence.append(
                        _validate_access_log_entry(
                            candidate["access_check"],
                            candidate_index,
                            path_prefix="bound candidate access_check",
                        )
                    )
                except RunContractError:
                    continue
            if registered_access_evidence:
                item_access_evidence = _validate_access_log_entry(
                    item.get("access_check"),
                    0,
                    path_prefix="refined item bound access_check",
                )
                if item_access_evidence not in registered_access_evidence:
                    raise RunContractError(
                        "semantic receipt output access_check does not match exact bound candidate evidence"
                    )
            if item.get("corroboration_status") == "multi_independent":
                _validate_multi_independent_lineage(
                    item,
                    resolved_candidates,
                    validated_access,
                )
    if review_kind == "red_team" and not set(actual_hashes).issubset(set(expected_hashes)):
        raise RunContractError("red-team receipt contains an unknown item hash")
    _parse_aware_datetime(receipt.get("completed_at"), "review receipt completed_at")
    if review_kind == "red_team" and receipt.get("status") == "not_required":
        if any(item.get("intelligence_level") == "L4" for item in refined.get("top_10", [])):
            raise RunContractError("red-team review is required for L4 items")
        if actual_hashes:
            raise RunContractError("not-required red-team receipt cannot claim reviewed items")
    if review_kind == "red_team" and receipt.get("status") == "passed":
        l4_hashes = {
            item_hash(item)
            for item in refined.get("top_10", [])
            if item.get("intelligence_level") == "L4"
        }
        if not l4_hashes.issubset(set(actual_hashes)):
            raise RunContractError("red-team receipt does not cover every L4 item")
        if request.get("review_mode") == "targeted_review":
            targeted_hashes = {
                str(value)
                for field in ("major_signal_item_hashes", "conflict_item_hashes")
                for value in request.get(field, [])
            }
            if set(actual_hashes) != targeted_hashes:
                raise RunContractError(
                    "targeted red-team receipt does not exactly cover its scope"
                )


def validate_semantic_draft(
    manifest_path: str | Path,
    refined_path: str | Path,
    semantic_receipt_path: str | Path,
) -> list[str]:
    """Validate a semantic draft before red-team registration.

    The synthetic red-team block only exercises the complete briefing schema.
    It is never registered in the run manifest or written to an archive.
    """
    manifest = load_manifest(manifest_path)
    refined_file = Path(refined_path)
    receipt = load_json(Path(semantic_receipt_path), {})
    validate_review_receipt(
        receipt,
        manifest_path,
        refined_file,
        expected_kind="semantic",
    )
    refined = load_json(refined_file, {})
    expected_identity = {
        "run_id": manifest.get("run_id"),
        "report_date": manifest.get("report_date"),
        "window": manifest.get("window"),
        "topic": manifest.get("topic"),
        "region": manifest.get("region"),
    }
    for field, expected in expected_identity.items():
        if refined.get(field) != expected:
            raise RunContractError(f"semantic draft {field} mismatch")

    validate_registered_pipeline_summary(refined, manifest)
    validate_semantic_history(refined, manifest)

    created_at = _parse_aware_datetime(
        manifest.get("created_at"), "run manifest created_at"
    )
    generated_at = _parse_aware_datetime(
        refined.get("generated_at"), "semantic draft generated_at"
    )
    if generated_at < created_at:
        raise RunContractError(
            "semantic draft generated_at cannot precede run creation"
        )
    current = _aware_now(str(manifest["timezone"]))
    if generated_at > current.astimezone(generated_at.tzinfo) + timedelta(minutes=5):
        raise RunContractError(
            "semantic draft generated_at is unreasonably in the future"
        )

    items = refined.get("top_10")
    if not isinstance(items, list):
        raise RunContractError("semantic draft top_10 must be a list")
    item_hashes = [item_hash(item) for item in items]
    l4_hashes = [
        item_hash(item)
        for item in items
        if isinstance(item, dict) and item.get("intelligence_level") == "L4"
    ]
    supplement_stage = manifest.get("stages", {}).get("supplemental", {})
    supplement_status = (
        "degraded" if supplement_stage.get("status") == "degraded" else "completed"
    )
    if supplement_stage.get("metadata", {}).get("result_status") == "no_increment":
        supplement_status = "no_increment"

    payload = deepcopy(refined)
    payload["pipeline"] = {
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "supplement_status": supplement_status,
        "semantic_review": {
            "status": receipt["status"],
            "reviewer_kind": receipt["reviewer_kind"],
            "reviewer_id": receipt["reviewer_id"],
            "invocation_id": receipt["invocation_id"],
            "request_sha256": receipt["request_sha256"],
            "turns_used": receipt["turns_used"],
            "halt_condition_met": receipt["halt_condition_met"],
            "input_bundle_sha256": receipt["input_bundle_sha256"],
            "access_log_sha256": receipt["data_provenance"]["access_log_sha256"],
            "verified_access_count": len(
                {
                    normalize_url(
                        str((item.get("access_check") or {}).get("requested_url") or "")
                    )
                    for item in items
                    if isinstance(item, dict)
                }
            ),
            "output_sha256": receipt["output_sha256"],
            "reviewed_item_hashes": deepcopy(receipt["reviewed_item_hashes"]),
            "lineage_bindings": deepcopy(receipt["lineage_bindings"]),
        },
        "red_team": {
            "status": "passed" if l4_hashes else "not_required",
            "reviewer_kind": "logic_adversary",
            "reviewer_id": "SemanticDraftGate",
            "invocation_id": "semantic-draft-gate",
            "request_sha256": "0" * 64,
            "turns_used": 1,
            "halt_condition_met": True,
            "covered_item_hashes": l4_hashes,
        },
    }
    from briefing_gate import validate_briefing_data

    errors, warnings = validate_briefing_data(payload)
    if errors:
        raise RunContractError("semantic draft gate failed: " + "; ".join(errors))
    if sorted(item_hashes) != sorted(receipt.get("reviewed_item_hashes", [])):
        raise RunContractError("semantic draft reviewed item hashes mismatch")
    return warnings


def validate_red_team_draft(
    manifest_path: str | Path,
    refined_path: str | Path,
    semantic_receipt_path: str | Path,
    red_team_receipt_path: str | Path,
) -> list[str]:
    """Validate a red-team draft before immutable publication."""
    warnings = validate_semantic_draft(
        manifest_path,
        refined_path,
        semantic_receipt_path,
    )
    manifest = load_manifest(manifest_path)
    receipt_file = Path(red_team_receipt_path)
    _validate_review_execution_paths(
        manifest,
        "red_team",
        refined_path,
        receipt_file,
        allow_draft_paths=True,
    )
    validate_review_receipt(
        load_json(receipt_file, {}),
        manifest_path,
        refined_path,
        expected_kind="red_team",
    )
    return warnings


def register_review_receipt(
    manifest_path: str | Path,
    refined_path: str | Path,
    receipt_path: str | Path,
    stage: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if stage not in {"semantic_review", "red_team"}:
        raise RunContractError("review receipt stage must be semantic_review or red_team")
    expected_kind = "semantic" if stage == "semantic_review" else "red_team"
    manifest = load_manifest(manifest_path)
    if manifest.get("stages", {}).get(stage, {}).get("status") in STAGE_FINAL:
        raise RunContractError(f"stage {stage} is final; review receipt rejected")
    receipt_file = Path(receipt_path)
    receipt = load_json(receipt_file, {})
    _validate_review_execution_paths(
        manifest,
        expected_kind,
        refined_path,
        receipt_file,
        allow_draft_paths=False,
    )
    validate_review_receipt(
        receipt,
        manifest_path,
        refined_path,
        expected_kind=expected_kind,
    )
    stage_status = "completed" if receipt["status"] == "passed" else "not_required"
    manifest = load_manifest(manifest_path)
    request, _ = _registered_review_request(manifest, expected_kind)
    started_at = _parse_aware_datetime(
        request.get("created_at"), "review request created_at"
    )
    completed_at = _parse_aware_datetime(
        receipt.get("completed_at"), "review receipt completed_at"
    )
    registered_at = _aware_now(manifest["timezone"], now)
    if completed_at < started_at:
        raise RunContractError("review receipt completed_at cannot precede request creation")
    if completed_at > registered_at:
        raise RunContractError("review receipt completed_at cannot follow registration")
    request_to_receipt_seconds = (completed_at - started_at).total_seconds()
    receipt_to_registration_seconds = (registered_at - completed_at).total_seconds()
    request_to_registration_seconds = (registered_at - started_at).total_seconds()
    return record_stage(
        manifest_path,
        stage,
        stage_status,
        artifact_path=receipt_file,
        input_sha256=file_sha256(refined_path),
        metadata={
            "review_kind": expected_kind,
            "reviewer_kind": receipt.get("reviewer_kind"),
            "reviewed_item_hashes": receipt.get("reviewed_item_hashes", []),
            "output_sha256": receipt.get("output_sha256"),
            "review_mode": request.get("review_mode"),
            "max_turns": request.get("max_turns"),
            "turns_used": receipt.get("turns_used"),
            "elapsed_seconds": round(request_to_receipt_seconds, 3),
            "request_to_receipt_seconds": round(request_to_receipt_seconds, 3),
            "receipt_to_registration_seconds": round(
                receipt_to_registration_seconds, 3
            ),
            "request_to_registration_seconds": round(
                request_to_registration_seconds, 3
            ),
        },
        now=registered_at,
    )


def register_review_bundle(
    manifest_path: str | Path,
    refined_path: str | Path,
    semantic_receipt_path: str | Path,
    red_team_receipt_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    semantic_path = Path(semantic_receipt_path)
    red_team_path = Path(red_team_receipt_path)
    semantic = load_json(semantic_path, {})
    red_team = load_json(red_team_path, {})
    manifest = load_manifest(manifest_path)
    _validate_review_execution_paths(
        manifest,
        "semantic",
        refined_path,
        semantic_path,
        allow_draft_paths=False,
    )
    _validate_review_execution_paths(
        manifest,
        "red_team",
        refined_path,
        red_team_path,
        allow_draft_paths=False,
    )
    validate_review_receipt(
        semantic,
        manifest_path,
        refined_path,
        expected_kind="semantic",
    )
    validate_review_receipt(
        red_team,
        manifest_path,
        refined_path,
        expected_kind="red_team",
    )

    supplied = {
        "semantic_review": semantic_path,
        "red_team": red_team_path,
    }
    for stage, path in supplied.items():
        manifest = load_manifest(manifest_path)
        existing = manifest.get("stages", {}).get(stage, {})
        if existing.get("status") in STAGE_FINAL:
            if existing.get("status") == "failed":
                raise RunContractError(f"stage {stage} is failed and cannot be resumed")
            if existing.get("artifact_sha256") != file_sha256(path):
                raise RunContractError(
                    f"stage {stage} is terminal with a different receipt"
                )
            continue
        register_review_receipt(
            manifest_path,
            refined_path,
            path,
            stage,
            now=now,
        )
    return load_manifest(manifest_path)
