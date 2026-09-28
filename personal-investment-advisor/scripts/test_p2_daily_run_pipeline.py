"""Contract tests for the pinned-epoch Daily Sync orchestrator (``pia_daily.py``).

The orchestrator must (a) pin one evaluation epoch, (b) never run a dependent
stage from an incomplete upstream stage, and (c) surface the upstream reason
instead of reporting a silent success.
"""
from __future__ import annotations

import contextlib
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

import pia_daily  # noqa: E402
import pia_refresh  # noqa: E402
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
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "insufficient_evidence")
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
        self.assertIn(code, (0, 2))
        summary = json.loads((self.task_dir / "out" / "daily_run_summary.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual([stage["stage"] for stage in summary["stages"]],
                         ["refresh", "quotes", "daily_sync", "weights"])
        self.assertEqual(summary["positions_input_sha256"],
                         pia_daily.sha256_file(self.positions))


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
        self.assertEqual(code, 2)
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


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(code, 0)
        stage = next(item for item in payload["stages"] if item["stage"] == "coverage-probe")
        # the stage completes (it produced a verdict); the verdict itself is data
        self.assertEqual(stage["status"], "complete")
        self.assertEqual(stage["detail_status"], "coverage_partially_unproven")
        self.assertEqual(stage["errors"], [])
        self.assertEqual(stage["probes"][0]["verdict"], "coverage_unproven")
        self.assertTrue(stage["unproven_probes"])
        self.assertTrue(Path(stage["artifacts"][0]).is_file())


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(run["status"], "complete")
        self.assertEqual(code, 0)
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
        self.assertEqual(code, 2)
        stage = next(item for item in run["stages"] if item["stage"] == "risk-diagnostic")
        self.assertEqual(stage["status"], "insufficient_data")
        self.assertEqual(stage["artifacts"], [])
        self.assertIn("history file not found", stage["errors"][0])


if __name__ == "__main__":
    unittest.main()
