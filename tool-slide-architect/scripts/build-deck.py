"""Validate a v2 blueprint and package structured JSON; never renders PPTX."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from safe_io import SafeWriteError, atomic_write_text, paths_alias, reject_symlink_path
from validator import (
    SCHEMA_VERSION,
    VALIDATION_SCOPE,
    StructuredArgumentParser,
    audit_outline,
    issue,
    load_source,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decision(record: list[str]) -> dict[str, Any]:
    return {"id": record[0], "action": record[1], "request": record[2], "owner": record[3], "due_date": record[4]}


def _claim(record: list[str]) -> dict[str, Any]:
    references = [] if record[4].lower() == "none" else [part.strip() for part in record[4].split(",")]
    return {"id": record[0], "kind": record[1], "status": record[2], "statement": record[3], "evidence_ids": references}


def _evidence(record: list[str]) -> dict[str, Any]:
    return {"id": record[0], "source": record[1], "date": record[2], "scope": record[3], "locator": record[4]}


def _open_item(record: list[str]) -> dict[str, Any]:
    return {"id": record[0], "kind": record[1], "description": record[2], "owner": record[3], "due_date": record[4]}


def _risk(record: list[str]) -> dict[str, Any]:
    return {"id": record[0], "category": record[1], "severity": record[2], "description": record[3], "mitigation": record[4]}


def _asset(record: list[str]) -> dict[str, Any]:
    return {"id": record[0], "reference": record[1], "rights": record[2], "deidentification": record[3]}


def normalized_slide(slide: dict[str, Any]) -> dict[str, Any]:
    records = slide["records"]
    content: dict[str, Any] = {"body": slide["content"].get("Body", "")}
    if "Action" in slide["content"]:
        content["action"] = slide["content"]["Action"]
    content["decisions"] = [_decision(record) for record in records["decisions"]]

    visual: dict[str, Any] = {
        "layout": slide["visual"].get("Layout", ""),
        "visual_description": slide["visual"].get("Visual Description", ""),
        "assets": [_asset(record) for record in records["assets"]],
    }
    if "Chart" in slide["visual"]:
        visual["chart"] = slide["visual"]["Chart"]

    delivery: dict[str, Any] = {"speaker_notes": slide["delivery"].get("Speaker Notes", "")}
    if "Delivery Notes" in slide["delivery"]:
        delivery["delivery_notes"] = slide["delivery"]["Delivery Notes"]

    normalized: dict[str, Any] = {
        "slide_id": slide["slide_id"],
        "page": int(slide["page"]),
        "type": slide["type"],
        "narrative": {
            "goal": slide["narrative"].get("Goal", ""),
            "title": slide["narrative"].get("Title", ""),
        },
        "content": content,
        "evidence": {
            "claims": [_claim(record) for record in records["claims"]],
            "sources": [_evidence(record) for record in records["evidence"]],
            "open_items": [_open_item(record) for record in records["open_items"]],
            "risk_flags": [_risk(record) for record in records["risk_flags"]],
        },
        "visual": visual,
        "delivery": delivery,
    }
    if slide.get("section"):
        normalized["section"] = slide["section"]
    if "Takeaway" in slide["narrative"]:
        normalized["narrative"]["takeaway"] = slide["narrative"]["Takeaway"]
    normalized["content_hash"] = _sha256(normalized)
    return normalized


def _normalized_metadata(metadata: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = dict(metadata)
    for key in ("Schema_Version", "Duration_Minutes", "Slide_Count"):
        if key in normalized and str(normalized[key]).isdigit():
            normalized[key] = int(normalized[key])
    return normalized


def _previous_hashes(path: Path) -> tuple[dict[str, str], list[str]]:
    reject_symlink_path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SafeWriteError("E_PREVIOUS_NOT_FOUND", "Previous bundle does not exist.", path=str(path)) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SafeWriteError("E_PREVIOUS_READ", "Could not read previous bundle.", path=str(path), detail=str(exc)) from exc
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("artifact_type") != "presentation_blueprint_bundle":
        raise SafeWriteError("E_PREVIOUS_SCHEMA", "Previous bundle does not use the supported blueprint-bundle schema.", path=str(path))
    slides = payload.get("slides")
    if not isinstance(slides, list):
        raise SafeWriteError("E_PREVIOUS_SCHEMA", "Previous bundle has no slides array.", path=str(path))
    hashes: dict[str, str] = {}
    order: list[str] = []
    for item in slides:
        if not isinstance(item, dict) or not isinstance(item.get("slide_id"), str):
            raise SafeWriteError("E_PREVIOUS_SCHEMA", "Previous bundle contains an invalid slide.", path=str(path))
        slide_id = item["slide_id"]
        if slide_id in hashes:
            raise SafeWriteError("E_PREVIOUS_SCHEMA", "Previous bundle contains duplicate slide IDs.", path=str(path), slide_id=slide_id)
        content_hash = item.get("content_hash")
        if not isinstance(content_hash, str):
            without_hash = {key: value for key, value in item.items() if key != "content_hash"}
            content_hash = _sha256(without_hash)
        elif not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise SafeWriteError("E_PREVIOUS_SCHEMA", "Previous bundle contains an invalid content hash.", path=str(path), slide_id=slide_id)
        hashes[slide_id] = content_hash
        order.append(slide_id)
    return hashes, order


def _changed_slide_ids(slides: list[dict[str, Any]], previous: Path) -> tuple[list[str], list[str]]:
    old_hashes, old_order = _previous_hashes(previous)
    new_hashes = {slide["slide_id"]: slide["content_hash"] for slide in slides}
    changed = [slide["slide_id"] for slide in slides if old_hashes.get(slide["slide_id"]) != slide["content_hash"]]
    removed = [slide_id for slide_id in old_order if slide_id not in new_hashes]
    return changed, removed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StructuredArgumentParser(description=__doc__)
    parser.add_argument("path", help="outline.md, directory containing outline.md, or '-' for stdin")
    parser.add_argument("--output", "-o", type=Path, default=Path("blueprint_bundle.json"), help="JSON output path; relative paths are resolved beside the source outline.")
    parser.add_argument("--force", action="store_true", help="Replace an existing non-symlink output.")
    parser.add_argument("--previous", type=Path, help="Previous bundle used to calculate changed_slide_ids.")
    return parser.parse_args(argv)


def _failure(error: dict[str, Any], *, source_schema_version: int | str = "unknown") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": source_schema_version,
        "validation_scope": VALIDATION_SCOPE,
        "status": "fail",
        "errors": [error],
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.output.suffix.lower() != ".json":
            raise SafeWriteError("E_OUTPUT_EXTENSION", "Output must use the .json extension.", path=str(args.output))

        if args.path == "-":
            content, source_files = sys.stdin.read(), ["<stdin>"]
            base_dir = Path.cwd()
            input_path: Path | None = None
        else:
            requested = Path(args.path)
            reject_symlink_path(requested)
            content, source_files = load_source(requested)
            input_path = Path(source_files[0])
            reject_symlink_path(input_path)
            input_path = input_path.resolve(strict=True)
            source_files = [str(input_path)]
            base_dir = requested if requested.is_dir() else requested.parent

        output_path = args.output if args.output.is_absolute() else base_dir / args.output
        reject_symlink_path(output_path)
        if input_path is not None and paths_alias(input_path, output_path):
            raise SafeWriteError("E_INPUT_OUTPUT_ALIAS", "Input and output must not be the same file or aliases.", input=str(input_path), output=str(output_path))

        report, document = audit_outline(content)
        if report["errors"]:
            report["source_files"] = source_files
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        slides = [normalized_slide(slide) for slide in document["slides"]]
        metadata = _normalized_metadata(document["metadata"])
        hash_payload = {"schema_version": SCHEMA_VERSION, "metadata": metadata, "style_instructions": document["style_instructions"], "slides": [{key: value for key, value in slide.items() if key != "content_hash"} for slide in slides]}
        deck_hash = _sha256(hash_payload)

        changed: list[str] | None = None
        removed: list[str] = []
        if args.previous:
            previous = args.previous if args.previous.is_absolute() else base_dir / args.previous
            changed, removed = _changed_slide_ids(slides, previous)

        bundle: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source_schema_version": document["source_schema_version"],
            "validation_scope": VALIDATION_SCOPE,
            "artifact_type": "presentation_blueprint_bundle",
            "pptx_generated": False,
            "source_files": source_files,
            "metadata": metadata,
            "style_instructions": document["style_instructions"],
            "slides": slides,
            "deck_hash": deck_hash,
            "validation": {"status": report["status"], "warnings": report["warnings"], "review": report["review"]},
        }
        if changed is not None:
            bundle["change_set"] = {"changed_slide_ids": changed, "removed_slide_ids": removed}

        atomic_write_text(output_path, json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", force=args.force)
        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source_schema_version": document["source_schema_version"],
            "validation_scope": VALIDATION_SCOPE,
            "status": "packaged",
            "artifact_type": "presentation_blueprint_bundle",
            "output": str(output_path),
            "slide_count": len(slides),
            "warning_count": len(report["warnings"]),
            "deck_hash": deck_hash,
            "pptx_generated": False,
        }
        if changed is not None:
            result["changed_slide_ids"] = changed
            result["removed_slide_ids"] = removed
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SafeWriteError as exc:
        print(json.dumps(_failure(exc.as_issue()), ensure_ascii=False, indent=2))
        return 1
    except ValueError as exc:
        print(json.dumps(_failure(issue("E_ARGUMENT", str(exc))), ensure_ascii=False, indent=2))
        return 2
    except (OSError, UnicodeError) as exc:
        print(json.dumps(_failure(issue("E_FILE_IO", str(exc))), ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:  # Keep CLI failures machine-readable.
        print(json.dumps(_failure(issue("E_INTERNAL", "Unexpected packaging failure.", detail=f"{type(exc).__name__}: {exc}")), ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
