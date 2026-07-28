import argparse
import json
import re
import sys
from pathlib import Path

from blackboard import validate_state


MODE_GUIDE_WORDS = {
    "brief": 600,
    "deep-dive": 1200,
    "board-memo": 350,
}

PLACEHOLDER_PATTERNS = [
    re.compile(r"\[(?:待填写|TODO|TBD|URL|来源|金额|日期)[^\]]*\]", re.IGNORECASE),
    re.compile(r"https?://example\.(?:com|org)(?:/|\b)", re.IGNORECASE),
]

QUANTITATIVE_CLAIM_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*%|[¥￥$]\s*\d|人民币\s*\d|"
    r"\d+(?:\.\d+)?\s*(?:万元|亿元|万美元|人天|小时/年))"
)
PROVENANCE_HINT_RE = re.compile(
    r"(?:来源|假设|测算|口径|截至|地区|情景|source|assumption|as of|region)",
    re.IGNORECASE,
)


def count_words(text: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_word_count = len(re.findall(r"\b[a-zA-Z0-9]+\b", text))
    return cjk_count + en_word_count


def load_blackboard(path: Path | None) -> tuple[dict, list[str]]:
    if not path:
        return {}, []
    if not path.exists():
        return {}, [f"blackboard file not found: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, [f"cannot read blackboard JSON: {exc}"]
    if not isinstance(data, dict):
        return {}, ["blackboard root must be a JSON object"]
    return data, []


def contains_any(text: str, options: list[str]) -> bool:
    return any(option.lower() in text.lower() for option in options if option)


def find_placeholders(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in PLACEHOLDER_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(text))
    return sorted(set(hits))


def find_quantitative_claim_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if QUANTITATIVE_CLAIM_RE.search(line) and not PROVENANCE_HINT_RE.search(line):
            warnings.append(
                f"line {line_number}: quantitative claim may need source, date, region, unit, or assumption label"
            )
    return warnings


def evaluate(
    text: str,
    mode: str,
    blackboard: dict,
    blackboard_errors: list[str] | None = None,
) -> dict:
    errors = list(blackboard_errors or [])
    warnings: list[str] = []

    placeholders = find_placeholders(text)
    if placeholders:
        errors.append("unresolved placeholders: " + ", ".join(placeholders[:8]))

    if blackboard:
        state_report = validate_state(blackboard)
        errors.extend(state_report["errors"])
        warnings.extend(state_report["warnings"])

        judgment = str(
            blackboard.get("logic_mesh", {}).get("core_judgment", "")
        ).strip()
        action_levers = (
            blackboard.get("decisions", {}).get("action_levers", []) or []
        )
        residual_risks = (
            blackboard.get("decisions", {}).get("residual_risks", []) or []
        )
        if judgment and not contains_any(
            text, [judgment, "中心判断", "core judgment"]
        ):
            warnings.append("report may not state the blackboard core judgment")
        if action_levers and not contains_any(
            text, ["行动", "建议", "action", "recommendation"]
        ):
            warnings.append("report may omit recorded action options")
        if residual_risks and not contains_any(
            text, ["风险", "限制", "不确定", "risk", "limitation"]
        ):
            warnings.append("report may omit recorded residual risks")
    else:
        warnings.append("no blackboard supplied; acceptable for a small or direct task")

    word_count = count_words(text)
    if word_count < MODE_GUIDE_WORDS[mode]:
        warnings.append(
            f"report is shorter than the optional {mode} depth guide "
            f"({word_count} < {MODE_GUIDE_WORDS[mode]})"
        )

    warnings.extend(find_quantitative_claim_warnings(text))
    return {
        "status": "fail" if errors else ("pass_with_warnings" if warnings else "pass"),
        "errors": errors,
        "warnings": warnings,
        "word_count": word_count,
        "mode": mode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate deterministic report invariants and emit non-blocking "
            "quality warnings."
        )
    )
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument(
        "--mode", required=True, choices=["brief", "deep-dive", "board-memo"]
    )
    parser.add_argument("--blackboard", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero only for deterministic errors; warnings never block.",
    )
    args = parser.parse_args()

    try:
        text = args.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False))
        return 1

    blackboard, blackboard_errors = load_blackboard(args.blackboard)
    report = evaluate(text, args.mode, blackboard, blackboard_errors)
    report["path"] = str(args.path.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
