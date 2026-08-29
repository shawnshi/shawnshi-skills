from __future__ import annotations

import importlib.util
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
CONFIG = SKILL_ROOT / "config" / "business-modes.json"
TEST_REQUEST_ISSUER = "discovery-call-test-host"
TEST_REQUEST_KEY_ID = "intake-test-key-1"
TEST_REQUEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
TEST_REQUEST_PUBLIC_KEY = base64.b64encode(
    TEST_REQUEST_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
).decode("ascii")
os.environ["DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON"] = json.dumps(
    {TEST_REQUEST_ISSUER: {TEST_REQUEST_KEY_ID: TEST_REQUEST_PUBLIC_KEY}},
    separators=(",", ":"),
)
TEST_CANDIDATE_ISSUER = "discovery-call-test-candidate-host"
TEST_CANDIDATE_KEY_ID = "candidate-test-key-1"
TEST_CANDIDATE_PRIVATE_KEY = Ed25519PrivateKey.generate()
TEST_CANDIDATE_PUBLIC_KEY = base64.b64encode(
    TEST_CANDIDATE_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
).decode("ascii")
os.environ["DISCOVERY_CALL_CANDIDATE_TRUSTED_KEYS_JSON"] = json.dumps(
    {TEST_CANDIDATE_ISSUER: {TEST_CANDIDATE_KEY_ID: TEST_CANDIDATE_PUBLIC_KEY}},
    separators=(",", ":"),
)


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso(value) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def signed_safety_directive(
    raw_text: str,
    surface: str,
    risk_code: str,
    *,
    assertion_status: str = "asserted",
    occurrence: int = 1,
) -> dict:
    starts = [match.start() for match in re.finditer(re.escape(surface), raw_text)]
    if occurrence < 1 or len(starts) < occurrence:
        raise ValueError(f"surface occurrence not found: {surface!r} #{occurrence}")
    start = starts[occurrence - 1]
    directive = {
        "directive_id": f"safety-{risk_code}-{occurrence}",
        "risk_code": risk_code,
        "assertion_status": assertion_status,
        "source_event_id": "test-user-event-001",
        "char_start": start,
        "char_end": start + len(surface),
        "surface_sha256": hashlib.sha256(surface.encode("utf-8")).hexdigest(),
        "source_ref": "test:user-turn:1",
    }
    if risk_code in {"unauthorized_patient_information", "unauthorized_internal_source"}:
        directive["material_scope_sha256"] = hashlib.sha256(
            f"material-scope|{risk_code}".encode("utf-8")
        ).hexdigest()
    return directive


_TEST_FIELD_SLOTS = {
    "customer_name": "organization",
    "organization_scope": "organization",
    "target_person": "person",
    "recipient_identity": "person",
    "target_role": "role",
    "target_contact_level": "role",
    "recipient_role": "role",
    "meeting_time": "meeting_time",
    "project_id": "project_id",
    "meeting_status": "meeting_status",
    "visit_objective": "visit_objective",
    "minimum_next_step": "minimum_next_step",
    "strategic_question": "strategic_question",
    "planning_horizon": "planning_horizon",
    "letter_scenario": "letter_scenario",
    "letter_purpose": "letter_purpose",
    "expected_action": "expected_action",
    "signer": "signer",
    "delivery_channel": "delivery_channel",
}
_TEST_SLOT_FIELDS = {
    slot: tuple(field for field, candidate_slot in _TEST_FIELD_SLOTS.items() if candidate_slot == slot)
    for slot in set(_TEST_FIELD_SLOTS.values())
}


def _test_binding_values_match(mention: dict, candidate_value: dict) -> bool:
    mention_status = mention.get("assertion_status")
    if mention_status != candidate_value.get("status"):
        return False
    if mention_status == "explicit_unknown":
        return candidate_value.get("value") is None
    if mention_status != "asserted":
        return False
    left = mention.get("normalized_value")
    right = candidate_value.get("value")
    if isinstance(left, dict) and isinstance(right, dict):
        if left.get("start") != right.get("start"):
            return False
        return not left.get("end") or left.get("end") == right.get("end")
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    normalize = lambda value: re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", value)
    ).strip().casefold()
    return normalize(left) == normalize(right)


