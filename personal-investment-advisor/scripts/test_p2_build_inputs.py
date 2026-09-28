"""Contract tests for ``pia_build.py`` (gate-ready input builders).

The builders must derive inputs from upstream artifacts, hash local files
themselves, and fail closed rather than inventing a value.  The scenario builder
is additionally checked against a fixed expected portfolio return so a silent
change in derivation cannot pass unnoticed.
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

import pia_build  # noqa: E402


def weights_payload() -> dict:
    return {
        "status": "complete",
        "evaluation_epoch": 1790474476.0456684,
        "current_weights": [
            {"symbol": "AAA", "current_weight": 0.3, "current_price": 100.0,
             "market_value_base": 300.0, "currency": "CNY"},
            {"symbol": "BBB", "current_weight": 0.2, "current_price": 50.0,
             "market_value_base": 200.0, "currency": "CNY"},
            {"symbol": "CASH_CNY", "current_weight": 0.5, "current_price": 1.0,
             "market_value_base": 500.0, "currency": "CNY"},
        ],
    }


def policy_payload(denominator: str | None = "active_non_cash_market_value") -> dict:
    return {
        "decision_scope": "research_only",
        "bucket_policy": {"denominator": denominator,
                          "core_fraction": 0.8, "satellite_fraction": 0.2,
                          "tolerance_fraction": 0.02,
                          "core": ["AAA"], "satellite": ["BBB"],
                          "excluded_cash": ["CASH_CNY"]},
        "main_local_total_returns": {"AAA": -0.2, "BBB": -0.15, "CASH_CNY": 0.0},
        "main_usd_cny_return": 0.05,
        "sensitivity_overrides": {"AAA_local_total_return": -0.3, "usd_cny_return": 0.0},
        "scenario_names": ["recession", "sensitivity"],
    }


def positions_payload(cash_lines: int = 1) -> dict:
    positions = [
        {"symbol": "AAA", "quantity": 3, "avg_cost": 100.0, "currency": "CNY",
         "market": "CN", "asset_type": "stock"},
        {"symbol": "BBB", "quantity": 4, "avg_cost": 50.0, "currency": "CNY",
         "market": "CN", "asset_type": "stock"},
        {"symbol": "CASH_CNY", "quantity": 500, "avg_cost": 1.0, "currency": "CNY",
         "market": "CASH", "asset_type": "cash"},
    ]
    if cash_lines > 1:
        positions.append({"symbol": "CASH_USD", "quantity": 10, "avg_cost": 1.0,
                          "currency": "USD", "market": "CASH", "asset_type": "cash"})
    return {"base_currency": "CNY", "positions": positions,
            "exchange_rates": {"CNY": 1.0, "USD": 6.7},
            "exchange_rate_metadata": {"USD": {"pair": "USD/CNY", "as_of": "2026-09-26",
                                               "source": "fixture",
                                               "source_locator": "dataset://fixture/fx",
                                               "retrieved_at": "2026-09-27T00:00:00+00:00",
                                               "content_sha256": "a" * 64}}}


class BuildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.task_dir = self.root / "task"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative: str, payload) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        return path

    def run_builder(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_build.main(argv)
        return code, json.loads(buffer.getvalue())


class ScenarioBuilderTests(BuildTestCase):
    def test_scenario_inputs_are_built_and_locators_resolve(self):
        weights = self.write("weights.json", weights_payload())
        policy = self.write("policy.json", policy_payload())
        positions = self.write("positions.json", positions_payload())
        code, payload = self.run_builder([
            "scenario", "--weights-file", str(weights), "--confirmed-policy", str(policy),
            "--positions-file", str(positions), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0, payload)
        assumptions = json.loads(Path(payload["assumptions_json"]).read_text(encoding="utf-8"))
        self.assertEqual(assumptions["scenario_contract_version"], "2.0")
        snapshot = assumptions["weight_snapshot"]
        self.assertEqual(snapshot["market_values_base_currency"]["AAA"], 300.0)
        self.assertEqual(snapshot["content_sha256"],
                         hashlib.sha256(weights.read_bytes()).hexdigest())
        # weight snapshot digest must bind the copy that the locator resolves to
        copied = self.task_dir / "out" / "weights.json"
        self.assertEqual(snapshot["content_sha256"],
                         hashlib.sha256(copied.read_bytes()).hexdigest())
        manifest = json.loads((self.task_dir / "inputs" / "dataset_manifest.json")
                              .read_text(encoding="utf-8"))
        for binding in manifest["bindings"]:
            self.assertTrue((self.task_dir / binding["file"]).is_file(), binding)
        primary = assumptions["scenarios"][0]["asset_returns"]["AAA"]["return"]
        sensitivity = assumptions["scenarios"][1]["asset_returns"]["AAA"]["return"]
        self.assertEqual(primary, -0.2)
        self.assertEqual(sensitivity, -0.3)

    def test_incomplete_weights_run_is_rejected(self):
        payload = weights_payload()
        payload["status"] = "invalid_input"
        weights = self.write("weights.json", payload)
        policy = self.write("policy.json", policy_payload())
        positions = self.write("positions.json", positions_payload())
        code, result = self.run_builder([
            "scenario", "--weights-file", str(weights), "--confirmed-policy", str(policy),
            "--positions-file", str(positions), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("status is 'invalid_input'", result["errors"][0])

    def test_policy_missing_a_symbol_return_is_rejected(self):
        policy_payload_missing = policy_payload()
        policy_payload_missing["main_local_total_returns"].pop("CASH_CNY")
        weights = self.write("weights.json", weights_payload())
        policy = self.write("policy.json", policy_payload_missing)
        positions = self.write("positions.json", positions_payload())
        code, result = self.run_builder([
            "scenario", "--weights-file", str(weights), "--confirmed-policy", str(policy),
            "--positions-file", str(positions), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("no scenario return for: CASH_CNY", result["errors"][0])

    def test_existing_output_requires_force(self):
        weights = self.write("weights.json", weights_payload())
        policy = self.write("policy.json", policy_payload())
        positions = self.write("positions.json", positions_payload())
        base = ["scenario", "--weights-file", str(weights), "--confirmed-policy", str(policy),
                "--positions-file", str(positions), "--task-dir", str(self.task_dir)]
        self.assertEqual(self.run_builder(base)[0], 0)
        code, result = self.run_builder(base)
        self.assertEqual(code, 3)
        self.assertIn("already exists", result["errors"][0])
        self.assertEqual(self.run_builder([*base, "--force"])[0], 0)


class InverseVolBuilderTests(BuildTestCase):
    def observations(self, symbols=("AAA", "BBB")) -> dict:
        record = {"annualized_volatility": 0.25, "observation_count": 252,
                  "window_start": "2025-09-26", "window_end": "2026-09-25",
                  "as_of": "2026-09-26", "source": "fixture",
                  "source_locator": "dataset://fixture/vol"}
        return {"as_of": "2026-09-26",
                "volatility_observations": {symbol: dict(record) for symbol in symbols}}

    def test_legacy_policy_with_two_cash_lines_is_still_refused(self):
        policy = self.write("policy.json", policy_payload(denominator=None))
        positions = self.write("positions.json", positions_payload(cash_lines=2))
        observations = self.write("vol.json", self.observations())
        code, result = self.run_builder([
            "inverse-vol", "--confirmed-policy", str(policy), "--positions-file", str(positions),
            "--volatilities-file", str(observations), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("cash_bucket_rule_conflict", result["errors"][0])
        self.assertIn("active_non_cash_market_value", result["errors"][0])

    def test_declared_non_cash_denominator_excludes_cash_with_reasons(self):
        policy = self.write("policy.json", policy_payload())
        positions = self.write("positions.json", positions_payload(cash_lines=2))
        observations = self.write("vol.json", self.observations())
        code, result = self.run_builder([
            "inverse-vol", "--confirmed-policy", str(policy), "--positions-file", str(positions),
            "--volatilities-file", str(observations), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0, result)
        built = json.loads(Path(result["policy_file"]).read_text(encoding="utf-8"))
        self.assertEqual(built["denominator"], "active_non_cash_market_value")
        self.assertEqual(sorted(built["excluded_policy_symbols"]), ["CASH_CNY", "CASH_USD"])
        for reason in built["excluded_policy_symbols"].values():
            self.assertIn("non-cash market value", reason)
        self.assertEqual(built["bucket_members"], {"core": ["AAA"], "satellite": ["BBB"]})
        self.assertAlmostEqual(sum(built["bucket_targets"].values()), 1.0, places=9)

    def test_legacy_policy_with_one_cash_position_still_conflicts(self):
        policy = self.write("policy.json", policy_payload(denominator=None))
        positions = self.write("positions.json", positions_payload())
        observations = self.write("vol.json", self.observations())
        code, result = self.run_builder([
            "inverse-vol", "--confirmed-policy", str(policy), "--positions-file", str(positions),
            "--volatilities-file", str(observations), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(result["detail_status"], "cash_bucket_weight_conflict")
        self.assertIn("CASH_CNY", result["errors"][0])
        self.assertTrue(result["remediation"])
        self.assertFalse((self.task_dir / "inputs" / "inverse_volatility_policy.json").exists())

    def test_policy_is_built_when_no_cash_position_is_active(self):
        policy = self.write("policy.json", policy_payload())
        payload = positions_payload()
        payload["positions"] = [item for item in payload["positions"]
                                if item["symbol"] != "CASH_CNY"]
        positions = self.write("positions.json", payload)
        observations = self.write("vol.json", self.observations())
        code, result = self.run_builder([
            "inverse-vol", "--confirmed-policy", str(policy), "--positions-file", str(positions),
            "--volatilities-file", str(observations), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0, result)
        built = json.loads(Path(result["policy_file"]).read_text(encoding="utf-8"))
        self.assertEqual(built["bucket_targets"], {"core": 0.8, "satellite": 0.2})
        self.assertEqual(built["bucket_members"], {"core": ["AAA"], "satellite": ["BBB"]})

    def test_missing_observation_is_insufficient_data(self):
        policy = self.write("policy.json", policy_payload())
        positions = self.write("positions.json", positions_payload())
        observations = self.write("vol.json", self.observations(symbols=()))
        code, result = self.run_builder([
            "inverse-vol", "--confirmed-policy", str(policy), "--positions-file", str(positions),
            "--volatilities-file", str(observations), "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(result["detail_status"], "volatility_observations_incomplete")


class ThesisPackBuilderTests(BuildTestCase):
    def setUp(self):
        super().setUp()
        self.quotes = self.write("quotes.json", {
            "status": "complete",
            "portfolio_batch_audit": {
                "portfolio_snapshot_binding": {
                    "schema_version": "pia_portfolio_snapshot_v1",
                    "sha256": "b" * 64,
                    "active_positions": [
                        {"symbol": "AAA", "quantity": "5", "currency": "CNY",
                         "market": "CN", "asset_type": "stock"},
                        {"symbol": "CASH_CNY", "quantity": "500", "currency": "CNY",
                         "market": "CASH", "asset_type": "cash"},
                    ],
                }
            },
        })
        (self.task_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.task_dir / "raw" / "note.txt").write_bytes(b"primary source body\n")

    def evidence(self, declared: str | None = None) -> dict:
        item = {"evidence_id": "e1", "source_tier": "issuer",
                "source_locator": "https://example.test/filing",
                "published_at": "2026-09-24T00:00:00+00:00",
                "retrieved_at": "2026-09-27T00:00:00+00:00",
                "claim": "fixture claim", "artifact": "raw/note.txt"}
        if declared:
            item["content_sha256"] = declared
        return {"evidence_items": [item]}

    def assessments(self) -> dict:
        return {"assessments": [{"symbol": "AAA", "conclusion": "insufficient_evidence",
                                 "rationale": "fixture", "evidence_ids": ["e1"]}]}

    def scopes(self) -> dict:
        return {"scope_coverage": {"macro": {"status": "complete", "evidence_ids": ["e1"]},
                                   "sector": {"status": "insufficient_evidence",
                                              "evidence_ids": ["e1"]},
                                   "regulatory": {"status": "complete", "evidence_ids": ["e1"]}}}

    def test_pack_hashes_local_artifacts_and_binds_the_quote_snapshot(self):
        evidence = self.write("evidence.json", self.evidence())
        assessments = self.write("assessments.json", self.assessments())
        scopes = self.write("scopes.json", self.scopes())
        code, result = self.run_builder([
            "thesis-pack", "--quotes-file", str(self.quotes), "--evidence-file", str(evidence),
            "--assessments-file", str(assessments), "--scope-coverage-file", str(scopes),
            "--window-start", "2026-09-24T00:00:00+00:00", "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0, result)
        pack = json.loads(Path(result["pack_file"]).read_text(encoding="utf-8"))
        expected = hashlib.sha256((self.task_dir / "raw" / "note.txt").read_bytes()).hexdigest()
        self.assertEqual(pack["evidence_items"][0]["content_sha256"], expected)
        self.assertEqual(pack["portfolio_snapshot_binding"]["sha256"], "b" * 64)
        self.assertEqual(pack["schema_version"], "pia_thesis_red_team_v1")

    def test_declared_hash_mismatch_is_rejected(self):
        evidence = self.write("evidence.json", self.evidence(declared="c" * 64))
        assessments = self.write("assessments.json", self.assessments())
        scopes = self.write("scopes.json", self.scopes())
        code, result = self.run_builder([
            "thesis-pack", "--quotes-file", str(self.quotes), "--evidence-file", str(evidence),
            "--assessments-file", str(assessments), "--scope-coverage-file", str(scopes),
            "--window-start", "2026-09-24T00:00:00+00:00", "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("does not match", result["errors"][0])

    def test_missing_assessment_is_rejected(self):
        evidence = self.write("evidence.json", self.evidence())
        assessments = self.write("assessments.json", {"assessments": []})
        scopes = self.write("scopes.json", self.scopes())
        code, result = self.run_builder([
            "thesis-pack", "--quotes-file", str(self.quotes), "--evidence-file", str(evidence),
            "--assessments-file", str(assessments), "--scope-coverage-file", str(scopes),
            "--window-start", "2026-09-24T00:00:00+00:00", "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("do not cover: AAA", result["errors"][0])


class DatasetManifestTests(BuildTestCase):
    def test_bindings_merge_across_calls(self):
        first = self.write("a.json", {"a": 1})
        second = self.write("b.json", {"b": 2})
        code, result = self.run_builder([
            "dataset-manifest", "--task-dir", str(self.task_dir),
            "--artifact", f"raw/a.json={first}", "--artifact", f"raw/b.json={second}"])
        self.assertEqual(code, 0)
        self.assertEqual(result["binding_count"], 2)
        code, result = self.run_builder([
            "dataset-manifest", "--task-dir", str(self.task_dir),
            "--artifact", f"raw/a.json={first}"])
        manifest = json.loads((self.task_dir / "inputs" / "dataset_manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["bindings"]), 2)


if __name__ == "__main__":
    unittest.main()
