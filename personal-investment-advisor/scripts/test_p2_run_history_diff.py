"""Contract tests for the cross-run registry and delta (P1-1).

The diff must be read-only by default and must report a missing artifact as an
explicit gap instead of silently reporting "no change".
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_history  # noqa: E402


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_run(self, run_id: str, *, epoch: float, status: str = "complete",
                 weights=None, watchlist=None, with_weights=True,
                 stages=None) -> Path:
        run_dir = self.root / run_id
        summary = {"status": status, "detail_status": "daily_run_complete",
                   "evaluation_epoch": epoch, "generated_at": f"2026-09-27T0{int(epoch) % 10}:00:00+00:00",
                   "positions_input_sha256": "f" * 64,
                   "stages": stages or [{"stage": "weights", "status": "complete"},
                                        {"stage": "watchlist", "status": "complete"}]}
        write_json(run_dir / "out" / "daily_run_summary.json", summary)
        if with_weights:
            write_json(run_dir / "out" / "weights.json", {
                "status": "complete", "detail_status": "current_weights_computed",
                "evaluation_epoch": epoch,
                "current_weights": [
                    {"symbol": symbol, "current_weight": value,
                     "quote": {"as_of": "2026-09-24T07:00:00Z"}}
                    for symbol, value in (weights or {}).items()],
            })
        if watchlist is not None:
            write_json(run_dir / "out" / "watchlist_results.json", watchlist)
        return run_dir

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_history.main(argv)
        return code, json.loads(buffer.getvalue())


class IndexTests(HistoryTestCase):
    def test_runs_are_indexed_and_ordered_by_evaluation_epoch(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 0.5, "Y": 0.5})
        self.make_run("run-b", epoch=200.0, weights={"X": 0.6, "Y": 0.4})
        registry = json.loads(json.dumps(pia_history.index_runs(self.root)))
        self.assertEqual([run["run_id"] for run in registry["runs"]], ["run-a", "run-b"])
        self.assertEqual(registry["runs"][0]["order_basis"], "daily_run_summary.evaluation_epoch")
        self.assertEqual(registry["runs"][1]["weights"]["X"], 0.6)
        self.assertTrue(registry["runs"][0]["artifacts"]["weights"]["sha256"])

    def test_index_is_read_only_by_default(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        code, payload = self.run_cli(["index", "--task-root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertFalse((self.root / "pia_run_registry.json").exists())
        self.assertNotIn("registry_file", payload)

    def test_write_creates_the_registry_at_the_task_root(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        code, payload = self.run_cli(["index", "--task-root", str(self.root), "--write"])
        self.assertEqual(code, 0)
        written = self.root / "pia_run_registry.json"
        self.assertTrue(written.is_file())
        self.assertEqual(payload["registry_file"], str(written))

    def test_nested_runs_are_found_only_with_depth(self):
        nested = self.root / "optimization-task"
        (nested / "inner-run" / "out").mkdir(parents=True)
        write_json(nested / "inner-run" / "out" / "weights.json",
                   {"status": "complete", "evaluation_epoch": 100.0, "current_weights": []})
        flat = pia_history.index_runs(self.root)
        self.assertEqual(flat["run_count"], 0)
        deep = pia_history.index_runs(self.root, 2)
        self.assertEqual([run["run_id"] for run in deep["runs"]], ["inner-run"])
        self.assertEqual(deep["depth"], 2)

    def test_directory_mtime_is_used_as_a_last_resort_basis(self):
        run_dir = self.root / "run-mtime"
        write_json(run_dir / "out" / "weights.json",
                   {"status": "complete", "current_weights": []})
        registry = pia_history.index_runs(self.root)
        self.assertEqual(registry["runs"][0]["order_basis"], "directory_mtime")


class DiffTests(HistoryTestCase):
    def test_weight_and_boundary_deltas_are_computed(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 0.4, "Y": 0.6},
                      watchlist={"X": {"status": "ok",
                                       "categories": {"downside_boundary_crossed": ["X-down"]}},
                                 "Y": {"status": "ok", "categories": {}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 0.45, "Y": 0.55},
                      watchlist={"X": {"status": "insufficient_evidence", "categories": {}},
                                 "Y": {"status": "ok", "categories": {}}})
        code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(report["from_run"]["run_id"], "run-a")
        self.assertEqual(report["weight_delta_pp"]["X"]["delta_pp"], 5.0)
        self.assertEqual(report["weight_delta_pp"]["Y"]["delta_pp"], -5.0)
        self.assertEqual(report["boundary_crossed_cleared"], ["X-down"])
        # only a real status change is recorded; unchanged symbols stay out of the map
        self.assertEqual(report["boundary_transitions"]["X"],
                         {"from_status": "ok", "to_status": "insufficient_evidence"})
        self.assertNotIn("Y", report["boundary_transitions"])

    def test_status_transition_is_reported(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0}, status="complete")
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0}, status="insufficient_evidence")
        _code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(report["run_status_transition"],
                         {"from": "complete", "to": "insufficient_evidence"})

    def test_missing_weights_is_a_gap_not_a_no_change(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        self.make_run("run-b", epoch=200.0, with_weights=False)
        code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertTrue(any("weights section not comparable" in gap for gap in report["gaps"]))
        # An empty map would read as "no change"; a comparison that could not be made
        # must say so, so the whole section is null rather than empty.
        self.assertIsNone(report["weight_delta_pp"])
        self.assertIsNone(report["symbols_removed"])
        self.assertEqual(report["sections"]["weights"]["state"], "not_comparable")

    def test_missing_watchlist_does_not_report_a_cleared_boundary(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0},
                      watchlist={"X": {"status": "ok",
                                       "categories": {"downside_boundary_crossed": ["X-down"]}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0})
        code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIsNone(report["boundary_crossed_cleared"])
        self.assertIsNone(report["boundary_crossed_added"])
        self.assertIsNone(report["boundary_transitions"])
        self.assertTrue(any("boundaries section not comparable" in gap
                            for gap in report["gaps"]))
        self.assertEqual(report["sections"]["boundaries"]["state"], "not_comparable")

    def test_fewer_than_two_runs_is_explicit(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertEqual(report["detail_status"], "fewer_than_two_runs")

    def test_unknown_run_id_is_reported(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0})
        code, report = self.run_cli(["diff", "--task-root", str(self.root),
                                     "--from", "nope"])
        self.assertEqual(code, 2)
        self.assertEqual(report["detail_status"], "run_not_found")

    def test_summary_lines_surface_moves_and_gaps(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 0.4, "Y": 0.6})
        self.make_run("run-b", epoch=200.0, with_weights=False)
        _code, report = self.run_cli(["diff", "--task-root", str(self.root), "--summary"])
        joined = "\n".join(report["summary_lines"])
        self.assertIn("run-a -> run-b", joined)
        self.assertIn("gap:", joined)

    def test_explicit_run_pair_is_honoured(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 0.4})
        self.make_run("run-b", epoch=200.0, weights={"X": 0.5})
        self.make_run("run-c", epoch=300.0, weights={"X": 0.9})
        _code, report = self.run_cli(["diff", "--task-root", str(self.root),
                                      "--from", "run-a", "--to", "run-c"])
        self.assertEqual(report["to_run"]["run_id"], "run-c")
        self.assertEqual(report["weight_delta_pp"]["X"]["delta_pp"], 50.0)


class ToleranceTests(HistoryTestCase):
    """Tolerance comes from the run's own declarations, never from a lax default."""

    def make_run(self, run_id: str, *, epoch: float, status: str = "complete",
                 weights=None, watchlist=None, with_weights=True,
                 stages=None, unrun=None, with_summary=True) -> Path:
        run_dir = self.root / run_id
        if with_summary:
            summary: dict = {"status": status, "detail_status": "daily_run_complete",
                             "evaluation_epoch": epoch,
                             "generated_at": f"2026-09-27T0{int(epoch) % 10}:00:00+00:00",
                             "positions_input_sha256": "f" * 64,
                             "stages": stages or [{"stage": "weights", "status": "complete"},
                                                  {"stage": "watchlist", "status": "complete"}]}
            if unrun is not None:
                summary["run_inventory"] = {"stages_not_run": unrun}
            write_json(run_dir / "out" / "daily_run_summary.json", summary)
        if with_weights:
            write_json(run_dir / "out" / "weights.json", {
                "status": "complete", "detail_status": "current_weights_computed",
                "evaluation_epoch": epoch,
                "current_weights": [
                    {"symbol": symbol, "current_weight": value,
                     "quote": {"as_of": "2026-09-24T07:00:00Z"}}
                    for symbol, value in (weights or {}).items()],
            })
        if watchlist is not None:
            write_json(run_dir / "out" / "watchlist_results.json", watchlist)
        return run_dir

    DECLARED_SKIP = [{"stage": "watchlist", "reason": "skipped_by_flag:--skip-watchlist"}]

    def test_a_declared_absent_section_is_a_warning_not_a_failure(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0},
                      watchlist={"X": {"status": "ok", "categories": {}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0}, unrun=self.DECLARED_SKIP)
        code, report = self.run_cli(["diff", "--task-root", str(self.root), "--summary"])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "complete_with_warnings")
        self.assertEqual(report["detail_status"], "diff_computed_with_warnings")
        self.assertEqual(report["gaps"], [])
        self.assertEqual(report["sections"]["boundaries"]["severity"], "warning")
        self.assertIs(report["sections"]["boundaries"]["declared_by_run"], True)
        # The boundary answers stay unknown rather than becoming "nothing crossed".
        self.assertIsNone(report["boundary_crossed_cleared"])
        self.assertIsNone(report["boundary_transitions"])
        self.assertIn("warn:", "\n".join(report["summary_lines"]))
        self.assertNotIn("gap:", "\n".join(report["summary_lines"]))

    def test_an_undeclared_absent_section_still_fails_closed(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0},
                      watchlist={"X": {"status": "ok", "categories": {}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0})
        code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertEqual(report["detail_status"], "diff_partial")
        self.assertIs(report["sections"]["boundaries"]["declared_by_run"], False)
        self.assertTrue(any("run-a / run-b" in gap for gap in report["gaps"]))

    def test_strict_keeps_a_declared_absence_blocking(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0},
                      watchlist={"X": {"status": "ok", "categories": {}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0}, unrun=self.DECLARED_SKIP)
        code, report = self.run_cli(["diff", "--task-root", str(self.root), "--strict"])
        self.assertEqual(code, 2)
        self.assertEqual(report["detail_status"], "diff_partial")
        self.assertIs(report["strict"], True)

    def test_requested_sections_decide_what_may_block(self):
        self.make_run("run-a", epoch=100.0, with_weights=False,
                      watchlist={"X": {"status": "ok", "categories": {}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0},
                      watchlist={"X": {"status": "insufficient_evidence",
                                       "categories": {}}})
        blocked = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(blocked[0], 2)
        narrow, report = self.run_cli(["diff", "--task-root", str(self.root),
                                       "--sections", "boundaries"])
        self.assertEqual(narrow, 0)
        self.assertEqual(report["requested_sections"], ["boundaries"])
        self.assertEqual(report["comparable_section_count"], 1)
        # Not requested means not compared, so the payload stays null rather than
        # claiming a weight delta was computed.
        self.assertEqual(report["sections"]["weights"]["state"], "not_requested")
        self.assertIsNone(report["weight_delta_pp"])
        self.assertEqual(report["boundary_transitions"]["X"],
                         {"from_status": "ok", "to_status": "insufficient_evidence"})

    def test_an_unknown_section_is_refused(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0})
        code, report = self.run_cli(["diff", "--task-root", str(self.root),
                                     "--sections", "weights,bogus"])
        self.assertEqual(code, 3)
        self.assertEqual(report["detail_status"], "unknown_section")
        self.assertIn("bogus", " ".join(report["errors"]))

    def test_an_empty_section_list_is_not_treated_as_every_section(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0})
        code, report = self.run_cli(["diff", "--task-root", str(self.root),
                                     "--sections", " , "])
        self.assertEqual(code, 3)
        self.assertEqual(report["detail_status"], "no_sections_requested")

    def test_nothing_comparable_is_not_a_clean_diff(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0}, unrun=self.DECLARED_SKIP)
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0}, unrun=self.DECLARED_SKIP)
        code, report = self.run_cli(["diff", "--task-root", str(self.root),
                                     "--sections", "boundaries"])
        self.assertEqual(code, 2)
        self.assertEqual(report["detail_status"], "nothing_comparable")
        self.assertIsNone(report["boundary_transitions"])

    def test_a_missing_weights_artifact_does_not_claim_symbols_were_removed(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 0.4, "Y": 0.6})
        self.make_run("run-b", epoch=200.0, with_weights=False)
        _code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertIsNone(report["symbols_removed"])
        self.assertIsNone(report["symbols_added"])
        self.assertIsNone(report["weight_delta_pp"])

    def test_a_blocked_weights_section_does_not_double_count_the_quotes_section(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0})
        self.make_run("run-b", epoch=200.0, with_weights=False)
        _code, report = self.run_cli(["diff", "--task-root", str(self.root)])
        self.assertEqual(report["sections"]["quotes"]["state"], "not_comparable")
        # One missing file must not produce two gaps.
        self.assertEqual(report["sections"]["quotes"]["severity"], "none")
        self.assertEqual([gap for gap in report["gaps"] if "quotes" in gap], [])
        self.assertIsNone(report["quote_as_of_changes"])

    def test_a_run_without_a_summary_is_a_warning_not_a_failure(self):
        self.make_run("run-a", epoch=100.0, weights={"X": 0.4})
        self.make_run("run-b", epoch=200.0, weights={"X": 0.5}, with_summary=False)
        code, report = self.run_cli(["diff", "--task-root", str(self.root),
                                     "--sections", "weights"])
        self.assertEqual(code, 0)
        self.assertEqual(report["weight_delta_pp"]["X"]["delta_pp"], 10.0)
        self.assertTrue(any("run summary missing on to" in warning
                            for warning in report["warnings"]))

    def test_a_declared_absence_is_only_honoured_when_the_run_declared_it(self):
        # The same absent artifact, with and without the run's own declaration.
        self.make_run("run-a", epoch=100.0, weights={"X": 1.0},
                      watchlist={"X": {"status": "ok", "categories": {}}})
        self.make_run("run-b", epoch=200.0, weights={"X": 1.0}, unrun=self.DECLARED_SKIP)
        self.make_run("run-c", epoch=300.0, weights={"X": 1.0})
        declared = self.run_cli(["diff", "--task-root", str(self.root),
                                 "--from", "run-a", "--to", "run-b"])
        undeclared = self.run_cli(["diff", "--task-root", str(self.root),
                                   "--from", "run-a", "--to", "run-c"])
        self.assertEqual(declared[0], 0)
        self.assertEqual(undeclared[0], 2)


if __name__ == "__main__":
    unittest.main()
