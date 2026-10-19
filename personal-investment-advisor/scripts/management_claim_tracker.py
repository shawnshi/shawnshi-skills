import argparse
import json
import math
import os
import sys
import tempfile
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
    "annual_audited_filing",
    "quarterly_filing",
    "current_report",
    "user_authorized",
}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
RESERVED_LOCATORS = ("example.com", "example.test", ".invalid", "localhost")


def finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [])


def _document_errors(document: dict[str, Any], index: int) -> list[str]:
    errors = []
    for field in ["document_id", "source_tier", "source_locator", "published_at", "retrieved_at", "text"]:
        if not isinstance(document.get(field), str) or not document[field].strip():
            errors.append(f'source_documents[{index}].{field} must be a non-empty string')
    if not isinstance(document.get('source_tier'), str) or document['source_tier'] not in SOURCE_TIERS:
        errors.append(f"source_documents[{index}].source_tier is invalid")
    for field in ["published_at", "retrieved_at"]:
        try:
            date.fromisoformat(str(document.get(field)))
        except (TypeError, ValueError):
            errors.append(f"source_documents[{index}].{field} must be an ISO date")
    return errors


def evaluate_claims(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {'valid': False, 'formal_use_allowed': False,
                'errors': ['input must be an object']}
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
        if not isinstance(document.get('document_id'), str) or not document['document_id'].strip():
            errors.append(f'source_documents[{index}].document_id must be a non-empty string')
        locator = str(document.get("source_locator", "")).lower()
        if not test_mode and any(token in locator for token in RESERVED_LOCATORS):
            errors.append(f"source_documents[{index}].source_locator is a reserved test locator")

    document_ids = {
        document.get("document_id")
        for document in documents
        if isinstance(document, dict) and isinstance(document.get('document_id'), str)
        and document['document_id'].strip()
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
        string_fields = ('claim_id', 'statement', 'metric', 'source_locator')
        if any(not isinstance(claim[field], str) or not claim[field].strip() for field in string_fields):
            errors.append(f'claims[{index}] identity, statement, metric and locator must be non-empty strings')
            continue
        if 'actual_period_complete' in claim and type(claim['actual_period_complete']) is not bool:
            errors.append(f'claims[{index}].actual_period_complete must be boolean')
            continue
        if not isinstance(claim['source_document_id'], str) or claim['source_document_id'] not in document_ids:
            errors.append(f"claims[{index}].source_document_id does not match a source document")
            continue
        try:
            deadline = date.fromisoformat(str(claim['deadline']))
        except (TypeError, ValueError):
            errors.append(f"claims[{index}].deadline must be an ISO date")
            continue
        operator = claim.get("operator")
        if not isinstance(operator, str) or operator not in OPERATORS:
            errors.append(f"claims[{index}].operator must be one of {sorted(OPERATORS)}")
            continue

        actual = claim.get("actual")
        actual_source_id = claim.get("actual_source_document_id")
        actual_locator = claim.get("actual_source_locator")
        target = claim['target']
        if not finite_number(target):
            errors.append(f'claims[{index}].target must be a finite non-boolean number')
            continue
        if actual is not None and not finite_number(actual):
            errors.append(f'claims[{index}].actual must be a finite non-boolean number')
            continue
        status = 'not_due' if as_of is not None and as_of < deadline else 'insufficient_evidence'
        comparison = None
        period_verified = False
        period_reason = 'actual period not established'
        if actual is not None:
            if (not isinstance(actual_source_id, str) or actual_source_id not in document_ids
                    or not isinstance(actual_locator, str) or not actual_locator.strip()):
                errors.append(
                    f"claims[{index}] actual value requires actual_source_document_id and actual_source_locator"
                )
                continue
            period_fields = ('period_start', 'period_end', 'actual_period_start', 'actual_period_end')
            if all(claim.get(field) is not None for field in period_fields):
                try:
                    start, end, actual_start, actual_end = [
                        date.fromisoformat(str(claim[field])) for field in period_fields]
                except (TypeError, ValueError):
                    errors.append(f'claims[{index}] period fields must be ISO dates')
                    continue
                if start > end or actual_start > actual_end or end > deadline:
                    errors.append(f'claims[{index}] inconsistent period boundaries')
                    continue
                period_verified = (start == actual_start and end == actual_end
                                   and claim.get('actual_period_complete') is True
                                   and as_of is not None and actual_end <= as_of)
                period_reason = None if period_verified else 'actual period incomplete or mismatched'
            if period_verified and status != 'not_due':
                comparison = OPERATORS[operator](actual, target)
                status = 'met' if comparison else 'missed'

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
                'period_verified': period_verified,
                'period_reason': period_reason,
                'period_start': claim.get('period_start'),
                'period_end': claim.get('period_end'),
                'actual_period_start': claim.get('actual_period_start'),
                'actual_period_end': claim.get('actual_period_end'),
                'actual_period_complete': claim.get('actual_period_complete'),
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

    counts = {status: 0 for status in ['met', 'missed', 'insufficient_evidence', 'not_due']}
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
        _atomic_write_text(Path(args.output), rendered + "\n")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
