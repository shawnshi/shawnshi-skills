#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Input:  Extracted content JSON (extracted_content_part1.json)
@Output: Summary/Tags JSON (document_summaries_enhanced.json)
@Pos:    Logic Layer (Deterministic/Template-based). 

!!! Maintenance Protocol: This is a fast, rule-based alternative to the LLM generator.
!!! Keep medical keyword lists synchronized with garmin-health-analysis references.

优化版摘要和标签生成器
- 摘要长度严格控制在100-150字
- 智能关键词提取
- 基于内容的精准摘要生成
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


class SmartSummaryGenerator:
    """智能摘要生成器"""

    def __init__(self):
        # 加载本体文件
        base_dir = Path(__file__).parent.parent
        ontology_path = base_dir / "references" / "healthcare_ontology.json"
        self.ontology = {}
        if ontology_path.exists():
            with open(ontology_path, "r", encoding="utf-8") as f:
                self.ontology = json.load(f)

        # 从 config.yaml 加载配置
        config_path = base_dir / "config.yaml"
        self.config = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}

        # 停用词（用于关键词提取）
        self.stop_words = {
            '医院', '系统', '信息', '建设', '管理', '服务', '项目', '方案',
            '文档', '介绍', '说明', '汇报', '报告', '材料', '内容', '相关',
            '主要', '重要', '基本', '关于', '进行', '实现', '提供', '支持',
            '本文档', '本方案', '该项目', '通过', '采用', '利用', '基于'
        }

    def extract_entities(self, filename, content):
        """提取关键实体信息"""
        entities = {
            'hospital': None,
            'project': None,
            'date': None,
            'location': None
        }

        # 提取医院名称
        hospital_pattern = r'([\u4e00-\u9fa5]{2,10}(医科大学|医学院|医院|卫生院|中医院|人民医院|中心医院))'
        hospitals = re.findall(hospital_pattern, content[:1000])
        if hospitals:
            entities['hospital'] = hospitals[0][0]
        else:
            # 从文件名提取
            hospitals = re.findall(hospital_pattern, filename)
            if hospitals:
                entities['hospital'] = hospitals[0][0]

        # 提取日期
        date_pattern = r'(202[0-9])[\.-]?(0[1-9]|1[0-2])[\.-]?(0[1-9]|[12][0-9]|3[01])'
        dates = re.findall(date_pattern, filename)
        if dates:
            entities['date'] = ''.join(dates[0])

        # 提取地点
        location_pattern = r'(北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆|香港|澳门|台湾)'
        locations = re.findall(location_pattern, filename + content[:500])
        if locations:
            entities['location'] = locations[0]

        return entities

    def classify_document(self, filename, content):
        """智能分类文档类型"""
        filename_lower = filename.lower()
        
        doc_categories = self.config.get("document_types", [])
        if doc_categories:
            for doc_type in doc_categories:
                name = doc_type.get("name", "")
                keywords = doc_type.get("keywords", [])
                if any(word in filename for word in keywords):
                    return name
            return '一般业务文档'

        # Fallback to old behavior if config not loaded properly
        if any(word in filename for word in ['规划', '方案', '蓝图', '顶层设计']):
            return '战略规划方案'
        elif any(word in filename for word in ['评级', '评审', '五级', '四级', '互联互通', '测评']):
            return '评级认证文档'
        elif any(word in filename for word in ['标准', '规范', '指南', '白皮书', '定义']):
            return '技术标准规范'
        elif any(word in filename for word in ['调研', '考察', '访谈', '报告', '分析']):
            return '调研考察报告'
        elif any(word in filename for word in ['交流', '汇报', 'PPT', '演讲', '分享']):
            return '技术交流汇报'
        elif any(word in filename for word in ['合作', '协议', '备忘录', '合同']):
            return '商务合作协议'
        elif any(word in filename for word in ['接口', '集成', 'API', 'HL7', 'FHIR']):
            return '系统集成接口'
        elif any(word in filename for word in ['数据', 'Data', 'Schema', '字典', '元数据']):
            return '数据治理文档'
        elif any(word in filename for word in ['功能', 'Specification', '需求', 'SRS']):
            return '系统功能规范'
        elif any(word in filename for word in ['实施', '部署', '安装', '配置', '手册', '操作']):
            return '实施运维文档'
        elif any(word in filename for word in ['研发', '设计', '架构', '开发', '代码']):
            return '产品研发文档'
        else:
            return '一般业务文档'

    def extract_keywords_tfidf(self, content, filename, top_n=10):
        """使用简化的TF-IDF提取关键词"""
        # 分词（简单按字符）
        words = []
        
        medical_keywords = self.config.get("medical_keywords", {})

        # 从内容中提取关键词
        for category, keywords in medical_keywords.items():
            for keyword in keywords:
                if keyword in content or keyword.lower() in content.lower():
                    words.append(keyword)

        # 从文件名提取
        for category, keywords in medical_keywords.items():
            for keyword in keywords:
                if keyword in filename or keyword.lower() in filename.lower():
                    words.append(keyword)
                    words.append(keyword)  # 文件名中的关键词权重加倍

        # 统计词频
        word_freq = Counter(words)

        # 返回top N关键词
        return [word for word, count in word_freq.most_common(top_n)]

    def generate_summary(self, filename, content, compliance_info=None):
        """生成100-150字的智能摘要，包含政策对齐洞察"""
        # 提取实体信息
        entities = self.extract_entities(filename, content)

        # 文档分类
        doc_type = self.classify_document(filename, content)

        # 提取关键词
        keywords = self.extract_keywords_tfidf(content, filename, top_n=8)

        # 构建摘要
        summary_parts = []

        # 第一部分：主体描述
        if entities['hospital']:
            summary_parts.append(f"{entities['hospital']}")
        
        name_clean = Path(filename).name[:20]
        summary_parts.append(f"《{name_clean}...》是关于{doc_type}的专业资产。")

        # 第二部分：核心内容与政策对齐
        if compliance_info and compliance_info.get("alignments"):
            # 提取最重要的一个对齐点
            policy_insight = compliance_info["alignments"][0]
            summary_parts.append(f"核心洞察：{policy_insight}。")
        elif keywords:
            summary_parts.append(f"重点涵盖{keywords[0]}、{keywords[1] if len(keywords)>1 else ''}等领域。")

        # 第三部分：战术缺口预警
        if compliance_info and compliance_info.get("gaps"):
            gap = compliance_info["gaps"][0]
            summary_parts.append(f"风险提示：{gap}。")
        else:
            summary_parts.append("该文档为医疗数字化转型提供了标准化的实施参考。")

        # 组合摘要
        summary = ''.join(summary_parts)

        # 长度控制 (100-150字)
        if len(summary) > 150:
            summary = summary[:147] + '...'
        
        while len(summary) < 100:
            padding = " 本文档结合行业实际需求，提供了系统化的技术解决方案和落地路径指引。"
            if len(summary) + len(padding) > 150:
                summary += padding[:150-len(summary)]
                break
            summary += padding

        return summary

    def generate_tags(self, filename, content):
        """生成5个分层标签"""
        # 提取关键词
        keywords = self.extract_keywords_tfidf(content, filename, top_n=10)

        # 文档分类
        doc_type = self.classify_document(filename, content)

        # 构建标签
        tags = []

        # 一级标签：领域分类（必选）
        tags.append('医疗信息化')

        # 二级标签：从关键词中选择
        for kw in keywords[:4]:
            if kw not in tags:
                tags.append(kw)
                if len(tags) >= 5:
                    break

        # 如果标签不足5个，补充通用标签
        generic_tags = ['数字化转型', '智慧医院', '系统建设', '技术标准', '医疗服务']
        for tag in generic_tags:
            if tag not in tags:
                tags.append(tag)
                if len(tags) >= 8:
                    break

        return tags[:5]


