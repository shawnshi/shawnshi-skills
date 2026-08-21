import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import daily_sync
from portfolio_loader import load_positions
from quote_evidence_contract import build_portfolio_snapshot_binding


NOW_EPOCH = 1_800_000_000.0


def positions_payload():
    return {
        "base_currency": "CNY",
        "exchange_rates": {"USD": 7.2},
        "positions": [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "quantity": 2,
                "avg_cost": 100.0,
                "currency": "USD",
                "market": "US",
                "asset_type": "stock",
            },
            {
                "symbol": "159516.SZ",
                "name": "半导体设备ETF国泰",
                "quantity": 100,
                "avg_cost": 0.737,
                "currency": "CNY",
                "market": "CN",
                "asset_type": "etf",
            },
            {
                "symbol": "CASH_CNY",
                "name": "人民币现金",
                "quantity": 1_000,
                "avg_cost": 1.0,
                "currency": "CNY",
                "market": "CASH",
                "asset_type": "cash",
            },
            {
                "symbol": "VOO",
                "name": "inactive audit record",
                "quantity": 0,
                "avg_cost": 600.0,
                "currency": "USD",
                "market": "US",
                "asset_type": "etf",
            },
        ],
    }


def quote_record(
    symbol,
    *,
    price,
    currency,
    exchange,
    quote_type,
    quote_epoch=NOW_EPOCH - 60,
):
    return {
        "query": symbol,
        "symbol": symbol,
        "summary": {"last_close": round(price, 2)},
        "info": {
            "symbol": symbol,
            "regularMarketPrice": price,
            "exchange": exchange,
            "currency": currency,
            "quoteType": quote_type,
            "regularMarketTime": quote_epoch,
            "marketState": "CLOSED",
        },
        "data_sources": {
            "price": "Yahoo Finance",
            "price_locator": f"yfinance:{symbol}:quote",
        },
        "portfolio_context": {
            "position_status": "matched",
            "current_price": price,
            "currency": currency,
        },
    }


def quote_records():
    return [
        quote_record(
            "AAPL",
            price=110.1234,
            currency="USD",
            exchange="NMS",
            quote_type="EQUITY",
        ),
        quote_record(
            "159516.SZ",
            price=0.751,
            currency="CNY",
            exchange="SHZ",
            quote_type="EQUITY",
        ),
    ]


def supplied_audit(**overrides):
    audit = {
        "requested_count": 2,
        "result_record_count": 2,
        "resolved_symbol_count": 2,
        "unique_resolved_symbol_count": 2,
        "quote_success_count": 2,
        "portfolio_matched_count": 2,
        "quote_contract_matched_count": 2,
        "returned_symbols": ["AAPL", "159516.SZ"],
        "quote_failed_symbols": [],
        "quote_contract_failures": {},
        "result_error_symbols": [],
        "stale_quote_symbols": [],
        "unmatched_symbols": [],
        "duplicate_requested_symbols": [],
        "expected_active_symbols": ["159516.SZ", "AAPL"],
        "missing_requested_symbols": [],
        "unexpected_requested_symbols": [],
        "coverage_complete": True,
        "portfolio_load_status": "ok",
        "portfolio_load_error": None,
        "strict_quote_contract": True,
        "complete": True,
        "status": "complete",
    }
    audit.update(overrides)
    return audit


