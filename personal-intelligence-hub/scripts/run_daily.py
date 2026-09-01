from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hub_utils import HUB_DIR, NEWS_DIR, RUNTIME_DIR, atomic_dump_json
from mix_policy import allocate_target_counts


DEFAULT_FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"
DEFAULT_MAX_CONCURRENCY = 8
MAX_CONCURRENCY = 32
DEFAULT_SCAN_DEADLINE_SECONDS = 300.0
MAX_SCAN_DEADLINE_SECONDS = 3600.0


@dataclass(frozen=True)
class PrepareResult:
    manifest_path: Path
    baseline_path: Path
    candidates_path: Path
    supplement_request_path: Path | None
    execution_cli_path: Path


def _candidate_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "")
        for field in ("title", "summary_hint", "keyword_connection_hint")
    ).lower()


def _is_verified_primary_lane_signal(
    item: dict[str, Any],
    keywords: list[str],
    window: dict[str, Any],
) -> bool:
    from history_manager import normalize_url
    from run_contract import normalize_published_at

    if not any(keyword in _candidate_text(item) for keyword in keywords):
        return False
    if item.get("source_type") != "primary":
        return False
    access = item.get("access_check")
    if not isinstance(access, dict) or access.get("status") != "verified":
        return False
    if normalize_url(str(access.get("requested_url") or "")) != normalize_url(
        str(item.get("url") or "")
    ):
        return False
    try:
        published = date.fromisoformat(
            normalize_published_at(str(item.get("published_at") or ""))
        )
        start = date.fromisoformat(str(window["start"]))
        end = date.fromisoformat(str(window["end"]))
    except (KeyError, TypeError, ValueError):
        return False
    return start <= published <= end


def assess_supplement_gaps(
    candidates: dict[str, Any],
    manifest: dict[str, Any],
    focus: dict[str, Any],
) -> list[dict[str, Any]]:
    from run_contract import RunContractError

    items = candidates.get("items")
    if not isinstance(items, list):
        raise RunContractError("candidate pool items must be a list")
    maximum = int(focus.get("filters", {}).get("max_top10", 10))
    targets = allocate_target_counts(maximum, manifest["mix_request"]["requested_ratio"])
    counts = {
        domain: sum(1 for item in items if item.get("provisional_domain") == domain)
        for domain in ("technology", "healthcare_digital")
    }
    gaps: list[dict[str, Any]] = []
    if counts["technology"] < targets["technology"]:
        gaps.append(
            {
                "gap_id": "technology-supply",
                "lane": "TechRadar",
                "query_scope": "通用技术原始来源；补足通过质量门的技术候选",
                "max_turns": 3,
                "halt_condition": "达到技术目标候选数、原始来源无增量或用完最大轮次",
            }
        )
    if counts["healthcare_digital"] < targets["healthcare_digital"]:
        gaps.append(
            {
                "gap_id": "healthcare-digital-supply",
                "lane": "HealthcareRadar",
                "query_scope": "医疗 AI、临床信息系统、支付政策与医院数字化原始来源",
                "max_turns": 3,
                "halt_condition": "达到医疗数字化目标候选数、原始来源无增量或用完最大轮次",
            }
        )

    coverage = candidates.get("metadata", {}).get("coverage")
    if not isinstance(coverage, dict):
        coverage = manifest.get("stages", {}).get("baseline", {}).get("metadata", {}).get("coverage", {})
    policy = focus.get("coverage_policy", {})
    source_rate = float(coverage.get("source_success_rate", 0.0) or 0.0)
    minimum_source = float(policy.get("minimum_source_success_rate", 0.7))
    source_coverage_degraded = source_rate < minimum_source
    if source_coverage_degraded:
        existing_lanes = {str(gap["lane"]) for gap in gaps}
        for lane, gap_id, scope in (
            (
                "TechRadar",
                "technology-coverage-integrity",
                "通用技术原始来源；修复基线来源失败或日期证据不足",
            ),
            (
                "HealthcareRadar",
                "healthcare-coverage-integrity",
                "医疗数字化原始来源；修复基线来源失败或日期证据不足",
            ),
        ):
            if lane not in existing_lanes:
                gaps.append(
                    {
                        "gap_id": gap_id,
                        "lane": lane,
                        "query_scope": scope,
                        "max_turns": 3,
                        "halt_condition": "至少完成一个直接来源访问核验、确认无增量或用完最大轮次",
                    }
                )

    lane_defaults = {
        "Sentinel": {
            "min_candidates": 1,
            "query_scope": "医疗政策、支付、采购与竞对原始来源",
            "keywords": ["policy", "regulation", "procurement", "payment", "政策", "监管", "采购", "支付", "竞对"],
        },
        "Ranger": {
            "min_candidates": 1,
            "query_scope": "技术与医疗数字化失败、漏洞、处罚与执行摩擦",
            "keywords": ["risk", "failure", "vulnerability", "breach", "处罚", "漏洞", "失败", "中断", "风险"],
        },
    }
    configured = focus.get("coverage_policy", {}).get("lanes", {})
    for lane, defaults in lane_defaults.items():
        policy = {**defaults, **(configured.get(lane, {}) if isinstance(configured, dict) else {})}
        keywords = [str(value).lower() for value in policy.get("keywords", []) if str(value)]
        matching = sum(
            1
            for item in items
            if isinstance(item, dict)
            and _is_verified_primary_lane_signal(item, keywords, manifest["window"])
        )
        if matching < int(policy.get("min_candidates", 1)):
            gaps.append(
                {
                    "gap_id": "policy-competition" if lane == "Sentinel" else "risk-counterevidence",
                    "lane": lane,
                    "query_scope": str(policy["query_scope"]),
                    "max_turns": int(policy.get("max_turns", 3)),
                    "halt_condition": "找到并核验至少一个直接来源事件、确认无增量或用完最大轮次",
                }
            )
    budget = focus.get("coverage_policy", {}).get("supplement_budget", {})
    max_queries = int(budget.get("max_queries_per_gap", 2))
    max_urls = int(budget.get("max_urls_per_gap", 4))
    max_duration_seconds = int(budget.get("max_duration_seconds", 150))
    max_turns = int(budget.get("max_turns_per_gap", 2))
    for gap in gaps:
        gap.update(
            {
                "max_queries": max_queries,
                "max_urls": max_urls,
                "max_duration_seconds": max_duration_seconds,
                "max_turns": min(int(gap["max_turns"]), max_turns),
            }
        )
    return gaps


