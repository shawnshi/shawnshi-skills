import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.audio_classifier import ClassifierError, OfflineClassifier, scalar_candidates, scene_candidates, validate_models, load_exact_model
from src import classifier_preview as preview
from src.calibrate_classifier import assess_review, normalized_value, worksheet_cell
from src.tag_preview import collect_fields, reconcile, DEFAULT_SCENES


class ClassifierTests(unittest.TestCase):
    def test_checkpoint_loading_requires_complete_coverage(self):
        from unittest.mock import MagicMock
        loader = MagicMock()
        model = MagicMock()
        info = {'missing_keys': set(), 'unexpected_keys': set(), 'mismatched_keys': set(), 'error_msgs': []}
        loader.from_pretrained.return_value = (model, info)
        load_exact_model(loader, 'fixture')
        self.assertTrue(loader.from_pretrained.call_args.kwargs['local_files_only'])
        self.assertTrue(loader.from_pretrained.call_args.kwargs['use_safetensors'])
        self.assertFalse(loader.from_pretrained.call_args.kwargs['trust_remote_code'])
        self.assertFalse(loader.from_pretrained.call_args.kwargs['token'])
        info['missing_keys'] = {'missing_layer'}
        with self.assertRaisesRegex(ClassifierError, 'coverage mismatch'):
            load_exact_model(loader, 'fixture')

    def test_scalar_consistency_and_uncertainty(self):
        result = scalar_candidates([{'vocal': .4, 'instrumental': .2}] * 3)
        self.assertEqual(result['suggested_value'], 'vocal')
        self.assertEqual(result['calibration'], 'unreviewed_never_auto_apply')
        for rows in ([{'low': .3, 'high': .29}], [{'low': .3, 'high': .2}, {'low': .2, 'high': .3}],
                     [{'low': .1, 'high': .02}], []):
            self.assertIsNone(scalar_candidates(rows)['suggested_value'])
        for value in (float('nan'), 2):
            with self.assertRaises(ClassifierError):
                scalar_candidates([{'low': value, 'high': .3}])

    def test_scene_multilabel_and_no_pop_fallback(self):
        rows = [{'focus': (.4, .2), 'coding': (.4, .2), 'pop': (.2, .4)}] * 3
        result = scene_candidates(rows, {'focus', 'coding', 'pop'})
        self.assertEqual(result['suggested_value'], 'coding; focus')
        self.assertIsNone(scene_candidates([{'pop': (.2, .4)}], {'pop'})['suggested_value'])
        self.assertIsNone(scene_candidates([], {'pop'})['suggested_value'])

    def tiny_manifest(self, root):
        spec = {'schema_version': 1, 'models': {}}
        for name in ('clap', 'whisper'):
            folder = root / name; folder.mkdir()
            files = {'config.json': json.dumps({'model_type': name}).encode(), 'model.safetensors': b'test-not-loaded'}
            for filename, data in files.items():
                (folder / filename).write_bytes(data)
            spec['models'][name] = {'files': {filename: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                                             for filename, data in files.items()}, 'revision': 'test'}
        return spec

    def test_model_hashes_and_pickle_fallback_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); spec = self.tiny_manifest(root)
            validate_models(root, spec)
            (root / 'clap/pytorch_model.bin').write_bytes(b'pickle')
            with self.assertRaisesRegex(ClassifierError, 'Unexpected model artifacts'):
                validate_models(root, spec)
            (root / 'clap/pytorch_model.bin').unlink()
            (root / 'clap/model.safetensors').write_bytes(b'x' * spec['models']['clap']['files']['model.safetensors']['size'])
            with self.assertRaisesRegex(ClassifierError, 'checksum'):
                validate_models(root, spec)
        with self.assertRaises(ClassifierError):
            validate_models('relative', {})

    def test_prompt_vocabulary_rejects_numeric_energy(self):
        prompts = json.loads((ROOT / 'classifier-prompts.json').read_text(encoding='utf-8'))
        prompts['scalar']['DJ_ENERGY']['8'] = prompts['scalar']['DJ_ENERGY'].pop('high')
        with patch('src.core.audio_classifier.validate_models', return_value={}):
            with self.assertRaisesRegex(ClassifierError, 'Scalar vocabulary'):
                OfflineClassifier('not-read', {}, prompts)

    def test_remote_code_denied_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); spec = self.tiny_manifest(root)
            path = root / 'clap/config.json'
            data = json.dumps({'model_type': 'clap', 'auto_map': {'AutoModel': 'remote.Code'}}).encode()
            path.write_bytes(data)
            spec['models']['clap']['files']['config.json'] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            with self.assertRaisesRegex(ClassifierError, 'remote code'):
                validate_models(root, spec)

    def report(self, vocals='unknown', energy='', language='eng'):
        entries = collect_fields({'DJ_VOCALS': vocals, 'DJ_ENERGY': energy, 'Language': language})
        return {'summary': {'source_sha256_before': 'same', 'notes': []}, 'rows': [{
            'source_path': 'fixture.flac', 'xml_fields': entries, 'file_probe': {'status': 'observed', 'fields': entries},
            'fields': {field: reconcile(field, values, values, 'observed', DEFAULT_SCENES)
                       for field, values in entries.items()},
        }]}

    def test_preserve_unknown_and_existing_values(self):
        class Fake:
            provenance = {'test': True}
            def classify(self, *args, **kwargs):
                return {'status': 'classified_unreviewed', 'fields': {
                    'DJ_VOCALS': {'status': 'unreviewed_candidate', 'suggested_value': 'vocal'},
                    'DJ_ENERGY': {'status': 'unreviewed_candidate', 'suggested_value': 'high'},
                    'language': {'status': 'unreviewed_language_candidate', 'suggested_value': 'en'},
                    'mood': {'status': 'unreviewed_candidate', 'suggested_value': 'calm'},
                }}
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'fixture.flac'; audio.write_bytes(b'not-decoded')
            report = self.report(energy='low');report['rows'][0]['source_path'] = str(audio)
            with patch.object(preview, 'create_preview', return_value=report), \
                 patch.object(preview, 'file_hash', return_value='same'), \
                 patch.object(preview, 'read_duration', return_value=12), \
                 patch.object(preview, 'decode_clip', return_value=object()), \
                 patch.object(preview, 'measure_clip', return_value={'bpm_candidates': []}):
                out = preview.create_classifier_preview('source.xml', 'models', ffmpeg='ffmpeg', ffprobe='ffprobe',
                                                        factory=lambda *args: Fake())
            row = out['rows'][0]
            for field in ('DJ_VOCALS', 'DJ_ENERGY', 'language'):
                self.assertIsNone(row['fields'][field]['proposed_value'])
                self.assertNotIn(field, row['classification_analysis']['fields'])
            self.assertEqual(row['fields']['mood']['proposed_value'], 'calm')
            self.assertIsNone(row['fields']['tempo']['proposed_value'])
            self.assertFalse(out['summary']['automatic_tag_write_eligible'])

    def test_model_unavailable_is_not_unknown(self):
        def fail(*args): raise ClassifierError('Model directory unavailable')
        metadata_report = self.report()
        metadata_report['rows'][0]['fields']['bpm']['status'] = 'existing'
        with patch.object(preview, 'create_preview', return_value=metadata_report), \
             patch.object(preview, 'file_hash', return_value='same'):
            report = preview.create_classifier_preview('source.xml', 'models', ffmpeg='ffmpeg', ffprobe='ffprobe', factory=fail)
        self.assertEqual(report['summary']['model_status'], 'unavailable')
        self.assertEqual(report['rows'][0]['classification_analysis']['status'], 'model_unavailable')
        self.assertTrue(all(value['proposed_value'] is None for value in report['rows'][0]['fields'].values()))

    def review_csv(self, path, rows):
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['source_path', 'field', 'candidate', 'status', 'owner_value', 'owner_reviewed'])
            writer.writerows(rows)
        tracks = {}
        for source, field, candidate, status, _, _ in rows:
            tracks.setdefault(source, {})[field] = {'status': 'not_observed_both',
                                                    'proposed_value': candidate or None, 'audio_status': status}
        snapshot = {'summary': {'mode': 'local_ai_candidate_review_only', 'automatic_tag_write_eligible': False},
                    'rows': [{'source_path': source, 'fields': fields} for source, fields in tracks.items()]}
        snapshot_path = path.parent / 'preview.json'
        data = json.dumps(snapshot).encode('utf-8')
        snapshot_path.write_bytes(data)
        return snapshot_path, hashlib.sha256(data).hexdigest()

    def test_consumer_mood_and_language_aliases(self):
        self.assertEqual(normalized_value('mood', 'happy; calm'), 'calm; joyful')
        self.assertEqual(normalized_value('language', 'en; fr'), 'eng; fra')
        with self.assertRaises(ValueError):
            normalized_value('language', 'en; unknown')

    def test_calibration_blank_is_pending_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'owner-review.csv'
            binding = self.review_csv(path, [['track', 'DJ_VOCALS', 'instrumental', 'unreviewed_candidate', '', '']])
            report = assess_review(path, *binding)
            self.assertEqual(report['status'], 'calibration_pending_no_owner_labels')
            self.assertEqual(report['reviewed_rows'], 0)
            self.assertFalse(report['automatic_tag_write_eligible'])

    def test_calibration_reports_false_instrumental_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'owner-review.csv'
            binding = self.review_csv(path, [['a', 'DJ_VOCALS', 'instrumental', 'unreviewed_candidate', 'vocal', 'yes'],
                                   ['b', 'DJ_VOCALS', '', 'uncertain', 'vocal', 'yes'],
                                   ['c', 'DJ_SCENE', 'coding; focus', 'unreviewed_candidate', 'focus; coding', 'yes']])
            report = assess_review(path, *binding)
            self.assertEqual(report['metrics']['DJ_VOCALS']['coverage'], .5)
            self.assertEqual(report['metrics']['DJ_VOCALS']['exact_match_rate_on_candidates'], 0)
            self.assertEqual(report['metrics']['DJ_SCENE']['exact_match_rate_on_candidates'], 1)
            self.assertFalse(report['automatic_tag_write_eligible'])

    def test_calibration_invalid_and_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'owner-review.csv'
            binding = self.review_csv(path, [['a', 'DJ_ENERGY', '8', 'unreviewed_candidate', 'high', 'yes']])
            self.assertEqual(assess_review(path, *binding)['status'], 'invalid_owner_review')
            binding = self.review_csv(path, [['a', 'DJ_ENERGY', 'high', 'unreviewed_candidate', 'high', 'yes']] * 2)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                assess_review(path, *binding)
            path.write_text('source_path,field,candidate,status,owner_value,owner_reviewed,owner_value\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'schema mismatch'):
                assess_review(path, *binding)

    @unittest.skipUnless(os.environ.get('MUSICBEE_CLASSIFIER_MODEL_ROOT'), 'Audited local model root not provided')
    def test_native_model_embeddings_language_and_no_network(self):
        import numpy as np
        import socket
        root = Path(os.environ['MUSICBEE_CLASSIFIER_MODEL_ROOT'])
        spec = json.loads((ROOT / 'classifier-models.json').read_text(encoding='utf-8'))
        prompts = json.loads((ROOT / 'classifier-prompts.json').read_text(encoding='utf-8'))
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network denied during inference')):
            engine = OfflineClassifier(root, spec, prompts)
            self.assertIsNone(engine.whisper)
            self.assertEqual(set(engine.provenance), {'clap'})
            engine._ensure_language_model()
            with patch.object(engine.whisper, 'generate', side_effect=AssertionError('Transcription denied')):
                result = engine._language([np.zeros(10 * 22050, dtype=np.float32)])
                self.assertFalse(result['transcription_generated'])
                self.assertEqual(len(result['ranked_candidates']), 3)
            silence = engine.classify([np.zeros(10 * 22050, dtype=np.float32)], DEFAULT_SCENES)
            self.assertEqual(silence['status'], 'insufficient_non_silent_segments')
            y = .1 * np.sin(2 * np.pi * 440 * np.arange(10 * 22050) / 22050).astype(np.float32)
            with self.assertRaises(ClassifierError):
                engine.classify([], DEFAULT_SCENES)
            with patch.object(engine, '_language') as language:
                engine.classify([y], DEFAULT_SCENES, need_language=True, confirmed_instrumental=True)
                language.assert_not_called()
            out = engine.classify([y], DEFAULT_SCENES)
            self.assertEqual(out['status'], 'classified_unreviewed')
            self.assertTrue(set(out['fields']).issuperset({'DJ_VOCALS', 'DJ_ENERGY', 'DJ_SCENE', 'mood'}))
            for field in ('DJ_VOCALS', 'DJ_ENERGY', 'mood'):
                self.assertTrue(all(math_finite(item['mean_cosine']) for item in out['fields'][field]['ranked_candidates']))


def math_finite(value):
    import math
    return math.isfinite(value)


if __name__ == '__main__':
    unittest.main()
