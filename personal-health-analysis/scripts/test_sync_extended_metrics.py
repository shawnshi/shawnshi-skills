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

            mock_client.get_fitnessage_data.return_value = {
                "chronologicalAge": 42,
                "fitnessAge": 40.3,
                "achievableFitnessAge": 36.3,
                "previousFitnessAge": 40.3,
                "components": {
                    "bmi": {"value": 26.6, "targetValue": 21.3, "potentialAge": 38.8},
                    "vigorousMinutesAvg": {"value": 0.5, "targetValue": 75.0, "potentialAge": 39.0},
                    "vigorousDaysAvg": {"value": 0.0, "targetValue": 3.0},
                    "rhr": {"value": 55},
                },
                "lastUpdated": "2026-10-23T00:00:00.0",
            }
            fa_res = syncer.sync_fitness_age_range(
                mock_client, syncer.date(2026, 10, 25), conn, cache_dir=Path(tmp)
            )
            self.assertEqual(fa_res["records_inserted"], 1)

            mock_client.get_endurance_score.return_value = {
                "enduranceScoreDTO": {
                    "calendarDate": "2026-10-25",
                    "overallScore": 4876,
                    "classification": 1,
                    "feedbackPhrase": "30",
                    "contributors": [{"activityTypeId": 37, "contribution": 90.57}],
                }
            }
            es_res = syncer.sync_endurance_score_range(
                mock_client, "2026-10-01", "2026-10-25", conn, cache_dir=Path(tmp)
            )
            self.assertEqual(es_res["records_inserted"], 1)

            mock_client.get_body_battery_events.return_value = [
                {
                    "event": {
                        "eventType": "RECOVERY",
                        "eventStartTimeGmt": "2026-10-24T10:00:00.0",
                        "durationInMilliseconds": 3600000,
                        "bodyBatteryImpact": 5,
                        "shortFeedback": "LONG_RESTFUL_PERIOD",
                    },
                    "averageStress": 12.5,
                    "activityName": None,
                }
            ]
            bbe_res = syncer.sync_body_battery_events_range(
                mock_client, syncer.date(2026, 10, 24), syncer.date(2026, 10, 24), conn, cache_dir=Path(tmp)
            )
            self.assertEqual(bbe_res["records_inserted"], 1)

            mock_client.get_respiration_data.return_value = {
                "highestRespirationValue": 24.0,
                "lowestRespirationValue": 8.0,
                "wakingAvg": 15.0,
                "latestRespirationValue": 14.0,
            }
            dr_res = syncer.sync_daily_respiration_range(
                mock_client, syncer.date(2026, 10, 24), syncer.date(2026, 10, 24), conn, cache_dir=Path(tmp)
            )
            self.assertEqual(dr_res["records_inserted"], 1)

            # Check DB rows
            bp_row = conn.execute("SELECT * FROM blood_pressure WHERE day='2026-10-25'").fetchone()
            self.assertIsNotNone(bp_row)
            self.assertEqual(bp_row[3], 126)  # systolic
            self.assertEqual(bp_row[4], 89)   # diastolic

            tr_row = conn.execute("SELECT * FROM training_readiness WHERE day='2026-10-25'").fetchone()
            self.assertIsNotNone(tr_row)
            self.assertEqual(tr_row[3], 100)  # score
            self.assertEqual(tr_row[4], "PRIME")

            fa_row = conn.execute("SELECT * FROM fitness_age WHERE day='2026-10-25'").fetchone()
            self.assertIsNotNone(fa_row)
            self.assertEqual(fa_row[1], 42)    # chronological_age
            self.assertEqual(fa_row[2], 40.3)  # fitness_age

            es_row = conn.execute("SELECT * FROM endurance_score WHERE day='2026-10-25'").fetchone()
            self.assertIsNotNone(es_row)
            self.assertEqual(es_row[1], 4876)  # overall_score

            bbe_row = conn.execute("SELECT * FROM body_battery_events WHERE day='2026-10-24'").fetchone()
            self.assertIsNotNone(bbe_row)
            self.assertEqual(bbe_row[2], "RECOVERY")
            self.assertEqual(bbe_row[5], 5)    # body_battery_impact

            dr_row = conn.execute("SELECT * FROM daily_respiration WHERE day='2026-10-24'").fetchone()
            self.assertIsNotNone(dr_row)
            self.assertEqual(dr_row[1], 24.0)  # highest_respiration
            self.assertEqual(dr_row[2], 8.0)   # lowest_respiration

            conn.close()


if __name__ == "__main__":
    unittest.main()