async def prepare_run(
    *,
    report_date: str | None = None,
    timezone_name: str = "Asia/Shanghai",
    window_days: int = 7,
    topic: str = "技术与医疗数字化",
    region: str = "中国、美国与全球",
    requested_ratio: dict[str, float] | None = None,
    ratio_source: str = "schema_default",
    ratio_reason: str = "none",
    focus_path: Path = DEFAULT_FOCUS_PATH,
    runtime_dir: Path = RUNTIME_DIR,
    news_dir: Path = NEWS_DIR,
    allow_existing_archive_replacement: bool = False,
    skill_path: Path = HUB_DIR / "SKILL.md",
    run_id: str | None = None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    scan_deadline_seconds: float = DEFAULT_SCAN_DEADLINE_SECONDS,
    now: datetime | None = None,
) -> PrepareResult:
    from run_contract import RunContractError

    if max_concurrency <= 0:
        raise RunContractError("max_concurrency must be positive")
    if max_concurrency > MAX_CONCURRENCY:
        raise RunContractError(
            f"max_concurrency must be between 1 and {MAX_CONCURRENCY}"
        )
    if (
        scan_deadline_seconds <= 0
        or scan_deadline_seconds > MAX_SCAN_DEADLINE_SECONDS
    ):
        raise RunContractError(
            "scan_deadline_seconds must be between 0 and "
            f"{MAX_SCAN_DEADLINE_SECONDS}"
        )

    effective_now = now or datetime.now(ZoneInfo(timezone_name))
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise RunContractError("prepare now must be timezone-aware")
    effective_report_date = report_date or effective_now.astimezone(
        ZoneInfo(timezone_name)
    ).date().isoformat()
    compact_date = effective_report_date.replace("-", "")

    import fetch_news
    import refine
    from run_contract import (
        build_supplement_request,
        create_run,
        file_sha256,
        load_manifest,
        record_run_artifact,
        record_stage,
    )
    from history_manager import load_recent_history
    from update_index import rebuild_history

    try:
        focus = json.loads(focus_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunContractError(f"focus config is unreadable: {focus_path}: {exc}") from exc
    if not isinstance(focus, dict):
        raise RunContractError("focus config must be a JSON object")
    existing_targets = [
        news_dir / f"intelligence_{compact_date}_briefing.{suffix}"
        for suffix in ("json", "md", "manifest.json")
    ]
    if any(path.exists() for path in existing_targets) and not allow_existing_archive_replacement:
        raise RunContractError(
            "formal archive targets already exist; pass "
            "--allow-existing-archive-replacement for an explicit replacement run"
        )

    manifest_path, manifest = create_run(
        report_date=report_date,
        timezone_name=timezone_name,
        window_days=window_days,
        topic=topic,
        region=region,
        requested_ratio=requested_ratio,
        ratio_source=ratio_source,
        ratio_reason=ratio_reason,
        runtime_dir=runtime_dir,
        skill_path=skill_path,
        now=now,
        run_id=run_id,
    )
    run_dir = Path(manifest["run_dir"])
    record_stage(
        manifest_path,
        "baseline",
        "running",
        metadata={"phase": "binding_inputs"},
        now=now,
    )
    try:
        record_run_artifact(
            manifest_path,
            "focus_config",
            focus_path,
            metadata={"configuration_role": "candidate_scoring_and_gap_policy"},
            now=now,
        )
    except Exception as exc:
        record_stage(
            manifest_path,
            "baseline",
            "failed",
            metadata={"error_type": type(exc).__name__, "phase": "binding_inputs"},
            now=now,
        )
        raise
    history_snapshot_path = run_dir / "history_snapshot.json"
    history_now = datetime.combine(
        date.fromisoformat(manifest["report_date"]),
        time.max,
        tzinfo=ZoneInfo(manifest["timezone"]),
    )
    try:
        rebuild_history(
            news_dir=news_dir,
            history_file=history_snapshot_path,
            now=history_now,
            exclude_report_date=manifest["report_date"],
        )
    except Exception as exc:
        record_stage(
            manifest_path,
            "baseline",
            "failed",
            metadata={"error_type": type(exc).__name__, "phase": "history_snapshot"},
            now=now,
        )
        raise
    dedupe_days = int(focus.get("filters", {}).get("dedupe_days", 7))
    compact_date = manifest["report_date"].replace("-", "")
    target_state = {}
    for suffix in ("json", "md", "manifest.json"):
        target = news_dir / f"intelligence_{compact_date}_briefing.{suffix}"
        target_state[target.name] = file_sha256(target) if target.is_file() else None
    record_run_artifact(
        manifest_path,
        "history_snapshot",
        history_snapshot_path,
        metadata={
            "news_dir": str(news_dir.resolve()),
            "archive_target_state": target_state,
            "dedupe_days": dedupe_days,
            "allow_existing_archive_replacement": bool(
                allow_existing_archive_replacement
            ),
        },
        now=now,
    )
    history_review_slice_path = run_dir / "history_review_slice.json"
    recent_history = load_recent_history(
        days=dedupe_days,
        now=history_now,
        path=history_snapshot_path,
    )
    atomic_dump_json(
        history_review_slice_path,
        {
            "resource_kind": "pih_history_review_slice",
            "schema_version": "1.0",
            "generated_at": history_now.isoformat(),
            "source_snapshot_sha256": file_sha256(history_snapshot_path),
            "dedupe_days": dedupe_days,
            "entries": recent_history,
        },
    )
    record_run_artifact(
        manifest_path,
        "history_review_slice",
        history_review_slice_path,
        input_sha256=file_sha256(history_snapshot_path),
        metadata={
            "dedupe_days": dedupe_days,
            "entry_count": len(recent_history),
        },
        now=now,
    )
    baseline_path = run_dir / "baseline_scan.json"
    current_path = run_dir / "current_scan.json"
    cache_path = run_dir / "fetch_cache.json"
    candidates_path = run_dir / "intelligence_candidates.json"
    blackboard_path = run_dir / "intelligence_blackboard.json"
    try:
        scan = await fetch_news.scan_all(
            focus_path=focus_path,
            window_days=window_days,
            topic=topic,
            region=region,
            report_date=manifest["report_date"],
            timezone_name=timezone_name,
            max_concurrency=max_concurrency,
            scan_deadline_seconds=scan_deadline_seconds,
            output_path=baseline_path,
            current_output_path=current_path,
            cache_path=cache_path,
            blackboard_path=blackboard_path,
        )
        if not isinstance(scan, dict):
            raise RunContractError("baseline scan did not return an object")
        if scan.get("metadata", {}).get("window") != manifest["window"]:
            raise RunContractError("baseline window does not match run manifest")
        coverage = scan.get("coverage") or {}
        if not isinstance(coverage, dict):
            raise RunContractError("baseline coverage is invalid")
        run_status = str(coverage.get("run_status") or "")
        baseline_status = {
            "complete": "completed",
            "degraded": "degraded",
            "failed": "failed",
        }.get(run_status)
        if baseline_status is None:
            raise RunContractError("baseline coverage status is missing or invalid")
    except Exception as exc:
        try:
            record_stage(
                manifest_path,
                "baseline",
                "failed",
                metadata={"error_type": type(exc).__name__},
                now=now,
            )
        except Exception as record_exc:
            exc.add_note(f"failed to record baseline failure: {record_exc}")
        raise
    record_stage(
        manifest_path,
        "baseline",
        baseline_status,
        artifact_path=baseline_path,
        metadata={"coverage": coverage, "candidate_funnel": scan.get("candidate_funnel", {})},
        now=now,
    )
    if baseline_status == "failed":
        raise RunContractError("baseline scan failed; supplement and review stages were not started")

    record_stage(
        manifest_path,
        "supplemental",
        "running",
        metadata={"phase": "candidate_refinement"},
        now=now,
    )
    try:
        candidate_pool = refine.refine(
            focus_path=focus_path,
            manifest_path=manifest_path,
            scan_path=baseline_path,
            candidates_path=candidates_path,
            blackboard_path=blackboard_path,
        )
        if not isinstance(candidate_pool, dict):
            raise RunContractError("candidate refinement did not return an object")
    except Exception as exc:
        record_stage(
            manifest_path,
            "supplemental",
            "failed",
            metadata={
                "error_type": type(exc).__name__,
                "phase": "candidate_refinement",
            },
            now=now,
        )
        raise
    record_run_artifact(
        manifest_path,
        "candidate_pool",
        candidates_path,
        input_sha256=load_manifest(manifest_path)["stages"]["baseline"]["artifact_sha256"],
        metadata={"candidate_funnel": candidate_pool.get("candidate_funnel", {})},
        now=now,
    )
    gaps = assess_supplement_gaps(candidate_pool, load_manifest(manifest_path), focus)
    request_path: Path | None = None
    if gaps:
        request_path, _ = build_supplement_request(manifest_path, gaps, now=now)
    else:
        no_increment_path = run_dir / "supplement_results.json"
        atomic_dump_json(
            no_increment_path,
            {
                "contract_version": "supplement-aggregate/1.0",
                "run_id": manifest["run_id"],
                "baseline_sha256": load_manifest(manifest_path)["stages"]["baseline"]["artifact_sha256"],
                "status": "no_increment",
                "coverage": {"attempted": 0, "succeeded": 0, "failed": 0},
                "results": [],
            },
        )
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=no_increment_path,
            metadata={"result_status": "no_increment", "gap_count": 0},
            now=now,
        )
    finalized_manifest = load_manifest(manifest_path)
    snapshot = finalized_manifest.get("bundle_snapshot")
    execution_cli_path = (
        Path(str(snapshot["execution_cli_path"]))
        if isinstance(snapshot, dict)
        else Path(__file__).resolve()
    )
    return PrepareResult(
        manifest_path,
        baseline_path,
        candidates_path,
        request_path,
        execution_cli_path,
    )


