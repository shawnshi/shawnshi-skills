from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.common import CONFIG, SKILL_ROOT, load_json, research_plan as rp


NOW = datetime(2026, 8, 26, 4, 0, 0, tzinfo=timezone.utc)
CONTEXT_ID = "dcx-20260826-Abcd1234"
RUN_ID = "dcr-20260826T040000-Ab12"


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
        common["strategic_question"] = "未来三年怎样形成院级数字化治理能力"
    if mode == "letter":
        common.update(
            {
                "letter_scenario": "首次拜访邀约",
                "recipient_role": "王院长｜分管信息化副院长",
                "recipient_identity_status": "confirmed",
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
        ready = build(
            "standard_visit",
            selected_modules=modules,
            tenant_id="tenant.demo",
            project_id="project.demo",
            allowed_project_ids=["project.demo"],
            authorization_expires_at="2026-09-30T12:00:00+08:00",
        )
        self.assertTrue(ready["planning_ready"], ready["gate_results"])


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
                "HTTPS://Example.COM/a/?b=2&a=1#fragment",
                "official content",
                ttl_class="institution",
                metadata={"title": "official"},
                fetched_at=NOW,
            )
            hit = cache.lookup("https://example.com/a?a=1&b=2", at=NOW + timedelta(days=89))
            self.assertEqual(hit["content_sha256"], entry["content_sha256"])
            self.assertIsNone(
                cache.lookup("https://example.com/a?a=1&b=2", at=NOW + timedelta(days=90))
            )

    def test_R03_invalid_url_port_is_plan_error_without_cache_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-cache.json'
            cache = rp.SourceCache(path, {'institution': 90}, clock=lambda: NOW)
            cache.put('https://example.test/a', 'valid', ttl_class='institution')
            before = path.read_bytes()
            for locator in ('https://example.test:bad/a', 'https://example.test:65536/a', 'https://[broken/a'):
                with self.subTest(locator=locator):
                    with self.assertRaises(rp.PlanError) as caught:
                        rp.canonical_locator(locator)
                    self.assertIsInstance(caught.exception.__cause__, ValueError)
                    with self.assertRaises(rp.PlanError):
                        cache.lookup(locator)
                    with self.assertRaises(rp.PlanError):
                        cache.put(locator, 'invalid', ttl_class='institution')
                    self.assertEqual(path.read_bytes(), before)

    def test_R03_malformed_cache_root_and_entries_are_not_misses(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-cache.json'
            cache = rp.SourceCache(path, {'institution': 90}, clock=lambda: NOW)
            valid = {'schema': 'discovery-call-source-cache/v1', 'entries': {}}
            invalid = [[], None, 1, {}, {**valid, 'entries': []}, {**valid, 'entries': None}]
            invalid.extend({**valid, 'entries': {'bad': entry}} for entry in (
                [], None, False, '', 1, {}, {'expires_at': None}, {'expires_at': 1},
                {'expires_at': 'broken'}, {'expires_at': '2026-08-26T00:00:00'},
            ))
            for payload in invalid:
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding='utf-8')
                    before = path.read_bytes()
                    with self.assertRaises(rp.PlanError):
                        cache.load()
                    with self.assertRaises(rp.PlanError):
                        cache.lookup('https://example.test/missing')
                    with self.assertRaises(rp.PlanError):
                        cache.put('https://example.test/a', 'new', ttl_class='institution')
                    self.assertEqual(path.read_bytes(), before)
            path.unlink()
            self.assertIsNone(cache.lookup('https://example.test/missing'))
            self.assertFalse(path.exists())

    def test_machine_files_metrics_and_markdown_independence(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "临时报告.md").write_text("temporary", encoding="utf-8")
            plan = build("briefing")
            paths = rp.RuntimeWorkspace(workspace).materialize(plan, generated_at=NOW)
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
            workspace = Path(temporary)
            plan = build("briefing")
            paths = rp.RuntimeWorkspace(workspace).materialize(plan, generated_at=NOW)
            updated = rp.update_evidence_manifest(
                paths["evidence_manifest"],
                sources={"SRC-I-001": {"locator": "https://example.test"}},
                claims={"CLM-I-001": {"source_ids": ["SRC-I-001"]}},
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
