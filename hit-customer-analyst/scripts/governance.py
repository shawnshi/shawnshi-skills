#!/usr/bin/env python3
"""Trusted human-actor and explicit external-request governance.

The registry is injected by the authenticated host.  This module deliberately
does not expose a command that can create actors, grants, or request events:
the skill may consume host assertions, but it must never mint its own authority.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


GOVERNANCE_SCHEMA = "discovery-call-governance/v1"
IDENTITY_ASSERTION_SCHEMA = "discovery-call-identity-assertion/v1"
ACTION_ASSERTION_SCHEMA = "discovery-call-action-assertion/v1"
EXTERNAL_REQUEST_ASSERTION_SCHEMA = "discovery-call-external-request-assertion/v1"
GOVERNANCE_CONTEXT_REL = Path("runtime") / "governance-context.json"
ACTOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRUST_AUDIENCE = "discovery-call-governance"
PUBLIC_KEY_ENV = "DISCOVERY_CALL_GOVERNANCE_PUBLIC_KEY_B64"
TRUSTED_ISSUER_ENV = "DISCOVERY_CALL_GOVERNANCE_TRUSTED_ISSUER"
TRUSTED_KEY_ID_ENV = "DISCOVERY_CALL_GOVERNANCE_TRUSTED_KEY_ID"
NONCE_DIR_ENV = "DISCOVERY_CALL_GOVERNANCE_NONCE_DIR"
MAX_ACTION_ASSERTION_SECONDS = 15 * 60
GENERIC_ACTORS = {
    "ai",
    "chatgpt",
    "gpt",
    "assistant",
    "bot",
    "model",
    "agent",
    "模型",
    "领导",
    "销售",
    "审核人",
    "审批人",
    "负责人",
    "管理员",
    "待确认",
    "待指定",
}


class GovernanceError(RuntimeError):
    """Raised when a trusted governance assertion is missing or invalid."""


@dataclass(frozen=True)
class ActorAuthorization:
    actor_id: str
    display_name: str
    role: str
    grant_id: str
    identity_provider: str

    def audit_fields(self, prefix: str) -> dict[str, str]:
        return {
            f"{prefix}_actor_id": self.actor_id,
            f"{prefix}_role": self.role,
            f"{prefix}_authority_id": self.grant_id,
            f"{prefix}_identity_provider": self.identity_provider,
        }


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _timestamp(value: Any, label: str) -> datetime:
    text = _normalized(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GovernanceError(f"{label}必须为带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise GovernanceError(f"{label}必须包含时区。")
    return parsed.astimezone(timezone.utc)


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and _normalized(item) for item in value):
        raise GovernanceError(f"{label}必须是非空字符串数组。")
    return [_normalized(item) for item in value]


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def identity_assertion_payload(registry: Mapping[str, Any]) -> dict[str, Any]:
    assertion = registry.get("identity_assertion")
    if not isinstance(assertion, Mapping):
        raise GovernanceError("治理上下文缺少宿主签名identity_assertion。")
    return {
        "schema": assertion.get("schema"),
        "issuer": assertion.get("issuer"),
        "audience": assertion.get("audience"),
        "key_id": assertion.get("key_id"),
        "issued_at": assertion.get("issued_at"),
        "expires_at": assertion.get("expires_at"),
        "context_id": registry.get("context_id"),
        "customer_id": registry.get("customer_id"),
        "runtime_actor_id": registry.get("runtime_actor_id"),
        "actors": registry.get("actors"),
    }


def external_request_assertion_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"signature", "consumed_at", "consumed_by_run_id"}
    return {key: event[key] for key in sorted(event) if key not in excluded}


def action_assertion_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"signature", "consumed_at", "consumed_by_run_id"}
    return {key: event[key] for key in sorted(event) if key not in excluded}


def _public_key() -> Ed25519PublicKey:
    encoded = os.environ.get(PUBLIC_KEY_ENV, "").strip()
    if not encoded:
        raise GovernanceError(f"宿主未注入{PUBLIC_KEY_ENV}信任根；治理写操作已关闭。")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != 32:
            raise ValueError("length")
        return Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise GovernanceError("宿主Ed25519治理公钥无效。") from exc


def _verify_assertion(
    payload: Mapping[str, Any],
    signature_text: Any,
    *,
    label: str,
    require_current: bool = False,
    at: datetime | None = None,
    max_lifetime_seconds: int | None = None,
) -> tuple[datetime, datetime]:
    trusted_issuer = os.environ.get(TRUSTED_ISSUER_ENV, "").strip()
    trusted_key_id = os.environ.get(TRUSTED_KEY_ID_ENV, "").strip()
    if not trusted_issuer or not trusted_key_id:
        raise GovernanceError(
            f"宿主未注入{TRUSTED_ISSUER_ENV}/{TRUSTED_KEY_ID_ENV}；治理写操作已关闭。"
        )
    if (
        payload.get("audience") != TRUST_AUDIENCE
        or payload.get("issuer") != trusted_issuer
        or payload.get("key_id") != trusted_key_id
    ):
        raise GovernanceError(f"{label}的issuer/audience/key_id无效。")
    try:
        signature = base64.b64decode(str(signature_text), validate=True)
        if len(signature) != 64:
            raise ValueError("signature length")
        _public_key().verify(signature, _canonical_bytes(payload))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise GovernanceError(f"{label}的宿主Ed25519签名无效。") from exc
    issued = _timestamp(payload.get("issued_at"), f"{label}.issued_at")
    expires = _timestamp(payload.get("expires_at"), f"{label}.expires_at")
    if expires <= issued:
        raise GovernanceError(f"{label}有效期无效。")
    if max_lifetime_seconds is not None and (expires - issued).total_seconds() > max_lifetime_seconds:
        raise GovernanceError(f"{label}有效期超过{max_lifetime_seconds}秒上限。")
    if require_current:
        current = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if not issued <= current < expires:
            raise GovernanceError(f"{label}尚未生效或已过期。")
    return issued, expires


def load_governance_context(workspace: Path) -> dict[str, Any]:
    root = workspace.resolve()
    path = root / GOVERNANCE_CONTEXT_REL
    if path.is_symlink() or not path.is_file() or path.resolve().parent != (root / "runtime").resolve():
        raise GovernanceError("缺少宿主注入的普通文件runtime/governance-context.json；高风险治理操作已关闭。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GovernanceError(f"治理上下文无法读取：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != GOVERNANCE_SCHEMA:
        raise GovernanceError("治理上下文schema无效。")
    if not isinstance(payload.get("actors"), dict) or not isinstance(payload.get("external_requests"), dict):
        raise GovernanceError("治理上下文必须包含actors与external_requests对象。")
    identity = payload.get("identity_assertion")
    identity_payload = identity_assertion_payload(payload)
    if identity_payload.get("schema") != IDENTITY_ASSERTION_SCHEMA:
        raise GovernanceError("identity_assertion.schema无效。")
    _verify_assertion(
        identity_payload,
        identity.get("signature") if isinstance(identity, dict) else None,
        label="identity_assertion",
        require_current=True,
    )
    actions = payload.get("action_assertions")
    if not isinstance(actions, dict):
        raise GovernanceError("治理上下文必须包含action_assertions对象。")
    for event_id, event in actions.items():
        if not isinstance(event, dict) or not EVENT_ID_RE.fullmatch(str(event_id)):
            raise GovernanceError("治理动作断言ID或结构无效。")
        if event.get("schema") != ACTION_ASSERTION_SCHEMA or event.get("action_id") != event_id:
            raise GovernanceError(f"action_assertion[{event_id}]的schema/action_id无效。")
        _verify_assertion(
            action_assertion_payload(event),
            event.get("signature"),
            label=f"action_assertion[{event_id}]",
            max_lifetime_seconds=MAX_ACTION_ASSERTION_SECONDS,
        )
    for event_id, event in payload["external_requests"].items():
        if not isinstance(event, dict) or not EVENT_ID_RE.fullmatch(str(event_id)):
            raise GovernanceError("外发请求事件ID或结构无效。")
        if event.get("schema") != EXTERNAL_REQUEST_ASSERTION_SCHEMA or event.get("request_id") != event_id:
            raise GovernanceError(f"external_request[{event_id}]的schema/request_id无效。")
        _verify_assertion(
            external_request_assertion_payload(event),
            event.get("signature"),
            label=f"external_request[{event_id}]",
            max_lifetime_seconds=MAX_ACTION_ASSERTION_SECONDS,
        )
    return payload


def _scope_match(values: Sequence[str], current: str) -> bool:
    return "*" in values or current in values


def resolve_actor(
    workspace: Path,
    *,
    actor_id: str,
    display_name: str,
    operation: str,
    required_roles: set[str],
    context_id: str,
    customer_id: str,
    business_mode: str,
    separate_from_runtime: bool = True,
    at: datetime | None = None,
    registry: Mapping[str, Any] | None = None,
) -> ActorAuthorization:
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    canonical_actor_id = _normalized(actor_id)
    if not ACTOR_ID_RE.fullmatch(canonical_actor_id):
        raise GovernanceError("--actor-id必须是3—128字符的稳定身份标识。")
    payload = dict(registry or load_governance_context(workspace))
    if payload.get("context_id") != context_id or payload.get("customer_id") != customer_id:
        raise GovernanceError("治理上下文与当前context/customer不一致。")
    if separate_from_runtime and canonical_actor_id == _normalized(payload.get("runtime_actor_id")):
        raise GovernanceError("该治理动作必须由不同于本次运行执行者的独立真人完成。")
    actors = payload.get("actors", {})
    actor = actors.get(canonical_actor_id) if isinstance(actors, dict) else None
    if not isinstance(actor, dict):
        raise GovernanceError("--actor-id不在宿主可信身份登记中。")
    canonical_display = _normalized(actor.get("display_name"))
    if (
        actor.get("actor_type") != "human"
        or actor.get("status") != "active"
        or not canonical_display
        or canonical_display.casefold() in GENERIC_ACTORS
    ):
        raise GovernanceError("治理动作只接受宿主登记的active human，模型、服务账号或泛化角色均被拒绝。")
    if _normalized(display_name) != canonical_display:
        raise GovernanceError("--approver/--reviewer必须与可信身份登记中的规范显示名完全一致。")
    identity_provider = _normalized(actor.get("identity_provider"))
    if not identity_provider or identity_provider.casefold() in GENERIC_ACTORS:
        raise GovernanceError("可信身份缺少稳定identity_provider。")
    grants = actor.get("grants")
    if not isinstance(grants, list):
        raise GovernanceError("可信身份没有结构化授权grant。")
    failures: list[str] = []
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        role = _normalized(grant.get("role"))
        grant_id = _normalized(grant.get("grant_id"))
        try:
            operations = _string_list(grant.get("operations"), "grant.operations")
            modes = _string_list(grant.get("business_modes"), "grant.business_modes")
            customers = _string_list(grant.get("customer_ids"), "grant.customer_ids")
            valid_from = _timestamp(grant.get("valid_from"), "grant.valid_from")
            expires_at = _timestamp(grant.get("expires_at"), "grant.expires_at")
        except GovernanceError as exc:
            failures.append(str(exc))
            continue
        if not grant_id or not ACTOR_ID_RE.fullmatch(grant_id):
            failures.append("grant_id无效")
            continue
        if role not in required_roles or operation not in operations:
            continue
        if not _scope_match(modes, business_mode) or not _scope_match(customers, customer_id):
            failures.append("grant业务模式或客户范围不匹配")
            continue
        if not valid_from <= now < expires_at:
            failures.append("grant尚未生效或已过期")
            continue
        return ActorAuthorization(canonical_actor_id, canonical_display, role, grant_id, identity_provider)
    detail = "；".join(dict.fromkeys(failures))
    raise GovernanceError(
        f"可信身份没有满足role/operation/customer/mode/time范围的有效授权：{operation}"
        + (f"（{detail}）" if detail else "。")
    )


def resolve_action_assertion(
    workspace: Path,
    *,
    event_id: str,
    actor_id: str,
    display_name: str,
    operation: str,
    required_roles: set[str],
    context_id: str,
    customer_id: str,
    business_mode: str,
    target_artifact_type: str,
    target_content_version: str,
    target_body_sha256: str,
    target_context_sha256: str = "",
    separate_from_runtime: bool = True,
    at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], ActorAuthorization]:
    current = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    canonical_event_id = _normalized(event_id)
    if not EVENT_ID_RE.fullmatch(canonical_event_id):
        raise GovernanceError("--action-event-id必须是3—128字符的稳定事件标识。")
    registry = load_governance_context(workspace)
    event = registry.get("action_assertions", {}).get(canonical_event_id)
    if not isinstance(event, dict):
        raise GovernanceError("治理动作缺少宿主签名的当前人工决定断言。")
    _verify_assertion(
        action_assertion_payload(event),
        event.get("signature"),
        label=f"action_assertion[{canonical_event_id}]",
        require_current=True,
        at=current,
        max_lifetime_seconds=MAX_ACTION_ASSERTION_SECONDS,
    )
    event_actor_id = _normalized(event.get("actor_id"))
    if event_actor_id != _normalized(actor_id):
        raise GovernanceError("--actor-id与宿主签名治理动作的actor_id不一致。")
    required_exact = {
        "schema": ACTION_ASSERTION_SCHEMA,
        "action_id": canonical_event_id,
        "event_type": "governance_action_approved",
        "source": "authenticated_human_action",
        "verified": True,
        "decision": "approved",
        "actor_id": event_actor_id,
        "operation": operation,
        "context_id": context_id,
        "customer_id": customer_id,
        "business_mode": business_mode,
        "target_artifact_type": target_artifact_type,
        "target_content_version": target_content_version,
        "target_body_sha256": target_body_sha256,
        "target_context_sha256": target_context_sha256,
    }
    mismatched = [key for key, expected in required_exact.items() if event.get(key) != expected]
    if mismatched:
        raise GovernanceError("治理动作断言与当前目标不一致：" + ", ".join(sorted(mismatched)))
    if not _normalized(event.get("session_id")) or not _normalized(event.get("nonce")):
        raise GovernanceError("治理动作断言缺少宿主session_id或nonce。")
    if event.get("consumed_at") is not None or event.get("consumed_by_run_id") is not None:
        raise GovernanceError("治理动作断言已经消费，不得重放。")
    actor = resolve_actor(
        workspace,
        actor_id=event_actor_id,
        display_name=display_name,
        operation=operation,
        required_roles=required_roles,
        context_id=context_id,
        customer_id=customer_id,
        business_mode=business_mode,
        separate_from_runtime=separate_from_runtime,
        at=current,
        registry=registry,
    )
    return registry, copy.deepcopy(event), actor


def resolve_external_request(
    workspace: Path,
    *,
    event_id: str,
    actor_id: str,
    internal: Mapping[str, str],
    total: Mapping[str, str],
    at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], ActorAuthorization]:
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    canonical_event_id = _normalized(event_id)
    if not EVENT_ID_RE.fullmatch(canonical_event_id):
        raise GovernanceError("--request-event-id必须是3—128字符的稳定事件标识。")
    registry = load_governance_context(workspace)
    events = registry.get("external_requests", {})
    event = events.get(canonical_event_id) if isinstance(events, dict) else None
    if not isinstance(event, dict):
        raise GovernanceError("外发请求事件不存在；必须由宿主记录审批后的第二次明确用户请求。")
    _verify_assertion(
        external_request_assertion_payload(event),
        event.get("signature"),
        label=f"external_request[{canonical_event_id}]",
        require_current=True,
        at=now,
        max_lifetime_seconds=MAX_ACTION_ASSERTION_SECONDS,
    )
    event_actor_id = _normalized(event.get("actor_id"))
    if event_actor_id != _normalized(actor_id):
        raise GovernanceError("--actor-id与外发请求事件的请求人不一致。")
    actor = resolve_actor(
        workspace,
        actor_id=event_actor_id,
        display_name=_normalized(registry.get("actors", {}).get(event_actor_id, {}).get("display_name")),
        operation="emit_external",
        required_roles={"requester", "account_owner"},
        context_id=str(total.get("context_id", "")),
        customer_id=str(total.get("customer_id", "")),
        business_mode=str(total.get("business_mode", "")),
        separate_from_runtime=False,
        at=now,
        registry=registry,
    )
    required_exact = {
        "schema": EXTERNAL_REQUEST_ASSERTION_SCHEMA,
        "request_id": canonical_event_id,
        "event_type": "external_output_requested",
        "source": "authenticated_user_turn",
        "operation": "emit_external",
        "business_mode": str(total.get("business_mode", "")),
        "context_id": str(total.get("context_id", "")),
        "customer_id": str(total.get("customer_id", "")),
        "approval_run_id": str(internal.get("latest_run_id", "")),
        "internal_content_version": str(internal.get("content_version", "")),
        "approved_body_sha256": str(internal.get("approved_body_sha256", "")),
        "approved_context_sha256": str(internal.get("approved_context_sha256", "")),
    }
    for key, expected in required_exact.items():
        if event.get(key) != expected:
            raise GovernanceError(f"外发请求事件{key}与当前批准谱系不一致。")
    if event.get("verified") is not True:
        raise GovernanceError("外发请求事件必须由宿主标记verified=true。")
    if not _normalized(event.get("session_id")) or not _normalized(event.get("nonce")):
        raise GovernanceError("外发请求事件缺少宿主session_id或nonce。")
    if event.get("consumed_at") is not None or event.get("consumed_by_run_id") is not None:
        raise GovernanceError("外发请求事件已经消费，不得重放。")
    requested_at = _timestamp(event.get("requested_at"), "external_request.requested_at")
    expires_at = _timestamp(event.get("expires_at"), "external_request.expires_at")
    approved_at = _timestamp(internal.get("approved_at"), "approved_at")
    if requested_at <= approved_at:
        raise GovernanceError("第二次明确外发请求必须发生在当前审批之后。")
    issued_at = _timestamp(event.get("issued_at"), "external_request.issued_at")
    if requested_at < issued_at:
        raise GovernanceError("第二次明确外发请求不得早于宿主断言签发时间。")
    if not requested_at <= now < expires_at:
        raise GovernanceError("外发请求事件尚未生效或已过期。")
    return registry, copy.deepcopy(event), actor


def claim_global_nonce(
    event: Mapping[str, Any],
    *,
    workspace: Path,
    event_id: str,
    operation: str,
    claimed_at: str,
) -> Path:
    """Burn a host-signed nonce in a shared directory before local mutation.

    The ledger deliberately has no delete/release API.  If the following local
    transaction fails, the host must issue a new assertion rather than risk a
    replay after a crash or workspace clone.
    """
    raw_root = os.environ.get(NONCE_DIR_ENV, "").strip()
    if not raw_root:
        raise GovernanceError(f"宿主未注入{NONCE_DIR_ENV}共享消费账本；治理写操作已关闭。")
    configured = Path(raw_root)
    if not configured.is_absolute() or configured.is_symlink():
        raise GovernanceError("共享消费账本必须是宿主配置的绝对普通目录，且不得为符号链接。")
    root = configured.resolve()
    if root != configured or not root.is_dir():
        raise GovernanceError("共享消费账本路径无效或包含重定向。")
    workspace_root = workspace.resolve()
    if root == workspace_root or workspace_root in root.parents:
        raise GovernanceError("共享消费账本不得位于工作区内。")
    metadata = root.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
        raise GovernanceError("共享消费账本必须仅对宿主服务账号开放（目录权限0700）。")
    if metadata.st_uid != os.geteuid():
        raise GovernanceError("共享消费账本必须由当前受控宿主服务账号持有。")
    nonce = _normalized(event.get("nonce"))
    session_id = _normalized(event.get("session_id"))
    if not nonce or not session_id:
        raise GovernanceError("宿主签名事件缺少session_id或nonce。")
    marker_id = hashlib.sha256(
        f"{event.get('issuer', '')}\n{event.get('key_id', '')}\n{nonce}".encode("utf-8")
    ).hexdigest()
    marker = root / f"{marker_id}.consumed"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(marker, flags, 0o600)
    except FileExistsError as exc:
        raise GovernanceError("宿主签名事件nonce已在共享账本消费，不得跨工作区或恢复快照重放。") from exc
    except OSError as exc:
        raise GovernanceError(f"共享消费账本无法原子登记nonce：{exc}") from exc
    record = {
        "schema": "discovery-call-global-consumption/v1",
        "event_id": event_id,
        "operation": operation,
        "context_id": event.get("context_id"),
        "customer_id": event.get("customer_id"),
        "session_id": session_id,
        "nonce_sha256": hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        "claimed_at": claimed_at,
    }
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(record) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Do not remove the marker: a failed or interrupted claim remains spent.
        raise
    return marker


def validate_global_nonce_claim(
    event: Mapping[str, Any],
    *,
    workspace: Path,
    event_id: str,
    operation: str,
    consumed_at: str,
) -> None:
    """Verify that a consumed signed event has a matching shared-ledger claim."""
    raw_root = os.environ.get(NONCE_DIR_ENV, "").strip()
    if not raw_root:
        raise GovernanceError(f"宿主未注入{NONCE_DIR_ENV}共享消费账本；治理校验已关闭。")
    configured = Path(raw_root)
    if not configured.is_absolute() or configured.is_symlink():
        raise GovernanceError("共享消费账本必须是宿主配置的绝对普通目录，且不得为符号链接。")
    root = configured.resolve()
    workspace_root = workspace.resolve()
    if root != configured or not root.is_dir() or root == workspace_root or workspace_root in root.parents:
        raise GovernanceError("共享消费账本路径无效、包含重定向或位于工作区内。")
    metadata = root.stat()
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise GovernanceError("共享消费账本的属主或权限不安全。")
    nonce = _normalized(event.get("nonce"))
    if not nonce:
        raise GovernanceError("宿主签名事件缺少nonce。")
    marker_id = hashlib.sha256(
        f"{event.get('issuer', '')}\n{event.get('key_id', '')}\n{nonce}".encode("utf-8")
    ).hexdigest()
    marker = root / f"{marker_id}.consumed"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_mode & 0o077:
        raise GovernanceError("宿主签名事件缺少受保护的共享消费记录。")
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GovernanceError("共享消费记录损坏。") from exc
    expected = {
        "schema": "discovery-call-global-consumption/v1",
        "event_id": event_id,
        "operation": operation,
        "context_id": event.get("context_id"),
        "customer_id": event.get("customer_id"),
        "session_id": event.get("session_id"),
        "nonce_sha256": hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        "claimed_at": consumed_at,
    }
    mismatched = [key for key, value in expected.items() if record.get(key) != value]
    if mismatched:
        raise GovernanceError("共享消费记录与成果谱系不一致：" + ", ".join(sorted(mismatched)))


def consume_external_request(
    registry: Mapping[str, Any],
    *,
    event_id: str,
    consumed_at: str,
    run_id: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(registry))
    events = result.get("external_requests")
    if not isinstance(events, dict) or not isinstance(events.get(event_id), dict):
        raise GovernanceError("待消费外发请求事件不存在。")
    event = events[event_id]
    if event.get("consumed_at") is not None or event.get("consumed_by_run_id") is not None:
        raise GovernanceError("外发请求事件已经消费，不得重放。")
    event["consumed_at"] = consumed_at
    event["consumed_by_run_id"] = run_id
    result["updated_at"] = consumed_at
    return result


def consume_action_assertion(
    registry: Mapping[str, Any],
    *,
    event_id: str,
    consumed_at: str,
    run_id: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(registry))
    events = result.get("action_assertions")
    if not isinstance(events, dict) or not isinstance(events.get(event_id), dict):
        raise GovernanceError("待消费治理动作断言不存在。")
    event = events[event_id]
    if event.get("consumed_at") is not None or event.get("consumed_by_run_id") is not None:
        raise GovernanceError("治理动作断言已经消费，不得重放。")
    event["consumed_at"] = consumed_at
    event["consumed_by_run_id"] = run_id
    result["updated_at"] = consumed_at
    return result


def governance_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
