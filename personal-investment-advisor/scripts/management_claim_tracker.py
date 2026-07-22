import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any


OPERATORS = {
    ">=": lambda actual, target: actual >= target,
    ">": lambda actual, target: actual > target,
    "<=": lambda actual, target: actual <= target,
    "<": lambda actual, target: actual < target,
    "==": lambda actual, target: math.isclose(actual, target, rel_tol=1e-9, abs_tol=1e-12),
}
SOURCE_TIERS = {
    "company_primary",
    "regulator",
    "exchange",
    "audited_filing",
    "user_authorized",
}
RESERVED_LOCATORS = ("example.com", "example.test", ".invalid", "localhost")


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [])


def _document_errors(document: dict[str, Any], index: int) -> list[str]:
    errors = []
    for field in ["document_id", "source_tier", "source_locator", "published_at", "retrieved_at", "text"]:
        if not _non_empty(document.get(field)):
            errors.append(f"source_documents[{index}].{field} is required")
    if document.get("source_tier") not in SOURCE_TIERS:
        errors.append(f"source_documents[{index}].source_tier is invalid")
    for field in ["published_at", "retrieved_at"]:
        try:
            date.fromisoformat(str(document.get(field)))
        except (TypeError, ValueError):
            errors.append(f"source_documents[{index}].{field} must be an ISO date")
    return errors


def evaluate_claims(payload: dict[str, Any]) -> dict[str, Any]:
    documents = payload.get("source_documents")
    claims = payload.get("claims")
    errors: list[str] = []
    test_mode = payload.get("test_mode") is True
    if not isinstance(documents, list) or not documents:
        errors.append("source_documents must be a non-empty list")
        documents = []
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be a non-empty list")
        claims = []

    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            errors.append(f"source_documents[{index}] must be an object")
            continue
        errors.extend(_document_errors(document, index))
        locator = str(document.get("source_locator", "")).lower()
        if not test_mode and any(token in locator for token in RESERVED_LOCATORS):
            errors.append(f"source_documents[{index}].source_locator is a reserved test locator")

    document_ids = {
        document.get("document_id")
        for document in documents
        if isinstance(document, dict) and _non_empty(document.get("document_id"))
    }
    if len(document_ids) != len(documents):
        errors.append("source document IDs must be present and unique")
    as_of_date = payload.get("as_of_date")
    try:
        as_of = date.fromisoformat(str(as_of_date))
    except (TypeError, ValueError):
        errors.append("as_of_date must be an ISO date")
        as_of = None
    if as_of is not None:
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            try:
                published = date.fromisoformat(str(document.get("published_at")))
                retrieved = date.fromisoformat(str(document.get("retrieved_at")))
                if published > retrieved:
                    errors.append(f"source_documents[{index}] published_at cannot be after retrieved_at")
                if retrieved > as_of:
                    errors.append(f"source_documents[{index}] retrieved_at cannot be after as_of_date")
            except (TypeError, ValueError):
                pass
    results: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claims[{index}] must be an object")
            continue
        missing = [
            field
            for field in [
                "claim_id",
                "statement",
                "metric",
                "operator",
                "target",
                "deadline",
                "source_document_id",
                "source_locator",
            ]
            if not _non_empty(claim.get(field))
        ]
        if missing:
            errors.append(f"claims[{index}] missing fields: {', '.join(missing)}")
            continue
        if claim["source_document_id"] not in document_ids:
            errors.append(f"claims[{index}].source_document_id does not match a source document")
            continue
        try:
            date.fromisoformat(str(claim["deadline"]))
        except (TypeError, ValueError):
            errors.append(f"claims[{index}].deadline must be an ISO date")
            continue
        operator = claim.get("operator")
        if operator not in OPERATORS:
            errors.append(f"claims[{index}].operator must be one of {sorted(OPERATORS)}")
            continue

        actual = claim.get("actual")
        actual_source_id = claim.get("actual_source_document_id")
        actual_locator = claim.get("actual_source_locator")
        status = "insufficient_evidence"
        comparison = None
        if actual is not None:
            if actual_source_id not in document_ids or not _non_empty(actual_locator):
                errors.append(
                    f"claims[{index}] actual value requires actual_source_document_id and actual_source_locator"
                )
                continue
            try:
                actual_value = float(actual)
                target_value = float(claim["target"])
            except (TypeError, ValueError):
                errors.append(f"claims[{index}] target and actual must be numeric")
                continue
            comparison = OPERATORS[operator](actual_value, target_value)
            status = "met" if comparison else "missed"

        results.append(
            {
                "claim_id": claim["claim_id"],
                "statement": claim["statement"],
                "metric": claim["metric"],
                "operator": operator,
                "target": claim["target"],
                "deadline": claim["deadline"],
                "actual": actual,
                "status": status,
                "comparison_result": comparison,
                "claim_source": {
                    "document_id": claim["source_document_id"],
                    "locator": claim["source_locator"],
                },
                "actual_source": (
                    {"document_id": actual_source_id, "locator": actual_locator}
                    if actual is not None
                    else None
                ),
            }
        )

    counts = {status: 0 for status in ["met", "missed", "insufficient_evidence"]}
    for result in results:
        counts[result["status"]] += 1
    return {
        "valid": not errors,
        "stock_code": payload.get("stock_code"),
        "as_of_date": payload.get("as_of_date"),
        "management_claim_tracking": {
            "summary": counts,
            "claims": results,
            "assessment_boundary": "claim fulfillment only; no honesty or fraud inference",
            "formal_use_allowed": not test_mode and not errors,
        },
        "formal_use_allowed": not test_mode and not errors,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare sourced management claims with sourced actual results."
    )
    parser.add_argument("input_json")
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    result = evaluate_claims(payload)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
