#!/usr/bin/env python3
"""Deterministic, dependency-free layout helpers for generic diagram nodes.

The renderer's public JSON is intentionally kept separate from this module.  The
single entry point, :func:`apply_auto_layout`, accepts that JSON-like mapping and
returns a deep-copied mapping.  It never mutates its caller's object.

Only items in ``nodes`` are positioned here.  A node is eligible when either of
its coordinates is missing/invalid, when the top-level ``layout.auto`` flag is
true, or when its own ``layout.auto`` flag is true.  Other node coordinates are
preserved.  The resulting top-level ``_layout_stats`` object is diagnostic data;
renderers should ignore it.
"""

from __future__ import annotations

import copy
import heapq
import math
import re
import unicodedata
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

Bounds = Tuple[float, float, float, float]

DEFAULT_CANVAS: Dict[str, Tuple[float, float]] = {
    "architecture": (960.0, 600.0),
    "data-flow": (960.0, 600.0),
    "flowchart": (960.0, 640.0),
    "sequence": (960.0, 700.0),
    "comparison": (960.0, 620.0),
    "comparison-matrix": (960.0, 620.0),
    "timeline": (960.0, 520.0),
    "mind-map": (960.0, 620.0),
    "agent": (960.0, 700.0),
    "agent-architecture": (960.0, 700.0),
    "memory": (960.0, 720.0),
    "use-case": (960.0, 600.0),
    "class": (960.0, 700.0),
    "state-machine": (960.0, 620.0),
    "er-diagram": (960.0, 680.0),
    "network-topology": (960.0, 620.0),
}

_PORTS = {"left", "right", "top", "bottom"}
_OPPOSITE_PORT = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
_ROUTE_HINT_FIELDS = ("route_points", "corridor_x", "corridor_y")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[-./:][A-Za-z0-9_]+)*|\s+|.", re.DOTALL)


def _number(value: Any) -> Optional[float]:
    """Return a finite float, treating booleans and malformed values as missing."""

    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clean_number(value: float) -> int | float:
    rounded = round(float(value), 2)
    return int(rounded) if rounded.is_integer() else rounded


def estimate_text_width(text: Any, font_size: float = 18.0) -> float:
    """Estimate rendered width for mixed Chinese and Latin text without a font.

    East Asian wide/full-width glyphs count as one em.  Latin letters and digits
    use conservative proportional-font factors.  This is deliberately a little
    generous so automatic wrapping avoids clipping across the renderer's CJK
    fallback font stack.
    """

    size = max(1.0, float(font_size))
    line_width = 0.0
    widest = 0.0
    for char in str(text or "").replace("\\n", "\n"):
        if char == "\n":
            widest = max(widest, line_width)
            line_width = 0.0
            continue
        if unicodedata.combining(char):
            continue
        if char == "\t":
            factor = 1.28
        elif char.isspace():
            factor = 0.34
        else:
            east_asian = unicodedata.east_asian_width(char)
            category = unicodedata.category(char)
            if east_asian in {"W", "F"}:
                factor = 1.0
            elif east_asian == "A":
                factor = 0.78
            elif char in "MW@#%&":
                factor = 0.82
            elif char in "ilI1|!.,:;'`":
                factor = 0.34
            elif category.startswith("P"):
                factor = 0.48
            elif char.isupper():
                factor = 0.66
            else:
                factor = 0.58
        line_width += factor * size
    return round(max(widest, line_width), 2)


