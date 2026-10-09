"""Synthetic library/config fixtures; never read the user's library or start MusicBee."""
import copy
import importlib
import json
import os
from pathlib import Path
import plistlib
import random
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
cli = importlib.import_module('src.cli')
from src.core.curator import DJCurator
from src.core.models import Track, CuratedPlayback
from src.core.parser import MusicBeeParser, MusicBeeParserError


def write_library(path, songs, playlists_first=False):
    data = {'Tracks': {str(song['Track ID']): song for song in songs}, 'Playlists': []}
    if playlists_first:
        data = {'Playlists': [], 'Tracks': data['Tracks']}
    with path.open('wb') as handle:
        plistlib.dump(data, handle, sort_keys=False)


def song(path, track_id=1, name=None, genre='Jazz', bpm=80):
    path.touch()
    return {'Track ID': track_id, 'Name': name if name is not None else path.stem, 'Artist': 'fixture', 'Location': path.as_uri(),
            'Genre': genre, 'BPM': bpm, 'Play Count': 0}


def track(index, path=None, play_count=0, date='2026-01-01T00:00:00Z', bpm=80):
    return Track(index, f'fixture-{index}', 'fixture', 'fixture', 'Jazz', play_count, bpm, 1000,
                 date, str(path or f'fixture-{index}.mp3'))


@pytest.fixture
def config(tmp_path):
    cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
    exe = tmp_path / 'MusicBee.exe'
    exe.touch()
    xml = tmp_path / 'library.xml'
    write_library(xml, [song(tmp_path / 'quiet.mp3', name='fixture')])
    cfg['musicbee'] = {'exe_path': str(exe), 'xml_path': str(xml)}
    cfg['cache'] = {'db_path': str(tmp_path / 'cache.json')}
    cfg['playlist']['output_m3u'] = str(tmp_path / 'queue.m3u')
    return cfg


def test_track_and_playlist_directories_are_not_playable(tmp_path):
    assert not track(1, tmp_path).is_valid
    assert not CuratedPlayback(str(tmp_path), 'scene', 'focus', 'focus', 1, 1, 1).is_playable


def test_track_types_and_negative_numbers_rejected():
    with pytest.raises(ValueError, match='play_count'):
        track(1, play_count='2')
    with pytest.raises(ValueError, match='bpm'):
        track(1, bpm=-1)


@pytest.mark.parametrize(('uri', 'expected'), [
    ('file://fixture-server/share/a%20b.mp3', r'\\fixture-server\share\a b.mp3'),
    ('file://localhost/C:/Music/a%20b.mp3', r'C:\Music\a b.mp3'),
    ('file:///C:/Music/a.mp3', r'C:\Music\a.mp3'),
    (r'C:\Music\a.mp3', r'C:\Music\a.mp3'),
])
def test_file_uri_paths(uri, expected):
    assert MusicBeeParser._location_to_path(uri) == expected


@pytest.mark.parametrize('location', ['https://example.test/a.mp3', 'relative.mp3', 'x\ny'])
def test_nonlocal_or_unrepresentable_locations_rejected(location):
    with pytest.raises(ValueError):
        MusicBeeParser._location_to_path(location)


def test_parser_round_trip_and_valid_cache(config, monkeypatch):
    parser = MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path'])
    first = parser.load_library()
    assert len(first) == 1 and first[0].is_valid
    monkeypatch.setattr(parser, '_parse_and_cache_xml', Mock(side_effect=AssertionError('unexpected reparse')))
    assert parser.load_library() == first


@pytest.mark.parametrize('bad_cache', [[], {'version': 999}, 'not json', 'invalid_rows', 'invalid_types'])
def test_invalid_cache_rebuilt_from_xml(config, bad_cache):
    parser = MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path'])
    if bad_cache == 'invalid_rows':
        payload = {'version': 1, 'source': parser._source_identity(), 'tracks': [{'unexpected': 1}]}
    elif bad_cache == 'invalid_types':
        payload = {'version': 1, 'source': parser._source_identity(),
                   'tracks': [{**track(1).__dict__, 'bpm': 'slow'}]}
    else:
        payload = bad_cache
    Path(parser.cache_path).write_text('{' if bad_cache == 'not json' else json.dumps(payload), encoding='utf-8')
    assert [item.name for item in parser.load_library()] == ['fixture']
    assert json.loads(Path(parser.cache_path).read_text(encoding='utf-8'))['version'] == 1


