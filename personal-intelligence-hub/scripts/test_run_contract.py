import json
import hashlib
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from run_contract import (
    RunContractError,
    build_review_request,
    build_supplement_request,
    candidate_object_hash,
    candidate_ref,
    calendar_window,
    canonical_json_bytes,
    create_run,
    file_sha256,
    item_hash,
    load_manifest,
    normalize_published_at,
    record_stage,
    record_run_artifact,
    review_scope,
    review_input_bundle_sha256,
    register_review_bundle,
    register_supplement_results,
    validate_resource_manifest,
    validate_review_receipt,
    validate_semantic_draft,
)
from test_contract_fixtures import cloned_v13_payload


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

        fast = review_scope({"top_10": [l3]})
        full = review_scope({"top_10": [l3, l4]})

        self.assertEqual(fast["review_mode"], "no_l4_fast_path")
        self.assertEqual(fast["l4_item_hashes"], [])
        self.assertEqual(fast["major_signal_item_hashes"], [item_hash(l3)])
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

    def bind_history(self, manifest_path):
        snapshot = self.runtime_dir / "history-snapshot.json"
        snapshot.write_text(
            json.dumps(
                {
                    "resource_kind": "pih_history_index",
                    "schema_version": "2.0",
                    "generated_at": self.now.isoformat(),
                    "entries": [],
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
        return snapshot

    def bind_candidates(self, manifest_path, items=None):
        candidate_pool = self.runtime_dir / "candidates.json"
        candidate_pool.write_text(
            json.dumps({"candidate_funnel": {"observed": len(items or [])}, "items": items or []}),
            encoding="utf-8",
        )
        record_run_artifact(manifest_path, "candidate_pool", candidate_pool, now=self.now)
        return candidate_pool

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

        self.assertEqual(schema["version"], "1.3")
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
        review_slice.write_text(
            json.dumps(
                {
                    "resource_kind": "pih_history_review_slice",
                    "schema_version": "1.0",
                    "generated_at": self.now.isoformat(),
                    "dedupe_days": 7,
                    "entries": [],
                }
            ),
            encoding="utf-8",
        )
        record_run_artifact(
            manifest_path,
            "history_review_slice",
            review_slice,
            input_sha256=load_manifest(manifest_path)["artifacts"]["history_snapshot"]["artifact_sha256"],
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

        _, request = build_review_request(
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
        packet = request["execution_packet"]
        self.assertTrue(packet["self_contained"])
        self.assertEqual(
            packet["agent_contract"]["role"],
            "语义评估",
        )
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
            "validate-semantic-draft",
            packet["validation_command"],
        )
        self.assertEqual(request["contract_version"], "review-request/1.1")

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
        self.bind_candidates(manifest_path)

        with self.assertRaisesRegex(RunContractError, "max_turns"):
            build_supplement_request(
                manifest_path,
                [
                    {
                        "gap_id": "bad-turns",
                        "lane": "TechRadar",
                        "query_scope": "AI",
                        "max_turns": 0,
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
        self.assertEqual(request["run_id"], "run-test-001")
        self.assertEqual(request["baseline_sha256"], load_manifest(manifest_path)["stages"]["baseline"]["artifact_sha256"])
        self.assertEqual(request["gaps"][0]["gap_id"], "technology")
        self.assertEqual(request["gaps"][0]["max_turns"], 3)
        self.assertTrue(request["gaps"][0]["halt_condition"])

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
        result_path = self.runtime_dir / "tech-result.json"
        access_log = [
            {
                "status": "verified",
                "checked_at": self.now.isoformat(),
                "method": "http_get",
                "requested_url": "https://example.org/no-result",
                "final_url": "https://example.org/no-result",
                "http_status": 200,
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
                    "completed_at": self.now.isoformat(),
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
        refined_payload = cloned_v13_payload()
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
        refined = self.runtime_dir / "refined.json"
        refined.write_text(json.dumps(refined_payload), encoding="utf-8")
        manifest = load_manifest(manifest_path)
        semantic_access_log = [item["access_check"]]
        _, semantic_request = build_review_request(
            manifest_path, None, "semantic", now=self.now
        )

        semantic = self.runtime_dir / "semantic.json"
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
        red_team = self.runtime_dir / "red-team.json"
        receipt = json.loads(semantic.read_text(encoding="utf-8"))
        receipt.update(
            {
                "review_kind": "red_team",
                "status": "failed",
                "reviewer_kind": "logic_adversary",
                "reviewer_id": red_request["reviewer_id"],
                "invocation_id": red_request["invocation_id"],
                "challenge": red_request["challenge"],
                "request_sha256": load_manifest(manifest_path)["artifacts"]["red_team_request"]["artifact_sha256"],
                "turns_used": 1,
                "halt_condition_met": True,
                "reviewed_item_hashes": [],
            }
        )
        red_team.write_text(json.dumps(receipt), encoding="utf-8")

        with self.assertRaisesRegex(RunContractError, "not acceptable"):
            register_review_bundle(
                manifest_path,
                refined,
                semantic,
                red_team,
                now=self.now,
            )
        self.assertEqual(
            load_manifest(manifest_path)["stages"]["semantic_review"]["status"],
            "pending",
        )

        receipt["status"] = "not_required"
        red_team.write_text(json.dumps(receipt), encoding="utf-8")
        register_review_bundle(
            manifest_path,
            refined,
            semantic,
            red_team,
            now=self.now + timedelta(seconds=90),
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
        self.assertEqual(stages["red_team"]["metadata"]["turns_used"], 1)
        self.assertEqual(stages["red_team"]["metadata"]["elapsed_seconds"], 0.0)
        self.assertEqual(
            stages["red_team"]["metadata"]["request_to_receipt_seconds"],
            0.0,
        )
        self.assertEqual(
            stages["red_team"]["metadata"]["receipt_to_registration_seconds"],
            90.0,
        )
        self.assertEqual(
            stages["red_team"]["metadata"]["request_to_registration_seconds"],
            90.0,
        )


if __name__ == "__main__":
    unittest.main()
