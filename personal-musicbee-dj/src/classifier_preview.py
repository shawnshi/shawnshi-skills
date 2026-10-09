"""Local seven-field candidate review, never music tag writes or transcript generation."""
import argparse
from collections import Counter
import csv
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cli import load_config, resolve_config_paths
from src.core.audio_analysis import read_duration, clip_plan, decode_clip, measure_clip, aggregate_bpm, AudioAnalysisError
from src.core.audio_classifier import OfflineClassifier, ClassifierError, validate_prompts
from src.core.attributes import LANGUAGE_ALIASES, MOOD_ALIASES
from src.calibrate_classifier import review_snapshot_rows
from src.tag_preview import create_preview, file_hash, local_file, write_report

ROOT = Path(__file__).resolve().parent.parent


def missing_fields(row):
    return {field for field, result in row['fields'].items() if result['status'] == 'not_observed_both'}


def create_classifier_preview(source, model_root=None, limit=3, scenes=None, ffmpeg=None, ffprobe=None, factory=OfflineClassifier, vocals_mode='sampled'):
    if vocals_mode not in {'sampled', 'full'}:
        raise ValueError('Vocal coverage mode must be sampled or full')
    if type(limit) is not int or limit < 1 or (vocals_mode == 'sampled' and limit > 6):
        raise ValueError('Full scan limit must be a positive integer; sampled limit must be 1..6')
    started = time.monotonic()
    if vocals_mode == 'full':
        report = create_preview(source, limit, scenes, ffprobe, allow_large_batch=True)
    else:
        report = create_preview(source, limit, scenes, ffprobe)
    allowed_scenes = set(scenes if scenes is not None else {'focus', 'coding', 'relax', 'energy', 'pop'})
    ai_fields = {'mood', 'language', 'DJ_VOCALS', 'DJ_ENERGY', 'DJ_SCENE'}
    errors = (ClassifierError, AudioAnalysisError, OSError, ValueError, ImportError, RuntimeError,
              subprocess.TimeoutExpired)
    engine, model_error, spec_hash, prompt_hash, prompts = None, None, None, None, None
    needs_model = any(row['file_probe']['status'] == 'observed' and missing_fields(row) & ai_fields
                      for row in report['rows'])
    if needs_model:
        try:
            spec_hash = file_hash(ROOT / 'classifier-models.json')
            prompt_hash = file_hash(ROOT / 'classifier-prompts.json')
            spec = json.loads((ROOT / 'classifier-models.json').read_text(encoding='utf-8'))
            prompts = json.loads((ROOT / 'classifier-prompts.json').read_text(encoding='utf-8'))
            validate_prompts(prompts)
            if model_root is None and factory is OfflineClassifier:
                from src.core.runtime_support import default_runtime_root
                model_root = default_runtime_root() / 'models'
            engine = factory(model_root, spec, prompts)
        except errors as exc:
            model_error = {'status': 'model_unavailable', 'error_type': type(exc).__name__}
            if isinstance(exc, ClassifierError):
                model_error['detail'] = str(exc)
    for row in report['rows']:
        needed = missing_fields(row)
        needed_ai = needed & ai_fields
        for field, result in row['fields'].items():
            result['audio_status'] = 'awaiting_candidate' if field in needed else 'preserved_no_reanalysis'
        if 'tempo' in needed:
            row['fields']['tempo']['audio_status'] = 'deferred_tempo_vocabulary_and_bpm_bins'
        if row['file_probe']['status'] != 'observed':
            row['classification_analysis'] = {'status': 'metadata_verification_blocked'}
            continue
        if not needed:
            row['classification_analysis'] = {'status': 'skipped_all_fields_protected'}
            continue
        analysis = {'status': 'deferred_tempo_only', 'fields': {}}
        row['classification_analysis'] = analysis
        for field in needed:
            row['fields'][field]['action'] = 'owner_review_only_never_auto_apply'
        if needed_ai and engine is None:
            analysis.update(model_error)
            for field in needed_ai:
                row['fields'][field]['audio_status'] = 'model_unavailable'
        if 'bpm' not in needed and (not needed_ai or engine is None):
            continue
        try:
            if not ffmpeg or not ffprobe:
                raise AudioAnalysisError('FFmpeg/FFprobe unavailable')
            path = local_file(row['source_path'])
            before = path.stat()
            duration = read_duration(path, ffprobe)
            segments, pcm, bpm_error = [], [], None
            for clip in clip_plan(duration):
                y = decode_clip(path, clip, ffmpeg)
                pcm.append(y)
                measured = dict(clip)
                if 'bpm' in needed:
                    try:
                        measured.update(measure_clip(y))
                    except errors as exc:
                        bpm_error = {'status': 'analysis_error', 'error_type': type(exc).__name__}
                segments.append(measured)
            analysis['segments'] = segments
            if 'bpm' in needed:
                try:
                    bpm = bpm_error or aggregate_bpm(segments, duration)
                except errors as exc:
                    bpm = {'status': 'analysis_error', 'error_type': type(exc).__name__}
                analysis['bpm'] = bpm
                row['fields']['bpm'].update(proposed_value=bpm.get('proposed_value'), audio_status=bpm['status'])
            if needed_ai and engine is not None:
                instrumental = any(isinstance(e['value'], str) and e['value'].strip().casefold() == 'instrumental'
                                   for entries in (row['xml_fields']['DJ_VOCALS'], row['file_probe']['fields']['DJ_VOCALS'])
                                   for e in entries)
                try:
                    classified = engine.classify(pcm, allowed_scenes, need_language='language' in needed,
                                                 confirmed_instrumental=instrumental)
                    if vocals_mode == 'full' and 'DJ_VOCALS' in needed_ai:
                        full_vocals = engine.scan_full_vocals(path, duration, ffmpeg)
                        classified.setdefault('fields', {})['DJ_VOCALS'] = full_vocals
                    analysis['fields'] = {field: value for field, value in classified.get('fields', {}).items()
                                          if field in needed_ai}
                    for field in needed_ai:
                        proposal = analysis['fields'].get(field, {})
                        target = row['fields'][field]
                        target['proposed_value'] = proposal.get('suggested_value')
                        target['audio_status'] = proposal.get('status', classified['status'])
                        if field == 'language' and target['proposed_value'] is not None:
                            raw = target['proposed_value']
                            target['proposed_value'] = LANGUAGE_ALIASES.get(raw)
                            proposal.update(suggested_bcp47=raw, consumer_language_candidate=target['proposed_value'])
                            if target['proposed_value'] is None:
                                target['audio_status'] = 'language_consumer_mapping_pending'
                except errors as exc:
                    analysis['classification_error'] = {'error_type': type(exc).__name__}
                    for field in needed_ai:
                        row['fields'][field].update(proposed_value=None, audio_status='analysis_error')
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise AudioAnalysisError('File changed during classification')
            failed = any(row['fields'][f]['audio_status'] in {'analysis_error', 'model_unavailable', 'voice_scan_error', 'voice_scan_incomplete'} for f in needed)
            analysis['status'] = 'partial_analysis_error' if failed else ('classified_unreviewed' if needed_ai else 'acoustic_only_unreviewed')
        except errors as exc:
            row['classification_analysis'] = {'status': 'analysis_error', 'error_type': type(exc).__name__}
            if isinstance(exc, (ClassifierError, AudioAnalysisError)):
                row['classification_analysis']['detail'] = str(exc)
            for field in needed - {'tempo'}:
                row['fields'][field].update(audio_status='analysis_error', proposed_value=None)
    if file_hash(source) != report['summary']['source_sha256_before']:
        raise ValueError('Source XML changed during classification; discard results')
    for name, digest in (('classifier-models.json', spec_hash), ('classifier-prompts.json', prompt_hash)):
        if digest is not None and file_hash(ROOT / name) != digest:
            raise ValueError('Model manifest or prompts changed during classification; discard results')
    versions = {}
    for package in ('torch', 'transformers', 'safetensors', 'librosa', 'numpy'):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    report['summary'].update({
        'mode': 'local_ai_candidate_review_only', 'audio_inference': 'acoustic_BPM_and_optional_CLAP_Whisper',
        'model_status': 'loaded' if engine is not None else ('unavailable' if model_error else 'not_needed'),
        'classification_status_counts': dict(Counter(row['classification_analysis']['status'] for row in report['rows'])),
        'candidate_counts_by_field': {field: sum(row['fields'][field]['proposed_value'] is not None for row in report['rows'])
                                      for field in report['rows'][0]['fields']} if report['rows'] else {},
        'models': engine.provenance if engine is not None else None, 'runtime_versions': versions,
        'prompt_version': prompts.get('version') if isinstance(prompts, dict) else None, 'classification_rule_version': 4,
        'vocals_mode': vocals_mode, 'whole_track_absence_verified': False,
        'prompt_sha256': prompt_hash, 'model_manifest_sha256': spec_hash,
        'consumer_vocabulary': {'mood': sorted(set(MOOD_ALIASES.values())),
                                'language': sorted(set(LANGUAGE_ALIASES.values()))},
        'calibration': 'not_completed_owner_labels_required', 'automatic_tag_write_eligible': False,
        'transcription_generated': False, 'elapsed_seconds': round(time.monotonic() - started, 3),
    })
    report['summary']['notes'].extend([
        'Every AI candidate requires listening review. Cosine similarity is not accuracy/confidence.',
        'BPM is independent of models; tempo-only requests are deferred without decoding.',
        'Scenes are independent multi-label comparisons; pop is never a fallback.',
        'Whisper loads only when stable vocal evidence requires language analysis.',
        'Language proposals use current consumer aliases, not proven native write mappings.',
        'Sampled instrumental evidence cannot verify absence of vocals throughout a recording.',
        'CLAP uses a pinned unmerged safetensors conversion PR, not an official main-branch release.',
        'No music, XML, player settings or listening statistics are modified.',
    ])
    return report