def _test_enrich_candidate_bindings(payload: dict, mentions: list[dict]) -> list[dict]:
    """Emulate a v2 host extractor; production never infers these bindings.

    Legacy fixtures without ``candidate_field`` are expanded into distinct,
    field-scoped mention IDs.  Security tests provide ``candidate_field`` and
    ``mention_ids`` explicitly, so this compatibility path cannot repair or
    hide a deliberately reused ID.
    """
    candidate_sets = {
        str(item.get("field")): item.get("candidates", [])
        for item in payload.get("candidate_sets", [])
        if isinstance(item, dict)
    }
    mode = str(payload.get("business_mode", ""))
    default_fields = {
        "organization": "customer_name",
        "person": "recipient_identity" if mode == "letter" else "target_person",
        "role": "recipient_role" if mode == "letter" else "target_role",
    }
    enriched: list[dict] = []
    used_ids: set[str] = set()
    for raw_mention in mentions:
        mention = dict(raw_mention)
        slot = str(mention.get("semantic_slot", ""))
        explicit_field = mention.get("candidate_field")
        if isinstance(explicit_field, str) and explicit_field:
            target_fields = [explicit_field]
        else:
            target_fields = [
                field
                for field in _TEST_SLOT_FIELDS.get(slot, ())
                if any(
                    isinstance(candidate_value, dict)
                    and _test_binding_values_match(mention, candidate_value)
                    for candidate_value in candidate_sets.get(field, [])
                )
            ]
            if not target_fields:
                target_fields = [default_fields.get(slot, slot)]
        for index, field in enumerate(dict.fromkeys(target_fields)):
            bound = dict(mention)
            bound["candidate_field"] = field
            original_id = str(bound.get("mention_id", "mention-test"))
            if index or original_id in used_ids:
                suffix = hashlib.sha256(
                    _canonical_json({"mention": mention, "field": field, "index": index}).encode("utf-8")
                ).hexdigest()[:20]
                bound["mention_id"] = f"mention-bind-{suffix}"
            used_ids.add(str(bound["mention_id"]))
            enriched.append(bound)

    for field, candidates in candidate_sets.items():
        if not isinstance(candidates, list):
            continue
        for candidate_value in candidates:
            if not isinstance(candidate_value, dict) or "mention_ids" in candidate_value:
                continue
            candidate_value["mention_ids"] = sorted(
                str(mention["mention_id"])
                for mention in enriched
                if mention.get("candidate_field") == field
                and _test_binding_values_match(mention, candidate_value)
            )
    return enriched


