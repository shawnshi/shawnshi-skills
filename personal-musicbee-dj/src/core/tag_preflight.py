"""Playlist handoff to the agent-controlled research lane; never calls a provider."""

import hashlib
from pathlib import Path

from src.core.local_paths import local_path
from src.core.tag_inventory import FIELDS, inventory, read_json, scan_paths, values

ATTRIBUTES = {
    "Tempo": "tempo",
    "mood": "mood",
    "DJ_VOCALS": "dj_vocals",
    "DJ_ENERGY": "dj_energy",
    "DJ_SCENE": "dj_scene",
}


class TagCompletionRequired(ValueError):
    def __init__(self, library_root, records, errors):
        super().__init__(
            "Actual song files need metadata completion before playlist export"
        )
        self.library_root = library_root
        self.records = records
        self.errors = errors


def attempted_paths(work_dir, library_root, requested_paths, required_fields=None):
    """A completed attempt can retain unknowns, but stale or failed work cannot bypass checks."""
    if not work_dir:
        return set()
    from src.tag_completion import task_manifest, reviewed_updates
    from src.core.tag_writer import digest

    work, manifest = task_manifest(work_dir)
    if Path(manifest["library_root"]).resolve() != Path(library_root).resolve():
        raise ValueError("Completion task belongs to a different library")
    verified = read_json(work / "verification_summary.json")
    if (not verified.get("all_checked_commits_valid")
        or not verified.get("research_reconciled")
        or verified.get("receipt_failures")):
        raise ValueError("Completion task not physically verified")
    plan = read_json(work / "jobs.json")
    if plan.get("blocked"):
        raise ValueError(
            "Failed research cannot be used to bypass automatic completion"
        )
    baselines = {r["path"]: r for r in manifest["records"]}
    checked = set()
    for job in plan["jobs"]:
        if job["state"] != "researched" or not set(job["paths"]) & requested_paths:
            continue
        result_path = Path(job["cwd"]) / "result.json"
        if digest(result_path) != job["result_sha256"]:
            raise ValueError("Accepted research changed")
        updates = reviewed_updates(work, job, {path: baselines[path] for path in job["paths"]})
        for path in job["paths"]:
            if path not in requested_paths:
                continue
            baseline = baselines[path]
            if required_fields is not None and not set(required_fields) <= set(baseline.get('requested_fields', FIELDS)):
                continue
            receipt = (
                work
                / "backups"
                / (hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json")
            )
            if receipt.exists():
                status = read_json(receipt)
                if status.get("status") != "committed" or digest(
                    Path(path)
                ) != status.get("after_sha256"):
                    raise ValueError("Committed completion file drifted")
            else:
                if updates[path]:
                    raise ValueError("Researched recording has unapplied changes")
                actual = inventory(path, library_root)
                if (actual["size"], actual["mtime_ns"], actual["tags"]) != (
                    baseline["size"],
                    baseline["mtime_ns"],
                    baseline["tags"],
                ):
                    raise ValueError("Unchanged/unresolved completion file drifted")
            checked.add(path)
    return checked


def inspect_tracks(tracks, settings, limit=True, required_fields=None):
    requested = set(FIELDS if required_fields is None else required_fields)
    if not requested <= set(FIELDS):
        raise ValueError('Invalid requested research fields')
    root = local_path(Path(settings["library_root"]).absolute())
    max_tracks = settings.get("candidate_limit", 100)
    if type(max_tracks) is not int or not 1 <= max_tracks <= 100:
        raise ValueError("Tag completion candidate_limit must be 1-100")
    eligible, seen = [], set()
    for track in tracks:
        path = Path(track.local_path)
        if not path.is_absolute() or path.suffix.lower() not in {".flac", ".mp3"}:
            continue
        try:
            path = local_path(path)
        except FileNotFoundError:
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        if track.local_path not in seen:
            eligible.append(track)
            seen.add(track.local_path)
        if limit and len(eligible) >= max_tracks:
            break
    allowed = attempted_paths(
        settings.get("completed_task"),
        root,
        {str(Path(t.local_path).absolute()) for t in eligible},
        required_fields=requested,
    )
    records, errors = scan_paths([t.local_path for t in eligible], root)
    by_path = {str(Path(t.local_path).absolute()): t for t in eligible}
    for record in records:
        track = by_path[record["path"]]
        # Live audio-file tags override stale XML only for the five authorized fields.
        for field, attribute in ATTRIBUTES.items():
            setattr(
                track,
                attribute,
                ";".join(v.strip() for v in values(record["tags"], field)),
            )
    for record in records:
        record['requested_fields'] = sorted(requested)
        record['needs'] = [field for field in record['needs'] if field in requested]
    pending = [r for r in records if r["needs"] and r["path"] not in allowed]
    if pending or errors:
        raise TagCompletionRequired(str(root), pending, errors)
    return {
        "inspected_files": len(records),
        "unresolved_after_completed_attempt": sum(bool(r["needs"]) for r in records),
        "errors": len(errors),
        "fields": sorted(requested),
    }


def related_candidates(curator, library, pool, criteria_type, resolved_value):
    """Genre is only a discovery hint here, never proof of vocals/energy/scene."""
    candidates = list(pool)
    if criteria_type == "scene":
        genres = [
            g.casefold()
            for g in curator.scenes.get(resolved_value, {}).get("genres", [])
        ]
        candidates.extend(
            t for t in library if any(g in t.genre.casefold() for g in genres)
        )
    # No matches is a selection result, not permission to research unrelated library entries.
    seen = set()
    result = []
    for track in candidates:
        if track.local_path in seen:
            continue
        if (
            any(s in track.artist.casefold() for s in curator.excluded_artists)
            or any(s in track.name.casefold() for s in curator.excluded_tracks)
            or any(s in track.album.casefold() for s in curator.excluded_albums)
            or any(s in track.genre.casefold() for s in curator.excluded_genres)
        ):
            continue
        seen.add(track.local_path)
        result.append(track)
    return result
