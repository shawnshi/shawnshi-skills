"""Synthetic raw-capture feedback tests; all network access forbidden."""
import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pia_expectation_feedback as feedback
import pia_fact_prepare as facts
import sec_edgar_fundamentals as sec
from test_p1p2_fact_prepare import Response, company_bytes


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.network = mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('PIA_TEST_TMP'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.today = date.today().isoformat()
        responses = {sec.TICKER_MAP_URL: b'{"0":{"ticker":"MSFT","cik_str":789019}}',
                     sec.COMPANYFACTS_URL.format(cik='0000789019'): company_bytes()}
        session = mock.Mock()
        session.get.side_effect = lambda url, **kwargs: Response(responses[url])
        report = sec.build_report(['MSFT'], as_of=date.today(), user_agent='synthetic',
                                  session=session, decision_scope='research_only', artifact_dir=self.root)
        spec = facts.load(Path(report['fact_prepare_input']).read_bytes())['projections'][0]
        self.document = facts.project(spec, self.root)
        self.projection_ref = self.save('projection.json', self.document, '/facts/0')
        self.expectation = {'symbol': 'MSFT', 'metric': 'diluted_eps', 'unit': 'USD/shares',
                            'period': '2023', 'scope': 'consolidated',
                            'period_start': '2023-01-01', 'period_end': '2023-12-31',
                            'recorded_at': '2022-12-01T00:00:00Z', 'deadline': '2024-02-15',
                            'expected_value': 8}
        self.prior_ref = self.save_prior()
        self.payload = {'as_of_date': self.today, 'comparisons': [
            {'comparison_id': 'eps', 'prior_ref': self.prior_ref, 'actual_refs': [self.projection_ref]}]}

    def save(self, name, document, pointer):
        raw = json.dumps(document, ensure_ascii=False).encode('utf-8')
        (self.root / name).write_bytes(raw)
        return {'local_path': name, 'content_sha256': hashlib.sha256(raw).hexdigest(), 'pointer': pointer}

    def save_prior(self):
        ref = self.save('prior.json', {'original_expectation': self.expectation}, '/original_expectation')
        if hasattr(self, 'payload'):
            self.payload['comparisons'][0]['prior_ref'] = ref
        return ref

    def run_feedback(self):
        return feedback.evaluate(self.payload, evidence_root=self.root)

    def item(self):
        return self.run_feedback()['comparisons'][0]

    def test_verified_positive_delta_relative_and_sensitivity(self):
        self.expectation.update(direction='higher', relative_error_definition='delta_over_abs_expected',
                                valuation_sensitivity={'method': 'linear_absolute_delta', 'input_unit': 'USD/shares',
                                                       'output_unit': 'USD/share_value', 'coefficient': 5,
                                                       'statement': 'Synthetic user sensitivity, conditional only'})
        self.save_prior()
        result = self.run_feedback()
        item = result['comparisons'][0]
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(item['actual']['fact']['value'], 10)
        self.assertEqual(item['comparison']['delta']['value'], 2)
        self.assertEqual(item['comparison']['relative_error']['value'], 0.25)
        self.assertTrue(item['comparison']['directional_target_met'])
        self.assertEqual(item['valuation_implications']['value'], 10)
        self.assertEqual(item['valuation_implications']['status'], 'conditional_only')
        self.assertFalse(result['formal_use_allowed'])
        self.assertFalse(item['formal_use_allowed'])

    def test_decline_inside_expected_range_is_not_falsification(self):
        del self.expectation['expected_value']
        self.expectation.update(expected_range={'lower': 8, 'upper': 12}, previous_actual=15)
        self.save_prior()
        item = self.item()
        self.assertEqual(item['status'], 'complete')
        self.assertEqual(item['comparison']['range_position'], 'within')
        self.assertEqual(item['comparison']['delta'], {'unit': 'USD/shares', 'definition': 'actual_minus_expected',
                                                      'lower': -2, 'upper': 2})
        self.assertIsNone(item['comparison']['directional_target_met'])
        self.assertEqual(item['thesis_implications']['status'], 'not_assessed')
        self.assertNotIn('fatal_event_status', item)

    def test_zero_and_negative_base(self):
        for base, delta, relative in [(0, 10, None), (-5, 15, 3)]:
            with self.subTest(base=base):
                self.expectation.update(expected_value=base, relative_error_definition='delta_over_abs_expected')
                self.save_prior()
                item = self.item()
                self.assertEqual(item['comparison']['delta']['value'], delta)
                if relative is None:
                    self.assertEqual(item['comparison']['relative_error']['reason'], 'zero_expected_base')
                    self.assertNotIn('value', item['comparison']['relative_error'])
                else:
                    self.assertEqual(item['comparison']['relative_error']['value'], relative)

    def test_missing_sensitivity_direction_and_relative_definition_not_invented(self):
        item = self.item()
        self.assertEqual(item['status'], 'complete')
        self.assertEqual(item['valuation_implications']['reason'], 'explicit_sensitivity_required')
        self.assertIsNone(item['comparison']['directional_target_met'])
        self.assertEqual(item['comparison']['relative_error']['reason'], 'explicit_definition_required')

    def test_posthoc_trusted_claims_never_prospective(self):
        for timestamp in ('2022-12-01T00:00:00Z', self.today + 'T00:00:00Z'):
            self.expectation.update(recorded_at=timestamp, trusted=True, verified=True, reviewed=True,
                                    captured_at='2020-01-01T00:00:00Z', publication_precision='exact')
            self.save_prior()
            result = self.run_feedback()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['feedback_mode'], 'descriptive_historical_comparison')
            self.assertEqual(result['prior_timing'], 'prior_timing_unverified')
            self.assertEqual(result['comparisons'][0]['prior_timing'], 'prior_timing_unverified')
            self.assertFalse(result['formal_use_allowed'])
            self.assertNotIn('prospective_error', result)

    def test_dimensions_must_match(self):
        for key, value in [('symbol', 'OTHER'), ('metric', 'revenue'), ('unit', 'EUR'),
                           ('period', '2022'), ('scope', 'segment:one'), ('symbol', 'ＭSFT'),
                           ('period', '２０２３'), ('period', 'FY2023'), ('period', '2023q4')]:
            original = self.expectation[key]
            with self.subTest(key=key, value=value):
                self.expectation[key] = value
                self.save_prior()
                item = self.item()
                self.assertEqual(item['status'], 'incomplete')
                self.assertIsNotNone(item['actual'])
                self.assertIsNone(item['comparison'])
            self.expectation[key] = original

    def test_actual_raw_or_projection_tamper_rejected(self):
        for target in ('projection', 'raw'):
            with self.subTest(target=target):
                if target == 'projection':
                    doc = copy.deepcopy(self.document)
                    doc['facts'][0]['value'] = 900
                    ref = self.save('bad-projection.json', doc, '/facts/0')
                    self.payload['comparisons'][0]['actual_refs'] = [ref]
                    self.assertIsNone(self.item()['actual'])
                else:
                    self.payload['comparisons'][0]['actual_refs'] = [self.projection_ref]
                    capture = self.document['projection']['captures']['companyfacts']
                    path = self.root / capture['raw_artifact']
                    path.write_bytes(path.read_bytes() + b' ')
                    item = self.item()
                    self.assertIsNone(item['actual'])
                    self.assertTrue(item['errors'])

    def test_hash_prior_failure_preserves_actual(self):
        self.payload['comparisons'][0]['prior_ref']['content_sha256'] = '0' * 64
        item = self.item()
        self.assertEqual(item['status'], 'incomplete')
        self.assertEqual(item['actual']['fact']['value'], 10)
        self.assertIsNone(item['expectation'])

    def test_self_reported_actual_not_accepted(self):
        self.payload['comparisons'][0].update(actual=999, reviewed=True)
        item = self.item()
        self.assertEqual(item['status'], 'incomplete')
        self.assertEqual(item['actual']['fact']['value'], 10)
        self.assertIsNone(item['comparison'])
        self.payload['comparisons'][0]['actual_refs'] = []
        self.assertIsNone(self.item()['actual'])

    def test_reference_order_and_conflicts(self):
        same = self.save('same-projection.json', self.document, '/facts/0')
        other = dict(self.projection_ref, pointer='/facts/1')
        for refs in ([self.projection_ref, same], [same, self.projection_ref]):
            self.payload['comparisons'][0]['actual_refs'] = refs
            self.assertEqual(self.item()['comparison']['delta']['value'], 2)
        for refs in ([self.projection_ref, other], [other, self.projection_ref]):
            self.payload['comparisons'][0]['actual_refs'] = refs
            item = self.item()
            self.assertIsNone(item['actual'])
            self.assertIn('conflicting_actual_references', str(item['errors']))

    def test_invalid_item_does_not_mask_independent_item(self):
        bad = copy.deepcopy(self.payload['comparisons'][0])
        bad['comparison_id'] = 'unrelated'
        bad['prior_ref']['local_path'] = 'missing.json'
        self.payload['comparisons'].append(bad)
        result = self.run_feedback()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['comparisons'][0]['comparison']['delta']['value'], 2)
        self.assertEqual(result['comparisons'][1]['actual']['fact']['value'], 10)
        self.assertIn('FileNotFoundError', str(result['comparisons'][1]['errors']))

    def test_sensitivity_errors_do_not_erase_numeric_comparison(self):
        self.expectation['valuation_sensitivity'] = {'method': 'linear_absolute_delta', 'input_unit': 'EUR'}
        self.save_prior()
        item = self.item()
        self.assertEqual(item['status'], 'incomplete')
        self.assertEqual(item['comparison']['delta']['value'], 2)
        self.assertEqual(item['actual']['fact']['value'], 10)
        self.assertNotIn('value', item['valuation_implications'])

    def test_paths_pointers_and_ordinary_actual_rejected(self):
        for path in ('../outside.json', '/outside.json', 'C:/outside.json', 'raw\\file.json'):
            with self.subTest(path=path):
                self.payload['comparisons'][0]['prior_ref']['local_path'] = path
                self.assertIsNone(self.item()['expectation'])
        self.payload['comparisons'][0]['actual_refs'] = [self.save('ordinary.json', {'facts': [self.document['facts'][0]]}, '/facts/0')]
        self.assertIsNone(self.item()['actual'])

    def test_bool_nonfinite_high_precision_and_duplicate_json_rejected(self):
        for token in ('true', 'NaN', 'Infinity', '0.123456789123456789'):
            raw = json.dumps({'original_expectation': self.expectation}).replace('"expected_value": 8', '"expected_value": ' + token).encode()
            (self.root / 'prior.json').write_bytes(raw)
            self.payload['comparisons'][0]['prior_ref']['content_sha256'] = hashlib.sha256(raw).hexdigest()
            self.assertIsNone(self.item()['expectation'])
        with self.assertRaises(feedback.FeedbackError):
            feedback.load_json(b'{"a":1,"a":2}')

    def test_due_and_instant_period(self):
        self.expectation['deadline'] = '9999-12-31'
        self.save_prior()
        self.assertEqual(self.item()['comparison']['due_status'], 'not_due')
        equity_index = next(i for i, f in enumerate(self.document['facts']) if f['metric'] == 'stockholders_equity')
        fact = self.document['facts'][equity_index]
        self.expectation.update(fact, expected_value=90, period_start='2023-12-31', period_end='2023-12-31')
        self.expectation.pop('value')
        self.save_prior()
        self.payload['comparisons'][0]['actual_refs'] = [dict(self.projection_ref, pointer=f'/facts/{equity_index}')]
        self.assertEqual(self.item()['comparison']['delta']['value'], 10)

    def test_malformed_root_duplicate_ids_and_missing_time(self):
        for payload in (None, {}, {'as_of_date': self.today, 'comparisons': []},
                        {'as_of_date': '9999-01-01', 'comparisons': self.payload['comparisons']}):
            self.assertEqual(feedback.evaluate(payload, evidence_root=self.root)['status'], 'incomplete')
        self.payload['comparisons'].append(copy.deepcopy(self.payload['comparisons'][0]))
        self.assertEqual(self.run_feedback()['comparisons'], [])
        self.payload['comparisons'].pop()
        self.expectation.pop('recorded_at')
        self.save_prior()
        self.assertEqual(self.item()['actual']['fact']['value'], 10)
        self.assertIsNone(self.item()['expectation'])

    def test_cli_roundtrip_and_invalid_input(self):
        input_file = self.root / 'input.json'
        input_file.write_text(json.dumps(self.payload), encoding='utf-8')
        script = Path(__file__).resolve().with_name('pia_expectation_feedback.py')
        command = [sys.executable, '-B', str(script), '--input-file', str(input_file),
                   '--evidence-root', str(self.root)]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(json.loads(proc.stdout)['comparisons'][0]['comparison']['delta']['value'], 2)
        input_file.write_text('{', encoding='utf-8')
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('JSONDecodeError', proc.stdout)


if __name__ == '__main__':
    unittest.main()
