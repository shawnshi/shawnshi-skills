"""Bounded metadata inventory only; no audio inference, tag writes or player commands."""
import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cli import load_config, resolve_config_paths
from src.core.parser import MusicBeeParser

FIELDS = {
    'tempo': ('Tempo', 'Speed', '速度', '节奏'),
    'bpm': ('BPM', 'TBPM'),
    'mood': ('Mood', 'TMOO', '情绪', '情感'),
    'language': ('Language', 'TLAN', '语言'),
    'DJ_VOCALS': ('DJ_VOCALS',),
    'DJ_ENERGY': ('DJ_ENERGY',),
    'DJ_SCENE': ('DJ_SCENE',),
}
# These are candidate read aliases, not verified MusicBee write mappings.
MAPPING_PENDING = {'tempo', 'mood', 'language'}
SUPPORTED = {'.mp3': 'mp3', '.flac': 'flac'}
DEFAULT_SCENES = {'focus', 'coding', 'relax', 'energy', 'pop'}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def field_for_key(key):
    folded = key.casefold()
    if folded.startswith('txxx:'):
        folded = folded[5:]
    for field, aliases in FIELDS.items():
        if folded in {alias.casefold() for alias in aliases}:
            return field
    if re.fullmatch(r'dj_scene\d+', folded):
        return 'DJ_SCENE'
    return None


def collect_fields(tags):
    result = {field: [] for field in FIELDS}
    for key, value in tags.items():
        field = field_for_key(key)
        if field:
            result[field].append({'key': key, 'value': value})
    return result


def inventory_xml(source, limit):
    """Retain only the bounded sample and target-field counts, never a library cache."""
    selected, priority, counts, seen_paths = [], [], Counter(), set()
    total = 0
    stack, tracks_root, pending_parent, found = [], None, None, False
    for event, elem in ET.iterparse(source, events=('start', 'end')):
        if event == 'start':
            parent = stack[-1] if stack else None
            if pending_parent is not None and parent is pending_parent:
                if elem.tag != 'dict':
                    raise ValueError('Root Tracks value must be a dictionary')
                tracks_root, pending_parent, found = elem, None, True
            stack.append(elem)
            continue
        parent = stack[-2] if len(stack) > 1 else None
        if tracks_root is not None and parent is tracks_root:
            if elem.tag == 'dict':
                total += 1
                data, key = {}, None
                for child in elem:
                    if child.tag == 'key':
                        key = child.text
                    elif key is not None:
                        if key in {'Location', 'Track ID', '轨迹 ID'} or field_for_key(key):
                            if key in data:
                                raise ValueError('Duplicate target XML key')
                            data[key] = child.text or '' if child.tag in {'string', 'integer', 'real'} else None
                        key = None
                fields = collect_fields(data)
                for field, entries in fields.items():
                    for entry in entries:
                        counts[entry['key']] += 1
                location = data.get('Location')
                if isinstance(location, str) and location:
                    try:
                        path = MusicBeeParser._location_to_path(location)
                    except ValueError:
                        path = ''
                    identity = os.path.normcase(os.path.normpath(path))
                    if path and identity not in seen_paths:
                        # Keep only bounded path sets. Prioritize tracks with observed target tags.
                        row = {'track_id': data.get('Track ID', data.get('轨迹 ID', '')),
                               'source_path': path, 'xml_fields': fields}
                        pool = priority if any(fields.values()) else selected
                        if len(pool) < limit:
                            pool.append(row)
                            seen_paths.add(identity)
            elem.clear()
            parent.remove(elem)
        elif tracks_root is None or elem is tracks_root:
            if (elem.tag == 'key' and elem.text == 'Tracks' and len(stack) == 3
                    and stack[0].tag == 'plist' and parent.tag == 'dict'):
                pending_parent = parent
            if elem is tracks_root:
                tracks_root = None
            elem.clear()
        stack.pop()
    if not found:
        raise ValueError('Library XML has no root Tracks dictionary')
    return (priority + selected)[:limit], total, dict(sorted(counts.items()))


def local_file(path):
    from src.core.local_paths import local_regular_file
    return local_regular_file(path)


