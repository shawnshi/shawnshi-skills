from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import (
    CONFIG,
    SCRIPTS,
    TEST_REQUEST_ISSUER,
    bind_intake_payload,
    load_module,
    run_python,
    signed_safety_directive,
)
from tests.fixture_builder import build_pending_letter_workspace


preflight = load_module("discovery_call_preflight_intake_p2_contracts", SCRIPTS / "preflight_intake.py")
validator = load_module("discovery_call_validate_outputs_p2_contracts", SCRIPTS / "validate_outputs.py")
initializer = load_module("discovery_call_init_workspace_p2_contracts", SCRIPTS / "init_workspace.py")


RISK_CODES = (
    "fabricated_approval",
    "unauthorized_patient_information",
    "unauthorized_internal_source",
    "unverified_delivery_timeline",
    "unverified_outcome_claim",
    "unapproved_price_cap",
    "direct_external_send",
    "nonhuman_accountability",
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _candidate(candidate_id: str, value: str, source_ref: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "value": value,
        "status": "asserted",
        "source_ref": source_ref,
    }


def _candidate_set(field: str, candidate_id: str, value: str) -> dict[str, object]:
    return {
        "field": field,
        "candidates": [_candidate(candidate_id, value, f"test:user-turn:1#{field}")],
    }


def _signed_mention(
    raw_text: str,
    surface: str,
    semantic_slot: str,
    normalized_value: str,
    *,
    occurrence: int = 1,
) -> dict[str, object]:
    starts: list[int] = []
    offset = 0
    while True:
        start = raw_text.find(surface, offset)
        if start < 0:
            break
        starts.append(start)
        offset = start + len(surface)
    if occurrence < 1 or occurrence > len(starts):
        raise ValueError(f"surface occurrence not found: {surface!r} #{occurrence}")
    start = starts[occurrence - 1]
    return {
        "mention_id": f"mention-{semantic_slot}-{occurrence}-{start}",
        "semantic_slot": semantic_slot,
        "source_event_id": "test-user-event-001",
        "char_start": start,
        "char_end": start + len(surface),
        "surface_sha256": hashlib.sha256(surface.encode("utf-8")).hexdigest(),
        "normalized_value": normalized_value,
        "assertion_status": "asserted",
        "source_ref": f"test:user-turn:1#chars={start}-{start + len(surface)}",
    }


def _subject_resolution(
    customer_name: str,
    organization_scope: str,
    *,
    entity_key: str,
    jurisdiction: str,
    id_source: str = "canonical_derived",
    customer_id: str | None = None,
) -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    subject_sha = hashlib.sha256(
        _canonical_json(
            {
                "canonical_customer_name": customer_name,
                "canonical_entity_key": entity_key,
                "jurisdiction": jurisdiction,
            }
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "discovery-call-subject-resolution/v1",
        "attestation_id": "subject-resolution-" + hashlib.sha256(
            f"{entity_key}|{jurisdiction}".encode("utf-8")
        ).hexdigest()[:16],
        "issuer": TEST_REQUEST_ISSUER,
        "customer_id": customer_id or "cust-" + subject_sha[:12],
        "canonical_customer_name": customer_name,
        "canonical_entity_key": entity_key,
        "jurisdiction": jurisdiction,
        "canonical_subject_sha256": subject_sha,
        "organization_scope_sha256": hashlib.sha256(organization_scope.encode("utf-8")).hexdigest(),
        "id_source": id_source,
        "evidence_sha256": hashlib.sha256(
            f"subject-evidence|{entity_key}|{jurisdiction}".encode("utf-8")
        ).hexdigest(),
        "issued_at": _iso(now - timedelta(minutes=1)),
        "expires_at": _iso(now + timedelta(hours=1)),
    }


def _letter_payload(
    *,
    customer_name: str = "甲市中心医院",
    organization_scope: str | None = None,
    subject_resolution: dict[str, object] | None = None,
    safety_authorizations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    scope = organization_scope or customer_name
    payload: dict[str, object] = {
        "schema": "discovery-call-intake/v3",
        "request_id": "p2-letter-contract-001",
        "business_mode": "letter",
        "candidate_sets": [
            _candidate_set("customer_name", "customer-1", customer_name),
            _candidate_set("organization_scope", "scope-1", scope),
            _candidate_set("recipient_role", "recipient-role-1", "信息中心主任｜身份已确认"),
            _candidate_set("letter_scenario", "scenario-1", "项目合作正式跟进"),
            _candidate_set("letter_purpose", "purpose-1", "请求确认项目启动安排"),
            _candidate_set("expected_action", "action-1", "确认下一次项目会议时间"),
            _candidate_set("signer", "signer-1", "王经理，客户负责人"),
            _candidate_set("delivery_channel", "channel-1", "正式电子邮件"),
        ],
        "confirmations": [],
    }
    if subject_resolution is not None:
        payload["subject_resolution"] = subject_resolution
    if safety_authorizations is not None:
        payload["safety_authorizations"] = safety_authorizations
    return payload


def _letter_raw_and_mentions(
    *,
    customer_surface: str = "甲市中心医院",
    scope_surface: str = "甲市中心医院",
    canonical_customer_name: str = "甲市中心医院",
    canonical_scope: str = "甲市中心医院",
    alias_context: str = "",
    unsafe_lines: tuple[str, ...] = (),
) -> tuple[str, list[dict[str, object]]]:
    fields = (
        ("客户", customer_surface, "organization", canonical_customer_name),
        ("机构范围", scope_surface, "organization", canonical_scope),
        ("收件角色", "信息中心主任｜身份已确认", "recipient_role", "信息中心主任｜身份已确认"),
        ("信件场景", "项目合作正式跟进", "letter_scenario", "项目合作正式跟进"),
        ("发信目的", "请求确认项目启动安排", "letter_purpose", "请求确认项目启动安排"),
        ("期望动作", "确认下一次项目会议时间", "expected_action", "确认下一次项目会议时间"),
        ("签署人", "王经理，客户负责人", "signer", "王经理，客户负责人"),
        ("发送渠道", "正式电子邮件", "delivery_channel", "正式电子邮件"),
    )
    raw_text = (f"用户输入别名：{alias_context}\n" if alias_context else "")
    raw_text += "".join(f"{label}：{surface}\n" for label, surface, _, _ in fields)
    raw_text += "".join(line + "\n" for line in unsafe_lines)
    seen: dict[str, int] = {}
    mentions: list[dict[str, object]] = []
    for _, surface, slot, normalized in fields:
        seen[surface] = seen.get(surface, 0) + 1
        mentions.append(
            _signed_mention(
                raw_text,
                surface,
                slot,
                normalized,
                occurrence=seen[surface],
            )
        )
    return raw_text, mentions


def _safety_authorizations(subject_sha: str) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return [
        {
            "schema": "discovery-call-safety-authorization/v1",
            "authorization_id": f"source-auth-{index}",
            "issuer": TEST_REQUEST_ISSUER,
            "risk_code": risk_code,
            "subject_sha256": subject_sha,
            "purpose": "internal_review_draft",
            "external_allowed": False,
            "evidence_sha256": hashlib.sha256(f"authorization|{risk_code}".encode("utf-8")).hexdigest(),
            "issued_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(hours=1)),
        }
        for index, risk_code in enumerate(
            ("unauthorized_patient_information", "unauthorized_internal_source"), 1
        )
    ]


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class P2HighRiskLetterContractTests(unittest.TestCase):
    def test_diagnostic_extractor_keeps_negation_local_to_each_risk_predicate(self) -> None:
        samples = {
            "不要使用患者案例并务必承诺3个月上线。": {"unverified_delivery_timeline"},
            "不要使用患者案例却要求承诺3个月上线。": {"unverified_delivery_timeline"},
            "不要直接发送正式信只是要使用患者案例。": {"unauthorized_patient_information"},
            "不得使用患者数据反而要直接外发正式信。": {"direct_external_send"},
            "不承诺3个月上线却要直接发送正式信。": {"direct_external_send"},
            "不能虚构审批；也不能承诺3个月上线。": set(),
            "不使用患者案例，也不直接外发。": set(),
            "请勿直接发送，可生成内部待审核稿。": set(),
            "切勿直接发送。": set(),
            "勿直接发送。": set(),
            "不必直接发送。": set(),
            "不需要直接发送。": set(),
            "请勿使用患者案例。": set(),
            "切勿把审批人写成AI。": set(),
            "请勿直接发送，但请使用患者案例。": {"unauthorized_patient_information"},
            "请勿使用患者案例，但仍要承诺3个月上线。": {"unverified_delivery_timeline"},
            "无需审核直接发送正式信。": {"direct_external_send"},
            "不要保证效率提升30%但总价写明不超过500万元。": {"unapproved_price_cap"},
            "禁止写成已获批准，AI作为执行人即可。": {"nonhuman_accountability"},
            "不要写领导已批准，改由AI担任审批人。": {"nonhuman_accountability"},
            "患者案例不得外发却可以在内部待审核稿引用。": {"unauthorized_patient_information"},
        }
        for raw_text, expected in samples.items():
            with self.subTest(raw_text=raw_text):
                self.assertEqual(set(preflight.detect_high_risk_letter_requests(raw_text)), expected)

    def test_N126_T3_all_eight_signed_directives_block_three_times_with_fixed_response(self) -> None:
        unsafe = (
            ("请虚构已获领导批准。", "虚构已获领导批准", "fabricated_approval"),
            ("请使用患者案例。", "使用患者案例", "unauthorized_patient_information"),
            ("请使用内部邮件和CRM记录。", "使用内部邮件和CRM记录", "unauthorized_internal_source"),
            ("请承诺3个月上线。", "承诺3个月上线", "unverified_delivery_timeline"),
            ("请保证效率提升30%。", "保证效率提升30%", "unverified_outcome_claim"),
            ("请注明总价不超过500万元。", "注明总价不超过500万元", "unapproved_price_cap"),
            ("请直接发送。", "直接发送", "direct_external_send"),
            ("审批人和执行人写为AI。", "审批人和执行人写为AI", "nonhuman_accountability"),
        )
        observed: list[dict[str, object]] = []
        for repetition in range(3):
            with self.subTest(repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                raw_text, mentions = _letter_raw_and_mentions(
                    unsafe_lines=tuple(line for line, _, _ in unsafe)
                )
                directives = [
                    signed_safety_directive(raw_text, surface, risk_code)
                    for _, surface, risk_code in unsafe
                ]
                intake = bind_intake_payload(
                    root / "intake.json",
                    _letter_payload(),
                    raw_text=raw_text,
                    mentions=mentions,
                    safety_directives=directives,
                )
                before = _file_hashes(root)
                completed = run_python("preflight_intake.py", [str(intake)])
                self.assertEqual(completed.returncode, 3, completed.stderr or completed.stdout)
                result = json.loads(completed.stdout)
                response = result["high_risk_failure_response"]
                self.assertEqual(result["status"], "blocked")
                self.assertFalse(result["safe_to_initialize_or_search"])
                self.assertEqual(result["questions"], [])
                self.assertEqual(
                    response["response_sections"],
                    ["refused_items", "reasons", "permitted_scope", "required_materials", "approval_path"],
                )
                self.assertEqual(
                    {item["code"] for item in response["refused_items"]},
                    set(RISK_CODES),
                )
                scope = response["permitted_scope"]
                self.assertEqual(scope["artifact"], "internal_review_draft_only")
                self.assertIsNone(scope["internal_artifact_path"])
                self.assertEqual(scope["external_artifact_paths"], [])
                self.assertFalse(scope["external_version_allowed"])
                self.assertFalse(scope["automatic_send_allowed"])
                self.assertFalse(scope["send_attempted"])
                self.assertFalse(scope["ready_for_use"])
                self.assertNotIn("expires_at", result)
                self.assertEqual(_file_hashes(root), before)
                observed.append(
                    {
                        "status": result["status"],
                        "questions": result["questions"],
                        "response": response,
                    }
                )
        self.assertEqual(observed, [observed[0]] * 3)

    def _authorized_intake(self, path: Path, *, customer_name: str = "甲市中心医院") -> Path:
        subject = _subject_resolution(
            customer_name,
            customer_name,
            entity_key="hospital-cn-001",
            jurisdiction="CN-11",
            id_source="host_attested_external",
            customer_id="customer.demo",
        )
        payload = _letter_payload(
            customer_name=customer_name,
            organization_scope=customer_name,
            subject_resolution=subject,
            safety_authorizations=_safety_authorizations(str(subject["canonical_subject_sha256"])),
        )
        unsafe = (
            ("请仅在内部待审核稿使用已授权脱敏患者案例。", "使用已授权脱敏患者案例", "unauthorized_patient_information"),
            ("请仅在内部待审核稿使用当前项目已授权CRM记录。", "使用当前项目已授权CRM记录", "unauthorized_internal_source"),
        )
        raw_text, mentions = _letter_raw_and_mentions(
            customer_surface=customer_name,
            scope_surface=customer_name,
            canonical_customer_name=customer_name,
            canonical_scope=customer_name,
            unsafe_lines=tuple(line for line, _, _ in unsafe)
        )
        directives = [
            signed_safety_directive(raw_text, surface, risk_code)
            for _, surface, risk_code in unsafe
        ]
        return bind_intake_payload(
            path,
            payload,
            raw_text=raw_text,
            mentions=mentions,
            safety_directives=directives,
        )

    def test_internal_source_authorizations_are_ready_but_gate_remains_internal_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = self._authorized_intake(root / "intake.json")
            completed = run_python("preflight_intake.py", [str(intake)])
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["safe_to_initialize_or_search"])
            gate = preflight.verified_gate_record(result)
            self.assertEqual(
                gate["safety_authorization_codes"],
                ["unauthorized_internal_source", "unauthorized_patient_information"],
            )

    def test_unused_standing_source_authorizations_do_not_contaminate_public_letter_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subject = _subject_resolution(
                "甲市中心医院",
                "甲市中心医院",
                entity_key="hospital-cn-001",
                jurisdiction="CN-11",
                id_source="host_attested_external",
                customer_id="customer.demo",
            )
            payload = _letter_payload(
                subject_resolution=subject,
                safety_authorizations=_safety_authorizations(
                    str(subject["canonical_subject_sha256"])
                ),
            )
            raw_text, mentions = _letter_raw_and_mentions()
            intake = bind_intake_payload(
                root / "intake-public-letter.json",
                payload,
                raw_text=raw_text,
                mentions=mentions,
                safety_directives=[],
            )
            completed = run_python("preflight_intake.py", [str(intake)])
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(
                preflight.verified_gate_record(result)["safety_authorization_codes"],
                [],
            )

    def test_N131_source_authorization_cannot_cover_another_signed_material_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subject = _subject_resolution(
                "甲市中心医院",
                "甲市中心医院",
                entity_key="hospital-cn-001",
                jurisdiction="CN-11",
                id_source="host_attested_external",
                customer_id="customer.demo",
            )
            authorizations = _safety_authorizations(
                str(subject["canonical_subject_sha256"])
            )
            patient_authorization = next(
                item
                for item in authorizations
                if item["risk_code"] == "unauthorized_patient_information"
            )
            patient_authorization["material_scope_sha256"] = hashlib.sha256(
                b"another-patient-material-scope"
            ).hexdigest()
            raw_text, mentions = _letter_raw_and_mentions(
                unsafe_lines=("请仅在内部待审核稿使用已授权脱敏患者案例。",)
            )
            directive = signed_safety_directive(
                raw_text,
                "使用已授权脱敏患者案例",
                "unauthorized_patient_information",
            )
            intake = bind_intake_payload(
                root / "intake-mismatched-material.json",
                _letter_payload(
                    subject_resolution=subject,
                    safety_authorizations=authorizations,
                ),
                raw_text=raw_text,
                mentions=mentions,
                safety_directives=[directive],
            )
            before = _file_hashes(root)
            completed = run_python("preflight_intake.py", [str(intake)])
            self.assertEqual(completed.returncode, 2, completed.stderr or completed.stdout)
            self.assertIn("material_scope_sha256", completed.stderr)
            self.assertEqual(_file_hashes(root), before)

    def test_N127_internal_only_authorization_blocks_external_lifecycle_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = self._authorized_intake(
                root / "intake-letter-authorized.json",
                customer_name="示例医院",
            )
            with patch("tests.fixture_builder.write_intake", return_value=intake):
                workspace = build_pending_letter_workspace(root / "output")
            operations = (
                (
                    "approve",
                    [
                        "--approve-letter",
                        "--approver", "外发审批岗",
                        "--actor-id", "approver-test",
                        "--action-event-id", "approval-event-test",
                    ],
                    "internal_review_draft_only",
                ),
                (
                    "emit",
                    [
                        "--emit-external",
                        "--actor-id", "requester-test",
                        "--request-event-id", "external-request-test",
                    ],
                    "internal_review_draft_only",
                ),
                (
                    "mark-ready",
                    [
                        "--mark-ready",
                        "--reviewer", "就绪审核岗",
                        "--actor-id", "ready-test",
                        "--action-event-id", "ready-event-test",
                    ],
                    "internal_review_draft_only",
                ),
                (
                    "release",
                    ["--profile", "release"],
                    "internal_only_source_release_forbidden",
                ),
            )
            for name, args, expected in operations:
                for repetition in range(3):
                    with self.subTest(operation=name, repetition=repetition):
                        before = _file_hashes(workspace)
                        completed = run_python(
                            "validate_outputs.py",
                            [str(workspace), *args, "--json"],
                        )
                        self.assertEqual(completed.returncode, 1, completed.stderr or completed.stdout)
                        result = json.loads(completed.stdout)
                        serialized = json.dumps(result, ensure_ascii=False)
                        self.assertIn(expected, serialized)
                        self.assertEqual(_file_hashes(workspace), before)


class P2SubjectResolutionContractTests(unittest.TestCase):
    def _bind_subject_intake(
        self,
        path: Path,
        subject: dict[str, object],
        *,
        customer_surface: str | None = None,
        scope_surface: str | None = None,
        alias_context: str = "",
    ) -> Path:
        canonical_name = str(subject["canonical_customer_name"])
        raw_text, mentions = _letter_raw_and_mentions(
            customer_surface=customer_surface or canonical_name,
            scope_surface=scope_surface or canonical_name,
            canonical_customer_name=canonical_name,
            canonical_scope=canonical_name,
            alias_context=alias_context,
        )
        payload = _letter_payload(
            customer_name=canonical_name,
            organization_scope=canonical_name,
            subject_resolution=subject,
        )
        return bind_intake_payload(path, payload, raw_text=raw_text, mentions=mentions)

    def test_N128_same_name_different_entity_and_jurisdiction_have_distinct_derived_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subjects = [
                _subject_resolution(
                    "同名中心医院",
                    "同名中心医院",
                    entity_key="registry-cn-11-0001",
                    jurisdiction="CN-11",
                ),
                _subject_resolution(
                    "同名中心医院",
                    "同名中心医院",
                    entity_key="registry-cn-31-0009",
                    jurisdiction="CN-31",
                ),
            ]
            ids: list[str] = []
            for index, subject in enumerate(subjects):
                intake = self._bind_subject_intake(root / f"subject-{index}.json", subject)
                result = run_python("preflight_intake.py", [str(intake)])
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                output = json.loads(result.stdout)
                ids.append(output["subject_resolution"]["customer_id"])
            self.assertNotEqual(ids[0], ids[1])

    def test_two_alias_surfaces_resolve_to_same_host_attested_customer_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subject = _subject_resolution(
                "甲市第一人民医院",
                "甲市第一人民医院",
                entity_key="registry-hospital-8848",
                jurisdiction="CN-11",
                id_source="host_attested_external",
                customer_id="crm:account-8848",
            )
            outputs: list[dict[str, object]] = []
            for index, alias in enumerate(("甲市一院", "市第一医院")):
                intake = self._bind_subject_intake(
                    root / f"alias-{index}.json",
                    json.loads(json.dumps(subject, ensure_ascii=False)),
                    alias_context=alias,
                )
                result = run_python("preflight_intake.py", [str(intake)])
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                outputs.append(json.loads(result.stdout))
            self.assertEqual(
                {output["subject_resolution"]["customer_id"] for output in outputs},
                {"crm:account-8848"},
            )
            self.assertEqual(
                {output["subject_resolution"]["canonical_subject_sha256"] for output in outputs},
                {subject["canonical_subject_sha256"]},
            )

    def test_every_subject_field_is_covered_by_request_receipt_hash(self) -> None:
        mutations: dict[str, object] = {
            "schema": "discovery-call-subject-resolution/v999",
            "attestation_id": "subject-resolution-tampered",
            "issuer": "tampered-host",
            "customer_id": "crm-account-tampered",
            "canonical_customer_name": "被篡改医院",
            "canonical_entity_key": "tampered-entity-key",
            "jurisdiction": "CN-99",
            "canonical_subject_sha256": "f" * 64,
            "organization_scope_sha256": "e" * 64,
            "id_source": "canonical_derived",
            "evidence_sha256": "d" * 64,
            "issued_at": "2026-08-26T00:00:00Z",
            "expires_at": "2026-08-28T00:00:00Z",
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                subject = _subject_resolution(
                    "甲市中心医院",
                    "甲市中心医院",
                    entity_key="registry-hospital-0001",
                    jurisdiction="CN-11",
                    id_source="host_attested_external",
                    customer_id="crm-account-0001",
                )
                intake = self._bind_subject_intake(root / "intake.json", subject)
                payload = json.loads(intake.read_text(encoding="utf-8"))
                payload["subject_resolution"][field] = replacement
                intake.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                result = run_python("preflight_intake.py", [str(intake)])
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertIn("subject_resolution", result.stderr)

    def test_resume_cannot_rebind_same_external_id_to_another_subject_tuple(self) -> None:
        original = _subject_resolution(
            "同名中心医院",
            "同名中心医院",
            entity_key="registry-cn-11-0001",
            jurisdiction="CN-11",
            id_source="host_attested_external",
            customer_id="crm:shared-0001",
        )
        changed = _subject_resolution(
            "同名中心医院",
            "同名中心医院",
            entity_key="registry-cn-31-0009",
            jurisdiction="CN-31",
            id_source="host_attested_external",
            customer_id="crm:shared-0001",
        )
        manifest = {"subject_binding": original}
        initializer.assert_resume_subject_binding(manifest, {"subject_resolution": original})
        with self.assertRaisesRegex(initializer.InitError, "普通resume不得改绑"):
            initializer.assert_resume_subject_binding(manifest, {"subject_resolution": changed})
        with self.assertRaisesRegex(initializer.InitError, "受审计迁移"):
            initializer.assert_resume_subject_binding({}, {"subject_resolution": original})

    def test_N135_resume_subject_mismatch_fails_before_root_lock_or_any_tree_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "同名中心医院__dcx-abcd1234"
            (workspace / "runtime").mkdir(parents=True)
            original = _subject_resolution(
                "同名中心医院",
                "同名中心医院",
                entity_key="registry-cn-11-0001",
                jurisdiction="CN-11",
                id_source="host_attested_external",
                customer_id="crm:shared-0001",
            )
            (workspace / "runtime" / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "discovery-call-runtime/v1",
                        "context_id": "dcx-20260827-abcd1234",
                        "transaction_sequence": 1,
                        "subject_binding": original,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            changed = _subject_resolution(
                "同名中心医院",
                "同名中心医院",
                entity_key="registry-cn-31-0009",
                jurisdiction="CN-31",
                id_source="host_attested_external",
                customer_id="crm:shared-0001",
            )
            intake = self._bind_subject_intake(root / "changed.json", changed)
            args = initializer.build_parser().parse_args(
                [
                    "同名中心医院",
                    "--output-root", str(root),
                    "--resume",
                    "--context-id", "dcx-20260827-abcd1234",
                    "--business-mode", "letter",
                    "--intake-input", str(intake),
                ]
            )
            before = _file_hashes(root)
            with patch.object(initializer, "find_resume_workspace", return_value=workspace), patch.object(
                initializer,
                "output_root_lock",
                side_effect=AssertionError("root lock must not be touched"),
            ):
                with self.assertRaisesRegex(initializer.InitError, "普通resume不得改绑"):
                    initializer.initialize(args)
            self.assertEqual(_file_hashes(root), before)


def _briefing_body(
    *,
    decision: str = "建议=monitor；投入强度=低；边界=先核实客户任务与责任角色",
    action: str = "确认下一次技术交流",
    owner: str = "客户负责人",
    due_date: str = "2026-09-25",
    conclusion: str = "客户主体已经核实，本次应先验证核心任务与责任角色，再确认最小推进动作（CLM-I-001）。",
    pads: dict[str, str] | None = None,
    extra_risk_lines: int = 0,
) -> str:
    pad = {heading: "" for heading in (
        "会前必须知道", "机会与边界", "建议交流节奏", "三个现场问题", "最小推进动作", "未决风险"
    )}
    if pads:
        pad.update(pads)
    risk_lines = "\n".join(f"补充风险{i:02d}" for i in range(extra_risk_lines))
    return f"""# 示例医院会前速览

## 一句话判断

{conclusion}

## 会前必须知道

| 事实 | 事实类型与claim_id | 对本次拜访的意义 |
|---|---|---|
| 示例医院为本次研究主体 | F；CLM-I-001 | 可据此开展限定范围的拜访准备 |
补充说明：{pad['会前必须知道']}

## 机会与边界

| 项目 | 当前判断 | 依据claim_id |
|---|---|---|
| Need | 核心任务仍待核实 | CLM-I-001 |
| Authority | 责任角色仍待确认 | CLM-I-001 |
| Budget/Procurement | 预算采购状态未知 | CLM-I-001 |
| Competition | 存量供应商格局待核实 | CLM-I-001 |
| 建议 | {decision} | CLM-I-001 |
补充说明：{pad['机会与边界']}

## 建议交流节奏

| 时间 | 议题/动作 | 目标信号 |
|---|---|---|
| 0—5分钟 | 确认客户交流目标 | 客户确认或修正目标 |
| 5—20分钟 | 验证客户核心任务 | 获得具体任务反馈 |
| 20—25分钟 | 核实角色与采购边界 | 明确责任角色与未知事项 |
| 25—30分钟 | 确认后续技术交流安排 | 明确动作责任人与日期 |
补充说明：{pad['建议交流节奏']}

## 三个现场问题

1. 当前最需要优先解决的业务任务是什么？
2. 谁负责业务、技术、预算和采购决策？
3. 下一次技术交流应由谁在何时组织？
补充说明：{pad['三个现场问题']}

## 最小推进动作

- 动作：{action}
- 依据claim_id：CLM-I-001
- Owner：{owner}
- Due date：{due_date}
- 红线：未经授权不得承诺价格、效果或工期
补充说明：{pad['最小推进动作']}

## 未决风险

预算、采购时序和竞争格局均缺少证据，现场确认前不得作结论。
补充说明：{pad['未决风险']}
{risk_lines}
"""


def _briefing_document(body: str) -> object:
    return validator.Document(
        Path("示例医院会前速览.md"),
        body,
        {
            "artifact_type": "briefing_delivery",
            "module_status": "completed",
            "review_status": "pending",
            "page_proxy": "markdown-one-page/v1",
            "delivery_state": "draft_for_review",
        },
        body,
    )


def _briefing_codes(body: str) -> set[str]:
    issues: list[object] = []
    profiles = json.loads(CONFIG.read_text(encoding="utf-8"))["profiles"]
    with patch.object(validator, "load_business_profiles", return_value=profiles):
        validator.validate_briefing_contract(_briefing_document(body), issues)
    return {issue.code for issue in issues}


def _body_at_visible_budget(target: int) -> str:
    headings = (
        "会前必须知道", "机会与边界", "建议交流节奏", "三个现场问题", "最小推进动作", "未决风险"
    )
    pads = {heading: "" for heading in headings}
    body = _briefing_body(pads=pads)
    remaining = target - len(validator.normalize_evidence_text(body))
    if remaining < 0:
        raise AssertionError("base briefing already exceeds target")
    for heading in headings:
        body = _briefing_body(pads=pads)
        sections = validator.h2_sections(body)
        current = len(validator.normalize_evidence_text(sections[heading][0]))
        capacity = 900 - current
        take = min(remaining, capacity)
        pads[heading] = "甲" * take
        remaining -= take
        if remaining == 0:
            break
    body = _briefing_body(pads=pads)
    if remaining or len(validator.normalize_evidence_text(body)) != target:
        raise AssertionError("unable to construct exact visible-character boundary")
    return body


def _body_at_line_budget(target: int) -> str:
    base = _briefing_body()
    count = len([line for line in base.splitlines() if line.strip()])
    if count > target:
        raise AssertionError("base briefing already exceeds line target")
    body = _briefing_body(extra_risk_lines=target - count)
    if len([line for line in body.splitlines() if line.strip()]) != target:
        raise AssertionError("unable to construct exact line boundary")
    return body


def _body_at_section_budget(target: int) -> str:
    body = _briefing_body()
    current = len(validator.normalize_evidence_text(validator.h2_sections(body)["未决风险"][0]))
    if current > target:
        raise AssertionError("base risk section already exceeds target")
    body = _briefing_body(pads={"未决风险": "甲" * (target - current)})
    if len(validator.normalize_evidence_text(validator.h2_sections(body)["未决风险"][0])) != target:
        raise AssertionError("unable to construct exact section boundary")
    return body


def _body_at_conclusion_budget(target: int) -> str:
    base = "客户主体已经核实，应先验证核心任务与责任角色（CLM-I-001）"
    current = len(validator.normalize_evidence_text(base))
    if current > target:
        raise AssertionError("base conclusion already exceeds target")
    conclusion = base + "甲" * (target - current)
    body = _briefing_body(conclusion=conclusion)
    actual = len(
        validator.normalize_evidence_text(validator.h2_sections(body)["一句话判断"][0])
    )
    if actual != target:
        raise AssertionError("unable to construct exact conclusion boundary")
    return body


class P2BriefingBudgetAndDecisionTests(unittest.TestCase):
    def test_N129_configured_page_proxy_boundaries_are_exact(self) -> None:
        budget = json.loads(CONFIG.read_text(encoding="utf-8"))["profiles"]["briefing"]["delivery_budget"]
        self.assertEqual(
            budget,
            {
                "page_proxy": "markdown-one-page/v1",
                "visible_chars_max": 3200,
                "nonblank_lines_max": 80,
                "section_visible_chars_max": 900,
                "conclusion_visible_chars_max": 80,
            },
        )
        boundaries = (
            ("visible-3200", _body_at_visible_budget(3200), "briefing_page_limit_exceeded", False),
            ("visible-3201", _body_at_visible_budget(3201), "briefing_page_limit_exceeded", True),
            ("lines-80", _body_at_line_budget(80), "briefing_page_limit_exceeded", False),
            ("lines-81", _body_at_line_budget(81), "briefing_page_limit_exceeded", True),
            ("section-900", _body_at_section_budget(900), "briefing_section_budget_exceeded", False),
            ("section-901", _body_at_section_budget(901), "briefing_section_budget_exceeded", True),
            ("conclusion-80", _body_at_conclusion_budget(80), "briefing_conclusion_budget_exceeded", False),
            ("conclusion-81", _body_at_conclusion_budget(81), "briefing_conclusion_budget_exceeded", True),
        )
        for label, body, code, expected in boundaries:
            with self.subTest(boundary=label):
                self.assertEqual(code in _briefing_codes(body), expected)

    def test_negative_recommendation_and_vacuous_action_are_rejected(self) -> None:
        negative = _briefing_body(
            decision="不建议=win；投入强度=高；边界=这里只是在否定高投入",
        )
        self.assertIn("briefing_opportunity_content_invalid", _briefing_codes(negative))
        vacuous = _briefing_body(action="暂无动作")
        self.assertIn("briefing_primary_action_invalid", _briefing_codes(vacuous))

    def test_N130_briefing_and_strategy_five_tuple_must_match(self) -> None:
        briefing = _briefing_document(_briefing_body())
        base_strategy = """# 示例医院交流策略

## 机会资格

- 建议：monitor
- 投入强度：低

## 会后行动

| action | owner | due_date |
|---|---|---|
| 确认下一次技术交流 | 客户负责人 | 2026-09-25 |
"""
        replacements = {
            "recommendation": ("- 建议：monitor", "- 建议：win"),
            "investment_intensity": ("- 投入强度：低", "- 投入强度：中"),
            "primary_action": ("确认下一次技术交流", "安排下一次项目评审"),
            "owner": ("客户负责人", "方案负责人"),
            "due_date": ("2026-09-25", "2026-09-26"),
        }
        for field, (old, new) in replacements.items():
            with self.subTest(field=field):
                strategy_body = base_strategy.replace(old, new)
                strategy = validator.Document(
                    Path("示例医院交流策略与议题设计.md"),
                    strategy_body,
                    {"artifact_type": "visit_strategy", "strategy_variant": "scheduled_visit"},
                    strategy_body,
                )
                issues: list[object] = []
                validator.validate_briefing_claim_contract(
                    {"briefing_delivery": briefing, "visit_strategy": strategy},
                    {},
                    issues,
                )
                self.assertIn(
                    "briefing_strategy_decision_drift",
                    {issue.code for issue in issues},
                )

    def test_N134_letter_branch_cannot_inherit_summary_from_historical_strategy_file(self) -> None:
        strategy_body = """# 示例医院交流策略

## 机会资格

- 建议：monitor
- 投入强度：低

## 会后行动

| action | owner | due_date |
|---|---|---|
| 确认下一次技术交流 | 客户负责人 | 2026-09-25 |
"""
        strategy = validator.Document(
            Path("示例医院交流策略与议题设计.md"),
            strategy_body,
            {"artifact_type": "visit_strategy", "strategy_variant": "scheduled_visit"},
            strategy_body,
        )
        documents = {"visit_strategy": strategy}
        self.assertIsNone(
            validator.delivery_summary_for_documents(
                documents,
                business_mode="letter",
                selected_modules=[],
            )
        )
        self.assertIsNone(
            validator.delivery_summary_for_documents(
                documents,
                business_mode="standard_visit",
                selected_modules=["institution"],
            )
        )
        self.assertEqual(
            validator.delivery_summary_for_documents(
                documents,
                business_mode="standard_visit",
                selected_modules=["strategy"],
            )["recommendation"],
            "monitor",
        )


if __name__ == "__main__":
    unittest.main()
