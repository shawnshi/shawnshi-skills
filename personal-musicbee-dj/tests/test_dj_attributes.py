"""Synthetic contract tests: optional DJ tags; no real library read or MusicBee launch."""
import pytest
from test_runtime import config, track
from test_export_contract import load_record
from src.core.curator import DJCurator


def item(index, *, scene='', energy='', vocals='', genre='Unknown', bpm=0):
    value = track(index, bpm=bpm)
    value.genre = genre
    value.dj_scene = scene
    value.dj_energy = energy
    value.dj_vocals = vocals
    value.artist = f'fixture-artist-{index}'
    value.album = f'fixture-album-{index}'
    return value


def test_optional_fields_and_numbered_scene_export(tmp_path):
    value = load_record(tmp_path, {'DJ_ENERGY': ' medium ', 'DJ_SCENE': 'focus; coding',
                                   'DJ_SCENE1': 'FOCUS', 'DJ_SCENE10': 'relax', 'DJ_SCENE2': 'pop'})
    assert value.dj_energy == 'medium'
    assert value.dj_scene == 'focus; coding; pop; relax'
    missing = load_record(tmp_path, {})
    assert missing.dj_energy == missing.dj_scene == ''


@pytest.mark.parametrize('scene', ['focus', 'FOCUS', ' coding; focus ', 'focus;focus'])
def test_scene_matches_exact_explicit_metadata_without_genre(config, scene):
    dj = DJCurator(config)
    values = [item(1, scene=scene), item(2, scene='pop', genre='Ambient')]
    assert [t.id for t in dj._retrieve_base_tracks(values, 'scene', 'focus')[0]] == [1]


@pytest.mark.parametrize('scene', ['unknown', 'not focus', 'focus,relax', 'unfocused', 'focus;bad', '专注'])
def test_invalid_or_unknown_scene_never_uses_genre_fallback(config, scene):
    value = item(1, scene=scene, genre='Ambient')
    assert DJCurator(config)._retrieve_base_tracks([value], 'scene', 'focus')[0] == []


def test_missing_scene_retains_legacy_fallback(config):
    values = [item(1, genre='Ambient'), item(2, scene='   ', genre='Ambient')]
    assert [t.id for t in DJCurator(config)._retrieve_base_tracks(values, 'scene', 'focus')[0]] == [1, 2]


def test_genre_request_does_not_treat_scene_as_genre(config):
    values = [item(1, scene='focus', genre='Rock'), item(2, scene='focus')]
    assert [t.id for t in DJCurator(config)._retrieve_base_tracks(values, 'genre', 'Rock')[0]] == [1]


@pytest.mark.parametrize(('energy', 'intensity', 'expected'), [
    ('low', 'low', True), (' LOW ', 'low', True), ('medium', 'low', False),
    ('high', 'low', False), ('high', 'high', True), ('medium', 'high', False),
    ('low', 'high', False), ('unknown', 'low', False), ('unknown', 'high', False),
    ('low;high', 'low', False), ('not high', 'high', False), ('低', 'low', False),
    ('unknown', 'normal', True), ('medium', 'normal', True),
])
def test_explicit_energy_gate_overrides_conflicting_bpm_and_genre(config, energy, intensity, expected):
    value = item(1, energy=energy, genre='Metal', bpm=170 if intensity == 'low' else 30)
    assert bool(DJCurator(config)._filter_by_intensity([value], intensity)) is expected


def test_missing_energy_retains_legacy_bpm_gate(config):
    values = [item(1, bpm=60), item(2, energy=' ', bpm=170), item(3, bpm=0)]
    assert [t.id for t in DJCurator(config)._filter_by_intensity(values, 'low')] == [1, 3]


def test_explicit_energy_never_bypasses_exclusions_or_vocals(config):
    config['request'] = {'no_vocals': True, 'exclude_artists': ['fixture-artist-1']}
    values = [item(1, energy='low', vocals='instrumental'),
              item(2, energy='low', vocals='vocal'),
              item(3, energy='low', vocals='unknown'),
              item(4, energy='low', vocals='instrumental')]
    assert [t.id for t in DJCurator(config)._filter_by_intensity(values, 'low')] == [4]


def test_energy_ramp_with_unknown_bpm_uses_reviewed_levels(config):
    config['request'] = {'seed': 5}
    values = [item(i, energy=energy) for i, energy in enumerate(
        ['high', 'low', 'medium', 'unknown', 'low', 'high', 'medium'], 1)]
    dj = DJCurator(config)
    flow = dj._build_energy_curve(values, 'energy', 'normal')
    assert [dj._energy_level(t) for t in flow] == [1, 1, 2, 2, 3, 3, 0]
    assert all(t.bpm == 0 for t in flow)
    assert len({t.id for t in flow}) == len(values)


def test_energy_continuity_still_respects_collaboration_spacing(config):
    config['request'] = {'seed': 9}
    values = [item(i, energy=energy) for i, energy in enumerate(
        ['low', 'low', 'medium', 'high', 'medium', 'high', 'low', 'medium'], 1)]
    values[0].artist = 'A'
    values[1].artist = 'A; B'
    dj = DJCurator(config)
    flow = dj._build_energy_curve(values, 'focus', 'normal')
    assert dj.sequence_relaxations == 0
    for i, value in enumerate(flow):
        previous = {a for old in flow[max(0,i-2):i] for a in dj._artist_keys(old)}
        assert not dj._artist_keys(value).intersection(previous)


def test_whole_selection_pipeline_without_genre(config):
    config['request'] = {'no_vocals': True}
    values = [item(1, scene='focus', energy='low', vocals='instrumental'),
              item(2, scene='pop', energy='low', vocals='instrumental'),
              item(3, scene='focus', energy='high', vocals='instrumental'),
              item(4, scene='focus', energy='unknown', vocals='instrumental'),
              item(5, scene='focus', energy='low', vocals='vocal')]
    dj = DJCurator(config)
    matched, _, _, _ = dj._retrieve_base_tracks(values, 'scene', 'focus')
    assert [t.id for t in dj._filter_by_intensity(matched, 'low')] == [1]


def test_genre_reset_does_not_merge_ambiguous_movement_titles():
    a, b = item(1), item(2)
    a.name = b.name = 'Allegro'
    a.artist = b.artist = 'fixture'
    assert DJCurator._recording_key(a) != DJCurator._recording_key(b)
    a.work = b.work = 'Work I'
    a.movement_name = b.movement_name = 'I'
    assert DJCurator._recording_key(a) == DJCurator._recording_key(b)


def test_work_metadata_retains_conservative_identity_after_genre_reset():
    a, b = item(1, genre='Rock'), item(2, genre='Rock')
    a.name = b.name = 'I'
    a.artist = b.artist = 'fixture'
    a.work = b.work = 'Work I'
    assert DJCurator._recording_key(a) != DJCurator._recording_key(b)
