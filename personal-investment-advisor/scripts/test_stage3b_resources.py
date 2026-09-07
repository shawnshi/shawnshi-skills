"""Synthetic R09/R10 projection and resource boundary regressions."""
import io
import json
import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import active_portfolio_constructor as constructor
import active_research_contract as contract
import advice_journal as journal
import alpha_validation as alpha
import pia
from test_p0p1_active_research import (
    alpha_package,
    construction_policy,
    promotion_policy,
)


def scan():
    return {'schema_version': constructor.SCAN_SCHEMA_VERSION, 'status': 'complete',
            'formal_use_allowed': True, 'as_of': construction_policy()['as_of'],
            'rankings': [{'symbol': 'AAA', 'robust_expected_excess_return_annualized': .07},
                         {'symbol': 'BBB', 'robust_expected_excess_return_annualized': .025}]}


class InputCapacityTests(unittest.TestCase):
    def test_append_input_threshold_and_growth_before_json_decode(self):
        with mock.patch.object(journal, 'MAX_APPEND_INPUT_BYTES', 2):
            with mock.patch.object(Path, 'open', return_value=io.BytesIO(b'{}')):
                self.assertEqual(journal._read_append_input('synthetic'), {})
            with mock.patch.object(Path, 'open', return_value=io.BytesIO(b'{} ')), mock.patch.object(journal.json, 'loads') as decode:
                with self.assertRaisesRegex(ValueError, 'journal_append_input_size_limit'):
                    journal._read_append_input('synthetic')
                decode.assert_not_called()

    def test_append_cli_input_limit_and_invalid_input_preserve_destination(self):
        code = f'import sys; sys.path.insert(0, {str(Path(journal.__file__).parent)!r}); import advice_journal as j; j.MAX_APPEND_INPUT_BYTES=32; j.main()'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'dashboard.json'
            target = root/'new'/'journal.jsonl'
            invocation = [sys.executable, '-B', '-c', code, 'append', str(source), '--journal-path', str(target)]
            for payload in (b'{}'+b' '*31, b'{'):
                source.write_bytes(payload)
                completed = subprocess.run(invocation, capture_output=True, text=True, check=False, timeout=8)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(target.parent.exists())
                self.assertEqual(source.read_bytes(), payload)
            target.parent.mkdir()
            original = b'{"entry_id":"synthetic-existing"}\n'
            target.write_bytes(original)
            for payload in (b'{}'+b' '*31, b'{'):
                source.write_bytes(payload)
                completed = subprocess.run(invocation, capture_output=True, text=True, check=False, timeout=8)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(list(target.parent.iterdir()), [target])
            source.write_bytes(b'{}'+b' '*30)
            completed = subprocess.run(invocation, capture_output=True, text=True, check=False, timeout=8)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(len(journal.load_entries(str(target))), 2)

    def test_actual_32_mib_snapshot_boundary_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'synthetic.json'
            with path.open('wb') as stream:
                stream.write(b'{}')
                remaining = contract.MAX_JSON_BYTES - 2
                while remaining:
                    size = min(65536, remaining)
                    stream.write(b' '*size)
                    remaining -= size
            self.assertEqual(contract.read_json_snapshot(path, 'synthetic')[0], {})
            with path.open('ab') as stream:
                stream.write(b' ')
            with self.assertRaisesRegex(ValueError, 'size_limit'):
                contract.read_json_snapshot(path, 'synthetic')

    def test_exact_dimension_boundaries_remain_usable(self):
        with mock.patch.object(constructor, 'MAX_CONSTRUCTION_ASSETS', 2):
            report = constructor.run_construction(scan(), construction_policy(), scan_sha256='a'*64, policy_sha256='b'*64)
        self.assertEqual(report['status'], 'complete')
        with mock.patch.object(alpha, 'MAX_TRIALS', 3), mock.patch.object(alpha, 'MAX_OBSERVATIONS', 16), mock.patch.object(alpha, 'MAX_TRIAL_CELLS', 48):
            self.assertEqual(alpha.evaluate_alpha_package(alpha_package(), promotion_policy())['status'], 'complete')

    def test_journal_growth_read_checks_before_decoding(self):
        with mock.patch.object(Path, 'exists', return_value=True), mock.patch.object(Path, 'open', return_value=io.BytesIO(b'{}\n  ')), mock.patch.object(journal, 'MAX_JOURNAL_BYTES', 3), mock.patch.object(journal.json, 'loads') as decode:
            with self.assertRaisesRegex(ValueError, 'size_limit'):
                journal.load_entries('synthetic.jsonl')
            decode.assert_not_called()

    def test_journal_append_at_exact_byte_cap_is_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'journal.jsonl'
            entry = {'entry_id': 'synthetic', 'note': '值'}
            raw = (json.dumps(entry, ensure_ascii=False)+'\n').encode()
            with mock.patch.object(journal, 'MAX_JOURNAL_BYTES', len(raw)), mock.patch.object(journal, 'build_journal_entry', return_value=entry):
                journal.append_entry({}, journal_path=str(path))
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(journal.load_entries(str(path)), [entry])
                with self.assertRaisesRegex(ValueError, 'size_limit'):
                    journal.append_entry({}, journal_path=str(path))
                self.assertEqual(path.read_bytes(), raw)

    def test_snapshot_byte_boundary_and_canonical_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'input.json'
            raw = '{"值":1}'.encode()
            path.write_bytes(raw)
            with mock.patch.object(contract, 'MAX_JSON_BYTES', len(raw), create=True):
                document, digest = contract.read_json_snapshot(path, 'synthetic')
                self.assertEqual(document, {'值': 1})
                self.assertEqual(len(digest), 64)
                path.write_bytes(raw+b' ')
                with self.assertRaisesRegex(ValueError, 'size_limit'):
                    contract.read_json_snapshot(path, 'synthetic')

    def test_snapshot_growth_read_is_bounded_before_decode(self):
        stream = io.BytesIO(b'{}     ')
        with mock.patch.object(contract, 'MAX_JSON_BYTES', 4, create=True), mock.patch.object(Path, 'open', return_value=stream), mock.patch.object(contract.json, 'loads') as decode:
            with self.assertRaisesRegex(ValueError, 'size_limit'):
                contract.read_json_snapshot('synthetic', 'synthetic')
            decode.assert_not_called()

    def test_construction_dimension_rejected_before_numpy(self):
        with mock.patch.object(constructor, 'MAX_CONSTRUCTION_ASSETS', 1, create=True), mock.patch.object(constructor.np, 'asarray') as allocate:
            report = constructor.run_construction(scan(), construction_policy(), scan_sha256='a'*64, policy_sha256='b'*64)
        self.assertEqual(report['status'], 'invalid_input')
        self.assertIn('size_limit', str(report['errors']))
        allocate.assert_not_called()

    def test_actual_matrix_and_policy_dimension_caps_precede_eigensolve(self):
        for field in ('symbols', 'rows', 'columns'):
            policy = construction_policy()
            if field == 'symbols':
                policy['symbols'] = ['SYN']*251
            elif field == 'rows':
                policy['covariance']['matrix'] = [[.01]]*251
            else:
                policy['covariance']['matrix'][0] = [.01]*251
            with self.subTest(field=field), mock.patch.object(constructor.np.linalg, 'eigvalsh', side_effect=AssertionError('must not solve')):
                report = constructor.run_construction(scan(), policy, scan_sha256='a'*64, policy_sha256='b'*64)
            self.assertIn('size_limit', str(report['errors']))

    def test_journal_update_at_exact_cap_is_readable_and_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'journal.jsonl'
            entry = {'entry_id': 'synthetic', 'note': '值'}
            path.write_text(json.dumps(entry, ensure_ascii=False)+'\n', encoding='utf-8')
            expected = dict(entry, outcome_price=1, feedback_status='reviewed')
            raw = (json.dumps(expected, ensure_ascii=False)+'\n').encode()
            with mock.patch.object(journal, 'MAX_JOURNAL_BYTES', len(raw)):
                for _ in range(2):
                    journal.batch_update_outcomes({'synthetic': {'outcome_price': 1}}, journal_path=str(path))
                    self.assertEqual(path.read_bytes(), raw)
                    self.assertEqual(journal.load_entries(str(path)), [expected])

    def test_alpha_dimension_budgets_before_conversion(self):
        for name, limit in [('MAX_TRIALS', 2), ('MAX_OBSERVATIONS', 15), ('MAX_TRIAL_CELLS', 47)]:
            with self.subTest(name=name), mock.patch.object(alpha, name, limit, create=True), mock.patch.object(alpha, 'finite_number', side_effect=AssertionError('converted oversized package')):
                errors, context = alpha._validate_package(alpha_package())
                self.assertIn('size_limit', str(errors))
                self.assertEqual(context, {})

    def test_alpha_trial_map_and_row_caps_ignore_ledger_mismatch(self):
        package = alpha_package()
        package['trial_net_excess_returns']['extra'] = [0.0]*16
        with mock.patch.object(alpha, 'MAX_TRIALS', 3, create=True):
            errors, _ = alpha._validate_package(package)
        self.assertIn('size_limit', str(errors))
        package = alpha_package()
        package['trial_net_excess_returns']['selected'] *= 2
        with mock.patch.object(alpha, 'MAX_OBSERVATIONS', 16, create=True):
            errors, _ = alpha._validate_package(package)
        self.assertIn('size_limit', str(errors))

    def test_journal_load_append_update_boundaries_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'journal.jsonl'
            entry = {'entry_id': 'synthetic'}
            raw = (json.dumps(entry)+'\n').encode()
            path.write_bytes(raw)
            with mock.patch.object(journal, 'MAX_JOURNAL_BYTES', len(raw), create=True):
                self.assertEqual(journal.load_entries(str(path)), [entry])
                with self.assertRaisesRegex(ValueError, 'size_limit'):
                    journal.append_entry({}, journal_path=str(path))
                self.assertEqual(path.read_bytes(), raw)
                with self.assertRaisesRegex(ValueError, 'size_limit'):
                    journal.batch_update_outcomes({'synthetic': {'outcome_price': 1}}, journal_path=str(path))
                self.assertEqual(path.read_bytes(), raw)
                with journal._journal_lock(path, timeout_seconds=.1):
                    pass
                path.write_bytes(raw+b' ')
                with self.assertRaisesRegex(ValueError, 'size_limit'):
                    journal.load_entries(str(path))
            self.assertFalse(list(Path(directory).glob('*.tmp')))


