#!/usr/bin/env python3
"""Normalize diagram-specific input into the renderer's common model.

``prepare_diagram`` is intentionally free of SVG concerns.  It validates the
semantic model, assigns a deterministic starter layout where one is needed,
and returns ordinary ``nodes`` and ``arrows``.  The input mapping is never
modified.
"""

from __future__ import annotations

import copy
import math
import re
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Dict, Iterable, List, MutableMapping, Optional, Tuple


SUPPORTED_DIAGRAM_TYPES = frozenset(
    {
        "architecture",
        "data-flow",
        "flowchart",
        "sequence",
        "state-machine",
        "er-diagram",
        "use-case",
        "timeline",
    }
)


_TYPE_ALIASES = {
    "architecture": "architecture",
    "system-architecture": "architecture",
    "agent-architecture": "architecture",
    "agent": "architecture",
    "memory": "architecture",
    "network-topology": "architecture",
    "comparison": "architecture",
    "comparison-matrix": "architecture",
    "data-flow": "data-flow",
    "dataflow": "data-flow",
    "dfd": "data-flow",
    "flowchart": "flowchart",
    "flow-chart": "flowchart",
    "process-flow": "flowchart",
    "sequence": "sequence",
    "sequence-diagram": "sequence",
    "state-machine": "state-machine",
    "statechart": "state-machine",
    "state-diagram": "state-machine",
    "er": "er-diagram",
    "erd": "er-diagram",
    "er-diagram": "er-diagram",
    "entity-relationship": "er-diagram",
    "use-case": "use-case",
    "usecase": "use-case",
    "use-case-diagram": "use-case",
    "timeline": "timeline",
}


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _canonical_type(value: object, path: str = "template_type") -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    token = re.sub(r"[\s_]+", "-", value.strip().lower())
    canonical = _TYPE_ALIASES.get(token)
    if canonical is None:
        supported = ", ".join(sorted(SUPPORTED_DIAGRAM_TYPES))
        _fail(path, f"unsupported diagram type {value!r}; expected one of {supported}")
    return canonical


def _list(value: object, path: str, *, required: bool = False) -> List[object]:
    if value is None:
        if required:
            _fail(path, "is required")
        return []
    if not isinstance(value, list):
        _fail(path, "must be an array")
    if required and not value:
        _fail(path, "must contain at least one item")
    return value


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _string(value: object, path: str, *, required: bool = True) -> str:
    if value is None:
        if required:
            _fail(path, "is required")
        return ""
    if not isinstance(value, str):
        _fail(path, "must be a string")
    result = value.strip()
    if required and not result:
        _fail(path, "must be a non-empty string")
    return result


