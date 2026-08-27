#!/usr/bin/env python3
"""Safely initialize or resume a discovery-call v2.5 workspace."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from capability_receipt import CapabilityReceiptError, verify_capability_receipt
except ModuleNotFoundError:
    _capability_path = Path(__file__).with_name("capability_receipt.py")
    _capability_spec = importlib.util.spec_from_file_location("capability_receipt", _capability_path)
    if _capability_spec is None or _capability_spec.loader is None:
        raise RuntimeError(f"无法加载能力收据验证模块：{_capability_path}")
    _capability_module = importlib.util.module_from_spec(_capability_spec)
    sys.modules["capability_receipt"] = _capability_module
    _capability_spec.loader.exec_module(_capability_module)
    CapabilityReceiptError = _capability_module.CapabilityReceiptError
    verify_capability_receipt = _capability_module.verify_capability_receipt
from runtime_tx import (
    MANIFEST_REL,
    CASMismatch,
    RecoveryRequired,
    TxError,
    atomic_write_json,
    build_manifest,
    file_state,
    fsync_directory,
    load_manifest,
    manifest_state,
    normalize_task_timezone,
    output_root_lock,
    recover_transaction,
    transactional_commit,
    task_date_at,
    unfinished_transaction,
    verify_manifest_artifacts,
    workspace_lock,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = SKILL_ROOT / "assets"
BUSINESS_MODES_FILE = SKILL_ROOT / "config" / "business-modes.json"
SCHEMA = "discovery-call-output/v2.5"
INVALID_SAFE_CHARS = re.compile(r'[<>:"/\\|?*#%()\[\]\x00-\x1f\x7f]+')
WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
CONTEXT_RE = re.compile(r"^dcx-\d{8}-[A-Za-z0-9]{8}$")
RUN_RE = re.compile(r"^dcr-\d{8}T\d{6}-[A-Za-z0-9]{4}$")
MODULE_CHOICES = {"institution", "leader", "internal", "strategy", "letter"}
MODULE_STATUSES = {"not_called", "queued", "running", "partial", "completed", "blocked"}
TERMINAL_STATUSES = {"partial", "completed", "blocked"}
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
ROUTES = {"research_only", "visit_prep", "strategy", "letter", "refresh"}
CONTENT_VERSION_RE = re.compile(r"^[1-9][0-9]*$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{3,128}$")
COMMON_REQUIRED_FIELDS = {
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
SUMMARY_SYNC_STATUSES = {"not_applicable", "pending", "synced", "out_of_sync"}
DOWNSTREAM_INVALIDATIONS = {"none", "stale", "invalidated"}
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
STRATEGY_CONTEXT_FIELDS = {"target_contact_level", "visit_objective", "minimum_next_step"}
INTERNAL_LETTER_FIELDS = APPROVAL_FIELDS | LETTER_CONTEXT_FIELDS | {"external_output_required"}
EXTERNAL_LINEAGE_FIELDS = APPROVAL_FIELDS | {"source_internal_content_version"}

TYPE_FOR_MODULE = {
    "institution": "institution_research",
    "leader": "leader_research",
    "internal": "internal_retrieval",
    "strategy": "visit_strategy",
    "letter": "customer_letter_internal",
}
TEMPLATES = {
    "comprehensive_report": "comprehensive-report-template.md",
    "institution_research": "institution-research-report-template.md",
    "leader_research": "leader-research-report-template.md",
    "internal_retrieval": "internal-retrieval-report-template.md",
    "visit_strategy": "visit-strategy-report-template.md",
    "customer_letter_internal": "customer-letter-output-template.md",
    "briefing_delivery": "briefing-template.md",
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
RUN_ARTIFACT_ORDER = (
    "institution",
    "leader",
    "internal",
    "strategy",
    "briefing",
    "letter",
    "external_letter",
)
MODE_LABELS = {"quick": "快速版", "standard": "标准版", "deep": "深度版"}
DEFAULT_REVIEW_STATUS = {
    "institution_research": "not_required",
    "leader_research": "not_started",
    "internal_retrieval": "not_started",
    "visit_strategy": "not_started",
    "customer_letter_internal": "not_started",
    "briefing_delivery": "not_started",
}


def _load_preflight_module():
    try:
        import preflight_intake as module

        return module
    except ModuleNotFoundError:
        path = Path(__file__).with_name("preflight_intake.py")
        spec = importlib.util.spec_from_file_location("preflight_intake", path)
        if spec is None or spec.loader is None:
            raise InitError(f"无法加载intake预检模块：{path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["preflight_intake"] = module
        spec.loader.exec_module(module)
        return module


PREFLIGHT = _load_preflight_module()


class InitError(RuntimeError):
    """Safe, user-actionable initialization failure."""


def require_ready_intake(args: argparse.Namespace) -> dict[str, object] | None:
    """Recompute the intake gate before any output-root write or lock."""
    if not args.business_mode:
        raise InitError(
            "新建或续建必须显式使用--business-mode并提供同一份--intake-input；"
            "旧--route/--mode仅可作为业务模式派生后的兼容参数。"
        )
    if not args.intake_input:
        raise InitError("使用--business-mode时必须提供--intake-input，并先完成输入消歧。")
    try:
        payload = PREFLIGHT.load_payload(args.intake_input)
        result = PREFLIGHT.evaluate_intake(payload, now=now_utc())
    except PREFLIGHT.PreflightError as exc:
        raise InitError(f"intake预检无效：{exc}") from exc
    if result.get("business_mode") != args.business_mode:
        raise InitError("intake预检business_mode与--business-mode不一致。")
    if result.get("status") != "ready" or result.get("safe_to_initialize_or_search") is not True:
        questions = [
            str(item.get("question", ""))
            for item in result.get("questions", [])
            if isinstance(item, dict) and item.get("question")
        ]
        detail = "；".join(questions) or "存在未消解的关键输入冲突或缺失。"
        raise InitError(f"intake_preflight_blocked：{detail}")
    selected = result.get("selected_values", {})
    customer = selected.get("customer_name", {}) if isinstance(selected, dict) else {}
    customer_values = customer.get("values", []) if isinstance(customer, dict) else []
    normalized_customer = normalize_customer_name(args.customer_name)
    if customer_values != [normalized_customer]:
        raise InitError("intake预检中的唯一客户主体与命令行customer_name不一致。")
    scope = selected.get("organization_scope", {}) if isinstance(selected, dict) else {}
    scope_values = scope.get("values", []) if isinstance(scope, dict) else []
    if len(scope_values) != 1 or not isinstance(scope_values[0], str):
        raise InitError("intake预检未形成唯一organization_scope。")
    if args.organization_scope and normalize_metadata_text(
        args.organization_scope, "--organization-scope"
    ) != scope_values[0]:
        raise InitError("intake预检中的organization_scope与命令行不一致。")
    args.organization_scope = scope_values[0]
    for field in (
        "visit_objective",
        "minimum_next_step",
        "strategic_question",
        "planning_horizon",
        "strategy_variant",
        "recipient_identity",
        "recipient_role",
        "letter_scenario",
        "letter_purpose",
        "expected_action",
        "signer",
        "delivery_channel",
    ):
        record = selected.get(field, {}) if isinstance(selected, dict) else {}
        values = record.get("values", []) if isinstance(record, dict) else []
        if len(values) == 1 and isinstance(values[0], str):
            supplied = getattr(args, field, None)
            if supplied and normalize_metadata_text(supplied, f"--{field.replace('_', '-')}") != values[0]:
                raise InitError(f"intake预检中的{field}与命令行不一致。")
            setattr(args, field, values[0])
    project_record = selected.get("project_id", {}) if isinstance(selected, dict) else {}
    project_values = project_record.get("values", []) if isinstance(project_record, dict) else []
    if project_record:
        if args.project_id and project_values != [args.project_id]:
            raise InitError("intake预检中的project_id与命令行--project-id不一致。")
        if len(project_values) == 1 and isinstance(project_values[0], str):
            args.project_id = args.project_id or project_values[0]
    elif args.project_id:
        raise InitError("--project-id必须先写入同一份intake并通过预检。")
    target_values: list[str] = []
    for field in ("target_contact_level", "target_role", "target_person"):
        record = selected.get(field, {}) if isinstance(selected, dict) else {}
        values = record.get("values", []) if isinstance(record, dict) else []
        if len(values) == 1 and isinstance(values[0], str):
            target_values = values
            break
    if target_values:
        if args.target_contact_level and normalize_metadata_text(
            args.target_contact_level, "--target-contact-level"
        ) != target_values[0]:
            raise InitError("intake预检中的拜访对象层级/角色与命令行不一致。")
        args.target_contact_level = target_values[0]
    return {
        "gate_id": result["gate_id"],
        "input_sha256": result["input_sha256"],
        "business_mode": result["business_mode"],
        "evaluated_at": result["evaluated_at"],
        "expires_at": result["expires_at"],
    }


def has_extra_frontmatter_block(body: str) -> bool:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    delimiters: list[int] = []
    fence_char = ""
    fence_length = 0
    for index, line in enumerate(lines):
        fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char, fence_length = marker[0], len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_length:
                fence_char, fence_length = "", 0
                continue
        if not fence_char and re.fullmatch(r"---[ \t]*", line):
            delimiters.append(index)
    for left, right in zip(delimiters, delimiters[1:]):
        if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:\s*.*", line) for line in lines[left + 1 : right]):
            return True
    return False


def load_business_profiles() -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(BUSINESS_MODES_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InitError(f"无法读取业务模式配置{BUSINESS_MODES_FILE}：{exc}") from exc
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict):
        raise InitError("business-modes.json缺少profiles对象。")
    required = {"briefing", "standard_visit", "strategic_account", "letter"}
    if not required <= profiles.keys():
        raise InitError("business-modes.json缺少业务模式：" + ", ".join(sorted(required - profiles.keys())))
    return profiles


def configured_module_values(values: list[str] | None, include_strategy: bool, include_letter: bool) -> set[str]:
    selected: set[str] = set()
    for value in values or []:
        selected.update(part.strip() for part in value.split(",") if part.strip())
    if include_strategy:
        selected.add("strategy")
    if include_letter:
        selected.add("letter")
    unknown = sorted(selected - MODULE_CHOICES)
    if unknown:
        raise InitError("未知模块：" + ", ".join(unknown))
    return selected


def modules_for_business_mode(args: argparse.Namespace, profile: dict[str, object]) -> list[str]:
    required = profile.get("modules")
    optional = profile.get("optional_modules", [])
    if not isinstance(required, list) or not all(value in MODULE_CHOICES for value in required):
        raise InitError("业务模式配置中的modules无效。")
    if not isinstance(optional, list) or not all(value in MODULE_CHOICES for value in optional):
        raise InitError("业务模式配置中的optional_modules无效。")
    explicit = configured_module_values(args.modules, args.include_strategy, args.include_letter)
    invalid = explicit - set(required) - set(optional)
    if invalid:
        raise InitError("本业务模式不允许加选模块：" + ", ".join(sorted(invalid)))
    selected = set(required) | explicit
    return [name for name in TYPE_FOR_MODULE if name in selected]


def infer_business_mode(route: str, depth: str) -> str:
    return {
        ("visit_prep", "quick"): "briefing",
        ("visit_prep", "standard"): "standard_visit",
        ("strategy", "deep"): "strategic_account",
        ("letter", "standard"): "letter",
    }.get((route, depth), "")


def parse_identifier_list(values: list[str] | None, label: str) -> list[str]:
    selected: list[str] = []
    for raw in values or []:
        for value in (part.strip() for part in raw.split(",")):
            if not value:
                continue
            if not IDENTIFIER_RE.fullmatch(value):
                raise InitError(f"{label}只能包含字母、数字、点、下划线和连字符。")
            if value not in selected:
                selected.append(value)
    return selected


def parse_text_list(values: list[str] | None, label: str) -> list[str]:
    selected: list[str] = []
    for raw in values or []:
        for value in (part.strip() for part in raw.split(",")):
            if not value:
                continue
            normalized = normalize_metadata_text(value, label, max_length=300)
            if normalized not in selected:
                selected.append(normalized)
    return selected


def validate_authorization_expiry(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InitError("--authorization-expires-at必须为带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise InitError("--authorization-expires-at必须包含时区。")
    if parsed <= datetime.now(timezone.utc):
        raise InitError("--authorization-expires-at已经过期。")
    return parsed.isoformat().replace("+00:00", "Z")


def inject_runtime_frontmatter(text: str, values: dict[str, str]) -> str:
    return replace_frontmatter(text, values)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def normalize_customer_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        raise InitError("客户名称不能为空。")
    if len(value) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InitError("客户名称不能超过200字符或包含控制字符。")
    return value


def normalize_metadata_text(value: str, label: str, *, max_length: int = 200) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    if not value:
        raise InitError(f"{label}不能为空。")
    if len(value) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InitError(f"{label}过长或包含控制字符。")
    return value


def validate_evidence_cutoff(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InitError("--evidence-cutoff-date 必须严格为 YYYY-MM-DD。")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InitError("--evidence-cutoff-date 必须为 YYYY-MM-DD。") from exc
    return parsed.strftime("%Y-%m-%d")


def validated_task_timezone(name: str) -> str:
    try:
        normalized = normalize_task_timezone(name)
    except TxError as exc:
        raise InitError("--task-timezone 必须是有效IANA时区，例如Asia/Shanghai。") from exc
    if normalized is None:  # Defensive: CLI only calls this for a supplied value.
        raise InitError("--task-timezone 必须是有效IANA时区，例如Asia/Shanghai。")
    return normalized


def local_date_for_timezone(name: str, *, instant: datetime | None = None) -> str:
    normalized = validated_task_timezone(name)
    try:
        return task_date_at(instant or now_utc(), normalized).isoformat()
    except TxError as exc:
        raise InitError("无法按--task-timezone计算任务日期。") from exc


def validate_cutoff_not_future(value: str, task_timezone: str | None, *, instant: datetime) -> str:
    """Validate a date against the persisted task calendar or legacy date-only envelope."""
    normalized = validate_evidence_cutoff(value)
    cutoff = datetime.strptime(normalized, "%Y-%m-%d").date()
    try:
        limit = (
            task_date_at(instant, task_timezone)
            if task_timezone is not None
            else instant.astimezone(timezone.utc).date() + timedelta(days=1)
        )
    except TxError as exc:
        raise InitError("无法确定信息截止日期的时区基准。") from exc
    if cutoff > limit:
        basis = f"任务时区{task_timezone}" if task_timezone else "未指定任务时区的兼容民用日窗口"
        raise InitError(f"--evidence-cutoff-date不得晚于{basis}当前日期{limit.isoformat()}。")
    return normalized


def validate_content_version(value: str) -> str:
    if not CONTENT_VERSION_RE.fullmatch(value):
        raise InitError("--content-version 必须为正整数。")
    return value


def increment_content_version(value: str) -> str:
    if not CONTENT_VERSION_RE.fullmatch(value):
        raise InitError("现有综合报告content_version不是正整数，无法安全续建。")
    return str(int(value) + 1)


def normalize_safe_component(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = INVALID_SAFE_CHARS.sub("-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip(" .-")
    if not value:
        value = "未命名客户"
    value = value[:48].rstrip(" .-") or "未命名客户"
    if WINDOWS_RESERVED.fullmatch(value):
        value = f"客户-{value}"
    return value[:48].rstrip(" .-")


def explicit_safe_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or ".." in normalized
        or INVALID_SAFE_CHARS.search(normalized)
        or Path(normalized).name != normalized
    ):
        raise InitError("--safe-name 必须是无路径穿越、无非法字符的单一文件名组件。")
    normalized = normalized.strip(" .-")
    if not normalized or len(normalized) > 48:
        raise InitError("--safe-name 清理后须为1—48个字符。")
    if WINDOWS_RESERVED.fullmatch(normalized):
        raise InitError("--safe-name 使用了系统保留名；请改用规范化后的客户名称。")
    canonical = normalize_safe_component(normalized)
    if normalized != canonical:
        raise InitError(f"--safe-name 不是规范形式；请使用：{canonical}")
    return canonical


def customer_id_for(customer_name: str) -> str:
    return "cust-" + hashlib.sha256(customer_name.encode("utf-8")).hexdigest()[:12]


def new_context_id(timestamp: datetime) -> str:
    return f"dcx-{timestamp:%Y%m%d}-{uuid.uuid4().hex[:8]}"


def new_run_id(timestamp: datetime) -> str:
    return f"dcr-{timestamp:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:4]}"


def context_short(context_id: str) -> str:
    if not CONTEXT_RE.fullmatch(context_id):
        raise InitError("context_id 必须符合 dcx-YYYYMMDD-8chars。")
    try:
        datetime.strptime(context_id[4:12], "%Y%m%d")
    except ValueError as exc:
        raise InitError("context_id中的日期无效。") from exc
    return context_id.rsplit("-", 1)[1]


def workspace_path(output_root: Path, safe_name: str, context_id: str) -> Path:
    expanded_root = output_root.expanduser()
    if expanded_root.is_symlink():
        raise InitError("--output-root 不得为符号链接。")
    root = expanded_root.resolve()
    target = (root / f"客户研究-{safe_name}-{context_short(context_id)}").resolve()
    if target.parent != root:
        raise InitError("工作目录解析到输出根目录之外，已拒绝。")
    return target


def context_id_candidates(output_root: Path, context_id: str) -> list[Path]:
    root = output_root.expanduser().resolve()
    short = context_short(context_id)
    if not root.is_dir():
        return []
    matches: set[Path] = set()
    for path in root.iterdir():
        if not path.is_dir() or path.is_symlink() or path.resolve().parent != root:
            continue
        if path.name.endswith(f"-{short}"):
            matches.add(path.resolve())
            continue
        manifest_path = path / MANIFEST_REL
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("context_id") == context_id:
                matches.add(path.resolve())
    return sorted(matches)


def unique_new_context_id(output_root: Path, requested: str | None, timestamp: datetime) -> str:
    if requested:
        if context_id_candidates(output_root, requested):
            raise InitError(f"context_id已在输出根目录使用：{requested}")
        return requested
    for _ in range(32):
        candidate = new_context_id(timestamp)
        if not context_id_candidates(output_root, candidate):
            return candidate
    raise InitError("连续生成的context_id发生冲突；请稍后重试。")


def find_resume_workspace(output_root: Path, safe_name: str, context_id: str | None) -> Path:
    expanded_root = output_root.expanduser()
    if expanded_root.is_symlink():
        raise InitError("--output-root 不得为符号链接。")
    root = expanded_root.resolve()
    if context_id:
        short = context_short(context_id)
        candidates = sorted(
            path.resolve()
            for path in root.glob(f"客户研究-*-{short}")
            if path.is_dir() and not path.is_symlink() and path.resolve().parent == root
        ) if root.is_dir() else []
        if not candidates:
            raise InitError(f"找不到指定 context_id 的工作目录：{context_id}")
        if len(candidates) > 1:
            raise InitError(f"context_id短码{short}匹配多个目录，需人工消歧。")
        return candidates[0]
    prefix = f"客户研究-{safe_name}-"
    candidates = sorted(
        path.resolve()
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and path.name.startswith(prefix) and path.resolve().parent == root
    ) if root.is_dir() else []
    if not candidates:
        raise InitError("未找到可续建工作目录；请检查 --output-root/--safe-name。")
    if len(candidates) > 1:
        raise InitError("同客户存在多个项目；续建时必须用 --context-id 明确选择。")
    return candidates[0]


def parse_modules(
    values: list[str] | None,
    include_strategy: bool,
    include_letter: bool,
    *,
    defaults: list[str] | None = None,
) -> list[str]:
    selected: set[str] = set()
    for value in values if values is not None else (defaults if defaults is not None else ["institution"]):
        selected.update(part.strip() for part in value.split(",") if part.strip())
    if include_strategy:
        selected.add("strategy")
    if include_letter:
        selected.add("letter")
    unknown = sorted(selected - MODULE_CHOICES)
    if unknown:
        raise InitError("未知模块：" + ", ".join(unknown))
    if not selected:
        raise InitError("至少选择一个模块。")
    return [name for name in TYPE_FOR_MODULE if name in selected]


def parse_refresh_modules(values: list[str] | None) -> set[str]:
    selected: set[str] = set()
    for value in values or []:
        selected.update(part.strip() for part in value.split(",") if part.strip())
    allowed = {"institution", "leader", "internal"}
    unknown = sorted(selected - allowed)
    if unknown:
        raise InitError("--refresh-modules只允许institution、leader、internal：" + ", ".join(unknown))
    return selected


def validate_refresh_modules(
    refresh_modules: set[str],
    modules: list[str],
    *,
    route: str,
    resume: bool,
    existing_types: set[str] | None = None,
) -> None:
    if not refresh_modules:
        return
    if not resume or route not in {"visit_prep", "strategy", "letter"}:
        raise InitError("--refresh-modules仅用于续建的visit_prep/strategy/letter组合路由。")
    if not refresh_modules <= set(modules):
        raise InitError("--refresh-modules中的研究模块必须同时列入--modules。")
    if existing_types is not None:
        missing = sorted(
            module for module in refresh_modules if TYPE_FOR_MODULE[module] not in existing_types
        )
        if missing:
            raise InitError("--refresh-modules只能更新既有研究成果；缺少：" + ", ".join(missing))


def validate_route_modules(route: str, modules: list[str], *, resume: bool) -> None:
    selected = set(modules)
    required = {
        "visit_prep": "strategy",
        "strategy": "strategy",
        "letter": "letter",
    }.get(route)
    if required and required not in modules:
        raise InitError(f"route={route}必须在--modules中包含{required}。")
    if route == "research_only" and ({"strategy", "letter"} & selected):
        raise InitError("research_only不能选择strategy/letter；请使用对应主路由。")
    if "letter" in selected and route != "letter":
        raise InitError("选择letter时主路由必须为letter，以执行最高外发门禁。")
    if route == "refresh":
        if not resume:
            raise InitError("refresh只能续建既有上下文；新任务请使用research_only或visit_prep。")
        if {"strategy", "letter"} & selected:
            raise InitError("refresh只刷新研究模块；需要策略或客户信时请使用strategy/letter主路由。")
    if route in {"visit_prep", "strategy", "letter"} and not (
        {"institution", "leader", "internal"} & selected
    ):
        phase = "新建" if not resume else "续建"
        raise InitError(f"{phase}route={route}至少把一个研究模块列为本轮selected，作为claim台账载体或复用依赖。")


def validate_template_assets(modules: list[str]) -> None:
    artifact_types = ["comprehensive_report"] + [TYPE_FOR_MODULE[name] for name in modules]
    for artifact_type in artifact_types:
        path = ASSET_ROOT / TEMPLATES[artifact_type]
        if not path.is_file():
            raise InitError(f"缺少模板：{path}")


def read_frontmatter(path: Path) -> dict[str, str]:
    if path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise InitError(f"拒绝读取符号链接或越界成果：{path}")
    text = path.read_text(encoding="utf-8")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise InitError(f"成果文件包含不允许的控制字符：{path}")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise InitError(f"缺少frontmatter：{path}")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise InitError(f"frontmatter未闭合：{path}") from exc
    data: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not match:
            raise InitError(f"frontmatter第{line_number}行不是受支持的扁平key: value：{path}")
        key, value = match.groups()
        if key in data:
            raise InitError(f"frontmatter字段{key}重复：{path}")
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise InitError(f"frontmatter字段{key}不是合法JSON字符串。") from exc
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        data[key] = value
    body = "\n".join(lines[end + 1 :])
    if has_extra_frontmatter_block(body):
        raise InitError(f"检测到第二个顶层frontmatter块：{path}")
    return data


def validate_existing_fields(path: Path, data: dict[str, str]) -> None:
    checks = (
        (data.get("module_status") in MODULE_STATUSES, "module_status无效"),
        (data.get("review_status") in REVIEW_STATUSES, "review_status无效"),
        (data.get("connector_status") in CONNECTOR_STATUSES, "connector_status无效"),
        (data.get("freshness_status") in FRESHNESS_STATUSES, "freshness_status无效"),
        (bool(CONTENT_VERSION_RE.fullmatch(data.get("content_version", ""))), "content_version无效"),
        (bool(RUN_RE.fullmatch(data.get("latest_run_id", ""))), "latest_run_id无效"),
        (bool(CONTEXT_RE.fullmatch(data.get("context_id", ""))), "context_id无效"),
        (bool(IDENTIFIER_RE.fullmatch(data.get("customer_id", ""))), "customer_id无效"),
        (normalize_safe_component(data.get("safe_name", "")) == data.get("safe_name"), "safe_name不是规范形式"),
    )
    for valid, message in checks:
        if not valid:
            raise InitError(f"现有成果{path.name}的{message}。")
    try:
        datetime.strptime(data.get("evidence_cutoff_date", ""), "%Y-%m-%d")
        parsed = datetime.fromisoformat(data.get("updated_at", "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise InitError(f"现有成果{path.name}的日期或带时区updated_at无效。") from exc


def audit_existing_workspace(workspace: Path, total_path: Path) -> dict[Path, dict[str, str]]:
    """Perform structural and identity checks before any resume write."""
    if workspace.is_symlink():
        raise InitError("续建工作目录不能是符号链接。")
    total_data = read_frontmatter(total_path)
    required_total = COMMON_REQUIRED_FIELDS | {"route", "depth", "workflow_stage"}
    missing_total = sorted(required_total - total_data.keys())
    if missing_total:
        raise InitError("现有综合报告缺少字段：" + ", ".join(missing_total))
    if total_data.get("schema") != SCHEMA or total_data.get("artifact_type") != "comprehensive_report":
        raise InitError("现有综合报告schema/artifact_type无效，需先迁移。")
    validate_existing_fields(total_path, total_data)
    identity = {
        key: total_data.get(key, "")
        for key in ("context_id", "customer_id", "customer_display_name", "organization_scope", "safe_name")
    }
    audited: dict[Path, dict[str, str]] = {total_path: total_data}
    for path in sorted(workspace.glob("*.md")):
        if path == total_path:
            continue
        if path.is_symlink() or path.resolve().parent != workspace.resolve():
            raise InitError(f"成果文件不得为符号链接或越出工作目录：{path}")
        if not any(path.name.endswith(suffix) for suffix in SUFFIXES.values()):
            continue
        data = read_frontmatter(path)
        missing = sorted(COMMON_REQUIRED_FIELDS - data.keys())
        if missing:
            raise InitError(f"现有成果{path.name}缺少字段：" + ", ".join(missing))
        if data.get("schema") != SCHEMA:
            raise InitError(f"现有成果{path.name}的schema无效，需先迁移。")
        validate_existing_fields(path, data)
        expected_type = next(
            (artifact_type for artifact_type, suffix in SUFFIXES.items() if path.name.endswith(suffix)),
            None,
        )
        if expected_type and data.get("artifact_type") != expected_type:
            raise InitError(f"现有成果{path.name}的artifact_type应为{expected_type}。")
        if expected_type == "customer_letter_internal" and not INTERNAL_LETTER_FIELDS <= data.keys():
            raise InitError(f"现有客户信内部稿{path.name}缺少v2.5.1审批字段，需先迁移。")
        if expected_type == "visit_strategy" and not STRATEGY_CONTEXT_FIELDS <= data.keys():
            raise InitError(f"现有交流策略{path.name}缺少v2.5.1执行上下文字段，需先迁移。")
        if expected_type == "customer_letter_external" and not EXTERNAL_LINEAGE_FIELDS <= data.keys():
            raise InitError(f"现有客户信外发版{path.name}缺少v2.5.1谱系字段，需先迁移。")
        for key, expected in identity.items():
            if data.get(key) != expected:
                raise InitError(f"现有成果{path.name}的{key}与综合报告不一致。")
        audited[path] = data
    return audited


def replace_frontmatter(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise InitError("总报告frontmatter未闭合，无法安全续建。") from exc
    seen: set[str] = set()
    for index in range(1, end):
        match = re.match(r"([A-Za-z_][A-Za-z0-9_-]*):", lines[index])
        if match and match.group(1) in updates:
            key = match.group(1)
            lines[index] = f"{key}: {json.dumps(updates[key], ensure_ascii=False)}"
            seen.add(key)
    for key in updates.keys() - seen:
        lines.insert(end, f"{key}: {json.dumps(updates[key], ensure_ascii=False)}")
        end += 1
    return "\n".join(lines).rstrip() + "\n"


def markdown_link(label: str, filename: str) -> str:
    return f"[{label}](./{filename})"


def markdown_cell(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).replace("|", r"\|").strip()


def split_markdown_cells(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", raw)]


def selected_callable_modules(text: str) -> list[str]:
    module_for_label = {
        "机构研究": "institution",
        "人物研究": "leader",
        "内部检索": "internal",
        "交流策略": "strategy",
        "客户信内部审核稿": "letter",
    }
    selected: set[str] = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = split_markdown_cells(line)
        if len(cells) >= 2 and cells[0] in module_for_label and cells[1] == "true":
            selected.add(module_for_label[cells[0]])
    return [name for name in TYPE_FOR_MODULE if name in selected]


def status_values(
    artifact_type: str,
    path: Path | None,
    *,
    selected_in_run: bool,
    run_action: str,
    frontmatter: dict[str, str] | None = None,
    summary_sync_status: str | None = None,
    key_claim_ids: str = "",
    downstream_invalidation: str = "none",
    gaps_blockers: str = "无",
) -> dict[str, str]:
    if path is None:
        return {
            "selected_in_run": "true" if selected_in_run else "false",
            "run_action": run_action,
            "module_status": "not_called",
            "review_status": "not_required",
            "connector_status": "not_applicable",
            "freshness_status": "current",
            "content_version": "",
            "latest_run_id": "",
            "updated_at": "",
            "summary_sync_status": "not_applicable",
            "key_claim_ids": "",
            "downstream_invalidation": "none",
            "gaps_blockers": "无",
            "link": "",
        }
    data = frontmatter if frontmatter is not None else read_frontmatter(path)
    values = {
        key: data.get(key, "")
        for key in (
            "module_status",
            "review_status",
            "connector_status",
            "freshness_status",
            "content_version",
            "latest_run_id",
            "updated_at",
        )
    }
    return {
        "selected_in_run": "true" if selected_in_run else "false",
        "run_action": run_action,
    } | values | {
        "summary_sync_status": summary_sync_status or ("pending" if run_action in {"created", "updated"} else "synced"),
        "key_claim_ids": key_claim_ids,
        "downstream_invalidation": downstream_invalidation,
        "gaps_blockers": gaps_blockers,
        "link": markdown_link(STATUS_LABELS[artifact_type], path.name),
    }


def status_row(label: str, values: dict[str, str]) -> str:
    return "| " + " | ".join(
        markdown_cell(value)
        for value in [
            label,
            values["selected_in_run"],
            values["run_action"],
            values["module_status"],
            values["review_status"],
            values["connector_status"],
            values["freshness_status"],
            values["content_version"],
            values["latest_run_id"],
            values["updated_at"],
            values["summary_sync_status"],
            values["key_claim_ids"],
            values["downstream_invalidation"],
            values["gaps_blockers"],
            values["link"],
        ]
    ) + " |"


def existing_status_extras(text: str, label: str) -> dict[str, str]:
    match = re.search(rf"^\|\s*{re.escape(label)}\s*\|(.*)$", text, flags=re.MULTILINE)
    if not match:
        return {}
    cells = [label] + split_markdown_cells("|" + match.group(1))
    if len(cells) < 15:
        return {}
    return {
        "summary_sync_status": cells[10],
        "key_claim_ids": cells[11],
        "downstream_invalidation": cells[12],
        "gaps_blockers": cells[13],
    }


def update_total_rows(
    text: str,
    paths: dict[str, Path],
    *,
    selected_types: set[str],
    created_types: set[str],
    planned_actions: dict[str, str],
    planned_frontmatter: dict[str, dict[str, str]] | None = None,
) -> str:
    planned_frontmatter = planned_frontmatter or {}
    for artifact_type, label in STATUS_LABELS.items():
        path = paths.get(artifact_type)
        selected = artifact_type in selected_types
        action = planned_actions.get(artifact_type, "not_called")
        extras = existing_status_extras(text, label)
        if artifact_type in created_types:
            extras = {
                "summary_sync_status": "pending",
                "key_claim_ids": "待提取",
                "downstream_invalidation": "none",
                "gaps_blockers": "待评估",
            }
        elif path is not None and not extras:
            extras = {
                "summary_sync_status": "out_of_sync",
                "key_claim_ids": "待提取",
                "downstream_invalidation": "none",
                "gaps_blockers": "待评估",
            }
        if action == "updated":
            extras["summary_sync_status"] = "pending"
        replacement = status_row(
            label,
            status_values(
                artifact_type,
                path,
                selected_in_run=selected,
                run_action=action,
                frontmatter=planned_frontmatter.get(artifact_type),
                **extras,
            ),
        )
        pattern = rf"^\|\s*{re.escape(label)}\s*\|.*$"
        occurrences = len(re.findall(pattern, text, flags=re.MULTILINE))
        if occurrences == 1:
            text = re.sub(pattern, lambda _: replacement, text, count=1, flags=re.MULTILINE)
        elif occurrences == 0 and artifact_type == "briefing_delivery":
            anchor = STATUS_LABELS["customer_letter_internal"]
            anchor_pattern = rf"^\|\s*{re.escape(anchor)}\s*\|.*$"
            if len(re.findall(anchor_pattern, text, flags=re.MULTILINE)) != 1:
                raise InitError("总报告缺少唯一客户信内部审核稿状态行，无法迁移会前速览登记。")
            text = re.sub(
                anchor_pattern,
                lambda match: replacement + "\n" + match.group(0),
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            raise InitError(f"总报告缺少或重复标准状态行：{label}")
    return text


def append_run_record(
    text: str,
    *,
    updated_at: str,
    content_version: str,
    latest_run_id: str,
    route: str,
    depth: str,
    objective: str,
    action_map: dict[str, str],
    target_cutoff: str,
    runtime_owner: str,
) -> str:
    if "## 9. 版本与同步记录" not in text:
        raise InitError("总报告缺少版本与同步记录章节，无法安全续建。")
    summary = run_summary(
        route=route,
        depth=depth,
        objective=objective,
        action_map=action_map,
        target_cutoff=target_cutoff,
    )
    owner = runtime_owner.replace("|", r"\|")
    row = f"| {updated_at} | {content_version} | {latest_run_id} | {summary} | {owner} |"
    lines = text.rstrip().splitlines()
    heading = next((index for index, line in enumerate(lines) if line.strip() == "## 9. 版本与同步记录"), None)
    if heading is None:
        raise InitError("总报告缺少版本与同步记录章节，无法追加运行记录。")
    section_end = next((index for index in range(heading + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    table_rows = [index for index in range(heading + 1, section_end) if lines[index].lstrip().startswith("|")]
    if len(table_rows) < 3:
        raise InitError("版本与同步记录表损坏，无法追加运行记录。")
    lines.insert(table_rows[-1] + 1, row)
    return "\n".join(lines).rstrip() + "\n"


def run_summary(
    *,
    route: str,
    depth: str,
    objective: str,
    action_map: dict[str, str],
    target_cutoff: str,
) -> str:
    clean_objective = re.sub(r"[;=|\r\n]+", " ", objective).strip()
    selected = [name for name in RUN_ARTIFACT_ORDER if action_map.get(name) != "not_called"]
    parts = [
        f"route={route}",
        f"depth={depth}",
        f"objective={clean_objective}",
        "selected_modules=" + (",".join(selected) or "none"),
    ]
    for action in ("created", "updated", "reused", "generated", "not_called"):
        names = [name for name in RUN_ARTIFACT_ORDER if action_map.get(name, "not_called") == action]
        parts.append(f"{action}=" + (",".join(names) or "none"))
    parts.append(f"target_evidence_cutoff_date={target_cutoff}")
    return "; ".join(parts)


REFRESH_HEADING = "## 8.1 刷新结果记录"
REFRESH_HEADER = "| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |"
REFRESH_SEPARATOR = "|---|---|---|---|---|---|"


def ensure_refresh_section(text: str) -> str:
    """Ensure the v2.5.1 refresh ledger exists without disturbing run history."""
    count = len(re.findall(r"^## 8\.1 刷新结果记录\s*$", text, flags=re.MULTILINE))
    if count > 1:
        raise InitError("综合报告包含重复的刷新结果记录章节。")
    if count == 0:
        marker = "## 9. 版本与同步记录"
        if marker not in text:
            raise InitError("总报告缺少版本与同步记录章节，无法补齐刷新台账。")
        block = f"{REFRESH_HEADING}\n\n{REFRESH_HEADER}\n{REFRESH_SEPARATOR}\n\n"
        text = text.replace(marker, block + marker, 1)
    lines = text.splitlines()
    heading = next((i for i, line in enumerate(lines) if line.strip() == REFRESH_HEADING), None)
    if heading is None:
        raise InitError("总报告缺少刷新结果记录章节。")
    section_end = next((i for i in range(heading + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[heading + 1 : section_end]
    if sum(line.strip() == REFRESH_HEADER for line in section) != 1 or sum(
        line.strip() == REFRESH_SEPARATOR for line in section
    ) != 1:
        raise InitError("刷新结果记录表头损坏，无法安全续建。")
    return text.rstrip() + "\n"


def append_refresh_record(text: str, latest_run_id: str) -> str:
    text = ensure_refresh_section(text)
    lines = text.rstrip().splitlines()
    heading = next(i for i, line in enumerate(lines) if line.strip() == REFRESH_HEADING)
    section_end = next((i for i in range(heading + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    table_rows = [i for i in range(heading + 1, section_end) if lines[i].lstrip().startswith("|")]
    if len(table_rows) < 2:
        raise InitError("刷新结果记录表损坏，无法追加本轮记录。")
    for index in table_rows[2:]:
        cells = split_markdown_cells(lines[index])
        if cells and cells[0] == latest_run_id:
            raise InitError("刷新结果记录已存在本轮run_id，拒绝重复追加。")
    row = f"| {latest_run_id} | pending | pending | pending | pending | pending |"
    lines.insert(table_rows[-1] + 1, row)
    return "\n".join(lines).rstrip() + "\n"


def assert_total_resumable(text: str) -> None:
    if "## 9. 版本与同步记录" not in text:
        raise InitError("总报告缺少版本与同步记录章节，无法安全续建。")
    for artifact_type, label in STATUS_LABELS.items():
        count = len(re.findall(rf"^\|\s*{re.escape(label)}\s*\|.*$", text, flags=re.MULTILINE))
        if artifact_type == "briefing_delivery" and count == 0:
            continue
        if count != 1:
            raise InitError(f"总报告状态行{label}缺失或重复，无法安全续建。")


def update_total_banner(text: str, *, mode: str, evidence_cutoff_date: str) -> str:
    modern_replacement = f"内部研究档位：{MODE_LABELS[mode]}｜信息截止：{evidence_cutoff_date}"
    updated, count = re.subn(
        r"内部研究档位：.*?｜信息截止：\d{4}-\d{2}-\d{2}",
        modern_replacement,
        text,
        count=1,
    )
    if count == 1:
        return updated
    replacement = f"> 研究档位：{MODE_LABELS[mode]}｜信息截止：{evidence_cutoff_date}｜保密级别：内部使用"
    updated, count = re.subn(
        r"^>\s*研究档位：.*?｜信息截止：.*?｜保密级别：内部使用[ \t]*$",
        replacement,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise InitError("总报告缺少标准研究档位/截止日横幅，无法安全续建。")
    return updated


def render_template(template_file: str, values: dict[str, str]) -> str:
    path = ASSET_ROOT / template_file
    if not path.is_file():
        raise InitError(f"缺少模板：{path}")
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.rstrip() + "\n"


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


def validate_workspace_postflight(workspace: Path) -> None:
    validator = Path(__file__).with_name("validate_outputs.py")
    result = subprocess.run(
        [sys.executable, str(validator), str(workspace), "--profile", "scaffold", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise InitError(f"提交后校验器未返回有效JSON：{detail or '无诊断'}") from exc
    errors = payload.get("errors")
    if result.returncode != 0 or not isinstance(errors, int) or errors:
        codes = [issue.get("code", "unknown") for issue in payload.get("issues", []) if issue.get("severity") == "error"]
        detail = ", ".join(codes[:8]) or (result.stderr.strip()[:500] if result.stderr else "unknown")
        raise InitError(f"提交后全量校验失败：{detail}")


def validate_runtime_postflight(workspace: Path) -> None:
    validate_workspace_postflight(workspace)
    manifest = load_manifest(workspace)
    assert manifest is not None
    verify_manifest_artifacts(workspace, manifest)


def collect_artifact_paths(workspace: Path, safe_name: str) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for artifact_type, suffix in SUFFIXES.items():
        path = workspace / f"{safe_name}{suffix}"
        if path.is_file():
            found[artifact_type] = path
    return found


def build_common(
    *,
    customer_name: str,
    safe_name: str,
    customer_id: str,
    context_id: str,
    latest_run_id: str,
    runtime_owner: str,
    mode: str,
    route: str,
    organization_scope: str,
    evidence_cutoff_date: str,
    timestamp: str,
    content_version: str,
) -> dict[str, str]:
    return {
        "context_id": context_id,
        "latest_run_id": latest_run_id,
        "customer_id": customer_id,
        "customer_display_name_yaml": json.dumps(customer_name, ensure_ascii=False),
        "organization_scope_yaml": json.dumps(organization_scope, ensure_ascii=False),
        "safe_name": safe_name,
        "客户中文规范名称": customer_name,
        "客户安全名称": safe_name,
        "runtime_owner": runtime_owner.replace("|", r"\|"),
        "runtime_owner_yaml": json.dumps(runtime_owner, ensure_ascii=False),
        "route": route,
        "depth": mode,
        "evidence_cutoff_date": evidence_cutoff_date,
        "updated_at": timestamp,
        "content_version": content_version,
        "freshness_status": "current",
        "YYYY-MM-DD": evidence_cutoff_date,
        "快速版/标准版/深度版": MODE_LABELS[mode],
        "external_output_required": "false",
        "approver_yaml": json.dumps("", ensure_ascii=False),
        "approved_at": "",
        "approved_content_version": "",
        "approved_body_sha256": "",
        "approved_context_sha256": "",
        "letter_scenario": "{{发送场景}}",
        "recipient_role": "{{收件对象与角色}}",
        "letter_purpose": "{{发信目的}}",
        "expected_action": "{{期望对方动作}}",
        "signer": "{{签署人}}",
        "delivery_channel": "{{发送渠道}}",
        "target_contact_level": "{{拜访对象与层级}}",
        "visit_objective": "{{拜访目标}}",
        "minimum_next_step": "{{最小推进动作}}",
    }


def _initialize_locked(
    args: argparse.Namespace,
    intake_preflight: dict[str, object] | None = None,
) -> dict[str, object]:
    customer_name = normalize_customer_name(args.customer_name)
    safe_name = explicit_safe_name(args.safe_name) if args.safe_name else normalize_safe_component(customer_name)
    requested_safe_name = safe_name if args.safe_name else None
    timestamp = now_utc()
    timestamp_iso = timestamp.isoformat().replace("+00:00", "Z")
    latest_run_id = args.run_id or new_run_id(timestamp)
    if not RUN_RE.fullmatch(latest_run_id):
        raise InitError("--run-id必须符合dcr-YYYYMMDDTHHMMSS-4chars。")
    requested_task_timezone = validated_task_timezone(args.task_timezone) if args.task_timezone else None
    default_cutoff = (
        local_date_for_timezone(requested_task_timezone, instant=timestamp)
        if requested_task_timezone
        else None
    )
    requested_customer_id = args.customer_id
    if requested_customer_id and not IDENTIFIER_RE.fullmatch(requested_customer_id):
        raise InitError("--customer-id 只能包含字母、数字、点、下划线和连字符。")
    requested_owner = (
        normalize_metadata_text(args.runtime_owner, "--runtime-owner", max_length=100)
        if args.runtime_owner
        else None
    )
    requested_scope = (
        normalize_metadata_text(args.organization_scope, "--organization-scope")
        if args.organization_scope
        else None
    )
    explicit_cutoff = (
        validate_evidence_cutoff(args.evidence_cutoff_date)
        if args.evidence_cutoff_date
        else None
    )
    objective = (
        normalize_metadata_text(args.run_objective, "--run-objective", max_length=300)
        if args.run_objective
        else ""
    )
    refresh_modules = parse_refresh_modules(args.refresh_modules)
    new_content_version = validate_content_version(args.content_version)
    requested_context = args.context_id
    profiles = load_business_profiles()
    selected_profile = profiles.get(args.business_mode) if args.business_mode else None
    if args.route == "refresh" and args.business_mode:
        raise InitError("refresh是续建后台路由，不能与--business-mode同时指定。")
    if args.route == "refresh" and not args.resume:
        raise InitError("refresh只能与--resume一起使用。")
    if args.internal_connector_status in {"connected", "no_hits"}:
        raise InitError(
            "init阶段禁止声明connected/no_hits；请通过commit_run.py提交候选成果及runtime/evidence-manifest.json连接审计。"
        )
    tenant_id = args.tenant_id or ""
    project_id = args.project_id or ""
    connector_id = args.internal_connector_id or ""
    for value, label in ((tenant_id, "--tenant-id"), (project_id, "--project-id"), (connector_id, "--internal-connector-id")):
        if value and not IDENTIFIER_RE.fullmatch(value):
            raise InitError(f"{label}只能包含字母、数字、点、下划线和连字符。")
    authorization_owner = (
        normalize_metadata_text(args.authorization_owner, "--authorization-owner", max_length=100)
        if args.authorization_owner else ""
    )
    authorization_purpose = (
        normalize_metadata_text(args.authorization_purpose, "--authorization-purpose", max_length=300)
        if args.authorization_purpose else ""
    )
    capability_receipt_id = args.capability_receipt_id or ""
    if capability_receipt_id and not IDENTIFIER_RE.fullmatch(capability_receipt_id):
        raise InitError("--capability-receipt-id只能包含字母、数字、点、下划线和连字符。")
    authorization_actor_id = args.authorization_actor_id or ""
    if authorization_actor_id and not IDENTIFIER_RE.fullmatch(authorization_actor_id):
        raise InitError("--authorization-actor-id只能包含字母、数字、点、下划线和连字符。")
    authorization_expires_at = (
        validate_authorization_expiry(args.authorization_expires_at)
        if args.authorization_expires_at else ""
    )
    allowed_project_ids = parse_identifier_list(args.allowed_project_ids, "--allowed-project-ids")
    authorized_roots = parse_text_list(args.authorized_root, "--authorized-root")
    allowed_dataset_aliases = parse_text_list(args.allowed_dataset_alias, "--allowed-dataset-alias")
    allowed_confidentiality = parse_text_list(args.allowed_confidentiality, "--allowed-confidentiality")
    existing_manifest: dict[str, object] | None = None
    baseline_states: dict[Path, dict[str, object]] = {}
    original_total_text: str | None = None
    audited: dict[Path, dict[str, str]] = {}
    if requested_context and not CONTEXT_RE.fullmatch(requested_context):
        raise InitError("--context-id 必须符合 dcx-YYYYMMDD-8chars。")

    if args.resume:
        workspace = find_resume_workspace(Path(args.output_root), safe_name, requested_context)
        total_candidates = list(workspace.glob(f"*{SUFFIXES['comprehensive_report']}"))
        if len(total_candidates) != 1:
            raise InitError("续建目录必须恰有一个综合报告。")
        total_path = total_candidates[0]
        audited = audit_existing_workspace(workspace, total_path)
        existing = audited[total_path]
        original_total_text = total_path.read_text(encoding="utf-8")
        assert_total_resumable(original_total_text)
        if not args.recover:
            validate_workspace_postflight(workspace)
        existing_manifest = load_manifest(workspace, required=False)
        existing_task_timezone = (
            normalize_task_timezone(existing_manifest.get("task_timezone"))
            if existing_manifest and "task_timezone" in existing_manifest
            else None
        )
        if (
            requested_task_timezone
            and existing_task_timezone
            and requested_task_timezone != existing_task_timezone
        ):
            raise InitError(
                "--task-timezone与既有上下文不一致；任务时区建立后不得在同一context中变更。"
            )
        task_timezone = requested_task_timezone or existing_task_timezone
        baseline_states = {
            path: file_state(path).as_dict()
            for path in workspace.glob("*.md")
            if path.is_file() and not path.is_symlink()
        }
        baseline_states[workspace / MANIFEST_REL] = file_state(workspace / MANIFEST_REL).as_dict()
        next_total_version = increment_content_version(existing.get("content_version", ""))
        context_id = existing.get("context_id", "")
        if not CONTEXT_RE.fullmatch(context_id):
            raise InitError("现有综合报告context_id无效。")
        if requested_context and context_id != requested_context:
            raise InitError("现有综合报告context_id与--context-id不一致。")
        safe_name = existing.get("safe_name", "")
        if requested_safe_name and requested_safe_name != safe_name:
            raise InitError("--safe-name 与现有上下文不一致。")
        customer_id = existing.get("customer_id", "")
        existing_name = existing.get("customer_display_name", "")
        if not existing_name or existing_name != customer_name:
            raise InitError("客户规范名称与现有上下文不一致；请使用原规范名称续建。")
        if requested_customer_id and requested_customer_id != customer_id:
            raise InitError("--customer-id 与现有上下文不一致。")
        organization_scope = existing.get("organization_scope", "")
        if not organization_scope:
            raise InitError("现有综合报告缺少organization_scope，需先迁移。")
        if requested_scope and requested_scope != organization_scope:
            raise InitError("--organization-scope 与现有上下文不一致。")
        manifest_business_mode = str((existing_manifest or {}).get("business_mode", ""))
        existing_business_mode = manifest_business_mode or existing.get("business_mode", "")
        if selected_profile:
            configured_route = str(selected_profile.get("route", ""))
            configured_depth = str(selected_profile.get("depth", ""))
            if args.route and args.route != configured_route:
                raise InitError("--route与--business-mode配置冲突。")
            if args.mode and args.mode != configured_depth:
                raise InitError("--mode与--business-mode配置冲突。")
            route, mode = configured_route, configured_depth
            business_mode = args.business_mode
        else:
            route = args.route or existing.get("route", "")
            mode = args.mode or existing.get("depth", "")
            business_mode = existing_business_mode or infer_business_mode(route, mode)
        if route not in ROUTES or mode not in MODE_LABELS:
            raise InitError("现有综合报告route/depth无效，需先迁移。")
        inherited_modules = selected_callable_modules(original_total_text)
        modules = (
            modules_for_business_mode(args, selected_profile)
            if selected_profile
            else parse_modules(args.modules, args.include_strategy, args.include_letter, defaults=inherited_modules)
        )
        validate_template_assets(modules)
        runtime_owner = requested_owner or existing.get("runtime_owner") or "待指定"
        if runtime_owner == "待指定":
            runtime_owner = "待确认"
        requested_cutoff = explicit_cutoff or existing.get("evidence_cutoff_date", "")
        if not requested_cutoff:
            raise InitError("现有综合报告evidence_cutoff_date无效。")
        requested_cutoff = validate_evidence_cutoff(requested_cutoff)
        total_cutoff = existing.get("evidence_cutoff_date", "")
        total_freshness = existing.get("freshness_status", "")
        if total_freshness not in FRESHNESS_STATUSES:
            raise InitError("现有综合报告freshness_status无效。")
        validate_route_modules(route, modules, resume=True)
        validate_refresh_modules(
            refresh_modules,
            modules,
            route=route,
            resume=True,
            existing_types={data.get("artifact_type", "") for data in audited.values()},
        )
        if route in {"visit_prep", "strategy", "letter"}:
            selected_research_types = {
                TYPE_FOR_MODULE[module]
                for module in modules
                if module in {"institution", "leader", "internal"}
            }
            refresh_types = {TYPE_FOR_MODULE[module] for module in refresh_modules}
            reusable_carriers = [
                data
                for data in audited.values()
                if data.get("artifact_type") in selected_research_types
                and (
                    (
                        data.get("module_status") == "completed"
                        and data.get("freshness_status") == "current"
                        and (
                            data.get("artifact_type") == "institution_research"
                            or data.get("review_status") in {"pending", "approved"}
                        )
                    )
                    or (
                        data.get("artifact_type") in refresh_types
                        and data.get("module_status") in TERMINAL_STATUSES
                    )
                )
                and data.get("organization_scope") == organization_scope
            ]
            if not reusable_carriers:
                raise InitError(
                    f"续建route={route}至少需要一个本轮选中的completed/current可复用研究成果，或用--refresh-modules显式计划更新既有终态研究成果。"
                )
        if workspace != workspace_path(Path(args.output_root), safe_name, context_id):
            raise InitError("目录名与frontmatter中的safe_name/context_id不一致。")
    else:
        if explicit_cutoff is None and default_cutoff is None:
            raise InitError("新建任务必须显式提供--task-timezone或--evidence-cutoff-date，避免跨时区日期偏差。")
        context_id = unique_new_context_id(Path(args.output_root), requested_context, timestamp)
        task_timezone = requested_task_timezone
        customer_id = requested_customer_id or customer_id_for(customer_name)
        organization_scope = requested_scope or customer_name
        if selected_profile:
            configured_route = str(selected_profile.get("route", ""))
            configured_depth = str(selected_profile.get("depth", ""))
            if args.route and args.route != configured_route:
                raise InitError("--route与--business-mode配置冲突。")
            if args.mode and args.mode != configured_depth:
                raise InitError("--mode与--business-mode配置冲突。")
            route, mode = configured_route, configured_depth
            business_mode = args.business_mode
        else:
            route = args.route or "research_only"
            mode = args.mode or "standard"
            business_mode = infer_business_mode(route, mode)
        runtime_owner = requested_owner or "待确认"
        requested_cutoff = explicit_cutoff or default_cutoff
        if requested_cutoff is None:  # Defensive: guarded above, keeps the type and invariant explicit.
            raise InitError("无法确定新建任务的信息截止日期。")
        total_cutoff = requested_cutoff
        total_freshness = "current"
        modules = (
            modules_for_business_mode(args, selected_profile)
            if selected_profile
            else parse_modules(args.modules, args.include_strategy, args.include_letter)
        )
        validate_template_assets(modules)
        validate_route_modules(route, modules, resume=False)
        validate_refresh_modules(refresh_modules, modules, route=route, resume=False)
        final_workspace = workspace_path(Path(args.output_root), safe_name, context_id)
        if final_workspace.exists():
            raise InitError("目标工作目录已存在；请用 --resume 或指定新的 --context-id。")

    requested_cutoff = validate_cutoff_not_future(
        requested_cutoff,
        task_timezone,
        instant=timestamp,
    )
    total_cutoff = validate_cutoff_not_future(
        total_cutoff,
        task_timezone,
        instant=timestamp,
    )

    inherited_authorization = (existing_manifest or {}).get("authorization", {})
    if not isinstance(inherited_authorization, dict):
        inherited_authorization = {}
    stable_pairs = (
        ("tenant_id", tenant_id),
        ("project_id", project_id),
    )
    for key, requested in stable_pairs:
        inherited = str(inherited_authorization.get(key, ""))
        if requested and inherited and requested != inherited:
            raise InitError(f"--{key.replace('_', '-')}与既有授权上下文不一致。")
    tenant_id = tenant_id or str(inherited_authorization.get("tenant_id", ""))
    project_id = project_id or str(inherited_authorization.get("project_id", ""))
    connector_id = connector_id or str(inherited_authorization.get("connector_id", ""))
    authorization_owner = authorization_owner or str(inherited_authorization.get("authorization_owner", ""))
    authorization_purpose = authorization_purpose or str(inherited_authorization.get("authorization_purpose", ""))
    # A capability receipt is bound to one run and must never be inherited into
    # a new run.  Stable scope may be inherited; authority must be re-issued.
    authorization_expires_at = authorization_expires_at or str(inherited_authorization.get("authorization_expires_at", ""))
    allowed_project_ids = allowed_project_ids or list(inherited_authorization.get("allowed_project_ids", []) or [])
    authorized_roots = authorized_roots or list(inherited_authorization.get("authorized_roots", []) or [])
    allowed_dataset_aliases = allowed_dataset_aliases or list(inherited_authorization.get("allowed_dataset_aliases", []) or [])
    allowed_confidentiality = allowed_confidentiality or list(inherited_authorization.get("allowed_confidentiality", []) or [])
    internal_selected = "internal" in modules
    effective_connector_status = args.internal_connector_status
    if args.resume and internal_selected and effective_connector_status == "not_configured":
        internal_existing = next(
            (data for data in audited.values() if data.get("artifact_type") == "internal_retrieval"),
            {},
        )
        effective_connector_status = internal_existing.get("connector_status", "not_configured")
    if effective_connector_status in {"connected", "no_hits"} and not internal_selected:
        raise InitError("connector_status=connected/no_hits时必须选择internal模块。")
    if internal_selected and effective_connector_status in {"connected", "no_hits"}:
        required_auth = {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "project_id": project_id,
            "authorization_owner": authorization_owner,
            "authorization_expires_at": authorization_expires_at,
        }
        missing = [key for key, value in required_auth.items() if not value]
        if missing:
            raise InitError("内部连接器connected缺少授权字段：" + ", ".join(missing))
        authorization_expires_at = validate_authorization_expiry(authorization_expires_at)
        if project_id not in allowed_project_ids:
            raise InitError("--allowed-project-ids必须包含--project-id。")
    receipt_audit: dict[str, object] = {
        "authorization_actor_id": authorization_actor_id,
        "capability_operation": "internal_read",
        "capability_receipt_verified": False,
        "capability_receipt_issuer": "",
        "capability_receipt_key_id": "",
        "capability_receipt_sha256": "",
        "capability_receipt_verified_at": "",
        "capability_receipt_expires_at": "",
    }
    if args.capability_receipt_file:
        if not internal_selected:
            raise InitError("--capability-receipt-file仅可用于选择了internal的run。")
        if not args.run_id:
            raise InitError("使用宿主能力收据时必须显式提供收据绑定的--run-id。")
        try:
            verified_receipt = verify_capability_receipt(
                args.capability_receipt_file,
                expected={
                    "receipt_id": capability_receipt_id,
                    "actor_id": authorization_actor_id,
                    "run_id": latest_run_id,
                    "connector_id": connector_id,
                    "operation": "internal_read",
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "project_id": project_id,
                    "allowed_project_ids": allowed_project_ids,
                    "authorization_owner": authorization_owner,
                    "authorization_expires_at": authorization_expires_at,
                    "authorized_roots": authorized_roots,
                    "allowed_dataset_aliases": allowed_dataset_aliases,
                    "allowed_confidentiality": allowed_confidentiality,
                    "authorization_purpose": authorization_purpose,
                },
                at=timestamp,
            )
        except CapabilityReceiptError as exc:
            raise InitError(f"capability_receipt_invalid：{exc}") from exc
        receipt_audit.update(verified_receipt.audit_fields())
    authorization = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "project_id": project_id,
        "connector_id": connector_id,
        "connector_status": effective_connector_status if internal_selected else "not_applicable",
        "authorization_owner": authorization_owner,
        "authorization_expires_at": authorization_expires_at,
        "allowed_project_ids": allowed_project_ids,
        "authorized_roots": authorized_roots,
        "allowed_dataset_aliases": allowed_dataset_aliases,
        "allowed_confidentiality": allowed_confidentiality,
        "authorization_purpose": authorization_purpose,
        "capability_receipt_id": capability_receipt_id,
        **receipt_audit,
    }
    # All intake and capability gates must finish before a new customer
    # workspace or staging directory is created.
    if not args.resume:
        staging_parent = Path(
            tempfile.mkdtemp(prefix=f".{final_workspace.name}.staging-", dir=final_workspace.parent)
        )
        workspace = staging_parent / final_workspace.name
        workspace.mkdir(parents=False, exist_ok=False)
        total_path = workspace / f"{safe_name}{SUFFIXES['comprehensive_report']}"
    runtime_frontmatter = {
        "business_mode": business_mode,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "authorization_owner": authorization_owner,
        "authorization_expires_at": authorization_expires_at,
        "ready_for_use": "false",
    }

    common = build_common(
        customer_name=customer_name,
        safe_name=safe_name,
        customer_id=customer_id,
        context_id=context_id,
        latest_run_id=latest_run_id,
        runtime_owner=runtime_owner,
        mode=mode,
        route=route,
        organization_scope=organization_scope,
        evidence_cutoff_date=requested_cutoff,
        timestamp=timestamp_iso,
        content_version=new_content_version,
    )
    common["会前速览/标准拜访包/战略客户包/一封信"] = (
        str(selected_profile.get("display_name", "")) if selected_profile else "未指定"
    )
    strategy_variant = args.strategy_variant or (
        "account_planning" if business_mode == "strategic_account" else "scheduled_visit"
    )
    if business_mode != "strategic_account" and strategy_variant != "scheduled_visit":
        raise InitError("只有strategic_account可使用account_planning；会前任务必须使用scheduled_visit。")
    common.update(
        {
            "target_contact_level": args.target_contact_level or "待确认",
            "visit_objective": args.visit_objective or "待确认",
            "minimum_next_step": args.minimum_next_step or "待确认",
            "strategic_question": args.strategic_question or "待确认",
            "planning_horizon": args.planning_horizon or "待确认",
            "letter_scenario": args.letter_scenario or "{{发送场景}}",
            "recipient_role": (
                "｜".join(
                    value
                    for value in (args.recipient_identity, args.recipient_role)
                    if value
                )
                or "{{收件对象与角色}}"
            ),
            "letter_purpose": args.letter_purpose or "{{发信目的}}",
            "expected_action": args.expected_action or "{{期望对方动作}}",
            "signer": args.signer or "{{签署人}}",
            "delivery_channel": args.delivery_channel or "{{发送渠道}}",
        }
    )
    created: list[str] = []
    created_types: set[str] = set()
    preserved: list[str] = []
    selected_types = [TYPE_FOR_MODULE[name] for name in modules]
    selected_status_types = set(selected_types)
    planned_text: dict[Path, str] = {}
    planned_frontmatter: dict[str, dict[str, str]] = {}
    paths = collect_artifact_paths(workspace, safe_name)
    for artifact_type in selected_types:
        path = workspace / f"{safe_name}{SUFFIXES[artifact_type]}"
        if path.exists():
            if not args.resume:
                raise InitError(f"拒绝覆盖现有成果：{path}")
            if not path.is_file() or path.is_symlink():
                raise InitError(f"成果路径不是普通文件：{path}")
            preserved.append(path.name)
            continue
        connector = effective_connector_status if artifact_type == "internal_retrieval" else "not_applicable"
        review = DEFAULT_REVIEW_STATUS[artifact_type]
        values = common | {
            "module_status": "queued",
            "review_status": review,
            "connector_status": connector,
        }
        template_file = (
            "account-strategy-report-template.md"
            if artifact_type == "visit_strategy" and strategy_variant == "account_planning"
            else TEMPLATES[artifact_type]
        )
        planned_text[path] = inject_runtime_frontmatter(
            render_template(template_file, values), runtime_frontmatter
        )
        planned_frontmatter[artifact_type] = {
            "schema": SCHEMA,
            "artifact_type": artifact_type,
            "context_id": context_id,
            "latest_run_id": latest_run_id,
            "customer_id": customer_id,
            "customer_display_name": customer_name,
            "organization_scope": organization_scope,
            "safe_name": safe_name,
            "module_status": "queued",
            "review_status": review,
            "connector_status": connector,
            "freshness_status": "current",
            "content_version": new_content_version,
            "evidence_cutoff_date": requested_cutoff,
            "updated_at": timestamp_iso,
            "runtime_owner": runtime_owner,
        } | runtime_frontmatter
        paths[artifact_type] = path
        created.append(path.name)
        created_types.add(artifact_type)

    if business_mode == "briefing":
        artifact_type = "briefing_delivery"
        selected_status_types.add(artifact_type)
        path = workspace / f"{safe_name}{SUFFIXES[artifact_type]}"
        if path.exists():
            if not args.resume:
                raise InitError(f"拒绝覆盖现有成果：{path}")
            if not path.is_file() or path.is_symlink():
                raise InitError(f"成果路径不是普通文件：{path}")
            preserved.append(path.name)
        else:
            values = common | {
                "module_status": "queued",
                "review_status": DEFAULT_REVIEW_STATUS[artifact_type],
                "connector_status": "not_applicable",
            }
            planned_text[path] = inject_runtime_frontmatter(
                render_template(TEMPLATES[artifact_type], values), runtime_frontmatter
            )
            planned_frontmatter[artifact_type] = {
                "schema": SCHEMA,
                "artifact_type": artifact_type,
                "context_id": context_id,
                "latest_run_id": latest_run_id,
                "customer_id": customer_id,
                "customer_display_name": customer_name,
                "organization_scope": organization_scope,
                "safe_name": safe_name,
                "module_status": "queued",
                "review_status": DEFAULT_REVIEW_STATUS[artifact_type],
                "connector_status": "not_applicable",
                "freshness_status": "current",
                "content_version": new_content_version,
                "evidence_cutoff_date": requested_cutoff,
                "updated_at": timestamp_iso,
                "runtime_owner": runtime_owner,
            } | runtime_frontmatter
            paths[artifact_type] = path
            created.append(path.name)
            created_types.add(artifact_type)

    if route in {"visit_prep", "strategy", "letter"} and not (
        {"institution_research", "leader_research", "internal_retrieval"} & paths.keys()
    ):
        raise InitError(f"route={route}缺少研究成果，无法为claim_id提供权威台账。")

    audited_by_type = {data.get("artifact_type", ""): data for data in audited.values()}
    action_map: dict[str, str] = {}
    for module, artifact_type in TYPE_FOR_MODULE.items():
        if artifact_type not in selected_types:
            action_map[module] = "not_called"
        elif artifact_type in created_types:
            action_map[module] = "created"
        elif not args.resume:
            action_map[module] = "created"
        elif module in refresh_modules:
            action_map[module] = "updated"
        elif module in {"institution", "leader", "internal"} and route in {"visit_prep", "strategy", "letter"}:
            existing_data = audited_by_type.get(artifact_type, {})
            action_map[module] = (
                "reused"
                if existing_data.get("freshness_status") == "current"
                and existing_data.get("module_status") in {"partial", "completed", "blocked"}
                else "updated"
            )
        else:
            action_map[module] = "updated"
    action_map["briefing"] = (
        "created"
        if "briefing_delivery" in created_types
        else "updated"
        if business_mode == "briefing"
        else "not_called"
    )
    action_map["external_letter"] = "not_called"
    planned_actions = {
        TYPE_FOR_MODULE[module]: action
        for module, action in action_map.items()
        if module in TYPE_FOR_MODULE
    } | {
        "briefing_delivery": action_map["briefing"],
        "customer_letter_external": "not_called",
    }
    common["run_summary"] = run_summary(
        route=route,
        depth=mode,
        objective=objective or f"{route}运行",
        action_map=action_map,
        target_cutoff=requested_cutoff,
    )
    if args.resume:
        total_text = total_path.read_text(encoding="utf-8")
        total_text = ensure_refresh_section(total_text)
        total_text = replace_frontmatter(
            total_text,
            {
                "latest_run_id": latest_run_id,
                "module_status": "running",
                "review_status": "not_required",
                "connector_status": "not_applicable",
                "freshness_status": total_freshness,
                "content_version": next_total_version,
                "route": route,
                "depth": mode,
                "organization_scope": organization_scope,
                "evidence_cutoff_date": total_cutoff,
                "updated_at": timestamp_iso,
                "runtime_owner": runtime_owner,
                "workflow_stage": "planning",
            } | runtime_frontmatter,
        )
        total_text = update_total_banner(total_text, mode=mode, evidence_cutoff_date=total_cutoff)
        total_text = update_total_rows(
            total_text,
            paths,
            selected_types=selected_status_types,
            created_types=created_types,
            planned_actions=planned_actions,
            planned_frontmatter=planned_frontmatter,
        )
        if route == "refresh":
            total_text = append_refresh_record(total_text, latest_run_id)
        total_text = append_run_record(
            total_text,
            updated_at=timestamp_iso,
            content_version=next_total_version,
            latest_run_id=latest_run_id,
            route=route,
            depth=mode,
            objective=objective or f"{route}运行",
            action_map=action_map,
            target_cutoff=requested_cutoff,
            runtime_owner=runtime_owner,
        )
    else:
        empty_status = {
            "selected_in_run": "false",
            "run_action": "not_called",
            "module_status": "not_called",
            "review_status": "not_required",
            "connector_status": "not_applicable",
            "freshness_status": "current",
            "content_version": "",
            "latest_run_id": "",
            "updated_at": "",
            "summary_sync_status": "not_applicable",
            "key_claim_ids": "",
            "downstream_invalidation": "none",
            "gaps_blockers": "无",
            "link": "",
        }
        values = common | {
            "module_status": "running",
            "review_status": "not_required",
            "connector_status": "not_applicable",
            "freshness_status": total_freshness,
            "evidence_cutoff_date": total_cutoff,
            "workflow_stage": "planning",
        }
        for artifact_type, stem in (
            ("institution_research", "institution"),
            ("leader_research", "leader"),
            ("internal_retrieval", "internal"),
            ("visit_strategy", "strategy"),
            ("briefing_delivery", "briefing"),
            ("customer_letter_internal", "letter"),
            ("customer_letter_external", "external_letter"),
        ):
            path = paths.get(artifact_type)
            selected = artifact_type in selected_status_types
            status = (
                status_values(
                    artifact_type,
                    path,
                    selected_in_run=selected,
                    run_action="created" if artifact_type in created_types else "not_called",
                    frontmatter=planned_frontmatter.get(artifact_type),
                    summary_sync_status="pending" if artifact_type in created_types else "not_applicable",
                    key_claim_ids="待提取" if artifact_type in created_types else "",
                    downstream_invalidation="none",
                    gaps_blockers="待评估" if artifact_type in created_types else "无",
                )
                if path
                else empty_status
            )
            values.update(
                {
                    f"{stem}_selected_in_run": status["selected_in_run"],
                    f"{stem}_run_action": status["run_action"],
                    f"{stem}_status": status["module_status"],
                    f"{stem}_review_status": status["review_status"],
                    f"{stem}_connector_status": status["connector_status"],
                    f"{stem}_freshness_status": status["freshness_status"],
                    f"{stem}_content_version": status["content_version"],
                    f"{stem}_latest_run_id": status["latest_run_id"],
                    f"{stem}_updated_at": status["updated_at"],
                    f"{stem}_summary_sync_status": status["summary_sync_status"],
                    f"{stem}_key_claim_ids": status["key_claim_ids"],
                    f"{stem}_downstream_invalidation": status["downstream_invalidation"],
                    f"{stem}_gaps_blockers": status["gaps_blockers"],
                    f"{stem}_link": status["link"],
                }
            )
        total_text = inject_runtime_frontmatter(
            ensure_refresh_section(render_template(TEMPLATES["comprehensive_report"], values)),
            runtime_frontmatter,
        )
        created.insert(0, total_path.name)

    total_version = next_total_version if args.resume else new_content_version
    planned_bytes = {path: text.encode("utf-8") for path, text in planned_text.items()}
    planned_bytes[total_path] = total_text.encode("utf-8")
    previous_sequence = int((existing_manifest or {}).get("transaction_sequence", 0))
    manifest = build_manifest(
        workspace,
        identity={
            "context_id": context_id,
            "customer_id": customer_id,
            "customer_display_name": customer_name,
            "organization_scope": organization_scope,
        },
        business_mode=business_mode,
        route=route,
        depth=mode,
        task_timezone=task_timezone,
        latest_run_id=latest_run_id,
        content_version=total_version,
        stage="planning",
        ready_for_use=False,
        selected_modules=modules,
        authorization=authorization,
        transaction_sequence=previous_sequence + 1,
        intake_preflight=intake_preflight,
        overlay=planned_bytes,
    )
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if args.resume:
        expected = dict(baseline_states)
        for path in planned_bytes:
            expected.setdefault(path, file_state(path).as_dict())
        expected.setdefault(workspace / MANIFEST_REL, file_state(workspace / MANIFEST_REL).as_dict())
        planned_bytes[workspace / MANIFEST_REL] = manifest_bytes
        try:
            transactional_commit(
                workspace,
                planned_bytes,
                expected=expected,
                operation="init_resume",
                postflight=validate_runtime_postflight,
            )
        except (TxError, OSError, UnicodeError) as exc:
            raise InitError(f"续建事务提交失败：{exc}") from exc
        result_workspace = workspace
    else:
        try:
            for path, data in planned_bytes.items():
                atomic_write(path, data.decode("utf-8"))
            atomic_write_json(workspace / MANIFEST_REL, manifest)
            validate_runtime_postflight(workspace)
            os.replace(workspace, final_workspace)
            fsync_directory(final_workspace.parent)
            result_workspace = final_workspace
            validate_runtime_postflight(result_workspace)
            staging_parent.rmdir()
        except (InitError, TxError, OSError, UnicodeError) as exc:
            if 'final_workspace' in locals() and final_workspace.exists():
                shutil.rmtree(final_workspace, ignore_errors=True)
            if 'staging_parent' in locals() and staging_parent.exists():
                shutil.rmtree(staging_parent, ignore_errors=True)
            if isinstance(exc, InitError):
                raise
            raise InitError(f"初始化暂存提交失败，已清理：{exc}") from exc

    return {
        "workspace": str(result_workspace),
        "context_id": context_id,
        "latest_run_id": latest_run_id,
        "customer_id": customer_id,
        "safe_name": safe_name,
        "route": route,
        "depth": mode,
        "business_mode": business_mode,
        "task_timezone": task_timezone,
        "manifest_revision": previous_sequence + 1,
        "organization_scope": organization_scope,
        "selected_modules": modules,
        "refresh_modules": [name for name in TYPE_FOR_MODULE if name in refresh_modules],
        "created": created,
        "preserved": preserved,
        "intake_preflight": intake_preflight,
        "strategy_variant": strategy_variant,
    }


def initialize(args: argparse.Namespace) -> dict[str, object]:
    """Run the complete read-plan-commit-postflight cycle under POSIX locks."""
    if args.lock_timeout < 0:
        raise InitError("--lock-timeout不能为负数。")
    if args.recover and not args.resume:
        raise InitError("--recover只能与--resume一起使用。")
    intake_preflight = require_ready_intake(args)
    output_root = Path(args.output_root).expanduser()
    if output_root.is_symlink():
        raise InitError("--output-root不得为符号链接。")
    output_root.mkdir(parents=True, exist_ok=True)
    root = output_root.resolve()
    with output_root_lock(root, timeout=args.lock_timeout):
        recovery = "not_requested"
        if args.resume:
            customer_name = normalize_customer_name(args.customer_name)
            safe_name = explicit_safe_name(args.safe_name) if args.safe_name else normalize_safe_component(customer_name)
            workspace = find_resume_workspace(root, safe_name, args.context_id)
            with workspace_lock(workspace, timeout=args.lock_timeout):
                if unfinished_transaction(workspace):
                    if not args.recover:
                        raise RecoveryRequired("检测到未完成事务；请用--resume --recover恢复后再续建。")
                    recovery = recover_transaction(
                        workspace,
                        strategy=args.recovery_strategy,
                        postflight=None,
                    )
                elif args.recover:
                    recovery = "no_transaction_reconcile"
                result = _initialize_locked(args, intake_preflight)
        else:
            result = _initialize_locked(args, intake_preflight)
        result["recovery"] = recovery
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="安全生成或续建 discovery-call v2.5 的 1+N 成果工作目录。"
    )
    parser.add_argument("customer_name", help="客户中文规范名称")
    parser.add_argument("--output-root", default=".", help="工作目录父目录（默认当前目录）")
    parser.add_argument("--safe-name", help="显式安全名称，1—48字符且不得包含路径片段")
    parser.add_argument("--context-id", help="新建时指定或续建时选择 dcx-YYYYMMDD-8chars")
    parser.add_argument("--run-id", help="可选显式run_id；若在init同run验证宿主能力收据时必需；常规候选收据应绑定后续candidate run")
    parser.add_argument("--customer-id", help="可选稳定客户ID；续建时必须与既有上下文一致")
    parser.add_argument("--organization-scope", help="院区、部门或项目范围；新建默认使用客户规范名称")
    parser.add_argument("--runtime-owner", help="运行负责人/角色；续建默认沿用")
    parser.add_argument(
        "--business-mode",
        choices=("briefing", "standard_visit", "strategic_account", "letter"),
        help="业务入口；从config/business-modes.json映射route/depth/modules",
    )
    parser.add_argument(
        "--intake-input",
        help="结构化intake JSON；使用--business-mode时必需，初始化器会在任何目录写入前重新计算门禁",
    )
    parser.add_argument("--strategy-variant", choices=("scheduled_visit", "account_planning"), help="策略成果变体；strategic_account默认account_planning")
    parser.add_argument("--target-contact-level", help="拜访对象层级或角色；须与intake一致")
    parser.add_argument("--visit-objective", help="本次拜访主要目标；须与intake一致")
    parser.add_argument("--minimum-next-step", help="最小推进动作；须与intake一致")
    parser.add_argument("--strategic-question", help="账户规划需回答的战略问题；须与intake一致")
    parser.add_argument("--planning-horizon", help="账户规划周期；须与intake一致")
    parser.add_argument("--recipient-identity", help="收件对象姓名或正式称谓；如提供须与intake一致")
    parser.add_argument("--recipient-role", help="收件对象角色；须与intake一致")
    parser.add_argument("--letter-scenario", help="客户信业务场景；须与intake一致")
    parser.add_argument("--letter-purpose", help="客户信目的；须与intake一致")
    parser.add_argument("--expected-action", help="希望收件人采取的动作；须与intake一致")
    parser.add_argument("--signer", help="签署人或稳定签署角色；须与intake一致")
    parser.add_argument("--delivery-channel", help="拟使用的发送渠道；须与intake一致")
    parser.add_argument("--route", choices=sorted(ROUTES), help="本轮路由；新建默认research_only，续建默认沿用")
    parser.add_argument("--mode", choices=sorted(MODE_LABELS), help="研究档位；新建默认standard，续建默认沿用")
    parser.add_argument(
        "--evidence-cutoff-date",
        help="本轮目标信息截止日期YYYY-MM-DD；续建未指定时保留既有截止日期",
    )
    parser.add_argument(
        "--task-timezone",
        help="新建截止日期所用IANA时区；新建时须至少与--evidence-cutoff-date提供一项，同时提供时按该时区校验显式日期",
    )
    parser.add_argument("--run-objective", help="本轮可审计目标；默认使用route")
    parser.add_argument(
        "--modules",
        action="append",
        help="逗号分隔或重复指定：institution,leader,internal,strategy,letter；新建默认institution，续建默认继承最新选择",
    )
    parser.add_argument(
        "--refresh-modules",
        action="append",
        help="续建输出路由中需同run更新的既有研究模块：institution,leader,internal；必须同时列入--modules",
    )
    parser.add_argument("--include-strategy", action="store_true", help="兼容加选strategy")
    parser.add_argument("--include-letter", action="store_true", help="兼容加选letter")
    parser.add_argument(
        "--internal-connector-status",
        choices=sorted(CONNECTOR_STATUSES),
        default="not_configured",
        help="内部检索连接状态；仅使用用户授权材料且未依赖连接器时可用not_applicable",
    )
    parser.add_argument("--internal-connector-id", help="内部连接器稳定标识")
    parser.add_argument("--tenant-id", help="内部授权租户稳定标识")
    parser.add_argument("--project-id", help="项目稳定标识")
    parser.add_argument("--allowed-project-ids", action="append", help="授权项目ID，可逗号分隔或重复")
    parser.add_argument("--authorization-owner", help="内部授权责任人")
    parser.add_argument("--authorization-purpose", help="本轮内部数据使用目的")
    parser.add_argument("--capability-receipt-id", help="宿主连接器能力/授权收据稳定ID")
    parser.add_argument("--authorization-actor-id", help="宿主认证的当前运行真人稳定actor_id")
    parser.add_argument(
        "--capability-receipt-file",
        help="宿主签发的Ed25519能力收据普通文件；文件本身不会写入workspace",
    )
    parser.add_argument("--authorization-expires-at", help="带时区的ISO 8601授权到期时间")
    parser.add_argument("--authorized-root", action="append", help="授权根范围，可重复")
    parser.add_argument("--allowed-dataset-alias", action="append", help="允许的数据集别名，可重复")
    parser.add_argument("--allowed-confidentiality", action="append", help="允许的密级，可重复")
    parser.add_argument("--content-version", default="1", help="新成果内容版本")
    parser.add_argument("--resume", action="store_true", help="续建；继承或显式选择模块，保留既有文件并登记计划动作")
    parser.add_argument("--recover", action="store_true", help="续建前恢复未完成事务，并允许合法中断状态对账")
    parser.add_argument(
        "--recovery-strategy", choices=("auto", "rollback", "roll-forward"), default="auto",
        help="未完成事务恢复策略（默认auto）",
    )
    parser.add_argument("--lock-timeout", type=float, default=60.0, help="等待POSIX运行锁秒数")
    parser.add_argument("--json", action="store_true", help="输出JSON结果")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = initialize(args)
    except (InitError, TxError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"工作目录：{result['workspace']}")
        print(f"context_id：{result['context_id']}")
        print(f"latest_run_id：{result['latest_run_id']}")
        print("已创建：" + (", ".join(result["created"]) or "无"))
        if result["preserved"]:
            print("已保留：" + ", ".join(result["preserved"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