def test_cache_cannot_cross_xml_sources_with_equal_size_and_time(config, tmp_path):
    xml1 = Path(config['musicbee']['xml_path'])
    xml2 = tmp_path / 'other.xml'
    write_library(xml2, [song(tmp_path / 'quiet.mp3', name='another')])
    stamp = 1_700_000_000_000_000_000
    os.utime(xml1, ns=(stamp, stamp))
    os.utime(xml2, ns=(stamp, stamp))
    assert xml1.stat().st_size == xml2.stat().st_size
    assert xml1.stat().st_mtime_ns == xml2.stat().st_mtime_ns
    parser1 = MusicBeeParser(str(xml1), config['cache']['db_path'])
    assert parser1.load_library()[0].name == 'fixture'
    parser2 = MusicBeeParser(str(xml2), config['cache']['db_path'])
    assert parser2.load_library()[0].name == 'another'


def test_library_dictionary_order_is_not_semantic(config, tmp_path):
    xml = Path(config['musicbee']['xml_path'])
    write_library(xml, [song(tmp_path / 'quiet.mp3')], playlists_first=True)
    assert len(MusicBeeParser(str(xml), config['cache']['db_path']).load_library()) == 1


def test_malformed_xml_is_error_not_empty(config):
    Path(config['musicbee']['xml_path']).write_text('<plist><dict>', encoding='utf-8')
    with pytest.raises(MusicBeeParserError, match='Failed to parse XML'):
        MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path']).load_library()


def test_cache_io_error_is_not_silently_rebuilt(config, monkeypatch):
    parser = MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path'])
    parser.load_library()
    monkeypatch.setattr('builtins.open', Mock(side_effect=PermissionError(13, 'fixture denied')))
    with pytest.raises(MusicBeeParserError, match='I/O failed'):
        parser.load_library()


def test_night_scene_mapping_and_unknown_scene_rejection(config):
    curator = DJCurator(config)
    assert curator._resolve_scene_name('播放适合夜间思考的音乐')[0] == 'focus'
    assert curator._resolve_scene_name('night thinking')[0] == 'focus'
    assert config['scenes']['focus']['intensity'] == 'low'
    assert curator.generate_m3u('scene', 'unmapped-scene', 'low') is None
    assert not Path(config['playlist']['output_m3u']).exists()


def test_novelty_ratio_changes_selection(config):
    items = [track(i, play_count=8) for i in range(1, 11)] + [
        track(i, play_count=3, date='2026-10-01T00:00:00Z') for i in range(11, 21)]
    anchors = copy.deepcopy(config)
    anchors['playlist']['curation'] = {'anchor_ratio': 1, 'discovery_ratio': 0, 'novelty_ratio': 0}
    newest = copy.deepcopy(config)
    newest['playlist']['curation'] = {'anchor_ratio': 0, 'discovery_ratio': 0, 'novelty_ratio': 1}
    random.seed(1)
    assert all(item.id <= 10 for item in DJCurator(anchors)._select_ratio_tracks(items, 5))
    random.seed(1)
    assert all(item.id >= 11 for item in DJCurator(newest)._select_ratio_tracks(items, 5))


def test_quota_rounding_shortage_and_path_deduplication(config):
    items = [track(i, play_count=3) for i in range(1, 12)]
    items.append(track(999, path=items[0].local_path))
    selected = DJCurator(config)._select_ratio_tracks(items, 7)
    assert len(selected) == 7
    assert len({item.local_path for item in selected}) == 7


def test_final_export_filters_directories_and_preserves_count(config, tmp_path):
    xml = Path(config['musicbee']['xml_path'])
    items = [song(tmp_path / f'quiet-{i}.mp3', track_id=i) for i in range(1, 7)]
    items.append({'Track ID': 7, 'Name': 'directory', 'Genre': 'Jazz', 'Location': tmp_path.as_uri()})
    write_library(xml, items)
    config['playlist']['max_tracks_per_session'] = 5
    result = DJCurator(config).generate_m3u('scene', 'focus', 'low')
    assert result.is_playable and result.exported_tracks == 5
    lines = Path(result.play_target).read_text(encoding='utf-8-sig').splitlines()
    assert len([line for line in lines if line and not line.startswith('#')]) == 5
    assert str(tmp_path) not in lines


