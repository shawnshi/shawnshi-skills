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

from tests.common import (
    attest_candidate,
    candidate_attestation,
    governance,
    load_json,
    research_plan as rp,
    run_python,
    runtime_tx as tx,
    validate_outputs,
    write_intake,
)


_GOVERNANCE_SIGNERS: dict[str, Ed25519PrivateKey] = {}
_SOURCE_RECEIPT_ISSUER = "test-source-host"
_SOURCE_RECEIPT_KEY_ID = "test-source-key"
_SOURCE_RECEIPT_PRIVATE_KEY = Ed25519PrivateKey.generate()
FIXTURE_EVIDENCE_CUTOFF = "2026-08-27"


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
        "schema": "discovery-call-source-capture-receipt/v3",
        "issuer": _SOURCE_RECEIPT_ISSUER,
        "audience": "discovery-call-source-capture",
        "key_id": _SOURCE_RECEIPT_KEY_ID,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "receipt_id": f"srcpt-{source_id.casefold()}",
        "source_id": source_id,
        "source_title": snapshot["source_title"],
        "publisher_or_provider": snapshot["publisher_or_provider"],
        "locator": snapshot["locator"],
        "final_url": snapshot["final_url"],
        "canonical_locator": snapshot["canonical_locator"],
        "publication_or_update_date": snapshot["publication_or_update_date"],
        "access_date": snapshot["access_date"],
        "content_sha256": snapshot["content_sha256"],
        "length": snapshot["length"],
        "capture_method": snapshot["capture_method"],
        "retrieved_at": snapshot["retrieved_at"],
        "published_at": snapshot.get("published_at"),
        "source_updated_at": snapshot.get("source_updated_at"),
        "internal_recorded_at": snapshot.get("internal_recorded_at"),
        "source_level": snapshot["source_level"],
        "source_group": snapshot["source_group"],
        "permission": snapshot["permission"],
        "applicable_scope": snapshot["applicable_scope"],
        "notes": snapshot["notes"],
        "upstream_id": snapshot["upstream_id"],
        "external_use": snapshot["external_use"],
        "tenant_id": snapshot.get("tenant_id"),
        "run_id": total["latest_run_id"],
        "customer_id": total["customer_id"],
        "project_id": snapshot.get("project_id", project_id),
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
    parse_issues: list[object] = []
    documents = validate_outputs.load_documents(workspace, parse_issues)
    if parse_issues:
        raise RuntimeError("fixture documents could not be parsed before manifest rebuild")
    by_type = {
        document.frontmatter.get("artifact_type", ""): document
        for document in documents
        if document.frontmatter.get("artifact_type")
    }
    delivery_summary = validate_outputs.delivery_summary_for_documents(
        by_type,
        business_mode=total["business_mode"],
        selected_modules=selected_modules,
    )
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
        intake_preflight=(
            dict(old["intake_preflight"])
            if isinstance(old.get("intake_preflight"), dict)
            else None
        ),
        delivery_summary=delivery_summary,
    )
    tx.atomic_write_json(workspace / tx.MANIFEST_REL, manifest)


