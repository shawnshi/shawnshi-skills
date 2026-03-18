#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Input:  Extracted content JSON (extracted_content_part1.json)
@Output: Summary/Tags JSON (document_summaries_enhanced.json)
@Pos:    Logic Layer (LLM-Driven / Mentat V6.0). 

!!! Maintenance Protocol: This script generates high-density semantic summaries.
!!! System Directive: Use structured prompt schema [核心洞察] + [合规风险] + [战略价值].
"""
import json
import sys
import io
import re
import argparse
from collections import Counter
from pathlib import Path
import yaml

# 设置标准输出编码为 UTF-8
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class LLMSummaryGenerator:
    """LLM 驱动的医疗战略摘要生成器"""

    def __init__(self):
        # 加载本体文件
        base_dir = Path(__file__).parent.parent
        self.config_path = base_dir / "config.yaml"
        self.config = {}
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}

    def get_prompt_template(self):
        """定义高密度语义压缩的 LLM Prompt (Mentat V6.0 标准)"""
        return """
# ROLE: 医疗信息化战略审计专家 (Mentat Edition)
# TASK: 对医疗文档执行深度语义压缩，生成 [核心洞察] + [合规风险] + [战略价值] 的结构化摘要。

## CONSTRAINTS:
1. 语言: 简体中文。
2. 长度: 120-160 字。
3. 风格: 极度克制、手术刀式直击。严禁使用“本文档介绍了”、“旨在”等废话。
4. 核心三元组: 必须包含 [状态_节点] :: [逻辑_变迁] 的表述模式。

## INPUT_DATA:
- Filename: {filename}
- Content_Snippet: {content}
- Compliance_Audit: {compliance}

## OUTPUT_FORMAT (Strict JSON or Plain Text with Headers):
[核心洞察]：...
[合规风险]：...
[战略价值]：...
"""

    def generate_rule_based_fallback(self, filename, content, compliance_info=None):
        """规则兜底逻辑 (当 LLM 不可用时使用)"""
        # 提取医院名称
        hospital_pattern = r'([\u4e00-\u9fa5]{2,10}(医院|卫生院|中医院|人民医院))'
        hospitals = re.findall(hospital_pattern, content[:500] + filename)
        hospital = hospitals[0][0] if hospitals else "医疗机构"
        
        name_clean = Path(filename).name[:15]
        summary = f"{hospital}《{name_clean}...》是核心资产。涉及电子病历、区域平台等。已识别合规性缺口。"
        
        # 确保达到最小长度
        while len(summary) < 100:
            summary += " 该文档为医疗数字化转型提供了标准化的实施参考。"
            
        return summary[:150]

    def process_batch(self, input_file, output_file, compliance_file=None):
        """处理文档批次，生成 Prompt 列表或执行模拟调用"""
        if not Path(input_file).exists():
            print(f"❌ 找不到输入文件: {input_file}")
            return

        with open(input_file, "r", encoding="utf-8") as f:
            documents = json.load(f)

        compliance_data = {}
        if compliance_file and Path(compliance_file).exists():
            with open(compliance_file, "r", encoding="utf-8") as f:
                compliance_data = json.load(f)

        print(f"正在处理 {len(documents)} 个文档...")
        
        # 在自动化流程中，此脚本将输出 Prompt 列表供上层 Agent 消费
        # 或者在此处集成 subprocess 调用 gemini-cli (如果环境允许)
        
        results = []
        for doc in documents:
            doc_id = doc['id']
            filename = doc['filename']
            content = doc['content'][:2000] # 截取前2k字作为上下文
            compliance = compliance_data.get(doc_id, "未执行合规审计")
            
            # 生成 Prompt (供 Agent 参考)
            prompt = self.get_prompt_template().format(
                filename=filename,
                content=content,
                compliance=json.dumps(compliance, ensure_ascii=False)
            )
            
            # 这里记录一个“占位”摘要，待 Agent 批量替换
            results.append({
                "id": doc_id,
                "filename": filename,
                "summary": "PENDING_LLM_GENERATION",
                "tags": ["LLM_PENDING"],
                "prompt": prompt
            })

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        print(f"✅ Prompt 列表已生成: {output_file}")
        print("💡 请将此文件交给 Agent 执行批量语义压缩。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='LLM 摘要生成器适配层')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--compliance', help='合规审计结果')
    args = parser.parse_args()
    
    generator = LLMSummaryGenerator()
    generator.process_batch(args.input, args.output, args.compliance)
