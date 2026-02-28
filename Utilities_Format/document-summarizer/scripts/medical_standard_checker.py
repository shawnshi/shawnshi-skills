#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Input:  Extracted content JSON
@Output: Compliance Gap Analysis JSON
@Pos:    Intelligence Layer. Evaluates documents against EMR Grade 5-7 standards.

!!! Maintenance Protocol: Update policy_mapping in healthcare_ontology.json as NHC guidelines evolve.
"""

import json
import sys
from pathlib import Path

def check_compliance(content, ontology):
    """检测文档内容与医疗标准的契合度及缺口"""
    gaps = []
    alignments = []
    
    # 1. 电子病历等级评审检测 (EMR Leveling)
    emr_std = ontology.get("domains", {}).get("EMR_Leveling", {})
    indicators = emr_std.get("key_indicators", {})
    
    found_any = False
    for category, keywords in indicators.items():
        matched = [k for k in keywords if k in content]
        if matched:
            alignments.append(f"符合{category}相关要求: {', '.join(matched)}")
            found_any = True
        else:
            # 只有当文档明确提到评级时，才报告缺口
            if "评级" in content or "评审" in content or "等级" in content:
                gaps.append(f"缺少{category}核心能力描述（评级关键点）")

    # 2. 战略趋势对齐 (Strategic Trends)
    future_tech = ontology.get("domains", {}).get("Future_Healthcare", {})
    themes = future_tech.get("themes", [])
    
    matched_themes = [t for t in themes if t in content or t.lower() in content.lower()]
    for theme in matched_themes:
        impact = future_tech.get("strategic_impact", {}).get(theme, "战略技术应用")
        alignments.append(f"前瞻性对齐: {theme} ({impact})")

    # 3. 政策映射 (Policy Mapping)
    policy_map = ontology.get("policy_mapping", {})
    for tech, impact in policy_map.items():
        if tech in content or tech.lower() in content.lower():
            alignments.append(f"政策价值: {tech} -> {impact}")

    return {
        "alignments": alignments,
        "gaps": gaps if found_any else [] # 只在有相关语境时显示缺口
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Medical Standard Aligner')
    parser.add_argument('--input', default='extracted_content_part1.json')
    parser.add_argument('--output', default='compliance_analysis.json')
    args = parser.parse_args()
    
    base_dir = Path(__file__).parent.parent
    ontology_path = base_dir / "references" / "healthcare_ontology.json"
    
    if not ontology_path.exists():
        print(f"❌ 找不到本体文件: {ontology_path}")
        return

    with open(ontology_path, "r", encoding="utf-8") as f:
        ontology = json.load(f)
        
    with open(args.input, "r", encoding="utf-8") as f:
        documents = json.load(f)
        
    results = {}
    for doc in documents:
        results[doc['id']] = check_compliance(doc['content'], ontology)
        
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 医疗标准对齐分析完成: {args.output}")

if __name__ == "__main__":
    main()
