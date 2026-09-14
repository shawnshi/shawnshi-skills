"""Offline WAV tests; no credentials, providers or real playback."""
import asyncio
import importlib.util
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def wav(path, frames=4, channels=1, width=2, rate=24000, sample=b'X'):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(width)
        stream.setframerate(rate)
        stream.writeframes(sample * frames * channels * width)
    return path


@pytest.fixture
def engine(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('tts_engine_test', Path(__file__).parents[1] / 'scripts/tts_engine.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os, 'environ', {})
    instance = module.FastTTSEngine(tmp_path / 'parts')
    return module, instance


def args(tmp_path, play=False, output=True):
    return SimpleNamespace(voice='fixture', scene=None, profile=None, notes=None, play=play,
                           output=str(tmp_path / 'output.wav') if output else None)


def test_merge_different_durations(engine, tmp_path):
    _, instance = engine
    parts = [wav(tmp_path / 'a.wav', 3, sample=b'A'), wav(tmp_path / 'b.wav', 8, sample=b'B')]
    output = tmp_path / 'merged.wav'
    assert instance._merge_wav(parts, output)
    with wave.open(str(output), 'rb') as stream:
        assert stream.getnframes() == 11
        assert stream.getcomptype() == 'NONE'
        assert stream.readframes(11) == b'A' * 6 + b'B' * 16


@pytest.mark.parametrize('change', [{'channels': 2}, {'width': 1}, {'rate': 8000}])
def test_incompatible_format_rejected(engine, tmp_path, change):
    _, instance = engine
    parts = [wav(tmp_path / 'a.wav'), wav(tmp_path / 'b.wav', **change)]
    assert not instance._merge_wav(parts, tmp_path / 'bad.wav')
    assert all(p.exists() for p in parts)


@pytest.mark.parametrize('count', [1, 2])
def test_complete_synthesis(engine, tmp_path, monkeypatch, capsys, count):
    _, instance = engine
    parts = [wav(instance.output_dir / f'fixture_{i}.wav', i + 3) for i in range(count)]
    monkeypatch.setattr(instance, '_synthesize_sentence', AsyncMock(side_effect=parts))
    player = AsyncMock(side_effect=AssertionError('generation must not play'))
    monkeypatch.setattr(instance, '_play_audio', player)
    assert asyncio.run(instance.process('Hello. ' * count, args(tmp_path))) is True
    with wave.open(str(tmp_path / 'output.wav'), 'rb') as stream:
        assert stream.getnframes() == sum(i + 3 for i in range(count))
    assert not any(p.exists() for p in parts)
    player.assert_not_called()
    assert 'SUCCESS' in capsys.readouterr().out


@pytest.mark.parametrize('failure', ['missing', 'exception', 'merge', 'output_missing', 'invalid'])
def test_failure_retains_parts_and_old_output(engine, tmp_path, monkeypatch, capsys, failure):
    _, instance = engine
    first = wav(instance.output_dir / 'first.wav')
    second = wav(instance.output_dir / 'second.wav')
    old_output = wav(tmp_path / 'output.wav', 19).read_bytes()
    values = [first, second]
    if failure == 'missing': values[1] = None
    if failure == 'exception': values[1] = RuntimeError('synthetic provider error')
    if failure == 'invalid': values[1] = tmp_path / 'nonexistent.wav'
    monkeypatch.setattr(instance, '_synthesize_sentence', AsyncMock(side_effect=values))
    if failure in {'merge', 'output_missing'}:
        monkeypatch.setattr(instance, '_merge_wav', Mock(return_value=failure == 'output_missing'))
    fallback = Mock(side_effect=AssertionError('partial synthesis must not be hidden'))
    monkeypatch.setattr(instance, '_speak_local', fallback)
    assert asyncio.run(instance.process('First. Second.', args(tmp_path))) is False
    assert first.exists() and second.exists()
    assert (tmp_path / 'output.wav').read_bytes() == old_output
    assert 'SUCCESS' not in capsys.readouterr().out
    fallback.assert_not_called()


def test_player_failure(engine, tmp_path, monkeypatch, capsys):
    module, instance = engine
    part = wav(instance.output_dir / 'first.wav')
    monkeypatch.setattr(instance, '_synthesize_sentence', AsyncMock(return_value=part))
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', AsyncMock(return_value=SimpleNamespace(wait=AsyncMock(return_value=7))))
    assert asyncio.run(instance.process('First.', args(tmp_path, play=True, output=False))) is False
    assert part.exists()
    assert 'SUCCESS' not in capsys.readouterr().out


@pytest.mark.parametrize('outcome', ['success', 'exception', 'missing_output'])
def test_local_fallback_fresh_output(engine, tmp_path, monkeypatch, capsys, outcome):
    _, instance = engine
    old = wav(tmp_path / 'output.wav', 13).read_bytes()
    monkeypatch.setattr(instance, '_synthesize_sentence', AsyncMock(return_value=None))
    backend = Mock()
    backend.getProperty.return_value = []
    if outcome == 'success': backend.save_to_file.side_effect = lambda text, path: wav(path, 5)
    if outcome == 'exception': backend.runAndWait.side_effect = RuntimeError('local backend failed')
    monkeypatch.setitem(sys.modules, 'pyttsx3', SimpleNamespace(init=Mock(return_value=backend)))
    ok = asyncio.run(instance.process('Hello.', args(tmp_path)))
    assert ok is (outcome == 'success')
    backend.say.assert_not_called()
    output = capsys.readouterr().out
    assert ('SUCCESS' in output) is (outcome == 'success')
    if outcome != 'success': assert (tmp_path / 'output.wav').read_bytes() == old


def test_main_failure_exit(engine, monkeypatch):
    module, instance = engine
    monkeypatch.setattr(sys, 'argv', ['tts_engine.py', 'fixture', '--output', 'unused.wav'])
    monkeypatch.setattr(module, 'FastTTSEngine', Mock(return_value=instance))
    monkeypatch.setattr(instance, 'process', AsyncMock(return_value=False))
    with pytest.raises(SystemExit) as exc:
        asyncio.run(module.main())
    assert exc.value.code != 0


@pytest.mark.parametrize('save_ok', [True, False])
def test_synthesis_save_failure_and_unique_fragments(engine, tmp_path, monkeypatch, save_ok):
    module, instance = engine
    constructors = {name: (lambda **kw: kw) for name in
                    ['SpeechConfig', 'VoiceConfig', 'PrebuiltVoiceConfig', 'GenerateContentConfig']}
    monkeypatch.setattr(module, 'types', SimpleNamespace(**constructors))
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
        SimpleNamespace(inline_data=SimpleNamespace(data=b'X' * 8))]))])
    instance.client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=response)))
    old_part = wav(instance.output_dir / 'part_0.wav', 17)
    old_bytes = old_part.read_bytes()
    if not save_ok:
        monkeypatch.setattr(instance, '_save_as_wav', Mock(return_value=False))
    first = asyncio.run(instance._synthesize_sentence('Hello.', 'fixture', 0, args(tmp_path)))
    second = asyncio.run(instance._synthesize_sentence('Hello.', 'fixture', 0, args(tmp_path)))
    if save_ok:
        assert first != second and first != old_part
        assert instance._valid_wav(first) and instance._valid_wav(second)
    else:
        assert first is None and second is None
    assert old_part.read_bytes() == old_bytes


