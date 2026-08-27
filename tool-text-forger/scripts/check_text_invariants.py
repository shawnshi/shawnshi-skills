#!/usr/bin/env python3
"""Compare protected textual invariants between an original and a revision."""

from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


NUMBER_RE = re.compile(
    r"(?<!\d)[-+]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?(?:[%％])?(?!\d)"
)
UNIT_RE = re.compile(
    r"(?<!\d)[-+]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?\s*"
    r"(?:%|％|人民币|美元|万元|亿元|元|人|例|次|项|套|家|张|床|年|月|日|天|"
    r"小时|分钟|秒|PB|TB|GB|MB|KB|Gbps|Mbps|Kbps|bps|mmHg|kPa|Pa|"
    r"mmol/L|μmol/L|umol/L|mg/dL|g/L|mEq/L|IU/L|U/L|mL/min|L/min|次/分钟|次/分|"
    r"bpm|km|cm|mm|μm|nm|m|kg|mg|μg|ug|g|mL|ml|L|℃|°C)(?![A-Za-z])",
    re.IGNORECASE,
)
URL_RE = re.compile(
    r"(?:https?://[^\s<>{}]+|mailto:[^\s<>{}]+|\[[^\]\n]+\]\([^)\s]+\))",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(
    r"(?:\{\{[^{}\n]+\}\}|\$\{[^{}\n]+\}|"
    r"【[^】\n]*(?:待|TBD|TODO|XXX)[^】\n]*】|"
    r"\[[^\]\n]*(?:待|TBD|TODO|XXX)[^\]\n]*\]|"
    r"待确认|待核实|\bTBD\b|\bTODO\b|\bXXX\b)",
    re.IGNORECASE,
)
CITATION_RE = re.compile(
    r"(?<!\!)\[(?:\^[^\]\n]+|\d+(?:\s*[-–—,，]\s*\d+)*|"
    r"@[A-Za-z0-9_:.+-]+(?:\s*;\s*@[A-Za-z0-9_:.+-]+)*)\]"
)
QUOTE_RE = re.compile(
    r"“[^”]+”|‘[^’]+’|「[^」]+」|『[^』]+』|(?<!\w)\"[^\"]+\"(?!\w)"
)
SEMANTIC_MARKER_RE = re.compile(
    r"不得少于|不得超过|应不少于|应不超过|不超过|不少于|尚不能|尚未|不得|禁止|"
    r"必须|应当|无需|至少|至多|最多|少于|超过|低于|高于|以内|以外|仅限|仅|"
    r"可能|或许|预计|建议|可以|大约|约|未|不|"
    r"\b(?:not|no|never|must|shall|should|may|might|could|only|"
    r"at\s+least|at\s+most|approximately|likely|unlikely)\b",
    re.IGNORECASE,
)
MARKDOWN_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

BASE_REQUIRED = {
    "numbers",
    "units",
    "urls",
    "placeholders",
    "citations",
    "quotes",
    "protected_terms",
    "tables",
    "json_validity",
    "json_shape",
    "json_values",
    "authorized_scope",
}
STRICT_REQUIRED = BASE_REQUIRED | {"semantic_markers", "headings", "protected_order"}


class DuplicateJsonKeyError(ValueError):
    pass


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def sequence_matches(pattern: re.Pattern[str], text: str) -> list[str]:
    return [match.group(0) for match in pattern.finditer(text)]


def sequence_terms(text: str, terms: Iterable[str]) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    for term in terms:
        if not term:
            continue
        for match in re.finditer(re.escape(term), text):
            matches.append((match.start(), -len(term), term))
    return [term for _, _, term in sorted(matches)]


def sequence_changes(
    category: str,
    original: list[Any],
    revised: list[Any],
    authorizations: Counter[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    matcher = SequenceMatcher(a=original, b=revised, autojunk=False)
    remaining = authorizations.copy()
    changes: list[dict[str, Any]] = []
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "equal":
            continue
        before = [str(value) for value in original[i1:i2]]
        after = [str(value) for value in revised[j1:j2]]
        width = max(len(before), len(after))
        for offset in range(width):
            old = before[offset] if offset < len(before) else ""
            new = after[offset] if offset < len(after) else ""
            key = (category, old, new)
            authorized = remaining[key] > 0
            if authorized:
                remaining[key] -= 1
            changes.append(
                {
                    "operation": operation,
                    "original": old,
                    "revised": new,
                    "authorized": authorized,
                }
            )
    return changes


def protected_order(
    text: str,
    patterns: dict[str, re.Pattern[str]],
    terms: list[str],
) -> list[str]:
    category_order = {name: index for index, name in enumerate(patterns)}
    category_order["protected_terms"] = len(category_order)
    matches: list[tuple[int, int, str]] = []
    for category, pattern in patterns.items():
        for match in pattern.finditer(text):
            matches.append((match.start(), category_order[category], category))
    for term in terms:
        for match in re.finditer(re.escape(term), text):
            matches.append((match.start(), category_order["protected_terms"], "protected_terms"))
    return [category for _, _, category in sorted(matches)]


def parse_exact_replacements(values: list[str]) -> list[tuple[str, str]]:
    replacements: list[tuple[str, str]] = []
    for value in values:
        if "=>" not in value:
            raise ValueError(f"Invalid exact replacement {value!r}; expected ORIGINAL=>REVISED")
        original, revised = value.split("=>", 1)
        if not original:
            raise ValueError("Exact replacement ORIGINAL must not be empty")
        replacements.append((original, revised))
    return replacements


def apply_exact_replacements(
    original: str, replacements: list[tuple[str, str]]
) -> tuple[str, list[str]]:
    expected = original
    errors: list[str] = []
    for before, after in replacements:
        occurrences = expected.count(before)
        if occurrences != 1:
            errors.append(
                f"Replacement source {before!r} occurs {occurrences} times; include more context so it is unique"
            )
            continue
        expected = expected.replace(before, after, 1)
    return expected, errors


def split_markdown_row(line: str) -> int:
    body = line.strip().strip("|")
    return len(re.split(r"(?<!\\)\|", body))


def is_markdown_separator(line: str) -> bool:
    if "|" not in line:
        return False
    cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
    return bool(cells) and all(MARKDOWN_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def markdown_tables(text: str) -> list[list[str]]:
    lines = text.splitlines()
    tables: list[list[str]] = []
    for index, line in enumerate(lines):
        if not is_markdown_separator(line):
            continue
        start = index
        while start > 0 and "|" in lines[start - 1] and lines[start - 1].strip():
            start -= 1
        end = index
        while end + 1 < len(lines) and "|" in lines[end + 1] and lines[end + 1].strip():
            end += 1
        tables.append(lines[start : end + 1])
    return tables


def markdown_table_shapes(text: str) -> list[dict[str, Any]]:
    return [
        {"rows": len(rows), "columns": [split_markdown_row(row) for row in rows]}
        for rows in markdown_tables(text)
    ]


def markdown_table_contents(text: str) -> list[list[list[str]]]:
    return [
        [
            [cell.strip() for cell in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
            for row in rows
        ]
        for rows in markdown_tables(text)
    ]


def heading_signature(text: str) -> list[str]:
    return [f"{len(match.group(1))}:{match.group(2)}" for match in HEADING_RE.finditer(text)]


def detect_format(text: str, requested: str) -> str:
    if requested != "auto":
        return requested
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return "json"
    if stripped.startswith("[") and stripped.rstrip().endswith("]"):
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return "json"
        else:
            return "json"
    if markdown_table_shapes(text) or HEADING_RE.search(text):
        return "markdown"
    return "text"


def parse_json_strict(text: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKeyError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicate_keys)


def json_signature(value: Any, path: str = "$") -> list[tuple[Any, ...]]:
    signature: list[tuple[Any, ...]] = []
    if isinstance(value, dict):
        keys = tuple(value.keys())
        signature.append((path, "object", keys))
        for key, item in value.items():
            signature.extend(json_signature(item, f"{path}.{key}"))
    elif isinstance(value, list):
        signature.append((path, "array", len(value)))
        for index, item in enumerate(value):
            signature.extend(json_signature(item, f"{path}[{index}]"))
    elif value is None:
        signature.append((path, "null"))
    elif isinstance(value, bool):
        signature.append((path, "boolean"))
    elif isinstance(value, (int, float)):
        signature.append((path, "number"))
    elif isinstance(value, str):
        signature.append((path, "string"))
    return signature


def json_value_signature(value: Any, path: str = "$") -> list[tuple[str, str]]:
    signature: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            signature.extend(json_value_signature(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            signature.extend(json_value_signature(item, f"{path}[{index}]"))
    else:
        signature.append((path, json.dumps(value, ensure_ascii=False, sort_keys=True)))
    return signature


def load_terms(values: list[str], terms_file: Path | None) -> list[str]:
    terms = list(values)
    if terms_file:
        terms.extend(
            line.strip()
            for line in read_text(terms_file).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return list(dict.fromkeys(terms))


def add_check(
    checks: list[dict[str, Any]],
    category: str,
    changed: bool,
    details: Any,
    required: set[str],
    fully_authorized: bool = False,
) -> None:
    if not changed:
        status = "pass"
    elif fully_authorized:
        status = "allowed"
    elif category in required:
        status = "fail"
    else:
        status = "warn"
    checks.append({"category": category, "status": status, "details": details})


def add_sequence_check(
    checks: list[dict[str, Any]],
    category: str,
    original: list[Any],
    revised: list[Any],
    required: set[str],
    authorizations: Counter[tuple[str, str, str]],
    scope_authorized: bool = False,
) -> None:
    changes = sequence_changes(category, original, revised, authorizations)
    add_check(
        checks,
        category,
        bool(changes),
        {"changes": changes},
        required,
        bool(changes)
        and (scope_authorized or all(change["authorized"] for change in changes)),
    )


def derive_authorizations(
    replacements: list[tuple[str, str]],
    patterns: dict[str, re.Pattern[str]],
    protected_terms: list[str],
) -> Counter[tuple[str, str, str]]:
    authorizations: Counter[tuple[str, str, str]] = Counter()
    for before, after in replacements:
        sequences: dict[str, tuple[list[Any], list[Any]]] = {
            category: (sequence_matches(pattern, before), sequence_matches(pattern, after))
            for category, pattern in patterns.items()
        }
        sequences["protected_terms"] = (
            sequence_terms(before, protected_terms),
            sequence_terms(after, protected_terms),
        )
        sequences["headings"] = (heading_signature(before), heading_signature(after))
        sequences["protected_order"] = (
            protected_order(before, patterns, protected_terms),
            protected_order(after, patterns, protected_terms),
        )
        for category, (original_values, revised_values) in sequences.items():
            for change in sequence_changes(category, original_values, revised_values, Counter()):
                authorizations[(category, change["original"], change["revised"])] += 1
    return authorizations


def compare(
    original: str,
    revised: str,
    mode: str,
    requested_format: str,
    protected_terms: list[str],
    exact_replacements: list[tuple[str, str]],
) -> dict[str, Any]:
    selected_format = detect_format(original, requested_format)
    required = STRICT_REQUIRED if mode in {"strict", "exact"} else BASE_REQUIRED
    checks: list[dict[str, Any]] = []

    patterns = {
        "numbers": NUMBER_RE,
        "units": UNIT_RE,
        "urls": URL_RE,
        "placeholders": PLACEHOLDER_RE,
        "citations": CITATION_RE,
        "semantic_markers": SEMANTIC_MARKER_RE,
    }
    if selected_format != "json":
        patterns["quotes"] = QUOTE_RE

    authorizations = derive_authorizations(exact_replacements, patterns, protected_terms)

    scope_matches = False
    if exact_replacements:
        expected, scope_errors = apply_exact_replacements(original, exact_replacements)
        scope_matches = not scope_errors and expected == revised
        add_check(
            checks,
            "authorized_scope",
            not scope_matches,
            {"exact_match": scope_matches, "errors": scope_errors},
            required,
        )
    else:
        add_check(
            checks,
            "authorized_scope",
            mode == "exact",
            {
                "skipped": "No exact replacement scope supplied",
                "required": mode == "exact",
            },
            required,
        )

    for category, pattern in patterns.items():
        add_sequence_check(
            checks,
            category,
            sequence_matches(pattern, original),
            sequence_matches(pattern, revised),
            required,
            authorizations,
            scope_matches,
        )

    if selected_format == "json":
        add_check(checks, "quotes", False, {"skipped": "JSON string delimiters"}, required)

    add_sequence_check(
        checks,
        "protected_terms",
        sequence_terms(original, protected_terms),
        sequence_terms(revised, protected_terms),
        required,
        authorizations,
        scope_matches,
    )
    add_sequence_check(
        checks,
        "protected_order",
        protected_order(original, patterns, protected_terms),
        protected_order(revised, patterns, protected_terms),
        required,
        authorizations,
        scope_matches,
    )

    before_tables = markdown_table_shapes(original)
    after_tables = markdown_table_shapes(revised)
    before_table_contents = markdown_table_contents(original)
    after_table_contents = markdown_table_contents(revised)
    tables_changed = before_tables != after_tables or before_table_contents != after_table_contents
    add_check(
        checks,
        "tables",
        tables_changed,
        {
            "original_shape": before_tables,
            "revised_shape": after_tables,
            "content_changed": before_table_contents != after_table_contents,
        },
        required,
        scope_matches and before_tables == after_tables,
    )

    add_sequence_check(
        checks,
        "headings",
        heading_signature(original),
        heading_signature(revised),
        required,
        authorizations,
        scope_matches,
    )

    if selected_format == "json":
        original_json: Any | None = None
        revised_json: Any | None = None
        validity_errors: dict[str, str] = {}
        try:
            original_json = parse_json_strict(original)
        except (json.JSONDecodeError, DuplicateJsonKeyError) as error:
            validity_errors["original"] = str(error)
        try:
            revised_json = parse_json_strict(revised)
        except (json.JSONDecodeError, DuplicateJsonKeyError) as error:
            validity_errors["revised"] = str(error)
        add_check(checks, "json_validity", bool(validity_errors), validity_errors, required)
        if original_json is not None and revised_json is not None:
            original_shape = json_signature(original_json)
            revised_shape = json_signature(revised_json)
            add_check(
                checks,
                "json_shape",
                original_shape != revised_shape,
                {"original": original_shape, "revised": revised_shape},
                required,
            )
            original_values = json_value_signature(original_json)
            revised_values = json_value_signature(revised_json)
            add_check(
                checks,
                "json_values",
                original_values != revised_values,
                {"original": original_values, "revised": revised_values},
                required,
                scope_matches,
            )
        else:
            add_check(
                checks,
                "json_shape",
                True,
                {"error": "JSON shape unavailable because parsing failed"},
                required,
            )
            add_check(
                checks,
                "json_values",
                True,
                {"error": "JSON values unavailable because parsing failed"},
                required,
            )
    else:
        add_check(checks, "json_validity", False, {"skipped": selected_format}, required)
        add_check(checks, "json_shape", False, {"skipped": selected_format}, required)
        add_check(checks, "json_values", False, {"skipped": selected_format}, required)

    failures = [check["category"] for check in checks if check["status"] == "fail"]
    warnings = [check["category"] for check in checks if check["status"] == "warn"]
    return {
        "ok": not failures,
        "mode": mode,
        "format": selected_format,
        "exact_replacements": len(exact_replacements),
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare protected invariants between UTF-8 original and revised text files."
    )
    parser.add_argument("original", type=Path)
    parser.add_argument("revised", type=Path)
    parser.add_argument("--mode", choices=("standard", "strict", "exact"), default="standard")
    parser.add_argument("--format", choices=("auto", "text", "markdown", "json"), default="auto")
    parser.add_argument("--protect-term", action="append", default=[])
    parser.add_argument("--terms-file", type=Path)
    parser.add_argument(
        "--exact-replacement",
        action="append",
        default=[],
        metavar="ORIGINAL=>REVISED",
        help=(
            "Authorize one unique replacement and require every other character to remain unchanged. "
            "Repeat for multiple replacements."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        original = read_text(args.original)
        revised = read_text(args.revised)
        terms = load_terms(args.protect_term, args.terms_file)
        replacements = parse_exact_replacements(args.exact_replacement)
        report = compare(
            original,
            revised,
            args.mode,
            args.format,
            terms,
            replacements,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
