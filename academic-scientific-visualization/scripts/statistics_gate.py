#!/usr/bin/env python3
"""Validate statistical evidence before deriving figure annotations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

try:
    from .figure_export import CheckResult, CheckStatus, aggregate_status
except ImportError:
    from figure_export import CheckResult, CheckStatus, aggregate_status


FORBIDDEN_LITERAL_KEYS = {"marker", "stars", "significance", "p_label"}
STAR_THRESHOLDS = (
    (0.0001, "****"),
    (0.001, "***"),
    (0.01, "**"),
    (0.05, "*"),
)


def _pass_or_fail(
    check_id: str, condition: bool, expected: Any, observed: Any, message: str
) -> CheckResult:
    return CheckResult(
        check_id,
        CheckStatus.PASS if condition else CheckStatus.FAIL,
        expected=expected,
        observed=observed,
        message=message,
        validator="statistics_gate",
    )


def _finite_probability(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def validate_comparison(comparison: Mapping[str, Any], index: int = 0) -> List[CheckResult]:
    prefix = f"comparison[{index}]"
    checks: List[CheckResult] = []
    forbidden = sorted(FORBIDDEN_LITERAL_KEYS.intersection(comparison))
    checks.append(_pass_or_fail(
        f"{prefix}.no_literal_annotation",
        not forbidden,
        "no hand-authored star or p-value label",
        forbidden,
        "Annotations must be derived from validated numeric evidence.",
    ))
    required_text = ("comparison_id", "analysis_unit", "test", "source")
    for key in required_text:
        value = comparison.get(key)
        checks.append(_pass_or_fail(
            f"{prefix}.{key}",
            isinstance(value, str) and bool(value.strip()),
            "non-empty string",
            value,
            f"{key} is required for an auditable annotation.",
        ))
    groups = comparison.get("groups")
    checks.append(_pass_or_fail(
        f"{prefix}.groups",
        isinstance(groups, list)
        and len(groups) == 2
        and all(isinstance(group, str) and group.strip() for group in groups),
        "exactly two named groups",
        groups,
        "Each comparison must identify the two displayed groups.",
    ))
    p_value = comparison.get("p_value")
    checks.append(_pass_or_fail(
        f"{prefix}.p_value",
        _finite_probability(p_value),
        "finite number in [0, 1]",
        p_value,
        "Raw p-value is missing or invalid.",
    ))
    family = comparison.get("family")
    family_valid = (
        isinstance(family, Mapping)
        and isinstance(family.get("id"), str)
        and bool(family.get("id", "").strip())
        and isinstance(family.get("size"), int)
        and not isinstance(family.get("size"), bool)
        and family.get("size") >= 1
    )
    checks.append(_pass_or_fail(
        f"{prefix}.family",
        family_valid,
        {"id": "non-empty", "size": "integer >= 1"},
        family,
        "Multiplicity family must be declared even when its size is one.",
    ))
    family_size = family.get("size") if family_valid else None
    correction = comparison.get("correction")
    adjusted = comparison.get("adjusted_p_value")
    if family_size and family_size > 1:
        checks.append(_pass_or_fail(
            f"{prefix}.correction",
            isinstance(correction, str)
            and bool(correction.strip())
            and correction.strip().lower() not in {"none", "na", "n/a"},
            "named multiplicity method",
            correction,
            "Multiple comparisons require a declared correction method.",
        ))
        checks.append(_pass_or_fail(
            f"{prefix}.adjusted_p_value",
            _finite_probability(adjusted),
            "finite adjusted p-value in [0, 1]",
            adjusted,
            "Multiple comparisons require an adjusted p-value.",
        ))
    else:
        checks.append(_pass_or_fail(
            f"{prefix}.correction",
            isinstance(correction, str) and bool(correction.strip()),
            "named method or 'none'",
            correction,
            "Correction handling must be explicit.",
        ))
        if adjusted is not None:
            checks.append(_pass_or_fail(
                f"{prefix}.adjusted_p_value",
                _finite_probability(adjusted),
                "finite adjusted p-value in [0, 1]",
                adjusted,
                "Provided adjusted p-value is invalid.",
            ))
    effect = comparison.get("effect_size")
    effect_valid = (
        isinstance(effect, Mapping)
        and isinstance(effect.get("name"), str)
        and bool(effect.get("name", "").strip())
        and isinstance(effect.get("value"), (int, float))
        and not isinstance(effect.get("value"), bool)
        and math.isfinite(float(effect.get("value")))
    )
    checks.append(_pass_or_fail(
        f"{prefix}.effect_size",
        effect_valid,
        {"name": "non-empty", "value": "finite number"},
        effect,
        "Effect size is required; significance alone is not an effect estimate.",
    ))
    interval = comparison.get("confidence_interval")
    interval_valid = (
        isinstance(interval, Mapping)
        and isinstance(interval.get("level"), (int, float))
        and 0 < float(interval.get("level", 0)) < 1
        and isinstance(interval.get("lower"), (int, float))
        and isinstance(interval.get("upper"), (int, float))
        and math.isfinite(float(interval.get("lower", float("nan"))))
        and math.isfinite(float(interval.get("upper", float("nan"))))
        and float(interval.get("lower")) <= float(interval.get("upper"))
    )
    checks.append(_pass_or_fail(
        f"{prefix}.confidence_interval",
        interval_valid,
        {"level": "(0,1)", "lower": "finite", "upper": "finite and >= lower"},
        interval,
        "A confidence interval is required for the reported effect.",
    ))
    return checks


def validate_statistics(payload: Mapping[str, Any]) -> Dict[str, Any]:
    checks: List[CheckResult] = []
    checks.append(_pass_or_fail(
        "statistics.schema_version",
        payload.get("schema_version") == 1,
        1,
        payload.get("schema_version"),
        "Unsupported statistics evidence schema.",
    ))
    requested = payload.get("annotations_requested")
    checks.append(_pass_or_fail(
        "statistics.annotations_requested",
        isinstance(requested, bool),
        "boolean",
        requested,
        "Declare whether inferential annotations are requested.",
    ))
    comparisons = payload.get("comparisons")
    valid_list = isinstance(comparisons, list)
    checks.append(_pass_or_fail(
        "statistics.comparisons",
        valid_list and (not requested or len(comparisons) > 0),
        "list; non-empty when annotations are requested",
        type(comparisons).__name__,
        "Requested annotations require structured comparisons.",
    ))
    if valid_list:
        for index, comparison in enumerate(comparisons):
            if not isinstance(comparison, Mapping):
                checks.append(_pass_or_fail(
                    f"comparison[{index}]",
                    False,
                    "object",
                    type(comparison).__name__,
                    "Each comparison must be an object.",
                ))
            else:
                checks.extend(validate_comparison(comparison, index))
    return {
        "status": aggregate_status(checks).value,
        "checks": [check.as_dict() for check in checks],
    }


def _validated_p_value(comparison: Mapping[str, Any]) -> float:
    result = validate_comparison(comparison)
    if aggregate_status(result) != CheckStatus.PASS:
        failures = [check.check_id for check in result if check.status != CheckStatus.PASS]
        raise ValueError(f"Statistical evidence did not pass: {', '.join(failures)}")
    family_size = int(comparison["family"]["size"])
    if family_size > 1 or comparison.get("adjusted_p_value") is not None:
        return float(comparison["adjusted_p_value"])
    return float(comparison["p_value"])


def derive_significance_label(comparison: Mapping[str, Any], style: str = "exact") -> str:
    """Derive a label from validated evidence; literal labels are never accepted."""
    p_value = _validated_p_value(comparison)
    if style == "exact":
        return "p < 0.001" if p_value < 0.001 else f"p = {p_value:.3g}"
    if style == "stars":
        for threshold, label in STAR_THRESHOLDS:
            if p_value < threshold:
                return label
        return "ns"
    raise ValueError("style must be 'exact' or 'stars'")


def add_significance_annotation(
    ax: Any,
    x1: float,
    x2: float,
    y: float,
    comparison: Mapping[str, Any],
    *,
    style: str = "exact",
    height: float = 0.02,
    text_kwargs: Mapping[str, Any] | None = None,
) -> str:
    label = derive_significance_label(comparison, style)
    ax.plot([x1, x1, x2, x2], [y, y + height, y + height, y], color="black", linewidth=0.8)
    ax.text((x1 + x2) / 2, y + height, label, ha="center", va="bottom", **dict(text_kwargs or {}))
    return label


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate structured statistical evidence")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    result = validate_statistics(payload)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        if not args.output.parent.exists():
            raise FileNotFoundError(args.output.parent)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["status"] == CheckStatus.PASS.value else 2


if __name__ == "__main__":
    raise SystemExit(main())
