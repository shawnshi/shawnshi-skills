from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.common import CONFIG, SKILL_ROOT, load_json, research_plan as rp, runtime_tx as tx, test_intake_gate


NOW = datetime(2026, 8, 26, 4, 0, 0, tzinfo=timezone.utc)
CONTEXT_ID = "dcx-20260826-Abcd1234"
RUN_ID = "dcr-20260826T040000-Ab12"


def bound_candidate(root: Path, plan: dict) -> tuple[Path, Path]:
    source = root / "source"
    candidate = root / "candidate"
    (source / "runtime").mkdir(parents=True)
    (candidate / "runtime").mkdir(parents=True)
    common = {
        "schema": "discovery-call-runtime/v1",
        "context_id": plan["context_id"],
        "customer_id": plan["customer_id"],
        "business_mode": plan["business_mode"],
        "authorization": {},
        "runtime_files": {},
        "artifacts": {},
        "intake_preflight": dict(plan["intake_preflight"]),
    }
    source_manifest = {**common, "latest_run_id": "dcr-20260826T030000-Src1", "transaction_sequence": 1}
    candidate_manifest = {**common, "latest_run_id": plan["run_id"], "transaction_sequence": 2}
    tx.atomic_write_json(source / "runtime" / "manifest.json", source_manifest)
    tx.atomic_write_json(candidate / "runtime" / "manifest.json", candidate_manifest)
    source_digest = hashlib.sha256((source / "runtime" / "manifest.json").read_bytes()).hexdigest()
    candidate_digest = hashlib.sha256((candidate / "runtime" / "manifest.json").read_bytes()).hexdigest()
    tx.atomic_write_json(
        candidate / "runtime" / "candidate-receipt.json",
        {
            "schema": "discovery-call-candidate-receipt/v2",
            "context_id": plan["context_id"],
            "run_id": plan["run_id"],
            "source_manifest_revision": 1,
            "source_manifest_sha256": source_digest,
            "source_workspace": str(source),
            "candidate_workspace": str(candidate),
            "input_payload_sha256": hashlib.sha256(b"profile-planning-test-input").hexdigest(),
            "final_manifest_sha256": candidate_digest,
        },
    )
    return source, candidate


def fields_for(mode: str) -> dict[str, str]:
    common = {
        "customer_name": "示例医院",
        "organization_scope": "示例医院主院区",
    }
    if mode in {"briefing", "standard_visit", "strategic_account"}:
        common.update(
            {
                "target_contact_level": "分管信息化副院长",
                "visit_objective": "确认年度建设重点",
                "minimum_next_step": "安排专题方案交流",
            }
        )
    if mode == "strategic_account":
        common["strategy_variant"] = "scheduled_visit"
        common["strategic_question"] = "未来三年怎样形成院级数字化治理能力"
    if mode == "letter":
        common.update(
            {
                "letter_scenario": "首次拜访邀约",
                "recipient_role": "王院长｜分管信息化副院长｜身份已确认",
                "letter_purpose": "邀请参加数字化专题交流",
                "expected_action": "确认可交流时间",
                "signer": "战略咨询部",
                "delivery_channel": "正式邮件",
            }
        )
    return common


def build(mode: str, **overrides):
    arguments = {
        "business_mode": mode,
        "context_id": CONTEXT_ID,
        "run_id": RUN_ID,
        "customer_name": "示例医院",
        "customer_id": "customer.demo",
        "organization_scope": "示例医院主院区",
        "business_fields": fields_for(mode),
        "generated_at": NOW,
        "intake_preflight": test_intake_gate(mode, at=NOW),
    }
    arguments.update(overrides)
    return rp.build_search_plan(**arguments)


