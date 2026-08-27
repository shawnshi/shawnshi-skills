from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from briefing_gate import validate_briefing_data
from history_manager import HistoryIndexBuilder
from hub_utils import HISTORY_PATH, NEWS_DIR, atomic_dump_json


URL_PATTERN = re.compile(r"https?://[^\s\)\"\'\\\[\]<>]+")
TRANSACTION_STAGE_PREFIX = ".pih-stage-"


class HistoryArchiveError(RuntimeError):
    """Raised when a formal archive cannot be trusted as history input."""


def _is_transaction_residue(path: Path, source_dir: Path) -> bool:
    try:
        relative = path.relative_to(source_dir)
    except ValueError:
        return True
    return any(part.startswith(TRANSACTION_STAGE_PREFIX) for part in relative.parts[:-1])


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoryArchiveError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise HistoryArchiveError(f"{label} must be a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HistoryArchiveError(f"cannot hash formal archive file: {path}: {exc}") from exc


def _validate_commit_sidecar(path: Path, payload: dict[str, Any]) -> None:
    markdown_path = path.with_suffix(".md")
    manifest_path = path.parent / f"{path.stem}.manifest.json"
    has_markdown = markdown_path.is_file()
    has_manifest = manifest_path.is_file()
    schema_version = str(payload.get("schema_version") or "")
    requires_triplet = schema_version in {"1.3", "1.4"}
    if requires_triplet and not (has_markdown and has_manifest):
        raise HistoryArchiveError(
            f"formal triplet is incomplete for schema {schema_version} archive: {path}"
        )
    if has_manifest and not has_markdown:
        raise HistoryArchiveError(f"formal triplet is incomplete: {path}")
    if not has_manifest:
        return

    sidecar = _read_json_object(manifest_path, "formal archive sidecar")
    try:
        markdown_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HistoryArchiveError(
            f"cannot read formal archive Markdown: {markdown_path}: {exc}"
        ) from exc
    expected = {
        "contract_version": "1.0",
        "run_id": payload.get("run_id"),
        "report_date": payload.get("report_date"),
        "schema_version": payload.get("schema_version"),
        "json_file": path.name,
        "markdown_file": markdown_path.name,
        "item_count": len(payload.get("top_10", [])),
    }
    for field, value in expected.items():
        if sidecar.get(field) != value:
            raise HistoryArchiveError(
                f"formal archive sidecar {field} does not match JSON: {manifest_path}"
            )
    if sidecar.get("json_sha256") != _sha256(path):
        raise HistoryArchiveError(
            f"formal archive JSON hash does not match sidecar: {path}"
        )
    if sidecar.get("markdown_sha256") != _sha256(markdown_path):
        raise HistoryArchiveError(
            f"formal archive Markdown hash does not match sidecar: {markdown_path}"
        )


def _verified_archive_payload(path: Path) -> dict[str, Any]:
    payload = _read_json_object(path, "formal archive")
    errors, _warnings = validate_briefing_data(payload)
    if errors:
        raise HistoryArchiveError(
            f"briefing gate failed for formal archive {path}: "
            + "; ".join(str(error) for error in errors)
        )
    report_date = str(payload.get("report_date") or "")
    if report_date:
        expected_stem = f"intelligence_{report_date.replace('-', '')}_briefing"
        if path.stem != expected_stem:
            raise HistoryArchiveError(
                f"formal archive filename does not match report_date: {path}"
            )
    else:
        legacy_match = re.fullmatch(r"intelligence_(\d{8})_briefing", path.stem)
        try:
            legacy_date = (
                datetime.strptime(legacy_match.group(1), "%Y%m%d").date()
                if legacy_match is not None
                else None
            )
        except ValueError:
            legacy_date = None
        if legacy_date is None:
            raise HistoryArchiveError(
                f"legacy formal archive requires a canonical filename date: {path}"
            )
    _validate_commit_sidecar(path, payload)
    return payload


def _assert_no_orphan_sidecars(source_dir: Path) -> None:
    for sidecar in sorted(source_dir.rglob("intelligence_*_briefing.manifest.json")):
        if _is_transaction_residue(sidecar, source_dir):
            continue
        stem = sidecar.name.removesuffix(".manifest.json")
        json_path = sidecar.with_name(f"{stem}.json")
        markdown_path = sidecar.with_name(f"{stem}.md")
        if not json_path.is_file() or not markdown_path.is_file():
            raise HistoryArchiveError(f"formal triplet is incomplete: {sidecar}")


def _archive_datetime(path: Path, payload: dict[str, Any], current: datetime) -> datetime:
    raw_generated = payload.get("generated_at")
    if raw_generated:
        try:
            parsed = datetime.fromisoformat(str(raw_generated).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=current.tzinfo)
            return parsed.astimezone(current.tzinfo)
        except ValueError:
            pass
    for raw_date in (payload.get("report_date"),):
        if raw_date:
            try:
                return datetime.combine(
                    date.fromisoformat(str(raw_date)),
                    time.min,
                    tzinfo=current.tzinfo,
                )
            except ValueError:
                pass
    match = re.search(r"intelligence_(\d{8})_briefing", path.name)
    if match:
        try:
            return datetime.combine(
                datetime.strptime(match.group(1), "%Y%m%d").date(),
                time.min,
                tzinfo=current.tzinfo,
            )
        except ValueError:
            pass
    return current


def _markdown_items(path: Path) -> list[dict[str, Any]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        {
            "url": match.rstrip(".,;)]"),
            "title": "",
            "source": "",
            "identity_quality": "provisional",
        }
        for match in URL_PATTERN.findall(content)
    ]


def rebuild_history(
    *,
    news_dir: Path | None = None,
    history_file: Path | None = None,
    now: datetime | None = None,
    exclude_report_date: str | None = None,
) -> dict[str, Any]:
    source_dir = news_dir or NEWS_DIR
    target = history_file or HISTORY_PATH
    current = now or datetime.now().astimezone()
    excluded_stem = (
        f"intelligence_{exclude_report_date.replace('-', '')}_briefing"
        if exclude_report_date
        else None
    )
    json_files = (
        [
            path
            for path in sorted(source_dir.rglob("intelligence_*_briefing.json"))
            if path.stem != excluded_stem
            and not _is_transaction_residue(path, source_dir)
        ]
        if source_dir.exists()
        else []
    )
    json_stems = {path.with_suffix("").resolve() for path in json_files}
    markdown_files = [
        path
        for path in sorted(source_dir.rglob("intelligence_*_briefing.md"))
        if path.with_suffix("").resolve() not in json_stems
        and path.stem != excluded_stem
        and not _is_transaction_residue(path, source_dir)
    ] if source_dir.exists() else []

    if source_dir.exists():
        _assert_no_orphan_sidecars(source_dir)
    verified_json_archives = [
        (archive, _verified_archive_payload(archive)) for archive in json_files
    ]

    builder = HistoryIndexBuilder()
    for archive, archive_payload in verified_json_archives:
        builder.merge(
            [
                item
                for item in archive_payload.get("top_10", [])
                if isinstance(item, dict)
            ]
            if isinstance(archive_payload.get("top_10"), list)
            else [],
            archive_ref=str(archive.relative_to(source_dir)).replace("\\", "/"),
            now=_archive_datetime(archive, archive_payload, current),
        )
    for archive in markdown_files:
        builder.merge(
            _markdown_items(archive),
            archive_ref=str(archive.relative_to(source_dir)).replace("\\", "/"),
            now=_archive_datetime(archive, {}, current),
        )
    payload = builder.payload(now=current)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(target, payload)
    print(
        f"[OK] history rebuilt: {len(payload['entries'])} events from "
        f"{len(verified_json_archives)} JSON and {len(markdown_files)} legacy Markdown archives"
    )
    return payload


if __name__ == "__main__":
    rebuild_history()
