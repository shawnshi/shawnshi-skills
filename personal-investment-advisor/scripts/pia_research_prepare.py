"""Convert an explicit collector report into unconfirmed research candidates; no collection."""
import argparse
import datetime as dt
import json
from pathlib import Path

import pia_research_loop as loop
from artifact_io import atomic_bytes
from status_contract import exit_code_for


def prepare(channel_report, template_file, evidence_root, task_dir):
    root, task = Path(evidence_root).absolute(), Path(task_dir).absolute()
    inputs = [Path(channel_report).absolute(), Path(template_file).absolute()]
    for path in [root, task, *inputs]:
        loop.no_links(path)
    if not root.is_dir() or task.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(task.resolve()) or any(p.resolve().is_relative_to(task.resolve()) for p in inputs):
        raise loop.LoopError('task must be disjoint from explicit sources')
    report, report_sha = loop.read_json(inputs[0])
    bundle, template_sha = loop.read_json(inputs[1])
    schema = json.loads(loop.SCHEMA.read_text(encoding='utf-8'))
    loop.validate(bundle, schema, schema)
    if bundle['events'] or bundle['links']:
        raise loop.LoopError('prepare template requires empty events and links; conditions remain caller supplied')
    as_of = loop.timestamp(bundle['as_of'])
    if as_of > dt.datetime.now(dt.timezone.utc):
        raise loop.LoopError('future as_of')
    if not isinstance(report, dict) or not isinstance(report.get('channel_results'), list):
        raise loop.LoopError('explicit collector channel_results required')
    candidates, tasks, budget = [], [], [0]
    for channel in report['channel_results']:
        if not isinstance(channel, dict) or not isinstance(channel.get('records', []), list):
            raise loop.LoopError('invalid collector record list')
        records = channel.get('records')
        if records is None:
            records = [channel] if channel.get('chosen') else []
        if not records:
            tasks.append({'symbol':channel.get('symbol'), 'kind':'source_or_window_gap', 'health':channel.get('health'), 'detail':channel.get('reason')})
        for row in records:
            if len(candidates) >= 100:
                raise loop.LoopError('event item limit 100; use explicit separate batch inputs, no rows discarded')
            chosen = row['chosen']
            eid = 'candidate_' + str(len(candidates) + 1)
            relative = None
            declared = row.get('content_sha256')
            if row.get('artifact') is not None:
                path = Path(row['artifact'])
                if '..' in path.parts:
                    raise loop.LoopError('collector artifact traversal forbidden')
                path = path if path.is_absolute() else root / path
                loop.no_links(path)
                if not path.resolve().is_relative_to(root.resolve()):
                    raise loop.LoopError('collector artifact escaped evidence root')
                relative = path.resolve().relative_to(root.resolve()).as_posix()
            event = {'event_id':eid, 'symbol':channel['symbol'], 'published_at':chosen['published_at'],
                     'retrieved_at':row['retrieved_at'], 'source_locator':row['source_locator'],
                     'artifact':relative, 'content_sha256':declared, 'body_retrieved':row.get('body_retrieved', False),
                     'health':row['health'], 'source_error':row.get('source_error'), 'coverage_complete':False,
                     'coverage_limits':channel.get('coverage_limitations') or ['pagination and material event completeness unproven']}
            if event['health'] == 'broken' and not event['source_error']:
                event['source_error'] = (row.get('document_retrieval') or {}).get('error')
                if not event['source_error']:
                    raise loop.LoopError('broken candidate requires original source error')
            published, retrieved = loop.timestamp(event['published_at']), loop.timestamp(event['retrieved_at'])
            if published > retrieved or retrieved > as_of:
                raise loop.LoopError('future/inconsistent candidate timestamp')
            loop.artifact(event, root, budget)
            if event['body_retrieved'] and relative is None:
                raise loop.LoopError('body acquired without artifact')
            bundle['events'].append(event)
            candidates.append({'event_id':eid, 'candidate_title':chosen.get('title'),
                               'condition_candidates':[{'condition_id':c['condition_id'], 'version':c['version']} for c in bundle['conditions'] if c['symbol'] == channel['symbol']],
                               'relation_confirmed':False, 'source_locator':event['source_locator'],
                               'document_retrieval':row.get('document_retrieval')})
            tasks.append({'event_id':eid, 'required':['human relation', 'original value/locator/unit/period', 'counterevidence', 'source pagination coverage'] + ([] if event['body_retrieved'] else ['original body'])})
    loop.validate(bundle, schema, schema)
    for c in bundle['conditions']:
        if loop.timestamp(c['confirmed_at']) > as_of or (c['period'] and c['period']['start'] > c['period']['end']):
            raise loop.LoopError('future confirmation or reversed condition period')
        loop.artifact(c, root, budget)
    output = task / 'research_prepare' / 'loop-bundle.json'
    loop.no_links(output)
    rendered = json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False).encode()
    if output.exists():
        if output.read_bytes() != rendered:
            raise loop.LoopError('prepared bundle conflict; use a new task domain')
    else:
        atomic_bytes(output, rendered)
    return {'status':'incomplete', 'detail_status':'research_candidates_prepared', 'decision_scope':'research_only',
            'bundle_file':str(output), 'bundle_sha256':loop.digest(bundle), 'channel_report_sha256':report_sha,
            'template_sha256':template_sha, 'candidates':candidates, 'evidence_tasks':tasks,
            'coverage_complete':False, 'links_confirmed':False, 'downloads_scheduled':False,
            'limitations':['not unattended research or complete material event coverage; titles are not business claims; duplicate URLs retain separate aliases; retrieved_at unchanged']}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('channel-report','template-file','evidence-root','task-dir'):
        p.add_argument('--'+flag, required=True)
    a = p.parse_args(argv)
    try:
        result = prepare(a.channel_report, a.template_file, a.evidence_root, a.task_dir)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as exc:
        result = {'status':'failed', 'detail_status':'research_prepare_invalid_input', 'errors':[f'{type(exc).__name__}: {exc}']}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return exit_code_for(result['status'])


if __name__ == '__main__':
    raise SystemExit(main())
