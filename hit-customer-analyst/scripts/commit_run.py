#!/usr/bin/env python3
"""Validate and atomically commit a prepared discovery-call candidate run."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import preflight_intake as intake_preflight
import build_candidate as candidate_builder

try:
    from candidate_attestation import (
        CandidateAttestationError,
        VerifiedCandidateAttestation,
        canonical_intake_gate_sha256,
        claim_candidate_attestation_nonce,
        verify_candidate_attestation,
    )
except ModuleNotFoundError:
    _candidate_attestation_path = Path(__file__).with_name("candidate_attestation.py")
    _candidate_attestation_spec = importlib.util.spec_from_file_location(
        "candidate_attestation", _candidate_attestation_path
    )
    if _candidate_attestation_spec is None or _candidate_attestation_spec.loader is None:
        raise RuntimeError(f"无法加载候选签章模块：{_candidate_attestation_path}")
    _candidate_attestation_module = importlib.util.module_from_spec(_candidate_attestation_spec)
    sys.modules["candidate_attestation"] = _candidate_attestation_module
    _candidate_attestation_spec.loader.exec_module(_candidate_attestation_module)
    CandidateAttestationError = _candidate_attestation_module.CandidateAttestationError
    VerifiedCandidateAttestation = _candidate_attestation_module.VerifiedCandidateAttestation
    canonical_intake_gate_sha256 = _candidate_attestation_module.canonical_intake_gate_sha256
    claim_candidate_attestation_nonce = _candidate_attestation_module.claim_candidate_attestation_nonce
    verify_candidate_attestation = _candidate_attestation_module.verify_candidate_attestation

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
from init_workspace import (
    SUFFIXES,
    selected_callable_modules,
    validate_runtime_postflight,
    validate_workspace_postflight,
)
from runtime_tx import (
    EVIDENCE_MANIFEST_REL,
    GOVERNANCE_CONTEXT_REL,
    MANIFEST_REL,
    RUN_METRICS_REL,
    SEARCH_PLAN_REL,
    SOURCE_CACHE_REL,
    CASMismatch,
    RecoveryRequired,
    TxError,
    assert_manifest_cas,
    build_manifest,
    file_state,
    load_manifest,
    manifest_state,
    output_root_lock,
    parse_frontmatter,
    recover_transaction,
    relative_target,
    sha256_bytes,
    sha256_file,
    transactional_commit,
    unfinished_transaction,
    verify_manifest_artifacts,
    workspace_lock,
)


COMMITTABLE_RUNTIME_RELS = {
    SEARCH_PLAN_REL,
    SOURCE_CACHE_REL,
    EVIDENCE_MANIFEST_REL,
    RUN_METRICS_REL,
}
CANDIDATE_RECEIPT_REL = Path("runtime") / "candidate-receipt.json"
CANDIDATE_RECEIPT_FIELDS = {
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


@dataclass(frozen=True)
class CandidateSnapshot:
    workspace: Path
    marker: dict[str, Any]
    manifest: dict[str, Any]
    manifest_bytes: bytes
    payload_by_relative: dict[Path, bytes]
    monitored_bytes: dict[Path, bytes]
    attestation_path: Path
    attestation_expected: dict[str, Any]
    attestation: VerifiedCandidateAttestation


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TxError(f"candidate JSON包含重复字段：{key}")
        value[key] = item
    return value


def _json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except TxError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TxError(f"{label}不是有效UTF-8 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise TxError(f"{label}必须为JSON对象。")
    return value


def _read_candidate_bytes(candidate: Path, relative: Path, label: str) -> bytes:
    if relative.is_absolute() or ".." in relative.parts:
        raise TxError(f"{label}路径越界。")
    common_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = common_flags | getattr(os, "O_DIRECTORY", 0)
    directory_descriptors: list[int] = []
    descriptor: int | None = None
    try:
        try:
            root_descriptor = os.open(candidate, directory_flags)
            directory_descriptors.append(root_descriptor)
            if not stat.S_ISDIR(os.fstat(root_descriptor).st_mode):
                raise TxError(f"{label}候选根不是普通目录。")
            for component in relative.parts[:-1]:
                next_descriptor = os.open(component, directory_flags, dir_fd=directory_descriptors[-1])
                directory_descriptors.append(next_descriptor)
                if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                    raise TxError(f"{label}父路径不是普通目录。")
            descriptor = os.open(relative.name, common_flags, dir_fd=directory_descriptors[-1])
        except OSError as exc:
            raise TxError(f"{label}缺失、为符号链接或无法读取：{exc}") from exc
        assert descriptor is not None
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise TxError(f"{label}不是普通文件。")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def _snapshot_manifest_payload(
    candidate: Path,
    manifest: Mapping[str, Any],
) -> tuple[dict[Path, bytes], dict[Path, bytes]]:
    payload: dict[Path, bytes] = {}
    monitored: dict[Path, bytes] = {}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TxError("candidate manifest.artifacts无效。")
    artifact_paths: set[Path] = set()
    for artifact_type, record in artifacts.items():
        if not isinstance(record, dict):
            raise TxError(f"candidate manifest成果记录无效：{artifact_type}")
        relative = Path(str(record.get("path", "")))
        expected_sha = str(record.get("sha256", ""))
        if len(relative.parts) != 1 or relative.suffix.casefold() != ".md" or relative in artifact_paths:
            raise TxError(f"candidate manifest成果路径无效或重复：{relative}")
        raw = _read_candidate_bytes(candidate, relative, f"candidate成果{relative}")
        if sha256_bytes(raw) != expected_sha:
            raise CASMismatch(f"candidate成果与已签manifest摘要不一致：{relative}")
        artifact_paths.add(relative)
        payload[relative] = raw
        monitored[relative] = raw
    actual_markdown: set[Path] = set()
    for path in candidate.glob("*.md"):
        if path.is_symlink() or not path.is_file():
            raise TxError(f"candidate根目录含非普通Markdown：{path.name}")
        actual_markdown.add(Path(path.name))
    if actual_markdown != artifact_paths:
        missing = sorted(str(path) for path in artifact_paths - actual_markdown)
        extra = sorted(str(path) for path in actual_markdown - artifact_paths)
        raise TxError(f"candidate Markdown集合与已签manifest不一致：缺少={missing}；未登记={extra}")

    runtime_records = manifest.get("runtime_files")
    expected_runtime_names = {relative.name for relative in COMMITTABLE_RUNTIME_RELS}
    allowed_runtime_names = expected_runtime_names | {GOVERNANCE_CONTEXT_REL.name}
    actual_runtime_names = set(runtime_records) if isinstance(runtime_records, dict) else set()
    if not expected_runtime_names <= actual_runtime_names or not actual_runtime_names <= allowed_runtime_names:
        missing = sorted(expected_runtime_names - actual_runtime_names)
        extra = sorted(actual_runtime_names - allowed_runtime_names)
        raise TxError(f"candidate manifest必须绑定四件套机器文件：缺少={missing}；未知={extra}")
    assert isinstance(runtime_records, dict)
    for name, record in runtime_records.items():
        if not isinstance(record, dict):
            raise TxError(f"candidate manifest机器文件记录无效：{name}")
        relative = Path(str(record.get("path", "")))
        expected_relative = Path("runtime") / name
        if relative != expected_relative:
            raise TxError(f"candidate manifest机器文件路径无效：{name}")
        raw = _read_candidate_bytes(candidate, relative, f"candidate机器文件{relative}")
        if sha256_bytes(raw) != str(record.get("sha256", "")):
            raise CASMismatch(f"candidate机器文件与已签manifest摘要不一致：{relative}")
        monitored[relative] = raw
        if relative in COMMITTABLE_RUNTIME_RELS:
            payload[relative] = raw
    return payload, monitored
BOUND_INTAKE_FIELDS = set(intake_preflight.PERSISTED_GATE_STABLE_FIELDS) | {
    "evaluated_at",
    "expires_at",
}


def _validated_candidate_workspace(
    args: argparse.Namespace,
    workspace: Path,
    existing: dict[str, object],
) -> CandidateSnapshot | None:
    if not args.candidate_workspace:
        return None
    supplied = Path(args.candidate_workspace).expanduser()
    if supplied.is_symlink():
        raise TxError("--candidate-workspace不得为符号链接。")
    candidate = supplied.resolve()
    if candidate == workspace or not candidate.is_dir():
        raise TxError("--candidate-workspace必须是与正式区分离的普通目录。")
    marker_bytes = _read_candidate_bytes(candidate, CANDIDATE_RECEIPT_REL, "candidate receipt")
    manifest_bytes = _read_candidate_bytes(candidate, MANIFEST_REL, "candidate manifest")
    marker = _json_bytes(marker_bytes, "candidate receipt")
    candidate_manifest = _json_bytes(manifest_bytes, "candidate manifest")
    if not isinstance(marker, dict) or set(marker) != CANDIDATE_RECEIPT_FIELDS:
        raise TxError("candidate receipt字段不完整或含未知字段。")
    if marker.get("schema") != "discovery-call-candidate-receipt/v2":
        raise TxError("candidate receipt schema无效。")
    if Path(str(marker.get("source_workspace", ""))).resolve() != workspace:
        raise TxError("candidate receipt未绑定当前正式workspace。")
    if Path(str(marker.get("candidate_workspace", ""))).resolve() != candidate:
        raise TxError("candidate receipt未绑定当前候选路径。")
    if marker.get("source_manifest_revision") != args.expected_manifest_revision:
        raise CASMismatch("candidate receipt的source manifest revision已过期。")
    if marker.get("source_manifest_sha256") != args.expected_manifest_sha256:
        raise CASMismatch("candidate receipt的source manifest SHA-256已过期。")
    if marker.get("context_id") != existing.get("context_id"):
        raise TxError("candidate receipt context_id与正式workspace不一致。")
    input_payload_digest = str(marker.get("input_payload_sha256", ""))
    final_manifest_digest = str(marker.get("final_manifest_sha256", ""))
    for field, digest in (
        ("input_payload_sha256", input_payload_digest),
        ("final_manifest_sha256", final_manifest_digest),
    ):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise TxError(f"candidate receipt {field}无效。")
    if sha256_bytes(manifest_bytes) != final_manifest_digest:
        raise TxError("candidate receipt未绑定当前candidate manifest。")
    if not isinstance(candidate_manifest, dict):
        raise TxError("candidate manifest必须为JSON对象。")
    if candidate_manifest.get("context_id") != marker.get("context_id"):
        raise TxError("candidate manifest context_id与收据不一致。")
    if candidate_manifest.get("latest_run_id") != marker.get("run_id"):
        raise TxError("candidate manifest run_id与收据不一致。")
    if candidate_manifest.get("transaction_sequence") != args.expected_manifest_revision + 1:
        raise TxError("candidate manifest事务序号未绑定source revision。")
    candidate_intake = candidate_manifest.get("intake_preflight")
    established_intake = existing.get("intake_preflight")
    if (
        not isinstance(candidate_intake, dict)
        or not isinstance(established_intake, dict)
        or not BOUND_INTAKE_FIELDS <= set(candidate_intake)
        or not BOUND_INTAKE_FIELDS <= set(established_intake)
    ):
        raise TxError("candidate或正式manifest缺少宿主签名请求绑定的intake门禁。")
    candidate_attestation_file = getattr(args, "candidate_attestation_file", None)
    if not candidate_attestation_file:
        raise TxError("候选提交必须提供--candidate-attestation-file；本地candidate receipt不构成授权。")
    attestation_path = Path(candidate_attestation_file).expanduser()
    attestation_expected = {
        "context_id": marker.get("context_id"),
        "run_id": marker.get("run_id"),
        "source_manifest_revision": marker.get("source_manifest_revision"),
        "source_manifest_sha256": marker.get("source_manifest_sha256"),
        "source_workspace": marker.get("source_workspace"),
        "candidate_workspace": marker.get("candidate_workspace"),
        "input_payload_sha256": input_payload_digest,
        "final_manifest_sha256": final_manifest_digest,
        "intake_gate_sha256": canonical_intake_gate_sha256(candidate_intake),
        "formal_workspace": str(workspace),
        "customer_id": str(existing.get("customer_id", "")),
    }
    try:
        attestation = verify_candidate_attestation(
            attestation_path,
            expected=attestation_expected,
        )
    except CandidateAttestationError as exc:
        raise TxError(f"candidate_attestation_invalid：{exc}") from exc
    payload_by_relative, monitored = _snapshot_manifest_payload(candidate, candidate_manifest)
    for field in intake_preflight.PERSISTED_GATE_STABLE_FIELDS:
        if candidate_intake.get(field) != established_intake.get(field):
            raise TxError(f"candidate intake_preflight.{field}与正式manifest不一致。")
    try:
        expiry = datetime.fromisoformat(str(candidate_intake["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TxError("candidate intake_preflight.expires_at无效。") from exc
    if expiry.tzinfo is None or expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise TxError("candidate intake_preflight已过期；禁止提交。")
    monitored[CANDIDATE_RECEIPT_REL] = marker_bytes
    monitored[MANIFEST_REL] = manifest_bytes
    return CandidateSnapshot(
        workspace=candidate,
        marker=marker,
        manifest=candidate_manifest,
        manifest_bytes=manifest_bytes,
        payload_by_relative=payload_by_relative,
        monitored_bytes=monitored,
        attestation_path=attestation_path,
        attestation_expected=attestation_expected,
        attestation=attestation,
    )


def _candidate_map(snapshot: CandidateSnapshot, workspace: Path) -> dict[Path, bytes]:
    planned = {
        workspace / relative: raw
        for relative, raw in snapshot.payload_by_relative.items()
        if len(relative.parts) == 1 or relative in COMMITTABLE_RUNTIME_RELS
    }
    included_runtime = {
        path.relative_to(workspace)
        for path in planned
        if path.relative_to(workspace) in COMMITTABLE_RUNTIME_RELS
    }
    if included_runtime != COMMITTABLE_RUNTIME_RELS:
        missing = sorted((COMMITTABLE_RUNTIME_RELS - included_runtime), key=lambda item: item.as_posix())
        raise TxError("机器运行文件必须四件套同事务提交，缺少：" + ", ".join(item.as_posix() for item in missing))
    if not planned:
        raise TxError("候选中没有可提交文件。")
    return planned


def _assert_candidate_snapshot_unchanged(snapshot: CandidateSnapshot) -> None:
    """Detect a non-cooperating writer; committed data still comes from snapshot."""

    for relative, expected in snapshot.monitored_bytes.items():
        current = _read_candidate_bytes(snapshot.workspace, relative, f"candidate稳定性复检{relative}")
        if current != expected:
            raise CASMismatch(f"candidate在封印读取后发生变化：{relative}")


def _fresh_candidate_attestation(
    snapshot: CandidateSnapshot,
    *,
    at: datetime,
) -> VerifiedCandidateAttestation:
    """Re-read and re-verify the host authorization immediately before WAL."""

    try:
        verified = verify_candidate_attestation(
            snapshot.attestation_path,
            expected=snapshot.attestation_expected,
            at=at,
        )
    except CandidateAttestationError as exc:
        raise TxError(f"candidate_attestation_invalid：WAL前复验失败：{exc}") from exc
    if (
        verified.attestation_id != snapshot.attestation.attestation_id
        or verified.attestation_sha256 != snapshot.attestation.attestation_sha256
    ):
        raise CASMismatch("candidate attestation在preview期间发生替换；必须重新开始提交。")
    return verified


def _candidate_postflight(workspace: Path) -> None:
    """Validate a committed research candidate, not a final approved release."""
    validator = Path(__file__).with_name("validate_outputs.py")
    completed = subprocess.run(
        [sys.executable, str(validator), str(workspace), "--profile", "candidate", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        try:
            payload = json.loads(completed.stdout)
            codes = sorted({issue.get("code", "unknown") for issue in payload.get("issues", [])})
            detail = ", ".join(codes) or completed.stderr.strip()
        except json.JSONDecodeError:
            detail = completed.stderr.strip() or completed.stdout.strip()
        raise TxError("candidate候选校验失败：" + detail)
    manifest = load_manifest(workspace)
    if manifest is None:
        raise TxError("candidate提交后缺少runtime/manifest.json。")
    verify_manifest_artifacts(workspace, manifest)


def _attested_candidate_postflight(
    workspace: Path,
    snapshot: CandidateSnapshot,
) -> None:
    """Keep the transaction uncommitted if the host seal expires mid-WAL."""

    _assert_candidate_snapshot_unchanged(snapshot)
    _fresh_candidate_attestation(snapshot, at=datetime.now(timezone.utc))
    _candidate_postflight(workspace)
    # The validator may be materially slower than a hash check. Re-check after
    # it returns so an authorization expiring during postflight cannot be
    # committed by the tiny pre-validation freshness observation alone.
    _fresh_candidate_attestation(snapshot, at=datetime.now(timezone.utc))


def _preview(workspace: Path, planned: dict[Path, bytes], deletes: list[Path], strict: bool) -> None:
    container = Path(tempfile.mkdtemp(prefix=".discovery-call-preview-", dir=workspace.parent))
    preview = container / workspace.name
    preview.mkdir()
    try:
        for source in workspace.glob("*.md"):
            if source.is_file() and not source.is_symlink():
                shutil.copy2(source, preview / source.name)
        runtime_source = workspace / "runtime"
        if runtime_source.is_dir() and not runtime_source.is_symlink():
            (preview / "runtime").mkdir()
            for source in runtime_source.glob("*.json"):
                if source.is_file() and not source.is_symlink():
                    shutil.copy2(source, preview / "runtime" / source.name)
        for target in deletes:
            relative = Path(relative_target(workspace, target))
            (preview / relative).unlink(missing_ok=True)
        for target, raw in planned.items():
            relative = Path(relative_target(workspace, target))
            if len(relative.parts) == 1 or relative.parent == Path("runtime"):
                destination = preview / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
        _candidate_postflight(preview)
    finally:
        shutil.rmtree(container, ignore_errors=True)


def _total_path(workspace: Path) -> Path:
    candidates = list(workspace.glob(f"*{SUFFIXES['comprehensive_report']}"))
    if len(candidates) != 1:
        raise TxError("工作区必须恰有一个综合报告。")
    return candidates[0]


def _expiry(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TxError("connector_audit.authorization_expires_at必须是带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None or parsed <= datetime.now(timezone.utc):
        raise TxError("connector_audit授权缺少时区或已经过期。")
    return parsed.isoformat().replace("+00:00", "Z")


def _planned_runtime_json(
    workspace: Path,
    planned: dict[Path, bytes],
    relative: Path,
    label: str,
) -> dict[str, object]:
    path = workspace / relative
    if path in planned:
        raw = planned[path]
    elif path.is_file() and not path.is_symlink():
        raw = path.read_bytes()
    else:
        raise TxError(f"internal提交缺少{label}。")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TxError(f"{label}不是有效UTF-8 JSON。") from exc
    if not isinstance(value, dict):
        raise TxError(f"{label}顶层必须是JSON对象。")
    return value


def _planned_sensitive_evidence(workspace: Path, planned: dict[Path, bytes]) -> bool:
    evidence = _planned_runtime_json(
        workspace,
        planned,
        EVIDENCE_MANIFEST_REL,
        "runtime/evidence-manifest.json",
    )
    sources = evidence.get("sources")
    claims = evidence.get("claims")
    if not isinstance(sources, dict) or not isinstance(claims, dict):
        raise TxError("evidence-manifest.json的sources/claims无效。")
    return bool(
        any(str(source_id).startswith("SRC-N-") for source_id in sources)
        or any(str(claim_id).startswith("CLM-N-") for claim_id in claims)
        or any(
            isinstance(record, dict)
            and (
                record.get("source_level") == "internal"
                or record.get("permission") in {"internal-authorized", "restricted"}
            )
            for record in sources.values()
        )
    )


def _connector_authorization(
    workspace: Path,
    planned: dict[Path, bytes],
    authorization: dict[str, object],
    established_authorization: dict[str, object],
    customer_id: str,
    expected_run_id: str,
    capability_receipt_file: str | None,
    *,
    sensitive_evidence: bool,
) -> dict[str, object]:
    internal_metadata: dict[str, str] = {}
    candidates = {source for source in workspace.glob("*.md")} | {
        target for target in planned if target.parent == workspace and target.suffix.casefold() == ".md"
    }
    for source in candidates:
        raw = planned[source] if source in planned else source.read_bytes()
        metadata = parse_frontmatter(raw.decode("utf-8"))
        if metadata.get("artifact_type") == "internal_retrieval":
            internal_metadata = metadata
            break
    connector_status = internal_metadata.get("connector_status")
    receipt_required = sensitive_evidence or connector_status in {"connected", "no_hits"}
    if not receipt_required:
        return authorization
    if not internal_metadata:
        raise TxError("本轮选择internal但候选中缺少内部检索成果。")
    if connector_status not in {
        "not_applicable", "not_configured", "connected", "no_hits", "permission_denied", "failed"
    }:
        raise TxError("本轮internal成果的connector_status无效。")

    plan = _planned_runtime_json(workspace, planned, SEARCH_PLAN_REL, "runtime/search-plan.json")
    if str(plan.get("run_id", "")) != expected_run_id:
        raise TxError("研究计划run_id与本次候选run不一致。")
    selected_modules = plan.get("selected_modules")
    if not isinstance(selected_modules, list) or "internal" not in selected_modules:
        raise TxError("internal候选提交必须由本run研究计划显式选择internal。")
    plan_authorization = plan.get("authorization_context")
    if not isinstance(plan_authorization, dict):
        raise TxError("研究计划缺少authorization_context。")

    stable_scalar_fields = (
        "tenant_id", "customer_id", "project_id", "connector_id",
        "authorization_owner", "authorization_expires_at", "authorization_purpose",
    )
    stable_list_fields = (
        "allowed_project_ids", "authorized_roots", "allowed_dataset_aliases",
        "allowed_confidentiality",
    )
    for key in stable_scalar_fields:
        established = established_authorization.get(key)
        if not isinstance(established, str) or not established.strip():
            raise TxError(f"internal提交前必须由init/resume建立授权字段{key}。")
        if plan_authorization.get(key) != established or authorization.get(key) != established:
            raise TxError(f"研究计划或候选成果试图改变既有授权字段{key}。")
    for key in stable_list_fields:
        established = established_authorization.get(key)
        planned_values = plan_authorization.get(key)
        if (
            not isinstance(established, list)
            or not established
            or not all(isinstance(value, str) and value.strip() for value in established)
            or not isinstance(planned_values, list)
            or not all(isinstance(value, str) and value.strip() for value in planned_values)
            or sorted(planned_values) != sorted(established)
        ):
            raise TxError(f"研究计划授权范围{key}缺失或与init/resume不一致。")
    if established_authorization.get("customer_id") != customer_id:
        raise TxError("既有授权customer_id与工作区不一致。")
    projects = established_authorization.get("allowed_project_ids")
    if not isinstance(projects, list) or established_authorization.get("project_id") not in projects:
        raise TxError("既有授权allowed_project_ids必须包含project_id。")
    _expiry(str(established_authorization["authorization_expires_at"]))

    receipt_id = plan_authorization.get("capability_receipt_id")
    actor_id = plan_authorization.get("authorization_actor_id")
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise TxError("研究计划缺少本run capability_receipt_id。")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise TxError("研究计划缺少本run authorization_actor_id。")
    if plan_authorization.get("capability_operation") != "internal_read":
        raise TxError("研究计划capability_operation必须为internal_read。")
    if plan_authorization.get("capability_receipt_verified") is not True:
        raise TxError("研究计划未记录宿主签名能力收据验证。")
    if plan_authorization.get("capability_receipt_run_id") != expected_run_id:
        raise TxError("研究计划capability_receipt_run_id未绑定本次候选run。")
    if not capability_receipt_file:
        raise TxError("提交任何internal候选必须提供--capability-receipt-file进行当前时点复验。")
    try:
        verified_receipt = verify_capability_receipt(
            capability_receipt_file,
            expected={
                "receipt_id": receipt_id,
                "actor_id": actor_id,
                "run_id": expected_run_id,
                "connector_id": established_authorization.get("connector_id"),
                "operation": "internal_read",
                "tenant_id": established_authorization.get("tenant_id"),
                "customer_id": established_authorization.get("customer_id"),
                "project_id": established_authorization.get("project_id"),
                "allowed_project_ids": projects,
                "authorization_owner": established_authorization.get("authorization_owner"),
                "authorization_expires_at": established_authorization.get("authorization_expires_at"),
                "authorized_roots": established_authorization.get("authorized_roots", []),
                "allowed_dataset_aliases": established_authorization.get("allowed_dataset_aliases", []),
                "allowed_confidentiality": established_authorization.get("allowed_confidentiality", []),
                "authorization_purpose": established_authorization.get("authorization_purpose"),
            },
        )
    except CapabilityReceiptError as exc:
        raise TxError(f"capability_receipt_invalid：{exc}") from exc
    immutable_receipt_audit = verified_receipt.audit_fields()
    immutable_receipt_audit.pop("capability_receipt_verified_at", None)
    for key, value in immutable_receipt_audit.items():
        if plan_authorization.get(key) != value:
            raise TxError(f"研究计划authorization_context.{key}与本run宿主签名收据不一致。")

    evidence_path = workspace / EVIDENCE_MANIFEST_REL
    evidence = _planned_runtime_json(workspace, planned, EVIDENCE_MANIFEST_REL, "runtime/evidence-manifest.json")
    raw_evidence = planned.get(evidence_path)
    if raw_evidence is None:
        raw_evidence = evidence_path.read_bytes()
    audit = evidence.get("connector_audit")
    if not isinstance(audit, dict) or audit.get("status") != connector_status:
        raise TxError("evidence-manifest.json的connector_audit.status与内部成果不一致。")
    if str(evidence.get("run_id", "")) != expected_run_id:
        raise TxError("连接器证据清单run_id与本次候选run不一致。")
    if (
        evidence.get("customer_id") != established_authorization.get("customer_id")
        or evidence.get("project_id") != established_authorization.get("project_id")
    ):
        raise TxError("连接器证据清单customer_id/project_id与init/resume授权范围不一致。")
    for key in stable_scalar_fields:
        if audit.get(key) != established_authorization.get(key):
            raise TxError(f"connector_audit.{key}与init/resume授权范围不一致。")
    for key in stable_list_fields:
        audited_values = audit.get(key)
        if (
            not isinstance(audited_values, list)
            or not all(isinstance(value, str) and value.strip() for value in audited_values)
            or sorted(audited_values) != sorted(established_authorization[key])
        ):
            raise TxError(f"connector_audit.{key}与init/resume授权范围不一致。")
    if audit.get("capability_receipt_id") != receipt_id:
        raise TxError("connector_audit.capability_receipt_id与本run研究计划不一致。")
    if audit.get("capability_receipt_verified") is not True:
        raise TxError("connector_audit必须记录宿主能力收据已验证。")
    if audit.get("capability_receipt_run_id") != expected_run_id:
        raise TxError("connector_audit.capability_receipt_run_id未绑定本次候选run。")
    if audit.get("capability_receipt_verified_at") != plan_authorization.get("capability_receipt_verified_at"):
        raise TxError("connector_audit.capability_receipt_verified_at与研究计划验证谱系不一致。")
    for key, value in immutable_receipt_audit.items():
        if audit.get(key) != value:
            raise TxError(f"connector_audit.{key}与本run宿主签名收据不一致。")

    authorization["capability_receipt_id"] = receipt_id
    authorization.update(verified_receipt.audit_fields())
    authorization["connector_status"] = connector_status
    if connector_status not in {"connected", "no_hits"}:
        return authorization

    required = (
        "tenant_id", "customer_id", "project_id", "connector_id", "call_id", "called_at",
        "authorization_owner", "authorization_expires_at", "authorization_purpose",
        "capability_receipt_id", "authorization_actor_id", "capability_operation",
        "capability_receipt_run_id",
        "capability_receipt_issuer", "capability_receipt_key_id",
        "capability_receipt_sha256", "capability_receipt_verified_at",
        "capability_receipt_expires_at", "response_fingerprint",
    )
    missing = [key for key in required if not isinstance(audit.get(key), str) or not str(audit[key]).strip()]
    if missing:
        raise TxError("connector_audit缺少稳定授权字段：" + ", ".join(missing))
    if audit.get("server_filter_verified") is not True or audit.get("response_scope_verified") is not True:
        raise TxError("connector_audit必须确认服务端过滤与响应范围校验。")
    for key in ("authorized_roots", "allowed_dataset_aliases", "allowed_confidentiality"):
        values = audit.get(key)
        if not isinstance(values, list) or not values or not all(isinstance(value, str) and value.strip() for value in values):
            raise TxError(f"connector_audit.{key}必须是非空授权范围数组。")
    if not isinstance(audit.get("isolated_record_count"), int) or int(audit["isolated_record_count"]) < 0:
        raise TxError("connector_audit.isolated_record_count无效。")
    try:
        called_at = datetime.fromisoformat(str(audit["called_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TxError("connector_audit.called_at不是带时区ISO 8601时间。") from exc
    if called_at.tzinfo is None or called_at > datetime.now(timezone.utc):
        raise TxError("connector_audit.called_at缺少时区或位于未来。")
    fingerprint = str(audit["response_fingerprint"])
    if not (fingerprint.startswith("sha256:") and len(fingerprint[7:]) == 64 and all(c in "0123456789abcdef" for c in fingerprint[7:])):
        raise TxError("connector_audit.response_fingerprint必须绑定响应内容SHA-256。")
    audit_projects = audit.get("allowed_project_ids")
    if not isinstance(audit_projects, list) or audit["project_id"] not in audit_projects:
        raise TxError("connector_audit.allowed_project_ids必须包含project_id。")
    if not set(str(value) for value in audit_projects) <= set(str(value) for value in projects):
        raise TxError("connector_audit.allowed_project_ids越出既有授权白名单。")
    expiry = _expiry(str(audit["authorization_expires_at"]))
    authorization.update({key: audit[key] for key in required})
    for key in ("authorized_roots", "allowed_dataset_aliases", "allowed_confidentiality"):
        authorization[key] = list(audit[key])
    authorization["authorization_expires_at"] = expiry
    authorization["allowed_project_ids"] = list(projects)
    authorization["capability_receipt_id"] = str(audit["capability_receipt_id"])
    authorization.update(verified_receipt.audit_fields())
    authorization["connector_status"] = connector_status
    authorization["connector_evidence_sha256"] = sha256_bytes(raw_evidence)
    return authorization


def commit(args: argparse.Namespace) -> dict[str, object]:
    # The legacy file-map path has no candidate receipt or intake lineage.  It
    # must be rejected before locks and WAL recovery: otherwise --recover could
    # mutate the formal workspace even though the requested commit is invalid.
    if args.file_map:
        raise TxError("普通--file-map提交已禁用；请使用build_candidate生成并绑定--candidate-workspace。")
    if getattr(args, "delete", None):
        raise TxError("commit_run删除接口已禁用；候选提交不得删除正式区文件。")
    supplied_workspace = Path(args.workspace).expanduser()
    workspace = supplied_workspace.resolve()
    if Path(os.path.abspath(supplied_workspace)) != workspace or not workspace.is_dir():
        raise TxError("工作区不存在或为符号链接。")
    if args.candidate_workspace:
        if not args.intake_input:
            raise TxError("候选提交必须提供--intake-input并在任何锁或恢复写入前复验当前宿主请求。")
        preliminary_manifest = load_manifest(workspace, required=True)
        preliminary_gate = preliminary_manifest.get("intake_preflight")
        try:
            verified_intake = intake_preflight.verify_persisted_gate(
                args.intake_input,
                preliminary_gate if isinstance(preliminary_gate, dict) else {},
                expected_business_mode=str(preliminary_manifest.get("business_mode", "")),
                expected_customer_name=str(preliminary_manifest.get("customer_display_name", "")),
                expected_organization_scope=str(preliminary_manifest.get("organization_scope", "")),
            )
        except intake_preflight.PreflightError as exc:
            raise TxError(f"当前请求intake复验失败：{exc}") from exc
    with output_root_lock(workspace.parent, timeout=args.lock_timeout):
        with workspace_lock(workspace, timeout=args.lock_timeout):
            if unfinished_transaction(workspace):
                if not args.recover:
                    raise RecoveryRequired("检测到未完成事务；请加--recover或先运行recover_workspace.py。")
                # A candidate WAL may be recovered long after its short host
                # authorization expired. This entry point has not yet rebuilt
                # a trusted CandidateSnapshot, so it must never front-run the
                # checks below with a roll-forward. Roll back first; a fresh
                # commit requires a fresh, unconsumed host authorization.
                recover_transaction(workspace, strategy="rollback", postflight=None)
            existing = assert_manifest_cas(
                workspace, args.expected_manifest_revision, args.expected_manifest_sha256
            )
            verify_manifest_artifacts(workspace, existing)
            candidate_snapshot = _validated_candidate_workspace(args, workspace, existing)
            if candidate_snapshot is None:
                raise TxError("候选提交缺少受宿主证明的candidate snapshot。")
            try:
                candidate_documents = candidate_builder._load_documents(
                    candidate_snapshot.workspace
                )
                candidate_builder._assert_intake_semantic_binding(
                    verified_intake=verified_intake,
                    business_mode=str(existing.get("business_mode", "")),
                    records={},
                    live_documents=candidate_documents,
                )
            except candidate_builder.CandidateError as exc:
                raise TxError(f"candidate_intake_semantic_drift：{exc}") from exc
            planned = _candidate_map(candidate_snapshot, workspace)
            deletes: list[Path] = []
            if args.strict:
                missing_runtime = [
                    relative.as_posix()
                    for relative in COMMITTABLE_RUNTIME_RELS
                    if (workspace / relative) not in planned
                ]
                if missing_runtime:
                    raise TxError("严格提交要求四个机器运行文件，缺少：" + ", ".join(sorted(missing_runtime)))
            total_path = _total_path(workspace)
            total_state = file_state(total_path)
            expected_total = (
                args.expected_content_version,
                args.expected_latest_run_id,
                args.expected_total_sha256,
            )
            if any(expected_total) and not all(expected_total):
                raise TxError("total CAS参数必须同时提供version、run_id、sha256。")
            if all(expected_total) and (
                total_state.content_version != args.expected_content_version
                or total_state.latest_run_id != args.expected_latest_run_id
                or total_state.sha256 != args.expected_total_sha256
            ):
                raise CASMismatch("综合报告content_version/latest_run_id/hash CAS冲突。")
            candidate_total = planned.get(total_path, total_path.read_bytes())
            total_metadata = parse_frontmatter(candidate_total.decode("utf-8"))
            raw_authorization = existing.get("authorization", {})
            if not isinstance(raw_authorization, dict):
                raise TxError("运行清单authorization无效。")
            established_authorization = dict(raw_authorization)
            authorization = dict(established_authorization)
            # Candidate content may consume an authorization established by
            # init/resume, but it must not grant or extend its own access while
            # being committed.  Authorization changes belong to the explicit
            # initialization/resume path so they are recorded before a
            # connector result is accepted.
            for key in (
                "tenant_id",
                "project_id",
                "authorization_owner",
                "authorization_expires_at",
            ):
                candidate_value = total_metadata.get(key, "")
                existing_value = str(authorization.get(key, ""))
                if candidate_value and existing_value and candidate_value != existing_value:
                    raise CASMismatch(f"候选综合报告试图改变既有授权字段{key}；请先显式续建授权上下文。")
            for key in ("tenant_id", "project_id", "authorization_owner", "authorization_expires_at"):
                if total_metadata.get(key):
                    authorization[key] = total_metadata[key]
            authorization["customer_id"] = str(existing.get("customer_id", ""))
            selected = selected_callable_modules(candidate_total.decode("utf-8"))
            sensitive_evidence = _planned_sensitive_evidence(workspace, planned)
            authorization = _connector_authorization(
                workspace,
                planned,
                authorization,
                established_authorization,
                str(existing.get("customer_id", "")),
                str(total_metadata.get("latest_run_id", "")),
                args.capability_receipt_file,
                sensitive_evidence=sensitive_evidence or "internal" in selected,
            )
            overlay = dict(planned)
            candidate_intake = None
            raw_candidate_intake = candidate_snapshot.manifest.get("intake_preflight")
            if isinstance(raw_candidate_intake, dict):
                candidate_intake = dict(raw_candidate_intake)
            manifest = build_manifest(
                workspace,
                identity={
                    "context_id": str(existing.get("context_id", "")),
                    "customer_id": str(existing.get("customer_id", "")),
                    "customer_display_name": str(existing.get("customer_display_name", "")),
                    "organization_scope": str(existing.get("organization_scope", "")),
                },
                business_mode=total_metadata.get("business_mode", str(existing.get("business_mode", ""))),
                route=total_metadata.get("route", str(existing.get("route", ""))),
                depth=total_metadata.get("depth", str(existing.get("depth", ""))),
                task_timezone=(
                    str(existing["task_timezone"])
                    if existing.get("task_timezone") is not None
                    else None
                ),
                latest_run_id=total_metadata.get("latest_run_id", str(existing.get("latest_run_id", ""))),
                content_version=total_metadata.get("content_version", str(existing.get("content_version", ""))),
                stage=total_metadata.get("workflow_stage", str(existing.get("stage", ""))),
                ready_for_use=total_metadata.get("ready_for_use", "false").casefold() == "true",
                selected_modules=selected,
                authorization=authorization,
                transaction_sequence=int(existing["transaction_sequence"]) + 1,
                intake_preflight=candidate_intake,
                candidate_attestation=None,
                delivery_summary=(
                    dict(candidate_snapshot.manifest["delivery_summary"])
                    if isinstance(candidate_snapshot.manifest.get("delivery_summary"), dict)
                    else None
                ),
                overlay=overlay,
                deletes=deletes,
            )
            # The preview proves candidate content, not the authorization
            # timing of a WAL that has not started yet.  Do not carry an old
            # audit forward or synthesize a misleading WAL timestamp here;
            # the fresh host verification below installs this run's audit.
            manifest.pop("candidate_attestation", None)
            planned[workspace / MANIFEST_REL] = (
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            _assert_candidate_snapshot_unchanged(candidate_snapshot)
            _preview(workspace, planned, deletes, args.strict)
            _assert_candidate_snapshot_unchanged(candidate_snapshot)
            fresh_attestation = _fresh_candidate_attestation(
                candidate_snapshot,
                at=datetime.now(timezone.utc),
            )
            try:
                claim_candidate_attestation_nonce(
                    fresh_attestation,
                    workspace=workspace,
                )
            except CandidateAttestationError as exc:
                raise TxError(f"candidate_attestation_invalid：{exc}") from exc
            manifest["candidate_attestation"] = fresh_attestation.audit_summary(
                candidate_snapshot.attestation_expected,
            )
            planned[workspace / MANIFEST_REL] = (
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            expected = {path: file_state(path).as_dict() for path in list(planned) + deletes}
            tx_id = transactional_commit(
                workspace,
                planned,
                deletes=deletes,
                expected=expected,
                operation=args.operation,
                postflight=lambda committed_workspace: _attested_candidate_postflight(
                    committed_workspace,
                    candidate_snapshot,
                ),
            )
            revision, digest = manifest_state(workspace)
            committed_manifest = load_manifest(workspace)
            assert committed_manifest is not None
            return {
                "workspace": str(workspace),
                "transaction_id": tx_id,
                "manifest_revision": revision,
                "manifest_sha256": digest,
                "candidate_attestation_id": fresh_attestation.attestation_id,
                "candidate_attestation_sha256": fresh_attestation.attestation_sha256,
                "committed": [str(path.relative_to(workspace)) for path in planned],
                "deleted": [str(path.relative_to(workspace)) for path in deletes],
                "delivery_summary": committed_manifest.get("delivery_summary"),
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在运行锁、CAS和WAL保护下提交候选成果。")
    parser.add_argument("workspace")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate-workspace")
    source.add_argument("--file-map", help=argparse.SUPPRESS)
    parser.add_argument("--expected-manifest-revision", type=int, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-content-version")
    parser.add_argument("--expected-latest-run-id")
    parser.add_argument("--expected-total-sha256")
    parser.add_argument(
        "--intake-input",
        help="候选提交必填；在锁、恢复和事务写入前重新验签当前宿主请求绑定的intake v3普通文件（不接受-或stdin）",
    )
    parser.add_argument("--operation", default="commit_run")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--capability-receipt-file",
        help="任何本轮敏感证据候选提交时用于当前时点二次验证的宿主签名能力收据",
    )
    parser.add_argument(
        "--candidate-attestation-file",
        help="认证宿主对最终candidate manifest签发的短期Ed25519 attestation；候选提交必填",
    )
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--recovery-strategy", choices=("auto", "rollback", "roll-forward"), default="auto")
    parser.add_argument("--lock-timeout", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = commit(args)
    except (TxError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"已提交事务：{result['transaction_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
