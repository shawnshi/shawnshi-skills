"""Ownership regressions ported unchanged in assertions from the preserved fail-first probes.
Semantic boundary: reuse installed test_semantic_agent._assess, mocking only bound
artifact loading/history. Candidate hashes, assessment and dispositions are real.
Date-invalid means existing metadata is unknown, NOT authenticated body evidence.
Gate boundary: installed cloned_v14_payload plus mocked manifest/request/registered
lineage loaders; real validate_review_receipt, access/hash/evidence checks. This is
not an end-to-end parent registration/envelope test. No future API is called.
"""
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import run_contract as rc
import test_semantic_agent as fixtures
from test_contract_fixtures import cloned_v14_payload

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ['TEMP']) / 'date-ownership-probes'
SCRATCH.mkdir(exist_ok=True)


def hashed(c):
    c['candidate_object_sha256'] = rc.candidate_object_hash(c)
    return c


def candidate(name, invalid=False, owned=False, final=None):
    c = fixtures._candidate('https://example.org/' + name)
    if invalid:
        c['published_at_source'] = 'unknown'
    if owned:
        c['access_check'] = access(c, final)
    return hashed(c)


def access(c, final=None):
    a = fixtures._access(c['url'])
    if final:
        a['final_url'] = final['url']
    return a


def lane(candidates=(), logs=(), rejected=(), failure=None):
    return {'gap_id': 'fixture-lane', 'failure_kind': failure,
            'candidates': list(candidates), 'access_log': list(logs),
            'bound_candidate_decisions': [
                {'candidate_id': c['candidate_id'], 'decision': decision,
                 'reason': 'Existing metadata disposition fixture'}
                for decision, records in [('registered', candidates), ('date_disqualified', rejected)]
                for c in records]}


def assess(label, pool, results):
    eligible, dispositions = fixtures.SemanticAgentCandidateTests()._assess(
        {'items': pool}, {'results': results})
    observation = {'case': label, 'pool': pool, 'results': results,
                   'eligible': eligible, 'dispositions': dispositions}
    (SCRATCH / (label + '.json')).write_text(json.dumps(observation, indent=2), encoding='utf-8')
    print(json.dumps({'case': label, 'eligible_urls': [c['url'] for c in eligible],
                      'dispositions': dispositions}))
    return {c['url'] for c in eligible}


def test_A_valid_B_invalid_same_lane():
    a, b = candidate('A', owned=True), candidate('B', invalid=True)
    assert assess('A_valid_B_invalid', [b], [lane([a], [access(a), access(b)], [b], 'published_at_conflict')]) == {a['url']}


def test_B_invalid_redirect_C_bare_no_grant():
    b, c = candidate('B', invalid=True), candidate('C')
    assert assess('B_invalid_redirect_C', [b, c], [lane(logs=[access(b, c)], rejected=[b], failure='published_at_conflict')]) == set()


def test_B_valid_redirect_C_no_alias():
    c = candidate('C')
    b = candidate('B', owned=True, final=c)
    assert assess('B_valid_redirect_C', [c], [lane([b], [b['access_check']])]) == {b['url']}


def test_C_direct_owned_candidate_independent_of_B_rejection():
    b, c = candidate('B', invalid=True), candidate('C', owned=True)
    assert assess('C_direct_independent', [b], [lane(logs=[access(b, c)], rejected=[b], failure='published_at_conflict'), lane([c], [access(c)])]) == {c['url']}


def test_C_direct_owned_candidate_control():
    c = candidate('C', owned=True)
    assert assess('C_direct_control', [], [lane([c], [access(c)])]) == {c['url']}


def test_source_access_does_not_mask_B_date_rejection():
    a, b, d = candidate('A', owned=True), candidate('B', invalid=True), candidate('blocked')
    blocked = {**access(d), 'status': 'blocked', 'http_status': 403,
               'failure_class': 'permanent', 'error_code': 'HTTP_403'}
    assert assess('source_access_masks_date', [b], [lane([a], [access(a), access(b), blocked], [b], 'source_access')]) == {a['url']}


def test_rejected_input_repackaged_different_hash_not_resurrected():
    b = candidate('B', invalid=True)
    copied = deepcopy(b)
    copied['retrieved_at'] = '2026-08-31T02:00:00+00:00'
    copied['access_check'] = access(b)
    hashed(copied)
    assert b['candidate_object_sha256'] != copied['candidate_object_sha256']
    # Source lineage is conceptual here: copied object changes only transport/time.
    # Current records have no parent-generated source edge, so this is a consumer
    # boundary defect probe, not proof parent registration accepts this candidate.
    assert assess('rejected_copy_new_hash', [b], [lane(logs=[access(b)], rejected=[b], failure='source_access'), lane([copied], [access(copied)])]) == set()


def test_same_origin_conflicting_metadata_no_success_precedence():
    b = candidate('B', invalid=True)
    enriched = candidate('B', owned=True)
    assert assess('same_origin_conflict', [b], [lane(logs=[access(b)], rejected=[b], failure='source_access'), lane([enriched], [access(enriched)])]) == set()


