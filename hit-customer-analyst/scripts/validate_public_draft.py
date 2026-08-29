#!/usr/bin/env python3
"""Fail-closed validation for conversation-only public discovery drafts.

The candidate draft is accepted only from stdin and is never echoed or written
to disk.  This validator is deliberately separate from the authenticated
workspace validators: passing it permits only delivery of an internal draft in
the current conversation and never authorizes a workspace, ready, release, or
external action.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import ipaddress
import json
import re
import sys
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit


SCHEMA = "discovery-call-public-draft-validation/v1"
MAX_INPUT_BYTES = 200_000
EXECUTION_PROFILE_LINE = "执行档：公开资料内部草稿"
STATE_LINES = {
    "ready_for_use": "ready_for_use：false",
    "external_use": "external_use：false",
    "release_eligible": "release_eligible：false",
}
SCOPE_LINE = "可用范围：内部讨论和人工复核；不得直接外发或写回业务系统"
REQUIRED_SECTIONS = (
    "## 公开来源支持、待人工复核",
    "## 推断与建议",
    "## 待人工复核",
    "## 下一步",
)
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)

URL_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>()\[\]\"'`]+")
PRIVATE_HOST_RE = re.compile(
    r"(?i)(?<![a-z0-9.-])(?:localhost|(?:[a-z0-9-]+\.)+(?:local|internal|intranet|corp|lan))(?![a-z0-9.-])"
)
IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
IPV6_CANDIDATE_RE = re.compile(
    r"(?<![0-9A-Za-z])(?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f:]{0,4}(?![0-9A-Za-z])"
)
WINDOWS_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\)[^\s<>\"'`]+")
RELATIVE_RUNTIME_PATH_RE = re.compile(
    r"(?im)(?<![A-Za-z0-9_])(?:[.~][\\/]|(?:workspace|candidate|runtime|customers?|output)[\\/])[^\s<>()\[\]\{\}\"'`]+"
)
UNIX_PATH_RE = re.compile(
    r"(?m)(?:^|[\s(\[\{\"'`：])/(?!/)[^\s<>()\[\]\{\}\"'`]+"
)
UNIX_NESTED_PATH_RE = re.compile(
    r"(?m)(?<![:/A-Za-z0-9])/(?!/)(?:[^\s/<>\"'`]+/)+[^\s<>()\[\]\{\}\"'`]+"
)
GENERIC_FILE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:[^/\\\s<>()\[\]\{\}\"'`]+[\\/])+[^/\\\s<>()\[\]\{\}\"'`]+\.(?:csv|db|docx?|json|log|md|pdf|sqlite|tsv|txt|xlsx?|ya?ml|zip)(?![A-Za-z0-9_])"
)
FORBIDDEN_SCHEME_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:data|file|javascript|ldap|mailto|nfs|smb):"
)
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])")
MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
PRC_ID_RE = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|session[_-]?id|cookie|authorization)\s*[:：=]\s*\S+"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
SENSITIVE_LABEL_RE = re.compile(
    r"(?:患者姓名|病历号|病案号|住院号|门诊号|身份证号|手机号|手机号码|电子邮箱|邮箱|CRM记录|内部邮件|客户私有数据)\s*[:：=]\s*\S+",
    re.IGNORECASE,
)
SENSITIVE_PROVENANCE_RE = re.compile(
    r"(?:CRM|PIMS|内部邮件|病历|病案|患者记录|住院记录|门诊记录)(?:导出|摘录|原文|附件|数据显示|显示)",
    re.IGNORECASE,
)

FORMAL_TRACE_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9])(?:CLM|SRC)\s*-\s*[A-Za-z0-9*]"),
    re.compile(r"(?i)(?<![A-Za-z0-9])F\s*/\s*F2(?![A-Za-z0-9])"),
    re.compile(r"(?i)(?<![A-Za-z0-9])F2(?![A-Za-z0-9])"),
    re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:context[-_]id|run[-_]id|tenant[-_]id|customer[-_]id|project[-_]id|receipt[-_]id|attestation[-_]id|request[-_]bundle[-_]id|action[-_]event[-_]id|candidate[-_]workspace)(?![A-Za-z0-9])"
    ),
    re.compile(
        r"(?i)\b(?:candidate-seal-request|evidence-manifest|source-cache|run-metrics|governance-context)\.json\b"
    ),
    re.compile(
        r"(?i)\bdiscovery-call-(?:request-binding-receipt|source-capture-receipt|candidate-attestation|governance-event)(?:/v\d+)?\b"
    ),
)

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "email",
    "id_card",
    "jwt",
    "key",
    "mobile",
    "password",
    "patient",
    "phone",
    "refresh_token",
    "session",
    "session_id",
    "sig",
    "signature",
    "sfzh",
    "token",
}
SENSITIVE_QUERY_KEY_PARTS = (
    "access_token",
    "api_key",
    "auth",
    "cookie",
    "credential",
    "jwt",
    "password",
    "patient",
    "secret",
    "session",
    "signature",
    "token",
)
INTERNAL_HOST_SUFFIXES = (".local", ".internal", ".intranet", ".corp", ".lan")


def _add(errors: set[str], code: str) -> None:
    errors.add(code)


def _validate_header(text: str, errors: set[str]) -> None:
    lines = text.splitlines()
    if not lines or lines[0] != EXECUTION_PROFILE_LINE:
        _add(errors, "execution_profile_watermark_missing_or_moved")
    if lines.count(EXECUTION_PROFILE_LINE) != 1:
        _add(errors, "execution_profile_watermark_must_appear_once")

    expected_prefix = [EXECUTION_PROFILE_LINE, *STATE_LINES.values()]
    if len(lines) < len(expected_prefix) or lines[: len(expected_prefix)] != expected_prefix:
        _add(errors, "fixed_header_invalid")

    for field, expected_line in STATE_LINES.items():
        occurrences = re.findall(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(field)}\s*[:：=]\s*([A-Za-z]+)",
            text,
        )
        if occurrences != ["false"] or text.splitlines().count(expected_line) != 1:
            _add(errors, f"{field}_must_be_exactly_false_once")

    cutoff_index = len(expected_prefix)
    if len(lines) <= cutoff_index or not lines[cutoff_index].startswith("证据截止时间："):
        _add(errors, "evidence_cutoff_missing_or_moved")
    else:
        value = lines[cutoff_index].removeprefix("证据截止时间：").strip()
        if RFC3339_RE.fullmatch(value):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        else:
            parsed = None
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            _add(errors, "evidence_cutoff_requires_rfc3339_timezone")
    if len(re.findall(r"(?m)^\s*证据截止时间\s*[:：]", text)) != 1:
        _add(errors, "evidence_cutoff_must_appear_once")

    scope_index = cutoff_index + 1
    if len(lines) <= scope_index or lines[scope_index] != SCOPE_LINE:
        _add(errors, "internal_use_scope_watermark_missing_or_moved")
    if text.splitlines().count(SCOPE_LINE) != 1:
        _add(errors, "internal_use_scope_watermark_must_appear_once")
    if len(re.findall(r"(?m)^\s*可用范围\s*[:：]", text)) != 1:
        _add(errors, "internal_use_scope_must_not_be_redefined")


def _validate_sections(text: str, errors: set[str]) -> None:
    lines = text.splitlines()
    positions: list[int] = []
    section_codes = (
        "public_sources_pending_review",
        "inference_and_recommendations",
        "human_review",
        "next_step",
    )
    for heading, code in zip(REQUIRED_SECTIONS, section_codes, strict=True):
        found = [index for index, line in enumerate(lines) if line == heading]
        if len(found) != 1:
            _add(errors, f"required_section_{code}_must_appear_once")
        else:
            positions.append(found[0])
    if len(positions) == len(REQUIRED_SECTIONS) and positions != sorted(positions):
        _add(errors, "required_sections_out_of_order")
    if len(positions) == len(REQUIRED_SECTIONS):
        for index, (heading, code) in enumerate(zip(REQUIRED_SECTIONS, section_codes, strict=True)):
            start = positions[index] + 1
            end = positions[index + 1] if index + 1 < len(positions) else len(lines)
            body = "\n".join(lines[start:end]).strip()
            if not body:
                _add(errors, f"required_section_{code}_must_contain_visible_content")
            if heading == REQUIRED_SECTIONS[0] and not any(
                match.group(0).lower().startswith(("http://", "https://"))
                for match in URL_RE.finditer(body)
            ):
                _add(errors, "public_sources_section_requires_public_url")
    if re.search(r"(?m)^\s{0,3}#{1,6}\s*已核实事实\s*$", text):
        _add(errors, "obsolete_verified_facts_heading_forbidden")


def _validate_urls(text: str, errors: set[str]) -> str:
    spans: list[tuple[int, int]] = []
    for match in URL_RE.finditer(text):
        raw = match.group(0).rstrip(".,;:!?，。；！？")
        spans.append((match.start(), match.start() + len(raw)))
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError:
            _add(errors, "malformed_or_unsafe_locator")
            continue
        if parsed.scheme.lower() not in {"http", "https"}:
            _add(errors, "nonpublic_locator_scheme_forbidden")
            continue
        if parsed.username is not None or parsed.password is not None:
            _add(errors, "locator_credentials_forbidden")
        decoded = raw
        for _ in range(3):
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        decoded = unicodedata.normalize("NFKC", decoded)
        if (
            SECRET_ASSIGNMENT_RE.search(decoded)
            or BEARER_RE.search(decoded)
            or EMAIL_RE.search(decoded)
            or MOBILE_RE.search(decoded)
            or PRC_ID_RE.search(decoded)
            or SENSITIVE_LABEL_RE.search(decoded)
        ):
            _add(errors, "sensitive_locator_value_forbidden")
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host or port is not None and not 1 <= port <= 65535:
            _add(errors, "malformed_or_unsafe_locator")
        else:
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                _add(errors, "internal_network_trace_forbidden")
            if (
                host == "localhost"
                or "." not in host
                or host.endswith(INTERNAL_HOST_SUFFIXES)
                or any(label in {"internal", "intranet", "corp", "lan"} for label in host.split("."))
            ):
                _add(errors, "internal_network_trace_forbidden")
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            normalized_key = key.casefold().replace("-", "_")
            if normalized_key in SENSITIVE_QUERY_KEYS or any(
                part in normalized_key for part in SENSITIVE_QUERY_KEY_PARTS
            ):
                _add(errors, "sensitive_locator_parameter_forbidden")
            decoded_value = unicodedata.normalize("NFKC", unquote(value))
            if (
                EMAIL_RE.search(decoded_value)
                or MOBILE_RE.search(decoded_value)
                or PRC_ID_RE.search(decoded_value)
                or SECRET_ASSIGNMENT_RE.search(decoded_value)
                or BEARER_RE.search(decoded_value)
                or SENSITIVE_LABEL_RE.search(decoded_value)
            ):
                _add(errors, "sensitive_locator_value_forbidden")

    if not spans:
        return text
    characters = list(text)
    for start, end in spans:
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _validate_network_and_paths(text_without_urls: str, errors: set[str]) -> None:
    if FORBIDDEN_SCHEME_RE.search(text_without_urls):
        _add(errors, "nonpublic_locator_scheme_forbidden")
    if PRIVATE_HOST_RE.search(text_without_urls):
        _add(errors, "internal_network_trace_forbidden")
    for candidate in IPV4_RE.findall(text_without_urls):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not address.is_global:
            _add(errors, "internal_network_trace_forbidden")
    for candidate in IPV6_CANDIDATE_RE.findall(text_without_urls):
        try:
            address = ipaddress.ip_address(candidate.strip("[]"))
        except ValueError:
            continue
        if not address.is_global:
            _add(errors, "internal_network_trace_forbidden")

    if (
        WINDOWS_PATH_RE.search(text_without_urls)
        or RELATIVE_RUNTIME_PATH_RE.search(text_without_urls)
        or UNIX_PATH_RE.search(text_without_urls)
        or UNIX_NESTED_PATH_RE.search(text_without_urls)
        or GENERIC_FILE_PATH_RE.search(text_without_urls)
    ):
        _add(errors, "filesystem_or_runtime_path_forbidden")


def _validate_sensitive_traces(text_without_urls: str, errors: set[str]) -> None:
    if SECRET_ASSIGNMENT_RE.search(text_without_urls) or BEARER_RE.search(text_without_urls):
        _add(errors, "credential_or_session_trace_forbidden")
    if (
        EMAIL_RE.search(text_without_urls)
        or MOBILE_RE.search(text_without_urls)
        or PRC_ID_RE.search(text_without_urls)
        or SENSITIVE_LABEL_RE.search(text_without_urls)
        or SENSITIVE_PROVENANCE_RE.search(text_without_urls)
    ):
        _add(errors, "personal_or_sensitive_data_trace_forbidden")


def validate_public_draft(raw_text: str) -> list[str]:
    errors: set[str] = set()
    try:
        input_size = len(raw_text.encode("utf-8"))
    except UnicodeEncodeError:
        return ["invalid_utf8"]
    if input_size > MAX_INPUT_BYTES:
        _add(errors, "draft_too_large")
    if not raw_text.strip():
        _add(errors, "draft_empty")
        return sorted(errors)
    if raw_text.startswith("\ufeff"):
        _add(errors, "utf8_bom_forbidden")

    text = unicodedata.normalize("NFC", raw_text.replace("\r\n", "\n").replace("\r", "\n"))
    if "\x00" in text or any(unicodedata.category(character) == "Cf" for character in text):
        _add(errors, "hidden_or_unsafe_unicode_forbidden")

    _validate_header(text, errors)
    _validate_sections(text, errors)

    scan_text = unicodedata.normalize("NFKC", text)
    if any(pattern.search(scan_text) for pattern in FORMAL_TRACE_PATTERNS):
        _add(errors, "formal_identifier_or_artifact_trace_forbidden")

    text_without_urls = _validate_urls(scan_text, errors)
    _validate_network_and_paths(text_without_urls, errors)
    _validate_sensitive_traces(text_without_urls, errors)
    return sorted(errors)


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "从标准输入校验公开资料内部草稿；不读取文件、不回显原文，"
            "通过只表示可在当前对话交付内部草稿。"
        )
    )


def main() -> int:
    build_parser().parse_args()
    try:
        raw_candidate = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    except OSError:
        errors = ["stdin_read_failed"]
    else:
        if len(raw_candidate) > MAX_INPUT_BYTES:
            errors = ["draft_too_large"]
        else:
            try:
                candidate = raw_candidate.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                errors = ["invalid_utf8"]
            else:
                errors = validate_public_draft(candidate)
    valid = not errors
    result = {
        "schema": SCHEMA,
        "valid": valid,
        "delivery_allowed": valid,
        "delivery_scope": "conversation_internal_draft" if valid else "blocked",
        "formal_authorized": False,
        "ready_for_use": False,
        "external_use": False,
        "release_eligible": False,
        "error_codes": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
