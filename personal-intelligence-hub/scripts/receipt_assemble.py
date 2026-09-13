#!/usr/bin/env python3
"""Assemble a broker receipt JSON from a small header plus a body file.

Why this exists: the parent must publish the exact delivered readable text in a native
receipt, but a single shell command is limited (measured ~6.7 KB on Windows host
shells), so long bodies cannot be written inline in one call. This helper lets the
parent build the receipt from two files it can write separately or append to in
chunks, and rejects anything that would not match the sealed receipt schema.

It never touches the ledger: the parent still runs
``supplement_agent.py broker-record-fetch|broker-record-query`` with the produced file.

Usage:
  python -B -X utf8 receipt_assemble.py --kind fetch --header header.json \
      --body body.txt --out receipt.json
  python -B -X utf8 receipt_assemble.py --kind query --header header.json \
      --out receipt.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

MAX_BODY = 1024 * 1024

FETCH_REQUIRED = {
    "request_sha256",
    "gap_id",
    "reservation_id",
    "invocation_id",
    "tool",
    "arguments",
    "started_at",
    "completed_at",
    "outcome",
    "error",
    "text",
    "truncated",
    "parent_attestation",
}
# The body text is supplied through --body, never inside the header.
FETCH_HEADER_REQUIRED = FETCH_REQUIRED - {"text"}
QUERY_REQUIRED = {
    "request_sha256",
    "gap_id",
    "reservation_id",
    "tool",
    "query",
    "responseId",
    "outcome",
    "error",
    "results",
    "proof_subset",
    "parent_attestation",
}
OPTIONAL = {"responseId", "text_coverage"}


class AssembleError(ValueError):
    """Contract violation; never evidence that a receipt is unnecessary."""


def _load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except OSError as exc:
        raise AssembleError(f"{label} is unreadable: {exc.strerror or exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AssembleError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AssembleError(f"{label} must contain a JSON object")
    return payload


def _check_keys(payload: dict, required: set[str], label: str) -> None:
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - required - OPTIONAL)
    if missing:
        raise AssembleError(f"{label} is missing keys: {', '.join(missing)}")
    if extra:
        raise AssembleError(f"{label} has unexpected keys: {', '.join(extra)}")
    empty = sorted(key for key in required if payload.get(key) in (None, "") and key != "error")
    if empty:
        raise AssembleError(f"{label} has empty values: {', '.join(empty)}")


def _check_common(payload: dict, label: str, expected_tool: str) -> None:
    if payload.get("parent_attestation") != "actual_public_tool_receipt":
        raise AssembleError(f"{label} parent_attestation must be actual_public_tool_receipt")
    if payload.get("tool") != expected_tool:
        raise AssembleError(f"{label} tool must be {expected_tool}")
    outcome = payload.get("outcome")
    if expected_tool == "fetch_content":
        if outcome not in {"success", "error", "partial"}:
            raise AssembleError(f"{label} outcome must be success, error or partial")
    elif outcome not in {"error", "matched", "empty"}:
        raise AssembleError(f"{label} outcome must be error, matched or empty")
    error = payload.get("error")
    if outcome == "error":
        if not isinstance(error, str) or not error.strip():
            raise AssembleError(f"{label} error outcome requires a non-empty error string")
    elif error not in (None, ""):
        raise AssembleError(f"{label} non-error outcome must not carry an error string")


def assemble_fetch(header: dict, body_text: str) -> dict:
    _check_keys(header, FETCH_HEADER_REQUIRED, "fetch header")
    _check_common(header, "fetch header", "fetch_content")
    if not isinstance(header.get("arguments"), dict):
        raise AssembleError("fetch header arguments must be an object")
    if header.get("outcome") == "success" and not body_text.strip():
        raise AssembleError("fetch success requires non-empty body text")
    truncated = header.get("truncated")
    if truncated is not None and type(truncated) is not bool:
        raise AssembleError("fetch header truncated must be boolean or null")
    coverage = header.get("text_coverage")
    if coverage is not None and coverage not in {"full", "bounded_excerpt"}:
        raise AssembleError("fetch header text_coverage must be full or bounded_excerpt")
    size = len(body_text.encode("utf-8"))
    if size > MAX_BODY:
        raise AssembleError(f"body exceeds {MAX_BODY} bytes ({size})")
    receipt = dict(header)
    receipt["text"] = body_text
    if set(receipt) - OPTIONAL != FETCH_REQUIRED:
        raise AssembleError("assembled receipt does not match the sealed fetch schema")
    return receipt


def assemble_query(header: dict) -> dict:
    _check_keys(header, QUERY_REQUIRED, "query header")
    _check_common(header, "query header", "web_search")
    results = header.get("results")
    if not isinstance(results, list):
        raise AssembleError("query header results must be a list")
    if header.get("outcome") == "error" and results:
        raise AssembleError("query error outcome must preserve an empty results list")
    if header.get("outcome") == "matched" and not results:
        raise AssembleError("query matched outcome requires at least one result")
    proof = header.get("proof_subset")
    if not isinstance(proof, dict) or not proof:
        raise AssembleError("query header proof_subset must be a non-empty object")
    for result in results:
        if not isinstance(result, dict) or set(result) != {"url", "title"}:
            raise AssembleError("query results must each be {url, title} only")
    if len(json.dumps(header, ensure_ascii=False)) > 65536:
        raise AssembleError("query receipt exceeds the bounded public proof size")
    return dict(header)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("fetch", "query"), required=True)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--body", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        header = _load_json(args.header, "header")
        if args.kind == "fetch":
            if args.body is None:
                raise AssembleError("fetch assembly requires --body")
            try:
                body_text = args.body.read_text(encoding="utf-8", errors="strict")
            except OSError as exc:
                raise AssembleError(f"body is unreadable: {exc.strerror or exc}") from exc
            except UnicodeError as exc:
                raise AssembleError(f"body is not strict UTF-8: {exc}") from exc
            receipt = assemble_fetch(header, body_text)
        else:
            if args.body is not None:
                raise AssembleError("query assembly must not receive --body")
            receipt = assemble_query(header)
    except AssembleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    target = args.out.resolve()
    if target.exists():
        print(f"ERROR: refusing to overwrite existing {target}", file=sys.stderr)
        return 2
    payload = json.dumps(receipt, ensure_ascii=False, indent=1)
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        print(f"ERROR: cannot write receipt: {exc.strerror or exc}", file=sys.stderr)
        return 1
    written = target.read_text(encoding="utf-8")
    if written != payload:
        print("ERROR: receipt read-back mismatch", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "receipt_path": str(target),
                "kind": args.kind,
                "bytes": len(payload.encode("utf-8")),
                "text_bytes": len(receipt.get("text", "").encode("utf-8")),
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "note": "assembled only; the ledger is written by broker-record-*",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