def _split_oversized_token(token: str, max_width: float, font_size: float) -> List[str]:
    pieces: List[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if current and estimate_text_width(candidate, font_size) > max_width:
            pieces.append(current)
            current = char
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [token]


def _wrap_paragraph(text: str, max_width: float, font_size: float) -> List[str]:
    tokens = [token for token in _TOKEN_RE.findall(text) if token]
    lines: List[str] = []
    current = ""
    for token in tokens:
        if token.isspace():
            if current and not current.endswith(" "):
                current += " "
            continue
        candidate = (current + token).rstrip()
        if not current or estimate_text_width(candidate, font_size) <= max_width:
            if estimate_text_width(token, font_size) <= max_width:
                current = candidate
                continue
        if current.strip():
            lines.append(current.strip())
            current = ""
        pieces = _split_oversized_token(token, max_width, font_size)
        lines.extend(piece for piece in pieces[:-1] if piece)
        current = pieces[-1] if pieces else ""
    if current.strip() or not lines:
        lines.append(current.strip())
    return lines


def wrap_text(text: Any, max_width: float, font_size: float = 18.0, max_lines: Optional[int] = None) -> str:
    """Greedily wrap mixed-language text and return SVG-friendly newlines.

    Existing real or escaped newlines are retained as paragraph boundaries.  If
    ``max_lines`` is supplied, the last line receives an ellipsis only when text
    would otherwise be lost.
    """

    raw = str(text or "").replace("\\n", "\n")
    width = max(float(max_width), float(font_size))
    lines: List[str] = []
    for paragraph in raw.split("\n"):
        lines.extend(_wrap_paragraph(paragraph, width, float(font_size)))
    if max_lines is not None and max_lines > 0 and len(lines) > max_lines:
        lines = lines[:max_lines]
        ellipsis = "…"
        last = lines[-1].rstrip()
        while last and estimate_text_width(last + ellipsis, font_size) > width:
            last = last[:-1].rstrip()
        lines[-1] = (last + ellipsis) if last else ellipsis
    return "\n".join(lines)


def _canvas(data: Mapping[str, Any], template_type: str) -> Tuple[float, float]:
    default_width, default_height = DEFAULT_CANVAS.get(str(template_type), (960.0, 600.0))
    width = _number(data.get("width")) or default_width
    height = _number(data.get("height")) or default_height
    viewbox = data.get("viewBox")
    if isinstance(viewbox, str):
        values = viewbox.replace(",", " ").split()
        if len(values) == 4:
            parsed_width = _number(values[2])
            parsed_height = _number(values[3])
            if parsed_width and parsed_height and parsed_width > 0 and parsed_height > 0:
                width, height = parsed_width, parsed_height
    return max(240.0, width), max(180.0, height)


def _canvas_profile(width: float, height: float) -> str:
    ratio = width / height
    if ratio >= 1.45:
        return "widescreen"
    if ratio <= 0.9:
        return "document"
    return "standard"


def _title_bottom(data: Mapping[str, Any]) -> float:
    # The renderer emits a default title even if `title` is omitted.
    bottom = 104.0 if data.get("subtitle") else 88.0
    if data.get("window_controls") or any(data.get(key) for key in ("meta_left", "meta_center", "meta_right")):
        bottom = max(bottom, 74.0)
    return bottom


def _node_auto(node: Mapping[str, Any]) -> bool:
    layout = node.get("layout")
    return isinstance(layout, Mapping) and layout.get("auto") is True


def _node_size(
    node: MutableMapping[str, Any],
    *,
    update_dimensions: bool,
    update_text: bool,
) -> Tuple[float, float, bool]:
    """Return a conservative node size and make requested defaults explicit.

    Dimension normalization is independent from coordinate layout: exporters
    require explicit geometry even when a semantic preparer has already supplied
    complete ``x``/``y`` coordinates.  Text wrapping remains limited to nodes
    participating in automatic coordinate layout so a size-only pass does not
    rewrite labels unexpectedly.
    """

    existing_width = _number(node.get("width"))
    existing_height = _number(node.get("height"))
    label = str(node.get("label", ""))
    sublabel = str(node.get("sublabel", ""))
    changed_wrap = False

    if existing_width and existing_width > 0:
        width = max(80.0, existing_width)
    else:
        desired = estimate_text_width(label, 18.0) + 44.0
        width = min(260.0, max(140.0, desired))
        if update_dimensions:
            node["width"] = _clean_number(width)

    content_width = max(48.0, width - 32.0)
    wrapped_label = wrap_text(label, content_width, 18.0)
    if update_text and wrapped_label != label.replace("\\n", "\n"):
        node["label"] = wrapped_label
        changed_wrap = True
    label_lines = max(1, len(wrapped_label.split("\n")))

    wrapped_sub = wrap_text(sublabel, content_width, 12.0) if sublabel else ""
    if update_text and sublabel and wrapped_sub != sublabel.replace("\\n", "\n"):
        node["sublabel"] = wrapped_sub
        changed_wrap = True
    sub_lines = len(wrapped_sub.split("\n")) if wrapped_sub else 0

    if existing_height and existing_height > 0:
        height = max(40.0, existing_height)
    else:
        type_allowance = 14.0 if node.get("type_label") else 0.0
        height = max(64.0, 30.0 + label_lines * 18.0 + sub_lines * 14.0 + type_allowance)
        if str(node.get("kind", node.get("shape", "rect"))) == "cylinder":
            height = max(height, 88.0)
        if update_dimensions:
            node["height"] = _clean_number(height)
    return width, height, changed_wrap


def _stable_layers(node_count: int, edges: Sequence[Tuple[int, int]]) -> Tuple[List[int], bool, int]:
    """Compute longest-path layers over a deterministic SCC condensation DAG."""

    adjacency: List[List[int]] = [[] for _ in range(node_count)]
    for source, target in sorted(set(edges)):
        adjacency[source].append(target)
    for neighbours in adjacency:
        neighbours.sort()

    index = 0
    indices = [-1] * node_count
    lowlink = [0] * node_count
    stack: List[int] = []
    on_stack = [False] * node_count
    components: List[List[int]] = []

    def strongconnect(vertex: int) -> None:
        nonlocal index
        indices[vertex] = index
        lowlink[vertex] = index
        index += 1
        stack.append(vertex)
        on_stack[vertex] = True
        for neighbour in adjacency[vertex]:
            if indices[neighbour] < 0:
                strongconnect(neighbour)
                lowlink[vertex] = min(lowlink[vertex], lowlink[neighbour])
            elif on_stack[neighbour]:
                lowlink[vertex] = min(lowlink[vertex], indices[neighbour])
        if lowlink[vertex] == indices[vertex]:
            component: List[int] = []
            while True:
                member = stack.pop()
                on_stack[member] = False
                component.append(member)
                if member == vertex:
                    break
            components.append(sorted(component))

    for vertex in range(node_count):
        if indices[vertex] < 0:
            strongconnect(vertex)

    components.sort(key=lambda members: members[0])
    component_of = [0] * node_count
    for component_index, members in enumerate(components):
        for member in members:
            component_of[member] = component_index

    dag: List[set[int]] = [set() for _ in components]
    indegree = [0] * len(components)
    self_loops = 0
    for source, target in set(edges):
        if source == target:
            self_loops += 1
        source_component = component_of[source]
        target_component = component_of[target]
        if source_component != target_component and target_component not in dag[source_component]:
            dag[source_component].add(target_component)
            indegree[target_component] += 1

    priority: List[Tuple[int, int]] = [
        (components[idx][0], idx) for idx, degree in enumerate(indegree) if degree == 0
    ]
    heapq.heapify(priority)
    component_layers = [0] * len(components)
    while priority:
        _, component_index = heapq.heappop(priority)
        for target_component in sorted(dag[component_index], key=lambda idx: components[idx][0]):
            component_layers[target_component] = max(
                component_layers[target_component], component_layers[component_index] + 1
            )
            indegree[target_component] -= 1
            if indegree[target_component] == 0:
                heapq.heappush(priority, (components[target_component][0], target_component))

    layers = [component_layers[component_of[idx]] for idx in range(node_count)]
    cyclic_components = sum(1 for members in components if len(members) > 1) + self_loops
    return layers, cyclic_components > 0, cyclic_components


def _container_index(
    node: Mapping[str, Any], aliases: Mapping[str, int]
) -> Optional[int]:
    for field in ("container_id", "container", "parent", "group"):
        value = node.get(field)
        if value is not None and str(value) in aliases:
            return aliases[str(value)]
    return None


def _region_for_container(container: Mapping[str, Any], fallback: Bounds) -> Bounds:
    x = _number(container.get("x"))
    y = _number(container.get("y"))
    width = _number(container.get("width"))
    height = _number(container.get("height"))
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return fallback
    header = max(24.0, _number(container.get("header_height")) or 30.0)
    padding = max(12.0, _number(container.get("layout_padding")) or 22.0)
    return (x + padding, y + header, x + width - padding, y + height - padding)


def _intersects(bounds: Bounds, obstacles: Iterable[Bounds], gap: float) -> bool:
    left, top, right, bottom = bounds
    for other_left, other_top, other_right, other_bottom in obstacles:
        if not (
            right + gap <= other_left
            or other_right + gap <= left
            or bottom + gap <= other_top
            or other_bottom + gap <= top
        ):
            return True
    return False


def _find_free_position(
    preferred_x: float,
    preferred_y: float,
    width: float,
    height: float,
    region: Bounds,
    obstacles: Sequence[Bounds],
    move_x: bool,
    move_y: bool,
    gap: float,
) -> Tuple[float, float]:
    """Find a stable nearby slot while respecting explicitly supplied axes."""

    left, top, right, bottom = region
    base_x = preferred_x
    base_y = preferred_y
    if move_x:
        base_x = min(max(base_x, left), max(left, right - width))
    if move_y:
        base_y = max(base_y, top)

    def free(x: float, y: float) -> bool:
        return not _intersects((x, y, x + width, y + height), obstacles, gap)

    if free(base_x, base_y):
        return base_x, base_y

    step = max(8.0, gap / 2.0)
    if move_y:
        # Downward movement preserves topological order and is stable when the
        # canvas later expands vertically.
        for attempt in range(1, 401):
            candidate_y = base_y + attempt * step
            if free(base_x, candidate_y):
                return base_x, candidate_y
    if move_x:
        span = max(0.0, right - left - width)
        attempts = max(1, int(span // step) + 2)
        for attempt in range(attempts):
            candidate_x = left + attempt * step
            if free(candidate_x, base_y):
                return candidate_x, base_y
    if move_x and move_y:
        for row in range(1, 201):
            candidate_y = base_y + row * (height + gap)
            for candidate_x in (left, base_x, max(left, right - width)):
                if free(candidate_x, candidate_y):
                    return candidate_x, candidate_y
    # This only occurs when both coordinates were explicitly pinned or the
    # diagram is extremely dense.  Returning the preferred point is safer than
    # silently changing a pinned coordinate; QA receives an overlap warning.
    return base_x, base_y


def _planned_positions_tb(
    indices: Sequence[int],
    layers: Sequence[int],
    sizes: Mapping[int, Tuple[float, float]],
    region: Bounds,
    horizontal_gap: float,
    vertical_gap: float,
) -> Dict[int, Tuple[float, float]]:
    left, top, right, _ = region
    available_width = max(80.0, right - left)
    by_layer: Dict[int, List[int]] = defaultdict(list)
    for index in indices:
        by_layer[layers[index]].append(index)

    planned: Dict[int, Tuple[float, float]] = {}
    cursor_y = top
    for layer in sorted(by_layer):
        layer_nodes = sorted(by_layer[layer])
        rows: List[List[int]] = []
        current: List[int] = []
        current_width = 0.0
        for index in layer_nodes:
            width, _ = sizes[index]
            candidate_width = width if not current else current_width + horizontal_gap + width
            if current and candidate_width > available_width:
                rows.append(current)
                current = [index]
                current_width = width
            else:
                current.append(index)
                current_width = candidate_width
        if current:
            rows.append(current)

        for row_index, row in enumerate(rows):
            row_width = sum(sizes[index][0] for index in row) + horizontal_gap * max(0, len(row) - 1)
            row_height = max(sizes[index][1] for index in row)
            cursor_x = left + max(0.0, (available_width - row_width) / 2.0)
            for index in row:
                width, height = sizes[index]
                planned[index] = (cursor_x, cursor_y + (row_height - height) / 2.0)
                cursor_x += width + horizontal_gap
            cursor_y += row_height
            cursor_y += vertical_gap * (0.62 if row_index < len(rows) - 1 else 1.0)
    return planned


def _planned_positions_lr(
    indices: Sequence[int],
    layers: Sequence[int],
    sizes: Mapping[int, Tuple[float, float]],
    region: Bounds,
    horizontal_gap: float,
    vertical_gap: float,
) -> Dict[int, Tuple[float, float]]:
    left, top, _, bottom = region
    available_height = max(80.0, bottom - top)
    by_layer: Dict[int, List[int]] = defaultdict(list)
    for index in indices:
        by_layer[layers[index]].append(index)

    planned: Dict[int, Tuple[float, float]] = {}
    cursor_x = left
    for layer in sorted(by_layer):
        layer_nodes = sorted(by_layer[layer])
        columns: List[List[int]] = []
        current: List[int] = []
        current_height = 0.0
        for index in layer_nodes:
            _, height = sizes[index]
            candidate_height = height if not current else current_height + vertical_gap + height
            if current and candidate_height > available_height:
                columns.append(current)
                current = [index]
                current_height = height
            else:
                current.append(index)
                current_height = candidate_height
        if current:
            columns.append(current)

        for column_index, column in enumerate(columns):
            column_width = max(sizes[index][0] for index in column)
            column_height = sum(sizes[index][1] for index in column) + vertical_gap * max(0, len(column) - 1)
            cursor_y = top + max(0.0, (available_height - column_height) / 2.0)
            for index in column:
                width, height = sizes[index]
                planned[index] = (cursor_x + (column_width - width) / 2.0, cursor_y)
                cursor_y += height + vertical_gap
            cursor_x += column_width
            cursor_x += horizontal_gap * (0.62 if column_index < len(columns) - 1 else 1.0)
    return planned


def _choose_ports(source: Mapping[str, Any], target: Mapping[str, Any]) -> Tuple[str, str]:
    sx = (_number(source.get("x")) or 0.0) + (_number(source.get("width")) or 180.0) / 2.0
    sy = (_number(source.get("y")) or 0.0) + (_number(source.get("height")) or 76.0) / 2.0
    tx = (_number(target.get("x")) or 0.0) + (_number(target.get("width")) or 180.0) / 2.0
    ty = (_number(target.get("y")) or 0.0) + (_number(target.get("height")) or 76.0) / 2.0
    dx, dy = tx - sx, ty - sy
    if abs(dx) > abs(dy) * 1.15:
        return ("right", "left") if dx >= 0 else ("left", "right")
    if abs(dy) > 1e-6:
        return ("bottom", "top") if dy >= 0 else ("top", "bottom")
    return ("right", "left") if dx >= 0 else ("left", "right")


def _assign_ports_and_clear_hints(
    result: MutableMapping[str, Any],
    nodes: Sequence[MutableMapping[str, Any]],
    moved_ids: set[str],
    preserve_route_hints: bool,
) -> Tuple[int, int, int]:
    arrows = result.get("arrows")
    if not isinstance(arrows, list):
        return 0, 0, 0
    node_by_id: Dict[str, MutableMapping[str, Any]] = {}
    for node in nodes:
        if node.get("id") is not None:
            node_by_id.setdefault(str(node["id"]), node)

    fields_assigned = 0
    arrows_configured = 0
    hints_removed = 0
    for arrow in arrows:
        if not isinstance(arrow, MutableMapping):
            continue
        source_id = str(arrow.get("source", ""))
        target_id = str(arrow.get("target", ""))
        source = node_by_id.get(source_id)
        target = node_by_id.get(target_id)
        if source is None or target is None:
            continue

        source_port = str(arrow.get("source_port", "")).strip().lower()
        target_port = str(arrow.get("target_port", "")).strip().lower()
        if source is target:
            suggested_source, suggested_target = "right", "top"
        elif source_port in _PORTS and target_port not in _PORTS:
            suggested_source, suggested_target = source_port, _OPPOSITE_PORT[source_port]
        elif target_port in _PORTS and source_port not in _PORTS:
            suggested_source, suggested_target = _OPPOSITE_PORT[target_port], target_port
        else:
            suggested_source, suggested_target = _choose_ports(source, target)

        assigned_this_arrow = False
        if source_port not in _PORTS:
            arrow["source_port"] = suggested_source
            fields_assigned += 1
            assigned_this_arrow = True
        if target_port not in _PORTS:
            arrow["target_port"] = suggested_target
            fields_assigned += 1
            assigned_this_arrow = True
        if assigned_this_arrow:
            arrows_configured += 1

        if not preserve_route_hints and (source_id in moved_ids or target_id in moved_ids):
            for field in _ROUTE_HINT_FIELDS:
                if field in arrow:
                    del arrow[field]
                    hints_removed += 1
    return fields_assigned, arrows_configured, hints_removed


def apply_auto_layout(data: Mapping[str, Any], template_type: str) -> Dict[str, Any]:
    """Return a deterministically laid-out deep copy of ``data``.

    Topological SCC condensation supplies stable layers, so cycles degrade to a
    deterministic same-layer placement instead of making layout fail.  Wide,
    standard, and document canvases share the same title-safe content contract;
    callers may select ``layout.direction`` as ``TB`` or ``LR``.
    """

    if not isinstance(data, Mapping):
        raise TypeError("data must be a mapping")
    result: Dict[str, Any] = copy.deepcopy(dict(data))
    raw_layout = result.get("layout")
    layout: Mapping[str, Any] = raw_layout if isinstance(raw_layout, Mapping) else {}
    force_auto = layout.get("auto") is True
    width, height = _canvas(result, template_type)
    original_width, original_height = width, height
    profile = _canvas_profile(width, height)
    horizontal_gap = max(24.0, _number(layout.get("horizontal_gap")) or 48.0)
    vertical_gap = max(24.0, _number(layout.get("vertical_gap")) or 52.0)
    minimum_gap = max(12.0, _number(layout.get("minimum_gap")) or 28.0)
    direction_raw = str(layout.get("direction", "TB")).strip().upper().replace("-", "")
    direction = "LR" if direction_raw in {"LR", "LEFTTORIGHT", "HORIZONTAL"} else "TB"

    nodes_value = result.get("nodes")
    nodes: List[MutableMapping[str, Any]] = (
        [node for node in nodes_value if isinstance(node, MutableMapping)]
        if isinstance(nodes_value, list)
        else []
    )

    eligible: List[int] = []
    existing_x: Dict[int, Optional[float]] = {}
    existing_y: Dict[int, Optional[float]] = {}
    for index, node in enumerate(nodes):
        existing_x[index] = _number(node.get("x"))
        existing_y[index] = _number(node.get("y"))
        if force_auto or _node_auto(node) or existing_x[index] is None or existing_y[index] is None:
            eligible.append(index)

    id_to_index: Dict[str, int] = {}
    for index, node in enumerate(nodes):
        if node.get("id") is not None:
            id_to_index.setdefault(str(node["id"]), index)
    graph_edges: List[Tuple[int, int]] = []
    arrows_value = result.get("arrows")
    if isinstance(arrows_value, list):
        for arrow in arrows_value:
            if not isinstance(arrow, Mapping):
                continue
            source = id_to_index.get(str(arrow.get("source", "")))
            target = id_to_index.get(str(arrow.get("target", "")))
            if source is not None and target is not None:
                graph_edges.append((source, target))
    layers, cycle_fallback, cyclic_components = _stable_layers(len(nodes), graph_edges)

    sizes: Dict[int, Tuple[float, float]] = {}
    wraps_applied = 0
    dimensions_assigned = 0
    eligible_set = set(eligible)
    for index, node in enumerate(nodes):
        before_width = _number(node.get("width"))
        before_height = _number(node.get("height"))
        node_width, node_height, wrapped = _node_size(
            node,
            update_dimensions=True,
            update_text=index in eligible_set,
        )
        sizes[index] = (node_width, node_height)
        wraps_applied += int(wrapped)
        dimensions_assigned += int(before_width is None or before_width <= 0) + int(
            before_height is None or before_height <= 0
        )

    top = _title_bottom(result) + 20.0
    bottom_reserve = 44.0
    legend = result.get("legend")
    if isinstance(legend, list) and legend:
        position = str(result.get("legend_position", "bottom-left"))
        if position.startswith("bottom"):
            bottom_reserve += len(legend) * 22.0 + 16.0
    if result.get("footer"):
        bottom_reserve += 26.0
    main_region: Bounds = (48.0, top, width - 48.0, max(top + 80.0, height - bottom_reserve))

    containers_value = result.get("containers")
    containers: List[MutableMapping[str, Any]] = (
        [container for container in containers_value if isinstance(container, MutableMapping)]
        if isinstance(containers_value, list)
        else []
    )
    aliases: Dict[str, int] = {}
    for index, container in enumerate(containers):
        for field in ("id", "name", "label"):
            if container.get(field) not in (None, ""):
                aliases.setdefault(str(container[field]), index)

    group_for: Dict[int, Optional[int]] = {
        index: _container_index(nodes[index], aliases) for index in eligible
    }
    groups: Dict[Optional[int], List[int]] = defaultdict(list)
    for index in eligible:
        groups[group_for[index]].append(index)

    obstacles: List[Bounds] = []
    for index, node in enumerate(nodes):
        if index in eligible_set:
            continue
        x, y = existing_x[index], existing_y[index]
        if x is not None and y is not None:
            node_width, node_height = sizes[index]
            obstacles.append((x, y, x + node_width, y + node_height))

    moved_ids: set[str] = set()
    positioned = 0
    partial_axes_preserved = 0
    overlap_warnings = 0
    container_overflow: set[int] = set()
    max_right = width
    max_bottom = height

    # Assigned containers are handled in declaration order; unassigned nodes are
    # placed last so they can avoid already positioned container nodes.
    group_keys = sorted((key for key in groups if key is not None))
    if None in groups:
        group_keys.append(None)
    for group_key in group_keys:
        indices = groups[group_key]
        region = main_region if group_key is None else _region_for_container(containers[group_key], main_region)
        planner = _planned_positions_lr if direction == "LR" else _planned_positions_tb
        planned = planner(indices, layers, sizes, region, horizontal_gap, vertical_gap)
        group_layers: Dict[int, List[int]] = defaultdict(list)
        for index in indices:
            group_layers[layers[index]].append(index)
        prior_layer_extent: Optional[float] = None
        for layer_number in sorted(group_layers):
            layer_indices = sorted(group_layers[layer_number])
            if direction == "LR":
                planned_origin = min(planned[index][0] for index in layer_indices)
            else:
                planned_origin = min(planned[index][1] for index in layer_indices)
            layer_offset = 0.0
            if prior_layer_extent is not None:
                layer_offset = max(0.0, prior_layer_extent + (horizontal_gap if direction == "LR" else vertical_gap) - planned_origin)
            current_layer_extent = prior_layer_extent or 0.0

            for index in layer_indices:
                node = nodes[index]
                node_width, node_height = sizes[index]
                preferred_x, preferred_y = planned[index]
                if direction == "LR":
                    preferred_x += layer_offset
                else:
                    preferred_y += layer_offset
                node_force = force_auto or _node_auto(node)
                supplied_x = existing_x[index]
                supplied_y = existing_y[index]
                move_x = node_force or supplied_x is None
                move_y = node_force or supplied_y is None
                x = preferred_x if move_x else float(supplied_x)
                y = preferred_y if move_y else float(supplied_y)
                partial_axes_preserved += int((not move_x) ^ (not move_y))
                x, y = _find_free_position(
                    x, y, node_width, node_height, region, obstacles, move_x, move_y, minimum_gap
                )
                bounds = (x, y, x + node_width, y + node_height)
                if _intersects(bounds, obstacles, minimum_gap):
                    overlap_warnings += 1
                node["x"] = _clean_number(x)
                node["y"] = _clean_number(y)
                obstacles.append(bounds)
                positioned += 1
                current_layer_extent = max(current_layer_extent, bounds[2] if direction == "LR" else bounds[3])
                if node.get("id") is not None:
                    moved_ids.add(str(node["id"]))
                max_right = max(max_right, bounds[2] + 48.0)
                max_bottom = max(max_bottom, bounds[3] + bottom_reserve)
                if group_key is not None:
                    _, _, region_right, region_bottom = region
                    if bounds[2] > region_right + 0.01 or bounds[3] > region_bottom + 0.01:
                        container_overflow.add(group_key)
            prior_layer_extent = current_layer_extent

    preserve_aspect = layout.get("preserve_aspect") is not False
    final_width = max(width, max_right)
    final_height = max(height, max_bottom)
    if preserve_aspect and profile == "widescreen":
        aspect = original_width / original_height
        final_width = max(final_width, final_height * aspect)
        final_height = max(final_height, final_width / aspect)
    elif preserve_aspect and profile == "document":
        aspect = original_width / original_height
        final_width = max(final_width, final_height * aspect)
        final_height = max(final_height, final_width / aspect)

    if final_width > original_width + 0.01:
        result["width"] = _clean_number(final_width)
    if final_height > original_height + 0.01:
        result["height"] = _clean_number(final_height)

    ports_assigned, arrows_configured, hints_removed = _assign_ports_and_clear_hints(
        result,
        nodes,
        moved_ids,
        preserve_route_hints=layout.get("preserve_route_hints") is True,
    )

    layer_sizes: Dict[str, int] = defaultdict(int)
    for index in eligible:
        layer_sizes[str(layers[index])] += 1
    warnings: List[str] = []
    if container_overflow:
        warnings.append("assigned nodes exceed one or more fixed container bounds")
    if overlap_warnings:
        warnings.append("one or more pinned/dense nodes could not satisfy minimum spacing")
    if cycle_fallback:
        warnings.append("cyclic components were placed deterministically on the same layer")

    result["_layout_stats"] = {
        "enabled": bool(eligible),
        "requested_nodes": len(eligible),
        "positioned_nodes": positioned,
        "preserved_nodes": max(0, len(nodes) - len(eligible)),
        "partial_axes_preserved": partial_axes_preserved,
        "layers": (max(layers[index] for index in eligible) + 1) if eligible else 0,
        "layer_sizes": dict(sorted(layer_sizes.items(), key=lambda item: int(item[0]))),
        "cycle_fallback": cycle_fallback,
        "cyclic_components": cyclic_components,
        "ports_assigned": ports_assigned,
        "arrows_configured": arrows_configured,
        "route_hints_removed": hints_removed,
        "dimensions_assigned": dimensions_assigned,
        "wraps_applied": wraps_applied,
        "minimum_gap": _clean_number(minimum_gap),
        "direction": direction,
        "container_overflow": len(container_overflow),
        "overlap_warnings": overlap_warnings,
        "canvas": {
            "profile": profile,
            "original": [_clean_number(original_width), _clean_number(original_height)],
            "final": [_clean_number(final_width), _clean_number(final_height)],
            "expanded": final_width > original_width + 0.01 or final_height > original_height + 0.01,
        },
        "warnings": warnings,
    }
    return result


__all__ = ["apply_auto_layout", "estimate_text_width", "wrap_text"]
