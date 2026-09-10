"""Isolated size boundaries only: no run creation, frozen bundles or recovery tests."""
import base64
import hashlib
import io
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import run_contract as rc
import supplement_agent as sa

MAX = rc.MAX_PARENT_DRAFT_BYTES


def padded(size):
    return b'{}' + b' ' * (size - 2)


def bound(monkeypatch, tmp_path):
    draft = tmp_path / 'draft.json'
    now = datetime.now(timezone.utc).isoformat()
    request = {'article_broker_version': 3, 'run_id': 'size-unit'}
    packet = {'finalization': {'parent_receipt_version': 1, 'grace_seconds': 300},
              'output_paths': {'draft': str(draft)}, 'run_manifest_path': 'mock-manifest'}
    monkeypatch.setattr(sa, '_load_bound_packet', Mock(return_value=(None, request, packet, {}, {}, {})))
    monkeypatch.setattr(sa, 'file_sha256', Mock(return_value='request-sha'))
    manifest = {}
    monkeypatch.setattr(sa, 'locked_manifest', Mock(return_value=nullcontext((manifest, 'sha'))))
    guard = Mock()
    monkeypatch.setattr(sa, '_guard_parent_finalization', guard)
    commit = Mock()
    materialize = Mock()
    monkeypatch.setattr(sa, 'commit_manifest', commit)
    monkeypatch.setattr(sa, '_materialize_parent_draft', materialize)
    return draft, now, request, packet, manifest, commit, materialize


def test_exact_1m_read_decode_and_materialize_preserve_bytes(tmp_path):
    raw = padded(MAX)
    path = tmp_path / 'draft'
    path.write_bytes(raw)
    assert rc._read_parent_draft_bytes(path) == raw
    encoded = base64.b64encode(raw).decode('ascii')
    assert len(encoded) == 1398104
    assert sa._decode_parent_draft(encoded) == raw
    sa._materialize_parent_draft(path, raw)
    assert path.read_bytes() == raw


def test_1m_plus_1_stat_rejects_before_open(tmp_path, monkeypatch):
    path = tmp_path / 'draft'
    raw = padded(MAX + 1)
    path.write_bytes(raw)
    with monkeypatch.context() as patch:
        opened = Mock(side_effect=AssertionError('must not open'))
        patch.setattr(Path, 'open', opened)
        with pytest.raises(rc.RunContractError, match='1048576 bytes'):
            rc._read_parent_draft_bytes(path)
        opened.assert_not_called()
    assert path.read_bytes() == raw


def test_race_growth_read_is_bounded(monkeypatch):
    stream = Mock(wraps=io.BytesIO(padded(MAX + 100)))
    opened = Mock(return_value=nullcontext(stream))
    monkeypatch.setattr(Path, 'stat', Mock(return_value=SimpleNamespace(st_size=MAX)))
    monkeypatch.setattr(Path, 'open', opened)
    with pytest.raises(rc.RunContractError, match='1048576 bytes'):
        rc._read_parent_draft_bytes(Path('growing'))
    opened.assert_called_once_with('rb')
    stream.read.assert_called_once_with(MAX + 1)


@pytest.mark.parametrize('encoded', ['A' * (1398104 + 1), 123, None, b'e30='],
                         ids=['encoded-limit-plus-one', 'integer', 'null', 'bytes'])
def test_encoded_limit_and_type_before_decode(encoded, monkeypatch):
    decode = Mock(side_effect=AssertionError('must not decode'))
    monkeypatch.setattr(sa.base64, 'b64decode', decode)
    with pytest.raises(rc.RunContractError):
        sa._decode_parent_draft(encoded)
    decode.assert_not_called()


@pytest.mark.parametrize('encoded', ['!!!!', 'e30', 'é==='])
def test_invalid_base64_is_typed_rejection(encoded):
    with pytest.raises(rc.RunContractError, match='payload invalid'):
        sa._decode_parent_draft(encoded)


