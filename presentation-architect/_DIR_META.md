---
title: _DIR_META.md - Presentation Architect
date: 2026-02-20
status: Active
author: antigravity
---

# _DIR_META.md - Presentation Architect

## 1. Vision (架构愿景)
作为 V2.0 战略操作系统内核心的“决策叙事引擎”，旨在通过“逻辑湖联结”、“Action Titles 硬约束”与“医疗垂直红队审计”，将碎片化的原始信息转化为具备咨询级质量、符合行业合规性、逻辑自洽且视觉美学统一的高管级演示文稿，且严格遵守物理区域隔离原则。

## 2. Directory Index (成员索引)
*   **SKILL.md**: 核心 SOP、指令清单与维护协议。
*   **references/**: [Knowledge Base] 包含布局、风格、内容规范、图表准则等深度知识资产。
    *   `blueprint-template.md`: 顶级交付蓝图模板。
    *   `content-rules.md`: 咨询级内容与风格约束。
    *   `styles/`: 多样化的视觉调色盘。
*   **scripts/**: [Core Engines]
    *   `build-deck.py`: 自动化组装引擎。
    *   `generate-images.py`: AI 驱动的视觉素材生成器。
    *   `merge-to-pptx.ts`: 物理层合并脚本。
*   **agents/**: 环境元数据声明。

## 3. Maintenance Trigger (维护触发器)
*   新增布局或风格时，更新 `references/` 并同步 `SKILL.md`。
*   脚本参数变更时，强制更新 `SKILL.md` 中的 `Golden Path` 及脚本 Header。
