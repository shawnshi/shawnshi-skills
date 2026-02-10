import sys
import os
import json

# Configuration: Forbidden terms and their suggested professional replacements
BUZZWORD_MAP = {
    "赋能": ["支撑", "注入", "助力", "Cognitive Injection"],
    "抓手": ["切入点", "治理工具", "业务支点", "杠杆"],
    "闭环": ["全程协同", "逻辑衔接", "完整动线", "End-to-End"],
    "生态位": ["战略定位", "业务象限", "功能边界"],
    "打法": ["策略组合", "实施路径", "战术动作"],
    "对齐": ["一致化", "标准化匹配", "逻辑映射", "Semantic Alignment"],
    "颗粒度": ["精细度", "层级深度", "分辨率"],
    "底层逻辑": ["核心机制", "归因模型", "First Principles"],
    "心智": ["认知模型", "决策习惯", "用户意识"],
    "拉通": ["数据贯通", "业务协同", "Integration"]
}

def audit_file(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    findings = []
    
    # 1. Style Check: Forbidden Bold Syntax
    if "**" in content:
        findings.append({
            "type": "Style Violation",
            "issue": "Forbidden Bold Syntax (**)",
            "suggestion": "Remove bolding. Use Headers (#) or > Blockquotes for emphasis."
        })
    
    # 2. Semantic Check: Buzzwords
    for word, replacements in BUZZWORD_MAP.items():
        if word in content:
            findings.append({
                "type": "Semantic Violation",
                "issue": f"Forbidden Buzzword: '{word}'",
                "suggestion": f"Replace with: {', '.join(replacements)}"
            })

    # Output Results
    report_path = os.path.join(os.path.dirname(file_path), "audit_report.json")
    
    output_data = {
        "target_file": file_path,
        "status": "Failed" if findings else "Passed",
        "findings": findings
    }

    # Write JSON Report
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Console Output
    if findings:
        print(f"❌ Audit Failed. Found {len(findings)} violations.")
        print("Detailed Report generated at: audit_report.json")
        for f in findings:
            print(f"- [{f['type']}] {f['issue']} -> Suggestion: {f['suggestion']}")
        sys.exit(1) # Return non-zero exit code to signal failure
    else:
        print("✅ Audit Passed: No stylistic or semantic violations found.")
        sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python buzzword_auditor.py <file_md>")
    else:
        audit_file(sys.argv[1])
