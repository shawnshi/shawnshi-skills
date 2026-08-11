from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from archive_transaction import (
    ArchiveCommitResult,
    ArchivePostcommitError,
    commit_briefing_pair,
)
from blackboard import finalize_briefing, update_phase
from briefing_gate import validate_briefing_data
from history_manager import load_recent_history, match_history, normalize_url, save_history_items
from hub_utils import HISTORY_PATH, HUB_DIR, NEWS_DIR, RUNTIME_DIR, atomic_dump_json
from run_contract import (
    RunContractError,
    candidate_object_hash,
    candidate_ref,
    file_sha256,
    item_hash,
    load_manifest,
    record_stage,
    require_stage,
    skill_bundle_sha256,
    validate_review_receipt,
)
from update_index import rebuild_history


TEMPLATE_PATH = HUB_DIR / "references" / "briefing_template.md"


class ForgeContractError(RuntimeError):
    pass


def _read_json_strict(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ForgeContractError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ForgeContractError(f"{label} must be a JSON object")
    return value


def _assert_core_identity(
    core: dict[str, Any],
    manifest: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    skill_path = Path(str(manifest.get("skill_path") or ""))
    if not skill_path.is_file() or file_sha256(skill_path) != manifest.get("skill_sha256"):
        raise ForgeContractError("skill contract bytes changed after the run was created")
    if skill_bundle_sha256(skill_path) != manifest.get("skill_bundle_sha256"):
        raise ForgeContractError("skill bundle bytes changed after the run was created")
    resource_manifest_path = Path(str(manifest.get("resource_manifest_path") or ""))
    if (
        not resource_manifest_path.is_file()
        or file_sha256(resource_manifest_path) != manifest.get("resource_manifest_sha256")
    ):
        raise ForgeContractError("skill resource manifest bytes changed after the run was created")
    expected = {
        "run_id": manifest["run_id"],
        "report_date": manifest["report_date"],
        "topic": manifest["topic"],
        "region": manifest["region"],
        "window": manifest["window"],
    }
    for field, value in expected.items():
        if core.get(field) != value:
            raise ForgeContractError(f"refined core {field} does not match run manifest")
    if core.get("schema_version") != "1.3":
        raise ForgeContractError("refined core schema_version must be 1.3")
    if str(core.get("model_used") or "").strip().lower() in {"", "heuristic"}:
        raise ForgeContractError("refined core must identify a non-heuristic semantic model")
    try:
        created_at = datetime.fromisoformat(str(manifest["created_at"]))
        generated_at = datetime.fromisoformat(str(core.get("generated_at") or ""))
    except ValueError as exc:
        raise ForgeContractError("run or refined generated_at is invalid") from exc
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() is None
        or generated_at.tzinfo is None
        or generated_at.utcoffset() is None
    ):
        raise ForgeContractError("run and refined timestamps must be timezone-aware")
    current = now or datetime.now(ZoneInfo(manifest["timezone"]))
    if current.tzinfo is None or current.utcoffset() is None:
        raise ForgeContractError("forge clock must be timezone-aware")
    if generated_at < created_at:
        raise ForgeContractError("refined generated_at cannot precede run creation")
    if generated_at > current.astimezone(generated_at.tzinfo) + timedelta(minutes=5):
        raise ForgeContractError("refined generated_at is unreasonably in the future")
    for index, item in enumerate(core.get("top_10", [])):
        for field in ("observed_at", "retrieved_at"):
            try:
                value = datetime.fromisoformat(str(item.get(field) or "").replace("Z", "+00:00"))
            except ValueError as exc:
                raise ForgeContractError(f"top_10[{index}].{field} is invalid") from exc
            if value.tzinfo is None or value.utcoffset() is None:
                raise ForgeContractError(f"top_10[{index}].{field} must be timezone-aware")
            if value < created_at.astimezone(value.tzinfo) or value > generated_at.astimezone(value.tzinfo):
                raise ForgeContractError(
                    f"top_10[{index}].{field} is outside the run chronology"
                )
        access_value = (item.get("access_check") or {}).get("checked_at")
        try:
            checked_at = datetime.fromisoformat(str(access_value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise ForgeContractError(
                f"top_10[{index}].access_check.checked_at is invalid"
            ) from exc
        if (
            checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or checked_at < created_at.astimezone(checked_at.tzinfo)
            or checked_at > generated_at.astimezone(checked_at.tzinfo)
        ):
            raise ForgeContractError(
                f"top_10[{index}].access_check.checked_at is outside the run chronology"
            )
    mix = core.get("mix")
    if not isinstance(mix, dict):
        raise ForgeContractError("refined core mix is missing")
    mix_request = manifest["mix_request"]
    for field in ("requested_ratio", "ratio_source", "ratio_reason"):
        if mix.get(field) != mix_request.get(field):
            raise ForgeContractError(f"refined core mix.{field} does not match run manifest")


def _load_hash_bound_artifact(record: dict[str, Any], label: str) -> dict[str, Any]:
    path_value = record.get("artifact_path")
    digest = record.get("artifact_sha256")
    if not path_value or not digest:
        raise ForgeContractError(f"{label} artifact receipt is incomplete")
    path = Path(path_value)
    if not path.is_file() or file_sha256(path) != digest:
        raise ForgeContractError(f"{label} artifact bytes changed after registration")
    return _read_json_strict(path, label)


def _assert_history_precondition(
    manifest: dict[str, Any], news_dir: Path, items: list[dict[str, Any]]
) -> dict[str, str | None]:
    record = manifest.get("artifacts", {}).get("history_snapshot")
    if not isinstance(record, dict):
        raise ForgeContractError("history_snapshot artifact receipt is missing")
    _load_hash_bound_artifact(record, "history_snapshot")
    metadata = record.get("metadata") or {}
    if Path(str(metadata.get("news_dir") or "")).resolve() != news_dir.resolve():
        raise ForgeContractError("archive news_dir does not match the history snapshot")
    target_state = metadata.get("archive_target_state")
    if not isinstance(target_state, dict) or not target_state:
        raise ForgeContractError("archive target precondition is missing")
    has_existing = any(value is not None for value in target_state.values())
    if has_existing and metadata.get("allow_existing_archive_replacement") is not True:
        raise ForgeContractError(
            "historical archive replacement was not explicitly authorized"
        )
    recheck_path = Path(manifest["run_dir"]) / "history_snapshot_recheck.json"
    try:
        rebuild_history(
            news_dir=news_dir,
            history_file=recheck_path,
            now=datetime.fromisoformat(str(manifest["created_at"])),
            exclude_report_date=manifest["report_date"],
        )
        if file_sha256(recheck_path) != record.get("artifact_sha256"):
            raise ForgeContractError(
                "formal archive history changed after prepare; restart the run"
            )
        report_clock = datetime.combine(
            date.fromisoformat(manifest["report_date"]),
            time.max,
            tzinfo=ZoneInfo(manifest["timezone"]),
        )
        recent_history = load_recent_history(
            days=int(metadata.get("dedupe_days", 7)),
            now=report_clock,
            path=recheck_path,
        )
        for index, item in enumerate(items):
            if match_history(item, entries=recent_history, now=report_clock).get(
                "redundant"
            ):
                raise ForgeContractError(
                    f"top_10[{index}] duplicates the locked formal archive history"
                )
    finally:
        recheck_path.unlink(missing_ok=True)
    return {
        str(name): str(value) if value is not None else None
        for name, value in target_state.items()
    }


def _assert_pipeline_provenance(payload: dict[str, Any], manifest: dict[str, Any]) -> None:
    baseline_stage = manifest["stages"]["baseline"]
    _load_hash_bound_artifact(baseline_stage, "baseline")
    baseline_coverage = baseline_stage.get("metadata", {}).get("coverage")
    if not isinstance(baseline_coverage, dict):
        raise ForgeContractError("baseline coverage receipt is missing")
    supplement_stage = manifest["stages"]["supplemental"]
    supplement = _load_hash_bound_artifact(supplement_stage, "supplemental")
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
        raise ForgeContractError("baseline coverage receipt counts are invalid") from exc
    coverage = payload.get("coverage") or {}
    for field, expected in expected_counts.items():
        if coverage.get(field) != expected:
            raise ForgeContractError(f"coverage.{field} does not match registered artifacts")
    attempted = expected_counts["source_attempted"]
    expected_rate = expected_counts["source_succeeded"] / attempted if attempted else 0.0
    if not isinstance(coverage.get("source_success_rate"), (int, float)) or not math.isclose(
        float(coverage["source_success_rate"]), expected_rate, abs_tol=1e-6
    ):
        raise ForgeContractError("coverage.source_success_rate does not match registered artifacts")
    expected_baseline_status = (
        "completed" if baseline_stage["status"] == "completed" else baseline_stage["status"]
    )
    if coverage.get("baseline_status") != expected_baseline_status:
        raise ForgeContractError("coverage.baseline_status does not match run manifest")

    results = supplement.get("results") if isinstance(supplement.get("results"), list) else []
    lane_failures = sorted(
        {
            str(result.get("lane"))
            for result in results
            if result.get("status") in {"degraded", "failed"}
        }
    )
    if sorted(str(value) for value in coverage.get("required_lane_failures", [])) != lane_failures:
        raise ForgeContractError("coverage.required_lane_failures does not match supplement results")
    expected_run_status = (
        "degraded"
        if baseline_stage["status"] == "degraded" or supplement_stage["status"] == "degraded"
        else "complete"
    )
    if coverage.get("run_status") != expected_run_status:
        raise ForgeContractError("coverage.run_status does not match registered stage status")
    expected_confidence = "high" if expected_run_status == "complete" else "medium"
    if coverage.get("coverage_confidence") != expected_confidence:
        raise ForgeContractError(
            "coverage.coverage_confidence does not match registered stage status"
        )
    expected_reasons = sorted(
        str(value) for value in baseline_coverage.get("reasons", []) if str(value)
    ) + [f"supplement lane degraded: {lane}" for lane in lane_failures]
    if sorted(str(value) for value in coverage.get("reasons", [])) != sorted(expected_reasons):
        raise ForgeContractError("coverage.reasons do not match registered artifacts")

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
        raise ForgeContractError("coverage.dated_candidate_rate does not match registered artifacts")

    candidate_record = manifest.get("artifacts", {}).get("candidate_pool")
    if not isinstance(candidate_record, dict):
        raise ForgeContractError("candidate_pool artifact receipt is missing")
    candidate_pool = _load_hash_bound_artifact(candidate_record, "candidate_pool")
    history_record = manifest.get("artifacts", {}).get("history_snapshot")
    if not isinstance(history_record, dict):
        raise ForgeContractError("history_snapshot artifact receipt is missing")
    _load_hash_bound_artifact(history_record, "history_snapshot")
    report_clock = datetime.combine(
        date.fromisoformat(manifest["report_date"]),
        time.max,
        tzinfo=ZoneInfo(manifest["timezone"]),
    )
    recent_history = load_recent_history(
        days=int(history_record.get("metadata", {}).get("dedupe_days", 7)),
        now=report_clock,
        path=Path(str(history_record["artifact_path"])),
    )
    baseline_observed = candidate_pool.get("candidate_funnel", {}).get("observed")
    if not isinstance(baseline_observed, int):
        raise ForgeContractError("candidate_pool observed count is missing")
    expected_observed = baseline_observed + supplemental_candidates
    if payload.get("candidate_funnel", {}).get("observed") != expected_observed:
        raise ForgeContractError("candidate_funnel.observed does not match registered artifacts")

    observed_candidates = list(candidate_pool.get("items", []))
    for result in results:
        if isinstance(result, dict) and isinstance(result.get("candidates"), list):
            observed_candidates.extend(result["candidates"])
    lineage: dict[str, dict[str, Any]] = {}
    for candidate in observed_candidates:
        if not isinstance(candidate, dict):
            continue
        reference = str(candidate.get("candidate_id") or candidate_ref(str(candidate.get("url") or "")))
        urls = {
            normalize_url(str(candidate.get("url") or "")),
            normalize_url(str((candidate.get("access_check") or {}).get("final_url") or "")),
        }
        lineage[reference] = {
            "urls": {url for url in urls if url},
            "candidate_object_sha256": candidate_object_hash(candidate),
        }
    semantic_bindings = {
        str(binding.get("output_item_sha256") or ""): binding
        for binding in payload.get("pipeline", {})
        .get("semantic_review", {})
        .get("lineage_bindings", [])
        if isinstance(binding, dict)
    }
    for index, item in enumerate(payload.get("top_10", [])):
        if match_history(item, entries=recent_history, now=report_clock).get("redundant"):
            raise ForgeContractError(
                f"top_10[{index}] duplicates the bound history snapshot"
            )
        references = item.get("candidate_refs")
        if not isinstance(references, list) or not references or any(
            reference not in lineage for reference in references
        ):
            raise ForgeContractError(f"top_10[{index}] is not bound to registered candidates")
        permitted_urls = set().union(
            *(lineage[reference]["urls"] for reference in references)
        )
        if normalize_url(str(item.get("url") or "")) not in permitted_urls:
            raise ForgeContractError(f"top_10[{index}] URL is outside its candidate lineage")
        binding = semantic_bindings.get(item_hash(item))
        if not isinstance(binding, dict):
            raise ForgeContractError(f"top_10[{index}] semantic lineage binding is missing")
        bound_inputs = {
            str(value.get("candidate_ref")): str(value.get("candidate_object_sha256"))
            for value in binding.get("inputs", [])
            if isinstance(value, dict)
        }
        expected_inputs = {
            reference: str(lineage[reference]["candidate_object_sha256"])
            for reference in references
        }
        if bound_inputs != expected_inputs:
            raise ForgeContractError(
                f"top_10[{index}] semantic lineage hashes do not match registered candidates"
            )


def _load_registered_receipt(
    manifest: dict[str, Any],
    manifest_path: Path,
    refined_path: Path,
    stage: str,
    expected_kind: str,
) -> dict[str, Any]:
    stage_data = manifest.get("stages", {}).get(stage, {})
    artifact_path = stage_data.get("artifact_path")
    if not artifact_path:
        raise ForgeContractError(f"{stage} receipt is not registered")
    receipt_path = Path(artifact_path)
    if not receipt_path.is_file():
        raise ForgeContractError(f"{stage} receipt artifact is missing")
    if stage_data.get("artifact_sha256") != file_sha256(receipt_path):
        raise ForgeContractError(f"{stage} receipt bytes changed after registration")
    receipt = _read_json_strict(receipt_path, f"{stage} receipt")
    try:
        validate_review_receipt(
            receipt,
            manifest_path,
            refined_path,
            expected_kind=expected_kind,
        )
    except RunContractError as exc:
        raise ForgeContractError(str(exc)) from exc
    return receipt


def assemble_final_payload(
    manifest_path: str | Path,
    refined_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    refined_file = Path(refined_path)
    try:
        require_stage(manifest_file, "semantic_review", {"completed"})
        require_stage(manifest_file, "red_team", {"completed", "not_required"})
    except RunContractError as exc:
        raise ForgeContractError(str(exc)) from exc
    manifest = load_manifest(manifest_file)
    if manifest.get("stages", {}).get("archive", {}).get("status") in {
        "completed",
        "degraded",
        "skipped",
        "not_required",
    }:
        raise ForgeContractError("archive stage is already terminal; create a new run for a rerun")
    core = _read_json_strict(refined_file, "refined core")
    _assert_core_identity(core, manifest, now=now)

    semantic = _load_registered_receipt(
        manifest, manifest_file, refined_file, "semantic_review", "semantic"
    )
    red_team = _load_registered_receipt(
        manifest, manifest_file, refined_file, "red_team", "red_team"
    )
    supplement_stage = manifest["stages"]["supplemental"]
    supplement_status = "degraded" if supplement_stage["status"] == "degraded" else "completed"
    if supplement_stage.get("metadata", {}).get("result_status") == "no_increment":
        supplement_status = "no_increment"

    payload = deepcopy(core)
    payload["pipeline"] = {
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "supplement_status": supplement_status,
        "semantic_review": {
            "status": semantic["status"],
            "reviewer_kind": semantic["reviewer_kind"],
            "reviewer_id": semantic["reviewer_id"],
            "invocation_id": semantic["invocation_id"],
            "request_sha256": semantic["request_sha256"],
            "turns_used": semantic["turns_used"],
            "halt_condition_met": semantic["halt_condition_met"],
            "input_bundle_sha256": semantic["input_bundle_sha256"],
            "access_log_sha256": semantic["data_provenance"]["access_log_sha256"],
            "verified_access_count": len(
                {
                    normalize_url(
                        str((item.get("access_check") or {}).get("requested_url") or "")
                    )
                    for item in payload.get("top_10", [])
                }
            ),
            "output_sha256": semantic["output_sha256"],
            "reviewed_item_hashes": deepcopy(semantic["reviewed_item_hashes"]),
            "lineage_bindings": deepcopy(semantic["lineage_bindings"]),
        },
        "red_team": {
            "status": red_team["status"],
            "reviewer_kind": red_team["reviewer_kind"],
            "reviewer_id": red_team["reviewer_id"],
            "invocation_id": red_team["invocation_id"],
            "request_sha256": red_team["request_sha256"],
            "turns_used": red_team["turns_used"],
            "halt_condition_met": red_team["halt_condition_met"],
            "covered_item_hashes": deepcopy(red_team.get("reviewed_item_hashes", [])),
        },
    }
    _assert_pipeline_provenance(payload, manifest)
    errors, _ = validate_briefing_data(payload)
    if errors:
        raise ForgeContractError("briefing gate blocked archive: " + "; ".join(errors))
    return payload


def render_briefing(
    payload: dict[str, Any],
    *,
    template_path: str | Path = TEMPLATE_PATH,
) -> str:
    path = Path(template_path)
    environment = Environment(
        loader=FileSystemLoader(str(path.parent)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = environment.get_template(path.name)
    rendered = template.render(**payload, date=payload["report_date"])
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def preview_briefing(
    manifest_path: str | Path,
    refined_path: str | Path,
    *,
    template_path: str | Path = TEMPLATE_PATH,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    payload = assemble_final_payload(manifest_path, refined_path, now=now)
    return payload, render_briefing(payload, template_path=template_path)


def forge_briefing(
    manifest_path: str | Path,
    refined_path: str | Path,
    *,
    news_dir: str | Path = NEWS_DIR,
    history_path: str | Path = HISTORY_PATH,
    template_path: str | Path = TEMPLATE_PATH,
    update_runtime_state: bool = True,
    now: datetime | None = None,
) -> ArchiveCommitResult:
    manifest_file = Path(manifest_path)
    refined_file = Path(refined_path)
    payload = assemble_final_payload(manifest_file, refined_file, now=now)
    manifest = load_manifest(manifest_file)
    archive_root = Path(news_dir)
    markdown = render_briefing(payload, template_path=template_path)
    if update_runtime_state:
        try:
            update_phase("forge", "running")
        except Exception as exc:
            print(f"[WARN] runtime phase telemetry unavailable: {exc}")

    def locked_history_precondition() -> dict[str, str | None]:
        return _assert_history_precondition(
            manifest,
            archive_root,
            payload["top_10"],
        )

    def locked_history_update(result: ArchiveCommitResult) -> None:
        save_history_items(
            payload["top_10"],
            archive_ref=str(result.json_path.resolve()),
            path=Path(history_path),
            now=now,
        )

    try:
        result = commit_briefing_pair(
            payload,
            news_dir=archive_root,
            report_date=payload["report_date"],
            run_id=payload["run_id"],
            markdown=markdown,
            precommit_validator=locked_history_precondition,
            postcommit_action=locked_history_update,
        )
    except ArchivePostcommitError as exc:
        result = exc.result
        try:
            record_stage(
                manifest_file,
                "archive",
                "failed",
                metadata={
                    "formal_archive_committed": True,
                    "json_path": str(result.json_path.resolve()),
                    "error": str(exc),
                },
                now=now,
            )
        except Exception:
            pass
        raise ForgeContractError(str(exc)) from exc

    try:
        record_stage(
            manifest_file,
            "archive",
            "completed",
            artifact_path=result.manifest_path,
            input_sha256=result.json_sha256,
            metadata={
                "json_path": str(result.json_path.resolve()),
                "markdown_path": str(result.markdown_path.resolve()),
                "json_sha256": result.json_sha256,
                "markdown_sha256": result.markdown_sha256,
                "history_path": str(Path(history_path).resolve()),
            },
            now=now,
        )
    except Exception as exc:
        try:
            record_stage(
                manifest_file,
                "archive",
                "failed",
                metadata={
                    "formal_archive_committed": True,
                    "json_path": str(result.json_path.resolve()),
                    "error": str(exc),
                },
                now=now,
            )
        except Exception:
            pass
        raise ForgeContractError(
            "formal archive and history committed, but run finalization failed: "
            + str(exc)
        ) from exc

    if update_runtime_state:
        try:
            finalize_briefing(str(result.markdown_path))
            update_phase("forge", "completed")
            atomic_dump_json(
                RUNTIME_DIR / "telemetry.json",
                {
                    "skill_name": "personal-intelligence-hub",
                    "status": "success",
                    "mode": "daily_brief",
                    "runner": "semantic_model",
                    "run_id": payload["run_id"],
                    "report_date": payload["report_date"],
                    "top10_count": len(payload["top_10"]),
                },
            )
        except Exception as exc:
            print(f"[WARN] formal archive succeeded; runtime telemetry failed: {exc}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and atomically archive a PIH briefing.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--refined", type=Path, required=True)
    parser.add_argument("--news-dir", type=Path, default=NEWS_DIR)
    parser.add_argument("--history-path", type=Path, default=HISTORY_PATH)
    args = parser.parse_args()
    result = forge_briefing(
        args.manifest,
        args.refined,
        news_dir=args.news_dir,
        history_path=args.history_path,
    )
    for warning in result.gate_warnings:
        print(f"[WARN] {warning}")
    print(f"[OK] briefing saved to {result.markdown_path}")
    print(f"[OK] structured archive saved to {result.json_path}")
    print(f"[OK] commit receipt saved to {result.manifest_path}")


if __name__ == "__main__":
    main()
