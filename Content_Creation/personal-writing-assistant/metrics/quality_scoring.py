#!/usr/bin/env python3
"""
Quality Scoring for Personal Writing Assistant
量化评估文章质量的工具
"""

import re
import jieba
import jieba.posseg as pseg
from pathlib import Path
from typing import Dict, List, Tuple
from collections import Counter


class QualityScorer:
    """文章质量评分器"""

    # 黑话词典（持续更新）
    JARGON_BLACKLIST = [
        '赋能', '闭环', '抓手', '赛道', '打法',
        '生态', '颗粒度', '心智', '破圈', '种草',
        '降维打击', '底层逻辑', '组合拳', '杀手锏',
        '深度赋能', '战略闭环', '精准抓手', '核心抓手',
        '顶层设计', '战略部署', '全面落实', '扎实推进'
    ]

    # 冗余副词
    REDUNDANT_ADVERBS = [
        '深刻地', '彻底地', '全面地', '系统地', '充分地',
        '显著地', '明显地', '清晰地', '有效地', '积极地'
    ]

    def __init__(self, article_text: str):
        """
        初始化评分器

        Args:
            article_text: 文章文本
        """
        self.text = article_text
        self.sentences = self._split_sentences(article_text)
        self.words = list(jieba.cut(article_text))
        self.pos_tagged = list(pseg.cut(article_text))

    def _split_sentences(self, text: str) -> List[str]:
        """分句"""
        # 按句号、问号、感叹号分句
        sentences = re.split(r'[。！？\n]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def score_verb_density(self) -> Dict:
        """
        计算动词密度

        Returns:
            {
                'score': 0-10分,
                'verb_count': 动词数量,
                'adj_count': 形容词数量,
                'ratio': 动词/形容词比例,
                'details': 详细说明
            }
        """
        verb_count = sum(1 for word, pos in self.pos_tagged if pos.startswith('v'))
        adj_count = sum(1 for word, pos in self.pos_tagged
                       if pos.startswith('a') or pos.startswith('ad'))

        ratio = verb_count / max(adj_count, 1)

        # 评分：比例 >= 3 得满分，< 1 不及格
        if ratio >= 3:
            score = 10
        elif ratio >= 2:
            score = 8
        elif ratio >= 1.5:
            score = 6
        elif ratio >= 1:
            score = 4
        else:
            score = 2

        return {
            'score': score,
            'verb_count': verb_count,
            'adj_count': adj_count,
            'ratio': round(ratio, 2),
            'details': f"动词/形容词比例 {ratio:.2f} ({'优秀' if score >= 8 else '良好' if score >= 6 else '需改进'})"
        }

    def detect_jargon(self) -> Dict:
        """
        检测黑话

        Returns:
            {
                'score': 0-10分,
                'jargon_found': 找到的黑话列表,
                'count': 黑话出现次数,
                'details': 详细说明
            }
        """
        jargon_found = []
        for jargon in self.JARGON_BLACKLIST:
            count = self.text.count(jargon)
            if count > 0:
                jargon_found.append((jargon, count))

        total_jargon = sum(count for _, count in jargon_found)

        # 评分：0个黑话满分，每个黑话扣1分
        score = max(0, 10 - total_jargon)

        return {
            'score': score,
            'jargon_found': jargon_found,
            'count': total_jargon,
            'details': f"发现 {total_jargon} 处黑话" + (f": {', '.join(j for j, _ in jargon_found)}" if jargon_found else "")
        }

    def detect_redundant_adverbs(self) -> Dict:
        """
        检测冗余副词（伪装的形容词）

        Returns:
            {
                'score': 0-10分,
                'adverbs_found': 找到的冗余副词列表,
                'count': 出现次数
            }
        """
        adverbs_found = []
        for adv in self.REDUNDANT_ADVERBS:
            count = self.text.count(adv)
            if count > 0:
                adverbs_found.append((adv, count))

        total_adverbs = sum(count for _, count in adverbs_found)

        # 评分：每个冗余副词扣2分
        score = max(0, 10 - total_adverbs * 2)

        return {
            'score': score,
            'adverbs_found': adverbs_found,
            'count': total_adverbs,
            'details': f"发现 {total_adverbs} 处冗余副词" + (f": {', '.join(a for a, _ in adverbs_found)}" if adverbs_found else "")
        }

    def calculate_readability(self) -> Dict:
        """
        计算可读性（基于句子长度方差）

        Returns:
            {
                'score': 0-10分,
                'avg_length': 平均句长,
                'variance': 句长方差,
                'details': 详细说明
            }
        """
        if not self.sentences:
            return {'score': 0, 'avg_length': 0, 'variance': 0, 'details': '无有效句子'}

        lengths = [len(s) for s in self.sentences]
        avg_length = sum(lengths) / len(lengths)
        variance = sum((l - avg_length) ** 2 for l in lengths) / len(lengths)

        # 理想方差在100-400之间（有节奏但不极端）
        if 100 <= variance <= 400:
            score = 10
        elif 50 <= variance < 100 or 400 < variance <= 600:
            score = 7
        elif variance < 50:
            score = 4  # 过于单调
        else:
            score = 5  # 过于跳跃

        return {
            'score': score,
            'avg_length': round(avg_length, 1),
            'variance': round(variance, 1),
            'details': f"平均句长 {avg_length:.1f}，方差 {variance:.1f} ({'节奏良好' if score >= 8 else '节奏单调' if variance < 50 else '需优化'})"
        }

    def check_passive_voice(self) -> Dict:
        """
        检测被动语态（简化版：检测常见被动结构）

        Returns:
            {
                'score': 0-10分,
                'passive_count': 被动语态数量,
                'total_sentences': 总句子数,
                'percentage': 被动语态占比
            }
        """
        passive_patterns = ['被', '受到', '得到', '遭到', '获得']
        passive_count = 0

        for sentence in self.sentences:
            if any(pattern in sentence for pattern in passive_patterns):
                passive_count += 1

        percentage = (passive_count / len(self.sentences)) * 100 if self.sentences else 0

        # 评分：<10% 满分，每超过5%扣2分
        if percentage < 10:
            score = 10
        elif percentage < 20:
            score = 8
        elif percentage < 30:
            score = 6
        else:
            score = 4

        return {
            'score': score,
            'passive_count': passive_count,
            'total_sentences': len(self.sentences),
            'percentage': round(percentage, 1),
            'details': f"被动语态占比 {percentage:.1f}% ({'优秀' if score >= 8 else '偏高' if score < 6 else '需改进'})"
        }

    def check_bold_usage(self) -> Dict:
        """
        检查粗体使用（Markdown **text**）

        Returns:
            {
                'score': 0-10分,
                'bold_count': 粗体数量,
                'details': 详细说明
            }
        """
        bold_pattern = r'\*\*(.+?)\*\*'
        bold_matches = re.findall(bold_pattern, self.text)
        bold_count = len(bold_matches)

        # 理想：1-3处粗体
        if 1 <= bold_count <= 3:
            score = 10
        elif bold_count == 0:
            score = 7  # 没有重点
        elif 4 <= bold_count <= 5:
            score = 6
        else:
            score = 3  # 过度使用

        return {
            'score': score,
            'bold_count': bold_count,
            'details': f"粗体使用 {bold_count} 次 ({'适当' if 1 <= bold_count <= 3 else '过少' if bold_count == 0 else '过多'})"
        }

    def check_analyst_note(self) -> Dict:
        """
        检查【分析师手记】是否存在及质量

        Returns:
            {
                'score': 0-10分,
                'exists': 是否存在,
                'length': 长度,
                'has_assumptions': 是否包含假设说明,
                'details': 详细说明
            }
        """
        # 检测是否有【分析师手记】
        note_pattern = r'【分析师手记】(.+?)(?=\n##|\n---|\Z)'
        match = re.search(note_pattern, self.text, re.DOTALL)

        if not match:
            return {
                'score': 0,
                'exists': False,
                'length': 0,
                'has_assumptions': False,
                'details': '缺少【分析师手记】'
            }

        note_content = match.group(1)
        length = len(note_content)

        # 检查是否包含关键元素
        has_assumptions = '假设' in note_content or '前提' in note_content
        has_red_team = '红队' in note_content or '反方' in note_content or '失效' in note_content
        has_uncertainty = '不知道' in note_content or '不确定' in note_content or '需要' in note_content

        # 评分
        score = 0
        if length >= 150:
            score += 3
        elif length >= 100:
            score += 2
        else:
            score += 1

        if has_assumptions:
            score += 3
        if has_red_team:
            score += 2
        if has_uncertainty:
            score += 2

        return {
            'score': min(score, 10),
            'exists': True,
            'length': length,
            'has_assumptions': has_assumptions,
            'details': f"【分析师手记】长度 {length} 字 ({'完整' if score >= 8 else '基本' if score >= 5 else '不足'})"
        }

    def comprehensive_score(self) -> Dict:
        """
        综合评分

        Returns:
            {
                'total_score': 总分 (0-100),
                'grade': 等级,
                'dimensions': 各维度得分,
                'recommendations': 改进建议
            }
        """
        # 各维度评分
        verb_density = self.score_verb_density()
        jargon = self.detect_jargon()
        adverbs = self.detect_redundant_adverbs()
        readability = self.calculate_readability()
        passive = self.check_passive_voice()
        bold = self.check_bold_usage()
        analyst_note = self.check_analyst_note()

        # 权重
        weights = {
            'verb_density': 0.20,
            'jargon': 0.20,
            'adverbs': 0.15,
            'readability': 0.15,
            'passive': 0.10,
            'bold': 0.05,
            'analyst_note': 0.15
        }

        # 加权总分
        total_score = (
            verb_density['score'] * weights['verb_density'] +
            jargon['score'] * weights['jargon'] +
            adverbs['score'] * weights['adverbs'] +
            readability['score'] * weights['readability'] +
            passive['score'] * weights['passive'] +
            bold['score'] * weights['bold'] +
            analyst_note['score'] * weights['analyst_note']
        ) * 10

        # 等级
        if total_score >= 85:
            grade = 'A (优秀)'
        elif total_score >= 70:
            grade = 'B (良好)'
        elif total_score >= 60:
            grade = 'C (及格)'
        else:
            grade = 'D (不及格)'

        # 改进建议
        recommendations = []
        if verb_density['score'] < 6:
            recommendations.append(f"增加动词密度（当前比例 {verb_density['ratio']}，建议 > 2）")
        if jargon['score'] < 8:
            recommendations.append(f"删除黑话：{', '.join(j for j, _ in jargon['jargon_found'])}")
        if adverbs['score'] < 6:
            recommendations.append(f"删除冗余副词：{', '.join(a for a, _ in adverbs['adverbs_found'])}")
        if passive['score'] < 6:
            recommendations.append(f"减少被动语态（当前 {passive['percentage']:.1f}%，建议 < 20%）")
        if analyst_note['score'] < 5:
            recommendations.append("补充或完善【分析师手记】")

        return {
            'total_score': round(total_score, 1),
            'grade': grade,
            'dimensions': {
                '动词密度': verb_density,
                '黑话检测': jargon,
                '冗余副词': adverbs,
                '可读性': readability,
                '被动语态': passive,
                '粗体使用': bold,
                '分析师手记': analyst_note
            },
            'recommendations': recommendations
        }


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description='文章质量评分工具')
    parser.add_argument('file', help='文章文件路径（Markdown格式）')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    # 读取文件
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误：文件不存在 {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        article_text = f.read()

    # 评分
    scorer = QualityScorer(article_text)
    result = scorer.comprehensive_score()

    # 输出结果
    print(f"\n{'='*60}")
    print(f"文章质量评估报告")
    print(f"{'='*60}")
    print(f"\n总分：{result['total_score']}/100")
    print(f"等级：{result['grade']}")
    print(f"\n{'-'*60}")
    print("各维度得分：")
    print(f"{'-'*60}")

    for dimension, score_data in result['dimensions'].items():
        print(f"\n{dimension}：{score_data['score']}/10")
        print(f"  {score_data['details']}")
        if args.verbose and 'jargon_found' in score_data and score_data['jargon_found']:
            for jargon, count in score_data['jargon_found']:
                print(f"    - {jargon}: {count}次")

    if result['recommendations']:
        print(f"\n{'-'*60}")
        print("改进建议：")
        print(f"{'-'*60}")
        for i, rec in enumerate(result['recommendations'], 1):
            print(f"{i}. {rec}")

    print(f"\n{'='*60}\n")


if __name__ == '__main__':
    main()
