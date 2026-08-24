from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from history_manager import normalize_url
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


def registered_candidate_hashes(manifest: dict[str, Any]) -> dict[str, set[str]]:
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
    registered: dict[str, set[str]] = {}
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
            registered.setdefault(reference, set()).add(claimed_hash)
    return registered


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
            "source_attempted": int(baseline_coverage["source_attempted"])
            + int(supplement_coverage.get("attempted", 0)),
            "source_succeeded": int(baseline_coverage["source_succeeded"])
            + int(supplement_coverage.get("succeeded", 0)),
            "source_failed": int(baseline_coverage["source_failed"])
            + int(supplement_coverage.get("failed", 0)),
        }
        baseline_raw = int(baseline_coverage["raw_candidates"])
        baseline_dated = int(baseline_coverage["dated_candidates"])
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
            if isinstance(result, dict) and result.get("status") in {"degraded", "failed"}
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
    supplement = manifest.get("stages", {}).get("supplemental", {})
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
    if any(values[field] in {None, ""} for field in (
        "run_id",
        "baseline_sha256",
        "candidate_pool_sha256",
        "history_snapshot_sha256",
        "supplement_sha256",
    )):
        raise RunContractError("review input bundle is incomplete")
    if history_review and values["history_review_slice_sha256"] in {None, ""}:
        raise RunContractError("review input bundle history slice is incomplete")
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
        "history_snapshot",
        "history_review_slice",
        "candidate_pool",
        "supplement_request",
        "semantic_review_request",
        "red_team_request",
    }:
        raise RunContractError(f"unsupported run artifact: {name}")
    path = Path(manifest_path)
    manifest = load_manifest(path)
    before = {field: deepcopy(manifest[field]) for field in IMMUTABLE_FIELDS}
    artifact = Path(artifact_path)
    if not artifact.is_file():
        raise RunContractError(f"run artifact not found: {artifact}")
    digest = file_sha256(artifact)
    existing = manifest.setdefault("artifacts", {}).get(name)
    if existing:
        same_path = Path(str(existing.get("artifact_path") or "")).resolve() == artifact.resolve()
        if (
            existing.get("artifact_sha256") != digest
            or not same_path
            or existing.get("input_sha256") != input_sha256
        ):
            raise RunContractError(f"run artifact {name} is immutable once recorded")
        return manifest
    current = _aware_now(manifest["timezone"], now)
    manifest["artifacts"][name] = {
        "artifact_path": str(artifact.resolve()),
        "artifact_sha256": digest,
        "input_sha256": input_sha256,
        "recorded_at": current.isoformat(),
        "metadata": deepcopy(metadata or {}),
    }
    manifest["events"].append(
        {"stage": f"artifact:{name}", "status": "completed", "recorded_at": current.isoformat()}
    )
    for field, expected in before.items():
        if manifest[field] != expected:
            raise RunContractError(f"immutable run field changed: {field}")
    atomic_dump_json(path, manifest)
    return manifest


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
    manifest = load_manifest(path)
    before = {field: deepcopy(manifest[field]) for field in IMMUTABLE_FIELDS}
    existing_stage = manifest.get("stages", {}).get(stage, {})
    if existing_stage.get("status") in STAGE_TERMINAL:
        raise RunContractError(f"stage {stage} is immutable once terminal")
    _validate_predecessors(manifest, stage)
    allowed_statuses = STAGE_TERMINAL | {"running", "failed"}
    if status not in allowed_statuses:
        raise RunContractError(f"invalid stage status: {status}")
    current = _aware_now(manifest["timezone"], now)
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
    manifest["events"].append(
        {"stage": stage, "status": status, "recorded_at": current.isoformat()}
    )
    for field, expected in before.items():
        if manifest[field] != expected:
            raise RunContractError(f"immutable run field changed: {field}")
    atomic_dump_json(path, manifest)
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
        max_turns = int(gap.get("max_turns", 3))
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
    request = {
        "contract_version": "supplement-request/1.0",
        "run_id": manifest["run_id"],
        "baseline_sha256": baseline_sha,
        "candidate_pool_sha256": candidate_record["artifact_sha256"],
        "gap_ledger_sha256": hashlib.sha256(canonical_json_bytes(normalized_gaps)).hexdigest(),
        "created_at": current.isoformat(),
        "gaps": normalized_gaps,
    }
    request_path = Path(manifest["run_dir"]) / "supplement_request.json"
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


