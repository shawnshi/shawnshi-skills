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

def generate_strategic_audit(summaries_file, output_file):
    """分析文档集合并生成战略审计报告"""
    
    if not Path(summaries_file).exists():
        print(f"❌ 找不到摘要文件: {summaries_file}")
        return

    with open(summaries_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_docs = len(data)
    all_tags = []
    doc_types = Counter()
    
    for doc in data:
        all_tags.extend(doc.get('tags', []))
        
        # 简单从摘要中识别类型（实际项目中可从元数据获取）
        summary = doc.get('summary', '')
        if '评级' in summary or '评审' in summary:
            doc_types['等级评审相关'] += 1
        elif '规划' in summary or '方案' in summary:
            doc_types['战略规划相关'] += 1
        elif '接口' in summary or '标准' in summary:
            doc_types['技术标准相关'] += 1
        else:
            doc_types['一般业务文档'] += 1

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
    
    # 硬编码一些2026年的战略关键词
    strategic_themes = ['ACI', '生成式AI', '数据要素', '五级评级', '互联互通五级乙等']
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