@pytest.mark.parametrize('extra', [1, 2])
def test_exact_encoded_max_decode_overshoot_before_parse(tmp_path, monkeypatch, extra):
    _, now, request, packet, _, _, _ = bound(monkeypatch, tmp_path)
    encoded = base64.b64encode(padded(MAX + extra)).decode('ascii')
    assert len(encoded) == 1398104
    receipt = {'contract_version': 'parent-supplement-finalization/1.0',
               'parent_attestation': 'validated_within_source_grace',
               'run_id': request['run_id'], 'request_sha256': 'request-sha', 'gap_id': 'tech',
               'packet_sha256': hashlib.sha256(rc.canonical_json_bytes(packet)).hexdigest(),
               'completed_at': now, 'final_draft_base64': encoded}
    loads = Mock(side_effect=AssertionError('must not parse'))
    monkeypatch.setattr(sa.json, 'loads', loads)
    with pytest.raises(rc.RunContractError, match='1048576 bytes'):
        sa._validate_parent_receipt('request', request, packet, 'tech', receipt)
    loads.assert_not_called()


def test_oversized_source_before_parse_encode_commit_write(tmp_path, monkeypatch):
    path, _, _, _, manifest, commit, materialize = bound(monkeypatch, tmp_path)
    raw = padded(MAX + 1)
    path.write_bytes(raw)
    loads, encode = Mock(), Mock()
    monkeypatch.setattr(sa.json, 'loads', loads)
    monkeypatch.setattr(sa.base64, 'b64encode', encode)
    with pytest.raises(rc.RunContractError, match='1048576 bytes'):
        sa._finalize_with_receipt('request', 'tech')
    for mock in (loads, encode, commit, materialize):
        mock.assert_not_called()
    assert manifest == {} and path.read_bytes() == raw


def test_generated_oversize_before_encode_commit_materialize(tmp_path, monkeypatch):
    path, now, _, _, manifest, commit, materialize = bound(monkeypatch, tmp_path)
    path.write_bytes(b'{}')
    result = {'completed_at': now, 'broker_evidence_sha256': 'proof', 'padding': '界' * (MAX // 3)}
    monkeypatch.setattr(sa, 'assemble_result', Mock(return_value=(path, result)))
    encode = Mock()
    monkeypatch.setattr(sa.base64, 'b64encode', encode)
    with pytest.raises(rc.RunContractError, match='1048576 bytes'):
        sa._finalize_with_receipt('request', 'tech')
    for mock in (encode, commit, materialize):
        mock.assert_not_called()
    assert manifest == {} and path.read_bytes() == b'{}'


def test_exact_max_assembled_journal_preserves_padding_and_digest(tmp_path, monkeypatch):
    path, now, _, _, manifest, commit, materialize = bound(monkeypatch, tmp_path)
    result = {'contract_version': 'supplement-result/1.0', 'completed_at': now,
              'broker_evidence_sha256': 'proof'}
    prefix = json.dumps(result).encode()
    raw = prefix + b' ' * (MAX - len(prefix))
    path.write_bytes(raw)
    monkeypatch.setattr(sa, 'assemble_result', Mock(return_value=(path, result)))
    assert sa._finalize_with_receipt('request', 'tech') == (path, 'already_assembled')
    receipt = manifest['parent_supplement_finalizations']['tech']
    assert base64.b64decode(receipt['final_draft_base64'], validate=True) == raw
    assert receipt['final_draft_sha256'] == hashlib.sha256(raw).hexdigest()
    commit.assert_called_once()
    materialize.assert_called_once_with(path, raw)


@pytest.mark.parametrize('raw', [padded(MAX + 1), 'not bytes'],
                         ids=['raw-limit-plus-one', 'string'])
def test_materialize_rejects_before_tempfile_or_replace(tmp_path, monkeypatch, raw):
    temporary, replace = Mock(), Mock()
    monkeypatch.setattr(sa.tempfile, 'NamedTemporaryFile', temporary)
    monkeypatch.setattr(sa, '_replace_with_retry', replace)
    with pytest.raises(rc.RunContractError):
        sa._materialize_parent_draft(tmp_path / 'draft', raw)
    temporary.assert_not_called()
    replace.assert_not_called()


def test_multibyte_byte_limit_not_character_limit(tmp_path):
    text = json.dumps({'text': '界' * (MAX // 3)}, ensure_ascii=False)
    assert len(text) < MAX < len(text.encode('utf8'))
    path = tmp_path / 'draft'
    path.write_bytes(text.encode('utf8'))
    with pytest.raises(rc.RunContractError, match='1048576 bytes'):
        rc._read_parent_draft_bytes(path)
    assert path.read_bytes() == text.encode('utf8')
