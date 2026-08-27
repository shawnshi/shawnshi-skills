"""Deterministic and heuristic quality gate for healthcare solution drafts.

Exit codes used by this script family:
0 = check completed without a blocking content error;
1 = document failed a content gate;
2 = arguments, input, or output prevented a reliable check.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "2.0"
EXIT_OK = 0
EXIT_CONTENT_FAILURE = 1
EXIT_RUNTIME_FAILURE = 2
PROFILES = ("brief", "review", "proposal", "blueprint", "design")
STAGES = ("draft", "review", "release")
DEFAULT_MAX_WARNINGS = 50
MAX_WARNING_LIMIT = 500
MAX_INPUT_BYTES = 10 * 1024 * 1024


MODULE_RULES: dict[str, dict[str, Any]] = {
    "context": {
        "label": "现状、约束与信息缺口",
        "keywords": ("现状", "约束", "信息缺口", "存量系统", "业务痛点"),
    },
    "architecture": {
        "label": "目标架构与责任边界",
        "keywords": ("目标架构", "架构设计", "系统边界", "部署边界", "责任边界"),
    },
    "data": {
        "label": "数据治理与权威源",
        "keywords": ("数据治理", "数据权威源", "主数据", "主索引", "数据质量"),
    },
    "interoperability": {
        "label": "互操作与接口",
        "keywords": ("互操作", "接口标准", "接口清单", "集成平台", "数据交换"),
    },
    "security": {
        "label": "安全、隐私与合规",
        "keywords": ("安全", "隐私", "合规", "访问控制", "审计", "脱敏"),
    },
    "operations": {
        "label": "运维、监控与故障降级",
        "keywords": ("运维", "可观测", "监控告警", "故障降级", "应急处置"),
    },
    "nonfunctional": {
        "label": "非功能要求",
        "keywords": ("非功能", "可用性", "峰值并发", "响应时间", "RTO", "RPO"),
    },
    "migration": {
        "label": "迁移、回退与验收",
        "keywords": ("迁移", "割接", "双轨", "灰度切换", "回退", "迁移验收"),
    },
    "tco": {
        "label": "TCO/ROI 与投资测算",
        "keywords": ("TCO", "ROI", "总拥有成本", "投资回报", "成本模型", "收益模型"),
    },
    "traceability": {
        "label": "需求到验收追溯",
        "keywords": ("追溯矩阵", "需求编号", "验收指标", "验收证据", "能力映射"),
    },
    "clinical-safety": {
        "label": "临床连续性与患者安全",
        "keywords": ("临床连续性", "患者安全", "人工降级", "医嘱核对", "临床签字"),
    },
    "evidence": {
        "label": "主张级证据与时效",
        "keywords": ("证据台账", "证据清单", "证据强度", "资料日期", "来源核验"),
    },
    "risk": {
        "label": "风险、替代方案与待决定事项",
        "keywords": ("风险", "替代方案", "待决定", "剩余风险", "决策门槛"),
    },
}

PROFILE_MODULES: dict[str, tuple[str, ...]] = {
    "brief": ("context", "risk"),
    "review": ("architecture", "nonfunctional", "evidence", "risk"),
    "proposal": ("context", "architecture", "security", "nonfunctional", "traceability", "risk"),
    "blueprint": (
        "context",
        "architecture",
        "data",
        "interoperability",
        "security",
        "operations",
        "nonfunctional",
        "traceability",
        "risk",
    ),
    "design": (
        "architecture",
        "data",
        "interoperability",
        "security",
        "operations",
        "nonfunctional",
        "traceability",
        "risk",
    ),
}

MODULE_ALIASES = {
    "clinical_safety": "clinical-safety",
    "clinical": "clinical-safety",
}

VAGUE_PATTERNS = ("提升效率", "降低成本", "优化流程", "增强体验", "提高质量", "减少负担")

# {{FIELD}} is the only recommended placeholder form. The legacy bracketed
# registry is intentionally finite: [HL7_V2] and [ISO_27001] are not inferred
# to be placeholders merely because they contain capitals and underscores.
LEGACY_PLACEHOLDER_NAMES = frozenset(
    {
        "TBD",
        "TODO",
        "ANALYSIS_PERIOD",
        "BASELINE",
        "BASELINE_METRIC",
        "BENEFIT_01",
        "CATEGORY",
        "CONDITIONS",
        "COST_DOWNTIME",
        "COST_HW",
        "COST_LABOR",
        "COST_MAINT",
        "COST_MIGRATION",
        "COST_SW",
        "CURRENCY",
        "CURRENCY/PERIOD",
        "DATE",
        "DIMENSION",
        "DOWNTIME_WINDOW",
        "ENTRY",
        "ENVIRONMENT",
        "EVALUATION_PROTOCOL",
        "EXIT",
        "FORMULA",
        "GAP",
        "HITL_ACTIONS",
        "IMPACT",
        "KNOWLEDGE_SOURCES",
        "LIMITATIONS",
        "MATURITY_TARGET",
        "MEASUREMENT_METHOD",
        "METRIC",
        "MITIGATION",
        "MODEL_VERSION",
        "OUTPUT_SCHEMA",
        "OWNER",
        "P99_LATENCY_TARGET",
        "PARALLEL_RUN_DAYS",
        "PERIOD_0",
        "PERIOD_1",
        "PERIOD_N",
        "PHASE_DURATION",
        "PRODUCT",
        "RANGE",
        "REGION",
        "REQUIRED_INPUTS",
        "RESIDUAL",
        "RESULT",
        "ROLLBACK",
        "SCOPE",
        "SOURCE",
        "SOURCE_OR_A-ID",
        "SOURCE_OR_ASSUMPTION",
        "SOURCE_OR_OBSERVATION",
        "TARGET",
        "TARGET_METRIC",
        "TEST",
        "TRIGGER",
        "TRIGGER_POINT",
        "UNIT",
        "URL_OR_FILE",
        "URL_OR_REPORT",
        "VALUE",
        "VARIABLE_IDS",
        "VERSION",
        "WORKLOAD",
        "业务对象",
        "动作或判断",
        "证据支持的目标或约束",
        "原文摘录或准确转述",
        "客户证据",
        "差距",
        "文件/页码/条款",
        "条件",
    }
)
LEGACY_PLACEHOLDER_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:REQ|CAP|POLICY|CANDIDATE|TEST|RISK|PHASE)-\d+",
        r"EVIDENCE_OR_A-\d+",
        r"(?:SOURCE|EVIDENCE)_OR_A-\d+",
    )
)
CURLY_PLACEHOLDER_RE = re.compile(r"\{\{\s*[^{}\n]+?\s*\}\}")
BRACKET_TOKEN_RE = re.compile(r"\[([^\[\]\n]+)\]")
CHINESE_PENDING_RE = re.compile(r"^(?:待核验|待确认|待客户确认|待补|待补充)(?:\s|$|[:：].*)")
CONTROLLED_PLACEHOLDER_SECTION_RE = re.compile(
    r"(?:信息缺口|未知项|取证计划|待决定|假设|排除项)", re.IGNORECASE
)

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
NEGATION_BEFORE_RE = re.compile(
    r"(?:不涉及|不包含|不包括|不含|不纳入|无需|无须|不需要|不要求|暂不(?:考虑|纳入|建设)?|排除)"
)
NEGATION_AFTER_RE = re.compile(r"(?:不在|不属于|排除在).{0,12}(?:范围|边界|本期|本次)")
CLAUSE_BOUNDARY_RE = re.compile(r"[。；;.!！？\n]|但(?:是)?|然而|不过")

QUANTIFIED_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])\d+(?:\.\d+)?\s*(?:%|％|万元|亿元|元|小时|分钟|天|人日|倍|毫秒|秒|ms)",
    re.IGNORECASE,
)
DIRECT_ROI_TCO_VALUE_RE = re.compile(
    r"(?:\bROI\b|\bTCO\b|投资回报率?|总拥有成本)[^\n。；;]{0,16}?\d+(?:\.\d+)?",
    re.IGNORECASE,
)
BENEFIT_TERM_RE = re.compile(
    r"(?:\bROI\b|\bTCO\b|投资回报|总拥有成本|收益|节省|降本|降低成本|减少成本|"
    r"提升效率|提高效率|缩短|减少(?:时间|人力|工作量)|改善(?:质量|结局))",
    re.IGNORECASE,
)
SOURCE_MARKER_RE = re.compile(
    r"(?:来源|source|客户材料|合同|公开文件|测量记录|测算底表|https?://|\[[\^]?\d+\])",
    re.IGNORECASE,
)
DATE_MARKER_RE = re.compile(r"(?:资料日期|测量日期|as[_ -]?of|20\d{2}[-/.年]\d{1,2})", re.IGNORECASE)
REGION_MARKER_RE = re.compile(r"(?:适用地区|地区|region|全国|中国|澳门|香港|医院|机构范围)", re.IGNORECASE)


@dataclass
class Section:
    """One ordered Markdown section and its direct body."""

    title: str
    level: int
    line: int
    body_lines: list[str] = field(default_factory=list)
    has_child: bool = False

    @property
    def body(self) -> str:
        return "\n".join(self.body_lines).strip()


def _without_fenced_code_lines(content: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    fence_character: str | None = None
    fence_length = 0
    for line_number, line in enumerate(content.splitlines(), 1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is None:
            lines.append((line_number, line))
    return lines


def find_placeholders(content: str) -> list[str]:
    """Return explicitly registered placeholders in first-seen order."""

    found: list[tuple[int, str]] = []
    for match in CURLY_PLACEHOLDER_RE.finditer(content):
        found.append((match.start(), match.group(0)))
    for match in BRACKET_TOKEN_RE.finditer(content):
        token = match.group(1).strip()
        registered = (
            token in LEGACY_PLACEHOLDER_NAMES
            or bool(CHINESE_PENDING_RE.match(token))
            or any(pattern.fullmatch(token) for pattern in LEGACY_PLACEHOLDER_PATTERNS)
        )
        if registered:
            found.append((match.start(), match.group(0)))

    seen: set[str] = set()
    ordered: list[str] = []
    for _, placeholder in sorted(found, key=lambda item: item[0]):
        if placeholder not in seen:
            seen.add(placeholder)
            ordered.append(placeholder)
    return ordered


def classify_review_placeholders(content: str) -> tuple[list[str], list[str]]:
    """Split placeholders into commitment text and controlled-gap sections.

    A heading named for information gaps, assumptions, exclusions, evidence
    collection, or pending decisions opens a controlled section. Descendant
    headings inherit that state until the document returns to the same or a
    higher heading level.
    """

    blocking: list[str] = []
    controlled: list[str] = []
    section_state: dict[int, bool] = {}
    current_controlled = False
    for _, line in _without_fenced_code_lines(content):
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            section_state = {
                existing_level: state
                for existing_level, state in section_state.items()
                if existing_level < level
            }
            parent_controlled = section_state[max(section_state)] if section_state else False
            current_controlled = bool(
                parent_controlled
                or CONTROLLED_PLACEHOLDER_SECTION_RE.search(heading.group(2))
            )
            section_state[level] = current_controlled
        target = controlled if current_controlled else blocking
        target.extend(find_placeholders(line))

    def unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    return unique(blocking), unique(controlled)


def cjk_bigrams(text: str) -> list[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]+", text)
    grams: list[str] = []
    for chunk in chunks:
        if len(chunk) == 1:
            grams.append(chunk)
        else:
            grams.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return grams


def tokenize(text: str) -> frozenset[str]:
    ascii_tokens = re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())
    return frozenset(ascii_tokens + cjk_bigrams(text))


def _normalize_title(title: str) -> str:
    title = re.sub(r"[*_`#]", "", title).strip().lower()
    title = re.sub(
        r"^\s*(?:第?[一二三四五六七八九十百\d]+[章节部分篇]?|\d+(?:\.\d+)*)[.、：:)）\-\s]+",
        "",
        title,
    )
    return re.sub(r"\s+", "", title)


def parse_sections(content: str, profile: str) -> tuple[list[Section], list[Section]]:
    """Parse headings without collapsing duplicate titles into a dictionary."""

    all_sections: list[Section] = []
    current: Section | None = None
    for line_number, line in _without_fenced_code_lines(content):
        match = HEADING_RE.match(line)
        if match:
            current = Section(match.group(2).strip(), len(match.group(1)), line_number)
            all_sections.append(current)
        elif current is not None:
            current.body_lines.append(line)

    for index, section in enumerate(all_sections):
        if index + 1 < len(all_sections) and all_sections[index + 1].level > section.level:
            section.has_child = True

    minimum_level = 1 if profile == "brief" else 2
    eligible = [section for section in all_sections if section.level >= minimum_level]
    return all_sections, eligible


def _visible_body(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*(?:---+|\*\*\*+|___+)\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _keyword_is_positive(content: str, keyword: str) -> bool:
    lowered = content.lower()
    needle = keyword.lower()
    start = 0
    while True:
        index = lowered.find(needle, start)
        if index < 0:
            return False
        left = max((match.end() for match in CLAUSE_BOUNDARY_RE.finditer(content[:index])), default=0)
        right_match = CLAUSE_BOUNDARY_RE.search(content, index + len(keyword))
        right = right_match.start() if right_match else len(content)
        segment = content[left:right]
        relative_index = max(index - left, 0)
        before = segment[:relative_index]
        after = segment[relative_index + len(keyword) :]
        if not NEGATION_BEFORE_RE.search(before[-40:]) and not NEGATION_AFTER_RE.search(after[:40]):
            return True
        start = index + len(needle)


def _module_is_present(content: str, module: str) -> bool:
    return any(_keyword_is_positive(content, keyword) for keyword in MODULE_RULES[module]["keywords"])


def _quantified_claims(content: str) -> list[dict[str, Any]]:
    lines = _without_fenced_code_lines(content)
    claims: list[dict[str, Any]] = []
    for index, (line_number, line) in enumerate(lines):
        has_unit = bool(QUANTIFIED_VALUE_RE.search(line))
        if not BENEFIT_TERM_RE.search(line) or not (has_unit or DIRECT_ROI_TCO_VALUE_RE.search(line)):
            continue
        nearby = "\n".join(candidate for _, candidate in lines[max(0, index - 2) : index + 3])
        claims.append(
            {
                "line": line_number,
                "text": line.strip()[:240],
                "has_source": bool(SOURCE_MARKER_RE.search(nearby)),
                "has_date": bool(DATE_MARKER_RE.search(nearby)),
                "has_region": bool(REGION_MARKER_RE.search(nearby)),
                "has_unit": has_unit,
            }
        )
    return claims


def status_from_findings(
    errors: Sequence[dict[str, Any]],
    warnings: Sequence[dict[str, Any]],
    review: Sequence[dict[str, Any]],
) -> str:
    if errors:
        return "fail"
    if review:
        return "review_required"
    if warnings:
        return "warning"
    return "pass"


def runtime_failure_report(tool: str, target_file: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "target_file": target_file,
        "status": "fail",
        "automated_checks": "not_run",
        "errors": [{"code": code, "message": message}],
        "warnings": [],
        "review": [],
        "summary": {"error_count": 1, "warning_count": 0, "review_count": 0},
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(report) + "\n", encoding="utf-8")


def read_utf8_document(path: Path, *, max_bytes: int = MAX_INPUT_BYTES) -> str:
    """Read UTF-8 Markdown with optional BOM and a bounded input size."""

    size = path.stat().st_size
    if size > max_bytes:
        raise OSError(f"输入文件超过 {max_bytes} 字节上限：{size}。")
    return path.read_text(encoding="utf-8-sig")


class SolutionLogicChecker:
    """Run the quality gate against already-loaded Markdown content."""

    def __init__(
        self,
        content: str,
        *,
        target_file: str,
        profile: str = "proposal",
        stage: str = "review",
        required_modules: Iterable[str] = (),
        allow_placeholders: bool = False,
        review_complete: bool = False,
        max_warnings: int = DEFAULT_MAX_WARNINGS,
    ):
        self.content = content
        self.target_file = target_file
        self.profile = profile
        self.stage = stage
        self.required_modules = tuple(dict.fromkeys(required_modules))
        self.allow_placeholders = allow_placeholders
        self.review_complete = review_complete
        self.max_warnings = max_warnings
        self.all_sections, self.sections = parse_sections(content, profile)
        self.section_tokens = [tokenize(section.body) for section in self.sections]

    @classmethod
    def from_path(cls, file_path: Path, **kwargs: Any) -> "SolutionLogicChecker":
        return cls(read_utf8_document(file_path), target_file=str(file_path), **kwargs)

    def structural_findings(self) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not self.content.strip():
            return [{"code": "E_EMPTY_FILE", "message": "文档为空。"}]
        if not self.sections:
            level_description = "一级或更深" if self.profile == "brief" else "二级或更深"
            errors.append(
                {
                    "code": "E_MISSING_HEADINGS",
                    "message": f"当前 profile 缺少{level_description}的 Markdown 章节标题。",
                }
            )
            return errors

        by_title: dict[str, list[Section]] = {}
        for section in self.sections:
            normalized = _normalize_title(section.title)
            if normalized:
                by_title.setdefault(normalized, []).append(section)
        duplicates = [items for items in by_title.values() if len(items) > 1]
        if duplicates:
            errors.append(
                {
                    "code": "E_DUPLICATE_SECTION",
                    "message": "存在重复章节标题；章节不会再被静默覆盖。",
                    "instances": [
                        {"title": items[0].title, "lines": [item.line for item in items]}
                        for items in duplicates[:20]
                    ],
                }
            )

        empty_sections = [
            {"title": section.title, "line": section.line}
            for section in self.sections
            if not _visible_body(section.body) and not section.has_child
        ]
        if empty_sections:
            errors.append(
                {
                    "code": "E_EMPTY_SECTION",
                    "message": "章节没有正文或子章节。",
                    "instances": empty_sections[:20],
                }
            )
        return errors

    def placeholder_findings(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        placeholders = find_placeholders(self.content)
        if not placeholders:
            return [], []
        if self.stage == "draft" or self.allow_placeholders:
            finding: dict[str, Any] = {
                "code": "W_UNRESOLVED_PLACEHOLDER",
                "message": "草稿或模板仍包含占位符；进入发布阶段前必须处理。",
                "instances": placeholders[:50],
                "total": len(placeholders),
            }
            return [], [finding]
        if self.stage == "review":
            blocking, controlled = classify_review_placeholders(self.content)
            errors = []
            warnings = []
            if blocking:
                errors.append(
                    {
                        "code": "E_UNRESOLVED_PLACEHOLDER",
                        "message": "审阅稿的技术承诺正文仍包含未处理占位符。",
                        "instances": blocking[:50],
                        "total": len(blocking),
                    }
                )
            if controlled:
                warnings.append(
                    {
                        "code": "W_CONTROLLED_REVIEW_PLACEHOLDER",
                        "message": "审阅稿在信息缺口、假设、排除项或取证计划中保留受控占位符。",
                        "instances": controlled[:50],
                        "total": len(controlled),
                    }
                )
            return errors, warnings
        return [
            {
                "code": "E_UNRESOLVED_PLACEHOLDER",
                "message": "可提交稿仍包含未处理占位符；新稿应统一使用 {{FIELD}} 语法。",
                "instances": placeholders[:50],
                "total": len(placeholders),
            }
        ], []

    def module_findings(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        active_modules = tuple(dict.fromkeys(PROFILE_MODULES[self.profile] + self.required_modules))
        explicitly_required = set(self.required_modules)
        for module in active_modules:
            if _module_is_present(self.content, module):
                continue
            finding = {
                "module": module,
                "dimension": MODULE_RULES[module]["label"],
                "source": "--require" if module in explicitly_required else f"profile:{self.profile}",
            }
            if module in explicitly_required and self.stage in {"review", "release"}:
                errors.append(
                    {
                        **finding,
                        "code": "E_MISSING_REQUIRED_MODULE",
                        "message": "未发现该显式必需模块的正向内容；否定或排除表述不计为覆盖。",
                    }
                )
            else:
                warnings.append(
                    {
                        **finding,
                        "code": "W_POSSIBLE_MISSING_MODULE",
                        "message": "未发现该模块的正向内容；请确认是否需要补充或明确排除理由。",
                    }
                )
        return errors, warnings

    def quantified_claim_findings(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        claims = _quantified_claims(self.content)
        unsourced = [claim for claim in claims if not claim["has_source"]]
        incomplete = [
            claim
            for claim in claims
            if claim["has_source"]
            and (not claim["has_date"] or not claim["has_region"] or not claim["has_unit"])
        ]
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if unsourced:
            finding: dict[str, Any] = {
                "code": "E_UNSOURCED_QUANTIFIED_BENEFIT",
                "message": "量化收益、ROI 或 TCO 数字缺少可追溯来源。",
                "instances": unsourced[:20],
                "total": len(unsourced),
            }
            if self.stage == "release":
                errors.append(finding)
            else:
                finding["code"] = "W_UNSOURCED_QUANTIFIED_BENEFIT"
                warnings.append(finding)
        if incomplete:
            finding = {
                "code": "E_INCOMPLETE_QUANT_METADATA",
                "message": "部分量化主张虽有来源，但缺少单位、资料日期或适用地区。",
                "instances": incomplete[:20],
                "total": len(incomplete),
            }
            if self.stage == "release":
                errors.append(finding)
            else:
                finding["code"] = "W_INCOMPLETE_QUANT_METADATA"
                warnings.append(finding)
        return errors, warnings

    def overlap_warnings(self, remaining: int) -> list[dict[str, Any]]:
        if remaining <= 0:
            return []
        warnings: list[dict[str, Any]] = []
        indexed_sections = list(enumerate(self.sections))
        for (left_index, left), (right_index, right) in itertools.combinations(indexed_sections, 2):
            left_tokens = self.section_tokens[left_index]
            right_tokens = self.section_tokens[right_index]
            if len(left_tokens) < 25 or len(right_tokens) < 25:
                continue
            overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
            if overlap >= 0.55:
                warnings.append(
                    {
                        "code": "W_SECTION_OVERLAP",
                        "left_section": left.title,
                        "right_section": right.title,
                        "overlap_ratio": round(overlap, 3),
                        "message": "章节词汇重叠较高；请人工判断是否重复。",
                    }
                )
                if len(warnings) >= remaining:
                    break
        return warnings

    def vague_claim_warnings(self, remaining: int) -> list[dict[str, Any]]:
        if remaining <= 0:
            return []
        warnings: list[dict[str, Any]] = []
        for section in self.sections:
            for phrase in VAGUE_PATTERNS:
                for match in re.finditer(re.escape(phrase), section.body):
                    start = max(0, match.start() - 30)
                    end = min(len(section.body), match.end() + 30)
                    warnings.append(
                        {
                            "code": "W_VAGUE_CLAIM",
                            "section": section.title,
                            "context": section.body[start:end].strip(),
                            "message": "补充基线、目标和测量方法，或明确标记为待测算。",
                        }
                    )
                    if len(warnings) >= remaining:
                        return warnings
        return warnings

    def run(self) -> dict[str, Any]:
        errors = self.structural_findings()
        placeholder_errors, placeholder_warnings = self.placeholder_findings()
        module_errors, module_warnings = self.module_findings()
        claim_errors, claim_warnings = self.quantified_claim_findings()
        errors.extend(placeholder_errors + module_errors + claim_errors)

        candidate_warnings = placeholder_warnings + module_warnings + claim_warnings
        warning_total_before_limit = len(candidate_warnings)
        warnings = candidate_warnings[: self.max_warnings]
        remaining = max(self.max_warnings - len(warnings), 0)
        overlap = self.overlap_warnings(remaining)
        warning_total_before_limit += len(overlap)
        warnings.extend(overlap)
        remaining = max(self.max_warnings - len(warnings), 0)
        vague = self.vague_claim_warnings(remaining)
        warning_total_before_limit += len(vague)
        warnings.extend(vague)

        review: list[dict[str, Any]] = []
        if self.stage == "release" and not self.review_complete:
            review.append(
                {
                    "code": "R_RELEASE_APPROVAL_REQUIRED",
                    "items": ["方案逻辑", "产品适配", "承诺风险", "临床安全", "项目可执行性"],
                    "message": "自动检查已完成，但发布仍需具备授权的负责人确认。",
                }
            )

        status = status_from_findings(errors, warnings, review)
        human_review = (
            "completed"
            if self.stage == "release" and self.review_complete
            else "required"
            if self.stage == "release"
            else "not_applicable"
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "logic_checker",
            "target_file": self.target_file,
            "profile": self.profile,
            "stage": self.stage,
            "status": status,
            "automated_checks": "fail" if errors else "pass",
            "gate": {
                "human_review": human_review,
                "release_ready": not errors and self.review_complete if self.stage == "release" else None,
            },
            "errors": errors,
            "warnings": warnings,
            "review": review,
            "structure": {
                "sections": [
                    {"title": section.title, "level": section.level, "line": section.line}
                    for section in self.sections
                ]
            },
            "summary": {
                "error_count": len(errors),
                "warning_count": len(warnings),
                "warning_truncated_count": max(warning_total_before_limit - len(warnings), 0),
                "review_count": len(review),
                "section_count": len(self.sections),
            },
        }


def parse_required_modules(values: Sequence[str]) -> tuple[str, ...]:
    modules: list[str] = []
    for value in values:
        modules.extend(
            MODULE_ALIASES.get(part.strip(), part.strip())
            for part in value.split(",")
            if part.strip()
        )
    return tuple(dict.fromkeys(modules))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_path", type=Path)
    parser.add_argument("legacy_profile", nargs="?", help="Deprecated positional profile.")
    parser.add_argument("--profile", metavar="{" + ",".join(PROFILES) + "}")
    parser.add_argument("--stage", default="review", metavar="{" + ",".join(STAGES) + "}")
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="MODULE[,MODULE]",
        help=f"Require one or more modules: {', '.join(MODULE_RULES)}.",
    )
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Compatibility option for reusable templates; never accepted for release.",
    )
    parser.add_argument(
        "--review-complete",
        action="store_true",
        help="Record that an authorized human completed the release review.",
    )
    parser.add_argument("--max-warnings", type=int, default=DEFAULT_MAX_WARNINGS)
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    return parser.parse_args(argv)


def _configuration_error(target: str, message: str) -> int:
    print(render_report(runtime_failure_report("logic_checker", target, "E_ARGUMENT", message)))
    return EXIT_RUNTIME_FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = str(args.file_path)
    profile = args.profile or args.legacy_profile or "proposal"
    if profile not in PROFILES:
        return _configuration_error(target, f"未知 profile：{profile}。")
    if args.stage not in STAGES:
        return _configuration_error(target, f"未知 stage：{args.stage}。")
    if args.profile and args.legacy_profile and args.profile != args.legacy_profile:
        return _configuration_error(target, "位置 profile 与 --profile 冲突。")
    required_modules = parse_required_modules(args.require)
    unknown_modules = sorted(set(required_modules) - set(MODULE_RULES))
    if unknown_modules:
        return _configuration_error(target, f"未知 --require 模块：{', '.join(unknown_modules)}。")
    if not 0 <= args.max_warnings <= MAX_WARNING_LIMIT:
        return _configuration_error(target, f"--max-warnings 必须在 0 到 {MAX_WARNING_LIMIT} 之间。")
    if args.stage == "release" and args.allow_placeholders:
        return _configuration_error(target, "release 阶段不能使用 --allow-placeholders 绕过占位符门禁。")
    if args.review_complete and args.stage != "release":
        return _configuration_error(target, "--review-complete 只适用于 release 阶段。")
    if args.output and args.output.resolve(strict=False) == args.file_path.resolve(strict=False):
        return _configuration_error(target, "输出报告不能覆盖被检查的输入文档。")

    try:
        checker = SolutionLogicChecker.from_path(
            args.file_path,
            profile=profile,
            stage=args.stage,
            required_modules=required_modules,
            allow_placeholders=args.allow_placeholders,
            review_complete=args.review_complete,
            max_warnings=args.max_warnings,
        )
        report = checker.run()
    except (OSError, UnicodeError) as exc:
        report = runtime_failure_report("logic_checker", target, "E_FILE_READ", str(exc))
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE

    if args.output:
        try:
            write_report(report, args.output)
        except (OSError, UnicodeError) as exc:
            report = runtime_failure_report("logic_checker", target, "E_FILE_WRITE", str(exc))
            report["output_file"] = str(args.output)
            print(render_report(report))
            return EXIT_RUNTIME_FAILURE
    print(render_report(report))
    return EXIT_CONTENT_FAILURE if report["errors"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
