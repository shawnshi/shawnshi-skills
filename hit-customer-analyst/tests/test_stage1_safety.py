from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.common import load_json, run_python
from tests.common import research_plan as rp
from tests.common import runtime_tx as tx
from tests.fixture_builder import build_pending_letter_workspace
from tests.test_letter_lifecycle import validator
from tests.test_profile_and_planning import NOW, build, fields_for


def formal_bytes(workspace: Path) -> dict[str, bytes]:
    return {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in [*workspace.glob('*.md'), *workspace.glob('runtime/*.json')]
    }


def commit_candidate(workspace: Path, candidate: Path):
    revision, digest = tx.manifest_state(workspace)
    return run_python('commit_run.py', [
        str(workspace), '--candidate-workspace', str(candidate),
        '--expected-manifest-revision', str(revision),
        '--expected-manifest-sha256', digest, '--json',
    ])


class Stage1SafetyTests(unittest.TestCase):
    def test_STAB05_all_candidates_preflight_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            first, second = workspace / 'a.md', workspace / 'b.md'
            first.write_bytes(b'old-a')
            second.write_bytes(b'old-b')
            # Retain a real prepared WAL without writing any formal target.
            real_write = tx._write_journal

            def stop_prepared(root, journal):
                real_write(root, journal)
                if journal['state'] == 'committing':
                    raise RuntimeError('simulated interruption before writes')

            with tx.workspace_lock(workspace):
                with (
                    patch.object(tx, '_write_journal', side_effect=stop_prepared),
                    self.assertRaisesRegex(RuntimeError, 'simulated interruption'),
                ):
                    tx.transactional_commit(workspace, {first: b'new-a', second: b'new-b'}, operation='test')
                journal = load_json(workspace / tx.JOURNAL_NAME)
                staged = workspace / journal['tx_dir'] / journal['entries'][-1]['new']
                staged.write_bytes(b'corrupted')
                before = formal_bytes(workspace)
                journal_bytes = (workspace / tx.JOURNAL_NAME).read_bytes()
                backups = {p: p.read_bytes() for p in (workspace / journal['tx_dir'] / 'old').iterdir()}
                with self.assertRaises(tx.TxError):
                    tx.recover_transaction(workspace, strategy='roll-forward')
                self.assertEqual(formal_bytes(workspace), before)
                self.assertEqual((workspace / tx.JOURNAL_NAME).read_bytes(), journal_bytes)
                self.assertTrue(all(p.read_bytes() == raw for p, raw in backups.items()))
                self.assertEqual(tx.recover_transaction(workspace, strategy='rollback'), 'rolled_back')
                self.assertEqual(formal_bytes(workspace), before)

    def test_STAB04_placeholder_approver_cli_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary))
            before = formal_bytes(workspace)
            result = run_python('validate_outputs.py', [str(workspace), '--approve-letter', '--approver', '待确认', '--json'])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(formal_bytes(workspace), before)

    def test_STAB04_candidate_cannot_create_authorization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_letter_workspace(root / 'output')
            candidate = root / 'candidate'
            candidate.mkdir()
            total = next(workspace.glob('*客户研究与拜访准备报告.md'))
            (candidate / total.name).write_text(validator.replace_flat_frontmatter(
                total.read_text(encoding='utf-8'), {'tenant_id': 'tenant.self-granted'}
            ), encoding='utf-8')
            before = formal_bytes(workspace)
            result = commit_candidate(workspace, candidate)
            self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
            self.assertEqual(formal_bytes(workspace), before)

    def test_UX03_unconfirmed_is_not_confirmed(self):
        fields = fields_for('letter')
        fields['recipient_role'] = 'Director unconfirmed'
        fields['recipient_identity_status'] = 'unconfirmed'
        plan = build('letter', business_fields=fields)
        self.assertFalse(plan['planning_ready'], plan['gate_results'])
        self.assertIn('recipient_identity_and_role_confirmed', plan['gate_results']['failed'])

    def test_EFF02_replan_preserves_evidence_and_executed_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = rp.RuntimeWorkspace(Path(temporary))
            plan = build('briefing')
            paths = workspace.materialize(plan)
            evidence = rp.update_evidence_manifest(
                paths['evidence_manifest'], sources={'SRC-I-001': {'locator': 'https://example.test'}},
                claims={'CLM-I-001': {'source_ids': ['SRC-I-001']}},
                query_links={plan['queries'][0]['query_id']: ['SRC-I-001']}, updated_at=NOW,
            )
            evidence['connector_audit']['status'] = 'failed'
            rp.atomic_write_json(paths['evidence_manifest'], evidence)
            metrics = rp.RunMetrics(paths['run_metrics'], plan['context_id'], plan['run_id'], 'briefing', NOW)
            metrics.increment(queries_executed=3, cache_hits=2)
            metrics.finish(ended_at=NOW, input_tokens=100, output_tokens=20)
            preserved = {name: paths[name].read_bytes() for name in ('evidence_manifest', 'run_metrics', 'source_cache')}
            changed = copy.deepcopy(plan)
            changed['queries'] = changed['queries'][:1]
            changed['batches'] = rp.batch_queries(changed['queries'], 4)
            workspace.materialize(changed)
            self.assertEqual({name: paths[name].read_bytes() for name in preserved}, preserved)
            self.assertEqual(load_json(paths['search_plan']), changed)

    def test_STAB05_recovery_cli_corruption_preserves_partial_state_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            initialized = run_python('init_workspace.py', [
                '示例医院', '--output-root', temporary, '--task-timezone', 'Asia/Shanghai',
                '--route', 'research_only', '--modules', 'institution', '--runtime-owner', '测试负责人', '--json',
            ])
            self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
            workspace = Path(json.loads(initialized.stdout)['workspace'])
            before_crash = formal_bytes(workspace)
            manifest = load_json(workspace / tx.MANIFEST_REL)
            crashed = run_python('init_workspace.py', [
                '示例医院', '--output-root', str(workspace.parent), '--resume',
                '--context-id', manifest['context_id'], '--route', 'research_only', '--modules', 'institution',
                '--runtime-owner', '测试负责人', '--json',
            ], env={'DISCOVERY_CALL_TX_SIGKILL_AFTER': '1'})
            self.assertNotEqual(crashed.returncode, 0)
            self.assertTrue((workspace / tx.JOURNAL_NAME).is_file(), crashed.stderr or crashed.stdout)
            journal = load_json(workspace / tx.JOURNAL_NAME)
            self.assertGreater(len(journal['entries']), 1)
            staged = workspace / journal['tx_dir'] / journal['entries'][-1]['new']
            staged.write_bytes(b'corrupted CLI candidate')
            after_crash = formal_bytes(workspace)
            journal_bytes = (workspace / tx.JOURNAL_NAME).read_bytes()
            backups = {p: p.read_bytes() for p in (workspace / journal['tx_dir'] / 'old').iterdir()}
            result = run_python('recover_workspace.py', [str(workspace), '--strategy', 'roll-forward', '--json'])
            self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
            self.assertIn('候选哈希不符', result.stderr)
            self.assertEqual(formal_bytes(workspace), after_crash)
            self.assertEqual((workspace / tx.JOURNAL_NAME).read_bytes(), journal_bytes)
            self.assertTrue(all(p.read_bytes() == raw for p, raw in backups.items()))
            rollback = run_python('recover_workspace.py', [str(workspace), '--strategy', 'rollback', '--json'])
            self.assertEqual(rollback.returncode, 0, rollback.stderr or rollback.stdout)
            self.assertEqual(formal_bytes(workspace), before_crash)
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())

    def test_STAB05_unsafe_late_candidates_never_write_earlier_targets(self):
        for defect in ('missing', 'directory', 'symlink', 'escape', 'bucket-symlink'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                first, second = workspace / 'a.md', workspace / 'b.md'
                first.write_bytes(b'old-a')
                second.write_bytes(b'old-b')
                real_write = tx._write_journal

                def stop_prepared(root, journal, write_journal=real_write):
                    write_journal(root, journal)
                    if journal['state'] == 'committing':
                        raise RuntimeError('prepared')

                with tx.workspace_lock(workspace):
                    with patch.object(tx, '_write_journal', side_effect=stop_prepared), self.assertRaisesRegex(RuntimeError, 'prepared'):
                        tx.transactional_commit(workspace, {first: b'new-a', second: b'new-b'}, operation='negative')
                    journal = load_json(workspace / tx.JOURNAL_NAME)
                    staged = workspace / journal['tx_dir'] / journal['entries'][-1]['new']
                    if defect == 'escape':
                        journal['entries'][-1]['new'] = '../outside.bin'
                        tx.atomic_write_json(workspace / tx.JOURNAL_NAME, journal)
                    elif defect == 'bucket-symlink':
                        bucket = staged.parent
                        moved = bucket.with_name('moved')
                        bucket.rename(moved)
                        bucket.symlink_to(moved, target_is_directory=True)
                    else:
                        staged.unlink()
                        if defect == 'directory':
                            staged.mkdir()
                        elif defect == 'symlink':
                            staged.symlink_to(first)
                    before = formal_bytes(workspace)
                    journal_bytes = (workspace / tx.JOURNAL_NAME).read_bytes()
                    backups = {p: p.read_bytes() for p in (workspace / journal['tx_dir'] / 'old').iterdir()}
                    with self.assertRaises(tx.TxError):
                        tx.recover_transaction(workspace, strategy='roll-forward')
                    self.assertEqual(formal_bytes(workspace), before)
                    self.assertEqual((workspace / tx.JOURNAL_NAME).read_bytes(), journal_bytes)
                    self.assertTrue(all(p.read_bytes() == raw for p, raw in backups.items()))
                    self.assertEqual(tx.recover_transaction(workspace, strategy='rollback'), 'rolled_back')

    def test_STAB05_valid_forward_and_auto_preserve_transaction_contract(self):
        for strategy in ('roll-forward', 'auto'):
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                target = workspace / 'a.md'
                target.write_bytes(b'old')
                real_write = tx._write_journal

                def interrupt(root, journal, write_journal=real_write):
                    write_journal(root, journal)
                    if journal['state'] == 'committing':
                        raise RuntimeError('prepared')

                with tx.workspace_lock(workspace):
                    with patch.object(tx, '_write_journal', side_effect=interrupt), self.assertRaisesRegex(RuntimeError, 'prepared'):
                        tx.transactional_commit(workspace, {target: b'new'}, operation='valid')
                    if strategy == 'auto':
                        target.write_bytes(b'new')
                    self.assertEqual(tx.recover_transaction(workspace, strategy=strategy), 'rolled_forward')
                    self.assertEqual(target.read_bytes(), b'new')
                    self.assertFalse((workspace / tx.JOURNAL_NAME).exists())

    def test_STAB04_actor_policy_entry_and_approved_read_gates(self):
        invalid = ('待确认', '待指定', '匿名', 'anonymous', '销售', '领导', '审核人', '{{approver}}', '张三（待确认）', 'ＡＮＯＮＹＭＯＵＳ')
        for actor in invalid:
            with self.subTest(actor=actor):
                self.assertFalse(validator.valid_actor(actor))
                with self.assertRaises(RuntimeError):
                    validator.clean_actor(actor, '--reviewer')
        for actor in ('张三（华北客户负责人）', '当班合规审批人：张三/employee_id', '李明（客户沟通审批岗）', '赵敏'):
            self.assertEqual(validator.clean_actor(actor, '--approver'), actor)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary))
            before = formal_bytes(workspace)
            for actor in invalid[1:7]:
                result = run_python('validate_outputs.py', [str(workspace), '--approve-letter', '--approver', actor, '--json'])
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(formal_bytes(workspace), before)
            approved = run_python('validate_outputs.py', [str(workspace), '--approve-letter', '--approver', '李明（客户沟通审批岗）', '--json'])
            self.assertEqual(approved.returncode, 0, approved.stderr or approved.stdout)
            documents = validator.load_documents(workspace, [])
            letter = next(doc for doc in documents if doc.frontmatter['artifact_type'] == 'customer_letter_internal')
            for actor in invalid:
                document = copy.deepcopy(letter)
                document.frontmatter['approver'] = actor
                issues = []
                validator.validate_frontmatter(document, issues, False)
                self.assertIn('approver_missing', {issue.code for issue in issues})
                document.frontmatter['artifact_type'] = 'customer_letter_external'
                issues = []
                validator.validate_frontmatter(document, issues, False)
                self.assertIn('approver_missing', {issue.code for issue in issues})
                document.frontmatter.update(artifact_type='leader_research', reviewer=actor)
                issues = []
                validator.validate_frontmatter(document, issues, False)
                self.assertIn('reviewer_unassigned', {issue.code for issue in issues})
            # Read gate is also exercised by the real CLI, not only a CAS failure.
            letter.path.write_text(validator.replace_flat_frontmatter(letter.text, {'approver': '匿名'}), encoding='utf-8')
            result = run_python('validate_outputs.py', [str(workspace), '--emit-external', '--json'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('approver_missing', result.stdout)
            self.assertFalse(list(workspace.glob('*客户信（外发版）.md')))

    def test_STAB04_candidate_self_authorization_matrix_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialized = run_python('init_workspace.py', [
                '示例医院', '--output-root', str(root / 'output'), '--task-timezone', 'Asia/Shanghai',
                '--route', 'research_only', '--modules', 'institution', '--runtime-owner', '测试负责人', '--json',
            ])
            self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
            workspace = Path(json.loads(initialized.stdout)['workspace'])
            candidate = root / 'candidate'
            candidate.mkdir()
            total = next(workspace.glob('*客户研究与拜访准备报告.md'))
            values = {'tenant_id': 'tenant.demo', 'project_id': 'project.demo', 'authorization_owner': '张三（数据所有者）', 'authorization_expires_at': '2099-09-30T00:00:00Z'}
            for key, value in values.items():
                (candidate / total.name).write_text(validator.replace_flat_frontmatter(total.read_text(encoding='utf-8'), {key: value}), encoding='utf-8')
                before = formal_bytes(workspace)
                result = commit_candidate(workspace, candidate)
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertIn('init/resume', result.stderr)
                self.assertEqual(formal_bytes(workspace), before)
            # Public-only unchanged candidate remains allowed without authorization.
            (candidate / total.name).write_bytes(total.read_bytes())
            result = commit_candidate(workspace, candidate)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def _authorized_workspace(self, root: Path) -> Path:
        initialized = run_python('init_workspace.py', [
            '示例医院', '--output-root', str(root / 'output'), '--task-timezone', 'Asia/Shanghai',
            '--route', 'research_only', '--modules', 'institution', '--runtime-owner', '测试负责人', '--json',
        ])
        self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
        workspace = Path(json.loads(initialized.stdout)['workspace'])
        manifest = load_json(workspace / tx.MANIFEST_REL)
        result = run_python('init_workspace.py', [
            '示例医院', '--output-root', str(workspace.parent), '--resume',
            '--context-id', manifest['context_id'], '--route', 'research_only',
            '--modules', 'institution', '--runtime-owner', '测试负责人',
            '--tenant-id', 'tenant.demo', '--project-id', 'project.demo',
            '--authorization-owner', '张三（数据所有者）',
            '--authorization-expires-at', '2099-09-30T00:00:00Z',
            '--allowed-project-ids', 'project.demo', '--json',
        ])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return workspace

    def test_STAB04_explicit_init_preserves_nfkc_authorization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._authorized_workspace(root)
            established = load_json(workspace / tx.MANIFEST_REL)['authorization']
            expected = {
                'tenant_id': 'tenant.demo', 'project_id': 'project.demo',
                # NFKC intentionally converts full-width parentheses; do not
                # use the implementation under test to derive this oracle.
                'authorization_owner': '张三(数据所有者)',
                'authorization_expires_at': '2099-09-30T00:00:00Z',
            }
            total = next(workspace.glob('*客户研究与拜访准备报告.md'))
            metadata = tx.parse_frontmatter(total.read_text(encoding='utf-8'))
            for key, value in expected.items():
                self.assertEqual(established[key], value)
                self.assertEqual(metadata[key], value)
            candidate = root / 'candidate'
            candidate.mkdir()
            (candidate / total.name).write_bytes(total.read_bytes())
            result = commit_candidate(workspace, candidate)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(load_json(workspace / tx.MANIFEST_REL)['authorization'], established)

    def _assert_existing_authorization_rejected(self, *, clear: bool) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._authorized_workspace(root)
            total = next(workspace.glob('*客户研究与拜访准备报告.md'))
            candidate = root / 'candidate'
            candidate.mkdir()
            for key in ('tenant_id', 'project_id', 'authorization_owner', 'authorization_expires_at'):
                with self.subTest(field=key):
                    value = '' if clear else ('2100-09-30T00:00:00Z' if key == 'authorization_expires_at' else 'changed.value')
                    (candidate / total.name).write_text(validator.replace_flat_frontmatter(total.read_text(encoding='utf-8'), {key: value}), encoding='utf-8')
                    before = formal_bytes(workspace)
                    result = commit_candidate(workspace, candidate)
                    self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                    self.assertIn('init/resume', result.stderr)
                    self.assertEqual(formal_bytes(workspace), before)

    def test_STAB04_existing_authorization_cannot_be_cleared(self):
        self._assert_existing_authorization_rejected(clear=True)

    def test_STAB04_existing_authorization_cannot_be_changed_or_extended(self):
        self._assert_existing_authorization_rejected(clear=False)

    def test_UX03_explicit_enum_missing_conflicted_and_cli(self):
        for status in (None, 'unconfirmed', 'conflicted', 'confirmed'):
            fields = fields_for('letter')
            fields['recipient_role'] = 'Director confirmed 已确认'
            if status is None:
                fields.pop('recipient_identity_status')
            else:
                fields['recipient_identity_status'] = status
            plan = build('letter', business_fields=fields)
            self.assertEqual(plan['planning_ready'], status == 'confirmed')
        for status in ('not-confirmed', '', 'CONFIRMED', True):
            fields = fields_for('letter') | {'recipient_identity_status': status}
            with self.assertRaises(rp.PlanError):
                build('letter', business_fields=fields)
        for role in ('', '待确认'):
            fields = fields_for('letter') | {'recipient_role': role}
            self.assertFalse(build('letter', business_fields=fields)['planning_ready'])
        with tempfile.TemporaryDirectory() as temporary:
            plan = build('letter')
            args = ['plan', '--workspace', temporary, '--business-mode', 'letter', '--context-id', plan['context_id'], '--run-id', plan['run_id'], '--customer-name', '示例医院', '--customer-id', plan['customer_id'], '--organization-scope', plan['organization_scope'], '--require-planning-ready']
            for key, value in fields_for('letter').items():
                args.extend(['--business-field', f'{key}={value}'])
            result = run_python('research_plan.py', args)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue(json.loads(result.stdout)['planning_ready'])

    def test_EFF02_mismatched_identity_and_corrupt_metrics_refuse_before_write(self):
        for key, value in (
            ('context_id', 'dcx-20260826-Zzzz9999'), ('run_id', 'dcr-20260826T050000-Xx99'),
            ('customer_id', 'customer.other'), ('organization_scope', '其他院区'),
            ('business_mode', 'letter'), ('project_id', 'project.other'),
            ('metrics_run', 'dcr-20260826T050000-Xx99'), ('metrics_schema', 'invalid'),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                workspace = rp.RuntimeWorkspace(Path(temporary))
                plan = build('briefing')
                paths = workspace.materialize(plan)
                if key.startswith('metrics_'):
                    metrics = load_json(paths['run_metrics'])
                    metrics['run_id' if key == 'metrics_run' else 'schema'] = value
                    rp.atomic_write_json(paths['run_metrics'], metrics)
                candidate = copy.deepcopy(plan)
                if key not in ('project_id', 'metrics_run', 'metrics_schema'):
                    candidate[key] = value
                before = formal_bytes(workspace.workspace)
                with self.assertRaises(rp.PlanError):
                    workspace.materialize(candidate, project_id=value if key == 'project_id' else None)
                self.assertEqual(formal_bytes(workspace.workspace), before)


if __name__ == '__main__':
    unittest.main()
