import os
import random
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from src.core.models import Track, CuratedPlayback
from src.core.parser import MusicBeeParser, MusicBeeParserError
from src.utils.logger import log


class DJCurator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

        playlist_cfg = config.get('playlist', {})
        energy_cfg = config.get('energy_curves', {})
        fallback_cfg = config.get('fallback', {})

        self.m3u_path = playlist_cfg.get('output_m3u', 'C:\\Users\\shich\\.gemini\\tmp\\musicbee_jit_queue.m3u')
        self.max_tracks = playlist_cfg.get('max_tracks_per_session', 100)

        curation = playlist_cfg.get('curation', {})
        self.anchor_ratio = curation.get('anchor_ratio', 0.6)
        self.discovery_ratio = curation.get('discovery_ratio', 0.3)
        self.novelty_ratio = curation.get('novelty_ratio', 0.1)

        self.high_min_bpm = energy_cfg.get('high_intensity_min_bpm', 110)
        self.low_max_bpm = energy_cfg.get('low_intensity_max_bpm', 100)

        self.scenes = config.get('scenes', {})
        self.default_scene = str(fallback_cfg.get('default_scene', 'pop')).lower()
        self.scene_aliases = {
            str(key).lower(): str(value).lower()
            for key, value in fallback_cfg.get('aliases', {}).items()
        }

        xml_path = config.get('musicbee', {}).get('xml_path', '')
        cache_path = config.get('cache', {}).get('db_path', '')
        self.parser = MusicBeeParser(xml_path=xml_path, cache_path=cache_path)

    def _extract_date(self, date_str: str) -> datetime:
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return datetime.min

    def generate_m3u(self, criteria_type: str, criteria_value: str, intensity: str = 'normal') -> Optional[CuratedPlayback]:
        try:
            library = self.parser.load_library()
        except MusicBeeParserError as exc:
            log.error(f"Cannot generate playlist due to parser error: {exc}")
            return None

        pool, resolved_value, fallback_applied, fallback_reason = self._retrieve_base_tracks(
            library, criteria_type, criteria_value
        )
        if not pool:
            log.warning(f"No tracks found matching {criteria_type} = {criteria_value}")
            return None

        filtered_pool = self._filter_by_intensity(pool, intensity)
        if not filtered_pool:
            log.warning(f"No tracks remained after applying intensity filter: {intensity}")
            return None

        target_len = min(len(filtered_pool), self.max_tracks)
        curated_tracks = self._select_ratio_tracks(filtered_pool, target_len)
        scene_type = resolved_value.lower() if criteria_type == 'scene' else 'normal'
        final_flow = self._build_energy_curve(curated_tracks, scene=scene_type, intensity=intensity)

        play_target, exported_count = self._export_to_m3u(final_flow)
        if not play_target or exported_count <= 0:
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
        )

    def _resolve_scene_name(self, raw_scene: str) -> Tuple[str, bool, str]:
        scene = raw_scene.lower().strip()
        if scene in self.scenes:
            return scene, False, ""

        if scene in self.scene_aliases and self.scene_aliases[scene] in self.scenes:
            resolved = self.scene_aliases[scene]
            return resolved, True, f"scene alias {scene} -> {resolved}"

        for alias, resolved in self.scene_aliases.items():
            if alias in scene and resolved in self.scenes:
                return resolved, True, f"semantic fallback {scene} -> {resolved}"

        if self.default_scene in self.scenes:
            return self.default_scene, True, f"default fallback {scene} -> {self.default_scene}"

        return scene, False, ""

    def _retrieve_base_tracks(self, library: List[Track], criteria_type: str, criteria_value: str) -> Tuple[List[Track], str, bool, str]:
        matched: List[Track] = []
        val_lower = criteria_value.lower()
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
                    if any(target_genre in track_genre_lower for target_genre in target_genres):
                        matched.append(track)
            else:
                log.warning(f"Scene '{resolved_scene}' is not mapped in config.yaml.")

        return matched, resolved_value, fallback_applied, fallback_reason

    def _filter_by_intensity(self, tracks: List[Track], intensity: str) -> List[Track]:
        filtered = []
        for track in tracks:
            bpm = track.bpm
            genre_lower = track.genre.lower()

            if intensity == 'high':
                if bpm > 0 and bpm < self.high_min_bpm:
                    continue
                if any(token in genre_lower for token in ['ambient', 'chill', 'intro']):
                    continue
            elif intensity == 'low':
                if bpm > 0 and bpm > self.low_max_bpm:
                    continue
                if any(token in genre_lower for token in ['metal', 'rock', 'edm']):
                    continue

            filtered.append(track)
        return filtered

    def _select_ratio_tracks(self, tracks: List[Track], total_needed: int) -> List[Track]:
        anchors = [track for track in tracks if track.play_count > 5]
        discoveries = [track for track in tracks if track.play_count <= 2]
        novelty_pool = sorted(tracks, key=lambda track: self._extract_date(track.date_added), reverse=True)

        needed_anchors = int(total_needed * self.anchor_ratio)
        needed_discoveries = int(total_needed * self.discovery_ratio)

        selected: List[Track] = []

        random.shuffle(anchors)
        random.shuffle(discoveries)

        selected.extend(anchors[:needed_anchors])
        selected.extend(discoveries[:needed_discoveries])

        selected_ids = {track.id for track in selected}
        for track in novelty_pool:
            if len(selected) >= total_needed:
                break
            if track.id not in selected_ids:
                selected.append(track)
                selected_ids.add(track.id)

        if len(selected) < total_needed:
            random.shuffle(tracks)
            for track in tracks:
                if len(selected) >= total_needed:
                    break
                if track.id not in selected_ids:
                    selected.append(track)
                    selected_ids.add(track.id)

        return selected

    def _build_energy_curve(self, tracks: List[Track], scene: str = 'normal', intensity: str = 'normal') -> List[Track]:
        bpm_tracks = sorted([track for track in tracks if track.bpm > 0], key=lambda track: track.bpm)
        no_bpm_tracks = [track for track in tracks if track.bpm == 0]

        random.shuffle(no_bpm_tracks)

        if len(bpm_tracks) < 5:
            all_tracks = tracks.copy()
            random.shuffle(all_tracks)
            return all_tracks

        num = len(bpm_tracks)
        warmup_idx = int(num * 0.15)

        warmup = bpm_tracks[:warmup_idx]
        cooldown = bpm_tracks[warmup_idx:warmup_idx + int(num * 0.15)]
        peak = bpm_tracks[warmup_idx + int(num * 0.15):]

        random.shuffle(warmup)
        random.shuffle(peak)
        random.shuffle(cooldown)

        final_flow = warmup + peak + cooldown

        for index, track in enumerate(no_bpm_tracks):
            insert_pos = (index * 3) % (len(final_flow) + 1)
            final_flow.insert(insert_pos, track)

        if scene == 'relax' or intensity == 'low':
            intro_candidates = [track for track in final_flow if 'intro' in track.name.lower() or 'prelude' in track.name.lower()]
            if intro_candidates:
                intro = intro_candidates[0]
                final_flow.remove(intro)
                final_flow.insert(0, intro)

        return final_flow

    def _export_to_m3u(self, tracks: List[Track]) -> Tuple[str, int]:
        os.makedirs(os.path.dirname(self.m3u_path), exist_ok=True)
        tmp_path = self.m3u_path + ".tmp"

        exported_count = 0
        with open(tmp_path, "w", encoding="utf-8-sig") as handle:
            handle.write("#EXTM3U\n")
            for track in tracks:
                if track.is_valid:
                    handle.write(f"#EXTINF:-1,{track.artist} - {track.name}\n")
                    handle.write(f"{track.local_path}\n")
                    exported_count += 1

        os.replace(tmp_path, self.m3u_path)
        log.info(f"JIT Playlist successfully curated: {exported_count} tracks exported.")
        return self.m3u_path, exported_count
