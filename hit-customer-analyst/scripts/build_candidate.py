#!/usr/bin/env python3
"""Build an isolated discovery-call candidate from one structured run payload.

This command is deliberately non-transactional with respect to the live
workspace: it only reads the live workspace and writes a new candidate tree.
``commit_run.py`` remains the sole authority that can merge the candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import validate_outputs as validator
from runtime_tx import (
    EVIDENCE_MANIFEST_REL,
    RUN_METRICS_REL,
    SEARCH_PLAN_REL,
    SOURCE_CACHE_REL,
    CASMismatch,
    TxError,
    assert_manifest_cas,
    build_manifest,
    file_state,
    sha256_bytes,
    sha256_file,
    task_date_at,
    verify_manifest_artifacts,
)


PAYLOAD_SCHEMA = "discovery-call-candidate-run/v1"
EDITABLE_TYPES = {
    "institution_research",
    "leader_research",
    "internal_retrieval",
    "visit_strategy",
    "customer_letter_internal",
    "briefing_delivery",
}
ALL_TYPES = set(validator.STATUS_LABELS) | {"comprehensive_report", "briefing_delivery"}
ACTION_TYPES = {
    "institution_research": "institution",
    "leader_research": "leader",
    "internal_retrieval": "internal",
    "visit_strategy": "strategy",
    "briefing_delivery": "briefing",
    "customer_letter_internal": "letter",
    "customer_letter_external": "external_letter",
}
TERMINAL_STATUSES = {"partial", "completed", "blocked"}
FRESHNESS_STATUSES = {"current", "stale", "invalidated"}
CONNECTOR_STATUSES = {
    "not_applicable",
    "not_configured",
    "connected",
    "no_hits",
    "permission_denied",
    "failed",
}
WORKFLOW_STAGES = {"research", "synthesis", "output", "review", "closed", "paused"}
RUN_ACTIONS = {"created", "updated", "reused", "not_called"}
SUMMARY_SYNC_STATUSES = {"synced", "out_of_sync"}
DOWNSTREAM_INVALIDATIONS = {"none", "stale", "invalidated"}
TYPE_METADATA_FIELDS = {
    "institution_research": set(),
    "leader_research": set(),
    "internal_retrieval": set(),
    "visit_strategy": set(validator.STRATEGY_CONTEXT_FIELDS)
    | {"strategy_variant", "strategic_question", "planning_horizon"},
    "customer_letter_internal": set(validator.LETTER_CONTEXT_FIELDS),
    "briefing_delivery": set(),
}
GENERIC_REVIEW_TYPES = set(validator.GENERIC_REVIEW_TYPES)
GENERIC_REVIEW_FIELDS = set(validator.GENERIC_REVIEW_FIELDS)
LETTER_APPROVAL_FIELDS = set(validator.APPROVAL_FIELDS)
LETTER_ACTOR_FIELDS = set(getattr(validator, "LETTER_ACTOR_FIELDS", set()))
LETTER_REQUEST_FIELDS = set(getattr(validator, "EXTERNAL_REQUEST_FIELDS", set()))
LETTER_REVIEW_AUDIT_FIELDS = LETTER_APPROVAL_FIELDS | LETTER_ACTOR_FIELDS | LETTER_REQUEST_FIELDS
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_BODY_CHARS = 3_000_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANDIDATE_MARKER_REL = Path("runtime") / "candidate-receipt.json"
RUNTIME_MACHINE_RELS = {
    SEARCH_PLAN_REL,
    SOURCE_CACHE_REL,
    EVIDENCE_MANIFEST_REL,
    RUN_METRICS_REL,
}


class CandidateError(RuntimeError):
    """A deterministic, user-actionable candidate construction failure."""


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidateError(f"{label}必须是JSON对象。")
    return dict(value)


def _strict_keys(
    value: Mapping[str, Any],
    *,
    label: str,
    required: set[str],
    allowed: set[str],
) -> None:
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        raise CandidateError(f"{label}缺少字段：{', '.join(missing)}。")
    if unknown:
        raise CandidateError(f"{label}包含未授权字段：{', '.join(unknown)}。")


def _plain_text(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise CandidateError(f"{label}必须是字符串。")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise CandidateError(f"{label}必须是1—{maximum}字符的非空文本。")
    if any(ord(char) < 32 and char not in "\t" for char in normalized):
        raise CandidateError(f"{label}包含控制字符。")
    return normalized


def _body_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise CandidateError(f"{label}必须是字符串。")
    if not value.strip() or len(value) > MAX_BODY_CHARS:
        raise CandidateError(f"{label}必须是非空且不超过{MAX_BODY_CHARS}字符的正文。")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        raise CandidateError(f"{label}包含控制字符。")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _parse_timestamp(value: object, label: str) -> tuple[str, datetime]:
    text = _plain_text(value, label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateError(f"{label}必须是带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise CandidateError(f"{label}必须包含时区。")
    canonical = parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return canonical, parsed


def _parse_cutoff(value: object, task_timezone: str | None) -> str:
    text = _plain_text(value, "run.evidence_cutoff_date", maximum=10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise CandidateError("run.evidence_cutoff_date必须为YYYY-MM-DD。") from exc
    now = datetime.now(timezone.utc)
    today = task_date_at(now, task_timezone) if task_timezone else now.date()
    if parsed > today:
        basis = f"任务时区{task_timezone}" if task_timezone else "UTC"
        raise CandidateError(f"run.evidence_cutoff_date晚于{basis}当前日期{today.isoformat()}。")
    return text


def _load_payload(path: Path) -> tuple[dict[str, Any], str]:
    supplied = path.expanduser()
    if supplied.is_symlink():
        raise CandidateError("--payload不得为符号链接。")
    resolved = supplied.resolve()
    if not resolved.is_file() or resolved.stat().st_size > MAX_PAYLOAD_BYTES:
        raise CandidateError(f"--payload必须是小于等于{MAX_PAYLOAD_BYTES}字节的普通文件。")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"payload不是有效UTF-8 JSON：{exc}") from exc
    return _require_object(payload, "payload"), sha256_bytes(raw)


def _load_documents(workspace: Path) -> dict[str, validator.Document]:
    issues: list[validator.Issue] = []
    documents = validator.load_documents(workspace, issues)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise CandidateError("正式工作区成果无法安全解析：" + "; ".join(issue.code for issue in errors[:6]))
    by_type: dict[str, validator.Document] = {}
    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type", "")
        if artifact_type not in ALL_TYPES:
            raise CandidateError(f"正式工作区存在不受控artifact_type：{artifact_type!r}。")
        if artifact_type in by_type:
            raise CandidateError(f"正式工作区artifact_type重复：{artifact_type}。")
        by_type[artifact_type] = document
    if "comprehensive_report" not in by_type:
        raise CandidateError("正式工作区缺少综合报告。")
    return by_type


def _expected_filename(safe_name: str, artifact_type: str) -> str:
    if not validator.safe_component(safe_name):
        raise CandidateError("综合报告safe_name不是规范安全文件名组件。")
    suffix = validator.SUFFIXES.get(artifact_type)
    if suffix is None:
        raise CandidateError(f"不受控artifact_type：{artifact_type}。")
    return f"{safe_name}{suffix}"


def _validate_live_identity(
    workspace: Path,
    manifest: Mapping[str, object],
    by_type: Mapping[str, validator.Document],
) -> validator.Document:
    total = by_type["comprehensive_report"]
    identity_fields = (
        "context_id",
        "customer_id",
        "customer_display_name",
        "organization_scope",
    )
    for field in identity_fields:
        expected = total.frontmatter.get(field, "")
        if str(manifest.get(field, "")) != expected:
            raise CandidateError(f"运行清单{field}与综合报告不一致。")
    safe_name = total.frontmatter.get("safe_name", "")
    for artifact_type, document in by_type.items():
        expected_name = _expected_filename(safe_name, artifact_type)
        if document.path.name != expected_name:
            raise CandidateError(f"{artifact_type}文件名应为{expected_name}。")
        if document.path.is_symlink() or document.path.resolve().parent != workspace:
            raise CandidateError(f"成果路径越界或为符号链接：{document.path}。")
        for field in (*identity_fields, "safe_name"):
            if document.frontmatter.get(field, "") != total.frontmatter.get(field, ""):
                raise CandidateError(f"{document.path.name}.{field}与综合报告不一致。")
    return total


def _frontmatter_and_body(text: str, path: Path) -> tuple[dict[str, str], str]:
    issues: list[validator.Issue] = []
    data, body = validator.parse_frontmatter(path, text, issues)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise CandidateError(f"{path.name}无法解析：" + "; ".join(issue.code for issue in errors[:5]))
    return data, body


def _replace_body(text: str, body: str, path: Path) -> str:
    lines = text.splitlines()
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise CandidateError(f"{path.name}的frontmatter未闭合。") from exc
    return "\n".join(lines[: end + 1]) + "\n\n" + body.strip("\n") + "\n"


def _new_document_text(
    *,
    total: validator.Document,
    artifact_type: str,
    body: str,
    metadata: Mapping[str, str],
) -> str:
    identity = {
        key: total.frontmatter.get(key, "")
        for key in (
            "context_id",
            "customer_id",
            "customer_display_name",
            "organization_scope",
            "safe_name",
        )
    }
    base: dict[str, str] = {
        "schema": validator.SCHEMA,
        "artifact_type": artifact_type,
        **identity,
        "latest_run_id": "",
        "module_status": "partial",
        "review_status": "not_required" if artifact_type == "institution_research" else "not_started",
        "connector_status": "not_applicable",
        "freshness_status": "current",
        "content_version": "1",
        "evidence_cutoff_date": total.frontmatter.get("evidence_cutoff_date", ""),
        "updated_at": total.frontmatter.get("updated_at", ""),
        "runtime_owner": total.frontmatter.get("runtime_owner", ""),
    }
    if artifact_type in GENERIC_REVIEW_TYPES:
        base.update({field: "" for field in GENERIC_REVIEW_FIELDS})
    if artifact_type == "customer_letter_internal":
        base.update({field: "" for field in validator.LETTER_CONTEXT_FIELDS})
        base.update({"external_output_required": "false"})
        base.update({field: "" for field in LETTER_REVIEW_AUDIT_FIELDS})
    if artifact_type == "visit_strategy":
        base.update({field: "" for field in validator.STRATEGY_CONTEXT_FIELDS})
    if artifact_type == "briefing_delivery":
        base.update({"delivery_state": "draft_for_review", "page_proxy": "markdown-one-page/v1"})
    base.update(metadata)
    lines = ["---"] + [f"{key}: {json.dumps(str(value), ensure_ascii=False)}" for key, value in base.items()] + ["---", "", body]
    return "\n".join(lines).rstrip() + "\n"


def _review_status(artifact_type: str, module_status: str, freshness_status: str) -> str:
    if artifact_type == "institution_research":
        return "not_required"
    if module_status != "completed":
        return "not_started"
    if freshness_status == "current":
        return "pending"
    return "changes_requested"


def _normalize_metadata(artifact_type: str, value: object) -> dict[str, str]:
    if value is None:
        return {}
    metadata = _require_object(value, f"artifacts[{artifact_type}].metadata")
    allowed = TYPE_METADATA_FIELDS[artifact_type]
    unknown = sorted(metadata.keys() - allowed)
    if unknown:
        raise CandidateError(
            f"artifacts[{artifact_type}].metadata包含不可写字段：{', '.join(unknown)}。"
        )
    normalized: dict[str, str] = {}
    for key, item in metadata.items():
        normalized[key] = _plain_text(item, f"artifacts[{artifact_type}].metadata.{key}")
    return normalized


def _normalize_artifacts(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise CandidateError("artifacts必须是非空数组。")
    normalized: dict[str, dict[str, Any]] = {}
    allowed = {
        "artifact_type",
        "action",
        "module_status",
        "freshness_status",
        "connector_status",
        "body",
        "metadata",
        "key_claim_ids",
        "summary_sync_status",
        "downstream_invalidation",
        "gaps_blockers",
    }
    required = {"artifact_type", "action"}
    for index, raw in enumerate(value):
        item = _require_object(raw, f"artifacts[{index}]")
        _strict_keys(item, label=f"artifacts[{index}]", required=required, allowed=allowed)
        artifact_type = _plain_text(item["artifact_type"], f"artifacts[{index}].artifact_type", maximum=64)
        if artifact_type not in EDITABLE_TYPES:
            raise CandidateError(
                f"artifacts[{index}].artifact_type不允许由候选构建器写入：{artifact_type}。"
            )
        if artifact_type in normalized:
            raise CandidateError(f"artifacts中artifact_type重复：{artifact_type}。")
        action = _plain_text(item["action"], f"artifacts[{index}].action", maximum=16)
        if action not in RUN_ACTIONS:
            raise CandidateError(f"artifacts[{index}].action无效：{action}。")
        mutation = action in {"created", "updated"}
        if mutation:
            missing = [field for field in ("module_status", "freshness_status", "body") if field not in item]
            if missing:
                raise CandidateError(f"artifacts[{index}]执行{action}时缺少：{', '.join(missing)}。")
        else:
            forbidden = sorted(
                field
                for field in ("module_status", "freshness_status", "connector_status", "body", "metadata")
                if field in item
            )
            if forbidden:
                raise CandidateError(f"artifacts[{index}]执行{action}时不得提供：{', '.join(forbidden)}。")
        record: dict[str, Any] = {"artifact_type": artifact_type, "action": action}
        if mutation:
            module_status = _plain_text(item["module_status"], f"artifacts[{index}].module_status", maximum=16)
            freshness = _plain_text(item["freshness_status"], f"artifacts[{index}].freshness_status", maximum=16)
            connector = _plain_text(
                item.get("connector_status", "not_applicable"),
                f"artifacts[{index}].connector_status",
                maximum=32,
            )
            if module_status not in TERMINAL_STATUSES:
                raise CandidateError(f"artifacts[{index}].module_status必须是终态。")
            if freshness not in FRESHNESS_STATUSES:
                raise CandidateError(f"artifacts[{index}].freshness_status无效。")
            if connector not in CONNECTOR_STATUSES:
                raise CandidateError(f"artifacts[{index}].connector_status无效。")
            if artifact_type != "internal_retrieval" and connector != "not_applicable":
                raise CandidateError(f"{artifact_type}.connector_status必须为not_applicable。")
            record.update(
                {
                    "module_status": module_status,
                    "freshness_status": freshness,
                    "connector_status": connector,
                    "body": _body_text(item["body"], f"artifacts[{index}].body"),
                    "metadata": _normalize_metadata(artifact_type, item.get("metadata")),
                }
            )
        record["key_claim_ids"] = str(item.get("key_claim_ids", "")).strip()
        sync = str(item.get("summary_sync_status", "synced")).strip()
        invalidation = str(item.get("downstream_invalidation", "none")).strip()
        gaps = str(item.get("gaps_blockers", "无")).strip()
        if sync not in SUMMARY_SYNC_STATUSES:
            raise CandidateError(f"artifacts[{index}].summary_sync_status无效。")
        if invalidation not in DOWNSTREAM_INVALIDATIONS:
            raise CandidateError(f"artifacts[{index}].downstream_invalidation无效。")
        if not gaps or any(char in gaps for char in "\r\n"):
            raise CandidateError(f"artifacts[{index}].gaps_blockers不能为空或包含换行。")
        record.update(
            {
                "summary_sync_status": sync,
                "downstream_invalidation": invalidation,
                "gaps_blockers": gaps,
            }
        )
        normalized[artifact_type] = record
    return normalized


def _normalize_payload(
    payload: dict[str, Any],
    *,
    manifest: Mapping[str, object],
    total: validator.Document,
) -> dict[str, Any]:
    required = {
        "schema",
        "context_id",
        "expected_manifest_revision",
        "expected_manifest_sha256",
        "run",
        "artifacts",
    }
    allowed = required | {"total_body"}
    _strict_keys(payload, label="payload", required=required, allowed=allowed)
    if payload["schema"] != PAYLOAD_SCHEMA:
        raise CandidateError(f"payload.schema必须为{PAYLOAD_SCHEMA}。")
    context_id = _plain_text(payload["context_id"], "context_id", maximum=64)
    if context_id != total.frontmatter.get("context_id") or context_id != manifest.get("context_id"):
        raise CandidateError("payload.context_id与正式工作区不一致。")
    revision = payload["expected_manifest_revision"]
    if not isinstance(revision, int) or revision < 1:
        raise CandidateError("expected_manifest_revision必须是正整数。")
    expected_hash = _plain_text(payload["expected_manifest_sha256"], "expected_manifest_sha256", maximum=64)
    if not SHA256_RE.fullmatch(expected_hash):
        raise CandidateError("expected_manifest_sha256必须是64位小写SHA-256。")

    run = _require_object(payload["run"], "run")
    run_required = {
        "run_id",
        "updated_at",
        "evidence_cutoff_date",
        "runtime_owner",
        "workflow_stage",
        "module_status",
        "freshness_status",
        "objective",
    }
    _strict_keys(run, label="run", required=run_required, allowed=run_required)
    run_id = _plain_text(run["run_id"], "run.run_id", maximum=32)
    if not validator.run_id_valid(run_id):
        raise CandidateError("run.run_id格式必须为dcr-YYYYMMDDTHHMMSS-4chars。")
    timestamp, parsed_timestamp = _parse_timestamp(run["updated_at"], "run.updated_at")
    prior_timestamp = total.frontmatter.get("updated_at", "")
    if validator.timestamp_valid(prior_timestamp):
        prior = datetime.fromisoformat(prior_timestamp.replace("Z", "+00:00"))
        if parsed_timestamp < prior:
            raise CandidateError("run.updated_at不得早于综合报告当前updated_at。")
    utc_stamp = parsed_timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")
    if run_id[4:19] != utc_stamp:
        raise CandidateError("run.run_id时间部分必须与run.updated_at对应的UTC时点一致。")
    history = validator.version_history_rows(total, [])
    known_runs = {row[2] for row in history} | {
        document.frontmatter.get("latest_run_id", "")
        for document in _load_documents(total.path.parent).values()
    }
    if run_id in known_runs:
        raise CandidateError("run.run_id已在正式工作区使用，必须生成新run_id。")
    task_timezone = str(manifest["task_timezone"]) if manifest.get("task_timezone") else None
    cutoff = _parse_cutoff(run["evidence_cutoff_date"], task_timezone)
    runtime_owner = _plain_text(run["runtime_owner"], "run.runtime_owner", maximum=100)
    if "|" in runtime_owner:
        raise CandidateError("run.runtime_owner不得包含表格分隔符。")
    stage = _plain_text(run["workflow_stage"], "run.workflow_stage", maximum=24)
    if stage not in WORKFLOW_STAGES:
        raise CandidateError("run.workflow_stage无效。")
    total_status = _plain_text(run["module_status"], "run.module_status", maximum=16)
    total_freshness = _plain_text(run["freshness_status"], "run.freshness_status", maximum=16)
    if total_status not in TERMINAL_STATUSES:
        raise CandidateError("run.module_status必须是partial/completed/blocked。")
    if total_freshness not in FRESHNESS_STATUSES:
        raise CandidateError("run.freshness_status无效。")
    objective = _plain_text(run["objective"], "run.objective", maximum=200)
    if any(char in objective for char in ";=\r\n"):
        raise CandidateError("run.objective不得包含分号、等号或换行。")

    artifacts = _normalize_artifacts(payload["artifacts"])
    total_body = _body_text(payload["total_body"], "total_body") if "total_body" in payload else None
    return {
        "context_id": context_id,
        "expected_manifest_revision": revision,
        "expected_manifest_sha256": expected_hash,
        "run_id": run_id,
        "updated_at": timestamp,
        "evidence_cutoff_date": cutoff,
        "runtime_owner": runtime_owner,
        "workflow_stage": stage,
        "module_status": total_status,
        "freshness_status": total_freshness,
        "objective": objective,
        "artifacts": artifacts,
        "total_body": total_body,
    }


def _reset_review_updates(
    artifact_type: str,
    module_status: str,
    freshness_status: str,
) -> dict[str, str]:
    updates = {"review_status": _review_status(artifact_type, module_status, freshness_status)}
    if artifact_type in GENERIC_REVIEW_TYPES:
        updates.update({field: "" for field in GENERIC_REVIEW_FIELDS})
    if artifact_type == "briefing_delivery":
        updates["delivery_state"] = "draft_for_review"
    if artifact_type == "customer_letter_internal":
        updates.update({field: "" for field in LETTER_REVIEW_AUDIT_FIELDS})
        updates["external_output_required"] = "false"
    return updates


def _render_artifact(
    *,
    total: validator.Document,
    existing: validator.Document | None,
    record: Mapping[str, Any],
    path: Path,
    run: Mapping[str, Any],
) -> str:
    action = str(record["action"])
    if action == "created" and existing is not None:
        raise CandidateError(f"{record['artifact_type']}已存在，action必须使用updated或reused。")
    if action == "updated" and existing is None:
        raise CandidateError(f"{record['artifact_type']}不存在，action必须使用created。")
    if action not in {"created", "updated"}:
        raise CandidateError("内部错误：_render_artifact只接受created/updated。")
    artifact_type = str(record["artifact_type"])
    metadata = dict(record.get("metadata", {}))
    body = str(record["body"])
    if artifact_type == "visit_strategy":
        variant = str(
            metadata.get("strategy_variant")
            or (existing.frontmatter.get("strategy_variant", "") if existing else "")
        )
        contract = validator.strategy_variant_contract(
            total.frontmatter.get("business_mode", ""),
            variant,
        )
        if contract is None:
            raise CandidateError(f"strategy_variant={variant or '空'}缺少可执行的业务模式契约。")
        forbidden = {
            str(field)
            for field in contract.get("forbidden_business_fields", [])
            if isinstance(field, str)
        }
        supplied = sorted(forbidden & metadata.keys())
        if supplied:
            raise CandidateError(
                f"strategy_variant={variant}不得提供另一分支或会议专属metadata："
                + ", ".join(supplied)
            )
    if existing is None:
        text = _new_document_text(
            total=total,
            artifact_type=artifact_type,
            body=body,
            metadata=metadata,
        )
        next_version = "1"
    else:
        current_version = existing.frontmatter.get("content_version", "")
        if not validator.CONTENT_VERSION_RE.fullmatch(current_version):
            raise CandidateError(f"{existing.path.name}.content_version无效。")
        next_version = str(int(current_version) + 1)
        text = _replace_body(existing.text, body, existing.path)
    module_status = str(record["module_status"])
    freshness = str(record["freshness_status"])
    updates = {
        **metadata,
        "latest_run_id": str(run["run_id"]),
        "content_version": next_version,
        "updated_at": str(run["updated_at"]),
        "evidence_cutoff_date": str(run["evidence_cutoff_date"]),
        "runtime_owner": str(run["runtime_owner"]),
        "module_status": module_status,
        "freshness_status": freshness,
        "connector_status": str(record["connector_status"]),
        **_reset_review_updates(artifact_type, module_status, freshness),
    }
    rendered = validator.replace_flat_frontmatter(text, updates)
    _frontmatter_and_body(rendered, path)
    return rendered


def _claims_for(document: validator.Document) -> str:
    claims = sorted(set(validator.CLAIM_RE.findall(validator.body_without_placeholders(document))))
    return ", ".join(claims)


def _status_extras(
    artifact_type: str,
    document: validator.Document | None,
    record: Mapping[str, Any] | None,
    previous_rows: Mapping[str, list[str]],
) -> list[str]:
    if record is not None:
        claim_ids = str(record.get("key_claim_ids", "")).strip()
        if not claim_ids and document is not None:
            claim_ids = _claims_for(document)
        return [
            str(record.get("summary_sync_status", "synced")),
            claim_ids,
            str(record.get("downstream_invalidation", "none")),
            str(record.get("gaps_blockers", "无")),
        ]
    old = previous_rows.get(artifact_type, [])
    if len(old) == 15:
        return old[10:14]
    if document is None:
        return ["not_applicable", "", "none", "无"]
    return [
        "not_applicable" if artifact_type == "customer_letter_external" else "synced",
        _claims_for(document),
        "none",
        "无",
    ]


def _rebuild_status_rows(
    total: validator.Document,
    by_type: Mapping[str, validator.Document],
    records: Mapping[str, Mapping[str, Any]],
) -> tuple[str, dict[str, str]]:
    text = total.text
    previous_rows = validator.parse_status_rows(total)
    actions: dict[str, str] = {
        artifact_type: str(record["action"])
        for artifact_type, record in records.items()
    }
    for artifact_type, label in validator.STATUS_LABELS.items():
        document = by_type.get(artifact_type)
        action = actions.get(artifact_type, "not_called")
        if artifact_type == "customer_letter_external" and action != "not_called":
            raise CandidateError("客户信外发版只能由--emit-external事务生成。")
        extras = _status_extras(
            artifact_type,
            document,
            records.get(artifact_type),
            previous_rows,
        )
        replacement = validator.registry_row(
            label,
            document.frontmatter if document else None,
            document.path if document else None,
            action=action,
            extras=extras,
        )
        try:
            text = validator.replace_or_insert_status_row(text, label, replacement)
        except RuntimeError as exc:
            raise CandidateError(str(exc)) from exc
    partition = {
        ACTION_TYPES[artifact_type]: actions.get(artifact_type, "not_called")
        for artifact_type in validator.STATUS_LABELS
    }
    return text, partition


def _member_list(members: list[str]) -> str:
    return ",".join(members) if members else "none"


def _run_summary(total: validator.Document, actions: Mapping[str, str], run: Mapping[str, Any]) -> str:
    selected = [name for name in validator.RUN_ARTIFACT_NAMES if actions.get(name) != "not_called"]
    ordered_names = list(validator.RUN_ARTIFACT_ORDER)
    parts = [
        f"route={total.frontmatter.get('route', '')}",
        f"depth={total.frontmatter.get('depth', '')}",
        f"objective={run['objective']}",
        f"selected_modules={_member_list([name for name in ordered_names if name in selected])}",
    ]
    for action in ("created", "updated", "reused", "generated", "not_called"):
        members = [name for name in ordered_names if actions.get(name, "not_called") == action]
        parts.append(f"{action}={_member_list(members)}")
    parts.append(f"target_evidence_cutoff_date={run['evidence_cutoff_date']}")
    return "; ".join(parts)


def _candidate_documents(candidate: Path) -> dict[str, validator.Document]:
    return _load_documents(candidate)


def _write_candidate_manifest(
    candidate: Path,
    *,
    live_manifest: Mapping[str, object],
    total: validator.Document,
    transaction_sequence: int,
) -> None:
    rows = validator.parse_status_rows(total)
    selected_modules = [
        ACTION_TYPES[artifact_type]
        for artifact_type, row in rows.items()
        if artifact_type in ACTION_TYPES
        and artifact_type not in {"customer_letter_external", "briefing_delivery"}
        and len(row) >= 2
        and row[1] == "true"
    ]
    raw_authorization = live_manifest.get("authorization", {})
    authorization = dict(raw_authorization) if isinstance(raw_authorization, dict) else {}
    manifest = build_manifest(
        candidate,
        identity={
            "context_id": total.frontmatter.get("context_id", ""),
            "customer_id": total.frontmatter.get("customer_id", ""),
            "customer_display_name": total.frontmatter.get("customer_display_name", ""),
            "organization_scope": total.frontmatter.get("organization_scope", ""),
        },
        business_mode=total.frontmatter.get("business_mode", ""),
        route=total.frontmatter.get("route", ""),
        depth=total.frontmatter.get("depth", ""),
        task_timezone=(
            str(live_manifest["task_timezone"])
            if live_manifest.get("task_timezone") is not None
            else None
        ),
        latest_run_id=total.frontmatter.get("latest_run_id", ""),
        content_version=total.frontmatter.get("content_version", ""),
        stage=total.frontmatter.get("workflow_stage", ""),
        ready_for_use=False,
        selected_modules=selected_modules,
        authorization=authorization,
        transaction_sequence=transaction_sequence,
        intake_preflight=(
            dict(live_manifest["intake_preflight"])
            if isinstance(live_manifest.get("intake_preflight"), dict)
            else None
        ),
    )
    runtime = candidate / "runtime"
    runtime.mkdir(exist_ok=True)
    (runtime / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_candidate(candidate: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("validate_outputs.py")),
            str(candidate),
            "--profile",
            "scaffold",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CandidateError(
            "候选校验没有返回有效JSON：" + (completed.stderr.strip() or completed.stdout.strip())
        ) from exc
    if completed.returncode or int(payload.get("errors", 0)):
        codes = sorted({str(issue.get("code", "unknown")) for issue in payload.get("issues", [])})
        raise CandidateError("候选完整校验失败：" + ", ".join(codes))
    return {
        "validation_profile": "scaffold",
        "errors": int(payload.get("errors", 0)),
        "warnings": int(payload.get("warnings", 0)),
        "issue_codes": sorted({str(issue.get("code", "")) for issue in payload.get("issues", []) if issue.get("code")}),
    }


def _diff(
    live: Mapping[str, validator.Document],
    candidate: Mapping[str, validator.Document],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for artifact_type in sorted(set(live) | set(candidate)):
        before = live.get(artifact_type)
        after = candidate.get(artifact_type)
        before_raw = before.text.encode("utf-8") if before else b""
        after_raw = after.text.encode("utf-8") if after else b""
        if before_raw == after_raw:
            continue
        result.append(
            {
                "artifact_type": artifact_type,
                "path": after.path.name if after else before.path.name,
                "change": "created" if before is None else "deleted" if after is None else "modified",
                "before_sha256": sha256_bytes(before_raw) if before else None,
                "after_sha256": sha256_bytes(after_raw) if after else None,
                "before_content_version": before.frontmatter.get("content_version") if before else None,
                "after_content_version": after.frontmatter.get("content_version") if after else None,
                "before_latest_run_id": before.frontmatter.get("latest_run_id") if before else None,
                "after_latest_run_id": after.frontmatter.get("latest_run_id") if after else None,
                "before_review_status": before.frontmatter.get("review_status") if before else None,
                "after_review_status": after.frontmatter.get("review_status") if after else None,
            }
        )
    return result


def _output_container(output_root: Path, context_id: str, run_id: str) -> Path:
    supplied = output_root.expanduser()
    if supplied.is_symlink():
        raise CandidateError("--output-root不得为符号链接。")
    root = supplied.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise CandidateError("--output-root必须是普通目录。")
    suffix = context_id.rsplit("-", 1)[-1]
    run_suffix = run_id.rsplit("-", 1)[-1]
    container = root / f"candidate-{suffix}-{run_suffix}"
    if container.exists() or container.is_symlink():
        raise CandidateError(f"候选容器已存在，拒绝覆盖：{container}。")
    return container


def build(args: argparse.Namespace) -> dict[str, Any]:
    supplied_workspace = Path(args.workspace).expanduser()
    if supplied_workspace.is_symlink():
        raise CandidateError("workspace不得为符号链接。")
    workspace = supplied_workspace.resolve()
    if Path(os.path.abspath(supplied_workspace)) != workspace or not workspace.is_dir():
        raise CandidateError("workspace不存在、包含重定向或不是普通目录。")
    payload, payload_sha256 = _load_payload(Path(args.payload))
    expected_revision = payload.get("expected_manifest_revision")
    expected_hash = payload.get("expected_manifest_sha256")
    if not isinstance(expected_revision, int) or not isinstance(expected_hash, str):
        raise CandidateError("payload缺少有效manifest CAS字段。")
    try:
        live_manifest = assert_manifest_cas(workspace, expected_revision, expected_hash)
        verify_manifest_artifacts(workspace, live_manifest)
    except (CASMismatch, TxError) as exc:
        raise CandidateError(str(exc)) from exc
    live_documents = _load_documents(workspace)
    total = _validate_live_identity(workspace, live_manifest, live_documents)
    normalized = _normalize_payload(payload, manifest=live_manifest, total=total)
    if normalized["expected_manifest_revision"] != expected_revision or normalized["expected_manifest_sha256"] != expected_hash:
        raise CandidateError("manifest CAS字段在解析期间发生漂移。")

    output_root = Path(args.output_root).expanduser().resolve()
    try:
        output_root.relative_to(workspace)
    except ValueError:
        pass
    else:
        raise CandidateError("--output-root不得位于正式workspace内部。")
    container = _output_container(output_root, normalized["context_id"], normalized["run_id"])
    candidate = container / workspace.name
    container.mkdir()
    candidate.mkdir()
    try:
        for document in live_documents.values():
            shutil.copy2(document.path, candidate / document.path.name)
        for relative in RUNTIME_MACHINE_RELS:
            source = workspace / relative
            if source.is_file() and not source.is_symlink():
                (candidate / "runtime").mkdir(exist_ok=True)
                shutil.copy2(source, candidate / relative)

        candidate_by_type = _candidate_documents(candidate)
        records: dict[str, dict[str, Any]] = normalized["artifacts"]
        existing_external = candidate_by_type.get("customer_letter_external")
        letter_record = records.get("customer_letter_internal")
        if existing_external is not None and letter_record and letter_record["action"] in {"created", "updated"}:
            raise CandidateError("现行外发版存在；修改内部稿前必须先执行--begin-letter-revision归档事务。")

        for artifact_type, record in records.items():
            action = record["action"]
            if action in {"reused", "not_called"}:
                exists = candidate_by_type.get(artifact_type)
                if action == "reused" and exists is None:
                    raise CandidateError(f"{artifact_type}标记reused但正式成果不存在。")
                continue
            expected_name = _expected_filename(total.frontmatter["safe_name"], artifact_type)
            path = candidate / expected_name
            rendered = _render_artifact(
                total=total,
                existing=candidate_by_type.get(artifact_type),
                record=record,
                path=path,
                run=normalized,
            )
            path.write_text(rendered, encoding="utf-8")
            candidate_by_type = _candidate_documents(candidate)

        candidate_total = candidate_by_type["comprehensive_report"]
        total_text = candidate_total.text
        if normalized["total_body"] is not None:
            prior_runs = {row[2] for row in validator.version_history_rows(candidate_total, [])}
            missing_runs = sorted(run_id for run_id in prior_runs if run_id not in normalized["total_body"])
            if missing_runs:
                raise CandidateError("total_body丢失既有运行历史：" + ", ".join(missing_runs))
            total_text = _replace_body(total_text, normalized["total_body"], candidate_total.path)
        current_total_version = candidate_total.frontmatter.get("content_version", "")
        if not validator.CONTENT_VERSION_RE.fullmatch(current_total_version):
            raise CandidateError("综合报告content_version无效。")
        next_total_version = str(int(current_total_version) + 1)
        total_text = validator.replace_flat_frontmatter(
            total_text,
            {
                "latest_run_id": normalized["run_id"],
                "content_version": next_total_version,
                "updated_at": normalized["updated_at"],
                "evidence_cutoff_date": normalized["evidence_cutoff_date"],
                "runtime_owner": normalized["runtime_owner"],
                "workflow_stage": normalized["workflow_stage"],
                "module_status": normalized["module_status"],
                "freshness_status": normalized["freshness_status"],
                "review_status": "not_required",
                "connector_status": "not_applicable",
                **validator.readiness_reset_updates(),
            },
        )
        total_data, total_body = _frontmatter_and_body(total_text, candidate_total.path)
        total_document = validator.Document(candidate_total.path, total_text, total_data, total_body)
        total_text, action_partition = _rebuild_status_rows(total_document, candidate_by_type, records)
        total_data, total_body = _frontmatter_and_body(total_text, candidate_total.path)
        total_document = validator.Document(candidate_total.path, total_text, total_data, total_body)
        summary = _run_summary(total_document, action_partition, normalized)
        total_text = validator.append_operation_record(
            total_text,
            timestamp=normalized["updated_at"],
            version=next_total_version,
            run_id=normalized["run_id"],
            summary=summary,
            owner=normalized["runtime_owner"],
        )
        candidate_total.path.write_text(total_text, encoding="utf-8")

        candidate_by_type = _candidate_documents(candidate)
        _write_candidate_manifest(
            candidate,
            live_manifest=live_manifest,
            total=candidate_by_type["comprehensive_report"],
            transaction_sequence=expected_revision + 1,
        )
        marker = {
            "schema": "discovery-call-candidate-receipt/v1",
            "context_id": normalized["context_id"],
            "run_id": normalized["run_id"],
            "source_manifest_revision": expected_revision,
            "source_manifest_sha256": expected_hash,
            "source_workspace": str(workspace),
            "candidate_workspace": str(candidate),
            # Bind the receipt to the candidate manifest.  That manifest in
            # turn hashes every Markdown artifact and tracked runtime file.
            "payload_sha256": sha256_file(candidate / "runtime" / "manifest.json"),
        }
        (candidate / CANDIDATE_MARKER_REL).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validation = _validate_candidate(candidate)
        candidate_by_type = _candidate_documents(candidate)
        differences = _diff(live_documents, candidate_by_type)
        if not differences:
            raise CandidateError("payload没有产生任何候选差异。")

        live_total_state = file_state(total.path)
        commit_parameters = {
            "workspace": str(workspace),
            "candidate_workspace": str(candidate),
            "expected_manifest_revision": expected_revision,
            "expected_manifest_sha256": expected_hash,
            "expected_content_version": live_total_state.content_version,
            "expected_latest_run_id": live_total_state.latest_run_id,
            "expected_total_sha256": live_total_state.sha256,
            "operation": f"candidate_{normalized['run_id']}",
        }
        command = [
            sys.executable,
            str(Path(__file__).with_name("commit_run.py")),
            str(workspace),
            "--candidate-workspace",
            str(candidate),
            "--expected-manifest-revision",
            str(expected_revision),
            "--expected-manifest-sha256",
            expected_hash,
            "--expected-content-version",
            live_total_state.content_version,
            "--expected-latest-run-id",
            live_total_state.latest_run_id,
            "--expected-total-sha256",
            live_total_state.sha256,
            "--operation",
            commit_parameters["operation"],
            "--json",
        ]
        return {
            "schema": "discovery-call-candidate-result/v1",
            "workspace": str(workspace),
            "candidate_workspace": str(candidate),
            "payload_sha256": payload_sha256,
            "context_id": normalized["context_id"],
            "run_id": normalized["run_id"],
            "validation": validation,
            "diff": differences,
            "next_commit": {
                "script": str(Path(__file__).with_name("commit_run.py")),
                "parameters": commit_parameters,
                "argv": command,
            },
        }
    except Exception:
        shutil.rmtree(container, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从单个结构化run payload安全构建隔离候选；不写正式workspace。"
    )
    parser.add_argument("workspace", help="已有runtime/manifest.json保护的正式工作区")
    parser.add_argument("--payload", required=True, help="discovery-call-candidate-run/v1 JSON文件")
    parser.add_argument("--output-root", required=True, help="用于新建隔离candidate容器的目录")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果（默认同样输出JSON）")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = build(args)
    except (CandidateError, CASMismatch, TxError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
