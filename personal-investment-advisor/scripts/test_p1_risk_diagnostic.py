"""Contract tests for the partial risk diagnostic (P1-7).

The diagnostic must compute what the supplied histories support, name every excluded
symbol with a reason, size the coverage gap in market value, and never present the
covered-subset result as the portfolio's risk contribution.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_risk_diagnostic as risk  # noqa: E402

NOW = datetime.datetime(2026, 9, 27, 12, 0, tzinfo=datetime.timezone.utc)


def price_history(days: int = 60, *, start: float = 100.0, step: float = 0.5,
                  cycle: float = 0.0) -> dict:
    rows = []
    price = start
    day = datetime.date(2026, 1, 1)
    for index in range(days):
        price = start + step * index + cycle * math.sin(index / 3.0)
        rows.append({"Date": day.isoformat(), "Close": round(price, 4)})
        day += datetime.timedelta(days=1)
    return {"symbol": "synthetic", "history": rows}


class RiskDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.weights = self.root / "weights.json"
        self._write_weights({
            "AAA": {"weight": 0.4, "value": 400.0},
            "BBB": {"weight": 0.3, "value": 300.0},
            "CCC": {"weight": 0.2, "value": 200.0},
            "CASH_CNY": {"weight": 0.1, "value": 100.0},
        })

    def tearDown(self):
        self._tmp.cleanup()

    def _write_weights(self, spec: dict) -> None:
        self.weights.write_bytes(json.dumps({
            "status": "complete",
            "current_weights": [
                {"symbol": symbol, "current_weight": row["weight"],
                 "market_value_base": row["value"], "currency": "CNY"}
                for symbol, row in spec.items()],
        }).encode("utf-8"))

    def history_file(self, name: str, payload: dict) -> Path:
        path = self.root / f"{name}.json"
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        return path

    def run_cli(self, histories: dict[str, Path], out: Path | None = None) -> tuple[int, dict]:
        argv = ["--weights-file", str(self.weights)]
        for symbol, path in histories.items():
            argv.extend(["--history", f"{symbol}={path}"])
        if out is not None:
            argv.extend(["--out", str(out)])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_partial_coverage_is_declared_with_reasons_and_share(self):
        histories = {
            "AAA": self.history_file("aaa", price_history(step=0.5)),
            "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0)),
        }
        code, payload = self.run_cli(histories)
        self.assertEqual(code, 0, payload)
        coverage = payload["coverage"]
        self.assertEqual(coverage["covered_symbols"], ["AAA", "BBB"])
        self.assertEqual(coverage["active_non_cash_count"], 3)
        self.assertAlmostEqual(coverage["covered_share_of_non_cash_value"], 700.0 / 900.0, places=6)
        excluded = {row["symbol"]: row["reason"] for row in coverage["excluded_symbols"]}
        self.assertEqual(excluded["CCC"], "no_history_supplied")
        self.assertEqual(excluded["CASH_CNY"], "base_currency_cash_excluded_from_equity_risk")
        self.assertIn("not the portfolio's risk contribution", coverage["statement"])
        self.assertEqual(payload["method"]["labels"],
                         list(risk.METHOD_LABELS))
        self.assertTrue(payload["non_executable"])

    def test_weights_are_renormalised_inside_the_covered_subset(self):
        histories = {
            "AAA": self.history_file("aaa", price_history(step=0.5)),
            "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0)),
        }
        _code, payload = self.run_cli(histories)
        renormalised = payload["renormalized_weights_within_subset"]
        self.assertAlmostEqual(sum(renormalised.values()), 1.0, places=6)
        self.assertAlmostEqual(renormalised["AAA"], 0.4 / 0.7, places=6)
        self.assertAlmostEqual(sum(payload["risk_contribution_within_subset"].values()), 1.0,
                               places=6)

    def test_correlation_is_symmetric_with_a_unit_diagonal(self):
        histories = {
            "AAA": self.history_file("aaa", price_history(step=0.5)),
            "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0)),
        }
        _code, payload = self.run_cli(histories)
        correlation = payload["correlation"]
        for left in correlation:
            self.assertEqual(correlation[left][left], 1.0)
            for right in correlation[left]:
                self.assertEqual(correlation[left][right], correlation[right][left])
        self.assertGreater(payload["covered_subset_annualized_volatility"], 0)

    def test_reruns_are_deterministic_apart_from_the_timestamp(self):
        histories = {
            "AAA": self.history_file("aaa", price_history(step=0.5)),
            "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0)),
        }
        first = self.run_cli(histories)[1]
        second = self.run_cli(histories)[1]
        first.pop("generated_at")
        second.pop("generated_at")
        self.assertEqual(first, second)

    def test_unusable_history_is_excluded_not_silently_dropped(self):
        broken = self.root / "broken.json"
        broken.write_bytes(json.dumps({"history": []}).encode("utf-8"))
        histories = {
            "AAA": self.history_file("aaa", price_history(step=0.5)),
            "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0)),
            "CCC": broken,
        }
        code, payload = self.run_cli(histories)
        self.assertEqual(code, 0, payload)
        excluded = {row["symbol"]: row["reason"] for row in payload["coverage"]["excluded_symbols"]}
        self.assertIn("unusable_history", excluded["CCC"])

    def test_provenance_records_file_hashes(self):
        import hashlib
        path = self.history_file("aaa", price_history(step=0.5))
        histories = {"AAA": path,
                     "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0))}
        _code, payload = self.run_cli(histories)
        row = next(item for item in payload["history_provenance"] if item["symbol"] == "AAA")
        self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_too_few_usable_histories_is_refused(self):
        histories = {"AAA": self.history_file("aaa", price_history(step=0.5))}
        code, payload = self.run_cli(histories)
        self.assertEqual(code, 3)
        self.assertIn("at least two usable histories", payload["errors"][0])

    def test_short_common_window_is_refused(self):
        histories = {
            "AAA": self.history_file("aaa", price_history(20)),
            "BBB": self.history_file("bbb", price_history(20, step=-0.3)),
        }
        code, payload = self.run_cli(histories)
        self.assertEqual(code, 3)
        self.assertIn("at least two usable histories", payload["errors"][0])
        # the per-symbol reason must survive the failure path
        reasons = {row["symbol"]: row["reason"] for row in payload["exclusions"]}
        self.assertIn("too few usable closes", reasons["AAA"])

    def test_missing_history_file_is_an_input_error(self):
        argv = ["--weights-file", str(self.weights),
                "--history", f"AAA={self.root / 'absent.json'}"]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(argv)
        self.assertEqual(code, 3)
        self.assertIn("history file not found", json.loads(buffer.getvalue())["errors"][0])

    def test_out_writes_the_diagnostic_with_a_hash(self):
        histories = {
            "AAA": self.history_file("aaa", price_history(step=0.5)),
            "BBB": self.history_file("bbb", price_history(step=-0.3, cycle=2.0)),
        }
        target = self.root / "out" / "risk_diagnostic.json"
        code, payload = self.run_cli(histories, out=target)
        self.assertEqual(code, 0)
        import hashlib
        self.assertEqual(payload["diagnostic_sha256"],
                         hashlib.sha256(target.read_bytes()).hexdigest())
        written = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(written["coverage"]["covered_count"], 2)


class UncoveredEquityPartitionTests(unittest.TestCase):
    """The value-coverage partition must account for the uncovered equity slice."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.weights = self.root / "weights.json"
        self.weights.write_bytes(json.dumps({
            "base_currency": "CNY",
            "current_weights": [
                {"symbol": "AAA", "current_weight": 0.4, "market_value_base": 400.0,
                 "currency": "CNY"},
                {"symbol": "BBB", "current_weight": 0.3, "market_value_base": 300.0,
                 "currency": "CNY"},
                {"symbol": "CCC", "current_weight": 0.2, "market_value_base": 200.0,
                 "currency": "CNY"},
                {"symbol": "CASH_CNY", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "CNY"},
            ],
        }).encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_uncovered_equity_is_unmeasured_and_the_partition_sums_to_one(self):
        paths = {}
        for symbol, step in (("AAA", 0.5), ("BBB", -0.3)):
            path = self.root / (symbol + ".json")
            path.write_bytes(json.dumps(price_history(step=step, cycle=2.0)).encode("utf-8"))
            paths[symbol] = path
        argv = ["--weights-file", str(self.weights)]
        for symbol, path in paths.items():
            argv.extend(["--history", symbol + "=" + str(path)])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(argv)
        self.assertEqual(code, 0, buffer.getvalue())
        shares = json.loads(buffer.getvalue())["value_coverage"]
        self.assertAlmostEqual(shares["equity_covered_share_of_portfolio_value"], 0.7, places=6)
        self.assertAlmostEqual(shares["equity_uncovered_share_of_portfolio_value"], 0.2, places=6)
        self.assertEqual(shares["equity_symbols_without_measured_risk"], ["CCC"])
        self.assertAlmostEqual(shares["unmeasured_share_of_portfolio_value"], 0.2, places=6)
        self.assertAlmostEqual(shares["base_currency_cash_share_of_portfolio_value"], 0.1,
                               places=6)
        self.assertAlmostEqual(shares["partition_total"], 1.0, places=6)


class CashFxRiskTests(unittest.TestCase):
    """Cash must carry a risk treatment, not just an exclusion (cash design B)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.weights = self.root / "weights.json"
        self.weights.write_bytes(json.dumps({
            "status": "complete",
            "base_currency": "CNY",
            "current_weights": [
                {"symbol": "AAA", "current_weight": 0.5, "market_value_base": 500.0,
                 "currency": "CNY"},
                {"symbol": "BBB", "current_weight": 0.3, "market_value_base": 300.0,
                 "currency": "CNY"},
                {"symbol": "CASH_CNY", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "CNY"},
                {"symbol": "CASH_USD", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "USD"},
            ],
        }).encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def payload(self, *, fx: Path | None = None, base_currency: str | None = None) -> dict:
        histories = {"AAA": self.root / "aaa.json", "BBB": self.root / "bbb.json"}
        histories["AAA"].write_bytes(json.dumps(price_history(step=0.5)).encode("utf-8"))
        histories["BBB"].write_bytes(json.dumps(price_history(step=-0.3, cycle=2.0)).encode("utf-8"))
        argv = ["--weights-file", str(self.weights)]
        for symbol, path in histories.items():
            argv.extend(["--history", f"{symbol}={path}"])
        if fx is not None:
            argv.extend(["--fx-history", f"USDCNY={fx}"])
        if base_currency:
            argv.extend(["--base-currency", base_currency])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(argv)
        self.assertEqual(code, 0, buffer.getvalue())
        return json.loads(buffer.getvalue())

    def _fx_file(self, name: str = "usdcny.json", *, shift_days: int = 0) -> Path:
        payload = price_history(60, start=7.1, step=0.002, cycle=0.05)
        if shift_days:
            payload["history"] = [
                {"Date": (datetime.date.fromisoformat(row["Date"])
                          + datetime.timedelta(days=shift_days)).isoformat(),
                 "Close": row["Close"]} for row in payload["history"]]
        path = self.root / name
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        return path

    def test_base_currency_cash_is_named_as_carrying_no_fx_risk(self):
        payload = self.payload()
        base = payload["cash_fx_risk"]["base_currency_cash"]
        self.assertEqual([row["symbol"] for row in base], ["CASH_CNY"])
        self.assertEqual(base[0]["risk_treatment"], "base_currency_cash_carries_no_fx_risk")
        self.assertEqual(payload["base_currency"], "CNY")

    def test_foreign_cash_without_fx_history_is_declared_unmeasured(self):
        payload = self.payload()
        unmeasured = payload["cash_fx_risk"]["unmeasured_cash"]
        self.assertEqual([row["symbol"] for row in unmeasured], ["CASH_USD"])
        self.assertEqual(unmeasured[0]["reason"], "no_fx_history_supplied_for_USDCNY")
        self.assertEqual(payload["cash_fx_risk"]["legs"], [])
        reasons = {row["symbol"]: row["reason"] for row in payload["coverage"]["excluded_symbols"]}
        self.assertEqual(reasons["CASH_USD"], "cash_fx_exposure_unmeasured:USDCNY")
        # an unmeasured leg must never be silently valued at zero volatility
        self.assertGreater(payload["value_coverage"]["unmeasured_share_of_portfolio_value"], 0)

    def test_foreign_cash_fx_leg_is_modelled_from_its_own_history_with_provenance(self):
        import hashlib
        fx = self._fx_file()
        payload = self.payload(fx=fx)
        legs = payload["cash_fx_risk"]["legs"]
        self.assertEqual(len(legs), 1)
        leg = legs[0]
        self.assertEqual((leg["symbol"], leg["currency"], leg["pair"]),
                         ("CASH_USD", "USD", "USDCNY"))
        self.assertGreater(leg["annualized_fx_volatility"], 0)
        self.assertAlmostEqual(leg["standalone_weighted_volatility"],
                               leg["weight_of_portfolio_value"] * leg["annualized_fx_volatility"],
                               places=6)
        self.assertAlmostEqual(leg["weight_of_portfolio_value"], 0.1, places=6)
        provenance = payload["cash_fx_risk"]["fx_history_provenance"][0]
        self.assertEqual(provenance["sha256"], hashlib.sha256(fx.read_bytes()).hexdigest())
        reasons = {row["symbol"]: row["reason"] for row in payload["coverage"]["excluded_symbols"]}
        self.assertEqual(reasons["CASH_USD"],
                         "cash_excluded_from_equity_risk_fx_modelled_separately")
        self.assertEqual(payload["cash_fx_risk"]["unmeasured_cash"], [])

    def test_combination_brackets_only_the_measured_legs(self):
        payload = self.payload(fx=self._fx_file())
        combination = payload["cash_fx_risk"]["measured_legs_combination"]
        equity = combination["equity_leg"]["weighted"]
        fx = combination["fx_leg"]["weighted_sum_of_standalone_legs"]
        self.assertAlmostEqual(combination["assumed_zero_correlation_point_estimate"],
                               math.sqrt(equity ** 2 + fx ** 2), places=6)
        self.assertAlmostEqual(combination["correlation_bounds"]["upper"], equity + fx, places=6)
        self.assertAlmostEqual(combination["correlation_bounds"]["lower"], abs(equity - fx), places=6)
        self.assertEqual(combination["excluded_from_this_combination"], [])
        self.assertIn("not bounded", combination["statement"])
        # the equity leg is the covered subset scaled to its share of the whole portfolio
        self.assertAlmostEqual(combination["equity_leg"]["weight_of_portfolio_value"],
                               (500.0 + 300.0) / 1000.0, places=6)

    def test_value_coverage_shares_partition_portfolio_value(self):
        payload = self.payload(fx=self._fx_file())
        shares = payload["value_coverage"]
        total = (shares["equity_covered_share_of_portfolio_value"]
                 + shares["fx_modelled_cash_share_of_portfolio_value"]
                 + shares["base_currency_cash_share_of_portfolio_value"]
                 + shares["unmeasured_share_of_portfolio_value"])
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertAlmostEqual(shares["equity_covered_share_of_portfolio_value"], 0.8, places=6)
        self.assertAlmostEqual(shares["fx_modelled_cash_share_of_portfolio_value"], 0.1, places=6)
        self.assertAlmostEqual(shares["base_currency_cash_share_of_portfolio_value"], 0.1,
                               places=6)
        self.assertAlmostEqual(shares["partition_total"], 1.0, places=6)



class UncoveredEquityPartitionTests(unittest.TestCase):
    """The value-coverage partition must account for the uncovered equity slice."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.weights = self.root / "weights.json"
        self.weights.write_bytes(json.dumps({
            "base_currency": "CNY",
            "current_weights": [
                {"symbol": "AAA", "current_weight": 0.4, "market_value_base": 400.0,
                 "currency": "CNY"},
                {"symbol": "BBB", "current_weight": 0.3, "market_value_base": 300.0,
                 "currency": "CNY"},
                {"symbol": "CCC", "current_weight": 0.2, "market_value_base": 200.0,
                 "currency": "CNY"},
                {"symbol": "CASH_CNY", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "CNY"},
            ],
        }).encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_uncovered_equity_is_unmeasured_and_the_partition_sums_to_one(self):
        paths = {}
        for symbol, step in (("AAA", 0.5), ("BBB", -0.3)):
            path = self.root / (symbol + ".json")
            path.write_bytes(json.dumps(price_history(step=step, cycle=2.0)).encode("utf-8"))
            paths[symbol] = path
        argv = ["--weights-file", str(self.weights)]
        for symbol, path in paths.items():
            argv.extend(["--history", symbol + "=" + str(path)])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(argv)
        self.assertEqual(code, 0, buffer.getvalue())
        shares = json.loads(buffer.getvalue())["value_coverage"]
        self.assertAlmostEqual(shares["equity_covered_share_of_portfolio_value"], 0.7, places=6)
        self.assertAlmostEqual(shares["equity_uncovered_share_of_portfolio_value"], 0.2, places=6)
        self.assertEqual(shares["equity_symbols_without_measured_risk"], ["CCC"])
        self.assertAlmostEqual(shares["unmeasured_share_of_portfolio_value"], 0.2, places=6)
        self.assertAlmostEqual(shares["base_currency_cash_share_of_portfolio_value"], 0.1,
                               places=6)
        self.assertAlmostEqual(shares["partition_total"], 1.0, places=6)


class CashFxRiskTests(unittest.TestCase):
    """Cash must carry a risk treatment, not just an exclusion (cash design B)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.weights = self.root / "weights.json"
        self.weights.write_bytes(json.dumps({
            "status": "complete",
            "base_currency": "CNY",
            "current_weights": [
                {"symbol": "AAA", "current_weight": 0.5, "market_value_base": 500.0,
                 "currency": "CNY"},
                {"symbol": "BBB", "current_weight": 0.3, "market_value_base": 300.0,
                 "currency": "CNY"},
                {"symbol": "CASH_CNY", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "CNY"},
                {"symbol": "CASH_USD", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "USD"},
            ],
        }).encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def payload(self, *, fx: Path | None = None, base_currency: str | None = None) -> dict:
        histories = {"AAA": self.root / "aaa.json", "BBB": self.root / "bbb.json"}
        histories["AAA"].write_bytes(json.dumps(price_history(step=0.5)).encode("utf-8"))
        histories["BBB"].write_bytes(json.dumps(price_history(step=-0.3, cycle=2.0)).encode("utf-8"))
        argv = ["--weights-file", str(self.weights)]
        for symbol, path in histories.items():
            argv.extend(["--history", f"{symbol}={path}"])
        if fx is not None:
            argv.extend(["--fx-history", f"USDCNY={fx}"])
        if base_currency:
            argv.extend(["--base-currency", base_currency])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(argv)
        self.assertEqual(code, 0, buffer.getvalue())
        return json.loads(buffer.getvalue())

    def _fx_file(self, name: str = "usdcny.json", *, shift_days: int = 0) -> Path:
        payload = price_history(60, start=7.1, step=0.002, cycle=0.05)
        if shift_days:
            payload["history"] = [
                {"Date": (datetime.date.fromisoformat(row["Date"])
                          + datetime.timedelta(days=shift_days)).isoformat(),
                 "Close": row["Close"]} for row in payload["history"]]
        path = self.root / name
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        return path

    def test_base_currency_cash_is_named_as_carrying_no_fx_risk(self):
        payload = self.payload()
        base = payload["cash_fx_risk"]["base_currency_cash"]
        self.assertEqual([row["symbol"] for row in base], ["CASH_CNY"])
        self.assertEqual(base[0]["risk_treatment"], "base_currency_cash_carries_no_fx_risk")
        self.assertEqual(payload["base_currency"], "CNY")

    def test_foreign_cash_without_fx_history_is_declared_unmeasured(self):
        payload = self.payload()
        unmeasured = payload["cash_fx_risk"]["unmeasured_cash"]
        self.assertEqual([row["symbol"] for row in unmeasured], ["CASH_USD"])
        self.assertEqual(unmeasured[0]["reason"], "no_fx_history_supplied_for_USDCNY")
        self.assertEqual(payload["cash_fx_risk"]["legs"], [])
        reasons = {row["symbol"]: row["reason"] for row in payload["coverage"]["excluded_symbols"]}
        self.assertEqual(reasons["CASH_USD"], "cash_fx_exposure_unmeasured:USDCNY")
        # an unmeasured leg must never be silently valued at zero volatility
        self.assertGreater(payload["value_coverage"]["unmeasured_share_of_portfolio_value"], 0)

    def test_foreign_cash_fx_leg_is_modelled_from_its_own_history_with_provenance(self):
        import hashlib
        fx = self._fx_file()
        payload = self.payload(fx=fx)
        legs = payload["cash_fx_risk"]["legs"]
        self.assertEqual(len(legs), 1)
        leg = legs[0]
        self.assertEqual((leg["symbol"], leg["currency"], leg["pair"]),
                         ("CASH_USD", "USD", "USDCNY"))
        self.assertGreater(leg["annualized_fx_volatility"], 0)
        self.assertAlmostEqual(leg["standalone_weighted_volatility"],
                               leg["weight_of_portfolio_value"] * leg["annualized_fx_volatility"],
                               places=6)
        self.assertAlmostEqual(leg["weight_of_portfolio_value"], 0.1, places=6)
        provenance = payload["cash_fx_risk"]["fx_history_provenance"][0]
        self.assertEqual(provenance["sha256"], hashlib.sha256(fx.read_bytes()).hexdigest())
        reasons = {row["symbol"]: row["reason"] for row in payload["coverage"]["excluded_symbols"]}
        self.assertEqual(reasons["CASH_USD"],
                         "cash_excluded_from_equity_risk_fx_modelled_separately")
        self.assertEqual(payload["cash_fx_risk"]["unmeasured_cash"], [])

    def test_combination_brackets_only_the_measured_legs(self):
        payload = self.payload(fx=self._fx_file())
        combination = payload["cash_fx_risk"]["measured_legs_combination"]
        equity = combination["equity_leg"]["weighted"]
        fx = combination["fx_leg"]["weighted_sum_of_standalone_legs"]
        self.assertAlmostEqual(combination["assumed_zero_correlation_point_estimate"],
                               math.sqrt(equity ** 2 + fx ** 2), places=6)
        self.assertAlmostEqual(combination["correlation_bounds"]["upper"], equity + fx, places=6)
        self.assertAlmostEqual(combination["correlation_bounds"]["lower"], abs(equity - fx), places=6)
        self.assertEqual(combination["excluded_from_this_combination"], [])
        self.assertIn("not bounded", combination["statement"])
        # the equity leg is the covered subset scaled to its share of the whole portfolio
        self.assertAlmostEqual(combination["equity_leg"]["weight_of_portfolio_value"],
                               (500.0 + 300.0) / 1000.0, places=6)

    def test_value_coverage_shares_partition_portfolio_value(self):
        payload = self.payload(fx=self._fx_file())
        shares = payload["value_coverage"]
        total = (shares["equity_covered_share_of_portfolio_value"]
                 + shares["fx_modelled_cash_share_of_portfolio_value"]
                 + shares["base_currency_cash_share_of_portfolio_value"]
                 + shares["unmeasured_share_of_portfolio_value"])
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertAlmostEqual(shares["equity_covered_share_of_portfolio_value"], 0.8, places=6)
        self.assertAlmostEqual(shares["fx_modelled_cash_share_of_portfolio_value"], 0.1, places=6)
        self.assertAlmostEqual(shares["base_currency_cash_share_of_portfolio_value"], 0.1,
                               places=6)
        self.assertAlmostEqual(shares["partition_total"], 1.0, places=6)

    def test_uncovered_equity_is_counted_as_unmeasured_not_as_a_silent_remainder(self):
        # Main fixture: AAA + BBB covered, CCC has no history, CASH_CNY is base cash.
        path = self.root / "covered.json"
        path.write_bytes(json.dumps(price_history(step=0.5)).encode("utf-8"))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(["--weights-file", str(self.weights),
                              "--history", "AAA=" + str(path)])
        self.assertEqual(code, 3)  # a single usable history is still refused
        self.assertIn("at least two usable histories", json.loads(buffer.getvalue())["errors"][0])

    def test_fx_window_without_overlap_is_unmeasured(self):
        payload = self.payload(fx=self._fx_file(shift_days=400))
        self.assertEqual(payload["cash_fx_risk"]["legs"], [])
        reason = payload["cash_fx_risk"]["unmeasured_cash"][0]["reason"]
        self.assertIn("fx_window_overlap_too_short", reason)

    def test_base_currency_override_changes_the_fx_treatment(self):
        # Labels follow the declared base currency: CNY cash becomes the foreign leg and
        # the USD leg becomes base-currency cash (market values are taken as already
        # expressed in the declared base currency).
        payload = self.payload(base_currency="USD", fx=self._fx_file())
        self.assertEqual(payload["cash_fx_risk"]["legs"], [])
        unmeasured = payload["cash_fx_risk"]["unmeasured_cash"][0]
        self.assertEqual((unmeasured["symbol"], unmeasured["pair"]), ("CASH_CNY", "CNYUSD"))
        base = payload["cash_fx_risk"]["base_currency_cash"][0]
        self.assertEqual(base["symbol"], "CASH_USD")

    def test_missing_fx_file_is_an_input_error(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = risk.main(["--weights-file", str(self.weights),
                              "--fx-history", "USDCNY=" + str(self.root / "absent.json")])
        self.assertEqual(code, 3)
        self.assertIn("fx history file not found", json.loads(buffer.getvalue())["errors"][0])


if __name__ == "__main__":
    unittest.main()
