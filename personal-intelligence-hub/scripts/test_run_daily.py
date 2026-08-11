import json
import hashlib
import io
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from zoneinfo import ZoneInfo

import run_daily
from run_contract import load_manifest


class RunDailyTests(unittest.IsolatedAsyncioTestCase):
    def test_red_team_prepare_command_forwards_semantic_receipt_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            refined = root / "refined.json"
            semantic = root / "semantic.json"
            request_path = root / "red_team_review_request.json"
            request = {
                "review_kind": "red_team",
                "reviewer_id": "RedTeam",
                "invocation_id": "invocation",
            }
            output = io.StringIO()

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "run_daily.py",
                        "prepare-review",
                        "--manifest",
                        str(manifest),
                        "--refined",
                        str(refined),
                        "--semantic-receipt",
                        str(semantic),
                        "--kind",
                        "red_team",
                    ],
                ),
                patch.object(
                    run_daily,
                    "build_review_request",
                    return_value=(request_path, request),
                ) as builder,
                redirect_stdout(output),
            ):
                run_daily.main()

            builder.assert_called_once_with(
                manifest,
                refined,
                "red_team",
                semantic_receipt_path=semantic,
                max_turns=3,
            )
            self.assertEqual(json.loads(output.getvalue())["review_kind"], "red_team")

    def test_degraded_coverage_forces_domain_remediation_when_ratio_is_met(self):
        items = []
        for index in range(6):
            items.append(
                {
                    "provisional_domain": "technology",
                    "title": "policy model release" if index == 0 else f"technology {index}",
                    "summary_hint": "primary source",
                    "keyword_connection_hint": "policy" if index == 0 else "technology",
                }
            )
        for index in range(4):
            items.append(
                {
                    "provisional_domain": "healthcare_digital",
                    "title": "risk incident" if index == 0 else f"healthcare {index}",
                    "summary_hint": "primary source",
                    "keyword_connection_hint": "risk" if index == 0 else "healthcare",
                }
            )
        candidates = {
            "items": items,
            "metadata": {
                "coverage": {
                    "source_failed": 8,
                    "source_success_rate": 0.2,
                    "dated_candidate_rate": 0.5,
                }
            },
        }
        manifest = {
            "mix_request": {
                "requested_ratio": {"technology": 0.6, "healthcare_digital": 0.4}
            },
            "stages": {},
        }
        focus = {
            "filters": {"max_top10": 10},
            "coverage_policy": {
                "minimum_source_success_rate": 0.7,
                "minimum_dated_candidate_rate": 0.7,
                "lanes": {
                    "Sentinel": {"min_candidates": 1, "keywords": ["policy"]},
                    "Ranger": {"min_candidates": 1, "keywords": ["risk"]},
                },
            },
        }

        gaps = run_daily.assess_supplement_gaps(candidates, manifest, focus)

        self.assertEqual(
            {(gap["gap_id"], gap["lane"]) for gap in gaps},
            {
                ("technology-coverage-integrity", "TechRadar"),
                ("healthcare-coverage-integrity", "HealthcareRadar"),
            },
        )

    async def test_prepare_runs_baseline_before_candidates_and_builds_bound_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            skill = root / "SKILL.md"
            skill.write_text("skill", encoding="utf-8")
            (root / "resource-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "skill": root.name,
                        "skill_md": "SKILL.md",
                        "skill_md_sha256": hashlib.sha256(b"skill").hexdigest(),
                        "top_level_file_hashes": [],
                        "declared_local_dependencies": [],
                        "missing_declared_dependencies": [],
                    }
                ),
                encoding="utf-8",
            )
            focus = root / "focus.json"
            focus.write_text(
                json.dumps(
                    {
                        "filters": {"max_top10": 10},
                        "coverage_policy": {
                            "lanes": {
                                "Sentinel": {"min_candidates": 1, "query_scope": "policy procurement", "keywords": ["policy"]},
                                "Ranger": {"min_candidates": 1, "query_scope": "risk failure", "keywords": ["risk"]}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            async def fake_scan_all(**kwargs):
                calls.append("baseline")
                payload = {
                    "generated_at": "2026-08-10T09:00:00+08:00",
                    "items": [],
                    "quarantine": [],
                    "coverage": {
                        "run_status": "degraded",
                        "baseline_status": "degraded",
                        "coverage_confidence": "medium",
                        "source_attempted": 1,
                        "source_succeeded": 1,
                        "source_failed": 0,
                        "source_success_rate": 1.0,
                        "raw_candidates": 0,
                        "dated_candidates": 0,
                        "quarantined_candidates": 0,
                        "dated_candidate_rate": 0.0,
                        "required_lane_failures": [],
                        "reasons": ["sources completed but produced no candidates"],
                    },
                    "candidate_funnel": {
                        "raw": 0,
                        "dated": 0,
                        "quarantined": 0,
                        "within_window": 0,
                        "outside_window": 0,
                        "excluded": 0,
                        "retained": 0,
                    },
                    "metadata": {
                        "topic": kwargs["topic"],
                        "region": kwargs["region"],
                        "window": {
                            "mode": "calendar_days",
                            "days": 7,
                            "start": "2026-08-04",
                            "end": "2026-08-10",
                            "timezone": "Asia/Shanghai",
                        },
                    },
                }
                kwargs["output_path"].write_text(json.dumps(payload), encoding="utf-8")
                kwargs["current_output_path"].write_text(json.dumps(payload), encoding="utf-8")
                return payload

            def fake_refine(*args, **kwargs):
                calls.append("candidates")
                payload = {
                    "contract_version": "candidate-pool/1.0",
                    "artifact_kind": "candidates_only",
                    "review_status": "unreviewed",
                    "model_used": "heuristic",
                    "run_id": "daily-test",
                    "items": [],
                    "candidate_funnel": {"observed": 0, "retained_for_review": 0, "terminal_dispositions": {"retained_for_review": 0}},
                }
                kwargs["candidates_path"].write_text(json.dumps(payload), encoding="utf-8")
                return payload

            with (
                patch.object(run_daily.fetch_news, "scan_all", side_effect=fake_scan_all),
                patch.object(run_daily.refine, "refine", side_effect=fake_refine),
            ):
                result = await run_daily.prepare_run(
                    report_date="2026-08-10",
                    runtime_dir=runtime,
                    news_dir=root / "news",
                    skill_path=skill,
                    focus_path=focus,
                    run_id="daily-test",
                    now=datetime(2026, 8, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                )

            self.assertEqual(calls, ["baseline", "candidates"])
            self.assertTrue(result.supplement_request_path.exists())
            request = json.loads(result.supplement_request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["run_id"], "daily-test")
            self.assertEqual(
                {gap["lane"] for gap in request["gaps"]},
                {"TechRadar", "HealthcareRadar", "Sentinel", "Ranger"},
            )
            manifest = load_manifest(result.manifest_path)
            expected_default = {"technology": 0.6, "healthcare_digital": 0.4}
            self.assertEqual(
                manifest["mix_request"]["schema_default_ratio"], expected_default
            )
            self.assertEqual(
                manifest["mix_request"]["requested_ratio"], expected_default
            )
            self.assertEqual(manifest["stages"]["baseline"]["status"], "degraded")
            self.assertIn("history_snapshot", manifest["artifacts"])
            self.assertEqual(manifest["stages"]["supplemental"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
