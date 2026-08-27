#!/usr/bin/env python3
"""
Style-driven SVG diagram generator.

Usage:
  python3 generate-from-template.py <template-type> <output-path> [data-json]

This generator intentionally does more than "fill a template".
It encodes the visual language from the documented style guides so the output
tracks the showcase quality more closely than the previous generic renderer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from types import ModuleType
from typing import Dict, List, Optional, Sequence, Set, Tuple
from xml.sax.saxutils import escape

Point = Tuple[float, float]
Bounds = Tuple[float, float, float, float]

SCRIPT_DIR = os.path.dirname(__file__)
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "..", "templates")
DEFAULT_VIEWBOX = {
    "architecture": (960, 600),
    "data-flow": (960, 600),
    "flowchart": (960, 640),
    "sequence": (960, 700),
    "comparison": (960, 620),
    "timeline": (960, 520),
    "mind-map": (960, 620),
    "agent": (960, 700),
    "memory": (960, 720),
    "use-case": (960, 600),
    "class": (960, 700),
    "state-machine": (960, 620),
    "er-diagram": (960, 680),
    "network-topology": (960, 620),
}

SUPPORTED_TEMPLATE_TYPES: Set[str] = set(DEFAULT_VIEWBOX) | {
    "agent-architecture",
    "comparison-matrix",
}

SUPPORTED_NODE_KINDS: Set[str] = {
    "rect",
    "double_rect",
    "cylinder",
    "document",
    "folder",
    "terminal",
    "hexagon",
    "circle_cluster",
    "user_avatar",
    "bot",
    "speech",
    "icon_box",
    "diamond",
    "circle",
    "ellipse",
    "actor",
    "entity",
    "state",
    "initial",
    "final",
    "terminator",
    "participant",
    "use-case",
    "timeline-event",
    "milestone",
    "process",
    "external-entity",
    "data-store",
}

SUPPORTED_PORTS: Set[str] = {
    "left",
    "right",
    "top",
    "bottom",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
}

SAFE_FILTER_IDS: Set[str] = {
    "shadowSoft",
    "shadowGlass",
    "glowBlue",
    "glowPurple",
    "glowGreen",
    "glowOrange",
}

SAFE_MARKER_IDS: Set[str] = set(MARKER_IDS.values()) if "MARKER_IDS" in globals() else {
    "arrowA", "arrowB", "arrowC", "arrowE", "arrowF", "arrowG", "arrowH"
}

FLOW_ALIASES = {
    "main": "control",
    "api": "control",
    "control": "control",
    "write": "write",
    "read": "read",
    "data": "data",
    "async": "async",
    "feedback": "feedback",
    "neutral": "neutral",
}

MARKER_IDS = {
    "control": "arrowA",
    "write": "arrowB",
    "read": "arrowC",
    "data": "arrowE",
    "async": "arrowF",
    "feedback": "arrowG",
    "neutral": "arrowH",
}

STYLE_PROFILES: Dict[int, Dict[str, object]] = {
    1: {
        "name": "Flat Icon",
        "font_family": "'Helvetica Neue', Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif",
        "background": "#ffffff",
        "shadow": True,
        "title_align": "center",
        "title_fill": "#111827",
        "title_size": 30,
        "subtitle_fill": "#6b7280",
        "subtitle_size": 14,
        "node_fill": "#ffffff",
        "node_stroke": "#d1d5db",
        "node_radius": 10,
        "node_shadow": "url(#shadowSoft)",
        "section_fill": "none",
        "section_stroke": "#dbe5f1",
        "section_dash": "6 5",
        "section_label_fill": "#2563eb",
        "section_sub_fill": "#94a3b8",
        "title_divider": False,
        "section_upper": True,
        "arrow_width": 2.4,
        "arrow_colors": {
            "control": "#7c3aed",
            "write": "#10b981",
            "read": "#2563eb",
            "data": "#f97316",
            "async": "#7c3aed",
            "feedback": "#ef4444",
            "neutral": "#6b7280",
        },
        "arrow_label_bg": "#ffffff",
        "arrow_label_opacity": 0.94,
        "arrow_label_fill": "#6b7280",
        "type_label_fill": "#9ca3af",
        "type_label_size": 12,
        "text_primary": "#111827",
        "text_secondary": "#6b7280",
        "text_muted": "#94a3b8",
        "legend_fill": "#6b7280",
    },
    2: {
        "name": "Dark Terminal",
        "font_family": "'SF Mono', 'Fira Code', Menlo, 'Microsoft YaHei', 'SimHei', monospace",
        "background": "#0f172a",
        "shadow": False,
        "title_align": "center",
        "title_fill": "#e2e8f0",
        "title_size": 30,
        "subtitle_fill": "#94a3b8",
        "subtitle_size": 14,
        "node_fill": "#111827",
        "node_stroke": "#334155",
        "node_radius": 10,
        "node_shadow": "",
        "section_fill": "rgba(15,23,42,0.28)",
        "section_stroke": "#334155",
        "section_dash": "7 6",
        "section_label_fill": "#38bdf8",
        "section_sub_fill": "#64748b",
        "title_divider": False,
        "section_upper": True,
        "arrow_width": 2.3,
        "arrow_colors": {
            "control": "#a855f7",
            "write": "#22c55e",
            "read": "#38bdf8",
            "data": "#fb7185",
            "async": "#f59e0b",
            "feedback": "#f97316",
            "neutral": "#94a3b8",
        },
        "arrow_label_bg": "#0f172a",
        "arrow_label_opacity": 0.92,
        "arrow_label_fill": "#cbd5e1",
        "type_label_fill": "#64748b",
        "type_label_size": 12,
        "text_primary": "#e2e8f0",
        "text_secondary": "#94a3b8",
        "text_muted": "#64748b",
        "legend_fill": "#94a3b8",
    },
    3: {
        "name": "Blueprint",
        "font_family": "'SF Mono', 'Fira Code', Menlo, 'Microsoft YaHei', 'SimHei', monospace",
        "background": "#082f49",
        "shadow": False,
        "title_align": "center",
        "title_fill": "#e0f2fe",
        "title_size": 30,
        "subtitle_fill": "#7dd3fc",
        "subtitle_size": 14,
        "node_fill": "#0b3b5e",
        "node_stroke": "#67e8f9",
        "node_radius": 8,
        "node_shadow": "",
        "section_fill": "none",
        "section_stroke": "#0ea5e9",
        "section_dash": "6 4",
        "section_label_fill": "#67e8f9",
        "section_sub_fill": "#7dd3fc",
        "title_divider": False,
        "section_upper": True,
        "arrow_width": 2.1,
        "arrow_colors": {
            "control": "#67e8f9",
            "write": "#22d3ee",
            "read": "#38bdf8",
            "data": "#fde047",
            "async": "#c084fc",
            "feedback": "#fb7185",
            "neutral": "#bae6fd",
        },
        "arrow_label_bg": "#082f49",
        "arrow_label_opacity": 0.9,
        "arrow_label_fill": "#e0f2fe",
        "type_label_fill": "#7dd3fc",
        "type_label_size": 11,
        "text_primary": "#e0f2fe",
        "text_secondary": "#bae6fd",
        "text_muted": "#7dd3fc",
        "legend_fill": "#bae6fd",
    },
    4: {
        "name": "Notion Clean",
        "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif",
        "background": "#ffffff",
        "shadow": False,
        "title_align": "left",
        "title_fill": "#111827",
        "title_size": 18,
        "subtitle_fill": "#9ca3af",
        "subtitle_size": 13,
        "node_fill": "#f9fafb",
        "node_stroke": "#e5e7eb",
        "node_radius": 4,
        "node_shadow": "",
        "section_fill": "none",
        "section_stroke": "#e5e7eb",
        "section_dash": "",
        "section_label_fill": "#9ca3af",
        "section_sub_fill": "#d1d5db",
        "title_divider": True,
        "section_upper": True,
        "arrow_width": 1.8,
        "arrow_colors": {
            "control": "#3b82f6",
            "write": "#3b82f6",
            "read": "#3b82f6",
            "data": "#3b82f6",
            "async": "#9ca3af",
            "feedback": "#9ca3af",
            "neutral": "#d1d5db",
        },
        "arrow_label_bg": "#ffffff",
        "arrow_label_opacity": 0.96,
        "arrow_label_fill": "#6b7280",
        "type_label_fill": "#9ca3af",
        "type_label_size": 11,
        "text_primary": "#111827",
        "text_secondary": "#374151",
        "text_muted": "#9ca3af",
        "legend_fill": "#6b7280",
    },
    5: {
        "name": "Glassmorphism",
        "font_family": "'Helvetica Neue', Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif",
        "background": "#0f172a",
        "shadow": True,
        "title_align": "center",
        "title_fill": "#f8fafc",
        "title_size": 30,
        "subtitle_fill": "#cbd5e1",
        "subtitle_size": 14,
        "node_fill": "rgba(255,255,255,0.12)",
        "node_stroke": "rgba(255,255,255,0.28)",
        "node_radius": 18,
        "node_shadow": "url(#shadowGlass)",
        "section_fill": "rgba(255,255,255,0.05)",
        "section_stroke": "rgba(255,255,255,0.18)",
        "section_dash": "7 6",
        "section_label_fill": "#e2e8f0",
        "section_sub_fill": "#94a3b8",
        "title_divider": False,
        "section_upper": True,
        "arrow_width": 2.2,
        "arrow_colors": {
            "control": "#c084fc",
            "write": "#34d399",
            "read": "#60a5fa",
            "data": "#fb923c",
            "async": "#f472b6",
            "feedback": "#f59e0b",
            "neutral": "#cbd5e1",
        },
        "arrow_label_bg": "rgba(15,23,42,0.7)",
        "arrow_label_opacity": 1,
        "arrow_label_fill": "#e2e8f0",
        "type_label_fill": "#cbd5e1",
        "type_label_size": 12,
        "text_primary": "#f8fafc",
        "text_secondary": "#cbd5e1",
        "text_muted": "#94a3b8",
        "legend_fill": "#cbd5e1",
    },
    6: {
        "name": "Warm Editorial",
        "font_family": "'Helvetica Neue', Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif",
        "background": "#f8f6f3",
        "shadow": False,
        "title_align": "left",
        "title_fill": "#141413",
        "title_size": 24,
        "subtitle_fill": "#8f8a80",
        "subtitle_size": 13,
        "node_fill": "#fffcf7",
        "node_stroke": "#d9d0c3",
        "node_radius": 10,
        "node_shadow": "",
        "section_fill": "none",
        "section_stroke": "#ded8cf",
        "section_dash": "5 4",
        "section_label_fill": "#8b7355",
        "section_sub_fill": "#b4aba0",
        "title_divider": True,
        "section_upper": True,
        "arrow_width": 2.0,
        "arrow_colors": {
            "control": "#d97757",
            "write": "#7b8b5c",
            "read": "#8c6f5a",
            "data": "#b45309",
            "async": "#9a6fb0",
            "feedback": "#d97757",
            "neutral": "#8f8a80",
        },
        "arrow_label_bg": "#f8f6f3",
        "arrow_label_opacity": 0.96,
        "arrow_label_fill": "#6b6257",
        "type_label_fill": "#a29a8f",
        "type_label_size": 11,
        "text_primary": "#141413",
        "text_secondary": "#6b6257",
        "text_muted": "#a29a8f",
        "legend_fill": "#6b6257",
    },
    7: {
        "name": "Clean Green",
        "font_family": "'Helvetica Neue', Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif",
        "background": "#ffffff",
        "shadow": False,
        "title_align": "left",
        "title_fill": "#0f172a",
        "title_size": 24,
        "subtitle_fill": "#64748b",
        "subtitle_size": 13,
        "node_fill": "#ffffff",
        "node_stroke": "#dce5e3",
        "node_radius": 14,
        "node_shadow": "",
        "section_fill": "none",
        "section_stroke": "#e2e8f0",
        "section_dash": "5 4",
        "section_label_fill": "#10a37f",
        "section_sub_fill": "#94a3b8",
        "title_divider": True,
        "section_upper": True,
        "arrow_width": 2.0,
        "arrow_colors": {
            "control": "#10a37f",
            "write": "#0f766e",
            "read": "#0891b2",
            "data": "#f59e0b",
            "async": "#64748b",
            "feedback": "#10a37f",
            "neutral": "#94a3b8",
        },
        "arrow_label_bg": "#ffffff",
        "arrow_label_opacity": 0.96,
        "arrow_label_fill": "#475569",
        "type_label_fill": "#94a3b8",
        "type_label_size": 11,
        "text_primary": "#0f172a",
        "text_secondary": "#475569",
        "text_muted": "#94a3b8",
        "legend_fill": "#475569",
    },
}


@dataclass
class Node:
    node_id: str
    kind: str
    shape: str
    data: Dict[str, object]
    bounds: Bounds
    cx: float
    cy: float


_INVALID_XML_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)
_PAINT_RE = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9.,%+\-\s]+\)|[A-Za-z]+)$"
)
_DASH_RE = re.compile(r"^(?:none|[0-9]+(?:\.[0-9]+)?(?:[ ,]+[0-9]+(?:\.[0-9]+)?)*)$")
_SAFE_FONT_RE = re.compile(r"^[A-Za-z0-9_',\-\s]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")

TOP_LEVEL_FIELDS: Set[str] = {
    "template_type", "title", "subtitle", "description", "style", "style_overrides",
    "width", "height", "viewBox", "containers", "nodes", "arrows", "legend",
    "legend_x", "legend_y", "legend_position", "legend_box", "legend_box_fill",
    "legend_box_opacity", "footer", "footer_x", "footer_y", "footer_position",
    "window_controls", "meta_left", "meta_center", "meta_right", "meta_fill", "meta_size",
    "blueprint_title_block", "layout", "_layout_stats", "_renderer_prepared",
}
NODE_FIELDS: Set[str] = {
    "id", "kind", "shape", "x", "y", "width", "height", "r", "rx", "label",
    "name", "title", "sublabel", "type_label", "fill", "stroke", "stroke_width",
    "filter", "glow", "flat", "accent_fill", "header_fill", "header_dots",
    "prompt_fill", "line_stroke", "icon_fill", "icon_stroke", "body_fill", "tags",
    "attributes", "auto_place", "offset_y", "semantic_type", "type", "side", "layout",
    "container_id", "container", "parent", "group",
}
ARROW_FIELDS: Set[str] = {
    "source", "target", "x1", "y1", "x2", "y2", "source_port", "target_port",
    "route_points", "corridor_x", "corridor_y", "routing_padding", "port_clearance",
    "flow", "color", "marker", "marker_end", "stroke_width", "stroke_dasharray",
    "dashed", "opacity", "label", "label_dx", "label_dy", "label_style",
    "semantic_source", "semantic_target", "semantic_type", "sequence_message_type",
    "participant", "event", "from_cardinality", "to_cardinality", "type",
}
CONTAINER_FIELDS: Set[str] = {
    "id", "name", "kind", "x", "y", "width", "height", "rx", "fill", "stroke", "stroke_dasharray",
    "label", "subtitle", "header_text", "header_prefix", "header_separator",
    "header_height", "preserve_case", "side_label", "side_label_x", "side_label_y",
    "side_label_fill", "side_label_size", "side_label_weight", "side_label_anchor", "layout_padding",
}


def _reject_unknown_fields(mapping: Dict[str, object], allowed: Set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ValueError(f"{_path(path, unknown[0])} is not a supported field")


def _path(parent: str, field: object) -> str:
    return f"{parent}[{field}]" if isinstance(field, int) else f"{parent}.{field}"


def _require_mapping(value: object, path: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _require_list(value: object, path: str) -> List[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    return value


def _require_string(value: object, path: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"{path} must not be empty")
    if _INVALID_XML_RE.search(value):
        raise ValueError(f"{path} contains characters that are invalid in XML")
    return value


def _require_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value


def _require_number(
    value: object,
    path: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number")
    if positive and result <= 0:
        raise ValueError(f"{path} must be greater than 0")
    if nonnegative and result < 0:
        raise ValueError(f"{path} must be at least 0")
    return result


def _validate_paint(value: object, path: str, *, allow_none: bool = True) -> str:
    text = _require_string(value, path, allow_empty=False).strip()
    lowered = text.lower()
    if lowered == "none" and not allow_none:
        raise ValueError(f"{path} may not be 'none'")
    if "url(" in lowered or "javascript:" in lowered or not _PAINT_RE.fullmatch(text):
        raise ValueError(f"{path} is not a safe SVG paint value")
    return text


def _validate_dash(value: object, path: str) -> str:
    text = _require_string(value, path).strip()
    if text and not _DASH_RE.fullmatch(text):
        raise ValueError(f"{path} must be a numeric SVG dash pattern")
    return text


def _validate_opacity(value: object, path: str) -> None:
    number = _require_number(value, path)
    if not 0 <= number <= 1:
        raise ValueError(f"{path} must be between 0 and 1")


def _validate_all_xml_strings(value: object, path: str = "data") -> None:
    if isinstance(value, str):
        _require_string(value, path)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_all_xml_strings(item, _path(path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_all_xml_strings(item, _path(path, index))


def _validate_style_overrides(overrides: object) -> None:
    mapping = _require_mapping(overrides, "data.style_overrides")
    allowed = set(STYLE_PROFILES[1]) - {"name"}
    color_keys = {
        "background", "title_fill", "subtitle_fill", "node_fill", "node_stroke",
        "section_fill", "section_stroke", "section_label_fill", "section_sub_fill",
        "arrow_label_bg", "arrow_label_fill", "type_label_fill", "text_primary",
        "text_secondary", "text_muted", "legend_fill",
    }
    numeric_positive = {"title_size", "subtitle_size", "node_radius", "arrow_width", "type_label_size"}
    bool_keys = {"shadow", "title_divider", "section_upper"}
    for key, value in mapping.items():
        path = _path("data.style_overrides", key)
        if key not in allowed:
            raise ValueError(f"{path} is not an allowed style override")
        if key in color_keys:
            _validate_paint(value, path)
        elif key in numeric_positive:
            _require_number(value, path, positive=True)
        elif key == "arrow_label_opacity":
            _validate_opacity(value, path)
        elif key in bool_keys:
            _require_bool(value, path)
        elif key == "title_align":
            if _require_string(value, path) not in {"left", "center"}:
                raise ValueError(f"{path} must be 'left' or 'center'")
        elif key == "section_dash":
            _validate_dash(value, path)
        elif key == "font_family":
            text = _require_string(value, path, allow_empty=False)
            if not _SAFE_FONT_RE.fullmatch(text):
                raise ValueError(f"{path} contains unsafe CSS")
        elif key == "node_shadow":
            text = _require_string(value, path)
            allowed_shadows = {"", "url(#shadowSoft)", "url(#shadowGlass)"}
            if text not in allowed_shadows:
                raise ValueError(f"{path} must reference a built-in local filter")
        elif key == "arrow_colors":
            colors = _require_mapping(value, path)
            if not colors:
                raise ValueError(f"{path} must not be empty")
            for flow, color in colors.items():
                if flow not in MARKER_IDS:
                    raise ValueError(f"{_path(path, flow)} is not a supported flow")
                _validate_paint(color, _path(path, flow), allow_none=False)
        else:
            _require_string(value, path)


def _validate_tags(tags: object, path: str) -> None:
    for index, raw_tag in enumerate(_require_list(tags, path)):
        tag_path = _path(path, index)
        tag = _require_mapping(raw_tag, tag_path)
        _reject_unknown_fields(tag, {"label", "fill", "stroke", "text_fill"}, tag_path)
        if "label" in tag:
            _require_string(tag["label"], _path(tag_path, "label"))
        for field in ("fill", "stroke", "text_fill"):
            if field in tag:
                _validate_paint(tag[field], _path(tag_path, field))


def _validate_entity_attributes(attributes: object, path: str) -> None:
    for index, raw_attribute in enumerate(_require_list(attributes, path)):
        item_path = _path(path, index)
        if isinstance(raw_attribute, str):
            _require_string(raw_attribute, item_path)
            continue
        attribute = _require_mapping(raw_attribute, item_path)
        _reject_unknown_fields(attribute, {"name", "label", "type", "key", "pk", "fk"}, item_path)
        if not any(field in attribute for field in ("name", "label")):
            raise ValueError(f"{item_path} requires 'name' or 'label'")
        for field in ("name", "label", "type", "key"):
            if field in attribute:
                _require_string(attribute[field], _path(item_path, field))
        for field in ("pk", "fk"):
            if field in attribute:
                _require_bool(attribute[field], _path(item_path, field))


def _validate_nodes(
    nodes: object,
    *,
    require_positions: bool = True,
    allow_semantic_kinds: bool = False,
) -> Tuple[List[Dict[str, object]], Set[str]]:
    result: List[Dict[str, object]] = []
    node_ids: Set[str] = set()
    for index, raw_node in enumerate(_require_list(nodes, "data.nodes")):
        path = _path("data.nodes", index)
        node = _require_mapping(raw_node, path)
        _reject_unknown_fields(node, NODE_FIELDS, path)
        if "id" not in node:
            raise ValueError(f"{path}.id is required")
        node_id = _require_string(node["id"], _path(path, "id"), allow_empty=False).strip()
        if not _SAFE_ID_RE.fullmatch(node_id):
            raise ValueError(f"{path}.id must be a safe identifier")
        if node_id in node_ids:
            raise ValueError(f"{path}.id duplicates node id: {node_id}")
        node_ids.add(node_id)
        kind_value = node.get("kind", node.get("shape", "rect"))
        kind = _require_string(kind_value, _path(path, "kind"), allow_empty=False).strip()
        semantic_kind_aliases = {
            "start", "end", "action", "task", "decision", "condition", "gateway"
        }
        if kind not in SUPPORTED_NODE_KINDS and not (allow_semantic_kinds and kind in semantic_kind_aliases):
            raise ValueError(f"{path}.kind has unsupported value: {kind}")
        if require_positions and "x" not in node:
            raise ValueError(f"{path}.x is required")
        if "x" in node:
            _require_number(node["x"], _path(path, "x"))
        auto_place = node.get("auto_place", False)
        if "auto_place" in node:
            _require_bool(auto_place, _path(path, "auto_place"))
        if require_positions and "y" not in node and not auto_place:
            raise ValueError(f"{path}.y is required unless auto_place is true")
        if "y" in node:
            _require_number(node["y"], _path(path, "y"))
        for field in ("width", "height", "r"):
            if field in node:
                _require_number(node[field], _path(path, field), positive=True)
        for field in ("rx", "offset_y"):
            if field in node:
                _require_number(node[field], _path(path, field), nonnegative=(field == "rx"))
        for field in ("stroke_width",):
            if field in node:
                _require_number(node[field], _path(path, field), positive=True)
        for field in ("label", "sublabel", "type_label"):
            if field in node:
                _require_string(node[field], _path(path, field))
        for field in ("name", "title", "semantic_type", "type", "side"):
            if field in node:
                _require_string(node[field], _path(path, field))
        if "layout" in node:
            layout = _require_mapping(node["layout"], _path(path, "layout"))
            _reject_unknown_fields(layout, {"auto"}, _path(path, "layout"))
            if "auto" in layout:
                _require_bool(layout["auto"], _path(_path(path, "layout"), "auto"))
        for field in (
            "fill", "stroke", "accent_fill", "header_fill", "icon_fill", "icon_stroke",
            "line_stroke", "body_fill", "prompt_fill",
        ):
            if field in node:
                _validate_paint(node[field], _path(path, field))
        for field in ("flat",):
            if field in node:
                _require_bool(node[field], _path(path, field))
        if "filter" in node:
            filter_id = _require_string(node["filter"], _path(path, "filter"), allow_empty=False)
            if filter_id not in SAFE_FILTER_IDS:
                raise ValueError(f"{path}.filter must reference a built-in local filter")
        if "glow" in node:
            glow = _require_string(node["glow"], _path(path, "glow"), allow_empty=False)
            if glow not in {"blue", "purple", "green", "orange"}:
                raise ValueError(f"{path}.glow is unsupported")
        if "header_dots" in node:
            dots = _require_list(node["header_dots"], _path(path, "header_dots"))
            for dot_index, color in enumerate(dots):
                _validate_paint(color, _path(_path(path, "header_dots"), dot_index))
        if "tags" in node:
            _validate_tags(node["tags"], _path(path, "tags"))
        if "attributes" in node:
            _validate_entity_attributes(node["attributes"], _path(path, "attributes"))
        result.append(node)
    return result, node_ids


def _validate_containers(containers: object) -> List[Dict[str, object]]:
    result: List[Dict[str, object]] = []
    container_ids: Set[str] = set()
    for index, raw_container in enumerate(_require_list(containers, "data.containers")):
        path = _path("data.containers", index)
        container = _require_mapping(raw_container, path)
        _reject_unknown_fields(container, CONTAINER_FIELDS, path)
        if "id" in container:
            container_id = _require_string(container["id"], _path(path, "id"), allow_empty=False)
            if container_id != container_id.strip():
                raise ValueError(f"{path}.id must not contain surrounding whitespace")
            if not _SAFE_ID_RE.fullmatch(container_id):
                raise ValueError(f"{path}.id must be a safe identifier")
            if container_id in container_ids:
                raise ValueError(f"{path}.id duplicates container id: {container_id}")
            container_ids.add(container_id)
        if "name" in container:
            _require_string(container["name"], _path(path, "name"), allow_empty=False)
        if "kind" in container:
            kind = _require_string(container["kind"], _path(path, "kind"), allow_empty=False)
            if kind not in {"container", "group", "section", "swimlane", "layer"}:
                raise ValueError(f"{path}.kind has unsupported value: {kind}")
        for field in ("x", "y", "width", "height"):
            if field not in container:
                raise ValueError(f"{path}.{field} is required")
            _require_number(
                container[field], _path(path, field), positive=field in {"width", "height"}
            )
        for field in ("rx", "header_height", "side_label_size"):
            if field in container:
                _require_number(container[field], _path(path, field), nonnegative=True)
        if "layout_padding" in container:
            _require_number(container["layout_padding"], _path(path, "layout_padding"), positive=True)
        for field in ("side_label_x", "side_label_y"):
            if field in container:
                _require_number(container[field], _path(path, field))
        for field in (
            "label", "subtitle", "side_label", "header_text", "header_prefix",
            "header_separator",
        ):
            if field in container:
                _require_string(container[field], _path(path, field))
        if "side_label_weight" in container:
            weight = _require_string(container["side_label_weight"], _path(path, "side_label_weight"))
            if weight not in {"normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600", "700", "800", "900"}:
                raise ValueError(f"{path}.side_label_weight is invalid")
        for field in ("fill", "stroke", "side_label_fill"):
            if field in container:
                _validate_paint(container[field], _path(path, field))
        if "stroke_dasharray" in container:
            _validate_dash(container["stroke_dasharray"], _path(path, "stroke_dasharray"))
        if "side_label_anchor" in container:
            anchor = _require_string(container["side_label_anchor"], _path(path, "side_label_anchor"))
            if anchor not in {"start", "middle", "end"}:
                raise ValueError(f"{path}.side_label_anchor is invalid")
        if "preserve_case" in container:
            _require_bool(container["preserve_case"], _path(path, "preserve_case"))
        result.append(container)
    return result


def _validate_container_references(
    containers: Sequence[Dict[str, object]],
    nodes: Sequence[Dict[str, object]],
) -> None:
    id_index: Dict[str, int] = {}
    alias_index: Dict[str, Set[int]] = {}
    for index, container in enumerate(containers):
        if "id" in container:
            container_id = str(container["id"])
            id_index[container_id] = index
        for field in ("id", "name", "label"):
            raw = container.get(field)
            if raw is None or not str(raw).strip():
                continue
            alias_index.setdefault(str(raw), set()).add(index)

    for node_index, node in enumerate(nodes):
        node_path = _path("data.nodes", node_index)
        resolved: List[Tuple[str, int]] = []
        if "container_id" in node:
            path = _path(node_path, "container_id")
            reference = _require_string(node["container_id"], path, allow_empty=False)
            if reference != reference.strip():
                raise ValueError(f"{path} must not contain surrounding whitespace")
            if not _SAFE_ID_RE.fullmatch(reference):
                raise ValueError(f"{path} must be a safe container identifier")
            target = id_index.get(reference)
            if target is None:
                raise ValueError(f"{path} references unknown container id: {reference}")
            resolved.append(("container_id", target))
        for field in ("container", "parent", "group"):
            if field not in node:
                continue
            path = _path(node_path, field)
            reference = _require_string(node[field], path, allow_empty=False)
            matches = alias_index.get(reference, set())
            if not matches:
                raise ValueError(f"{path} references unknown container: {reference}")
            if len(matches) > 1:
                raise ValueError(f"{path} is ambiguous across multiple containers: {reference}")
            resolved.append((field, next(iter(matches))))
        if resolved and len({target for _, target in resolved}) > 1:
            fields = ", ".join(field for field, _ in resolved)
            raise ValueError(f"{node_path} has conflicting container references: {fields}")


def _validate_layout_config(value: object, path: str = "data.layout") -> Dict[str, object]:
    layout = _require_mapping(value, path)
    allowed_layout = {
        "auto", "horizontal_gap", "vertical_gap", "minimum_gap", "direction",
        "preserve_aspect", "preserve_route_hints",
    }
    _reject_unknown_fields(layout, allowed_layout, path)
    for field in ("auto", "preserve_aspect", "preserve_route_hints"):
        if field in layout:
            _require_bool(layout[field], _path(path, field))
    for field in ("horizontal_gap", "vertical_gap", "minimum_gap"):
        if field in layout:
            _require_number(layout[field], _path(path, field), positive=True)
    if "direction" in layout:
        direction = _require_string(layout["direction"], _path(path, "direction"), allow_empty=False)
        if direction not in {"TB", "LR"}:
            raise ValueError(f"{path}.direction must be 'TB' or 'LR'")
    return layout


def _validate_arrows(arrows: object, node_ids: Set[str]) -> List[Dict[str, object]]:
    result: List[Dict[str, object]] = []
    for index, raw_arrow in enumerate(_require_list(arrows, "data.arrows")):
        path = _path("data.arrows", index)
        arrow = _require_mapping(raw_arrow, path)
        _reject_unknown_fields(arrow, ARROW_FIELDS, path)
        for endpoint, coord_x, coord_y in (("source", "x1", "y1"), ("target", "x2", "y2")):
            if endpoint in arrow:
                node_id = _require_string(arrow[endpoint], _path(path, endpoint), allow_empty=False).strip()
                if node_id not in node_ids:
                    raise ValueError(f"{path}.{endpoint} references unknown node: {node_id}")
            else:
                for coordinate in (coord_x, coord_y):
                    if coordinate not in arrow:
                        raise ValueError(f"{path} requires {endpoint} or both {coord_x}/{coord_y}")
                    _require_number(arrow[coordinate], _path(path, coordinate))
        for field, endpoint in (("source_port", "source"), ("target_port", "target")):
            if field in arrow:
                if endpoint not in arrow:
                    raise ValueError(f"{path}.{field} requires a node {endpoint}")
                port = _require_string(arrow[field], _path(path, field), allow_empty=False).lower()
                if port not in SUPPORTED_PORTS:
                    raise ValueError(f"{path}.{field} has unsupported port: {port}")
        if "flow" in arrow:
            flow = _require_string(arrow["flow"], _path(path, "flow"), allow_empty=False).lower()
            if flow not in FLOW_ALIASES:
                raise ValueError(f"{path}.flow has unsupported value: {flow}")
        for field in ("label",):
            if field in arrow:
                _require_string(arrow[field], _path(path, field))
        for field in (
            "semantic_source", "semantic_target", "semantic_type", "sequence_message_type",
            "participant", "event", "from_cardinality", "to_cardinality", "type",
        ):
            if field in arrow:
                _require_string(arrow[field], _path(path, field))
        for field in (
            "x1", "y1", "x2", "y2", "routing_padding", "port_clearance", "stroke_width",
            "label_dx", "label_dy",
        ):
            if field in arrow:
                _require_number(
                    arrow[field], _path(path, field), positive=field in {"routing_padding", "port_clearance", "stroke_width"}
                )
        for field in ("dashed", "marker_end"):
            if field in arrow:
                _require_bool(arrow[field], _path(path, field))
        if "opacity" in arrow:
            _validate_opacity(arrow["opacity"], _path(path, "opacity"))
        if "color" in arrow:
            _validate_paint(arrow["color"], _path(path, "color"), allow_none=False)
        if "stroke_dasharray" in arrow:
            _validate_dash(arrow["stroke_dasharray"], _path(path, "stroke_dasharray"))
        if "marker" in arrow:
            marker = _require_string(arrow["marker"], _path(path, "marker"), allow_empty=False)
            if marker not in SAFE_MARKER_IDS:
                raise ValueError(f"{path}.marker must reference a built-in local marker")
        if "label_style" in arrow:
            label_style = _require_string(arrow["label_style"], _path(path, "label_style"))
            if label_style not in {"badge", "offset"}:
                raise ValueError(f"{path}.label_style is invalid")
        for field in ("corridor_x", "corridor_y"):
            if field in arrow:
                values = _require_list(arrow[field], _path(path, field))
                for value_index, value in enumerate(values):
                    _require_number(value, _path(_path(path, field), value_index))
        if "route_points" in arrow:
            points = _require_list(arrow["route_points"], _path(path, "route_points"))
            for point_index, raw_point in enumerate(points):
                point_path = _path(_path(path, "route_points"), point_index)
                point = _require_list(raw_point, point_path)
                if len(point) != 2:
                    raise ValueError(f"{point_path} must contain exactly [x, y]")
                _require_number(point[0], _path(point_path, 0))
                _require_number(point[1], _path(point_path, 1))
        result.append(arrow)
    return result


def _validate_legend(legend: object) -> None:
    for index, raw_item in enumerate(_require_list(legend, "data.legend")):
        path = _path("data.legend", index)
        item = _require_mapping(raw_item, path)
        _reject_unknown_fields(item, {"label", "flow", "color"}, path)
        if "label" in item:
            _require_string(item["label"], _path(path, "label"))
        if "flow" in item:
            flow = _require_string(item["flow"], _path(path, "flow"), allow_empty=False).lower()
            if flow not in FLOW_ALIASES:
                raise ValueError(f"{path}.flow has unsupported value: {flow}")
        if "color" in item:
            _validate_paint(item["color"], _path(path, "color"), allow_none=False)


def _validate_blueprint_block(block: object) -> None:
    mapping = _require_mapping(block, "data.blueprint_title_block")
    _reject_unknown_fields(
        mapping,
        {
            "x", "y", "width", "height", "title", "subtitle", "left_caption",
            "center_caption", "right_caption", "stroke", "fill", "title_fill",
            "subtitle_fill", "muted_fill",
        },
        "data.blueprint_title_block",
    )
    for field in ("x", "y"):
        if field in mapping:
            _require_number(mapping[field], _path("data.blueprint_title_block", field))
    for field in ("width", "height"):
        if field in mapping:
            _require_number(mapping[field], _path("data.blueprint_title_block", field), positive=True)
    for field in ("title", "subtitle", "left_caption", "center_caption", "right_caption"):
        if field in mapping:
            _require_string(mapping[field], _path("data.blueprint_title_block", field))
    for field in ("stroke", "fill", "title_fill", "subtitle_fill", "muted_fill"):
        if field in mapping:
            _validate_paint(mapping[field], _path("data.blueprint_title_block", field))


def validate_diagram_data(template_type: str, data: object) -> Dict[str, object]:
    if template_type not in SUPPORTED_TEMPLATE_TYPES:
        raise ValueError(f"Unsupported template type: {template_type}")
    mapping = _require_mapping(data, "data")
    _reject_unknown_fields(mapping, TOP_LEVEL_FIELDS, "data")
    _validate_all_xml_strings(mapping)
    if "template_type" in mapping:
        declared = _require_string(mapping["template_type"], "data.template_type", allow_empty=False)
        if declared not in SUPPORTED_TEMPLATE_TYPES:
            raise ValueError(f"data.template_type has unsupported value: {declared}")
    parse_style(mapping.get("style"))
    for field in ("title", "subtitle", "description", "footer", "meta_left", "meta_center", "meta_right"):
        if field in mapping:
            _require_string(mapping[field], _path("data", field))
    for field in ("width", "height"):
        if field in mapping:
            _require_number(mapping[field], _path("data", field), positive=True)
    for field in ("legend_x", "legend_y", "footer_x", "footer_y"):
        if field in mapping:
            _require_number(mapping[field], _path("data", field))
    if "meta_size" in mapping:
        _require_number(mapping["meta_size"], "data.meta_size", positive=True)
    for field in ("meta_fill", "legend_box_fill"):
        if field in mapping:
            _validate_paint(mapping[field], _path("data", field))
    if "legend_box_opacity" in mapping:
        _validate_opacity(mapping["legend_box_opacity"], "data.legend_box_opacity")
    if "legend_box" in mapping:
        _require_bool(mapping["legend_box"], "data.legend_box")
    if "viewBox" in mapping:
        text = _require_string(mapping["viewBox"], "data.viewBox", allow_empty=False).strip()
        match = re.fullmatch(r"0(?:\.0+)?\s+0(?:\.0+)?\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)", text)
        if not match or float(match.group(1)) <= 0 or float(match.group(2)) <= 0:
            raise ValueError("data.viewBox must be '0 0 <positive-width> <positive-height>'")
    if "legend_position" in mapping:
        position = _require_string(mapping["legend_position"], "data.legend_position")
        if position not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
            raise ValueError("data.legend_position is invalid")
    if "footer_position" in mapping:
        position = _require_string(mapping["footer_position"], "data.footer_position")
        if position not in {"bottom-left", "bottom-right"}:
            raise ValueError("data.footer_position is invalid")
    if "window_controls" in mapping:
        controls = mapping["window_controls"]
        if not isinstance(controls, bool):
            for index, color in enumerate(_require_list(controls, "data.window_controls")):
                _validate_paint(color, _path("data.window_controls", index), allow_none=False)
    if "style_overrides" in mapping:
        _validate_style_overrides(mapping["style_overrides"])
    containers = _validate_containers(mapping.get("containers", []))
    nodes, node_ids = _validate_nodes(mapping.get("nodes", []))
    _validate_container_references(containers, nodes)
    arrows = _validate_arrows(mapping.get("arrows", []), node_ids)
    _validate_legend(mapping.get("legend", []))
    if "blueprint_title_block" in mapping:
        _validate_blueprint_block(mapping["blueprint_title_block"])
    if "layout" in mapping:
        _validate_layout_config(mapping["layout"])
    if "_layout_stats" in mapping:
        _require_mapping(mapping["_layout_stats"], "data._layout_stats")
    if "_renderer_prepared" in mapping:
        _require_bool(mapping["_renderer_prepared"], "data._renderer_prepared")
    # Retain object identity for downstream rendering while making validated defaults explicit.
    mapping["containers"] = containers
    mapping["nodes"] = nodes
    mapping["arrows"] = arrows
    mapping.setdefault("legend", [])
    return mapping


def _prevalidate_reserved_fields(value: object, path: str = "data") -> None:
    """Reject security/topology control fields before helpers can normalize them."""
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = _path(path, key)
            if key in {"source_port", "target_port"}:
                port = _require_string(item, item_path, allow_empty=False).lower()
                if port not in SUPPORTED_PORTS:
                    raise ValueError(f"{item_path} has unsupported port: {port}")
            elif key in {"marker_end", "dashed", "auto_place"}:
                _require_bool(item, item_path)
            _prevalidate_reserved_fields(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _prevalidate_reserved_fields(item, _path(path, index))


def prevalidate_untrusted_input(template_type: str, data: object) -> Dict[str, object]:
    """Validate raw controls before semantic/layout modules can rewrite them.

    Semantic inputs may legitimately omit rendered coordinates, so the complete
    renderer schema is applied after preparation. This pass still ensures that
    malformed numbers, duplicate IDs, dangling generic edges, unsafe styles,
    and invalid ports cannot be silently repaired by a helper module.
    """
    if template_type not in SUPPORTED_TEMPLATE_TYPES:
        raise ValueError(f"Unsupported template type: {template_type}")
    mapping = _require_mapping(data, "data")
    _validate_all_xml_strings(mapping)
    _prevalidate_reserved_fields(mapping)
    parse_style(mapping.get("style"))
    for field in ("width", "height"):
        if field in mapping:
            _require_number(mapping[field], _path("data", field), positive=True)
    if "viewBox" in mapping:
        text = _require_string(mapping["viewBox"], "data.viewBox", allow_empty=False).strip()
        match = re.fullmatch(r"0(?:\.0+)?\s+0(?:\.0+)?\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)", text)
        if not match or float(match.group(1)) <= 0 or float(match.group(2)) <= 0:
            raise ValueError("data.viewBox must be '0 0 <positive-width> <positive-height>'")
    if "style_overrides" in mapping:
        _validate_style_overrides(mapping["style_overrides"])
    if "layout" in mapping:
        _validate_layout_config(mapping["layout"])
    containers: List[Dict[str, object]] = []
    if "containers" in mapping:
        containers = _validate_containers(mapping["containers"])
    node_ids: Set[str] = set()
    nodes: List[Dict[str, object]] = []
    if "nodes" in mapping:
        nodes, node_ids = _validate_nodes(
            mapping["nodes"], require_positions=False, allow_semantic_kinds=True
        )
        _validate_container_references(containers, nodes)
    if "arrows" in mapping:
        raw_arrows = _require_list(mapping["arrows"], "data.arrows")
        generic_edges = bool(node_ids) and all(
            isinstance(arrow, dict)
            and ("source" in arrow or ("x1" in arrow and "y1" in arrow))
            and ("target" in arrow or ("x2" in arrow and "y2" in arrow))
            for arrow in raw_arrows
        )
        if generic_edges or not raw_arrows:
            _validate_arrows(raw_arrows, node_ids)
        else:
            # Semantic relation arrays may use from/to; validate the shared
            # render controls now and let the semantic module validate ends.
            for index, raw_arrow in enumerate(raw_arrows):
                path = _path("data.arrows", index)
                arrow = _require_mapping(raw_arrow, path)
                for field in ("x1", "y1", "x2", "y2", "label_dx", "label_dy"):
                    if field in arrow:
                        _require_number(arrow[field], _path(path, field))
                if "flow" in arrow:
                    flow = _require_string(arrow["flow"], _path(path, "flow"), allow_empty=False).lower()
                    if flow not in FLOW_ALIASES:
                        raise ValueError(f"{path}.flow has unsupported value: {flow}")
                if "color" in arrow:
                    _validate_paint(arrow["color"], _path(path, "color"), allow_none=False)
                if "marker" in arrow:
                    marker = _require_string(arrow["marker"], _path(path, "marker"), allow_empty=False)
                    if marker not in SAFE_MARKER_IDS:
                        raise ValueError(f"{path}.marker must reference a built-in local marker")
                if "route_points" in arrow:
                    for point_index, raw_point in enumerate(
                        _require_list(arrow["route_points"], _path(path, "route_points"))
                    ):
                        point_path = _path(_path(path, "route_points"), point_index)
                        point = _require_list(raw_point, point_path)
                        if len(point) != 2:
                            raise ValueError(f"{point_path} must contain exactly [x, y]")
                        _require_number(point[0], _path(point_path, 0))
                        _require_number(point[1], _path(point_path, 1))
    return mapping


def _load_optional_module(filename: str, module_name: str) -> Optional[ModuleType]:
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load optional module: {filename}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError(f"Failed to load {filename}: {exc}") from exc
    return module


def prepare_diagram_data(template_type: str, data: object) -> Dict[str, object]:
    if template_type not in SUPPORTED_TEMPLATE_TYPES:
        raise ValueError(f"Unsupported template type: {template_type}")
    prepared = copy.deepcopy(prevalidate_untrusted_input(template_type, data))
    raw_nodes = prepared.get("nodes", [])
    already_prepared = (
        (prepared.get("_renderer_prepared") is True or isinstance(prepared.get("_layout_stats"), dict))
        and isinstance(raw_nodes, list)
        and all(isinstance(node, dict) and "x" in node and "y" in node for node in raw_nodes)
    )
    if already_prepared:
        # Preparation flags only suppress duplicate semantic/layout transforms;
        # they never bypass the strict schema, topology, or security validation.
        return validate_diagram_data(template_type, prepared)
    semantic_module = _load_optional_module("semantic_diagrams.py", "technical_diagram_semantics")
    if semantic_module is not None and template_type not in {"mind-map", "class"}:
        prepare = getattr(semantic_module, "prepare_diagram", None)
        if not callable(prepare):
            raise ValueError("semantic_diagrams.py must define prepare_diagram(template_type, data)")
        try:
            prepared = prepare(template_type, prepared)
        except Exception as exc:
            raise ValueError(f"Semantic diagram preparation failed: {exc}") from exc
        prepared = _require_mapping(prepared, "semantic_diagrams.prepare_diagram result")
    layout_module = _load_optional_module("layout_engine.py", "technical_diagram_layout")
    if layout_module is not None:
        apply_layout = getattr(layout_module, "apply_auto_layout", None)
        if not callable(apply_layout):
            raise ValueError("layout_engine.py must define apply_auto_layout(data, template_type)")
        try:
            prepared = apply_layout(prepared, template_type)
        except Exception as exc:
            raise ValueError(f"Automatic layout failed: {exc}") from exc
        prepared = _require_mapping(prepared, "layout_engine.apply_auto_layout result")
    return validate_diagram_data(template_type, prepared)


def style_value(style: Dict[str, object], key: str) -> object:
    return style[key]


def to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value: object) -> str:
    return escape(str(value)) if value is not None else ""

def render_multiline_text(text: str, x: float, y: float, text_anchor: str, cls: str, dy: float = 14) -> str:
    raw_str = str(text)
    if '\\n' in raw_str:
        lines = raw_str.split('\\n')
    else:
        lines = raw_str.split('\n')
    if len(lines) <= 1:
        return f'  <text x="{x}" y="{y}" text-anchor="{text_anchor}" class="{cls}">{normalize_text(lines[0])}</text>'

    y_start = y - (len(lines) - 1) * dy / 2
    parts = [f'  <text x="{x}" y="{y_start}" text-anchor="{text_anchor}" class="{cls}">']
    for i, line in enumerate(lines):
        parts.append(f'    <tspan x="{x}" dy="{dy if i > 0 else 0}">{normalize_text(line)}</tspan>')
    parts.append('  </text>')
    return "\n".join(parts)



# Style 8 is retained as a visual reference only. The validated generator does
# not implement it, so callers must select one of the supported styles 1-7.
_AI_AUTHORED_STYLES: Dict[int, str] = {8: "Style 8 (Dark Luxury)"}
_AI_AUTHORED_ALIASES: set = {"dark luxury", "dark-luxury"}
_AI_AUTHORED_MSG = (
    "{name} is reference-only and cannot currently be generated. "
    "Choose a supported style from 1-7."
)


def _unsupported_style_message(raw: object) -> str:
    return f"Unsupported style: {raw}. Choose a supported style from 1-7."


def parse_style(raw: object) -> Tuple[int, Dict[str, object]]:
    if raw is None:
        index = 1
    elif isinstance(raw, bool):
        raise ValueError(_unsupported_style_message(raw))
    elif isinstance(raw, int):
        index = raw
    elif not isinstance(raw, str):
        raise ValueError(_unsupported_style_message(raw))
    else:
        text = raw.strip().lower()
        if text.isdigit():
            index = int(text)
        else:
            if text in _AI_AUTHORED_ALIASES:
                raise ValueError(_AI_AUTHORED_MSG.format(name=_AI_AUTHORED_STYLES[8]))
            names = {profile["name"].lower(): key for key, profile in STYLE_PROFILES.items()}
            if text not in names:
                raise ValueError(_unsupported_style_message(raw))
            index = names[text]
    if index in _AI_AUTHORED_STYLES:
        raise ValueError(_AI_AUTHORED_MSG.format(name=_AI_AUTHORED_STYLES[index]))
    if index not in STYLE_PROFILES:
        raise ValueError(_unsupported_style_message(raw))
    return index, copy.deepcopy(STYLE_PROFILES[index])


def parse_template_viewbox(template_type: str) -> Tuple[float, float]:
    template_path = os.path.join(TEMPLATE_DIR, f"{template_type}.svg")
    if os.path.exists(template_path):
        content = open(template_path, "r", encoding="utf-8").read()
        match = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', content)
        if match:
            return float(match.group(1)), float(match.group(2))
    return DEFAULT_VIEWBOX.get(template_type, (960, 600))


def render_defs(style_index: int, style: Dict[str, object]) -> str:
    marker_size = "8" if style_index == 4 else "10"
    marker_height = "6" if style_index == 4 else "7"
    ref_x = "7" if style_index == 4 else "9"
    ref_y = "3" if style_index == 4 else "3.5"
    color_map = style_value(style, "arrow_colors")
    marker_lines = []
    for key, color in color_map.items():
        marker_id = MARKER_IDS.get(key, "arrowA")
        marker_lines.append(
            f'    <marker id="{marker_id}" markerWidth="{marker_size}" markerHeight="{marker_height}" '
            f'refX="{ref_x}" refY="{ref_y}" orient="auto">'
        )
        if style_index == 4:
            marker_lines.append(f'      <polygon points="0 0, 8 3, 0 6" fill="{color}"/>')
        else:
            marker_lines.append(f'      <polygon points="0 0, 10 3.5, 0 7" fill="{color}"/>')
        marker_lines.append("    </marker>")

    filters = []
    if style_value(style, "shadow"):
        filters.extend(
            [
                '    <filter id="shadowSoft" x="-20%" y="-20%" width="140%" height="160%">',
                '      <feDropShadow dx="0" dy="3" stdDeviation="6" flood-color="#0f172a" flood-opacity="0.12"/>',
                "    </filter>",
                '    <filter id="shadowGlass" x="-20%" y="-20%" width="140%" height="160%">',
                '      <feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="#020617" flood-opacity="0.28"/>',
                "    </filter>",
            ]
        )

    if style_index == 3:
        filters.extend(
            [
                '    <pattern id="blueprintGrid" width="32" height="32" patternUnits="userSpaceOnUse">',
                '      <path d="M 32 0 L 0 0 0 32" fill="none" stroke="#0ea5e9" stroke-opacity="0.12" stroke-width="1"/>',
                "    </pattern>",
            ]
        )
    if style_index == 2:
        filters.extend(
            [
                '    <linearGradient id="terminalGradient" x1="0%" y1="0%" x2="100%" y2="100%">',
                '      <stop offset="0%" stop-color="#0f0f1a"/>',
                '      <stop offset="100%" stop-color="#1a1a2e"/>',
                "    </linearGradient>",
                '    <filter id="glowBlue" x="-30%" y="-30%" width="160%" height="160%">',
                '      <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#3b82f6" flood-opacity="0.65"/>',
                "    </filter>",
                '    <filter id="glowPurple" x="-30%" y="-30%" width="160%" height="160%">',
                '      <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#a855f7" flood-opacity="0.72"/>',
                "    </filter>",
                '    <filter id="glowGreen" x="-30%" y="-30%" width="160%" height="160%">',
                '      <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#22c55e" flood-opacity="0.62"/>',
                "    </filter>",
                '    <filter id="glowOrange" x="-30%" y="-30%" width="160%" height="160%">',
                '      <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#f97316" flood-opacity="0.62"/>',
                "    </filter>",
            ]
        )

    styles = [
        f"    text {{ font-family: {style_value(style, 'font_family')}; }}",
        f"    .title {{ font-size: {style_value(style, 'title_size')}px; font-weight: 700; fill: {style_value(style, 'title_fill')}; }}",
        f"    .subtitle {{ font-size: {style_value(style, 'subtitle_size')}px; font-weight: 500; fill: {style_value(style, 'subtitle_fill')}; }}",
        f"    .section {{ font-size: 13px; font-weight: 700; fill: {style_value(style, 'section_label_fill')}; letter-spacing: 1.4px; }}",
        f"    .section-sub {{ font-size: 12px; font-weight: 500; fill: {style_value(style, 'section_sub_fill')}; }}",
        f"    .node-title {{ font-size: 18px; font-weight: 700; fill: {style_value(style, 'text_primary')}; }}",
        f"    .node-sub {{ font-size: 12px; font-weight: 500; fill: {style_value(style, 'text_secondary')}; }}",
        f"    .node-type {{ font-size: {style_value(style, 'type_label_size')}px; font-weight: 700; fill: {style_value(style, 'type_label_fill')}; letter-spacing: 0.08em; }}",
        f"    .arrow-label {{ font-size: 12px; font-weight: 600; fill: {style_value(style, 'arrow_label_fill')}; }}",
        f"    .legend {{ font-size: 12px; font-weight: 500; fill: {style_value(style, 'legend_fill')}; }}",
        f"    .footnote {{ font-size: 12px; font-weight: 500; fill: {style_value(style, 'text_muted')}; }}",
    ]
    return "\n".join(
        ["  <defs>"] + marker_lines + filters + ["    <style>"] + styles + ["    </style>", "  </defs>"]
    )


def render_canvas(style_index: int, style: Dict[str, object], width: float, height: float) -> str:
    background = str(style_value(style, "background"))
    if style_index == 2:
        parts = [f'  <rect width="{width}" height="{height}" fill="url(#terminalGradient)"/>']
    else:
        parts = [f'  <rect width="{width}" height="{height}" fill="{background}"/>']

    return "\n".join(parts)


def title_position(style: Dict[str, object], width: float) -> Tuple[float, str]:
    if style_value(style, "title_align") == "left":
        return 48.0, "start"
    return width / 2.0, "middle"


def render_title_block(style: Dict[str, object], data: Dict[str, object], width: float) -> Tuple[str, float]:
    title = normalize_text(data.get("title", "Diagram"))
    subtitle = normalize_text(data.get("subtitle", ""))
    x, anchor = title_position(style, width)
    if anchor == "middle":
        parts = [f'  <text x="{x}" y="56" text-anchor="{anchor}" class="title">{title}</text>']
        cursor_y = 82
        if subtitle:
            parts.append(f'  <text x="{x}" y="{cursor_y}" text-anchor="{anchor}" class="subtitle">{subtitle}</text>')
            cursor_y += 24
        return "\n".join(parts), cursor_y + 10

    parts = [f'  <text x="{x}" y="48" text-anchor="{anchor}" class="title">{title}</text>']
    cursor_y = 72
    if subtitle:
        parts.append(f'  <text x="{x}" y="{cursor_y}" text-anchor="{anchor}" class="subtitle">{subtitle}</text>')
        cursor_y += 18
    if style_value(style, "title_divider"):
        parts.append(
            f'  <line x1="48" y1="{cursor_y + 10}" x2="{width - 48}" y2="{cursor_y + 10}" '
            f'stroke="{style_value(style, "section_stroke")}" stroke-width="1"/>'
        )
        cursor_y += 26
    return "\n".join(parts), cursor_y + 8


def render_window_controls(data: Dict[str, object], style_index: int, width: float) -> str:
    controls = data.get("window_controls")
    if not controls:
        return ""
    if controls is True:
        controls = ["#ef4444", "#f59e0b", "#10b981"]
    if style_index != 2:
        return ""
    cursor_x = 20.0
    lines = []
    for color in controls:
        lines.append(f'  <circle cx="{cursor_x}" cy="20" r="5.5" fill="{color}"/>')
        cursor_x += 18
    return "\n".join(lines)


def render_header_meta(data: Dict[str, object], style: Dict[str, object], width: float) -> str:
    meta_left = normalize_text(data.get("meta_left", ""))
    meta_center = normalize_text(data.get("meta_center", ""))
    meta_right = normalize_text(data.get("meta_right", ""))
    if not any([meta_left, meta_center, meta_right]):
        return ""
    fill = str(data.get("meta_fill", style_value(style, "text_muted")))
    size = to_float(data.get("meta_size", 11))
    lines = []
    if meta_left:
        lines.append(f'  <text x="28" y="24" font-size="{size}" font-weight="600" fill="{fill}">{meta_left}</text>')
    if meta_center:
        lines.append(f'  <text x="{width / 2}" y="24" text-anchor="middle" font-size="{size}" font-weight="600" fill="{fill}">{meta_center}</text>')
    if meta_right:
        lines.append(f'  <text x="{width - 28}" y="24" text-anchor="end" font-size="{size}" font-weight="600" fill="{fill}">{meta_right}</text>')
    return "\n".join(lines)


def render_blueprint_title_block(
    data: Dict[str, object],
    style: Dict[str, object],
    style_index: int,
    width: float,
    height: float,
) -> Tuple[str, Optional[Bounds]]:
    if style_index != 3:
        return "", None
    block = data.get("blueprint_title_block")
    if not block:
        return "", None
    block_width = to_float(block.get("width", 256))
    block_height = to_float(block.get("height", 92))
    x = to_float(block.get("x", width - block_width - 28))
    y = to_float(block.get("y", height - block_height - 18))
    title = normalize_text(block.get("title", data.get("title", "")))
    subtitle = normalize_text(block.get("subtitle", "SYSTEM ARCHITECTURE"))
    left_caption = normalize_text(block.get("left_caption", "REV: 1.0"))
    center_caption = normalize_text(block.get("center_caption", "AUTO-GENERATED"))
    right_caption = normalize_text(block.get("right_caption", "DWG: ARCH-001"))
    stroke = str(block.get("stroke", style_value(style, "section_stroke")))
    fill = str(block.get("fill", "#0b3552"))
    title_fill = str(block.get("title_fill", style_value(style, "text_primary")))
    sub_fill = str(block.get("subtitle_fill", style_value(style, "section_label_fill")))
    muted_fill = str(block.get("muted_fill", style_value(style, "text_muted")))
    lines = [
        f'  <rect x="{x}" y="{y}" width="{block_width}" height="{block_height}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>',
        f'  <line x1="{x}" y1="{y + 18}" x2="{x + block_width}" y2="{y + 18}" stroke="{stroke}" stroke-width="1"/>',
        f'  <line x1="{x}" y1="{y + 54}" x2="{x + block_width}" y2="{y + 54}" stroke="{stroke}" stroke-width="1"/>',
        f'  <text x="{x + block_width / 2}" y="{y + 13}" text-anchor="middle" font-size="10" font-weight="600" fill="{muted_fill}">{subtitle}</text>',
        f'  <text x="{x + block_width / 2}" y="{y + 42}" text-anchor="middle" font-size="18" font-weight="700" fill="{title_fill}">{title}</text>',
        f'  <text x="{x + 12}" y="{y + 75}" font-size="9.5" font-weight="600" fill="{muted_fill}">{left_caption}</text>',
        f'  <text x="{x + block_width / 2}" y="{y + 75}" text-anchor="middle" font-size="9.5" font-weight="600" fill="{sub_fill}">{center_caption}</text>',
        f'  <text x="{x + block_width - 12}" y="{y + 75}" text-anchor="end" font-size="9.5" font-weight="600" fill="{muted_fill}">{right_caption}</text>',
    ]
    return "\n".join(lines), rectangle_bounds(x - 6, y - 6, block_width + 12, block_height + 12)


def infer_shape(kind: str) -> str:
    mapping = {
        "rect": "rect",
        "double_rect": "rect",
        "cylinder": "rect",
        "document": "rect",
        "folder": "rect",
        "terminal": "rect",
        "hexagon": "rect",
        "circle_cluster": "cluster",
        "user_avatar": "rect",
        "bot": "rect",
        "speech": "rect",
        "icon_box": "rect",
        "diamond": "diamond",
        "milestone": "diamond",
        "circle": "circle",
        "ellipse": "ellipse",
        "use-case": "ellipse",
        "actor": "actor",
        "entity": "entity",
        "state": "state",
        "initial": "circle",
        "final": "circle",
        "terminator": "ellipse",
        "participant": "rect",
        "timeline-event": "rect",
        "process": "rect",
        "external-entity": "rect",
        "data-store": "rect",
    }
    return mapping.get(kind, "rect")


def node_bounds(data: Dict[str, object]) -> Bounds:
    kind = str(data.get("kind", data.get("shape", "rect")))
    x = to_float(data.get("x"))
    y = to_float(data.get("y"))
    if kind in {"circle", "initial", "final"} and "r" in data:
        r = to_float(data.get("r"))
        return (x, y, x + 2 * r, y + 2 * r)
    width = to_float(data.get("width", 180))
    height = to_float(data.get("height", 76))
    return (x, y, x + width, y + height)


def union_bounds(bounds: Sequence[Bounds]) -> Optional[Bounds]:
    if not bounds:
        return None
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _text_width(text: object, char_width: float = 9.5, minimum: float = 0.0) -> float:
    raw = str(text or "")
    lines = raw.split("\\n") if "\\n" in raw else raw.split("\n")
    return max(minimum, max((len(line) for line in lines), default=0) * char_width)


def visual_node_bounds(data: Dict[str, object]) -> Bounds:
    left, top, right, bottom = node_bounds(data)
    kind = str(data.get("kind", data.get("shape", "rect")))
    cx = (left + right) / 2
    label_width = max(
        _text_width(data.get("label"), 10.0),
        _text_width(data.get("sublabel"), 7.5),
        _text_width(data.get("type_label"), 7.0),
    )
    if label_width:
        left = min(left, cx - label_width / 2 - 6)
        right = max(right, cx + label_width / 2 + 6)
    if kind in {"document", "folder", "bot", "terminal", "circle_cluster"}:
        bottom += 70 if data.get("tags") else 52
    elif kind in {"actor", "initial", "final"} and data.get("label"):
        bottom += 26 + (18 if data.get("sublabel") else 0)
    elif kind == "speech":
        bottom += 18
    if data.get("tags"):
        tags = data.get("tags", [])
        tags_width = sum(max(62, len(str(tag.get("label", ""))) * 8 + 18) + 8 for tag in tags)
        left = min(left, node_bounds(data)[0] + 12)
        right = max(right, node_bounds(data)[0] + 18 + tags_width)
        bottom = max(bottom, node_bounds(data)[3] + (68 if kind in {"document", "folder", "bot", "terminal", "circle_cluster"} else 2))
    return (left, top, right, bottom)


def explicit_content_bounds(data: Dict[str, object]) -> Optional[Bounds]:
    bounds: List[Bounds] = []
    node_lookup: Dict[str, Bounds] = {}
    for node in data.get("nodes", []):
        item = visual_node_bounds(node)
        bounds.append(item)
        node_lookup[str(node.get("id"))] = node_bounds(node)
    for container in data.get("containers", []):
        x = to_float(container["x"])
        y = to_float(container["y"])
        width = to_float(container["width"])
        height = to_float(container["height"])
        bounds.append(rectangle_bounds(x, y, width, height))
        side_label = str(container.get("side_label", "")).strip()
        if side_label:
            side_x = to_float(container.get("side_label_x", max(28, x - 18)))
            side_y = to_float(container.get("side_label_y", y + height / 2))
            text_width = _text_width(side_label, 8.0, 20)
            anchor = str(container.get("side_label_anchor", "end"))
            if anchor == "start":
                bounds.append((side_x, side_y - 12, side_x + text_width, side_y + 8))
            elif anchor == "middle":
                bounds.append((side_x - text_width / 2, side_y - 12, side_x + text_width / 2, side_y + 8))
            else:
                bounds.append((side_x - text_width, side_y - 12, side_x, side_y + 8))
    for arrow in data.get("arrows", []):
        points: List[Point] = []
        source = arrow.get("source")
        target = arrow.get("target")
        if source in node_lookup:
            s = node_lookup[str(source)]
            points.append(((s[0] + s[2]) / 2, (s[1] + s[3]) / 2))
        else:
            points.append((to_float(arrow.get("x1")), to_float(arrow.get("y1"))))
        for point in arrow.get("route_points", []):
            points.append((to_float(point[0]), to_float(point[1])))
        if target in node_lookup:
            t = node_lookup[str(target)]
            points.append(((t[0] + t[2]) / 2, (t[1] + t[3]) / 2))
        else:
            points.append((to_float(arrow.get("x2")), to_float(arrow.get("y2"))))
        if points:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bounds.append((min(xs) - 8, min(ys) - 8, max(xs) + 12, max(ys) + 12))
            label = str(arrow.get("label", ""))
            if label:
                dx = to_float(arrow.get("label_dx", 0))
                dy = to_float(arrow.get("label_dy", -4))
                label_width = _text_width(label, 7.0, 36) + 16
                bounds.append(
                    (
                        min(xs) + dx - label_width / 2,
                        min(ys) + dy - 20,
                        max(xs) + dx + label_width / 2,
                        max(ys) + dy + 20,
                    )
                )
    if "legend_x" in data or "legend_y" in data:
        legend = data.get("legend", [])
        if legend:
            x = to_float(data.get("legend_x", 42))
            y = to_float(data.get("legend_y", 96))
            max_label = max((_text_width(item.get("label"), 7.0) for item in legend), default=0)
            bounds.append((x - 14, y - 18, x + 52 + max_label, y + len(legend) * 22 + 12))
    if "footer_x" in data or "footer_y" in data:
        text = str(data.get("footer", ""))
        if text:
            x = to_float(data.get("footer_x", 42))
            y = to_float(data.get("footer_y", 0))
            bounds.append((x, y - 14, x + _text_width(text, 7.0, 140), y + 4))
    block = data.get("blueprint_title_block")
    if isinstance(block, dict) and ("x" in block or "y" in block):
        x = to_float(block.get("x", 0))
        y = to_float(block.get("y", 0))
        bounds.append(rectangle_bounds(x - 6, y - 6, to_float(block.get("width", 256)) + 12, to_float(block.get("height", 92)) + 12))
    return union_bounds(bounds)


def translate_content(data: Dict[str, object], dx: float, dy: float) -> None:
    if not dx and not dy:
        return
    for node in data.get("nodes", []):
        node["x"] = to_float(node.get("x")) + dx
        if "y" in node:
            node["y"] = to_float(node.get("y")) + dy
    for container in data.get("containers", []):
        container["x"] = to_float(container.get("x")) + dx
        container["y"] = to_float(container.get("y")) + dy
        if "side_label_x" in container:
            container["side_label_x"] = to_float(container["side_label_x"]) + dx
        if "side_label_y" in container:
            container["side_label_y"] = to_float(container["side_label_y"]) + dy
    for arrow in data.get("arrows", []):
        for field, delta in (("x1", dx), ("x2", dx), ("y1", dy), ("y2", dy)):
            if field in arrow:
                arrow[field] = to_float(arrow[field]) + delta
        if "route_points" in arrow:
            arrow["route_points"] = [
                [to_float(point[0]) + dx, to_float(point[1]) + dy]
                for point in arrow["route_points"]
            ]
        if "corridor_x" in arrow:
            arrow["corridor_x"] = [to_float(value) + dx for value in arrow["corridor_x"]]
        if "corridor_y" in arrow:
            arrow["corridor_y"] = [to_float(value) + dy for value in arrow["corridor_y"]]
    for field, delta in (("legend_x", dx), ("footer_x", dx), ("legend_y", dy), ("footer_y", dy)):
        if field in data:
            data[field] = to_float(data[field]) + delta
    block = data.get("blueprint_title_block")
    if isinstance(block, dict):
        if "x" in block:
            block["x"] = to_float(block["x"]) + dx
        if "y" in block:
            block["y"] = to_float(block["y"]) + dy


def normalize_node(node_data: Dict[str, object], fallback_id: str) -> Node:
    kind = str(node_data.get("kind", node_data.get("shape", "rect")))
    bounds = node_bounds(node_data)
    left, top, right, bottom = bounds
    return Node(
        node_id=str(node_data.get("id", fallback_id)),
        kind=kind,
        shape=infer_shape(kind),
        data=node_data,
        bounds=bounds,
        cx=(left + right) / 2,
        cy=(top + bottom) / 2,
    )


def anchor_on_side(node: Node, side: str) -> Point:
    left, top, right, bottom = node.bounds
    cx, cy = node.cx, node.cy
    side = side.lower()
    if side == "left":
        return (left, cy)
    if side == "right":
        return (right, cy)
    if side == "top":
        return (cx, top)
    if side == "bottom":
        return (cx, bottom)
    if side == "top-left":
        return (left, top)
    if side == "top-right":
        return (right, top)
    if side == "bottom-left":
        return (left, bottom)
    if side == "bottom-right":
        return (right, bottom)
    return (cx, cy)


def anchor_point(node: Node, toward: Point, port: Optional[str] = None) -> Point:
    if port:
        return anchor_on_side(node, port)
    left, top, right, bottom = node.bounds
    dx = toward[0] - node.cx
    dy = toward[1] - node.cy
    width = right - left
    height = bottom - top
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return (right, node.cy)
    if node.shape in {"circle", "ellipse"}:
        rx = max(width / 2, 1e-9)
        ry = max(height / 2, 1e-9)
        scale = 1.0 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
        return (node.cx + dx * scale, node.cy + dy * scale)
    if node.shape == "diamond":
        half_w = max(width / 2, 1e-9)
        half_h = max(height / 2, 1e-9)
        scale = 1.0 / (abs(dx) / half_w + abs(dy) / half_h)
        return (node.cx + dx * scale, node.cy + dy * scale)
    if abs(dx) * height >= abs(dy) * width:
        return (right, node.cy) if dx >= 0 else (left, node.cy)
    return (node.cx, bottom) if dy >= 0 else (node.cx, top)


def expand_bounds(bounds: Bounds, padding: float) -> Bounds:
    left, top, right, bottom = bounds
    return (left - padding, top - padding, right + padding, bottom + padding)


def segment_hits_bounds(p1: Point, p2: Point, bounds: Bounds) -> bool:
    """Return true when any segment (including a diagonal) crosses a box interior.

    Liang-Barsky clipping against a slightly inset rectangle avoids treating a
    route that merely runs along an obstacle border as a collision.
    """
    x1, y1 = p1
    x2, y2 = p2
    left, top, right, bottom = bounds
    eps = 1e-6
    left += eps
    top += eps
    right -= eps
    bottom -= eps
    if left >= right or top >= bottom:
        return False
    dx = x2 - x1
    dy = y2 - y1
    t_min, t_max = 0.0, 1.0
    for p, q in ((-dx, x1 - left), (dx, right - x1), (-dy, y1 - top), (dy, bottom - y1)):
        if abs(p) < eps:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            t_min = max(t_min, ratio)
        else:
            t_max = min(t_max, ratio)
        if t_min > t_max:
            return False
    return t_max - t_min > eps


def segment_axis(p1: Point, p2: Point) -> str:
    if abs(p1[1] - p2[1]) < 1e-6:
        return "horizontal"
    if abs(p1[0] - p2[0]) < 1e-6:
        return "vertical"
    return "other"


def port_axis(port: Optional[str]) -> Optional[str]:
    if not port:
        return None
    port = port.lower()
    if port in {"left", "right"}:
        return "horizontal"
    if port in {"top", "bottom"}:
        return "vertical"
    return None


def offset_point(point: Point, port: Optional[str], distance: float) -> Point:
    if not port:
        return point
    x, y = point
    port = port.lower()
    if port == "left":
        return (x - distance, y)
    if port == "right":
        return (x + distance, y)
    if port == "top":
        return (x, y - distance)
    if port == "bottom":
        return (x, y + distance)
    return point


def route_length(points: Sequence[Point]) -> float:
    return sum(abs(x1 - x2) + abs(y1 - y2) for (x1, y1), (x2, y2) in zip(points, points[1:]))


def route_uses_lane(points: Sequence[Point], value: float, axis: str, tolerance: float = 1.0) -> bool:
    if axis == "x":
        return any(abs(x - value) <= tolerance for x, _ in points)
    return any(abs(y - value) <= tolerance for _, y in points)


def collision_count(points: Sequence[Point], obstacles: Sequence[Bounds]) -> int:
    """Count how many (segment, obstacle) pairs collide."""
    return sum(
        1
        for p1, p2 in zip(points, points[1:])
        for obs in obstacles
        if segment_hits_bounds(p1, p2, obs)
    )


def route_is_orthogonal(points: Sequence[Point]) -> bool:
    return all(segment_axis(p1, p2) != "other" for p1, p2 in zip(points, points[1:]))


def route_score(
    points: Sequence[Point],
    hint_x: Sequence[float],
    hint_y: Sequence[float],
    source_port: Optional[str],
    target_port: Optional[str],
) -> float:
    length = route_length(points)
    bends = max(0, len(points) - 2)
    score = length + bends * 22
    if len(points) >= 2 and source_port:
        first_axis = segment_axis(points[0], points[1])
        if first_axis != port_axis(source_port):
            score += 180
    if len(points) >= 2 and target_port:
        last_axis = segment_axis(points[-2], points[-1])
        if last_axis != port_axis(target_port):
            score += 180
    for lane in hint_x:
        score -= 28 if route_uses_lane(points, lane, "x") else 0
    for lane in hint_y:
        score -= 28 if route_uses_lane(points, lane, "y") else 0
    return score


def simplify_points(points: Sequence[Point]) -> List[Point]:
    simplified: List[Point] = []
    for x, y in points:
        pt = (round(x, 2), round(y, 2))
        if simplified and pt == simplified[-1]:
            continue
        simplified.append(pt)

    collapsed: List[Point] = []
    for point in simplified:
        if len(collapsed) < 2:
            collapsed.append(point)
            continue
        x0, y0 = collapsed[-2]
        x1, y1 = collapsed[-1]
        x2, y2 = point
        if (x0 == x1 == x2) or (y0 == y1 == y2):
            collapsed[-1] = point
        else:
            collapsed.append(point)
    return collapsed


def orthogonalize_points(points: Sequence[Point], obstacles: Sequence[Bounds]) -> List[Point]:
    """Convert every diagonal hop to the safer of its two orthogonal elbows."""
    if not points:
        return []
    result: List[Point] = [points[0]]
    for end in points[1:]:
        start = result[-1]
        if segment_axis(start, end) != "other":
            result.append(end)
            continue
        elbow_xy = (end[0], start[1])
        elbow_yx = (start[0], end[1])
        options = ([start, elbow_xy, end], [start, elbow_yx, end])
        best = min(
            options,
            key=lambda option: (
                collision_count(option, obstacles),
                route_length(option),
            ),
        )
        result.extend(best[1:])
    return simplify_points(result)


def route_collides(points: Sequence[Point], obstacles: Sequence[Bounds]) -> bool:
    return collision_count(points, obstacles) > 0


def build_orthogonal_route(
    start: Point,
    end: Point,
    obstacles: Sequence[Bounds],
    arrow_data: Dict[str, object],
) -> List[Point]:
    if arrow_data.get("route_points"):
        raw_points = [tuple(point) for point in arrow_data["route_points"]]
        manual = orthogonalize_points(
            [start] + [(float(x), float(y)) for x, y in raw_points] + [end],
            obstacles,
        )
        if not route_collides(manual, obstacles):
            return manual
        # A stale/manual waypoint that now crosses a node must not silently
        # produce a broken diagram. Fall through to the automatic router.

    sx, sy = start
    ex, ey = end
    routing_padding = to_float(arrow_data.get("routing_padding", 24))
    port_clearance = to_float(arrow_data.get("port_clearance", max(18, routing_padding * 0.85)))
    source_port = str(arrow_data.get("source_port", "")).strip().lower() or None
    target_port = str(arrow_data.get("target_port", "")).strip().lower() or None
    inner_start = offset_point(start, source_port, port_clearance)
    inner_end = offset_point(end, target_port, port_clearance)
    ssx, ssy = inner_start
    eex, eey = inner_end
    expanded = [expand_bounds(bounds, routing_padding) for bounds in obstacles]
    hint_x = [to_float(value) for value in arrow_data.get("corridor_x", [])]
    hint_y = [to_float(value) for value in arrow_data.get("corridor_y", [])]
    lane_x = sorted({ssx, eex, round((ssx + eex) / 2, 2), *hint_x, *[b[0] for b in expanded], *[b[2] for b in expanded]})
    lane_y = sorted({ssy, eey, round((ssy + eey) / 2, 2), *hint_y, *[b[1] for b in expanded], *[b[3] for b in expanded]})
    if expanded:
        left_rail = min(b[0] for b in expanded) - 24
        right_rail = max(b[2] for b in expanded) + 24
        top_rail = min(b[1] for b in expanded) - 24
        bottom_rail = max(b[3] for b in expanded) + 24
    else:
        left_rail = min(ssx, eex) - 48
        right_rail = max(ssx, eex) + 48
        top_rail = min(ssy, eey) - 48
        bottom_rail = max(ssy, eey) + 48

    candidates = [
        [start, inner_start, inner_end, end],
        [start, inner_start, (eex, ssy), inner_end, end],
        [start, inner_start, (ssx, eey), inner_end, end],
        [start, inner_start, ((ssx + eex) / 2, ssy), ((ssx + eex) / 2, eey), inner_end, end],
        [start, inner_start, (ssx, (ssy + eey) / 2), (eex, (ssy + eey) / 2), inner_end, end],
        [start, inner_start, (left_rail, ssy), (left_rail, eey), inner_end, end],
        [start, inner_start, (right_rail, ssy), (right_rail, eey), inner_end, end],
        [start, inner_start, (ssx, top_rail), (eex, top_rail), inner_end, end],
        [start, inner_start, (ssx, bottom_rail), (eex, bottom_rail), inner_end, end],
    ]
    for x in lane_x:
        candidates.append([start, inner_start, (x, ssy), (x, eey), inner_end, end])
    for y in lane_y:
        candidates.append([start, inner_start, (ssx, y), (eex, y), inner_end, end])
    for x in hint_x:
        for y in hint_y:
            candidates.append([start, inner_start, (x, ssy), (x, y), (eex, y), inner_end, end])

    default_route = simplify_points([start, inner_start, (eex, ssy), inner_end, end])
    default_coll = collision_count(default_route, expanded)
    default_raw_coll = collision_count(default_route, obstacles)
    default_length = route_length(default_route)
    best_route: Optional[List[Point]] = None
    best_score = float("inf")
    best_fallback: Optional[List[Point]] = None
    best_fb_coll = float("inf")
    best_fb_score = float("inf")
    for candidate in candidates:
        simplified = simplify_points(candidate)
        coll = collision_count(simplified, expanded)
        score = route_score(simplified, hint_x, hint_y, source_port, target_port)
        if coll == 0 and route_is_orthogonal(simplified):
            if score < best_score:
                best_score = score
                best_route = simplified
        elif route_is_orthogonal(simplified):
            length = route_length(simplified)
            raw_coll = collision_count(simplified, obstacles)
            if (
                coll < default_coll
                and raw_coll <= default_raw_coll
                and length <= default_length
                and (coll < best_fb_coll or (coll == best_fb_coll and score < best_fb_score))
            ):
                best_fb_coll = coll
                best_fb_score = score
                best_fallback = simplified

    if best_route is not None:
        return best_route
    if best_fallback is not None:
        return best_fallback
    return default_route


def choose_label_position(points: Sequence[Point]) -> Point:
    segments = list(zip(points, points[1:]))
    if not segments:
        return points[0]
    best = max(segments, key=lambda seg: abs(seg[0][0] - seg[1][0]) + abs(seg[0][1] - seg[1][1]))
    return ((best[0][0] + best[1][0]) / 2, (best[0][1] + best[1][1]) / 2)


def color_for_flow(style: Dict[str, object], arrow_data: Dict[str, object]) -> str:
    if arrow_data.get("color"):
        return str(arrow_data["color"])
    flow = FLOW_ALIASES.get(str(arrow_data.get("flow", "control")).lower(), "control")
    return str(style_value(style, "arrow_colors")[flow])


def marker_for_color(style: Dict[str, object], color: str, arrow_data: Dict[str, object]) -> str:
    if arrow_data.get("marker"):
        return f"url(#{arrow_data['marker']})"
    colors = style_value(style, "arrow_colors")
    for name, token in colors.items():
        if token == color:
            return f"url(#{MARKER_IDS.get(name, 'arrowA')})"
    return "url(#arrowA)"


def render_label_badge(x: float, y: float, text: str, style: Dict[str, object], label_style: str = "offset") -> str:
    raw_str = str(text)
    lines = raw_str.split('\\n') if '\\n' in raw_str else raw_str.split('\n')
    max_line_len = max((len(line) for line in lines), default=0)
    width = max(36, max_line_len * 7 + 14)
    height = len(lines) * 16 + 4

    parts: List[str] = []
    if label_style == "badge":
        bg = style_value(style, "arrow_label_bg")
        opacity = style_value(style, "arrow_label_opacity")
        parts.append(f'  <rect x="{round(x - width / 2, 2)}" y="{round(y - height / 2 + 2, 2)}" width="{width}" height="{height}" rx="6" fill="{bg}" opacity="{opacity}"/>')

    parts.append(render_multiline_text(text, round(x, 2), round(y + 4, 2), "middle", "arrow-label", 14))
    return "\n".join(parts)


def rectangle_bounds(x: float, y: float, width: float, height: float) -> Bounds:
    return (x, y, x + width, y + height)


def bounds_intersect(a: Bounds, b: Bounds, padding: float = 0.0) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (
        ax2 + padding <= bx1
        or bx2 + padding <= ax1
        or ay2 + padding <= by1
        or by2 + padding <= ay1
    )


def estimate_label_bounds(x: float, y: float, text: str) -> Bounds:
    width = max(36, len(text) * 7 + 14)
    return rectangle_bounds(x - width / 2, y - 10, width, 20)


def section_header_text(container: Dict[str, object], style: Dict[str, object]) -> str:
    if container.get("header_text"):
        text = str(container.get("header_text", ""))
    else:
        label = str(container.get("label", ""))
        prefix = str(container.get("header_prefix", "")).strip()
        separator = str(container.get("header_separator", " // " if prefix else ""))
        text = f"{prefix}{separator}{label}" if prefix else label
    if style_value(style, "section_upper") and not container.get("preserve_case"):
        text = text.upper()
    return text


def render_section(container: Dict[str, object], style: Dict[str, object]) -> str:
    x = to_float(container["x"])
    y = to_float(container["y"])
    width = to_float(container["width"])
    height = to_float(container["height"])
    rx = to_float(container.get("rx", 16 if style_value(style, "name") != "Notion Clean" else 4))
    fill = str(container.get("fill", style_value(style, "section_fill")))
    stroke = str(container.get("stroke", style_value(style, "section_stroke")))
    dash = str(container.get("stroke_dasharray", style_value(style, "section_dash")))
    label = section_header_text(container, style)
    subtitle = str(container.get("subtitle", ""))
    side_label = str(container.get("side_label", "")).strip()
    side_label_fill = str(container.get("side_label_fill", style_value(style, "text_secondary")))
    side_label_size = to_float(container.get("side_label_size", 14))
    side_label_weight = str(container.get("side_label_weight", "600"))
    side_label_anchor = str(container.get("side_label_anchor", "end"))
    lines = [f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"']
    if dash:
        lines[-1] += f' stroke-dasharray="{dash}"'
    lines[-1] += "/>"
    if label:
        lines.append(f'  <text x="{x + 18}" y="{y + 24}" class="section">{normalize_text(label)}</text>')
    if subtitle:
        lines.append(f'  <text x="{x + 18}" y="{y + 44}" class="section-sub">{normalize_text(subtitle)}</text>')
    if side_label:
        side_x = to_float(container.get("side_label_x", max(28, x - 18)))
        side_y = to_float(container.get("side_label_y", y + height / 2))
        lines.append(
            f'  <text x="{side_x}" y="{side_y}" text-anchor="{side_label_anchor}" dominant-baseline="middle" '
            f'font-size="{side_label_size}" font-weight="{side_label_weight}" fill="{side_label_fill}">{normalize_text(side_label)}</text>'
        )
    return "\n".join(lines)


def container_header_bounds(container: Dict[str, object]) -> Optional[Bounds]:
    label = str(container.get("header_text", "") or container.get("label", "")).strip()
    subtitle = str(container.get("subtitle", "")).strip()
    if not label and not subtitle:
        return None
    x = to_float(container["x"])
    y = to_float(container["y"])
    width = to_float(container["width"])
    header_height = to_float(container.get("header_height", 54 if subtitle else 30))
    return rectangle_bounds(x + 6, y + 6, width - 12, header_height)


def label_position_candidates(points: Sequence[Point]) -> List[Point]:
    segments = list(zip(points, points[1:]))
    if not segments:
        return [points[0]]
    ranked_segments = sorted(
        segments,
        key=lambda seg: abs(seg[0][0] - seg[1][0]) + abs(seg[0][1] - seg[1][1]),
        reverse=True,
    )
    candidates: List[Point] = []
    for (x1, y1), (x2, y2) in ranked_segments:
        length = abs(x1 - x2) + abs(y1 - y2)
        if length < 34:
            continue
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        if abs(y1 - y2) < 1e-6:
            candidates.extend([(mx, my - 16), (mx, my + 16), (mx, my - 28), (mx, my + 28), (mx, my)])
        elif abs(x1 - x2) < 1e-6:
            candidates.extend([(mx - 18, my), (mx + 18, my), (mx - 30, my), (mx + 30, my), (mx, my)])
        else:
            candidates.extend([(mx, my - 16), (mx, my + 16), (mx, my)])
    return candidates or [choose_label_position(points)]


def choose_label_position_avoiding(points: Sequence[Point], text: str, occupied: Sequence[Bounds]) -> Point:
    for candidate in label_position_candidates(points):
        label_box = estimate_label_bounds(candidate[0], candidate[1], text)
        if not any(bounds_intersect(label_box, other, 4) for other in occupied):
            return candidate
    return choose_label_position(points)


def legend_layout(data: Dict[str, object], legend: Sequence[Dict[str, object]], width: float, height: float) -> Optional[Tuple[float, float, Bounds]]:
    if not legend:
        return None
    x = to_float(data.get("legend_x", 42))
    y = to_float(data.get("legend_y", height - (len(legend) * 22 + 34)))
    position = str(data.get("legend_position", "bottom-left"))
    max_label = max((len(str(item.get("label", ""))) for item in legend), default=12)
    block_width = 40 + max_label * 7 + 12
    block_height = len(legend) * 22 + 6
    if position == "bottom-right":
        x = to_float(data.get("legend_x", width - block_width - 42))
    elif position == "top-right":
        x = to_float(data.get("legend_x", width - block_width - 42))
        y = to_float(data.get("legend_y", 96))
    elif position == "top-left":
        x = to_float(data.get("legend_x", 42))
        y = to_float(data.get("legend_y", 96))
    return (x, y, rectangle_bounds(x - 4, y - 10, block_width + 8, block_height + 12))


def footer_layout(data: Dict[str, object], width: float, height: float) -> Optional[Tuple[float, float, Bounds]]:
    text = str(data.get("footer", "")).strip()
    if not text:
        return None
    footer_width = max(140, len(text) * 7)
    x = to_float(data.get("footer_x", 42))
    y = to_float(data.get("footer_y", height - 16))
    position = str(data.get("footer_position", "bottom-left"))
    if position == "bottom-right":
        x = to_float(data.get("footer_x", width - footer_width - 42))
    return (x, y, rectangle_bounds(x, y - 12, footer_width, 16))


def render_tags(node: Dict[str, object], x: float, y: float, style: Dict[str, object]) -> List[str]:
    tags = node.get("tags", [])
    if not tags:
        return []
    cursor_x = x
    lines = []
    for tag in tags:
        label = normalize_text(tag.get("label", ""))
        width = max(62, len(str(tag.get("label", ""))) * 8 + 18)
        fill = tag.get("fill", "#eff6ff")
        stroke = tag.get("stroke", "#bfdbfe")
        text_fill = tag.get("text_fill", style_value(style, "arrow_colors")["read"])
        lines.append(
            f'  <rect x="{cursor_x}" y="{y}" width="{width}" height="16" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        )
        lines.append(
            f'  <text x="{cursor_x + width / 2}" y="{y + 11.5}" text-anchor="middle" font-size="11" font-weight="500" fill="{text_fill}">{label}</text>'
        )
        cursor_x += width + 8
    return lines


def render_rect_node(node: Dict[str, object], style: Dict[str, object], kind: str) -> str:
    x = to_float(node["x"])
    y = to_float(node["y"])
    width = to_float(node.get("width", 180))
    height = to_float(node.get("height", 76))
    rx = to_float(node.get("rx", style_value(style, "node_radius")))
    fill = str(node.get("fill", style_value(style, "node_fill")))
    stroke = str(node.get("stroke", style_value(style, "node_stroke")))
    stroke_width = to_float(node.get("stroke_width", 2.0 if kind != "rect" else 1.8))
    filter_attr = ""
    node_shadow = node.get("filter")
    if node_shadow:
        filter_attr = f' filter="url(#{node_shadow})"'
    elif node.get("glow"):
        glow_name = str(node.get("glow"))
        glow_map = {
            "blue": "glowBlue",
            "purple": "glowPurple",
            "green": "glowGreen",
            "orange": "glowOrange",
        }
        if glow_name in glow_map:
            filter_attr = f' filter="url(#{glow_map[glow_name]})"'
    elif style_value(style, "node_shadow"):
        if not node.get("flat", False):
            filter_attr = f' filter="{style_value(style, "node_shadow")}"'
    # Keep multiline content raw here; render_multiline_text performs the one
    # and only XML escaping pass for each line.
    title = str(node.get("label", ""))
    subtitle = str(node.get("sublabel", ""))
    type_label = normalize_text(node.get("type_label", ""))
    accent_fill = node.get("accent_fill")
    lines = []

    if kind == "double_rect":
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>'
        )
        lines.append(
            f'  <rect x="{x + 6}" y="{y + 6}" width="{width - 12}" height="{height - 12}" rx="{max(rx - 3, 4)}" fill="none" stroke="{stroke}" stroke-width="1.2" opacity="0.65"/>'
        )
    elif kind == "terminal":
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>'
        )
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="18" rx="{rx}" fill="{node.get("header_fill", "#1f2937")}" opacity="0.95"/>'
        )
        header_colors = node.get("header_dots", ["#ef4444", "#f59e0b", "#10b981"])
        for idx, color in enumerate(header_colors):
            lines.append(f'  <circle cx="{x + 16 + idx * 14}" cy="{y + 9}" r="4" fill="{color}"/>')
        lines.append(
            f'  <text x="{x + 18}" y="{y + 44}" font-size="28" font-weight="700" fill="{node.get("prompt_fill", "#10b981")}">$</text>'
        )
        lines.append(
            f'  <text x="{x + 38}" y="{y + 44}" font-size="22" font-weight="500" fill="{style_value(style, "text_secondary")}">_</text>'
        )
    elif kind == "document":
        fold = min(18, width * 0.18, height * 0.22)
        path = (
            f"M {x} {y} L {x + width - fold} {y} L {x + width} {y + fold} "
            f"L {x + width} {y + height} L {x} {y + height} Z"
        )
        lines.append(
            f'  <path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>'
        )
        lines.append(
            f'  <path d="M {x + width - fold} {y} L {x + width - fold} {y + fold} L {x + width} {y + fold}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        for idx in range(4):
            line_y = y + 26 + idx * 14
            lines.append(
                f'  <line x1="{x + 18}" y1="{line_y}" x2="{x + width - 28}" y2="{line_y}" stroke="{node.get("line_stroke", "#c4b5fd")}" stroke-width="1.2"/>'
            )
    elif kind == "folder":
        tab_w = min(54, width * 0.34)
        tab_h = 18
        path = (
            f"M {x} {y + tab_h} L {x + tab_w * 0.4} {y + tab_h} L {x + tab_w * 0.58} {y} "
            f"L {x + tab_w} {y} L {x + width} {y} L {x + width} {y + height} L {x} {y + height} Z"
        )
        lines.append(
            f'  <path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>'
        )
        for idx in range(3):
            line_y = y + 42 + idx * 14
            lines.append(
                f'  <line x1="{x + 22}" y1="{line_y}" x2="{x + width - 22}" y2="{line_y}" stroke="{node.get("line_stroke", stroke)}" stroke-opacity="0.35" stroke-width="1.2"/>'
            )
    elif kind == "hexagon":
        inset = 22
        path = (
            f"M {x + inset} {y} L {x + width - inset} {y} L {x + width} {y + height / 2} "
            f"L {x + width - inset} {y + height} L {x + inset} {y + height} L {x} {y + height / 2} Z"
        )
        lines.append(f'  <path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>')
    elif kind == "speech":
        tail = 18
        path = (
            f"M {x + rx} {y} L {x + width - rx} {y} Q {x + width} {y} {x + width} {y + rx} "
            f"L {x + width} {y + height - rx} Q {x + width} {y + height} {x + width - rx} {y + height} "
            f"L {x + 26} {y + height} L {x + 12} {y + height + tail} L {x + 16} {y + height} "
            f"L {x + rx} {y + height} Q {x} {y + height} {x} {y + height - rx} "
            f"L {x} {y + rx} Q {x} {y} {x + rx} {y} Z"
        )
        lines.append(f'  <path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>')
    else:
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{filter_attr}/>'
        )

    if accent_fill and kind == "icon_box":
        lines.append(
            f'  <rect x="{x + 12}" y="{y + 12}" width="{width - 24}" height="{height - 24}" rx="{max(rx - 4, 4)}" fill="{accent_fill}" opacity="0.9"/>'
        )

    if kind == "user_avatar":
        circle_fill = node.get("icon_fill", "#dbeafe")
        icon_stroke = node.get("icon_stroke", stroke)
        cx = x + 26
        cy = y + height / 2
        lines.append(f'  <circle cx="{cx}" cy="{cy}" r="18" fill="{circle_fill}" stroke="{icon_stroke}" stroke-width="1.6"/>')
        lines.append(f'  <circle cx="{cx}" cy="{cy - 6}" r="5" fill="{icon_stroke}"/>')
        lines.append(f'  <path d="M {cx - 10} {cy + 11} Q {cx} {cy + 2} {cx + 10} {cy + 11}" fill="none" stroke="{icon_stroke}" stroke-width="2"/>')

    if kind == "bot":
        cx = x + width / 2
        cy = y + height / 2 + 2
        body_fill = node.get("body_fill", "#1e293b")
        accent = node.get("accent_fill", "#34d399")
        lines.append(f'  <rect x="{cx - 42}" y="{cy - 32}" width="84" height="84" rx="18" fill="{body_fill}" stroke="#334155" stroke-width="1.8"{filter_attr}/>')
        lines.append(f'  <rect x="{cx - 26}" y="{cy - 16}" width="52" height="22" rx="6" fill="#0f172a" stroke="#475569" stroke-width="1.2"/>')
        lines.append(f'  <circle cx="{cx - 12}" cy="{cy - 5}" r="5" fill="{accent}"/>')
        lines.append(f'  <circle cx="{cx + 12}" cy="{cy - 5}" r="5" fill="{accent}"/>')
        lines.append(f'  <rect x="{cx - 14}" y="{cy + 14}" width="28" height="6" rx="3" fill="#334155"/>')
        lines.append(f'  <line x1="{cx}" y1="{cy - 36}" x2="{cx}" y2="{cy - 50}" stroke="{accent}" stroke-width="3"/>')
        lines.append(f'  <circle cx="{cx}" cy="{cy - 54}" r="5" fill="{accent}"/>')

    if kind == "circle_cluster":
        r = min(width, height) / 4.0
        centers = [(x + width * 0.36, y + height * 0.56), (x + width * 0.58, y + height * 0.45), (x + width * 0.74, y + height * 0.58)]
        for cx, cy in centers:
            lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>')

    type_offset = y + 18 if kind not in {"terminal", "bot"} else y + 18
    title_y = y + height / 2 - (4 if type_label and kind not in {"terminal", "bot"} else 0)
    if kind in {"document", "folder"}:
        title_y = y + height + 26
    elif kind == "circle_cluster":
        title_y = y + height / 2 + 8
    elif kind == "bot":
        title_y = y + height + 22
    elif kind == "user_avatar":
        title_y = y + height / 2 + 6

    if type_label:
        lines.append(f'  <text x="{x + (54 if kind == "user_avatar" else width / 2)}" y="{type_offset}" text-anchor="middle" class="node-type">{type_label}</text>')
        title_y += 10 if kind not in {"document", "folder", "circle_cluster", "bot"} else 0

    title_x = x + width / 2
    text_anchor = "middle"
    if kind == "user_avatar":
        title_x = x + 64
        text_anchor = "start"
    if kind == "terminal":
        title_y = y + height - 14
    if kind == "bot":
        title_x = x + width / 2
        text_anchor = "middle"
    lines.append(render_multiline_text(title, title_x, title_y, text_anchor, "node-title", 18))

    if subtitle:
        sub_y = title_y + 22
        if kind == "document":
            sub_y = y + height + 44
            title_y = y + height + 24
        if kind == "folder":
            sub_y = y + height + 44
        if kind == "circle_cluster":
            sub_y = y + height / 2 + 28
        if kind == "bot":
            sub_y = y + height + 42
        if kind == "terminal":
            sub_y = y + height + 20
        if kind == "user_avatar":
            sub_y = title_y + 22
        lines.append(render_multiline_text(subtitle, title_x, sub_y, text_anchor, "node-sub", 14))

    tag_lines = []
    if node.get("tags"):
        tag_x = x + 18
        tag_y = y + height - 20
        if kind in {"document", "folder", "circle_cluster", "bot", "terminal"}:
            tag_y = y + height + 52
        tag_lines = render_tags(node, tag_x, tag_y, style)
    lines.extend(tag_lines)

    return "\n".join(lines)


def render_semantic_node(node: Dict[str, object], style: Dict[str, object], kind: str) -> str:
    """Render diagram-semantic shapes instead of flattening them to rectangles."""
    x = to_float(node["x"])
    y = to_float(node["y"])
    width = to_float(node.get("width", 100 if kind in {"circle", "initial", "final"} else 180))
    height = to_float(node.get("height", 100 if kind in {"circle", "initial", "final"} else 76))
    if "r" in node and kind in {"circle", "initial", "final"}:
        width = height = 2 * to_float(node["r"])
    fill = str(node.get("fill", style_value(style, "node_fill")))
    stroke = str(node.get("stroke", style_value(style, "node_stroke")))
    stroke_width = to_float(node.get("stroke_width", 1.8))
    label = str(node.get("label", ""))
    subtitle = str(node.get("sublabel", ""))
    cx = x + width / 2
    cy = y + height / 2
    lines: List[str] = []

    if kind in {"diamond", "milestone"}:
        points = f"{cx},{y} {x + width},{cy} {cx},{y + height} {x},{cy}"
        lines.append(
            f'  <polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
    elif kind == "circle":
        lines.append(
            f'  <ellipse cx="{cx}" cy="{cy}" rx="{width / 2}" ry="{height / 2}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
    elif kind in {"ellipse", "use-case"}:
        lines.append(
            f'  <ellipse cx="{cx}" cy="{cy}" rx="{width / 2}" ry="{height / 2}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
    elif kind == "terminator":
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{height / 2}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
    elif kind == "actor":
        head_r = min(width * 0.13, height * 0.13, 16)
        head_y = y + head_r + 2
        body_top = head_y + head_r
        body_bottom = y + height * 0.7
        arm_y = y + height * 0.42
        lines.extend(
            [
                f'  <circle cx="{cx}" cy="{head_y}" r="{head_r}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
                f'  <line x1="{cx}" y1="{body_top}" x2="{cx}" y2="{body_bottom}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
                f'  <line x1="{x + width * 0.22}" y1="{arm_y}" x2="{x + width * 0.78}" y2="{arm_y}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
                f'  <line x1="{cx}" y1="{body_bottom}" x2="{x + width * 0.25}" y2="{y + height * 0.9}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
                f'  <line x1="{cx}" y1="{body_bottom}" x2="{x + width * 0.75}" y2="{y + height * 0.9}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
            ]
        )
    elif kind == "entity":
        attributes = node.get("attributes", [])
        header_height = min(34.0, max(24.0, height * 0.28))
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="2" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        lines.append(
            f'  <line x1="{x}" y1="{y + header_height}" x2="{x + width}" y2="{y + header_height}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        lines.append(render_multiline_text(label, cx, y + header_height / 2 + 5, "middle", "node-title", 16))
        if attributes:
            row_height = max(15.0, (height - header_height) / max(len(attributes), 1))
            for index, raw_attribute in enumerate(attributes):
                if isinstance(raw_attribute, str):
                    attribute_text = raw_attribute
                else:
                    name = str(raw_attribute.get("name", raw_attribute.get("label", "")))
                    attr_type = str(raw_attribute.get("type", "")).strip()
                    key = str(raw_attribute.get("key", "")).strip().upper()
                    if not key:
                        key = "PK" if raw_attribute.get("pk") else "FK" if raw_attribute.get("fk") else ""
                    prefix = f"{key} " if key else ""
                    attribute_text = f"{prefix}{name}{(' : ' + attr_type) if attr_type else ''}"
                row_y = y + header_height + row_height * index
                if index:
                    lines.append(
                        f'  <line x1="{x}" y1="{row_y}" x2="{x + width}" y2="{row_y}" '
                        f'stroke="{stroke}" stroke-opacity="0.35" stroke-width="1"/>'
                    )
                lines.append(
                    f'  <text x="{x + 10}" y="{row_y + row_height * 0.68}" class="node-sub">'
                    f'{normalize_text(attribute_text)}</text>'
                )
        elif subtitle:
            lines.append(render_multiline_text(subtitle, cx, y + header_height + 22, "middle", "node-sub", 14))
        return "\n".join(lines)
    elif kind in {"state", "participant", "timeline-event"}:
        radius = 18 if kind == "state" else 6
        lines.append(
            f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        if kind == "state" and subtitle:
            divider_y = y + min(34, height * 0.42)
            lines.append(
                f'  <line x1="{x}" y1="{divider_y}" x2="{x + width}" y2="{divider_y}" '
                f'stroke="{stroke}" stroke-opacity="0.55" stroke-width="1"/>'
            )
    elif kind == "initial":
        initial_fill = str(node.get("fill", style_value(style, "text_primary")))
        lines.append(f'  <ellipse cx="{cx}" cy="{cy}" rx="{width / 2}" ry="{height / 2}" fill="{initial_fill}"/>')
    elif kind == "final":
        inner_rx = max(1.0, width / 2 - max(4.0, stroke_width * 2.2))
        inner_ry = max(1.0, height / 2 - max(4.0, stroke_width * 2.2))
        final_fill = str(node.get("fill", style_value(style, "text_primary")))
        lines.extend(
            [
                f'  <ellipse cx="{cx}" cy="{cy}" rx="{width / 2}" ry="{height / 2}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"/>',
                f'  <ellipse cx="{cx}" cy="{cy}" rx="{inner_rx}" ry="{inner_ry}" fill="{final_fill}"/>',
            ]
        )

    if kind not in {"entity", "state", "initial", "final"} and label:
        label_y = y + height + 18 if kind == "actor" else cy + 5
        lines.append(render_multiline_text(label, cx, label_y, "middle", "node-title", 18))
    if kind not in {"entity", "state", "initial", "final"} and subtitle:
        sub_y = y + height + 36 if kind == "actor" else cy + 25
        lines.append(render_multiline_text(subtitle, cx, sub_y, "middle", "node-sub", 14))
    if kind == "state":
        title_y = y + (22 if subtitle else height / 2 + 5)
        lines.append(render_multiline_text(label, cx, title_y, "middle", "node-title", 18))
        if subtitle:
            lines.append(render_multiline_text(subtitle, cx, y + height * 0.67, "middle", "node-sub", 14))
    if kind in {"initial", "final"} and label:
        lines.append(render_multiline_text(label, cx, y + height + 18, "middle", "node-sub", 14))
    return "\n".join(lines)


def render_node(node: Dict[str, object], style: Dict[str, object]) -> str:
    kind = str(node.get("kind", node.get("shape", "rect")))
    if kind == "data-store":
        cylinder_node = dict(node)
        cylinder_node["kind"] = "cylinder"
        return render_node(cylinder_node, style)
    if kind in {"process", "external-entity"}:
        return render_rect_node(node, style, kind)
    if kind in {
        "diamond", "circle", "ellipse", "actor", "entity", "state", "initial", "final",
        "terminator", "participant", "use-case", "timeline-event", "milestone",
    }:
        return render_semantic_node(node, style, kind)
    if kind == "cylinder":
        x = to_float(node["x"])
        y = to_float(node["y"])
        width = to_float(node.get("width", 160))
        height = to_float(node.get("height", 120))
        rx = width / 2
        ry = min(18, height / 8)
        # Database/data-store nodes must inherit the active theme. Hard-coded
        # light green made titles unreadable in dark styles.
        fill = str(node.get("fill", style_value(style, "node_fill")))
        stroke = str(node.get("stroke", style_value(style, "node_stroke")))
        stroke_width = to_float(node.get("stroke_width", 2.2))
        label = str(node.get("label", ""))
        subtitle = str(node.get("sublabel", ""))
        lines = [
            f'  <ellipse cx="{x + width / 2}" cy="{y + ry}" rx="{rx / 2}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
            f'  <rect x="{x}" y="{y + ry}" width="{width}" height="{height - 2 * ry}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
            f'  <ellipse cx="{x + width / 2}" cy="{y + height - ry}" rx="{rx / 2}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>',
            f'  <ellipse cx="{x + width / 2}" cy="{y + height * 0.38}" rx="{rx / 2}" ry="{ry}" fill="none" stroke="{stroke}" stroke-opacity="0.45" stroke-width="1.2"/>',
            f'  <ellipse cx="{x + width / 2}" cy="{y + height * 0.6}" rx="{rx / 2}" ry="{ry}" fill="none" stroke="{stroke}" stroke-opacity="0.25" stroke-width="1.2"/>',
            render_multiline_text(label, x + width / 2, y + height / 2 - 6, "middle", "node-title", 18),
        ]
        if subtitle:
            lines.append(render_multiline_text(subtitle, x + width / 2, y + height / 2 + 18, "middle", "node-sub", 14))
        return "\n".join(lines)
    return render_rect_node(node, style, kind)


def render_arrow(
    arrow: Dict[str, object],
    style: Dict[str, object],
    node_map: Dict[str, Node],
    route_obstacles: Sequence[Bounds],
    label_obstacles: Sequence[Bounds],
) -> Tuple[str, str, Optional[Bounds], Bounds]:
    start_hint = (to_float(arrow.get("x1")), to_float(arrow.get("y1")))
    end_hint = (to_float(arrow.get("x2")), to_float(arrow.get("y2")))
    source_node = node_map.get(str(arrow.get("source"))) if arrow.get("source") else None
    target_node = node_map.get(str(arrow.get("target"))) if arrow.get("target") else None
    source_port = arrow.get("source_port")
    target_port = arrow.get("target_port")

    if source_node is not None:
        toward = end_hint if target_node is None else (target_node.cx, target_node.cy)
        start = anchor_point(source_node, toward, str(source_port) if source_port else None)
    else:
        start = start_hint

    if target_node is not None:
        toward = start_hint if source_node is None else (source_node.cx, source_node.cy)
        end = anchor_point(target_node, toward, str(target_port) if target_port else None)
    else:
        end = end_hint

    obstacles = list(route_obstacles)
    if source_node is not None:
        obstacles = [bounds for bounds in obstacles if bounds != source_node.bounds]
    if target_node is not None:
        obstacles = [bounds for bounds in obstacles if bounds != target_node.bounds]

    route = build_orthogonal_route(start, end, obstacles, arrow)
    path_d = "M " + " L ".join(f"{round(x, 2)},{round(y, 2)}" for x, y in route)
    color = color_for_flow(style, arrow)
    width = to_float(arrow.get("stroke_width", style_value(style, "arrow_width")))
    dash = arrow.get("stroke_dasharray")
    if dash is None and arrow.get("dashed"):
        dash = "6,4"
    marker = marker_for_color(style, color, arrow)
    path = f'  <path d="{path_d}" fill="none" stroke="{color}" stroke-width="{width}"'
    if arrow.get("marker_end", True):
        path += f' marker-end="{marker}"'
    if dash:
        path += f' stroke-dasharray="{dash}"'
    if arrow.get("opacity") is not None:
        path += f' opacity="{arrow["opacity"]}"'
    path += "/>"
    label_svg = ""
    label_bounds = None

    label = str(arrow.get("label", "")).strip()
    if label:
        label_x, label_y = choose_label_position_avoiding(route, label, label_obstacles)
        label_x += to_float(arrow.get("label_dx", 0))
        label_y += to_float(arrow.get("label_dy", -4))
        label_svg = render_label_badge(label_x, label_y, label, style, label_style=str(arrow.get("label_style", "badge")))
        label_bounds = estimate_label_bounds(label_x, label_y, label)
    route_padding = max(4.0, width / 2 + (10.0 if arrow.get("marker_end", True) else 0.0))
    route_bounds = (
        min(point[0] for point in route) - route_padding,
        min(point[1] for point in route) - route_padding,
        max(point[0] for point in route) + route_padding,
        max(point[1] for point in route) + route_padding,
    )
    return path, label_svg, label_bounds, route_bounds


def render_legend(
    legend: Sequence[Dict[str, object]],
    style: Dict[str, object],
    width: float,
    height: float,
    data: Dict[str, object],
) -> str:
    layout = legend_layout(data, legend, width, height)
    if not layout:
        return ""
    legend_x, legend_y, _ = layout
    lines = []
    for idx, item in enumerate(legend):
        y = legend_y + idx * 22
        color = item.get("color")
        if not color:
            color = style_value(style, "arrow_colors")[FLOW_ALIASES.get(str(item.get("flow", "control")).lower(), "control")]
        marker = marker_for_color(style, str(color), {"flow": item.get("flow", "control")})
        lines.append(f'  <line x1="{legend_x}" y1="{y}" x2="{legend_x + 30}" y2="{y}" stroke="{color}" stroke-width="{style_value(style, "arrow_width")}" marker-end="{marker}"/>')
        lines.append(f'  <text x="{legend_x + 40}" y="{y + 4}" class="legend">{normalize_text(item.get("label", ""))}</text>')
    if data.get("legend_box"):
        max_label = max((len(str(item.get("label", ""))) for item in legend), default=12)
        block_width = 40 + max_label * 7 + 12
        block_height = len(legend) * 22 + 6
        bg = data.get("legend_box_fill", style_value(style, "arrow_label_bg"))
        opacity = data.get("legend_box_opacity", 0.88)
        lines.insert(0, f'  <rect x="{legend_x - 10}" y="{legend_y - 14}" width="{block_width + 20}" height="{block_height + 18}" rx="10" fill="{bg}" opacity="{opacity}"/>')
    return "\n".join(lines)


def render_footer(data: Dict[str, object], style: Dict[str, object], width: float, height: float) -> str:
    layout = footer_layout(data, width, height)
    if not layout:
        return ""
    x, y, _ = layout
    text = str(data.get("footer", "")).strip()
    return f'  <text x="{x}" y="{y}" class="footnote">{normalize_text(text)}</text>'


def build_svg(template_type: str, data: Dict[str, object]) -> str:
    data = prepare_diagram_data(template_type, data)
    style_index, style = parse_style(data.get("style"))
    if data.get("style_overrides"):
        overrides = copy.deepcopy(data["style_overrides"])
        arrow_color_overrides = overrides.pop("arrow_colors", None)
        style.update(overrides)
        if arrow_color_overrides:
            style["arrow_colors"].update(arrow_color_overrides)
    width, height = parse_template_viewbox(template_type)
    width = to_float(data.get("width", width))
    height = to_float(data.get("height", height))
    if data.get("viewBox"):
        match = re.match(r"0 0 ([0-9.]+) ([0-9.]+)", str(data["viewBox"]))
        if match:
            width = float(match.group(1))
            height = float(match.group(2))

    containers: List[Dict[str, object]] = data.get("containers", [])
    nodes_data: List[Dict[str, object]] = data.get("nodes", [])
    arrows_data: List[Dict[str, object]] = data.get("arrows", [])
    legend = data.get("legend", [])

    # Account for long headers before positioning any bottom/right anchored UI.
    width = max(
        width,
        _text_width(data.get("title", "Diagram"), to_float(style_value(style, "title_size")) * 0.62) + 96,
        _text_width(data.get("subtitle", ""), to_float(style_value(style, "subtitle_size")) * 0.62) + 96,
    )
    _, content_start_y = render_title_block(style, data, width)

    # Assign auto_place y before building node maps so arrows route correctly
    for node_data in nodes_data:
        if "y" not in node_data and node_data.get("auto_place"):
            node_data["y"] = content_start_y + to_float(node_data.get("offset_y", 0))

    content_bounds = explicit_content_bounds(data)
    if content_bounds:
        left, top, right, bottom = content_bounds
        dx = 72 - left if left < 0 else 0.0
        dy = max(content_start_y + 28, 72) - top if top < 0 else 0.0
        if dx or dy:
            translate_content(data, dx, dy)
            content_bounds = explicit_content_bounds(data)
        if content_bounds:
            width = max(width, content_bounds[2] + 60)
            height = max(height, content_bounds[3] + 60)

    arrow_paths: List[str] = []
    arrow_labels: List[str] = []
    blueprint_block_svg = ""
    # Recompute anchored/reserved elements when a route or label expands the
    # canvas. A few passes converge while keeping the common case single-pass.
    for _ in range(3):
        normalized_nodes = [normalize_node(node, f"node-{idx}") for idx, node in enumerate(nodes_data)]
        node_map = {node.node_id: node for node in normalized_nodes}
        section_obstacles = [
            bounds for container in containers
            if (bounds := container_header_bounds(container)) is not None
        ]
        legend_reserved = legend_layout(data, legend, width, height)
        footer_reserved = footer_layout(data, width, height)
        blueprint_block_svg, blueprint_block_bounds = render_blueprint_title_block(
            data, style, style_index, width, height
        )
        reserved_bounds = list(section_obstacles)
        for reserved in (legend_reserved, footer_reserved):
            if reserved:
                reserved_bounds.append(reserved[2])
        if blueprint_block_bounds:
            reserved_bounds.append(blueprint_block_bounds)

        arrow_paths = []
        arrow_labels = []
        route_and_label_bounds: List[Bounds] = []
        node_obstacles = [node.bounds for node in normalized_nodes]
        route_obstacles = node_obstacles + reserved_bounds
        label_obstacles = node_obstacles + reserved_bounds
        for arrow in arrows_data:
            path_svg, label_svg, label_bounds, route_bounds = render_arrow(
                arrow, style, node_map, route_obstacles, label_obstacles
            )
            arrow_paths.append(path_svg)
            route_and_label_bounds.append(route_bounds)
            if label_svg:
                arrow_labels.append(label_svg)
            if label_bounds:
                label_obstacles.append(label_bounds)
                route_and_label_bounds.append(label_bounds)

        all_visible: List[Bounds] = [visual_node_bounds(node) for node in nodes_data]
        all_visible.extend(
            rectangle_bounds(
                to_float(container["x"]), to_float(container["y"]),
                to_float(container["width"]), to_float(container["height"]),
            )
            for container in containers
        )
        all_visible.extend(route_and_label_bounds)
        all_visible.extend(reserved_bounds)
        visible = union_bounds(all_visible)
        if not visible:
            break
        min_x, min_y, max_x, max_y = visible
        if min_x < 0 or min_y < 0:
            dx = 72 - min_x if min_x < 0 else 0.0
            dy = max(content_start_y + 28, 72) - min_y if min_y < 0 else 0.0
            translate_content(data, dx, dy)
            continue
        expanded_width = max(width, max_x + 60)
        expanded_height = max(height, max_y + 60)
        if expanded_width > width + 0.5 or expanded_height > height + 0.5:
            width, height = expanded_width, expanded_height
            continue
        break

    width = float(math.ceil(width))
    height = float(math.ceil(height))
    defs = render_defs(style_index, style)
    canvas = render_canvas(style_index, style, width, height)
    title_block, _ = render_title_block(style, data, width)
    window_controls = render_window_controls(data, style_index, width)
    header_meta = render_header_meta(data, style, width)
    diagram_title = str(data.get("title", "Diagram"))
    diagram_desc = str(
        data.get("description")
        or data.get("subtitle")
        or f"Technical diagram: {diagram_title}"
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(width)} {int(height)}" '
        f'width="{int(width)}" height="{int(height)}" role="img" '
        f'aria-labelledby="diagram-title diagram-desc">',
        f'  <title id="diagram-title">{normalize_text(diagram_title)}</title>',
        f'  <desc id="diagram-desc">{normalize_text(diagram_desc)}</desc>',
        defs,
        canvas,
    ]
    if window_controls:
        lines.append(window_controls)
    if header_meta:
        lines.append(header_meta)
    lines.append(title_block)
    for container in containers:
        lines.append(render_section(container, style))

    lines.extend(path for path in arrow_paths if path)

    for node_data in nodes_data:
        lines.append(render_node(node_data, style))

    lines.extend(label for label in arrow_labels if label)

    legend_svg = render_legend(legend, style, width, height, data)
    if legend_svg:
        lines.append(legend_svg)

    if blueprint_block_svg:
        lines.append(blueprint_block_svg)

    footer_svg = render_footer(data, style, width, height)
    if footer_svg:
        lines.append(footer_svg)

    lines.append("</svg>")
    return "\n".join(line for line in lines if line)


def atomic_write_svg(output_path: str, svg_content: str) -> None:
    """Validate XML then atomically replace the destination in its directory."""
    try:
        ET.fromstring(svg_content)
    except ET.ParseError as exc:
        raise ValueError(f"Generated SVG is not valid XML: {exc}") from exc
    absolute_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(absolute_path)
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"Output directory does not exist: {output_dir}")
    old_mode: Optional[int] = None
    if os.path.exists(absolute_path):
        old_mode = os.stat(absolute_path).st_mode & 0o777
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(absolute_path)}.", suffix=".tmp", dir=output_dir
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg_content)
            handle.flush()
            os.fsync(handle.fileno())
        if old_mode is not None:
            os.chmod(temporary_path, old_mode)
        os.replace(temporary_path, absolute_path)
        try:
            directory_fd = os.open(output_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not available on every supported platform;
            # the file replacement itself has already completed atomically.
            pass
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python3 generate-from-template.py <template-type> <output-path> [data-json]")
        sys.exit(1)

    template_type = sys.argv[1]
    output_path = sys.argv[2]

    try:
        if len(sys.argv) > 3:
            raw_arg = sys.argv[3]
            if raw_arg.endswith('.json') and os.path.exists(raw_arg):
                with open(raw_arg, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(raw_arg)
        else:
            data = json.load(sys.stdin)
        svg_content = build_svg(template_type, data)
        atomic_write_svg(output_path, svg_content)
        print(f"✓ SVG generated: {output_path}")
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON: {exc}")
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
