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

    def _call_gemini(self, prompt, api_key):
        """调用 Gemini 基座模型，带自动重试机制"""
        import google.generativeai as genai
        import time
        genai.configure(api_key=api_key)
        # Using a reliable model like gemini-2.5-flash
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                if response.text:
                    return response.text
            except Exception as e:
                print(f"⚠️ API 调用失败 (尝试 {attempt+1}/3): {e}")
                time.sleep(2 ** attempt)
        return None

    def process_batch(self, input_file, output_file, compliance_file=None):
        """处理文档批次，原生调用 LLM 进行压缩"""
        import os
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        if not Path(input_file).exists():
            print(f"❌ 找不到输入文件: {input_file}")
            sys.exit(1)

        with open(input_file, "r", encoding="utf-8") as f:
            documents = json.load(f)

        compliance_data = {}
        if compliance_file and Path(compliance_file).exists():
            with open(compliance_file, "r", encoding="utf-8") as f:
                compliance_data = json.load(f)

        print(f"正在处理 {len(documents)} 个文档...")
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ 未检测到 GEMINI_API_KEY 环境变量。将回退到规则引擎！")

        results = []
        
        def _process_single(doc):
            doc_id = doc['id']
            filename = doc['filename']
            content = doc['content'][:2000] # 截取前2k字作为上下文
            compliance = compliance_data.get(doc_id, "未执行合规审计")
            
            prompt = self.get_prompt_template().format(
                filename=filename,
                content=content,
                compliance=json.dumps(compliance, ensure_ascii=False)
            )
            
            summary = None
            tags = []
            if api_key:
                raw_res = self._call_gemini(prompt, api_key)
                if raw_res:
                    summary = raw_res.strip()
                    tags = ["Mentat_Auto_LLM"]
                    
            if not summary:
                # 规则兜底
                summary = self.generate_rule_based_fallback(filename, content, compliance)
                tags = ["RULES_FALLBACK"]
                
            return {
                "id": doc_id,
                "filename": filename,
                "summary": summary,
                "tags": tags
            }

        # 异步并发执行 API 请求，最大并发限流控制在 4 避免 429 Error
        max_workers = 4 if api_key else 8
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_process_single, doc) for doc in documents]
            for future in as_completed(futures):
                try:
                    res = future.result()
                    results.append(res)
                    print(f"✓ 生成完成: {res['filename']} [{res['tags'][0]}]")
                except Exception as e:
                    print(f"❌ 严重内部错误: {e}")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 生成完毕并落盘至: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='LLM 摘要生成器适配层')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--compliance', help='合规审计结果')
    args = parser.parse_args()
    
    generator = LLMSummaryGenerator()
    generator.process_batch(args.input, args.output, args.compliance)