class DailySyncTestCase(unittest.TestCase):
    def write_inputs(self, root, *, positions=None, quotes=None):
        positions_value = positions if positions is not None else positions_payload()
        positions_path = Path(root) / "positions.json"
        quotes_path = Path(root) / "quotes.json"
        positions_path.write_text(
            json.dumps(positions_value),
            encoding="utf-8",
        )
        quotes_value = (
            copy.deepcopy(quotes)
            if quotes is not None
            else {
                "records": quote_records(),
                "portfolio_batch_audit": supplied_audit(),
            }
        )
        if (
            isinstance(quotes_value, dict)
            and isinstance(quotes_value.get("portfolio_batch_audit"), dict)
            and "portfolio_snapshot_binding"
            not in quotes_value["portfolio_batch_audit"]
        ):
            quotes_value["portfolio_batch_audit"]["portfolio_snapshot_binding"] = (
                build_portfolio_snapshot_binding(load_positions(str(positions_path)))
            )
        quotes_path.write_text(
            json.dumps(quotes_value),
            encoding="utf-8",
        )
        return positions_path, quotes_path

    def write_thesis_evidence(
        self,
        root,
        positions_path,
        *,
        conclusions=None,
        omit_symbol=None,
        wrong_binding=False,
    ):
        def stamp(epoch):
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()

        binding = build_portfolio_snapshot_binding(load_positions(str(positions_path)))
        if wrong_binding:
            binding = copy.deepcopy(binding)
            binding["sha256"] = "0" * 64
        evidence_items = []
        for index, evidence_id in enumerate(
            ["macro", "sector", "regulatory", "aapl", "159516"]
        ):
            evidence_items.append(
                {
                    "evidence_id": evidence_id,
                    "source_tier": "regulator" if index < 3 else "exchange",
                    "source_locator": f"https://example.com/{evidence_id}",
                    "published_at": stamp(NOW_EPOCH - 120),
                    "retrieved_at": stamp(NOW_EPOCH - 30),
                    "content_sha256": format(index + 1, "064x"),
                    "claim": f"Primary-source coverage for {evidence_id}",
                }
            )
        conclusions = conclusions or {}
        assessments = []
        for symbol, evidence_id in (("AAPL", "aapl"), ("159516.SZ", "159516")):
            if symbol == omit_symbol:
                continue
            assessments.append(
                {
                    "symbol": symbol,
                    "conclusion": conclusions.get(
                        symbol, "no_fatal_breach_verified"
                    ),
                    "rationale": f"Assessment for {symbol}",
                    "evidence_ids": [evidence_id],
                }
            )
        payload = {
            "schema_version": "pia_thesis_red_team_v1",
            "generated_at": stamp(NOW_EPOCH - 10),
            "window_start": stamp(NOW_EPOCH - 86_400),
            "window_end": stamp(NOW_EPOCH - 60),
            "portfolio_snapshot_binding": binding,
            "scope_coverage": {
                scope: {"status": "complete", "evidence_ids": [scope]}
                for scope in ("macro", "sector", "regulatory")
            },
            "assessments": assessments,
            "evidence_items": evidence_items,
        }
        path = Path(root) / "thesis-evidence.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def evaluate(self, positions_path, quotes_path, thesis_evidence_path=None):
        return daily_sync.evaluate_daily_sync(
            positions_file=str(positions_path),
            quotes_file=str(quotes_path),
            thesis_evidence_file=(
                str(thesis_evidence_path) if thesis_evidence_path else None
            ),
            now_epoch=NOW_EPOCH,
        )


class CompleteOfflineSyncTests(DailySyncTestCase):
    def test_complete_package_is_deterministic_and_excludes_cash_and_inactive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir)
            first = self.evaluate(positions_path, quotes_path)
            second = self.evaluate(positions_path, quotes_path)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "incomplete")
        self.assertTrue(first["completeness"]["complete"])
        self.assertEqual(first["requested"], 2)
        self.assertEqual(first["succeeded"], 2)
        self.assertEqual(first["matched"], 2)
        self.assertEqual(
            first["completeness"]["expected_symbols"],
            ["AAPL", "159516.SZ"],
        )
        self.assertEqual(
            [item["symbol"] for item in first["quote_snapshot"]],
            ["AAPL", "159516.SZ"],
        )
        self.assertEqual(first["quote_snapshot"][0]["current_price"], 110.1234)
        self.assertEqual(
            first["quote_snapshot"][0]["source_locator"],
            "yfinance:AAPL:quote",
        )
        self.assertEqual(first["thesis_red_team"]["status"], "not_assessed")
        self.assertEqual(
            first["thesis_red_team"]["evidence_status"],
            "insufficient_evidence",
        )
        self.assertIn("thesis_red_team_incomplete", first["errors"])
        self.assertEqual(
            first["input_bindings"]["portfolio_snapshot"]["active_position_count"],
            3,
        )
        self.assertEqual(
            len(first["input_bindings"]["portfolio_snapshot"]["sha256"]), 64
        )
        self.assertEqual(len(first["input_bindings"]["quote_package"]["sha256"]), 64)
        self.assertEqual(len(first["input_bindings"]["quote_snapshot"]["sha256"]), 64)

    def test_primary_evidence_package_can_complete_the_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir)
            evidence_path = self.write_thesis_evidence(tmpdir, positions_path)
            report = self.evaluate(positions_path, quotes_path, evidence_path)

        self.assertEqual(report["status"], "complete")
        self.assertTrue(report["completeness"]["complete"])
        self.assertTrue(report["completeness"]["thesis_assessment_complete"])
        self.assertEqual(report["thesis_red_team"]["status"], "complete")
        self.assertEqual(
            report["thesis_red_team"]["fatal_event_status"],
            "no_fatal_breach_verified",
        )
        self.assertEqual(
            len(report["input_bindings"]["thesis_evidence"]["sha256"]), 64
        )

    def test_fatal_breach_is_complete_and_preserves_the_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir)
            evidence_path = self.write_thesis_evidence(
                tmpdir,
                positions_path,
                conclusions={"AAPL": "fatal_breach"},
            )
            report = self.evaluate(positions_path, quotes_path, evidence_path)

        self.assertEqual(report["status"], "complete")
        self.assertEqual(
            report["thesis_red_team"]["fatal_event_status"],
            "fatal_breach_detected",
        )
        self.assertEqual(report["thesis_red_team"]["fatal_symbols"], ["AAPL"])

    def test_inline_repeated_batch_audit_is_rejected(self):
        records = quote_records()
        audit = supplied_audit()
        for record in records:
            record["portfolio_batch_audit"] = copy.deepcopy(audit)
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(
                tmpdir,
                quotes={"records": records, "portfolio_batch_audit": audit},
            )
            report = self.evaluate(positions_path, quotes_path)

        self.assertEqual(report["status"], "incomplete")
        self.assertIn(
            "inline_portfolio_batch_audit_not_allowed",
            report["stages"][1]["errors"],
        )


