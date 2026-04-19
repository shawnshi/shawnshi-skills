from dataclasses import dataclass
from typing import Optional


@dataclass
class Track:
    id: int
    name: str
    artist: str
    album: str
    genre: str
    play_count: int
    bpm: int
    total_time: int
    date_added: str
    local_path: str

    @property
    def is_valid(self) -> bool:
        import os
        return bool(self.local_path) and os.path.exists(self.local_path)


@dataclass
class CuratedPlayback:
    play_target: str
    requested_type: str
    requested_value: str
    resolved_value: str
    matched_tracks: int
    filtered_tracks: int
    exported_tracks: int
    fallback_applied: bool = False
    fallback_reason: str = ""

    @property
    def is_playable(self) -> bool:
        import os
        return bool(self.play_target) and os.path.exists(self.play_target) and self.exported_tracks > 0
