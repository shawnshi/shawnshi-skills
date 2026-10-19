"""Research-only consumer of existing gates and explicitly dimensioned scenarios."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from cn_valuation_drivers import evaluate as evaluate_valuation
from dashboard_math_gate import validate_math_consistency
from pia_fact_prepare import verify_fact_projection
from research_brief_gate import validate_research_brief


class InputError(ValueError):
    def __init__(self, message, status='invalid_input'):
        super().__init__(message)
        self.status = status


def required(obj, key):
    if key not in obj or obj[key] is None:
        raise InputError('missing:' + key, 'insufficient_data')
    return obj[key]


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise InputError(name + ':nonempty_string_required')
    return value


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(name + ':JSON_number_required')
    result = Decimal(str(value))
    if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
        raise InputError(name + ':invalid_number')
    return Fraction(result)


def integer(value, name, low, high=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        raise InputError(name + ':integer_out_of_range')
    return value


def output_number(value):
    try:
        result = float(value)
    except OverflowError as exc:
        raise InputError('computed_number_out_of_range') from exc
    if not math.isfinite(result):
        raise InputError('computed_number_out_of_range')
    return result


def fx(obj, key, cross):
    if cross:
        return number(required(obj, key), key, positive=True)
    if key in obj and number(obj[key], key, positive=True) != 1:
        raise InputError(key + ':same_currency_must_equal_one')
    return Fraction(1)


def scenario_case(case, expected):
    if not isinstance(case, dict):
        raise InputError('case:object_required')
    for key in ('case_id', 'symbol', 'currency', 'reporting_currency'):
        text(required(case, key), key)
    as_of = required(case, 'as_of')
    if not isinstance(as_of, str):
        raise InputError('as_of:ISO_date_required')
    try:
        parsed = date.fromisoformat(as_of)
    except ValueError as exc:
        raise InputError('as_of:ISO_date_required') from exc
    if parsed.isoformat() != as_of or parsed > date.today():
        raise InputError('as_of:invalid_or_future_date')
    horizon = integer(required(case, 'horizon_days'), 'horizon_days', 1)
    if required(case, 'cash_flow_treatment') != 'unreinvested':
        raise InputError('cash_flow_treatment:only_explicit_unreinvested_supported')
    price = number(required(case, 'price'), 'price', positive=True)
    cross = case['currency'] != case['reporting_currency']
    entry_fx = fx(case, 'entry_fx', cross)
    scenarios = required(case, 'scenarios')
    if not isinstance(scenarios, list) or not scenarios:
        raise InputError('scenarios:nonempty_list_required')
    results, definitions, probabilities, expected_errors = {}, {}, {}, []
    for item in scenarios:
        if not isinstance(item, dict):
            raise InputError('scenario:object_required')
        sid = text(required(item, 'scenario_id'), 'scenario_id')
        if sid in results:
            raise InputError('duplicate_scenario_id:' + sid)
        definitions[sid] = text(required(item, 'definition'), 'definition')
        terminal = number(required(item, 'terminal_value'), 'terminal_value', nonnegative=True)
        terminal_fx = fx(item, 'terminal_fx', cross)
        costs = required(item, 'costs')
        if not isinstance(costs, dict):
            raise InputError('costs:object_required')
        entry_cost = number(required(costs, 'entry'), 'costs.entry', nonnegative=True)
        exit_cost = number(required(costs, 'exit'), 'costs.exit', nonnegative=True)
        flows = required(item, 'cash_flows')
        if not isinstance(flows, list):
            raise InputError('cash_flows:list_required')
        cash = Fraction(0)
        for flow in flows:
            if not isinstance(flow, dict):
                raise InputError('cash_flow:object_required')
            integer(required(flow, 'day'), 'cash_flow.day', 1, horizon)
            cash += number(required(flow, 'amount'), 'cash_flow.amount') * fx(flow, 'fx', cross)
        net = (terminal * terminal_fx + cash - exit_cost * terminal_fx) / ((price + entry_cost) * entry_fx) - 1
        results[sid] = {'net_return': output_number(net)}
        if expected or 'probability' in item:
            try:
                probability = number(required(item, 'probability'), 'probability', nonnegative=True)
                if probability > 1:
                    raise InputError('probability:must_not_exceed_one')
                probabilities[sid] = probability
            except InputError as exc:
                expected_errors.append({'status': exc.status, 'error': str(exc)})
    expectation = {'status': 'not_requested'}
    if expected:
        if not expected_errors and sum(probabilities.values(), Fraction(0)) != 1:
            expected_errors.append({'status': 'invalid_input', 'error': 'probabilities:exact_sum_one_required'})
        if expected_errors:
            expectation = {'status': 'invalid_input' if any(e['status'] == 'invalid_input' for e in expected_errors) else 'insufficient_data', 'errors': expected_errors}
        else:
            expectation = {'status': 'complete', 'net_return': output_number(sum(Fraction(str(results[s]['net_return'])) * probabilities[s] for s in results))}
    elif expected_errors:
        # A supplied malformed probability is not silently ignored even outside expectations.
        raise InputError(expected_errors[0]['error'], expected_errors[0]['status'])
    return {'status': 'complete', 'case_id': case['case_id'], 'symbol': case['symbol'],
            'as_of': as_of, 'horizon_days': horizon, 'reporting_currency': case['reporting_currency'],
            'cash_flow_treatment': case['cash_flow_treatment'], 'scenario_definitions': definitions,
            'scenarios': results, 'probabilities': {s: output_number(p) for s, p in probabilities.items()},
            'expected_value': expectation}


def scenarios(payload):
    expected = payload.get('expected_value', False)
    if not isinstance(expected, bool):
        return {'status': 'invalid_input', 'errors': ['expected_value:boolean_required'], 'cases': [], 'comparisons': []}
    if 'scenario_cases' not in payload:
        if expected or payload.get('comparison') is not None:
            return {'status': 'insufficient_data', 'errors': ['scenario_cases:required_for_requested_computation'], 'cases': [], 'comparisons': []}
        return {'status': 'not_evaluated', 'cases': [], 'comparisons': []}
    cases = payload['scenario_cases']
    if not isinstance(cases, list) or not cases:
        return {'status': 'invalid_input', 'errors': ['scenario_cases:nonempty_list_required'], 'cases': [], 'comparisons': []}
    ids = [c.get('case_id') for c in cases if isinstance(c, dict)]
    duplicates = {i for i in ids if isinstance(i, str) and ids.count(i) > 1}
    results = []
    for case in cases:
        try:
            if isinstance(case, dict) and isinstance(case.get('case_id'), str) and case['case_id'] in duplicates:
                raise InputError('duplicate_case_id:' + case['case_id'])
            result = scenario_case(case, expected)
        except InputError as exc:
            result = {'case_id': case.get('case_id') if isinstance(case, dict) else None, 'status': exc.status, 'errors': [str(exc)]}
        results.append(result)
    comparisons = []
    selection = payload.get('comparison')
    if selection is not None:
        try:
            if not isinstance(selection, dict):
                raise InputError('comparison:object_required')
            anchor = text(required(selection, 'baseline_case_id'), 'baseline_case_id')
            alternatives = required(selection, 'alternative_case_ids')
            if not isinstance(alternatives, list) or not alternatives or any(not isinstance(a, str) or not a for a in alternatives):
                raise InputError('alternative_case_ids:nonempty_string_list_required')
            if len(set(alternatives)) != len(alternatives) or anchor in alternatives:
                raise InputError('comparison:duplicate_or_self_reference')
            by_id = {r['case_id']: r for r in results if r['status'] == 'complete'}
            for alternative in alternatives:
                row = {'baseline_case_id': anchor, 'alternative_case_id': alternative}
                if anchor not in by_id or alternative not in by_id:
                    row.update(status='insufficient_data', errors=['comparison:case_unavailable'])
                else:
                    a, b = by_id[anchor], by_id[alternative]
                    dimensions = ('as_of', 'horizon_days', 'reporting_currency', 'cash_flow_treatment', 'scenario_definitions')
                    mismatch = [d for d in dimensions if a[d] != b[d]]
                    if mismatch:
                        row.update(status='invalid_input', errors=['comparison:incompatible:' + ','.join(mismatch)])
                    else:
                        row.update(status='complete', net_return_deltas={s: output_number(Decimal(str(b['scenarios'][s]['net_return'])) - Decimal(str(a['scenarios'][s]['net_return']))) for s in a['scenarios']})
                        if expected:
                            if a['expected_value']['status'] != 'complete' or b['expected_value']['status'] != 'complete':
                                row['expected_delta'] = {'status': 'insufficient_data', 'errors': ['expectations_unavailable']}
                            elif a['probabilities'] != b['probabilities']:
                                row['expected_delta'] = {'status': 'invalid_input', 'errors': ['comparison:probabilities_differ']}
                            else:
                                row['expected_delta'] = {'status': 'complete', 'net_return_delta': output_number(Decimal(str(b['expected_value']['net_return'])) - Decimal(str(a['expected_value']['net_return'])))}
                comparisons.append(row)
        except InputError as exc:
            comparisons.append({'status': exc.status, 'errors': [str(exc)]})
    statuses = [r['status'] for r in results + comparisons]
    statuses += [r['expected_value']['status'] for r in results if 'expected_value' in r and expected]
    statuses += [r['expected_delta']['status'] for r in comparisons if 'expected_delta' in r]
    status = 'invalid_input' if 'invalid_input' in statuses else 'insufficient_data' if 'insufficient_data' in statuses else 'complete'
    return {'status': status, 'cases': results, 'comparisons': comparisons,
            'comparison_status': 'explicit_selection' if selection is not None else 'not_requested_no_anchor'}


def facts(items, evidence_root):
    if not isinstance(items, list):
        return {'status': 'invalid_input', 'errors': ['source_facts:list_required'], 'items': []}
    results = []
    for item in items:
        try:
            if not isinstance(item, dict) or not isinstance(item.get('fact'), dict):
                raise InputError('source_fact:fact_object_required')
            claimed = item['fact']
            if set(claimed) != {'symbol', 'metric', 'value', 'unit', 'period', 'scope'}:
                raise InputError('source_fact:six_field_fact_required')
            for field in ('symbol', 'metric', 'unit', 'period', 'scope'):
                text(claimed[field], 'fact.' + field)
            number(claimed['value'], 'fact.value')
            if 'proof' not in item:
                results.append({'fact': claimed, 'status': 'unverified'})
                continue
            if evidence_root is None:
                raise InputError('source_fact:explicit_evidence_root_required', 'insufficient_data')
            verified = verify_fact_projection(item['proof'], evidence_root)
            # JSON's bool/int equality is not a numeric proof.
            if not any(json.dumps(claimed, sort_keys=True, allow_nan=False) == json.dumps(f, sort_keys=True, allow_nan=False) for f in verified['facts']):
                raise InputError('source_fact:claim_not_in_verified_projection')
            results.append({'fact': claimed, 'status': 'source_bound_numeric_consistency', 'publisher_authenticated': False})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            results.append({'status': getattr(exc, 'status', 'invalid_input'), 'errors': [type(exc).__name__ + ':' + str(exc)]})
    statuses = [r['status'] for r in results]
    status = 'invalid_input' if 'invalid_input' in statuses else 'insufficient_data' if 'insufficient_data' in statuses else 'complete'
    return {'status': status, 'items': results, 'semantic_review': 'not_performed', 'publisher_authenticated': False,
            'boundary': 'Only explicitly bound fact items are verified; no label propagates to brief/dashboard/model/scenarios.'}


def evaluate(payload: Any, *, evidence_root=None) -> dict[str, Any]:
    result: dict[str, Any] = {'schema_version': 'pia_fundamental_diagnostic_v1', 'decision_scope': 'research_only',
              'formal_use_allowed': False, 'alpha_eligible': False, 'status': 'invalid_input',
              'assumption_status': 'declared_scenarios_not_forecast_truth'}
    if not isinstance(payload, dict) or payload.get('research_lane') not in ('fundamental', 'quantitative'):
        return dict(result, errors=['research_lane:fundamental_or_quantitative_required'])
    result['research_lane'] = payload['research_lane']
    if payload['research_lane'] == 'quantitative':
        result['source_binding'] = facts(payload.get('source_facts', []), evidence_root)
        status = result['source_binding']['status']
        return dict(result, status='not_evaluated' if status == 'complete' else status, alpha_path={'entry_points': ['pia.py alpha-validate', 'pia.py alpha-scan'],
            'gaps': ['Existing point-in-time alpha evidence and promotion policy must pass alpha-validate; alpha-scan eligibility remains separate.'],
            'fundamental_diagnostic_is_alpha_evidence': False})
    brief, dashboard = payload.get('research_brief'), payload.get('dashboard')
    result['brief_structure'] = {'status': 'insufficient_data', 'errors': ['research_brief:required']}
    if brief is not None:
        errors = validate_research_brief(brief)
        result['brief_structure'] = {'status': 'invalid_input' if errors else 'complete', 'errors': errors}
    result['dashboard_math'] = {'status': 'insufficient_data', 'errors': ['dashboard:required']}
    if dashboard is not None:
        errors = validate_math_consistency(dashboard)
        result['dashboard_math'] = {'status': 'invalid_input' if errors else 'complete', 'errors': errors,
                                    'boundary': 'Math only, not dashboard structure/source/semantic validation.'}
    result['valuation'] = {'status': 'not_evaluated'}
    if 'valuation_model' in payload:
        if not isinstance(payload['valuation_model'], dict) or not isinstance(dashboard, dict):
            result['valuation'] = {'status': 'invalid_input', 'errors': ['valuation_model_and_dashboard:objects_required']}
        else:
            result['valuation'] = evaluate_valuation(payload['valuation_model'], dashboard,
                filing_package=payload.get('filing_package'), verify_filing_raw='filing_package' in payload)
    result['source_binding'] = facts(payload.get('source_facts', []), evidence_root)
    result['scenario_analysis'] = scenarios(payload)
    profiles = json.loads((Path(__file__).resolve().parent.parent / 'references' / 'method_profiles.json').read_text(encoding='utf-8'))['profiles']
    profile = profiles.get(brief.get('method_profile')) if isinstance(brief, dict) and isinstance(brief.get('method_profile'), str) else None
    result['method'] = {k: profile[k] for k in ('screening_mode', 'alpha_validation_status', 'profile_version')} if profile else {'status': 'not_selected'}
    statuses = [result[k]['status'] for k in ('brief_structure', 'dashboard_math', 'valuation', 'source_binding', 'scenario_analysis')]
    result['status'] = 'invalid_input' if 'invalid_input' in statuses else 'insufficient_data' if 'insufficient_data' in statuses else 'complete'
    result['completion_scope'] = 'provided structural/math diagnostics only; not research, source semantics, Alpha, allocation or trading readiness'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-file', required=True)
    parser.add_argument('--evidence-root')
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.input_file).read_text(encoding='utf-8'))
        result = evaluate(payload, evidence_root=args.evidence_root)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {'status': 'invalid_input', 'decision_scope': 'research_only', 'formal_use_allowed': False,
                  'alpha_eligible': False, 'errors': [type(exc).__name__ + ':' + str(exc)]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    sys.exit(main())