def write_calibration_template(report, output_dir):
    records = review_snapshot_rows(report)
    path = Path(output_dir) / 'owner-review.csv'
    with path.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['source_path', 'field', 'candidate', 'status', 'owner_value', 'owner_reviewed'])
        for (source_path, field), (candidate, status) in records.items():
            writer.writerow([source_path, field, candidate, status, '', ''])
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml', type=Path)
    parser.add_argument('--model-root', type=Path, help='Optional override of the durable model directory')
    parser.add_argument('--limit', type=int, help='Positive count for full vocals; 1..6 sampled; default 3 sampled / 1 full')
    parser.add_argument('--vocals-mode', choices=('sampled', 'full'), default='sampled')
    parser.add_argument('--output-dir', type=Path, help='New musicbee-preview-* task directory under TEMP')
    args = parser.parse_args()
    try:
        config = resolve_config_paths(load_config(ROOT / 'config.yaml'), ROOT)
        report = create_classifier_preview(args.xml or Path(config['musicbee']['xml_path']), args.model_root,
                                           args.limit if args.limit is not None else (1 if args.vocals_mode == 'full' else 3),
                                           config.get('scenes', {}).keys(), shutil.which('ffmpeg'),
                                           shutil.which('ffprobe'), vocals_mode=args.vocals_mode)
        if args.output_dir:
            output = write_report(report, args.output_dir)
            write_calibration_template(report, output)
            report['summary']['output_dir'] = str(output)
            report['summary']['preview_json_sha256'] = file_hash(Path(output) / 'preview.json')
    except (OSError, ValueError, ET.ParseError) as exc:
        parser.exit(1, f'Classifier preview failed ({type(exc).__name__}): {exc}\n')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    blocked = {'model_unavailable', 'metadata_verification_blocked', 'analysis_error', 'partial_analysis_error'}
    return 2 if not report['rows'] or any(row['classification_analysis']['status'] in blocked for row in report['rows']) else 0


if __name__ == '__main__':
    sys.exit(main())
