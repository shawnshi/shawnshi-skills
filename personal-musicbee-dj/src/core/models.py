from dataclasses import dataclass, field, fields


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
    language: str = ''
    composer: str = ''
    work: str = ''
    movement_name: str = ''
    dj_vocals: str = ''
    dj_energy: str = ''
    dj_scene: str = ''
    mood: str = ''
    tempo: str = ''

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not field.type:
                raise ValueError(f"Invalid track field type: {field.name}")
            if field.type is int and value < 0:
                raise ValueError(f"Negative track field: {field.name}")

    @property
    def is_valid(self) -> bool:
        import os
        return (
            bool(self.local_path)
            and not any(char in self.local_path for char in "\r\n")
            and os.path.isfile(self.local_path)
        )


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
    total_duration_ms: int = 0
    unknown_duration_tracks: int = 0
    unknown_bpm_tracks: int = 0
    unknown_vocal_tag_tracks: int = 0
    repeat_spacing_relaxations: int = 0
    unknown_energy_tag_tracks: int = 0
    unknown_scene_tag_tracks: int = 0
    selection_diagnostics: dict = field(default_factory=dict)

    @property
    def is_playable(self) -> bool:
        import os
        return bool(self.play_target) and os.path.isfile(self.play_target) and self.exported_tracks > 0
