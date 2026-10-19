"""Native facade integration with synthetic captures and explicit policy only."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pia
import pia_readiness
import pia_report
import pia_research_workflow as workflow
import pia_review_pack
import sec_edgar_fundamentals as sec
from test_p1p2_fact_prepare import Response, company_bytes
from test_p1p2_fundamental_diagnostic import payload as fundamental_payload
from test_p2_build_inputs import policy_payload, positions_payload, weights_payload


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['PIA_TEST_TMP'])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = self.root / 'run'
        self.network = mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('offline'))
        self.network.start()
        self.addCleanup(self.network.stop)
        responses = {sec.TICKER_MAP_URL: b'{"0":{"ticker":"MSFT","cik_str":789019}}',
                     sec.COMPANYFACTS_URL.format(cik='0000789019'): company_bytes()}
        session = mock.Mock()
        session.get.side_effect = lambda url, **kw: Response(responses[url])
        report = sec.build_report(['MSFT'], as_of=date.today(), session=session, user_agent='synthetic',
                                  decision_scope='research_only', artifact_dir=self.root)
        self.save('native.json', report)
        self.save('fundamental.json', fundamental_payload())
        prior = {'symbol': 'MSFT', 'metric': 'diluted_eps', 'unit': 'USD/shares', 'period': '2023',
                 'scope': 'consolidated', 'period_start': '2023-01-01', 'period_end': '2023-12-31',
                 'recorded_at': '2022-12-01T00:00:00Z', 'deadline': '2024-02-15', 'expected_value': 8}
        p = self.save('prior.json', {'expectation': prior})
        self.save('feedback.json', {'as_of_date': date.today().isoformat(), 'comparisons': [
            {'comparison_id': 'eps', 'prior_ref': {'local_path': 'prior.json',
             'content_sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'pointer': '/expectation'}}]})
        self.manifest: dict[str, Any] = {'native_report': 'native.json', 'fundamental_input': 'fundamental.json', 'feedback_input': 'feedback.json'}

    def save(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def run_workflow(self):
        return workflow.run(self.save('workflow.json', self.manifest), self.root, self.task)

    def risk_spec(self):
        self.save('weights.json', weights_payload())
        self.save('positions.json', positions_payload())
        policy = policy_payload()
        policy.update(horizon='explicit 12 months', risk_thresholds={'max_loss': 0.3}, no_transactions_no_new_capital=True)
        self.save('policy.json', policy)
        dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(40)]
        histories = {}
        for j, symbol in enumerate(('AAA', 'BBB')):
            name = symbol + '.json'
            self.save(name, {'history': [{'Date': d, 'Close': 100 + i * (j + 1) + (i % 3)} for i, d in enumerate(dates)]})
            histories[symbol] = {'file': name, 'source': 'synthetic', 'source_locator': 'https://example.invalid/' + name, 'currency': 'CNY'}
        return {'weights_file': 'weights.json', 'positions_file': 'positions.json', 'confirmed_policy': 'policy.json',
                'base_currency': 'CNY', 'window_start': dates[0], 'window_end': dates[-1],
                'as_of': '2024-02-15T00:00:00Z', 'annualization_factor': 252,
                'annualization_basis': 'explicit synthetic 252 trading sessions/year method',
                'histories': histories, 'requests': ['diagnostic', 'inverse_vol', 'scenario']}

    def test_bad_prior_preserves_independent_auto_binding_both_orders(self):
        good = json.loads((self.root / 'feedback.json').read_text())['comparisons'][0]
        for bad_first in (False, True):
            with self.subTest(bad_first=bad_first):
                self.task = self.root / ('prior-order-' + str(bad_first))
                bad = dict(good, comparison_id='bad', prior_ref=dict(good['prior_ref'], local_path='missing-prior.json'))
                self.save('feedback.json', {'as_of_date': date.today().isoformat(),
                                          'comparisons': [bad, good] if bad_first else [good, bad]})
                result = self.run_workflow()
                branch = result['branches']['expectation_feedback']
                self.assertEqual(branch['status'], 'incomplete')
                items = {i['comparison_id']: i for i in branch['comparisons']}
                self.assertEqual(items['eps']['comparison']['delta']['value'], 2)
                self.assertTrue(any(e['type'] == 'FileNotFoundError' for e in items['bad']['errors']))

    def test_nonobject_prior_preserves_independent_auto_binding_both_orders(self):
        good = json.loads((self.root / 'feedback.json').read_text())['comparisons'][0]
        for shape in ([], None, 7, 'invalid', True, False):
            for bad_first in (False, True):
                with self.subTest(shape=shape, bad_first=bad_first):
                    self.task = self.root / ('shape-' + str(type(shape).__name__) + str(shape) + str(bad_first))
                    p = self.save('bad-prior.json', {'expectation': shape})
                    bad = dict(good, comparison_id='bad', prior_ref=dict(
                        good['prior_ref'], local_path='bad-prior.json',
                        content_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
                    self.save('feedback.json', {'as_of_date': date.today().isoformat(),
                                              'comparisons': [bad, good] if bad_first else [good, bad]})
                    result = self.run_workflow()
                    self.assertEqual(result['status'], 'incomplete')
                    branch = result['branches']['expectation_feedback']
                    self.assertEqual(branch['status'], 'incomplete')
                    items = {i['comparison_id']: i for i in branch['comparisons']}
                    self.assertEqual(items['eps']['actual']['fact']['value'], 10)
                    self.assertEqual(items['eps']['comparison']['delta']['value'], 2)
                    self.assertIsNone(items['bad']['comparison'])
                    self.assertTrue(any(e['type'] == 'FeedbackError' and
                                        e['message'] == 'expectation_object_required'
                                        for e in items['bad']['errors']))
                    saved = json.loads((self.task / 'out/research_workflow.json').read_text())
                    self.assertEqual(saved, result)

    def test_nonobject_prior_native_cli_keeps_manifest_and_valid_delta(self):
        good = json.loads((self.root / 'feedback.json').read_text())['comparisons'][0]
        p = self.save('bad-prior.json', {'expectation': []})
        bad = dict(good, comparison_id='bad', prior_ref=dict(
            good['prior_ref'], local_path='bad-prior.json',
            content_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        for bad_first in (False, True):
            with self.subTest(bad_first=bad_first):
                self.task = self.root / ('native-shape-' + str(bad_first))
                self.save('feedback.json', {'as_of_date': date.today().isoformat(),
                                          'comparisons': [bad, good] if bad_first else [good, bad]})
                manifest = self.save('workflow.json', self.manifest)
                run = subprocess.run([sys.executable, '-B', str(Path(pia.__file__)), 'research-workflow',
                                      '--input-file', str(manifest), '--evidence-root', str(self.root),
                                      '--task-dir', str(self.task)], capture_output=True, text=True,
                                     encoding='utf-8', timeout=60)
                self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
                envelope = json.loads(run.stdout)
                self.assertNotEqual(envelope['detail_status'], 'child_output_invalid')
                result = envelope['result']
                self.assertEqual(result['status'], 'incomplete')
                self.assertEqual(json.loads((self.task / 'out/research_workflow.json').read_text()), result)
                items = {i['comparison_id']: i for i in result['branches']['expectation_feedback']['comparisons']}
                self.assertEqual(items['eps']['actual']['fact']['value'], 10)
                self.assertEqual(items['eps']['comparison']['delta']['value'], 2)
                self.assertTrue(any(e['type'] == 'FeedbackError' and
                                    e['message'] == 'expectation_object_required'
                                    for e in items['bad']['errors']))

    def test_explicit_actual_refs_are_not_replaced(self):
        data = json.loads((self.root / 'feedback.json').read_text())
        data['comparisons'][0]['actual_refs'] = [{'local_path': 'missing-actual.json',
                                                'content_sha256': '0' * 64, 'pointer': '/facts/0'}]
        self.save('feedback.json', data)
        item = self.run_workflow()['branches']['expectation_feedback']['comparisons'][0]
        self.assertEqual(item['status'], 'incomplete')
        self.assertIsNone(item['comparison'])
        self.assertTrue(any(e['component'] == 'actual' and e['type'] == 'FileNotFoundError' for e in item['errors']))

    def test_currency_mismatch_missing_and_base_conflict_reject_formal(self):
        for mode in ('mismatch', 'missing', 'position_missing', 'base', 'payload'):
            with self.subTest(mode=mode):
                self.task = self.root / ('currency-' + mode)
                spec = self.risk_spec()
                if mode == 'mismatch':
                    spec['histories']['AAA']['currency'] = 'USD'
                elif mode == 'missing':
                    del spec['histories']['AAA']['currency']
                elif mode == 'payload':
                    history = json.loads((self.root / 'AAA.json').read_text())
                    self.save('AAA.json', dict(history, currency='USD'))
                else:
                    snapshot = json.loads((self.root / 'positions.json').read_text())
                    if mode == 'base':
                        snapshot['base_currency'] = 'USD'
                    else:
                        del snapshot['positions'][0]['currency']
                    self.save('positions.json', snapshot)
                self.manifest['risk'] = spec
                result = self.run_workflow()
                self.assertNotEqual(result['status'], 'complete')
                branch = result['branches']['risk']
                self.assertEqual(branch['inverse_vol']['status'], 'insufficient_data')
                self.assertTrue(branch['diagnostic']['currency_errors'])
                self.assertEqual(result['branches']['expectation_feedback']['comparisons'][0]['comparison']['delta']['value'], 2)

    def test_currency_error_retains_two_independent_histories(self):
        spec = self.risk_spec()
        weights = json.loads((self.root / 'weights.json').read_text())
        row = dict(weights['current_weights'][1], symbol='CCC')
        weights['current_weights'].append(row)
        self.save('weights.json', weights)
        positions = json.loads((self.root / 'positions.json').read_text())
        positions['positions'].append(dict(positions['positions'][1], symbol='CCC'))
        self.save('positions.json', positions)
        spec['histories']['CCC'] = dict(spec['histories']['BBB'])
        spec['histories']['AAA']['currency'] = 'USD'
        self.manifest['risk'] = spec
        result = self.run_workflow()['branches']['risk']
        diagnostic = result['diagnostic']
        self.assertEqual(set(diagnostic['annualized_volatility']), {'BBB', 'CCC'})
        self.assertEqual(diagnostic['coverage']['covered_count'], 2)
        self.assertEqual(result['inverse_vol']['status'], 'insufficient_data')
        derived = json.loads((self.task / 'inputs' / 'derived_volatilities.json').read_text())
        self.assertNotIn('AAA', derived['volatility_observations'])

    def test_partial_f_and_bad_prior_native_cli_report_both_orders(self):
        native = json.loads((self.root / 'native.json').read_text())
        fact_input = Path(native['fact_prepare_input'])
        original = json.loads(fact_input.read_text())['projections']
        good_prior = json.loads((self.root / 'feedback.json').read_text())['comparisons'][0]
        for bad_first in (False, True):
            with self.subTest(bad_first=bad_first):
                self.task = self.root / ('mixed-' + str(bad_first))
                bad_spec = dict(original[0], cik='0000000001')
                fact_input.write_text(json.dumps({'projections': [bad_spec] + original if bad_first else original + [bad_spec]}))
                bad_prior = dict(good_prior, comparison_id='bad', prior_ref=dict(good_prior['prior_ref'], local_path='missing-prior.json'))
                self.save('feedback.json', {'as_of_date': date.today().isoformat(), 'comparisons': [bad_prior, good_prior]})
                spec = self.risk_spec()
                spec['histories']['AAA']['currency'] = 'USD'
                self.manifest['risk'] = spec
                manifest = self.save('workflow.json', self.manifest)
                run = subprocess.run([sys.executable, '-B', str(Path(pia.__file__)), 'research-workflow', '--input-file', str(manifest),
                                      '--evidence-root', str(self.root), '--task-dir', str(self.task)],
                                     capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
                result = json.loads(run.stdout)['result']
                self.assertEqual(result['branches']['fact_prepare']['status'], 'incomplete')
                self.assertTrue(result['branches']['fact_prepare']['projections'])
                self.assertEqual(result['branches']['fundamental_diagnostic']['source_binding']['items'][0]['status'], 'source_bound_numeric_consistency')
                items = result['branches']['expectation_feedback']['comparisons']
                self.assertEqual(items[1]['comparison']['delta']['value'], 2)
                self.assertEqual(items[0]['errors'][-1]['type'], 'FeedbackError')
                self.assertTrue(any(e['type'] == 'FileNotFoundError' for e in items[0]['errors']))
                self.assertEqual(result['branches']['risk']['inverse_vol']['status'], 'insufficient_data')
                self.assertEqual(pia_report.main(['--run-dir', str(self.task), '--out', str(self.task / 'report.md'), '--expect-scope', 'research_only']), 0)
                text = (self.task / 'report.md').read_text(encoding='utf-8')
                self.assertIn('FileNotFoundError', text)
                self.assertIn('projection_index', text)
                self.assertIn('delta', text)

    def test_native_f_to_m_j_report_readiness_review(self):
        original = {p: p.read_bytes() for p in (self.root / 'prior.json', self.root / 'native.json')}
        result = self.run_workflow()
        self.assertEqual(result['status'], 'complete', result)
        m = result['branches']['fundamental_diagnostic']
        self.assertEqual(m['source_binding']['items'][0]['status'], 'source_bound_numeric_consistency')
        self.assertAlmostEqual(m['scenario_analysis']['comparisons'][0]['net_return_deltas']['base'], 10 / 102)
        j = result['branches']['expectation_feedback']['comparisons'][0]
        self.assertEqual(j['comparison']['delta']['value'], 2)
        self.assertFalse(result['formal_use_allowed'])
        self.assertFalse(m['alpha_eligible'])
        self.assertEqual(pia_report.main(['--run-dir', str(self.task), '--out', str(self.task / 'report.md'), '--expect-scope', 'research_only']), 0)
        rendered = (self.task / 'report.md').read_text(encoding='utf-8')
        for expected in ('prior_timing_unverified', 'source_bound_numeric_consistency', 'net_return_deltas', '非交易就绪'):
            self.assertIn(expected, rendered)
        artifacts, assessment = pia_readiness.load_run_artifacts(self.task)
        ready = pia_readiness.build_rollup(self.task, artifacts, assessment)
        self.assertEqual(ready['status'], 'not_ready')
        self.assertEqual(ready['research_diagnostics']['branches']['expectation_feedback']['comparisons'][0]['comparison']['delta']['value'], 2)
        brief = pia_review_pack.render_brief('synthetic', {'purpose': 'test', 'required_tools': ['local'], 'forbidden': ['write'], 'questions': ['check'], 'output_contract': ['findings']}, self.task, [], [])
        self.assertIn('prior_timing_unverified', brief)
        for path, raw in original.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_native_cli_thin_e2e_and_help(self):
        path = self.save('workflow.json', self.manifest)
        command = [sys.executable, '-B', str(Path(pia.__file__)), 'research-workflow', '--input-file', str(path), '--evidence-root', str(self.root), '--task-dir', str(self.task)]
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        envelope = json.loads(completed.stdout)
        self.assertEqual(envelope['result']['branches']['expectation_feedback']['comparisons'][0]['comparison']['delta']['value'], 2)
        help_run = subprocess.run([sys.executable, '-B', str(Path(pia.__file__)), '--help'], capture_output=True, text=True, timeout=30)
        for name in ('fact-prepare', 'fundamental-diagnostic', 'expectation-feedback', 'research-workflow'):
            self.assertIn(name, help_run.stdout)

    def test_actual_existing_risk_and_builders(self):
        self.manifest['risk'] = self.risk_spec()
        result = self.run_workflow()
        risk_result = result['branches']['risk']
        self.assertEqual(risk_result['status'], 'complete', risk_result)
        self.assertEqual(risk_result['diagnostic']['coverage']['covered_count'], 2)
        self.assertEqual(risk_result['inverse_vol']['status'], 'complete')
        self.assertEqual(risk_result['scenario']['status'], 'complete')
        policy = json.loads(Path(risk_result['inverse_vol']['policy_file']).read_text())
        self.assertEqual(policy['bucket_targets'], {'core': 0.8, 'satellite': 0.2})
        derived = json.loads((self.task / 'inputs' / 'derived_volatilities.json').read_text())
        self.assertEqual(derived['volatility_observations']['AAA']['observation_count'], 39)

    def test_missing_window_buckets_fractions_aggregated_without_defaults(self):
        spec = self.risk_spec()
        del spec['window_start']
        policy = json.loads((self.root / 'policy.json').read_text())
        for key in ('core', 'core_fraction', 'satellite_fraction'):
            policy['bucket_policy'].pop(key)
        self.save('policy.json', policy)
        self.manifest['risk'] = spec
        r = self.run_workflow()
        missing = r['gaps']['rule_confirmation_needed']
        for key in ('risk.window_start', 'bucket_policy.core', 'bucket_policy.core_fraction', 'bucket_policy.satellite_fraction'):
            self.assertIn(key, missing)
        self.assertFalse((self.task / 'inputs' / 'inverse_volatility_policy.json').exists())
        self.assertEqual(r['branches']['fundamental_diagnostic']['status'], 'complete')

    def test_provider_error_keeps_independent_results(self):
        self.save('native.json', {'status': 'error', 'errors': ['synthetic HTTP 503']})
        r = self.run_workflow()
        self.assertEqual(r['branches']['fact_prepare']['status'], 'failed')
        self.assertIn('503', json.dumps(r['gaps']['provider/error']))
        self.assertEqual(r['branches']['fundamental_diagnostic']['status'], 'complete')
        self.assertNotIn('no_data', json.dumps(r))

    def test_escape_output_overlap_and_existing_outputs_rejected(self):
        self.manifest['fundamental_input'] = '../escape.json'
        with self.assertRaises(ValueError):
            self.run_workflow()
        self.assertFalse(self.task.exists())
        self.manifest['fundamental_input'] = 'fundamental.json'
        self.run_workflow()
        with self.assertRaises(ValueError):
            self.run_workflow()
        with self.assertRaises(ValueError):
            workflow.run(self.root / 'workflow.json', self.root, self.root.parent / 'outside')

    def test_malformed_dependency_preserves_f_and_j(self):
        (self.root / 'fundamental.json').write_text('{', encoding='utf-8')
        r = self.run_workflow()
        self.assertEqual(r['branches']['fact_prepare']['status'], 'complete')
        self.assertEqual(r['branches']['expectation_feedback']['status'], 'complete')
        self.assertIn('JSONDecodeError', json.dumps(r['gaps']['provider/error']))
        self.assertNotIn('no_data', json.dumps(r))

    def test_missing_dependency_preserves_other_branches(self):
        self.manifest['fundamental_input'] = 'missing.json'
        r = self.run_workflow()
        self.assertEqual(r['branches']['expectation_feedback']['status'], 'complete')
        self.assertIn('FileNotFoundError', json.dumps(r['branches']['fundamental_diagnostic']))

    def test_scenario_gap_does_not_block_inverse_vol(self):
        self.manifest['risk'] = self.risk_spec()
        p = json.loads((self.root / 'policy.json').read_text())
        del p['horizon']
        self.save('policy.json', p)
        r = self.run_workflow()
        self.assertEqual(r['branches']['risk']['inverse_vol']['status'], 'complete')
        self.assertEqual(r['branches']['risk']['diagnostic']['status'], 'complete')
        self.assertEqual(r['branches']['risk']['scenario']['status'], 'insufficient_data')

    def test_native_bad_json_and_missing_file_classify_errors(self):
        bad = self.root / 'bad.json'
        bad.write_text('{', encoding='utf-8')
        for command in ('fact-prepare', 'fundamental-diagnostic', 'expectation-feedback', 'research-workflow'):
            for source, expected in ((bad, 'JSONDecodeError'), (self.root / 'absent.json', 'FileNotFoundError')):
                args = [sys.executable, '-B', str(Path(pia.__file__)), command, '--input-file', str(source), '--evidence-root', str(self.root)]
                if command in ('fact-prepare', 'research-workflow'):
                    args += ['--task-dir', str(self.root / (command + '-out'))]
                r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertNotEqual(r.returncode, 0)
                envelope = json.loads(r.stdout)
                expected_error = 'BindingError:invalid_json' if command == 'fact-prepare' and expected == 'JSONDecodeError' else expected
                self.assertIn(expected_error, json.dumps(envelope))
                self.assertNotIn('no_data', json.dumps(envelope))

    def test_no_implicit_fetch_private_scan_or_journal(self):
        with mock.patch.object(socket, 'create_connection', side_effect=AssertionError('no fetch')), \
             mock.patch.object(Path, 'glob', side_effect=AssertionError('no scan')), \
             mock.patch.object(Path, 'rglob', side_effect=AssertionError('no scan')):
            r = self.run_workflow()
        self.assertEqual(r['status'], 'complete')
        self.assertFalse((self.task / 'journal.json').exists())

    def test_explicit_quantitative_branch_never_promotes_fundamental(self):
        self.save('fundamental.json', {'research_lane': 'quantitative'})
        r = self.run_workflow()
        m = r['branches']['fundamental_diagnostic']
        self.assertEqual(m['status'], 'not_evaluated')
        self.assertFalse(m['alpha_eligible'])
        self.assertFalse(m['alpha_path']['fundamental_diagnostic_is_alpha_evidence'])


if __name__ == '__main__':
    unittest.main()
