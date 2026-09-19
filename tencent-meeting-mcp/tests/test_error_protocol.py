"""Exercise CLI and proxy with synthetic config, environment and HTTP responses."""
import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import Mock
from email.message import Message

import pytest

SCRIPTS = Path(__file__).parents[1] / 'scripts'


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('meeting_cli_test', SCRIPTS / 'tencent_meeting.py')
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    mcp_proxy = importlib.import_module("mcp_proxy")
    monkeypatch.setattr(cli.os, 'environ', {'TENCENT_MEETING_TOKEN': 'synthetic-test-value'})
    monkeypatch.setattr(cli, 'load_config', lambda: {'baseUrl': 'https://example.invalid/mcp', 'version': 'test'})
    monkeypatch.setattr(sys, 'argv', ['tencent_meeting.py', 'tools/call', '{"name":"fixture","arguments":{}}'])
    return cli, mcp_proxy


@pytest.mark.parametrize('response', [
    {'error': {'code': -32001, 'message': 'outer denied'}},
    {'result': {'error': {'code': 40301, 'message': 'inner denied'}}},
    {'result': {'isError': True, 'content': [{'type': 'text', 'text': '{"code":40901,"message":"tool denied"}'}]}},
])
def test_errors_preserved_and_nonzero_without_retry(modules, monkeypatch, capsys, response):
    cli, _ = modules
    proxy = Mock()
    proxy.request.return_value = response
    monkeypatch.setattr(cli, 'McpProxy', Mock(return_value=proxy))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0
    out = capsys.readouterr()
    assert json.loads(out.err) == response
    proxy.request.assert_called_once()


@pytest.mark.parametrize('response,expected', [
    ({'result': {'content': [{'type': 'text', 'text': 'known meeting'}]}}, 'known meeting'),
    ({'result': {'content': []}}, ''),
    ({'result': {'content': [{'type': 'text', 'text': '[]'}]}}, '[]'),
])
def test_success_and_empty_remain_success(modules, monkeypatch, capsys, response, expected):
    cli, _ = modules
    proxy = Mock()
    proxy.request.return_value = response
    monkeypatch.setattr(cli, 'McpProxy', Mock(return_value=proxy))
    cli.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == expected and not captured.err


def test_http_error_native_code_is_not_wrapped(modules, monkeypatch):
    _, proxy_module = modules
    error = urllib.error.HTTPError('https://example.invalid', 429, 'rate limited', Message(), None)
    request = Mock(side_effect=error)
    monkeypatch.setattr(proxy_module.urllib.request, 'urlopen', request)
    with pytest.raises(urllib.error.HTTPError) as exc:
        proxy_module.McpProxy('synthetic', 'https://example.invalid', 'test').request('tools/list')
    assert exc.value is error and exc.value.code == 429
    request.assert_called_once()


@pytest.mark.parametrize('body', [b'not JSON', b'[]'])
def test_invalid_response_is_not_no_data(modules, monkeypatch, capsys, body):
    cli, proxy_module = modules
    monkeypatch.setattr(proxy_module.urllib.request, 'urlopen', Mock(return_value=io.BytesIO(body)))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0
    output = capsys.readouterr()
    assert '响应错误' in output.out + output.err


@pytest.mark.parametrize('error', [
    urllib.error.HTTPError('https://example.invalid', 403, 'forbidden', Message(), None),
    urllib.error.URLError('synthetic connection refused'),
])
def test_cli_transport_failure_preserves_native_message(modules, monkeypatch, capsys, error):
    cli, proxy_module = modules
    request = Mock(side_effect=error)
    monkeypatch.setattr(proxy_module.urllib.request, 'urlopen', request)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code != 0
    output = capsys.readouterr()
    assert str(error) in output.out + output.err
    request.assert_called_once()


def test_list_rpc_error_nonzero(modules, monkeypatch, capsys):
    cli, _ = modules
    monkeypatch.setattr(sys, 'argv', ['tencent_meeting.py', 'tools/list'])
    response = {'error': {'code': -32600, 'message': 'invalid request'}}
    proxy = Mock()
    proxy.request.return_value = response
    monkeypatch.setattr(cli, 'McpProxy', Mock(return_value=proxy))
    with pytest.raises(SystemExit):
        cli.main()
    assert json.loads(capsys.readouterr().err) == response
    proxy.request.assert_called_once()