@pytest.mark.parametrize('ratios', [
    {'anchor_ratio': 0.7, 'discovery_ratio': 0.3, 'novelty_ratio': 0.3},
    {'anchor_ratio': float('nan')}, {'anchor_ratio': True}, {'novelty_ratio': -0.1},
])
def test_invalid_ratios_fail_configuration_gate(config, ratios):
    config['playlist']['curation'].update(ratios)
    assert any('ratios' in error for error in cli.validate_config(config, 'scene'))


def test_env_override_and_unresolved_placeholder(config, tmp_path, monkeypatch):
    exe = tmp_path / 'override.exe'
    exe.touch()
    monkeypatch.setenv('MUSICBEE_EXE_PATH', str(exe))
    assert cli.resolve_config_paths(copy.deepcopy(config), ROOT)['musicbee']['exe_path'] == str(exe.resolve())
    monkeypatch.delenv('MUSICBEE_EXE_PATH')
    monkeypatch.delenv('MUSICBEE_XML_PATH', raising=False)
    config['musicbee']['xml_path'] = '${MUSICBEE_XML_PATH}'
    with pytest.raises(ValueError, match='Unresolved environment variable'):
        cli.resolve_config_paths(config, ROOT)


def test_xml_directory_rejected(config, tmp_path):
    config['musicbee']['xml_path'] = str(tmp_path)
    assert any('xml_path' in error for error in cli.validate_config(config, 'scene'))


def test_empty_yaml_rejected(tmp_path):
    path = tmp_path / 'empty.yaml'
    path.write_text('', encoding='utf-8')
    with pytest.raises(ValueError, match='YAML mapping'):
        cli.load_config(path)


@pytest.fixture
def runtime(config, tmp_path, monkeypatch):
    temp_root = tmp_path / 'tasks'
    temp_root.mkdir()
    monkeypatch.setattr(cli.tempfile, 'gettempdir', lambda: str(temp_root))
    monkeypatch.setattr(cli, 'load_config', lambda _: copy.deepcopy(config))
    monkeypatch.setattr(cli, 'log', Mock())
    monkeypatch.setattr(cli, 'musicbee_running', lambda: False)
    launch = Mock(return_value=SimpleNamespace(pid=123, poll=lambda: None))
    monkeypatch.setattr(cli.subprocess, 'Popen', launch)
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', '夜间思考'])
    return temp_root, launch


def test_synthetic_xml_to_m3u_to_literal_launch_and_cleanup(runtime):
    temp_root, launch = runtime
    cli.main()
    task_dirs = list(temp_root.iterdir())
    assert len(task_dirs) == 1
    task = task_dirs[0]
    assert {item.name for item in task.iterdir()} == {cli.TASK_MARKER, 'queue.m3u'}
    args, kwargs = launch.call_args
    assert kwargs == {'shell': False} and args[0][1:] == ['/Play', str(task / 'queue.m3u')]
    assert '#EXTM3U' in (task / 'queue.m3u').read_text(encoding='utf-8-sig')
    messages = str(cli.log.info.call_args_list)
    assert 'intensity=low' in messages and 'not confirmed' in messages
    cli.cleanup_task(task)
    assert not task.exists()


def test_failed_launch_removes_all_task_artifacts(runtime):
    temp_root, launch = runtime
    launch.side_effect = PermissionError(13, 'fixture denied')
    with pytest.raises(SystemExit):
        cli.main()
    assert not list(temp_root.iterdir())


def test_immediate_failed_scene_launch_removes_task_artifacts(runtime):
    temp_root, launch = runtime
    launch.return_value = SimpleNamespace(pid=123, poll=lambda: 9)
    with pytest.raises(SystemExit):
        cli.main()
    assert not list(temp_root.iterdir())


def test_check_has_no_library_artifacts_or_launch(runtime, monkeypatch):
    temp_root, launch = runtime
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--check'])
    cli.main()
    assert not list(temp_root.iterdir())
    launch.assert_not_called()


def test_unknown_scene_cleans_task_without_launch(runtime, monkeypatch):
    temp_root, launch = runtime
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', 'unmapped-scene'])
    with pytest.raises(SystemExit):
        cli.main()
    assert not list(temp_root.iterdir())
    launch.assert_not_called()


def test_cleanup_rejects_foreign_directory_and_unknown_files(runtime, tmp_path):
    temp_root, _ = runtime
    foreign = tmp_path / 'musicbee-dj-foreign'
    foreign.mkdir()
    with pytest.raises(ValueError, match='namespace'):
        cli.cleanup_task(foreign)
    marked = temp_root / 'musicbee-dj-test'
    marked.mkdir()
    (marked / cli.TASK_MARKER).write_text('1\n', encoding='utf-8')
    (marked / 'user-file.txt').write_text('fixture', encoding='utf-8')
    with pytest.raises(ValueError, match='unrecognized'):
        cli.cleanup_task(marked)
    assert (marked / cli.TASK_MARKER).exists() and (marked / 'user-file.txt').exists()


