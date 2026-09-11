import hashlib
import io
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
from supplement_agent import FetchResult, assemble_result, build_agent_context


class ArticleResponse:
    status = 200

    def __init__(self, body, content_type="text/html; charset=utf-8"):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": content_type}
        self.read_limits = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return "https://example.org/landing"

    def read(self, limit):
        self.read_limits.append(limit)
        return self.body[:limit]


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
                            "title": "Multimodal agent release",
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
        focus_config = self.root / "focus.json"
        focus_config.write_text(
            (
                Path(__file__).resolve().parents[1]
                / "references"
                / "strategic_focus.json"
            ).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        record_run_artifact(
            self.manifest_path,
            "focus_config",
            focus_config,
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
                    "max_urls": 4,
                    "verify_bound_candidates": True,
                }
            ],
            now=self.now,
        )

    def tearDown(self):
        self.directory.cleanup()

    def _replace_lane_candidates(self, candidates):
        packet = self.request["execution_packets"][0]
        path = Path(packet["lane_slice"]["path"])
        lane = json.loads(path.read_text(encoding="utf-8"))
        lane["candidates"] = candidates
        lane["required_bound_candidate_ids"] = [c["candidate_ref"] for c in candidates]
        path.write_text(json.dumps(lane), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        packet["lane_slice"]["sha256"] = sha
        packet["bound_input_paths"]["lane_slice"]["sha256"] = sha
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["supplement_request"]["artifact_sha256"] = hashlib.sha256(self.request_path.read_bytes()).hexdigest()
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_initial_body_delivery_four_bound_accesses_cli_json_dynamic_only(self):
        from supplement_agent import DYNAMIC_FIELDS, main

        candidates = [{"candidate_ref": candidate_ref(f"https://example.org/article-{i}"),
                       "url": f"https://example.org/article-{i}", "title": "Article",
                       "published_at": "2026-08-31", "published_at_source": "rss_published",
                       "source": "Example", "source_type": "secondary"} for i in range(4)]
        self._replace_lane_candidates(candidates)
        article = ('<meta property="article:published_time" content="2026-08-31">'
                   '<script>hidden secret</script><style>hidden style</style><article>' +
                   'Initial body evidence &amp; source claims. ' * 500 + '</article>')
        responses = [ArticleResponse(article) for _ in range(4)]
        stdout = io.StringIO()
        with patch("supplement_agent.urllib.request.urlopen", side_effect=responses) as fetch, patch("supplement_agent.time.sleep"), patch("sys.stdout", stdout), patch("sys.argv", ["supplement_agent.py", "verify-bound", "--request", str(self.request_path), "--gap-id", "technology", "--write-draft"]):
            self.assertEqual(main(), 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(output["access_log_count"], 4)
        self.assertEqual(len(output["body_evidence"]), 4)
        dynamic = json.loads(Path(output["path"]).read_text(encoding="utf-8"))
        self.assertLessEqual(set(dynamic), DYNAMIC_FIELDS)
        self.assertNotIn("body_evidence", dynamic)
        for index, evidence in enumerate(output["body_evidence"]):
            self.assertEqual(evidence["access_log_index"], index)
            self.assertEqual(evidence["candidate_id"], candidates[index]["candidate_ref"])
            self.assertEqual(evidence["access_check"], dynamic["access_log"][index])
            self.assertEqual(evidence["body_sha256"], hashlib.sha256(article.encode()).hexdigest())
            self.assertEqual(evidence["text_sha256"], hashlib.sha256(evidence["text"].encode()).hexdigest())
            self.assertIn("Initial body evidence & source claims.", evidence["text"])
            self.assertNotIn("hidden", evidence["text"])
            self.assertLessEqual(len(json.dumps(evidence["text"], ensure_ascii=False).encode()), 6000)
            self.assertTrue(evidence["text_truncated"])
            self.assertFalse(evidence["body_truncated"])
            self.assertEqual(evidence["publication_metadata"], [{"field": "article:published_time", "raw": "2026-08-31"}])
            self.assertEqual(responses[index].read_limits, [1048577])
        self.assertTrue(all(c["source_type"] == "secondary" for c in dynamic["candidates"]))
        _, result = assemble_result(self.request_path, "technology", dynamic)
        self.assertEqual(result["coverage"], {"attempted": 4, "succeeded": 4, "failed": 0})

    def test_body_evidence_bounds_read_text_and_raw_publication_metadata(self):
        from supplement_agent import _fetch_url

        body = ('<meta name="datePublished" content="2026-08-31">' * 17 +
                '<meta name="pubdate" content="' + 'x' * 513 + '">' +
                '<article>' + 'Visible article evidence. ' * 15000 + '</article>')
        response = ArticleResponse(body)
        with patch("supplement_agent.urllib.request.urlopen", return_value=response):
            result = _fetch_url("https://example.org/agent")
        evidence = result.body_evidence
        assert evidence is not None
        self.assertEqual(result.status, "verified")
        self.assertEqual(response.read_limits, [1048577])
        self.assertEqual(evidence["body_bytes"], len(body.encode()))
        self.assertEqual(evidence["body_sha256"], hashlib.sha256(body.encode()).hexdigest())
        self.assertFalse(evidence["body_truncated"])
        self.assertTrue(evidence["text_truncated"])
        self.assertTrue(evidence["publication_metadata_truncated"])
        self.assertEqual(len(evidence["publication_metadata"]), 16)
        self.assertEqual(len(json.dumps(evidence["text"], ensure_ascii=False).encode()), 6000)

    def test_four_multilingual_evidence_records_fit_cli_output(self):
        from supplement_agent import main

        self._replace_lane_candidates([
            {"candidate_ref": candidate_ref(f"https://example.org/{i}"), "url": f"https://example.org/{i}", "published_at": "unknown"}
            for i in range(4)
        ])
        body = '<meta name="datePublished" content="' + 'd' * 126 + '">'
        response = ArticleResponse(body * 16 + '<article>' + '\u6b63\u6587\u8bc1\u636e\\\u0001 ' * 3000 + '</article>')
        stdout = io.StringIO()
        with patch("supplement_agent.urllib.request.urlopen", return_value=response) as fetch, patch("supplement_agent.time.sleep"), patch("sys.stdout", stdout), patch("sys.argv", ["supplement_agent.py", "verify-bound", "--request", str(self.request_path), "--gap-id", "technology"]):
            self.assertEqual(main(), 0)
        self.assertEqual(fetch.call_count, 4)
        output = json.loads(stdout.getvalue())
        self.assertEqual(len(output["body_evidence"]), 4)
        self.assertLess(len(stdout.getvalue().encode("utf-8")), 48000)
        for evidence in output["body_evidence"]:
            self.assertIn('\u6b63\u6587\u8bc1\u636e', evidence["text"])
            self.assertLessEqual(len(json.dumps(evidence["text"], ensure_ascii=False).encode()), 6000)
            self.assertTrue(evidence["text_truncated"])

    def test_plain_text_charset_and_conflicting_raw_dates_are_not_inferred(self):
        from supplement_agent import _fetch_url

        text = "Article caf\u00e9 evidence. " * 30
        response = ArticleResponse(text.encode("latin-1"), "text/plain; charset=iso-8859-1")
        with patch("supplement_agent.urllib.request.urlopen", return_value=response):
            result = _fetch_url("https://example.org/agent")
        assert result.body_evidence is not None
        self.assertEqual(result.body_evidence["text"], text.strip())
        self.assertEqual(result.body_evidence["publication_metadata"], [])
        html = ('<meta name="datePublished" content="2026-08-31">'
                '<meta name="pubdate" content="2026-07-01">'
                '<meta name="dateModified" content="2026-09-01">' + text)
        with patch("supplement_agent.urllib.request.urlopen", return_value=ArticleResponse(html)):
            result = _fetch_url("https://example.org/agent")
        assert result.body_evidence is not None
        self.assertEqual(result.body_evidence["publication_metadata"], [
            {"field": "datePublished", "raw": "2026-08-31"},
            {"field": "pubdate", "raw": "2026-07-01"},
        ])
        self.assertNotIn("published_at", result.body_evidence)
        self.assertNotIn("source_type", result.body_evidence)

    def test_blocked_challenge_delivers_no_usable_body(self):
        from supplement_agent import verify_bound_candidates

        response = ArticleResponse('<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/test"></script>' + 'checking your browser ' * 50)
        with patch("supplement_agent.urllib.request.urlopen", return_value=response) as fetch, patch("supplement_agent.time.sleep"):
            output = verify_bound_candidates(self.request_path, "technology")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(output["body_evidence"], [])
        self.assertEqual(output["draft"]["access_log"][0]["status"], "blocked")
        self.assertEqual(output["draft"]["candidates"], [])

    def test_delivered_metadata_does_not_override_unknown_or_out_of_window_date(self):
        from supplement_agent import verify_bound_candidates

        for date in ("unknown", "2026-07-01"):
            with self.subTest(date=date):
                self._replace_lane_candidates([{"candidate_ref": candidate_ref("https://example.org/agent"), "url": "https://example.org/agent", "published_at": date, "published_at_source": "rss_published"}])
                response = ArticleResponse('<meta property="article:published_time" content="2026-08-31"><article>' + 'Article with publication claims. ' * 20 + '</article>')
                with patch("supplement_agent.urllib.request.urlopen", return_value=response), patch("supplement_agent.time.sleep"):
                    output = verify_bound_candidates(self.request_path, "technology")
                self.assertEqual(len(output["body_evidence"]), 1)
                dynamic = output["draft"]
                self.assertEqual(dynamic["candidates"], [])
                self.assertEqual(dynamic["bound_candidate_decisions"][0]["decision"], "date_disqualified")
                _, result = assemble_result(self.request_path, "technology", dynamic)
                self.assertEqual(result["failure_kind"], "published_at_conflict")
                self.assertEqual(result["coverage"]["succeeded"], 1)

    def test_accessed_exclusions_are_not_infrastructure_failure(self):
        from supplement_agent import verify_bound_candidates

        response = ArticleResponse('<article>' + 'Document source claims. ' * 20 + '</article>')
        with patch("supplement_agent.urllib.request.urlopen", return_value=response), patch("supplement_agent.time.sleep"):
            output = verify_bound_candidates(self.request_path, "technology")
        for decision in ("source_quality_rejected", "domain_rejected", "date_disqualified"):
            with self.subTest(decision=decision):
                dynamic = deepcopy(output["draft"])
                dynamic["candidates"] = []
                dynamic["bound_candidate_decisions"][0].update(decision=decision, reason="Delivered body does not support eligibility")
                dynamic["status"] = "degraded" if decision == "date_disqualified" else "no_increment"
                _, result = assemble_result(self.request_path, "technology", dynamic)
                self.assertEqual(result["coverage"]["succeeded"], 1)
                dynamic.update(status="failed", failure_kind="infrastructure", failure_reason="No usable candidates")
                draft_path = Path(self.request["execution_packets"][0]["output_paths"]["draft"])
                before = draft_path.read_bytes()
                with self.assertRaisesRegex(RunContractError, "infrastructure.*initialization.*zero.*evidence"):
                    assemble_result(self.request_path, "technology", dynamic)
                self.assertEqual(draft_path.read_bytes(), before)

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
        self.assertEqual(context["execution_budget"]["max_urls"], 4)
        self.assertTrue(any("not unique URLs" in value for value in context["draft_instructions"]))
        self.assertIn("redirect_rule", context["rules"])
        self.assertIn("verification_rule", context["rules"])
        self.assertIn("infrastructure_failure_rule", context["rules"])
        self.assertTrue(any("body_evidence" in value for value in context["draft_instructions"]))
        self.assertTrue(any("zero evidence" in value for value in context["draft_instructions"]))
        self.assertIn("body_evidence", self.request["execution_packets"][0]["task_message"])
        self.assertIn("initialization failure", self.request["execution_packets"][0]["task_message"])
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
            ("<html><title>Making sure you're not a bot!</title>" +
             "Please wait a moment while we ensure the security of your connection. " * 5 +
             "Sadly, you must enable JavaScript to get past this challenge. Protected by Anubis.</html>",
             "https://example.org/article"),
            ('<html><script id="anubis_challenge">{}</script>' + 'loading challenge ' * 30 + '</html>',
             "https://example.org/article"),
        )
        for body, final_url in cases:
            with self.subTest(final_url=final_url, body=body):
                with patch("supplement_agent.urllib.request.urlopen", return_value=Response(body, final_url)):
                    outcome = _fetch_url("https://example.org/article")
                self.assertEqual(outcome.status, "blocked")
                self.assertEqual(outcome.error_code, "CONTENT_NOT_VERIFIED")
                self.assertIsNone(outcome.body_evidence)

        article = "<html><article>" + ("substantive evidence text " * 20) + "</article></html>"
        with patch(
            "supplement_agent.urllib.request.urlopen",
            return_value=Response(article, "https://example.org/article"),
        ):
            outcome = _fetch_url("https://example.org/article")
        self.assertEqual(outcome.status, "verified")
        self.assertEqual(outcome.final_url, "https://example.org/article")
        self.assertIsNotNone(outcome.body_evidence)

        with patch(
            "supplement_agent.urllib.request.urlopen",
            side_effect=ssl.SSLCertVerificationError(1, "certificate verify failed"),
        ):
            outcome = _fetch_url("https://example.org/article")
        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(outcome.failure_class, "permanent")
        self.assertEqual(outcome.error_code, "error_SSLCertVerificationError")
        self.assertIsNone(outcome.body_evidence)

    def test_verify_bound_candidates_quarantines_unknown_or_out_of_window_date(self):
        from supplement_agent import verify_bound_candidates

        with patch(
            "supplement_agent._fetch_url",
            return_value=FetchResult("verified", "https://example.org/agent", 200, "none", None),
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

            dynamic = verify_bound_candidates(self.request_path, "technology")["draft"]

        self.assertEqual(dynamic["status"], "degraded")
        self.assertEqual(dynamic["failure_kind"], "published_at_conflict")
        self.assertEqual(dynamic["candidates"], [])
        self.assertEqual(
            dynamic["bound_candidate_decisions"][0]["decision"],
            "date_disqualified",
        )

    def test_fifth_access_attempt_is_rejected_without_erasing_draft(self):
        from supplement_agent import verify_bound_candidates

        with patch("supplement_agent._fetch_url", return_value=FetchResult("verified", "https://example.org/agent", 200, "none", None)), patch("supplement_agent.time.sleep"):
            dynamic = verify_bound_candidates(self.request_path, "technology")["draft"]
        # Observed failure: four initial probes plus an appended blocked recheck.
        first = deepcopy(dynamic["access_log"][0])
        dynamic["access_log"] = [deepcopy(first) for _ in range(4)]
        for i, access in enumerate(dynamic["access_log"][1:], 1):
            access["requested_url"] = access["final_url"] = f"https://example.org/article-{i}"
        dynamic["candidates"].append(deepcopy(dynamic["candidates"][0]))
        blocked = deepcopy(dynamic["access_log"][0])
        blocked.update(status="blocked", failure_class="permanent", error_code="BOT_CHALLENGE")
        dynamic["access_log"].append(blocked)
        draft = Path(self.request["execution_packets"][0]["output_paths"]["draft"])
        draft.write_text(json.dumps(dynamic), encoding="utf-8")
        original = draft.read_bytes()
        with self.assertRaisesRegex(RunContractError, "5 attempts; exceeds max_urls=4"):
            assemble_result(self.request_path, "technology", dynamic)
        self.assertEqual(draft.read_bytes(), original)

    def test_verify_bound_preflights_overbudget_and_repeated_urls_without_fetch_or_write(self):
        from supplement_agent import verify_bound_candidates

        draft = Path(self.request["execution_packets"][0]["output_paths"]["draft"])
        draft.write_bytes(b"original evidence")
        for urls, message in (([f"https://example.org/{i}" for i in range(4)], "exceeds max_urls"), (["https://example.org/agent"], "must not repeat")):
            with self.subTest(urls=urls), patch("supplement_agent._fetch_url") as fetch:
                with self.assertRaisesRegex(RunContractError, message):
                    verify_bound_candidates(self.request_path, "technology", urls=urls)
                fetch.assert_not_called()
                self.assertEqual(draft.read_bytes(), b"original evidence")

    def test_verify_bound_preserves_no_http_response(self):
        from supplement_agent import verify_bound_candidates

        with patch("supplement_agent._fetch_url", return_value=FetchResult("blocked", "https://example.org/agent", None, "permanent", "error_SSLCertVerificationError")), patch("supplement_agent.time.sleep"):
            dynamic = verify_bound_candidates(self.request_path, "technology")["draft"]
        self.assertIsNone(dynamic["access_log"][0]["http_status"])
        _, result = assemble_result(self.request_path, "technology", dynamic)
        self.assertEqual(result["coverage"], {"attempted": 1, "succeeded": 0, "failed": 1})

    def test_verify_bound_candidates_generates_valid_draft(self):
        from supplement_agent import verify_bound_candidates

        # Mock _fetch_url to avoid network calls in unit tests
        with patch("supplement_agent._fetch_url") as mock_fetch:
            mock_fetch.return_value = FetchResult("verified", "https://example.org/agent", 200, "none", None)
            dynamic = verify_bound_candidates(
                self.request_path,
                "technology",
                write_draft=True,
            )["draft"]
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


class BoundedBodyTransportTests(unittest.TestCase):
    def test_p1_all_content_encoding_headers_before_read(self):
        from email.message import Message

        from supplement_agent import _fetch_url

        cases = [([], True), (['identity'], True), (['IdEnTiTy'], True),
                 (['identity', 'gzip'], False), (['IdEnTiTy', 'GZiP'], False),
                 (['gzip', 'identity'], False), (['identity', 'identity'], False),
                 (['identity, gzip'], False), (['identity, identity'], False), ([''], False)]
        for encodings, accepted in cases:
            with self.subTest(encodings=encodings):
                response = ArticleResponse('Article evidence. ' * 40)
                response.headers = Message()
                response.headers['Content-Type'] = 'text/html'
                for index, value in enumerate(encodings):
                    response.headers['Content-Encoding' if index == 0 else 'cOnTeNt-EnCoDiNg'] = value
                with patch('supplement_agent.urllib.request.urlopen', return_value=response):
                    result = _fetch_url('https://example.org/article')
                self.assertEqual(result.status, 'verified' if accepted else 'blocked')
                if not accepted:
                    self.assertEqual(response.read_limits, [])
                    self.assertIsNone(result.body_evidence)
                    self.assertEqual(result.error_code, 'UNEXPECTED_CONTENT_ENCODING')

    def test_p1_real_httpresponse_framing_completion(self):
        from http.client import HTTPResponse
        from unittest.mock import Mock

        from supplement_agent import MAX_FETCH_BODY_BYTES, _fetch_url

        class Socket:
            def __init__(self, raw):
                self.stream = io.BytesIO(raw)

            def makefile(self, mode):
                assert mode == 'rb'
                return self.stream

        body = b'a' * 300000
        chunk = f'{len(body):x}\r\n'.encode() + body + b'\r\n'
        cases = [
            ('short-content-length', [('Content-Length', '400000')], body, False, True),
            ('complete-content-length', [('Content-Length', str(len(body)))], body, True, True),
            ('eof-delimited', [], body, True, True),
            ('valid-chunked', [('Transfer-Encoding', 'chunked')], chunk + b'0\r\n\r\n', True, True),
            ('mixed-case-chunked', [('Transfer-Encoding', 'ChUnKeD')], chunk + b'0\r\n\r\n', True, True),
            ('missing-terminal-chunk', [('Transfer-Encoding', 'chunked')], chunk, False, True),
            ('short-chunk', [('Transfer-Encoding', 'chunked')], b'70000\r\n' + body, False, True),
            ('cl-and-te', [('Content-Length', str(len(body))), ('Transfer-Encoding', 'chunked')], chunk + b'0\r\n\r\n', False, False),
            ('duplicate-cl-conflict', [('Content-Length', str(len(body))), ('cOnTeNt-LeNgTh', '400000')], body, False, False),
            ('duplicate-cl-identical', [('Content-Length', str(len(body)))] * 2, body, False, False),
            ('comma-cl', [('Content-Length', '300000, 300000')], body, False, False),
            ('invalid-cl', [('Content-Length', 'invalid')], body, False, False),
            ('negative-cl', [('Content-Length', '-1')], body, False, False),
            ('signed-cl', [('Content-Length', '+300000')], body, False, False),
            ('empty-cl', [('Content-Length', '')], body, False, False),
            ('unsupported-te', [('Transfer-Encoding', 'gzip')], body, False, False),
            ('comma-te', [('Transfer-Encoding', 'chunked, gzip')], body, False, False),
            ('duplicate-te', [('Transfer-Encoding', 'chunked'), ('tRaNsFeR-EnCoDiNg', 'gzip')], chunk + b'0\r\n\r\n', False, False),
            ('duplicate-chunked', [('Transfer-Encoding', 'chunked')] * 2, chunk + b'0\r\n\r\n', False, False),
            ('empty-te', [('Transfer-Encoding', '')], body, False, False),
            ('trailing-space-te', [('Transfer-Encoding', 'chunked ')], body, False, False),
        ]
        for size in (MAX_FETCH_BODY_BYTES - 1, MAX_FETCH_BODY_BYTES, MAX_FETCH_BODY_BYTES + 1):
            payload = b'a' * size
            cases.append((f'cap-cl-{size}', [('Content-Length', str(size))], payload,
                          size <= MAX_FETCH_BODY_BYTES, True))
            cases.append((f'cap-chunked-{size}', [('Transfer-Encoding', 'chunked')],
                          f'{size:x}\r\n'.encode() + payload + b'\r\n0\r\n\r\n',
                          size <= MAX_FETCH_BODY_BYTES, True))
            cases.append((f'cap-eof-{size}', [], payload, size <= MAX_FETCH_BODY_BYTES, True))
        for name, headers, payload, accepted, read_expected in cases:
            with self.subTest(case=name):
                raw = (b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n' +
                       b''.join(f'{key}: {value}\r\n'.encode() for key, value in headers) +
                       b'\r\n' + payload)
                response = HTTPResponse(Socket(raw))
                response.begin()
                response.url = 'https://example.org/article'
                original_read = response.read
                response.read = Mock(wraps=original_read)
                with patch('supplement_agent.urllib.request.urlopen', return_value=response):
                    result = _fetch_url(response.url)
                self.assertEqual(result.status, 'verified' if accepted else 'blocked')
                self.assertEqual(response.read.call_count, int(read_expected))
                if read_expected:
                    response.read.assert_called_once_with(MAX_FETCH_BODY_BYTES + 1)
                if accepted:
                    self.assertIsNotNone(result.body_evidence)
                    self.assertFalse(result.body_evidence['body_truncated'])
                else:
                    self.assertIsNone(result.body_evidence)
                if name == 'short-content-length':
                    self.assertEqual(result.error_code, 'INCOMPLETE_HTTP_BODY')
                if name == 'complete-content-length':
                    self.assertEqual(result.body_evidence['body_bytes'], len(body))
                    self.assertEqual(result.body_evidence['body_sha256'], hashlib.sha256(body).hexdigest())

    def test_cap_edges_and_identity_request_without_reaccess(self):
        from supplement_agent import MAX_FETCH_BODY_BYTES, _fetch_url

        for size in (MAX_FETCH_BODY_BYTES - 1, MAX_FETCH_BODY_BYTES, MAX_FETCH_BODY_BYTES + 1):
            with self.subTest(size=size):
                response = ArticleResponse(b'a' * size, 'text/plain')
                with patch('supplement_agent.urllib.request.urlopen', return_value=response) as fetch:
                    result = _fetch_url('https://example.org/article')
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(fetch.call_args.args[0].get_header('Accept-encoding'), 'identity')
                self.assertEqual(response.read_limits, [MAX_FETCH_BODY_BYTES + 1])
                self.assertEqual(result.status, 'blocked' if size > MAX_FETCH_BODY_BYTES else 'verified')
                if size > MAX_FETCH_BODY_BYTES:
                    self.assertIsNone(result.body_evidence)

                    self.assertEqual(result.error_code, 'BODY_BYTE_LIMIT_EXCEEDED')
                else:
                    assert result.body_evidence is not None
                    self.assertEqual(result.body_evidence['body_bytes'], size)
                    self.assertFalse(result.body_evidence['body_truncated'])
                    self.assertLessEqual(len(json.dumps(result.body_evidence['text'], ensure_ascii=False).encode()), 6000)

    def test_compression_rejected_before_read(self):
        from supplement_agent import _fetch_url

        for encoding in ('gzip', 'br', 'deflate', 'identity, gzip'):
            with self.subTest(encoding=encoding):
                response = ArticleResponse('Article evidence. ' * 40)
                response.headers['Content-Encoding'] = encoding
                with patch('supplement_agent.urllib.request.urlopen', return_value=response) as fetch:
                    result = _fetch_url('https://example.org/article')
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(response.read_limits, [])
                self.assertEqual(result.status, 'blocked')
                self.assertIsNone(result.body_evidence)
                self.assertEqual(result.error_code, 'UNEXPECTED_CONTENT_ENCODING')


    def test_slow_recognition_or_excerpt_never_verified_after_original_deadline(self):
        from types import SimpleNamespace

        import supplement_agent as agent
        from supplement_agent import _fetch_url

        for seam in ('_recognizable_document_body', '_document_body_evidence'):
            with self.subTest(seam=seam):
                clock = [100.0]
                original = getattr(agent, seam)
                def slow(*args, _original=original, _clock=clock, **kwargs):
                    output = _original(*args, **kwargs)
                    _clock[0] = 108.01
                    return output
                with patch.object(agent, 'time', SimpleNamespace(monotonic=lambda clock=clock: clock[0])), patch.object(agent, seam, slow), patch('supplement_agent.urllib.request.urlopen', return_value=ArticleResponse('Visible evidence. ' * 40)):
                    result = _fetch_url('https://example.org/article', 8.0)
                self.assertEqual(result.status, 'blocked')
                self.assertEqual(result.error_code, 'HTTP_DEADLINE_EXCEEDED')
                self.assertIsNone(result.body_evidence)


if __name__ == "__main__":
    unittest.main()
