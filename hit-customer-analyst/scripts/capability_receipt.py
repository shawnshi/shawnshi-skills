#!/usr/bin/env python3
"""Verify host-issued capability receipts for internal discovery-call access.

This module deliberately exposes verification only.  It never creates keys or
signs receipts.  The authenticated host injects trusted Ed25519 public keys via
``DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON``; no private key or trust-store
file is read from a workspace or from the skill package.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


RECEIPT_SCHEMA = "discovery-call-capability-receipt/v1"
RECEIPT_AUDIENCE = "discovery-call-internal"
SOURCE_RECEIPT_SCHEMA = "discovery-call-source-capture-receipt/v3"
SOURCE_RECEIPT_AUDIENCE = "discovery-call-source-capture"
TRUSTED_KEYS_ENV = "DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON"
MAX_RECEIPT_BYTES = 64 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
RUN_RE = re.compile(r"^dcr-\d{8}T\d{6}-[A-Za-z0-9]{4}$")
REQUIRED_FIELDS = {
    "schema",
    "issuer",
    "audience",
    "key_id",
    "issued_at",
    "expires_at",
    "receipt_id",
    "actor_id",
    "run_id",
    "connector_id",
    "operation",
    "tenant_id",
    "customer_id",
    "project_id",
    "allowed_project_ids",
    "authorization_owner",
    "authorization_expires_at",
    "authorized_roots",
    "allowed_dataset_aliases",
    "allowed_confidentiality",
    "authorization_purpose",
    "signature",
}
SOURCE_REQUIRED_FIELDS = {
    "schema",
    "issuer",
    "audience",
    "key_id",
    "issued_at",
    "expires_at",
    "receipt_id",
    "source_id",
    "source_title",
    "publisher_or_provider",
    "locator",
    "final_url",
    "canonical_locator",
    "publication_or_update_date",
    "access_date",
    "content_sha256",
    "length",
    "capture_method",
    "retrieved_at",
    "published_at",
    "source_updated_at",
    "internal_recorded_at",
    "source_level",
    "source_group",
    "permission",
    "applicable_scope",
    "notes",
    "upstream_id",
    "external_use",
    "tenant_id",
    "run_id",
    "customer_id",
    "project_id",
    "signature",
}
UNSAFE_VISIBLE_RE = re.compile(
    r"(?:!?\[[^\]\n]*\]\s*(?:\([^\)\n]*\)|\[[^\]\n]*\])|`|<[^>\n]+>)"
)
STABLE_LOCATOR_RE = re.compile(
    r"^(?:urn|record|document|dataset|ragflow|archive):[A-Za-z0-9][A-Za-z0-9._~:/?#@!$&'*+,;=%-]*$",
    re.IGNORECASE,
)
SCALAR_SCOPE_FIELDS = (
    "receipt_id",
    "actor_id",
    "run_id",
    "connector_id",
    "operation",
    "tenant_id",
    "customer_id",
    "project_id",
    "authorization_owner",
    "authorization_purpose",
)
LIST_SCOPE_FIELDS = (
    "allowed_project_ids",
    "authorized_roots",
    "allowed_dataset_aliases",
    "allowed_confidentiality",
)


class CapabilityReceiptError(RuntimeError):
    """Raised when a host capability receipt cannot be trusted."""


@dataclass(frozen=True)
class VerifiedCapabilityReceipt:
    receipt_id: str
    actor_id: str
    run_id: str
    connector_id: str
    operation: str
    issuer: str
    key_id: str
    issued_at: str
    expires_at: str
    receipt_sha256: str
    verified_at: str

    def audit_fields(self) -> dict[str, object]:
        return {
            "authorization_actor_id": self.actor_id,
            "capability_receipt_run_id": self.run_id,
            "capability_operation": self.operation,
            "capability_receipt_verified": True,
            "capability_receipt_issuer": self.issuer,
            "capability_receipt_key_id": self.key_id,
            "capability_receipt_sha256": self.receipt_sha256,
            "capability_receipt_verified_at": self.verified_at,
            "capability_receipt_expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class VerifiedSourceCaptureReceipt:
    receipt_id: str
    issuer: str
    key_id: str
    receipt_sha256: str
    expires_at: str

    def audit_fields(self) -> dict[str, object]:
        return {
            "source_capture_receipt_id": self.receipt_id,
            "source_capture_receipt_verified": True,
            "source_capture_receipt_issuer": self.issuer,
            "source_capture_receipt_key_id": self.key_id,
            "source_capture_receipt_sha256": self.receipt_sha256,
            "source_capture_receipt_expires_at": self.expires_at,
        }


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _safe_visible_scalar(value: Any, label: str) -> str:
    text = _normalized(value)
    if (
        not isinstance(value, str)
        or not text
        or text != value
        or UNSAFE_VISIBLE_RE.search(text)
        or any(unicodedata.category(char) == "Cf" for char in text)
    ):
        raise CapabilityReceiptError(
            f"{label}必须是规范化可见纯文本，不得包含Markdown链接/图片、代码标记、HTML或隐藏控制字符。"
        )
    return text


def _canonical_locator(value: str) -> str:
    """Canonicalize only raw HTTP(S) URLs or controlled stable identifiers."""

    text = _safe_visible_scalar(value, "source locator")
    if STABLE_LOCATOR_RE.fullmatch(text):
        return text.casefold()
    try:
        parsed = urlsplit(text)
        parsed_port = parsed.port
    except ValueError as exc:
        raise CapabilityReceiptError("source locator不是有效raw URL或受控stable-id。") from exc
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise CapabilityReceiptError("source locator只允许raw HTTP(S) URL或受控stable-id。")
    host = (parsed.hostname or "").casefold()
    if not host or parsed.username is not None or parsed.password is not None:
        raise CapabilityReceiptError("source locator主机无效或包含禁止的userinfo。")
    default_port = (parsed.scheme.casefold(), parsed_port) in {("http", 80), ("https", 443)}
    port = f":{parsed_port}" if parsed_port and not default_port else ""
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), host + port, path, query, ""))


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CapabilityReceiptError(f"JSON包含重复字段：{key}")
        value[key] = item
    return value


def _parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except CapabilityReceiptError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityReceiptError(f"{label}不是有效UTF-8 JSON。") from exc


def _timestamp(value: Any, label: str) -> datetime:
    text = _normalized(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapabilityReceiptError(f"{label}必须是带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise CapabilityReceiptError(f"{label}必须包含时区。")
    return parsed.astimezone(timezone.utc)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _clean_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CapabilityReceiptError(f"{label}必须是非空字符串数组。")
    cleaned = [_normalized(item) for item in value if isinstance(item, str)]
    if len(cleaned) != len(value) or any(not item for item in cleaned):
        raise CapabilityReceiptError(f"{label}必须是非空字符串数组。")
    if cleaned != value:
        raise CapabilityReceiptError(f"{label}必须使用规范化字符串。")
    if len(set(cleaned)) != len(cleaned):
        raise CapabilityReceiptError(f"{label}不得包含重复项。")
    return cleaned


def _trusted_key(issuer: str, key_id: str) -> Ed25519PublicKey:
    encoded_registry = os.environ.get(TRUSTED_KEYS_ENV, "").strip()
    if not encoded_registry:
        raise CapabilityReceiptError(
            f"宿主未注入{TRUSTED_KEYS_ENV}信任根；internal能力已关闭。"
        )
    registry = _parse_json(encoded_registry.encode("utf-8"), TRUSTED_KEYS_ENV)
    if not isinstance(registry, dict):
        raise CapabilityReceiptError(f"{TRUSTED_KEYS_ENV}必须是issuer到key_id公钥的对象。")
    issuer_keys = registry.get(issuer)
    encoded = issuer_keys.get(key_id) if isinstance(issuer_keys, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise CapabilityReceiptError("capability receipt的issuer/key_id不在宿主信任根中。")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != 32:
            raise ValueError("length")
        return Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise CapabilityReceiptError("宿主注入的Ed25519能力公钥无效。") from exc


def read_receipt(path_value: str | os.PathLike[str]) -> tuple[dict[str, Any], bytes]:
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise CapabilityReceiptError("capability receipt必须是现有普通文件，且不得为符号链接。")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CapabilityReceiptError(f"capability receipt无法读取：{exc}") from exc
    if not raw or len(raw) > MAX_RECEIPT_BYTES:
        raise CapabilityReceiptError("capability receipt为空或超过64KiB上限。")
    payload = _parse_json(raw, "capability receipt")
    if not isinstance(payload, dict):
        raise CapabilityReceiptError("capability receipt顶层必须是对象。")
    if set(payload) != REQUIRED_FIELDS:
        missing = sorted(REQUIRED_FIELDS - set(payload))
        extra = sorted(set(payload) - REQUIRED_FIELDS)
        detail = []
        if missing:
            detail.append("缺少=" + ",".join(missing))
        if extra:
            detail.append("未知=" + ",".join(extra))
        raise CapabilityReceiptError("capability receipt字段不符合v1契约：" + "；".join(detail))
    return payload, raw


def verify_capability_receipt(
    path_value: str | os.PathLike[str],
    *,
    expected: Mapping[str, Any],
    at: datetime | None = None,
) -> VerifiedCapabilityReceipt:
    """Verify signature, lifetime, and exact requested authorization scope."""

    payload, _raw = read_receipt(path_value)
    for key in ("issuer", "key_id", *SCALAR_SCOPE_FIELDS):
        value = payload.get(key)
        clean = _normalized(value)
        if not isinstance(value, str) or not clean or clean != value:
            raise CapabilityReceiptError(f"capability receipt.{key}必须是规范化非空字符串。")
    for key in ("issuer", "key_id", "receipt_id", "actor_id", "connector_id", "tenant_id", "customer_id", "project_id"):
        if not ID_RE.fullmatch(str(payload[key])):
            raise CapabilityReceiptError(f"capability receipt.{key}不是稳定标识符。")
    if not RUN_RE.fullmatch(str(payload["run_id"])):
        raise CapabilityReceiptError("capability receipt.run_id格式无效。")
    for key in LIST_SCOPE_FIELDS:
        _clean_list(payload.get(key), f"capability receipt.{key}")
    if payload.get("schema") != RECEIPT_SCHEMA or payload.get("audience") != RECEIPT_AUDIENCE:
        raise CapabilityReceiptError("capability receipt的schema/audience无效。")

    issued = _timestamp(payload.get("issued_at"), "capability receipt.issued_at")
    expires = _timestamp(payload.get("expires_at"), "capability receipt.expires_at")
    authorization_expires = _timestamp(
        payload.get("authorization_expires_at"),
        "capability receipt.authorization_expires_at",
    )
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if issued > now or expires <= now or expires <= issued:
        raise CapabilityReceiptError("capability receipt尚未生效、已过期或有效期倒置。")
    if authorization_expires <= now or authorization_expires > expires:
        raise CapabilityReceiptError("capability receipt中的业务授权已过期或越过收据有效期。")

    signature_text = payload.get("signature")
    try:
        signature = base64.b64decode(str(signature_text), validate=True)
        if len(signature) != 64:
            raise ValueError("length")
        signed_payload = {key: payload[key] for key in sorted(payload) if key != "signature"}
        _trusted_key(str(payload["issuer"]), str(payload["key_id"])).verify(
            signature,
            _canonical_bytes(signed_payload),
        )
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise CapabilityReceiptError("capability receipt的宿主Ed25519签名无效。") from exc

    missing_expected = [key for key in (*SCALAR_SCOPE_FIELDS, *LIST_SCOPE_FIELDS, "authorization_expires_at") if key not in expected]
    if missing_expected:
        raise CapabilityReceiptError("验证调用缺少预期授权字段：" + ", ".join(missing_expected))
    for key in SCALAR_SCOPE_FIELDS:
        if _normalized(expected.get(key)) != str(payload[key]):
            raise CapabilityReceiptError(f"capability receipt.{key}与本run授权上下文不一致。")
    for key in LIST_SCOPE_FIELDS:
        expected_values = expected.get(key)
        if not isinstance(expected_values, Sequence) or isinstance(expected_values, (str, bytes)):
            raise CapabilityReceiptError(f"预期授权字段{key}必须是数组。")
        clean_expected = [_normalized(item) for item in expected_values]
        if any(not item for item in clean_expected) or len(set(clean_expected)) != len(clean_expected):
            raise CapabilityReceiptError(f"预期授权字段{key}无效。")
        if sorted(clean_expected) != sorted(payload[key]):
            raise CapabilityReceiptError(f"capability receipt.{key}与本run授权范围不一致。")
    expected_auth_expiry = _timestamp(expected.get("authorization_expires_at"), "预期authorization_expires_at")
    if expected_auth_expiry != authorization_expires:
        raise CapabilityReceiptError("capability receipt.authorization_expires_at与本run授权不一致。")
    if str(payload["project_id"]) not in payload["allowed_project_ids"]:
        raise CapabilityReceiptError("capability receipt.allowed_project_ids未包含project_id。")

    envelope_sha = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return VerifiedCapabilityReceipt(
        receipt_id=str(payload["receipt_id"]),
        actor_id=str(payload["actor_id"]),
        run_id=str(payload["run_id"]),
        connector_id=str(payload["connector_id"]),
        operation=str(payload["operation"]),
        issuer=str(payload["issuer"]),
        key_id=str(payload["key_id"]),
        issued_at=issued.isoformat().replace("+00:00", "Z"),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
        receipt_sha256=envelope_sha,
        verified_at=now.isoformat().replace("+00:00", "Z"),
    )


def verify_source_capture_receipt(
    receipt: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    at: datetime | None = None,
) -> VerifiedSourceCaptureReceipt:
    """Verify a host-signed source snapshot without persisting source content."""

    if not isinstance(receipt, Mapping):
        raise CapabilityReceiptError("source capture receipt必须是JSON对象。")
    payload = dict(receipt)
    if set(payload) != SOURCE_REQUIRED_FIELDS:
        missing = sorted(SOURCE_REQUIRED_FIELDS - set(payload))
        extra = sorted(set(payload) - SOURCE_REQUIRED_FIELDS)
        detail = []
        if missing:
            detail.append("缺少=" + ",".join(missing))
        if extra:
            detail.append("未知=" + ",".join(extra))
        raise CapabilityReceiptError("source capture receipt字段不符合v3契约：" + "；".join(detail))
    if payload.get("schema") != SOURCE_RECEIPT_SCHEMA or payload.get("audience") != SOURCE_RECEIPT_AUDIENCE:
        raise CapabilityReceiptError("source capture receipt的schema/audience无效。")
    for key in (
        "issuer", "key_id", "receipt_id", "source_id", "source_title",
        "publisher_or_provider", "locator", "final_url", "canonical_locator",
        "publication_or_update_date", "access_date", "content_sha256",
        "capture_method", "source_group", "applicable_scope", "notes",
        "upstream_id", "run_id", "customer_id",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or not value or value != _normalized(value):
            raise CapabilityReceiptError(f"source capture receipt.{key}必须是规范化非空字符串。")
    for key in (
        "source_title", "publisher_or_provider", "publication_or_update_date",
        "access_date", "source_group", "applicable_scope", "notes", "upstream_id",
    ):
        _safe_visible_scalar(payload.get(key), f"source capture receipt.{key}")
    locator_canonical = _canonical_locator(str(payload["locator"]))
    _canonical_locator(str(payload["final_url"]))
    if payload.get("canonical_locator") != locator_canonical:
        raise CapabilityReceiptError(
            "source capture receipt.canonical_locator必须精确等于raw locator的规范化结果。"
        )
    for key in ("issuer", "key_id", "receipt_id", "customer_id"):
        if not ID_RE.fullmatch(str(payload[key])):
            raise CapabilityReceiptError(f"source capture receipt.{key}不是稳定标识符。")
    if not re.fullmatch(r"SRC-(?:I|L|N)-\d{3,}", str(payload["source_id"])):
        raise CapabilityReceiptError("source capture receipt.source_id无效。")
    if not RUN_RE.fullmatch(str(payload["run_id"])):
        raise CapabilityReceiptError("source capture receipt.run_id无效。")
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload["content_sha256"])):
        raise CapabilityReceiptError("source capture receipt.content_sha256无效。")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(payload["access_date"])):
        raise CapabilityReceiptError("source capture receipt.access_date必须为YYYY-MM-DD。")
    if payload.get("capture_method") not in {"raw-bytes-v1", "text-nfc-lf-utf8-v1"}:
        raise CapabilityReceiptError("source capture receipt.capture_method无效。")
    if not isinstance(payload.get("length"), int) or isinstance(payload.get("length"), bool) or payload["length"] < 0:
        raise CapabilityReceiptError("source capture receipt.length无效。")
    if payload.get("source_level") not in {"S", "A", "B", "C", "internal"}:
        raise CapabilityReceiptError("source capture receipt.source_level无效。")
    if payload.get("permission") not in {"public", "internal-authorized", "restricted"}:
        raise CapabilityReceiptError("source capture receipt.permission无效。")
    if payload.get("external_use") not in {"true", "false"}:
        raise CapabilityReceiptError("source capture receipt.external_use必须为true或false。")
    if payload.get("notes") not in {
        "none", "capture_limitation", "metadata_unavailable", "scope_limited"
    }:
        raise CapabilityReceiptError("source capture receipt.notes只能使用受控审计码。")
    if payload.get("permission") == "restricted" and payload.get("external_use") != "false":
        raise CapabilityReceiptError("restricted来源不得标记external_use=true。")
    for key in ("tenant_id", "project_id"):
        scope_id = payload.get(key)
        if scope_id is not None and (
            not isinstance(scope_id, str) or not ID_RE.fullmatch(scope_id)
        ):
            raise CapabilityReceiptError(f"source capture receipt.{key}必须是稳定标识符或null。")
    sensitive = bool(
        payload.get("source_level") == "internal"
        or payload.get("permission") in {"internal-authorized", "restricted"}
    )
    if sensitive and (payload.get("tenant_id") is None or payload.get("project_id") is None):
        raise CapabilityReceiptError("内部或受限来源必须绑定非空tenant_id与project_id。")

    issued = _timestamp(payload.get("issued_at"), "source capture receipt.issued_at")
    retrieved = _timestamp(payload.get("retrieved_at"), "source capture receipt.retrieved_at")
    expires = _timestamp(payload.get("expires_at"), "source capture receipt.expires_at")
    for key in ("published_at", "source_updated_at", "internal_recorded_at"):
        if payload.get(key) is not None:
            _timestamp(payload.get(key), f"source capture receipt.{key}")
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if retrieved > issued or issued > now or expires <= now or expires <= issued:
        raise CapabilityReceiptError("source capture receipt时间谱系无效、尚未签发或已过期。")

    expected_fields = (
        "source_id", "source_title", "publisher_or_provider", "locator", "final_url",
        "canonical_locator", "publication_or_update_date", "access_date", "content_sha256",
        "length", "capture_method", "retrieved_at", "published_at", "source_updated_at",
        "internal_recorded_at", "source_level", "source_group", "permission",
        "applicable_scope", "notes", "upstream_id", "external_use", "tenant_id",
        "run_id", "customer_id", "project_id",
    )
    missing_expected = [key for key in expected_fields if key not in expected]
    if missing_expected:
        raise CapabilityReceiptError("来源收据验证缺少预期字段：" + ", ".join(missing_expected))
    for key in expected_fields:
        if payload.get(key) != expected.get(key):
            raise CapabilityReceiptError(f"source capture receipt.{key}与候选来源快照不一致。")

    signature_text = payload.get("signature")
    try:
        signature = base64.b64decode(str(signature_text), validate=True)
        if len(signature) != 64:
            raise ValueError("length")
        signed_payload = {key: payload[key] for key in sorted(payload) if key != "signature"}
        _trusted_key(str(payload["issuer"]), str(payload["key_id"])).verify(
            signature,
            _canonical_bytes(signed_payload),
        )
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise CapabilityReceiptError("source capture receipt宿主Ed25519签名无效。") from exc

    envelope_sha = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return VerifiedSourceCaptureReceipt(
        receipt_id=str(payload["receipt_id"]),
        issuer=str(payload["issuer"]),
        key_id=str(payload["key_id"]),
        receipt_sha256=envelope_sha,
        expires_at=expires.isoformat().replace("+00:00", "Z"),
    )
