#!/usr/bin/env python3
"""Create candidate seal requests and verify host Ed25519 attestations.

This module never generates a key or signs an attestation.  The candidate
receipt and seal request are untrusted local metadata; only an attestation
verified against the host-injected trust root authorizes ``commit_run.py``.
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


REQUEST_SCHEMA = "discovery-call-candidate-seal-request/v3"
ATTESTATION_SCHEMA = "discovery-call-candidate-attestation/v3"
AUDIT_SCHEMA = "discovery-call-candidate-attestation-audit/v3"
ATTESTATION_AUDIENCE = "discovery-call-candidate-commit"
TRUSTED_KEYS_ENV = "DISCOVERY_CALL_CANDIDATE_TRUSTED_KEYS_JSON"
MARKER_SCHEMA = "discovery-call-candidate-receipt/v2"
MARKER_REL = Path("runtime") / "candidate-receipt.json"
MANIFEST_REL = Path("runtime") / "manifest.json"
REQUEST_REL = Path("runtime") / "candidate-seal-request.json"
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_ATTESTATION_LIFETIME = timedelta(minutes=15)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONTEXT_RE = re.compile(r"^dcx-\d{8}-[A-Za-z0-9]{8}$")
RUN_RE = re.compile(r"^dcr-\d{8}T\d{6}-[A-Za-z0-9]{4}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
MARKER_FIELDS = {
    "schema",
    "context_id",
    "run_id",
    "source_manifest_revision",
    "source_manifest_sha256",
    "source_workspace",
    "candidate_workspace",
    "input_payload_sha256",
    "final_manifest_sha256",
}
REQUEST_FIELDS = {
    "schema",
    "audience",
    "context_id",
    "run_id",
    "source_manifest_revision",
    "source_manifest_sha256",
    "source_workspace",
    "candidate_workspace",
    "input_payload_sha256",
    "final_manifest_sha256",
    "intake_gate_sha256",
    "formal_workspace",
    "customer_id",
}
ATTESTATION_FIELDS = REQUEST_FIELDS | {
    "issuer",
    "key_id",
    "attestation_id",
    "issued_at",
    "expires_at",
    "host_authorized_at",
    "session_id",
    "nonce",
    "signature",
}
BOUND_FIELDS = (
    "context_id",
    "run_id",
    "source_manifest_revision",
    "source_manifest_sha256",
    "source_workspace",
    "candidate_workspace",
    "input_payload_sha256",
    "final_manifest_sha256",
    "intake_gate_sha256",
    "formal_workspace",
    "customer_id",
)
AUDIT_FIELDS = (ATTESTATION_FIELDS - {"schema"}) | {
    "schema",
    "attestation_schema",
    "attestation_sha256",
}


class CandidateAttestationError(RuntimeError):
    """Raised when a seal request or host attestation is not trustworthy."""


@dataclass(frozen=True)
class VerifiedCandidateAttestation:
    attestation_id: str
    nonce: str
    issuer: str
    key_id: str
    issued_at: str
    expires_at: str
    host_authorized_at: str
    session_id: str
    verified_at: str
    attestation_sha256: str
    envelope: Mapping[str, Any]

    def audit_summary(
        self,
        binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return only host-signed lineage for the formal WAL commit.

        ``verified_at`` is deliberately not persisted: it is a local clock
        observation and cannot serve as durable proof that a WAL started in
        the signed validity window.  Durable acceptance additionally requires
        the protected one-time nonce claim created immediately before WAL.
        """

        for field in BOUND_FIELDS:
            if self.envelope.get(field) != binding.get(field):
                raise CandidateAttestationError(
                    f"candidate attestation.{field}无法写入漂移的审计绑定。"
                )
        audit = {
            "schema": AUDIT_SCHEMA,
            "attestation_schema": ATTESTATION_SCHEMA,
            "attestation_sha256": self.attestation_sha256,
            **{field: self.envelope[field] for field in ATTESTATION_FIELDS if field != "schema"},
        }
        if set(audit) != AUDIT_FIELDS:
            raise CandidateAttestationError("candidate attestation审计材料不完整。")
        return audit


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_intake_gate_sha256(value: Mapping[str, Any]) -> str:
    """Hash the complete persisted intake gate, including internal-only codes."""

    if not isinstance(value, Mapping):
        raise CandidateAttestationError("candidate manifest.intake_preflight必须是对象。")
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CandidateAttestationError(f"JSON包含重复字段：{key}")
        value[key] = item
    return value


