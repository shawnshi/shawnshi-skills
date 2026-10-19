"""Synthetic offline oracles for the scoped fundamental consumer."""
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import sec_edgar_fundamentals as sec
from pia_fact_prepare import prepare_facts
from pia_fundamental_diagnostic import evaluate
from test_cn_valuation_drivers import OperatingDCFTests
from test_p0_research_contract import valid_brief
from test_p1p2_fact_prepare import Response, company_bytes


def case(cid='A', price=100, terminal=120, currency='USD') -> dict[str, Any]:
    return {'case_id': cid, 'symbol': 'SYNTHETIC-' + cid, 'price': price,
            'currency': currency, 'reporting_currency': 'USD', 'as_of': '2026-07-22',
            'horizon_days': 365, 'cash_flow_treatment': 'unreinvested',
            'scenarios': [{'scenario_id': 'base', 'definition': 'unchanged operations',
                           'terminal_value': terminal, 'cash_flows': [{'day': 180, 'amount': 5}],
                           'costs': {'entry': 2, 'exit': 3}}]}


def payload() -> dict[str, Any]:
    return {'research_lane': 'fundamental', 'research_brief': valid_brief(),
            'dashboard': {'scenario_analysis': {'valuation_contract_version': '2.0',
                **{s: {'enterprise_value': 100, 'net_debt': 10, 'equity_value': 90,
                       'diluted_shares': 10, 'per_share_value': 9} for s in ('base', 'bull', 'bear')}}},
            'scenario_cases': [case(), case('B', terminal=130)],
            'comparison': {'baseline_case_id': 'A', 'alternative_case_ids': ['B']}}


class FundamentalDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.net = mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.net.start()
        self.addCleanup(self.net.stop)

    def test_hand_computable_returns_and_delta(self):
        r = evaluate(payload())
        self.assertEqual(r['status'], 'complete', r)
        s = r['scenario_analysis']
        self.assertAlmostEqual(s['cases'][0]['scenarios']['base']['net_return'], 122 / 102 - 1)
        self.assertAlmostEqual(s['cases'][1]['scenarios']['base']['net_return'], 132 / 102 - 1)
        self.assertAlmostEqual(s['comparisons'][0]['net_return_deltas']['base'], 10 / 102)
        self.assertEqual(r['brief_structure']['status'], 'complete')
        self.assertEqual(r['dashboard_math']['status'], 'complete')
        self.assertEqual(r['method']['screening_mode'], 'descriptive_filter')
        self.assertEqual(r['method']['alpha_validation_status'], 'not_validated')
        self.assertFalse(r['formal_use_allowed'])
        self.assertFalse(r['alpha_eligible'])
        self.assertNotIn('target_weights', r)
        self.assertNotIn('orders', r)

    def test_existing_cn_dcf_positive_and_mismatch(self):
        fixture = OperatingDCFTests()
        fixture.setUp()
        p = payload()
        p.update(valuation_model=fixture.model, dashboard=fixture.dashboard)
        # Preserve an actual legal DCF rather than weakening it to insufficiency.
        self.assertEqual(evaluate(p)['valuation']['cases']['base']['enterprise_value_cny'], 800)
        p['dashboard']['scenario_analysis']['base']['enterprise_value'] = 900
        r = evaluate(p)
        self.assertEqual(r['valuation']['status'], 'invalid_input')
        self.assertEqual(r['scenario_analysis']['status'], 'complete')

    def test_brief_gap_and_math_failure_are_distinct(self):
        p = payload()
        p['research_brief']['core_hypothesis']['expected_gap']['absolute'] = 0.99
        p['dashboard']['scenario_analysis']['base']['equity_value'] = 50
        r = evaluate(p)
        self.assertEqual(r['brief_structure']['status'], 'invalid_input')
        self.assertEqual(r['dashboard_math']['status'], 'invalid_input')
        self.assertEqual(r['scenario_analysis']['status'], 'complete')

    def test_missing_dimensions_only_block_dependent_case(self):
        for key in ('price', 'horizon_days', 'as_of', 'currency', 'cash_flow_treatment'):
            with self.subTest(key=key):
                p = payload()
                p['scenario_cases'][0].pop(key)
                r = evaluate(p)
                self.assertEqual(r['status'], 'insufficient_data', r)
                self.assertEqual(r['scenario_analysis']['cases'][1]['status'], 'complete')
                self.assertEqual(r['dashboard_math']['status'], 'complete')
                self.assertNotIn('net_return_deltas', r['scenario_analysis']['comparisons'][0])
        for key in ('entry', 'exit'):
            p = payload()
            p['scenario_cases'][0]['scenarios'][0]['costs'].pop(key)
            self.assertEqual(evaluate(p)['status'], 'insufficient_data')

    def test_cross_currency_explicit_entry_terminal_and_cash_fx(self):
        p = payload()
        c = p['scenario_cases'][0]
        c['currency'] = 'EUR'
        c['entry_fx'] = 2
        c['scenarios'][0]['terminal_fx'] = 3
        c['scenarios'][0]['cash_flows'][0]['fx'] = 4
        r = evaluate(p)
        self.assertEqual(r['status'], 'complete', r)
        self.assertAlmostEqual(r['scenario_analysis']['cases'][0]['scenarios']['base']['net_return'], (120 * 3 + 5 * 4 - 3 * 3) / (102 * 2) - 1)
        for target, key in ((c, 'entry_fx'), (c['scenarios'][0], 'terminal_fx'), (c['scenarios'][0]['cash_flows'][0], 'fx')):
            old = target.pop(key)
            self.assertEqual(evaluate(p)['status'], 'insufficient_data')
            target[key] = old

    def test_expectations_require_all_probabilities_exact_sum(self):
        p = payload()
        p['expected_value'] = True
        r = evaluate(p)
        self.assertEqual(r['status'], 'insufficient_data')
        self.assertIn('base', r['scenario_analysis']['cases'][0]['scenarios'])
        for c in p['scenario_cases']:
            c['scenarios'][0]['probability'] = 1
        r = evaluate(p)
        self.assertEqual(r['status'], 'complete', r)
        self.assertAlmostEqual(r['scenario_analysis']['comparisons'][0]['expected_delta']['net_return_delta'], 10 / 102)
        p['scenario_cases'][0]['scenarios'][0]['probability'] = 0.9999999999999999
        self.assertEqual(evaluate(p)['status'], 'invalid_input')

    def test_different_expected_probabilities_do_not_mix(self):
        p = payload()
        p['expected_value'] = True
        for c, probability in zip(p['scenario_cases'], (0.25, 0.75), strict=True):
            c['scenarios'][0]['probability'] = probability
            other = copy.deepcopy(c['scenarios'][0])
            other.update(scenario_id='bear', definition='lower operations', probability=1-probability, terminal_value=80)
            c['scenarios'].append(other)
        r = evaluate(p)
        row = r['scenario_analysis']['comparisons'][0]
        self.assertEqual(row['status'], 'complete')
        self.assertEqual(row['expected_delta']['status'], 'invalid_input')
        self.assertNotIn('net_return_delta', row['expected_delta'])
        self.assertEqual(r['status'], 'invalid_input')

    def test_dimensions_and_definitions_never_mix(self):
        for key, value in [('horizon_days', 90), ('as_of', '2026-07-21'), ('reporting_currency', 'EUR')]:
            p = payload()
            p['scenario_cases'][1][key] = value
            if key == 'horizon_days':
                p['scenario_cases'][1]['scenarios'][0]['cash_flows'][0]['day'] = 45
            if key == 'reporting_currency':
                c = p['scenario_cases'][1]
                c['entry_fx'] = c['scenarios'][0]['terminal_fx'] = c['scenarios'][0]['cash_flows'][0]['fx'] = 1
            r = evaluate(p)
            self.assertEqual(r['scenario_analysis']['cases'][1]['status'], 'complete', r)
            self.assertEqual(r['scenario_analysis']['comparisons'][0]['status'], 'invalid_input')
        p = payload()
        p['scenario_cases'][1]['scenarios'][0]['definition'] = 'different operations'
        self.assertEqual(evaluate(p)['status'], 'invalid_input')
        p['scenario_cases'][1]['scenarios'][0]['scenario_id'] = 'bull'
        self.assertEqual(evaluate(p)['status'], 'invalid_input')

    def test_no_implicit_anchor_or_order(self):
        p = payload()
        p.pop('comparison')
        r = evaluate(p)['scenario_analysis']
        self.assertEqual(r['comparisons'], [])
        self.assertEqual(r['comparison_status'], 'not_requested_no_anchor')
        p['scenario_cases'].reverse()
        self.assertEqual(evaluate(p)['scenario_analysis']['comparisons'], [])

    def test_duplicates_bad_numbers_dates_types_rejected(self):
        for value in (True, False, float('nan'), float('inf'), -1, '100'):
            p = payload()
            p['scenario_cases'][0]['price'] = value
            self.assertEqual(evaluate(p)['status'], 'invalid_input', value)
        for field, value in [('horizon_days', True), ('horizon_days', 0), ('as_of', '2026-13-01'), ('cash_flow_treatment', 'reinvest')]:
            p = payload()
            p['scenario_cases'][0][field] = value
            self.assertEqual(evaluate(p)['status'], 'invalid_input')
        p = payload()
        p['scenario_cases'][1]['case_id'] = 'A'
        self.assertEqual(evaluate(p)['status'], 'invalid_input')
        p = payload()
        p['scenario_cases'][0]['scenarios'] *= 2
        self.assertEqual(evaluate(p)['status'], 'invalid_input')
        p = payload()
        p['scenario_cases'][0]['scenarios'][0]['cash_flows'][0]['day'] = 366
        self.assertEqual(evaluate(p)['status'], 'invalid_input')

    def test_all_numeric_boundaries_and_exact_probability_sum(self):
        for value in (True, float('nan'), float('inf')):
            for field in ('terminal_value', 'probability'):
                p = payload()
                p['scenario_cases'][0]['scenarios'][0][field] = value
                self.assertEqual(evaluate(p)['status'], 'invalid_input')
            p = payload()
            p['scenario_cases'][0]['scenarios'][0]['costs']['exit'] = value
            self.assertEqual(evaluate(p)['status'], 'invalid_input')
            p = payload()
            p['source_facts'] = [{'fact': {'symbol': 'X', 'metric': 'net_income', 'value': value,
                                         'unit': 'USD', 'period': '2023', 'scope': 'entity'}}]
            self.assertEqual(evaluate(p)['source_binding']['status'], 'invalid_input')
        p = payload()
        p['expected_value'] = True
        for c in p['scenario_cases']:
            c['scenarios'][0]['probability'] = 0.7
            other = copy.deepcopy(c['scenarios'][0])
            other.update(scenario_id='bear', definition='lower operations', probability=0.3, terminal_value=80)
            c['scenarios'].append(other)
        self.assertEqual(evaluate(p)['status'], 'complete')
        for c in p['scenario_cases']:
            c['scenarios'][0]['probability'] = 1
            c['scenarios'][1]['probability'] = 1e-30
        self.assertEqual(evaluate(p)['status'], 'invalid_input')

    def test_requested_computation_without_cases_is_insufficient(self):
        p = payload()
        p.pop('scenario_cases')
        self.assertEqual(evaluate(p)['scenario_analysis']['status'], 'insufficient_data')
        p.pop('comparison')
        p['expected_value'] = True
        self.assertEqual(evaluate(p)['scenario_analysis']['status'], 'insufficient_data')
        p['expected_value'] = 'yes'
        self.assertEqual(evaluate(p)['scenario_analysis']['status'], 'invalid_input')

    def test_no_new_industry_dcf_or_profile_semantics(self):
        for profile in ('financial_institution', 'etf_research'):
            p = payload()
            p['research_brief']['method_profile'] = profile
            r = evaluate(p)
            self.assertEqual(r['method']['screening_mode'], 'evidence_only')
            self.assertFalse(r['alpha_eligible'])
        fixture = OperatingDCFTests()
        fixture.setUp()
        fixture.model['instrument']['industry_type'] = 'bank'
        p = payload()
        p.update(valuation_model=fixture.model, dashboard=fixture.dashboard)
        self.assertEqual(evaluate(p)['valuation']['status'], 'invalid_input')

    def test_quantitative_routes_to_real_existing_path_not_pass(self):
        r = evaluate({'research_lane': 'quantitative'})
        self.assertEqual(r['status'], 'not_evaluated')
        self.assertFalse(r['formal_use_allowed'])
        self.assertFalse(r['alpha_eligible'])
        self.assertIn('pia.py alpha-validate', r['alpha_path']['entry_points'])
        self.assertEqual(evaluate({})['status'], 'invalid_input')

    def test_source_projection_positive_tamper_and_unbound(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('PIA_TEST_TMP')) as temp:
            root = Path(temp)
            mapping = b'{"0":{"ticker":"MSFT","cik_str":789019}}'
            raws = {sec.TICKER_MAP_URL: mapping, sec.COMPANYFACTS_URL.format(cik='0000789019'): company_bytes()}
            session = mock.Mock()
            session.get.side_effect = lambda url, **kwargs: Response(raws[url])
            report = sec.build_report(['MSFT'], as_of=date.today(), user_agent='synthetic', session=session, decision_scope='research_only', artifact_dir=root)
            prepared = prepare_facts(report['fact_prepare_input'], root, root)
            proof = prepared['projections'][0]['document']
            p = payload()
            fact = copy.deepcopy(proof['facts'][0])
            p['source_facts'] = [{'fact': fact, 'proof': proof}, {'fact': dict(fact, value=99)}]
            r = evaluate(p, evidence_root=root)
            self.assertEqual(r['status'], 'complete', r)
            self.assertEqual(r['source_binding']['items'][0]['status'], 'source_bound_numeric_consistency')
            self.assertEqual(r['source_binding']['items'][1]['status'], 'unverified')
            self.assertEqual(r['source_binding']['semantic_review'], 'not_performed')
            self.assertEqual(evaluate(p)['source_binding']['status'], 'insufficient_data')
            for key, value in [('value', True), ('symbol', 'OTHER'), ('value', 999)]:
                old = fact[key]
                fact[key] = value
                self.assertEqual(evaluate(p, evidence_root=root)['source_binding']['status'], 'invalid_input')
                fact[key] = old
            proof['facts'][0]['value'] = 888
            self.assertEqual(evaluate(p, evidence_root=root)['source_binding']['status'], 'invalid_input')
            self.assertEqual(evaluate(p, evidence_root=root)['dashboard_math']['status'], 'complete')
            p['research_lane'] = 'quantitative'
            self.assertEqual(evaluate(p, evidence_root=root)['status'], 'invalid_input')
            self.assertFalse(evaluate(p, evidence_root=root)['alpha_eligible'])

    def test_cli_positive_and_bad_input(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('PIA_TEST_TMP')) as temp:
            path = Path(temp) / 'input.json'
            path.write_text(json.dumps(payload()), encoding='utf-8')
            cmd = [sys.executable, '-B', str(HERE / 'pia_fundamental_diagnostic.py'), '--input-file', str(path)]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertEqual(json.loads(completed.stdout)['status'], 'complete')
            incomplete = payload()
            incomplete['scenario_cases'][0]['scenarios'][0]['costs'].pop('entry')
            path.write_text(json.dumps(incomplete), encoding='utf-8')
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(json.loads(completed.stdout)['status'], 'insufficient_data')
            path.write_text('{broken', encoding='utf-8')
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(json.loads(completed.stdout)['status'], 'invalid_input')
            path.unlink()
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 2)
            self.assertIn('FileNotFoundError', json.loads(completed.stdout)['errors'][0])


if __name__ == '__main__':
    unittest.main()
