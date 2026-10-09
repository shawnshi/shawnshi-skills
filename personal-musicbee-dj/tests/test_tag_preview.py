import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import tag_preview as preview


class TagPreviewTests(unittest.TestCase):
    def test_keys_and_numbered_scenes(self):
        fields = preview.collect_fields({'TXXX:DJ_VOCALS': 'vocal', 'dj_scene2': 'coding',
                                         'TBPM': '120.5', 'unrelated': 'private'})
        self.assertEqual(fields['DJ_VOCALS'][0]['value'], 'vocal')
        self.assertEqual(fields['DJ_SCENE'][0]['value'], 'coding')
        self.assertEqual(fields['bpm'][0]['value'], '120.5')
        self.assertNotIn('unrelated', str(fields))

    def reconcile(self, field, xml='', file='', status='observed'):
        return preview.reconcile(field, [{'key': field, 'value': xml}],
                                 [{'key': field, 'value': file}], status, preview.DEFAULT_SCENES)

    def test_existing_unknown_and_invalid_are_protected(self):
        self.assertEqual(self.reconcile('DJ_ENERGY', file='high')['action'],
                         'preserve_file_value_check_export')
        self.assertEqual(self.reconcile('DJ_VOCALS', xml='unknown', file='UNKNOWN')['action'],
                         'preserve_unknown')
        self.assertEqual(self.reconcile('DJ_ENERGY', file='8')['status'], 'invalid_existing')
        self.assertEqual(self.reconcile('DJ_VOCALS', xml='vocal', file='instrumental')['status'], 'conflict')
        self.assertEqual(self.reconcile('bpm', xml='120')['status'], 'xml_only_value')

    def test_unobserved_is_not_proven_missing_or_ai_inference(self):
        result = self.reconcile('bpm')
        self.assertEqual(result['status'], 'not_observed_both')
        self.assertEqual(result['action'], 'candidate_for_later_audio_analysis')
        self.assertIsNone(result['proposed_value'])
        for field in ('tempo', 'mood', 'language'):
            self.assertEqual(self.reconcile(field)['action'], 'verify_mapping')

    def test_read_errors_never_become_missing(self):
        for status in ('read_error', 'unsupported_format', 'dependency_missing', 'changed_during_read'):
            self.assertEqual(self.reconcile('bpm', status=status)['status'], 'verification_blocked')

    def test_scene_multivalue_and_invalid(self):
        self.assertEqual(self.reconcile('DJ_SCENE', xml='coding; focus', file='Focus; CODING')['status'],
                         'existing')
        for value in ('focus; unknown', 'focus, coding', 'focus;', 'Workout', ';'):
            self.assertEqual(self.reconcile('DJ_SCENE', file=value)['status'], 'invalid_existing')

    def test_bpm_decimal_and_bad_input(self):
        self.assertEqual(self.reconcile('bpm', xml='120.00', file='120')['status'], 'existing')
        for value in ('NaN', 'sNaN', 'Infinity', '0', '-1', 'fast'):
            self.assertEqual(self.reconcile('bpm', file=value)['status'], 'invalid_existing')
        entries = [{'key': 'BPM', 'value': '120'}, {'key': 'TBPM', 'value': '125'}]
        self.assertEqual(preview.value_state('bpm', entries, preview.DEFAULT_SCENES)[0], 'conflict')
        self.assertEqual(preview.value_state('bpm', [{'value': None}], preview.DEFAULT_SCENES)[0], 'invalid')

    def test_missing_and_network_files_are_blocked(self):
        for path in ('relative.mp3', '//server/share/song.mp3', 'https://host/song.mp3'):
            with patch.object(preview.subprocess, 'run') as run:
                self.assertEqual(preview.probe_file(path, 'ffprobe')['status'], 'read_error')
                run.assert_not_called()

    def test_probe_failure_timeout_and_bad_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.mp3'
            path.write_bytes(b'not-a-real-audio-file')
            cases = [
                (subprocess.CompletedProcess([], 9, '', 'native error'), 'FFprobeExit'),
                (subprocess.CompletedProcess([], 0, '{', ''), 'JSONDecodeError'),
            ]
            for completed, error_type in cases:
                with patch.object(preview.subprocess, 'run', return_value=completed):
                    result = preview.probe_file(path, 'ffprobe')
                self.assertEqual(result['status'], 'read_error')
                self.assertEqual(result['error_type'], error_type)
            with patch.object(preview.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffprobe', 10)):
                self.assertEqual(preview.probe_file(path, 'ffprobe')['error_type'], 'TimeoutExpired')
            self.assertEqual(preview.probe_file(path, None)['status'], 'dependency_missing')

    def test_container_mismatch_and_file_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.mp3'
            path.write_bytes(b'test')
            completed = subprocess.CompletedProcess([], 0, json.dumps({'format': {'format_name': 'flac'}}), '')
            with patch.object(preview.subprocess, 'run', return_value=completed):
                self.assertEqual(preview.probe_file(path, 'ffprobe')['status'], 'container_mismatch')
            def change_file(*args, **kwargs):
                path.write_bytes(b'changed-size')
                return subprocess.CompletedProcess([], 0, json.dumps({'format': {'format_name': 'mp3'}}), '')
            with patch.object(preview.subprocess, 'run', side_effect=change_file):
                self.assertEqual(preview.probe_file(path, 'ffprobe')['status'], 'changed_during_read')

    def test_xml_inventory_priority_and_no_unrelated_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tracks = {
                '1': {'Track ID': 1, 'Location': (root / 'a.mp3').as_uri(), 'Comment': 'private'},
                '2': {'Track ID': 2, 'Location': (root / 'b.flac').as_uri(), 'DJ_SCENE': 'unknown'},
                '3': {'Track ID': 3, 'Location': (root / 'c.flac').as_uri(), '速度': 'slow', '语言': 'eng'},
            }
            source = root / 'library.xml'
            source.write_bytes(plistlib.dumps({'Playlists': [{'Name': 'private'}], 'Tracks': tracks}, sort_keys=False))
            rows, total, counts = preview.inventory_xml(source, 1)
            self.assertEqual(total, 3)
            self.assertEqual(rows[0]['track_id'], '2')
            self.assertEqual(counts, {'DJ_SCENE': 1, '语言': 1, '速度': 1})
            self.assertNotIn('private', str(rows))
            self.assertEqual(len(rows), 1)

    def test_invalid_xml_and_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'library.xml'
            for payload in ({}, {'Tracks': []}):
                source.write_bytes(plistlib.dumps(payload))
                with self.assertRaises(ValueError):
                    preview.inventory_xml(source, 1)
            for limit in (0, 49, True):
                with self.assertRaises(ValueError):
                    preview.create_preview(source, limit)
            with self.assertRaises(ValueError):
                preview.create_preview(source, scenes={'Workout'})

    def test_empty_library_is_not_completed_file_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'library.xml'
            source.write_bytes(plistlib.dumps({'Tracks': {}}))
            report = preview.create_preview(source)
            self.assertFalse(report['summary']['sample_probe_complete'])
            completed = subprocess.run([sys.executable, '-B', str(ROOT / 'src/tag_preview.py'),
                                        '--xml', str(source)], capture_output=True, encoding='utf-8', timeout=20)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(json.loads(completed.stdout)['sample_rows'], 0)

    def test_xml_drift_stops_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'library.xml'
            source.write_bytes(plistlib.dumps({'Tracks': {}}))
            with patch.object(preview, 'file_hash', side_effect=['before', 'after']):
                with self.assertRaisesRegex(ValueError, 'changed during preview'):
                    preview.create_preview(source)

    def test_output_location_exclusive_and_csv_formula_safety(self):
        with tempfile.TemporaryDirectory(prefix='musicbee-preview-') as folder:
            out = Path(folder) / 'musicbee-preview-report'
            report = {'summary': {}, 'rows': [{
                'track_id': '=1+1', 'source_path': '@bad', 'xml_fields': preview.collect_fields({}),
                'file_probe': {'fields': preview.collect_fields({})},
                'fields': {'bpm': {'status': 'not_observed_both', 'action': 'review'}},
            }]}
            with patch.object(preview.tempfile, 'gettempdir', return_value=folder):
                preview.write_report(report, out)
                self.assertIn("'=1+1,'@bad", (out / 'review-only.csv').read_text(encoding='utf-8-sig'))
                with self.assertRaises(ValueError):
                    preview.write_report(report, out)
                with self.assertRaises(ValueError):
                    preview.write_report(report, Path(folder) / 'nested' / 'musicbee-preview-no')
                with self.assertRaises(ValueError):
                    preview.write_report(report, Path(folder) / 'not-a-task')

    @unittest.skipUnless(shutil.which('ffprobe') and shutil.which('ffmpeg'), 'FFmpeg tools unavailable')
    def test_real_mp3_flac_cli_and_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tracks = {}
            before = {}
            for index, extension in enumerate(('mp3', 'flac'), 1):
                path = root / f'fixture.{extension}'
                subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi',
                                '-i', 'sine=frequency=440:duration=0.2', '-metadata', 'BPM=120.5',
                                '-metadata', 'DJ_VOCALS=unknown', '-metadata', 'DJ_ENERGY=high',
                                '-metadata', 'DJ_SCENE=focus; coding', '-metadata', 'TEMPO=slow',
                                '-metadata', 'MOOD=calm', '-metadata', 'LANGUAGE=eng', str(path)], check=True,
                               capture_output=True, timeout=15)
                before[path] = preview.file_hash(path)
                tracks[str(index)] = {'Track ID': index, 'Location': path.as_uri(), 'DJ_VOCALS': 'unknown'}
            source = root / 'library.xml'
            source.write_bytes(plistlib.dumps({'Tracks': tracks}))
            before[source] = preview.file_hash(source)
            report = preview.create_preview(source, executable=shutil.which('ffprobe'))
            self.assertEqual(report['summary']['file_probe_status_counts'], {'observed': 2})
            for row in report['rows']:
                self.assertEqual(row['fields']['bpm']['status'], 'xml_export_gap')
                self.assertEqual(row['fields']['DJ_VOCALS']['status'], 'unknown_existing')
                self.assertEqual(row['fields']['DJ_ENERGY']['status'], 'xml_export_gap')
                self.assertEqual(row['fields']['DJ_SCENE']['status'], 'xml_export_gap')
                for field in ('tempo', 'mood', 'language'):
                    self.assertEqual(row['fields'][field]['status'], 'xml_export_gap')
                    self.assertEqual(row['fields'][field]['mapping'], 'pending')
                self.assertTrue(all(result['proposed_value'] is None for result in row['fields'].values()))
            command = [sys.executable, '-B', '-X', 'utf8', str(ROOT / 'src/tag_preview.py'),
                       '--xml', str(source), '--limit', '2']
            completed = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertFalse(summary['music_writes'])
            self.assertEqual(summary['audio_inference'], 'not_implemented')
            self.assertEqual(summary['sample_rows'], 2)
            self.assertEqual(before, {path: preview.file_hash(path) for path in before})
            self.assertEqual({path.name for path in root.iterdir()}, {'fixture.mp3', 'fixture.flac', 'library.xml'})


if __name__ == '__main__':
    unittest.main()
