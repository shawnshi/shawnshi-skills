---
title: _DIR_META.md - Presentation Architect
version: V10.0
date: 2026-04-01
status: Active
author: Mentat
---

# _DIR_META.md - Presentation Architect

## 1. Vision (架构愿景)
"Narrative is Asset x Semantic Invariance x Native Forging" (V10.0: Native Rendering Edition). 
作为核心的“决策叙事引擎”，旨在通过“逻辑湖思考画布”、“Action Titles 硬约束”与“医疗垂直红队审计”，将碎片化的原始信息转化为具备咨询级质量、符合行业合规性、逻辑自洽且视觉美学统一的高管级演示文稿，且严格遵守物理区域隔离原则。

## 2. Directory Index (成员索引)
*   **SKILL.md**: 核心 SOP、指令清单与维护协议 (V10.0)。
*   **references/**: [Knowledge Base] 包含布局、风格、内容规范、图表准则等深度知识资产。
    *   `blueprint-template.md`: 顶级交付蓝图模板。
    *   `content-rules.md`: 咨询级内容与风格约束。
    *   `styles/`: 多样化的视觉调色盘。
*   **scripts/**: [Core Engines]
    *   `build-deck.py`: 自动化组装引擎。强制要求输入文件为 `outline.md`。
    *   `generate-images.py`: AI 驱动的视觉素材生成器。
    *   `validator.py`: 物理与叙事约束审计器。
    *   `layout_engine.py`: 动态布局渲染引擎。

## 3. Maintenance Trigger (维护触发器)
*   新增布局或风格时，更新 `references/` 并同步 `SKILL.md`。
*   脚本参数变更时，强制更新 `SKILL.md` 中的 `Golden Path` 及脚本 Header。
*   ⚠️ **Protocol**: 所有的 PPT 组装必须在独立的物理沙箱 `C:\Users\shich\.gemini\slide-deck\{Topic}_{Date}\` 中完成。最终的蓝图资产必须被严格命名为 `outline.md` 才能被 `build-deck.py` 成功解析。
