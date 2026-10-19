"""Opt-in content-addressed source ZIPs. Independent restores; no run migration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

META = "__bundle_inventory__.json"
MAX_FILES = 512
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
# This skill's approved static layout, not a declaration from an input archive.
SOURCE_FILES = {
    "SKILL.md", "resource-manifest.json", "requirements.txt", "agents/openai.yaml",
    "references/briefing_schema.json", "references/briefing_schema_v1.0.json",
    "references/briefing_schema_v1.1.json", "references/briefing_schema_v1.2.json",
    "references/briefing_schema_v1.3.json", "references/briefing_template.md",
    "references/karpathy_feeds.json", "references/prompts/v1_refine_system.md",
    "references/quality_standard.md", "references/responses.md",
    "references/run_manifest_schema.json", "references/strategic_focus.json",
    "references/subagent_prompts.json", "references/workflow_protocols.md",
    "references/collection-quality.md",
}


def _source_name(name):
    _safe_name(name)
    parts = PurePosixPath(name).parts
    if name not in SOURCE_FILES and not (len(parts) == 2 and parts[0] == "scripts" and parts[1].endswith(".py")):
        raise BundlePoolError("member is outside the approved static source layout")
    return name


class BundlePoolError(ValueError):
    pass


def _safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise BundlePoolError("invalid bundle member path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name or name == "." or len(name) > 2048:
        raise BundlePoolError("bundle path escapes or is not canonical")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    for part in path.parts:
        if part.endswith((".", " ")) or part.split('.')[0].casefold() in reserved or any(c in part for c in '<>"|?*'):
            raise BundlePoolError("bundle path uses a reserved Windows filename")
    return name


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _identity(files):
    return _sha(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def _table(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise BundlePoolError("bundle file table exceeds limit or is empty")
    seen, total = set(), 0
    for name, record in files.items():
        _source_name(name)
        if name == META or name.casefold() in seen:
            raise BundlePoolError("bundle member duplicates reserved/case-insensitive name")
        seen.add(name.casefold())
        if not isinstance(record, dict) or set(record) != {"sha256", "bytes"}:
            raise BundlePoolError("bundle member descriptor is invalid")
        digest, size = record["sha256"], record["bytes"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise BundlePoolError("bundle member hash is invalid")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise BundlePoolError("bundle member exceeds size limit")
        total += size
    for name in files:
        if any(str(parent).casefold() in seen for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise BundlePoolError("bundle file/directory paths conflict")
    if total > MAX_TOTAL_BYTES:
        raise BundlePoolError("bundle expanded size exceeds limit")
    if not {"SKILL.md", "resource-manifest.json"}.issubset(files):
        raise BundlePoolError("source bundle lacks skill/resource manifest")
    return total


def _source_inventory(root):
    from run_contract import validate_resource_manifest

    root = Path(root).resolve()
    resource_path = root / "resource-manifest.json"
    if resource_path.stat().st_size > 1024 * 1024:
        raise BundlePoolError("resource manifest exceeds limit")
    resource = json.loads(resource_path.read_text(encoding="utf-8"))
    if resource.get("skill") != "personal-intelligence-hub":
        raise BundlePoolError("bundle pool only accepts personal-intelligence-hub source packages")
    names = {"SKILL.md", "resource-manifest.json"}
    for key in ("top_level_file_hashes", "resource_file_hashes"):
        rows = resource.get(key)
        if not isinstance(rows, list):
            raise BundlePoolError("source resource table is invalid")
        names.update(_source_name(row["path"]) for row in rows)
    if len(names) > MAX_FILES:
        raise BundlePoolError("source bundle exceeds file limit")
    files = {}
    for name in sorted(names):
        path = root / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and p.is_relative_to(root)):
            raise BundlePoolError("source symlinks are not exported")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise BundlePoolError("source member missing or outside source package")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise BundlePoolError("source member exceeds size limit")
        data = path.read_bytes()
        files[name] = {"sha256": _sha(data), "bytes": len(data)}
    _table(files)
    validate_resource_manifest(resource_path, root / "SKILL.md")
    return root, files


def verify_archive(path):
    """Validate names and expansion bounds before reading archive members."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not 2 <= len(infos) <= MAX_FILES + 1:
            raise BundlePoolError("ZIP member count exceeds limit")
        seen, by_name, total = set(), {}, 0
        for info in infos:
            name = _safe_name(info.filename)
            if name.casefold() in seen or info.is_dir() or info.flag_bits & 1:
                raise BundlePoolError("duplicate, directory or encrypted ZIP member")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise BundlePoolError("ZIP special files are forbidden")
            if info.file_size > MAX_FILE_BYTES:
                raise BundlePoolError("ZIP member exceeds size limit")
            total += info.file_size
            seen.add(name.casefold())
            by_name[name] = info
        if total > MAX_TOTAL_BYTES or META not in by_name or by_name[META].file_size > 1024 * 1024:
            raise BundlePoolError("ZIP inventory missing or expanded size exceeds limit")
        metadata = json.loads(archive.read(META))
        if not isinstance(metadata, dict) or metadata.get("format") != "source-bundle-pool/1.0":
            raise BundlePoolError("unknown bundle inventory format")
        files = metadata.get("files")
        if not isinstance(files, dict):
            raise BundlePoolError("bundle file table must be an object")
        expanded = _table(files)
        if metadata.get("bundle_id") != _identity(files) or set(by_name) != {*files, META}:
            raise BundlePoolError("ZIP inventory identity/member mismatch")
        for name, record in files.items():
            if by_name[name].file_size != record["bytes"] or _sha(archive.read(name)) != record["sha256"]:
                raise BundlePoolError("ZIP member hash/size mismatch")
    return {"format": metadata["format"], "bundle_id": metadata["bundle_id"], "files": files,
            "source_bytes": expanded, "archive_bytes": Path(path).stat().st_size,
            "integrity_scope": "Content integrity only, not trusted authorship or permission to execute."}


