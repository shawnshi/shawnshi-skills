"""Split an explicitly supplied UTF-8 text and package explicit context files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SUPPORTED_EXTENSIONS = {".md", ".txt"}


def read_utf8(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not valid UTF-8: {path}: {exc}") from exc


def split_text(text: str, max_chars: int) -> list[str]:
    if max_chars < 100:
        raise ValueError("--chunk-size must be at least 100")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in text.splitlines():
        line = paragraph.rstrip()
        addition = len(line) + 1
        if current and size + addition > max_chars:
            chunks.append("\n".join(current).strip())
            current, size = [], 0
        if len(line) > max_chars:
            if current:
                chunks.append("\n".join(current).strip())
                current, size = [], 0
            for start in range(0, len(line), max_chars):
                chunks.append(line[start : start + max_chars])
            continue
        current.append(line)
        size += addition
    if current and "\n".join(current).strip():
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def main() -> int:
    parser = argparse.ArgumentParser(description="Package an explicit book-mirror input")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--context", action="append", default=[], type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--chunk-size", type=int, default=10000)
    args = parser.parse_args()

    try:
        if args.file.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("input must be .md or .txt; convert other formats separately")
        source_text = read_utf8(args.file)
        chunks = split_text(source_text, args.chunk_size)
        if not chunks:
            raise ValueError("input contains no non-whitespace text")

        context_sections = []
        context_paths = []
        for context_path in args.context:
            context_text = read_utf8(context_path)
            context_sections.append(f"## {context_path.name}\n\n{context_text.strip()}")
            context_paths.append(str(context_path.resolve()))

        output_dir = args.output_dir.resolve()
        chunks_dir = output_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        context_file = output_dir / "context.md"
        context_file.write_text("\n\n".join(context_sections), encoding="utf-8")

        chunk_entries = []
        for index, chunk in enumerate(chunks, 1):
            chunk_path = chunks_dir / f"chunk_{index:04d}.txt"
            chunk_path.write_text(chunk + "\n", encoding="utf-8")
            chunk_entries.append(
                {
                    "index": index,
                    "file": str(chunk_path),
                    "sha256": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                }
            )

        manifest = {
            "schema_version": 1,
            "source": str(args.file.resolve()),
            "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "context_sources": context_paths,
            "context_file": str(context_file),
            "chunk_count": len(chunk_entries),
            "chunks": chunk_entries,
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR[input]: {exc}")
        return 1

    print(str(manifest_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
