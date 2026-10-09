import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.attributes import LANGUAGE_ALIASES, MOOD_ALIASES, requested_values
from src.core.curator import DJCurator
from src.core.parser import MusicBeeParserError
from src.core.tag_preflight import TagCompletionRequired
from src.utils.logger import log


def load_config(config_path: Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping")
    return config


def resolve_config_paths(config: Dict, skill_root: Path) -> Dict:
    """Resolve player/library paths; nonempty environment overrides take precedence."""
    musicbee = config.get("musicbee", {})
    if not isinstance(musicbee, dict):
        raise ValueError("musicbee must be a mapping")
    for key, variable in (("exe_path", "MUSICBEE_EXE_PATH"), ("xml_path", "MUSICBEE_XML_PATH")):
        raw = str(os.environ.get(variable) or musicbee.get(key, "")).strip()
        if not raw:
            continue
        expanded = os.path.expanduser(os.path.expandvars(raw))
        if expanded.startswith("${") or expanded.startswith("%"):
            raise ValueError(f"Unresolved environment variable for musicbee.{key}")
        path = Path(expanded)
        if not path.is_absolute():
            path = skill_root / path
        musicbee[key] = str(path.resolve())
    config["musicbee"] = musicbee
    return config


def validate_config(config: Dict, request_type: str, *, require_player=True) -> List[str]:
    errors: List[str] = []
    sections = ("musicbee", "playlist", "scenes", "energy_curves", "filters", "fallback")
    for section in sections:
        if not isinstance(config.get(section, {}), dict):
            errors.append(f"{section} must be a mapping")
    if errors:
        return errors

    musicbee = config.get("musicbee", {})
    if require_player and not Path(str(musicbee.get("exe_path", ""))).is_file():
        errors.append("musicbee.exe_path is missing or is not a regular file")
    if request_type not in {"genre", "scene"}:
        return errors
    if not Path(str(musicbee.get("xml_path", ""))).is_file():
        errors.append("musicbee.xml_path is missing or is not a regular file")

    playlist = config.get("playlist", {})
    max_tracks = playlist.get("max_tracks_per_session", 0)
    if type(max_tracks) is not int or max_tracks <= 0:
        errors.append("playlist.max_tracks_per_session must be a positive integer")
    curation = playlist.get("curation", {})
    if not isinstance(curation, dict):
        errors.append("playlist.curation must be a mapping")
    else:
        ratios = [curation.get(key, default) for key, default in (
            ("anchor_ratio", 0.6), ("discovery_ratio", 0.3), ("novelty_ratio", 0.1))]
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in ratios):
            errors.append("curation ratios must be finite numbers between 0 and 1")
        elif not math.isclose(sum(ratios), 1.0, abs_tol=1e-9):
            errors.append("curation ratios must sum to 1")
    for key in ("high_intensity_min_bpm", "low_intensity_max_bpm"):
        value = config.get("energy_curves", {}).get(key, 100)
        if type(value) is not int or value < 0:
            errors.append(f"energy_curves.{key} must be a nonnegative integer")
    for key, values in config.get("filters", {}).items():
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            errors.append(f"filters.{key} must be a string list")
    aliases = config.get("fallback", {}).get("aliases", {})
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in aliases.items()):
        errors.append("fallback.aliases must map strings to strings")
    scenes = config.get("scenes", {})
    if request_type == "scene" and not scenes:
        errors.append("scenes must contain at least one configured scene")
    for name, scene in scenes.items():
        if not isinstance(name, str) or not isinstance(scene, dict):
            errors.append("scenes must map names to mappings")
            continue
        genres = scene.get("genres", [])
        if not isinstance(genres, list) or any(not isinstance(genre, str) or not genre for genre in genres):
            errors.append(f"scenes.{name}.genres must be a string list")
        try:
            requested_values(scene.get('moods', []), MOOD_ALIASES, 'mood')
        except ValueError:
            errors.append(f'scenes.{name}.moods contains an invalid identifier')
        intensity = scene.get("intensity", "normal")
        if not isinstance(intensity, str) or intensity not in {"high", "normal", "low"}:
            errors.append(f"scenes.{name}.intensity is invalid")
    return errors


