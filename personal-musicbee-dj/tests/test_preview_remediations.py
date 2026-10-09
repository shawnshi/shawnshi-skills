import copy
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import classifier_preview as preview
from src.calibrate_classifier import assess_review, review_snapshot_rows, worksheet_cell
from src.core.audio_classifier import ClassifierError, OfflineClassifier, validate_prompts
from src.tag_preview import FIELDS, reconcile


class PreviewRemediationTests(unittest.TestCase):
    def metadata(self, needed):
        return {'summary': {'source_sha256_before': 'same', 'notes': []}, 'rows': [{
            'source_path': 'fixture.mp3', 'xml_fields': {f: [] for f in FIELDS},
            'file_probe': {'status': 'observed', 'fields': {f: [] for f in FIELDS}},
            'fields': {f: {'status': 'not_observed_both' if f in needed else 'existing',
                           'proposed_value': None} for f in FIELDS}}]}

    def run_preview(self, needed, factory, classify_error=False, dsp_error=False):
        path = MagicMock()
        path.stat.return_value = SimpleNamespace(st_size=1, st_mtime_ns=1)
        with patch.object(preview, 'create_preview', return_value=self.metadata(needed)), \
             patch.object(preview, 'file_hash', return_value='same'), \
             patch.object(preview, 'local_file', return_value=path), \
             patch.object(preview, 'read_duration', return_value=180), \
             patch.object(preview, 'decode_clip', return_value='bounded-pcm'), \
             patch.object(preview, 'measure_clip', side_effect=ValueError('DSP fixture') if dsp_error else None,
                          return_value={'bpm_candidates': [{'bpm': 120, 'periodicity': 1}]}), \
             patch.object(preview, 'aggregate_bpm', return_value={'status': 'consistent_unreviewed_candidate',
                                                                'proposed_value': 120}):
            return preview.create_classifier_preview('fixture.xml', None, ffmpeg='fixture', ffprobe='fixture', factory=factory)

    def test_bpm_only_never_constructs_models(self):
        factory = MagicMock(side_effect=AssertionError('AI must not load'))
        report = self.run_preview({'bpm'}, factory)
        factory.assert_not_called()
        self.assertEqual(report['rows'][0]['fields']['bpm']['proposed_value'], 120)
        self.assertEqual(report['summary']['model_status'], 'not_needed')

    def test_tempo_only_skips_models_and_decoding(self):
        factory = MagicMock(side_effect=AssertionError('AI must not load'))
        with patch.object(preview, 'create_preview', return_value=self.metadata({'tempo'})), \
             patch.object(preview, 'file_hash', return_value='same'), patch.object(preview, 'decode_clip') as decode:
            report = preview.create_classifier_preview('fixture.xml', factory=factory)
        factory.assert_not_called()
        decode.assert_not_called()
        self.assertEqual(report['rows'][0]['classification_analysis']['status'], 'deferred_tempo_only')

    def test_model_failure_preserves_bpm(self):
        factory = MagicMock(side_effect=ClassifierError('Model unavailable fixture'))
        report = self.run_preview({'bpm', 'mood'}, factory)
        row = report['rows'][0]
        self.assertEqual(row['fields']['bpm']['proposed_value'], 120)
        self.assertEqual(row['fields']['mood']['audio_status'], 'model_unavailable')
        self.assertEqual(row['classification_analysis']['status'], 'partial_analysis_error')

    def test_classification_failure_preserves_bpm(self):
        engine = MagicMock(provenance={})
        engine.classify.side_effect = ClassifierError('CLAP inference fixture')
        report = self.run_preview({'bpm', 'mood'}, lambda *a: engine)
        self.assertEqual(report['rows'][0]['fields']['bpm']['proposed_value'], 120)
        self.assertEqual(report['rows'][0]['fields']['mood']['audio_status'], 'analysis_error')

    def test_dsp_failure_preserves_ai_fields(self):
        engine = MagicMock(provenance={})
        engine.classify.return_value = {'status': 'classified_unreviewed', 'fields': {
            'mood': {'status': 'unreviewed_candidate', 'suggested_value': 'calm'}}}
        report = self.run_preview({'bpm', 'mood'}, lambda *a: engine, dsp_error=True)
        self.assertEqual(report['rows'][0]['fields']['bpm']['audio_status'], 'analysis_error')
        self.assertEqual(report['rows'][0]['fields']['mood']['proposed_value'], 'calm')

    def test_bad_prompts_rejected_before_factory_without_losing_bpm(self):
        factory = MagicMock()
        original = json.loads
        count = [0]
        def missing_version(data):
            value = original(data)
            count[0] += 1
            if count[0] == 2:
                value.pop('version')
            return value
        with patch.object(preview.json, 'loads', side_effect=missing_version):
            report = self.run_preview({'bpm', 'mood'}, factory)
        factory.assert_not_called()
        self.assertEqual(report['summary']['model_status'], 'unavailable')
        self.assertIsNone(report['summary']['prompt_version'])
        self.assertEqual(report['rows'][0]['fields']['bpm']['proposed_value'], 120)

    def test_prompt_lists_rejected_before_model_validation(self):
        valid = json.loads((ROOT / 'classifier-prompts.json').read_text(encoding='utf-8'))
        for invalid in ('phrase-not-list', [], [''], [3]):
            prompts = copy.deepcopy(valid)
            prompts['scalar']['DJ_VOCALS']['vocal'] = invalid
            with self.subTest(invalid=invalid), patch('src.core.audio_classifier.validate_models') as models:
                with self.assertRaises(ClassifierError):
                    OfflineClassifier(None, {}, prompts)
                models.assert_not_called()
        validate_prompts(valid)

    def test_whisper_failure_does_not_erase_other_predictions(self):
        engine = object.__new__(OfflineClassifier)
        labels = {'DJ_VOCALS': ['vocal', 'instrumental'], 'DJ_ENERGY': ['low', 'medium', 'high'], 'mood': ['calm', 'warm']}
        engine.groups = {(field, label): [] for field, names in labels.items() for label in names}
        scores = {(field, label): .4 if i == 0 else .1 for field, names in labels.items() for i, label in enumerate(names)}
        scores.update({('DJ_SCENE', 'focus', 'positive'): .4, ('DJ_SCENE', 'focus', 'contrast'): .1})
        with patch.object(engine, '_audio_scores', return_value=(scores, 'pcm')), \
             patch.object(engine, '_language', side_effect=ClassifierError('Whisper unavailable fixture')):
            result = engine.classify(['pcm'] * 3, {'focus'}, need_language=True)
        self.assertEqual(result['fields']['language']['status'], 'analysis_error')
        self.assertEqual(result['fields']['mood']['suggested_value'], 'calm')
        self.assertEqual(result['fields']['DJ_VOCALS']['suggested_value'], 'vocal')

    def test_language_load_failure_is_not_retried_for_each_track(self):
        engine = object.__new__(OfflineClassifier)
        engine.whisper, engine._language_load_error = None, None
        engine._model_root, engine._spec = Path('unused'), {}
        with patch('src.core.audio_classifier.validate_models', side_effect=ClassifierError('Missing fixture')) as validate:
            for _ in range(6):
                with self.assertRaises(ClassifierError):
                    engine._ensure_language_model()
            self.assertEqual(validate.call_count, 1)

    def binding(self, directory):
        snapshot = {'summary': {'mode': 'local_ai_candidate_review_only', 'automatic_tag_write_eligible': False,
                                'classification_rule_version': 2},
                    'rows': [{'source_path': 'fixture.mp3', 'fields': {'DJ_VOCALS': {
                        'status': 'not_observed_both', 'audio_status': 'unreviewed_candidate', 'proposed_value': 'vocal'}}}]}
        data = json.dumps(snapshot).encode()
        path = directory / 'preview.json'
        path.write_bytes(data)
        worksheet = directory / 'owner-review.csv'
        with worksheet.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['source_path', 'field', 'candidate', 'status', 'owner_value', 'owner_reviewed'])
            writer.writerow(['fixture.mp3', 'DJ_VOCALS', 'vocal', 'unreviewed_candidate', 'instrumental', 'yes'])
        return worksheet, path, hashlib.sha256(data).hexdigest()

    def test_bound_review_scores_original_prediction_not_human_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = assess_review(*self.binding(Path(tmp)))
        self.assertEqual(result['metrics']['DJ_VOCALS']['exact_match_rate_on_candidates'], 0)
        self.assertFalse(result['automatic_tag_write_eligible'])

    def test_candidate_and_status_tampering_rejected_even_if_unreviewed(self):
        for index, changed in [(2, 'instrumental'), (3, 'analysis_error'), (0, 'different.mp3')]:
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                review, reference, digest = self.binding(Path(tmp))
                with review.open(newline='', encoding='utf-8') as f:
                    rows = list(csv.reader(f))
                rows[1][index], rows[1][5] = changed, 'no'
                with review.open('w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerows(rows)
                with self.assertRaises(ValueError):
                    assess_review(review, reference, digest)

    def test_reference_tampering_and_missing_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            review, reference, digest = self.binding(Path(tmp))
            with self.assertRaises(ValueError):
                assess_review(review)
            reference.write_text(reference.read_text().replace('vocal', 'instrumental'))
            with self.assertRaisesRegex(ValueError, 'checksum'):
                assess_review(review, reference, digest)

    def test_deleted_snapshot_rows_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            review, reference, digest = self.binding(Path(tmp))
            review.write_text('source_path,field,candidate,status,owner_value,owner_reviewed\n')
            with self.assertRaisesRegex(ValueError, 'set differs'):
                assess_review(review, reference, digest)

    def test_failed_status_cannot_carry_valid_prediction(self):
        report = {'summary': {'mode': 'local_ai_candidate_review_only', 'automatic_tag_write_eligible': False},
                  'rows': [{'source_path': 'fixture', 'fields': {'DJ_VOCALS': {
                      'status': 'not_observed_both', 'audio_status': 'analysis_error', 'proposed_value': 'vocal'}}}]}
        with self.assertRaisesRegex(ValueError, 'candidate/status'):
            review_snapshot_rows(report)

    def test_aliases_compare_semantically_without_dropping_unknown_text(self):
        for field, a, b in [('language', 'en', 'eng'), ('mood', 'happy', 'joyful'),
                            ('language', 'en; fr', 'fra; eng'), ('mood', 'happy; calm', 'calm; joyful')]:
            with self.subTest(field=field, value=a):
                result = reconcile(field, [{'value': a}], [{'value': b}], 'observed', {'focus'})
                self.assertEqual(result['status'], 'existing')
                self.assertEqual(result['mapping'], 'pending')
        result = reconcile('language', [{'value': 'en; unmapped'}], [{'value': 'eng'}], 'observed', {'focus'})
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(reconcile('language', [{'value': 'unknown'}], [], 'observed', {'focus'})['status'], 'unknown_existing')

    def test_csv_control_character_protection(self):
        for value in ('=formula', '+formula', '\tname', '\rname', '\nname'):
            self.assertTrue(worksheet_cell(value).startswith("'"))


if __name__ == '__main__':
    unittest.main()