class BusinessProfileTests(unittest.TestCase):
    def test_profile_schema_and_required_fields(self):
        config = rp.load_config(CONFIG)
        self.assertEqual(set(config["profiles"]), set(rp.BUSINESS_MODES))
        expected = {
            "briefing": ("visit_prep", "quick", 12, 8, 5),
            "standard_visit": ("visit_prep", "standard", 30, 20, 12),
            "strategic_account": ("strategy", "deep", 60, 40, 25),
            "letter": ("letter", "standard", 12, 8, 5),
        }
        for mode, profile in config["profiles"].items():
            route, depth, public_max, internal_max, source_max = expected[mode]
            self.assertEqual((profile["route"], profile["depth"]), (route, depth))
            self.assertEqual(profile["query_budget"]["public_max"], public_max)
            self.assertEqual(profile["query_budget"]["internal_max"], internal_max)
            self.assertEqual(profile["source_budget"]["max"], source_max)
            self.assertEqual(set(profile["ttl_days"]), set(rp.TTL_CLASSES))
            self.assertEqual(profile["authorization_requirements"]["stable_ids"], ["customer_id"])
            self.assertTrue(profile["planning_gate"]["required"])
        self.assertEqual(config["profiles"]["briefing"]["output_pages"], {"min": 1, "max": 1})

    def test_all_machine_schema_files_are_json(self):
        expected = {
            "business-modes.schema.json",
            "intake-preflight.schema.json",
            "request-binding-receipt.schema.json",
            "search-plan.schema.json",
            "source-cache.schema.json",
            "evidence-manifest.schema.json",
            "run-metrics.schema.json",
        }
        schema_root = SKILL_ROOT / "schemas"
        self.assertTrue(expected <= {path.name for path in schema_root.glob("*.json")})
        for name in expected:
            payload = load_json(schema_root / name)
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_briefing_template_covers_the_full_thirty_minute_agenda(self):
        template = (SKILL_ROOT / "assets" / "briefing-template.md").read_text(encoding="utf-8")
        for interval in ("0—5分钟", "5—20分钟", "20—25分钟", "25—30分钟"):
            self.assertIn(interval, template)

    def test_role_level_visit_does_not_force_named_leader_research(self):
        config = rp.load_config(CONFIG)
        for mode in ("standard_visit", "strategic_account"):
            with self.subTest(mode=mode):
                profile = config["profiles"][mode]
                self.assertNotIn("leader", profile["modules"])
                self.assertIn("leader", profile["optional_modules"])
                plan = build(mode)
                self.assertTrue(plan["planning_ready"], plan["gate_results"])
                self.assertNotIn("leader", plan["selected_modules"])

    def test_each_mode_builds_planning_ready_compatible_plan(self):
        for mode in rp.BUSINESS_MODES:
            with self.subTest(mode=mode):
                plan = build(mode)
                self.assertTrue(plan["planning_ready"], plan["gate_results"])
                self.assertEqual(
                    (plan["route"], plan["depth"]), rp.EXPECTED_COMPATIBILITY[mode]
                )
                self.assertTrue(set(plan["selected_modules"]) >= set(rp.load_config()["profiles"][mode]["modules"]))

    def test_internal_authorization_is_conditional_and_strict(self):
        modules = ["institution", "leader", "strategy", "internal"]
        blocked = build("standard_visit", selected_modules=modules)
        self.assertFalse(blocked["planning_ready"])
        self.assertTrue(
            {"tenant_customer_project_ids_stable", "project_authorized", "authorization_current"}
            <= set(blocked["gate_results"]["failed"])
        )
        locally_asserted = build(
            "standard_visit",
            selected_modules=modules,
            tenant_id="tenant.demo",
            project_id="project.demo",
            allowed_project_ids=["project.demo"],
            authorization_expires_at="2026-09-30T12:00:00+08:00",
        )
        self.assertFalse(locally_asserted["planning_ready"])
        self.assertTrue(locally_asserted["internal_queries_suppressed"])
        self.assertIn("capability_receipt_verified", locally_asserted["gate_results"]["failed"])


