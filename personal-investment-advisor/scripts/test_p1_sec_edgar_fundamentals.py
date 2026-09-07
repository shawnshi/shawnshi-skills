import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia  # noqa: E402
import sec_edgar_fundamentals as sec  # noqa: E402
from sec_edgar_fundamentals import (  # noqa: E402
    extract_company_snapshot,
    parse_as_of,
    validate_user_agent,
)


SHA = "a" * 64
AS_OF = datetime(2023, 6, 30, 23, 59, 59, tzinfo=timezone.utc)


def duration_fact(value, unit, *, filed="2023-02-15", accession="0000000000-23-000001"):
    return {
        "start": "2022-01-01",
        "end": "2022-12-31",
        "val": value,
        "filed": filed,
        "form": "10-K",
        "accn": accession,
        "unit": unit,
    }


def companyfacts_fixture():
    return {
        "cik": 1234,
        "entityName": "Free Data Corp",
        "facts": {
            "us-gaap": {
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            duration_fact(2.0, "USD/shares"),
                            duration_fact(
                                2.5,
                                "USD/shares",
                                filed="2024-02-15",
                                accession="0000000000-24-000001",
                            ),
                        ]
                    }
                },
                "NetIncomeLoss": {"units": {"USD": [duration_fact(200.0, "USD")]}},
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": [duration_fact(300.0, "USD")]}
                },
                "WeightedAverageNumberOfDilutedSharesOutstanding": {
                    "units": {"shares": [duration_fact(100.0, "shares")]}
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {
                                "end": "2022-12-31",
                                "val": 1000.0,
                                "filed": "2023-02-15",
                                "form": "10-K",
                                "accn": "0000000000-23-000001",
                            }
                        ]
                    }
                },
            }
        },
    }


