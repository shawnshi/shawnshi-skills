import argparse
import subprocess
import os
import sys
import yaml

# Ensure the root of the skill is in PYTHONPATH for standard imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.curator import DJCurator
from src.utils.logger import log

def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        log.error(f"Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    parser = argparse.ArgumentParser(description="MusicBee DJ - Intelligent playback controller (v2.0 GEB-Flow)")
    parser.add_argument('--type', choices=['genre', 'scene', 'playlist'], required=True, help="Type of play target")
    parser.add_argument('--value', required=True, help="Target value (e.g., 'Jazz', 'focus', 'My Favorites')")
    parser.add_argument('--intensity', choices=['high', 'low', 'normal'], default='normal', help="Momentum/Energy level")
    args = parser.parse_args()
    
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    config = load_config(config_path)

    musicbee_exe = config.get('musicbee', {}).get('exe_path', '')
    if not os.path.exists(musicbee_exe):
        log.error(f"MusicBee executable not found at {musicbee_exe}")
        sys.exit(1)

    play_target = None
    
    if args.type in ['genre', 'scene']:
        log.info(f"Initializing DJ Curator for [Type: {args.type}, Value: {args.value}, Intensity: {args.intensity}]")
        curator = DJCurator(config=config)
        play_target = curator.generate_m3u(criteria_type=args.type, criteria_value=args.value, intensity=args.intensity)
    elif args.type == 'playlist':
        play_target = args.value

    if play_target:
        log.info(f"Triggering MusicBee with target: {play_target}")
        try:
            subprocess.Popen([musicbee_exe, "/Play", play_target])
            log.info("Playback sequence initiated successfully.")
        except Exception as e:
            log.error(f"Failed to execute MusicBee process: {e}")
    else:
        log.warning("Failed to resolve play target. Aborting playback.")

if __name__ == "__main__":
    main()