def pack_bundle(source_root, pool_dir):
    root, files = _source_inventory(source_root)
    pool = Path(pool_dir).resolve()
    if pool.is_relative_to(root) or root.is_relative_to(pool):
        raise BundlePoolError("source and pool directories must not overlap")
    pool.mkdir(parents=True, exist_ok=True)
    identity = _identity(files)
    target = pool / f"{identity}.zip"
    if target.exists():
        report = verify_archive(target)
        if report["bundle_id"] != identity:
            raise BundlePoolError("existing pool object has a different identity")
        return {"archive_path": str(target), "reused": True, **report}
    descriptor, name = tempfile.mkstemp(prefix=".bundle-", suffix=".tmp", dir=pool)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for rel, record in files.items():
                data = (root / rel).read_bytes()
                if _sha(data) != record["sha256"]:
                    raise BundlePoolError("source changed during export")
                archive.writestr(rel, data)
            archive.writestr(META, json.dumps({"format": "source-bundle-pool/1.0", "bundle_id": identity, "files": files}, sort_keys=True))
        report = verify_archive(temporary)
        try:
            # Atomic no-clobber publication of a ZIP object; the temporary link is removed.
            # No source or executable file is hardlinked between runs.
            os.link(temporary, target)
            reused = False
        except FileExistsError:
            if verify_archive(target)["bundle_id"] != identity:
                raise BundlePoolError("raced pool object has a different identity")
            reused = True
        return {"archive_path": str(target), "reused": reused, **report}
    finally:
        temporary.unlink(missing_ok=True)


def restore_bundle(archive_path, destination):
    report = verify_archive(archive_path)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise BundlePoolError("restore destination exists; never overwrite a run or source tree")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()  # Exclusive ownership; fail if another writer won the race.
    restored_root = destination / "personal-intelligence-hub"
    try:
        restored_root.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for rel, record in report["files"].items():
                data = archive.read(rel)
                if len(data) != record["bytes"] or _sha(data) != record["sha256"]:
                    raise BundlePoolError("archive changed during restore")
                path = restored_root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as handle:
                    handle.write(data)
        root, files = _source_inventory(restored_root)
        if _identity(files) != report["bundle_id"]:
            raise BundlePoolError("restored source bundle identity changed")
    except BaseException as original:
        try:
            shutil.rmtree(destination)
        except OSError as cleanup_error:
            raise BundlePoolError(f"restore failed: {original}; cleanup failed: {cleanup_error}") from original
        raise
    return {"container": str(destination), "destination": str(root), "bundle_id": report["bundle_id"], "files": len(files),
            "independent_copy": True, "run_manifests_rewritten": False, "execution_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--source-root", type=Path, required=True)
    pack.add_argument("--pool-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = pack_bundle(args.source_root, args.pool_dir) if args.command == "pack" else restore_bundle(args.archive, args.destination) if args.command == "restore" else verify_archive(args.archive)
        print(json.dumps(report, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
