"""Audited offline CLAP/Whisper candidates. Similarity is not calibrated confidence."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import subprocess
from src.core.attributes import MOOD_ALIASES
from src.core.local_paths import local_path


class ClassifierError(Exception):
    pass


def validate_models(model_root, spec, required=None):
    if not isinstance(model_root, (str, os.PathLike)):
        raise ClassifierError('Model root required for AI fields')
    required = set(required if required is not None else {'clap', 'whisper'})
    if not required or not required.issubset({'clap', 'whisper'}):
        raise ClassifierError('Unsupported required models')
    try:
        root = local_path(model_root)
    except (ValueError, OSError) as exc:
        raise ClassifierError('Model path must be local without links/reparse points') from exc
    if not isinstance(spec, dict) or type(spec.get('schema_version')) is not int or spec['schema_version'] != 1 or not isinstance(spec.get('models'), dict) or set(spec['models']) != {'clap', 'whisper'}:
        raise ClassifierError('Unsupported model manifest')
    for name in sorted(required):
        model = spec['models'][name]
        if not isinstance(model, dict) or not isinstance(model.get('files'), dict):
            raise ClassifierError('Invalid artifact manifest')
        try:
            folder = local_path(root / name)
        except (ValueError, OSError) as exc:
            raise ClassifierError('Model directory unavailable or linked') from exc
        if not folder.is_dir() or folder.is_symlink():
            raise ClassifierError(f'Model directory unavailable: {name}')
        files = model['files']
        if 'model.safetensors' not in files or len(files) > 15:
            raise ClassifierError('Safetensors/model manifest required')
        if {p.name for p in folder.iterdir()} != set(files):
            raise ClassifierError('Unexpected model artifacts; pickle/remote-code fallback denied')
        for filename, item in files.items():
            if not isinstance(item, dict) or type(item.get('size')) is not int or item['size'] < 0 or not isinstance(item.get('sha256'), str):
                raise ClassifierError('Invalid artifact size/checksum schema')
            if Path(filename).name != filename or filename in {'.', '..'}:
                raise ClassifierError('Invalid artifact path')
            try:
                path = local_path(folder / filename)
            except (ValueError, OSError) as exc:
                raise ClassifierError('Artifact path unavailable or linked') from exc
            if not path.is_file() or path.is_symlink() or path.stat().st_size != item['size']:
                raise ClassifierError(f'Artifact size/path mismatch: {name}/{filename}')
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            if not re.fullmatch('[0-9a-f]{64}', item['sha256']) or digest.hexdigest() != item['sha256']:
                raise ClassifierError(f'Artifact checksum mismatch: {name}/{filename}')
        config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
        if not isinstance(config, dict) or config.get('auto_map') or config.get('model_type') != name:
            raise ClassifierError('Model architecture/remote code denied')
    return {name: {key: value for key, value in model.items() if key != 'files'}
            for name, model in spec['models'].items() if name in required}


def load_exact_model(cls, folder):
    model, info = cls.from_pretrained(folder, local_files_only=True, trust_remote_code=False,
                                      use_safetensors=True, output_loading_info=True, token=False)
    keys = {'missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs'}
    if not keys.issubset(info) or any(info[key] for key in keys):
        raise ClassifierError('Checkpoint load coverage mismatch; random/fallback weights denied')
    return model.eval()


def scalar_candidates(score_rows):
    """Conservative draft selection, not an automatic-write threshold."""
    if not score_rows:
        return {'status': 'uncertain', 'suggested_value': None, 'ranked_candidates': []}
    labels = set(score_rows[0])
    if len(labels) < 2 or any(set(row) != labels for row in score_rows):
        raise ClassifierError('Scalar score shape mismatch')
    if any(not math.isfinite(v) or not -1.001 <= v <= 1.001 for row in score_rows for v in row.values()):
        raise ClassifierError('Invalid cosine scores')
    ranking = sorted(({'label': label, 'mean_cosine': sum(row[label] for row in score_rows) / len(score_rows)}
                      for label in labels), key=lambda x: (-x['mean_cosine'], x['label']))
    winners = [max(sorted(row), key=row.get) for row in score_rows]
    margin = ranking[0]['mean_cosine'] - ranking[1]['mean_cosine']
    stable = len(set(winners)) == 1 and margin >= .02 and ranking[0]['mean_cosine'] >= .18
    return {'status': 'unreviewed_candidate' if stable else 'uncertain',
            'suggested_value': ranking[0]['label'] if stable else None,
            'ranked_candidates': [{'label': x['label'], 'mean_cosine': round(x['mean_cosine'], 6)} for x in ranking],
            'segment_winners': winners, 'cosine_margin': round(margin, 6),
            'calibration': 'unreviewed_never_auto_apply'}


def scene_candidates(score_rows, allowed):
    if not score_rows:
        return {'status': 'uncertain', 'suggested_value': None, 'ranked_candidates': []}
    ranking, selected = [], []
    for scene in sorted(allowed):
        pairs = [row[scene] for row in score_rows]
        if any(len(pair) != 2 or any(not math.isfinite(v) or not -1.001 <= v <= 1.001 for v in pair)
               for pair in pairs):
            raise ClassifierError('Invalid scene cosine scores')
        positive = sum(pair[0] for pair in pairs) / len(pairs)
        delta = sum(pair[0] - pair[1] for pair in pairs) / len(pairs)
        support = sum(pair[0] > pair[1] for pair in pairs) / len(pairs)
        if positive >= .18 and delta >= .02 and support >= 2 / 3:
            selected.append(scene)
        ranking.append({'label': scene, 'positive_cosine': round(positive, 6),
                        'contrast_delta': round(delta, 6), 'segment_support': round(support, 6)})
    return {'status': 'unreviewed_candidate' if selected else 'uncertain',
            'suggested_value': '; '.join(selected) or None,
            'ranked_candidates': sorted(ranking, key=lambda x: (-x['contrast_delta'], x['label'])),
            'calibration': 'unreviewed_never_auto_apply'}


def validate_prompts(prompts):
    if not isinstance(prompts, dict) or type(prompts.get('version')) is not int or prompts['version'] != 1:
        raise ClassifierError('Unsupported prompt schema')
    expected = {'DJ_VOCALS': {'vocal', 'instrumental'}, 'DJ_ENERGY': {'low', 'medium', 'high'},
                'mood': set(MOOD_ALIASES.values())}
    scalar, scenes = prompts.get('scalar'), prompts.get('scenes')
    if not isinstance(scalar, dict) or set(scalar) != set(expected):
        raise ClassifierError('Scalar vocabulary mismatch')
    if not isinstance(scenes, dict) or set(scenes) != {'focus', 'coding', 'relax', 'energy', 'pop'}:
        raise ClassifierError('Scene vocabulary mismatch')
    groups = []
    for field, labels in expected.items():
        if not isinstance(scalar[field], dict) or set(scalar[field]) != labels:
            raise ClassifierError('Scalar vocabulary mismatch')
        groups.extend(scalar[field].values())
    for pair in scenes.values():
        if not isinstance(pair, dict) or set(pair) != {'positive', 'contrast'}:
            raise ClassifierError('Scene contrast schema mismatch')
        groups.extend(pair.values())
    if any(not isinstance(group, list) or not group or any(not isinstance(text, str) or not text.strip() or len(text) > 250 for text in group) for group in groups):
        raise ClassifierError('Invalid prompt phrase list')
    if sum(map(len, groups)) > 64:
        raise ClassifierError('Prompt resource bounds exceeded')


class OfflineClassifier:
    def __init__(self, model_root, spec, prompts):
        validate_prompts(prompts)
        from src.core.runtime_support import verify_runtime
        verify_runtime()
        self.provenance = validate_models(model_root, spec, {'clap'})
        self._model_root, self._spec = Path(model_root), spec
        # Local files only is authoritative; these flags additionally suppress library telemetry.
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        import torch
        from transformers import ClapModel, ClapProcessor
        self.torch = torch
        torch.set_num_threads(1)
        torch.manual_seed(0)
        root = Path(model_root)
        self.clap = load_exact_model(ClapModel, root / 'clap')
        self.processor = ClapProcessor.from_pretrained(root / 'clap', local_files_only=True, trust_remote_code=False, token=False)
        self.whisper, self.speech_features, self._language_load_error = None, None, None
        texts, self.groups = [], {}
        for field, labels in prompts['scalar'].items():
            for label, phrases in labels.items():
                self.groups[(field, label)] = list(range(len(texts), len(texts) + len(phrases)))
                texts.extend(phrases)
        for scene, pair in prompts['scenes'].items():
            for polarity, phrases in pair.items():
                self.groups[('DJ_SCENE', scene, polarity)] = list(range(len(texts), len(texts) + len(phrases)))
                texts.extend(phrases)
        if not 1 <= len(texts) <= 64 or any(not isinstance(t, str) or not 1 <= len(t) <= 250 for t in texts):
            raise ClassifierError('Prompt resource bounds exceeded')
        with torch.inference_mode():
            features = self.clap.get_text_features(**self.processor(text=texts, padding=True, return_tensors='pt')).pooler_output
        self.text_vectors = {key: torch.nn.functional.normalize(features[indices].mean(dim=0), dim=0)
                             for key, indices in self.groups.items()}

    def _audio_scores(self, y):
        import librosa
        import numpy as np
        if y.ndim != 1 or not np.isfinite(y).all() or not 8 * 22050 <= len(y) <= 31 * 22050:
            raise ClassifierError('Invalid bounded PCM')
        center, half = len(y) // 2, 5 * 22050
        clip = y[max(0, center - half):min(len(y), center + half)]
        if float(np.mean(np.square(clip, dtype=np.float64))) <= 1e-12:
            return None, clip
        wave = librosa.resample(clip, orig_sr=22050, target_sr=48000)
        with self.torch.inference_mode():
            vector = self.clap.get_audio_features(**self.processor(audio=wave, sampling_rate=48000,
                                                                   return_tensors='pt')).pooler_output[0]
            values = {key: float(self.torch.dot(vector, text)) for key, text in self.text_vectors.items()}
        return values, clip

    def scan_full_vocals(self, path, duration, ffmpeg, budget_seconds=120):
        from src.core.audio_analysis import full_vocal_plan, decode_clip, AudioAnalysisError
        if not math.isfinite(budget_seconds) or not 0 < budget_seconds <= 120:
            raise ClassifierError('Full vocal scan budget must be 0..120 seconds')
        result = {'status': 'voice_scan_incomplete', 'suggested_value': None, 'windows': [],
                  'coverage_complete': False, 'whole_track_absence_verified': False,
                  'automatic_tag_write_eligible': False, 'calibration': 'unreviewed_never_auto_apply'}
        deadline = time.monotonic() + budget_seconds
        rows = []
        try:
            plan = full_vocal_plan(duration)
            for window in plan:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    result['reason'] = 'wall_clock_budget_exhausted'
                    return result
                y = decode_clip(path, window, ffmpeg, timeout=min(45, remaining))
                scores, _ = self._audio_scores(y)
                decision = {'status': 'silent', 'suggested_value': None}
                if scores is not None:
                    row = {label: scores[('DJ_VOCALS', label)] for label in ('vocal', 'instrumental')}
                    decision = scalar_candidates([row])
                    rows.append(row)
                result['windows'].append({**window, 'decision': decision})
                if time.monotonic() > deadline:
                    result['reason'] = 'wall_clock_budget_exhausted'
                    return result
            result['coverage_complete'] = True
            if not rows:
                result['status'] = 'insufficient_non_silent_segments'
                return result
            ranking = scalar_candidates(rows)
            result['ranked_candidates'] = ranking['ranked_candidates']
            decisions = [window['decision'] for window in result['windows'] if window['decision']['status'] != 'silent']
            # Any locally credible vocal observation defeats an instrumental whole-track candidate.
            if any(item['suggested_value'] == 'vocal' for item in decisions):
                result.update(status='unreviewed_candidate', suggested_value='vocal')
            elif all(item['suggested_value'] == 'instrumental' for item in decisions):
                result.update(status='unreviewed_candidate', suggested_value='instrumental')
            else:
                result['status'] = 'uncertain'
            return result
        except (ClassifierError, AudioAnalysisError, OSError, ValueError, ImportError, RuntimeError,
                subprocess.TimeoutExpired) as exc:
            result.update(status='voice_scan_error', reason='scan_failed', error_type=type(exc).__name__)
            return result

    def _ensure_language_model(self):
        if self.whisper is not None:
            return
        if self._language_load_error is not None:
            raise ClassifierError('Language model unavailable in this run')
        try:
            provenance = validate_models(self._model_root, self._spec, {'whisper'})
            from transformers import WhisperForConditionalGeneration, WhisperFeatureExtractor
            model = load_exact_model(WhisperForConditionalGeneration, self._model_root / 'whisper')
            features = WhisperFeatureExtractor.from_pretrained(self._model_root / 'whisper', local_files_only=True, token=False)
        except (ClassifierError, OSError, ValueError, ImportError, RuntimeError) as exc:
            self._language_load_error = type(exc).__name__
            raise
        self.whisper, self.speech_features = model, features
        self.provenance.update(provenance)

    def _language(self, clips):
        self._ensure_language_model()
        import librosa
        torch = self.torch
        mapping = self.whisper.generation_config.lang_to_id
        codes = [token.removeprefix('<|').removesuffix('|>') for token in mapping]
        ids = list(mapping.values())
        distributions = []
        for clip in clips:
            wave = librosa.resample(clip, orig_sr=22050, target_sr=16000)
            features = self.speech_features(wave, sampling_rate=16000, return_tensors='pt').input_features
            start = torch.tensor([[self.whisper.generation_config.decoder_start_token_id]])
            with torch.inference_mode():
                logits = self.whisper(input_features=features, decoder_input_ids=start, use_cache=False).logits[0, -1]
                distribution = torch.softmax(logits[ids], dim=-1)
            if not torch.isfinite(distribution).all():
                raise ClassifierError('Invalid language distribution')
            distributions.append(distribution)
        average = torch.stack(distributions).mean(dim=0)
        order = torch.argsort(average, descending=True)[:3].tolist()
        winners = [codes[int(row.argmax())] for row in distributions]
        stable = len(set(winners)) == 1 and float(average[order[0]]) >= .6
        return {'status': 'unreviewed_language_candidate' if stable else 'uncertain',
                'suggested_value': codes[order[0]] if stable else None, 'value_namespace': 'BCP47_candidate_not_MusicBee_mapping',
                'ranked_candidates': [{'label': codes[i], 'model_language_probability': round(float(average[i]), 6)} for i in order],
                'segment_winners': winners, 'calibration': 'model_probability_not_calibrated_accuracy',
                'transcription_generated': False}

    def classify(self, segments, allowed_scenes, need_language=False, confirmed_instrumental=False):
        if not 1 <= len(segments) <= 3 or not allowed_scenes or not set(allowed_scenes).issubset({'focus', 'coding', 'relax', 'energy', 'pop'}):
            raise ClassifierError('Segment/scene resource bounds invalid')
        rows, clips = [], []
        for y in segments:
            scores, clip = self._audio_scores(y)
            if scores is not None:
                rows.append(scores)
                clips.append(clip)
        if len(rows) != len(segments):
            return {'status': 'insufficient_non_silent_segments', 'fields': {}}
        fields = {}
        for field in ('DJ_VOCALS', 'DJ_ENERGY', 'mood'):
            labels = [key[1] for key in self.groups if key[0] == field]
            fields[field] = scalar_candidates([{label: row[(field, label)] for label in labels} for row in rows])
        if fields['DJ_VOCALS']['suggested_value'] == 'instrumental':
            fields['DJ_VOCALS'].update(suggested_value=None, status='insufficient_coverage_for_instrumental',
                                       whole_track_absence_verified=False)
        fields['DJ_SCENE'] = scene_candidates([{scene: (row[('DJ_SCENE', scene, 'positive')],
                                                        row[('DJ_SCENE', scene, 'contrast')]) for scene in allowed_scenes}
                                             for row in rows], allowed_scenes)
        vocals = fields['DJ_VOCALS']
        if need_language and not confirmed_instrumental and vocals['suggested_value'] == 'vocal':
            try:
                fields['language'] = self._language(clips)
            except (ClassifierError, OSError, ValueError, ImportError, RuntimeError) as exc:
                fields['language'] = {'status': 'analysis_error', 'suggested_value': None, 'error_type': type(exc).__name__}
        else:
            fields['language'] = {'status': 'skipped_no_stable_vocal_evidence_or_existing_language', 'suggested_value': None}
        return {'status': 'classified_with_errors' if fields['language']['status'] == 'analysis_error' else 'classified_unreviewed', 'fields': fields,
                'calibration': 'owner_review_required_before_any_tag_write', 'rule_version': 1}
