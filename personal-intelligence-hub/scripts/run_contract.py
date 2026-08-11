from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from history_manager import normalize_url
from hub_utils import HUB_DIR, RUNTIME_DIR, atomic_dump_json, load_json


CONTRACT_VERSION = "1.0"
CURRENT_SCHEMA_PATH = HUB_DIR / "references" / "briefing_schema.json"
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


def candidate_ref(url: str) -> str:
    normalized = normalize_url(str(url))
    if not normalized:
        raise RunContractError("candidate URL is required")
    return "cand-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def candidate_object_hash(candidate: dict[str, Any]) -> str:
    bound = deepcopy(candidate)
    bound.pop("candidate_object_sha256", None)
    return hashlib.sha256(canonical_json_bytes(bound)).hexdigest()


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
        ".md",
        ".txt",
        ".py",
        ".ps1",
        ".sh",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".tsv",
        ".html",
        ".css",
        ".js",
        ".ts",
    }:
        text = data.decode("utf-8")
        data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def validate_resource_manifest(manifest_path: str | Path, skill_path: str | Path) -> None:
    path = Path(manifest_path)
    root = Path(skill_path).resolve().parent
    payload = load_json(path, {})
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 2
        or payload.get("skill") != root.name
    ):
        raise RunContractError("skill resource manifest identity is invalid")
    if payload.get("missing_declared_dependencies"):
        raise RunContractError("skill resource manifest has missing dependencies")
    declared: list[tuple[str, str]] = []
    skill_name = str(payload.get("skill_md") or "SKILL.md")
    declared.append((skill_name, str(payload.get("skill_md_sha256") or "")))
    for record in payload.get("top_level_file_hashes", []):
        if isinstance(record, dict):
            declared.append((str(record.get("path") or ""), str(record.get("sha256") or "")))
    for record in payload.get("declared_local_dependencies", []):
        if isinstance(record, dict) and record.get("exists") is True:
            declared.append((str(record.get("path") or ""), str(record.get("sha256") or "")))
    seen: set[str] = set()
    for relative, expected in declared:
        normalized = relative.replace("\\", "/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
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
    if any(values[field] in {None, ""} for field in (
        "run_id",
        "baseline_sha256",
        "candidate_pool_sha256",
        "history_snapshot_sha256",
        "supplement_sha256",
    )):
        raise RunContractError("review input bundle is incomplete")
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
        now=now,
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
    published_raw = str(candidate["published_at"]).strip()
    try:
        if len(published_raw) == 10:
            published_day = date.fromisoformat(published_raw)
        else:
            published_dt = _parse_aware_datetime(
                published_raw, f"supplement candidate {index}.published_at"
            )
            published_day = published_dt.astimezone(ZoneInfo(str(window["timezone"]))).date()
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
        _parse_aware_datetime(result.get("completed_at"), "supplement result completed_at")
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
        },
        now=now,
    )
    return aggregate_path, aggregate


def build_review_request(
    manifest_path: str | Path,
    refined_path: str | Path | None,
    review_kind: str,
    *,
    semantic_receipt_path: str | Path | None = None,
    max_turns: int = 3,
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
    if manifest.get("artifacts", {}).get(artifact_name) is not None:
        raise RunContractError(f"{review_kind} review request is immutable once registered")
    refined_file = Path(refined_path) if refined_path is not None else None
    if review_kind == "red_team" and (
        refined_file is None or not refined_file.is_file()
    ):
        raise RunContractError("refined core is required before red-team invocation")
    if review_kind == "red_team":
        if semantic_receipt_path is None:
            raise RunContractError(
                "validated semantic receipt is required before red-team invocation"
            )
        semantic_receipt = load_json(Path(semantic_receipt_path), {})
        validate_review_receipt(
            semantic_receipt,
            manifest_path,
            refined_file,
            expected_kind="semantic",
        )
    if not isinstance(max_turns, int) or not 1 <= max_turns <= 10:
        raise RunContractError("review request max_turns must be between 1 and 10")
    default_halt = (
        "所有最终条目完成语义评估并生成完整血缘映射，或发现阻断问题"
        if review_kind == "semantic"
        else "全部 L4 与重大资讯资格完成反证检查，或发现阻断问题"
    )
    halt = str(halt_condition or default_halt).strip()
    if not halt:
        raise RunContractError("review request halt_condition is required")
    current = _aware_now(manifest["timezone"], now)
    request: dict[str, Any] = {
        "contract_version": "review-request/1.0",
        "run_id": manifest["run_id"],
        "review_kind": review_kind,
        "reviewer_kind": reviewer_kind,
        "reviewer_id": reviewer_id,
        "invocation_id": uuid.uuid4().hex,
        "challenge": uuid.uuid4().hex + uuid.uuid4().hex,
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "max_turns": max_turns,
        "halt_condition": halt,
        "created_at": current.isoformat(),
    }
    if review_kind == "semantic":
        request["input_bundle_sha256"] = review_input_bundle_sha256(manifest)
    else:
        request["refined_sha256"] = file_sha256(refined_file)
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
        request.get("contract_version") != "review-request/1.0"
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
                if (
                    not isinstance(value, dict)
                    or not str(value.get("candidate_ref") or "").startswith("cand-")
                    or len(str(value.get("candidate_object_sha256") or "")) != 64
                ):
                    raise RunContractError("semantic receipt lineage input is invalid")
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
        },
        now=now,
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
