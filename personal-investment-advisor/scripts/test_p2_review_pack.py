"""Contract tests for the independent review brief packer (P2-3).

A lane must never be handed a brief whose required inputs are missing, and the
brief must declare the tools the lane needs so an environment gap is reported
instead of silently producing "evidence".
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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_review_pack as packer  # noqa: E402


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "run-a"
        (self.run_dir / "out").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative: str, payload) -> Path:
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return path

    def seed(self) -> None:
        self.write("out/daily_run_summary.json", {"status": "complete"})
        self.write("out/weights.json", {"status": "complete", "current_weights": []})
        self.write("out/quotes.json", {"records": [], "portfolio_batch_audit": {}})
        self.write("out/watchlist_results.json", {})

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = packer.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_shipped_lanes_declare_tools_questions_and_constraints(self):
        lanes = packer.load_lanes()["lanes"]
        self.assertIn("numbers-auditor", lanes)
        for name, lane in lanes.items():
            self.assertTrue(lane["required_tools"], name)
            self.assertTrue(lane["questions"], name)
            self.assertTrue(lane["output_contract"], name)
            self.assertIn("写", " ".join(lane["forbidden"]), name)

    def test_brief_declares_tools_and_hashes_present_inputs(self):
        self.seed()
        code, report = self.run_cli(["--lane", "numbers-auditor", "--run-dir", str(self.run_dir),
                                     "--out", str(self.run_dir / "review.md")])
        self.assertEqual(code, 0, report)
        self.assertEqual(report["detail_status"], "brief_ready")
        self.assertIn("bash", report["required_tools"])
        weights = next(row for row in report["present_inputs"] if row["path"].endswith("weights.json"))
        self.assertEqual(weights["sha256"],
                         hashlib.sha256((self.run_dir / "out" / "weights.json").read_bytes()).hexdigest())
        brief = (self.run_dir / "review.md").read_text(encoding="utf-8")
        self.assertIn("## 声明所需工具", brief)
        self.assertIn("## 必须回答的问题", brief)
        self.assertIn("UNVERIFIED", brief)

    def test_missing_required_input_refuses_to_hand_over_a_brief(self):
        self.write("out/daily_run_summary.json", {"status": "complete"})
        code, report = self.run_cli(["--lane", "numbers-auditor", "--run-dir", str(self.run_dir),
                                     "--out", str(self.run_dir / "review.md")])
        self.assertEqual(code, 2)
        self.assertEqual(report["detail_status"], "required_inputs_missing")
        self.assertIn("out/weights.json", report["missing_inputs"])
        self.assertIsNone(report["brief_file"])
        self.assertFalse((self.run_dir / "review.md").exists())

    def test_unknown_lane_is_refused(self):
        self.seed()
        code, payload = self.run_cli(["--lane", "nope", "--run-dir", str(self.run_dir)])
        self.assertEqual(code, 3)
        self.assertIn("unknown lane", payload["errors"][0])

    def test_missing_run_dir_is_refused(self):
        code, payload = self.run_cli(["--lane", "numbers-auditor",
                                      "--run-dir", str(self.root / "absent")])
        self.assertEqual(code, 3)
        self.assertIn("run directory not found", payload["errors"][0])

    def test_evidence_lane_declares_web_tools(self):
        self.seed()
        self.write("out/scenario_result.json", {"valid": True})
        code, report = self.run_cli(["--lane", "evidence-auditor", "--run-dir", str(self.run_dir)])
        self.assertEqual(code, 0, report)
        self.assertIn("web_search", report["required_tools"])

    def test_contract_lane_needs_the_refresh_receipt(self):
        self.seed()
        code, report = self.run_cli(["--lane", "contract-reviewer", "--run-dir", str(self.run_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(report["missing_inputs"], ["out/refresh_receipt.json"])
        self.write("out/refresh_receipt.json", {"original_unchanged": True})
        self.assertEqual(self.run_cli(["--lane", "contract-reviewer",
                                       "--run-dir", str(self.run_dir)])[0], 0)

    def test_malformed_lane_specification_is_rejected(self):
        broken = self.root / "lanes.json"
        broken.write_text(json.dumps({"lanes": {"x": {"purpose": "p"}}}), encoding="utf-8")
        code, payload = self.run_cli(["--lane", "x", "--run-dir", str(self.run_dir),
                                      "--lanes-file", str(broken)])
        self.assertEqual(code, 3)
        self.assertIn("required_tools", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
