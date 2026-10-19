from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest

import bundle_pool as pool
import run_contract as rc
import run_research as research
from test_article_broker_contract import new_run, request  # noqa: F401


def hashes(root):
    return {str(p.relative_to(root)): rc.file_sha256(p) for p in root.rglob('*') if p.is_file()}


def test_pending_research_is_unknown_and_readonly(new_run):
    manifest, root, _ = new_run
    request(new_run)
    before = hashes(root)
    report = research.evaluate_run(manifest)
    assert report['aggregate_registered'] is False
    assert report['distinct_returned_candidates'] is None
    assert report['gaps'][0]['state'] == 'unregistered'
    assert report['gaps'][0]['candidates_returned'] is None
    assert report['feedback'][0]['kind'] == 'delivery_or_reconciliation_required'
    assert not report['automatic_policy_changes']
    assert hashes(root) == before


def test_tampered_research_receipt_is_error(new_run):
    manifest, _, _ = new_run
    path, _ = request(new_run)
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(rc.RunContractError):
        research.evaluate_run(manifest)


def test_catalog_preserves_duplicate_ids_without_execution_claim(new_run):
    path, root, now = new_run
    copied = root / 'same-id.json'
    value = rc.load_manifest(path)
    value['created_at'] = (now + timedelta(seconds=10)).isoformat()
    copied.write_text(json.dumps(value), encoding='utf-8')
    before = hashes(root)
    report = research.catalog([path, copied])
    assert len(report['rows']) == 2
    assert report['duplicate_run_ids'] == [value['run_id']]
    assert report['rows'][0]['manifest_path'] == str(copied.resolve())
    assert all(not row['completion_verified'] and not row['launch_permission'] for row in report['rows'])
    assert hashes(root) == before


def test_catalog_errors_are_not_no_data(new_run):
    path, root, _ = new_run
    bad = root / 'bad.json'
    bad.write_text('{', encoding='utf-8')
    report = research.catalog([path, bad, root / 'missing.json'])
    assert report['status'] == 'partial'
    assert len(report['rows']) == 1 and len(report['errors']) == 2


def test_catalog_unsupported_version_and_duplicates(new_run):
    path, root, _ = new_run
    value = rc.load_manifest(path)
    value['contract_version'] = 'unknown'
    bad = root / 'unknown.json'
    bad.write_text(json.dumps(value), encoding='utf-8')
    report = research.catalog([path, path, bad])
    assert len(report['rows']) == 1 and len(report['errors']) == 2


def test_real_frozen_evaluate_catalog_cli(new_run):
    path, root, _ = new_run
    request(new_run)
    before = hashes(root)
    cli = rc.load_manifest(path)['bundle_snapshot']['execution_cli_path']
    for command in ('evaluate', 'catalog'):
        run = subprocess.run([sys.executable, '-B', '-X', 'utf8', cli, command, '--manifest', str(path)], capture_output=True, encoding='utf-8', timeout=30)
        assert run.returncode == 0, run.stderr
        assert json.loads(run.stdout)['mode'] == 'read_only'
    assert hashes(root) == before


def test_pool_reuses_one_archive_and_restores_independent_bytes(new_run, tmp_path):
    path, _, _ = new_run
    source = Path(rc.load_manifest(path)['skill_path']).parent
    before = hashes(source)
    first = pool.pack_bundle(source, tmp_path / 'pool')
    second = pool.pack_bundle(source, tmp_path / 'pool')
    assert not first['reused'] and second['reused']
    assert first['archive_path'] == second['archive_path']
    assert len(list((tmp_path / 'pool').glob('*.zip'))) == 1
    assert first['archive_bytes'] < first['source_bytes']
    restored = tmp_path / 'restored'
    report = pool.restore_bundle(first['archive_path'], restored)
    assert report['independent_copy'] and not report['execution_performed']
    restored_root = Path(report['destination'])
    assert restored_root == restored / 'personal-intelligence-hub'
    assert hashes(restored_root) == before
    changed = restored_root / 'SKILL.md'
    changed.write_text('controlled local edit', encoding='utf-8')
    assert hashes(source) == before
    assert pool.verify_archive(first['archive_path'])['bundle_id'] == first['bundle_id']


