import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_data
import garmin_sqlite_adapter as adapter


class ExplicitLocalWindowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.main_db = root / "garmin.db"
        self.activities_db = root / "garmin_activities.db"
        con = sqlite3.connect(self.main_db)
        con.executescript("""
            CREATE TABLE sleep (
                day TEXT PRIMARY KEY, total_sleep TEXT, score INTEGER,
                rem_sleep TEXT, deep_sleep TEXT, light_sleep TEXT, awake TEXT,
                start TEXT, end TEXT, avg_rr INTEGER, avg_spo2 INTEGER, avg_stress INTEGER
            );
            CREATE TABLE hrv (day TEXT PRIMARY KEY, last_night_avg INTEGER, status TEXT);
            CREATE TABLE daily_summary (
                day TEXT PRIMARY KEY, rhr INTEGER, hr_max INTEGER,
                stress_avg INTEGER, bb_max INTEGER, bb_min INTEGER,
                bb_charged INTEGER, sweat_loss INTEGER,
                rr_waking_avg INTEGER, steps INTEGER
            );
        """)
        for day in ("2001-01-01", "2001-01-02", "2001-01-03", "2001-01-04"):
            con.execute("INSERT INTO sleep (day, total_sleep, score, rem_sleep, deep_sleep, light_sleep, awake, start, end) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (day, "08:00:00", 80, "01:00:00", "01:00:00", "06:00:00",
                         "00:05:00", None, None))
            con.execute("INSERT INTO hrv (day, last_night_avg) VALUES (?, ?)", (day, 40))
            con.execute("INSERT INTO daily_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (day, 55, 100, 20, 80, 20, 60, 0, 12, 1000))
        con.commit()
        con.close()
        con = sqlite3.connect(self.activities_db)
        con.executescript("""
            CREATE TABLE activities (
                activity_id INTEGER, name TEXT, type TEXT, start_time TEXT,
                elapsed_time INTEGER, distance INTEGER, avg_hr INTEGER,
                max_hr INTEGER, calories INTEGER, avg_speed INTEGER,
                ascent INTEGER, training_load INTEGER
            );
        """)
        for i, day in enumerate(("2001-01-01", "2001-01-02", "2001-01-03", "2001-01-04")):
            con.execute("INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (i, "synthetic", "walking", day + " 12:00:00", 1800,
                         1000, 90, 100, 100, 1, 0, 10))
        con.commit()
        con.close()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(adapter, "GARMIN_DB", self.main_db))
        self.stack.enter_context(patch.object(adapter, "ACTIVITIES_DB", self.activities_db))
        self.stack.enter_context(patch.object(
            garmin_data, "get_client", side_effect=AssertionError("local reads must not authenticate")
        ))

    def test_historical_summary_uses_exact_inclusive_bounds(self):
        result = garmin_data._fetch_local_metric(
            "summary", 7, "2001-01-01", "2001-01-03"
        )
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["coverage"]["requested_days"], 3)
        self.assertEqual(result["data_integrity"]["status"], "verified_unchanged")
        for component in ("sleep", "hrv", "heart_rate", "body_battery", "stress", "activities"):
            with self.subTest(component=component):
                self.assertEqual({r["date"] for r in result[component]},
                                 {"2001-01-01", "2001-01-02", "2001-01-03"})
                self.assertEqual(result["component_status"][component]["observed_days"], 3)

    def test_single_day_component_queries_do_not_include_adjacent_dates(self):
        for component in ("sleep", "hrv", "heart_rate", "body_battery", "stress", "activities"):
            with self.subTest(component=component):
                result = garmin_data._fetch_local_metric(
                    component, 7, "2001-01-02", "2001-01-02"
                )
                self.assertEqual({r["date"] for r in result[component]}, {"2001-01-02"})
                self.assertEqual(result["coverage"]["requested_days"], 1)

    def test_no_observations_remain_no_data_not_fabricated_zeroes(self):
        result = garmin_data._fetch_local_metric(
            "summary", 7, "2001-01-10", "2001-01-12"
        )
        self.assertEqual(result["status"], "no_data")
        for coverage in result["component_status"].values():
            self.assertEqual(coverage["observed_days"], 0)
        for row in result["daily_summary"]:
            self.assertIsNone(row["resting_heart_rate"])
            self.assertIsNone(row["body_battery_highest"])

    def test_local_parameter_errors_are_not_database_read_errors(self):
        output = io.StringIO()
        with patch.object(garmin_data, "_fetch_local_metric", side_effect=ValueError("invalid request")), \
                patch.object(garmin_data.sys, "argv", ["garmin_data.py", "summary", "--days", "3", "--source", "local", "--allow-health-data"]), \
                contextlib.redirect_stdout(output):
            code = garmin_data.main()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "invalid_request")

    def test_default_layout_uses_populated_data_root_not_empty_legacy_files(self):
        home = Path(self.temporary.name) / "isolated-home"
        legacy = home / ".GarminDb"
        canonical = legacy / "HealthData" / "DBs"
        canonical.mkdir(parents=True)
        (legacy / "garmin.db").touch()
        shutil.copy2(self.main_db, canonical / "garmin.db")
        code = """import json, pathlib, garmin_sqlite_adapter as a
resolved = a.resolve_database_path(a.GARMIN_DB)
explicit_bad_path_rejected = False
try:
    a.resolve_database_path(pathlib.Path.home() / '.GarminDb' / 'garmin.db')
except a.LocalDatabaseReadError:
    explicit_bad_path_rejected = True
print(json.dumps({'resolved': str(resolved), 'explicit_bad_path_rejected': explicit_bad_path_rejected}))
"""
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        completed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", code],
            cwd=Path(__file__).parent, env=env, capture_output=True,
            text=True, encoding="utf8", timeout=15, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(Path(receipt["resolved"]), (canonical / "garmin.db").resolve())
        self.assertTrue(receipt["explicit_bad_path_rejected"])
        self.assertEqual((legacy / "garmin.db").stat().st_size, 0)

    def test_probe_error_keeps_its_stable_code_without_private_details(self):
        output = io.StringIO()
        with patch.object(garmin_data, "_fetch_local_metric", side_effect=adapter.LocalDatabaseReadError("database_probe_failed: invalid database file")), \
                patch.object(garmin_data.sys, "argv", ["garmin_data.py", "summary", "--source", "local", "--allow-health-data"]), \
                contextlib.redirect_stdout(output):
            code = garmin_data.main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "status": "read_error", "error_code": "database_probe_failed",
        })

    def test_schema_failure_remains_a_read_error(self):
        con = sqlite3.connect(self.main_db)
        con.execute("DROP TABLE hrv")
        con.commit()
        con.close()
        output = io.StringIO()
        with patch.object(garmin_data.sys, "argv", [
                "garmin_data.py", "hrv", "--start", "2001-01-01", "--end", "2001-01-03",
                "--source", "local", "--allow-health-data",
            ]), contextlib.redirect_stdout(output):
            code = garmin_data.main()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "read_error")
        self.assertEqual(result["error_code"], "hrv_query_failed")


if __name__ == "__main__":
    unittest.main()
