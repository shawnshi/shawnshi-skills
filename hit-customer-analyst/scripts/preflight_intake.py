#!/usr/bin/env python3
"""Deterministic, side-effect-free intake disambiguation for discovery-call.

The script deliberately does not create a customer workspace, build a search
plan, access the network, or select between conflicting user-provided values.
It turns structured candidate occurrences into either:

* a short-lived ``ready`` receipt containing the exact selected values; or
* a ``blocked`` result containing only the questions that must be answered
  before initialization or research begins.

Exit codes:

* 0: ready
* 2: invalid intake contract
* 3: clarification required
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


LEGACY_INPUT_SCHEMA = "discovery-call-intake/v1"
BOUND_LEGACY_INPUT_SCHEMA = "discovery-call-intake/v2"
LEGACY_INPUT_SCHEMAS = {LEGACY_INPUT_SCHEMA, BOUND_LEGACY_INPUT_SCHEMA}
INPUT_SCHEMA = "discovery-call-intake/v3"
RESULT_SCHEMA = "discovery-call-intake-gate/v3"
REQUEST_BINDING_SCHEMA = "discovery-call-request-binding-receipt/v2"
REQUEST_BINDING_AUDIENCE = "discovery-call-request-binding"
REQUEST_BINDING_TRUSTED_KEYS_ENV = "DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON"
CURRENT_REQUEST_CONTEXT_ENV = "DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON"
REQUEST_NORMALIZATION = "unicode-nfc-lf-utf8/v1"
REQUEST_CAPTURE_METHOD = "authenticated_host_message_bundle"
REQUEST_COVERAGE_POLICY = "discovery-call-high-impact-occurrences/v2"
SAFETY_DIRECTIVE_POLICY = "discovery-call-letter-safety-directives/v1"
SUBJECT_RESOLUTION_SCHEMA = "discovery-call-subject-resolution/v1"
SAFETY_AUTHORIZATION_SCHEMA = "discovery-call-safety-authorization/v1"
SUBJECT_ID_SOURCES = {"host_attested_external", "canonical_derived"}
AUTHORIZABLE_SOURCE_RISKS = {
    "unauthorized_patient_information",
    "unauthorized_internal_source",
}
LETTER_SAFETY_RISK_ORDER = (
    "fabricated_approval",
    "unauthorized_patient_information",
    "unauthorized_internal_source",
    "unverified_delivery_timeline",
    "unverified_outcome_claim",
    "unapproved_price_cap",
    "direct_external_send",
    "nonhuman_accountability",
)
LETTER_SAFETY_RISK_CODES = set(LETTER_SAFETY_RISK_ORDER)
MAX_RAW_REQUEST_BYTES = 256 * 1024
MAX_REQUEST_RECEIPT_BYTES = 64 * 1024
MAX_REQUEST_RECEIPT_LIFETIME = timedelta(hours=2)
BUSINESS_MODES = {"briefing", "standard_visit", "strategic_account", "letter"}
FIELD_LABELS = {
    "customer_name": "客户主体",
    "organization_scope": "机构/院区范围",
    "target_person": "拜访对象姓名",
    "target_role": "拜访对象职务",
    "target_contact_level": "拜访对象层级",
    "meeting_status": "会议状态",
    "meeting_time": "会议时间",
    "project_id": "项目范围",
    "recipient_identity": "收件对象",
    "recipient_role": "收件对象职务",
    "visit_objective": "拜访目标",
    "minimum_next_step": "最小推进动作",
    "strategic_question": "账户战略问题",
    "planning_horizon": "账户经营周期",
    "strategy_variant": "策略成果变体",
    "letter_scenario": "信件场景",
    "letter_purpose": "发信目的",
    "expected_action": "期望对方动作",
    "signer": "签署人",
    "delivery_channel": "发送渠道",
}
SUPPORTED_FIELDS = set(FIELD_LABELS)
VISIT_MODES = {"briefing", "standard_visit"}
MEETING_STATUSES = {"confirmed", "tentative", "none", "unknown"}
MEETING_STATUS_VARIANTS = {
    "confirmed": "scheduled_visit",
    "tentative": "account_planning",
    "none": "account_planning",
    "unknown": "account_planning",
}
DEFAULT_TTL_SECONDS = 1800
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 3600
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,128}$")
BINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")
DISALLOWED_RAW_CONTROLS = frozenset(
    {
        "\u200b",
        "\u200c",
        "\u200d",
        "\u2060",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)
MENTION_SLOTS = {
    "organization",
    "person",
    "role",
    "meeting_time",
    "project_id",
    "meeting_status",
    "recipient_identity",
    "recipient_role",
    "visit_objective",
    "minimum_next_step",
    "strategic_question",
    "planning_horizon",
    "letter_scenario",
    "letter_purpose",
    "expected_action",
    "signer",
    "delivery_channel",
}
ACTIVE_ASSERTION_STATUSES = {"asserted", "uncertain", "explicit_unknown"}
MENTION_FIELD_MAP = {
    "organization": ("customer_name", "organization_scope"),
    "person": ("target_person", "recipient_identity"),
    "role": ("target_role", "target_contact_level", "recipient_role"),
    "meeting_time": ("meeting_time",),
    "project_id": ("project_id",),
    "meeting_status": ("meeting_status",),
    "recipient_identity": ("recipient_identity",),
    "recipient_role": ("recipient_role",),
    "visit_objective": ("visit_objective",),
    "minimum_next_step": ("minimum_next_step",),
    "strategic_question": ("strategic_question",),
    "planning_horizon": ("planning_horizon",),
    "letter_scenario": ("letter_scenario",),
    "letter_purpose": ("letter_purpose",),
    "expected_action": ("expected_action",),
    "signer": ("signer",),
    "delivery_channel": ("delivery_channel",),
}
SIGNED_CANDIDATE_FIELDS = frozenset(
    field for mapped_fields in MENTION_FIELD_MAP.values() for field in mapped_fields
)

_ORG_SUFFIX = (
    "卫生健康委员会|疾病预防控制中心|妇幼保健院|医学中心|医疗中心|"
    "中医院|医院|卫健委|医保局|卫生局|疾控中心|卫生院"
)
_REGION_PREFIX = (
    "北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|"
    "山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|"
    "广西|西藏|宁夏|新疆|香港|澳门|中国"
)
OBVIOUS_ORGANIZATION_RE = re.compile(
    rf"(?:{_REGION_PREFIX})[\u4e00-\u9fffA-Za-z0-9·()（）-]{{1,60}}?(?:{_ORG_SUFFIX})"
)
LABELLED_ORGANIZATION_RE = re.compile(
    rf"(?:客户(?:主体)?|机构(?:范围)?|organization_scope|customer_name)\s*[:：]\s*"
    rf"(?P<value>[\u4e00-\u9fffA-Za-z0-9·()（）-]{{2,80}}?(?:{_ORG_SUFFIX}))"
)
MEETING_DATE_RE = re.compile(
    r"(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|20\d{2}年\d{1,2}月\d{1,2}日)"
    r"(?:[ T\s]*\d{1,2}[:：]\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?"
)
AMBIGUOUS_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)")
MEETING_CONTEXT_RE = re.compile(r"拜访|会议|会面|约定|交流|行程|meeting_time|时间")

REQUEST_RECEIPT_FIELDS = {
    "schema",
    "issuer",
    "audience",
    "key_id",
    "receipt_id",
    "issued_at",
    "expires_at",
    "request_id",
    "business_mode",
    "request_actor_id",
    "request_bundle_id",
    "request_revision",
    "ordered_request_event_ids",
    "last_user_event_id",
    "capture_method",
    "normalization_method",
    "raw_request_sha256",
    "raw_request_length",
    "attachment_manifest_sha256",
    "attachment_count",
    "mention_ledger_sha256",
    "subject_resolution_sha256",
    "safety_authorizations_sha256",
    "safety_directives_sha256",
    "mention_count",
    "extractor_id",
    "extractor_version",
    "extraction_policy_sha256",
    "coverage_policy",
    "coverage_complete",
    "mentions",
    "safety_directive_policy",
    "safety_coverage_complete",
    "safety_directives_sha256",
    "safety_directive_count",
    "safety_directives",
    "signature",
}
MENTION_FIELDS = {
    "mention_id",
    "semantic_slot",
    "candidate_field",
    "source_event_id",
    "char_start",
    "char_end",
    "surface_sha256",
    "normalized_value",
    "assertion_status",
    "source_ref",
}


class PreflightError(RuntimeError):
    """Raised when the structured intake contract is invalid."""


@dataclass(frozen=True)
class VerifiedRequestBinding:
    """Host-authenticated raw-request and occurrence-ledger binding."""

    receipt_id: str
    request_bundle_id: str
    request_revision: int
    issuer: str
    key_id: str
    receipt_sha256: str
    raw_request_sha256: str
    mention_ledger_sha256: str
    subject_resolution_sha256: str
    safety_authorizations_sha256: str
    safety_directives_sha256: str
    expires_at: datetime
    mentions: tuple[dict[str, Any], ...]
    safety_directives: tuple[dict[str, Any], ...]
    raw_request_text: str

    def audit_fields(self) -> dict[str, Any]:
        return {
            "verified": True,
            "receipt_id": self.receipt_id,
            "request_bundle_id": self.request_bundle_id,
            "request_revision": self.request_revision,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "receipt_sha256": self.receipt_sha256,
            "raw_request_sha256": self.raw_request_sha256,
            "mention_ledger_sha256": self.mention_ledger_sha256,
            "subject_resolution_sha256": self.subject_resolution_sha256,
            "safety_authorizations_sha256": self.safety_authorizations_sha256,
            "safety_directives_sha256": self.safety_directives_sha256,
            "expires_at": isoformat(self.expires_at),
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        raise PreflightError("时间必须包含时区。")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PreflightError(f"{label}必须是带时区ISO 8601时间。")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreflightError(f"{label}必须是带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise PreflightError(f"{label}必须包含时区。")
    return parsed.astimezone(timezone.utc)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def resolved_text(value: Any) -> bool:
    text = normalize_text(value)
    return bool(
        text
        and len(text) <= 500
        and not PLACEHOLDER_RE.search(text)
        and text.casefold() not in {
            "待确认",
            "未确认",
            "待核实",
            "未核实",
            "待指定",
            "待补充",
            "unknown",
            "none",
            "n/a",
            "na",
        }
        and not any(ord(char) < 32 or ord(char) == 127 for char in text)
    )


LETTER_PURPOSE_ACTION_RE = re.compile(
    r"(?:确认|说明|澄清|同步|商议|讨论|邀请|跟进|回应|感谢|征询|安排|请求)"
)
LETTER_EXPECTED_ACTION_RE = re.compile(
    r"(?:确认|提供|回复|安排|选择|反馈|提交|签署|指定|告知|同意|审阅|参加|协调|预约|补充)"
)
LETTER_VACUOUS_RE = re.compile(
    r"^(?:相关|上述|以上|本项|该项|本节|具体)?(?:内容|事项|信息|情况|结果)?"
    r"(?:已经|已)?(?:记录|完成|讨论|沟通|处理|说明)(?:并(?:已)?完成)?[。.!！?？;；:：]*$"
)


# These narrow patterns are diagnostic fixtures for host-extractor conformance;
# they are not an authorization or production gate.  Runtime decisions consume
# only the host-signed, occurrence-bound safety_directives ledger so a model
# cannot alter safety status by rewriting or omitting raw text.
HIGH_RISK_LETTER_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "fabricated_approval",
        (
            re.compile(r"(?:虚构|伪造|假造|谎称|写成|声称).{0,20}(?:已获|已经获得|领导).{0,20}(?:批准|审批|同意)", re.IGNORECASE),
            re.compile(r"(?:fabricate|falsify|pretend).{0,30}(?:approval|approved)", re.IGNORECASE),
        ),
    ),
    (
        "unauthorized_patient_information",
        (
            re.compile(r"(?:使用|引用|调取|写入|提供|带上).{0,24}(?:患者|病人).{0,16}(?:案例|病历|数据|信息)", re.IGNORECASE),
            re.compile(r"(?:患者|病人).{0,16}(?:案例|病历|数据|信息).{0,24}(?:使用|引用|调取|写入|提供|带上)", re.IGNORECASE),
            re.compile(r"(?:患者|病人).{0,16}(?:案例|病历|数据|信息).{0,20}(?:不得|禁止).{0,8}外发.{0,20}(?:却|但)?(?:可以|允许).{0,20}(?:内部待审核稿|内部稿).{0,8}(?:使用|引用)", re.IGNORECASE),
            re.compile(r"(?:use|include|retrieve).{0,30}(?:patient|medical record).{0,20}(?:data|case|information)?", re.IGNORECASE),
        ),
    ),
    (
        "unauthorized_internal_source",
        (
            re.compile(r"(?:使用|引用|调取|写入|提供|带上).{0,24}(?:内部邮件|内部邮箱|CRM(?:记录|数据)?|客户关系管理系统)", re.IGNORECASE),
            re.compile(r"(?:内部邮件|内部邮箱|CRM(?:记录|数据)?|客户关系管理系统).{0,24}(?:使用|引用|调取|写入|提供|带上)", re.IGNORECASE),
            re.compile(r"(?:use|include|retrieve).{0,30}(?:internal email|CRM record|CRM data)", re.IGNORECASE),
        ),
    ),
    (
        "unverified_delivery_timeline",
        (
            re.compile(r"(?:承诺|保证|确保).{0,28}(?:\d+\s*(?:个月|月|周|天).{0,16}(?:上线|交付|完成)|(?:上线|交付|完成).{0,16}\d+\s*(?:个月|月|周|天))", re.IGNORECASE),
            re.compile(r"(?:guarantee|promise).{0,30}(?:go-live|delivery|launch).{0,20}\d+", re.IGNORECASE),
        ),
    ),
    (
        "unverified_outcome_claim",
        (
            re.compile(r"(?:承诺|保证|确保).{0,28}(?:提升|降低|改善|节省).{0,16}\d+(?:\.\d+)?\s*%", re.IGNORECASE),
            re.compile(r"(?:guarantee|promise).{0,30}\d+(?:\.\d+)?\s*%", re.IGNORECASE),
        ),
    ),
    (
        "unapproved_price_cap",
        (
            re.compile(r"(?:承诺|保证|确保|写明|注明).{0,18}(?:总价|价格|报价|费用).{0,20}(?:不超|不超过|以内|封顶).{0,16}(?:人民币)?\s*\d+", re.IGNORECASE),
            re.compile(r"(?:总价|价格|报价|费用).{0,12}(?:写明|注明|承诺|保证|确保).{0,12}(?:不超|不超过|以内|封顶).{0,16}(?:人民币)?\s*\d+", re.IGNORECASE),
            re.compile(r"(?:promise|guarantee|state).{0,18}(?:price|total price|fee).{0,20}(?:under|not exceed|capped at).{0,16}\d+", re.IGNORECASE),
        ),
    ),
    (
        "direct_external_send",
        (
            re.compile(r"(?:直接|立即|马上|无需审核|不经审核).{0,10}(?:发送|外发|发出)", re.IGNORECASE),
            re.compile(r"(?:send|dispatch).{0,20}(?:directly|immediately|without review)", re.IGNORECASE),
        ),
    ),
    (
        "nonhuman_accountability",
        (
            re.compile(r"(?:审批人|执行人|责任人).{0,10}(?:写|设|填)?(?:为|成)?\s*(?:AI|模型|智能体)", re.IGNORECASE),
            re.compile(r"(?:AI|模型|智能体).{0,12}(?:(?:作为|担任|充当|写为|设为).{0,8})?(?:审批人|执行人|责任人)", re.IGNORECASE),
            re.compile(r"(?:approver|owner|responsible actor).{0,20}(?:AI|model|agent)", re.IGNORECASE),
        ),
    ),
)

HIGH_RISK_LETTER_RESPONSE_ITEMS: dict[str, dict[str, str]] = {
    "fabricated_approval": {
        "item": "虚假审批或授权",
        "reason": "不能把未发生的批准、审批或授权写成事实。",
        "required_material": "提供可追溯到真人、稳定角色/账号和当前事项的真实审批记录。",
    },
    "unauthorized_patient_information": {
        "item": "患者案例、病历或患者数据",
        "reason": "未经授权的患者资料不得用于客户研究、信件或外发背书。",
        "required_material": "只提供已获合法授权、完成必要脱敏且明确允许该用途的材料。",
    },
    "unauthorized_internal_source": {
        "item": "内部邮件、CRM记录或其他内部资料",
        "reason": "内部资料只能在已授权的连接器、项目与用途范围内检索和引用，不能直接复制到外发信件。",
        "required_material": "提供当前有效的访问授权、项目范围与可外发性结论；否则不得检索或引用。",
    },
    "unverified_delivery_timeline": {
        "item": "上线或交付期限承诺",
        "reason": "未经项目评估和授权的排期不能作为对外承诺。",
        "required_material": "提供经交付负责人核验的范围、依赖、资源和批准排期。",
    },
    "unverified_outcome_claim": {
        "item": "量化效果承诺",
        "reason": "未经证据和授权的效率、质量或结果提升数字不能外发。",
        "required_material": "提供可复核的测量口径、基线、证据和有权审批人的确认。",
    },
    "unapproved_price_cap": {
        "item": "价格上限或商务承诺",
        "reason": "未经商业审批的价格、免费范围或总价边界不能写入正式信件。",
        "required_material": "提供当前有效的授权报价或商业审批记录。",
    },
    "direct_external_send": {
        "item": "绕过审核直接外发",
        "reason": "本Skill只生成文件，不能替用户发送，也不能跳过事实复核和外发审批。",
        "required_material": "完成事实复核、独立外发审批，并由用户在审批后再次明确要求生成外发版。",
    },
    "nonhuman_accountability": {
        "item": "由AI承担审批或执行责任",
        "reason": "AI不能作为审批人、签署责任人或外发责任主体。",
        "required_material": "指定可追溯到真人及稳定组织角色/账号的责任人。",
    },
}


RISK_CLAUSE_SPLIT_RE = re.compile(
    r"(?:[，,。；;！？!?\n\r]+|但(?:是)?|不过|然而|也请|并请|"
    r"(?:并且|以及|同时|随后|然后|还要|另外|和|并|而|且)(?=(?:请|再|也)?(?:直接|立即|马上|承诺|保证|确保|使用|引用|调取|写入|提供|带上|虚构|伪造|执行人|审批人|责任人))|"
    r"请(?=(?:直接|立即|马上|承诺|保证|确保|使用|引用|调取|写入|提供|带上|虚构|伪造|执行人|审批人)))"
)


def _risk_match_is_negated(raw_text: str, start: int, end: int) -> bool:
    """Return true when the matched unsafe action is explicitly prohibited.

    The denial can precede the regex match (``禁止在信中使用患者案例``)
    or occur inside it (``患者案例不得使用`` / ``内部稿，不发送``).
    Keeping this check local avoids treating an unrelated earlier prohibition
    as applying to a later positive request.
    """
    negation = re.compile(
        r"(?:请勿|切勿|勿|不要|不得|禁止|避免|不能|不应|不必|不需要|拒绝|严禁|不会|无需(?!审核)|无须(?!审核)|不是|并非|"
        r"不(?=\s*(?:虚构|伪造|假造|谎称|承诺|保证|确保|使用|引用|调取|写入|提供|带上|直接|立即|马上|发送|外发|发出|写|设|填))|"
        r"do\s+not|must\s+not|never|without\s+sending)",
        re.IGNORECASE,
    )
    risk_predicate = re.compile(
        r"(?:虚构|伪造|假造|谎称|承诺|保证|确保|使用|引用|调取|写入|提供|带上|"
        r"直接|立即|马上|发送|外发|发出|写|设|填|fabricate|falsify|pretend|"
        r"guarantee|promise|use|include|retrieve|send|dispatch)",
        re.IGNORECASE,
    )
    clause_start = max(
        (raw_text.rfind(mark, 0, start) for mark in "，,。；;！？!?\n\r"),
        default=-1,
    ) + 1
    prefix = raw_text[clause_start:start]
    if re.search(r"(?:不|别)\s*$", prefix):
        return True
    for denial in reversed(list(negation.finditer(prefix))):
        # A prior denial applies only if no other risky predicate intervenes.
        # This prevents “不要使用患者案例并承诺上线” from negating “承诺”.
        if not risk_predicate.search(prefix[denial.end() :]):
            return True
        break
    within = raw_text[start : min(len(raw_text), end + 12)]
    for denial in negation.finditer(within):
        tail = within[denial.end() :]
        # A later explicit permission starts a new instruction even when the
        # same clause first prohibits external use (for example, “不得外发却可
        # 以在内部稿引用”).  That internal use still needs a signed material-
        # scoped authorization and therefore remains a diagnostic risk.
        if re.search(
            r"(?:却|但|不过).{0,12}(?:可以|允许|可).{0,24}"
            r"(?:使用|引用|调取|写入|提供|带上)",
            tail,
            re.IGNORECASE,
        ):
            continue
        if risk_predicate.search(tail):
            return True
    return False


def _risk_match_is_quoted_example(raw_text: str, start: int, end: int) -> bool:
    for quote_pattern in (r"“[^”]*”", r"‘[^’]*’", r"「[^」]*」", r'"[^"\n]*"'):
        for quoted in re.finditer(quote_pattern, raw_text):
            if quoted.start() <= start and end <= quoted.end():
                lead = raw_text[max(0, quoted.start() - 24) : quoted.start()]
                if re.search(r"(?:执行|照做|采纳|按.{0,8}(?:要求|内容|指令))\s*$", lead):
                    return False
                return True
    return False


def detect_high_risk_letter_requests(raw_text: str) -> tuple[str, ...]:
    """Best-effort diagnostic classifier; never authoritative at runtime."""
    clauses = [item.strip() for item in RISK_CLAUSE_SPLIT_RE.split(raw_text) if item.strip()]
    detected: list[str] = []
    for code, patterns in HIGH_RISK_LETTER_PATTERNS:
        matched = False
        for pattern in patterns:
            for clause in clauses:
                for match in pattern.finditer(clause):
                    if (
                        not _risk_match_is_negated(clause, match.start(), match.end())
                        and not _risk_match_is_quoted_example(clause, match.start(), match.end())
                    ):
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break
        if matched:
            detected.append(code)
    return tuple(detected)


def high_risk_letter_failure_response(risk_codes: Sequence[str]) -> dict[str, Any]:
    refused = [
        {"code": code, **HIGH_RISK_LETTER_RESPONSE_ITEMS[code]}
        for code in risk_codes
        if code in HIGH_RISK_LETTER_RESPONSE_ITEMS
    ]
    return {
        "response_schema": "discovery-call-high-risk-letter-failure/v1",
        "decision": "refused_external_and_unsafe_components",
        "response_sections": [
            "refused_items",
            "reasons",
            "permitted_scope",
            "required_materials",
            "approval_path",
        ],
        "refused_items": refused,
        "reasons": [
            {"code": item["code"], "reason": item["reason"]}
            for item in refused
        ],
        "permitted_scope": {
            "artifact": "internal_review_draft_only",
            "internal_artifact_path": None,
            "external_artifact_paths": [],
            "external_version_allowed": False,
            "automatic_send_allowed": False,
            "send_attempted": False,
            "ready_for_use": False,
            "condition": "删除虚假或未授权内容，并补齐真实证据、真人责任人与审批后，才可重新受理内部待审核稿。",
        },
        "approval_path": [
            "事实与患者资料授权核验",
            "交付、效果与价格边界分别由有权真人确认",
            "独立事实复核人与外发审批人完成审批",
            "审批后由用户再次明确要求生成外发版；Skill仍不发送",
        ],
        "required_materials": [
            {"code": item["code"], "material": item["required_material"]}
            for item in refused
        ],
        "next_step": "如需继续，请一次性提供真实审批记录、患者资料授权/脱敏证明、排期与效果证据、商业审批，以及真人责任人；否则仅保留拒绝记录，不创建客户业务文件。",
    }


def substantive_letter_field(value: str, *, purpose: bool) -> bool:
    normalized = unicodedata.normalize("NFKC", value).strip()
    compact = re.sub(r"\s+", "", normalized)
    action_pattern = LETTER_PURPOSE_ACTION_RE if purpose else LETTER_EXPECTED_ACTION_RE
    return bool(
        resolved_text(normalized)
        and len(compact) >= 6
        and not LETTER_VACUOUS_RE.fullmatch(compact)
        and not re.search(r"(?:元数据|字段|提示词|letter_purpose|expected_action)", compact, re.IGNORECASE)
        and action_pattern.search(compact)
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def input_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PreflightError(f"JSON包含重复字段：{key}。")
        value[key] = item
    return value


def _parse_json_bytes(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except PreflightError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"{label}不是有效UTF-8 JSON：{exc}") from exc


def canonical_raw_request(text: str) -> str:
    """Canonical form whose character offsets are used by the signed ledger."""
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]
    if any(char in normalized for char in DISALLOWED_RAW_CONTROLS):
        raise PreflightError("原始请求含零宽或双向控制字符，宿主必须规范化并重新签发绑定收据。")
    if "\x00" in normalized:
        raise PreflightError("原始请求含NUL字符，不能进入预检。")
    return normalized


def raw_request_sha256(text: str) -> str:
    return hashlib.sha256(canonical_raw_request(text).encode("utf-8")).hexdigest()


def _read_regular_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PreflightError(f"{label}必须是现有普通文件，且不得为符号链接。")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PreflightError(f"{label}无法读取：{exc}") from exc
    if not raw or len(raw) > maximum:
        raise PreflightError(f"{label}为空或超过{maximum}字节上限。")
    return raw


def _binding_file(base: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise PreflightError(f"request_binding.{label}必须是同目录普通文件名。")
    candidate = Path(value)
    if candidate.name != value or candidate.is_absolute() or value in {".", ".."}:
        raise PreflightError(f"request_binding.{label}只能引用intake同目录文件。")
    return base / value


def _binding_timestamp(value: Any, label: str) -> datetime:
    return parse_timestamp(value, f"request binding receipt.{label}")


def _trusted_request_key(issuer: str, key_id: str) -> Ed25519PublicKey:
    encoded_registry = os.environ.get(REQUEST_BINDING_TRUSTED_KEYS_ENV, "").strip()
    if not encoded_registry:
        raise PreflightError(
            f"宿主未注入{REQUEST_BINDING_TRUSTED_KEYS_ENV}信任根；初始化和检索已关闭。"
        )
    registry = _parse_json_bytes(
        encoded_registry.encode("utf-8"), REQUEST_BINDING_TRUSTED_KEYS_ENV
    )
    if not isinstance(registry, dict):
        raise PreflightError(f"{REQUEST_BINDING_TRUSTED_KEYS_ENV}必须是issuer到key_id公钥的对象。")
    issuer_keys = registry.get(issuer)
    encoded = issuer_keys.get(key_id) if isinstance(issuer_keys, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise PreflightError("request binding receipt的issuer/key_id不在宿主信任根中。")
    try:
        public_bytes = base64.b64decode(encoded, validate=True)
        if len(public_bytes) != 32:
            raise ValueError("length")
        return Ed25519PublicKey.from_public_bytes(public_bytes)
    except (TypeError, ValueError) as exc:
        raise PreflightError("宿主注入的Ed25519请求绑定公钥无效。") from exc


def _clean_binding_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not BINDING_ID_RE.fullmatch(value):
        raise PreflightError(f"request binding receipt.{label}格式无效。")
    return value


def _surface_matches_value(surface: str, value: str, *, slot: str) -> bool:
    left = normalize_text(surface).casefold()
    right = normalize_text(value).casefold()
    if not left or not right:
        return False
    if slot == "meeting_status":
        status_terms = {
            "confirmed": ("confirmed", "已确认", "已确定", "已约定", "已预约"),
            "tentative": ("tentative", "暂定", "待最终确认"),
            "none": ("none", "已取消", "取消", "不再举行", "不再拜访"),
            "unknown": ("unknown", "状态未知", "尚不清楚"),
        }
        return right in status_terms and any(term in left for term in status_terms[right])
    # A signed occurrence must identify the same normalized value.  Substring
    # matching lets “北京协和医院/澳门协和医院” or “院长/副院长” collapse into one
    # shorter candidate and recreates the original P0 omission bypass.
    return left == right


def _validate_time_mention(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise PreflightError(f"{label}必须是时间对象。")
    _validate_exact_keys(value, {"start", "end", "timezone", "date_anchor"}, label)
    if "start" not in value:
        raise PreflightError(f"{label}必须包含start。")
    start = parse_timestamp(value.get("start"), f"{label}.start")
    normalized: dict[str, str] = {"start": isoformat(start)}
    if value.get("end") not in {None, ""}:
        end = parse_timestamp(value.get("end"), f"{label}.end")
        if end <= start:
            raise PreflightError(f"{label}.end必须晚于start。")
        normalized["end"] = isoformat(end)
    timezone_name = normalize_text(value.get("timezone"))
    if timezone_name:
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise PreflightError(f"{label}.timezone必须是有效IANA时区。") from exc
        supplied_start = parse_timestamp(value.get("start"), f"{label}.start")
        original = datetime.fromisoformat(str(value.get("start")).strip().replace("Z", "+00:00"))
        if original.utcoffset() != supplied_start.astimezone(zone).utcoffset():
            raise PreflightError(f"{label}.timezone与start的UTC offset不一致。")
        normalized["timezone"] = timezone_name
    date_anchor = normalize_text(value.get("date_anchor"))
    if date_anchor:
        try:
            datetime.strptime(date_anchor, "%Y-%m-%d")
        except ValueError as exc:
            raise PreflightError(f"{label}.date_anchor必须是YYYY-MM-DD。") from exc
        normalized["date_anchor"] = date_anchor
    return normalized


def _obvious_mentions(raw_text: str) -> list[tuple[str, int, int]]:
    """Find high-confidence spans; ambiguity is rejected rather than guessed."""
    detected: set[tuple[str, int, int]] = set()
    for match in OBVIOUS_ORGANIZATION_RE.finditer(raw_text):
        detected.add(("organization", match.start(), match.end()))
    for match in LABELLED_ORGANIZATION_RE.finditer(raw_text):
        detected.add(("organization", match.start("value"), match.end("value")))
    for match in AMBIGUOUS_DATE_RE.finditer(raw_text):
        left, right = int(match.group(1)), int(match.group(2))
        context = raw_text[max(0, match.start() - 24) : min(len(raw_text), match.end() + 24)]
        if left <= 12 and right <= 12 and MEETING_CONTEXT_RE.search(context):
            raise PreflightError("原始请求含月/日顺序不明确的会议日期，必须先由用户澄清。")
    for match in MEETING_DATE_RE.finditer(raw_text):
        context = raw_text[max(0, match.start() - 24) : min(len(raw_text), match.end() + 24)]
        if MEETING_CONTEXT_RE.search(context):
            detected.add(("meeting_time", match.start(), match.end()))
    return sorted(detected, key=lambda item: (item[1], item[2], item[0]))


def _verify_request_binding(
    payload: Mapping[str, Any],
    *,
    intake_path: Path,
    now: datetime,
) -> VerifiedRequestBinding:
    reference = payload.get("request_binding")
    if not isinstance(reference, dict):
        raise PreflightError("v3 intake缺少request_binding。")
    raw_path = _binding_file(intake_path.parent, reference.get("raw_request_file"), "raw_request_file")
    receipt_path = _binding_file(intake_path.parent, reference.get("receipt_file"), "receipt_file")
    raw_bytes = _read_regular_bytes(raw_path, maximum=MAX_RAW_REQUEST_BYTES, label="宿主原始请求bundle")
    try:
        raw_text = canonical_raw_request(raw_bytes.decode("utf-8"))
    except UnicodeError as exc:
        raise PreflightError("宿主原始请求bundle不是有效UTF-8文本。") from exc
    canonical_raw = raw_text.encode("utf-8")
    raw_digest = hashlib.sha256(canonical_raw).hexdigest()

    receipt_bytes = _read_regular_bytes(
        receipt_path, maximum=MAX_REQUEST_RECEIPT_BYTES, label="request binding receipt"
    )
    receipt = _parse_json_bytes(receipt_bytes, "request binding receipt")
    if not isinstance(receipt, dict) or set(receipt) != REQUEST_RECEIPT_FIELDS:
        missing = sorted(REQUEST_RECEIPT_FIELDS - set(receipt)) if isinstance(receipt, dict) else []
        extra = sorted(set(receipt) - REQUEST_RECEIPT_FIELDS) if isinstance(receipt, dict) else []
        raise PreflightError(
            "request binding receipt字段不符合v2契约："
            + ("缺少=" + ",".join(missing) if missing else "")
            + ("；" if missing and extra else "")
            + ("未知=" + ",".join(extra) if extra else "")
        )
    if receipt.get("schema") != REQUEST_BINDING_SCHEMA:
        raise PreflightError(f"request binding receipt.schema必须为{REQUEST_BINDING_SCHEMA}。")
    if receipt.get("audience") != REQUEST_BINDING_AUDIENCE:
        raise PreflightError("request binding receipt.audience不匹配。")
    issuer = _clean_binding_id(receipt.get("issuer"), "issuer")
    key_id = _clean_binding_id(receipt.get("key_id"), "key_id")
    receipt_id = _clean_binding_id(receipt.get("receipt_id"), "receipt_id")
    request_bundle_id = _clean_binding_id(receipt.get("request_bundle_id"), "request_bundle_id")
    _clean_binding_id(receipt.get("request_actor_id"), "request_actor_id")
    issued_at = _binding_timestamp(receipt.get("issued_at"), "issued_at")
    expires_at = _binding_timestamp(receipt.get("expires_at"), "expires_at")
    if issued_at > now + timedelta(minutes=5) or expires_at <= now:
        raise PreflightError("request binding receipt尚未生效或已过期。")
    if expires_at <= issued_at or expires_at - issued_at > MAX_REQUEST_RECEIPT_LIFETIME:
        raise PreflightError("request binding receipt有效期无效或超过2小时。")
    receipt_request_id = receipt.get("request_id")
    if not isinstance(receipt_request_id, str) or not REQUEST_ID_RE.fullmatch(receipt_request_id):
        raise PreflightError("request binding receipt.request_id格式无效。")
    if receipt_request_id != payload.get("request_id"):
        raise PreflightError("request binding receipt.request_id与intake不一致。")
    if receipt.get("business_mode") != payload.get("business_mode"):
        raise PreflightError("request binding receipt.business_mode与intake不一致。")
    revision = receipt.get("request_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PreflightError("request binding receipt.request_revision必须是正整数。")
    event_ids = receipt.get("ordered_request_event_ids")
    if (
        not isinstance(event_ids, list)
        or not event_ids
        or any(not isinstance(item, str) or not BINDING_ID_RE.fullmatch(item) for item in event_ids)
        or len(set(event_ids)) != len(event_ids)
    ):
        raise PreflightError("request binding receipt.ordered_request_event_ids必须是有序唯一事件ID数组。")
    if receipt.get("last_user_event_id") != event_ids[-1]:
        raise PreflightError("request binding receipt.last_user_event_id必须等于最后一个请求事件。")
    encoded_current = os.environ.get(CURRENT_REQUEST_CONTEXT_ENV, "").strip()
    if not encoded_current:
        raise PreflightError(
            f"宿主未注入{CURRENT_REQUEST_CONTEXT_ENV}；无法证明request binding对应当前会话头。"
        )
    current_context = _parse_json_bytes(encoded_current.encode("utf-8"), CURRENT_REQUEST_CONTEXT_ENV)
    expected_context_fields = {
        "request_id",
        "business_mode",
        "receipt_id",
        "request_bundle_id",
        "request_revision",
        "last_user_event_id",
        "raw_request_sha256",
    }
    if not isinstance(current_context, dict) or set(current_context) != expected_context_fields:
        raise PreflightError(f"{CURRENT_REQUEST_CONTEXT_ENV}字段不完整或含未知字段。")
    for key in expected_context_fields:
        if current_context.get(key) != receipt.get(key):
            raise PreflightError(f"request binding已脱离当前会话头：{key}不一致。")
    if receipt.get("capture_method") != REQUEST_CAPTURE_METHOD:
        raise PreflightError("request binding receipt.capture_method不是认证宿主消息bundle。")
    if receipt.get("normalization_method") != REQUEST_NORMALIZATION:
        raise PreflightError("request binding receipt.normalization_method不受支持。")
    if receipt.get("coverage_policy") != REQUEST_COVERAGE_POLICY or receipt.get("coverage_complete") is not True:
        raise PreflightError("宿主未证明高影响提及清单完整；初始化和检索已关闭。")
    if (
        receipt.get("safety_directive_policy") != SAFETY_DIRECTIVE_POLICY
        or receipt.get("safety_coverage_complete") is not True
    ):
        raise PreflightError("宿主未证明客户信安全指令清单完整；初始化和检索已关闭。")
    for key in (
        "raw_request_sha256",
        "attachment_manifest_sha256",
        "mention_ledger_sha256",
        "subject_resolution_sha256",
        "safety_authorizations_sha256",
        "safety_directives_sha256",
        "extraction_policy_sha256",
    ):
        if not isinstance(receipt.get(key), str) or not SHA256_RE.fullmatch(str(receipt.get(key))):
            raise PreflightError(f"request binding receipt.{key}必须是SHA-256。")
    if receipt.get("raw_request_sha256") != raw_digest or receipt.get("raw_request_length") != len(canonical_raw):
        raise PreflightError("宿主原始请求bundle与签名收据的摘要或长度不一致。")
    subject_resolution = payload.get("subject_resolution")
    safety_authorizations = payload.get("safety_authorizations")
    if receipt.get("subject_resolution_sha256") != hashlib.sha256(
        canonical_json(subject_resolution).encode("utf-8")
    ).hexdigest():
        raise PreflightError("subject_resolution未被当前宿主request binding精确签名。")
    if receipt.get("safety_authorizations_sha256") != hashlib.sha256(
        canonical_json(safety_authorizations).encode("utf-8")
    ).hexdigest():
        raise PreflightError("safety_authorizations未被当前宿主request binding精确签名。")
    for key in ("attachment_count", "mention_count"):
        value = receipt.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PreflightError(f"request binding receipt.{key}必须是非负整数。")
    for key in ("extractor_id", "extractor_version"):
        _clean_binding_id(receipt.get(key), key)

    mentions = receipt.get("mentions")
    if not isinstance(mentions, list) or len(mentions) != receipt.get("mention_count") or len(mentions) > 200:
        raise PreflightError("request binding receipt.mentions数量与mention_count不一致或超过200项。")
    if hashlib.sha256(canonical_json(mentions).encode("utf-8")).hexdigest() != receipt.get("mention_ledger_sha256"):
        raise PreflightError("request binding receipt的mention ledger摘要不匹配。")
    normalized_mentions: list[dict[str, Any]] = []
    mention_ids: set[str] = set()
    for index, mention in enumerate(mentions):
        label = f"request binding receipt.mentions[{index}]"
        if not isinstance(mention, dict):
            raise PreflightError(f"{label}必须是对象。")
        _validate_exact_keys(mention, MENTION_FIELDS, label)
        mention_id = _clean_binding_id(mention.get("mention_id"), f"mentions[{index}].mention_id")
        if mention_id in mention_ids:
            raise PreflightError(f"request binding receipt.mention_id重复：{mention_id}。")
        mention_ids.add(mention_id)
        slot = mention.get("semantic_slot")
        candidate_field = mention.get("candidate_field")
        status = mention.get("assertion_status")
        if slot not in MENTION_SLOTS:
            raise PreflightError(f"{label}.semantic_slot不受支持。")
        if candidate_field not in MENTION_FIELD_MAP[slot]:
            raise PreflightError(
                f"{label}.candidate_field必须是semantic_slot={slot}允许的精确候选字段。"
            )
        if status not in ACTIVE_ASSERTION_STATUSES | {"negated", "quoted", "superseded"}:
            raise PreflightError(f"{label}.assertion_status不受支持。")
        start, end = mention.get("char_start"), mention.get("char_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(raw_text)
        ):
            raise PreflightError(f"{label}字符范围无效。")
        surface = raw_text[start:end]
        surface_digest = hashlib.sha256(surface.encode("utf-8")).hexdigest()
        if mention.get("surface_sha256") != surface_digest:
            raise PreflightError(f"{label}.surface_sha256与原始请求范围不一致。")
        if mention.get("source_event_id") not in event_ids:
            raise PreflightError(f"{label}.source_event_id不在签名事件序列中。")
        source_ref = mention.get("source_ref")
        if not isinstance(source_ref, str) or not resolved_text(source_ref):
            raise PreflightError(f"{label}.source_ref必须是可定位的非占位文本。")
        normalized_value = mention.get("normalized_value")
        if status == "explicit_unknown":
            if normalized_value is not None:
                raise PreflightError(f"{label}.normalized_value在explicit_unknown时必须为null。")
        elif slot == "meeting_time":
            normalized_value = _validate_time_mention(normalized_value, f"{label}.normalized_value")
        else:
            if not isinstance(normalized_value, str):
                raise PreflightError(f"{label}.normalized_value必须是非占位文本。")
            normalized_value = normalize_text(normalized_value)
            if slot == "meeting_status":
                normalized_value = normalized_value.casefold()
                if normalized_value not in MEETING_STATUSES:
                    raise PreflightError(
                        f"{label}.normalized_value必须是confirmed/tentative/none/unknown之一。"
                    )
            elif not resolved_text(normalized_value):
                raise PreflightError(f"{label}.normalized_value必须是非占位文本。")
            if not _surface_matches_value(surface, normalized_value, slot=slot):
                raise PreflightError(f"{label}.normalized_value与原始请求范围不一致。")
        normalized_mentions.append(
            {
                "mention_id": mention_id,
                "semantic_slot": slot,
                "candidate_field": candidate_field,
                "source_event_id": mention["source_event_id"],
                "char_start": start,
                "char_end": end,
                "surface_sha256": surface_digest,
                "normalized_value": normalized_value,
                "assertion_status": status,
                "source_ref": normalize_text(source_ref),
            }
        )

    safety_directives = receipt.get("safety_directives")
    safety_count = receipt.get("safety_directive_count")
    if (
        not isinstance(safety_directives, list)
        or not isinstance(safety_count, int)
        or isinstance(safety_count, bool)
        or safety_count != len(safety_directives)
        or safety_count > 100
    ):
        raise PreflightError("request binding receipt.safety_directives数量无效或超过100项。")
    if hashlib.sha256(canonical_json(safety_directives).encode("utf-8")).hexdigest() != receipt.get(
        "safety_directives_sha256"
    ):
        raise PreflightError("request binding receipt的safety_directives摘要不匹配。")
    if payload.get("business_mode") != "letter" and safety_directives:
        raise PreflightError("非客户信模式不得携带letter safety directives。")
    normalized_safety_directives: list[dict[str, Any]] = []
    directive_ids: set[str] = set()
    directive_fields = {
        "directive_id",
        "risk_code",
        "assertion_status",
        "source_event_id",
        "char_start",
        "char_end",
        "surface_sha256",
        "source_ref",
        "material_scope_sha256",
    }
    for index, directive in enumerate(safety_directives):
        label = f"request binding receipt.safety_directives[{index}]"
        if not isinstance(directive, dict):
            raise PreflightError(f"{label}必须是对象。")
        _validate_exact_keys(directive, directive_fields, label)
        directive_id = _clean_binding_id(directive.get("directive_id"), f"{label}.directive_id")
        if directive_id in directive_ids:
            raise PreflightError(f"{label}.directive_id重复。")
        directive_ids.add(directive_id)
        risk_code = directive.get("risk_code")
        if risk_code not in LETTER_SAFETY_RISK_CODES:
            raise PreflightError(f"{label}.risk_code不受支持。")
        material_scope_sha256 = directive.get("material_scope_sha256")
        if risk_code in AUTHORIZABLE_SOURCE_RISKS:
            if not isinstance(material_scope_sha256, str) or not SHA256_RE.fullmatch(
                material_scope_sha256
            ):
                raise PreflightError(
                    f"{label}.material_scope_sha256必须绑定当前患者/内部材料范围。"
                )
        elif material_scope_sha256 is not None:
            raise PreflightError(f"{label}非资料授权风险不得携带material_scope_sha256。")
        status = directive.get("assertion_status")
        if status not in ACTIVE_ASSERTION_STATUSES | {"negated", "quoted", "superseded"}:
            raise PreflightError(f"{label}.assertion_status不受支持。")
        start, end = directive.get("char_start"), directive.get("char_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(raw_text)
        ):
            raise PreflightError(f"{label}字符范围无效。")
        surface = raw_text[start:end]
        if directive.get("surface_sha256") != hashlib.sha256(surface.encode("utf-8")).hexdigest():
            raise PreflightError(f"{label}.surface_sha256与原始请求范围不一致。")
        if directive.get("source_event_id") not in event_ids:
            raise PreflightError(f"{label}.source_event_id不在签名事件序列中。")
        source_ref = directive.get("source_ref")
        if not isinstance(source_ref, str) or not resolved_text(source_ref):
            raise PreflightError(f"{label}.source_ref必须是可定位的非占位文本。")
        normalized_safety_directives.append(
            {
                **directive,
                "directive_id": directive_id,
                "source_ref": normalize_text(source_ref),
            }
        )

    obvious = _obvious_mentions(raw_text)
    uncovered_obvious: list[tuple[str, int, int]] = []
    for slot, start, end in obvious:
        surface = raw_text[start:end]
        covered = False
        for item in normalized_mentions:
            if item["semantic_slot"] != slot:
                continue
            if slot == "organization":
                obvious_value = normalize_text(surface).casefold()
                ledger_value = normalize_text(item["normalized_value"]).casefold()
                if (
                    int(item["char_start"]) <= start
                    and int(item["char_end"]) >= end
                    and bool(obvious_value and ledger_value and obvious_value in ledger_value)
                ):
                    covered = True
                    break
            elif int(item["char_start"]) == start and int(item["char_end"]) == end:
                covered = True
                break
        if not covered:
            uncovered_obvious.append((slot, start, end))
    if uncovered_obvious:
        raise PreflightError("签名mention ledger遗漏原始请求中可确定的机构或会议日期提及。")

    signature_text = receipt.get("signature")
    try:
        signature = base64.b64decode(str(signature_text), validate=True)
        if len(signature) != 64:
            raise ValueError("signature length")
        signed_payload = {key: receipt[key] for key in sorted(receipt) if key != "signature"}
        _trusted_request_key(issuer, key_id).verify(
            signature, canonical_json(signed_payload).encode("utf-8")
        )
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise PreflightError("request binding receipt的宿主Ed25519签名无效。") from exc

    reference_pairs = (
        ("receipt_id", receipt_id),
        ("request_bundle_id", request_bundle_id),
        ("request_revision", revision),
        ("raw_request_sha256", raw_digest),
    )
    for key, expected in reference_pairs:
        if reference.get(key) != expected:
            raise PreflightError(f"intake.request_binding.{key}与宿主签名收据不一致。")
    return VerifiedRequestBinding(
        receipt_id=receipt_id,
        request_bundle_id=request_bundle_id,
        request_revision=revision,
        issuer=issuer,
        key_id=key_id,
        receipt_sha256=hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest(),
        raw_request_sha256=raw_digest,
        mention_ledger_sha256=str(receipt["mention_ledger_sha256"]),
        subject_resolution_sha256=str(receipt["subject_resolution_sha256"]),
        safety_authorizations_sha256=str(receipt["safety_authorizations_sha256"]),
        safety_directives_sha256=str(receipt["safety_directives_sha256"]),
        expires_at=expires_at,
        mentions=tuple(normalized_mentions),
        safety_directives=tuple(normalized_safety_directives),
        raw_request_text=raw_text,
    )


def _validate_exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PreflightError(f"{label}含未知字段：{', '.join(unknown)}。")


def _canonical_time_range(value: Any, label: str) -> tuple[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise PreflightError(f"{label}的meeting_time.value必须是start/end时间段对象。")
    _validate_exact_keys(value, {"start", "end", "timezone"}, f"{label}.value")
    if set(value) < {"start", "end"}:
        raise PreflightError(f"{label}.value必须包含start和end。")
    start = parse_timestamp(value.get("start"), f"{label}.value.start")
    end = parse_timestamp(value.get("end"), f"{label}.value.end")
    if end <= start:
        raise PreflightError(f"{label}.value.end必须晚于start。")
    if end - start > timedelta(hours=24):
        raise PreflightError(f"{label}.value时间跨度不得超过24小时。")
    timezone_name = normalize_text(value.get("timezone"))
    normalized = {
        "start": isoformat(start),
        "end": isoformat(end),
    }
    if timezone_name:
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise PreflightError(f"{label}.value.timezone必须是有效IANA时区。") from exc
        original_start = datetime.fromisoformat(str(value.get("start")).strip().replace("Z", "+00:00"))
        original_end = datetime.fromisoformat(str(value.get("end")).strip().replace("Z", "+00:00"))
        if (
            original_start.utcoffset() != start.astimezone(zone).utcoffset()
            or original_end.utcoffset() != end.astimezone(zone).utcoffset()
        ):
            raise PreflightError(f"{label}.value.timezone与start/end的UTC offset不一致。")
        normalized["timezone"] = timezone_name
    comparison = canonical_json({"start": isoformat(start), "end": isoformat(end)})
    return comparison, normalized


def _candidate_key(field: str, candidate: Mapping[str, Any], label: str) -> tuple[str, Any]:
    status = candidate["status"]
    value = candidate["value"]
    if field == "meeting_status":
        if status != "asserted":
            raise PreflightError(
                f"{label}的meeting_status必须用asserted和"
                "confirmed/tentative/none/unknown之一表达。"
            )
        normalized_status = normalize_text(value).casefold()
        if normalized_status not in MEETING_STATUSES:
            raise PreflightError(
                f"{label}.value必须是confirmed/tentative/none/unknown之一。"
            )
        return normalized_status, normalized_status
    if status == "explicit_unknown":
        if value is not None:
            raise PreflightError(f"{label}.value在explicit_unknown时必须为null。")
        return "__explicit_unknown__", None
    if field == "meeting_time":
        return _canonical_time_range(value, label)
    if not isinstance(value, str) or not resolved_text(value):
        raise PreflightError(f"{label}.value必须是非占位文本。")
    normalized = normalize_text(value)
    return normalized.casefold(), normalized


def _canonical_subject_name(value: object) -> str:
    normalized = normalize_text(value)
    if not resolved_text(normalized):
        raise PreflightError("subject_resolution.canonical_customer_name必须是已解析的规范主体。")
    return normalized


def _canonical_subject_digest(customer_name: str, entity_key: str, jurisdiction: str) -> str:
    payload = {
        "canonical_customer_name": customer_name,
        "canonical_entity_key": entity_key,
        "jurisdiction": jurisdiction,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_subject_resolution(value: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreflightError("v3 intake必须包含宿主签名的subject_resolution对象。")
    expected = {
        "schema",
        "attestation_id",
        "issuer",
        "customer_id",
        "canonical_customer_name",
        "canonical_entity_key",
        "jurisdiction",
        "canonical_subject_sha256",
        "organization_scope_sha256",
        "id_source",
        "evidence_sha256",
        "issued_at",
        "expires_at",
    }
    _validate_exact_keys(value, expected, "intake.subject_resolution")
    if value.get("schema") != SUBJECT_RESOLUTION_SCHEMA:
        raise PreflightError(f"subject_resolution.schema必须为{SUBJECT_RESOLUTION_SCHEMA}。")
    for key in ("attestation_id", "issuer", "customer_id", "canonical_entity_key", "jurisdiction"):
        if not isinstance(value.get(key), str) or not BINDING_ID_RE.fullmatch(str(value.get(key))):
            raise PreflightError(f"subject_resolution.{key}格式无效。")
    canonical_name = _canonical_subject_name(value.get("canonical_customer_name"))
    subject_sha = _canonical_subject_digest(
        canonical_name,
        str(value.get("canonical_entity_key")),
        str(value.get("jurisdiction")),
    )
    if value.get("canonical_subject_sha256") != subject_sha:
        raise PreflightError("subject_resolution.canonical_subject_sha256与规范主体不一致。")
    for key in ("organization_scope_sha256", "evidence_sha256"):
        if not isinstance(value.get(key), str) or not SHA256_RE.fullmatch(str(value.get(key))):
            raise PreflightError(f"subject_resolution.{key}必须是SHA-256。")
    id_source = value.get("id_source")
    if id_source not in SUBJECT_ID_SOURCES:
        raise PreflightError("subject_resolution.id_source不受支持。")
    if id_source == "canonical_derived" and value.get("customer_id") != "cust-" + subject_sha[:12]:
        raise PreflightError("canonical_derived customer_id与规范主体不一致。")
    issued_at = _binding_timestamp(value.get("issued_at"), "subject_resolution.issued_at")
    expires_at = _binding_timestamp(value.get("expires_at"), "subject_resolution.expires_at")
    if issued_at > now + timedelta(minutes=5) or expires_at <= now:
        raise PreflightError("subject_resolution尚未生效或已过期。")
    if expires_at <= issued_at or expires_at - issued_at > timedelta(days=30):
        raise PreflightError("subject_resolution有效期无效或超过30天。")
    return {
        **value,
        "canonical_customer_name": canonical_name,
        "issued_at": isoformat(issued_at),
        "expires_at": isoformat(expires_at),
    }


def _validate_safety_authorizations(value: Any, *, now: datetime) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > len(AUTHORIZABLE_SOURCE_RISKS):
        raise PreflightError("safety_authorizations必须是至多2项的数组。")
    expected = {
        "schema",
        "authorization_id",
        "issuer",
        "risk_code",
        "subject_sha256",
        "request_bundle_id",
        "request_revision",
        "material_scope_sha256",
        "purpose",
        "external_allowed",
        "evidence_sha256",
        "issued_at",
        "expires_at",
    }
    normalized: list[dict[str, Any]] = []
    codes: set[str] = set()
    for index, item in enumerate(value):
        label = f"intake.safety_authorizations[{index}]"
        if not isinstance(item, dict):
            raise PreflightError(f"{label}必须是对象。")
        _validate_exact_keys(item, expected, label)
        if item.get("schema") != SAFETY_AUTHORIZATION_SCHEMA:
            raise PreflightError(f"{label}.schema无效。")
        for key in ("authorization_id", "issuer"):
            if not isinstance(item.get(key), str) or not BINDING_ID_RE.fullmatch(str(item.get(key))):
                raise PreflightError(f"{label}.{key}格式无效。")
        code = item.get("risk_code")
        if code not in AUTHORIZABLE_SOURCE_RISKS or code in codes:
            raise PreflightError(f"{label}.risk_code无效或重复。")
        codes.add(str(code))
        if item.get("purpose") != "internal_review_draft" or item.get("external_allowed") is not False:
            raise PreflightError(f"{label}只能授权内部待审核稿且external_allowed必须为false。")
        if not isinstance(item.get("request_bundle_id"), str) or not BINDING_ID_RE.fullmatch(
            str(item.get("request_bundle_id"))
        ):
            raise PreflightError(f"{label}.request_bundle_id格式无效。")
        revision = item.get("request_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise PreflightError(f"{label}.request_revision必须是正整数。")
        for key in ("subject_sha256", "material_scope_sha256", "evidence_sha256"):
            if not isinstance(item.get(key), str) or not SHA256_RE.fullmatch(str(item.get(key))):
                raise PreflightError(f"{label}.{key}必须是SHA-256。")
        issued_at = _binding_timestamp(item.get("issued_at"), f"{label}.issued_at")
        expires_at = _binding_timestamp(item.get("expires_at"), f"{label}.expires_at")
        if issued_at > now + timedelta(minutes=5) or expires_at <= now:
            raise PreflightError(f"{label}尚未生效或已过期。")
        if expires_at <= issued_at or expires_at - issued_at > timedelta(days=30):
            raise PreflightError(f"{label}有效期无效或超过30天。")
        normalized.append({**item, "issued_at": isoformat(issued_at), "expires_at": isoformat(expires_at)})
    return normalized


def validate_intake(payload: Any, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PreflightError("intake根节点必须是JSON对象。")
    schema = payload.get("schema")
    if schema not in {INPUT_SCHEMA, *LEGACY_INPUT_SCHEMAS}:
        raise PreflightError(
            f"schema必须为{INPUT_SCHEMA}；{', '.join(sorted(LEGACY_INPUT_SCHEMAS))}仅可诊断读取。"
        )
    allowed_keys = {"schema", "request_id", "business_mode", "candidate_sets", "confirmations"}
    if schema in {INPUT_SCHEMA, BOUND_LEGACY_INPUT_SCHEMA}:
        allowed_keys.add("request_binding")
    if schema == INPUT_SCHEMA:
        allowed_keys.update({"subject_resolution", "safety_authorizations"})
    _validate_exact_keys(
        payload,
        allowed_keys,
        "intake",
    )
    if schema in {INPUT_SCHEMA, BOUND_LEGACY_INPUT_SCHEMA}:
        reference = payload.get("request_binding")
        if not isinstance(reference, dict):
            raise PreflightError(f"{schema}必须包含request_binding对象。")
        _validate_exact_keys(
            reference,
            {
                "receipt_id",
                "request_bundle_id",
                "request_revision",
                "raw_request_sha256",
                "raw_request_file",
                "receipt_file",
            },
            "intake.request_binding",
        )
        missing_binding = {
            "receipt_id",
            "request_bundle_id",
            "request_revision",
            "raw_request_sha256",
            "raw_request_file",
            "receipt_file",
        } - set(reference)
        if missing_binding:
            raise PreflightError(
                "intake.request_binding缺少：" + ", ".join(sorted(missing_binding)) + "。"
            )
        for key in ("receipt_id", "request_bundle_id"):
            if not isinstance(reference.get(key), str) or not BINDING_ID_RE.fullmatch(str(reference.get(key))):
                raise PreflightError(f"intake.request_binding.{key}格式无效。")
        if (
            not isinstance(reference.get("request_revision"), int)
            or isinstance(reference.get("request_revision"), bool)
            or reference.get("request_revision") < 1
        ):
            raise PreflightError("intake.request_binding.request_revision必须是正整数。")
        if not isinstance(reference.get("raw_request_sha256"), str) or not SHA256_RE.fullmatch(
            str(reference.get("raw_request_sha256"))
        ):
            raise PreflightError("intake.request_binding.raw_request_sha256必须是SHA-256。")
        for key in ("raw_request_file", "receipt_file"):
            value = reference.get(key)
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 255
                or Path(value).name != value
                or Path(value).is_absolute()
            ):
                raise PreflightError(f"intake.request_binding.{key}只能是intake同目录文件名。")
        if schema == INPUT_SCHEMA:
            subject_resolution = _validate_subject_resolution(
                payload.get("subject_resolution"),
                now=now or utc_now(),
            )
            safety_authorizations = _validate_safety_authorizations(
                payload.get("safety_authorizations"),
                now=now or utc_now(),
            )
        else:
            subject_resolution = None
            safety_authorizations = []
    else:
        subject_resolution = None
        safety_authorizations = []
    business_mode = payload.get("business_mode")
    if business_mode not in BUSINESS_MODES:
        raise PreflightError("business_mode必须是briefing/standard_visit/strategic_account/letter。")
    request_id = payload.get("request_id", "")
    if request_id and (not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id)):
        raise PreflightError("request_id只能包含3—128位字母、数字、点、下划线或连字符。")
    if schema in {INPUT_SCHEMA, BOUND_LEGACY_INPUT_SCHEMA} and not request_id:
        raise PreflightError(f"{schema}.request_id必须绑定当前宿主请求。")
    candidate_sets = payload.get("candidate_sets")
    if not isinstance(candidate_sets, list) or not candidate_sets:
        raise PreflightError("candidate_sets必须是非空数组。")
    confirmations = payload.get("confirmations", [])
    if not isinstance(confirmations, list):
        raise PreflightError("confirmations必须是数组。")
    if confirmations:
        raise PreflightError(
            "intake内嵌confirmations不具备可信宿主身份，不能消解冲突；"
            "请由认证宿主核验用户回合后重建只保留已确认候选的新intake。"
        )

    fields: dict[str, dict[str, Any]] = {}
    all_candidate_ids: set[str] = set()
    for set_index, candidate_set in enumerate(candidate_sets):
        label = f"candidate_sets[{set_index}]"
        if not isinstance(candidate_set, dict):
            raise PreflightError(f"{label}必须是对象。")
        _validate_exact_keys(candidate_set, {"field", "candidates"}, label)
        field = candidate_set.get("field")
        if field not in SUPPORTED_FIELDS:
            raise PreflightError(f"{label}.field不受支持：{field!r}。")
        if field in fields:
            raise PreflightError(f"field重复：{field}。")
        candidates = candidate_set.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PreflightError(f"{label}.candidates必须是非空数组。")
        normalized_candidates: list[dict[str, Any]] = []
        for candidate_index, candidate in enumerate(candidates):
            candidate_label = f"{label}.candidates[{candidate_index}]"
            if not isinstance(candidate, dict):
                raise PreflightError(f"{candidate_label}必须是对象。")
            candidate_fields = {"candidate_id", "value", "status", "source_ref"}
            if schema == INPUT_SCHEMA:
                candidate_fields.add("mention_ids")
            _validate_exact_keys(
                candidate,
                candidate_fields,
                candidate_label,
            )
            missing = sorted(candidate_fields - set(candidate))
            if missing:
                raise PreflightError(f"{candidate_label}缺少：{', '.join(missing)}。")
            candidate_id = candidate["candidate_id"]
            if not isinstance(candidate_id, str) or not REQUEST_ID_RE.fullmatch(candidate_id):
                raise PreflightError(f"{candidate_label}.candidate_id格式无效。")
            if candidate_id in all_candidate_ids:
                raise PreflightError(f"candidate_id重复：{candidate_id}。")
            all_candidate_ids.add(candidate_id)
            if candidate["status"] not in {"asserted", "explicit_unknown"}:
                raise PreflightError(f"{candidate_label}.status只能是asserted或explicit_unknown。")
            source_ref = candidate["source_ref"]
            if not isinstance(source_ref, str) or not resolved_text(source_ref):
                raise PreflightError(f"{candidate_label}.source_ref必须是可定位的非占位文本。")
            mention_ids: list[str] = []
            if schema == INPUT_SCHEMA:
                raw_mention_ids = candidate.get("mention_ids")
                if (
                    not isinstance(raw_mention_ids, list)
                    or len(raw_mention_ids) > 200
                    or any(
                        not isinstance(mention_id, str)
                        or not BINDING_ID_RE.fullmatch(mention_id)
                        for mention_id in raw_mention_ids
                    )
                    or len(raw_mention_ids) != len(set(raw_mention_ids))
                ):
                    raise PreflightError(
                        f"{candidate_label}.mention_ids必须是不超过200项的唯一签名mention ID数组。"
                    )
                mention_ids = sorted(raw_mention_ids)
            comparison_key, normalized_value = _candidate_key(field, candidate, candidate_label)
            normalized_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "value": normalized_value,
                    "status": candidate["status"],
                    "source_ref": normalize_text(source_ref),
                    "mention_ids": mention_ids,
                    "comparison_key": comparison_key,
                }
            )
        fields[field] = {"candidates": normalized_candidates}

    return {
        "schema": schema,
        "request_id": request_id,
        "business_mode": business_mode,
        "fields": fields,
        "confirmations": {},
        "subject_resolution": subject_resolution,
        "safety_authorizations": safety_authorizations,
    }


def _group_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(str(candidate["comparison_key"]), []).append(candidate)
    return [
        sorted(group, key=lambda item: str(item["candidate_id"]))
        for _, group in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _selected_entry(
    candidates: Sequence[Mapping[str, Any]],
    *,
    basis: str,
    confirmation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = sorted(candidates, key=lambda item: str(item["candidate_id"]))
    value_groups = _group_candidates(ordered)
    entry: dict[str, Any] = {
        "values": [group[0]["value"] for group in value_groups],
        "candidate_ids": [candidate["candidate_id"] for candidate in ordered],
        "source_refs": sorted({str(candidate["source_ref"]) for candidate in ordered}),
        "selection_basis": basis,
    }
    if confirmation:
        entry["confirmation_ref"] = confirmation["confirmation_ref"]
        entry["confirmed_at"] = confirmation["confirmed_at"]
    return entry


def _display_value(candidate: Mapping[str, Any]) -> str:
    if candidate["status"] == "explicit_unknown":
        return "暂不清楚"
    value = candidate["value"]
    if isinstance(value, dict) and {"start", "end"} <= set(value):
        return f"{value['start']}—{value['end']}"
    return str(value)


def _conflict_question(field: str, groups: Sequence[Sequence[Mapping[str, Any]]]) -> str:
    choices: list[str] = []
    for index, group in enumerate(groups, 1):
        representative = group[0]
        refs = "、".join(sorted({str(item["source_ref"]) for item in group}))
        choices.append(f"{index}. {_display_value(representative)}（{refs}）")
    return f"请确认{FIELD_LABELS[field]}采用哪一项：" + "；".join(choices) + "。"


def _text_candidate_matches(mention_value: str, candidate_value: Any) -> bool:
    if not isinstance(candidate_value, str):
        return False
    left = normalize_text(mention_value).casefold()
    right = normalize_text(candidate_value).casefold()
    return bool(left and right and left == right)


def _time_candidate_matches(mention_value: Mapping[str, Any], candidate_value: Any) -> bool:
    if not isinstance(candidate_value, dict):
        return False
    # A point-in-time mention is not evidence for a model-supplied range.  The
    # host must sign both ends (and any timezone/date anchor) before a range can
    # become an asserted candidate.
    if not mention_value.get("end"):
        return False
    if (
        mention_value.get("start") != candidate_value.get("start")
        or mention_value.get("end") != candidate_value.get("end")
        or (mention_value.get("timezone") or None)
        != (candidate_value.get("timezone") or None)
    ):
        return False
    date_anchor = mention_value.get("date_anchor")
    if date_anchor:
        timezone_name = mention_value.get("timezone")
        if not isinstance(timezone_name, str) or not timezone_name:
            return False
        try:
            from zoneinfo import ZoneInfo

            local_date = parse_timestamp(
                candidate_value.get("start"), "candidate meeting_time.start"
            ).astimezone(ZoneInfo(timezone_name)).date().isoformat()
        except (PreflightError, ValueError):
            return False
        if local_date != date_anchor:
            return False
    return True


def _candidate_binding_error(
    mention: Mapping[str, Any],
    *,
    field: str,
    candidate: Mapping[str, Any],
) -> str | None:
    if mention.get("candidate_field") != field:
        return "candidate_field_mismatch"
    mention_status = mention.get("assertion_status")
    candidate_status = candidate.get("status")
    if mention_status != candidate_status:
        return "assertion_status_mismatch"
    if mention_status == "explicit_unknown":
        return None if candidate.get("value") is None else "explicit_unknown_value_mismatch"
    if mention_status != "asserted":
        return "nonasserted_mention_cannot_authorize_candidate"
    slot = str(mention.get("semantic_slot", ""))
    value_matches = (
        _time_candidate_matches(mention.get("normalized_value", {}), candidate.get("value"))
        if slot == "meeting_time" and isinstance(mention.get("normalized_value"), Mapping)
        else _text_candidate_matches(str(mention.get("normalized_value", "")), candidate.get("value"))
    )
    return None if value_matches else "normalized_value_mismatch"


def _request_coverage(
    validated: Mapping[str, Any],
    binding: VerifiedRequestBinding,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]], list[dict[str, Any]]]:
    """Bind each active signed occurrence to exactly one semantically equal candidate."""
    uncovered: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    fields = validated.get("fields", {})
    mention_by_id = {str(item["mention_id"]): item for item in binding.mentions}
    valid_claims: dict[str, list[tuple[str, str]]] = {}
    all_claims: dict[str, list[tuple[str, str]]] = {}
    unsigned_candidates: list[dict[str, Any]] = []

    if isinstance(fields, dict):
        for field in sorted(SIGNED_CANDIDATE_FIELDS):
            record = fields.get(field)
            candidates = record.get("candidates", []) if isinstance(record, dict) else []
            for candidate in candidates:
                candidate_id = str(candidate.get("candidate_id", ""))
                mention_ids = candidate.get("mention_ids", [])
                binding_errors: list[dict[str, str]] = []
                candidate_valid_ids: list[str] = []
                for mention_id in mention_ids if isinstance(mention_ids, list) else []:
                    all_claims.setdefault(str(mention_id), []).append((field, candidate_id))
                    mention = mention_by_id.get(str(mention_id))
                    if mention is None:
                        binding_errors.append(
                            {"mention_id": str(mention_id), "reason": "unknown_mention_id"}
                        )
                        continue
                    error = _candidate_binding_error(
                        mention,
                        field=field,
                        candidate=candidate,
                    )
                    if error is not None:
                        binding_errors.append({"mention_id": str(mention_id), "reason": error})
                    else:
                        candidate_valid_ids.append(str(mention_id))
                if not mention_ids:
                    binding_errors.append({"mention_id": "", "reason": "mention_ids_missing"})
                if binding_errors:
                    unsigned_candidates.append(
                        {
                            "field": field,
                            "candidate_id": candidate_id,
                            "value": candidate.get("value"),
                            "status": candidate.get("status"),
                            "source_ref": candidate.get("source_ref"),
                            "binding_errors": binding_errors,
                        }
                    )
                    continue
                for mention_id in candidate_valid_ids:
                    valid_claims.setdefault(mention_id, []).append((field, candidate_id))

    for mention in binding.mentions:
        slot = str(mention["semantic_slot"])
        mention_id = str(mention["mention_id"])
        candidate_ids = [candidate_id for _, candidate_id in valid_claims.get(mention_id, [])]
        if mention["assertion_status"] in ACTIVE_ASSERTION_STATUSES:
            if not candidate_ids:
                uncovered.append(
                    {
                        "mention_id": mention_id,
                        "semantic_slot": slot,
                        "candidate_field": mention["candidate_field"],
                        "normalized_value": mention["normalized_value"],
                        "assertion_status": mention["assertion_status"],
                        "source_ref": mention["source_ref"],
                    }
                )
        ledger.append(
            {
                "mention_id": mention_id,
                "semantic_slot": slot,
                "candidate_field": mention["candidate_field"],
                "assertion_status": mention["assertion_status"],
                "source_ref": mention["source_ref"],
                "surface_sha256": mention["surface_sha256"],
                "candidate_ids": sorted(set(candidate_ids)),
                "coverage_status": (
                    "represented"
                    if candidate_ids
                    else "not_applicable"
                    if mention["assertion_status"] not in ACTIVE_ASSERTION_STATUSES
                    else "unrepresented"
                ),
            }
        )
    reused_mentions = [
        {
            "mention_id": mention_id,
            "candidate_claims": [
                {"field": field, "candidate_id": candidate_id}
                for field, candidate_id in sorted(set(claims))
            ],
        }
        for mention_id, claims in sorted(all_claims.items())
        if len(set(claims)) > 1
    ]
    if not uncovered and not unsigned_candidates and not reused_mentions:
        return [], [], ledger
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for mention in uncovered:
        by_slot.setdefault(str(mention["semantic_slot"]), []).append(mention)
    conflicts = [
        {
            "field": "request_binding",
            "field_label": "原始请求覆盖",
            "code": "raw_mentions_unrepresented",
            "semantic_slot": slot,
            "mentions": values,
        }
        for slot, values in sorted(by_slot.items())
    ]
    if unsigned_candidates:
        conflicts.append(
            {
                "field": "request_binding",
                "field_label": "原始请求覆盖",
                "code": "candidate_without_signed_occurrence",
                "candidates": unsigned_candidates,
            }
        )
    if reused_mentions:
        conflicts.append(
            {
                "field": "request_binding",
                "field_label": "原始请求覆盖",
                "code": "signed_mention_reused",
                "mentions": reused_mentions,
            }
        )
    slot_labels = {
        "organization": "客户/机构",
        "person": "人物",
        "role": "职务/层级",
        "meeting_time": "会议时间",
        "project_id": "项目范围",
    }
    summary = "、".join(
        f"{slot_labels.get(slot, slot)}{len(values)}项" for slot, values in sorted(by_slot.items())
    )
    if unsigned_candidates:
        unsigned_summary = f"候选{len(unsigned_candidates)}项缺少宿主签名原文提及"
        summary = "、".join(value for value in (summary, unsigned_summary) if value)
    if reused_mentions:
        reuse_summary = f"签名提及{len(reused_mentions)}项被多候选复用"
        summary = "、".join(value for value in (summary, reuse_summary) if value)
    questions = [
        (
            "request_binding",
            f"原始请求中有{summary}未进入结构化候选；请保留全部提及并确认冲突后重试。",
        )
    ]
    return conflicts, questions, ledger


def _one_conflict_question(
    conflicts: Sequence[Mapping[str, Any]],
    question_pairs: Sequence[tuple[str, str]],
) -> dict[str, str]:
    """Return one actionable question for all unresolved conflicts.

    Conflict resolution is intentionally serialized ahead of ordinary missing
    fields: choosing a subject, date, target or other disputed value can change
    which remaining fields are actually required.  Asking those speculative
    follow-ups in the same turn creates inconsistent T2 behavior and needless
    user burden.
    """

    fields = [
        str(item.get("field", ""))
        for item in conflicts
        if item.get("code") != "unsafe_letter_request" and str(item.get("field", ""))
    ]
    unique_fields = list(dict.fromkeys(fields))
    question_by_field = dict(question_pairs)
    if "request_binding" in unique_fields:
        return {
            "field": "request_binding",
            "question": question_by_field.get(
                "request_binding",
                "请由认证宿主重新捕获完整原始请求并重签intake后再继续。",
            ),
        }

    subject_fields = {"customer_name", "organization_scope"}
    date_fields = {"meeting_time", "meeting_status"}
    if subject_fields.intersection(unique_fields) and date_fields.intersection(unique_fields):
        return {
            "field": "identity_and_date",
            "question": "请一次性确认唯一客户主体或机构范围，以及唯一会议日期时间；认证宿主核验后重建intake。",
        }

    if len(unique_fields) == 1:
        field = unique_fields[0]
        return {
            "field": field,
            "question": question_by_field.get(
                field,
                f"请确认{FIELD_LABELS.get(field, field)}的唯一口径。",
            ),
        }

    labels = [FIELD_LABELS.get(field, field) for field in unique_fields]
    return {
        "field": "conflict_resolution",
        "question": "请一次性确认以下冲突项的唯一口径：" + "、".join(labels) + "。",
    }


def evaluate_intake(
    payload: Any,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    request_binding: VerifiedRequestBinding | None = None,
    require_request_binding: bool = False,
) -> dict[str, Any]:
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise PreflightError(f"ttl_seconds必须在{MIN_TTL_SECONDS}—{MAX_TTL_SECONDS}之间。")
    current = (now or utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    validated = validate_intake(payload, now=current)
    if require_request_binding and validated["schema"] != INPUT_SCHEMA:
        raise PreflightError(
            "旧intake仅可诊断读取；初始化和检索必须迁移为"
            f"{INPUT_SCHEMA}及{REQUEST_BINDING_SCHEMA}。"
        )
    if require_request_binding and request_binding is None:
        raise PreflightError("缺少已验证的宿主request binding；初始化和检索已关闭。")
    selected_values: dict[str, dict[str, Any]] = {}
    blocking_conflicts: list[dict[str, Any]] = []
    question_pairs: list[tuple[str, str]] = []

    for field in FIELD_LABELS:
        record = validated["fields"].get(field)
        if not record:
            continue
        candidates = record["candidates"]
        groups = _group_candidates(candidates)
        confirmation = validated["confirmations"].get(field)
        if confirmation:
            selected_ids = set(confirmation["selected_candidate_ids"])
            chosen = [candidate for candidate in candidates if candidate["candidate_id"] in selected_ids]
            selected_values[field] = _selected_entry(
                chosen,
                basis="user_confirmation",
                confirmation=confirmation,
            )
            continue
        if len(groups) == 1:
            selected_values[field] = _selected_entry(groups[0], basis="single_value")
            continue
        blocking_conflicts.append(
            {
                "field": field,
                "field_label": FIELD_LABELS[field],
                "code": "conflicting_candidates",
                "candidate_groups": [
                    {
                        "candidate_ids": [item["candidate_id"] for item in group],
                        "values": [item["value"] for item in group],
                        "source_refs": sorted({str(item["source_ref"]) for item in group}),
                    }
                    for group in groups
                ],
            }
        )
        question_pairs.append((field, _conflict_question(field, groups)))

    if "organization_scope" not in selected_values and "customer_name" in selected_values:
        customer = selected_values["customer_name"]
        selected_values["organization_scope"] = {
            "values": list(customer["values"]),
            "candidate_ids": list(customer["candidate_ids"]),
            "source_refs": list(customer["source_refs"]),
            "selection_basis": "default_from_customer_name",
        }

    subject_resolution = validated.get("subject_resolution")
    safety_authorizations = validated.get("safety_authorizations", [])
    authorized_source_risks: set[str] = set()
    if request_binding is not None:
        if not isinstance(subject_resolution, dict):
            raise PreflightError("宿主签名intake缺少subject_resolution。")
        customer_values = selected_values.get("customer_name", {}).get("values", [])
        scope_values = selected_values.get("organization_scope", {}).get("values", [])
        if len(customer_values) == 1 and subject_resolution.get("canonical_customer_name") != customer_values[0]:
            raise PreflightError("subject_resolution与唯一客户主体不一致。")
        if len(scope_values) == 1 and subject_resolution.get("organization_scope_sha256") != hashlib.sha256(
            str(scope_values[0]).encode("utf-8")
        ).hexdigest():
            raise PreflightError("subject_resolution与organization_scope不一致。")
        if subject_resolution.get("issuer") != request_binding.issuer:
            raise PreflightError("subject_resolution.issuer与request binding签发者不一致。")
        subject_sha = str(subject_resolution.get("canonical_subject_sha256", ""))
        for authorization in safety_authorizations:
            if authorization.get("issuer") != request_binding.issuer:
                raise PreflightError("safety_authorization.issuer与request binding签发者不一致。")
            if authorization.get("subject_sha256") != subject_sha:
                raise PreflightError("safety_authorization未绑定当前规范主体。")
            if authorization.get("request_bundle_id") != request_binding.request_bundle_id:
                raise PreflightError("safety_authorization未绑定当前request bundle。")
            if authorization.get("request_revision") != request_binding.request_revision:
                raise PreflightError("safety_authorization未绑定当前request revision。")
            risk_code = str(authorization["risk_code"])
            active_material_scopes = {
                str(item.get("material_scope_sha256"))
                for item in request_binding.safety_directives
                if item.get("risk_code") == risk_code
                and item.get("assertion_status") in ACTIVE_ASSERTION_STATUSES
            }
            if active_material_scopes and active_material_scopes != {
                str(authorization.get("material_scope_sha256"))
            }:
                raise PreflightError(
                    "safety_authorization.material_scope_sha256未覆盖当前签名材料范围。"
                )
            authorized_source_risks.add(risk_code)

    missing_requirements: list[dict[str, Any]] = []
    if "customer_name" not in selected_values:
        missing_requirements.append(
            {
                "field": "customer_name",
                "code": "required_value_missing",
                "message": "客户主体尚未形成唯一值。",
            }
        )
        if not any(field == "customer_name" for field, _ in question_pairs):
            question_pairs.append(("customer_name", "请确认本次研究对应的客户规范名称。"))

    mode = validated["business_mode"]
    strategy_variant = ""
    if mode == "strategic_account":
        status_record = selected_values.get("meeting_status", {})
        status_values = status_record.get("values", []) if isinstance(status_record, dict) else []
        meeting_status = (
            str(status_values[0])
            if len(status_values) == 1 and status_values[0] in MEETING_STATUSES
            else ""
        )
        meeting_record = selected_values.get("meeting_time", {})
        meeting_values = meeting_record.get("values", []) if isinstance(meeting_record, dict) else []
        exact_meeting_time = bool(
            len(meeting_values) == 1
            and isinstance(meeting_values[0], dict)
            and {"start", "end"} <= set(meeting_values[0])
        )
        status_time_conflict = meeting_status in {"none", "unknown"} and exact_meeting_time
        if status_time_conflict:
            blocking_conflicts.append(
                {
                    "field": "meeting_status",
                    "field_label": FIELD_LABELS["meeting_status"],
                    "code": "meeting_status_time_conflict",
                    "candidate_groups": [
                        {
                            "candidate_ids": list(status_record.get("candidate_ids", [])),
                            "values": [meeting_status],
                            "source_refs": list(status_record.get("source_refs", [])),
                        },
                        {
                            "candidate_ids": list(meeting_record.get("candidate_ids", [])),
                            "values": list(meeting_values),
                            "source_refs": list(meeting_record.get("source_refs", [])),
                        },
                    ],
                }
            )
            question_pairs.append(
                (
                    "meeting_status",
                    "会议状态为无会议或未知，但同时存在确切时间；请确认会议是否已确定，认证宿主核验后重建intake。",
                )
            )

        # meeting_status is authoritative when supplied.  A confirmed meeting
        # selects visit preparation even when its exact time is still unknown;
        # tentative stays in account planning until confirmation.  For legacy
        # inputs without meeting_status, an exact time range remains the only
        # meeting fact that can select scheduled_visit.  Target/objective alone
        # never establish that a meeting exists.
        if meeting_status:
            derived_variant = MEETING_STATUS_VARIANTS[meeting_status]
        else:
            derived_variant = "scheduled_visit" if exact_meeting_time else "account_planning"
        variant_record = selected_values.get("strategy_variant")
        if variant_record:
            variant_values = variant_record.get("values", [])
            if len(variant_values) == 1 and variant_values[0] in {"scheduled_visit", "account_planning"}:
                strategy_variant = str(variant_values[0])
                if strategy_variant != derived_variant:
                    blocking_conflicts.append(
                        {
                            "field": "strategy_variant",
                            "field_label": FIELD_LABELS["strategy_variant"],
                            "code": "strategy_variant_fact_conflict",
                            "candidate_groups": [
                                {
                                    "candidate_ids": list(variant_record.get("candidate_ids", [])),
                                    "values": [strategy_variant],
                                    "source_refs": list(variant_record.get("source_refs", [])),
                                },
                                {
                                    "candidate_ids": [],
                                    "values": [derived_variant],
                                    "source_refs": (
                                        ["结构化会议状态或确切会议时间"]
                                        if derived_variant == "scheduled_visit"
                                        else ["未发现已确认会议事实"]
                                    ),
                                },
                            ],
                        }
                    )
                    question_pairs.append(
                        (
                            "strategy_variant",
                            "策略分支与已确认会议事实冲突；请确认是否确有需要执行准备的明确拜访，并据此更新intake。",
                        )
                    )
            else:
                missing_requirements.append(
                    {"field": "strategy_variant", "code": "invalid_strategy_variant", "message": "策略成果变体未形成唯一有效值。"}
                )
                question_pairs.append(("strategy_variant", "请补充明确会议事实；系统将据此选择拜访准备或账户规划。"))
        else:
            strategy_variant = derived_variant
            if meeting_status:
                evidence_fields = ("meeting_status", "meeting_time")
            elif exact_meeting_time:
                evidence_fields = ("meeting_time",)
            else:
                evidence_fields = ()
            candidate_ids = sorted(
                {
                    str(candidate_id)
                    for field in evidence_fields
                    for candidate_id in selected_values.get(field, {}).get("candidate_ids", [])
                }
            )
            source_refs = sorted(
                {
                    str(source_ref)
                    for field in evidence_fields
                    for source_ref in selected_values.get(field, {}).get("source_refs", [])
                }
            )
            selected_values["strategy_variant"] = {
                "values": [strategy_variant],
                "candidate_ids": candidate_ids,
                "source_refs": source_refs,
                "selection_basis": (
                    "derived_from_confirmed_meeting_status"
                    if meeting_status == "confirmed"
                    else "derived_from_tentative_meeting_status"
                    if meeting_status == "tentative"
                    else "derived_from_nonmeeting_status"
                    if meeting_status in {"none", "unknown"}
                    else "derived_from_exact_meeting_time"
                    if exact_meeting_time
                    else "default_without_confirmed_meeting"
                ),
            }
    visit_contract = mode in VISIT_MODES or (mode == "strategic_account" and strategy_variant == "scheduled_visit")
    target_fields = {"target_person", "target_role", "target_contact_level"}
    target_conflict_present = any(
        str(item.get("field", "")) in target_fields for item in blocking_conflicts
    )
    if (
        visit_contract
        and not any(field in selected_values for field in target_fields)
        and not target_conflict_present
    ):
        missing_requirements.append(
            {
                "field": "target_identity_or_level",
                "code": "required_any_missing",
                "message": "拜访对象姓名、职务或层级至少需要一项唯一值。",
            }
        )
        question_pairs.append(("target_identity_or_level", "请确认拜访对象的姓名、职务或至少所属层级。"))
    if visit_contract:
        for field, question in (
            ("visit_objective", "请确认本次拜访希望达成的主要目标。"),
            ("minimum_next_step", "请确认本次拜访希望形成的最小下一步。"),
        ):
            if field not in selected_values:
                missing_requirements.append(
                    {"field": field, "code": "required_value_missing", "message": f"{FIELD_LABELS[field]}尚未形成唯一值。"}
                )
                question_pairs.append((field, question))
    if mode == "strategic_account" and strategy_variant == "account_planning":
        for field, question in (
            ("strategic_question", "请确认本轮账户经营需要回答的战略问题。"),
            ("planning_horizon", "请确认账户规划周期，例如90天或本财年。"),
            ("minimum_next_step", "请确认本周期的最小推进动作。"),
        ):
            if field not in selected_values:
                missing_requirements.append(
                    {"field": field, "code": "required_value_missing", "message": f"{FIELD_LABELS[field]}尚未形成唯一值。"}
                )
                question_pairs.append((field, question))
    if mode == "letter":
        for field, question in (
            ("recipient_role", "请确认收件对象的明确角色或正式称谓。"),
            ("letter_scenario", "请确认本封信的业务场景。"),
            ("letter_purpose", "请确认本封信要达成的目的。"),
            ("expected_action", "请确认希望对方采取的动作。"),
            ("signer", "请确认签署人或稳定签署角色。"),
            ("delivery_channel", "请确认拟使用的发送渠道。"),
        ):
            if field not in selected_values:
                missing_requirements.append(
                    {"field": field, "code": "required_value_missing", "message": f"{FIELD_LABELS[field]}尚未形成唯一值。"}
                )
                question_pairs.append((field, question))
        for field, purpose, question in (
            ("letter_purpose", True, "请用明确动词和对象说明本封信要达成的具体目的。"),
            ("expected_action", False, "请用明确动词和对象说明希望对方采取的具体动作。"),
        ):
            values = selected_values.get(field, {}).get("values", [])
            if len(values) == 1 and isinstance(values[0], str) and not substantive_letter_field(
                values[0], purpose=purpose
            ):
                missing_requirements.append(
                    {
                        "field": field,
                        "code": "required_value_non_substantive",
                        "message": f"{FIELD_LABELS[field]}缺少明确动作或对象，不能使用空壳表述。",
                    }
                )
                question_pairs.append((field, question))

    request_mention_ledger: list[dict[str, Any]] = []
    if request_binding is not None:
        coverage_conflicts, coverage_questions, request_mention_ledger = _request_coverage(
            validated, request_binding
        )
        blocking_conflicts.extend(coverage_conflicts)
        question_pairs.extend(coverage_questions)

    high_risk_response: dict[str, Any] | None = None
    if mode == "letter" and request_binding is not None:
        active_set = {
            str(item["risk_code"])
            for item in request_binding.safety_directives
            if item.get("assertion_status") in ACTIVE_ASSERTION_STATUSES
        }
        active_directive_codes = tuple(
            code for code in LETTER_SAFETY_RISK_ORDER if code in active_set
        )
        external_send_requested = "direct_external_send" in active_directive_codes
        risk_codes = tuple(
            code
            for code in active_directive_codes
            if code not in authorized_source_risks or external_send_requested
        )
        if risk_codes:
            high_risk_response = high_risk_letter_failure_response(risk_codes)
            blocking_conflicts.append(
                {
                    "field": "letter_safety",
                    "field_label": "客户信安全边界",
                    "code": "unsafe_letter_request",
                    "risk_codes": list(risk_codes),
                }
            )
            # Safety refusal is terminal for this turn.  Continuation
            # conditions live in the fixed failure response rather than an
            # ordinary clarification question that could imply authorization.
            question_pairs = []

    # Keep only the first question for each blocking field.  Unresolved
    # conflicts are always collapsed into one question and take priority over
    # ordinary missing fields.  A letter without a resolved recipient likewise
    # asks only for that prerequisite; no speculative drafting questions follow.
    deduplicated_questions: list[dict[str, str]] = []
    seen_question_fields: set[str] = set()
    for field, question in question_pairs:
        if field in seen_question_fields:
            continue
        seen_question_fields.add(field)
        deduplicated_questions.append({"field": field, "question": question})
    if high_risk_response is not None:
        questions: list[dict[str, str]] = []
    elif blocking_conflicts:
        questions = [_one_conflict_question(blocking_conflicts, question_pairs)]
    elif mode == "letter" and "recipient_role" not in selected_values:
        recipient_question = next(
            (
                item
                for item in deduplicated_questions
                if item["field"] == "recipient_role"
            ),
            {
                "field": "recipient_role",
                "question": "请确认收件对象的明确角色或正式称谓。",
            },
        )
        questions = [recipient_question]
    else:
        questions = deduplicated_questions[:3]

    digest = input_sha256(payload)
    gate_digest = digest
    if request_binding is not None:
        gate_digest = hashlib.sha256(
            (digest + request_binding.receipt_sha256 + request_binding.mention_ledger_sha256).encode(
                "ascii"
            )
        ).hexdigest()
    blocked = bool(blocking_conflicts or missing_requirements)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "gate_id": "dcg-" + gate_digest[:16],
        "request_id": validated["request_id"],
        "business_mode": mode,
        "status": "blocked" if blocked else "ready",
        "safe_to_initialize_or_search": not blocked,
        "input_sha256": digest,
        "evaluated_at": isoformat(current),
        "selected_values": selected_values,
        "blocking_conflicts": blocking_conflicts,
        "missing_requirements": missing_requirements,
        "questions": questions,
        "unasked_blocker_count": max(0, len(deduplicated_questions) - len(questions)),
    }
    if high_risk_response is not None:
        result["high_risk_failure_response"] = high_risk_response
    if request_binding is not None:
        result["request_binding"] = request_binding.audit_fields()
        result["request_mention_ledger"] = request_mention_ledger
        result["request_safety_directives"] = [dict(item) for item in request_binding.safety_directives]
        result["subject_resolution"] = dict(subject_resolution)
        result["safety_authorizations"] = [dict(item) for item in safety_authorizations]
    if not blocked:
        expiry = current + timedelta(seconds=ttl_seconds)
        if request_binding is not None:
            expiry = min(expiry, request_binding.expires_at)
        result["expires_at"] = isoformat(expiry)
    return result


def load_payload(path_text: str) -> Any:
    if path_text == "-":
        try:
            return json.loads(sys.stdin.read(), object_pairs_hook=_unique_object)
        except PreflightError:
            raise
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PreflightError(f"stdin不是有效UTF-8 JSON：{exc}") from exc
    supplied = Path(path_text).expanduser()
    if supplied.is_symlink():
        raise PreflightError("intake文件不得为符号链接。")
    path = supplied.resolve()
    if not path.is_file():
        raise PreflightError(f"intake文件不存在或不是普通文件：{path}")
    try:
        return _parse_json_bytes(path.read_bytes(), "intake文件")
    except PreflightError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"intake文件不是有效UTF-8 JSON：{exc}") from exc


def evaluate_intake_file(
    path_text: str,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    require_request_binding: bool = True,
) -> dict[str, Any]:
    """Load intake and verify its sibling host capture before evaluation."""
    if path_text == "-":
        raise PreflightError("带宿主request binding的v3 intake必须使用普通文件，不能从stdin执行。")
    supplied = Path(path_text).expanduser()
    if supplied.is_symlink():
        raise PreflightError("intake文件不得为符号链接。")
    path = supplied.resolve()
    payload = load_payload(str(path))
    current = (now or utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    binding = None
    if isinstance(payload, dict) and payload.get("schema") == INPUT_SCHEMA:
        binding = _verify_request_binding(payload, intake_path=path, now=current)
    return evaluate_intake(
        payload,
        now=current,
        ttl_seconds=ttl_seconds,
        request_binding=binding,
        require_request_binding=require_request_binding,
    )


PERSISTED_GATE_STABLE_FIELDS = (
    "gate_id",
    "input_sha256",
    "business_mode",
    "request_binding_receipt_id",
    "request_binding_receipt_sha256",
    "request_bundle_id",
    "request_revision",
    "raw_request_sha256",
    "mention_ledger_sha256",
    "subject_resolution_sha256",
    "safety_authorizations_sha256",
    "safety_directives_sha256",
    "subject_resolution",
    "safety_authorization_codes",
)


def verified_gate_record(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact downstream gate only from a verified ready result."""
    if result.get("status") != "ready" or result.get("safe_to_initialize_or_search") is not True:
        raise PreflightError("intake_preflight_blocked：存在冲突、缺项或未覆盖的原始提及。")
    binding = result.get("request_binding")
    if not isinstance(binding, dict) or binding.get("verified") is not True:
        raise PreflightError("intake预检缺少已验证的宿主request binding。")
    subject_resolution = result.get("subject_resolution")
    if not isinstance(subject_resolution, dict):
        raise PreflightError("intake预检缺少宿主签名subject_resolution。")
    active_directive_codes = {
        str(item.get("risk_code"))
        for item in result.get("request_safety_directives", [])
        if isinstance(item, Mapping)
        and item.get("assertion_status") in ACTIVE_ASSERTION_STATUSES
    }
    authorized_codes = {
        str(item.get("risk_code"))
        for item in result.get("safety_authorizations", [])
        if isinstance(item, Mapping)
    }
    # A standing host authorization is only a request lifecycle constraint
    # when the current signed request actually invokes that source class.  The
    # complete authorization array remains receipt-bound for audit, but an
    # unused authorization must not turn an otherwise public letter into a
    # permanently internal-only artifact.
    effective_internal_only_codes = sorted(
        authorized_codes & active_directive_codes & AUTHORIZABLE_SOURCE_RISKS
    )
    return {
        "gate_id": result["gate_id"],
        "input_sha256": result["input_sha256"],
        "business_mode": result["business_mode"],
        "evaluated_at": result["evaluated_at"],
        "expires_at": result["expires_at"],
        "request_binding_receipt_id": binding["receipt_id"],
        "request_binding_receipt_sha256": binding["receipt_sha256"],
        "request_bundle_id": binding["request_bundle_id"],
        "request_revision": binding["request_revision"],
        "raw_request_sha256": binding["raw_request_sha256"],
        "mention_ledger_sha256": binding["mention_ledger_sha256"],
        "subject_resolution_sha256": binding["subject_resolution_sha256"],
        "safety_authorizations_sha256": binding["safety_authorizations_sha256"],
        "safety_directives_sha256": binding["safety_directives_sha256"],
        "subject_resolution": dict(subject_resolution),
        "safety_authorization_codes": effective_internal_only_codes,
    }