def test_pool_corrupt_object_preserved(new_run, tmp_path):
    path, _, _ = new_run
    source = Path(rc.load_manifest(path)['skill_path']).parent
    packed = pool.pack_bundle(source, tmp_path / 'pool')
    archive = Path(packed['archive_path'])
    archive.write_bytes(b'corrupt')
    with pytest.raises((pool.BundlePoolError, zipfile.BadZipFile)):
        pool.pack_bundle(source, tmp_path / 'pool')
    assert archive.read_bytes() == b'corrupt'


def test_restore_existing_destination_preserved(new_run, tmp_path):
    path, _, _ = new_run
    packed = pool.pack_bundle(Path(rc.load_manifest(path)['skill_path']).parent, tmp_path / 'pool')
    destination = tmp_path / 'existing'
    destination.mkdir()
    marker = destination / 'user.txt'
    marker.write_text('keep', encoding='utf-8')
    with pytest.raises(pool.BundlePoolError, match='exists'):
        pool.restore_bundle(packed['archive_path'], destination)
    assert marker.read_text(encoding='utf-8') == 'keep'


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a\\b', 'C:/escape', './a', 'NUL', 'dir/CON.txt', 'a.', 'a '])
def test_archive_unsafe_path_rejected_before_restore(tmp_path, name):
    archive = tmp_path / 'malicious.zip'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr(name, 'bad')
        out.writestr(pool.META, '{}')
    with pytest.raises(pool.BundlePoolError):
        pool.restore_bundle(archive, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


def test_archive_symlink_duplicate_and_size_limits(tmp_path):
    for kind in ('symlink', 'duplicate', 'oversize'):
        path = tmp_path / f'{kind}.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            info = zipfile.ZipInfo('entry')
            info.external_attr = ((stat.S_IFLNK | 0o777) if kind == 'symlink' else (stat.S_IFREG | 0o600)) << 16
            archive.writestr(info, b'x' * (pool.MAX_FILE_BYTES + 1 if kind == 'oversize' else 1))
            archive.writestr(pool.META, '{}')
            if kind == 'duplicate':
                with pytest.warns(UserWarning):
                    archive.writestr('entry', 'duplicate')
        with pytest.raises(pool.BundlePoolError):
            pool.verify_archive(path)


def test_pool_real_cli_and_bad_archive_exit(new_run, tmp_path):
    path, _, _ = new_run
    source = Path(rc.load_manifest(path)['skill_path']).parent
    script = source / 'scripts' / 'bundle_pool.py'
    run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(script), 'pack', '--source-root', str(source), '--pool-dir', str(tmp_path / 'pool')], capture_output=True, encoding='utf-8', timeout=30)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    verify = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(script), 'verify', '--archive', data['archive_path']], capture_output=True, encoding='utf-8', timeout=30)
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)['bundle_id'] == data['bundle_id']
    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'bad')
    failed = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(script), 'verify', '--archive', str(bad)], capture_output=True, encoding='utf-8', timeout=30)
    assert failed.returncode != 0 and failed.stderr and not failed.stdout


def test_selection_matches_candidate_version_not_only_url(new_run, monkeypatch):
    manifest_path, root, _ = new_run
    manifest = rc.load_manifest(manifest_path)
    url = 'https://example.org/one-release'
    a = {'url': url, 'title': 'version A', 'candidate_id': rc.candidate_ref(url)}
    b = {**a, 'title': 'version B'}
    for candidate in (a, b):
        candidate['candidate_object_sha256'] = rc.candidate_object_hash(candidate)
    assert a['candidate_object_sha256'] != b['candidate_object_sha256']

    def registered(filename, payload):
        path = root / filename
        path.write_text(json.dumps(payload), encoding='utf-8')
        return {'artifact_path': str(path), 'artifact_sha256': rc.file_sha256(path)}

    request_record = registered('counter-request.json', {'gaps': [{'gap_id': 'a', 'lane': 'technology'}, {'gap_id': 'b', 'lane': 'technology'}]})
    manifest['artifacts']['supplement_request'] = request_record
    results = [{'gap_id': name, 'status': 'completed', 'candidates': [candidate], 'coverage': {}} for name, candidate in (('a', a), ('b', b))]
    aggregate = {'run_id': manifest['run_id'], 'request_sha256': request_record['artifact_sha256'], 'results': results}
    manifest['stages']['supplemental'].update(registered('counter-results.json', aggregate), status='completed')
    receipt = {'run_id': manifest['run_id'], 'review_kind': 'semantic', 'lineage_bindings': [{'inputs': [{'candidate_ref': a['candidate_id'], 'candidate_object_sha256': a['candidate_object_sha256']}]}]}
    manifest['stages']['semantic_review'].update(registered('counter-semantic.json', receipt), status='completed')
    # Isolate the counter oracle; real artifact byte verification remains enabled.
    monkeypatch.setattr(rc, 'load_manifest', lambda path: deepcopy(manifest))
    report = research.evaluate_run(manifest_path)
    assert [gap['selected_candidates'] for gap in report['gaps']] == [1, 0]
    assert report['distinct_returned_candidates'] == 1


