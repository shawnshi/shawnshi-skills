"""Synthetic byte/rule binding regressions; never read financial user files."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pia_thesis_ledger as ledger
from test_p1_thesis_condition_not_due import BINDING, NOW, assessment, build_pack
from thesis_evidence_gate import evaluate_thesis_evidence


def condition(**changes):
    row = {'id': 'c1', 'metric': 'revenue', 'operator': 'lt', 'threshold': 10,
           'unit': 'USD', 'period': {'frequency': 'quarterly', 'end': '2026Q2',
                                   'count': 1, 'basis': 'absolute', 'scope': 'consolidated'},
           'due': '2026-08-01', 'channel': 'structured issuer data'}
    row.update(changes)
    return row


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger_path = self.root / 'conditions.json'
        self.source_path = self.root / 'source.json'
        self.ledger = {'schema_version': 'pia_thesis_ledger_v1', 'decision_scope': 'advisory',
                       'created_at': '2026-01-01T00:00:00+00:00', 'symbols': {'SYNTH': {'versions': [{
                           'version': 1, 'confirmed_at': '2026-02-01',
                           'source_locator': 'dataset://pia/user-confirmation/synthetic',
                           'recorded_at': '2026-02-01T12:00:00+00:00',
                           'conditions': [condition()]}]}}}
        self.pack = build_pack([assessment('SYNTH', 'no_fatal_breach_verified', 'aapl',
                                           condition_ids=['c1'], condition_version=1)])
        self.pack['schema_version'] = 'pia_thesis_red_team_v2'
        self.fact = {'symbol': 'SYNTH', 'metric': 'revenue', 'value': 9,
                     'unit': 'USD', 'period': '2026Q2', 'scope': 'consolidated'}
        self.source = {'facts': [self.fact]}
        self.write_source()
        self.write_ledger()

    @property
    def rule(self):
        return self.ledger['symbols']['SYNTH']['versions'][-1]['conditions'][0]

    @property
    def claim(self):
        return self.pack['assessments'][0]

    def write_ledger(self):
        self.ledger_path.write_text(json.dumps(self.ledger), encoding='utf-8')
        self.pack['conditions_sha256'] = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()

    def write_source(self):
        self.source_path.write_text(json.dumps(self.source), encoding='utf-8')
        item = next(item for item in self.pack['evidence_items'] if item['evidence_id'] == 'aapl')
        item.update(content_sha256=hashlib.sha256(self.source_path.read_bytes()).hexdigest(),
                    local_path='source.json', fact_pointer='/facts/0')

    def evaluate(self, *, expected=None, trusted=True, root=True):
        return evaluate_thesis_evidence(
            self.pack, expected_symbols=expected or ['SYNTH'],
            portfolio_snapshot_binding=copy.deepcopy(BINDING), evaluation_epoch=NOW.timestamp(),
            conditions_file=self.ledger_path if trusted else None,
            evidence_root=self.root if root else None)

    def assert_no_hit(self, report, reason=None):
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['verified_hits'], [])
        self.assertNotEqual(report['fatal_event_status'], 'no_fatal_breach_verified')
        if reason:
            self.assertIn(reason, json.dumps(report))

    def test_recomputes_hit_despite_submitted_non_hit_and_coverage_gaps(self):
        self.pack['scope_coverage'] = {}
        report = self.evaluate(expected=['SYNTH', 'OTHER'])
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['fatal_event_status'], 'fatal_breach_detected')
        self.assertEqual(report['fatal_symbols'], ['SYNTH'])
        self.assertEqual(report['condition_results'][0]['status'], 'verified_fatal_breach')
        self.assertEqual(report['verified_hits'][0]['observed_values'], ['9'])
        self.assertEqual(report['verified_hits'][0]['source_bindings'][0]['fact_pointer'], '/facts/0')
        self.assertIn('missing_assessment_symbols:OTHER', report['errors'])

    def test_non_hit_is_local_and_never_global_all_clear(self):
        self.fact['value'] = 11
        self.claim['conclusion'] = 'fatal_breach'
        self.write_source()
        report = self.evaluate()
        self.assert_no_hit(report)
        self.assertEqual(report['condition_results'][0]['status'], 'verified_non_hit')
        self.assertIn('semantic_scope_coverage_not_verified', report['warnings'])
        self.assertEqual(report['submitted_claims'][0]['conclusion'], 'fatal_breach')

    def add_referenced_fact(self, fact, evidence_id='second'):
        self.source['facts'].append(fact)
        self.write_source()
        item = copy.deepcopy(next(item for item in self.pack['evidence_items']
                                  if item['evidence_id'] == 'aapl'))
        item.update(evidence_id=evidence_id, fact_pointer='/facts/1')
        self.pack['evidence_items'].append(item)
        self.claim['evidence_ids'] = ['aapl', evidence_id]

    def test_unicode_period_aliases_are_insufficient_in_both_orders(self):
        for frequency, ascii_period, unicode_period in [
                ('quarterly', '2026Q2', '２０２６Q2'),
                ('annual', '2025', '２０２５')]:
            with self.subTest(frequency=frequency):
                self.rule['period'].update(frequency=frequency, end=ascii_period)
                self.fact['period'] = ascii_period
                self.source = {'facts': [self.fact]}
                self.pack['evidence_items'] = [item for item in self.pack['evidence_items']
                                               if item['evidence_id'] != 'second']
                self.add_referenced_fact(dict(self.fact, value=11, period=unicode_period))
                self.write_ledger()
                for order in [['aapl', 'second'], ['second', 'aapl']]:
                    self.claim['evidence_ids'] = order
                    report = self.evaluate()
                    self.assert_no_hit(report, 'unsupported_period')
                    self.assertEqual(report['condition_results'][0]['status'], 'insufficient_evidence')

    def test_unicode_condition_period_is_not_executable(self):
        self.rule['period']['end'] = '２０２６Q2'
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'unsupported_period')

    def test_duplicate_ascii_conflicts_are_insufficient_in_both_orders(self):
        self.add_referenced_fact(dict(self.fact, value=11))
        for order in [['aapl', 'second'], ['second', 'aapl']]:
            self.claim['evidence_ids'] = order
            self.assert_no_hit(self.evaluate(), 'conflicting_facts')

    def test_identical_duplicate_ascii_facts_preserve_hit(self):
        self.add_referenced_fact(dict(self.fact))
        for order in [['aapl', 'second'], ['second', 'aapl']]:
            self.claim['evidence_ids'] = order
            self.assertEqual(self.evaluate()['fatal_symbols'], ['SYNTH'])

    def test_bad_period_data_does_not_hide_independent_condition_hit(self):
        self.ledger['symbols']['SYNTH']['versions'][0]['conditions'].append(
            condition(id='c2', metric='profit'))
        self.claim['condition_ids'] = ['c1', 'c2']
        self.fact['metric'] = 'profit'
        self.source = {'facts': [self.fact]}
        self.write_ledger()
        self.add_referenced_fact(dict(self.fact, metric='revenue', period='２０２６Q2'))
        for order in [['aapl', 'second'], ['second', 'aapl']]:
            self.claim['evidence_ids'] = order
            report = self.evaluate()
            self.assertEqual(report['fatal_symbols'], ['SYNTH'])
            self.assertEqual([r['condition_id'] for r in report['verified_hits']], ['c2'])
            self.assertEqual(report['condition_results'][0]['status'], 'insufficient_evidence')
        self.source['facts'][1].update(period='2026Q2', value=9)
        self.source['facts'].append(dict(self.source['facts'][1], value=11))
        self.write_source()
        for item in self.pack['evidence_items']:
            if item['evidence_id'] == 'second':
                item['content_sha256'] = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        third = copy.deepcopy(next(item for item in self.pack['evidence_items']
                                  if item['evidence_id'] == 'second'))
        third.update(evidence_id='third', fact_pointer='/facts/2')
        self.pack['evidence_items'].append(third)
        for order in [['aapl', 'second', 'third'], ['third', 'second', 'aapl']]:
            self.claim['evidence_ids'] = order
            report = self.evaluate()
            self.assertEqual(report['fatal_symbols'], ['SYNTH'])
            self.assertEqual([r['condition_id'] for r in report['verified_hits']], ['c2'])
            self.assertIn('conflicting_facts', report['condition_results'][0]['reason'])

    def test_strict_and_inclusive_boundary(self):
        self.fact['value'] = 10
        self.write_source()
        for operator, hit in [('lt', False), ('lte', True), ('gt', False), ('gte', True), ('eq', True)]:
            with self.subTest(operator=operator):
                self.rule['operator'] = operator
                self.write_ledger()
                report = self.evaluate()
                self.assertEqual(bool(report['verified_hits']), hit)

    def test_real_current_future_condition(self):
        self.rule['due'] = '2027-01-01'
        self.write_ledger()
        self.claim.update(conclusion='condition_not_due', due_date='2027-01-01')
        report = self.evaluate(root=False)
        self.assertEqual(report['not_due_symbols'], ['SYNTH'])
        self.assertEqual(report['earliest_due_date'], '2027-01-01')
        self.assertEqual(report['condition_results'][0]['status'], 'verified_not_due')
        self.assertEqual(report['fatal_event_status'], 'no_condition_due_yet')
        self.assertEqual(report['status'], 'incomplete')

    def test_today_is_due_and_forged_future_date_cannot_hide_hit(self):
        self.rule['due'] = NOW.date().isoformat()
        self.write_ledger()
        self.claim.update(conclusion='condition_not_due', due_date='2027-01-01')
        report = self.evaluate()
        self.assertEqual(report['not_due_symbols'], [])
        self.assertEqual(report['fatal_symbols'], ['SYNTH'])

    def test_wrong_future_date_is_not_verified_not_due(self):
        self.rule['due'] = '2027-01-01'
        self.write_ledger()
        self.claim.update(conclusion='condition_not_due', due_date='2028-01-01')
        self.assert_no_hit(self.evaluate(), 'submitted_due_date_mismatch')
        self.assertEqual(self.evaluate()['not_due_symbols'], [])

    def test_declaration_only_v1_with_fake_url_zero_hash(self):
        for conclusion in ['fatal_breach', 'no_fatal_breach_verified', 'condition_not_due']:
            self.pack['schema_version'] = 'pia_thesis_red_team_v1'
            self.pack.pop('conditions_sha256', None)
            self.claim.update(conclusion=conclusion, due_date='2027-01-01')
            for item in self.pack['evidence_items']:
                item.update(source_locator='https://example.com/not-a-verified-source.pdf',
                            content_sha256='0' * 64)
            report = self.evaluate(trusted=False)
            self.assert_no_hit(report, 'explicit_conditions_file_required')
            self.assertEqual(report['verification_status'], 'declaration_only')
            self.assertEqual(report['submitted_claims'][0]['conclusion'], conclusion)

    def test_hashes_are_of_actual_bytes(self):
        self.pack['evidence_items'][3]['content_sha256'] = '0' * 64
        self.assert_no_hit(self.evaluate(), 'source_hash_mismatch')
        self.write_source()
        self.pack['conditions_sha256'] = '0' * 64
        self.assert_no_hit(self.evaluate(), 'conditions_hash_mismatch')

    def test_missing_source_or_root_is_not_no_data(self):
        self.assert_no_hit(self.evaluate(root=False), 'explicit_evidence_root_required')
        self.source_path.unlink()
        self.assert_no_hit(self.evaluate(), 'FileNotFoundError')

    def test_unsupported_pdf_or_missing_location(self):
        item = self.pack['evidence_items'][3]
        pdf = self.root / 'source.pdf'
        pdf.write_bytes(b'synthetic pdf')
        item.update(local_path='source.pdf', content_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
        self.assert_no_hit(self.evaluate(), 'unsupported_source_format')
        self.write_source()
        item['fact_pointer'] = '/facts/9'
        self.assert_no_hit(self.evaluate(), 'fact_pointer_not_found')

    def test_path_escapes_are_rejected(self):
        item = self.pack['evidence_items'][3]
        for path in ['../source.json', str(self.source_path), 'C:/source.json',
                     '//server/share.json', 'folder/../../source.json', '..\\source.json']:
            with self.subTest(path=path):
                item['local_path'] = path
                self.assert_no_hit(self.evaluate())

    def test_symlink_escape(self):
        link = self.root / 'link.json'
        try:
            link.symlink_to(self.source_path)
        except OSError as exc:
            # Windows commonly requires developer mode. Do not silently skip the
            # escape gate; a junction escape is tested by the runner if needed.
            self.fail('symlink gate unavailable: ' + str(exc))
        self.pack['evidence_items'][3]['local_path'] = 'link.json'
        self.assert_no_hit(self.evaluate(), 'evidence_link_forbidden')

    def test_condition_identity_and_versions(self):
        for key, value in [('condition_version', 2), ('condition_version', True),
                           ('condition_ids', ['wrong']), ('condition_ids', [])]:
            with self.subTest(key=key, value=value):
                original = copy.deepcopy(self.claim)
                self.claim[key] = value
                self.assert_no_hit(self.evaluate(), 'current_condition_')
                self.claim.clear()
                self.claim.update(original)
        newest = copy.deepcopy(self.ledger['symbols']['SYNTH']['versions'][0])
        newest.update(version=2, confirmed_at='2026-03-01', recorded_at='2026-03-01T12:00:00+00:00')
        self.ledger['symbols']['SYNTH']['versions'].append(newest)
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'current_condition_version_mismatch')
        self.claim['condition_version'] = 2
        self.assertTrue(self.evaluate()['verified_hits'])

    def test_missing_conditions_and_unconfirmed_metadata(self):
        version = self.ledger['symbols']['SYNTH']['versions'][0]
        for key, value in [('confirmed_at', '2027-01-01'), ('recorded_at', '2027-01-01T00:00:00Z'),
                           ('recorded_at', '2026-02-01'), ('source_locator', ''),
                           ('source_locator', 'https://example.com/confirmation'), ('conditions', [])]:
            with self.subTest(key=key):
                original = copy.deepcopy(version)
                version[key] = value
                self.write_ledger()
                self.assert_no_hit(self.evaluate())
                version.clear()
                version.update(original)
        self.ledger['symbols'] = {}
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'symbol_not_in_ledger')

    def test_fact_dimensions_must_match_and_caller_values_are_ignored(self):
        self.claim.update(extracted_value=-1000, reviewed=True)
        self.fact['value'] = 12
        self.write_source()
        self.assert_no_hit(self.evaluate())
        self.fact['value'] = 9
        for key, value in [('symbol', 'OTHER'), ('metric', 'profit'), ('unit', 'CNY'),
                           ('period', '2026Q1'), ('scope', 'segment:x')]:
            with self.subTest(key=key):
                original = self.fact[key]
                self.fact[key] = value
                self.write_source()
                self.assert_no_hit(self.evaluate(), 'required_period_fact_missing')
                self.fact[key] = original

    def test_non_finite_and_boolean_values(self):
        for value in [float('nan'), float('inf'), float('-inf'), True, '9']:
            with self.subTest(value=str(value)):
                self.fact['value'] = value
                self.write_source()
                self.assert_no_hit(self.evaluate())
        self.fact['value'] = 9
        self.write_source()
        self.rule['threshold'] = float('inf')
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'non_finite_json_number')

    def test_incomplete_and_qualitative_rules_are_not_non_hits_or_not_due(self):
        for changes in [{'period': 'FY2027'}, {'unit': ''}, {'operator': 'qualitative'},
                        {'threshold': None}, {'period': {'frequency': 'quarterly'}},
                        {'due': '持续'}]:
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.rule)
                self.rule.update(changes)
                self.write_ledger()
                self.assert_no_hit(self.evaluate())
                self.assertEqual(self.evaluate()['not_due_symbols'], [])
                self.rule.clear()
                self.rule.update(original)

    def test_missing_current_condition_cannot_be_all_clear_but_retains_hit(self):
        self.ledger['symbols']['SYNTH']['versions'][0]['conditions'].append(condition(id='c2'))
        self.write_ledger()
        report = self.evaluate()
        self.assertEqual(len(report['verified_hits']), 1)
        self.assertEqual(report['condition_results'][1]['status'], 'insufficient_evidence')
        self.assertIn('current_condition_omitted', report['condition_results'][1]['reason'])

    def add_fact(self, **changes):
        row = copy.deepcopy(self.fact)
        row.update(changes)
        self.source['facts'].append(row)
        self.write_source()
        item = copy.deepcopy(self.pack['evidence_items'][3])
        item.update(evidence_id='extra' + str(len(self.source['facts'])),
                    fact_pointer='/facts/' + str(len(self.source['facts']) - 1))
        self.pack['evidence_items'].append(item)
        self.claim['evidence_ids'].append(item['evidence_id'])
        digest = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        for evidence in self.pack['evidence_items']:
            if evidence.get('local_path') == 'source.json':
                evidence['content_sha256'] = digest

    def test_consecutive_periods_require_every_fact(self):
        self.rule['period']['count'] = 2
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'required_period_fact_missing')
        self.add_fact(period='2026Q1', value=8)
        self.assertTrue(self.evaluate()['verified_hits'])
        self.source['facts'][1]['value'] = 11
        self.write_source()
        for item in self.pack['evidence_items']:
            if item.get('local_path') == 'source.json':
                item['content_sha256'] = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        self.assert_no_hit(self.evaluate())

    def test_growth_is_recalculated_from_raw_comparable_periods(self):
        self.rule.update(unit='percent', threshold=0)
        self.rule['period'].update(basis='yoy', source_unit='USD')
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'positive_comparison_base_required')
        self.add_fact(period='2025Q2', value=10)
        report = self.evaluate()
        self.assertEqual(report['verified_hits'][0]['observed_values'], ['-10'])
        self.rule['period']['basis'] = 'qoq'
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'positive_comparison_base_required')
        self.add_fact(period='2026Q1', value=10)
        self.assertTrue(self.evaluate()['verified_hits'])

    def test_bad_snapshot_window_and_duplicate_evidence_do_not_verify(self):
        self.pack['portfolio_snapshot_binding'] = {}
        self.assert_no_hit(self.evaluate(), 'invalid_binding_context')
        self.pack['portfolio_snapshot_binding'] = copy.deepcopy(BINDING)
        self.pack['evidence_items'].append(copy.deepcopy(self.pack['evidence_items'][3]))
        self.assert_no_hit(self.evaluate(), 'valid_evidence_references_required')

    def test_invalid_evidence_time_does_not_verify(self):
        self.pack['evidence_items'][3]['retrieved_at'] = '2027-01-01T00:00:00Z'
        self.assert_no_hit(self.evaluate(), 'valid_evidence_references_required')

    def test_native_ledger_command_output_binds_without_translation(self):
        raw_conditions = self.root / 'new-conditions.json'
        raw_conditions.write_text(json.dumps([condition()]), encoding='utf-8')
        with patch('pia_thesis_ledger.datetime.datetime') as clock:
            clock.now.return_value = NOW
            code, _ = ledger.cmd_init(argparse.Namespace(file=str(self.ledger_path), force=True))
            self.assertEqual(code, 0)
            code, _ = ledger.cmd_append(argparse.Namespace(
                file=str(self.ledger_path), symbol='SYNTH', confirmed_at='2026-02-01',
                source_locator='dataset://pia/user-confirmation/synthetic',
                conditions_file=str(raw_conditions), note=None))
            self.assertEqual(code, 0)
        self.pack['conditions_sha256'] = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        self.assertEqual(self.evaluate()['fatal_symbols'], ['SYNTH'])

    def test_threshold_uses_exact_original_json_number(self):
        self.rule['threshold'] = 'EXACT_THRESHOLD'
        self.write_ledger()
        raw = self.ledger_path.read_text().replace('"EXACT_THRESHOLD"', '9.00000000000000000001')
        self.ledger_path.write_text(raw, encoding='utf-8')
        self.pack['conditions_sha256'] = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        self.assertTrue(self.evaluate()['verified_hits'])

    def test_junction_escape_on_windows(self):
        if os.name != 'nt':
            self.skipTest('Windows junction only')
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, 'source.json').write_bytes(self.source_path.read_bytes())
        junction = self.root / 'junction'
        command = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(junction), outside.name],
                                 capture_output=True, timeout=10, check=False)
        self.assertEqual(command.returncode, 0, command.stderr.decode(errors='replace'))
        self.addCleanup(lambda: junction.rmdir() if junction.exists() else None)
        self.pack['evidence_items'][3]['local_path'] = 'junction/source.json'
        self.assert_no_hit(self.evaluate())

    def test_bad_input_shapes_do_not_mask_as_no_data(self):
        self.pack['schema_version'] = []
        self.assert_no_hit(self.evaluate(), 'schema_version_must_be')
        self.pack['schema_version'] = 'pia_thesis_red_team_v2'
        self.pack['evidence_items'][3]['source_tier'] = []
        self.assert_no_hit(self.evaluate(), 'source_tier_not_primary')
        self.pack['evidence_items'][3]['source_tier'] = 'issuer'
        self.pack['evidence_items'][3]['source_locator'] = 'https://[bad'
        self.assert_no_hit(self.evaluate(), 'source_locator_must_be_public_http_url')

    def test_future_period_cannot_be_presented_as_due_fact(self):
        self.rule['period']['end'] = '2027Q1'
        self.fact['period'] = '2027Q1'
        self.write_source()
        self.write_ledger()
        self.assert_no_hit(self.evaluate(), 'required_period_not_ended')


if __name__ == '__main__':
    unittest.main()
