import json
import os
import ntpath
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import List
import re
from src.core.models import Track
from src.utils.logger import log

class MusicBeeParserError(Exception):
    """Raised when iTunes XML parsing fails or file is not found."""
    pass

class MusicBeeParser:
    def __init__(self, xml_path: str, cache_path=None):
        self.xml_path = xml_path
        self.cache_path = cache_path

    def _source_identity(self) -> dict:
        path = Path(self.xml_path)
        if not path.is_file():
            raise MusicBeeParserError("Library XML is missing or is not a regular file.")
        stat = path.stat()
        return {"path": str(path.resolve()), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}

    def load_library(self) -> List[Track]:
        try:
            source = self._source_identity()
            if self.cache_path is not None and Path(self.cache_path).is_file():
                try:
                    with open(self.cache_path, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                    if not isinstance(data, dict) or data.get("version") != 1:
                        raise ValueError("Invalid cache envelope")
                    if data.get("source") != source:
                        raise ValueError("Cache belongs to a different or changed XML source")
                    rows = data.get("tracks")
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError("Invalid cached track list")
                    return [Track(**row) for row in rows]
                except (ValueError, TypeError, UnicodeError) as exc:
                    log.warning(f"Invalid cache; rebuilding from XML ({type(exc).__name__}).")
            return self._parse_and_cache_xml(source)
        except OSError as exc:
            raise MusicBeeParserError(f"Library/cache I/O failed: {exc}") from exc

    @staticmethod
    def _location_to_path(location: str) -> str:
        if not isinstance(location, str) or not location or any(char in location for char in "\r\n"):
            raise ValueError("Invalid track location")
        if ntpath.isabs(location) and not location.lower().startswith("file:"):
            return location
        parsed = urlparse(location)
        if parsed.scheme.lower() != "file":
            raise ValueError("Track location must be a local file URI or absolute path")
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            return ntpath.normpath("//" + unquote(parsed.netloc) + path)
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            return ntpath.normpath(path[1:])
        return ntpath.normpath(path) if os.name == "nt" else path

    @staticmethod
    def _text_value(data, aliases, default=''):
        for key in aliases:
            value = data.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f'Expected text metadata: {key}')
            if value.strip():
                return value.strip()
        return default

    @classmethod
    def _multi_text(cls, data, aliases, prefix, default='Unknown'):
        values = [cls._text_value(data, aliases)]
        numbered = sorted((int(match.group(1)), key) for key in data
                          if (match := re.fullmatch(re.escape(prefix) + r'(\d+)', key)))
        values.extend(cls._text_value(data, [key]) for _, key in numbered)
        result, seen = [], set()
        # MusicBee uses semicolons for multivalue tags; commas/& can be part of real names.
        for value in values:
            for part in value.split(';'):
                part = part.strip()
                if part and part.casefold() not in seen:
                    result.append(part)
                    seen.add(part.casefold())
        return '; '.join(result) or default

    def _track_from_element(self, elem):
        data = {}
        key = None
        for child in elem:
            if child.tag == "key":
                key = child.text
            elif key:
                if child.tag in {"string", "date"}:
                    data[key] = child.text
                elif child.tag == "integer" and key in {
                    "Track ID", "轨迹 ID", "Play Count", "播放次数", "BPM", "Total Time", "总时间"
                }:
                    # Validate consumed fields only: MusicBee can emit multivalue Track/Disc counts.
                    # Invalid required numeric metadata remains a source error, not a fabricated zero.
                    data[key] = int(child.text)
                key = None
        location = data.get("Location")
        if not location:
            return None
        return Track(
            id=data.get("Track ID") or data.get("轨迹 ID") or 0,
            name=self._text_value(data, ['Name', 'Title', '名称'], 'Unknown'),
            artist=self._multi_text(data, ['Artist', '演出者', '艺术家'], 'Artist'),
            album=self._text_value(data, ['Album', '专辑'], 'Unknown'),
            genre=self._multi_text(data, ['Genre', '流派'], 'Genre'),
            play_count=data.get("Play Count") or data.get("播放次数") or 0,
            bpm=data.get("BPM") or 0,
            total_time=data.get("Total Time") or data.get("总时间") or 0,
            date_added=data.get("Date Added") or data.get("添加日期") or "Unknown",
            local_path=self._location_to_path(location),
            language=self._multi_text(data, ['Language', '语言'], 'Language', default=''),
            composer=self._text_value(data, ['Composer', '作曲家', '作曲者']),
            work=self._text_value(data, ['Work', '作品']),
            movement_name=self._text_value(data, ['Movement Name', '乐章名称']),
            dj_vocals=self._text_value(data, ['DJ_VOCALS']),
            dj_energy=self._text_value(data, ['DJ_ENERGY']),
            dj_scene=self._multi_text(data, ['DJ_SCENE'], 'DJ_SCENE', default=''),
            mood=self._multi_text(data, ['Mood', '情绪', '心情'], 'Mood', default=''),
            tempo=self._text_value(data, ['Tempo', '速度']),
        )

    def _parse_and_cache_xml(self, source=None) -> List[Track]:
        import xml.etree.ElementTree as ET
        log.info(f"Parsing library XML: {self.xml_path}")
        library: List[Track] = []

        try:
            source = source or self._source_identity()
            # Plist dictionary order is not semantic; parse only children of the root Tracks dict.
            stack = []
            tracks_root = None
            pending_parent = None
            found_tracks = False
            for event, elem in ET.iterparse(self.xml_path, events=("start", "end")):
                if event == "start":
                    parent = stack[-1] if stack else None
                    if pending_parent is not None and parent is pending_parent:
                        if elem.tag != "dict":
                            raise ValueError("Root Tracks value must be a dictionary")
                        tracks_root = elem
                        pending_parent = None
                        found_tracks = True
                    stack.append(elem)
                    continue
                parent = stack[-2] if len(stack) > 1 else None
                if tracks_root is not None and parent is tracks_root:
                    if elem.tag == "dict":
                        track = self._track_from_element(elem)
                        if track is not None:
                            library.append(track)
                    elem.clear()
                    parent.remove(elem)
                elif tracks_root is None or elem is tracks_root:
                    if (elem.tag == "key" and elem.text == "Tracks" and len(stack) == 3
                            and stack[0].tag == "plist" and parent.tag == "dict"):
                        pending_parent = parent
                    if elem is tracks_root:
                        tracks_root = None
                    elem.clear()
                stack.pop()
            if not found_tracks:
                raise ValueError("Library XML has no root Tracks dictionary")

            if self._source_identity() != source:
                raise MusicBeeParserError("Library XML changed during parsing; retry after the export finishes.")
            if self.cache_path is not None:
                cache = Path(self.cache_path)
                cache.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = str(cache) + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "source": source, "tracks": [t.__dict__ for t in library]},
                              handle, ensure_ascii=False, indent=2)
                os.replace(tmp_path, cache)

            log.info(f"Library parsed: {len(library)} tracks indexed in memory.")
            return library

        except (OSError, ET.ParseError, ValueError, TypeError, MusicBeeParserError) as exc:
            raise MusicBeeParserError(f"Failed to parse XML: {exc}") from exc
