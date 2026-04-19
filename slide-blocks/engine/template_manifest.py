# -*- coding: utf-8 -*-
"""
template_manifest.py - Normalize template semantics for SlideBlocks.
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from slide_vault.config import get_materials_dir, get_output_dir
except Exception:
    get_materials_dir = None
    get_output_dir = None


DEFAULT_TEMPLATE_CONFIG = {
    "page_roles": {
        "cover": 1,
        "transition": 2,
        "content_with_title": 3,
        "content_without_title": 4,
        "closing": 5,
    },
    "selection_rules": {
        "title_detection": {
            "mode": "top_threshold_pt",
            "threshold_pt": 65,
        },
        "exclude_shapes": [
            {
                "kind": "picture",
                "top_lt_pt": 65,
            }
        ],
    },
    "rendering_rules": {
        "paste_retry_count": 5,
        "paste_retry_delay_ms": 300,
    },
    "validation_rules": {
        "require_transition_font_size_40": True,
    },
    "transition_default_font_size": 40,
}


def _deep_copy(value):
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _coerce_positive_int(value, fallback: int) -> int:
    return value if isinstance(value, int) and value > 0 else fallback


def load_template_manifest(manifest_path: str | Path | None) -> tuple[dict | None, str | None]:
    if manifest_path is None:
        return None, None

    path = Path(manifest_path).resolve()
    if not path.exists():
        return None, f"Manifest file not found: {path}"

    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as exc:
        return None, f"Failed to parse manifest JSON: {exc}"

    if not isinstance(manifest, dict):
        return None, "Manifest must be a JSON object."

    manifest["_manifest_path"] = str(path)
    return manifest, None


def expand_known_placeholders(value: str | None, extra: dict | None = None) -> str | None:
    if not isinstance(value, str):
        return value

    tokens = {}
    if get_materials_dir:
        try:
            tokens["materials_dir"] = str(get_materials_dir().resolve()).replace("\\", "/")
        except Exception:
            pass
    if get_output_dir:
        try:
            tokens["output_dir"] = str(get_output_dir().resolve()).replace("\\", "/")
        except Exception:
            pass
    if extra:
        tokens.update({k: str(v).replace("\\", "/") for k, v in extra.items()})

    expanded = value
    for key, replacement in tokens.items():
        expanded = expanded.replace("{" + key + "}", replacement)
    return expanded


def normalize_template_manifest(manifest: dict | None) -> dict:
    config = _deep_copy(DEFAULT_TEMPLATE_CONFIG)
    if not manifest:
        return config

    config["manifest_version"] = manifest.get("manifest_version")
    config["template_id"] = manifest.get("template_id")
    config["display_name"] = manifest.get("display_name")
    config["template_path"] = manifest.get("template_path")
    config["background_mode"] = manifest.get("background_mode")
    config["manifest_path"] = manifest.get("_manifest_path")

    raw_page_roles = manifest.get("page_roles")
    if isinstance(raw_page_roles, dict):
        for role_name, fallback_page in config["page_roles"].items():
            role_obj = raw_page_roles.get(role_name)
            if isinstance(role_obj, dict):
                config["page_roles"][role_name] = _coerce_positive_int(role_obj.get("page"), fallback_page)
            else:
                config["page_roles"][role_name] = _coerce_positive_int(role_obj, fallback_page)

        transition_obj = raw_page_roles.get("transition")
        if isinstance(transition_obj, dict):
            config["transition_default_font_size"] = _coerce_positive_int(
                transition_obj.get("default_font_size"),
                config["transition_default_font_size"],
            )

    selection_rules = manifest.get("selection_rules")
    if isinstance(selection_rules, dict):
        title_detection = selection_rules.get("title_detection")
        if isinstance(title_detection, dict):
            config["selection_rules"]["title_detection"]["mode"] = title_detection.get(
                "mode",
                config["selection_rules"]["title_detection"]["mode"],
            )
            config["selection_rules"]["title_detection"]["threshold_pt"] = _coerce_positive_int(
                title_detection.get("threshold_pt"),
                config["selection_rules"]["title_detection"]["threshold_pt"],
            )

        exclude_shapes = selection_rules.get("exclude_shapes")
        if isinstance(exclude_shapes, list):
            config["selection_rules"]["exclude_shapes"] = [
                shape for shape in exclude_shapes if isinstance(shape, dict)
            ] or config["selection_rules"]["exclude_shapes"]

    rendering_rules = manifest.get("rendering_rules")
    if isinstance(rendering_rules, dict):
        config["rendering_rules"]["paste_retry_count"] = _coerce_positive_int(
            rendering_rules.get("paste_retry_count"),
            config["rendering_rules"]["paste_retry_count"],
        )
        config["rendering_rules"]["paste_retry_delay_ms"] = _coerce_positive_int(
            rendering_rules.get("paste_retry_delay_ms"),
            config["rendering_rules"]["paste_retry_delay_ms"],
        )

    validation_rules = manifest.get("validation_rules")
    if isinstance(validation_rules, dict):
        config["validation_rules"]["require_transition_font_size_40"] = bool(
            validation_rules.get(
                "require_transition_font_size_40",
                config["validation_rules"]["require_transition_font_size_40"],
            )
        )

    return config


def resolve_manifest_template_path(manifest: dict | None) -> str | None:
    config = normalize_template_manifest(manifest)
    return expand_known_placeholders(config.get("template_path"))
