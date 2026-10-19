"""Verify bounded artifact claims, not objective business truth or human identity."""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

import pia_research_loop as loop
from artifact_io import atomic_bytes
from management_claim_tracker import finite_number
from status_contract import exit_code_for


def utc(value, as_of=None):
    stamp = loop.timestamp(value)
    if stamp.utcoffset() != dt.timedelta(0) or stamp > (as_of or dt.datetime.now(dt.timezone.utc)):
        raise loop.LoopError('timestamp must be UTC and not future')
    return stamp


def pointer(document, locator):
    if not isinstance(locator, str) or not locator.startswith('/'):
        raise loop.LoopError('JSON Pointer must identify a non-root value')
    value = document
    for token in locator[1:].split('/'):
        if re.search(r'~(?![01])', token):
            raise loop.LoopError('invalid JSON Pointer escape')
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if re.fullmatch(r'0|[1-9][0-9]*', token) is None:
                raise loop.LoopError('invalid JSON Pointer array index')
            index = int(token)
            if index >= len(value):
                raise loop.LoopError('JSON Pointer index absent')
            value = value[index]
        elif isinstance(value, dict) and token in value:
            value = value[token]
        else:
            raise loop.LoopError('JSON Pointer target absent')
    return value


def nonblank(value):
    if not isinstance(value, str) or not value.strip():
        raise loop.LoopError('nonblank text required')
    return value


def check(input_file, evidence_root, output):
    source, root, out = Path(input_file).absolute(), Path(evidence_root).absolute(), Path(output).absolute()
    for p in (source, root, out):
        loop.no_links(p)
    if not root.is_dir() or out.resolve().is_relative_to(root.resolve()) or out.resolve() == source.resolve():
        raise loop.LoopError('output must be outside evidence and distinct from input')
    data, input_sha = loop.read_json(source)
    if not isinstance(data, dict) or set(data) != {'schema_version','as_of','assertions'} or data['schema_version'] != 'pia_artifact_assertions_v1':
        raise loop.LoopError('assertion envelope invalid')
    as_of = utc(data['as_of'])
    if not isinstance(data['assertions'], list) or not 1 <= len(data['assertions']) <= 200:
        raise loop.LoopError('assertion limit 1..200')
    results, seen, budget = [], set(), [0]
    for row in data['assertions']:
        base = {'assertion_id','artifact','content_sha256','kind','expected'}
        fields = {'json_pointer': {'pointer','bindings'}, 'text_lines':{'start_line','end_line'}}
        if not isinstance(row, dict) or row.get('kind') not in fields or set(row) != base | fields[row['kind']]:
            raise loop.LoopError('assertion fields invalid')
        identity = nonblank(row['assertion_id'])
        if identity in seen:
            raise loop.LoopError('duplicate assertion identity')
        seen.add(identity)
        if row['artifact'] is None or not isinstance(row['content_sha256'], str) or re.fullmatch('[a-fA-F0-9]{64}', row['content_sha256']) is None:
            raise loop.LoopError('explicit artifact/hash required')
        raw = loop.artifact(row, root, budget, return_bytes=True)
        if not isinstance(raw, bytes):
            raise loop.LoopError('verified artifact bytes required')
        expected = row['expected']
        if isinstance(expected, str):
            nonblank(expected)
        elif not finite_number(expected):
            raise loop.LoopError('expected must be nonblank text or finite nonboolean number')
        if row['kind'] == 'text_lines':
            if not isinstance(expected, str):
                raise loop.LoopError('text expected required')
            lines = raw.decode('utf-8').splitlines()
            start, end = row['start_line'], row['end_line']
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
                raise loop.LoopError('invalid 1-based text line range')
            actual = '\n'.join(lines[start-1:end])
        else:
            document = json.loads(raw.decode('utf-8'))
            actual = pointer(document, row['pointer'])
            if not (isinstance(actual, str) or finite_number(actual)) or type(actual) is bool:
                raise loop.LoopError('located value must be text or finite nonboolean number')
            bindings = row['bindings']
            if not isinstance(bindings, dict) or set(bindings) != {'unit','period','observed_at'}:
                raise loop.LoopError('explicit unit/period/observed_at bindings required')
            for name, binding in bindings.items():
                if not isinstance(binding, dict) or set(binding) != {'pointer','expected'}:
                    raise loop.LoopError('invalid metadata binding')
                bound = pointer(document, binding['pointer'])
                wanted = binding['expected']
                if name == 'unit':
                    nonblank(wanted)
                elif name == 'observed_at':
                    utc(wanted, as_of)
                    utc(bound, as_of)
                else:
                    if not isinstance(wanted, dict) or set(wanted) != {'start','end'}:
                        raise loop.LoopError('period must be explicit start/end dates')
                    start = dt.date.fromisoformat(wanted['start'])
                    end = dt.date.fromisoformat(wanted['end'])
                    if start > end or end > as_of.date():
                        raise loop.LoopError('reversed or future period')
                if bound != wanted:
                    raise loop.LoopError(f'{name} mismatch')
        if (isinstance(actual, str) != isinstance(expected, str)) or actual != expected:
            raise loop.LoopError('located claim value mismatch')
        results.append({'assertion_id':identity, 'artifact':row['artifact'], 'content_sha256':row['content_sha256'], 'status':'artifact_claim_match_verified'})
    result = {'status':'complete', 'detail_status':'artifact_claim_match_verified', 'input_sha256':input_sha,
              'as_of':data['as_of'], 'assertions':results, 'business_facts_authenticated':False,
              'human_identity_authenticated':False, 'decision_scope':'artifact_claim_consistency_only',
              'limitations':['no OCR, semantic truth, issuer provenance or reviewer identity authentication']}
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode()
    if out.exists():
        if out.read_bytes() != rendered:
            raise loop.LoopError('output conflict; use a new task result')
    else:
        atomic_bytes(out, rendered)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('input-file','evidence-root','output'):
        p.add_argument('--'+name, required=True)
    a = p.parse_args(argv)
    try:
        result = check(a.input_file, a.evidence_root, a.output)
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, IndexError) as exc:
        result = {'status':'failed', 'detail_status':'artifact_claim_check_failed', 'business_facts_authenticated':False,
                  'human_identity_authenticated':False, 'errors':[f'{type(exc).__name__}: {exc}']}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return exit_code_for(result['status'])


if __name__ == '__main__':
    raise SystemExit(main())
