#!/usr/bin/env python3
"""Fail-closed export and artifact inspection for publication figures."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

try:
    from .style_presets import CONFIG_PATH, get_profile, publication_style
except ImportError:
    from style_presets import CONFIG_PATH, get_profile, publication_style


RASTER_FORMATS = {"png", "tiff"}
VECTOR_FORMATS = {"pdf", "eps", "svg"}
SUPPORTED_FORMATS = RASTER_FORMATS | VECTOR_FORMATS


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: CheckStatus
    required: bool = True
    expected: Any = None
    observed: Any = None
    message: str = ""
    validator: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "required": self.required,
            "expected": self.expected,
            "observed": self.observed,
            "message": self.message,
            "validator": self.validator,
            "evidence": dict(self.evidence),
        }


def aggregate_status(checks: Sequence[CheckResult]) -> CheckStatus:
    required = [check for check in checks if check.required]
    if any(check.status == CheckStatus.FAIL for check in required):
        return CheckStatus.FAIL
    if any(check.status == CheckStatus.NOT_CHECKED for check in required):
        return CheckStatus.NOT_CHECKED
    return CheckStatus.PASS


@dataclass
class ArtifactReport:
    path: Path
    format: str
    checks: List[CheckResult]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def overall_status(self) -> CheckStatus:
        return aggregate_status(self.checks)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "format": self.format,
            "overall_status": self.overall_status.value,
            "metadata": self.metadata,
            "checks": [check.as_dict() for check in self.checks],
        }


@dataclass
class ExportReport:
    profile_id: Optional[str]
    spec_sha256: Optional[str]
    artifacts: List[ArtifactReport]
    checks: List[CheckResult] = field(default_factory=list)
    verification_level: str = "draft"
    artifacts_committed: Optional[bool] = None

    @property
    def overall_status(self) -> CheckStatus:
        statuses = list(self.checks)
        for artifact in self.artifacts:
            statuses.extend(artifact.checks)
        return aggregate_status(statuses)

    @property
    def paths(self) -> List[Path]:
        return [artifact.path for artifact in self.artifacts]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "spec_sha256": self.spec_sha256,
            "overall_status": self.overall_status.value,
            "verification_level": self.verification_level,
            "artifacts_committed": self.artifacts_committed,
            "checks": [check.as_dict() for check in self.checks],
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
        }


class ExportValidationError(RuntimeError):
    def __init__(self, message: str, report: ExportReport):
        super().__init__(message)
        self.report = report


def _profile_hash() -> str:
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()


def _normalize_formats(formats: Sequence[str]) -> List[str]:
    if isinstance(formats, (str, bytes)):
        raise TypeError("formats must be a sequence such as ('pdf', 'png'), not a string")
    normalized: List[str] = []
    for item in formats:
        if not isinstance(item, str):
            raise TypeError("Every format must be a string")
        fmt = item.lower().lstrip(".")
        if fmt == "tif":
            fmt = "tiff"
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format {item!r}; choose from {sorted(SUPPORTED_FORMATS)}")
        if fmt not in normalized:
            normalized.append(fmt)
    if not normalized:
        raise ValueError("At least one output format is required")
    return normalized


def _profile_freshness_checks(profile: Mapping[str, Any]) -> List[CheckResult]:
    verification = profile.get("verification", {})
    state = verification.get("state")
    sources = verification.get("sources") or []
    due = verification.get("review_due_on")
    checks = [
        CheckResult(
            "profile.official_source",
            CheckStatus.PASS if state == "official_verified" and sources else CheckStatus.NOT_CHECKED,
            expected="official_verified with at least one official source",
            observed={"state": state, "sources": len(sources)},
            message="Draft profiles cannot support journal_verified status.",
            validator="visual_profiles.json",
        )
    ]
    if not due:
        status = CheckStatus.NOT_CHECKED
    else:
        try:
            status = CheckStatus.PASS if date.today() <= date.fromisoformat(due) else CheckStatus.NOT_CHECKED
        except ValueError:
            status = CheckStatus.FAIL
    checks.append(
        CheckResult(
            "profile.freshness",
            status,
            expected=f"review_due_on >= {date.today().isoformat()}",
            observed=due,
            message="Expired or malformed rules must be rechecked against the official guide.",
            validator="ISO date",
        )
    )
    return checks


def verify_profile(profile: Mapping[str, Any]) -> List[CheckResult]:
    """Return source and freshness checks for a loaded profile."""
    return _profile_freshness_checks(profile)


def _check(
    check_id: str,
    passed: bool,
    expected: Any,
    observed: Any,
    message: str,
    validator: str,
    required: bool = True,
) -> CheckResult:
    return CheckResult(
        check_id,
        CheckStatus.PASS if passed else CheckStatus.FAIL,
        required=required,
        expected=expected,
        observed=observed,
        message=message,
        validator=validator,
    )


def _parse_svg_length(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = re.fullmatch(r"\s*([0-9.]+)\s*(in|mm|cm|pt|px)?\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "px"
    factors = {"in": 25.4, "mm": 1.0, "cm": 10.0, "pt": 25.4 / 72.0, "px": 25.4 / 96.0}
    return number * factors[unit]


def inspect_artifact(path: Union[str, Path]) -> Dict[str, Any]:
    """Inspect a finished artifact; never infer properties from the Figure object."""
    artifact = Path(path)
    metadata: Dict[str, Any] = {
        "exists": artifact.is_file(),
        "size_bytes": artifact.stat().st_size if artifact.is_file() else 0,
    }
    if not artifact.is_file() or artifact.stat().st_size == 0:
        return metadata
    fmt = artifact.suffix.lower().lstrip(".")
    if fmt == "tif":
        fmt = "tiff"
    metadata["format"] = fmt
    if fmt in RASTER_FORMATS:
        from PIL import Image

        with Image.open(artifact) as image:
            dpi_value = image.info.get("dpi")
            dpi = [float(value) for value in dpi_value] if dpi_value else None
            metadata.update({
                "detected_format": (image.format or "").lower(),
                "pixel_width": int(image.width),
                "pixel_height": int(image.height),
                "mode": image.mode,
                "has_alpha": "A" in image.getbands(),
                "n_frames": int(getattr(image, "n_frames", 1)),
                "dpi": dpi,
                "compression": image.info.get("compression"),
            })
            if dpi and dpi[0] > 0 and dpi[1] > 0:
                metadata["width_mm"] = image.width / dpi[0] * 25.4
                metadata["height_mm"] = image.height / dpi[1] * 25.4
    elif fmt == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(artifact))
        metadata["pages"] = len(reader.pages)
        if reader.pages:
            box = reader.pages[0].mediabox
            metadata["width_mm"] = float(box.width) / 72.0 * 25.4
            metadata["height_mm"] = float(box.height) / 72.0 * 25.4
        metadata["detected_format"] = "pdf"
    elif fmt == "eps":
        header = artifact.read_text(encoding="latin-1", errors="ignore")[:65536]
        match = re.search(r"^%%(?:HiRes)?BoundingBox:\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)", header, re.MULTILINE)
        if match:
            x0, y0, x1, y1 = map(float, match.groups())
            metadata["width_mm"] = (x1 - x0) / 72.0 * 25.4
            metadata["height_mm"] = (y1 - y0) / 72.0 * 25.4
        metadata["detected_format"] = "eps" if header.startswith("%!PS") else "unknown"
    elif fmt == "svg":
        root = ET.parse(artifact).getroot()
        metadata["width_mm"] = _parse_svg_length(root.attrib.get("width"))
        metadata["height_mm"] = _parse_svg_length(root.attrib.get("height"))
        metadata["detected_format"] = "svg" if root.tag.endswith("svg") else "unknown"
    return metadata


def _pdf_font_checks(path: Path, forbid_type3: bool = False) -> List[CheckResult]:
    executable = shutil.which("pdffonts")
    if not executable:
        unavailable = CheckResult(
            "pdf.font_embedding",
            CheckStatus.NOT_CHECKED,
            expected="all fonts embedded",
            observed=None,
            message="pdffonts is unavailable; PDF readability is not proof of embedding.",
            validator="pdffonts",
        )
        return [unavailable, CheckResult(
            "pdf.font_type",
            CheckStatus.NOT_CHECKED,
            expected="no Type 3 fonts" if forbid_type3 else "font types inspected",
            observed=None,
            message="pdffonts is unavailable; PDF font type was not checked.",
            validator="pdffonts",
            required=forbid_type3,
        )]
    completed = subprocess.run(
        [executable, str(path)], capture_output=True, text=True, check=False, timeout=30
    )
    if completed.returncode != 0:
        unavailable = CheckResult(
            "pdf.font_embedding",
            CheckStatus.NOT_CHECKED,
            expected="all fonts embedded",
            observed=completed.stderr.strip(),
            message="pdffonts could not inspect the artifact.",
            validator="pdffonts",
        )
        return [unavailable, CheckResult(
            "pdf.font_type",
            CheckStatus.NOT_CHECKED,
            expected="no Type 3 fonts" if forbid_type3 else "font types inspected",
            observed=None,
            message="pdffonts could not inspect the artifact font types.",
            validator="pdffonts",
            required=forbid_type3,
        )]
    embedded: List[str] = []
    font_types: List[str] = []
    lines = completed.stdout.splitlines()
    type_start: Optional[int] = None
    encoding_start: Optional[int] = None
    for line in lines:
        if "name" in line and "type" in line and "encoding" in line and "emb" in line:
            type_start = line.index("type")
            encoding_start = line.index("encoding")
            break
    for line in lines:
        match = re.search(r"\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$", line)
        if match:
            embedded.append(match.group(1))
            if type_start is not None and encoding_start is not None:
                font_types.append(line[type_start:encoding_start].strip())
    embedding = _check(
        "pdf.font_embedding",
        all(value == "yes" for value in embedded),
        "all fonts embedded",
        embedded or "no fonts used",
        "Every detected PDF font must report emb=yes.",
        "pdffonts",
    )
    type_check = _check(
        "pdf.font_type",
        not forbid_type3 or all(font_type != "Type 3" for font_type in font_types),
        "no Type 3 fonts" if forbid_type3 else "font types inspected",
        font_types or "no fonts used",
        "Profile output must use embedded non-Type-3 fonts.",
        "pdffonts",
        required=forbid_type3,
    )
    return [embedding, type_check]


def _pdf_font_check(path: Path) -> CheckResult:
    return _pdf_font_checks(path)[0]


def _pdf_raster_ppi_check(path: Path, minimum_ppi: int) -> CheckResult:
    executable = shutil.which("pdfimages")
    if not executable:
        return CheckResult(
            "pdf.embedded_raster_ppi",
            CheckStatus.NOT_CHECKED,
            expected=f">= {minimum_ppi}",
            observed=None,
            message="pdfimages is unavailable; embedded raster resolution was not checked.",
            validator="pdfimages -list",
        )
    completed = subprocess.run(
        [executable, "-list", str(path)], capture_output=True, text=True, check=False, timeout=30
    )
    if completed.returncode != 0:
        return CheckResult(
            "pdf.embedded_raster_ppi",
            CheckStatus.NOT_CHECKED,
            expected=f">= {minimum_ppi}",
            observed=completed.stderr.strip(),
            message="pdfimages could not inspect embedded rasters.",
            validator="pdfimages -list",
        )
    values: List[int] = []
    for line in completed.stdout.splitlines():
        if re.match(r"^\s*\d+\s+\d+\s+", line):
            fields = line.split()
            if len(fields) >= 6:
                try:
                    values.extend([int(fields[-4]), int(fields[-3])])
                except (ValueError, IndexError):
                    continue
    observed: Any = min(values) if values else "vector-only/no embedded rasters"
    return _check(
        "pdf.embedded_raster_ppi",
        not values or min(values) >= minimum_ppi,
        f">= {minimum_ppi}",
        observed,
        "Embedded raster PPI must meet the selected figure-type minimum.",
        "pdfimages -list",
    )


def _dimension_checks(
    metadata: Mapping[str, Any],
    dimensions: Optional[Mapping[str, Any]],
    expected_size_mm: Optional[Tuple[float, float]],
    column: Optional[str],
) -> List[CheckResult]:
    checks: List[CheckResult] = []
    width = metadata.get("width_mm")
    height = metadata.get("height_mm")
    if width is None or height is None:
        return [
            CheckResult(
                "artifact.physical_size",
                CheckStatus.NOT_CHECKED,
                expected=expected_size_mm or dimensions,
                observed=None,
                message="The physical size could not be read from the finished artifact.",
                validator="artifact metadata",
            )
        ]
    if expected_size_mm:
        tolerance = float((dimensions or {}).get("tolerance_mm", 0.6))
        expected_width, expected_height = expected_size_mm
        checks.append(_check(
            "artifact.canvas_width",
            abs(width - expected_width) <= tolerance,
            expected_width,
            width,
            "Exported width must match the Figure canvas; tight cropping changes physical size.",
            "finished artifact",
        ))
        checks.append(_check(
            "artifact.canvas_height",
            abs(height - expected_height) <= tolerance,
            expected_height,
            height,
            "Exported height must match the Figure canvas; tight cropping changes physical size.",
            "finished artifact",
        ))
    if dimensions:
        tolerance = float(dimensions.get("tolerance_mm", 0.6))
        targets = dimensions.get("width_targets_mm")
        width_range = dimensions.get("width_range_mm")
        if targets:
            if column not in targets:
                checks.append(CheckResult(
                    "profile.column",
                    CheckStatus.FAIL,
                    expected=sorted(targets),
                    observed=column,
                    message="A target-width profile requires an explicit valid column.",
                    validator="visual profile",
                ))
            else:
                checks.append(_check(
                    "profile.width",
                    abs(width - float(targets[column])) <= tolerance,
                    float(targets[column]),
                    width,
                    "Finished width must match the selected journal column.",
                    "finished artifact",
                ))
        elif width_range:
            low, high = map(float, width_range)
            checks.append(_check(
                "profile.width",
                low - tolerance <= width <= high + tolerance,
                [low, high],
                width,
                "Finished width must remain inside the journal range.",
                "finished artifact",
            ))
        checks.append(_check(
            "profile.max_height",
            height <= float(dimensions["max_height_mm"]) + tolerance,
            f"<= {dimensions['max_height_mm']}",
            height,
            "Finished height must not exceed the profile maximum.",
            "finished artifact",
        ))
    return checks


def verify_artifact(
    path: Union[str, Path],
    *,
    profile: Optional[Mapping[str, Any]] = None,
    figure_type: str = "combination",
    column: Optional[str] = None,
    expected_size_mm: Optional[Tuple[float, float]] = None,
    expected_dpi: Optional[int] = None,
    artifact_constraints: Optional[Mapping[str, Any]] = None,
) -> ArtifactReport:
    artifact = Path(path)
    metadata = inspect_artifact(artifact)
    fmt = artifact.suffix.lower().lstrip(".")
    if fmt == "tif":
        fmt = "tiff"
    checks: List[CheckResult] = []
    checks.append(_check(
        "artifact.exists_nonempty",
        bool(metadata.get("exists") and metadata.get("size_bytes", 0) > 0),
        "existing non-empty file",
        metadata.get("size_bytes", 0),
        "Export must produce a non-empty file.",
        "filesystem",
    ))
    if not metadata.get("exists") or metadata.get("size_bytes", 0) == 0:
        return ArtifactReport(artifact, fmt, checks, metadata)
    checks.append(_check(
        "artifact.signature",
        metadata.get("detected_format") == fmt,
        fmt,
        metadata.get("detected_format"),
        "File signature/content must agree with its extension.",
        "Pillow/pypdf/XML/header",
    ))

    dimensions = profile.get("dimensions") if profile else None
    checks.extend(_dimension_checks(metadata, dimensions, expected_size_mm, column))

    selected_rule: Mapping[str, Any] = {}
    if profile:
        figure_rules = profile.get("figure_types", {})
        if figure_type not in figure_rules:
            checks.append(CheckResult(
                "profile.figure_type",
                CheckStatus.FAIL,
                expected=sorted(figure_rules),
                observed=figure_type,
                message="Unknown figure type for this profile.",
                validator="visual profile",
            ))
        else:
            selected_rule = figure_rules[figure_type]
            checks.append(_check(
                "profile.format",
                fmt in selected_rule["formats"],
                selected_rule["formats"],
                fmt,
                "Artifact format must be allowed for the selected figure type.",
                "visual profile",
            ))
            expected_dpi = int(selected_rule["raster_dpi"])

    if fmt in RASTER_FORMATS:
        dpi_values = metadata.get("dpi")
        if expected_dpi is not None:
            minimum = min(dpi_values) if dpi_values else None
            checks.append(_check(
                "raster.ppi",
                minimum is not None and minimum >= expected_dpi - 1.0,
                f">= {expected_dpi}",
                dpi_values,
                "Finished raster resolution must meet the requested minimum.",
                "Pillow metadata",
            ))
        if selected_rule.get("max_raster_dpi") is not None:
            maximum = max(dpi_values) if dpi_values else None
            checks.append(_check(
                "raster.max_ppi",
                maximum is not None and maximum <= float(selected_rule["max_raster_dpi"]) + 1.0,
                f"<= {selected_rule['max_raster_dpi']}",
                dpi_values,
                "Finished raster resolution must not exceed the profile maximum.",
                "Pillow metadata",
            ))
        if profile:
            allowed_modes = profile["color"]["allowed_modes"]
            observed_mode = "GRAYSCALE" if metadata.get("mode") in {"1", "L", "I", "F"} else metadata.get("mode")
            checks.append(_check(
                "raster.color_mode",
                observed_mode in allowed_modes,
                allowed_modes,
                observed_mode,
                "Raster color mode must be allowed by the profile.",
                "Pillow",
            ))
            checks.append(_check(
                "raster.alpha",
                profile["color"].get("alpha_allowed", False) or not metadata.get("has_alpha"),
                profile["color"].get("alpha_allowed", False),
                metadata.get("has_alpha"),
                "Alpha is not allowed for this profile.",
                "Pillow",
            ))
            if fmt == "tiff":
                expected_compression = profile["tiff"]["compression"].replace("tiff_", "")
                observed_compression = str(metadata.get("compression", "")).replace("tiff_", "")
                checks.append(_check(
                    "tiff.compression",
                    observed_compression == expected_compression,
                    expected_compression,
                    observed_compression,
                    "TIFF must use the configured lossless compression.",
                    "Pillow",
                ))
                checks.append(_check(
                    "tiff.frames",
                    metadata.get("n_frames") == 1,
                    1,
                    metadata.get("n_frames"),
                    "A submission TIFF must contain exactly one frame/page.",
                    "Pillow",
                ))
    elif fmt == "pdf":
        checks.extend(_pdf_font_checks(
            artifact,
            forbid_type3=bool(profile and profile.get("pdf", {}).get("forbid_type3")),
        ))
        if expected_dpi is not None:
            checks.append(_pdf_raster_ppi_check(artifact, expected_dpi))
        checks.append(_check(
            "pdf.pages",
            metadata.get("pages") == 1,
            1,
            metadata.get("pages"),
            "A figure PDF must contain exactly one page.",
            "pypdf",
        ))
    elif fmt in {"eps", "svg"} and profile:
        checks.append(CheckResult(
            f"{fmt}.font_embedding",
            CheckStatus.NOT_CHECKED,
            expected="fonts embedded or outlined",
            observed=None,
            message=f"Automated {fmt.upper()} font verification is unavailable.",
            validator="none",
        ))

    if profile and profile.get("max_file_mb") is not None:
        actual_mb = metadata["size_bytes"] / 1_000_000
        checks.append(_check(
            "profile.max_file_size",
            actual_mb <= float(profile["max_file_mb"]),
            f"<= {profile['max_file_mb']} MB",
            actual_mb,
            "Artifact size must not exceed the profile limit.",
            "filesystem",
        ))
    constraints = dict(artifact_constraints or {})
    if constraints:
        if constraints.get("color_mode") is not None:
            observed_mode = "GRAYSCALE" if metadata.get("mode") in {"1", "L", "I", "F"} else metadata.get("mode")
            checks.append(_check(
                "user.color_mode",
                observed_mode == constraints["color_mode"],
                constraints["color_mode"],
                observed_mode,
                "Artifact color mode must match the user-specific requirement.",
                "finished artifact",
            ))
        if constraints.get("exact_ppi") is not None:
            observed_dpi = metadata.get("dpi")
            tolerance_ppi = float(constraints.get("ppi_tolerance", 1.0))
            exact_ppi = float(constraints["exact_ppi"])
            checks.append(_check(
                "user.exact_ppi",
                bool(observed_dpi)
                and all(abs(float(value) - exact_ppi) <= tolerance_ppi for value in observed_dpi),
                {"value": exact_ppi, "tolerance": tolerance_ppi},
                observed_dpi,
                "Raster PPI must match the user-specific target within metadata tolerance.",
                "Pillow metadata",
            ))
        if constraints.get("single_frame") is True and fmt in RASTER_FORMATS:
            checks.append(_check(
                "user.single_frame",
                metadata.get("n_frames") == 1,
                1,
                metadata.get("n_frames"),
                "Artifact must contain one frame/page.",
                "Pillow",
            ))
    return ArtifactReport(artifact, fmt, checks, metadata)


def _normalize_raster(path: Path, fmt: str, dpi: int, transparent: bool, facecolor: str, profile: Optional[Mapping[str, Any]]) -> None:
    from PIL import Image, ImageColor

    must_flatten = bool(profile and not profile["color"].get("alpha_allowed", False)) or not transparent
    compression = (profile or {}).get("tiff", {}).get("compression", "tiff_lzw")
    with Image.open(path) as source:
        image = source.copy()
    if must_flatten and "A" in image.getbands():
        background = Image.new("RGBA", image.size, ImageColor.getrgb(facecolor) + (255,))
        background.alpha_composite(image.convert("RGBA"))
        image = background.convert("RGB")
    elif image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    temp = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.normalized{path.suffix}")
    save_kwargs: Dict[str, Any] = {"dpi": (dpi, dpi)}
    if fmt == "tiff":
        save_kwargs["compression"] = compression
        save_kwargs["format"] = "TIFF"
    else:
        save_kwargs["format"] = "PNG"
    try:
        image.save(temp, **save_kwargs)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def export_publication_figure(
    fig: Any,
    filename: Union[str, Path],
    formats: Sequence[str] = ("pdf",),
    dpi: int = 300,
    *,
    profile_name: Optional[str] = None,
    figure_type: str = "combination",
    column: Optional[str] = None,
    transparent: bool = False,
    bbox_inches: Optional[str] = None,
    pad_inches: float = 0.0,
    facecolor: str = "white",
    create_dirs: bool = False,
    overwrite: bool = False,
    strict: bool = True,
    savefig_kwargs: Optional[Mapping[str, Any]] = None,
    artifact_constraints: Optional[Mapping[str, Any]] = None,
    style_overrides: Optional[Mapping[str, Any]] = None,
) -> ExportReport:
    """Export as an atomic batch and verify the finished files."""
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    if bbox_inches not in {None, "tight"}:
        raise ValueError("bbox_inches must be None or 'tight'")
    format_list = _normalize_formats(formats)
    base = Path(filename)
    if base.suffix.lower().lstrip(".") in SUPPORTED_FORMATS | {"tif"}:
        base = base.with_suffix("")
    parent = base.parent
    if not parent.exists():
        if create_dirs:
            parent.mkdir(parents=True, exist_ok=True)
        else:
            raise FileNotFoundError(f"Parent directory does not exist: {parent}")
    if not parent.is_dir():
        raise NotADirectoryError(str(parent))
    targets = [parent / f"{base.name}.{fmt}" for fmt in format_list]
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Refusing to overwrite: {', '.join(map(str, existing))}")

    profile = get_profile(profile_name) if profile_name else None
    profile_checks = _profile_freshness_checks(profile) if profile else []
    if profile:
        rules = profile.get("figure_types", {})
        if figure_type not in rules:
            raise ValueError(f"Unknown figure_type {figure_type!r}; choose from {sorted(rules)}")
        illegal = [fmt for fmt in format_list if fmt not in rules[figure_type]["formats"]]
        if illegal:
            raise ValueError(f"Formats {illegal} are not allowed by profile {profile['id']!r}")
        expected_dpi = int(rules[figure_type]["raster_dpi"])
        if dpi < expected_dpi:
            raise ValueError(f"dpi {dpi} is below profile minimum {expected_dpi}")
    expected_size_mm = tuple(float(value) * 25.4 for value in fig.get_size_inches())
    forbidden = {"format", "dpi", "transparent", "facecolor", "bbox_inches", "pad_inches"}
    user_kwargs = dict(savefig_kwargs or {})
    overlap = sorted(forbidden.intersection(user_kwargs))
    if overlap:
        raise ValueError(f"savefig_kwargs may not override controlled fields: {overlap}")

    temp_pairs: List[Tuple[Path, Path]] = []
    temp_reports: List[ArtifactReport] = []
    try:
        for target, fmt in zip(targets, format_list):
            temp = parent / f".{base.name}.{uuid.uuid4().hex}.tmp.{fmt}"
            temp_pairs.append((temp, target))
            kwargs = {
                "format": fmt,
                "dpi": dpi,
                "transparent": transparent,
                "facecolor": "none" if transparent else facecolor,
                "edgecolor": "none",
                "bbox_inches": bbox_inches,
                "pad_inches": pad_inches,
            }
            kwargs.update(user_kwargs)
            style_scope = (
                publication_style(profile["style"], rc_overrides=style_overrides)
                if profile
                else nullcontext()
            )
            with style_scope:
                fig.savefig(temp, **kwargs)
            if fmt in RASTER_FORMATS:
                _normalize_raster(temp, fmt, dpi, transparent, facecolor, profile)
            report = verify_artifact(
                temp,
                profile=profile,
                figure_type=figure_type,
                column=column,
                expected_size_mm=expected_size_mm,
                expected_dpi=dpi,
                artifact_constraints=artifact_constraints,
            )
            report.path = target
            temp_reports.append(report)
        report = ExportReport(
            profile_id=profile.get("id") if profile else None,
            spec_sha256=_profile_hash() if profile else None,
            artifacts=temp_reports,
            checks=profile_checks,
            artifacts_committed=False,
        )
        if report.overall_status != CheckStatus.PASS:
            raise ExportValidationError("Artifact verification did not fully pass", report)
        for temp, target in temp_pairs:
            temp.replace(target)
        report.artifacts_committed = True
        return report
    except Exception:
        for temp, _target in temp_pairs:
            temp.unlink(missing_ok=True)
        if strict:
            raise
        if "report" in locals():
            return report
        raise


def export_for_journal(
    fig: Any,
    filename: Union[str, Path],
    journal: str,
    submission_stage: str = "final",
    figure_type: str = "combination",
    column: Optional[str] = None,
    *,
    formats: Optional[Sequence[str]] = None,
    strict: bool = True,
    create_dirs: bool = False,
    overwrite: bool = False,
) -> ExportReport:
    if submission_stage != "final":
        raise ValueError("Only explicitly versioned final profiles are supported; use generic-draft for drafts")
    profile = get_profile(journal)
    rules = profile["figure_types"]
    if figure_type not in rules:
        raise ValueError(f"Unknown figure_type {figure_type!r}; choose from {sorted(rules)}")
    chosen = list(formats) if formats is not None else [rules[figure_type]["formats"][0]]
    return export_publication_figure(
        fig,
        filename,
        chosen,
        int(rules[figure_type]["raster_dpi"]),
        profile_name=profile["id"],
        figure_type=figure_type,
        column=column,
        create_dirs=create_dirs,
        overwrite=overwrite,
        strict=strict,
    )


def save_publication_figure(
    fig: Any,
    filename: Union[str, Path],
    formats: Sequence[str] = ("pdf",),
    dpi: int = 300,
    transparent: bool = False,
    bbox_inches: Optional[str] = None,
    pad_inches: float = 0.0,
    facecolor: str = "white",
    **kwargs: Any,
) -> List[Path]:
    """Strict compatibility wrapper; failures are raised instead of printed."""
    report = export_publication_figure(
        fig,
        filename,
        formats,
        dpi,
        transparent=transparent,
        bbox_inches=bbox_inches,
        pad_inches=pad_inches,
        facecolor=facecolor,
        savefig_kwargs=kwargs,
    )
    return report.paths


def save_for_journal(
    fig: Any,
    filename: Union[str, Path],
    journal: str,
    figure_type: str = "combination",
) -> List[Path]:
    return export_for_journal(fig, filename, journal, figure_type=figure_type).paths


def check_figure_size(
    fig: Any, journal: str = "nature", column: Optional[str] = None
) -> Dict[str, Any]:
    """Pre-export size check only; this is not a finished-artifact certification."""
    profile = get_profile(journal)
    width_inches, height_inches = map(float, fig.get_size_inches())
    width_mm, height_mm = width_inches * 25.4, height_inches * 25.4
    dimensions = profile["dimensions"]
    tolerance = float(dimensions.get("tolerance_mm", 0.6))
    width_ok = False
    if dimensions.get("width_targets_mm"):
        targets = dimensions["width_targets_mm"]
        if column not in targets:
            raise ValueError(f"column must be one of {sorted(targets)}")
        width_ok = abs(width_mm - float(targets[column])) <= tolerance
    elif dimensions.get("width_range_mm"):
        low, high = map(float, dimensions["width_range_mm"])
        width_ok = low - tolerance <= width_mm <= high + tolerance
    height_ok = height_mm <= float(dimensions["max_height_mm"]) + tolerance
    return {
        "width_inches": width_inches,
        "height_inches": height_inches,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "profile_id": profile["id"],
        "column": column,
        "width_ok": bool(width_ok),
        "height_ok": bool(height_ok),
        "preflight_status": CheckStatus.PASS.value if width_ok and height_ok else CheckStatus.FAIL.value,
        "certification": "NOT_CHECKED",
    }


def verify_font_embedding(pdf_path: Union[str, Path]) -> Optional[bool]:
    """Compatibility mapping: PASS=True, FAIL=False, NOT_CHECKED=None."""
    check = _pdf_font_check(Path(pdf_path))
    if check.status == CheckStatus.PASS:
        return True
    if check.status == CheckStatus.FAIL:
        return False
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Inspect a finished scientific figure")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--figure-type", default="combination")
    parser.add_argument("--column")
    parser.add_argument("--exact-ppi", type=float)
    parser.add_argument("--color-mode", choices=["RGB", "GRAYSCALE"])
    parser.add_argument("--single-frame", action="store_true")
    args = parser.parse_args()
    selected = get_profile(args.profile) if args.profile else None
    result = verify_artifact(
        args.artifact,
        profile=selected,
        figure_type=args.figure_type,
        column=args.column,
        artifact_constraints={
            key: value
            for key, value in {
                "exact_ppi": args.exact_ppi,
                "color_mode": args.color_mode,
                "single_frame": args.single_frame or None,
            }.items()
            if value is not None
        },
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.overall_status == CheckStatus.PASS else 2)