def _validate_supplement_candidate(
    candidate: Any,
    index: int,
    window: dict[str, Any],
) -> None:
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
    _parse_aware_datetime(
        access.get("checked_at"), f"supplement candidate {index}.access_check.checked_at"
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
    _parse_aware_datetime(candidate["retrieved_at"], f"supplement candidate {index}.retrieved_at")


def _validate_access_log_entry(
    access: Any,
    index: int,
    *,
    path_prefix: str = "supplement result access_log",
) -> tuple[str, str, str, str, str, int | None]:
    path = f"{path_prefix}[{index}]"
    if not isinstance(access, dict):
        raise RunContractError(f"{path} must be an object")
    status = access.get("status")
    if status not in {"verified", "blocked"}:
        raise RunContractError(f"{path}.status is invalid")
    checked_at = str(access.get("checked_at") or "")
    _parse_aware_datetime(checked_at, f"{path}.checked_at")
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
    if http_status is not None and not isinstance(http_status, int):
        raise RunContractError(f"{path}.http_status is invalid")
    if status == "verified" and method in {"http_get", "api"} and (
        not isinstance(http_status, int) or not 200 <= http_status < 400
    ):
        raise RunContractError(f"{path}.http_status does not prove successful access")
    return (
        status,
        checked_at,
        method,
        normalize_url(requested_url),
        normalize_url(final_url),
        http_status,
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

    results: list[dict[str, Any]] = []
    result_completed_at: list[datetime] = []
    seen: set[str] = set()
    degraded = False
    for raw_path in result_paths:
        result = load_json(Path(raw_path), {})
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
        seen.add(gap_id)
        gap = gaps[gap_id]
        if result.get("lane") != gap.get("lane"):
            raise RunContractError("supplement result lane mismatch")
        status = result.get("status")
        if status not in {"completed", "no_increment", "degraded", "failed"}:
            raise RunContractError("supplement result has invalid status")
        queries = result.get("executed_queries")
        if (
            not isinstance(queries, list)
            or not queries
            or any(not str(query).strip() for query in queries)
        ):
            raise RunContractError(
                "supplement result executed_queries must be a non-empty string list"
            )
        access_log = result.get("access_log")
        if not isinstance(access_log, list) or not access_log:
            raise RunContractError("supplement result access_log must be a non-empty list")
        validated_access = [
            _validate_access_log_entry(access, index)
            for index, access in enumerate(access_log)
        ]
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
            _validate_supplement_candidate(candidate, index, manifest["window"])
            candidate["candidate_id"] = candidate_ref(str(candidate["url"]))
            candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
            candidate_access = candidate["access_check"]
            candidate_evidence = (
                "verified",
                str(candidate_access["checked_at"]),
                str(candidate_access["method"]),
                normalize_url(str(candidate_access["requested_url"])),
                normalize_url(str(candidate_access["final_url"])),
                candidate_access.get("http_status"),
            )
            if candidate_evidence not in validated_access:
                raise RunContractError(
                    f"supplement candidate {index} access_check is absent from access_log"
                )
        coverage = result.get("coverage")
        if not isinstance(coverage, dict):
            raise RunContractError("supplement result coverage is required")
        try:
            attempted = int(coverage["attempted"])
            succeeded = int(coverage["succeeded"])
            failed = int(coverage["failed"])
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
        if not isinstance(turns_used, int) or not 1 <= turns_used <= int(gap["max_turns"]):
            raise RunContractError("supplement result exceeds max_turns")
        halt_met = result.get("halt_condition_met")
        if not isinstance(halt_met, bool):
            raise RunContractError("supplement result halt_condition_met must be boolean")
        if status in {"completed", "no_increment"} and not halt_met:
            raise RunContractError("terminal supplement result did not meet halt condition")
        if status == "completed" and not candidates:
            raise RunContractError("completed supplement result requires candidates")
        if status in {"no_increment", "failed"} and candidates:
            raise RunContractError(f"{status} supplement result cannot contain candidates")
        result_completed_at.append(
            _parse_aware_datetime(
                result.get("completed_at"), "supplement result completed_at"
            )
        )
        degraded = degraded or status in {"degraded", "failed"} or failed > 0
        results.append(deepcopy(result))

    if seen != set(gaps):
        missing = sorted(set(gaps) - seen)
        raise RunContractError(f"supplement results missing gaps: {missing}")
    existing_stage = manifest.get("stages", {}).get("supplemental", {})
    if existing_stage.get("status") in STAGE_TERMINAL:
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
    current = _aware_now(manifest["timezone"], now)
    request_started_at = _parse_aware_datetime(
        request.get("created_at"), "supplement request created_at"
    )
    latest_result_at = max(result_completed_at)
    earliest_result_at = min(result_completed_at)
    timing = {
        "request_to_registration_seconds": round(
            max(0.0, (current - request_started_at).total_seconds()), 3
        ),
        "latest_result_to_registration_seconds": round(
            max(0.0, (current - latest_result_at).total_seconds()), 3
        ),
        "result_completion_skew_seconds": round(
            max(0.0, (latest_result_at - earliest_result_at).total_seconds()), 3
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
    if not isinstance(max_turns, int) or not 1 <= max_turns <= 10:
        raise RunContractError("review request max_turns must be between 1 and 10")
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
    atomic_dump_json(request_path, request)
    record_run_artifact(
        manifest_path,
        artifact_name,
        request_path,
        input_sha256=request.get("input_bundle_sha256") or request.get("refined_sha256"),
        metadata={
            "review_kind": review_kind,
            "reviewer_kind": reviewer_kind,
            "reviewer_id": reviewer_id,
            "review_mode": request["review_mode"],
            "max_turns": request["max_turns"],
            "l4_item_count": len(request.get("l4_item_hashes", [])),
        },
        now=now,
    )
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
        candidate_hashes = registered_candidate_hashes(manifest)
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
        for binding in bindings:
            if not isinstance(binding, dict):
                raise RunContractError("semantic receipt lineage binding must be an object")
            output_hash = str(binding.get("output_item_sha256") or "")
            if output_hash in by_output:
                raise RunContractError("semantic receipt has duplicate lineage binding")
            inputs = binding.get("inputs")
            if not isinstance(inputs, list) or not inputs:
                raise RunContractError("semantic receipt lineage binding inputs are required")
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
            by_output[output_hash] = binding
        if set(by_output) != set(expected_hashes):
            raise RunContractError("semantic receipt lineage outputs do not match final items")
        for item in refined.get("top_10", []):
            binding = by_output[item_hash(item)]
            bound_refs = sorted(
                str(value.get("candidate_ref")) for value in binding["inputs"]
            )
            item_refs = sorted(str(value) for value in item.get("candidate_refs", []))
            if not item_refs or bound_refs != item_refs:
                raise RunContractError(
                    "semantic receipt lineage inputs do not match item candidate_refs"
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
    receipt_file = Path(receipt_path)
    receipt = load_json(receipt_file, {})
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
    request_to_receipt_seconds = max(
        0.0, (completed_at - started_at).total_seconds()
    )
    receipt_to_registration_seconds = max(
        0.0, (registered_at - completed_at).total_seconds()
    )
    request_to_registration_seconds = max(
        0.0, (registered_at - started_at).total_seconds()
    )
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
        if existing.get("status") in STAGE_TERMINAL:
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
