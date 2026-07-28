"""Locate healthcare terms without making compliance or policy judgments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _term_groups(ontology):
    groups = {}
    for domain_name, domain in ontology.get("domains", {}).items():
        if not isinstance(domain, dict):
            continue
        for group_name, terms in domain.get("term_groups", domain.get("key_indicators", {})).items():
            if isinstance(terms, list):
                groups[f"{domain_name}.{group_name}"] = [str(term) for term in terms]
        themes = domain.get("themes", [])
        if isinstance(themes, list):
            groups[f"{domain_name}.themes"] = [str(term) for term in themes]
    return groups


def scan_terms(content, ontology):
    lower = content.lower()
    matches = []
    for group, terms in _term_groups(ontology).items():
        found = sorted({term for term in terms if term.lower() in lower})
        if found:
            matches.append({"group": group, "terms": found})
    return {
        "matches": matches,
        "review_note": (
            "Keyword matches locate possible evidence only. They do not establish "
            "compliance, certification level, policy value or a missing capability."
        ),
    }


def load_documents(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("input must be a JSON array")
    seen = set()
    for index, doc in enumerate(data):
        if not isinstance(doc, dict):
            raise ValueError(f"document[{index}] must be an object")
        if not isinstance(doc.get("id"), str) or not doc["id"].strip():
            raise ValueError(f"document[{index}].id must be a non-empty string")
        if doc["id"] in seen:
            raise ValueError(f"duplicate document id: {doc['id']}")
        seen.add(doc["id"])
        if not isinstance(doc.get("content"), str):
            raise ValueError(f"document[{index}].content must be a string")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Healthcare term locator")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--ontology",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "healthcare_ontology.json",
    )
    args = parser.parse_args()

    try:
        documents = load_documents(args.input)
        ontology = json.loads(args.ontology.read_text(encoding="utf-8"))
        results = {
            "schema_version": 1,
            "analysis_type": "keyword_location_only",
            "documents": {
                doc["id"]: scan_terms(doc["content"], ontology) for doc in documents
            },
        }
        output = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
            print(str(args.output.resolve()))
        else:
            print(output, end="")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR[input]: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
