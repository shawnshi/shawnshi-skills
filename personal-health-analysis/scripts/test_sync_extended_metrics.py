"""Unit tests for sync_extended_metrics using synthetic data and mocked API."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

import sync_extended_metrics as syncer


class SyncExtendedMetricsTests(unittest.TestCase):
    def test_dry_run_requires_no_network_and_no_db_write(self):
        code = syncer.main(["--dry-run", "--start", "2026-10-01", "--end", "2026-10-25"])
        self.assertEqual(code, 0)

    def test_missing_network_authorization_fails_closed(self):
        code = syncer.main(["--start", "2026-10-01", "--end", "2026-10-25"])
        self.assertEqual(code, 3)

    def test_sync_blood_pressure_and_readiness_into_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "garmin.db"
            conn = sqlite3.connect(db_file)
            syncer._init_extended_tables(conn)

            # Test Mock client
            mock_client = Mock()
            mock_client.get_blood_pressure.return_value = {
                "measurementSummaries": [
                    {
                        "startDate": "2026-10-25",
                        "measurements": [
                            {
                                "systolic": 126,
                                "diastolic": 89,
                                "pulse": 63,
                                "category": "STAGE_1_HIGH",
                                "categoryName": "STAGE_1_HIGH",
                                "sourceType": "MANUAL",
                                "measurementTimestampLocal": "2026-10-25T10:55:36.0",
                                "measurementTimestampGMT": "2026-10-25T02:55:36.0",
                                "version": 1792896943745,
                            }
                        ],
                    }
                ]
            }
            mock_client.get_morning_training_readiness.return_value = {
                "score": 100,
                "level": "PRIME",
                "feedbackShort": "READY_FOR_ACTION",
                "feedbackLong": "PRIME_RT_HIGHEST",
                "recoveryTime": 1,
                "recoveryTimeFactorPercent": 99,
                "recoveryTimeFactorFeedback": "GOOD",
                "sleepScore": 82,
                "sleepScoreFactorPercent": 82,
                "sleepScoreFactorFeedback": "GOOD",
                "acwrFactorPercent": 100,
                "acwrFactorFeedback": "VERY_GOOD",
                "acuteLoad": 0,
                "hrvFactorPercent": 100,
                "hrvFactorFeedback": "VERY_GOOD",
                "hrvWeeklyAverage": 40,
                "stressHistoryFactorPercent": 85,
                "stressHistoryFactorFeedback": "EXCELLENT",
                "sleepHistoryFactorPercent": 80,
                "sleepHistoryFactorFeedback": "GOOD",
                "validSleep": True,
                "timestampLocal": "2026-10-25T07:42:00.0",
                "timestamp": "2026-10-24T23:42:00.0",
            }

            bp_res = syncer.sync_blood_pressure_range(
                mock_client, "2026-10-25", "2026-10-25", conn, cache_dir=Path(tmp)
            )
            self.assertEqual(bp_res["records_inserted"], 1)

            tr_res = syncer.sync_training_readiness_range(
                mock_client,
                syncer.date(2026, 10, 25),
                syncer.date(2026, 10, 25),
                conn,
                cache_dir=Path(tmp),
            )
            self.assertEqual(tr_res["records_inserted"], 1)

            # Check DB rows
            bp_row = conn.execute("SELECT * FROM blood_pressure WHERE day='2026-10-25'").fetchone()
            self.assertIsNotNone(bp_row)
            self.assertEqual(bp_row[3], 126)  # systolic
            self.assertEqual(bp_row[4], 89)   # diastolic

            tr_row = conn.execute("SELECT * FROM training_readiness WHERE day='2026-10-25'").fetchone()
            self.assertIsNotNone(tr_row)
            self.assertEqual(tr_row[3], 100)  # score
            self.assertEqual(tr_row[4], "PRIME")

            conn.close()


if __name__ == "__main__":
    unittest.main()
