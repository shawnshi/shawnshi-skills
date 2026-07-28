import json
import re
import sys
import os

def load_rules(rules_path):
    with open(rules_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def check_compliance(file_path, rules):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    issues = []
    
    # 检查 restricted_words
    for word, replacement in rules.get('restricted_words', {}).items():
        if word in content:
            matches = len(re.findall(re.escape(word), content))
            issues.append(f"[STYLE WARNING] Found term '{word}' ({matches} times). Consider '{replacement}' when context supports it.")

    # 检查核心缩写是否首次出现时带有全称
    for abbr, full_name in rules.get('standard_terms', {}).items():
        if abbr in content and full_name not in content:
            issues.append(f"[TERMINOLOGY WARNING] Abbreviation '{abbr}' appears without the configured full definition '{full_name}'.")

    # 检查战略雷达 (Strategic Radar) 高敏词汇
    radar_keywords = [
        "DRG/DIP 2.0", "DRG 2.0", "DIP 2.0",
        "数据要素", "数据资产入表", 
        "三类证", "NMPA", "FDA", "SaMD",
        "互联互通", "电子病历评级"
    ]
    radar_findings = []
    for hw in radar_keywords:
        if hw in content:
            radar_findings.append(hw)
            
    if radar_findings:
        issues.append(f"[REVIEW NOTE] 报告涉及以下时效性主题: {', '.join(radar_findings)}。请核验当前适用地区、版本与原始依据。")

    return issues

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compliance_check.py <target_file>")
        sys.exit(1)

    target = sys.argv[1]
    rules_file = os.path.join(os.path.dirname(__file__), "..", "references", "medical_terms.json")

    if not os.path.exists(target):
        print(f"ERROR: File {target} not found.")
        sys.exit(1)

    try:
        findings = check_compliance(target, load_rules(rules_file))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot run deterministic input check: {exc}")
        sys.exit(1)
    
    if findings:
        print("\n=== Non-blocking Review Warnings ===")
        for issue in findings:
            print(issue)
        print("\nConclusion: These are heuristic warnings, not an automated compliance determination.")
    else:
        print("\nNo configured terminology warnings found. Human legal and clinical review may still be required.")
    sys.exit(0)
