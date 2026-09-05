import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from threading import Event
from unittest.mock import patch
from zoneinfo import ZoneInfo

from briefing_gate import validate_briefing_data
from history_manager import generate_event_id
from mix_policy import select_candidates_with_mix
from run_contract import (
    RunContractError,
    _assert_execution_budget_allows_launch,
    _validate_access_log_entry,
    _validate_access_retry_policy,
    _validate_bound_candidate_source_type,
    _validate_multi_independent_lineage,
    build_review_request,
    build_supplement_request,
    candidate_object_hash,
    candidate_ref,
    calendar_window,
    canonical_json_bytes,
    create_run,
    file_sha256,
    finalize_semantic_decision,
    item_hash,
    load_manifest,
    load_review_progress_state,
    normalize_published_at,
    normalize_supplement_failure_kind,
    record_execution_telemetry,
    record_run_artifact,
    record_stage,
    reconcile_supplement_progress,
    registered_candidate_lineage,
    review_input_bundle_sha256,
    review_scope,
    register_review_receipt,
    register_supplement_results,
    update_review_progress,
    validate_resource_manifest,
    validate_review_receipt,
    validate_semantic_draft,
    validate_semantic_history,
    validate_supplement_failure_kind,
)
from review_progress_gate import evaluate_progress, main as progress_gate_main
from semantic_agent import (  # pyright: ignore[reportMissingImports]
    build_agent_context as build_semantic_agent_context,
)
from test_contract_fixtures import cloned_v14_payload


class RunContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime_dir = Path(self.directory.name)
        self.skill_file = self.runtime_dir / "SKILL.md"
        self.skill_file.write_text("skill contract", encoding="utf-8")
        skill_sha = hashlib.sha256(b"skill contract").hexdigest()
        (self.runtime_dir / "resource-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "skill": self.runtime_dir.name,
                    "skill_md": "SKILL.md",
                    "skill_md_sha256": skill_sha,
                    "top_level_file_hashes": [],
                    "declared_local_dependencies": [],
                    "missing_declared_dependencies": [],
                }
            ),
            encoding="utf-8",
        )
        self.now = datetime(2026, 8, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def test_supplement_failure_kind_is_closed_and_aliases_are_normalized(self):
        self.assertEqual(
            normalize_supplement_failure_kind("date_conflict"),
            "published_at_conflict",
        )
        self.assertEqual(
            normalize_supplement_failure_kind("bound_source_access_blocked"),
            "source_access",
        )
        with self.assertRaisesRegex(RunContractError, "failure_kind is invalid"):
            normalize_supplement_failure_kind("arbitrary_failure")
        with self.assertRaisesRegex(RunContractError, "requires failure_kind"):
            validate_supplement_failure_kind(None, "degraded")

    def test_publication_datetime_normalizes_in_its_own_timezone(self):
        self.assertEqual(
            normalize_published_at("2026-08-20T23:30:00-07:00"),
            "2026-08-20",
        )
        self.assertEqual(normalize_published_at("2026-08-20"), "2026-08-20")
        with self.assertRaisesRegex(RunContractError, "timezone-aware"):
            normalize_published_at("2026-08-20T23:30:00")

    def tearDown(self):
        self.directory.cleanup()

    def test_review_scope_selects_fast_and_full_paths(self):
        l3 = {"title": "l3", "intelligence_level": "L3", "major_signal": True}
        l4 = {"title": "l4", "intelligence_level": "L4", "major_signal": False}

        fast = review_scope(
            {"top_10": [{**l3, "major_signal": False}]}
        )
        targeted = review_scope({"top_10": [l3]})
        full = review_scope({"top_10": [l3, l4]})

        self.assertEqual(fast["review_mode"], "no_l4_fast_path")
        self.assertEqual(fast["l4_item_hashes"], [])
        self.assertEqual(fast["major_signal_item_hashes"], [])
        self.assertEqual(targeted["review_mode"], "targeted_review")
        self.assertEqual(targeted["major_signal_item_hashes"], [item_hash(l3)])
        self.assertEqual(full["review_mode"], "l4_full_review")
        self.assertEqual(full["l4_item_hashes"], [item_hash(l4)])

    def new_run(self):
        return create_run(
            runtime_dir=self.runtime_dir,
            skill_path=self.skill_file,
            report_date="2026-08-10",
            timezone_name="Asia/Shanghai",
            window_days=7,
            topic="技术与医疗数字化",
            region="中国、美国与全球",
            now=self.now,
            run_id="run-test-001",
        )

    def bind_history(self, manifest_path, entries=None):
        snapshot = self.runtime_dir / "history-snapshot.json"
        snapshot.write_text(
            json.dumps(
                {
                    "resource_kind": "pih_history_index",
                    "schema_version": "2.0",
                    "generated_at": self.now.isoformat(),
                    "entries": entries or [],
                }
            ),
            encoding="utf-8",
        )
        record_run_artifact(
            manifest_path,
            "history_snapshot",
            snapshot,
            metadata={"news_dir": str(self.runtime_dir), "archive_target_state": {"x": None}},
            now=self.now,
        )
        review_slice = self.runtime_dir / "history-review-slice.json"
        review_slice.write_text(
            json.dumps(
                {
                    "resource_kind": "pih_history_review_slice",
                    "schema_version": "1.0",
                    "generated_at": self.now.isoformat(),
                    "source_snapshot_sha256": file_sha256(snapshot),
                    "dedupe_days": 7,
                    "entries": entries or [],
                }
            ),
            encoding="utf-8",
        )
        record_run_artifact(
            manifest_path,
            "history_review_slice",
            review_slice,
            input_sha256=file_sha256(snapshot),
            now=self.now,
        )
        return snapshot

    def test_semantic_history_gate_rejects_bound_duplicate(self):
        manifest_path, _ = self.new_run()
        item = cloned_v14_payload()["top_10"][0]
        self.bind_history(
            manifest_path,
            [
                {
                    "event_id": item["event_id"],
                    "canonical_url": item["url"],
                    "urls": [item["url"]],
                    "title": item["title"],
                    "fingerprints": [],
                    "last_seen_at": self.now.isoformat(),
                }
            ],
        )

        with self.assertRaisesRegex(
            RunContractError,
            "duplicates the bound history snapshot",
        ):
            validate_semantic_history(
                {"top_10": [item]},
                load_manifest(manifest_path),
            )

    def test_registered_candidate_lineage_preserves_all_hashes_for_same_reference(self):
        reference = candidate_ref("https://example.org/source")
        first = {
            "candidate_id": reference,
            "url": "https://example.org/source",
            "title": "baseline form",
        }
        first["candidate_object_sha256"] = candidate_object_hash(first)
        second = {
            "candidate_id": reference,
            "url": "https://example.org/source",
            "title": "supplement form",
            "source": "primary",
        }
        second["candidate_object_sha256"] = candidate_object_hash(second)
        candidate_pool = self.runtime_dir / "candidate-lineage.json"
        candidate_pool.write_text(
            json.dumps({"items": [first]}),
            encoding="utf-8",
        )
        supplement = self.runtime_dir / "supplement-lineage.json"
        supplement.write_text(
            json.dumps({"results": [{"candidates": [second]}]}),
            encoding="utf-8",
        )
        manifest = {
            "artifacts": {
                "candidate_pool": {
                    "artifact_path": str(candidate_pool),
                    "artifact_sha256": file_sha256(candidate_pool),
                }
            },
            "stages": {
                "supplemental": {
                    "artifact_path": str(supplement),
                    "artifact_sha256": file_sha256(supplement),
                }
            },
        }

        lineage = registered_candidate_lineage(manifest)

        self.assertEqual(
            lineage[reference]["object_hashes"],
            {
                first["candidate_object_sha256"],
                second["candidate_object_sha256"],
            },
        )

    def test_explicit_bound_candidate_source_type_cannot_be_upgraded(self):
        with self.assertRaisesRegex(RunContractError, "source_type"):
            _validate_bound_candidate_source_type(
                {"source_type": "primary"},
                [{"source_type": "secondary"}],
            )

        _validate_bound_candidate_source_type(
            {"source_type": "primary"},
            [{"title": "legacy baseline without source_type"}],
        )

    def test_multi_independent_requires_same_bound_semantic_event(self):
        identity = {
            "key_version": "1",
            "primary_domain": "healthcare_digital",
            "actor": "Example Hospital",
            "action": "published",
            "object": "clinical AI evaluation",
            "event_date": "2026-08-09",
        }
        event_id = generate_event_id(identity)

        def candidate(url, source, *, candidate_identity=None, quality="semantic"):
            bound_identity = deepcopy(candidate_identity or identity)
            return {
                "url": url,
                "source": source,
                "primary_domain": bound_identity["primary_domain"],
                "identity_quality": quality,
                "event_id": generate_event_id(bound_identity),
                "event_identity": bound_identity,
            }

        def access(url, *, status="verified"):
            payload = {
                "status": status,
                "checked_at": self.now.isoformat(),
                "method": "http_get",
                "requested_url": url,
                "final_url": url,
                "http_status": 200 if status == "verified" else 403,
                "failure_class": "none" if status == "verified" else "permanent",
                "error_code": None if status == "verified" else "HTTP_403",
            }
            return _validate_access_log_entry(payload, 0)

        item = {"event_id": event_id, "corroboration_status": "multi_independent"}
        first = candidate("https://source-a.example/a", "Source A")
        second = candidate("https://source-b.example/b", "Source B")
        verified = [access(first["url"]), access(second["url"])]

        _validate_multi_independent_lineage(item, [first, second], verified)

        identity_changes = {
            "key_version": "2",
            "primary_domain": "technology",
            "actor": "Another Hospital",
            "action": "announced",
            "object": "another evaluation",
            "event_date": "2026-08-08",
        }
        for field, changed_value in identity_changes.items():
            changed_identity = deepcopy(identity)
            changed_identity[field] = changed_value
            changed = candidate(
                second["url"],
                second["source"],
                candidate_identity=changed_identity,
            )
            with (
                self.subTest(identity_field=field),
                self.assertRaisesRegex(RunContractError, "final item.event_id"),
            ):
                _validate_multi_independent_lineage(
                    item,
                    [first, changed],
                    verified,
                )

        missing_identity = deepcopy(second)
        missing_identity.pop("event_identity")
        with self.assertRaisesRegex(RunContractError, "semantic event identity"):
            _validate_multi_independent_lineage(
                item, [first, missing_identity], verified
            )

        provisional = deepcopy(second)
        provisional["identity_quality"] = "provisional"
        with self.assertRaisesRegex(RunContractError, "semantic event identity"):
            _validate_multi_independent_lineage(item, [first, provisional], verified)

        copied_event_id = deepcopy(second)
        copied_event_id["event_identity"]["actor"] = "Forged Actor"
        copied_event_id["event_id"] = event_id
        with self.assertRaisesRegex(RunContractError, "does not match event_identity"):
            _validate_multi_independent_lineage(
                item, [first, copied_event_id], verified
            )

        subjective_relationship = deepcopy(second)
        subjective_relationship["event_identity"]["relationship"] = "same story"
        with self.assertRaisesRegex(RunContractError, "exactly the semantic identity fields"):
            _validate_multi_independent_lineage(
                item, [first, subjective_relationship], verified
            )

        source_alias = deepcopy(second)
        source_alias["source"] = "  SOURCE   A  "
        with self.assertRaisesRegex(RunContractError, "distinct normalized sources"):
            _validate_multi_independent_lineage(item, [first, source_alias], verified)

        same_host = candidate("https://source-a.example/other", "Source B")
        with self.assertRaisesRegex(RunContractError, "distinct hosts"):
            _validate_multi_independent_lineage(
                item,
                [first, same_host],
                [access(first["url"]), access(same_host["url"])],
            )

        with self.assertRaisesRegex(RunContractError, "verified receipt access"):
            _validate_multi_independent_lineage(
                item,
                [first, second],
                [access(first["url"]), access(second["url"], status="blocked")],
            )

        third_identity = deepcopy(identity)
        third_identity["object"] = "unrelated procurement"
        third = candidate(
            "https://source-c.example/c",
            "Source C",
            candidate_identity=third_identity,
        )
        with self.assertRaisesRegex(RunContractError, "final item.event_id"):
            _validate_multi_independent_lineage(
                item,
                [first, second, third],
                [*verified, access(third["url"])],
            )

    def test_candidate_identity_change_invalidates_bound_object_hash(self):
        identity = {
            "key_version": "1",
            "primary_domain": "technology",
            "actor": "Example Vendor",
            "action": "released",
            "object": "agent platform",
            "event_date": "2026-08-09",
        }
        candidate = {
            "candidate_id": candidate_ref("https://example.org/source"),
            "url": "https://example.org/source",
            "identity_quality": "semantic",
            "event_id": generate_event_id(identity),
            "event_identity": identity,
        }
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        candidate["event_identity"]["object"] = "tampered object"
        pool = self.runtime_dir / "tampered-identity-candidate.json"
        pool.write_text(json.dumps({"items": [candidate]}), encoding="utf-8")
        supplement = self.runtime_dir / "empty-supplement.json"
        supplement.write_text(json.dumps({"results": []}), encoding="utf-8")
        manifest = {
            "artifacts": {
                "candidate_pool": {
                    "artifact_path": str(pool),
                    "artifact_sha256": file_sha256(pool),
                }
            },
            "stages": {
                "supplemental": {
                    "artifact_path": str(supplement),
                    "artifact_sha256": file_sha256(supplement),
                }
            },
        }

        with self.assertRaisesRegex(RunContractError, "candidate hash is invalid"):
            registered_candidate_lineage(manifest)

    def bind_candidates(self, manifest_path, items=None):
        candidate_items = items or []
        candidate_pool = self.runtime_dir / "candidates.json"
        candidate_pool.write_text(
            json.dumps(
                {
                    "candidate_funnel": {
                        "observed": len(candidate_items),
                        "retained_for_review": len(candidate_items),
                        "terminal_dispositions": {
                            "retained_for_review": len(candidate_items)
                        },
                    },
                    "items": candidate_items,
                }
            ),
            encoding="utf-8",
        )
        record_run_artifact(manifest_path, "candidate_pool", candidate_pool, now=self.now)
        return candidate_pool

    def prepare_semantic_run(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=baseline,
            now=self.now,
        )
        self.bind_history(manifest_path)
        self.bind_candidates(manifest_path)
        supplement = self.runtime_dir / "supplement.json"
        supplement.write_text('{"coverage":{"attempted":0,"succeeded":0,"failed":0},"results":[]}', encoding="utf-8")
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=supplement,
            now=self.now,
        )
        request_path, request = build_review_request(
            manifest_path,
            None,
            "semantic",
            now=self.now,
        )
        return manifest_path, request_path, request

    def prepare_targeted_red_team_request(self, item_updates):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "targeted-review-baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "degraded",
            artifact_path=baseline,
            metadata={
                "coverage": {
                    "source_attempted": 10,
                    "source_succeeded": 8,
                    "source_failed": 2,
                    "raw_candidates": 10,
                    "dated_candidates": 9,
                    "reasons": [],
                }
            },
            now=self.now,
        )
        self.bind_history(manifest_path)
        manifest = load_manifest(manifest_path)
        refined = cloned_v14_payload()
        refined.update(
            {
                "run_id": manifest["run_id"],
                "report_date": manifest["report_date"],
                "generated_at": self.now.isoformat(),
                "topic": manifest["topic"],
                "region": manifest["region"],
                "window": manifest["window"],
            }
        )
        item = refined["top_10"][0]
        item.update(item_updates)
        _, refined["mix"] = select_candidates_with_mix(
            refined["top_10"],
            10,
            {
                "default_ratio": refined["mix"]["default_ratio"],
                "requested_ratio": refined["mix"]["requested_ratio"],
                "ratio_source": refined["mix"]["ratio_source"],
                "ratio_reason": refined["mix"]["ratio_reason"],
                "max_ratio_shift": 0.2,
            },
        )
        candidate = {
            "candidate_id": item["candidate_refs"][0],
            "url": item["url"],
            "title": item["title"],
            "source": item["source"],
            "published_at": item["published_at"],
            "published_at_source": item["published_at_source"],
            "access_check": deepcopy(item["access_check"]),
        }
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        extra_candidates = []
        for index in (2, 3):
            extra = {
                "candidate_id": candidate_ref(f"https://example.org/{index}"),
                "url": f"https://example.org/{index}",
                "title": f"candidate {index}",
            }
            extra["candidate_object_sha256"] = candidate_object_hash(extra)
            extra_candidates.append(extra)
        self.bind_candidates(manifest_path, [candidate, *extra_candidates])
        supplement = self.runtime_dir / "targeted-review-supplement.json"
        supplement.write_text(
            '{"coverage":{"attempted":0,"succeeded":0,"failed":0},"results":[]}',
            encoding="utf-8",
        )
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=supplement,
            now=self.now,
        )
        _, semantic_request = build_review_request(
            manifest_path,
            None,
            "semantic",
            now=self.now,
        )
        core_draft = Path(
            semantic_request["execution_packet"]["draft_paths"]["refined_core"]
        )
        decision = Path(
            semantic_request["execution_packet"]["draft_paths"]["decision"]
        )
        core_draft.write_text(json.dumps(refined), encoding="utf-8")
        decision.write_text(
            json.dumps(
                {
                    "contract_version": "semantic-decision/1.0",
                    "status": "passed",
                    "turns_used": 1,
                    "halt_condition_met": True,
                }
            ),
            encoding="utf-8",
        )
        refined_path, semantic_receipt = finalize_semantic_decision(
            manifest_path,
            core_draft,
            decision,
            now=self.now,
        )
        telemetry_path = Path(manifest["run_dir"]) / (
            "execution_telemetry_semantic_review_"
            f"{semantic_request['invocation_id']}.json"
        )
        telemetry_path.write_text(
            json.dumps(
                {
                    "contract_version": "pih-execution-telemetry/1.0",
                    "run_id": manifest["run_id"],
                    "stage": "semantic_review",
                    "invocation_id": semantic_request["invocation_id"],
                    "status": "completed",
                    "usage": {
                        "input_tokens": 60,
                        "output_tokens": 40,
                        "reasoning_tokens": 0,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "total_tokens": 100,
                        "cost_usd": 0.1,
                        "assistant_messages": 1,
                        "tool_results": 0,
                        "tool_errors": 0,
                    },
                    "duration_seconds": 1.0,
                    "sources": [{"path": "semantic.jsonl", "sha256": "1" * 64}],
                }
            ),
            encoding="utf-8",
        )
        record_execution_telemetry(
            manifest_path,
            telemetry_path,
            now=self.now,
        )
        _, red_request = build_review_request(
            manifest_path,
            refined_path,
            "red_team",
            semantic_receipt_path=semantic_receipt,
            now=self.now,
        )
        return manifest_path, refined_path, red_request

    def register_targeted_red_team_receipt(
        self,
        manifest_path,
        refined_path,
        request,
    ):
        receipt_path = Path(
            request["execution_packet"]["output_paths"]["review_receipt"]
        )
        receipt = {
            "contract_version": "review-receipt/1.0",
            "run_id": load_manifest(manifest_path)["run_id"],
            "review_kind": "red_team",
            "status": "passed",
            "reviewer_kind": "logic_adversary",
            "reviewer_id": request["reviewer_id"],
            "invocation_id": request["invocation_id"],
            "challenge": request["challenge"],
            "request_sha256": load_manifest(manifest_path)["artifacts"]
            ["red_team_request"]["artifact_sha256"],
            "baseline_sha256": request["baseline_sha256"],
            "output_sha256": file_sha256(refined_path),
            "reviewed_item_hashes": sorted(
                set(request.get("major_signal_item_hashes", []))
                | set(request.get("conflict_item_hashes", []))
            ),
            "turns_used": 1,
            "halt_condition_met": True,
            "completed_at": self.now.isoformat(),
        }
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        validate_review_receipt(
            receipt,
            manifest_path,
            refined_path,
            expected_kind="red_team",
        )
        register_review_receipt(
            manifest_path,
            refined_path,
            receipt_path,
            "red_team",
            now=self.now,
        )
        return receipt_path

    def prepare_supplement_run(self, run_id, gap_ids, lane_by_gap=None):
        lane_by_gap = lane_by_gap or {}
        manifest_path, _ = create_run(
            runtime_dir=self.runtime_dir,
            skill_path=self.skill_file,
            report_date="2026-08-10",
            timezone_name="Asia/Shanghai",
            now=self.now,
            run_id=run_id,
        )
        baseline = self.runtime_dir / f"{run_id}-baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=baseline,
            now=self.now,
        )
        self.bind_candidates(manifest_path)
        request_path, request = build_supplement_request(
            manifest_path,
            [
                {
                    "gap_id": gap_id,
                    "lane": lane_by_gap.get(gap_id, "TechRadar"),
                    "query_scope": gap_id,
                }
                for gap_id in gap_ids
            ],
            now=self.now,
        )
        return manifest_path, request_path, request

    def write_supplement_result(self, request_path, request, gap_id, access_log):
        packet = next(
            packet
            for packet in request["execution_packets"]
            if packet["assigned_gap_ids"] == [gap_id]
        )
        result_path = Path(packet["output_paths"]["result"])
        blocked = sum(access["status"] == "blocked" for access in access_log)
        verified = len(access_log) - blocked
        completed_at = max(
            datetime.fromisoformat(access["checked_at"]) for access in access_log
        )
        request_created_at = datetime.fromisoformat(request["created_at"])
        started_at = max(request_created_at, completed_at - timedelta(seconds=1))
        result = {
            "contract_version": "supplement-result/1.0",
            "run_id": request["run_id"],
            "request_sha256": file_sha256(request_path),
            "baseline_sha256": request["baseline_sha256"],
            "candidate_pool_sha256": request["candidate_pool_sha256"],
            "gap_id": gap_id,
            "lane": packet["assigned_lanes"][0],
            "status": "degraded" if blocked else "no_increment",
            **(
                {
                    "failure_kind": "source_access",
                    "failure_reason": "registered access evidence contains blocked sources",
                }
                if blocked
                else {}
            ),
            "executed_queries": [gap_id],
            "access_log": access_log,
            "candidates": [],
            "coverage": {
                "attempted": len(access_log),
                "succeeded": verified,
                "failed": blocked,
            },
            "confidence": "low" if blocked else "medium",
            "data_provenance": {
                "request_sha256": file_sha256(request_path),
                "candidate_pool_sha256": request["candidate_pool_sha256"],
                "access_log_sha256": hashlib.sha256(
                    canonical_json_bytes(access_log)
                ).hexdigest(),
            },
            "turns_used": 1,
            "halt_condition_met": not blocked,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return result_path

    def test_major_signal_without_l4_uses_targeted_red_team(self):
        manifest_path, refined_path, request = self.prepare_targeted_red_team_request(
            {
                "major_signal": True,
                "major_signal_reason": "requires independent qualification",
                "intelligence_level": "L3",
                "confidence": "high",
                "near_term_decision_impact": True,
                "decision_impact_reason": "changes immediate qualification priority",
            }
        )

        self.assertEqual(request["review_mode"], "targeted_review")
        self.assertFalse(request["deterministic_fast_path"])
        self.assertEqual(request["reviewer_kind"], "logic_adversary")
        self.assertEqual(request["max_turns"], 1)
        self.assertEqual(request["execution_packet"]["timeout_ms"], 120000)
        self.register_targeted_red_team_receipt(
            manifest_path,
            refined_path,
            request,
        )
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["red_team"]["status"],
            "completed",
        )
        errors, _ = validate_briefing_data(
            json.loads(refined_path.read_text(encoding="utf-8"))
        )
        self.assertNotIn("targeted red-team review must record covered item hashes", errors)

    def test_conflict_without_l4_uses_targeted_red_team(self):
        manifest_path, refined_path, request = self.prepare_targeted_red_team_request(
            {"evidence_conflict": True}
        )

        self.assertEqual(request["review_mode"], "targeted_review")
        self.assertFalse(request["deterministic_fast_path"])
        self.assertEqual(request["reviewer_kind"], "logic_adversary")
        self.assertEqual(request["max_turns"], 1)
        refined_item = json.loads(refined_path.read_text(encoding="utf-8"))["top_10"][0]
        self.assertEqual(request["conflict_item_hashes"], [item_hash(refined_item)])
        self.register_targeted_red_team_receipt(
            manifest_path,
            refined_path,
            request,
        )
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["red_team"]["status"],
            "completed",
        )

    def test_execution_budget_reserves_pending_agent_before_launch(self):
        within = {
            "telemetry": {
                "executions": {
                    "semantic:one": {
                        "usage": {"total_tokens": 170000, "cost_usd": 2.0}
                    }
                }
            }
        }
        budget = _assert_execution_budget_allows_launch(
            within,
            reserved_tokens=80000,
            reserved_cost_usd=1.0,
        )
        self.assertEqual(budget["remaining_cost_usd"], 1.0)
        cached_usage = {
            "telemetry": {
                "executions": {
                    "supplemental:one": {
                        "usage": {
                            "total_tokens": 500000,
                            "cache_read_tokens": 450000,
                            "cache_write_tokens": 0,
                            "cost_usd": 0.5,
                        }
                    }
                }
            }
        }
        cached_budget = _assert_execution_budget_allows_launch(
            cached_usage,
            reserved_tokens=80000,
            reserved_cost_usd=1.0,
        )
        self.assertEqual(cached_budget["actual_tokens"], 50000)
        self.assertEqual(cached_budget["raw_total_tokens"], 500000)
        no_reservation_headroom = deepcopy(within)
        no_reservation_headroom["telemetry"]["executions"]["semantic:one"][
            "usage"
        ]["total_tokens"] = 170001
        with self.assertRaisesRegex(RunContractError, "reservation unavailable"):
            _assert_execution_budget_allows_launch(
                no_reservation_headroom,
                reserved_tokens=80000,
                reserved_cost_usd=1.0,
            )
        ceiling_reached = deepcopy(within)
        ceiling_reached["telemetry"]["executions"]["semantic:one"]["usage"] = {
            "total_tokens": 250000,
            "cost_usd": 3.0,
        }
        with self.assertRaisesRegex(RunContractError, "budget exceeded"):
            _assert_execution_budget_allows_launch(
                ceiling_reached,
                reserved_tokens=1,
                reserved_cost_usd=0.01,
            )

    def test_unavailable_supplement_telemetry_keeps_cost_reservation(self):
        manifest_path, _, request = self.prepare_supplement_run(
            "unavailable-telemetry-run",
            ["gap-a"],
        )
        manifest = load_manifest(manifest_path)
        reservation = manifest["telemetry"]["reservations"]["supplemental:gap-a"]
        self.assertEqual(reservation["status"], "reserved")
        self.assertEqual(reservation["cost_usd"], 2.0)
        self.assertEqual(
            manifest["telemetry"]["summary"]["accounted_total_cost_usd"],
            2.0,
        )
        semantic_headroom = _assert_execution_budget_allows_launch(
            manifest,
            reserved_tokens=40000,
            reserved_cost_usd=0.75,
        )
        self.assertEqual(semantic_headroom["remaining_cost_usd"], 1.0)
        self.assertEqual(
            request["execution_packets"][0]["usage_budget"]["cost_usd"],
            2.0,
        )
        missing_review_telemetry = deepcopy(manifest)
        semantic_reservation = deepcopy(reservation)
        semantic_reservation.update(
            {
                "stage": "semantic_review",
                "invocation_id": "semantic-without-telemetry",
                "tokens": 40000,
                "cost_usd": 0.5,
            }
        )
        missing_review_telemetry["telemetry"]["reservations"][
            "semantic_review:semantic-without-telemetry"
        ] = semantic_reservation
        red_team_headroom = _assert_execution_budget_allows_launch(
            missing_review_telemetry,
            reserved_tokens=30000,
            reserved_cost_usd=0.5,
        )
        self.assertEqual(red_team_headroom["accounted_cost_usd"], 2.5)

    def test_execution_telemetry_settles_reservation_to_actual_usage(self):
        manifest_path, _, _ = self.prepare_supplement_run(
            "settled-telemetry-run",
            ["gap-a"],
        )
        run_dir = Path(load_manifest(manifest_path)["run_dir"])
        artifact = run_dir / "execution_telemetry_supplemental_gap-a.json"
        artifact.write_text(
            json.dumps(
                {
                    "contract_version": "pih-execution-telemetry/1.0",
                    "run_id": "settled-telemetry-run",
                    "stage": "supplemental",
                    "invocation_id": "gap-a",
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "reasoning_tokens": 0,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "total_tokens": 15,
                        "cost_usd": 0.25,
                        "assistant_messages": 1,
                        "tool_results": 0,
                        "tool_errors": 0,
                    },
                    "duration_seconds": 1.0,
                    "sources": [{"path": "supplement.jsonl", "sha256": "2" * 64}],
                }
            ),
            encoding="utf-8",
        )
        record_execution_telemetry(manifest_path, artifact, now=self.now)

        manifest = load_manifest(manifest_path)
        reservation = manifest["telemetry"]["reservations"]["supplemental:gap-a"]
        self.assertEqual(reservation["status"], "settled")
        summary = manifest["telemetry"]["summary"]
        self.assertEqual(summary["reserved_cost_usd"], 0.0)
        self.assertEqual(summary["accounted_total_cost_usd"], 0.25)
        _assert_execution_budget_allows_launch(
            manifest,
            reserved_tokens=80000,
            reserved_cost_usd=2.75,
        )

    def test_calendar_window_is_exactly_seven_inclusive_dates(self):
        window = calendar_window("2026-08-10", 7, "Asia/Shanghai")

        self.assertEqual(window["start"], "2026-08-04")
        self.assertEqual(window["end"], "2026-08-10")
        self.assertEqual(window["days"], 7)

    def test_current_schema_default_ratio_is_used_for_new_runs(self):
        _, manifest = self.new_run()
        expected = {"technology": 0.6, "healthcare_digital": 0.4}

        self.assertEqual(manifest["mix_request"]["schema_default_ratio"], expected)
        self.assertEqual(manifest["mix_request"]["requested_ratio"], expected)
        self.assertEqual(manifest["mix_request"]["ratio_source"], "schema_default")

    def test_current_ratio_contract_surfaces_are_consistent(self):
        root = Path(__file__).resolve().parent.parent
        schema = json.loads(
            (root / "references" / "briefing_schema.json").read_text(encoding="utf-8")
        )
        focus = json.loads(
            (root / "references" / "strategic_focus.json").read_text(encoding="utf-8")
        )
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        expected = {"technology": 0.6, "healthcare_digital": 0.4}

        self.assertEqual(schema["version"], "1.4")
        self.assertEqual(schema["domain_mix"]["default_ratio"], expected)
        self.assertEqual(focus["mix_policy"]["default_ratio"], expected)
        self.assertIn("默认领域请求比例为技术 60%、医疗数字化 40%", skill)
        self.assertIn("7 条为 4:3、5 条为 3:2、3 条为 2:1", skill)

    def test_resource_manifest_v3_validates_all_resource_hashes(self):
        references = self.runtime_dir / "references"
        references.mkdir()
        contract = references / "contract.json"
        contract.write_text('{"version": 1}\n', encoding="utf-8")
        payload = json.loads(
            (self.runtime_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )
        payload.update(
            {
                "schema_version": 3,
                "hash_algorithm": "SHA-256",
                "text_hash_normalization": "LF",
                "resource_file_hashes": [
                    {
                        "path": "references/contract.json",
                        "sha256": hashlib.sha256(b'{"version": 1}\n').hexdigest(),
                    }
                ],
            }
        )
        manifest = self.runtime_dir / "resource-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        validate_resource_manifest(manifest, self.skill_file)

        contract.write_text('{"version": 2}\n', encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "hash mismatch"):
            validate_resource_manifest(manifest, self.skill_file)

    def test_resource_manifest_v3_requires_resource_hash_inventory(self):
        payload = json.loads(
            (self.runtime_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )
        payload.update(
            {
                "schema_version": 3,
                "hash_algorithm": "SHA-256",
                "text_hash_normalization": "LF",
            }
        )
        manifest = self.runtime_dir / "resource-manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(RunContractError, "resource_file_hashes"):
            validate_resource_manifest(manifest, self.skill_file)

    def test_user_can_override_default_with_previous_four_to_six_ratio(self):
        _, manifest = create_run(
            runtime_dir=self.runtime_dir,
            skill_path=self.skill_file,
            report_date="2026-08-10",
            requested_ratio={"technology": 0.4, "healthcare_digital": 0.6},
            ratio_source="user",
            ratio_reason="用户明确指定",
            now=self.now,
            run_id="run-user-ratio",
        )

        self.assertEqual(
            manifest["mix_request"]["requested_ratio"],
            {"technology": 0.4, "healthcare_digital": 0.6},
        )
        self.assertEqual(manifest["mix_request"]["ratio_source"], "user")

    def test_parent_directory_run_id_is_rejected(self):
        with self.assertRaisesRegex(RunContractError, "invalid path"):
            create_run(
                runtime_dir=self.runtime_dir,
                skill_path=self.skill_file,
                report_date="2026-08-10",
                now=self.now,
                run_id="..",
            )

    def test_any_script_change_invalidates_the_active_run(self):
        scripts = self.runtime_dir / "scripts"
        scripts.mkdir()
        core = scripts / "core.py"
        core.write_text("VALUE = 1\n", encoding="utf-8")
        manifest_path, _ = self.new_run()
        core.write_text("VALUE = 2\n", encoding="utf-8")

        with self.assertRaisesRegex(RunContractError, "skill bundle"):
            load_manifest(manifest_path)

    def test_schema3_run_uses_immutable_bundle_snapshot_after_source_drift(self):
        bundle = self.runtime_dir / "snapshot-source"
        scripts = bundle / "scripts"
        scripts.mkdir(parents=True)
        skill = bundle / "SKILL.md"
        run_cli = scripts / "run_daily.py"
        skill.write_text("snapshot skill", encoding="utf-8")
        run_cli.write_text("print('snapshot')\n", encoding="utf-8")
        skill_hash = hashlib.sha256(b"snapshot skill").hexdigest()
        cli_hash = hashlib.sha256(b"print('snapshot')\n").hexdigest()
        resource_manifest = bundle / "resource-manifest.json"
        resource_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "skill": bundle.name,
                    "hash_algorithm": "SHA-256",
                    "text_hash_normalization": "LF",
                    "skill_md": "SKILL.md",
                    "skill_md_sha256": skill_hash,
                    "top_level_file_hashes": [],
                    "resource_file_hashes": [
                        {"path": "scripts/run_daily.py", "sha256": cli_hash}
                    ],
                    "declared_local_dependencies": [],
                    "missing_declared_dependencies": [],
                }
            ),
            encoding="utf-8",
        )
        manifest_path, created = create_run(
            runtime_dir=self.runtime_dir,
            skill_path=skill,
            resource_manifest_path=resource_manifest,
            report_date="2026-09-01",
            timezone_name="Asia/Shanghai",
            run_id="snapshot-run",
            now=self.now,
        )
        snapshot = created["bundle_snapshot"]
        self.assertTrue(Path(snapshot["execution_cli_path"]).is_file())
        self.assertNotEqual(Path(created["skill_path"]), skill.resolve())

        run_cli.write_text("print('drifted')\n", encoding="utf-8")
        loaded = load_manifest(manifest_path)
        self.assertEqual(loaded["skill_bundle_sha256"], created["skill_bundle_sha256"])
        self.assertEqual(
            Path(snapshot["execution_cli_path"]).read_text(encoding="utf-8"),
            "print('snapshot')\n",
        )

    def test_tool_cache_changes_do_not_invalidate_the_active_run(self):
        scripts = self.runtime_dir / "scripts"
        scripts.mkdir()
        semantic = scripts / "core.py"
        semantic.write_text("VALUE = 1\n", encoding="utf-8")
        manifest_path, _ = self.new_run()

        for cache_name in (".ruff_cache", ".pytest_cache", ".mypy_cache"):
            cache = scripts / cache_name / "state.json"
            cache.parent.mkdir()
            cache.write_text('{"version": 1}', encoding="utf-8")
            load_manifest(manifest_path)
            cache.write_text('{"version": 2}', encoding="utf-8")
            load_manifest(manifest_path)

        semantic.write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "skill bundle"):
            load_manifest(manifest_path)

    def test_supplement_request_requires_terminal_baseline(self):
        manifest_path, _ = self.new_run()

        with self.assertRaises(RunContractError):
            build_supplement_request(
                manifest_path,
                [{"gap_id": "technology", "lane": "TechRadar", "query_scope": "AI"}],
            )

    def test_stage_update_preserves_run_identity(self):
        manifest_path, original = self.new_run()
        artifact = self.runtime_dir / "baseline.json"
        artifact.write_text('{"items": []}', encoding="utf-8")

        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=artifact,
            metadata={"source_total": 3, "source_ok": 3, "source_failed": 0},
            now=self.now,
        )
        updated = load_manifest(manifest_path)

        for field in (
            "run_id",
            "skill_sha256",
            "skill_bundle_sha256",
            "skill_path",
            "resource_manifest_sha256",
            "resource_manifest_path",
            "report_date",
            "timezone",
            "window",
            "mix_request",
        ):
            self.assertEqual(updated[field], original[field])

        with self.assertRaisesRegex(RunContractError, "immutable once terminal"):
            record_stage(
                manifest_path,
                "baseline",
                "completed",
                artifact_path=artifact,
                now=self.now,
            )

    def test_failed_stage_is_final_and_cannot_satisfy_successor(self):
        manifest_path, _ = self.new_run()
        record_stage(manifest_path, "baseline", "failed", now=self.now)
        failed_sha = file_sha256(manifest_path)

        with self.assertRaisesRegex(RunContractError, "terminal/final"):
            record_stage(manifest_path, "baseline", "running", now=self.now)
        with self.assertRaisesRegex(RunContractError, "requires terminal predecessor"):
            record_stage(manifest_path, "supplemental", "running", now=self.now)

        self.assertEqual(file_sha256(manifest_path), failed_sha)

    def test_review_request_retry_recovers_request_only_commit_failure(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=baseline,
            now=self.now,
        )
        self.bind_history(manifest_path)
        self.bind_candidates(manifest_path)
        supplement = self.runtime_dir / "supplement.json"
        supplement.write_text('{"results": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=supplement,
            now=self.now,
        )
        manifest_sha = file_sha256(manifest_path)
        request_path = Path(load_manifest(manifest_path)["run_dir"]) / "semantic_review_request.json"
        from run_contract import atomic_dump_json as real_atomic_dump_json

        def fail_manifest_commit(path, payload):
            if Path(path).resolve() == manifest_path.resolve():
                raise OSError("injected manifest commit failure")
            return real_atomic_dump_json(path, payload)

        with (
            patch("run_contract.atomic_dump_json", side_effect=fail_manifest_commit),
            self.assertRaisesRegex(OSError, "injected manifest commit failure"),
        ):
            build_review_request(
                manifest_path,
                None,
                "semantic",
                now=self.now,
            )

        orphan_sha = file_sha256(request_path)
        orphan = json.loads(request_path.read_text(encoding="utf-8"))
        after_failure = load_manifest(manifest_path)
        self.assertEqual(file_sha256(manifest_path), manifest_sha)
        self.assertNotIn("semantic_review_request", after_failure["artifacts"])
        self.assertEqual(after_failure["stages"]["semantic_review"]["status"], "pending")

        retried_path, retried = build_review_request(
            manifest_path,
            None,
            "semantic",
            now=self.now,
        )

        self.assertEqual(retried_path, request_path)
        self.assertEqual(file_sha256(request_path), orphan_sha)
        self.assertEqual(retried["invocation_id"], orphan["invocation_id"])
        registered = load_manifest(manifest_path)
        self.assertEqual(
            registered["artifacts"]["semantic_review_request"]["artifact_sha256"],
            orphan_sha,
        )
        self.assertEqual(registered["stages"]["semantic_review"]["status"], "running")

    def test_progress_identity_is_bound_and_failed_review_cannot_revive(self):
        manifest_path, request_path, request = self.prepare_semantic_run()
        request_sha = file_sha256(request_path)
        state_path = self.runtime_dir / "semantic_progress_state.json"
        fingerprint = {
            "event_ordinal": 1,
            "last_event_at": self.now.isoformat(),
            "tool_call_count": 1,
            "milestone_seq": 0,
        }
        initial_sha = file_sha256(manifest_path)
        for invocation_id, supplied_sha in (
            ("stale-invocation", request_sha),
            (request["invocation_id"], "0" * 64),
        ):
            with self.assertRaisesRegex(RunContractError, "stale progress writer"):
                update_review_progress(
                    manifest_path,
                    "semantic",
                    invocation_id,
                    supplied_sha,
                    state_path,
                    fingerprint,
                    "running",
                    evaluate_progress,
                    now=self.now,
                )
            self.assertEqual(file_sha256(manifest_path), initial_sha)

        state, decision = update_review_progress(
            manifest_path,
            "semantic",
            request["invocation_id"],
            request_sha,
            state_path,
            fingerprint,
            "failed",
            evaluate_progress,
            now=self.now,
        )
        self.assertEqual(decision, "declare_lost")
        self.assertEqual(state["previous_fingerprint"]["event_ordinal"], 1)
        failed_sha = file_sha256(manifest_path)
        with self.assertRaisesRegex(RunContractError, "final"):
            update_review_progress(
                manifest_path,
                "semantic",
                request["invocation_id"],
                request_sha,
                state_path,
                dict(fingerprint, event_ordinal=2, tool_call_count=2),
                "running",
                evaluate_progress,
                now=self.now,
            )
        self.assertEqual(file_sha256(manifest_path), failed_sha)
        receipt_path = Path(
            request["execution_packet"]["output_paths"]["review_receipt"]
        )
        receipt_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "review receipt rejected"):
            register_review_receipt(
                manifest_path,
                request["execution_packet"]["output_paths"]["refined_core"],
                receipt_path,
                "semantic_review",
                now=self.now,
            )
        self.assertEqual(file_sha256(manifest_path), failed_sha)
        with self.assertRaisesRegex(RunContractError, "immutable once registered"):
            build_review_request(
                manifest_path,
                None,
                "semantic",
                now=self.now,
            )
        self.assertEqual(file_sha256(manifest_path), failed_sha)

    def test_semantic_finalizer_timeout_expires_reservation_and_terminalizes_stage(self):
        manifest_path, _, request = self.prepare_semantic_run()
        packet = request["execution_packet"]
        timeout = timedelta(milliseconds=packet["timeout_ms"] + 1)
        with self.assertRaisesRegex(
            RunContractError, "completed after registered timeout"
        ):
            finalize_semantic_decision(
                manifest_path,
                packet["draft_paths"]["refined_core"],
                packet["draft_paths"]["decision"],
                now=self.now + timeout,
            )

        manifest = load_manifest(manifest_path)
        key = f"semantic_review:{request['invocation_id']}"
        self.assertEqual(
            manifest["telemetry"]["reservations"][key]["status"],
            "expired",
        )
        self.assertEqual(
            manifest["stages"]["semantic_review"]["status"],
            "degraded_timeout",
        )
        self.assertEqual(
            manifest["telemetry"]["summary"]["active_reservation_count"],
            0,
        )

    def test_review_timeout_is_recorded_as_terminal_degraded_checkpoint(self):
        manifest_path, request_path, request = self.prepare_semantic_run()
        request_sha = file_sha256(request_path)
        state_path = self.runtime_dir / "semantic_timeout_state.json"
        fingerprint = {
            "event_ordinal": 1,
            "last_event_at": self.now.isoformat(),
            "tool_call_count": 1,
            "milestone_seq": 0,
        }

        _, decision = update_review_progress(
            manifest_path,
            "semantic",
            request["invocation_id"],
            request_sha,
            state_path,
            fingerprint,
            "timed_out",
            evaluate_progress,
            now=self.now,
        )

        self.assertEqual(decision, "degraded_timeout")
        manifest = load_manifest(manifest_path)
        stage = manifest["stages"]["semantic_review"]
        self.assertEqual(stage["status"], "degraded_timeout")
        self.assertEqual(stage["metadata"]["progress_decision"], "degraded_timeout")
        with self.assertRaisesRegex(RunContractError, "final"):
            update_review_progress(
                manifest_path,
                "semantic",
                request["invocation_id"],
                request_sha,
                state_path,
                dict(fingerprint, event_ordinal=2),
                "running",
                evaluate_progress,
                now=self.now,
            )

    def test_two_concurrent_progress_updates_preserve_both_events(self):
        manifest_path, request_path, request = self.prepare_semantic_run()
        request_sha = file_sha256(request_path)
        state_path = self.runtime_dir / "semantic_progress_state.json"
        fingerprint = {
            "event_ordinal": 1,
            "last_event_at": self.now.isoformat(),
            "tool_call_count": 1,
            "milestone_seq": 0,
        }

        def submit():
            return update_review_progress(
                manifest_path,
                "semantic",
                request["invocation_id"],
                request_sha,
                state_path,
                fingerprint,
                "running",
                evaluate_progress,
                now=self.now,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result() for future in [executor.submit(submit), executor.submit(submit)]]

        manifest = load_manifest(manifest_path)
        progress_events = [
            event
            for event in manifest["events"]
            if event.get("stage") == "semantic_review"
        ]
        self.assertEqual(len(progress_events), 3)
        self.assertEqual(len(results), 2)
        self.assertEqual(
            load_review_progress_state(
                manifest_path,
                "semantic",
                request["invocation_id"],
                request_sha,
            ),
            manifest["stages"]["semantic_review"]["metadata"]["progress_state"],
        )

    def test_manifest_precedes_state_mirror_and_recovers_after_mirror_failure(self):
        manifest_path, request_path, request = self.prepare_semantic_run()
        request_sha = file_sha256(request_path)
        state_path = self.runtime_dir / "semantic_progress_state.json"

        def argv(ordinal):
            return [
                "review_progress_gate.py",
                "--state",
                str(state_path),
                "--manifest",
                str(manifest_path),
                "--review-kind",
                "semantic",
                "--invocation-id",
                request["invocation_id"],
                "--request-sha256",
                request_sha,
                "--agent-status",
                "running",
                "--event-ordinal",
                str(ordinal),
                "--last-event-at",
                (self.now + timedelta(seconds=ordinal)).isoformat(),
                "--tool-call-count",
                str(ordinal),
            ]

        with (
            patch("sys.argv", argv(1)),
            patch(
                "review_progress_gate.atomic_write_json",
                side_effect=OSError("injected mirror failure"),
            ),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(progress_gate_main(), 0)
        first_result = json.loads(output.getvalue())
        self.assertEqual(first_result["decision"], "continue_wait")
        self.assertIn("state_mirror_error", first_result)
        self.assertFalse(state_path.exists())
        first_manifest_state = load_manifest(manifest_path)["stages"][
            "semantic_review"
        ]["metadata"]["progress_state"]
        self.assertEqual(
            first_manifest_state["previous_fingerprint"]["event_ordinal"], 1
        )

        with patch("sys.argv", argv(2)), redirect_stdout(StringIO()):
            self.assertEqual(progress_gate_main(), 0)
        mirrored = json.loads(state_path.read_text(encoding="utf-8"))
        authoritative = load_manifest(manifest_path)["stages"]["semantic_review"][
            "metadata"
        ]["progress_state"]
        self.assertEqual(mirrored, authoritative)
        self.assertEqual(authoritative["previous_fingerprint"]["event_ordinal"], 2)

    def test_manifest_commit_failure_does_not_advance_state_mirror(self):
        manifest_path, request_path, request = self.prepare_semantic_run()
        request_sha = file_sha256(request_path)
        state_path = self.runtime_dir / "semantic_progress_state.json"
        manifest_sha = file_sha256(manifest_path)
        args = [
            "review_progress_gate.py",
            "--state",
            str(state_path),
            "--manifest",
            str(manifest_path),
            "--review-kind",
            "semantic",
            "--invocation-id",
            request["invocation_id"],
            "--request-sha256",
            request_sha,
            "--agent-status",
            "running",
            "--event-ordinal",
            "1",
            "--last-event-at",
            self.now.isoformat(),
            "--tool-call-count",
            "1",
        ]
        with (
            patch("sys.argv", args),
            patch(
                "run_contract.commit_manifest",
                side_effect=OSError("injected manifest failure"),
            ),
            patch("review_progress_gate.atomic_write_json") as mirror,
            self.assertRaises(SystemExit),
        ):
            progress_gate_main()
        mirror.assert_not_called()
        self.assertFalse(state_path.exists())
        self.assertEqual(file_sha256(manifest_path), manifest_sha)

    def test_progress_and_terminal_commit_race_preserves_terminal_artifact(self):
        manifest_path, request_path, request = self.prepare_semantic_run()
        request_sha = file_sha256(request_path)
        state_path = self.runtime_dir / "semantic_progress_state.json"
        receipt = self.runtime_dir / "terminal-receipt.json"
        receipt.write_text('{"status":"passed"}', encoding="utf-8")
        fingerprint = {
            "event_ordinal": 1,
            "last_event_at": self.now.isoformat(),
            "tool_call_count": 1,
            "milestone_seq": 0,
        }
        progress_entered = Event()
        allow_progress_commit = Event()

        def barrier_evaluator(*args, **kwargs):
            progress_entered.set()
            if not allow_progress_commit.wait(timeout=5):
                raise AssertionError("terminal contender did not reach the barrier")
            return evaluate_progress(*args, **kwargs)

        def progress():
            return update_review_progress(
                manifest_path,
                "semantic",
                request["invocation_id"],
                request_sha,
                state_path,
                fingerprint,
                "running",
                barrier_evaluator,
                now=self.now,
            )

        def terminal():
            return record_stage(
                manifest_path,
                "semantic_review",
                "completed",
                artifact_path=receipt,
                now=self.now,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            progress_future = executor.submit(progress)
            self.assertTrue(progress_entered.wait(timeout=5))
            terminal_future = executor.submit(terminal)
            allow_progress_commit.set()
            outcomes = [progress_future.result(), terminal_future.result()]

        manifest = load_manifest(manifest_path)
        terminal_stage = manifest["stages"]["semantic_review"]
        self.assertEqual(terminal_stage["status"], "completed")
        self.assertEqual(terminal_stage["artifact_sha256"], file_sha256(receipt))
        self.assertTrue(
            any(
                event.get("stage") == "semantic_review"
                and event.get("status") == "completed"
                for event in manifest["events"]
            )
        )
        progress_events = [
            event
            for event in manifest["events"]
            if event.get("stage") == "semantic_review"
            and event.get("metadata", {}).get("progress_decision") == "continue_wait"
        ]
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(len(outcomes), 2)

    def test_candidate_artifact_is_hash_bound_and_immutable(self):
        manifest_path, _ = self.new_run()
        candidate_pool = self.bind_candidates(manifest_path)
        candidate_pool.write_text('{"items":[1]}', encoding="utf-8")

        with self.assertRaisesRegex(RunContractError, "immutable"):
            record_run_artifact(manifest_path, "candidate_pool", candidate_pool, now=self.now)

    def test_semantic_request_binds_compact_history_slice(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=baseline,
            now=self.now,
        )
        self.bind_history(manifest_path)
        review_slice = self.runtime_dir / "history-review-slice.json"
        focus = self.runtime_dir / "focus.json"
        focus.write_text('{"filters": {}}', encoding="utf-8")
        record_run_artifact(
            manifest_path,
            "focus_config",
            focus,
            now=self.now,
        )
        self.bind_candidates(manifest_path)
        supplement = self.runtime_dir / "supplement.json"
        supplement.write_text('{"results": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=supplement,
            now=self.now,
        )
        tampered_manifest = load_manifest(manifest_path)
        tampered_manifest["artifacts"]["history_review_slice"]["input_sha256"] = "0" * 64
        with self.assertRaisesRegex(RunContractError, "history slice lineage"):
            review_input_bundle_sha256(tampered_manifest)

        request_path, request = build_review_request(
            manifest_path,
            None,
            "semantic",
            now=self.now,
        )

        bound = request["bound_artifacts"]
        self.assertEqual(bound["history_review_slice"]["path"], str(review_slice.resolve()))
        self.assertEqual(
            bound["history_review_slice"]["sha256"],
            file_sha256(review_slice),
        )
        self.assertEqual(
            bound["history_snapshot"]["sha256"],
            file_sha256(self.runtime_dir / "history-snapshot.json"),
        )
        self.assertEqual(bound["focus_config"]["sha256"], file_sha256(focus))
        packet = request["execution_packet"]
        self.assertTrue(packet["self_contained"])
        self.assertEqual(
            packet["agent_contract"]["role"],
            "语义评估",
        )
        self.assertTrue(packet["contract_bundle"]["common_contract"])
        self.assertTrue(packet["contract_bundle"]["review_common_contract"])
        self.assertTrue(packet["contract_bundle"]["execution_policy"])
        readiness = packet["contract_bundle"]["execution_policy"]["readiness"]
        for command_name in ("progress_gate_command", "progress_gate_watch_command"):
            for flag in (
                "--manifest",
                "--review-kind",
                "--invocation-id",
                "--request-sha256",
            ):
                self.assertIn(flag, readiness[command_name])
        self.assertEqual(
            packet["output_paths"]["refined_core"],
            str(
                (
                    Path(load_manifest(manifest_path)["run_dir"])
                    / "refined_core.json"
                ).resolve()
            ),
        )
        self.assertIn(
            "semantic_agent.py",
            " ".join(packet["validation_command"]),
        )
        self.assertEqual(packet["validation_command"], packet["agent_helper"]["finalize_command"])
        self.assertIn("decision", packet["draft_paths"])
        self.assertIn("dynamic", packet["draft_paths"])
        self.assertEqual(packet["write_scope"], [packet["draft_paths"]["dynamic"]])
        self.assertNotIn(packet["draft_paths"]["review_receipt"], packet["write_scope"])
        self.assertEqual(packet["tool_budget"], {"soft": 6, "hard": 10, "block": "*"})
        context = build_semantic_agent_context(request_path)
        self.assertEqual(context["contract_version"], "semantic-agent-context/1.0")
        self.assertEqual(context["dynamic_draft_path"], packet["draft_paths"]["dynamic"])
        self.assertNotIn("bound_artifacts", context)
        self.assertEqual(request["contract_version"], "review-request/1.1")
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["semantic_review"]["status"],
            "running",
        )

        focus.write_text('{"filters": {"tampered": true}}', encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "focus_config bytes changed"):
            review_input_bundle_sha256(load_manifest(manifest_path))

    def test_supplement_packet_binds_run_baseline_gap_and_stop_contract(self):
        manifest_path, _ = self.new_run()
        artifact = self.runtime_dir / "baseline.json"
        artifact.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=artifact,
            metadata={"source_total": 3, "source_ok": 3, "source_failed": 0},
            now=self.now,
        )
        self.bind_candidates(
            manifest_path,
            items=[
                {
                    "title": "Agent release",
                    "url": "https://example.org/agent",
                    "provisional_domain": "technology",
                    "summary": "A new agent runtime.",
                },
                {
                    "title": "Clinical AI release",
                    "url": "https://example.org/clinical",
                    "provisional_domain": "healthcare_digital",
                    "summary": "A clinical AI deployment.",
                },
            ],
        )

        for field, value in (("max_turns", 0), ("max_queries", 0)):
            with self.subTest(field=field), self.assertRaisesRegex(
                RunContractError, field
            ):
                build_supplement_request(
                    manifest_path,
                    [
                        {
                            "gap_id": f"bad-{field}",
                            "lane": "TechRadar",
                            "query_scope": "AI",
                            field: value,
                        }
                    ],
                    now=self.now,
                )
        request_path, request = build_supplement_request(
            manifest_path,
            [
                {
                    "gap_id": "technology",
                    "lane": "TechRadar",
                    "query_scope": "AI agents",
                    "max_turns": 3,
                    "halt_condition": "所有直接来源已核验",
                }
            ],
            now=self.now,
        )

        self.assertTrue(request_path.exists())
        self.assertEqual(request["contract_version"], "supplement-request/1.1")
        self.assertEqual(request["run_id"], "run-test-001")
        self.assertEqual(request["baseline_sha256"], load_manifest(manifest_path)["stages"]["baseline"]["artifact_sha256"])
        self.assertEqual(request["gaps"][0]["gap_id"], "technology")
        self.assertEqual(request["gaps"][0]["max_turns"], 3)
        self.assertTrue(request["gaps"][0]["halt_condition"])
        prompt_contract = json.loads(
            (
                Path(__file__).resolve().parent.parent
                / "references"
                / "subagent_prompts.json"
            ).read_text(encoding="utf-8")
        )
        required_fields = set(
            prompt_contract["execution_policy"]["context_transfer"][
                "required_fields"
            ]
        )
        packet = request["execution_packets"][0]
        self.assertTrue(required_fields.issubset(packet))
        self.assertEqual(packet["assigned_gap_ids"], ["technology"])
        self.assertEqual(packet["assigned_lanes"], ["TechRadar"])
        self.assertEqual(
            packet["registered_request_path"], str(request_path.resolve())
        )
        self.assertEqual(
            packet["output_path_by_gap"]["technology"],
            packet["output_paths"]["result"],
        )
        self.assertTrue(packet["write_authorization"]["forbid_other_writes"])
        self.assertEqual(set(packet["bound_input_paths"]), {"lane_slice"})
        self.assertEqual(
            packet["execution_budget"],
            {"max_queries": 3, "max_urls": 6, "max_duration_seconds": 180},
        )
        self.assertEqual(
            packet["finalization"],
            {
                "grace_seconds": 60,
                "result_completed_at_semantics": "source_check_completed",
            },
        )
        self.assertEqual(
            packet["tool_budget"],
            {"soft": 8, "hard": 12, "block": "*"},
        )
        self.assertTrue(Path(packet["agent_helper"]["path"]).is_file())
        self.assertEqual(
            packet["agent_helper"]["sha256"],
            file_sha256(Path(packet["agent_helper"]["path"])),
        )
        self.assertIn("supplement_agent.py context", packet["task_message"])
        self.assertIn("supplement_agent.py finalize", packet["task_message"])
        self.assertIn("stop all research", packet["task_message"])
        lane_slice_path = Path(packet["lane_slice"]["path"])
        lane_slice = json.loads(lane_slice_path.read_text(encoding="utf-8"))
        self.assertEqual(lane_slice["gap"]["gap_id"], "technology")
        self.assertEqual(len(lane_slice["candidates"]), 1)
        self.assertEqual(
            lane_slice["candidates"][0]["url"], "https://example.org/agent"
        )
        self.assertNotIn("history_snapshot", packet["bound_input_paths"])
        self.assertEqual(len(request["launch_plan"]), 1)
        self.assertEqual(request["launch_plan"][0]["workers"][0]["gap_id"], "technology")

        original_lane_slice = lane_slice_path.read_bytes()
        lane_slice_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "lane slice path or hash"):
            register_supplement_results(
                manifest_path,
                request_path,
                [],
                now=self.now,
            )
        lane_slice_path.write_bytes(original_lane_slice)

        forged_request = self.runtime_dir / "forged-request.json"
        forged_request.write_text(json.dumps(request), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "registered artifact"):
            register_supplement_results(
                manifest_path,
                forged_request,
                [],
                now=self.now,
            )

        with self.assertRaisesRegex(RunContractError, "immutable"):
            build_supplement_request(
                manifest_path,
                [{"gap_id": "other", "lane": "Ranger", "query_scope": "risk"}],
                now=self.now,
            )

    def test_supplement_launch_plan_uses_bounded_fresh_waves(self):
        _, _, request = self.prepare_supplement_run(
            "launch-plan-run",
            ["gap-a", "gap-b", "gap-c", "gap-d"],
        )

        self.assertEqual([len(wave["workers"]) for wave in request["launch_plan"]], [1, 3])
        self.assertEqual(request["launch_plan"][0]["mode"], "canary")
        self.assertEqual(
            [
                worker["gap_id"]
                for wave in request["launch_plan"]
                for worker in wave["workers"]
            ],
            ["gap-a", "gap-b", "gap-c", "gap-d"],
        )
        self.assertTrue(
            all(
                "supplement_agent.py context" in worker["task_message"]
                and worker["timeout_ms"] == 240_000
                and worker["tool_budget"]
                == {"soft": 8, "hard": 12, "block": "*"}
                and worker["token_budget"] == 30_000
                and worker["cost_budget_usd"] == 0.5
                for wave in request["launch_plan"]
                for worker in wave["workers"]
            )
        )

    def test_supplement_timeout_state_reconciles_to_degraded_manifest(self):
        manifest_path, request_path, request = self.prepare_supplement_run(
            "timeout-reconcile-run",
            ["gap-timeout"],
        )
        packet = request["execution_packets"][0]
        state_path = Path(packet["progress"]["state_path"])
        state_path.write_text(
            json.dumps(
                {
                    "progress_id": "gap-timeout",
                    "last_decision": "degraded_timeout",
                    "terminal_status": "degraded_timeout",
                    "recorded_at": self.now.isoformat(),
                    "previous_fingerprint": {
                        "event_ordinal": 1,
                        "last_event_at": self.now.isoformat(),
                        "tool_call_count": 1,
                        "milestone_seq": 1,
                    },
                }
            ),
            encoding="utf-8",
        )

        late_result = self.write_supplement_result(
            request_path,
            request,
            "gap-timeout",
            [
                {
                    "status": "verified",
                    "checked_at": (self.now + timedelta(seconds=1)).isoformat(),
                    "method": "http_get",
                    "requested_url": "https://example.org/late",
                    "final_url": "https://example.org/late",
                    "http_status": 200,
                    "failure_class": "none",
                }
            ],
        )
        aggregate_path, aggregate = reconcile_supplement_progress(
            manifest_path,
            request_path,
            [late_result],
            [],
            now=self.now + timedelta(seconds=2),
        )

        self.assertEqual(aggregate["status"], "degraded")
        self.assertEqual(aggregate["results"][0]["status"], "failed")
        self.assertIn(
            "degraded_timeout",
            aggregate["results"][0]["failure_reason"],
        )
        self.assertTrue(aggregate_path.is_file())
        manifest = load_manifest(manifest_path)
        self.assertEqual(manifest["stages"]["supplemental"]["status"], "degraded")
        final_path = Path(packet["output_paths"]["result"])
        self.assertTrue(final_path.is_file())

    def test_supplement_finalizer_validates_before_atomic_publication(self):
        manifest_path, request_path, request = self.prepare_supplement_run(
            "finalizer-run",
            ["gap-a"],
        )
        access_log = [
            {
                "status": "verified",
                "checked_at": (self.now + timedelta(seconds=1)).isoformat(),
                "method": "http_get",
                "requested_url": "https://example.org/source",
                "final_url": "https://example.org/source",
                "http_status": 200,
                "failure_class": "none",
            }
        ]
        final_path = self.write_supplement_result(
            request_path,
            request,
            "gap-a",
            access_log,
        )
        draft_path = Path(request["execution_packets"][0]["output_paths"]["draft"])
        final_path.replace(draft_path)
        invalid = json.loads(draft_path.read_text(encoding="utf-8"))
        invalid.pop("started_at")
        draft_path.write_text(json.dumps(invalid), encoding="utf-8")

        with self.assertRaisesRegex(RunContractError, "started_at"):
            register_supplement_results(
                manifest_path,
                request_path,
                [draft_path],
                publish_drafts=True,
                now=self.now + timedelta(seconds=2),
            )
        self.assertTrue(draft_path.exists())
        self.assertFalse(final_path.exists())

        invalid["started_at"] = request["created_at"]
        draft_path.write_text(json.dumps(invalid), encoding="utf-8")
        _, aggregate = register_supplement_results(
            manifest_path,
            request_path,
            [draft_path],
            publish_drafts=True,
            now=self.now + timedelta(seconds=2),
        )

        self.assertFalse(draft_path.exists())
        self.assertTrue(final_path.exists())
        self.assertEqual(aggregate["status"], "no_increment")

    def test_supplement_result_enforces_query_and_duration_budgets(self):
        manifest_path, request_path, request = self.prepare_supplement_run(
            "bounded-result-run",
            ["gap-a"],
        )
        access_log = [
            {
                "status": "verified",
                "checked_at": (self.now + timedelta(seconds=1)).isoformat(),
                "method": "http_get",
                "requested_url": "https://example.org/source",
                "final_url": "https://example.org/source",
                "http_status": 200,
                "failure_class": "none",
            }
        ]
        result_path = self.write_supplement_result(
            request_path,
            request,
            "gap-a",
            access_log,
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["executed_queries"] = ["q1", "q2", "q3", "q4"]
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "max_queries"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=2),
            )

        result["executed_queries"] = ["q1"]
        result["started_at"] = self.now.isoformat()
        result["completed_at"] = (self.now + timedelta(seconds=181)).isoformat()
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "max_duration_seconds"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=182),
            )

    def test_review_receipt_rejects_heuristic_reviewer_and_hash_mismatch(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(manifest_path, "baseline", "completed", artifact_path=baseline, now=self.now)
        self.bind_history(manifest_path)
        self.bind_candidates(manifest_path)
        skipped = self.runtime_dir / "supplement-skipped.json"
        skipped.write_text('{"coverage":{"attempted":0,"succeeded":0,"failed":0},"results":[]}', encoding="utf-8")
        record_stage(manifest_path, "supplemental", "completed", artifact_path=skipped, now=self.now)
        refined = self.runtime_dir / "refined.json"
        item = {
            "event_id": "evt-1",
            "url": "https://example.org/1",
            "fact": "fact",
            "candidate_refs": [candidate_ref("https://example.org/1")],
        }
        refined.write_text(json.dumps({"top_10": [item]}), encoding="utf-8")
        manifest = load_manifest(manifest_path)
        with self.assertRaisesRegex(RunContractError, "between 1 and 2"):
            build_review_request(
                manifest_path,
                None,
                "semantic",
                max_turns=3,
                now=self.now,
            )
        _, semantic_request = build_review_request(
            manifest_path, None, "semantic", now=self.now
        )
        self.assertEqual(semantic_request["review_mode"], "registered_evidence_batch")
        self.assertEqual(semantic_request["max_turns"], 2)
        base_receipt = {
            "contract_version": "1.0",
            "run_id": manifest["run_id"],
            "review_kind": "semantic",
            "status": "passed",
            "reviewer_kind": "heuristic",
            "reviewer_id": semantic_request["reviewer_id"],
            "invocation_id": semantic_request["invocation_id"],
            "challenge": semantic_request["challenge"],
            "request_sha256": load_manifest(manifest_path)["artifacts"]["semantic_review_request"]["artifact_sha256"],
            "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
            "input_bundle_sha256": review_input_bundle_sha256(load_manifest(manifest_path)),
            "output_sha256": "wrong",
            "reviewed_item_hashes": [item_hash(item)],
            "lineage_bindings": [
                {
                    "output_item_sha256": item_hash(item),
                    "inputs": [
                        {
                            "candidate_ref": item["candidate_refs"][0],
                            "candidate_object_sha256": "a" * 64,
                        }
                    ],
                }
            ],
            "turns_used": 1,
            "halt_condition_met": True,
            "completed_at": self.now.isoformat(),
        }

        with self.assertRaisesRegex(RunContractError, "heuristic"):
            validate_review_receipt(base_receipt, manifest_path, refined)

        base_receipt["reviewer_kind"] = "semantic_model"
        base_receipt["challenge"] = "forged-challenge"
        with self.assertRaisesRegex(RunContractError, "challenge mismatch"):
            validate_review_receipt(base_receipt, manifest_path, refined)

        base_receipt["challenge"] = semantic_request["challenge"]
        with self.assertRaisesRegex(RunContractError, "output_sha256"):
            validate_review_receipt(base_receipt, manifest_path, refined)

    def test_supplement_results_are_bound_to_request_and_baseline(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(manifest_path, "baseline", "completed", artifact_path=baseline, now=self.now)
        self.bind_candidates(manifest_path)
        request_path, request = build_supplement_request(
            manifest_path,
            [{"gap_id": "tech", "lane": "TechRadar", "query_scope": "AI agents"}],
            now=self.now,
        )
        result_path = Path(
            request["execution_packets"][0]["output_paths"]["result"]
        )
        access_log = [
            {
                "status": "verified",
                "checked_at": self.now.isoformat(),
                "method": "http_get",
                "requested_url": "https://example.org/no-result",
                "final_url": "https://example.org/no-result",
                "http_status": 200,
                "failure_class": "none",
            }
        ]
        result_path.write_text(
            json.dumps(
                {
                    "contract_version": "supplement-result/1.0",
                    "run_id": "run-test-001",
                    "request_sha256": file_sha256(request_path),
                    "baseline_sha256": request["baseline_sha256"],
                    "candidate_pool_sha256": request["candidate_pool_sha256"],
                    "gap_id": "tech",
                    "lane": "TechRadar",
                    "status": "no_increment",
                    "executed_queries": ["AI agents official release"],
                    "access_log": access_log,
                    "candidates": [],
                    "coverage": {"attempted": 1, "succeeded": 1, "failed": 0},
                    "confidence": "medium",
                    "data_provenance": {
                        "request_sha256": file_sha256(request_path),
                        "candidate_pool_sha256": request["candidate_pool_sha256"],
                        "access_log_sha256": hashlib.sha256(canonical_json_bytes(access_log)).hexdigest(),
                    },
                    "turns_used": 1,
                    "halt_condition_met": True,
                    "started_at": self.now.isoformat(),
                    "completed_at": self.now.isoformat(),
                }
            ),
            encoding="utf-8",
        )

        wrong_result_path = self.runtime_dir / "tech-result.json"
        wrong_result_path.write_bytes(result_path.read_bytes())
        with self.assertRaisesRegex(RunContractError, "execution packet output path"):
            register_supplement_results(
                manifest_path,
                request_path,
                [wrong_result_path],
                now=self.now + timedelta(seconds=60),
            )

        stale_access = json.loads(result_path.read_text(encoding="utf-8"))
        stale_access["access_log"][0]["checked_at"] = (
            self.now - timedelta(seconds=1)
        ).isoformat()
        stale_access["data_provenance"]["access_log_sha256"] = hashlib.sha256(
            canonical_json_bytes(stale_access["access_log"])
        ).hexdigest()
        result_path.write_text(json.dumps(stale_access), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "request-to-result window"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=60),
            )

        result_path.write_text(
            json.dumps(
                {
                    **stale_access,
                    "access_log": access_log,
                    "data_provenance": {
                        **stale_access["data_provenance"],
                        "access_log_sha256": hashlib.sha256(
                            canonical_json_bytes(access_log)
                        ).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )

        artifact_path, aggregate = register_supplement_results(
            manifest_path,
            request_path,
            [result_path],
            now=self.now + timedelta(seconds=60),
        )

        self.assertTrue(artifact_path.exists())
        self.assertEqual(aggregate["run_id"], "run-test-001")
        self.assertEqual(aggregate["status"], "no_increment")
        self.assertEqual(aggregate["results"][0]["gap_id"], "tech")
        self.assertEqual(
            aggregate["timing"],
            {
                "request_to_registration_seconds": 60.0,
                "latest_result_to_registration_seconds": 60.0,
                "result_completion_skew_seconds": 0.0,
            },
        )
        self.assertEqual(load_manifest(manifest_path)["stages"]["supplemental"]["status"], "completed")
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["supplemental"]["metadata"]["result_status"],
            "no_increment",
        )

        repeated_path, repeated = register_supplement_results(
            manifest_path,
            request_path,
            [result_path],
            now=self.now,
        )
        self.assertEqual(repeated_path, artifact_path)
        self.assertEqual(repeated, aggregate)

        for field in ("attempted", "succeeded", "failed"):
            invalid_integer = deepcopy(aggregate["results"][0])
            invalid_integer["coverage"][field] = True
            result_path.write_text(json.dumps(invalid_integer), encoding="utf-8")
            with self.subTest(coverage_field=field), self.assertRaisesRegex(
                RunContractError, "coverage counts are invalid"
            ):
                register_supplement_results(
                    manifest_path,
                    request_path,
                    [result_path],
                    now=self.now,
                )
        invalid_turns = deepcopy(aggregate["results"][0])
        invalid_turns["turns_used"] = True
        result_path.write_text(json.dumps(invalid_turns), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "max_turns"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now,
            )
        invalid_http = deepcopy(aggregate["results"][0])
        invalid_http["access_log"][0]["http_status"] = True
        invalid_http["data_provenance"]["access_log_sha256"] = hashlib.sha256(
            canonical_json_bytes(invalid_http["access_log"])
        ).hexdigest()
        result_path.write_text(json.dumps(invalid_http), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "http_status"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now,
            )

        permanent_retry = json.loads(result_path.read_text(encoding="utf-8"))
        permanent_retry = deepcopy(aggregate["results"][0])
        blocked = {
            "status": "blocked",
            "checked_at": self.now.isoformat(),
            "method": "http_get",
            "requested_url": "https://example.org/missing",
            "final_url": "https://example.org/missing",
            "http_status": 404,
            "failure_class": "permanent",
            "error_code": "HTTP_404",
        }
        permanent_retry["status"] = "degraded"
        permanent_retry["failure_kind"] = "source_access"
        permanent_retry["failure_reason"] = "source access failed"
        permanent_retry["access_log"] = [blocked, dict(blocked)]
        permanent_retry["coverage"] = {
            "attempted": 2,
            "succeeded": 0,
            "failed": 2,
        }
        permanent_retry["data_provenance"]["access_log_sha256"] = hashlib.sha256(
            canonical_json_bytes(permanent_retry["access_log"])
        ).hexdigest()
        result_path.write_text(json.dumps(permanent_retry), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "chronology is ambiguous"):
            register_supplement_results(
                manifest_path, request_path, [result_path], now=self.now
            )

        result_path.write_text(
            json.dumps(aggregate["results"][0]), encoding="utf-8"
        )

        late_access = json.loads(result_path.read_text(encoding="utf-8"))
        late_access["access_log"][0]["checked_at"] = (
            self.now + timedelta(seconds=1)
        ).isoformat()
        late_access["data_provenance"]["access_log_sha256"] = hashlib.sha256(
            canonical_json_bytes(late_access["access_log"])
        ).hexdigest()
        result_path.write_text(json.dumps(late_access), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "request-to-result window"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=60),
            )

        result_path.write_text(
            json.dumps(aggregate["results"][0]), encoding="utf-8"
        )

        early_completion = json.loads(result_path.read_text(encoding="utf-8"))
        early_completion["completed_at"] = (
            self.now - timedelta(seconds=1)
        ).isoformat()
        result_path.write_text(json.dumps(early_completion), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "cannot precede request"):
            register_supplement_results(
                manifest_path, request_path, [result_path], now=self.now
            )

        result_path.write_text(
            json.dumps(aggregate["results"][0]), encoding="utf-8"
        )

        mismatched_candidate = json.loads(result_path.read_text(encoding="utf-8"))
        mismatched_candidate["status"] = "completed"
        mismatched_candidate["candidates"] = [
            {
                "title": "candidate",
                "url": "https://example.org/candidate",
                "source": "Example",
                "published_at": "2026-08-09",
                "published_at_source": "page_metadata",
                "retrieved_at": self.now.isoformat(),
                "primary_domain": "technology",
                "source_type": "primary",
                "identity_quality": "semantic",
                "event_id": generate_event_id(
                    {
                        "key_version": "1",
                        "primary_domain": "technology",
                        "actor": "Example",
                        "action": "published",
                        "object": "candidate",
                        "event_date": "2026-08-09",
                    }
                ),
                "event_identity": {
                    "key_version": "1",
                    "primary_domain": "technology",
                    "actor": "Example",
                    "action": "published",
                    "object": "candidate",
                    "event_date": "2026-08-09",
                },
                "summary": "candidate",
                "access_check": dict(access_log[0]),
            }
        ]
        result_path.write_text(json.dumps(mismatched_candidate), encoding="utf-8")
        with self.assertRaisesRegex(
            RunContractError, "requested_url does not match candidate url"
        ):
            register_supplement_results(
                manifest_path, request_path, [result_path], now=self.now
            )

        candidate_time = json.loads(result_path.read_text(encoding="utf-8"))
        candidate_time["candidates"][0]["access_check"] = {
            **candidate_time["access_log"][0],
            "checked_at": "2026-08-10T01:00:00Z",
            "requested_url": "https://example.org/candidate",
            "final_url": "https://example.org/candidate",
        }
        candidate_time["access_log"] = [
            deepcopy(candidate_time["candidates"][0]["access_check"])
        ]
        candidate_time["candidates"][0]["retrieved_at"] = (
            self.now - timedelta(seconds=1)
        ).isoformat()
        candidate_time["data_provenance"]["access_log_sha256"] = hashlib.sha256(
            canonical_json_bytes(candidate_time["access_log"])
        ).hexdigest()
        result_path.write_text(json.dumps(candidate_time), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "retrieved_at.*request-to-result"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=60),
            )

        missing_identity = deepcopy(candidate_time)
        missing_identity["candidates"][0]["retrieved_at"] = self.now.isoformat()
        missing_identity["candidates"][0].pop("event_identity")
        result_path.write_text(json.dumps(missing_identity), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "semantic event identity"):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=60),
            )

        for error_code in ("TLS_CERTIFICATE_VERIFY_FAILED", "INVALID_URL"):
            permanent_transport = json.loads(
                json.dumps(aggregate["results"][0])
            )
            blocked_transport = {
                "status": "blocked",
                "checked_at": self.now.isoformat(),
                "method": "http_get",
                "requested_url": "https://example.org/transport-error",
                "final_url": "https://example.org/transport-error",
                "http_status": None,
                "failure_class": "permanent",
                "error_code": error_code,
            }
            permanent_transport["status"] = "degraded"
            permanent_transport["failure_kind"] = "source_access"
            permanent_transport["failure_reason"] = "source access failed"
            permanent_transport["access_log"] = [
                blocked_transport,
                deepcopy(blocked_transport),
            ]
            permanent_transport["coverage"] = {
                "attempted": 2,
                "succeeded": 0,
                "failed": 2,
            }
            permanent_transport["data_provenance"]["access_log_sha256"] = (
                hashlib.sha256(
                    canonical_json_bytes(permanent_transport["access_log"])
                ).hexdigest()
            )
            result_path.write_text(
                json.dumps(permanent_transport), encoding="utf-8"
            )
            with (
                self.subTest(error_code=error_code),
                self.assertRaisesRegex(
                    RunContractError, "chronology is ambiguous"
                ),
            ):
                register_supplement_results(
                    manifest_path,
                    request_path,
                    [result_path],
                    now=self.now + timedelta(seconds=60),
                )

        unclassified_transport = json.loads(json.dumps(aggregate["results"][0]))
        unclassified_transport["status"] = "degraded"
        unclassified_transport["failure_kind"] = "source_access"
        unclassified_transport["failure_reason"] = "source access failed"
        unclassified_transport["access_log"] = [
            {
                "status": "blocked",
                "checked_at": self.now.isoformat(),
                "method": "http_get",
                "requested_url": "https://example.org/unclassified",
                "final_url": "https://example.org/unclassified",
                "http_status": None,
            }
        ]
        unclassified_transport["coverage"] = {
            "attempted": 1,
            "succeeded": 0,
            "failed": 1,
        }
        unclassified_transport["data_provenance"]["access_log_sha256"] = (
            hashlib.sha256(
                canonical_json_bytes(unclassified_transport["access_log"])
            ).hexdigest()
        )
        result_path.write_text(json.dumps(unclassified_transport), encoding="utf-8")
        with self.assertRaisesRegex(
            RunContractError, "requires failure_class and error_code"
        ):
            register_supplement_results(
                manifest_path,
                request_path,
                [result_path],
                now=self.now + timedelta(seconds=60),
            )

        empty_claim = json.loads(result_path.read_text(encoding="utf-8"))
        empty_claim["executed_queries"] = []
        empty_claim["access_log"] = []
        empty_claim["coverage"] = {"attempted": 0, "succeeded": 0, "failed": 0}
        empty_claim["turns_used"] = 0
        empty_claim["data_provenance"]["access_log_sha256"] = hashlib.sha256(
            canonical_json_bytes([])
        ).hexdigest()
        result_path.write_text(json.dumps(empty_claim), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "non-empty string list"):
            register_supplement_results(
                manifest_path, request_path, [result_path], now=self.now
            )

    def test_permanent_retry_is_url_global_across_status_method_and_gap(self):
        permanent = {
            "status": "blocked",
            "checked_at": self.now.isoformat(),
            "method": "http_get",
            "requested_url": "https://example.org/item?b=2&a=1",
            "final_url": "https://example.org/item?a=1&b=2",
            "http_status": 404,
            "failure_class": "permanent",
            "error_code": "HTTP_404",
        }
        seen: set[str] = set()
        _validate_access_retry_policy([permanent], seen_permanent_requests=seen)
        for method, status, failure_class in (
            ("http_get", "verified", "none"),
            ("browser", "verified", "none"),
            ("api", "blocked", "transient"),
        ):
            later = {
                **permanent,
                "status": status,
                "method": method,
                "http_status": 200 if status == "verified" else 503,
                "failure_class": failure_class,
                "error_code": None if status == "verified" else "HTTP_503",
            }
            with self.subTest(method=method, status=status), self.assertRaisesRegex(
                RunContractError, "retries a permanent failure"
            ):
                _validate_access_retry_policy(
                    [later],
                    seen_permanent_requests=seen,
                )

    def test_blocked_access_requires_consistent_machine_classification(self):
        base = {
            "status": "blocked",
            "checked_at": self.now.isoformat(),
            "method": "http_get",
            "requested_url": "https://example.org/item",
            "final_url": "https://example.org/item",
            "http_status": 404,
        }
        with self.assertRaisesRegex(RunContractError, "failure_class and error_code"):
            _validate_access_log_entry(base, 0)
        for http_status, failure_class, expected in (
            (403, "transient", "must be permanent"),
            (503, "permanent", "must be transient"),
        ):
            invalid = {
                **base,
                "http_status": http_status,
                "failure_class": failure_class,
                "error_code": f"HTTP_{http_status}",
            }
            with self.subTest(http_status=http_status), self.assertRaisesRegex(
                RunContractError, expected
            ):
                _validate_access_log_entry(invalid, 0)

    def test_registration_orders_retry_evidence_by_time_not_path_or_log_order(self):
        manifest_path, request_path, request = self.prepare_supplement_run(
            "retry-order-run",
            ["first", "second"],
        )
        url = "https://example.org/same"
        permanent = {
            "status": "blocked",
            "checked_at": self.now.isoformat(),
            "method": "http_get",
            "requested_url": url,
            "final_url": url,
            "http_status": 404,
            "failure_class": "permanent",
            "error_code": "HTTP_404",
        }
        verified = {
            "status": "verified",
            "checked_at": (self.now + timedelta(seconds=1)).isoformat(),
            "method": "browser",
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "failure_class": "none",
        }
        first = self.write_supplement_result(
            request_path, request, "first", [permanent]
        )
        second = self.write_supplement_result(
            request_path, request, "second", [verified]
        )
        for paths in ([first, second], [second, first]):
            with self.subTest(paths=[path.name for path in paths]), self.assertRaisesRegex(
                RunContractError, "retries a permanent failure"
            ):
                register_supplement_results(
                    manifest_path,
                    request_path,
                    paths,
                    now=self.now + timedelta(seconds=2),
                )

        single_manifest, single_request_path, single_request = (
            self.prepare_supplement_run("retry-log-order-run", ["only"])
        )
        single = self.write_supplement_result(
            single_request_path,
            single_request,
            "only",
            [verified, permanent],
        )
        with self.assertRaisesRegex(RunContractError, "retries a permanent failure"):
            register_supplement_results(
                single_manifest,
                single_request_path,
                [single],
                now=self.now + timedelta(seconds=2),
            )

    def test_registration_allows_one_cross_lane_transport_recovery(self):
        manifest_path, request_path, request = self.prepare_supplement_run(
            "cross-lane-transport-recovery",
            ["technology-coverage-integrity", "risk-counterevidence"],
            lane_by_gap={
                "technology-coverage-integrity": "TechRadar",
                "risk-counterevidence": "Ranger",
            },
        )
        url = "https://example.org/local-tls-path"
        permanent_transport = {
            "status": "blocked",
            "checked_at": self.now.isoformat(),
            "method": "http_get",
            "requested_url": url,
            "final_url": url,
            "http_status": None,
            "failure_class": "permanent",
            "error_code": "TLS_SSL_CONNECTION_FAILED",
        }
        verified = {
            "status": "verified",
            "checked_at": (self.now + timedelta(seconds=1)).isoformat(),
            "method": "browser",
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "failure_class": "none",
        }
        first = self.write_supplement_result(
            request_path,
            request,
            "technology-coverage-integrity",
            [permanent_transport],
        )
        second = self.write_supplement_result(
            request_path,
            request,
            "risk-counterevidence",
            [verified],
        )

        _, aggregate = register_supplement_results(
            manifest_path,
            request_path,
            [second, first],
            now=self.now + timedelta(seconds=2),
        )

        self.assertEqual(aggregate["status"], "degraded")
        self.assertEqual(len(aggregate["cross_lane_recoveries"]), 1)
        recovery = aggregate["cross_lane_recoveries"][0]
        self.assertEqual(recovery["failed_gap_id"], "technology-coverage-integrity")
        self.assertEqual(recovery["recovery_gap_id"], "risk-counterevidence")
        self.assertEqual(recovery["failure_code"], "TLS_SSL_CONNECTION_FAILED")
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["supplemental"]["metadata"][
                "cross_lane_recovery_count"
            ],
            1,
        )

    def test_registration_allows_success_before_permanent_failure(self):
        manifest_path, request_path, request = self.prepare_supplement_run(
            "retry-allowed-run",
            ["only"],
        )
        url = "https://example.org/allowed"
        verified = {
            "status": "verified",
            "checked_at": self.now.isoformat(),
            "method": "http_get",
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "failure_class": "none",
        }
        permanent = {
            "status": "blocked",
            "checked_at": (self.now + timedelta(seconds=1)).isoformat(),
            "method": "http_get",
            "requested_url": url,
            "final_url": url,
            "http_status": 404,
            "failure_class": "permanent",
            "error_code": "HTTP_404",
        }
        result = self.write_supplement_result(
            request_path,
            request,
            "only",
            [permanent, verified],
        )

        _, aggregate = register_supplement_results(
            manifest_path,
            request_path,
            [result],
            now=self.now + timedelta(seconds=2),
        )

        self.assertEqual(aggregate["status"], "degraded")

    def test_registration_applies_consecutive_host_limit_across_gaps(self):
        gap_ids = ["one", "two", "three"]
        manifest_path, request_path, request = self.prepare_supplement_run(
            "retry-host-run",
            gap_ids,
        )
        paths = []
        for index, gap_id in enumerate(gap_ids):
            url = f"https://example.org/{gap_id}"
            paths.append(
                self.write_supplement_result(
                    request_path,
                    request,
                    gap_id,
                    [
                        {
                            "status": "blocked",
                            "checked_at": (
                                self.now + timedelta(seconds=index)
                            ).isoformat(),
                            "method": "http_get",
                            "requested_url": url,
                            "final_url": url,
                            "http_status": 404,
                            "failure_class": "permanent",
                            "error_code": "HTTP_404",
                        }
                    ],
                )
            )
        with self.assertRaisesRegex(RunContractError, "host limit"):
            register_supplement_results(
                manifest_path,
                request_path,
                list(reversed(paths)),
                now=self.now + timedelta(seconds=3),
            )

    def test_zero_attempt_infrastructure_failure_is_registered_as_degraded(self):
        manifest_path, _ = create_run(
            runtime_dir=self.runtime_dir,
            skill_path=self.skill_file,
            report_date="2026-08-10",
            timezone_name="Asia/Shanghai",
            now=self.now,
            run_id="infrastructure-failure-run",
        )
        baseline = self.runtime_dir / "infra-baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "completed",
            artifact_path=baseline,
            now=self.now,
        )
        self.bind_candidates(manifest_path)
        request_path, request = build_supplement_request(
            manifest_path,
            [{"gap_id": "tech", "lane": "TechRadar", "query_scope": "AI"}],
            now=self.now,
        )
        access_log = []
        result_path = Path(
            request["execution_packets"][0]["output_paths"]["result"]
        )
        result_path.write_text(
            json.dumps(
                {
                    "contract_version": "supplement-result/1.0",
                    "run_id": "infrastructure-failure-run",
                    "request_sha256": file_sha256(request_path),
                    "baseline_sha256": request["baseline_sha256"],
                    "candidate_pool_sha256": request["candidate_pool_sha256"],
                    "gap_id": "tech",
                    "lane": "TechRadar",
                    "status": "failed",
                    "failure_kind": "infrastructure",
                    "failure_reason": "worker initialization failed",
                    "executed_queries": [],
                    "access_log": access_log,
                    "candidates": [],
                    "coverage": {"attempted": 0, "succeeded": 0, "failed": 0},
                    "confidence": "low",
                    "data_provenance": {
                        "request_sha256": file_sha256(request_path),
                        "candidate_pool_sha256": request["candidate_pool_sha256"],
                        "access_log_sha256": hashlib.sha256(
                            canonical_json_bytes(access_log)
                        ).hexdigest(),
                    },
                    "turns_used": 0,
                    "halt_condition_met": False,
                    "started_at": self.now.isoformat(),
                    "completed_at": self.now.isoformat(),
                }
            ),
            encoding="utf-8",
        )

        _, aggregate = register_supplement_results(
            manifest_path,
            request_path,
            [result_path],
            now=self.now + timedelta(seconds=1),
        )

        self.assertEqual(aggregate["status"], "degraded")
        self.assertEqual(aggregate["coverage"], {"attempted": 0, "succeeded": 0, "failed": 0})
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["supplemental"]["status"],
            "degraded",
        )

        result_path.write_text(json.dumps(aggregate["results"][0]), encoding="utf-8")

        invalid_access = json.loads(result_path.read_text(encoding="utf-8"))
        invalid_access["candidates"] = [
            {
                "title": "candidate",
                "url": "https://example.org/candidate",
                "source": "Example",
                "published_at": "2026-08-09",
                "published_at_source": "page_metadata",
                "retrieved_at": self.now.isoformat(),
                "primary_domain": "technology",
                "source_type": "primary",
                "summary": "candidate",
                "access_check": {"status": "verified"},
            }
        ]
        result_path.write_text(json.dumps(invalid_access), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "access_check missing"):
            register_supplement_results(manifest_path, request_path, [result_path], now=self.now)

        bad = json.loads(result_path.read_text(encoding="utf-8"))
        bad["run_id"] = "another-run"
        result_path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "run_id"):
            register_supplement_results(manifest_path, request_path, [result_path], now=self.now)

    def test_semantic_finalizer_assembles_receipt_and_publishes(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "semantic-finalizer-baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "degraded",
            artifact_path=baseline,
            metadata={
                "coverage": {
                    "source_attempted": 10,
                    "source_succeeded": 8,
                    "source_failed": 2,
                    "raw_candidates": 10,
                    "dated_candidates": 9,
                    "reasons": [],
                }
            },
            now=self.now,
        )
        self.bind_history(manifest_path)
        manifest = load_manifest(manifest_path)
        refined_payload = cloned_v14_payload()
        refined_payload.update(
            {
                "run_id": manifest["run_id"],
                "report_date": manifest["report_date"],
                "generated_at": self.now.isoformat(),
                "topic": manifest["topic"],
                "region": manifest["region"],
                "window": manifest["window"],
            }
        )
        item = refined_payload["top_10"][0]
        candidate = {
            "candidate_id": item["candidate_refs"][0],
            "event_id": item["event_id"],
            "event_identity": deepcopy(item["event_identity"]),
            "identity_quality": "semantic",
            "primary_domain": item["primary_domain"],
            "url": item["url"],
            "title": item["title"],
            "source": item["source"],
            "source_type": item["source_type"],
            "published_at": item["published_at"],
            "published_at_source": item["published_at_source"],
            "access_check": deepcopy(item["access_check"]),
        }
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        corroborating_url = "https://independent.example.net/corroboration"
        corroborating = {
            "candidate_id": candidate_ref(corroborating_url),
            "event_id": item["event_id"],
            "event_identity": deepcopy(item["event_identity"]),
            "identity_quality": "semantic",
            "primary_domain": item["primary_domain"],
            "url": corroborating_url,
            "title": "Independent clinical AI evaluation report",
            "source": "Independent Evaluator",
            "source_type": "secondary",
            "published_at": item["published_at"],
            "published_at_source": item["published_at_source"],
            "access_check": {
                "status": "verified",
                "checked_at": "2026-08-10T09:01:00+08:00",
                "method": "http_get",
                "requested_url": corroborating_url,
                "final_url": corroborating_url,
                "http_status": 200,
            },
        }
        corroborating["candidate_object_sha256"] = candidate_object_hash(
            corroborating
        )
        item["candidate_refs"] = [
            candidate["candidate_id"],
            corroborating["candidate_id"],
        ]
        item["corroboration_status"] = "multi_independent"
        extra_candidates = []
        for index in (2,):
            extra = {
                "candidate_id": candidate_ref(f"https://example.org/{index}"),
                "url": f"https://example.org/{index}",
                "title": f"candidate {index}",
            }
            extra["candidate_object_sha256"] = candidate_object_hash(extra)
            extra_candidates.append(extra)
        self.bind_candidates(
            manifest_path,
            [candidate, corroborating, *extra_candidates],
        )
        supplement = self.runtime_dir / "semantic-finalizer-supplement.json"
        supplement.write_text(
            '{"coverage":{"attempted":0,"succeeded":0,"failed":0},"results":[]}',
            encoding="utf-8",
        )
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=supplement,
            now=self.now,
        )
        _, request = build_review_request(
            manifest_path,
            None,
            "semantic",
            now=self.now,
        )
        self.assertEqual(request["execution_packet"]["timeout_ms"], 240000)
        self.assertEqual(request["execution_packet"]["usage_budget"]["cost_usd"], 0.5)
        core_draft = Path(request["execution_packet"]["draft_paths"]["refined_core"])
        decision = Path(request["execution_packet"]["draft_paths"]["decision"])
        core_draft.write_text(json.dumps(refined_payload), encoding="utf-8")
        decision.write_text(
            json.dumps(
                {
                    "contract_version": "semantic-decision/1.0",
                    "status": "passed",
                    "turns_used": 1,
                    "halt_condition_met": True,
                }
            ),
            encoding="utf-8",
        )

        real_replace = os.replace
        refined_final = Path(request["execution_packet"]["output_paths"]["refined_core"])
        receipt_final = Path(request["execution_packet"]["output_paths"]["review_receipt"])
        promotion_count = 0

        def fail_second_promotion(source, destination):
            nonlocal promotion_count
            if Path(destination) in {refined_final, receipt_final}:
                promotion_count += 1
                if promotion_count == 2:
                    raise OSError("injected second semantic promotion failure")
            return real_replace(source, destination)

        with (
            patch("run_contract.os.replace", side_effect=fail_second_promotion),
            self.assertRaisesRegex(OSError, "second semantic promotion"),
        ):
            finalize_semantic_decision(
                manifest_path,
                core_draft,
                decision,
                now=self.now,
            )
        self.assertTrue(refined_final.is_file())
        self.assertFalse(receipt_final.exists())

        with (
            patch(
                "run_contract.register_review_receipt",
                side_effect=RunContractError("injected semantic registration failure"),
            ),
            self.assertRaisesRegex(RunContractError, "registration failure"),
        ):
            finalize_semantic_decision(
                manifest_path,
                core_draft,
                decision,
                now=self.now,
            )
        self.assertTrue(refined_final.is_file())
        self.assertTrue(receipt_final.is_file())
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["semantic_review"]["status"],
            "running",
        )

        refined_path, receipt_path = finalize_semantic_decision(
            manifest_path,
            core_draft,
            decision,
            now=self.now,
        )

        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["reviewed_item_hashes"], [item_hash(item)])
        self.assertEqual(
            receipt["lineage_bindings"][0]["inputs"][0][
                "candidate_object_sha256"
            ],
            candidate["candidate_object_sha256"],
        )
        self.assertEqual(
            receipt["lineage_bindings"][0]["inputs"][1][
                "candidate_object_sha256"
            ],
            corroborating["candidate_object_sha256"],
        )
        self.assertEqual(len(receipt["access_log"]), 2)
        self.assertEqual(receipt["output_sha256"], file_sha256(refined_path))
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["semantic_review"]["status"],
            "completed",
        )
        self.assertFalse(core_draft.exists())
        self.assertFalse(decision.exists())

    def test_review_registration_binds_semantic_and_red_team_receipts(self):
        manifest_path, _ = self.new_run()
        baseline = self.runtime_dir / "baseline.json"
        baseline.write_text('{"items": []}', encoding="utf-8")
        record_stage(
            manifest_path,
            "baseline",
            "degraded",
            artifact_path=baseline,
            metadata={
                "coverage": {
                    "source_attempted": 10,
                    "source_succeeded": 8,
                    "source_failed": 2,
                    "raw_candidates": 10,
                    "dated_candidates": 9,
                    "reasons": [],
                }
            },
            now=self.now,
        )
        self.bind_history(manifest_path)
        manifest = load_manifest(manifest_path)
        refined_payload = cloned_v14_payload()
        refined_payload.update(
            {
                "run_id": manifest["run_id"],
                "report_date": manifest["report_date"],
                "generated_at": self.now.isoformat(),
                "topic": manifest["topic"],
                "region": manifest["region"],
                "window": manifest["window"],
            }
        )
        item = refined_payload["top_10"][0]
        candidate = {
            "candidate_id": item["candidate_refs"][0],
            "url": item["url"],
            "title": item["title"],
            "source": item["source"],
            "published_at": item["published_at"],
            "published_at_source": item["published_at_source"],
            "access_check": deepcopy(item["access_check"]),
        }
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        extra_candidates = []
        for index in (2, 3):
            extra = {
                "candidate_id": candidate_ref(f"https://example.org/{index}"),
                "url": f"https://example.org/{index}",
                "title": f"candidate {index}",
            }
            extra["candidate_object_sha256"] = candidate_object_hash(extra)
            extra_candidates.append(extra)
        self.bind_candidates(manifest_path, [candidate, *extra_candidates])
        skipped = self.runtime_dir / "supplement-skipped.json"
        skipped.write_text('{"coverage":{"attempted":0,"succeeded":0,"failed":0},"results":[]}', encoding="utf-8")
        record_stage(manifest_path, "supplemental", "completed", artifact_path=skipped, now=self.now)
        manifest = load_manifest(manifest_path)
        semantic_access_log = [item["access_check"]]
        _, semantic_request = build_review_request(
            manifest_path, None, "semantic", now=self.now
        )
        refined = Path(
            semantic_request["execution_packet"]["output_paths"]["refined_core"]
        )
        refined.write_text(json.dumps(refined_payload), encoding="utf-8")

        semantic = Path(
            semantic_request["execution_packet"]["output_paths"]["review_receipt"]
        )
        semantic.write_text(
            json.dumps(
                {
                    "contract_version": "review-receipt/1.0",
                    "run_id": manifest["run_id"],
                    "review_kind": "semantic",
                    "status": "passed",
                    "reviewer_kind": "semantic_model",
                    "reviewer_id": semantic_request["reviewer_id"],
                    "invocation_id": semantic_request["invocation_id"],
                    "challenge": semantic_request["challenge"],
                    "request_sha256": load_manifest(manifest_path)["artifacts"]["semantic_review_request"]["artifact_sha256"],
                    "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
                    "input_bundle_sha256": semantic_request["input_bundle_sha256"],
                    "access_log": semantic_access_log,
                    "data_provenance": {
                        "input_bundle_sha256": semantic_request["input_bundle_sha256"],
                        "access_log_sha256": hashlib.sha256(
                            canonical_json_bytes(semantic_access_log)
                        ).hexdigest(),
                    },
                    "output_sha256": file_sha256(refined),
                    "reviewed_item_hashes": [item_hash(item)],
                    "lineage_bindings": [
                        {
                            "output_item_sha256": item_hash(item),
                            "inputs": [
                                {
                                    "candidate_ref": candidate["candidate_id"],
                                    "candidate_object_sha256": candidate["candidate_object_sha256"],
                                }
                            ],
                        }
                    ],
                    "turns_used": 1,
                    "halt_condition_met": True,
                    "completed_at": self.now.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        self.assertIsInstance(
            validate_semantic_draft(manifest_path, refined, semantic),
            list,
        )

        rewritten_access_refined = self.runtime_dir / "refined-rewritten-access.json"
        rewritten_access_payload = deepcopy(refined_payload)
        rewritten_access_item = rewritten_access_payload["top_10"][0]
        rewritten_access_item["access_check"]["checked_at"] = (
            self.now + timedelta(seconds=1)
        ).isoformat()
        rewritten_access_hash = item_hash(rewritten_access_item)
        rewritten_access_payload["pipeline"]["semantic_review"][
            "reviewed_item_hashes"
        ] = [rewritten_access_hash]
        rewritten_access_payload["pipeline"]["semantic_review"][
            "lineage_bindings"
        ][0]["output_item_sha256"] = rewritten_access_hash
        rewritten_access_refined.write_text(
            json.dumps(rewritten_access_payload), encoding="utf-8"
        )
        rewritten_access_receipt = self.runtime_dir / "semantic-rewritten-access.json"
        rewritten_access_receipt_payload = json.loads(
            semantic.read_text(encoding="utf-8")
        )
        rewritten_access_receipt_payload["output_sha256"] = file_sha256(
            rewritten_access_refined
        )
        rewritten_access_receipt_payload["reviewed_item_hashes"] = [
            rewritten_access_hash
        ]
        rewritten_access_receipt_payload["lineage_bindings"][0][
            "output_item_sha256"
        ] = rewritten_access_hash
        rewritten_access_receipt_payload["access_log"] = [
            rewritten_access_item["access_check"]
        ]
        rewritten_access_receipt_payload["data_provenance"][
            "access_log_sha256"
        ] = hashlib.sha256(
            canonical_json_bytes(rewritten_access_receipt_payload["access_log"])
        ).hexdigest()
        rewritten_access_receipt.write_text(
            json.dumps(rewritten_access_receipt_payload), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            RunContractError, "access_check does not match exact bound candidate"
        ):
            validate_semantic_draft(
                manifest_path,
                rewritten_access_refined,
                rewritten_access_receipt,
            )

        bad_funnel_refined = self.runtime_dir / "refined-bad-funnel.json"
        bad_funnel_payload = deepcopy(refined_payload)
        bad_funnel_payload["candidate_funnel"]["terminal_dispositions"] = {
            "retained": 1,
            "below_quality_gate": 1,
            "semantic_capacity": 2,
        }
        bad_funnel_refined.write_text(
            json.dumps(bad_funnel_payload), encoding="utf-8"
        )
        bad_funnel_receipt = self.runtime_dir / "semantic-bad-funnel.json"
        bad_funnel_receipt_payload = json.loads(
            semantic.read_text(encoding="utf-8")
        )
        bad_funnel_receipt_payload["output_sha256"] = file_sha256(
            bad_funnel_refined
        )
        bad_funnel_receipt.write_text(
            json.dumps(bad_funnel_receipt_payload), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            RunContractError, "downstream terminal dispositions"
        ):
            validate_semantic_draft(
                manifest_path,
                bad_funnel_refined,
                bad_funnel_receipt,
            )

        rewritten_evidence_refined = self.runtime_dir / "refined-rewritten-evidence.json"
        rewritten_evidence_payload = deepcopy(refined_payload)
        rewritten_item = rewritten_evidence_payload["top_10"][0]
        rewritten_item["source"] = "Unregistered Publisher"
        rewritten_hash = item_hash(rewritten_item)
        rewritten_evidence_payload["pipeline"]["semantic_review"][
            "reviewed_item_hashes"
        ] = [rewritten_hash]
        rewritten_evidence_payload["pipeline"]["semantic_review"][
            "lineage_bindings"
        ][0]["output_item_sha256"] = rewritten_hash
        rewritten_evidence_refined.write_text(
            json.dumps(rewritten_evidence_payload), encoding="utf-8"
        )
        rewritten_evidence_receipt = self.runtime_dir / "semantic-rewritten-evidence.json"
        rewritten_evidence_receipt_payload = json.loads(
            semantic.read_text(encoding="utf-8")
        )
        rewritten_evidence_receipt_payload["output_sha256"] = file_sha256(
            rewritten_evidence_refined
        )
        rewritten_evidence_receipt_payload["reviewed_item_hashes"] = [
            rewritten_hash
        ]
        rewritten_evidence_receipt_payload["lineage_bindings"][0][
            "output_item_sha256"
        ] = rewritten_hash
        rewritten_evidence_receipt.write_text(
            json.dumps(rewritten_evidence_receipt_payload), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            RunContractError, "output evidence does not match"
        ):
            validate_semantic_draft(
                manifest_path,
                rewritten_evidence_refined,
                rewritten_evidence_receipt,
            )

        weak_corroboration_refined = self.runtime_dir / "refined-weak-corroboration.json"
        weak_corroboration_payload = deepcopy(refined_payload)
        weak_item = weak_corroboration_payload["top_10"][0]
        weak_item["source_type"] = "secondary"
        weak_item["corroboration_status"] = "multi_independent"
        weak_item["candidate_refs"] = [
            candidate["candidate_id"],
            extra_candidates[0]["candidate_id"],
        ]
        weak_hash = item_hash(weak_item)
        weak_binding_inputs = [
            {
                "candidate_ref": candidate["candidate_id"],
                "candidate_object_sha256": candidate["candidate_object_sha256"],
            },
            {
                "candidate_ref": extra_candidates[0]["candidate_id"],
                "candidate_object_sha256": extra_candidates[0][
                    "candidate_object_sha256"
                ],
            },
        ]
        weak_corroboration_payload["pipeline"]["semantic_review"][
            "reviewed_item_hashes"
        ] = [weak_hash]
        weak_corroboration_payload["pipeline"]["semantic_review"][
            "lineage_bindings"
        ] = [
            {
                "output_item_sha256": weak_hash,
                "inputs": weak_binding_inputs,
            }
        ]
        weak_corroboration_refined.write_text(
            json.dumps(weak_corroboration_payload), encoding="utf-8"
        )
        weak_corroboration_receipt = self.runtime_dir / "semantic-weak-corroboration.json"
        weak_corroboration_receipt_payload = json.loads(
            semantic.read_text(encoding="utf-8")
        )
        weak_corroboration_receipt_payload["output_sha256"] = file_sha256(
            weak_corroboration_refined
        )
        weak_corroboration_receipt_payload["reviewed_item_hashes"] = [weak_hash]
        weak_corroboration_receipt_payload["lineage_bindings"] = [
            {
                "output_item_sha256": weak_hash,
                "inputs": weak_binding_inputs,
            }
        ]
        weak_corroboration_receipt.write_text(
            json.dumps(weak_corroboration_receipt_payload), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            RunContractError, "semantic event identity"
        ):
            validate_semantic_draft(
                manifest_path,
                weak_corroboration_refined,
                weak_corroboration_receipt,
            )

        bad_coverage_refined = self.runtime_dir / "refined-bad-coverage.json"
        bad_coverage_payload = deepcopy(refined_payload)
        bad_coverage_payload["coverage"]["source_attempted"] = 9
        bad_coverage_refined.write_text(
            json.dumps(bad_coverage_payload), encoding="utf-8"
        )
        bad_coverage_receipt = self.runtime_dir / "semantic-bad-coverage.json"
        bad_coverage_receipt_payload = json.loads(semantic.read_text(encoding="utf-8"))
        bad_coverage_receipt_payload["output_sha256"] = file_sha256(
            bad_coverage_refined
        )
        bad_coverage_receipt.write_text(
            json.dumps(bad_coverage_receipt_payload), encoding="utf-8"
        )
        with self.assertRaisesRegex(RunContractError, "coverage.source_attempted"):
            validate_semantic_draft(
                manifest_path,
                bad_coverage_refined,
                bad_coverage_receipt,
            )

        bad_date_refined = self.runtime_dir / "refined-bad-date.json"
        bad_date_payload = deepcopy(refined_payload)
        bad_date_payload["top_10"][0]["published_at"] = (
            "2026-08-09T09:00:00+08:00"
        )
        bad_date_refined.write_text(json.dumps(bad_date_payload), encoding="utf-8")
        bad_date_receipt = self.runtime_dir / "semantic-bad-date.json"
        bad_date_receipt_payload = json.loads(semantic.read_text(encoding="utf-8"))
        bad_date_item_hash = item_hash(bad_date_payload["top_10"][0])
        bad_date_receipt_payload["output_sha256"] = file_sha256(bad_date_refined)
        bad_date_receipt_payload["reviewed_item_hashes"] = [bad_date_item_hash]
        bad_date_receipt_payload["lineage_bindings"][0][
            "output_item_sha256"
        ] = bad_date_item_hash
        bad_date_receipt.write_text(
            json.dumps(bad_date_receipt_payload),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RunContractError, "published_at"):
            validate_semantic_draft(
                manifest_path,
                bad_date_refined,
                bad_date_receipt,
            )

        bad_lineage = self.runtime_dir / "semantic-bad-lineage.json"
        bad_lineage_payload = json.loads(semantic.read_text(encoding="utf-8"))
        bad_lineage_payload["lineage_bindings"][0]["inputs"][0][
            "candidate_object_sha256"
        ] = "0" * 64
        bad_lineage.write_text(json.dumps(bad_lineage_payload), encoding="utf-8")
        with self.assertRaisesRegex(
            RunContractError, "candidate hash does not match registered candidate"
        ):
            validate_review_receipt(
                json.loads(bad_lineage.read_text(encoding="utf-8")),
                manifest_path,
                refined,
                expected_kind="semantic",
            )
        with self.assertRaisesRegex(
            RunContractError, "validated semantic receipt is required"
        ):
            build_review_request(
                manifest_path, refined, "red_team", now=self.now
            )
        self.assertNotIn(
            "red_team_request", load_manifest(manifest_path)["artifacts"]
        )

        tampered_semantic = self.runtime_dir / "semantic-tampered.json"
        tampered_payload = json.loads(semantic.read_text(encoding="utf-8"))
        tampered_payload["challenge"] = "tampered"
        tampered_semantic.write_text(json.dumps(tampered_payload), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "challenge mismatch"):
            build_review_request(
                manifest_path,
                refined,
                "red_team",
                semantic_receipt_path=tampered_semantic,
                now=self.now,
            )
        self.assertNotIn(
            "red_team_request", load_manifest(manifest_path)["artifacts"]
        )

        _, red_request = build_review_request(
            manifest_path,
            refined,
            "red_team",
            semantic_receipt_path=semantic,
            now=self.now,
        )
        self.assertEqual(red_request["review_mode"], "no_l4_fast_path")
        self.assertEqual(red_request["max_turns"], 1)
        self.assertEqual(red_request["l4_item_hashes"], [])
        self.assertEqual(red_request["major_signal_item_hashes"], [])
        self.assertTrue(red_request["deterministic_fast_path"])
        self.assertEqual(red_request["reviewer_kind"], "deterministic_gate")
        self.assertEqual(red_request["reviewer_id"], "NoL4Gate")
        self.assertEqual(red_request["execution_packet"]["timeout_ms"], 0)
        self.assertEqual(red_request["network_policy"], "forbidden")
        red_team = Path(
            red_request["execution_packet"]["output_paths"]["review_receipt"]
        )
        receipt = json.loads(red_team.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "not_required")
        self.assertEqual(receipt["reviewer_kind"], "deterministic_gate")
        self.assertEqual(receipt["reviewed_item_hashes"], [])
        self.assertEqual(receipt["turns_used"], 0)
        validate_review_receipt(
            receipt,
            manifest_path,
            refined,
            expected_kind="red_team",
        )

        stages = load_manifest(manifest_path)["stages"]
        self.assertEqual(stages["semantic_review"]["status"], "completed")
        self.assertEqual(stages["red_team"]["status"], "not_required")
        self.assertEqual(
            stages["semantic_review"]["metadata"]["review_mode"],
            "registered_evidence_batch",
        )
        self.assertEqual(
            stages["red_team"]["metadata"]["review_mode"],
            "no_l4_fast_path",
        )
        self.assertEqual(stages["red_team"]["metadata"]["max_turns"], 1)
        self.assertEqual(stages["red_team"]["metadata"]["turns_used"], 0)
        self.assertEqual(stages["red_team"]["metadata"]["elapsed_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
