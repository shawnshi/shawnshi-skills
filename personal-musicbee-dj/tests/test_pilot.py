"""Pilot output tests use synthetic XML/files, with no MusicBee settings or audio tag writes."""
import csv
from pathlib import Path

import pytest

from test_runtime import config, track
from src.pilot import create_pilot, excel_safe, file_hash, select_sample


def test_pilot_preserves_source_and_leaves_proposed_tags_blank(config, tmp_path):
    source = Path(config['musicbee']['xml_path'])
    before = file_hash(source)
    output = tmp_path / 'pilot'
    report = create_pilot(config, output)
    assert report['mode'] == 'review_only_no_music_or_settings_writes'
    assert report['source_xml_unchanged'] and report['sample_file_stat_unchanged']
    assert file_hash(source) == before and report['sample_rows'] == 1
    with (output / 'review-only.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]['proposed_genre'] == rows[0]['proposed_language'] == rows[0]['proposed_vocals'] == ''
    assert rows[0]['review_status'] == 'needs_owner_review'
    assert rows[0]['xml_bpm'] == '80'
    assert not Path(config['cache']['db_path']).exists()


def test_existing_output_folder_is_not_overwritten(config, tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    original = output / 'user-file.txt'
    original.write_text('preserve', encoding='utf-8')
    with pytest.raises(ValueError, match='new'):
        create_pilot(config, output)
    assert original.read_text(encoding='utf-8') == 'preserve'


@pytest.mark.parametrize('value', ['=1+1', '+cmd', '-cmd', '@formula', '  =formula', '\tformula'])
def test_review_csv_formula_text_is_inert(value):
    assert excel_safe(value).startswith("'")


def test_sample_is_bounded_and_file_deduplicated(tmp_path):
    items = []
    for i in range(1, 31):
        path = tmp_path / f'{i}.mp3'
        path.touch()
        item = track(i, path)
        item.genre = 'Classical; Instrumental'
        item.movement_name = f'Movement {i}'
        item.artist = 'A; B'
        items.append(item)
    selected, counts = select_sample(items, per_group=2)
    assert all(count <= 2 for count in counts.values())
    assert len(selected) <= 12
    assert len({item.local_path for _, item in selected}) == len(selected)
    assert counts['movement_metadata'] == counts['multi_artist'] == counts['classical'] == 2


@pytest.mark.parametrize('count', [0, 9, -1, True])
def test_invalid_per_group_does_not_scan_or_write(count):
    with pytest.raises(ValueError, match='per-group'):
        select_sample([], count)
