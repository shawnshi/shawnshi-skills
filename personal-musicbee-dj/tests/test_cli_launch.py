"""Offline CLI launch tests: no config, library, or player access."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def cli(monkeypatch, tmp_path):
    curator = SimpleNamespace(DJCurator=Mock(side_effect=AssertionError('no library access')))
    logger = SimpleNamespace(log=Mock())
    with patch.dict(sys.modules, {'src.core.curator': curator, 'src.utils.logger': logger}):
        spec = importlib.util.spec_from_file_location('musicbee_cli_test', Path(__file__).parents[1] / 'src/cli.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    exe = tmp_path / 'Music Bee.exe'
    exe.touch()
    monkeypatch.setattr(module, 'load_config', lambda _: {'musicbee': {'exe_path': str(exe)}})
    monkeypatch.setattr(module, 'resolve_config_paths', lambda config, _: config)
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'playlist', '--value', 'A "quoted" & named playlist'])
    monkeypatch.setattr(module.subprocess, 'run', Mock(side_effect=AssertionError('no shell/WMI')))
    return module, exe


def test_launch_uses_literal_arguments_and_reports_only_request(cli, monkeypatch):
    module, exe = cli
    launch = Mock(return_value=SimpleNamespace(pid=321, poll=lambda: None))
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    module.main()
    launch.assert_called_once_with([str(exe), 'A "quoted" & named playlist'], shell=False)
    messages = str(module.log.info.call_args_list)
    assert 'request submitted' in messages and 'not confirmed' in messages


@pytest.mark.parametrize('failure', [PermissionError(13, 'access denied'), FileNotFoundError(2, 'missing exe')])
def test_creation_error_exits_nonzero(cli, monkeypatch, failure):
    module, _ = cli
    monkeypatch.setattr(module.subprocess, 'Popen', Mock(side_effect=failure))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code != 0
    assert str(failure) in str(module.log.error.call_args_list)
    assert 'request submitted' not in str(module.log.info.call_args_list)


def test_immediate_process_failure_exits_nonzero(cli, monkeypatch):
    module, _ = cli
    monkeypatch.setattr(module.subprocess, 'Popen', Mock(return_value=SimpleNamespace(pid=321, poll=lambda: 5)))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code != 0
    assert '5' in str(module.log.error.call_args_list)


def test_invalid_executable_never_launches(cli, monkeypatch):
    module, exe = cli
    exe.unlink()
    launch = Mock(side_effect=AssertionError('must not launch'))
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    with pytest.raises(SystemExit):
        module.main()
    launch.assert_not_called()


def test_executable_directory_is_rejected(cli, monkeypatch):
    module, exe = cli
    exe.unlink()
    exe.mkdir()
    launch = Mock(side_effect=AssertionError('must not launch directory'))
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    with pytest.raises(SystemExit):
        module.main()
    launch.assert_not_called()


def test_successful_immediate_exit_only_reports_submission(cli, monkeypatch):
    module, _ = cli
    monkeypatch.setattr(module.subprocess, 'Popen', Mock(return_value=SimpleNamespace(pid=321, poll=lambda: 0)))
    module.main()
    assert 'not confirmed' in str(module.log.info.call_args_list)
