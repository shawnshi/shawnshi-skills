"""Exercise bounded insight through real, task-isolated SQLite reads."""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import garmin_bounded as bounded
import garmin_sqlite_adapter as adapter


def create_database(path):
    day = datetime.now().date().isoformat()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE daily_summary (day TEXT, rhr REAL, hr_max REAL, stress_avg REAL, bb_max REAL, bb_charged REAL, bb_min REAL, sweat_loss REAL, rr_waking_avg REAL, steps REAL)')
        connection.execute('INSERT INTO daily_summary VALUES (?, 60, 100, 25, 80, 40, 20, 0, 14, 3000)', (day,))
        connection.execute('CREATE TABLE sleep (day TEXT, total_sleep REAL, deep_sleep REAL, light_sleep REAL, rem_sleep REAL, awake REAL, score REAL, avg_rr REAL, avg_spo2 REAL, avg_stress REAL)')
        connection.execute('INSERT INTO sleep VALUES (?, 27000, 5000, 16000, 6000, 300, 80, 14, 98, 20)', (day,))
        connection.execute('CREATE TABLE hrv (day TEXT, last_night_avg REAL, status TEXT)')
        connection.execute('INSERT INTO hrv VALUES (?, 42, "BALANCED")', (day,))
        connection.commit()


class BoundedReadIntegrityTests(unittest.TestCase):
    def test_real_bounded_read_exposes_verified_integrity_and_exact_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'garmin.db'
            create_database(database)
            with patch.object(adapter, 'GARMIN_DB', database), patch.object(bounded, '_load_local_adapter', return_value=adapter):
                result = bounded.fetch_local_summary(1)
            self.assertEqual(result['data_integrity']['status'], 'verified_unchanged')
            self.assertEqual(result['_accessed_days'], 1)
            self.assertEqual(result['sleep'][0]['sleep_time_seconds'], 27000)
            self.assertIsNone(adapter._PINNED_DATABASES.get())

    def test_real_cli_keeps_integrity_receipt_in_public_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'garmin.db'
            create_database(database)
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(adapter, 'GARMIN_DB', database), patch.object(bounded, '_load_local_adapter', return_value=adapter), redirect_stdout(stdout), redirect_stderr(stderr):
                rc = bounded.main(['insight_cn', '--days', '1', '--source', 'local', '--allow-health-data'])
            self.assertEqual(rc, 0, stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result['data_integrity']['status'], 'verified_unchanged')
            self.assertEqual(len(result['data_integrity']['databases']), 1)
            self.assertFalse(result['provenance']['network_accessed'])
            self.assertFalse(result['provenance']['persisted'])
            self.assertNotIn(str(database), stdout.getvalue())

    def test_optional_schema_error_is_not_reported_as_missing_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'garmin.db'
            create_database(database)
            with patch.object(adapter, 'GARMIN_DB', database), patch.object(bounded, '_load_local_adapter', return_value=adapter), patch.object(adapter, 'get_sleep_data', side_effect=adapter.LocalDatabaseReadError('sleep_query_failed')):
                with self.assertRaises(adapter.LocalDatabaseReadError):
                    bounded.fetch_local_summary(1)

    def test_changed_database_blocks_cli_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'garmin.db'
            create_database(database)
            original = adapter.get_hrv_data
            def mutate(days, **kwargs):
                result = original(days, **kwargs)
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute('UPDATE daily_summary SET rhr=61')
                    connection.commit()
                return result
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(adapter, 'GARMIN_DB', database), patch.object(bounded, '_load_local_adapter', return_value=adapter), patch.object(adapter, 'get_hrv_data', side_effect=mutate), redirect_stdout(stdout), redirect_stderr(stderr):
                rc = bounded.main(['insight_cn', '--days', '1', '--source', 'local', '--allow-health-data'])
            self.assertEqual(rc, 4)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('read_error', stderr.getvalue())
            self.assertIsNone(adapter._PINNED_DATABASES.get())


if __name__ == '__main__':
    unittest.main()
