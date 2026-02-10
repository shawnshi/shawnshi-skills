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

        # 医疗信息化关键词库（扩展版）
        self.keywords_dict = {
            # 系统类
            '电子病历': ['电子病历', 'EMR', '病历系统', '电子病案'],
            'HIS系统': ['HIS', '医院信息系统', 'Hospital Information System'],
            'PACS系统': ['PACS', '影像归档', '医学影像', '影像系统'],
            'LIS系统': ['LIS', '检验信息系统', '实验室信息'],
            'RIS系统': ['RIS', '放射信息系统', '放射科'],

            # 评级认证
            '电子病历评级': ['五级', '四级', '三级', '评级', '分级评价', '评审'],
            '智慧医院': ['智慧医院', '智慧管理', '智慧服务', '智慧医疗'],
            '互联互通': ['互联互通', '标准化', '测评', '信息共享'],

            # 中医特色
            '中医信息化': ['中医', '中西医结合', '中药', '辨证论治', '中医馆'],
            '数字中医': ['数字中医', '中医数字化', '智慧中医'],

            # 技术应用
            '人工智能': ['AI', '人工智能', '机器学习', '深度学习', '大模型', 'ACI', 'Ambient Clinical Intelligence'],
            '大数据': ['大数据', '数据分析', '数据挖掘', 'BI'],
            '云计算': ['云计算', '云平台', '云HIS', '上云'],
            '物联网': ['物联网', 'IoT', '智能设备', '传感器'],

            # 数据治理
            '数据治理': ['数据治理', '数据质量', '主数据', 'MDM', '数据要素'],
            '数据安全': ['数据安全', '信息安全', '网络安全', '隐私保护'],
            '数据标准': ['数据标准', '编码规范', 'HL7', 'FHIR'],

            # 业务场景
            '医联体': ['医联体', '医共体', '分级诊疗', '远程医疗'],
            '互联网医疗': ['互联网医院', '在线诊疗', '远程问诊', '移动医疗'],
            '智能诊断': ['辅助诊断', 'CDSS', '临床决策', '智能推荐'],
            '药品管理': ['药品管理', '处方流转', '药库', '药房'],
            '运营管理': ['运营管理', 'HRP', '绩效', '成本核算'],

            # 建设内容
            '信息化规划': ['规划', '顶层设计', '蓝图', '信息化建设'],
            '系统集成': ['集成平台', 'ESB', '接口', '数据交换', 'FHIR', 'HL7'],
            '升级改造': ['升级', '改造', '优化', '迁移'],
            '技术架构': ['架构', '微服务', '中台', '平台化'],
            '标准规范': ['标准', '规范', '指南', '白皮书'],
        }

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
        content_sample = content[:2000]

        # 分类规则
        if any(word in filename for word in ['规划', '方案', '蓝图']):
            return '信息化规划方案'
        elif any(word in filename for word in ['评级', '评审', '五级', '四级', '三级']):
            return '电子病历评级'
        elif any(word in filename for word in ['标准', '规范', '指南', '白皮书']):
            return '技术标准规范'
        elif any(word in filename for word in ['调研', '考察', '访谈', '报告']):
            return '调研考察报告'
        elif any(word in filename for word in ['交流', '汇报', 'PPT']):
            return '技术交流汇报'
        elif any(word in filename for word in ['合作', '协议', '备忘录']):
            return '合作协议文件'
        elif any(word in filename for word in ['接口', '集成', 'API', 'HL7']):
            return '系统集成接口'
        elif any(word in filename for word in ['数据', 'Data', 'Schema']):
            return '数据结构文档'
        elif any(word in filename for word in ['功能', 'Specification', '需求']):
            return '系统功能规范'
        else:
            return '医疗信息化文档'

    def extract_keywords_tfidf(self, content, filename, top_n=10):
        """使用简化的TF-IDF提取关键词"""
        # 分词（简单按字符）
        words = []

        # 从内容中提取关键词
        for category, keywords in self.keywords_dict.items():
            for keyword in keywords:
                if keyword in content or keyword.lower() in content.lower():
                    words.append(category)

        # 从文件名提取
        for category, keywords in self.keywords_dict.items():
            for keyword in keywords:
                if keyword in filename or keyword.lower() in filename.lower():
                    words.append(category)
                    words.append(category)  # 文件名中的关键词权重加倍

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
                if len(tags) >= 5:
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

        # 生成摘要（100-150字）
        summary = generator.generate_summary(filename, content, comp_info)

        # 生成标签
        tags = generator.generate_tags(filename, content)

        results.append({
            'id': file_id,
            'filename': filename,
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
