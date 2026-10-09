"""Sanitized MusicBee 3.7 XML shapes, including localized and numbered tag fields."""
import json
from pathlib import Path
import plistlib

from test_runtime import config, track
from src.core.parser import MusicBeeParser
from src.core.curator import DJCurator


def load_record(tmp_path, record):
    audio = tmp_path / 'fixture.mp3'
    audio.touch()
    data = {'Track ID': 1, 'Name': '示例作品 I', 'Location': audio.as_uri(), 'Total Time': 120000, **record}
    xml = tmp_path / 'localized.xml'
    with xml.open('wb') as handle:
        plistlib.dump({'Tracks': {'1': data}, 'Playlists': []}, handle, sort_keys=False)
    return MusicBeeParser(str(xml)).load_library()[0]


def test_localized_actual_export_contract(tmp_path):
    item = load_record(tmp_path, {'演出者': '示例艺人甲', '专辑': '示例专辑', '流派': 'Classical',
                                  '语言': 'und', 'Composer': '示例作曲者', '作品': '示例作品', '乐章名称': 'I. 示例乐章'})
    assert item.artist == '示例艺人甲' and item.genre == 'Classical'
    assert item.album == '示例专辑' and item.language == 'und'
    assert item.composer == '示例作曲者' and item.work == '示例作品'
    assert item.movement_name == 'I. 示例乐章'
    assert item.bpm == 0


def test_numbered_values_augment_base_and_deduplicate_case(tmp_path):
    item = load_record(tmp_path, {'演出者': 'A; B', 'Artist1': 'b', 'Artist2': 'C', 'Artist10': 'J',
                                 '流派': 'Jazz', 'Genre1': 'Instrumental', 'Genre2': 'jazz'})
    assert item.artist == 'A; B; C; J'
    assert item.genre == 'Jazz; Instrumental'


def test_english_priority_and_existing_alias_compatibility(tmp_path):
    item = load_record(tmp_path, {'Artist': 'Canonical', '演出者': 'Alternate', 'Genre': 'Rock', '流派': 'Jazz'})
    assert item.artist == 'Canonical' and item.genre == 'Rock'
    second = load_record(tmp_path, {'艺术家': 'Earlier Alias', '名称': '备用名称'})
    assert second.artist == 'Earlier Alias'


def test_real_name_punctuation_not_split_as_artist_values(tmp_path):
    item = load_record(tmp_path, {'演出者': 'Earth, Wind & Fire; 示例艺人乙'})
    assert DJCurator._artist_keys(item) == {'earth, wind & fire', '示例艺人乙'}


def test_legacy_region_labels_do_not_infer_language_or_style(tmp_path):
    item = load_record(tmp_path, {'演出者': '示例艺人', '流派': 'France'})
    assert item.genre == 'France' and item.language == ''


def test_genre_numbered_only_and_missing_artist_remain_honest(tmp_path):
    item = load_record(tmp_path, {'Genre1': 'Ambient', 'Genre2': 'Instrumental'})
    assert item.genre == 'Ambient; Instrumental' and item.artist == 'Unknown'


def test_collaboration_members_share_spacing_identity(config):
    config['request'] = {'seed': 11}
    items = [track(i, bpm=0) for i in range(1, 9)]
    items[0].artist = 'A'
    items[1].artist = 'A; B'
    for item in items[2:]:
        item.artist = f'other-{item.id}'
        item.album = f'album-{item.id}'
    dj = DJCurator(config)
    flow = dj._build_energy_curve(items, 'focus', 'low')
    assert dj.sequence_relaxations == 0
    for index, item in enumerate(flow):
        prior = {artist for old in flow[max(0, index - 2):index] for artist in dj._artist_keys(old)}
        assert not dj._artist_keys(item).intersection(prior)


def test_artist_order_does_not_duplicate_recording_identity():
    first, second = track(1), track(2)
    first.artist, second.artist = 'A; B', 'B; A'
    first.name = second.name = '示例作品 II'
    assert DJCurator._recording_key(first) == DJCurator._recording_key(second)