def probe_file(path, executable, timeout=10):
    """FFprobe is an observation source, not an authoritative writer-format validator."""
    try:
        path = local_file(path)
        expected = SUPPORTED.get(path.suffix.casefold())
        if not expected:
            return {'status': 'unsupported_format', 'fields': collect_fields({})}
        if not executable:
            return {'status': 'dependency_missing', 'error_type': 'FFprobeUnavailable',
                    'fields': collect_fields({})}
        before = path.stat()
        # Network protocols are denied even if an apparent audio file contains a playlist.
        completed = subprocess.run(
            [str(executable), '-v', 'error', '-protocol_whitelist', 'file',
             '-show_entries', 'format=format_name:format_tags:stream_tags', '-of', 'json', str(path)],
            capture_output=True, encoding='utf-8', errors='strict', timeout=timeout, check=False)
        if completed.returncode:
            # Preserve code/type, not stderr that can contain unrelated embedded metadata.
            return {'status': 'read_error', 'error_type': 'FFprobeExit',
                    'returncode': completed.returncode, 'fields': collect_fields({})}
        payload = json.loads(completed.stdout)
        format_info = payload.get('format', {})
        if expected not in format_info.get('format_name', '').split(','):
            return {'status': 'container_mismatch', 'fields': collect_fields({})}
        tags = dict(format_info.get('tags', {}))
        fields = collect_fields(tags)
        for stream in payload.get('streams', []):
            for field, entries in collect_fields(stream.get('tags', {})).items():
                fields[field].extend(entries)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return {'status': 'changed_during_read', 'fields': collect_fields({})}
        return {'status': 'observed', 'container': expected, 'fields': fields,
                'stat_unchanged': True}
    except subprocess.TimeoutExpired:
        return {'status': 'read_error', 'error_type': 'TimeoutExpired', 'fields': collect_fields({})}
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError) as exc:
        return {'status': 'read_error', 'error_type': type(exc).__name__, 'fields': collect_fields({})}


def value_state(field, entries, scenes):
    if any(not isinstance(entry['value'], str) for entry in entries):
        return 'invalid', None
    values = [entry['value'].strip() for entry in entries if entry['value'].strip()]
    if not values:
        return 'not_observed', None
    folded = [value.casefold() for value in values]
    if set(folded) == {'unknown'}:
        return 'unknown', 'unknown'
    if field == 'bpm':
        try:
            parsed = [Decimal(value) for value in values]
            if any(not number.is_finite() or number <= 0 for number in parsed):
                return 'invalid', None
            numbers = set(parsed)
        except InvalidOperation:
            return 'invalid', None
        return ('present', str(next(iter(numbers)).normalize())) if len(numbers) == 1 else ('conflict', None)
    if field == 'DJ_SCENE':
        parts = {part.strip() for value in folded for part in value.split(';') if part.strip()}
        if not parts or not parts.issubset(scenes) or any(not part.strip() for v in folded for part in v.split(';')):
            return 'invalid', None
        return 'present', '; '.join(sorted(parts))
    if field in {'mood', 'language'}:
        from src.core.attributes import MOOD_ALIASES, LANGUAGE_ALIASES, token
        aliases = MOOD_ALIASES if field == 'mood' else LANGUAGE_ALIASES
        comparable = []
        for value in folded:
            mapped = [aliases.get(token(part)) for part in value.split(';')]
            # Unrecognised text remains evidence; never discard it to force equality.
            comparable.append('; '.join(sorted(set(mapped))) if all(mapped) else value)
        folded = comparable
    allowed = {'DJ_VOCALS': {'vocal', 'instrumental'}, 'DJ_ENERGY': {'low', 'medium', 'high'}}
    if field in allowed and not set(folded).issubset(allowed[field]):
        return 'invalid', None
    if len(set(folded)) != 1:
        return 'conflict', None
    return ('present_unvalidated' if field in MAPPING_PENDING else 'present'), folded[0]


def reconcile(field, xml_entries, file_entries, file_status, scenes):
    xml_state, xml_value = value_state(field, xml_entries, scenes)
    file_state, file_value = value_state(field, file_entries, scenes)
    if file_status != 'observed':
        status, action = 'verification_blocked', 'resolve_file_read'
    elif 'conflict' in {xml_state, file_state} or (
            xml_value is not None and file_value is not None and xml_value != file_value):
        status, action = 'conflict', 'review_conflict'
    elif 'invalid' in {xml_state, file_state}:
        status, action = 'invalid_existing', 'review_existing_no_overwrite'
    elif 'unknown' in {xml_state, file_state}:
        status, action = 'unknown_existing', 'preserve_unknown'
    elif xml_state == 'not_observed' and file_state != 'not_observed':
        status, action = 'xml_export_gap', 'preserve_file_value_check_export'
    elif file_state == 'not_observed' and xml_state != 'not_observed':
        status, action = 'xml_only_value', 'review_storage_no_overwrite'
    elif xml_state == file_state == 'not_observed':
        status = 'not_observed_both'
        action = 'verify_mapping' if field in MAPPING_PENDING else 'candidate_for_later_audio_analysis'
    else:
        status, action = 'existing', 'preserve_existing'
    return {'status': status, 'action': action, 'xml_state': xml_state, 'file_state': file_state,
            'mapping': 'pending' if field in MAPPING_PENDING else 'probe_only_not_write_authority',
            'proposed_value': None}


