"""Contract tests for the user-confirmed thesis condition ledger (P1-6).

A confirmation date and source locator are mandatory, backdating is refused, and
``show --as-of`` must return the version that was effective on that date rather
than the newest one.
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

import pia_thesis_ledger as ledger  # noqa: E402


def condition(condition_id: str = "c1", **overrides) -> dict:
    payload = {"id": condition_id, "metric": "扣非归母净利润", "operator": "lt",
               "threshold": 100.0, "unit": "CNY", "period": "FY2027",
               "due": "2028-04-30", "channel": "cninfo 年度报告"}
    payload.update(overrides)
    return payload


class ThesisLedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger_file = self.root / "thesis_ledger.json"
        self.conditions_file = self.root / "conditions.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write_conditions(self, payload) -> Path:
        self.conditions_file.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return self.conditions_file

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ledger.main(argv)
        return code, json.loads(buffer.getvalue())

    def init(self) -> None:
        code, payload = self.run_cli(["init", "--file", str(self.ledger_file)])
        self.assertEqual(code, 0, payload)

    def append(self, *, confirmed_at: str, conditions=None, locator="dataset://pia/user-policy/X",
               symbol="601899.SS", note=None) -> tuple[int, dict]:
        self.write_conditions(conditions or [condition()])
        argv = ["append", "--file", str(self.ledger_file), "--symbol", symbol,
                "--confirmed-at", confirmed_at, "--source-locator", locator,
                "--conditions-file", str(self.conditions_file)]
        if note:
            argv.extend(["--note", note])
        return self.run_cli(argv)

    def test_init_then_append_records_a_version(self):
        self.init()
        code, payload = self.append(confirmed_at="2026-08-05", note="route A confirmation")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["condition_ids"], ["c1"])
        stored = json.loads(self.ledger_file.read_text(encoding="utf-8"))
        self.assertEqual(stored["symbols"]["601899.SS"]["versions"][0]["note"],
                         "route A confirmation")

    def test_init_refuses_to_overwrite_without_force(self):
        self.init()
        code, payload = self.run_cli(["init", "--file", str(self.ledger_file)])
        self.assertEqual(code, 3)
        self.assertIn("already exists", payload["errors"][0])

    def test_backdating_is_refused(self):
        self.init()
        self.assertEqual(self.append(confirmed_at="2026-08-05")[0], 0)
        code, payload = self.append(confirmed_at="2026-07-01", conditions=[condition("c2")])
        self.assertEqual(code, 3)
        self.assertIn("backdating", payload["errors"][0])
        stored = json.loads(self.ledger_file.read_text(encoding="utf-8"))
        self.assertEqual(len(stored["symbols"]["601899.SS"]["versions"]), 1)

    def test_show_returns_the_version_effective_at_a_date(self):
        self.init()
        self.append(confirmed_at="2026-08-05", conditions=[condition("c1", threshold=100.0)])
        self.append(confirmed_at="2026-09-20", conditions=[condition("c1", threshold=150.0)])
        _code, shown = self.run_cli(["show", "--file", str(self.ledger_file),
                                     "--symbol", "601899.SS", "--as-of", "2026-08-31"])
        self.assertEqual(shown["version"], 1)
        self.assertEqual(shown["conditions"][0]["threshold"], 100.0)
        _code, newest = self.run_cli(["show", "--file", str(self.ledger_file),
                                      "--symbol", "601899.SS"])
        self.assertEqual(newest["version"], 2)
        self.assertEqual(newest["conditions"][0]["threshold"], 150.0)

    def test_show_before_the_first_version_is_insufficient_data(self):
        self.init()
        self.append(confirmed_at="2026-08-05")
        code, payload = self.run_cli(["show", "--file", str(self.ledger_file),
                                      "--symbol", "601899.SS", "--as-of", "2026-01-01"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "no_version_effective")

    def test_unknown_symbol_is_reported(self):
        self.init()
        code, payload = self.run_cli(["show", "--file", str(self.ledger_file),
                                      "--symbol", "999999.SS"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "symbol_not_in_ledger")

    def test_duplicate_condition_id_is_refused(self):
        self.init()
        code, payload = self.append(confirmed_at="2026-08-05",
                                    conditions=[condition("c1"), condition("c1")])
        self.assertEqual(code, 3)
        self.assertIn("duplicated", payload["errors"][0])

    def test_numeric_operator_requires_a_numeric_threshold(self):
        self.init()
        code, payload = self.append(confirmed_at="2026-08-05",
                                    conditions=[condition("c1", threshold=None)])
        self.assertEqual(code, 3)
        self.assertIn("threshold must be a number", payload["errors"][0])

    def test_qualitative_rule_needs_no_threshold(self):
        self.init()
        code, payload = self.append(confirmed_at="2026-08-05", conditions=[condition(
            "c1", operator="qualitative", threshold=None, metric="减值计提显著超出已披露口径")])
        self.assertEqual(code, 0, payload)

    def test_missing_channel_and_locator_are_refused(self):
        self.init()
        payload = condition("c1")
        payload.pop("channel")
        code, result = self.append(confirmed_at="2026-08-05", conditions=[payload])
        self.assertEqual(code, 3)
        self.assertIn("channel is required", result["errors"][0])
        code, result = self.append(confirmed_at="2026-08-05",
                                   locator="https://example.test/policy")
        self.assertEqual(code, 3)
        self.assertIn("reserved test locator", result["errors"][0])

    def test_list_summarizes_symbols(self):
        self.init()
        self.append(confirmed_at="2026-08-05")
        self.append(confirmed_at="2026-08-06", symbol="159072.SZ")
        _code, listed = self.run_cli(["list", "--file", str(self.ledger_file)])
        self.assertEqual(listed["symbol_count"], 2)
        self.assertEqual([row["symbol"] for row in listed["symbols"]],
                         ["159072.SZ", "601899.SS"])

    def test_written_ledger_is_valid_json_after_append(self):
        self.init()
        self.append(confirmed_at="2026-08-05")
        payload = json.loads(self.ledger_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], ledger.SCHEMA_VERSION)
        self.assertFalse((self.ledger_file.parent /
                          (self.ledger_file.name + ".tmp")).exists())


if __name__ == "__main__":
    unittest.main()
