---
name: skill-creator
description: 创建与升级 Gemini 技能的核心指南。作为 GEB-Flow 协议的守护者，确保新技能具备“分形自描述”与“渐进式披露”的高级架构标准。
---

# Skill Creator (GEB-Flow Edition)

定义并初始化具有“分形共鸣”能力的技能模块。

## 1. About Skills
技能是模块化的自描述文件夹，通过确定性逻辑（Scripts）与启发式引导（Markdown）扩展 Gemini 的能力边界。

## 2. Core Axioms (核心公理)
*   **Root Authority**: 每一个技能目录必须包含 `_DIR_META.md`。
*   **Fractal Integrity**: 每一个脚本必须以 Standard Header 开始。
*   **Lagged Sync**: 逻辑变更必须回溯更新文档。

## 3. Skill Anatomy (技能解剖学)
一个标准的 GEB-Flow 技能包含以下结构：
- `_DIR_META.md`: [Required] 目录架构愿景与成员索引。
- `SKILL.md`: [Required] 指令清单、触发逻辑与维护协议。
- `scripts/`: [Bundled] 确定性执行逻辑（Python/Shell）。
- `references/`: [Knowledge] 详细的 API、规范或本体指南（用于渐进式披露）。
- `agents/`: [UI] `gemini.yaml` 标识。

## 4. Initiation Workflow

### Step 1: Initialize
使用升级后的引擎一键创建骨架：
```bash
python scripts/init_skill.py <skill-name> --path <output-path> --resources scripts,references --examples
```

### Step 2: Edit & Refine
1.  **Define Vision**: 在 `_DIR_META.md` 中描述其系统地位。
2.  **Logic Injection**: 编写 `scripts/` 下的代码，**严禁省略 Header**。
3.  **Instruction Design**: 在 `SKILL.md` 中定义核心 SOP。

### Step 3: Validate
运行校验工具检查合规性：
```bash
python scripts/quick_validate.py <path/to/skill>
```

## 5. Maintenance Protocol
任何影响 API 接口、数据结构或核心工作流的修改，**必须**同步更新：
1.  脚本内的 `@Input/@Output` Header。
2.  `_DIR_META.md` 中的成员索引（若文件变更）。
3.  `SKILL.md` 中的用法示例。
