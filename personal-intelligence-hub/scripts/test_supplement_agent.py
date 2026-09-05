import hashlib
import json
import ssl
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
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
                            "published_at_source": "rss_published",
                            "source": "Example",
                            "source_type": "primary",
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
                    "verify_bound_candidates": True,
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
        self.assertEqual(
            context["required_bound_candidate_urls"],
            ["https://example.org/agent"],
        )
        self.assertEqual(context["required_bound_candidate_count"], 1)
        self.assertIn("redirect_rule", context["rules"])
        self.assertIn("verification_rule", context["rules"])
        self.assertTrue(
            any(
                "emit an enriched candidate using the same candidate_id" in instruction
                for instruction in context["draft_instructions"]
            )
        )
        self.assertIn(
            "Re-register each bound candidate",
            self.request["execution_packets"][0]["task_message"],
        )
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

    def test_infrastructure_failure_accounts_for_unattempted_bound_candidate(self):
        started = self.now + timedelta(seconds=1)
        completed = started + timedelta(seconds=1)
        dynamic = {
            "status": "failed",
            "failure_kind": "infrastructure",
            "failure_reason": "network tooling was unavailable",
            "executed_queries": [],
            "access_log": [],
            "bound_candidate_decisions": [
                {
                    "candidate_id": candidate_ref("https://example.org/agent"),
                    "decision": "infrastructure_unavailable",
                    "reason": "network tooling failed before the first request",
                }
            ],
            "candidates": [],
            "confidence": "low",
            "turns_used": 0,
            "halt_condition_met": False,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
        }

        _, result = assemble_result(self.request_path, "technology", dynamic)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["coverage"], {"attempted": 0, "succeeded": 0, "failed": 0})
        self.assertEqual(
            result["bound_candidate_decisions"][0]["decision"],
            "infrastructure_unavailable",
        )

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
            "bound_candidate_decisions": [
                {
                    "candidate_id": candidate_ref("https://example.org/agent"),
                    "decision": "registered",
                    "reason": "verified primary source within the report window",
                }
            ],
            "candidates": [
                {
                    "candidate_id": candidate_ref("https://example.org/agent"),
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

        omitted_required = deepcopy(dynamic)
        omitted_required["status"] = "no_increment"
        omitted_required["candidates"] = []
        omitted_required["access_log"][0]["requested_url"] = (
            "https://example.org/unbound"
        )
        omitted_required["access_log"][0]["final_url"] = (
            "https://example.org/unbound"
        )
        with self.assertRaisesRegex(RunContractError, "omitted required"):
            assemble_result(self.request_path, "technology", omitted_required)

        swapped_bound_url = deepcopy(dynamic)
        swapped_bound_url["candidates"][0]["url"] = "https://example.org/swapped"
        swapped_bound_url["candidates"][0]["access_check"]["requested_url"] = (
            "https://example.org/swapped"
        )
        swapped_bound_url["candidates"][0]["access_check"]["final_url"] = (
            "https://example.org/swapped"
        )
        with self.assertRaisesRegex(RunContractError, "preserve the bound URL"):
            assemble_result(self.request_path, "technology", swapped_bound_url)

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
        success_with_failed_coverage["bound_candidate_decisions"] = [
            {
                "candidate_id": candidate_ref("https://example.org/agent"),
                "decision": "access_blocked",
                "reason": "HTTP 404 permanent response",
            }
        ]
        with self.assertRaisesRegex(
            RunContractError, "successful supplement status"
        ):
            assemble_result(
                self.request_path,
                "technology",
                success_with_failed_coverage,
            )

    def test_degraded_auto_infers_source_access_failure_kind(self):
        started = self.now + timedelta(seconds=1)
        checked = started + timedelta(seconds=2)
        completed = checked + timedelta(seconds=1)
        dynamic = {
            "status": "degraded",
            # failure_kind and failure_reason omitted
            "executed_queries": ["source check"],
            "access_log": [
                {
                    "status": "blocked",
                    "checked_at": checked.isoformat(),
                    "method": "http_get",
                    "requested_url": "https://example.org/agent",
                    "final_url": "https://example.org/agent",
                    "http_status": 403,
                    "failure_class": "permanent",
                    "error_code": "HTTP_403",
                }
            ],
            "bound_candidate_decisions": [
                {
                    "candidate_id": candidate_ref("https://example.org/agent"),
                    "decision": "access_blocked",
                    "reason": "HTTP 403 Forbidden",
                }
            ],
            "candidates": [],
            "confidence": "low",
            "turns_used": 1,
            "halt_condition_met": True,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
        }
        _, result = assemble_result(self.request_path, "technology", dynamic)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["failure_kind"], "source_access")
        self.assertTrue(len(result["failure_reason"]) > 0)

    def test_fetch_probe_rejects_empty_login_and_soft_404_bodies(self):
        from supplement_agent import _fetch_url

        class Response:
            status = 200

            def __init__(self, body: str, final_url: str):
                self.body = body.encode("utf-8")
                self.final_url = final_url
                self.headers = {"Content-Type": "text/html; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return self.final_url

            def read(self, _limit):
                return self.body

        cases = (
            ("", "https://example.org/article"),
            ("<html><title>Login</title>Sign in</html>", "https://example.org/login"),
            ("<html><title>404 Not Found</title>missing</html>", "https://example.org/article"),
        )
        for body, final_url in cases:
            with self.subTest(final_url=final_url, body=body):
                with patch("supplement_agent.urllib.request.urlopen", return_value=Response(body, final_url)):
                    outcome = _fetch_url("https://example.org/article")
                self.assertEqual(outcome[0], "blocked")
                self.assertEqual(outcome[4], "CONTENT_NOT_VERIFIED")

        article = "<html><article>" + ("substantive evidence text " * 20) + "</article></html>"
        with patch(
            "supplement_agent.urllib.request.urlopen",
            return_value=Response(article, "https://example.org/article"),
        ):
            outcome = _fetch_url("https://example.org/article")
        self.assertEqual(outcome, ("verified", "https://example.org/article", 200, "none", None))

        with patch(
            "supplement_agent.urllib.request.urlopen",
            side_effect=ssl.SSLCertVerificationError(1, "certificate verify failed"),
        ):
            outcome = _fetch_url("https://example.org/article")
        self.assertEqual(outcome[0], "blocked")
        self.assertEqual(outcome[3], "permanent")
        self.assertEqual(outcome[4], "error_SSLCertVerificationError")

    def test_verify_bound_candidates_quarantines_unknown_or_out_of_window_date(self):
        from supplement_agent import verify_bound_candidates

        with patch(
            "supplement_agent._fetch_url",
            return_value=("verified", "https://example.org/agent", 200, "none", None),
        ):
            lane_slice_path = Path(
                self.request["execution_packets"][0]["lane_slice"]["path"]
            )
            lane_slice = json.loads(lane_slice_path.read_text(encoding="utf-8"))
            lane_slice["candidates"][0]["published_at"] = "unknown"
            lane_slice["candidates"][0]["published_at_source"] = "unknown"
            lane_slice_path.write_text(json.dumps(lane_slice), encoding="utf-8")
            lane_sha = hashlib.sha256(lane_slice_path.read_bytes()).hexdigest()
            packet = self.request["execution_packets"][0]
            packet["lane_slice"]["sha256"] = lane_sha
            packet["bound_input_paths"]["lane_slice"]["sha256"] = lane_sha
            self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["supplement_request"]["artifact_sha256"] = hashlib.sha256(
                self.request_path.read_bytes()
            ).hexdigest()
            self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            dynamic = verify_bound_candidates(self.request_path, "technology")

        self.assertEqual(dynamic["status"], "degraded")
        self.assertEqual(dynamic["failure_kind"], "published_at_conflict")
        self.assertEqual(dynamic["candidates"], [])
        self.assertEqual(
            dynamic["bound_candidate_decisions"][0]["decision"],
            "date_disqualified",
        )

    def test_verify_bound_candidates_generates_valid_draft(self):
        from supplement_agent import verify_bound_candidates

        # Mock _fetch_url to avoid network calls in unit tests
        with patch("supplement_agent._fetch_url") as mock_fetch:
            mock_fetch.return_value = ("verified", "https://example.org/agent", 200, "none", None)
            dynamic = verify_bound_candidates(
                self.request_path,
                "technology",
                write_draft=True,
            )
            self.assertEqual(dynamic["status"], "completed")
            self.assertEqual(len(dynamic["candidates"]), 1)
            self.assertEqual(dynamic["candidates"][0]["url"], "https://example.org/agent")
            self.assertEqual(dynamic["candidates"][0]["primary_domain"], "technology")
            self.assertEqual(len(dynamic["bound_candidate_decisions"]), 1)
            self.assertEqual(dynamic["bound_candidate_decisions"][0]["decision"], "registered")

            # Validate that assemble_result passes cleanly on this generated draft
            _, result = assemble_result(self.request_path, "technology", dynamic)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(len(result["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()
