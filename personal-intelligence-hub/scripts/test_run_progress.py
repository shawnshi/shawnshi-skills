from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

import run_contract as rc
import run_progress as progress
from test_article_broker_contract import new_run  # noqa: F401


def tree_hashes(root):
    return {str(p.relative_to(root)): rc.file_sha256(p) for p in root.rglob('*') if p.is_file()}


def test_resume_is_readonly_and_preserves_unmetered_budget(new_run):
    manifest, root, created = new_run
    before = tree_hashes(root)
    result = progress.inspect_run(manifest, now=created + timedelta(seconds=10))
    assert result['mode'] == 'read_only'
    assert result['next_action']['kind'] == 'host_state_required'
    assert result['next_action']['stage'] == 'supplemental'
    assert result['cost']['complete_run_cost_usd'] is None
    assert result['cost']['reported_cost_usd'] is None
    assert result['cost']['coverage'] == 'unmeasured'
    assert tree_hashes(root) == before


def test_semantic_prepare_uses_frozen_cli_without_creating_request(new_run):
    manifest, root, created = new_run
    rc.record_stage(manifest, 'supplemental', 'not_required', now=created)
    before = tree_hashes(root)
    value = progress.inspect_run(manifest, now=created + timedelta(seconds=10))
    action = value['next_action']
    assert action['kind'] == 'prepare_review'
    assert action['argv'][:4] == ['python', '-B', '-X', 'utf8']
    assert action['argv'][4] == rc.load_manifest(manifest)['bundle_snapshot']['execution_cli_path']
    assert action['argv'][5] == 'prepare-review'
    assert action['argv'][-2:] == ['--kind', 'semantic']
    assert tree_hashes(root) == before


def test_existing_request_is_not_rebuilt_or_relabelled_running(tmp_path):
    from test_run_daily_broker_entry import prepare_fixture

    prepared = prepare_fixture(tmp_path, 0, 2)
    manifest = prepared.manifest_path
    value = rc.load_manifest(manifest)
    root = Path(value['run_dir'])
    created = datetime.fromisoformat(value['created_at'])
    aggregate = root / 'supplement-skipped.json'
    aggregate.write_text('{"results":[]}', encoding='utf-8')
    rc.record_stage(manifest, 'supplemental', 'not_required', artifact_path=aggregate, now=created)
    path, request = rc.build_review_request(manifest, None, 'semantic', now=created)
    before = tree_hashes(root)
    result = progress.inspect_run(manifest, now=created + timedelta(seconds=30))
    assert result['next_action']['kind'] == 'handoff_existing_review'
    assert result['next_action']['requires_host_state'] is True
    assert result['next_action']['request_path'] == str(path.resolve())
    assert result['next_action']['helper'] == 'review_handoff.preflight'
    assert rc.load_manifest(manifest)['telemetry'] == json.loads(manifest.read_text(encoding='utf-8'))['telemetry']
    assert json.loads(path.read_text(encoding='utf-8'))['invocation_id'] == request['invocation_id']
    assert tree_hashes(root) == before


def test_failed_archive_is_not_retried_even_after_formal_commit(new_run):
    manifest, root, created = new_run
    for stage in ('supplemental', 'semantic_review', 'red_team'):
        rc.record_stage(manifest, stage, 'not_required', now=created)
    rc.record_stage(manifest, 'archive', 'failed', metadata={'formal_archive_committed': True}, now=created)
    before = tree_hashes(root)
    result = progress.inspect_run(manifest, now=created + timedelta(seconds=30))
    assert result['next_action']['kind'] == 'blocked'
    assert result['next_action']['stage'] == 'archive'
    assert 'argv' not in result['next_action']
    assert tree_hashes(root) == before


def test_tampered_registered_artifact_is_not_treated_as_ready(new_run):
    manifest, root, created = new_run
    request = root / 'request-input.json'
    request.write_text('{}', encoding='utf-8')
    rc.record_run_artifact(manifest, 'focus_config', request, now=created)
    request.write_text('{"changed":true}', encoding='utf-8')
    with pytest.raises(rc.RunContractError, match='artifact changed'):
        progress.inspect_run(manifest, now=created + timedelta(seconds=30))


