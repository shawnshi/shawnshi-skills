import argparse
import json
import re
import sys
from pathlib import Path

MODE_MIN_WORDS = {
    "brief": 1200,
    "deep-dive": 5000,
    "board-memo": 800,
}


def count_words(text: str) -> int:
    cjk_count = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_word_count = len(re.findall(r'\b[a-zA-Z0-9]+\b', text))
    return cjk_count + en_word_count


def load_blackboard(path: Path | None):
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def contains_any(text: str, options: list[str]) -> bool:
    return any(option.lower() in text.lower() for option in options)


def evaluate(text: str, mode: str, blackboard: dict) -> dict:
    judgment = str(blackboard.get("logic_mesh", {}).get("core_judgment", "")).strip()
    second_hops = blackboard.get("logic_mesh", {}).get("second_hop_inferences", []) or []
    action_levers = blackboard.get("decisions", {}).get("action_levers", []) or []
    residual_risks = blackboard.get("decisions", {}).get("residual_risks", []) or []
    pessimistic_roi = blackboard.get("decisions", {}).get("pessimistic_roi", {}) or {}

    checks = {
        "min_words": count_words(text) >= MODE_MIN_WORDS[mode],
        "center_judgment": bool(judgment) and contains_any(text, [judgment, "中心判断", "Core Judgment"]),
        "pessimistic_roi": bool(pessimistic_roi) and contains_any(text, ["悲观 ROI", "Pessimistic ROI", "下行情景"]),
        "second_hop_inference": bool(second_hops) and (contains_any(text, ["二跳推理", "second-hop"]) or any(str(item).lower() in text.lower() for item in second_hops)),
        "action_levers": bool(action_levers) and contains_any(text, ["行动杠杆", "Action Levers", "动作建议"]),
        "residual_risk": bool(residual_risks) and contains_any(text, ["残酷风险", "Residual Risk", "Residual Risks", "主要风险"]),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "status": "pass" if not missing else "fail",
        "checks": checks,
        "missing": missing,
        "word_count": count_words(text),
        "mode": mode,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate result-oriented strategy gates")
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["brief", "deep-dive", "board-memo"])
    parser.add_argument("--blackboard", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    text = args.path.read_text(encoding="utf-8")
    report = evaluate(text, args.mode, load_blackboard(args.blackboard))
    report["path"] = str(args.path.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and report["status"] != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()