def test_classical_generic_titles_are_not_merged_without_work_identity():
    first, second = track(1), track(2)
    first.genre = second.genre = 'Classical'
    first.name = second.name = 'Allegro'
    assert DJCurator._recording_key(first) != DJCurator._recording_key(second)


def test_work_and_movement_context_disambiguates_recordings():
    first, second = track(1), track(2)
    first.genre = second.genre = 'Classical'
    first.name = second.name = 'Allegro'
    first.work, second.work = 'Work One', 'Work Two'
    first.movement_name = second.movement_name = 'I'
    assert DJCurator._recording_key(first) != DJCurator._recording_key(second)
    second.work = first.work
    second.name = 'Allegro (2019 Remastered)'
    assert DJCurator._recording_key(first) == DJCurator._recording_key(second)


def test_cached_tracks_without_new_optional_fields_are_compatible(config, monkeypatch):
    parser = MusicBeeParser(config['musicbee']['xml_path'], config['cache']['db_path'])
    item = track(1)
    old_fields = {key: value for key, value in item.__dict__.items()
                  if key not in {'language', 'composer', 'work', 'movement_name', 'dj_vocals', 'dj_energy', 'dj_scene', 'mood', 'tempo'}}
    Path(parser.cache_path).write_text(json.dumps({'version': 1, 'source': parser._source_identity(),
                                                 'tracks': [old_fields]}), encoding='utf-8')
    monkeypatch.setattr(parser, '_parse_and_cache_xml', lambda *args: (_ for _ in ()).throw(AssertionError('cache should load')))
    restored = parser.load_library()[0]
    assert restored.language == restored.work == restored.movement_name == restored.dj_vocals == restored.dj_energy == restored.dj_scene == restored.mood == restored.tempo == ''


def test_verified_custom_vocals_export_without_genre(tmp_path):
    item = load_record(tmp_path, {'演出者': '示例艺人', 'DJ_VOCALS': 'unknown'})
    assert item.dj_vocals == 'unknown'
    assert item.genre == 'Unknown'
    assert DJCurator._vocal_status(item) == 'unknown'


def test_custom_vocals_override_conflicting_legacy_genre(tmp_path):
    for explicit, genre, expected in [('instrumental', 'Opera', 'instrumental'),
                                      ('vocal', 'Instrumental', 'vocal'),
                                      ('unknown', 'Instrumental', 'unknown'),
                                      (' VOCAL ', 'Instrumental', 'vocal')]:
        item = load_record(tmp_path, {'DJ_VOCALS': explicit, 'Genre': genre})
        assert DJCurator._vocal_status(item) == expected


def test_invalid_vocals_never_use_legacy_genre_as_override(tmp_path):
    for explicit in ['non-vocal', 'vocal; instrumental', 'not instrumental', 'music', '有人声']:
        item = load_record(tmp_path, {'DJ_VOCALS': explicit, 'Genre': 'Instrumental'})
        assert DJCurator._vocal_status(item) == 'unknown'


def test_missing_or_empty_vocals_preserve_legacy_fallback(tmp_path):
    for fields in [{}, {'DJ_VOCALS': ''}, {'DJ_VOCALS': '   '}]:
        item = load_record(tmp_path, {'Genre': 'Instrumental', **fields})
        assert item.dj_vocals == ''
        assert DJCurator._vocal_status(item) == 'instrumental'


def test_no_vocals_gate_uses_custom_field_without_genre(config):
    config['request'] = {'no_vocals': True}
    items = [track(i) for i in range(1, 5)]
    for item, value in zip(items, ['instrumental', 'vocal', 'unknown', 'not instrumental']):
        item.genre = 'Unknown'
        item.dj_vocals = value
    assert [item.id for item in DJCurator(config)._filter_by_intensity(items, 'normal')] == [1]
