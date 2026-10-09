"""Policy regressions use synthetic metadata and mocked player/process controls only."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_runtime import config, runtime, track, song, write_library, cli
from src.core.curator import DJCurator
from src.core.parser import MusicBeeParser


def distinct_tracks():
    items = [track(i, bpm=60 + i * 5) for i in range(1, 9)]
    for item in items:
        item.artist = f'artist-{item.id}'
        item.album = f'album-{item.id}'
    return items


def test_focus_and_energy_have_different_bpm_profiles(config):
    config['request'] = {'seed': 7}
    items = distinct_tracks()
    focus = DJCurator(config)._build_energy_curve(items, 'focus', 'low')
    energy = DJCurator(config)._build_energy_curve(items, 'energy', 'high')
    assert [item.bpm for item in focus] == sorted([item.bpm for item in items], reverse=True)
    assert [item.bpm for item in energy] == sorted(item.bpm for item in items)
    assert {item.id for item in focus} == {item.id for item in energy}


def test_unknown_bpm_ordering_uses_artist_spacing_not_unconditional_shuffle(config):
    items = distinct_tracks() + [track(9), track(10)]
    for item in items[8:]:
        item.artist, item.album = f'artist-{item.id}', f'album-{item.id}'
    for item in items:
        item.bpm = 0
    for item in items[:4]:
        item.artist, item.album = 'shared', 'shared-album'
    config['request'] = {'seed': 3}
    curator = DJCurator(config)
    output = curator._build_energy_curve(items, 'focus', 'low')
    assert len(output) == len(items)
    for index, item in enumerate(output):
        assert item.artist not in {prior.artist for prior in output[max(0, index - 2):index]}
    assert curator.sequence_relaxations == 0


def test_spacing_shortages_are_reported_not_hidden(config):
    curator = DJCurator(config)
    items = [track(i) for i in range(1, 5)]
    assert len(curator._build_energy_curve(items, 'focus', 'low')) == 4
    assert curator.sequence_relaxations == 3


def test_semantic_version_dedup_preserves_different_movements_and_artists(config):
    items = [track(i) for i in range(1, 6)]
    for item, title in zip(items, ['Sonata I', 'Sonata I (2019 Remastered)', 'Sonata II', 'Sonata I', 'Sonata I (Olive Mix)']):
        item.name = title
    items[3].artist = 'other'
    selected = DJCurator(config)._select_ratio_tracks(items, 5)
    assert len(selected) == 4
    assert any(item.name == 'Sonata II' for item in selected)
    assert any(item.artist == 'other' for item in selected)
    assert any(item.name.endswith('(Olive Mix)') for item in selected)


def test_version_suffixes_do_not_erase_movement_labels(config):
    first, second = track(1), track(2)
    first.name, second.name = 'Sonata (Live I)', 'Sonata (Live II)'
    assert DJCurator._recording_key(first) != DJCurator._recording_key(second)


def test_unknown_titles_not_merged_by_missing_metadata(config):
    items = [track(i) for i in range(1, 4)]
    for item in items:
        item.name = item.artist = 'Unknown'
    assert len(DJCurator(config)._select_ratio_tracks(items, 3)) == 3


def test_seed_reproduces_selection_and_order_for_same_candidates(config):
    items = distinct_tracks()
    config['request'] = {'seed': 97}
    first, second = DJCurator(config), DJCurator(config)
    a = first._build_energy_curve(first._select_ratio_tracks(items, 6), 'focus', 'low')
    b = second._build_energy_curve(second._select_ratio_tracks(items, 6), 'focus', 'low')
    assert [item.id for item in a] == [item.id for item in b]


@pytest.mark.parametrize(('strategy', 'weights'), [
    ('balanced', (0.6, 0.3, 0.1)), ('familiar', (0.8, 0.15, 0.05)), ('explore', (0.3, 0.5, 0.2)),
])
def test_familiarity_is_explicit_per_request_not_saved(config, strategy, weights):
    original = config['playlist']['curation'].copy()
    config['request'] = {'familiarity': strategy}
    dj = DJCurator(config)
    assert (dj.anchor_ratio, dj.discovery_ratio, dj.novelty_ratio) == weights
    assert config['playlist']['curation'] == original


def test_preferred_artist_is_prioritized_within_requested_quota(config):
    items = distinct_tracks()
    config['playlist']['curation'] = {'anchor_ratio': 1, 'discovery_ratio': 0, 'novelty_ratio': 0}
    config['request'] = {'prefer_artists': ['artist-8'], 'seed': 1}
    assert DJCurator(config)._select_ratio_tracks(items, 1)[0].artist == 'artist-8'


def test_track_album_exclusions_and_vocal_tag_unknowns(config):
    item = track(1)
    config['request'] = {'exclude_tracks': ['fixture-1']}
    assert not DJCurator(config)._filter_by_intensity([item], 'normal')
    config['request'] = {'exclude_albums': ['fixture']}
    assert not DJCurator(config)._filter_by_intensity([item], 'normal')
    assert DJCurator._vocal_status(item) == 'unknown'
    item.genre = 'Jazz; Non-Vocal'
    assert DJCurator._vocal_status(item) == 'instrumental'


def test_production_parser_without_cache_never_writes_index(config, monkeypatch):
    parser = MusicBeeParser(config['musicbee']['xml_path'])
    real_open = open
    def guarded_open(file, mode='r', *args, **kwargs):
        assert not any(flag in mode for flag in 'wax+')
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr('builtins.open', guarded_open)
    assert len(parser.load_library()) == 1
    assert not Path(config['cache']['db_path']).exists()


@pytest.mark.parametrize(('mode', 'command'), [('play', '/Play'), ('next', '/QueueNext'), ('last', '/QueueLast')])
def test_documented_queue_switches_are_literal(runtime, monkeypatch, mode, command):
    temp_root, launch = runtime
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', 'focus', '--queue', mode])
    cli.main()
    task = next(temp_root.iterdir())
    assert launch.call_args.args[0][1:] == [command, str(task / 'queue.m3u')]
    cli.cleanup_task(task)


def test_running_player_without_replacement_permission_stops_before_library_read(runtime, monkeypatch):
    temp_root, launch = runtime
    monkeypatch.setattr(cli, 'musicbee_running', lambda: True)
    monkeypatch.setattr(cli, 'DJCurator', Mock(side_effect=AssertionError('no library read')))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert not list(temp_root.iterdir())
    launch.assert_not_called()


def test_explicit_replacement_permission_is_not_requested_again(runtime, monkeypatch):
    temp_root, launch = runtime
    monkeypatch.setattr(cli, 'musicbee_running', Mock(side_effect=AssertionError('explicit permission already supplied')))
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', 'focus', '--replace-current'])
    cli.main()
    launch.assert_called_once()
    cli.cleanup_task(next(temp_root.iterdir()))


def test_process_probe_unknown_output_never_means_stopped(monkeypatch):
    monkeypatch.setattr(cli.sys, 'platform', 'win32')
    query = Mock(return_value=SimpleNamespace(stdout='unexpected'))
    monkeypatch.setattr(cli.subprocess, 'run', query)
    with pytest.raises(ValueError, match='could not be determined'):
        cli.musicbee_running()
    assert query.call_args.kwargs['check'] is True and query.call_args.kwargs['timeout'] == 5


@pytest.mark.parametrize(('answer', 'running'), [('running\n', True), ('stopped\n', False)])
def test_process_probe_is_presence_not_play_state(monkeypatch, answer, running):
    monkeypatch.setattr(cli.sys, 'platform', 'win32')
    monkeypatch.setattr(cli.subprocess, 'run', Mock(return_value=SimpleNamespace(stdout=answer)))
    assert cli.musicbee_running() == running


def test_probe_execution_error_never_becomes_stopped(runtime, monkeypatch):
    temp_root, launch = runtime
    # runtime patches the probe: restore the real function via the module source without launching.
    import importlib.util
    spec = importlib.util.spec_from_file_location('musicbee_probe_regression', Path(cli.__file__))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(cli, 'musicbee_running', module.musicbee_running)
    error = cli.subprocess.CalledProcessError(1, ['powershell.exe'], stderr='fixture permission denied')
    monkeypatch.setattr(cli.subprocess, 'run', Mock(side_effect=error))
    with pytest.raises(SystemExit):
        cli.main()
    assert not list(temp_root.iterdir())
    launch.assert_not_called()


def test_non_windows_append_cannot_bypass_platform_gate(runtime, monkeypatch):
    temp_root, launch = runtime
    monkeypatch.setattr(cli.sys, 'platform', 'linux')
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', 'focus', '--queue', 'last'])
    with pytest.raises(SystemExit):
        cli.main()
    assert not list(temp_root.iterdir())
    launch.assert_not_called()


def test_bare_playlist_name_rejected_without_launch(runtime, monkeypatch):
    _, launch = runtime
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'playlist', '--value', 'My Favorites'])
    with pytest.raises(SystemExit):
        cli.main()
    launch.assert_not_called()


def test_existing_playlist_is_not_curated_or_reordered(runtime, monkeypatch):
    temp_root, launch = runtime
    playlist = temp_root / 'user-order.m3u'
    original = '#EXTM3U\nsecond.mp3\nfirst.mp3\n'
    playlist.write_text(original, encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'playlist', '--value', str(playlist)])
    monkeypatch.setattr(cli, 'DJCurator', Mock(side_effect=AssertionError('no curation')))
    cli.main()
    assert launch.call_args.args[0][1:] == ['/Play', str(playlist.resolve())]
    assert playlist.read_text(encoding='utf-8') == original
    assert not list(temp_root.glob('musicbee-dj-*'))
