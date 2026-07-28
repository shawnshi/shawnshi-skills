"""Report style signals in a solution draft without turning heuristics into blockers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


BUZZWORD_MAP = {
    "赋能": ["支撑", "说明具体能力"],
    "抓手": ["切入点", "治理工具"],
    "闭环": ["说明起点、终点和责任人"],
    "生态位": ["战略定位", "功能边界"],
    "打法": ["策略组合", "实施路径"],
    "颗粒度": ["精细度", "层级"],
    "底层逻辑": ["核心机制", "基本原理"],
    "拉通": ["说明需贯通的数据或流程"],
    "打通": ["说明需建设的接口或集成"],
    "沉淀": ["归档", "结构化存储"],
    "落地": ["实施", "部署", "交付"],
    "全链路": ["全流程", "端到端"],
    "降本增效": ["分别说明成本与效率指标"],
    "新质生产力": ["说明具体技术或业务能力"],
}

VAGUE_PATTERNS = [
    (
        r"(?:明显|显著|大幅|极大地?|有效地?)\s*(?:提升|提高|改善|优化|增强|降低|减少)",
        "补充测量口径，或明确标记为待测算。",
    ),
    (r"(?:一定程度上|在某种程度上)", "说明具体条件，或删除无法验证的限定词。"),
]


def audit(content: str, bold_hint: int) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    bold_matches = re.findall(r"\*\*[^*\n]+\*\*", content)
    if len(bold_matches) > bold_hint:
        warnings.append(
            {
                "code": "W_BOLD_DENSITY",
                "message": f"加粗标记共 {len(bold_matches)} 处，可能影响阅读层级。",
                "instances": bold_matches[:10],
            }
        )

    for word, replacements in BUZZWORD_MAP.items():
        count = content.count(word)
        if count:
            warnings.append(
                {
                    "code": "W_BUZZWORD",
                    "term": word,
                    "count": count,
                    "message": "该词可能过于抽象；请结合上下文人工判断。",
                    "alternatives": replacements,
                }
            )

    for pattern, suggestion in VAGUE_PATTERNS:
        matches = [match.group(0) for match in re.finditer(pattern, content)]
        if matches:
            warnings.append(
                {
                    "code": "W_VAGUE_QUANTIFICATION",
                    "count": len(matches),
                    "instances": matches[:10],
                    "message": suggestion,
                }
            )

    return {
        "schema_version": 1,
        "status": "warning" if warnings else "pass",
        "errors": [],
        "warnings": warnings,
        "summary": {
            "warning_count": len(warnings),
            "bold_count": len(bold_matches),
            "bold_hint": bold_hint,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_md", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional report path. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--bold-hint",
        type=int,
        default=20,
        help="Soft review threshold; it never changes the process exit code.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        content = args.file_md.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        report = {
            "schema_version": 1,
            "target_file": str(args.file_md),
            "status": "fail",
            "errors": [{"code": "E_FILE_READ", "message": str(exc)}],
            "warnings": [],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = audit(content, args.bold_hint)
    report["target_file"] = str(args.file_md)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
