import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia  # noqa: E402
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
        self.assertAlmostEqual(result["derived"]["roe"], 0.2)
        self.assertAlmostEqual(
            result["derived"]["operating_cash_flow_per_diluted_share"], 3.0
        )

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
