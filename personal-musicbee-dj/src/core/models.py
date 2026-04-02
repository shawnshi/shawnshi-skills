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
        """Determines if the track has a valid physical location to play."""
        import os
        return bool(self.local_path) and os.path.exists(self.local_path)
