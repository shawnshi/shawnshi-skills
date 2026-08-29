#!/usr/bin/env python3
"""Validate discovery-call v2.9 outputs and perform governed review operations."""

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
from typing import Mapping, Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import preflight_intake as intake_preflight

from capability_receipt import CapabilityReceiptError, verify_source_capture_receipt
from candidate_attestation import (
    ATTESTATION_AUDIENCE,
    ATTESTATION_SCHEMA,
    AUDIT_FIELDS as CANDIDATE_ATTESTATION_AUDIT_FIELDS,
    AUDIT_SCHEMA as CANDIDATE_ATTESTATION_AUDIT_SCHEMA,
    CandidateAttestationError,
    verify_persisted_candidate_attestation,
)

from governance import (
    GOVERNANCE_CONTEXT_REL,
    GovernanceError,
    claim_global_nonce,
    consume_action_assertion,
    consume_external_request,
    governance_json,
    load_governance_context,
    resolve_action_assertion,
    resolve_actor,
    resolve_external_request,
    validate_global_nonce_claim,
)

from runtime_tx import (
    AUDITED_RUNTIME_RELS,
    MANIFEST_REL,
    TxError,
    build_manifest,
    file_state,
    load_manifest,
    manifest_state,
    normalize_task_timezone,
    sha256_file,
    task_date_at,
    transactional_write,
)


SCHEMA = "discovery-call-output/v2.5"
SCHEMA_ROOT = Path(__file__).resolve().parent.parent / "schemas"
BUSINESS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "business-modes.json"
# These digests are a release trust anchor, not metadata supplied by the
# protected files themselves.  Any intentional contract change must update the
# relevant constant in the same reviewed change and rerun the trust tests.
TRUSTED_SCHEMA_SHA256 = {
    "business-modes.schema.json": "1d9be7bfbbe543cb132c61b87054c3a94164fd831ed4879347ff4b904718f659",
    "candidate-attestation.schema.json": "90274641c12f5e00ab3e05c7a5f0d87b2d0feed4bad3180b637aab6dc6908c74",
    "candidate-seal-request.schema.json": "88ccf3a84a17c6ec62df756e7bb5a4ec7601f5d21dcede17e8209f82acf49788",
    "capability-receipt.schema.json": "a63cba095eeb74e9e3fb3560be1037d702dab5646ef2b80cd0aa21954ba66244",
    "evidence-manifest.schema.json": "c9ddd02398b9a1a7f918a02baf1d061e8948a8a48769448bce1f649746dc3ea9",
    "forward-evaluation-manifest.schema.json": "6004f1073efc307c56a6d456081f4ddff86e9a6cc214303547f13f0b3a02f239",
    "forward-execution-receipt.schema.json": "e22aed5779e8fb765ee054e97d47bbe53e897ef13d8a226cc6e8feaa7708004c",
    "forward-plan.schema.json": "ac84be414bd166fddaf7b0d001f3f6502e5eefc39fb95ea07b52f882c2d5c8eb",
    "forward-side-effect-audit.schema.json": "72d0efe09babb47bf04c042726dedc3a9d19b7d310d787acab91821a4982a8ed",
    "forward-tool-trace.schema.json": "77fd66863d6ad665fa915299afa4f445c857f0418f8fdb422862fe0c64bea7da",
    "forward-validation-result.schema.json": "a327bea4f27712cc7ee49cfd612c6c208836a13af80a3c15a09d5a8619605e6d",
    "governance-context.schema.json": "0692cdb0600c79863c91f7abe2df489e0b44fdbf6e73ec6ec8e7af084e70578a",
    "intake-preflight.schema.json": "c3d6e3c28ae500fbfe5ecaf774ecae0255e7b8d9fe6b2922fc5421023bba49f3",
    "request-binding-receipt.schema.json": "e2c92e117d29b0552cc36e0a446f9b3683a54d4738ced6413f60218afb7af28f",
    "run-metrics.schema.json": "b90063589e363695a32d765d6450c3bafef2ada7f5a92c4c7f90e5348c8376e8",
    "search-plan.schema.json": "f1a50cb7d6d0914ac584ab197ac60c456ebb21bf146d9992207969a2ed4ffc95",
    "source-cache.schema.json": "04014056e9f2ce6fff396f75aa3cc2be67d4c2beb9f3d68772691fbfc75fc782",
    "source-capture-receipt.schema.json": "87012899a7942bc75acb25ab03d249dc80500fb4a9056a18d5cd87a90e2c41de",
}
TRUSTED_BUSINESS_CONFIG_SHA256 = "1a2eb2e21a43afdc17c0b89c7a569b8e61591c5842ee90114ac240f0c6f8daf4"
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
REVIEW_STATUSES = {"not_required", "not_started", "pending", "approved", "changes_requested"}
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
LEGACY_RUN_ARTIFACT_NAMES = {
    "institution",
    "leader",
    "internal",
    "strategy",
    "letter",
    "external_letter",
}
RUN_ARTIFACT_NAMES = LEGACY_RUN_ARTIFACT_NAMES | {"briefing"}
RUN_ARTIFACT_ORDER = (
    "institution",
    "leader",
    "internal",
    "strategy",
    "briefing",
    "letter",
    "external_letter",
)
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
    "briefing_delivery",
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
    "briefing_delivery": "会前速览.md",
}
STATUS_LABELS = {
    "institution_research": "机构研究",
    "leader_research": "人物研究",
    "internal_retrieval": "内部检索",
    "visit_strategy": "交流策略",
    "briefing_delivery": "会前速览",
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
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
INVALID_SAFE_CHARS = re.compile(r'[<>:"/\\|?*#%()\[\]\x00-\x1f\x7f]+')
WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]+\}\}")
SHA256_FINGERPRINT_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
PROVIDER_FINGERPRINT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{1,31}:[A-Za-z0-9][A-Za-z0-9._:/+-]{2,255}$")
CLAIM_RE = re.compile(r"\bCLM-(?:I|L|N)-\d{3,}\b")
SOURCE_RE = re.compile(r"\bSRC-(?:I|L|N)-\d{3,}\b")
BRIEFING_FACT_TYPE_RE = re.compile(r"(?<![A-Za-z0-9])(?:F2|F)(?![A-Za-z0-9])")
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
RAW_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
APPROVAL_FIELDS = {
    "approver",
    "approved_at",
    "approved_content_version",
    "approved_body_sha256",
    "approved_context_sha256",
    "approval_run_id",
    "approval_action_event_id",
}
LETTER_ACTOR_FIELDS = {
    "approver_actor_id",
    "approver_role",
    "approval_authority_id",
    "approver_identity_provider",
}
LETTER_FACT_REVIEW_FIELDS = {
    "fact_reviewer",
    "fact_reviewed_at",
    "fact_reviewed_content_version",
    "fact_reviewed_body_sha256",
    "fact_reviewed_context_sha256",
    "fact_reviewer_actor_id",
    "fact_reviewer_role",
    "fact_reviewer_authority_id",
    "fact_reviewer_identity_provider",
    "fact_reviewed_run_id",
    "fact_review_action_event_id",
}
LETTER_REVISION_FIELDS = {
    "revision_action_event_id",
    "revision_run_id",
    "revision_actor_id",
    "revision_at",
    "revision_target_content_version",
    "revision_target_body_sha256",
    "revision_target_context_sha256",
}
EXTERNAL_REQUEST_FIELDS = {
    "external_request_event_id",
    "external_requested_by_actor_id",
    "external_requested_at",
}
LETTER_CONTEXT_FIELDS = {
    "letter_scenario",
    "recipient_role",
    "letter_purpose",
    "expected_action",
    "signer",
    "delivery_channel",
}
SCHEDULED_STRATEGY_FIELDS = {"target_contact_level", "visit_objective", "minimum_next_step"}
ACCOUNT_STRATEGY_FIELDS = {"strategic_question", "planning_horizon", "minimum_next_step"}
STRATEGY_CONTEXT_FIELDS = SCHEDULED_STRATEGY_FIELDS | ACCOUNT_STRATEGY_FIELDS | {"strategy_variant"}
INTERNAL_LETTER_FIELDS = (
    APPROVAL_FIELDS
    | LETTER_ACTOR_FIELDS
    | LETTER_FACT_REVIEW_FIELDS
    | LETTER_REVISION_FIELDS
    | EXTERNAL_REQUEST_FIELDS
    | LETTER_CONTEXT_FIELDS
    | {"external_output_required"}
)
EXTERNAL_LINEAGE_FIELDS = (
    APPROVAL_FIELDS
    | LETTER_ACTOR_FIELDS
    | LETTER_FACT_REVIEW_FIELDS
    | EXTERNAL_REQUEST_FIELDS
    | {"source_internal_content_version"}
)
GENERIC_REVIEW_FIELDS = {
    "reviewer",
    "reviewed_at",
    "reviewed_content_version",
    "reviewed_body_sha256",
    "reviewer_actor_id",
    "reviewer_role",
    "reviewer_authority_id",
    "reviewer_identity_provider",
    "review_action_event_id",
}
GENERIC_REVIEW_TYPES = {
    "institution_research", "leader_research", "internal_retrieval",
    "visit_strategy", "briefing_delivery",
}
GENERIC_REVIEW_TARGETS = {
    "institution": "institution_research",
    "leader": "leader_research",
    "internal": "internal_retrieval",
    "strategy": "visit_strategy",
    "briefing": "briefing_delivery",
}
BUSINESS_MODES = {"briefing", "standard_visit", "strategic_account", "letter"}
RECOMMENDATIONS = {"win", "conditional_win", "monitor", "no_go"}
EXPECTED_DELIVERY_CONTRACTS = {
    "briefing": {
        "formal_artifact": "briefing_delivery",
        "audit_artifact": "comprehensive_report",
    },
    "standard_visit": {
        "formal_artifact": "visit_strategy",
        "audit_artifact": "comprehensive_report",
    },
    "strategic_account": {
        "formal_artifact": "visit_strategy",
        "audit_artifact": "comprehensive_report",
    },
    "letter": {
        "formal_artifact": "customer_letter_external",
        "audit_artifact": "comprehensive_report",
    },
}
STRATEGY_AUDIT_HEADINGS = {
    "任务上下文与成果状态",
    "本次RACI与审核SLA",
    "异常审核队列",
    "主张与来源导航",
    "刷新结果记录",
    "版本与同步记录",
}
NO_GO_TOTAL_REQUIRED_SECTIONS = {
    "决策摘要",
    "任务上下文与成果状态",
    "综合判断链",
    "G-C-P 推演",
    "机会资格与投入建议",
    "执行与下一步",
    "刷新结果记录",
    "版本与同步记录",
}
NO_GO_TOTAL_OPTIONAL_SECTIONS = {
    "高价值发现",
    "关键缺口与验证计划",
}
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
    "readiness_target_body_sha256",
    "readiness_reviewer_actor_id",
    "readiness_reviewer_role",
    "readiness_reviewer_authority_id",
    "readiness_reviewer_identity_provider",
    "readiness_action_event_id",
}
COMMON_FRONTMATTER_FIELDS = (
    REQUIRED_FIELDS
    | {"business_mode", "ready_for_use"}
    | AUTHORIZATION_FIELDS
)
ARTIFACT_FRONTMATTER_FIELDS = {
    "comprehensive_report": COMMON_FRONTMATTER_FIELDS | TOTAL_REQUIRED_FIELDS | READINESS_FIELDS,
    "institution_research": COMMON_FRONTMATTER_FIELDS | GENERIC_REVIEW_FIELDS,
    "leader_research": COMMON_FRONTMATTER_FIELDS | GENERIC_REVIEW_FIELDS,
    "internal_retrieval": COMMON_FRONTMATTER_FIELDS | GENERIC_REVIEW_FIELDS,
    "visit_strategy": COMMON_FRONTMATTER_FIELDS | GENERIC_REVIEW_FIELDS | STRATEGY_CONTEXT_FIELDS,
    "briefing_delivery": COMMON_FRONTMATTER_FIELDS | GENERIC_REVIEW_FIELDS | {"delivery_state", "page_proxy"},
    "customer_letter_internal": COMMON_FRONTMATTER_FIELDS | INTERNAL_LETTER_FIELDS,
    "customer_letter_external": (
        COMMON_FRONTMATTER_FIELDS
        | INTERNAL_LETTER_FIELDS
        | EXTERNAL_LINEAGE_FIELDS
        | {"source_internal_content_version"}
    ),
}


def readiness_reset_updates() -> dict[str, str]:
    return {"ready_for_use": "false", **{field: "" for field in READINESS_FIELDS}}
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


def add(issues: list[Issue], severity: str, code: str, path: Path, message: str) -> None:
    issues.append(Issue(severity, code, str(path), message))


class TrustedContractError(RuntimeError):
    """Raised when a packaged contract cannot be authenticated by code."""


def _trusted_json_file(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    parent = path.parent.resolve()
    if path.is_symlink() or not path.is_file() or path.resolve().parent != parent:
        raise TrustedContractError(f"{label}缺失、不是普通文件或包含重定向：{path.name}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TrustedContractError(f"{label}无法读取：{path.name}：{exc}") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not expected_sha256 or actual_sha256 != expected_sha256:
        raise TrustedContractError(
            f"{label}摘要与代码内可信清单不一致：{path.name}；"
            "禁止由同目录文件自证或自动重写可信摘要。"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedContractError(f"{label}不是有效UTF-8 JSON：{path.name}") from exc
    if not isinstance(payload, dict):
        raise TrustedContractError(f"{label}顶层必须是对象：{path.name}")
    return payload


def load_trusted_schema_contract(name: str) -> dict[str, object]:
    expected_sha256 = TRUSTED_SCHEMA_SHA256.get(name)
    if expected_sha256 is None:
        raise TrustedContractError(f"schema未登记在代码内可信清单：{name}")
    return _trusted_json_file(SCHEMA_ROOT / name, expected_sha256, "schema")


def load_trusted_business_profiles() -> dict[str, dict[str, object]]:
    payload = _trusted_json_file(
        BUSINESS_CONFIG_PATH,
        TRUSTED_BUSINESS_CONFIG_SHA256,
        "business-modes配置",
    )
    profiles = payload.get("profiles", payload)
    if not isinstance(profiles, dict) or not all(
        isinstance(name, str) and isinstance(profile, dict)
        for name, profile in profiles.items()
    ):
        raise TrustedContractError("business-modes配置缺少结构化profiles对象。")
    return profiles


def validate_trusted_contract_bundle(issues: list[Issue]) -> bool:
    """Authenticate package contracts before reading customer artifacts.

    This detects packaging errors and accidental/unauthorized contract edits
    while the Python validator remains trusted.  It is not a self-integrity
    claim against an attacker who can also replace this source file.
    """

    trusted = True
    if SCHEMA_ROOT.is_symlink() or not SCHEMA_ROOT.is_dir():
        add(
            issues,
            "error",
            "runtime_machine_contract_unavailable",
            SCHEMA_ROOT,
            "schema目录缺失、不是普通目录或包含重定向。",
        )
        trusted = False
    else:
        actual_names = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
        unexpected = sorted(actual_names - set(TRUSTED_SCHEMA_SHA256))
        if unexpected:
            add(
                issues,
                "error",
                "runtime_machine_contract_unavailable",
                SCHEMA_ROOT,
                "schema目录包含未登记文件：" + ", ".join(unexpected),
            )
            trusted = False
        for name in sorted(TRUSTED_SCHEMA_SHA256):
            try:
                load_trusted_schema_contract(name)
            except TrustedContractError as exc:
                add(
                    issues,
                    "error",
                    "runtime_machine_contract_unavailable",
                    SCHEMA_ROOT / name,
                    str(exc),
                )
                trusted = False
    try:
        load_trusted_business_profiles()
    except TrustedContractError as exc:
        add(
            issues,
            "error",
            "runtime_business_contract_unavailable",
            BUSINESS_CONFIG_PATH,
            str(exc),
        )
        trusted = False
    return trusted


def markdown_without_fenced_code(text: str) -> str:
    """Mask rendered code blocks so examples cannot satisfy delivery contracts."""
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
        if fence or re.match(r"^(?: {4,}|\t)\S", line):
            output.append("")
        else:
            output.append(line)
    return "\n".join(output)


def contains_markdown_code_block(text: str) -> bool:
    """Return true for fenced or four-space/tab-indented Markdown code blocks."""

    return bool(
        re.search(r"(?m)^[ \t]{0,3}(?:`{3,}|~{3,})", text)
        or re.search(r"(?m)^(?: {4,}|\t)\S", text)
    )


def contains_markdown_link_or_image(text: str) -> bool:
    """Detect inline/reference links and images whose destinations are not visible text."""

    return bool(
        re.search(r"!?\[[^\]\n]*\]\([^\)\n]*\)", text)
        or re.search(r"!?\[[^\]\n]*\]\[[^\]\n]*\]", text)
        or re.search(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:\s*\S", text)
    )


def has_extra_frontmatter_block(body: str) -> bool:
    lines = markdown_without_fenced_code(body).split("\n")
    delimiters = [index for index, line in enumerate(lines) if re.fullmatch(r"---[ \t]*", line)]
    for left, right in zip(delimiters, delimiters[1:]):
        if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:\s*.*", line) for line in lines[left + 1 : right]):
            return True
    return False


def parse_frontmatter(path: Path, text: str, issues: list[Issue]) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        add(issues, "error", "frontmatter_missing", path, "成果文件必须以YAML frontmatter开始。")
        return {}, text
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        add(issues, "error", "frontmatter_unclosed", path, "YAML frontmatter缺少结束分隔符。")
        return {}, text
    data: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not match:
            add(issues, "error", "frontmatter_unsupported", path, f"第{line_number}行不是扁平key: value。")
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                add(issues, "error", "frontmatter_string_invalid", path, f"第{line_number}行不是合法JSON字符串。")
                continue
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        if key in data:
            add(issues, "error", "frontmatter_duplicate", path, f"字段{key}重复。")
        data[key] = value
    body = "\n".join(lines[end + 1 :])
    if has_extra_frontmatter_block(body):
        add(issues, "error", "frontmatter_duplicate_block", path, "检测到第二个顶层frontmatter块。")
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
    return bool(re.search(r"^schema:\s*[\"']?discovery-call-output/v2\.5[\"']?\s*$", head, re.M))


def load_documents(root: Path, issues: list[Issue]) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(root.glob("*.md")):
        if path.is_symlink() or path.resolve().parent != root.resolve():
            add(issues, "error", "artifact_symlink", path, "成果文件不得为符号链接或越出工作目录。")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            add(issues, "error", "read_failed", path, str(exc))
            continue
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            add(issues, "error", "artifact_control_character", path, "成果文件包含不允许的控制字符。")
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


def _json_type_matches(value: object, expected: str) -> bool:
    """Dependency-free JSON Schema type predicate for runtime contracts."""
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _schema_pointer(root_schema: Mapping[str, object], reference: str) -> Mapping[str, object] | None:
    if not reference.startswith("#/"):
        return None
    current: object = root_schema
    for raw in reference[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, Mapping) else None


def validate_json_contract(
    value: object,
    schema: Mapping[str, object],
    *,
    root_schema: Mapping[str, object] | None = None,
    location: str = "$",
) -> list[str]:
    """Validate the JSON-Schema subset used by the four runtime files.

    The skill deliberately has no third-party runtime dependency.  This covers
    every keyword currently used by the bundled machine schemas and fails
    closed for an unresolved local reference.
    """
    root = root_schema or schema
    reference = schema.get("$ref")
    if isinstance(reference, str):
        target = _schema_pointer(root, reference)
        if target is None:
            return [f"{location}: 无法解析schema引用{reference}"]
        return validate_json_contract(value, target, root_schema=root, location=location)

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        allowed_types = [expected_type]
    elif isinstance(expected_type, list) and all(isinstance(item, str) for item in expected_type):
        allowed_types = list(expected_type)
    else:
        allowed_types = []
    if allowed_types and not any(_json_type_matches(value, item) for item in allowed_types):
        return [f"{location}: 类型应为{'/'.join(allowed_types)}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{location}: 值不等于const")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{location}: 值不在enum中")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(f"{location}.{key}: 缺少必填字段")
        properties = schema.get("properties", {})
        property_map = properties if isinstance(properties, Mapping) else {}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in property_map:
                    errors.append(f"{location}.{key}: 不允许的字段")
        additional = schema.get("additionalProperties")
        for key, item in value.items():
            child_schema = property_map.get(key)
            if isinstance(child_schema, Mapping):
                errors.extend(
                    validate_json_contract(
                        item,
                        child_schema,
                        root_schema=root,
                        location=f"{location}.{key}",
                    )
                )
            elif isinstance(additional, Mapping):
                errors.extend(
                    validate_json_contract(
                        item,
                        additional,
                        root_schema=root,
                        location=f"{location}.{key}",
                    )
                )

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            errors.append(f"{location}: 数组少于{minimum_items}项")
        if schema.get("uniqueItems") is True:
            serialized = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{location}: 数组项必须唯一")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(
                    validate_json_contract(
                        item,
                        item_schema,
                        root_schema=root,
                        location=f"{location}[{index}]",
                    )
                )
        contains = schema.get("contains")
        if isinstance(contains, Mapping) and not any(
            not validate_json_contract(item, contains, root_schema=root, location=location)
            for item in value
        ):
            errors.append(f"{location}: 没有满足contains的数组项")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{location}: 字符串短于{minimum_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{location}: 不匹配pattern")
        if schema.get("format") == "date-time" and not timestamp_valid(value):
            errors.append(f"{location}: 不是带时区date-time")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{location}: 小于minimum {minimum}")

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for index, branch in enumerate(all_of):
            if not isinstance(branch, Mapping):
                errors.append(f"{location}.allOf[{index}]: schema无效")
                continue
            condition = branch.get("if")
            consequence = branch.get("then")
            if isinstance(condition, Mapping) and isinstance(consequence, Mapping):
                if not validate_json_contract(value, condition, root_schema=root, location=location):
                    errors.extend(
                        validate_json_contract(value, consequence, root_schema=root, location=location)
                    )
            else:
                errors.extend(validate_json_contract(value, branch, root_schema=root, location=location))
    return errors


def parse_expiry(value: str) -> datetime | None:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed_date = date.fromisoformat(value)
            return datetime.combine(parsed_date, datetime.max.time(), tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def evidence_calendar(
    root: Path,
    *,
    instant: datetime | None = None,
) -> tuple[date, date, str | None]:
    """Resolve TTL/future-date policy from the persisted task timezone.

    Legacy v2.5 manifests and explicit-date-only workspaces have no timezone.
    Their future guard accepts at most the adjacent UTC civil date, which is
    the complete range of dates that can be current somewhere in the world.
    """
    current = (instant or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        manifest = load_manifest(root, required=False)
    except TxError:
        # validate_runtime_manifest reports the authoritative manifest error;
        # use the bounded legacy policy here instead of crashing validation.
        manifest = None
    task_timezone = (
        normalize_task_timezone(manifest.get("task_timezone"))
        if manifest and "task_timezone" in manifest
        else None
    )
    if task_timezone is not None:
        today = task_date_at(current, task_timezone)
        return today, today, task_timezone
    today = current.date()
    return today, today + timedelta(days=1), None


def load_business_profiles(issues: list[Issue] | None = None) -> dict[str, dict[str, object]]:
    try:
        return load_trusted_business_profiles()
    except TrustedContractError as exc:
        if issues is not None:
            add(
                issues,
                "error",
                "runtime_business_contract_unavailable",
                BUSINESS_CONFIG_PATH,
                str(exc),
            )
        return {}


def strategy_variant_contract(
    business_mode: str,
    variant: str,
    *,
    profiles: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    """Return the configured contract for a strategy branch.

    The two branch definitions are canonical in the strategic-account profile.
    Briefing and standard-visit both use the same scheduled-visit definition.
    """
    configured = profiles or load_business_profiles()
    profile = configured.get(business_mode) if isinstance(configured, Mapping) else None
    variants = profile.get("strategy_variants") if isinstance(profile, Mapping) else None
    if not isinstance(variants, Mapping):
        strategic = configured.get("strategic_account") if isinstance(configured, Mapping) else None
        variants = strategic.get("strategy_variants") if isinstance(strategic, Mapping) else None
    branches = variants.get("variants") if isinstance(variants, Mapping) else None
    contract = branches.get(variant) if isinstance(branches, Mapping) else None
    return contract if isinstance(contract, Mapping) else None


def delivery_contract_for_mode(
    business_mode: str,
    *,
    profiles: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Return the exact user-delivery/audit split for one public mode.

    The mapping is deliberately total over the four public modes.  A missing,
    extra, or remapped field is a contract failure rather than a fallback to the
    comprehensive report as an informal delivery.
    """

    expected = EXPECTED_DELIVERY_CONTRACTS.get(business_mode)
    if expected is None:
        raise ValueError(f"unsupported business_mode={business_mode or 'empty'}")
    configured = profiles if profiles is not None else load_business_profiles()
    profile = configured.get(business_mode) if isinstance(configured, Mapping) else None
    contract = profile.get("delivery_contract") if isinstance(profile, Mapping) else None
    if not isinstance(contract, Mapping) or set(contract) != {"formal_artifact", "audit_artifact"}:
        raise ValueError(f"profiles.{business_mode}.delivery_contract missing or malformed")
    actual = {
        "formal_artifact": str(contract.get("formal_artifact", "")),
        "audit_artifact": str(contract.get("audit_artifact", "")),
    }
    if actual != expected:
        raise ValueError(
            f"profiles.{business_mode}.delivery_contract must equal {expected}, got {actual}"
        )
    return actual


def recommendation_template_pair(
    business_mode: str,
    variant: str,
    recommendation: str,
    *,
    profiles: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Select the account strategy/audit template pair without guessing.

    `win`, `conditional_win`, and `monitor` share the default pair; `no_go`
    selects the closed-code pair.  Unknown recommendations and malformed maps
    raise so callers can fail closed.
    """

    if business_mode != "strategic_account" or variant != "account_planning":
        raise ValueError(
            "template_by_recommendation is only valid for strategic_account/account_planning"
        )
    if recommendation not in RECOMMENDATIONS:
        raise ValueError(f"unsupported recommendation={recommendation or 'empty'}")
    contract = strategy_variant_contract(
        business_mode,
        variant,
        profiles=profiles,
    )
    if not isinstance(contract, Mapping):
        raise ValueError(f"strategy_variant={variant or 'empty'} contract missing")
    mapping = contract.get("template_by_recommendation")
    if not isinstance(mapping, Mapping) or set(mapping) != {"default", "no_go"}:
        raise ValueError("template_by_recommendation must contain only default and no_go")
    expected_keys = {"visit_strategy", "comprehensive_report"}
    validated: dict[str, dict[str, str]] = {}
    for route_name in ("default", "no_go"):
        pair = mapping.get(route_name)
        if not isinstance(pair, Mapping) or set(pair) != expected_keys:
            raise ValueError(
                f"template_by_recommendation.{route_name} must contain the exact artifact pair"
            )
        validated[route_name] = {
            key: str(pair.get(key, "")) for key in sorted(expected_keys)
        }
        for artifact_type, relative in validated[route_name].items():
            if not re.fullmatch(r"assets/[a-z0-9-]+\.md", relative):
                raise ValueError(f"{route_name}.{artifact_type} template path invalid")
            target = BUSINESS_CONFIG_PATH.parent.parent / relative
            if not target.is_file() or target.is_symlink():
                raise ValueError(f"{route_name}.{artifact_type} template unavailable")
    if validated["default"]["visit_strategy"] != contract.get("template"):
        raise ValueError("default visit_strategy template must equal the variant scaffold template")
    branch = "no_go" if recommendation == "no_go" else "default"
    return validated[branch]


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


def resolved_business_text(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized_folded = normalized.casefold()
    unresolved_markers = ("待确认", "未确认", "待核实", "未核实", "待指定", "待补充", "unknown")
    return bool(
        normalized
        and len(normalized) <= 500
        and not PLACEHOLDER_RE.search(normalized)
        and normalize_evidence_text(normalized) not in {"待确认", "待指定", "待补充", "unknown", "none", "n/a", "na", "无"}
        and not any(marker in normalized_folded for marker in unresolved_markers)
        and not any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    )


def letter_context_sha256(data: dict[str, str]) -> str:
    payload = {key: data.get(key, "") for key in sorted(LETTER_CONTEXT_FIELDS)}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_subject_digest(customer_name: object, entity_key: object, jurisdiction: object) -> str:
    """Recompute the host-attested subject tuple without performing alias resolution."""
    canonical_name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(customer_name or ""))).strip()
    payload = {
        "canonical_customer_name": canonical_name,
        "canonical_entity_key": str(entity_key or ""),
        "jurisdiction": str(jurisdiction or ""),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def strategy_required_fields(data: Mapping[str, str]) -> set[str]:
    variant = data.get("strategy_variant", "")
    if variant == "scheduled_visit":
        return SCHEDULED_STRATEGY_FIELDS | {"strategy_variant"}
    if variant == "account_planning":
        return ACCOUNT_STRATEGY_FIELDS | {"strategy_variant"}
    return {"strategy_variant"}


def h2_sections(body: str) -> dict[str, list[str]]:
    """Return exact H2 section bodies, normalizing optional numeric prefixes."""

    matches = list(
        re.finditer(
            r"^##\s+(?:(?:\d+(?:\.\d+)*)[.)]?\s+)?(.+?)\s*$",
            body,
            flags=re.MULTILINE,
        )
    )
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.setdefault(match.group(1).strip(), []).append(body[match.end() : end])
    return sections


def markdown_preamble(body: str) -> str:
    """Return content before the first H2, including an optional H1/banner."""

    match = re.search(r"^##(?!#)\s+\S", body, re.MULTILINE)
    return body[: match.start()] if match else body


def markdown_table_blocks(section: str) -> list[tuple[list[str], list[list[str]]]]:
    """Parse contiguous Markdown tables as (header, data rows)."""

    raw_blocks: list[list[str]] = []
    current: list[str] = []
    for line in section.splitlines():
        if line.lstrip().startswith("|"):
            current.append(line)
        elif current:
            raw_blocks.append(current)
            current = []
    if current:
        raw_blocks.append(current)
    tables: list[tuple[list[str], list[list[str]]]] = []
    for block in raw_blocks:
        rows = [split_table_cells(line) for line in block]
        if len(rows) < 2:
            continue
        separator = rows[1]
        if not separator or not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in separator):
            continue
        tables.append((rows[0], rows[2:]))
    return tables


def operational_cell(value: str) -> bool:
    """Whether a fixed-contract table cell contains resolved, usable content."""

    return resolved_business_text(value) and not PLACEHOLDER_RE.search(value)


INTERNAL_OWNER_ROLES = {
    "账户负责人",
    "客户负责人",
    "客户责任岗",
    "战略账户责任岗",
    "方案顾问",
    "售前顾问",
    "方案负责人",
    "方案责任岗",
    "技术负责人",
    "技术经理",
    "技术架构师",
    "产品经理",
    "客户成功",
    "证据负责人",
    "运行负责人",
    "测试负责人",
    "商务审核岗",
    "拜访策略审核岗",
    "人物事实审核岗",
    "客户信事实复核岗",
    "会前简报事实审核岗",
    "交付就绪审核岗",
}
OWNER_NAMED_ROLE_RE = re.compile(r"([\u4e00-\u9fffA-Za-z·]{2,12})\(([^()]{2,20})\)")


def stable_owner_cell(value: str) -> bool:
    """Accept a short accountable identity/role, never an action sentence."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    if not operational_cell(normalized) or not 2 <= len(compact_contract_text(normalized)) <= 40:
        return False
    if normalized in INTERNAL_OWNER_ROLES:
        return True
    named = OWNER_NAMED_ROLE_RE.fullmatch(normalized)
    return bool(named and named.group(2) in INTERNAL_OWNER_ROLES)


VACUOUS_DELIVERY_TEXTS = {
    "已讨论",
    "已沟通",
    "已完成",
    "内容",
    "待补充",
    "待确认",
    "待核实",
    "未知",
    "暂无",
    "无",
    "同上",
    "略",
    "tbd",
    "n/a",
}


def meaningful_delivery_text(value: str, *, minimum_chars: int = 4) -> bool:
    """Reject empty-shell delivery prose while allowing explicit, explained gaps."""

    if PLACEHOLDER_RE.search(value):
        return False
    normalized = unicodedata.normalize("NFKC", value).strip()
    visible = normalize_evidence_text(normalized)
    compact = compact_contract_text(visible)
    meta_shell = bool(
        re.fullmatch(
            r"(?:相关|上述|以上|本项|该项|本节|具体)?"
            r"(?:内容|事项|信息|情况|结果)?"
            r"(?:已经|已)?(?:记录|完成|讨论|沟通|处理|说明)"
            r"(?:并(?:已)?完成)?",
            compact,
        )
    )
    return bool(
        len(compact) >= minimum_chars
        and visible.casefold().rstrip("。.!！?？;；:：") not in VACUOUS_DELIVERY_TEXTS
        and not meta_shell
        and not any(
            (ord(char) < 32 and char not in "\r\n\t") or ord(char) == 127
            for char in normalized
        )
    )


LETTER_PURPOSE_ACTION_RE = re.compile(
    r"(?:确认|说明|澄清|同步|商议|讨论|邀请|跟进|回应|感谢|征询|安排|请求)"
)
LETTER_EXPECTED_ACTION_RE = re.compile(
    r"(?:确认|提供|回复|安排|选择|反馈|提交|签署|指定|告知|同意|审阅|参加|协调|预约|补充)"
)


def substantive_letter_field(value: str, *, purpose: bool) -> bool:
    action_pattern = LETTER_PURPOSE_ACTION_RE if purpose else LETTER_EXPECTED_ACTION_RE
    return bool(
        meaningful_delivery_text(value, minimum_chars=6)
        and not LETTER_PURPOSE_META_RE.search(value)
        and action_pattern.search(unicodedata.normalize("NFKC", value))
    )


BRIEFING_DECISION_RE = re.compile(
    r"^建议\s*=\s*(win|conditional_win|monitor|no_go)\s*；\s*"
    r"投入强度\s*=\s*(低|中|高)\s*；\s*边界\s*=\s*(.+)$",
    re.IGNORECASE,
)
PRIMARY_ACTION_VERB_RE = re.compile(
    r"(?:安排|确认|组织|提交|复核|预约|制定|形成|核实|验证|归档|观察|停止|退出|同步|澄清|召开|完成)"
)
VACUOUS_PRIMARY_ACTION_RE = re.compile(
    r"^(?:不采取任何动作|无需(?:任何)?动作|暂无动作|无动作|不推进|什么也不做)[。.!！]?$"
)
DELIVERY_SUMMARY_FIELDS = (
    "recommendation",
    "investment_intensity",
    "primary_action",
    "owner",
    "due_date",
)


def briefing_delivery_summary(document: Document) -> dict[str, str] | None:
    visible = markdown_without_fenced_code(document.body)
    sections = h2_sections(visible)
    opportunity = sections.get("机会与边界", [])
    action_sections = sections.get("最小推进动作", [])
    if len(opportunity) != 1 or len(action_sections) != 1:
        return None
    tables = markdown_table_blocks(opportunity[0])
    rows = tables[0][1] if len(tables) == 1 else []
    suggestion = next((row[1] for row in rows if len(row) == 3 and row[0] == "建议"), "")
    decision = BRIEFING_DECISION_RE.fullmatch(suggestion.strip())
    action_body = action_sections[0]
    extracted = {
        label: re.findall(rf"^\s*-\s*{re.escape(label)}：\s*(.+)$", action_body, re.MULTILINE)
        for label in ("动作", "Owner", "Due date")
    }
    if decision is None or any(len(values) != 1 for values in extracted.values()):
        return None
    return {
        "recommendation": decision.group(1).casefold(),
        "investment_intensity": decision.group(2),
        "primary_action": normalize_evidence_text(extracted["动作"][0]).rstrip("。.!！"),
        "owner": normalize_evidence_text(extracted["Owner"][0]),
        "due_date": extracted["Due date"][0].strip(),
    }


def strategy_delivery_summary(document: Document) -> dict[str, str] | None:
    visible = markdown_without_fenced_code(document.body)
    sections = h2_sections(visible)
    qualification = sections.get("机会资格与投入建议", [])
    if len(qualification) != 1:
        qualification = sections.get("机会资格", [])
    if len(qualification) != 1:
        return None
    recommendation = re.search(
        r"^\s*-\s*建议：\s*(win|conditional_win|monitor|no_go)\s*$",
        qualification[0],
        re.MULTILINE,
    )
    investment = re.search(
        r"^\s*-\s*投入强度：\s*(低|中|高)(?:；\s*依据：\s*.+)?\s*$",
        qualification[0],
        re.MULTILINE,
    )
    if recommendation is None or investment is None:
        return None
    variant = document.frontmatter.get("strategy_variant", "scheduled_visit")
    action_sections = sections.get(
        "30/60/90天账户动作" if variant == "account_planning" else "会后行动",
        [],
    )
    tables = markdown_table_blocks(action_sections[0]) if len(action_sections) == 1 else []
    if len(tables) != 1 or not tables[0][1]:
        return None
    header, rows = tables[0]
    action_key = "action"
    try:
        action_index = header.index(action_key)
        owner_index = header.index("owner")
        due_index = header.index("due_date")
    except ValueError:
        return None
    row = rows[0]
    if max(action_index, owner_index, due_index) >= len(row):
        return None
    return {
        "recommendation": recommendation.group(1),
        "investment_intensity": investment.group(1),
        "primary_action": normalize_evidence_text(row[action_index]).rstrip("。.!！"),
        "owner": normalize_evidence_text(row[owner_index]),
        "due_date": row[due_index].strip(),
    }


def delivery_summary_for_documents(
    by_type: Mapping[str, Document],
    *,
    business_mode: str | None = None,
    selected_modules: Sequence[str] | None = None,
) -> dict[str, str] | None:
    """Return the current run's strategy decision summary, never a stale carrier.

    A workspace may retain a historical ``visit_strategy`` Markdown file when
    switching to the letter branch.  File presence alone therefore cannot
    select a decision for the current delivery.  Callers that build or verify
    a manifest must supply the current business mode and selected module set.
    """

    if business_mode is None:
        total = by_type.get("comprehensive_report")
        if total is not None:
            business_mode = total.frontmatter.get("business_mode")
    if business_mode not in {"briefing", "standard_visit", "strategic_account"}:
        return None
    if selected_modules is not None and "strategy" not in set(selected_modules):
        return None
    strategy = by_type.get("visit_strategy")
    if strategy is None:
        return None
    summary = strategy_delivery_summary(strategy)
    if summary is None:
        return None
    return {
        "schema": "discovery-call-delivery-summary/v1",
        "source_artifact_type": "visit_strategy",
        **summary,
    }


def validate_briefing_contract(document: Document, issues: list[Issue]) -> None:
    """Enforce the one-page briefing as a small, stable delivery contract."""
    data = document.frontmatter
    visible_body = markdown_without_fenced_code(document.body)
    if HTML_COMMENT_RE.search(document.body) or RAW_HTML_TAG_RE.search(document.body):
        add(
            issues,
            "error",
            "briefing_html_comment_forbidden",
            document.path,
            "会前速览不得包含HTML注释或原始HTML标签；禁止把正式章节隐藏、折叠或移出默认渲染区域。",
        )
    if contains_markdown_link_or_image(document.body):
        add(
            issues,
            "error",
            "briefing_markdown_link_forbidden",
            document.path,
            "会前速览不得使用Markdown链接或图片；核心判断、事实、问题和动作必须直接显示在默认渲染文本中。",
        )
    if data.get("page_proxy") != "markdown-one-page/v1":
        add(issues, "error", "briefing_page_proxy_invalid", document.path, "page_proxy必须为markdown-one-page/v1。")
    expected_state = "ready" if data.get("review_status") == "approved" else "draft_for_review"
    if data.get("delivery_state") != expected_state:
        add(issues, "error", "briefing_delivery_state_invalid", document.path, f"delivery_state应为{expected_state}。")
    required = (
        "一句话判断",
        "会前必须知道",
        "机会与边界",
        "建议交流节奏",
        "三个现场问题",
        "最小推进动作",
        "未决风险",
    )
    for heading in required:
        if len(re.findall(rf"^##\s+{re.escape(heading)}\s*$", visible_body, flags=re.MULTILINE)) != 1:
            add(issues, "error", "briefing_section_invalid", document.path, f"一页简报必须且只能有一个“{heading}”章节。")
            if heading == "建议交流节奏":
                add(issues, "error", "briefing_agenda_required", document.path, "一页简报必须保留固定的“建议交流节奏”章节。")
    profiles = load_business_profiles(issues)
    briefing_profile = profiles.get("briefing", {}) if isinstance(profiles, dict) else {}
    delivery_budget = (
        briefing_profile.get("delivery_budget")
        if isinstance(briefing_profile, dict)
        else None
    )
    if not isinstance(delivery_budget, dict):
        add(issues, "error", "briefing_delivery_budget_missing", document.path, "可信业务配置缺少会前速览delivery_budget。")
        delivery_budget = {
            "visible_chars_max": 0,
            "nonblank_lines_max": 0,
            "section_visible_chars_max": 0,
            "conclusion_visible_chars_max": 0,
        }
    visible = normalize_evidence_text(PLACEHOLDER_RE.sub("", visible_body))
    nonblank_lines = [line for line in visible_body.splitlines() if line.strip()]
    visible_max = int(delivery_budget.get("visible_chars_max", 0))
    line_max = int(delivery_budget.get("nonblank_lines_max", 0))
    if len(visible) > visible_max or len(nonblank_lines) > line_max:
        add(issues, "error", "briefing_page_limit_exceeded", document.path, f"一页代理超过{visible_max}可见字符或{line_max}个非空行。")
    visible_sections = h2_sections(PLACEHOLDER_RE.sub("", visible_body))
    section_max = int(delivery_budget.get("section_visible_chars_max", 0))
    oversized_sections = sorted(
        heading
        for heading in required
        for body in visible_sections.get(heading, [])
        if len(normalize_evidence_text(body)) > section_max
    )
    if oversized_sections:
        add(
            issues,
            "error",
            "briefing_section_budget_exceeded",
            document.path,
            f"一页代理单节超过{section_max}可见字符：" + ", ".join(oversized_sections),
        )
    completed = data.get("module_status") == "completed"
    question_section = re.search(
        r"^##\s+三个现场问题\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    questions = (
        re.findall(r"^\s*\d+\.\s+(.+)$", question_section.group(1), flags=re.MULTILINE)
        if question_section
        else []
    )
    if len(questions) != 3:
        add(issues, "error", "briefing_question_count_invalid", document.path, "一页简报必须恰有3个现场问题。")
    elif completed and any(
        not meaningful_delivery_text(question, minimum_chars=8)
        or not re.search(r"[?？]\s*$", question)
        or not re.search(r"(?:什么|谁|是否|如何|哪|能否|可否|何时|多久|有无|为何|多少)", question)
        for question in questions
    ):
        add(issues, "error", "briefing_question_content_invalid", document.path, "三个现场问题必须分别包含可执行的完整问题，不能只写短词或空壳。")
    if len(re.findall(r"^\s*-\s*动作：\s*\S", visible_body, flags=re.MULTILINE)) != 1:
        add(issues, "error", "briefing_action_count_invalid", document.path, "一页简报必须恰有1个主动作。")
    fact_section = re.search(
        r"^##\s+会前必须知道\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    fact_rows: list[list[str]] = []
    if fact_section:
        table_lines = [line for line in fact_section.group(1).splitlines() if line.lstrip().startswith("|")]
        fact_rows = [
            split_table_cells(line)
            for line in table_lines[2:]
            if any(cell.strip() for cell in split_table_cells(line))
        ]
    if not 1 <= len(fact_rows) <= 5:
        add(issues, "error", "briefing_fact_count_invalid", document.path, "“会前必须知道”必须包含1—5条事实。")
    for index, cells in enumerate(fact_rows, 1):
        if len(cells) != 3:
            add(issues, "error", "briefing_fact_row_shape", document.path, f"“会前必须知道”第{index}条必须恰有3列。")
            continue
        if any(PLACEHOLDER_RE.search(cell) for cell in cells):
            continue
        if completed and (
            not meaningful_delivery_text(cells[0], minimum_chars=6)
            or not meaningful_delivery_text(cells[2], minimum_chars=6)
        ):
            add(issues, "error", "briefing_fact_content_invalid", document.path, f"“会前必须知道”第{index}条事实及业务意义不能为空或为短句空壳。")
        fact_types = BRIEFING_FACT_TYPE_RE.findall(cells[1])
        if len(fact_types) != 1:
            add(issues, "error", "briefing_fact_type_invalid", document.path, f"“会前必须知道”第{index}条必须明确且只标一个F或F2。")
        if not CLAIM_RE.search(cells[1]):
            add(issues, "error", "briefing_fact_claim_missing", document.path, f"“会前必须知道”第{index}条至少需要一个CLM-I/L/N-###。")

    conclusion_section = re.search(
        r"^##\s+一句话判断\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    conclusion = conclusion_section.group(1).strip() if conclusion_section else ""
    conclusion_max = int(delivery_budget.get("conclusion_visible_chars_max", 0))
    if len(normalize_evidence_text(PLACEHOLDER_RE.sub("", conclusion))) > conclusion_max:
        add(issues, "error", "briefing_conclusion_budget_exceeded", document.path, f"一句话判断超过{conclusion_max}可见字符。")
    if completed and not meaningful_delivery_text(conclusion, minimum_chars=20):
        add(issues, "error", "briefing_conclusion_content_invalid", document.path, "一句话判断必须是可直接使用的完整判断，不能留空或只写短句。")
    elif conclusion and not PLACEHOLDER_RE.search(conclusion) and not CLAIM_RE.search(conclusion):
        add(issues, "error", "briefing_conclusion_claim_missing", document.path, "一句话判断必须引用至少一个合法claim_id。")

    opportunity_section = re.search(
        r"^##\s+机会与边界\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    opportunity_rows: list[list[str]] = []
    if opportunity_section:
        table_lines = [
            line
            for line in opportunity_section.group(1).splitlines()
            if line.lstrip().startswith("|")
        ]
        opportunity_rows = [
            split_table_cells(line)
            for line in table_lines[2:]
            if any(cell.strip() for cell in split_table_cells(line))
        ]
    expected_opportunity_labels = [
        "Need",
        "Authority",
        "Budget/Procurement",
        "Competition",
        "建议",
    ]
    if (
        len(opportunity_rows) != len(expected_opportunity_labels)
        or [cells[0] if cells else "" for cells in opportunity_rows]
        != expected_opportunity_labels
    ):
        add(
            issues,
            "error",
            "briefing_opportunity_rows_invalid",
            document.path,
            "“机会与边界”必须按固定顺序各保留Need、Authority、Budget/Procurement、Competition、建议一行。",
        )
    briefing_decision_match: re.Match[str] | None = None
    for index, cells in enumerate(opportunity_rows, 1):
        if len(cells) != 3:
            add(issues, "error", "briefing_opportunity_row_shape", document.path, f"“机会与边界”第{index}条必须恰有3列并单列依据claim_id。")
            continue
        if any(PLACEHOLDER_RE.search(cell) for cell in cells):
            continue
        label_terms = {
            "Need": r"(?:需求|任务|压力|问题|目标|结果|待核实|待确认|未知)",
            "Authority": r"(?:角色|职责|权限|决策|审批|责任|待核实|待确认|未知)",
            "Budget/Procurement": r"(?:预算|采购|资金|立项|待核实|待确认|未知)",
            "Competition": r"(?:竞争|存量|供应商|厂商|替代|切换|待核实|待确认|未知)",
        }
        if cells[0] == "建议":
            briefing_decision_match = BRIEFING_DECISION_RE.fullmatch(cells[1].strip())
            content_valid = bool(
                briefing_decision_match is not None
                and meaningful_delivery_text(briefing_decision_match.group(3), minimum_chars=6)
            )
        else:
            content_valid = bool(
                meaningful_delivery_text(cells[1], minimum_chars=6)
                and re.search(label_terms.get(cells[0], r"$^"), cells[1], re.IGNORECASE)
            )
        if completed and not content_valid:
            add(issues, "error", "briefing_opportunity_content_invalid", document.path, f"“机会与边界”第{index}条当前判断不能为空或为短句空壳；证据不足时须写明具体缺口。")
        if not CLAIM_RE.search(cells[2]):
            add(issues, "error", "briefing_opportunity_claim_missing", document.path, f"“机会与边界”第{index}条判断或建议必须引用至少一个claim_id。")

    agenda_section = re.search(
        r"^##\s+建议交流节奏\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    agenda_tables = markdown_table_blocks(agenda_section.group(1)) if agenda_section else []
    agenda_rows = agenda_tables[0][1] if agenda_tables else []
    expected_agenda_slots = ["0—5分钟", "5—20分钟", "20—25分钟", "25—30分钟"]
    actual_agenda_slots = [
        re.sub(r"[-–—]", "—", cells[0].strip()) if cells else ""
        for cells in agenda_rows
    ]
    if (
        actual_agenda_slots != expected_agenda_slots
        or any(len(cells) != 3 for cells in agenda_rows)
    ):
        add(
            issues,
            "error",
            "briefing_agenda_rows_invalid",
            document.path,
            "“建议交流节奏”必须恰有0—5、5—20、20—25、25—30分钟四行且每行3列。",
        )
    elif completed and any(
        not meaningful_delivery_text(cells[1], minimum_chars=6)
        or not meaningful_delivery_text(cells[2], minimum_chars=6)
        for cells in agenda_rows
    ):
        add(
            issues,
            "error",
            "briefing_agenda_content_invalid",
            document.path,
            "“建议交流节奏”每个时段的议题/动作和目标信号都必须是可执行内容，不能留空或写空壳短句。",
        )

    action_section = re.search(
        r"^##\s+最小推进动作\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    action_text = action_section.group(1) if action_section else ""
    evidence_lines = re.findall(r"^\s*-\s*依据claim_id：\s*(.+)$", action_text, flags=re.MULTILINE)
    if not evidence_lines:
        add(issues, "error", "briefing_action_claim_missing", document.path, "最小推进动作必须有一行“依据claim_id：”并引用至少一个claim_id。")
    elif len(evidence_lines) != 1:
        add(issues, "error", "briefing_action_claim_count_invalid", document.path, "最小推进动作只能有一行“依据claim_id：”。")
    elif not PLACEHOLDER_RE.search(evidence_lines[0]) and not CLAIM_RE.search(evidence_lines[0]):
        add(issues, "error", "briefing_action_claim_missing", document.path, "最小推进动作的依据必须引用至少一个claim_id。")
    action_fields = {
        label: re.findall(
            rf"^\s*-\s*{re.escape(label)}：\s*(.+)$",
            action_text,
            flags=re.MULTILINE,
        )
        for label in ("动作", "Owner", "Due date", "红线")
    }
    if any(len(values) != 1 for values in action_fields.values()):
        add(
            issues,
            "error",
            "briefing_action_fields_invalid",
            document.path,
            "最小推进动作必须各有且仅有一行动作、Owner、Due date和红线。",
        )
    elif document.frontmatter.get("module_status") == "completed":
        unresolved = sorted(
            label
            for label, values in action_fields.items()
            if not operational_cell(values[0])
            or not meaningful_delivery_text(
                values[0],
                minimum_chars=(4 if label in {"动作", "Owner"} else 6),
            )
        )
        if unresolved:
            add(
                issues,
                "error",
                "briefing_action_fields_invalid",
                document.path,
                "最小推进动作存在未解析字段：" + ", ".join(unresolved),
            )
        if not date_valid(action_fields["Due date"][0].strip()):
            add(
                issues,
                "error",
                "briefing_action_due_date_invalid",
                document.path,
                "最小推进动作的Due date必须为YYYY-MM-DD。",
            )
        if not stable_owner_cell(action_fields["Owner"][0]):
            add(issues, "error", "briefing_action_owner_invalid", document.path, "Owner必须为受控格式的真人姓名、稳定角色或账号，不得夹带动作。")
        primary_action = normalize_evidence_text(action_fields["动作"][0]).rstrip("。.!！")
        recommendation = (
            briefing_decision_match.group(1).casefold()
            if briefing_decision_match is not None
            else ""
        )
        controlled_no_go_actions = {
            normalize_evidence_text(value).rstrip("。.!！")
            for value in NO_GO_CONTROLLED_ACTIONS.values()
        }
        if (
            VACUOUS_PRIMARY_ACTION_RE.fullmatch(primary_action)
            or not PRIMARY_ACTION_VERB_RE.search(primary_action)
            or (recommendation == "no_go" and primary_action not in controlled_no_go_actions)
        ):
            add(issues, "error", "briefing_primary_action_invalid", document.path, "主动作必须包含明确动作与对象；no_go只能使用受控的停止、归档、观察或复核动作。")
        if not re.search(r"(?:不得|禁止|未经|不承诺|不触碰|不展示|不外发)", action_fields["红线"][0]):
            add(issues, "error", "briefing_action_redline_invalid", document.path, "红线必须明确写出不得、禁止、未经授权或其他可执行限制。")

    risk_sections = h2_sections(visible_body).get("未决风险", [])
    if completed and (
        len(risk_sections) != 1
        or not meaningful_delivery_text(risk_sections[0], minimum_chars=8)
    ):
        add(issues, "error", "briefing_risk_content_invalid", document.path, "未决风险必须写明具体风险或明确说明无阻断及其依据，不能留空或写空壳短句。")


def validate_briefing_claim_contract(
    by_type: Mapping[str, Document],
    claims: Mapping[str, ClaimDefinition],
    issues: list[Issue],
) -> None:
    """Bind briefing fact labels and decision evidence to defined claims."""
    briefing = by_type.get("briefing_delivery")
    if briefing is None:
        return
    visible_body = markdown_without_fenced_code(briefing.body)
    fact_section = re.search(
        r"^##\s+会前必须知道\s*$([\s\S]*?)(?=^##\s+|\Z)",
        visible_body,
        flags=re.MULTILINE,
    )
    if fact_section:
        table_lines = [line for line in fact_section.group(1).splitlines() if line.lstrip().startswith("|")]
        for index, line in enumerate(table_lines[2:], 1):
            cells = split_table_cells(line)
            if len(cells) != 3 or any(PLACEHOLDER_RE.search(cell) for cell in cells):
                continue
            row_types = BRIEFING_FACT_TYPE_RE.findall(cells[1])
            claim_ids = set(CLAIM_RE.findall(cells[1]))
            missing = sorted(claim_ids - claims.keys())
            if missing:
                add(issues, "error", "briefing_claim_invalid", briefing.path, f"“会前必须知道”第{index}条引用未定义claim：{', '.join(missing)}。")
            if len(row_types) == 1:
                mismatched = sorted(
                    claim_id
                    for claim_id in claim_ids & claims.keys()
                    if len(claims[claim_id].cells) < 2
                    or claims[claim_id].cells[1] != row_types[0]
                    or claims[claim_id].cells[1] not in {"F", "F2"}
                )
                if mismatched:
                    add(issues, "error", "briefing_fact_claim_type_mismatch", briefing.path, f"“会前必须知道”第{index}条的F/F2标记与claim台账不一致：{', '.join(mismatched)}。")

    evidence_sections = ("一句话判断", "机会与边界", "最小推进动作")
    for heading in evidence_sections:
        match = re.search(
            rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
            visible_body,
            flags=re.MULTILINE,
        )
        if match is None:
            continue
        body = PLACEHOLDER_RE.sub("", match.group(1))
        missing = sorted(set(CLAIM_RE.findall(body)) - claims.keys())
        if missing:
            add(issues, "error", "briefing_claim_invalid", briefing.path, f"“{heading}”引用未定义claim：{', '.join(missing)}。")

    strategy = by_type.get("visit_strategy")
    briefing_summary = briefing_delivery_summary(briefing)
    strategy_summary = strategy_delivery_summary(strategy) if strategy is not None else None
    completed_pair = (
        strategy is not None
        and briefing.frontmatter.get("module_status") == "completed"
        and strategy.frontmatter.get("module_status") == "completed"
    )
    decision_contract_active = completed_pair or (
        briefing_summary is not None or strategy_summary is not None
    )
    if decision_contract_active and (briefing_summary is None or strategy_summary is None):
        add(
            issues,
            "error",
            "briefing_delivery_summary_invalid",
            briefing.path,
            "会前速览与交流策略必须都能形成受控决策五元组。",
        )
    elif decision_contract_active and briefing_summary is not None and strategy_summary is not None:
        drift = [
            field
            for field in DELIVERY_SUMMARY_FIELDS
            if briefing_summary.get(field) != strategy_summary.get(field)
        ]
        if drift:
            add(
                issues,
                "error",
                "briefing_strategy_decision_drift",
                briefing.path,
                "会前速览与交流策略的建议/投入/主动作责任必须逐字段一致：" + ", ".join(drift),
            )


def validate_frontmatter(
    document: Document,
    issues: list[Issue],
    strict: bool,
    *,
    placeholder_errors: bool = False,
) -> None:
    data = document.frontmatter
    required = REQUIRED_FIELDS | (
        TOTAL_REQUIRED_FIELDS if data.get("artifact_type") == "comprehensive_report" else set()
    )
    missing = sorted(required - data.keys())
    if missing:
        add(issues, "error", "frontmatter_required", document.path, "缺少字段：" + ", ".join(missing))
        return
    allowed_frontmatter = ARTIFACT_FRONTMATTER_FIELDS.get(data.get("artifact_type", ""))
    if allowed_frontmatter is not None:
        unknown_frontmatter = sorted(set(data) - allowed_frontmatter)
        if unknown_frontmatter:
            add(
                issues,
                "error",
                "frontmatter_unknown_field",
                document.path,
                "frontmatter含未登记字段：" + ", ".join(unknown_frontmatter),
            )
    if data.get("module_status") == "completed":
        hidden_format_characters = sorted(
            {f"U+{ord(character):04X}" for character in document.body if unicodedata.category(character) == "Cf"}
        )
        if hidden_format_characters:
            add(
                issues,
                "error",
                "invisible_format_character_forbidden",
                document.path,
                "completed成果不得包含零宽、软连字符或其他不可见格式字符："
                + ", ".join(hidden_format_characters),
            )
        if HTML_COMMENT_RE.search(document.body) or RAW_HTML_TAG_RE.search(document.body):
            add(
                issues,
                "error",
                "delivery_hidden_content_forbidden",
                document.path,
                "completed Markdown成果不得包含HTML注释或原始HTML标签；禁止隐藏、折叠或改变默认可见交付。",
            )
        if contains_markdown_code_block(document.body):
            add(
                issues,
                "error",
                "delivery_code_block_forbidden",
                document.path,
                "completed成果不得包含围栏式或缩进式Markdown代码块；正式交付内容必须在默认渲染视图中直接可见。",
            )
    if data.get("artifact_type") == "customer_letter_internal":
        approval_missing = sorted(INTERNAL_LETTER_FIELDS - data.keys())
        if approval_missing:
            add(issues, "error", "approval_metadata_required", document.path, "客户信内部稿缺少业务上下文/外发/审批字段：" + ", ".join(approval_missing))
    if data.get("artifact_type") == "visit_strategy":
        strategy_missing = sorted(strategy_required_fields(data) - data.keys())
        if strategy_missing:
            add(issues, "error", "strategy_context_required", document.path, "交流策略缺少执行上下文字段：" + ", ".join(strategy_missing))
        if data.get("strategy_variant") not in {"scheduled_visit", "account_planning"}:
            add(issues, "error", "strategy_variant_invalid", document.path, "strategy_variant必须为scheduled_visit或account_planning。")
    if data.get("artifact_type") == "briefing_delivery":
        briefing_missing = sorted({"delivery_state", "page_proxy"} - data.keys())
        if briefing_missing:
            add(issues, "error", "briefing_metadata_required", document.path, "一页简报缺少交付字段：" + ", ".join(briefing_missing))
    if data.get("artifact_type") == "customer_letter_external":
        lineage_missing = sorted(EXTERNAL_LINEAGE_FIELDS - data.keys())
        if lineage_missing:
            add(issues, "error", "external_lineage_required", document.path, "客户信外发版缺少谱系字段：" + ", ".join(lineage_missing))
    if data["schema"] != SCHEMA:
        add(issues, "error", "schema_invalid", document.path, f"schema必须为{SCHEMA}。")
    if data["artifact_type"] not in ARTIFACT_TYPES:
        add(issues, "error", "artifact_type_invalid", document.path, "artifact_type不在允许集合。")
    if data["module_status"] not in MODULE_STATUSES:
        add(issues, "error", "module_status_invalid", document.path, "module_status枚举无效。")
    if data["review_status"] not in REVIEW_STATUSES:
        add(issues, "error", "review_status_invalid", document.path, "review_status枚举无效。")
    if data["connector_status"] not in CONNECTOR_STATUSES:
        add(issues, "error", "connector_status_invalid", document.path, "connector_status枚举无效。")
    if data["freshness_status"] not in FRESHNESS_STATUSES:
        add(issues, "error", "freshness_status_invalid", document.path, "freshness_status枚举无效。")
    if not context_id_valid(data["context_id"]):
        add(issues, "error", "context_id_invalid", document.path, "context_id格式应为dcx-YYYYMMDD-8chars。")
    if not run_id_valid(data["latest_run_id"]):
        add(issues, "error", "latest_run_id_invalid", document.path, "latest_run_id格式应为dcr-YYYYMMDDTHHMMSS-4chars。")
    if not safe_component(data["safe_name"]):
        add(issues, "error", "safe_name_invalid", document.path, "safe_name不是1—48字符的安全文件名组件。")
    if not timestamp_valid(data["updated_at"]):
        add(issues, "error", "updated_at_invalid", document.path, "updated_at必须为ISO 8601时间。")
    if not date_valid(data["evidence_cutoff_date"]):
        add(issues, "error", "evidence_cutoff_date_invalid", document.path, "evidence_cutoff_date必须为YYYY-MM-DD。")
    if not IDENTIFIER_RE.fullmatch(data["customer_id"]):
        add(issues, "error", "customer_id_invalid", document.path, "customer_id格式无效。")
    if not data["customer_display_name"].strip():
        add(issues, "error", "customer_display_name_missing", document.path, "customer_display_name不能为空。")
    if not data["organization_scope"].strip():
        add(issues, "error", "organization_scope_missing", document.path, "organization_scope不能为空。")
    if not CONTENT_VERSION_RE.fullmatch(data["content_version"]):
        add(issues, "error", "content_version_invalid", document.path, "content_version必须为正整数。")
    if not data["runtime_owner"].strip():
        add(issues, "error", "runtime_owner_missing", document.path, "runtime_owner不能为空。")
    elif data["runtime_owner"] in {"待确认", "待指定"} and data["module_status"] in TERMINAL_STATUSES:
        severity = "error" if strict else "warning"
        add(issues, severity, "runtime_owner_unassigned", document.path, "终态成果必须指定可追责的runtime_owner。")
    if data["module_status"] == "not_called":
        add(issues, "error", "uncalled_artifact_exists", document.path, "not_called模块不得存在成果文件。")
    if data["review_status"] == "approved" and data["module_status"] != "completed":
        add(issues, "error", "review_state_conflict", document.path, "approved仅能与completed组合。")
    if data["artifact_type"] == "comprehensive_report" and data["review_status"] != "not_required":
        add(issues, "error", "review_not_applicable", document.path, "综合报告的review_status必须为not_required。")
    if data["module_status"] in {"queued", "running"} and data["review_status"] in {"pending", "approved", "changes_requested"}:
        add(issues, "error", "review_state_conflict", document.path, "未完成执行的成果不能进入已提交或已处理审核状态。")
    if data["module_status"] == "completed" and data["artifact_type"] in {
        "institution_research",
        "leader_research",
        "internal_retrieval",
        "visit_strategy",
        "customer_letter_internal",
        "briefing_delivery",
    } and data["review_status"] not in {"pending", "approved", "changes_requested"}:
        add(issues, "error", "review_submission_missing", document.path, "该类completed成果必须进入pending/approved/changes_requested审核状态。")
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
    if data["artifact_type"] != "internal_retrieval" and data["connector_status"] != "not_applicable":
        add(issues, "error", "connector_not_applicable", document.path, "非内部检索成果的connector_status必须为not_applicable。")
    if data["artifact_type"] == "comprehensive_report":
        if data.get("workflow_stage") not in WORKFLOW_STAGES:
            add(issues, "error", "workflow_stage_invalid", document.path, "综合报告必须提供有效workflow_stage。")
        if data.get("route") not in ROUTES:
            add(issues, "error", "route_invalid", document.path, "综合报告route无效。")
        if data.get("depth") not in DEPTHS:
            add(issues, "error", "depth_invalid", document.path, "综合报告depth无效。")
    if data["artifact_type"] == "customer_letter_internal":
        if strict or data["module_status"] in TERMINAL_STATUSES:
            unresolved = sorted(
                key for key in LETTER_CONTEXT_FIELDS if not resolved_business_text(data.get(key, ""))
            )
            if not substantive_letter_field(data.get("letter_purpose", ""), purpose=True):
                unresolved.append("letter_purpose")
            if not substantive_letter_field(data.get("expected_action", ""), purpose=False):
                unresolved.append("expected_action")
            unresolved = sorted(set(unresolved))
            if unresolved:
                add(
                    issues,
                    "error",
                    "letter_context_unresolved",
                    document.path,
                    "客户信进入严格校验或终态前必须明确业务上下文：" + ", ".join(unresolved),
                )
            body_text = normalize_evidence_text(document.body)
            mismatched = sorted(
                key
                for key in LETTER_CONTEXT_FIELDS
                if resolved_business_text(data.get(key, ""))
                and normalize_evidence_text(data[key]) not in body_text
            )
            if mismatched:
                add(issues, "error", "letter_context_body_mismatch", document.path, "客户信结构化业务上下文必须在内部审核摘要中保持一致：" + ", ".join(mismatched))
        if data.get("external_output_required", "false") not in {"true", "false"}:
            add(issues, "error", "external_requirement_invalid", document.path, "external_output_required必须为true或false。")
        approval_values = {key: data.get(key, "") for key in APPROVAL_FIELDS}
        actor_values = {key: data.get(key, "") for key in LETTER_ACTOR_FIELDS}
        fact_values = {key: data.get(key, "") for key in LETTER_FACT_REVIEW_FIELDS}
        revision_values = {key: data.get(key, "") for key in LETTER_REVISION_FIELDS}
        request_values = {key: data.get(key, "") for key in EXTERNAL_REQUEST_FIELDS}
        if any(fact_values.values()):
            missing_fact = sorted(key for key, value in fact_values.items() if not value.strip())
            if missing_fact:
                add(issues, "error", "letter_fact_review_incomplete", document.path, "客户信事实复核谱系不完整：" + ", ".join(missing_fact))
            if fact_values["fact_reviewer_role"] != "evidence_reviewer":
                add(issues, "error", "letter_fact_reviewer_role_invalid", document.path, "客户信事实复核必须由evidence_reviewer完成。")
            if not timestamp_valid(fact_values["fact_reviewed_at"]):
                add(issues, "error", "letter_fact_review_time_invalid", document.path, "fact_reviewed_at必须为带时区ISO 8601时间。")
            fact_version = fact_values["fact_reviewed_content_version"]
            current_version = data["content_version"]
            if (
                not CONTENT_VERSION_RE.fullmatch(fact_version)
                or not CONTENT_VERSION_RE.fullmatch(current_version)
                or int(fact_version) > int(current_version)
                or (data["review_status"] == "pending" and fact_version != current_version)
            ):
                add(issues, "error", "letter_fact_review_version_drift", document.path, "pending内部稿事实复核版本须等于当前版本；approved后可保留早期复核版本但不得晚于当前版本。")
            approved_body = extract_external_body(document)
            if fact_values["fact_reviewed_body_sha256"] != body_sha256(approved_body):
                add(issues, "error", "letter_fact_review_body_drift", document.path, "事实复核后外发正文已变化，必须重新复核。")
            if fact_values["fact_reviewed_context_sha256"] != letter_context_sha256(data):
                add(issues, "error", "letter_fact_review_context_drift", document.path, "事实复核后业务上下文已变化，必须重新复核。")
        if data["review_status"] == "approved":
            if not approval_values["approver"].strip():
                add(issues, "error", "approver_missing", document.path, "approved内部稿必须记录approver。")
            if not timestamp_valid(approval_values["approved_at"]):
                add(issues, "error", "approved_at_invalid", document.path, "approved_at必须为带时区ISO 8601时间。")
            if approval_values["approved_content_version"] != data["content_version"]:
                add(issues, "error", "approval_version_drift", document.path, "approved_content_version必须等于当前content_version。")
            approved_body = extract_external_body(document)
            expected_digest = body_sha256(approved_body) if approved_body is not None else ""
            if not re.fullmatch(r"[0-9a-f]{64}", approval_values["approved_body_sha256"]):
                add(issues, "error", "approval_hash_invalid", document.path, "approved_body_sha256必须为64位小写SHA-256。")
            elif approval_values["approved_body_sha256"] != expected_digest:
                add(issues, "error", "approval_body_drift", document.path, "已批准正文与审批哈希不一致，必须重新审核。")
            if not re.fullmatch(r"[0-9a-f]{64}", approval_values["approved_context_sha256"]):
                add(issues, "error", "approval_context_hash_invalid", document.path, "approved_context_sha256必须为64位小写SHA-256。")
            elif approval_values["approved_context_sha256"] != letter_context_sha256(data):
                add(issues, "error", "approval_context_drift", document.path, "已批准业务上下文与审批哈希不一致，必须重新审核。")
            missing_actor = sorted(key for key, value in actor_values.items() if not value.strip())
            if missing_actor:
                add(issues, "error", "approval_actor_audit_required", document.path, "approved内部稿缺少可信身份谱系：" + ", ".join(missing_actor))
            if not all(fact_values.values()):
                add(issues, "error", "letter_fact_review_required", document.path, "外发审批前必须完成独立、可信的客户信事实复核。")
            if fact_values["fact_reviewer_actor_id"] == actor_values["approver_actor_id"]:
                add(issues, "error", "letter_reviewers_not_independent", document.path, "事实复核人与外发审批人必须是不同actor。")
        elif any(approval_values.values()) or any(actor_values.values()) or any(request_values.values()):
            add(issues, "error", "stale_approval_metadata", document.path, "非approved内部稿不得保留审批、身份或外发请求谱系；修改后应清空并重新审核。")
        if data["review_status"] == "changes_requested" and any(fact_values.values()):
            add(issues, "error", "stale_fact_review_metadata", document.path, "changes_requested内部稿不得保留旧事实复核谱系。")
        if any(revision_values.values()):
            missing_revision = sorted(key for key, value in revision_values.items() if not value.strip())
            if missing_revision:
                add(issues, "error", "letter_revision_lineage_incomplete", document.path, "客户信修订动作谱系不完整：" + ", ".join(missing_revision))
            if not timestamp_valid(revision_values["revision_at"]):
                add(issues, "error", "letter_revision_time_invalid", document.path, "revision_at必须为带时区ISO 8601时间。")
            if not CONTENT_VERSION_RE.fullmatch(revision_values["revision_target_content_version"]):
                add(issues, "error", "letter_revision_target_version_invalid", document.path, "revision_target_content_version无效。")
            for field in ("revision_target_body_sha256", "revision_target_context_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", revision_values[field]):
                    add(issues, "error", "letter_revision_target_hash_invalid", document.path, f"{field}必须为64位小写SHA-256。")
    if data["artifact_type"] in GENERIC_REVIEW_TYPES:
        review_values = {key: data.get(key, "") for key in GENERIC_REVIEW_FIELDS}
        if data["review_status"] == "approved":
            missing_review = sorted(key for key, value in review_values.items() if not value.strip())
            if missing_review:
                add(issues, "error", "review_audit_required", document.path, "approved成果缺少可验证审核记录：" + ", ".join(missing_review))
            if review_values["reviewer"] in {"待确认", "待指定", ""}:
                add(issues, "error", "reviewer_unassigned", document.path, "approved成果必须记录实名审核人或稳定审核角色。")
            if not timestamp_valid(review_values["reviewed_at"]):
                add(issues, "error", "reviewed_at_invalid", document.path, "reviewed_at必须为带时区ISO 8601时间。")
            if review_values["reviewed_content_version"] != data["content_version"]:
                add(issues, "error", "review_version_drift", document.path, "reviewed_content_version必须等于当前content_version。")
            digest = body_sha256(document.body)
            if review_values["reviewed_body_sha256"] != digest:
                add(issues, "error", "review_body_drift", document.path, "审核后正文已变化，必须清空审核戳并重新审核。")
        elif any(review_values.values()):
            add(issues, "error", "stale_review_metadata", document.path, "非approved成果不得保留通用审核戳。")
    if data["artifact_type"] == "briefing_delivery":
        validate_briefing_contract(document, issues)
    if data["artifact_type"] == "visit_strategy" and (strict or data["module_status"] in TERMINAL_STATUSES):
        required_strategy_fields = strategy_required_fields(data) - {"strategy_variant"}
        unresolved = sorted(
            key for key in required_strategy_fields if not resolved_business_text(data.get(key, ""))
        )
        if unresolved:
            add(
                issues,
                "error",
                "strategy_context_unresolved",
                document.path,
                "交流策略进入严格校验或终态前必须明确对象/目标/最小推进动作：" + ", ".join(unresolved),
            )
        body_text = normalize_evidence_text(document.body)
        mismatched = sorted(
            key
            for key in required_strategy_fields
            if resolved_business_text(data.get(key, ""))
            and normalize_evidence_text(data[key]) not in body_text
        )
        if mismatched:
            add(issues, "error", "strategy_context_body_mismatch", document.path, "交流策略结构化上下文必须与正文一致：" + ", ".join(mismatched))
    if data["artifact_type"] == "customer_letter_external":
        if data["module_status"] != "completed" or data["review_status"] != "approved":
            add(issues, "error", "external_letter_unapproved", document.path, "外发版必须为completed/approved。")
        if data["content_version"] != "1":
            add(issues, "error", "external_content_version_invalid", document.path, "派生外发版content_version固定为1；新版本须归档旧文件后重新生成。")
        if data["connector_status"] != "not_applicable":
            add(issues, "error", "external_connector_invalid", document.path, "外发版connector_status须为not_applicable。")
        if data["freshness_status"] != "current":
            add(issues, "error", "external_stale", document.path, "外发版freshness_status必须为current。")
    for legacy in ("version", "owner"):
        if legacy in data:
            add(issues, "error", "legacy_metadata", document.path, f"禁用旧字段{legacy}。")
    placeholders = sorted(set(PLACEHOLDER_RE.findall(document.text)))
    if placeholders:
        severity = "error" if placeholder_errors or strict or data["module_status"] in TERMINAL_STATUSES else "warning"
        add(issues, severity, "placeholder_remaining", document.path, "仍有占位符：" + ", ".join(placeholders[:5]))


def split_table_cells(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", raw)]


def letter_review_history_rows(letter: Document, issues: list[Issue]) -> list[list[str]]:
    lines = letter.body.splitlines()
    headings = [index for index, line in enumerate(lines) if line.strip() == LETTER_REVIEW_HEADING]
    if len(headings) != 1:
        add(issues, "error", "letter_review_history_section_invalid", letter.path, "内部稿必须恰有一个版本与审核记录章节。")
        return []
    expected_header = ["updated_at", "content_version", "latest_run_id", "变更摘要", "runtime_owner", "review_status"]
    rows: list[list[str]] = []
    for line in lines[headings[0] + 1 :]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if cells == expected_header or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if len(cells) != 6:
            add(issues, "error", "letter_review_history_row_shape", letter.path, "版本与审核记录必须恰有6列。")
            continue
        rows.append(cells)
    if not rows:
        add(issues, "error", "letter_review_history_empty", letter.path, "内部稿至少需要一条版本与审核记录。")
    return rows


def validate_letter_review_history(by_type: dict[str, Document], issues: list[Issue], strict: bool) -> None:
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
            add(issues, "error", "letter_review_history_time_invalid", letter.path, f"审核记录{run_id}的updated_at无效。")
            parsed_time = None
        else:
            parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if not CONTENT_VERSION_RE.fullmatch(version):
            add(issues, "error", "letter_review_history_version_invalid", letter.path, f"审核记录{run_id}的content_version无效。")
            numeric_version = None
        else:
            numeric_version = int(version)
        if not run_id_valid(run_id) or run_id in seen_runs:
            add(issues, "error", "letter_review_history_run_invalid", letter.path, f"审核记录run_id无效或重复：{run_id!r}。")
        seen_runs.add(run_id)
        if not summary.strip() or not owner.strip():
            add(issues, "error", "letter_review_history_content_missing", letter.path, f"审核记录{run_id}的摘要与runtime_owner不能为空。")
        if review_status not in REVIEW_STATUSES:
            add(issues, "error", "letter_review_history_status_invalid", letter.path, f"审核记录{run_id}的review_status无效。")
        if previous_version is not None and numeric_version is not None and numeric_version != previous_version + 1:
            add(issues, "error", "letter_review_history_version_sequence", letter.path, f"审核记录{run_id}的版本必须紧接前一版本。")
        if previous_time is not None and parsed_time is not None and parsed_time < previous_time:
            add(issues, "error", "letter_review_history_time_sequence", letter.path, f"审核记录{run_id}早于前一条记录。")
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
            add(issues, "error", "letter_review_history_latest_mismatch", letter.path, "最新版本与审核记录必须与内部稿frontmatter的时间、版本、run、owner和审核状态一致。")


def collect_ledgers(
    documents: list[Document], issues: list[Issue]
) -> tuple[dict[str, ClaimDefinition], dict[str, SourceDefinition]]:
    """Collect definitions only from the two authoritative research ledgers.

    Claim/source-shaped references in downstream delivery tables are not
    definitions and must never be promoted into the evidence registry.
    """

    claims: dict[str, ClaimDefinition] = {}
    sources: dict[str, SourceDefinition] = {}
    claim_header = [
        "claim_id", "claim_type", "provenance", "verification_status", "主张内容",
        "时间/口径", "支持 source_id", "反证 source_id", "置信度", "下游影响/备注",
    ]
    source_header = [
        "source_id", "标题/文档名", "发布者/提供者", "URL/稳定定位", "发布/更新日期",
        "访问日期", "来源等级", "source_group", "权限", "适用客户/项目", "备注",
        "source_fingerprint", "upstream_id", "external_use",
    ]
    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if artifact_type not in RESEARCH_PREFIX:
            continue
        sections = h2_sections(document.body)
        claim_tables = [
            rows
            for body in sections.get("主张台账", [])
            for header, rows in markdown_table_blocks(body)
            if header == claim_header
        ]
        source_tables = [
            rows
            for body in sections.get("来源台账", [])
            for header, rows in markdown_table_blocks(body)
            if header == source_header
        ]
        for cells in [row for rows in claim_tables for row in rows]:
            if cells and CLAIM_RE.fullmatch(cells[0]) and not any("{{" in cell for cell in cells):
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
                    add(issues, "error", "claim_duplicate", document.path, f"claim_id重复定义：{claim_id}")
                else:
                    line = "| " + " | ".join(cells) + " |"
                    claims[claim_id] = ClaimDefinition(claim_id, document, cells, line)
        for cells in [row for rows in source_tables for row in rows]:
            if cells and SOURCE_RE.fullmatch(cells[0]) and not any("{{" in cell for cell in cells):
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
                    add(issues, "error", "source_duplicate", document.path, f"source_id重复定义：{source_id}")
                else:
                    line = "| " + " | ".join(cells) + " |"
                    sources[source_id] = SourceDefinition(source_id, document, cells, line)
    return claims, sources


def body_without_placeholders(document: Document) -> str:
    return PLACEHOLDER_RE.sub("", document.body)


def normalize_evidence_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def normalize_locator(value: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    stable = re.fullmatch(
        r"(?:urn|record|document|dataset|ragflow|archive):[A-Za-z0-9][A-Za-z0-9._~:/?#@!$&'*+,;=%-]*",
        normalized,
        re.IGNORECASE,
    )
    if stable:
        return normalized.casefold()
    try:
        parsed = urlsplit(normalized)
        parsed_port = parsed.port
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return ""
        host = (parsed.hostname or "").casefold()
        if not host or parsed.username is not None or parsed.password is not None:
            return ""
        default_port = (parsed.scheme.casefold(), parsed_port) in {("http", 80), ("https", 443)}
        port = f":{parsed_port}" if parsed_port and not default_port else ""
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        return urlunsplit((parsed.scheme.casefold(), host + port, path, query, ""))
    except ValueError:
        return ""


SOURCE_LEDGER_MARKUP_RE = re.compile(
    r"(?:!?\[[^\]\n]*\]\s*(?:\([^\)\n]*\)|\[[^\]\n]*\])|`|<[^>\n]+>)"
)


def source_ledger_scalar_safe(value: str) -> bool:
    return bool(
        value
        and value == re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
        and not SOURCE_LEDGER_MARKUP_RE.search(value)
        and not any(unicodedata.category(char) == "Cf" for char in value)
    )


def unresolved_evidence_value(value: str) -> bool:
    normalized = normalize_evidence_text(value)
    return normalized in {"", "无", "未知", "unknown", "待确认", "待补充", "n/a", "na", "none"}


def source_fingerprint_valid(value: str) -> bool:
    fingerprint = value.strip()
    if (
        unresolved_evidence_value(fingerprint)
        or normalize_evidence_text(fingerprint).startswith("unknown:")
        or any(char.isspace() for char in fingerprint)
    ):
        return False
    return bool(SHA256_FINGERPRINT_RE.fullmatch(fingerprint))


def supporting_sources(
    definition: ClaimDefinition,
    sources: dict[str, SourceDefinition],
) -> list[SourceDefinition]:
    if len(definition.cells) < 7:
        return []
    return [sources[source_id] for source_id in SOURCE_RE.findall(definition.cells[6]) if source_id in sources]


def requires_internal_authorization(
    claims: Mapping[str, ClaimDefinition] | None,
    sources: Mapping[str, SourceDefinition] | None,
) -> bool:
    """Return whether the evidence ledger contains internal/restricted data."""

    return bool(
        any(len(item.cells) >= 3 and item.cells[2] == "N" for item in (claims or {}).values())
        or any(
            len(item.cells) >= 9
            and (item.cells[6] == "internal" or item.cells[8] in {"internal-authorized", "restricted"})
            for item in (sources or {}).values()
        )
    )


def f2_independence_values(source: SourceDefinition) -> tuple[str, str, str, str] | None:
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
            add(issues, "error", "legacy_evidence_id", document.path, "禁用旧证据ID：" + ", ".join(legacy))
        for claim_id in CLAIM_RE.findall(cleaned):
            claim_refs.setdefault(claim_id, set()).add(document.path)
        for source_id in SOURCE_RE.findall(cleaned):
            source_refs.setdefault(source_id, set()).add(document.path)

    for claim_id, paths in sorted(claim_refs.items()):
        if claim_id not in claims:
            for path in paths:
                add(issues, "error", "claim_orphan_reference", path, f"引用了未定义claim_id：{claim_id}")
    for source_id, paths in sorted(source_refs.items()):
        if source_id not in sources:
            for path in paths:
                add(issues, "error", "source_orphan_reference", path, f"引用了未定义source_id：{source_id}")

    for claim_id, definition in claims.items():
        cells = definition.cells
        if len(cells) != 10:
            add(issues, "error", "claim_row_shape", definition.document.path, f"{claim_id}主张台账必须恰有10列；正文竖线须写为\\|。")
            continue
        if any(not source_ledger_scalar_safe(cell) for cell in cells):
            add(
                issues,
                "error",
                "claim_ledger_markup_forbidden",
                definition.document.path,
                f"{claim_id}主张台账只允许可见纯文本与受控ID，不得包含Markdown链接/图片、代码标记、HTML或隐藏字符。",
            )
        claim_type, provenance, verification = cells[1], cells[2], cells[3]
        if claim_type not in CLAIM_TYPES:
            add(issues, "error", "claim_type_invalid", definition.document.path, f"{claim_id} claim_type无效：{claim_type}")
        if provenance not in PROVENANCE_VALUES:
            add(issues, "error", "provenance_invalid", definition.document.path, f"{claim_id} provenance无效：{provenance}")
        if provenance == "N" and (
            not claim_id.startswith("CLM-N-")
            or definition.document.frontmatter.get("artifact_type") != "internal_retrieval"
        ):
            add(
                issues,
                "error",
                "internal_claim_carrier_invalid",
                definition.document.path,
                f"{claim_id}的provenance=N只能由internal_retrieval中的CLM-N-*承载。",
            )
        if verification not in VERIFICATION_STATUSES:
            add(issues, "error", "verification_invalid", definition.document.path, f"{claim_id} verification_status无效：{verification}")
        if claim_type == "F" and verification != "verified_single":
            add(issues, "error", "fact_mapping_invalid", definition.document.path, f"{claim_id}: F必须对应verified_single。")
        if claim_type == "F2" and verification != "corroborated":
            add(issues, "error", "fact2_mapping_invalid", definition.document.path, f"{claim_id}: F2必须对应corroborated。")
        if unresolved_evidence_value(cells[4]):
            add(issues, "error", "claim_text_missing", definition.document.path, f"{claim_id}主张内容不能为空或待确认。")
        if unresolved_evidence_value(cells[5]):
            add(issues, "error", "claim_time_scope_missing", definition.document.path, f"{claim_id}必须记录时间/口径。")
        if cells[8] not in {"高", "中", "低", "不可用"}:
            add(issues, "error", "claim_confidence_invalid", definition.document.path, f"{claim_id}置信度必须为高/中/低/不可用。")
        if verification in {"conflicted", "stale", "invalidated", "unusable"} and cells[8] == "高":
            add(issues, "error", "claim_confidence_conflict", definition.document.path, f"{claim_id}处于{verification}时不得标高置信度。")
        support_ids = SOURCE_RE.findall(cells[6])
        canonical_support_refs = ", ".join(sorted(set(support_ids)))
        if not support_ids or cells[6] != canonical_support_refs:
            add(
                issues,
                "error",
                "claim_support_refs_invalid",
                definition.document.path,
                f"{claim_id}支持来源必须只写去重排序的source_id列表，并以逗号空格分隔。",
            )
        if not support_ids:
            add(issues, "error", "claim_source_missing", definition.document.path, f"{claim_id}没有支持source_id。")
        counter_ids = SOURCE_RE.findall(cells[7])
        canonical_counter_refs = "无" if not counter_ids else ", ".join(sorted(set(counter_ids)))
        if cells[7] != canonical_counter_refs:
            add(
                issues,
                "error",
                "claim_counter_refs_invalid",
                definition.document.path,
                f"{claim_id}反证来源只能写“无”或去重排序的source_id列表。",
            )
        for source_id in support_ids + counter_ids:
            if source_id not in sources:
                add(issues, "error", "claim_source_orphan", definition.document.path, f"{claim_id}引用未定义来源{source_id}。")
        expected_prefix = claim_id.split("-")[1]
        for source_id in support_ids:
            if source_id.split("-")[1] != expected_prefix:
                add(issues, "warning", "claim_source_prefix_mismatch", definition.document.path, f"{claim_id}的支持来源{source_id}跨台账前缀。")
        if verification == "conflicted" and not SOURCE_RE.findall(cells[7]):
            add(issues, "error", "conflicted_counter_source_missing", definition.document.path, f"{claim_id}标conflicted时必须记录反证source_id。")
        if claim_type != "H":
            for source in supporting_sources(definition, sources):
                if len(source.cells) >= 7 and source.cells[6] == "C":
                    code = "fact_source_level_unsafe" if claim_type in {"F", "F2"} else "c_source_claim_type_unsafe"
                    add(issues, "error", code, definition.document.path, f"{claim_id}不能由C级线索支撑{claim_type}主张；C级来源只允许支撑H：{source.source_id}。")
        if claim_type == "F2":
            unique_support = list(dict.fromkeys(support_ids))
            if len(unique_support) < 2:
                add(issues, "error", "fact2_sources_insufficient", definition.document.path, f"{claim_id}: F2至少需要两个支持来源。")
            # Fourfold independence is evaluated later from independently
            # verified machine-source receipts.  Markdown cells are display
            # projections and must never establish F2 independence.


def validate_machine_evidence(
    root: Path,
    documents: list[Document],
    by_type: dict[str, Document],
    claims: dict[str, ClaimDefinition],
    sources: dict[str, SourceDefinition],
    issues: list[Issue],
    strict: bool,
    current_time: datetime | None = None,
    validation_profile: str = "candidate",
) -> None:
    evidence_path = root / "runtime" / "evidence-manifest.json"
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    require_machine = validation_profile != "scaffold"
    evidence_run_id = ""
    try:
        runtime_manifest = load_manifest(root, required=False)
    except (OSError, UnicodeError, TxError):
        runtime_manifest = None
    if isinstance(runtime_manifest, dict):
        evidence_run_id = str(runtime_manifest.get("evidence_run_id", ""))
    runtime_authorization = (
        runtime_manifest.get("authorization", {})
        if isinstance(runtime_manifest, dict)
        and isinstance(runtime_manifest.get("authorization"), dict)
        else {}
    )
    if not evidence_path.exists():
        if require_machine:
            add(issues, "error", "machine_evidence_missing", evidence_path, "candidate/release校验要求runtime/evidence-manifest.json。")
        evidence = {
            "schema": "discovery-call-evidence-manifest/v1",
            "context_id": total.frontmatter.get("context_id", ""),
            "run_id": total.frontmatter.get("latest_run_id", ""),
            "business_mode": total.frontmatter.get("business_mode", ""),
            "customer_id": total.frontmatter.get("customer_id", ""),
            "sources": {},
            "claims": {},
        }
    else:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            add(issues, "error", "machine_evidence_invalid", evidence_path, str(exc))
            return
    if not isinstance(evidence, dict) or evidence.get("schema") != "discovery-call-evidence-manifest/v1":
        add(issues, "error", "machine_evidence_schema_invalid", evidence_path, "evidence manifest schema无效。")
        return
    if not require_machine:
        # init/resume only scaffolds the next run.  Historical evidence may be
        # stale or bound to the prior intake until the candidate phase replaces
        # and revalidates the complete four-file bundle.
        return
    for field, expected in (
        ("context_id", total.frontmatter.get("context_id", "")),
        # A later governance action advances latest_run_id without rewriting
        # the research snapshot.  Bind machine evidence to the explicit
        # research lineage carried by runtime/manifest.json.
        ("run_id", evidence_run_id or evidence.get("run_id", "")),
        ("business_mode", total.frontmatter.get("business_mode", "")),
        ("customer_id", total.frontmatter.get("customer_id", "")),
    ):
        if evidence.get(field) != expected:
            add(issues, "error", "machine_evidence_context_drift", evidence_path, f"{field}与当前成果不一致。")
    machine_sources = evidence.get("sources")
    machine_claims = evidence.get("claims")
    if not isinstance(machine_sources, dict) or not isinstance(machine_claims, dict):
        add(issues, "error", "machine_evidence_records_invalid", evidence_path, "sources和claims必须为对象。")
        return
    cache_entries: dict[str, object] = {}
    cache_path = root / "runtime" / "source-cache.json"
    if cache_path.is_file():
        try:
            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cache_payload, dict) and isinstance(cache_payload.get("entries"), dict):
                cache_entries = cache_payload["entries"]
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    required_source_fields = {
        "source_id", "source_title", "publisher_or_provider", "locator",
        "canonical_locator", "final_url", "cache_key", "publication_or_update_date",
        "access_date", "source_group", "applicable_scope", "notes", "upstream_id",
        "source_fingerprint", "content_sha256", "retrieved_at", "capture_method", "length",
        "published_at", "source_updated_at", "internal_recorded_at", "source_level",
        "permission", "external_use", "tenant_id", "project_id",
    }
    source_verification_time = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    verified_machine_sources: dict[str, dict[str, object]] = {}
    verified_source_receipt_hashes: dict[str, str] = {}
    for source_id, definition in sources.items():
        record = machine_sources.get(source_id)
        if not isinstance(record, dict):
            if require_machine:
                add(issues, "error", "machine_source_missing", evidence_path, f"缺少{source_id}的内容快照绑定。")
            continue
        missing = sorted(required_source_fields - set(record))
        if missing:
            add(issues, "error", "machine_source_fields_missing", evidence_path, f"{source_id}缺少：{', '.join(missing)}。")
            continue
        digest = str(record.get("content_sha256", ""))
        fingerprint = str(record.get("source_fingerprint", ""))
        if record.get("source_id") != source_id or not re.fullmatch(r"[0-9a-f]{64}", digest) or fingerprint != f"sha256:{digest}":
            add(issues, "error", "machine_source_content_unbound", evidence_path, f"{source_id}必须绑定内容SHA-256。")
        receipt_verified = False
        if require_machine:
            receipt = record.get("capture_receipt")
            if not isinstance(receipt, dict):
                add(
                    issues,
                    "error",
                    "source_capture_receipt_missing",
                    evidence_path,
                    f"{source_id}缺少宿主签名的来源捕获收据；不得仅凭本地摘要自证。",
                )
            else:
                try:
                    verified_receipt = verify_source_capture_receipt(
                        receipt,
                        expected={
                            "source_id": source_id,
                            "source_title": record.get("source_title"),
                            "publisher_or_provider": record.get("publisher_or_provider"),
                            "locator": record.get("locator"),
                            "final_url": record.get("final_url"),
                            "canonical_locator": record.get("canonical_locator"),
                            "publication_or_update_date": record.get("publication_or_update_date"),
                            "access_date": record.get("access_date"),
                            "content_sha256": record.get("content_sha256"),
                            "length": record.get("length"),
                            "capture_method": record.get("capture_method"),
                            "retrieved_at": record.get("retrieved_at"),
                            "published_at": record.get("published_at"),
                            "source_updated_at": record.get("source_updated_at"),
                            "internal_recorded_at": record.get("internal_recorded_at"),
                            "source_level": record.get("source_level"),
                            "source_group": record.get("source_group"),
                            "permission": record.get("permission"),
                            "applicable_scope": record.get("applicable_scope"),
                            "notes": record.get("notes"),
                            "upstream_id": record.get("upstream_id"),
                            "external_use": record.get("external_use"),
                            "tenant_id": record.get("tenant_id"),
                            "run_id": evidence.get("run_id"),
                            "customer_id": evidence.get("customer_id"),
                            "project_id": record.get("project_id"),
                        },
                        at=source_verification_time,
                    )
                    receipt_verified = True
                    verified_source_receipt_hashes[source_id] = verified_receipt.receipt_sha256
                except CapabilityReceiptError as exc:
                    add(
                        issues,
                        "error",
                        "source_capture_receipt_invalid",
                        evidence_path,
                        f"{source_id}来源捕获收据验证失败：{exc}",
                    )
        ledger_binding_valid = len(definition.cells) == 14
        if len(definition.cells) >= 12 and definition.cells[11] != fingerprint:
            ledger_binding_valid = False
            add(issues, "error", "source_fingerprint_machine_drift", definition.document.path, f"{source_id}台账指纹与机器快照不一致。")
        if len(definition.cells) == 14:
            ledger_binding = {
                "source_title": definition.cells[1],
                "publisher_or_provider": definition.cells[2],
                "locator": definition.cells[3],
                "publication_or_update_date": definition.cells[4],
                "access_date": definition.cells[5],
                "source_level": definition.cells[6],
                "source_group": definition.cells[7],
                "permission": definition.cells[8],
                "applicable_scope": definition.cells[9],
                "notes": definition.cells[10],
                "upstream_id": definition.cells[12],
                "external_use": definition.cells[13],
            }
            for field, expected in ledger_binding.items():
                if record.get(field) != expected:
                    ledger_binding_valid = False
                    add(
                        issues,
                        "error",
                        "source_ledger_machine_drift",
                        definition.document.path,
                        f"{source_id}.{field}与Markdown来源台账不一致。",
                    )
            ledger_locator = definition.cells[3]
            record_locator = str(record.get("locator", ""))
            canonical = str(record.get("canonical_locator", ""))
            if (
                not source_ledger_scalar_safe(ledger_locator)
                or normalize_locator(ledger_locator) != canonical
                or normalize_locator(record_locator) != canonical
                or not normalize_locator(str(record.get("final_url", "")))
            ):
                ledger_binding_valid = False
                add(
                    issues,
                    "error",
                    "source_locator_machine_drift",
                    definition.document.path,
                    f"{source_id}的raw locator必须逐字绑定验签记录，且canonical_locator必须由locator规范化生成。",
                )
        sensitive_source = bool(
            record.get("source_level") == "internal"
            or record.get("permission") in {"internal-authorized", "restricted"}
        )
        if sensitive_source:
            expected_tenant = runtime_authorization.get("tenant_id")
            expected_project = runtime_authorization.get("project_id")
            if (
                not expected_tenant
                or not expected_project
                or record.get("tenant_id") != expected_tenant
                or record.get("project_id") != expected_project
                or evidence.get("project_id") != expected_project
            ):
                add(
                    issues,
                    "error",
                    "machine_source_authorization_scope_drift",
                    evidence_path,
                    f"{source_id}内部/受限来源必须绑定当前manifest的tenant_id与project_id。",
                )
        cache_key = str(record.get("cache_key", ""))
        cache = cache_entries.get(cache_key)
        snapshot_fields = (
            "cache_key",
            "source_title",
            "publisher_or_provider",
            "locator",
            "canonical_locator",
            "final_url",
            "publication_or_update_date",
            "access_date",
            "source_group",
            "applicable_scope",
            "notes",
            "upstream_id",
            "source_fingerprint",
            "content_sha256",
            "retrieved_at",
            "capture_method",
            "length",
            "published_at",
            "source_updated_at",
            "internal_recorded_at",
            "source_level",
            "permission",
            "external_use",
            "tenant_id",
            "project_id",
            "capture_receipt",
        )
        if not isinstance(cache, dict) or any(cache.get(field) != record.get(field) for field in snapshot_fields):
            add(issues, "error", "source_cache_binding_missing", evidence_path, f"{source_id}未绑定到同内容的source-cache快照。")
        canonical = str(record.get("canonical_locator", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", cache_key) or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != cache_key:
            add(issues, "error", "source_cache_key_invalid", evidence_path, f"{source_id}.cache_key必须由canonical_locator计算。")
        if record.get("capture_method") not in {"raw-bytes-v1", "text-nfc-lf-utf8-v1"}:
            add(issues, "error", "source_capture_method_invalid", evidence_path, f"{source_id}.capture_method无效。")
        if not isinstance(record.get("length"), int) or isinstance(record.get("length"), bool) or int(record.get("length", -1)) < 0:
            add(issues, "error", "source_capture_length_invalid", evidence_path, f"{source_id}.length无效。")
        if receipt_verified:
            verified_machine_sources[source_id] = record
    if require_machine:
        for source_id in sorted(set(machine_sources) - set(sources)):
            add(issues, "error", "machine_source_orphan", evidence_path, f"机器清单含未在Markdown台账定义的{source_id}。")

    for claim_id, definition in claims.items():
        if len(definition.cells) < 7 or definition.cells[1] != "F2":
            continue
        support_ids = list(dict.fromkeys(SOURCE_RE.findall(definition.cells[6])))
        signed_values: list[tuple[str, str, str, str]] = []
        for supporting_id in support_ids:
            source = verified_machine_sources.get(supporting_id)
            if source is None:
                continue
            group = normalize_evidence_text(str(source.get("source_group", "")))
            canonical = str(source.get("canonical_locator", ""))
            digest = str(source.get("content_sha256", ""))
            upstream = normalize_evidence_text(str(source.get("upstream_id", "")))
            if (
                unresolved_evidence_value(group)
                or group.startswith("unknown:")
                or not canonical
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or unresolved_evidence_value(upstream)
                or upstream.startswith("unknown:")
            ):
                continue
            signed_values.append((group, canonical, digest, upstream))
        if len({item[0] for item in signed_values}) < 2:
            add(issues, "error", "fact2_source_groups_not_independent", definition.document.path, f"{claim_id}: F2至少需要两个验签后不同的source_group。")
        if len({item[1] for item in signed_values}) < 2:
            add(issues, "error", "fact2_locator_not_independent", definition.document.path, f"{claim_id}: F2至少需要两个验签后不同的canonical_locator。")
        if len({item[2] for item in signed_values}) < 2:
            add(issues, "error", "fact2_source_fingerprint_not_independent", definition.document.path, f"{claim_id}: F2至少需要两个验签后不同的内容SHA-256。")
        if len({item[3] for item in signed_values}) < 2:
            add(issues, "error", "fact2_upstream_not_independent", definition.document.path, f"{claim_id}: F2至少需要两个验签后不同的upstream_id。")
        if not any(
            all(left[index] != right[index] for index in range(4))
            for left_index, left in enumerate(signed_values)
            for right in signed_values[left_index + 1 :]
        ):
            add(
                issues,
                "error",
                "fact2_sources_not_fourfold_independent",
                definition.document.path,
                f"{claim_id}: F2必须存在同一对已验签来源，其source_group、canonical_locator、content_sha256、upstream_id四项同时有效且互不相同。",
            )

    profiles = load_business_profiles()
    profile = profiles.get(total.frontmatter.get("business_mode", ""), {})
    ttl_profile = profile.get("ttl_days", {}) if isinstance(profile, dict) else {}
    now = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    referenced_claims = {
        claim_id
        for artifact_type, document in by_type.items()
        if artifact_type in {"comprehensive_report", "visit_strategy", "customer_letter_internal", "customer_letter_external", "briefing_delivery"}
        for claim_id in CLAIM_RE.findall(body_without_placeholders(document))
    }
    required_claim_fields = {
        "claim_id", "information_type", "ttl_class", "evidence_anchor_at", "date_basis",
        "verified_at", "ttl_days", "expires_at", "claim_type", "provenance",
        "verification_status", "claim_text", "time_scope", "supporting_source_refs",
        "supporting_source_ids", "counter_source_refs", "counter_source_ids",
        "supporting_source_receipt_sha256s", "confidence", "downstream_impact",
    }
    for claim_id, definition in claims.items():
        record = machine_claims.get(claim_id)
        if not isinstance(record, dict):
            if require_machine:
                add(issues, "error", "machine_claim_missing", evidence_path, f"缺少{claim_id}的逐claim TTL记录。")
            continue
        missing = sorted(required_claim_fields - set(record))
        if missing:
            add(issues, "error", "machine_claim_fields_missing", evidence_path, f"{claim_id}缺少：{', '.join(missing)}。")
            continue
        ttl_class = str(record.get("ttl_class", ""))
        information_type = str(record.get("information_type", ""))
        if record.get("claim_id") != claim_id or ttl_class not in {"institution", "leader", "procurement", "internal"} or information_type != ttl_class:
            add(issues, "error", "claim_ttl_class_invalid", evidence_path, f"{claim_id}的信息类型/TTL分类无效。")
        expected_ttl = ttl_profile.get(ttl_class) if isinstance(ttl_profile, dict) else None
        ttl_days = record.get("ttl_days")
        if not isinstance(ttl_days, int) or isinstance(ttl_days, bool) or ttl_days < 1 or expected_ttl != ttl_days:
            add(issues, "error", "claim_ttl_policy_drift", evidence_path, f"{claim_id}.ttl_days必须等于当前模式{ttl_class}策略{expected_ttl}。")
            continue
        try:
            anchor = datetime.fromisoformat(str(record.get("evidence_anchor_at", "")).replace("Z", "+00:00"))
            verified = datetime.fromisoformat(str(record.get("verified_at", "")).replace("Z", "+00:00"))
            expires = datetime.fromisoformat(str(record.get("expires_at", "")).replace("Z", "+00:00"))
        except ValueError:
            add(issues, "error", "claim_ttl_timestamp_invalid", evidence_path, f"{claim_id}的TTL时间必须为带时区ISO 8601。")
            continue
        if any(value.tzinfo is None for value in (anchor, verified, expires)):
            add(issues, "error", "claim_ttl_timestamp_invalid", evidence_path, f"{claim_id}的TTL时间缺少时区。")
            continue
        ttl_ceiling = anchor + timedelta(days=ttl_days)
        if expires > ttl_ceiling or expires <= anchor:
            add(issues, "error", "claim_expiry_recompute_mismatch", evidence_path, f"{claim_id}.expires_at必须晚于锚点且不得超过evidence_anchor_at+ttl_days。")
        if anchor > verified:
            add(issues, "error", "claim_anchor_after_verification", evidence_path, f"{claim_id}.evidence_anchor_at晚于verified_at。")
        if anchor > now:
            add(issues, "error", "claim_anchor_in_future", evidence_path, f"{claim_id}.evidence_anchor_at位于未来。")
        if verified > now:
            add(issues, "error", "claim_verified_in_future", evidence_path, f"{claim_id}.verified_at位于未来。")
        if claim_id in referenced_claims and expires <= now:
            add(issues, "error", "referenced_claim_expired", definition.document.path, f"下游引用的{claim_id}已过期，必须刷新或移除。")
        if record.get("date_basis") not in {"published_at", "updated_at", "retrieved_at", "internal_recorded_at"}:
            add(issues, "error", "claim_date_basis_invalid", evidence_path, f"{claim_id}.date_basis无效。")
        support_ids = sorted(set(SOURCE_RE.findall(definition.cells[6] if len(definition.cells) > 6 else "")))
        machine_support = record.get("supporting_source_ids")
        if not isinstance(machine_support, list) or sorted(set(map(str, machine_support))) != support_ids:
            add(issues, "error", "claim_support_machine_drift", evidence_path, f"{claim_id}支持来源与Markdown台账不一致。")
        if any(source_id not in verified_machine_sources for source_id in support_ids):
            add(
                issues,
                "error",
                "claim_support_receipt_unverified",
                evidence_path,
                f"{claim_id}的全部支持来源必须先通过独立宿主source-capture receipt验签。",
            )
        expected_receipt_hashes = {
            source_id: verified_source_receipt_hashes[source_id]
            for source_id in support_ids
            if source_id in verified_source_receipt_hashes
        }
        if record.get("supporting_source_receipt_sha256s") != expected_receipt_hashes:
            add(
                issues,
                "error",
                "claim_support_receipt_binding_drift",
                evidence_path,
                f"{claim_id}必须逐来源绑定本次验签source-capture receipt的完整信封摘要。",
            )
        counter_ids = sorted(set(SOURCE_RE.findall(definition.cells[7] if len(definition.cells) > 7 else "")))
        claim_binding = {
            "claim_type": definition.cells[1],
            "provenance": definition.cells[2],
            "verification_status": definition.cells[3],
            "claim_text": definition.cells[4],
            "time_scope": definition.cells[5],
            "supporting_source_refs": definition.cells[6],
            "counter_source_refs": definition.cells[7],
            "confidence": definition.cells[8],
            "downstream_impact": definition.cells[9],
        }
        drift_fields = [field for field, value in claim_binding.items() if record.get(field) != value]
        if record.get("counter_source_ids") != counter_ids:
            drift_fields.append("counter_source_ids")
        if drift_fields:
            add(
                issues,
                "error",
                "claim_ledger_machine_drift",
                definition.document.path,
                f"{claim_id}主张台账与候选machine claim逐列不一致：{', '.join(sorted(set(drift_fields)))}。",
            )
        basis_field = {
            "retrieved_at": "retrieved_at",
            "published_at": "published_at",
            "updated_at": "source_updated_at",
            "internal_recorded_at": "internal_recorded_at",
        }.get(str(record.get("date_basis", "")))
        support_anchors: list[datetime] = []
        if basis_field:
            for supporting_id in support_ids:
                supporting = machine_sources.get(supporting_id)
                if not isinstance(supporting, dict) or not supporting.get(basis_field):
                    continue
                try:
                    supporting_at = datetime.fromisoformat(
                        str(supporting[basis_field]).replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if supporting_at.tzinfo is not None:
                    support_anchors.append(supporting_at)
        if basis_field and (not support_anchors or anchor != max(support_anchors)):
            add(
                issues,
                "error",
                "claim_anchor_source_drift",
                evidence_path,
                f"{claim_id}.evidence_anchor_at必须等于支持来源中最新的{basis_field}。",
            )
    if require_machine:
        for claim_id in sorted(set(machine_claims) - set(claims)):
            add(issues, "error", "machine_claim_orphan", evidence_path, f"机器清单含未在Markdown台账定义的{claim_id}。")

    for source_id, definition in sources.items():
        if len(definition.cells) != 14:
            add(issues, "error", "source_row_shape", definition.document.path, f"{source_id}来源台账必须恰有14列；正文竖线须写为\\|。")
        else:
            locator = definition.cells[3]
            level = definition.cells[6]
            source_group = definition.cells[7]
            permission = definition.cells[8]
            fingerprint = definition.cells[11]
            upstream_id = definition.cells[12]
            external_use = definition.cells[13]
            if any(not source_ledger_scalar_safe(cell) for cell in definition.cells):
                add(
                    issues,
                    "error",
                    "source_ledger_markup_forbidden",
                    definition.document.path,
                    f"{source_id}来源台账只允许可见纯文本与raw locator，不得包含Markdown链接/图片、代码标记、HTML或隐藏字符。",
                )
            if unresolved_evidence_value(definition.cells[1]):
                add(issues, "error", "source_title_missing", definition.document.path, f"{source_id}标题/文档名不能为空或待确认。")
            if unresolved_evidence_value(definition.cells[2]):
                add(issues, "error", "source_publisher_missing", definition.document.path, f"{source_id}发布者/提供者不能为空或待确认。")
            if not definition.cells[4].strip():
                add(issues, "error", "source_publish_date_missing", definition.document.path, f"{source_id}必须记录发布/更新日期或明确写未标注。")
            if not date_valid(definition.cells[5]):
                add(issues, "error", "source_access_date_invalid", definition.document.path, f"{source_id}访问日期必须为YYYY-MM-DD。")
            if unresolved_evidence_value(definition.cells[9]):
                add(issues, "error", "source_scope_missing", definition.document.path, f"{source_id}适用客户/项目不能为空或待确认。")
            if definition.cells[10] not in {
                "none", "capture_limitation", "metadata_unavailable", "scope_limited"
            }:
                add(issues, "error", "source_notes_code_invalid", definition.document.path, f"{source_id}备注只能使用受控审计码，不得承载事实或建议。")
            if unresolved_evidence_value(locator) or normalize_evidence_text(locator).startswith("unknown:"):
                add(issues, "error", "source_locator_missing", definition.document.path, f"{source_id}必须记录非空稳定定位。")
            elif not normalize_locator(locator):
                add(issues, "error", "source_locator_raw_invalid", definition.document.path, f"{source_id}的稳定定位只允许raw HTTP(S) URL或受控stable-id。")
            if unresolved_evidence_value(source_group) or normalize_evidence_text(source_group).startswith("unknown:"):
                add(issues, "error", "source_group_missing", definition.document.path, f"{source_id}必须记录非空source_group。")
            if level not in SOURCE_LEVELS:
                add(issues, "error", "source_level_invalid", definition.document.path, f"{source_id}来源等级无效：{level!r}。")
            if permission not in SOURCE_PERMISSIONS:
                add(issues, "error", "source_permission_invalid", definition.document.path, f"{source_id}权限无效：{permission!r}。")
            if (
                level == "internal"
                or permission in {"internal-authorized", "restricted"}
            ) and (
                not source_id.startswith("SRC-N-")
                or definition.document.frontmatter.get("artifact_type") != "internal_retrieval"
            ):
                add(
                    issues,
                    "error",
                    "internal_source_carrier_invalid",
                    definition.document.path,
                    f"{source_id}的内部/受限证据只能由internal_retrieval中的SRC-N-*承载。",
                )
            if external_use not in SOURCE_EXTERNAL_USE_VALUES:
                add(issues, "error", "source_external_use_invalid", definition.document.path, f"{source_id}的external_use必须为true或false。")
            if permission == "restricted" and external_use == "true":
                add(issues, "error", "restricted_external_use_conflict", definition.document.path, f"{source_id}为restricted时external_use必须为false。")
            if not source_fingerprint_valid(fingerprint):
                add(issues, "error", "source_fingerprint_invalid", definition.document.path, f"{source_id}的source_fingerprint必须为SHA-256或scheme:stable-id格式。")
            if unresolved_evidence_value(upstream_id):
                add(issues, "error", "source_upstream_missing", definition.document.path, f"{source_id}必须记录upstream_id；无法识别时用unknown:{source_id}且不得参与F2。")
            elif normalize_evidence_text(upstream_id).startswith("unknown:") and normalize_evidence_text(upstream_id) != f"unknown:{source_id.casefold()}":
                add(issues, "error", "source_upstream_unknown_invalid", definition.document.path, f"{source_id}无法识别上游时必须精确写unknown:{source_id}。")
        used = any(source_id in SOURCE_RE.findall(claim.cells[6] + " " + claim.cells[7]) for claim in claims.values() if len(claim.cells) >= 8)
        if not used:
            add(issues, "warning", "source_unreferenced", definition.document.path, f"{source_id}未被任何主张引用。")

    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if document.frontmatter.get("module_status") != "completed":
            continue
        prefix = RESEARCH_PREFIX.get(artifact_type)
        if prefix:
            own_claims = [key for key, value in claims.items() if value.document.path == document.path and key.startswith(f"CLM-{prefix}-")]
            own_sources = [key for key, value in sources.items() if value.document.path == document.path and key.startswith(f"SRC-{prefix}-")]
            if not own_claims:
                add(issues, "error", "completed_claim_ledger_missing", document.path, "completed研究成果必须有非空主张台账。")
            if not own_sources:
                add(issues, "error", "completed_source_ledger_missing", document.path, "completed研究成果必须有非空来源台账。")
            non_registry_lines = [
                line
                for line in body_without_placeholders(document).splitlines()
                if not (line.lstrip().startswith("|") and split_table_cells(line) and (CLAIM_RE.fullmatch(split_table_cells(line)[0]) or SOURCE_RE.fullmatch(split_table_cells(line)[0])))
            ]
            if not CLAIM_RE.search("\n".join(non_registry_lines)):
                add(issues, "error", "body_claim_reference_missing", document.path, "completed研究正文必须引用claim_id。")
        elif artifact_type in {
            "comprehensive_report",
            "visit_strategy",
            "briefing_delivery",
            "customer_letter_internal",
        } and not CLAIM_RE.search(body_without_placeholders(document)):
            allow_gap_only_total = False
            if artifact_type == "comprehensive_report" and document.frontmatter.get("route") in {"research_only", "refresh"}:
                rows = parse_status_rows(document)
                selected_research = [
                    row
                    for kind, row in rows.items()
                    if kind in RESEARCH_PREFIX and len(row) >= 4 and row[1] == "true"
                ]
                allow_gap_only_total = bool(selected_research) and all(row[3] in {"partial", "blocked"} for row in selected_research)
            if not allow_gap_only_total:
                add(
                    issues,
                    "error",
                    "body_claim_reference_missing",
                    document.path,
                    "completed成果正文必须引用至少一个已定义claim_id；仅全为partial/blocked的研究型总报告可只交付缺口。",
                )

    for document in documents:
        if document.frontmatter.get("module_status") != "completed" or document.frontmatter.get("freshness_status") != "current":
            continue
        if document.frontmatter.get("artifact_type") not in {
            "comprehensive_report",
            "visit_strategy",
            "briefing_delivery",
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
                add(issues, "error", "current_output_uses_stale_claim", document.path, f"current成果引用了非current主张：{claim_id}")
            dependency_cutoff = dependency.frontmatter.get("evidence_cutoff_date", "")
            if date_valid(cutoff) and date_valid(dependency_cutoff) and cutoff > dependency_cutoff:
                add(issues, "error", "evidence_cutoff_exceeds_dependency", document.path, f"信息截止{cutoff}晚于{claim_id}所属研究成果截止{dependency_cutoff}。")

    total = next(
        (document for document in documents if document.frontmatter.get("artifact_type") == "comprehensive_report"),
        None,
    )
    status_rows = parse_status_rows(total) if total else {}
    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if artifact_type not in {"visit_strategy", "briefing_delivery", "customer_letter_internal"}:
            continue
        if document.frontmatter.get("module_status") != "completed" or document.frontmatter.get("freshness_status") != "current":
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
                add(issues, "error", "output_uses_incomplete_research", document.path, f"{artifact_type}引用了非completed研究载体：{claim_id}。")
            if dependency.frontmatter.get("freshness_status") != "current":
                add(issues, "error", "output_uses_stale_research", document.path, f"{artifact_type}引用了非current研究载体：{claim_id}。")
            if output_selected:
                dependency_row = status_rows.get(dependency_type, [])
                if len(dependency_row) < 3 or dependency_row[1] != "true" or dependency_row[2] == "not_called":
                    add(issues, "error", "output_carrier_unselected", document.path, f"本轮输出引用的研究载体未登记为selected：{claim_id}。")
            claim_type = definition.cells[1] if len(definition.cells) >= 2 else ""
            verification = definition.cells[3] if len(definition.cells) >= 4 else ""
            supports = supporting_sources(definition, sources)
            if verification in UNSAFE_DOWNSTREAM_VERIFICATIONS:
                add(issues, "error", "output_uses_unsafe_claim", document.path, f"{artifact_type}引用了{verification}主张：{claim_id}。")
            fact_anchor = (
                claim_type in {"F", "F2"}
                and verification in SAFE_FACT_VERIFICATIONS
                and bool(supports)
                and all(len(source.cells) >= 7 and source.cells[6] != "C" for source in supports)
            )
            verified_anchor = verified_anchor or fact_anchor
            if artifact_type == "customer_letter_internal":
                if dependency_type in {"leader_research", "internal_retrieval"} and dependency.frontmatter.get("review_status") != "approved":
                    add(issues, "error", "letter_carrier_review_missing", document.path, f"客户信引用的人物/内部研究必须先审核为approved：{claim_id}。")
                if not fact_anchor:
                    add(issues, "error", "letter_claim_not_externally_verified", document.path, f"客户信依据必须是由非C级来源支撑的F/F2已核实事实：{claim_id}。")
                for source in supports:
                    if len(source.cells) >= 9 and source.cells[8] == "restricted":
                        add(issues, "error", "letter_source_restricted", document.path, f"客户信不得依赖restricted来源：{source.source_id}。")
                    if len(source.cells) < 14 or source.cells[13] != "true":
                        add(issues, "error", "letter_source_not_external_authorized", document.path, f"客户信依据必须显式记录external_use=true：{source.source_id}。")
        if not verified_anchor:
            add(issues, "error", "output_verified_anchor_missing", document.path, f"completed/current的{artifact_type}至少需要一个可核验的F/F2事实锚点。")


def validate_filenames_and_identity(documents: list[Document], root: Path, issues: list[Issue]) -> dict[str, Document]:
    by_type: dict[str, Document] = {}
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(totals) != 1:
        add(issues, "error", "comprehensive_count", root, f"综合报告必须且只能有1个，当前{len(totals)}个。")
    for document in documents:
        artifact_type = document.frontmatter.get("artifact_type")
        if artifact_type not in ARTIFACT_TYPES:
            continue
        if artifact_type in by_type:
            add(issues, "error", "artifact_duplicate", document.path, f"artifact_type重复：{artifact_type}")
        else:
            by_type[artifact_type] = document
        safe_name = document.frontmatter.get("safe_name", "")
        expected = f"{safe_name}{SUFFIXES[artifact_type]}"
        if document.path.name != expected:
            add(issues, "error", "filename_invalid", document.path, f"文件名应为：{expected}")
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
                    add(issues, "error", "identity_mismatch", document.path, f"{field}与综合报告不一致。")
        safe_name = total.frontmatter.get("safe_name", "")
        context_id = total.frontmatter.get("context_id", "")
        if safe_name and context_id and CONTEXT_RE.fullmatch(context_id):
            expected_dir = f"客户研究-{safe_name}-{context_id.rsplit('-', 1)[1]}"
            if root.name != expected_dir:
                add(issues, "error", "workspace_name_invalid", root, f"工作目录名应为：{expected_dir}")
    return by_type


def parse_status_rows(total: Document) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    label_to_type = {label: artifact_type for artifact_type, label in STATUS_LABELS.items()}
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


def status_link_parts(cell: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", cell.strip())
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def validate_status_sync(
    by_type: dict[str, Document],
    issues: list[Issue],
    strict: bool,
    *,
    claims: Mapping[str, ClaimDefinition] | None = None,
) -> None:
    total = by_type.get("comprehensive_report")
    if not total:
        return
    current_claim_ids = set(claims) if claims is not None else None
    rows = parse_status_rows(total)
    for artifact_type, label in STATUS_LABELS.items():
        artifact = by_type.get(artifact_type)
        occurrences = len(re.findall(rf"^\|\s*{re.escape(label)}\s*\|.*$", total.body, flags=re.MULTILINE))
        legacy_optional = (
            artifact_type == "briefing_delivery"
            and artifact is None
            and total.frontmatter.get("business_mode") != "briefing"
        )
        if occurrences == 0 and legacy_optional:
            continue
        if occurrences != 1:
            add(issues, "error", "status_row_count_invalid", total.path, f"{label}状态行必须恰有1条，当前{occurrences}条。")
        row = rows.get(artifact_type)
        if not row or len(row) != 15:
            add(issues, "error", "status_row_missing", total.path, f"缺少或损坏状态行：{label}；必须恰有15列，竖线须写为\\|。")
            continue
        selected = row[1]
        run_action = row[2]
        if selected not in {"true", "false"}:
            add(issues, "error", "selected_in_run_invalid", total.path, f"{label}.selected_in_run必须为true或false。")
        if run_action not in RUN_ACTIONS:
            add(issues, "error", "run_action_invalid", total.path, f"{label}.run_action无效：{run_action!r}。")
        if artifact_type == "customer_letter_external" and run_action not in {"generated", "reused", "not_called"}:
            add(issues, "error", "external_run_action_invalid", total.path, "客户信外发版run_action只允许generated、reused或not_called。")
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
        status_link = status_link_parts(row[14])
        target = status_link[1] if status_link is not None else ""
        if summary_sync_status not in SUMMARY_SYNC_STATUSES:
            add(issues, "error", "summary_sync_status_invalid", total.path, f"{label}.summary_sync_status无效。")
        if downstream_invalidation not in DOWNSTREAM_INVALIDATIONS:
            add(issues, "error", "downstream_invalidation_invalid", total.path, f"{label}.downstream_invalidation无效。")
        allow_empty_key_claims = artifact is None and selected == "false" and run_action == "not_called"
        parsed_key_claims = canonical_key_claim_ids(
            key_claim_ids,
            current_claim_ids,
            allow_empty=allow_empty_key_claims,
        )
        if parsed_key_claims is None:
            add(
                issues,
                "error",
                "key_claim_ids_contract_invalid",
                total.path,
                f"{label}.key_claim_ids只能是当前权威ledger中的去重排序claim_id列表；无引用写none，未调用也可留空。",
            )
        parsed_gap_tokens = canonical_status_tokens(gaps_blockers, current_claim_ids)
        if parsed_gap_tokens is None:
            add(
                issues,
                "error",
                "gaps_blockers_contract_invalid",
                total.path,
                f"{label}.gaps/blockers只能写none，或受控gap/blocker码与当前claim_id的去重排序列表。",
            )
        elif row_values["module_status"] in {"partial", "blocked"} and not parsed_gap_tokens:
            add(issues, "error", "terminal_gap_missing", total.path, f"{label}为partial/blocked时必须登记受控缺口或阻塞码。")
        elif row_values["module_status"] == "blocked" and not status_blocked_recovery_complete(parsed_gap_tokens):
            add(
                issues,
                "error",
                "blocked_recovery_contract_invalid",
                total.path,
                f"{label}为blocked时，gaps/blockers必须同时包含attempted_*、impact_*、release_*受控码。",
            )
        if artifact is None:
            if selected == "true":
                add(issues, "error", "selected_artifact_missing", total.path, f"{label}本轮已选但成果文件不存在。")
            if run_action != "not_called":
                add(issues, "error", "run_action_missing_artifact", total.path, f"{label}无文件时run_action必须为not_called。")
            if row_values["module_status"] != "not_called":
                add(issues, "error", "status_missing_artifact", total.path, f"{label}无文件但状态不是not_called。")
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
            if row[14].strip():
                add(issues, "error", "status_phantom_link", total.path, f"{label}未调用却存在链接或链接文本。")
            empty_key_claim_values = {"", "none"}
            if (
                summary_sync_status != "not_applicable"
                or key_claim_ids not in empty_key_claim_values
                or downstream_invalidation != "none"
            ):
                add(issues, "error", "status_uncalled_registry", total.path, f"{label}未调用时同步/主张/失效字段不符合空登记。")
            continue
        if selected == "false" and run_action != "not_called":
            add(issues, "error", "run_action_unselected", total.path, f"{label}本轮未选时run_action必须为not_called。")
        if selected == "true" and run_action == "not_called":
            add(issues, "error", "run_action_selected", total.path, f"{label}本轮已选时run_action不能为not_called。")
        if row_values["module_status"] == "not_called":
            add(issues, "error", "status_uncalled_artifact", total.path, f"{label}存在历史或本轮成果文件，module_status不能为not_called。")
        for field, row_value in row_values.items():
            artifact_value = artifact.frontmatter.get(field, "")
            if row_value != artifact_value:
                add(issues, "error", "status_sync_mismatch", total.path, f"{label}.{field}={row_value!r}，成果为{artifact_value!r}。")
        expected_target = "./" + artifact.path.name
        if (
            status_link is None
            or status_link[0] != label
            or unquote(target) != expected_target
        ):
            add(
                issues,
                "error",
                "status_link_mismatch",
                total.path,
                f"{label}成果链接必须完整写为[{label}]({expected_target})。",
            )
        if selected == "true" and run_action in {"created", "updated", "generated"}:
            if artifact.frontmatter.get("latest_run_id") != total.frontmatter.get("latest_run_id"):
                planned_update = (
                    run_action == "updated"
                    and not strict
                    and total.frontmatter.get("workflow_stage") in {"planning", "research", "paused"}
                )
                if not planned_update:
                    add(issues, "error", "run_id_current_action_mismatch", total.path, f"{label}本轮{run_action}但latest_run_id不是本轮run。")
                elif summary_sync_status != "pending":
                    add(issues, "error", "planned_update_sync_invalid", total.path, f"{label}尚未由本轮更新时summary_sync_status必须为pending。")
        if selected == "true" and run_action == "reused" and artifact.frontmatter.get("latest_run_id") == total.frontmatter.get("latest_run_id"):
            add(issues, "error", "reused_artifact_modified_in_run", total.path, f"{label}标为reused却由本轮run更新。")
        if selected == "false" and artifact.frontmatter.get("latest_run_id") == total.frontmatter.get("latest_run_id"):
            add(issues, "error", "uncalled_artifact_modified_in_run", total.path, f"{label}标为本轮未调用，却由本轮run更新。")
        if summary_sync_status == "not_applicable" and artifact_type != "customer_letter_external":
            add(issues, "error", "summary_sync_not_applicable", total.path, f"{label}存在成果时summary_sync_status不能为not_applicable。")
        if artifact.frontmatter.get("module_status") == "completed" and artifact_type != "customer_letter_external":
            if not CLAIM_RE.search(key_claim_ids):
                add(issues, "error", "key_claim_ids_missing", total.path, f"{label}completed时必须登记key_claim_ids。")
        registered_claims = set(parsed_key_claims or [])
        body_claims = set(CLAIM_RE.findall(body_without_placeholders(artifact)))
        expected_registered_claims = (
            body_claims
            if current_claim_ids is None
            else body_claims & current_claim_ids
        )
        binding_required = selected == "true" or artifact.frontmatter.get("module_status") == "completed"
        if binding_required and registered_claims != expected_registered_claims:
            add(
                issues,
                "error",
                "key_claim_ids_binding_mismatch",
                total.path,
                f"{label}.key_claim_ids必须精确等于成果正文引用的当前ledger claim_id全集：{sorted(expected_registered_claims)}。",
            )
        if registered_claims - body_claims:
            add(issues, "error", "key_claim_ids_not_in_artifact", total.path, f"{label}.key_claim_ids包含成果正文未引用的主张：{sorted(registered_claims - body_claims)}。")
        prefix = RESEARCH_PREFIX.get(artifact_type)
        if prefix and any(not claim_id.startswith(f"CLM-{prefix}-") for claim_id in registered_claims):
            add(issues, "error", "key_claim_ids_wrong_carrier", total.path, f"{label}.key_claim_ids包含不属于本研究台账的主张。")


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
    headings = [index for index, line in enumerate(lines) if line.strip() == "## 9. 版本与同步记录"]
    if len(headings) != 1:
        add(issues, "error", "run_history_section_invalid", total.path, "综合报告必须恰有一个“版本与同步记录”章节。")
        return []
    rows: list[list[str]] = []
    for line in lines[headings[0] + 1 :]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        if not cells or cells[0] == "updated_at" or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if len(cells) != 5:
            add(issues, "error", "run_history_row_shape", total.path, f"运行记录必须恰有5列：{line[:120]}")
            continue
        rows.append(cells)
    if not rows:
        add(issues, "error", "run_history_empty", total.path, "版本与同步记录至少需要一条运行记录。")
    return rows


def refresh_ledger_rows(total: Document, issues: list[Issue]) -> list[list[str]]:
    lines = total.body.splitlines()
    headings = [index for index, line in enumerate(lines) if line.strip() == REFRESH_HEADING]
    if not headings:
        if total.frontmatter.get("route") == "refresh":
            add(issues, "error", "refresh_ledger_section_missing", total.path, "refresh综合报告必须包含刷新结果记录章节。")
        return []
    if len(headings) != 1:
        add(issues, "error", "refresh_ledger_section_invalid", total.path, "刷新结果记录章节必须恰有一个。")
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
            add(issues, "error", "refresh_ledger_row_shape", total.path, "刷新结果记录必须恰有6列。")
            continue
        rows.append(cells)
    if not header_seen:
        add(issues, "error", "refresh_ledger_header_invalid", total.path, "刷新结果记录表头必须为run_id及五类变更。")
    run_ids = [row[0] for row in rows]
    if len(run_ids) != len(set(run_ids)):
        add(issues, "error", "refresh_ledger_run_duplicate", total.path, "刷新结果记录的latest_run_id不得重复。")
    return rows


def parse_refresh_items(value: str) -> tuple[set[str], bool]:
    if value == "none":
        return set(), True
    members = [member.strip() for member in value.split(",")]
    valid = bool(members) and all(REFRESH_ITEM_RE.fullmatch(member) for member in members)
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
        add(issues, "error", "refresh_not_resume", total.path, "refresh必须建立在至少一条更早运行记录上，首轮不得为refresh。")
    if history:
        first_fields = summary_fields_without_reporting(history[0][3])
        if first_fields.get("route") == "refresh":
            add(issues, "error", "refresh_first_run_invalid", total.path, "首条运行记录不得为refresh。")
    enforce = strict or total.frontmatter.get("workflow_stage") in {"review", "closed"}
    if not enforce:
        return
    latest_run_id = total.frontmatter.get("latest_run_id", "")
    matches = [row for row in ledger if row[0] == latest_run_id]
    if len(matches) != 1:
        add(issues, "error", "refresh_ledger_latest_missing", total.path, "严格refresh必须恰有一条对应latest_run_id的刷新结果记录。")
        return
    row = matches[0]
    categories: list[set[str]] = []
    for label, value in zip(REFRESH_HEADER[1:], row[1:]):
        members, valid = parse_refresh_items(value)
        if not valid:
            add(issues, "error", "refresh_ledger_value_invalid", total.path, f"刷新分类“{label}”必须是逗号分隔claim/source ID或exact none。")
        categories.append(members)
    all_members = set().union(*categories)
    if not all_members:
        add(issues, "error", "refresh_ledger_empty", total.path, "严格refresh至少应在五类中登记一个claim/source ID；无变化时在“未变化”列列出已复核ID。")
    if sum(len(members) for members in categories) != len(all_members):
        add(issues, "error", "refresh_ledger_overlap", total.path, "同一claim/source ID不得同时属于多个刷新分类。")
    known_ids = set(claims) | set(sources)
    unknown = sorted(all_members - known_ids)
    if unknown:
        add(issues, "error", "refresh_ledger_orphan", total.path, "刷新结果记录引用了未定义ID：" + ", ".join(unknown))
    if history:
        latest_fields = summary_fields_without_reporting(history[-1][3])
        target_cutoff = latest_fields.get("target_evidence_cutoff_date", "")
        if target_cutoff != total.frontmatter.get("evidence_cutoff_date"):
            add(issues, "error", "refresh_cutoff_not_merged", total.path, "严格refresh要求最新run目标截止日与综合报告evidence_cutoff_date一致。")
    status_rows = parse_status_rows(total)
    selected_research = {
        artifact_type
        for artifact_type in RESEARCH_PREFIX
        if len(status_rows.get(artifact_type, [])) >= 3 and status_rows[artifact_type][1] == "true"
    }
    if not selected_research:
        add(issues, "error", "refresh_research_missing", total.path, "严格refresh至少选择一个研究成果。")
    for artifact_type in selected_research:
        row = status_rows[artifact_type]
        if row[2] not in {"created", "updated"}:
            add(issues, "error", "refresh_action_invalid", total.path, f"{STATUS_LABELS[artifact_type]}在refresh中必须created或updated。")
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue
        if artifact.frontmatter.get("latest_run_id") != latest_run_id:
            add(issues, "error", "refresh_artifact_run_mismatch", artifact.path, "refresh所选研究成果必须由本轮run实际写入。")
        if artifact.frontmatter.get("evidence_cutoff_date") != total.frontmatter.get("evidence_cutoff_date"):
            add(issues, "error", "refresh_artifact_cutoff_mismatch", artifact.path, "refresh所选研究成果的evidence_cutoff_date必须与已合并总报告一致。")


def parse_member_set(value: str) -> tuple[set[str], bool]:
    if value == "none":
        return set(), True
    members = [member.strip() for member in value.split(",")]
    valid = bool(members) and all(members) and len(members) == len(set(members))
    return set(members), valid


def parse_run_summary(summary: str, total: Document, run_id: str, issues: list[Issue]) -> dict[str, str] | None:
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
            add(issues, "error", "run_history_field_duplicate", total.path, f"{run_id}运行摘要字段重复：{key}。")
        fields[key] = value
    if malformed:
        add(issues, "error", "run_history_field_malformed", total.path, f"{run_id}运行摘要包含非key=value片段。")
    missing = sorted(RUN_SUMMARY_KEYS - fields.keys())
    unknown = sorted(fields.keys() - RUN_SUMMARY_KEYS)
    if missing:
        add(issues, "error", "run_history_incomplete", total.path, f"{run_id}运行记录缺少：" + ", ".join(missing))
    if unknown:
        add(issues, "error", "run_history_unknown_field", total.path, f"{run_id}运行记录含未知字段：" + ", ".join(unknown))
    if missing or unknown or malformed:
        return None
    if fields["route"] not in ROUTES:
        add(issues, "error", "run_history_route_invalid", total.path, f"{run_id}的route无效。")
    if fields["depth"] not in DEPTHS:
        add(issues, "error", "run_history_depth_invalid", total.path, f"{run_id}的depth无效。")
    if not fields["objective"]:
        add(issues, "error", "run_objective_missing", total.path, f"{run_id}的objective不能为空。")
    if not date_valid(fields["target_evidence_cutoff_date"]):
        add(issues, "error", "run_target_cutoff_invalid", total.path, f"{run_id}的target_evidence_cutoff_date必须为YYYY-MM-DD。")

    selected, selected_valid = parse_member_set(fields["selected_modules"])
    if not selected_valid or not selected <= RUN_ARTIFACT_NAMES:
        add(issues, "error", "run_history_selected_invalid", total.path, f"{run_id}的selected_modules含重复、空值或未知成果。")
    action_sets: dict[str, set[str]] = {}
    for action in ("created", "updated", "reused", "generated", "not_called"):
        members, valid = parse_member_set(fields[action])
        action_sets[action] = members
        if not valid or not members <= RUN_ARTIFACT_NAMES:
            add(issues, "error", "run_history_action_invalid", total.path, f"{run_id}的{action}含重复、空值或未知成果。")
    assigned = set().union(*action_sets.values())
    overlaps = sum(len(members) for members in action_sets.values()) != len(assigned)
    allowed_partition = frozenset(assigned) in {
        frozenset(LEGACY_RUN_ARTIFACT_NAMES),
        frozenset(RUN_ARTIFACT_NAMES),
    }
    if not allowed_partition or overlaps:
        add(issues, "error", "run_history_action_partition_invalid", total.path, f"{run_id}的五类动作必须无重叠且完整覆盖旧版6项或当前7项成果登记。")
    expected_selected = assigned - action_sets["not_called"]
    if selected != expected_selected:
        add(issues, "error", "run_history_selected_mismatch", total.path, f"{run_id}的selected_modules与动作分区不一致。")
    if action_sets["generated"] - {"external_letter"}:
        add(issues, "error", "run_history_generated_invalid", total.path, f"{run_id}仅external_letter可使用generated动作。")
    invalid_external_actions = [
        action
        for action in ("created", "updated")
        if "external_letter" in action_sets[action]
    ]
    if invalid_external_actions:
        add(
            issues,
            "error",
            "run_history_external_action_invalid",
            total.path,
            f"{run_id}的external_letter只允许generated、reused或not_called，不能属于：{', '.join(invalid_external_actions)}。",
        )
    if "external_letter" in selected and fields["route"] != "letter":
        add(issues, "error", "run_history_external_route_invalid", total.path, f"{run_id}选择external_letter时route必须为letter。")
    if fields["route"] == "research_only" and selected & {"strategy", "briefing", "letter", "external_letter"}:
        add(issues, "error", "run_history_route_modules_invalid", total.path, f"{run_id}的research_only不得选择输出成果。")
    if fields["route"] == "refresh" and selected & {"strategy", "briefing", "letter", "external_letter"}:
        add(issues, "error", "run_history_route_modules_invalid", total.path, f"{run_id}的refresh只能选择研究成果。")
    if fields["route"] == "refresh":
        if not selected & {"institution", "leader", "internal"}:
            add(issues, "error", "run_history_refresh_research_missing", total.path, f"{run_id}的refresh至少选择一个研究成果。")
        if action_sets["reused"]:
            add(issues, "error", "run_history_refresh_reused_invalid", total.path, f"{run_id}的refresh所选研究必须created/updated，不能仅标reused。")
    required = {"visit_prep": "strategy", "strategy": "strategy", "letter": "letter"}.get(fields["route"])
    if required and required not in selected:
        add(issues, "error", "run_history_required_module_missing", total.path, f"{run_id}的route={fields['route']}必须选择{required}。")
    if fields["route"] in {"visit_prep", "strategy", "letter"} and not selected & {"institution", "leader", "internal"}:
        add(issues, "error", "run_history_research_carrier_missing", total.path, f"{run_id}缺少研究载体。")
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
            add(issues, "error", "run_history_timestamp_invalid", total.path, f"运行记录{run_id}的updated_at无效。")
            parsed_time = None
        else:
            parsed_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if not CONTENT_VERSION_RE.fullmatch(version):
            add(issues, "error", "run_history_version_invalid", total.path, f"运行记录{run_id}的content_version无效。")
            numeric_version = None
        else:
            numeric_version = int(version)
        if not run_id_valid(run_id):
            add(issues, "error", "run_history_run_id_invalid", total.path, f"运行记录run_id无效：{run_id!r}。")
        if run_id in seen_runs:
            add(issues, "error", "run_history_run_duplicate", total.path, f"运行记录run_id重复：{run_id}。")
        seen_runs.add(run_id)
        if not owner.strip():
            add(issues, "error", "run_history_owner_missing", total.path, f"运行记录{run_id}的runtime_owner不能为空。")
        if previous_version is not None and numeric_version is not None and numeric_version != previous_version + 1:
            add(issues, "error", "run_history_version_sequence", total.path, f"运行记录{run_id}的版本必须紧接前一版本。")
        if previous_time is not None and parsed_time is not None and parsed_time < previous_time:
            add(issues, "error", "run_history_time_sequence", total.path, f"运行记录{run_id}的updated_at早于前一条记录。")
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
        add(issues, "error", "latest_run_history_missing", total.path, f"最后一条版本记录必须恰好对应latest_run_id={latest_run_id}。")
        return
    latest = matching[0]
    if latest[0] != total.frontmatter.get("updated_at"):
        add(issues, "error", "run_history_latest_time_mismatch", total.path, "最新运行记录updated_at与综合报告不一致。")
    if latest[1] != total.frontmatter.get("content_version"):
        add(issues, "error", "run_history_latest_version_mismatch", total.path, "最新运行记录content_version与综合报告不一致。")
    if latest[4] != total.frontmatter.get("runtime_owner"):
        add(issues, "error", "run_history_latest_owner_mismatch", total.path, "最新运行记录runtime_owner与综合报告不一致。")
    fields = parsed_by_run.get(latest_run_id)
    if fields is None:
        return
    if fields["route"] != total.frontmatter.get("route") or fields["depth"] != total.frontmatter.get("depth"):
        add(issues, "error", "run_history_latest_route_mismatch", total.path, "最新运行记录route/depth与综合报告不一致。")
    rows = parse_status_rows(total)
    names = {
        "institution_research": "institution",
        "leader_research": "leader",
        "internal_retrieval": "internal",
        "visit_strategy": "strategy",
        "briefing_delivery": "briefing",
        "customer_letter_internal": "letter",
        "customer_letter_external": "external_letter",
    }
    expected_actions = {
        names[artifact_type]: row[2]
        for artifact_type, row in rows.items()
        if artifact_type in names and len(row) >= 3
    }
    recorded_universe = set().union(
        *(parse_member_set(fields[action])[0] for action in ("created", "updated", "reused", "generated", "not_called"))
    )
    for action in ("created", "updated", "reused", "generated", "not_called"):
        expected = {
            name
            for name, value in expected_actions.items()
            if value == action and name in recorded_universe
        }
        recorded, _ = parse_member_set(fields[action])
        if recorded != expected:
            add(issues, "error", "run_history_action_mismatch", total.path, f"最新运行记录{action}与当前成果登记不一致。")


def validate_route_gate(by_type: dict[str, Document], issues: list[Issue], strict: bool) -> None:
    total = by_type.get("comprehensive_report")
    if not total:
        return
    if strict and (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("freshness_status") != "current"
    ):
        add(issues, "error", "strict_total_not_ready", total.path, "严格最终校验要求综合报告completed/current。")
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
                add(issues, "error", "selected_module_nonterminal", artifact.path, "严格交付或review/closed流程要求本轮所选模块达到partial/completed/blocked。")
            row = rows.get(artifact_type, [])
            if artifact_type != "customer_letter_external" and len(row) >= 11 and row[10] != "synced":
                add(issues, "error", "selected_module_unsynced", total.path, f"{STATUS_LABELS[artifact_type]}尚未同步到综合报告。")
    if total.frontmatter.get("workflow_stage") == "closed" and total.frontmatter.get("module_status") != "completed":
        add(issues, "error", "closed_total_incomplete", total.path, "workflow_stage=closed时综合报告module_status必须为completed。")

    route = total.frontmatter.get("route")
    required_selected = {
        "visit_prep": "visit_strategy",
        "strategy": "visit_strategy",
        "letter": "customer_letter_internal",
    }.get(route)
    if required_selected and required_selected not in selected_types:
        add(issues, "error", "route_required_module_unselected", total.path, f"route={route}必须把{required_selected}列为本轮调用或复用模块。")
    if route == "research_only":
        unexpected = selected_types & {
            "visit_strategy",
            "briefing_delivery",
            "customer_letter_internal",
            "customer_letter_external",
        }
        if unexpected:
            add(issues, "error", "research_only_output_selected", total.path, "research_only不得选择策略或客户信成果；请改用对应主路由。")
    if selected_types & {"customer_letter_internal", "customer_letter_external"} and route != "letter":
        add(issues, "error", "letter_route_not_highest_gate", total.path, "选择客户信时主路由必须为letter。")
    if route == "refresh" and selected_types & {
        "visit_strategy",
        "briefing_delivery",
        "customer_letter_internal",
        "customer_letter_external",
    }:
        add(issues, "error", "refresh_output_selected", total.path, "refresh只允许研究模块；策略或客户信应使用相应主路由。")
    if route in {"visit_prep", "strategy", "letter"} and not (
        {"institution_research", "leader_research", "internal_retrieval"} & by_type.keys()
    ):
        add(issues, "error", "route_research_carrier_missing", total.path, f"route={route}至少需要一个研究成果承载claim/source台账。")
    if route in {"visit_prep", "strategy", "letter"} and not (
        {"institution_research", "leader_research", "internal_retrieval"} & selected_types
    ):
        add(issues, "error", "route_research_carrier_unselected", total.path, f"route={route}必须把至少一个研究成果登记为本轮selected/reused或selected/updated。")
    if total.frontmatter.get("workflow_stage") == "closed" and total.frontmatter.get("freshness_status") == "current":
        invalidations = [row[12] for row in rows.values() if len(row) >= 13 and row[12] in {"stale", "invalidated"}]
        if invalidations:
            add(issues, "error", "closed_total_ignores_invalidation", total.path, "综合报告标为current但成果登记仍有下游失效信号。")
    if not strict and total.frontmatter.get("workflow_stage") not in {"review", "closed"}:
        return
    if total.frontmatter.get("module_status") != "completed" or total.frontmatter.get("freshness_status") != "current":
        add(issues, "error", "review_stage_total_not_ready", total.path, "review/closed阶段的综合报告必须completed/current。")

    for artifact_type in selected_types:
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue
        is_research = artifact_type in {"institution_research", "leader_research", "internal_retrieval"}
        if is_research:
            if artifact.frontmatter.get("module_status") not in TERMINAL_STATUSES:
                add(issues, "error", "review_stage_research_nonterminal", artifact.path, "review/closed阶段的研究成果必须为partial/completed/blocked终态。")
            if artifact.frontmatter.get("freshness_status") != "current":
                add(issues, "error", "review_stage_research_stale", artifact.path, "review/closed阶段引用的研究成果必须current；stale/invalidated应先刷新或移除依赖。")
        allowed_reviews: set[str] = set()
        if artifact_type in RESEARCH_PREFIX:
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
        if allowed_reviews and artifact.frontmatter.get("review_status") not in allowed_reviews:
            add(issues, "error", "review_stage_status_invalid", artifact.path, f"review/closed阶段的{artifact_type}审核状态必须为{sorted(allowed_reviews)}。")

    for artifact_type in selected_types & {"visit_strategy", "customer_letter_internal"}:
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue
        if artifact.frontmatter.get("module_status") != "completed":
            add(issues, "error", "selected_output_incomplete", artifact.path, "review/closed阶段的选中输出必须completed。")
        if artifact.frontmatter.get("freshness_status") != "current":
            add(issues, "error", "selected_output_stale", artifact.path, "review/closed阶段的选中输出必须current。")
        if artifact.frontmatter.get("review_status") not in {"pending", "approved", "changes_requested"}:
            add(issues, "error", "selected_output_review_missing", artifact.path, "review/closed阶段的选中输出必须记录审核状态。")
        if total.frontmatter.get("workflow_stage") == "closed" and artifact.frontmatter.get("review_status") == "changes_requested":
            add(issues, "error", "closed_output_changes_requested", artifact.path, "changes_requested成果不得进入closed；修改后重新提交审核。")
    required_type = required_selected
    if not required_type:
        return
    artifact = by_type.get(required_type)
    if artifact is None:
        add(issues, "error", "route_required_artifact_missing", total.path, f"route={route}缺少{required_type}成果。")
        return
    if artifact.frontmatter.get("module_status") != "completed":
        add(issues, "error", "route_required_artifact_incomplete", artifact.path, f"route={route}要求该成果module_status=completed。")
    if artifact.frontmatter.get("freshness_status") != "current":
        add(issues, "error", "route_required_artifact_stale", artifact.path, f"route={route}要求该成果freshness_status=current。")
    letter_reviews = (
        {"pending", "approved"}
        if total.frontmatter.get("workflow_stage") == "closed"
        else {"pending", "approved", "changes_requested"}
    )
    if route == "letter" and artifact.frontmatter.get("review_status") not in letter_reviews:
        add(issues, "error", "letter_review_gate", artifact.path, f"letter在当前阶段的审核状态必须为{sorted(letter_reviews)}。")


def required_research_review_types(by_type: Mapping[str, Document]) -> set[str]:
    """Return selected or downstream-referenced research carriers.

    The reference pass deliberately ignores the selected flag so a delivery
    cannot evade fact review by marking a still-referenced carrier unselected.
    """

    total = by_type.get("comprehensive_report")
    selected: set[str] = set()
    if total is not None:
        selected = {
            artifact_type
            for artifact_type, row in parse_status_rows(total).items()
            if artifact_type in RESEARCH_PREFIX and len(row) >= 2 and row[1] == "true"
        }
    prefix_to_type = {prefix: artifact_type for artifact_type, prefix in RESEARCH_PREFIX.items()}
    referenced: set[str] = set()
    for artifact_type, document in by_type.items():
        if artifact_type in RESEARCH_PREFIX:
            continue
        for claim_id in CLAIM_RE.findall(body_without_placeholders(document)):
            referenced_type = prefix_to_type.get(claim_id.split("-")[1])
            if referenced_type:
                referenced.add(referenced_type)
    return selected | referenced


def validate_research_fact_review_gate(
    by_type: Mapping[str, Document],
    issues: list[Issue],
    strict: bool,
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None or not (strict or total.frontmatter.get("ready_for_use") == "true"):
        return
    for artifact_type in sorted(required_research_review_types(by_type)):
        artifact = by_type.get(artifact_type)
        if (
            artifact is None
            or artifact.frontmatter.get("module_status") != "completed"
            or artifact.frontmatter.get("freshness_status") != "current"
            or artifact.frontmatter.get("review_status") != "approved"
        ):
            add(
                issues,
                "error",
                "research_fact_review_required",
                artifact.path if artifact is not None else total.path,
                f"被选中或被下游引用的{artifact_type}必须由独立evidence_reviewer按当前正文SHA完成approved审核。",
            )


def validate_links(documents: list[Document], root: Path, issues: list[Issue]) -> None:
    for document in documents:
        for raw_target in LINK_RE.findall(document.body):
            target = unquote(raw_target.strip().split("#", 1)[0])
            if not target or "{{" in target or re.match(r"^(?:https?://|mailto:)", target):
                continue
            candidate = Path(target)
            if candidate.is_absolute():
                add(issues, "error", "link_absolute", document.path, f"本地成果链接必须相对：{raw_target}")
                continue
            resolved = (document.path.parent / candidate).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                add(issues, "error", "link_escape", document.path, f"链接越出工作目录：{raw_target}")
                continue
            if not resolved.is_file():
                add(issues, "error", "link_missing", document.path, f"链接目标不存在：{raw_target}")


def marker_bounds(body: str) -> tuple[int, int] | None:
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip(" `\t") == "EXTERNAL_BODY_START"]
    ends = [i for i, line in enumerate(lines) if line.strip(" `\t") == "EXTERNAL_BODY_END"]
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


def compact_contract_text(value: str) -> str:
    """Normalize a delivery-field value for deterministic anchor checks."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())


def context_anchor(value: str) -> str:
    """Use the explicit recipient/signer token before role/status qualifiers."""

    return re.split(r"[｜|,，;；/（(]", unicodedata.normalize("NFKC", value), maxsplit=1)[0].strip()


def bounded_ordered_text_contains(expected: str, actual: str) -> bool:
    """Allow small particles inside an action phrase, not characters scattered across prose."""

    return bounded_ordered_text_span(expected, actual) is not None


def bounded_ordered_text_span(expected: str, actual: str) -> tuple[int, int] | None:
    """Return the normalized-text span used for a bounded ordered anchor match."""

    needle = compact_contract_text(expected)
    normalized_actual = unicodedata.normalize("NFKC", actual).casefold()
    indexed_haystack = [
        (character, index)
        for index, character in enumerate(normalized_actual)
        if character.isalnum()
    ]
    haystack = "".join(character for character, _index in indexed_haystack)
    if not needle or not haystack:
        return None
    allowed_extra = max(4, len(needle) // 2)
    for start, candidate in enumerate(haystack):
        if candidate != needle[0]:
            continue
        cursor = start
        for character in needle[1:]:
            cursor = haystack.find(character, cursor + 1)
            if cursor < 0:
                break
        else:
            if cursor - start + 1 <= len(needle) + allowed_extra:
                return indexed_haystack[start][1], indexed_haystack[cursor][1] + 1
    return None


LETTER_NEGATIVE_POLARITY_RE = re.compile(
    r"(?:不|非|勿|无|未|莫|毋|别|暂缓|暂停|停止|取消|拒绝|避免)"
)
LETTER_PURPOSE_META_RE = re.compile(
    r"(?:元数据|字段|提示词|系统指令|发信目的为|letter_purpose|expected_action)",
    re.IGNORECASE,
)


def positive_letter_anchor(expected: str, sentence: str) -> bool:
    """Require an expected-action anchor without local negative polarity."""

    if any(unicodedata.category(character) == "Cf" for character in sentence):
        return False
    normalized = unicodedata.normalize("NFKC", sentence).casefold()
    span = bounded_ordered_text_span(expected, normalized)
    if span is None:
        return False
    start, end = span
    local_window = normalized[max(0, start - 10) : end]
    return LETTER_NEGATIVE_POLARITY_RE.search(local_window) is None


def external_markdown_forbidden(value: str) -> bool:
    """Allow plain paragraphs and simple emphasis, but reject structural Markdown."""

    return bool(
        contains_markdown_code_block(value)
        or re.search(r"(?m)^[ \t]{0,3}(?:#{1,6}\s|>|[-+*]\s|\d+[.)、]\s|\|)", value)
        or re.search(r"(?m)^[ \t]{0,3}(?:-{3,}|_{3,}|\*{3,})[ \t]*$", value)
        or contains_markdown_link_or_image(value)
        or "`" in value
    )


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


def validate_letter_isolation(by_type: dict[str, Document], issues: list[Issue]) -> None:
    internal = by_type.get("customer_letter_internal")
    external = by_type.get("customer_letter_external")
    if internal:
        approved_body = extract_external_body(internal)
        if approved_body is None:
            add(issues, "error", "external_markers_invalid", internal.path, "外发正文标记必须各出现一次且顺序正确。")
        elif internal.frontmatter.get("module_status") == "completed" and not normalize_body(approved_body):
            add(issues, "error", "external_body_empty", internal.path, "completed内部稿的外发正文不能为空。")
        elif approved_body is not None and not PLACEHOLDER_RE.search(approved_body):
            if internal.frontmatter.get("module_status") == "completed":
                if not substantive_letter_field(
                    internal.frontmatter.get("letter_purpose", ""), purpose=True
                ) or not substantive_letter_field(
                    internal.frontmatter.get("expected_action", ""), purpose=False
                ):
                    add(
                        issues,
                        "error",
                        "letter_context_non_substantive",
                        internal.path,
                        "letter_purpose和expected_action必须分别包含明确动作及对象；空壳、元叙述或仅称‘已记录/已处理’不得进入候选外发正文。",
                    )
                hidden_format_characters = sorted(
                    {
                        f"U+{ord(character):04X}"
                        for character in approved_body
                        if unicodedata.category(character) == "Cf"
                    }
                )
                if hidden_format_characters:
                    add(
                        issues,
                        "error",
                        "letter_external_format_character_forbidden",
                        internal.path,
                        "候选外发正文不得包含零宽、软连字符或其他不可见格式字符："
                        + ", ".join(hidden_format_characters),
                    )
                if HTML_COMMENT_RE.search(approved_body) or RAW_HTML_TAG_RE.search(approved_body):
                    add(
                        issues,
                        "error",
                        "letter_external_html_forbidden",
                        internal.path,
                        "候选外发正文只允许纯文本或受控Markdown，不得使用HTML注释、details/summary或其他原始HTML隐藏/折叠内容。",
                    )
                if external_markdown_forbidden(approved_body):
                    add(
                        issues,
                        "error",
                        "letter_external_markdown_forbidden",
                        internal.path,
                        "候选外发正文只允许普通段落、换行和简单强调；不得使用代码块、标题、列表、表格、链接或行内代码。",
                    )
                visible_approved_body = markdown_without_fenced_code(approved_body)
                compact_body = compact_contract_text(visible_approved_body)
                if len(compact_body) < 20:
                    add(
                        issues,
                        "error",
                        "letter_external_body_too_short",
                        internal.path,
                        "候选外发正文规范化后必须至少有20个可见字符，不能只保留问候或落款。",
                    )
                recipient = context_anchor(internal.frontmatter.get("recipient_role", ""))
                if not recipient or compact_contract_text(recipient) not in compact_body:
                    add(
                        issues,
                        "error",
                        "letter_recipient_anchor_missing",
                        internal.path,
                        "候选外发正文必须明确承载recipient_role中的收件对象或称谓。",
                    )
                signer = context_anchor(internal.frontmatter.get("signer", ""))
                lines = [line.strip() for line in visible_approved_body.splitlines() if line.strip()]
                salutation_valid = bool(
                    lines
                    and recipient
                    and re.fullmatch(
                        rf"(?:尊敬的)?{re.escape(recipient)}(?:[，,]?您好)?[:：]",
                        unicodedata.normalize("NFKC", lines[0]).strip(),
                    )
                )
                signer_indexes = [
                    index
                    for index, line in enumerate(lines)
                    if signer
                    and compact_contract_text(signer) == compact_contract_text(line)
                ]
                signer_index = signer_indexes[-1] if signer_indexes else -1
                structure_valid = bool(
                    len(lines) >= 3
                    and salutation_valid
                    and signer_index >= 2
                    and signer_index == len(lines) - 1
                )
                substantive_lines = lines[1:signer_index] if structure_valid else []
                substantive_body = "\n".join(substantive_lines)
                if not structure_valid or not meaningful_delivery_text(
                    substantive_body,
                    minimum_chars=20,
                ):
                    add(
                        issues,
                        "error",
                        "letter_external_structure_invalid",
                        internal.path,
                        "候选外发正文必须将称谓、至少一段实质正文和签署人分行呈现；不得把三项锚点拼成一行。",
                    )
                sentences = [
                    sentence.strip()
                    for sentence in re.split(r"(?<=[。！？!?；;])", substantive_body)
                    if sentence.strip()
                ]
                negation_re = LETTER_NEGATIVE_POLARITY_RE
                action_sentence_indexes = [
                    index
                    for index, sentence in enumerate(sentences)
                    if positive_letter_anchor(
                        internal.frontmatter.get("expected_action", ""), sentence
                    )
                    and re.search(r"(?:请|烦请|敬请|诚请|期待|希望|可否|能否)", sentence)
                    and not negation_re.search(sentence)
                ]
                purpose = internal.frontmatter.get("letter_purpose", "")
                purpose_meta_sentence_indexes = [
                    index
                    for index, sentence in enumerate(sentences)
                    if bounded_ordered_text_contains(purpose, sentence)
                    and LETTER_PURPOSE_META_RE.search(sentence)
                ]
                purpose_sentence_indexes = [
                    index
                    for index, sentence in enumerate(sentences)
                    if index not in action_sentence_indexes
                    and bounded_ordered_text_contains(purpose, sentence)
                    and meaningful_delivery_text(sentence, minimum_chars=8)
                    and not negation_re.search(sentence)
                    and index not in purpose_meta_sentence_indexes
                ]
                has_context_sentence = any(
                    index not in action_sentence_indexes
                    and index not in purpose_sentence_indexes
                    and meaningful_delivery_text(sentence, minimum_chars=8)
                    and not negation_re.search(sentence)
                    for index, sentence in enumerate(sentences)
                )
                if not action_sentence_indexes:
                    add(
                        issues,
                        "error",
                        "letter_expected_action_missing",
                        internal.path,
                        "候选外发正文必须用请/期待/希望等请求语，在同一句中连续承载expected_action；不得把行动字符分散到无关正文。",
                    )
                if purpose_meta_sentence_indexes:
                    add(
                        issues,
                        "error",
                        "letter_purpose_meta_forbidden",
                        internal.path,
                        "外发正文不得用元数据、字段名、提示词或‘发信目的为’等内部元叙述冒充真实来函目的。",
                    )
                if not has_context_sentence or not purpose_sentence_indexes:
                    add(
                        issues,
                        "error",
                        "letter_purpose_anchor_missing",
                        internal.path,
                        "候选外发正文必须分别提供：连续承载letter_purpose的肯定句，以及独立于目的/行动请求的背景或客户价值句；否定表达和通用空话不能替代发信目的。",
                    )
                if not signer or compact_contract_text(signer) not in compact_body:
                    add(
                        issues,
                        "error",
                        "letter_signer_anchor_missing",
                        internal.path,
                        "候选外发正文必须明确承载signer中的签署人。",
                    )
            for leak in external_leaks(approved_body):
                add(issues, "error", "external_candidate_leak", internal.path, f"标记间候选外发正文包含禁用内容：{leak}")
        required = internal.frontmatter.get("external_output_required") == "true"
        if required and internal.frontmatter.get("review_status") == "approved" and external is None:
            add(issues, "error", "external_letter_required", internal.path, "已批准且要求外发版，但外发文件不存在。")
    if external:
        if internal is None:
            add(issues, "error", "external_without_internal", external.path, "外发版必须有对应内部审核稿。")
            return
        if internal.frontmatter.get("module_status") != "completed" or internal.frontmatter.get("review_status") != "approved":
            add(issues, "error", "external_source_unapproved", external.path, "内部稿未completed/approved，不得存在外发版。")
        if internal.frontmatter.get("external_output_required") != "true":
            add(issues, "error", "external_not_requested", external.path, "外发版存在时内部稿external_output_required必须为true。")
        if internal.frontmatter.get("freshness_status") != "current":
            add(issues, "error", "external_source_stale", external.path, "内部稿不是current时不得存在外发版。")
        clean = external_body_without_title(external.body)
        first_line = next((line.strip() for line in external.body.splitlines() if line.strip()), "")
        expected_title = f"# {external.frontmatter.get('customer_display_name', '')}客户信（外发版）"
        if first_line != expected_title:
            add(issues, "error", "external_title_invalid", external.path, f"外发版标题应为：{expected_title}")
        if not normalize_body(clean):
            add(issues, "error", "external_body_empty", external.path, "外发版正文为空。")
        if external_markdown_forbidden(clean):
            add(
                issues,
                "error",
                "letter_external_markdown_forbidden",
                external.path,
                "外发版只允许普通段落、换行和简单强调；不得包含代码块、标题、列表、表格、链接或行内代码。",
            )
        for leak in external_leaks(external.body):
            code = "external_html_comment" if leak == "HTML注释" else "external_internal_leak"
            add(issues, "error", code, external.path, f"外发版包含禁用内容：{leak}")
        approved_body = extract_external_body(internal)
        if approved_body is not None and canonical_approved_body(clean) != canonical_approved_body(approved_body):
            add(issues, "error", "external_body_drift", external.path, "外发版与内部稿标记间已批准正文不一致。")
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
            "approval_run_id",
            "approval_action_event_id",
            "approver_actor_id",
            "approver_role",
            "approval_authority_id",
            "approver_identity_provider",
            *sorted(LETTER_FACT_REVIEW_FIELDS),
            "external_request_event_id",
            "external_requested_by_actor_id",
            "external_requested_at",
        ):
            if external.frontmatter.get(field) != internal.frontmatter.get(field):
                add(issues, "error", "external_metadata_drift", external.path, f"外发版{field}必须继承当前内部稿。")
        if external.frontmatter.get("source_internal_content_version") != internal.frontmatter.get("content_version"):
            add(issues, "error", "external_lineage_version_drift", external.path, "source_internal_content_version必须等于当前内部稿content_version。")
        if external.frontmatter.get("approved_content_version") != internal.frontmatter.get("approved_content_version"):
            add(issues, "error", "external_approval_version_drift", external.path, "外发版approved_content_version必须与内部稿一致。")


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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
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


def capture_workspace_snapshot(root: Path, documents: list[Document]) -> WorkspaceSnapshot:
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
            raise RuntimeError(f"读取工作区期间成果发生变化，请重试：{document.path.name}")
        file_states[document.path] = state.as_dict()
    for relative in AUDITED_RUNTIME_RELS:
        path = root / relative
        if path.exists():
            file_states[path] = file_state(path).as_dict()
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
    for key in ("tenant_id", "customer_id", "project_id", "authorization_owner", "authorization_expires_at"):
        value = total_data.get(key, "")
        if value:
            authorization[key] = value
    overlay = {path: text.encode("utf-8") for path, text in planned.items()}
    manifest = build_manifest(
        root,
        identity={
            "context_id": total_data.get("context_id", ""),
            "customer_id": total_data.get("customer_id", ""),
            "customer_display_name": total_data.get("customer_display_name", ""),
            "organization_scope": total_data.get("organization_scope", ""),
        },
        business_mode=total_data.get("business_mode", "") or str((snapshot.manifest or {}).get("business_mode", "")),
        route=total_data.get("route", ""),
        depth=total_data.get("depth", ""),
        task_timezone=(
            str(snapshot.manifest["task_timezone"])
            if snapshot.manifest and snapshot.manifest.get("task_timezone") is not None
            else None
        ),
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
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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
        cells = [label, "false", "not_called", "not_called", "not_required", "not_applicable", "current", "", "", "", "not_applicable", "", "none", "none", ""]
    else:
        preserved = extras or ["synced", "none", "none", "none"]
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
    clean = [re.sub(r"[\r\n]+", " ", cell).replace("|", r"\|").strip() for cell in cells]
    return "| " + " | ".join(clean) + " |"


def replace_or_insert_status_row(text: str, label: str, replacement: str) -> str:
    """Replace a status row, migrating the additive briefing row when absent."""
    pattern = rf"^\|\s*{re.escape(label)}\s*\|.*$"
    occurrences = len(re.findall(pattern, text, flags=re.MULTILINE))
    if occurrences == 1:
        return re.sub(pattern, lambda _: replacement, text, count=1, flags=re.MULTILINE)
    if occurrences > 1 or label != STATUS_LABELS["briefing_delivery"]:
        raise RuntimeError(f"综合报告缺少或重复标准状态行：{label}")
    anchor = STATUS_LABELS["customer_letter_internal"]
    anchor_pattern = rf"^\|\s*{re.escape(anchor)}\s*\|.*$"
    if len(re.findall(anchor_pattern, text, flags=re.MULTILINE)) != 1:
        raise RuntimeError("综合报告缺少唯一客户信内部审核稿状态行，无法迁移会前速览登记。")
    return re.sub(
        anchor_pattern,
        lambda match: replacement + "\n" + match.group(0),
        text,
        count=1,
        flags=re.MULTILINE,
    )


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
        extras = row[10:14] if len(row) >= 15 else ["out_of_sync", "none", "none", "input_missing"]
        if artifact_type in actions:
            extras[0] = "not_applicable" if artifact_type == "customer_letter_external" else "synced"
            extras[2] = "none"
            if artifact_type == "customer_letter_external":
                extras[1], extras[3] = "none", "none"
        replacement = registry_row(label, data, path, action=actions.get(artifact_type, "not_called"), extras=extras)
        text = replace_or_insert_status_row(text, label, replacement)
    return text


def operation_summary(total: Document, objective: str, actions: dict[str, str], cutoff: str) -> str:
    names = {
        "institution_research": "institution",
        "leader_research": "leader",
        "internal_retrieval": "internal",
        "visit_strategy": "strategy",
        "briefing_delivery": "briefing",
        "customer_letter_internal": "letter",
        "customer_letter_external": "external_letter",
    }
    action_map = {names[key]: actions.get(key, "not_called") for key in names}
    selected = [name for name in RUN_ARTIFACT_ORDER if action_map[name] != "not_called"]
    parts = [
        f"route={total.frontmatter.get('route', '')}",
        f"depth={total.frontmatter.get('depth', '')}",
        f"objective={objective}",
        "selected_modules=" + (",".join(selected) or "none"),
    ]
    for action in ("created", "updated", "reused", "generated", "not_called"):
        members = [name for name in RUN_ARTIFACT_ORDER if action_map[name] == action]
        parts.append(f"{action}=" + (",".join(members) or "none"))
    parts.append(f"target_evidence_cutoff_date={cutoff}")
    return "; ".join(parts)


def append_operation_record(text: str, *, timestamp: str, version: str, run_id: str, summary: str, owner: str) -> str:
    clean_owner = owner.replace("|", r"\|")
    row = f"| {timestamp} | {version} | {run_id} | {summary} | {clean_owner} |"
    lines = text.rstrip().splitlines()
    heading = next((index for index, line in enumerate(lines) if line.strip() == "## 9. 版本与同步记录"), None)
    if heading is None:
        raise RuntimeError("总报告缺少版本与同步记录章节，无法追加操作记录。")
    section_end = next((index for index in range(heading + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    table_rows = [index for index in range(heading + 1, section_end) if lines[index].lstrip().startswith("|")]
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
    headings = [index for index, line in enumerate(lines) if line.strip() == LETTER_REVIEW_HEADING]
    if len(headings) != 1:
        raise RuntimeError("内部稿必须恰有一个版本与审核记录章节，无法追加审计记录。")
    heading = headings[0]
    section_end = next((index for index in range(heading + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    table_rows = [index for index in range(heading + 1, section_end) if lines[index].lstrip().startswith("|")]
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
        all_planned, expected_files = manifest_for_mutation(root, planned, deleted, snapshot)

        def governed_postflight(workspace: Path) -> None:
            post_issues: list[Issue] = []
            post_documents = load_documents(workspace, post_issues)
            validate_loaded(workspace, post_documents, post_issues, strict_postflight)
            errors = [issue for issue in post_issues if issue.severity == "error"]
            if errors:
                summary = "; ".join(f"{issue.code}:{issue.message}" for issue in errors[:5])
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
            raise RuntimeError("事务写入失败且回滚不完整：" + "; ".join(rollback_errors)) from exc
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


def internal_only_safety_authorization_codes(root: Path) -> list[str]:
    """Return internal-only codes only after re-verifying the durable host seal."""
    try:
        manifest = load_manifest(root)
    except TxError as exc:
        raise RuntimeError(f"无法读取内部授权边界：{exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("无法读取内部授权边界：缺少runtime manifest。")
    gate = manifest.get("intake_preflight")
    audit = manifest.get("candidate_attestation")
    if not isinstance(gate, dict) or not isinstance(audit, dict):
        raise RuntimeError("无法读取内部授权边界：缺少完整intake门禁或独立候选签章。")
    try:
        verify_persisted_candidate_attestation(
            audit,
            current_intake_gate=gate,
            current_workspace=root.resolve(),
        )
    except CandidateAttestationError as exc:
        raise RuntimeError(f"无法读取内部授权边界：candidate_gate_attestation_invalid：{exc}") from exc
    codes = gate.get("safety_authorization_codes") if isinstance(gate, dict) else None
    if not isinstance(codes, list) or any(
        code not in {"unauthorized_patient_information", "unauthorized_internal_source"}
        for code in codes
    ):
        raise RuntimeError("无法读取内部授权边界：safety_authorization_codes无效。")
    return sorted(set(codes))


def reject_external_lifecycle_for_internal_only_sources(root: Path, operation: str) -> None:
    codes = internal_only_safety_authorization_codes(root)
    if codes:
        raise RuntimeError(
            "internal_review_draft_only：签名授权仅允许内部审核稿，不得执行"
            f"{operation}；受限风险=" + ",".join(codes)
        )


def review_letter_facts(
    root: Path,
    documents: list[Document],
    reviewer: str,
    actor_id: str,
    action_event_id: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    internals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "customer_letter_internal"]
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(internals) != 1 or len(totals) != 1:
        raise RuntimeError("事实复核需要且只能有一个客户信内部稿和一个综合报告。")
    internal, total = internals[0], totals[0]
    data = internal.frontmatter
    if data.get("module_status") != "completed" or data.get("review_status") != "pending":
        raise RuntimeError("只有completed/pending的内部稿可进行事实复核。")
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的内部稿可进行事实复核。")
    if any(data.get(field, "") for field in LETTER_FACT_REVIEW_FIELDS):
        raise RuntimeError("当前版本已存在事实复核；正文或上下文变化后应先清空旧复核谱系。")
    body = extract_external_body(internal)
    if body is None or not normalize_body(body):
        raise RuntimeError("外发正文标记无效或正文为空。")
    registry, action_event, authorization = resolve_action_assertion(
        root,
        event_id=action_event_id,
        actor_id=actor_id,
        display_name=reviewer,
        operation="review_letter_facts",
        required_roles={"evidence_reviewer"},
        context_id=data.get("context_id", ""),
        customer_id=data.get("customer_id", ""),
        business_mode=total.frontmatter.get("business_mode", ""),
        target_artifact_type="customer_letter_internal",
        target_content_version=data.get("content_version", ""),
        target_body_sha256=body_sha256(body),
        target_context_sha256=letter_context_sha256(data),
    )
    now = datetime.now(timezone.utc)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    if not CONTENT_VERSION_RE.fullmatch(data.get("content_version", "")):
        raise RuntimeError("内部稿content_version无效。")
    next_version = str(int(data["content_version"]) + 1)
    updates = {
        "latest_run_id": run_id,
        "content_version": next_version,
        "updated_at": timestamp,
        "fact_reviewer": authorization.display_name,
        "fact_reviewed_at": timestamp,
        "fact_reviewed_content_version": next_version,
        "fact_reviewed_body_sha256": body_sha256(body),
        "fact_reviewed_context_sha256": letter_context_sha256(data),
        "fact_reviewed_run_id": run_id,
        "fact_review_action_event_id": action_event_id,
        **authorization.audit_fields("fact_reviewer"),
    }
    updated_internal = replace_flat_frontmatter(internal.text, updates)
    updated_internal = append_letter_review_record(
        updated_internal,
        timestamp=timestamp,
        version=next_version,
        run_id=run_id,
        summary=f"完成客户信事实复核；reviewer={authorization.display_name}",
        owner=data["runtime_owner"],
        review_status="pending",
    )
    internal_data = data | updates
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    actions = preserve_selected_actions(
        total,
        by_type,
        actions_with_research_carrier(by_type, "customer_letter_internal", "updated"),
    )
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
        {"latest_run_id": run_id, "content_version": next_total_version, "updated_at": timestamp, **readiness_reset_updates()},
    )
    summary = operation_summary(total, "review_letter_facts", actions, data["evidence_cutoff_date"])
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=data["runtime_owner"],
    )
    claim_global_nonce(
        action_event,
        workspace=root,
        event_id=action_event_id,
        operation="review_letter_facts",
        claimed_at=timestamp,
    )
    consumed_registry = consume_action_assertion(
        registry, event_id=action_event_id, consumed_at=timestamp, run_id=run_id
    )
    return commit_mutation(
        {
            internal.path: updated_internal,
            total.path: updated_total,
            root / GOVERNANCE_CONTEXT_REL: governance_json(consumed_registry),
        },
        [],
        internal.path,
        snapshot=snapshot,
        workspace=root,
        operation="review_letter_facts",
    )


def approve_internal(
    root: Path,
    documents: list[Document],
    approver: str,
    actor_id: str,
    action_event_id: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    reject_external_lifecycle_for_internal_only_sources(root, "外发审批")
    internals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "customer_letter_internal"]
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(internals) != 1 or len(totals) != 1:
        raise RuntimeError("审批需要且只能有一个客户信内部稿和一个综合报告。")
    internal, total = internals[0], totals[0]
    data = internal.frontmatter
    if total.frontmatter.get("route") != "letter" or total.frontmatter.get("workflow_stage") not in {"review", "closed"}:
        raise RuntimeError("审批只能在route=letter且workflow_stage=review/closed的上下文执行。")
    if total.frontmatter.get("module_status") != "completed" or total.frontmatter.get("freshness_status") != "current":
        raise RuntimeError("审批前综合报告必须completed/current。")
    if data.get("module_status") != "completed" or data.get("review_status") != "pending":
        raise RuntimeError("只有completed/pending的内部稿可加审批戳；changes_requested必须修改并重新提交为pending。")
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的内部稿可批准。")
    if any(doc.frontmatter.get("artifact_type") == "customer_letter_external" for doc in documents):
        raise RuntimeError("外发版已存在；修改或重新审批前请先按治理流程归档旧外发版。")
    body = extract_external_body(internal)
    if body is None or not normalize_body(body):
        raise RuntimeError("外发正文标记无效或正文为空。")
    fact_values = {field: data.get(field, "") for field in LETTER_FACT_REVIEW_FIELDS}
    if not all(fact_values.values()):
        raise RuntimeError("外发审批前必须先由独立evidence_reviewer完成宿主签名的事实复核。")
    if (
        fact_values["fact_reviewer_role"] != "evidence_reviewer"
        or fact_values["fact_reviewed_content_version"] != data.get("content_version", "")
        or fact_values["fact_reviewed_body_sha256"] != body_sha256(body)
        or fact_values["fact_reviewed_context_sha256"] != letter_context_sha256(data)
    ):
        raise RuntimeError("客户信事实复核与当前版本、正文或业务上下文不一致。")
    registry, action_event, authorization = resolve_action_assertion(
        root,
        event_id=action_event_id,
        actor_id=actor_id,
        display_name=approver,
        operation="approve_letter",
        required_roles={"external_approver"},
        context_id=data.get("context_id", ""),
        customer_id=data.get("customer_id", ""),
        business_mode=total.frontmatter.get("business_mode", ""),
        target_artifact_type="customer_letter_internal",
        target_content_version=data.get("content_version", ""),
        target_body_sha256=body_sha256(body),
        target_context_sha256=letter_context_sha256(data),
    )
    clean_approver = authorization.display_name
    if authorization.actor_id == fact_values["fact_reviewer_actor_id"]:
        raise RuntimeError("客户信事实复核人与外发审批人必须是两个独立actor。")
    leaks = external_leaks(body)
    if leaks:
        raise RuntimeError("候选外发正文包含禁用内容：" + ", ".join(leaks))
    now = datetime.now(timezone.utc)
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
        "approval_run_id": run_id,
        "approval_action_event_id": action_event_id,
        "approver_actor_id": authorization.actor_id,
        "approver_role": authorization.role,
        "approval_authority_id": authorization.grant_id,
        "approver_identity_provider": authorization.identity_provider,
        **{field: "" for field in EXTERNAL_REQUEST_FIELDS},
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
    carrier_for_prefix = {"I": "institution_research", "L": "leader_research", "N": "internal_retrieval"}
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
        {"latest_run_id": run_id, "content_version": next_total_version, "updated_at": timestamp, **readiness_reset_updates()},
    )
    summary = operation_summary(total, "approve_internal_letter", actions, data["evidence_cutoff_date"])
    updated_total = append_operation_record(updated_total, timestamp=timestamp, version=next_total_version, run_id=run_id, summary=summary, owner=data["runtime_owner"])
    claim_global_nonce(
        action_event,
        workspace=root,
        event_id=action_event_id,
        operation="approve_letter",
        claimed_at=timestamp,
    )
    consumed_registry = consume_action_assertion(
        registry,
        event_id=action_event_id,
        consumed_at=timestamp,
        run_id=run_id,
    )
    return commit_mutation(
        {
            internal.path: updated_internal,
            total.path: updated_total,
            root / GOVERNANCE_CONTEXT_REL: governance_json(consumed_registry),
        },
        [],
        internal.path,
        snapshot=snapshot,
        workspace=root,
        operation="approve_letter",
    )


def clean_actor(value: str, flag: str) -> str:
    actor = re.sub(r"[|\r\n]+", " ", value).strip()
    if not actor or actor in {"待确认", "待指定"} or len(actor) > 100:
        raise RuntimeError(f"{flag}必须是1—100字符的实名责任人或稳定责任角色。")
    return actor


def actions_with_research_carrier(
    by_type: dict[str, Document],
    primary_type: str,
    primary_action: str,
) -> dict[str, str]:
    actions = {primary_type: primary_action}
    if primary_type not in {"institution_research", "leader_research", "internal_retrieval"}:
        for carrier in ("institution_research", "leader_research", "internal_retrieval"):
            document = by_type.get(carrier)
            if document and document.frontmatter.get("module_status") == "completed" and document.frontmatter.get("freshness_status") == "current":
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
    actor_id: str,
    action_event_id: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    artifact_type = GENERIC_REVIEW_TARGETS[target_name]
    targets = [doc for doc in documents if doc.frontmatter.get("artifact_type") == artifact_type]
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(targets) != 1 or len(totals) != 1:
        raise RuntimeError(f"审批需要且只能有一个{artifact_type}和一个综合报告。")
    target, total = targets[0], totals[0]
    data = target.frontmatter
    if total.frontmatter.get("workflow_stage") not in {"review", "closed"}:
        raise RuntimeError("通用审批只能在workflow_stage=review/closed的上下文执行。")
    if data.get("module_status") != "completed" or data.get("review_status") != "pending":
        raise RuntimeError("只有completed/pending成果可审批；changes_requested必须修改并重新提交为pending。")
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的成果可审批。")
    required_roles = {
        "strategy": {"commercial_reviewer"},
        "briefing": {"evidence_reviewer", "account_owner"},
    }.get(target_name, {"evidence_reviewer"})
    registry, action_event, authorization = resolve_action_assertion(
        root,
        event_id=action_event_id,
        actor_id=actor_id,
        display_name=reviewer,
        operation=f"approve_artifact:{target_name}",
        required_roles=required_roles,
        context_id=data.get("context_id", ""),
        customer_id=data.get("customer_id", ""),
        business_mode=total.frontmatter.get("business_mode", ""),
        target_artifact_type=artifact_type,
        target_content_version=data.get("content_version", ""),
        target_body_sha256=body_sha256(target.body),
        target_context_sha256="",
    )
    actor = authorization.display_name
    if not CONTENT_VERSION_RE.fullmatch(data.get("content_version", "")):
        raise RuntimeError("待审批成果content_version无效。")
    now = datetime.now(timezone.utc)
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
        "review_action_event_id": action_event_id,
        **authorization.audit_fields("reviewer"),
    }
    if artifact_type == "briefing_delivery":
        updates["delivery_state"] = "ready"
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
    summary = operation_summary(total, f"approve_{target_name}", actions, data["evidence_cutoff_date"])
    updated_total = append_operation_record(
        updated_total,
        timestamp=timestamp,
        version=next_total_version,
        run_id=run_id,
        summary=summary,
        owner=total.frontmatter["runtime_owner"],
    )
    claim_global_nonce(
        action_event,
        workspace=root,
        event_id=action_event_id,
        operation=f"approve_artifact:{target_name}",
        claimed_at=timestamp,
    )
    consumed_registry = consume_action_assertion(
        registry,
        event_id=action_event_id,
        consumed_at=timestamp,
        run_id=run_id,
    )
    return commit_mutation(
        {
            target.path: updated_target,
            total.path: updated_total,
            root / GOVERNANCE_CONTEXT_REL: governance_json(consumed_registry),
        },
        [],
        target.path,
        snapshot=snapshot,
        workspace=root,
        operation=f"approve_{target_name}",
    )


def begin_letter_revision(
    root: Path,
    documents: list[Document],
    reviewer: str,
    actor_id: str,
    action_event_id: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    internals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "customer_letter_internal"]
    externals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "customer_letter_external"]
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(internals) != 1 or len(externals) != 1 or len(totals) != 1:
        raise RuntimeError("开始修订需要一个内部稿、一个现行外发版和一个综合报告。")
    internal, external, total = internals[0], externals[0], totals[0]
    approved_body = extract_external_body(internal)
    if approved_body is None or not normalize_body(approved_body):
        raise RuntimeError("现行内部稿缺少可验证的已批准正文。")
    registry, action_event, authorization = resolve_action_assertion(
        root,
        event_id=action_event_id,
        actor_id=actor_id,
        display_name=reviewer,
        operation="begin_letter_revision",
        required_roles={"runtime_owner", "external_approver"},
        context_id=internal.frontmatter.get("context_id", ""),
        customer_id=internal.frontmatter.get("customer_id", ""),
        business_mode=total.frontmatter.get("business_mode", ""),
        target_artifact_type="customer_letter_internal",
        target_content_version=internal.frontmatter.get("content_version", ""),
        target_body_sha256=body_sha256(approved_body),
        target_context_sha256=letter_context_sha256(internal.frontmatter),
        separate_from_runtime=False,
    )
    actor = authorization.display_name
    if internal.frontmatter.get("review_status") != "approved":
        raise RuntimeError("只有已有approved外发谱系的内部稿可开始修订。")
    now = datetime.now(timezone.utc)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    archive_dir = root / "archive" / "letters"
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
        **{
            field: ""
            for field in APPROVAL_FIELDS
            | LETTER_ACTOR_FIELDS
            | LETTER_FACT_REVIEW_FIELDS
            | EXTERNAL_REQUEST_FIELDS
        },
        "revision_action_event_id": action_event_id,
        "revision_run_id": run_id,
        "revision_actor_id": authorization.actor_id,
        "revision_at": timestamp,
        "revision_target_content_version": data["content_version"],
        "revision_target_body_sha256": body_sha256(approved_body),
        "revision_target_context_sha256": letter_context_sha256(data),
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
    without_external = {key: value for key, value in by_type.items() if key != "customer_letter_external"}
    actions = actions_with_research_carrier(without_external, "customer_letter_internal", "updated")
    actions = preserve_selected_actions(total, without_external, actions, excluded={"customer_letter_external"})
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
    summary = operation_summary(total, "begin_letter_revision", actions, data["evidence_cutoff_date"])
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
    claim_global_nonce(
        action_event,
        workspace=root,
        event_id=action_event_id,
        operation="begin_letter_revision",
        claimed_at=timestamp,
    )
    consumed_registry = consume_action_assertion(
        registry,
        event_id=action_event_id,
        consumed_at=timestamp,
        run_id=run_id,
    )
    planned[root / GOVERNANCE_CONTEXT_REL] = governance_json(consumed_registry)
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
    root: Path,
    documents: list[Document],
    reviewer: str,
    actor_id: str,
    action_event_id: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(totals) != 1:
        raise RuntimeError("就绪审批需要且只能有一个综合报告。")
    total = totals[0]
    if total.frontmatter.get("business_mode", "") == "letter":
        reject_external_lifecycle_for_internal_only_sources(root, "mark-ready")
    if total.frontmatter.get("module_status") != "completed" or total.frontmatter.get("freshness_status") != "current":
        raise RuntimeError("ready_for_use审批前综合报告必须completed/current。")
    if total.frontmatter.get("workflow_stage") not in {"output", "review", "closed"}:
        raise RuntimeError("ready_for_use审批只能在output/review/closed阶段执行。")
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    rows = parse_status_rows(total)
    selected = {key for key, row in rows.items() if len(row) >= 2 and row[1] == "true"}
    for artifact_type in required_research_review_types(by_type):
        artifact = by_type.get(artifact_type)
        if (
            artifact is None
            or artifact.frontmatter.get("module_status") != "completed"
            or artifact.frontmatter.get("freshness_status") != "current"
            or artifact.frontmatter.get("review_status") != "approved"
        ):
            raise RuntimeError(
                f"{artifact_type}被选中或被下游引用，但未完成独立evidence_reviewer的当前正文SHA审核，不得标记ready_for_use。"
            )
    for artifact_type in selected & ((GENERIC_REVIEW_TYPES - set(RESEARCH_PREFIX)) | {"customer_letter_internal"}):
        artifact = by_type.get(artifact_type)
        if artifact is None or artifact.frontmatter.get("review_status") != "approved":
            raise RuntimeError(f"{artifact_type}未完成approved审核，不得标记ready_for_use。")
    business_mode = total.frontmatter.get("business_mode", "")
    if business_mode == "letter":
        internal = by_type.get("customer_letter_internal")
        external = by_type.get("customer_letter_external")
        if internal is None or external is None:
            raise RuntimeError("letter_external_required：一封信只有经审批并按第二次请求生成外发版后才能mark-ready。")
        if "customer_letter_external" not in selected:
            raise RuntimeError("letter_external_required：综合报告未把当前外发版登记为本轮选中成果。")
        if (
            internal.frontmatter.get("external_output_required") != "true"
            or internal.frontmatter.get("review_status") != "approved"
            or external.frontmatter.get("module_status") != "completed"
            or external.frontmatter.get("review_status") != "approved"
            or external.frontmatter.get("freshness_status") != "current"
        ):
            raise RuntimeError("letter_external_not_ready：内部稿或外发版状态未满足ready门禁。")
        request_id = external.frontmatter.get("external_request_event_id", "")
        if not request_id or request_id != internal.frontmatter.get("external_request_event_id"):
            raise RuntimeError("letter_external_request_missing：外发版缺少一致的已消费第二次请求谱系。")
        registry = load_governance_context(root)
        event = registry.get("external_requests", {}).get(request_id)
        if (
            not isinstance(event, dict)
            or event.get("consumed_by_run_id") != external.frontmatter.get("latest_run_id")
            or not event.get("consumed_at")
        ):
            raise RuntimeError("letter_external_request_unconsumed：第二次请求事件尚未由当前外发事务消费。")
    if business_mode == "briefing":
        briefing = by_type.get("briefing_delivery")
        if (
            briefing is None
            or briefing.frontmatter.get("module_status") != "completed"
            or briefing.frontmatter.get("freshness_status") != "current"
            or briefing.frontmatter.get("review_status") != "approved"
            or briefing.frontmatter.get("delivery_state") != "ready"
        ):
            raise RuntimeError("briefing_delivery_not_ready：会前速览必须completed/current/approved且delivery_state=ready。")
    readiness_roles = {
        "briefing": {"evidence_reviewer", "account_owner"},
        "standard_visit": {"commercial_reviewer"},
        "strategic_account": {"account_owner"},
        "letter": {"external_approver"},
    }
    registry, action_event, authorization = resolve_action_assertion(
        root,
        event_id=action_event_id,
        actor_id=actor_id,
        display_name=reviewer,
        operation=f"mark_ready:{business_mode}",
        required_roles=readiness_roles.get(business_mode, set()),
        context_id=total.frontmatter.get("context_id", ""),
        customer_id=total.frontmatter.get("customer_id", ""),
        business_mode=business_mode,
        target_artifact_type="comprehensive_report",
        target_content_version=total.frontmatter.get("content_version", ""),
        target_body_sha256=body_sha256(total.body),
        target_context_sha256="",
    )
    actor = authorization.display_name
    actions = {
        artifact_type: "reused"
        for artifact_type in selected
        if artifact_type in by_type
    }
    if total.frontmatter.get("route") in {"visit_prep", "strategy", "letter"} and not (
        actions.keys() & {"institution_research", "leader_research", "internal_retrieval"}
    ):
        actions.update(actions_with_research_carrier(by_type, "comprehensive_report", "not_called"))
        actions.pop("comprehensive_report", None)
    now = datetime.now(timezone.utc)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    updated_total = update_operation_rows(total, by_type, metadata={}, paths={}, actions=actions)
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
    summary = operation_summary(total, "mark_ready_for_use", actions, total.frontmatter["evidence_cutoff_date"])
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
            "readiness_target_body_sha256": str(action_event["target_body_sha256"]),
            "readiness_action_event_id": action_event_id,
            **authorization.audit_fields("readiness_reviewer"),
        },
    )
    claim_global_nonce(
        action_event,
        workspace=root,
        event_id=action_event_id,
        operation=f"mark_ready:{business_mode}",
        claimed_at=timestamp,
    )
    consumed_registry = consume_action_assertion(
        registry,
        event_id=action_event_id,
        consumed_at=timestamp,
        run_id=run_id,
    )
    return commit_mutation(
        {
            total.path: updated_total,
            root / GOVERNANCE_CONTEXT_REL: governance_json(consumed_registry),
        },
        [],
        total.path,
        snapshot=snapshot,
        workspace=root,
        operation="mark_ready",
        strict_postflight=True,
    )


def emit_external(
    root: Path,
    documents: list[Document],
    actor_id: str,
    request_event_id: str,
    snapshot: WorkspaceSnapshot,
) -> Mutation:
    reject_external_lifecycle_for_internal_only_sources(root, "外发版生成")
    internals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "customer_letter_internal"]
    totals = [doc for doc in documents if doc.frontmatter.get("artifact_type") == "comprehensive_report"]
    if len(internals) != 1 or len(totals) != 1:
        raise RuntimeError("--emit-external需要且只能有一个客户信内部审核稿和一个综合报告。")
    internal, total = internals[0], totals[0]
    data = internal.frontmatter
    if total.frontmatter.get("route") != "letter" or total.frontmatter.get("workflow_stage") not in {"review", "closed"}:
        raise RuntimeError("外发生成只能在route=letter且workflow_stage=review/closed的上下文执行。")
    if total.frontmatter.get("module_status") != "completed" or total.frontmatter.get("freshness_status") != "current":
        raise RuntimeError("外发生成前综合报告必须completed/current。")
    if data.get("module_status") != "completed" or data.get("review_status") != "approved":
        raise RuntimeError("只有completed/approved的内部稿可抽取外发版。")
    if data.get("freshness_status") != "current":
        raise RuntimeError("只有freshness_status=current的内部稿可抽取外发版。")
    body = extract_external_body(internal)
    if body is None or not normalize_body(body):
        raise RuntimeError("外发正文标记无效或正文为空。")
    if data.get("approved_body_sha256") != body_sha256(body) or data.get("approved_content_version") != data.get("content_version"):
        raise RuntimeError("审批戳与当前正文或版本不一致，必须重新审核。")
    leaks = external_leaks(body)
    if leaks:
        raise RuntimeError("候选外发正文包含禁用内容：" + ", ".join(leaks))
    registry, request_event, request_actor = resolve_external_request(
        root,
        event_id=request_event_id,
        actor_id=actor_id,
        internal=data,
        total=total.frontmatter,
    )
    now = datetime.now(timezone.utc)
    timestamp, run_id = now.isoformat().replace("+00:00", "Z"), new_run_id(now)
    internal_version = str(int(data["content_version"]) + 1)
    internal_updates = {
        "latest_run_id": run_id,
        "content_version": internal_version,
        "updated_at": timestamp,
        "external_output_required": "true",
        "approved_content_version": internal_version,
        "external_request_event_id": request_event_id,
        "external_requested_by_actor_id": request_actor.actor_id,
        "external_requested_at": str(request_event["requested_at"]),
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
        "approval_run_id": data["approval_run_id"],
        "approval_action_event_id": data["approval_action_event_id"],
        "approver_actor_id": data["approver_actor_id"],
        "approver_role": data["approver_role"],
        "approval_authority_id": data["approval_authority_id"],
        "approver_identity_provider": data["approver_identity_provider"],
        **{field: internal_data.get(field, "") for field in LETTER_FACT_REVIEW_FIELDS},
        "external_request_event_id": request_event_id,
        "external_requested_by_actor_id": request_actor.actor_id,
        "external_requested_at": str(request_event["requested_at"]),
        "source_internal_content_version": internal_version,
    }
    fields = [yaml_line(key, value) for key, value in external_data.items()]
    external_text = "---\n" + "\n".join(fields) + "\n---\n\n" + f"# {data['customer_display_name']}客户信（外发版）\n\n" + canonical_approved_body(body) + "\n"
    by_type = {doc.frontmatter.get("artifact_type", ""): doc for doc in documents}
    actions = {"customer_letter_internal": "updated", "customer_letter_external": "generated"}
    carrier_for_prefix = {"I": "institution_research", "L": "leader_research", "N": "internal_retrieval"}
    for claim_id in set(CLAIM_RE.findall(internal.body)):
        carrier = carrier_for_prefix[claim_id.split("-")[1]]
        if carrier in by_type:
            actions[carrier] = "reused"
    actions = preserve_selected_actions(total, by_type, actions)
    if not (actions.keys() & {"institution_research", "leader_research", "internal_retrieval"}):
        raise RuntimeError("外发运行缺少可复用的current研究台账载体。")
    updated_total = update_operation_rows(
        total,
        by_type,
        metadata={"customer_letter_internal": internal_data, "customer_letter_external": external_data},
        paths={"customer_letter_internal": internal.path, "customer_letter_external": target},
        actions=actions,
    )
    total_version = total.frontmatter.get("content_version", "")
    if not CONTENT_VERSION_RE.fullmatch(total_version):
        raise RuntimeError("综合报告content_version无效。")
    next_total_version = str(int(total_version) + 1)
    updated_total = replace_flat_frontmatter(
        updated_total,
        {"latest_run_id": run_id, "content_version": next_total_version, "updated_at": timestamp, **readiness_reset_updates()},
    )
    summary = operation_summary(total, "generate_external", actions, data["evidence_cutoff_date"])
    updated_total = append_operation_record(updated_total, timestamp=timestamp, version=next_total_version, run_id=run_id, summary=summary, owner=data["runtime_owner"])
    claim_global_nonce(
        request_event,
        workspace=root,
        event_id=request_event_id,
        operation="emit_external",
        claimed_at=timestamp,
    )
    consumed_registry = consume_external_request(
        registry,
        event_id=request_event_id,
        consumed_at=timestamp,
        run_id=run_id,
    )
    return commit_mutation(
        {
            internal.path: updated_internal,
            total.path: updated_total,
            target: external_text,
            root / GOVERNANCE_CONTEXT_REL: governance_json(consumed_registry),
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
    "briefing_delivery": 3,
}


def validate_candidate_attestation_audit(
    root: Path,
    manifest_path: Path,
    manifest: Mapping[str, object],
    issues: list[Issue],
    validation_profile: str,
) -> None:
    audit = manifest.get("candidate_attestation")
    if audit is None:
        if validation_profile == "release":
            add(issues, "error", "candidate_attestation_required", manifest_path, "release必须保留可历史验签的完整宿主候选签章材料。")
        return
    if not isinstance(audit, dict) or set(audit) != CANDIDATE_ATTESTATION_AUDIT_FIELDS:
        add(issues, "error", "candidate_attestation_audit_invalid", manifest_path, "candidate attestation审计摘要字段不完整或含未知字段。")
        return
    if (
        audit.get("schema") != CANDIDATE_ATTESTATION_AUDIT_SCHEMA
        or audit.get("attestation_schema") != ATTESTATION_SCHEMA
        or audit.get("audience") != ATTESTATION_AUDIENCE
    ):
        add(issues, "error", "candidate_attestation_audit_invalid", manifest_path, "candidate attestation审计schema/audience无效。")
    for field in (
        "attestation_sha256", "source_manifest_sha256", "input_payload_sha256",
        "final_manifest_sha256", "intake_gate_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(audit.get(field, ""))):
            add(issues, "error", "candidate_attestation_audit_invalid", manifest_path, f"candidate_attestation.{field}不是SHA-256。")
    for field in (
        "attestation_id", "issuer", "key_id", "session_id", "customer_id",
        "source_workspace", "candidate_workspace", "formal_workspace",
    ):
        if not isinstance(audit.get(field), str) or not str(audit[field]).strip():
            add(issues, "error", "candidate_attestation_audit_invalid", manifest_path, f"candidate_attestation.{field}缺失。")
    if audit.get("context_id") != manifest.get("context_id"):
        add(issues, "error", "candidate_attestation_lineage_drift", manifest_path, "candidate attestation context_id与正式manifest不一致。")
    if audit.get("customer_id") != manifest.get("customer_id"):
        add(issues, "error", "candidate_attestation_lineage_drift", manifest_path, "candidate attestation customer_id与正式manifest不一致。")
    if not RUN_RE.fullmatch(str(audit.get("run_id", ""))):
        add(issues, "error", "candidate_attestation_lineage_drift", manifest_path, "candidate attestation run_id无效。")
    source_revision = audit.get("source_manifest_revision")
    transaction_sequence = manifest.get("transaction_sequence")
    if (
        not isinstance(source_revision, int)
        or isinstance(source_revision, bool)
        or not isinstance(transaction_sequence, int)
        or source_revision < 1
        or source_revision >= transaction_sequence
    ):
        add(issues, "error", "candidate_attestation_lineage_drift", manifest_path, "candidate attestation source revision必须早于当前正式事务序号。")
    source_workspace = Path(str(audit.get("source_workspace", "")))
    candidate_workspace = Path(str(audit.get("candidate_workspace", "")))
    if not source_workspace.is_absolute() or not candidate_workspace.is_absolute() or candidate_workspace == source_workspace:
        add(issues, "error", "candidate_attestation_lineage_drift", manifest_path, "candidate/source workspace必须是两个不同的绝对身份路径。")
    issued = parse_expiry(str(audit.get("issued_at", "")))
    expires = parse_expiry(str(audit.get("expires_at", "")))
    host_authorized = parse_expiry(str(audit.get("host_authorized_at", "")))
    if (
        issued is None
        or expires is None
        or host_authorized is None
        or not (issued <= host_authorized < expires)
        or expires - issued > timedelta(minutes=15)
    ):
        add(issues, "error", "candidate_attestation_time_invalid", manifest_path, "candidate attestation签发、宿主授权与过期时间无效。")
    intake_gate = manifest.get("intake_preflight")
    if not isinstance(intake_gate, dict):
        add(issues, "error", "candidate_attestation_gate_missing", manifest_path, "candidate attestation缺少当前完整intake门禁供复验。")
        return
    try:
        verify_persisted_candidate_attestation(
            audit,
            current_intake_gate=intake_gate,
            current_workspace=root.resolve(),
        )
    except CandidateAttestationError as exc:
        add(issues, "error", "candidate_attestation_signature_or_gate_invalid", manifest_path, str(exc))


def validate_runtime_manifest(
    root: Path,
    by_type: dict[str, Document],
    issues: list[Issue],
    strict: bool,
    validation_profile: str = "candidate",
    current_time: datetime | None = None,
    *,
    claims: Mapping[str, ClaimDefinition] | None = None,
    sources: Mapping[str, SourceDefinition] | None = None,
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    manifest_path = root / MANIFEST_REL
    if not manifest_path.exists():
        severity = "error" if strict else "warning"
        add(issues, severity, "runtime_manifest_missing", root, "缺少机器权威runtime/manifest.json；旧工作区应先安全续建迁移。")
        return
    try:
        manifest = load_manifest(root)
    except (OSError, UnicodeError, TxError) as exc:
        add(issues, "error", "runtime_manifest_invalid", manifest_path, str(exc))
        return
    assert manifest is not None
    validate_candidate_attestation_audit(
        root,
        manifest_path,
        manifest,
        issues,
        validation_profile,
    )
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
            add(issues, "error", "runtime_manifest_drift", manifest_path, f"{key}与综合报告不一致。")
    actual_subject_binding = manifest.get("subject_binding")
    intake_gate = manifest.get("intake_preflight")
    signed_subject_resolution = (
        intake_gate.get("subject_resolution") if isinstance(intake_gate, dict) else None
    )
    if not isinstance(actual_subject_binding, dict):
        add(issues, "error", "runtime_subject_binding_missing", manifest_path, "缺少规范主体绑定摘要。")
    else:
        if actual_subject_binding != signed_subject_resolution:
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding必须与签名intake中的subject_resolution逐字段一致。")
        canonical_name = re.sub(
            r"\s+",
            " ",
            unicodedata.normalize("NFKC", data.get("customer_display_name", "")),
        ).strip()
        entity_key = actual_subject_binding.get("canonical_entity_key")
        jurisdiction = actual_subject_binding.get("jurisdiction")
        expected_subject_sha = canonical_subject_digest(canonical_name, entity_key, jurisdiction)
        expected_scope_sha = hashlib.sha256(
            re.sub(
                r"\s+",
                " ",
                unicodedata.normalize("NFKC", data.get("organization_scope", "")),
            ).strip().encode("utf-8")
        ).hexdigest()
        if actual_subject_binding.get("schema") != "discovery-call-subject-resolution/v1":
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.schema无效。")
        if actual_subject_binding.get("canonical_customer_name") != canonical_name:
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.canonical_customer_name与成果主体不一致。")
        if not isinstance(entity_key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}", entity_key):
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.canonical_entity_key无效。")
        if not isinstance(jurisdiction, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}", jurisdiction):
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.jurisdiction无效。")
        if actual_subject_binding.get("canonical_subject_sha256") != expected_subject_sha:
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.canonical_subject_sha256与规范主体三元组不一致。")
        if actual_subject_binding.get("organization_scope_sha256") != expected_scope_sha:
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.organization_scope_sha256与成果范围不一致。")
        if actual_subject_binding.get("customer_id") != data.get("customer_id", ""):
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.customer_id与成果不一致。")
        id_source = actual_subject_binding.get("id_source")
        if id_source not in {"canonical_derived", "host_attested_external"}:
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "subject_binding.id_source无效。")
        elif id_source == "canonical_derived" and actual_subject_binding.get("customer_id") != "cust-" + expected_subject_sha[:12]:
            add(issues, "error", "runtime_subject_binding_drift", manifest_path, "canonical_derived customer_id与规范主体不一致。")
    expected_ready = data.get("ready_for_use", "false") == "true"
    if manifest.get("ready_for_use") is not expected_ready:
        add(issues, "error", "runtime_manifest_ready_drift", manifest_path, "ready_for_use与综合报告不一致。")
    safety_codes = intake_gate.get("safety_authorization_codes") if isinstance(intake_gate, dict) else None
    if not isinstance(safety_codes, list) or any(
        code not in {"unauthorized_patient_information", "unauthorized_internal_source"}
        for code in safety_codes
    ):
        add(issues, "error", "runtime_safety_authorization_invalid", manifest_path, "intake_preflight.safety_authorization_codes无效。")
    elif safety_codes and data.get("business_mode") == "letter":
        internal_letter = by_type.get("customer_letter_internal")
        if internal_letter is not None and internal_letter.frontmatter.get("review_status") == "approved":
            add(issues, "error", "internal_only_source_external_approval", internal_letter.path, "内部来源授权仅允许internal_review_draft，不得形成外发审批状态。")
        if by_type.get("customer_letter_external") is not None:
            add(issues, "error", "internal_only_source_external_artifact", by_type["customer_letter_external"].path, "内部来源授权不得生成外发版。")
        if expected_ready:
            add(issues, "error", "internal_only_source_ready_forbidden", total.path, "内部来源授权不得标记ready_for_use。")
        if validation_profile == "release":
            add(issues, "error", "internal_only_source_release_forbidden", total.path, "内部来源授权仅支持内部审核稿，不得通过release校验。")
    selected_modules = manifest.get("selected_modules")
    selected_module_names = (
        [str(item) for item in selected_modules]
        if isinstance(selected_modules, list)
        and all(isinstance(item, str) for item in selected_modules)
        else []
    )
    expected_delivery_summary = delivery_summary_for_documents(
        by_type,
        business_mode=data.get("business_mode"),
        selected_modules=selected_module_names,
    )
    manifest_delivery_summary = manifest.get("delivery_summary")
    current_strategy_selected = (
        data.get("business_mode") in {"briefing", "standard_visit", "strategic_account"}
        and "strategy" in selected_module_names
    )
    if validation_profile in {"candidate", "release"} and current_strategy_selected:
        if expected_delivery_summary is None:
            add(issues, "error", "delivery_summary_invalid", manifest_path, "交流策略无法形成受控决策五元组。")
        elif manifest_delivery_summary != expected_delivery_summary:
            add(issues, "error", "runtime_delivery_summary_drift", manifest_path, "manifest.delivery_summary必须与当前交流策略的建议、投入、动作、owner和日期完全一致。")
    elif validation_profile in {"candidate", "release"} and manifest_delivery_summary is not None:
        add(issues, "error", "runtime_delivery_summary_stale", manifest_path, "当前候选无交流策略时manifest不得保留历史决策五元组。")
    elif manifest_delivery_summary is not None and expected_delivery_summary is not None and manifest_delivery_summary != expected_delivery_summary:
        add(issues, "error", "runtime_delivery_summary_drift", manifest_path, "manifest.delivery_summary与当前交流策略不一致。")
    records = manifest.get("artifacts")
    if not isinstance(records, dict):
        add(issues, "error", "runtime_manifest_artifacts_invalid", manifest_path, "artifacts必须为对象。")
        return
    for artifact_type, document in by_type.items():
        record = records.get(artifact_type)
        if not isinstance(record, dict):
            add(issues, "error", "runtime_manifest_artifact_missing", manifest_path, f"缺少成果记录：{artifact_type}。")
            continue
        if record.get("path") != document.path.name or record.get("sha256") != sha256_file(document.path):
            add(issues, "error", "runtime_manifest_artifact_drift", document.path, "成果路径或SHA-256与机器清单不一致；禁止绕过事务直接修改。")
        state = record.get("state")
        if not isinstance(state, dict):
            add(issues, "error", "runtime_manifest_state_invalid", manifest_path, f"{artifact_type}.state无效。")
        else:
            for field in ("module_status", "review_status", "connector_status", "freshness_status"):
                if state.get(field) != document.frontmatter.get(field, ""):
                    add(issues, "error", "runtime_manifest_state_drift", document.path, f"{field}与机器清单不一致。")
        for field in ("content_version", "latest_run_id"):
            if str(record.get(field, "")) != document.frontmatter.get(field, ""):
                add(issues, "error", "runtime_manifest_version_drift", document.path, f"{field}与机器清单不一致。")
        if artifact_type == "visit_strategy" and record.get("strategy_variant") != document.frontmatter.get("strategy_variant", ""):
            add(
                issues,
                "error",
                "runtime_manifest_strategy_variant_drift",
                document.path,
                "交流策略strategy_variant与机器清单不一致。",
            )
    extras = set(records) - set(by_type)
    if extras:
        add(issues, "error", "runtime_manifest_phantom_artifact", manifest_path, "清单登记了不存在的根成果：" + ", ".join(sorted(extras)))

    rows = parse_status_rows(total)
    expected_modules = sorted(
        MODULE_NAME_FOR_TYPE[artifact_type]
        for artifact_type, row in rows.items()
        if artifact_type in MODULE_NAME_FOR_TYPE and len(row) >= 2 and row[1] == "true"
    )
    actual_modules = manifest.get("selected_modules")
    if not isinstance(actual_modules, list) or sorted(str(item) for item in actual_modules) != expected_modules:
        add(issues, "error", "runtime_manifest_selection_drift", manifest_path, "selected_modules与综合报告本轮登记不一致。")

    runtime_records = manifest.get("runtime_files", {})
    expected_runtime = {
        "search-plan.json": "discovery-call-search-plan/v2",
        "source-cache.json": "discovery-call-source-cache/v1",
        "evidence-manifest.json": "discovery-call-evidence-manifest/v1",
        "run-metrics.json": "discovery-call-run-metrics/v1",
    }
    if not isinstance(runtime_records, dict):
        add(issues, "error", "runtime_manifest_files_invalid", manifest_path, "runtime_files必须为对象。")
        runtime_records = {}
    require_runtime = validation_profile != "scaffold" or data.get("ready_for_use") == "true"
    evidence_run_id = str(manifest.get("evidence_run_id", ""))
    if require_runtime:
        if not run_id_valid(evidence_run_id):
            add(
                issues,
                "error",
                "runtime_evidence_run_missing",
                manifest_path,
                "candidate/release清单必须记录有效evidence_run_id并绑定研究四件套。",
            )
        else:
            research_history_runs = {
                row[2] for row in version_history_rows(total, []) if len(row) == 5
            }
            if evidence_run_id not in research_history_runs:
                add(
                    issues,
                    "error",
                    "runtime_evidence_run_untracked",
                    manifest_path,
                    "evidence_run_id未出现在综合报告版本谱系中。",
                )
    if require_runtime:
        missing_runtime = sorted(set(expected_runtime) - set(runtime_records))
        if missing_runtime:
            add(issues, "error", "runtime_machine_set_incomplete", manifest_path, "发布校验缺少四件套机器文件：" + ", ".join(missing_runtime))
    loaded_runtime: dict[str, dict[str, object]] = {}
    schema_names = {
        "search-plan.json": "search-plan.schema.json",
        "source-cache.json": "source-cache.schema.json",
        "evidence-manifest.json": "evidence-manifest.schema.json",
        "run-metrics.json": "run-metrics.schema.json",
    }
    for name, expected_schema in expected_runtime.items():
        record = runtime_records.get(name)
        if record is None:
            path = root / "runtime" / name
            if require_runtime and path.exists():
                add(issues, "error", "runtime_machine_untracked", path, f"{name}存在但未由manifest登记；禁止绕过事务写入。")
            continue
        path = root / "runtime" / name
        if not isinstance(record, dict) or record.get("path") != f"runtime/{name}":
            add(issues, "error", "runtime_machine_record_invalid", manifest_path, f"{name}登记路径无效。")
            continue
        if not path.is_file() or path.is_symlink() or record.get("sha256") != sha256_file(path):
            add(issues, "error", "runtime_machine_hash_drift", path, f"{name}缺失、为符号链接或哈希漂移。")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            add(issues, "error", "runtime_machine_json_invalid", path, str(exc))
            continue
        if not isinstance(payload, dict) or payload.get("schema") != expected_schema:
            add(issues, "error", "runtime_machine_schema_invalid", path, f"schema必须为{expected_schema}。")
            continue
        loaded_runtime[name] = payload
        try:
            contract = load_trusted_schema_contract(schema_names[name])
        except TrustedContractError as exc:
            add(issues, "error", "runtime_machine_contract_unavailable", path, str(exc))
            continue
        contract_errors = validate_json_contract(payload, contract)
        if contract_errors:
            add(
                issues,
                "error",
                "runtime_machine_contract_invalid",
                path,
                "; ".join(contract_errors[:8]),
            )
        for field, expected in (
            ("context_id", data.get("context_id", "")),
            ("run_id", evidence_run_id),
            ("business_mode", data.get("business_mode", "")),
        ):
            if payload.get(field) != expected:
                add(issues, "error", "runtime_machine_context_drift", path, f"{field}与当前工作区不一致。")

    plan = loaded_runtime.get("search-plan.json")
    if plan is not None:
        if plan.get("customer_id") != data.get("customer_id", ""):
            add(issues, "error", "search_plan_customer_drift", root / "runtime" / "search-plan.json", "customer_id与当前工作区不一致。")
        plan_modules = plan.get("selected_modules")
        actual_modules = manifest.get("selected_modules")
        if require_runtime and (
            not isinstance(plan_modules, list)
            or not isinstance(actual_modules, list)
            or sorted(map(str, plan_modules)) != sorted(map(str, actual_modules))
        ):
            add(issues, "error", "search_plan_selection_drift", root / "runtime" / "search-plan.json", "selected_modules与manifest不一致。")
        if require_runtime and plan.get("planning_ready") is not True:
            add(issues, "error", "search_plan_not_ready", root / "runtime" / "search-plan.json", "candidate/release提交要求planning_ready=true。")
        strategy = by_type.get("visit_strategy")
        if require_runtime and strategy is not None:
            plan_variant = plan.get("strategy_variant")
            artifact_variant = strategy.frontmatter.get("strategy_variant", "")
            manifest_artifacts = manifest.get("artifacts", {})
            strategy_record = (
                manifest_artifacts.get("visit_strategy")
                if isinstance(manifest_artifacts, dict)
                else None
            )
            manifest_variant = (
                strategy_record.get("strategy_variant")
                if isinstance(strategy_record, dict)
                else None
            )
            if plan_variant != artifact_variant or plan_variant != manifest_variant:
                add(
                    issues,
                    "error",
                    "search_plan_strategy_variant_drift",
                    root / "runtime" / "search-plan.json",
                    "search-plan.strategy_variant与交流策略成果不一致。",
                )
        queries = plan.get("queries") if isinstance(plan.get("queries"), list) else []
        query_ids = {item.get("query_id") for item in queries if isinstance(item, dict)}
        internal_queries = [item for item in queries if isinstance(item, dict) and item.get("channel") == "internal"]
        if plan.get("internal_queries_suppressed") is True and internal_queries:
            add(issues, "error", "suppressed_internal_query_present", root / "runtime" / "search-plan.json", "internal_queries_suppressed=true时不得保留internal query。")
        for batch in plan.get("batches", []) if isinstance(plan.get("batches"), list) else []:
            if not isinstance(batch, dict):
                continue
            missing_query_ids = sorted(set(map(str, batch.get("query_ids", []))) - set(map(str, query_ids)))
            if missing_query_ids:
                add(issues, "error", "search_batch_query_missing", root / "runtime" / "search-plan.json", "batch引用未知query_id：" + ", ".join(missing_query_ids[:5]))
            if plan.get("internal_queries_suppressed") is True and batch.get("channel") == "internal":
                add(issues, "error", "suppressed_internal_batch_present", root / "runtime" / "search-plan.json", "internal_queries_suppressed=true时不得保留internal batch。")
        intake = plan.get("intake_preflight")
        established_intake = manifest.get("intake_preflight")
        if require_runtime and (not isinstance(intake, dict) or not isinstance(established_intake, dict)):
            add(issues, "error", "search_plan_intake_missing", root / "runtime" / "search-plan.json", "candidate/release计划必须绑定当前intake预检收据。")
        elif require_runtime and isinstance(intake, dict) and isinstance(established_intake, dict):
            for key in intake_preflight.PERSISTED_GATE_STABLE_FIELDS:
                if intake.get(key) != established_intake.get(key):
                    add(issues, "error", "search_plan_intake_drift", root / "runtime" / "search-plan.json", f"intake_preflight.{key}与manifest不一致。")
            expiry_text = str(established_intake.get("expires_at", ""))
            try:
                intake_expiry = datetime.fromisoformat(expiry_text.replace("Z", "+00:00"))
            except ValueError:
                intake_expiry = None
            validation_now = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
            if intake_expiry is None or intake_expiry.tzinfo is None or intake_expiry <= validation_now:
                add(
                    issues,
                    "error",
                    "intake_preflight_expired",
                    manifest_path,
                    "candidate/release使用的intake预检收据无效或已过期；必须用同一份intake重新预检并重建候选。",
                )

    evidence_payload = loaded_runtime.get("evidence-manifest.json")
    if evidence_payload is not None and evidence_payload.get("customer_id") != data.get("customer_id", ""):
        add(issues, "error", "runtime_evidence_customer_drift", root / "runtime" / "evidence-manifest.json", "customer_id与当前工作区不一致。")

    connector_audit = (
        evidence_payload.get("connector_audit")
        if isinstance(evidence_payload, dict)
        and isinstance(evidence_payload.get("connector_audit"), dict)
        else {}
    )
    connector_status = str(connector_audit.get("status", ""))
    machine_sources = (
        evidence_payload.get("sources", {})
        if isinstance(evidence_payload, dict)
        and isinstance(evidence_payload.get("sources"), dict)
        else {}
    )
    machine_sensitive = any(
        isinstance(record, dict)
        and (
            record.get("source_level") == "internal"
            or record.get("permission") in {"internal-authorized", "restricted"}
        )
        for record in machine_sources.values()
    )
    signed_internal_required = bool(
        require_runtime
        and (
            "internal" in expected_modules
            or connector_status in {"connected", "no_hits"}
            or machine_sensitive
            or requires_internal_authorization(claims, sources)
        )
    )
    if signed_internal_required:
        authorization = manifest.get("authorization")
        if not isinstance(authorization, dict):
            authorization = {}
        if (
            authorization.get("capability_receipt_verified") is not True
            or connector_audit.get("capability_receipt_verified") is not True
        ):
            add(
                issues,
                "error",
                "capability_receipt_unverified",
                root / "runtime" / "evidence-manifest.json",
                "internal候选/调用必须由宿主签名能力收据验证；本地自报字段不构成授权。",
            )
        immutable_receipt_fields = (
            "authorization_actor_id",
            "capability_receipt_run_id",
            "capability_operation",
            "capability_receipt_issuer",
            "capability_receipt_key_id",
            "capability_receipt_sha256",
            "capability_receipt_expires_at",
        )
        for field in immutable_receipt_fields:
            authorized_value = authorization.get(field)
            audited_value = connector_audit.get(field)
            if not isinstance(authorized_value, str) or not authorized_value.strip():
                add(
                    issues,
                    "error",
                    "capability_receipt_lineage_missing",
                    manifest_path,
                    f"宿主能力收据谱系缺少{field}。",
                )
            elif audited_value != authorized_value:
                add(
                    issues,
                    "error",
                    "capability_receipt_lineage_drift",
                    root / "runtime" / "evidence-manifest.json",
                    f"connector_audit.{field}与manifest授权谱系不一致。",
                )
        evidence_run_id = str(evidence_payload.get("run_id", "")) if isinstance(evidence_payload, dict) else ""
        plan_run_id = str(plan.get("run_id", "")) if isinstance(plan, dict) else ""
        receipt_run_id = str(authorization.get("capability_receipt_run_id", ""))
        if not receipt_run_id or receipt_run_id != evidence_run_id or receipt_run_id != plan_run_id:
            add(
                issues,
                "error",
                "capability_receipt_run_drift",
                manifest_path,
                "宿主能力收据必须同时绑定当前search plan与evidence manifest的run_id。",
            )
        if authorization.get("capability_operation") != "internal_read":
            add(issues, "error", "capability_operation_invalid", manifest_path, "internal能力操作必须精确为internal_read。")
        receipt_sha = str(authorization.get("capability_receipt_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", receipt_sha):
            add(issues, "error", "capability_receipt_digest_invalid", manifest_path, "能力收据SHA-256无效。")
        receipt_expiry = parse_expiry(str(authorization.get("capability_receipt_expires_at", "")))
        if receipt_expiry is None or receipt_expiry <= datetime.now(timezone.utc):
            add(issues, "error", "capability_receipt_expired", manifest_path, "宿主能力收据无效或已过期。")

    metrics = loaded_runtime.get("run-metrics.json")
    if metrics is not None and plan is not None:
        counters = metrics.get("counters")
        if isinstance(counters, dict) and counters.get("queries_planned") != len(plan.get("queries", [])):
            add(issues, "error", "runtime_metrics_plan_drift", root / "runtime" / "run-metrics.json", "queries_planned与search-plan queries数量不一致。")

    if not require_runtime:
        # init/resume is a scaffold transition.  Existing research evidence is
        # historical until a new candidate plan rebinds modules, intake and
        # any run-scoped authorization receipt.
        return

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
        add(issues, "error", "connector_audit_missing", evidence_path, f"连接状态{connector_status}必须有真实调用审计：{exc}")
        return
    audit = evidence.get("connector_audit") if isinstance(evidence, dict) else None
    if not isinstance(audit, dict) or audit.get("status") != connector_status:
        add(issues, "error", "connector_audit_status_drift", evidence_path, "connector_audit.status与内部检索成果不一致。")
        return
    authorization = manifest.get("authorization") if isinstance(manifest.get("authorization"), dict) else {}
    for field in (
        "connector_id", "call_id", "called_at", "tenant_id", "customer_id", "project_id",
        "authorization_owner", "authorization_expires_at", "authorization_purpose", "capability_receipt_id",
    ):
        if not str(audit.get(field) or "").strip():
            add(issues, "error", "connector_audit_field_missing", evidence_path, f"真实调用审计缺少{field}。")
    for field in (
        "tenant_id", "customer_id", "project_id", "connector_id", "authorization_owner",
        "authorization_expires_at", "authorization_purpose", "capability_receipt_id",
    ):
        if str(audit.get(field) or "") != str(authorization.get(field) or ""):
            add(issues, "error", "connector_audit_scope_drift", evidence_path, f"{field}与运行授权不一致。")
    for field in ("authorized_roots", "allowed_dataset_aliases", "allowed_confidentiality"):
        audited_values = audit.get(field)
        authorized_values = authorization.get(field)
        if not isinstance(audited_values, list) or not audited_values:
            add(issues, "error", "connector_audit_field_missing", evidence_path, f"真实调用审计缺少非空{field}。")
        elif not isinstance(authorized_values, list) or sorted(map(str, audited_values)) != sorted(map(str, authorized_values)):
            add(issues, "error", "connector_audit_scope_drift", evidence_path, f"{field}与运行授权不一致。")
    allowed_projects = audit.get("allowed_project_ids")
    authorized_projects = authorization.get("allowed_project_ids")
    if not isinstance(allowed_projects, list) or audit.get("project_id") not in allowed_projects:
        add(issues, "error", "connector_project_not_allowed", evidence_path, "connector_audit.allowed_project_ids必须包含本轮project_id。")
    elif isinstance(authorized_projects, list) and sorted(map(str, allowed_projects)) != sorted(map(str, authorized_projects)):
        add(issues, "error", "connector_allowlist_drift", evidence_path, "调用审计项目白名单与运行授权不一致。")
    if connector_status in {"connected", "no_hits"}:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(audit.get("response_fingerprint") or "")):
            add(issues, "error", "connector_response_content_unbound", evidence_path, "response_fingerprint必须绑定响应内容SHA-256。")
        if audit.get("server_filter_verified") is not True or audit.get("response_scope_verified") is not True:
            add(issues, "error", "connector_scope_unverified", evidence_path, "服务端三重过滤和返回范围必须均经验证。")
    expiry = parse_expiry(str(audit.get("authorization_expires_at") or ""))
    if expiry is None or expiry <= datetime.now(timezone.utc):
        add(issues, "error", "connector_authorization_expired", evidence_path, "连接器调用授权无效或已过期。")


SCHEDULED_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "目标与最小推进动作": ("目标与最小推进动作",),
    "机会资格": ("机会资格", "机会资格与投入建议"),
    "议程": ("议程", "时间化议程与参会分工"),
    "参会分工": ("参会分工", "时间化议程与参会分工"),
    "材料": ("材料", "材料计划", "材料与演示计划"),
    "会后行动": ("会后行动",),
    "CRM/PIMS": ("CRM/PIMS", "CRM/PIMS候选"),
}
ACCOUNT_ACTION_LABELS = {
    "action": "action",
    "action_disposition": "action_disposition",
    "external_interaction": "external_interaction",
    "resource_commitment": "resource_commitment",
    "owner": "owner",
    "due_date": "due_date",
    "dependency": "依赖",
    "completion_criteria": "完成标准",
    "adjust_or_stop_trigger": "调整/停止触发",
    "crm_candidate": "CRM/PIMS候选",
}
ACTION_DISPOSITIONS = {"advance", "adjust", "stop", "archive", "observe", "recheck"}
NO_GO_DISPOSITIONS = {"stop", "archive", "observe", "recheck"}
NO_GO_ADVANCEMENT_RE = re.compile(r"(?:继续|推进|争取|加码|投标|演示|跟进|促成|扩大投入)")
NO_GO_EXTERNAL_ACTION_RE = re.compile(
    r"(?:提交|发送|邀约|邀请|试用|报价|签约|立项|拜访|会谈|会议|交流|沟通|"
    r"产品方案|方案给|推动|推进|争取|促成|加码|投标|演示|跟进|扩大投入)"
)
EXTERNAL_INTERACTION_VALUES = {"none", "customer_contact"}
RESOURCE_COMMITMENT_VALUES = {"none", "proposed", "approved"}
NO_GO_CONTROLLED_ACTIONS = {
    "stop": "停止主动投入",
    "archive": "归档当前机会",
    "observe": "被动观察证据变化",
    "recheck": "内部复核机会资格",
}
NO_GO_ACTION_OUTCOMES = {
    "stop": ("no_go_recorded", "reopen_internal_review"),
    "archive": ("opportunity_archived", "reopen_internal_review"),
    "observe": ("evidence_watch_recorded", "archive_if_unchanged"),
    "recheck": ("qualification_review_recorded", "keep_no_go_if_unresolved"),
}
NO_GO_DEPENDENCY_VALUES = {
    "none",
    "无",
    "无依赖",
    "内部复核",
    "内部证据更新",
    "公开证据变化",
}
NO_GO_EVIDENCE_STATES = {"insufficient_evidence", "conflicted_evidence", "disqualified", "not_applicable"}
NO_GO_STAKEHOLDER_ROLES = {"known_role", "unknown_role", "decision_role_unverified"}
NO_GO_ROLE_STATES = {"verified", "unverified", "conflicted"}
NO_GO_STAGES = {"qualification", "monitoring", "closure"}
NO_GO_INFLUENCE_STATES = {"verified", "unverified", "not_applicable"}
NO_GO_QUALIFICATION_STATES = {"unverified", "insufficient", "disqualified", "not_applicable"}
NO_GO_SCENARIO_VALUES = {
    "基准情景": ("evidence_unchanged", "maintain_no_go", "被动观察证据变化"),
    "上行情景": ("new_verified_evidence", "reopen_internal_review", "内部复核机会资格"),
    "下行情景": ("disqualifying_evidence", "close_opportunity", "归档当前机会"),
}
NO_GO_VERIFICATION_SOURCES = {"internal_evidence", "public_evidence", "none"}
NO_GO_VERIFICATION_SIGNALS = {"keep_no_go", "reopen_internal_review", "archive"}
NO_GO_RISK_CODES = {"evidence_insufficient", "authorization_missing", "resource_limit", "qualification_failed"}
NO_GO_CONSEQUENCE_CODES = {"maintain_no_go", "close_opportunity", "internal_review_required"}
NO_GO_REASON_CODES = {"evidence_insufficient", "qualification_failed", "authorization_missing", "resource_limit"}
NO_GO_STOP_CODES = {"evidence_still_insufficient", "qualification_failed", "authorization_unavailable", "resource_limit_reached"}
NO_GO_TOTAL_DECISION_LABELS = {
    "主体与边界", "当前重点任务", "决策影响者", "项目与采购窗口",
    "主要机会与风险", "最小推进动作", "客户主体", "责任角色", "当前任务",
}
NO_GO_TOTAL_EFFECT_CODES = {
    "maintain_no_go", "internal_review_required", "close_opportunity", "no_external_action",
}
STATUS_GAP_BLOCKER_CODES = {
    "evidence_insufficient",
    "evidence_conflicted",
    "source_unavailable",
    "authorization_missing",
    "qualification_failed",
    "resource_limit",
    "connector_unavailable",
    "review_pending",
    "input_missing",
    "artifact_unavailable",
    "attempted_internal_review",
    "attempted_public_refresh",
    "attempted_connector_retry",
    "attempted_input_request",
    "impact_decision_blocked",
    "impact_evidence_unavailable",
    "impact_delivery_blocked",
    "release_verified_evidence",
    "release_authorization_restored",
    "release_connector_restored",
    "release_review_approved",
    "release_input_received",
}
STATUS_BLOCKED_CODE_PREFIXES = ("attempted_", "impact_", "release_")


def canonical_key_claim_ids(
    value: str,
    current_claim_ids: set[str] | None = None,
    *,
    allow_empty: bool = False,
) -> list[str] | None:
    """Parse the exact claim registry representation used by status rows."""

    if value == "none" or (allow_empty and value == ""):
        return []
    tokens = value.split(", ")
    if (
        not tokens
        or value != ", ".join(tokens)
        or tokens != sorted(set(tokens))
        or any(
            not CLAIM_RE.fullmatch(token)
            or (current_claim_ids is not None and token not in current_claim_ids)
            for token in tokens
        )
    ):
        return None
    return tokens


def canonical_status_tokens(
    value: str,
    current_claim_ids: set[str] | None = None,
) -> list[str] | None:
    """Parse a status cell without accepting prose or ambiguous separators."""

    if value == "none":
        return []
    tokens = value.split(", ")
    if (
        not tokens
        or value != ", ".join(tokens)
        or tokens != sorted(set(tokens))
        or "none" in tokens
    ):
        return None
    if any(
        token not in STATUS_GAP_BLOCKER_CODES
        and not (
            CLAIM_RE.fullmatch(token)
            and (current_claim_ids is None or token in current_claim_ids)
        )
        for token in tokens
    ):
        return None
    return tokens


def status_blocked_recovery_complete(tokens: list[str] | None) -> bool:
    """Keep blocked recovery auditable while retaining the closed-code contract."""

    return bool(
        tokens
        and all(any(token.startswith(prefix) for token in tokens) for prefix in STATUS_BLOCKED_CODE_PREFIXES)
    )


def no_go_action_semantics_valid(
    disposition: str,
    action: str,
    owner: str,
    dependency: str,
    completion_criteria: str,
    trigger: str,
    external_interaction: str,
    resource_commitment: str,
) -> bool:
    """Authorize no-go actions only through closed codes and explicit zero commitments."""

    normalized_action = normalize_evidence_text(action)
    controlled_action = NO_GO_CONTROLLED_ACTIONS.get(disposition)
    normalized_dependency = normalize_evidence_text(dependency)
    combined = " ".join((action, owner, dependency, completion_criteria, trigger))
    return bool(
        controlled_action is not None
        and normalized_action == normalize_evidence_text(controlled_action)
        and stable_owner_cell(owner)
        and external_interaction == "none"
        and resource_commitment == "none"
        and normalized_dependency
        in {normalize_evidence_text(value) for value in NO_GO_DEPENDENCY_VALUES}
        and NO_GO_ACTION_OUTCOMES.get(disposition) == (completion_criteria, trigger)
        and not NO_GO_EXTERNAL_ACTION_RE.search(combined)
        and not NO_GO_ADVANCEMENT_RE.search(combined)
    )


def resolved_section_body(value: str) -> bool:
    visible = re.sub(r"[|#>*_`\-:：\s]", "", value)
    return meaningful_delivery_text(visible, minimum_chars=8)


STRATEGY_NAV_ARTIFACT_BY_PREFIX = {
    "I": "institution_research",
    "L": "leader_research",
    "N": "internal_retrieval",
}
STRATEGY_NAV_LABEL_BY_PREFIX = {
    "I": "机构研究成果",
    "L": "人物研究成果",
    "N": "内部检索成果",
}
SCHEDULED_NAV_USAGE_CODES = {
    "target", "assumption", "agenda", "qualification", "roles",
    "materials", "questions", "risk", "action", "crm",
}
ACCOUNT_NAV_USAGE_CODES = {
    "strategic_question", "judgment_chain", "stakeholder", "qualification",
    "scenario", "action", "verification", "risk", "crm",
}
STRATEGY_GAP_HEADER = [
    "claim_ref", "claim_type_ref", "provenance_ref", "evidence_state",
    "impact_type", "verification_mode", "owner", "due_date",
]


def strategy_navigation_contract_errors(
    strategy: Document,
    sections: Mapping[str, list[str]],
    *,
    usage_codes: set[str],
    by_type: Mapping[str, Document] | None = None,
    claims: Mapping[str, ClaimDefinition] | None = None,
) -> list[str]:
    """Validate evidence navigation as typed local bindings, never as prose."""

    bodies = sections.get("依据导航与缺口", [])
    if not bodies:
        return []
    tables = markdown_table_blocks(bodies[0]) if len(bodies) == 1 else []
    errors: list[str] = []
    if (
        len(bodies) != 1
        or len(tables) != 2
        or tables[0][0] != ["序号", "claim_id", "来源成果", "使用位置"]
        or tables[1][0] != STRATEGY_GAP_HEADER
        or not 1 <= len(tables[0][1]) <= 20
        or not 1 <= len(tables[1][1]) <= 10
    ):
        return ["固定双表表头或行数无效"]

    navigation_rows = tables[0][1]
    seen_navigation: set[tuple[str, str]] = set()
    for index, row in enumerate(navigation_rows, start=1):
        if len(row) != 4 or row[0] != str(index) or not CLAIM_RE.fullmatch(row[1]):
            errors.append(f"导航第{index}行形状/序号/claim_id无效")
            continue
        claim_id = row[1]
        prefix = claim_id.split("-")[1]
        artifact_type = STRATEGY_NAV_ARTIFACT_BY_PREFIX.get(prefix)
        expected_label = STRATEGY_NAV_LABEL_BY_PREFIX.get(prefix)
        linked_artifact = by_type.get(artifact_type) if by_type is not None and artifact_type else None
        link = status_link_parts(row[2])
        expected_target = f"./{linked_artifact.path.name}" if linked_artifact is not None else ""
        if (
            artifact_type is None
            or expected_label is None
            or link is None
            or link[0] != expected_label
            or linked_artifact is None
            or linked_artifact.frontmatter.get("artifact_type") != artifact_type
            or linked_artifact.path.parent != strategy.path.parent
            or not linked_artifact.path.is_file()
            or link[1] != expected_target
        ):
            errors.append(f"{claim_id}来源成果链接未绑定当前实际{expected_label or '研究'}文件")
        if row[3] not in usage_codes:
            errors.append(f"{claim_id}使用位置不是当前策略分支受控代码")
        if claims is not None and claim_id not in claims:
            errors.append(f"{claim_id}不在当前权威claim ledger")
        navigation_key = (claim_id, row[3])
        if navigation_key in seen_navigation:
            errors.append(f"{claim_id}/{row[3]}重复导航")
        seen_navigation.add(navigation_key)

    for index, row in enumerate(tables[1][1], start=1):
        claim_id = row[0] if row else ""
        definition = claims.get(claim_id) if claims is not None else None
        if (
            len(row) != 8
            or any(contains_markdown_link_or_image(cell) for cell in row)
            or not CLAIM_RE.fullmatch(claim_id)
            or row[1] not in {"F", "F2", "A", "H", "R"}
            or row[2] not in {"public", "U", "N"}
            or row[3] not in {"unknown", "conflicted", "stale", "insufficient"}
            or row[4] not in {"decision", "verification", "risk", "resource"}
            or row[5] not in {"internal_review", "public_refresh", "authorized_customer_contact"}
            or not stable_owner_cell(row[6])
            or not date_valid(row[7])
            or (
                claims is not None
                and (
                    definition is None
                    or len(definition.cells) < 3
                    or definition.cells[1] != row[1]
                    or definition.cells[2] != row[2]
                )
            )
        ):
            errors.append(f"缺口第{index}行不是权威claim绑定的固定8列代码记录")
    return errors


def validate_scheduled_strategy_sections(
    strategy: Document,
    issues: list[Issue],
    *,
    by_type: Mapping[str, Document] | None = None,
    claims: Mapping[str, ClaimDefinition] | None = None,
) -> None:
    """Enforce fixed, executable scheduled-visit tables rather than prose shells."""

    global_visible = markdown_without_fenced_code(strategy.body)
    sections = h2_sections(global_visible)
    allowed_sections = {
        "目标与最小推进动作",
        "对象假设与验证",
        "议题与节奏",
        "机会资格",
        "机会资格与投入建议",
        "议程",
        "参会分工",
        "时间化议程与参会分工",
        "材料",
        "材料计划",
        "材料与演示计划",
        "问题清单",
        "红线、异议与承诺边界",
        "会后行动",
        "CRM/PIMS",
        "CRM/PIMS候选",
        "依据导航与缺口",
    }
    missing: list[str] = []
    empty: list[str] = []
    for logical, aliases in SCHEDULED_SECTION_ALIASES.items():
        matched = [body for alias in aliases for body in sections.get(alias, [])]
        if not matched:
            missing.append(logical)
        elif not any(resolved_section_body(body) for body in matched):
            empty.append(logical)
    if missing:
        add(
            issues,
            "error",
            "presales_section_missing",
            strategy.path,
            "scheduled_visit缺少独立二级章节：" + ", ".join(missing),
        )
    if empty:
        add(
            issues,
            "error",
            "presales_section_empty",
            strategy.path,
            "scheduled_visit章节不能只写待补充或空表：" + ", ".join(empty),
        )

    def bodies_for(logical: str) -> list[str]:
        return [
            body
            for alias in SCHEDULED_SECTION_ALIASES[logical]
            for body in sections.get(alias, [])
        ]

    structure_errors: list[str] = []
    unexpected_sections = sorted(set(sections) - allowed_sections)
    if unexpected_sections:
        structure_errors.append("非契约二级章节：" + ", ".join(unexpected_sections))
    hidden_link_sections = sorted(
        section_name
        for section_name, bodies in sections.items()
        if section_name != "依据导航与缺口"
        and any(contains_markdown_link_or_image(body) for body in bodies)
    )
    if hidden_link_sections:
        structure_errors.append(
            "核心/行动章节不得包含Markdown链接或图片：" + ", ".join(hidden_link_sections)
        )
    if re.search(r"(?m)^#{3,6}\s+", global_visible):
        structure_errors.append("scheduled_visit不得新增H3-H6子章节")

    allowed_table_headers = {
        ("项目", "内容", "claim_id"),
        ("假设", "claim_id", "风险", "验证问题"),
        ("顺序", "议题", "进入依据 claim_id", "建议表达", "观察信号"),
        ("维度", "当前判断", "claim_id", "待验证问题"),
        ("时间", "环节/议题", "客户对象", "我方owner", "目标信号"),
        ("参会人/角色", "RACI", "负责内容", "备用安排"),
        ("材料/演示", "用途与展示时点", "owner", "版本/授权", "备用/不展示边界"),
        ("场景", "风险依据 claim_id", "建议回应", "禁止承诺", "升级角色"),
        ("action", "owner", "due_date", "依赖", "完成标准", "CRM/PIMS候选"),
        ("候选类型", "内容", "owner", "due_date", "写回状态"),
        ("序号", "claim_id", "来源成果", "使用位置"),
        tuple(STRATEGY_GAP_HEADER),
    }
    table_header_counts: dict[tuple[str, ...], int] = {}
    for header, _rows in markdown_table_blocks(global_visible):
        signature = tuple(header)
        table_header_counts[signature] = table_header_counts.get(signature, 0) + 1
        if signature not in allowed_table_headers:
            structure_errors.append("非契约表头：" + "/".join(header))
    duplicate_table_headers = sorted(
        "/".join(header)
        for header, count in table_header_counts.items()
        if header in allowed_table_headers and count > 1
    )
    if duplicate_table_headers:
        structure_errors.append("重复契约表：" + ", ".join(duplicate_table_headers))

    allowed_bullet_locations = {
        "目标对象": {"目标与最小推进动作"},
        "建议": {"机会资格", "机会资格与投入建议"},
        "投入强度": {"机会资格", "机会资格与投入建议"},
        "前提与停止条件": {"机会资格", "机会资格与投入建议"},
    }
    for section_name, bodies in sections.items():
        for section_body in bodies:
            for line in section_body.splitlines():
                bullet = re.match(r"^\s*[-*+]\s+([^:：]+)[:：]", line)
                if bullet:
                    label = bullet.group(1).strip()
                    if section_name not in allowed_bullet_locations.get(label, set()):
                        structure_errors.append(f"{section_name}含非契约列表项：{label}")
                elif re.match(r"^\s*[-*+]\s+\S", line):
                    structure_errors.append(f"{section_name}含无标签列表动作")
                if section_name != "问题清单" and re.match(r"^\s*\d+[.)、]\s+\S", line):
                    structure_errors.append(f"{section_name}含非契约编号动作")
                if (
                    line.strip()
                    and not line.lstrip().startswith("|")
                    and bullet is None
                    and not (
                        section_name == "问题清单"
                        and re.match(r"^\s*\d+[.)、]\s+\S", line)
                    )
                ):
                    structure_errors.append(f"{section_name}含非契约自由正文")

    scheduled_preamble = markdown_preamble(global_visible)
    if any(
        line.strip() and not re.match(r"^#(?!#)\s+\S", line.strip())
        for line in scheduled_preamble.splitlines()
    ):
        structure_errors.append("标题区含非契约自由正文")

    structured_conclusion_counts = {
        label: len(re.findall(rf"^\s*-\s*{re.escape(label)}：", global_visible, re.MULTILINE))
        for label in ("建议", "投入强度", "前提与停止条件")
    }
    if any(count != 1 for count in structured_conclusion_counts.values()):
        structure_errors.append("建议/投入强度/前提与停止条件必须全文件唯一")
    scheduled_action_header = ["action", "owner", "due_date", "依赖", "完成标准", "CRM/PIMS候选"]
    scheduled_action_tables = [
        (header, rows)
        for header, rows in markdown_table_blocks(global_visible)
        if header == scheduled_action_header
    ]
    if len(scheduled_action_tables) != 1:
        structure_errors.append("会后action固定表必须全文件唯一")

    optional_table_contracts = {
        "对象假设与验证": (["假设", "claim_id", "风险", "验证问题"], 4),
        "议题与节奏": (["顺序", "议题", "进入依据 claim_id", "建议表达", "观察信号"], 5),
        "红线、异议与承诺边界": (["场景", "风险依据 claim_id", "建议回应", "禁止承诺", "升级角色"], 5),
    }
    for section_name, (expected_header, column_count) in optional_table_contracts.items():
        bodies = sections.get(section_name, [])
        if not bodies:
            continue
        tables = markdown_table_blocks(bodies[0]) if len(bodies) == 1 else []
        if (
            len(bodies) != 1
            or len(tables) != 1
            or tables[0][0] != expected_header
            or not 1 <= len(tables[0][1]) <= 8
            or any(
                len(row) != column_count
                or any(not meaningful_delivery_text(cell, minimum_chars=2) for cell in row)
                for row in tables[0][1]
            )
        ):
            structure_errors.append(section_name + "固定表")

    question_bodies = sections.get("问题清单", [])
    if question_bodies:
        question_tables = markdown_table_blocks(question_bodies[0]) if len(question_bodies) == 1 else []
        questions = (
            re.findall(r"^\s*(\d+)\.\s+(.+)$", question_bodies[0], re.MULTILINE)
            if len(question_bodies) == 1
            else []
        )
        if (
            question_tables
            or [number for number, _question in questions] != ["1", "2", "3"]
            or any(
                not meaningful_delivery_text(question, minimum_chars=8)
                or not re.search(r"[?？]\s*$", question)
                for _number, question in questions
            )
        ):
            structure_errors.append("问题清单必须恰有三个可见问题且不得包含表格或行动列表")

    navigation_bodies = sections.get("依据导航与缺口", [])
    if navigation_bodies:
        navigation_errors = strategy_navigation_contract_errors(
            strategy,
            sections,
            usage_codes=SCHEDULED_NAV_USAGE_CODES,
            by_type=by_type,
            claims=claims,
        )
        if navigation_errors:
            add(
                issues,
                "error",
                "strategy_navigation_contract_invalid",
                strategy.path,
                "scheduled_visit依据导航必须绑定当前实际研究成果，使用位置和缺口必须为受控代码，缺口不得含任何链接或图片："
                + ", ".join(navigation_errors),
            )
            structure_errors.append("依据导航与缺口闭合契约")

    target_bodies = bodies_for("目标与最小推进动作")
    target_tables = markdown_table_blocks(target_bodies[0]) if len(target_bodies) == 1 else []
    target_header, target_rows = target_tables[0] if target_tables else ([], [])
    target_labels = ["主要目标", "最小推进动作", "成功标准"]
    target_map = {row[0]: row for row in target_rows if len(row) == 3}
    if (
        len(target_bodies) != 1
        or len(target_tables) != 1
        or target_header != ["项目", "内容", "claim_id"]
        or [row[0] if row else "" for row in target_rows] != target_labels
        or any(
            label not in target_map
            or not meaningful_delivery_text(target_map[label][1], minimum_chars=6)
            or not CLAIM_RE.fullmatch(target_map[label][2])
            for label in target_labels
        )
        or (
            "主要目标" in target_map
            and normalize_evidence_text(target_map["主要目标"][1])
            != normalize_evidence_text(strategy.frontmatter.get("visit_objective", ""))
        )
        or (
            "最小推进动作" in target_map
            and normalize_evidence_text(target_map["最小推进动作"][1])
            != normalize_evidence_text(strategy.frontmatter.get("minimum_next_step", ""))
        )
    ):
        structure_errors.append("目标与最小推进动作固定表")

    qualification_bodies = bodies_for("机会资格")
    qualification_tables = markdown_table_blocks(qualification_bodies[0]) if len(qualification_bodies) == 1 else []
    qualification_header, qualification_rows = qualification_tables[0] if qualification_tables else ([], [])
    qualification_labels = ["Budget", "Authority", "Need", "Timing/采购时序", "竞争位置"]
    qualification_body = qualification_bodies[0] if len(qualification_bodies) == 1 else ""
    if (
        len(qualification_bodies) != 1
        or len(qualification_tables) != 1
        or qualification_header != ["维度", "当前判断", "claim_id", "待验证问题"]
        or [row[0] if row else "" for row in qualification_rows] != qualification_labels
        or any(
            len(row) != 4
            or not meaningful_delivery_text(row[1], minimum_chars=6)
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3], minimum_chars=6)
            for row in qualification_rows
        )
        or re.search(r"^\s*-\s*建议：\s*(win|conditional_win|monitor|no_go)\s*$", qualification_body, re.MULTILINE) is None
        or re.search(r"^\s*-\s*投入强度：\s*(低|中|高)\s*$", qualification_body, re.MULTILINE) is None
        or (
            (stop_match := re.search(r"^\s*-\s*前提与停止条件：\s*(.+)$", qualification_body, re.MULTILINE)) is None
            or not meaningful_delivery_text(stop_match.group(1), minimum_chars=8)
        )
    ):
        structure_errors.append("机会资格与投入建议固定表/结论")

    agenda_bodies = bodies_for("议程")
    participant_bodies = bodies_for("参会分工")
    combined = sections.get("时间化议程与参会分工", [])
    combined_tables = markdown_table_blocks(combined[0]) if len(combined) == 1 else []
    if combined_tables:
        agenda_table = combined_tables[0]
        participant_table = combined_tables[1] if len(combined_tables) > 1 else ([], [])
        agenda_layout_invalid = bool(
            len(combined) != 1
            or len(combined_tables) != 2
            or any(sections.get(alias) for alias in ("议程",))
            or any(sections.get(alias) for alias in ("参会分工",))
        )
    else:
        agenda_tables = markdown_table_blocks(agenda_bodies[0]) if len(agenda_bodies) == 1 else []
        participant_tables = markdown_table_blocks(participant_bodies[0]) if len(participant_bodies) == 1 else []
        agenda_table = agenda_tables[0] if agenda_tables else ([], [])
        participant_table = participant_tables[0] if participant_tables else ([], [])
        agenda_layout_invalid = bool(
            combined
            or len(agenda_bodies) != 1
            or len(participant_bodies) != 1
            or len(agenda_tables) != 1
            or len(participant_tables) != 1
        )
    agenda_header, agenda_rows = agenda_table
    if (
        agenda_layout_invalid
        or agenda_header != ["时间", "环节/议题", "客户对象", "我方owner", "目标信号"]
        or len(agenda_rows) != 3
        or any(
            len(row) != 5
            or not re.search(r"(?:分钟|最后)", row[0])
            or any(not meaningful_delivery_text(cell, minimum_chars=4) for cell in row[1:])
            or not stable_owner_cell(row[3])
            for row in agenda_rows
        )
    ):
        structure_errors.append("时间化议程固定表")
    participant_header, participant_rows = participant_table
    if (
        agenda_layout_invalid
        or participant_header != ["参会人/角色", "RACI", "负责内容", "备用安排"]
        or not 1 <= len(participant_rows) <= 8
        or any(
            len(row) != 4
            or not stable_owner_cell(row[0])
            or row[1] not in {"R", "A", "C", "I"}
            or not meaningful_delivery_text(row[2], minimum_chars=4)
            or not meaningful_delivery_text(row[3], minimum_chars=4)
            for row in participant_rows
        )
    ):
        structure_errors.append("参会RACI固定表")

    material_bodies = bodies_for("材料")
    material_tables = markdown_table_blocks(material_bodies[0]) if len(material_bodies) == 1 else []
    material_header, material_rows = material_tables[0] if material_tables else ([], [])
    if (
        len(material_bodies) != 1
        or len(material_tables) != 1
        or material_header != ["材料/演示", "用途与展示时点", "owner", "版本/授权", "备用/不展示边界"]
        or not 1 <= len(material_rows) <= 6
        or any(
            len(row) != 5
            or any(not meaningful_delivery_text(cell, minimum_chars=4) for cell in row)
            or not stable_owner_cell(row[2])
            for row in material_rows
        )
    ):
        structure_errors.append("材料与演示固定表")

    action_bodies = bodies_for("会后行动")
    action_tables = markdown_table_blocks(action_bodies[0]) if len(action_bodies) == 1 else []
    action_header, action_rows = action_tables[0] if action_tables else ([], [])
    if (
        len(action_bodies) != 1
        or len(action_tables) != 1
        or action_header != ["action", "owner", "due_date", "依赖", "完成标准", "CRM/PIMS候选"]
        or not 1 <= len(action_rows) <= 2
        or any(
            len(row) != 6
            or not meaningful_delivery_text(row[0], minimum_chars=4)
            or not stable_owner_cell(row[1])
            or not date_valid(row[2])
            or not meaningful_delivery_text(row[3], minimum_chars=4)
            or not meaningful_delivery_text(row[4], minimum_chars=6)
            or row[5] not in {"是", "否"}
            for row in action_rows
        )
        or (
            action_rows
            and normalize_evidence_text(action_rows[0][0])
            != normalize_evidence_text(strategy.frontmatter.get("minimum_next_step", ""))
        )
    ):
        structure_errors.append("会后行动固定表")

    crm_bodies = bodies_for("CRM/PIMS")
    crm_tables = markdown_table_blocks(crm_bodies[0]) if len(crm_bodies) == 1 else []
    crm_header, crm_rows = crm_tables[0] if crm_tables else ([], [])
    if (
        len(crm_bodies) != 1
        or len(crm_tables) != 1
        or crm_header != ["候选类型", "内容", "owner", "due_date", "写回状态"]
        or not 1 <= len(crm_rows) <= 5
        or any(
            len(row) != 5
            or row[0] not in {"action", "verification", "risk", "opportunity"}
            or not meaningful_delivery_text(row[1], minimum_chars=6)
            or not stable_owner_cell(row[2])
            or not date_valid(row[3])
            or row[4] != "candidate_only"
            for row in crm_rows
        )
    ):
        structure_errors.append("CRM/PIMS候选固定表")

    if structure_errors:
        add(
            issues,
            "error",
            "scheduled_strategy_structure_invalid",
            strategy.path,
            "scheduled_visit交付结构或可执行字段无效：" + ", ".join(structure_errors),
        )


def validate_account_action_contract(
    strategy: Document,
    contract: Mapping[str, object],
    issues: list[Issue],
    *,
    by_type: Mapping[str, Document] | None = None,
    claims: Mapping[str, ClaimDefinition] | None = None,
) -> None:
    """Enforce executable account actions, recommendation and stop conditions."""

    if strategy.frontmatter.get("module_status") != "completed":
        return
    global_visible = markdown_without_fenced_code(strategy.body)
    sections = h2_sections(global_visible)
    structure_errors: list[str] = []
    allowed_sections = {
        "战略问题与最小推进动作",
        "判断链与证据边界",
        "利益相关者与决策结构",
        "机会资格与投入建议",
        "情景与触发条件",
        "30/60/90天账户动作",
        "验证计划",
        "风险、承诺边界与停止条件",
        "CRM/PIMS候选",
        "依据导航与缺口",
    }
    unexpected_sections = sorted(set(sections) - allowed_sections)
    if unexpected_sections:
        structure_errors.append("非契约二级章节：" + ", ".join(unexpected_sections))
    if re.search(r"(?m)^#{3,6}\s+", global_visible):
        structure_errors.append("account_planning不得新增H3-H6子章节")

    allowed_table_headers = {
        ("项目", "内容", "claim_id"),
        ("环节", "当前判断", "claim_id", "反证/替代解释", "置信度", "验证方式"),
        ("角色层级", "当前可核实职责", "事项/阶段", "影响方式", "证据 claim_id", "缺口与验证动作"),
        ("维度", "当前判断", "claim_id", "缺口/反证", "下一验证动作"),
        ("情景", "触发信号", "可能影响", "应对动作", "owner", "复核日期"),
        (
            "周期", "action", "action_disposition", "external_interaction", "resource_commitment",
            "owner", "due_date", "依赖", "完成标准", "调整/停止触发", "CRM/PIMS候选",
        ),
        ("待验证主张/假设", "当前状态", "验证问题或动作", "目标对象/来源", "owner", "due_date", "通过/停止信号"),
        ("风险/停止条件", "依据 claim_id", "业务后果", "预防或降级动作", "升级角色"),
        ("候选类型", "内容", "数据属性", "owner", "due_date", "写回状态"),
        ("序号", "claim_id", "来源成果", "使用位置"),
        tuple(STRATEGY_GAP_HEADER),
    }
    header_counts: dict[tuple[str, ...], int] = {}
    for table_header, _table_rows in markdown_table_blocks(global_visible):
        signature = tuple(table_header)
        header_counts[signature] = header_counts.get(signature, 0) + 1
        if signature not in allowed_table_headers:
            structure_errors.append("非契约表头：" + "/".join(table_header))
    duplicate_headers = sorted(
        "/".join(table_header)
        for table_header, count in header_counts.items()
        if table_header in allowed_table_headers and count > 1
    )
    if duplicate_headers:
        structure_errors.append("重复契约表：" + ", ".join(duplicate_headers))

    allowed_bullet_locations = {
        "建议": {"机会资格与投入建议"},
        "投入强度": {"机会资格与投入建议"},
        "建议理由": {"机会资格与投入建议"},
        "停止继续投入的最低条件": {"风险、承诺边界与停止条件"},
        "禁止承诺": {"风险、承诺边界与停止条件"},
    }
    for section_name, bodies in sections.items():
        for section_body in bodies:
            for line in section_body.splitlines():
                bullet = re.match(r"^\s*[-*+]\s+([^:：]+)[:：]", line)
                if bullet:
                    label = bullet.group(1).strip()
                    if section_name not in allowed_bullet_locations.get(label, set()):
                        structure_errors.append(f"{section_name}含非契约列表项：{label}")
                elif re.match(r"^\s*[-*+]\s+\S", line):
                    structure_errors.append(f"{section_name}含无标签列表动作")
                if re.match(r"^\s*\d+[.)、]\s+\S", line):
                    structure_errors.append(f"{section_name}含非契约编号动作")
                if line.strip() and not line.lstrip().startswith("|") and bullet is None:
                    structure_errors.append(f"{section_name}含非契约自由正文")

    account_preamble = markdown_preamble(global_visible)
    if any(
        line.strip() and not re.match(r"^#(?!#)\s+\S", line.strip())
        for line in account_preamble.splitlines()
    ):
        structure_errors.append("标题区含非契约自由正文")

    navigation_bodies = sections.get("依据导航与缺口", [])
    if navigation_bodies:
        navigation_errors = strategy_navigation_contract_errors(
            strategy,
            sections,
            usage_codes=ACCOUNT_NAV_USAGE_CODES,
            by_type=by_type,
            claims=claims,
        )
        if navigation_errors:
            add(
                issues,
                "error",
                "strategy_navigation_contract_invalid",
                strategy.path,
                "account_planning依据导航必须绑定当前实际研究成果，使用位置和缺口必须为受控代码，缺口不得含任何链接或图片："
                + ", ".join(navigation_errors),
            )
            structure_errors.append("依据导航与缺口闭合契约")

    linked_core_sections = sorted(
        section_name
        for section_name, bodies in sections.items()
        if section_name != "依据导航与缺口"
        and any(contains_markdown_link_or_image(body) for body in bodies)
    )
    if linked_core_sections:
        add(
            issues,
            "error",
            "account_strategy_hidden_link_forbidden",
            strategy.path,
            "账户策略的判断、资格、行动与风险章节不得包含Markdown链接或图片；链接只允许出现在依据导航指定列："
            + ", ".join(linked_core_sections),
        )
    action_sections = sections.get("30/60/90天账户动作", [])
    tables = markdown_table_blocks(action_sections[0]) if len(action_sections) == 1 else []
    header, rows = tables[0] if tables else ([], [])
    configured_action_fields = [
        str(field)
        for field in contract.get("required_action_fields", [])
        if isinstance(field, str)
    ]
    configured_no_go_fields = {
        str(field)
        for field in contract.get("required_no_go_fields", [])
        if isinstance(field, str)
    }
    expected_action_fields = list(ACCOUNT_ACTION_LABELS)
    expected_no_go_fields = {
        "recommendation",
        "investment_intensity",
        "recommendation_reason",
        "minimum_stop_condition",
    }
    contract_invalid = (
        configured_action_fields != expected_action_fields
        or configured_no_go_fields != expected_no_go_fields
    )
    if contract_invalid:
        add(
            issues,
            "error",
            "account_strategy_contract_invalid",
            strategy.path,
            "account_planning机器契约缺少固定动作或No-Go字段定义。",
        )
    account_action_header = ["周期"] + [
        ACCOUNT_ACTION_LABELS[field] for field in configured_action_fields if field in ACCOUNT_ACTION_LABELS
    ]
    expected_cycles = ["30天", "60天", "90天"]
    invalid = contract_invalid or len(tables) != 1 or header != account_action_header or len(rows) != 3
    if not invalid:
        invalid = [row[0] if row else "" for row in rows] != expected_cycles
    if not invalid:
        for row in rows:
            if len(row) != len(account_action_header):
                invalid = True
                break
            if (
                not all(operational_cell(row[index]) for index in (1, 7, 8, 9))
                or not stable_owner_cell(row[5])
            ):
                invalid = True
                break
            if (
                row[2] not in ACTION_DISPOSITIONS
                or row[3] not in EXTERNAL_INTERACTION_VALUES
                or row[4] not in RESOURCE_COMMITMENT_VALUES
                or not date_valid(row[6].strip())
                or row[10] not in {"是", "否"}
            ):
                invalid = True
                break
    minimum_next_step = strategy.frontmatter.get("minimum_next_step", "")
    if not invalid and normalize_evidence_text(rows[0][1]) != normalize_evidence_text(minimum_next_step):
        invalid = True
    if invalid:
        add(
            issues,
            "error",
            "account_strategy_action_invalid",
            strategy.path,
            "账户策略必须提供固定11列的30/60/90天动作；每行action、action_disposition、external_interaction、resource_commitment、owner、due_date、依赖、完成标准、调整/停止触发和CRM/PIMS候选均须可执行，30天action须等于minimum_next_step。",
        )

    def first_table(name: str) -> tuple[list[str], list[list[str]]]:
        bodies = sections.get(name, [])
        tables = markdown_table_blocks(bodies[0]) if len(bodies) == 1 else []
        return tables[0] if tables else ([], [])

    def has_exactly_one_table(name: str) -> bool:
        bodies = sections.get(name, [])
        return len(bodies) == 1 and len(markdown_table_blocks(bodies[0])) == 1

    question_header, question_rows = first_table("战略问题与最小推进动作")
    question_labels = ["待决策问题", "经营周期", "最小推进动作", "完成标准"]
    question_map = {row[0]: row for row in question_rows if len(row) == 3}
    if (
        not has_exactly_one_table("战略问题与最小推进动作")
        or question_header != ["项目", "内容", "claim_id"]
        or [row[0] if row else "" for row in question_rows] != question_labels
        or any(
            label not in question_map
            or not meaningful_delivery_text(question_map[label][1], minimum_chars=(2 if label == "经营周期" else 6))
            or not CLAIM_RE.fullmatch(question_map[label][2])
            for label in question_labels
        )
        or (
            "待决策问题" in question_map
            and normalize_evidence_text(question_map["待决策问题"][1])
            != normalize_evidence_text(strategy.frontmatter.get("strategic_question", ""))
        )
        or (
            "经营周期" in question_map
            and normalize_evidence_text(question_map["经营周期"][1])
            != normalize_evidence_text(strategy.frontmatter.get("planning_horizon", ""))
        )
        or (
            "最小推进动作" in question_map
            and normalize_evidence_text(question_map["最小推进动作"][1])
            != normalize_evidence_text(strategy.frontmatter.get("minimum_next_step", ""))
        )
    ):
        structure_errors.append("战略问题与最小推进动作")

    chain_header, chain_rows = first_table("判断链与证据边界")
    chain_labels = ["客户发展或履职阶段", "核心任务或矛盾", "数字化支撑点"]
    if (
        not has_exactly_one_table("判断链与证据边界")
        or chain_header != ["环节", "当前判断", "claim_id", "反证/替代解释", "置信度", "验证方式"]
        or [row[0] if row else "" for row in chain_rows] != chain_labels
        or any(
            len(row) != 6
            or not meaningful_delivery_text(row[1], minimum_chars=6)
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3], minimum_chars=6)
            or row[4] not in {"高", "中", "低"}
            or not meaningful_delivery_text(row[5], minimum_chars=6)
            for row in chain_rows
        )
    ):
        structure_errors.append("判断链与证据边界")

    stakeholder_header, stakeholder_rows = first_table("利益相关者与决策结构")
    if (
        not has_exactly_one_table("利益相关者与决策结构")
        or stakeholder_header != ["角色层级", "当前可核实职责", "事项/阶段", "影响方式", "证据 claim_id", "缺口与验证动作"]
        or not 1 <= len(stakeholder_rows) <= 10
        or any(
            len(row) != 6
            or any(not meaningful_delivery_text(row[index], minimum_chars=4) for index in (0, 1, 2, 3, 5))
            or not CLAIM_RE.fullmatch(row[4])
            for row in stakeholder_rows
        )
    ):
        structure_errors.append("利益相关者与决策结构")

    qualification_table_header, qualification_table_rows = first_table("机会资格与投入建议")
    qualification_labels = ["Budget", "Authority", "Need", "Timing/采购时序", "竞争位置"]
    if (
        not has_exactly_one_table("机会资格与投入建议")
        or qualification_table_header != ["维度", "当前判断", "claim_id", "缺口/反证", "下一验证动作"]
        or [row[0] if row else "" for row in qualification_table_rows] != qualification_labels
        or any(
            len(row) != 5
            or not meaningful_delivery_text(row[1], minimum_chars=6)
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3], minimum_chars=6)
            or not meaningful_delivery_text(row[4], minimum_chars=6)
            for row in qualification_table_rows
        )
    ):
        structure_errors.append("机会资格固定表")

    scenario_header, scenario_rows = first_table("情景与触发条件")
    if (
        not has_exactly_one_table("情景与触发条件")
        or scenario_header != ["情景", "触发信号", "可能影响", "应对动作", "owner", "复核日期"]
        or [row[0] if row else "" for row in scenario_rows] != ["基准情景", "上行情景", "下行情景"]
        or any(
            len(row) != 6
            or any(not meaningful_delivery_text(row[index], minimum_chars=4) for index in (1, 2, 3))
            or not stable_owner_cell(row[4])
            or not date_valid(row[5])
            for row in scenario_rows
        )
    ):
        structure_errors.append("三情景与触发条件")

    verification_header, verification_rows = first_table("验证计划")
    if (
        not has_exactly_one_table("验证计划")
        or verification_header != ["待验证主张/假设", "当前状态", "验证问题或动作", "目标对象/来源", "owner", "due_date", "通过/停止信号"]
        or not 1 <= len(verification_rows) <= 10
        or any(
            len(row) != 7
            or not meaningful_delivery_text(row[0], minimum_chars=4)
            or row[1] not in {"conflicted", "unknown", "stale", "H"}
            or not meaningful_delivery_text(row[2], minimum_chars=6)
            or not meaningful_delivery_text(row[3], minimum_chars=4)
            or not stable_owner_cell(row[4])
            or not date_valid(row[5])
            or not meaningful_delivery_text(row[6], minimum_chars=6)
            for row in verification_rows
        )
    ):
        structure_errors.append("验证计划")

    risk_header, risk_rows = first_table("风险、承诺边界与停止条件")
    if (
        not has_exactly_one_table("风险、承诺边界与停止条件")
        or risk_header != ["风险/停止条件", "依据 claim_id", "业务后果", "预防或降级动作", "升级角色"]
        or not 1 <= len(risk_rows) <= 8
        or any(
            len(row) != 5
            or not meaningful_delivery_text(row[0], minimum_chars=6)
            or not CLAIM_RE.fullmatch(row[1])
            or not meaningful_delivery_text(row[2], minimum_chars=6)
            or not meaningful_delivery_text(row[3], minimum_chars=6)
            or not stable_owner_cell(row[4])
            for row in risk_rows
        )
    ):
        structure_errors.append("风险与停止条件固定表")

    crm_header, crm_rows = first_table("CRM/PIMS候选")
    if (
        not has_exactly_one_table("CRM/PIMS候选")
        or crm_header != ["候选类型", "内容", "数据属性", "owner", "due_date", "写回状态"]
        or not 1 <= len(crm_rows) <= 8
        or any(
            len(row) != 6
            or row[0] not in {"action", "verification", "risk", "opportunity"}
            or not meaningful_delivery_text(row[1], minimum_chars=6)
            or row[2] not in {"事实", "假设", "建议", "事实缺口", "风险"}
            or not stable_owner_cell(row[3])
            or not date_valid(row[4])
            or row[5] != "candidate_only"
            for row in crm_rows
        )
    ):
        structure_errors.append("CRM/PIMS候选")

    if structure_errors:
        add(
            issues,
            "error",
            "account_strategy_structure_invalid",
            strategy.path,
            "account_planning核心结构或可执行字段无效：" + ", ".join(structure_errors),
        )

    qualification = sections.get("机会资格与投入建议", [])
    qualification_body = qualification[0] if len(qualification) == 1 else ""
    recommendation_match = re.search(
        r"^\s*-\s*建议：\s*(win|conditional_win|monitor|no_go)\s*$",
        qualification_body,
        flags=re.MULTILINE,
    )
    investment_match = re.search(
        r"^\s*-\s*投入强度：\s*(低|中|高)\s*$",
        qualification_body,
        flags=re.MULTILINE,
    )
    reason_match = re.search(
        r"^\s*-\s*建议理由：\s*(.+)$",
        qualification_body,
        flags=re.MULTILINE,
    )
    stop_sections = sections.get("风险、承诺边界与停止条件", [])
    stop_body = stop_sections[0] if len(stop_sections) == 1 else ""
    stop_match = re.search(
        r"^\s*-\s*停止继续投入的最低条件：\s*(.+)$",
        stop_body,
        flags=re.MULTILINE,
    )
    if (
        recommendation_match is None
        or investment_match is None
        or reason_match is None
        or not meaningful_delivery_text(reason_match.group(1), minimum_chars=8)
        or stop_match is None
        or not meaningful_delivery_text(stop_match.group(1), minimum_chars=8)
    ):
        add(
            issues,
            "error",
            "account_strategy_no_go_fields_invalid",
            strategy.path,
            "账户策略必须结构化给出win/conditional_win/monitor/no_go建议、投入强度、具体建议理由和可观察的最低停止条件。",
        )
    elif recommendation_match.group(1) == "no_go" and rows:
        conflicting = [
            row[0]
            for row in rows
            if len(row) != 11
            or row[2] not in NO_GO_DISPOSITIONS
            or not no_go_action_semantics_valid(
                row[2], row[1], row[5], row[7], row[8], row[9], row[3], row[4]
            )
        ]
        controlled_actions = {
            normalize_evidence_text(value) for value in NO_GO_CONTROLLED_ACTIONS.values()
        }
        question_conflicts = [
            label
            for label, row in question_map.items()
            if label == "完成标准" and (len(row) != 3 or row[1] != "no_go_decision_recorded")
        ]
        chain_conflicts = [
            row[0] if row else "未知环节"
            for row in chain_rows
            if len(row) != 6
            or row[1] not in NO_GO_EVIDENCE_STATES
            or row[3] not in NO_GO_EVIDENCE_STATES
            or normalize_evidence_text(row[5]) not in controlled_actions
        ]
        stakeholder_conflicts = [
            row[0] if row else "未知角色"
            for row in stakeholder_rows
            if len(row) != 6
            or row[0] not in NO_GO_STAKEHOLDER_ROLES
            or row[1] not in NO_GO_ROLE_STATES
            or row[2] not in NO_GO_STAGES
            or row[3] not in NO_GO_INFLUENCE_STATES
            or normalize_evidence_text(row[5]) not in controlled_actions
        ]
        qualification_conflicts = [
            row[0] if row else "未知维度"
            for row in qualification_table_rows
            if len(row) != 5
            or row[1] not in NO_GO_QUALIFICATION_STATES
            or row[3] not in NO_GO_QUALIFICATION_STATES
            or normalize_evidence_text(row[4]) not in controlled_actions
        ]
        scenario_conflicts = [
            row[0]
            for row in scenario_rows
            if len(row) != 6
            or NO_GO_SCENARIO_VALUES.get(row[0]) != (row[1], row[2], row[3])
            or not stable_owner_cell(row[4])
        ]
        verification_conflicts = [
            row[0] if row else "未知主张"
            for row in verification_rows
            if len(row) != 7
            or not CLAIM_RE.fullmatch(row[0])
            or normalize_evidence_text(row[2]) not in controlled_actions
            or row[3] not in NO_GO_VERIFICATION_SOURCES
            or not stable_owner_cell(row[4])
            or row[6] not in NO_GO_VERIFICATION_SIGNALS
        ]
        risk_conflicts = [
            row[0] if row else "未知风险"
            for row in risk_rows
            if len(row) != 5
            or row[0] not in NO_GO_RISK_CODES
            or row[2] not in NO_GO_CONSEQUENCE_CODES
            or normalize_evidence_text(row[3]) not in controlled_actions
            or not stable_owner_cell(row[4])
        ]
        crm_conflicts = [
            row[0] if row else "未知候选"
            for row in crm_rows
            if len(row) != 6
            or row[0] not in {"action", "verification"}
            or not stable_owner_cell(row[3])
            or normalize_evidence_text(row[1]) not in controlled_actions
            or row[2] != ("建议" if row[0] == "action" else "事实缺口")
        ]
        no_go_bullet_conflicts: list[str] = []
        if investment_match.group(1) != "低":
            no_go_bullet_conflicts.append("投入强度")
        if reason_match.group(1) not in NO_GO_REASON_CODES:
            no_go_bullet_conflicts.append("建议理由")
        if stop_match.group(1) not in NO_GO_STOP_CODES:
            no_go_bullet_conflicts.append("最低停止条件")
        forbidden_matches = re.findall(
            r"^\s*-\s*禁止承诺：\s*(.+)$", stop_body, re.MULTILINE
        )
        if forbidden_matches != ["all_unapproved_commitments"]:
            no_go_bullet_conflicts.append("禁止承诺")
        if navigation_bodies:
            no_go_bullet_conflicts.append("依据导航与缺口")

        uncontracted_sections: list[str] = []
        for section_name, bodies in sections.items():
            for body in bodies:
                for line in body.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("|"):
                        continue
                    if re.match(r"^[-*+]\s+[^:：]+[:：]\s*\S", stripped):
                        continue
                    uncontracted_sections.append(section_name)
                    break
        preamble = global_visible.split("\n##", 1)[0]
        if any(
            line.strip() and not re.match(r"^#(?!#)\s+\S", line.strip())
            for line in preamble.splitlines()
        ):
            uncontracted_sections.append("标题前言")
        for prefix, values in (
            ("战略问题:", question_conflicts),
            ("判断链:", chain_conflicts),
            ("利益相关者:", stakeholder_conflicts),
            ("资格:", qualification_conflicts),
            ("情景:", scenario_conflicts),
            ("验证:", verification_conflicts),
            ("风险:", risk_conflicts),
            ("CRM:", crm_conflicts),
            ("字段:", no_go_bullet_conflicts),
            ("自由文本:", sorted(set(uncontracted_sections))),
        ):
            conflicting.extend(prefix + value for value in values)
        if conflicting:
            add(
                issues,
                "error",
                "account_strategy_no_go_conflict",
                strategy.path,
                "建议为no_go时必须使用闭合代码契约：所有动作、结果、情景、验证、风险、CRM及理由/停止条件均使用模板枚举，owner使用登记我方角色；不得保留自由正文、导航缺口或任何对客推进与资源承诺：" + ", ".join(conflicting),
            )


def validate_comprehensive_delivery_contract(
    total: Document,
    strategy: Document | None,
    issues: list[Issue],
    *,
    claims: Mapping[str, ClaimDefinition] | None = None,
) -> None:
    """Enforce the minimum decision-ready total for standard and strategic packs."""

    if (
        total.frontmatter.get("module_status") != "completed"
        or total.frontmatter.get("business_mode") not in {"standard_visit", "strategic_account"}
    ):
        return
    validate_account_comprehensive_contract(total, set(), set(), issues, claims=claims)
    sections = h2_sections(markdown_without_fenced_code(total.body))
    required_sections = (
        "决策摘要",
        "综合判断链",
        "G-C-P 推演",
        "机会资格与投入建议",
        "执行与下一步",
    )
    linked_core_sections = sorted(
        name
        for name in required_sections
        if any(contains_markdown_link_or_image(body) for body in sections.get(name, []))
    )
    if linked_core_sections:
        add(
            issues,
            "error",
            "comprehensive_hidden_link_forbidden",
            total.path,
            "综合报告核心判断、资格与行动章节不得包含Markdown链接或图片；关键内容必须直接可见："
            + ", ".join(linked_core_sections),
        )
    missing = [name for name in required_sections if len(sections.get(name, [])) != 1]
    if missing:
        add(
            issues,
            "error",
            "comprehensive_section_missing",
            total.path,
            "标准拜访包/战略客户包综合报告缺少唯一核心章节：" + ", ".join(missing),
        )

    def first_table(name: str) -> tuple[list[str], list[list[str]]]:
        bodies = sections.get(name, [])
        tables = markdown_table_blocks(bodies[0]) if len(bodies) == 1 else []
        return tables[0] if tables else ([], [])

    def has_exactly_one_table(name: str) -> bool:
        bodies = sections.get(name, [])
        return len(bodies) == 1 and len(markdown_table_blocks(bodies[0])) == 1

    decision_header, decision_rows = first_table("决策摘要")
    expected_decision_header = ["核心问题", "当前结论", "claim_id", "对业务决策的意义"]
    decision_invalid = (
        not has_exactly_one_table("决策摘要")
        or decision_header != expected_decision_header
        or not 3 <= len(decision_rows) <= 6
        or any(
            len(row) != 4
            or not meaningful_delivery_text(row[0])
            or not meaningful_delivery_text(row[1])
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3])
            for row in decision_rows
        )
    )
    if decision_invalid:
        add(issues, "error", "comprehensive_decision_summary_invalid", total.path, "决策摘要必须使用固定4列表，提供3—6条有claim_id支撑且有业务意义的结论。")

    chain_header, chain_rows = first_table("综合判断链")
    expected_chain_header = ["环节", "判断", "claim_id", "反证/局限", "置信度", "验证问题或动作"]
    expected_chain_labels = ["发展阶段", "核心矛盾", "决策者关注", "信息化支撑", "最小推进动作"]
    chain_invalid = (
        not has_exactly_one_table("综合判断链")
        or chain_header != expected_chain_header
        or [row[0] if row else "" for row in chain_rows] != expected_chain_labels
        or any(
            len(row) != 6
            or not meaningful_delivery_text(row[1])
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3])
            or row[4] not in {"高", "中", "低"}
            or not meaningful_delivery_text(row[5])
            for row in chain_rows
        )
    )
    if chain_invalid:
        add(issues, "error", "comprehensive_judgment_chain_invalid", total.path, "综合判断链必须按固定5个环节填写判断、claim_id、反证、置信度和验证动作。")

    gcp_header, gcp_rows = first_table("G-C-P 推演")
    expected_gcp_header = ["模块", "结论", "claim_id", "边界", "置信度"]
    expected_gcp_labels = ["G：目标任务", "C：承接能力", "P：政策与项目风险"]
    gcp_invalid = (
        not has_exactly_one_table("G-C-P 推演")
        or gcp_header != expected_gcp_header
        or [row[0] if row else "" for row in gcp_rows] != expected_gcp_labels
        or any(
            len(row) != 5
            or not meaningful_delivery_text(row[1], minimum_chars=6)
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3], minimum_chars=6)
            or row[4] not in {"高", "中", "低"}
            for row in gcp_rows
        )
    )
    if gcp_invalid:
        add(issues, "error", "comprehensive_gcp_invalid", total.path, "G-C-P推演必须按G目标任务、C承接能力、P政策与项目风险三行填写结论、claim_id、边界和置信度。")

    qualification_header, qualification_rows = first_table("机会资格与投入建议")
    expected_qualification_header = ["维度", "当前判断", "claim_id", "缺口/验证问题"]
    expected_qualification_labels = ["Budget", "Authority", "Need", "Timing/采购时序", "竞争位置"]
    qualification_invalid = (
        not has_exactly_one_table("机会资格与投入建议")
        or qualification_header != expected_qualification_header
        or [row[0] if row else "" for row in qualification_rows] != expected_qualification_labels
        or any(
            len(row) != 4
            or not meaningful_delivery_text(row[1])
            or not CLAIM_RE.fullmatch(row[2])
            or not meaningful_delivery_text(row[3])
            for row in qualification_rows
        )
    )
    qualification_body = sections.get("机会资格与投入建议", [""])[0]
    global_visible = markdown_without_fenced_code(total.body)
    global_conclusion_counts = {
        label: len(re.findall(rf"^\s*-\s*{re.escape(label)}：", global_visible, re.MULTILINE))
        for label in ("建议", "投入强度", "继续投入的前提/停止条件")
    }
    recommendation = re.search(r"^\s*-\s*建议：\s*(win|conditional_win|monitor|no_go)\s*$", qualification_body, re.MULTILINE)
    investment = re.search(r"^\s*-\s*投入强度：\s*(低|中|高)(?:；\s*依据：\s*(.+))?\s*$", qualification_body, re.MULTILINE)
    stop_condition = re.search(r"^\s*-\s*继续投入的前提/停止条件：\s*(.+)$", qualification_body, re.MULTILINE)
    strategy_recommendation = None
    strategy_summary = strategy_delivery_summary(strategy) if strategy is not None else None
    if strategy is not None:
        strategy_sections = h2_sections(markdown_without_fenced_code(strategy.body))
        strategy_qualification = strategy_sections.get("机会资格与投入建议", [])
        if len(strategy_qualification) != 1:
            strategy_qualification = strategy_sections.get("机会资格", [])
        if len(strategy_qualification) == 1:
            strategy_recommendation = re.search(
                r"^\s*-\s*建议：\s*(win|conditional_win|monitor|no_go)\s*$",
                strategy_qualification[0],
                re.MULTILINE,
            )
    if (
        qualification_invalid
        or recommendation is None
        or investment is None
        or not meaningful_delivery_text(investment.group(2) or "", minimum_chars=6)
        or stop_condition is None
        or not meaningful_delivery_text(stop_condition.group(1), minimum_chars=8)
        or strategy_recommendation is None
        or recommendation.group(1) != strategy_recommendation.group(1)
        or strategy_summary is None
        or recommendation.group(1) != strategy_summary.get("recommendation")
        or investment.group(1) != strategy_summary.get("investment_intensity")
        or any(count != 1 for count in global_conclusion_counts.values())
    ):
        add(issues, "error", "comprehensive_qualification_invalid", total.path, "机会资格必须完整填写BANT、采购时序、竞争位置、建议、投入强度与依据、继续/停止条件。")

    action_header, action_rows = first_table("执行与下一步")
    expected_action_header = ["action", "action_disposition", "external_interaction", "resource_commitment", "owner", "due_date", "依赖", "完成标准", "继续/调整/no-go条件", "CRM/PIMS候选"]
    action_invalid = (
        not has_exactly_one_table("执行与下一步")
        or action_header != expected_action_header
        or len(action_rows) != 1
    )
    if not action_invalid:
        row = action_rows[0]
        action_invalid = bool(
            len(row) != 10
            or not operational_cell(row[0])
            or row[1] not in ACTION_DISPOSITIONS
            or row[2] not in EXTERNAL_INTERACTION_VALUES
            or row[3] not in RESOURCE_COMMITMENT_VALUES
            or not stable_owner_cell(row[4])
            or not date_valid(row[5])
            or not meaningful_delivery_text(row[6])
            or not meaningful_delivery_text(row[7])
            or not meaningful_delivery_text(row[8])
            or row[9] not in {"是", "否"}
        )
        if not action_invalid and strategy is not None:
            action_invalid = bool(
                normalize_evidence_text(row[0])
                != normalize_evidence_text(strategy.frontmatter.get("minimum_next_step", ""))
                or strategy_summary is None
                or normalize_evidence_text(row[0]).rstrip("。.!！")
                != strategy_summary.get("primary_action")
                or normalize_evidence_text(row[4]) != strategy_summary.get("owner")
                or row[5].strip() != strategy_summary.get("due_date")
            )
    if action_invalid:
        add(issues, "error", "comprehensive_action_invalid", total.path, "执行与下一步必须恰有一个固定10列的可执行动作，且action、owner、due_date须与策略决策五元组一致。")
    if recommendation is not None and recommendation.group(1) == "no_go" and action_rows:
        row = action_rows[0]
        if len(row) != 10 or row[1] not in NO_GO_DISPOSITIONS or not no_go_action_semantics_valid(
            row[1], row[0], row[4], row[6], row[7], row[8], row[2], row[3]
        ):
            add(issues, "error", "comprehensive_no_go_conflict", total.path, "综合报告建议为no_go时只能停止、归档、观察或复核，且不得同时安排继续推进类动作。")
        no_go_conflicts: list[str] = []
        controlled_actions = {
            normalize_evidence_text(value) for value in NO_GO_CONTROLLED_ACTIONS.values()
        }
        if (
            investment is None
            or investment.group(1) != "低"
            or investment.group(2) not in NO_GO_REASON_CODES
        ):
            no_go_conflicts.append("投入强度/理由")
        if stop_condition is None or stop_condition.group(1) not in NO_GO_STOP_CODES:
            no_go_conflicts.append("停止条件")
        if any(
            len(item) != 4
            or item[0] not in NO_GO_TOTAL_DECISION_LABELS
            or (
                normalize_evidence_text(item[1]) not in controlled_actions
                if item[0] == "最小推进动作"
                else item[1] not in NO_GO_EVIDENCE_STATES | {"verified"}
            )
            or not CLAIM_RE.fullmatch(item[2])
            or item[3] not in NO_GO_TOTAL_EFFECT_CODES
            for item in decision_rows
        ):
            no_go_conflicts.append("决策摘要")
        if any(
            len(item) != 6
            or item[1] not in NO_GO_EVIDENCE_STATES
            or not CLAIM_RE.fullmatch(item[2])
            or item[3] not in NO_GO_EVIDENCE_STATES
            or normalize_evidence_text(item[5]) not in controlled_actions
            for item in chain_rows
        ):
            no_go_conflicts.append("综合判断链")
        if any(
            len(item) != 5
            or item[1] not in NO_GO_EVIDENCE_STATES
            or not CLAIM_RE.fullmatch(item[2])
            or item[3] not in NO_GO_EVIDENCE_STATES
            for item in gcp_rows
        ):
            no_go_conflicts.append("G-C-P")
        if any(
            len(item) != 4
            or item[1] not in NO_GO_QUALIFICATION_STATES
            or not CLAIM_RE.fullmatch(item[2])
            or item[3] not in NO_GO_QUALIFICATION_STATES
            for item in qualification_rows
        ):
            no_go_conflicts.append("机会资格")

        strategy_action_rows: list[list[str]] = []
        if strategy is not None:
            strategy_sections = h2_sections(markdown_without_fenced_code(strategy.body))
            strategy_action_bodies = strategy_sections.get("30/60/90天账户动作", [])
            strategy_action_tables = (
                markdown_table_blocks(strategy_action_bodies[0])
                if len(strategy_action_bodies) == 1
                else []
            )
            if strategy_action_tables:
                strategy_action_rows = strategy_action_tables[0][1]
        if not strategy_action_rows or len(strategy_action_rows[0]) != 11 or row != strategy_action_rows[0][1:]:
            no_go_conflicts.append("策略/综合动作未逐字段绑定")

        finding_bodies = sections.get("高价值发现", [])
        if finding_bodies:
            finding_tables = markdown_table_blocks(finding_bodies[0]) if len(finding_bodies) == 1 else []
            if not finding_tables or any(
                len(item) != 8 or item[2] not in {"F", "F2"}
                for item in finding_tables[0][1]
            ):
                no_go_conflicts.append("高价值发现")
        gap_bodies = sections.get("关键缺口与验证计划", [])
        if gap_bodies:
            gap_tables = markdown_table_blocks(gap_bodies[0]) if len(gap_bodies) == 1 else []
            if not gap_tables or any(
                len(item) != 8 or item[5] not in {"internal_review", "public_refresh"}
                for item in gap_tables[0][1]
            ):
                no_go_conflicts.append("关键缺口")
        if sections.get("主张与来源导航"):
            no_go_conflicts.append("主张与来源导航")
        if no_go_conflicts:
            add(
                issues,
                "error",
                "comprehensive_no_go_contract_invalid",
                total.path,
                "综合报告为no_go时，判断、资格、影响、动作、发现和验证必须使用闭合代码并与账户策略首行动作逐字段一致："
                + ", ".join(sorted(set(no_go_conflicts))),
            )


def validate_strategy_delivery_separation(
    strategy: Document,
    issues: list[Issue],
) -> None:
    """Keep governance workpapers out of the formal strategy body."""

    visible = markdown_without_fenced_code(strategy.body)
    headings = {
        re.sub(r"^\d+(?:\.\d+)*[.)]?\s+", "", match.group(1).strip())
        for match in re.finditer(r"^#{2,6}\s+(.+?)\s*$", visible, re.MULTILINE)
    }
    forbidden = sorted(headings & STRATEGY_AUDIT_HEADINGS)
    if forbidden:
        add(
            issues,
            "error",
            "strategy_audit_heading_forbidden",
            strategy.path,
            "交流策略是正式业务交付，正文不得混入综合报告的状态、审核、异常、刷新或版本审计章节："
            + ", ".join(forbidden),
        )


def validate_recommendation_template_route(
    total: Document,
    strategy: Document,
    contract: Mapping[str, object],
    profiles: Mapping[str, object],
    issues: list[Issue],
) -> None:
    """Resolve and enforce the recommendation-specific account template route."""

    if strategy.frontmatter.get("strategy_variant") != "account_planning":
        return
    # Init/resume intentionally keeps the ordinary account scaffold until a
    # completed candidate has a structured recommendation to route on.
    if strategy.frontmatter.get("module_status") != "completed":
        return
    qualification = h2_sections(markdown_without_fenced_code(strategy.body)).get(
        "机会资格与投入建议",
        [],
    )
    raw_recommendations = (
        re.findall(r"^\s*-\s*建议：\s*(.+?)\s*$", qualification[0], re.MULTILINE)
        if len(qualification) == 1
        else []
    )
    if len(raw_recommendations) != 1:
        add(
            issues,
            "error",
            "recommendation_template_route_invalid",
            strategy.path,
            "账户策略必须恰有一个结构化建议，才能确定性选择正式策略与综合审计模板。",
        )
        return
    recommendation = raw_recommendations[0].strip()
    try:
        selected_pair = recommendation_template_pair(
            total.frontmatter.get("business_mode", ""),
            "account_planning",
            recommendation,
            profiles=profiles,
        )
    except ValueError as exc:
        add(
            issues,
            "error",
            "recommendation_template_route_invalid",
            strategy.path,
            "账户策略模板选择失败并已关闭：" + str(exc),
        )
        return
    if recommendation != "no_go":
        return

    required_strategy = {
        str(section).strip()
        for section in contract.get("required_sections", [])
        if isinstance(section, str) and section.strip()
    }
    strategy_sections = h2_sections(markdown_without_fenced_code(strategy.body))
    strategy_missing = sorted(required_strategy - set(strategy_sections))
    strategy_extra = sorted(set(strategy_sections) - required_strategy)
    strategy_repeated = sorted(
        heading for heading, bodies in strategy_sections.items() if len(bodies) != 1
    )

    total_sections = h2_sections(markdown_without_fenced_code(total.body))
    allowed_total = NO_GO_TOTAL_REQUIRED_SECTIONS | NO_GO_TOTAL_OPTIONAL_SECTIONS
    total_missing = sorted(NO_GO_TOTAL_REQUIRED_SECTIONS - set(total_sections))
    total_extra = sorted(set(total_sections) - allowed_total)
    total_repeated = sorted(
        heading for heading, bodies in total_sections.items() if len(bodies) != 1
    )
    conflicts: list[str] = []
    if strategy_missing:
        conflicts.append("strategy缺少=" + ",".join(strategy_missing))
    if strategy_extra:
        conflicts.append("strategy多出=" + ",".join(strategy_extra))
    if strategy_repeated:
        conflicts.append("strategy重复=" + ",".join(strategy_repeated))
    if total_missing:
        conflicts.append("comprehensive缺少=" + ",".join(total_missing))
    if total_extra:
        conflicts.append("comprehensive多出=" + ",".join(total_extra))
    if total_repeated:
        conflicts.append("comprehensive重复=" + ",".join(total_repeated))
    if conflicts:
        add(
            issues,
            "error",
            "no_go_template_route_mismatch",
            strategy.path,
            "no_go必须采用确定性选择的专用策略/审计模板结构"
            f"（{selected_pair['visit_strategy']}；{selected_pair['comprehensive_report']}）："
            + "; ".join(conflicts),
        )


def validate_account_comprehensive_contract(
    total: Document,
    forbidden_heading_terms: set[str],
    forbidden_body_labels: set[str],
    issues: list[Issue],
    *,
    claims: Mapping[str, ClaimDefinition] | None = None,
) -> None:
    """Enforce the comprehensive-report allowlist and prevent shadow execution plans."""

    visible = markdown_without_fenced_code(total.body)
    minute_pattern = r"(?:\b\d+\s*[-–—]\s*\d+\s*分钟|(?:前|随后|最后)?[一二三四五六七八九十]+分钟)"
    headings = h2_sections(visible)
    allowed_sections = {
        "决策摘要",
        "任务上下文与成果状态",
        "综合判断链",
        "G-C-P 推演",
        "机会资格与投入建议",
        "执行与下一步",
        "高价值发现",
        "异常审核队列",
        "关键缺口与验证计划",
        "主张与来源导航",
        "刷新结果记录",
        "版本与同步记录",
    }
    bad_headings = sorted(
        heading
        for heading in headings
        if heading not in allowed_sections
        or any(term in heading for term in forbidden_heading_terms)
    )
    bad_labels: set[str] = set()
    allowed_subheading_parents = {
        "本次RACI与审核SLA": "任务上下文与成果状态",
    }
    current_h2 = ""
    current_h3 = ""
    line_locations: list[tuple[str, str, str]] = []
    for line in visible.splitlines():
        h2_match = re.match(r"^##(?!#)\s+(.+?)\s*$", line)
        if h2_match:
            current_h2 = re.sub(
                r"^\d+(?:\.\d+)*[.)]?\s+", "", h2_match.group(1).strip()
            )
            current_h3 = ""
        h3_match = re.match(r"^(#{3,6})\s+(.+?)\s*$", line)
        if h3_match:
            current_h3 = re.sub(
                r"^\d+(?:\.\d+)*[.)]?\s+", "", h3_match.group(2).strip()
            )
            if (
                h3_match.group(1) != "###"
                or allowed_subheading_parents.get(current_h3) != current_h2
            ):
                bad_labels.add("非契约子章节或父章节：" + current_h3)
        line_locations.append((line, current_h2, current_h3))

    allowed_table_headers = {
        ("核心问题", "当前结论", "claim_id", "对业务决策的意义"),
        (
            "模块", "selected_in_run", "run_action", "module_status", "review_status",
            "connector_status", "freshness_status", "content_version", "latest_run_id",
            "updated_at", "summary_sync_status", "key_claim_ids", "downstream_invalidation",
            "gaps/blockers", "成果链接",
        ),
        ("角色", "姓名（稳定角色/账号）", "本次责任", "截止时间/状态"),
        ("环节", "判断", "claim_id", "反证/局限", "置信度", "验证问题或动作"),
        ("模块", "结论", "claim_id", "边界", "置信度"),
        ("维度", "当前判断", "claim_id", "缺口/验证问题"),
        (
            "action", "action_disposition", "external_interaction", "resource_commitment",
            "owner", "due_date", "依赖", "完成标准", "继续/调整/no-go条件", "CRM/PIMS候选",
        ),
        ("序号", "claim_id", "claim_type", "provenance", "发现", "impact_type", "业务影响", "置信度"),
        ("review_id", "review_type", "claim_or_source_ref", "risk_code", "owner", "review_status"),
        ("claim_ref", "claim_type_ref", "provenance_ref", "evidence_state", "impact_type", "verification_mode", "owner", "due_date"),
        ("序号", "claim_id", "artifact_type", "usage_code"),
        ("序号", "source_id", "artifact_type", "source_status"),
        ("run_id", "新增", "更正", "失效", "未变化", "待确认"),
        ("updated_at", "content_version", "latest_run_id", "变更摘要", "runtime_owner"),
    }
    header_counts: dict[tuple[str, ...], int] = {}
    for header, _rows in markdown_table_blocks(visible):
        signature = tuple(header)
        header_counts[signature] = header_counts.get(signature, 0) + 1
        if signature not in allowed_table_headers:
            bad_labels.add("非契约表头：" + "/".join(header))
    duplicate_headers = [
        "/".join(header)
        for header, count in header_counts.items()
        if header in allowed_table_headers and count > 1
    ]
    if duplicate_headers:
        bad_labels.add("重复契约表：" + ", ".join(sorted(duplicate_headers)))

    review_bodies = headings.get("异常审核队列", [])
    if review_bodies:
        review_tables = markdown_table_blocks(review_bodies[0]) if len(review_bodies) == 1 else []
        expected_review_header = [
            "review_id", "review_type", "claim_or_source_ref",
            "risk_code", "owner", "review_status",
        ]
        if (
            len(review_bodies) != 1
            or len(review_tables) != 1
            or review_tables[0][0] != expected_review_header
            or not 1 <= len(review_tables[0][1]) <= 10
            or any(
                len(row) != 6
                or not re.fullmatch(r"REV-\d{3,}", row[0])
                or row[1] not in {
                    "evidence_conflict", "low_confidence", "internal_sensitive",
                    "commitment_review", "external_fact_review",
                }
                or not (CLAIM_RE.fullmatch(row[2]) or SOURCE_RE.fullmatch(row[2]))
                or row[3] not in {
                    "decision_risk", "compliance_risk", "confidentiality_risk", "commitment_risk",
                }
                or not stable_owner_cell(row[4])
                or row[5] not in {"not_started", "pending", "approved", "changes_requested"}
                for row in review_tables[0][1]
            )
        ):
            bad_labels.add("异常审核队列固定代码表无效")

    navigation_bodies = headings.get("主张与来源导航", [])
    if navigation_bodies:
        navigation_tables = markdown_table_blocks(navigation_bodies[0]) if len(navigation_bodies) == 1 else []
        expected_claim_nav = ["序号", "claim_id", "artifact_type", "usage_code"]
        expected_source_nav = ["序号", "source_id", "artifact_type", "source_status"]
        artifact_by_prefix = {
            "I": "institution_research", "L": "leader_research", "N": "internal_retrieval"
        }
        claim_rows = navigation_tables[0][1] if len(navigation_tables) >= 1 else []
        source_rows = navigation_tables[1][1] if len(navigation_tables) >= 2 else []
        if (
            len(navigation_bodies) != 1
            or len(navigation_tables) != 2
            or navigation_tables[0][0] != expected_claim_nav
            or navigation_tables[1][0] != expected_source_nav
            or not claim_rows
            or not source_rows
            or any(
                len(row) != 4
                or not CLAIM_RE.fullmatch(row[1])
                or row[2] != artifact_by_prefix.get(row[1].split("-")[1] if CLAIM_RE.fullmatch(row[1]) else "")
                or row[3] not in {
                    "decision_summary", "judgment_chain", "gcp", "qualification",
                    "action", "finding", "gap",
                }
                for row in claim_rows
            )
            or any(
                len(row) != 4
                or not SOURCE_RE.fullmatch(row[1])
                or row[2] != artifact_by_prefix.get(row[1].split("-")[1] if SOURCE_RE.fullmatch(row[1]) else "")
                or row[3] not in {"current", "stale", "invalidated"}
                for row in source_rows
            )
        ):
            bad_labels.add("主张与来源导航固定代码表无效")

    raci_heading_present = bool(
        re.search(r"^###\s+(?:\d+(?:\.\d+)*[.)]?\s+)?本次RACI与审核SLA\s*$", visible, re.MULTILINE)
    )
    raci_tables = [
        (header, rows)
        for header, rows in markdown_table_blocks(visible)
        if header == ["角色", "姓名（稳定角色/账号）", "本次责任", "截止时间/状态"]
    ]
    if raci_heading_present or raci_tables:
        expected_raci_roles = [
            "account_owner", "runtime_owner", "evidence_reviewer",
            "commercial_reviewer", "external_approver", "authorization_owner",
        ]
        responsibility_by_role = {
            "account_owner": "account_decision",
            "runtime_owner": "research_execution",
            "evidence_reviewer": "evidence_review",
            "commercial_reviewer": "commercial_review",
            "external_approver": "external_approval",
            "authorization_owner": "data_authorization",
        }
        raci_rows = raci_tables[0][1] if len(raci_tables) == 1 else []
        if (
            not raci_heading_present
            or len(raci_tables) != 1
            or [row[0] if row else "" for row in raci_rows] != expected_raci_roles
            or any(
                len(row) != 4
                or (row[1] != "not_applicable" and not stable_owner_cell(row[1]))
                or row[2] != responsibility_by_role.get(row[0])
                or not (
                    row[3] in {"pending", "not_applicable"}
                    or date_valid(row[3])
                    or timestamp_valid(row[3])
                )
                for row in raci_rows
            )
        ):
            bad_labels.add("RACI与审核SLA固定代码表无效")

    allowed_list_labels = {
        "建议",
        "投入强度",
        "继续投入的前提/停止条件",
    }
    list_label_locations = {
        "建议": ("机会资格与投入建议", ""),
        "投入强度": ("机会资格与投入建议", ""),
        "继续投入的前提/停止条件": ("机会资格与投入建议", ""),
    }
    for line, parent_h2, parent_h3 in line_locations:
        list_match = re.match(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+)([^:：]+)[:：]", line)
        if list_match:
            label = list_match.group(1).strip()
            if label not in allowed_list_labels:
                bad_labels.add("非契约列表项：" + label)
            elif list_label_locations.get(label) != (parent_h2, parent_h3):
                bad_labels.add("列表项父章节无效：" + label)
        elif (
            parent_h2
            and line.strip()
            and not line.lstrip().startswith("|")
            and not re.match(r"^##(?!#)\s+\S", line)
            and not re.match(r"^#{3,6}\s+\S", line)
        ):
            bad_labels.add("章节含非契约自由正文：" + parent_h2)
        if not line.lstrip().startswith("|"):
            continue
        cells = split_table_cells(line)
        bad_labels.update(cell for cell in cells if cell in forbidden_body_labels)
        if (
            "时间" in cells
            and "议题/动作" in cells
            and any(cell in {"材料/演示", "展示材料", "演示材料"} for cell in cells)
        ):
            bad_labels.update({"时间化议程", "材料/演示"})

    preamble_lines = [line.strip() for line in markdown_preamble(visible).splitlines() if line.strip()]
    customer_name = total.frontmatter.get("customer_display_name", "")
    allowed_titles = {
        f"# {customer_name}客户研究与行动准备报告",
        f"# {customer_name}客户研究与拜访准备报告",
        f"# {customer_name}No-Go客户研究与行动准备报告",
    }
    mode_label = {
        "briefing": "会前速览",
        "standard_visit": "标准拜访包",
        "strategic_account": "战略客户包",
        "letter": "一封信",
    }.get(total.frontmatter.get("business_mode", ""), "")
    depth_label = {"quick": "快速版", "standard": "标准版", "deep": "深度版"}.get(
        total.frontmatter.get("depth", ""), ""
    )
    allowed_banner_line = (
        f"> 用户业务模式：{mode_label}｜内部研究档位：{depth_label}｜信息截止：{total.frontmatter.get('evidence_cutoff_date', '')}"
    )
    preamble_valid = bool(
        not preamble_lines
        or (
            preamble_lines[0] in allowed_titles
            and preamble_lines[1:] in ([], [allowed_banner_line])
        )
    )
    if not preamble_valid:
        bad_labels.add("标题区含非契约自由正文")

    for header, rows in markdown_table_blocks(visible):
        normalized_header = [normalize_evidence_text(cell) for cell in header]
        has_time_slot = any(re.search(r"(?:时段|时间|分钟)", cell) for cell in normalized_header)
        has_meeting_plan = any(
            re.search(r"(?:议题|主题|议程|材料|资料|演示|参会|出席)", cell)
            for cell in normalized_header
        )
        has_stage_axis = any(
            re.search(r"(?:阶段|环节|顺序|流程|时段|时间)", cell)
            for cell in normalized_header
        )
        has_discussion_axis = any(
            re.search(r"(?:讨论|主题|议题|议程|交流|内容|动作|安排|方案)", cell)
            for cell in normalized_header
        )
        has_customer_axis = any(
            re.search(r"(?:客户|院方|甲方|对象|参会|出席|联系人)", cell)
            for cell in normalized_header
        )
        has_owner_axis = any(
            re.search(r"(?:我方|乙方|owner|负责人|责任人|主持|讲解)", cell, re.IGNORECASE)
            for cell in normalized_header
        )
        has_material_axis = any(
            re.search(r"(?:材料|资料|附件|演示|截图|介绍|PPT|方案包)", cell, re.IGNORECASE)
            for cell in normalized_header
        )
        if has_discussion_axis and (
            (has_stage_axis and (has_owner_axis or has_customer_axis or has_material_axis))
            or (has_owner_axis and (has_customer_axis or has_material_axis))
        ):
            bad_labels.add("会议执行语义组合表")
        if has_time_slot and has_meeting_plan:
            bad_labels.add("改名后的时间化会议表")
        if rows and any(
            re.search(minute_pattern, cell)
            for row in rows
            for cell in row
        ) and has_meeting_plan:
            bad_labels.add("分钟级会议安排")
    account_mode = total.frontmatter.get("business_mode") == "strategic_account"
    if (
        account_mode
        and "开场" in visible
        and "收口" in visible
        and re.search(r"(?:展示|讲解|方案|材料|下次交流|客户活动|产品介绍)", visible)
    ):
        bad_labels.add("账户报告单元格中的开场/收口会议执行序列")

    finding_tables = [
        (header, rows)
        for header, rows in markdown_table_blocks(visible)
        if header == [
            "序号", "claim_id", "claim_type", "provenance", "发现",
            "impact_type", "业务影响", "置信度",
        ]
    ]
    if finding_tables:
        finding_conflicts: list[str] = []
        for row in finding_tables[0][1]:
            if len(row) != 8:
                finding_conflicts.append("列数无效")
                continue
            claim_id = row[1]
            definition = claims.get(claim_id) if claims is not None else None
            impact_values = {
                "decision": "影响机会决策",
                "verification": "需要补充验证",
                "risk": "存在误判风险",
                "resource": "影响资源投入",
            }
            if (
                not CLAIM_RE.fullmatch(claim_id)
                or row[2] not in {"F", "F2", "A", "H", "R"}
                or row[3] not in {"public", "U", "N"}
                or not meaningful_delivery_text(row[4], minimum_chars=6)
                or row[5] not in impact_values
                or row[6] != impact_values.get(row[5])
                or row[7] not in {"高", "中", "低"}
            ):
                finding_conflicts.append(claim_id or "未知claim")
                continue
            if claims is not None and (
                definition is None
                or len(definition.cells) < 5
                or definition.cells[1] != row[2]
                or definition.cells[2] != row[3]
                or normalize_evidence_text(definition.cells[4])
                != normalize_evidence_text(row[4])
            ):
                finding_conflicts.append(claim_id)
        if finding_conflicts:
            add(
                issues,
                "error",
                "comprehensive_finding_claim_mismatch",
                total.path,
                "高价值发现的claim_type、provenance和发现正文必须逐项匹配权威claim台账；impact_type与业务影响必须使用固定映射，不得借claim新增事实或执行计划："
                + ", ".join(sorted(set(finding_conflicts))),
            )

    expected_gap_header = [
        "claim_ref", "claim_type_ref", "provenance_ref", "evidence_state",
        "impact_type", "verification_mode", "owner", "due_date",
    ]
    gap_bodies = headings.get("关键缺口与验证计划", [])
    gap_tables = markdown_table_blocks(gap_bodies[0]) if len(gap_bodies) == 1 else []
    if gap_bodies and (
        len(gap_bodies) != 1
        or len(gap_tables) != 1
        or gap_tables[0][0] != expected_gap_header
        or not 1 <= len(gap_tables[0][1]) <= 10
    ):
        add(
            issues,
            "error",
            "comprehensive_gap_contract_invalid",
            total.path,
            "关键缺口与验证计划如出现，必须恰有一张1—10行的固定8列表。",
        )
    elif gap_tables:
        gap_conflicts: list[str] = []
        for row in gap_tables[0][1]:
            claim_id = row[0] if row else ""
            definition = claims.get(claim_id) if claims is not None else None
            if (
                len(row) != 8
                or not CLAIM_RE.fullmatch(claim_id)
                or row[1] not in {"F", "F2", "A", "H", "R"}
                or row[2] not in {"public", "U", "N"}
                or row[3] not in {"unknown", "conflicted", "stale", "insufficient"}
                or row[4] not in {"decision", "verification", "risk", "resource"}
                or row[5] not in {"internal_review", "public_refresh", "authorized_customer_contact"}
                or not stable_owner_cell(row[6])
                or not date_valid(row[7])
                or (
                    claims is not None
                    and (
                        definition is None
                        or len(definition.cells) < 3
                        or definition.cells[1] != row[1]
                        or definition.cells[2] != row[2]
                    )
                )
            ):
                gap_conflicts.append(claim_id or "未知claim")
        if gap_conflicts:
            add(
                issues,
                "error",
                "comprehensive_gap_contract_invalid",
                total.path,
                "关键缺口只能引用权威claim，并使用受控evidence_state、impact_type和verification_mode；owner必须是稳定身份，due_date必须是日期："
                + ", ".join(sorted(set(gap_conflicts))),
            )
    if re.search(minute_pattern, visible) and re.search(
        r"(?:会议|拜访|议程|开场|收口|参会|出席|材料|资料|演示)",
        visible,
    ):
        bad_labels.add("正文中的分钟级会议安排")
    sequence_markers = set(
        re.findall(
            r"(?m)^\s*(?:[-*+]\s+|\d+[.)、]\s+)?(开场|开局|核心|收口|结束|总结)\s*[:：|]",
            visible,
        )
    )
    if (
        len(sequence_markers) >= 2
        and re.search(r"(?:交流|方案|客户|主任|反馈|介绍|截图|下次|双方)", visible)
    ):
        bad_labels.add("正文中的序列化会议计划")
    if bad_headings or bad_labels:
        detail = sorted(set(bad_headings) | bad_labels)
        add(
            issues,
            "error",
            (
                "account_comprehensive_structure_forbidden"
                if account_mode
                else "comprehensive_structure_forbidden"
            ),
            total.path,
            "综合报告只能使用模板规定的章节、表格和列表，不得增加影子结论、动作或会议执行结构："
            + ", ".join(detail),
        )


def validate_workspace_delivery_contract(
    by_type: Mapping[str, Document],
    total: Document,
    profile: Mapping[str, object],
    issues: list[Issue],
    *,
    strict: bool,
) -> None:
    """Enforce the configured formal-delivery/audit-carrier boundary."""

    business_mode = total.frontmatter.get("business_mode", "")
    try:
        contract = delivery_contract_for_mode(
            business_mode,
            profiles={business_mode: profile},
        )
    except ValueError as exc:
        add(
            issues,
            "error",
            "delivery_contract_invalid",
            total.path,
            "业务模式交付契约缺失或漂移：" + str(exc),
        )
        return
    audit = by_type.get(contract["audit_artifact"])
    if audit is not total:
        add(
            issues,
            "error",
            "delivery_audit_carrier_invalid",
            total.path,
            "综合报告必须是唯一审计与状态载体。",
        )
        return
    if not (strict or total.frontmatter.get("ready_for_use") == "true"):
        return

    formal_type = contract["formal_artifact"]
    formal = by_type.get(formal_type)
    if formal is None:
        add(
            issues,
            "error",
            "formal_delivery_required",
            total.path,
            f"{business_mode}缺少正式交付成果{formal_type}。",
        )
        return
    if (
        formal.frontmatter.get("module_status") != "completed"
        or formal.frontmatter.get("freshness_status") != "current"
        or formal.frontmatter.get("review_status") != "approved"
    ):
        add(
            issues,
            "error",
            "formal_delivery_not_ready",
            formal.path,
            f"正式交付成果{formal_type}必须completed/current/approved。",
        )
    if formal_type == "briefing_delivery" and formal.frontmatter.get("delivery_state") != "ready":
        add(
            issues,
            "error",
            "formal_delivery_not_ready",
            formal.path,
            "会前速览正式交付还必须delivery_state=ready。",
        )
    status_row = parse_status_rows(total).get(formal_type, [])
    if len(status_row) < 3 or status_row[1] != "true" or status_row[2] == "not_called":
        add(
            issues,
            "error",
            "formal_delivery_unselected",
            total.path,
            f"正式交付成果{formal_type}必须在综合审计载体登记为本轮selected且动作非not_called。",
        )


def validate_operating_governance(
    by_type: dict[str, Document],
    issues: list[Issue],
    strict: bool,
    current_time: datetime | None = None,
    *,
    claims: Mapping[str, ClaimDefinition] | None = None,
    sources: Mapping[str, SourceDefinition] | None = None,
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    data = total.frontmatter
    now = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    business_mode = data.get("business_mode", "")
    if business_mode and business_mode not in BUSINESS_MODES:
        add(issues, "error", "business_mode_invalid", total.path, f"business_mode必须为{sorted(BUSINESS_MODES)}。")
    if strict and not business_mode:
        add(issues, "error", "business_mode_required", total.path, "严格交付必须通过四种业务模式之一启动。")
    profiles = load_business_profiles(issues)
    profile = profiles.get(business_mode, {}) if business_mode else {}
    if business_mode in BUSINESS_MODES:
        validate_workspace_delivery_contract(
            by_type,
            total,
            profile if isinstance(profile, Mapping) else {},
            issues,
            strict=strict,
        )
    if isinstance(profile, dict) and data.get("route") != "refresh":
        expected_route = str(profile.get("route", ""))
        expected_depth = str(profile.get("depth", ""))
        if expected_route and data.get("route") != expected_route:
            add(issues, "error", "business_mode_route_mismatch", total.path, f"{business_mode}必须映射route={expected_route}。")
        if expected_depth and data.get("depth") != expected_depth:
            add(issues, "error", "business_mode_depth_mismatch", total.path, f"{business_mode}必须映射depth={expected_depth}。")

    ready = data.get("ready_for_use", "false")
    if ready not in {"true", "false"}:
        add(issues, "error", "ready_for_use_invalid", total.path, "ready_for_use必须为true或false。")
    if strict and ready != "true":
        add(issues, "error", "ready_for_use_required", total.path, "严格交付前必须完成独立就绪门禁并设置ready_for_use=true。")

    internal = by_type.get("internal_retrieval")
    status_rows = parse_status_rows(total)
    if business_mode == "briefing":
        briefing_row = status_rows.get("briefing_delivery", [])
        if len(briefing_row) < 3 or briefing_row[1] != "true" or briefing_row[2] == "not_called":
            add(issues, "error", "briefing_delivery_unselected", total.path, "briefing模式必须把会前速览登记为本轮selected且动作非not_called。")
    if isinstance(profile, dict) and data.get("route") != "refresh" and (strict or ready == "true"):
        selected_names = {
            MODULE_NAME_FOR_TYPE[artifact_type]
            for artifact_type, row in status_rows.items()
            if artifact_type in MODULE_NAME_FOR_TYPE and len(row) >= 2 and row[1] == "true"
        }
        required_names = {str(value) for value in profile.get("modules", []) if isinstance(value, str)}
        missing_required = sorted(required_names - selected_names)
        if missing_required:
            add(issues, "error", "business_mode_module_missing", total.path, "当前业务模式缺少必需成果：" + ", ".join(missing_required))
    internal_row = status_rows.get("internal_retrieval", [])
    internal_selected = len(internal_row) >= 2 and internal_row[1] == "true"
    authorization_required = bool(
        internal_selected
        or (internal and internal.frontmatter.get("connector_status") == "connected")
        or requires_internal_authorization(claims, sources)
    )
    if authorization_required:
        missing = sorted(field for field in AUTHORIZATION_FIELDS if not data.get(field, "").strip())
        if missing:
            add(issues, "error", "authorization_required", total.path, "缺少稳定租户/项目授权字段：" + ", ".join(missing))
        for field in ("tenant_id", "project_id"):
            value = data.get(field, "")
            if value and not IDENTIFIER_RE.fullmatch(value):
                add(issues, "error", "authorization_id_invalid", total.path, f"{field}必须是稳定标识符。")
        owner = data.get("authorization_owner", "")
        if owner in {"", "待确认", "待指定"}:
            add(issues, "error", "authorization_owner_unassigned", total.path, "授权必须绑定实名责任人或稳定责任角色。")
        expiry = parse_expiry(data.get("authorization_expires_at", ""))
        if expiry is None:
            add(issues, "error", "authorization_expiry_invalid", total.path, "authorization_expires_at必须为日期或带时区ISO 8601时间。")
        elif expiry <= now:
            add(issues, "error", "authorization_expired", total.path, "租户/项目授权已过期，不得继续检索或交付。")

    today, future_limit, task_timezone = evidence_calendar(total.path.parent, instant=now)
    profile_ttl = profile.get("ttl_days", {}) if isinstance(profile, dict) else {}
    for artifact_type, document in by_type.items():
        cutoff_text = document.frontmatter.get("evidence_cutoff_date", "")
        if not date_valid(cutoff_text):
            continue
        cutoff = date.fromisoformat(cutoff_text)
        if cutoff > future_limit:
            basis = f"任务时区{task_timezone}" if task_timezone else "未指定任务时区的兼容民用日窗口"
            add(
                issues,
                "error",
                "evidence_cutoff_in_future",
                document.path,
                f"evidence_cutoff_date不得晚于{basis}当前日期{future_limit.isoformat()}。",
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
                "briefing_delivery": "strategy",
                "comprehensive_report": "total",
            }.get(artifact_type, "")
            candidate = profile_ttl.get(ttl_key) if ttl_key else None
            if isinstance(candidate, int) and candidate > 0:
                ttl = candidate
        if document.frontmatter.get("freshness_status") == "current" and today - cutoff > timedelta(days=ttl):
            severity = "error" if strict or data.get("workflow_stage") in {"review", "closed"} else "warning"
            add(issues, severity, "freshness_ttl_exceeded", document.path, f"该类信息TTL为{ttl}天；应标记stale并刷新或移除依赖。")

    if ready == "true":
        readiness = {field: data.get(field, "") for field in READINESS_FIELDS}
        missing_readiness = sorted(field for field, value in readiness.items() if not value.strip())
        if missing_readiness:
            add(issues, "error", "readiness_audit_required", total.path, "ready_for_use缺少审批审计字段：" + ", ".join(missing_readiness))
        if readiness["readiness_reviewer"] in {"", "待确认", "待指定"}:
            add(issues, "error", "readiness_reviewer_unassigned", total.path, "ready_for_use必须绑定实名审核人或稳定审核角色。")
        if not timestamp_valid(readiness["readiness_reviewed_at"]):
            add(issues, "error", "readiness_time_invalid", total.path, "readiness_reviewed_at必须为带时区ISO 8601时间。")
        if readiness["readiness_content_version"] != data.get("content_version"):
            add(issues, "error", "readiness_version_drift", total.path, "readiness_content_version必须等于综合报告content_version。")
        if readiness["readiness_body_sha256"] != body_sha256(total.body):
            add(issues, "error", "readiness_body_drift", total.path, "ready_for_use后综合报告正文已变化，必须重新执行就绪审批。")
        if data.get("module_status") != "completed" or data.get("freshness_status") != "current":
            add(issues, "error", "ready_state_conflict", total.path, "ready_for_use=true要求综合报告completed/current。")
        if data.get("runtime_owner") in {"", "待确认", "待指定"}:
            add(issues, "error", "ready_owner_missing", total.path, "ready_for_use=true前必须绑定runtime_owner。")
        rows = parse_status_rows(total)
        selected = {key for key, row in rows.items() if len(row) >= 2 and row[1] == "true"}
        for artifact_type in selected & (GENERIC_REVIEW_TYPES | {"customer_letter_internal"}):
            artifact = by_type.get(artifact_type)
            if artifact is not None and artifact.frontmatter.get("review_status") != "approved":
                add(issues, "error", "ready_review_missing", artifact.path, "选中成果未完成独立审核，不能标记ready_for_use。")
        if business_mode == "briefing":
            briefing = by_type.get("briefing_delivery")
            if briefing is None:
                add(issues, "error", "briefing_delivery_required", total.path, "briefing模式缺少正式会前速览成果。")
            elif briefing.frontmatter.get("review_status") != "approved" or briefing.frontmatter.get("delivery_state") != "ready":
                add(issues, "error", "briefing_delivery_not_ready", briefing.path, "briefing模式就绪前会前速览必须approved/ready。")
    elif any(data.get(field, "").strip() for field in READINESS_FIELDS):
        add(issues, "error", "stale_readiness_metadata", total.path, "ready_for_use=false时必须清空旧就绪审批戳。")

    if strict and business_mode == "briefing" and "briefing_delivery" not in by_type:
        add(issues, "error", "briefing_delivery_required", total.path, "briefing发布校验必须包含正式会前速览成果。")

    if business_mode in {"briefing", "standard_visit", "strategic_account"}:
        strategy = by_type.get("visit_strategy")
        if business_mode in {"standard_visit", "strategic_account"}:
            validate_comprehensive_delivery_contract(total, strategy, issues, claims=claims)
        if strategy is not None:
            validate_strategy_delivery_separation(strategy, issues)
            actual_variant = strategy.frontmatter.get("strategy_variant", "")
            expected_variant = actual_variant if business_mode == "strategic_account" else "scheduled_visit"
            if actual_variant != expected_variant or expected_variant not in {"scheduled_visit", "account_planning"}:
                add(issues, "error", "strategy_variant_mode_mismatch", strategy.path, f"{business_mode}不允许strategy_variant={actual_variant or '空'}。")
            contract = strategy_variant_contract(
                business_mode,
                expected_variant,
                profiles=profiles,
            )
            if contract is None:
                add(
                    issues,
                    "error",
                    "strategy_variant_contract_missing",
                    strategy.path,
                    f"strategy_variant={expected_variant}缺少可执行的业务模式契约。",
                )
            else:
                validate_recommendation_template_route(
                    total,
                    strategy,
                    contract,
                    profiles,
                    issues,
                )
                forbidden_fields = {
                    str(field)
                    for field in (
                        list(contract.get("forbidden_business_fields", []))
                        + list(contract.get("forbidden_followup_fields", []))
                    )
                    if isinstance(field, str)
                }
                present_fields = sorted(
                    field
                    for field in forbidden_fields
                    if field in strategy.frontmatter
                    and str(strategy.frontmatter.get(field, "")).strip()
                )
                if present_fields:
                    add(
                        issues,
                        "error",
                        "strategy_variant_field_forbidden",
                        strategy.path,
                        f"strategy_variant={expected_variant}不得持久化另一分支或会议专属字段："
                        + ", ".join(present_fields),
                    )
                headings = [
                    match.group(1).strip()
                    for match in re.finditer(
                        r"^##\s+(?:\d+\.\s*)?(.+?)\s*$",
                        strategy.body,
                        re.MULTILINE,
                    )
                ]
                forbidden_sections = {
                    str(section).strip()
                    for section in contract.get("forbidden_sections", [])
                    if isinstance(section, str) and section.strip()
                }
                forbidden_terms = {
                    str(term).strip()
                    for term in contract.get("forbidden_heading_terms", [])
                    if isinstance(term, str) and term.strip()
                }
                forbidden_headings = sorted(
                    {
                        heading
                        for heading in headings
                        if heading in forbidden_sections
                        or any(term in heading for term in forbidden_terms)
                    }
                )
                if forbidden_headings:
                    add(
                        issues,
                        "error",
                        "strategy_variant_heading_forbidden",
                        strategy.path,
                        f"strategy_variant={expected_variant}不得包含会议/另一分支专属章节："
                        + ", ".join(forbidden_headings),
                    )
                forbidden_body_labels = {
                    str(label).strip()
                    for label in contract.get("forbidden_body_labels", [])
                    if isinstance(label, str) and label.strip()
                }
                present_body_labels: set[str] = set()
                if forbidden_body_labels:
                    visible_body = markdown_without_fenced_code(strategy.body)
                    alternatives = "|".join(
                        re.escape(label)
                        for label in sorted(forbidden_body_labels, key=len, reverse=True)
                    )
                    label_pattern = re.compile(
                        rf"^\s*(?:(?:[-*+]\s+)|(?:\d+[.)、]\s*))?(?:\*\*)?"
                        rf"(?P<label>{alternatives})(?:\*\*)?\s*[:：]",
                        re.MULTILINE,
                    )
                    present_body_labels.update(
                        match.group("label") for match in label_pattern.finditer(visible_body)
                    )
                    for line in visible_body.splitlines():
                        if not line.lstrip().startswith("|"):
                            continue
                        cells = split_table_cells(line)
                        present_body_labels.update(
                            cell for cell in cells if cell in forbidden_body_labels
                        )
                if present_body_labels:
                    add(
                        issues,
                        "error",
                        "strategy_variant_body_label_forbidden",
                        strategy.path,
                        f"strategy_variant={expected_variant}不得把未确认会议信息写成结构化事实标签："
                        + ", ".join(sorted(present_body_labels)),
                    )
                if strategy.frontmatter.get("module_status") == "completed":
                    if expected_variant == "scheduled_visit":
                        validate_scheduled_strategy_sections(
                            strategy,
                            issues,
                            by_type=by_type,
                            claims=claims,
                        )
                    elif expected_variant == "account_planning":
                        validate_account_action_contract(
                            strategy,
                            contract,
                            issues,
                            by_type=by_type,
                            claims=claims,
                        )
                        validate_account_comprehensive_contract(
                            total,
                            forbidden_terms,
                            forbidden_body_labels,
                            issues,
                            claims=claims,
                        )
                if strict:
                    if business_mode == "strategic_account":
                        required_sections = [
                            str(section).strip()
                            for section in contract.get("required_sections", [])
                            if isinstance(section, str) and section.strip()
                        ]
                        missing_sections = [
                            section for section in required_sections if section not in headings
                        ]
                    else:
                        # v2.5 briefing/standard_visit成果使用兼容章节名；它们仍
                        # 共享scheduled_visit的禁止字段契约，但不被战略客户模板
                        # 的新版标题名称反向破坏。
                        required_sections = [
                            "目标与最小推进动作",
                            "机会资格",
                            "议程",
                            "参会分工",
                            "材料",
                            "会后行动",
                            "CRM/PIMS",
                        ]
                        missing_sections = [
                            section for section in required_sections if section not in strategy.body
                        ]
                    if missing_sections:
                        add(issues, "error", "presales_loop_incomplete", strategy.path, "售前闭环缺少章节：" + ", ".join(missing_sections))
                    if expected_variant == "account_planning":
                        for cycle in ("30天", "60天", "90天"):
                            if not re.search(rf"^\|\s*{re.escape(cycle)}\s*\|", strategy.body, re.MULTILINE):
                                add(issues, "error", "account_strategy_action_horizon_missing", strategy.path, f"30/60/90天动作表缺少{cycle}。")


def _audit_instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_trusted_governance(
    root: Path,
    by_type: dict[str, Document],
    issues: list[Issue],
) -> None:
    total = by_type.get("comprehensive_report")
    if total is None:
        return
    governed = [
        document
        for document in by_type.values()
        if document.frontmatter.get("review_status") == "approved"
        or document.frontmatter.get("artifact_type") == "customer_letter_external"
        or document.frontmatter.get("fact_review_action_event_id")
        or document.frontmatter.get("revision_action_event_id")
    ]
    if total.frontmatter.get("ready_for_use") == "true":
        governed.append(total)
    if not governed:
        return
    try:
        registry = load_governance_context(root)
    except GovernanceError as exc:
        add(issues, "error", "trusted_governance_missing", root, str(exc))
        return
    context_id = total.frontmatter.get("context_id", "")
    customer_id = total.frontmatter.get("customer_id", "")
    business_mode = total.frontmatter.get("business_mode", "")

    def check_consumed_action(
        document: Document,
        *,
        event_id: str,
        operation: str,
        actor_id: str,
        run_id: str,
        consumed_at: str,
        target_artifact_type: str,
        target_content_version: str,
        target_body_digest: str | None,
        target_context_digest: str | None,
    ) -> None:
        event = registry.get("action_assertions", {}).get(event_id)
        if not isinstance(event, dict):
            add(issues, "error", "action_event_missing", document.path, f"成果引用的宿主签名动作事件不存在：{event_id}")
            return
        expected = {
            "schema": "discovery-call-action-assertion/v1",
            "action_id": event_id,
            "event_type": "governance_action_approved",
            "source": "authenticated_human_action",
            "verified": True,
            "decision": "approved",
            "actor_id": actor_id,
            "operation": operation,
            "context_id": context_id,
            "customer_id": customer_id,
            "business_mode": business_mode,
            "target_artifact_type": target_artifact_type,
            "target_content_version": target_content_version,
            "consumed_by_run_id": run_id,
            "consumed_at": consumed_at,
        }
        if target_body_digest is not None:
            expected["target_body_sha256"] = target_body_digest
        if target_context_digest is not None:
            expected["target_context_sha256"] = target_context_digest
        mismatched = [key for key, value in expected.items() if event.get(key) != value]
        if not event.get("session_id") or not event.get("nonce"):
            mismatched.extend(["session_id", "nonce"])
        if mismatched:
            add(
                issues,
                "error",
                "action_event_lineage_invalid",
                document.path,
                "宿主签名动作事件与成果谱系不一致：" + ", ".join(sorted(set(mismatched))),
            )
            return
        try:
            validate_global_nonce_claim(
                event,
                workspace=root,
                event_id=event_id,
                operation=operation,
                consumed_at=consumed_at,
            )
        except GovernanceError as exc:
            add(issues, "error", "action_event_global_claim_invalid", document.path, str(exc))

    generic_requirements = {
        "institution_research": ("institution", {"evidence_reviewer"}),
        "leader_research": ("leader", {"evidence_reviewer"}),
        "internal_retrieval": ("internal", {"evidence_reviewer"}),
        "visit_strategy": ("strategy", {"commercial_reviewer"}),
        "briefing_delivery": ("briefing", {"evidence_reviewer", "account_owner"}),
    }
    for artifact_type, (target_name, roles) in generic_requirements.items():
        document = by_type.get(artifact_type)
        if document is None or document.frontmatter.get("review_status") != "approved":
            continue
        data = document.frontmatter
        try:
            target_version = str(int(data.get("reviewed_content_version", "")) - 1)
        except ValueError:
            target_version = ""
        check_consumed_action(
            document,
            event_id=data.get("review_action_event_id", ""),
            operation=f"approve_artifact:{target_name}",
            actor_id=data.get("reviewer_actor_id", ""),
            run_id=data.get("latest_run_id", ""),
            consumed_at=data.get("reviewed_at", ""),
            target_artifact_type=artifact_type,
            target_content_version=target_version,
            target_body_digest=body_sha256(document.body),
            target_context_digest="",
        )
        try:
            resolve_actor(
                root,
                actor_id=data.get("reviewer_actor_id", ""),
                display_name=data.get("reviewer", ""),
                operation=f"approve_artifact:{target_name}",
                required_roles=roles,
                context_id=context_id,
                customer_id=customer_id,
                business_mode=business_mode,
                at=_audit_instant(data.get("reviewed_at", "")),
                registry=registry,
            )
        except GovernanceError as exc:
            add(issues, "error", "review_actor_untrusted", document.path, str(exc))
    internal = by_type.get("customer_letter_internal")
    if internal is not None and internal.frontmatter.get("fact_review_action_event_id"):
        data = internal.frontmatter
        try:
            fact_target_version = str(int(data.get("fact_reviewed_content_version", "")) - 1)
        except ValueError:
            fact_target_version = ""
        check_consumed_action(
            internal,
            event_id=data.get("fact_review_action_event_id", ""),
            operation="review_letter_facts",
            actor_id=data.get("fact_reviewer_actor_id", ""),
            run_id=data.get("fact_reviewed_run_id", ""),
            consumed_at=data.get("fact_reviewed_at", ""),
            target_artifact_type="customer_letter_internal",
            target_content_version=fact_target_version,
            target_body_digest=data.get("fact_reviewed_body_sha256", ""),
            target_context_digest=data.get("fact_reviewed_context_sha256", ""),
        )
        try:
            resolve_actor(
                root,
                actor_id=data.get("fact_reviewer_actor_id", ""),
                display_name=data.get("fact_reviewer", ""),
                operation="review_letter_facts",
                required_roles={"evidence_reviewer"},
                context_id=context_id,
                customer_id=customer_id,
                business_mode=business_mode,
                at=_audit_instant(data.get("fact_reviewed_at", "")),
                registry=registry,
            )
        except GovernanceError as exc:
            add(issues, "error", "fact_reviewer_actor_untrusted", internal.path, str(exc))
    if internal is not None and internal.frontmatter.get("review_status") == "approved":
        data = internal.frontmatter
        check_consumed_action(
            internal,
            event_id=data.get("approval_action_event_id", ""),
            operation="approve_letter",
            actor_id=data.get("approver_actor_id", ""),
            run_id=data.get("approval_run_id", ""),
            consumed_at=data.get("approved_at", ""),
            target_artifact_type="customer_letter_internal",
            target_content_version=data.get("fact_reviewed_content_version", ""),
            target_body_digest=data.get("approved_body_sha256", ""),
            target_context_digest=data.get("approved_context_sha256", ""),
        )
        try:
            resolve_actor(
                root,
                actor_id=data.get("approver_actor_id", ""),
                display_name=data.get("approver", ""),
                operation="approve_letter",
                required_roles={"external_approver"},
                context_id=context_id,
                customer_id=customer_id,
                business_mode=business_mode,
                at=_audit_instant(data.get("approved_at", "")),
                registry=registry,
            )
        except GovernanceError as exc:
            add(issues, "error", "approver_actor_untrusted", internal.path, str(exc))
    if total.frontmatter.get("ready_for_use") == "true":
        readiness_roles = {
            "briefing": {"evidence_reviewer", "account_owner"},
            "standard_visit": {"commercial_reviewer"},
            "strategic_account": {"account_owner"},
            "letter": {"external_approver"},
        }
        try:
            readiness_target_version = str(int(total.frontmatter.get("readiness_content_version", "")) - 1)
        except ValueError:
            readiness_target_version = ""
        check_consumed_action(
            total,
            event_id=total.frontmatter.get("readiness_action_event_id", ""),
            operation=f"mark_ready:{business_mode}",
            actor_id=total.frontmatter.get("readiness_reviewer_actor_id", ""),
            run_id=total.frontmatter.get("latest_run_id", ""),
            consumed_at=total.frontmatter.get("readiness_reviewed_at", ""),
            target_artifact_type="comprehensive_report",
            target_content_version=readiness_target_version,
            target_body_digest=total.frontmatter.get("readiness_target_body_sha256", ""),
            target_context_digest="",
        )
        try:
            resolve_actor(
                root,
                actor_id=total.frontmatter.get("readiness_reviewer_actor_id", ""),
                display_name=total.frontmatter.get("readiness_reviewer", ""),
                operation=f"mark_ready:{business_mode}",
                required_roles=readiness_roles.get(business_mode, set()),
                context_id=context_id,
                customer_id=customer_id,
                business_mode=business_mode,
                at=_audit_instant(total.frontmatter.get("readiness_reviewed_at", "")),
                registry=registry,
            )
        except GovernanceError as exc:
            add(issues, "error", "readiness_actor_untrusted", total.path, str(exc))
    if internal is not None and internal.frontmatter.get("revision_action_event_id"):
        data = internal.frontmatter
        check_consumed_action(
            internal,
            event_id=data.get("revision_action_event_id", ""),
            operation="begin_letter_revision",
            actor_id=data.get("revision_actor_id", ""),
            run_id=data.get("revision_run_id", ""),
            consumed_at=data.get("revision_at", ""),
            target_artifact_type="customer_letter_internal",
            target_content_version=data.get("revision_target_content_version", ""),
            target_body_digest=data.get("revision_target_body_sha256", ""),
            target_context_digest=data.get("revision_target_context_sha256", ""),
        )
    external = by_type.get("customer_letter_external")
    if external is None:
        if business_mode == "letter" and total.frontmatter.get("ready_for_use") == "true":
            add(issues, "error", "letter_external_required", total.path, "一封信ready_for_use=true必须存在经第二次请求生成的外发版。")
        return
    if internal is None:
        return
    request_id = external.frontmatter.get("external_request_event_id", "")
    event = registry.get("external_requests", {}).get(request_id)
    if not isinstance(event, dict):
        add(issues, "error", "external_request_event_missing", external.path, "外发版引用的宿主请求事件不存在。")
        return
    checks = {
        "schema": "discovery-call-external-request-assertion/v1",
        "request_id": request_id,
        "event_type": "external_output_requested",
        "source": "authenticated_user_turn",
        "verified": True,
        "operation": "emit_external",
        "business_mode": business_mode,
        "context_id": context_id,
        "customer_id": customer_id,
        "approved_body_sha256": internal.frontmatter.get("approved_body_sha256", ""),
        "approved_context_sha256": internal.frontmatter.get("approved_context_sha256", ""),
        "consumed_by_run_id": external.frontmatter.get("latest_run_id", ""),
    }
    mismatched = [key for key, expected in checks.items() if event.get(key) != expected]
    try:
        expected_source_version = str(int(internal.frontmatter.get("content_version", "")) - 1)
    except ValueError:
        expected_source_version = ""
    if event.get("internal_content_version") != expected_source_version:
        mismatched.append("internal_content_version")
    if event.get("consumed_at") != external.frontmatter.get("updated_at"):
        mismatched.append("consumed_at")
    if event.get("actor_id") != external.frontmatter.get("external_requested_by_actor_id"):
        mismatched.append("actor_id")
    if event.get("requested_at") != external.frontmatter.get("external_requested_at"):
        mismatched.append("requested_at")
    if mismatched:
        add(issues, "error", "external_request_lineage_invalid", external.path, "外发请求事件谱系不一致：" + ", ".join(sorted(set(mismatched))))
    else:
        try:
            validate_global_nonce_claim(
                event,
                workspace=root,
                event_id=request_id,
                operation="emit_external",
                consumed_at=external.frontmatter.get("updated_at", ""),
            )
        except GovernanceError as exc:
            add(issues, "error", "external_request_global_claim_invalid", external.path, str(exc))
    try:
        actor_id = str(event.get("actor_id", ""))
        display = str(registry.get("actors", {}).get(actor_id, {}).get("display_name", ""))
        resolve_actor(
            root,
            actor_id=actor_id,
            display_name=display,
            operation="emit_external",
            required_roles={"requester", "account_owner"},
            context_id=context_id,
            customer_id=customer_id,
            business_mode=business_mode,
            separate_from_runtime=False,
            at=_audit_instant(str(event.get("requested_at", ""))),
            registry=registry,
        )
    except GovernanceError as exc:
        add(issues, "error", "external_request_actor_untrusted", external.path, str(exc))


def validate_loaded(
    root: Path,
    documents: list[Document],
    issues: list[Issue],
    strict: bool,
    recovery_preflight: bool = False,
    current_time: datetime | None = None,
    validation_profile: str = "candidate",
    contracts_prevalidated: bool = False,
) -> None:
    if not contracts_prevalidated and not validate_trusted_contract_bundle(issues):
        return
    for document in documents:
        validate_frontmatter(
            document,
            issues,
            False if recovery_preflight else strict,
            placeholder_errors=not recovery_preflight and validation_profile != "scaffold",
        )
    by_type = validate_filenames_and_identity(documents, root, issues)
    if recovery_preflight:
        return
    claims, sources = collect_ledgers(documents, issues)
    validate_briefing_claim_contract(by_type, claims, issues)
    validate_claim_graph(documents, claims, sources, issues)
    validate_machine_evidence(
        root,
        documents,
        by_type,
        claims,
        sources,
        issues,
        strict,
        current_time,
        validation_profile,
    )
    validate_status_sync(by_type, issues, strict, claims=claims)
    validate_letter_review_history(by_type, issues, strict)
    validate_run_history(by_type, issues)
    validate_refresh_ledger(by_type, claims, sources, issues, strict)
    validate_route_gate(by_type, issues, strict)
    validate_research_fact_review_gate(by_type, issues, strict)
    validate_operating_governance(
        by_type,
        issues,
        strict,
        current_time,
        claims=claims,
        sources=sources,
    )
    validate_trusted_governance(root, by_type, issues)
    validate_runtime_manifest(
        root,
        by_type,
        issues,
        strict,
        validation_profile,
        current_time,
        claims=claims,
        sources=sources,
    )
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
    actor_id: str | None = None,
    action_event_id: str | None = None,
    request_event_id: str | None = None,
    review_facts: bool = False,
    begin_revision: bool = False,
    mark_ready: bool = False,
    recovery_preflight: bool = False,
    current_time: datetime | None = None,
    validation_profile: str = "candidate",
) -> tuple[list[Issue], list[Document], Path | None, str | None]:
    issues: list[Issue] = []
    if not validate_trusted_contract_bundle(issues):
        return issues, [], None, None
    documents = load_documents(root, issues)
    mutating = emit or approve or bool(approve_artifact) or review_facts or begin_revision or mark_ready
    validate_loaded(
        root,
        documents,
        issues,
        strict if not mutating else False,
        recovery_preflight,
        current_time,
        validation_profile,
        contracts_prevalidated=True,
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
            add(issues, "error", "operation_preflight_failed", root, "现有成果校验未通过，未执行治理状态变更。")
            return issues, documents, None, None
        try:
            snapshot = capture_workspace_snapshot(root, documents)
            if emit:
                mutation = emit_external(root, documents, actor_id or "", request_event_id or "", snapshot)
                operation = "emit_external"
            elif review_facts:
                mutation = review_letter_facts(
                    root, documents, reviewer or "", actor_id or "", action_event_id or "", snapshot
                )
                operation = "review_letter_facts"
            elif approve:
                mutation = approve_internal(
                    root, documents, approver or "", actor_id or "", action_event_id or "", snapshot
                )
                operation = "approve_letter"
            elif approve_artifact:
                mutation = approve_generic_artifact(
                    root,
                    documents,
                    approve_artifact,
                    reviewer or "",
                    actor_id or "",
                    action_event_id or "",
                    snapshot,
                )
                operation = f"approve_{approve_artifact}"
            elif begin_revision:
                mutation = begin_letter_revision(
                    root, documents, reviewer or "", actor_id or "", action_event_id or "", snapshot
                )
                operation = "begin_letter_revision"
            else:
                mutation = mark_ready_for_use(
                    root, documents, reviewer or "", actor_id or "", action_event_id or "", snapshot
                )
                operation = "mark_ready"
        except (KeyError, OSError, RuntimeError, UnicodeError) as exc:
            add(issues, "error", "operation_failed", root, str(exc))
            return issues, documents, None, None
        post_issues: list[Issue] = []
        post_documents = load_documents(root, post_issues)
        validate_loaded(
            root,
            post_documents,
            post_issues,
            mark_ready,
            current_time=current_time,
            validation_profile="release" if mark_ready else "candidate",
        )
        if any(issue.severity == "error" for issue in post_issues):
            if mutation.transactional:
                add(post_issues, "error", "transaction_postflight_inconsistent", root, "事务内复检与提交后复检结果不一致；停止后续操作并保留机器审计。")
                return post_issues, post_documents, None, None
            try:
                rollback_mutation(mutation)
            except (OSError, UnicodeError) as exc:
                add(post_issues, "error", "transaction_rollback_failed", root, f"提交后校验失败且回滚不完整：{exc}")
                return post_issues, post_documents, None, None
            add(post_issues, "error", "operation_postflight_failed", root, "变更后完整校验失败，已恢复全部文件。")
            return post_issues, documents, None, None
        issues, documents = post_issues, post_documents
        result_path = mutation.result_path
    return issues, documents, result_path, operation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验discovery-call v2.9成果契约，并执行可审计审批、就绪和客户信修订。"
    )
    parser.add_argument("workspace", type=Path, help="客户研究工作目录")
    parser.add_argument("--strict", action="store_true", help="最终交付校验：拒绝占位符及本轮非终态模块")
    parser.add_argument(
        "--profile",
        choices=("scaffold", "candidate", "release"),
        default=None,
        help="校验档位；默认candidate会把占位符作为错误，release另要求终态与就绪契约",
    )
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("--approve-letter", action="store_true", help="为pending内部稿写入审核人、版本和正文哈希审批戳")
    operations.add_argument("--review-letter-facts", action="store_true", help="由独立evidence_reviewer复核客户信事实与证据边界")
    operations.add_argument("--emit-external", action="store_true", help="从带有效审批戳的approved内部稿事务生成纯净外发版")
    operations.add_argument("--approve-artifact", choices=sorted(GENERIC_REVIEW_TARGETS), help="审批机构、人物、内部检索、策略或简报成果")
    operations.add_argument("--begin-letter-revision", action="store_true", help="归档现行外发版并事务开启新一轮客户信修订")
    operations.add_argument("--mark-ready", action="store_true", help="完成最终独立就绪审批并设置ready_for_use=true")
    operations.add_argument("--recovery-preflight", action="store_true", help="仅做恢复安全预检，允许模块与总报告暂时不同步")
    parser.add_argument("--approver", help="与--approve-letter配合使用的审核人或审核角色")
    parser.add_argument("--reviewer", help="与--approve-artifact、--begin-letter-revision或--mark-ready配合的责任人/稳定角色")
    parser.add_argument("--actor-id", help="宿主可信身份登记中的稳定真人ID；所有治理写操作必需")
    parser.add_argument("--action-event-id", help="与审批或mark-ready配合的宿主签名、短期、单次人工决定事件ID")
    parser.add_argument("--request-event-id", help="与--emit-external配合的审批后第二次明确用户请求事件ID")
    parser.add_argument("--json", action="store_true", help="输出JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.strict and args.profile is not None:
        print("ERROR: --strict是--profile release的兼容别名，不得与--profile同时使用。", file=sys.stderr)
        return 2
    validation_profile = (
        "scaffold"
        if args.recovery_preflight
        else "release"
        if args.strict
        else args.profile or "candidate"
    )
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
        args.review_letter_facts or args.approve_artifact or args.begin_letter_revision or args.mark_ready
    )
    if reviewer_operation and not args.reviewer:
        print("ERROR: 该治理操作必须同时提供 --reviewer。", file=sys.stderr)
        return 2
    if args.reviewer and not reviewer_operation:
        print("ERROR: --reviewer 只能与 --approve-artifact、--begin-letter-revision或--mark-ready一起使用。", file=sys.stderr)
        return 2
    mutating_operation = bool(
        args.approve_letter
        or args.review_letter_facts
        or args.emit_external
        or args.approve_artifact
        or args.begin_letter_revision
        or args.mark_ready
    )
    if mutating_operation and not args.actor_id:
        print("ERROR: 所有治理写操作必须同时提供宿主可信身份 --actor-id。", file=sys.stderr)
        return 2
    if args.actor_id and not mutating_operation:
        print("ERROR: --actor-id只能与治理写操作一起使用。", file=sys.stderr)
        return 2
    action_assertion_operation = bool(
        args.approve_letter
        or args.review_letter_facts
        or args.approve_artifact
        or args.begin_letter_revision
        or args.mark_ready
    )
    if action_assertion_operation and not args.action_event_id:
        print("ERROR: 审批和mark-ready必须同时提供宿主签名的--action-event-id。", file=sys.stderr)
        return 2
    if args.action_event_id and not action_assertion_operation:
        print("ERROR: --action-event-id只能与审批或mark-ready一起使用。", file=sys.stderr)
        return 2
    if args.emit_external and not args.request_event_id:
        print("ERROR: --emit-external必须同时提供审批后宿主记录的--request-event-id。", file=sys.stderr)
        return 2
    if args.request_event_id and not args.emit_external:
        print("ERROR: --request-event-id只能与--emit-external一起使用。", file=sys.stderr)
        return 2
    issues, documents, result_path, operation = validate(
        root,
        validation_profile == "release",
        args.emit_external,
        args.approve_letter,
        args.approver,
        approve_artifact=args.approve_artifact,
        reviewer=args.reviewer,
        actor_id=args.actor_id,
        action_event_id=args.action_event_id,
        request_event_id=args.request_event_id,
        review_facts=args.review_letter_facts,
        begin_revision=args.begin_letter_revision,
        mark_ready=args.mark_ready,
        recovery_preflight=args.recovery_preflight,
        validation_profile=validation_profile,
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
                    "validation_profile": validation_profile,
                    "deliverable_state": (
                        "invalid"
                        if errors
                        else "release_ready"
                        if validation_profile == "release"
                        else "scaffold_not_deliverable"
                        if validation_profile == "scaffold"
                        else "draft_for_review"
                    ),
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
            print(f"{issue.severity.upper()} [{issue.code}] {issue.path}: {issue.message}")
        if result_path:
            labels = {
                "emit_external": "外发版",
                "approve_letter": "已批准内部稿",
                "review_letter_facts": "已完成客户信事实复核",
                "approve_leader": "已批准人物研究",
                "approve_internal": "已批准内部检索",
                "approve_strategy": "已批准交流策略",
                "approve_briefing": "已批准会前速览",
                "begin_letter_revision": "客户信修订工作稿",
                "mark_ready": "已完成就绪审批的综合报告",
            }
            label = labels.get(operation or "", "结果")
            print(f"{label}：{result_path}")
        print(f"校验完成：{len(documents)}个成果，{errors}个错误，{warnings}个警告。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
