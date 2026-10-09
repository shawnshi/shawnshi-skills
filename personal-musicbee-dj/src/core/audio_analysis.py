"""Local, bounded acoustic measurements and unreviewed tempo candidates, not DJ labels."""
import json
import math
from pathlib import Path
import subprocess

SAMPLE_RATE = 22050
HOP_LENGTH = 512
MAX_CLIP_SECONDS = 30
MIN_SECONDS = 8
LONG_RECORDING_SECONDS = 1200


class AudioAnalysisError(Exception):
    pass


def clip_plan(duration):
    if not math.isfinite(duration) or duration < MIN_SECONDS:
        raise AudioAnalysisError('Recording too short or duration invalid')
    seconds = min(float(MAX_CLIP_SECONDS), duration)
    starts = sorted({round(max(0.0, min(duration - seconds, duration * fraction - seconds / 2)), 3)
                     for fraction in (0.15, 0.5, 0.85)})
    return [{'start_seconds': start, 'duration_seconds': seconds} for start in starts]


def full_vocal_plan(duration):
    if not math.isfinite(duration) or duration < MIN_SECONDS:
        raise AudioAnalysisError('Full vocal scan requires a finite duration of at least 8 seconds')
    seconds = min(10.0, duration)
    # Lazy planning keeps long recordings bounded in memory before the scan budget is checked.
    return ({'start_seconds': min(index * seconds, duration - seconds), 'duration_seconds': seconds}
            for index in range(math.ceil(duration / seconds)))


def read_duration(path, ffprobe):
    completed = subprocess.run(
        [str(ffprobe), '-v', 'error', '-protocol_whitelist', 'file', '-show_entries',
         'format=duration', '-of', 'json', str(path)], capture_output=True,
        encoding='utf-8', timeout=15, check=False)
    if completed.returncode:
        raise AudioAnalysisError(f'Duration probe exit code {completed.returncode}')
    try:
        duration = float(json.loads(completed.stdout)['format']['duration'])
    except (ValueError, KeyError, TypeError) as exc:
        raise AudioAnalysisError(f'Invalid duration response ({type(exc).__name__})') from exc
    if not math.isfinite(duration) or duration <= 0:
        raise AudioAnalysisError('Invalid recording duration')
    return duration


