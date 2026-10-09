"""Actual-file metadata inventory; no network, player or automatic inference."""

import csv
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys
from collections import Counter

from src.core.local_paths import local_path, local_regular_file

VENDOR = Path(__file__).resolve().parents[2] / "vendor-tag-metadata"
FIELDS = ["Tempo", "mood", "DJ_VOCALS", "DJ_ENERGY", "DJ_SCENE"]
COLS = ["文件名", "标题", "演出者", "专辑 / 来源", "年份"] + FIELDS
VALID = {
    "Tempo": {"Very Slow", "Slow", "Moderate", "Fast", "Very Fast"},
    "mood": set(
        "Angry|Bewildered|Bouncy|Calm|Cheerful|Chill|Cold|Comatose|Complacent|Crazy|Crushed|Cynical|Depressed|Dreamy|Drunk|Eclectic|Envious|Groovy|Happy|Mellow|Morose|Quirky|Rockin|Sad|Soothing|Spooky|Sunday Brunch|Tranquil|Trippy|Upbeat|Wild|Work".split(
            "|"
        )
    ),
    "DJ_VOCALS": {"vocal", "instrumental", "unknown"},
    "DJ_ENERGY": {"low", "medium", "high", "unknown"},
    "DJ_SCENE": {"focus", "coding", "relax", "energy", "pop", "unknown"},
}
_CODEC = None


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot load {Path(path).name}: {type(error).__name__}"
        ) from error


def codec():
    global _CODEC
    if _CODEC is None:
        spec = read_json(VENDOR / "vendor-manifest.json")
        for name, expected in spec["files_sha256"].items():
            path = VENDOR / name
            if not path.resolve().is_relative_to(VENDOR.resolve()) or path.is_symlink():
                raise ValueError("Invalid vendored dependency path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Vendored dependency checksum mismatch: " + name)
        sys.path.insert(0, str(VENDOR))
        package = importlib.import_module("mutagen")
        if not Path(package.__file__).resolve().is_relative_to(VENDOR.resolve()):
            raise ValueError(
                "Unreviewed Mutagen origin; use the bundled package in a fresh process"
            )
        _CODEC = package
    return _CODEC


def acceptable(field, items):
    if not items:
        return False
    if field == "DJ_SCENE":
        parts = [v.strip() for item in items for v in item.split(";") if v.strip()]
        return (
            bool(parts)
            and len(parts) == len(set(parts))
            and set(parts) <= VALID[field]
            and ("unknown" not in parts or parts == ["unknown"])
        )
    return len(items) == 1 and items[0].strip() in VALID[field]


def incomplete(field, items):
    return not acceptable(field, items) or (
        len(items) == 1 and items[0].strip() == "unknown"
    )


def mapped(audio):
    tags = audio.tags
    out = {}
    ID3 = importlib.import_module("mutagen.id3").ID3
    if isinstance(tags, ID3):
        names = {
            "TIT2": "title",
            "TPE1": "artist",
            "TALB": "album",
            "TDRC": "date",
            "TYER": "year",
            "TMOO": "mood",
            "TCON": "genre",
            "TBPM": "bpm",
        }
        for frame in tags.values():
            key = (
                frame.desc
                if frame.FrameID == "TXXX"
                else names.get(frame.FrameID, frame.FrameID)
            )
            if isinstance(key, str) and hasattr(frame, "text"):
                out.setdefault(key.casefold(), []).extend(str(t) for t in frame.text)
    elif tags is not None:
        for key, item in tags.items():
            out.setdefault(key.casefold(), []).extend(str(t) for t in item)
    return out


def values(tags, field):
    return tags.get(field.casefold(), [])


