import json
import re
import sys
import os

def load_rules(rules_path):
    with open(rules_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def check_compliance(file_path, rules):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    issues = []
    
    # 检查 restricted_words
    for word, replacement in rules.get('restricted_words', {}).items():
        if word in content:
            matches = len(re.findall(re.escape(word), content))
            issues.append(f"[Low] Found informal term '{word}' ({matches} times). Suggest using '{replacement}'.")

    # 检查核心缩写是否首次出现时带有全称
    for abbr, full_name in rules.get('standard_terms', {}).items():
        if abbr in content and full_name not in content:
            issues.append(f"[Medium] Abbreviation '{abbr}' used without full definition '{full_name}' in the document.")

    # 检查公司称谓规范
    for short, formal in rules.get('winning_specific', {}).items():
        if short in content and formal not in content:
             # 特指“卫宁”这种简称
             if short == "卫宁":
                 # 简单正则防止误报，比如“防卫宁静”
                 if re.search(rf"(?<!\w){short}(?!\w)", content):
                    issues.append(f"[High] Found informal reference '{short}'. Use formal name '{formal}'.")

    return issues

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compliance_check.py <target_file>")
        sys.exit(1)

    target = sys.argv[1]
    rules_file = os.path.join(os.path.dirname(__file__), "..", "references", "medical_terms.json")
    
    findings = check_compliance(target, load_rules(rules_file))
    
    if findings:
        print("\n=== Compliance Audit Report ===")
        for issue in findings:
            print(issue)
        print("\nConclusion: Non-compliant elements found. Refinement recommended.")
    else:
        print("\nCompliance Check Passed: All terms meet industry standards.")