def main():
    parser = argparse.ArgumentParser(description='优化版摘要和标签生成器')
    parser.add_argument('--input', required=True, help='输入的提取内容JSON文件')
    parser.add_argument('--output', required=True, help='输出的摘要JSON文件')
    parser.add_argument('--compliance', help='医疗标准对齐分析JSON文件')
    args = parser.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output)
    
    compliance_data = {}
    if args.compliance and Path(args.compliance).exists():
        print(f"正在加载合规性分析: {args.compliance}")
        with open(args.compliance, "r", encoding="utf-8") as f:
            compliance_data = json.load(f)

    # 读取提取的内容
    print("正在读取文档内容...")
    with open(input_file, "r", encoding="utf-8") as f:
        documents = json.load(f)

    print(f"共有 {len(documents)} 个文档需要生成摘要和标签\n")

    # 初始化生成器
    generator = SmartSummaryGenerator()

    # 生成摘要和标签
    results = []

    for i, doc in enumerate(documents, 1):
        file_id = doc['id']
        filename = doc['filename']
        content = doc['content']
        
        # 获取合规性信息
        comp_info = compliance_data.get(file_id)

        # 获取文档类型
        doc_type = generator.classify_document(filename, content)

        # 生成摘要（100-150字）
        summary = generator.generate_summary(filename, content, comp_info)

        # 生成标签
        tags = generator.generate_tags(filename, content)

        results.append({
            'id': file_id,
            'filename': filename,
            'doc_type': doc_type,
            'summary': summary,
            'tags': tags
        })

        if i <= 5 or i % 100 == 0:
            print(f"[{i}/{len(documents)}] ✓ {filename}")
            print(f"  摘要长度: {len(summary)} 字")
            if i <= 3:
                print(f"  摘要: {summary}")
                print(f"  标签: {', '.join(tags)}\n")

    # 保存结果
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print("摘要和标签生成完成！")
    print("="*60)
    print(f"✓ 处理文档: {len(results)} 个")
    print(f"✓ 输出文件: {output_file}")
    print("="*60)

    # 统计摘要长度分布
    lengths = [len(r['summary']) for r in results]
    print(f"\n摘要长度统计:")
    print(f"  最短: {min(lengths)} 字")
    print(f"  最长: {max(lengths)} 字")
    print(f"  平均: {sum(lengths)//len(lengths)} 字")
    print(f"  符合要求(100-150字): {sum(1 for l in lengths if 100 <= l <= 150)} 个 ({sum(1 for l in lengths if 100 <= l <= 150)*100//len(lengths)}%)")


if __name__ == "__main__":
    main()
