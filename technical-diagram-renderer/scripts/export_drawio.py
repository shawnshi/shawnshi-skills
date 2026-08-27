#!/usr/bin/env python3
"""Export normalized diagram JSON as uncompressed diagrams.net XML.

Usage:
    export_drawio.py <input.json> <output.drawio>

The exporter intentionally accepts only semantic fields.  It never copies raw
SVG, XML, HTML, or style fragments from the input into the output.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableSet, Optional, Sequence, Tuple


class DrawioExportError(ValueError):
    """Raised when the input cannot be represented safely as a draw.io file."""


BASE_VERTEX_STYLE = "whiteSpace=wrap;html=0;align=center;verticalAlign=middle;"

NODE_STYLES: Dict[str, str] = {
    "rect": BASE_VERTEX_STYLE + "rounded=0;",
    "diamond": BASE_VERTEX_STYLE + "shape=rhombus;perimeter=rhombusPerimeter;",
    "ellipse": BASE_VERTEX_STYLE + "ellipse;perimeter=ellipsePerimeter;",
    "cylinder": BASE_VERTEX_STYLE + "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;",
    "actor": (
        "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;"
        "html=0;outlineConnect=0;"
    ),
    "entity": (
        "shape=swimlane;horizontal=1;startSize=28;rounded=0;collapsible=0;"
        "whiteSpace=wrap;html=0;"
    ),
    "state": BASE_VERTEX_STYLE + "rounded=1;arcSize=20;",
}

NODE_KIND_ALIASES: Dict[str, str] = {
    "rect": "rect",
    "rectangle": "rect",
    "box": "rect",
    "double-rect": "rect",
    "document": "rect",
    "folder": "rect",
    "terminal": "rect",
    "bot": "rect",
    "speech": "rect",
    "icon-box": "rect",
    "process": "rect",
    "participant": "rect",
    "timeline-event": "rect",
    "diamond": "diamond",
    "decision": "diamond",
    "hexagon": "diamond",
    "ellipse": "ellipse",
    "circle": "ellipse",
    "oval": "ellipse",
    "circle-cluster": "ellipse",
    "initial": "ellipse",
    "final": "ellipse",
    "terminator": "ellipse",
    "use-case": "ellipse",
    "milestone": "ellipse",
    "cylinder": "cylinder",
    "database": "cylinder",
    "data-store": "cylinder",
    "actor": "actor",
    "user": "actor",
    "uml-actor": "actor",
    "user-avatar": "actor",
    "entity": "entity",
    "table": "entity",
    "class": "entity",
    "state": "state",
    "status": "state",
}

CONTAINER_STYLES: Dict[str, str] = {
    "container": (
        "swimlane;horizontal=1;startSize=28;rounded=1;arcSize=12;"
        "collapsible=0;container=1;whiteSpace=wrap;html=0;"
        "fillColor=none;strokeColor=#94a3b8;dashed=1;"
    ),
    "group": (
        "swimlane;horizontal=1;startSize=28;rounded=1;arcSize=12;"
        "collapsible=0;container=1;whiteSpace=wrap;html=0;"
        "fillColor=none;strokeColor=#94a3b8;dashed=1;"
    ),
    "section": (
        "swimlane;horizontal=1;startSize=28;rounded=1;arcSize=12;"
        "collapsible=0;container=1;whiteSpace=wrap;html=0;"
        "fillColor=none;strokeColor=#64748b;"
    ),
    "swimlane": (
        "swimlane;horizontal=1;startSize=30;rounded=0;collapsible=0;"
        "container=1;whiteSpace=wrap;html=0;strokeColor=#64748b;"
    ),
    "layer": (
        "swimlane;horizontal=1;startSize=28;rounded=1;arcSize=12;"
        "collapsible=0;container=1;whiteSpace=wrap;html=0;"
        "fillColor=none;strokeColor=#64748b;"
    ),
}

EDGE_STYLES: Dict[str, str] = {
    "control": "strokeColor=#475569;endArrow=block;endFill=1;",
    "data": "strokeColor=#f59e0b;endArrow=block;endFill=1;",
    "write": "strokeColor=#059669;endArrow=block;endFill=1;",
    "read": "strokeColor=#2563eb;endArrow=block;endFill=1;",
    "async": "strokeColor=#7c3aed;dashed=1;endArrow=block;endFill=1;",
    "feedback": "strokeColor=#dc2626;dashed=1;endArrow=open;endFill=0;",
    "neutral": "strokeColor=#64748b;endArrow=block;endFill=1;",
    "association": "strokeColor=#475569;endArrow=none;",
    "dependency": "strokeColor=#475569;dashed=1;endArrow=open;endFill=0;",
    "inheritance": "strokeColor=#475569;endArrow=block;endFill=0;",
}

EDGE_KIND_ALIASES: Dict[str, str] = {
    "arrow": "control",
    "main": "control",
    "api": "control",
    "control": "control",
    "data": "data",
    "write": "write",
    "read": "read",
    "async": "async",
    "feedback": "feedback",
    "neutral": "neutral",
    "relationship": "association",
    "association": "association",
    "dependency": "dependency",
    "inheritance": "inheritance",
}

PORTS: Dict[str, Tuple[float, float]] = {
    "left": (0.0, 0.5),
    "right": (1.0, 0.5),
    "top": (0.5, 0.0),
    "bottom": (0.5, 1.0),
    "top-left": (0.0, 0.0),
    "top-right": (1.0, 0.0),
    "bottom-left": (0.0, 1.0),
    "bottom-right": (1.0, 1.0),
}

PORT_ALIASES = {
    "west": "left",
    "east": "right",
    "north": "top",
    "south": "bottom",
}


def _normalize_token(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DrawioExportError("{} must be a non-empty string".format(path))
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def _validate_xml_text(value: str, path: str) -> str:
    for char in value:
        codepoint = ord(char)
        if not (
            codepoint in (0x09, 0x0A, 0x0D)
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            raise DrawioExportError("{} contains a character forbidden by XML 1.0".format(path))
    return value


def _identifier(value: object, path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise DrawioExportError("{} must be a string or integer".format(path))
    text = str(value)
    if not text.strip():
        raise DrawioExportError("{} must not be empty".format(path))
    return _validate_xml_text(text, path)


def _number(item: Mapping[str, object], key: str, path: str) -> float:
    if key not in item:
        raise DrawioExportError("{}.{} is required".format(path, key))
    raw = item[key]
    if isinstance(raw, bool):
        raise DrawioExportError("{}.{} must be a finite number".format(path, key))
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise DrawioExportError("{}.{} must be a finite number".format(path, key))
    if not math.isfinite(value):
        raise DrawioExportError("{}.{} must be a finite number".format(path, key))
    return value


def _format_number(value: float) -> str:
    if value == 0:
        value = 0.0
    if value.is_integer():
        return str(int(value))
    return format(value, ".12g")


def _label_parts(value: object, path: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_validate_xml_text(value, path)] if value else []
    if isinstance(value, bool):
        return [str(value).lower()]
    if isinstance(value, int):
        return [str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DrawioExportError("{} must not contain NaN or infinity".format(path))
        return [_format_number(value)]
    if isinstance(value, (list, tuple)):
        parts: List[str] = []
        for index, part in enumerate(value):
            parts.extend(_label_parts(part, "{}[{}]".format(path, index)))
        return parts
    if isinstance(value, Mapping):
        parts = []
        for key in sorted(value, key=lambda entry: str(entry)):
            parts.extend(_label_parts(value[key], "{}.{}".format(path, key)))
        return parts
    raise DrawioExportError("{} must be text, a number, a list, or an object".format(path))


def _label(item: Mapping[str, object], path: str) -> str:
    if "label" in item:
        parts = _label_parts(item.get("label"), "{}.label".format(path))
    elif "labels" in item:
        parts = _label_parts(item.get("labels"), "{}.labels".format(path))
    elif "name" in item:
        parts = _label_parts(item.get("name"), "{}.name".format(path))
    else:
        parts = []
    if "sublabel" in item:
        parts.extend(_label_parts(item.get("sublabel"), "{}.sublabel".format(path)))
    return "\n".join(part for part in parts if part)


def _mapping_list(document: Mapping[str, object], key: str) -> List[Mapping[str, object]]:
    raw = document.get(key, [])
    if not isinstance(raw, list):
        raise DrawioExportError("{} must be an array".format(key))
    result: List[Mapping[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise DrawioExportError("{}[{}] must be an object".format(key, index))
        result.append(item)
    return result


def _reserve_explicit_ids(
    collections: Iterable[Tuple[str, Sequence[Mapping[str, object]]]],
) -> MutableSet[str]:
    used: MutableSet[str] = set()
    for collection_name, items in collections:
        for index, item in enumerate(items):
            if item.get("id") is None:
                continue
            path = "{}[{}].id".format(collection_name, index)
            value = _identifier(item["id"], path)
            if value in used:
                raise DrawioExportError("{} duplicates id {!r}".format(path, value))
            used.add(value)
    return used


def _generated_id(prefix: str, index: int, used: MutableSet[str]) -> str:
    base = "{}-{}".format(prefix, index + 1)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = "{}-{}".format(base, suffix)
        suffix += 1
    used.add(candidate)
    return candidate


def _node_style(item: Mapping[str, object], path: str) -> str:
    raw_kind = item.get("kind", item.get("shape", "rect"))
    token = _normalize_token(raw_kind, "{}.kind".format(path))
    canonical = NODE_KIND_ALIASES.get(token)
    if canonical is None:
        raise DrawioExportError("{}.kind has unsupported value {!r}".format(path, raw_kind))
    return NODE_STYLES[canonical]


def _container_style(item: Mapping[str, object], path: str) -> str:
    raw_kind = item.get("kind", "container")
    token = _normalize_token(raw_kind, "{}.kind".format(path))
    style = CONTAINER_STYLES.get(token)
    if style is None:
        raise DrawioExportError("{}.kind has unsupported value {!r}".format(path, raw_kind))
    return style


def _edge_style(item: Mapping[str, object], path: str) -> str:
    raw_kind = item.get("kind", item.get("flow", "control"))
    token = _normalize_token(raw_kind, "{}.kind".format(path))
    canonical = EDGE_KIND_ALIASES.get(token)
    if canonical is None:
        raise DrawioExportError("{}.kind has unsupported relationship {!r}".format(path, raw_kind))
    style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
        "jettySize=auto;html=0;" + EDGE_STYLES[canonical]
    )
    dashed = item.get("dashed")
    if dashed is not None and not isinstance(dashed, bool):
        raise DrawioExportError("{}.dashed must be true or false".format(path))
    if dashed and "dashed=1;" not in style:
        style += "dashed=1;"
    marker_end = item.get("marker_end")
    if marker_end is not None and not isinstance(marker_end, bool):
        raise DrawioExportError("{}.marker_end must be true or false".format(path))
    if marker_end is False:
        style += "endArrow=none;endFill=0;"
    source_port = _port(item, "source", path)
    target_port = _port(item, "target", path)
    if source_port:
        x_value, y_value = PORTS[source_port]
        style += "exitX={};exitY={};exitDx=0;exitDy=0;exitPerimeter=1;".format(
            _format_number(x_value), _format_number(y_value)
        )
    if target_port:
        x_value, y_value = PORTS[target_port]
        style += "entryX={};entryY={};entryDx=0;entryDy=0;entryPerimeter=1;".format(
            _format_number(x_value), _format_number(y_value)
        )
    return style


def _port(item: Mapping[str, object], endpoint: str, path: str) -> Optional[str]:
    field = "{}_port".format(endpoint)
    raw = item.get(field)
    if raw is None and "ports" in item:
        ports = item["ports"]
        if not isinstance(ports, Mapping):
            raise DrawioExportError("{}.ports must be an object".format(path))
        raw = ports.get(endpoint)
    if raw is None or raw == "":
        return None
    token = _normalize_token(raw, "{}.{}".format(path, field))
    token = PORT_ALIASES.get(token, token)
    if token not in PORTS:
        raise DrawioExportError("{}.{} has unsupported port {!r}".format(path, field, raw))
    return token


def _route_points(item: Mapping[str, object], path: str) -> List[Tuple[float, float]]:
    raw = item.get("route_points", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DrawioExportError("{}.route_points must be an array".format(path))
    points: List[Tuple[float, float]] = []
    for index, point in enumerate(raw):
        point_path = "{}.route_points[{}]".format(path, index)
        if isinstance(point, Mapping):
            x_value = _number(point, "x", point_path)
            y_value = _number(point, "y", point_path)
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            x_value = _number({"value": point[0]}, "value", point_path + "[0]")
            y_value = _number({"value": point[1]}, "value", point_path + "[1]")
        else:
            raise DrawioExportError("{} must be [x, y] or an object with x/y".format(point_path))
        points.append((x_value, y_value))
    return points


def _geometry(item: Mapping[str, object], path: str) -> Tuple[float, float, float, float]:
    x_value = _number(item, "x", path)
    y_value = _number(item, "y", path)
    width = _number(item, "width", path)
    height = _number(item, "height", path)
    if width <= 0:
        raise DrawioExportError("{}.width must be greater than zero".format(path))
    if height <= 0:
        raise DrawioExportError("{}.height must be greater than zero".format(path))
    return x_value, y_value, width, height


def _append_vertex(
    graph_root: ET.Element,
    internal_id: str,
    external_id: str,
    label: str,
    style: str,
    geometry: Tuple[float, float, float, float],
) -> None:
    cell = ET.SubElement(
        graph_root,
        "mxCell",
        {
            "id": internal_id,
            "data-id": external_id,
            "value": label,
            "style": style,
            "vertex": "1",
            "parent": "1",
        },
    )
    x_value, y_value, width, height = geometry
    ET.SubElement(
        cell,
        "mxGeometry",
        {
            "x": _format_number(x_value),
            "y": _format_number(y_value),
            "width": _format_number(width),
            "height": _format_number(height),
            "as": "geometry",
        },
    )


def _indent(element: ET.Element, level: int = 0) -> None:
    indentation = "\n" + level * "  "
    child_indentation = "\n" + (level + 1) * "  "
    children = list(element)
    if children:
        if not element.text or not element.text.strip():
            element.text = child_indentation
        for child in children:
            _indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = child_indentation
        children[-1].tail = indentation
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = indentation


def build_drawio_tree(document: Mapping[str, object]) -> ET.ElementTree:
    """Validate *document* and return an uncompressed draw.io XML tree."""
    if not isinstance(document, Mapping):
        raise DrawioExportError("top-level JSON value must be an object")

    containers = _mapping_list(document, "containers")
    nodes = _mapping_list(document, "nodes")
    arrows = _mapping_list(document, "arrows")

    used_ids = _reserve_explicit_ids(
        (("containers", containers), ("nodes", nodes), ("arrows", arrows))
    )

    container_ids: List[str] = []
    for index, container in enumerate(containers):
        if container.get("id") is None:
            container_ids.append(_generated_id("container", index, used_ids))
        else:
            container_ids.append(_identifier(container["id"], "containers[{}].id".format(index)))

    node_ids: List[str] = []
    for index, node in enumerate(nodes):
        if node.get("id") is None:
            raise DrawioExportError("nodes[{}].id is required".format(index))
        node_ids.append(_identifier(node["id"], "nodes[{}].id".format(index)))

    arrow_ids: List[str] = []
    for index, arrow in enumerate(arrows):
        if arrow.get("id") is None:
            arrow_ids.append(_generated_id("edge", index, used_ids))
        else:
            arrow_ids.append(_identifier(arrow["id"], "arrows[{}].id".format(index)))

    container_specs = []
    node_specs = []
    max_x = 0.0
    max_y = 0.0

    for index, (container, external_id) in enumerate(zip(containers, container_ids)):
        path = "containers[{}]".format(index)
        geometry = _geometry(container, path)
        container_specs.append((external_id, _label(container, path), _container_style(container, path), geometry))
        max_x = max(max_x, geometry[0] + geometry[2])
        max_y = max(max_y, geometry[1] + geometry[3])

    for index, (node, external_id) in enumerate(zip(nodes, node_ids)):
        path = "nodes[{}]".format(index)
        geometry = _geometry(node, path)
        node_specs.append((external_id, _label(node, path), _node_style(node, path), geometry))
        max_x = max(max_x, geometry[0] + geometry[2])
        max_y = max(max_y, geometry[1] + geometry[3])

    page_name_raw = document.get("title", document.get("name", "Page-1"))
    page_name_parts = _label_parts(page_name_raw, "title")
    page_name = " - ".join(page_name_parts) if page_name_parts else "Page-1"

    page_width = max(1169, int(math.ceil(max_x + 80)))
    page_height = max(827, int(math.ceil(max_y + 80)))
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "Technical Diagram Renderer",
            "compressed": "false",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "page-1", "name": page_name})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": str(page_width),
            "dy": str(page_height),
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(page_width),
            "pageHeight": str(page_height),
            "math": "0",
            "shadow": "0",
        },
    )
    graph_root = ET.SubElement(model, "root")
    ET.SubElement(graph_root, "mxCell", {"id": "0"})
    ET.SubElement(graph_root, "mxCell", {"id": "1", "parent": "0"})

    external_to_internal: Dict[str, str] = {}
    next_internal = 2
    for external_id, label, style, geometry in container_specs:
        internal_id = "cell-{}".format(next_internal)
        next_internal += 1
        external_to_internal[external_id] = internal_id
        _append_vertex(graph_root, internal_id, external_id, label, style, geometry)
    for external_id, label, style, geometry in node_specs:
        internal_id = "cell-{}".format(next_internal)
        next_internal += 1
        external_to_internal[external_id] = internal_id
        _append_vertex(graph_root, internal_id, external_id, label, style, geometry)

    edge_specs = []
    for index, (arrow, external_id) in enumerate(zip(arrows, arrow_ids)):
        path = "arrows[{}]".format(index)
        id_fields_present = "source" in arrow or "target" in arrow
        coordinate_names = ("x1", "y1", "x2", "y2")
        coordinate_fields_present = any(name in arrow for name in coordinate_names)
        if id_fields_present and coordinate_fields_present:
            raise DrawioExportError(
                "{} must not mix source/target ids with x1/y1/x2/y2 coordinates".format(path)
            )

        source_internal: Optional[str] = None
        target_internal: Optional[str] = None
        coordinates: Optional[Tuple[float, float, float, float]] = None
        if id_fields_present:
            if "source" not in arrow or "target" not in arrow:
                raise DrawioExportError("{} must provide both source and target".format(path))
            source = _identifier(arrow["source"], "{}.source".format(path))
            target = _identifier(arrow["target"], "{}.target".format(path))
            if source not in external_to_internal:
                raise DrawioExportError("{}.source references unknown id {!r}".format(path, source))
            if target not in external_to_internal:
                raise DrawioExportError("{}.target references unknown id {!r}".format(path, target))
            source_internal = external_to_internal[source]
            target_internal = external_to_internal[target]
        elif coordinate_fields_present:
            missing = [name for name in coordinate_names if name not in arrow]
            if missing:
                raise DrawioExportError(
                    "{} coordinate endpoints require x1, y1, x2, and y2; missing {}".format(
                        path, ", ".join(missing)
                    )
                )
            coordinates = (
                _number(arrow, "x1", path),
                _number(arrow, "y1", path),
                _number(arrow, "x2", path),
                _number(arrow, "y2", path),
            )
            if _port(arrow, "source", path) or _port(arrow, "target", path):
                raise DrawioExportError(
                    "{} coordinate endpoints must not declare source or target ports".format(path)
                )
        else:
            raise DrawioExportError(
                "{} must provide either source/target ids or x1/y1/x2/y2 coordinates".format(path)
            )
        edge_specs.append(
            (
                external_id,
                _label(arrow, path),
                _edge_style(arrow, path),
                source_internal,
                target_internal,
                coordinates,
                _route_points(arrow, path),
            )
        )

    for external_id, label, style, source, target, coordinates, points in edge_specs:
        internal_id = "cell-{}".format(next_internal)
        next_internal += 1
        cell_attributes = {
            "id": internal_id,
            "data-id": external_id,
            "value": label,
            "style": style,
            "edge": "1",
            "parent": "1",
        }
        if source is not None and target is not None:
            cell_attributes["source"] = source
            cell_attributes["target"] = target
        edge_cell = ET.SubElement(
            graph_root,
            "mxCell",
            cell_attributes,
        )
        geometry = ET.SubElement(edge_cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        if coordinates is not None:
            x1, y1, x2, y2 = coordinates
            ET.SubElement(
                geometry,
                "mxPoint",
                {"x": _format_number(x1), "y": _format_number(y1), "as": "sourcePoint"},
            )
            ET.SubElement(
                geometry,
                "mxPoint",
                {"x": _format_number(x2), "y": _format_number(y2), "as": "targetPoint"},
            )
        if points:
            point_array = ET.SubElement(geometry, "Array", {"as": "points"})
            for x_value, y_value in points:
                ET.SubElement(
                    point_array,
                    "mxPoint",
                    {"x": _format_number(x_value), "y": _format_number(y_value)},
                )

    _indent(mxfile)
    return ET.ElementTree(mxfile)


def _atomic_write(tree: ET.ElementTree, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{}-".format(output_path.name), suffix=".tmp", dir=str(output_path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            tree.write(handle, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
            handle.flush()
            os.fsync(handle.fileno())
        ET.parse(str(temporary_path))
        try:
            os.chmod(str(temporary_path), 0o644)
        except OSError:
            pass
        os.replace(str(temporary_path), str(output_path))
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def export_drawio(document: Mapping[str, object], output_path: Path) -> None:
    tree = build_drawio_tree(document)
    _atomic_write(tree, Path(output_path))


def _reject_json_constant(value: str) -> None:
    raise DrawioExportError("JSON constant {} is not permitted".format(value))


def load_document(input_path: Path) -> Mapping[str, object]:
    with Path(input_path).open("r", encoding="utf-8-sig") as handle:
        document = json.load(handle, parse_constant=_reject_json_constant)
    if not isinstance(document, Mapping):
        raise DrawioExportError("top-level JSON value must be an object")
    return document


def export_file(input_path: Path, output_path: Path) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if os.path.abspath(str(input_path)) == os.path.abspath(str(output_path)):
        raise DrawioExportError("input and output paths must be different")
    export_drawio(load_document(input_path), output_path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    if len(arguments) != 2:
        print("Usage: export_drawio.py <input.json> <output.drawio>", file=sys.stderr)
        return 2
    try:
        export_file(Path(arguments[0]), Path(arguments[1]))
    except (DrawioExportError, json.JSONDecodeError, UnicodeError, OSError, ET.ParseError) as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1
    print("Draw.io generated: {}".format(arguments[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