def test_legacy_pool_plus_URL_access_no_positive_ownership():
    b = candidate('B')
    old = {'failure_kind': None, 'access_log': [access(b)], 'candidates': []}
    assert assess('legacy_URL_only', [b], [old]) == set()


def gate_probe(mode):
    refined = cloned_v14_payload()
    item = refined['top_10'][0]
    c = {k: deepcopy(item[k]) for k in ('url', 'title', 'source', 'source_type', 'published_at', 'published_at_source')}
    c['candidate_id'] = item['candidate_refs'][0]
    if mode not in {'missing_owned_access', 'borrowed_same_url_version'}:
        c['access_check'] = deepcopy(item['access_check'])
        if mode == 'wrong_owned_access':
            c['access_check']['checked_at'] = '2026-08-10T09:01:00+08:00'
    hashed(c)
    reference, object_hash = c['candidate_id'], c['candidate_object_sha256']
    lineage = {reference: {'object_hashes': [object_hash], 'objects': {object_hash: c}}}
    inputs = [{'candidate_ref': reference, 'candidate_object_sha256': object_hash}]
    logs = [item['access_check']]
    if mode == 'borrowed_same_url_version':
        other = hashed({**c, 'access_check': deepcopy(item['access_check'])})
        lineage[reference]['objects'][other['candidate_object_sha256']] = other
        lineage[reference]['object_hashes'].append(other['candidate_object_sha256'])
    if mode == 'borrowed_auxiliary':
        other = hashed({**c, 'url': 'https://independent.example/aux', 'source': 'Independent',
                        'candidate_id': rc.candidate_ref('https://independent.example/aux')})
        other.pop('access_check')
        hashed(other)
        ref, h = other['candidate_id'], other['candidate_object_sha256']
        lineage[ref] = {'objects': {h: other}, 'object_hashes': [h]}
        item['candidate_refs'].append(ref)
        item['corroboration_status'] = 'multi_independent'
        inputs.append({'candidate_ref': ref, 'candidate_object_sha256': h})
        logs.append({**item['access_check'], 'requested_url': other['url'], 'final_url': other['url']})
    refined_path = SCRATCH / ('gate-' + mode + '.json')
    refined_path.write_text(json.dumps(refined), encoding='utf-8')
    manifest = {'run_id': refined['run_id'], 'stages': {'baseline': {'artifact_sha256': 'a'*64}}}
    request = {'review_mode': 'registered_evidence_batch', 'max_turns': 2,
               'reviewer_kind': 'semantic_model', 'reviewer_id': 'fixture-reviewer',
               'invocation_id': 'fixture-invocation', 'challenge': 'fixture-challenge'}
    receipt = {**{k: request[k] for k in ('reviewer_kind', 'reviewer_id', 'invocation_id', 'challenge')},
               'contract_version': 'review-receipt/1.0', 'run_id': manifest['run_id'],
               'review_kind': 'semantic', 'status': 'passed', 'request_sha256': 'c'*64,
               'baseline_sha256': 'a'*64, 'input_bundle_sha256': 'd'*64,
               'output_sha256': rc.file_sha256(refined_path),
               'access_log': logs, 'reviewed_item_hashes': [rc.item_hash(item)],
               'lineage_bindings': [{'output_item_sha256': rc.item_hash(item), 'inputs': inputs}],
               'data_provenance': {'input_bundle_sha256': 'd'*64,
                   'access_log_sha256': hashlib.sha256(rc.canonical_json_bytes(logs)).hexdigest()},
               'turns_used': 1, 'halt_condition_met': True, 'completed_at': refined['generated_at']}
    with (patch.object(rc, 'load_manifest', return_value=manifest),
          patch.object(rc, '_registered_review_request', return_value=(request, 'c'*64)),
          patch.object(rc, 'review_input_bundle_sha256', return_value='d'*64),
          patch.object(rc, 'registered_candidate_lineage', return_value=lineage)):
        rc.validate_review_receipt(receipt, SCRATCH / 'mock-manifest.json', refined_path, expected_kind='semantic')
    print('REAL_GATE_ACCEPTED ' + mode)


def test_final_gate_missing_candidate_access_must_not_borrow_receipt():
    with pytest.raises(rc.RunContractError):
        gate_probe('missing_owned_access')


def test_final_gate_exact_owned_access_control():
    gate_probe('exact_owned_access')


def test_final_gate_wrong_owned_access_control():
    with pytest.raises(rc.RunContractError, match='access_check does not match exact bound candidate'):
        gate_probe('wrong_owned_access')


@pytest.mark.parametrize('mode', ['borrowed_same_url_version', 'borrowed_auxiliary'])
def test_final_gate_rejects_borrowed_versions_and_every_auxiliary(mode):
    with pytest.raises(rc.RunContractError, match='owned date/access'):
        gate_probe(mode)