class SecEdgarFundamentalTests(unittest.TestCase):
    def test_as_of_filters_later_amendment_and_computes_ratios(self):
        result = extract_company_snapshot(
            companyfacts_fixture(),
            symbol="FREE",
            as_of=AS_OF,
            source_locator="https://data.sec.gov/api/xbrl/companyfacts/CIK0000001234.json",
            content_sha256=SHA,
            retrieved_at=AS_OF,
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["facts"]["diluted_eps"]["value"], 2.0)
        self.assertEqual(result["facts"]["diluted_eps"]["filed"], "2023-02-15")
        self.assertNotIn("roe", result["derived"])
        self.assertAlmostEqual(result["derived"]["net_income_to_period_end_equity"], 0.2)
        self.assertAlmostEqual(
            result["derived"]["operating_cash_flow_per_diluted_share"], 3.0
        )

    def snapshot(self, payload=None, as_of=AS_OF):
        return extract_company_snapshot(
            companyfacts_fixture() if payload is None else payload,
            symbol="FREE", as_of=as_of, source_locator="dataset://sec-synthetic",
            content_sha256=SHA, retrieved_at=datetime.now(timezone.utc),
        )

    def test_date_only_keeps_date_granularity_and_accepts_today(self):
        today = datetime.now(timezone.utc).date()
        cutoff = parse_as_of(today.isoformat())
        self.assertIs(type(cutoff), date)
        with mock.patch.object(sec, "validate_user_agent", return_value="synthetic-contact"), mock.patch.object(sec, "build_report", return_value={"status": "complete"}) as build, mock.patch.object(sys, "argv", ["sec", "FREE", "--as-of", today.isoformat()]), mock.patch("builtins.print"):
            self.assertEqual(sec.main(), 0)
        self.assertEqual(build.call_args.kwargs["as_of"], today)
        result = self.snapshot(as_of=cutoff)
        self.assertEqual(result["as_of"], today.isoformat())
        self.assertEqual(result["availability_granularity"], "filed_date")
        self.assertFalse(result["cutoff_day_complete"])

    def test_future_date_and_datetime_rejected_before_fetch(self):
        now = datetime.now(timezone.utc)
        for cutoff in ((now.date() + timedelta(days=1)).isoformat(), (now + timedelta(days=1)).isoformat()):
            with self.subTest(cutoff=cutoff), mock.patch.object(sec, "validate_user_agent", return_value="synthetic-contact"), mock.patch.object(sec, "build_report") as build, mock.patch.object(sys, "argv", ["sec", "FREE", "--as-of", cutoff]), mock.patch("builtins.print"):
                self.assertEqual(sec.main(), 2)
                build.assert_not_called()

    def test_datetime_excludes_same_utc_day_filed_without_acceptance_times(self):
        day = self.snapshot(as_of=parse_as_of("2023-02-15"))
        instant = self.snapshot(as_of=parse_as_of("2023-02-15T08:00:00Z"))
        offset = self.snapshot(as_of=parse_as_of("2023-02-16T01:00:00+02:00"))
        self.assertEqual(day["status"], "complete")
        for result in (instant, offset):
            self.assertEqual(result["status"], "insufficient_evidence")
            self.assertEqual(result["availability_granularity"], "filed_date_before_cutoff_day")
            self.assertIsNone(result["facts"]["net_income"])
        self.assertEqual(self.snapshot(as_of=parse_as_of("2023-02-16T00:00:00Z"))["status"], "complete")

    def test_equity_ratio_rejects_currency_year_and_quarter_mismatch(self):
        for mismatch in ("currency", "year", "quarter", "currency_and_year"):
            with self.subTest(mismatch=mismatch):
                payload = companyfacts_fixture()
                gaap = payload["facts"]["us-gaap"]
                if "currency" in mismatch:
                    gaap["NetIncomeLoss"]["units"]["EUR"] = gaap["NetIncomeLoss"]["units"].pop("USD")
                if "year" in mismatch:
                    fact = next(iter(gaap["NetIncomeLoss"]["units"].values()))[0]
                    fact.update(start="2021-01-01", end="2021-12-31")
                if mismatch == "quarter":
                    gaap["StockholdersEquity"]["units"]["USD"][0].update(end="2023-03-31", filed="2023-05-15", form="10-Q")
                result = self.snapshot(payload)
                self.assertEqual(result["status"], "insufficient_evidence")
                self.assertNotIn("roe", result["derived"])
                self.assertNotIn("net_income_to_period_end_equity", result["derived"])
                self.assertIn("net_income_to_period_end_equity", result["unavailable_derivations"])
                self.assertIsNotNone(result["facts"]["net_income"])
                self.assertEqual(result["derived"]["operating_cash_flow_per_diluted_share"], 3.0)

    def test_cash_flow_per_share_rejects_misaligned_period_or_units(self):
        for mismatch in ("year", "start", "shares_unit", "cash_unit"):
            with self.subTest(mismatch=mismatch):
                payload = companyfacts_fixture()
                gaap = payload["facts"]["us-gaap"]
                shares = gaap["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]
                if mismatch == "year":
                    shares["shares"][0].update(start="2021-01-01", end="2021-12-31")
                elif mismatch == "start":
                    shares["shares"][0]["start"] = "2022-02-01"
                elif mismatch == "shares_unit":
                    shares["USD"] = shares.pop("shares")
                else:
                    cash = gaap["NetCashProvidedByUsedInOperatingActivities"]["units"]
                    cash["shares"] = cash.pop("USD")
                result = self.snapshot(payload)
                self.assertEqual(result["status"], "insufficient_evidence")
                self.assertNotIn("operating_cash_flow_per_diluted_share", result["derived"])
                self.assertIn("operating_cash_flow_per_diluted_share", result["unavailable_derivations"])
                self.assertEqual(result["derived"]["net_income_to_period_end_equity"], 0.2)

    def test_nonpositive_denominators_are_explicitly_unavailable(self):
        payload = companyfacts_fixture()
        gaap = payload["facts"]["us-gaap"]
        gaap["StockholdersEquity"]["units"]["USD"][0]["val"] = 0
        gaap["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"][0]["val"] = -1
        result = self.snapshot(payload)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["derived"], {})
        self.assertEqual(len(result["unavailable_derivations"]), 2)

    def test_missing_required_fact_is_insufficient_evidence(self):
        payload = companyfacts_fixture()
        del payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]
        result = extract_company_snapshot(
            payload,
            symbol="FREE",
            as_of=AS_OF,
            source_locator="https://data.sec.gov/api/xbrl/companyfacts/CIK0000001234.json",
            content_sha256=SHA,
            retrieved_at=AS_OF,
        )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn("operating_cash_flow", result["missing_facts"])

    def test_user_agent_and_as_of_are_fail_closed(self):
        self.assertEqual(
            validate_user_agent("PIA research investor@domain.cn"),
            "PIA research investor@domain.cn",
        )
        with self.assertRaises(ValueError):
            validate_user_agent("PIA research contact@example.com")
        with self.assertRaises(ValueError):
            parse_as_of("2023-06-30T12:00:00")

    def test_stable_router_exposes_free_edgar_snapshot(self):
        parser = pia._build_parser()
        args = parser.parse_args(
            [
                "edgar-fundamentals",
                "AAPL",
                "MSFT",
                "--as-of",
                "2023-06-30",
                "--user-agent",
                "PIA research investor@domain.cn",
            ]
        )
        with mock.patch.object(pia, "_run_child", return_value=({}, 0)) as run:
            pia._dispatch(args)
        self.assertEqual(run.call_args.kwargs["script_name"], "sec_edgar_fundamentals.py")
        self.assertEqual(
            run.call_args.kwargs["child_arguments"],
            [
                "AAPL",
                "MSFT",
                "--as-of",
                "2023-06-30",
                "--user-agent",
                "PIA research investor@domain.cn",
            ],
        )


if __name__ == "__main__":
    unittest.main()