def decode_clip(path, clip, ffmpeg, timeout=45):
    import numpy as np
    if not math.isfinite(timeout) or not 0 < timeout <= 45:
        raise AudioAnalysisError('Decode timeout exceeds task bounds')
    seconds = clip['duration_seconds']
    start = clip['start_seconds']
    if not (0 < seconds <= MAX_CLIP_SECONDS and math.isfinite(start) and start >= 0):
        raise AudioAnalysisError('Clip exceeds allowed bounds')
    completed = subprocess.run(
        [str(ffmpeg), '-v', 'error', '-nostdin', '-protocol_whitelist', 'file',
         '-ss', str(start), '-i', str(path), '-t', str(seconds), '-map', '0:a:0',
         '-vn', '-sn', '-dn', '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 'f32le', 'pipe:1'],
        capture_output=True, timeout=timeout, check=False)
    if completed.returncode:
        raise AudioAnalysisError(f'Audio decode exit code {completed.returncode}')
    if len(completed.stdout) > math.ceil((seconds + 0.25) * SAMPLE_RATE) * 4 or len(completed.stdout) % 4:
        raise AudioAnalysisError('Decoded audio violates size bounds')
    y = np.frombuffer(completed.stdout, dtype='<f4')
    if len(y) < MIN_SECONDS * SAMPLE_RATE or not np.isfinite(y).all():
        raise AudioAnalysisError('Decoded clip too short or contains non-finite samples')
    return y


def measure_clip(y):
    from src.core.runtime_support import verify_runtime
    verify_runtime()
    import numpy as np
    import librosa
    from scipy.signal import find_peaks
    if y.ndim != 1 or not np.isfinite(y).all() or len(y) < MIN_SECONDS * SAMPLE_RATE:
        raise AudioAnalysisError('Invalid PCM samples')
    if len(y) > MAX_CLIP_SECONDS * SAMPLE_RATE + SAMPLE_RATE // 4:
        raise AudioAnalysisError('PCM exceeds clip bounds')
    rms = float(np.sqrt(np.mean(np.square(y, dtype=np.float64))))
    if rms <= 1e-6:
        return {'status': 'silent_or_near_silent', 'rms_dbfs': None, 'bpm_candidates': []}
    onset = librosa.onset.onset_strength(y=y, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)))
    result = {'status': 'measured', 'rms_dbfs': round(20 * math.log10(rms), 3),
              'spectral_centroid_hz': round(centroid, 3), 'onset_mean': round(float(np.mean(onset)), 6),
              'bpm_candidates': []}
    if len(onset) < 4 or float(np.max(onset)) <= 1e-6:
        result['status'] = 'no_reliable_onsets'
        return result
    tempogram = librosa.feature.tempogram(onset_envelope=onset, sr=SAMPLE_RATE,
                                         hop_length=HOP_LENGTH, win_length=384)
    periodicity = np.mean(tempogram, axis=1)
    frequencies = librosa.tempo_frequencies(len(periodicity), sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    peaks, _ = find_peaks(periodicity)
    peaks = [int(index) for index in peaks if 40 <= frequencies[index] <= 220 and periodicity[index] > 0.05]
    peaks.sort(key=lambda index: float(periodicity[index]), reverse=True)
    result['bpm_candidates'] = [{'bpm': round(float(frequencies[index]), 3),
                                  'periodicity': round(float(periodicity[index]), 6)} for index in peaks[:5]]
    if not peaks:
        result['status'] = 'no_reliable_periodicity'
    return result


def aggregate_bpm(segments, duration):
    """Candidate-only consistency checks; periodicity is not calibrated probability."""
    candidates = [segment['bpm_candidates'][0]['bpm'] for segment in segments if segment.get('bpm_candidates')]
    result = {'status': 'needs_review', 'proposed_value': None, 'segment_primary_bpms': candidates,
              'reasons': [], 'calibration': 'unreviewed_not_for_auto_write'}
    if duration >= LONG_RECORDING_SECONDS:
        result['reasons'].append('long_recording_no_single_global_bpm')
    if len(candidates) != len(segments) or not candidates:
        result['reasons'].append('insufficient_periodic_segments')
    if candidates:
        ordered = sorted(candidates)
        median = ordered[len(ordered) // 2]
        if max(abs(value - median) / median for value in candidates) > 0.05:
            result['reasons'].append('segment_disagreement')
        for segment in segments:
            peaks = segment.get('bpm_candidates', [])
            if not peaks:
                continue
            first = peaks[0]
            for alternative in peaks[1:]:
                ratio = alternative['bpm'] / first['bpm']
                if (abs(ratio - 0.5) <= 0.04 or abs(ratio - 2.0) <= 0.08) and (
                        alternative['periodicity'] >= 0.8 * first['periodicity']):
                    result['reasons'].append('half_double_time_ambiguity')
                    break
        if not result['reasons']:
            result['proposed_value'] = round(median, 2)
            result['status'] = 'consistent_unreviewed_candidate'
    result['reasons'] = sorted(set(result['reasons']))
    return result


def analyze_file(path, ffmpeg, ffprobe):
    from src.tag_preview import local_file, SUPPORTED
    path = local_file(path)
    if path.suffix.casefold() not in SUPPORTED:
        raise AudioAnalysisError('Unsupported audio format')
    before = path.stat()
    duration = read_duration(path, ffprobe)
    plan = clip_plan(duration)
    segments = []
    for clip in plan:
        measurement = measure_clip(decode_clip(path, clip, ffmpeg))
        segments.append({**clip, **measurement})
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AudioAnalysisError('File changed during audio analysis')
    return {'status': 'analyzed', 'duration_seconds': round(duration, 3),
            'sample_rate': SAMPLE_RATE, 'segments': segments,
            'bpm': aggregate_bpm(segments, duration),
            'classification': 'not_implemented_no_ai_labels_generated',
            'stat_unchanged': True}
