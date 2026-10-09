import importlib.util
import json
import math
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import audio_preview
from src.core import audio_analysis as analysis
from src.tag_preview import collect_fields, DEFAULT_SCENES, file_hash, reconcile

HAS_LIBROSA = importlib.util.find_spec('librosa') is not None


def segment(*values):
    return {'bpm_candidates': [{'bpm': bpm, 'periodicity': score} for bpm, score in values]}


class AudioPreviewTests(unittest.TestCase):
    def test_clip_plan_bounded_and_short_tracks(self):
        self.assertEqual(analysis.clip_plan(12), [{'start_seconds': 0.0, 'duration_seconds': 12}])
        for duration in (31, 120, 2400, 86400):
            plan = analysis.clip_plan(duration)
            self.assertLessEqual(len(plan), 3)
            for clip in plan:
                self.assertLessEqual(clip['duration_seconds'], 30)
                self.assertGreaterEqual(clip['start_seconds'], 0)
                self.assertLessEqual(clip['start_seconds'] + clip['duration_seconds'], duration)
        for duration in (0, 7, math.inf, math.nan):
            with self.assertRaises(analysis.AudioAnalysisError):
                analysis.clip_plan(duration)

    def test_consistent_unreviewed_candidate(self):
        result = analysis.aggregate_bpm([segment((120, .8)), segment((122, .8)), segment((119, .8))], 180)
        self.assertEqual(result['proposed_value'], 120)
        self.assertEqual(result['calibration'], 'unreviewed_not_for_auto_write')

    def test_ambiguity_disagreement_and_long_set(self):
        cases = [([segment((120, .8), (60, .75))], 30, 'half_double_time_ambiguity'),
                 ([segment((120, .8), (240, .75))], 30, 'half_double_time_ambiguity'),
                 ([segment((80, .8)), segment((120, .8))], 180, 'segment_disagreement'),
                 ([segment((120, .8))], 2400, 'long_recording_no_single_global_bpm'),
                 ([segment((120, .8)), segment()], 180, 'insufficient_periodic_segments')]
        for segments, duration, reason in cases:
            result = analysis.aggregate_bpm(segments, duration)
            self.assertIsNone(result['proposed_value'])
            self.assertIn(reason, result['reasons'])
        self.assertIsNone(analysis.aggregate_bpm([], 180)['proposed_value'])

    def test_duration_errors(self):
        for stdout in ('{}', '{', '{"format":{"duration":"nan"}}'):
            with patch.object(analysis.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout, '')):
                with self.assertRaises(analysis.AudioAnalysisError):
                    analysis.read_duration('fixture.flac', 'ffprobe')
        with patch.object(analysis.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7, '', '')):
            with self.assertRaisesRegex(analysis.AudioAnalysisError, 'exit code 7'):
                analysis.read_duration('fixture.flac', 'ffprobe')

    def test_decode_output_bounds_and_protocol(self):
        import numpy as np
        clip = {'start_seconds': 0, 'duration_seconds': 10}
        for payload in (b'x', b'', np.full(10 * analysis.SAMPLE_RATE, np.nan, dtype='<f4').tobytes(),
                        bytes((analysis.SAMPLE_RATE * 11) * 4)):
            with patch.object(analysis.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, payload, b'')):
                with self.assertRaises(analysis.AudioAnalysisError):
                    analysis.decode_clip('fixture.flac', clip, 'ffmpeg')
        payload = np.zeros(10 * analysis.SAMPLE_RATE, dtype='<f4').tobytes()
        with patch.object(analysis.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, payload, b'')) as run:
            analysis.decode_clip('fixture.flac', clip, 'ffmpeg')
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'file')
            self.assertIn('-nostdin', args)
        with self.assertRaises(analysis.AudioAnalysisError):
            analysis.decode_clip('fixture.flac', {'start_seconds': 0, 'duration_seconds': 31}, 'ffmpeg')

    def report(self, bpm='', vocals=''):
        fields = collect_fields({'BPM': bpm, 'DJ_VOCALS': vocals})
        return {'summary': {'source_sha256_before': 'same', 'notes': []}, 'rows': [{
            'source_path': 'fixture.flac', 'xml_fields': fields,
            'file_probe': {'status': 'observed', 'fields': fields},
            'fields': {field: reconcile(field, entries, entries, 'observed', DEFAULT_SCENES)
                       for field, entries in fields.items()},
        }]}

    def test_only_missing_bpm_is_analyzed_no_other_labels(self):
        report = self.report(vocals='unknown')
        result = {'status': 'analyzed', 'bpm': {'status': 'consistent_unreviewed_candidate', 'proposed_value': 120}}
        with patch.object(audio_preview, 'create_preview', return_value=report), \
             patch.object(audio_preview, 'file_hash', return_value='same'), \
             patch.object(audio_preview.importlib.util, 'find_spec', return_value=object()), \
             patch.object(audio_preview, 'analyze_file', return_value=result):
            out = audio_preview.create_audio_preview('library.xml', ffmpeg='ffmpeg', ffprobe='ffprobe')
        row = out['rows'][0]
        self.assertEqual(row['fields']['bpm']['proposed_value'], 120)
        for field, value in row['fields'].items():
            if field != 'bpm':
                self.assertIsNone(value['proposed_value'])
        self.assertEqual(row['fields']['DJ_VOCALS']['action'], 'preserve_unknown')
        self.assertEqual(out['summary']['ai_classification'], 'not_implemented')

    def test_existing_bpm_is_not_reanalyzed(self):
        with patch.object(audio_preview, 'create_preview', return_value=self.report(bpm='120')), \
             patch.object(audio_preview, 'file_hash', return_value='same'), \
             patch.object(audio_preview, 'analyze_file') as analyzer:
            out = audio_preview.create_audio_preview('library.xml', ffmpeg='ffmpeg', ffprobe='ffprobe')
        analyzer.assert_not_called()
        self.assertEqual(out['rows'][0]['audio_analysis']['status'], 'skipped_existing_or_unverified_bpm')

    def test_dependency_failure_does_not_fabricate_candidates(self):
        with patch.object(audio_preview, 'create_preview', return_value=self.report()), \
             patch.object(audio_preview, 'file_hash', return_value='same'), \
             patch.object(audio_preview.importlib.util, 'find_spec', return_value=None):
            out = audio_preview.create_audio_preview('library.xml', ffmpeg='ffmpeg', ffprobe='ffprobe')
        self.assertEqual(out['rows'][0]['audio_analysis']['status'], 'dependency_missing')
        self.assertIsNone(out['rows'][0]['fields']['bpm']['proposed_value'])

    def test_analysis_failure_is_not_unknown(self):
        with patch.object(audio_preview, 'create_preview', return_value=self.report()), \
             patch.object(audio_preview, 'file_hash', return_value='same'), \
             patch.object(audio_preview.importlib.util, 'find_spec', return_value=object()), \
             patch.object(audio_preview, 'analyze_file', side_effect=analysis.AudioAnalysisError('Audio decode exit code 9')):
            out = audio_preview.create_audio_preview('library.xml', ffmpeg='ffmpeg', ffprobe='ffprobe')
        self.assertEqual(out['rows'][0]['audio_analysis']['status'], 'analysis_error')
        self.assertEqual(out['rows'][0]['audio_analysis']['detail'], 'Audio decode exit code 9')

    def test_xml_drift_and_limits(self):
        for limit in (0, 7, True):
            with self.assertRaises(ValueError):
                audio_preview.create_audio_preview('library.xml', limit)
        with patch.object(audio_preview, 'create_preview', return_value=self.report(bpm='120')), \
             patch.object(audio_preview, 'file_hash', return_value='changed'):
            with self.assertRaisesRegex(ValueError, 'XML changed'):
                audio_preview.create_audio_preview('library.xml')

    @unittest.skipUnless(HAS_LIBROSA, 'Optional audited librosa runtime unavailable')
    def test_silence_and_known_click_tempo(self):
        import numpy as np
        y = np.zeros(30 * analysis.SAMPLE_RATE, dtype=np.float32)
        self.assertEqual(analysis.measure_clip(y)['status'], 'silent_or_near_silent')
        pulse = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(550) / analysis.SAMPLE_RATE).astype(np.float32)
        for start in range(0, len(y) - len(pulse), analysis.SAMPLE_RATE // 2):
            y[start:start + len(pulse)] = pulse
        result = analysis.measure_clip(y)
        self.assertTrue(any(abs(candidate['bpm'] - 120) < 5 for candidate in result['bpm_candidates']), result)
        self.assertGreater(result['spectral_centroid_hz'], 0)
        with self.assertRaises(analysis.AudioAnalysisError):
            analysis.measure_clip(np.zeros(3))

    @unittest.skipUnless(HAS_LIBROSA and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Audio runtime unavailable')
    def test_real_flac_and_cli_do_not_write_audio(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pcm = np.zeros(12 * analysis.SAMPLE_RATE, dtype=np.float32)
            pulse = .5 * np.sin(2 * np.pi * 1000 * np.arange(550) / analysis.SAMPLE_RATE)
            for start in range(0, len(pcm) - len(pulse), analysis.SAMPLE_RATE // 2):
                pcm[start:start + len(pulse)] = pulse
            wav = root / 'fixture.wav'
            with wave.open(str(wav), 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(analysis.SAMPLE_RATE)
                writer.writeframes((pcm * 32767).astype('<i2').tobytes())
            flac = root / 'fixture.flac'
            subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(wav), str(flac)],
                           capture_output=True, check=True, timeout=15)
            source = root / 'library.xml'
            source.write_bytes(plistlib.dumps({'Tracks': {'1': {'Location': flac.as_uri()}}}))
            before = {path: file_hash(path) for path in (wav, flac, source)}
            run = subprocess.run([sys.executable, '-B', str(ROOT / 'src/audio_preview.py'),
                                  '--xml', str(source), '--limit', '1'],
                                 capture_output=True, encoding='utf-8', timeout=90)
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads(run.stdout)
            self.assertEqual(summary['audio_status_counts'], {'analyzed': 1})
            self.assertFalse(summary['music_writes'])
            self.assertEqual(before, {path: file_hash(path) for path in before})
            self.assertEqual({path.name for path in root.iterdir()}, {'fixture.wav', 'fixture.flac', 'library.xml'})


if __name__ == '__main__':
    unittest.main()
