#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Input:  document_summaries_enhanced.json
@Output: Strategic Portfolio Audit (Markdown/JSON)
@Pos:    Intelligence Layer. Macro-analysis of document collections.

!!! Maintenance Protocol: Update strategic themes based on annual healthcare IT trends (e.g. ACI, EMR Grade 5).
"""

import json
import sys
import argparse
from datetime import datetime
from collections import Counter
from pathlib import Path
import yaml

def generate_strategic_audit(summaries_file, output_file):
    """分析文档集合并生成战略审计报告"""
    
    if not Path(summaries_file).exists():
        print(f"❌ 找不到摘要文件: {summaries_file}")
        return

    # 读取 config.yaml
    base_dir = Path(__file__).parent.parent
    config_path = base_dir / "config.yaml"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    with open(summaries_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_docs = len(data)
    all_tags = []
    doc_types = Counter()
    
    for doc in data:
        all_tags.extend(doc.get('tags', []))
        
        # 优先使用元数据中的类型
        if 'doc_type' in doc:
            doc_types[doc['doc_type']] += 1
        else:
            # 简单从摘要中识别类型（兼容旧版）
            summary = doc.get('summary', '')
            matched_type = '一般业务文档'
            for dt in config.get('document_types', []):
                name = dt.get('name', '')
                keywords = dt.get('keywords', [])
                if any(kw in summary for kw in keywords):
                    matched_type = name
                    break
            
            # 后备兼容
            if matched_type == '一般业务文档':
                if '评级' in summary or '评审' in summary:
                    matched_type = '等级评审相关'
                elif '规划' in summary or '方案' in summary:
                    matched_type = '战略规划相关'
            
            doc_types[matched_type] += 1

    tag_counts = Counter(all_tags)
    top_tags = tag_counts.most_common(10)

    # 报告生成 (Markdown)
    report = []
    report.append(f"# 医疗信息化文档资产战略审计报告 (SHA)")
    report.append(f"\n> **审计日期**: {datetime.now().strftime('%Y-%m-%d')}")
    report.append(f"> **样本规模**: {total_docs} 份文档")
    
    report.append(f"\n## 1. 资产分布概览")
    for doc_type, count in doc_types.items():
        pct = (count / total_docs) * 100
        report.append(f"- **{doc_type}**: {count} 份 ({pct:.1f}%)")

    report.append(f"\n## 2. 语义焦点 (Top 10 标签)")
    for tag, count in top_tags:
        report.append(f"- {tag}: {count} 次出现")

    report.append(f"\n## 3. 战略缺口分析 (Gap Analysis)")
    
    # 动态加载战略关键词 (从 config.yaml 提取核心前沿趋势)
    strategic_themes = []
    med_kws = config.get('medical_keywords', {})
    if med_kws:
        # 取技术、数据治理和评级的前几个选项作为战略追踪核心目标
        for cat in ['technologies', 'data_governance', 'certifications']:
            strategic_themes.extend(med_kws.get(cat, [])[:3])
    else:
        strategic_themes = ['人工智能', '数据治理', '评级']
    
    found_themes = [t for t in strategic_themes if any(t in str(data) for t in strategic_themes)]
    missing_themes = [t for t in strategic_themes if t not in found_themes]
    
    if missing_themes:
        report.append(f"⚠️ **检测到战略盲区**: 资产库中缺乏关于以下领域的深度储备：")
        for theme in missing_themes:
            report.append(f"  - {theme}")
    else:
        report.append(f"✅ **战略对齐**: 资产库与 2026 医疗信息化主流趋势高度契合。")

    report.append(f"\n## 4. 行动建议")
    report.append("1. **知识补强**: 针对上述战略盲区，建议补充相关行业白皮书或成功案例.")
    report.append("2. **元数据治理**: 建议对“一般业务文档”进行二次精细化分类.")
    top_tag_name = top_tags[0][0] if top_tags else '核心'
    report.append(f"3. **资产活化**: 建议将高频出现的“{top_tag_name}”领域文档整理为专题知识库.")
    
    # 自动生成建议的目录结构
    report.append(f"\n## 5. 建议归档结构 (Auto-Generated Taxonomy)")
    report.append("```")
    report.append("Knowledge_Base/")
    
    # 基于文档类型的一级目录
    for dtype, _ in doc_types.most_common():
        report.append(f"├── {dtype}/")
        # 基于标签的二级目录建议
        relevant_tags = [t for t, c in tag_counts.most_common(5) if t not in dtype]
        if relevant_tags:
            for rt in relevant_tags[:2]:
                report.append(f"│   ├── {rt}/")
    report.append("```")

    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('\n'.join(report))
    
    print(f"✅ 战略审计报告已生成: {output_path.absolute()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Strategic Portfolio Audit (SHA)')
    parser.add_argument('--input', default='document_summaries_enhanced.json', help='摘要文件')
    parser.add_argument('--output', default='STRATEGIC_AUDIT.md', help='输出报告文件名')
    args = parser.parse_args()
    
    generate_strategic_audit(args.input, args.output)