def test_play_only_cloud_success(engine, tmp_path, monkeypatch, capsys):
    module, instance = engine
    part = wav(instance.output_dir / 'play.wav')
    monkeypatch.setattr(instance, '_synthesize_sentence', AsyncMock(return_value=part))
    player = AsyncMock(return_value=SimpleNamespace(wait=AsyncMock(return_value=0)))
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', player)
    assert asyncio.run(instance.process('Hello.', args(tmp_path, play=True, output=False))) is True
    player.assert_called_once()
    assert not part.exists() and not (tmp_path / 'output.wav').exists()
    assert 'played=1' in capsys.readouterr().out


def test_compression_mismatch_is_rejected(engine, tmp_path, monkeypatch):
    module, instance = engine
    first = wav(tmp_path / 'pcm.wav')
    with wave.open(str(first), 'rb') as stream:
        params = stream.getparams()
    sources = []
    for compression in ['NONE', 'ULAW']:
        source = Mock()
        source.getparams.return_value = params._replace(comptype=compression)
        source.readframes.return_value = b'X' * 8
        context = Mock()
        context.__enter__ = Mock(return_value=source)
        context.__exit__ = Mock(return_value=False)
        sources.append(context)
    monkeypatch.setattr(module.wave, 'open', Mock(side_effect=sources))
    assert not instance._merge_wav(['first.wav', 'second.wav'], tmp_path / 'bad.wav')


def test_local_failure_preserves_generated_recovery_file(engine, tmp_path, monkeypatch, capsys):
    _, instance = engine
    backend = Mock()
    backend.getProperty.return_value = []
    paths = []
    def save(text, path):
        paths.append(wav(Path(path), 5))
    backend.save_to_file.side_effect = save
    backend.runAndWait.side_effect = RuntimeError('native local failure')
    monkeypatch.setitem(sys.modules, 'pyttsx3', SimpleNamespace(init=Mock(return_value=backend)))
    assert not instance._speak_local('Hello.', 180, 1.0, str(tmp_path / 'output.wav'))
    assert len(paths) == 1 and paths[0].exists()
    assert 'native local failure' in capsys.readouterr().out


def test_truncated_wav_rejected(engine, tmp_path):
    _, instance = engine
    part = wav(tmp_path / 'truncated.wav', 8)
    part.write_bytes(part.read_bytes()[:-2])
    assert not instance._valid_wav(part)
    assert not instance._merge_wav([part], tmp_path / 'result.wav')
    assert part.exists()


def test_local_play_only_fallback(engine, tmp_path, monkeypatch):
    _, instance = engine
    monkeypatch.setattr(instance, '_synthesize_sentence', AsyncMock(return_value=None))
    backend = Mock()
    backend.getProperty.return_value = []
    monkeypatch.setitem(sys.modules, 'pyttsx3', SimpleNamespace(init=Mock(return_value=backend)))
    assert asyncio.run(instance.process('Hello.', args(tmp_path, play=True, output=False))) is True
    backend.say.assert_called_once_with('Hello.')
    backend.save_to_file.assert_not_called()
    backend.runAndWait.assert_called_once()