def create_preview(source, limit=12, scenes=None, executable=None, *, allow_large_batch=False):
    if type(limit) is not int or limit < 1 or (not allow_large_batch and limit > 48):
        raise ValueError('limit must be a positive integer' if allow_large_batch else 'limit must be an integer from 1 to 48')
    scenes = set(scenes if scenes is not None else DEFAULT_SCENES)
    if not scenes or not scenes.issubset(DEFAULT_SCENES):
        raise ValueError('Scene vocabulary must be a nonempty subset of the current DJ_SCENE contract')
    source = local_file(source)
    started = time.monotonic()
    before = file_hash(source)
    rows, total, counts = inventory_xml(source, limit)
    file_counts, status_counts = Counter(), Counter()
    for row in rows:
        file_result = probe_file(row['source_path'], executable)
        row['file_probe'] = file_result
        row['fields'] = {}
        for field in FIELDS:
            file_entries = file_result['fields'][field]
            for entry in file_entries:
                file_counts[entry['key']] += 1
            result = reconcile(field, row['xml_fields'][field], file_entries, file_result['status'], scenes)
            row['fields'][field] = result
            status_counts[result['status']] += 1
    after = file_hash(source)
    if before != after:
        raise ValueError('Source XML changed during preview; discard results and wait for export to settle')
    summary = {
        'mode': 'metadata_preview_only', 'audio_inference': 'not_implemented',
        'music_writes': False, 'player_commands': False,
        'source_xml': str(source), 'source_sha256_before': before, 'source_sha256_after': after,
        'source_xml_unchanged': True, 'tracks_total': total, 'sample_rows': len(rows),
        'sample_policy': 'target_fields_first_then_xml_order_not_statistically_representative',
        'sample_probe_complete': bool(rows) and all(row['file_probe']['status'] == 'observed' for row in rows),
        'xml_field_occurrences_all_tracks': counts,
        'file_field_occurrences_sample_only': dict(sorted(file_counts.items())),
        'field_status_counts_sample_only': dict(sorted(status_counts.items())),
        'file_probe_status_counts': dict(Counter(row['file_probe']['status'] for row in rows)),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'notes': ['Unobserved is not proven missing: FFprobe may not expose every native tag.',
                  'Tempo/mood/language mappings require MusicBee round-trip verification.',
                  'Unknown and all existing nonempty values are protected; no candidates are fabricated.',
                  'Audio-file stat checks are not audio-content hash verification.'],
    }
    return {'summary': summary, 'rows': rows}


def write_report(report, output_dir):
    output_dir = Path(output_dir)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (output_dir.parent.resolve() != temp_root or not output_dir.name.startswith('musicbee-preview-')
            or output_dir.exists() or output_dir.is_symlink()):
        raise ValueError('Output must be a new musicbee-preview-* directory directly under system TEMP')
    output_dir.mkdir(exist_ok=False)
    try:
        with (output_dir / 'preview.json').open('x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        with (output_dir / 'review-only.csv').open('x', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['track_id', 'source_path', 'field', 'xml_values', 'file_values',
                             'status', 'action', 'proposed_value', 'audio_status'])
            for row in report['rows']:
                for field, result in row['fields'].items():
                    values = [row['track_id'], row['source_path'], field,
                              json.dumps(row['xml_fields'][field], ensure_ascii=False),
                              json.dumps(row['file_probe']['fields'][field], ensure_ascii=False),
                              result['status'], result['action'],
                              result.get('proposed_value') if result.get('proposed_value') is not None else '',
                              result.get('audio_status', '')]
                    writer.writerow(["'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@'))
                                     or str(v).startswith(('\t', '\r', '\n')) else str(v) for v in values])
    except (OSError, ValueError, TypeError):
        # Remove only the two files exclusively created by this invocation, never arbitrary contents.
        for name in ('preview.json', 'review-only.csv'):
            (output_dir / name).unlink(missing_ok=True)
        output_dir.rmdir()
        raise
    return output_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml', type=Path, help='Default: configured MusicBee XML export')
    parser.add_argument('--limit', type=int, default=12, help='File probes: 1..48; default 12')
    parser.add_argument('--output-dir', type=Path, help='Optional new musicbee-preview-* directory under TEMP')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        config = resolve_config_paths(load_config(root / 'config.yaml'), root)
        source = args.xml or Path(config['musicbee']['xml_path'])
        report = create_preview(source, args.limit, config.get('scenes', {}).keys(), shutil.which('ffprobe'))
        if args.output_dir:
            report['summary']['output_dir'] = str(write_report(report, args.output_dir))
    except (OSError, ValueError, ET.ParseError) as exc:
        parser.exit(1, f'Preview failed ({type(exc).__name__}): {exc}\n')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    if not report['rows'] or any(row['file_probe']['status'] != 'observed' for row in report['rows']):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
