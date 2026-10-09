"""Build a local review worksheet; never edit music tags, MusicBee settings or queues."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cli import load_config, resolve_config_paths
from src.core.curator import DJCurator
from src.core.parser import MusicBeeParser, MusicBeeParserError

LEGACY = {'chs', 'eng', 'jap', 'korean', 'france'}


def genre_tokens(track):
    return {value.strip().casefold() for value in track.genre.split(';') if value.strip()}


def groups():
    return [
        ('movement_metadata', lambda t: bool(t.work or t.movement_name)),
        ('multi_artist', lambda t: len(DJCurator._artist_keys(t)) > 1),
        ('classical', lambda t: any(value in t.genre.casefold() for value in ('classical', '古典'))),
        ('jazz', lambda t: any(value in t.genre.casefold() for value in ('jazz', '爵士'))),
        ('instrumental_ambient', lambda t: DJCurator._vocal_status(t) == 'instrumental' or 'ambient' in t.genre.casefold()),
        ('legacy_language_region', lambda t: bool(genre_tokens(t).intersection(LEGACY))),
    ]


def select_sample(library, per_group=5):
    if type(per_group) is not int or not 1 <= per_group <= 8:
        raise ValueError('per-group must be an integer from 1 to 8')
    ordered = sorted(library, key=lambda t: (t.id, os.path.normcase(t.local_path)))
    selected, paths = [], set()
    counts = Counter()
    for name, predicate in groups():
        for track in ordered:
            key = os.path.normcase(os.path.normpath(track.local_path))
            if key in paths or not predicate(track) or not track.is_valid:
                continue
            selected.append((name, track))
            paths.add(key)
            counts[name] += 1
            if counts[name] >= per_group:
                break
    return selected, {name: counts[name] for name, _ in groups()}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def excel_safe(value):
    text = str(value)
    # A review CSV is not an import format: prevent untrusted tag text becoming spreadsheet formulas.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


def create_pilot(config, output_dir, per_group=5):
    started = time.monotonic()
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError('Output directory must be new; existing files will not be overwritten')
    source = Path(config['musicbee']['xml_path'])
    before = file_hash(source)
    library = MusicBeeParser(str(source)).load_library()
    selected, group_counts = select_sample(library, per_group)
    if not selected:
        raise ValueError('No existing song files matched the pilot groups; no worksheet created')
    snapshots = {track.local_path: (Path(track.local_path).stat().st_size, Path(track.local_path).stat().st_mtime_ns)
                 for _, track in selected}
    after = file_hash(source)
    if before != after:
        raise ValueError('Source XML changed while reading; no worksheet created')

    output_dir.mkdir(parents=True, exist_ok=False)
    worksheet = output_dir / 'review-only.csv'
    fields = ['group', 'track_id', 'source_path', 'title', 'artist', 'album', 'original_genre',
              'existing_language', 'composer', 'work', 'movement_name', 'xml_bpm', 'duration_ms',
              'proposed_genre', 'proposed_language', 'proposed_vocals', 'proposed_energy',
              'proposed_scene', 'review_status']
    with worksheet.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for group, track in selected:
            writer.writerow([excel_safe(value) for value in [
                group, track.id, track.local_path, track.name, track.artist, track.album, track.genre,
                track.language, track.composer, track.work, track.movement_name,
                track.bpm if track.bpm > 0 else '', track.total_time if track.total_time > 0 else '',
                '', '', '', '', '', 'needs_owner_review',
            ]])
    summary = {
        'mode': 'review_only_no_music_or_settings_writes',
        'source_xml': str(source), 'source_sha256_before': before, 'source_sha256_after': after,
        'source_xml_unchanged': before == after,
        'tracks_total': len(library),
        'artist_unknown_count': sum(not DJCurator._artist_keys(track) for track in library),
        'multiple_artist_count': sum(len(DJCurator._artist_keys(track)) > 1 for track in library),
        'xml_bpm_known_count': sum(track.bpm > 0 for track in library),
        'sample_rows': len(selected), 'sample_group_counts': group_counts,
        'missing_groups': [name for name, count in group_counts.items() if count == 0],
        'sample_file_stat_unchanged': all((Path(path).stat().st_size, Path(path).stat().st_mtime_ns) == stat
                                        for path, stat in snapshots.items()),
        'worksheet_sha256': file_hash(worksheet), 'output_dir': str(output_dir),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'notes': [
            'Blank proposed fields are deliberate: language/region does not imply musical style or vocals.',
            'XML BPM absence does not prove audio-file tags lack BPM.',
            'Sample is not a complete-work playlist and must not be played as one.',
            'CSV is for human review only, may contain formula-safety apostrophes, and must not be imported as tags.',
            'File stats are a metadata check, not audio-content hash verification.',
        ],
    }
    with (output_dir / 'summary.json').open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    return summary


def main():
    parser = argparse.ArgumentParser(description='Prepare a bounded, local MusicBee tag-review pilot')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--per-group', type=int, default=5)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        config = resolve_config_paths(load_config(root / 'config.yaml'), root)
        summary = create_pilot(config, args.output_dir, args.per_group)
    except (OSError, ValueError, MusicBeeParserError) as exc:
        parser.exit(1, f'Pilot failed ({type(exc).__name__}): {exc}\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
