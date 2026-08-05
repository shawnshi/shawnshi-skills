import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import quality_screener


class QualityPointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "profile_version": "test",
            "applicable_markets": ["US"],
            "applicable_asset_types": ["stock"],
            "thresholds": {"roe_avg": {"min": 0.08}},
        }

    def test_historical_cutoff_fails_closed_before_provider_fetch(self):
        with patch.object(quality_screener, "fetch_yf_data") as fetch:
            result = quality_screener.evaluate_ticker(
                "AAPL",
                "quality_equity",
                self.profile,
                market="US",
                asset_type="stock",
                as_of_date="2026-07-31",
                now=datetime(2026, 8, 5, tzinfo=timezone.utc),
            )

        fetch.assert_not_called()
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(
            result["detail_status"], "point_in_time_snapshot_unavailable"
        )
        self.assertFalse(result["historical_replay_allowed"])
        self.assertIn("filed_at or announced_at", result["reason"])

    def test_future_cutoff_remains_invalid_before_provider_fetch(self):
        with patch.object(quality_screener, "fetch_yf_data") as fetch:
            result = quality_screener.evaluate_ticker(
                "AAPL",
                "quality_equity",
                self.profile,
                market="US",
                asset_type="stock",
                as_of_date="2026-08-06",
                now=datetime(2026, 8, 5, tzinfo=timezone.utc),
            )

        fetch.assert_not_called()
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertTrue(
            any("cannot be after retrieved_at" in error for error in result["applicability_errors"])
        )


if __name__ == "__main__":
    unittest.main()
