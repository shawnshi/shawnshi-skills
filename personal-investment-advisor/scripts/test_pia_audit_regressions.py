"""PIA audit regressions using synthetic inputs and no provider requests."""

import contextlib
import io
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

import pia
import pia_daily
import pia_etf_packet
import pia_refresh
import pia_report
import position_limits
import quote_fallback as qf
import unpurchased_analysis
from test_p2_daily_run_pipeline import positions_payload
from test_p2_quote_fallback import cn_payload


class DailyStatusRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task = self.root / "task"
        self.dashboard_root = self.root / "dashboards"
        self.boundary = (2, {"status": "invalid_input", "detail_status": "runtime_quote_invalid",
                             "errors": ["synthetic quote mismatch"], "categories": {}})
        self.catalog = {"complete": True, "errors": [], "entries": [
            {"symbol": "600000.SS", "json_path": str(self.dashboard_root / "synthetic.json")}]}
        self.probe = (3, {"status": "failed", "detail_status": "packet_input_invalid",
                          "errors": ["synthetic probe failure"]})
        self.ledger = (3, {"status": "failed", "detail_status": "ledger_append_failed",
                           "errors": ["synthetic ledger failure"]})

    def fake_quotes(self, positions_file, cache_dir, symbols, task_dir, holiday_calendar=None):
        target = task_dir / "out" / "quotes.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        return 0, {"status": "complete", "detail_status": "synthetic_quotes"}, target

    def fake_module(self, main, argv):
        module = getattr(main, "__module__", "")
        if module == "dashboard_catalog":
            return (0 if self.catalog["complete"] else 1), self.catalog
        if module == "watchlist_gate":
            return self.boundary
        if module == "pia_trigger_ledger":
            return self.ledger
        if argv[:1] == ["coverage-probe"]:
            return self.probe
        if module == "cn_actionability_gate":
            return 0, {"status": "complete", "decision_scope": "advisory"}
        if "--task-dir" in argv:
            target = self.task / "inputs" / pia_refresh.DERIVED_FILENAME
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.positions.read_bytes())
            return 0, {"status": "complete", "detail_status": "synthetic_refresh"}
        if "--decision-scope" in argv:
            return 0, {"status": "complete", "decision_scope": "advisory",
                       "completeness": {"complete": True}}
        return 0, {"status": "complete", "decision_scope": "advisory", "current_weights": [
            {"symbol": "600000.SS", "current_price": 10.0, "currency": "CNY", "quote": {}}]}

    def run_pipeline(self, *extra, watchlist=False, authorized_dashboards=True):
        argv = ["--positions-file", str(self.positions), "--task-dir", str(self.task)]
        if authorized_dashboards:
            argv.extend(["--dashboard-root", str(self.dashboard_root)])
        if not watchlist:
            argv.append("--skip-watchlist")
        output = io.StringIO()
        with mock.patch.object(pia_daily, "run_quotes", side_effect=self.fake_quotes), \
                mock.patch.object(pia_daily, "run_module", side_effect=self.fake_module), \
                contextlib.redirect_stdout(output):
            code = pia_daily.main([*argv, *extra])
        payload = json.loads(output.getvalue())
        disk = json.loads((self.task / "out" / "daily_run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(disk, payload)
        return code, payload

    def stage(self, payload, name):
        return next(row for row in payload["stages"] if row["stage"] == name)

    def coverage_file(self):
        target = self.root / "coverage.json"
        target.write_text(json.dumps({"probes": [{
            "channel": "cninfo", "target": "600000.SS", "control": "600001.SS",
            "target_class": "stock", "control_class": "stock",
            "channel_scope": "public", "window_days": 7}]}), encoding="utf-8")
        return target

    def test_invalid_boundary_fails_the_stage_and_run(self):
        code, payload = self.run_pipeline(watchlist=True)
        self.assertEqual((code, payload["status"]), (3, "failed"))
        stage = self.stage(payload, "watchlist")
        self.assertEqual(stage["status"], "failed")
        child = next(row for row in stage["stages"] if row["stage"] == "600000.SS")
        self.assertEqual(child["exit_code"], 2)
        self.assertIn("synthetic quote mismatch", child["errors"])
        self.assertEqual(stage["crossed_boundaries"], [])

    def test_missing_dashboard_path_is_incomplete_not_a_crash(self):
        self.catalog = {"complete": False, "errors": [], "entries": [
            {"symbol": "600000.SS", "reason": "dashboard_not_indexed"}]}
        code, payload = self.run_pipeline(watchlist=True)
        self.assertEqual((code, payload["status"]), (2, "insufficient_evidence"))
        child = self.stage(payload, "watchlist")["stages"][-1]
        self.assertEqual(child["detail_status"], "dashboard_not_indexed")

    def test_verified_crossing_remains_a_successful_evaluation(self):
        self.boundary = (0, {"status": "ok", "categories": {
            "downside_boundary_crossed": ["synthetic_limit"]}, "errors": []})
        code, payload = self.run_pipeline(watchlist=True)
        self.assertEqual((code, payload["status"]), (0, "complete"))
        self.assertEqual(self.stage(payload, "watchlist")["crossed_boundaries"], ["synthetic_limit"])

    def test_failed_probe_is_not_a_complete_inconclusive_probe(self):
        code, payload = self.run_pipeline("--coverage-probe-file", str(self.coverage_file()))
        self.assertEqual((code, payload["status"]), (3, "failed"))
        stage = self.stage(payload, "coverage-probe")
        self.assertEqual(stage["detail_status"], "coverage_probe_failed")
        self.assertEqual(stage["probes"][0]["exit_code"], 3)
        self.assertIn("synthetic probe failure", stage["errors"][0])

    def test_legitimate_unproven_coverage_does_not_fail_probe_execution(self):
        self.probe = (2, {"status": "insufficient_data", "detail_status": "coverage_unproven",
                          "target_count": 0, "control_count": 0, "errors": []})
        code, payload = self.run_pipeline("--coverage-probe-file", str(self.coverage_file()))
        self.assertEqual((code, payload["status"]), (0, "complete"))
        self.assertTrue(self.stage(payload, "coverage-probe")["unproven_probes"])

    def test_both_verified_coverage_verdicts_are_accepted(self):
        for verdict in ("covered_zero_events", "covered_with_events"):
            with self.subTest(verdict=verdict):
                self.probe = (0, {"status": "complete", "detail_status": verdict, "errors": []})
                code, payload = self.run_pipeline("--coverage-probe-file", str(self.coverage_file()))
                self.assertEqual((code, payload["status"]), (0, "complete"))

    def test_crash_exit_overrides_an_apparently_valid_probe_verdict(self):
        self.probe = (3, {"status": "complete", "detail_status": "covered_zero_events"})
        code, payload = self.run_pipeline("--coverage-probe-file", str(self.coverage_file()))
        self.assertEqual((code, payload["status"]), (3, "failed"))

    def test_explicit_ledger_failure_is_part_of_final_status(self):
        code, payload = self.run_pipeline("--record", "--ledger", str(self.root / "synthetic.jsonl"))
        self.assertEqual((code, payload["status"]), (3, "failed"))
        self.assertIn("ledger", payload["run_inventory"]["requested_stages"])
        self.assertEqual(self.stage(payload, "ledger")["errors"], ["synthetic ledger failure"])
        self.assertFalse(payload["ledger"]["appended"])

    def test_successful_ledger_append_still_completes(self):
        self.ledger = (0, {"status": "complete", "appended": True})
        code, payload = self.run_pipeline("--record")
        self.assertEqual((code, payload["status"]), (0, "complete"))
        self.assertTrue(payload["status_consistency"]["consistent"])

    def test_readiness_scope_conflict_fails_final_status(self):
        terms = self.root / "terms.json"
        terms.write_text("{}", encoding="utf-8")
        rollup = {"status": "ready_for_human_review", "scope_conflicts": ["synthetic scope conflict"]}
        with mock.patch.object(pia_daily.pia_readiness, "build_rollup", return_value=rollup):
            code, payload = self.run_pipeline("--actionability-assessment", str(terms))
        self.assertEqual((code, payload["status"]), (3, "failed"))
        self.assertEqual(self.stage(payload, "readiness")["status"], "failed")

    def test_ledger_failure_refreshes_readiness_from_final_run(self):
        terms = self.root / "terms.json"
        terms.write_text("{}", encoding="utf-8")

        def evaluate(run_dir, artifacts, assessment):
            status = artifacts["daily_run_summary"]["status"]
            return {"status": "ready_for_human_review" if status == "complete" else "not_ready",
                    "run_status": status, "scope_conflicts": []}

        with mock.patch.object(pia_daily.pia_readiness, "build_rollup", side_effect=evaluate) as build:
            code, payload = self.run_pipeline("--actionability-assessment", str(terms), "--record")
        self.assertEqual((code, payload["status"]), (3, "failed"))
        self.assertEqual(build.call_count, 2)
        self.assertEqual(payload["readiness"]["status"], "not_ready")
        self.assertEqual(payload["readiness"]["run_status"], "failed")
        self.assertEqual(json.loads((self.task / "out" / "readiness_rollup.json").read_text(encoding="utf-8")),
                         payload["readiness"])

    def test_a_valid_not_ready_verdict_is_not_an_execution_failure(self):
        terms = self.root / "terms.json"
        terms.write_text("{}", encoding="utf-8")
        rollup = {"status": "not_ready", "scope_conflicts": [], "blockers": ["synthetic unmet prerequisite"]}
        with mock.patch.object(pia_daily.pia_readiness, "build_rollup", return_value=rollup):
            code, payload = self.run_pipeline("--actionability-assessment", str(terms))
        self.assertEqual((code, payload["status"]), (0, "complete"))
        self.assertEqual(payload["readiness"]["status"], "not_ready")

    def write_mixed_positions(self):
        positions = positions_payload()
        unpurchased = dict(positions["positions"][0])
        unpurchased.update(symbol="601899.SS", name="Synthetic unpurchased security", quantity=0)
        positions["positions"].append(unpurchased)
        self.positions.write_text(json.dumps(positions), encoding="utf-8")

    def test_all_scope_still_plans_unpurchased_research(self):
        self.write_mixed_positions()
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_daily.main(["--positions-file", str(self.positions), "--task-dir", str(self.task),
                                   "--plan-only", "--skip-watchlist"])
        payload = json.loads(captured.getvalue())
        self.assertEqual(code, 0)
        self.assertIn("unpurchased_analysis", payload["plan"])
        self.assertEqual(payload["analysis_selection"], "all")
        self.assertEqual(payload["analysis_scope"]["analysis_non_cash_count"], 2)

    def test_held_only_plan_declares_excluded_unpurchased_security(self):
        self.write_mixed_positions()
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_daily.main(["--positions-file", str(self.positions), "--task-dir", str(self.task),
                                   "--analysis-scope", "held_only", "--plan-only", "--skip-watchlist"])
        payload = json.loads(captured.getvalue())
        self.assertEqual(code, 0)
        self.assertNotIn("unpurchased_analysis", payload["plan"])
        self.assertEqual(payload["analysis_scope"]["excluded_unpurchased_symbols"], ["601899.SS"])
        self.assertEqual(payload["analysis_scope"]["analysis_non_cash_count"], 1)

    def test_held_only_execution_never_collects_unpurchased_quotes(self):
        self.write_mixed_positions()
        with mock.patch.object(unpurchased_analysis, "run") as research:
            code, payload = self.run_pipeline("--analysis-scope", "held_only")
        research.assert_not_called()
        self.assertEqual((code, payload["status"]), (0, "complete"))
        self.assertEqual(payload["analysis_selection"], "held_only")
        self.assertEqual(payload["analysis_scope"]["excluded_unpurchased_symbols"], ["601899.SS"])
        skipped = payload["run_inventory"]["stages_not_run"]
        self.assertTrue(any(row["stage"] == "unpurchased_analysis"
                            and "held_only" in row["reason"] for row in skipped))
        self.assertFalse((self.task / "out" / "unpurchased_quotes.json").exists())

    def test_aborted_held_only_run_keeps_scope_and_exclusions(self):
        self.write_mixed_positions()
        self.fake_quotes = lambda *args, **kwargs: (
            3, {"status": "failed", "detail_status": "synthetic_quote_failure",
                "errors": ["synthetic provider failure"]}, self.task / "out" / "quotes.json")
        code, payload = self.run_pipeline("--analysis-scope", "held_only")
        self.assertEqual((code, payload["status"]), (3, "failed"))
        self.assertEqual(payload["analysis_selection"], "held_only")
        self.assertEqual(payload["analysis_scope"]["excluded_unpurchased_symbols"], ["601899.SS"])
        self.assertTrue(any(row["stage"] == "unpurchased_analysis" and "held_only" in row["reason"]
                            for row in payload["run_inventory"]["stages_not_run"]))

    def test_held_only_empty_universe_stops_before_provider_calls(self):
        positions = positions_payload()
        positions["positions"][0]["quantity"] = 0
        self.positions.write_text(json.dumps(positions), encoding="utf-8")
        with mock.patch.object(pia_daily, "run_quotes") as quotes, \
                contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_daily.main(["--positions-file", str(self.positions), "--task-dir", str(self.task),
                                   "--analysis-scope", "held_only", "--skip-watchlist"])
        quotes.assert_not_called()
        payload = json.loads(captured.getvalue())
        self.assertEqual((code, payload["status"]), (2, "insufficient_evidence"))
        self.assertEqual(payload["detail_status"], "no_held_non_cash_securities")
        self.assertTrue(payload["status_consistency"]["consistent"])

    def test_held_only_report_names_exclusions_without_reading_old_research(self):
        self.write_mixed_positions()
        _, payload = self.run_pipeline("--analysis-scope", "held_only")
        stale = self.task / "out" / "unpurchased_analysis.json"
        stale.write_text("SYNTHETIC STALE FILE MUST NOT BE READ", encoding="utf-8")
        target = self.root / "report.md"
        original_read = Path.read_text

        def guarded_read(path, *args, **kwargs):
            if path == stale:
                self.fail("held_only report read stale unpurchased evidence")
            return original_read(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", autospec=True, side_effect=guarded_read), \
                contextlib.redirect_stdout(io.StringIO()):
            code = pia_report.main(["--run-dir", str(self.task), "--out", str(target)])
        self.assertEqual(code, 0)
        report = target.read_text(encoding="utf-8")
        self.assertIn("held_only", report)
        self.assertIn("范围外未购标的：601899.SS", report)
        self.assertNotIn("SYNTHETIC STALE FILE", report)

    def test_report_rejects_held_only_summary_with_unpurchased_stage(self):
        _, payload = self.run_pipeline("--analysis-scope", "held_only")
        payload["stages"].append({"stage": "unpurchased_analysis", "status": "complete"})
        (self.task / "out" / "daily_run_summary.json").write_text(json.dumps(payload), encoding="utf-8")
        target = self.root / "invalid-report.md"
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_report.main(["--run-dir", str(self.task), "--out", str(target)])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(captured.getvalue())["detail_status"], "analysis_scope_conflict")
        self.assertFalse(target.exists())

    def test_public_router_forwards_scope_and_explicit_policy(self):
        with mock.patch.object(pia, "_run_child", return_value=({"status": "complete"}, 0)) as child:
            pia._dispatch(pia._build_parser().parse_args([
                "daily-run", "--positions-file", str(self.positions), "--task-dir", str(self.task),
                "--analysis-scope", "held_only", "--risk-bounds-policy", str(self.root / "policy.json")]))
        arguments = child.call_args.kwargs["child_arguments"]
        self.assertEqual(arguments[arguments.index("--analysis-scope") + 1], "held_only")
        self.assertEqual(Path(arguments[arguments.index("--risk-bounds-policy") + 1]), self.root / "policy.json")

    def test_positions_authorization_does_not_infer_dashboard_root(self):
        with mock.patch.object(position_limits, "load_policy") as load_policy:
            code, payload = self.run_pipeline(watchlist=True, authorized_dashboards=False)
        self.assertEqual((code, payload["status"]), (2, "insufficient_evidence"))
        self.assertEqual(self.stage(payload, "watchlist")["detail_status"], "dashboard_root_not_authorized")
        load_policy.assert_not_called()
        self.assertFalse((self.task / "out" / "dashboard_catalog.json").exists())

    def test_dashboard_root_does_not_authorize_sibling_or_environment_policy(self):
        self.dashboard_root.mkdir()
        policy = self.dashboard_root / "risk_bounds_policy.json"
        policy.write_text('{"synthetic": "not authorized"}', encoding="utf-8")
        self.boundary = (0, {"status": "ok", "categories": {}, "errors": []})
        with mock.patch.dict(os.environ, {"PIA_RISK_BOUNDS_POLICY": str(policy)}), \
                mock.patch.object(position_limits, "load_policy") as load_policy:
            code, payload = self.run_pipeline(watchlist=True)
        self.assertEqual((code, payload["status"]), (0, "complete"))
        load_policy.assert_not_called()
        self.assertEqual(self.stage(payload, "watchlist")["derived_limits"]["status"], "not_supplied")

    def test_explicit_authorized_policy_is_loaded(self):
        policy = self.root / "explicit-policy.json"
        policy.write_text("{}", encoding="utf-8")
        self.boundary = (0, {"status": "ok", "categories": {}, "errors": []})
        derived = {"generated_from": {"policy_sha256": "a" * 64}, "rules": [], "positions": []}
        with mock.patch.object(position_limits, "load_policy", return_value={}) as load_policy, \
                mock.patch.object(position_limits, "build", return_value=derived):
            code, payload = self.run_pipeline("--risk-bounds-policy", str(policy), watchlist=True)
        self.assertEqual((code, payload["status"]), (0, "complete"))
        load_policy.assert_called_once_with(policy)
        self.assertEqual(self.stage(payload, "watchlist")["derived_limits"]["status"], "applied")

    def test_explicit_missing_policy_cannot_pass(self):
        self.boundary = (0, {"status": "ok", "categories": {}, "errors": []})
        code, payload = self.run_pipeline("--risk-bounds-policy", str(self.root / "missing.json"), watchlist=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.stage(payload, "watchlist")["derived_limits"]["status"], "invalid")

    def test_unpurchased_evaluation_without_root_does_not_resolve_dashboards(self):
        positions = positions_payload()
        positions["positions"][0]["quantity"] = 0
        self.positions.write_text(json.dumps(positions), encoding="utf-8")
        positions = pia_daily.load_positions(str(self.positions))
        with mock.patch.object(unpurchased_analysis.dashboard_catalog, "resolve_dashboards") as resolve:
            result = unpurchased_analysis.evaluate(
                positions, {"records": []}, evaluation_epoch=1_790_000_000, dashboard_root=None)
        resolve.assert_not_called()
        self.assertEqual(result["rows"][0]["dashboard_status"], "not_authorized")


class CoverageTransportRegressions(unittest.TestCase):
    def run_probe(self, fetcher):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with mock.patch.object(pia_etf_packet, "_fetch_cninfo", side_effect=fetcher), \
                    contextlib.redirect_stdout(output):
                code = pia_etf_packet.main([
                    "coverage-probe", "--channel", "cninfo", "--target", "600000.SS",
                    "--control", "600001.SS", "--target-class", "stock",
                    "--control-class", "stock", "--channel-scope", "public",
                    "--as-of-date", "2026-10-09", "--task-dir", directory])
            return code, json.loads(output.getvalue())

    def test_transport_failure_retains_error_not_no_data(self):
        def unavailable(*args):
            raise ConnectionError("synthetic transport unavailable")
        code, payload = self.run_probe(unavailable)
        self.assertEqual((code, payload["status"]), (3, "failed"))
        self.assertEqual(payload["detail_status"], "channel_probe_failed")
        self.assertIn("synthetic transport unavailable", payload["errors"][0])

    def test_empty_shell_remains_inconclusive_not_transport_failure(self):
        code, payload = self.run_probe(lambda *args: (b"{}", 0, {"empty_shell": True, "attempts": 1}))
        self.assertEqual((code, payload["status"]), (2, "insufficient_data"))
        self.assertEqual(payload["detail_status"], "channel_unavailable")
        self.assertEqual(payload["errors"], [])

    def test_unparseable_rows_are_a_failed_probe(self):
        code, payload = self.run_probe(lambda *args: (b"{}", 0, {"rows_parsed": False}))
        self.assertEqual((code, payload["status"]), (3, "failed"))
        self.assertIn("not parseable", payload["errors"][0])


class FallbackCacheRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = 1000.0
        self.transport = mock.Mock(return_value=(200, cn_payload()))
        self.fetcher = qf.FallbackFetcher(
            http_get=self.transport, cache_dir=Path(self.tmp.name), now=lambda: self.clock)
        self.url = qf.source_url("601899.SS")

    def write_cache(self, **overrides):
        payload = {"url": self.url, "status_code": 200, "text": cn_payload(), "stored_epoch": 1000.0}
        payload.update(overrides)
        self.fetcher._cache_path(self.url).write_text(json.dumps(payload), encoding="utf-8")

    def test_future_and_nonfinite_cache_epochs_are_rejected(self):
        for value in (1001.0, float("nan"), float("inf"), -float("inf")):
            with self.subTest(epoch=value):
                self.write_cache(stored_epoch=value)
                result = self.fetcher.fetch("601899.SS", market="CN")
                self.assertEqual(result["fetched_via"], "network")
        self.assertEqual(self.transport.call_count, 4)

    def test_cache_hit_retains_original_retrieval_time(self):
        first = self.fetcher.fetch("601899.SS", market="CN")
        self.clock = 1100.0
        second = self.fetcher.fetch("601899.SS", market="CN")
        self.assertEqual(second["fetched_via"], "cache")
        self.assertEqual(first["record"]["retrieved_at"], second["record"]["retrieved_at"])
        self.assertNotEqual(second["record"]["cache_read_at"], second["record"]["retrieved_at"])
        self.transport.assert_called_once()

    def test_expired_cache_makes_a_new_capture(self):
        first = self.fetcher.fetch("601899.SS", market="CN")
        self.clock = 1121.0
        second = self.fetcher.fetch("601899.SS", market="CN")
        self.assertEqual(second["fetched_via"], "network")
        self.assertNotEqual(first["record"]["retrieved_at"], second["record"]["retrieved_at"])

    def test_wrong_url_or_malformed_cache_is_not_reused(self):
        for override in ({"url": "https://example.invalid/wrong"}, {"text": 42}, {"status_code": True}):
            with self.subTest(override=override):
                self.write_cache(**override)
                self.assertEqual(self.fetcher.fetch("601899.SS")["fetched_via"], "network")

    def test_configured_timeout_reaches_requests_transport(self):
        response = SimpleNamespace(status_code=200, text=cn_payload(), encoding=None)
        with mock.patch("requests.get", return_value=response) as get:
            result = qf.FallbackFetcher(timeout_seconds=0.1).fetch("601899.SS")
        self.assertEqual(result["health"], "ok")
        self.assertEqual(get.call_args.kwargs["timeout"], 0.1)
        self.assertEqual(response.encoding, "gbk")

    def test_invalid_timeout_and_ttl_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                qf.FallbackFetcher(timeout_seconds=value)
        for value in (-1, float("nan"), float("inf")):
            with self.subTest(ttl=value), self.assertRaises(ValueError):
                qf.FallbackFetcher(ttl_seconds=value)


if __name__ == "__main__":
    unittest.main()
