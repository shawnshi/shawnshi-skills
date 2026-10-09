"""Validate skill frontmatter or optional agents/openai.yaml metadata."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

import yaml
from yaml.constructor import ConstructorError


ALLOWED_FRONTMATTER_KEYS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools", "disable-model-invocation"}
)
ALLOWED_TOP_LEVEL_KEYS = frozenset({"interface", "dependencies", "policy"})
ALLOWED_INTERFACE_KEYS = frozenset(
    {"display_name", "short_description", "icon_small", "icon_large", "brand_color", "default_prompt"}
)
ALLOWED_POLICY_KEYS = frozenset({"allow_implicit_invocation"})
ALLOWED_DEPENDENCY_KEYS = frozenset({"tools"})
ALLOWED_TOOL_KEYS = frozenset({"type", "value", "description", "transport", "url"})


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys and uses Pi-compatible booleans."""


# PyYAML's YAML 1.1 on/yes coercion would claim manual invocation while Pi's
# YAML 1.2 loader treats those words as strings.
UniqueKeyLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
UniqueKeyLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found unhashable key", key_node.start_mark,
            ) from exc
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _issue(skill: str, code: str, detail: str) -> dict[str, str]:
    return {"skill": skill, "code": code, "detail": detail}


def load_frontmatter(skill_dir: Path) -> dict:
    lines = (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not terminated") from exc
    document = yaml.load("\n".join(lines[1:end]), Loader=UniqueKeyLoader)
    if not isinstance(document, dict) or any(not isinstance(key, str) for key in document):
        raise ValueError("frontmatter must be a mapping with string keys")
    return document


def validate_frontmatter(skill_dir: Path) -> tuple[dict, list[dict[str, str]]]:
    skill = skill_dir.name
    record = {
        "skill": skill, "valid": False, "keys": [], "unexpected_keys": [],
        "name": "", "description_has_trigger_context": None,
    }
    try:
        document = load_frontmatter(skill_dir)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return record, [_issue(skill, "frontmatter_parse_error", str(exc))]
    issues = []
    record["keys"] = list(document)
    record["unexpected_keys"] = sorted(set(document) - ALLOWED_FRONTMATTER_KEYS)
    if record["unexpected_keys"]:
        issues.append(_issue(skill, "frontmatter_unknown_field", ", ".join(record["unexpected_keys"])))
    name = document.get("name")
    if isinstance(name, str):
        record["name"] = name
    if not isinstance(name, str) or len(name) > 64 or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None or name != skill:
        issues.append(_issue(skill, "frontmatter_name_invalid", "name must be a portable name matching the directory"))
    description = document.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        issues.append(_issue(skill, "frontmatter_description_invalid", "description must contain 1-1024 characters"))
    for key in ("license", "allowed-tools", "compatibility"):
        if key in document and (not isinstance(document[key], str) or not document[key].strip()):
            issues.append(_issue(skill, "frontmatter_field_invalid", f"{key} must be non-empty text"))
    if isinstance(document.get("compatibility"), str) and len(document["compatibility"]) > 500:
        issues.append(_issue(skill, "frontmatter_field_invalid", "compatibility exceeds 500 characters"))
    if "disable-model-invocation" in document and not isinstance(document["disable-model-invocation"], bool):
        issues.append(_issue(skill, "frontmatter_field_invalid", "disable-model-invocation must be boolean"))
    if "metadata" in document:
        metadata = document["metadata"]
        if not isinstance(metadata, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
            issues.append(_issue(skill, "frontmatter_field_invalid", "metadata must map strings to strings"))
    record["valid"] = not issues
    return record, issues


def frontmatter_disable_model_invocation(skill_dir: Path) -> bool | None:
    document = load_frontmatter(skill_dir)
    value = document.get("disable-model-invocation")
    if value is not None and not isinstance(value, bool):
        raise ValueError("disable-model-invocation must be boolean")
    return value


def _safe_relative_asset(skill_dir: Path, value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.replace("\\", "/")
    if PureWindowsPath(normalized).is_absolute() or normalized.startswith("/") or ".." in Path(normalized).parts:
        return False
    candidate = (skill_dir / Path(*normalized.split("/"))).resolve()
    try:
        candidate.relative_to(skill_dir.resolve())
    except ValueError:
        return False
    return candidate.is_file()


def validate_skill(skill_dir: Path) -> list[dict[str, str]]:
    issues, _ = validate_skill_detailed(skill_dir)
    return issues


def validate_skill_detailed(skill_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (blocking issues, non-blocking warnings) for one skill.

    A missing manifest field is a warning, not a failure: deciding the missing
    side changes which host may auto-trigger the skill, and that routing choice
    belongs to the skill owner rather than to this validator.
    """
    path = skill_dir / "agents" / "openai.yaml"
    if not path.is_file():
        return [], []
    skill = skill_dir.name
    try:
        document = yaml.load(
            path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return [_issue(skill, "openai_yaml_parse_error", str(exc))], []
    if not isinstance(document, dict):
        return [_issue(skill, "openai_yaml_root_invalid", "root must be a mapping")], []
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    extra_top = sorted(set(document) - ALLOWED_TOP_LEVEL_KEYS)
    if extra_top:
        issues.append(_issue(skill, "openai_yaml_unknown_top_level", ", ".join(extra_top)))

    interface = document.get("interface")
    if not isinstance(interface, dict):
        return issues + [_issue(skill, "openai_interface_invalid", "interface must be a mapping")], warnings
    extra_interface = sorted(set(interface) - ALLOWED_INTERFACE_KEYS)
    if extra_interface:
        issues.append(_issue(skill, "openai_interface_unknown_field", ", ".join(extra_interface)))
    display_name = interface.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        issues.append(_issue(skill, "openai_display_name_invalid", "display_name is required"))
    short_description = interface.get("short_description")
    if not isinstance(short_description, str) or not 25 <= len(short_description) <= 64:
        issues.append(_issue(skill, "openai_short_description_invalid", "short_description must be 25-64 characters"))
    default_prompt = interface.get("default_prompt")
    token = f"${skill}"
    token_pattern = rf"(?<![A-Za-z0-9_-])\${re.escape(skill)}(?![A-Za-z0-9_-])"
    if not isinstance(default_prompt, str) or not default_prompt.strip() or re.search(token_pattern, default_prompt) is None:
        issues.append(_issue(skill, "openai_default_prompt_invalid", f"default_prompt must contain {token}"))
    for field in ("icon_small", "icon_large"):
        if field in interface and not _safe_relative_asset(skill_dir, interface[field]):
            issues.append(_issue(skill, "openai_icon_invalid", f"{field} must resolve inside the skill"))
    if "brand_color" in interface:
        color = interface["brand_color"]
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            issues.append(_issue(skill, "openai_brand_color_invalid", "brand_color must be #RRGGBB"))

    policy = document.get("policy")
    if policy is not None:
        if not isinstance(policy, dict):
            issues.append(_issue(skill, "openai_policy_invalid", "policy must be a mapping"))
        else:
            extra_policy = sorted(set(policy) - ALLOWED_POLICY_KEYS)
            if extra_policy:
                issues.append(_issue(skill, "openai_policy_unknown_field", ", ".join(extra_policy)))
            if "allow_implicit_invocation" in policy and not isinstance(policy["allow_implicit_invocation"], bool):
                issues.append(_issue(skill, "openai_policy_invalid", "allow_implicit_invocation must be boolean"))

    try:
        declared_disable = frontmatter_disable_model_invocation(skill_dir)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        issues.append(_issue(skill, "frontmatter_parse_error", str(exc)))
        declared_disable = None
    declared_implicit = (
        policy.get("allow_implicit_invocation")
        if isinstance(policy, dict) and isinstance(policy.get("allow_implicit_invocation"), bool)
        else None
    )
    if declared_disable is not None and declared_implicit is not None:
        if declared_disable is declared_implicit:
            issues.append(
                _issue(
                    skill,
                    "openai_policy_contradiction",
                    "SKILL.md disable-model-invocation and agents/openai.yaml "
                    "allow_implicit_invocation declare the same intent; they must be inverse",
                )
            )
    elif declared_disable is True:
        warnings.append(
            _issue(
                skill,
                "openai_policy_unpaired",
                "SKILL.md disables model invocation but agents/openai.yaml does not "
                "declare policy.allow_implicit_invocation",
            )
        )
    elif declared_implicit is False:
        warnings.append(
            _issue(
                skill,
                "openai_policy_unpaired",
                "agents/openai.yaml disables implicit invocation but SKILL.md does not "
                "declare disable-model-invocation; Pi can still advertise it for automatic selection",
            )
        )

    dependencies = document.get("dependencies")
    if dependencies is not None:
        if not isinstance(dependencies, dict):
            issues.append(_issue(skill, "openai_dependencies_invalid", "dependencies must be a mapping"))
        else:
            extra_dependencies = sorted(set(dependencies) - ALLOWED_DEPENDENCY_KEYS)
            if extra_dependencies:
                issues.append(_issue(skill, "openai_dependencies_unknown_field", ", ".join(extra_dependencies)))
            tools = dependencies.get("tools", [])
            if not isinstance(tools, list):
                issues.append(_issue(skill, "openai_dependencies_invalid", "dependencies.tools must be a list"))
            else:
                for index, tool in enumerate(tools):
                    if not isinstance(tool, dict):
                        issues.append(_issue(skill, "openai_dependency_tool_invalid", f"tools[{index}] must be a mapping"))
                        continue
                    extra_tool = sorted(set(tool) - ALLOWED_TOOL_KEYS)
                    if extra_tool:
                        issues.append(_issue(skill, "openai_dependency_tool_unknown_field", f"tools[{index}]: {', '.join(extra_tool)}"))
                    if tool.get("type") != "mcp" or not isinstance(tool.get("value"), str) or not tool["value"].strip():
                        issues.append(_issue(skill, "openai_dependency_tool_invalid", f"tools[{index}] must declare an mcp value"))
                    for field in ("description", "transport", "url"):
                        if field in tool and (not isinstance(tool[field], str) or not tool[field].strip()):
                            issues.append(_issue(skill, "openai_dependency_tool_invalid", f"tools[{index}].{field} must be non-empty text"))
    return issues, warnings


def _skill_dirs(root: Path, include: Iterable[str], exclude: Iterable[str]) -> tuple[list[Path], list[str]]:
    all_skills = {
        path.name: path for path in root.iterdir()
        if path.is_dir() and path.name not in {".system", "scripts", "shared", "reports", "examples"}
        and (path / "SKILL.md").is_file()
    }
    included = {name for name in include if name}
    excluded = {name for name in exclude if name}
    problems = [f"unknown scoped skill: {name}" for name in sorted((included | excluded) - set(all_skills))]
    problems.extend(
        f"skill cannot be both included and excluded: {name}"
        for name in sorted(included & excluded)
    )
    names = sorted(included or set(all_skills))
    selected = [all_skills[name] for name in names if name not in excluded and name in all_skills]
    if (included or excluded) and not selected:
        problems.append("skill selection is empty")
    return selected, problems


def validate_root(root: Path, include: Iterable[str] = (), exclude: Iterable[str] = ()) -> dict[str, object]:
    skill_dirs, scope_problems = _skill_dirs(root.resolve(), include, exclude)
    issues = [_issue("", "scope_error", problem) for problem in scope_problems]
    warnings: list[dict[str, str]] = []
    checked = 0
    for skill_dir in skill_dirs:
        if (skill_dir / "agents" / "openai.yaml").is_file():
            checked += 1
        skill_issues, skill_warnings = validate_skill_detailed(skill_dir)
        issues.extend(skill_issues)
        warnings.extend(skill_warnings)
    return {
        "checked": checked,
        "failures": len(issues),
        "issues": issues,
        "warnings": warnings,
    }


def validate_frontmatter_root(root: Path, include: Iterable[str] = (), exclude: Iterable[str] = ()) -> dict[str, object]:
    skill_dirs, scope_problems = _skill_dirs(root.resolve(), include, exclude)
    issues = [_issue("", "scope_error", problem) for problem in scope_problems]
    records = []
    for skill_dir in skill_dirs:
        record, skill_issues = validate_frontmatter(skill_dir)
        records.append(record)
        issues.extend(skill_issues)
    return {"checked": len(skill_dirs), "failures": len(issues), "issues": issues, "warnings": [], "records": records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--include-skill", action="append", default=[])
    parser.add_argument("--exclude-skill", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--frontmatter-only", action="store_true", help="Validate SKILL.md without requiring OpenAI metadata")
    args = parser.parse_args()
    validate = validate_frontmatter_root if args.frontmatter_only else validate_root
    result = validate(args.root, args.include_skill, args.exclude_skill)
    print(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if args.json else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