def _number(value: object, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a number")
    result = float(value)
    if not math.isfinite(result):
        _fail(path, "must be finite")
    if positive and result <= 0:
        _fail(path, "must be greater than zero")
    return result


def _item_id(item: Mapping[str, object], path: str) -> str:
    return _string(item.get("id"), f"{path}.id")


def _label(
    item: Mapping[str, object],
    path: str,
    *,
    default: Optional[str] = None,
    required: bool = True,
) -> str:
    raw = item.get("label", item.get("name", item.get("title")))
    if raw is None and default is not None:
        return default
    return _string(raw, f"{path}.label", required=required)


def _check_unique(identifier: str, path: str, seen: MutableMapping[str, str]) -> None:
    if identifier in seen:
        _fail(path, f"duplicate id {identifier!r}; first declared at {seen[identifier]}")
    seen[identifier] = path


def _relation_ends(
    item: Mapping[str, object], path: str, known_ids: Iterable[str]
) -> Tuple[str, str]:
    source = _string(item.get("from", item.get("source")), f"{path}.from")
    target = _string(item.get("to", item.get("target")), f"{path}.to")
    known = set(known_ids)
    if source not in known:
        _fail(f"{path}.from", f"references unknown id {source!r}")
    if target not in known:
        _fail(f"{path}.to", f"references unknown id {target!r}")
    return source, target


def _base(data: Mapping[str, object], consumed: Sequence[str]) -> Dict[str, object]:
    result = copy.deepcopy(dict(data))
    for key in consumed:
        result.pop(key, None)
    return result


def _node_size(node: Mapping[str, object]) -> Tuple[float, float]:
    width = node.get("width", 180)
    height = node.get("height", 72)
    return float(width), float(height)


def _layered_layout(
    nodes: List[Dict[str, object]],
    edges: Sequence[Tuple[str, str]],
    *,
    canvas_width: float,
    start_y: float = 126,
    horizontal_gap: float = 64,
    vertical_gap: float = 84,
) -> Tuple[float, float]:
    """Fill missing x/y values while retaining all explicit coordinates."""

    if not nodes:
        return canvas_width, start_y

    order = [str(node["id"]) for node in nodes]
    positions = {identifier: index for index, identifier in enumerate(order)}
    incoming = {identifier: 0 for identifier in order}
    outgoing = {identifier: [] for identifier in order}
    for source, target in edges:
        if source in outgoing and target in incoming and source != target:
            outgoing[source].append(target)
            incoming[target] += 1

    rank = {identifier: 0 for identifier in order}
    queue = deque(identifier for identifier in order if incoming[identifier] == 0)
    processed = set()
    while queue:
        identifier = queue.popleft()
        processed.add(identifier)
        for target in outgoing[identifier]:
            rank[target] = max(rank[target], rank[identifier] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)

    # Cycles are valid in flows and state machines.  Keep unresolved nodes in
    # deterministic input order instead of repeatedly relaxing the cycle.
    unresolved = [identifier for identifier in order if identifier not in processed]
    if unresolved:
        cycle_rank = max(rank.values(), default=-1) + 1
        for identifier in unresolved:
            rank[identifier] = cycle_rank

    layers: Dict[int, List[Dict[str, object]]] = {}
    for node in sorted(nodes, key=lambda item: positions[str(item["id"])]):
        layers.setdefault(rank[str(node["id"])], []).append(node)

    maximum_right = canvas_width
    maximum_bottom = start_y
    current_y = start_y
    for layer_index in sorted(layers):
        layer = layers[layer_index]
        widths = [_node_size(node)[0] for node in layer]
        heights = [_node_size(node)[1] for node in layer]
        total_width = sum(widths) + horizontal_gap * max(0, len(layer) - 1)
        required_width = total_width + 80
        canvas_width = max(canvas_width, required_width)
        cursor_x = max(40.0, (canvas_width - total_width) / 2)
        layer_height = max(heights, default=72)
        for node, width, height in zip(layer, widths, heights):
            if "x" not in node:
                node["x"] = round(cursor_x, 2)
            if "y" not in node:
                node["y"] = round(current_y + (layer_height - height) / 2, 2)
            cursor_x += width + horizontal_gap
            maximum_right = max(maximum_right, float(node["x"]) + width + 40)
            maximum_bottom = max(maximum_bottom, float(node["y"]) + height + 40)
        current_y += layer_height + vertical_gap
    return max(canvas_width, maximum_right), maximum_bottom


def _grid_layout(
    nodes: List[Dict[str, object]],
    *,
    canvas_width: float,
    start_y: float = 126,
    columns: Optional[int] = None,
) -> Tuple[float, float]:
    if not nodes:
        return canvas_width, start_y
    columns = columns or max(1, min(4, math.ceil(math.sqrt(len(nodes)))))
    cell_width = max(210.0, (canvas_width - 80) / columns)
    row_height = max((_node_size(node)[1] for node in nodes), default=72) + 76
    for index, node in enumerate(nodes):
        width, height = _node_size(node)
        row, column = divmod(index, columns)
        if "x" not in node:
            node["x"] = round(40 + column * cell_width + (cell_width - width) / 2, 2)
        if "y" not in node:
            node["y"] = round(start_y + row * row_height, 2)
    rows = math.ceil(len(nodes) / columns)
    return max(canvas_width, 80 + columns * cell_width), start_y + rows * row_height + 20


def _set_ports(arrow: Dict[str, object], nodes: Mapping[str, Mapping[str, object]]) -> None:
    source = nodes.get(str(arrow.get("source", "")))
    target = nodes.get(str(arrow.get("target", "")))
    if source is None or target is None or source is target:
        return
    sw, sh = _node_size(source)
    tw, th = _node_size(target)
    sx = float(source.get("x", 0)) + sw / 2
    sy = float(source.get("y", 0)) + sh / 2
    tx = float(target.get("x", 0)) + tw / 2
    ty = float(target.get("y", 0)) + th / 2
    if abs(ty - sy) >= abs(tx - sx):
        arrow.setdefault("source_port", "bottom" if ty >= sy else "top")
        arrow.setdefault("target_port", "top" if ty >= sy else "bottom")
    else:
        arrow.setdefault("source_port", "right" if tx >= sx else "left")
        arrow.setdefault("target_port", "left" if tx >= sx else "right")


def _validate_common(result: Dict[str, object]) -> None:
    nodes = _list(result.get("nodes", []), "nodes")
    arrows = _list(result.get("arrows", []), "arrows")
    known: Dict[str, str] = {}
    for index, raw_node in enumerate(nodes):
        path = f"nodes[{index}]"
        node = _mapping(raw_node, path)
        identifier = _item_id(node, path)
        _check_unique(identifier, f"{path}.id", known)
        for key in ("x", "y"):
            if key in node:
                _number(node[key], f"{path}.{key}")
        for key in ("width", "height"):
            if key in node:
                _number(node[key], f"{path}.{key}", positive=True)

    ids = set(known)
    for index, raw_arrow in enumerate(arrows):
        path = f"arrows[{index}]"
        arrow = _mapping(raw_arrow, path)
        source = arrow.get("source")
        target = arrow.get("target")
        if source is not None:
            source_id = _string(source, f"{path}.source")
            if source_id not in ids:
                _fail(f"{path}.source", f"references unknown node {source_id!r}")
        if target is not None:
            target_id = _string(target, f"{path}.target")
            if target_id not in ids:
                _fail(f"{path}.target", f"references unknown node {target_id!r}")
        if source is None:
            for key in ("x1", "y1"):
                if key not in arrow:
                    _fail(f"{path}.{key}", "is required when source is omitted")
                _number(arrow[key], f"{path}.{key}")
        if target is None:
            for key in ("x2", "y2"):
                if key not in arrow:
                    _fail(f"{path}.{key}", "is required when target is omitted")
                _number(arrow[key], f"{path}.{key}")


def _prepare_generic(data: Mapping[str, object]) -> Dict[str, object]:
    result = _base(data, ())
    nodes = _list(result.get("nodes", []), "nodes")
    arrows = _list(result.get("arrows", []), "arrows")
    # Validate identifiers and references before layout so malformed input
    # reports a field path rather than leaking a KeyError from the layout code.
    _validate_common(result)
    mutable_nodes = [dict(node) if isinstance(node, Mapping) else node for node in nodes]
    result["nodes"] = mutable_nodes
    edge_pairs = []
    for arrow in arrows:
        if isinstance(arrow, Mapping) and arrow.get("source") and arrow.get("target"):
            edge_pairs.append((str(arrow["source"]), str(arrow["target"])))
    width = float(result.get("width", 960))
    width, required_height = _layered_layout(
        mutable_nodes, edge_pairs, canvas_width=width
    )
    if mutable_nodes:
        result["width"] = max(float(result.get("width", 0)), width)
        result["height"] = max(float(result.get("height", 0)), required_height)
    node_map = {str(node["id"]): node for node in mutable_nodes if isinstance(node, Mapping) and "id" in node}
    result["arrows"] = [dict(arrow) if isinstance(arrow, Mapping) else arrow for arrow in arrows]
    for arrow in result["arrows"]:
        if isinstance(arrow, dict):
            _set_ports(arrow, node_map)
    return result


def _prepare_architecture(data: Mapping[str, object]) -> Dict[str, object]:
    if "components" not in data and "connections" not in data and "relationships" not in data:
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with architecture components/connections")
    components = _list(data.get("components"), "components", required=True)
    links = _list(
        data.get("connections", data.get("relationships", [])), "connections"
    )
    result = _base(data, ("components", "connections", "relationships"))
    seen: Dict[str, str] = {}
    nodes: List[Dict[str, object]] = []
    for index, raw in enumerate(components):
        path = f"components[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        node = copy.deepcopy(dict(item))
        node["id"] = identifier
        node["label"] = _label(item, path)
        node.setdefault("kind", "rect")
        node.setdefault("semantic_type", "component")
        if item.get("type") and not item.get("type_label"):
            node["type_label"] = _string(item["type"], f"{path}.type", required=False).upper()
        nodes.append(node)
    arrows: List[Dict[str, object]] = []
    for index, raw in enumerate(links):
        path = f"connections[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        arrow = copy.deepcopy(dict(item))
        arrow.pop("from", None)
        arrow.pop("to", None)
        arrow["source"] = source
        arrow["target"] = target
        arrow.setdefault("flow", "control")
        arrow.setdefault("semantic_type", "connection")
        arrows.append(arrow)
    result["nodes"] = nodes
    result["arrows"] = arrows
    return _prepare_generic(result)


def _prepare_data_flow(data: Mapping[str, object]) -> Dict[str, object]:
    semantic_keys = {
        "external_entities",
        "externalEntities",
        "processes",
        "data_stores",
        "dataStores",
    }
    if not semantic_keys.intersection(data):
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with data-flow semantic collections")
    entity_key = "external_entities" if "external_entities" in data else "externalEntities"
    store_key = "data_stores" if "data_stores" in data else "dataStores"
    groups = [
        (entity_key, _list(data.get(entity_key, []), entity_key), "external-entity", "rect"),
        ("processes", _list(data.get("processes", []), "processes"), "process", "process"),
        (store_key, _list(data.get(store_key, []), store_key), "data-store", "data-store"),
    ]
    if not any(items for _, items, _, _ in groups):
        _fail("processes", "data-flow requires at least one entity, process, or data store")
    result = _base(
        data,
        ("external_entities", "externalEntities", "processes", "data_stores", "dataStores", "flows"),
    )
    seen: Dict[str, str] = {}
    nodes: List[Dict[str, object]] = []
    for key, items, semantic_type, kind in groups:
        for index, raw in enumerate(items):
            path = f"{key}[{index}]"
            item = _mapping(raw, path)
            identifier = _item_id(item, path)
            _check_unique(identifier, f"{path}.id", seen)
            node = copy.deepcopy(dict(item))
            node["id"] = identifier
            node["label"] = _label(item, path)
            node.setdefault("kind", kind)
            node["semantic_type"] = semantic_type
            node.setdefault("type_label", semantic_type.replace("-", " ").upper())
            nodes.append(node)
    arrows: List[Dict[str, object]] = []
    for index, raw in enumerate(_list(data.get("flows", []), "flows")):
        path = f"flows[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        arrow = copy.deepcopy(dict(item))
        arrow.pop("from", None)
        arrow.pop("to", None)
        arrow["source"] = source
        arrow["target"] = target
        arrow["label"] = _string(item.get("label"), f"{path}.label")
        arrow.setdefault("flow", "data")
        arrow["semantic_type"] = "data-flow"
        arrows.append(arrow)
    result["nodes"] = nodes
    result["arrows"] = arrows
    return _prepare_generic(result)


_FLOW_STEP_ALIASES = {
    "start": "start",
    "initial": "start",
    "start-event": "start",
    "end": "end",
    "stop": "end",
    "final": "end",
    "end-event": "end",
    "process": "process",
    "action": "process",
    "task": "process",
    "decision": "decision",
    "condition": "decision",
    "gateway": "decision",
}


def _prepare_flowchart(data: Mapping[str, object]) -> Dict[str, object]:
    if "steps" not in data and "flows" not in data:
        return _prepare_generic(data)
    step_key = "steps" if "steps" in data else "nodes"
    flow_key = "flows" if "flows" in data else "arrows"
    steps = _list(data.get(step_key), step_key, required=True)
    flows = _list(data.get(flow_key, []), flow_key)
    result = _base(data, ("steps", "flows", "nodes", "arrows"))
    seen: Dict[str, str] = {}
    nodes: List[Dict[str, object]] = []
    step_types: Dict[str, str] = {}
    for index, raw in enumerate(steps):
        path = f"{step_key}[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        declared = item.get("type", item.get("node_type"))
        if declared is None and str(item.get("kind", "")).lower() in _FLOW_STEP_ALIASES:
            declared = item.get("kind")
        token = str(declared or "process").strip().lower().replace("_", "-")
        step_type = _FLOW_STEP_ALIASES.get(token)
        if step_type is None:
            _fail(f"{path}.type", "must be start, end, process, or decision")
        default_label = "Start" if step_type == "start" else "End" if step_type == "end" else None
        node = copy.deepcopy(dict(item))
        for key in ("type", "node_type"):
            node.pop(key, None)
        node["id"] = identifier
        node["label"] = _label(item, path, default=default_label)
        node["semantic_type"] = step_type
        node["type_label"] = step_type.upper()
        if step_type in {"start", "end"}:
            node["kind"] = "terminator"
            node.setdefault("width", 132)
            node.setdefault("height", 48)
        elif step_type == "decision":
            node["kind"] = "diamond"
            node.setdefault("width", 170)
            node.setdefault("height", 104)
        else:
            node["kind"] = "process"
            node.setdefault("width", 180)
            node.setdefault("height", 66)
        nodes.append(node)
        step_types[identifier] = step_type

    if "start" not in step_types.values():
        _fail(step_key, "must contain at least one start step")
    if "end" not in step_types.values():
        _fail(step_key, "must contain at least one end step")

    arrows: List[Dict[str, object]] = []
    outgoing: Dict[str, int] = {identifier: 0 for identifier in seen}
    for index, raw in enumerate(flows):
        path = f"{flow_key}[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        outgoing[source] += 1
        arrow = copy.deepcopy(dict(item))
        arrow.pop("from", None)
        arrow.pop("to", None)
        arrow["source"] = source
        arrow["target"] = target
        arrow.setdefault("flow", "control")
        arrow["semantic_type"] = "flow"
        arrows.append(arrow)
    for identifier, count in outgoing.items():
        if step_types[identifier] == "decision" and count < 2:
            _fail(
                f"{step_key}[{list(seen).index(identifier)}]",
                "decision must have at least two outgoing flows",
            )
    result["nodes"] = nodes
    result["arrows"] = arrows
    return _prepare_generic(result)


_MESSAGE_TYPES = {
    "sync": "sync",
    "synchronous": "sync",
    "call": "sync",
    "async": "async",
    "asynchronous": "async",
    "signal": "async",
    "return": "return",
    "reply": "return",
    "response": "return",
}


def _prepare_sequence(data: Mapping[str, object]) -> Dict[str, object]:
    if "participants" not in data and "messages" not in data:
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with sequence participants/messages")
    participants = _list(data.get("participants"), "participants", required=True)
    messages = _list(data.get("messages", []), "messages")
    lifeline_spec = data.get("lifelines", None)
    result = _base(data, ("participants", "messages", "lifelines"))
    seen: Dict[str, str] = {}
    normalized_participants: List[Tuple[str, Mapping[str, object], str]] = []
    for index, raw in enumerate(participants):
        path = f"participants[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        normalized_participants.append((identifier, item, _label(item, path)))

    width = max(float(result.get("width", 960)), 220 + len(participants) * 180)
    head_y = 116.0
    head_width = min(164.0, max(112.0, (width - 100) / len(participants) - 38))
    head_height = 58.0
    edge_margin = head_width / 2 + 40
    centers = {
        identifier: edge_margin
        + index * ((width - 2 * edge_margin) / max(1, len(participants) - 1))
        for index, (identifier, _, _) in enumerate(normalized_participants)
    }
    if len(participants) == 1:
        centers[normalized_participants[0][0]] = width / 2

    nodes: List[Dict[str, object]] = []
    for identifier, item, label in normalized_participants:
        node = copy.deepcopy(dict(item))
        node["id"] = identifier
        node["label"] = label
        node["kind"] = "participant"
        node["semantic_type"] = "participant"
        node.setdefault("type_label", "PARTICIPANT")
        node.setdefault("width", head_width)
        node.setdefault("height", head_height)
        node.setdefault("x", round(centers[identifier] - float(node["width"]) / 2, 2))
        node.setdefault("y", head_y)
        nodes.append(node)
        centers[identifier] = float(node["x"]) + float(node["width"]) / 2

    message_rows: List[Tuple[Mapping[str, object], str, str, str, float]] = []
    current_y = head_y + head_height + 52
    for index, raw in enumerate(messages):
        path = f"messages[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        if bool(item.get("return")) and bool(item.get("async")):
            _fail(path, "return and async cannot both be true")
        raw_type = (
            "return"
            if bool(item.get("return"))
            else "async"
            if bool(item.get("async"))
            else item.get("type", item.get("message_type", "sync"))
        )
        token = str(raw_type).strip().lower().replace("_", "-")
        message_type = _MESSAGE_TYPES.get(token)
        if message_type is None:
            _fail(f"{path}.type", "must be sync, async, or return")
        message_rows.append((item, source, target, message_type, current_y))
        current_y += 66 if source == target else 50

    lifeline_bottom = max(current_y + 16, head_y + head_height + 150)
    enabled_lifelines = set(seen)
    lifeline_overrides: Dict[str, Mapping[str, object]] = {}
    if isinstance(lifeline_spec, bool):
        if not lifeline_spec:
            enabled_lifelines.clear()
    elif lifeline_spec is not None:
        entries = _list(lifeline_spec, "lifelines")
        enabled_lifelines.clear()
        for index, raw in enumerate(entries):
            path = f"lifelines[{index}]"
            if isinstance(raw, str):
                identifier = _string(raw, path)
                item = {}
            else:
                item = _mapping(raw, path)
                identifier = _string(item.get("participant", item.get("id")), f"{path}.participant")
            if identifier not in seen:
                _fail(f"{path}.participant", f"references unknown participant {identifier!r}")
            enabled_lifelines.add(identifier)
            lifeline_overrides[identifier] = item
    elif lifeline_spec is not None and not isinstance(lifeline_spec, (list, bool)):
        _fail("lifelines", "must be a boolean or an array")

    arrows: List[Dict[str, object]] = []
    for identifier in seen:
        if identifier not in enabled_lifelines:
            continue
        override = lifeline_overrides.get(identifier, {})
        x = centers[identifier]
        start = override.get("start_y", head_y + head_height)
        end = override.get("end_y", lifeline_bottom)
        start_y = _number(start, f"lifelines[{identifier}].start_y")
        end_y = _number(end, f"lifelines[{identifier}].end_y")
        if end_y <= start_y:
            _fail(f"lifelines[{identifier}].end_y", "must be greater than start_y")
        arrows.append(
            {
                "x1": x,
                "y1": start_y,
                "x2": x,
                "y2": end_y,
                "flow": "neutral",
                "dashed": bool(override.get("dashed", True)),
                "marker_end": False,
                "stroke_width": 1.35,
                "semantic_type": "lifeline",
                "participant": identifier,
            }
        )

    for index, (item, source, target, message_type, y) in enumerate(message_rows):
        path = f"messages[{index}]"
        arrow = copy.deepcopy(dict(item))
        for key in ("from", "to", "source", "target", "return", "async", "type", "message_type"):
            arrow.pop(key, None)
        arrow.update(
            {
                "x1": centers[source],
                "y1": y,
                "x2": centers[target],
                "y2": y + (30 if source == target else 0),
                "semantic_type": "message",
                "semantic_source": source,
                "semantic_target": target,
                "sequence_message_type": message_type,
                "flow": "async" if message_type == "async" else "feedback" if message_type == "return" else "control",
            }
        )
        if "label" in item:
            arrow["label"] = _string(item.get("label"), f"{path}.label", required=False)
        if message_type == "return":
            arrow["dashed"] = True
        if source == target:
            loop_x = centers[source] + 54
            arrow["route_points"] = [[loop_x, y], [loop_x, y + 30]]
        arrows.append(arrow)

    result["nodes"] = nodes
    result["arrows"] = arrows
    result["width"] = width
    result["height"] = max(float(result.get("height", 0)), lifeline_bottom + 50)
    return result


_STATE_TYPES = {
    "state": "state",
    "normal": "state",
    "initial": "initial",
    "start": "initial",
    "initial-state": "initial",
    "final": "final",
    "end": "final",
    "final-state": "final",
}


def _prepare_state_machine(data: Mapping[str, object]) -> Dict[str, object]:
    if "states" not in data and "transitions" not in data:
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with states/transitions")
    states = _list(data.get("states"), "states", required=True)
    transitions = _list(data.get("transitions", []), "transitions")
    result = _base(data, ("states", "transitions"))
    seen: Dict[str, str] = {}
    nodes: List[Dict[str, object]] = []
    for index, raw in enumerate(states):
        path = f"states[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        token = str(item.get("type", item.get("state_type", "state"))).strip().lower().replace("_", "-")
        state_type = _STATE_TYPES.get(token)
        if state_type is None:
            _fail(f"{path}.type", "must be initial, state, or final")
        node = copy.deepcopy(dict(item))
        node.pop("type", None)
        node.pop("state_type", None)
        node["id"] = identifier
        node["semantic_type"] = state_type
        if state_type == "initial":
            node["kind"] = "initial"
            node["label"] = _label(item, path, default="", required=False)
            node.setdefault("width", 28)
            node.setdefault("height", 28)
        elif state_type == "final":
            node["kind"] = "final"
            node["label"] = _label(item, path, default="", required=False)
            node.setdefault("width", 34)
            node.setdefault("height", 34)
        else:
            node["kind"] = "state"
            node["label"] = _label(item, path)
            node.setdefault("width", 178)
            node.setdefault("height", 68)
            node.setdefault("type_label", "STATE")
        nodes.append(node)

    arrows: List[Dict[str, object]] = []
    edges: List[Tuple[str, str]] = []
    for index, raw in enumerate(transitions):
        path = f"transitions[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        edges.append((source, target))
        guard = _string(item.get("guard"), f"{path}.guard", required=False) if "guard" in item else ""
        action = _string(item.get("action"), f"{path}.action", required=False) if "action" in item else ""
        explicit_label = _string(item.get("label"), f"{path}.label", required=False) if "label" in item else ""
        composed = explicit_label
        if not composed and guard:
            composed = f"[{guard}]"
        if action:
            composed = f"{composed} / {action}" if composed else action
        arrow = copy.deepcopy(dict(item))
        for key in ("from", "to", "guard", "action"):
            arrow.pop(key, None)
        arrow["source"] = source
        arrow["target"] = target
        arrow["label"] = composed
        arrow.setdefault("flow", "control")
        arrow["semantic_type"] = "transition"
        arrows.append(arrow)

    width = float(result.get("width", 960))
    width, height = _layered_layout(nodes, edges, canvas_width=width)
    node_map = {str(node["id"]): node for node in nodes}
    for arrow in arrows:
        if arrow["source"] == arrow["target"]:
            node = node_map[str(arrow["source"])]
            x, y = float(node["x"]), float(node["y"])
            node_width, node_height = _node_size(node)
            arrow.setdefault("source_port", "right")
            arrow.setdefault("target_port", "bottom")
            arrow.setdefault(
                "route_points",
                [
                    [x + node_width + 44, y + node_height / 2],
                    [x + node_width + 44, y + node_height + 42],
                    [x + node_width / 2, y + node_height + 42],
                ],
            )
        else:
            _set_ports(arrow, node_map)
    result["nodes"] = nodes
    result["arrows"] = arrows
    result["width"] = width
    result["height"] = max(float(result.get("height", 0)), height)
    return result


_KEY_TYPES = {"", "PK", "FK", "UK", "PK/FK", "FK/PK"}


def _normalize_attribute(raw: object, path: str) -> Dict[str, object]:
    if isinstance(raw, str):
        return {"name": _string(raw, path), "key": "", "type": ""}
    item = _mapping(raw, path)
    name = _string(item.get("name"), f"{path}.name")
    key = _string(item.get("key"), f"{path}.key", required=False).upper()
    if key not in _KEY_TYPES:
        _fail(f"{path}.key", "must be PK, FK, UK, PK/FK, or empty")
    attribute_type = _string(item.get("type"), f"{path}.type", required=False)
    result = copy.deepcopy(dict(item))
    result.update({"name": name, "key": key, "type": attribute_type})
    return result


def _cardinality(value: object, path: str) -> str:
    result = _string(value, path, required=False)
    if len(result) > 24:
        _fail(path, "must be 24 characters or fewer")
    return result


def _prepare_er(data: Mapping[str, object]) -> Dict[str, object]:
    if "entities" not in data and "relationships" not in data:
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with entities/relationships")
    entities = _list(data.get("entities"), "entities", required=True)
    relationships = _list(data.get("relationships", []), "relationships")
    result = _base(data, ("entities", "relationships"))
    seen: Dict[str, str] = {}
    nodes: List[Dict[str, object]] = []
    for index, raw in enumerate(entities):
        path = f"entities[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        attributes = [
            _normalize_attribute(attribute, f"{path}.attributes[{attribute_index}]")
            for attribute_index, attribute in enumerate(_list(item.get("attributes", []), f"{path}.attributes"))
        ]
        lines = []
        for attribute in attributes:
            prefix = f"{attribute['key']} " if attribute["key"] else ""
            suffix = f": {attribute['type']}" if attribute["type"] else ""
            lines.append(f"{prefix}{attribute['name']}{suffix}")
        node = copy.deepcopy(dict(item))
        node["id"] = identifier
        node["label"] = _label(item, path)
        node["kind"] = "entity"
        node["semantic_type"] = "entity"
        node["attributes"] = attributes
        node.setdefault("type_label", "ENTITY")
        node.setdefault("sublabel", "\n".join(lines))
        longest = max([len(str(node["label"])), *(len(line) for line in lines)], default=12)
        node.setdefault("width", min(310, max(210, longest * 7 + 42)))
        node.setdefault("height", max(88, 54 + len(attributes) * 22))
        nodes.append(node)

    arrows: List[Dict[str, object]] = []
    edges: List[Tuple[str, str]] = []
    for index, raw in enumerate(relationships):
        path = f"relationships[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        edges.append((source, target))
        left = _cardinality(item.get("from_cardinality"), f"{path}.from_cardinality") if "from_cardinality" in item else ""
        right = _cardinality(item.get("to_cardinality"), f"{path}.to_cardinality") if "to_cardinality" in item else ""
        raw_cardinality = item.get("cardinality")
        if raw_cardinality is not None:
            if isinstance(raw_cardinality, list):
                if len(raw_cardinality) != 2:
                    _fail(f"{path}.cardinality", "array form must contain exactly two values")
                left = _cardinality(raw_cardinality[0], f"{path}.cardinality[0]")
                right = _cardinality(raw_cardinality[1], f"{path}.cardinality[1]")
                cardinality_text = f"{left} — {right}".strip(" —")
            else:
                cardinality_text = _cardinality(raw_cardinality, f"{path}.cardinality")
        else:
            cardinality_text = f"{left} — {right}".strip(" —")
        relation_label = _string(item.get("label", item.get("name")), f"{path}.label", required=False)
        display_label = cardinality_text
        if relation_label:
            display_label = f"{display_label} · {relation_label}" if display_label else relation_label
        arrow = copy.deepcopy(dict(item))
        for key in ("from", "to", "from_cardinality", "to_cardinality", "cardinality", "name"):
            arrow.pop(key, None)
        arrow.update(
            {
                "source": source,
                "target": target,
                "label": display_label,
                "flow": "neutral",
                "marker_end": False,
                "semantic_type": "relationship",
                "from_cardinality": left,
                "to_cardinality": right,
            }
        )
        arrows.append(arrow)
    width = float(result.get("width", 960))
    width, height = _layered_layout(nodes, edges, canvas_width=width, vertical_gap=110)
    node_map = {str(node["id"]): node for node in nodes}
    for arrow in arrows:
        _set_ports(arrow, node_map)
    result["nodes"] = nodes
    result["arrows"] = arrows
    result["width"] = width
    result["height"] = max(float(result.get("height", 0)), height)
    return result


