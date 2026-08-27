#!/usr/bin/env python3
"""Two-stage scientific-figure pipeline with contracts, QA, and safe packaging."""

from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

os.environ.setdefault("MPLBACKEND", "Agg")
_MPL_ALREADY_IMPORTED = "matplotlib" in sys.modules
_MANAGED_MPLCONFIGDIR: Optional[Path] = None
if not _MPL_ALREADY_IMPORTED:
    cache_parent = Path(os.environ.get("MPLCONFIGDIR", tempfile.gettempdir()))
    _MANAGED_MPLCONFIGDIR = cache_parent / f"academic-sciviz-{os.getpid()}-{uuid.uuid4().hex}"
    os.environ["MPLCONFIGDIR"] = str(_MANAGED_MPLCONFIGDIR)


def _clear_managed_mpl_cache() -> None:
    if _MANAGED_MPLCONFIGDIR is not None:
        shutil.rmtree(_MANAGED_MPLCONFIGDIR, ignore_errors=True)


atexit.register(_clear_managed_mpl_cache)

try:
    from .figure_export import (
        ArtifactReport,
        CheckResult,
        CheckStatus,
        ExportReport,
        aggregate_status,
        export_publication_figure,
        verify_artifact,
        verify_profile,
    )
    from .font_preflight import inspect_font, run_preflight
    from .statistics_gate import validate_statistics
    from .style_presets import CONFIG_PATH, get_profile, publication_style
except ImportError:
    from figure_export import (
        ArtifactReport,
        CheckResult,
        CheckStatus,
        ExportReport,
        aggregate_status,
        export_publication_figure,
        verify_artifact,
        verify_profile,
    )
    from font_preflight import inspect_font, run_preflight
    from statistics_gate import validate_statistics
    from style_presets import CONFIG_PATH, get_profile, publication_style


MODES = {"create", "redesign", "visual_audit", "manuscript_set"}
STAGES = {"preview", "final"}
VISUAL_CHECKS = {
    "crop",
    "overlap",
    "legibility",
    "glyphs",
    "accessibility",
    "data_alignment",
}
FORBIDDEN_IDENTIFIER_KEYS = {
    "patient_name",
    "patient_id",
    "mrn",
    "email",
    "phone",
    "direct_identifier",
}
SAFE_EVIDENCE_OPERATIONS = {
    "global_adjustment",
    "crop",
    "rotation",
    "channel_mapping",
    "scale_bar",
    "declared_splice",
}
INLINE_DATA_KEYS = {"data", "values", "records", "rows", "observations"}
IDENTIFIER_PATTERNS = {
    "mrn": re.compile(r"(?i)(?<![a-z0-9])mrn[\s:_-]*[a-z0-9]{4,}(?![a-z0-9])"),
    "email": re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b"),
    "phone": re.compile(r"(?<![\d-])(?:\+?\d[\s().-]?){10,15}(?![\d-])"),
    "cn_identifier": re.compile(r"(?:病历号|住院号|身份证号|手机号)\s*[:：_-]?\s*[A-Za-z0-9]{4,}"),
}


