import os
import random
from datetime import datetime
from typing import List, Dict, Any, Optional

from src.core.models import Track
from src.core.parser import MusicBeeParser, MusicBeeParserError
from src.utils.logger import log

class DJCurator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        playlist_cfg = config.get('playlist', {})
        energy_cfg = config.get('energy_curves', {})
        
        self.m3u_path = playlist_cfg.get('output_m3u', 'C:\\Users\\shich\\.gemini\\tmp\\musicbee_jit_queue.m3u')
        self.max_tracks = playlist_cfg.get('max_tracks_per_session', 100)
        
        curation = playlist_cfg.get('curation', {})
        self.anchor_ratio = curation.get('anchor_ratio', 0.6)
        self.discovery_ratio = curation.get('discovery_ratio', 0.3)
        self.novelty_ratio = curation.get('novelty_ratio', 0.1)
        
        self.high_min_bpm = energy_cfg.get('high_intensity_min_bpm', 110)
        self.low_max_bpm = energy_cfg.get('low_intensity_max_bpm', 100)
        
        self.scenes = config.get('scenes', {})

        xml_path = config.get('musicbee', {}).get('xml_path', '')
        cache_path = config.get('cache', {}).get('db_path', '')
        self.parser = MusicBeeParser(xml_path=xml_path, cache_path=cache_path)

    def _extract_date(self, date_str: str) -> datetime:
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        except:
            return datetime.min

    def generate_m3u(self, criteria_type: str, criteria_value: str, intensity: str = 'normal') -> Optional[str]:
        """
        Orchestrates the curation flow: Fetch -> Filter -> Sort -> Export.
        """
        try:
            library = self.parser.load_library()
        except MusicBeeParserError as e:
            log.error(f"Cannot generate playlist due to parser error: {e}")
            return None

        # 1. Base Retrieval
        pool = self._retrieve_base_tracks(library, criteria_type, criteria_value)
        if not pool:
            log.warning(f"No tracks found matching {criteria_type} = {criteria_value}")
            return None

        # 2. Intensity Filtering
        pool = self._filter_by_intensity(pool, intensity)
        if not pool:
            log.warning(f"No tracks remained after applying intensity filter: {intensity}")
            return None

        # 3. Ratio-based Curation
        target_len = min(len(pool), self.max_tracks)
        curated_tracks = self._select_ratio_tracks(pool, target_len)

        # 4. Momentum Sorting
        scene_type = criteria_value.lower() if criteria_type == 'scene' else 'normal'
        final_flow = self._build_energy_curve(curated_tracks, scene=scene_type, intensity=intensity)

        # 5. Export M3U Atomically
        return self._export_to_m3u(final_flow)

    def _retrieve_base_tracks(self, library: List[Track], criteria_type: str, criteria_value: str) -> List[Track]:
        matched = []
        val_lower = criteria_value.lower()
        
        if criteria_type == 'genre':
            matched = [t for t in library if val_lower in t.genre.lower()]
        elif criteria_type == 'scene':
            if val_lower in self.scenes:
                target_genres = [g.lower() for g in self.scenes[val_lower].get('genres', [])]
                for t in library:
                    t_genre_lower = t.genre.lower()
                    if any(tg in t_genre_lower for tg in target_genres):
                        matched.append(t)
            else:
                log.warning(f"Scene '{val_lower}' is not mapped in config.yaml.")
                
        return matched

    def _filter_by_intensity(self, tracks: List[Track], intensity: str) -> List[Track]:
        filtered = []
        for t in tracks:
            bpm = t.bpm
            genre_lower = t.genre.lower()
            
            if intensity == 'high':
                if bpm > 0 and bpm < self.high_min_bpm:
                    continue
                if any(x in genre_lower for x in ['ambient', 'chill', 'intro']):
                    continue
            elif intensity == 'low':
                if bpm > 0 and bpm > self.low_max_bpm:
                    continue
                if any(x in genre_lower for x in ['metal', 'rock', 'edm']):
                    continue
                    
            filtered.append(t)
        return filtered

    def _select_ratio_tracks(self, tracks: List[Track], total_needed: int) -> List[Track]:
        anchors = [t for t in tracks if t.play_count > 5]
        discoveries = [t for t in tracks if t.play_count <= 2]
        novelty_pool = sorted(tracks, key=lambda x: self._extract_date(x.date_added), reverse=True)
        
        needed_anchors = int(total_needed * self.anchor_ratio)
        needed_discoveries = int(total_needed * self.discovery_ratio)
        
        selected: List[Track] = []
        
        random.shuffle(anchors)
        random.shuffle(discoveries)
        
        selected.extend(anchors[:needed_anchors])
        selected.extend(discoveries[:needed_discoveries])
        
        selected_ids = {t.id for t in selected}
        for t in novelty_pool:
            if len(selected) >= total_needed:
                break
            if t.id not in selected_ids:
                selected.append(t)
                selected_ids.add(t.id)
                
        # Fill remainder
        if len(selected) < total_needed:
            random.shuffle(tracks)
            for t in tracks:
                if len(selected) >= total_needed:
                    break
                if t.id not in selected_ids:
                    selected.append(t)
                    selected_ids.add(t.id)
                    
        return selected

    def _build_energy_curve(self, tracks: List[Track], scene: str = 'normal', intensity: str = 'normal') -> List[Track]:
        bpm_tracks = sorted([t for t in tracks if t.bpm > 0], key=lambda x: x.bpm)
        no_bpm_tracks = [t for t in tracks if t.bpm == 0]
        
        random.shuffle(no_bpm_tracks)
        
        if len(bpm_tracks) < 5:
            all_tracks = tracks.copy()
            random.shuffle(all_tracks)
            return all_tracks
            
        num = len(bpm_tracks)
        warmup_idx = int(num * 0.15)
        
        warmup = bpm_tracks[:warmup_idx]
        cooldown = bpm_tracks[warmup_idx:warmup_idx + int(num*0.15)]
        peak = bpm_tracks[warmup_idx + int(num*0.15):]
        
        random.shuffle(warmup)
        random.shuffle(peak)
        random.shuffle(cooldown)
        
        final_flow = warmup + peak + cooldown
        
        for i, track in enumerate(no_bpm_tracks):
            insert_pos = (i * 3) % (len(final_flow) + 1)
            final_flow.insert(insert_pos, track)
            
        if scene == 'relax' or intensity == 'low':
            intro_candidates = [t for t in final_flow if 'intro' in t.name.lower() or 'prelude' in t.name.lower()]
            if intro_candidates:
                intro = intro_candidates[0]
                final_flow.remove(intro)
                final_flow.insert(0, intro)
                
        return final_flow

    def _export_to_m3u(self, tracks: List[Track]) -> str:
        os.makedirs(os.path.dirname(self.m3u_path), exist_ok=True)
        tmp_path = self.m3u_path + ".tmp"
        
        exported_count = 0
        with open(tmp_path, "w", encoding="utf-8-sig") as f:
            f.write("#EXTM3U\n")
            for t in tracks:
                if t.is_valid:
                    f.write(f"#EXTINF:-1,{t.artist} - {t.name}\n")
                    f.write(f"{t.local_path}\n")
                    exported_count += 1
                    
        os.replace(tmp_path, self.m3u_path)
        log.info(f"JIT Playlist successfully curated: {exported_count} tracks exported.")
        return self.m3u_path
