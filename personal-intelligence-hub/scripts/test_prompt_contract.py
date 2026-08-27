import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class PromptContractTests(unittest.TestCase):
    def test_supplement_agents_use_bound_result_envelope(self):
        config = json.loads(
            (ROOT / "references" / "subagent_prompts.json").read_text(encoding="utf-8")
        )

        self.assertEqual(config["contract_version"], "subagent-prompts/1.9")
        review_transfer = config["execution_policy"]["review_context_transfer"]
        self.assertEqual(
            review_transfer["mode"],
            "self_contained_registered_request",
        )
        self.assertFalse(review_transfer["inherit_conversation_history"])
        self.assertEqual(
            review_transfer["authoritative_packet_field"],
            "execution_packet",
        )
        self.assertEqual(config["invocation_order"][0], "baseline_candidates")
        required = set(config["result_envelope"]["required"])
        self.assertTrue(
            {
                "run_id",
                "request_sha256",
                "baseline_sha256",
                "candidate_pool_sha256",
                "gap_id",
                "status",
                "executed_queries",
                "access_log",
                "candidates",
                "coverage",
                "confidence",
                "data_provenance",
                "turns_used",
                "halt_condition_met",
            }.issubset(required)
        )
        candidate_contract = config["result_envelope"]["properties"]["candidates"][
            "items"
        ]
        self.assertTrue(
            {"identity_quality", "event_id", "event_identity"}.issubset(
                set(candidate_contract["required"])
            )
        )
        self.assertEqual(
            set(candidate_contract["properties"]["event_identity"]["required"]),
            {
                "key_version",
                "primary_domain",
                "actor",
                "action",
                "object",
                "event_date",
            },
        )
        self.assertFalse(
            candidate_contract["properties"]["event_identity"][
                "additionalProperties"
            ]
        )
        for name in ("TechRadar", "HealthcareRadar", "Sentinel", "Ranger"):
            prompt = config["supplement_agents"][name]["system_prompt"]
            self.assertIn("先处理绑定的基线候选", prompt)
            self.assertIn("common_contract.identity_rule", prompt)
            self.assertIn("无增量", prompt)
        self.assertIn(
            "generate_event_id(event_identity)",
            config["common_contract"]["identity_rule"],
        )

        policy = config["execution_policy"]
        self.assertEqual(policy["context_transfer"]["mode"], "minimal_task_packet")
        self.assertFalse(policy["context_transfer"]["inherit_conversation_history"])
        self.assertEqual(
            policy["context_transfer"]["payload_mode"],
            "path_references_not_embedded_file_bytes",
        )
        self.assertTrue(
            {
                "run_manifest_path",
                "bound_input_paths",
                "assigned_gap_ids",
                "assigned_lanes",
                "output_path_by_gap",
                "per_gap_max_turns",
                "per_gap_halt_condition",
            }.issubset(set(policy["context_transfer"]["required_fields"]))
        )
        self.assertEqual(policy["parallelism"]["max_supplement_workers"], 3)
        self.assertEqual(
            policy["parallelism"]["overflow_strategy"],
            "launch_fresh_worker_when_first_slot_frees",
        )
        self.assertTrue(policy["parallelism"]["one_gap_per_worker"])
        self.assertTrue(policy["readiness"]["artifact_first"])
        self.assertEqual(
            policy["readiness"]["primary_signal"],
            "artifact_ready_control_message_with_path_and_sha256",
        )
        self.assertEqual(policy["readiness"]["watch_mode"], "single_fallback_only")
        self.assertLessEqual(policy["readiness"]["watch_timeout_seconds"], 10)
        self.assertEqual(policy["readiness"]["max_unchanged_wait_timeouts"], 2)
        self.assertEqual(policy["readiness"]["wait_timeout_seconds"], 60)
        self.assertEqual(
            policy["readiness"]["supplement_progress_messages"],
            [
                "supplement_progress seq=1 phase=input_validated",
                "supplement_progress seq=2 phase=source_checked",
            ],
        )
        self.assertEqual(
            policy["readiness"]["relaunch_policy"],
            "forbidden_for_same_registered_request; create_a_new_run_for_a_new_attempt",
        )
        self.assertEqual(
            policy["readiness"]["after_wait_gate"],
            "stop_waiting_until_artifact_control_message_or_progress_fingerprint_changes",
        )
        self.assertIn(
            "review_progress_gate.py",
            policy["readiness"]["progress_gate_command"],
        )
        self.assertIn(
            "--milestone-seq",
            policy["readiness"]["progress_gate_command"],
        )
        for command_name in ("progress_gate_command", "progress_gate_watch_command"):
            for flag in (
                "--manifest",
                "--review-kind",
                "--invocation-id",
                "--request-sha256",
            ):
                self.assertIn(flag, policy["readiness"][command_name])
        self.assertFalse(
            policy["source_efficiency"]["retry_same_url_on_permanent_failure"]
        )
        self.assertEqual(
            policy["source_efficiency"][
                "max_consecutive_permanent_failures_per_host"
            ],
            2,
        )
        self.assertEqual(
            policy["review_sequence"],
            [
                "register_semantic_request",
                "validate_semantic_drafts",
                "publish_semantic_outputs",
                "validate_semantic_and_register_red_team_request",
                "validate_red_team_draft",
                "publish_red_team_receipt",
                "register_review_bundle",
            ],
        )

    def test_semantic_prompt_targets_v14_and_emits_receipt(self):
        text = (ROOT / "references" / "prompts" / "v1_refine_system.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("briefing_schema.json` 1.4", text)
        self.assertIn("review-receipt/1.0", text)
        self.assertIn("run_id", text)
        self.assertIn("baseline_sha256", text)
        self.assertIn("candidate_funnel", text)
        self.assertIn("semantic_review_request.json", text)
        self.assertIn("challenge", text)
        self.assertIn("lineage_bindings", text)
        self.assertIn("access_log_sha256", text)
        self.assertIn("history_review_slice.json", text)
        self.assertIn("原样复制已登记 review request.input_bundle_sha256", text)
        self.assertIn("强制 `history_review_slice`", text)
        self.assertIn("可选 `focus_config`", text)
        self.assertNotIn("由 baseline、history_snapshot、candidate_pool、supplement、window 与 mix_request 计算", text)
        self.assertIn("不得读取完整历史索引", text)
        self.assertIn("generate_event_id(event_identity)", text)
        self.assertIn("旧 baseline 无 identity 只能作为单一主证据", text)
        self.assertIn("每个 candidate URL 都必须在本次回执中有 verified access", text)
        self.assertNotIn("绑定的历史快照", text)

        config = json.loads(
            (ROOT / "references" / "subagent_prompts.json").read_text(encoding="utf-8")
        )
        access_contract = config["result_envelope"]["properties"]["access_log"]["items"]
        self.assertEqual(
            access_contract["properties"]["failure_class"]["enum"],
            ["none", "transient", "permanent"],
        )
        blocked_contract = access_contract["allOf"][0]["then"]
        self.assertEqual(
            set(blocked_contract["required"]),
            {"failure_class", "error_code"},
        )
        for name in ("SemanticEvaluator", "RedTeam"):
            contract = config["review_agents"][name]
            self.assertGreaterEqual(contract["max_turns"], 1)
            self.assertTrue(contract["halt_condition"])
            self.assertIn("challenge", contract["output_contract"])
            self.assertIn("turns_used", contract["output_contract"])
        self.assertEqual(config["review_agents"]["SemanticEvaluator"]["max_turns"], 2)
        self.assertIn(
            "不得重新联网访问已经 verified 的 URL",
            config["review_agents"]["SemanticEvaluator"]["system_prompt"],
        )
        self.assertIn(
            "validate-semantic-draft",
            config["review_agents"]["SemanticEvaluator"]["system_prompt"],
        )
        self.assertIn(
            "multi_independent",
            config["review_agents"]["SemanticEvaluator"]["system_prompt"],
        )
        self.assertIn(
            "每个 candidate.url 都须出现在本回执 verified access_log",
            config["review_agents"]["SemanticEvaluator"]["system_prompt"],
        )
        self.assertIn(
            "YYYY-MM-DD",
            config["review_agents"]["SemanticEvaluator"]["system_prompt"],
        )
        self.assertIn(
            "input_validated",
            config["review_agents"]["SemanticEvaluator"]["progress_contract"],
        )
        self.assertIn(
            "进度指纹",
            config["execution_policy"]["readiness"]["lost_agent_rule"],
        )
        self.assertIn(
            "no_l4_fast_path",
            config["review_agents"]["RedTeam"]["system_prompt"],
        )
        self.assertIn(
            "validation_command",
            config["review_agents"]["RedTeam"]["system_prompt"],
        )
        self.assertIn("永久失败", config["common_contract"]["failure_rule"])
        self.assertIn(
            "supplement_progress seq=2 phase=source_checked",
            config["common_contract"]["progress_rule"],
        )
        self.assertIn("另一 lane", config["common_contract"]["failure_rule"])
        self.assertIn(
            "failure_kind=infrastructure",
            config["common_contract"]["infrastructure_failure_rule"],
        )


if __name__ == "__main__":
    unittest.main()
