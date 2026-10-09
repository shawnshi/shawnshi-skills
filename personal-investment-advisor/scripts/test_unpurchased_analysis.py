"""Offline regression tests: research includes zero quantities, holdings do not."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pia_daily
import pia
import pia_report
import unpurchased_analysis as research
from portfolio_loader import load_positions, analysis_positions
from quote_evidence_contract import build_portfolio_snapshot_binding
from test_p2_daily_run_pipeline import positions_payload

NOW = time.time()


class UnpurchasedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'positions.json'
        self.raw = positions_payload()
        self.raw['positions'].append({'symbol': '688188.SS', 'name': '柏楚电子',
                                     'quantity': 0, 'avg_cost': 12345,
                                     'currency': 'CNY', 'market': 'CN', 'asset_type': 'stock'})
        self.path.write_text(json.dumps(self.raw), encoding='utf-8')
        self.original = self.path.read_bytes()
        self.positions = load_positions(str(self.path))
        self.quote = {'symbol': '688188.SS', 'info': {
            'symbol': '688188.SS', 'exchange': 'SHH', 'currency': 'CNY',
            'financialCurrency': 'CNY', 'quoteType': 'EQUITY', 'marketState': 'REGULAR',
            'regularMarketPrice': 100.0, 'regularMarketTime': NOW - 60, 'trailingEps': 4.0}}

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, rows=None, **kwargs):
        return research.evaluate(self.positions, [self.quote] if rows is None else rows,
                                 evaluation_epoch=NOW, **kwargs)

    def test_same_mtime_quantity_change_does_not_reuse_old_classification(self):
        previous_stat = self.path.stat()
        self.raw['positions'][0]['quantity'] = 0
        self.path.write_text(json.dumps(self.raw), encoding='utf-8')
        os.utime(self.path, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
        updated = load_positions(str(self.path))
        self.assertNotIn('600000.SS', updated['_positions_dict'])
        self.assertIn('600000.SS', updated['_inactive_positions_dict'])

    def test_zero_in_research_but_not_actual_positions_or_binding(self):
        self.assertEqual(len(analysis_positions(self.positions)), 2)
        self.assertNotIn('688188.SS', self.positions['_positions_dict'])
        actual = build_portfolio_snapshot_binding(self.positions)
        self.assertNotIn('688188.SS', [row['symbol'] for row in actual['active_positions']])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_reference_cost_is_not_capital_or_return(self):
        row = self.evaluate()['rows'][0]
        self.assertEqual(row['actual_quantity'], 0)
        self.assertEqual(row['actual_market_value'], 0)
        self.assertEqual(row['actual_cost_basis'], 0)
        self.assertIsNone(row['unrealized_pnl'])
        self.assertIsNone(row['unrealized_pnl_pct'])
        self.assertIsNone(row['trade_parameters'])
        self.assertEqual(row['valuation']['price_to_trailing_eps'], 25)
        self.assertTrue(row['excluded_from_actual_weight_denominator'])

    def test_valid_quote_not_equal_to_thesis_safe(self):
        result = self.evaluate()
        self.assertTrue(result['coverage']['quote_coverage_complete'])
        self.assertEqual(result['thesis_red_team']['status'], 'not_assessed')
        self.assertEqual(result['status'], 'insufficient_evidence')

    def test_missing_and_duplicate_quotes_are_not_silent(self):
        missing = self.evaluate([])
        self.assertEqual(len(missing['rows']), 1)
        self.assertIn('quote_missing', missing['rows'][0]['errors'])
        duplicate = self.evaluate([self.quote, self.quote])
        self.assertIn('duplicate_quote_symbol', duplicate['rows'][0]['errors'])
        self.assertIsNone(duplicate['rows'][0]['current_price'])

    def test_stale_or_wrong_currency_prevents_calculation(self):
        for change in [{'regularMarketTime': NOW - 10000}, {'currency': 'USD'}]:
            quote = copy.deepcopy(self.quote)
            quote['info'].update(change)
            row = self.evaluate([quote])['rows'][0]
            self.assertIsNone(row['current_price'])
            self.assertIsNone(row['valuation']['price_to_trailing_eps'])

    def test_bad_eps_and_financial_currency_not_filled(self):
        for change in [{'trailingEps': -1}, {'trailingEps': 0}, {'trailingEps': True},
                       {'financialCurrency': 'USD'}, {'financialCurrency': None}]:
            quote = copy.deepcopy(self.quote)
            quote['info'].update(change)
            self.assertIsNone(self.evaluate([quote])['rows'][0]['valuation']['price_to_trailing_eps'])

    def test_invalid_epoch_rejected(self):
        for value in [float('nan'), float('inf'), True, -1]:
            with self.assertRaises(ValueError):
                research.evaluate(self.positions, [self.quote], evaluation_epoch=value)

    def test_research_binding_detects_unheld_identity_change(self):
        binding = research.research_binding(self.positions)
        other = copy.deepcopy(self.positions)
        other['_inactive_positions_dict']['688188.SS']['name'] = 'another issuer'
        self.assertNotEqual(binding, research.research_binding(other))
        packet = {'records': [self.quote], 'research_binding': research.research_binding(other)}
        result = research.evaluate(self.positions, packet, evaluation_epoch=NOW)
        self.assertIn('research_snapshot_binding_mismatch', result['errors'])
        self.assertFalse(result['coverage']['quote_coverage_complete'])

    def test_offline_replay_never_mints_new_binding(self):
        task = self.root / 'task'
        (task / 'out').mkdir(parents=True)
        wrong = self.root / 'wrong.json'
        wrong.write_text(json.dumps({'records': [self.quote], 'research_binding': {}}))
        with self.assertRaisesRegex(ValueError, 'binding_mismatch'):
            research.run(self.positions, task_dir=task, cache_dir=task / 'cache',
                         evaluation_epoch=NOW, dashboard_root=self.root, quotes_file=wrong)
        self.assertFalse((task / 'out/unpurchased_analysis.json').exists())

    def test_plan_includes_research_and_keeps_actual_stages(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = pia_daily.main(['--positions-file', str(self.path), '--task-dir', str(self.root / 'task'),
                                   '--plan-only'])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result['plan'][0], 'unpurchased_analysis')
        self.assertIn('weights', result['plan'])
        self.assertEqual(result['analysis_scope']['analysis_non_cash_count'], 2)

    def test_all_unpurchased_do_not_invent_holdings_or_fetch_actual_quotes(self):
        self.raw['positions'][0]['quantity'] = 0
        self.path.write_text(json.dumps(self.raw))
        positions = load_positions(str(self.path))
        quote2 = copy.deepcopy(self.quote)
        quote2['symbol'] = quote2['info']['symbol'] = '600000.SS'
        packet = self.root / 'research.json'
        packet.write_text(json.dumps({'records': [self.quote, quote2],
                                     'research_binding': research.research_binding(positions)}))
        output = io.StringIO()
        with mock.patch.object(pia_daily, 'run_quotes') as actual_quotes:
            with contextlib.redirect_stdout(output):
                code = pia_daily.main(['--positions-file', str(self.path), '--task-dir', str(self.root / 'task'),
                                       '--unpurchased-quotes-file', str(packet), '--now-epoch', str(NOW)])
        result = json.loads(output.getvalue())
        actual_quotes.assert_not_called()
        self.assertNotEqual(code, 0)  # no primary Thesis or Dashboard
        self.assertIn('actual_holdings_status', result, json.dumps(result))
        self.assertEqual(result['actual_holdings_status'], 'not_computed_no_held_non_cash_securities')
        self.assertEqual(result['cash_weights_status'], 'not_computed')
        self.assertIsNone(result['actual_holdings_weights'])
        self.assertEqual(result['analysis_scope']['unpurchased_count'], 2)
        self.assertEqual([row['stage'] for row in result['stages']], ['unpurchased_analysis'])

    def test_mixed_run_actual_denominator_unchanged(self):
        import yf
        packet = self.root / 'research.json'
        packet.write_text(json.dumps({'records': [self.quote], 'research_binding': research.research_binding(self.positions)}))
        held = copy.deepcopy(self.quote)
        held['symbol'] = held['info']['symbol'] = '600000.SS'
        held['portfolio_context'] = {'position_status': 'matched'}
        held['data_sources'] = {'price': 'Yahoo Finance', 'price_locator': 'yfinance:600000.SS:quote'}

        def offline_capture(path, cache, symbols, task_dir, holiday_calendar=None):
            positions = load_positions(str(path))
            audit = yf.build_portfolio_batch_audit(
                [held], requested_count=1, expected_symbols=['600000.SS'], portfolio_load_status='ok',
                expected_position_metadata=positions['_positions_dict'], now_epoch=NOW,
                portfolio_snapshot_binding=build_portfolio_snapshot_binding(positions))
            self.assertTrue(audit['complete'])
            quotes = task_dir / 'out/quotes.json'
            quotes.write_text(json.dumps({'records': [held], 'portfolio_batch_audit': audit}))
            return 0, {'status': 'complete', 'coverage_complete': True}, quotes

        output = io.StringIO()
        task = self.root / 'mixed'
        with mock.patch.object(pia_daily, 'run_quotes', side_effect=offline_capture):
            with contextlib.redirect_stdout(output):
                code = pia_daily.main(['--positions-file', str(self.path), '--task-dir', str(task),
                                       '--skip-watchlist', '--unpurchased-quotes-file', str(packet),
                                       '--now-epoch', str(NOW)])
        summary = json.loads(output.getvalue())
        self.assertTrue((task / 'out/weights.json').is_file(), json.dumps(summary))
        weights = json.loads((task / 'out/weights.json').read_text())
        by_symbol = {row['symbol']: row for row in weights['current_weights']}
        self.assertEqual(by_symbol['600000.SS']['current_weight'], .375)
        self.assertNotIn('688188.SS', by_symbol)
        self.assertEqual(summary['analysis_scope']['analysis_non_cash_count'], 2)
        self.assertNotEqual(code, 0)  # unpurchased Thesis/valuation remain unassessed
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_mixed_run_keeps_research_failure_when_fx_fails(self):
        output = io.StringIO()
        with mock.patch.object(research, 'run', side_effect=ValueError('capture_failed')):
            with mock.patch.object(pia_daily, 'run_module', return_value=(3, {'status': 'failed', 'errors': ['FX']})):
                with contextlib.redirect_stdout(output):
                    code = pia_daily.main(['--positions-file', str(self.path), '--task-dir', str(self.root / 'task')])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual([row['stage'] for row in result['stages']], ['unpurchased_analysis', 'refresh'])
        self.assertEqual(result['analysis_scope']['unpurchased_count'], 1)
        self.assertEqual(result['unpurchased_analysis']['expected_symbols'], ['688188.SS'])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_report_exposes_research_not_just_actual_quote_count(self):
        task = self.root / 'render'
        (task / 'out').mkdir(parents=True)
        result = self.evaluate()
        (task / 'out/unpurchased_analysis.json').write_text(json.dumps(result))
        summary = {'status': 'incomplete', 'evaluation_epoch': NOW, 'analysis_scope': result['coverage'],
                   'stages': [{'stage': 'unpurchased_analysis', 'status': 'insufficient_evidence', 'artifacts': []}]}
        rendered = pia_report.render(task, {'daily_run_summary': summary}, {})
        self.assertIn('实仓 1 + 未购 1 = 2', rendered)
        self.assertIn('688188.SS', rendered)
        self.assertIn('not_assessed', rendered)

    def test_builder_research_packet_does_not_overwrite_actual_quotes(self):
        task = self.root / 'build'
        (task / 'out').mkdir(parents=True)
        actual = task / 'out/quotes.json'
        actual.write_text('{"sentinel":"actual holdings"}')
        source = self.root / 'research.json'
        source.write_text(json.dumps({'records': [self.quote], 'research_binding': research.research_binding(self.positions)}))
        evidence = self.root / 'evidence.json'; evidence.write_text('{"evidence_items":[]}')
        assessments = self.root / 'assessments.json'; assessments.write_text(json.dumps({'assessments': [
            {'symbol': '688188.SS', 'conclusion': 'insufficient_evidence', 'rationale': 'missing', 'evidence_ids': ['missing']}]}))
        scopes = self.root / 'scopes.json'; scopes.write_text('{"scope_coverage":{}}')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = pia.main(['build', 'thesis-pack', '--research-universe', '--quotes-file', str(source),
                                   '--evidence-file', str(evidence), '--assessments-file', str(assessments),
                                   '--scope-coverage-file', str(scopes), '--window-start', '2026-09-01T00:00:00Z',
                                   '--task-dir', str(task)])
        self.assertEqual(code, 0)  # build success is not semantic evidence-gate success
        self.assertEqual(actual.read_text(), '{"sentinel":"actual holdings"}')
        self.assertTrue((task / 'inputs/unpurchased_thesis_evidence_pack.json').exists())
        self.assertFalse((task / 'inputs/thesis_evidence_pack.json').exists())


if __name__ == '__main__':
    unittest.main()
