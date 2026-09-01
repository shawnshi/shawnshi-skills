import json
import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from zoneinfo import ZoneInfo

import run_daily
from run_contract import RunContractError, load_manifest


class RunDailyTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_rejects_excessive_concurrency_before_runtime_writes(self):
        with self.assertRaisesRegex(RunContractError, "between 1 and"):
            await run_daily.prepare_run(
                max_concurrency=run_daily.MAX_CONCURRENCY + 1,
            )

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
                "review_mode": "no_l4_fast_path",
                "max_turns": 1,
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
                patch(
                    "run_contract.build_review_request",
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
                max_turns=2,
            )
            parsed = json.loads(output.getvalue())
            self.assertEqual(parsed["review_kind"], "red_team")
            self.assertEqual(parsed["review_mode"], request["review_mode"])
            self.assertEqual(parsed["max_turns"], request["max_turns"])

    def test_validate_semantic_draft_command_is_read_only(self):
        manifest = Path("manifest.json")
        refined = Path("refined.json")
        semantic = Path("semantic.json")
        output = io.StringIO()

        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_daily.py",
                    "validate-semantic-draft",
                    "--manifest",
                    str(manifest),
                    "--refined",
                    str(refined),
                    "--semantic-receipt",
                    str(semantic),
                ],
            ),
            patch(
                "run_contract.validate_semantic_draft",
                return_value=["bounded warning"],
            ) as validator,
            redirect_stdout(output),
        ):
            run_daily.main()

        validator.assert_called_once_with(manifest, refined, semantic)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "valid", "warnings": ["bounded warning"]},
        )

    def test_validate_red_team_draft_command_is_read_only(self):
        manifest = Path("manifest.json")
        refined = Path("refined.json")
        semantic = Path("semantic.json")
        red_team = Path("red-team.draft.json")
        output = io.StringIO()

        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_daily.py",
                    "validate-red-team-draft",
                    "--manifest",
                    str(manifest),
                    "--refined",
                    str(refined),
                    "--semantic-receipt",
                    str(semantic),
                    "--red-team-receipt",
                    str(red_team),
                ],
            ),
            patch(
                "run_contract.validate_red_team_draft",
                return_value=["bounded warning"],
            ) as validator,
            redirect_stdout(output),
        ):
            run_daily.main()

        validator.assert_called_once_with(manifest, refined, semantic, red_team)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "valid", "warnings": ["bounded warning"]},
        )

    def test_normalize_published_at_command_uses_public_normalizer(self):
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_daily.py",
                    "normalize-published-at",
                    "--value",
                    "2026-08-20T23:30:00-07:00",
                ],
            ),
            patch(
                "run_contract.normalize_published_at",
                return_value="2026-08-20",
            ) as normalizer,
            redirect_stdout(output),
        ):
            run_daily.main()

        normalizer.assert_called_once_with("2026-08-20T23:30:00-07:00")
        self.assertEqual(
            json.loads(output.getvalue()),
            {"published_at": "2026-08-20"},
        )

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
            "window": {
                "start": "2026-08-04",
                "end": "2026-08-10",
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
                ("policy-competition", "Sentinel"),
                ("risk-counterevidence", "Ranger"),
            },
        )

    def test_verified_primary_evidence_can_satisfy_policy_and_risk_lanes(self):
        def candidate(title, url):
            return {
                "provisional_domain": "technology",
                "title": title,
                "summary_hint": title,
                "keyword_connection_hint": title,
                "url": url,
                "published_at": "2026-08-09T08:00:00+00:00",
                "source_type": "primary",
                "access_check": {
                    "status": "verified",
                    "requested_url": url,
                },
            }

        candidates = {
            "items": [
                *[
                    candidate(f"technology {index}", f"https://example.org/t{index}")
                    for index in range(6)
                ],
                *[
                    {
                        **candidate(f"healthcare {index}", f"https://example.org/h{index}"),
                        "provisional_domain": "healthcare_digital",
                    }
                    for index in range(4)
                ],
            ],
            "metadata": {
                "coverage": {
                    "source_failed": 0,
                    "source_success_rate": 1.0,
                    "dated_candidate_rate": 1.0,
                }
            },
        }
        candidates["items"][0]["title"] = "policy update"
        candidates["items"][0]["summary_hint"] = "policy update"
        candidates["items"][1]["title"] = "risk disclosure"
        candidates["items"][1]["summary_hint"] = "risk disclosure"
        manifest = {
            "mix_request": {
                "requested_ratio": {"technology": 0.6, "healthcare_digital": 0.4}
            },
            "window": {"start": "2026-08-04", "end": "2026-08-10"},
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

        self.assertEqual(gaps, [])

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
            blackboard_paths = []

            async def fake_scan_all(**kwargs):
                calls.append("baseline")
                blackboard_paths.append(kwargs["blackboard_path"])
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
                blackboard_paths.append(kwargs["blackboard_path"])
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
                patch("fetch_news.scan_all", side_effect=fake_scan_all),
                patch("refine.refine", side_effect=fake_refine),
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
            self.assertEqual(
                blackboard_paths,
                [
                    runtime / "runs" / "daily-test" / "intelligence_blackboard.json",
                    runtime / "runs" / "daily-test" / "intelligence_blackboard.json",
                ],
            )
            self.assertIsNotNone(result.supplement_request_path)
            supplement_request_path = result.supplement_request_path
            assert supplement_request_path is not None
            self.assertTrue(supplement_request_path.exists())
            request = json.loads(supplement_request_path.read_text(encoding="utf-8"))
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
            self.assertEqual(
                manifest["artifacts"]["focus_config"]["artifact_sha256"],
                hashlib.sha256(focus.read_bytes()).hexdigest(),
            )
            self.assertIn("history_snapshot", manifest["artifacts"])
            self.assertIn("history_review_slice", manifest["artifacts"])
            review_slice = json.loads(
                Path(
                    manifest["artifacts"]["history_review_slice"]["artifact_path"]
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(review_slice["dedupe_days"], 7)
            self.assertEqual(
                review_slice["generated_at"],
                "2026-08-10T23:59:59.999999+08:00",
            )
            self.assertEqual(review_slice["entries"], [])
            self.assertEqual(manifest["stages"]["supplemental"]["status"], "running")

    def test_run_scoped_cli_rejects_installed_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "run_manifest.json"
            expected = root / "snapshot" / "scripts" / "run_daily.py"
            manifest.write_text(
                json.dumps(
                    {
                        "bundle_snapshot": {
                            "execution_cli_path": str(expected.resolve())
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "immutable execution CLI"):
                run_daily._enforce_run_scoped_cli(manifest)

    async def test_invalid_concurrency_is_rejected_before_run_creation(self):
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
            with self.assertRaisesRegex(RunContractError, "must be positive"):
                await run_daily.prepare_run(
                    runtime_dir=runtime,
                    skill_path=skill,
                    focus_path=root / "unused.json",
                    max_concurrency=0,
                )

            self.assertFalse(runtime.exists())

    async def test_existing_archive_requires_explicit_replacement_before_run_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            (news / "intelligence_20260901_briefing.json").write_text(
                "{}", encoding="utf-8"
            )
            focus = root / "focus.json"
            focus.write_text("{}", encoding="utf-8")
            runtime = root / "runtime"
            with self.assertRaisesRegex(
                RunContractError, "formal archive targets already exist"
            ):
                await run_daily.prepare_run(
                    report_date="2026-09-01",
                    runtime_dir=runtime,
                    news_dir=news,
                    focus_path=focus,
                )
            self.assertFalse(runtime.exists())

    async def test_missing_or_malformed_focus_is_rejected_before_run_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "SKILL.md"
            skill.write_text("skill", encoding="utf-8")
            for label, content in (("missing", None), ("malformed", "[")):
                with self.subTest(label=label):
                    runtime = root / f"runtime-{label}"
                    focus = root / f"focus-{label}.json"
                    if content is not None:
                        focus.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(RunContractError, "focus config"):
                        await run_daily.prepare_run(
                            runtime_dir=runtime,
                            skill_path=skill,
                            focus_path=focus,
                        )
                    self.assertFalse(runtime.exists())

    async def test_baseline_exception_is_recorded_as_failed(self):
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
            focus.write_text("{}", encoding="utf-8")

            def fake_rebuild_history(*, history_file, **kwargs):
                history_file.parent.mkdir(parents=True, exist_ok=True)
                history_file.write_text("{}", encoding="utf-8")

            with (
                patch("update_index.rebuild_history", side_effect=fake_rebuild_history),
                patch("fetch_news.scan_all", side_effect=RuntimeError("network stack failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "network stack failed"):
                    await run_daily.prepare_run(
                        report_date="2026-08-10",
                        runtime_dir=runtime,
                        news_dir=root / "news",
                        skill_path=skill,
                        focus_path=focus,
                        run_id="failed-run",
                        now=datetime(2026, 8, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                    )

            manifest = load_manifest(runtime / "runs" / "failed-run" / "run_manifest.json")
            self.assertEqual(manifest["stages"]["baseline"]["status"], "failed")
            self.assertEqual(
                manifest["stages"]["baseline"]["metadata"]["error_type"],
                "RuntimeError",
            )


class ImportPerformanceContractTests(unittest.TestCase):
    def _fresh_imports(self, module_name):
        names = ["fetch_news", "refine", "forge", "run_contract", "aiohttp", "feedparser", "bs4"]
        code = (
            "import importlib,json,sys; "
            f"importlib.import_module({module_name!r}); "
            f"print(json.dumps({{name: name in sys.modules for name in {names!r}}}))"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", code],
            cwd=Path(__file__).resolve().parent,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_run_daily_does_not_eagerly_import_command_specific_modules(self):
        loaded = self._fresh_imports("run_daily")

        self.assertEqual(loaded, {name: False for name in loaded})

    def test_fetch_news_does_not_eagerly_import_network_parsers(self):
        loaded = self._fresh_imports("fetch_news")

        self.assertFalse(loaded["aiohttp"])
        self.assertFalse(loaded["feedparser"])
        self.assertFalse(loaded["bs4"])


if __name__ == "__main__":
    unittest.main()
