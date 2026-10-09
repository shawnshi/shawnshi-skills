import copy
import hashlib
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import classifier_preview as preview
from src import tag_preview as tags
from src.calibrate_classifier import assess_review, review_snapshot_rows
from src.core.audio_analysis import full_vocal_plan
from src.core.audio_classifier import OfflineClassifier


class FullModeLimitsTests(unittest.TestCase):
    def test_large_duration_plan_is_lazy(self):
        plan = full_vocal_plan(10**12)
        self.assertIs(iter(plan), plan)
        windows = list(itertools.islice(plan, 3))
        self.assertEqual([w['start_seconds'] for w in windows], [0, 10, 20])

    def test_long_scan_completes_without_duration_gate(self):
        engine = object.__new__(OfflineClassifier)
        engine._audio_scores = lambda _: ({('DJ_VOCALS', 'vocal'): .1,
                                           ('DJ_VOCALS', 'instrumental'): .4}, None)
        with patch('src.core.audio_analysis.decode_clip', return_value='synthetic-pcm'):
            result = engine.scan_full_vocals('fixture', 3600.7, 'fixture')
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(len(result['windows']), 361)
        self.assertAlmostEqual(sum(result['windows'][-1][k] for k in ('start_seconds', 'duration_seconds')), 3600.7)
        self.assertFalse(result['whole_track_absence_verified'])
        self.assertFalse(result['automatic_tag_write_eligible'])

    def test_long_scan_still_honors_budget_without_absence_claim(self):
        engine = object.__new__(OfflineClassifier)
        with patch('src.core.audio_classifier.time.monotonic', side_effect=[0, 121]), \
             patch('src.core.audio_analysis.decode_clip') as decode:
            result = engine.scan_full_vocals('fixture', 10**12, 'fixture')
        decode.assert_not_called()
        self.assertEqual(result['status'], 'voice_scan_incomplete')
        self.assertEqual(result['reason'], 'wall_clock_budget_exhausted')
        self.assertIsNone(result['suggested_value'])
        self.assertFalse(result['coverage_complete'])

    def test_fifty_track_full_preview_and_bound_review_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'synthetic.xml'
            source.write_text('<synthetic/>', encoding='utf-8')
            audio = base / 'synthetic.mp3'
            audio.write_bytes(b'synthetic fixture; never decoded')
            original_audio = hashlib.sha256(audio.read_bytes()).hexdigest()
            original_xml = hashlib.sha256(source.read_bytes()).hexdigest()
            metadata_rows = [{'track_id': str(i), 'source_path': str(base / f'{i}.mp3'),
                              'xml_fields': {f: [] if f == 'DJ_VOCALS' else [{'key': f, 'value': 'unknown'}]
                                             for f in tags.FIELDS}} for i in range(50)]
            engine = MagicMock(provenance={})
            engine.classify.side_effect = lambda *a, **k: {'status': 'classified_unreviewed', 'fields': {}}
            engine.scan_full_vocals.return_value = {'status': 'unreviewed_candidate', 'suggested_value': 'instrumental',
                                                    'coverage_complete': True, 'whole_track_absence_verified': False,
                                                    'automatic_tag_write_eligible': False}
            with patch.object(tags, 'inventory_xml', return_value=(metadata_rows, 50, {})) as inventory, \
                 patch.object(tags, 'probe_file', side_effect=lambda *a: {'status': 'observed', 'fields': {f: [] for f in tags.FIELDS}}), \
                 patch.object(preview, 'local_file', return_value=audio), \
                 patch.object(preview, 'read_duration', return_value=3600.7), \
                 patch.object(preview, 'decode_clip', return_value='synthetic-pcm'):
                report = preview.create_classifier_preview(source, limit=50, ffmpeg='fixture', ffprobe='fixture',
                                                           vocals_mode='full', factory=lambda *a: engine)
            inventory.assert_called_once_with(source, 50)
            self.assertEqual(len(report['rows']), 50)
            self.assertEqual(engine.scan_full_vocals.call_count, 50)
            self.assertEqual(report['summary']['classification_rule_version'], 4)
            self.assertFalse(report['summary']['automatic_tag_write_eligible'])
            self.assertEqual(len(review_snapshot_rows(report)), 50)
            # Exercise actual JSON/CSV binding, not a newly substituted prediction or checksum.
            json_path = base / 'preview.json'
            json_path.write_text(json.dumps(report), encoding='utf-8')
            original_digest = hashlib.sha256(json_path.read_bytes()).hexdigest()
            review = preview.write_calibration_template(report, base)
            result = assess_review(review, json_path, original_digest)
            self.assertEqual(result['status'], 'calibration_pending_no_owner_labels')
            self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), original_audio)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_xml)
            sampled = copy.deepcopy(report)
            sampled['summary']['vocals_mode'] = 'sampled'
            with self.assertRaises(ValueError):
                review_snapshot_rows(sampled)

    def test_sampled_and_metadata_defaults_keep_existing_limits(self):
        with self.assertRaises(ValueError):
            preview.create_classifier_preview('fixture', limit=7)
        with self.assertRaises(ValueError):
            tags.create_preview('fixture', limit=49)
        for count in (0, -1, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                preview.create_classifier_preview('fixture', limit=count, vocals_mode='full')


if __name__ == '__main__':
    unittest.main()