class PiaCapacityTests(unittest.TestCase):
    def run_script(self, source, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'child.py'
            script.write_text(source, encoding='utf-8')
            with mock.patch.object(pia, '_child_script', return_value=script):
                return pia._run_child(public_command='synthetic', script_name='child.py', child_arguments=[], completion_scope='test', **kwargs)

    def test_nonblocking_capability_failure_does_not_spawn(self):
        with mock.patch.object(pia.os, 'set_blocking', side_effect=NotImplementedError('synthetic unavailable')), mock.patch.object(pia.subprocess, 'Popen') as spawn:
            report, code = self.run_script('raise AssertionError("must not execute")')
        self.assertNotEqual(code, 0)
        self.assertEqual(report['detail_status'], 'child_transport_unavailable')
        spawn.assert_not_called()

    def test_below_and_exact_caps_unicode_chunk_and_partial_bytes(self):
        for size in (63, 64):
            stdout = json.dumps({'status': 'complete', 'note': '值'}, ensure_ascii=False).encode()
            stdout += b' '*(size-len(stdout))
            with self.subTest(size=size), mock.patch.object(pia, 'MAX_CHILD_STREAM_BYTES', 64), mock.patch.object(pia, 'CHILD_READ_BYTES', 1):
                report, code = self.run_script(f'import sys; sys.stdout.buffer.write({stdout!r}); sys.stderr.buffer.write(b"x"*{size})')
            self.assertEqual(code, 0, report)
            self.assertEqual(report['result']['note'], '值')
        # Preserve prior errors=replace decoding, but only after full bounded bytes.
        report, code = self.run_script('import sys; sys.stdout.buffer.write(b\'{"status":"complete","note":"\\xe5"}\')')
        self.assertEqual(code, 0, report)
        self.assertEqual(report['result']['note'], '\ufffd')

    def test_exit_after_would_block_does_not_drop_final_output(self):
        process = mock.Mock()
        process.stdout.fileno.return_value = 100
        process.stderr.fileno.return_value = 101
        process.poll.side_effect = [None, 0, 0, 0]
        process.returncode = 0
        reads = [BlockingIOError(), BlockingIOError(), b'{"status":"complete"}', b'', b'']
        with mock.patch.object(pia, '_check_nonblocking_pipes'), mock.patch.object(pia.subprocess, 'Popen', return_value=process) as spawn, mock.patch.object(pia.os, 'set_blocking'), mock.patch.object(pia.os, 'read', side_effect=reads):
            result = pia._execute_child(['synthetic'])
        self.assertFalse(spawn.call_args.kwargs['shell'])
        self.assertEqual(Path(spawn.call_args.kwargs['cwd']), pia.SCRIPT_DIR)
        self.assertEqual(json.loads(result.stdout)['status'], 'complete')
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_exited_child_does_not_wait_for_inherited_open_pipe(self):
        process = mock.Mock()
        process.poll.return_value = 0
        process.returncode = 0
        with mock.patch.object(pia, '_check_nonblocking_pipes'), mock.patch.object(pia.subprocess, 'Popen', return_value=process), mock.patch.object(pia.os, 'set_blocking'), mock.patch.object(pia.os, 'read', side_effect=BlockingIOError), mock.patch.object(pia.time, 'sleep') as sleep:
            result = pia._execute_child(['synthetic'])
        self.assertEqual(result.stdout, '')
        sleep.assert_not_called()
        process.wait.assert_not_called()

    def test_cleanup_escalates_once_to_kill_and_wait(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('synthetic', 1), 0]
        pia._reap_child(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertTrue(all(call.kwargs['timeout'] == 1 for call in process.wait.call_args_list))

    def test_valid_json_prefix_cannot_mask_oversize_failure(self):
        with mock.patch.object(pia, 'MAX_CHILD_STREAM_BYTES', 64):
            report, code = self.run_script('import sys; sys.stdout.write(\'{"status":"complete"}\'+" "*65); sys.exit(3)')
        self.assertNotEqual(code, 0)
        self.assertEqual(report['detail_status'], 'child_output_size_limit')
        self.assertIsNone(report.get('result'))

    def test_malformed_and_nonzero_failures_are_not_partial_success(self):
        report, code = self.run_script('print("not-json")')
        self.assertNotEqual(code, 0)
        self.assertEqual(report['detail_status'], 'child_output_invalid')
        report, code = self.run_script('import sys; print(\'{"status":"complete"}\'); sys.stderr.write("synthetic failure"); sys.exit(3)')
        self.assertNotEqual(code, 0)
        self.assertEqual(report['route']['child_exit_code'], 3)

    def test_timeout_cap_and_cancel_reap_exact_child(self):
        original_popen = subprocess.Popen
        for mode in ('timeout', 'cap', 'cancel'):
            processes = []
            def spawn(*args, owned=processes, **kwargs):
                process = original_popen(*args, **kwargs)
                owned.append(process)
                return process
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                script = Path(directory)/'child.py'
                source = 'import time; time.sleep(20)'
                if mode == 'cap':
                    source = 'import sys,time; sys.stderr.buffer.write(b"x"*65); sys.stderr.flush(); time.sleep(20)'
                script.write_text(source)
                start = time.monotonic()
                with mock.patch.object(pia.subprocess, 'Popen', side_effect=spawn), mock.patch.object(pia, 'MAX_CHILD_STREAM_BYTES', 64), mock.patch.object(pia, 'CHILD_TIMEOUT_SECONDS', 8 if mode == 'cap' else .5):
                    if mode == 'cancel':
                        with mock.patch.object(pia, '_check_nonblocking_pipes'), mock.patch.object(pia.os, 'read', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                            pia._execute_child([sys.executable, str(script)])
                    else:
                        error = subprocess.TimeoutExpired if mode == 'timeout' else pia.ChildOutputLimitError
                        with self.assertRaises(error):
                            pia._execute_child([sys.executable, str(script)])
                self.assertLess(time.monotonic()-start, 10 if mode == 'cap' else 3)
                self.assertEqual(len(processes), 1)
                self.assertIsNotNone(processes[0].poll())
                self.assertTrue(processes[0].stdout.closed)
                self.assertTrue(processes[0].stderr.closed)

    def test_required_artifacts_verified_independently_and_json_file_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'report.json'
            source = f'from pathlib import Path; Path({str(path)!r}).write_text(\'{{"status":"complete"}}\'); print("written")'
            report, code = self.run_script(source, output_mode='json_file', required_output=path)
            self.assertEqual(code, 0, report)
            before = path.read_bytes()
            report, code = self.run_script('print("written")', output_mode='json_file', required_output=path)
            self.assertNotEqual(code, 0)
            self.assertEqual(path.read_bytes(), before)
            with mock.patch.object(pia, 'MAX_CHILD_STREAM_BYTES', 64):
                report, code = self.run_script(f'from pathlib import Path; Path({str(path)!r}).write_text(" "*65)', output_mode='json_file', required_output=path)
            self.assertNotEqual(code, 0)
            self.assertIn('size_limit', str(report['errors']))
            text = Path(directory)/'report.md'
            report, code = self.run_script('print("written")', output_mode='text', required_output=text)
            self.assertNotEqual(code, 0)
            report, code = self.run_script(f'from pathlib import Path; Path({str(text)!r}).write_text("synthetic"); print("written")', output_mode='text', required_output=text)
            self.assertEqual(code, 0, report)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['report.json', 'report.md'])

    def test_stdout_and_stderr_caps_including_exit_race(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'child.py'
            for stream in ('stdout', 'stderr'):
                script.write_text(f'import sys; sys.{stream}.buffer.write(b"x"*65); sys.{stream}.flush()')
                with self.subTest(stream=stream), mock.patch.object(pia, '_child_script', return_value=script), mock.patch.object(pia, 'MAX_CHILD_STREAM_BYTES', 64, create=True):
                    report, code = pia._run_child(public_command='synthetic', script_name='child.py', child_arguments=[], completion_scope='test')
                self.assertNotEqual(code, 0)
                self.assertEqual(report['detail_status'], 'child_output_size_limit')
                self.assertIn(stream, str(report['errors']))
                self.assertIsNone(report.get('result'))


class ProjectionTests(unittest.TestCase):
    def test_seeded_projection_matches_fixed_iteration_reference(self):
        rng = np.random.default_rng(309)
        for count in (2, 10, 50, 100, 250):
            for case in range(12):
                center = rng.dirichlet(np.ones(count))
                lower = center*rng.uniform(0, 1, count)
                upper = center+(1-center)*rng.uniform(0, 1, count)
                values = rng.normal(0, 2, count)
                if case == 0:
                    lower = upper = center.copy()
                left = float(np.min(values-upper))-1
                right = float(np.max(values-lower))+1
                for _ in range(200):
                    midpoint = (left+right)/2
                    if np.clip(values-midpoint, lower, upper).sum() > 1:
                        left = midpoint
                    else:
                        right = midpoint
                expected = np.clip(values-(left+right)/2, lower, upper)
                result = constructor._bounded_simplex_projection(values, lower, upper)
                with self.subTest(count=count, case=case):
                    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-12)
                    self.assertLessEqual(abs(result.sum()-1), 1e-10)
                    self.assertTrue(np.all(result >= lower-1e-10))
                    self.assertTrue(np.all(result <= upper+1e-10))

    def test_projection_stops_before_fixed_200_clips(self):
        with mock.patch.object(constructor.np, 'clip', wraps=np.clip) as clip:
            result = constructor._bounded_simplex_projection(np.array([.7, .4]), np.array([.1, .1]), np.array([.9, .9]))
        self.assertLess(clip.call_count, 100)
        np.testing.assert_allclose(result, [.65, .35], atol=1e-12, rtol=0)


if __name__ == '__main__':
    unittest.main()
