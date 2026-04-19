# -*- coding: utf-8 -*-
"""
plan_validator.py - Validate SlideBlocks JSON plans before COM execution.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _ENGINE_DIR.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

try:
    from slide_vault.config import get_materials_dir, get_output_dir
except Exception:
    get_materials_dir = None
    get_output_dir = None

try:
    from .template_manifest import (
        expand_known_placeholders,
        load_template_manifest,
        normalize_template_manifest,
        resolve_manifest_template_path,
    )
except ImportError:
    from template_manifest import (
        expand_known_placeholders,
        load_template_manifest,
        normalize_template_manifest,
        resolve_manifest_template_path,
    )

_SLIDE_ENTRY_RE = re.compile(r"^ppt/slides/slide\d+\.xml$")


def _safe_console_text(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="backslashreplace").decode(encoding)


def _issue(severity: str, code: str, message: str, step_index: int | None = None) -> dict:
    issue = {
        "code": code,
        "message": message,
    }
    if step_index is not None:
        issue["step_index"] = step_index
    issue["severity"] = severity
    return issue


def _append(result: dict, severity: str, code: str, message: str, step_index: int | None = None) -> None:
    bucket = "errors" if severity == "error" else "warnings"
    result[bucket].append(_issue(severity, code, message, step_index=step_index))


def _load_json_file(path: Path) -> tuple[dict | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as exc:
        return None, str(exc)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _count_slides(ppt_path: Path) -> tuple[int | None, str | None]:
    if ppt_path.suffix.lower() != ".pptx":
        return None, "Only .pptx files support zip-based page counting."

    try:
        with zipfile.ZipFile(ppt_path) as zf:
            count = sum(1 for name in zf.namelist() if _SLIDE_ENTRY_RE.match(name))
        return count, None
    except Exception as exc:
        return None, str(exc)


def validate_plan_data(
    data: dict,
    *,
    plan_path: Path | None = None,
    manifest_path: Path | None = None,
    strict: bool = False,
) -> dict:
    normalized_data = json.loads(json.dumps(data, ensure_ascii=False))
    result = {
        "valid": False,
        "errors": [],
        "warnings": [],
        "data": normalized_data,
        "manifest_path": str(manifest_path.resolve()) if manifest_path else None,
    }

    if not isinstance(data, dict):
        _append(result, "error", "PLAN_NOT_OBJECT", "Plan JSON must be a top-level object.")
        return result

    manifest, manifest_error = load_template_manifest(manifest_path)
    if manifest_error:
        error_code = "MANIFEST_NOT_FOUND" if "not found" in manifest_error.lower() else "MANIFEST_INVALID"
        _append(result, "error", error_code, manifest_error)

    manifest_config = normalize_template_manifest(manifest)
    roles = manifest_config["page_roles"]
    require_transition_font_40 = manifest_config["validation_rules"]["require_transition_font_size_40"]

    template_path = normalized_data.get("template_path")
    output_path = normalized_data.get("output_path")
    plan = normalized_data.get("plan")

    if not template_path:
        template_path = resolve_manifest_template_path(manifest)
        normalized_data["template_path"] = template_path

    if isinstance(template_path, str):
        template_path = expand_known_placeholders(template_path)
        normalized_data["template_path"] = template_path
    if isinstance(output_path, str):
        output_path = expand_known_placeholders(output_path)
        normalized_data["output_path"] = output_path
    if isinstance(plan, list):
        for step in plan:
            if isinstance(step, dict) and isinstance(step.get("src"), str):
                step["src"] = expand_known_placeholders(step["src"])

    if not isinstance(template_path, str) or not template_path.strip():
        _append(result, "error", "MISSING_TEMPLATE_PATH", "Plan must contain a non-empty string field 'template_path'.")
    if not isinstance(output_path, str) or not output_path.strip():
        _append(result, "error", "MISSING_OUTPUT_PATH", "Plan must contain a non-empty string field 'output_path'.")
    if not isinstance(plan, list) or not plan:
        _append(result, "error", "MISSING_PLAN", "Plan must contain a non-empty array field 'plan'.")

    if result["errors"]:
        return result

    template_path_obj = Path(template_path).resolve()
    output_path_obj = Path(output_path).resolve()

    if not template_path_obj.exists():
        _append(result, "error", "TEMPLATE_NOT_FOUND", f"Template not found: {template_path_obj}")

    output_parent = output_path_obj.parent
    if not output_parent.exists():
        if not output_parent.parent.exists():
            _append(
                result,
                "error",
                "OUTPUT_PARENT_UNREACHABLE",
                f"Output directory parent does not exist: {output_parent}",
            )
        else:
            _append(
                result,
                "warning",
                "OUTPUT_PARENT_MISSING",
                f"Output directory does not exist yet and will need to be created: {output_parent}",
            )

    if strict and get_materials_dir and get_output_dir:
        try:
            materials_dir = get_materials_dir().resolve()
            output_dir = get_output_dir().resolve()
            if not _is_relative_to(template_path_obj, materials_dir):
                _append(
                    result,
                    "error",
                    "TEMPLATE_OUTSIDE_MATERIALS_DIR",
                    f"Template path is outside materials_dir: {template_path_obj}",
                )
            if not _is_relative_to(output_path_obj, output_dir):
                _append(
                    result,
                    "error",
                    "OUTPUT_OUTSIDE_OUTPUT_DIR",
                    f"Output path is outside output_dir: {output_path_obj}",
                )
        except Exception as exc:
            _append(result, "warning", "STRICT_ROOT_CHECK_SKIPPED", f"Strict root validation skipped: {exc}")

    if plan:
        first_step = plan[0] if isinstance(plan[0], dict) else None
        last_step = plan[-1] if isinstance(plan[-1], dict) else None
        if not first_step or first_step.get("template_page") != roles["cover"]:
            _append(
                result,
                "warning",
                "COVER_NOT_FIRST",
                f"First step should usually be the cover page template ({roles['cover']}).",
                step_index=1,
            )
        if not last_step or last_step.get("template_page") != roles["closing"]:
            _append(
                result,
                "error",
                "CLOSING_NOT_LAST",
                f"Final step must be the closing template page ({roles['closing']}).",
                step_index=len(plan),
            )

    template_slide_count = None
    if template_path_obj.exists():
        template_slide_count, error = _count_slides(template_path_obj)
        if error and template_path_obj.suffix.lower() == ".pptx":
            _append(result, "warning", "TEMPLATE_SLIDE_COUNT_SKIPPED", f"Template slide counting failed: {error}")

    for idx, step in enumerate(plan, start=1):
        if not isinstance(step, dict):
            _append(result, "error", "STEP_NOT_OBJECT", "Each plan step must be a JSON object.", step_index=idx)
            continue

        has_template = "template_page" in step
        has_source = "src" in step or "page" in step

        if has_template and has_source:
            _append(
                result,
                "error",
                "MIXED_STEP",
                "A step cannot mix 'template_page' with source fields like 'src' or 'page'.",
                step_index=idx,
            )
            continue

        if not has_template and not has_source:
            _append(
                result,
                "error",
                "EMPTY_STEP",
                "A step must be either a template step or a source step.",
                step_index=idx,
            )
            continue

        if has_template:
            template_page = step.get("template_page")
            if not isinstance(template_page, int) or template_page <= 0:
                _append(
                    result,
                    "error",
                    "INVALID_TEMPLATE_PAGE",
                    "Template steps must use a positive integer 'template_page'.",
                    step_index=idx,
                )
                continue

            if template_slide_count is not None and template_page > template_slide_count:
                _append(
                    result,
                    "error",
                    "TEMPLATE_PAGE_OUT_OF_RANGE",
                    f"Template page {template_page} exceeds template slide count {template_slide_count}.",
                    step_index=idx,
                )

            if template_page == roles["transition"] and require_transition_font_40:
                font_size = step.get("font_size")
                if font_size != 40:
                    _append(
                        result,
                        "error",
                        "TRANSITION_FONT_SIZE_INVALID",
                        "Transition template pages must set 'font_size' to 40.",
                        step_index=idx,
                    )
            continue

        src = step.get("src")
        page = step.get("page")
        if not isinstance(src, str) or not src.strip():
            _append(result, "error", "MISSING_SRC", "Source steps must contain a non-empty string 'src'.", step_index=idx)
            continue
        if not isinstance(page, int) or page <= 0:
            _append(result, "error", "INVALID_SOURCE_PAGE", "Source steps must contain a positive integer 'page'.", step_index=idx)
            continue

        src_path = Path(src).resolve()
        if not src_path.exists():
            _append(result, "error", "SOURCE_NOT_FOUND", f"Source file not found: {src_path}", step_index=idx)
            continue

        if strict and get_materials_dir:
            try:
                materials_dir = get_materials_dir().resolve()
                if not _is_relative_to(src_path, materials_dir):
                    _append(
                        result,
                        "error",
                        "SOURCE_OUTSIDE_MATERIALS_DIR",
                        f"Source path is outside materials_dir: {src_path}",
                        step_index=idx,
                    )
            except Exception as exc:
                _append(result, "warning", "STRICT_SOURCE_CHECK_SKIPPED", f"Strict source validation skipped: {exc}", step_index=idx)

        src_slide_count, error = _count_slides(src_path)
        if error:
            if src_path.suffix.lower() == ".pptx":
                _append(
                    result,
                    "warning",
                    "SOURCE_SLIDE_COUNT_SKIPPED",
                    f"Source slide counting failed: {error}",
                    step_index=idx,
                )
        elif src_slide_count is not None and page > src_slide_count:
            _append(
                result,
                "error",
                "SOURCE_PAGE_OUT_OF_RANGE",
                f"Requested page {page}, but source deck has {src_slide_count} pages.",
                step_index=idx,
            )

    result["valid"] = not result["errors"]
    return result


def validate_plan_file(plan_file: str | Path, *, manifest_path: str | Path | None = None, strict: bool = False) -> dict:
    plan_path = Path(plan_file).resolve()
    result = {
        "valid": False,
        "errors": [],
        "warnings": [],
        "data": None,
        "manifest_path": str(Path(manifest_path).resolve()) if manifest_path else None,
    }

    if not plan_path.exists():
        _append(result, "error", "PLAN_NOT_FOUND", f"Plan file not found: {plan_path}")
        return result

    data, error = _load_json_file(plan_path)
    if error:
        _append(result, "error", "PLAN_PARSE_FAILED", f"Failed to parse plan JSON: {error}")
        return result

    return validate_plan_data(
        data,
        plan_path=plan_path,
        manifest_path=Path(manifest_path).resolve() if manifest_path else None,
        strict=strict,
    )


def print_validation_report(result: dict) -> None:
    for issue in result.get("errors", []):
        prefix = f"Step {issue['step_index']}: " if "step_index" in issue else ""
        print(_safe_console_text(f"[ERROR] {prefix}{issue['code']}: {issue['message']}"))

    for issue in result.get("warnings", []):
        prefix = f"Step {issue['step_index']}: " if "step_index" in issue else ""
        print(_safe_console_text(f"[WARN ] {prefix}{issue['code']}: {issue['message']}"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SlideBlocks assembly plans before COM execution.")
    parser.add_argument("plan_file", help="Path to the JSON plan file")
    parser.add_argument("--manifest", help="Optional template manifest JSON path")
    parser.add_argument("--strict", action="store_true", help="Enforce config-root ownership checks")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    args = parser.parse_args()

    result = validate_plan_file(args.plan_file, manifest_path=args.manifest, strict=args.strict)

    if args.json:
        print(
            json.dumps(
                {
                    "valid": result["valid"],
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_validation_report(result)
        if result["valid"] and not result["warnings"]:
            print(_safe_console_text("[OK] Plan validation passed with no issues."))
        elif result["valid"]:
            print(_safe_console_text("[OK] Plan validation passed with warnings."))

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
