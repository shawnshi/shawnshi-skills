"""Audit a solution draft with deterministic errors and heuristic warnings."""

from __future__ import annotations

import argparse
import itertools
import json
import re
from pathlib import Path
from typing import Any


BASE_DIMENSIONS = {
    "现状与约束": ["痛点", "挑战", "现状", "约束", "信息缺口"],
    "迁移与验收": ["迁移", "割接", "并行", "灰度", "切换", "回退", "验收"],
    "成本与收益": ["TCO", "ROI", "成本", "预算", "投资回报", "现金流", "敏感性"],
}

MODE_EXTRAS = {
    "brief": {"风险与决策": ["风险", "替代方案", "待决定"]},
    "proposal": {
        "架构设计": ["架构", "接口", "数据流", "部署", "责任边界"],
        "风险与决策": ["风险", "替代方案", "待决定"],
    },
    "blueprint": {
        "架构设计": ["架构", "接口", "数据流", "部署", "责任边界"],
        "数据治理": ["主数据", "数据治理", "数据流", "主索引", "数据资产"],
        "风险与决策": ["风险", "替代方案", "待决定"],
    },
}

VAGUE_PATTERNS = ["提升效率", "降低成本", "优化流程", "增强体验", "提高质量", "减少负担"]
PLACEHOLDER_RE = re.compile(
    r"\[(?:(?i:TBD|TODO)|待补|待确认|待客户确认)[^\]]*\]"
    r"|\[(?:[A-Z][A-Z0-9]*_[A-Z0-9_./-]+|SOURCE|DATE|REGION|VALUE|FORMULA|CURRENCY|UNIT|RANGE)\](?![\[(])"
    r"|<(?:(?i:TBD|TODO|PLACEHOLDER)|待补|待确认)[^<>\n]*>",
)


def cjk_bigrams(text: str) -> list[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]+", text)
    grams: list[str] = []
    for chunk in chunks:
        if len(chunk) == 1:
            grams.append(chunk)
        else:
            grams.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return grams


def tokenize(text: str) -> set[str]:
    ascii_tokens = re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())
    return set(ascii_tokens + cjk_bigrams(text))


class SolutionLogicChecker:
    def __init__(self, file_path: Path, mode: str, allow_placeholders: bool = False):
        self.file_path = file_path
        self.mode = mode
        self.allow_placeholders = allow_placeholders
        self.content = file_path.read_text(encoding="utf-8")
        self.headings = re.findall(r"^(##+)\s+(.+?)\s*$", self.content, re.MULTILINE)
        self.sections = self._split_sections()

    def _split_sections(self) -> dict[str, str]:
        sections: dict[str, str] = {}
        current: str | None = None
        buffer: list[str] = []
        for line in self.content.splitlines():
            match = re.match(r"^(##+)\s+(.+?)\s*$", line)
            if match:
                if current is not None:
                    sections[current] = "\n".join(buffer).strip()
                current = match.group(2).strip()
                buffer = []
            elif current is not None:
                buffer.append(line)
        if current is not None:
            sections[current] = "\n".join(buffer).strip()
        return sections

    def deterministic_errors(self) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not self.content.strip():
            errors.append({"code": "E_EMPTY_FILE", "message": "文档为空。"})
        if not self.headings:
            errors.append({"code": "E_MISSING_HEADINGS", "message": "缺少二级或更深层级的 Markdown 标题。"})
        if not self.allow_placeholders:
            matches = sorted(set(PLACEHOLDER_RE.findall(self.content)))
            if matches:
                errors.append(
                    {
                        "code": "E_UNRESOLVED_PLACEHOLDER",
                        "message": "最终稿仍包含未处理占位符。",
                        "instances": matches[:20],
                    }
                )
        return errors

    def overlap_warnings(self) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        titles = list(self.sections)
        for left, right in itertools.combinations(titles, 2):
            left_tokens = tokenize(self.sections[left])
            right_tokens = tokenize(self.sections[right])
            if len(left_tokens) < 25 or len(right_tokens) < 25:
                continue
            overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
            if overlap >= 0.55:
                warnings.append(
                    {
                        "code": "W_SECTION_OVERLAP",
                        "left_section": left,
                        "right_section": right,
                        "overlap_ratio": round(overlap, 3),
                        "message": "章节词汇重叠较高；这只是复核提示，不等同于违反 MECE。",
                    }
                )
        return warnings

    def vague_claim_warnings(self) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for title, section in self.sections.items():
            for phrase in VAGUE_PATTERNS:
                for context in re.findall(rf".{{0,30}}{re.escape(phrase)}.{{0,30}}", section):
                    warnings.append(
                        {
                            "code": "W_VAGUE_CLAIM",
                            "section": title,
                            "context": context.strip(),
                            "message": "该表述可能需要基线、目标、测量方法或明确标记为待测算。",
                        }
                    )
        return warnings

    def dimension_warnings(self) -> list[dict[str, Any]]:
        dimensions = dict(BASE_DIMENSIONS)
        dimensions.update(MODE_EXTRAS.get(self.mode, {}))
        lowered = self.content.lower()
        return [
            {
                "code": "W_POSSIBLE_MISSING_DIMENSION",
                "dimension": dimension,
                "message": "未发现相关关键词；请人工判断该维度是否适用于当前范围。",
            }
            for dimension, keywords in dimensions.items()
            if not any(keyword.lower() in lowered for keyword in keywords)
        ]

    def run(self) -> dict[str, Any]:
        errors = self.deterministic_errors()
        warnings = (
            self.overlap_warnings()
            + self.vague_claim_warnings()
            + self.dimension_warnings()
        )
        review = [
            {
                "code": "R_HUMAN_REVIEW",
                "items": ["方案逻辑", "标题准确性", "产品适配", "承诺风险", "项目可执行性"],
                "message": "这些判断不能由关键词扫描替代。",
            }
        ]
        status = "fail" if errors else "warning" if warnings else "pass"
        return {
            "schema_version": 1,
            "file": str(self.file_path),
            "mode": self.mode,
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "review": review,
            "summary": {
                "error_count": len(errors),
                "warning_count": len(warnings),
                "review_count": len(review),
            },
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_path", type=Path)
    parser.add_argument("mode", nargs="?", choices=sorted(MODE_EXTRAS), default="proposal")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Validate a reusable template without treating its placeholders as release errors.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checker = SolutionLogicChecker(args.file_path, args.mode, args.allow_placeholders)
        report = checker.run()
    except (OSError, UnicodeError) as exc:
        report = {
            "schema_version": 1,
            "file": str(args.file_path),
            "status": "fail",
            "errors": [{"code": "E_FILE_READ", "message": str(exc)}],
            "warnings": [],
            "review": [],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
