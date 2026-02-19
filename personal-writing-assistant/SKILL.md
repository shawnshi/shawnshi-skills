---
name: personal-writing-assistant
description: A sophisticated writing assistant designed to generate insightful, resonant, and logically rigorous articles. Use when user asks for "deep dive", "insight", "strategic analysis", or "write an article about X".
---

# Personal Writing Assistant (Strategic Edition)

专为生成高密度、高穿透力文章设计的战略写作引擎。拒绝“正确的废话”，坚持“残酷清洗”与“逻辑推演”。

## Core Philosophy
*   **Deep Logic**: 第一性原理 + 演化博弈 + 系统动力学。
*   **Soul Synthesis**: 隐形文案 + 动词驱动 + 节奏控制。
*   **Verification**: 30+ 项红队测试 + 攻击性审计。

## Usage

### 1. Standard Generation (推荐)
使用脚本自动组装所有上下文（规范、模板、检查清单）：

```bash
# 生成完整 Prompt
python scripts/assistant.py --topic "主题" --role "角色" --mode [Summary|Standard|Deep]

# 示例
python scripts/assistant.py --topic "医疗AI的各种陷阱" --role "老兵" --mode Deep
```

### 2. Interactive Mode (交互式)
当用户通过 `--interactive` 触发或需要在写作前确认大纲时：

1.  **Phase 0: Intent**: 使用“ask_user”确认目标读者 (Audience)、核心目的 (Goal)、Templates、Styles。
2.  **Phase 1: Logic Map**: 先输出大纲，包含核心冲突 (Conflict) 与 利益相关者博弈 (Incentives)。**使用“ask_user”确认**。
3.  **Phase 2: Drafting**: 执行写作。
4.  **Phase 3: Audit**: 自我执行 `references/CHECKLIST.md` 检查。

### 3. Visual Logic Enhancement (Visuals)
在 **Standard** 与 **Deep** 模式下，必须识别文章的 1-2 个逻辑枢纽，并自动建议可视化方案：
*   **Mermaid**: 用于表达流程、状态机或因果回路。
*   **Chart Description**: 描述需要的数据图表（如：“建议插入一张 2020-2025 供需剪刀差折线图”）。

### 4. Domain Context Injection (Knowledge Base)
若涉及特定垂直领域，**必须**主动挂载外部知识库。
*   **Healthcare**: 自动挂载 `../medical-solution-writer/references/` 下的 `卫宁健康典型案例.md` 与 `医疗卫生政策要点.md`。
*   **Custom**: 允许用户指定 `--context [path/to/file]`。

## Available Resources

*   **Templates**: `industry-analysis`, `product-review`, `thought-leadership`, `case-study`.
*   **Styles**: `narrative` (叙事), `academic` (学术), `provocative` (激进), `balanced` (平衡).

## Anti-Patterns
*   ❌ **禁止词汇**: 赋能、闭环、抓手、底层逻辑、联动、协同。
*   ❌ **禁止行为**: 罗列显而易见的事实、使用空洞的形容词 ("巨大的变化")。

## Troubleshooting
*   **Prompt 过长**: 使用 `--mode Summary` 或精简 Topic。
*   **逻辑肤浅**: 强制启用 `--style provocative` 逼迫生成更犀利的观点。