_USE_CASE_RELATIONS = {
    "association": "association",
    "associate": "association",
    "include": "include",
    "includes": "include",
    "extend": "extend",
    "extends": "extend",
}


def _prepare_use_case(data: Mapping[str, object]) -> Dict[str, object]:
    case_key = "use_cases" if "use_cases" in data else "useCases" if "useCases" in data else None
    relation_key = "relations" if "relations" in data else "relationships"
    if "actors" not in data and case_key is None:
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with actors/use_cases")
    actors = _list(data.get("actors"), "actors", required=True)
    use_cases = _list(data.get(case_key) if case_key else None, case_key or "use_cases", required=True)
    relations = _list(data.get(relation_key, []), relation_key)
    result = _base(data, ("actors", "use_cases", "useCases", "relations", "relationships", "system"))
    width = max(float(result.get("width", 960)), 760)
    seen: Dict[str, str] = {}
    actor_ids = set()
    case_ids = set()
    nodes: List[Dict[str, object]] = []
    left_actors: List[Tuple[str, Mapping[str, object], str]] = []
    right_actors: List[Tuple[str, Mapping[str, object], str]] = []
    for index, raw in enumerate(actors):
        path = f"actors[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        actor_ids.add(identifier)
        side = str(item.get("side", "left")).strip().lower()
        if side not in {"left", "right"}:
            _fail(f"{path}.side", "must be left or right")
        target = right_actors if side == "right" else left_actors
        target.append((identifier, item, _label(item, path)))

    case_items: List[Tuple[str, Mapping[str, object], str]] = []
    for index, raw in enumerate(use_cases):
        path = f"{case_key or 'use_cases'}[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        case_ids.add(identifier)
        case_items.append((identifier, item, _label(item, path)))

    case_width = 230.0
    case_height = 62.0
    case_gap = 34.0
    case_x = (width - case_width) / 2
    start_y = 132.0
    for index, (identifier, item, label) in enumerate(case_items):
        node = copy.deepcopy(dict(item))
        node.update(
            {
                "id": identifier,
                "label": label,
                "kind": "use-case",
                "semantic_type": "use-case",
            }
        )
        node.setdefault("width", case_width)
        node.setdefault("height", case_height)
        node.setdefault("x", case_x)
        node.setdefault("y", start_y + index * (case_height + case_gap))
        nodes.append(node)
    vertical_span = max(1, len(case_items)) * (case_height + case_gap)

    for side_items, default_x in ((left_actors, 46.0), (right_actors, width - 166.0)):
        actor_gap = vertical_span / max(1, len(side_items))
        for index, (identifier, item, label) in enumerate(side_items):
            node = copy.deepcopy(dict(item))
            node.update(
                {
                    "id": identifier,
                    "label": label,
                    "kind": "actor",
                    "semantic_type": "actor",
                }
            )
            node.setdefault("width", 120)
            node.setdefault("height", 92)
            node.setdefault("x", default_x)
            node.setdefault("y", start_y + index * actor_gap)
            nodes.append(node)

    arrows: List[Dict[str, object]] = []
    for index, raw in enumerate(relations):
        path = f"{relation_key}[{index}]"
        item = _mapping(raw, path)
        source, target = _relation_ends(item, path, seen)
        token = str(item.get("type", "association")).strip().lower().replace("_", "-")
        relation_type = _USE_CASE_RELATIONS.get(token)
        if relation_type is None:
            _fail(f"{path}.type", "must be association, include, or extend")
        if relation_type == "association":
            if not ((source in actor_ids and target in case_ids) or (target in actor_ids and source in case_ids)):
                _fail(path, "association must connect one actor and one use case")
        elif source not in case_ids or target not in case_ids:
            _fail(path, f"{relation_type} must connect two use cases")
        explicit = _string(item.get("label"), f"{path}.label", required=False) if "label" in item else ""
        label = explicit
        if relation_type in {"include", "extend"}:
            stereotype = f"«{relation_type}»"
            label = f"{stereotype} {explicit}".strip()
        arrow = copy.deepcopy(dict(item))
        for key in ("from", "to", "type"):
            arrow.pop(key, None)
        arrow.update(
            {
                "source": source,
                "target": target,
                "label": label,
                "flow": "neutral" if relation_type == "association" else "control",
                "marker_end": relation_type != "association",
                "dashed": relation_type in {"include", "extend"},
                "semantic_type": relation_type,
            }
        )
        arrows.append(arrow)

    system = data.get("system")
    containers = list(copy.deepcopy(result.get("containers", [])))
    if system is not None:
        if isinstance(system, str):
            system_label = _string(system, "system")
            system_options: Mapping[str, object] = {}
        else:
            system_options = _mapping(system, "system")
            system_label = _label(system_options, "system")
        container = copy.deepcopy(dict(system_options))
        container.update(
            {
                "label": system_label,
                "x": case_x - 42,
                "y": start_y - 42,
                "width": case_width + 84,
                "height": max(case_height + 84, len(case_items) * (case_height + case_gap) + 34),
            }
        )
        containers.append(container)
    node_map = {str(node["id"]): node for node in nodes}
    for arrow in arrows:
        _set_ports(arrow, node_map)
    result["containers"] = containers
    result["nodes"] = nodes
    result["arrows"] = arrows
    result["width"] = width
    result["height"] = max(
        float(result.get("height", 0)),
        start_y + max(1, len(case_items)) * (case_height + case_gap) + 70,
    )
    return result


