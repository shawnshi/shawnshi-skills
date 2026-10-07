"""Contract tests for the pinned-epoch Daily Sync orchestrator (``pia_daily.py``).

The orchestrator must (a) pin one evaluation epoch, (b) never run a dependent
stage from an incomplete upstream stage, and (c) surface the upstream reason
instead of reporting a silent success.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia  # noqa: E402
import pia_daily  # noqa: E402
from status_contract import status_rank  # noqa: E402
import pia_refresh  # noqa: E402
import pia_trigger_ledger  # noqa: E402
import quote_evidence_contract  # noqa: E402
import pia_risk_diagnostic  # noqa: E402


def positions_payload() -> dict:
    return {
        "base_currency": "CNY",
        "positions": [
            {"symbol": "600000.SS", "quantity": 3, "avg_cost": 100.0, "currency": "CNY",
             "market": "CN", "asset_type": "stock"},
            {"symbol": "CASH_CNY", "quantity": 500, "avg_cost": 1.0, "currency": "CNY",
             "market": "CASH", "asset_type": "cash"},
        ],
        "exchange_rates": {"CNY": 1.0},
        "exchange_rate_metadata": {},
    }


class DailyRunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task_dir = self.root / "task"

    def tearDown(self):
        self._tmp.cleanup()

    def run_pipeline(self, *extra: str) -> tuple[int, dict]:
        argv = ["--positions-file", str(self.positions), "--task-dir", str(self.task_dir),
                "--skip-watchlist", *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_daily.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_plan_only_lists_the_ordered_pipeline(self):
        code, payload = self.run_pipeline("--plan-only")
        self.assertEqual(code, 0)
        self.assertEqual(payload["plan"][:4], ["refresh", "quotes", "daily_sync", "weights"])
        self.assertTrue(payload["evaluation_epoch"])
        self.assertEqual(payload["decision_scope"], "advisory")

    def test_refresh_force_is_opt_in_and_forwarded(self):
        captured: dict = {}

        def fake_module(main, argv):
            if "--task-dir" in argv:
                captured["refresh_argv"] = list(argv)
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 3, {"status": "failed", "detail_status": "derived_snapshot_exists",
                           "errors": ["already exists; pass --force to overwrite"]}
            return 0, {"status": "complete", "detail_status": "current_weights_computed",
                       "current_weights": []}

        with mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            code, payload = self.run_pipeline()
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["detail_status"], "refresh_stage_failed")
        self.assertNotIn("--force", captured["refresh_argv"])

        with mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            self.run_pipeline("--force")
        self.assertIn("--force", captured["refresh_argv"])

    def test_stable_router_forwards_daily_run_force(self):
        captured: dict = {}

        def fake_child(**kwargs):
            captured["arguments"] = list(kwargs["child_arguments"])
            return {"status": "complete", "detail_status": "daily_run_complete"}, 0

        with mock.patch.object(pia, "_run_child", side_effect=fake_child):
            pia._dispatch(pia._build_parser().parse_args(
                ["daily-run", "--positions-file", "positions.json", "--task-dir", "task",
                 "--plan-only", "--force"]))
        self.assertIn("--force", captured["arguments"])

    def test_explicit_research_only_remains_available(self):
        code, payload = self.run_pipeline("--decision-scope", "research_only", "--plan-only")
        self.assertEqual(code, 0)
        self.assertEqual(payload["decision_scope"], "research_only")

    def test_stable_router_defaults_to_advisory(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia.main(["daily-run", "--positions-file", str(self.positions),
                             "--task-dir", str(self.task_dir), "--plan-only"])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["decision_scope"], "advisory")
        self.assertEqual(payload["result"]["decision_scope"], "advisory")

    def test_missing_positions_file_fails_before_any_stage(self):
        argv = ["--positions-file", str(self.root / "absent.json"),
                "--task-dir", str(self.task_dir)]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_daily.main(argv)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "positions_file_missing")
        self.assertNotIn("stages", payload)

    def test_refresh_failure_stops_the_pipeline(self):
        broken = positions_payload()
        broken["positions"][0].pop("avg_cost")
        self.positions.write_text(json.dumps(broken), encoding="utf-8")
        code, payload = self.run_pipeline()
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["detail_status"], "refresh_stage_failed")
        self.assertEqual([stage["stage"] for stage in payload["stages"]], ["refresh"])

    def test_quote_failure_stops_dependent_stages(self):
        with mock.patch.object(
            pia_daily, "run_quotes",
            return_value=(1, {"status": "insufficient_data",
                              "detail_status": "quote_batch_incomplete",
                              "errors": ["quote batch coverage is incomplete"]}, None),
        ):
            code, payload = self.run_pipeline()
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "quote_stage_incomplete")
        stages = [stage["stage"] for stage in payload["stages"]]
        self.assertEqual(stages, ["refresh", "quotes"])
        self.assertNotIn("weights", stages)

    def test_every_stage_is_recorded_with_its_artifact(self):
        captured: dict = {}

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            captured["symbols"] = symbols
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text(json.dumps({"records": [], "portfolio_batch_audit": {}}),
                              encoding="utf-8")
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, quotes

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes):
            def fake_module(main, argv):
                if "--task-dir" in argv:  # the refresh stage is the only one carrying --task-dir
                    snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    snapshot.write_bytes(self.positions.read_bytes())
                    return 0, {"status": "complete", "detail_status": "fx_snapshot_written"}
                if "--thesis-evidence-file" in argv or "--decision-scope" in argv:
                    return 1, {"status": "incomplete",
                               "detail_status": "thesis_not_assessed",
                               "completeness": {"complete": True}}
                return 0, {"status": "complete", "detail_status": "current_weights_computed",
                           "current_weights": []}
            with mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
                code, payload = self.run_pipeline()
        self.assertEqual(captured["symbols"], ["600000.SS"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "incomplete")
        self.assertEqual(payload["detail_status"], "thesis_not_assessed")
        self.assertEqual(payload["stages"][2]["status"], "incomplete")
        self.assertEqual(payload["stages"][2]["exit_code"], 1)
        self.assertEqual(payload["stages"][3]["status"], "complete")
        summary = json.loads((self.task_dir / "out" / "daily_run_summary.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual([stage["stage"] for stage in summary["stages"]],
                         ["refresh", "quotes", "daily_sync", "weights"])
        self.assertEqual(summary["positions_input_sha256"],
                         pia_daily.sha256_file(self.positions))

    def test_summary_reports_scope_validity_and_unrun_stages(self):
        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text(json.dumps({"records": [], "portfolio_batch_audit": {}}),
                              encoding="utf-8")
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, quotes

        captured: dict = {}

        def fake_module(main, argv):
            if "--task-dir" in argv:
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete", "detail_status": "fx_snapshot_written"}
            captured["argv"] = argv
            return 0, {"status": "complete", "detail_status": "current_weights_computed",
                       "current_weights": []}

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes),                 mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            _code, payload = self.run_pipeline()

        inventory = payload["run_inventory"]
        self.assertEqual(inventory["decision_scope"], "advisory")
        self.assertEqual(inventory["stage_scopes"]["refresh"], "advisory")
        # The abort path still reports both the stages that never ran and the
        # stage the caller switched off: neither may look like an empty result.
        self.assertEqual(sorted(inventory["stages_run"]), ["daily_sync", "quotes", "refresh"])
        self.assertEqual(
            inventory["stages_not_run"],
            [{"stage": "weights", "reason": "not_reached_due_to_upstream_incomplete"},
             {"stage": "watchlist", "reason": "skipped_by_flag:--skip-watchlist"}],
        )
        self.assertEqual(inventory["valid_until_basis"], "conservative_shortest_quote_window")
        self.assertTrue(inventory["valid_until"].endswith("+00:00"))
        consistency = payload["status_consistency"]
        self.assertEqual(consistency["top_level_status"], payload["status"])
        # A parent may be stricter than its stages; it may never be softer.
        self.assertGreaterEqual(status_rank(consistency["top_level_status"]),
                                status_rank(consistency["stage_derived_status"]))
        self.assertTrue(consistency["consistent"])
        kinds = [item["kind"] for item in payload["residual_unknowns"]]
        self.assertIn("account_rules_not_verified", kinds)
        self.assertIn("run_not_complete", kinds)
        for stage in payload["stages"]:
            self.assertEqual(stage["decision_scope"], "advisory")


    def test_thesis_pack_replays_once_and_preserves_compatibility_artifact(self):
        pack = self.root / "evidence.json"
        pack.write_text("{}", encoding="utf-8")
        replay_calls = []

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text("{}", encoding="utf-8")
            return 0, {"status": "complete"}, quotes

        def fake_module(main, argv):
            if "--task-dir" in argv:
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete"}
            if "--quotes-file" in argv and "--filepath" not in argv:
                replay_calls.append(argv)
                return 0, {"status": "complete", "completeness": {"complete": True},
                           "thesis_red_team": {"status": "complete"}}
            return 0, {"status": "complete", "current_weights": []}

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            code, payload = self.run_pipeline("--thesis-evidence-file", str(pack))
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(len(replay_calls), 1)
        self.assertEqual(replay_calls[0][-2:], ["--thesis-evidence-file", str(pack)])
        out = self.task_dir / "out"
        self.assertEqual((out / "daily_sync.json").read_bytes(),
                         (out / "daily_sync_with_thesis.json").read_bytes())

    def test_requested_missing_thesis_pack_is_not_success(self):
        missing = self.root / "missing-evidence.json"

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text("{}", encoding="utf-8")
            return 0, {"status": "complete"}, quotes

        def fake_module(main, argv):
            if "--task-dir" in argv:
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete"}
            if "--quotes-file" in argv and "--filepath" not in argv:
                return 1, {"status": "incomplete", "completeness": {"complete": True}}
            return 0, {"status": "complete", "current_weights": []}

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            code, payload = self.run_pipeline("--thesis-evidence-file", str(missing))
        self.assertEqual((code, payload["status"]), (2, "insufficient_evidence"))
        self.assertEqual(payload["stages"][-1]["detail_status"], "thesis_pack_missing")
        self.assertTrue((self.task_dir / "out" / "weights.json").is_file())

    def test_thesis_pack_with_unclosed_evidence_stays_incomplete(self):
        pack = self.root / "evidence.json"
        pack.write_text("{}", encoding="utf-8")

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text("{}", encoding="utf-8")
            return 0, {"status": "complete"}, quotes

        def fake_module(main, argv):
            if "--task-dir" in argv:
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete"}
            if "--quotes-file" in argv and "--filepath" not in argv:
                return 1, {"status": "incomplete", "completeness": {"complete": True},
                           "thesis_red_team": {"status": "not_assessed"}}
            return 0, {"status": "complete", "current_weights": []}

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            code, payload = self.run_pipeline("--thesis-evidence-file", str(pack))
        self.assertEqual((code, payload["status"]), (1, "incomplete"))
        self.assertEqual(payload["detail_status"], "thesis_evidence_incomplete")
        self.assertEqual([stage["status"] for stage in payload["stages"][-2:]],
                         ["complete", "incomplete"])


class StageRunnerTests(unittest.TestCase):
    def test_refresh_without_artifact_is_a_failed_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            positions = root / "p.json"
            positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
            with mock.patch.object(
                pia_daily, "run_module",
                return_value=(0, {"status": "complete", "detail_status": "fx_snapshot_written"}),
            ):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    code = pia_daily.main(["--positions-file", str(positions),
                                           "--task-dir", str(root / "task"),
                                           "--skip-watchlist"])
            payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["stages"][0]["detail_status"], "derived_snapshot_missing")
    def test_argparse_style_main_is_driven_through_sys_argv(self):
        def main() -> None:
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("--value", required=True)
            args = parser.parse_args()
            print(json.dumps({"status": "complete", "value": args.value}))

        code, payload = pia_daily.run_module(main, ["--value", "7"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["value"], "7")

    def test_systemexit_codes_are_captured(self):
        def main(argv):
            print(json.dumps({"status": "incomplete", "detail_status": "nope"}))
            raise SystemExit(1)

        code, payload = pia_daily.run_module(main, [])
        self.assertEqual(code, 1)
        self.assertEqual(payload["detail_status"], "nope")

    def test_crash_is_reported_as_a_failed_stage(self):
        def main(argv):
            raise RuntimeError("boom")

        code, payload = pia_daily.run_module(main, [])
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "stage_crashed")
        self.assertIn("boom", payload["errors"][0])


class CoverageProbeStageTests(unittest.TestCase):
    """The coverage stage is optional, must never gate the critical path, and must
    report an unproven verdict without turning the whole run into a failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task_dir = self.root / "task"
        self.spec = self.root / "probes.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write_spec(self, probes) -> Path:
        self.spec.write_bytes(json.dumps({"schema_version": "pia_coverage_probes_v1",
                                          "probes": probes}).encode("utf-8"))
        return self.spec

    def probe(self, **overrides) -> dict:
        payload = {"channel": "cninfo", "target": "515650.SS", "control": "510300.SS",
                   "target_class": "etf", "control_class": "etf",
                   "channel_scope": "cninfo exchange disclosure", "window_days": 60}
        payload.update(overrides)
        return payload

    def test_spec_validation_rejects_incomplete_and_duplicate_probes(self):
        for probes, expected in (
            ([], "non-empty"),
            ([self.probe(target_class="fund")], "must be stock or etf"),
            ([self.probe(channel="")], "channel must be a non-empty string"),
            ([self.probe(), self.probe()], "duplicates an earlier probe"),
        ):
            with self.subTest(expected=expected):
                self.write_spec(probes)
                with self.assertRaises(ValueError) as ctx:
                    pia_daily.load_coverage_probes(self.spec)
                self.assertIn(expected, str(ctx.exception))

    def test_invalid_spec_stops_the_run_before_any_stage(self):
        self.write_spec([self.probe(target_class="fund")])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_daily.main(["--positions-file", str(self.positions),
                                   "--task-dir", str(self.task_dir),
                                   "--coverage-probe-file", str(self.spec)])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "coverage_probe_spec_invalid")
        self.assertFalse((self.task_dir / "out").exists())

    def test_plan_includes_the_stage_only_when_a_spec_is_supplied(self):
        self.write_spec([self.probe()])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            pia_daily.main(["--positions-file", str(self.positions), "--task-dir",
                            str(self.task_dir), "--plan-only"])
        plain = json.loads(buffer.getvalue())["plan"]
        self.assertNotIn("coverage-probe", plain)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            pia_daily.main(["--positions-file", str(self.positions), "--task-dir",
                            str(self.task_dir), "--plan-only",
                            "--coverage-probe-file", str(self.spec)])
        with_probe = json.loads(buffer.getvalue())["plan"]
        self.assertIn("coverage-probe", with_probe)
        self.assertLess(with_probe.index("weights"), with_probe.index("coverage-probe"))

    def test_unproven_probe_is_recorded_without_failing_the_run(self):
        self.write_spec([self.probe()])

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text("{}", encoding="utf-8")
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, quotes

        def fake_module(main, argv):
            # the probe child also carries --task-dir, so it must be checked first
            if argv[:1] == ["coverage-probe"]:
                return 2, {"status": "insufficient_data",
                           "detail_status": "coverage_unproven",
                           "target_count": 0, "control_count": 0,
                           "coverage_basis": "same_instrument_class_control",
                           "official_coverage": None,
                           "query_quality_notes": ["both roles answered with the empty shell"]}
            if "--task-dir" in argv:  # refresh
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete", "detail_status": "fx"}
            if "--decision-scope" in argv:  # offline replay
                return 1, {"status": "incomplete", "detail_status": "thesis_not_assessed",
                           "completeness": {"complete": True}}
            return 0, {"status": "complete", "detail_status": "current_weights_computed",
                       "current_weights": []}

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes),              mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = pia_daily.main(["--positions-file", str(self.positions),
                                       "--task-dir", str(self.task_dir),
                                       "--skip-watchlist",
                                       "--coverage-probe-file", str(self.spec)])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "incomplete")
        self.assertEqual(code, 1)
        stage = next(item for item in payload["stages"] if item["stage"] == "coverage-probe")
        # the stage completes (it produced a verdict); the verdict itself is data
        self.assertEqual(stage["status"], "complete")
        self.assertEqual(stage["detail_status"], "coverage_partially_unproven")
        self.assertEqual(stage["errors"], [])
        self.assertEqual(stage["probes"][0]["verdict"], "coverage_unproven")
        self.assertTrue(stage["unproven_probes"])
        self.assertTrue(Path(stage["artifacts"][0]).is_file())