@pytest.mark.parametrize('no_bytecode', [True, False])
def test_real_frozen_cli_observes_without_writes(new_run, no_bytecode):
    manifest, root, created = new_run
    before = tree_hashes(root)
    cli = rc.load_manifest(manifest)['bundle_snapshot']['execution_cli_path']
    import os
    env = dict(os.environ)
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    argv = [sys.executable, *(['-B'] if no_bytecode else []), '-X', 'utf8', cli, 'resume', '--manifest', str(manifest)]
    run = subprocess.run(argv, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)['next_action']['kind'] == 'host_state_required'
    assert tree_hashes(root) == before


def timing_manifest():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    stages = {key: {'status': 'pending'} for key in rc.STAGE_ORDER}
    for index, stage in enumerate(('baseline', 'supplemental', 'semantic_review', 'red_team')):
        stages[stage] = {'status': 'completed', 'recorded_at': (start + timedelta(seconds=index * 10)).isoformat()}
    return {'created_at': start.isoformat(), 'stages': stages, 'artifacts': {}}, start


def test_missing_start_is_unknown_not_idle_time():
    manifest, start = timing_manifest()
    result = progress.timing_projection(manifest, start + timedelta(seconds=100))
    archive = result['stages'][-1]
    assert archive['handoff_seconds'] is None
    assert archive['request_to_registration_seconds'] is None
    assert archive['unobserved_transition_seconds'] == 70


def test_handoff_and_registration_delay_are_separate():
    manifest, start = timing_manifest()
    manifest['artifacts']['semantic_review_request'] = {'recorded_at': (start + timedelta(seconds=12)).isoformat()}
    manifest['stages']['semantic_review']['metadata'] = {'request_to_receipt_seconds': 5, 'receipt_to_registration_seconds': 3}
    archive = manifest['stages']['archive']
    archive.update(status='completed', recorded_at=(start + timedelta(seconds=50)).isoformat(), metadata={'forge_started_at': (start + timedelta(seconds=42)).isoformat(), 'commit_started_at': (start + timedelta(seconds=48)).isoformat()})
    rows = progress.timing_projection(manifest, start + timedelta(seconds=60))['stages']
    assert rows[2]['handoff_seconds'] == 2
    assert rows[2]['request_to_receipt_seconds'] == 5
    assert rows[2]['receipt_to_registration_seconds'] == 3
    assert rows[-1]['handoff_seconds'] == 12
    assert rows[-1]['request_to_registration_seconds'] == 8
    assert rows[-1]['assembly_seconds'] == 6
    assert rows[-1]['commit_to_registration_seconds'] == 2
    assert rows[-1]['unobserved_transition_seconds'] is None


@pytest.mark.parametrize('bad', ['not-a-date', '2026-10-01T00:00:00'])
def test_malformed_timestamp_does_not_become_zero(bad):
    manifest, start = timing_manifest()
    manifest['created_at'] = bad
    with pytest.raises(rc.RunContractError, match='timestamp'):
        progress.timing_projection(manifest, start + timedelta(seconds=60))


def test_future_timestamp_does_not_become_zero():
    manifest, start = timing_manifest()
    with pytest.raises(rc.RunContractError, match='regressed'):
        progress.timing_projection(manifest, start - timedelta(seconds=1))


