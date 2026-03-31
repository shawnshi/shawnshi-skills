# -*- coding: utf-8 -*-
import sys, os
from pathlib import Path

# 初始化环境
_ROOT = Path(r"D:\OneDrive\Desktop\slide-blocks")
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "engine"))

import engine.assemble_template as assemble_template
from engine.assemble_template import assemble

# 配置模板与输出
assemble_template.TEMPLATE_PATH = _ROOT / "模板" / "蓝色商务（浅色底）.pptx"
output_name = "卫宁健康AI战略与实践全景汇报_2026_浅色版"

PLAN = [
    # --- 章节一：公司简介 ---
    {"template_page": 1, "replace_title": "卫宁健康 AI 战略与实践全景汇报"},
    {"src": _ROOT / "素材/从理念到实践：探析医院数字化转型之路.240914.pptx", "page": 2, "replace_title": "卫宁健康：驱动医疗高质量发展"},
    {"src": _ROOT / "素材/The Introduction of Winning Health.241108.pptx", "page": 7, "replace_title": "全国化服务体系：扎根本地，贴身服务"},
    {"src": _ROOT / "素材/从理念到实践：探析医院数字化转型之路.240914.pptx", "page": 6, "replace_title": "数字化转型框架：从信息化迈向数智化"},
    {"src": _ROOT / "素材/从理念到实践：探析医院数字化转型之路.240914.pptx", "page": 24, "replace_title": "整合型医疗体系：全病程资源统筹"},

    # --- 章节二：AI 整体策略 ---
    {"template_page": 2, "replace_title": "AI 整体策略：构建 AI 原生医院"},
    {"src": _ROOT / "素材/北大医疗AI规划交流20260303.pptx", "page": 5, "replace_title": "AI 医院架构蓝图：意图驱动的全域智能"},
    {"src": _ROOT / "素材/北大医疗AI规划交流20260303.pptx", "page": 14, "replace_title": "底座重构：构建新一代 AI 原生操作系统"},
    {"src": _ROOT / "素材/北大医疗AI规划交流20260317.pptx", "page": 17, "replace_title": "医疗语义层 (MSL)：消除幻觉的核心壁垒"},
    {"src": _ROOT / "素材/北大医疗AI规划交流20260317.pptx", "page": 32, "replace_title": "核心对齐：医学术语标准化体系建设"},
    {"src": _ROOT / "素材/北大医疗AI规划交流20260317.pptx", "page": 30, "replace_title": "演进蓝图：分阶段迈向全面 AI 原生"},
    {"src": _ROOT / "素材/2025年度PPT素材汇总（浅色底）.pptx", "page": 4, "replace_title": "战略主动权：AI 作为国家核心竞争力"},
    {"src": _ROOT / "素材/2025年度PPT素材汇总（浅色底）.pptx", "page": 5, "replace_title": "政策指引：加速拥抱智能医疗时代"},

    # --- 章节三：典型场景 ---
    {"template_page": 2, "replace_title": "典型场景：AI 深度赋能业务闭环"},
    {"src": _ROOT / "素材/天津市儿童医院十五五信息化合作20250820.pptx", "page": 28, "replace_title": "演进路径：从生成模型到 Agent 智能体"},
    {"src": _ROOT / "素材/CHIMA2024大会-医院高质量数字化转型实践-卫宁.240510.pptx", "page": 11, "replace_title": "智慧管理：管理与临床的一体化智能闭环"},
    {"src": _ROOT / "素材/从理念到实践：探析医院数字化转型之路.240914.pptx", "page": 23, "replace_title": "WiNEX Copilot：核心业务系统全场景落地"},
    {"src": _ROOT / "素材/2025年度PPT素材汇总（浅色底）.pptx", "page": 75, "replace_title": "交互革命：Zero-UI 驱动的医疗办公范式"},
    {"src": _ROOT / "素材/2025年度PPT素材汇总（浅色底）.pptx", "page": 89, "replace_title": "知识中心：构建具备临床思维的 Agent 大脑"},
    {"src": _ROOT / "素材/2025年度PPT素材汇总（浅色底）.pptx", "page": 95, "replace_title": "临床智能：肿瘤精准分期与决策支持"},
    {"src": _ROOT / "素材/2025年度PPT素材汇总（浅色底）.pptx", "page": 96, "replace_title": "风险预警：VTE 智能评估与动态闭环"},

    # --- 章节四：典型案例 ---
    {"template_page": 2, "replace_title": "典型案例：标杆医院的先行实践"},
    {"src": _ROOT / "素材/The Introduction of Winning Health.241108.pptx", "page": 19, "replace_title": "标杆案例：北京大学人民医院数字化精进"},
    {"src": _ROOT / "素材/哈密市医疗健康数智融合发展规划建议20260203.pptx", "page": 28, "replace_title": "创新实践：住院查房智能语音录入"},
    
    {"template_page": 5} # 封底
]

if __name__ == "__main__":
    assemble(PLAN, output_name)
