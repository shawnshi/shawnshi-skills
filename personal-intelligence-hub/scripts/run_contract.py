from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time as monotonic_time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from history_manager import generate_event_id, load_recent_history, match_history, normalize_url
from hub_utils import HUB_DIR, RUNTIME_DIR, atomic_dump_json, load_json


CONTRACT_VERSION = "1.0"
STRICT_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
CURRENT_SCHEMA_PATH = HUB_DIR / "references" / "briefing_schema.json"
SUBAGENT_PROMPTS_PATH = HUB_DIR / "references" / "subagent_prompts.json"
STAGE_ORDER = ("baseline", "supplemental", "semantic_review", "red_team", "archive")
STAGE_TERMINAL = {
    "completed",
    "degraded",
    "skipped",
    "not_required",
}
STAGE_FINAL = STAGE_TERMINAL | {"failed"}
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


def review_scope(refined: dict[str, Any]) -> dict[str, Any]:
    items = refined.get("top_10", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise RunContractError("refined core top_10 must be a list of objects")
    l4_hashes = sorted(
        item_hash(item) for item in items if item.get("intelligence_level") == "L4"
    )
    major_signal_hashes = sorted(
        item_hash(item) for item in items if item.get("major_signal") is True
    )
    return {
        "review_mode": "l4_full_review" if l4_hashes else "no_l4_fast_path",
        "l4_item_hashes": l4_hashes,
        "major_signal_item_hashes": major_signal_hashes,
    }


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
    registered: dict[str, dict[str, set[str]]] = {}
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

    results = supplement.get("results") if isinstance(supplement.get("results"), list) else []
    lane_failures = sorted(
        {
            str(result.get("lane"))
            for result in results
            if isinstance(result, dict)
            and (
                result.get("status") in {"degraded", "failed"}
                or int((result.get("coverage") or {}).get("failed", 0)) > 0
            )
        }
    )
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

    supplemental_candidates = sum(
        len(result.get("candidates", []))
        for result in results
        if isinstance(result, dict) and isinstance(result.get("candidates"), list)
    )
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
    manifest: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "run_id": identifier,
        "skill_sha256": file_sha256(skill_path),
        "skill_bundle_sha256": skill_bundle_sha256(skill_path),
        "skill_path": str(skill_path.resolve()),
        "resource_manifest_sha256": file_sha256(bundle_manifest),
        "resource_manifest_path": str(bundle_manifest.resolve()),
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
    event = {"stage": stage, "status": status, "recorded_at": current.isoformat()}
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
        normalized_gaps.append(
            {
                "gap_id": gap_id,
                "lane": lane,
                "query_scope": query_scope,
                "max_turns": max_turns,
                "halt_condition": halt_condition,
            }
        )
    if not normalized_gaps:
        raise RunContractError("supplement request requires at least one gap")
    current = _aware_now(manifest["timezone"], now)
    run_dir = Path(manifest["run_dir"]).resolve()
    request_path = run_dir / "supplement_request.json"
    prompt_config = load_json(SUBAGENT_PROMPTS_PATH, {})
    required_packet_fields = (
        prompt_config.get("execution_policy", {})
        .get("context_transfer", {})
        .get("required_fields")
        if isinstance(prompt_config, dict)
        else None
    )
    if not isinstance(required_packet_fields, list) or not required_packet_fields:
        raise RunContractError("supplement execution packet contract is missing")
    bound_input_paths = {
        "baseline": {
            "path": str(Path(manifest["stages"]["baseline"]["artifact_path"]).resolve()),
            "sha256": str(baseline_sha),
        },
        "candidate_pool": {
            "path": str(candidate_path.resolve()),
            "sha256": str(candidate_record["artifact_sha256"]),
        },
    }
    history_record = manifest.get("artifacts", {}).get("history_snapshot")
    if isinstance(history_record, dict) and history_record.get("artifact_path"):
        bound_input_paths["history_snapshot"] = {
            "path": str(Path(history_record["artifact_path"]).resolve()),
            "sha256": str(history_record.get("artifact_sha256") or ""),
        }
    execution_packets = []
    for gap in normalized_gaps:
        safe_gap_id = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", gap["gap_id"])
        if safe_gap_id is None:
            raise RunContractError("supplement gap_id is not safe for an output path")
        final_path = run_dir / f"supplement_{gap['gap_id']}.json"
        draft_path = run_dir / f"supplement_{gap['gap_id']}.draft.json"
        packet = {
            "contract_version": "supplement-execution-packet/1.0",
            "self_contained": True,
            "skill_path": str(Path(manifest["skill_path"]).resolve()),
            "prompt_config_path": str(SUBAGENT_PROMPTS_PATH.resolve()),
            "prompt_config_sha256": file_sha256(SUBAGENT_PROMPTS_PATH),
            "run_manifest_path": str(Path(manifest_path).resolve()),
            "registered_request_path": str(request_path.resolve()),
            "bound_input_paths": deepcopy(bound_input_paths),
            "assigned_gap_ids": [gap["gap_id"]],
            "assigned_lanes": [gap["lane"]],
            "output_paths": {
                "result": str(final_path.resolve()),
                "draft": str(draft_path.resolve()),
            },
            "output_path_by_gap": {gap["gap_id"]: str(final_path.resolve())},
            "write_authorization": {
                "mode": "exact_final_and_sibling_temporary_file",
                "final_paths": [str(final_path.resolve())],
                "draft_paths": [str(draft_path.resolve())],
                "forbid_other_writes": True,
            },
            "per_gap_max_turns": {gap["gap_id"]: gap["max_turns"]},
            "per_gap_halt_condition": {gap["gap_id"]: gap["halt_condition"]},
            "publication": {
                "mode": "sibling_temporary_file_then_atomic_replace",
                "artifact_ready_message": "artifact_ready path=<path> sha256=<sha256>",
            },
        }
        missing_fields = sorted(set(required_packet_fields) - set(packet))
        if missing_fields:
            raise RunContractError(
                f"supplement execution packet missing declared fields: {missing_fields}"
            )
        execution_packets.append(packet)
    request = {
        "contract_version": "supplement-request/1.0",
        "run_id": manifest["run_id"],
        "baseline_sha256": baseline_sha,
        "candidate_pool_sha256": candidate_record["artifact_sha256"],
        "gap_ledger_sha256": hashlib.sha256(canonical_json_bytes(normalized_gaps)).hexdigest(),
        "created_at": current.isoformat(),
        "gaps": normalized_gaps,
        "execution_packets": execution_packets,
    }
    atomic_dump_json(request_path, request)
    record_run_artifact(
        manifest_path,
        "supplement_request",
        request_path,
        input_sha256=candidate_record["artifact_sha256"],
        metadata={"gap_count": len(normalized_gaps)},
        now=current,
    )
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


def register_supplement_results(
    manifest_path: str | Path,
    request_path: str | Path,
    result_paths: list[str | Path],
    *,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    manifest = require_stage(manifest_path, "baseline", {"completed", "degraded"})
    request_file = Path(request_path)
    request = load_json(request_file, {})
    if request.get("contract_version") != "supplement-request/1.0":
        raise RunContractError("invalid supplement request")
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
        authorized_paths = (packet.get("write_authorization") or {}).get("final_paths")
        if (
            Path(str(output_by_gap.get(gap_id) or "")).resolve() != expected_path
            or not isinstance(authorized_paths, list)
            or [Path(str(value)).resolve() for value in authorized_paths]
            != [expected_path]
        ):
            raise RunContractError("supplement execution packet output path mismatch")
        packet_paths[gap_id] = expected_path
    if set(packet_paths) != set(gaps):
        raise RunContractError("supplement execution packets do not cover every gap")

    results: list[dict[str, Any]] = []
    result_completed_at: list[datetime] = []
    seen: set[str] = set()
    global_access_evidence: list[tuple[str, str, int, dict[str, Any]]] = []
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
        if result_file.resolve() != packet_paths[gap_id]:
            raise RunContractError(
                "supplement result path does not match execution packet output path"
            )
        seen.add(gap_id)
        gap = gaps[gap_id]
        if result.get("lane") != gap.get("lane"):
            raise RunContractError("supplement result lane mismatch")
        status = result.get("status")
        if status not in {"completed", "no_increment", "degraded", "failed"}:
            raise RunContractError("supplement result has invalid status")
        infrastructure_failure = (
            status == "failed" and result.get("failure_kind") == "infrastructure"
        )
        if infrastructure_failure and not str(result.get("failure_reason") or "").strip():
            raise RunContractError(
                "infrastructure supplement failure requires failure_reason"
            )
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
        queries = result.get("executed_queries")
        if (
            not isinstance(queries, list)
            or (not queries and not infrastructure_failure)
            or any(not str(query).strip() for query in queries)
        ):
            raise RunContractError(
                "supplement result executed_queries must be a non-empty string list"
            )
        access_log = result.get("access_log")
        if not isinstance(access_log, list) or (
            not access_log and not infrastructure_failure
        ):
            raise RunContractError("supplement result access_log must be a non-empty list")
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
    _validate_access_retry_policy([entry[3] for entry in ordered_access])

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
            "result_status": aggregate_status,
            **timing,
        },
        now=current,
    )
    return aggregate_path, aggregate


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
            "refined_core": str(
                (run_dir / f"refined_core.{invocation_id}.draft.json").resolve()
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
        expected_validation = [
            "python",
            "-X",
            "utf8",
            str((HUB_DIR / "scripts" / "run_daily.py").resolve()),
            "validate-semantic-draft",
            "--manifest",
            str(Path(packet.get("run_manifest_path") or "").resolve()),
            "--refined",
            expected_drafts["refined_core"],
            "--semantic-receipt",
            expected_drafts["review_receipt"],
        ]
        if packet.get("validation_command") != expected_validation:
            return False
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
    if review_kind == "red_team":
        if semantic_receipt_path is None:
            raise RunContractError(
                "validated semantic receipt is required before red-team invocation"
            )
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
        scope = review_scope(load_json(refined_file, {}))
        if scope["review_mode"] == "no_l4_fast_path":
            max_turns = 1
    if review_kind == "semantic":
        default_halt = "所有最终条目批量完成语义评估并生成完整血缘映射，或发现阻断问题"
    elif scope and scope["review_mode"] == "no_l4_fast_path":
        default_halt = "确认绑定 core 无 L4 并完成重大资讯资格、日期、来源独立性与行动时序检查，或发现阻断问题"
    else:
        default_halt = "全部 L4 与重大资讯资格完成反证检查，或发现阻断问题"
    halt = str(halt_condition or default_halt).strip()
    if not halt:
        raise RunContractError("review request halt_condition is required")
    current = _aware_now(manifest["timezone"], now)
    prompt_config = load_json(SUBAGENT_PROMPTS_PATH, {})
    agent_contract = (
        prompt_config.get("review_agents", {}).get(reviewer_id)
        if isinstance(prompt_config, dict)
        else None
    )
    if not isinstance(agent_contract, dict):
        raise RunContractError(f"review prompt contract is missing for {reviewer_id}")
    prompt_sha256 = file_sha256(SUBAGENT_PROMPTS_PATH)
    if prompt_sha256 is None:
        raise RunContractError("review prompt configuration is missing")
    run_dir = Path(manifest["run_dir"]).resolve()
    invocation_id = uuid.uuid4().hex
    if review_kind == "semantic":
        output_paths = {
            "refined_core": str(run_dir / "refined_core.json"),
            "review_receipt": str(run_dir / "semantic_receipt.json"),
        }
        draft_paths = {
            "refined_core": str(run_dir / f"refined_core.{invocation_id}.draft.json"),
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
            "skill_root": str(HUB_DIR.resolve()),
            "prompt_config": {
                "path": str(SUBAGENT_PROMPTS_PATH.resolve()),
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
            "write_scope": sorted([*output_paths.values(), *draft_paths.values()]),
            "progress_messages": progress_messages,
            "artifact_ready_message": (
                "artifact_ready refined_core_path=<path> refined_core_sha256=<sha256> "
                "semantic_receipt_path=<path> semantic_receipt_sha256=<sha256>"
                if review_kind == "semantic"
                else "artifact_ready path=<path> sha256=<sha256>"
            ),
        },
    }
    if review_kind == "semantic":
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
        request["execution_packet"]["validation_command"] = [
            "python",
            "-X",
            "utf8",
            str((HUB_DIR / "scripts" / "run_daily.py").resolve()),
            "validate-semantic-draft",
            "--manifest",
            str(Path(manifest_path).resolve()),
            "--refined",
            draft_paths["refined_core"],
            "--semantic-receipt",
            draft_paths["review_receipt"],
        ]
    else:
        request["refined_sha256"] = file_sha256(refined_file)
        request["execution_packet"]["bound_refined_path"] = str(
            refined_file.resolve()
        )
        request.update(scope or {})
    request_path = Path(manifest["run_dir"]) / f"{review_kind}_review_request.json"
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
    return request_path, request


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
        _record_stage_in_manifest(
            manifest,
            stage,
            "failed" if decision == "declare_lost" else "running",
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
    allowed_reviewer = {
        "semantic": "semantic_model",
        "red_team": "logic_adversary",
    }.get(str(review_kind))
    if allowed_reviewer is None or receipt.get("reviewer_kind") != allowed_reviewer:
        raise RunContractError("review receipt reviewer_kind is not authorized")
    request, request_sha = _registered_review_request(manifest, str(review_kind))
    if review_kind == "semantic":
        if request.get("review_mode") != "registered_evidence_batch":
            raise RunContractError("semantic review request mode is invalid")
    else:
        expected_scope = review_scope(refined)
        for field, expected in expected_scope.items():
            if request.get(field) != expected:
                raise RunContractError(f"red-team review request {field} mismatch")
        if (
            expected_scope["review_mode"] == "no_l4_fast_path"
            and receipt.get("status") != "not_required"
        ):
            raise RunContractError(
                "no-L4 red-team receipt status must be not_required"
            )
        if (
            expected_scope["review_mode"] == "l4_full_review"
            and receipt.get("status") != "passed"
        ):
            raise RunContractError("L4 red-team receipt status must be passed")
        if (
            expected_scope["review_mode"] == "no_l4_fast_path"
            and request.get("max_turns") != 1
        ):
            raise RunContractError("no-L4 red-team request must use one turn")
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
    if (
        not isinstance(turns_used, int)
        or isinstance(turns_used, bool)
        or not 1 <= turns_used <= int(request.get("max_turns", 0))
    ):
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