def test_partial_cost_and_held_broker_slot_are_honest(new_run):
    from test_article_broker_contract import request, telemetry

    path, _, created = new_run
    request(new_run)
    rc.record_execution_telemetry(path, telemetry(new_run), now=created)
    manifest = deepcopy(rc.load_manifest(path))
    original_held_tokens = manifest['telemetry']['reservations']['supplemental:tech']['tokens']
    manifest['telemetry']['reservations']['semantic_review:missing'] = {'status': 'held_unmetered', 'tokens': 1000, 'cost_usd': 0.3}
    before = deepcopy(manifest)
    result = progress.cost_projection(manifest)
    assert result['by_stage']['supplemental']['budget_tokens'] == 120
    assert result['by_stage']['supplemental']['reported_total_tokens'] == 120
    assert result['reported_cost_usd'] == 0.01
    assert result['coverage'] == 'partial'
    assert result['complete_run_cost_usd'] is None
    assert result['by_stage']['supplemental']['incomplete_invocations'] == ['supplemental:tech']
    assert result['held_reservation_keys'] == ['semantic_review:missing', 'supplemental:tech']
    assert result['missing_telemetry_keys'] == ['semantic_review:missing']
    assert result['budget_summary']['reserved_tokens'] == original_held_tokens + 1000
    assert manifest == before


@pytest.mark.parametrize('bad', [-1, float('nan'), True])
def test_invalid_timing_counter_is_not_silently_zero(bad):
    manifest, start = timing_manifest()
    manifest['stages']['semantic_review']['metadata'] = {'request_to_receipt_seconds': bad}
    with pytest.raises(rc.RunContractError, match='counter'):
        progress.timing_projection(manifest, start + timedelta(seconds=60))


def test_invalid_pending_timestamp_is_not_ignored():
    manifest, start = timing_manifest()
    manifest['stages']['archive']['recorded_at'] = 'malformed'
    with pytest.raises(rc.RunContractError, match='timestamp'):
        progress.timing_projection(manifest, start + timedelta(seconds=60))


def test_missing_frozen_cli_cannot_produce_action():
    manifest, _ = timing_manifest()
    manifest['stages']['semantic_review']['status'] = 'pending'
    with pytest.raises(rc.RunContractError, match='frozen execution CLI'):
        progress._next_action(manifest, Path('unused-manifest.json'))


@pytest.mark.parametrize('source', [False, True, 'mixed'])
def test_frozen_resume_review_and_archive_e2e(tmp_path, monkeypatch, source):
    from test_native_article_evidence import test_native_mocked_end_to_end_temporary_forge

    original_run = subprocess.run
    observed = []

    def checked_run(argv, **kwargs):
        args = list(argv)
        if '-c' in args and 'NATIVE_E2E_RECEIPT_SEAL_DATE_SEMANTIC_GATE_FORGE_PASS' in args[args.index('-c') + 1]:
            index = args.index('-c') + 1
            code = args[index]
            code = code.replace('core,semantic=assemble_and_finalize(review,dynamic)', '''core,semantic=assemble_and_finalize(review,dynamic)
from run_progress import inspect_run
import subprocess
before=rc.file_sha256(manifest)
action=inspect_run(manifest)['next_action']
assert action['kind']=='prepare_review' and action['stage']=='red_team'
assert rc.file_sha256(manifest)==before
prepared_red=subprocess.run(action['argv'],capture_output=True,text=True,encoding='utf-8',timeout=30)
assert prepared_red.returncode==0,prepared_red.stderr
red_path=Path(json.loads(prepared_red.stdout)['request_path'])''')
            code = code.replace("_,red=rc.build_review_request(manifest,core,'red_team',semantic_receipt_path=semantic)", 'red=rc.load_json(red_path,{})')
            code = code.replace('result=forge_briefing(manifest,core,news_dir=news,update_runtime_state=False)', '''before=rc.file_sha256(manifest)
action=inspect_run(manifest)['next_action']
assert action['kind']=='forge' and action['requires_archive_authorization']
assert action['argv'][4]==rc.load_manifest(manifest)['bundle_snapshot']['execution_cli_path']
assert action['argv'][action['argv'].index('--news-dir')+1]==str(news.resolve())
assert '--no-runtime-state' in action['argv']
assert rc.file_sha256(manifest)==before
committed=subprocess.run(action['argv'],capture_output=True,text=True,encoding='utf-8',timeout=30)
assert committed.returncode==0,committed.stderr
from types import SimpleNamespace
paths=json.loads(committed.stdout)
result=SimpleNamespace(json_path=Path(paths['json_path']))
finished=inspect_run(manifest)
assert finished['next_action']['kind']=='done'
assert finished['timing']['stages'][-1]['handoff_seconds'] is not None
assert finished['cost']['complete_run_cost_usd'] is None
print('FROZEN_RESUME_REVIEW_ARCHIVE_PASS')''')
            args[index] = code
            result = original_run(args, **kwargs)
            assert 'FROZEN_RESUME_REVIEW_ARCHIVE_PASS' in result.stdout, result.stdout + result.stderr
            observed.append(True)
            return result
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', checked_run)
    test_native_mocked_end_to_end_temporary_forge(tmp_path, monkeypatch, source)
    assert observed == [True]