TASK_MARKER = ".musicbee-dj-task"
TASK_FILES = {TASK_MARKER, "queue.m3u", "queue.m3u.tmp", "library-cache.json", "library-cache.json.tmp"}


def cleanup_task(path: Path):
    """Delete only this CLI's marked, flat task directory beneath the OS temp root."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("Refusing to clean a linked task directory")
    resolved = path.resolve()
    if resolved.parent != Path(tempfile.gettempdir()).resolve() or not resolved.name.startswith("musicbee-dj-"):
        raise ValueError("Cleanup target is outside the MusicBee task namespace")
    marker = resolved / TASK_MARKER
    if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding="utf-8") != "1\n":
        raise ValueError("Cleanup target has no valid MusicBee task marker")
    files = list(resolved.iterdir())
    if any(file.name not in TASK_FILES or file.is_symlink() or not file.is_file() for file in files):
        raise ValueError("Cleanup target contains unrecognized entries; nothing deleted")
    for file in files:
        file.unlink()
    resolved.rmdir()


def musicbee_running() -> bool:
    """Process presence only, never proof of playback. Query without changing the player."""
    if sys.platform != 'win32':
        raise ValueError('MusicBee playback requires Windows')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         'try { Get-Process -Name MusicBee -ErrorAction Stop | Out-Null; "running" } '
         'catch { if ($_.FullyQualifiedErrorId -eq "NoProcessFoundForGivenName,Microsoft.PowerShell.Commands.GetProcessCommand") '
         '{ "stopped" } else { Write-Error $_; exit 1 } }'],
        capture_output=True, text=True, check=True, timeout=5,
    )
    state = result.stdout.strip()
    if state not in {'running', 'stopped'}:
        raise ValueError('MusicBee process presence could not be determined')
    return state == 'running'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MusicBee local playlist launcher")
    parser.add_argument('--type', choices=['genre', 'scene', 'playlist'])
    parser.add_argument('--value', help="Genre, scene alias or existing playlist target")
    parser.add_argument('--intensity', choices=['high', 'low', 'normal'], help="Override the scene intensity")
    parser.add_argument('--minutes', type=float, help="Whole-track duration budget; unknown durations are excluded")
    parser.add_argument('--no-vocals', action='store_true', help="Require instrumental DJ/legacy tags; exclude unknown/vocal tags")
    parser.add_argument('--language', action='append', default=[], help='Required vocal language; repeat for alternatives')
    parser.add_argument('--exclude-language', action='append', default=[], help='Exclude vocal languages; unknown vocal language fails closed')
    parser.add_argument('--prefer-language', action='append', default=[], help='Soft vocal language preference')
    parser.add_argument('--mood', action='append', default=[], help='Required metadata mood; missing/mismatched tags excluded')
    parser.add_argument('--prefer-mood', action='append', default=[], help='Soft metadata mood preference')
    parser.add_argument('--bpm-min', type=int, help='Strict minimum known BPM; cannot be overridden by DJ_ENERGY')
    parser.add_argument('--bpm-max', type=int, help='Strict maximum known BPM')
    parser.add_argument('--strict-evidence', action='store_true', help='Require explicit DJ scene/energy/instrumental tags instead of legacy Genre/BPM fallbacks')
    parser.add_argument('--dry-run', action='store_true', help='Read-only genre/scene selection; no task, playlist, cache or player writes')
    parser.add_argument('--generate-only', action='store_true', help='Export a playlist without querying or launching MusicBee')
    parser.add_argument('--completion-task', type=Path, help='Previously verified research attempt; retain unresolved fields without a research loop')
    parser.add_argument('--allow-tag-completion', action='store_true', help='Caller verified existing explicit authority for bounded tag research/artifacts; not a grant of permission')
    parser.add_argument('--explain', action='store_true', help='Print evidence, unknowns and allocation diagnostics; combine with --dry-run for read-only')
    parser.add_argument('--exclude-genre', action='append', default=[], help="Genre to exclude; repeat for multiple exclusions")
    parser.add_argument('--exclude-artist', action='append', default=[], help="Artist to exclude; repeat for multiple exclusions")
    parser.add_argument('--exclude-track', action='append', default=[], help='Exclude title substrings')
    parser.add_argument('--exclude-album', action='append', default=[], help='Exclude album substrings')
    parser.add_argument('--prefer-artist', action='append', default=[], help='Prioritize matching artists within the selected strategy')
    parser.add_argument('--familiarity', choices=['balanced', 'familiar', 'explore'], default='balanced')
    parser.add_argument('--seed', type=int, help='Reproducible selection for an unchanged candidate set')
    parser.add_argument('--queue', choices=['play', 'next', 'last'], default='play', help='Replace/play, queue next or queue last')
    parser.add_argument('--replace-current', action='store_true', help='Only after explicit permission to replace an existing queue')
    parser.add_argument('--check', action='store_true', help="Validate configuration without reading the library or launching")
    parser.add_argument('--cleanup-task', type=Path, help="Remove a reported task directory after playback ends")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    metadata_options = (args.language or args.exclude_language or args.prefer_language or args.mood
                        or args.prefer_mood or args.bpm_min is not None or args.bpm_max is not None or args.strict_evidence)
    try:
        for items in (args.language, args.exclude_language, args.prefer_language):
            requested_values(items, LANGUAGE_ALIASES, 'language')
        for items in (args.mood, args.prefer_mood):
            requested_values(items, MOOD_ALIASES, 'mood')
        for bound in (args.bpm_min, args.bpm_max):
            if bound is not None and not 1 <= bound <= 500:
                raise ValueError('BPM bounds must be in [1, 500]')
        if args.bpm_min is not None and args.bpm_max is not None and args.bpm_min > args.bpm_max:
            raise ValueError('BPM minimum cannot exceed maximum')
    except ValueError as exc:
        parser.error(str(exc))
    if args.check and (metadata_options or args.dry_run or args.explain or args.generate_only or args.completion_task):
        parser.error('--check cannot ignore selection/preview options')
    if args.dry_run and (args.type == 'playlist' or args.queue != 'play' or args.replace_current or args.generate_only or args.completion_task):
        parser.error('--dry-run applies only to genre/scene selection and cannot include queue/completion controls')
    if args.generate_only and (args.type == 'playlist' or args.queue != 'play' or args.replace_current):
        parser.error('--generate-only applies to genre/scene creation, not existing playlists or queue controls')
    if args.completion_task and args.type not in {'genre', 'scene'}:
        parser.error('--completion-task applies only to genre/scene selection')
    if args.cleanup_task:
        if (args.type or args.value or args.intensity or args.check or args.minutes is not None
                or args.no_vocals or args.exclude_genre or args.exclude_artist or args.exclude_track
                or args.exclude_album or args.prefer_artist or args.familiarity != 'balanced'
                or args.seed is not None or args.queue != 'play' or args.replace_current
                or metadata_options or args.dry_run or args.explain or args.generate_only or args.completion_task):
            parser.error("--cleanup-task cannot be combined with playback/check options")
        try:
            cleanup_task(args.cleanup_task)
        except (OSError, ValueError) as exc:
            log.error(f"Task cleanup failed ({type(exc).__name__}): {exc}")
            sys.exit(1)
        log.info("MusicBee task directory removed.")
        return
    if not args.check and (not args.type or not args.value or not args.value.strip()):
        parser.error("Playback requires --type and a nonempty --value")

    constrained = (args.minutes is not None or args.no_vocals or args.exclude_genre or args.exclude_artist
                   or args.exclude_track or args.exclude_album or args.prefer_artist
                   or args.familiarity != 'balanced' or args.seed is not None or metadata_options or args.explain)
    if args.replace_current and args.queue != 'play':
        parser.error('--replace-current applies only to --queue play')
    if args.minutes is not None and (not math.isfinite(args.minutes) or args.minutes <= 0):
        parser.error("--minutes must be finite and positive")
    if any(not value.strip() for value in args.exclude_genre + args.exclude_artist
           + args.exclude_track + args.exclude_album + args.prefer_artist):
        parser.error("Exclusion terms must not be empty")
    if args.type == 'playlist' and constrained:
        parser.error("Selection constraints apply only to genre/scene requests, not existing playlists")

    task_dir = None
    keep_playlist = False
    try:
        skill_root = Path(__file__).resolve().parent.parent
        config = resolve_config_paths(load_config(skill_root / "config.yaml"), skill_root)
        config_errors = validate_config(config, args.type or "scene", require_player=not (args.dry_run or args.generate_only))
        if args.completion_task:
            config.setdefault('tag_completion', {})['completed_task'] = str(args.completion_task.absolute())
        if config_errors:
            raise ValueError("Configuration validation failed: " + "; ".join(config_errors))
        if args.check:
            log.info("Configuration check passed; no library read, task files or player launch.")
            return

        if not args.dry_run and not args.generate_only and sys.platform != 'win32':
            raise ValueError('MusicBee playback requires Windows')
        musicbee_exe = Path(config["musicbee"]["exe_path"])
        if args.type == 'playlist':
            target = Path(args.value.strip()).expanduser()
            if not target.is_file() or target.suffix.lower() not in {'.m3u', '.m3u8', '.mbp'}:
                raise ValueError('Playlist requires an existing local .m3u/.m3u8/.mbp file; names are not resolved')
            play_target = str(target.resolve())
        if not args.dry_run and not args.generate_only and args.queue == 'play' and not args.replace_current and musicbee_running():
            raise ValueError('MusicBee is already running; confirm queue replacement before using --replace-current, or request queue next/last')
        if args.type in {"genre", "scene"}:
            if not args.dry_run:
                task_dir = Path(tempfile.mkdtemp(prefix="musicbee-dj-"))
                try:
                    (task_dir / TASK_MARKER).write_text("1\n", encoding="utf-8")
                except OSError:
                    task_dir.rmdir()
                    task_dir = None
                    raise
            config["cache"] = {"db_path": None}
            config["playlist"]["output_m3u"] = str(task_dir / "queue.m3u") if task_dir else ''
            config['request'] = {'minutes': args.minutes, 'no_vocals': args.no_vocals,
                                 'exclude_genres': args.exclude_genre, 'exclude_artists': args.exclude_artist,
                                 'exclude_tracks': args.exclude_track, 'exclude_albums': args.exclude_album,
                                 'prefer_artists': args.prefer_artist, 'familiarity': args.familiarity, 'seed': args.seed,
                                 'languages': args.language, 'exclude_languages': args.exclude_language,
                                 'prefer_languages': args.prefer_language, 'moods': args.mood,
                                 'prefer_moods': args.prefer_mood, 'bpm_min': args.bpm_min, 'bpm_max': args.bpm_max,
                                 'strict_evidence': args.strict_evidence}
            curator = DJCurator(config=config)
            intensity = args.intensity or "normal"
            if args.type == "scene" and args.intensity is None:
                resolved, _, _ = curator._resolve_scene_name(args.value)
                intensity = config["scenes"].get(resolved, {}).get("intensity", "normal")
            if args.dry_run or args.explain:
                result = curator.generate_m3u(criteria_type=args.type, criteria_value=args.value,
                                              intensity=intensity, export=not args.dry_run, explain=args.explain)
            else:
                result = curator.generate_m3u(criteria_type=args.type, criteria_value=args.value, intensity=intensity)
            if args.dry_run or args.explain:
                print(json.dumps({'mode': 'read_only' if args.dry_run else 'playback_request',
                    'scene_or_genre': args.value, 'intensity': intensity,
                    'selection_diagnostics': curator.last_diagnostics}, ensure_ascii=False))
            if args.dry_run:
                if result is None:
                    raise ValueError('Read-only selection has no candidates satisfying the constraints')
                return
            if result is None or not result.is_playable:
                raise ValueError("No playable playlist matched the requested scene/genre and intensity")
            play_target = result.play_target
            log.info(
                f"Playlist ready: resolved={result.resolved_value} intensity={intensity} "
                f"matched={result.matched_tracks} filtered={result.filtered_tracks} exported={result.exported_tracks} "
                f"known_duration_minutes={result.total_duration_ms / 60000:.1f} unknown_duration_tracks={result.unknown_duration_tracks} "
                f"unknown_bpm_tracks={result.unknown_bpm_tracks} unknown_vocal_tag_tracks={result.unknown_vocal_tag_tracks} "
                f"unknown_energy_tag_tracks={result.unknown_energy_tag_tracks} unknown_scene_tag_tracks={result.unknown_scene_tag_tracks} "
                f"repeat_spacing_relaxations={result.repeat_spacing_relaxations} "
                f"familiarity={args.familiarity} seed={args.seed}"
            )
            if result.fallback_applied:
                log.info(f"Scene mapping applied: {result.fallback_reason}")
        if args.generate_only:
            keep_playlist = True
            print(json.dumps({'mode': 'playlist_only', 'playlist': play_target,
                'exported_tracks': result.exported_tracks, 'playback_requested': False,
                'selection_diagnostics': curator.last_diagnostics}, ensure_ascii=False))
            return
        # Documented one-way controls: https://musicbee.fandom.com/wiki/Command_Line_Parameters
        command = {'play': '/Play', 'next': '/QueueNext', 'last': '/QueueLast'}[args.queue]
        process = subprocess.Popen([str(musicbee_exe), command, str(play_target)], shell=False)
        returncode = process.poll()
        if returncode not in (None, 0):
            raise subprocess.CalledProcessError(returncode, [str(musicbee_exe), command, str(play_target)])
        keep_playlist = True
        log.info(f"MusicBee launch request submitted (pid={process.pid}); playback not confirmed.")
    except TagCompletionRequired as exc:
        if not args.allow_tag_completion:
            print(json.dumps({'status': 'tag_completion_authorization_required',
                'incomplete_files': len(exc.records), 'read_errors': len(exc.errors),
                'required_fields': sorted({field for record in exc.records for field in record['needs']}),
                'playback_requested': False, 'task_created': False}, ensure_ascii=False))
            sys.exit(3)
        # Agent-level handoff, not an implicit shell launch of Pi or another provider.
        from src.core.tag_inventory import write_inventory
        from src.tag_completion import prepare_jobs, next_jobs
        request_root = Path(tempfile.mkdtemp(prefix='musicbee-tag-completion-'))
        work = request_root / 'work'
        try:
            summary = write_inventory(work, exc.library_root, exc.records, exc.errors)
            prepare_jobs(work)
            print(json.dumps({'status': 'needs_tag_completion', 'work_dir': str(work),
                'summary': summary, 'jobs': next_jobs(work), 'playback_requested': False}, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError) as error:
            log.error(f'Tag completion handoff failed ({type(error).__name__}): {error}; retained at {request_root}')
            sys.exit(1)
        sys.exit(3)
    except (OSError, ValueError, TypeError, yaml.YAMLError, MusicBeeParserError, subprocess.SubprocessError) as exc:
        log.error(f"MusicBee request failed ({type(exc).__name__}): {exc}")
        sys.exit(1)
    finally:
        if task_dir is not None:
            if keep_playlist:
                # MusicBee may read asynchronously; process creation does not acknowledge M3U consumption.
                log.info(f"Temporary playlist retained: {task_dir}; after playback use --cleanup-task with this directory.")
            else:
                try:
                    cleanup_task(task_dir)
                except (OSError, ValueError) as exc:
                    log.error(f"Task cleanup failed ({type(exc).__name__}); retained at {task_dir}: {exc}")
                    sys.exit(1)


if __name__ == "__main__":
    main()
