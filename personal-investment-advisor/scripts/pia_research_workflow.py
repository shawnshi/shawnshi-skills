"""Explicit offline F/M/J and existing risk composition; never investment approval."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

import pia_build
import pia_expectation_feedback
import pia_fact_prepare as facts
import pia_fundamental_diagnostic
import pia_risk_diagnostic as risk


def read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('input_object_required:' + str(path))
    return value


def write(path, value):
    path = facts.no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return path


def error(exc):
    return {'status': 'failed', 'errors': [type(exc).__name__ + ':' + str(exc)],
            'decision_scope': 'research_only'}


def input_path(root, relative, task):
    # Absence is a branch dependency error; escape/link/output overlap is a run-wide
    # safety rejection, checked even for an input that does not exist yet.
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or Path(relative).is_absolute() or PureWindowsPath(relative).drive
            or '..' in Path(relative).parts):
        raise ValueError('relative_root_bounded_input_required')
    path = facts.no_links(root / relative).resolve()
    if not path.is_relative_to(root) or any(path.is_relative_to(task / name) for name in ('out', 'inputs', 'fact_prepare')):
        raise ValueError('input_escape_or_output_overlap')
    return path


def check_refs(value, root, task):
    """Preflight component references before any derived output is written."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('local_path', 'raw_artifact'):
                input_path(root, item, task)
            else:
                check_refs(item, root, task)
    elif isinstance(value, list):
        for item in value:
            check_refs(item, root, task)


