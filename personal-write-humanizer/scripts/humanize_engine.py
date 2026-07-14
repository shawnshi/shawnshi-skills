"""Local, deterministic checks for common machine-like Chinese prose patterns."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PATTERNS = {
    "empty_opening": [r"在.{0,20}背景下", r"随着.{0,20}(发展|推进)"],
    "formulaic_transition": [r"综上所述", r"总而言之", r"值得注意的是"],
    "parallel_template": [r"不仅.{0,80}(而且|更)", r"既.{0,80}又"],
    "vague_subject": [r"相关方面", r"有关部门", r"各方应"],
    "inflated_wording": [r"全面提升", r"深度赋能", r"形成合力", r"打造新格局"],
}


def read_input(value: str) -> tuple[str, str]:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8"), str(candidate.resolve())
    return value, "inline"


def inspect(text: str) -> dict:
    findings = []
    for category, patterns in PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                findings.append(
                    {
                        "category": category,
                        "text": match.group(0),
                        "start": match.start(),
                        "end": match.end(),
                    }
                )

    sentences = [part.strip() for part in re.split(r"[。！？!?]", text) if part.strip()]
    long_sentences = [sentence for sentence in sentences if len(sentence) > 80]
    return {
        "characters": len(text),
        "sentences": len(sentences),
        "long_sentence_count": len(long_sentences),
        "findings": findings,
        "review_notes": [
            "Keep facts, numbers, entities, negations, and causal qualifiers unchanged.",
            "Treat matches as review candidates, not automatic errors.",
            "Rewrite in context; do not apply blind global replacement.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Chinese prose for formulaic or vague patterns without calling an external model.")
    parser.add_argument("text_or_file", help="Inline text or a UTF-8 text file.")
    parser.add_argument("--output", help="Optional JSON report path. Without it, print only.")
    args = parser.parse_args()

    text, source = read_input(args.text_or_file)
    if not text.strip():
        parser.error("input is empty")

    report = {"source": source, **inspect(text)}
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized + "\n", encoding="utf-8")
        print(target)
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
