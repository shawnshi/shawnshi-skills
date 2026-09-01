import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from history_manager import generate_event_id
from run_contract import (
    RunContractError,
    build_supplement_request,
    candidate_object_hash,
    candidate_ref,
    create_run,
    record_run_artifact,
    record_stage,
)
from supplement_agent import assemble_result, build_agent_context


class SupplementAgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.skill = self.root / "SKILL.md"
        self.skill.write_text("skill", encoding="utf-8")
        skill_sha = hashlib.sha256(b"skill").hexdigest()
        (self.root / "resource-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "skill": self.root.name,
                    "skill_md": "SKILL.md",
                    "skill_md_sha256": skill_sha,
                    "top_level_file_hashes": [],
                    "declared_local_dependencies": [],
                    "missing_declared_dependencies": [],
                }
            ),
            encoding="utf-8",
        )
        self.now = datetime(2026, 8, 31, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.manifest_path, _ = create_run(
            runtime_dir=self.root / "runtime",
            skill_path=self.skill,
            report_date="2026-08-31",
            timezone_name="Asia/Shanghai",
            now=self.now,
            run_id="supplement-agent-test",
        )
        baseline = self.root / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            self.manifest_path,
            "baseline",
            "completed",
            artifact_path=baseline,
            metadata={"source_total": 1, "source_ok": 1, "source_failed": 0},
            now=self.now,
        )
        candidate_pool = self.root / "candidate_pool.json"
        candidate_pool.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "title": "Agent release",
                            "url": "https://example.org/agent",
                            "published_at": "2026-08-31T00:00:00+00:00",
                            "source": "Example",
                            "provisional_domain": "technology",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        record_run_artifact(
            self.manifest_path,
            "candidate_pool",
            candidate_pool,
            now=self.now,
        )
        self.request_path, self.request = build_supplement_request(
            self.manifest_path,
            [
                {
                    "gap_id": "technology",
                    "lane": "TechRadar",
                    "query_scope": "AI agents",
                    "max_turns": 3,
                }
            ],
            now=self.now,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_context_is_compact_and_hides_unassigned_packet_details(self):
        context = build_agent_context(self.request_path, "technology")

        self.assertEqual(context["contract_version"], "supplement-agent-context/1.0")
        self.assertEqual(context["gap"]["gap_id"], "technology")
        self.assertEqual(len(context["bound_candidates"]), 1)
        self.assertIn("finalize", context["finalize_command"])
        self.assertEqual(
            context["draft_schema"]["access_method_allowed"],
            ["http_get", "browser", "api", "document"],
        )
        self.assertEqual(
            context["draft_schema"]["candidate_source_type_allowed"],
            ["primary", "secondary"],
        )
        self.assertEqual(
            context["draft_schema"]["candidate_primary_domain_allowed"],
            ["technology", "healthcare_digital"],
        )
        self.assertNotIn("execution_packets", context)
        self.assertNotIn("common_contract", context)

    def test_assemble_result_fills_hashes_event_id_and_coverage(self):
        started = self.now + timedelta(seconds=1)
        checked = started + timedelta(seconds=2)
        completed = checked + timedelta(seconds=1)
        identity = {
            "key_version": "1",
            "primary_domain": "technology",
            "actor": "Example",
            "action": "published",
            "object": "Agent release",
            "event_date": "2026-08-31",
        }
        access = {
            "status": "verified",
            "checked_at": checked.isoformat(),
            "method": "http_get",
            "requested_url": "https://example.org/agent",
            "final_url": "https://example.org/agent",
            "http_status": 200,
            "failure_class": "none",
            "error_code": None,
        }
        dynamic = {
            "status": "completed",
            "executed_queries": ["direct source check"],
            "access_log": [access],
            "candidates": [
                {
                    "title": "Agent release",
                    "url": "https://example.org/agent",
                    "source": "Example",
                    "published_at": "2026-08-31T00:00:00+00:00",
                    "published_at_source": "source page",
                    "retrieved_at": checked.isoformat(),
                    "primary_domain": "technology",
                    "secondary_domains": [],
                    "source_type": "primary",
                    "identity_quality": "semantic",
                    "event_identity": identity,
                    "access_check": {key: access[key] for key in ("status", "checked_at", "method", "requested_url", "final_url", "http_status")},
                    "summary": "Example published an agent release.",
                }
            ],
            "confidence": "high",
            "turns_used": 1,
            "halt_condition_met": True,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
        }

        draft_path, result = assemble_result(
            self.request_path, "technology", dynamic
        )

        self.assertTrue(draft_path.is_file())
        self.assertEqual(result["coverage"], {"attempted": 1, "succeeded": 1, "failed": 0})
        self.assertEqual(result["candidates"][0]["published_at"], "2026-08-31")
        self.assertEqual(result["candidates"][0]["event_id"], generate_event_id(identity))
        self.assertEqual(
            result["candidates"][0]["candidate_id"],
            candidate_ref("https://example.org/agent"),
        )
        self.assertEqual(
            result["candidates"][0]["candidate_object_sha256"],
            candidate_object_hash(result["candidates"][0]),
        )
        self.assertEqual(result["request_sha256"], hashlib.sha256(self.request_path.read_bytes()).hexdigest())
        self.assertEqual(json.loads(draft_path.read_text(encoding="utf-8")), result)

        invalid = deepcopy(dynamic)
        invalid["access_log"][0].pop("checked_at")
        with self.assertRaisesRegex(RunContractError, "checked_at"):
            assemble_result(self.request_path, "technology", invalid)

        success_with_failed_coverage = deepcopy(dynamic)
        success_with_failed_coverage["status"] = "no_increment"
        success_with_failed_coverage["candidates"] = []
        success_with_failed_coverage["confidence"] = "low"
        success_with_failed_coverage["access_log"][0].update(
            {
                "status": "blocked",
                "http_status": 404,
                "failure_class": "permanent",
                "error_code": "HTTP_404",
            }
        )
        with self.assertRaisesRegex(
            RunContractError, "successful supplement status"
        ):
            assemble_result(
                self.request_path,
                "technology",
                success_with_failed_coverage,
            )


if __name__ == "__main__":
    unittest.main()
