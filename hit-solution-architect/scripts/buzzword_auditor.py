"""
<!-- Standard Header -->
@Input: Draft MD file
@Output: Scan report with forbidden terms, bold count, and vague quantification warnings.
@Pos: Phase 7 (Narrative Refinement)
@Maintenance Protocol: Vocabulary list update must sync SKILL.md and user preferences.
@Version: V5.0 — aligned with SKILL.md V5.0 core mandates.
"""
import sys
import os
import json
import re

# Configuration: Forbidden terms and their suggested professional replacements
BUZZWORD_MAP = {
    "赋能": ["支撑", "注入", "助力"],
    "抓手": ["切入点", "治理工具", "业务支点", "杠杆"],
    "闭环": ["全程协同", "逻辑衔接", "完整动线", "End-to-End"],
    "生态位": ["战略定位", "业务象限", "功能边界"],
    "打法": ["策略组合", "实施路径", "战术动作"],
    "对齐": ["一致化", "标准化匹配", "逻辑映射"],
    "颗粒度": ["精细度", "层级深度", "分辨率"],
    "底层逻辑": ["核心机制", "归因模型", "基本原理"],
    "心智": ["认知模型", "决策习惯", "用户意识"],
    "拉通": ["数据贯通", "业务协同", "集成"],
    "打通": ["数据贯通", "接口建设", "集成"],
    "沉淀": ["积累", "归档", "结构化存储"],
    "落地": ["实施", "部署", "交付"],
    "全链路": ["全流程", "端到端"],
    "一盘棋": ["统筹规划", "协同治理"],
    "降本增效": ["量化为具体工时节省与成本削减"],
    "数字化转型赋能": ["数字化驱动XX改进"],
    "新质生产力": ["具体技术能力（如AI辅助诊断、数据自动治理）"],
    "智慧XX": ["数字化XX", "AI增强XX"],
    "生态": ["技术栈", "产品矩阵", "合作网络"],
}

# V5.0: Vague quantification patterns (SKILL.md 2.3 requires HEOR-grade precision)
VAGUE_PATTERNS = [
    (r"(?:明显|显著|大幅|极大地?|有效地?)\s*(?:提升|提高|改善|优化|增强|降低|减少)", 
     "必须量化为具体指标：[当前状态] -> [目标状态] (量化数值)"),
    (r"(?:一定程度上|在某种程度上)", 
     "删除模糊限定词，给出具体程度或数据支撑"),
]

# V5.0: Maximum allowed bold occurrences (Three-Bold Rule, SKILL.md 2.1)
MAX_BOLD_COUNT = 3


def audit_file(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    findings = []
    
    # 1. Style Check: Bold Count Limit (Three-Bold Rule)
    bold_matches = re.findall(r'\*\*[^*]+\*\*', content)
    bold_count = len(bold_matches)
    if bold_count > MAX_BOLD_COUNT:
        findings.append({
            "type": "Style Violation",
            "issue": f"Bold count ({bold_count}) exceeds Three-Bold Rule limit ({MAX_BOLD_COUNT})",
            "instances": bold_matches[:10],  # Show first 10
            "suggestion": f"全篇加粗不得超过 {MAX_BOLD_COUNT} 处。保留最具战略判词价值的加粗，其余改用 Headers 或 Blockquotes。"
        })
    
    # 2. Semantic Check: Buzzwords
    for word, replacements in BUZZWORD_MAP.items():
        if word in content:
            findings.append({
                "type": "Semantic Violation",
                "issue": f"Forbidden Buzzword: '{word}'",
                "suggestion": f"Replace with: {', '.join(replacements)}"
            })

    # 3. Quantification Check: Vague claims (V5.0 HEOR requirement)
    for pattern, suggestion in VAGUE_PATTERNS:
        matches = re.findall(pattern, content)
        if matches:
            findings.append({
                "type": "Quantification Violation",
                "issue": f"Vague quantification detected: '{matches[0]}' (共 {len(matches)} 处)",
                "suggestion": suggestion
            })

    # Output Results
    report_path = os.path.join(os.path.dirname(file_path), "audit_report.json")
    
    output_data = {
        "target_file": file_path,
        "status": "Failed" if findings else "Passed",
        "metrics": {
            "bold_count": bold_count,
            "bold_limit": MAX_BOLD_COUNT,
            "buzzword_violations": sum(1 for f in findings if f["type"] == "Semantic Violation"),
            "vague_violations": sum(1 for f in findings if f["type"] == "Quantification Violation"),
        },
        "findings": findings
    }

    # Write JSON Report
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Console Output
    if findings:
        print(f"❌ Audit Failed. Found {len(findings)} violations.")
        print(f"   Bold: {bold_count}/{MAX_BOLD_COUNT} | Buzzwords: {output_data['metrics']['buzzword_violations']} | Vague: {output_data['metrics']['vague_violations']}")
        print(f"Detailed Report: {report_path}")
        for finding in findings:
            print(f"- [{finding['type']}] {finding['issue']} -> {finding['suggestion']}")
        sys.exit(1)
    else:
        print("✅ Audit Passed: No stylistic, semantic, or quantification violations found.")
        sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python buzzword_auditor.py <file_md>")
    else:
        audit_file(sys.argv[1])