def _prepare_timeline(data: Mapping[str, object]) -> Dict[str, object]:
    if "events" not in data:
        return _prepare_generic(data)
    if "nodes" in data or "arrows" in data:
        _fail("nodes", "cannot be combined with timeline events")
    events = _list(data.get("events"), "events", required=True)
    result = _base(data, ("events",))
    orientation = str(data.get("orientation", "horizontal")).strip().lower()
    if orientation != "horizontal":
        _fail("orientation", "only horizontal timelines are supported")
    seen: Dict[str, str] = {}
    normalized: List[Tuple[str, Mapping[str, object], str, str, str]] = []
    for index, raw in enumerate(events):
        path = f"events[{index}]"
        item = _mapping(raw, path)
        identifier = _item_id(item, path)
        _check_unique(identifier, f"{path}.id", seen)
        label = _label(item, path)
        time = _string(
            item.get("time", item.get("date", item.get("timestamp"))),
            f"{path}.time",
            required=False,
        )
        description = _string(item.get("description"), f"{path}.description", required=False)
        normalized.append((identifier, item, label, time, description))

    event_width = 176.0
    gap = 72.0
    margin = 72.0
    width = max(float(result.get("width", 960)), margin * 2 + len(events) * event_width + max(0, len(events) - 1) * gap)
    axis_y = 360.0
    nodes: List[Dict[str, object]] = []
    arrows: List[Dict[str, object]] = [
        {
            "x1": margin,
            "y1": axis_y,
            "x2": width - margin,
            "y2": axis_y,
            "flow": "neutral",
            "marker_end": False,
            "stroke_width": 2.2,
            "semantic_type": "timeline-axis",
        }
    ]
    available = width - 2 * margin
    step = available / max(1, len(events) - 1)
    for index, (identifier, item, label, time, description) in enumerate(normalized):
        center_x = width / 2 if len(events) == 1 else margin + index * step
        above = index % 2 == 0
        node_y = axis_y - 146 if above else axis_y + 54
        node = copy.deepcopy(dict(item))
        for key in ("time", "date", "timestamp", "description"):
            node.pop(key, None)
        node.update(
            {
                "id": identifier,
                "label": label,
                "kind": "timeline-event",
                "semantic_type": "timeline-event",
                "x": round(center_x - event_width / 2, 2),
                "y": node_y,
                "width": event_width,
                "height": 82,
                "type_label": time or "EVENT",
                "sublabel": description,
            }
        )
        nodes.append(node)
        connector_start = node_y + 82 if above else node_y
        arrows.append(
            {
                "x1": center_x,
                "y1": connector_start,
                "x2": center_x,
                "y2": axis_y,
                "flow": "neutral",
                "marker_end": False,
                "stroke_width": 1.4,
                "semantic_type": "timeline-connector",
                "event": identifier,
            }
        )
        nodes.append(
            {
                "id": f"__timeline_marker_{identifier}",
                "label": "",
                "kind": "milestone",
                "semantic_type": "milestone",
                "x": center_x - 7,
                "y": axis_y - 7,
                "width": 14,
                "height": 14,
            }
        )
    result["nodes"] = nodes
    result["arrows"] = arrows
    result["width"] = width
    result["height"] = max(float(result.get("height", 0)), 560)
    return result


