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
        import xml.etree.ElementTree as ET
        log.info(f"Generating new cache from XML: {self.xml_path}")
        library: List[Track] = []

        try:
            context = ET.iterparse(self.xml_path, events=('end',))
            in_tracks = False
            for event, elem in context:
                if elem.tag == 'key' and elem.text == 'Tracks':
                    in_tracks = True
                    elem.clear()
                    continue
                if elem.tag == 'key' and elem.text == 'Playlists':
                    in_tracks = False
                    elem.clear()
                    break

                if in_tracks and elem.tag == 'dict':
                    # Parse the track dict
                    track_data = {}
                    current_key = None
                    for child in elem:
                        if child.tag == 'key':
                            current_key = child.text
                        elif current_key:
                            if child.tag == 'string':
                                track_data[current_key] = child.text
                            elif child.tag == 'integer':
                                try:
                                    track_data[current_key] = int(child.text)
                                except (ValueError, TypeError):
                                    track_data[current_key] = 0
                            elif child.tag == 'date':
                                track_data[current_key] = child.text
                            current_key = None

                    elem.clear()

                    if not track_data:
                        continue

                    location = track_data.get('Location')
                    if not location:
                        continue

                    parsed_url = urlparse(location)
                    local_path = unquote(parsed_url.path)

                    if local_path.startswith('/'):
                        if len(local_path) > 2 and local_path[2] == ':':
                            local_path = local_path[1:]
                    local_path = local_path.replace('/', '\\')

                    track = Track(
                        id=track_data.get('Track ID') or track_data.get('轨迹 ID') or 0,
                        name=track_data.get('Name') or track_data.get('名称') or 'Unknown',
                        artist=track_data.get('Artist') or track_data.get('艺术家') or 'Unknown',
                        album=track_data.get('Album') or track_data.get('专辑') or 'Unknown',
                        genre=track_data.get('Genre') or track_data.get('流派') or 'Unknown',
                        play_count=track_data.get('Play Count') or track_data.get('播放次数') or 0,
                        bpm=track_data.get('BPM') or track_data.get('BPM') or 0,
                        total_time=track_data.get('Total Time') or track_data.get('总时间') or 0,
                        date_added=track_data.get('Date Added') or track_data.get('添加日期') or 'Unknown',
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
