import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.curator import DJCurator
from src.utils.logger import log


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        log.error(f"Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def validate_config(config: Dict, request_type: str) -> List[str]:
    errors: List[str] = []

    musicbee = config.get('musicbee', {})
    cache = config.get('cache', {})
    playlist = config.get('playlist', {})
    scenes = config.get('scenes', {})

    exe_path = Path(str(musicbee.get('exe_path', '')).strip())
    if not exe_path.exists():
        errors.append(f"musicbee.exe_path is missing or invalid: {exe_path}")

    if request_type in {'genre', 'scene'}:
        xml_path = Path(str(musicbee.get('xml_path', '')).strip())
        if not xml_path.exists():
            errors.append(f"musicbee.xml_path is missing or invalid: {xml_path}")

        cache_path = str(cache.get('db_path', '')).strip()
        if not cache_path:
            errors.append("cache.db_path is required for genre/scene playback")

        output_m3u = str(playlist.get('output_m3u', '')).strip()
        if not output_m3u:
            errors.append("playlist.output_m3u is required for genre/scene playback")

        max_tracks = playlist.get('max_tracks_per_session', 0)
        if not isinstance(max_tracks, int) or max_tracks <= 0:
            errors.append("playlist.max_tracks_per_session must be a positive integer")

    if request_type == 'scene' and (not isinstance(scenes, dict) or not scenes):
        errors.append("scenes must contain at least one configured scene for scene playback")

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MusicBee DJ - Intelligent playback controller (V4)")
    parser.add_argument('--type', choices=['genre', 'scene', 'playlist'], required=True, help="Type of play target")
    parser.add_argument('--value', required=True, help="Target value (e.g., 'Jazz', 'focus', 'My Favorites')")
    parser.add_argument('--intensity', choices=['high', 'low', 'normal'], default='normal', help="Momentum/Energy level")
    return parser


def main():
    args = build_parser().parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    config_path = skill_root / "config.yaml"
    config = load_config(config_path)

    config_errors = validate_config(config, args.type)
    if config_errors:
        log.error("Configuration validation failed:")
        for error in config_errors:
            log.error(f" - {error}")
        sys.exit(1)

    musicbee_exe = Path(config.get('musicbee', {}).get('exe_path', ''))
    play_target = None

    if args.type in ['genre', 'scene']:
        log.info(f"Initializing DJ Curator for [Type: {args.type}, Value: {args.value}, Intensity: {args.intensity}]")
        curator = DJCurator(config=config)
        result = curator.generate_m3u(criteria_type=args.type, criteria_value=args.value, intensity=args.intensity)
        if result is None:
            log.error("Failed to curate a playable JIT playlist.")
            sys.exit(1)
        if not result.is_playable:
            log.error("Result gate failed: playlist target is not playable.")
            log.error(
                f"resolved={result.resolved_value} matched={result.matched_tracks} filtered={result.filtered_tracks} exported={result.exported_tracks}"
            )
            sys.exit(1)
        if result.fallback_applied:
            log.info(f"Semantic fallback applied: {result.fallback_reason}")
        play_target = result.play_target
        log.info(
            f"Result gate passed: resolved={result.resolved_value} matched={result.matched_tracks} filtered={result.filtered_tracks} exported={result.exported_tracks}"
        )
    else:
        play_target = args.value.strip()
        if not play_target:
            log.error("Playlist target is empty.")
            sys.exit(1)

    log.info(f"Triggering MusicBee with target: {play_target}")
    try:
        subprocess.Popen([str(musicbee_exe), "/Play", play_target])
        log.info("Playback sequence initiated successfully.")
    except Exception as exc:
        log.error(f"Failed to execute MusicBee process: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
