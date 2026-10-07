"""Dependency availability is independent of a particular data directory."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LocalRuntimeAvailabilityTests(unittest.TestCase):
    def test_adapter_import_succeeds_without_the_primary_database_directory(self):
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            environment = dict(os.environ)
            environment.update(HOME=temporary, USERPROFILE=temporary,
                               PYTHONPATH=os.pathsep.join((str(scripts), environment.get('PYTHONPATH', ''))),
                               PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run(
                [sys.executable, '-c', 'import garmin_intelligence as g; assert not g.DB_DIR.exists(); assert g.HAS_SQLITE'],
                env=environment, capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
