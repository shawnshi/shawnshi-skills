#!/usr/bin/env python3
"""Validate generated SVGs without executing or fetching embedded content.

The validator deliberately supports a static subset of SVG.  Technical diagrams
do not need scripts, foreign objects, links, images, animation, or remote
resources; rejecting those features makes the generated file safe to hand to a
browser or document renderer.

The command always emits one JSON report to stdout.  Exit status is 0 only when
the report contains no errors, 1 for an invalid SVG, and 2 for an invocation or
I/O failure.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


SVG_NS = "http://www.w3.org/2000/svg"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XLINK_NS = "http://www.w3.org/1999/xlink"
MAX_SVG_BYTES = 20 * 1024 * 1024

# Static elements used by the renderer plus common inert SVG primitives.  Active
# and remotely-backed elements (script, foreignObject, image, use, a, animation,
# feImage) are intentionally absent.
SAFE_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "title",
        "desc",
        "symbol",
        "marker",
        "clipPath",
        "mask",
        "pattern",
        "linearGradient",
        "radialGradient",
        "stop",
        "filter",
        "feBlend",
        "feColorMatrix",
        "feComponentTransfer",
        "feComposite",
        "feConvolveMatrix",
        "feDiffuseLighting",
        "feDisplacementMap",
        "feDistantLight",
        "feDropShadow",
        "feFlood",
        "feFuncA",
        "feFuncB",
        "feFuncG",
        "feFuncR",
        "feGaussianBlur",
        "feMerge",
        "feMergeNode",
        "feMorphology",
        "feOffset",
        "fePointLight",
        "feSpecularLighting",
        "feSpotLight",
        "feTile",
        "feTurbulence",
        "style",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "path",
        "text",
        "tspan",
        "textPath",
    }
)

VISIBLE_ELEMENTS = frozenset(
    {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "tspan"}
)
DEFINITION_CONTAINERS = frozenset(
    {"defs", "symbol", "marker", "clipPath", "mask", "pattern", "linearGradient", "radialGradient", "filter"}
)
MARKER_ATTRIBUTES = frozenset({"marker-start", "marker-mid", "marker-end"})
URL_ATTRIBUTES = frozenset({"href", "src"})

NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
URL_FUNC_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
LOCAL_URL_RE = re.compile(r"^#[A-Za-z_][A-Za-z0-9_.:-]*$")
MARKER_URL_RE = re.compile(r"^url\(\s*#([A-Za-z_][A-Za-z0-9_.:-]*)\s*\)$", re.IGNORECASE)
DANGEROUS_CSS_RE = re.compile(
    r"@import|expression\s*\(|-moz-binding|behavior\s*:|javascript\s*:|vbscript\s*:",
    re.IGNORECASE,
)
EXTERNAL_SCHEME_RE = re.compile(r"(?:^|[\s'\"(])(?:https?|ftp|file|data|javascript|vbscript):|^//", re.IGNORECASE)
PATH_TOKEN_RE = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1] if "}" in name else name


def _namespace(name: str) -> str | None:
    if name.startswith("{") and "}" in name:
        return name[1:].split("}", 1)[0]
    return None


def _finite_float(value: object, *, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    text = str(value).strip()
    # Unit-bearing lengths cannot be compared reliably with a numeric viewBox.
    if not NUMBER_RE.fullmatch(text):
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class Report:
    file: str
    errors: list[dict[str, object]] = field(default_factory=list)
    warnings: list[dict[str, object]] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    stats: dict[str, object] = field(default_factory=dict)

    def add_error(self, code: str, message: str, **context: object) -> None:
        issue: dict[str, object] = {"code": code, "message": message}
        if context:
            issue["context"] = context
        self.errors.append(issue)

    def add_warning(self, code: str, message: str, **context: object) -> None:
        issue: dict[str, object] = {"code": code, "message": message}
        if context:
            issue["context"] = context
        self.warnings.append(issue)

    def as_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
            "stats": self.stats,
        }


def _element_context(element: ET.Element) -> dict[str, str]:
    context = {"element": _local_name(element.tag)}
    if element.get("id"):
        context["id"] = str(element.get("id"))
    return context


def _iter_elements_with_ancestors(root: ET.Element) -> Iterator[tuple[ET.Element, tuple[str, ...]]]:
    stack: list[tuple[ET.Element, tuple[str, ...]]] = [(root, ())]
    while stack:
        element, ancestors = stack.pop()
        yield element, ancestors
        next_ancestors = ancestors + (_local_name(element.tag),)
        for child in reversed(list(element)):
            stack.append((child, next_ancestors))


def _parse_viewbox(root: ET.Element, report: Report) -> tuple[float, float, float, float] | None:
    raw = root.get("viewBox")
    if not raw:
        report.add_error("missing_viewbox", "The root svg element must define viewBox.")
        return None
    parts = re.split(r"[\s,]+", raw.strip())
    if len(parts) != 4:
        report.add_error("invalid_viewbox", "viewBox must contain four finite numbers.", value=raw)
        return None
    values = [_finite_float(part) for part in parts]
    if any(value is None for value in values):
        report.add_error("invalid_viewbox", "viewBox must contain four finite numbers.", value=raw)
        return None
    x, y, width, height = (float(value) for value in values if value is not None)
    if width <= 0 or height <= 0:
        report.add_error("invalid_viewbox_size", "viewBox width and height must be positive.", value=raw)
        return None
    return x, y, width, height


def _point_pairs(raw: str) -> list[tuple[float, float]]:
    values: list[float] = []
    for token in NUMBER_RE.findall(raw):
        value = _finite_float(token)
        if value is not None:
            values.append(value)
    return list(zip(values[0::2], values[1::2]))


def _path_points(raw: str) -> list[tuple[float, float]]:
    """Return conservative control/end points for common SVG path commands."""

    tokens = PATH_TOKEN_RE.findall(raw)
    points: list[tuple[float, float]] = []
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = current
    arities = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command.upper() == "Z":
                current = start
                points.append(current)
                continue
        if not command or command.upper() not in arities:
            # Unknown/malformed path data is handled by a renderer; bounds remain
            # best-effort and therefore should not turn into a false assertion.
            index += 1
            continue
        arity = arities[command.upper()]
        if index + arity > len(tokens):
            break
        if any(part.isalpha() for part in tokens[index : index + arity]):
            continue
        try:
            values = [float(part) for part in tokens[index : index + arity]]
        except ValueError:
            index += arity
            continue
        index += arity
        relative = command.islower()
        upper = command.upper()
        cx, cy = current

        def absolute(px: float, py: float) -> tuple[float, float]:
            return (px + cx, py + cy) if relative else (px, py)

        if upper == "H":
            current = (values[0] + cx if relative else values[0], cy)
            points.append(current)
        elif upper == "V":
            current = (cx, values[0] + cy if relative else values[0])
            points.append(current)
        elif upper == "A":
            # End point plus a conservative radius envelope.  Rotation is not
            # resolved; using both radii on both axes errs on the safe side.
            end = absolute(values[5], values[6])
            radius = max(abs(values[0]), abs(values[1]))
            points.extend([(end[0] - radius, end[1] - radius), (end[0] + radius, end[1] + radius), end])
            current = end
        else:
            command_points = [absolute(values[offset], values[offset + 1]) for offset in range(0, arity, 2)]
            points.extend(command_points)
            current = command_points[-1]
            if upper == "M":
                start = current
                command = "l" if relative else "L"
    return points


def _element_bounds(element: ET.Element) -> tuple[float, float, float, float] | None:
    tag = _local_name(element.tag)
    get = element.get
    if tag == "rect":
        x, y = _finite_float(get("x"), default=0.0), _finite_float(get("y"), default=0.0)
        width, height = _finite_float(get("width")), _finite_float(get("height"))
        if None in (x, y, width, height):
            return None
        return float(x), float(y), float(x) + float(width), float(y) + float(height)
    if tag == "circle":
        cx, cy = _finite_float(get("cx"), default=0.0), _finite_float(get("cy"), default=0.0)
        radius = _finite_float(get("r"))
        if None in (cx, cy, radius):
            return None
        return float(cx) - float(radius), float(cy) - float(radius), float(cx) + float(radius), float(cy) + float(radius)
    if tag == "ellipse":
        cx, cy = _finite_float(get("cx"), default=0.0), _finite_float(get("cy"), default=0.0)
        rx, ry = _finite_float(get("rx")), _finite_float(get("ry"))
        if None in (cx, cy, rx, ry):
            return None
        return float(cx) - float(rx), float(cy) - float(ry), float(cx) + float(rx), float(cy) + float(ry)
    if tag == "line":
        values = [_finite_float(get(name), default=0.0) for name in ("x1", "y1", "x2", "y2")]
        if any(value is None for value in values):
            return None
        x1, y1, x2, y2 = (float(value) for value in values if value is not None)
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    if tag in {"polyline", "polygon"}:
        points = _point_pairs(get("points", ""))
    elif tag == "path":
        points = _path_points(get("d", ""))
    elif tag in {"text", "tspan"}:
        x = _finite_float((get("x") or "").split()[0] if get("x") else None)
        y = _finite_float((get("y") or "").split()[0] if get("y") else None)
        return (x, y, x, y) if x is not None and y is not None else None
    else:
        return None
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _is_hidden(element: ET.Element) -> bool:
    style = str(element.get("style", "")).replace(" ", "").lower()
    return (
        element.get("display", "").lower() == "none"
        or element.get("visibility", "").lower() == "hidden"
        or element.get("opacity") == "0"
        or "display:none" in style
        or "visibility:hidden" in style
    )


def _check_urls(value: str) -> tuple[list[str], list[str]]:
    """Return (local fragment ids, unsafe URL-like values)."""

    local_refs: list[str] = []
    unsafe: list[str] = []
    for match in URL_FUNC_RE.finditer(value):
        target = match.group(2).strip()
        if LOCAL_URL_RE.fullmatch(target):
            local_refs.append(target[1:])
        else:
            unsafe.append(target)
    if EXTERNAL_SCHEME_RE.search(value):
        unsafe.append(value.strip())
    return local_refs, unsafe


def validate_svg(path: str | Path, *, bounds_tolerance: float = 1.0) -> dict[str, object]:
    svg_path = Path(path)
    report = Report(str(svg_path.resolve()))

    try:
        size = svg_path.stat().st_size
        report.stats["bytes"] = size
        if size > MAX_SVG_BYTES:
            report.add_error("file_too_large", f"SVG exceeds the {MAX_SVG_BYTES}-byte validation limit.", bytes=size)
            report.checks["xml_well_formed"] = False
            return report.as_dict()
        raw = svg_path.read_bytes()
    except OSError as exc:
        report.add_error("io_error", f"Cannot read SVG: {exc}")
        report.checks["xml_well_formed"] = False
        return report.as_dict()

    try:
        # Generated artifacts have a UTF-8 contract.  Decode before scanning so
        # UTF-16/NUL-separated declarations cannot bypass an ASCII byte search.
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        report.add_error("invalid_encoding", f"SVG must be strict UTF-8: {exc}")
        report.checks["xml_well_formed"] = False
        return report.as_dict()

    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        report.add_error("doctype_forbidden", "DOCTYPE and entity declarations are forbidden in SVG output.")
        # Do not give an XML parser a chance to expand internal entities.
        report.checks["xml_well_formed"] = False
        return report.as_dict()

    try:
        # Parse original bytes so a legal UTF-8 XML encoding declaration keeps
        # its byte-oriented semantics.  The strict decode and DTD/entity scan
        # above have already completed before the parser sees the document.
        root = ET.fromstring(raw)
        report.checks["xml_well_formed"] = True
    except (ET.ParseError, ValueError) as exc:
        report.add_error("xml_not_well_formed", f"SVG is not well-formed XML: {exc}")
        report.checks["xml_well_formed"] = False
        return report.as_dict()

    root_name = _local_name(root.tag)
    root_namespace = _namespace(root.tag)
    if root_name != "svg" or root_namespace not in {None, SVG_NS}:
        report.add_error("invalid_root", "Root element must be svg in the SVG namespace.", tag=root.tag)

    viewbox = _parse_viewbox(root, report)
    if viewbox:
        report.stats["viewBox"] = list(viewbox)

    elements = list(_iter_elements_with_ancestors(root))
    report.stats["elements"] = len(elements)
    ids: dict[str, list[str]] = {}
    unsafe_element_count = 0
    unsafe_attribute_count = 0
    local_url_refs: list[tuple[str, ET.Element, str]] = []
    marker_refs: list[tuple[str, ET.Element, str]] = []

    for element, _ancestors in elements:
        tag = _local_name(element.tag)
        namespace = _namespace(element.tag)
        context = _element_context(element)
        if namespace not in {None, SVG_NS}:
            report.add_error("foreign_namespace", "Foreign namespaces are not allowed in generated SVG.", namespace=namespace, **context)
            unsafe_element_count += 1
        if tag not in SAFE_ELEMENTS:
            report.add_error("unsafe_element", f"Element <{tag}> is not in the static SVG allowlist.", **context)
            unsafe_element_count += 1

        element_id = element.get("id")
        if element_id:
            ids.setdefault(element_id, []).append(tag)

        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            attr_namespace = _namespace(raw_name)
            value = str(raw_value)
            if name.lower().startswith("on"):
                report.add_error("event_attribute", f"Event attribute '{name}' is forbidden.", attribute=name, **context)
                unsafe_attribute_count += 1
            if attr_namespace not in {None, XML_NS, XLINK_NS}:
                report.add_error("foreign_attribute_namespace", "Foreign attribute namespaces are forbidden.", attribute=raw_name, **context)
                unsafe_attribute_count += 1

            local_refs, unsafe_urls = _check_urls(value)
            for ref_id in local_refs:
                local_url_refs.append((ref_id, element, name))
            for unsafe_url in unsafe_urls:
                report.add_error("external_url", "External, data, or executable URL is forbidden.", attribute=name, value=unsafe_url, **context)
                unsafe_attribute_count += 1

            if name in URL_ATTRIBUTES:
                stripped = value.strip()
                if not LOCAL_URL_RE.fullmatch(stripped):
                    report.add_error("unsafe_href", "href/src must be a local fragment reference.", attribute=name, value=value, **context)
                    unsafe_attribute_count += 1
                else:
                    local_url_refs.append((stripped[1:], element, name))

            if name in MARKER_ATTRIBUTES and value.strip().lower() != "none":
                marker_match = MARKER_URL_RE.fullmatch(value.strip())
                if not marker_match:
                    report.add_error("invalid_marker_reference", "Marker attributes must use url(#local-id) or none.", attribute=name, value=value, **context)
                else:
                    marker_refs.append((marker_match.group(1), element, name))

            if name == "style" and DANGEROUS_CSS_RE.search(value):
                report.add_error("unsafe_css", "Inline CSS contains an executable or importing construct.", attribute=name, **context)
                unsafe_attribute_count += 1

        if tag == "style":
            css = "".join(element.itertext())
            if DANGEROUS_CSS_RE.search(css):
                report.add_error("unsafe_css", "Style element contains an executable or importing construct.", **context)
            _local_refs, unsafe_urls = _check_urls(css)
            for unsafe_url in unsafe_urls:
                report.add_error("external_css_url", "Style element contains a non-local URL.", value=unsafe_url, **context)

    duplicates = {element_id: tags for element_id, tags in ids.items() if len(tags) > 1}
    for element_id, tags in sorted(duplicates.items()):
        report.add_error("duplicate_id", f"ID '{element_id}' occurs {len(tags)} times.", id=element_id, elements=tags)

    for ref_id, element, attribute in local_url_refs:
        if ref_id not in ids:
            report.add_error("missing_local_reference", f"Local reference '#{ref_id}' does not exist.", attribute=attribute, **_element_context(element))

    for marker_id, element, attribute in marker_refs:
        if marker_id not in ids:
            report.add_error("missing_marker", f"Marker '#{marker_id}' does not exist.", attribute=attribute, **_element_context(element))
        elif "marker" not in ids[marker_id]:
            report.add_error("wrong_marker_target", f"Marker reference '#{marker_id}' does not target a marker element.", attribute=attribute, **_element_context(element))

    report.stats.update(
        {
            "ids": len(ids),
            "duplicate_ids": len(duplicates),
            "marker_references": len(marker_refs),
            "unsafe_elements": unsafe_element_count,
            "unsafe_attributes": unsafe_attribute_count,
        }
    )
    report.checks["safe_static_svg"] = not any(
        issue["code"]
        in {
            "doctype_forbidden",
            "foreign_namespace",
            "unsafe_element",
            "event_attribute",
            "foreign_attribute_namespace",
            "external_url",
            "unsafe_href",
            "unsafe_css",
            "external_css_url",
        }
        for issue in report.errors
    )
    report.checks["unique_ids"] = not duplicates
    report.checks["references_resolve"] = not any(
        issue["code"] in {"missing_local_reference", "missing_marker", "wrong_marker_target", "invalid_marker_reference"}
        for issue in report.errors
    )

    checked_bounds = 0
    out_of_bounds = 0
    unsupported_transforms = 0
    if viewbox:
        vx, vy, vw, vh = viewbox
        right, bottom = vx + vw, vy + vh
        for element, ancestors in elements:
            tag = _local_name(element.tag)
            if tag not in VISIBLE_ELEMENTS or any(ancestor in DEFINITION_CONTAINERS for ancestor in ancestors):
                continue
            if _is_hidden(element):
                continue
            if element.get("transform"):
                unsupported_transforms += 1
                continue
            bounds = _element_bounds(element)
            if bounds is None:
                continue
            checked_bounds += 1
            left, top, element_right, element_bottom = bounds
            if (
                left < vx - bounds_tolerance
                or top < vy - bounds_tolerance
                or element_right > right + bounds_tolerance
                or element_bottom > bottom + bounds_tolerance
            ):
                out_of_bounds += 1
                report.add_error(
                    "visible_element_outside_viewbox",
                    "A visible element extends outside viewBox (rough geometry check).",
                    bounds=[left, top, element_right, element_bottom],
                    viewBox=list(viewbox),
                    **_element_context(element),
                )
        if unsupported_transforms:
            report.add_warning(
                "transformed_bounds_skipped",
                "Bounds were not estimated for transformed elements.",
                elements=unsupported_transforms,
            )
    report.stats["bounds_checked"] = checked_bounds
    report.stats["bounds_skipped_transforms"] = unsupported_transforms
    report.stats["out_of_bounds"] = out_of_bounds
    report.checks["visible_elements_within_viewbox"] = viewbox is not None and out_of_bounds == 0

    return report.as_dict()


def _write_json(path: Path, payload: Mapping[str, object], *, pretty: bool) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a static SVG and emit a JSON report.")
    parser.add_argument("svg", type=Path, help="SVG file to validate")
    parser.add_argument("--report", type=Path, help="also write the JSON report to this file")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    parser.add_argument(
        "--bounds-tolerance",
        type=float,
        default=1.0,
        metavar="PX",
        help="viewBox bounds tolerance in user units (default: 1)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.bounds_tolerance) or args.bounds_tolerance < 0:
        parser.error("--bounds-tolerance must be a finite non-negative number")
    report = validate_svg(args.svg, bounds_tolerance=args.bounds_tolerance)
    rendered = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True)
    print(rendered)
    if args.report:
        try:
            _write_json(args.report, report, pretty=args.pretty)
        except OSError as exc:
            print(f"Cannot write report: {exc}", file=sys.stderr)
            return 2
    error_codes = {issue.get("code") for issue in report.get("errors", []) if isinstance(issue, Mapping)}
    if "io_error" in error_codes:
        return 2
    return 0 if report.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
