"""Synthetic files; every converter subprocess is mocked."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def converter(monkeypatch):
    spec = importlib.util.spec_from_file_location('converter_test', Path(__file__).parents[1] / 'scripts/converter.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os, 'environ', {})
    return module


def ebook_mock(monkeypatch, module, text=None, failure=None):
    def run(command, **kwargs):
        if '--version' in command:
            return subprocess.CompletedProcess(command, 0)
        if failure:
            raise failure
        assert text is not None
        Path(command[2]).write_text(text, encoding='utf-8')
        return subprocess.CompletedProcess(command, 0, '', '')
    mocked = Mock(side_effect=run)
    monkeypatch.setattr(module.subprocess, 'run', mocked)
    return mocked


@pytest.mark.parametrize('save', [False, True])
def test_short_epub_is_retained_in_full(converter, monkeypatch, tmp_path, save):
    source = tmp_path / 'short.epub'
    source.write_bytes(b'synthetic EPUB fixture')
    text = '# Short book\n\n' + 'A small but legitimate paragraph. ' * 5
    ebook_mock(monkeypatch, converter, text)
    output = tmp_path / 'result.md' if save else None
    result = converter.convert_file(str(source), str(output) if output else None)
    assert result['status'] == 'success' and result['completeness'] == 'full'
    assert (output.read_text(encoding='utf-8') if output else result['output']) == text
    assert source.read_bytes() == b'synthetic EPUB fixture'
    assert 'Scanned Image Book Detected' not in str(result)


def test_empty_extraction_is_error(converter, monkeypatch, tmp_path):
    source = tmp_path / 'empty.epub'
    source.touch()
    ebook_mock(monkeypatch, converter, '  ')
    result = converter.convert_file(str(source))
    assert result['status'] == 'error' and result['completeness'] == 'error'
    assert result['warnings'] and 'OCR' in str(result['warnings'])


def test_native_calibre_failure_preserved(converter, monkeypatch, tmp_path):
    source = tmp_path / 'broken.epub'
    source.touch()
    error = subprocess.CalledProcessError(17, ['ebook-convert'], stderr='native conversion failure')
    ebook_mock(monkeypatch, converter, failure=error)
    result = converter.convert_file(str(source))
    assert result['status'] == 'error' and result['returncode'] == 17
    assert 'native conversion failure' in result['message']


def test_truncation_is_partial(converter, monkeypatch, tmp_path):
    source = tmp_path / 'long.docx'
    source.touch()
    text = 'abcdef' * 20
    monkeypatch.setattr(converter, 'MAX_CHARS', 40)
    monkeypatch.setattr(converter, 'check_markitdown', lambda: True)
    monkeypatch.setattr(converter.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 0, text, '')))
    result = converter.convert_file(str(source))
    assert result['status'] == 'success' and result['completeness'] == 'partial'
    assert result['output'].endswith(text[:40]) and result['warnings']


def test_cli_prints_partial_warning_separately(converter, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['converter.py', 'synthetic.docx'])
    monkeypatch.setattr(converter, 'convert_file', lambda *args: {'status': 'success', 'completeness': 'partial', 'output': 'kept text', 'warnings': ['truncated fixture']})
    converter.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == 'kept text'
    assert 'truncated fixture' in captured.err


def test_partial_calibre_failure_keeps_text_and_nonzero(converter, monkeypatch, tmp_path, capsys):
    source = tmp_path / 'partial.epub'
    source.touch()
    destination = tmp_path / 'not-written.md'
    text = '# Recovered paragraph'
    def run(command, **kwargs):
        if '--version' in command:
            return subprocess.CompletedProcess(command, 0)
        Path(command[2]).write_text(text, encoding='utf-8')
        raise subprocess.CalledProcessError(23, command, stderr='bad object at page 2')
    monkeypatch.setattr(converter.subprocess, 'run', Mock(side_effect=run))
    result = converter.convert_file(str(source), str(destination))
    assert result['status'] == 'error' and result['completeness'] == 'partial'
    assert result['output'] == text and result['returncode'] == 23
    assert not destination.exists()
    monkeypatch.setattr(sys, 'argv', ['converter.py', str(source)])
    with pytest.raises(SystemExit) as exc:
        converter.main()
    assert exc.value.code != 0
    output = capsys.readouterr()
    assert text in output.out and 'bad object at page 2' in output.err


@pytest.mark.parametrize('version', [False, True])
def test_markitdown_native_failure(converter, monkeypatch, tmp_path, version):
    source = tmp_path / 'bad.docx'
    source.touch()
    def run(command, **kwargs):
        if '--version' in command and not version:
            return subprocess.CompletedProcess(command, 0)
        raise subprocess.CalledProcessError(19, command, stderr='native tool failed')
    monkeypatch.setattr(converter.subprocess, 'run', Mock(side_effect=run))
    result = converter.convert_file(str(source), str(tmp_path / 'output.md'))
    assert result['status'] == 'error' and result['returncode'] == 19
    assert 'native tool failed' in result['message']


@pytest.mark.parametrize('failure', ['missing_parent', 'permission', 'write'])
def test_save_failure_returns_extracted_text(converter, monkeypatch, tmp_path, capsys, failure):
    from unittest.mock import MagicMock
    source = tmp_path / 'short.epub'
    source.write_bytes(b'synthetic short EPUB')
    destination = tmp_path / 'missing' / 'output.md'
    text = '# Short book' + chr(10) * 2 + 'Retain all extracted text.'
    ebook_mock(monkeypatch, converter, text)
    native_error = None
    if failure != 'missing_parent':
        native_error = PermissionError(13, 'synthetic access denied') if failure == 'permission' else OSError(28, 'synthetic disk full')
        real_open = open
        def output_open(path, mode='r', **kwargs):
            if str(path) == str(destination) and mode == 'w':
                if failure == 'permission':
                    raise native_error
                handle = MagicMock()
                handle.__enter__.return_value.write.side_effect = native_error
                return handle
            return real_open(path, mode, **kwargs)
        monkeypatch.setattr(converter, 'open', output_open, raising=False)
    result = converter.convert_file(str(source), str(destination))
    assert result['status'] == 'error' and result['completeness'] == 'partial'
    assert result['output'] == text and result['warnings']
    assert (str(native_error) if native_error else 'FileNotFoundError') in result['message']
    capsys.readouterr()
    monkeypatch.setattr(sys, 'argv', ['converter.py', str(source), '-o', str(destination)])
    with pytest.raises(SystemExit) as exc:
        converter.main()
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert captured.out == text + chr(10)
    assert 'ERROR:' in captured.err and 'WARNING:' in captured.err
    assert source.read_bytes() == b'synthetic short EPUB'
    assert not destination.exists()
