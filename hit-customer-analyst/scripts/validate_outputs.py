#!/usr/bin/env python3
"""Validate discovery-call v2.6 outputs and perform governed review operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from runtime_tx import (
    MANIFEST_REL,
    TxError,
    build_manifest,
    file_state,
    load_manifest,
    manifest_state,
    sha256_file,
    transactional_write,
)

SCHEMA = "discovery-call-output/v2.5"
REQUIRED_FIELDS = {
    "schema",
    "artifact_type",
    "context_id",
    "latest_run_id",
    "customer_id",
    "customer_display_name",
    "organization_scope",
    "safe_name",
    "module_status",
    "review_status",
    "connector_status",
    "freshness_status",
    "content_version",
    "evidence_cutoff_date",
    "updated_at",
    "runtime_owner",
}
TOTAL_REQUIRED_FIELDS = {"route", "depth", "workflow_stage"}
MODULE_STATUSES = {"not_called", "queued", "running", "partial", "completed", "blocked"}
REVIEW_STATUSES = {
    "not_required",
    "not_started",
    "pending",
    "approved",
    "changes_requested",
}
CONNECTOR_STATUSES = {
    "not_applicable",
    "not_configured",
    "connected",
    "no_hits",
    "permission_denied",
    "failed",
}
FRESHNESS_STATUSES = {"current", "stale", "invalidated"}
WORKFLOW_STAGES = {
    "intake",
    "disambiguation",
    "planning",
    "research",
    "synthesis",
    "confirmation",
    "output",
    "review",
    "closed",
    "paused",
}
ROUTES = {"research_only", "visit_prep", "strategy", "letter", "refresh"}
DEPTHS = {"quick", "standard", "deep"}
RUN_ACTIONS = {"not_called", "created", "reused", "updated", "generated"}
RUN_ARTIFACT_NAMES = {
    "institution",
    "leader",
    "internal",
    "strategy",
    "letter",
    "external_letter",
}
SUMMARY_SYNC_STATUSES = {"not_applicable", "pending", "synced", "out_of_sync"}
DOWNSTREAM_INVALIDATIONS = {"none", "stale", "invalidated"}
ARTIFACT_TYPES = {
    "comprehensive_report",
    "institution_research",
    "leader_research",
    "internal_retrieval",
    "visit_strategy",
    "customer_letter_internal",
    "customer_letter_external",
}
RESEARCH_PREFIX = {
    "institution_research": "I",
    "leader_research": "L",
    "internal_retrieval": "N",
}
SUFFIXES = {
    "comprehensive_report": "客户研究与拜访准备报告.md",
    "institution_research": "机构研究报告.md",
    "leader_research": "人物研究报告.md",
    "internal_retrieval": "内部信息检索报告.md",
    "visit_strategy": "交流策略与议题设计.md",
    "customer_letter_internal": "客户信（内部待审核稿）.md",
    "customer_letter_external": "客户信（外发版）.md",
}
STATUS_LABELS = {
    "institution_research": "机构研究",
    "leader_research": "人物研究",
    "internal_retrieval": "内部检索",
    "visit_strategy": "交流策略",
    "customer_letter_internal": "客户信内部审核稿",
    "customer_letter_external": "客户信外发版",
}
TERMINAL_STATUSES = {"partial", "completed", "blocked"}
CLAIM_TYPES = {"F", "F2", "A", "H", "R"}
PROVENANCE_VALUES = {"public", "U", "N"}
VERIFICATION_STATUSES = {
    "asserted",
    "verified_single",
    "corroborated",
    "conflicted",
    "stale",
    "invalidated",
    "unusable",
}
SOURCE_LEVELS = {"S", "A", "B", "C", "internal"}
SOURCE_PERMISSIONS = {"public", "internal-authorized", "restricted"}
SOURCE_EXTERNAL_USE_VALUES = {"true", "false"}
SAFE_FACT_VERIFICATIONS = {"verified_single", "corroborated"}
UNSAFE_DOWNSTREAM_VERIFICATIONS = {"conflicted", "stale", "invalidated", "unusable"}
CONTEXT_RE = re.compile(r"^dcx-\d{8}-[A-Za-z0-9]{8}$")
RUN_RE = re.compile(r"^dcr-\d{8}T\d{6}-[A-Za-z0-9]{4}$")
CONTENT_VERSION_RE = re.compile(r"^[1-9][0-9]*$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{3,128}$")
INVALID_SAFE_CHARS = re.compile(r'[<>:"/\\|?*#%()\[\]\x00-\x1f\x7f]+')
WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]+\}\}")
SHA256_FINGERPRINT_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
PROVIDER_FINGERPRINT_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9._-]{1,31}:[A-Za-z0-9][A-Za-z0-9._:/+-]{2,255}$"
)
CLAIM_RE = re.compile(r"(?<![A-Za-z0-9_-])CLM-(?:I|L|N)-[0-9]{3,}(?![A-Za-z0-9_-])")
SOURCE_RE = re.compile(r"(?<![A-Za-z0-9_-])SRC-(?:I|L|N)-[0-9]{3,}(?![A-Za-z0-9_-])")
LEGACY_EVIDENCE_RE = re.compile(r"\b(?:I|L|N)-E\d{3,}\b")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FORBIDDEN_EXTERNAL_TERMS = {
    "EXTERNAL_BODY_START",
    "EXTERNAL_BODY_END",
    "内部审核",
    "个性化依据",
    "待核实事实",
    "销售判断",
    "销售研判",
    "竞对",
    "竞争态势",
    "价格底线",
    "关系评价",
    "受限资料",
    "承诺检查",
    "审核人",
    "claim_id",
    "source_id",
    "主张ID",
    "来源ID",
}
HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
APPROVAL_FIELDS = {
    "approver",
    "approved_at",
    "approved_content_version",
    "approved_body_sha256",
    "approved_context_sha256",
}
LETTER_CONTEXT_FIELDS = {
    "letter_scenario",
    "recipient_role",
    "letter_purpose",
    "expected_action",
    "signer",
    "delivery_channel",
}
STRATEGY_CONTEXT_FIELDS = {
    "target_contact_level",
    "visit_objective",
    "minimum_next_step",
}
INTERNAL_LETTER_FIELDS = (
    APPROVAL_FIELDS | LETTER_CONTEXT_FIELDS | {"external_output_required"}
)
EXTERNAL_LINEAGE_FIELDS = APPROVAL_FIELDS | {"source_internal_content_version"}
GENERIC_REVIEW_FIELDS = {
    "reviewer",
    "reviewed_at",
    "reviewed_content_version",
    "reviewed_body_sha256",
}
GENERIC_REVIEW_TYPES = {"leader_research", "internal_retrieval", "visit_strategy"}
GENERIC_REVIEW_TARGETS = {
    "leader": "leader_research",
    "internal": "internal_retrieval",
    "strategy": "visit_strategy",
}
BUSINESS_MODES = {"briefing", "standard_visit", "strategic_account", "letter"}
AUTHORIZATION_FIELDS = {
    "tenant_id",
    "project_id",
    "authorization_owner",
    "authorization_expires_at",
}
READINESS_FIELDS = {
    "readiness_reviewer",
    "readiness_reviewed_at",
    "readiness_content_version",
    "readiness_body_sha256",
}


def readiness_reset_updates() -> dict[str, str]:
    return {"ready_for_use": "false", **dict.fromkeys(READINESS_FIELDS, "")}


REFRESH_HEADING = "## 8.1 刷新结果记录"
REFRESH_HEADER = ["run_id", "新增", "更正", "失效", "未变化", "待确认"]
REFRESH_ITEM_RE = re.compile(r"^(?:CLM|SRC)-(?:I|L|N)-\d{3,}$")
LETTER_REVIEW_HEADING = "## 4. 版本与审核记录（严禁外发）"


@dataclass
class Issue:
    severity: str
    code: str
    path: str
    message: str


@dataclass
class Document:
    path: Path
    text: str
    frontmatter: dict[str, str]
    body: str


@dataclass
class ClaimDefinition:
    claim_id: str
    document: Document
    cells: list[str]
    line: str


@dataclass
class SourceDefinition:
    source_id: str
    document: Document
    cells: list[str]
    line: str


def add(
    issues: list[Issue], severity: str, code: str, path: Path, message: str
) -> None:
    issues.append(Issue(severity, code, str(path), message))


def markdown_without_fenced_code(text: str) -> str:
    """Mask fenced code so examples cannot be parsed as control metadata."""
    output: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            output.append("")
            continue
        output.append("" if fence else line)
    return "\n".join(output)


def has_extra_frontmatter_block(body: str) -> bool:
    lines = markdown_without_fenced_code(body).split("\n")
    delimiters = [
        index for index, line in enumerate(lines) if re.fullmatch(r"---[ \t]*", line)
    ]
    for left, right in zip(delimiters, delimiters[1:]):
        if any(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:\s*.*", line)
            for line in lines[left + 1 : right]
        ):
            return True
    return False


def parse_frontmatter(
    path: Path, text: str, issues: list[Issue]
) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        add(
            issues,
            "error",
            "frontmatter_missing",
            path,
            "成果文件必须以YAML frontmatter开始。",
        )
        return {}, text
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        add(
            issues,
            "error",
            "frontmatter_unclosed",
            path,
            "YAML frontmatter缺少结束分隔符。",
        )
        return {}, text
    data: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not match:
            add(
                issues,
                "error",
                "frontmatter_unsupported",
                path,
                f"第{line_number}行不是扁平key: value。",
            )
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                add(
                    issues,
                    "error",
                    "frontmatter_string_invalid",
                    path,
                    f"第{line_number}行不是合法JSON字符串。",
                )
                continue
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        if key in data:
            add(issues, "error", "frontmatter_duplicate", path, f"字段{key}重复。")
        data[key] = value
    body = "\n".join(lines[end + 1 :])
    if has_extra_frontmatter_block(body):
        add(
            issues,
            "error",
            "frontmatter_duplicate_block",
            path,
            "检测到第二个顶层frontmatter块。",
        )
    return data, body


def body_from_text(text: str) -> str:
    lines = text.splitlines()
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return text
    return "\n".join(lines[end + 1 :])


def looks_like_artifact(path: Path, text: str) -> bool:
    if any(path.name.endswith(suffix) for suffix in SUFFIXES.values()):
        return True
    head = "\n".join(text.splitlines()[:30])
    return bool(
        re.search(r"^schema:\s*[\"']?discovery-call-output/v2\.5[\"']?\s*$", head, re.M)
    )


def load_documents(root: Path, issues: list[Issue]) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(root.glob("*.md")):
        if path.is_symlink() or path.resolve().parent != root.resolve():
            add(
                issues,
                "error",
                "artifact_symlink",
                path,
                "成果文件不得为符号链接或越出工作目录。",
            )
            continue
        try:
            # CAS hashes bind disk bytes, not universal-newline-normalized text.
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            add(issues, "error", "read_failed", path, str(exc))
            continue
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            add(
                issues,
                "error",
                "artifact_control_character",
                path,
                "成果文件包含不允许的控制字符。",
            )
        if not looks_like_artifact(path, text):
            continue
        frontmatter, body = parse_frontmatter(path, text, issues)
        documents.append(Document(path, text, frontmatter, body))
    return documents


def timestamp_valid(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def date_valid(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parse_expiry(value: str) -> datetime | None:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed_date = date.fromisoformat(value)
            return datetime.combine(
                parsed_date, datetime.max.time(), tzinfo=timezone.utc
            )
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def load_business_profiles() -> dict[str, dict[str, object]]:
    path = Path(__file__).resolve().parent.parent / "config" / "business-modes.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取业务模式配置{path}：{exc}") from exc
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict) or not profiles.keys() >= BUSINESS_MODES:
        raise RuntimeError(f"业务模式配置{path}缺少完整profiles对象。")
    if any(not isinstance(profiles[mode], dict) for mode in BUSINESS_MODES):
        raise RuntimeError(f"业务模式配置{path}的profile必须为对象。")
    return profiles


def context_id_valid(value: str) -> bool:
    if not CONTEXT_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value[4:12], "%Y%m%d")
        return True
    except ValueError:
        return False


def run_id_valid(value: str) -> bool:
    if not RUN_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value[4:19], "%Y%m%dT%H%M%S")
        return True
    except ValueError:
        return False


def new_run_id(timestamp: datetime) -> str:
    return f"dcr-{timestamp:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:4]}"


def canonical_safe_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = INVALID_SAFE_CHARS.sub("-", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip(" .-")
    if WINDOWS_RESERVED.fullmatch(normalized):
        normalized = f"客户-{normalized}"
    return normalized[:48].rstrip(" .-")


def safe_component(value: str) -> bool:
    return bool(
        value
        and len(value) <= 48
        and value not in {".", ".."}
        and ".." not in value
        and "/" not in value
        and "\\" not in value
        and not INVALID_SAFE_CHARS.search(value)
        and not WINDOWS_RESERVED.fullmatch(value)
        and value == value.strip(" .-")
        and Path(value).name == value
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
        and value == canonical_safe_component(value)
    )


def resolved_strategy_context(key: str, value: str) -> bool:
    if resolved_business_text(value):
        return True
    if key not in {"visit_objective", "minimum_next_step"}:
        return False
    normalized = unicodedata.normalize("NFKC", value).strip()
    # A defined verification action may explicitly concern unconfirmed matters.
    # This never confirms the underlying fact, person, or approval.
    return bool(
        8 <= len(normalized) <= 500
        and not PLACEHOLDER_RE.search(normalized)
        and not any(ord(c) < 32 or ord(c) == 127 for c in normalized)
        and re.match(r"^(形成|列明|整理|核实|确认|验证|判断|收集|记录|梳理)", normalized)
    )


def resolved_business_text(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized_folded = normalized.casefold()
    unresolved_markers = (
        "待确认",
        "未确认",
        "待核实",
        "未核实",
        "待指定",
        "待补充",
        "unknown",
    )
    return bool(
        normalized
        and len(normalized) <= 500
        and not PLACEHOLDER_RE.search(normalized)
        and normalize_evidence_text(normalized)
        not in {"待确认", "待指定", "待补充", "unknown", "none", "n/a", "na", "无"}
        and not any(marker in normalized_folded for marker in unresolved_markers)
        and not any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    )


def letter_context_sha256(data: dict[str, str]) -> str:
    payload = {key: data.get(key, "") for key in sorted(LETTER_CONTEXT_FIELDS)}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_frontmatter(document: Document, issues: list[Issue], strict: bool) -> None:
    data = document.frontmatter
    required = REQUIRED_FIELDS | (
        TOTAL_REQUIRED_FIELDS
        if data.get("artifact_type") == "comprehensive_report"
        else set()
    )
    missing = sorted(required - data.keys())
    if missing:
        add(
            issues,
            "error",
            "frontmatter_required",
            document.path,
            "缺少字段：" + ", ".join(missing),
        )
        return
    if data.get("artifact_type") == "customer_letter_internal":
        approval_missing = sorted(INTERNAL_LETTER_FIELDS - data.keys())
        if approval_missing:
            add(
                issues,
                "error",
                "approval_metadata_required",
                document.path,
                "客户信内部稿缺少业务上下文/外发/审批字段："
                + ", ".join(approval_missing),
            )
    if data.get("artifact_type") == "visit_strategy":
        strategy_missing = sorted(STRATEGY_CONTEXT_FIELDS - data.keys())
        if strategy_missing:
            add(
                issues,
                "error",
                "strategy_context_required",
                document.path,
                "交流策略缺少执行上下文字段：" + ", ".join(strategy_missing),
            )
    if data.get("artifact_type") == "customer_letter_external":
        lineage_missing = sorted(EXTERNAL_LINEAGE_FIELDS - data.keys())
        if lineage_missing:
            add(
                issues,
                "error",
                "external_lineage_required",
                document.path,
                "客户信外发版缺少谱系字段：" + ", ".join(lineage_missing),
            )
    if data["schema"] != SCHEMA:
        add(issues, "error", "schema_invalid", document.path, f"schema必须为{SCHEMA}。")
    if data["artifact_type"] not in ARTIFACT_TYPES:
        add(
            issues,
            "error",
            "artifact_type_invalid",
            document.path,
            "artifact_type不在允许集合。",
        )
    if data["module_status"] not in MODULE_STATUSES:
        add(
            issues,
            "error",
            "module_status_invalid",
            document.path,
            "module_status枚举无效。",
        )
    if data["review_status"] not in REVIEW_STATUSES:
        add(
            issues,
            "error",
            "review_status_invalid",
            document.path,
            "review_status枚举无效。",
        )
    if data["connector_status"] not in CONNECTOR_STATUSES:
        add(
            issues,
            "error",
            "connector_status_invalid",
            document.path,
            "connector_status枚举无效。",
        )
    if data["freshness_status"] not in FRESHNESS_STATUSES:
        add(
            issues,
            "error",
            "freshness_status_invalid",
            document.path,
            "freshness_status枚举无效。",
        )
    if not context_id_valid(data["context_id"]):
        add(
            issues,
            "error",
            "context_id_invalid",
            document.path,
            "context_id格式应为dcx-YYYYMMDD-8chars。",
        )
    if not run_id_valid(data["latest_run_id"]):
        add(
            issues,
            "error",
            "latest_run_id_invalid",
            document.path,
            "latest_run_id格式应为dcr-YYYYMMDDTHHMMSS-4chars。",
        )
    if not safe_component(data["safe_name"]):
        add(
            issues,
            "error",
            "safe_name_invalid",
            document.path,
            "safe_name不是1—48字符的安全文件名组件。",
        )
    if not timestamp_valid(data["updated_at"]):
        add(
            issues,
            "error",
            "updated_at_invalid",
            document.path,
            "updated_at必须为ISO 8601时间。",
        )
    if not date_valid(data["evidence_cutoff_date"]):
        add(
            issues,
            "error",
            "evidence_cutoff_date_invalid",
            document.path,
            "evidence_cutoff_date必须为YYYY-MM-DD。",
        )
    if not IDENTIFIER_RE.fullmatch(data["customer_id"]):
        add(
            issues,
            "error",
            "customer_id_invalid",
            document.path,
            "customer_id格式无效。",
        )
    if not data["customer_display_name"].strip():
        add(
            issues,
            "error",
            "customer_display_name_missing",
            document.path,
            "customer_display_name不能为空。",
        )
    if not data["organization_scope"].strip():
        add(
            issues,
            "error",
            "organization_scope_missing",
            document.path,
            "organization_scope不能为空。",
        )
    if not CONTENT_VERSION_RE.fullmatch(data["content_version"]):
        add(
            issues,
            "error",
            "content_version_invalid",
            document.path,
            "content_version必须为正整数。",
        )
    if not data["runtime_owner"].strip():
        add(
            issues,
            "error",
            "runtime_owner_missing",
            document.path,
            "runtime_owner不能为空。",
        )
    elif (
        data["runtime_owner"] in {"待确认", "待指定"}
        and data["module_status"] in TERMINAL_STATUSES
    ):
        severity = "error" if strict else "warning"
        add(
            issues,
            severity,
            "runtime_owner_unassigned",
            document.path,
            "终态成果必须指定可追责的runtime_owner。",
        )
    if data["module_status"] == "not_called":
        add(
            issues,
            "error",
            "uncalled_artifact_exists",
            document.path,
            "not_called模块不得存在成果文件。",
        )
    if data["review_status"] == "approved" and data["module_status"] != "completed":
        add(
            issues,
            "error",
            "review_state_conflict",
            document.path,
            "approved仅能与completed组合。",
        )
    if (
        data["artifact_type"] in {"comprehensive_report", "institution_research"}
        and data["review_status"] != "not_required"
    ):
        add(
            issues,
            "error",
            "review_not_applicable",
            document.path,
            "综合报告和机构研究的review_status必须为not_required。",
        )
    if data["module_status"] in {"queued", "running"} and data["review_status"] in {
        "pending",
        "approved",
        "changes_requested",
    }:
        add(
            issues,
            "error",
            "review_state_conflict",
            document.path,
            "未完成执行的成果不能进入已提交或已处理审核状态。",
        )
    if (
        data["module_status"] == "completed"
        and data["artifact_type"]
        in {
            "leader_research",
            "internal_retrieval",
            "visit_strategy",
            "customer_letter_internal",
        }
        and data["review_status"] not in {"pending", "approved", "changes_requested"}
    ):
        add(
            issues,
            "error",
            "review_submission_missing",
            document.path,
            "该类completed成果必须进入pending/approved/changes_requested审核状态。",
        )
    if (
        data["artifact_type"] in {"visit_strategy", "customer_letter_internal"}
        and data["freshness_status"] in {"stale", "invalidated"}
        and data["review_status"] != "changes_requested"
    ):
        add(
            issues,
            "error",
            "output_review_freshness_conflict",
            document.path,
            "stale/invalidated策略或客户信必须标为changes_requested；pending/approved只允许freshness_status=current。",
        )
    if (
        data["artifact_type"] != "internal_retrieval"
        and data["connector_status"] != "not_applicable"
    ):
        add(
            issues,
            "error",
            "connector_not_applicable",
            document.path,
            "非内部检索成果的connector_status必须为not_applicable。",
        )
    if data["artifact_type"] == "comprehensive_report":
        if data.get("workflow_stage") not in WORKFLOW_STAGES:
            add(
                issues,
                "error",
                "workflow_stage_invalid",
                document.path,
                "综合报告必须提供有效workflow_stage。",
            )
        if data.get("route") not in ROUTES:
            add(issues, "error", "route_invalid", document.path, "综合报告route无效。")
        if data.get("depth") not in DEPTHS:
            add(issues, "error", "depth_invalid", document.path, "综合报告depth无效。")
    if data["artifact_type"] == "customer_letter_internal":
        if strict or data["module_status"] in TERMINAL_STATUSES:
            unresolved = sorted(
                key
                for key in LETTER_CONTEXT_FIELDS
                if not resolved_business_text(data.get(key, ""))
            )
            if unresolved:
                add(
                    issues,
                    "error",
                    "letter_context_unresolved",
                    document.path,
                    "客户信进入严格校验或终态前必须明确业务上下文："
                    + ", ".join(unresolved),
                )
            body_text = normalize_evidence_text(document.body)
            mismatched = sorted(
                key
                for key in LETTER_CONTEXT_FIELDS
                if resolved_business_text(data.get(key, ""))
                and normalize_evidence_text(data[key]) not in body_text
            )
            if mismatched:
                add(
                    issues,
                    "error",
                    "letter_context_body_mismatch",
                    document.path,
                    "客户信结构化业务上下文必须在内部审核摘要中保持一致："
                    + ", ".join(mismatched),
                )
        if data.get("external_output_required", "false") not in {"true", "false"}:
            add(
                issues,
                "error",
                "external_requirement_invalid",
                document.path,
                "external_output_required必须为true或false。",
            )
        approval_values = {key: data.get(key, "") for key in APPROVAL_FIELDS}
        if data["review_status"] == "approved":
            if not valid_actor(approval_values["approver"]):
                add(
                    issues,
                    "error",
                    "approver_missing",
                    document.path,
                    "approved内部稿必须记录非占位、非匿名、非泛化角色的approver。",
                )
            if not timestamp_valid(approval_values["approved_at"]):
                add(
                    issues,
                    "error",
                    "approved_at_invalid",
                    document.path,
                    "approved_at必须为带时区ISO 8601时间。",
                )
            if approval_values["approved_content_version"] != data["content_version"]:
                add(
                    issues,
                    "error",
                    "approval_version_drift",
                    document.path,
                    "approved_content_version必须等于当前content_version。",
                )
            approved_body = extract_external_body(document)
            expected_digest = (
                body_sha256(approved_body) if approved_body is not None else ""
            )
            if not re.fullmatch(
                r"[0-9a-f]{64}", approval_values["approved_body_sha256"]
            ):
                add(
                    issues,
                    "error",
                    "approval_hash_invalid",
                    document.path,
                    "approved_body_sha256必须为64位小写SHA-256。",
                )
            elif approval_values["approved_body_sha256"] != expected_digest:
                add(
                    issues,
                    "error",
                    "approval_body_drift",
                    document.path,
                    "已批准正文与审批哈希不一致，必须重新审核。",
                )
            if not re.fullmatch(
                r"[0-9a-f]{64}", approval_values["approved_context_sha256"]
            ):
                add(
                    issues,
                    "error",
                    "approval_context_hash_invalid",
                    document.path,
                    "approved_context_sha256必须为64位小写SHA-256。",
                )
            elif approval_values["approved_context_sha256"] != letter_context_sha256(
                data
            ):
                add(
                    issues,
                    "error",
                    "approval_context_drift",
                    document.path,
                    "已批准业务上下文与审批哈希不一致，必须重新审核。",
                )
        elif any(approval_values.values()):
            add(
                issues,
                "error",
                "stale_approval_metadata",
                document.path,
                "非approved内部稿不得保留审批戳；修改后应清空并重新审核。",
            )
    if data["artifact_type"] in GENERIC_REVIEW_TYPES:
        review_values = {key: data.get(key, "") for key in GENERIC_REVIEW_FIELDS}
        if data["review_status"] == "approved":
            missing_review = sorted(
                key for key, value in review_values.items() if not value.strip()
            )
            if missing_review:
                add(
                    issues,
                    "error",
                    "review_audit_required",
                    document.path,
                    "approved成果缺少可验证审核记录：" + ", ".join(missing_review),
                )
            if not valid_actor(review_values["reviewer"]):
                add(
                    issues,
                    "error",
                    "reviewer_unassigned",
                    document.path,
                    "approved成果必须记录实名审核人或稳定审核角色。",
                )
            if not timestamp_valid(review_values["reviewed_at"]):
                add(
                    issues,
                    "error",
                    "reviewed_at_invalid",
                    document.path,
                    "reviewed_at必须为带时区ISO 8601时间。",
                )
            if review_values["reviewed_content_version"] != data["content_version"]:
                add(
                    issues,
                    "error",
                    "review_version_drift",
                    document.path,
                    "reviewed_content_version必须等于当前content_version。",
                )
            digest = body_sha256(document.body)
            if review_values["reviewed_body_sha256"] != digest:
                add(
                    issues,
                    "error",
                    "review_body_drift",
                    document.path,
                    "审核后正文已变化，必须清空审核戳并重新审核。",
                )
        elif any(review_values.values()):
            add(
                issues,
                "error",
                "stale_review_metadata",
                document.path,
                "非approved成果不得保留通用审核戳。",
            )
    if data["artifact_type"] == "visit_strategy" and (
        strict or data["module_status"] in TERMINAL_STATUSES
    ):
        unresolved = sorted(
            key
            for key in STRATEGY_CONTEXT_FIELDS
            if not resolved_strategy_context(key, data.get(key, ""))
        )
        if unresolved:
            add(
                issues,
                "error",
                "strategy_context_unresolved",
                document.path,
                "交流策略进入严格校验或终态前必须明确对象/目标/最小推进动作："
                + ", ".join(unresolved),
            )
        body_text = normalize_evidence_text(document.body)
        mismatched = sorted(
            key
            for key in STRATEGY_CONTEXT_FIELDS
            if resolved_strategy_context(key, data.get(key, ""))
            and normalize_evidence_text(data[key]) not in body_text
        )
        if mismatched:
            add(
                issues,
                "error",
                "strategy_context_body_mismatch",
                document.path,
                "交流策略结构化上下文必须与正文一致：" + ", ".join(mismatched),
            )
    if data["artifact_type"] == "customer_letter_external":
        if data["review_status"] == "approved" and not valid_actor(
            data.get("approver", "")
        ):
            add(
                issues,
                "error",
                "approver_missing",
                document.path,
                "approved外发版必须记录有效approver标识。",
            )
        if data["module_status"] != "completed" or data["review_status"] != "approved":
            add(
                issues,
                "error",
                "external_letter_unapproved",
                document.path,
                "外发版必须为completed/approved。",
            )
        if data["content_version"] != "1":
            add(
                issues,
                "error",
                "external_content_version_invalid",
                document.path,
                "派生外发版content_version固定为1；新版本须归档旧文件后重新生成。",
            )
        if data["connector_status"] != "not_applicable":
            add(
                issues,
                "error",
                "external_connector_invalid",
                document.path,
                "外发版connector_status须为not_applicable。",
            )
        if data["freshness_status"] != "current":
            add(
                issues,
                "error",
                "external_stale",
                document.path,
                "外发版freshness_status必须为current。",
            )
    for legacy in ("version", "owner"):
        if legacy in data:
            add(
                issues,
                "error",
                "legacy_metadata",
                document.path,
                f"禁用旧字段{legacy}。",
            )
    placeholders = sorted(set(PLACEHOLDER_RE.findall(document.text)))
    if placeholders:
        severity = (
            "error"
            if strict or data["module_status"] in TERMINAL_STATUSES
            else "warning"
        )
        add(
            issues,
            severity,
            "placeholder_remaining",
            document.path,
            "仍有占位符：" + ", ".join(placeholders[:5]),
        )


def split_table_cells(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", raw)]


def letter_review_history_rows(
    letter: Document, issues: list[Issue]
) -> list[list[str]]:
    lines = letter.body.splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if line.strip() == LETTER_REVIEW_HEADING
    ]
    if len(headings) != 1:
        add(
            issues,
            "error",
            "letter_review_history_section_invalid",
            letter.path,
            "内部稿必须恰有一个版本与审核记录章节。",
        )
        return []
    expected_header = [
        "updated_at",
        "content_version",
        "latest_run_id",
        "变更摘要",
        "runtime_owner",
        "review_status",
    ]
    rows: list[list[str]] = []
    for line in lines[headings[0] + 1 :]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if cells == expected_header or all(
            re.fullmatch(r":?-{3,}:?", cell) for cell in cells
        ):
            continue
        if len(cells) != 6:
            add(
                issues,
                "error",
                "letter_review_history_row_shape",
                letter.path,
                "版本与审核记录必须恰有6列。",
            )
            continue
        rows.append(cells)
    if not rows:
        add(
            issues,
            "error",
            "letter_review_history_empty",
            letter.path,
            "内部稿至少需要一条版本与审核记录。",
        )
    return rows


def validate_letter_review_history(
    by_type: dict[str, Document], issues: list[Issue], strict: bool
) -> None:
    letter = by_type.get("customer_letter_internal")
    if letter is None:
        return
    rows = letter_review_history_rows(letter, issues)
    if not rows:
        return
    seen_runs: set[str] = set()
    previous_version: int | None = None
    previous_time: datetime | None = None
    for updated_at, version, run_id, summary, owner, review_status in rows:
        if not timestamp_valid(updated_at):
            add(
                issues,
                "error",
                "letter_review_history_time_invalid",
                letter.path,
                f"审核记录{run_id}的updated_at无效。",
            )
            parsed_time = None
        else:
            parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if not CONTENT_VERSION_RE.fullmatch(version):
            add(
                issues,
                "error",
                "letter_review_history_version_invalid",
                letter.path,
                f"审核记录{run_id}的content_version无效。",
            )
            numeric_version = None
        else:
            numeric_version = int(version)
        if not run_id_valid(run_id) or run_id in seen_runs:
            add(
                issues,
                "error",
                "letter_review_history_run_invalid",
                letter.path,
                f"审核记录run_id无效或重复：{run_id!r}。",
            )
        seen_runs.add(run_id)
        if not summary.strip() or not owner.strip():
            add(
                issues,
                "error",
                "letter_review_history_content_missing",
                letter.path,
                f"审核记录{run_id}的摘要与runtime_owner不能为空。",
            )
        if review_status not in REVIEW_STATUSES:
            add(
                issues,
                "error",
                "letter_review_history_status_invalid",
                letter.path,
                f"审核记录{run_id}的review_status无效。",
            )
        if (
            previous_version is not None
            and numeric_version is not None
            and numeric_version != previous_version + 1
        ):
            add(
                issues,
                "error",
                "letter_review_history_version_sequence",
                letter.path,
                f"审核记录{run_id}的版本必须紧接前一版本。",
            )
        if (
            previous_time is not None
            and parsed_time is not None
            and parsed_time < previous_time
        ):
            add(
                issues,
                "error",
                "letter_review_history_time_sequence",
                letter.path,
                f"审核记录{run_id}早于前一条记录。",
            )
        if numeric_version is not None:
            previous_version = numeric_version
        if parsed_time is not None:
            previous_time = parsed_time
    if strict or letter.frontmatter.get("module_status") in TERMINAL_STATUSES:
        latest = rows[-1]
        expected = [
            letter.frontmatter.get("updated_at", ""),
            letter.frontmatter.get("content_version", ""),
            letter.frontmatter.get("latest_run_id", ""),
            letter.frontmatter.get("runtime_owner", ""),
            letter.frontmatter.get("review_status", ""),
        ]
        actual = [latest[0], latest[1], latest[2], latest[4], latest[5]]
        if actual != expected:
            add(
                issues,
                "error",
                "letter_review_history_latest_mismatch",
                letter.path,
                "最新版本与审核记录必须与内部稿frontmatter的时间、版本、run、owner和审核状态一致。",
            )


def collect_ledgers(
    documents: list[Document], issues: list[Issue]
) -> tuple[dict[str, ClaimDefinition], dict[str, SourceDefinition]]:
    claims: dict[str, ClaimDefinition] = {}
    sources: dict[str, SourceDefinition] = {}
    for document in documents:
        for line in document.body.splitlines():
            if "{{" in line or not line.lstrip().startswith("|"):
                continue
            cells = split_table_cells(line)
            if cells and CLAIM_RE.fullmatch(cells[0]):
                claim_id = cells[0]
                expected_type = {
                    "I": "institution_research",
                    "L": "leader_research",
                    "N": "internal_retrieval",
                }[claim_id.split("-")[1]]
                if document.frontmatter.get("artifact_type") != expected_type:
                    add(
                        issues,
                        "error",
                        "claim_ledger_artifact_mismatch",
                        document.path,
                        f"{claim_id}只能在{expected_type}中定义。",
                    )
                if claim_id in claims:
                    add(
                        issues,
                        "error",
                        "claim_duplicate",
                        document.path,
                        f"claim_id重复定义：{claim_id}",
                    )
                else:
                    claims[claim_id] = ClaimDefinition(claim_id, document, cells, line)
            if cells and SOURCE_RE.fullmatch(cells[0]):
                source_id = cells[0]
                expected_type = {
                    "I": "institution_research",
                    "L": "leader_research",
                    "N": "internal_retrieval",
                }[source_id.split("-")[1]]
                if document.frontmatter.get("artifact_type") != expected_type:
                    add(
                        issues,
                        "error",
                        "source_ledger_artifact_mismatch",
                        document.path,
                        f"{source_id}只能在{expected_type}中定义。",
                    )
                if source_id in sources:
                    add(
                        issues,
                        "error",
                        "source_duplicate",
                        document.path,
                        f"source_id重复定义：{source_id}",
                    )
                else:
                    sources[source_id] = SourceDefinition(
                        source_id, document, cells, line
                    )
    return claims, sources


def body_without_placeholders(document: Document) -> str:
    return PLACEHOLDER_RE.sub("", document.body)


def normalize_evidence_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def normalize_locator(value: str) -> str:
    normalized = normalize_evidence_text(value)
    try:
        parsed = urlsplit(normalized)
        if not parsed.scheme or not parsed.netloc:
            return normalized
        host = (parsed.hostname or "").casefold()
        port = f":{parsed.port}" if parsed.port else ""
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        return urlunsplit(
            (parsed.scheme.casefold(), host + port, path, parsed.query, "")
        )
    except ValueError:
        return normalized


def unresolved_evidence_value(value: str) -> bool:
    normalized = normalize_evidence_text(value)
    return normalized in {
        "",
        "无",
        "未知",
        "unknown",
        "待确认",
        "待补充",
        "n/a",
        "na",
        "none",
    }


def source_fingerprint_valid(value: str) -> bool:
    fingerprint = value.strip()
    if (
        unresolved_evidence_value(fingerprint)
        or normalize_evidence_text(fingerprint).startswith("unknown:")
        or any(char.isspace() for char in fingerprint)
    ):
        return False
    if fingerprint.casefold().startswith("sha256:"):
        return bool(SHA256_FINGERPRINT_RE.fullmatch(fingerprint))
    return bool(
        SHA256_FINGERPRINT_RE.fullmatch(fingerprint)
        or PROVIDER_FINGERPRINT_RE.fullmatch(fingerprint)
    )


def supporting_sources(
    definition: ClaimDefinition,
    sources: dict[str, SourceDefinition],
) -> list[SourceDefinition]:
    if len(definition.cells) < 7:
        return []
    return [
        sources[source_id]
        for source_id in SOURCE_RE.findall(definition.cells[6])
        if source_id in sources
    ]


def f2_independence_values(
    source: SourceDefinition,
) -> tuple[str, str, str, str] | None:
    if len(source.cells) != 14:
        return None
    group = normalize_evidence_text(source.cells[7])
    locator = normalize_locator(source.cells[3])
    fingerprint = normalize_evidence_text(source.cells[11])
    upstream_id = normalize_evidence_text(source.cells[12])
    if (
        unresolved_evidence_value(group)
        or group.startswith("unknown:")
        or unresolved_evidence_value(locator)
        or locator.startswith("unknown:")
        or not source_fingerprint_valid(source.cells[11])
        or unresolved_evidence_value(upstream_id)
        or upstream_id.startswith("unknown:")
    ):
        return None
    return group, locator, fingerprint, upstream_id


def validate_claim_graph(
    documents: list[Document],
    claims: dict[str, ClaimDefinition],
    sources: dict[str, SourceDefinition],
    issues: list[Issue],
) -> None:
    claim_refs: dict[str, set[Path]] = {}
    source_refs: dict[str, set[Path]] = {}
    for document in documents:
        cleaned = body_without_placeholders(document)
        legacy = sorted(set(LEGACY_EVIDENCE_RE.findall(cleaned)))
        if legacy:
            add(
                issues,
                "error",
                "legacy_evidence_id",
                document.path,
                "禁用旧证据ID：" + ", ".join(legacy),
            )
        for claim_id in CLAIM_RE.findall(cleaned):
            claim_refs.setdefault(claim_id, set()).add(document.path)
        for source_id in SOURCE_RE.findall(cleaned):
            source_refs.setdefault(source_id, set()).add(document.path)

    for claim_id, paths in sorted(claim_refs.items()):
        if claim_id not in claims:
            for path in paths:
                add(
                    issues,
                    "error",
                    "claim_orphan_reference",
                    path,
                    f"引用了未定义claim_id：{claim_id}",
                )
    for source_id, paths in sorted(source_refs.items()):
        if source_id not in sources:
            for path in paths:
                add(
                    issues,
                    "error",
                    "source_orphan_reference",
                    path,
                    f"引用了未定义source_id：{source_id}",
                )

    for claim_id, definition in claims.items():
        cells = definition.cells
        if len(cells) != 10:
            add(
                issues,
                "error",
                "claim_row_shape",
                definition.document.path,
                f"{claim_id}主张台账必须恰有10列；正文竖线须写为\\|。",
            )
            continue
        claim_type, provenance, verification = cells[1], cells[2], cells[3]
        if claim_type not in CLAIM_TYPES:
            add(
                issues,
                "error",
                "claim_type_invalid",
                definition.document.path,
                f"{claim_id} claim_type无效：{claim_type}",
            )
        if provenance not in PROVENANCE_VALUES:
            add(
                issues,
                "error",
                "provenance_invalid",
                definition.document.path,
                f"{claim_id} provenance无效：{provenance}",
            )
        if verification not in VERIFICATION_STATUSES:
            add(
                issues,
                "error",
                "verification_invalid",
                definition.document.path,
                f"{claim_id} verification_status无效：{verification}",
            )
        if claim_type == "F" and verification != "verified_single":
            add(
                issues,
                "error",
                "fact_mapping_invalid",
                definition.document.path,
                f"{claim_id}: F必须对应verified_single。",
            )
        if claim_type == "F2" and verification != "corroborated":
            add(
                issues,
                "error",
                "fact2_mapping_invalid",
                definition.document.path,
                f"{claim_id}: F2必须对应corroborated。",
            )
        if unresolved_evidence_value(cells[4]):
            add(
                issues,
                "error",
                "claim_text_missing",
                definition.document.path,
                f"{claim_id}主张内容不能为空或待确认。",
            )
        if unresolved_evidence_value(cells[5]):
            add(
                issues,
                "error",
                "claim_time_scope_missing",
                definition.document.path,
                f"{claim_id}必须记录时间/口径。",
            )
        if cells[8] not in {"高", "中", "低", "不可用"}:
            add(
                issues,
                "error",
                "claim_confidence_invalid",
                definition.document.path,
                f"{claim_id}置信度必须为高/中/低/不可用。",
            )
        if (
            verification in {"conflicted", "stale", "invalidated", "unusable"}
            and cells[8] == "高"
        ):
            add(
                issues,
                "error",
                "claim_confidence_conflict",
                definition.document.path,
                f"{claim_id}处于{verification}时不得标高置信度。",
            )
        support_ids = SOURCE_RE.findall(cells[6])
        if not support_ids:
            add(
                issues,
                "error",
                "claim_source_missing",
                definition.document.path,
                f"{claim_id}没有支持source_id。",
            )
        for source_id in support_ids + SOURCE_RE.findall(cells[7]):
            if source_id not in sources:
                add(
                    issues,
                    "error",
                    "claim_source_orphan",
                    definition.document.path,
                    f"{claim_id}引用未定义来源{source_id}。",
                )
        expected_prefix = claim_id.split("-")[1]
        for source_id in support_ids:
            if source_id.split("-")[1] != expected_prefix:
                add(
                    issues,
                    "warning",
                    "claim_source_prefix_mismatch",
                    definition.document.path,
                    f"{claim_id}的支持来源{source_id}跨台账前缀。",
                )
        if verification == "conflicted" and not SOURCE_RE.findall(cells[7]):
            add(
                issues,
                "error",
                "conflicted_counter_source_missing",
                definition.document.path,
                f"{claim_id}标conflicted时必须记录反证source_id。",
            )
        if claim_type != "H":
            for source in supporting_sources(definition, sources):
                if len(source.cells) >= 7 and source.cells[6] == "C":
                    code = (
                        "fact_source_level_unsafe"
                        if claim_type in {"F", "F2"}
                        else "c_source_claim_type_unsafe"
                    )
                    add(
                        issues,
                        "error",
                        code,
                        definition.document.path,
                        f"{claim_id}不能由C级线索支撑{claim_type}主张；C级来源只允许支撑H：{source.source_id}。",
                    )
        if claim_type == "F2":
            unique_support = list(dict.fromkeys(support_ids))
            if len(unique_support) < 2:
                add(
                    issues,
                    "error",
                    "fact2_sources_insufficient",
                    definition.document.path,
                    f"{claim_id}: F2至少需要两个支持来源。",
                )
            groups = {
                normalize_evidence_text(sources[source_id].cells[7])
                for source_id in unique_support
                if source_id in sources
                and len(sources[source_id].cells) >= 8
                and not unresolved_evidence_value(sources[source_id].cells[7])
                and not normalize_evidence_text(sources[source_id].cells[7]).startswith(
                    "unknown:"
                )
            }
            if len(groups) < 2:
                add(
                    issues,
                    "error",
                    "fact2_source_groups_not_independent",
                    definition.document.path,
                    f"{claim_id}: F2至少需要两个不同source_group。",
                )
            source_defs = [
                sources[source_id]
                for source_id in unique_support
                if source_id in sources
            ]
            locators = {
                normalize_locator(source.cells[3])
                for source in source_defs
                if len(source.cells) >= 4
                and not unresolved_evidence_value(source.cells[3])
                and not normalize_evidence_text(source.cells[3]).startswith("unknown:")
            }
            fingerprints = {
                normalize_evidence_text(source.cells[11])
                for source in source_defs
                if len(source.cells) >= 13
                and source_fingerprint_valid(source.cells[11])
            }
            upstream_ids = {
                normalize_evidence_text(source.cells[12])
                for source in source_defs
                if len(source.cells) >= 13
                and not unresolved_evidence_value(source.cells[12])
                and not normalize_evidence_text(source.cells[12]).startswith("unknown:")
            }
            if len(locators) < 2:
                add(
                    issues,
                    "error",
                    "fact2_locator_not_independent",
                    definition.document.path,
                    f"{claim_id}: F2支持来源的稳定定位必须不同。",
                )
            if len(fingerprints) < 2:
                add(
                    issues,
                    "error",
                    "fact2_source_fingerprint_not_independent",
                    definition.document.path,
                    f"{claim_id}: F2至少需要两个不同且格式有效的source_fingerprint。",
                )
            if len(upstream_ids) < 2:
                add(
                    issues,
                    "error",
                    "fact2_upstream_not_independent",
                    definition.document.path,
                    f"{claim_id}: F2至少需要两个不同且已确认的upstream_id。",
                )
            independence_values = [
                values
                for source in source_defs
                if (values := f2_independence_values(source)) is not None
            ]
            has_fourfold_independent_pair = any(
                all(left[index] != right[index] for index in range(4))
                for left_index, left in enumerate(independence_values)
                for right in independence_values[left_index + 1 :]
            )
            if not has_fourfold_independent_pair:
                add(
                    issues,
                    "error",
                    "fact2_sources_not_fourfold_independent",
                    definition.document.path,
                    f"{claim_id}: F2必须存在同一对来源，其source_group、稳定定位、source_fingerprint、upstream_id四项同时有效且互不相同。",
                )

    for source_id, definition in sources.items():
        if len(definition.cells) != 14:
            add(
                issues,
                "error",
                "source_row_shape",
                definition.document.path,
                f"{source_id}来源台账必须恰有14列；正文竖线须写为\\|。",
            )
        else:
            locator = definition.cells[3]
            level = definition.cells[6]
            source_group = definition.cells[7]
            permission = definition.cells[8]
            fingerprint = definition.cells[11]
            upstream_id = definition.cells[12]
            external_use = definition.cells[13]
            if unresolved_evidence_value(definition.cells[1]):
                add(
                    issues,
                    "error",
                    "source_title_missing",
                    definition.document.path,
                    f"{source_id}标题/文档名不能为空或待确认。",
                )
            if unresolved_evidence_value(definition.cells[2]):
                add(
                    issues,
                    "error",
                    "source_publisher_missing",
                    definition.document.path,
                    f"{source_id}发布者/提供者不能为空或待确认。",
                )
            if not definition.cells[4].strip():
                add(
                    issues,
                    "error",
                    "source_publish_date_missing",
                    definition.document.path,
                    f"{source_id}必须记录发布/更新日期或明确写未标注。",
                )
            if not date_valid(definition.cells[5]):
                add(
                    issues,
                    "error",
                    "source_access_date_invalid",
                    definition.document.path,
                    f"{source_id}访问日期必须为YYYY-MM-DD。",
                )
            if unresolved_evidence_value(definition.cells[9]):
                add(
                    issues,
                    "error",
                    "source_scope_missing",
                    definition.document.path,
                    f"{source_id}适用客户/项目不能为空或待确认。",
                )
            if unresolved_evidence_value(locator) or normalize_evidence_text(
                locator
            ).startswith("unknown:"):
                add(
                    issues,
                    "error",
                    "source_locator_missing",
                    definition.document.path,
                    f"{source_id}必须记录非空稳定定位。",
                )
            if unresolved_evidence_value(source_group) or normalize_evidence_text(
                source_group
            ).startswith("unknown:"):
                add(
                    issues,
                    "error",
                    "source_group_missing",
                    definition.document.path,
                    f"{source_id}必须记录非空source_group。",
                )
            if level not in SOURCE_LEVELS:
                add(
                    issues,
                    "error",
                    "source_level_invalid",
                    definition.document.path,
                    f"{source_id}来源等级无效：{level!r}。",
                )
            if permission not in SOURCE_PERMISSIONS:
                add(
                    issues,
                    "error",
                    "source_permission_invalid",
                    definition.document.path,
                    f"{source_id}权限无效：{permission!r}。",
                )
            if external_use not in SOURCE_EXTERNAL_USE_VALUES:
                add(
                    issues,
                    "error",
                    "source_external_use_invalid",
                    definition.document.path,
                    f"{source_id}的external_use必须为true或false。",
                )
            if permission == "restricted" and external_use == "true":
                add(
                    issues,
                    "error",
                    "restricted_external_use_conflict",
                    definition.document.path,
                    f"{source_id}为restricted时external_use必须为false。",
                )
            if not source_fingerprint_valid(fingerprint):
                add(
                    issues,
                    "error",
                    "source_fingerprint_invalid",
                    definition.document.path,
                    f"{source_id}的source_fingerprint必须为SHA-256或scheme:stable-id格式。",
                )
            if unresolved_evidence_value(upstream_id):
                add(
                    issues,
                    "error",
                    "source_upstream_missing",
                    definition.document.path,
                    f"{source_id}必须记录upstream_id；无法识别时用unknown:{source_id}且不得参与F2。",
                )
            elif (
                normalize_evidence_text(upstream_id).startswith("unknown:")
                and normalize_evidence_text(upstream_id)
                != f"unknown:{source_id.casefold()}"
            ):
                add(
                    issues,
                    "error",
                    "source_upstream_unknown_invalid",
                    definition.document.path,
                    f"{source_id}无法识别上游时必须精确写unknown:{source_id}。",
                )
        used = any(
            source_id in SOURCE_RE.findall(claim.cells[6] + " " + claim.cells[7])
            for claim in claims.values()
            if len(claim.cells) >= 8
        )
        if not used:
            add(
                issues,
                "warning",
                "source_unreferenced",
                definition.document.path,
                f"{source_id}未被任何主张引用。",
            )

    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if document.frontmatter.get("module_status") != "completed":
            continue
        prefix = RESEARCH_PREFIX.get(artifact_type)
        if prefix:
            own_claims = [
                key
                for key, value in claims.items()
                if value.document.path == document.path
                and key.startswith(f"CLM-{prefix}-")
            ]
            own_sources = [
                key
                for key, value in sources.items()
                if value.document.path == document.path
                and key.startswith(f"SRC-{prefix}-")
            ]
            if not own_claims:
                add(
                    issues,
                    "error",
                    "completed_claim_ledger_missing",
                    document.path,
                    "completed研究成果必须有非空主张台账。",
                )
            if not own_sources:
                add(
                    issues,
                    "error",
                    "completed_source_ledger_missing",
                    document.path,
                    "completed研究成果必须有非空来源台账。",
                )
            non_registry_lines = [
                line
                for line in body_without_placeholders(document).splitlines()
                if not (
                    line.lstrip().startswith("|")
                    and split_table_cells(line)
                    and (
                        CLAIM_RE.fullmatch(split_table_cells(line)[0])
                        or SOURCE_RE.fullmatch(split_table_cells(line)[0])
                    )
                )
            ]
            if not CLAIM_RE.search("\n".join(non_registry_lines)):
                add(
                    issues,
                    "error",
                    "body_claim_reference_missing",
                    document.path,
                    "completed研究正文必须引用claim_id。",
                )
        elif artifact_type in {
            "comprehensive_report",
            "visit_strategy",
            "customer_letter_internal",
        } and not CLAIM_RE.search(body_without_placeholders(document)):
            allow_gap_only_total = False
            if artifact_type == "comprehensive_report" and document.frontmatter.get(
                "route"
            ) in {"research_only", "refresh"}:
                rows = parse_status_rows(document)
                selected_research = [
                    row
                    for kind, row in rows.items()
                    if kind in RESEARCH_PREFIX and len(row) >= 4 and row[1] == "true"
                ]
                allow_gap_only_total = bool(selected_research) and all(
                    row[3] in {"partial", "blocked"} for row in selected_research
                )
            if not allow_gap_only_total:
                add(
                    issues,
                    "error",
                    "body_claim_reference_missing",
                    document.path,
                    "completed成果正文必须引用至少一个已定义claim_id；仅全为partial/blocked的研究型总报告可只交付缺口。",
                )

    for document in documents:
        if (
            document.frontmatter.get("module_status") != "completed"
            or document.frontmatter.get("freshness_status") != "current"
        ):
            continue
        if document.frontmatter.get("artifact_type") not in {
            "comprehensive_report",
            "visit_strategy",
            "customer_letter_internal",
        }:
            continue
        cutoff = document.frontmatter.get("evidence_cutoff_date", "")
        for claim_id in set(CLAIM_RE.findall(body_without_placeholders(document))):
            definition = claims.get(claim_id)
            if not definition:
                continue
            dependency = definition.document
            if dependency.frontmatter.get("freshness_status") != "current":
                add(
                    issues,
                    "error",
                    "current_output_uses_stale_claim",
                    document.path,
                    f"current成果引用了非current主张：{claim_id}",
                )
            dependency_cutoff = dependency.frontmatter.get("evidence_cutoff_date", "")
            if (
                date_valid(cutoff)
                and date_valid(dependency_cutoff)
                and cutoff > dependency_cutoff
            ):
                add(
                    issues,
                    "error",
                    "evidence_cutoff_exceeds_dependency",
                    document.path,
                    f"信息截止{cutoff}晚于{claim_id}所属研究成果截止{dependency_cutoff}。",
                )

    total = next(
        (
            document
            for document in documents
            if document.frontmatter.get("artifact_type") == "comprehensive_report"
        ),
        None,
    )
    status_rows = parse_status_rows(total) if total else {}
    for definition in claims.values():
        if (
            definition.document.frontmatter.get("artifact_type") == "leader_research"
            and definition.document.frontmatter.get("module_status") == "completed"
            and len(definition.cells) >= 4
            and definition.cells[3] == "conflicted"
        ):
            add(
                issues,
                "error",
                "leader_completed_conflict",
                definition.document.path,
                "人物/角色研究仍有未解冲突，不能标completed或批准；应先消解冲突或交付partial/blocked底稿。",
            )
    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if artifact_type not in {"visit_strategy", "customer_letter_internal"}:
            continue
        if (
            document.frontmatter.get("module_status") != "completed"
            or document.frontmatter.get("freshness_status") != "current"
        ):
            continue
        claim_ids = set(CLAIM_RE.findall(body_without_placeholders(document)))
        verified_anchor = False
        output_selected = bool(
            artifact_type in status_rows
            and len(status_rows[artifact_type]) >= 2
            and status_rows[artifact_type][1] == "true"
        )
        for claim_id in claim_ids:
            definition = claims.get(claim_id)
            if definition is None:
                continue
            dependency = definition.document
            dependency_type = dependency.frontmatter.get("artifact_type", "")
            if dependency.frontmatter.get("module_status") != "completed":
                add(
                    issues,
                    "error",
                    "output_uses_incomplete_research",
                    document.path,
                    f"{artifact_type}引用了非completed研究载体：{claim_id}。",
                )
            if dependency.frontmatter.get("freshness_status") != "current":
                add(
                    issues,
                    "error",
                    "output_uses_stale_research",
                    document.path,
                    f"{artifact_type}引用了非current研究载体：{claim_id}。",
                )
            if output_selected:
                dependency_row = status_rows.get(dependency_type, [])
                if (
                    len(dependency_row) < 3
                    or dependency_row[1] != "true"
                    or dependency_row[2] == "not_called"
                ):
                    add(
                        issues,
                        "error",
                        "output_carrier_unselected",
                        document.path,
                        f"本轮输出引用的研究载体未登记为selected：{claim_id}。",
                    )
            claim_type = definition.cells[1] if len(definition.cells) >= 2 else ""
            verification = definition.cells[3] if len(definition.cells) >= 4 else ""
            supports = supporting_sources(definition, sources)
            if verification in UNSAFE_DOWNSTREAM_VERIFICATIONS:
                add(
                    issues,
                    "error",
                    "output_uses_unsafe_claim",
                    document.path,
                    f"{artifact_type}引用了{verification}主张：{claim_id}。",
                )
            fact_anchor = (
                claim_type in {"F", "F2"}
                and verification in SAFE_FACT_VERIFICATIONS
                and bool(supports)
                and all(
                    len(source.cells) >= 7 and source.cells[6] != "C"
                    for source in supports
                )
            )
            verified_anchor = verified_anchor or fact_anchor
            if artifact_type == "customer_letter_internal":
                if (
                    dependency_type in {"leader_research", "internal_retrieval"}
                    and dependency.frontmatter.get("review_status") != "approved"
                ):
                    add(
                        issues,
                        "error",
                        "letter_carrier_review_missing",
                        document.path,
                        f"客户信引用的人物/内部研究必须先审核为approved：{claim_id}。",
                    )
                if not fact_anchor:
                    add(
                        issues,
                        "error",
                        "letter_claim_not_externally_verified",
                        document.path,
                        f"客户信依据必须是由非C级来源支撑的F/F2已核实事实：{claim_id}。",
                    )
                for source in supports:
                    if len(source.cells) >= 9 and source.cells[8] == "restricted":
                        add(
                            issues,
                            "error",
                            "letter_source_restricted",
                            document.path,
                            f"客户信不得依赖restricted来源：{source.source_id}。",
                        )
                    if len(source.cells) < 14 or source.cells[13] != "true":
                        add(
                            issues,
                            "error",
                            "letter_source_not_external_authorized",
                            document.path,
                            f"客户信依据必须显式记录external_use=true：{source.source_id}。",
                        )
        if not verified_anchor:
            add(
                issues,
                "error",
                "output_verified_anchor_missing",
                document.path,
                f"completed/current的{artifact_type}至少需要一个可核验的F/F2事实锚点。",
            )


def validate_filenames_and_identity(
    documents: list[Document], root: Path, issues: list[Issue]
) -> dict[str, Document]:
    by_type: dict[str, Document] = {}
    totals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "comprehensive_report"
    ]
    if len(totals) != 1:
        add(
            issues,
            "error",
            "comprehensive_count",
            root,
            f"综合报告必须且只能有1个，当前{len(totals)}个。",
        )
    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if artifact_type not in ARTIFACT_TYPES:
            continue
        if artifact_type in by_type:
            add(
                issues,
                "error",
                "artifact_duplicate",
                document.path,
                f"artifact_type重复：{artifact_type}",
            )
        else:
            by_type[artifact_type] = document
        safe_name = document.frontmatter.get("safe_name", "")
        expected = f"{safe_name}{SUFFIXES[artifact_type]}"
        if document.path.name != expected:
            add(
                issues,
                "error",
                "filename_invalid",
                document.path,
                f"文件名应为：{expected}",
            )
    if totals:
        total = totals[0]
        for document in documents:
            for field in (
                "context_id",
                "customer_id",
                "customer_display_name",
                "organization_scope",
                "safe_name",
            ):
                if document.frontmatter.get(field) != total.frontmatter.get(field):
                    add(
                        issues,
                        "error",
                        "identity_mismatch",
                        document.path,
                        f"{field}与综合报告不一致。",
                    )
        safe_name = total.frontmatter.get("safe_name", "")
        context_id = total.frontmatter.get("context_id", "")
        if safe_name and context_id and CONTEXT_RE.fullmatch(context_id):
            expected_dir = f"客户研究-{safe_name}-{context_id.rsplit('-', 1)[1]}"
            if root.name != expected_dir:
                add(
                    issues,
                    "error",
                    "workspace_name_invalid",
                    root,
                    f"工作目录名应为：{expected_dir}",
                )
    return by_type


def parse_status_rows(total: Document) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    label_to_type = {
        label: artifact_type for artifact_type, label in STATUS_LABELS.items()
    }
    for line in total.body.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if cells and cells[0] in label_to_type:
            rows[label_to_type[cells[0]]] = cells
    return rows


def link_target(cell: str) -> str:
    match = LINK_RE.search(cell)
    return match.group(1).strip() if match else ""


def validate_status_sync(
    by_type: dict[str, Document], issues: list[Issue], strict: bool
) -> None:
    total = by_type.get("comprehensive_report")
    if not total:
        return
    rows = parse_status_rows(total)
    for artifact_type, label in STATUS_LABELS.items():
        occurrences = len(
            re.findall(
                rf"^\|\s*{re.escape(label)}\s*\|.*$", total.body, flags=re.MULTILINE
            )
        )
        if occurrences != 1:
            add(
                issues,
                "error",
                "status_row_count_invalid",
                total.path,
                f"{label}状态行必须恰有1条，当前{occurrences}条。",
            )
        row = rows.get(artifact_type)
        artifact = by_type.get(artifact_type)
        if not row or len(row) != 15:
            add(
                issues,
                "error",
                "status_row_missing",
                total.path,
                f"缺少或损坏状态行：{label}；必须恰有15列，竖线须写为\\|。",
            )
            continue
        selected = row[1]
        run_action = row[2]
        if selected not in {"true", "false"}:
            add(
                issues,
                "error",
                "selected_in_run_invalid",
                total.path,
                f"{label}.selected_in_run必须为true或false。",
            )
        if run_action not in RUN_ACTIONS:
            add(
                issues,
                "error",
                "run_action_invalid",
                total.path,
                f"{label}.run_action无效：{run_action!r}。",
            )
        if artifact_type == "customer_letter_external" and run_action not in {
            "generated",
            "not_called",
        }:
            add(
                issues,
                "error",
                "external_run_action_invalid",
                total.path,
                "客户信外发版run_action只允许generated或not_called。",
            )
        row_values = {
            "module_status": row[3],
            "review_status": row[4],
            "connector_status": row[5],
            "freshness_status": row[6],
            "content_version": row[7],
            "latest_run_id": row[8],
            "updated_at": row[9],
        }
        summary_sync_status = row[10]
        key_claim_ids = row[11]
        downstream_invalidation = row[12]
        gaps_blockers = row[13]
        target = link_target(row[14])
        if summary_sync_status not in SUMMARY_SYNC_STATUSES:
            add(
                issues,
                "error",
                "summary_sync_status_invalid",
                total.path,
                f"{label}.summary_sync_status无效。",
            )
        if downstream_invalidation not in DOWNSTREAM_INVALIDATIONS:
            add(
                issues,
                "error",
                "downstream_invalidation_invalid",
                total.path,
                f"{label}.downstream_invalidation无效。",
            )
        if not gaps_blockers.strip():
            add(
                issues,
                "error",
                "gaps_blockers_missing",
                total.path,
                f"{label}.gaps/blockers不能为空；无则写“无”。",
            )
        if artifact is None:
            if selected == "true":
                add(
                    issues,
                    "error",
                    "selected_artifact_missing",
                    total.path,
                    f"{label}本轮已选但成果文件不存在。",
                )
            if run_action != "not_called":
                add(
                    issues,
                    "error",
                    "run_action_missing_artifact",
                    total.path,
                    f"{label}无文件时run_action必须为not_called。",
                )
            if row_values["module_status"] != "not_called":
                add(
                    issues,
                    "error",
                    "status_missing_artifact",
                    total.path,
                    f"{label}无文件但状态不是not_called。",
                )
            expected_uncalled = {
                "review_status": "not_required",
                "connector_status": "not_applicable",
                "freshness_status": "current",
                "content_version": "",
                "latest_run_id": "",
                "updated_at": "",
            }
            for field, expected in expected_uncalled.items():
                if row_values[field] != expected:
                    add(
                        issues,
                        "error",
                        "status_uncalled_metadata",
                        total.path,
                        f"{label}未调用时{field}应为{expected!r}。",
                    )
            if target:
                add(
                    issues,
                    "error",
                    "status_phantom_link",
                    total.path,
                    f"{label}未调用却存在链接。",
                )
            if (
                summary_sync_status != "not_applicable"
                or key_claim_ids
                or downstream_invalidation != "none"
            ):
                add(
                    issues,
                    "error",
                    "status_uncalled_registry",
                    total.path,
                    f"{label}未调用时同步/主张/失效字段不符合空登记。",
                )
            continue
        if selected == "false" and run_action != "not_called":
            add(
                issues,
                "error",
                "run_action_unselected",
                total.path,
                f"{label}本轮未选时run_action必须为not_called。",
            )
        if selected == "true" and run_action == "not_called":
            add(
                issues,
                "error",
                "run_action_selected",
                total.path,
                f"{label}本轮已选时run_action不能为not_called。",
            )
        if row_values["module_status"] == "not_called":
            add(
                issues,
                "error",
                "status_uncalled_artifact",
                total.path,
                f"{label}存在历史或本轮成果文件，module_status不能为not_called。",
            )
        for field, row_value in row_values.items():
            artifact_value = artifact.frontmatter.get(field, "")
            if row_value != artifact_value:
                add(
                    issues,
                    "error",
                    "status_sync_mismatch",
                    total.path,
                    f"{label}.{field}={row_value!r}，成果为{artifact_value!r}。",
                )
        expected_target = "./" + artifact.path.name
        if unquote(target) != expected_target:
            add(
                issues,
                "error",
                "status_link_mismatch",
                total.path,
                f"{label}链接应为{expected_target}。",
            )
        if selected == "true" and run_action in {"created", "updated", "generated"}:
            if artifact.frontmatter.get("latest_run_id") != total.frontmatter.get(
                "latest_run_id"
            ):
                planned_update = (
                    run_action == "updated"
                    and not strict
                    and total.frontmatter.get("workflow_stage")
                    in {"planning", "research", "paused"}
                )
                if not planned_update:
                    add(
                        issues,
                        "error",
                        "run_id_current_action_mismatch",
                        total.path,
                        f"{label}本轮{run_action}但latest_run_id不是本轮run。",
                    )
                elif summary_sync_status != "pending":
                    add(
                        issues,
                        "error",
                        "planned_update_sync_invalid",
                        total.path,
                        f"{label}尚未由本轮更新时summary_sync_status必须为pending。",
                    )
        if (
            selected == "true"
            and run_action == "reused"
            and artifact.frontmatter.get("latest_run_id")
            == total.frontmatter.get("latest_run_id")
        ):
            add(
                issues,
                "error",
                "reused_artifact_modified_in_run",
                total.path,
                f"{label}标为reused却由本轮run更新。",
            )
        if selected == "false" and artifact.frontmatter.get(
            "latest_run_id"
        ) == total.frontmatter.get("latest_run_id"):
            add(
                issues,
                "error",
                "uncalled_artifact_modified_in_run",
                total.path,
                f"{label}标为本轮未调用，却由本轮run更新。",
            )
        if (
            summary_sync_status == "not_applicable"
            and artifact_type != "customer_letter_external"
        ):
            add(
                issues,
                "error",
                "summary_sync_not_applicable",
                total.path,
                f"{label}存在成果时summary_sync_status不能为not_applicable。",
            )
        if (
            artifact.frontmatter.get("module_status") == "completed"
            and artifact_type != "customer_letter_external"
        ):
            if not CLAIM_RE.search(key_claim_ids):
                add(
                    issues,
                    "error",
                    "key_claim_ids_missing",
                    total.path,
                    f"{label}completed时必须登记key_claim_ids。",
                )
        registered_claims = set(CLAIM_RE.findall(key_claim_ids))
        body_claims = set(CLAIM_RE.findall(body_without_placeholders(artifact)))
        if registered_claims - body_claims:
            add(
                issues,
                "error",
                "key_claim_ids_not_in_artifact",
                total.path,
                f"{label}.key_claim_ids包含成果正文未引用的主张：{sorted(registered_claims - body_claims)}。",
            )
        prefix = RESEARCH_PREFIX.get(artifact_type)
        if prefix and any(
            not claim_id.startswith(f"CLM-{prefix}-") for claim_id in registered_claims
        ):
            add(
                issues,
                "error",
                "key_claim_ids_wrong_carrier",
                total.path,
                f"{label}.key_claim_ids包含不属于本研究台账的主张。",
            )


RUN_SUMMARY_KEYS = {
    "route",
    "depth",
    "objective",
    "selected_modules",
    "created",
    "updated",
    "reused",
    "generated",
    "not_called",
    "target_evidence_cutoff_date",
}


def version_history_rows(total: Document, issues: list[Issue]) -> list[list[str]]:
    lines = total.body.splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if line.strip() == "## 9. 版本与同步记录"
    ]
    if len(headings) != 1:
        add(
            issues,
            "error",
            "run_history_section_invalid",
            total.path,
            "综合报告必须恰有一个“版本与同步记录”章节。",
        )
        return []
    rows: list[list[str]] = []
    for line in lines[headings[0] + 1 :]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if (
            not cells
            or cells[0] == "updated_at"
            or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)
        ):
            continue
        if len(cells) != 5:
            add(
                issues,
                "error",
                "run_history_row_shape",
                total.path,
                f"运行记录必须恰有5列：{line[:120]}",
            )
            continue
        rows.append(cells)
    if not rows:
        add(
            issues,
            "error",
            "run_history_empty",
            total.path,
            "版本与同步记录至少需要一条运行记录。",
        )
    return rows


def refresh_ledger_rows(total: Document, issues: list[Issue]) -> list[list[str]]:
    lines = total.body.splitlines()
    headings = [
        index for index, line in enumerate(lines) if line.strip() == REFRESH_HEADING
    ]
    if not headings:
        if total.frontmatter.get("route") == "refresh":
            add(
                issues,
                "error",
                "refresh_ledger_section_missing",
                total.path,
                "refresh综合报告必须包含刷新结果记录章节。",
            )
        return []
    if len(headings) != 1:
        add(
            issues,
            "error",
            "refresh_ledger_section_invalid",
            total.path,
            "刷新结果记录章节必须恰有一个。",
        )
        return []
    rows: list[list[str]] = []
    header_seen = False
    for line in lines[headings[0] + 1 :]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if cells == REFRESH_HEADER:
            header_seen = True
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if len(cells) != 6:
            add(
                issues,
                "error",
                "refresh_ledger_row_shape",
                total.path,
                "刷新结果记录必须恰有6列。",
            )
            continue
        rows.append(cells)
    if not header_seen:
        add(
            issues,
            "error",
            "refresh_ledger_header_invalid",
            total.path,
            "刷新结果记录表头必须为run_id及五类变更。",
        )
    run_ids = [row[0] for row in rows]
    if len(run_ids) != len(set(run_ids)):
        add(
            issues,
            "error",
            "refresh_ledger_run_duplicate",
            total.path,
            "刷新结果记录的latest_run_id不得重复。",
        )
    return rows


def parse_refresh_items(value: str) -> tuple[set[str], bool]:
    if value == "none":
        return set(), True
    members = [member.strip() for member in value.split(",")]
    valid = bool(members) and all(
        REFRESH_ITEM_RE.fullmatch(member) for member in members
    )
    return set(members), valid and len(members) == len(set(members))


def summary_fields_without_reporting(summary: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in summary.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def validate_refresh_ledger(
    by_type: dict[str, Document],
    claims: dict[str, ClaimDefinition],
    sources: dict[str, SourceDefinition],
    issues: list[Issue],
    strict: bool,
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    ledger = refresh_ledger_rows(total, issues)
    if total.frontmatter.get("route") != "refresh":
        return
    history = version_history_rows(total, [])
    if len(history) < 2:
        add(
            issues,
            "error",
            "refresh_not_resume",
            total.path,
            "refresh必须建立在至少一条更早运行记录上，首轮不得为refresh。",
        )
    if history:
        first_fields = summary_fields_without_reporting(history[0][3])
        if first_fields.get("route") == "refresh":
            add(
                issues,
                "error",
                "refresh_first_run_invalid",
                total.path,
                "首条运行记录不得为refresh。",
            )
    enforce = strict or total.frontmatter.get("workflow_stage") in {"review", "closed"}
    if not enforce:
        return
    latest_run_id = total.frontmatter.get("latest_run_id", "")
    matches = [row for row in ledger if row[0] == latest_run_id]
    if len(matches) != 1:
        add(
            issues,
            "error",
            "refresh_ledger_latest_missing",
            total.path,
            "严格refresh必须恰有一条对应latest_run_id的刷新结果记录。",
        )
        return
    row = matches[0]
    categories: list[set[str]] = []
    for label, value in zip(REFRESH_HEADER[1:], row[1:]):
        members, valid = parse_refresh_items(value)
        if not valid:
            add(
                issues,
                "error",
                "refresh_ledger_value_invalid",
                total.path,
                f"刷新分类“{label}”必须是逗号分隔claim/source ID或exact none。",
            )
        categories.append(members)
    all_members = set().union(*categories)
    if not all_members:
        add(
            issues,
            "error",
            "refresh_ledger_empty",
            total.path,
            "严格refresh至少应在五类中登记一个claim/source ID；无变化时在“未变化”列列出已复核ID。",
        )
    if sum(len(members) for members in categories) != len(all_members):
        add(
            issues,
            "error",
            "refresh_ledger_overlap",
            total.path,
            "同一claim/source ID不得同时属于多个刷新分类。",
        )
    known_ids = set(claims) | set(sources)
    unknown = sorted(all_members - known_ids)
    if unknown:
        add(
            issues,
            "error",
            "refresh_ledger_orphan",
            total.path,
            "刷新结果记录引用了未定义ID：" + ", ".join(unknown),
        )
    if history:
        latest_fields = summary_fields_without_reporting(history[-1][3])
        target_cutoff = latest_fields.get("target_evidence_cutoff_date", "")
        if target_cutoff != total.frontmatter.get("evidence_cutoff_date"):
            add(
                issues,
                "error",
                "refresh_cutoff_not_merged",
                total.path,
                "严格refresh要求最新run目标截止日与综合报告evidence_cutoff_date一致。",
            )
    status_rows = parse_status_rows(total)
    selected_research = {
        artifact_type
        for artifact_type in RESEARCH_PREFIX
        if len(status_rows.get(artifact_type, [])) >= 3
        and status_rows[artifact_type][1] == "true"
    }
    if not selected_research:
        add(
            issues,
            "error",
            "refresh_research_missing",
            total.path,
            "严格refresh至少选择一个研究成果。",
        )
    for artifact_type in selected_research:
        row = status_rows[artifact_type]
        if row[2] not in {"created", "updated"}:
            add(
                issues,
                "error",
                "refresh_action_invalid",
                total.path,
                f"{STATUS_LABELS[artifact_type]}在refresh中必须created或updated。",
            )
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue
        if artifact.frontmatter.get("latest_run_id") != latest_run_id:
            add(
                issues,
                "error",
                "refresh_artifact_run_mismatch",
                artifact.path,
                "refresh所选研究成果必须由本轮run实际写入。",
            )
        if artifact.frontmatter.get("evidence_cutoff_date") != total.frontmatter.get(
            "evidence_cutoff_date"
        ):
            add(
                issues,
                "error",
                "refresh_artifact_cutoff_mismatch",
                artifact.path,
                "refresh所选研究成果的evidence_cutoff_date必须与已合并总报告一致。",
            )


def parse_member_set(value: str) -> tuple[set[str], bool]:
    if value == "none":
        return set(), True
    members = [member.strip() for member in value.split(",")]
    valid = bool(members) and all(members) and len(members) == len(set(members))
    return set(members), valid


def parse_run_summary(
    summary: str, total: Document, run_id: str, issues: list[Issue]
) -> dict[str, str] | None:
    fields: dict[str, str] = {}
    malformed = False
    for part in summary.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            malformed = True
            continue
        key, value = part.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in fields:
            add(
                issues,
                "error",
                "run_history_field_duplicate",
                total.path,
                f"{run_id}运行摘要字段重复：{key}。",
            )
        fields[key] = value
    if malformed:
        add(
            issues,
            "error",
            "run_history_field_malformed",
            total.path,
            f"{run_id}运行摘要包含非key=value片段。",
        )
    missing = sorted(RUN_SUMMARY_KEYS - fields.keys())
    unknown = sorted(fields.keys() - RUN_SUMMARY_KEYS)
    if missing:
        add(
            issues,
            "error",
            "run_history_incomplete",
            total.path,
            f"{run_id}运行记录缺少：" + ", ".join(missing),
        )
    if unknown:
        add(
            issues,
            "error",
            "run_history_unknown_field",
            total.path,
            f"{run_id}运行记录含未知字段：" + ", ".join(unknown),
        )
    if missing or unknown or malformed:
        return None
    if fields["route"] not in ROUTES:
        add(
            issues,
            "error",
            "run_history_route_invalid",
            total.path,
            f"{run_id}的route无效。",
        )
    if fields["depth"] not in DEPTHS:
        add(
            issues,
            "error",
            "run_history_depth_invalid",
            total.path,
            f"{run_id}的depth无效。",
        )
    if not fields["objective"]:
        add(
            issues,
            "error",
            "run_objective_missing",
            total.path,
            f"{run_id}的objective不能为空。",
        )
    if not date_valid(fields["target_evidence_cutoff_date"]):
        add(
            issues,
            "error",
            "run_target_cutoff_invalid",
            total.path,
            f"{run_id}的target_evidence_cutoff_date必须为YYYY-MM-DD。",
        )

    selected, selected_valid = parse_member_set(fields["selected_modules"])
    if not selected_valid or not selected <= RUN_ARTIFACT_NAMES:
        add(
            issues,
            "error",
            "run_history_selected_invalid",
            total.path,
            f"{run_id}的selected_modules含重复、空值或未知成果。",
        )
    action_sets: dict[str, set[str]] = {}
    for action in ("created", "updated", "reused", "generated", "not_called"):
        members, valid = parse_member_set(fields[action])
        action_sets[action] = members
        if not valid or not members <= RUN_ARTIFACT_NAMES:
            add(
                issues,
                "error",
                "run_history_action_invalid",
                total.path,
                f"{run_id}的{action}含重复、空值或未知成果。",
            )
    assigned = set().union(*action_sets.values())
    overlaps = sum(len(members) for members in action_sets.values()) != len(assigned)
    if assigned != RUN_ARTIFACT_NAMES or overlaps:
        add(
            issues,
            "error",
            "run_history_action_partition_invalid",
            total.path,
            f"{run_id}的五类动作必须无重叠且完整覆盖全部成果登记。",
        )
    expected_selected = assigned - action_sets["not_called"]
    if selected != expected_selected:
        add(
            issues,
            "error",
            "run_history_selected_mismatch",
            total.path,
            f"{run_id}的selected_modules与动作分区不一致。",
        )
    if action_sets["generated"] - {"external_letter"}:
        add(
            issues,
            "error",
            "run_history_generated_invalid",
            total.path,
            f"{run_id}仅external_letter可使用generated动作。",
        )
    invalid_external_actions = [
        action
        for action in ("created", "updated", "reused")
        if "external_letter" in action_sets[action]
    ]
    if invalid_external_actions:
        add(
            issues,
            "error",
            "run_history_external_action_invalid",
            total.path,
            f"{run_id}的external_letter只允许generated或not_called，不能属于：{', '.join(invalid_external_actions)}。",
        )
    if "external_letter" in selected and fields["route"] != "letter":
        add(
            issues,
            "error",
            "run_history_external_route_invalid",
            total.path,
            f"{run_id}选择external_letter时route必须为letter。",
        )
    if fields["route"] == "research_only" and selected & {
        "strategy",
        "letter",
        "external_letter",
    }:
        add(
            issues,
            "error",
            "run_history_route_modules_invalid",
            total.path,
            f"{run_id}的research_only不得选择输出成果。",
        )
    if fields["route"] == "refresh" and selected & {
        "strategy",
        "letter",
        "external_letter",
    }:
        add(
            issues,
            "error",
            "run_history_route_modules_invalid",
            total.path,
            f"{run_id}的refresh只能选择研究成果。",
        )
    if fields["route"] == "refresh":
        if not selected & {"institution", "leader", "internal"}:
            add(
                issues,
                "error",
                "run_history_refresh_research_missing",
                total.path,
                f"{run_id}的refresh至少选择一个研究成果。",
            )
        if action_sets["reused"]:
            add(
                issues,
                "error",
                "run_history_refresh_reused_invalid",
                total.path,
                f"{run_id}的refresh所选研究必须created/updated，不能仅标reused。",
            )
    required = {
        "visit_prep": "strategy",
        "strategy": "strategy",
        "letter": "letter",
    }.get(fields["route"])
    if required and required not in selected:
        add(
            issues,
            "error",
            "run_history_required_module_missing",
            total.path,
            f"{run_id}的route={fields['route']}必须选择{required}。",
        )
    if fields["route"] in {"visit_prep", "strategy", "letter"} and not selected & {
        "institution",
        "leader",
        "internal",
    }:
        add(
            issues,
            "error",
            "run_history_research_carrier_missing",
            total.path,
            f"{run_id}缺少研究载体。",
        )
    return fields


def validate_run_history(by_type: dict[str, Document], issues: list[Issue]) -> None:
    total = by_type.get("comprehensive_report")
    if not total:
        return
    history = version_history_rows(total, issues)
    if not history:
        return
    seen_runs: set[str] = set()
    previous_version: int | None = None
    previous_time: datetime | None = None
    parsed_by_run: dict[str, dict[str, str]] = {}
    for updated_at, version, run_id, summary, owner in history:
        if not timestamp_valid(updated_at):
            add(
                issues,
                "error",
                "run_history_timestamp_invalid",
                total.path,
                f"运行记录{run_id}的updated_at无效。",
            )
            parsed_time = None
        else:
            parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if not CONTENT_VERSION_RE.fullmatch(version):
            add(
                issues,
                "error",
                "run_history_version_invalid",
                total.path,
                f"运行记录{run_id}的content_version无效。",
            )
            numeric_version = None
        else:
            numeric_version = int(version)
        if not run_id_valid(run_id):
            add(
                issues,
                "error",
                "run_history_run_id_invalid",
                total.path,
                f"运行记录run_id无效：{run_id!r}。",
            )
        if run_id in seen_runs:
            add(
                issues,
                "error",
                "run_history_run_duplicate",
                total.path,
                f"运行记录run_id重复：{run_id}。",
            )
        seen_runs.add(run_id)
        if not owner.strip():
            add(
                issues,
                "error",
                "run_history_owner_missing",
                total.path,
                f"运行记录{run_id}的runtime_owner不能为空。",
            )
        if (
            previous_version is not None
            and numeric_version is not None
            and numeric_version != previous_version + 1
        ):
            add(
                issues,
                "error",
                "run_history_version_sequence",
                total.path,
                f"运行记录{run_id}的版本必须紧接前一版本。",
            )
        if (
            previous_time is not None
            and parsed_time is not None
            and parsed_time < previous_time
        ):
            add(
                issues,
                "error",
                "run_history_time_sequence",
                total.path,
                f"运行记录{run_id}的updated_at早于前一条记录。",
            )
        if numeric_version is not None:
            previous_version = numeric_version
        if parsed_time is not None:
            previous_time = parsed_time
        parsed = parse_run_summary(summary, total, run_id, issues)
        if parsed is not None:
            parsed_by_run[run_id] = parsed

    latest_run_id = total.frontmatter.get("latest_run_id", "")
    matching = [row for row in history if row[2] == latest_run_id]
    if len(matching) != 1 or history[-1][2] != latest_run_id:
        add(
            issues,
            "error",
            "latest_run_history_missing",
            total.path,
            f"最后一条版本记录必须恰好对应latest_run_id={latest_run_id}。",
        )
        return
    latest = matching[0]
    if latest[0] != total.frontmatter.get("updated_at"):
        add(
            issues,
            "error",
            "run_history_latest_time_mismatch",
            total.path,
            "最新运行记录updated_at与综合报告不一致。",
        )
    if latest[1] != total.frontmatter.get("content_version"):
        add(
            issues,
            "error",
            "run_history_latest_version_mismatch",
            total.path,
            "最新运行记录content_version与综合报告不一致。",
        )
    if latest[4] != total.frontmatter.get("runtime_owner"):
        add(
            issues,
            "error",
            "run_history_latest_owner_mismatch",
            total.path,
            "最新运行记录runtime_owner与综合报告不一致。",
        )
    fields = parsed_by_run.get(latest_run_id)
    if fields is None:
        return
    if fields["route"] != total.frontmatter.get("route") or fields[
        "depth"
    ] != total.frontmatter.get("depth"):
        add(
            issues,
            "error",
            "run_history_latest_route_mismatch",
            total.path,
            "最新运行记录route/depth与综合报告不一致。",
        )
    rows = parse_status_rows(total)
    names = {
        "institution_research": "institution",
        "leader_research": "leader",
        "internal_retrieval": "internal",
        "visit_strategy": "strategy",
        "customer_letter_internal": "letter",
        "customer_letter_external": "external_letter",
    }
    expected_actions = {
        names[artifact_type]: row[2]
        for artifact_type, row in rows.items()
        if artifact_type in names and len(row) >= 3
    }
    for action in ("created", "updated", "reused", "generated", "not_called"):
        expected = {name for name, value in expected_actions.items() if value == action}
        recorded, _ = parse_member_set(fields[action])
        if recorded != expected:
            add(
                issues,
                "error",
                "run_history_action_mismatch",
                total.path,
                f"最新运行记录{action}与当前成果登记不一致。",
            )


def validate_route_gate(
    by_type: dict[str, Document], issues: list[Issue], strict: bool
) -> None:
    total = by_type.get("comprehensive_report")
    if not total:
        return
    if strict and (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("freshness_status") != "current"
    ):
        add(
            issues,
            "error",
            "strict_total_not_ready",
            total.path,
            "严格最终校验要求综合报告completed/current。",
        )
    if strict:
        route = total.frontmatter.get("route")
        allowed_stages = (
            {"output", "closed"}
            if route in {"research_only", "refresh"}
            else {"output", "review", "closed"}
        )
        if total.frontmatter.get("workflow_stage") not in allowed_stages:
            add(
                issues,
                "error",
                "strict_workflow_stage_not_ready",
                total.path,
                f"严格最终校验下route={route}的workflow_stage必须为{sorted(allowed_stages)}。",
            )
    rows = parse_status_rows(total)
    selected_types = {
        artifact_type
        for artifact_type, row in rows.items()
        if len(row) >= 2 and row[1] == "true"
    }
    if strict or total.frontmatter.get("workflow_stage") in {"review", "closed"}:
        for artifact_type in selected_types:
            artifact = by_type.get(artifact_type)
            if artifact is None:
                continue
            if artifact.frontmatter.get("module_status") not in TERMINAL_STATUSES:
                add(
                    issues,
                    "error",
                    "selected_module_nonterminal",
                    artifact.path,
                    "严格交付或review/closed流程要求本轮所选模块达到partial/completed/blocked。",
                )
            row = rows.get(artifact_type, [])
            if (
                artifact_type != "customer_letter_external"
                and len(row) >= 11
                and row[10] != "synced"
            ):
                add(
                    issues,
                    "error",
                    "selected_module_unsynced",
                    total.path,
                    f"{STATUS_LABELS[artifact_type]}尚未同步到综合报告。",
                )
            if len(row) >= 14 and row[13] in {"", "待评估", "待提取", "待确认"}:
                add(
                    issues,
                    "error",
                    "selected_module_gaps_unresolved",
                    total.path,
                    f"{STATUS_LABELS[artifact_type]}必须明确填写gaps/blockers；无则写“无”。",
                )
            if (
                len(row) >= 14
                and artifact.frontmatter.get("module_status") in {"partial", "blocked"}
                and normalize_evidence_text(row[13])
                in {"无", "none", "n/a", "na", "暂无"}
            ):
                add(
                    issues,
                    "error",
                    "terminal_gap_missing",
                    total.path,
                    f"{STATUS_LABELS[artifact_type]}为partial/blocked时必须写明实际缺口或阻塞。",
                )
            if (
                len(row) >= 14
                and artifact.frontmatter.get("module_status") == "blocked"
            ):
                gap_text = row[13]
                if not all(token in gap_text for token in ("尝试", "影响", "解除")):
                    add(
                        issues,
                        "error",
                        "blocked_resolution_incomplete",
                        total.path,
                        f"{STATUS_LABELS[artifact_type]}为blocked时gaps/blockers必须包含已尝试动作、影响和解除条件。",
                    )
    if (
        total.frontmatter.get("workflow_stage") == "closed"
        and total.frontmatter.get("module_status") != "completed"
    ):
        add(
            issues,
            "error",
            "closed_total_incomplete",
            total.path,
            "workflow_stage=closed时综合报告module_status必须为completed。",
        )

    route = total.frontmatter.get("route")
    required_selected = {
        "visit_prep": "visit_strategy",
        "strategy": "visit_strategy",
        "letter": "customer_letter_internal",
    }.get(route)
    if required_selected and required_selected not in selected_types:
        add(
            issues,
            "error",
            "route_required_module_unselected",
            total.path,
            f"route={route}必须把{required_selected}列为本轮调用或复用模块。",
        )
    if route == "research_only":
        unexpected = selected_types & {
            "visit_strategy",
            "customer_letter_internal",
            "customer_letter_external",
        }
        if unexpected:
            add(
                issues,
                "error",
                "research_only_output_selected",
                total.path,
                "research_only不得选择策略或客户信成果；请改用对应主路由。",
            )
    if (
        selected_types & {"customer_letter_internal", "customer_letter_external"}
        and route != "letter"
    ):
        add(
            issues,
            "error",
            "letter_route_not_highest_gate",
            total.path,
            "选择客户信时主路由必须为letter。",
        )
    if route == "refresh" and selected_types & {
        "visit_strategy",
        "customer_letter_internal",
        "customer_letter_external",
    }:
        add(
            issues,
            "error",
            "refresh_output_selected",
            total.path,
            "refresh只允许研究模块；策略或客户信应使用相应主路由。",
        )
    if route in {"visit_prep", "strategy", "letter"} and not (
        {"institution_research", "leader_research", "internal_retrieval"}
        & by_type.keys()
    ):
        add(
            issues,
            "error",
            "route_research_carrier_missing",
            total.path,
            f"route={route}至少需要一个研究成果承载claim/source台账。",
        )
    if route in {"visit_prep", "strategy", "letter"} and not (
        {"institution_research", "leader_research", "internal_retrieval"}
        & selected_types
    ):
        add(
            issues,
            "error",
            "route_research_carrier_unselected",
            total.path,
            f"route={route}必须把至少一个研究成果登记为本轮selected/reused或selected/updated。",
        )
    if (
        total.frontmatter.get("workflow_stage") == "closed"
        and total.frontmatter.get("freshness_status") == "current"
    ):
        invalidations = [
            row[12]
            for row in rows.values()
            if len(row) >= 13 and row[12] in {"stale", "invalidated"}
        ]
        if invalidations:
            add(
                issues,
                "error",
                "closed_total_ignores_invalidation",
                total.path,
                "综合报告标为current但成果登记仍有下游失效信号。",
            )
    if not strict and total.frontmatter.get("workflow_stage") not in {
        "review",
        "closed",
    }:
        return
    if (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("freshness_status") != "current"
    ):
        add(
            issues,
            "error",
            "review_stage_total_not_ready",
            total.path,
            "review/closed阶段的综合报告必须completed/current。",
        )

    for artifact_type in selected_types:
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue
        is_research = artifact_type in {
            "institution_research",
            "leader_research",
            "internal_retrieval",
        }
        if is_research:
            if artifact.frontmatter.get("module_status") not in TERMINAL_STATUSES:
                add(
                    issues,
                    "error",
                    "review_stage_research_nonterminal",
                    artifact.path,
                    "review/closed阶段的研究成果必须为partial/completed/blocked终态。",
                )
            if artifact.frontmatter.get("freshness_status") != "current":
                add(
                    issues,
                    "error",
                    "review_stage_research_stale",
                    artifact.path,
                    "review/closed阶段引用的研究成果必须current；stale/invalidated应先刷新或移除依赖。",
                )
        allowed_reviews = (
            {"not_required"} if artifact_type == "institution_research" else set()
        )
        if artifact_type in {"leader_research", "internal_retrieval"}:
            allowed_reviews = (
                {"pending", "approved"}
                if artifact.frontmatter.get("module_status") == "completed"
                else {"not_started", "pending", "approved"}
            )
        if artifact_type in {"visit_strategy", "customer_letter_internal"}:
            allowed_reviews = (
                {"pending", "approved"}
                if total.frontmatter.get("workflow_stage") == "closed"
                else {"pending", "approved", "changes_requested"}
            )
        if artifact_type == "customer_letter_external":
            allowed_reviews = {"approved"}
        if (
            allowed_reviews
            and artifact.frontmatter.get("review_status") not in allowed_reviews
        ):
            add(
                issues,
                "error",
                "review_stage_status_invalid",
                artifact.path,
                f"review/closed阶段的{artifact_type}审核状态必须为{sorted(allowed_reviews)}。",
            )

    for artifact_type in selected_types & {
        "visit_strategy",
        "customer_letter_internal",
    }:
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue
        if artifact.frontmatter.get("module_status") != "completed":
            add(
                issues,
                "error",
                "selected_output_incomplete",
                artifact.path,
                "review/closed阶段的选中输出必须completed。",
            )
        if artifact.frontmatter.get("freshness_status") != "current":
            add(
                issues,
                "error",
                "selected_output_stale",
                artifact.path,
                "review/closed阶段的选中输出必须current。",
            )
        if artifact.frontmatter.get("review_status") not in {
            "pending",
            "approved",
            "changes_requested",
        }:
            add(
                issues,
                "error",
                "selected_output_review_missing",
                artifact.path,
                "review/closed阶段的选中输出必须记录审核状态。",
            )
        if (
            total.frontmatter.get("workflow_stage") == "closed"
            and artifact.frontmatter.get("review_status") == "changes_requested"
        ):
            add(
                issues,
                "error",
                "closed_output_changes_requested",
                artifact.path,
                "changes_requested成果不得进入closed；修改后重新提交审核。",
            )
    required_type = required_selected
    if not required_type:
        return
    artifact = by_type.get(required_type)
    if artifact is None:
        add(
            issues,
            "error",
            "route_required_artifact_missing",
            total.path,
            f"route={route}缺少{required_type}成果。",
        )
        return
    if artifact.frontmatter.get("module_status") != "completed":
        add(
            issues,
            "error",
            "route_required_artifact_incomplete",
            artifact.path,
            f"route={route}要求该成果module_status=completed。",
        )
    if artifact.frontmatter.get("freshness_status") != "current":
        add(
            issues,
            "error",
            "route_required_artifact_stale",
            artifact.path,
            f"route={route}要求该成果freshness_status=current。",
        )
    letter_reviews = (
        {"pending", "approved"}
        if total.frontmatter.get("workflow_stage") == "closed"
        else {"pending", "approved", "changes_requested"}
    )
    if (
        route == "letter"
        and artifact.frontmatter.get("review_status") not in letter_reviews
    ):
        add(
            issues,
            "error",
            "letter_review_gate",
            artifact.path,
            f"letter在当前阶段的审核状态必须为{sorted(letter_reviews)}。",
        )


def validate_links(documents: list[Document], root: Path, issues: list[Issue]) -> None:
    for document in documents:
        for raw_target in LINK_RE.findall(document.body):
            target = unquote(raw_target.strip().split("#", 1)[0])
            if (
                not target
                or "{{" in target
                or re.match(r"^(?:https?://|mailto:)", target)
            ):
                continue
            candidate = Path(target)
            if candidate.is_absolute():
                add(
                    issues,
                    "error",
                    "link_absolute",
                    document.path,
                    f"本地成果链接必须相对：{raw_target}",
                )
                continue
            resolved = (document.path.parent / candidate).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                add(
                    issues,
                    "error",
                    "link_escape",
                    document.path,
                    f"链接越出工作目录：{raw_target}",
                )
                continue
            if not resolved.is_file():
                add(
                    issues,
                    "error",
                    "link_missing",
                    document.path,
                    f"链接目标不存在：{raw_target}",
                )


def marker_bounds(body: str) -> tuple[int, int] | None:
    lines = body.splitlines()
    starts = [
        i for i, line in enumerate(lines) if line.strip(" `\t") == "EXTERNAL_BODY_START"
    ]
    ends = [
        i for i, line in enumerate(lines) if line.strip(" `\t") == "EXTERNAL_BODY_END"
    ]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        return None
    return starts[0], ends[0]


def extract_external_body(document: Document) -> str | None:
    bounds = marker_bounds(document.body)
    if not bounds:
        return None
    lines = document.body.splitlines()
    return "\n".join(lines[bounds[0] + 1 : bounds[1]])


def normalize_body(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def canonical_approved_body(value: str | None) -> str:
    lines = (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def body_sha256(value: str | None) -> str:
    return hashlib.sha256(canonical_approved_body(value).encode("utf-8")).hexdigest()


def external_leaks(body: str) -> list[str]:
    leaks = [term for term in sorted(FORBIDDEN_EXTERNAL_TERMS) if term in body]
    if HTML_COMMENT_RE.search(body):
        leaks.append("HTML注释")
    if CLAIM_RE.search(body) or SOURCE_RE.search(body):
        leaks.append("claim_id/source_id")
    return leaks


def external_body_without_title(body: str) -> str:
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^#\s+", lines[0]):
        lines.pop(0)
    return "\n".join(lines)


def validate_letter_isolation(
    by_type: dict[str, Document], issues: list[Issue]
) -> None:
    internal = by_type.get("customer_letter_internal")
    external = by_type.get("customer_letter_external")
    if internal:
        approved_body = extract_external_body(internal)
        if approved_body is None:
            add(
                issues,
                "error",
                "external_markers_invalid",
                internal.path,
                "外发正文标记必须各出现一次且顺序正确。",
            )
        elif internal.frontmatter.get(
            "module_status"
        ) == "completed" and not normalize_body(approved_body):
            add(
                issues,
                "error",
                "external_body_empty",
                internal.path,
                "completed内部稿的外发正文不能为空。",
            )
        elif approved_body is not None and not PLACEHOLDER_RE.search(approved_body):
            for leak in external_leaks(approved_body):
                add(
                    issues,
                    "error",
                    "external_candidate_leak",
                    internal.path,
                    f"标记间候选外发正文包含禁用内容：{leak}",
                )
        required = internal.frontmatter.get("external_output_required") == "true"
        if (
            required
            and internal.frontmatter.get("review_status") == "approved"
            and external is None
        ):
            add(
                issues,
                "error",
                "external_letter_required",
                internal.path,
                "已批准且要求外发版，但外发文件不存在。",
            )
    if external:
        if internal is None:
            add(
                issues,
                "error",
                "external_without_internal",
                external.path,
                "外发版必须有对应内部审核稿。",
            )
            return
        if (
            internal.frontmatter.get("module_status") != "completed"
            or internal.frontmatter.get("review_status") != "approved"
        ):
            add(
                issues,
                "error",
                "external_source_unapproved",
                external.path,
                "内部稿未completed/approved，不得存在外发版。",
            )
        if internal.frontmatter.get("external_output_required") != "true":
            add(
                issues,
                "error",
                "external_not_requested",
                external.path,
                "外发版存在时内部稿external_output_required必须为true。",
            )
        if internal.frontmatter.get("freshness_status") != "current":
            add(
                issues,
                "error",
                "external_source_stale",
                external.path,
                "内部稿不是current时不得存在外发版。",
            )
        clean = external_body_without_title(external.body)
        first_line = next(
            (line.strip() for line in external.body.splitlines() if line.strip()), ""
        )
        expected_title = (
            f"# {external.frontmatter.get('customer_display_name', '')}客户信（外发版）"
        )
        if first_line != expected_title:
            add(
                issues,
                "error",
                "external_title_invalid",
                external.path,
                f"外发版标题应为：{expected_title}",
            )
        if not normalize_body(clean):
            add(
                issues,
                "error",
                "external_body_empty",
                external.path,
                "外发版正文为空。",
            )
        for leak in external_leaks(external.body):
            code = (
                "external_html_comment"
                if leak == "HTML注释"
                else "external_internal_leak"
            )
            add(issues, "error", code, external.path, f"外发版包含禁用内容：{leak}")
        approved_body = extract_external_body(internal)
        if approved_body is not None and canonical_approved_body(
            clean
        ) != canonical_approved_body(approved_body):
            add(
                issues,
                "error",
                "external_body_drift",
                external.path,
                "外发版与内部稿标记间已批准正文不一致。",
            )
        for field in (
            "context_id",
            "latest_run_id",
            "customer_id",
            "customer_display_name",
            "organization_scope",
            "safe_name",
            "evidence_cutoff_date",
            "updated_at",
            "runtime_owner",
            "approver",
            "approved_at",
            "approved_body_sha256",
            "approved_context_sha256",
        ):
            if external.frontmatter.get(field) != internal.frontmatter.get(field):
                add(
                    issues,
                    "error",
                    "external_metadata_drift",
                    external.path,
                    f"外发版{field}必须继承当前内部稿。",
                )
        if external.frontmatter.get(
            "source_internal_content_version"
        ) != internal.frontmatter.get("content_version"):
            add(
                issues,
                "error",
                "external_lineage_version_drift",
                external.path,
                "source_internal_content_version必须等于当前内部稿content_version。",
            )
        if external.frontmatter.get(
            "approved_content_version"
        ) != internal.frontmatter.get("approved_content_version"):
            add(
                issues,
                "error",
                "external_approval_version_drift",
                external.path,
                "外发版approved_content_version必须与内部稿一致。",
            )


def yaml_line(key: str, value: str) -> str:
    return f"{key}: {json.dumps(value, ensure_ascii=False)}"


def replace_flat_frontmatter(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise RuntimeError("综合报告frontmatter未闭合。") from exc
    seen: set[str] = set()
    for index in range(1, end):
        match = re.match(r"([A-Za-z_][A-Za-z0-9_-]*):", lines[index])
        if match and match.group(1) in updates:
            key = match.group(1)
            lines[index] = yaml_line(key, updates[key])
            seen.add(key)
    for key in updates.keys() - seen:
        lines.insert(end, yaml_line(key, updates[key]))
        end += 1
    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass
class Mutation:
    result_path: Path
    originals: dict[Path, str]
    created: list[Path]
    deleted: list[Path]
    transactional: bool = False


@dataclass(frozen=True)
class WorkspaceSnapshot:
    manifest_revision: int | None
    manifest_sha256: str | None
    manifest: dict[str, object] | None
    file_states: dict[Path, dict[str, object]]


def capture_workspace_snapshot(
    root: Path, documents: list[Document]
) -> WorkspaceSnapshot:
    manifest_path = root / MANIFEST_REL
    before_manifest_exists = manifest_path.exists()
    manifest = load_manifest(root, required=False)
    revision: int | None = None
    manifest_digest: str | None = None
    file_states: dict[Path, dict[str, object]] = {}
    if manifest is not None:
        revision, manifest_digest = manifest_state(root)
        file_states[manifest_path] = file_state(manifest_path).as_dict()
    for document in documents:
        state = file_state(document.path)
        expected_hash = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        if not state.exists or state.sha256 != expected_hash:
            raise RuntimeError(
                f"读取工作区期间成果发生变化，请重试：{document.path.name}"
            )
        file_states[document.path] = state.as_dict()
    after_manifest_exists = manifest_path.exists()
    if before_manifest_exists != after_manifest_exists:
        raise RuntimeError("读取工作区期间运行清单发生变化，请重试。")
    if manifest is not None:
        current_revision, current_digest = manifest_state(root)
        if current_revision != revision or current_digest != manifest_digest:
            raise RuntimeError("读取工作区期间运行清单发生变化，请重试。")
    return WorkspaceSnapshot(revision, manifest_digest, manifest, file_states)


MODULE_NAME_FOR_TYPE = {
    "institution_research": "institution",
    "leader_research": "leader",
    "internal_retrieval": "internal",
    "visit_strategy": "strategy",
    "customer_letter_internal": "letter",
    "customer_letter_external": "external_letter",
}


def manifest_for_mutation(
    root: Path,
    planned: dict[Path, str],
    deleted: list[Path],
    snapshot: WorkspaceSnapshot,
) -> tuple[dict[Path, bytes | str], dict[Path, dict[str, object]]]:
    total_candidates: list[tuple[Path, str]] = []
    for path, text in planned.items():
        metadata, _ = parse_frontmatter(path, text, [])
        if metadata.get("artifact_type") == "comprehensive_report":
            total_candidates.append((path, text))
    if not total_candidates:
        for path in root.glob(f"*{SUFFIXES['comprehensive_report']}"):
            if path not in deleted:
                total_candidates.append((path, path.read_text(encoding="utf-8")))
    if len(total_candidates) != 1:
        raise RuntimeError("事务候选必须恰有一个综合报告。")
    total_path, total_text = total_candidates[0]
    parse_issues: list[Issue] = []
    total_data, total_body = parse_frontmatter(total_path, total_text, parse_issues)
    if any(issue.severity == "error" for issue in parse_issues):
        raise RuntimeError("事务候选综合报告frontmatter无效。")
    total_document = Document(total_path, total_text, total_data, total_body)
    rows = parse_status_rows(total_document)
    selected_modules = [
        MODULE_NAME_FOR_TYPE[artifact_type]
        for artifact_type, row in rows.items()
        if artifact_type in MODULE_NAME_FOR_TYPE and len(row) >= 2 and row[1] == "true"
    ]
    authorization: dict[str, object] = {}
    if snapshot.manifest and isinstance(snapshot.manifest.get("authorization"), dict):
        authorization.update(snapshot.manifest["authorization"])
    for key in (
        "tenant_id",
        "customer_id",
        "project_id",
        "authorization_owner",
        "authorization_expires_at",
    ):
        value = total_data.get(key, "")
        if value:
            authorization[key] = value
    overlay = {
        path: text.encode("utf-8")
        for path, text in planned.items()
        if path.suffix.casefold() == ".md"
    }
    manifest = build_manifest(
        root,
        identity={
            "context_id": total_data.get("context_id", ""),
            "customer_id": total_data.get("customer_id", ""),
            "customer_display_name": total_data.get("customer_display_name", ""),
            "organization_scope": total_data.get("organization_scope", ""),
        },
        business_mode=total_data.get("business_mode", "")
        or str((snapshot.manifest or {}).get("business_mode", "")),
        route=total_data.get("route", ""),
        depth=total_data.get("depth", ""),
        latest_run_id=total_data.get("latest_run_id", ""),
        content_version=total_data.get("content_version", ""),
        stage=total_data.get("workflow_stage", ""),
        ready_for_use=total_data.get("ready_for_use", "false") == "true",
        selected_modules=selected_modules,
        authorization=authorization,
        transaction_sequence=(snapshot.manifest_revision or 0) + 1,
        overlay=overlay,
        deletes=deleted,
    )
    manifest_text = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    all_planned: dict[Path, bytes | str] = dict(planned)
    manifest_path = root / MANIFEST_REL
    all_planned[manifest_path] = manifest_text
    expected_files = dict(snapshot.file_states)
    for path in list(all_planned) + deleted:
        if path not in expected_files:
            expected_files[path] = file_state(path).as_dict()
    return all_planned, expected_files


def registry_row(
    label: str,
    data: dict[str, str] | None,
    path: Path | None,
    *,
    action: str,
    extras: list[str] | None = None,
) -> str:
    if data is None or path is None:
        cells = [
            label,
            "false",
            "not_called",
            "not_called",
            "not_required",
            "not_applicable",
            "current",
            "",
            "",
            "",
            "not_applicable",
            "",
            "none",
            "无",
            "",
        ]
    else:
        preserved = extras or ["synced", "待提取", "none", "无"]
        cells = [
            label,
            "true" if action != "not_called" else "false",
            action,
            data.get("module_status", ""),
            data.get("review_status", ""),
            data.get("connector_status", ""),
            data.get("freshness_status", ""),
            data.get("content_version", ""),
            data.get("latest_run_id", ""),
            data.get("updated_at", ""),
            preserved[0],
            preserved[1],
            preserved[2],
            preserved[3],
            f"[{label}](./{path.name})",
        ]
    clean = [
        re.sub(r"[\r\n]+", " ", cell).replace("|", r"\|").strip() for cell in cells
    ]
    return "| " + " | ".join(clean) + " |"


def update_operation_rows(
    total: Document,
    by_type: dict[str, Document],
    *,
    metadata: dict[str, dict[str, str]],
    paths: dict[str, Path],
    actions: dict[str, str],
) -> str:
    text = total.text
    current_rows = parse_status_rows(total)
    for artifact_type, label in STATUS_LABELS.items():
        data = metadata.get(artifact_type)
        path = paths.get(artifact_type)
        if data is None and artifact_type in by_type:
            data = by_type[artifact_type].frontmatter
            path = by_type[artifact_type].path
        row = current_rows.get(artifact_type, [])
        extras = (
            row[10:14]
            if len(row) >= 15
            else ["out_of_sync", "待提取", "none", "待评估"]
        )
        if artifact_type in actions:
            extras[0] = (
                "not_applicable"
                if artifact_type == "customer_letter_external"
                else "synced"
            )
            extras[2] = "none"
            if artifact_type == "customer_letter_external":
                extras[1], extras[3] = "无", "无"
        replacement = registry_row(
            label,
            data,
            path,
            action=actions.get(artifact_type, "not_called"),
            extras=extras,
        )
        text, count = re.subn(
            rf"^\|\s*{re.escape(label)}\s*\|.*$",
            replacement,
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise RuntimeError(f"综合报告缺少标准状态行：{label}")
    return text


def operation_summary(
    total: Document, objective: str, actions: dict[str, str], cutoff: str
) -> str:
    names = {
        "institution_research": "institution",
        "leader_research": "leader",
        "internal_retrieval": "internal",
        "visit_strategy": "strategy",
        "customer_letter_internal": "letter",
        "customer_letter_external": "external_letter",
    }
    action_map = {names[key]: actions.get(key, "not_called") for key in names}
    selected = [name for name, action in action_map.items() if action != "not_called"]
    parts = [
        f"route={total.frontmatter.get('route', '')}",
        f"depth={total.frontmatter.get('depth', '')}",
        f"objective={objective}",
        "selected_modules=" + (",".join(selected) or "none"),
    ]
    for action in ("created", "updated", "reused", "generated", "not_called"):
        members = [name for name, value in action_map.items() if value == action]
        parts.append(f"{action}=" + (",".join(members) or "none"))
    parts.append(f"target_evidence_cutoff_date={cutoff}")
    return "; ".join(parts)


def append_operation_record(
    text: str, *, timestamp: str, version: str, run_id: str, summary: str, owner: str
) -> str:
    clean_owner = owner.replace("|", r"\|")
    row = f"| {timestamp} | {version} | {run_id} | {summary} | {clean_owner} |"
    lines = text.rstrip().splitlines()
    heading = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == "## 9. 版本与同步记录"
        ),
        None,
    )
    if heading is None:
        raise RuntimeError("总报告缺少版本与同步记录章节，无法追加操作记录。")
    section_end = next(
        (
            index
            for index in range(heading + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    table_rows = [
        index
        for index in range(heading + 1, section_end)
        if lines[index].lstrip().startswith("|")
    ]
    if len(table_rows) < 3:
        raise RuntimeError("版本与同步记录表损坏，无法追加操作记录。")
    lines.insert(table_rows[-1] + 1, row)
    return "\n".join(lines).rstrip() + "\n"


def append_letter_review_record(
    text: str,
    *,
    timestamp: str,
    version: str,
    run_id: str,
    summary: str,
    owner: str,
    review_status: str,
) -> str:
    clean = [
        re.sub(r"[\r\n]+", " ", value).replace("|", r"\|").strip()
        for value in (timestamp, version, run_id, summary, owner, review_status)
    ]
    row = "| " + " | ".join(clean) + " |"
    lines = text.rstrip().splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if line.strip() == LETTER_REVIEW_HEADING
    ]
    if len(headings) != 1:
        raise RuntimeError("内部稿必须恰有一个版本与审核记录章节，无法追加审计记录。")
    heading = headings[0]
    section_end = next(
        (
            index
            for index in range(heading + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    table_rows = [
        index
        for index in range(heading + 1, section_end)
        if lines[index].lstrip().startswith("|")
    ]
    if len(table_rows) < 3:
        raise RuntimeError("内部稿版本与审核记录表损坏，无法追加审计记录。")
    lines.insert(table_rows[-1] + 1, row)
    return "\n".join(lines).rstrip() + "\n"


def commit_mutation(
    planned: dict[Path, str],
    created: list[Path],
    result_path: Path,
    deleted: list[Path] | None = None,
    *,
    snapshot: WorkspaceSnapshot | None = None,
    workspace: Path | None = None,
    operation: str = "validator_mutation",
    strict_postflight: bool = False,
) -> Mutation:
    deleted = deleted or []
    originals: dict[Path, str] = {}
    for path in set(planned) | set(deleted):
        if path.exists():
            if path.is_symlink() or path.resolve().parent != path.parent.resolve():
                raise RuntimeError(f"拒绝修改符号链接或越界成果：{path}")
            originals[path] = path.read_text(encoding="utf-8")
        elif path in deleted:
            raise RuntimeError(f"待归档成果不存在：{path}")
    if snapshot is not None:
        if workspace is None:
            raise RuntimeError("事务化治理操作缺少workspace。")
        root = workspace.resolve()
        all_planned, expected_files = manifest_for_mutation(
            root, planned, deleted, snapshot
        )

        def governed_postflight(workspace: Path) -> None:
            post_issues: list[Issue] = []
            post_documents = load_documents(workspace, post_issues)
            validate_loaded(workspace, post_documents, post_issues, strict_postflight)
            errors = [issue for issue in post_issues if issue.severity == "error"]
            if errors:
                summary = "; ".join(
                    f"{issue.code}:{issue.message}" for issue in errors[:5]
                )
                raise TxError("事务候选完整校验失败：" + summary)

        transactional_write(
            root,
            all_planned,
            deletes=deleted,
            expected_manifest_revision=snapshot.manifest_revision,
            expected_manifest_hash=snapshot.manifest_sha256,
            expected_files=expected_files,
            operation=operation,
            postflight=governed_postflight,
            result_path=result_path,
        )
        return Mutation(result_path, originals, created, deleted, True)
    try:
        for path, text in planned.items():
            atomic_write(path, text.rstrip() + "\n")
        for path in deleted:
            path.unlink()
    except (OSError, UnicodeError) as exc:
        rollback_errors: list[str] = []
        for path, original in originals.items():
            try:
                atomic_write(path, original)
            except (OSError, UnicodeError) as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        for path in created:
            try:
                path.unlink(missing_ok=True)
            except (OSError, UnicodeError) as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "事务写入失败且回滚不完整：" + "; ".join(rollback_errors)
            ) from exc
        raise
    return Mutation(result_path, originals, created, deleted, False)


def rollback_mutation(mutation: Mutation) -> None:
    rollback_errors: list[str] = []
    for path, original in mutation.originals.items():
        try:
            atomic_write(path, original)
        except (OSError, UnicodeError) as exc:
            rollback_errors.append(f"{path}: {exc}")
    for path in mutation.created:
        try:
            path.unlink(missing_ok=True)
        except (OSError, UnicodeError) as exc:
            rollback_errors.append(f"{path}: {exc}")
    if rollback_errors:
        raise OSError("事务回滚不完整：" + "; ".join(rollback_errors))


def approve_internal(
    root: Path, documents: list[Document], approver: str, snapshot: WorkspaceSnapshot
) -> Mutation:
    internals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "customer_letter_internal"
    ]
    totals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "comprehensive_report"
    ]
    if len(internals) != 1 or len(totals) != 1:
        raise RuntimeError("审批需要且只能有一个客户信内部稿和一个综合报告。")
    internal, total = internals[0], totals[0]
    data = internal.frontmatter
    if total.frontmatter.get("route") != "letter" or total.frontmatter.get(
        "workflow_stage"
    ) not in {"review", "closed"}:
        raise RuntimeError(
            "审批只能在route=letter且workflow_stage=review/closed的上下文执行。"
        )
    if (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("freshness_status") != "current"
    ):
        raise RuntimeError("审批前综合报告必须completed/current。")
    if (
        data.get("module_status") != "completed"
        or data.get("review_status") != "pending"
    ):
        raise RuntimeError(
            "只有completed/pending的内部稿可加审批戳；changes_requested必须修改并重新提交为pending。"
        )
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的内部稿可批准。")
    if any(
        doc.frontmatter.get("artifact_type") == "customer_letter_external"
        for doc in documents
    ):
        raise RuntimeError("外发版已存在；修改或重新审批前请先按治理流程归档旧外发版。")
    clean_approver = clean_actor(approver, "--approver")
    body = extract_external_body(internal)
    if body is None or not normalize_body(body):
        raise RuntimeError("外发正文标记无效或正文为空。")
    leaks = external_leaks(body)
    if leaks:
        raise RuntimeError("候选外发正文包含禁用内容：" + ", ".join(leaks))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    if not CONTENT_VERSION_RE.fullmatch(data.get("content_version", "")):
        raise RuntimeError("内部稿content_version无效。")
    internal_version = str(int(data["content_version"]) + 1)
    internal_updates = {
        "latest_run_id": run_id,
        "review_status": "approved",
        "content_version": internal_version,
        "updated_at": timestamp,
        "approver": clean_approver,
        "approved_at": timestamp,
        "approved_content_version": internal_version,
        "approved_body_sha256": body_sha256(body),
        "approved_context_sha256": letter_context_sha256(data),
    }
    updated_internal = replace_flat_frontmatter(internal.text, internal_updates)
    updated_internal = append_letter_review_record(
        updated_internal,
        timestamp=timestamp,
        version=internal_version,
        run_id=run_id,
        summary=f"批准内部稿；approver={clean_approver}",
        owner=data["runtime_owner"],
        review_status="approved",
    )
    internal_data = data | internal_updates
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    actions = {"customer_letter_internal": "updated"}
    carrier_for_prefix = {
        "I": "institution_research",
        "L": "leader_research",
        "N": "internal_retrieval",
    }
    for claim_id in set(CLAIM_RE.findall(internal.body)):
        carrier = carrier_for_prefix[claim_id.split("-")[1]]
        if carrier in by_type:
            actions[carrier] = "reused"
    actions = preserve_selected_actions(total, by_type, actions)
    updated_total = update_operation_rows(
        total,
        by_type,
        metadata={"customer_letter_internal": internal_data},
        paths={"customer_letter_internal": internal.path},
        actions=actions,
    )
    total_version = total.frontmatter.get("content_version", "")
    if not CONTENT_VERSION_RE.fullmatch(total_version):
        raise RuntimeError("综合报告content_version无效。")
    next_total_version = str(int(total_version) + 1)
    updated_total = replace_flat_frontmatter(
        updated_total,
        {
            "latest_run_id": run_id,
            "content_version": next_total_version,
            "updated_at": timestamp,
            **readiness_reset_updates(),
        },
    )
    summary = operation_summary(
        total, "approve_internal_letter", actions, data["evidence_cutoff_date"]
    )
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=data["runtime_owner"],
    )
    return commit_mutation(
        {internal.path: updated_internal, total.path: updated_total},
        [],
        internal.path,
        snapshot=snapshot,
        workspace=root,
        operation="approve_letter",
    )


def valid_actor(value: str) -> bool:
    """Reject unusable actor labels; this does not authenticate a person or role."""
    actor = unicodedata.normalize("NFKC", re.sub(r"[|\r\n]+", " ", value)).strip()
    # Ignore trailing label punctuation for this check, not for the stored display value.
    label = actor
    while label and (
        label[-1].isspace() or unicodedata.category(label[-1]).startswith("P")
    ):
        label = label[:-1]
    return (
        1 <= len(actor) <= 100
        and resolved_business_text(actor)
        and not re.search(r"匿名|anonymous|模型", actor, re.IGNORECASE)
        and not re.search(r"机器人|智能体|助手|chatgpt|codex|gemini|claude|deepseek|(?<![a-z])ai(?![a-z])", actor.split("(", 1)[0], re.IGNORECASE)
        and label.casefold()
        not in {
            "销售",
            "领导",
            "审核人",
            "审批人",
            "责任人",
            "负责人",
            "sales",
            "leader",
            "reviewer",
            "approver",
            "ai",
            "model",
        }
    )


def clean_actor(value: str, flag: str) -> str:
    actor = re.sub(r"[|\r\n]+", " ", value).strip()
    if not valid_actor(actor):
        raise RuntimeError(
            f"{flag}必须是1—100字符的非占位、非匿名、非泛化角色的责任人标识。"
        )
    return actor


def actions_with_research_carrier(
    by_type: dict[str, Document],
    primary_type: str,
    primary_action: str,
) -> dict[str, str]:
    actions = {primary_type: primary_action}
    if primary_type not in {
        "institution_research",
        "leader_research",
        "internal_retrieval",
    }:
        for carrier in (
            "institution_research",
            "leader_research",
            "internal_retrieval",
        ):
            document = by_type.get(carrier)
            if (
                document
                and document.frontmatter.get("module_status") == "completed"
                and document.frontmatter.get("freshness_status") == "current"
            ):
                actions[carrier] = "reused"
                break
    return actions


def preserve_selected_actions(
    total: Document,
    by_type: dict[str, Document],
    actions: dict[str, str],
    *,
    excluded: set[str] | None = None,
) -> dict[str, str]:
    preserved = dict(actions)
    excluded = excluded or set()
    for artifact_type, row in parse_status_rows(total).items():
        if (
            len(row) >= 2
            and row[1] == "true"
            and artifact_type in by_type
            and artifact_type not in excluded
            and artifact_type != "customer_letter_external"
        ):
            preserved.setdefault(artifact_type, "reused")
    return preserved


def approve_generic_artifact(
    root: Path,
    documents: list[Document],
    target_name: str,
    reviewer: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    artifact_type = GENERIC_REVIEW_TARGETS[target_name]
    targets = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == artifact_type
    ]
    totals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "comprehensive_report"
    ]
    if len(targets) != 1 or len(totals) != 1:
        raise RuntimeError(f"审批需要且只能有一个{artifact_type}和一个综合报告。")
    target, total = targets[0], totals[0]
    data = target.frontmatter
    if total.frontmatter.get("workflow_stage") not in {"review", "closed"}:
        raise RuntimeError("通用审批只能在workflow_stage=review/closed的上下文执行。")
    if (
        data.get("module_status") != "completed"
        or data.get("review_status") != "pending"
    ):
        raise RuntimeError(
            "只有completed/pending成果可审批；changes_requested必须修改并重新提交为pending。"
        )
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的成果可审批。")
    actor = clean_actor(reviewer, "--reviewer")
    if not CONTENT_VERSION_RE.fullmatch(data.get("content_version", "")):
        raise RuntimeError("待审批成果content_version无效。")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    next_version = str(int(data["content_version"]) + 1)
    updates = {
        "latest_run_id": run_id,
        "review_status": "approved",
        "content_version": next_version,
        "updated_at": timestamp,
        "reviewer": actor,
        "reviewed_at": timestamp,
        "reviewed_content_version": next_version,
        "reviewed_body_sha256": body_sha256(target.body),
    }
    updated_target = replace_flat_frontmatter(target.text, updates)
    target_data = data | updates
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    actions = actions_with_research_carrier(by_type, artifact_type, "updated")
    actions = preserve_selected_actions(total, by_type, actions)
    updated_total = update_operation_rows(
        total,
        by_type,
        metadata={artifact_type: target_data},
        paths={artifact_type: target.path},
        actions=actions,
    )
    total_version = total.frontmatter.get("content_version", "")
    if not CONTENT_VERSION_RE.fullmatch(total_version):
        raise RuntimeError("综合报告content_version无效。")
    next_total_version = str(int(total_version) + 1)
    updated_total = replace_flat_frontmatter(
        updated_total,
        {
            "latest_run_id": run_id,
            "content_version": next_total_version,
            "updated_at": timestamp,
            "workflow_stage": "review",
            **readiness_reset_updates(),
        },
    )
    summary = operation_summary(
        total, f"approve_{target_name}", actions, data["evidence_cutoff_date"]
    )
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=total.frontmatter["runtime_owner"],
    )
    return commit_mutation(
        {target.path: updated_target, total.path: updated_total},
        [],
        target.path,
        snapshot=snapshot,
        workspace=root,
        operation=f"approve_{target_name}",
    )


def begin_letter_revision(
    root: Path, documents: list[Document], reviewer: str, snapshot: WorkspaceSnapshot
) -> Mutation:
    internals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "customer_letter_internal"
    ]
    externals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "customer_letter_external"
    ]
    totals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "comprehensive_report"
    ]
    if len(internals) != 1 or len(externals) != 1 or len(totals) != 1:
        raise RuntimeError("开始修订需要一个内部稿、一个现行外发版和一个综合报告。")
    internal, external, total = internals[0], externals[0], totals[0]
    actor = clean_actor(reviewer, "--reviewer")
    if internal.frontmatter.get("review_status") != "approved":
        raise RuntimeError("只有已有approved外发谱系的内部稿可开始修订。")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    archive_dir = root / "archive" / "letters"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{now:%Y%m%dT%H%M%SZ}-v{external.frontmatter.get('source_internal_content_version', 'unknown')}-{external.path.name}"
    archive_path = archive_dir / archive_name
    if archive_path.exists() or archive_path.is_symlink():
        raise RuntimeError("目标归档文件已存在，拒绝覆盖。")
    data = internal.frontmatter
    next_version = str(int(data["content_version"]) + 1)
    updates = {
        "latest_run_id": run_id,
        "review_status": "changes_requested",
        "content_version": next_version,
        "updated_at": timestamp,
        "external_output_required": "false",
        "approver": "",
        "approved_at": "",
        "approved_content_version": "",
        "approved_body_sha256": "",
        "approved_context_sha256": "",
    }
    updated_internal = replace_flat_frontmatter(internal.text, updates)
    updated_internal = append_letter_review_record(
        updated_internal,
        timestamp=timestamp,
        version=next_version,
        run_id=run_id,
        summary=f"归档现行外发版并开始修订；reviewer={actor}",
        owner=data["runtime_owner"],
        review_status="changes_requested",
    )
    internal_data = data | updates
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    without_external = {
        key: value
        for key, value in by_type.items()
        if key != "customer_letter_external"
    }
    actions = actions_with_research_carrier(
        without_external, "customer_letter_internal", "updated"
    )
    actions = preserve_selected_actions(
        total, without_external, actions, excluded={"customer_letter_external"}
    )
    updated_total = update_operation_rows(
        total,
        without_external,
        metadata={"customer_letter_internal": internal_data},
        paths={"customer_letter_internal": internal.path},
        actions=actions,
    )
    total_version = total.frontmatter.get("content_version", "")
    if not CONTENT_VERSION_RE.fullmatch(total_version):
        raise RuntimeError("综合报告content_version无效。")
    next_total_version = str(int(total_version) + 1)
    updated_total = replace_flat_frontmatter(
        updated_total,
        {
            "latest_run_id": run_id,
            "content_version": next_total_version,
            "updated_at": timestamp,
            "workflow_stage": "review",
            **readiness_reset_updates(),
        },
    )
    summary = operation_summary(
        total, "begin_letter_revision", actions, data["evidence_cutoff_date"]
    )
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=total.frontmatter["runtime_owner"],
    )
    planned = {
        internal.path: updated_internal,
        total.path: updated_total,
        archive_path: external.text,
    }
    return commit_mutation(
        planned,
        [archive_path],
        internal.path,
        deleted=[external.path],
        snapshot=snapshot,
        workspace=root,
        operation="begin_letter_revision",
    )


def mark_ready_for_use(
    root: Path, documents: list[Document], reviewer: str, snapshot: WorkspaceSnapshot
) -> Mutation:
    totals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "comprehensive_report"
    ]
    if len(totals) != 1:
        raise RuntimeError("就绪审批需要且只能有一个综合报告。")
    total = totals[0]
    actor = clean_actor(reviewer, "--reviewer")
    if (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("freshness_status") != "current"
    ):
        raise RuntimeError("ready_for_use审批前综合报告必须completed/current。")
    if total.frontmatter.get("workflow_stage") not in {"output", "review", "closed"}:
        raise RuntimeError("ready_for_use审批只能在output/review/closed阶段执行。")
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    rows = parse_status_rows(total)
    selected = {key for key, row in rows.items() if len(row) >= 2 and row[1] == "true"}
    for artifact_type in selected & (
        GENERIC_REVIEW_TYPES | {"customer_letter_internal"}
    ):
        artifact = by_type.get(artifact_type)
        if artifact is None or artifact.frontmatter.get("review_status") != "approved":
            raise RuntimeError(
                f"{artifact_type}未完成approved审核，不得标记ready_for_use。"
            )
    actions = {
        artifact_type: "reused"
        for artifact_type in selected
        if artifact_type in by_type and artifact_type != "customer_letter_external"
    }
    if total.frontmatter.get("route") in {"visit_prep", "strategy", "letter"} and not (
        actions.keys()
        & {"institution_research", "leader_research", "internal_retrieval"}
    ):
        actions.update(
            actions_with_research_carrier(by_type, "comprehensive_report", "not_called")
        )
        actions.pop("comprehensive_report", None)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    updated_total = update_operation_rows(
        total, by_type, metadata={}, paths={}, actions=actions
    )
    total_version = total.frontmatter.get("content_version", "")
    if not CONTENT_VERSION_RE.fullmatch(total_version):
        raise RuntimeError("综合报告content_version无效。")
    next_total_version = str(int(total_version) + 1)
    updated_total = replace_flat_frontmatter(
        updated_total,
        {
            "latest_run_id": run_id,
            "content_version": next_total_version,
            "updated_at": timestamp,
            **readiness_reset_updates(),
        },
    )
    summary = operation_summary(
        total, "mark_ready_for_use", actions, total.frontmatter["evidence_cutoff_date"]
    )
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=total.frontmatter["runtime_owner"],
    )
    # The readiness signature must cover the exact body that will be
    # committed.  append_operation_record() mutates that body, so signing
    # before appending would create an immediately stale approval stamp.
    readiness_digest = body_sha256(body_from_text(updated_total))
    updated_total = replace_flat_frontmatter(
        updated_total,
        {
            "ready_for_use": "true",
            "readiness_reviewer": actor,
            "readiness_reviewed_at": timestamp,
            "readiness_content_version": next_total_version,
            "readiness_body_sha256": readiness_digest,
        },
    )
    return commit_mutation(
        {total.path: updated_total},
        [],
        total.path,
        snapshot=snapshot,
        workspace=root,
        operation="mark_ready",
        strict_postflight=True,
    )


def emit_external(
    root: Path, documents: list[Document], snapshot: WorkspaceSnapshot
) -> Mutation:
    internals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "customer_letter_internal"
    ]
    totals = [
        doc
        for doc in documents
        if doc.frontmatter.get("artifact_type") == "comprehensive_report"
    ]
    if len(internals) != 1 or len(totals) != 1:
        raise RuntimeError(
            "--emit-external需要且只能有一个客户信内部审核稿和一个综合报告。"
        )
    internal, total = internals[0], totals[0]
    data = internal.frontmatter
    if total.frontmatter.get("route") != "letter" or total.frontmatter.get(
        "workflow_stage"
    ) not in {"review", "closed"}:
        raise RuntimeError(
            "外发生成只能在route=letter且workflow_stage=review/closed的上下文执行。"
        )
    if (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("freshness_status") != "current"
    ):
        raise RuntimeError("外发生成前综合报告必须completed/current。")
    if (
        data.get("module_status") != "completed"
        or data.get("review_status") != "approved"
    ):
        raise RuntimeError("只有completed/approved的内部稿可抽取外发版。")
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的内部稿可抽取外发版。")
    body = extract_external_body(internal)
    if body is None or not normalize_body(body):
        raise RuntimeError("外发正文标记无效或正文为空。")
    if data.get("approved_body_sha256") != body_sha256(body) or data.get(
        "approved_content_version"
    ) != data.get("content_version"):
        raise RuntimeError("审批戳与当前正文或版本不一致，必须重新审核。")
    leaks = external_leaks(body)
    if leaks:
        raise RuntimeError("候选外发正文包含禁用内容：" + ", ".join(leaks))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    internal_version = str(int(data["content_version"]) + 1)
    internal_updates = {
        "latest_run_id": run_id,
        "content_version": internal_version,
        "updated_at": timestamp,
        "external_output_required": "true",
        "approved_content_version": internal_version,
    }
    updated_internal = replace_flat_frontmatter(internal.text, internal_updates)
    updated_internal = append_letter_review_record(
        updated_internal,
        timestamp=timestamp,
        version=internal_version,
        run_id=run_id,
        summary="生成客户信外发版；已批准正文与业务上下文保持不变",
        owner=data["runtime_owner"],
        review_status="approved",
    )
    internal_data = data | internal_updates
    filename = f"{data['safe_name']}{SUFFIXES['customer_letter_external']}"
    target = root / filename
    if target.resolve().parent != root.resolve() or target.is_symlink():
        raise RuntimeError("外发版路径越出工作目录或为符号链接。")
    if target.exists():
        raise RuntimeError("外发版已存在；为避免覆盖已审核文件，请先归档旧版后再生成。")
    external_data = {
        "schema": SCHEMA,
        "artifact_type": "customer_letter_external",
        "context_id": data["context_id"],
        "latest_run_id": run_id,
        "customer_id": data["customer_id"],
        "customer_display_name": data["customer_display_name"],
        "organization_scope": data["organization_scope"],
        "safe_name": data["safe_name"],
        "module_status": "completed",
        "review_status": "approved",
        "connector_status": "not_applicable",
        "freshness_status": "current",
        "content_version": "1",
        "evidence_cutoff_date": data["evidence_cutoff_date"],
        "updated_at": timestamp,
        "runtime_owner": data["runtime_owner"],
        "approver": data["approver"],
        "approved_at": data["approved_at"],
        "approved_content_version": internal_version,
        "approved_body_sha256": data["approved_body_sha256"],
        "approved_context_sha256": data["approved_context_sha256"],
        "source_internal_content_version": internal_version,
    }
    fields = [yaml_line(key, value) for key, value in external_data.items()]
    external_text = (
        "---\n"
        + "\n".join(fields)
        + "\n---\n\n"
        + f"# {data['customer_display_name']}客户信（外发版）\n\n"
        + canonical_approved_body(body)
        + "\n"
    )
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    actions = {
        "customer_letter_internal": "updated",
        "customer_letter_external": "generated",
    }
    carrier_for_prefix = {
        "I": "institution_research",
        "L": "leader_research",
        "N": "internal_retrieval",
    }
    for claim_id in set(CLAIM_RE.findall(internal.body)):
        carrier = carrier_for_prefix[claim_id.split("-")[1]]
        if carrier in by_type:
            actions[carrier] = "reused"
    actions = preserve_selected_actions(total, by_type, actions)
    if not (
        actions.keys()
        & {"institution_research", "leader_research", "internal_retrieval"}
    ):
        raise RuntimeError("外发运行缺少可复用的current研究台账载体。")
    updated_total = update_operation_rows(
        total,
        by_type,
        metadata={
            "customer_letter_internal": internal_data,
            "customer_letter_external": external_data,
        },
        paths={
            "customer_letter_internal": internal.path,
            "customer_letter_external": target,
        },
        actions=actions,
    )
    total_version = total.frontmatter.get("content_version", "")
    if not CONTENT_VERSION_RE.fullmatch(total_version):
        raise RuntimeError("综合报告content_version无效。")
    next_total_version = str(int(total_version) + 1)
    updated_total = replace_flat_frontmatter(
        updated_total,
        {
            "latest_run_id": run_id,
            "content_version": next_total_version,
            "updated_at": timestamp,
            **readiness_reset_updates(),
        },
    )
    summary = operation_summary(
        total, "generate_external", actions, data["evidence_cutoff_date"]
    )
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=data["runtime_owner"],
    )
    return commit_mutation(
        {
            internal.path: updated_internal,
            total.path: updated_total,
            target: external_text,
        },
        [target],
        target,
        snapshot=snapshot,
        workspace=root,
        operation="emit_external",
    )


DEFAULT_TTL_DAYS = {
    "comprehensive_report": 7,
    "institution_research": 30,
    "leader_research": 14,
    "internal_retrieval": 7,
    "visit_strategy": 7,
    "customer_letter_internal": 3,
    "customer_letter_external": 3,
}


def validate_runtime_manifest(
    root: Path,
    by_type: dict[str, Document],
    issues: list[Issue],
    strict: bool,
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    manifest_path = root / MANIFEST_REL
    if not manifest_path.exists():
        severity = "error" if strict else "warning"
        add(
            issues,
            severity,
            "runtime_manifest_missing",
            root,
            "缺少机器权威runtime/manifest.json；旧工作区应先安全续建迁移。",
        )
        return
    try:
        manifest = load_manifest(root)
    except (OSError, UnicodeError, TxError) as exc:
        add(issues, "error", "runtime_manifest_invalid", manifest_path, str(exc))
        return
    assert manifest is not None
    data = total.frontmatter
    top_level = {
        "context_id": data.get("context_id", ""),
        "customer_id": data.get("customer_id", ""),
        "customer_display_name": data.get("customer_display_name", ""),
        "organization_scope": data.get("organization_scope", ""),
        "business_mode": data.get("business_mode", ""),
        "route": data.get("route", ""),
        "depth": data.get("depth", ""),
        "latest_run_id": data.get("latest_run_id", ""),
        "content_version": data.get("content_version", ""),
        "stage": data.get("workflow_stage", ""),
    }
    for key, expected in top_level.items():
        if str(manifest.get(key, "")) != expected:
            add(
                issues,
                "error",
                "runtime_manifest_drift",
                manifest_path,
                f"{key}与综合报告不一致。",
            )
    expected_ready = data.get("ready_for_use", "false") == "true"
    if manifest.get("ready_for_use") is not expected_ready:
        add(
            issues,
            "error",
            "runtime_manifest_ready_drift",
            manifest_path,
            "ready_for_use与综合报告不一致。",
        )
    records = manifest.get("artifacts")
    if not isinstance(records, dict):
        add(
            issues,
            "error",
            "runtime_manifest_artifacts_invalid",
            manifest_path,
            "artifacts必须为对象。",
        )
        return
    for artifact_type, document in by_type.items():
        record = records.get(artifact_type)
        if not isinstance(record, dict):
            add(
                issues,
                "error",
                "runtime_manifest_artifact_missing",
                manifest_path,
                f"缺少成果记录：{artifact_type}。",
            )
            continue
        if record.get("path") != document.path.name or record.get(
            "sha256"
        ) != sha256_file(document.path):
            add(
                issues,
                "error",
                "runtime_manifest_artifact_drift",
                document.path,
                "成果路径或SHA-256与机器清单不一致；禁止绕过事务直接修改。",
            )
        state = record.get("state")
        if not isinstance(state, dict):
            add(
                issues,
                "error",
                "runtime_manifest_state_invalid",
                manifest_path,
                f"{artifact_type}.state无效。",
            )
        else:
            for field in (
                "module_status",
                "review_status",
                "connector_status",
                "freshness_status",
            ):
                if state.get(field) != document.frontmatter.get(field, ""):
                    add(
                        issues,
                        "error",
                        "runtime_manifest_state_drift",
                        document.path,
                        f"{field}与机器清单不一致。",
                    )
        for field in ("content_version", "latest_run_id"):
            if str(record.get(field, "")) != document.frontmatter.get(field, ""):
                add(
                    issues,
                    "error",
                    "runtime_manifest_version_drift",
                    document.path,
                    f"{field}与机器清单不一致。",
                )
    extras = set(records) - set(by_type)
    if extras:
        add(
            issues,
            "error",
            "runtime_manifest_phantom_artifact",
            manifest_path,
            "清单登记了不存在的根成果：" + ", ".join(sorted(extras)),
        )

    rows = parse_status_rows(total)
    expected_modules = sorted(
        MODULE_NAME_FOR_TYPE[artifact_type]
        for artifact_type, row in rows.items()
        if artifact_type in MODULE_NAME_FOR_TYPE and len(row) >= 2 and row[1] == "true"
    )
    actual_modules = manifest.get("selected_modules")
    if (
        not isinstance(actual_modules, list)
        or sorted(str(item) for item in actual_modules) != expected_modules
    ):
        add(
            issues,
            "error",
            "runtime_manifest_selection_drift",
            manifest_path,
            "selected_modules与综合报告本轮登记不一致。",
        )

    internal = by_type.get("internal_retrieval")
    if internal is None:
        return
    connector_status = internal.frontmatter.get("connector_status", "")
    if connector_status in {"not_applicable", "not_configured"}:
        return
    evidence_path = root / "runtime" / "evidence-manifest.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        add(
            issues,
            "error",
            "connector_audit_missing",
            evidence_path,
            f"连接状态{connector_status}必须有真实调用审计：{exc}",
        )
        return
    audit = evidence.get("connector_audit") if isinstance(evidence, dict) else None
    if not isinstance(audit, dict) or audit.get("status") != connector_status:
        add(
            issues,
            "error",
            "connector_audit_status_drift",
            evidence_path,
            "connector_audit.status与内部检索成果不一致。",
        )
        return
    authorization = (
        manifest.get("authorization")
        if isinstance(manifest.get("authorization"), dict)
        else {}
    )
    for field in (
        "connector_id",
        "call_id",
        "called_at",
        "tenant_id",
        "customer_id",
        "project_id",
        "authorization_owner",
        "authorization_expires_at",
    ):
        if not str(audit.get(field) or "").strip():
            add(
                issues,
                "error",
                "connector_audit_field_missing",
                evidence_path,
                f"真实调用审计缺少{field}。",
            )
    for field in (
        "tenant_id",
        "customer_id",
        "project_id",
        "authorization_owner",
        "authorization_expires_at",
    ):
        if str(audit.get(field) or "") != str(authorization.get(field) or ""):
            add(
                issues,
                "error",
                "connector_audit_scope_drift",
                evidence_path,
                f"{field}与运行授权不一致。",
            )
    allowed_projects = audit.get("allowed_project_ids")
    authorized_projects = authorization.get("allowed_project_ids")
    if (
        not isinstance(allowed_projects, list)
        or audit.get("project_id") not in allowed_projects
    ):
        add(
            issues,
            "error",
            "connector_project_not_allowed",
            evidence_path,
            "connector_audit.allowed_project_ids必须包含本轮project_id。",
        )
    elif isinstance(authorized_projects, list) and sorted(
        map(str, allowed_projects)
    ) != sorted(map(str, authorized_projects)):
        add(
            issues,
            "error",
            "connector_allowlist_drift",
            evidence_path,
            "调用审计项目白名单与运行授权不一致。",
        )
    if connector_status in {"connected", "no_hits"}:
        if not str(audit.get("response_fingerprint") or "").strip():
            add(
                issues,
                "error",
                "connector_audit_field_missing",
                evidence_path,
                "真实调用审计缺少response_fingerprint。",
            )
        if (
            audit.get("server_filter_verified") is not True
            or audit.get("response_scope_verified") is not True
        ):
            add(
                issues,
                "error",
                "connector_scope_unverified",
                evidence_path,
                "服务端三重过滤和返回范围必须均经验证。",
            )
    expiry = parse_expiry(str(audit.get("authorization_expires_at") or ""))
    if expiry is None or expiry <= datetime.now(timezone.utc):
        add(
            issues,
            "error",
            "connector_authorization_expired",
            evidence_path,
            "连接器调用授权无效或已过期。",
        )


BRIEFING_START = "<!-- briefing:start -->"
BRIEFING_END = "<!-- briefing:end -->"


def briefing_body(total: Document) -> str:
    """Only this total-body section is eligible for a briefing export."""
    text = total.body
    if text.count(BRIEFING_START) != 1 or text.count(BRIEFING_END) != 1:
        raise ValueError("速览必须恰有一对 briefing:start/end 标记。")
    start = text.index(BRIEFING_START) + len(BRIEFING_START)
    end = text.index(BRIEFING_END)
    if end <= start or not text[start:end].strip():
        raise ValueError("速览交付区为空或标记顺序错误。")
    return text[start:end].strip()


def briefing_lines(body: str) -> list[str]:
    """Bound a plain-text A4 export without clipping or silently truncating it."""
    if len(body) > 1600:
        raise ValueError("速览正文超过1600字符。")
    lines: list[str] = []
    for raw in body.expandtabs(4).splitlines():
        text, width = "", 0
        for char in raw:
            if unicodedata.category(char).startswith("C"):
                raise ValueError("速览正文含不支持的控制字符。")
            cells = 2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1
            if width + cells > 72:
                lines.append(text)
                text, width = "", 0
            text += char
            width += cells
        lines.append(text)
    if len(lines) > 48:
        raise ValueError("速览折行后超过48行，请缩减正文；不得裁切内容。")
    return lines


def validate_briefing_content(body: str) -> None:
    """Minimum delivery contract; not semantic fact verification or approval."""
    headings = ("一句话判断", "会前必须知道", "机会与边界", "建议交流节奏",
                "三个现场问题", "最小推进动作", "未决风险")
    sections = {}
    active = None
    for line in markdown_without_fenced_code(body).splitlines():
        if line.startswith("## "):
            active = line[3:].strip()
            if active in sections:
                raise ValueError("速览章节重复：" + active)
            sections[active] = []
        elif active:
            sections[active].append(line)
    for heading in headings:
        if not "".join(sections.get(heading, [])).strip():
            raise ValueError("速览缺少实质内容：" + heading)
    questions = sections["三个现场问题"]
    if len([line for line in questions if re.match(r"^\s*[1-3][.、]\s*\S", line)]) != 3:
        raise ValueError("速览必须有三个编号现场问题。")
    agenda = "\n".join(sections["建议交流节奏"])
    if not re.search(r"[0-9]+\s*[—–~-]\s*[0-9]+\s*分钟", agenda):
        raise ValueError("速览缺少时间化交流节奏。")
    action = "\n".join(sections["最小推进动作"])
    if len(re.findall(r"(?:^|[\n；;])\s*[-* ]*(?:\*\*)?动作[：:]", action)) != 1:
        raise ValueError("速览必须标明唯一动作。")
    owner = re.search(r"Owner[：:]\s*(?:\*\*)?\s*([^\n；;]+?)(?=\s*(?:Due date|due_date)|$|[\n；;])", action, re.I)
    date = re.search(r"(?:Due date|due_date)[：:]\s*(?:\*\*)?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", action, re.I)
    if not owner or not valid_actor(owner.group(1).strip(" *　")) or not date or not date_valid(date.group(1)):
        raise ValueError("速览动作须有可归因Owner与有效Due date。")
    if not re.search(r"红线[：:]\s*\S", action):
        raise ValueError("速览缺少明确红线。")


def delivery_table_rows(body: str, prefix: list[str]) -> list[list[str]]:
    """Read real Markdown table rows, never examples inside fenced code."""
    rows: list[list[str]] = []
    active = False
    for line in markdown_without_fenced_code(body).splitlines():
        if not line.strip().startswith("|"):
            active = False
            continue
        cells = split_table_cells(line)
        if cells[: len(prefix)] == prefix:
            active = True
        elif active and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            rows.append(cells)
    return rows


def validate_delivery_contract(
    by_type: dict[str, Document], issues: list[Issue]
) -> None:
    total = by_type["comprehensive_report"]
    owners = [
        row
        for row in delivery_table_rows(total.body, ["角色", "姓名（稳定角色/账号）"])
        if row and row[0] == "account_owner"
    ]
    if len(owners) != 1 or len(owners[0]) < 2 or not valid_actor(owners[0][1]):
        add(
            issues,
            "error",
            "account_owner_required",
            total.path,
            "RACI必须登记唯一可归因的account_owner。",
        )
    mode = total.frontmatter.get("business_mode", "")
    targets = [total]
    if (
        mode in {"briefing", "standard_visit", "strategic_account"}
        and "visit_strategy" in by_type
    ):
        targets.append(by_type["visit_strategy"])
    for document in targets:
        rows = delivery_table_rows(document.body, ["action", "owner", "due_date"])
        if (
            len(rows) != 1
            or len(rows[0]) < 3
            or not rows[0][0].strip()
            or rows[0][0] in {"无", "待确认", "待补充"}
            or not valid_actor(rows[0][1])
            or not date_valid(rows[0][2])
        ):
            add(
                issues,
                "error",
                "main_action_required",
                document.path,
                "须有唯一主动作表：action、可归因owner、有效YYYY-MM-DD due_date；no_go可写停止投入或复核动作。",
            )
    if mode == "briefing":
        try:
            body = briefing_body(total)
            briefing_lines(body)
            validate_briefing_content(body)
        except ValueError as exc:
            add(issues, "error", "briefing_body_required", total.path, str(exc))
        else:
            if not CLAIM_RE.search(body):
                add(
                    issues,
                    "error",
                    "briefing_evidence_required",
                    total.path,
                    "速览正文必须含可回溯的claim_id。",
                )


def validate_operating_governance(
    by_type: dict[str, Document],
    issues: list[Issue],
    strict: bool,
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    data = total.frontmatter
    business_mode = data.get("business_mode", "")
    if business_mode and business_mode not in BUSINESS_MODES:
        add(
            issues,
            "error",
            "business_mode_invalid",
            total.path,
            f"business_mode必须为{sorted(BUSINESS_MODES)}。",
        )
    if strict and not business_mode:
        add(
            issues,
            "error",
            "business_mode_required",
            total.path,
            "严格交付必须通过四种业务模式之一启动。",
        )
    try:
        profiles = load_business_profiles()
    except RuntimeError as exc:
        cause = exc.__cause__
        detail = f"{exc}"
        if cause is not None:
            detail += f" [cause: {type(cause).__name__}: {cause}]"
        add(issues, "error", "business_config_read_error", total.path, detail)
        return
    profile = profiles.get(business_mode, {}) if business_mode else {}
    if isinstance(profile, dict) and data.get("route") != "refresh":
        expected_route = str(profile.get("route", ""))
        expected_depth = str(profile.get("depth", ""))
        if expected_route and data.get("route") != expected_route:
            add(
                issues,
                "error",
                "business_mode_route_mismatch",
                total.path,
                f"{business_mode}必须映射route={expected_route}。",
            )
        if expected_depth and data.get("depth") != expected_depth:
            add(
                issues,
                "error",
                "business_mode_depth_mismatch",
                total.path,
                f"{business_mode}必须映射depth={expected_depth}。",
            )

    ready = data.get("ready_for_use", "false")
    if ready not in {"true", "false"}:
        add(
            issues,
            "error",
            "ready_for_use_invalid",
            total.path,
            "ready_for_use必须为true或false。",
        )
    if strict and ready != "true":
        add(
            issues,
            "error",
            "ready_for_use_required",
            total.path,
            "严格交付前必须完成独立就绪门禁并设置ready_for_use=true。",
        )

    internal = by_type.get("internal_retrieval")
    status_rows = parse_status_rows(total)
    if (
        isinstance(profile, dict)
        and data.get("route") != "refresh"
        and (strict or ready == "true")
    ):
        selected_names = {
            MODULE_NAME_FOR_TYPE[artifact_type]
            for artifact_type, row in status_rows.items()
            if artifact_type in MODULE_NAME_FOR_TYPE
            and len(row) >= 2
            and row[1] == "true"
        }
        required_names = {
            str(value) for value in profile.get("modules", []) if isinstance(value, str)
        }
        missing_required = sorted(required_names - selected_names)
        if missing_required:
            add(
                issues,
                "error",
                "business_mode_module_missing",
                total.path,
                "当前业务模式缺少必需成果：" + ", ".join(missing_required),
            )
    internal_row = status_rows.get("internal_retrieval", [])
    internal_selected = len(internal_row) >= 2 and internal_row[1] == "true"
    authorization_required = bool(
        internal_selected
        or (internal and internal.frontmatter.get("connector_status") == "connected")
    )
    if authorization_required:
        missing = sorted(
            field for field in AUTHORIZATION_FIELDS if not data.get(field, "").strip()
        )
        if missing:
            add(
                issues,
                "error",
                "authorization_required",
                total.path,
                "缺少稳定租户/项目授权字段：" + ", ".join(missing),
            )
        for field in ("tenant_id", "project_id"):
            value = data.get(field, "")
            if value and not IDENTIFIER_RE.fullmatch(value):
                add(
                    issues,
                    "error",
                    "authorization_id_invalid",
                    total.path,
                    f"{field}必须是稳定标识符。",
                )
        owner = data.get("authorization_owner", "")
        if owner in {"", "待确认", "待指定"}:
            add(
                issues,
                "error",
                "authorization_owner_unassigned",
                total.path,
                "授权必须绑定实名责任人或稳定责任角色。",
            )
        expiry = parse_expiry(data.get("authorization_expires_at", ""))
        if expiry is None:
            add(
                issues,
                "error",
                "authorization_expiry_invalid",
                total.path,
                "authorization_expires_at必须为日期或带时区ISO 8601时间。",
            )
        elif expiry <= datetime.now(timezone.utc):
            add(
                issues,
                "error",
                "authorization_expired",
                total.path,
                "租户/项目授权已过期，不得继续检索或交付。",
            )

    # One explicit context calendar governs both future dates and TTL ages.
    # v2.5 totals without this optional field retain UTC, not the host timezone.
    task_timezone = data.get("task_timezone", "UTC")
    try:
        task_zone = timezone.utc if task_timezone == "UTC" else ZoneInfo(task_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        add(
            issues,
            "error",
            "task_timezone_invalid",
            total.path,
            f"task_timezone必须是有效IANA时区：{exc}",
        )
        return
    today = datetime.now(task_zone).date()
    profile_ttl = profile.get("ttl_days", {}) if isinstance(profile, dict) else {}
    for artifact_type, document in by_type.items():
        if document.frontmatter.get("task_timezone", task_timezone) != task_timezone:
            add(
                issues,
                "error",
                "task_timezone_mismatch",
                document.path,
                "成果task_timezone与综合报告不一致；不得覆盖任务时区。",
            )
        cutoff_text = document.frontmatter.get("evidence_cutoff_date", "")
        if not date_valid(cutoff_text):
            continue
        cutoff = date.fromisoformat(cutoff_text)
        if cutoff > today:
            add(
                issues,
                "error",
                "evidence_cutoff_in_future",
                document.path,
                "evidence_cutoff_date不得晚于当前日期。",
            )
            continue
        ttl = DEFAULT_TTL_DAYS.get(artifact_type, 7)
        if isinstance(profile_ttl, dict):
            ttl_key = {
                "institution_research": "institution",
                "leader_research": "leader",
                "internal_retrieval": "internal",
                "visit_strategy": "strategy",
                "customer_letter_internal": "letter",
                "customer_letter_external": "letter",
                "comprehensive_report": "total",
            }.get(artifact_type, "")
            candidate = profile_ttl.get(ttl_key) if ttl_key else None
            if isinstance(candidate, int) and candidate > 0:
                ttl = candidate
        if document.frontmatter.get(
            "freshness_status"
        ) == "current" and today - cutoff > timedelta(days=ttl):
            severity = (
                "error"
                if strict or data.get("workflow_stage") in {"review", "closed"}
                else "warning"
            )
            add(
                issues,
                severity,
                "freshness_ttl_exceeded",
                document.path,
                f"该类信息TTL为{ttl}天；应标记stale并刷新或移除依赖。",
            )

    if ready == "true":
        readiness = {field: data.get(field, "") for field in READINESS_FIELDS}
        missing_readiness = sorted(
            field for field, value in readiness.items() if not value.strip()
        )
        if missing_readiness:
            add(
                issues,
                "error",
                "readiness_audit_required",
                total.path,
                "ready_for_use缺少审批审计字段：" + ", ".join(missing_readiness),
            )
        if not valid_actor(readiness["readiness_reviewer"]):
            add(
                issues,
                "error",
                "readiness_reviewer_unassigned",
                total.path,
                "ready_for_use必须绑定实名审核人或稳定审核角色。",
            )
        if not timestamp_valid(readiness["readiness_reviewed_at"]):
            add(
                issues,
                "error",
                "readiness_time_invalid",
                total.path,
                "readiness_reviewed_at必须为带时区ISO 8601时间。",
            )
        if readiness["readiness_content_version"] != data.get("content_version"):
            add(
                issues,
                "error",
                "readiness_version_drift",
                total.path,
                "readiness_content_version必须等于综合报告content_version。",
            )
        if readiness["readiness_body_sha256"] != body_sha256(total.body):
            add(
                issues,
                "error",
                "readiness_body_drift",
                total.path,
                "ready_for_use后综合报告正文已变化，必须重新执行就绪审批。",
            )
        if (
            data.get("module_status") != "completed"
            or data.get("freshness_status") != "current"
        ):
            add(
                issues,
                "error",
                "ready_state_conflict",
                total.path,
                "ready_for_use=true要求综合报告completed/current。",
            )
        if data.get("runtime_owner") in {"", "待确认", "待指定"}:
            add(
                issues,
                "error",
                "ready_owner_missing",
                total.path,
                "ready_for_use=true前必须绑定runtime_owner。",
            )
        rows = parse_status_rows(total)
        selected = {
            key for key, row in rows.items() if len(row) >= 2 and row[1] == "true"
        }
        for artifact_type in selected & (
            GENERIC_REVIEW_TYPES | {"customer_letter_internal"}
        ):
            artifact = by_type.get(artifact_type)
            if (
                artifact is not None
                and artifact.frontmatter.get("review_status") != "approved"
            ):
                add(
                    issues,
                    "error",
                    "ready_review_missing",
                    artifact.path,
                    "选中成果未完成独立审核，不能标记ready_for_use。",
                )
    elif any(data.get(field, "").strip() for field in READINESS_FIELDS):
        add(
            issues,
            "error",
            "stale_readiness_metadata",
            total.path,
            "ready_for_use=false时必须清空旧就绪审批戳。",
        )

    if strict or ready == "true":
        validate_delivery_contract(by_type, issues)
    if (strict or ready == "true") and business_mode in {
        "standard_visit",
        "strategic_account",
    }:
        strategy = by_type.get("visit_strategy")
        if strategy is not None:
            account_plan = business_mode == "strategic_account" and bool(
                re.search(r"(?m)^## 账户经营计划\s*$", strategy.body)
            )
            required_sections = (
                (
                    "机会资格",
                    "账户经营计划",
                    "经营周期",
                    "验证责任",
                    "复核动作",
                    "停止条件",
                    "CRM/PIMS",
                )
                if account_plan
                else (
                    "机会资格",
                    "议程",
                    "参会分工",
                    "材料与演示计划",
                    "会后行动",
                    "CRM/PIMS",
                )
            )
            missing_sections = [
                section for section in required_sections if section not in strategy.body
            ]
            if missing_sections:
                add(
                    issues,
                    "error",
                    "presales_loop_incomplete",
                    strategy.path,
                    "售前闭环缺少章节：" + ", ".join(missing_sections),
                )


def validate_loaded(
    root: Path,
    documents: list[Document],
    issues: list[Issue],
    strict: bool,
    recovery_preflight: bool = False,
) -> None:
    for document in documents:
        validate_frontmatter(document, issues, False if recovery_preflight else strict)
    by_type = validate_filenames_and_identity(documents, root, issues)
    if recovery_preflight:
        return
    claims, sources = collect_ledgers(documents, issues)
    validate_claim_graph(documents, claims, sources, issues)
    validate_status_sync(by_type, issues, strict)
    validate_letter_review_history(by_type, issues, strict)
    validate_run_history(by_type, issues)
    validate_refresh_ledger(by_type, claims, sources, issues, strict)
    validate_route_gate(by_type, issues, strict)
    validate_operating_governance(by_type, issues, strict)
    validate_runtime_manifest(root, by_type, issues, strict)
    validate_links(documents, root, issues)
    validate_letter_isolation(by_type, issues)


def validate(
    root: Path,
    strict: bool,
    emit: bool,
    approve: bool = False,
    approver: str | None = None,
    *,
    approve_artifact: str | None = None,
    reviewer: str | None = None,
    begin_revision: bool = False,
    mark_ready: bool = False,
    recovery_preflight: bool = False,
) -> tuple[list[Issue], list[Document], Path | None, str | None]:
    issues: list[Issue] = []
    documents = load_documents(root, issues)
    mutating = emit or approve or bool(approve_artifact) or begin_revision or mark_ready
    validate_loaded(
        root, documents, issues, strict if not mutating else False, recovery_preflight
    )
    result_path: Path | None = None
    operation: str | None = "recovery_preflight" if recovery_preflight else None
    if mutating:
        ignored_codes = {"external_letter_required"} if emit else set()
        blocking = [
            issue
            for issue in issues
            if issue.severity == "error" and issue.code not in ignored_codes
        ]
        if blocking:
            add(
                issues,
                "error",
                "operation_preflight_failed",
                root,
                "现有成果校验未通过，未执行治理状态变更。",
            )
            return issues, documents, None, None
        try:
            snapshot = capture_workspace_snapshot(root, documents)
            if emit:
                mutation = emit_external(root, documents, snapshot)
                operation = "emit_external"
            elif approve:
                mutation = approve_internal(root, documents, approver or "", snapshot)
                operation = "approve_letter"
            elif approve_artifact:
                mutation = approve_generic_artifact(
                    root, documents, approve_artifact, reviewer or "", snapshot
                )
                operation = f"approve_{approve_artifact}"
            elif begin_revision:
                mutation = begin_letter_revision(
                    root, documents, reviewer or "", snapshot
                )
                operation = "begin_letter_revision"
            else:
                mutation = mark_ready_for_use(root, documents, reviewer or "", snapshot)
                operation = "mark_ready"
        except (KeyError, OSError, RuntimeError, UnicodeError) as exc:
            add(issues, "error", "operation_failed", root, str(exc))
            return issues, documents, None, None
        post_issues: list[Issue] = []
        post_documents = load_documents(root, post_issues)
        validate_loaded(root, post_documents, post_issues, mark_ready)
        if any(issue.severity == "error" for issue in post_issues):
            if mutation.transactional:
                add(
                    post_issues,
                    "error",
                    "transaction_postflight_inconsistent",
                    root,
                    "事务内复检与提交后复检结果不一致；停止后续操作并保留机器审计。",
                )
                return post_issues, post_documents, None, None
            try:
                rollback_mutation(mutation)
            except (OSError, UnicodeError) as exc:
                add(
                    post_issues,
                    "error",
                    "transaction_rollback_failed",
                    root,
                    f"提交后校验失败且回滚不完整：{exc}",
                )
                return post_issues, post_documents, None, None
            add(
                post_issues,
                "error",
                "operation_postflight_failed",
                root,
                "变更后完整校验失败，已恢复全部文件。",
            )
            return post_issues, documents, None, None
        issues, documents = post_issues, post_documents
        result_path = mutation.result_path
    return issues, documents, result_path, operation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验discovery-call v2.6成果契约，并执行可审计审批、就绪和客户信修订。"
    )
    parser.add_argument("workspace", type=Path, help="客户研究工作目录")
    parser.add_argument(
        "--strict", action="store_true", help="最终交付校验：拒绝占位符及本轮非终态模块"
    )
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument(
        "--approve-letter",
        action="store_true",
        help="为pending内部稿写入审核人、版本和正文哈希审批戳",
    )
    operations.add_argument(
        "--emit-external",
        action="store_true",
        help="从带有效审批戳的approved内部稿事务生成纯净外发版",
    )
    operations.add_argument(
        "--approve-artifact",
        choices=sorted(GENERIC_REVIEW_TARGETS),
        help="审批人物、内部检索或策略成果",
    )
    operations.add_argument(
        "--begin-letter-revision",
        action="store_true",
        help="归档现行外发版并事务开启新一轮客户信修订",
    )
    operations.add_argument(
        "--mark-ready",
        action="store_true",
        help="完成最终独立就绪审批并设置ready_for_use=true",
    )
    operations.add_argument(
        "--recovery-preflight",
        action="store_true",
        help="仅做恢复安全预检，允许模块与总报告暂时不同步",
    )
    parser.add_argument(
        "--approver", help="与--approve-letter配合使用的审核人或审核角色"
    )
    parser.add_argument(
        "--reviewer",
        help="与--approve-artifact、--begin-letter-revision或--mark-ready配合的责任人/稳定角色",
    )
    parser.add_argument("--json", action="store_true", help="输出JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    expanded_root = args.workspace.expanduser()
    if expanded_root.is_symlink():
        print(f"ERROR: 工作目录不得为符号链接：{expanded_root}", file=sys.stderr)
        return 2
    root = expanded_root.resolve()
    if not root.is_dir():
        print(f"ERROR: 工作目录不存在：{root}", file=sys.stderr)
        return 2
    if args.approve_letter and not args.approver:
        print("ERROR: --approve-letter 必须同时提供 --approver。", file=sys.stderr)
        return 2
    if args.approver and not args.approve_letter:
        print("ERROR: --approver 只能与 --approve-letter 一起使用。", file=sys.stderr)
        return 2
    reviewer_operation = bool(
        args.approve_artifact or args.begin_letter_revision or args.mark_ready
    )
    if reviewer_operation and not args.reviewer:
        print("ERROR: 该治理操作必须同时提供 --reviewer。", file=sys.stderr)
        return 2
    if args.reviewer and not reviewer_operation:
        print(
            "ERROR: --reviewer 只能与 --approve-artifact、--begin-letter-revision或--mark-ready一起使用。",
            file=sys.stderr,
        )
        return 2
    issues, documents, result_path, operation = validate(
        root,
        args.strict,
        args.emit_external,
        args.approve_letter,
        args.approver,
        approve_artifact=args.approve_artifact,
        reviewer=args.reviewer,
        begin_revision=args.begin_letter_revision,
        mark_ready=args.mark_ready,
        recovery_preflight=args.recovery_preflight,
    )
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    if args.json:
        print(
            json.dumps(
                {
                    "workspace": str(root),
                    "documents": len(documents),
                    "errors": errors,
                    "warnings": warnings,
                    "operation": operation,
                    "result_path": str(result_path) if result_path else None,
                    "issues": [asdict(issue) for issue in issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for issue in issues:
            print(
                f"{issue.severity.upper()} [{issue.code}] {issue.path}: {issue.message}"
            )
        if result_path:
            labels = {
                "emit_external": "外发版",
                "approve_letter": "已批准内部稿",
                "approve_leader": "已批准人物研究",
                "approve_internal": "已批准内部检索",
                "approve_strategy": "已批准交流策略",
                "begin_letter_revision": "客户信修订工作稿",
                "mark_ready": "已完成就绪审批的综合报告",
            }
            label = labels.get(operation or "", "结果")
            print(f"{label}：{result_path}")
        print(f"校验完成：{len(documents)}个成果，{errors}个错误，{warnings}个警告。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
