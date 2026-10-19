"""Phase two offline persistence, identity and observable-time tests."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pia_daily as pd
import pia_refresh as pr
import process_budget as pb
from test_p2_daily_run_pipeline import positions_payload


class CommitTests(unittest.TestCase):
    def test_summary_failed_replace_keeps_original(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root/'out/daily_run_summary.json'
            target.parent.mkdir(); target.write_text('{"status":"incomplete"}')
            before = target.read_bytes()
            with mock.patch('os.replace', side_effect=OSError('synthetic replace failure')):
                with self.assertRaises(OSError):
                    pd.write_run_summary(root, {'status': 'failed'})
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(target.parent.glob('*.tmp')), [])

    def test_refresh_failed_replace_keeps_original(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'derived.json'; target.write_bytes(b'old')
            with mock.patch('os.replace', side_effect=OSError('synthetic replace failure')):
                with self.assertRaises(OSError): pr.write_new_file(target, {'fresh': True}, True)
            self.assertEqual(target.read_bytes(), b'old')

    def test_previous_snapshot_is_byte_recoverable_and_failure_precedes_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); out = root/'out'; out.mkdir()
            (out/'daily_run_summary.json').write_bytes(b'{"status":"incomplete"}')
            (out/'weights.json').write_bytes(b'old weights')
            previous = pd.capture_previous_run(root)
            assert isinstance(previous, dict)
            manifest = json.loads(Path(previous['recovery_manifest']).read_text())
            row = next(x for x in manifest['files'] if x['path'] == 'out/weights.json')
            self.assertEqual(Path(row['snapshot']).read_bytes(), b'old weights')
            (out/'daily_run_summary.json').write_bytes(b'{"status":"failed"}')
            old = (out/'weights.json').read_bytes()
            with mock.patch('os.replace', side_effect=OSError('snapshot interrupted')):
                with self.assertRaises(OSError): pd.capture_previous_run(root)
            self.assertEqual((out/'weights.json').read_bytes(), old)


    def test_pipeline_storage_error_emits_failed_metrics_without_overwriting_summary(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root/'synthetic.json'
            source.write_text(json.dumps(positions_payload()))
            target = root/'task/out/daily_run_summary.json'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'{"status":"incomplete"}')
            buffer = io.StringIO()
            with mock.patch('os.replace', side_effect=OSError('synthetic snapshot interrupted')), contextlib.redirect_stdout(buffer):
                code = pd.main(['--positions-file', str(source), '--task-dir', str(root/'task')])
            report = json.loads(buffer.getvalue())
            self.assertEqual(code, 3)
            self.assertEqual(report['status'], 'failed')
            self.assertGreaterEqual(report['run_elapsed_seconds'], 0)
            self.assertGreaterEqual(report['stages'][-1]['stage_elapsed_seconds'], 0)
            self.assertIn('OSError', report['errors'][0])
            self.assertEqual(target.read_bytes(), b'{"status":"incomplete"}')


class MeasurementTests(unittest.TestCase):
    def test_failed_pipeline_has_monotonic_stage_and_run_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root/'synthetic.json'
            source.write_text(json.dumps(positions_payload()))
            buffer = io.StringIO()
            with mock.patch.object(pd, 'run_module', return_value=(3, {'status': 'failed', 'errors': ['synthetic']})), contextlib.redirect_stdout(buffer):
                code = pd.main(['--positions-file', str(source), '--task-dir', str(root/'task'), '--skip-watchlist'])
            report = json.loads(buffer.getvalue())
            self.assertEqual(code, 3)
            self.assertGreaterEqual(report['run_elapsed_seconds'], 0)
            self.assertGreaterEqual(report['stages'][0]['stage_elapsed_seconds'], 0)
            self.assertEqual(report['stages'][0]['request_count'], 'unknown')
            self.assertEqual(report['stages'][0]['retry_count'], 'unknown')

    def test_scope_key_is_stable_across_python_hash_seeds(self):
        command = [sys.executable, '-B', '-c', "import pia_evidence; print(pia_evidence.scope_request_key('macro','https://example.test/x'))"]
        values = []
        for seed in ('1', '2'):
            r = subprocess.run(command, env={**os.environ, 'PYTHONHASHSEED': seed}, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr); values.append(r.stdout)
        self.assertEqual(values[0], values[1])
        self.assertRegex(values[0], r'^scope_macro_[a-f0-9]{64}')

    def test_inherited_remaining_budget_never_expands_and_exhausted_does_not_spawn(self):
        import time
        import pia
        with mock.patch.dict(os.environ, {pb.DEADLINE_ENV: str(time.monotonic() + 10)}):
            self.assertLessEqual(pb.remaining_seconds(900), 8.1)
        with mock.patch.dict(os.environ, {pb.DEADLINE_ENV: str(time.monotonic() - 1)}), mock.patch.object(pia.subprocess, 'Popen') as spawn:
            with self.assertRaises(subprocess.TimeoutExpired): pia._execute_child(['must-not-run'])
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