def test_registered_runtime_file_cannot_enter_source_pool(new_run, tmp_path):
    manifest, _, _ = new_run
    source = Path(rc.load_manifest(manifest)['skill_path']).parent
    runtime = source / 'runs' / 'example' / 'run.json'
    runtime.parent.mkdir(parents=True)
    runtime.write_text('{"private":"not-a-source"}', encoding='utf-8')
    resource_path = source / 'resource-manifest.json'
    resource = json.loads(resource_path.read_text(encoding='utf-8'))
    resource['resource_file_hashes'].append({'path': 'runs/example/run.json', 'sha256': rc._canonical_content_sha256(runtime)})
    resource_path.write_text(json.dumps(resource), encoding='utf-8')
    with pytest.raises(pool.BundlePoolError, match='static source layout'):
        pool.pack_bundle(source, tmp_path / 'pool')
    assert not (tmp_path / 'pool').exists()


@pytest.mark.parametrize('source', [False, True, 'mixed'])
def test_research_catalog_pool_frozen_e2e(tmp_path, monkeypatch, source):
    from test_native_article_evidence import test_native_mocked_end_to_end_temporary_forge

    original = subprocess.run
    observed = []

    def checked(argv, **kwargs):
        args = list(argv)
        if '-c' in args and 'NATIVE_E2E_RECEIPT_SEAL_DATE_SEMANTIC_GATE_FORGE_PASS' in args[args.index('-c') + 1]:
            position = args.index('-c') + 1
            args[position] = args[position].replace("print('NATIVE_E2E_RECEIPT_SEAL_DATE_SEMANTIC_GATE_FORGE_PASS')", '''from run_research import evaluate_run,catalog
from bundle_pool import pack_bundle,restore_bundle
before=rc.file_sha256(manifest)
evaluation=evaluate_run(manifest)
assert evaluation['aggregate_registered']
assert evaluation['distinct_returned_candidates']==expected
assert sum(g['selected_candidates'] for g in evaluation['gaps'])==expected
assert evaluation['automatic_policy_changes'] is False
assert evaluation['source_clock_extension'] is False
index=catalog([manifest])
assert index['rows'][0]['recorded_stage_statuses']['archive']=='completed'
assert index['rows'][0]['completion_verified'] is False
assert rc.file_sha256(manifest)==before
root=Path(m['skill_path']).parent
packed=pack_bundle(root,news.parent/'code-pool')
assert pack_bundle(root,news.parent/'code-pool')['reused']
restored=restore_bundle(packed['archive_path'],news.parent/'code-copy')
assert restored['independent_copy'] and not restored['execution_performed']
assert rc.file_sha256(manifest)==before
print('PHASE3_EVALUATE_CATALOG_POOL_PASS')
print('NATIVE_E2E_RECEIPT_SEAL_DATE_SEMANTIC_GATE_FORGE_PASS')''')
            result = original(args, **kwargs)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'PHASE3_EVALUATE_CATALOG_POOL_PASS' in result.stdout
            observed.append(True)
            return result
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', checked)
    test_native_mocked_end_to_end_temporary_forge(tmp_path, monkeypatch, source)
    assert observed == [True]
