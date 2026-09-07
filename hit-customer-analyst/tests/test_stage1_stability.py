from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.common import SCRIPTS, load_module
from tests.common import runtime_tx as tx
from tests.test_letter_lifecycle import validator
from tests.test_stage1_safety import formal_bytes

initializer = load_module('init_workspace', SCRIPTS / 'init_workspace.py')
committer = load_module('stage1_stability_commit_run', SCRIPTS / 'commit_run.py')
CONTEXT_ID = 'dcx-20260826-Abcd1234'


class ConfigurationFailureTests(unittest.TestCase):
    def test_R02_validator_config_read_failures_preserve_cause(self):
        failures = (
            OSError('synthetic read failure'), PermissionError('synthetic denied'),
            FileNotFoundError('synthetic missing'),
            UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'synthetic invalid UTF-8'),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(Path, 'read_text', side_effect=failure):
                    with self.assertRaisesRegex(RuntimeError, '业务模式配置') as caught:
                        validator.load_business_profiles()
                self.assertIs(caught.exception.__cause__, failure)
        with patch.object(Path, 'read_text', return_value='{broken'):
            with self.assertRaises(RuntimeError) as caught:
                validator.load_business_profiles()
        self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)

    def test_R02_validator_config_structural_corruption_fails(self):
        for payload in ([], None, {}, {'profiles': []}, {'profiles': {}},
                        {'profiles': dict.fromkeys(validator.BUSINESS_MODES, None)}):
            with self.subTest(payload=payload):
                with patch.object(Path, 'read_text', return_value=json.dumps(payload)):
                    with self.assertRaisesRegex(RuntimeError, '业务模式配置'):
                        validator.load_business_profiles()
        self.assertEqual(set(validator.load_business_profiles()), validator.BUSINESS_MODES)

    def test_R02_matched_context_corrupt_manifest_is_not_no_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / '客户研究-示例-Abcd1234'
            manifest = workspace / tx.MANIFEST_REL
            manifest.parent.mkdir(parents=True)
            for raw in (b'{broken', b'\xff', b'[]', b'{}'):
                with self.subTest(raw=raw):
                    manifest.write_bytes(raw)
                    with self.assertRaisesRegex(initializer.InitError, '匹配context_id') as caught:
                        initializer.context_id_candidates(root, CONTEXT_ID)
                    self.assertIsInstance(caught.exception.__cause__, tx.TxError)
                    self.assertEqual(manifest.read_bytes(), raw)
            manifest.write_text('{}', encoding='utf-8')
            failure = PermissionError('synthetic denied')
            with patch.object(Path, 'read_text', side_effect=failure):
                with self.assertRaises(initializer.InitError) as caught:
                    initializer.context_id_candidates(root, CONTEXT_ID)
            self.assertIs(caught.exception.__cause__.__cause__, failure)

    def test_R02_unrelated_corrupt_workspace_does_not_block_scan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unrelated = root / '客户研究-无关-Zzzz9999' / tx.MANIFEST_REL
            unrelated.parent.mkdir(parents=True)
            unrelated.write_bytes(b'{broken')
            self.assertEqual(initializer.context_id_candidates(root, CONTEXT_ID), [])
            target = root / '客户研究-示例-Abcd1234'
            target.mkdir()
            # Legacy directory identity remains a match without a manifest.
            self.assertEqual(initializer.context_id_candidates(root, CONTEXT_ID), [target])
            self.assertEqual(unrelated.read_bytes(), b'{broken')


