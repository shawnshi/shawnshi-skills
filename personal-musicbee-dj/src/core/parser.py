import json
import os
import re
from urllib.parse import unquote, urlparse
from typing import List, Optional
from src.core.models import Track
from src.utils.logger import log

class MusicBeeParserError(Exception):
    """Raised when iTunes XML parsing fails or file is not found."""
    pass

class MusicBeeParser:
    def __init__(self, xml_path: str, cache_path: str):
        self.xml_path = xml_path
        self.cache_path = cache_path

    def load_library(self) -> List[Track]:
        """
        Loads the library either from the fast JSON cache or by parsing the XML.
        Returns a strongly-typed list of Track objects.
        """
        if not os.path.exists(self.xml_path):
            log.error(f"iTunes XML not found at: {self.xml_path}")
            raise MusicBeeParserError("Please enable 'Share iTunes compatible library XML' in MusicBee settings.")

        # Check cache freshness
        if os.path.exists(self.cache_path):
            xml_mtime = os.path.getmtime(self.xml_path)
            cache_mtime = os.path.getmtime(self.cache_path)
            if cache_mtime > xml_mtime:
                log.debug("Cache is up-to-date. Loading from cache...")
                try:
                    with open(self.cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        return [Track(**t) for t in data]
                except json.JSONDecodeError:
                    log.warning("Cache is corrupted. Forcing XML rebuild.")

        return self._parse_and_cache_xml()

    def _parse_and_cache_xml(self) -> List[Track]:
        log.info(f"Generating new cache from XML: {self.xml_path}")
        library: List[Track] = []

        try:
            with open(self.xml_path, 'r', encoding='utf-8') as f:
                xml_data = f.read()

            tracks_match = re.search(r'<key>Tracks</key>\s*<dict>(.*?)</dict>\s*<key>Playlists</key>', xml_data, re.DOTALL)
            if not tracks_match:
                raise MusicBeeParserError("Could not find <Tracks> section in iTunes XML.")

            tracks_chunk = tracks_match.group(1)

            for track_dict_match in re.finditer(r'<key>\d+</key>\s*<dict>(.*?)</dict>', tracks_chunk, re.DOTALL):
                track_content = track_dict_match.group(1)

                # Skip if no Location
                location_match = re.search(r'<key>Location</key>\s*<string>(.*?)</string>', track_content)
                if not location_match:
                    continue

                location = location_match.group(1)
                parsed_url = urlparse(location)
                local_path = unquote(parsed_url.path)

                if local_path.startswith('/'):
                    if len(local_path) > 2 and local_path[2] == ':':
                        local_path = local_path[1:]
                local_path = local_path.replace('/', '\\')

                # Regex Builders
                def get_str(key_en: str, key_zh: str, default: str = 'Unknown') -> str:
                    m = re.search(fr'<key>({key_en}|{key_zh})</key>\s*<string>(.*?)</string>', track_content)
                    return m.group(2) if m else default

                def get_int(key_en: str, key_zh: str, default: int = 0) -> int:
                    m = re.search(fr'<key>({key_en}|{key_zh})</key>\s*<integer>(\d+).*?</integer>', track_content)
                    return int(m.group(2)) if m else default

                def get_date(key_en: str, key_zh: str, default: str = 'Unknown') -> str:
                    m = re.search(fr'<key>({key_en}|{key_zh})</key>\s*<date>(.*?)</date>', track_content)
                    return m.group(2) if m else default

                track = Track(
                    id=get_int('Track ID', '轨迹 ID'),
                    name=get_str('Name', '名称'),
                    artist=get_str('Artist', '艺术家'),
                    album=get_str('Album', '专辑'),
                    genre=get_str('Genre', '流派'),
                    play_count=get_int('Play Count', '播放次数'),
                    bpm=get_int('BPM', 'BPM'),
                    total_time=get_int('Total Time', '总时间'),
                    date_added=get_date('Date Added', '添加日期'),
                    local_path=local_path
                )
                library.append(track)

            # Atomic Cache Write
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp_path = self.cache_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump([t.__dict__ for t in library], f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cache_path)

            log.info(f"Cache built successfully: {len(library)} tracks indexed.")
            return library

        except Exception as e:
            log.error(f"Critical error during XML parsing: {str(e)}")
            raise MusicBeeParserError(f"Failed to parse XML: {e}")
