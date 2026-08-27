import argparse
import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


VALID_MODES = ("brief", "board-memo", "deep-dive", "investment-case")
BLACKBOARD_SCHEMA_VERSION = 2
MATURITY_VALUES = (
    "working_draft",
    "review_ready",
    "decision_ready",
    "approved_for_execution",
    "blocked",
)


class AssemblyError(Exception):
    """A user-actionable assembly failure that can be returned as JSON."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.details = details or {}

    def as_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.path is not None:
            result["path"] = str(self.path.resolve(strict=False))
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class ChapterFile:
    path: Path
    relative_path: str
    number: int | None


def _is_frontmatter_delimiter(line: str) -> bool:
    """Return true only for a non-indented, exact YAML delimiter line."""

    return line.rstrip("\r\n").rstrip(" \t") == "---" and not line.startswith(
        (" ", "\t")
    )


def clean_content(content: str) -> str:
    """Remove only a complete YAML frontmatter block at the start of a file.

    A UTF-8 BOM and CRLF line endings are supported. An opening delimiter without
    a closing delimiter is preserved because it may be legitimate Markdown. No
    Markdown separators or triple-quoted text elsewhere in the document is
    altered.
    """

    if content.startswith("\ufeff"):
        content = content[1:]

    lines = content.splitlines(keepends=True)
    if not lines or not _is_frontmatter_delimiter(lines[0]):
        return content

    for index, line in enumerate(lines[1:], start=1):
        if _is_frontmatter_delimiter(line):
            return "".join(lines[index + 1 :])

    return content


def extract_action_titles(content: str) -> list[str]:
    titles = re.findall(r"^(#|##)\s+(.*)", content, re.MULTILINE)
    return [title for _level, title in titles]


def count_words(text: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_word_count = len(re.findall(r"\b[a-zA-Z0-9]+\b", text))
    return cjk_count + en_word_count


def chapter_patterns() -> tuple[str, ...]:
    return (
        "chapter*.md",
        "[0-9]*.md",
        "chapters/chapter*.md",
        "chapters/[0-9]*.md",
    )


def _chapter_number(path: Path) -> int | None:
    stem = path.stem
    match = re.match(r"chapter[_ -]?(\d+)", stem, flags=re.IGNORECASE)
    if match is None:
        match = re.match(r"(\d+)", stem)
    return int(match.group(1)) if match else None


def discover_chapters(project_path: Path, output_path: Path) -> list[ChapterFile]:
    discovered: dict[str, ChapterFile] = {}
    output_resolved = output_path.resolve(strict=False)

    try:
        for pattern in chapter_patterns():
            for path in project_path.glob(pattern):
                if not path.is_file() or path.resolve(strict=False) == output_resolved:
                    continue
                absolute_path = path.resolve(strict=False)
                relative_path = path.relative_to(project_path).as_posix()
                discovered[str(absolute_path)] = ChapterFile(
                    path=path,
                    relative_path=relative_path,
                    number=_chapter_number(path),
                )
    except OSError as exc:
        raise AssemblyError(
            "chapter_discovery_failed",
            f"cannot discover chapter files: {exc}",
            path=project_path,
        ) from exc

    return sorted(
        discovered.values(),
        key=lambda item: (
            item.number is None,
            item.number if item.number is not None else 0,
            item.relative_path.casefold(),
            item.relative_path,
        ),
    )


def duplicate_chapter_numbers(chapters: list[ChapterFile]) -> list[dict]:
    by_number: dict[int, list[str]] = defaultdict(list)
    for chapter in chapters:
        if chapter.number is not None:
            by_number[chapter.number].append(chapter.relative_path)

    return [
        {"number": number, "files": sorted(files, key=lambda item: (item.casefold(), item))}
        for number, files in sorted(by_number.items())
        if len(files) > 1
    ]


def read_text_input(path: Path, input_kind: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AssemblyError(
            "invalid_utf8",
            f"{input_kind} is not valid UTF-8",
            path=path,
            details={"start": exc.start, "end": exc.end},
        ) from exc
    except OSError as exc:
        raise AssemblyError(
            "input_read_failed",
            f"cannot read {input_kind}: {exc}",
            path=path,
        ) from exc


def load_blackboard(blackboard_path: Path | None, mode: str) -> dict:
    if blackboard_path is None:
        return {"provided": False}

    path = blackboard_path.resolve(strict=False)
    if not path.is_file():
        raise AssemblyError(
            "blackboard_not_found",
            "the requested blackboard file does not exist",
            path=path,
        )

    raw_text = read_text_input(path, "blackboard")
    if raw_text.startswith("\ufeff"):
        raw_text = raw_text[1:]
    try:
        state = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AssemblyError(
            "invalid_blackboard_json",
            "blackboard is not valid JSON",
            path=path,
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc

    if not isinstance(state, dict):
        raise AssemblyError(
            "invalid_blackboard_schema",
            "blackboard root must be a JSON object",
            path=path,
        )

    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        raise AssemblyError(
            "invalid_blackboard_schema",
            "blackboard metadata must be a JSON object",
            path=path,
        )

    schema_version = metadata.get("schema_version")
    if schema_version != BLACKBOARD_SCHEMA_VERSION:
        raise AssemblyError(
            "unsupported_blackboard_schema",
            f"blackboard schema_version must equal {BLACKBOARD_SCHEMA_VERSION}",
            path=path,
            details={"expected": BLACKBOARD_SCHEMA_VERSION, "actual": schema_version},
        )

    blackboard_mode = metadata.get("mode")
    if blackboard_mode not in VALID_MODES:
        raise AssemblyError(
            "invalid_blackboard_mode",
            "blackboard metadata.mode is missing or unsupported",
            path=path,
            details={"actual": blackboard_mode, "supported": list(VALID_MODES)},
        )

    alignment = state.get("alignment")
    alignment_mode = alignment.get("mode") if isinstance(alignment, dict) else None
    if alignment_mode not in (None, "", blackboard_mode):
        raise AssemblyError(
            "blackboard_internal_mode_mismatch",
            "blackboard metadata.mode and alignment.mode do not match",
            path=path,
            details={
                "metadata_mode": blackboard_mode,
                "alignment_mode": alignment_mode,
            },
        )

    if blackboard_mode != mode:
        raise AssemblyError(
            "blackboard_mode_mismatch",
            "assembler mode does not match blackboard metadata.mode",
            path=path,
            details={"assembler_mode": mode, "blackboard_mode": blackboard_mode},
        )

    maturity = metadata.get("maturity")
    if maturity not in MATURITY_VALUES:
        raise AssemblyError(
            "invalid_blackboard_maturity",
            "blackboard metadata.maturity is missing or unsupported",
            path=path,
            details={"actual": maturity, "supported": list(MATURITY_VALUES)},
        )

    return {
        "provided": True,
        "path": str(path),
        "schema_version": schema_version,
        "mode": blackboard_mode,
        "maturity": maturity,
    }


def atomic_write_text(output_path: Path, content: str, *, force: bool) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AssemblyError(
            "output_directory_failed",
            f"cannot create output directory: {exc}",
            path=output_path.parent,
        ) from exc

    if output_path.exists() and not force:
        raise AssemblyError(
            "output_exists",
            "output already exists; pass --force to replace it",
            path=output_path,
        )

    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        if force:
            os.replace(temporary_path, output_path)
            temporary_path = None
        else:
            try:
                os.link(temporary_path, output_path)
            except FileExistsError as exc:
                raise AssemblyError(
                    "output_exists",
                    "output appeared during assembly; pass --force to replace it",
                    path=output_path,
                ) from exc
            temporary_path.unlink()
            temporary_path = None

        try:
            directory_descriptor = os.open(output_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            # The completed file is already durable on platforms that do not
            # support directory fsync; this best-effort step is not a failure.
            pass
    except AssemblyError:
        raise
    except OSError as exc:
        raise AssemblyError(
            "output_write_failed",
            f"cannot atomically write output: {exc}",
            path=output_path,
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _append_markdown_block(parts: list[str], content: str) -> None:
    parts.append(content)
    if not content.endswith(("\n", "\r")):
        parts.append("\n")
    parts.append("\n---\n\n")


def assemble_report(
    project_path: Path,
    output_filename: str,
    title: str,
    mode: str,
    min_words: int | None,
    *,
    blackboard_path: Path | None = None,
    allow_empty: bool = False,
    force: bool = False,
) -> dict:
    project_path = project_path.resolve(strict=False)
    if not project_path.is_dir():
        raise AssemblyError(
            "invalid_project_path",
            "project path must be an existing directory",
            path=project_path,
        )
    if mode not in VALID_MODES:
        raise AssemblyError(
            "invalid_mode",
            "unsupported assembly mode",
            details={"actual": mode, "supported": list(VALID_MODES)},
        )
    if min_words is not None and min_words < 0:
        raise AssemblyError(
            "invalid_min_words",
            "min_words must be zero or greater",
            details={"actual": min_words},
        )

    output_path = (project_path / output_filename).resolve(strict=False)
    if not output_path.is_relative_to(project_path):
        raise AssemblyError(
            "output_outside_project",
            "output must remain inside the project path",
            path=output_path,
        )
    if mode in {"board-memo", "deep-dive", "investment-case"} and blackboard_path is None:
        raise AssemblyError(
            "blackboard_required",
            f"{mode} assembly requires a schema-v2 blackboard",
            path=project_path,
        )
    blackboard_audit = load_blackboard(blackboard_path, mode)
    chapters = discover_chapters(project_path, output_path)
    duplicates = duplicate_chapter_numbers(chapters)
    unnumbered = [item.relative_path for item in chapters if item.number is None]

    if not chapters and not allow_empty:
        raise AssemblyError(
            "no_chapters",
            "no chapter files were found; pass --allow-empty only when an empty draft is intentional",
            path=project_path,
            details={"patterns": list(chapter_patterns())},
        )

    current_date = datetime.now().strftime("%Y-%m-%d")
    maturity = blackboard_audit.get("maturity", "working_draft")
    yaml_header = f"""---
