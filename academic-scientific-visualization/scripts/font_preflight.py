#!/usr/bin/env python3
"""Environment, dependency, external-tool, and glyph coverage preflight."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from .figure_export import CheckResult, CheckStatus, aggregate_status
except ImportError:
    from figure_export import CheckResult, CheckStatus, aggregate_status


REQUIRED_PACKAGES = ("matplotlib", "numpy", "Pillow", "pypdf", "PyMuPDF")
REQUIRED_TOOLS = ("pdffonts", "pdfimages")


def _result(
    check_id: str,
    status: CheckStatus,
    expected: Any,
    observed: Any,
    message: str,
    validator: str,
    required: bool = True,
) -> CheckResult:
    return CheckResult(
        check_id,
        status,
        required=required,
        expected=expected,
        observed=observed,
        message=message,
        validator=validator,
    )


def _package_checks() -> List[CheckResult]:
    checks: List[CheckResult] = []
    for package in REQUIRED_PACKAGES:
        try:
            version = importlib.metadata.version(package)
            status = CheckStatus.PASS
        except importlib.metadata.PackageNotFoundError:
            version = None
            status = CheckStatus.FAIL
        checks.append(_result(
            f"dependency.{package.lower()}",
            status,
            "installed",
            version,
            "Install dependencies from requirements.txt only with user authorization.",
            "importlib.metadata",
        ))
    return checks


def _matplotlib_environment_checks() -> List[CheckResult]:
    backend = os.environ.get("MPLBACKEND")
    config = os.environ.get("MPLCONFIGDIR")
    checks = [
        _result(
            "environment.backend",
            CheckStatus.PASS if backend and backend.lower() == "agg" else CheckStatus.NOT_CHECKED,
            "MPLBACKEND=Agg for headless execution",
            backend,
            "Set MPLBACKEND=Agg before importing Matplotlib in automated runs.",
            "environment",
        )
    ]
    writable = False
    observed: Any = config
    if config:
        path = Path(config)
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, prefix="write-check-", delete=True):
                pass
            writable = True
            observed = str(path.resolve())
        except OSError as exc:
            observed = f"{config}: {exc}"
    checks.append(_result(
        "environment.mplconfigdir",
        CheckStatus.PASS if writable else CheckStatus.FAIL,
        "explicit writable MPLCONFIGDIR",
        observed,
        "Use a task-local temporary cache; do not rely on a read-only home directory.",
        "filesystem write probe",
    ))
    return checks


def _tool_checks(tools: Sequence[str]) -> List[CheckResult]:
    return [
        _result(
            f"tool.{tool}",
            CheckStatus.PASS if shutil.which(tool) else CheckStatus.NOT_CHECKED,
            "available on PATH",
            shutil.which(tool),
            f"{tool} is required for the corresponding final-artifact check.",
            "shutil.which",
        )
        for tool in tools
    ]


def inspect_font(
    *,
    family: Optional[str] = None,
    font_path: Optional[Path] = None,
    texts: Sequence[str] = (),
) -> List[CheckResult]:
    checks: List[CheckResult] = []
    resolved: Optional[Path] = None
    try:
        if font_path:
            resolved = Path(font_path)
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
        elif family:
            from matplotlib import font_manager

            resolved = Path(font_manager.findfont(family, fallback_to_default=False))
        else:
            raise ValueError("family or font_path is required")
        checks.append(_result(
            "font.resolve",
            CheckStatus.PASS,
            family or str(font_path),
            str(resolved),
            "Font resolved without silent fallback.",
            "matplotlib.font_manager",
        ))
    except Exception as exc:
        checks.append(_result(
            "font.resolve",
            CheckStatus.FAIL,
            family or str(font_path),
            str(exc),
            "Required font could not be resolved.",
            "matplotlib.font_manager",
        ))
        return checks

    characters = sorted({character for text in texts for character in text if not character.isspace()})
    if not characters:
        checks.append(_result(
            "font.glyph_coverage",
            CheckStatus.NOT_CHECKED,
            "all final labels supplied to preflight",
            "no text supplied",
            "Pass every title, label, legend entry, and annotation to verify glyphs.",
            "matplotlib.ft2font",
            required=False,
        ))
        return checks
    from matplotlib.ft2font import FT2Font

    charmap = FT2Font(str(resolved)).get_charmap()
    missing = [character for character in characters if ord(character) not in charmap]
    checks.append(_result(
        "font.glyph_coverage",
        CheckStatus.PASS if not missing else CheckStatus.FAIL,
        "all supplied characters covered",
        {"missing": missing, "font": str(resolved)},
        "Missing glyphs are a final-output failure; choose a font with actual CJK coverage.",
        "matplotlib.ft2font",
    ))
    return checks


def run_preflight(
    *,
    family: Optional[str] = None,
    font_path: Optional[Path] = None,
    texts: Sequence[str] = (),
    tools: Sequence[str] = REQUIRED_TOOLS,
) -> Dict[str, Any]:
    checks = _package_checks() + _matplotlib_environment_checks() + _tool_checks(tools)
    if family or font_path:
        checks += inspect_font(family=family, font_path=font_path, texts=texts)
    else:
        checks.append(_result(
            "font.resolve",
            CheckStatus.NOT_CHECKED,
            "explicit family or font path",
            None,
            "Final output must preflight the exact font and text.",
            "font_preflight",
        ))
    return {
        "status": aggregate_status(checks).value,
        "checks": [check.as_dict() for check in checks],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight a scientific-figure runtime")
    parser.add_argument("--font-family")
    parser.add_argument("--font-path", type=Path)
    parser.add_argument("--text", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_preflight(
        family=args.font_family,
        font_path=args.font_path,
        texts=args.text,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        if not args.output.parent.exists():
            raise FileNotFoundError(args.output.parent)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["status"] == CheckStatus.PASS.value else 2


if __name__ == "__main__":
    raise SystemExit(main())
