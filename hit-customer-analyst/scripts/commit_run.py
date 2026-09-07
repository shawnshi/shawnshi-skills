#!/usr/bin/env python3
"""Validate and atomically commit a prepared discovery-call candidate run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from init_workspace import (
    SUFFIXES,
    VALIDATOR_TIMEOUT_SECONDS,
    selected_callable_modules,
    validate_runtime_postflight,
    validate_workspace_postflight,
)
from runtime_tx import (
    EVIDENCE_MANIFEST_REL,
    MANIFEST_REL,
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
    transactional_commit,
    unfinished_transaction,
    verify_manifest_artifacts,
    workspace_lock,
)


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
        for relative in (EVIDENCE_MANIFEST_REL, Path("runtime/search-plan.json"), Path("runtime/run-metrics.json")):
            evidence = candidate / relative
            if evidence.is_symlink():
                raise TxError("审计文件不得为符号链接。")
            if evidence.is_file():
                planned[workspace / relative] = evidence.read_bytes()
    else:
        mapping_path = Path(args.file_map).expanduser().resolve()
        try:
            payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TxError(f"候选文件映射无法读取：{exc}") from exc
        if not isinstance(payload, dict) or not payload:
            raise TxError("候选文件映射必须是非空JSON对象：目标相对路径 -> 候选源文件。")
        for target_name, source_name in payload.items():
            if not isinstance(target_name, str) or not isinstance(source_name, str):
                raise TxError("候选文件映射的键和值必须是字符串。")
            source = Path(source_name).expanduser()
            if not source.is_absolute():
                source = mapping_path.parent / source
            if source.is_symlink():
                raise TxError(f"候选源不得为符号链接：{source}")
            source = source.resolve()
            if not source.is_file():
                raise TxError(f"候选源不是普通文件：{source}")
            target = workspace / target_name
            relative_target(workspace, target)
            planned[target] = source.read_bytes()
    if not planned:
        raise TxError("候选中没有可提交文件。")
    return planned


def _strict_postflight(workspace: Path) -> None:
    validate_runtime_postflight(workspace)
    validator = Path(__file__).with_name("validate_outputs.py")
    try:
        completed = subprocess.run(
            [sys.executable, str(validator), str(workspace), "--strict", "--json"],
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            check=False,
            timeout=VALIDATOR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise TxError(f"严格候选校验器超时（{VALIDATOR_TIMEOUT_SECONDS:g}秒）：{workspace}") from exc
    if completed.returncode:
        try:
            payload = json.loads(completed.stdout)
            codes = sorted({issue.get("code", "unknown") for issue in payload.get("issues", [])})
            detail = ", ".join(codes) or completed.stderr.strip()
        except json.JSONDecodeError:
            detail = completed.stderr.strip() or completed.stdout.strip()
        raise TxError("严格候选校验失败：" + detail)


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
        (_strict_postflight if strict else validate_workspace_postflight)(preview)
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


def _connector_authorization(
    workspace: Path,
    planned: dict[Path, bytes],
    authorization: dict[str, object],
    established_authorization: dict[str, object],
    customer_id: str,
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
    if internal_metadata.get("connector_status") != "connected":
        return authorization
    evidence_path = workspace / EVIDENCE_MANIFEST_REL
    raw_evidence = planned.get(evidence_path, evidence_path.read_bytes() if evidence_path.is_file() else b"")
    if not raw_evidence:
        raise TxError("connector_status=connected必须同时提交runtime/evidence-manifest.json。")
    try:
        evidence = json.loads(raw_evidence.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TxError("连接器证据清单不是有效UTF-8 JSON。") from exc
    audit = evidence.get("connector_audit") if isinstance(evidence, dict) else None
    if not isinstance(audit, dict) or audit.get("status") != "connected":
        raise TxError("evidence-manifest.json缺少status=connected的connector_audit。")
    required = (
        "tenant_id", "customer_id", "project_id", "connector_id", "call_id", "called_at",
        "authorization_owner", "authorization_expires_at", "response_fingerprint",
    )
    missing = [key for key in required if not isinstance(audit.get(key), str) or not str(audit[key]).strip()]
    if missing:
        raise TxError("connector_audit缺少稳定授权字段：" + ", ".join(missing))
    if audit.get("server_filter_verified") is not True or audit.get("response_scope_verified") is not True:
        raise TxError("connector_audit必须确认服务端过滤与响应范围校验。")
    if not isinstance(audit.get("isolated_record_count"), int) or int(audit["isolated_record_count"]) < 0:
        raise TxError("connector_audit.isolated_record_count无效。")
    try:
        called_at = datetime.fromisoformat(str(audit["called_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TxError("connector_audit.called_at不是带时区ISO 8601时间。") from exc
    if called_at.tzinfo is None or called_at > datetime.now(timezone.utc):
        raise TxError("connector_audit.called_at缺少时区或位于未来。")
    fingerprint = str(audit["response_fingerprint"])
    if not (
        (len(fingerprint.removeprefix("sha256:")) == 64 and all(c in "0123456789abcdef" for c in fingerprint.removeprefix("sha256:")))
        or (":" in fingerprint and not any(c.isspace() for c in fingerprint))
    ):
        raise TxError("connector_audit.response_fingerprint格式无效。")
    for key in ("tenant_id", "customer_id", "project_id", "authorization_owner", "authorization_expires_at"):
        established = str(established_authorization.get(key, ""))
        if not established:
            raise TxError(f"connector_status=connected前必须由init/resume建立授权字段{key}。")
        if str(audit[key]) != established or str(authorization.get(key, "")) != established:
            raise TxError(f"connector_audit.{key}或候选成果与既有授权不一致。")
    if str(audit["customer_id"]) != customer_id:
        raise TxError("connector_audit.customer_id与工作区不一致。")
    projects = established_authorization.get("allowed_project_ids")
    if not isinstance(projects, list) or audit["project_id"] not in projects:
        raise TxError("既有授权allowed_project_ids必须包含connector_audit.project_id。")
    audit_projects = audit.get("allowed_project_ids")
    if not isinstance(audit_projects, list) or audit["project_id"] not in audit_projects:
        raise TxError("connector_audit.allowed_project_ids必须包含project_id。")
    if not set(str(value) for value in audit_projects) <= set(str(value) for value in projects):
        raise TxError("connector_audit.allowed_project_ids越出既有授权白名单。")
    expiry = _expiry(str(audit["authorization_expires_at"]))
    authorization.update({key: audit[key] for key in required})
    authorization["authorization_expires_at"] = expiry
    authorization["allowed_project_ids"] = list(projects)
    authorization["connector_status"] = "connected"
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
            planned = _candidate_map(args, workspace)
            deletes: list[Path] = []
            for value in args.delete or []:
                target = workspace / value
                relative_target(workspace, target)
                deletes.append(target)
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
            established_metadata = parse_frontmatter(total_path.read_text(encoding="utf-8"))
            if total_metadata.get("task_timezone") != established_metadata.get("task_timezone"):
                raise CASMismatch("候选综合报告不得新增、清空或更改task_timezone；既有证据日期时区不可重解释。")
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
                if key in total_metadata and candidate_value != existing_value:
                    raise CASMismatch(f"候选综合报告试图建立或改变既有授权字段{key}；请先通过init/resume显式建立授权上下文。")
            authorization["customer_id"] = str(existing.get("customer_id", ""))
            authorization = _connector_authorization(
                workspace,
                planned,
                authorization,
                established_authorization,
                str(existing.get("customer_id", "")),
            )
            for relative in (Path("runtime/search-plan.json"), Path("runtime/run-metrics.json")):
                raw = planned.get(workspace / relative)
                if raw is not None:
                    try:
                        audit = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeError) as exc:
                        raise TxError("审计JSON损坏：" + str(relative)) from exc
                    expected_schema = "discovery-call-search-plan/v1" if relative.name == "search-plan.json" else "discovery-call-run-metrics/v1"
                    if not isinstance(audit, dict) or audit.get("schema") != expected_schema:
                        raise TxError("审计schema不匹配：" + str(relative))
                    for key, expected in (("context_id", existing["context_id"]), ("run_id", total_metadata["latest_run_id"]), ("business_mode", total_metadata["business_mode"])):
                        if audit.get(key) != expected:
                            raise TxError("审计身份不匹配：" + key)
            selected = selected_callable_modules(candidate_total.decode("utf-8"))
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
                postflight=_strict_postflight if args.strict else validate_runtime_postflight,
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
    source.add_argument("--file-map", help="JSON对象：工作区相对目标路径 -> 候选源路径")
    parser.add_argument("--delete", action="append", help="随事务删除的工作区相对普通文件")
    parser.add_argument("--expected-manifest-revision", type=int, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-content-version")
    parser.add_argument("--expected-latest-run-id")
    parser.add_argument("--expected-total-sha256")
    parser.add_argument("--operation", default="commit_run")
    parser.add_argument("--strict", action="store_true")
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