Title: {json.dumps(title, ensure_ascii=False)}
Date: {current_date}
Maturity: {maturity}
Author: HIT Digital Strategy Partner
Mode: {mode}
Version: 2.0
Audience: Strategic Decision Makers
---

# {title}
> Strategic decision draft

"""
    merged_content = [yaml_header]
    toc: list[str] = []
    audit_results: list[dict] = []
    chapter_contents: list[str] = []

    for chapter in chapters:
        raw_text = read_text_input(chapter.path, "chapter")
        clean_text = clean_content(raw_text)
        word_count = count_words(clean_text)
        toc.extend(extract_action_titles(clean_text))
        chapter_contents.append(clean_text)
        audit_results.append(
            {
                "file": chapter.relative_path,
                "chapter_number": chapter.number,
                "words": word_count,
                "depth_guide_words": min_words,
                "depth_guide_met": (
                    None if min_words is None else word_count >= min_words
                ),
            }
        )

    if toc:
        merged_content.append("## [Strategic Insight Index]\n")
        for index, title_item in enumerate(toc, start=1):
            merged_content.append(f"{index}. **{title_item}**\n")
        merged_content.append("\n---\n\n")

    for content in chapter_contents:
        _append_markdown_block(merged_content, content)

    final_text = "".join(merged_content)
    atomic_write_text(output_path, final_text, force=force)

    failed_chapters = [
        row["file"] for row in audit_results if row["depth_guide_met"] is False
    ]
    warnings: list[str] = []
    if not chapters:
        warnings.append("no chapters were merged because --allow-empty was specified")
    if failed_chapters:
        warnings.append(
            "user-specified chapter depth guide was not met after frontmatter removal: "
            + ", ".join(failed_chapters)
        )
    if duplicates:
        for duplicate in duplicates:
            warnings.append(
                f"duplicate chapter number {duplicate['number']}; deterministic path ordering applied: "
                + ", ".join(duplicate["files"])
            )
    if unnumbered:
        warnings.append(
            "chapter files without a numeric index were placed after numbered chapters: "
            + ", ".join(unnumbered)
        )

    return {
        "status": "success_with_warnings" if warnings else "success",
        "warnings": warnings,
        "path": str(output_path.resolve(strict=False)),
        "mode": mode,
        "blackboard": blackboard_audit,
        "chapters_merged": len(chapters),
        "chapter_order": [chapter.relative_path for chapter in chapters],
        "duplicate_chapter_numbers": duplicates,
        "unnumbered_chapters": unnumbered,
        "audit": audit_results,
        "failed_depth_list": failed_chapters,
        "final_size": len(final_text),
        "final_bytes": len(final_text.encode("utf-8")),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble strategic report")
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--output", default="final_report.md")
    parser.add_argument("--title", default="Strategic Deep Dive Report")
    parser.add_argument("--mode", default="deep-dive", choices=VALID_MODES)
    parser.add_argument(
        "--blackboard",
        type=Path,
        help=(
            "Schema-v2 strategy blackboard. Required for board-memo, deep-dive, "
            "and investment-case; metadata.mode must match --mode. Relative paths "
            "are resolved from the current working directory."
        ),
    )
    parser.add_argument(
        "--min-words",
        type=int,
        help=(
            "Optional user-specified depth guide, evaluated after leading "
            "frontmatter is removed. It produces warnings and never blocks assembly."
        ),
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow a title-only draft when no chapter files are present.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Atomically replace an existing output file.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = assemble_report(
            args.path,
            args.output,
            args.title,
            args.mode,
            args.min_words,
            blackboard_path=args.blackboard,
            allow_empty=args.allow_empty,
            force=args.force,
        )
    except AssemblyError as exc:
        print(
            json.dumps(
                {"status": "error", "error": exc.as_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except Exception as exc:  # Keep CLI failures machine-readable without a traceback.
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": "internal_error",
                        "message": f"unexpected assembly failure: {exc}",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
