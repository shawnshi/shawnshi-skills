import itertools
import json
import re
import sys
from pathlib import Path

ACTION_PATTERNS = [
    r"通过", r"实现", r"构建", r"打造", r"优化", r"提升", r"重构", r"驱动", r"解决", r"降低", r"形成", r"建立", r"推进", r"支撑"
]

BASE_DIMENSIONS = {
    "医院痛点": ["痛点", "挑战", "现状", "矛盾", "不可能三角", "评级压力", "临床减负"],
    "迁移路径": ["迁移", "割接", "双活", "并行", "灰度", "切换", "无损"],
    "TCO/ROI": ["TCO", "ROI", "成本", "预算", "投资回报", "总体拥有成本", "回收期"],
    "信创合规": ["信创", "国产化", "自主可控", "等保", "合规", "海光", "昇腾", "达梦"],
    "受众分层": ["院长", "CIO", "临床", "科主任", "信息科", "管理层"],
}

MODE_EXTRAS = {
    "brief": {
        "风险提示": ["风险", "致命风险", "主要风险", "缓释"]
    },
    "proposal": {
        "架构设计": ["架构", "中台", "微服务", "FHIR", "接口", "Mermaid"],
        "风险提示": ["风险", "致命风险", "主要风险", "缓释"],
    },
    "blueprint": {
        "架构设计": ["架构", "中台", "微服务", "FHIR", "接口", "Mermaid"],
        "数据治理": ["主数据", "数据治理", "数据流", "主索引", "数据资产"],
        "风险提示": ["风险", "致命风险", "主要风险", "缓释"],
    },
}

EMPTY_METRIC_PATTERNS = [r"提升效率", r"降低成本", r"优化流程", r"增强体验", r"提高质量", r"减少负担"]


def cjk_bigrams(text: str):
    chunks = re.findall(r"[\u4e00-\u9fff]+", text)
    grams = []
    for chunk in chunks:
        if len(chunk) == 1:
            grams.append(chunk)
        else:
            grams.extend(chunk[i:i+2] for i in range(len(chunk) - 1))
    return grams


def tokenize(text: str):
    ascii_tokens = re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())
    return set(ascii_tokens + cjk_bigrams(text))


class SolutionLogicChecker:
    def __init__(self, file_path: str, mode: str = "proposal"):
        self.file_path = Path(file_path)
        self.mode = mode
        self.content = self._read_file()
        self.headings = self._extract_headings()
        self.sections = self._split_sections()

    def _read_file(self):
        try:
            return self.file_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(json.dumps({"status": "Failed", "error": f"Error reading file: {exc}"}, ensure_ascii=False, indent=2))
            sys.exit(1)

    def _extract_headings(self):
        return re.findall(r"^(##+)\s+(.*)$", self.content, re.MULTILINE)

    def _split_sections(self):
        sections = {}
        current = None
        buffer = []
        for line in self.content.splitlines():
            match = re.match(r"^(##+)\s+(.*)$", line)
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

    def check_me(self):
        risks = []
        titles = list(self.sections.keys())
        for left, right in itertools.combinations(titles, 2):
            left_tokens = tokenize(self.sections[left])
            right_tokens = tokenize(self.sections[right])
            if len(left_tokens) < 25 or len(right_tokens) < 25:
                continue
            overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
            if overlap >= 0.55:
                risks.append({
                    "left_section": left,
                    "right_section": right,
                    "overlap_ratio": round(overlap, 3),
                    "reason": "两个章节语义重叠过高，可能违反 MECE 的互斥要求。",
                    "suggestion": "重新划分章节边界：一个讲管理判断，一个讲架构/实施，不要重复解释同一价值点。"
                })
        return risks

    def check_action_titles(self):
        violations = []
        if not self.headings:
            violations.append({
                "title": "<missing-headings>",
                "reason": "文档没有二级及以下章节标题，无法形成结构化方案。",
                "suggestion": "至少使用二级标题组织方案章节。"
            })
            return violations

        for _level, title in self.headings:
            clean_title = re.sub(r"^\d+(\.\d+)*\s*", "", title).strip()
            is_short = len(clean_title) < 8
            has_action = any(re.search(pattern, clean_title) for pattern in ACTION_PATTERNS)
            if is_short or not has_action:
                reason = "标题过短。" if is_short else "标题缺乏动作导向与判断性。"
                violations.append({
                    "title": title,
                    "reason": f"{reason} V9 要求标题体现『动作 + 目标/价值』。",
                    "suggestion": "改写为完整判断句，例如：『通过统一主数据治理降低互联互通整改成本』。"
                })
        return violations

    def check_empty_metrics(self):
        violations = []
        for title, content in self.sections.items():
            for pattern in EMPTY_METRIC_PATTERNS:
                if pattern in content:
                    contexts = re.findall(rf".{{0,30}}{pattern}.{{0,30}}", content)
                    for ctx in contexts:
                        if not re.search(r"\d+%|\d+倍|\d+分|\d+天|\d+月|\d+年|\d+例|\d+万元|\d+元|\d+分钟|\d+min", ctx):
                            violations.append({
                                "section": title,
                                "context": ctx.strip(),
                                "reason": f"检测到空洞量化词『{pattern}』，没有数字口径。",
                                "suggestion": "补充基线、目标值和单位，或者明确暂以测算假设表示。"
                            })
        return violations

    def check_required_dimensions(self):
        dimensions = dict(BASE_DIMENSIONS)
        dimensions.update(MODE_EXTRAS.get(self.mode, {}))
        full_text = self.content.lower()
        missing = []
        for dimension, keywords in dimensions.items():
            if not any(keyword.lower() in full_text for keyword in keywords):
                missing.append({
                    "dimension": dimension,
                    "missing_keywords": keywords,
                    "suggestion": f"方案可能缺失【{dimension}】维度。V9 不允许跳过这个结果门。"
                })
        return missing

    def run_audit(self):
        me_risks = self.check_me()
        ce_risks = self.check_required_dimensions()
        title_risks = self.check_action_titles()
        metric_risks = self.check_empty_metrics()

        fatal = bool(me_risks or ce_risks or len(title_risks) > 3)
        warning = bool(metric_risks or title_risks)
        status = "Failed" if fatal else "Warning" if warning else "Passed"

        report = {
            "file": str(self.file_path),
            "mode": self.mode,
            "status": status,
            "metrics": {
                "me_violations": len(me_risks),
                "required_dimension_violations": len(ce_risks),
                "title_violations": len(title_risks),
                "empty_metrics_violations": len(metric_risks)
            },
            "details": {
                "me_risks": me_risks,
                "required_dimension_risks": ce_risks,
                "action_title_risks": title_risks,
                "empty_metrics_risks": metric_risks
            }
        }

        print(json.dumps(report, ensure_ascii=False, indent=2))
        if status != "Passed":
            sys.exit(1)
        sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print("Usage: python logic_checker.py <file_path> [mode]")
        sys.exit(1)
    file_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "proposal"
    checker = SolutionLogicChecker(file_path, mode)
    checker.run_audit()


if __name__ == "__main__":
    main()
