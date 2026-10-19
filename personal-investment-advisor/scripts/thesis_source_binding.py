"""Byte-bound quantitative checks, not publisher authentication or PDF review.

Only caller-selected ledger/root paths are read. The package selects relative JSON
facts within that root, never a ledger or an extraction implementation.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException, InvalidOperation
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from typing import Any

from pia_thesis_ledger import (
    RESERVED_LOCATORS,
    SCHEMA_VERSION,
    LedgerError,
    effective_version,
    iso_date,
    validate_conditions,
)


class BindingError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BindingError('duplicate_json_key')
        result[key] = value
    return result


def _json(raw: bytes, *, decimal=False):
    def invalid_constant(value):
        raise BindingError('non_finite_json_number')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                          parse_constant=invalid_constant,
                          parse_float=Decimal,
                          parse_int=Decimal if decimal else int)
    except (UnicodeError, ValueError) as exc:
        raise BindingError('invalid_json:' + str(exc)) from exc


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise BindingError('finite_number_required')
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise BindingError('finite_number_required') from exc
    if not number.is_finite():
        raise BindingError('finite_number_required')
    return number


def _period_index(value, frequency):
    pattern = r'([0-9]{4})' if frequency == 'annual' else r'([0-9]{4})Q([1-4])'
    match = re.fullmatch(pattern, value) if isinstance(value, str) else None
    if not match:
        raise BindingError('unsupported_period')
    year = int(match[1])
    if year < 1:
        raise BindingError('unsupported_period')
    return year if frequency == 'annual' else year * 4 + int(match[2]) - 1


def _rule(condition):
    if condition['operator'] == 'qualitative':
        raise BindingError('independent_review_required')
    threshold = _number(condition.get('threshold'))
    period = condition.get('period')
    if not isinstance(period, dict) or set(period) - {
            'frequency', 'end', 'count', 'basis', 'scope', 'source_unit'}:
        raise BindingError('unsupported_or_incomplete_period_rule')
    frequency = period.get('frequency')
    basis = period.get('basis')
    count = period.get('count')
    if (not isinstance(frequency, str) or not isinstance(basis, str)
            or frequency not in {'annual', 'quarterly'} or basis not in {'absolute', 'yoy', 'qoq'}):
        raise BindingError('unsupported_frequency_or_basis')
    if basis == 'qoq' and frequency != 'quarterly':
        raise BindingError('qoq_requires_quarterly')
    if type(count) is not int or count < 1:
        raise BindingError('positive_integer_consecutive_count_required')
    scope = period.get('scope')
    if not isinstance(scope, str) or not (scope == 'consolidated' or
            (scope.startswith('segment:') and scope[8:].strip())):
        raise BindingError('explicit_consolidated_or_segment_scope_required')
    unit = condition.get('unit')
    if not isinstance(unit, str) or not unit.strip():
        raise BindingError('unit_required')
    if basis != 'absolute' and (unit != 'percent' or not isinstance(period.get('source_unit'), str)
                                or not period['source_unit'].strip()):
        raise BindingError('growth_requires_percent_and_source_unit')
    end = _period_index(period.get('end'), frequency)
    return period, threshold, end, count


def _facts(items, root, *, evaluation_epoch=None):
    facts = {}
    provenance = []
    for item in items:
        relative = item.get('local_path')
        if not isinstance(relative, str) or not relative or '\\' in relative:
            raise BindingError('relative_posix_local_path_required')
        path = Path(relative)
        if path.is_absolute() or PureWindowsPath(relative).drive or '..' in path.parts:
            raise BindingError('evidence_path_escape')
        current = root
        for part in path.parts:
            current = current / part
            # Also reject in-root links: no linked file can change the read authority.
            if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                raise BindingError('evidence_link_forbidden')
        target = current.resolve(strict=True)
        if not target.is_relative_to(root):
            raise BindingError('evidence_path_escape')
        if target.suffix.lower() != '.json':
            raise BindingError('unsupported_source_format')
        raw = target.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != str(item.get('content_sha256', '')).lower():
            raise BindingError('source_hash_mismatch')
        pointer = item.get('fact_pointer')
        match = re.fullmatch(r'/facts/(0|[1-9]\d*)', pointer) if isinstance(pointer, str) else None
        if not match:
            raise BindingError('fact_pointer_required')
        doc = _json(raw, decimal=True)
        derived = isinstance(doc, dict) and ('projection' in doc or doc.get('role') == 'derived'
                                               or str(doc.get('schema_version', '')).startswith('pia_fact_projection_'))
        if derived:
            from pia_fact_prepare import FactError, verify_fact_projection
            try:
                verify_fact_projection(doc, root)
                if evaluation_epoch is not None:
                    cutoff = datetime.fromtimestamp(evaluation_epoch, timezone.utc)
                    from sec_edgar_fundamentals import parse_as_of
                    as_of = parse_as_of(doc['projection']['as_of'])
                    if (as_of > cutoff if isinstance(as_of, datetime) else as_of > cutoff.date()):
                        raise FactError('projection_after_evaluation')
                    from source_timing_contract import aware
                    if any(aware(r['retrieved_at']) > cutoff for r in doc['projection']['captures'].values()):
                        raise FactError('capture_after_evaluation')
            except (ValueError, KeyError, TypeError) as exc:
                raise BindingError('invalid_derived_projection:' + str(exc)) from exc
        rows = doc.get('facts') if isinstance(doc, dict) else None
        index = int(match[1])
        if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], dict):
            raise BindingError('fact_pointer_not_found')
        fact = rows[index]
        if set(fact) != {'symbol', 'metric', 'value', 'unit', 'period', 'scope'}:
            raise BindingError('unsupported_fact_shape')
        if not all(isinstance(fact[key], str) and fact[key] for key in
                   ('symbol', 'metric', 'unit', 'period', 'scope')):
            raise BindingError('invalid_fact_dimensions')
        value = _number(fact['value'])
        key = tuple(fact[key] for key in ('symbol', 'metric', 'unit', 'period', 'scope'))
        facts.setdefault(key, set()).add(value)
        provenance.append({'evidence_id': item['evidence_id'], 'content_sha256': digest,
                           'local_path': relative, 'fact_pointer': pointer,
                           **({'role': 'derived', 'verification': 'source_bound_numeric_consistency'} if derived else {})})
    return facts, provenance


def _compute(condition, symbol, facts, rule):
    period, threshold, end, count = rule
    frequency, basis = period['frequency'], period['basis']
    unit = condition['unit'] if basis == 'absolute' else period['source_unit']
    values = {}
    for (fact_symbol, metric, fact_unit, label, scope), candidates in facts.items():
        if (fact_symbol, metric, fact_unit, scope) == (symbol, condition['metric'], unit, period['scope']):
            index = _period_index(label, frequency)
            if len(candidates) != 1:
                raise BindingError('conflicting_facts')
            value = next(iter(candidates))
            # R1-001: never resolve contradictory period identities by reference order.
            if index in values and values[index] != value:
                raise BindingError('conflicting_facts')
            values[index] = value
    # Every required period is checked; one missing period is not a non-hit.
    required = range(end - count + 1, end + 1)
    comparisons = []
    observed = []
    for index in required:
        if index not in values:
            raise BindingError('required_period_fact_missing')
        value = values[index]
        if basis != 'absolute':
            offset = 4 if basis == 'yoy' and frequency == 'quarterly' else 1
            previous = values.get(index - offset)
            if previous is None or previous <= 0:
                raise BindingError('positive_comparison_base_required')
            # Exact rational arithmetic keeps equality/strict boundaries independent
            # of the ambient Decimal precision or binary floating-point rounding.
            value = (Fraction(value) / Fraction(previous) - 1) * 100
        operator = condition['operator']
        comparisons.append({'lt': value < threshold, 'lte': value <= threshold,
                            'gt': value > threshold, 'gte': value >= threshold,
                            'eq': value == threshold}[operator])
        observed.append(str(value))
    return all(comparisons), observed


def evaluate_bound_conditions(payload: dict, assessments: dict, expected: list,
                              *, conditions_file, evidence_root, evaluation_epoch,
                              valid_evidence: dict) -> dict:
    result: dict[str, Any] = {'condition_results': [], 'verified_hits': [],
                              'fatal_symbols': [], 'not_due_symbols': [],
                              'earliest_due_date': None, 'binding_errors': []}
    if conditions_file is None:
        result['binding_errors'].append('explicit_conditions_file_required')
        return result
    try:
        raw = Path(conditions_file).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        result['conditions_sha256'] = digest
        if payload.get('conditions_sha256') != digest:
            raise BindingError('conditions_hash_mismatch')
        ledger = _json(raw)
        if not isinstance(ledger, dict) or ledger.get('schema_version') != SCHEMA_VERSION or not isinstance(ledger.get('symbols'), dict):
            raise BindingError('invalid_ledger_schema')
        root = Path(evidence_root).resolve(strict=True) if evidence_root is not None else None
        if root is not None and not root.is_dir():
            raise BindingError('evidence_root_must_be_directory')
    except (OSError, BindingError) as exc:
        result['binding_errors'].append(type(exc).__name__ + ':' + str(exc))
        return result
    today = datetime.fromtimestamp(evaluation_epoch, timezone.utc).date().isoformat()
    due_dates = []
    for symbol in expected:
        assessment = assessments.get(symbol)
        if not isinstance(assessment, dict):
            result['binding_errors'].append(symbol + ':assessment_missing')
            continue
        try:
            entry = ledger['symbols'].get(symbol)
            if not isinstance(entry, dict) or not isinstance(entry.get('versions'), list):
                raise BindingError('symbol_not_in_ledger')
            previous_date = ''
            for index, version in enumerate(entry['versions'], 1):
                if not isinstance(version, dict) or type(version.get('version')) is not int or version['version'] != index:
                    raise BindingError('invalid_ledger_version_sequence')
                confirmed = iso_date(version.get('confirmed_at'), 'confirmed_at')
                if confirmed < previous_date:
                    raise BindingError('ledger_confirmation_backdated')
                previous_date = confirmed
            active = effective_version(entry, today)
            if active is None:
                raise BindingError('no_current_confirmed_conditions')
            locator = active.get('source_locator')
            if not isinstance(locator, str) or not locator.strip() or any(token in locator.lower() for token in RESERVED_LOCATORS):
                raise BindingError('confirmation_source_required')
            recorded = datetime.fromisoformat(str(active.get('recorded_at', '')).replace('Z', '+00:00'))
            if recorded.tzinfo is None or recorded.timestamp() > evaluation_epoch or recorded.date().isoformat() < active['confirmed_at']:
                raise BindingError('confirmation_recorded_at_invalid')
            raw_conditions = active.get('conditions')
            if not isinstance(raw_conditions, list):
                raise BindingError('conditions_must_be_list')
            compatible = []
            for raw_condition in raw_conditions:
                if not isinstance(raw_condition, dict) or not isinstance(raw_condition.get('operator'), str):
                    raise BindingError('invalid_condition_shape')
                candidate = dict(raw_condition)
                # The ledger validator predates Decimal. Validate its native shape,
                # then restore the exact original numeric token for comparisons.
                if isinstance(candidate.get('threshold'), Decimal):
                    candidate['threshold'] = float(candidate['threshold'])
                compatible.append(candidate)
            conditions = validate_conditions(compatible)
            for condition, original in zip(conditions, raw_conditions, strict=True):
                if 'threshold' in original:
                    condition['threshold'] = original['threshold']
            if type(assessment.get('condition_version')) is not int or assessment['condition_version'] != active['version']:
                raise BindingError('current_condition_version_mismatch')
            ids = assessment.get('condition_ids')
            current_ids = {condition['id'] for condition in conditions}
            if not isinstance(ids, list) or not ids or not all(isinstance(cid, str) for cid in ids) or len(ids) != len(set(ids)) or not set(ids) <= current_ids:
                raise BindingError('current_condition_ids_mismatch')
        except (BindingError, LedgerError, ValueError) as exc:
            result['binding_errors'].append(symbol + ':' + type(exc).__name__ + ':' + str(exc))
            continue
        symbol_results = []
        for condition in conditions:
            row = {'symbol': symbol, 'condition_id': condition['id'],
                   'condition_version': active['version'], 'confirmed_at': active['confirmed_at'],
                   'confirmation_source': locator, 'status': 'insufficient_evidence'}
            symbol_results.append(row)
            result['condition_results'].append(row)
            try:
                if condition['id'] not in ids:
                    raise BindingError('current_condition_omitted')
                rule = _rule(condition)
                due = iso_date(condition['due'], 'condition.due')
                if due > today:
                    if assessment.get('conclusion') == 'condition_not_due' and assessment.get('due_date') != due:
                        raise BindingError('submitted_due_date_mismatch')
                    row.update(status='verified_not_due', due_date=due)
                    due_dates.append(due)
                    continue
                if root is None:
                    raise BindingError('explicit_evidence_root_required')
                ids_evidence = assessment.get('evidence_ids')
                if not isinstance(ids_evidence, list) or not ids_evidence or not all(isinstance(eid, str) and eid in valid_evidence for eid in ids_evidence):
                    raise BindingError('valid_evidence_references_required')
                period = rule[0]
                end = rule[2]
                year = end if period['frequency'] == 'annual' else end // 4
                month = 12 if period['frequency'] == 'annual' else (end % 4 + 1) * 3
                if date(year, month, calendar.monthrange(year, month)[1]).isoformat() > today:
                    raise BindingError('required_period_not_ended')
                facts, provenance = _facts([valid_evidence[eid] for eid in ids_evidence], root,
                                           evaluation_epoch=evaluation_epoch)
                hit, observed = _compute(condition, symbol, facts, rule)
                row.update(status='verified_fatal_breach' if hit else 'verified_non_hit',
                           observed_values=observed, source_bindings=provenance)
                if hit:
                    result['verified_hits'].append(dict(row))
                    if symbol not in result['fatal_symbols']:
                        result['fatal_symbols'].append(symbol)
            except (OSError, BindingError, LedgerError, DecimalException) as exc:
                row['reason'] = type(exc).__name__ + ':' + str(exc)
        if symbol_results and all(row['status'] == 'verified_not_due' for row in symbol_results):
            result['not_due_symbols'].append(symbol)
    result['earliest_due_date'] = min(due_dates) if due_dates else None
    return result
