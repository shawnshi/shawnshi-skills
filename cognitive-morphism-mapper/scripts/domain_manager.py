"""Manage a SHA-256 allowlist of provenance-bearing domain references."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "references"
ALLOWLIST = REFERENCES / "verified_domains.json"
DRAFTS = REFERENCES / "drafts"
VERIFIED = REFERENCES / "verified"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
UNRESOLVED_VALUES = {"TBD", "<TBD>", "[TBD]", "PENDING", "LLM_PENDING"}
REQUIRED_HEADINGS = (
    "## Core Objects",
    "## Core Morphisms",
    "## Theorems / Patterns",
)
REQUIRED_MECHANISM_FIELDS = (
    "Statement",
    "Preconditions",
    "Applicable structure",
    "Mapping hint",
    "Counterexample / limit",
    "Source",
)
DRAFT_INSTRUCTIONS = (
    "- Add evidence-backed objects and definitions.",
    "- Add directional relationships, conditions and composition rules.",
    "### Add a mechanism",
    "- Add discovery tags; tag matches do not auto-trigger use.",
)

TEMPLATE = """# Domain: {display_name}
# Source: {source}
# Structural_Primitives: {primitives}

## Evidence status

- Document what is verified and what remains a research lead.

## Core Objects

- Add evidence-backed objects and definitions.

## Core Morphisms

- Add directional relationships, conditions and composition rules.

## Theorems / Patterns

### Add a mechanism

- **Statement**:
- **Preconditions**:
- **Applicable structure**:
- **Mapping hint**:
- **Counterexample / limit**:
- **Source**: {source}

## Tags