class ValidatorTimeoutTests(unittest.TestCase):
    def _args(self, root: Path, *extra: str):
        return initializer.build_parser().parse_args([
            '示例医院', '--output-root', str(root), '--task-timezone', 'Asia/Shanghai',
            '--route', 'research_only', '--modules', 'institution',
            '--runtime-owner', '测试负责人', *extra,
        ])

    def _assert_locks_released(self, workspace: Path):
        with tx.output_root_lock(workspace.parent, timeout=0), tx.workspace_lock(workspace, timeout=0):
            pass

    def test_R04_validator_wrappers_bound_timeout_and_utf8(self):
        for strict in (False, True):
            with self.subTest(strict=strict), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                failure = subprocess.TimeoutExpired(['validator'], 60, output=b'partial')
                with patch.object(committer, 'validate_runtime_postflight'):
                    with patch.object(subprocess, 'run', side_effect=failure) as runner:
                        callback = committer._strict_postflight if strict else initializer.validate_workspace_postflight
                        error = tx.TxError if strict else initializer.InitError
                        with self.assertRaisesRegex(error, '校验器超时') as caught:
                            callback(workspace)
                self.assertIs(caught.exception.__cause__, failure)
                options = runner.call_args.kwargs
                self.assertEqual(options['timeout'], 60.0)
                self.assertEqual(options['encoding'], 'utf-8')
                self.assertEqual(options['env']['PYTHONIOENCODING'], 'utf-8')
                self.assertEqual('--strict' in runner.call_args.args[0], strict)

    def test_R04_new_init_timeout_cleans_staging_and_releases_root_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'output'
            with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired(['validator'], 60)):
                with self.assertRaisesRegex(initializer.InitError, '校验器超时'):
                    initializer.initialize(self._args(root))
            self.assertFalse([p for p in root.iterdir() if p.is_dir()])
            with tx.output_root_lock(root, timeout=0):
                pass

    def test_R04_resume_postflight_timeout_rolls_back_and_releases_locks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'output'
            initial = initializer.initialize(self._args(root))
            workspace = Path(initial['workspace'])
            before = formal_bytes(workspace)
            real_run = subprocess.run
            timed_out = []

            def run(command, **kwargs):
                if (workspace / tx.JOURNAL_NAME).exists():
                    self.assertNotEqual(formal_bytes(workspace), before)
                    timed_out.append(command)
                    raise subprocess.TimeoutExpired(command, kwargs['timeout'])
                return real_run(command, **kwargs)

            with patch.object(subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(initializer.InitError, '校验器超时'):
                    initializer.initialize(self._args(root, '--resume', '--context-id', initial['context_id']))
            self.assertEqual(len(timed_out), 1)
            self.assertEqual(formal_bytes(workspace), before)
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
            self._assert_locks_released(workspace)
            initializer.validate_runtime_postflight(workspace)

    def test_R04_commit_postflight_timeout_rolls_back_and_releases_locks(self):
        for strict in (False, True):
            with self.subTest(strict=strict), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = Path(initializer.initialize(self._args(root / 'output'))['workspace'])
                candidate = root / 'candidate'
                candidate.mkdir()
                total = next(workspace.glob('*客户研究与拜访准备报告.md'))
                (candidate / total.name).write_bytes(total.read_bytes())
                revision, digest = tx.manifest_state(workspace)
                args = committer.build_parser().parse_args([
                    str(workspace), '--candidate-workspace', str(candidate),
                    '--expected-manifest-revision', str(revision),
                    '--expected-manifest-sha256', digest, *(['--strict'] if strict else []),
                ])
                before = formal_bytes(workspace)
                real_run = subprocess.run
                timed_out = []

                def run(command, **kwargs):
                    is_strict = '--strict' in command
                    if (workspace / tx.JOURNAL_NAME).exists() and is_strict == strict:
                        self.assertNotEqual(formal_bytes(workspace), before)
                        timed_out.append(command)
                        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
                    if is_strict:
                        # Simulate a successful strict preview; this is not
                        # approval of this synthetic planning-state workspace.
                        return subprocess.CompletedProcess(command, 0, '{"errors": 0}', '')
                    return real_run(command, **kwargs)

                with patch.object(subprocess, 'run', side_effect=run):
                    with self.assertRaisesRegex((tx.TxError, initializer.InitError), '校验器超时'):
                        committer.commit(args)
                self.assertEqual(len(timed_out), 1)
                self.assertEqual(formal_bytes(workspace), before)
                self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
                self.assertFalse(list(workspace.parent.glob('.discovery-call-preview-*')))
                self._assert_locks_released(workspace)
                initializer.validate_runtime_postflight(workspace)


if __name__ == '__main__':
    unittest.main()