def test_cleanup_does_not_need_player_config(runtime, monkeypatch):
    temp_root, _ = runtime
    task = temp_root / 'musicbee-dj-test'
    task.mkdir()
    (task / cli.TASK_MARKER).write_text('1\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--cleanup-task', str(task)])
    monkeypatch.setattr(cli, 'load_config', Mock(side_effect=AssertionError('no config needed')))
    cli.main()
    assert not task.exists()


def test_missing_tracks_is_schema_error_not_empty(config):
    Path(config['musicbee']['xml_path']).write_bytes(plistlib.dumps({'Playlists': []}))
    with pytest.raises(MusicBeeParserError, match='no root Tracks'):
        MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path']).load_library()


def test_trailing_malformed_xml_is_not_accepted(config):
    path = Path(config['musicbee']['xml_path'])
    path.write_bytes(path.read_bytes().replace(b'</plist>', b'</broken>'))
    with pytest.raises(MusicBeeParserError):
        MusicBeeParser(str(path), config['cache']['db_path']).load_library()
    assert not Path(config['cache']['db_path']).exists()


@pytest.mark.parametrize('field', ['Track Count', 'Track Number', 'Disc Count'])
def test_multivalue_unused_integer_metadata_does_not_block_playback(config, field):
    path = Path(config['musicbee']['xml_path'])
    with path.open('rb') as handle:
        data = plistlib.load(handle)
    data['Tracks']['1'][field] = 28
    with path.open('wb') as handle:
        plistlib.dump(data, handle, sort_keys=False)
    path.write_bytes(path.read_bytes().replace(b'<integer>28</integer>', b'<integer>28; 57</integer>'))
    tracks = MusicBeeParser(str(path), config['cache']['db_path']).load_library()
    assert len(tracks) == 1 and tracks[0].bpm == 80 and tracks[0].is_valid


def test_invalid_source_integer_is_not_silently_zero(config):
    path = Path(config['musicbee']['xml_path'])
    path.write_bytes(path.read_bytes().replace(b'<integer>80</integer>', b'<integer>invalid</integer>'))
    with pytest.raises(MusicBeeParserError):
        MusicBeeParser(str(path), config['cache']['db_path']).load_library()


def test_source_change_during_parse_prevents_cache(config, monkeypatch):
    parser = MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path'])
    source = parser._source_identity()
    changed = {**source, 'size': source['size'] + 1}
    monkeypatch.setattr(parser, '_source_identity', Mock(side_effect=[source, changed]))
    with pytest.raises(MusicBeeParserError, match='changed during parsing'):
        parser.load_library()
    assert not Path(parser.cache_path).exists()


def test_available_pools_obey_all_three_quotas(config):
    items = ([track(i, play_count=8) for i in range(1, 21)]
             + [track(i, play_count=0) for i in range(21, 41)]
             + [track(i, play_count=3, date='2026-10-01T00:00:00Z') for i in range(41, 61)])
    selected = DJCurator(config)._select_ratio_tracks(items, 10)
    assert sum(item.id <= 20 for item in selected) == 6
    assert sum(21 <= item.id <= 40 for item in selected) == 3
    assert sum(item.id >= 41 for item in selected) == 1


def test_m3u_metadata_newlines_do_not_create_extra_entries(config, tmp_path):
    item = track(1, tmp_path / 'fixture.mp3')
    Path(item.local_path).touch()
    item.name = 'first\n#injected'
    path, count = DJCurator(config)._export_to_m3u([item])
    lines = Path(path).read_text(encoding='utf-8-sig').splitlines()
    assert count == 1 and len(lines) == 3
    assert lines[1] == '#EXTINF:-1,fixture - first #injected'


@pytest.mark.parametrize('intensity', [[], {}, 123])
def test_bad_scene_intensity_returns_validation_error(config, intensity):
    config['scenes']['focus']['intensity'] = intensity
    assert any('intensity' in error for error in cli.validate_config(config, 'scene'))