def bind_intake_payload(
    path: Path,
    payload: dict,
    *,
    raw_text: str | None = None,
    mentions: list[dict] | None = None,
    safety_directives: list[dict] | None = None,
) -> Path:
    """Test-only host signer. Production Skill contains verification only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    request_id = str(payload.get("request_id") or "test-request-001")
    payload["request_id"] = request_id
    payload["schema"] = "discovery-call-intake/v3"
    event_id = "test-user-event-001"
    generated_mentions: list[dict] = []
    if raw_text is None:
        parts: list[str] = []
        for candidate_set in payload.get("candidate_sets", []):
            field = candidate_set.get("field") if isinstance(candidate_set, dict) else None
            slot = _TEST_FIELD_SLOTS.get(field)
            if slot is None:
                continue
            for candidate_value in candidate_set.get("candidates", []):
                if not isinstance(candidate_value, dict) or candidate_value.get("status") != "asserted":
                    continue
                value = candidate_value.get("value")
                if slot == "meeting_time":
                    if not isinstance(value, dict) or not isinstance(value.get("start"), str):
                        continue
                    surface = value["start"]
                    normalized_value = {
                        key: value[key]
                        for key in ("start", "end", "timezone")
                        if key in value and value[key] not in {None, ""}
                    }
                else:
                    if not isinstance(value, str) or not value:
                        continue
                    surface = value
                    normalized_value = value
                prefix = f"{field}: "
                start = sum(len(part) for part in parts) + len(prefix)
                line = prefix + surface + "\n"
                parts.append(line)
                generated_mentions.append(
                    {
                        "mention_id": f"mention-{len(generated_mentions) + 1:03d}",
                        "semantic_slot": slot,
                        "candidate_field": field,
                        "source_event_id": event_id,
                        "char_start": start,
                        "char_end": start + len(surface),
                        "surface_sha256": hashlib.sha256(surface.encode("utf-8")).hexdigest(),
                        "normalized_value": normalized_value,
                        "assertion_status": "asserted",
                        "source_ref": str(candidate_value.get("source_ref") or "test:user-turn:1"),
                    }
                )
        raw_text = "".join(parts) or "测试请求：未提供高影响提及。\n"
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    if mentions is None:
        mentions = generated_mentions
    mentions = _test_enrich_candidate_bindings(payload, mentions)
    if safety_directives is None:
        safety_directives = []
    raw_bytes = raw_text.encode("utf-8")
    raw_digest = hashlib.sha256(raw_bytes).hexdigest()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    def selected_text(field: str) -> str:
        for candidate_set in payload.get("candidate_sets", []):
            if isinstance(candidate_set, dict) and candidate_set.get("field") == field:
                values = [
                    item.get("value")
                    for item in candidate_set.get("candidates", [])
                    if isinstance(item, dict) and item.get("status") == "asserted"
                ]
                if len(values) == 1 and isinstance(values[0], str):
                    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", values[0])).strip()
        return ""
    customer_name = selected_text("customer_name")
    organization_scope = selected_text("organization_scope") or customer_name
    if "subject_resolution" not in payload:
        canonical_entity_key = "test-entity-" + hashlib.sha256(customer_name.encode("utf-8")).hexdigest()[:16]
        jurisdiction = "test-jurisdiction"
        subject_sha = hashlib.sha256(
            _canonical_json(
                {
                    "canonical_customer_name": customer_name,
                    "canonical_entity_key": canonical_entity_key,
                    "jurisdiction": jurisdiction,
                }
            ).encode("utf-8")
        ).hexdigest()
        payload["subject_resolution"] = {
            "schema": "discovery-call-subject-resolution/v1",
            "attestation_id": "subject-resolution-" + subject_sha[:16],
            "issuer": TEST_REQUEST_ISSUER,
            "customer_id": "cust-" + subject_sha[:12],
            "canonical_customer_name": customer_name,
            "canonical_entity_key": canonical_entity_key,
            "jurisdiction": jurisdiction,
            "canonical_subject_sha256": subject_sha,
            "organization_scope_sha256": hashlib.sha256(organization_scope.encode("utf-8")).hexdigest(),
            "id_source": "canonical_derived",
            "evidence_sha256": hashlib.sha256(("test-subject-evidence|" + customer_name).encode("utf-8")).hexdigest(),
            "issued_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(hours=1)),
        }
    payload.setdefault("safety_authorizations", [])
    receipt_id = "request-receipt-" + hashlib.sha256((request_id + raw_digest).encode("utf-8")).hexdigest()[:16]
    bundle_id = "request-bundle-" + hashlib.sha256(raw_bytes).hexdigest()[:16]
    for authorization in payload["safety_authorizations"]:
        if not isinstance(authorization, dict):
            continue
        risk_code = str(authorization.get("risk_code", ""))
        authorization.setdefault("request_bundle_id", bundle_id)
        authorization.setdefault("request_revision", 1)
        authorization.setdefault(
            "material_scope_sha256",
            hashlib.sha256(f"material-scope|{risk_code}".encode("utf-8")).hexdigest(),
        )
    raw_path = path.with_name("request-" + path.stem + ".txt")
    receipt_path = path.with_name("request-receipt-" + path.stem + ".json")
    receipt = {
        "schema": "discovery-call-request-binding-receipt/v2",
        "issuer": TEST_REQUEST_ISSUER,
        "audience": "discovery-call-request-binding",
        "key_id": TEST_REQUEST_KEY_ID,
        "receipt_id": receipt_id,
        "issued_at": _iso(now - timedelta(minutes=1)),
        "expires_at": _iso(now + timedelta(hours=1)),
        "request_id": request_id,
        "business_mode": payload["business_mode"],
        "request_actor_id": "test-user-001",
        "request_bundle_id": bundle_id,
        "request_revision": 1,
        "ordered_request_event_ids": [event_id],
        "last_user_event_id": event_id,
        "capture_method": "authenticated_host_message_bundle",
        "normalization_method": "unicode-nfc-lf-utf8/v1",
        "raw_request_sha256": raw_digest,
        "raw_request_length": len(raw_bytes),
        "attachment_manifest_sha256": hashlib.sha256(b"[]").hexdigest(),
        "attachment_count": 0,
        "mention_ledger_sha256": hashlib.sha256(_canonical_json(mentions).encode("utf-8")).hexdigest(),
        "subject_resolution_sha256": hashlib.sha256(_canonical_json(payload["subject_resolution"]).encode("utf-8")).hexdigest(),
        "safety_authorizations_sha256": hashlib.sha256(_canonical_json(payload["safety_authorizations"]).encode("utf-8")).hexdigest(),
        "mention_count": len(mentions),
        "extractor_id": "test-host-extractor",
        "extractor_version": "1.0.0",
        "extraction_policy_sha256": hashlib.sha256(b"test-policy-v1").hexdigest(),
        "coverage_policy": "discovery-call-high-impact-occurrences/v2",
        "coverage_complete": True,
        "mentions": mentions,
        "safety_directive_policy": "discovery-call-letter-safety-directives/v1",
        "safety_coverage_complete": True,
        "safety_directives_sha256": hashlib.sha256(_canonical_json(safety_directives).encode("utf-8")).hexdigest(),
        "safety_directive_count": len(safety_directives),
        "safety_directives": safety_directives,
    }
    signature_payload = {key: receipt[key] for key in sorted(receipt)}
    receipt["signature"] = base64.b64encode(
        TEST_REQUEST_PRIVATE_KEY.sign(_canonical_json(signature_payload).encode("utf-8"))
    ).decode("ascii")
    payload["request_binding"] = {
        "receipt_id": receipt_id,
        "request_bundle_id": bundle_id,
        "request_revision": 1,
        "raw_request_sha256": raw_digest,
        "raw_request_file": raw_path.name,
        "receipt_file": receipt_path.name,
    }
    raw_path.write_text(raw_text, encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.environ["DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON"] = _canonical_json(
        {
            "request_id": receipt["request_id"],
            "business_mode": receipt["business_mode"],
            "receipt_id": receipt["receipt_id"],
            "request_bundle_id": receipt["request_bundle_id"],
            "request_revision": receipt["request_revision"],
            "last_user_event_id": receipt["last_user_event_id"],
            "raw_request_sha256": receipt["raw_request_sha256"],
        }
    )
    return path


def test_intake_gate(
    business_mode: str,
    *,
    at: datetime,
    customer_name: str = "示例医院",
    organization_scope: str = "示例医院主院区",
    customer_id: str = "customer.demo",
) -> dict[str, object]:
    """Stable bound-gate shape for pure plan-builder unit tests."""
    seed = hashlib.sha256(f"{business_mode}|{at.isoformat()}".encode("utf-8")).hexdigest()
    canonical_name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", customer_name)).strip()
    canonical_scope = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", organization_scope)).strip()
    canonical_entity_key = "test-entity-" + hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()[:16]
    jurisdiction = "test-jurisdiction"
    subject_sha = hashlib.sha256(
        _canonical_json(
            {
                "canonical_customer_name": canonical_name,
                "canonical_entity_key": canonical_entity_key,
                "jurisdiction": jurisdiction,
            }
        ).encode("utf-8")
    ).hexdigest()
    subject_resolution = {
        "schema": "discovery-call-subject-resolution/v1",
        "attestation_id": "subject-resolution-test-001",
        "issuer": TEST_REQUEST_ISSUER,
        "customer_id": customer_id,
        "canonical_customer_name": canonical_name,
        "canonical_entity_key": canonical_entity_key,
        "jurisdiction": jurisdiction,
        "canonical_subject_sha256": subject_sha,
        "organization_scope_sha256": hashlib.sha256(canonical_scope.encode("utf-8")).hexdigest(),
        "id_source": "host_attested_external",
        "evidence_sha256": hashlib.sha256(b"test-subject-resolution").hexdigest(),
        "issued_at": _iso(at - timedelta(minutes=1)),
        "expires_at": _iso(at + timedelta(hours=1)),
    }
    return {
        "gate_id": "dcg-" + seed[:16],
        "input_sha256": seed,
        "business_mode": business_mode,
        "evaluated_at": _iso(at),
        "expires_at": _iso(at + timedelta(minutes=30)),
        "request_binding_receipt_id": "request-receipt-test-001",
        "request_binding_receipt_sha256": hashlib.sha256(b"request-receipt-test-001").hexdigest(),
        "request_bundle_id": "request-bundle-test-001",
        "request_revision": 1,
        "raw_request_sha256": hashlib.sha256(b"test-raw-request").hexdigest(),
        "mention_ledger_sha256": hashlib.sha256(b"test-mention-ledger").hexdigest(),
        "subject_resolution_sha256": hashlib.sha256(_canonical_json(subject_resolution).encode("utf-8")).hexdigest(),
        "safety_authorizations_sha256": hashlib.sha256(b"[]").hexdigest(),
        "safety_directives_sha256": hashlib.sha256(b"[]").hexdigest(),
        "subject_resolution": subject_resolution,
        "safety_authorization_codes": [],
    }


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


research_plan = load_module("discovery_call_research_plan", SCRIPTS / "research_plan.py")
runtime_tx = load_module("runtime_tx", SCRIPTS / "runtime_tx.py")
governance = load_module("governance", SCRIPTS / "governance.py")
candidate_attestation = sys.modules["candidate_attestation"]
validate_outputs = load_module("validate_outputs", SCRIPTS / "validate_outputs.py")


def refresh_candidate_seal_request(candidate: Path) -> Path:
    """Refresh unsigned local seal metadata after a test mutates the candidate."""
    marker_path = candidate / candidate_attestation.MARKER_REL
    manifest_path = candidate / candidate_attestation.MANIFEST_REL
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["schema"] = candidate_attestation.MARKER_SCHEMA
    marker.pop("payload_sha256", None)
    marker["final_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    marker_path.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    request_path, _ = candidate_attestation.write_seal_request(candidate)
    return request_path


def attest_candidate(
    candidate: Path,
    *,
    at: datetime | None = None,
    run_id: str | None = None,
    final_manifest_sha256: str | None = None,
) -> Path:
    """TEST ONLY: emulate a protected host signer; production code never holds this key."""
    request_path = refresh_candidate_seal_request(candidate)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if run_id is not None:
        request["run_id"] = run_id
    if final_manifest_sha256 is not None:
        request["final_manifest_sha256"] = final_manifest_sha256
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    nonce_seed = os.urandom(24)
    envelope = {
        **request,
        "schema": candidate_attestation.ATTESTATION_SCHEMA,
        "issuer": TEST_CANDIDATE_ISSUER,
        "key_id": TEST_CANDIDATE_KEY_ID,
        "attestation_id": "candidate-attestation-" + hashlib.sha256(nonce_seed).hexdigest()[:20],
        "issued_at": _iso(now - timedelta(minutes=1)),
        "expires_at": _iso(now + timedelta(minutes=5)),
        "host_authorized_at": _iso(now),
        "session_id": "candidate-session-" + hashlib.sha256(nonce_seed).hexdigest()[:20],
        "nonce": base64.urlsafe_b64encode(nonce_seed).decode("ascii").rstrip("="),
    }
    envelope["signature"] = base64.b64encode(
        TEST_CANDIDATE_PRIVATE_KEY.sign(
            candidate_attestation.canonical_bytes(envelope)
        )
    ).decode("ascii")
    target = candidate / "runtime" / "candidate-attestation.json"
    target.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def run_python(
    script: str,
    args: Sequence[str],
    *,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env["PYTHONDONTWRITEBYTECODE"] = "1"
    argument_list = [str(item) for item in args]
    intake_value: str | None = None
    if "--intake-input" in argument_list:
        index = argument_list.index("--intake-input")
        if index + 1 < len(argument_list):
            intake_value = argument_list[index + 1]
    elif script == "preflight_intake.py" and argument_list and argument_list[0] != "-":
        intake_value = argument_list[0]
    if intake_value:
        try:
            intake_path = Path(intake_value)
            intake_payload = json.loads(intake_path.read_text(encoding="utf-8"))
            binding = intake_payload.get("request_binding", {})
            receipt_path = intake_path.parent / str(binding.get("receipt_file", ""))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            process_env["DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON"] = _canonical_json(
                {
                    "request_id": receipt["request_id"],
                    "business_mode": receipt["business_mode"],
                    "receipt_id": receipt["receipt_id"],
                    "request_bundle_id": receipt["request_bundle_id"],
                    "request_revision": receipt["request_revision"],
                    "last_user_event_id": receipt["last_user_event_id"],
                    "raw_request_sha256": receipt["raw_request_sha256"],
                }
            )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            pass
    if env:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / script), *argument_list],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=process_env,
        check=False,
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_intake(
    directory: Path,
    customer_name: str,
    business_mode: str,
    *,
    organization_scope: str | None = None,
    conflicting_role: bool = False,
    letter_recipient_role: str = "信息中心主任",
) -> Path:
    """Write a deterministic ready intake, or a deliberately blocked role conflict."""
    candidate_sets = [
        {
            "field": "customer_name",
            "candidates": [
                {
                    "candidate_id": "customer-1",
                    "value": customer_name,
                    "status": "asserted",
                    "source_ref": "test:user-turn:1",
                }
            ],
        },
        {
            "field": "organization_scope",
            "candidates": [
                {
                    "candidate_id": "scope-1",
                    "value": organization_scope or customer_name,
                    "status": "asserted",
                    "source_ref": "test:user-turn:1",
                }
            ],
        },
    ]
    if business_mode in {"briefing", "standard_visit"}:
        role_candidates = [
            {
                "candidate_id": "role-1",
                "value": "信息中心主任",
                "status": "asserted",
                "source_ref": "test:user-turn:1",
            }
        ]
        if conflicting_role:
            role_candidates.append(
                {
                    "candidate_id": "role-2",
                    "value": "分管副院长",
                    "status": "asserted",
                    "source_ref": "test:attachment:1",
                }
            )
        candidate_sets.append({"field": "target_role", "candidates": role_candidates})
        candidate_sets.extend(
            [
                {
                    "field": "visit_objective",
                    "candidates": [{"candidate_id": "objective-1", "value": "核实客户核心任务", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "minimum_next_step",
                    "candidates": [{"candidate_id": "step-1", "value": "确认下一次技术交流", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
            ]
        )
    if business_mode == "strategic_account":
        candidate_sets.extend(
            [
                {
                    "field": "strategy_variant",
                    "candidates": [{"candidate_id": "variant-1", "value": "account_planning", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "strategic_question",
                    "candidates": [{"candidate_id": "question-1", "value": "未来90天是否值得持续投入", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "planning_horizon",
                    "candidates": [{"candidate_id": "horizon-1", "value": "90天", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "minimum_next_step",
                    "candidates": [{"candidate_id": "step-1", "value": "完成机会资格复核", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
            ]
        )
    if business_mode == "letter":
        candidate_sets.extend(
            [
                {
                    "field": "recipient_role",
                    "candidates": [{"candidate_id": "recipient-1", "value": letter_recipient_role, "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "letter_scenario",
                    "candidates": [{"candidate_id": "scenario-1", "value": "拜访后正式跟进", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "letter_purpose",
                    "candidates": [{"candidate_id": "purpose-1", "value": "确认下一次技术交流安排", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "expected_action",
                    "candidates": [{"candidate_id": "action-1", "value": "确认九月技术交流时间", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "signer",
                    "candidates": [{"candidate_id": "signer-1", "value": "战略咨询部", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "delivery_channel",
                    "candidates": [{"candidate_id": "channel-1", "value": "正式邮件", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
            ]
        )
    payload = {
        "schema": "discovery-call-intake/v2",
        "request_id": "test-request-001",
        "business_mode": business_mode,
        "candidate_sets": candidate_sets,
        "confirmations": [],
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"intake-{business_mode}-{time.time_ns()}.json"
    return bind_intake_payload(path, payload)