def risk_inputs(spec, root, task, gaps):
    requests = spec.get('requests', ['diagnostic'])
    if not isinstance(requests, list) or not requests or any(x not in ('diagnostic', 'inverse_vol', 'scenario') for x in requests):
        raise ValueError('risk.requests:diagnostic_inverse_vol_scenario_only')
    missing = []
    for field in ('weights_file', 'base_currency', 'window_start', 'window_end',
                  'annualization_factor', 'annualization_basis', 'as_of'):
        if spec.get(field) in (None, ''):
            missing.append(field)
    for field in missing:
        gaps['program_fetchable' if field == 'weights_file' else 'rule_confirmation_needed'].append('risk.' + field)
    policy = read(facts.bounded_path(root, spec['confirmed_policy'])) if spec.get('confirmed_policy') else {}
    bucket = policy.get('bucket_policy') or {}
    if 'inverse_vol' in requests or 'scenario' in requests:
        for field in ('positions_file', 'confirmed_policy'):
            if not spec.get(field):
                gaps['rule_confirmation_needed'].append('risk.' + field)
        for field in ('core', 'satellite', 'denominator', 'core_fraction', 'satellite_fraction', 'tolerance_fraction'):
            if bucket.get(field) in (None, ''):
                gaps['rule_confirmation_needed'].append('bucket_policy.' + field)
    if 'scenario' in requests:
        for field in ('horizon', 'scenario_names', 'main_local_total_returns', 'sensitivity_overrides', 'risk_thresholds'):
            if not policy.get(field):
                gaps['rule_confirmation_needed'].append('scenario.' + field)
        if policy.get('no_transactions_no_new_capital') is not True:
            gaps['rule_confirmation_needed'].append('scenario.no_transactions_no_new_capital:legacy_builder_requires_explicit_zero_turnover')
        if len(policy.get('scenario_names', [])) != 2:
            gaps['semantic_review_needed'].append('scenario:legacy_builder_requires_two_explicit_scenario_names')
        # The legacy scenario builder has positive-value fallbacks. Do not send zero
        # through them or reinterpret a new FX regime as its USD-only contract.
        for field in ('core_fraction', 'satellite_fraction', 'tolerance_fraction'):
            if bucket.get(field) == 0:
                gaps['semantic_review_needed'].append('scenario.' + field + ':zero_not_supported_by_legacy_builder')
    if missing:
        return {'status': 'insufficient_data', 'decision_scope': 'research_only'}
    if (isinstance(spec['annualization_factor'], bool) or spec['annualization_factor'] != risk.ANNUALIZATION_FACTOR
            or not isinstance(spec['annualization_basis'], str) or not spec['annualization_basis'].strip()):
        raise ValueError('risk:existing_method_requires_explicit_252_trading_day_basis')
    start = datetime.date.fromisoformat(spec['window_start'])
    end = datetime.date.fromisoformat(spec['window_end'])
    now = datetime.datetime.fromisoformat(spec['as_of'].replace('Z', '+00:00'))
    if start >= end or now.tzinfo is None or end > now.date():
        raise ValueError('risk:invalid_window_or_aware_as_of')
    weights = read(facts.bounded_path(root, spec['weights_file']))
    snapshot = read(facts.bounded_path(root, spec['positions_file'])) if spec.get('positions_file') else None
    weight_rows = {r['symbol']: r for r in weights.get('current_weights', [])}
    position_rows = {r['symbol']: r for r in snapshot.get('positions', [])} if snapshot else {}
    base = spec['base_currency']
    base_error = (weights.get('base_currency', base) != base or
                  (snapshot is not None and snapshot.get('base_currency') != base))
    currency_errors = []
    histories, fx_histories = {}, {}
    history_meta = {}
    for key, target in (('histories', histories), ('fx_histories', fx_histories)):
        for symbol, item in spec.get(key, {}).items():
            if not isinstance(item, dict) or any(not item.get(f) for f in ('file', 'source', 'source_locator', 'currency')):
                gaps['program_fetchable'].append('risk.' + key + '.' + symbol + ':source_currency_metadata')
                if key == 'histories':
                    currency_errors.append({'symbol': symbol, 'reason': 'history_source_currency_metadata_required'})
                continue
            if key == 'histories':
                wc = weight_rows.get(symbol, {}).get('currency')
                pc = position_rows.get(symbol, {}).get('currency') if snapshot is not None else wc
                if base_error or not wc or not pc or item['currency'] != wc or pc != wc or wc != base:
                    # The existing equity method has no local-price FX conversion.
                    issue = {'symbol': symbol, 'reason': 'currency_semantics_unverified_or_unsupported',
                             'history_currency': item['currency'], 'weight_currency': wc,
                             'position_currency': pc, 'base_currency': base}
                    currency_errors.append(issue)
                    gaps['semantic_review_needed'].append(issue)
                    continue
            elif item['currency'] != base or not symbol.endswith(base):
                issue = {'symbol': symbol, 'reason': 'FX_pair_quote_currency_mismatch'}
                gaps['semantic_review_needed'].append(issue)
                continue
            source = facts.bounded_path(root, item['file'])
            payload = read(source)
            if payload.get('currency', item['currency']) != item['currency']:
                issue = {'symbol': symbol, 'reason': 'history_payload_currency_mismatch'}
                gaps['semantic_review_needed'].append(issue)
                if key == 'histories':
                    currency_errors.append(issue)
                continue
            if payload.get('status') in ('error', 'failed', 'provider_error') or payload.get('error'):
                gaps['provider/error'].append({'symbol': symbol, 'provider_result': payload})
                continue
            try:
                series = risk.close_series(source)
            except (ValueError, OSError, risk.RiskError) as exc:
                gaps['provider/error'].append({'symbol': symbol, **error(exc)})
                continue
            selected = {day: value for day, value in series.items() if start.isoformat() <= day <= end.isoformat()}
            path = write(task / 'inputs' / (key + '-' + hashlib.sha256(symbol.encode()).hexdigest()[:16] + '.json'),
                         {'history': [{'Date': day, 'Close': value} for day, value in sorted(selected.items())]})
            target[symbol] = path
            history_meta[symbol] = dict(item, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    try:
        result = risk.compute(weights, histories, fx_histories=fx_histories,
                              base_currency=spec['base_currency'], now=now)
    except risk.RiskError as exc:
        if not currency_errors:
            raise
        return {'status': 'insufficient_data', 'decision_scope': 'research_only',
                'diagnostic': {'status': 'insufficient_data', 'errors': [type(exc).__name__ + ':' + str(exc)],
                               'currency_errors': currency_errors, 'original_history_sources': history_meta},
                **{name: {'status': 'insufficient_data', 'errors': currency_errors}
                   for name in requests if name != 'diagnostic'}}
    result['currency_errors'] = currency_errors
    result['input_contract'] = {k: spec[k] for k in ('window_start', 'window_end', 'annualization_factor', 'annualization_basis', 'base_currency', 'as_of')}
    result['original_history_sources'] = history_meta
    write(task / 'out' / 'risk_diagnostic.json', result)
    branches: dict[str, Any] = {'diagnostic': result}
    # The method's fixed 252 is not a portfolio policy, and partial coverage stays partial.
    if any(x in requests for x in ('inverse_vol', 'scenario')):
        builder_gaps = [g for g in gaps['rule_confirmation_needed'] if not g.startswith('scenario.')]
        scenario_gaps = [g for g in gaps['rule_confirmation_needed'] + gaps['semantic_review_needed']
                         if isinstance(g, str) and g.startswith(('scenario.', 'scenario:'))]
        if builder_gaps:
            branches['builders'] = {'status': 'insufficient_data', 'errors': builder_gaps}
        else:
            positions = facts.bounded_path(root, spec['positions_file'])
            policy_path = facts.bounded_path(root, spec['confirmed_policy'])
            args = argparse.Namespace(task_dir=task, weights_file=facts.bounded_path(root, spec['weights_file']),
                                   positions_file=positions, confirmed_policy=policy_path, force=False)
            if 'inverse_vol' in requests:
                window = result['observation_window']
                observations = {'as_of': spec['as_of'], 'volatility_observations': {
                    symbol: {'annualized_volatility': vol, 'observation_count': window['common_observations'],
                             'window_start': window['first'], 'window_end': window['last'], 'as_of': spec['as_of'],
                             'source': history_meta[symbol]['source'], 'source_locator': history_meta[symbol]['source_locator'],
                             'currency': history_meta[symbol]['currency'], 'content_sha256': history_meta[symbol]['sha256'],
                             'annualization_factor': spec['annualization_factor'], 'annualization_basis': spec['annualization_basis']}
                    for symbol, vol in result['annualized_volatility'].items()}}
                args.volatilities_file = write(task / 'inputs' / 'derived_volatilities.json', observations)
                try:
                    branches['inverse_vol'] = ({'status': 'insufficient_data', 'errors': currency_errors}
                                               if currency_errors else pia_build.build_inverse_vol(args))
                except (ValueError, OSError, pia_build.BuildError) as exc:
                    branches['inverse_vol'] = error(exc)
            if 'scenario' in requests:
                snapshot = read(positions)
                foreign = {p.get('currency') for p in snapshot.get('positions', [])
                           if p.get('currency') != spec['base_currency']}
                if scenario_gaps:
                    branches['scenario'] = {'status': 'insufficient_data', 'errors': scenario_gaps}
                elif foreign - {'USD'} or ('USD' in foreign and (policy.get('main_usd_cny_return') is None or (policy.get('sensitivity_overrides') or {}).get('usd_cny_return') is None)):
                    branches['scenario'] = {'status': 'insufficient_data', 'errors': ['scenario:explicit_supported_FX_shocks_required']}
                    gaps['rule_confirmation_needed'].append('scenario:explicit_supported_FX_shocks_required')
                else:
                    try:
                        branches['scenario'] = pia_build.build_scenario(args)
                    except (ValueError, OSError, pia_build.BuildError) as exc:
                        branches['scenario'] = error(exc)
                    branches['scenario']['input_contract'] = {k: policy[k] for k in ('horizon', 'risk_thresholds', 'no_transactions_no_new_capital')}
                    branches['scenario']['threshold_boundary'] = 'declared only; builder is not a threshold approval gate'
    branches['status'] = 'insufficient_data' if any(isinstance(v, dict) and v.get('status') != 'complete' for v in branches.values()) else 'complete'
    branches['decision_scope'] = 'research_only'
    return branches


def run(input_file, evidence_root, task_dir):
    root = facts.no_links(evidence_root).resolve(strict=True)
    source = facts.no_links(input_file).resolve(strict=True)
    task = facts.no_links(task_dir).resolve()
    payload = read(source)
    if not root.is_dir() or not task.is_relative_to(root) or source.is_relative_to(task / 'out') or source.is_relative_to(task / 'inputs') or source.is_relative_to(task / 'fact_prepare'):
        raise ValueError('task_must_be_within_explicit_evidence_root_and_not_overwrite_input')
    for name in ('out', 'inputs', 'fact_prepare'):
        if (task / name).exists():
            raise ValueError('output_directory_already_exists:' + name)
    check_refs(payload, root, task)
    if 'native_report' in payload and 'fact_input' in payload:
        raise ValueError('select_native_report_or_fact_input_not_both')
    inputs = {}
    for key in ('native_report', 'fact_input', 'fundamental_input', 'feedback_input'):
        if key in payload:
            inputs[key] = input_path(root, payload[key], task)
    native = {}
    if 'native_report' in inputs:
        try:
            native = read(inputs['native_report'])
            native = native.get('result', native)
            if not isinstance(native, dict):
                raise ValueError('native_report_object_required')
        except (ValueError, OSError) as exc:
            native = error(exc)
        if native.get('fact_prepare_input'):
            if facts.no_links(native['evidence_root']).resolve(strict=True) != root:
                raise ValueError('native_capture_root_must_equal_explicit_evidence_root')
            selected = facts.no_links(native['fact_prepare_input']).resolve()
            if not selected.is_relative_to(root):
                raise ValueError('native_fact_input_outside_explicit_root')
            inputs['fact_input'] = input_path(root, selected.relative_to(root).as_posix(), task)
    for path in inputs.values():
        if any(path.is_relative_to(task / name) for name in ('out', 'inputs', 'fact_prepare')):
            raise ValueError('output_would_cover_input')
        try:
            document = read(path)
        except (ValueError, OSError):
            continue  # The owning branch below retains its real dependency failure.
        check_refs(document, root, task)
    spec = payload.get('risk')
    if spec is not None:
        if not isinstance(spec, dict):
            raise ValueError('risk_object_required')
        for key in ('weights_file', 'positions_file', 'confirmed_policy'):
            if key in spec:
                input_path(root, spec[key], task)
        for key in ('histories', 'fx_histories'):
            for item in spec.get(key, {}).values():
                input_path(root, item['file'], task)
    gaps = {key: [] for key in ('program_fetchable', 'semantic_review_needed', 'rule_confirmation_needed', 'provider/error')}
    branches = {}
    if 'native_report' in inputs and native.get('status') != 'complete':
        gaps['provider/error'].append({'native_capture_status': native.get('status'), 'provider_result': native})
    if 'native_report' in inputs and 'fact_input' not in inputs:
        branches['fact_prepare'] = {'status': 'failed', 'decision_scope': 'research_only',
                                    'provider_result': native, 'errors': ['native_capture_input_unavailable']}
        gaps['provider/error'].append(branches['fact_prepare'])
    if 'fact_input' in inputs:
        try:
            branches['fact_prepare'] = facts.prepare_facts(inputs['fact_input'], root, task)
            prepared = branches['fact_prepare']
            gaps['provider/error'].extend(prepared.get('errors', []))
            gaps['semantic_review_needed'].extend(prepared['rules_need_confirmation'])
            if prepared['candidates']:
                gaps['semantic_review_needed'].append('PDF candidates are unverified; page semantics/coverage require review')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            branches['fact_prepare'] = error(exc)
            gaps['provider/error'].append(branches['fact_prepare'])
    if 'fundamental_input' in inputs:
        try:
            data = read(inputs['fundamental_input'])
            data.setdefault('source_facts', []).extend(
                {'fact': fact, 'proof': projection['document']}
                for projection in branches.get('fact_prepare', {}).get('projections', [])
                for fact in projection['document']['facts'])
            branches['fundamental_diagnostic'] = pia_fundamental_diagnostic.evaluate(data, evidence_root=root)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            branches['fundamental_diagnostic'] = error(exc)
    if 'feedback_input' in inputs:
        try:
            data = read(inputs['feedback_input'])
            for comparison in data.get('comparisons', []):
                if not isinstance(comparison, dict) or 'actual_refs' in comparison:
                    continue
                try:
                    prior_ref = comparison['prior_ref']
                    prior_path = facts.bounded_path(root, prior_ref['local_path'])
                    if hashlib.sha256(prior_path.read_bytes()).hexdigest() != prior_ref['content_sha256']:
                        continue
                    prior = facts.pointer(read(prior_path), prior_ref['pointer'])
                    if not isinstance(prior, dict):
                        continue  # J retains the original expectation_object_required error.
                    comparison['actual_refs'] = [
                        {'local_path': Path(p['file']).relative_to(root).as_posix(), 'content_sha256': p['content_sha256'], 'pointer': '/facts/' + str(index)}
                        for p in branches.get('fact_prepare', {}).get('projections', [])
                        for index, fact in enumerate(p['document']['facts'])
                        if all(prior.get(k) == fact[k] for k in ('symbol', 'metric', 'unit', 'period', 'scope'))]
                except pia_expectation_feedback.ERRORS:
                    # J owns per-item error reporting, including the original prior failure.
                    continue
            branches['expectation_feedback'] = pia_expectation_feedback.evaluate(data, evidence_root=root)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            branches['expectation_feedback'] = error(exc)
    if spec is not None:
        try:
            branches['risk'] = risk_inputs(spec, root, task, gaps)
        except (ValueError, OSError, KeyError, TypeError, risk.RiskError, pia_build.BuildError) as exc:
            branches['risk'] = error(exc)
            gaps['provider/error'].append(branches['risk'])
    if not branches:
        raise ValueError('at_least_one_explicit_branch_required')
    for key, value in branches.items():
        if value.get('status') not in ('complete',):
            category = ('provider/error' if value.get('status') == 'failed' else
                        'semantic_review_needed' if key == 'fundamental_diagnostic' else 'program_fetchable')
            gaps[category].append({'branch': key, 'status': value.get('status'), 'errors': value.get('errors', [])})
        write(task / 'out' / (key + '.json'), value)
    result = {'schema_version': 'pia_research_workflow_v1', 'status': 'complete' if all(b.get('status') == 'complete' for b in branches.values()) and not any(gaps.values()) else 'incomplete',
              'decision_scope': 'research_only', 'formal_use_allowed': False, 'alpha_eligible': False,
              'completion_scope': 'listed offline component diagnostics, not source semantics or investment readiness',
              'branches': branches, 'gaps': gaps, 'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'limitations': ['source-bound numeric consistency is not publisher authentication',
                              'declared scenarios are not validated forecasts', 'prior timing remains unverified; no formal calibration',
                              'fundamental and quantitative Alpha gates remain separate', 'no private scan, fetch, journal append or orders']}
    write(task / 'out' / 'research_workflow.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-file', 'evidence-root', 'task-dir'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.input_file, args.evidence_root, args.task_dir)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = error(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    sys.exit(main())
