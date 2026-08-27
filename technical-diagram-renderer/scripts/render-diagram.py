#!/usr/bin/env python3
"""Generate, normalize, validate, and atomically publish diagram artifacts."""

from __future__ import annotations

import argparse
import copy
import importlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
GENERATOR = SCRIPT_DIR / "generate-from-template.py"
VALIDATOR = SCRIPT_DIR / "validate-svg.py"
DRAWIO_EXPORTER = SCRIPT_DIR / "export_drawio.py"
FORMATS = ("svg", "json", "png", "drawio")
TYPE_ALIASES = {
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
CJK_RE = re.compile(
    "["
    "\u2e80-\u2fff"
    "\u3000-\u303f"
    "\u3040-\u30ff"
    "\u3100-\u312f"
    "\u31a0-\u31bf"
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uac00-\ud7af"
    "\uf900-\ufaff"
    "]"
)


class RenderError(RuntimeError):
    """A user-facing, side-effect-safe render failure."""


def _canonical_template_type(value: str) -> str:
    token = re.sub(r"[\s_]+", "-", value.strip().lower())
    canonical = TYPE_ALIASES.get(token)
    if canonical is None:
        supported = ", ".join(sorted(set(TYPE_ALIASES.values())))
        raise RenderError(f"Unsupported diagram type '{value}'; expected one of {supported}.")
    return canonical


def _load_core_prevalidator() -> Callable[[str, object], object]:
    module_name = "_technical_diagram_generator_prevalidation"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, GENERATOR)
        if spec is None or spec.loader is None:
            raise RenderError("Cannot load the generator's raw-input validator.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise RenderError(f"Cannot load the generator's raw-input validator: {exc}") from exc
    function = getattr(module, "prevalidate_untrusted_input", None)
    if not callable(function):
        raise RenderError("generate-from-template.py does not expose prevalidate_untrusted_input().")
    return function


def _prevalidate_raw_input(template_type: str, data: Mapping[str, object]) -> None:
    canonical_type = _canonical_template_type(template_type)
    validator = _load_core_prevalidator()
    try:
        validator(canonical_type, copy.deepcopy(dict(data)))
    except Exception as exc:
        raise RenderError(f"Raw input validation failed: {exc}") from exc


def _load_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RenderError(f"Cannot read input JSON: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise RenderError("Input JSON must be an object.")
    return data


def _load_optional_function(module_name: str, function_name: str) -> tuple[Callable[..., object] | None, str | None]:
    module_path = SCRIPT_DIR / f"{module_name}.py"
    if not module_path.exists():
        return None, f"{module_path.name} is unavailable; preserving the input JSON for this stage."
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
    except Exception as exc:  # Import failures must be visible, never silently swallowed.
        raise RenderError(f"Cannot load {module_path.name}: {exc}") from exc
    if not callable(function):
        raise RenderError(f"{module_path.name} does not expose callable {function_name}().")
    return function, None


def normalize_diagram(template_type: str, data: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    normalized: dict[str, object] = copy.deepcopy(dict(data))
    warnings: list[str] = []
    declared_type = normalized.get("template_type")

    prepare_diagram, warning = _load_optional_function("semantic_diagrams", "prepare_diagram")
    if warning:
        warnings.append(warning)
        if declared_type is not None and str(declared_type) != template_type:
            raise RenderError(
                f"template_type mismatch: input declares '{declared_type}', CLI requested '{template_type}'."
            )
        normalized["template_type"] = template_type
    elif prepare_diagram:
        try:
            prepared = prepare_diagram(template_type, normalized)
        except Exception as exc:
            raise RenderError(f"Semantic normalization failed: {exc}") from exc
        if not isinstance(prepared, dict):
            raise RenderError("semantic_diagrams.prepare_diagram() must return a dict.")
        normalized = prepared

    canonical_type = normalized.get("template_type")
    if not isinstance(canonical_type, str) or not canonical_type.strip():
        raise RenderError("Semantic normalization did not return a canonical template_type.")

    apply_auto_layout, warning = _load_optional_function("layout_engine", "apply_auto_layout")
    if warning:
        warnings.append(warning)
    elif apply_auto_layout:
        try:
            laid_out = apply_auto_layout(normalized, canonical_type)
        except Exception as exc:
            raise RenderError(f"Automatic layout failed: {exc}") from exc
        if not isinstance(laid_out, dict):
            raise RenderError("layout_engine.apply_auto_layout() must return a dict.")
        normalized = laid_out
    return normalized, warnings


def _assert_nodes_positioned(data: Mapping[str, object]) -> None:
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        return  # The generator's strict validator will provide the field-path error.
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            return
        for coordinate in ("x", "y"):
            value = node.get(coordinate)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise RenderError(f"nodes[{index}].{coordinate}: layout did not produce a finite coordinate")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run(command: Sequence[str], *, purpose: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RenderError(f"{purpose} could not start: {exc}") from exc
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        suffix = f": {details}" if details else ""
        raise RenderError(f"{purpose} failed with exit code {result.returncode}{suffix}")
    return result


def _validate_svg(svg_path: Path) -> dict[str, object]:
    result = _run([sys.executable, str(VALIDATOR), str(svg_path)], purpose="SVG validation")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RenderError(f"SVG validator returned invalid JSON: {exc}") from exc
    if not isinstance(report, dict) or not report.get("valid"):
        raise RenderError("SVG validation did not return a valid report.")
    return report


def _cjk_languages(text: str) -> set[str]:
    languages: set[str] = set()
    has_japanese = any("\u3040" <= char <= "\u30ff" for char in text)
    has_korean = any("\uac00" <= char <= "\ud7af" for char in text)
    if has_japanese:
        languages.add("ja")
    if has_korean:
        languages.add("ko")
    # Han-only text is not linguistically distinguishable.  Treat it as zh for
    # fontconfig unless kana or Hangul gives us a more precise requested font.
    if CJK_RE.search(text) and not (has_japanese or has_korean):
        languages.add("zh")
    return languages


def _has_cjk_font(text: str) -> tuple[bool, str]:
    languages = _cjk_languages(text)
    if not languages:
        return True, "not-required"

    fc_list = shutil.which("fc-list")
    if fc_list:
        missing: list[str] = []
        for language in sorted(languages):
            result = subprocess.run(
                [fc_list, f":lang={language}", "family"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode or not result.stdout.strip():
                missing.append(language)
        if not missing:
            return True, f"fontconfig:{','.join(sorted(languages))}"

    system = platform.system().lower()
    candidates: list[Path] = []
    if system == "windows":
        font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates.extend(font_dir / name for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "msgothic.ttc", "malgun.ttf"))
    elif system == "darwin":
        candidates.extend(
            Path(name)
            for name in (
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/Library/Fonts/Arial Unicode.ttf",
            )
        )
    else:
        candidates.extend(
            Path(name)
            for name in (
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
                "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/arphic/uming.ttc",
            )
        )
    existing = next((path for path in candidates if path.exists()), None)
    return (True, f"file:{existing}") if existing else (False, "missing")


def _export_png(svg_path: Path, png_path: Path, *, width: int | None, source_text: str) -> str:
    font_ok, font_source = _has_cjk_font(source_text)
    if not font_ok:
        raise RenderError(
            "PNG export blocked: the diagram contains CJK text but no CJK-capable system font was found. "
            "Install Noto Sans CJK/Source Han Sans, Microsoft YaHei/SimHei, PingFang, or an equivalent font. "
            "The SVG can still be delivered."
        )

    converter = shutil.which("rsvg-convert")
    if converter:
        command = [converter]
        if width:
            command.extend(["--width", str(width)])
        command.extend([str(svg_path), "--output", str(png_path)])
        _run(command, purpose="PNG export with rsvg-convert")
        engine = "rsvg-convert"
    else:
        converter = shutil.which("inkscape")
        if not converter:
            raise RenderError("PNG export requested, but neither rsvg-convert nor Inkscape is available.")
        command = [converter, str(svg_path), f"--export-filename={png_path}"]
        if width:
            command.append(f"--export-width={width}")
        _run(command, purpose="PNG export with Inkscape")
        engine = "inkscape"

    try:
        signature = png_path.read_bytes()[:8]
    except OSError as exc:
        raise RenderError(f"PNG exporter did not create a readable file: {exc}") from exc
    if signature != b"\x89PNG\r\n\x1a\n":
        raise RenderError("PNG exporter returned a file without a valid PNG signature.")
    return f"{engine};cjk-font={font_source}"


def _parse_formats(raw: str) -> list[str]:
    values: list[str] = []
    for item in raw.split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value not in FORMATS:
            raise argparse.ArgumentTypeError(f"unsupported format '{value}'; choose from {','.join(FORMATS)}")
        if value not in values:
            values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("at least one format is required")
    return values


def _resolve_base(output: str, input_path: Path) -> Path:
    raw = output.strip()
    candidate = Path(raw).expanduser()
    if raw.endswith(("/", "\\")):
        return candidate / input_path.stem
    # A recognized suffix is an explicit file/base request even when the path
    # currently names a directory or a symlink to one.  The target preflight
    # can then reject a real directory without following/deleting it, while a
    # symlink itself remains safely replaceable.
    if candidate.suffix.lower() in {f".{item}" for item in FORMATS}:
        return candidate.with_suffix("")
    if candidate.exists() and candidate.is_dir():
        return candidate / input_path.stem
    return candidate


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return left.resolve(strict=False) == right.resolve(strict=False)


def _ensure_input_is_not_an_output(input_path: Path, destinations: Mapping[str, Path]) -> None:
    for file_format, destination in destinations.items():
        if _same_resolved_path(input_path, destination):
            raise RenderError(
                f"Input JSON and {file_format} output resolve to the same path: {input_path}."
            )


def _validate_publish_targets(destinations: Mapping[str, Path]) -> None:
    """Reject directories/special files without following destination symlinks."""

    for file_format, destination in destinations.items():
        try:
            mode = os.lstat(destination).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(mode):
            raise RenderError(f"Refusing to replace directory destination for {file_format}: {destination}")
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise RenderError(f"Refusing to replace non-file destination for {file_format}: {destination}")


def _atomic_publish(staged: Mapping[str, Path], destinations: Mapping[str, Path], staging_dir: Path) -> None:
    # Perform the complete type gate before touching any existing artifact.
    # lstat treats a symlink as the replaceable link itself, never its target.
    _validate_publish_targets(destinations)
    backups: dict[str, Path] = {}
    committed: list[str] = []
    try:
        for file_format, destination in destinations.items():
            if os.path.lexists(destination):
                backup = staging_dir / f"backup-{file_format}{destination.suffix}"
                # Copying instead of moving ensures a mistaken/racing directory
                # can never be placed under TemporaryDirectory for recursive
                # cleanup.  follow_symlinks=False copies the link, not its target.
                shutil.copy2(destination, backup, follow_symlinks=False)
                backups[file_format] = backup
        for file_format, destination in destinations.items():
            os.replace(staged[file_format], destination)
            committed.append(file_format)
    except Exception:
        for file_format in reversed(committed):
            destination = destinations[file_format]
            backup = backups.get(file_format)
            if backup is not None and os.path.lexists(backup):
                os.replace(backup, destination)
            else:
                try:
                    mode = os.lstat(destination).st_mode
                    if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                        destination.unlink()
                except FileNotFoundError:
                    pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate validated SVG/JSON/PNG diagram artifacts atomically.")
    parser.add_argument("--type", required=True, dest="template_type", help="diagram/template type")
    parser.add_argument("--input", required=True, type=Path, help="source JSON file")
    parser.add_argument("--output", required=True, help="output base, file path, or existing directory")
    parser.add_argument(
        "--formats",
        type=_parse_formats,
        default=["svg", "json"],
        metavar="LIST",
        help="comma-separated svg,json,png,drawio (default: svg,json)",
    )
    parser.add_argument("--style", type=int, choices=range(1, 8), help="override input style (1-7)")
    parser.add_argument("--png-width", type=int, help="optional PNG width in pixels")
    validation = parser.add_mutually_exclusive_group()
    validation.add_argument("--validate", action="store_true", dest="validate", help="validate SVG (default)")
    validation.add_argument("--no-validate", action="store_false", dest="validate", help="skip final SVG validation")
    parser.set_defaults(validate=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.png_width is not None and args.png_width <= 0:
        print("Error: --png-width must be positive.", file=sys.stderr)
        return 2

    try:
        input_path = args.input.expanduser().resolve()
        base = _resolve_base(args.output, input_path).resolve()
        destinations = {file_format: base.with_suffix(f".{file_format}") for file_format in args.formats}
        _ensure_input_is_not_an_output(input_path, destinations)
        _validate_publish_targets(destinations)

        source = _load_json(input_path)
        # Validate raw controls before semantic adapters or layout can replace
        # an invalid value with a plausible-looking default.
        _prevalidate_raw_input(args.template_type, source)
        if args.style is not None:
            source["style"] = args.style
        normalized, normalization_warnings = normalize_diagram(args.template_type, source)
        _assert_nodes_positioned(normalized)
        canonical_type = str(normalized["template_type"])
        normalized_text = json.dumps(normalized, ensure_ascii=False, sort_keys=True)

        base.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{base.name}-render-", dir=base.parent) as temporary:
            staging_dir = Path(temporary)
            staged_json = staging_dir / f"{base.name}.json"
            generator_json = staging_dir / f"{base.name}.generator.json"
            staged_svg = staging_dir / f"{base.name}.svg"
            _write_json(staged_json, normalized)
            generator_payload = copy.deepcopy(normalized)
            generator_payload["_renderer_prepared"] = True
            _write_json(generator_json, generator_payload)

            _run(
                [sys.executable, str(GENERATOR), canonical_type, str(staged_svg), str(generator_json)],
                purpose="SVG generation",
            )
            validation_report: dict[str, object] | None = None
            if args.validate:
                validation_report = _validate_svg(staged_svg)

            staged: dict[str, Path] = {}
            if "svg" in args.formats:
                staged["svg"] = staged_svg
            if "json" in args.formats:
                staged["json"] = staged_json
            png_engine: str | None = None
            if "png" in args.formats:
                staged_png = staging_dir / f"{base.name}.png"
                png_engine = _export_png(
                    staged_svg,
                    staged_png,
                    width=args.png_width,
                    source_text=normalized_text,
                )
                staged["png"] = staged_png
            if "drawio" in args.formats:
                if not DRAWIO_EXPORTER.exists():
                    raise RenderError("drawio export requested, but scripts/export_drawio.py is unavailable.")
                staged_drawio = staging_dir / f"{base.name}.drawio"
                _run(
                    [sys.executable, str(DRAWIO_EXPORTER), str(staged_json), str(staged_drawio)],
                    purpose="draw.io export",
                )
                staged["drawio"] = staged_drawio

            _atomic_publish(staged, destinations, staging_dir)

        payload: dict[str, object] = {
            "ok": True,
            "type": canonical_type,
            "artifacts": {file_format: str(path) for file_format, path in destinations.items()},
            "validated": bool(args.validate),
            "warnings": normalization_warnings,
        }
        if canonical_type != args.template_type:
            payload["requested_type"] = args.template_type
        if validation_report:
            validation_report = dict(validation_report)
            if "svg" in destinations:
                validation_report["file"] = str(destinations["svg"])
            else:
                validation_report.pop("file", None)
                validation_report["scope"] = "staged-svg-not-published"
            payload["validation"] = validation_report
        if png_engine:
            payload["png_engine"] = png_engine
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        for warning in normalization_warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        return 0
    except RenderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:
        print(f"Error: output operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
