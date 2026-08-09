import sqlite3
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import garmin_sqlite_adapter as adapter


def _create_database(path, statements):
    connection = sqlite3.connect(path)
    try:
        for statement, parameters in statements:
            connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


class MissingObservationContractTests(unittest.TestCase):
    def test_direct_adapter_entrypoint_is_rejected_without_reading_databases(self):
        output = io.StringIO()
        with (
            patch.object(
                adapter,
                "get_summary",
                side_effect=AssertionError("direct entrypoint must not read data"),
            ),
            patch("sys.stdout", output),
        ):
            rc = adapter.main()

        self.assertEqual(rc, 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "status": "unsupported_entrypoint",
                "error_code": "use_verified_health_cli",
            },
        )

    def test_schema_errors_fail_closed_with_machine_readable_codes(self):
        with tempfile.TemporaryDirectory() as temp_root:
            database = Path(temp_root) / "garmin.db"
            _create_database(database, [("CREATE TABLE unrelated (value INTEGER)", ())])

            with patch.object(
                adapter,
                "get_connection",
                side_effect=lambda _path: sqlite3.connect(database),
            ):
                for reader, expected_code in (
                    (adapter.get_summary, "summary_query_failed"),
                    (adapter.get_sleep_data, "sleep_query_failed"),
                    (adapter.get_hrv_data, "hrv_query_failed"),
                    (
                        adapter.get_daily_friction_matrix,
                        "friction_activity_query_failed",
                    ),
                ):
                    with self.subTest(reader=reader.__name__), self.assertRaisesRegex(
                        adapter.LocalDatabaseReadError,
                        expected_code,
                    ):
                        reader(days=1)

    def test_device_info_returns_latest_firmware_per_serial_deterministically(self):
        with tempfile.TemporaryDirectory() as temp_root:
            database = Path(temp_root) / "garmin.db"
            _create_database(
                database,
                [
                    (
                        """
                        CREATE TABLE device_info (
                            timestamp TEXT,
                            serial_number TEXT,
                            software_version TEXT
                        )
                        """,
                        (),
                    ),
                    (
                        "INSERT INTO device_info VALUES (?, ?, ?)",
                        ("2026-07-01 08:00:00", "alpha", "1.0"),
                    ),
                    (
                        "INSERT INTO device_info VALUES (?, ?, ?)",
                        ("2026-07-03 08:00:00", "alpha", "2.0"),
                    ),
                    (
                        "INSERT INTO device_info VALUES (?, ?, ?)",
                        ("2026-07-03 08:00:00", "alpha", "2.1"),
                    ),
                    (
                        "INSERT INTO device_info VALUES (?, ?, ?)",
                        ("2026-07-02 08:00:00", "beta", "9.0"),
                    ),
                ],
            )

            with patch.object(
                adapter,
                "get_connection",
                side_effect=lambda _path: sqlite3.connect(database),
            ):
                frame = adapter.get_devices_info()
                history = adapter.get_device_firmware_history()

        self.assertEqual(
            frame.to_dict("records"),
            [
                {
                    "serial_number": "alpha",
                    "software_version": "2.1",
                    "timestamp": "2026-07-03 08:00:00",
                },
                {
                    "serial_number": "beta",
                    "software_version": "9.0",
                    "timestamp": "2026-07-02 08:00:00",
                },
            ],
        )
        self.assertEqual(
            history[["serial_number", "software_version"]].to_dict("records"),
            [
                {"serial_number": "alpha", "software_version": "1.0"},
                {"serial_number": "beta", "software_version": "9.0"},
                {"serial_number": "alpha", "software_version": "2.0"},
                {"serial_number": "alpha", "software_version": "2.1"},
            ],
        )

    def test_connection_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_root:
            database = Path(temp_root) / "garmin.db"
            _create_database(database, [("CREATE TABLE sample (value INTEGER)", ())])
            connection = adapter.get_connection(database)
            try:
                connection.execute("SELECT * FROM sample").fetchall()
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("INSERT INTO sample VALUES (1)")
            finally:
                connection.close()

    def test_days_must_be_positive(self):
        with self.assertRaises(ValueError):
            adapter.get_summary(days=0)

    def test_missing_daily_summary_values_remain_nan(self):
        with tempfile.TemporaryDirectory() as temp_root:
            database = Path(temp_root) / "garmin.db"
            today = datetime.now().strftime("%Y-%m-%d")
            _create_database(
                database,
                [
                    (
                        """
                        CREATE TABLE daily_summary (
                            day TEXT, rhr REAL, hr_max REAL, stress_avg REAL,
                            bb_max REAL, bb_charged REAL, bb_min REAL,
                            sweat_loss REAL, rr_waking_avg REAL, steps REAL
                        )
                        """,
                        (),
                    ),
                    (
                        """
                        INSERT INTO daily_summary
                        VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                        """,
                        (today,),
                    ),
                ],
            )

            with patch.object(
                adapter,
                "get_connection",
                side_effect=lambda _path: sqlite3.connect(database),
            ):
                frame = adapter.get_summary(days=1)

        self.assertEqual(len(frame), 1)
        row = frame.loc[frame["date"] == today].iloc[0]
        for field in (
            "resting_heart_rate",
            "max_hr",
            "stress_avg",
            "body_battery_highest",
            "body_battery_charged",
            "body_battery_lowest",
            "sweat_loss",
            "rr_waking_avg",
            "steps",
            "high_stress_duration",
            "medium_stress_duration",
        ):
            self.assertTrue(pd.isna(row[field]), field)

    def test_missing_sleep_values_remain_nan(self):
        with tempfile.TemporaryDirectory() as temp_root:
            database = Path(temp_root) / "garmin.db"
            today = datetime.now().strftime("%Y-%m-%d")
            _create_database(
                database,
                [
                    (
                        """
                        CREATE TABLE sleep (
                            day TEXT, total_sleep TEXT, deep_sleep TEXT,
                            light_sleep TEXT, rem_sleep TEXT, awake TEXT,
                            score REAL, avg_rr REAL, avg_spo2 REAL,
                            avg_stress REAL
                        )
                        """,
                        (),
                    ),
                    (
                        """
                        INSERT INTO sleep
                        VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                        """,
                        (today,),
                    ),
                ],
            )

            with patch.object(
                adapter,
                "get_connection",
                side_effect=lambda _path: sqlite3.connect(database),
            ):
                frame = adapter.get_sleep_data(days=1)

        self.assertEqual(len(frame), 1)
        row = frame.loc[frame["date"] == today].iloc[0]
        for field in (
            "sleep_time_seconds",
            "deep_sleep_seconds",
            "light_sleep_seconds",
            "rem_sleep_seconds",
            "sleep_score",
            "avg_spo2",
            "avg_respiration",
            "avg_stress",
        ):
            self.assertTrue(pd.isna(row[field]), field)

    def test_missing_hrv_and_status_remain_nan(self):
        with tempfile.TemporaryDirectory() as temp_root:
            database = Path(temp_root) / "garmin.db"
            today = datetime.now().strftime("%Y-%m-%d")
            _create_database(
                database,
                [
                    (
                        "CREATE TABLE hrv (day TEXT, last_night_avg REAL, status TEXT)",
                        (),
                    ),
                    (
                        "INSERT INTO hrv VALUES (?, NULL, NULL)",
                        (today,),
                    ),
                ],
            )

            with patch.object(
                adapter,
                "get_connection",
                side_effect=lambda _path: sqlite3.connect(database),
            ):
                frame = adapter.get_hrv_data(days=1)

        self.assertEqual(len(frame), 1)
        row = frame.loc[frame["date"] == today].iloc[0]
        self.assertTrue(pd.isna(row["hrv_avg"]))
        self.assertTrue(pd.isna(row["status"]))

    def test_daily_friction_load_is_not_computed_without_explicit_config(self):
        with tempfile.TemporaryDirectory() as temp_root:
            activity_database = Path(temp_root) / "garmin_activities.db"
            summary_database = Path(temp_root) / "garmin.db"
            today = datetime.now().strftime("%Y-%m-%d")
            _create_database(
                activity_database,
                [
                    (
                        "CREATE TABLE activities (start_time TEXT, training_load REAL)",
                        (),
                    ),
                    (
                        "INSERT INTO activities VALUES (?, 50)",
                        (f"{today} 08:00:00",),
                    ),
                ],
            )
            _create_database(
                summary_database,
                [
                    (
                        """
                        CREATE TABLE daily_summary (
                            day TEXT, stress_avg REAL, rhr REAL,
                            bb_max REAL, bb_min REAL
                        )
                        """,
                        (),
                    ),
                    (
                        "INSERT INTO daily_summary VALUES (?, NULL, NULL, NULL, NULL)",
                        (today,),
                    ),
                ],
            )

            def open_database(path):
                selected = (
                    activity_database
                    if Path(path).name == "garmin_activities.db"
                    else summary_database
                )
                return sqlite3.connect(selected)

            with patch.object(adapter, "get_connection", side_effect=open_database):
                frame = adapter.get_daily_friction_matrix(days=1)
                with self.assertRaises(ValueError):
                    adapter.get_daily_friction_matrix(
                        days=1,
                        derivation_config={
                            "input_field": "training_load",
                            "scale": 1,
                        },
                    )
                configured_frame = adapter.get_daily_friction_matrix(
                    days=1,
                    derivation_config={
                        "input_field": "training_load",
                        "scale": 2,
                        "provenance": {
                            "source_type": "method_assumption",
                            "source": "unit-test configuration",
                            "published_at": "2026-07-28",
                            "retrieved_at": "2026-07-28",
                            "region": "test",
                            "population": "synthetic",
                            "intended_use": "regression_test",
                        },
                    },
                )

        row = frame.loc[frame["date"] == today].iloc[0]
        configured_row = configured_frame.loc[
            configured_frame["date"] == today
        ].iloc[0]
        self.assertEqual(row["training_load"], 50)
        self.assertTrue(pd.isna(row["daily_friction_load"]))
        self.assertTrue(pd.isna(row["stress_avg"]))
        self.assertTrue(pd.isna(row["resting_heart_rate"]))
        self.assertEqual(configured_row["daily_friction_load"], 100)


if __name__ == "__main__":
    unittest.main()
