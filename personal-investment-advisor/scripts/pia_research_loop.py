"""Explicit-input, offline, research-only event/condition review records."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import stat
from pathlib import Path, PureWindowsPath

from artifact_io import atomic_bytes
from management_claim_tracker import finite_number
from status_contract import exit_code_for

SCHEMA = Path(__file__).resolve().parent.parent / 'references/research_loop_schema.json'
MAX_INPUT = 2 * 1024 * 1024
MAX_ARTIFACT = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_RECORD = 16 * 1024 * 1024
EVALUATION_RULE_VERSION = 'research_loop_proof_v3_two_phase'


class LoopError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError) as exc:
        raise LoopError('invalid ISO timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LoopError('timestamp requires timezone')
    return parsed


def validate(value, spec, schema, label='input'):
    if '$ref' in spec:
        return validate(value, schema['$defs'][spec['$ref'].split('/')[-1]], schema, label)
    if 'anyOf' in spec:
        for candidate in spec['anyOf']:
            try:
                validate(value, candidate, schema, label)
                return
            except LoopError:
                pass
        raise LoopError(f'{label}: invalid nullable value')
    expected = spec.get('type')
    okay = {'object': isinstance(value, dict), 'array': isinstance(value, list),
            'string': isinstance(value, str), 'boolean': type(value) is bool,
            'null': value is None, 'number': finite_number(value),
            'integer': type(value) is int and finite_number(value)}
    if expected and not okay[expected]:
        raise LoopError(f'{label}: expected {expected}')
    if 'const' in spec and value != spec['const']:
        raise LoopError(f'{label}: unexpected constant')
    if 'enum' in spec and value not in spec['enum']:
        raise LoopError(f'{label}: unknown enum')
    if isinstance(value, dict):
        properties = spec['properties']
        if set(value) - set(properties) or set(spec['required']) - set(value):
            raise LoopError(f'{label}: missing or additional fields')
        for key, item in value.items():
            validate(item, properties[key], schema, f'{label}.{key}')
    elif isinstance(value, list):
        if not spec.get('minItems', 0) <= len(value) <= spec.get('maxItems', 1000000):
            raise LoopError(f'{label}: item limit')
        if spec.get('uniqueItems') and len({digest(item) for item in value}) != len(value):
            raise LoopError(f'{label}: duplicate items')
        for index, item in enumerate(value):
            validate(item, spec['items'], schema, f'{label}[{index}]')
    elif isinstance(value, str):
        if not spec.get('minLength', 0) <= len(value) <= spec.get('maxLength', 1000000):
            raise LoopError(f'{label}: string limit')
        if 'pattern' in spec and re.search(spec['pattern'], value) is None:
            raise LoopError(f'{label}: invalid pattern')
        if spec.get('format') == 'date-time':
            timestamp(value)
        if spec.get('format') == 'date':
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise LoopError(f'{label}: invalid date') from exc
    elif type(value) in (int, float):
        if value < spec.get('minimum', value) or value > spec.get('maximum', value):
            raise LoopError(f'{label}: numeric bound')


def referenced_events(link):
    return set(link['event_ids']) | {row['event_id'] for row in link['counterevidence'] or []}


def no_links(path):
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise LoopError('symlink/reparse paths forbidden')


def read_json(path, limit=MAX_INPUT):
    no_links(path)
    if path.stat().st_size > limit:
        raise LoopError('input file size limit')
    raw = path.read_bytes()
    if len(raw) > limit:
        raise LoopError('input file size limit')
    return json.loads(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest()


def artifact(row, root, budget, *, return_bytes=False):
    relative, declared = row['artifact'], row['content_sha256']
    if relative is None:
        if declared is not None:
            raise LoopError('digest without artifact')
        return None
    if declared is None:
        raise LoopError('artifact requires digest')
    normalized = relative.replace('\\', '/')
    parts = normalized.split('/')
    if (Path(normalized).is_absolute() or PureWindowsPath(relative).drive
            or any(part in ('', '.', '..') for part in parts)):
        raise LoopError('artifact path must be strictly relative')
    path = root / normalized
    no_links(path)
    if not path.resolve().is_relative_to(root.resolve()):
        raise LoopError('artifact escaped evidence root')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT:
        raise LoopError('artifact must be bounded regular file')
    raw = path.read_bytes()
    budget[0] += len(raw)
    if len(raw) > MAX_ARTIFACT or budget[0] > MAX_TOTAL:
        raise LoopError('artifact byte limit')
    actual = hashlib.sha256(raw).hexdigest()
    if actual != declared.lower():
        raise LoopError('artifact hash mismatch')
    return raw if return_bytes else actual


def persist(task, record_id, key, payload):
    directory = task / 'research_loop'
    path = directory / (record_id + '.json')
    no_links(path)
    if path.exists():
        existing, _ = read_json(path, MAX_RECORD)
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        validate(existing, schema['$defs']['record'], schema, 'existing_record')
        checksum = existing.get('record_sha256')
        if digest({k: v for k, v in existing.items() if k != 'record_sha256'}) != checksum:
            raise LoopError('existing record integrity conflict')
        if existing.get('record_key') != key:
            raise LoopError('record_id conflict; use a new explicit record_id')
        return existing, path
    payload = {**payload, 'record_key': key,
               'generated_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    payload['record_sha256'] = digest(payload)
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    validate(payload, schema['$defs']['record'], schema, 'record')
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode()
    if len(rendered) > MAX_RECORD:
        raise LoopError('record byte limit')
    atomic_bytes(path, rendered)
    return payload, path


def run(input_file, evidence_root, task_dir, decisions_file=None, require_authenticated_review=False):
    if require_authenticated_review:
        raise LoopError('required_capability_unavailable: authenticated review verifier; rule/key binding unavailable; BLOCKED')
    root = Path(evidence_root).absolute()
    task = Path(task_dir).absolute()
    inputs = [Path(input_file).absolute()] + ([Path(decisions_file).absolute()] if decisions_file else [])
    no_links(root)
    no_links(task)
    if not root.is_dir():
        raise LoopError('evidence root is not a directory')
    if (task.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(task.resolve())
            or any(path.resolve().is_relative_to(task.resolve()) for path in inputs)):
        raise LoopError('task must be disjoint from evidence and input files')
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    bundle, input_sha = read_json(inputs[0])
    validate(bundle, schema, schema)
    as_of = timestamp(bundle['as_of'])
    if as_of > dt.datetime.now(dt.timezone.utc):
        raise LoopError('future as_of')
    budget = [0]
    events, groups, canonical = {}, {}, []
    tasks = {}

    def gap(kind, identity, detail):
        key = digest([kind, identity])
        tasks[key] = {'task_id': key, 'kind': kind, 'identity': identity,
                      'detail': detail, 'state': 'pending_human_evidence', 'downloads_scheduled': False}

    for event in bundle['events']:
        eid = event['event_id']
        if eid in events:
            raise LoopError('duplicate event_id')
        published, retrieved = timestamp(event['published_at']), timestamp(event['retrieved_at'])
        if published > retrieved or retrieved > as_of:
            raise LoopError('future or inconsistent event timestamps')
        physical = artifact(event, root, budget)
        if event['body_retrieved'] and physical is None:
            raise LoopError('body acquired without artifact')
        if event['health'] == 'ok' and event['source_error'] is not None:
            raise LoopError('healthy source contradicts source_error')
        if event['health'] == 'broken' and event['source_error'] is None:
            raise LoopError('broken source requires original source_error')
        if event['health'] != 'ok':
            gap('source_health', eid, {'health': event['health'], 'error': event['source_error']})
        if not event['body_retrieved']:
            gap('missing_body', eid, 'body not acquired')
        if not event['coverage_complete'] or event['coverage_limits']:
            gap('coverage_unproven', eid, event['coverage_limits'])
        events[eid] = event
        identity = (event['source_locator'], physical) if physical else ('missing', eid)
        if identity in groups:
            group = groups[identity]
            if group['symbol'] != event['symbol']:
                raise LoopError('same content identity has conflicting symbols')
            group['event_aliases'].append(eid)
            group['source_receipts'].append(event)
        else:
            group = {'event_id': eid, 'symbol': event['symbol'], 'event_aliases': [eid],
                     'source_receipts': [event]}
            groups[identity] = group
            canonical.append(group)
    conditions, versions, condition_sources = {}, set(), {}
    for condition in bundle['conditions']:
        identity = (condition['condition_id'], condition['version'])
        if identity in versions:
            raise LoopError('duplicate condition version')
        versions.add(identity)
        confirmed = timestamp(condition['confirmed_at'])
        effective = timestamp(condition['effective_from'])
        if confirmed > as_of:
            raise LoopError('future condition confirmation')
        if condition['due'] != '持续':
            try:
                dt.date.fromisoformat(condition['due'])
            except ValueError as exc:
                raise LoopError('invalid condition due date') from exc
        if condition['period'] and condition['period']['start'] > condition['period']['end']:
            raise LoopError('condition period reversed')
        condition_sources[identity] = artifact(condition, root, budget)
        if effective <= as_of:
            previous = conditions.get(condition['condition_id'])
            if previous is None or condition['version'] > previous['version']:
                conditions[condition['condition_id']] = condition
    for selected in conditions.values():
        identity = (selected['condition_id'], selected['version'])
        if condition_sources[identity] is None:
            gap('missing_condition_source', str(identity), 'selected condition original absent')
    links, assessments, linked_events = {}, [], set()
    for link in bundle['links']:
        lid = link['link_id']
        if lid in links or any(eid not in events for eid in link['event_ids']):
            raise LoopError('duplicate link or unknown event reference')
        links[lid] = link
        if link['actual_period'] and link['actual_period']['start'] > link['actual_period']['end']:
            raise LoopError('actual period reversed')
        linked_events.update(link['event_ids'])
        condition = conditions.get(link['condition_id'])
        row = {'link_id': lid, 'condition_id': link['condition_id'],
               'condition_version': link['condition_version'], 'event_ids': link['event_ids'],
               'assessment': 'insufficient_evidence', 'comparison_result': None}
        if condition is None:
            gap('missing_effective_version', lid, 'no confirmed effective condition version at as_of')
        else:
            if condition['version'] != link['condition_version']:
                raise LoopError('link references stale condition version')
            if any(events[eid]['symbol'] != condition['symbol'] for eid in link['event_ids']):
                raise LoopError('link symbol identity conflict')
            not_due = condition['due'] != '持续' and as_of.date() < dt.date.fromisoformat(condition['due'])
            row['assessment'] = 'not_due' if not_due else 'insufficient_evidence'
            if link['locator'] is None:
                gap('missing_original_locator', lid, 'page/table/line location not provided')
            if not link['counterevidence']:
                gap('missing_counterevidence', lid, 'absence of counterevidence is not verified')
            else:
                for counter in link['counterevidence']:
                    if counter['event_id'] not in events:
                        raise LoopError('unknown counterevidence event')
            proof_ready = (
                condition_sources[(condition['condition_id'], condition['version'])] is not None
                and link['locator'] is not None and bool(link['counterevidence'])
                and all(events[eid]['body_retrieved'] and events[eid]['health'] == 'ok'
                        and events[eid]['coverage_complete'] and not events[eid]['coverage_limits']
                        for eid in referenced_events(link)))
            if not not_due and condition['operator'] != 'qualitative':
                period = condition['period']
                actual_period = link['actual_period']
                matched = (period is not None and actual_period is not None
                           and actual_period['complete'] and period['start'] == actual_period['start']
                           and period['end'] == actual_period['end'] and dt.date.fromisoformat(actual_period['end']) <= as_of.date())
                if not matched:
                    gap('period_unproven', lid, 'actual period is incomplete or mismatched')
                if condition['unit'] is None or link['unit'] != condition['unit']:
                    gap('unit_unproven', lid, 'unit is missing or mismatched')
                if link['actual'] is None or condition['threshold'] is None:
                    gap('missing_numeric_fact', lid, 'actual or threshold missing')
                if (proof_ready and matched and link['unit'] == condition['unit'] and condition['unit'] is not None
                        and link['actual'] is not None and condition['threshold'] is not None):
                    operators = {'lt': lambda a,b:a<b, 'lte':lambda a,b:a<=b,
                                 'gt':lambda a,b:a>b, 'gte':lambda a,b:a>=b, 'eq':lambda a,b:a==b}
                    row['comparison_result'] = operators[condition['operator']](link['actual'], condition['threshold'])
                    row['assessment'] = 'met' if row['comparison_result'] else 'missed'
            elif condition['operator'] == 'qualitative' and not not_due and proof_ready:
                row['assessment'] = 'human_semantic_review_only'
        assessments.append(row)
    if not events:
        gap('empty_scope', bundle['record_id'], 'explicit empty event list, not a source error or safety verdict')
    common = {'schema_version': 'pia_research_loop_record_v1', 'decision_scope': 'research_only',
              'scope': bundle['scope'], 'as_of': bundle['as_of'], 'input_sha256': input_sha,
              'orders_executed': False, 'investment_authorized': False, 'formal_use_allowed': False,
              'thesis_safety': 'not_assessed', 'business_facts_authenticated': False,
              'human_identity_authenticated': False, 'event_coverage_claim': 'listed_events_only',
              'errors': [], 'events': canonical, 'selected_conditions': list(conditions.values()),
              'assessments': assessments, 'unlinked_event_ids': sorted(set(events)-linked_events)}
    proposal_key = digest([EVALUATION_RULE_VERSION, input_sha, str(root.resolve()), bundle])
    proposal = {**common, 'kind': 'proposal', 'record_id': bundle['record_id'],
                'status': 'insufficient_evidence' if tasks else 'incomplete',
                'detail_status': 'pending_human_review', 'evidence_tasks': sorted(tasks.values(), key=lambda x:x['task_id']),
                'human_reviews': []}
    if decisions_file is None:
        stored_proposal, proposal_path = persist(task, bundle['record_id'], proposal_key, proposal)
        return {**stored_proposal, 'record_file': str(proposal_path),
                'proposal_sha256': stored_proposal['record_sha256']}
    proposal_path = task / 'research_loop' / (bundle['record_id'] + '.json')
    if not proposal_path.is_file():
        raise LoopError('previously committed proposal required; receipt phase never creates proposal')
    stored_proposal, _ = read_json(proposal_path, MAX_RECORD)
    validate(stored_proposal, schema['$defs']['record'], schema, 'committed_proposal')
    if (stored_proposal['kind'] != 'proposal' or stored_proposal['record_id'] != bundle['record_id']
            or stored_proposal['record_key'] != proposal_key
            or digest({k:v for k,v in stored_proposal.items() if k != 'record_sha256'}) != stored_proposal['record_sha256']):
        raise LoopError('committed proposal integrity/key conflict')
    decision_data, decisions_sha = read_json(inputs[1])
    validate(decision_data, schema['$defs']['decision_file'], schema, 'decisions')
    if decision_data['proposal_sha256'] != stored_proposal['record_sha256']:
        raise LoopError('decision proposal hash mismatch')
    if decision_data['record_id'] == bundle['record_id']:
        raise LoopError('receipt requires independent record_id')
    decisions = {}
    for decision in decision_data['decisions']:
        lid = decision['link_id']
        if lid in decisions or lid not in links:
            raise LoopError('duplicate decision or unknown link')
        link = links[lid]
        condition = conditions.get(link['condition_id'])
        if (condition is None or decision['condition_version'] != condition['version']
                or set(decision['event_ids']) != set(link['event_ids'])):
            raise LoopError('decision event/version identity mismatch')
        reviewed = timestamp(decision['reviewed_at'])
        if reviewed > as_of or reviewed < timestamp(condition['confirmed_at']) or any(
                reviewed < timestamp(events[eid][field])
                for eid in referenced_events(link) for field in ('published_at', 'retrieved_at')):
            raise LoopError('future or premature human review')
        decisions[lid] = decision
        if decision['action'] == 'return':
            gap('human_return', lid, decision['reason'])
        if decision['action'] == 'reject':
            # Rejecting a relation closes that relation only, not the event/source gaps.
            tasks = {key:item for key,item in tasks.items() if item['identity'] != lid}
            next(row for row in assessments if row['link_id'] == lid).update(
                assessment='rejected_association', comparison_result=None)
    pending = sorted(set(links) - set(decisions))
    status = ('insufficient_evidence' if tasks else 'incomplete' if pending or common['unlinked_event_ids'] or not links else 'complete')
    receipt = {**common, 'kind':'receipt', 'record_id':decision_data['record_id'],
               'proposal_sha256':stored_proposal['record_sha256'], 'decisions_sha256':decisions_sha,
               'status':status, 'detail_status':'finite_scope_review_recorded',
               'evidence_tasks':sorted(tasks.values(), key=lambda x:x['task_id']),
               'pending_link_ids':pending, 'human_reviews':list(decisions.values())}
    stored, path = persist(task, decision_data['record_id'], digest([proposal_key, decisions_sha]), receipt)
    return {**stored, 'record_file':str(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-file', required=True)
    parser.add_argument('--evidence-root', required=True)
    parser.add_argument('--task-dir', required=True)
    parser.add_argument('--decisions-file')
    parser.add_argument('--require-authenticated-review', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run(args.input_file, args.evidence_root, args.task_dir, args.decisions_file, args.require_authenticated_review)
    except (LoopError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {'status':'failed', 'detail_status':('required_capability_unavailable' if str(exc).startswith('required_capability_unavailable') else 'research_loop_invalid_input_or_commit'),
                  'decision_scope':'research_only', 'orders_executed':False,
                  'investment_authorized':False, 'formal_use_allowed':False,
                  'errors':[f'{type(exc).__name__}: {exc}']}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return exit_code_for(result['status'])


if __name__ == '__main__':
    raise SystemExit(main())