class ResearchPlanTests(unittest.TestCase):
    def test_query_dedup_budget_batch_and_determinism(self):
        duplicate_queries = [
            "示例医院 官网 地址",
            "  示例医院，官网 地址  ",
            {"query": "示例医院 官网 地址", "channel": "public", "priority": 1},
        ]
        first = build(
            "briefing",
            aliases=["示例医院", "示例 医院"],
            custom_queries=duplicate_queries,
        )
        second = build(
            "briefing",
            aliases=["示例医院", "示例 医院"],
            custom_queries=duplicate_queries,
        )
        self.assertEqual(first, second)
        keys = [(item["channel"], item["normalized_query"]) for item in first["queries"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertLessEqual(
            sum(item["channel"] == "public" for item in first["queries"]),
            first["budgets"]["query"]["public_max"],
        )
        self.assertTrue(all(len(batch["query_ids"]) <= 4 for batch in first["batches"]))

    def test_time_sensitive_query_uses_plan_year_not_a_frozen_literal(self):
        plan = build("briefing")
        current_task = next(query for query in plan["queries"] if query["purpose"] == "current-task")
        self.assertIn("2026", current_task["query"])
        future = rp.build_search_plan(
            business_mode="briefing",
            context_id=CONTEXT_ID,
            run_id=RUN_ID,
            customer_name="示例医院",
            customer_id="customer.demo",
            organization_scope="示例医院主院区",
            business_fields=fields_for("briefing"),
            generated_at=NOW.replace(year=2028),
            intake_preflight=test_intake_gate("briefing", at=NOW.replace(year=2028)),
        )
        future_query = next(query for query in future["queries"] if query["purpose"] == "current-task")
        self.assertIn("2028", future_query["query"])
        self.assertNotIn("2026", future_query["query"])

    def test_source_cache_hit_expiry_and_canonical_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source-cache.json"
            cache = rp.SourceCache(
                path,
                {"institution": 90, "leader": 14, "procurement": 7, "internal": 30},
                clock=lambda: NOW,
            )
            entry = cache.put(
                "https://redirect.example/source",
                "official content",
                ttl_class="institution",
                metadata={"title": "official"},
                final_url="HTTPS://Example.COM:443/a/?b=2&a=1#fragment",
                retrieved_at=NOW,
            )
            hit = cache.lookup("https://redirect.example/source", at=NOW + timedelta(days=89))
            self.assertEqual(hit["content_sha256"], entry["content_sha256"])
            self.assertEqual(entry["final_url"], "HTTPS://Example.COM:443/a/?b=2&a=1#fragment")
            self.assertEqual(entry["canonical_locator"], "https://redirect.example/source")
            self.assertEqual(entry["retrieved_at"], "2026-08-26T04:00:00Z")
            self.assertEqual(entry["capture_method"], rp.CAPTURE_METHOD_TEXT)
            self.assertEqual(entry["length"], len("official content".encode("utf-8")))
            self.assertEqual(entry["source_fingerprint"], "sha256:" + entry["content_sha256"])
            self.assertIsNone(
                cache.lookup("https://redirect.example/source", at=NOW + timedelta(days=90))
            )

    def test_capture_source_snapshot_is_content_derived_and_canonical(self):
        decomposed = "Cafe\u0301\r\n第二行"
        normalized = "Caf\u00e9\n第二行"
        first = rp.capture_source_snapshot(
            "https://redirect.example/source",
            decomposed,
            final_url="HTTPS://Example.COM:443/a//?b=2&a=1#fragment",
            retrieved_at=NOW,
        )
        second = rp.capture_source_snapshot(
            "https://redirect.example/source",
            normalized,
            final_url="https://example.com/a?a=1&b=2",
            retrieved_at=NOW,
        )
        expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        self.assertEqual(first["canonical_locator"], "https://redirect.example/source")
        self.assertEqual(first["content_sha256"], expected)
        self.assertEqual(first["source_fingerprint"], "sha256:" + expected)
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(first["capture_method"], rp.CAPTURE_METHOD_TEXT)
        self.assertEqual(first["length"], len(normalized.encode("utf-8")))

        raw = rp.capture_source_snapshot(
            "https://example.com/raw",
            b"a\r\nb",
            retrieved_at=NOW,
        )
        self.assertEqual(raw["capture_method"], rp.CAPTURE_METHOD_RAW_BYTES)
        self.assertEqual(raw["content_sha256"], hashlib.sha256(b"a\r\nb").hexdigest())
        self.assertNotEqual(raw["content_sha256"], hashlib.sha256(b"a\nb").hexdigest())

    def test_source_cache_treats_tampered_fingerprint_as_cache_miss(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source-cache.json"
            cache = rp.SourceCache(
                path,
                {"institution": 90, "leader": 14, "procurement": 7, "internal": 30},
                clock=lambda: NOW,
            )
            entry = cache.put(
                "https://example.com/a",
                "official content",
                ttl_class="institution",
                retrieved_at=NOW,
            )
            payload = load_json(path)
            payload["entries"][entry["cache_key"]]["source_fingerprint"] = (
                "sha256:" + hashlib.sha256(entry["canonical_locator"].encode("utf-8")).hexdigest()
            )
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(cache.lookup("https://example.com/a", at=NOW))

    def test_source_cache_schema_requires_content_snapshot_fields(self):
        schema = load_json(SKILL_ROOT / "schemas" / "source-cache.schema.json")
        entry = schema["$defs"]["entry"]
        self.assertTrue(
            {"final_url", "retrieved_at", "capture_method", "length", "content_sha256"}
            <= set(entry["required"])
        )
        self.assertEqual(entry["properties"]["source_fingerprint"]["pattern"], "^sha256:[0-9a-f]{64}$")

    def test_machine_files_metrics_and_markdown_independence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build("briefing")
            source, workspace = bound_candidate(root, plan)
            (workspace / "临时报告.md").write_text("temporary", encoding="utf-8")
            paths = rp.RuntimeWorkspace(workspace, source_workspace=source).materialize(plan, generated_at=NOW)
            self.assertEqual(set(paths), {"search_plan", "source_cache", "evidence_manifest", "run_metrics"})
            for path in paths.values():
                self.assertTrue(path.is_file())
                json.loads(path.read_text(encoding="utf-8"))
            evidence = load_json(paths["evidence_manifest"])
            self.assertEqual(evidence["connector_audit"]["status"], "not_applicable")
            self.assertNotEqual(evidence["connector_audit"]["status"], "connected")

            metrics = rp.RunMetrics(
                paths["run_metrics"], CONTEXT_ID, RUN_ID, "briefing", NOW
            )
            metrics.increment(cache_hits=2, queries_executed=3, sources_accepted=1)
            final = metrics.finish(
                ended_at=NOW + timedelta(milliseconds=250), input_tokens=100, output_tokens=20
            )
            self.assertEqual(final["elapsed_ms"], 250)
            self.assertEqual(final["counters"]["cache_hits"], 2)
            self.assertEqual(final["counters"]["input_tokens"], 100)

            (workspace / "临时报告.md").unlink()
            self.assertFalse(list(workspace.glob("*.md")))
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertEqual(load_json(paths["search_plan"])["run_id"], RUN_ID)

    def test_evidence_manifest_update_preserves_offline_connector_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build("briefing")
            source, workspace = bound_candidate(root, plan)
            paths = rp.RuntimeWorkspace(workspace, source_workspace=source).materialize(plan, generated_at=NOW)
            source_record = {
                "source_id": "SRC-I-001",
                **rp.capture_source_snapshot(
                    "https://example.test",
                    "example source",
                    retrieved_at=NOW,
                ),
            }
            source_record["cache_key"] = hashlib.sha256(
                source_record["canonical_locator"].encode("utf-8")
            ).hexdigest()
            source_record.update(
                {
                    "source_title": "Example source",
                    "publisher_or_provider": "Example publisher",
                    "publication_or_update_date": "未标注",
                    "access_date": NOW.date().isoformat(),
                    "published_at": None,
                    "source_updated_at": None,
                    "internal_recorded_at": None,
                    "source_level": "A",
                    "source_group": "example-group",
                    "permission": "public",
                    "applicable_scope": "示例客户",
                    "notes": "none",
                    "upstream_id": "record:example-source",
                    "external_use": "true",
                    "tenant_id": None,
                    "project_id": None,
                    # This unit exercises deterministic record assembly; the
                    # candidate validator separately verifies the host signature.
                    "capture_receipt": {
                        "schema": "discovery-call-source-capture-receipt/v3"
                    },
                }
            )
            updated = rp.update_evidence_manifest(
                paths["evidence_manifest"],
                sources={"SRC-I-001": source_record},
                claims={
                    "CLM-I-001": {
                        "claim_id": "CLM-I-001",
                        "information_type": "institution",
                        "ttl_class": "institution",
                        "evidence_anchor_at": NOW.isoformat(),
                        "date_basis": "retrieved_at",
                        "verified_at": NOW.isoformat(),
                        "ttl_days": 90,
                        "expires_at": (NOW + timedelta(days=90)).isoformat(),
                        "claim_type": "F",
                        "provenance": "public",
                        "verification_status": "verified_single",
                        "claim_text": "示例来源已确认",
                        "time_scope": "当前口径",
                        "supporting_source_refs": "SRC-I-001",
                        "supporting_source_ids": ["SRC-I-001"],
                        "supporting_source_receipt_sha256s": {"SRC-I-001": "a" * 64},
                        "counter_source_refs": "无",
                        "counter_source_ids": [],
                        "confidence": "高",
                        "downstream_impact": "用于测试",
                    }
                },
                query_links={plan["queries"][0]["query_id"]: ["SRC-I-001", "SRC-I-001"]},
                updated_at=NOW + timedelta(seconds=1),
            )
            self.assertIn("SRC-I-001", updated["sources"])
            self.assertEqual(
                updated["query_links"][plan["queries"][0]["query_id"]], ["SRC-I-001"]
            )
            self.assertEqual(updated["connector_audit"]["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
