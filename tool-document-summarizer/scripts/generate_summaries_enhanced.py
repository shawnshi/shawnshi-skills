"""Evidence-bounded document summaries with opt-in external model use."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def load_documents(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("input must be a JSON array")
    seen = set()
    for index, doc in enumerate(data):
        if not isinstance(doc, dict):
            raise ValueError(f"document[{index}] must be an object")
        for field in ("id", "filename", "content"):
            if not isinstance(doc.get(field), str):
                raise ValueError(f"document[{index}].{field} must be a string")
        if not doc["id"].strip():
            raise ValueError(f"document[{index}].id must not be empty")
        if doc["id"] in seen:
            raise ValueError(f"duplicate document id: {doc['id']}")
        seen.add(doc["id"])
    return data


def extractive_summary(content, max_chars):
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", content)]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return "", []
    selected = []
    total = 0
    for paragraph in paragraphs:
        if selected and total + len(paragraph) + 1 > max_chars:
            break
        selected.append(paragraph[:max_chars] if not selected else paragraph)
        total += len(selected[-1]) + 1
        if total >= max_chars:
            break
    return "\n".join(selected)[:max_chars], list(range(1, len(selected) + 1))


def external_summary(filename, content, model_name, api_key):
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise RuntimeError("google-generativeai is not installed") from exc
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = (
        "Summarize only claims supported by the supplied excerpt. Preserve numbers, "
        "negation, conditions and uncertainty. Do not infer compliance, clinical "
        "advice, strategic value or missing capabilities. Return plain text.\n\n"
        f"Filename: {filename}\nExcerpt:\n{content}"
    )
    response = model.generate_content(prompt)
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("external model returned no text")
    return text.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate evidence-bounded summaries")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-chars", type=int, required=True)
    parser.add_argument("--allow-external-model", action="store_true")
    parser.add_argument(
        "--external-max-chars",
        type=int,
        help="explicit maximum source characters sent to the external model",
    )
    args = parser.parse_args()
    if args.max_chars <= 0:
        print("ERROR[argument]: --max-chars must be positive", file=sys.stderr)
        return 2
    if args.allow_external_model and (
        args.external_max_chars is None or args.external_max_chars <= 0
    ):
        print(
            "ERROR[authorization]: --allow-external-model requires a positive "
            "--external-max-chars data boundary",
            file=sys.stderr,
        )
        return 2
    if args.external_max_chars is not None and not args.allow_external_model:
        print(
            "ERROR[argument]: --external-max-chars requires --allow-external-model",
            file=sys.stderr,
        )
        return 2

    try:
        documents = load_documents(args.input)
        api_key = os.environ.get("DOCUMENT_SUMMARIZER_API_KEY")
        model_name = os.environ.get("DOCUMENT_SUMMARIZER_MODEL")
        if args.allow_external_model and (not api_key or not model_name):
            raise ValueError(
                "--allow-external-model requires DOCUMENT_SUMMARIZER_API_KEY and DOCUMENT_SUMMARIZER_MODEL"
            )

        results = []
        for doc in documents:
            method = "extractive_local"
            warnings = []
            if args.allow_external_model:
                excerpt = doc["content"][: args.external_max_chars]
                try:
                    summary = external_summary(doc["filename"], excerpt, model_name, api_key)
                    method = f"external:{model_name}"
                    source_units = [
                        f"excerpt:first_{args.external_max_chars}_chars"
                    ]
                except Exception as exc:
                    # A single classified failure changes the method to local; no blind retry.
                    summary, paragraphs = extractive_summary(doc["content"], args.max_chars)
                    source_units = [f"paragraph:{number}" for number in paragraphs]
                    warnings.append(f"external_model_error; changed_to_local: {type(exc).__name__}: {exc}")
            else:
                summary, paragraphs = extractive_summary(doc["content"], args.max_chars)
                source_units = [f"paragraph:{number}" for number in paragraphs]

            results.append(
                {
                    "id": doc["id"],
                    "filename": doc["filename"],
                    "summary": summary,
                    "summary_method": method,
                    "source_units": source_units,
                    "source_truncated": (
                        len(doc["content"]) > args.external_max_chars
                        if method.startswith("external:")
                        else len(summary) < len(doc["content"])
                    ),
                    "tags": [],
                    "warnings": warnings,
                }
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(str(args.output.resolve()))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR[input]: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
