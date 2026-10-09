import os
import random
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from src.core.attributes import LANGUAGE_ALIASES, MOOD_ALIASES, AROUSAL_MOODS, values, requested_values, evidence_score
from src.core.models import Track, CuratedPlayback
from src.core.parser import MusicBeeParser
from src.utils.logger import log


class DJCurator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

        playlist_cfg = config.get('playlist', {})
        energy_cfg = config.get('energy_curves', {})
        fallback_cfg = config.get('fallback', {})
        filters_cfg = config.get('filters', {})

        self.m3u_path = playlist_cfg['output_m3u']
        self.max_tracks = playlist_cfg.get('max_tracks_per_session', 100)
        request = config.get('request', {})
        minutes = request.get('minutes')
        if minutes is not None and (type(minutes) not in (int, float) or not math.isfinite(minutes) or minutes <= 0):
            raise ValueError("minutes must be a finite positive number")
        self.duration_budget = round(minutes * 60000) if minutes is not None else None
        self.no_vocals = request.get('no_vocals', False)
        self.strict_evidence = request.get('strict_evidence', False)
        self.languages = requested_values(request.get('languages', []), LANGUAGE_ALIASES, 'language')
        self.excluded_languages = requested_values(request.get('exclude_languages', []), LANGUAGE_ALIASES, 'language')
        self.preferred_languages = requested_values(request.get('prefer_languages', []), LANGUAGE_ALIASES, 'language')
        self.moods = requested_values(request.get('moods', []), MOOD_ALIASES, 'mood')
        self.preferred_moods = requested_values(request.get('prefer_moods', []), MOOD_ALIASES, 'mood')
        if self.languages & self.excluded_languages or self.preferred_languages & self.excluded_languages:
            raise ValueError('Conflicting required/preferred and excluded languages')
        self.bpm_min, self.bpm_max = request.get('bpm_min'), request.get('bpm_max')
        for bound in (self.bpm_min, self.bpm_max):
            if bound is not None and (type(bound) is not int or not 1 <= bound <= 500):
                raise ValueError('BPM bounds must be integers in [1, 500]')
        if self.bpm_min is not None and self.bpm_max is not None and self.bpm_min > self.bpm_max:
            raise ValueError('BPM minimum cannot exceed maximum')
        self.score_scene, self.score_genre, self.score_intensity = '', '', 'normal'
        self.selection_buckets, self.quota_target, self.last_diagnostics = {}, {}, {}
        self.excluded_genres = [self._genre_term(value) for value in request.get('exclude_genres', [])]
        self.excluded_artists = [value.lower().strip() for value in request.get('exclude_artists', [])]
        self.excluded_tracks = [value.lower().strip() for value in request.get('exclude_tracks', [])]
        self.excluded_albums = [value.lower().strip() for value in request.get('exclude_albums', [])]
        self.preferred_artists = [value.lower().strip() for value in request.get('prefer_artists', [])]
        self.rng = random.Random(request.get('seed'))
        self.familiarity = request.get('familiarity', 'balanced')
        if self.familiarity not in {'balanced', 'familiar', 'explore'}:
            raise ValueError('Unsupported familiarity strategy')
        self.sequence_relaxations = 0

        curation = playlist_cfg.get('curation', {})
        self.anchor_ratio = curation.get('anchor_ratio', 0.6)
        self.discovery_ratio = curation.get('discovery_ratio', 0.3)
        self.novelty_ratio = curation.get('novelty_ratio', 0.1)
        if self.familiarity == 'familiar':
            self.anchor_ratio, self.discovery_ratio, self.novelty_ratio = 0.8, 0.15, 0.05
        elif self.familiarity == 'explore':
            self.anchor_ratio, self.discovery_ratio, self.novelty_ratio = 0.3, 0.5, 0.2

        self.high_min_bpm = energy_cfg.get('high_intensity_min_bpm', 110)
        self.low_max_bpm = energy_cfg.get('low_intensity_max_bpm', 100)

        self.high_intensity_exclude = [kw.lower() for kw in filters_cfg.get('high_intensity_exclude', ["ambient", "chill", "intro"])]
        self.low_intensity_exclude = [kw.lower() for kw in filters_cfg.get('low_intensity_exclude', ["metal", "rock", "edm"])]

        self.scenes = config.get('scenes', {})
        self.scene_aliases = {
            str(key).lower(): str(value).lower()
            for key, value in fallback_cfg.get('aliases', {}).items()
        }

        xml_path = config['musicbee']['xml_path']
        cache_path = config.get('cache', {}).get('db_path')
        self.parser = MusicBeeParser(xml_path=xml_path, cache_path=cache_path)

    def _extract_date(self, date_str: str) -> datetime:
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            return datetime.min

    def generate_m3u(self, criteria_type: str, criteria_value: str, intensity: str = 'normal', *, export=True, explain=False) -> Optional[CuratedPlayback]:
        library = self.parser.load_library()

        pool, resolved_value, fallback_applied, fallback_reason = self._retrieve_base_tracks(
            library, criteria_type, criteria_value
        )
        self.score_scene = resolved_value if criteria_type == 'scene' else ''
        self.score_genre = criteria_value if criteria_type == 'genre' else ''
        self.score_intensity = intensity
        required_fields = set()
        if criteria_type == 'scene':
            required_fields.add('DJ_SCENE')
        if intensity in {'low', 'high'}:
            required_fields.add('DJ_ENERGY')
        if self.no_vocals or self.languages or self.excluded_languages:
            required_fields.add('DJ_VOCALS')
        if self.moods or self.preferred_moods:
            required_fields.add('mood')
        completion = self.config.get('tag_completion', {})
        completion_diagnostics = None
        if export and completion.get('enabled', False):
            from src.core.tag_preflight import inspect_tracks, related_candidates
            candidates = related_candidates(self, library, pool, criteria_type, resolved_value)
            candidates.sort(key=lambda track: self._track_evidence(track)['match_score'], reverse=True)
            completion_diagnostics = inspect_tracks(candidates, completion, required_fields=required_fields)
            pool, resolved_value, fallback_applied, fallback_reason = self._retrieve_base_tracks(
                library, criteria_type, criteria_value
            )
        self.last_diagnostics = {'loaded_tracks': len(library), 'matched_tracks': len(pool),
            'requested_tracks': self.max_tracks, 'selected_tracks': 0, 'candidate_shortfall': self.max_tracks,
            'strict_evidence': self.strict_evidence,
            'metadata_available': {'bpm': sum(t.bpm > 0 for t in library),
                'language': sum(bool(values(t.language, LANGUAGE_ALIASES)) for t in library),
                'mood': sum(bool(values(t.mood, MOOD_ALIASES)) for t in library),
                'energy': sum(self._energy_level(t) > 0 for t in library),
                'scene': sum(bool(values(t.dj_scene)) and values(t.dj_scene) <= set(self.scenes) for t in library)}}
        self.last_diagnostics['tag_completion'] = completion_diagnostics or {
            'active': False, 'reason': 'read_only_mode' if not export else 'not_enabled'
        }
        if not pool:
            log.warning(f"No tracks found matching {criteria_type} = {criteria_value}")
            return None

        filtered_pool = [track for track in self._filter_by_intensity(pool, intensity) if track.is_valid]
        self.last_diagnostics['filtered_tracks'] = len(filtered_pool)
        self.last_diagnostics['hard_constraint_rejections'] = dict(Counter(self._metadata_rejection(t) for t in pool if self._metadata_rejection(t)))
        if not filtered_pool:
            log.warning(f"No regular song files remained after applying intensity filter: {intensity}")
            return None

        unknown_durations = sum(track.total_time == 0 for track in filtered_pool)
        if self.duration_budget is not None:
            filtered_pool = [track for track in filtered_pool if track.total_time > 0]
            if unknown_durations:
                log.warning(f"Duration budget: excluded {unknown_durations} tracks with unknown duration.")

        # Select the final count before ordering; truncation would change the configured quotas.
        target_len = min(len(filtered_pool), self.max_tracks)
        curated_tracks = self._select_ratio_tracks(filtered_pool, target_len)
        if self.duration_budget is not None:
            within_budget = []
            elapsed = 0
            for track in curated_tracks:
                if elapsed + track.total_time <= self.duration_budget:
                    within_budget.append(track)
                    elapsed += track.total_time
            curated_tracks = within_budget
            if not curated_tracks:
                log.warning("No whole track fits the requested duration budget.")
                return None
        scene_type = resolved_value.lower() if criteria_type == 'scene' else 'normal'
        final_flow = self._build_energy_curve(curated_tracks, scene=scene_type, intensity=intensity)
        if export and completion.get('enabled', False):
            final_inspection = inspect_tracks(final_flow, completion, limit=False, required_fields=required_fields)
            current_pool, _, _, _ = self._retrieve_base_tracks(library, criteria_type, criteria_value)
            current_paths = {track.local_path for track in current_pool}
            validated = self._filter_by_intensity(final_flow, intensity)
            if len(validated) != len(final_flow) or any(track.local_path not in current_paths for track in final_flow):
                raise ValueError('Final live metadata violates the requested scene or hard constraints; no playlist exported')
            final_flow = self._build_energy_curve(final_flow, scene=scene_type, intensity=intensity)
            self.last_diagnostics['tag_completion']['final_inspection'] = final_inspection

        actual_buckets = dict(Counter(self.selection_buckets.get(os.path.normcase(os.path.normpath(t.local_path)), 'fill') for t in final_flow))
        evidence = [self._track_evidence(t) for t in final_flow]
        self.last_diagnostics.update({'quota_target': self.quota_target, 'quota_actual': actual_buckets,
            'requested_tracks': self.max_tracks, 'selected_tracks': len(final_flow),
            'candidate_shortfall': max(0, self.max_tracks-len(final_flow)),
            'quota_deviation': {k: actual_buckets.get(k, 0)-v for k,v in self.quota_target.items()},
            'novelty_pool_policy': 'latest dated max(10% candidates, novelty quota); missing dates are not novelty evidence',
            'mean_match_score': round(sum(e['match_score'] for e in evidence)/len(evidence), 6) if evidence else 0,
            'mean_evidence_coverage': round(sum(e['evidence_coverage'] for e in evidence)/len(evidence), 6) if evidence else 0,
            'weak_genre_scene_fallback_tracks': sum(bool(self.score_scene) and not t.dj_scene.strip() for t in final_flow),
            'sequence_spacing_relaxations': self.sequence_relaxations,
            'strict_evidence': self.strict_evidence,
            'language_constraint_scope': 'vocal/unknown vocal tracks; instrumental tracks are exempt',
            'legacy_instrumental_language_exemptions': sum(bool(self.languages or self.excluded_languages) and not t.dj_vocals.strip() and self._vocal_status(t) == 'instrumental' for t in final_flow)})
        if explain:
            self.last_diagnostics['tracks'] = [{'id': t.id, 'path': t.local_path,
                'allocation_bucket': self.selection_buckets.get(os.path.normcase(os.path.normpath(t.local_path)), 'fill'),
                'unknown_fields': [name for name, known in [('language', bool(values(t.language, LANGUAGE_ALIASES))),
                    ('mood', bool(values(t.mood, MOOD_ALIASES))), ('bpm', t.bpm > 0),
                    ('vocals', self._vocal_status(t) != 'unknown'), ('energy', self._energy_level(t) > 0),
                    ('scene', bool(values(t.dj_scene)) and values(t.dj_scene) <= set(self.scenes))] if not known],
                **item} for t,item in zip(final_flow, evidence)]
        if export:
            play_target, exported_count = self._export_to_m3u(final_flow)
        else:
            play_target, exported_count = '', len(final_flow)
        if exported_count <= 0 or (export and not play_target):
            log.error("Playlist export produced no playable tracks.")
            return None

        return CuratedPlayback(
            play_target=play_target,
            requested_type=criteria_type,
            requested_value=criteria_value,
            resolved_value=resolved_value,
            matched_tracks=len(pool),
            filtered_tracks=len(filtered_pool),
            exported_tracks=exported_count,
            fallback_applied=fallback_applied,
            fallback_reason=fallback_reason,
            total_duration_ms=sum(track.total_time for track in final_flow),
            unknown_duration_tracks=sum(track.total_time == 0 for track in final_flow),
            unknown_bpm_tracks=sum(track.bpm == 0 for track in final_flow),
            unknown_vocal_tag_tracks=sum(self._vocal_status(track) == 'unknown' for track in final_flow),
            repeat_spacing_relaxations=self.sequence_relaxations,
            unknown_energy_tag_tracks=sum(self._energy_level(t) == 0 for t in final_flow),
            unknown_scene_tag_tracks=sum(not values(t.dj_scene) or not values(t.dj_scene) <= set(self.scenes) for t in final_flow),
            selection_diagnostics=self.last_diagnostics,
        )

    def _resolve_scene_name(self, raw_scene: str) -> Tuple[str, bool, str]:
        scene = raw_scene.lower().strip()
        if scene in self.scenes:
            return scene, False, ""

        if scene in self.scene_aliases and self.scene_aliases[scene] in self.scenes:
            resolved = self.scene_aliases[scene]
            return resolved, True, f"scene alias {scene} -> {resolved}"

        clauses = re.split(r"[,，;；。]", scene)
        positive = [part.strip() for part in clauses if part.strip() and not re.match(
            r"^(?:不要|不想|别|避免|不听|without\b|not\b|no\b)", part.strip())]
        resolved_scenes = set()
        aliases = {**{key: key for key in self.scenes}, **self.scene_aliases}
        for clause in positive:
            hits = []
            for alias, resolved in aliases.items():
                if not alias or resolved not in self.scenes:
                    continue
                match = (re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", clause)
                         if alias.isascii() else alias in clause)
                if match:
                    hits.append((len(alias), resolved))
            if hits:
                longest = max(length for length, _ in hits)
                resolved_scenes.update(resolved for length, resolved in hits if length == longest)
        if len(resolved_scenes) == 1:
            resolved = resolved_scenes.pop()
            return resolved, True, f"scene phrase {scene} -> {resolved}"
        return scene, False, ""

    @staticmethod
    def _genre_term(value):
        term = value.lower().strip()
        return {"爵士": "jazz", "古典": "classical", "摇滚": "rock", "电音": "edm"}.get(term, term)

    def _retrieve_base_tracks(self, library: List[Track], criteria_type: str, criteria_value: str) -> Tuple[List[Track], str, bool, str]:
        matched: List[Track] = []
        val_lower = self._genre_term(criteria_value)
        fallback_applied = False
        fallback_reason = ""
        resolved_value = criteria_value

        if criteria_type == 'genre':
            matched = [track for track in library if val_lower in track.genre.lower()]
        elif criteria_type == 'scene':
            resolved_scene, fallback_applied, fallback_reason = self._resolve_scene_name(criteria_value)
            resolved_value = resolved_scene
            if resolved_scene in self.scenes:
                target_genres = [genre.lower() for genre in self.scenes[resolved_scene].get('genres', [])]
                for track in library:
                    track_genre_lower = track.genre.lower()
                    explicit = track.dj_scene.strip()
                    if explicit:
                        # Exact canonical identifiers only. Unknown, invalid or negated
                        # labels cannot silently inherit a matching legacy Genre.
                        tags = {part.strip().casefold() for part in explicit.split(';') if part.strip()}
                        if tags and tags <= set(self.scenes) and resolved_scene in tags:
                            matched.append(track)
                    elif any(target_genre in track_genre_lower for target_genre in target_genres):
                        matched.append(track)
            else:
                log.warning(f"Scene '{resolved_scene}' is not mapped in config.yaml.")

        return matched, resolved_value, fallback_applied, fallback_reason

    @staticmethod
    def _vocal_status(track):
        # An explicit reviewed field overrides legacy Genre, including explicit unknown.
        # Invalid/compound values stay unknown; never infer instrumental from substrings.
        explicit = track.dj_vocals.strip().casefold()
        if explicit:
            return explicit if explicit in {'vocal', 'instrumental', 'unknown'} else 'unknown'
        genre = track.genre.casefold().replace('non-vocal', 'instrumental').replace('无人声', '器乐')
        if any(term in genre for term in ('vocal', 'opera', 'choir', '人声', '声乐', '合唱', '歌剧')):
            return 'vocal'
        if any(term in genre for term in ('instrumental', 'pure music', '纯音乐', '器乐', '无歌词')):
            return 'instrumental'
        return 'unknown'

    @staticmethod
    def _energy_level(track):
        # Owner-reviewed qualitative metadata; neither a BPM measurement nor loudness.
        return {'low': 1, 'medium': 2, 'high': 3}.get(track.dj_energy.strip().casefold(), 0)

    def _metadata_rejection(self, track):
        if self.strict_evidence:
            if self.score_scene and (not values(track.dj_scene) or not values(track.dj_scene) <= set(self.scenes) or self.score_scene not in values(track.dj_scene)):
                return 'missing_required_explicit_scene'
            if self.score_intensity in {'low', 'high'} and self._energy_level(track) == 0:
                return 'missing_required_explicit_energy'
            if self.no_vocals and track.dj_vocals.strip().casefold() != 'instrumental':
                return 'missing_required_explicit_instrumental'
        if self.no_vocals and self._vocal_status(track) != 'instrumental':
            return 'unknown_or_vocal_for_no_vocals'
        if self.bpm_min is not None or self.bpm_max is not None:
            if track.bpm <= 0:
                return 'unknown_bpm_for_required_range'
            if self.bpm_min is not None and track.bpm < self.bpm_min or self.bpm_max is not None and track.bpm > self.bpm_max:
                return 'outside_required_bpm_range'
        language = values(track.language, LANGUAGE_ALIASES)
        if self.languages or self.excluded_languages:
            if self._vocal_status(track) != 'instrumental':
                if not language:
                    return 'unknown_language_for_required_constraint'
                if self.languages and not language & self.languages:
                    return 'required_language_mismatch'
                if language & self.excluded_languages:
                    return 'excluded_language'
        if self.moods and not values(track.mood, MOOD_ALIASES) & self.moods:
            return 'required_mood_unknown_or_mismatch'
        return ''

    def _track_evidence(self, track):
        components = {}
        scene_cfg = self.scenes.get(self.score_scene, {}) if self.score_scene else {}
        if self.score_scene:
            if track.dj_scene.strip():
                tags = values(track.dj_scene)
                valid = bool(tags) and tags <= set(self.scenes)
                components['scene'] = (float(valid and self.score_scene in tags), float(valid), 'DJ_SCENE' if valid else 'unknown_or_invalid')
            else:
                matched = any(g.lower() in track.genre.lower() for g in scene_cfg.get('genres', []))
                components['scene'] = (float(matched), .4 if matched else 0, 'weak_Genre_fallback' if matched else 'missing')
        target_moods = self.moods | self.preferred_moods or set(scene_cfg.get('moods', []))
        scoring_moods = target_moods - AROUSAL_MOODS if self.score_intensity in {'low', 'high'} else target_moods
        if scoring_moods:
            actual = values(track.mood, MOOD_ALIASES)
            if self.score_intensity in {'low', 'high'}:
                actual -= AROUSAL_MOODS
            components['mood'] = (float(bool(actual & scoring_moods)), .8 if actual else 0, 'Mood' if actual else 'missing')
        if self.score_intensity in {'low', 'high'}:
            level = self._energy_level(track)
            desired = 1 if self.score_intensity == 'low' else 3
            components['energy'] = (float(level == desired), float(level > 0), 'DJ_ENERGY' if level else 'missing')
        genres = [self.score_genre] if self.score_genre else scene_cfg.get('genres', [])
        if genres:
            known = track.genre.strip().casefold() not in {'', 'unknown'}
            components['genre'] = (float(any(g.lower() in track.genre.lower() for g in genres)), .6 if known else 0, 'Genre' if known else 'missing')
        if self.bpm_min is not None or self.bpm_max is not None:
            known = track.bpm > 0
            components['tempo'] = (float(known and (self.bpm_min is None or track.bpm >= self.bpm_min) and (self.bpm_max is None or track.bpm <= self.bpm_max)), float(known), 'BPM' if known else 'missing')
        result = evidence_score(components)
        result['preferred_language_match'] = bool(self.preferred_languages and values(track.language, LANGUAGE_ALIASES) & self.preferred_languages)
        return result

    def _filter_by_intensity(self, tracks: List[Track], intensity: str) -> List[Track]:
        filtered = []
        for track in tracks:
            bpm = track.bpm
            genre_lower = track.genre.lower()
            if any(term in genre_lower for term in self.excluded_genres):
                continue
            if any(term in track.artist.lower() for term in self.excluded_artists):
                continue
            if any(term in track.name.lower() for term in self.excluded_tracks):
                continue
            if any(term in track.album.lower() for term in self.excluded_albums):
                continue
            if self.no_vocals and self._vocal_status(track) != 'instrumental':
                continue
            if self._metadata_rejection(track):
                continue

            if track.dj_energy.strip() and intensity in {'low', 'high'}:
                required_level = 1 if intensity == 'low' else 3
                if self._energy_level(track) == required_level:
                    filtered.append(track)
                # Explicit unknown/invalid stays unknown, even with a convenient BPM/Genre.
                continue

            if intensity == 'high':
                if bpm > 0 and bpm < self.high_min_bpm:
                    continue
                if any(token in genre_lower for token in self.high_intensity_exclude):
                    continue
            elif intensity == 'low':
                if bpm > 0 and bpm > self.low_max_bpm:
                    continue
                if any(token in genre_lower for token in self.low_intensity_exclude):
                    continue

            filtered.append(track)
        return filtered

    def _select_ratio_tracks(self, tracks: List[Track], total_needed: int) -> List[Track]:
        pools = [
            [track for track in tracks if track.play_count > 5],
            [track for track in tracks if track.play_count <= 2],
            sorted([track for track in tracks if self._extract_date(track.date_added) != datetime.min],
                   key=lambda track: self._extract_date(track.date_added), reverse=True)[:max(
                       math.ceil(len(tracks)*.1), math.ceil(total_needed*self.novelty_ratio))],
        ]
        self.rng.shuffle(pools[0])
        self.rng.shuffle(pools[1])
        for pool in pools:
            pool.sort(key=lambda track: (-self._track_evidence(track)['match_score'],
                -self._track_evidence(track)['evidence_coverage'],
                not self._track_evidence(track)['preferred_language_match'],
                not any(term in track.artist.lower() for term in self.preferred_artists)))
        weights = [self.anchor_ratio, self.discovery_ratio, self.novelty_ratio]
        raw_quotas = [total_needed * weight for weight in weights]
        quotas = [math.floor(value) for value in raw_quotas]
        for index in sorted(range(3), key=lambda i: raw_quotas[i] - quotas[i], reverse=True)[:total_needed - sum(quotas)]:
            quotas[index] += 1

        selected: List[Track] = []
        selected_paths = set()
        selected_recordings = set()
        self.selection_buckets = {}
        self.quota_target = dict(zip(['anchor', 'discovery', 'novelty'], quotas))

        def take(pool, limit, bucket):
            count = 0
            for track in pool:
                if count >= limit or len(selected) >= total_needed:
                    break
                key = os.path.normcase(os.path.normpath(track.local_path))
                recording = self._recording_key(track)
                if key not in selected_paths and recording not in selected_recordings:
                    selected.append(track)
                    selected_paths.add(key)
                    selected_recordings.add(recording)
                    self.selection_buckets[key] = bucket
                    count += 1

        # Reserve the newest quota before it can be consumed by the other overlapping pools.
        for index in (2, 0, 1):
            take(pools[index], quotas[index], ['anchor', 'discovery', 'novelty'][index])
        remaining = tracks.copy()
        self.rng.shuffle(remaining)
        remaining.sort(key=lambda track: (-self._track_evidence(track)['match_score'],
            -self._track_evidence(track)['evidence_coverage'],
            not self._track_evidence(track)['preferred_language_match'],
            not any(term in track.artist.lower() for term in self.preferred_artists)))
        take(remaining, total_needed - len(selected), 'fill')
        return selected

    @staticmethod
    def _artist_keys(track):
        return {re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', part).casefold()).strip()
                for part in track.artist.split(';')
                if part.strip() and part.strip().casefold() != 'unknown'}

    @staticmethod
    def _recording_key(track):
        artist = tuple(sorted(DJCurator._artist_keys(track)))
        title = unicodedata.normalize('NFKC', track.name).casefold().strip()
        if not artist or title in {'', 'unknown'}:
            return ('path', os.path.normcase(os.path.normpath(track.local_path)))
        normalize = lambda value: unicodedata.normalize('NFKC', value).casefold().strip()
        work, movement, composer = normalize(track.work), normalize(track.movement_name), normalize(track.composer)
        context = (work, movement, composer)
        work_context_present = work not in {'', 'unknown'} or movement not in {'', 'unknown'}
        if (DJCurator._style_group(track) in {'classical', 'unknown', ''} or work_context_present) and (work in {'', 'unknown'} or movement in {'', 'unknown'}):
            # A generic tempo title can describe different movements; do not infer identity from it.
            return ('path', os.path.normcase(os.path.normpath(track.local_path)))
        # Strip only explicit recording-version suffixes, preserving work/movement numbers.
        title = re.sub(
            r'\s*[\(\[](?:(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?|'
            r'live(?:\s+(?:version|recording|at\s+[^\)\]]+))?|(?:\d{4}\s*)?(?:重制|现场)(?:版|录音)?)'
            r'[\)\]]\s*$', '', title,
        )
        return (artist, re.sub(r'\s+', ' ', title), context)

    @staticmethod
    def _style_group(track):
        genre = track.genre.casefold()
        for group, tokens in [('ambient', ('ambient', 'pure music', '纯音乐')),
                              ('classical', ('classical', '古典')),
                              ('jazz', ('jazz', '爵士')), ('rock', ('rock', '摇滚'))]:
            if any(token in genre for token in tokens):
                return group
        return genre

    def _build_energy_curve(self, tracks: List[Track], scene: str = 'normal', intensity: str = 'normal') -> List[Track]:
        """Metadata-only ordering: steady focus, ascending known-BPM energy, varied pop."""
        remaining = tracks.copy()
        self.rng.shuffle(remaining)
        self.sequence_relaxations = 0
        flow = []
        steady = scene in {'focus', 'relax', 'coding'} or intensity == 'low'
        ramp = not steady and (scene == 'energy' or intensity == 'high')
        known = [track.bpm for track in tracks if track.bpm > 0]
        target = max(known) if steady and known else (sorted(known)[len(known) // 2] if known else 0)
        levels = sorted(self._energy_level(track) for track in tracks if self._energy_level(track))
        target_level = levels[len(levels) // 2] if levels else 0
        while remaining:
            recent_artists = {artist for track in flow[-2:] for artist in self._artist_keys(track)}
            recent_albums = {(artist, track.album.casefold().strip()) for track in flow[-2:]
                             for artist in self._artist_keys(track) if track.album.casefold().strip() not in {'', 'unknown'}}
            candidates = [track for track in remaining
                          if not self._artist_keys(track).intersection(recent_artists)
                          and not {(artist, track.album.casefold().strip()) for artist in self._artist_keys(track)}.intersection(recent_albums)]
            if not candidates:
                candidates = remaining
                self.sequence_relaxations += 1

            counts = Counter(artist for track in remaining for artist in self._artist_keys(track))

            def cost(track):
                # Reserve scarce spacing slots before rare artists consume them.
                urgent = any((counts[artist] - 1) * 3 + 1 >= len(remaining) for artist in self._artist_keys(track))
                style_change = bool(flow and self._style_group(track) != self._style_group(flow[-1]))
                previous_moods = values(flow[-1].mood, MOOD_ALIASES) - AROUSAL_MOODS if flow else set()
                track_moods = values(track.mood, MOOD_ALIASES) - AROUSAL_MOODS
                mood_change = bool(previous_moods and track_moods and not previous_moods & track_moods)
                level = self._energy_level(track)
                if ramp:
                    if levels:
                        return (not urgent, level == 0, level, track.bpm == 0, track.bpm, style_change)
                    return (not urgent, track.bpm == 0, track.bpm, style_change)
                delta = abs(track.bpm - (flow[-1].bpm if flow and flow[-1].bpm > 0 else target)) if track.bpm > 0 else 100
                if levels:
                    prior_level = self._energy_level(flow[-1]) if flow else 0
                    level_delta = abs(level - (prior_level or target_level)) if level else 4
                    return (not urgent, level_delta, mood_change, style_change if steady else False, delta, track.bpm == 0)
                return (not urgent, mood_change, style_change if steady else False, delta, track.bpm == 0)

            next_track = min(candidates, key=cost)
            flow.append(next_track)
            remaining.remove(next_track)
        if self.sequence_relaxations:
            log.warning(f'Ordering: repeat spacing relaxed {self.sequence_relaxations} times due to candidate shortages.')
        return flow

    def _export_to_m3u(self, tracks: List[Track]) -> Tuple[str, int]:
        os.makedirs(os.path.dirname(self.m3u_path), exist_ok=True)
        tmp_path = self.m3u_path + ".tmp"

        exported_count = 0
        with open(tmp_path, "w", encoding="utf-8-sig") as handle:
            handle.write("#EXTM3U\n")
            for track in tracks:
                if exported_count >= self.max_tracks:
                    break
                if track.is_valid:
                    label = f"{track.artist} - {track.name}".replace("\r", " ").replace("\n", " ")
                    handle.write(f"#EXTINF:-1,{label}\n")
                    handle.write(f"{track.local_path}\n")
                    exported_count += 1

        os.replace(tmp_path, self.m3u_path)
        log.info(f"JIT Playlist successfully curated: {exported_count} tracks exported (max {self.max_tracks}).")
        return self.m3u_path, exported_count