def test_explicit_intensity_overrides_scene_default(runtime, config, tmp_path, monkeypatch):
    temp_root, launch = runtime
    write_library(Path(config['musicbee']['xml_path']), [
        song(tmp_path / 'quiet.mp3', track_id=1, bpm=80),
        song(tmp_path / 'fast.mp3', track_id=2, bpm=150),
    ])
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', '夜间思考', '--intensity', 'high'])
    cli.main()
    launch.assert_called_once()
    task = next(temp_root.iterdir())
    queue = (task / 'queue.m3u').read_text(encoding='utf-8-sig')
    assert 'fast.mp3' in queue and 'quiet.mp3' not in queue
    cli.cleanup_task(task)


def test_cleanup_rejects_missing_marker_and_directory_entries(runtime):
    temp_root, _ = runtime
    task = temp_root / 'musicbee-dj-test'
    task.mkdir()
    with pytest.raises(ValueError, match='marker'):
        cli.cleanup_task(task)
    (task / cli.TASK_MARKER).write_text('1\n', encoding='utf-8')
    (task / 'queue.m3u').mkdir()
    with pytest.raises(ValueError, match='unrecognized'):
        cli.cleanup_task(task)
    assert (task / 'queue.m3u').is_dir()


def test_cleanup_rejects_links_before_touching_entries(runtime, monkeypatch):
    temp_root, _ = runtime
    task = temp_root / 'musicbee-dj-test'
    task.mkdir()
    monkeypatch.setattr(Path, 'is_symlink', lambda _: True)
    with pytest.raises(ValueError, match='linked'):
        cli.cleanup_task(task)
    assert task.exists()


@pytest.mark.parametrize(('phrase', 'expected'), [
    ('workout music', 'energy'), ('housework music', 'energy'),
    ('不要助眠，我要运动', 'energy'), ('播放适合夜间思考的音乐', 'focus'),
])
def test_scene_phrase_boundaries_and_negation(config, phrase, expected):
    assert DJCurator(config)._resolve_scene_name(phrase)[0] == expected


def test_conflicting_scene_clauses_not_resolved_arbitrarily(config):
    assert DJCurator(config)._resolve_scene_name('阅读，运动')[0] not in config['scenes']


@pytest.mark.parametrize(('genre', 'allowed'), [
    ('Jazz', False), ('Classical', False), ('Jazz; Vocal', False),
    ('Jazz; Instrumental', True), ('Instrumental; Vocal', False), ('纯音乐', True),
])
def test_strict_no_vocals_requires_positive_tags(config, genre, allowed):
    config['request'] = {'no_vocals': True}
    item = track(1)
    item.genre = genre
    assert bool(DJCurator(config)._filter_by_intensity([item], 'normal')) == allowed


def test_explicit_genre_and_artist_exclusions(config):
    item = track(1)
    config['request'] = {'exclude_genres': ['爵士']}
    assert not DJCurator(config)._filter_by_intensity([item], 'low')
    config['request'] = {'exclude_artists': ['fixture']}
    assert not DJCurator(config)._filter_by_intensity([item], 'low')


@pytest.mark.parametrize(('minutes', 'expected_count'), [(3, 1), (4, 2)])
def test_whole_track_duration_budget_excludes_unknowns(config, tmp_path, minutes, expected_count):
    songs = [song(tmp_path / f'budget-{i}.mp3', track_id=i) for i in range(1, 4)]
    songs[0]['Total Time'] = 120000
    songs[1]['Total Time'] = 120000
    write_library(Path(config['musicbee']['xml_path']), songs)
    config['request'] = {'minutes': minutes}
    result = DJCurator(config).generate_m3u('scene', 'focus', 'low')
    assert result.exported_tracks == expected_count
    assert result.total_duration_ms <= minutes * 60000
    assert result.unknown_duration_tracks == 0


def test_unknown_duration_only_cannot_claim_time_budget(config):
    config['request'] = {'minutes': 60}
    assert DJCurator(config).generate_m3u('scene', 'focus', 'low') is None


@pytest.mark.parametrize('minutes', ['0', '-1', 'nan', 'inf'])
def test_invalid_duration_cli_rejected_before_io(runtime, monkeypatch, minutes):
    _, launch = runtime
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', 'focus', '--minutes', minutes])
    monkeypatch.setattr(cli, 'load_config', Mock(side_effect=AssertionError('no config access')))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    launch.assert_not_called()


def test_constraints_cannot_be_silently_ignored_for_existing_playlist(runtime, monkeypatch):
    _, launch = runtime
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'playlist', '--value', 'fixture', '--no-vocals'])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    launch.assert_not_called()