def _parse_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except CandidateAttestationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateAttestationError(f"{label}不是有效UTF-8 JSON。") from exc
    if not isinstance(value, dict):
        raise CandidateAttestationError(f"{label}顶层必须是对象。")
    return value


def _read_regular(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CandidateAttestationError(f"{label}必须是现有普通文件，且不得为符号链接。")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CandidateAttestationError(f"{label}无法读取：{exc}") from exc
    if not raw or len(raw) > MAX_ENVELOPE_BYTES:
        raise CandidateAttestationError(f"{label}为空或超过64KiB上限。")
    return raw


def _timestamp(value: Any, label: str) -> datetime:
    text = _normalized(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateAttestationError(f"{label}必须是带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise CandidateAttestationError(f"{label}必须包含时区。")
    return parsed.astimezone(timezone.utc)


def _trusted_key(issuer: str, key_id: str) -> Ed25519PublicKey:
    raw_registry = os.environ.get(TRUSTED_KEYS_ENV, "").strip()
    if not raw_registry:
        raise CandidateAttestationError(f"宿主未注入{TRUSTED_KEYS_ENV}；候选提交已关闭。")
    registry = _parse_json(raw_registry.encode("utf-8"), TRUSTED_KEYS_ENV)
    issuer_keys = registry.get(issuer)
    encoded = issuer_keys.get(key_id) if isinstance(issuer_keys, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise CandidateAttestationError("candidate attestation的issuer/key_id不在宿主信任根中。")
    try:
        public = base64.b64decode(encoded, validate=True)
        if len(public) != 32:
            raise ValueError("length")
        return Ed25519PublicKey.from_public_bytes(public)
    except (ValueError, TypeError) as exc:
        raise CandidateAttestationError("宿主注入的candidate Ed25519公钥无效。") from exc


def build_seal_request(candidate_workspace: Path | str) -> dict[str, Any]:
    supplied = Path(candidate_workspace).expanduser()
    if supplied.is_symlink():
        raise CandidateAttestationError("candidate workspace不得为符号链接。")
    candidate = supplied.resolve()
    if not candidate.is_dir():
        raise CandidateAttestationError("candidate workspace必须是现有普通目录。")
    marker_path = candidate / MARKER_REL
    manifest_path = candidate / MANIFEST_REL
    marker = _parse_json(_read_regular(marker_path, "candidate receipt"), "candidate receipt")
    if set(marker) != MARKER_FIELDS or marker.get("schema") != MARKER_SCHEMA:
        raise CandidateAttestationError("candidate receipt字段或schema不符合v2契约。")
    manifest_raw = _read_regular(manifest_path, "candidate manifest")
    manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
    if marker.get("final_manifest_sha256") != manifest_digest:
        raise CandidateAttestationError("candidate receipt未绑定当前final manifest；先重建manifest并刷新本地marker。")
    if Path(str(marker.get("candidate_workspace", ""))).resolve() != candidate:
        raise CandidateAttestationError("candidate receipt未绑定当前候选路径。")
    if not CONTEXT_RE.fullmatch(str(marker.get("context_id", ""))) or not RUN_RE.fullmatch(str(marker.get("run_id", ""))):
        raise CandidateAttestationError("candidate receipt的context_id/run_id无效。")
    if not isinstance(marker.get("source_manifest_revision"), int) or isinstance(marker.get("source_manifest_revision"), bool):
        raise CandidateAttestationError("candidate receipt source_manifest_revision无效。")
    for field in ("source_manifest_sha256", "input_payload_sha256", "final_manifest_sha256"):
        if not SHA256_RE.fullmatch(str(marker.get(field, ""))):
            raise CandidateAttestationError(f"candidate receipt.{field}无效。")
    manifest = _parse_json(manifest_raw, "candidate manifest")
    intake_gate = manifest.get("intake_preflight")
    if not isinstance(intake_gate, dict):
        raise CandidateAttestationError("candidate manifest缺少完整intake_preflight。")
    customer_id = _normalized(manifest.get("customer_id"))
    if not ID_RE.fullmatch(customer_id):
        raise CandidateAttestationError("candidate manifest.customer_id不是稳定标识符。")
    source_workspace = Path(str(marker.get("source_workspace", "")))
    if not source_workspace.is_absolute():
        raise CandidateAttestationError("candidate receipt.source_workspace必须是绝对路径。")
    formal_workspace = str(source_workspace.resolve(strict=False))
    if formal_workspace != str(source_workspace):
        raise CandidateAttestationError("candidate receipt.source_workspace必须是规范绝对路径。")
    return {
        "schema": REQUEST_SCHEMA,
        "audience": ATTESTATION_AUDIENCE,
        **{
            field: marker[field]
            for field in BOUND_FIELDS
            if field not in {"intake_gate_sha256", "formal_workspace", "customer_id"}
        },
        "intake_gate_sha256": canonical_intake_gate_sha256(intake_gate),
        "formal_workspace": formal_workspace,
        "customer_id": customer_id,
    }


def write_seal_request(candidate_workspace: Path | str) -> tuple[Path, dict[str, Any]]:
    request = build_seal_request(candidate_workspace)
    candidate = Path(candidate_workspace).expanduser().resolve()
    path = candidate / REQUEST_REL
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, request


def _verify_attestation_payload(
    payload: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    at: datetime | None,
    require_current: bool,
) -> VerifiedCandidateAttestation:
    if set(payload) != ATTESTATION_FIELDS:
        missing = sorted(ATTESTATION_FIELDS - set(payload))
        extra = sorted(set(payload) - ATTESTATION_FIELDS)
        raise CandidateAttestationError(f"candidate attestation字段不符合v3契约：缺少={missing}；未知={extra}")
    if payload.get("schema") != ATTESTATION_SCHEMA or payload.get("audience") != ATTESTATION_AUDIENCE:
        raise CandidateAttestationError("candidate attestation的schema/audience无效。")
    for field in ("issuer", "key_id", "attestation_id", "session_id", "customer_id"):
        if not isinstance(payload.get(field), str) or payload[field] != _normalized(payload[field]) or not ID_RE.fullmatch(payload[field]):
            raise CandidateAttestationError(f"candidate attestation.{field}不是规范化稳定标识符。")
    if not NONCE_RE.fullmatch(str(payload.get("nonce", ""))):
        raise CandidateAttestationError("candidate attestation.nonce格式或熵长度无效。")
    if not CONTEXT_RE.fullmatch(str(payload.get("context_id", ""))) or not RUN_RE.fullmatch(str(payload.get("run_id", ""))):
        raise CandidateAttestationError("candidate attestation的context_id/run_id无效。")
    for field in (
        "source_manifest_sha256",
        "input_payload_sha256",
        "final_manifest_sha256",
        "intake_gate_sha256",
    ):
        if not SHA256_RE.fullmatch(str(payload.get(field, ""))):
            raise CandidateAttestationError(f"candidate attestation.{field}无效。")
    if not isinstance(payload.get("source_manifest_revision"), int) or isinstance(payload.get("source_manifest_revision"), bool):
        raise CandidateAttestationError("candidate attestation.source_manifest_revision无效。")
    issued = _timestamp(payload.get("issued_at"), "candidate attestation.issued_at")
    expires = _timestamp(payload.get("expires_at"), "candidate attestation.expires_at")
    host_authorized = _timestamp(
        payload.get("host_authorized_at"),
        "candidate attestation.host_authorized_at",
    )
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        expires <= issued
        or expires - issued > MAX_ATTESTATION_LIFETIME
        or not issued <= host_authorized < expires
    ):
        raise CandidateAttestationError("candidate attestation宿主授权时间倒置或超过15分钟上限。")
    if require_current and (host_authorized > now or expires <= now):
        raise CandidateAttestationError("candidate attestation宿主授权尚未生效或已过期。")
    formal_workspace = Path(str(payload.get("formal_workspace", "")))
    source_workspace = Path(str(payload.get("source_workspace", "")))
    candidate_workspace = Path(str(payload.get("candidate_workspace", "")))
    if (
        not formal_workspace.is_absolute()
        or not source_workspace.is_absolute()
        or not candidate_workspace.is_absolute()
        or str(formal_workspace.resolve(strict=False)) != str(formal_workspace)
        or str(source_workspace.resolve(strict=False)) != str(source_workspace)
        or str(candidate_workspace.resolve(strict=False)) != str(candidate_workspace)
        or formal_workspace != source_workspace
        or candidate_workspace == formal_workspace
    ):
        raise CandidateAttestationError(
            "candidate attestation的formal/source/candidate workspace必须是规范、分离的绝对路径。"
        )
    missing_expected = [field for field in BOUND_FIELDS if field not in expected]
    if missing_expected:
        raise CandidateAttestationError("candidate attestation验证缺少预期字段：" + ", ".join(missing_expected))
    for field in BOUND_FIELDS:
        if payload.get(field) != expected.get(field):
            raise CandidateAttestationError(f"candidate attestation.{field}与当前候选封印不一致。")
    try:
        signature = base64.b64decode(str(payload.get("signature")), validate=True)
        if len(signature) != 64:
            raise ValueError("length")
        signed = {key: payload[key] for key in sorted(payload) if key != "signature"}
        _trusted_key(str(payload["issuer"]), str(payload["key_id"])).verify(signature, canonical_bytes(signed))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise CandidateAttestationError("candidate attestation宿主Ed25519签名无效。") from exc
    return VerifiedCandidateAttestation(
        attestation_id=str(payload["attestation_id"]),
        nonce=str(payload["nonce"]),
        issuer=str(payload["issuer"]),
        key_id=str(payload["key_id"]),
        issued_at=issued.isoformat().replace("+00:00", "Z"),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
        host_authorized_at=host_authorized.isoformat().replace("+00:00", "Z"),
        session_id=str(payload["session_id"]),
        verified_at=now.isoformat().replace("+00:00", "Z"),
        attestation_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest(),
        envelope=dict(payload),
    )


def verify_candidate_attestation(
    path_value: Path | str,
    *,
    expected: Mapping[str, Any],
    at: datetime | None = None,
) -> VerifiedCandidateAttestation:
    payload = _parse_json(
        _read_regular(Path(path_value).expanduser(), "candidate attestation"),
        "candidate attestation",
    )
    return _verify_attestation_payload(
        payload,
        expected=expected,
        at=at,
        require_current=True,
    )


def verify_persisted_candidate_attestation(
    audit: Mapping[str, Any],
    *,
    current_intake_gate: Mapping[str, Any],
    current_workspace: Path | str,
    at: datetime | None = None,
) -> VerifiedCandidateAttestation:
    """Verify a durable v3 authorization after its short TTL has elapsed.

    No locally supplied timestamp is trusted. Historical acceptance requires
    a still-trusted host signature, an exact current-root/full-gate binding,
    and the protected one-time nonce claim made before the candidate WAL.
    """

    if not isinstance(audit, Mapping) or set(audit) != AUDIT_FIELDS:
        raise CandidateAttestationError("candidate attestation历史审计材料字段不完整或含未知字段。")
    if (
        audit.get("schema") != AUDIT_SCHEMA
        or audit.get("attestation_schema") != ATTESTATION_SCHEMA
        or audit.get("audience") != ATTESTATION_AUDIENCE
    ):
        raise CandidateAttestationError("candidate attestation历史审计schema/audience无效。")
    current_gate_sha = canonical_intake_gate_sha256(current_intake_gate)
    if audit.get("intake_gate_sha256") != current_gate_sha:
        raise CandidateAttestationError(
            "candidate attestation.intake_gate_sha256与当前完整intake门禁不一致；需重建候选并重新签章。"
        )
    supplied_workspace = Path(current_workspace).expanduser()
    resolved_workspace = supplied_workspace.resolve(strict=False)
    if (
        not supplied_workspace.is_absolute()
        or str(supplied_workspace) != str(resolved_workspace)
        or audit.get("formal_workspace") != str(resolved_workspace)
        or audit.get("source_workspace") != str(resolved_workspace)
    ):
        raise CandidateAttestationError(
            "candidate attestation.formal_workspace与当前正式workspace不一致；禁止克隆或路径重绑定。"
        )
    envelope = {
        "schema": audit["attestation_schema"],
        **{field: audit[field] for field in ATTESTATION_FIELDS if field != "schema"},
    }
    verified = _verify_attestation_payload(
        envelope,
        expected={field: audit[field] for field in BOUND_FIELDS},
        at=at,
        require_current=False,
    )
    if verified.attestation_sha256 != audit.get("attestation_sha256"):
        raise CandidateAttestationError("candidate attestation历史审计摘要与完整签章不一致。")
    try:
        from governance import GovernanceError, validate_global_nonce_claim
    except ImportError as exc:
        raise CandidateAttestationError(
            f"candidate attestation无法加载受保护nonce验证器：{exc}"
        ) from exc
    try:
        validate_global_nonce_claim(
            verified.envelope,
            workspace=resolved_workspace,
            event_id=verified.attestation_id,
            operation="candidate_commit",
            consumed_at=verified.host_authorized_at,
        )
    except GovernanceError as exc:
        raise CandidateAttestationError(
            f"candidate attestation缺少受保护的提交nonce消费证明：{exc}"
        ) from exc
    return verified


def claim_candidate_attestation_nonce(
    verified: VerifiedCandidateAttestation,
    *,
    workspace: Path | str,
    at: datetime | None = None,
) -> Path:
    """Burn the signed commit nonce immediately before opening the WAL."""

    resolved_workspace = Path(workspace).expanduser().resolve()
    expected = {field: verified.envelope.get(field) for field in BOUND_FIELDS}
    freshly_verified = _verify_attestation_payload(
        verified.envelope,
        expected=expected,
        at=at,
        require_current=True,
    )
    if freshly_verified.attestation_sha256 != verified.attestation_sha256:
        raise CandidateAttestationError("candidate attestation在nonce消费前发生漂移。")
    if freshly_verified.envelope.get("formal_workspace") != str(resolved_workspace):
        raise CandidateAttestationError("candidate attestation未绑定当前正式workspace。")
    try:
        from governance import GovernanceError, claim_global_nonce
    except ImportError as exc:
        raise CandidateAttestationError(
            f"candidate attestation无法加载受保护nonce消费器：{exc}"
        ) from exc
    try:
        return claim_global_nonce(
            freshly_verified.envelope,
            workspace=resolved_workspace,
            event_id=freshly_verified.attestation_id,
            operation="candidate_commit",
            claimed_at=freshly_verified.host_authorized_at,
        )
    except GovernanceError as exc:
        raise CandidateAttestationError(
            f"candidate attestation提交nonce无法原子消费：{exc}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="生成待认证宿主签名的candidate seal request；本工具不会签名。")
    parser.add_argument("candidate_workspace")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        path, request = write_seal_request(args.candidate_workspace)
    except (CandidateAttestationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"request_path": str(path), "seal_request": request}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
