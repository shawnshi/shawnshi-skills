import json
import hashlib
import tempfile
import threading
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from archive_transaction import ArchiveTransactionError
import forge as forge_module
from forge import (
    ForgeContractError,
    assemble_final_payload,
    forge_briefing,
    preview_briefing,
)
from history_manager import generate_event_id
from run_contract import (
    RunContractError,
    build_review_request,
    candidate_object_hash,
    candidate_ref,
    canonical_json_bytes,
    create_run,
    file_sha256,
    item_hash,
    load_manifest,
    record_stage,
    record_run_artifact,
    review_input_bundle_sha256,
    register_review_receipt,
)
from test_contract_fixtures import valid_v12_payload, valid_v14_payload
from update_index import rebuild_history


def _retarget_fixture_event(payload: dict, *, actor: str, url: str, title: str) -> dict:
    item = payload["top_10"][0]
    identity = dict(item["event_identity"])
    identity.update({"actor": actor, "object": title})
    item.update(
        {
            "event_identity": identity,
            "event_id": generate_event_id(identity),
            "title": title,
            "title_zh": title,
            "url": url,
            "candidate_refs": [candidate_ref(url)],
            "source": actor,
        }
    )
    item["access_check"].update({"requested_url": url, "final_url": url})
    reviewed_hash = item_hash(item)
    semantic = payload["pipeline"]["semantic_review"]
    semantic["reviewed_item_hashes"] = [reviewed_hash]
    semantic["lineage_bindings"] = [
        {
            "output_item_sha256": reviewed_hash,
            "inputs": [
                {
                    "candidate_ref": candidate_ref(url),
                    "candidate_object_sha256": "e" * 64,
                }
            ],
        }
    ]
    return payload


class ForgeContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.runtime = self.root / "runtime"
        self.news = self.root / "news"
        self.history = self.news / ".pih_history_v2.json"
        self.skill = self.root / "SKILL.md"
        self.skill.write_text("skill", encoding="utf-8")
        (self.root / "resource-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "skill": self.root.name,
                    "skill_md": "SKILL.md",
                    "skill_md_sha256": hashlib.sha256(b"skill").hexdigest(),
                    "top_level_file_hashes": [],
                    "declared_local_dependencies": [],
                    "missing_declared_dependencies": [],
                }
            ),
            encoding="utf-8",
        )
        self.now = datetime(2026, 8, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def tearDown(self):
        self.directory.cleanup()

    def _run_with_baseline(
        self,
        *,
        report_date: str = "2026-08-10",
        run_id: str = "run-forge",
    ):
        manifest_path, _ = create_run(
            runtime_dir=self.runtime,
            skill_path=self.skill,
            report_date=report_date,
            now=self.now,
            run_id=run_id,
        )
        run_dir = manifest_path.parent
        snapshot = run_dir / "history-snapshot.json"
        history_clock = datetime.combine(
            date.fromisoformat(report_date),
            time.max,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        rebuild_history(
            news_dir=self.news,
            history_file=snapshot,
            now=history_clock,
            exclude_report_date=report_date,
        )
        target_state = {}
        compact_date = report_date.replace("-", "")
        for suffix in ("json", "md", "manifest.json"):
            target = self.news / f"intelligence_{compact_date}_briefing.{suffix}"
            target_state[target.name] = file_sha256(target) if target.is_file() else None
        record_run_artifact(
            manifest_path,
            "history_snapshot",
            snapshot,
            metadata={
                "news_dir": str(self.news.resolve()),
                "archive_target_state": target_state,
                "allow_existing_archive_replacement": True,
            },
            now=self.now,
        )
        review_slice = run_dir / "history_review_slice.json"
        snapshot_payload = json.loads(snapshot.read_text(encoding="utf-8"))
        review_slice.write_text(
            json.dumps(
                {
                    "resource_kind": "pih_history_review_slice",
                    "schema_version": "1.0",
                    "generated_at": self.now.isoformat(),
                    "source_snapshot_sha256": file_sha256(snapshot),
                    "dedupe_days": 7,
                    "entries": snapshot_payload.get("entries", []),
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
        baseline = run_dir / "baseline.json"
        baseline.write_text('{"items":[]}', encoding="utf-8")
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
                }
            },
            now=self.now,
        )
        candidates = run_dir / "candidates.json"
        candidate = {
            "candidate_id": candidate_ref("https://example.org/source"),
            "url": "https://example.org/source",
            "title": "Clinical AI evaluation published",
            "source": "Example Hospital",
            "published_at": "2026-08-09",
            "published_at_source": "page_metadata",
        }
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        review_candidates = [candidate]
        for index in (2, 3):
            extra = {
                "candidate_id": candidate_ref(f"https://example.org/extra-{index}"),
                "url": f"https://example.org/extra-{index}",
                "title": f"Extra registered candidate {index}",
                "source": f"Extra Source {index}",
                "published_at": "2026-08-09",
                "published_at_source": "page_metadata",
            }
            extra["candidate_object_sha256"] = candidate_object_hash(extra)
            review_candidates.append(extra)
        candidates.write_text(
            json.dumps(
                {
                    "candidate_funnel": {
                        "observed": 3,
                        "retained_for_review": 3,
                        "terminal_dispositions": {"retained_for_review": 3},
                    },
                    "items": review_candidates,
                }
            ),
            encoding="utf-8",
        )
        record_run_artifact(manifest_path, "candidate_pool", candidates, now=self.now)
        supplement = run_dir / "supplement.json"
        supplement.write_text(
            json.dumps(
                {
                    "status": "no_increment",
                    "coverage": {"attempted": 0, "succeeded": 0, "failed": 0},
                    "results": [],
                }
            ),
            encoding="utf-8",
        )
        record_stage(
            manifest_path,
            "supplemental",
            "completed",
            artifact_path=supplement,
            metadata={"result_status": "no_increment"},
            now=self.now,
        )
        return manifest_path

    def _register_reviews(self, manifest_path: Path, refined: Path) -> Path:
        manifest = load_manifest(manifest_path)
        run_id = str(manifest["run_id"])
        candidate = json.loads(
            Path(manifest["artifacts"]["candidate_pool"]["artifact_path"]).read_text(
                encoding="utf-8"
            )
        )["items"][0]
        _, semantic_request = build_review_request(
            manifest_path, None, "semantic", now=self.now
        )
        semantic_outputs = semantic_request["execution_packet"]["output_paths"]
        final_refined = Path(semantic_outputs["refined_core"])
        final_refined.write_bytes(refined.read_bytes())
        refined = final_refined
        payload = json.loads(refined.read_text(encoding="utf-8"))
        semantic_access_log = [item["access_check"] for item in payload["top_10"]]
        hashes = [item_hash(item) for item in payload["top_10"]]
        manifest = load_manifest(manifest_path)
        semantic = Path(semantic_outputs["review_receipt"])
        semantic.write_text(
            json.dumps(
                {
                    "contract_version": "review-receipt/1.0",
                    "run_id": run_id,
                    "review_kind": "semantic",
                    "status": "passed",
                    "reviewer_kind": "semantic_model",
                    "reviewer_id": semantic_request["reviewer_id"],
                    "invocation_id": semantic_request["invocation_id"],
                    "challenge": semantic_request["challenge"],
                    "request_sha256": manifest["artifacts"]["semantic_review_request"]["artifact_sha256"],
                    "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
                    "input_bundle_sha256": review_input_bundle_sha256(manifest),
                    "access_log": semantic_access_log,
                    "data_provenance": {
                        "input_bundle_sha256": review_input_bundle_sha256(manifest),
                        "access_log_sha256": hashlib.sha256(
                            canonical_json_bytes(semantic_access_log)
                        ).hexdigest(),
                    },
                    "output_sha256": file_sha256(refined),
                    "reviewed_item_hashes": hashes,
                    "lineage_bindings": [
                        {
                            "output_item_sha256": item_hash(item),
                            "inputs": [
                                {
                                    "candidate_ref": item["candidate_refs"][0],
                                    "candidate_object_sha256": candidate["candidate_object_sha256"],
                                }
                            ],
                        }
                        for item in payload["top_10"]
                    ],
                    "turns_used": 1,
                    "halt_condition_met": True,
                    "completed_at": self.now.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        register_review_receipt(manifest_path, refined, semantic, "semantic_review", now=self.now)
        _, red_request = build_review_request(
            manifest_path,
            refined,
            "red_team",
            semantic_receipt_path=semantic,
            now=self.now,
        )
        manifest = load_manifest(manifest_path)
        red = Path(red_request["execution_packet"]["output_paths"]["review_receipt"])
        red.write_text(
            json.dumps(
                {
                    "contract_version": "review-receipt/1.0",
                    "run_id": run_id,
                    "review_kind": "red_team",
                    "status": "not_required",
                    "reviewer_kind": "logic_adversary",
                    "reviewer_id": red_request["reviewer_id"],
                    "invocation_id": red_request["invocation_id"],
                    "challenge": red_request["challenge"],
                    "request_sha256": manifest["artifacts"]["red_team_request"]["artifact_sha256"],
                    "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
                    "output_sha256": file_sha256(refined),
                    "reviewed_item_hashes": [],
                    "turns_used": 1,
                    "halt_condition_met": True,
                    "completed_at": self.now.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        register_review_receipt(manifest_path, refined, red, "red_team", now=self.now)
        return refined

    def test_forge_requires_receipts_then_commits_pair_and_history(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with self.assertRaisesRegex(ForgeContractError, "semantic_review"):
            forge_briefing(
                manifest_path,
                refined,
                news_dir=self.news,
                history_path=self.history,
                update_runtime_state=False,
            )

        refined = self._register_reviews(manifest_path, refined)
        result = forge_briefing(
            manifest_path,
            refined,
            news_dir=self.news,
            update_runtime_state=False,
            now=self.now,
        )

        archived = json.loads(result.json_path.read_text(encoding="utf-8"))
        markdown = result.markdown_path.read_text(encoding="utf-8")
        history = json.loads(self.history.read_text(encoding="utf-8"))
        self.assertEqual(archived["pipeline"]["semantic_review"]["status"], "passed")
        self.assertEqual(archived["top_10"][0]["title"], "Clinical AI evaluation published")
        self.assertIn("临床 AI 评估发布", markdown)
        self.assertEqual(history["schema_version"], "2.0")
        self.assertEqual(load_manifest(manifest_path)["stages"]["archive"]["status"], "completed")

    def test_forge_rejects_v14_boolean_funnel_count_with_gate_error(self):
        manifest_path = self.root / "run-manifest.json"
        refined = self.runtime / "refined-boolean-count.json"
        payload = valid_v14_payload()
        payload["candidate_funnel"]["terminal_dispositions"]["retained"] = True
        refined.parent.mkdir(parents=True, exist_ok=True)
        refined.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        manifest = {
            "stages": {
                "archive": {"status": "pending"},
                "baseline": {"artifact_sha256": "a" * 64},
                "supplemental": {
                    "status": "completed",
                    "metadata": {"result_status": "no_increment"},
                },
            }
        }
        semantic = dict(payload["pipeline"]["semantic_review"])
        semantic["data_provenance"] = {
            "access_log_sha256": semantic["access_log_sha256"]
        }
        red_team = dict(payload["pipeline"]["red_team"])
        red_team["reviewed_item_hashes"] = list(red_team["covered_item_hashes"])

        with (
            patch.object(forge_module, "require_stage"),
            patch.object(forge_module, "load_manifest", return_value=manifest),
            patch.object(forge_module, "_assert_core_identity"),
            patch.object(
                forge_module,
                "_load_registered_receipt",
                side_effect=[semantic, red_team],
            ),
            patch.object(forge_module, "_assert_pipeline_provenance"),
        ):
            with self.assertRaisesRegex(
                ForgeContractError,
                "candidate_funnel\\.terminal_dispositions must contain "
                "non-negative integers",
            ):
                assemble_final_payload(manifest_path, refined, now=self.now)

    def test_forge_rejects_noncanonical_history_path_before_formal_write(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)
        wrong_history = self.runtime / "history.json"

        with self.assertRaisesRegex(ForgeContractError, "history_path must be canonical"):
            forge_briefing(
                manifest_path,
                refined,
                news_dir=self.news,
                history_path=wrong_history,
                update_runtime_state=False,
                now=self.now,
            )

        self.assertFalse(wrong_history.exists())
        self.assertEqual(list(self.news.glob("intelligence_*_briefing.*")), [])

    def test_forge_rejects_news_dir_outside_bound_snapshot_before_formal_write(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)
        wrong_news = self.root / "wrong-news"

        with self.assertRaisesRegex(ForgeContractError, "archive news_dir does not match"):
            forge_briefing(
                manifest_path,
                refined,
                news_dir=wrong_news,
                history_path=wrong_news / ".pih_history_v2.json",
                update_runtime_state=False,
                now=self.now,
            )

        self.assertEqual(list(wrong_news.glob("intelligence_*_briefing.*")), [])

    def test_history_postcommit_failure_keeps_formal_triplet_and_reports_failure(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)
        original_rebuild = forge_module.rebuild_history
        rebuild_calls = 0

        def fail_history_postcommit(*args, **kwargs):
            nonlocal rebuild_calls
            rebuild_calls += 1
            if rebuild_calls == 2:
                raise OSError("injected derived history failure")
            return original_rebuild(*args, **kwargs)

        with patch.object(forge_module, "rebuild_history", side_effect=fail_history_postcommit):
            with self.assertRaisesRegex(ForgeContractError, "derived history failure"):
                forge_briefing(
                    manifest_path,
                    refined,
                    news_dir=self.news,
                    history_path=self.history,
                    update_runtime_state=False,
                    now=self.now,
                )

        compact = self.news / "intelligence_20260810_briefing"
        self.assertTrue(compact.with_suffix(".json").is_file())
        self.assertTrue(compact.with_suffix(".md").is_file())
        self.assertTrue((self.news / f"{compact.name}.manifest.json").is_file())
        self.assertEqual(load_manifest(manifest_path)["stages"]["archive"]["status"], "failed")

    def test_same_day_replacement_rebuilds_history_without_ghost_event(self):
        old_payload = _retarget_fixture_event(
            valid_v12_payload(),
            actor="Superseded Hospital",
            url="https://old.example/superseded",
            title="Superseded AI pilot",
        )
        old_archive = self.news / "intelligence_20260810_briefing.json"
        old_archive.parent.mkdir(parents=True, exist_ok=True)
        old_archive.write_text(json.dumps(old_payload), encoding="utf-8")
        old_event_id = old_payload["top_10"][0]["event_id"]
        rebuild_history(news_dir=self.news, history_file=self.history, now=self.now)

        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)

        forge_briefing(
            manifest_path,
            refined,
            news_dir=self.news,
            history_path=self.history,
            update_runtime_state=False,
            now=self.now,
        )

        entries = json.loads(self.history.read_text(encoding="utf-8"))["entries"]
        event_ids = {entry["event_id"] for entry in entries}
        self.assertNotIn(old_event_id, event_ids)
        self.assertIn(payload["top_10"][0]["event_id"], event_ids)

    def test_new_run_rejects_frozen_v12_refined_core(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined-v12.json"
        payload = valid_v12_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)

        with self.assertRaisesRegex(ForgeContractError, "schema_version must be 1.4"):
            preview_briefing(manifest_path, refined, now=self.now)

    def test_preview_is_read_only_for_news_history_and_manifest(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)
        manifest_before = manifest_path.read_bytes()
        news_before = sorted(str(path.relative_to(self.news)) for path in self.news.rglob("*"))

        assembled, markdown = preview_briefing(
            manifest_path, refined, now=self.now
        )

        self.assertEqual(assembled["pipeline"]["semantic_review"]["status"], "passed")
        self.assertIn("临床 AI 评估发布", markdown)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(
            sorted(str(path.relative_to(self.news)) for path in self.news.rglob("*")),
            news_before,
        )
        self.assertFalse(self.history.exists())

    def test_preview_chain_rejects_unrelated_requested_url_before_assembly(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined-unrelated-access.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {
                "run_status": "degraded",
                "coverage_confidence": "medium",
                "baseline_status": "degraded",
            }
        )
        payload["top_10"][0]["access_check"].update(
            {
                "requested_url": "https://unrelated.invalid/proof",
                "final_url": "https://unrelated.invalid/proof",
            }
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(RunContractError, "requested_url does not match item url"):
            self._register_reviews(manifest_path, refined)

    def test_forge_rejects_core_identity_drift(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "report_date": "2026-08-09"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "report_date"):
            self._register_reviews(manifest_path, refined)

    def test_forge_rejects_requested_ratio_drift_from_manifest(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined-ratio-drift.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        payload["mix"].update(
            {
                "requested_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
                "ratio_source": "user",
                "ratio_reason": "用户明确指定",
                "effective_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
                "target_counts": {"technology": 0, "healthcare_digital": 1},
                "supply_exception": {
                    "applied": False,
                    "reason": "none",
                    "missing_domains": [],
                },
            }
        )
        refined.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)

        with self.assertRaisesRegex(ForgeContractError, "mix.requested_ratio"):
            preview_briefing(manifest_path, refined, now=self.now)

    def test_forge_rejects_skill_bundle_drift_after_run_creation(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)
        (self.root / "resource-manifest.json").write_text('{"changed":true}', encoding="utf-8")

        with self.assertRaisesRegex(ForgeContractError, "skill bundle|resource manifest"):
            forge_briefing(
                manifest_path,
                refined,
                news_dir=self.news,
                history_path=self.history,
                update_runtime_state=False,
            )

    def test_forge_rejects_event_already_present_in_bound_history(self):
        prior = self.news / "intelligence_20260809_briefing.json"
        prior.parent.mkdir(parents=True, exist_ok=True)
        historical_payload = valid_v12_payload()
        historical_payload["report_date"] = "2026-08-09"
        historical_payload["generated_at"] = "2026-08-09T09:00:00+08:00"
        historical_payload["window"].update({"start": "2026-08-03", "end": "2026-08-09"})
        historical_item = historical_payload["top_10"][0]
        historical_item["observed_at"] = "2026-08-09T09:00:00+08:00"
        historical_item["retrieved_at"] = "2026-08-09T09:00:00+08:00"
        historical_item["access_check"]["checked_at"] = "2026-08-09T09:00:00+08:00"
        historical_hash = item_hash(historical_item)
        historical_payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
            historical_hash
        ]
        historical_payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = historical_hash
        prior.write_text(json.dumps(historical_payload), encoding="utf-8")
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "bound history snapshot"):
            self._register_reviews(manifest_path, refined)
        self.assertNotIn("red_team_request", load_manifest(manifest_path)["artifacts"])

    def test_cross_report_date_forge_allows_only_one_shared_event(self):
        manifest_a = self._run_with_baseline(
            report_date="2026-08-10",
            run_id="run-forge-a",
        )
        manifest_b = self._run_with_baseline(
            report_date="2026-08-09",
            run_id="run-forge-b",
        )

        def build_payload(report_date: str, run_id: str) -> dict:
            payload = valid_v14_payload()
            report_day = date.fromisoformat(report_date)
            payload.update(
                {
                    "run_id": run_id,
                    "report_date": report_date,
                    "generated_at": self.now.isoformat(),
                    "model_used": "semantic_model",
                }
            )
            payload["window"].update(
                {
                    "start": (report_day - timedelta(days=6)).isoformat(),
                    "end": report_date,
                }
            )
            payload["coverage"].update(
                {
                    "run_status": "degraded",
                    "coverage_confidence": "medium",
                    "baseline_status": "degraded",
                }
            )
            return payload

        refined_a = manifest_a.parent / "refined.json"
        refined_b = manifest_b.parent / "refined.json"
        refined_a.write_text(
            json.dumps(build_payload("2026-08-10", "run-forge-a")),
            encoding="utf-8",
        )
        refined_b.write_text(
            json.dumps(build_payload("2026-08-09", "run-forge-b")),
            encoding="utf-8",
        )
        refined_a = self._register_reviews(manifest_a, refined_a)
        refined_b = self._register_reviews(manifest_b, refined_b)

        original_precondition = forge_module._assert_history_precondition
        first_locked = threading.Event()
        release_first = threading.Event()
        worker_errors: list[BaseException] = []

        def hold_first_locked_precondition(manifest, news_dir, items):
            state = original_precondition(manifest, news_dir, items)
            if manifest["run_id"] == "run-forge-a":
                first_locked.set()
                if not release_first.wait(5):
                    raise TimeoutError("first forge owner was not released")
            return state

        def forge_first() -> None:
            try:
                forge_briefing(
                    manifest_a,
                    refined_a,
                    news_dir=self.news,
                    history_path=self.history,
                    update_runtime_state=False,
                    now=self.now,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                worker_errors.append(exc)

        with patch.object(
            forge_module,
            "_assert_history_precondition",
            side_effect=hold_first_locked_precondition,
        ):
            worker = threading.Thread(target=forge_first, daemon=True)
            worker.start()
            self.assertTrue(
                first_locked.wait(5),
                "first forge did not reach the locked history precondition",
            )
            try:
                with self.assertRaisesRegex(
                    ArchiveTransactionError, "another archive transaction owns"
                ):
                    forge_briefing(
                        manifest_b,
                        refined_b,
                        news_dir=self.news,
                        history_path=self.history,
                        update_runtime_state=False,
                        now=self.now,
                    )
            finally:
                release_first.set()
                worker.join(5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(worker_errors, [])
            with self.assertRaisesRegex(
                ForgeContractError, "formal archive history changed"
            ):
                forge_briefing(
                    manifest_b,
                    refined_b,
                    news_dir=self.news,
                    history_path=self.history,
                    update_runtime_state=False,
                    now=self.now,
                )

        archives = sorted(self.news.glob("intelligence_*_briefing.json"))
        self.assertEqual(len(archives), 1)
        event_ids = [
            item["event_id"]
            for archive in archives
            for item in json.loads(archive.read_text(encoding="utf-8"))["top_10"]
        ]
        self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_same_day_existing_archive_is_excluded_but_hash_guarded(self):
        existing = self.news / "intelligence_20260810_briefing.json"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text(
            json.dumps(
                {
                    "schema_version": "1.2",
                    "report_date": "2026-08-10",
                    "generated_at": "2026-08-10T08:00:00+08:00",
                    "top_10": [valid_v12_payload()["top_10"][0]],
                }
            ),
            encoding="utf-8",
        )
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update({"run_id": "run-forge", "model_used": "semantic_model"})
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        refined = self._register_reviews(manifest_path, refined)

        result = forge_briefing(
            manifest_path,
            refined,
            news_dir=self.news,
            history_path=self.history,
            update_runtime_state=False,
            now=self.now,
        )

        self.assertEqual(result.json_path, existing)

    def test_forge_rejects_generated_at_before_run_creation(self):
        manifest_path = self._run_with_baseline()
        refined = self.runtime / "refined.json"
        payload = valid_v14_payload()
        payload.update(
            {
                "run_id": "run-forge",
                "model_used": "semantic_model",
                "generated_at": "2026-08-10T08:59:59+08:00",
            }
        )
        payload["coverage"].update(
            {"run_status": "degraded", "coverage_confidence": "medium", "baseline_status": "degraded"}
        )
        refined.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "cannot precede run creation"):
            self._register_reviews(manifest_path, refined)


if __name__ == "__main__":
    unittest.main()
