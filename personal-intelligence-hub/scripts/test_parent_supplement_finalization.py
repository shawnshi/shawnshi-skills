"""New frozen-run CLI integration: parent assembly never resumes worker research."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from run_contract import (
    build_supplement_request,
    candidate_ref,
    create_run,
    record_run_artifact,
    record_stage,
)


class ParentSupplementFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.now(timezone.utc)
        prompts = json.loads((Path(__file__).resolve().parents[1] /
            "references/subagent_prompts.json").read_text(encoding="utf8"))
        grace = prompts["execution_policy"]["observability"]["supplement_finalization_grace_seconds"]
        created = self.now - timedelta(seconds=grace + 120)
        self.manifest_path, manifest = create_run(
            runtime_dir=self.root, skill_path=Path(__file__).resolve().parents[1] / "SKILL.md",
            now=created,
        )
        self.run_dir = Path(manifest["run_dir"])
        self.snapshot = Path(manifest["skill_path"]).parent
        baseline = self.run_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf8")
        record_stage(self.manifest_path, "baseline", "completed", artifact_path=baseline,
                     metadata={"source_total": 1, "source_ok": 1, "source_failed": 0}, now=created)
        pool = self.run_dir / "candidate_pool.json"
        self.url = "https://example.org/agent"
        pool.write_text(json.dumps({"items": [{"title": "Agent release", "url": self.url,
            "published_at": self.now.date().isoformat(), "published_at_source": "rss_published",
            "source": "Example", "source_type": "primary", "provisional_domain": "technology"}]}), encoding="utf8")
        record_run_artifact(self.manifest_path, "candidate_pool", pool, now=created)
        self.request_path, self.request = build_supplement_request(self.manifest_path, [{
            "gap_id": "technology", "lane": "TechRadar", "query_scope": "AI agents",
            "max_turns": 3, "max_urls": 4, "verify_bound_candidates": True}], now=created)
        self.packet = self.request["execution_packets"][0]
        self.draft = Path(self.packet["output_paths"]["draft"])
        self.final = Path(self.packet["output_paths"]["result"])
        self.dynamic = {"status": "no_increment", "executed_queries": ["direct source check"],
            "access_log": [{"status": "verified", "checked_at": (self.now-timedelta(seconds=2)).isoformat(),
                "method": "http_get", "requested_url": self.url, "final_url": self.url,
                "http_status": 200, "failure_class": "none", "error_code": None}],
            "bound_candidate_decisions": [{"candidate_id": candidate_ref(self.url),
                "decision": "source_quality_rejected", "reason": "No substantive article evidence"}],
            "candidates": [], "confidence": "low", "turns_used": 1, "halt_condition_met": True,
            "started_at": (self.now-timedelta(seconds=3)).isoformat(),
            "completed_at": (self.now-timedelta(seconds=1)).isoformat()}
        self.dynamic["status"] = "completed"
        self.dynamic["bound_candidate_decisions"][0].update(
            decision="registered", reason="Verified primary article within the window")
        self.dynamic["candidates"] = [{
            "candidate_id": candidate_ref(self.url), "title": "Agent release", "url": self.url,
            "source": "Example", "published_at": self.now.date().isoformat(),
            "published_at_source": "source page", "retrieved_at": self.dynamic["access_log"][0]["checked_at"],
            "primary_domain": "technology", "secondary_domains": [], "source_type": "primary",
            "identity_quality": "semantic", "event_identity": {"key_version": "1",
                "primary_domain": "technology", "actor": "Example", "action": "published",
                "object": "Agent release", "event_date": self.now.date().isoformat()},
            "access_check": dict(self.dynamic["access_log"][0]),
            "summary": "Example published an agent release.",
        }]
        self.raw = json.dumps(self.dynamic, indent=3).encode()
        self.draft.write_bytes(self.raw)

    def helper(self, parent=True):
        return subprocess.run([sys.executable, "-X", "utf8", str(self.snapshot / "scripts/supplement_agent.py"),
            "finalize", "--request", str(self.request_path), "--gap-id", "technology",
            *(["--parent"] if parent else [])], cwd=self.snapshot, capture_output=True, text=True)

    def test_exhausted_worker_parent_finalizes_same_payload_and_registers(self):
        self.assertEqual(self.packet["tool_budget"], {"soft": 8, "hard": 12, "block": "*"})
        # Expected bytes come from the existing deterministic worker helper, not invented receipts.
        ordinary = self.helper(parent=False)
        self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
        expected = self.draft.read_bytes()
        self.draft.write_bytes(self.raw)
        # Worker is exhausted: only the parent invokes another CLI, no child calls/relaunch.
        parent = self.helper()
        self.assertEqual(parent.returncode, 0, parent.stderr)
        self.assertEqual(self.draft.read_bytes(), expected)
        again = self.helper()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.draft.read_bytes(), expected)
        self.assertEqual(json.loads(again.stdout)["assembly"], "already_assembled")
        registration = subprocess.run([sys.executable, "-X", "utf8", str(self.snapshot / "scripts/run_daily.py"),
            "finalize-supplement", "--manifest", str(self.manifest_path), "--request", str(self.request_path),
            "--draft", str(self.draft)], cwd=self.snapshot, capture_output=True, text=True)
        self.assertEqual(registration.returncode, 0, registration.stderr)
        self.assertEqual(self.final.read_bytes(), expected)
        aggregate = json.loads((self.run_dir / "supplement_results.json").read_text(encoding="utf8"))
        self.assertEqual(aggregate["results"], [json.loads(expected)])
        self.assertEqual(aggregate["status"], "completed")
        self.assertEqual(aggregate["results"][0]["completed_at"], self.dynamic["completed_at"])
        self.assertEqual(len(aggregate["results"][0]["candidates"]), 1)
        self.assertEqual(aggregate["coverage"], {"attempted": 1, "succeeded": 1, "failed": 0})

    def test_rejected_drafts_preserve_exact_bytes_and_publish_nothing(self):
        for case in ("malformed", "missing", "partial", "expired", "late_source", "declare_lost", "terminal"):
            with self.subTest(case=case):
                self.draft.write_bytes(self.raw)
                state_path = Path(self.packet["progress"]["state_path"])
                state_path.unlink(missing_ok=True)
                manifest_raw = self.manifest_path.read_bytes()
                if case == "malformed":
                    self.draft.write_bytes(b'{not JSON\n')
                if case == "missing":
                    self.draft.unlink()
                if case == "partial":
                    self.draft.write_bytes(b'{"status":"no_increment"}')
                if case in {"expired", "late_source"}:
                    dynamic = json.loads(self.raw)
                    if case == "expired":
                        for key in ("started_at", "completed_at"):
                            dynamic[key] = (datetime.fromisoformat(dynamic[key])-timedelta(seconds=self.packet["finalization"]["grace_seconds"] + 1)).isoformat()
                        dynamic["access_log"][0]["checked_at"] = dynamic["started_at"]
                    else:
                        dynamic["started_at"] = (self.now-timedelta(seconds=1000)).isoformat()
                    self.draft.write_text(json.dumps(dynamic), encoding="utf8")
                if case == "declare_lost":
                    state_path.write_text(json.dumps({"progress_id": "technology", "terminal_status": "declare_lost"}), encoding="utf8")
                if case == "terminal":
                    manifest = json.loads(manifest_raw)
                    manifest["stages"]["supplemental"]["status"] = "failed"
                    self.manifest_path.write_text(json.dumps(manifest), encoding="utf8")
                expected_manifest = self.manifest_path.read_bytes()
                before = self.draft.read_bytes() if self.draft.exists() else None
                result = self.helper()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.draft.read_bytes() if self.draft.exists() else None, before)
                self.assertFalse(self.final.exists())
                self.assertFalse((self.run_dir / "supplement_results.json").exists())
                self.assertFalse(self.final.with_suffix(".failure.json").exists())
                self.assertEqual(self.manifest_path.read_bytes(), expected_manifest)
                self.manifest_path.write_bytes(manifest_raw)

    def _assert_assembled_fallback_rejected(self, case):
        if case == "expired":
            dynamic = self.dynamic
            for key in ("started_at", "completed_at"):
                dynamic[key] = (datetime.fromisoformat(dynamic[key]) - timedelta(seconds=self.packet["finalization"]["grace_seconds"] + 1)).isoformat()
            dynamic["access_log"][0]["checked_at"] = dynamic["started_at"]
            dynamic["candidates"][0]["access_check"]["checked_at"] = dynamic["started_at"]
            dynamic["candidates"][0]["retrieved_at"] = dynamic["started_at"]
            self.draft.write_text(json.dumps(dynamic), encoding="utf8")
        ordinary = self.helper(parent=False)
        self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
        self.assertEqual(json.loads(self.draft.read_bytes())["contract_version"], "supplement-result/1.0")
        state_path = Path(self.packet["progress"]["state_path"])
        if case == "declare_lost":
            state_path.write_text(json.dumps({"progress_id": "technology", "terminal_status": "declare_lost"}), encoding="utf8")
        draft_before = self.draft.read_bytes()
        manifest_before = self.manifest_path.read_bytes()
        state_before = state_path.read_bytes() if state_path.exists() else None
        self.assertEqual(json.loads(manifest_before)["stages"]["supplemental"]["status"], "pending")
        # Every parent fallback, including already assembled, must guard before registration.
        result = self.helper()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("terminal progress" if case == "declare_lost" else "grace expired", result.stderr)
        self.assertEqual(self.draft.read_bytes(), draft_before)
        self.assertEqual(self.manifest_path.read_bytes(), manifest_before)
        self.assertEqual(state_path.read_bytes() if state_path.exists() else None, state_before)
        self.assertFalse(self.final.exists())
        self.assertFalse((self.run_dir / "supplement_results.json").exists())
        self.assertFalse(self.final.with_suffix(".failure.json").exists())

    def test_already_assembled_declare_lost_fallback_is_guarded(self):
        self._assert_assembled_fallback_rejected("declare_lost")

    def test_already_assembled_expired_fallback_is_guarded(self):
        self._assert_assembled_fallback_rejected("expired")

    def test_all_parent_fallback_handoffs_require_guard_before_registration(self):
        task = self.packet["task_message"]
        self.assertIn("including already assembled drafts", task)
        self.assertIn("must first run", task)
        self.assertIn("skip reassembly, never the parent guard", task)
        context_result = subprocess.run([
            sys.executable, "-X", "utf8", str(self.snapshot / "scripts/supplement_agent.py"),
            "context", "--request", str(self.request_path), "--gap-id", "technology",
        ], cwd=self.snapshot, capture_output=True, text=True, encoding="utf8")
        self.assertEqual(context_result.returncode, 0, context_result.stderr)
        instructions = " ".join(json.loads(context_result.stdout)["draft_instructions"])
        self.assertIn("including already assembled drafts", instructions)
        self.assertIn("must first run", instructions)
        self.assertIn("skip reassembly, never the parent guard", instructions)
        prompts = json.loads(Path(self.packet["prompt_config_path"]).read_text(encoding="utf8"))
        self.assertIn("已装配 draft 也必须先通过", prompts["common_contract"]["progress_rule"])
        self.assertIn("including_already_assembled_must_pass_parent_guard", prompts["execution_policy"]["readiness"]["on_exhaustion"])
        workflow = (self.snapshot / "references/workflow_protocols.md").read_text(encoding="utf8")
        self.assertIn("已装配 draft 也必须先通过", workflow)
        self.assertNotIn("直接交现有 `finalize-supplement`", workflow)

    def test_handoff_prioritizes_persistence_before_optional_chatter(self):
        task = self.packet["task_message"]
        self.assertIn("before optional", task)
        self.assertIn("--parent", task)
        self.assertIn("hard cap", task)
        prompts = json.loads(Path(self.packet["prompt_config_path"]).read_text(encoding="utf8"))
        self.assertIn("不要求额外 chat", prompts["common_contract"]["progress_rule"])
        self.assertIn("finalize --parent", prompts["common_contract"]["progress_rule"])


if __name__ == "__main__":
    unittest.main()