def _check(check_id: str, condition: bool, expected: Any, observed: Any, message: str) -> CheckResult:
    return CheckResult(
        check_id,
        CheckStatus.PASS if condition else CheckStatus.FAIL,
        expected=expected,
        observed=observed,
        message=message,
        validator="figure_pipeline",
    )


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _walk_keys(value: Any) -> List[str]:
    keys: List[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            keys.append(str(key).lower())
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def _walk_strings(value: Any, location: str = "job") -> List[Tuple[str, str]]:
    strings: List[Tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            strings.extend(_walk_strings(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            strings.extend(_walk_strings(child, f"{location}[{index}]"))
    elif isinstance(value, str):
        strings.append((location, value))
    return strings


def _identifier_hits(value: Any) -> List[Dict[str, str]]:
    hits: List[Dict[str, str]] = []
    for location, text in _walk_strings(value):
        for pattern_name, pattern in IDENTIFIER_PATTERNS.items():
            if pattern.search(text):
                hits.append({"location": location, "pattern": pattern_name})
    return hits


def _path_key(key: str) -> bool:
    lowered = key.lower()
    return lowered == "path" or lowered.endswith("_path") or lowered.endswith("_paths")


def _source_path_values(value: Any, location: str = "source") -> List[Tuple[str, str]]:
    paths: List[Tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if _path_key(str(key)):
                if isinstance(child, str):
                    paths.append((child_location, child))
                elif isinstance(child, list):
                    paths.extend(
                        (f"{child_location}[{index}]", item)
                        for index, item in enumerate(child)
                        if isinstance(item, str)
                    )
            else:
                paths.extend(_source_path_values(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_source_path_values(child, f"{location}[{index}]"))
    return paths


def _semantic_figure_texts(fig: Any) -> List[str]:
    texts: List[str] = []
    for ax in fig.axes:
        candidates = [ax.get_title(), ax.get_xlabel(), ax.get_ylabel()]
        candidates.extend(item.get_text() for item in ax.texts)
        legend = ax.get_legend()
        if legend:
            candidates.extend(item.get_text() for item in legend.get_texts())
            title = legend.get_title().get_text()
            if title:
                candidates.append(title)
        for tick in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            text = tick.get_text().strip()
            if text and not re.fullmatch(r"[\d\s.,+−-]+", text):
                candidates.append(text)
        texts.extend(text.strip() for text in candidates if isinstance(text, str) and text.strip())
    texts.extend(item.get_text().strip() for item in getattr(fig, "texts", []) if item.get_text().strip())
    return sorted(set(texts))


def _safe_base_name(value: Any) -> bool:
    return _nonempty(value) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value) is not None


def validate_job(
    job: Mapping[str, Any], execution_paths: Sequence[str] = ()
) -> Dict[str, Any]:
    checks: List[CheckResult] = []
    checks.append(_check("job.schema_version", job.get("schema_version") == 1, 1, job.get("schema_version"), "Unsupported job schema."))
    mode = job.get("mode")
    checks.append(_check("job.mode", mode in MODES, sorted(MODES), mode, "Select one explicit task mode."))
    checks.append(_check("job.question", _nonempty(job.get("question")), "scientific question or relationship", job.get("question"), "The figure must have a stated analytical purpose."))
    source = job.get("source")
    checks.append(_check("job.source", isinstance(source, Mapping), "source object", type(source).__name__, "Source provenance is required."))
    target = job.get("target")
    checks.append(_check("job.target", isinstance(target, Mapping), "target object", type(target).__name__, "Target profile and use are required."))
    delivery = job.get("delivery")
    base_name = delivery.get("base_name") if isinstance(delivery, Mapping) else None
    checks.append(_check("job.delivery.base_name", _safe_base_name(base_name), "safe filename stem", base_name, "Use a short identifier-free filename stem."))
    forbidden_anywhere = sorted(set(_walk_keys(job)).intersection(FORBIDDEN_IDENTIFIER_KEYS))
    checks.append(_check("job.no_direct_identifier_fields", not forbidden_anywhere, "no direct-identifier fields anywhere in the job", forbidden_anywhere, "Direct identifiers must be removed before the job is created."))

    if isinstance(source, Mapping):
        sensitivity = source.get("sensitivity")
        checks.append(_check("job.source.sensitivity", sensitivity in {"public", "unpublished", "sensitive"}, ["public", "unpublished", "sensitive"], sensitivity, "Declare source sensitivity."))
        forbidden = sorted(set(_walk_keys(source)).intersection(FORBIDDEN_IDENTIFIER_KEYS))
        checks.append(_check("job.source.no_direct_identifiers", not forbidden, "no direct-identifier fields", forbidden, "Direct identifiers must not enter jobs, labels, manifests, or caches."))
        inline_keys = sorted(set(_walk_keys(job)).intersection(INLINE_DATA_KEYS))
        checks.append(_check("job.source.no_inline_data", not inline_keys, "data supplied by declared file paths", inline_keys, "Do not embed observations in the Job; use hashable source files."))
        if sensitivity == "sensitive":
            checks.append(_check("job.source.deidentified", source.get("deidentified") is True, True, source.get("deidentified"), "Sensitive inputs must be deidentified before plotting."))
            checks.append(_check("job.source.external_sharing", source.get("external_sharing") is False, False, source.get("external_sharing"), "Sensitive inputs default to local-only processing."))
            checks.append(_check("job.source.package_data", source.get("package_data") is False, False, source.get("package_data"), "Sensitive source files are never copied into the portable package."))
            privacy_review = source.get("privacy_review")
            checks.append(_check(
                "job.source.privacy_review",
                isinstance(privacy_review, Mapping)
                and privacy_review.get("status") == CheckStatus.PASS.value
                and _nonempty(privacy_review.get("reviewer")),
                {"status": "PASS", "reviewer": "non-empty"},
                privacy_review,
                "Sensitive work requires an explicit deidentification review.",
            ))
            identifier_hits = _identifier_hits({
                "job": job,
                "execution_paths": list(execution_paths),
            })
            checks.append(_check(
                "job.source.identifier_value_scan",
                not identifier_hits,
                "no high-confidence identifier patterns in values",
                identifier_hits,
                "Potential identifiers were found; remove them before plotting.",
            ))
            checks.append(_check(
                "environment.network_isolation",
                os.environ.get("ACADEMIC_SCIVIZ_NETWORK_ISOLATED") == "1",
                "externally verified egress-disabled runtime",
                "verified" if os.environ.get("ACADEMIC_SCIVIZ_NETWORK_ISOLATED") == "1" else "not verified",
                "Do not execute arbitrary plotting code on sensitive data without host-level network isolation.",
            ))
            checks.append(_check(
                "environment.cache_isolation",
                _MANAGED_MPLCONFIGDIR is not None,
                "pipeline-managed disposable Matplotlib cache",
                str(_MANAGED_MPLCONFIGDIR) if _MANAGED_MPLCONFIGDIR else "Matplotlib imported before pipeline",
                "Sensitive runs require a disposable cache created before Matplotlib import.",
            ))
        if source.get("evidence_image") is True:
            checks.append(_check("integrity.original_read_only", source.get("original_read_only") is True, True, source.get("original_read_only"), "Microscopy, gel, and blot originals must remain read-only."))
            checks.append(_check("integrity.generative_editing", source.get("generative_editing") is False, False, source.get("generative_editing"), "Generative editing is prohibited for evidentiary images."))
            transformations = source.get("transformations")
            operations = [
                item.get("operation")
                for item in transformations
                if isinstance(item, Mapping)
            ] if isinstance(transformations, list) else []
            checks.append(_check("integrity.transformations", isinstance(transformations, list) and len(operations) == len(transformations) and set(operations) <= SAFE_EVIDENCE_OPERATIONS, sorted(SAFE_EVIDENCE_OPERATIONS), operations, "Only declared, traceable evidence-image operations are allowed."))
            for index, item in enumerate(transformations or []):
                if isinstance(item, Mapping) and item.get("operation") == "global_adjustment":
                    checks.append(_check(
                        f"integrity.transformations[{index}].global_scope",
                        item.get("scope") == "global" and isinstance(item.get("parameters"), Mapping) and bool(item.get("parameters")),
                        {"scope": "global", "parameters": "non-empty object"},
                        {"scope": item.get("scope"), "parameters": item.get("parameters")},
                        "Global adjustments must apply to the whole image with recorded parameters.",
                    ))
                if isinstance(item, Mapping) and item.get("operation") == "crop":
                    bounds = item.get("bounds")
                    checks.append(_check(
                        f"integrity.transformations[{index}].crop_bounds",
                        isinstance(bounds, list)
                        and len(bounds) == 4
                        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in bounds)
                        and _nonempty(item.get("reason")),
                        {"bounds": "[x0, y0, x1, y1]", "reason": "non-empty"},
                        {"bounds": bounds, "reason": item.get("reason")},
                        "Every crop requires coordinates and a scientific/layout reason.",
                    ))
                if isinstance(item, Mapping) and item.get("operation") == "rotation":
                    angle = item.get("angle_degrees")
                    checks.append(_check(
                        f"integrity.transformations[{index}].rotation",
                        isinstance(angle, (int, float)) and not isinstance(angle, bool),
                        "numeric angle_degrees",
                        angle,
                        "Every rotation requires a recorded angle.",
                    ))
                if isinstance(item, Mapping) and item.get("operation") == "channel_mapping":
                    mapping = item.get("mapping")
                    checks.append(_check(
                        f"integrity.transformations[{index}].channel_mapping",
                        isinstance(mapping, Mapping) and bool(mapping),
                        "non-empty source-to-display channel mapping",
                        mapping,
                        "Displayed channels must be traceable to source channels.",
                    ))
                if isinstance(item, Mapping) and item.get("operation") == "scale_bar":
                    scale_valid = (
                        _nonempty(item.get("calibration_source"))
                        and isinstance(item.get("length"), (int, float))
                        and not isinstance(item.get("length"), bool)
                        and float(item.get("length")) > 0
                        and _nonempty(item.get("unit"))
                    )
                    checks.append(_check(f"integrity.transformations[{index}].calibration", scale_valid, "calibration source, positive length, and unit", {"calibration_source": item.get("calibration_source"), "length": item.get("length"), "unit": item.get("unit")}, "Scale bars require metadata calibration and declared physical length."))
                if isinstance(item, Mapping) and item.get("operation") == "declared_splice":
                    checks.append(_check(
                        f"integrity.transformations[{index}].splice_marked",
                        item.get("boundaries_marked") is True and _nonempty(item.get("reason")),
                        {"boundaries_marked": True, "reason": "non-empty"},
                        {"boundaries_marked": item.get("boundaries_marked"), "reason": item.get("reason")},
                        "Any allowed splice must be visibly bounded and scientifically justified.",
                    ))

    if isinstance(target, Mapping):
        profile_name = target.get("profile")
        try:
            profile = get_profile(profile_name)
            checks.append(_check("job.target.profile", True, "known exact profile", profile["id"], "Profile resolved exactly."))
            figure_type = target.get("figure_type")
            checks.append(_check("job.target.figure_type", figure_type in profile["figure_types"], sorted(profile["figure_types"]), figure_type, "Figure type must exist in the selected profile."))
            requested_formats = target.get("formats")
            allowed_formats = profile["figure_types"].get(figure_type, {}).get("formats", [])
            formats_valid = (
                requested_formats is None
                or (
                    isinstance(requested_formats, list)
                    and bool(requested_formats)
                    and all(isinstance(item, str) and item.lower().lstrip(".") in allowed_formats for item in requested_formats)
                )
            )
            checks.append(_check("job.target.formats", formats_valid, allowed_formats, requested_formats, "Every requested format must be allowed by the exact profile."))
            requirements = target.get("requirements", {})
            requirements_valid = (
                isinstance(requirements, Mapping)
                and set(requirements) <= {"color_mode", "exact_ppi", "ppi_tolerance", "single_frame"}
                and requirements.get("color_mode") in {None, "RGB", "GRAYSCALE"}
                and (
                    requirements.get("exact_ppi") is None
                    or (
                        isinstance(requirements.get("exact_ppi"), (int, float))
                        and not isinstance(requirements.get("exact_ppi"), bool)
                        and math.isfinite(float(requirements.get("exact_ppi")))
                        and float(requirements.get("exact_ppi")) > 0
                    )
                )
                and (
                    requirements.get("ppi_tolerance") is None
                    or (
                        isinstance(requirements.get("ppi_tolerance"), (int, float))
                        and not isinstance(requirements.get("ppi_tolerance"), bool)
                        and math.isfinite(float(requirements.get("ppi_tolerance")))
                        and float(requirements.get("ppi_tolerance")) >= 0
                    )
                )
                and requirements.get("single_frame") in {None, True, False}
            )
            checks.append(_check("job.target.requirements", requirements_valid, "supported user-specific artifact constraints", requirements, "Use color_mode, exact_ppi, ppi_tolerance, or single_frame only."))
            targets = profile["dimensions"].get("width_targets_mm")
            if targets:
                checks.append(_check("job.target.column", target.get("column") in targets, sorted(targets), target.get("column"), "Target-width profiles require an explicit column."))
        except Exception as exc:
            checks.append(_check("job.target.profile", False, "known exact profile", str(exc), "Unknown profiles never fall back to another journal."))
        checks.append(_check("job.target.submission_stage", target.get("submission_stage") in {"draft", "final"}, ["draft", "final"], target.get("submission_stage"), "Declare draft or final use."))
        if target.get("submission_stage") == "final" and mode != "manuscript_set":
            checks.append(_check("job.caption", _nonempty(job.get("caption")), "complete final caption", job.get("caption"), "Final submissions require a caption with statistical and transformation definitions."))
        labels = target.get("labels")
        checks.append(_check("job.target.labels", isinstance(labels, list) and all(isinstance(label, str) for label in labels), "complete list of final strings", labels, "Font preflight requires every displayed string."))
        font = target.get("font")
        checks.append(_check("job.target.font", isinstance(font, Mapping) and (_nonempty(font.get("family")) or _nonempty(font.get("path"))), "font family or path", font, "Final font must be explicit."))

    analysis = job.get("analysis")
    checks.append(_check("job.analysis", isinstance(analysis, Mapping), "analysis object", type(analysis).__name__, "Analysis and uncertainty definitions are required."))
    if isinstance(analysis, Mapping):
        checks.append(_check("job.analysis.annotations_requested", isinstance(analysis.get("annotations_requested"), bool), "boolean", analysis.get("annotations_requested"), "Declare inferential annotation intent."))
        if analysis.get("annotations_requested") is True:
            checks.append(_check("job.statistics_file", _nonempty(job.get("statistics_file")), "structured statistics evidence path", job.get("statistics_file"), "Inferential annotations require a statistics evidence file."))
        if mode == "create":
            for key in ("analysis_unit", "sample_size", "missing_data", "transformation", "uncertainty", "variables"):
                value = analysis.get(key)
                checks.append(_check(f"job.analysis.{key}", value not in {None, ""} if not isinstance(value, (list, dict)) else bool(value), "declared", value, f"{key} is required in create mode."))
            source_paths = _source_path_values(source) if isinstance(source, Mapping) else []
            checks.append(_check("job.source.data_paths", bool(source_paths), "at least one declared source file path", [location for location, _ in source_paths], "Create mode requires file-backed data for hashing and mutation checks."))
            checks.append(_check("job.source.package_data", isinstance(source.get("package_data"), bool) if isinstance(source, Mapping) else False, "boolean", source.get("package_data") if isinstance(source, Mapping) else None, "Declare whether authorized source files may enter the reproducibility package."))
            if isinstance(source, Mapping) and source.get("package_data") is True:
                checks.append(_check("job.source.package_data_authorized", source.get("package_data_authorized") is True, True, source.get("package_data_authorized"), "Packaging source data requires explicit authorization."))
    if mode == "redesign" and isinstance(source, Mapping):
        checks.append(_check("job.redesign.figure_path", _nonempty(source.get("figure_path")), "existing figure path", source.get("figure_path"), "Redesign mode requires the original figure."))
        checks.append(_check("job.redesign.constraints", bool(job.get("preserve")) and bool(job.get("change")), "non-empty preserve and change lists", {"preserve": job.get("preserve"), "change": job.get("change")}, "State what may and may not change."))
    if mode == "visual_audit" and isinstance(source, Mapping):
        checks.append(_check("job.audit.figure_path", _nonempty(source.get("figure_path")), "finished artifact path", source.get("figure_path"), "Audit mode requires a finished file."))
    if mode == "manuscript_set":
        figures = job.get("figures")
        valid = (
            isinstance(figures, list)
            and bool(figures)
            and all(
                isinstance(item, Mapping)
                and _safe_base_name(item.get("id"))
                and _nonempty(item.get("source_ref"))
                and _nonempty(item.get("question"))
                and _nonempty(item.get("caption"))
                for item in figures
            )
        )
        checks.append(_check("job.figures", valid, "non-empty list with safe unique ids", figures, "Manuscript-set mode requires an explicit figure list."))
        if valid:
            ids = [item["id"] for item in figures]
            checks.append(_check("job.figures.unique", len(ids) == len(set(ids)), "unique ids", ids, "Figure ids must be unique."))
        checks.append(_check("job.shared_style", isinstance(job.get("shared_style"), Mapping) and bool(job.get("shared_style")), "non-empty shared style rules", job.get("shared_style"), "Declare cross-figure typography and encoding rules."))
        checks.append(_check("job.cross_figure_rules", isinstance(job.get("cross_figure_rules"), list) and bool(job.get("cross_figure_rules")), "non-empty cross-figure comparison rules", job.get("cross_figure_rules"), "Declare relationships that must remain consistent across figures."))
        paths = _source_path_values(source) if isinstance(source, Mapping) else []
        checks.append(_check("job.source.manuscript_paths", bool(paths), "at least one file-backed source", [location for location, _value in paths], "A manuscript set needs hashable file-backed inputs."))
    return {"status": aggregate_status(checks).value, "checks": [check.as_dict() for check in checks]}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _update_digest_file(digest: Any, path: Path) -> None:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    _update_digest_file(digest, path)
    return digest.hexdigest()


def _canonicalize_paths_for_hash(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if key == "plot_script":
                continue
            if key == "statistics_file":
                result[key] = "[statistics-file]"
            elif _path_key(str(key)):
                if isinstance(child, list):
                    result[key] = [f"[path-{index}]" for index, _item in enumerate(child)]
                else:
                    result[key] = "[path]"
            else:
                result[key] = _canonicalize_paths_for_hash(child)
        return result
    if isinstance(value, list):
        return [_canonicalize_paths_for_hash(item) for item in value]
    return value


def _hash_inputs(job: Mapping[str, Any], job_path: Path, plot_script: Optional[Path]) -> str:
    digest = hashlib.sha256()
    canonical_job = _canonicalize_paths_for_hash(job)
    digest.update(json.dumps(canonical_job, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    _update_digest_file(digest, CONFIG_PATH)
    for runtime_script in sorted(Path(__file__).resolve().parent.glob("*.py")):
        if not runtime_script.name.startswith("test_"):
            _update_digest_file(digest, runtime_script)
    if plot_script:
        _update_digest_file(digest, plot_script)
    source = job.get("source", {})
    candidates = _source_path_values(source) if isinstance(source, Mapping) else []
    for location, candidate in sorted(candidates, key=lambda item: item[0]):
        resolved = (job_path.parent / candidate).resolve()
        digest.update(location.encode())
        if resolved.is_file():
            _update_digest_file(digest, resolved)
        else:
            digest.update(b"missing")
    statistics_path = job.get("statistics_file")
    if statistics_path:
        resolved = (job_path.parent / statistics_path).resolve()
        if resolved.is_file():
            _update_digest_file(digest, resolved)
    for package in ("matplotlib", "numpy", "Pillow", "pypdf", "PyMuPDF"):
        try:
            digest.update(f"{package}={importlib.metadata.version(package)}".encode())
        except importlib.metadata.PackageNotFoundError:
            digest.update(f"{package}=missing".encode())
    font = job.get("target", {}).get("font", {})
    if isinstance(font, Mapping):
        try:
            if font.get("path"):
                font_file = (job_path.parent / font["path"]).resolve()
            else:
                from matplotlib import font_manager

                font_file = Path(font_manager.findfont(font.get("family"), fallback_to_default=False))
            _update_digest_file(digest, font_file)
        except Exception as exc:
            digest.update(f"font-unresolved={exc}".encode())
    return digest.hexdigest()


def _load_builder(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"scientific_figure_{uuid.uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load plot script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _visual_review(path: Optional[Path], expected_input_hash: str) -> Dict[str, Any]:
    if path is None:
        return {"status": CheckStatus.NOT_CHECKED.value, "checks": [], "message": "No visual-review record supplied."}
    payload = json.loads(path.read_text(encoding="utf-8"))
    checks = payload.get("checks")
    valid = (
        payload.get("schema_version") == 1
        and _nonempty(payload.get("reviewer"))
        and payload.get("input_hash") == expected_input_hash
        and isinstance(checks, Mapping)
        and VISUAL_CHECKS <= set(checks)
        and all(checks[name] == CheckStatus.PASS.value for name in VISUAL_CHECKS)
    )
    return {
        "status": CheckStatus.PASS.value if valid else CheckStatus.FAIL.value,
        "reviewer": payload.get("reviewer"),
        "expected_input_hash": expected_input_hash,
        "observed_input_hash": payload.get("input_hash"),
        "checks": checks,
        "required_checks": sorted(VISUAL_CHECKS),
    }


def _accessibility_previews(path: Path) -> List[Path]:
    import numpy as np
    from PIL import Image, ImageOps

    with Image.open(path) as source:
        rgb = source.convert("RGB")
    outputs: List[Path] = []
    grayscale = path.with_name(f"{path.stem}.grayscale.png")
    ImageOps.grayscale(rgb).save(grayscale)
    outputs.append(grayscale)
    array = np.asarray(rgb, dtype=float) / 255.0
    matrices = {
        "protanopia": np.array([[0.567, 0.433, 0.0], [0.558, 0.442, 0.0], [0.0, 0.242, 0.758]]),
        "deuteranopia": np.array([[0.625, 0.375, 0.0], [0.700, 0.300, 0.0], [0.0, 0.300, 0.700]]),
        "tritanopia": np.array([[0.950, 0.050, 0.0], [0.0, 0.433, 0.567], [0.0, 0.475, 0.525]]),
    }
    for name, matrix in matrices.items():
        simulated = np.clip(array @ matrix.T, 0, 1)
        output = path.with_name(f"{path.stem}.{name}.png")
        Image.fromarray((simulated * 255).astype("uint8"), "RGB").save(output)
        outputs.append(output)
    return outputs


def _render_audit_preview(artifact: Path, output: Path) -> Path:
    suffix = artifact.suffix.lower()
    if suffix in {".png", ".tif", ".tiff"}:
        from PIL import Image

        with Image.open(artifact) as source:
            image = source.convert("RGB")
            dpi = source.info.get("dpi")
        if dpi and min(dpi) > 0:
            target_size = (
                max(1, round(image.width / float(dpi[0]) * 150)),
                max(1, round(image.height / float(dpi[1]) * 150)),
            )
            if target_size != image.size:
                image = image.resize(target_size, Image.Resampling.LANCZOS)
        image.save(output, format="PNG", dpi=(150, 150))
        return output
    import fitz

    document = fitz.open(artifact)
    try:
        if document.page_count != 1:
            raise ValueError("Audit preview requires a single-page artifact")
        pixmap = document[0].get_pixmap(dpi=150, alpha=False)
        pixmap.save(output)
    finally:
        document.close()
    return output


def _contact_sheet(paths: Sequence[Path], output: Path) -> Optional[Path]:
    if len(paths) < 2:
        return None
    from PIL import Image, ImageDraw

    cards = []
    for path in paths:
        with Image.open(path) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((600, 400))
            cards.append((path.stem, thumb.copy()))
    width = max(card.width for _, card in cards)
    height = sum(card.height + 40 for _, card in cards)
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, card in cards:
        draw.text((8, y + 4), label, fill="black")
        sheet.paste(card, (0, y + 32))
        y += card.height + 40
    sheet.save(output, dpi=(150, 150))
    return output


def _statistics_report(job: Mapping[str, Any], job_path: Path) -> Tuple[Dict[str, Any], Optional[Path]]:
    requested = bool(job.get("analysis", {}).get("annotations_requested"))
    source = job.get("statistics_file")
    if source:
        path = (job_path.parent / source).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("annotations_requested") != requested:
            payload = dict(payload)
            payload["annotations_requested"] = requested
        return validate_statistics(payload), path
    return validate_statistics({"schema_version": 1, "annotations_requested": requested, "comparisons": []}), None


def _prepare_bundle(output: Path) -> Dict[str, Path]:
    paths = {name: output / name for name in ("final", "preview", "source", "captions", "stats", "qa")}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _replace_path_values(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if _path_key(str(key)):
                if isinstance(child, str):
                    result[key] = replacements.get(child, "[not packaged; hash in manifest]")
                elif isinstance(child, list):
                    result[key] = [
                        replacements.get(item, "[not packaged; hash in manifest]")
                        if isinstance(item, str)
                        else item
                        for item in child
                    ]
                else:
                    result[key] = child
            else:
                result[key] = _replace_path_values(child, replacements)
        return result
    if isinstance(value, list):
        return [_replace_path_values(item, replacements) for item in value]
    return value


def _prepare_public_job(
    job: Mapping[str, Any],
    job_path: Path,
    bundle: Mapping[str, Path],
    statistics_path: Optional[Path],
    plot_script: Optional[Path],
    *,
    allow_data_package: bool,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], bool]:
    if job["source"].get("sensitivity") == "sensitive":
        entries: List[Dict[str, Any]] = []
        for index, (_location, value) in enumerate(_source_path_values(job["source"]), start=1):
            resolved = (job_path.parent / value).resolve()
            entry: Dict[str, Any] = {"source_id": f"source_{index:02d}", "packaged": False}
            if resolved.is_file():
                entry.update({"sha256": _sha256_file(resolved), "size_bytes": resolved.stat().st_size})
            else:
                entry["status"] = "missing"
            entries.append(entry)
        return None, entries, False
    source_paths = _source_path_values(job["source"])
    package_data = bool(
        allow_data_package
        and job["source"].get("package_data")
        and job["source"].get("package_data_authorized")
    )
    replacements: Dict[str, str] = {}
    source_entries: List[Dict[str, Any]] = []
    data_dir = bundle["source"] / "data"
    if package_data:
        data_dir.mkdir(parents=True, exist_ok=True)
    unique_paths = sorted({value for _location, value in source_paths})
    all_packaged = bool(unique_paths)
    for index, value in enumerate(unique_paths, start=1):
        resolved = (job_path.parent / value).resolve()
        entry: Dict[str, Any] = {"source_id": f"source_{index:02d}", "packaged": False}
        if resolved.is_file():
            entry["sha256"] = _sha256_file(resolved)
            entry["size_bytes"] = resolved.stat().st_size
            if package_data:
                suffix = resolved.suffix.lower() if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", resolved.suffix) else ""
                packaged_name = f"input_{index:02d}{suffix}"
                destination = data_dir / packaged_name
                shutil.copy2(resolved, destination)
                replacements[value] = f"data/{packaged_name}"
                entry["packaged"] = True
                entry["package_path"] = f"source/data/{packaged_name}"
            else:
                replacements[value] = f"[not packaged: source_{index:02d}]"
                all_packaged = False
        else:
            entry["status"] = "missing"
            replacements[value] = f"[missing: source_{index:02d}]"
            all_packaged = False
        source_entries.append(entry)
    public_job = json.loads(json.dumps(job))
    public_job["source"] = _replace_path_values(public_job["source"], replacements)
    if statistics_path:
        public_job["statistics_file"] = "../stats/statistics.json"
    if plot_script:
        public_job["plot_script"] = plot_script.name
    return public_job, source_entries, all_packaged


def run_pipeline(
    *,
    job_path: Path,
    output_dir: Path,
    stage: str,
    plot_script: Optional[Path] = None,
    visual_review_path: Optional[Path] = None,
    changed_only: bool = False,
) -> Dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {sorted(STAGES)}")
    job_path = job_path.resolve()
    if plot_script is not None:
        plot_script = plot_script.resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    bundle = _prepare_bundle(output_dir.resolve())
    contract = validate_job(
        job,
        execution_paths=[
            str(job_path),
            str(plot_script) if plot_script else "",
            str(output_dir.resolve()),
            str(visual_review_path.resolve()) if visual_review_path else "",
        ],
    )
    _atomic_json(bundle["qa"] / "job_validation.json", contract)
    if contract["status"] != CheckStatus.PASS.value:
        if job.get("source", {}).get("sensitivity") == "sensitive":
            _clear_managed_mpl_cache()
        return {"status": CheckStatus.FAIL.value, "verification_level": "draft", "contract": contract}

    target = job["target"]
    profile = get_profile(target["profile"])
    runtime_checks: List[CheckResult] = []
    for location, value in _source_path_values(job["source"]):
        resolved = (job_path.parent / value).resolve()
        runtime_checks.append(_check(
            f"source.file.{len(runtime_checks)}",
            resolved.is_file(),
            "existing regular source file",
            {"location": location, "exists": resolved.is_file()},
            "Every declared source path must resolve to a file before plotting.",
        ))
    if job.get("statistics_file"):
        statistics_candidate = (job_path.parent / job["statistics_file"]).resolve()
        runtime_checks.append(_check(
            "source.statistics_file",
            statistics_candidate.is_file(),
            "existing structured statistics file",
            {"exists": statistics_candidate.is_file()},
            "Declared statistical evidence must exist before plotting.",
        ))
    if job["mode"] != "visual_audit":
        runtime_checks.append(_check(
            "source.plot_script",
            plot_script is not None and plot_script.is_file(),
            "existing plotting script",
            {"provided": plot_script is not None, "exists": bool(plot_script and plot_script.is_file())},
            "A plotting script is required outside visual_audit mode.",
        ))
    source_runtime = {
        "status": aggregate_status(runtime_checks).value,
        "checks": [check.as_dict() for check in runtime_checks],
    }
    _atomic_json(bundle["qa"] / "source_preflight.json", source_runtime)
    if source_runtime["status"] != CheckStatus.PASS.value:
        if job["source"].get("sensitivity") == "sensitive":
            _clear_managed_mpl_cache()
        return {
            "status": CheckStatus.FAIL.value,
            "verification_level": "draft",
            "contract": contract,
            "source_preflight": source_runtime,
        }
    labels = target.get("labels", [])
    font = target["font"]
    formats = target.get("formats") or [profile["figure_types"][target["figure_type"]]["formats"][0]]
    tools = ("pdffonts", "pdfimages") if stage == "final" and "pdf" in formats else ()
    preflight = run_preflight(
        family=font.get("family"),
        font_path=(job_path.parent / font["path"]).resolve() if font.get("path") else None,
        texts=labels,
        tools=tools,
    )
    _atomic_json(bundle["qa"] / "preflight.json", preflight)
    stats, statistics_path = _statistics_report(job, job_path)
    _atomic_json(bundle["qa"] / "statistics_validation.json", stats)
    if statistics_path and job["source"].get("sensitivity") != "sensitive":
        shutil.copy2(statistics_path, bundle["stats"] / "statistics.json")

    input_hash = _hash_inputs(job, job_path, plot_script)
    cache_path = bundle["qa"] / "pipeline_cache.json"
    expected_outputs: List[Path] = []
    if changed_only and stage == "preview" and cache_path.is_file() and job["source"].get("sensitivity") != "sensitive":
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        expected_outputs = [Path(value) for value in cached.get("artifacts", [])]
        if cached.get("input_hash") == input_hash and all(path.is_file() for path in expected_outputs):
            return {
                "status": CheckStatus.PASS.value,
                "verification_level": "draft",
                "cached": True,
                "artifacts": [str(path) for path in expected_outputs],
            }

    visual = _visual_review(visual_review_path.resolve() if visual_review_path else None, input_hash)
    mode = job["mode"]
    export_reports: List[Dict[str, Any]] = []
    preview_paths: List[Path] = []
    audited_artifacts: List[Dict[str, Any]] = []
    if mode == "visual_audit":
        artifact_path = (job_path.parent / job["source"]["figure_path"]).resolve()
        audit_preview_path = bundle["preview"] / f"{job['delivery']['base_name']}.png"
        if stage == "preview":
            try:
                rendered_preview = _render_audit_preview(artifact_path, audit_preview_path)
                expected_outputs.extend([rendered_preview] + _accessibility_previews(rendered_preview))
                runtime_checks.append(_check(
                    "audit.preview",
                    True,
                    "150 PPI preview plus accessibility variants",
                    str(rendered_preview),
                    "Audit preview rendered from the exact input artifact.",
                ))
            except Exception as exc:
                runtime_checks.append(CheckResult(
                    "audit.preview",
                    CheckStatus.NOT_CHECKED,
                    expected="150 PPI preview plus accessibility variants",
                    observed=type(exc).__name__,
                    message="The audit artifact could not be rendered for visual inspection.",
                    validator="Pillow/PyMuPDF",
                ))
        else:
            runtime_checks.append(_check(
                "audit.preview",
                audit_preview_path.is_file(),
                "preview from the same bundle before final audit",
                audit_preview_path.is_file(),
                "Final audit requires the preview stage in the same bundle.",
            ))
        artifact = verify_artifact(
            artifact_path,
            profile=profile,
            figure_type=target["figure_type"],
            column=target.get("column"),
            artifact_constraints=target.get("requirements"),
        )
        profile_checks = verify_profile(profile)
        report = ExportReport(profile["id"], _sha256_file(CONFIG_PATH), [artifact], profile_checks)
        export_reports.append(report.as_dict())
        audited_artifacts.append({
            "artifact_id": "audited_01",
            "artifact_role": "input_under_audit",
            "format": (
                "tiff"
                if artifact_path.suffix.lower() in {".tif", ".tiff"}
                else artifact_path.suffix.lower().lstrip(".")
            ),
            "sha256": _sha256_file(artifact_path),
            "size_bytes": artifact_path.stat().st_size,
        })
        _atomic_json(bundle["qa"] / "runtime_figure_checks.json", {
            "status": aggregate_status(runtime_checks).value,
            "checks": [check.as_dict() for check in runtime_checks],
        })
    else:
        if plot_script is None:
            raise ValueError("--plot-script is required outside visual_audit mode")
        builder = _load_builder(plot_script)
        font_family = font.get("family")
        font_path = None
        if font.get("path"):
            from matplotlib import font_manager

            font_path = (job_path.parent / font["path"]).resolve()
            font_manager.fontManager.addfont(str(font_path))
            font_family = font_manager.FontProperties(fname=str(font_path)).get_name()
        overrides = {"font.family": font_family} if font_family else {}
        with publication_style(profile["style"], rc_overrides=overrides):
            if mode == "manuscript_set":
                if not hasattr(builder, "build_figures"):
                    raise AttributeError("Manuscript-set scripts must define build_figures(job)")
                built = builder.build_figures(job)
                specs = [(item["id"], built[item["id"]]) for item in job["figures"]]
            else:
                if not hasattr(builder, "build_figure"):
                    raise AttributeError("Plot scripts must define build_figure(job)")
                specs = [(job["delivery"]["base_name"], builder.build_figure(job))]

        with publication_style(profile["style"], rc_overrides=overrides):
            actual_texts = sorted({text for _name, fig in specs for text in _semantic_figure_texts(fig)})
        declared_texts = set(labels)
        undeclared = sorted(set(actual_texts) - declared_texts)
        runtime_checks.append(_check(
            "figure.text_contract",
            not undeclared,
            "every semantic Figure string declared in target.labels",
            undeclared,
            "Undeclared text can bypass glyph and privacy checks.",
        ))
        runtime_checks.extend(inspect_font(
            family=font_family if font_path is None else None,
            font_path=font_path,
            texts=actual_texts,
        ))
        if job["source"].get("sensitivity") == "sensitive":
            text_hits = _identifier_hits(actual_texts)
            runtime_checks.append(_check(
                "figure.identifier_value_scan",
                not text_hits,
                "no high-confidence identifiers in rendered text",
                text_hits,
                "Potential identifiers were found in Figure text.",
            ))
        post_build_hash = _hash_inputs(job, job_path, plot_script)
        runtime_checks.append(_check(
            "integrity.source_unchanged",
            post_build_hash == input_hash,
            input_hash,
            post_build_hash,
            "Plot construction must not modify any declared source, script, font, or rule file.",
        ))
        runtime_figure = {
            "status": aggregate_status(runtime_checks).value,
            "actual_texts": actual_texts if job["source"].get("sensitivity") != "sensitive" else "[withheld]",
            "checks": [check.as_dict() for check in runtime_checks],
        }
        _atomic_json(bundle["qa"] / "runtime_figure_checks.json", runtime_figure)

        if runtime_figure["status"] == CheckStatus.PASS.value:
            for name, fig in specs:
                with publication_style(profile["style"], rc_overrides=overrides):
                    if stage == "preview":
                        report = export_publication_figure(
                            fig,
                            bundle["preview"] / name,
                            ("png",),
                            150,
                            overwrite=True,
                        )
                        preview = report.paths[0]
                        preview_paths.append(preview)
                        expected_outputs.extend([preview] + _accessibility_previews(preview))
                    else:
                        use_profile = None if profile["verification"]["state"] == "draft_only" else profile["id"]
                        report = export_publication_figure(
                            fig,
                            bundle["final"] / name,
                            formats,
                            profile["figure_types"][target["figure_type"]]["raster_dpi"],
                            profile_name=use_profile,
                            figure_type=target["figure_type"],
                            column=target.get("column"),
                            create_dirs=True,
                            overwrite=True,
                            strict=False,
                            artifact_constraints=target.get("requirements"),
                            style_overrides=overrides,
                        )
                        if report.artifacts_committed is True:
                            expected_outputs.extend([path for path in report.paths if path.is_file()])
                export_reports.append(report.as_dict())
        for _name, fig in specs:
            try:
                import matplotlib.pyplot as plt

                plt.close(fig)
            except Exception:
                pass
        contact = _contact_sheet(preview_paths, bundle["preview"] / "contact_sheet.png")
        if contact:
            expected_outputs.append(contact)
        if job["source"].get("sensitivity") != "sensitive":
            shutil.copy2(plot_script, bundle["source"] / plot_script.name)

    if mode == "manuscript_set":
        for item in job["figures"]:
            (bundle["captions"] / f"{item['id']}.md").write_text(item["caption"].strip() + "\n", encoding="utf-8")
    else:
        caption = job.get("caption")
        if _nonempty(caption):
            (bundle["captions"] / f"{job['delivery']['base_name']}.md").write_text(caption.strip() + "\n", encoding="utf-8")

    public_job, source_entries, source_data_packaged = _prepare_public_job(
        job,
        job_path,
        bundle,
        statistics_path,
        plot_script,
        allow_data_package=aggregate_status(runtime_checks) == CheckStatus.PASS,
    )
    if public_job is not None:
        _atomic_json(bundle["source"] / "job.public.json", public_job)
        shutil.copy2(CONFIG_PATH, bundle["source"] / "visual_profiles.snapshot.json")
        requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
        shutil.copy2(requirements_path, bundle["source"] / "requirements.txt")
        plot_option = f" --plot-script {plot_script.name}" if plot_script else ""
        (bundle["source"] / "README.md").write_text(
            "Re-run with the installed skill:\n\n"
            "    python <skill>/scripts/figure_pipeline.py --job job.public.json"
            f"{plot_option} --stage preview --output ../rerun\n\n"
            "A package is input-complete only when manifest.json reports "
            "reproducibility_level=self_contained_inputs.\n",
            encoding="utf-8",
        )
    else:
        (bundle["source"] / "RESTRICTED.txt").write_text(
            "Sensitive source metadata and plotting code were intentionally not copied.\n",
            encoding="utf-8",
        )

    core_statuses = [contract["status"], source_runtime["status"], preflight["status"], stats["status"]]
    core_statuses.append(aggregate_status(runtime_checks).value)
    core_statuses += [report["overall_status"] for report in export_reports]
    if stage == "final" or visual_review_path is not None:
        core_statuses.append(visual["status"])
    if CheckStatus.FAIL.value in core_statuses:
        overall = CheckStatus.FAIL.value
    elif CheckStatus.NOT_CHECKED.value in core_statuses:
        overall = CheckStatus.NOT_CHECKED.value
    else:
        overall = CheckStatus.PASS.value
    verification_level = "draft"
    if visual["status"] == CheckStatus.PASS.value and overall == CheckStatus.PASS.value:
        verification_level = "visually_checked"
        profile_ready = all(check.status == CheckStatus.PASS for check in verify_profile(profile))
        if stage == "final" and target["submission_stage"] == "final" and profile_ready:
            verification_level = "journal_verified"

    qa = {
        "schema_version": 1,
        "status": overall,
        "verification_level": verification_level,
        "stage": stage,
        "profile_id": profile["id"],
        "input_hash": input_hash,
        "contract": contract,
        "source_preflight": source_runtime,
        "preflight": preflight,
        "statistics": stats,
        "visual_review": visual,
        "exports": export_reports,
        "artifacts": [str(path) for path in expected_outputs],
        "audited_artifacts": audited_artifacts,
    }
    _atomic_json(bundle["qa"] / "figure_qa.json", qa)
    manifest = {
        "schema_version": 1,
        "profile_id": profile["id"],
        "profile_sha256": _sha256_file(CONFIG_PATH),
        "input_hash": input_hash,
        "stage": stage,
        "verification_level": verification_level,
        "artifacts": [
            {
                "path": str(path.relative_to(output_dir.resolve())),
                "sha256": _sha256_file(path),
            }
            for path in expected_outputs
            if path.is_file()
        ],
        "audited_artifacts": audited_artifacts,
        "source_inputs": source_entries,
        "source_data_packaged": source_data_packaged,
        "reproducibility_level": "self_contained_inputs" if source_data_packaged else "code_and_hashes_only",
    }
    _atomic_json(output_dir.resolve() / "manifest.json", manifest)
    if job["source"].get("sensitivity") == "sensitive":
        cache_path.unlink(missing_ok=True)
        _clear_managed_mpl_cache()
    else:
        _atomic_json(cache_path, {"input_hash": input_hash, "artifacts": [str(path) for path in expected_outputs]})
    return qa


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scientific-figure preview/final pipeline")
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    parser.add_argument("--plot-script", type=Path)
    parser.add_argument("--visual-review", type=Path)
    parser.add_argument("--changed-only", action="store_true")
    args = parser.parse_args(argv)
    result = run_pipeline(
        job_path=args.job,
        output_dir=args.output,
        stage=args.stage,
        plot_script=args.plot_script,
        visual_review_path=args.visual_review,
        changed_only=args.changed_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == CheckStatus.PASS.value else 2


if __name__ == "__main__":
    raise SystemExit(main())