_PREPARERS = {
    "architecture": _prepare_architecture,
    "data-flow": _prepare_data_flow,
    "flowchart": _prepare_flowchart,
    "sequence": _prepare_sequence,
    "state-machine": _prepare_state_machine,
    "er-diagram": _prepare_er,
    "use-case": _prepare_use_case,
    "timeline": _prepare_timeline,
}


def prepare_diagram(template_type: str, data: Mapping[str, object]) -> Dict[str, object]:
    """Validate and normalize one diagram without mutating ``data``.

    ``ValueError`` messages begin with the offending field path so callers can
    return actionable diagnostics instead of silently drawing a wrong graph.
    Legacy generic aliases (``agent``, ``memory``, ``comparison`` and network
    topology) intentionally normalize through the architecture path.
    """

    canonical = _canonical_type(template_type)
    source = _mapping(data, "data")
    declared_type = source.get("template_type")
    if declared_type is not None and _canonical_type(declared_type, "template_type") != canonical:
        _fail(
            "template_type",
            f"declares {declared_type!r} but renderer requested {template_type!r}",
        )
    prepared = _PREPARERS[canonical](source)
    # Downstream template lookup accepts canonical names only.  Always replace
    # a validated alias (for example ``flow-chart`` or ``memory``) here.
    prepared["template_type"] = canonical
    _validate_common(prepared)
    return prepared


__all__ = ["SUPPORTED_DIAGRAM_TYPES", "prepare_diagram"]
