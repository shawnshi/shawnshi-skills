from __future__ import annotations

import json
import re
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from history_manager import save_history_items
from hub_utils import HISTORY_PATH, NEWS_DIR, atomic_dump_json


URL_PATTERN = re.compile(r"https?://[^\s\)\"\'\\\[\]<>]+")


def _json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_items(path: Path) -> list[dict[str, Any]]:
    payload = _json_payload(path)
    items = payload.get("top_10") if isinstance(payload, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


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
        ]
        if source_dir.exists()
        else []
    )
    json_stems = {path.with_suffix("").resolve() for path in json_files}
    markdown_files = [
        path
        for path in sorted(source_dir.rglob("intelligence_*_briefing.md"))
        if path.with_suffix("").resolve() not in json_stems and path.stem != excluded_stem
    ] if source_dir.exists() else []

    with tempfile.TemporaryDirectory(prefix="pih-history-rebuild-") as directory:
        stage = Path(directory) / "history.json"
        for archive in json_files:
            archive_payload = _json_payload(archive)
            save_history_items(
                [
                    item
                    for item in archive_payload.get("top_10", [])
                    if isinstance(item, dict)
                ]
                if isinstance(archive_payload.get("top_10"), list)
                else [],
                archive_ref=str(archive.relative_to(source_dir)).replace("\\", "/"),
                path=stage,
                now=_archive_datetime(archive, archive_payload, current),
            )
        for archive in markdown_files:
            save_history_items(
                _markdown_items(archive),
                archive_ref=str(archive.relative_to(source_dir)).replace("\\", "/"),
                path=stage,
                now=_archive_datetime(archive, {}, current),
            )
        if stage.exists():
            payload = json.loads(stage.read_text(encoding="utf-8"))
        else:
            payload = {
                "resource_kind": "pih_history_index",
                "schema_version": "2.0",
                "generated_at": current.isoformat(),
                "entries": [],
            }
        payload["generated_at"] = current.isoformat()
    atomic_dump_json(target, payload)
    print(
        f"[OK] history rebuilt: {len(payload['entries'])} events from "
        f"{len(json_files)} JSON and {len(markdown_files)} legacy Markdown archives"
    )
    return payload


if __name__ == "__main__":
    rebuild_history()
