"""Create a descriptive inventory of summary metadata."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def load_summaries(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("input must be a JSON array")
    seen = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"summary[{index}] must be an object")
        doc_id = item.get("id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError(f"summary[{index}].id must be a non-empty string")
        if doc_id in seen:
            raise ValueError(f"duplicate summary id: {doc_id}")
        seen.add(doc_id)
        if not isinstance(item.get("summary", ""), str):
            raise ValueError(f"summary[{index}].summary must be a string")
        if not isinstance(item.get("tags", []), list):
            raise ValueError(f"summary[{index}].tags must be a list")
    return data


def build_inventory(data):
    tags = Counter()
    types = Counter()
    methods = Counter()
    for item in data:
        tags.update(str(tag) for tag in item.get("tags", []))
        types[str(item.get("doc_type", "unclassified"))] += 1
        methods[str(item.get("summary_method", "unspecified"))] += 1
    return {
        "schema_version": 1,
        "analysis_type": "descriptive_inventory",
        "document_count": len(data),
        "document_types": dict(types.most_common()),
        "summary_methods": dict(methods.most_common()),
        "tag_frequency": dict(tags.most_common()),
        "limitations": [
            "Counts describe supplied metadata only.",
            "An absent keyword or tag is not evidence of a strategic, compliance or capability gap.",
            "Business relevance and portfolio priorities require human review against the source documents.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Descriptive document inventory")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_inventory(load_summaries(args.input))
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(str(args.output.resolve()))
        else:
            print(text, end="")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR[input]: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