@pytest.mark.parametrize('stage', ['semantic_review', 'red_team'])
def test_existing_request_preflight_references_are_real(stage):
    import inspect
    import review_handoff

    module, name = progress._HANDOFF_PREFLIGHTS[stage].split('.')
    assert module == 'review_handoff'
    helper = getattr(review_handoff, name)
    assert callable(helper)
    assert next(iter(inspect.signature(helper).parameters)) == 'request_path'


def test_incomplete_rollback_pending_archive_is_blocked(tmp_path, monkeypatch):
    import archive_transaction as transaction
    from test_run_daily_broker_entry import prepare_fixture

    prepared = prepare_fixture(tmp_path, 0, 2)
    path = prepared.manifest_path
    manifest = rc.load_manifest(path)
    news = Path(manifest['artifacts']['history_snapshot']['metadata']['news_dir'])
    report_date = manifest['report_date']
    run_id = manifest['run_id']
    rollback_calls = []

    def promote(source, destination):
        import os
        if Path(destination).suffix == '.md':
            raise OSError('controlled promotion failure')
        os.replace(source, destination)

    def incomplete_rollback(snapshots):
        rollback_calls.append(True)
        return ['controlled rollback failure']

    monkeypatch.setattr(transaction, '_rollback', incomplete_rollback)
    with pytest.raises(transaction.ArchiveTransactionError, match='rollback was incomplete'):
        transaction.commit_briefing_pair({'run_id': run_id, 'report_date': report_date}, news_dir=news,
            report_date=report_date, run_id=run_id, markdown='fixture', gate=lambda _: ([], []), replace_fn=promote)
    assert list(news.glob('.pih-stage-*'))
    assert rc.load_manifest(path)['stages']['archive']['status'] == 'pending'
    # Isolate the archive-routing component without persisting fabricated review receipts.
    # Full registered predecessors are exercised by the three frozen CLI E2Es above.
    for stage in ('supplemental', 'semantic_review', 'red_team'):
        manifest['stages'][stage] = {'status': 'completed'}
    before = tree_hashes(tmp_path)
    action = progress._next_action(manifest, path)
    assert action['kind'] == 'blocked'
    assert 'transaction residue' in action['reason']
    assert 'argv' not in action
    assert rollback_calls == [True]
    assert tree_hashes(tmp_path) == before


def test_target_change_without_journal_is_blocked(tmp_path):
    from test_run_daily_broker_entry import prepare_fixture

    prepared = prepare_fixture(tmp_path, 0, 2)
    path = prepared.manifest_path
    manifest = rc.load_manifest(path)
    metadata = manifest['artifacts']['history_snapshot']['metadata']
    news = Path(metadata['news_dir'])
    news.mkdir(parents=True, exist_ok=True)
    target = news / next(iter(metadata['archive_target_state']))
    target.write_text('controlled post-prepare change', encoding='utf-8')
    before = tree_hashes(tmp_path)
    _, reason = progress._archive_safety(manifest)
    assert 'changed since prepare' in reason
    assert tree_hashes(tmp_path) == before
