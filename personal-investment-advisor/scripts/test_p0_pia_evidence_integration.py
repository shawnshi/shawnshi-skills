"""Synthetic native CLI binding and fail-closed propagation checks."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import daily_sync
import pia
import pia_report
import unpurchased_analysis
import test_p0_constraint_authority as constraint_fixture
from portfolio_loader import load_positions
from quote_evidence_contract import build_portfolio_snapshot_binding
import test_p0_thesis_source_binding as binding_fixture
from test_p2_daily_sync import DailySyncTestCase, NOW_EPOCH


class EvidenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = binding_fixture.SourceBindingTests('test_recomputes_hit_despite_submitted_non_hit_and_coverage_gaps')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.positions, self.quotes = DailySyncTestCase().write_inputs(self.root)
        f = self.fixture
        f.ledger['symbols']['AAPL'] = f.ledger['symbols'].pop('SYNTH')
        f.claim['symbol'] = f.fact['symbol'] = 'AAPL'
        f.pack['portfolio_snapshot_binding'] = build_portfolio_snapshot_binding(load_positions(str(self.positions)))
        def stamp(offset):
            return datetime.fromtimestamp(NOW_EPOCH + offset, timezone.utc).isoformat()
        f.pack.update(generated_at=stamp(-10), window_start=stamp(-86400), window_end=stamp(-60))
        for item in f.pack['evidence_items']:
            item.update(published_at=stamp(-7200), retrieved_at=stamp(-30))
        f.write_source()
        f.write_ledger()
        self.pack_path = self.root / 'pack.json'
        self.save_pack()

    def save_pack(self):
        self.pack_path.write_text(json.dumps(self.fixture.pack), encoding='utf-8')

    def native(self, script, *args):
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).parent / script),
                                 *map(str, args)], capture_output=True, text=True,
                                encoding='utf-8', timeout=60)
        self.assertIn(result.returncode, (0, 1, 2), result.stderr + result.stdout)
        return result.returncode, json.loads(result.stdout)

    def sync(self, trusted=True):
        return daily_sync.evaluate_daily_sync(
            positions_file=str(self.positions), quotes_file=str(self.quotes),
            thesis_evidence_file=str(self.pack_path), now_epoch=NOW_EPOCH,
            conditions_file=str(self.fixture.ledger_path) if trusted else None,
            evidence_root=str(self.root) if trusted else None)

    def assert_local_hit(self, report):
        self.assertEqual(report['status'], 'incomplete')
        thesis = report['thesis_red_team']
        self.assertEqual(thesis['fatal_symbols'], ['AAPL'])
        self.assertEqual(thesis['verified_hits'][0]['observed_values'], ['9'])
        self.assertIn('missing_assessment_symbols:159516.SZ', thesis['errors'])

    def test_native_sync_retains_bound_hit_with_other_coverage_missing(self):
        code, report = self.native('daily_sync.py', '--positions-file', self.positions,
            '--quotes-file', self.quotes, '--thesis-evidence-file', self.pack_path,
            '--conditions-file', self.fixture.ledger_path, '--evidence-root', self.root,
            '--now-epoch', NOW_EPOCH)
        self.assertEqual(code, 1)
        self.assert_local_hit(report)
        lines = []
        pia_report._render_verified_thesis(lines, report['thesis_red_team'])
        text = '\n'.join(lines)
        self.assertIn('AAPL', text)
        self.assertIn('verified_fatal_breach', text)
        self.assertIn('incomplete', text)

    def test_native_router_rejects_declarations_without_trust(self):
        self.fixture.claim['conclusion'] = 'fatal_breach'
        self.save_pack()
        code, envelope = self.native('pia.py', 'daily-sync', '--positions-file', self.positions,
            '--quotes-file', self.quotes, '--thesis-evidence-file', self.pack_path,
            '--now-epoch', NOW_EPOCH)
        self.assertEqual(code, 1)
        report = envelope['result']
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['thesis_red_team']['verified_hits'], [])
        self.assertEqual(report['thesis_red_team']['verification_status'], 'declaration_only')
        lines = []
        pia_report._render_verified_thesis(lines, report['thesis_red_team'])
        self.assertIn('declaration_only', '\n'.join(lines))

    def test_binding_failures_cannot_be_upgraded_by_sync(self):
        f = self.fixture
        original = copy.deepcopy(f.source)
        for field, value in [('symbol', 'OTHER'), ('unit', 'CNY'),
                             ('period', '2025Q2'), ('scope', 'segment:other')]:
            with self.subTest(field=field):
                f.source = copy.deepcopy(original)
                f.source['facts'][0][field] = value
                f.write_source()
                self.save_pack()
                self.assertEqual(self.sync()['thesis_red_team']['verified_hits'], [])
        f.source = original
        f.write_source()
        self.save_pack()
        f.source_path.write_text('{}', encoding='utf-8')
        self.assertEqual(self.sync()['thesis_red_team']['verified_hits'], [])

    def test_native_builder_does_not_promote_artifact_creation(self):
        f = self.fixture
        # Builder requires assessment coverage; missing rules still cannot become safe.
        f.pack['assessments'].append({'symbol': '159516.SZ', 'conclusion': 'no_fatal_breach_verified',
            'rationale': 'synthetic', 'evidence_ids': ['aapl']})
        item = next(x for x in f.pack['evidence_items'] if x['evidence_id'] == 'aapl')
        item['artifact'] = 'source.json'
        files = {'evidence.json': {'evidence_items': [item]},
                 'assessments.json': {'assessments': f.pack['assessments']},
                 'scopes.json': {'scope_coverage': {}}}
        for name, payload in files.items():
            (self.root / name).write_text(json.dumps(payload), encoding='utf-8')
        code, result = self.native('pia_build.py', 'thesis-pack', '--quotes-file', self.quotes,
            '--evidence-file', self.root / 'evidence.json', '--assessments-file', self.root / 'assessments.json',
            '--scope-coverage-file', self.root / 'scopes.json', '--window-start', f.pack['window_start'],
            '--window-end', f.pack['window_end'], '--now-epoch', NOW_EPOCH,
            '--conditions-file', f.ledger_path, '--evidence-root', self.root, '--task-dir', self.root)
        self.assertEqual(code, 2)
        self.assertEqual(result['artifact_build_status'], 'complete')
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['thesis_red_team']['fatal_symbols'], ['AAPL'])
        built = json.loads(Path(result['pack_file']).read_text(encoding='utf-8'))
        self.assertEqual(built['conditions_sha256'], hashlib.sha256(f.ledger_path.read_bytes()).hexdigest())
        self.assertEqual(built['evidence_items'][0]['local_path'], 'source.json')

    def test_zero_quantity_lane_uses_same_bound_verification(self):
        positions = load_positions(str(self.positions))
        for row in positions['positions']:
            if row['symbol'] == 'AAPL':
                row['quantity'] = 0
        f = self.fixture
        f.pack['portfolio_snapshot_binding'] = unpurchased_analysis.research_binding(positions)
        result = unpurchased_analysis.evaluate(positions, [], evaluation_epoch=NOW_EPOCH,
            thesis_payload=f.pack, conditions_file=f.ledger_path, evidence_root=self.root)
        self.assertNotEqual(result['status'], 'complete')
        self.assertEqual(result['thesis_red_team']['fatal_symbols'], ['AAPL'])
        self.assertTrue(all(row['actual_quantity'] == 0 for row in result['rows']))
        untrusted = unpurchased_analysis.evaluate(positions, [], evaluation_epoch=NOW_EPOCH,
            thesis_payload=f.pack)
        self.assertEqual(untrusted['thesis_red_team']['verified_hits'], [])

    def test_report_preserves_known_breach_while_authority_is_unresolved(self):
        fixture = constraint_fixture.ConstraintAuthorityTests('test_confirmed_stricter_individual_cap_is_computed_and_observed')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.position['max_weight'] = .1
        derived = fixture.build([constraint_fixture.confirmed()])
        observed = fixture.observe(derived)
        self.assertEqual(observed['categories']['weight_cap_breached'], ['AAPL'])
        self.assertEqual(derived['positions'][0]['constraint_resolution'], observed['constraint_resolution'])
        lines = []
        pia_report._render_position_limits(lines, derived)
        text = '\n'.join(lines)
        self.assertIn('unresolved', text)
        self.assertIn('breached', text)
        self.assertIn('recorded_unconfirmed', text)

    def test_router_forwards_explicit_trust_to_daily_run(self):
        captured = {}
        def child(**kwargs):
            captured.update(kwargs)
            return {'status': 'incomplete'}, 2
        with mock.patch.object(pia, '_run_child', side_effect=child):
            pia._dispatch(pia._build_parser().parse_args(['daily-run', '--positions-file', str(self.positions),
                '--task-dir', str(self.root / 'run'), '--conditions-file', str(self.fixture.ledger_path),
                '--evidence-root', str(self.root), '--plan-only']))
        args = captured['child_arguments']
        self.assertEqual(args[args.index('--conditions-file') + 1], str(self.fixture.ledger_path.resolve()))
        self.assertEqual(args[args.index('--evidence-root') + 1], str(self.root.resolve()))


if __name__ == '__main__':
    unittest.main()
