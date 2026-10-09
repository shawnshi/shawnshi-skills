"""Assess owner-reviewed candidate CSV locally. Never authorize tag writes."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import re
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.core.attributes import MOOD_ALIASES, LANGUAGE_ALIASES

ALLOWED = {
    'DJ_VOCALS': {'vocal', 'instrumental', 'unknown'},
    'DJ_ENERGY': {'low', 'medium', 'high', 'unknown'},
    'mood': set(MOOD_ALIASES.values()) | {'unknown'},
    'DJ_SCENE': {'focus', 'coding', 'relax', 'energy', 'pop'},
}


def normalized_value(field, value):
    value = value.strip().casefold()
    if field in {'DJ_VOCALS', 'DJ_ENERGY'}:
        if value not in ALLOWED[field]:
            raise ValueError('Invalid owner label')
    elif field == 'mood':
        if value == 'unknown':
            return value
        parts = [MOOD_ALIASES.get(part.strip()) for part in value.split(';')]
        if any(part is None for part in parts):
            raise ValueError('Invalid owner mood label')
        value = '; '.join(sorted({part for part in parts if part is not None}))
    elif field == 'DJ_SCENE':
        if value == 'unknown':
            return value
        parts = value.split(';')
        if any(not p.strip() or p.strip() not in ALLOWED[field] for p in parts):
            raise ValueError('Invalid scene label')
        value = '; '.join(sorted({p.strip() for p in parts}))
    elif field == 'language':
        if value == 'unknown':
            return value
        parts = [LANGUAGE_ALIASES.get(part.strip()) for part in value.split(';')]
        if any(part is None for part in parts):
            raise ValueError('Expected supported consumer language values')
        value = '; '.join(sorted({part for part in parts if part is not None}))
    elif field == 'bpm':
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError('Invalid owner BPM')
        value = str(number)
    else:
        raise ValueError('Field vocabulary not frozen; cannot calibrate')
    return value


def bounded_bytes(source, maximum):
    from src.core.local_paths import local_regular_file
    source = local_regular_file(source)
    with source.open('rb') as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Source oversized')
    return data


def worksheet_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def review_snapshot_rows(report):
    summary, rows = report.get('summary'), report.get('rows')
    if not isinstance(summary, dict) or summary.get('mode') != 'local_ai_candidate_review_only' or summary.get('automatic_tag_write_eligible') is not False:
        raise ValueError('Unsupported preview snapshot')
    if not isinstance(rows, list) or (summary.get('vocals_mode') != 'full' and len(rows) > 6):
        raise ValueError('Invalid preview row bounds')
    records = {}
    fields = {'tempo', 'bpm', 'mood', 'language', 'DJ_VOCALS', 'DJ_ENERGY', 'DJ_SCENE'}
    candidate_statuses = {'unreviewed_candidate', 'unreviewed_language_candidate', 'consistent_unreviewed_candidate'}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('source_path'), str) or not row['source_path'] or not isinstance(row.get('fields'), dict) or not set(row['fields']).issubset(fields):
            raise ValueError('Invalid preview track schema')
        for field, result in sorted(row['fields'].items()):
            if not isinstance(result, dict):
                raise ValueError('Invalid preview field schema')
            if result.get('status') != 'not_observed_both':
                continue
            status, value = result.get('audio_status'), result.get('proposed_value')
            if not isinstance(status, str) or (value is not None and status not in candidate_statuses):
                raise ValueError('Invalid candidate/status pair in preview')
            key = (worksheet_cell(row['source_path']), field)
            if key in records:
                raise ValueError('Duplicate track/field in preview')
            records[key] = (worksheet_cell(value if value is not None else ''), worksheet_cell(status))
    return records


def assess_review(source, preview_source=None, expected_preview_sha256=None):
    if preview_source is None or not isinstance(expected_preview_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_preview_sha256):
        raise ValueError('Original preview JSON and its recorded SHA256 are required')
    preview_data = bounded_bytes(preview_source, 2 * 1024 * 1024)
    if hashlib.sha256(preview_data).hexdigest() != expected_preview_sha256:
        raise ValueError('Preview checksum mismatch')
    try:
        snapshot = json.loads(preview_data.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid preview JSON') from exc
    if not isinstance(snapshot, dict):
        raise ValueError('Invalid preview JSON schema')
    expected_rows = review_snapshot_rows(snapshot)
    data = bounded_bytes(source, 1024 * 1024)
    reviewed, available, matches, confusion, errors, seen = Counter(), Counter(), Counter(), {}, [], set()
    bpm_errors = []
    rows = 0
    with io.StringIO(data.decode('utf-8-sig'), newline='') as handle:
        reader = csv.DictReader(handle)
        expected = {'source_path', 'field', 'candidate', 'status', 'owner_value', 'owner_reviewed'}
        if set(reader.fieldnames or []) != expected or len(reader.fieldnames or []) != len(expected):
            raise ValueError('Review CSV schema mismatch')
        for rows, row in enumerate(reader, 1):
            if rows > 500:
                raise ValueError('Review row bound exceeded')
            if None in row or any(v is None for v in row.values()):
                raise ValueError('Malformed review CSV row')
            key = (row['source_path'], row['field'])
            if key in seen:
                raise ValueError('Duplicate track/field review row')
            seen.add(key)
            if key not in expected_rows or (row['candidate'], row['status']) != expected_rows[key]:
                raise ValueError('Review prediction/status differs from original preview')
            confirmed = row['owner_reviewed'].strip().casefold()
            if confirmed in {'', 'no', 'false', '0'}:
                continue
            if confirmed not in {'yes', 'true', '1'}:
                errors.append({'row': rows, 'error': 'invalid_review_flag'})
                continue
            field = row['field']
            try:
                owner = normalized_value(field, row['owner_value'])
                candidate = normalized_value(field, row['candidate']) if row['candidate'].strip() else None
            except ValueError:
                errors.append({'row': rows, 'field': field, 'error': 'invalid_or_unfrozen_label'})
                continue
            reviewed[field] += 1
            if candidate is None:
                continue
            available[field] += 1
            matches[field] += candidate == owner
            confusion.setdefault(field, Counter())[(owner, candidate)] += 1
            if field == 'bpm':
                bpm_errors.append(abs(float(candidate) - float(owner)))
    metrics = {field: {'reviewed_rows': reviewed[field], 'candidate_rows': available[field],
                       'coverage': available[field] / reviewed[field],
                       'exact_match_rate_on_candidates': matches[field] / available[field] if available[field] else None,
                       'confusion': [{'owner': owner, 'candidate': candidate, 'count': count}
                                     for (owner, candidate), count in sorted(confusion.get(field, {}).items())]}
               for field in sorted(reviewed)}
    if seen != set(expected_rows):
        raise ValueError('Review track/field set differs from original preview')
    if data != bounded_bytes(source, 1024 * 1024) or preview_data != bounded_bytes(preview_source, 2 * 1024 * 1024):
        raise ValueError('Review CSV or preview changed while reading')
    return {'status': 'invalid_owner_review' if errors else ('assessed_small_sample_not_validated' if reviewed
                                                           else 'calibration_pending_no_owner_labels'),
            'source_sha256': hashlib.sha256(data).hexdigest(), 'source_unchanged': True,
            'preview_sha256': expected_preview_sha256,
            'preview_provenance': {key: snapshot['summary'].get(key) for key in
                                   ('source_sha256_before', 'model_manifest_sha256', 'prompt_sha256',
                                    'prompt_version', 'classification_rule_version', 'models', 'runtime_versions')},
            'rows_total': rows, 'reviewed_rows': sum(reviewed.values()), 'metrics': metrics,
            'bpm_mae': sum(bpm_errors) / len(bpm_errors) if bpm_errors else None,
            'label_errors': errors[:5], 'label_error_count': len(errors),
            'automatic_tag_write_eligible': False,
            'notes': ['This worksheet is a small biased sample, not proof of whole-library accuracy.',
                      'No calibration pass or CSV edit grants permission to write music tags.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-csv', type=Path, required=True)
    parser.add_argument('--preview-json', type=Path, required=True)
    parser.add_argument('--preview-sha256', required=True, help='SHA256 recorded when the preview was created')
    args = parser.parse_args()
    try:
        result = assess_review(args.review_csv, args.preview_json, args.preview_sha256)
    except (OSError, ValueError, UnicodeError, csv.Error) as exc:
        parser.exit(1, f'Calibration assessment failed ({type(exc).__name__}): {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['status'] != 'assessed_small_sample_not_validated' else 0


if __name__ == '__main__':
    raise SystemExit(main())
