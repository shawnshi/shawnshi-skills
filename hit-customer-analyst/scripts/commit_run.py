#!/usr/bin/env python3
"""Validate and atomically commit a prepared discovery-call candidate run."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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
    "payload_sha256",
}


def _validated_candidate_workspace(
    args: argparse.Namespace,
    workspace: Path,
    existing: dict[str, object],
) -> Path | None:
    if not args.candidate_workspace:
        return None
    supplied = Path(args.candidate_workspace).expanduser()
    if supplied.is_symlink():
        raise TxError("--candidate-workspace不得为符号链接。")
    candidate = supplied.resolve()
    if candidate == workspace or not candidate.is_dir():
        raise TxError("--candidate-workspace必须是与正式区分离的普通目录。")
    marker_path = candidate / CANDIDATE_RECEIPT_REL
    candidate_manifest_path = candidate / MANIFEST_REL
    for path, label in ((marker_path, "candidate receipt"), (candidate_manifest_path, "candidate manifest")):
        if path.is_symlink() or not path.is_file():
            raise TxError(f"{label}缺失或不是普通文件。")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TxError(f"candidate收据或manifest无法读取：{exc}") from exc
    if not isinstance(marker, dict) or set(marker) != CANDIDATE_RECEIPT_FIELDS:
        raise TxError("candidate receipt字段不完整或含未知字段。")
    if marker.get("schema") != "discovery-call-candidate-receipt/v1":
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
    payload_digest = str(marker.get("payload_sha256", ""))
    if len(payload_digest) != 64 or any(char not in "0123456789abcdef" for char in payload_digest):
        raise TxError("candidate receipt payload_sha256无效。")
    if sha256_file(candidate_manifest_path) != payload_digest:
        raise TxError("candidate receipt未绑定当前candidate manifest。")
    if not isinstance(candidate_manifest, dict):
        raise TxError("candidate manifest必须为JSON对象。")
    if candidate_manifest.get("context_id") != marker.get("context_id"):
        raise TxError("candidate manifest context_id与收据不一致。")
    if candidate_manifest.get("latest_run_id") != marker.get("run_id"):
        raise TxError("candidate manifest run_id与收据不一致。")
    if candidate_manifest.get("transaction_sequence") != args.expected_manifest_revision + 1:
        raise TxError("candidate manifest事务序号未绑定source revision。")
    return candidate


def _candidate_map(args: argparse.Namespace, workspace: Path) -> dict[Path, bytes]:
    planned: dict[Path, bytes] = {}
    if args.candidate_workspace:
        candidate_input = Path(args.candidate_workspace).expanduser()
        if candidate_input.is_symlink():
            raise TxError("--candidate-workspace不得为符号链接。")
        candidate = candidate_input.resolve()
        if not candidate.is_dir():
            raise TxError("--candidate-workspace必须是普通目录。")
        for source in candidate.glob("*.md"):
            if source.is_file() and not source.is_symlink():
                planned[workspace / source.name] = source.read_bytes()
        for relative in COMMITTABLE_RUNTIME_RELS:
            source = candidate / relative
            if source.is_file() and not source.is_symlink():
                planned[workspace / relative] = source.read_bytes()
    else:
        # An arbitrary file map cannot prove that Markdown, the four machine
        # evidence files, and the candidate receipt came from one build.  It
        # also allowed callers to inject lifecycle/governance frontmatter.
        # Recovery is handled by the WAL recovery path, not by an unbound map.
        raise TxError("普通--file-map提交已禁用；请使用build_candidate生成并绑定--candidate-workspace。")
    included_runtime = {
        path.relative_to(workspace)
        for path in planned
        if path.relative_to(workspace) in COMMITTABLE_RUNTIME_RELS
    }
    if included_runtime and included_runtime != COMMITTABLE_RUNTIME_RELS:
        missing = sorted((COMMITTABLE_RUNTIME_RELS - included_runtime), key=lambda item: item.as_posix())
        raise TxError("机器运行文件必须四件套同事务提交，缺少：" + ", ".join(item.as_posix() for item in missing))
    if not planned:
        raise TxError("候选中没有可提交文件。")
    return planned


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


def _connector_authorization(
    workspace: Path,
    planned: dict[Path, bytes],
    authorization: dict[str, object],
    established_authorization: dict[str, object],
    customer_id: str,
    expected_run_id: str,
    capability_receipt_file: str | None,
    *,
    internal_selected: bool,
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
    receipt_required = internal_selected or connector_status in {"connected", "no_hits"}
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
    supplied_workspace = Path(args.workspace).expanduser()
    workspace = supplied_workspace.resolve()
    if Path(os.path.abspath(supplied_workspace)) != workspace or not workspace.is_dir():
        raise TxError("工作区不存在或为符号链接。")
    with output_root_lock(workspace.parent, timeout=args.lock_timeout):
        with workspace_lock(workspace, timeout=args.lock_timeout):
            if unfinished_transaction(workspace):
                if not args.recover:
                    raise RecoveryRequired("检测到未完成事务；请加--recover或先运行recover_workspace.py。")
                recover_transaction(workspace, strategy=args.recovery_strategy, postflight=None)
            existing = assert_manifest_cas(
                workspace, args.expected_manifest_revision, args.expected_manifest_sha256
            )
            verify_manifest_artifacts(workspace, existing)
            _validated_candidate_workspace(args, workspace, existing)
            planned = _candidate_map(args, workspace)
            deletes: list[Path] = []
            for value in args.delete or []:
                target = workspace / value
                relative = Path(relative_target(workspace, target))
                if relative == GOVERNANCE_CONTEXT_REL:
                    raise TxError("runtime/governance-context.json是宿主信任根，commit_run不得删除。")
                deletes.append(target)
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
            authorization = _connector_authorization(
                workspace,
                planned,
                authorization,
                established_authorization,
                str(existing.get("customer_id", "")),
                str(total_metadata.get("latest_run_id", "")),
                args.capability_receipt_file,
                internal_selected="internal" in selected,
            )
            overlay = dict(planned)
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
                overlay=overlay,
                deletes=deletes,
            )
            planned[workspace / MANIFEST_REL] = (
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            _preview(workspace, planned, deletes, args.strict)
            expected = {path: file_state(path).as_dict() for path in list(planned) + deletes}
            tx_id = transactional_commit(
                workspace,
                planned,
                deletes=deletes,
                expected=expected,
                operation=args.operation,
                postflight=_candidate_postflight,
            )
            revision, digest = manifest_state(workspace)
            return {
                "workspace": str(workspace),
                "transaction_id": tx_id,
                "manifest_revision": revision,
                "manifest_sha256": digest,
                "committed": [str(path.relative_to(workspace)) for path in planned],
                "deleted": [str(path.relative_to(workspace)) for path in deletes],
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在运行锁、CAS和WAL保护下提交候选成果。")
    parser.add_argument("workspace")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate-workspace")
    source.add_argument("--file-map", help=argparse.SUPPRESS)
    parser.add_argument("--delete", action="append", help="随事务删除的工作区相对普通文件")
    parser.add_argument("--expected-manifest-revision", type=int, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-content-version")
    parser.add_argument("--expected-latest-run-id")
    parser.add_argument("--expected-total-sha256")
    parser.add_argument("--operation", default="commit_run")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--capability-receipt-file",
        help="任何本轮selected internal候选提交时用于当前时点二次验证的宿主签名能力收据",
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
