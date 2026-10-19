"""Evidence-bound descriptive expectation feedback; never formal calibration."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from management_claim_tracker import evaluate_claims
from pia_fact_prepare import (
    bounded_path,
    exact_number,
    no_links,
    pointer,
    verify_fact_projection,
)


class FeedbackError(ValueError):
    pass


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise FeedbackError('canonical_ISO_date_required')
    return date.fromisoformat(value)


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise FeedbackError('finite_JSON_number_required')
    number = Decimal(str(value))
    if not number.is_finite():
        raise FeedbackError('finite_JSON_number_required')
    return Fraction(number)


def output(value):
    if value.denominator == 1:
        return value.numerator
    result = float(value)
    if not Decimal(str(result)).is_finite():
        raise FeedbackError('computed_number_out_of_range')
    return result


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FeedbackError('duplicate_JSON_key:' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise FeedbackError('nonfinite_JSON_constant:' + value)
    def exact(value):
        if isinstance(value, Decimal):
            return exact_number(value)
        if isinstance(value, dict):
            return {k: exact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [exact(v) for v in value]
        return value
    return exact(json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant, parse_float=Decimal))


def reference(ref, root):
    if not isinstance(ref, dict) or set(ref) != {'local_path', 'content_sha256', 'pointer'}:
        raise FeedbackError('explicit_file_hash_pointer_required')
    digest = ref['content_sha256']
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise FeedbackError('SHA256_required')
    raw = bounded_path(root, ref['local_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise FeedbackError('reference_hash_mismatch')
    return load_json(raw)


def period_bounds(label):
    if not isinstance(label, str):
        raise FeedbackError('canonical_period_required')
    if re.fullmatch(r'[0-9]{4}', label):
        year = int(label)
        return date(year, 1, 1), date(year, 12, 31)
    if re.fullmatch(r'[0-9]{4}Q[1-4]', label):
        year, quarter = int(label[:4]), int(label[-1])
        month = quarter * 3
        return date(year, month - 2, 1), date(year, month, calendar.monthrange(year, month)[1])
    parts = label.split('/')
    if len(parts) == 1:
        day = iso_date(label)
        return day, day
    if len(parts) == 2:
        start, end = map(iso_date, parts)
        if start <= end:
            return start, end
    raise FeedbackError('canonical_period_required')


def actual(refs, root, as_of):
    if not isinstance(refs, list) or not refs:
        raise FeedbackError('actual_projection_refs_required')
    verified = []
    for ref in refs:
        document = reference(ref, root)
        document = verify_fact_projection(document, root)
        selected = ref['pointer']
        if not isinstance(selected, str) or not re.fullmatch(r'/facts/(0|[1-9][0-9]*)', selected):
            raise FeedbackError('actual_fact_pointer_required')
        fact = pointer(document, selected)
        provenance = document['provenance'][int(selected.rsplit('/', 1)[1])]
        for receipt in document['projection']['captures'].values():
            if datetime.fromisoformat(receipt['retrieved_at'].replace('Z', '+00:00')).date() > as_of:
                raise FeedbackError('actual_capture_after_as_of')
        projection_cutoff = document['projection']['as_of']
        if iso_date(projection_cutoff[:10]) > as_of:
            raise FeedbackError('projection_after_as_of')
        period_bounds(fact['period'])
        for key in ('symbol', 'metric', 'unit', 'scope'):
            if not isinstance(fact[key], str) or not fact[key].isascii() or fact[key].strip() != fact[key]:
                raise FeedbackError('canonical_actual_dimension_required:' + key)
        numeric(fact['value'])
        verified.append({'fact': fact, 'period_start': provenance['period_start'] or provenance['period_end'],
                         'period_end': provenance['period_end'], 'reference': ref})
    signatures = {json.dumps({k: v for k, v in item.items() if k != 'reference'}, sort_keys=True)
                  for item in verified}
    if len(signatures) != 1:
        raise FeedbackError('conflicting_actual_references')
    item = verified[0]
    return {'status': 'verified_numeric_projection', 'fact': item['fact'],
            'period_start': item['period_start'], 'period_end': item['period_end'],
            'references': sorted(refs, key=lambda r: (r['local_path'], r['pointer'], r['content_sha256'])),
            'publisher_authenticated': False}


def prior(ref, root, as_of):
    document = reference(ref, root)
    result = pointer(document, ref['pointer'])
    if not isinstance(result, dict):
        raise FeedbackError('expectation_object_required')
    for key in ('symbol', 'metric', 'unit', 'scope'):
        value = result.get(key)
        if not isinstance(value, str) or not value or not value.isascii() or value.strip() != value:
            raise FeedbackError('canonical_dimension_required:' + key)
    start, end = period_bounds(result.get('period'))
    pstart, pend = iso_date(result.get('period_start')), iso_date(result.get('period_end'))
    # A year label also represents an instant in the existing F projection contract.
    if (pstart, pend) != (start, end) and not (pstart == pend == end and re.fullmatch(r'[0-9]{4}', result['period'])):
        raise FeedbackError('prior_period_bounds_mismatch')
    deadline = iso_date(result.get('deadline'))
    if deadline < pend:
        raise FeedbackError('deadline_before_period_end')
    timestamp = result.get('recorded_at')
    if not isinstance(timestamp, str):
        raise FeedbackError('prior_recorded_at_required')
    recorded = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if recorded.tzinfo is None or recorded.utcoffset() is None or recorded.astimezone(timezone.utc).date() > as_of:
        raise FeedbackError('prior_timestamp_invalid_or_future')
    if ('expected_value' in result) == ('expected_range' in result):
        raise FeedbackError('one_point_or_range_expectation_required')
    if 'expected_value' in result:
        numeric(result['expected_value'])
    else:
        bounds = result['expected_range']
        if not isinstance(bounds, dict) or set(bounds) != {'lower', 'upper'} or numeric(bounds['lower']) > numeric(bounds['upper']):
            raise FeedbackError('ordered_expected_range_required')
    if 'direction' in result and result['direction'] not in ('higher', 'lower'):
        raise FeedbackError('explicit_higher_or_lower_direction_required')
    return result


def comparison(expectation, observed, as_of, ref):
    fact = observed['fact']
    for key in ('symbol', 'metric', 'unit', 'period', 'scope'):
        if expectation[key] != fact[key]:
            raise FeedbackError('dimension_mismatch:' + key)
    for key in ('period_start', 'period_end'):
        if expectation[key] != observed[key]:
            raise FeedbackError('dimension_mismatch:' + key)
    value = numeric(fact['value'])
    point = 'expected_value' in expectation
    if point:
        lower = upper = numeric(expectation['expected_value'])
    else:
        lower, upper = (numeric(expectation['expected_range'][k]) for k in ('lower', 'upper'))
    delta = {'unit': fact['unit'], 'definition': 'actual_minus_expected'}
    if point:
        delta.update(value=output(value - lower), absolute_magnitude=output(abs(value - lower)))
    else:
        delta.update(lower=output(value - upper), upper=output(value - lower))
    position = 'below' if value < lower else 'above' if value > upper else 'within'
    # evaluate_claims is only the existing due/period/comparator subcalculation.
    # Its document validation is not used to establish source truth or prior trust.
    boundary = upper if expectation.get('direction') == 'lower' else lower
    op = '<=' if expectation.get('direction') == 'lower' else '>='
    source = {'document_id': 'bound_original', 'source_tier': 'user_authorized',
              'source_locator': ref['local_path'], 'published_at': expectation['recorded_at'][:10],
              'retrieved_at': as_of.isoformat(), 'text': 'Hash-bound expectation; asserted timing only.'}
    claim = {'claim_id': 'due_period_comparison', 'statement': 'Numeric subcalculation only',
             'metric': fact['metric'], 'operator': op, 'target': output(boundary),
             'deadline': expectation['deadline'], 'source_document_id': 'bound_original',
             'source_locator': ref['local_path'], 'actual': fact['value'],
             'actual_source_document_id': 'bound_original', 'actual_source_locator': observed['references'][0]['local_path'],
             'period_start': expectation['period_start'], 'period_end': expectation['period_end'],
             'actual_period_start': observed['period_start'], 'actual_period_end': observed['period_end'],
             'actual_period_complete': True}
    computation = evaluate_claims({'as_of_date': as_of.isoformat(), 'source_documents': [source],
                                   'claims': [claim], 'test_mode': True})
    if not computation['valid']:
        raise FeedbackError('claim_subcalculation_invalid:' + ';'.join(computation['errors']))
    sub = computation['management_claim_tracking']['claims'][0]
    relative = {'status': 'not_assessed', 'reason': 'explicit_definition_required'}
    definition = expectation.get('relative_error_definition')
    if definition is not None:
        if definition != 'delta_over_abs_expected':
            raise FeedbackError('unsupported_relative_error_definition')
        if not point:
            relative['reason'] = 'point_base_required'
        elif lower == 0:
            relative['reason'] = 'zero_expected_base'
        else:
            relative = {'status': 'computed', 'definition': definition, 'value': output((value - lower) / abs(lower))}
    return {'delta': delta, 'relative_error': relative, 'range_position': position,
            'due_status': sub['status'] if sub['status'] == 'not_due' else 'due',
            'period_verified': sub['period_verified'],
            'directional_target_met': sub['comparison_result'] if 'direction' in expectation else None,
            'interpretation': 'numeric_comparison_only_not_thesis_falsification'}


def valuation(expectation, observed):
    sensitivity = expectation.get('valuation_sensitivity')
    if sensitivity is None:
        return {'status': 'not_assessed', 'reason': 'explicit_sensitivity_required'}
    if not isinstance(sensitivity, dict) or sensitivity.get('method') != 'linear_absolute_delta':
        raise FeedbackError('explicit_linear_sensitivity_required')
    if sensitivity.get('input_unit') != expectation['unit']:
        raise FeedbackError('sensitivity_input_unit_mismatch')
    for key in ('output_unit', 'statement'):
        if not isinstance(sensitivity.get(key), str) or not sensitivity[key].strip():
            raise FeedbackError('sensitivity_' + key + '_required')
    coefficient = numeric(sensitivity.get('coefficient'))
    if 'expected_value' not in expectation:
        return {'status': 'not_assessed', 'reason': 'point_delta_required'}
    delta = numeric(observed['fact']['value']) - numeric(expectation['expected_value'])
    return {'status': 'conditional_only', 'method': sensitivity['method'],
            'value': output(delta * coefficient), 'unit': sensitivity['output_unit'],
            'assumption': sensitivity['statement'], 'coefficient': sensitivity['coefficient'],
            'not_a_valuation_forecast': True}


ERRORS = (ValueError, TypeError, KeyError, IndexError, OSError, OverflowError)


def evaluate(payload, *, evidence_root):
    result = {'status': 'incomplete', 'decision_scope': 'research_only', 'formal_use_allowed': False,
              'feedback_mode': 'descriptive_historical_comparison', 'prior_timing': 'prior_timing_unverified',
              'comparisons': [], 'errors': []}
    try:
        root = no_links(evidence_root).resolve(strict=True)
        if not isinstance(payload, dict) or set(payload) != {'as_of_date', 'comparisons'}:
            raise FeedbackError('as_of_date_and_comparisons_required')
        as_of = iso_date(payload['as_of_date'])
        if as_of > datetime.now(timezone.utc).date():
            raise FeedbackError('future_as_of_not_allowed')
        entries = payload['comparisons']
        if not isinstance(entries, list) or not entries:
            raise FeedbackError('nonempty_comparisons_required')
        ids = [e.get('comparison_id') if isinstance(e, dict) else None for e in entries]
        if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
            raise FeedbackError('unique_comparison_ids_required')
    except ERRORS as exc:
        result['errors'].append({'type': type(exc).__name__, 'message': str(exc)})
        return result
    for entry in entries:
        item = {'comparison_id': entry['comparison_id'], 'status': 'incomplete', 'actual': None,
                'expectation': None, 'prior_reference': entry.get('prior_ref'),
                'comparison': None, 'formal_use_allowed': False,
                'prior_timing': 'prior_timing_unverified', 'errors': [],
                'valuation_implications': {'status': 'not_assessed'},
                'thesis_implications': {'status': 'not_assessed', 'requires': 'original_P0_confirmed_condition_gate'}}
        for name, function, argument in (('actual', actual, entry.get('actual_refs')),
                                         ('expectation', prior, entry.get('prior_ref'))):
            try:
                item[name] = function(argument, root, as_of)
            except ERRORS as exc:
                item['errors'].append({'component': name, 'type': type(exc).__name__, 'message': str(exc)})
        try:
            if set(entry) != {'comparison_id', 'prior_ref', 'actual_refs'}:
                raise FeedbackError('unexpected_comparison_fields')
            if item['actual'] is not None and item['expectation'] is not None:
                item['comparison'] = comparison(item['expectation'], item['actual'], as_of, entry['prior_ref'])
                item['valuation_implications'] = valuation(item['expectation'], item['actual'])
                item['status'] = 'complete'
        except ERRORS as exc:
            item['errors'].append({'component': 'comparison', 'type': type(exc).__name__, 'message': str(exc)})
        result['comparisons'].append(item)
    if all(item['status'] == 'complete' for item in result['comparisons']):
        result['status'] = 'complete'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-file', required=True)
    parser.add_argument('--evidence-root', required=True)
    args = parser.parse_args(argv)
    try:
        payload = load_json(Path(args.input_file).read_bytes())
        result = evaluate(payload, evidence_root=args.evidence_root)
    except ERRORS as exc:
        result = {'status': 'incomplete', 'formal_use_allowed': False,
                  'errors': [{'type': type(exc).__name__, 'message': str(exc)}]}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