- Add discovery tags; tag matches do not auto-trigger use.
"""


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside_verified(path):
    try:
        path.resolve().relative_to(VERIFIED.resolve())
        return True
    except ValueError:
        return False


def _is_unresolved(value):
    normalized = value.strip()
    return (
        not normalized
        or normalized.upper() in UNRESOLVED_VALUES
        or normalized.upper().startswith("PENDING_")
    )


def _load_allowlist():
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("domains"), list):
        raise ValueError("invalid verified_domains.json")
    return data


def _header_value(content, label):
    match = re.search(
        rf"(?m)^# {re.escape(label)}:[ \t]*(.*?)[ \t]*$",
        content,
    )
    return match.group(1).strip() if match else ""


def _validate_domain_content(content, expected_source=None):
    errors = []
    source = _header_value(content, "Source")
    primitives = _header_value(content, "Structural_Primitives")
    if _is_unresolved(source):
        errors.append("domain Source header is missing or unresolved")
    if _is_unresolved(primitives):
        errors.append("domain Structural_Primitives header is missing or unresolved")
    if expected_source is not None and source != expected_source:
        errors.append("domain Source header does not match allowlist source")
    for heading in REQUIRED_HEADINGS:
        if heading not in content:
            errors.append(f"domain heading is missing: {heading}")
    for instruction in DRAFT_INSTRUCTIONS:
        if instruction in content:
            errors.append(f"domain draft instruction is unresolved: {instruction}")
    for field in REQUIRED_MECHANISM_FIELDS:
        matches = re.findall(
            rf"(?m)^-[ \t]+\*\*{re.escape(field)}\*\*:[ \t]*(.*?)[ \t]*$",
            content,
        )
        if not matches:
            errors.append(f"domain mechanism field is missing: {field}")
        elif any(_is_unresolved(value) for value in matches):
            errors.append(f"domain mechanism field is unresolved: {field}")
    return source, errors


def list_domains():
    try:
        data = _load_allowlist()
    except ValueError as exc:
        return {
            "status": "error",
            "category": "allowlist_schema",
            "message": str(exc),
        }

    active, errors = [], []
    seen_names, seen_paths = set(), set()
    for index, item in enumerate(data["domains"]):
        if not isinstance(item, dict):
            errors.append(f"domains[{index}] must be an object")
            continue
        missing = [key for key in ("name", "path", "sha256", "source") if not item.get(key)]
        if missing:
            errors.append(f"domains[{index}] missing fields: {', '.join(missing)}")
            continue
        name = item["name"]
        path_text = str(item["path"]).replace("\\", "/")
        source = item["source"]
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            errors.append(f"domains[{index}] name is invalid")
            expected_path = None
        else:
            if name in seen_names:
                errors.append(f"domains[{index}] duplicate name: {name}")
            seen_names.add(name)
            expected_path = f"verified/{name}.md"
        if path_text in seen_paths:
            errors.append(f"domains[{index}] duplicate path: {path_text}")
        seen_paths.add(path_text)
        if expected_path is not None and path_text != expected_path:
            errors.append(
                f"domains[{index}] path must be {expected_path}"
            )
        if not isinstance(source, str) or _is_unresolved(source):
            errors.append(f"domains[{index}] source is missing or unresolved")

        path = REFERENCES / path_text
        if not _inside_verified(path):
            errors.append(
                f"domains[{index}] path must be inside references/verified"
            )
        elif not path.is_file():
            errors.append(f"domains[{index}] file not found: {path}")
        else:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"domains[{index}] cannot read {path}: {exc}")
                continue
            _, content_errors = _validate_domain_content(
                content,
                expected_source=source if isinstance(source, str) else None,
            )
            errors.extend(
                f"domains[{index}] {message}" for message in content_errors
            )
            if _sha256(path) != item["sha256"]:
                errors.append(f"domains[{index}] sha256 mismatch: {path}")
                continue
            if content_errors:
                continue
            active.append(
                {
                    "name": name,
                    "path": str(path),
                    "source": source,
                    "sha256": item["sha256"],
                    "status": "verified",
                }
            )
    if errors:
        return {"status": "error", "category": "allowlist_validation", "errors": errors}

    return {"status": "success", "count": len(active), "domains": active}


def add_domain(name, source, primitives, apply):
    if not SAFE_NAME.fullmatch(name):
        return {"status": "error", "category": "invalid_name", "message": "name must match [a-z0-9][a-z0-9_-]*"}
    if not source.strip() or not primitives.strip():
        return {"status": "error", "category": "missing_field", "message": "source and primitives are required"}
    path = DRAFTS / f"{name}.md"
    content = TEMPLATE.format(
        display_name=name.replace("_", " ").title(),
        source=source.strip(),
        primitives=primitives.strip(),
    )
    if not apply:
        return {
            "status": "preview",
            "path": str(path),
            "content": content,
            "note": "Drafts are inactive until separately reviewed and added to verified_domains.json with a SHA-256.",
        }
    if path.exists():
        return {"status": "error", "category": "exists", "message": f"{path} already exists"}
    DRAFTS.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "status": "created_draft",
        "path": str(path),
        "sha256": _sha256(path),
        "active": False,
    }


def promote_domain(name, apply):
    if not SAFE_NAME.fullmatch(name):
        return {
            "status": "error",
            "category": "invalid_name",
            "message": "name must match [a-z0-9][a-z0-9_-]*",
        }
    draft = DRAFTS / f"{name}.md"
    target = VERIFIED / f"{name}.md"
    if not draft.is_file():
        return {
            "status": "error",
            "category": "missing_draft",
            "message": f"draft not found: {draft}",
        }
    if target.exists():
        return {
            "status": "error",
            "category": "exists",
            "message": f"verified domain already exists: {target}",
        }

    content = draft.read_text(encoding="utf-8")
    source, content_errors = _validate_domain_content(content)
    if content_errors:
        return {
            "status": "error",
            "category": "domain_schema",
            "errors": content_errors,
        }
    data = _load_allowlist()
    path_text = f"verified/{name}.md"
    for index, item in enumerate(data["domains"]):
        if not isinstance(item, dict):
            return {
                "status": "error",
                "category": "allowlist_schema",
                "message": f"domains[{index}] must be an object",
            }
        if item.get("name") == name or str(item.get("path", "")).replace("\\", "/") == path_text:
            return {
                "status": "error",
                "category": "duplicate",
                "message": f"allowlist already contains {name} or {path_text}",
            }

    digest = _sha256(draft)
    entry = {
        "name": name,
        "path": path_text,
        "sha256": digest,
        "source": source,
    }
    if not apply:
        return {
            "status": "preview",
            "draft": str(draft),
            "target": str(target),
            "allowlist_entry": entry,
            "note": "No files changed. Re-run with --apply only after review and authorization.",
        }

    VERIFIED.mkdir(parents=True, exist_ok=True)
    allowlist_temp = ALLOWLIST.with_name(f".{ALLOWLIST.name}.tmp")
    updated = {**data, "domains": [*data["domains"], entry]}
    allowlist_temp.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    moved = False
    try:
        draft.replace(target)
        moved = True
        allowlist_temp.replace(ALLOWLIST)
    except OSError:
        if moved and target.exists() and not draft.exists():
            target.replace(draft)
        raise
    finally:
        allowlist_temp.unlink(missing_ok=True)
    return {
        "status": "promoted",
        "path": str(target),
        "source": source,
        "sha256": digest,
        "active": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage morphism-mapper domain references")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    add = commands.add_parser("add")
    add.add_argument("name")
    add.add_argument("--source", required=True)
    add.add_argument("--primitives", required=True)
    add.add_argument("--apply", action="store_true", help="write an inactive draft")
    promote = commands.add_parser("promote")
    promote.add_argument("name")
    promote.add_argument(
        "--apply",
        action="store_true",
        help="move a reviewed draft into verified and update the allowlist",
    )
    args = parser.parse_args()

    try:
        if args.command == "list":
            result = list_domains()
        elif args.command == "add":
            result = add_domain(args.name, args.source, args.primitives, args.apply)
        else:
            result = promote_domain(args.name, args.apply)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result = {"status": "error", "category": "io", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
