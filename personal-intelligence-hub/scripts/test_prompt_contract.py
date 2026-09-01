import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class PromptContractTests(unittest.TestCase):
    def test_supplement_agents_use_bound_result_envelope(self):
        config = json.loads(
            (ROOT / "references" / "subagent_prompts.json").read_text(encoding="utf-8")
        )

        self.assertEqual(config["contract_version"], "subagent-prompts/2.0")
        review_transfer = config["execution_policy"]["review_context_transfer"]
        self.assertEqual(review_transfer["mode"], "compact_helper_packet")
        self.assertFalse(review_transfer["inherit_conversation_history"])
        self.assertEqual(
            review_transfer["authoritative_packet_field"],
            "agent_helper_context",
        )
        self.assertIn("candidate_pool", review_transfer["forbidden_redundant_reads"])
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
        self.assertIn(
            "degraded 或 failed 必须写规范化 failure_kind",
            config["common_contract"]["infrastructure_failure_rule"],
        )
        self.assertEqual(len(config["result_envelope"]["allOf"]), 2)

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
                "finalization",
                "tool_budget",
                "agent_helper",
                "task_message",
            }.issubset(set(policy["context_transfer"]["required_fields"]))
        )
        self.assertEqual(policy["parallelism"]["max_supplement_workers"], 3)
        self.assertEqual(
            policy["parallelism"]["overflow_strategy"],
            "canary_first_then_bounded_fanout",
        )
        self.assertTrue(policy["parallelism"]["one_gap_per_worker"])
        self.assertEqual(
            policy["observability"]["normal_run_token_ceiling"], 250000
        )
        self.assertEqual(
            policy["observability"]["normal_run_token_meter"],
            "total_tokens - cache_read_tokens - cache_write_tokens",
        )
        self.assertEqual(policy["observability"]["semantic_timeout_ms"], 240000)
        self.assertEqual(policy["observability"]["red_team_timeout_ms"], 120000)
        self.assertEqual(
            policy["observability"]["supplement_finalization_grace_seconds"],
            60,
        )
        self.assertEqual(policy["observability"]["supplement_tool_budget_soft"], 8)
        self.assertEqual(policy["observability"]["supplement_tool_budget_hard"], 12)
        self.assertEqual(
            policy["observability"]["normal_run_cost_usd_ceiling"], 3.0
        )
        self.assertIn(
            "session_telemetry.py",
            policy["observability"]["telemetry_command"],
        )
        self.assertTrue(policy["readiness"]["artifact_first"])
        self.assertEqual(
            policy["readiness"]["primary_signal"],
            "agent_helper_draft_ready_or_review_artifact_ready_control_message_with_path_and_sha256",
        )
        self.assertEqual(
            policy["publication"]["mode"],
            "supplement_dynamic_draft_then_agent_helper_then_deterministic_parent_finalizer",
        )
        self.assertEqual(policy["readiness"]["watch_mode"], "single_fallback_only")
        self.assertLessEqual(policy["readiness"]["watch_timeout_seconds"], 10)
        self.assertEqual(
            policy["readiness"]["completion_strategy"],
            "async_nonblocking_wakeup",
        )
        self.assertTrue(policy["readiness"]["forbid_interactive_blocking_wait"])
        self.assertEqual(policy["readiness"]["max_blocking_wait_calls"], 0)
        self.assertEqual(
            policy["readiness"]["timeout_decision"], "degraded_timeout"
        )
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
            "resume_only_on_completion_wakeup_or_progress_event",
        )
        self.assertIn(
            "review_progress_gate.py",
            policy["readiness"]["progress_gate_command"],
        )
        self.assertIn(
            "--milestone-seq",
            policy["readiness"]["progress_gate_command"],
        )
        self.assertIn(
            "--progress-id <gap_id>",
            policy["readiness"]["supplement_progress_gate_command"],
        )
        self.assertIn(
            "--review-kind supplement",
            policy["readiness"]["supplement_progress_gate_command"],
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

    def test_skill_progress_examples_match_current_cli_and_drafts(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("--invocation-id <semantic_request.invocation_id>", skill)
        self.assertIn("--request-sha256 <manifest.artifacts.semantic_review_request.artifact_sha256>", skill)
        self.assertIn("--watch-path <semantic-dynamic-draft>", skill)
        self.assertNotIn("--watch-path <semantic-decision-draft>", skill)
        self.assertNotIn("--watch-path <semantic-receipt-draft>", skill)
        self.assertIn("run_daily.py reconcile-supplement", skill)

    def test_run_manifest_schema_declares_aggregate_failure_telemetry(self):
        schema = json.loads(
            (ROOT / "references" / "run_manifest_schema.json").read_text(
                encoding="utf-8"
            )
        )

        telemetry = schema["telemetry_contract"]
        self.assertEqual(telemetry["version"], "pih-execution-telemetry/1.0")
        self.assertEqual(telemetry["content_policy"], "aggregate_only_no_message_content")
        self.assertTrue(telemetry["failure_usage_included"])
        self.assertEqual(telemetry["normal_run_token_ceiling"], 250000)
        self.assertEqual(
            telemetry["token_meter"],
            "total_tokens - cache_read_tokens - cache_write_tokens",
        )
        self.assertTrue(telemetry["raw_total_tokens_retained_for_observability"])
        self.assertEqual(telemetry["normal_run_cost_usd_ceiling"], 3.0)
        self.assertTrue(telemetry["new_launches_blocked_at_ceiling"])
        self.assertTrue(telemetry["token_reservation_required_before_launch"])
        self.assertTrue(telemetry["cost_reservation_required_before_launch"])
        self.assertEqual(
            telemetry["reservation_registry"],
            "manifest.telemetry.reservations",
        )
        self.assertIn("unavailable_telemetry_keeps_full_reservation", telemetry["settlement_rule"])
        self.assertEqual(
            telemetry["runtime_usage_budget_semantics"],
            "launch_and_future_launch_gate_not_running_interrupt",
        )
        supplement_execution = schema["supplement_execution_contract"]
        self.assertTrue(supplement_execution["timeout_includes_finalization_grace"])
        self.assertTrue(supplement_execution["tool_budget_pass_through_required"])
        self.assertIn("supplement_agent.py", supplement_execution["context_helper"])
        self.assertEqual(
            schema["supplement_progress_contract"]["durable_terminal_statuses"],
            ["degraded_timeout", "declare_lost"],
        )
        review_execution = schema["review_execution_contract"]
        self.assertTrue(review_execution["timeout_pass_through_required"])
        self.assertEqual(review_execution["semantic_context_mode"], "compact_helper_packet")
        self.assertEqual(review_execution["semantic_token_budget"], 40000)
        self.assertEqual(review_execution["semantic_tool_budget"]["hard"], 10)
        self.assertEqual(review_execution["red_team_token_budget"], 30000)

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
        semantic = config["review_agents"]["SemanticEvaluator"]
        red_team = config["review_agents"]["RedTeam"]
        for contract in (semantic, red_team):
            self.assertGreaterEqual(contract["max_turns"], 1)
            self.assertTrue(contract["halt_condition"])
        self.assertNotIn("challenge", semantic["output_contract"])
        self.assertIn("challenge", red_team["output_contract"])
        self.assertIn("turns_used", red_team["output_contract"])
        self.assertEqual(semantic["max_turns"], 2)
        self.assertIn("不得重新联网核验已登记 URL", semantic["system_prompt"])
        self.assertIn("semantic-dynamic", semantic["system_prompt"])
        self.assertIn(
            "semantic-decision/1.0",
            config["review_agents"]["SemanticEvaluator"]["output_contract"],
        )
        self.assertIn("帮助脚本负责日期规范化", semantic["system_prompt"])
        self.assertIn("agent_helper.finalize_command", semantic["system_prompt"])
        self.assertIn("静态证据复制", semantic["system_prompt"])
        self.assertIn("event_id", semantic["system_prompt"])
        self.assertIn(
            "input_validated",
            config["review_agents"]["SemanticEvaluator"]["progress_contract"],
        )
        self.assertIn(
            "进度指纹",
            config["execution_policy"]["readiness"]["lost_agent_rule"],
        )
        self.assertIn(
            "deterministic_fast_path=true",
            config["review_agents"]["RedTeam"]["system_prompt"],
        )
        self.assertIn(
            "validation_command",
            config["review_agents"]["RedTeam"]["system_prompt"],
        )
        self.assertIn(
            "targeted_review",
            config["review_agents"]["RedTeam"]["system_prompt"],
        )
        self.assertIn(
            "targeted_review 成功状态均为 passed",
            config["review_agents"]["RedTeam"]["output_contract"],
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