def inventory(path, library_root):
    root = local_path(Path(library_root).absolute()).resolve()
    path = local_regular_file(Path(path).absolute())
    if not path.resolve().is_relative_to(root) or path.suffix.lower() not in {
        ".flac",
        ".mp3",
    }:
        raise ValueError(
            "Only FLAC/MP3 regular files within the declared library root are supported"
        )
    before = path.stat()
    audio = codec().File(path)
    if audio is None:
        raise ValueError("Unrecognized audio format")
    tags = mapped(audio)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("File changed during metadata inventory")

    def raw(key):
        return ";".join(values(tags, key))

    row = dict(
        zip(
            COLS,
            [
                str(path),
                raw("title"),
                raw("artist"),
                raw("album"),
                raw("date") or raw("year"),
            ]
            + [raw(k) for k in FIELDS],
            strict=True,
        )
    )
    return {
        "path": str(path),
        "size": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "format": type(audio).__name__,
        "tags": tags,
        "needs": [k for k in FIELDS if incomplete(k, values(tags, k))],
        "row": row,
    }


def empty_noncanonical_windows_directory(path):
    if os.name != "nt" or not path.name.endswith((" ", ".")):
        return False
    # Called only after local_path checked an enumerated local drive entry and
    # failed to address its final component; never accept an external device/UNC path.
    wide = Path("\\\\?\\" + str(path.absolute()))
    info = wide.lstat()
    if getattr(info, "st_file_attributes", 0) & 1024 or not stat.S_ISDIR(info.st_mode):
        return False
    return next(wide.iterdir(), None) is None


def library_audio_paths(library_root, traversal_errors, coverage_notes):
    """Inaccessible/denied entries are explicit coverage gaps, never empty tag records."""
    root = local_path(Path(library_root).absolute())
    if (root / ".musicbee-dj-tag-writer.lock").exists():
        raise ValueError("Library writer lock present; inventory would be inconsistent")
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            directory = local_path(directory)
            entries = sorted(directory.iterdir())
        except (OSError, ValueError) as error:
            traversal_errors.append(
                {
                    "path": str(directory),
                    "scope": "library_entry",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            continue
        for entry in entries:
            try:
                entry = local_path(entry)
                if entry.is_dir():
                    pending.append(entry)
                elif entry.suffix.lower() in {".flac", ".mp3"} and entry.is_file():
                    yield entry
            except (OSError, ValueError) as error:
                if isinstance(error, FileNotFoundError):
                    try:
                        if empty_noncanonical_windows_directory(entry):
                            coverage_notes.append(
                                {
                                    "path": str(entry),
                                    "kind": "verified_empty_noncanonical_directory",
                                }
                            )
                            continue
                    except OSError:
                        pass  # Preserve the original surfaced error below, never fake an empty directory.
                traversal_errors.append(
                    {
                        "path": str(entry),
                        "scope": "library_entry",
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )


def scan_paths(paths, library_root):
    records, errors, seen = [], [], set()
    module = codec()
    for path in paths:
        key = str(Path(path).absolute()).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            records.append(inventory(path, library_root))
        except (OSError, ValueError, module.MutagenError) as error:
            errors.append(
                {
                    "path": str(path),
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
    return records, errors


def write_inventory(output, library_root, records, errors, coverage_notes=None):
    """Only explicit preparation writes a task artifact; source files remain untouched."""
    output = Path(output).absolute()
    local_path(output.parent)
    output.mkdir(exist_ok=False)
    local_path(output)
    candidates = [r for r in records if r["needs"]]
    with (output / "missing_tags.csv").open("w", encoding="utf-8-sig", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=COLS)
        writer.writeheader()
        writer.writerows(r["row"] for r in candidates)
    manifest = {
        "schema_version": 1,
        "library_root": str(Path(library_root).absolute()),
        "records": candidates,
        "errors": errors,
        "coverage_notes": coverage_notes or [],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    summary = {
        "scanned_files": len(records)
        + sum(e.get("scope") != "library_entry" for e in errors),
        "verified_empty_noncanonical_directories": len(coverage_notes or []),
        "unreadable_library_entries": sum(
            e.get("scope") == "library_entry" for e in errors
        ),
        "complete_directory_walk": not any(
            e.get("scope") == "library_entry" for e in errors
        ),
        "incomplete_files": len(candidates),
        "complete_files": len(records) - len(candidates),
        "read_errors": sum(e.get("scope") != "library_entry" for e in errors),
        "missing_by_field": dict(Counter(k for r in candidates for k in r["needs"])),
        "csv_sha256": hashlib.sha256(
            (output / "missing_tags.csv").read_bytes()
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256(
            (output / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
