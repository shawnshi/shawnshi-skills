"""Small-sample local acoustic/BPM preview. Never classify DJ tags or write music."""
import argparse
from collections import Counter
from importlib import metadata
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cli import load_config, resolve_config_paths
from src.core.audio_analysis import analyze_file, AudioAnalysisError
from src.tag_preview import create_preview, file_hash, write_report


def create_audio_preview(source, limit=3, scenes=None, ffmpeg=None, ffprobe=None):
    if type(limit) is not int or not 1 <= limit <= 6:
        raise ValueError('Audio preview limit must be an integer from 1 to 6')
    started = time.monotonic()
    report = create_preview(source, limit, scenes, ffprobe)
    missing = [name for name in ('numpy', 'scipy', 'librosa') if importlib.util.find_spec(name) is None]
    if not ffmpeg:
        missing.append('ffmpeg')
    if not ffprobe:
        missing.append('ffprobe')
    for row in report['rows']:
        bpm = row['fields']['bpm']
        if row['file_probe']['status'] != 'observed':
            result = {'status': 'metadata_verification_blocked'}
        elif bpm['action'] != 'candidate_for_later_audio_analysis':
            result = {'status': 'skipped_existing_or_unverified_bpm'}
        elif missing:
            result = {'status': 'dependency_missing', 'dependencies': missing}
        else:
            try:
                result = analyze_file(row['source_path'], ffmpeg, ffprobe)
            except (AudioAnalysisError, OSError, ValueError, ImportError, RuntimeError,
                    subprocess.TimeoutExpired) as exc:
                result = {'status': 'analysis_error', 'error_type': type(exc).__name__}
                # Controlled diagnostics from our code only; third-party exception text may expose metadata.
                if isinstance(exc, AudioAnalysisError):
                    result['detail'] = str(exc)
        row['audio_analysis'] = result
        bpm['audio_status'] = result.get('bpm', {}).get('status', result['status'])
        if result['status'] == 'analyzed':
            bpm['proposed_value'] = result['bpm']['proposed_value']
            bpm['action'] = 'review_audio_bpm_candidate_no_write'
        for field, value in row['fields'].items():
            if field == 'bpm':
                continue
            value['audio_status'] = ('deferred_mapping_or_classifier' if value['status'] == 'not_observed_both'
                                     else 'preserved_no_reanalysis')
    if file_hash(source) != report['summary']['source_sha256_before']:
        raise ValueError('Source XML changed during audio analysis; discard results')
    versions = {}
    for name in ('librosa', 'numpy', 'scipy', 'numba'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    report['summary'].update({
        'mode': 'local_acoustic_bpm_preview_only', 'audio_inference': 'acoustic_features_and_bpm_candidates',
        'ai_classification': 'not_implemented', 'dependency_missing': missing,
        'audio_status_counts': dict(Counter(row['audio_analysis']['status'] for row in report['rows'])),
        'bpm_proposed_count': sum(row['fields']['bpm']['proposed_value'] is not None for row in report['rows']),
        'analysis_versions': versions, 'analysis_rules_version': 1,
        'sample_rate': 22050, 'max_clips_per_file': 3, 'max_seconds_per_clip': 30,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'deferred_fields': ['tempo', 'mood', 'language', 'DJ_VOCALS', 'DJ_ENERGY', 'DJ_SCENE'],
    })
    report['summary']['notes'].extend([
        'BPM candidates are unreviewed estimates, not approved values or calibrated probabilities.',
        'Half/double-time ambiguity, inconsistent segments and long recordings suppress proposed BPM.',
        'Acoustic measurements do not imply vocal status, mood, language, energy or scene.',
        'No audio is saved or uploaded; no model or example audio is downloaded by this command.',
    ])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml', type=Path)
    parser.add_argument('--limit', type=int, default=3, help='Audio-file sample: 1..6; default 3')
    parser.add_argument('--output-dir', type=Path, help='New musicbee-preview-* directory directly under TEMP')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        config = resolve_config_paths(load_config(root / 'config.yaml'), root)
        source = args.xml or Path(config['musicbee']['xml_path'])
        report = create_audio_preview(source, args.limit, config.get('scenes', {}).keys(),
                                      shutil.which('ffmpeg'), shutil.which('ffprobe'))
        if args.output_dir:
            report['summary']['output_dir'] = str(write_report(report, args.output_dir))
    except (OSError, ValueError, ET.ParseError) as exc:
        parser.exit(1, f'Audio preview failed ({type(exc).__name__}): {exc}\n')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    incomplete = {'dependency_missing', 'analysis_error', 'metadata_verification_blocked'}
    return 2 if not report['rows'] or any(row['audio_analysis']['status'] in incomplete for row in report['rows']) else 0


if __name__ == '__main__':
    sys.exit(main())
