"""Use synthetic databases only; corrupt storage must never become no_data."""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import garmin_sqlite_adapter as adapter


class DatabaseResolutionStabilityTests(unittest.TestCase):
    def test_corrupt_database_does_not_fall_through_to_another_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            corrupt = Path(temporary) / 'garmin.db'
            corrupt.write_bytes(b'not a sqlite database')
            other = Path(temporary) / 'fallback.db'
            with closing(sqlite3.connect(other)) as connection:
                connection.execute('CREATE TABLE sample (value INTEGER)')
                connection.commit()
            with patch.object(adapter, '_candidate_paths', return_value=[corrupt, other]):
                with self.assertRaisesRegex(adapter.LocalDatabaseReadError, 'database_probe_failed'):
                    adapter.resolve_database_path(corrupt)

    def test_empty_and_schema_free_databases_are_read_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name, raw in [('zero.db', b''), ('schema_free.db', None)]:
                path = Path(temporary) / name
                if raw is None:
                    connection = sqlite3.connect(path)
                    connection.execute('PRAGMA user_version=1')
                    connection.close()
                else:
                    path.write_bytes(raw)
                with self.subTest(name=name), patch.object(adapter, '_candidate_paths', return_value=[path]):
                    with self.assertRaises(adapter.LocalDatabaseReadError):
                        adapter.resolve_database_path(path)

    def test_absent_database_is_distinct_from_a_read_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'absent.db'
            with patch.object(adapter, '_candidate_paths', return_value=[path]):
                with self.assertRaises(FileNotFoundError):
                    adapter.resolve_database_path(path)
            self.assertFalse(path.exists())

    def test_pinned_connection_does_not_repeat_schema_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'garmin.db'
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('CREATE TABLE sample (value INTEGER)')
                connection.commit()
            token = adapter._PINNED_DATABASES.set({path.name: path})
            original = adapter.sqlite3.connect
            try:
                with patch.object(adapter.sqlite3, 'connect', wraps=original) as connect:
                    connection = adapter.get_connection(path)
                    try:
                        self.assertEqual(connection.execute('SELECT count(*) FROM sample').fetchone(), (0,))
                    finally:
                        connection.close()
                self.assertEqual(connect.call_count, 1)
            finally:
                adapter._PINNED_DATABASES.reset(token)


if __name__ == '__main__':
    unittest.main()
