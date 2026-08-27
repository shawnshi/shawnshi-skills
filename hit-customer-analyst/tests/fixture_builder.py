from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.common import governance, load_json, research_plan as rp, run_python, runtime_tx as tx, write_intake


_GOVERNANCE_SIGNERS: dict[str, Ed25519PrivateKey] = {}
_SOURCE_RECEIPT_ISSUER = "test-source-host"
_SOURCE_RECEIPT_KEY_ID = "test-source-key"
_SOURCE_RECEIPT_PRIVATE_KEY = Ed25519PrivateKey.generate()


def _sign(private_key: Ed25519PrivateKey, payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(private_key.sign(canonical)).decode("ascii")


def _source_capture_receipt(source_id: str, snapshot: dict, total: dict, project_id: str | None) -> dict:
    public_key = _SOURCE_RECEIPT_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    try:
        trust = json.loads(os.environ.get("DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON", "{}"))
    except json.JSONDecodeError:
        trust = {}
    if not isinstance(trust, dict):
        trust = {}
    issuer_keys = trust.setdefault(_SOURCE_RECEIPT_ISSUER, {})
    if not isinstance(issuer_keys, dict):
        issuer_keys = {}
        trust[_SOURCE_RECEIPT_ISSUER] = issuer_keys
    issuer_keys[_SOURCE_RECEIPT_KEY_ID] = base64.b64encode(public_key).decode("ascii")
    os.environ["DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON"] = json.dumps(trust, sort_keys=True)
    issued = datetime.now(timezone.utc).replace(microsecond=0)
    receipt = {
        "schema": "discovery-call-source-capture-receipt/v1",
        "issuer": _SOURCE_RECEIPT_ISSUER,
        "audience": "discovery-call-source-capture",
        "key_id": _SOURCE_RECEIPT_KEY_ID,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "receipt_id": f"srcpt-{source_id.casefold()}",
        "source_id": source_id,
        "locator": snapshot["locator"],
        "final_url": snapshot["final_url"],
        "canonical_locator": snapshot["canonical_locator"],
        "content_sha256": snapshot["content_sha256"],
        "length": snapshot["length"],
        "capture_method": snapshot["capture_method"],
        "retrieved_at": snapshot["retrieved_at"],
        "run_id": total["latest_run_id"],
        "customer_id": total["customer_id"],
        "project_id": project_id,
    }
    receipt["signature"] = _sign(_SOURCE_RECEIPT_PRIVATE_KEY, receipt)
    return receipt


def _artifact_target(workspace: Path, artifact_type: str) -> tuple[dict[str, str], str]:
    for path in workspace.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        data = tx.parse_frontmatter(text)
        if data.get("artifact_type") == artifact_type:
            lines = text.splitlines()
            end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
            return data, "\n".join(lines[end + 1 :])
    raise RuntimeError(f"missing artifact: {artifact_type}")


def _canonical_body(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _body_digest(value: str) -> str:
    return hashlib.sha256(_canonical_body(value).encode("utf-8")).hexdigest()


def _letter_body(body: str) -> str:
    lines = body.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip(" `\t") == "EXTERNAL_BODY_START")
    end = next(i for i, line in enumerate(lines) if line.strip(" `\t") == "EXTERNAL_BODY_END")
    return "\n".join(lines[start + 1 : end])


def _letter_context_digest(data: dict[str, str]) -> str:
    keys = ("letter_scenario", "recipient_role", "letter_purpose", "expected_action", "signer", "delivery_channel")
    canonical = json.dumps({key: data.get(key, "") for key in sorted(keys)}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replace_frontmatter(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    seen: set[str] = set()
    for index in range(1, end):
        key = lines[index].partition(":")[0]
        if key in updates:
            lines[index] = f"{key}: {json.dumps(updates[key], ensure_ascii=False)}"
            seen.add(key)
    for key in updates.keys() - seen:
        lines.insert(end, f"{key}: {json.dumps(updates[key], ensure_ascii=False)}")
        end += 1
    return "\n".join(lines[: end + 1]).rstrip() + "\n"


def _document(original: str, updates: dict[str, str], body: str) -> str:
    return _replace_frontmatter(original, updates) + "\n" + body.strip() + "\n"


def _rebuild_manifest(workspace: Path, selected_modules: list[str]) -> None:
    old = load_json(workspace / tx.MANIFEST_REL)
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
    manifest = tx.build_manifest(
        workspace,
        identity={
            "context_id": total["context_id"],
            "customer_id": total["customer_id"],
            "customer_display_name": total["customer_display_name"],
            "organization_scope": total["organization_scope"],
        },
        business_mode=total["business_mode"],
        route=total["route"],
        depth=total["depth"],
        task_timezone=(
            str(old["task_timezone"])
            if old.get("task_timezone") is not None
            else None
        ),
        latest_run_id=total["latest_run_id"],
        content_version=total["content_version"],
        stage=total["workflow_stage"],
        ready_for_use=total["ready_for_use"] == "true",
        selected_modules=selected_modules,
        authorization=old.get("authorization", {}),
        transaction_sequence=int(old["transaction_sequence"]) + 1,
    )
    tx.atomic_write_json(workspace / tx.MANIFEST_REL, manifest)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _install_machine_bundle(workspace: Path, selected_modules: list[str]) -> None:
    """Install a complete candidate/release machine bundle for lifecycle fixtures."""
    manifest = load_json(workspace / tx.MANIFEST_REL)
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
    mode = total["business_mode"]
    generated_at = datetime.fromisoformat(total["updated_at"].replace("Z", "+00:00"))
    business_fields: dict[str, str] = {
        "customer_name": total["customer_display_name"],
        "organization_scope": total["organization_scope"],
    }
    if mode in {"briefing", "standard_visit"}:
        business_fields.update(
            {
                "target_contact_level": "信息中心主任",
                "visit_objective": "确认年度建设重点",
                "minimum_next_step": "安排专题交流",
            }
        )
    elif mode == "letter":
        business_fields.update(
            {
                "letter_scenario": "拜访后正式跟进",
                "recipient_role": "张主任，信息中心主任，身份已确认",
                "letter_purpose": "确认下一次技术交流安排",
                "expected_action": "确认九月技术交流时间",
                "signer": "王经理，客户负责人",
                "delivery_channel": "正式电子邮件",
            }
        )
    plan = rp.build_search_plan(
        business_mode=mode,
        context_id=total["context_id"],
        run_id=total["latest_run_id"],
        customer_name=total["customer_display_name"],
        customer_id=total["customer_id"],
        organization_scope=total["organization_scope"],
        business_fields=business_fields,
        selected_modules=selected_modules,
        people=["张主任"] if "leader" in selected_modules else [],
        generated_at=generated_at,
        intake_preflight=manifest.get("intake_preflight"),
    )
    runtime = workspace / "runtime"
    runtime.mkdir(exist_ok=True)
    tx.atomic_write_json(runtime / "search-plan.json", plan)

    source_rows: dict[str, list[str]] = {}
    claim_rows: dict[str, list[str]] = {}
    for document in workspace.glob("*.md"):
        for line in document.read_text(encoding="utf-8").splitlines():
            cells = _cells(line) if line.lstrip().startswith("|") else []
            if cells and re.fullmatch(r"SRC-(?:I|L|N)-\d{3,}", cells[0]):
                source_rows[cells[0]] = cells
            if cells and re.fullmatch(r"CLM-(?:I|L|N)-\d{3,}", cells[0]):
                claim_rows[cells[0]] = cells

    ttl_profile = rp.load_config()["profiles"][mode]["ttl_days"]
    authorization = manifest.get("authorization", {}) if isinstance(manifest.get("authorization"), dict) else {}
    cache_entries: dict[str, dict] = {}
    machine_sources: dict[str, dict] = {}
    for source_id, cells in source_rows.items():
        locator = cells[3]
        canonical = rp.canonicalize_source_locator(locator)
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        digest = cells[11].removeprefix("sha256:")
        retrieved_at = f"{cells[5]}T00:00:00Z"
        ttl_class = {"I": "institution", "L": "leader", "N": "internal"}[source_id.split("-")[1]]
        snapshot = {
            "cache_key": cache_key,
            "locator": locator,
            "final_url": locator,
            "canonical_locator": canonical,
            "source_fingerprint": "sha256:" + digest,
            "content_sha256": digest,
            "retrieved_at": retrieved_at,
            "capture_method": "text-nfc-lf-utf8-v1",
            "length": 1,
        }
        snapshot["capture_receipt"] = _source_capture_receipt(
            source_id,
            snapshot,
            total,
            authorization.get("project_id") or None,
        )
        machine_sources[source_id] = {"source_id": source_id, **snapshot}
        retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        cache_entries[cache_key] = {
            **snapshot,
            "expires_at": (retrieved + timedelta(days=ttl_profile[ttl_class])).isoformat().replace("+00:00", "Z"),
            "ttl_class": ttl_class,
            "metadata": {},
        }
    tx.atomic_write_json(
        runtime / "source-cache.json",
        {
            "schema": "discovery-call-source-cache/v1",
            "context_id": total["context_id"],
            "run_id": total["latest_run_id"],
            "business_mode": mode,
            "updated_at": total["updated_at"],
            "entries": cache_entries,
        },
    )

    machine_claims: dict[str, dict] = {}
    for claim_id, cells in claim_rows.items():
        support_ids = sorted(set(re.findall(r"SRC-(?:I|L|N)-\d{3,}", cells[6])))
        ttl_class = {"I": "institution", "L": "leader", "N": "internal"}[claim_id.split("-")[1]]
        anchors = [
            datetime.fromisoformat(machine_sources[source_id]["retrieved_at"].replace("Z", "+00:00"))
            for source_id in support_ids
        ]
        anchor = max(anchors)
        machine_claims[claim_id] = {
            "claim_id": claim_id,
            "information_type": ttl_class,
            "ttl_class": ttl_class,
            "evidence_anchor_at": anchor.isoformat().replace("+00:00", "Z"),
            "date_basis": "retrieved_at",
            "verified_at": total["updated_at"],
            "ttl_days": ttl_profile[ttl_class],
            "expires_at": (anchor + timedelta(days=ttl_profile[ttl_class])).isoformat().replace("+00:00", "Z"),
            "verification_status": cells[3],
            "supporting_source_ids": support_ids,
        }
    tx.atomic_write_json(
        runtime / "evidence-manifest.json",
        {
            "schema": "discovery-call-evidence-manifest/v1",
            "context_id": total["context_id"],
            "run_id": total["latest_run_id"],
            "business_mode": mode,
            "customer_id": total["customer_id"],
            "project_id": authorization.get("project_id") or None,
            "updated_at": total["updated_at"],
            "connector_audit": {
                "status": "not_applicable",
                "connector_id": None,
                "call_id": None,
                "called_at": None,
                "tenant_id": authorization.get("tenant_id") or None,
                "customer_id": total["customer_id"],
                "project_id": authorization.get("project_id") or None,
                "allowed_project_ids": authorization.get("allowed_project_ids", []),
                "authorization_owner": authorization.get("authorization_owner") or None,
                "authorization_expires_at": authorization.get("authorization_expires_at") or None,
                "authorized_roots": authorization.get("authorized_roots", []),
                "allowed_dataset_aliases": authorization.get("allowed_dataset_aliases", []),
                "allowed_confidentiality": authorization.get("allowed_confidentiality", []),
                "authorization_purpose": authorization.get("authorization_purpose") or None,
                "capability_receipt_id": authorization.get("capability_receipt_id") or None,
                "authorization_actor_id": authorization.get("authorization_actor_id") or None,
                "capability_operation": authorization.get("capability_operation") or None,
                "capability_receipt_verified": bool(authorization.get("capability_receipt_verified", False)),
                "capability_receipt_issuer": authorization.get("capability_receipt_issuer") or None,
                "capability_receipt_key_id": authorization.get("capability_receipt_key_id") or None,
                "capability_receipt_sha256": authorization.get("capability_receipt_sha256") or None,
                "capability_receipt_verified_at": authorization.get("capability_receipt_verified_at") or None,
                "capability_receipt_expires_at": authorization.get("capability_receipt_expires_at") or None,
                "server_filter_verified": False,
                "response_scope_verified": False,
                "response_fingerprint": None,
                "isolated_record_count": 0,
            },
            "sources": machine_sources,
            "claims": machine_claims,
            "query_links": {},
        },
    )
    metrics = rp.RunMetrics(
        runtime / "run-metrics.json",
        total["context_id"],
        total["latest_run_id"],
        mode,
        generated_at,
    ).initial(len(plan["queries"]))
    tx.atomic_write_json(runtime / "run-metrics.json", metrics)


def bind_candidate_machine_bundle(candidate: Path, selected_modules: list[str]) -> None:
    """Populate and bind all four research-machine files in a built candidate.

    ``build_candidate.py`` binds its receipt to the candidate manifest before
    research materialization.  Tests that exercise the real init -> candidate
    -> commit path therefore need to refresh only the manifest's machine-file
    records and the receipt digest after installing evidence.  The source CAS,
    transaction sequence, artifact hashes, and candidate identity remain
    unchanged.
    """
    marker_path = candidate / "runtime" / "candidate-receipt.json"
    manifest_path = candidate / tx.MANIFEST_REL
    if not marker_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("candidate receipt/manifest missing")

    _install_machine_bundle(candidate, selected_modules)
    manifest = load_json(manifest_path)
    total_path = next(candidate.glob("*客户研究与拜访准备报告.md"))
    total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
    runtime_files: dict[str, dict[str, str]] = {}
    for name in (
        "search-plan.json",
        "source-cache.json",
        "evidence-manifest.json",
        "run-metrics.json",
    ):
        path = candidate / "runtime" / name
        payload = load_json(path)
        runtime_files[name] = {
            "path": f"runtime/{name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "schema": str(payload.get("schema", "")),
            "context_id": str(payload.get("context_id", "")),
            "run_id": str(payload.get("run_id", "")),
        }
    manifest["runtime_files"] = runtime_files
    manifest["evidence_run_id"] = total["latest_run_id"]
    manifest["updated_at"] = total["updated_at"]
    tx.atomic_write_json(manifest_path, manifest)

    marker = load_json(marker_path)
    marker["payload_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    tx.atomic_write_json(marker_path, marker)


def _grant(
    grant_id: str,
    role: str,
    operations: list[str],
    customer_id: str,
) -> dict:
    return {
        "grant_id": grant_id,
        "role": role,
        "operations": operations,
        "business_modes": ["*"],
        "customer_ids": [customer_id],
        "valid_from": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
    }


def install_governance_context(workspace: Path) -> dict:
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
    customer_id = total["customer_id"]
    actors = {
        "reviewer-letter-facts": ("吴芳（客户信事实复核岗）", "evidence_reviewer", ["review_letter_facts"]),
        "reviewer-leader": ("孙宁（人物事实审核岗）", "evidence_reviewer", ["approve_artifact:leader"]),
        "reviewer-strategy": ("钱琳（拜访策略审核岗）", "commercial_reviewer", ["approve_artifact:strategy"]),
        "reviewer-briefing": ("何静（会前简报事实审核岗）", "evidence_reviewer", ["approve_artifact:briefing"]),
        "ready-briefing": ("刘宁（客户责任岗）", "account_owner", ["mark_ready:briefing"]),
        "ready-standard": ("陈洁（交付就绪审核岗）", "commercial_reviewer", ["mark_ready:standard_visit"]),
        "ready-letter": ("陈洁（交付就绪审核岗）", "external_approver", ["mark_ready:letter"]),
        "approver-li": ("李明（客户沟通审批岗）", "external_approver", ["approve_letter"]),
        "approver-zhou": ("周岚（客户沟通审批岗）", "external_approver", ["approve_letter"]),
        "letter-editor": ("赵敏（客户信修订岗）", "runtime_owner", ["begin_letter_revision"]),
        "requester-wang": ("王强（认证请求人）", "requester", ["emit_external"]),
    }
    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    issuer = f"test-host:{secrets.token_hex(8)}"
    key_id = f"test-key-{secrets.token_hex(4)}"
    payload = {
        "schema": "discovery-call-governance/v1",
        "context_id": total["context_id"],
        "customer_id": customer_id,
        "runtime_actor_id": "runtime-actor-001",
        "updated_at": "2026-08-27T00:00:00Z",
        "actors": {
            actor_id: {
                "display_name": display,
                "actor_type": "human",
                "identity_provider": "test-sso",
                "status": "active",
                "grants": [_grant(f"grant-{actor_id}", role, operations, customer_id)],
            }
            for actor_id, (display, role, operations) in actors.items()
        },
        "action_assertions": {},
        "external_requests": {},
    }
    identity = {
        "schema": governance.IDENTITY_ASSERTION_SCHEMA,
        "issuer": issuer,
        "audience": governance.TRUST_AUDIENCE,
        "key_id": key_id,
        "issued_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
    }
    payload["identity_assertion"] = identity
    identity["signature"] = _sign(private_key, governance.identity_assertion_payload(payload))
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    nonce_dir = workspace.parents[1] / ".governance-nonces"
    nonce_dir.mkdir(mode=0o700, exist_ok=True)
    nonce_dir.chmod(0o700)
    os.environ[governance.PUBLIC_KEY_ENV] = base64.b64encode(public).decode("ascii")
    os.environ[governance.TRUSTED_ISSUER_ENV] = issuer
    os.environ[governance.TRUSTED_KEY_ID_ENV] = key_id
    os.environ[governance.NONCE_DIR_ENV] = str(nonce_dir.resolve())
    _GOVERNANCE_SIGNERS[issuer] = private_key
    runtime = workspace / "runtime"
    runtime.mkdir(exist_ok=True)
    tx.atomic_write_json(runtime / "governance-context.json", payload)
    return payload


def record_action_assertion(
    workspace: Path,
    *,
    event_id: str,
    actor_id: str,
    operation: str,
    artifact_type: str,
) -> dict:
    governance_path = workspace / "runtime" / "governance-context.json"
    payload = load_json(governance_path)
    total, _ = _artifact_target(workspace, "comprehensive_report")
    target, target_body = _artifact_target(workspace, artifact_type)
    body_value = _letter_body(target_body) if artifact_type == "customer_letter_internal" else target_body
    now = datetime.now(timezone.utc)
    event = {
        "schema": governance.ACTION_ASSERTION_SCHEMA,
        "action_id": event_id,
        "event_type": "governance_action_approved",
        "source": "authenticated_human_action",
        "verified": True,
        "decision": "approved",
        "actor_id": actor_id,
        "operation": operation,
        "context_id": target["context_id"],
        "customer_id": target["customer_id"],
        "business_mode": total["business_mode"],
        "target_artifact_type": artifact_type,
        "target_content_version": target["content_version"],
        "target_body_sha256": _body_digest(body_value),
        "target_context_sha256": _letter_context_digest(target) if artifact_type == "customer_letter_internal" else "",
        "session_id": f"test-session-{secrets.token_hex(8)}",
        "nonce": secrets.token_hex(24),
        "issuer": payload["identity_assertion"]["issuer"],
        "audience": governance.TRUST_AUDIENCE,
        "key_id": payload["identity_assertion"]["key_id"],
        "issued_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "consumed_at": None,
        "consumed_by_run_id": None,
    }
    signer = _GOVERNANCE_SIGNERS[event["issuer"]]
    event["signature"] = _sign(signer, governance.action_assertion_payload(event))
    payload["action_assertions"][event_id] = event
    payload["updated_at"] = now.isoformat().replace("+00:00", "Z")
    tx.atomic_write_json(governance_path, payload)
    manifest = load_json(workspace / tx.MANIFEST_REL)
    _rebuild_manifest(workspace, list(manifest.get("selected_modules", [])))
    return event


def record_external_request(
    workspace: Path,
    *,
    event_id: str,
    actor_id: str = "requester-wang",
) -> dict:
    governance_path = workspace / "runtime" / "governance-context.json"
    payload = load_json(governance_path)
    internal_path = next(workspace.glob("*客户信（内部待审核稿）.md"))
    internal = tx.parse_frontmatter(internal_path.read_text(encoding="utf-8"))
    approved_at = datetime.fromisoformat(internal["approved_at"].replace("Z", "+00:00"))
    requested_at = datetime.now(timezone.utc)
    if requested_at <= approved_at:
        requested_at = approved_at + timedelta(microseconds=1)
    payload["external_requests"][event_id] = {
        "schema": governance.EXTERNAL_REQUEST_ASSERTION_SCHEMA,
        "request_id": event_id,
        "event_type": "external_output_requested",
        "actor_id": actor_id,
        "source": "authenticated_user_turn",
        "verified": True,
        "operation": "emit_external",
        "business_mode": "letter",
        "context_id": internal["context_id"],
        "customer_id": internal["customer_id"],
        "approval_run_id": internal["latest_run_id"],
        "internal_content_version": internal["content_version"],
        "approved_body_sha256": internal["approved_body_sha256"],
        "approved_context_sha256": internal["approved_context_sha256"],
        "session_id": f"test-session-{secrets.token_hex(8)}",
        "nonce": secrets.token_hex(24),
        "issuer": payload["identity_assertion"]["issuer"],
        "audience": governance.TRUST_AUDIENCE,
        "key_id": payload["identity_assertion"]["key_id"],
        "issued_at": (requested_at - timedelta(microseconds=1)).isoformat().replace("+00:00", "Z"),
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (requested_at + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "consumed_at": None,
        "consumed_by_run_id": None,
    }
    event = payload["external_requests"][event_id]
    event["signature"] = _sign(
        _GOVERNANCE_SIGNERS[event["issuer"]], governance.external_request_assertion_payload(event)
    )
    payload["updated_at"] = requested_at.isoformat().replace("+00:00", "Z")
    tx.atomic_write_json(governance_path, payload)
    manifest = load_json(workspace / tx.MANIFEST_REL)
    _rebuild_manifest(workspace, list(manifest.get("selected_modules", [])))
    return payload["external_requests"][event_id]


def build_pending_letter_workspace(output_root: Path) -> Path:
    """Build the smallest non-strict-valid workspace for letter lifecycle tests."""
    intake_path = write_intake(output_root, "示例医院", "letter")
    initialized = run_python(
        "init_workspace.py",
        [
            "示例医院",
            "--output-root",
            str(output_root),
            "--task-timezone",
            "Asia/Shanghai",
            "--runtime-owner",
            "测试负责人",
            "--business-mode",
            "letter",
            "--intake-input",
            str(intake_path),
            "--json",
        ],
    )
    if initialized.returncode:
        raise RuntimeError(initialized.stderr or initialized.stdout)
    workspace = Path(json.loads(initialized.stdout)["workspace"])
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    institution_path = next(workspace.glob("*机构研究报告.md"))
    letter_path = next(workspace.glob("*客户信（内部待审核稿）.md"))
    total_original = total_path.read_text(encoding="utf-8")
    institution_original = institution_path.read_text(encoding="utf-8")
    letter_original = letter_path.read_text(encoding="utf-8")
    initial = tx.parse_frontmatter(total_original)
    run_id = initial["latest_run_id"]
    timestamp = initial["updated_at"]
    cutoff = initial["evidence_cutoff_date"]

    institution_body = """
# 示例医院机构研究报告

公开资料确认示例医院为本次研究主体（CLM-I-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001 | 无 | 高 | 用于客户信主体确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | 主体确认 | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
    institution_text = _document(
        institution_original,
        {
            "module_status": "completed",
            "review_status": "not_required",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
        },
        institution_body,
    )

    letter_context = {
        "letter_scenario": "拜访后正式跟进",
        "recipient_role": "张主任，信息中心主任，身份已确认",
        "letter_purpose": "确认下一次技术交流安排",
        "expected_action": "确认九月技术交流时间",
        "signer": "王经理，客户负责人",
        "delivery_channel": "正式电子邮件",
    }
    letter_body = f"""
# 示例医院客户信（内部待审核稿）

## 1. 内部摘要

- 信件场景：{letter_context['letter_scenario']}
- 收件对象：{letter_context['recipient_role']}
- 发信目的：{letter_context['letter_purpose']}
- 期望动作：{letter_context['expected_action']}
- 签署人：{letter_context['signer']}
- 发送渠道：{letter_context['delivery_channel']}
- 事实依据：CLM-I-001

## 2. 候选正文

`EXTERNAL_BODY_START`

张主任，您好：

感谢您此前的交流。诚请您确认九月技术交流的合适时间，我们将据此安排相关同事参加。

王经理

`EXTERNAL_BODY_END`

## 4. 版本与审核记录（严禁外发）

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner | review_status |
|---|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | 完成客户信内部稿并提交审核 | 测试负责人 | pending |
"""
    letter_text = _document(
        letter_original,
        {
            "module_status": "completed",
            "review_status": "pending",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
            **letter_context,
            "external_output_required": "false",
            "approver": "",
            "approved_at": "",
            "approved_content_version": "",
            "approved_body_sha256": "",
            "approved_context_sha256": "",
        },
        letter_body,
    )

    status_header = (
        "| 模块 | selected_in_run | run_action | module_status | review_status | "
        "connector_status | freshness_status | content_version | latest_run_id | "
        "updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | "
        "gaps/blockers | 成果链接 |"
    )
    uncalled = {
        "人物研究": "",
        "内部检索": "",
        "交流策略": "",
        "客户信外发版": "",
    }
    status_rows = [
        f"| 机构研究 | true | created | completed | not_required | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | 无 | [机构研究](./{institution_path.name}) |",
        *(
            f"| {label} | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |"
            for label in uncalled
            if label != "客户信外发版"
        ),
        f"| 客户信内部审核稿 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | 无 | [客户信内部审核稿](./{letter_path.name}) |",
        "| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
    ]
    run_summary = (
        "route=letter; depth=standard; objective=letter; "
        "selected_modules=institution,letter; created=institution,letter; "
        "updated=none; reused=none; generated=none; "
        "not_called=leader,internal,strategy,external_letter; "
        f"target_evidence_cutoff_date={cutoff}"
    )
    total_body = f"""
# 示例医院客户研究与拜访准备报告

本次客户信由公开事实 CLM-I-001 支撑。

## 2. 任务上下文与成果状态

{status_header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(status_rows)}

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | {run_summary} | 测试负责人 |
"""
    total_text = _document(
        total_original,
        {
            "module_status": "completed",
            "review_status": "not_required",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
            "workflow_stage": "review",
            "ready_for_use": "false",
            "readiness_reviewer": "",
            "readiness_reviewed_at": "",
            "readiness_content_version": "",
            "readiness_body_sha256": "",
        },
        total_body,
    )

    institution_path.write_text(institution_text, encoding="utf-8")
    letter_path.write_text(letter_text, encoding="utf-8")
    total_path.write_text(total_text, encoding="utf-8")
    install_governance_context(workspace)
    _install_machine_bundle(workspace, ["institution", "letter"])
    _rebuild_manifest(workspace, ["institution", "letter"])
    return workspace


def build_pending_strategy_workspace(output_root: Path) -> Path:
    """Build a valid pending standard-visit workspace for generic review tests."""
    intake_path = write_intake(output_root, "示例医院", "standard_visit")
    initialized = run_python(
        "init_workspace.py",
        [
            "示例医院",
            "--output-root",
            str(output_root),
            "--task-timezone",
            "Asia/Shanghai",
            "--runtime-owner",
            "测试负责人",
            "--business-mode",
            "standard_visit",
            "--intake-input",
            str(intake_path),
            "--json",
        ],
    )
    if initialized.returncode:
        raise RuntimeError(initialized.stderr or initialized.stdout)
    workspace = Path(json.loads(initialized.stdout)["workspace"])
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    institution_path = next(workspace.glob("*机构研究报告.md"))
    leader_path = next(workspace.glob("*人物研究报告.md"))
    strategy_path = next(workspace.glob("*交流策略与议题设计.md"))
    originals = {
        "total": total_path.read_text(encoding="utf-8"),
        "institution": institution_path.read_text(encoding="utf-8"),
        "leader": leader_path.read_text(encoding="utf-8"),
        "strategy": strategy_path.read_text(encoding="utf-8"),
    }
    initial = tx.parse_frontmatter(originals["total"])
    run_id = initial["latest_run_id"]
    timestamp = initial["updated_at"]
    cutoff = initial["evidence_cutoff_date"]
    terminal = {
        "module_status": "completed",
        "freshness_status": "current",
        "content_version": "1",
        "latest_run_id": run_id,
        "updated_at": timestamp,
        "evidence_cutoff_date": cutoff,
    }

    institution_body = """
# 示例医院机构研究报告

公开资料确认示例医院为本次研究主体（CLM-I-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001 | 无 | 高 | 用于拜访主体确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | 主体确认 | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
    institution_path.write_text(
        _document(
            originals["institution"],
            {**terminal, "review_status": "not_required"},
            institution_body,
        ),
        encoding="utf-8",
    )

    leader_body = """
# 示例医院人物研究报告

公开任职信息显示张主任负责信息化工作（CLM-L-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-L-001 | F | public | verified_single | 张主任负责信息化工作 | 2026-08-26公开任职口径 | SRC-L-001 | 无 | 高 | 用于拜访对象确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-L-001 | 示例医院领导介绍 | 示例医院 | https://example.org/hospital/leader | 2026-08-25 | 2026-08-26 | A | official-leader | public | 示例医院 | 任职确认 | sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb | official:leader-page | true |
"""
    leader_path.write_text(
        _document(
            originals["leader"],
            {
                **terminal,
                "review_status": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "reviewed_content_version": "",
                "reviewed_body_sha256": "",
            },
            leader_body,
        ),
        encoding="utf-8",
    )

    strategy_context = {
        "target_contact_level": "信息中心主任张主任",
        "visit_objective": "确认院级数据治理需求与决策路径",
        "minimum_next_step": "确定下一次需求澄清会时间",
    }
    strategy_body = f"""
# 示例医院交流策略与议题设计

## 目标与最小推进动作

- 拜访对象：{strategy_context['target_contact_level']}
- 拜访目标：{strategy_context['visit_objective']}
- 最小推进动作：{strategy_context['minimum_next_step']}
- 事实依据：CLM-I-001、CLM-L-001

## 机会资格

以客户任务、预算、权限和时序为现场验证重点。

## 议程

围绕现状、目标和下一步展开。

## 参会分工

客户负责人主持，方案顾问记录问题。

## 材料计划

使用经授权的方案简介。

## 会后行动

由客户负责人跟进下一次需求澄清会，并形成CRM/PIMS候选记录。

## CRM/PIMS

记录最小下一步、owner与预计完成时间。
"""
    strategy_path.write_text(
        _document(
            originals["strategy"],
            {
                **terminal,
                "review_status": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "reviewed_content_version": "",
                "reviewed_body_sha256": "",
                **strategy_context,
            },
            strategy_body,
        ),
        encoding="utf-8",
    )

    header = (
        "| 模块 | selected_in_run | run_action | module_status | review_status | "
        "connector_status | freshness_status | content_version | latest_run_id | "
        "updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | "
        "gaps/blockers | 成果链接 |"
    )
    rows = [
        f"| 机构研究 | true | created | completed | not_required | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | 无 | [机构研究](./{institution_path.name}) |",
        f"| 人物研究 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-L-001 | none | 无 | [人物研究](./{leader_path.name}) |",
        "| 内部检索 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
        f"| 交流策略 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001, CLM-L-001 | none | 无 | [交流策略](./{strategy_path.name}) |",
        "| 客户信内部审核稿 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
        "| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
    ]
    summary = (
        "route=visit_prep; depth=standard; objective=standard_visit; "
        "selected_modules=institution,leader,strategy; "
        "created=institution,leader,strategy; updated=none; reused=none; "
        "generated=none; not_called=internal,letter,external_letter; "
        f"target_evidence_cutoff_date={cutoff}"
    )
    total_body = f"""
# 示例医院客户研究与拜访准备报告

> 用户业务模式：标准拜访包｜内部研究档位：标准版｜信息截止：{cutoff}

本次拜访由 CLM-I-001 和 CLM-L-001 支撑。

## 2. 任务上下文与成果状态

{header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | {summary} | 测试负责人 |
"""
    total_path.write_text(
        _document(
            originals["total"],
            {
                **terminal,
                "review_status": "not_required",
                "workflow_stage": "review",
                "ready_for_use": "false",
                "readiness_reviewer": "",
                "readiness_reviewed_at": "",
                "readiness_content_version": "",
                "readiness_body_sha256": "",
            },
            total_body,
        ),
        encoding="utf-8",
    )
    install_governance_context(workspace)
    _install_machine_bundle(workspace, ["institution", "leader", "strategy"])
    _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
    return workspace