def verify_persisted_gate(
    path_text: str,
    persisted_gate: Mapping[str, Any],
    *,
    now: datetime | None = None,
    expected_business_mode: str | None = None,
    expected_customer_name: str | None = None,
    expected_organization_scope: str | None = None,
) -> dict[str, Any]:
    """Reverify raw binding/current request and match a persisted downstream gate.

    Side-effecting stages call this again instead of trusting hashes copied from
    a model-writable manifest.  Evaluation timestamps may differ, but every
    stable identity and the original persisted TTL must remain valid.
    """
    if not isinstance(persisted_gate, Mapping):
        raise PreflightError("持久化intake门禁不是对象。")
    current = (now or utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    result = evaluate_intake_file(
        path_text,
        now=current,
        require_request_binding=True,
    )
    current_gate = verified_gate_record(result)
    required = set(PERSISTED_GATE_STABLE_FIELDS) | {"evaluated_at", "expires_at"}
    missing = sorted(required - set(persisted_gate))
    if missing:
        raise PreflightError("持久化intake门禁缺少：" + ", ".join(missing) + "。")
    for field in PERSISTED_GATE_STABLE_FIELDS:
        if persisted_gate.get(field) != current_gate.get(field):
            raise PreflightError(f"持久化intake门禁与当前宿主请求不一致：{field}。")
    evaluated_at = parse_timestamp(persisted_gate.get("evaluated_at"), "持久化intake门禁.evaluated_at")
    expires_at = parse_timestamp(persisted_gate.get("expires_at"), "持久化intake门禁.expires_at")
    fresh_expiry = parse_timestamp(current_gate.get("expires_at"), "当前intake门禁.expires_at")
    if evaluated_at > current or expires_at <= current or expires_at > fresh_expiry:
        raise PreflightError("持久化intake门禁尚未生效、已过期或超出当前宿主收据有效期。")
    if expected_business_mode is not None and result.get("business_mode") != expected_business_mode:
        raise PreflightError("intake预检business_mode与当前阶段不一致。")
    selected = result.get("selected_values", {})
    if not isinstance(selected, dict):
        raise PreflightError("intake预检selected_values无效。")
    if expected_customer_name is not None:
        values = selected.get("customer_name", {}).get("values", [])
        if values != [normalize_text(expected_customer_name)]:
            raise PreflightError("intake预检客户主体与当前workspace不一致。")
    if expected_organization_scope is not None:
        values = selected.get("organization_scope", {}).get("values", [])
        if values != [normalize_text(expected_organization_scope)]:
            raise PreflightError("intake预检机构范围与当前workspace不一致。")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在创建客户工作区或检索前，对结构化候选值执行无副作用消歧。"
    )
    parser.add_argument(
        "intake",
        help="当前宿主签名的intake v3普通文件；CLI不接受-或stdin",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help=f"ready回执有效期，{MIN_TTL_SECONDS}—{MAX_TTL_SECONDS}秒（默认{DEFAULT_TTL_SECONDS}）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = evaluate_intake_file(
            args.intake,
            ttl_seconds=args.ttl_seconds,
            require_request_binding=True,
        )
    except (PreflightError, OSError, UnicodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