def _enforce_run_scoped_cli(manifest_path: Path) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    snapshot = manifest.get("bundle_snapshot") if isinstance(manifest, dict) else None
    if not isinstance(snapshot, dict):
        return
    expected = Path(str(snapshot.get("execution_cli_path") or "")).resolve()
    if Path(__file__).resolve() != expected:
        raise RuntimeError(
            "this run is bound to its immutable execution CLI; rerun with: "
            f"python -X utf8 {expected}"
        )


def _ratio_from_args(args: argparse.Namespace) -> tuple[dict[str, float] | None, str, str]:
    from run_contract import RunContractError

    if args.technology_ratio is None:
        return None, "schema_default", "none"
    technology = float(args.technology_ratio)
    if not 0 <= technology <= 1:
        raise RunContractError("--technology-ratio must be between 0 and 1")
    if not str(args.ratio_reason or "").strip():
        raise RunContractError("--ratio-reason is required for a user ratio")
    return (
        {"technology": technology, "healthcare_digital": 1 - technology},
        "user",
        args.ratio_reason,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the staged personal intelligence workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create a run, fetch baseline, build candidates and gaps.")
    prepare.add_argument("--report-date")
    prepare.add_argument("--timezone", default="Asia/Shanghai")
    prepare.add_argument("--window-days", type=int, default=7)
    prepare.add_argument("--topic", default="技术与医疗数字化")
    prepare.add_argument("--region", default="中国、美国与全球")
    prepare.add_argument("--focus-config", type=Path, default=DEFAULT_FOCUS_PATH)
    prepare.add_argument("--technology-ratio", type=float)
    prepare.add_argument("--ratio-reason")
    prepare.add_argument("--run-id")
    prepare.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_MAX_CONCURRENCY,
        help=f"Global concurrent requests (1..{MAX_CONCURRENCY}; per-host maximum 4).",
    )
    prepare.add_argument(
        "--scan-deadline-seconds",
        type=float,
        default=DEFAULT_SCAN_DEADLINE_SECONDS,
        help=(
            "Overall source-scan deadline; unfinished sources become explicit "
            "coverage failures."
        ),
    )
    prepare.add_argument("--news-dir", type=Path, default=NEWS_DIR)
    prepare.add_argument(
        "--allow-existing-archive-replacement",
        action="store_true",
        help="Explicitly allow replacement when a historical report date already has an archive.",
    )

    prepare_review = subparsers.add_parser(
        "prepare-review",
        help="Create registered semantic and red-team invocation requests.",
    )
    prepare_review.add_argument("--manifest", type=Path, required=True)
    prepare_review.add_argument("--refined", type=Path)
    prepare_review.add_argument("--semantic-receipt", type=Path)
    prepare_review.add_argument(
        "--kind", choices=("semantic", "red_team"), required=True
    )
    prepare_review.add_argument("--max-turns", type=int, default=2)

    validate_semantic = subparsers.add_parser(
        "validate-semantic-draft",
        help="Validate semantic core and receipt before immutable publication or red-team registration.",
    )
    validate_semantic.add_argument("--manifest", type=Path, required=True)
    validate_semantic.add_argument("--refined", type=Path, required=True)
    validate_semantic.add_argument("--semantic-receipt", type=Path, required=True)

    finalize_semantic = subparsers.add_parser(
        "finalize-semantic-decision",
        help="Assemble lineage and receipt fields from a semantic core and compact decision, then publish.",
    )
    finalize_semantic.add_argument("--manifest", type=Path, required=True)
    finalize_semantic.add_argument("--refined", type=Path, required=True)
    finalize_semantic.add_argument("--decision", type=Path, required=True)

    validate_red_team = subparsers.add_parser(
        "validate-red-team-draft",
        help="Validate a red-team receipt before immutable publication.",
    )
    validate_red_team.add_argument("--manifest", type=Path, required=True)
    validate_red_team.add_argument("--refined", type=Path, required=True)
    validate_red_team.add_argument("--semantic-receipt", type=Path, required=True)
    validate_red_team.add_argument("--red-team-receipt", type=Path, required=True)

    normalize_date = subparsers.add_parser(
        "normalize-published-at",
        help="Normalize a date or timezone-aware ISO datetime to its source-local YYYY-MM-DD date.",
    )
    normalize_date.add_argument("--value", required=True)

    supplement = subparsers.add_parser("register-supplement", help="Validate and register all gap results.")
    supplement.add_argument("--manifest", type=Path, required=True)
    supplement.add_argument("--request", type=Path, required=True)
    supplement.add_argument("--result", type=Path, action="append", required=True)

    finalize_supplement = subparsers.add_parser(
        "finalize-supplement",
        help="Validate draft gap results, atomically publish finals, and register the aggregate.",
    )
    finalize_supplement.add_argument("--manifest", type=Path, required=True)
    finalize_supplement.add_argument("--request", type=Path, required=True)
    finalize_supplement.add_argument("--draft", type=Path, action="append", required=True)

    reconcile_supplement = subparsers.add_parser(
        "reconcile-supplement",
        help="Convert per-gap terminal progress states and available drafts into a registered aggregate.",
    )
    reconcile_supplement.add_argument("--manifest", type=Path, required=True)
    reconcile_supplement.add_argument("--request", type=Path, required=True)
    reconcile_supplement.add_argument("--result", type=Path, action="append", default=[])
    reconcile_supplement.add_argument(
        "--progress-state", type=Path, action="append", default=[]
    )

    review = subparsers.add_parser("register-review", help="Register semantic and red-team receipts.")
    review.add_argument("--manifest", type=Path, required=True)
    review.add_argument("--refined", type=Path, required=True)
    review.add_argument("--semantic-receipt", type=Path, required=True)
    review.add_argument("--red-team-receipt", type=Path, required=True)

    archive = subparsers.add_parser("forge", help="Validate receipts and atomically archive the briefing pair.")
    archive.add_argument("--manifest", type=Path, required=True)
    archive.add_argument("--refined", type=Path, required=True)
    archive.add_argument("--news-dir", type=Path)
    archive.add_argument("--history-path", type=Path)

    preview = subparsers.add_parser(
        "preview",
        help="Assemble, validate and render without writing formal news or history files.",
    )
    preview.add_argument("--manifest", type=Path, required=True)
    preview.add_argument("--refined", type=Path, required=True)
    preview.add_argument("--format", choices=("markdown", "json"), default="markdown")

    status = subparsers.add_parser("status", help="Print a run manifest.")
    status.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if hasattr(args, "manifest"):
        try:
            _enforce_run_scoped_cli(args.manifest)
        except RuntimeError as exc:
            parser.error(str(exc))
    if args.command == "prepare":
        if args.window_days <= 0:
            parser.error("--window-days must be positive")
        if args.max_concurrency <= 0:
            parser.error("--max-concurrency must be positive")
        if args.max_concurrency > MAX_CONCURRENCY:
            parser.error(
                f"--max-concurrency must be between 1 and {MAX_CONCURRENCY}"
            )
        if (
            args.scan_deadline_seconds <= 0
            or args.scan_deadline_seconds > MAX_SCAN_DEADLINE_SECONDS
        ):
            parser.error(
                "--scan-deadline-seconds must be between 0 and "
                f"{MAX_SCAN_DEADLINE_SECONDS}"
            )
        ratio, source, reason = _ratio_from_args(args)
        result = asyncio.run(
            prepare_run(
                report_date=args.report_date,
                timezone_name=args.timezone,
                window_days=args.window_days,
                topic=args.topic,
                region=args.region,
                requested_ratio=ratio,
                ratio_source=source,
                ratio_reason=reason,
                focus_path=args.focus_config,
                news_dir=args.news_dir,
                allow_existing_archive_replacement=args.allow_existing_archive_replacement,
                run_id=args.run_id,
                max_concurrency=args.max_concurrency,
                scan_deadline_seconds=args.scan_deadline_seconds,
            )
        )
        print(json.dumps({
            "manifest_path": str(result.manifest_path.resolve()),
            "baseline_path": str(result.baseline_path.resolve()),
            "candidates_path": str(result.candidates_path.resolve()),
            "supplement_request_path": str(result.supplement_request_path.resolve()) if result.supplement_request_path else None,
            "execution_cli_path": str(result.execution_cli_path.resolve()),
        }, ensure_ascii=False, indent=2))
    elif args.command == "prepare-review":
        from run_contract import build_review_request

        path, request = build_review_request(
            args.manifest,
            args.refined,
            args.kind,
            semantic_receipt_path=args.semantic_receipt,
            max_turns=args.max_turns,
        )
        print(
            json.dumps(
                {
                    "request_path": str(path.resolve()),
                    "review_kind": request["review_kind"],
                    "reviewer_id": request["reviewer_id"],
                    "invocation_id": request["invocation_id"],
                    "review_mode": request["review_mode"],
                    "max_turns": request["max_turns"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "normalize-published-at":
        from run_contract import normalize_published_at

        print(
            json.dumps(
                {"published_at": normalize_published_at(args.value)},
                ensure_ascii=False,
            )
        )
    elif args.command == "validate-semantic-draft":
        from run_contract import validate_semantic_draft

        warnings = validate_semantic_draft(
            args.manifest,
            args.refined,
            args.semantic_receipt,
        )
        print(
            json.dumps(
                {"status": "valid", "warnings": warnings},
                ensure_ascii=False,
            )
        )
    elif args.command == "finalize-semantic-decision":
        from run_contract import finalize_semantic_decision

        refined_path, receipt_path = finalize_semantic_decision(
            args.manifest,
            args.refined,
            args.decision,
        )
        print(
            json.dumps(
                {
                    "status": "registered",
                    "refined_path": str(refined_path),
                    "semantic_receipt_path": str(receipt_path),
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "validate-red-team-draft":
        from run_contract import validate_red_team_draft

        warnings = validate_red_team_draft(
            args.manifest,
            args.refined,
            args.semantic_receipt,
            args.red_team_receipt,
        )
        print(
            json.dumps(
                {"status": "valid", "warnings": warnings},
                ensure_ascii=False,
            )
        )
    elif args.command == "register-supplement":
        from run_contract import register_supplement_results

        path, aggregate = register_supplement_results(
            args.manifest, args.request, args.result
        )
        print(json.dumps({"artifact_path": str(path.resolve()), "status": aggregate["status"]}, ensure_ascii=False))
    elif args.command == "finalize-supplement":
        from run_contract import register_supplement_results

        path, aggregate = register_supplement_results(
            args.manifest,
            args.request,
            args.draft,
            publish_drafts=True,
        )
        print(
            json.dumps(
                {"artifact_path": str(path.resolve()), "status": aggregate["status"]},
                ensure_ascii=False,
            )
        )
    elif args.command == "reconcile-supplement":
        from run_contract import reconcile_supplement_progress

        path, aggregate = reconcile_supplement_progress(
            args.manifest,
            args.request,
            args.result,
            args.progress_state,
        )
        print(
            json.dumps(
                {"artifact_path": str(path.resolve()), "status": aggregate["status"]},
                ensure_ascii=False,
            )
        )
    elif args.command == "register-review":
        from run_contract import register_review_bundle

        register_review_bundle(
            args.manifest,
            args.refined,
            args.semantic_receipt,
            args.red_team_receipt,
        )
        print(json.dumps({"status": "registered"}, ensure_ascii=False))
    elif args.command == "preview":
        from forge import preview_briefing

        payload, markdown = preview_briefing(args.manifest, args.refined)
        print(
            json.dumps(payload, ensure_ascii=False, indent=2)
            if args.format == "json"
            else markdown,
            end="" if args.format == "markdown" else "\n",
        )
    elif args.command == "forge":
        from forge import forge_briefing

        kwargs: dict[str, Any] = {}
        if args.news_dir is not None:
            kwargs["news_dir"] = args.news_dir
        if args.history_path is not None:
            kwargs["history_path"] = args.history_path
        result = forge_briefing(args.manifest, args.refined, **kwargs)
        print(json.dumps({
            "json_path": str(result.json_path.resolve()),
            "markdown_path": str(result.markdown_path.resolve()),
            "commit_receipt": str(result.manifest_path.resolve()),
        }, ensure_ascii=False, indent=2))
    else:
        from run_contract import load_manifest

        print(json.dumps(load_manifest(args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
