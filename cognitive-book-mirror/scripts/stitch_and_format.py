"""Combine numbered book-mirror result files into an explicit output path."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

RESULT_PATTERN = re.compile(r"^result_(\d+)\.md$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stitch book-mirror result files")
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--book-title", default="认知镜像")
    args = parser.parse_args()

    if not args.results_dir.is_dir():
        print(f"ERROR[input]: results directory not found: {args.results_dir}")
        return 1

    numbered = []
    for path in args.results_dir.glob("result_*.md"):
        match = RESULT_PATTERN.match(path.name)
        if not match:
            print(f"ERROR[numbering]: invalid result filename: {path.name}")
            return 1
        numbered.append((int(match.group(1)), path))
    if not numbered:
        print("ERROR[input]: no result_<number>.md files found")
        return 1

    numbered.sort()
    indices = [index for index, _ in numbered]
    if len(indices) != len(set(indices)):
        print("ERROR[numbering]: duplicate result number")
        return 1
    expected = list(range(1, indices[-1] + 1))
    if indices != expected:
        print(f"ERROR[numbering]: expected contiguous sequence {expected}, got {indices}")
        return 1

    sections = [f"# {args.book_title}"]
    try:
        for index, path in numbered:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                raise ValueError(f"{path.name} contains no content")
            sections.append(f"## 分片 {index}\n\n{text}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    except UnicodeDecodeError as exc:
        print(f"ERROR[input]: result is not valid UTF-8: {exc}")
        return 1
    except (OSError, ValueError) as exc:
        print(f"ERROR[write]: {exc}")
        return 1

    print(str(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