def _install_candidate_attestation_audit(workspace: Path) -> None:
    """Install a protected-host-equivalent candidate audit for lifecycle fixtures."""

    manifest_path = workspace / tx.MANIFEST_REL
    manifest = load_json(manifest_path)
    candidate = workspace.parent / f".fixture-candidate-{secrets.token_hex(6)}"
    (candidate / "runtime").mkdir(parents=True)
    candidate_manifest_path = candidate / tx.MANIFEST_REL
    tx.atomic_write_json(
        candidate_manifest_path,
        {
            "schema": tx.RUNTIME_SCHEMA,
            "context_id": manifest["context_id"],
            "customer_id": manifest["customer_id"],
            "intake_preflight": manifest["intake_preflight"],
        },
    )
    marker = {
        "schema": candidate_attestation.MARKER_SCHEMA,
        "context_id": manifest["context_id"],
        "run_id": manifest["latest_run_id"],
        "source_manifest_revision": manifest["transaction_sequence"],
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_workspace": str(workspace.resolve()),
        "candidate_workspace": str(candidate.resolve()),
        "input_payload_sha256": hashlib.sha256(b"fixture-lifecycle-candidate").hexdigest(),
        "final_manifest_sha256": hashlib.sha256(candidate_manifest_path.read_bytes()).hexdigest(),
    }
    tx.atomic_write_json(candidate / candidate_attestation.MARKER_REL, marker)
    attestation_path = attest_candidate(candidate)
    expected = load_json(candidate / candidate_attestation.REQUEST_REL)
    verified = candidate_attestation.verify_candidate_attestation(
        attestation_path,
        expected=expected,
    )
    candidate_attestation.claim_candidate_attestation_nonce(
        verified,
        workspace=workspace,
    )
    audit = verified.audit_summary(expected)

    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
    next_manifest = tx.build_manifest(
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
        task_timezone=manifest.get("task_timezone"),
        latest_run_id=total["latest_run_id"],
        content_version=total["content_version"],
        stage=total["workflow_stage"],
        ready_for_use=total["ready_for_use"] == "true",
        selected_modules=list(manifest.get("selected_modules", [])),
        authorization=manifest.get("authorization", {}),
        transaction_sequence=int(manifest["transaction_sequence"]) + 1,
        intake_preflight=manifest["intake_preflight"],
        candidate_attestation=audit,
    )
    tx.atomic_write_json(manifest_path, next_manifest)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _intake_candidate_value(intake_path: Path, field: str) -> str:
    payload = load_json(intake_path)
    matching = [
        item
        for item in payload.get("candidate_sets", [])
        if isinstance(item, dict) and item.get("field") == field
    ]
    candidates = matching[0].get("candidates", []) if len(matching) == 1 else []
    values = [
        item.get("value")
        for item in candidates
        if isinstance(item, dict) and item.get("status") == "asserted"
    ]
    if len(values) != 1 or not isinstance(values[0], str):
        raise RuntimeError(f"fixture intake missing one asserted value for {field}")
    return values[0]


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
        strategy_meta, _ = _artifact_target(workspace, "visit_strategy")
        business_fields.update(
            {
                "target_contact_level": strategy_meta.get("target_contact_level", ""),
                "visit_objective": strategy_meta.get("visit_objective", ""),
                "minimum_next_step": strategy_meta.get("minimum_next_step", ""),
            }
        )
    elif mode == "letter":
        letter_meta, _ = _artifact_target(workspace, "customer_letter_internal")
        business_fields.update(
            {
                field: letter_meta.get(field, "")
                for field in (
                    "letter_scenario",
                    "recipient_role",
                    "letter_purpose",
                    "expected_action",
                    "signer",
                    "delivery_channel",
                )
            }
        )
    elif mode == "strategic_account":
        strategy_meta, _ = _artifact_target(workspace, "visit_strategy")
        business_fields.update(
            {
                field: strategy_meta.get(field, "")
                for field in (
                    "strategic_question",
                    "planning_horizon",
                    "minimum_next_step",
                )
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
            "source_title": cells[1],
            "publisher_or_provider": cells[2],
            "locator": locator,
            "final_url": locator,
            "canonical_locator": canonical,
            "publication_or_update_date": cells[4],
            "access_date": cells[5],
            "source_fingerprint": "sha256:" + digest,
            "content_sha256": digest,
            "retrieved_at": retrieved_at,
            "published_at": None,
            "source_updated_at": None,
            "internal_recorded_at": None,
            "source_level": cells[6],
            "source_group": cells[7],
            "permission": cells[8],
            "applicable_scope": cells[9],
            "notes": cells[10],
            "upstream_id": cells[12],
            "external_use": cells[13],
            "tenant_id": authorization.get("tenant_id") or None,
            "project_id": authorization.get("project_id") or None,
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
            "claim_type": cells[1],
            "provenance": cells[2],
            "verification_status": cells[3],
            "claim_text": cells[4],
            "time_scope": cells[5],
            "supporting_source_refs": cells[6],
            "supporting_source_ids": support_ids,
            "supporting_source_receipt_sha256s": {
                source_id: hashlib.sha256(
                    json.dumps(
                        machine_sources[source_id]["capture_receipt"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                for source_id in support_ids
            },
            "counter_source_refs": cells[7],
            "counter_source_ids": sorted(set(re.findall(r"SRC-(?:I|L|N)-\d{3,}", cells[7]))),
            "confidence": cells[8],
            "downstream_impact": cells[9],
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
                "capability_receipt_run_id": authorization.get("capability_receipt_run_id") or None,
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
    marker["schema"] = "discovery-call-candidate-receipt/v2"
    marker.pop("payload_sha256", None)
    marker.setdefault("input_payload_sha256", hashlib.sha256(b"test-fixture-input").hexdigest())
    marker["final_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    tx.atomic_write_json(marker_path, marker)
    attest_candidate(candidate)


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
        "reviewer-institution": ("周洁（机构事实审核岗）", "evidence_reviewer", ["approve_artifact:institution"]),
        "reviewer-leader": ("孙宁（人物事实审核岗）", "evidence_reviewer", ["approve_artifact:leader"]),
        "reviewer-strategy": ("钱琳（拜访策略审核岗）", "commercial_reviewer", ["approve_artifact:strategy"]),
        "reviewer-briefing": ("何静（会前简报事实审核岗）", "evidence_reviewer", ["approve_artifact:briefing"]),
        "ready-briefing": ("刘宁（客户责任岗）", "account_owner", ["mark_ready:briefing"]),
        "ready-standard": ("陈洁（交付就绪审核岗）", "commercial_reviewer", ["mark_ready:standard_visit"]),
        "ready-strategic": ("刘宁（战略账户责任岗）", "account_owner", ["mark_ready:strategic_account"]),
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
    intake_path = write_intake(
        output_root,
        "示例医院",
        "letter",
        letter_recipient_role="信息中心主任｜身份已确认",
    )
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
            "--evidence-cutoff-date",
            FIXTURE_EVIDENCE_CUTOFF,
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
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | none | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
    institution_text = _document(
        institution_original,
        {
            "module_status": "completed",
            "review_status": "pending",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
        },
        institution_body,
    )

    letter_context = {
        field: _intake_candidate_value(intake_path, field)
        for field in (
            "letter_scenario",
            "recipient_role",
            "letter_purpose",
            "expected_action",
            "signer",
            "delivery_channel",
        )
    }
    letter_salutation = validate_outputs.context_anchor(letter_context["recipient_role"])
    letter_signer = validate_outputs.context_anchor(letter_context["signer"])
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

{letter_salutation}，您好：

本次交流将围绕双方关心的技术议题展开。我们希望通过本次来函{letter_context['letter_purpose']}。诚请您{letter_context['expected_action']}，我们将据此安排相关同事参加。

{letter_signer}

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
        f"| 机构研究 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | none | [机构研究](./{institution_path.name}) |",
        *(
            f"| {label} | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |"
            for label in uncalled
            if label != "客户信外发版"
        ),
        f"| 客户信内部审核稿 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | none | [客户信内部审核稿](./{letter_path.name}) |",
        "| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |",
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
    _install_candidate_attestation_audit(workspace)
    return workspace


def build_pending_strategy_workspace(
    output_root: Path,
    *,
    business_mode: str = "standard_visit",
    include_leader: bool = True,
) -> Path:
    """Build a valid pending scheduled-visit or account-planning workspace."""
    if business_mode not in {"standard_visit", "strategic_account"}:
        raise ValueError("business_mode must be standard_visit or strategic_account")
    intake_path = write_intake(output_root, "示例医院", business_mode)
    module_args = ["--modules", "leader"] if include_leader else []
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
            business_mode,
            "--evidence-cutoff-date",
            FIXTURE_EVIDENCE_CUTOFF,
            *module_args,
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
    leader_path = next(workspace.glob("*人物研究报告.md"), None)
    strategy_path = next(workspace.glob("*交流策略与议题设计.md"))
    originals = {
        "total": total_path.read_text(encoding="utf-8"),
        "institution": institution_path.read_text(encoding="utf-8"),
        "strategy": strategy_path.read_text(encoding="utf-8"),
    }
    if include_leader:
        if leader_path is None:
            raise RuntimeError("explicit leader fixture did not create leader artifact")
        originals["leader"] = leader_path.read_text(encoding="utf-8")
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
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | none | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
    institution_path.write_text(
        _document(
            originals["institution"],
            {**terminal, "review_status": "pending"},
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
| SRC-L-001 | 示例医院领导介绍 | 示例医院 | https://example.org/hospital/leader | 2026-08-25 | 2026-08-26 | A | official-leader | public | 示例医院 | none | sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb | official:leader-page | true |
"""
    if include_leader and leader_path is not None:
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

    if business_mode == "standard_visit":
        strategy_context = {
            "target_contact_level": _intake_candidate_value(intake_path, "target_role"),
            "visit_objective": _intake_candidate_value(intake_path, "visit_objective"),
            "minimum_next_step": _intake_candidate_value(intake_path, "minimum_next_step"),
        }
        strategy_body = f"""
# 示例医院交流策略与议题设计

## 目标与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 主要目标 | {strategy_context['visit_objective']} | CLM-I-001 |
| 最小推进动作 | {strategy_context['minimum_next_step']} | CLM-I-001 |
| 成功标准 | 客户确认下一步验证安排与责任角色 | CLM-I-001 |

- 目标对象：{strategy_context['target_contact_level']}

## 机会资格

| 维度 | 当前判断 | claim_id | 待验证问题 |
|---|---|---|---|
| Budget | 预算状态尚无可靠证据 | CLM-I-001 | 核实正式预算或采购安排 |
| Authority | 信息化职责已确认，其他角色未知 | CLM-L-001 | 核实预算、采购和验收角色 |
| Need | 数据治理任务仍需客户确认 | CLM-I-001 | 核实任务、压力和目标结果 |
| Timing/采购时序 | 当前没有可靠时序证据 | CLM-I-001 | 核实计划、审批及采购窗口 |
| 竞争位置 | 存量和竞争信息尚待核实 | CLM-I-001 | 核实现有系统和供应商约束 |

- 建议：monitor
- 投入强度：低
- 前提与停止条件：确认真实任务和责任角色；无法确认时转为观察

## 议程

| 时间 | 环节/议题 | 客户对象 | 我方owner | 目标信号 |
|---|---|---|---|---|
| 0—5分钟 | 对齐交流目标和边界 | 信息中心主任 | 客户负责人 | 客户确认或修正交流目标 |
| 5—25分钟 | 验证数据治理任务与角色 | 信息中心主任 | 方案顾问 | 形成任务和决策路径反馈 |
| 最后5分钟 | 收口并确认下一步安排 | 信息中心主任 | 客户负责人 | 明确动作、责任人与日期 |

## 参会分工

| 参会人/角色 | RACI | 负责内容 | 备用安排 |
|---|---|---|---|
| 客户负责人 | A | 主持交流并确认下一步 | 无法出席时由账户责任岗接替 |
| 方案顾问 | R | 记录问题和能力边界 | 使用书面问题清单补充记录 |

## 材料计划

| 材料/演示 | 用途与展示时点 | owner | 版本/授权 | 备用/不展示边界 |
|---|---|---|---|---|
| 数据治理方案简介 | 客户确认任务后按需展示 | 方案顾问 | 当前授权版本且可外发 | 未确认需求前不展示产品清单 |

## 会后行动

| action | owner | due_date | 依赖 | 完成标准 | CRM/PIMS候选 |
|---|---|---|---|---|---|
| {strategy_context['minimum_next_step']} | 客户负责人 | 2026-09-25 | 客户确认沟通窗口 | 形成书面时间与责任人记录 | 是 |

## CRM/PIMS

| 候选类型 | 内容 | owner | due_date | 写回状态 |
|---|---|---|---|---|
| action | {strategy_context['minimum_next_step']} | 客户负责人 | 2026-09-25 | candidate_only |
| verification | 核实任务、角色、预算与采购时序 | 方案顾问 | 2026-09-25 | candidate_only |
"""
    else:
        strategy_context = {
            "strategy_variant": _intake_candidate_value(intake_path, "strategy_variant"),
            "strategic_question": _intake_candidate_value(intake_path, "strategic_question"),
            "planning_horizon": _intake_candidate_value(intake_path, "planning_horizon"),
            "minimum_next_step": _intake_candidate_value(intake_path, "minimum_next_step"),
        }
        strategy_body = f"""
# 示例医院账户经营策略与验证计划

## 战略问题与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 待决策问题 | {strategy_context['strategic_question']} | CLM-I-001 |
| 经营周期 | {strategy_context['planning_horizon']} | CLM-I-001 |
| 最小推进动作 | {strategy_context['minimum_next_step']} | CLM-I-001 |
| 完成标准 | 形成可审核的机会资格结论 | CLM-I-001 |

## 判断链与证据边界

| 环节 | 当前判断 | claim_id | 反证/替代解释 | 置信度 | 验证方式 |
|---|---|---|---|---|---|
| 客户发展或履职阶段 | 信息化责任角色已确认但建设阶段待核实 | CLM-I-001 | 公开资料未披露当前项目阶段 | 中 | 向客户核实当前建设阶段和任务 |
| 核心任务或矛盾 | 数据治理任务可能是当前切入口 | CLM-I-001 | 尚无客户正式需求材料支持 | 低 | 核实任务压力和可观察结果 |
| 数字化支撑点 | 先提供需求验证和方案边界澄清 | CLM-I-001 | 产品适配及交付范围仍待验证 | 中 | 仅讨论授权能力并记录差距 |

## 利益相关者与决策结构

| 角色层级 | 当前可核实职责 | 事项/阶段 | 影响方式 | 证据 claim_id | 缺口与验证动作 |
|---|---|---|---|---|---|
| 信息中心主任 | 负责信息化相关工作 | 技术与实施 | 影响与执行 | CLM-L-001 | 核实其正式职责边界及上游审批角色 |
| 预算采购角色 | 当前正式角色尚未确认 | 预算与采购 | 审批与执行 | CLM-I-001 | 通过客户正式渠道核实角色与流程 |

## 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/反证 | 下一验证动作 |
|---|---|---|---|---|
| Budget | 预算来源和状态尚未获得可靠证据 | CLM-I-001 | 公开资料无法证明当前预算 | 核实正式预算或采购安排 |
| Authority | 信息化职责已确认，其他角色未知 | CLM-L-001 | 不推断个人预算或采购权限 | 核实预算、采购和验收角色 |
| Need | 数据治理任务仍处于待客户验证状态 | CLM-I-001 | 尚无客户正式需求材料支持 | 核实任务、压力和目标结果 |
| Timing/采购时序 | 当前没有可靠采购时序证据 | CLM-I-001 | 规划不等于当前采购项目 | 核实计划、审批及采购窗口 |
| 竞争位置 | 存量和竞争信息尚无可靠依据 | CLM-I-001 | 不从单一来源推断供应商格局 | 核实现有系统和切换约束 |

- 建议：monitor
- 投入强度：低
- 建议理由：先完成角色和窗口验证，再决定是否加码（CLM-I-001）。

## 情景与触发条件

| 情景 | 触发信号 | 可能影响 | 应对动作 | owner | 复核日期 |
|---|---|---|---|---|---|
| 基准情景 | 客户确认任务但预算窗口未知 | 保持低强度验证投入 | 完成角色与窗口复核 | 账户负责人 | 2026-09-25 |
| 上行情景 | 客户确认任务、角色及正式窗口 | 可评估增加方案资源 | 提交经授权的适配评估 | 账户负责人 | 2026-10-25 |
| 下行情景 | 无法确认真实任务或正式角色 | 主动投入价值显著下降 | 转为观察并准备退出 | 账户负责人 | 2026-11-24 |

## 30/60/90天账户动作

| 周期 | action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 调整/停止触发 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|---|
| 30天 | {strategy_context['minimum_next_step']} | observe | customer_contact | none | 账户负责人 | 2026-09-25 | 客户确认 | 形成资格复核结论 | 无法确认任务时转观察 | 是 |
| 60天 | 复核角色与预算窗口 | recheck | customer_contact | none | 账户负责人 | 2026-10-25 | 资格复核结论 | 形成角色与窗口清单 | 无正式窗口时停止主动投入 | 是 |
| 90天 | 作出继续或退出判断 | recheck | none | none | 账户负责人 | 2026-11-24 | 前两项完成 | 形成书面投入结论 | 关键证据仍缺失时退出 | 是 |

## 验证计划

| 待验证主张/假设 | 当前状态 | 验证问题或动作 | 目标对象/来源 | owner | due_date | 通过/停止信号 |
|---|---|---|---|---|---|---|
| CLM-I-001对应的真实任务 | unknown | 核实是否存在院级数据治理任务 | 客户正式责任角色 | 账户负责人 | 2026-09-25 | 客户确认任务或明确否定任务 |
| CLM-L-001对应的角色边界 | H | 核实信息化职责及上下游审批角色 | 客户组织与正式流程 | 账户负责人 | 2026-09-25 | 形成可审核角色清单或停止推断 |

## 风险、承诺边界与停止条件

| 风险/停止条件 | 依据 claim_id | 业务后果 | 预防或降级动作 | 升级角色 |
|---|---|---|---|---|
| 无法确认真实任务或正式责任角色 | CLM-I-001 | 继续投入可能造成资源浪费 | 降为观察并停止主动投入 | 战略账户责任岗 |
| 产品适配和交付边界仍未验证 | CLM-I-001 | 不当承诺可能误导客户 | 仅使用已授权材料并升级复核 | 方案责任岗 |

- 停止继续投入的最低条件：90天内仍无法确认真实任务或正式责任角色。
- 禁止承诺：未经授权的价格、效果、工期、资源或高层出席。

## CRM/PIMS候选

| 候选类型 | 内容 | 数据属性 | owner | due_date | 写回状态 |
|---|---|---|---|---|---|
| action | {strategy_context['minimum_next_step']}并形成书面结论 | 建议 | 账户负责人 | 2026-09-25 | candidate_only |
| verification | 核实正式角色与预算采购窗口 | 事实缺口 | 账户负责人 | 2026-10-25 | candidate_only |
"""
    if not include_leader:
        strategy_body = strategy_body.replace("CLM-L-001", "CLM-I-001").replace(
            "张主任", "信息化责任角色"
        )
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
        f"| 机构研究 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | none | [机构研究](./{institution_path.name}) |",
        (
            f"| 人物研究 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-L-001 | none | none | [人物研究](./{leader_path.name}) |"
            if include_leader and leader_path is not None
            else "| 人物研究 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |"
        ),
        "| 内部检索 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |",
        f"| 交流策略 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | {'CLM-I-001, CLM-L-001' if include_leader else 'CLM-I-001'} | none | none | [交流策略](./{strategy_path.name}) |",
        "| 客户信内部审核稿 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |",
        "| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |",
    ]
    route = "visit_prep" if business_mode == "standard_visit" else "strategy"
    depth = "standard" if business_mode == "standard_visit" else "deep"
    selected_names = "institution,leader,strategy" if include_leader else "institution,strategy"
    not_called_names = (
        "internal,letter,external_letter"
        if include_leader
        else "leader,internal,letter,external_letter"
    )
    summary = (
        f"route={route}; depth={depth}; objective={business_mode}; "
        f"selected_modules={selected_names}; "
        f"created={selected_names}; updated=none; reused=none; "
        f"generated=none; not_called={not_called_names}; "
        f"target_evidence_cutoff_date={cutoff}"
    )
    action_owner = "客户负责人" if business_mode == "standard_visit" else "账户负责人"
    total_body = f"""
# 示例医院客户研究与行动准备报告

> 用户业务模式：{'标准拜访包' if business_mode == 'standard_visit' else '战略客户包'}｜内部研究档位：{'标准版' if business_mode == 'standard_visit' else '深度版'}｜信息截止：{cutoff}
## 1. 决策摘要

| 核心问题 | 当前结论 | claim_id | 对业务决策的意义 |
|---|---|---|---|
| 客户主体 | 示例医院主体已经公开资料确认 | CLM-I-001 | 可围绕该机构开展后续验证 |
| 责任角色 | 张主任负责信息化工作 | CLM-L-001 | 可从正式信息化职责切入沟通 |
| 当前任务 | 数据治理任务仍需客户进一步确认 | CLM-I-001 | 现阶段应保持验证优先而非扩大承诺 |

## 2. 任务上下文与成果状态

{header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## 3. 综合判断链

| 环节 | 判断 | claim_id | 反证/局限 | 置信度 | 验证问题或动作 |
|---|---|---|---|---|---|
| 发展阶段 | 已具备信息化责任角色但建设阶段待确认 | CLM-I-001 | 公开资料未披露当前项目阶段 | 中 | 向客户核实当前建设阶段和优先任务 |
| 核心矛盾 | 数据治理任务可能是当前切入口 | CLM-I-001 | 尚无客户正式需求材料支持 | 低 | 核实是否存在院级数据治理任务 |
| 决策者关注 | 正式信息化职责可能关注实施可行性 | CLM-L-001 | 不推断个人偏好或预算权限 | 低 | 确认各阶段正式责任角色及关注点 |
| 信息化支撑 | 先以需求验证和边界澄清提供支持 | CLM-I-001 | 产品适配和交付范围尚未验证 | 中 | 仅讨论经授权能力并记录不适配项 |
| 最小推进动作 | {strategy_context['minimum_next_step']} | CLM-I-001 | 依赖客户确认后续沟通窗口 | 中 | 由账户负责人确认动作和完成日期 |

## 4. G-C-P 推演

| 模块 | 结论 | claim_id | 边界 | 置信度 |
|---|---|---|---|---|
| G：目标任务 | 当前优先验证数据治理真实任务 | CLM-I-001 | 尚无客户正式需求材料支持 | 中 |
| C：承接能力 | 仅讨论已授权的需求验证与方案边界 | CLM-I-001 | 不推断未核验产品能力和交付承诺 | 中 |
| P：政策与项目风险 | 预算、采购和项目窗口仍需核实 | CLM-I-001 | 不把公开规划写成当前采购事实 | 低 |

## 4.1 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/验证问题 |
|---|---|---|---|
| Budget | 预算来源和状态尚未获得可靠证据 | CLM-I-001 | 核实是否存在正式预算或采购安排 |
| Authority | 张主任的信息化职责已确认，其他角色未知 | CLM-L-001 | 核实业务、预算、采购和验收角色 |
| Need | 数据治理任务仍处于待客户验证状态 | CLM-I-001 | 确认任务、压力和可观察结果 |
| Timing/采购时序 | 当前没有可靠采购时序证据 | CLM-I-001 | 核实计划、审批及采购窗口 |
| 竞争位置 | 存量和竞争信息尚无可靠依据 | CLM-I-001 | 核实现有系统、供应商和切换约束 |

- 建议：monitor
- 投入强度：低；依据：核心任务、预算窗口和正式角色仍需验证
- 继续投入的前提/停止条件：确认真实任务及正式责任角色；无法确认时停止主动投入

## 4.2 执行与下一步

| action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 继续/调整/no-go条件 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|
| {strategy_context['minimum_next_step']} | observe | customer_contact | none | {action_owner} | 2026-09-25 | 客户确认沟通窗口 | 形成书面验证结论 | 无法确认真实任务时转为观察或停止 | 是 |

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | {summary} | 测试负责人 |
"""
    if not include_leader:
        total_body = total_body.replace("CLM-L-001", "CLM-I-001").replace(
            "张主任", "信息化责任角色"
        )
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
    selected_modules = ["institution", "strategy"]
    if include_leader:
        selected_modules.insert(1, "leader")
    _install_machine_bundle(workspace, selected_modules)
    _rebuild_manifest(workspace, selected_modules)
    _install_candidate_attestation_audit(workspace)
    return workspace