class RiskDiagnosticStageTests(unittest.TestCase):
    """The optional risk stage must validate its history syntax up front, sit after the
    critical path, and record its coverage declaration (or fail closed loudly)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task_dir = self.root / "task"
        (self.task_dir / "raw").mkdir(parents=True)
        self.history = self.task_dir / "raw" / "history.json"
        self.history.write_bytes(json.dumps({"symbol": "600000.SS", "history": []}).encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_history_syntax_is_validated_and_duplicates_refused(self):
        for items, expected in (
            (["600000.SS"], "expects symbol=path"),
            (["=x.json"], "expects symbol=path"),
            (["600000.SS=a.json", "600000.SS=b.json"], "repeats the symbol"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError) as ctx:
                    pia_daily.parse_risk_histories(items, self.task_dir)
                self.assertIn(expected, str(ctx.exception))

    def test_relative_history_paths_resolve_against_the_task_dir(self):
        parsed = pia_daily.parse_risk_histories(["600000.SS=raw/history.json"], self.task_dir)
        self.assertEqual(parsed[0]["path"], str(self.task_dir / "raw" / "history.json"))

    def test_invalid_syntax_stops_the_run_before_any_stage(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_daily.main(["--positions-file", str(self.positions),
                                   "--task-dir", str(self.task_dir),
                                   "--risk-history", "600000.SS"])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "risk_history_spec_invalid")
        self.assertFalse((self.task_dir / "out").exists())

    def test_plan_places_the_stage_after_weights(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            pia_daily.main(["--positions-file", str(self.positions), "--task-dir",
                            str(self.task_dir), "--plan-only",
                            "--risk-history", "600000.SS=raw/history.json"])
        plan = json.loads(buffer.getvalue())["plan"]
        self.assertIn("risk-diagnostic", plan)
        self.assertLess(plan.index("weights"), plan.index("risk-diagnostic"))

    def _run_with_mock(self, risk_payload, risk_code=0):
        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            quotes = task_dir / "out" / "quotes.json"
            quotes.parent.mkdir(parents=True, exist_ok=True)
            quotes.write_text("{}", encoding="utf-8")
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, quotes

        def fake_module(main, argv):
            if argv[:1] == ["coverage-probe"]:
                return 2, {"status": "insufficient_data", "detail_status": "coverage_unproven",
                           "target_count": 0, "control_count": 0, "official_coverage": None}
            if "--task-dir" in argv:  # refresh
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete", "detail_status": "fx"}
            if "--decision-scope" in argv:  # offline replay
                return 1, {"status": "incomplete", "detail_status": "thesis_not_assessed",
                           "completeness": {"complete": True}}
            if "--history" in argv:  # the risk child takes --history, not --risk-history
                if risk_payload.get("status") == "complete":
                    out = Path(argv[argv.index("--out") + 1])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(risk_payload), encoding="utf-8")
                return risk_code, risk_payload
            return 0, {"status": "complete", "detail_status": "current_weights_computed",
                       "current_weights": []}

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes),              mock.patch.object(pia_daily, "run_module", side_effect=fake_module):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = pia_daily.main(["--positions-file", str(self.positions),
                                       "--task-dir", str(self.task_dir),
                                       "--skip-watchlist",
                                       "--risk-history", "600000.SS=raw/history.json"])
        return code, json.loads(buffer.getvalue())

    def test_stage_records_the_coverage_declaration(self):
        payload = {"status": "complete", "detail_status": "partial_risk_diagnostic_computed",
                   "observation_window": {"first": "2025-09-26", "last": "2026-09-24",
                                          "common_observations": 233},
                   "covered_subset_annualized_volatility": 0.28,
                   "coverage": {"covered_count": 9, "active_non_cash_count": 11,
                                "covered_share_of_non_cash_value": 0.7339,
                                "statement": "limited diagnostic; not the portfolio's risk contribution",
                                "excluded_symbols": [{"symbol": "515650.SS",
                                                      "reason": "no_history_supplied"}]},
                   "risk_contribution_within_subset": {"A": 0.6, "B": 0.3, "C": 0.1},
                   "method": {"labels": list(pia_risk_diagnostic.METHOD_LABELS)}}
        code, run = self._run_with_mock(payload)
        self.assertEqual(run["status"], "incomplete")
        self.assertEqual(code, 1)
        stage = next(item for item in run["stages"] if item["stage"] == "risk-diagnostic")
        self.assertEqual(stage["status"], "complete")
        self.assertEqual(stage["coverage"]["covered_count"], 9)
        self.assertEqual(stage["coverage"]["excluded_symbols"][0]["symbol"], "515650.SS")
        self.assertEqual(stage["top_risk_contributions"][0]["symbol"], "A")
        self.assertTrue(Path(stage["artifacts"][0]).is_file())

    def test_failed_stage_is_reported_as_incomplete(self):
        payload = {"status": "failed", "detail_status": "risk_diagnostic_input_invalid",
                   "errors": ["history file not found for 600000.SS"]}
        code, run = self._run_with_mock(payload, risk_code=3)
        self.assertEqual(code, 3)
        self.assertEqual(run["status"], "failed")
        stage = next(item for item in run["stages"] if item["stage"] == "risk-diagnostic")
        self.assertEqual(stage["status"], "failed")
        self.assertEqual(stage["artifacts"], [])
        self.assertIn("history file not found", stage["errors"][0])


class GateSnapshotCompositionTests(unittest.TestCase):
    """One command must deliver the readiness verdict when terms are supplied."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task_dir = self.root / "task"
        self.snapshot = self.root / "terms.json"
        self.snapshot.write_text(json.dumps({"schema_version": "pia_cn_actionability_v1"}),
                                 encoding="utf-8")
        self._real_run_module = pia_daily.run_module

    def tearDown(self):
        self._tmp.cleanup()

    def fake_quotes(self, positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
        quotes = task_dir / "out" / "quotes.json"
        quotes.parent.mkdir(parents=True, exist_ok=True)
        quotes.write_text(json.dumps({
            "records": [{"symbol": "600000.SS"}],
            "provider_receipt": {"provider": "yfinance", "outcomes": {"600000.SS": "ok"},
                                 "outcome_counts": {"ok": 1}},
            "portfolio_batch_audit": {
                "complete": True, "coverage_complete": True,
                "portfolio_matched_count": 1, "expected_active_symbols": ["600000.SS"],
                "quote_freshness_contracts": {"600000.SS": {"market_state": "REGULAR"}},
            },
        }), encoding="utf-8")
        return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, quotes

    def fake_module(self, gate_payload, gate_code, capture):
        def fake(main, argv):
            if getattr(main, "__module__", "") == "cn_actionability_gate":
                capture["gate_argv"] = list(argv)
                return gate_code, gate_payload
            if "--task-dir" in argv:
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete", "detail_status": "fx_snapshot_written"}
            if "--decision-scope" in argv:  # the offline replay; weights carries no scope
                return 0, {
                    "status": "complete", "detail_status": "daily_sync_complete",
                    "decision_scope": "advisory",
                    "completeness": {"complete": True},
                    "thesis_red_team": {"status": "complete", "evidence_status": "ok",
                                        "fatal_event_status": "no_condition_due_yet"},
                }
            return 0, {"status": "complete", "decision_scope": "advisory",
                       "detail_status": "current_weights_computed", "current_weights": []}
        return fake

    def run_pipeline(self, *extra: str) -> tuple[int, dict]:
        argv = ["--positions-file", str(self.positions), "--task-dir", str(self.task_dir),
                "--skip-watchlist", *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_daily.main(argv)
        return code, json.loads(buffer.getvalue())

    def _gate_passthrough(self):
        capture: dict = {}
        inner = self.fake_module({"status": "complete"}, 0, capture)

        def fake(main, argv):
            if getattr(main, "__module__", "") == "cn_actionability_gate":
                return self._real_run_module(main, argv)
            return inner(main, argv)
        return fake

    def test_supplied_snapshot_yields_one_command_readiness_verdict(self):
        capture: dict = {}
        gate_payload = {"status": "complete",
                        "detail_status": "input_terms_feasible_under_supplied_snapshots",
                        "actionability": "human_review_required_no_order"}
        with mock.patch.object(pia_daily, "run_quotes", side_effect=self.fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module(gate_payload, 0, capture)):
            code, payload = self.run_pipeline("--actionability-assessment", str(self.snapshot))

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(capture["gate_argv"][0], str(self.snapshot))
        self.assertIn("actionability-gate", payload["run_inventory"]["requested_stages"])
        gate_stage = next(item for item in payload["stages"]
                          if item["stage"] == "actionability-gate")
        self.assertEqual(gate_stage["status"], "complete")
        self.assertEqual(Path(gate_stage["artifacts"][0]).read_text(encoding="utf-8"),
                         json.dumps(gate_payload, ensure_ascii=False, indent=2))
        readiness = payload["readiness"]
        self.assertEqual(readiness["status"], "ready_for_human_review")
        self.assertEqual(readiness["detail_status"],
                         "machine_prerequisites_verified_human_gates_pending")
        self.assertEqual(readiness["human_gates"], ["账户规则与成本模型已由一手来源核验"])
        self.assertTrue(all(row["verified"] is True
                            for row in readiness["machine_prerequisites"]))
        self.assertEqual(readiness["blockers"], [])
        disk = json.loads((self.task_dir / "out" / "readiness_rollup.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(disk, readiness)
        self.assertEqual(json.loads((self.task_dir / "out" / "daily_run_summary.json")
                                    .read_text(encoding="utf-8")), payload)

    def test_a_closed_market_verdict_is_insufficient_evidence_not_failure(self):
        capture: dict = {}
        gate_payload = {"status": "market_closed",
                        "detail_status": "verified_exchange_calendar_closed",
                        "actionability": "not_actionable"}
        with mock.patch.object(pia_daily, "run_quotes", side_effect=self.fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module(gate_payload, 2, capture)):
            code, payload = self.run_pipeline("--actionability-assessment", str(self.snapshot))
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "insufficient_evidence")
        self.assertEqual(payload["detail_status"], "actionability_gate_market_closed")
        self.assertEqual(payload["readiness"]["status"], "not_ready")

    def test_the_real_gate_rejects_a_snapshot_it_cannot_verify(self):
        with mock.patch.object(pia_daily, "run_quotes", side_effect=self.fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self._gate_passthrough()):
            code, payload = self.run_pipeline("--actionability-assessment", str(self.snapshot))
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["detail_status"], "actionability_gate_invalid_input")
        written = json.loads((self.task_dir / "out" / "actionability_assessment.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "invalid_input")
        self.assertEqual(payload["readiness"]["status"], "not_ready")
        self.assertIn("actionability gate", " ".join(payload["readiness"]["blockers"]))

    def test_plan_only_names_the_gate_stage_without_running_it(self):
        code, payload = self.run_pipeline("--actionability-assessment", str(self.snapshot),
                                          "--plan-only")
        self.assertEqual(code, 0)
        self.assertIn("actionability-gate", payload["plan"])
        self.assertFalse((self.task_dir / "out" / "actionability_assessment.json").exists())

    def test_stable_router_forwards_the_gate_snapshot(self):
        captured: dict = {}

        def fake_child(**kwargs):
            captured["arguments"] = list(kwargs["child_arguments"])
            return {"status": "complete", "detail_status": "daily_run_complete"}, 0

        with mock.patch.object(pia, "_run_child", side_effect=fake_child):
            pia._dispatch(pia._build_parser().parse_args(
                ["daily-run", "--positions-file", "positions.json", "--task-dir", "task",
                 "--actionability-assessment", "terms.json"]))
        index = captured["arguments"].index("--actionability-assessment")
        self.assertEqual(Path(captured["arguments"][index + 1]).name, "terms.json")


class ArtifactReuseAndLedgerTests(unittest.TestCase):
    """Continuity: reusing a run's own artifacts must be explicit, and recorded."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task_dir = self.root / "task"

    def tearDown(self):
        self._tmp.cleanup()

    def seed_derived_snapshot(self) -> dict:
        snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(self.positions.read_bytes())
        return json.loads(snapshot.read_text(encoding="utf-8"))

    def seed_quotes(self, positions: dict, *, coverage: bool = True,
                    binding: dict | None = None) -> None:
        quotes = self.task_dir / "out" / "quotes.json"
        quotes.parent.mkdir(parents=True, exist_ok=True)
        quotes.write_text(json.dumps({
            "records": [{"symbol": "600000.SS"}],
            "portfolio_batch_audit": {
                "coverage_complete": coverage,
                "portfolio_snapshot_binding": (
                    binding if binding is not None
                    else quote_evidence_contract.build_portfolio_snapshot_binding(positions)),
            },
        }), encoding="utf-8")

    def fake_module(self, capture: dict):
        real = pia_daily.run_module

        def fake(main, argv):
            if getattr(main, "__module__", "") == "pia_trigger_ledger":
                # The ledger must actually run: a stubbed append would prove nothing
                # about whether this run reaches the append-only ledger.
                return real(main, argv)
            if "--task-dir" in argv:
                capture["refresh_calls"] = capture.get("refresh_calls", 0) + 1
                snapshot = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(self.positions.read_bytes())
                return 0, {"status": "complete", "detail_status": "fx_snapshot_written"}
            if "--decision-scope" in argv:
                return 0, {"status": "complete", "detail_status": "daily_sync_complete",
                           "completeness": {"complete": True}}
            return 0, {"status": "complete", "detail_status": "current_weights_computed",
                       "current_weights": [{"symbol": "600000.SS", "current_weight": 1.0,
                                            "current_price": 10.0}]}
        return fake

    def run_pipeline(self, *extra: str) -> tuple[int, dict]:
        argv = ["--positions-file", str(self.positions), "--task-dir", str(self.task_dir),
                "--skip-watchlist", *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_daily.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_reused_artifacts_skip_fetching_and_say_so(self):
        positions = self.seed_derived_snapshot()
        self.seed_quotes(positions)
        capture: dict = {}
        fetch = mock.Mock(side_effect=AssertionError("reuse must not refetch"))
        with mock.patch.object(pia_daily, "run_quotes", fetch), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module(capture)):
            code, payload = self.run_pipeline("--reuse-artifacts")
        self.assertEqual(code, 0)
        fetch.assert_not_called()
        self.assertNotIn("refresh_calls", capture)
        self.assertEqual([row["stage"] for row in payload["reused_artifacts"]],
                         ["refresh", "quotes"])
        stages = {stage["stage"]: stage for stage in payload["stages"]}
        self.assertIs(stages["refresh"]["reused"], True)
        self.assertEqual(stages["refresh"]["detail_status"], "reused_derived_snapshot")
        self.assertIs(stages["quotes"]["reused"], True)
        self.assertIs(stages["quotes"]["reuse_checks"]["snapshot_binding_matches"], True)
        self.assertEqual(payload["status"], "complete")

    def test_an_unverifiable_batch_is_refused_instead_of_reused(self):
        positions = self.seed_derived_snapshot()
        self.seed_quotes(positions, binding={"schema_version": "pia_portfolio_snapshot_v1",
                                             "active_positions": []})
        fetch = mock.Mock(side_effect=AssertionError("a refused reuse must not fetch either"))
        with mock.patch.object(pia_daily, "run_quotes", fetch), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module({})):
            code, payload = self.run_pipeline("--reuse-artifacts")
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "reuse_artifacts_unusable")
        fetch.assert_not_called()
        self.assertEqual([stage["stage"] for stage in payload["stages"]],
                         ["refresh", "quotes"])
        self.assertEqual(payload["stages"][-1]["detail_status"], "reuse_artifacts_unusable")
        self.assertIn("snapshot_binding_matches", str(payload["stages"][-1]["errors"]))

    def test_a_missing_batch_is_refused_rather_than_silently_refetched(self):
        self.seed_derived_snapshot()
        with mock.patch.object(pia_daily, "run_module",
                               side_effect=self.fake_module({})):
            code, payload = self.run_pipeline("--reuse-artifacts")
        self.assertEqual(code, 3)
        self.assertIn("quotes_file_missing", str(payload["stages"][-1]["errors"]))

    def test_without_the_flag_the_pipeline_still_fetches(self):
        self.seed_derived_snapshot()
        positions = json.loads(self.positions.read_text(encoding="utf-8"))
        calls: list[str] = []

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            calls.append("quotes")
            self.seed_quotes(positions)
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, \
                task_dir / "out" / "quotes.json"

        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module({})):
            code, payload = self.run_pipeline()
        self.assertEqual(calls, ["quotes"])
        self.assertNotIn("reused_artifacts", payload)

    def test_a_repeat_run_names_the_run_it_replaced(self):
        positions = json.loads(self.positions.read_text(encoding="utf-8"))

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            self.seed_quotes(positions, coverage=False)
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, \
                task_dir / "out" / "quotes.json"

        summary_path = self.task_dir / "out" / "daily_run_summary.json"
        history = self.task_dir / "out" / pia_daily.REPLAY_HISTORY_FILENAME
        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module({})):
            first_code, first = self.run_pipeline()
            self.assertEqual(first_code, 0)
            # A first run replaces nothing and must not claim otherwise.
            self.assertNotIn("previous_run", first)
            self.assertFalse(history.exists())
            first_sha = hashlib.sha256(summary_path.read_bytes()).hexdigest()
            second_code, second = self.run_pipeline()
        self.assertEqual(second_code, 0)
        self.assertEqual(second["previous_run"]["summary_sha256"], first_sha)
        self.assertEqual(second["previous_run"]["status"], first["status"])
        lines = [json.loads(line) for line in
                 history.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["overwrote_summary_sha256"], first_sha)
        self.assertEqual(lines[0]["overwrote_status"], first["status"])
        # A later repeat chains to the run it replaced, so the sequence stays readable.
        second_sha = hashlib.sha256(summary_path.read_bytes()).hexdigest()
        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module({})):
            _third_code, third = self.run_pipeline()
        self.assertEqual(third["previous_run"]["summary_sha256"], second_sha)
        lines = [json.loads(line) for line in
                 history.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual([line["overwrote_summary_sha256"] for line in lines],
                         [first_sha, second_sha])

    def test_an_aborted_repeat_is_recorded_too(self):
        self.seed_derived_snapshot()
        summary_path = self.task_dir / "out" / "daily_run_summary.json"
        prior = {"schema_version": "pia_daily_run_v1", "status": "complete",
                 "detail_status": "daily_run_complete", "generated_at": "2026-09-29T12:00:00+00:00"}
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(prior), encoding="utf-8")
        prior_sha = hashlib.sha256(summary_path.read_bytes()).hexdigest()
        # No usable quote batch: the run must refuse, yet still say what it replaced.
        with mock.patch.object(pia_daily, "run_module", side_effect=self.fake_module({})):
            code, payload = self.run_pipeline("--reuse-artifacts")
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "reuse_artifacts_unusable")
        self.assertEqual(payload["previous_run"]["summary_sha256"], prior_sha)
        history = self.task_dir / "out" / pia_daily.REPLAY_HISTORY_FILENAME
        lines = [json.loads(line) for line in
                 history.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["overwrote_summary_sha256"], prior_sha)

    def test_recording_appends_this_run_to_the_ledger_once(self):
        self.seed_derived_snapshot()
        positions = json.loads(self.positions.read_text(encoding="utf-8"))

        def fake_quotes(positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
            self.seed_quotes(positions, coverage=False)
            return 0, {"status": "complete", "detail_status": "quote_batch_captured"}, \
                task_dir / "out" / "quotes.json"

        (self.root / "ledger").mkdir(parents=True, exist_ok=True)
        ledger = self.root / "ledger" / pia_trigger_ledger.DEFAULT_LEDGER_NAME
        with mock.patch.object(pia_daily, "run_quotes", side_effect=fake_quotes), \
                mock.patch.object(pia_daily, "run_module",
                                  side_effect=self.fake_module({})):
            code, payload = self.run_pipeline("--record", "--ledger", str(ledger))
        self.assertEqual(code, 0)
        self.assertIs(payload["ledger"]["appended"], True)
        self.assertEqual(payload["ledger"]["status"], "complete")
        entries = [json.loads(line) for line in
                   ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["run_id"], self.task_dir.name)
        self.assertIn("600000.SS", entries[0]["weights"])
        # Re-appending the same run (same summary, same entry id) is refused, so a
        # repeated invocation cannot inflate the ledger.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            again = pia_trigger_ledger.main(["append", "--run-dir", str(self.task_dir),
                                             "--ledger", str(ledger)])
        self.assertEqual(again, 0)
        self.assertIs(json.loads(buffer.getvalue())["appended"], False)
        self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

    def test_stable_router_forwards_reuse_record_and_ledger(self):
        captured: dict = {}

        def fake_child(**kwargs):
            captured["arguments"] = list(kwargs["child_arguments"])
            return {"status": "complete", "detail_status": "daily_run_complete"}, 0

        with mock.patch.object(pia, "_run_child", side_effect=fake_child):
            pia._dispatch(pia._build_parser().parse_args(
                ["daily-run", "--positions-file", "positions.json", "--task-dir", "task",
                 "--reuse-artifacts", "--record", "--ledger", "ledger.jsonl"]))
        arguments = captured["arguments"]
        self.assertIn("--reuse-artifacts", arguments)
        self.assertIn("--record", arguments)
        self.assertEqual(Path(arguments[arguments.index("--ledger") + 1]).name,
                         "ledger.jsonl")


if __name__ == "__main__":
    unittest.main()
