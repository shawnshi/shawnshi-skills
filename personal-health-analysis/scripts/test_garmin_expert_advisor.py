"""Unit tests for garmin_expert_advisor using synthetic temporary SQLite databases."""

from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
import sqlite3
import tempfile
import unittest
from pathlib import Path

import garmin_expert_advisor as advisor


class GarminExpertAdvisorTests(unittest.TestCase):
    def _create_synthetic_dbs(self, root: Path) -> Path:
        g_path = root / "garmin.db"
        m_path = root / "garmin_monitoring.db"
        a_path = root / "garmin_activities.db"

        with closing(sqlite3.connect(g_path)) as g, g:
            g.executescript(
                """
                CREATE TABLE devices (
                    serial_number INTEGER PRIMARY KEY,
                    manufacturer TEXT,
                    product TEXT
                );
                CREATE TABLE device_info (
                    timestamp TEXT,
                    serial_number INTEGER,
                    software_version TEXT
                );
                CREATE TABLE daily_summary (
                    day TEXT PRIMARY KEY,
                    rhr INTEGER,
                    hr_max INTEGER,
                    stress_avg INTEGER,
                    steps INTEGER,
                    moderate_activity_time TEXT,
                    vigorous_activity_time TEXT,
                    bb_max INTEGER,
                    bb_min INTEGER,
                    bb_charged INTEGER,
                    spo2_avg REAL,
                    spo2_min REAL,
                    rr_waking_avg REAL,
                    calories_active INTEGER
                );
                CREATE TABLE resting_hr (
                    day TEXT PRIMARY KEY,
                    resting_heart_rate REAL
                );
                CREATE TABLE sleep (
                    day TEXT PRIMARY KEY,
                    start TEXT,
                    end TEXT,
                    total_sleep TEXT,
                    deep_sleep TEXT,
                    light_sleep TEXT,
                    rem_sleep TEXT,
                    awake TEXT,
                    score INTEGER,
                    qualifier TEXT,
                    avg_spo2 REAL,
                    avg_rr REAL,
                    avg_stress REAL
                );
                CREATE TABLE hrv (
                    day TEXT PRIMARY KEY,
                    weekly_avg INTEGER,
                    last_night_avg INTEGER,
                    last_night_5min_high INTEGER,
                    baseline_low INTEGER,
                    baseline_upper INTEGER,
                    status TEXT
                );
                CREATE TABLE sleep_events (
                    timestamp TEXT,
                    event TEXT,
                    duration TEXT
                );
                CREATE TABLE stress (
                    timestamp TEXT PRIMARY KEY,
                    stress INTEGER
                );
                CREATE TABLE weight (
                    day TEXT PRIMARY KEY,
                    weight REAL
                );
                """
            )
            g.execute("INSERT INTO devices VALUES (1234567890, 'Garmin', 'Fenix')")
            anchor = date(2026, 10, 24)
            for i in range(14):
                d = anchor - timedelta(days=13 - i)
                d_str = d.isoformat()
                prev_str = (d - timedelta(days=1)).isoformat()
                g.execute(
                    "INSERT INTO device_info VALUES (?, 1234567890, '18.32')",
                    (f"{d_str} 07:00:00",),
                )
                g.execute(
                    "INSERT INTO daily_summary VALUES (?, 54, 120, 26, 6500, '00:15:00', '00:05:00', 82, 28, 54, 97.0, 93.0, 15.0, 400)",
                    (d_str,),
                )
                g.execute("INSERT INTO resting_hr VALUES (?, 54.0)", (d_str,))
                g.execute(
                    "INSERT INTO sleep VALUES (?, ?, ?, '07:30:00', '01:45:00', '04:00:00', '01:45:00', '00:05:00', 86, 'GOOD', 97.0, 14.0, 17.0)",
                    (d_str, f"{prev_str} 23:15:00", f"{d_str} 06:45:00"),
                )
                g.execute(
                    "INSERT INTO hrv VALUES (?, 40, 43, 65, 34, 48, 'BALANCED')",
                    (d_str,),
                )
                g.execute(
                    "INSERT INTO sleep_events VALUES (?, 'deep_sleep', '01:00:00')",
                    (f"{prev_str} 23:45:00",),
                )
                g.execute(
                    "INSERT INTO sleep_events VALUES (?, 'awake', '00:05:00')",
                    (f"{d_str} 04:00:00",),
                )
                g.execute(
                    "INSERT INTO stress VALUES (?, 28), (?, 15)",
                    (f"{d_str} 14:00:00", f"{d_str} 21:30:00"),
                )

        with closing(sqlite3.connect(m_path)) as m, m:
            m.execute("CREATE TABLE monitoring_hrv_value (timestamp TEXT, hrv REAL)")
            for idx in range(10):
                hrv_val = 36.0 if idx < 5 else 46.0
                m.execute(
                    "INSERT INTO monitoring_hrv_value VALUES (?, ?)",
                    (f"2026-10-23 15:{20 + idx * 5:02d}:00", hrv_val),
                )

        with closing(sqlite3.connect(a_path)) as a, a:
            a.executescript(
                """
                CREATE TABLE activities (
                    activity_id TEXT PRIMARY KEY,
                    start_time TEXT,
                    sport TEXT,
                    sub_sport TEXT,
                    elapsed_time TEXT,
                    avg_hr INTEGER,
                    max_hr INTEGER,
                    training_load REAL,
                    training_effect REAL,
                    anaerobic_training_effect REAL,
                    hrz_1_time TEXT,
                    hrz_2_time TEXT,
                    hrz_3_time TEXT,
                    hrz_4_time TEXT,
                    hrz_5_time TEXT
                );
                CREATE TABLE steps_activities (
                    activity_id TEXT PRIMARY KEY,
                    vo2_max REAL
                );
                """
            )
            a.execute(
                "INSERT INTO activities VALUES ('1', '2026-10-22 18:00:00', 'running', 'street', '00:40:00', 135, 155, 65.0, 3.1, 0.5, '00:05:00', '00:25:00', '00:10:00', '00:00:00', '00:00:00')"
            )
            a.execute("INSERT INTO steps_activities VALUES ('1', 46.5)")

        return root

    def test_requires_explicit_health_data_authorization(self):
        code = advisor.main(["--days", "7"])
        self.assertEqual(code, 2)

    def test_builds_multi_horizon_baselines_intranight_hrv_and_playbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._create_synthetic_dbs(Path(tmp))
            result = advisor.build_expert_advisory(
                days=7, end_date=date(2026, 10, 24), db_dir=root
            )
        self.assertEqual(result["schema"], "garmin-expert-advisor.v1")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["medical_interpretation"])
        self.assertTrue(result["device_epoch_provenance"]["single_primary_device_confirmed"])
        self.assertEqual(result["data_integrity"]["status"], "verified_unchanged")
        latest_rec = result["window_daily_records"][-1]
        self.assertIsNotNone(latest_rec["intra_night_hrv"])
        self.assertEqual(latest_rec["intra_night_hrv"]["intra_night_hrv_slope"], 10.0)
        self.assertEqual(
            result["cardiorespiratory_and_activity_load"]["latest_vo2_max"], 46.5
        )
        self.assertTrue(len(result["detected_phenotypes"]) >= 1)
        self.assertIn("4_n_of_1_verification_targets", result["management_playbook"])


if __name__ == "__main__":
    unittest.main()