class FailClosedOfflineSyncTests(DailySyncTestCase):
    def test_thesis_evidence_rejects_non_primary_stale_or_unbound_references(self):
        def mutate_non_primary(payload):
            payload["evidence_items"][0]["source_tier"] = "secondary"

        def mutate_stale(payload):
            stale = datetime.fromtimestamp(
                NOW_EPOCH - 7_200, tz=timezone.utc
            ).isoformat()
            payload["window_end"] = stale

        def mutate_unknown_reference(payload):
            payload["assessments"][0]["evidence_ids"] = ["missing"]

        for mutate in (
            mutate_non_primary,
            mutate_stale,
            mutate_unknown_reference,
        ):
            with self.subTest(mutate=mutate.__name__), tempfile.TemporaryDirectory() as tmpdir:
                positions_path, quotes_path = self.write_inputs(tmpdir)
                evidence_path = self.write_thesis_evidence(tmpdir, positions_path)
                payload = json.loads(evidence_path.read_text(encoding="utf-8"))
                mutate(payload)
                evidence_path.write_text(json.dumps(payload), encoding="utf-8")
                report = self.evaluate(positions_path, quotes_path, evidence_path)

            self.assertEqual(report["status"], "incomplete")
            self.assertFalse(
                report["completeness"]["thesis_assessment_complete"]
            )
            self.assertTrue(report["thesis_red_team"]["errors"])

    def test_thesis_evidence_requires_exact_symbol_coverage_and_binding(self):
        cases = (
            {"omit_symbol": "AAPL"},
            {"wrong_binding": True},
        )
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmpdir:
                positions_path, quotes_path = self.write_inputs(tmpdir)
                evidence_path = self.write_thesis_evidence(
                    tmpdir,
                    positions_path,
                    **options,
                )
                report = self.evaluate(positions_path, quotes_path, evidence_path)

            self.assertEqual(report["status"], "incomplete")
            self.assertFalse(
                report["completeness"]["thesis_assessment_complete"]
            )
            self.assertTrue(report["thesis_red_team"]["errors"])

    def test_supplied_audit_must_bind_the_same_normalized_portfolio_snapshot(self):
        wrong = positions_payload()
        wrong["positions"][0]["quantity"] = 99
        audit = supplied_audit(
            portfolio_snapshot_binding=build_portfolio_snapshot_binding(wrong)
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(
                tmpdir,
                quotes={
                    "records": quote_records(),
                    "portfolio_batch_audit": audit,
                },
            )
            report = self.evaluate(positions_path, quotes_path)

        self.assertFalse(report["completeness"]["complete"])
        self.assertIn(
            "portfolio_batch_audit.portfolio_snapshot_binding_mismatch",
            report["stages"][2]["supplied_audit_errors"],
        )

    def test_missing_duplicate_extra_and_unmatched_universe_fail(self):
        cases = {}
        missing = quote_records()[:1]
        cases["missing"] = missing
        duplicate = quote_records()
        duplicate.append(copy.deepcopy(duplicate[0]))
        cases["duplicate"] = duplicate
        extra = quote_records()
        extra.append(
            quote_record(
                "MSFT",
                price=500,
                currency="USD",
                exchange="NMS",
                quote_type="EQUITY",
            )
        )
        cases["extra"] = extra
        unmatched = quote_records()
        unmatched[0]["portfolio_context"]["position_status"] = "not_found"
        cases["unmatched"] = unmatched

        for name, records in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                positions_path, quotes_path = self.write_inputs(
                    tmpdir,
                    quotes={
                        "records": records,
                        "portfolio_batch_audit": supplied_audit(),
                    },
                )
                report = self.evaluate(positions_path, quotes_path)
                self.assertEqual(report["status"], "incomplete")
                self.assertFalse(report["completeness"]["complete"])

    def test_identity_currency_type_time_and_record_errors_fail(self):
        mutations = [
            ("currency", lambda r: r[0]["info"].update(currency="CNY")),
            ("exchange", lambda r: r[0]["info"].update(exchange="SHH")),
            ("type", lambda r: r[0]["info"].update(quoteType="ETF")),
            (
                "source",
                lambda r: r[0]["data_sources"].update(
                    price="arbitrary-nonempty-source"
                ),
            ),
            (
                "locator_missing",
                lambda r: r[0]["data_sources"].pop("price_locator"),
            ),
            (
                "locator_mismatch",
                lambda r: r[0]["data_sources"].update(
                    price_locator="yfinance:MSFT:quote"
                ),
            ),
            (
                "stale",
                lambda r: r[0]["info"].update(
                    regularMarketTime=NOW_EPOCH - 8 * 24 * 60 * 60
                ),
            ),
            ("errors", lambda r: r[0].update(errors=["partial provider response"])),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                records = quote_records()
                mutate(records)
                positions_path, quotes_path = self.write_inputs(
                    tmpdir,
                    quotes={
                        "records": records,
                        "portfolio_batch_audit": supplied_audit(),
                    },
                )
                report = self.evaluate(positions_path, quotes_path)
                self.assertEqual(report["status"], "incomplete")
                self.assertFalse(report["completeness"]["identity_complete"])

    def test_missing_or_incomplete_supplied_audit_fails_even_with_good_records(self):
        packages = [
            {"records": quote_records()},
            {
                "records": quote_records(),
                "portfolio_batch_audit": supplied_audit(
                    complete=False, status="incomplete"
                ),
            },
        ]
        for package in packages:
            with self.subTest(package=package), tempfile.TemporaryDirectory() as tmpdir:
                positions_path, quotes_path = self.write_inputs(tmpdir, quotes=package)
                report = self.evaluate(positions_path, quotes_path)
                self.assertEqual(report["status"], "incomplete")
                self.assertFalse(report["completeness"]["supplied_audit_complete"])

    def test_cli_failure_is_parseable_json_and_nonzero(self):
        package = {
            "records": quote_records()[:1],
            "portfolio_batch_audit": supplied_audit(),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir, quotes=package)
            output = io.StringIO()
            argv = [
                "daily_sync.py",
                "--positions-file",
                str(positions_path),
                "--quotes-file",
                str(quotes_path),
                "--now-epoch",
                str(NOW_EPOCH),
            ]
            with (
                patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                daily_sync.main()

        report = json.loads(output.getvalue())
        self.assertNotEqual(exit_context.exception.code, 0)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["thesis_red_team"]["status"], "not_assessed")

    def test_cli_invalid_json_is_structured_and_uses_input_error_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir)
            quotes_path.write_text("{", encoding="utf-8")
            output = io.StringIO()
            argv = [
                "daily_sync.py",
                "--positions-file",
                str(positions_path),
                "--quotes-file",
                str(quotes_path),
                "--now-epoch",
                str(NOW_EPOCH),
            ]
            with (
                patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                daily_sync.main()

        report = json.loads(output.getvalue())
        self.assertEqual(exit_context.exception.code, 2)
        self.assertEqual(report["status"], "invalid_input")
        self.assertTrue(report["errors"][0].startswith("quotes_file_json_error"))

    def test_missing_cli_arguments_also_emit_stable_json(self):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["daily_sync.py"]),
            contextlib.redirect_stdout(output),
            self.assertRaises(SystemExit) as exit_context,
        ):
            daily_sync.main()

        report = json.loads(output.getvalue())
        self.assertEqual(exit_context.exception.code, 2)
        self.assertEqual(report["status"], "invalid_input")
        self.assertTrue(report["errors"][0].startswith("argument_error:"))


if __name__ == "__main__":
    unittest.main()
